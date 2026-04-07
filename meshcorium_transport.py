from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meshcorium_client import (
    DEFAULT_BAUDRATE,
    DEFAULT_TIMEOUT,
    MeshCoreClient,
)
from meshcorium_serial_transport import SerialPortTransport, discover_serial_ports


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
        if transport_type != SERIAL_TRANSPORT_TYPE:
            raise ValueError(f"unsupported transport_type: {transport_type}")
        transport_id = source.get("transport_id") or source.get("device") or source.get("port") or body.get("transport_id") or body.get("device") or body.get("port")
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

    def to_dict(self) -> dict[str, object]:
        payload = {
            "transport_type": self.transport_type,
            "transport_id": self.transport_id,
            "display_label": self.display_label or self.transport_id,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
        }
        if self.transport_type == SERIAL_TRANSPORT_TYPE:
            payload["port"] = self.port
        return payload


class SerialTransportAdapter:
    transport_type = SERIAL_TRANSPORT_TYPE

    def discover(self) -> list[dict[str, str]]:
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
        transport = SerialPortTransport(
            port=descriptor.port,
            baudrate=descriptor.baudrate,
            timeout=descriptor.timeout,
        )
        return MeshCoreClient(
            port=descriptor.port,
            baudrate=descriptor.baudrate,
            timeout=descriptor.timeout,
            transport=transport,
        )


class ConnectionRouter:
    def __init__(self, *, serial_adapter: SerialTransportAdapter | None = None):
        self._serial_adapter = serial_adapter or SerialTransportAdapter()

    def from_request(self, body: dict[str, Any]) -> ConnectionDescriptor:
        return ConnectionDescriptor.from_request(body)

    def from_legacy_serial_kwargs(self, **kwargs: Any) -> ConnectionDescriptor:
        return ConnectionDescriptor.from_legacy_serial(
            port=kwargs.get("port"),
            baudrate=kwargs.get("baudrate", DEFAULT_BAUDRATE),
            timeout=kwargs.get("timeout", DEFAULT_TIMEOUT),
        )

    def discover(self, transport_type: str = SERIAL_TRANSPORT_TYPE) -> list[dict[str, str]]:
        if _normalize_transport_type(transport_type) != SERIAL_TRANSPORT_TYPE:
            raise ValueError(f"unsupported transport_type: {transport_type}")
        return self._serial_adapter.discover()

    def open_client(self, descriptor: ConnectionDescriptor) -> MeshCoreClient:
        if descriptor.transport_type == SERIAL_TRANSPORT_TYPE:
            return self._serial_adapter.open_client(descriptor)
        raise ValueError(f"unsupported transport_type: {descriptor.transport_type}")

    def open_legacy_serial_client(self, **kwargs: Any) -> MeshCoreClient:
        return self.open_client(self.from_legacy_serial_kwargs(**kwargs))


DEFAULT_CONNECTION_ROUTER = ConnectionRouter()
