from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meshcorium_client import (
    DEFAULT_BAUDRATE,
    DEFAULT_TIMEOUT,
    MeshCoreError,
    MeshCoreClient,
)
from meshcorium_ble_transport import BLE_TRANSPORT_TYPE, BleFrameTransport, discover_ble_devices
from meshcorium_serial_transport import discover_serial_ports, open_serial_runtime


SERIAL_TRANSPORT_TYPE = "serial"


def _normalize_transport_type(value: object) -> str:
    transport_type = str(value or SERIAL_TRANSPORT_TYPE).strip().lower()
    return transport_type or SERIAL_TRANSPORT_TYPE


def _normalize_serial_port(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ConnectionDescriptor:
    """Transport-aware node connection identity with legacy USB defaults."""

    transport_type: str
    transport_id: str
    baudrate: int = DEFAULT_BAUDRATE
    timeout: float = DEFAULT_TIMEOUT
    display_label: str = ""
    adapter_id: str = ""
    pin: str = ""

    @classmethod
    def from_legacy_serial(
        cls,
        *,
        port: object,
        baudrate: object = DEFAULT_BAUDRATE,
        timeout: object = DEFAULT_TIMEOUT,
        display_label: object = "",
    ) -> ConnectionDescriptor:
        normalized_port = _normalize_serial_port(port)
        if not normalized_port:
            raise ValueError("port is required")
        return cls(
            transport_type=SERIAL_TRANSPORT_TYPE,
            transport_id=normalized_port,
            baudrate=int(baudrate or DEFAULT_BAUDRATE),
            timeout=float(timeout if timeout not in (None, "") else DEFAULT_TIMEOUT),
            display_label=str(display_label or normalized_port).strip(),
        )

    @classmethod
    def from_request(cls, body: dict[str, Any]) -> ConnectionDescriptor:
        source = body.get("connection") if isinstance(body.get("connection"), dict) else body
        transport_type = _normalize_transport_type(source.get("transport_type") or body.get("transport_type"))
        transport_id = source.get("transport_id") or source.get("device") or source.get("port") or body.get("transport_id") or body.get("device") or body.get("port")
        if transport_type == BLE_TRANSPORT_TYPE:
            normalized_transport_id = str(transport_id or source.get("address") or body.get("address") or "").strip()
            if not normalized_transport_id:
                raise ValueError("transport_id is required")
            return cls(
                transport_type=BLE_TRANSPORT_TYPE,
                transport_id=normalized_transport_id,
                baudrate=int(source.get("baudrate", body.get("baudrate", 0)) or 0),
                timeout=float(source.get("timeout", body.get("timeout", DEFAULT_TIMEOUT)) or DEFAULT_TIMEOUT),
                display_label=str(
                    source.get("display_label")
                    or source.get("name")
                    or source.get("label")
                    or body.get("display_label")
                    or body.get("name")
                    or body.get("label")
                    or normalized_transport_id
                ).strip(),
                adapter_id=str(source.get("adapter_id") or body.get("adapter_id") or "").strip(),
                pin=str(source.get("pin") or body.get("pin") or "").strip(),
            )
        if transport_type != SERIAL_TRANSPORT_TYPE:
            raise ValueError(f"unsupported transport_type: {transport_type}")
        return cls.from_legacy_serial(
            port=transport_id,
            baudrate=source.get("baudrate", body.get("baudrate", DEFAULT_BAUDRATE)),
            timeout=source.get("timeout", body.get("timeout", DEFAULT_TIMEOUT)),
            display_label=source.get("display_label") or source.get("label") or body.get("display_label") or body.get("label") or transport_id,
        )

    @property
    def port(self) -> str:
        if self.transport_type != SERIAL_TRANSPORT_TYPE:
            raise ValueError(f"connection does not expose a serial port: {self.transport_type}")
        return self.transport_id

    @property
    def lock_key(self) -> str:
        return f"{self.transport_type}:{self.transport_id}"

    def legacy_kwargs(self) -> dict[str, object]:
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
        }

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, object]:
        payload = {
            "transport_type": self.transport_type,
            "transport_id": self.transport_id,
            "display_label": self.display_label or self.transport_id,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
        }
        if self.transport_type == SERIAL_TRANSPORT_TYPE:
            payload["port"] = self.port
        if self.adapter_id:
            payload["adapter_id"] = self.adapter_id
        if include_secrets and self.pin:
            payload["pin"] = self.pin
        return payload


