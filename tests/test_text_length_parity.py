"""Text-length parity tests vs MeshCore reference (audit T2, 2026-10-12).

Reference facts (read-only clone, HEAD a366955c):
- `#define MAX_TEXT_LEN (10*CIPHER_BLOCK_SIZE)` = 160 -> MeshCore/src/helpers/BaseChatMesh.h:8
- send path refuses overlong text: `if (text_len > MAX_TEXT_LEN) return NULL;`
  and `if (attempt > 3 && text_len > MAX_TEXT_LEN-2) return NULL;`
  -> BaseChatMesh.cpp:422-423 (composeMsgPacket), :463 (sendCommandData).
  The device answers ERR_CODE_TABLE_FULL — an ambiguous error for the caller.
- official client guards client-side instead (meshcore-open): `maxTextPayloadBytes = 160`
  (meshcore_protocol.dart:373), guard at meshcore_connector.dart:4276-4282, and
  `maxTextPayloadBytesAfterFullLengthAttempts = 160 - 2` (dart:377) because from
  attempt 4 the firmware appends [0][attempt] to the payload.
- group text is stored as "<sender>: <text>" and truncated to MAX_TEXT_LEN at the
  device (BaseChatMesh.cpp:492-497), so the text budget for a channel send is
  MAX_TEXT_LEN - len(sender_name) - 2 when the sender name is known.

We guard client-side so the caller gets an explicit error instead of an ambiguous
device ERR — same behavior as the official client.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meshcorium"))

from meshcorium_client import (  # noqa: E402
    MeshCoreError,
    MAX_TEXT_PAYLOAD_BYTES,
    MAX_TEXT_PAYLOAD_BYTES_AFTER_FULL_LENGTH_ATTEMPTS,
    MeshCoreClient,
    channel_text_limit,
    contact_text_limit,
)


class StopAfterPayload(Exception):
    """Raised by the stub hub instead of waiting for a device response."""


class RecordingTransport:
    transport_type = "fake"

    def __init__(self):
        self.payloads = []
        self.timeout = 0.5

    def write_frame(self, payload: bytes) -> None:
        self.payloads.append(bytes(payload))

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


class StubHub:
    """Records what the guard allowed through, then stops before any reader loop."""

    def __init__(self, transport):
        self._transport = transport

    def ensure_send_allowed(self) -> None:
        pass

    def send_and_await_matching_response(self, send_frame, matcher, *, deadline_monotonic=None):
        send_frame()
        raise StopAfterPayload("stop after payload build")


def _client() -> MeshCoreClient:
    fake = RecordingTransport()
    client = MeshCoreClient("fake-port", transport=fake, frame_transport=fake, open_settle=0.0)
    client._frame_hub = StubHub(fake)
    return client


def _sent_payload(client, method, *args, **kwargs):
    try:
        getattr(client, method)(*args, **kwargs)
    except StopAfterPayload:
        return client.transport.payloads
    raise AssertionError("stub hub did not reach the send stage")


def test_limits_match_reference():
    assert MAX_TEXT_PAYLOAD_BYTES == 160
    assert MAX_TEXT_PAYLOAD_BYTES_AFTER_FULL_LENGTH_ATTEMPTS == 158
    assert contact_text_limit(attempt=0) == 160
    assert contact_text_limit(attempt=3) == 160
    assert contact_text_limit(attempt=4) == 158


def test_channel_budget_accounts_for_sender_name_prefix():
    assert channel_text_limit("Node") == 160 - (4 + 2)
    # reference maxNameSize = 32 -> 31 usable name bytes (meshcore_protocol.dart:362)
    assert channel_text_limit("n" * 31) == 160 - (31 + 2)
    # unknown sender name: fall back to the device-level check (text_len <= MAX_TEXT_LEN)
    assert channel_text_limit(None) == 160


def test_contact_send_rejects_overlong_text_before_transmit():
    client = _client()
    try:
        client.send_contact_text_message(bytes.fromhex("aa" * 6), "x" * 161)
    except MeshCoreError as exc:
        assert "160" in str(exc)
    else:
        raise AssertionError("overlong text must be rejected before sending")
    assert client.transport.payloads == []


def test_contact_send_accepts_text_at_exact_limit():
    client = _client()
    payloads = _sent_payload(client, "send_contact_text_message", bytes.fromhex("bb" * 6), "x" * 160)
    frame = payloads[0]
    assert len(frame) == 3 + 4 + 6 + 160  # cmd + txt_type + attempt + ts + prefix + text


def test_attempt_4_budget_shrinks_by_two():
    client = _client()
    try:
        client.send_contact_text_message(bytes.fromhex("cc" * 6), "x" * 159, attempt=4)
    except MeshCoreError as exc:
        assert "158" in str(exc)
    else:
        raise AssertionError("attempt > 3 must use MAX_TEXT_LEN - 2")


def test_cli_command_shares_the_same_limit():
    client = _client()
    try:
        client.send_repeater_cli_command(bytes.fromhex("dd" * 6), "y" * 161)
    except MeshCoreError as exc:
        assert "160" in str(exc)
    else:
        raise AssertionError("CLI data is text payload too — same MAX_TEXT_LEN")


def test_channel_send_rejects_overlong_text_before_transmit():
    # sender name unknown to the client -> device-level budget (text_len <= 160)
    client = _client()
    try:
        client.send_channel_text_message(1, "z" * 161)
    except MeshCoreError as exc:
        assert "160" in str(exc)
    else:
        raise AssertionError("overlong channel text must be rejected before sending")
    assert client.transport.payloads == []


def test_channel_send_uses_sender_name_prefix_budget_after_app_start():
    client = _client()
    # app_start caches the node name (SelfInfo.name) for the budget calculation
    client._self_name = "Node"
    try:
        client.send_channel_text_message(1, "z" * 155)
    except MeshCoreError as exc:
        assert "154" in str(exc)  # 160 - ("Node: " = 6)
    else:
        raise AssertionError("channel text budget must account for '<sender>: ' prefix")
    assert client.transport.payloads == []
