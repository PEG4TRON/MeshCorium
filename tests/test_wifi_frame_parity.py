"""Wifi/TCP frame-size parity (audit T3, 2026-10-12).

MAX_FRAME_SIZE is transport-wide in the reference: `#define MAX_FRAME_SIZE 176`
(BaseSerialInterface.h:5, "176 // +4 for transport codes (region scoping)") and the
same guard is used by every interface —
  SerialWifiInterface.cpp:22, SerialEthernetInterface.cpp:23,
  nrf52/SerialBLEInterface.cpp:277, esp32/SerialBLEInterface.cpp:169,
  ArduinoSerialInterface.cpp:25.

Our wifi path had WIFI_MAX_FRAME_PAYLOAD = 172, which is the pre-region-scoping value
(check `git show f58a34f5:src/helpers/BaseSerialInterface.h` in the reference clone).
A legitimate companion frame carrying region transport codes is 173..176 bytes, so the
wifi guard rejected frames the device would accept.

The write path is unchanged in behavior beyond the limit; the read-path truncation in
the reference (frame_length > MAX_FRAME_SIZE → skip, SerialWifiInterface.cpp:130) is
represented here as a rejection, which is stricter and keeps the stream in sync.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meshcorium"))

from meshcorium_serial_transport import MAX_FRAME_PAYLOAD_BYTES  # noqa: E402
from meshcorium_wifi_transport import (  # noqa: E402
    WIFI_MAX_FRAME_PAYLOAD,
    WifiFrameTransport,
)


class FakeByteTransport:
    def __init__(self, feed: bytes = b""):
        self._feed = feed
        self.written = bytearray()
        self.port = "fake:0"
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

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_wifi_limit_matches_reference_max_frame_size():
    assert MAX_FRAME_PAYLOAD_BYTES == 176
    assert WIFI_MAX_FRAME_PAYLOAD == MAX_FRAME_PAYLOAD_BYTES


def test_wifi_accepts_frame_with_region_transport_codes():
    # 173..176-byte frames are legitimate (region transport codes), they must not be rejected
    t = FakeByteTransport(b">" + struct.pack("<H", 173) + b"x" * 173)
    transport = WifiFrameTransport(t)
    assert len(transport.read_frame()) == 173


def test_wifi_rejects_above_limit():
    t = FakeByteTransport(b">" + struct.pack("<H", 177) + b"x" * 177)
    transport = WifiFrameTransport(t)
    try:
        transport.read_frame()
    except Exception as exc:
        assert "176" in str(exc)
    else:
        raise AssertionError("frame above MAX_FRAME_SIZE must be rejected")