class SerialTransportAdapter:
    transport_type = SERIAL_TRANSPORT_TYPE

    def discover(self) -> list[dict[str, object]]:
        ports = []
        for item in discover_serial_ports():
            next_item = dict(item)
            device = str(next_item.get("device") or "").strip()
            next_item["transport_type"] = self.transport_type
            next_item["transport_id"] = device
            ports.append(next_item)
        return ports

    def open_client(self, descriptor: ConnectionDescriptor) -> MeshCoreClient:
        if descriptor.transport_type != self.transport_type:
            raise ValueError(f"serial adapter cannot open {descriptor.transport_type}")
        transport, frame_transport = open_serial_runtime(
            port=descriptor.port,
            baudrate=descriptor.baudrate,
            timeout=descriptor.timeout,
            frame_error=MeshCoreError,
        )
        return MeshCoreClient(
            port=descriptor.port,
            baudrate=descriptor.baudrate,
            timeout=descriptor.timeout,
            transport=transport,
            frame_transport=frame_transport,
        )


class BleTransportAdapter:
    transport_type = BLE_TRANSPORT_TYPE

    def discover(self, *, timeout: float = 5.0, adapter_id: str = "") -> list[dict[str, object]]:
        return discover_ble_devices(timeout=timeout, adapter_id=adapter_id)

    def open_client(self, descriptor: ConnectionDescriptor) -> MeshCoreClient:
        if descriptor.transport_type != self.transport_type:
            raise ValueError(f"BLE adapter cannot open {descriptor.transport_type}")
        transport = BleFrameTransport(
            address=descriptor.transport_id,
            timeout=descriptor.timeout,
            adapter_id=descriptor.adapter_id,
            pin=descriptor.pin,
            frame_error=MeshCoreError,
        )
        return MeshCoreClient(
            port=descriptor.transport_id,
            baudrate=0,
            timeout=descriptor.timeout,
            open_settle=0,
            transport=transport,
            frame_transport=transport,
        )


class ConnectionRouter:
    def __init__(
        self,
        *,
        serial_adapter: SerialTransportAdapter | None = None,
        ble_adapter: BleTransportAdapter | None = None,
    ):
        self._serial_adapter = serial_adapter or SerialTransportAdapter()
        self._ble_adapter = ble_adapter or BleTransportAdapter()

    def from_request(self, body: dict[str, Any]) -> ConnectionDescriptor:
        return ConnectionDescriptor.from_request(body)

    def from_legacy_serial_kwargs(self, **kwargs: Any) -> ConnectionDescriptor:
        return ConnectionDescriptor.from_legacy_serial(
            port=kwargs.get("port"),
            baudrate=kwargs.get("baudrate", DEFAULT_BAUDRATE),
            timeout=kwargs.get("timeout", DEFAULT_TIMEOUT),
        )

    def discover(self, transport_type: str = SERIAL_TRANSPORT_TYPE, **kwargs: Any) -> list[dict[str, object]]:
        normalized_type = _normalize_transport_type(transport_type)
        if normalized_type == SERIAL_TRANSPORT_TYPE:
            return self._serial_adapter.discover()
        if normalized_type == BLE_TRANSPORT_TYPE:
            return self._ble_adapter.discover(
                timeout=float(kwargs.get("timeout", 5.0) or 5.0),
                adapter_id=str(kwargs.get("adapter_id") or ""),
            )
        if normalized_type in {"all", "*"}:
            return [
                *self._serial_adapter.discover(),
                *self._ble_adapter.discover(
                    timeout=float(kwargs.get("timeout", 5.0) or 5.0),
                    adapter_id=str(kwargs.get("adapter_id") or ""),
                ),
            ]
        if normalized_type != SERIAL_TRANSPORT_TYPE:
            raise ValueError(f"unsupported transport_type: {transport_type}")
        return self._serial_adapter.discover()

    def open_client(self, descriptor: ConnectionDescriptor) -> MeshCoreClient:
        if descriptor.transport_type == SERIAL_TRANSPORT_TYPE:
            return self._serial_adapter.open_client(descriptor)
        if descriptor.transport_type == BLE_TRANSPORT_TYPE:
            return self._ble_adapter.open_client(descriptor)
        raise ValueError(f"unsupported transport_type: {descriptor.transport_type}")

    def open_legacy_serial_client(self, **kwargs: Any) -> MeshCoreClient:
        return self.open_client(self.from_legacy_serial_kwargs(**kwargs))


DEFAULT_CONNECTION_ROUTER = ConnectionRouter()
