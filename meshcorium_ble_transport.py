from __future__ import annotations

import asyncio
import logging
import platform
import queue
import shutil
import subprocess
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any


BLE_TRANSPORT_TYPE = "ble"
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
BLE_NAME_PREFIXES = ("MeshCore-", "Whisper-")


try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # BLE remains an optional transport until the adapter is complete.
    BleakClient = None
    BleakScanner = None


class BleTransportUnavailable(ValueError):
    pass


class BleTransportError(ValueError):
    pass


class BleFrameTransport:
    """Synchronous MeshCore frame transport over BLE Nordic UART Service."""

    def __init__(
        self,
        *,
        address: str,
        timeout: float = 4.0,
        adapter_id: str = "",
        pin: str = "",
        frame_error=BleTransportError,
    ):
        if BleakClient is None:
            raise BleTransportUnavailable("Python package 'bleak' is not installed")
        _ensure_bluez_available()
        self.port = str(address or "").strip()
        if not self.port:
            raise BleTransportUnavailable("BLE device address is required")
        self.timeout = max(0.1, float(timeout or 4.0))
        self.adapter_id = str(adapter_id or "").strip()
        self.pin = str(pin or "").strip()
        self._frame_error = frame_error
        self._frames: queue.Queue[bytes] = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._connect_error: Exception | None = None
        self._client = None
        self._rx_char = None
        self._write_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"meshcorium-ble-loop:{self.port}",
            daemon=True,
        )
        self._thread.start()
        try:
            self._submit(self._connect()).result(timeout=max(5.0, self.timeout + 5.0))
        except FutureTimeoutError as exc:
            self.close()
            raise BleTransportUnavailable("BLE connect timed out before NUS became ready") from exc
        if self._connect_error is not None:
            raise self._connect_error
        if not self._ready.is_set():
            raise BleTransportUnavailable("BLE transport did not become ready")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coroutine):
        if self._closed.is_set():
            raise self._frame_error("BLE transport is closed")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    async def _connect(self) -> None:
        client_kwargs: dict[str, object] = {"disconnected_callback": self._on_disconnect}
        if self.adapter_id:
            client_kwargs["bluez"] = {"adapter": self.adapter_id}
        scanner_kwargs: dict[str, object] = {}
        if self.adapter_id:
            scanner_kwargs["bluez"] = {"adapter": self.adapter_id}
        try:
            logging.info("ble transport resolving device address=%s adapter=%s", self.port, self.adapter_id or "-")
            resolve_timeout = max(3.0, min(self.timeout, 10.0))
            device = await _resolve_ble_device_by_address_async(
                self.port,
                timeout=resolve_timeout,
                adapter_id=self.adapter_id,
            )
            if device is None:
                device = await BleakScanner.find_device_by_address(
                    self.port,
                    timeout=resolve_timeout,
                    **scanner_kwargs,
                )
            if device is None:
                raise BleTransportUnavailable(f"BLE device {self.port} was not found during pre-connect scan")
            self._client = BleakClient(device, **client_kwargs)
        except TypeError as exc:
            if self.adapter_id:
                raise BleTransportUnavailable(
                    f"installed bleak does not support explicit BlueZ adapter selection: {exc}"
                ) from exc
            raise
        try:
            logging.info("ble transport connect start address=%s adapter=%s", self.port, self.adapter_id or "-")
            await self._client.connect(timeout=max(5.0, self.timeout))
            logging.info("ble transport connected address=%s", self.port)
            if self.pin:
                try:
                    logging.info("ble transport pairing requested address=%s", self.port)
                    await self._client.pair()
                    logging.info("ble transport pairing completed address=%s", self.port)
                except Exception:
                    # Already-paired devices and BlueZ agents can report benign pairing errors.
                    logging.info("ble transport pairing skipped/failed address=%s", self.port, exc_info=True)
            services = self._client.services
            service = services.get_service(NUS_SERVICE_UUID) if services is not None else None
            if service is None:
                try:
                    services = await self._client.get_services()
                    service = services.get_service(NUS_SERVICE_UUID)
                except AttributeError:
                    service = None
            if service is None:
                raise BleTransportUnavailable("MeshCore NUS service not found")
            tx_char = service.get_characteristic(NUS_TX_CHAR_UUID)
            if tx_char is None:
                raise BleTransportUnavailable("MeshCore NUS TX characteristic not found")
            logging.info("ble transport start notify address=%s char=%s", self.port, NUS_TX_CHAR_UUID)
            await self._client.start_notify(tx_char, self._on_notify)
            rx_char = service.get_characteristic(NUS_RX_CHAR_UUID)
            if rx_char is None:
                raise BleTransportUnavailable("MeshCore NUS RX characteristic not found")
            self._rx_char = rx_char
            logging.info("ble transport ready address=%s service=%s rx=%s tx=%s", self.port, NUS_SERVICE_UUID, NUS_RX_CHAR_UUID, NUS_TX_CHAR_UUID)
            self._ready.set()
        except Exception as exc:
            self._connect_error = BleTransportUnavailable(_format_ble_exception(exc))
            logging.warning("ble transport connect failed address=%s error=%s", self.port, self._connect_error)
            self._ready.set()
            try:
                if self._client is not None:
                    await self._client.disconnect()
            except Exception:
                pass

    def _on_disconnect(self, _client) -> None:
        logging.warning("ble transport disconnected address=%s", self.port)
        self._closed.set()
        self._frames.put(b"")

    def _on_notify(self, _characteristic, data: bytearray) -> None:
        payload = bytes(data or b"")
        if payload:
            self._frames.put(payload)

    async def _write_async(self, payload: bytes) -> None:
        if self._client is None or not getattr(self._client, "is_connected", False):
            raise self._frame_error("BLE device is not connected")
        if self._rx_char is None:
            raise self._frame_error("MeshCore NUS RX characteristic is not ready")
        await self._client.write_gatt_char(self._rx_char, bytes(payload), response=True)

    def read_frame(self) -> bytes:
        while not self._closed.is_set():
            try:
                frame = self._frames.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise self._frame_error("ble timeout while reading frame") from exc
            if frame:
                return frame
            if self._closed.is_set():
                break
        raise self._frame_error("BLE transport is closed")

    def write_frame(self, payload: bytes) -> None:
        if self._closed.is_set():
            raise self._frame_error("BLE transport is closed")
        with self._write_lock:
            self._submit(self._write_async(bytes(payload))).result(timeout=max(5.0, self.timeout + 5.0))

    def reset_input_buffer(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def reset_output_buffer(self) -> None:
        return

    def cancel_read(self) -> None:
        self._frames.put(b"")

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._frames.put(b"")
        if self._loop.is_running():
            if self._client is not None:
                try:
                    asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop).result(timeout=2.0)
                except Exception:
                    pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        try:
            self._loop.close()
        except Exception:
            pass


