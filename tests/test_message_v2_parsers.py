"""Tests for legacy V2 message parsers (RESP_CONTACT_MSG_RECV=7, RESP_CHANNEL_MSG_RECV=8).

V2 is the pre-V3 wire format that the companion firmware emits when the app
target protocol version is < 3 (e.g. after a device reboot that reset
app_target_ver to 0). It carries no SNR and no embedded path hashes.

Layouts (from companion firmware MyMesh.cpp):
- channel: [channel_idx:1][path_len_byte:1][txt_type:1][sender_ts:4 LE][text]
- contact: [pubkey_prefix:6][path_len_byte:1][txt_type:1][sender_ts:4 LE][signature:4 if signed][text]
"""

import os
import struct
import sys

CLIENT_PY = os.path.join(os.path.dirname(__file__), "..", "meshcorium", "meshcorium_client.py")
sys.path.insert(0, os.path.dirname(CLIENT_PY))

from meshcorium_client import (  # noqa: E402
    MeshCoreError,
    parse_channel_message_v2,
    parse_contact_message_v2,
)


def test_channel_v2_plain():
    ts = 1786753548
    payload = bytes([0x00, 0x44, 0x00]) + struct.pack("<I", ts) + "ANANAS 🍍: Есть кто не спит?".encode()
    d = parse_channel_message_v2(payload)
    assert d.channel_idx == 0
    assert d.path_len == 4
    assert d.path_hashes == ""
    assert d.snr is None
    assert d.txt_type == 0
    assert d.sender_timestamp == ts
    assert d.text == "ANANAS 🍍: Есть кто не спит?"


def test_channel_v2_real_payload_from_log():
    # Real payload from 15.08 delivery log (resp_code 8):
    # "0044000cb27f6a" + "ANANAS 🍍: Есть кто не спит?"
    hex_payload = (
        "0044000cb27f6a414e414e415320f09f8d8d3a20d095d181d182d18c"
        "20d0bad182d0be20d0bdd0b520d181d0bfd0b8d1823f"
    )
    d = parse_channel_message_v2(bytes.fromhex(hex_payload))
    assert d.channel_idx == 0
    assert d.path_len == 4
    assert d.sender_timestamp == 1786753548
    assert d.text == "ANANAS 🍍: Есть кто не спит?"
    assert d.snr is None


def test_channel_v2_path_len_ff():
    # path_len_byte 0xFF = direct / non-flood route marker (like V3)
    ts = 1786753548
    payload = bytes([0x01, 0xFF, 0x00]) + struct.pack("<I", ts) + b"direct"
    d = parse_channel_message_v2(payload)
    assert d.path_len == 255
    assert d.text == "direct"


def test_channel_v2_short_frame_rejected():
    try:
        parse_channel_message_v2(b"\x00\x01")
        raise AssertionError("short frame must raise MeshCoreError")
    except MeshCoreError:
        pass


def test_contact_v2_plain():
    ts = 1786753548
    pubkey = bytes.fromhex("3a3993c7a994")
    payload = pubkey + bytes([0x02, 0x00]) + struct.pack("<I", ts) + b"Hello contact"
    d = parse_contact_message_v2(payload)
    assert d.pubkey_prefix == "3a3993c7a994"
    assert d.path_len == 2
    assert d.path_hashes == ""
    assert d.snr is None
    assert d.sender_timestamp == ts
    assert d.signature_hex is None
    assert d.text == "Hello contact"


def test_contact_v2_signed():
    ts = 1786753548
    pubkey = bytes.fromhex("3a3993c7a994")
    payload = pubkey + bytes([0x05, 0x02]) + struct.pack("<I", ts) + b"\xde\xad\xbe\xef" + b"@[Name] hello"
    d = parse_contact_message_v2(payload)
    assert d.path_len == 5
    assert d.txt_type == 2
    assert d.signature_hex == "deadbeef"
    assert d.text == "@[Name] hello"


def test_contact_v2_short_frame_rejected():
    try:
        parse_contact_message_v2(b"\x00\x01\x02")
        raise AssertionError("short frame must raise MeshCoreError")
    except MeshCoreError:
        pass
