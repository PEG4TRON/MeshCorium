from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import queue
import select
import shlex
import shutil
import subprocess
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from meshcorium_serial_transport import TRANSPORT_FRAME_TIMEOUT_ERROR


BLE_TRANSPORT_TYPE = "ble"
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
BLE_NAME_PREFIXES = ("MeshCore-", "Whisper-")
BLE_ADDRESS_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$", re.IGNORECASE)
BLE_DEVICE_CACHE_TTL_SECS = 120.0
_BLE_DEVICE_CACHE_LOCK = threading.Lock()
_BLE_DEVICE_CACHE: dict[str, tuple[float, Any]] = {}
_BLE_ACTIVE_TRANSPORTS_LOCK = threading.Lock()
_BLE_ACTIVE_TRANSPORTS: dict[str, object] = {}
_BLE_CONNECTING_TRANSPORTS_LOCK = threading.Lock()
_BLE_CONNECTING_TRANSPORTS: dict[str, set[object]] = {}
_BLE_CONNECTION_GENERATIONS_LOCK = threading.Lock()
_BLE_CONNECTION_GENERATIONS: dict[str, int] = {}


try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
except ImportError:  # BLE remains an optional transport until the adapter is complete.
    BleakClient = None
    BleakScanner = None
    BLEDevice = None

try:
    import dbus
except ImportError:
    dbus = None


class BleTransportUnavailable(ValueError):
    pass


class BleTransportError(ValueError):
    pass


_BLUETOOTHCTL_PASSKEY_PROMPTS = (
    "enter pin code",
    "enter passkey",
    "request passkey",
    "requestpasskey",
    "requestpin",
    "input pin code",
)
_BLUETOOTHCTL_CONFIRM_PROMPTS = (
    "confirm passkey",
    "confirm value",
    "requestconfirmation",
    "[agent] confirm",
    "authorize service",
    "accept pairing",
)
_BLUETOOTHCTL_SUCCESS_MARKERS = (
    "pairing successful",
    "trust succeeded",
    "already paired",
)
_BLUETOOTHCTL_FAILURE_MARKERS = (
    "authentication failed",
    "authenticationfailed",
    "failed to pair",
    "not available",
    "timed out",
    "org.bluez.error",
)