@dataclass(frozen=True)
class BleDeviceInfo:
    address: str
    name: str
    rssi: int | None = None
    adapter_id: str = ""
    service_uuids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        label = self.name or self.address
        payload: dict[str, object] = {
            "transport_type": BLE_TRANSPORT_TYPE,
            "transport_id": self.address,
            "device": self.address,
            "address": self.address,
            "name": self.name,
            "display_label": label,
            "description": label,
            "service_uuid": NUS_SERVICE_UUID,
        }
        if self.rssi is not None:
            payload["rssi"] = self.rssi
        if self.adapter_id:
            payload["adapter_id"] = self.adapter_id
        if self.service_uuids:
            payload["service_uuids"] = list(self.service_uuids)
        return payload


def _normalize_uuid(value: object) -> str:
    return str(value or "").strip().lower()


def _is_meshcore_ble_candidate(name: str, service_uuids: list[str]) -> bool:
    normalized_name = str(name or "")
    if any(normalized_name.startswith(prefix) for prefix in BLE_NAME_PREFIXES):
        return True
    return NUS_SERVICE_UUID in {_normalize_uuid(item) for item in service_uuids}


def _format_ble_exception(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "no bluetooth adapters found" in lowered:
        return "No Linux Bluetooth adapters found (hci0/hci1 missing, disabled, or blocked)"
    if "operation not permitted" in lowered and "system scope bus" in lowered:
        return "BlueZ D-Bus access denied while checking bluetooth.service"
    return message


def _ensure_bluez_available() -> None:
    if platform.system().lower() != "linux":
        return
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return
    try:
        result = subprocess.run(
            [systemctl, "is-active", "bluetooth.service"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    state = str(result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        raise BleTransportUnavailable(f"BlueZ bluetooth.service is not active ({state or 'unknown'})")


async def _discover_ble_devices_async(*, timeout: float, adapter_id: str = "") -> list[dict[str, object]]:
    if BleakScanner is None:
        raise BleTransportUnavailable("Python package 'bleak' is not installed")
    _ensure_bluez_available()

    timeout = max(1.0, float(timeout or 5.0))
    adapter_id = str(adapter_id or "").strip()
    devices: dict[str, BleDeviceInfo] = {}

    def on_detect(device: Any, advertisement_data: Any) -> None:
        address = str(getattr(device, "address", "") or "").strip()
        if not address:
            return
        name = str(
            getattr(advertisement_data, "local_name", "")
            or getattr(device, "name", "")
            or ""
        ).strip()
        service_uuids = [
            _normalize_uuid(item)
            for item in list(getattr(advertisement_data, "service_uuids", []) or [])
            if _normalize_uuid(item)
        ]
        if not _is_meshcore_ble_candidate(name, service_uuids):
            return
        rssi = getattr(advertisement_data, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)
        devices[address] = BleDeviceInfo(
            address=address,
            name=name,
            rssi=int(rssi) if rssi is not None else None,
            adapter_id=adapter_id,
            service_uuids=tuple(service_uuids),
        )

    scanner_kwargs: dict[str, object] = {}
    if adapter_id:
        scanner_kwargs["bluez"] = {"adapter": adapter_id}

    try:
        async with BleakScanner(detection_callback=on_detect, **scanner_kwargs):
            await asyncio.sleep(timeout)
    except TypeError as exc:
        if adapter_id:
            raise BleTransportUnavailable(
                f"installed bleak does not support explicit BlueZ adapter selection: {exc}"
            ) from exc
        raise
    except Exception as exc:
        raise BleTransportUnavailable(_format_ble_exception(exc)) from exc

    return [
        item.to_dict()
        for item in sorted(
            devices.values(),
            key=lambda device: (device.name.lower(), device.address.lower()),
        )
    ]


async def _resolve_ble_device_by_address_async(
    address: str,
    *,
    timeout: float,
    adapter_id: str = "",
) -> Any | None:
    """Resolve a BLEDevice using the same scanner path as discovery.

    BlueZ can be flaky with ``find_device_by_address`` for random-address BLE
    peripherals while a plain callback scan still sees the advertisement.
    """

    if BleakScanner is None:
        raise BleTransportUnavailable("Python package 'bleak' is not installed")
    address = str(address or "").strip().lower()
    if not address:
        return None
    timeout = max(1.0, float(timeout or 5.0))
    adapter_id = str(adapter_id or "").strip()
    found: dict[str, Any] = {}
    ready = asyncio.Event()

    def on_detect(device: Any, _advertisement_data: Any) -> None:
        candidate_address = str(getattr(device, "address", "") or "").strip().lower()
        if candidate_address == address:
            found["device"] = device
            ready.set()

    scanner_kwargs: dict[str, object] = {}
    if adapter_id:
        scanner_kwargs["bluez"] = {"adapter": adapter_id}

    try:
        async with BleakScanner(detection_callback=on_detect, **scanner_kwargs):
            try:
                await asyncio.wait_for(ready.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return None
    except TypeError as exc:
        if adapter_id:
            raise BleTransportUnavailable(
                f"installed bleak does not support explicit BlueZ adapter selection: {exc}"
            ) from exc
        raise
    except Exception as exc:
        raise BleTransportUnavailable(_format_ble_exception(exc)) from exc

    return found.get("device")


def discover_ble_devices(*, timeout: float = 5.0, adapter_id: str = "") -> list[dict[str, object]]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_discover_ble_devices_async(timeout=timeout, adapter_id=adapter_id))
    raise BleTransportUnavailable("BLE discovery cannot run inside an existing asyncio event loop")
