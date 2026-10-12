"""RESP 27 (RESP_CODE_CHANNEL_DATA_RECV) parity tests (audit T5, 2026-10-12).

Reference facts (read-only clone, HEAD a366955c):
- `#define RESP_CODE_CHANNEL_DATA_RECV 27` -> MyMesh.cpp:98
- the device builds it for group datagrams (image/binary messages):
  `[code][snr][reserved1][reserved2][channel_idx][path_len_byte][data_type LE16][data_len][payload]`
  -> MyMesh.cpp:600-616 (onChannelDataRecv)
- it is delivered as a reply to CMD_SYNC_NEXT_MESSAGE from the offline queue; the
  official client must advance the queue-sync state machine for it
  (meshcore_connector.dart:6002-6013 — its comment states that leaving code 27
  unhandled stalls the queue-sync timeout and blocks every queued message behind
  it), and `MyMesh.h:214-217` counts code 27 as a channel message.

Before this fix our sync path did not expect code 27, so a queued datagram produced
"unexpected response code: 27" and the drain aborted.

Like the other parsers, parse_channel_data_recv() receives the payload WITHOUT the
code byte (MessageEvent.code carries the code).
"""

import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meshcorium"))

WEB = pathlib.Path(__file__).resolve().parent.parent / "meshcorium" / "meshcorium_web.py"

from meshcorium_client import (  # noqa: E402
    RESP_CHANNEL_DATA_RECV,
    MeshCoreError,
    MeshCoreClient,
    parse_channel_data_recv,
)


class FakeTransport:
    transport_type = "fake"
    timeout = 0.5

    def write_frame(self, payload: bytes) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


class StubHub:
    """Returns a canned response frame instead of running the reader loop."""

    def __init__(self, frame: bytes):
        self._frame = frame

    def ensure_send_allowed(self) -> None:
        pass

    def send_and_await_matching_response(self, send_frame, matcher, *, deadline_monotonic=None):
        send_frame()
        frame = self._frame
        code = int(frame[0])
        if code in matcher.expected_codes:
            return frame
        raise MeshCoreError(matcher.unexpected_error(frame))


def _client(frame: bytes) -> MeshCoreClient:
    fake = FakeTransport()
    client = MeshCoreClient("fake-port", transport=fake, frame_transport=fake, open_settle=0.0)
    client._frame_hub = StubHub(frame)
    return client


def test_code_matches_reference():
    assert RESP_CHANNEL_DATA_RECV == 27


def test_parser_follows_reference_layout():
    # payload after the code byte: [snr][rsv1][rsv2][channel_idx][path_byte][data_type LE16][data_len][payload]
    snr_byte = 0xFE  # -2 raw -> -0.5 dB (signed byte / 4.0, as in the reference docs)
    data = b"\x01\x02\x03hello"
    frame = bytes([27, snr_byte, 0, 0, 5, 0x41, 0x09, 0x00, len(data)]) + data
    event = _client(frame).sync_next_message()
    assert event is not None
    assert event.code == 27
    d = parse_channel_data_recv(event.payload)
    assert d.snr == -0.5
    assert d.channel_idx == 5
    assert d.path_len == 1          # 0x41: hash width code 1 (2 bytes), hop count 1
    assert d.data_type == 9
    assert d.data_len == len(data)
    assert d.payload == data


def test_parser_rejects_short_payload():
    try:
        parse_channel_data_recv(bytes([0, 0, 0, 1]))
    except MeshCoreError as exc:
        assert "CHANNEL_DATA_RECV" in str(exc)
    else:
        raise AssertionError("short datagram payload must raise")


def test_parser_rejects_declared_length_beyond_frame():
    payload = bytes([0, 0, 0, 1, 0, 0x00, 0x00, 10]) + b"abc"
    try:
        parse_channel_data_recv(payload)
    except MeshCoreError as exc:
        assert "10" in str(exc)
    else:
        raise AssertionError("data_len beyond the frame must raise")


def test_sync_next_message_accepts_datagram_code():
    frame = bytes([27, 0, 0, 0, 1, 0, 0x00, 0x00, 2]) + b"hi"
    event = _client(frame).sync_next_message()
    assert event is not None
    assert event.code == 27
    assert event.payload == bytes([0, 0, 0, 1, 0, 0x00, 0x00, 2]) + b"hi"


def test_web_dispatch_has_datagram_branch():
    """The web message dispatcher must handle code 27 explicitly.

    meshcorium_web has import side effects, so this is checked on the AST, in the
    same style as tests/test_nameerror_regression.py: the dispatcher must reference
    RESP_CHANNEL_DATA_RECV and parse_channel_data_recv (imported from the client).
    """
    tree = ast.parse(WEB.read_text(encoding="utf-8"))
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_process_background_message_event"),
        None,
    )
    assert func is not None, "_process_background_message_event not found"
    names = {
        node.id for node in ast.walk(func)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert "RESP_CHANNEL_DATA_RECV" in names, "dispatcher does not handle code 27"
    assert "parse_channel_data_recv" in names, "dispatcher does not parse datagram payloads"