class _BluetoothctlAgentSession:
    def __init__(self, *, address: str, pin: str = "", adapter_id: str = "", purpose: str = "connect"):
        self.address = str(address or "").strip()
        self.pin = re.sub(r"\D+", "", str(pin or "").strip())
        self.adapter_id = str(adapter_id or "").strip()
        self.purpose = str(purpose or "connect").strip() or "connect"
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._detector_buffer = ""
        self._lock = threading.Lock()
        self.passkey_requested = False
        self.confirmation_requested = False
        self.pin_sent = False
        self.no_pin_available = False
        self.passkey_reprompted = False
        self.request_canceled = False

    def start(self, *, ready_timeout: float = 3.0) -> bool:
        if platform.system().lower() != "linux":
            return False
        if self._process is not None:
            return True
        try:
            self._process = subprocess.Popen(
                [_bluetoothctl_binary()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
            )
        except (OSError, subprocess.TimeoutExpired):
            self._process = None
            return False
        self._thread = threading.Thread(
            target=self._run,
            name=f"meshcorium-bluetoothctl-agent:{self.purpose}:{self.address}",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=max(0.5, float(ready_timeout or 3.0)))
        logging.info(
            "ble connect agent session started address=%s purpose=%s ready=%s",
            self.address,
            self.purpose,
            self._ready.is_set(),
        )
        return True

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                self._write_cmd("quit")
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._process = None
        self._thread = None

    def auth_state(self) -> dict[str, bool]:
        return {
            "passkey_requested": self.passkey_requested,
            "confirmation_requested": self.confirmation_requested,
            "pin_sent": self.pin_sent,
            "no_pin_available": self.no_pin_available,
            "passkey_reprompted": self.passkey_reprompted,
            "request_canceled": self.request_canceled,
        }

    def _write_cmd(self, command: str) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        with self._lock:
            process.stdin.write(f"{command}\n".encode("utf-8"))
            process.stdin.flush()

    def _run(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        prompt_seen = False
        adapter_selected = not bool(self.adapter_id)
        power_requested = False
        agent_requested = False
        agent_ready = False
        default_agent_requested = False
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
            except Exception:
                break
            if not ready:
                if process.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(process.stdout.fileno(), 4096)
            except Exception:
                break
            if not chunk:
                if process.poll() is not None:
                    break
                continue
            decoded = chunk.decode("utf-8", errors="ignore")
            if not decoded:
                continue
            if "]>" in decoded or decoded.rstrip().endswith(">"):
                prompt_seen = True
            self._detector_buffer += decoded.lower()
            if len(self._detector_buffer) > 4096:
                self._detector_buffer = self._detector_buffer[-4096:]
            lowered = self._detector_buffer
            for raw_line in decoded.splitlines():
                stripped = raw_line.strip()
                if stripped:
                    logging.info(
                        "ble connect agent line address=%s purpose=%s line=%s",
                        self.address,
                        self.purpose,
                        stripped,
                    )
            if prompt_seen and self.adapter_id and not adapter_selected:
                self._write_cmd(f"select {self.adapter_id}")
                adapter_selected = True
                continue
            if prompt_seen and not power_requested:
                self._write_cmd("power on")
                power_requested = True
                continue
            if prompt_seen and not agent_requested:
                self._write_cmd("agent KeyboardDisplay")
                agent_requested = True
                continue
            if "agent registered" in lowered or "agent is already registered" in lowered:
                agent_ready = True
                self._ready.set()
                if not default_agent_requested:
                    self._write_cmd("default-agent")
                    default_agent_requested = True
                self._detector_buffer = ""
                continue
            if "default agent request successful" in lowered:
                self._ready.set()
                self._detector_buffer = ""
                continue
            if "failed to register agent object" in lowered or "no agent is registered" in lowered:
                agent_requested = False
                agent_ready = False
                default_agent_requested = False
                self._detector_buffer = ""
                continue
            if any(prompt in lowered for prompt in _BLUETOOTHCTL_PASSKEY_PROMPTS):
                self.passkey_requested = True
                self.request_canceled = True
                if not self.pin:
                    self.no_pin_available = True
                    logging.warning(
                        "ble connect agent passkey requested without pin address=%s purpose=%s; cancelling prompt",
                        self.address,
                        self.purpose,
                    )
                else:
                    logging.warning(
                        "ble connect agent passkey requested during regular connect address=%s purpose=%s; deferring to bond-repair flow",
                        self.address,
                        self.purpose,
                    )
                self._write_cmd("cancel")
                self._detector_buffer = ""
                continue
            if any(prompt in lowered for prompt in _BLUETOOTHCTL_CONFIRM_PROMPTS):
                self.confirmation_requested = True
                self._write_cmd("yes")
                self._detector_buffer = ""
                continue
            if "request canceled" in lowered:
                self.request_canceled = True
                self._detector_buffer = ""
                continue
            if agent_ready and not self._ready.is_set():
                self._ready.set()


class BleFrameTransport:
    """Synchronous MeshCore frame transport over BLE Nordic UART Service."""

    transport_type = BLE_TRANSPORT_TYPE

    def __init__(
        self,
        *,
        address: str,
        timeout: float = 4.0,
        adapter_id: str = "",
        pin: str = "",
        allow_bond_repair: bool = False,
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
        self._allow_bond_repair = bool(allow_bond_repair)
        self._frame_error = frame_error
        self._frames: queue.Queue[bytes] = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._connecting = threading.Event()
        self._connect_error: Exception | None = None
        self._connect_stage = "init"
        self._client = None
        self._rx_char = None
        self._active_token = object()
        self._connection_generation = 0
        self._write_lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"meshcorium-ble-loop:{self.port}",
            daemon=True,
        )
        self._thread.start()
        connect_future = None
        try:
            connect_budget = max(64.0, self.timeout + 54.0)
            if self.pin:
                connect_budget = max(connect_budget, self.timeout + 60.0, 70.0)
            connect_future = self._submit(self._connect())
            connect_future.result(timeout=connect_budget)
        except FutureTimeoutError as exc:
            if connect_future is not None:
                connect_future.cancel()
                try:
                    connect_future.result(timeout=1.0)
                except Exception:
                    pass
            self.close()
            _schedule_ble_soft_disconnect(
                address=self.port,
                timeout=max(4.0, self.timeout + 2.0),
                adapter_id=self.adapter_id,
                generation=self._connection_generation,
            )
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

    def _set_connect_stage(self, stage: str, **details: object) -> None:
        self._connect_stage = str(stage or "").strip() or "unknown"
        payload = " ".join(f"{key}={value}" for key, value in details.items() if value not in (None, ""))
        if payload:
            logging.info("ble transport stage address=%s stage=%s %s", self.port, self._connect_stage, payload)
        else:
            logging.info("ble transport stage address=%s stage=%s", self.port, self._connect_stage)

    async def _get_nus_service(self):
        self._set_connect_stage("resolve-services")
        services = self._client.services
        service = services.get_service(NUS_SERVICE_UUID) if services is not None else None
        if service is not None:
            return service
        for attempt in (1, 2):
            try:
                self._set_connect_stage("get-services", attempt=attempt)
                services = await self._client.get_services()
                service = services.get_service(NUS_SERVICE_UUID)
            except AttributeError:
                service = None
            if service is not None:
                return service
            if attempt == 1:
                await asyncio.sleep(0.35)
        raise BleTransportUnavailable("MeshCore NUS service not found")

    async def _start_notify_with_retry(self, tx_char) -> None:
        for attempt in (1, 2):
            try:
                self._set_connect_stage("start-notify", attempt=attempt, char=NUS_TX_CHAR_UUID)
                await self._client.start_notify(tx_char, self._on_notify)
                return
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.35)

    async def _connect_client(self, *, timeout: float, use_cache: bool = False) -> None:
        connect_kwargs: dict[str, object] = {"timeout": timeout}
        if use_cache:
            connect_kwargs["dangerous_use_bleak_cache"] = True
        await asyncio.wait_for(
            self._client.connect(**connect_kwargs),
            timeout=max(2.0, timeout + 1.0),
        )

    async def _disconnect_existing_bluez_link_before_connect(self, *, timeout: float) -> None:
        self._set_connect_stage("bluez-active-link-disconnect", adapter=self.adapter_id or "-")
        before = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
        logging.warning(
            "ble transport disconnecting pre-existing BlueZ active link address=%s adapter=%s paired=%s bonded=%s trusted=%s connected=%s",
            self.port,
            self.adapter_id or "-",
            bool(before.get("paired")),
            bool(before.get("bonded")),
            bool(before.get("trusted")),
            bool(before.get("connected")),
        )
        await asyncio.to_thread(
            _disconnect_ble_device_via_dbus,
            address=self.port,
            adapter_id=self.adapter_id,
        )
        disconnected = await asyncio.to_thread(
            _wait_for_bluez_device_disconnected,
            address=self.port,
            timeout=max(2.0, min(float(timeout or 6.0), 8.0)),
            adapter_id=self.adapter_id,
        )
        after = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
        logging.info(
            "ble transport pre-connect BlueZ active link state-after address=%s adapter=%s connected=%s disconnected=%s paired=%s trusted=%s",
            self.port,
            self.adapter_id or "-",
            bool(after.get("connected")),
            disconnected,
            bool(after.get("paired") or after.get("bonded")),
            bool(after.get("trusted")),
        )
        if not disconnected:
            raise BleTransportUnavailable("BLE BlueZ active link did not disconnect before Meshcorium connect")

    async def _close_client_quietly(self) -> None:
        client = self._client
        self._client = None
        self._rx_char = None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    def _should_attempt_trust_repair(self, exc: Exception) -> bool:
        if not self.pin:
            return False
        if _has_active_ble_transport(self.port):
            return False
        message = _format_ble_exception(exc).lower()
        bluez_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
        pairing_present = bool(
            bluez_state.get("paired")
            or bluez_state.get("bonded")
            or bluez_state.get("trusted")
            or bluez_state.get("connected")
        )
        paired = bool(bluez_state.get("paired") or bluez_state.get("bonded"))
        trusted = bool(bluez_state.get("trusted"))
        if not pairing_present or trusted or not paired:
            return False
        trust_markers = (
            "authentication failed",
            "authenticationfailed",
            "not permitted",
            "not paired",
            "failed to pair",
            "pairing failed",
            "att error",
            "unlikely error",
            "not connected",
            "nordic uart",
        )
        return any(marker in message for marker in trust_markers)

    def _should_attempt_bond_repair(self, exc: Exception) -> bool:
        if not self._allow_bond_repair or not self.pin:
            return False
        if _has_active_ble_transport(self.port):
            return False
        message = _format_ble_exception(exc).lower()
        bluez_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
        pairing_present = bool(
            bluez_state.get("paired")
            or bluez_state.get("bonded")
            or bluez_state.get("trusted")
            or bluez_state.get("connected")
        )
        if not pairing_present and (
            "pairing failed" in message or "automatic ble pairing failed" in message
        ):
            return False
        skip_markers = (
            "python package 'bleak' is not installed",
            "bluetooth.service is not active",
            "d-bus access denied",
            "no linux bluetooth adapters found",
            "bluetoothctl is required",
            "not discoverable right now",
            "not found during pre-connect scan",
        )
        if any(marker in message for marker in skip_markers):
            return False
        auth_failure_markers = (
            "failed to pair",
            "pairing failed",
            "automatic ble pairing failed",
            "trust repair did not complete",
        )
        if pairing_present:
            return _is_stale_ble_bond_error_message(message) or any(marker in message for marker in auth_failure_markers)
        return _is_stale_ble_bond_error_message(message) or any(marker in message for marker in auth_failure_markers)

    async def _attempt_trust_repair(self, *, failure_message: str) -> None:
        self._set_connect_stage("trust-repair-start", adapter=self.adapter_id or "-")
        logging.warning(
            "ble trust repair start address=%s adapter=%s error=%s",
            self.port,
            self.adapter_id or "-",
            failure_message or "-",
        )
        await asyncio.to_thread(
            _repair_ble_trust_via_bluetoothctl,
            address=self.port,
            timeout=max(10.0, self.timeout + 10.0),
            adapter_id=self.adapter_id,
            failure_message=failure_message,
        )
        self.reset_input_buffer()
        self._set_connect_stage("trust-repair-reconnect", adapter=self.adapter_id or "-")

    async def _attempt_bond_repair(self, *, failure_message: str) -> None:
        self._set_connect_stage("bond-repair-start", adapter=self.adapter_id or "-")
        logging.warning(
            "ble bond repair start address=%s adapter=%s error=%s",
            self.port,
            self.adapter_id or "-",
            failure_message or "-",
        )
        await asyncio.to_thread(
            _repair_ble_bond_via_bluetoothctl,
            address=self.port,
            pin=self.pin,
            timeout=max(16.0, self.timeout + 18.0),
            adapter_id=self.adapter_id,
            failure_message=failure_message,
        )
        self.reset_input_buffer()
        self._set_connect_stage("bond-repair-reconnect", adapter=self.adapter_id or "-")

    async def _connect(self) -> None:
        self._connecting.set()
        self._connection_generation = _bump_ble_connection_generation(self.port)
        _register_connecting_ble_transport(self.port, self._active_token)
        try:
            bond_repair_attempted = False
            trust_repair_attempted = False
            preexisting_link_reset_attempted = False
            client_kwargs: dict[str, object] = {"disconnected_callback": self._on_disconnect}
            if self.adapter_id:
                client_kwargs["bluez"] = {"adapter": self.adapter_id}
            while True:
                reuse_existing_connection = False
                bluez_paired = False
                bluez_bonded = False
                bluez_trusted = False
                bluez_connected = False
                try:
                    bluez_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
                    bluez_paired = bool(bluez_state.get("paired"))
                    bluez_bonded = bool(bluez_state.get("bonded"))
                    bluez_trusted = bool(bluez_state.get("trusted"))
                    bluez_connected = bool(bluez_state.get("connected"))
                    bluez_uuids = {_normalize_uuid(item) for item in bluez_state.get("uuids") or []}
                    bluez_pairing_present = bool(bluez_paired or bluez_bonded or bluez_trusted or bluez_connected)
                    if bluez_pairing_present:
                        reuse_existing_connection = True
                        if bluez_connected:
                            preexisting_link_reset_attempted = True
                            await self._disconnect_existing_bluez_link_before_connect(
                                timeout=max(6.0, min(self.timeout + 2.0, 10.0)),
                            )
                            bluez_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
                            bluez_paired = bool(bluez_state.get("paired"))
                            bluez_bonded = bool(bluez_state.get("bonded"))
                            bluez_trusted = bool(bluez_state.get("trusted"))
                            bluez_connected = bool(bluez_state.get("connected"))
                            bluez_uuids = {_normalize_uuid(item) for item in bluez_state.get("uuids") or []}
                        self._set_connect_stage(
                            "reuse-paired-device" if not bluez_connected else "reuse-connected-device",
                            adapter=self.adapter_id or "-",
                        )
                        logging.info(
                            "ble transport reusing BlueZ cached device address=%s adapter=%s paired=%s bonded=%s trusted=%s connected=%s nus_known=%s",
                            self.port,
                            self.adapter_id or "-",
                            bluez_paired,
                            bluez_bonded,
                            bluez_trusted,
                            bluez_connected,
                            NUS_SERVICE_UUID in bluez_uuids,
                        )
                        reuse_target = await _resolve_ble_client_target_async(
                            self.port,
                            timeout=max(4.0, min(self.timeout + 2.0, 8.0)),
                            adapter_id=self.adapter_id,
                            prefer_bluez_state=True,
                            allow_directed_scan=True,
                            skip_cache=preexisting_link_reset_attempted,
                        )
                        logging.info(
                            "ble transport reuse paired target address=%s source=%s target_type=%s preexisting_link_reset=%s",
                            self.port,
                            _describe_ble_client_target_source(reuse_target),
                            type(reuse_target).__name__ if reuse_target is not None else "address",
                            preexisting_link_reset_attempted,
                        )
                        if reuse_target is not None:
                            self._client = BleakClient(reuse_target, **client_kwargs)
                        else:
                            self._client = BleakClient(self.port, **client_kwargs)
                    else:
                        device = await _resolve_ble_client_target_async(
                            self.port,
                            timeout=max(3.0, min(self.timeout + 1.0, 6.0)),
                            adapter_id=self.adapter_id,
                            prefer_bluez_state=False,
                            allow_directed_scan=False,
                        )
                        if device is not None:
                            self._set_connect_stage("reuse-recent-scan-device", adapter=self.adapter_id or "-")
                            logging.info(
                                "ble transport reusing recently scanned device address=%s adapter=%s",
                                self.port,
                                self.adapter_id or "-",
                            )
                        else:
                            self._set_connect_stage("resolve-device", adapter=self.adapter_id or "-")
                            logging.info("ble transport resolving device address=%s adapter=%s", self.port, self.adapter_id or "-")
                            device = await _resolve_ble_client_target_async(
                                self.port,
                                timeout=max(3.0, min(self.timeout + 1.0, 6.0)),
                                adapter_id=self.adapter_id,
                                prefer_bluez_state=False,
                                allow_directed_scan=False,
                            )
                        if device is None and BLE_ADDRESS_RE.match(self.port):
                            self._set_connect_stage("resolve-device-directed-scan", adapter=self.adapter_id or "-")
                            logging.info(
                                "ble transport directed scan address=%s adapter=%s",
                                self.port,
                                self.adapter_id or "-",
                            )
                            device = await _resolve_ble_client_target_async(
                                self.port,
                                timeout=max(4.0, min(self.timeout + 2.0, 8.0)),
                                adapter_id=self.adapter_id,
                                prefer_bluez_state=False,
                                allow_directed_scan=True,
                            )
                        if device is None:
                            raise BleTransportUnavailable(
                                f"BLE device {self.port} is not discoverable right now. Keep the node advertising and retry."
                            )
                        self._client = BleakClient(device, **client_kwargs)
                except TypeError as exc:
                    if self.adapter_id:
                        raise BleTransportUnavailable(
                            f"installed bleak does not support explicit BlueZ adapter selection: {exc}"
                        ) from exc
                    raise
                connect_agent_session: _BluetoothctlAgentSession | None = None
                try:
                    self._set_connect_stage("connect-start", adapter=self.adapter_id or "-")
                    logging.info("ble transport connect start address=%s adapter=%s", self.port, self.adapter_id or "-")
                    connect_timeout = max(12.0, self.timeout + 8.0)
                    connect_started_at = time.monotonic()
                    logging.info(
                        "ble transport connect attempt address=%s timeout=%s",
                        self.port,
                        round(connect_timeout, 2),
                    )
                    for attempt in (1, 2):
                        try:
                            await self._connect_client(
                                timeout=connect_timeout,
                                use_cache=False,
                            )
                            break
                        except Exception as exc:
                            retry_reason = _ble_connect_retry_reason(exc)
                            if attempt == 2 or not retry_reason:
                                raise
                            self._set_connect_stage(f"connect-retry-after-{retry_reason}", attempt=attempt + 1)
                            logging.warning(
                                "ble transport connect retry after %s address=%s attempt=%s error=%s",
                                retry_reason,
                                self.port,
                                attempt + 1,
                                exc,
                            )
                            await self._close_client_quietly()
                            if retry_reason != "in-progress":
                                await asyncio.to_thread(
                                    _disconnect_ble_device_via_dbus,
                                    address=self.port,
                                    adapter_id=self.adapter_id,
                                )
                                await asyncio.to_thread(
                                    _wait_for_bluez_device_disconnected,
                                    address=self.port,
                                    timeout=4.0,
                                    adapter_id=self.adapter_id,
                                )
                                await asyncio.sleep(0.35)
                            retry_target = await _resolve_ble_client_target_async(
                                self.port,
                                timeout=max(4.0, min(self.timeout + 2.0, 8.0)),
                                adapter_id=self.adapter_id,
                                prefer_bluez_state=retry_reason != "service-discovery-disconnected",
                                allow_directed_scan=True,
                                skip_cache=preexisting_link_reset_attempted
                                or retry_reason == "service-discovery-disconnected",
                            )
                            logging.info(
                                "ble transport retry target address=%s reason=%s source=%s target_type=%s",
                                self.port,
                                retry_reason,
                                _describe_ble_client_target_source(retry_target),
                                type(retry_target).__name__ if retry_target is not None else "address",
                            )
                            if retry_target is not None:
                                self._client = BleakClient(retry_target, **client_kwargs)
                            else:
                                self._client = BleakClient(self.port, **client_kwargs)
                    if getattr(self._client, "is_connected", False):
                        self._closed.clear()
                    logging.info(
                        "ble transport connect attempt completed address=%s elapsed_ms=%s",
                        self.port,
                        int((time.monotonic() - connect_started_at) * 1000),
                    )
                    self._set_connect_stage("connected")
                    logging.info("ble transport connected address=%s", self.port)
                    await asyncio.sleep(0.25)
                    if self.pin:
                        post_connect_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
                        post_connect_paired = bool(post_connect_state.get("paired"))
                        post_connect_bonded = bool(post_connect_state.get("bonded"))
                        post_connect_trusted = bool(post_connect_state.get("trusted"))
                        post_connect_connected = bool(post_connect_state.get("connected"))
                        if post_connect_paired and post_connect_trusted:
                            self._set_connect_stage("pairing-present", adapter=self.adapter_id or "-")
                            logging.info(
                                "ble transport pairing already present address=%s paired=%s bonded=%s trusted=%s connected=%s",
                                self.port,
                                post_connect_paired,
                                post_connect_bonded,
                                post_connect_trusted,
                                post_connect_connected,
                            )
                        elif post_connect_paired or post_connect_bonded:
                            self._set_connect_stage("trust-repair", adapter=self.adapter_id or "-")
                            await asyncio.to_thread(
                                _repair_ble_trust_via_bluetoothctl,
                                address=self.port,
                                timeout=max(10.0, self.timeout + 10.0),
                                adapter_id=self.adapter_id,
                                failure_message="post-connect trust repair",
                            )
                            refreshed_state = _get_bluez_device_state(self.port, adapter_id=self.adapter_id)
                            if not _is_bluez_device_paired_and_trusted(self.port, adapter_id=self.adapter_id):
                                raise BleTransportUnavailable(
                                    "BLE trust repair did not complete"
                                )
                            if not getattr(self._client, "is_connected", False):
                                self._set_connect_stage("trust-repair-reconnect", adapter=self.adapter_id or "-")
                                retry_target = await _resolve_ble_client_target_async(
                                    self.port,
                                    timeout=max(4.0, min(self.timeout + 2.0, 8.0)),
                                    adapter_id=self.adapter_id,
                                    prefer_bluez_state=False,
                                    allow_directed_scan=True,
                                )
                                self._client = BleakClient(retry_target or self.port, **client_kwargs)
                                await self._connect_client(timeout=connect_timeout, use_cache=False)
                            bluez_paired = bool(refreshed_state.get("paired"))
                            bluez_bonded = bool(refreshed_state.get("bonded"))
                            bluez_trusted = bool(refreshed_state.get("trusted"))
                            bluez_connected = bool(refreshed_state.get("connected"))
                        else:
                            self._set_connect_stage("pairing-helper", adapter=self.adapter_id or "-")
                            helper_paired = await asyncio.to_thread(
                                _ensure_ble_pairing_via_bluetoothctl,
                                address=self.port,
                                pin=self.pin,
                                timeout=max(12.0, self.timeout + 14.0),
                                adapter_id=self.adapter_id,
                                allow_no_challenge_fallback=True,
                            )
                            if not helper_paired:
                                self._set_connect_stage("pairing-helper-fallback-no-challenge", adapter=self.adapter_id or "-")
                            elif not _is_bluez_device_paired_and_trusted(self.port, adapter_id=self.adapter_id):
                                raise BleTransportUnavailable("BLE pairing completed without trusted BlueZ state")
                            if helper_paired and not getattr(self._client, "is_connected", False):
                                self._set_connect_stage("pairing-helper-reconnect", adapter=self.adapter_id or "-")
                                retry_target = await _resolve_ble_client_target_async(
                                    self.port,
                                    timeout=max(4.0, min(self.timeout + 2.0, 8.0)),
                                    adapter_id=self.adapter_id,
                                    prefer_bluez_state=False,
                                    allow_directed_scan=True,
                                )
                                self._client = BleakClient(retry_target or self.port, **client_kwargs)
                                await self._connect_client(timeout=connect_timeout, use_cache=False)
                    if platform.system().lower() == "linux":
                        connect_agent_session = _BluetoothctlAgentSession(
                            address=self.port,
                            pin=self.pin,
                            adapter_id=self.adapter_id,
                            purpose="connect",
                        )
                        connect_agent_session.start()
                        self._set_connect_stage("connect-agent-active", adapter=self.adapter_id or "-")
                    service = await self._get_nus_service()
                    self._set_connect_stage("resolve-tx-char")
                    tx_char = service.get_characteristic(NUS_TX_CHAR_UUID)
                    if tx_char is None:
                        raise BleTransportUnavailable("MeshCore NUS TX characteristic not found")
                    logging.info("ble transport start notify address=%s char=%s", self.port, NUS_TX_CHAR_UUID)
                    await self._start_notify_with_retry(tx_char)
                    self._set_connect_stage("resolve-rx-char")
                    rx_char = service.get_characteristic(NUS_RX_CHAR_UUID)
                    if rx_char is None:
                        raise BleTransportUnavailable("MeshCore NUS RX characteristic not found")
                    self._rx_char = rx_char
                    self._set_connect_stage("ready", service=NUS_SERVICE_UUID)
                    logging.info("ble transport ready address=%s service=%s rx=%s tx=%s", self.port, NUS_SERVICE_UUID, NUS_RX_CHAR_UUID, NUS_TX_CHAR_UUID)
                    _register_active_ble_transport(self.port, self._active_token)
                    _unregister_connecting_ble_transport(self.port, self._active_token)
                    self._connecting.clear()
                    self._ready.set()
                    return
                except Exception as exc:
                    if connect_agent_session is not None:
                        agent_state = connect_agent_session.auth_state()
                        if agent_state.get("passkey_requested"):
                            if agent_state.get("no_pin_available"):
                                exc = BleTransportUnavailable(
                                    "current PIN required for existing BLE bond"
                                )
                            elif agent_state.get("passkey_reprompted") or agent_state.get("request_canceled"):
                                exc = BleTransportUnavailable(
                                    "existing bond requested passkey during connect"
                                )
                    if connect_agent_session is not None:
                        connect_agent_session.stop()
                    await self._close_client_quietly()
                    if not self.pin and _is_stale_ble_bond_error_message(_format_ble_exception(exc)):
                        exc = BleTransportUnavailable(
                            "current PIN required for stale BLE bond"
                        )
                    if not trust_repair_attempted and self._should_attempt_trust_repair(exc):
                        trust_repair_attempted = True
                        await self._attempt_trust_repair(failure_message=_format_ble_exception(exc))
                        continue
                    if not bond_repair_attempted and self._should_attempt_bond_repair(exc):
                        bond_repair_attempted = True
                        await self._attempt_bond_repair(failure_message=_format_ble_exception(exc))
                        continue
                    raise
                finally:
                    if connect_agent_session is not None:
                        connect_agent_session.stop()
        except Exception as exc:
            self._connecting.clear()
            _unregister_connecting_ble_transport(self.port, self._active_token)
            self._connect_error = BleTransportUnavailable(_format_ble_exception(exc))
            logging.warning(
                "ble transport connect failed address=%s stage=%s error=%s",
                self.port,
                self._connect_stage,
                self._connect_error,
            )
            if _should_soft_disconnect_ble_device(str(self._connect_error)):
                _schedule_ble_soft_disconnect(
                    address=self.port,
                    timeout=max(4.0, self.timeout + 2.0),
                    adapter_id=self.adapter_id,
                    generation=self._connection_generation,
                )
            elif _should_reset_ble_device_cache(str(self._connect_error)):
                logging.warning(
                    "ble cache reset skipped address=%s reason=automatic-unpair-disabled error=%s",
                    self.port,
                    self._connect_error,
                )
            self._ready.set()
            await self._close_client_quietly()

    def _on_disconnect(self, _client) -> None:
        if self._connecting.is_set() and not self._ready.is_set():
            logging.warning(
                "ble transport transient disconnect during connect ignored address=%s stage=%s",
                self.port,
                self._connect_stage,
            )
            return
        logging.warning("ble transport disconnected address=%s", self.port)
        _unregister_connecting_ble_transport(self.port, self._active_token)
        _unregister_active_ble_transport(self.port, self._active_token)
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
                raise self._frame_error(TRANSPORT_FRAME_TIMEOUT_ERROR) from exc
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
        _unregister_connecting_ble_transport(self.port, self._active_token)
        _unregister_active_ble_transport(self.port, self._active_token)
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
    paired: bool = False
    bonded: bool = False
    trusted: bool = False
    connected: bool = False
    address_type: str = ""
    cached: bool = False

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
        payload["paired"] = self.paired
        payload["bonded"] = self.bonded
        payload["trusted"] = self.trusted
        payload["connected"] = self.connected
        payload["cached"] = self.cached
        if self.address_type:
            payload["address_type"] = self.address_type
        return payload


def _normalize_uuid(value: object) -> str:
    return str(value or "").strip().lower()


def _is_meshcore_ble_candidate(name: str, service_uuids: list[str]) -> bool:
    normalized_name = str(name or "")
    if any(normalized_name.startswith(prefix) for prefix in BLE_NAME_PREFIXES):
        return True
    return NUS_SERVICE_UUID in {_normalize_uuid(item) for item in service_uuids}


def _cache_ble_device(device: Any) -> None:
    address = str(getattr(device, "address", "") or "").strip().lower()
    if not address:
        return
    with _BLE_DEVICE_CACHE_LOCK:
        _BLE_DEVICE_CACHE[address] = (time.monotonic(), device)


def _get_cached_ble_device(address: object) -> Any | None:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return None
    with _BLE_DEVICE_CACHE_LOCK:
        cached = _BLE_DEVICE_CACHE.get(normalized_address)
        if cached is None:
            return None
        cached_at, device = cached
        if time.monotonic() - cached_at > BLE_DEVICE_CACHE_TTL_SECS:
            _BLE_DEVICE_CACHE.pop(normalized_address, None)
            return None
        return device


def _register_active_ble_transport(address: object, token: object) -> None:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return
    with _BLE_ACTIVE_TRANSPORTS_LOCK:
        _BLE_ACTIVE_TRANSPORTS[normalized_address] = token


def _unregister_active_ble_transport(address: object, token: object) -> None:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return
    with _BLE_ACTIVE_TRANSPORTS_LOCK:
        if _BLE_ACTIVE_TRANSPORTS.get(normalized_address) is token:
            _BLE_ACTIVE_TRANSPORTS.pop(normalized_address, None)


def _has_active_ble_transport(address: object) -> bool:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return False
    with _BLE_ACTIVE_TRANSPORTS_LOCK:
        return normalized_address in _BLE_ACTIVE_TRANSPORTS


def _has_any_active_ble_transport() -> bool:
    with _BLE_ACTIVE_TRANSPORTS_LOCK:
        return bool(_BLE_ACTIVE_TRANSPORTS)


def _register_connecting_ble_transport(address: object, token: object) -> None:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return
    with _BLE_CONNECTING_TRANSPORTS_LOCK:
        tokens = _BLE_CONNECTING_TRANSPORTS.setdefault(normalized_address, set())
        tokens.add(token)


def _unregister_connecting_ble_transport(address: object, token: object) -> None:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return
    with _BLE_CONNECTING_TRANSPORTS_LOCK:
        tokens = _BLE_CONNECTING_TRANSPORTS.get(normalized_address)
        if not tokens:
            return
        tokens.discard(token)
        if not tokens:
            _BLE_CONNECTING_TRANSPORTS.pop(normalized_address, None)


def _has_connecting_ble_transport(address: object) -> bool:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return False
    with _BLE_CONNECTING_TRANSPORTS_LOCK:
        return bool(_BLE_CONNECTING_TRANSPORTS.get(normalized_address))


def _bump_ble_connection_generation(address: object) -> int:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return 0
    with _BLE_CONNECTION_GENERATIONS_LOCK:
        next_generation = int(_BLE_CONNECTION_GENERATIONS.get(normalized_address, 0)) + 1
        _BLE_CONNECTION_GENERATIONS[normalized_address] = next_generation
        return next_generation


def _get_ble_connection_generation(address: object) -> int:
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        return 0
    with _BLE_CONNECTION_GENERATIONS_LOCK:
        return int(_BLE_CONNECTION_GENERATIONS.get(normalized_address, 0))


def _should_skip_ble_soft_disconnect(address: object) -> str:
    if _has_active_ble_transport(address):
        return "active-meshcorium-transport"
    if _has_connecting_ble_transport(address):
        return "connecting-meshcorium-transport"
    return ""


def _format_ble_exception(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "no bluetooth adapters found" in lowered:
        return "No Linux Bluetooth adapters found (hci0/hci1 missing, disabled, or blocked)"
    if "operation not permitted" in lowered and "system scope bus" in lowered:
        return "BlueZ D-Bus access denied while checking bluetooth.service"
    if "authentication failed" in lowered:
        return f"BLE authentication failed: {message}"
    return message


def _is_stale_ble_bond_error_message(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    stale_markers = (
        "pin or key missing",
        "pin_or_key_missing",
        "missing key",
        "authentication failed",
        "authenticationfailed",
        "not permitted: not paired",
        "not paired",
        "existing bond requested passkey",
        "current pin required for existing ble bond",
        "current pin required for stale ble bond",
    )
    return any(marker in lowered for marker in stale_markers)


def _ble_connect_retry_reason(exc: Exception) -> str:
    lowered = str(exc or "").strip().lower()
    if "device with address" in lowered and "was not found" in lowered:
        return "device-not-found"
    if "org.bluez.error.inprogress" in lowered or "operation already in progress" in lowered:
        return "in-progress"
    if "failed to discover services" in lowered and "device disconnected" in lowered:
        return "service-discovery-disconnected"
    if "service discovery" in lowered and "disconnected" in lowered:
        return "service-discovery-disconnected"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, FutureTimeoutError)) or lowered == "timeouterror":
        return "timeout"
    return ""


def _should_reset_ble_device_cache(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "authentication failed",
        "not connected",
        "unlikely error",
        "no matching connection",
        "nordic uart service",
        "nordic uart",
    )
    return any(marker in lowered for marker in markers)


def _should_soft_disconnect_ble_device(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "timed out",
        "timeouterror",
        "did not become ready",
        "device with address",
    )
    return any(marker in lowered for marker in markers)


def _parse_busctl_property_value(output: str) -> object:
    line = str(output or "").strip()
    if not line:
        return None
    try:
        parts = shlex.split(line)
    except ValueError:
        return None
    if not parts:
        return None
    signature = parts[0]
    values = parts[1:]
    if signature == "b":
        return bool(values and str(values[0]).strip().lower() == "true")
    if signature in {"s", "o"}:
        return str(values[0]) if values else ""
    if signature == "as":
        if values and re.fullmatch(r"\d+", str(values[0]).strip()):
            values = values[1:]
        return [str(item or "").strip() for item in values if str(item or "").strip()]
    if signature in {"n", "q", "i", "u", "x", "t", "y"}:
        if not values:
            return None
        try:
            return int(str(values[0]).strip(), 10)
        except ValueError:
            return None
    return None


def _get_bluez_device_props_via_busctl(device_path: str) -> dict[str, object]:
    if platform.system().lower() != "linux":
        return {}
    busctl = shutil.which("busctl")
    if not busctl:
        return {}
    props: dict[str, object] = {}
    for property_name in ("Address", "AddressType", "Name", "Alias", "Paired", "Trusted", "Connected", "ServicesResolved", "UUIDs", "RSSI"):
        try:
            result = subprocess.run(
                [
                    busctl,
                    "--system",
                    "get-property",
                    "org.bluez",
                    device_path,
                    "org.bluez.Device1",
                    property_name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        parsed = _parse_busctl_property_value(result.stdout)
        if parsed is not None:
            props[property_name] = parsed
    return props


def _coerce_dbus_value(value: object) -> object:
    if dbus is None:
        return value
    if isinstance(value, (dbus.String, dbus.ObjectPath, dbus.Signature)):
        return str(value)
    if isinstance(value, (dbus.Boolean,)):
        return bool(value)
    if isinstance(value, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
        return int(value)
    if isinstance(value, (dbus.Double,)):
        return float(value)
    if isinstance(value, (dbus.Array, list, tuple)):
        return [_coerce_dbus_value(item) for item in value]
    if isinstance(value, (dbus.Dictionary, dict)):
        return {
            str(_coerce_dbus_value(key)): _coerce_dbus_value(item)
            for key, item in dict(value).items()
        }
    return value


def _find_bluez_device_path(address: str, adapter_id: str = "") -> str:
    normalized_address = str(address or "").strip().upper()
    if not normalized_address:
        return ""
    normalized_adapter = str(adapter_id or "").strip()
    if platform.system().lower() != "linux":
        return ""
    if dbus is None:
        busctl = shutil.which("busctl")
        if not busctl:
            return ""
        address_suffix = normalized_address.replace(":", "_")
        expected_suffix = f"/dev_{address_suffix}"
        try:
            result = subprocess.run(
                [busctl, "--system", "tree", "org.bluez"],
                check=False,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        for raw_line in output.splitlines():
            line = str(raw_line or "").strip()
            if expected_suffix not in line:
                continue
            path_start = line.find("/org/bluez/")
            if path_start < 0:
                continue
            path = line[path_start:].strip()
            if normalized_adapter and not path.startswith(f"/org/bluez/{normalized_adapter}/"):
                continue
            if path.endswith(expected_suffix):
                return path
        return ""
    try:
        bus = dbus.SystemBus()
        manager_object = bus.get_object("org.bluez", "/")
        manager = dbus.Interface(manager_object, "org.freedesktop.DBus.ObjectManager")
        managed_objects = manager.GetManagedObjects()
    except Exception:
        return ""
    for raw_path, interfaces in dict(managed_objects).items():
        path = str(raw_path or "")
        if normalized_adapter and not path.startswith(f"/org/bluez/{normalized_adapter}/"):
            continue
        device_props = dict(interfaces).get("org.bluez.Device1")
        if not device_props:
            continue
        device_address = str(_coerce_dbus_value(dict(device_props).get("Address", "")) or "").strip().upper()
        if device_address == normalized_address:
            return path
    return ""


def _get_bluez_device_state_via_dbus(address: str, adapter_id: str = "") -> dict[str, object]:
    if platform.system().lower() != "linux" or dbus is None:
        return {}
    device_path = _find_bluez_device_path(address, adapter_id=adapter_id)
    if not device_path:
        return {}
    try:
        bus = dbus.SystemBus()
        device_object = bus.get_object("org.bluez", device_path)
        properties = dbus.Interface(device_object, "org.freedesktop.DBus.Properties")
        paired = bool(_coerce_dbus_value(properties.Get("org.bluez.Device1", "Paired")))
        trusted = bool(_coerce_dbus_value(properties.Get("org.bluez.Device1", "Trusted")))
        connected = bool(_coerce_dbus_value(properties.Get("org.bluez.Device1", "Connected")))
        try:
            services_resolved = bool(_coerce_dbus_value(properties.Get("org.bluez.Device1", "ServicesResolved")))
        except Exception:
            services_resolved = False
        uuids = _coerce_dbus_value(properties.Get("org.bluez.Device1", "UUIDs")) or []
        address_type = str(_coerce_dbus_value(properties.Get("org.bluez.Device1", "AddressType")) or "").strip().lower()
    except Exception:
        return {}
    return {
        "paired": paired,
        "bonded": paired,
        "trusted": trusted,
        "connected": connected,
        "services_resolved": services_resolved,
        "uuids": [str(item or "").strip().lower() for item in list(uuids or []) if str(item or "").strip()],
        "address_type": address_type,
        "object_path": device_path,
    }


def _build_bleak_device_from_bluez_state(address: str, adapter_id: str = "") -> Any | None:
    if platform.system().lower() != "linux" or BLEDevice is None:
        return None
    device_path = _find_bluez_device_path(address, adapter_id=adapter_id)
    if not device_path:
        return None
    if dbus is None:
        try:
            props = _get_bluez_device_props_via_busctl(device_path)
            resolved_address = str(props.get("Address") or address or "").strip()
            if not resolved_address:
                return None
            name = str(props.get("Name") or props.get("Alias") or "").strip() or None
            details = {
                "path": device_path,
                "props": props or None,
            }
            kwargs: dict[str, object] = {}
            rssi = props.get("RSSI")
            if rssi is not None:
                try:
                    kwargs["rssi"] = int(rssi)
                except Exception:
                    pass
            device = BLEDevice(resolved_address, name, details, **kwargs)
            _cache_ble_device(device)
            return device
        except Exception:
            return None
    try:
        bus = dbus.SystemBus()
        device_object = bus.get_object("org.bluez", device_path)
        properties = dbus.Interface(device_object, "org.freedesktop.DBus.Properties")
        props = _coerce_dbus_value(properties.GetAll("org.bluez.Device1")) or {}
        resolved_address = str(props.get("Address") or address or "").strip()
        if not resolved_address:
            return None
        name = str(props.get("Name") or props.get("Alias") or "").strip() or None
        details = {
            "path": device_path,
            "props": props,
        }
        kwargs: dict[str, object] = {}
        rssi = props.get("RSSI")
        if rssi is not None:
            try:
                kwargs["rssi"] = int(rssi)
            except Exception:
                pass
        device = BLEDevice(resolved_address, name, details, **kwargs)
        _cache_ble_device(device)
        return device
    except Exception:
        return None


def _describe_ble_client_target_source(device: Any | None) -> str:
    if device is None:
        return "address"
    details = getattr(device, "details", None)
    if isinstance(details, dict):
        path = str(details.get("path") or "").strip()
        props = details.get("props")
        if path:
            return "bluez-state-with-props" if props else "bluez-state-path-only"
    return "bleak-discovery-cache"


async def _resolve_ble_client_target_async(
    address: str,
    *,
    timeout: float,
    adapter_id: str = "",
    prefer_bluez_state: bool = False,
    allow_directed_scan: bool = True,
    skip_cache: bool = False,
) -> Any | None:
    if prefer_bluez_state:
        device = _build_bleak_device_from_bluez_state(address, adapter_id=adapter_id)
        if device is not None:
            return device
    if not skip_cache:
        device = _get_cached_ble_device(address)
        if device is not None:
            return device
    device = await _resolve_ble_device_by_address_async(
        address,
        timeout=timeout,
        adapter_id=adapter_id,
    )
    if device is not None:
        return device
    if allow_directed_scan and BLE_ADDRESS_RE.match(address):
        return await _scan_for_meshcore_ble_device_async(
            target_address=address,
            timeout=max(4.0, min(timeout + 2.0, 8.0)),
            adapter_id=adapter_id,
        )
    return None


def _disconnect_ble_device_via_dbus(*, address: str, adapter_id: str = "") -> None:
    if platform.system().lower() != "linux":
        return
    device_path = _find_bluez_device_path(address, adapter_id=adapter_id)
    if not device_path:
        return
    if dbus is None:
        busctl = shutil.which("busctl")
        if not busctl:
            return
        try:
            subprocess.run(
                [busctl, "--system", "call", "org.bluez", device_path, "org.bluez.Device1", "Disconnect"],
                check=False,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BleTransportUnavailable(f"BlueZ busctl disconnect failed: {_format_ble_exception(exc)}") from exc
        return
    try:
        bus = dbus.SystemBus()
        device_object = bus.get_object("org.bluez", device_path)
        properties = dbus.Interface(device_object, "org.freedesktop.DBus.Properties")
        if not bool(_coerce_dbus_value(properties.Get("org.bluez.Device1", "Connected"))):
            return
        device_interface = dbus.Interface(device_object, "org.bluez.Device1")
        device_interface.Disconnect()
    except Exception as exc:
        raise BleTransportUnavailable(f"BlueZ D-Bus disconnect failed: {_format_ble_exception(exc)}") from exc


def _wait_for_bluez_device_disconnected(*, address: str, timeout: float = 6.0, adapter_id: str = "") -> bool:
    if platform.system().lower() != "linux":
        return True
    deadline = time.monotonic() + max(0.5, float(timeout or 6.0))
    last_state: dict[str, object] = {}
    while time.monotonic() < deadline:
        last_state = _get_bluez_device_state(address, adapter_id=adapter_id)
        if not bool(last_state.get("connected")):
            return True
        time.sleep(0.15)
    logging.warning(
        "ble wait for BlueZ disconnect timed out address=%s adapter=%s paired=%s trusted=%s connected=%s",
        address,
        adapter_id or "-",
        bool(last_state.get("paired") or last_state.get("bonded")),
        bool(last_state.get("trusted")),
        bool(last_state.get("connected")),
    )
    return False


def _schedule_ble_soft_disconnect(
    *,
    address: str,
    timeout: float,
    adapter_id: str = "",
    generation: int = 0,
    delay: float = 6.0,
) -> None:
    def worker() -> None:
        try:
            if delay > 0:
                time.sleep(float(delay))
            if generation and _get_ble_connection_generation(address) != generation:
                logging.info(
                    "ble soft disconnect skipped address=%s reason=newer-connect-attempt scheduled_generation=%s current_generation=%s",
                    address,
                    generation,
                    _get_ble_connection_generation(address),
                )
                return
            skip_reason = _should_skip_ble_soft_disconnect(address)
            if skip_reason:
                logging.info(
                    "ble soft disconnect skipped address=%s reason=%s",
                    address,
                    skip_reason,
                )
                return
            _disconnect_ble_device_via_bluetoothctl(
                address=address,
                timeout=timeout,
                adapter_id=adapter_id,
                skip_if_active_transport=True,
                generation=generation,
            )
        except Exception:
            logging.warning("ble soft disconnect raised address=%s", address, exc_info=True)

    threading.Thread(
        target=worker,
        name=f"meshcorium-ble-soft-disconnect:{address}",
        daemon=True,
    ).start()


def _bluetoothctl_binary() -> str:
    binary = shutil.which("bluetoothctl")
    if not binary:
        raise BleTransportUnavailable("bluetoothctl is required for Linux BLE pairing but is not installed")
    return binary


def _is_bluez_device_paired(address: str, adapter_id: str = "") -> bool:
    state = _get_bluez_device_state(address, adapter_id=adapter_id)
    return bool(state.get("paired") or state.get("bonded"))


def _is_bluez_device_paired_and_trusted(address: str, adapter_id: str = "") -> bool:
    state = _get_bluez_device_state(address, adapter_id=adapter_id)
    return bool((state.get("paired") or state.get("bonded")) and state.get("trusted"))


def _has_bluez_device_pairing(address: str, adapter_id: str = "") -> bool:
    state = _get_bluez_device_state(address, adapter_id=adapter_id)
    return bool(state.get("paired") or state.get("bonded") or state.get("trusted") or state.get("connected"))


def _get_bluez_device_state(address: str, adapter_id: str = "") -> dict[str, object]:
    dbus_state = _get_bluez_device_state_via_dbus(address, adapter_id=adapter_id)
    if dbus_state:
        return dbus_state
    if platform.system().lower() != "linux":
        return {}
    try:
        result = subprocess.run(
            [_bluetoothctl_binary(), "info", str(address or "").strip()],
            check=False,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    lowered = output.lower()
    if "not available" in lowered:
        return {}
    info: dict[str, object] = {
        "paired": "paired: yes" in lowered,
        "bonded": "bonded: yes" in lowered,
        "trusted": "trusted: yes" in lowered,
        "connected": "connected: yes" in lowered,
        "services_resolved": "servicesresolved: yes" in lowered,
        "uuids": [],
    }
    address_type_match = re.search(r"^Device\s+[0-9A-F:]+\s+\(([^)]+)\)", output, re.MULTILINE | re.IGNORECASE)
    if address_type_match:
        info["address_type"] = str(address_type_match.group(1) or "").strip().lower()
    info["uuids"] = [
        str(match.group(1) or "").strip().lower()
        for match in re.finditer(r"UUID:\s+.+?\(([0-9a-fA-F-]{36})\)", output)
        if str(match.group(1) or "").strip()
    ]
    return info


def _write_bluetoothctl_command(process: subprocess.Popen[str], command: str) -> None:
    if process.stdin is None:
        raise BleTransportUnavailable("bluetoothctl stdin is unavailable")
    process.stdin.write(f"{command}\n")
    process.stdin.flush()


def _list_bluetoothctl_devices() -> list[tuple[str, str]]:
    if platform.system().lower() != "linux":
        return []
    try:
        result = subprocess.run(
            [_bluetoothctl_binary(), "devices"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices: list[tuple[str, str]] = []
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("device "):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            continue
        devices.append((parts[1].strip(), parts[2].strip()))
    return devices


def _list_known_meshcore_ble_devices(*, adapter_id: str = "") -> list[dict[str, object]]:
    devices: dict[str, BleDeviceInfo] = {}
    for address, name in _list_bluetoothctl_devices():
        normalized_address = str(address or "").strip()
        if not normalized_address:
            continue
        bluez_state = _get_bluez_device_state(normalized_address, adapter_id=adapter_id)
        service_uuids: list[str] = []
        for uuid_value in list(bluez_state.get("uuids") or []):
            normalized_uuid = _normalize_uuid(uuid_value)
            if normalized_uuid:
                service_uuids.append(normalized_uuid)
        if not _is_meshcore_ble_candidate(name, service_uuids):
            continue
        devices[normalized_address] = BleDeviceInfo(
            address=normalized_address,
            name=name,
            rssi=None,
            adapter_id=str(adapter_id or "").strip(),
            service_uuids=tuple(service_uuids),
            paired=bool(bluez_state.get("paired")),
            bonded=bool(bluez_state.get("bonded")),
            trusted=bool(bluez_state.get("trusted")),
            connected=bool(bluez_state.get("connected")),
            address_type=str(bluez_state.get("address_type") or "").strip(),
            cached=True,
        )
    return [
        item.to_dict()
        for item in sorted(
            devices.values(),
            key=lambda device: (device.name.lower(), device.address.lower()),
        )
    ]


def _has_connected_meshcore_ble_device(*, adapter_id: str = "") -> bool:
    for entry in _list_known_meshcore_ble_devices(adapter_id=adapter_id):
        if bool(entry.get("connected")):
            return True
    return False


def reset_meshcore_ble_pairs(*, timeout: float = 8.0, adapter_id: str = "") -> dict[str, object]:
    removed: list[str] = []
    candidates = [
        (address, name)
        for address, name in _list_bluetoothctl_devices()
        if _is_meshcore_ble_candidate(name, [])
    ]
    for address, _name in candidates:
        try:
            _remove_ble_device_via_bluetoothctl(address=address, timeout=timeout, adapter_id=adapter_id)
            removed.append(address)
        except Exception:
            logging.warning("ble reset-known-pairs failed address=%s", address, exc_info=True)
    return {
        "removed": removed,
        "count": len(removed),
    }


def unpair_ble_device(*, address: str, timeout: float = 8.0, adapter_id: str = "") -> dict[str, object]:
    address = str(address or "").strip()
    if not address:
        raise BleTransportUnavailable("BLE device address is required")
    before = _get_bluez_device_state(address, adapter_id=adapter_id)
    removed_via_dbus = _remove_ble_device_via_dbus(address=address, adapter_id=adapter_id)
    if not _has_bluez_device_pairing(address, adapter_id=adapter_id):
        after = _get_bluez_device_state(address, adapter_id=adapter_id)
        return {
            "address": address,
            "before": before,
            "after": after,
            "removed": True,
            "method": "dbus" if removed_via_dbus else "bluez-state",
        }
    _remove_ble_device_via_bluetoothctl(address=address, timeout=timeout, adapter_id=adapter_id)
    after = _wait_for_ble_unpaired_state(address=address, adapter_id=adapter_id, timeout=timeout)
    return {
        "address": address,
        "before": before,
        "after": after,
        "removed": not _has_bluez_device_pairing(address, adapter_id=adapter_id),
        "method": "dbus+bluetoothctl" if removed_via_dbus else "bluetoothctl",
    }


def _disconnect_ble_device_via_bluetoothctl(
    *,
    address: str,
    timeout: float = 6.0,
    adapter_id: str = "",
    skip_if_active_transport: bool = False,
    generation: int = 0,
) -> None:
    if platform.system().lower() != "linux":
        return
    address = str(address or "").strip()
    if not address:
        return
    bluetoothctl = _bluetoothctl_binary()
    process = subprocess.Popen(
        [bluetoothctl],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.monotonic() + max(2.0, float(timeout or 6.0))
    output_chunks: list[str] = []

    def cleanup() -> None:
        if process.poll() is None:
            try:
                _write_bluetoothctl_command(process, "quit")
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()

    try:
        prompt_seen = False
        adapter_selected = not bool(adapter_id)
        disconnect_sent = False
        while time.monotonic() < deadline:
            if process.stdout is None:
                break
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            stripped = line.strip()
            lowered = stripped.lower()
            if stripped:
                output_chunks.append(stripped)
            if ("]>" in stripped or stripped.endswith(">")) and not prompt_seen:
                prompt_seen = True
            if prompt_seen and not adapter_selected and adapter_id:
                _write_bluetoothctl_command(process, f"select {adapter_id}")
                adapter_selected = True
                continue
            if prompt_seen and adapter_selected and not disconnect_sent:
                if generation and _get_ble_connection_generation(address) != generation:
                    logging.info(
                        "ble soft disconnect skipped address=%s reason=newer-connect-attempt scheduled_generation=%s current_generation=%s",
                        address,
                        generation,
                        _get_ble_connection_generation(address),
                    )
                    return
                skip_reason = _should_skip_ble_soft_disconnect(address) if skip_if_active_transport else ""
                if skip_reason:
                    logging.info(
                        "ble soft disconnect skipped address=%s reason=%s",
                        address,
                        skip_reason,
                    )
                    return
                _write_bluetoothctl_command(process, f"disconnect {address}")
                disconnect_sent = True
                continue
            if disconnect_sent and any(
                marker in lowered
                for marker in (
                    "successful disconnected",
                    "not connected",
                    "failed to disconnect",
                    "not available",
                )
            ):
                break
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.warning("ble soft disconnect failed address=%s error=%s", address, exc)
        return
    finally:
        cleanup()
    output = " | ".join(chunk for chunk in output_chunks[-8:] if chunk)
    logging.info("ble soft disconnect address=%s output=%s", address, output or "-")


def _remove_ble_device_via_bluetoothctl(*, address: str, timeout: float = 6.0, adapter_id: str = "") -> None:
    if platform.system().lower() != "linux":
        return
    address = str(address or "").strip()
    if not address:
        return
    bluetoothctl = _bluetoothctl_binary()
    process = subprocess.Popen(
        [bluetoothctl],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.monotonic() + max(2.0, float(timeout or 6.0))
    output_chunks: list[str] = []

    def cleanup() -> None:
        if process.poll() is None:
            try:
                _write_bluetoothctl_command(process, "quit")
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()

    try:
        prompt_seen = False
        adapter_selected = not bool(adapter_id)
        disconnect_sent = False
        remove_sent = False
        while time.monotonic() < deadline:
            if process.stdout is None:
                break
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            stripped = line.strip()
            lowered = stripped.lower()
            if stripped:
                output_chunks.append(stripped)
            if ("]>" in stripped or stripped.endswith(">")) and not prompt_seen:
                prompt_seen = True
            if prompt_seen and not adapter_selected and adapter_id:
                _write_bluetoothctl_command(process, f"select {adapter_id}")
                adapter_selected = True
                continue
            if prompt_seen and adapter_selected and not disconnect_sent:
                _write_bluetoothctl_command(process, f"disconnect {address}")
                disconnect_sent = True
                continue
            if disconnect_sent and not remove_sent:
                if any(
                    marker in lowered
                    for marker in (
                        "successful disconnected",
                        "successful disconnected",
                        "not connected",
                        "not available",
                        "device has been removed",
                        "failed to disconnect",
                    )
                ) or ("]>" in stripped or stripped.endswith(">")):
                    _write_bluetoothctl_command(process, f"remove {address}")
                    remove_sent = True
                    continue
            if remove_sent and any(
                marker in lowered
                for marker in (
                    "device has been removed",
                    "not available",
                    "failed to remove",
                )
            ):
                break
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.warning("ble cache reset failed address=%s error=%s", address, exc)
        return
    finally:
        cleanup()
    output = " | ".join(chunk for chunk in output_chunks[-12:] if chunk)
    logging.info(
        "ble cache reset address=%s output=%s",
        address,
        output or "-",
    )


def _remove_ble_device_via_dbus(*, address: str, adapter_id: str = "") -> bool:
    if platform.system().lower() != "linux":
        return False
    address = str(address or "").strip()
    if not address:
        return False
    device_path = _find_bluez_device_path(address, adapter_id=adapter_id)
    if not device_path:
        return True
    adapter_path = str(device_path).rsplit("/dev_", 1)[0]
    if dbus is None:
        busctl = shutil.which("busctl")
        if not busctl:
            return False
        try:
            result = subprocess.run(
                [busctl, "--system", "call", "org.bluez", adapter_path, "org.bluez.Adapter1", "RemoveDevice", "o", device_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
            output = " | ".join(
                chunk.strip()
                for chunk in (str(result.stdout or "").strip(), str(result.stderr or "").strip())
                if chunk and chunk.strip()
            )
            if result.returncode != 0:
                logging.warning(
                    "ble busctl remove non-zero address=%s adapter=%s rc=%s output=%s",
                    address,
                    adapter_id or "-",
                    result.returncode,
                    output or "-",
                )
            else:
                logging.info(
                    "ble busctl remove invoked address=%s adapter=%s output=%s",
                    address,
                    adapter_id or "-",
                    output or "-",
                )
        except Exception as exc:
            logging.warning("ble busctl remove failed address=%s adapter=%s error=%s", address, adapter_id or "-", exc)
            return False
        for _ in range(10):
            time.sleep(0.2)
            if not _has_bluez_device_pairing(address, adapter_id=adapter_id):
                logging.info("ble busctl remove completed address=%s adapter=%s", address, adapter_id or "-")
                return True
        logging.warning("ble busctl remove pending address=%s adapter=%s state=%s", address, adapter_id or "-", _get_bluez_device_state(address, adapter_id=adapter_id))
        return False
    try:
        bus = dbus.SystemBus()
        adapter_object = bus.get_object("org.bluez", adapter_path)
        adapter = dbus.Interface(adapter_object, "org.bluez.Adapter1")
        adapter.RemoveDevice(dbus.ObjectPath(device_path))
    except Exception as exc:
        logging.warning("ble dbus remove failed address=%s adapter=%s error=%s", address, adapter_id or "-", exc)
        return False
    for _ in range(10):
        time.sleep(0.2)
        if not _has_bluez_device_pairing(address, adapter_id=adapter_id):
            logging.info("ble dbus remove completed address=%s adapter=%s", address, adapter_id or "-")
            return True
    logging.warning("ble dbus remove pending address=%s adapter=%s state=%s", address, adapter_id or "-", _get_bluez_device_state(address, adapter_id=adapter_id))
    return False


def _wait_for_ble_unpaired_state(*, address: str, adapter_id: str = "", timeout: float = 6.0) -> dict[str, object]:
    deadline = time.monotonic() + max(1.0, float(timeout or 6.0))
    last_state = _get_bluez_device_state(address, adapter_id=adapter_id)
    while time.monotonic() < deadline:
        last_state = _get_bluez_device_state(address, adapter_id=adapter_id)
        if not (
            last_state.get("paired")
            or last_state.get("bonded")
            or last_state.get("trusted")
            or last_state.get("connected")
        ):
            return last_state
        time.sleep(0.2)
    return last_state


def _trust_ble_device_via_bluetoothctl(*, address: str, timeout: float = 6.0, adapter_id: str = "") -> bool:
    if platform.system().lower() != "linux":
        return False
    address = str(address or "").strip()
    if not address:
        return False
    bluetoothctl = _bluetoothctl_binary()
    process = subprocess.Popen(
        [bluetoothctl],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.monotonic() + max(2.0, float(timeout or 6.0))
    output_chunks: list[str] = []

    def cleanup() -> None:
        if process.poll() is None:
            try:
                _write_bluetoothctl_command(process, "quit")
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()

    try:
        prompt_seen = False
        adapter_selected = not bool(adapter_id)
        trust_sent = False
        while time.monotonic() < deadline:
            if process.stdout is None:
                break
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            stripped = line.strip()
            lowered = stripped.lower()
            if stripped:
                output_chunks.append(stripped)
            if ("]>" in stripped or stripped.endswith(">")) and not prompt_seen:
                prompt_seen = True
            if prompt_seen and not adapter_selected and adapter_id:
                _write_bluetoothctl_command(process, f"select {adapter_id}")
                adapter_selected = True
                continue
            if prompt_seen and adapter_selected and not trust_sent:
                _write_bluetoothctl_command(process, f"trust {address}")
                trust_sent = True
                continue
            if trust_sent and any(
                marker in lowered
                for marker in (
                    "trust succeeded",
                    "already exists",
                    "changed",
                    "not available",
                    "failed to trust",
                )
            ):
                break
        trusted = _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id)
        output = " | ".join(chunk for chunk in output_chunks[-8:] if chunk)
        logging.info("ble trust helper address=%s trusted=%s output=%s", address, trusted, output or "-")
        return trusted
    finally:
        cleanup()


def _repair_ble_trust_via_bluetoothctl(
    *,
    address: str,
    timeout: float,
    adapter_id: str = "",
    failure_message: str = "",
) -> None:
    if platform.system().lower() != "linux":
        return
    address = str(address or "").strip()
    if not address:
        raise BleTransportUnavailable("BLE trust repair requires device address")
    before = _get_bluez_device_state(address, adapter_id=adapter_id)
    logging.warning(
        "ble trust repair state-before address=%s paired=%s bonded=%s trusted=%s connected=%s error=%s",
        address,
        bool(before.get("paired")),
        bool(before.get("bonded")),
        bool(before.get("trusted")),
        bool(before.get("connected")),
        failure_message or "-",
    )
    if not bool(before.get("paired") or before.get("bonded")):
        raise BleTransportUnavailable("BLE trust repair requires an existing paired BlueZ device state")
    trusted = _trust_ble_device_via_bluetoothctl(
        address=address,
        timeout=max(4.0, min(float(timeout or 8.0), 8.0)),
        adapter_id=adapter_id,
    )
    after = _get_bluez_device_state(address, adapter_id=adapter_id)
    logging.info(
        "ble trust repair after-trust address=%s paired=%s bonded=%s trusted=%s connected=%s",
        address,
        bool(after.get("paired")),
        bool(after.get("bonded")),
        bool(after.get("trusted")),
        bool(after.get("connected")),
    )
    if not trusted:
        raise BleTransportUnavailable("BLE trust repair did not complete")


def _repair_ble_bond_via_bluetoothctl(
    *,
    address: str,
    pin: str,
    timeout: float,
    adapter_id: str = "",
    failure_message: str = "",
) -> None:
    if platform.system().lower() != "linux":
        return
    address = str(address or "").strip()
    pin = re.sub(r"\D+", "", str(pin or "").strip())
    if not address or not pin:
        raise BleTransportUnavailable("BLE bond repair requires both device address and PIN")
    before = _get_bluez_device_state(address, adapter_id=adapter_id)
    logging.warning(
        "ble bond repair state-before address=%s paired=%s bonded=%s trusted=%s connected=%s error=%s",
        address,
        bool(before.get("paired")),
        bool(before.get("bonded")),
        bool(before.get("trusted")),
        bool(before.get("connected")),
        failure_message or "-",
    )
    try:
        repaired_without_remove = False
        try:
            repaired_without_remove = _ensure_ble_pairing_via_bluetoothctl(
                address=address,
                pin=pin,
                timeout=max(10.0, float(timeout or 12.0)),
                adapter_id=adapter_id,
                allow_no_challenge_fallback=False,
                force_pairing_attempt=True,
            )
        except Exception as exc:
            logging.warning(
                "ble bond repair forced pair attempt failed address=%s error=%s",
                address,
                _format_ble_exception(exc),
            )
        after_forced_pair = _get_bluez_device_state(address, adapter_id=adapter_id)
        logging.info(
            "ble bond repair after-forced-pair address=%s paired=%s bonded=%s trusted=%s connected=%s repaired=%s",
            address,
            bool(after_forced_pair.get("paired")),
            bool(after_forced_pair.get("bonded")),
            bool(after_forced_pair.get("trusted")),
            bool(after_forced_pair.get("connected")),
            repaired_without_remove,
        )
        if repaired_without_remove and _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id):
            _disconnect_ble_device_via_bluetoothctl(
                address=address,
                timeout=max(4.0, min(float(timeout or 10.0), 8.0)),
                adapter_id=adapter_id,
                skip_if_active_transport=False,
            )
            time.sleep(0.75)
            return
        _remove_ble_device_via_bluetoothctl(
            address=address,
            timeout=max(6.0, min(float(timeout or 12.0), 12.0)),
            adapter_id=adapter_id,
        )
        time.sleep(0.75)
        after_remove = _get_bluez_device_state(address, adapter_id=adapter_id)
        logging.info(
            "ble bond repair after-remove address=%s paired=%s bonded=%s trusted=%s connected=%s",
            address,
            bool(after_remove.get("paired")),
            bool(after_remove.get("bonded")),
            bool(after_remove.get("trusted")),
            bool(after_remove.get("connected")),
        )
        _ensure_ble_pairing_via_bluetoothctl(
            address=address,
            pin=pin,
            timeout=max(10.0, float(timeout or 12.0)),
            adapter_id=adapter_id,
        )
        after_pair = _get_bluez_device_state(address, adapter_id=adapter_id)
        logging.info(
            "ble bond repair after-pair address=%s paired=%s bonded=%s trusted=%s connected=%s",
            address,
            bool(after_pair.get("paired")),
            bool(after_pair.get("bonded")),
            bool(after_pair.get("trusted")),
            bool(after_pair.get("connected")),
        )
        if not _has_bluez_device_pairing(address, adapter_id=adapter_id):
            raise BleTransportUnavailable("BLE bond repair did not leave a trusted or paired BlueZ device state")
        _disconnect_ble_device_via_bluetoothctl(
            address=address,
            timeout=max(4.0, min(float(timeout or 10.0), 8.0)),
            adapter_id=adapter_id,
            skip_if_active_transport=False,
        )
        time.sleep(0.75)
        after_disconnect = _get_bluez_device_state(address, adapter_id=adapter_id)
        logging.info(
            "ble bond repair after-disconnect address=%s paired=%s bonded=%s trusted=%s connected=%s",
            address,
            bool(after_disconnect.get("paired")),
            bool(after_disconnect.get("bonded")),
            bool(after_disconnect.get("trusted")),
            bool(after_disconnect.get("connected")),
        )
    except Exception as exc:
        raise BleTransportUnavailable(f"BLE bond repair failed: {_format_ble_exception(exc)}") from exc


def _ensure_ble_pairing_via_bluetoothctl(
    *,
    address: str,
    pin: str,
    timeout: float,
    adapter_id: str = "",
    allow_no_challenge_fallback: bool = False,
    force_pairing_attempt: bool = False,
) -> bool:
    if platform.system().lower() != "linux":
        return False
    address = str(address or "").strip()
    pin = re.sub(r"\D+", "", str(pin or "").strip())
    if not address or not pin:
        return False
    if _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id) and not force_pairing_attempt:
        logging.info("ble pairing helper address=%s already paired+trusted", address)
        return True
    bluetoothctl = _bluetoothctl_binary()
    process = subprocess.Popen(
        [bluetoothctl],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )
    deadline = time.monotonic() + max(8.0, float(timeout or 12.0))
    output_chunks: list[str] = []
    detector_buffer = ""
    adapter_selected = not bool(adapter_id)
    power_requested = False
    agent_requested = False
    agent_ready = False
    default_agent_requested = False
    default_agent_requested_at = 0.0
    default_agent_ready = False
    pair_sent = False
    pin_sent = False
    confirmation_handled = False
    pair_succeeded = False
    trust_sent = False
    prompt_seen = False
    meaningful_pair_activity = False

    def cleanup() -> None:
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b"quit\n")
                    process.stdin.flush()
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()

    def write_cmd(command: str) -> None:
        if process.stdin is None:
            raise BleTransportUnavailable("bluetoothctl stdin is unavailable")
        process.stdin.write(f"{command}\n".encode("utf-8"))
        process.stdin.flush()

    try:
        while time.monotonic() < deadline:
            if process.stdout is None:
                break
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                if (
                    agent_ready
                    and default_agent_requested
                    and not default_agent_ready
                    and not pair_sent
                    and default_agent_requested_at > 0
                    and time.monotonic() - default_agent_requested_at >= 1.0
                ):
                    logging.info(
                        "ble pairing helper address=%s default-agent response delayed; sending pair anyway",
                        address,
                    )
                    write_cmd(f"pair {address}")
                    pair_sent = True
                continue
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                if process.poll() is not None:
                    break
                continue
            decoded = chunk.decode("utf-8", errors="ignore")
            if not decoded:
                continue
            detector_buffer += decoded.lower()
            if len(detector_buffer) > 4096:
                detector_buffer = detector_buffer[-4096:]
            lowered = detector_buffer
            chunk_prompt_seen = "]>" in decoded or decoded.rstrip().endswith(">")
            if chunk_prompt_seen:
                prompt_seen = True
            for raw_line in decoded.splitlines():
                stripped = raw_line.strip()
                if stripped:
                    output_chunks.append(stripped)
                    logging.info("ble pairing helper address=%s line=%s", address, stripped)
            if prompt_seen and adapter_id and not adapter_selected:
                write_cmd(f"select {adapter_id}")
                adapter_selected = True
                continue
            if prompt_seen and not power_requested:
                write_cmd("power on")
                power_requested = True
                continue
            if prompt_seen and not agent_requested:
                write_cmd("agent KeyboardDisplay")
                agent_requested = True
                continue
            if "agent registered" in lowered or "agent is already registered" in lowered:
                agent_ready = True
                if not default_agent_requested:
                    write_cmd("default-agent")
                    default_agent_requested = True
                    default_agent_requested_at = time.monotonic()
                detector_buffer = ""
                continue
            if "failed to register agent object" in lowered:
                agent_requested = False
                detector_buffer = ""
                continue
            if "default agent request successful" in lowered:
                default_agent_ready = True
                if not pair_sent:
                    write_cmd(f"pair {address}")
                    pair_sent = True
                detector_buffer = ""
                continue
            if "no agent is registered" in lowered:
                default_agent_requested = False
                default_agent_ready = False
                agent_requested = False
                detector_buffer = ""
                continue
            if not pin_sent and any(prompt in lowered for prompt in _BLUETOOTHCTL_PASSKEY_PROMPTS):
                write_cmd(pin)
                pin_sent = True
                meaningful_pair_activity = True
                detector_buffer = ""
                continue
            if not confirmation_handled and any(prompt in lowered for prompt in _BLUETOOTHCTL_CONFIRM_PROMPTS):
                write_cmd("yes")
                confirmation_handled = True
                meaningful_pair_activity = True
                detector_buffer = ""
                continue
            if "pairing successful" in lowered and not trust_sent:
                pair_succeeded = True
                meaningful_pair_activity = True
                write_cmd(f"trust {address}")
                trust_sent = True
                detector_buffer = ""
                continue
            if "already paired" in lowered and not trust_sent:
                pair_succeeded = True
                meaningful_pair_activity = True
                write_cmd(f"trust {address}")
                trust_sent = True
                detector_buffer = ""
                continue
            if "trust succeeded" in lowered and _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id):
                return True
            if any(marker in lowered for marker in _BLUETOOTHCTL_FAILURE_MARKERS):
                joined = " | ".join(output_chunks[-8:]).strip()
                raise BleTransportUnavailable(
                    f"automatic BLE pairing failed{': ' + joined if joined else ''}"
                )
            if any(marker in lowered for marker in _BLUETOOTHCTL_SUCCESS_MARKERS) and _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id):
                return True
            if pair_succeeded and _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id):
                return True
        if _is_bluez_device_paired_and_trusted(address, adapter_id=adapter_id) and (not force_pairing_attempt or meaningful_pair_activity):
            return True
        joined = " | ".join(output_chunks[-8:]).strip()
        if not pin_sent:
            if allow_no_challenge_fallback:
                logging.warning(
                    "ble pairing helper address=%s no PIN challenge observed; falling back to direct BLE connect output=%s",
                    address,
                    joined or "-",
                )
                return False
            raise BleTransportUnavailable(
                f"automatic BLE pairing did not complete in time (no PIN challenge observed){': ' + joined if joined else ''}"
            )
        raise BleTransportUnavailable(
            f"automatic BLE pairing did not complete in time{': ' + joined if joined else ''}"
        )
    finally:
        cleanup()


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


async def _discover_ble_devices_async(*, timeout: float, adapter_id: str = "", cached_only: bool = False) -> list[dict[str, object]]:
    if BleakScanner is None:
        raise BleTransportUnavailable("Python package 'bleak' is not installed")
    _ensure_bluez_available()

    timeout = max(1.0, float(timeout or 5.0))
    adapter_id = str(adapter_id or "").strip()
    if cached_only or _has_any_active_ble_transport() or _has_connected_meshcore_ble_device(adapter_id=adapter_id):
        return _list_known_meshcore_ble_devices(adapter_id=adapter_id)
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
        _cache_ble_device(device)
        rssi = getattr(advertisement_data, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)
        bluez_state = _get_bluez_device_state(address, adapter_id=adapter_id)
        devices[address] = BleDeviceInfo(
            address=address,
            name=name,
            rssi=int(rssi) if rssi is not None else None,
            adapter_id=adapter_id,
            service_uuids=tuple(service_uuids),
            paired=bool(bluez_state.get("paired")),
            bonded=bool(bluez_state.get("bonded")),
            trusted=bool(bluez_state.get("trusted")),
            connected=bool(bluez_state.get("connected")),
            address_type=str(bluez_state.get("address_type") or "").strip(),
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

    for entry in _list_known_meshcore_ble_devices(adapter_id=adapter_id):
        address = str(entry.get("transport_id") or entry.get("address") or "").strip()
        if not address or address in devices:
            continue
        devices[address] = BleDeviceInfo(
            address=address,
            name=str(entry.get("name") or entry.get("display_label") or address),
            rssi=None,
            adapter_id=adapter_id,
            service_uuids=tuple(entry.get("service_uuids") or ()),
            paired=bool(entry.get("paired")),
            bonded=bool(entry.get("bonded")),
            trusted=bool(entry.get("trusted")),
            connected=bool(entry.get("connected")),
            address_type=str(entry.get("address_type") or "").strip(),
            cached=True,
        )

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
            _cache_ble_device(device)
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


async def _scan_for_meshcore_ble_device_async(
    *,
    target_address: str = "",
    timeout: float,
    adapter_id: str = "",
) -> Any | None:
    if BleakScanner is None:
        raise BleTransportUnavailable("Python package 'bleak' is not installed")
    target_address = str(target_address or "").strip().lower()
    timeout = max(1.0, float(timeout or 6.0))
    adapter_id = str(adapter_id or "").strip()
    found: dict[str, Any] = {}
    ready = asyncio.Event()

    def on_detect(device: Any, advertisement_data: Any) -> None:
        if ready.is_set():
            return
        candidate_address = str(getattr(device, "address", "") or "").strip().lower()
        if target_address and candidate_address == target_address:
            _cache_ble_device(device)
            found["device"] = device
            ready.set()
            return
        local_name = str(getattr(advertisement_data, "local_name", "") or "")
        service_uuids = [
            _normalize_uuid(item)
            for item in list(getattr(advertisement_data, "service_uuids", []) or [])
            if str(item or "").strip()
        ]
        if _is_meshcore_ble_candidate(local_name, service_uuids):
            _cache_ble_device(device)
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


def discover_ble_devices(*, timeout: float = 5.0, adapter_id: str = "", cached_only: bool = False) -> list[dict[str, object]]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_discover_ble_devices_async(timeout=timeout, adapter_id=adapter_id, cached_only=cached_only))
    raise BleTransportUnavailable("BLE discovery cannot run inside an existing asyncio event loop")
