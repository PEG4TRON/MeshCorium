"""Push / response payload format tests (audit T4, 2026-10-12).

Reference layouts (read-only clone, HEAD a366955c):
- SEND_CONFIRMED (0x82): `processAck` writes [code][ack_hash:4 LE][trip_time:4] = 9 bytes
  (MyMesh.cpp:416-421); official dart parses exactly that
  (meshcore_connector.dart:7638-7648).
- RESP_SENT (6): [code][is_flood][ack_hash:4 LE][timeout:4] = 10 bytes
  (MyMesh.cpp:1120-1124, second site :1541-1544); dart `_handleMessageSent`
  (meshcore_connector.dart:7538-7549).
- LOGIN_SUCCESS (0x85): [code][permissions][pubkey_prefix:6][tag/ts:4 LE][acl][fw_level]
  (MyMesh.cpp:690-703) — already parity in parse_repeater_login_push.

The parsers historically supported a legacy 6-byte pubkey-prefix variant of the ack
field. That variant is NOT emitted by any version of the reference firmware
(check `git show f58a34f5:examples/companion_radio/MyMesh.cpp` in the reference
clone — always `memcpy(&out_frame[2], &expected_ack, 4)`). The tests below pin the
reference layout as the primary interpretation so a future refactor cannot
mis-read it.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meshcorium"))

from meshcorium_client import (  # noqa: E402
    MeshCoreError,
    parse_repeater_login_push,
    parse_send_confirmed_push,
    parse_sent_message_info,
)


def test_send_confirmed_reference_layout():
    # [0x82][ack_hash:4][trip_time:4] = 9 bytes
    frame = bytes([0x82]) + struct.pack("<I", 0xDEADBEEF) + struct.pack("<I", 1500)
    ack, trip = parse_send_confirmed_push(frame)
    assert ack == struct.pack("<I", 0xDEADBEEF)
    assert trip == 1500
    assert len(ack) == 4


def test_send_confirmed_rejects_short_payload():
    try:
        parse_send_confirmed_push(bytes([0x82]))
    except MeshCoreError as exc:
        assert "SEND_CONFIRMED" in str(exc)
    else:
        raise AssertionError("short push must raise")


def test_resp_sent_reference_layout():
    # [6][is_flood][ack_hash:4][timeout:4] = 10 bytes
    frame = bytes([6, 1]) + struct.pack("<I", 0x11223344) + struct.pack("<I", 3000)
    info = parse_sent_message_info(frame)
    assert info.route_flag == 1
    assert info.expected_ack == struct.pack("<I", 0x11223344)
    assert len(info.expected_ack) == 4
    assert info.suggested_timeout_ms == 3000


def test_resp_sent_rejects_short_frame():
    try:
        parse_sent_message_info(bytes([6, 0]))
    except MeshCoreError as exc:
        assert "MSG_SENT" in str(exc)
    else:
        raise AssertionError("short RESP_SENT frame must raise")


def test_login_push_reference_layout():
    # [0x85][permissions][pubkey:6][ts:4][acl][fw_level]
    frame = (
        bytes([0x85, 3])
        + bytes.fromhex("aabbccddeeff")
        + struct.pack("<I", 1786753548)
        + bytes([0x0F, 7])
    )
    success, prefix, is_admin, tag, acl, fw = parse_repeater_login_push(frame)
    assert success is True
    assert prefix == bytes.fromhex("aabbccddeeff")
    assert is_admin == 3
    assert tag == 1786753548
    assert acl == 0x0F
    assert fw == 7
