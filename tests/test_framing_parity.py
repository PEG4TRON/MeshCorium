"""Framing parity tests vs MeshCore reference (audit T1, 2026-10-12).

Reference source of truth (read-only clone, HEAD a366955c):
- MAX_FRAME_SIZE = 176  -> MeshCore/src/helpers/BaseSerialInterface.h:5
  ("176 // +4 for transport codes (region scoping)")
- send guard: `if (len > MAX_FRAME_SIZE) return 0;` -> ArduinoSerialInterface.cpp:25-28
- recv guard: length > MAX_FRAME_SIZE -> device truncates to MAX_FRAME_SIZE before memcpy
  (checkRecvFrame, ArduinoSerialInterface.cpp:59-64); our client rejects instead
  (cleaner: a length > 176 can never be a legitimate companion frame).

These tests drive the two missing guards in UsbSerialFrameTransport.write_frame /
read_frame (serial path only; BLE path is deliberately out of scope until a BLE
test environment is available).
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meshcorium"))

from meshcorium_serial_transport import (  # noqa: E402
    MAX_FRAME_PAYLOAD_BYTES,
    SerialFrameError,
    USB_INBOUND_PREFIX,
    USB_OUTBOUND_PREFIX,
    UsbSerialFrameTransport,
)


class FakeByteTransport:
    """Minimal byte transport: scripted reads, captured writes."""

    def __init__(self, feed: bytes = b""):
        self._feed = feed
        self.written = bytearray()
        self.port = "/dev/null"
        self.timeout = 1.0

    def read(self, size: int) -> bytes:
        chunk = self._feed[:size]
        self._feed = self._feed[size:]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        pass


def test_max_frame_constant_matches_reference():
    assert MAX_FRAME_PAYLOAD_BYTES == 176


def test_write_frame_within_limit():
    t = FakeByteTransport()
    transport = UsbSerialFrameTransport(t)
    transport.write_frame(bytes([0x01]) + b"x" * 175)  # 176 bytes total
    assert bytes(t.written[:1]) == USB_INBOUND_PREFIX
    assert struct.unpack("<H", bytes(t.written[1:3]))[0] == 176
    assert len(t.written) == 3 + 176


def test_write_frame_over_limit_is_rejected():
    t = FakeByteTransport()
    transport = UsbSerialFrameTransport(t)
    try:
        transport.write_frame(b"x" * 177)
    except SerialFrameError as exc:
        assert "176" in str(exc)
    else:
        raise AssertionError("oversize frame must be rejected before it hits the device")
    # nothing was put on the wire
    assert bytes(t.written) == b""


def test_read_frame_rejects_bogus_length():
    # device-side would truncate; client must not try to read 177+ bytes
    t = FakeByteTransport(USB_OUTBOUND_PREFIX + struct.pack("<H", 200))
    transport = UsbSerialFrameTransport(t)
    try:
        transport.read_frame()
    except SerialFrameError as exc:
        assert "176" in str(exc)
    else:
        raise AssertionError("frame length above MAX_FRAME_SIZE must be rejected")


def test_read_frame_at_limit_is_accepted():
    frame = USB_OUTBOUND_PREFIX + struct.pack("<H", 176) + b"x" * 176
    t = FakeByteTransport(frame)
    transport = UsbSerialFrameTransport(t)
    got = transport.read_frame()
    assert len(got) == 176


def test_resync_within_bound_still_works():
    # garbage bytes before the next frame prefix are discarded (bounded), as before
    t = FakeByteTransport(b"\x00\x01\x02" + USB_OUTBOUND_PREFIX + struct.pack("<H", 1) + b"A")
    transport = UsbSerialFrameTransport(t)
    assert transport.read_frame() == b"A"
