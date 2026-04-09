from __future__ import annotations

import struct

import serial
from serial.tools import list_ports


SerialException = serial.SerialException
USB_INBOUND_PREFIX = b"<"
USB_OUTBOUND_PREFIX = b">"
TRANSPORT_FRAME_TIMEOUT_ERROR = "transport timeout while reading frame"


class SerialFrameError(RuntimeError):
    pass


class SerialPortTransport:
    """Small pyserial wrapper used by the MeshCore protocol client."""

    def __init__(self, *, port: str, baudrate: int, timeout: float):
        self.port = str(port)
        self._serial = serial.Serial(port=self.port, baudrate=baudrate, timeout=timeout)

    @property
    def timeout(self) -> float | None:
        return self._serial.timeout

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        self._serial.timeout = value

    @property
    def in_waiting(self) -> int:
        return int(getattr(self._serial, "in_waiting", 0) or 0)

    def read(self, size: int) -> bytes:
        return self._serial.read(size)

    def write(self, data: bytes) -> int:
        return int(self._serial.write(data))

    def flush(self) -> None:
        self._serial.flush()

    def reset_input_buffer(self) -> None:
        self._serial.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        self._serial.reset_output_buffer()

    def cancel_read(self) -> None:
        cancel_read = getattr(self._serial, "cancel_read", None)
        if callable(cancel_read):
            cancel_read()

    def close(self) -> None:
        self._serial.close()


class UsbSerialFrameTransport:
    """MeshCore USB companion wire framing over a byte-oriented transport."""

    def __init__(self, byte_transport, *, frame_error=SerialFrameError):
        self.byte_transport = byte_transport
        self._frame_error = frame_error

    @property
    def port(self) -> str:
        return str(getattr(self.byte_transport, "port", ""))

    @property
    def timeout(self) -> float | None:
        return getattr(self.byte_transport, "timeout", None)

    @timeout.setter
    def timeout(self, value: float | None) -> None:
        self.byte_transport.timeout = value

    @property
    def in_waiting(self) -> int:
        return int(getattr(self.byte_transport, "in_waiting", 0) or 0)

    def _error(self, message: str) -> Exception:
        return self._frame_error(message)

    def read_exact(self, size: int) -> bytes:
        data = self.byte_transport.read(size)
        if len(data) != size:
            raise self._error(TRANSPORT_FRAME_TIMEOUT_ERROR)
        return data

    def read_prefixed_byte(self, expected_prefix: bytes, *, max_discard: int = 256) -> bytes:
        discarded = bytearray()
        while True:
            prefix = self.byte_transport.read(1)
            if len(prefix) != 1:
                if discarded:
                    preview = discarded[:16].hex().upper()
                    raise self._error(
                        f"transport timeout while resyncing frame prefix after discarding {len(discarded)} bytes ({preview})"
                    )
                raise self._error(TRANSPORT_FRAME_TIMEOUT_ERROR)
            if prefix == expected_prefix:
                return prefix
            discarded.extend(prefix)
            if len(discarded) >= max_discard:
                preview = bytes(discarded[:16]).hex().upper()
                raise self._error(
                    f"transport lost framing after discarding {len(discarded)} bytes "
                    f"while waiting for {expected_prefix!r} ({preview})"
                )

    def read_frame(self) -> bytes:
        self.read_prefixed_byte(USB_OUTBOUND_PREFIX)
        length = struct.unpack("<H", self.read_exact(2))[0]
        return self.read_exact(length)

    def write_frame(self, payload: bytes) -> None:
        header = USB_INBOUND_PREFIX + struct.pack("<H", len(payload))
        self.byte_transport.write(header + payload)
        self.byte_transport.flush()

    def reset_input_buffer(self) -> None:
        self.byte_transport.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        self.byte_transport.reset_output_buffer()

    def cancel_read(self) -> None:
        cancel_read = getattr(self.byte_transport, "cancel_read", None)
        if callable(cancel_read):
            cancel_read()

    def close(self) -> None:
        self.byte_transport.close()


def discover_serial_ports() -> list[dict[str, str]]:
    result = []
    for port in list_ports.comports():
        device = port.device or ""
        description = port.description or ""
        hwid = port.hwid or ""
        manufacturer = port.manufacturer or ""
        product = port.product or ""
        usb_info = " ".join([device, description, hwid, manufacturer, product]).lower()
        if not (
            "usb" in usb_info
            or "vid:pid" in usb_info
            or device.startswith("/dev/ttyUSB")
            or device.startswith("/dev/ttyACM")
            or device.startswith("/dev/cu.usb")
            or device.startswith("COM")
        ):
            continue
        result.append(
            {
                "device": device,
                "description": description,
                "hwid": hwid,
                "manufacturer": manufacturer,
                "product": product,
            }
        )
    return result


def open_serial_runtime(*, port: str, baudrate: int, timeout: float, frame_error=SerialFrameError):
    byte_transport = SerialPortTransport(
        port=port,
        baudrate=baudrate,
        timeout=timeout,
    )
    frame_transport = UsbSerialFrameTransport(
        byte_transport,
        frame_error=frame_error,
    )
    return byte_transport, frame_transport
