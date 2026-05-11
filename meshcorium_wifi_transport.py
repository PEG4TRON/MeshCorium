from __future__ import annotations

import socket
import threading
import struct

from meshcorium_serial_transport import (
    TRANSPORT_FRAME_TIMEOUT_ERROR,
    USB_INBOUND_PREFIX,
    USB_OUTBOUND_PREFIX,
    UsbSerialFrameTransport,
)


WIFI_TRANSPORT_TYPE = "wifi"
WIFI_DEFAULT_PORT = 5000
WIFI_MAX_FRAME_PAYLOAD = 172


class WifiTransportError(RuntimeError):
    pass


class TcpSocketTransport:
    """Small blocking TCP transport for MeshCore companion framing."""

    def __init__(self, *, host: str, port: int, timeout: float):
        self.host = str(host or "").strip()
        self.port = int(port or 0)
        if not self.host:
            raise WifiTransportError("host is required for Wi-Fi transport")
        if not (1 <= self.port <= 65535):
            raise WifiTransportError(f"invalid Wi-Fi port: {self.port}")
        self._connect_timeout = max(0.1, float(timeout or 4.0))
        self._read_timeout = max(0.1, float(timeout or 4.0))
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self) -> None:
        try:
            sock = socket.create_connection(
                (self.host, self.port),
                timeout=self._connect_timeout,
            )
        except OSError as exc:
            raise WifiTransportError(
                f"Wi-Fi TCP connect failed to {self.host}:{self.port}: {exc}"
            ) from exc
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        sock.settimeout(self._read_timeout)
        self._socket = sock

    @property
    def timeout(self) -> float | None:
        if self._socket is None:
            return None
        try:
            return self._socket.gettimeout()
        except OSError:
            return None

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        if self._socket is None:
            return
        if value is None:
            self._socket.settimeout(None)
            return
        self._socket.settimeout(max(0.0, float(value)))

    @property
    def in_waiting(self) -> int:
        return 0

    def read(self, size: int) -> bytes:
        if self._socket is None:
            raise WifiTransportError("Wi-Fi transport is closed")
        buf = bytearray()
        try:
            while len(buf) < size:
                chunk = self._socket.recv(size - len(buf))
                if not chunk:
                    raise WifiTransportError(
                        "Wi-Fi connection closed while reading frame"
                    )
                buf.extend(chunk)
        except socket.timeout as exc:
            if not buf:
                raise WifiTransportError(TRANSPORT_FRAME_TIMEOUT_ERROR) from exc
        except OSError as exc:
            raise WifiTransportError(f"Wi-Fi read error: {exc}") from exc
        return bytes(buf)

    def write(self, data: bytes) -> int:
        if self._socket is None:
            raise WifiTransportError("Wi-Fi transport is closed")
        with self._lock:
            try:
                self._socket.sendall(data)
            except OSError as exc:
                raise WifiTransportError(f"Wi-Fi write error: {exc}") from exc
        return len(data)

    def flush(self) -> None:
        return

    def reset_input_buffer(self) -> None:
        if self._socket is None:
            return
        previous_timeout = self.timeout
        self._socket.settimeout(0.0)
        try:
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
        except (socket.timeout, BlockingIOError, OSError):
            pass
        finally:
            self.timeout = previous_timeout

    def reset_output_buffer(self) -> None:
        return

    def cancel_read(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.shutdown(socket.SHUT_RD)
        except OSError:
            pass

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


class WifiFrameTransport(UsbSerialFrameTransport):
    transport_type = WIFI_TRANSPORT_TYPE

    def read_frame(self) -> bytes:
        self.read_prefixed_byte(USB_OUTBOUND_PREFIX)
        length = struct.unpack("<H", self.read_exact(2))[0]
        if length > WIFI_MAX_FRAME_PAYLOAD:
            raise self._error(
                f"transport frame too large: {length} > {WIFI_MAX_FRAME_PAYLOAD}"
            )
        return self.read_exact(length)

    def write_frame(self, payload: bytes) -> None:
        if len(payload) > WIFI_MAX_FRAME_PAYLOAD:
            raise self._error(
                f"transport payload too large: {len(payload)} > {WIFI_MAX_FRAME_PAYLOAD}"
            )
        header = USB_INBOUND_PREFIX + struct.pack("<H", len(payload))
        self.byte_transport.write(header + payload)
        self.byte_transport.flush()


def parse_wifi_address(address: str) -> tuple[str, int]:
    raw = str(address or "").strip()
    if raw.startswith("tcp://"):
        raw = raw[len("tcp://") :]
    host = ""
    port = WIFI_DEFAULT_PORT
    if raw.startswith("[") and "]" in raw:
        bracket_end = raw.index("]")
        host = raw[1:bracket_end].strip()
        remainder = raw[bracket_end + 1 :].strip()
        if remainder.startswith(":"):
            port = int(remainder[1:].strip())
    elif raw.count(":") == 1:
        host_part, port_part = raw.split(":", 1)
        host = host_part.strip()
        port = int(port_part.strip())
    else:
        host = raw
    if not host:
        raise WifiTransportError(f"invalid Wi-Fi address: {address}")
    if not (1 <= port <= 65535):
        raise WifiTransportError(f"invalid Wi-Fi port: {port}")
    return host, port


def normalize_wifi_address(address: str) -> str:
    host, port = parse_wifi_address(address)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def open_wifi_runtime(
    *,
    address: str,
    timeout: float = 4.0,
    frame_error=WifiTransportError,
):
    host, port = parse_wifi_address(address)
    byte_transport = TcpSocketTransport(
        host=host,
        port=port,
        timeout=timeout,
    )
    frame_transport = WifiFrameTransport(
        byte_transport,
        frame_error=frame_error,
    )
    return byte_transport, frame_transport


def discover_wifi_devices() -> list[dict[str, object]]:
    return []
