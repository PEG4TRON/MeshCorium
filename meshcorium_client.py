#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import struct
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable

from meshcorium_serial_transport import (
    SerialException,
    SerialPortTransport,
    UsbSerialFrameTransport,
    discover_serial_ports,
)

DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 4.0
DEFAULT_OPEN_SETTLE = 1.25
DEFAULT_APP_NAME = "meshcorium-usb-client"
DEFAULT_PROTOCOL_VERSION = 3
DEFAULT_APP_VERSION = 1
MESHCORE_PUBLIC_CHANNEL_NAME = "#public"
MESHCORE_PUBLIC_CHANNEL_PSK_HEX = "8b3387e9c5cdea6ac9e5edbaa115cd72"
MESHCORE_PUBLIC_CHANNEL_PSK = bytes.fromhex(MESHCORE_PUBLIC_CHANNEL_PSK_HEX)


CMD_APP_START = 1
CMD_SEND_TXT_MSG = 2
CMD_SEND_CHANNEL_MSG = 3
CMD_SEND_SELF_ADVERT = 7
CMD_SET_ADVERT_NAME = 8
CMD_GET_CONTACTS = 4
CMD_ADD_UPDATE_CONTACT = 9
CMD_RESET_PATH = 13
CMD_SET_ADVERT_LATLON = 14
CMD_REMOVE_CONTACT = 15


def normalize_meshcore_channel_name(channel_name: str) -> str:
    normalized = str(channel_name or "").strip()
    if normalized.lower() == MESHCORE_PUBLIC_CHANNEL_NAME:
        return MESHCORE_PUBLIC_CHANNEL_NAME
    return normalized


def is_meshcore_public_channel_name(channel_name: str) -> bool:
    return normalize_meshcore_channel_name(channel_name).lower() == MESHCORE_PUBLIC_CHANNEL_NAME


def derive_meshcore_channel_secret(channel_name: str, channel_secret: bytes | None = None) -> bytes:
    normalized_name = normalize_meshcore_channel_name(channel_name)
    if not normalized_name:
        raise ValueError("channel name is required")
    if is_meshcore_public_channel_name(normalized_name):
        return bytes(MESHCORE_PUBLIC_CHANNEL_PSK)
    if normalized_name.startswith("#"):
        return hashlib.sha256(normalized_name.encode("utf-8")).digest()[:16]
    if channel_secret is None:
        return hashlib.sha256(normalized_name.encode("utf-8")).digest()[:16]
    resolved_secret = bytes(channel_secret)
    if len(resolved_secret) != 16:
        raise ValueError("channel secret must be exactly 16 bytes")
    return resolved_secret
CMD_SHARE_CONTACT = 16
CMD_EXPORT_CONTACT = 17
CMD_IMPORT_CONTACT = 18
CMD_GET_DEVICE_TIME = 5
CMD_SET_DEVICE_TIME = 6
CMD_SYNC_NEXT_MESSAGE = 10
CMD_DEVICE_QUERY = 22
CMD_SEND_LOGIN = 26
CMD_SEND_STATUS_REQ = 27
CMD_GET_CONTACT_BY_KEY = 30
CMD_SET_OTHER_PARAMS = 38
CMD_GET_SELF_TELEMETRY = 39
CMD_SEND_BINARY_REQ = 50
CMD_GET_CHANNEL = 31
CMD_SET_CHANNEL = 32
CMD_SEND_TRACE_PATH = 36

RESP_OK = 0
RESP_ERR = 1
RESP_CONTACTS_START = 2
RESP_CONTACT = 3
RESP_END_OF_CONTACTS = 4
RESP_SELF_INFO = 5
RESP_SENT = 6
RESP_CONTACT_MSG_RECV = 7
RESP_CHANNEL_MSG_RECV = 8
RESP_CURR_TIME = 9
RESP_NO_MORE_MESSAGES = 10
RESP_EXPORT_CONTACT = 11
RESP_BATT_AND_STORAGE = 12
RESP_DEVICE_INFO = 13
RESP_CONTACT_MSG_RECV_V3 = 16
RESP_CHANNEL_MSG_RECV_V3 = 17
RESP_CHANNEL_INFO = 18
RESP_STATS = 24

PUSH_ADVERT = 0x80
PUSH_PATH_UPDATED = 0x81
PUSH_SEND_CONFIRMED = 0x82
PUSH_MSG_WAITING = 0x83
PUSH_RAW_DATA = 0x84
PUSH_LOGIN_SUCCESS = 0x85
PUSH_LOGIN_FAIL = 0x86
PUSH_STATUS_RESPONSE = 0x87
PUSH_LOG_RX_DATA = 0x88
PUSH_TRACE_DATA = 0x89
PUSH_NEW_ADVERT = 0x8A
PUSH_TELEMETRY_RESPONSE = 0x8B
PUSH_BINARY_RESPONSE = 0x8C
PUSH_CONTROL_DATA = 0x8E

CONTACT_SEND_RESPONSE_TIMEOUT_SECS = 12.0
CHANNEL_SEND_RESPONSE_TIMEOUT_SECS = 15.0


class MeshCoreError(RuntimeError):
    pass


def is_push_code(code: int) -> bool:
    return code >= 0x80


def decode_c_string(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def format_hex(raw: bytes) -> str:
    return raw.hex()


def format_latlon(value: int) -> float:
    return value / 1_000_000.0


def utc_now_epoch() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


@dataclasses.dataclass(slots=True)
class DeviceInfo:
    firmware_ver: int
    max_contacts_div_2: int
    max_channels: int
    ble_pin: int
    firmware_build_date: str
    manufacturer_model: str
    semantic_version: str


@dataclasses.dataclass(slots=True)
class SelfInfo:
    adv_type: int
    tx_power_dbm: int
    max_tx_power: int
    public_key: bytes
    adv_lat: int
    adv_lon: int
    multi_acks: int
    advert_loc_policy: int
    telemetry_modes: int
    manual_add_contacts: int
    radio_freq: int
    radio_bw: int
    radio_sf: int
    radio_cr: int
    name: str


@dataclasses.dataclass(slots=True)
class Contact:
    public_key: bytes
    adv_type: int
    flags: int
    path_len_byte: int
    out_path_len: int
    out_path_hash_len: int
    out_path: bytes
    adv_name: str
    last_advert: int
    adv_lat: int
    adv_lon: int
    lastmod: int
    raw_payload_hex: str


@dataclasses.dataclass(slots=True)
class ChannelInfo:
    channel_idx: int
    channel_name: str
    channel_secret: bytes
    channel_hash: str


@dataclasses.dataclass(slots=True)
class RadioStats:
    noise_floor: int
    last_rssi: int
    last_snr: float
    tx_air_secs: int
    rx_air_secs: int


@dataclasses.dataclass(slots=True)
class CoreStats:
    battery_mv: int
    uptime_secs: int
    errors: int
    queue_len: int


@dataclasses.dataclass(slots=True)
class SelfTelemetry:
    public_key_prefix: str
    battery_mv: int | None
    battery_percent: int | None
    voltage: float | None
    raw_hex: str


@dataclasses.dataclass(slots=True)
class BatteryInfo:
    level: int
    used_kb: int | None
    total_kb: int | None


@dataclasses.dataclass(slots=True)
class ContactMessageV3Info:
    pubkey_prefix: str
    path_len: int
    path_hashes: str
    snr: float
    txt_type: int
    sender_timestamp: int
    signature_hex: str | None
    text: str


@dataclasses.dataclass(slots=True)
class ChannelMessageV3Info:
    channel_idx: int
    path_len: int
    path_hashes: str
    txt_type: int
    sender_timestamp: int
    snr: float
    text: str


@dataclasses.dataclass(slots=True)
class MessageEvent:
    code: int
    payload: bytes


@dataclasses.dataclass(slots=True)
class SentMessageInfo:
    route_flag: int
    expected_ack: bytes
    suggested_timeout_ms: int


@dataclasses.dataclass(slots=True)
class RepeaterLoginResult:
    success: bool
    public_key_prefix: str
    route_flag: int
    expected_ack: bytes
    suggested_timeout_ms: int
    is_admin: bool
    login_tag: int | None
    acl_permissions: int | None
    firmware_level: int | None


@dataclasses.dataclass(slots=True)
class TraceHop:
    hash_hex: str | None
    snr: float | None


@dataclasses.dataclass(slots=True)
class TraceDataInfo:
    tag: int
    auth_code: int
    flags: int
    path_hash_len: int
    path_hops: list[TraceHop]
    final_snr: float | None


def parse_send_confirmed_push(frame: bytes) -> tuple[bytes, int | None]:
    if not frame or frame[0] != PUSH_SEND_CONFIRMED:
        raise MeshCoreError(f"expected SEND_CONFIRMED push, got code {frame[:1].hex() if frame else 'empty'}")
    payload_len = len(frame) - 1
    if payload_len >= 10:
        return frame[1:7], int.from_bytes(frame[7:11], byteorder="little", signed=False)
    if payload_len >= 8:
        ack_len = payload_len - 4
        return frame[1:1 + ack_len], int.from_bytes(frame[1 + ack_len:1 + ack_len + 4], byteorder="little", signed=False)
    if payload_len < 1 or payload_len > 6:
        raise MeshCoreError(f"unsupported SEND_CONFIRMED payload length: {payload_len} bytes")
    return frame[1:1 + payload_len], None


def ack_codes_match(expected_ack: bytes, received_ack: bytes) -> bool:
    if not expected_ack or not received_ack:
        return False
    overlap = min(len(expected_ack), len(received_ack))
    if overlap < 4:
        return len(expected_ack) == len(received_ack) and expected_ack == received_ack
    return expected_ack[:overlap] == received_ack[:overlap]


def parse_repeater_login_push(frame: bytes) -> tuple[bool, bytes, int, int | None, int | None, int | None]:
    if not frame or frame[0] not in (PUSH_LOGIN_SUCCESS, PUSH_LOGIN_FAIL):
        raise MeshCoreError(f"expected LOGIN_SUCCESS/LOGIN_FAIL push, got code {frame[:1].hex() if frame else 'empty'}")
    if len(frame) < 8:
        raise MeshCoreError(f"short repeater login push: {len(frame)} bytes")
    success = frame[0] == PUSH_LOGIN_SUCCESS
    is_admin = int(frame[1]) if success else 0
    public_key_prefix = bytes(frame[2:8])
    login_tag = struct.unpack_from("<I", frame, 8)[0] if success and len(frame) >= 12 else None
    acl_permissions = int(frame[12]) if success and len(frame) >= 13 else None
    firmware_level = int(frame[13]) if success and len(frame) >= 14 else None
    return success, public_key_prefix, is_admin, login_tag, acl_permissions, firmware_level


def parse_trace_data_push(frame: bytes) -> TraceDataInfo:
    if not frame or frame[0] != PUSH_TRACE_DATA:
        raise MeshCoreError(f"expected TRACE_DATA push, got code {frame[:1].hex() if frame else 'empty'}")
    if len(frame) < 12:
        raise MeshCoreError(f"short TRACE_DATA push: {len(frame)} bytes")
    path_len_raw = frame[2]
    flags = frame[3]
    tag = struct.unpack_from("<I", frame, 4)[0]
    auth_code = struct.unpack_from("<I", frame, 8)[0]
    path_hash_len = 1 << (flags & 0x03)
    if path_hash_len <= 0:
        raise MeshCoreError(f"invalid TRACE_DATA path hash len from flags={flags}")
    if path_len_raw % path_hash_len != 0:
        raise MeshCoreError(
            f"TRACE_DATA path bytes {path_len_raw} not divisible by path hash len {path_hash_len}"
        )
    hop_count = path_len_raw // path_hash_len
    offset = 12
    expected_len = offset + path_len_raw + hop_count + 1
    if len(frame) < expected_len:
        raise MeshCoreError(f"short TRACE_DATA push: {len(frame)} bytes, expected at least {expected_len}")
    path_hops: list[TraceHop] = []
    for _ in range(hop_count):
        path_hops.append(
            TraceHop(
                hash_hex=frame[offset:offset + path_hash_len].hex().upper(),
                snr=None,
            )
        )
        offset += path_hash_len
    for hop in path_hops:
        hop.snr = struct.unpack_from("<b", frame, offset)[0] / 4.0
        offset += 1
    final_snr = struct.unpack_from("<b", frame, offset)[0] / 4.0 if len(frame) > offset else None
    return TraceDataInfo(
        tag=tag,
        auth_code=auth_code,
        flags=flags,
        path_hash_len=path_hash_len,
        path_hops=path_hops,
        final_snr=final_snr,
    )


@dataclasses.dataclass(slots=True)
class QueueDrainResult:
    messages: list[MessageEvent]
    sync_attempts: int
    queue_empty_via_timeout: bool
    queue_empty_error: str
    hit_message_limit: bool


class _PendingPushFrameBuffer:
    def __init__(self):
        self._pending_push_frames: deque[bytes] = deque()

    def pending_push_count(self) -> int:
        return len(self._pending_push_frames)

    def pop_pending_push_frames(self, max_frames: int | None = None) -> list[bytes]:
        if max_frames is None or max_frames <= 0:
            max_frames = len(self._pending_push_frames)
        frames: list[bytes] = []
        while self._pending_push_frames and len(frames) < max_frames:
            frames.append(self._pending_push_frames.popleft())
        return frames

    def push_pending_frame(self, frame: bytes) -> None:
        self._pending_push_frames.append(frame)

    def pop_next_pending_push_frame(self) -> bytes | None:
        if not self._pending_push_frames:
            return None
        return self._pending_push_frames.popleft()

    def pop_matching_pending_push_frame(self, predicate) -> bytes | None:
        if not self._pending_push_frames:
            return None
        remaining: deque[bytes] = deque()
        matched: bytes | None = None
        while self._pending_push_frames:
            frame = self._pending_push_frames.popleft()
            if matched is None and predicate(frame):
                matched = frame
                continue
            remaining.append(frame)
        self._pending_push_frames = remaining
        return matched


@dataclasses.dataclass(slots=True)
class _ResponseFrameMatcher:
    expected_codes: frozenset[int]
    empty_error: str
    err_error: str | None = None
    unexpected_error: object = None

    @classmethod
    def create(
        cls,
        expected_codes: int | Iterable[int],
        *,
        empty_error: str,
        err_error: str | None = None,
        unexpected_error=None,
    ) -> "_ResponseFrameMatcher":
        expected = (
            frozenset([int(expected_codes)])
            if isinstance(expected_codes, int)
            else frozenset(int(item) for item in expected_codes)
        )
        return cls(
            expected_codes=expected,
            empty_error=empty_error,
            err_error=err_error,
            unexpected_error=unexpected_error,
        )

    def matches(self, frame: bytes) -> bool:
        if not frame:
            return False
        code = int(frame[0])
        return code in self.expected_codes or (code == RESP_ERR and self.err_error is not None)

    def validate(self, frame: bytes) -> bytes:
        if not frame:
            raise MeshCoreError(self.empty_error)
        code = int(frame[0])
        if code in self.expected_codes:
            return frame
        if code == RESP_ERR and self.err_error:
            raise MeshCoreError(self.err_error)
        if self.unexpected_error is not None:
            raise MeshCoreError(self.unexpected_error(frame))
        raise MeshCoreError(f"unexpected response code: {code}")


@dataclasses.dataclass(slots=True)
class _RegisteredResponseWaiter:
    matcher: _ResponseFrameMatcher
    matched_frame: bytes | None = None

    def take_frame(self) -> bytes | None:
        frame = self.matched_frame
        self.matched_frame = None
        return frame


class _ResponseWaitRegistry:
    def __init__(self):
        self._waiters: list[_RegisteredResponseWaiter] = []

    def register(self, matcher: _ResponseFrameMatcher) -> _RegisteredResponseWaiter:
        waiter = _RegisteredResponseWaiter(matcher=matcher)
        self._waiters.append(waiter)
        return waiter

    def unregister(self, waiter: _RegisteredResponseWaiter) -> None:
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass

    def waiter_count(self) -> int:
        return len(self._waiters)

    def dispatch(self, frame: bytes) -> _RegisteredResponseWaiter | None:
        for waiter in list(self._waiters):
            if waiter.matcher.matches(frame):
                waiter.matched_frame = frame
                return waiter
        return None


class _ReaderOwnedFrameHub:
    def __init__(
        self,
        *,
        port: str,
        frame_transport,
        push_buffer: _PendingPushFrameBuffer,
        response_wait_registry: _ResponseWaitRegistry,
    ):
        self.port = port
        self._frame_transport = frame_transport
        self._push_buffer = push_buffer
        self._response_wait_registry = response_wait_registry
        self._condition = threading.Condition()
        self._reader_thread: threading.Thread | None = None
        self._reader_error: Exception | None = None
        self._generic_response_waiters = 0
        self._buffered_frame_waiters = 0
        self._unclaimed_response_frames: deque[bytes] = deque()
        self._typed_push_waiters: dict[int, int] = {}
        self._typed_push_frames: dict[int, deque[bytes]] = {}
        self._closed = False

    @staticmethod
    def _is_transient_read_timeout(exc: Exception | None) -> bool:
        return isinstance(exc, MeshCoreError) and str(exc) in {
            "serial timeout while reading 1 bytes, got 0",
            "ble timeout while reading frame",
        }

    def close(self) -> None:
        thread: threading.Thread | None = None
        with self._condition:
            if self._closed:
                return
            self._closed = True
            if self._reader_error is None:
                self._reader_error = MeshCoreError("serial client closed")
            thread = self._reader_thread
            self._condition.notify_all()
        cancel_read = getattr(self._frame_transport, "cancel_read", None)
        if callable(cancel_read):
            try:
                cancel_read()
            except Exception:
                pass
        self._frame_transport.close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.25)

    def ensure_send_allowed(self) -> None:
        if self._closed:
            raise MeshCoreError("serial client closed")

    def response_waiter_count(self) -> int:
        return self._response_wait_registry.waiter_count()

    def _reader_demand_locked(self) -> bool:
        if self._closed:
            return False
        return (
            self._generic_response_waiters > 0
            or self._buffered_frame_waiters > 0
            or any(count > 0 for count in self._typed_push_waiters.values())
            or self._response_wait_registry.waiter_count() > 0
        )

    def _ensure_reader_loop_locked(self) -> None:
        if self._closed:
            raise MeshCoreError("serial client closed")
        thread = self._reader_thread
        if thread is not None and thread.is_alive():
            return
        self._reader_error = None
        thread = threading.Thread(
            target=self._reader_loop,
            name=f"meshcorium-response-reader:{self.port}",
            daemon=True,
        )
        self._reader_thread = thread
        thread.start()

    def _reader_loop(self) -> None:
        while True:
            with self._condition:
                if not self._reader_demand_locked():
                    self._reader_thread = None
                    self._condition.notify_all()
                    return
            try:
                frame = self._frame_transport.read_frame()
            except Exception as exc:
                with self._condition:
                    self._reader_error = exc
                    self._reader_thread = None
                    self._condition.notify_all()
                return
            with self._condition:
                if frame and is_push_code(frame[0]):
                    code = int(frame[0])
                    if int(self._typed_push_waiters.get(code, 0)) > 0:
                        self._typed_push_frames.setdefault(code, deque()).append(frame)
                    else:
                        self._push_buffer.push_pending_frame(frame)
                else:
                    matched_waiter = self._response_wait_registry.dispatch(frame)
                    if matched_waiter is None:
                        self._unclaimed_response_frames.append(frame)
                self._condition.notify_all()

    def _wait_for_reader_activity_locked(
        self,
        deadline_monotonic: float | None,
        *,
        empty_error: str,
    ) -> None:
        if self._closed:
            raise MeshCoreError("serial client closed")
        if self._reader_error is not None:
            if self._is_transient_read_timeout(self._reader_error):
                self._reader_error = None
                if self._reader_demand_locked():
                    self._ensure_reader_loop_locked()
            else:
                raise self._reader_error
        if self._reader_error is not None:
            raise self._reader_error
        if deadline_monotonic is None:
            self._condition.wait()
        else:
            remaining = float(deadline_monotonic) - time.monotonic()
            if remaining <= 0:
                raise MeshCoreError(empty_error)
            self._condition.wait(timeout=remaining)
        if self._reader_error is not None:
            if self._is_transient_read_timeout(self._reader_error):
                self._reader_error = None
                if self._reader_demand_locked():
                    self._ensure_reader_loop_locked()
                return
            raise self._reader_error

    def await_unclaimed_response_frame(
        self,
        *,
        deadline_monotonic: float | None = None,
        empty_error: str = "empty response frame",
    ) -> bytes:
        with self._condition:
            if self._unclaimed_response_frames:
                return self._unclaimed_response_frames.popleft()
            self._generic_response_waiters += 1
            self._ensure_reader_loop_locked()
            try:
                while True:
                    if self._unclaimed_response_frames:
                        return self._unclaimed_response_frames.popleft()
                    self._wait_for_reader_activity_locked(deadline_monotonic, empty_error=empty_error)
            finally:
                self._generic_response_waiters = max(0, self._generic_response_waiters - 1)
                self._condition.notify_all()

    def _pop_matching_typed_push_frame_locked(self, queue_frames: deque[bytes], predicate) -> bytes | None:
        if not queue_frames:
            return None
        remaining: deque[bytes] = deque()
        matched: bytes | None = None
        while queue_frames:
            frame = queue_frames.popleft()
            if matched is None and predicate(frame):
                matched = frame
                continue
            remaining.append(frame)
        queue_frames.extend(remaining)
        return matched

    def _typed_push_waiter_enter_locked(self, code: int) -> None:
        normalized_code = int(code)
        self._typed_push_waiters[normalized_code] = int(self._typed_push_waiters.get(normalized_code, 0)) + 1

    def _typed_push_waiter_leave_locked(self, code: int) -> None:
        normalized_code = int(code)
        next_count = int(self._typed_push_waiters.get(normalized_code, 0)) - 1
        if next_count > 0:
            self._typed_push_waiters[normalized_code] = next_count
            return
        self._typed_push_waiters.pop(normalized_code, None)
        if not self._typed_push_frames.get(normalized_code):
            self._typed_push_frames.pop(normalized_code, None)

    def _pop_matching_typed_push_by_code_locked(self, code: int, predicate) -> bytes | None:
        queue_frames = self._typed_push_frames.get(int(code))
        if not queue_frames:
            return None
        matched = self._pop_matching_typed_push_frame_locked(queue_frames, predicate)
        if not queue_frames:
            self._typed_push_frames.pop(int(code), None)
        return matched

    def _pop_matching_unclaimed_response_locked(self, predicate) -> bytes | None:
        if not self._unclaimed_response_frames:
            return None
        remaining: deque[bytes] = deque()
        matched: bytes | None = None
        while self._unclaimed_response_frames:
            frame = self._unclaimed_response_frames.popleft()
            if matched is None and predicate(frame):
                matched = frame
                continue
            remaining.append(frame)
        self._unclaimed_response_frames = remaining
        return matched

    def await_typed_push_frame(
        self,
        *,
        push_code: int,
        predicate,
        deadline_monotonic: float | None = None,
        empty_error: str,
    ) -> bytes:
        with self._condition:
            normalized_code = int(push_code)
            frame = self._pop_matching_typed_push_by_code_locked(normalized_code, predicate)
            if frame is None:
                frame = self._push_buffer.pop_matching_pending_push_frame(predicate)
            if frame is not None:
                return frame
            self._typed_push_waiter_enter_locked(normalized_code)
            self._ensure_reader_loop_locked()
            try:
                while True:
                    frame = self._pop_matching_typed_push_by_code_locked(normalized_code, predicate)
                    if frame is None:
                        frame = self._push_buffer.pop_matching_pending_push_frame(predicate)
                    if frame is not None:
                        return frame
                    self._wait_for_reader_activity_locked(deadline_monotonic, empty_error=empty_error)
            finally:
                self._typed_push_waiter_leave_locked(normalized_code)
                self._condition.notify_all()

    def pop_unclaimed_response_frame(self) -> bytes | None:
        with self._condition:
            if not self._unclaimed_response_frames:
                return None
            return self._unclaimed_response_frames.popleft()

    def await_push_or_response_frame(
        self,
        *,
        push_codes: Iterable[int] | int,
        response_codes: Iterable[int] | int = (),
        push_predicate=None,
        response_predicate=None,
        deadline_monotonic: float | None = None,
        empty_error: str,
    ) -> bytes:
        push_code_set = (
            frozenset([int(push_codes)])
            if isinstance(push_codes, int)
            else frozenset(int(code) for code in push_codes)
        )
        response_code_set = (
            frozenset([int(response_codes)])
            if isinstance(response_codes, int)
            else frozenset(int(code) for code in response_codes)
        )
        if not push_code_set and not response_code_set:
            raise MeshCoreError("await_push_or_response_frame requires at least one push or response code")

        def _matches_push(frame: bytes) -> bool:
            return (
                bool(frame)
                and int(frame[0]) in push_code_set
                and (push_predicate(frame) if push_predicate is not None else True)
            )

        def _matches_response(frame: bytes) -> bool:
            return (
                bool(frame)
                and int(frame[0]) in response_code_set
                and (response_predicate(frame) if response_predicate is not None else True)
            )

        with self._condition:
            frame = None
            for push_code in push_code_set:
                frame = self._pop_matching_typed_push_by_code_locked(push_code, _matches_push)
                if frame is not None:
                    break
            if frame is None:
                frame = self._push_buffer.pop_matching_pending_push_frame(_matches_push)
            if frame is not None:
                return frame
            response_frame = self._pop_matching_unclaimed_response_locked(_matches_response)
            if response_frame is not None:
                return response_frame
            for push_code in push_code_set:
                self._typed_push_waiter_enter_locked(push_code)
            self._ensure_reader_loop_locked()
            try:
                while True:
                    frame = None
                    for push_code in push_code_set:
                        frame = self._pop_matching_typed_push_by_code_locked(push_code, _matches_push)
                        if frame is not None:
                            break
                    if frame is None:
                        frame = self._push_buffer.pop_matching_pending_push_frame(_matches_push)
                    if frame is not None:
                        return frame
                    response_frame = self._pop_matching_unclaimed_response_locked(_matches_response)
                    if response_frame is not None:
                        return response_frame
                    self._wait_for_reader_activity_locked(deadline_monotonic, empty_error=empty_error)
            finally:
                for push_code in push_code_set:
                    self._typed_push_waiter_leave_locked(push_code)
                self._condition.notify_all()

    def await_telemetry_response_frame(self, *, empty_error: str) -> bytes:
        return self.await_push_or_response_frame(
            push_codes=PUSH_TELEMETRY_RESPONSE,
            response_codes=RESP_ERR,
            empty_error=empty_error,
        )

    def await_next_frame(
        self,
        *,
        deadline_monotonic: float | None = None,
        empty_error: str = "empty frame",
    ) -> bytes:
        with self._condition:
            frame = self._push_buffer.pop_next_pending_push_frame()
            if frame is not None:
                return frame
            if self._unclaimed_response_frames:
                return self._unclaimed_response_frames.popleft()
            self._buffered_frame_waiters += 1
            self._ensure_reader_loop_locked()
            try:
                while True:
                    frame = self._push_buffer.pop_next_pending_push_frame()
                    if frame is not None:
                        return frame
                    if self._unclaimed_response_frames:
                        return self._unclaimed_response_frames.popleft()
                    self._wait_for_reader_activity_locked(deadline_monotonic, empty_error=empty_error)
            finally:
                self._buffered_frame_waiters = max(0, self._buffered_frame_waiters - 1)
                self._condition.notify_all()

    def await_matching_response(
        self,
        matcher: _ResponseFrameMatcher,
        *,
        deadline_monotonic: float | None = None,
    ) -> bytes:
        with self._condition:
            waiter = self._response_wait_registry.register(matcher)
            self._ensure_reader_loop_locked()
            try:
                while True:
                    matched_frame = waiter.take_frame()
                    if matched_frame is not None:
                        frame = matched_frame
                        break
                    self._wait_for_reader_activity_locked(deadline_monotonic, empty_error=matcher.empty_error)
            finally:
                self._response_wait_registry.unregister(waiter)
                self._condition.notify_all()
        return matcher.validate(frame)

    def collect_response_sequence(
        self,
        *,
        start_code: int,
        item_codes: Iterable[int] | int,
        end_code: int,
        start_empty_error: str,
        item_empty_error: str,
        start_unexpected_error,
        item_unexpected_error,
        end_cursor_offset: int | None = None,
        ignored_codes: Iterable[int] | int = (),
        ignored_frame_logger=None,
    ) -> tuple[int, list[bytes]]:
        item_code_set = (
            frozenset([int(item_codes)])
            if isinstance(item_codes, int)
            else frozenset(int(code) for code in item_codes)
        )
        ignored_code_set = (
            frozenset([int(ignored_codes)])
            if isinstance(ignored_codes, int)
            else frozenset(int(code) for code in ignored_codes)
        )

        def _log_ignored_frame(frame: bytes) -> None:
            if ignored_frame_logger is None:
                return
            try:
                ignored_frame_logger(frame)
            except Exception:
                pass

        while True:
            start_frame = self.await_unclaimed_response_frame(empty_error=start_empty_error)
            if start_frame and int(start_frame[0]) == int(start_code):
                break
            if start_frame and int(start_frame[0]) in ignored_code_set:
                _log_ignored_frame(start_frame)
                continue
            raise MeshCoreError(start_unexpected_error(start_frame))
        item_frames: list[bytes] = []
        cursor = 0
        while True:
            frame = self.await_unclaimed_response_frame(empty_error=item_empty_error)
            if frame and int(frame[0]) in item_code_set:
                item_frames.append(frame)
                continue
            if frame and int(frame[0]) == int(end_code):
                if end_cursor_offset is not None and len(frame) >= int(end_cursor_offset) + 4:
                    cursor = struct.unpack_from("<I", frame, int(end_cursor_offset))[0]
                return cursor, item_frames
            if frame and int(frame[0]) in ignored_code_set:
                _log_ignored_frame(frame)
                continue
            raise MeshCoreError(item_unexpected_error(frame))

    def collect_contacts_sequence(self) -> tuple[int, list[bytes]]:
        return self.collect_response_sequence(
            start_code=RESP_CONTACTS_START,
            item_codes=RESP_CONTACT,
            end_code=RESP_END_OF_CONTACTS,
            start_empty_error="empty frame while waiting for CONTACTS_START",
            item_empty_error="empty frame while reading contacts",
            start_unexpected_error=lambda frame: (
                f"expected CONTACTS_START, got code {frame[:1].hex() if frame else 'empty'}"
            ),
            item_unexpected_error=lambda frame: (
                f"unexpected frame while reading contacts: code={frame[0]} hex=0x{frame[0]:02x}"
            ),
            end_cursor_offset=1,
            ignored_codes=(RESP_CHANNEL_INFO,),
            ignored_frame_logger=lambda frame: logging.warning(
                "discarding stray CHANNEL_INFO while reading contacts code=%s hex=%s",
                int(frame[0]) if frame else None,
                frame.hex() if frame else "",
            ),
        )

def parse_device_info(payload: bytes) -> DeviceInfo:
    if len(payload) < 1 + 1 + 1 + 1 + 4 + 12 + 40 + 20:
        raise MeshCoreError(f"short DEVICE_INFO frame: {len(payload)} bytes")
    _, firmware_ver, max_contacts_div_2, max_channels = payload[:4]
    ble_pin = struct.unpack_from("<I", payload, 4)[0]
    build_date = decode_c_string(payload[8:20])
    manufacturer_model = decode_c_string(payload[20:60])
    semantic_version = decode_c_string(payload[60:80])
    return DeviceInfo(
        firmware_ver=firmware_ver,
        max_contacts_div_2=max_contacts_div_2,
        max_channels=max_channels,
        ble_pin=ble_pin,
        firmware_build_date=build_date,
        manufacturer_model=manufacturer_model,
        semantic_version=semantic_version,
    )


def parse_self_info(payload: bytes) -> SelfInfo:
    min_len = 1 + 1 + 1 + 1 + 32 + 4 + 4 + 1 + 1 + 1 + 1 + 4 + 4 + 1 + 1
    if len(payload) < min_len:
        raise MeshCoreError(f"short SELF_INFO frame: {len(payload)} bytes")
    return SelfInfo(
        adv_type=payload[1],
        tx_power_dbm=payload[2],
        max_tx_power=payload[3],
        public_key=payload[4:36],
        adv_lat=struct.unpack_from("<i", payload, 36)[0],
        adv_lon=struct.unpack_from("<i", payload, 40)[0],
        multi_acks=payload[44],
        advert_loc_policy=payload[45],
        telemetry_modes=payload[46],
        manual_add_contacts=payload[47],
        radio_freq=struct.unpack_from("<I", payload, 48)[0],
        radio_bw=struct.unpack_from("<I", payload, 52)[0],
        radio_sf=payload[56],
        radio_cr=payload[57],
        name=decode_c_string(payload[58:]),
    )


def parse_contact(payload: bytes) -> Contact:
    min_len = 1 + 32 + 1 + 1 + 1 + 64 + 32 + 4 + 4 + 4 + 4
    if len(payload) < min_len:
        raise MeshCoreError(f"short CONTACT frame: {len(payload)} bytes")
    plen = payload[35]
    if plen == 0xFF:
        out_path_len = -1
        out_path_hash_len = 0
        out_path = b""
    else:
        out_path_hash_len = (plen >> 6) + 1
        out_path_len = plen & 0x3F
        path_bytes = out_path_len * out_path_hash_len
        out_path = payload[36:36 + path_bytes]
    return Contact(
        public_key=payload[1:33],
        adv_type=payload[33],
        flags=payload[34],
        path_len_byte=plen,
        out_path_len=out_path_len,
        out_path_hash_len=out_path_hash_len,
        out_path=out_path,
        adv_name=decode_c_string(payload[100:132]),
        last_advert=struct.unpack_from("<I", payload, 132)[0],
        adv_lat=struct.unpack_from("<i", payload, 136)[0],
        adv_lon=struct.unpack_from("<i", payload, 140)[0],
        lastmod=struct.unpack_from("<I", payload, 144)[0],
        raw_payload_hex=format_hex(payload),
    )


def parse_message(payload: bytes) -> MessageEvent:
    return MessageEvent(code=payload[0], payload=payload[1:])


def parse_channel_info(payload: bytes) -> ChannelInfo:
    min_len = 1 + 1 + 32 + 16
    if len(payload) < min_len:
        raise MeshCoreError(f"short CHANNEL_INFO frame: {len(payload)} bytes")
    secret = payload[34:50]
    return ChannelInfo(
        channel_idx=payload[1],
        channel_name=decode_c_string(payload[2:34]),
        channel_secret=secret,
        channel_hash=hashlib.sha256(secret).hexdigest()[:2],
    )


def parse_sent_message_info(payload: bytes) -> SentMessageInfo:
    min_len = 1 + 1 + 4 + 4
    if len(payload) < min_len:
        raise MeshCoreError(f"short MSG_SENT frame: {len(payload)} bytes")
    ack_len = 6 if len(payload) >= 12 else 4
    timeout_offset = 2 + ack_len
    if len(payload) < timeout_offset + 4:
        raise MeshCoreError(f"short MSG_SENT frame: {len(payload)} bytes")
    return SentMessageInfo(
        route_flag=payload[1],
        expected_ack=payload[2:2 + ack_len],
        suggested_timeout_ms=struct.unpack_from("<I", payload, timeout_offset)[0],
    )


def parse_radio_stats(payload: bytes) -> RadioStats:
    min_len = 1 + 1 + 2 + 1 + 1 + 4 + 4
    if len(payload) < min_len:
        raise MeshCoreError(f"short STATS_RADIO frame: {len(payload)} bytes")
    if payload[1] != 1:
        raise MeshCoreError(f"unexpected STATS subtype for radio stats: {payload[1]}")
    noise_floor, last_rssi, last_snr_scaled, tx_air_secs, rx_air_secs = struct.unpack_from("<hbbII", payload, 2)
    return RadioStats(
        noise_floor=noise_floor,
        last_rssi=last_rssi,
        last_snr=last_snr_scaled / 4.0,
        tx_air_secs=tx_air_secs,
        rx_air_secs=rx_air_secs,
    )


def parse_core_stats(payload: bytes) -> CoreStats:
    min_len = 1 + 1 + 2 + 4 + 2 + 1
    if len(payload) < min_len:
        raise MeshCoreError(f"short STATS_CORE frame: {len(payload)} bytes")
    if payload[1] != 0:
        raise MeshCoreError(f"unexpected STATS subtype for core stats: {payload[1]}")
    battery_mv, uptime_secs, errors, queue_len = struct.unpack_from("<HIHB", payload, 2)
    return CoreStats(
        battery_mv=battery_mv,
        uptime_secs=uptime_secs,
        errors=errors,
        queue_len=queue_len,
    )


LPP_VALUE_SIZES = {
    0: 1,
    1: 1,
    2: 2,
    3: 2,
    100: 4,
    101: 2,
    102: 1,
    103: 2,
    104: 1,
    113: 6,
    115: 2,
    116: 2,
    117: 2,
    118: 4,
    120: 1,
    121: 2,
    122: 2,
    125: 2,
    128: 2,
    130: 4,
    131: 4,
    132: 2,
    133: 4,
    134: 6,
    135: 3,
    136: 9,
    142: 1,
}


def battery_percent_from_mv(millivolts: int | None) -> int | None:
    if millivolts is None:
        return None
    min_voltage = 3400
    max_voltage = 4200
    if millivolts <= min_voltage:
        return 0
    if millivolts >= max_voltage:
        return 100
    return int((millivolts - min_voltage) * 100 / (max_voltage - min_voltage))


def parse_self_telemetry(frame: bytes) -> SelfTelemetry:
    if not frame or frame[0] != PUSH_TELEMETRY_RESPONSE:
        raise MeshCoreError(f"expected TELEMETRY_RESPONSE push, got code {frame[:1].hex() if frame else 'empty'}")
    if len(frame) < 8:
        raise MeshCoreError(f"short TELEMETRY_RESPONSE frame: {len(frame)} bytes")
    public_key_prefix = frame[2:8].hex()
    payload = frame[8:]
    offset = 0
    voltage = None
    battery_mv = None
    battery_percent = None
    while offset + 2 <= len(payload) and payload[offset] != 0:
        _channel = payload[offset]
        lpp_type = payload[offset + 1]
        offset += 2
        value_size = LPP_VALUE_SIZES.get(lpp_type)
        if value_size is None or offset + value_size > len(payload):
            break
        raw_value = payload[offset:offset + value_size]
        offset += value_size
        if lpp_type == 116 and value_size == 2:
            centivolts = int.from_bytes(raw_value, byteorder="little", signed=False)
            if centivolts > 32767:
                centivolts -= 65536
            voltage = round(centivolts / 100.0, 2)
            if voltage >= 0:
                battery_mv = int(round(voltage * 1000))
        elif lpp_type == 120 and value_size == 1:
            battery_percent = max(0, min(100, int(raw_value[0])))
    if battery_percent is None:
        battery_percent = battery_percent_from_mv(battery_mv)
    return SelfTelemetry(
        public_key_prefix=public_key_prefix,
        battery_mv=battery_mv,
        battery_percent=battery_percent,
        voltage=voltage,
        raw_hex=payload.hex(),
    )


def parse_battery_info(frame: bytes) -> BatteryInfo:
    if not frame or frame[0] != RESP_BATT_AND_STORAGE:
        raise MeshCoreError(f"expected BATT_AND_STORAGE, got code {frame[:1].hex() if frame else 'empty'}")
    if len(frame) < 3:
        raise MeshCoreError(f"short BATT_AND_STORAGE frame: {len(frame)} bytes")
    level = int.from_bytes(frame[1:3], byteorder="little", signed=False)
    used_kb = None
    total_kb = None
    if len(frame) >= 11:
        used_kb = int.from_bytes(frame[3:7], byteorder="little", signed=False)
        total_kb = int.from_bytes(frame[7:11], byteorder="little", signed=False)
    return BatteryInfo(level=level, used_kb=used_kb, total_kb=total_kb)


def parse_contact_message_v3(payload: bytes) -> ContactMessageV3Info:
    min_len = 1 + 2 + 6 + 1 + 1 + 4
    if len(payload) < min_len:
        raise MeshCoreError(f"short CONTACT_MSG_RECV_V3 payload: {len(payload)} bytes")
    snr = struct.unpack_from("<b", payload, 0)[0] / 4.0
    plen = payload[9]
    path_hash_size = 0 if plen == 255 else ((plen >> 6) + 1)
    path_len = plen if plen == 255 else (plen & 0x3F)
    cursor = 10
    path_hashes = ""
    if path_len > 0 and plen != 255:
        path_byte_len = path_len * path_hash_size
        has_path_bytes_flag = bool(payload[1] & 0x01) if len(payload) > 1 else False
        can_fit_path = len(payload) >= cursor + path_byte_len + 1 + 4
        has_valid_txt_type = cursor < len(payload) and payload[cursor] in (0, 1, 2)
        if (has_path_bytes_flag or (can_fit_path and not has_valid_txt_type)) and can_fit_path:
            path_bytes = payload[cursor:cursor + path_byte_len]
            path_hashes = " -> ".join(
                path_bytes[offset:offset + path_hash_size].hex().upper()
                for offset in range(0, len(path_bytes), path_hash_size)
                if len(path_bytes[offset:offset + path_hash_size]) == path_hash_size
            )
            cursor += path_byte_len
    txt_type = payload[cursor]
    sender_timestamp = struct.unpack_from("<I", payload, cursor + 1)[0]
    offset = cursor + 5
    signature_hex = None
    if txt_type == 2:
        if len(payload) < offset + 4:
            raise MeshCoreError(f"short CONTACT_MSG_RECV_V3 signature payload: {len(payload)} bytes")
        signature_hex = payload[offset:offset + 4].hex()
        offset += 4
    elif txt_type == 1:
        # Some direct-message variants carry the remaining 26 bytes of the sender
        # public key after the 6-byte prefix already present in the header.
        # Skip that suffix before decoding the UTF-8 body.
        if len(payload) < offset + 26:
            raise MeshCoreError(f"short CONTACT_MSG_RECV_V3 sender-suffix payload: {len(payload)} bytes")
        offset += 26
    text_bytes = payload[offset:].split(b"\x00", 1)[0]
    if text_bytes:
        # Some direct-message payload variants leak binary key material ahead of the
        # real UTF-8 body. Prefer the clean UTF-8 suffix when the leading bytes are
        # clearly non-textual.
        for prefix_len in (26, 32):
            if len(text_bytes) <= prefix_len:
                continue
            prefix_bytes = text_bytes[:prefix_len]
            stripped_candidate = text_bytes[prefix_len:]
            try:
                decoded_stripped = stripped_candidate.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not decoded_stripped.strip():
                continue
            try:
                decoded_full = text_bytes.decode("utf-8")
            except UnicodeDecodeError:
                decoded_full = None
            try:
                decoded_prefix = prefix_bytes.decode("utf-8")
            except UnicodeDecodeError:
                decoded_prefix = None
            prefix_control_bytes = sum(
                1 for byte in prefix_bytes
                if byte < 0x20 and byte not in (0x09, 0x0A, 0x0D)
            )
            prefix_non_ascii_bytes = sum(1 for byte in prefix_bytes if byte >= 0x80)
            prefix_looks_binary = (
                decoded_prefix is None
                or prefix_control_bytes > 0
                or prefix_non_ascii_bytes >= max(4, prefix_len // 4)
            )
            if decoded_full is None or prefix_looks_binary:
                text_bytes = stripped_candidate
                break
    return ContactMessageV3Info(
        pubkey_prefix=payload[3:9].hex(),
        path_len=path_len,
        path_hashes=path_hashes,
        snr=snr,
        txt_type=txt_type,
        sender_timestamp=sender_timestamp,
        signature_hex=signature_hex,
        text=text_bytes.decode("utf-8", errors="ignore"),
    )


def parse_channel_message_v3(payload: bytes) -> ChannelMessageV3Info:
    min_len = 1 + 2 + 1 + 1 + 1 + 4
    if len(payload) < min_len:
        raise MeshCoreError(f"short CHANNEL_MSG_RECV_V3 payload: {len(payload)} bytes")
    snr = struct.unpack_from("<b", payload, 0)[0] / 4.0
    channel_idx = payload[3]
    plen = payload[4]
    path_hash_size = 0 if plen == 255 else ((plen >> 6) + 1)
    path_len = plen if plen == 255 else (plen & 0x3F)
    cursor = 5
    path_hashes = ""
    if path_len > 0 and plen != 255:
        path_byte_len = path_len * path_hash_size
        has_path_bytes_flag = bool(payload[1] & 0x01) if len(payload) > 1 else False
        can_fit_path = len(payload) >= cursor + path_byte_len + 5
        has_valid_txt_type = cursor < len(payload) and payload[cursor] in (0, 2)
        if (has_path_bytes_flag or (can_fit_path and not has_valid_txt_type)) and can_fit_path:
            path_bytes = payload[cursor:cursor + path_byte_len]
            path_hashes = " -> ".join(
                path_bytes[offset:offset + path_hash_size].hex().upper()
                for offset in range(0, len(path_bytes), path_hash_size)
                if len(path_bytes[offset:offset + path_hash_size]) == path_hash_size
            )
            cursor += path_byte_len
    txt_type = payload[cursor]
    sender_timestamp = struct.unpack_from("<I", payload, cursor + 1)[0]
    text = payload[cursor + 5:].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    return ChannelMessageV3Info(
        channel_idx=channel_idx,
        path_len=path_len,
        path_hashes=path_hashes,
        txt_type=txt_type,
        sender_timestamp=sender_timestamp,
        snr=snr,
        text=text,
    )


class MeshCoreClient:
    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
        open_settle: float = DEFAULT_OPEN_SETTLE,
        transport=None,
        frame_transport=None,
    ):
        self.port = port
        self.serial = transport or SerialPortTransport(port=port, baudrate=baudrate, timeout=timeout)
        self._frame_transport = frame_transport or UsbSerialFrameTransport(self.serial, frame_error=MeshCoreError)
        self._push_buffer = _PendingPushFrameBuffer()
        self._response_wait_registry = _ResponseWaitRegistry()
        self._frame_hub = _ReaderOwnedFrameHub(
            port=port,
            frame_transport=self._frame_transport,
            push_buffer=self._push_buffer,
            response_wait_registry=self._response_wait_registry,
        )
        if open_settle > 0:
            time.sleep(open_settle)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def close(self) -> None:
        self._frame_hub.close()

    def __enter__(self) -> MeshCoreClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def clear_input(self) -> None:
        self.serial.reset_input_buffer()

    def set_serial_timeout(self, timeout: float | None, *, suppress_errors: bool = False) -> bool:
        if timeout is None:
            return True
        try:
            self.serial.timeout = max(0.0, float(timeout))
            return True
        except (AttributeError, OSError, ValueError, SerialException):
            if suppress_errors:
                return False
            raise

    @contextmanager
    def temporary_serial_timeout(self, timeout: float | None):
        if timeout is None:
            yield
            return
        previous_timeout = getattr(self.serial, "timeout", None)
        self.set_serial_timeout(timeout)
        try:
            yield
        finally:
            self.set_serial_timeout(previous_timeout, suppress_errors=True)

    def send_frame(self, payload: bytes) -> None:
        self._frame_hub.ensure_send_allowed()
        self._frame_transport.write_frame(payload)

    def send_command(self, payload: bytes) -> None:
        self.send_frame(payload)

    def _await_unclaimed_response_frame(
        self,
        *,
        deadline_monotonic: float | None = None,
        empty_error: str = "empty response frame",
    ) -> bytes:
        return self._frame_hub.await_unclaimed_response_frame(
            deadline_monotonic=deadline_monotonic,
            empty_error=empty_error,
        )

    def _await_next_reader_owned_frame(
        self,
        *,
        deadline_monotonic: float | None = None,
        empty_error: str = "empty frame",
    ) -> bytes:
        return self._frame_hub.await_next_frame(
            deadline_monotonic=deadline_monotonic,
            empty_error=empty_error,
        )

    def await_response_frame(self) -> bytes:
        return self._await_unclaimed_response_frame()

    def await_matching_response(
        self,
        matcher: _ResponseFrameMatcher,
        *,
        deadline_monotonic: float | None = None,
    ) -> bytes:
        return self._frame_hub.await_matching_response(
            matcher,
            deadline_monotonic=deadline_monotonic,
        )

    def _default_response_timeout_secs(self) -> float:
        serial_timeout = float(getattr(self.serial, "timeout", 0.0) or 0.0)
        if serial_timeout <= 0:
            return 2.0
        return max(2.0, min(serial_timeout * 4.0, 30.0))

    def read_exact(self, size: int) -> bytes:
        return self._frame_transport.read_exact(size)

    def read_frame(self) -> bytes:
        return self._frame_transport.read_frame()

    def read_response_frame(self) -> bytes:
        return self.await_response_frame()

    def request(self, payload: bytes) -> bytes:
        self.send_command(payload)
        return self.await_response_frame()

    def request_expect_frame(
        self,
        payload: bytes,
        *,
        expected_codes: int | Iterable[int],
        empty_error: str,
        err_error: str | None = None,
        unexpected_error=None,
        timeout_secs: float | None = None,
    ) -> bytes:
        matcher = _ResponseFrameMatcher.create(
            expected_codes,
            empty_error=empty_error,
            err_error=err_error,
            unexpected_error=unexpected_error,
        )
        self.send_command(payload)
        timeout_budget = self._default_response_timeout_secs() if timeout_secs is None else max(0.0, float(timeout_secs))
        deadline_monotonic = time.monotonic() + timeout_budget if timeout_budget > 0 else None
        return self.await_matching_response(
            matcher,
            deadline_monotonic=deadline_monotonic,
        )

    def pending_push_count(self) -> int:
        return self._push_buffer.pending_push_count()

    def pop_pending_push_frames(self, max_frames: int | None = None) -> list[bytes]:
        return self._push_buffer.pop_pending_push_frames(max_frames)

    def response_waiter_count(self) -> int:
        return self._frame_hub.response_waiter_count()

    def query_device(self, protocol_version: int = DEFAULT_PROTOCOL_VERSION) -> DeviceInfo:
        frame = self.request_expect_frame(
            bytes([CMD_DEVICE_QUERY, protocol_version]),
            expected_codes=RESP_DEVICE_INFO,
            empty_error="empty response to DEVICE_QUERY",
            unexpected_error=lambda next_frame: (
                f"expected DEVICE_INFO, got code {next_frame[:1].hex() if next_frame else 'empty'}"
            ),
        )
        return parse_device_info(frame)

    def app_start(self, app_name: str = DEFAULT_APP_NAME, app_version: int = DEFAULT_APP_VERSION) -> SelfInfo:
        payload = bytes([CMD_APP_START, app_version]) + (b"\x00" * 6) + app_name.encode("utf-8")
        frame = self.request_expect_frame(
            payload,
            expected_codes=RESP_SELF_INFO,
            empty_error="empty response to APP_START",
            unexpected_error=lambda next_frame: (
                f"expected SELF_INFO, got code {next_frame[:1].hex() if next_frame else 'empty'}"
            ),
        )
        return parse_self_info(frame)

    def get_device_time(self) -> int:
        frame = self.request_expect_frame(
            bytes([CMD_GET_DEVICE_TIME]),
            expected_codes=RESP_CURR_TIME,
            empty_error="empty response to GET_DEVICE_TIME",
            unexpected_error=lambda next_frame: (
                f"expected CURR_TIME, got code {next_frame[:1].hex() if next_frame else 'empty'}"
            ),
        )
        if len(frame) < 5:
            raise MeshCoreError(f"short CURR_TIME frame: {len(frame)} bytes")
        return struct.unpack_from("<I", frame, 1)[0]

    def set_device_time(self, epoch_secs: int) -> None:
        self.request_expect_frame(
            bytes([CMD_SET_DEVICE_TIME]) + struct.pack("<I", epoch_secs),
            expected_codes=RESP_OK,
            empty_error="empty response to SET_DEVICE_TIME",
            err_error="device returned ERR for SET_DEVICE_TIME",
            unexpected_error=lambda frame: f"unexpected response code for SET_DEVICE_TIME: {frame[0]}",
        )

    def send_contact_text_message(
        self,
        destination_public_key: bytes,
        text: str,
        timestamp: int | None = None,
        attempt: int = 0,
        txt_type: int = 0,
    ) -> SentMessageInfo:
        if len(destination_public_key) not in (6, 32):
            raise MeshCoreError("destination_public_key must be 6 or 32 bytes")
        destination_prefix = destination_public_key[:6]
        payload = (
            bytes([CMD_SEND_TXT_MSG, txt_type & 0xFF, attempt & 0xFF])
            + struct.pack("<I", timestamp if timestamp is not None else utc_now_epoch())
            + destination_prefix
            + text.encode("utf-8")
        )
        frame = self.request_expect_frame(
            payload,
            expected_codes=RESP_SENT,
            empty_error="empty response to SEND_TXT_MSG",
            err_error="device returned ERR for SEND_TXT_MSG",
            unexpected_error=lambda next_frame: f"unexpected response code for SEND_TXT_MSG: {next_frame[0]}",
            timeout_secs=CONTACT_SEND_RESPONSE_TIMEOUT_SECS,
        )
        return parse_sent_message_info(frame)

    def send_channel_text_message(
        self,
        channel_idx: int,
        text: str,
        timestamp: int | None = None,
        txt_type: int = 0,
    ) -> SentMessageInfo:
        payload = (
            bytes([CMD_SEND_CHANNEL_MSG, txt_type & 0xFF, channel_idx & 0xFF])
            + struct.pack("<I", timestamp if timestamp is not None else utc_now_epoch())
            + text.encode("utf-8")
        )
        frame = self.request_expect_frame(
            payload,
            expected_codes=(RESP_OK, RESP_SENT),
            empty_error="empty response to SEND_CHANNEL_MSG",
            err_error="device returned ERR for SEND_CHANNEL_MSG",
            unexpected_error=lambda frame: f"unexpected response code for SEND_CHANNEL_MSG: {frame[0]}",
            timeout_secs=CHANNEL_SEND_RESPONSE_TIMEOUT_SECS,
        )
        if frame[0] == RESP_OK:
            return SentMessageInfo(
                route_flag=0,
                expected_ack=b"",
                suggested_timeout_ms=0,
            )
        return parse_sent_message_info(frame)

    def send_repeater_login(self, destination_public_key: bytes, password: str) -> SentMessageInfo:
        if len(destination_public_key) != 32:
            raise MeshCoreError("destination_public_key must be 32 bytes")
        password_bytes = str(password or "").encode("utf-8")
        payload = bytes([CMD_SEND_LOGIN]) + destination_public_key + password_bytes + b"\x00"
        frame = self.request_expect_frame(
            payload,
            expected_codes=RESP_SENT,
            empty_error="empty response to SEND_LOGIN",
            err_error="device returned ERR for SEND_LOGIN",
            unexpected_error=lambda next_frame: f"unexpected response code for SEND_LOGIN: {next_frame[0]}",
            timeout_secs=CONTACT_SEND_RESPONSE_TIMEOUT_SECS,
        )
        return parse_sent_message_info(frame)

    def wait_for_repeater_login(self, public_key_prefix: bytes, timeout_secs: float) -> tuple[bool, int, int | None, int | None, int | None]:
        normalized_prefix = bytes(public_key_prefix[:6])
        if len(normalized_prefix) < 4:
            raise MeshCoreError("public_key_prefix must be at least 4 bytes")
        deadline = time.monotonic() + max(0.0, float(timeout_secs))
        frame = self._frame_hub.await_push_or_response_frame(
            push_codes=(PUSH_LOGIN_SUCCESS, PUSH_LOGIN_FAIL),
            response_codes=RESP_ERR,
            push_predicate=lambda current: bool(current)
            and current[0] in (PUSH_LOGIN_SUCCESS, PUSH_LOGIN_FAIL)
            and len(current) >= 8
            and current[2:2 + len(normalized_prefix)] == normalized_prefix,
            deadline_monotonic=deadline,
            empty_error="empty frame while waiting for repeater login result",
        )
        if frame[0] == RESP_ERR:
            raise MeshCoreError("device returned ERR while waiting for repeater login result")
        success, _prefix, is_admin, login_tag, acl_permissions, firmware_level = parse_repeater_login_push(frame)
        return success, is_admin, login_tag, acl_permissions, firmware_level

    def login_to_repeater(
        self,
        destination_public_key: bytes,
        password: str,
        *,
        wait_timeout_secs: float | None = None,
    ) -> RepeaterLoginResult:
        sent = self.send_repeater_login(destination_public_key, password)
        wait_timeout = max(5.0, min((sent.suggested_timeout_ms / 1000.0) * 1.2, 30.0))
        if wait_timeout_secs is not None:
            wait_timeout = max(wait_timeout, max(0.0, float(wait_timeout_secs)))
        success, is_admin, login_tag, acl_permissions, firmware_level = self.wait_for_repeater_login(
            destination_public_key[:6],
            wait_timeout,
        )
        return RepeaterLoginResult(
            success=bool(success),
            public_key_prefix=destination_public_key[:6].hex(),
            route_flag=int(sent.route_flag),
            expected_ack=bytes(sent.expected_ack),
            suggested_timeout_ms=int(sent.suggested_timeout_ms),
            is_admin=bool(is_admin),
            login_tag=login_tag,
            acl_permissions=acl_permissions,
            firmware_level=firmware_level,
        )

    def send_repeater_cli_command(
        self,
        destination_public_key: bytes,
        command: str,
        *,
        timestamp: int | None = None,
        attempt: int = 0,
    ) -> SentMessageInfo:
        normalized_command = str(command or "").strip()
        if not normalized_command:
            raise MeshCoreError("command is required")
        return self.send_contact_text_message(
            destination_public_key,
            normalized_command,
            timestamp=timestamp,
            attempt=attempt,
            txt_type=1,
        )

    def send_trace_path(
        self,
        path: bytes,
        *,
        path_hash_len: int,
        tag: int | None = None,
        auth_code: int | None = None,
    ) -> SentMessageInfo:
        normalized_path = bytes(path or b"")
        if path_hash_len not in (1, 2, 4, 8):
            raise MeshCoreError("path_hash_len must be one of 1, 2, 4, 8 bytes")
        if not normalized_path:
            raise MeshCoreError("trace path is required")
        if len(normalized_path) % path_hash_len != 0:
            raise MeshCoreError("trace path length must be divisible by path_hash_len")
        tag_value = int(tag if tag is not None else (time.monotonic_ns() & 0xFFFFFFFF)) & 0xFFFFFFFF
        auth_value = int(auth_code if auth_code is not None else ((time.monotonic_ns() >> 12) & 0xFFFFFFFF)) & 0xFFFFFFFF
        path_hash_flag = {1: 0, 2: 1, 4: 2, 8: 3}[path_hash_len]
        payload = (
            bytes([CMD_SEND_TRACE_PATH])
            + struct.pack("<I", tag_value)
            + struct.pack("<I", auth_value)
            + bytes([path_hash_flag & 0xFF])
            + normalized_path
        )
        frame = self.request_expect_frame(
            payload,
            expected_codes=RESP_SENT,
            empty_error="empty response to SEND_TRACE_PATH",
            err_error="device returned ERR for SEND_TRACE_PATH",
            unexpected_error=lambda next_frame: f"unexpected response code for SEND_TRACE_PATH: {next_frame[0]}",
        )
        return parse_sent_message_info(frame)

    def send_trace_path_probe(
        self,
        path: bytes,
        *,
        path_hash_len: int,
        tag: int | None = None,
        auth_code: int | None = None,
        timeout_secs: float | None = None,
        response_grace_secs: float = 0.75,
        cancel_event: threading.Event | None = None,
        poll_interval_secs: float = 0.5,
    ) -> tuple[SentMessageInfo | None, TraceDataInfo | None]:
        normalized_path = bytes(path or b"")
        if path_hash_len not in (1, 2, 4, 8):
            raise MeshCoreError("path_hash_len must be one of 1, 2, 4, 8 bytes")
        if not normalized_path:
            raise MeshCoreError("trace path is required")
        if len(normalized_path) % path_hash_len != 0:
            raise MeshCoreError("trace path length must be divisible by path_hash_len")
        tag_value = int(tag if tag is not None else (time.monotonic_ns() & 0xFFFFFFFF)) & 0xFFFFFFFF
        auth_value = int(auth_code if auth_code is not None else ((time.monotonic_ns() >> 12) & 0xFFFFFFFF)) & 0xFFFFFFFF
        path_hash_flag = {1: 0, 2: 1, 4: 2, 8: 3}[path_hash_len]
        payload = (
            bytes([CMD_SEND_TRACE_PATH])
            + struct.pack("<I", tag_value)
            + struct.pack("<I", auth_value)
            + bytes([path_hash_flag & 0xFF])
            + normalized_path
        )
        self.send_command(payload)
        timeout_budget = self._default_response_timeout_secs() if timeout_secs is None else max(0.0, float(timeout_secs))
        deadline_monotonic = time.monotonic() + timeout_budget if timeout_budget > 0 else None
        expected_ack_prefix = struct.pack("<I", tag_value)
        empty_error = "empty response to SEND_TRACE_PATH"

        def _next_poll_deadline(global_deadline: float | None) -> float | None:
            if global_deadline is None:
                return None
            poll_window = max(0.05, float(poll_interval_secs))
            return min(global_deadline, time.monotonic() + poll_window)

        def _await_trace_probe_frame(global_deadline: float | None) -> bytes | None:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                try:
                    return self._frame_hub.await_push_or_response_frame(
                        push_codes=PUSH_TRACE_DATA,
                        response_codes=(RESP_SENT, RESP_ERR),
                        push_predicate=lambda current: (
                            bool(current)
                            and len(current) >= 8
                            and struct.unpack_from("<I", current, 4)[0] == tag_value
                        ),
                        response_predicate=lambda current: (
                            bool(current)
                            and current[0] == RESP_ERR
                        ) or (
                            bool(current)
                            and current[0] == RESP_SENT
                            and parse_sent_message_info(current).expected_ack[:4] == expected_ack_prefix
                        ),
                        deadline_monotonic=_next_poll_deadline(global_deadline),
                        empty_error=empty_error,
                    )
                except MeshCoreError as exc:
                    if cancel_event is not None and cancel_event.is_set():
                        return None
                    if str(exc) != empty_error:
                        raise
                    if global_deadline is not None and time.monotonic() >= global_deadline:
                        raise

        frame = _await_trace_probe_frame(deadline_monotonic)
        if frame is None:
            return None, None
        if frame[0] == RESP_ERR:
            raise MeshCoreError("device returned ERR for SEND_TRACE_PATH")
        if frame[0] == RESP_SENT:
            return parse_sent_message_info(frame), None
        trace_info = parse_trace_data_push(frame)
        sent_info: SentMessageInfo | None = None
        if response_grace_secs > 0:
            try:
                response_frame = _await_trace_probe_frame(time.monotonic() + max(0.0, float(response_grace_secs)))
            except (MeshCoreError, SerialException):
                response_frame = None
            if response_frame is not None:
                if response_frame[0] == RESP_ERR:
                    raise MeshCoreError("device returned ERR for SEND_TRACE_PATH")
                sent_info = parse_sent_message_info(response_frame)
        return sent_info, trace_info

    def send_status_request(self, destination_public_key: bytes) -> SentMessageInfo:
        if len(destination_public_key) != 32:
            raise MeshCoreError("destination_public_key must be 32 bytes")
        frame = self.request_expect_frame(
            bytes([CMD_SEND_STATUS_REQ]) + destination_public_key,
            expected_codes=RESP_SENT,
            empty_error="empty response to SEND_STATUS_REQ",
            err_error="device returned ERR for SEND_STATUS_REQ",
            unexpected_error=lambda next_frame: f"unexpected response code for SEND_STATUS_REQ: {next_frame[0]}",
        )
        return parse_sent_message_info(frame)

    def wait_for_ack(self, expected_ack: bytes, timeout_secs: float) -> bool:
        if len(expected_ack) < 1 or len(expected_ack) > 6:
            raise MeshCoreError("expected_ack must be 1 to 6 bytes")
        deadline = time.monotonic() + max(0.0, float(timeout_secs))
        try:
            self._frame_hub.await_typed_push_frame(
                push_code=PUSH_SEND_CONFIRMED,
                predicate=lambda frame: frame[0] == PUSH_SEND_CONFIRMED
                and ack_codes_match(expected_ack, parse_send_confirmed_push(frame)[0]),
                deadline_monotonic=deadline,
                empty_error="empty frame while waiting for ack",
            )
            return True
        except (MeshCoreError, SerialException):
            return False

    def wait_for_trace_data(
        self,
        tag: int,
        timeout_secs: float,
        *,
        cancel_event: threading.Event | None = None,
        poll_interval_secs: float = 0.5,
    ) -> TraceDataInfo | None:
        deadline = time.monotonic() + max(0.0, float(timeout_secs))
        tag_value = int(tag) & 0xFFFFFFFF
        empty_error = "empty frame while waiting for trace data"
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return None
            try:
                frame = self._frame_hub.await_typed_push_frame(
                    push_code=PUSH_TRACE_DATA,
                    predicate=lambda current: bool(current)
                    and current[0] == PUSH_TRACE_DATA
                    and len(current) >= 8
                    and struct.unpack_from("<I", current, 4)[0] == tag_value,
                    deadline_monotonic=min(deadline, time.monotonic() + max(0.05, float(poll_interval_secs))),
                    empty_error=empty_error,
                )
                return parse_trace_data_push(frame)
            except SerialException:
                return None
            except MeshCoreError as exc:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                if str(exc) != empty_error:
                    return None
                if time.monotonic() >= deadline:
                    return None

    def wait_for_status_response(self, public_key_prefix: bytes, timeout_secs: float) -> bool:
        normalized_prefix = bytes(public_key_prefix[:6])
        if len(normalized_prefix) < 4:
            raise MeshCoreError("public_key_prefix must be at least 4 bytes")
        deadline = time.monotonic() + max(0.0, float(timeout_secs))
        try:
            self._frame_hub.await_typed_push_frame(
                push_code=PUSH_STATUS_RESPONSE,
                predicate=lambda frame: bool(frame)
                and frame[0] == PUSH_STATUS_RESPONSE
                and len(frame) >= 8
                and frame[2:2 + len(normalized_prefix)] == normalized_prefix,
                deadline_monotonic=deadline,
                empty_error="empty frame while waiting for status response",
            )
            return True
        except (MeshCoreError, SerialException):
            return False

    def send_self_advert(self, flood: bool = False) -> None:
        payload = bytes([CMD_SEND_SELF_ADVERT, 1 if flood else 0])
        self.request_expect_frame(
            payload,
            expected_codes=RESP_OK,
            empty_error="empty response to SEND_SELF_ADVERT",
            err_error="device returned ERR for SEND_SELF_ADVERT",
            unexpected_error=lambda frame: f"unexpected response code for SEND_SELF_ADVERT: {frame[0]}",
        )

    def set_advert_name(self, name: str) -> None:
        self.request_expect_frame(
            bytes([CMD_SET_ADVERT_NAME]) + name.encode("utf-8"),
            expected_codes=RESP_OK,
            empty_error="empty response to SET_ADVERT_NAME",
            unexpected_error=lambda frame: (
                f"SET_ADVERT_NAME failed, response code={frame[:1].hex() if frame else 'empty'}"
            ),
        )

    def set_advert_coords(self, lat: float, lon: float, alt: int = 0) -> None:
        lat_value = float(lat)
        lon_value = float(lon)
        if not (-90.0 <= lat_value <= 90.0):
            raise ValueError("lat must be in range -90..90")
        if not (-180.0 <= lon_value <= 180.0):
            raise ValueError("lon must be in range -180..180")
        self.request_expect_frame(
            bytes([CMD_SET_ADVERT_LATLON])
            + int(round(lat_value * 1_000_000)).to_bytes(4, "little", signed=True)
            + int(round(lon_value * 1_000_000)).to_bytes(4, "little", signed=True)
            + int(alt).to_bytes(4, "little", signed=True),
            expected_codes=RESP_OK,
            empty_error="empty response to SET_ADVERT_LATLON",
            unexpected_error=lambda frame: (
                f"SET_ADVERT_LATLON failed, response code={frame[:1].hex() if frame else 'empty'}"
            ),
        )

    def set_other_params(
        self,
        *,
        manual_add_contacts: int,
        telemetry_modes: int,
        advert_loc_policy: int,
        multi_acks: int,
    ) -> None:
        self.request_expect_frame(
            bytes([
                CMD_SET_OTHER_PARAMS,
                int(manual_add_contacts) & 0xFF,
                int(telemetry_modes) & 0xFF,
                int(advert_loc_policy) & 0xFF,
                int(multi_acks) & 0xFF,
            ]),
            expected_codes=RESP_OK,
            empty_error="empty response to SET_OTHER_PARAMS",
            unexpected_error=lambda frame: (
                f"SET_OTHER_PARAMS failed, response code={frame[:1].hex() if frame else 'empty'}"
            ),
        )

    def get_contacts(self, since: int | None = None) -> tuple[int, list[Contact]]:
        payload = bytes([CMD_GET_CONTACTS])
        if since is not None:
            payload += struct.pack("<I", since)
        self.send_frame(payload)
        cursor, contact_frames = self._frame_hub.collect_contacts_sequence()
        return cursor, [parse_contact(frame) for frame in contact_frames]

    def remove_contact(self, public_key: bytes) -> None:
        if len(public_key) != 32:
            raise MeshCoreError("public_key must be 32 bytes")
        self.request_expect_frame(
            bytes([CMD_REMOVE_CONTACT]) + public_key,
            expected_codes=RESP_OK,
            empty_error="empty response to REMOVE_CONTACT",
            err_error="device returned ERR for REMOVE_CONTACT",
            unexpected_error=lambda frame: f"unexpected response code for REMOVE_CONTACT: {frame[0]}",
        )

    def get_contact_by_key(self, public_key: bytes) -> Contact:
        if len(public_key) != 32:
            raise MeshCoreError("public_key must be 32 bytes")
        frame = self.request_expect_frame(
            bytes([CMD_GET_CONTACT_BY_KEY]) + public_key,
            expected_codes=RESP_CONTACT,
            empty_error="empty response to GET_CONTACT_BY_KEY",
            err_error="device returned ERR for GET_CONTACT_BY_KEY",
            unexpected_error=lambda next_frame: (
                f"unexpected response code for GET_CONTACT_BY_KEY: {next_frame[0]}"
            ),
        )
        return parse_contact(frame)

    def reset_contact_path(self, public_key: bytes) -> None:
        if len(public_key) != 32:
            raise MeshCoreError("public_key must be 32 bytes")
        self.request_expect_frame(
            bytes([CMD_RESET_PATH]) + public_key,
            expected_codes=RESP_OK,
            empty_error="empty response to RESET_PATH",
            err_error="device returned ERR for RESET_PATH",
            unexpected_error=lambda frame: f"unexpected response code for RESET_PATH: {frame[0]}",
        )

    def share_contact(self, public_key: bytes) -> None:
        if len(public_key) != 32:
            raise MeshCoreError("public_key must be 32 bytes")
        self.request_expect_frame(
            bytes([CMD_SHARE_CONTACT]) + public_key,
            expected_codes=RESP_OK,
            empty_error="empty response to SHARE_CONTACT",
            err_error="device returned ERR for SHARE_CONTACT",
            unexpected_error=lambda frame: f"unexpected response code for SHARE_CONTACT: {frame[0]}",
        )

    def export_contact(self, public_key: bytes | None = None) -> bytes:
        payload = bytes([CMD_EXPORT_CONTACT])
        if public_key is not None:
            if len(public_key) != 32:
                raise MeshCoreError("public_key must be 32 bytes")
            payload += public_key
        frame = self.request_expect_frame(
            payload,
            expected_codes=RESP_EXPORT_CONTACT,
            empty_error="empty response to EXPORT_CONTACT",
            err_error="device returned ERR for EXPORT_CONTACT",
            unexpected_error=lambda next_frame: (
                f"unexpected response code for EXPORT_CONTACT: {next_frame[0]}"
            ),
        )
        return frame[1:]

    def import_contact(self, advert_packet: bytes) -> None:
        if not advert_packet:
            raise MeshCoreError("advert_packet is required")
        self.request_expect_frame(
            bytes([CMD_IMPORT_CONTACT]) + advert_packet,
            expected_codes=RESP_OK,
            empty_error="empty response to IMPORT_CONTACT",
            err_error="device returned ERR for IMPORT_CONTACT",
            unexpected_error=lambda frame: f"unexpected response code for IMPORT_CONTACT: {frame[0]}",
        )

    def update_contact(self, contact: Contact, *, flags: int | None = None) -> None:
        if len(contact.public_key) != 32:
            raise MeshCoreError("contact public_key must be 32 bytes")
        out_path_len = int(contact.out_path_len)
        if out_path_len < 0:
            path_len_byte = 0xFF
            out_path = b""
        else:
            hash_len = max(1, int(contact.out_path_hash_len))
            path_len_byte = ((hash_len - 1) << 6) | (out_path_len & 0x3F)
            out_path = bytes(contact.out_path)
        if len(out_path) > 64:
            raise MeshCoreError("contact out_path must be <= 64 bytes")
        payload = (
            bytes([CMD_ADD_UPDATE_CONTACT])
            + bytes(contact.public_key)
            + bytes([int(contact.adv_type) & 0xFF])
            + bytes([int(contact.flags if flags is None else flags) & 0xFF])
            + bytes([path_len_byte & 0xFF])
            + out_path.ljust(64, b"\x00")
            + str(contact.adv_name or "").encode("utf-8")[:32].ljust(32, b"\x00")
            + struct.pack("<I", int(contact.last_advert))
            + struct.pack("<i", int(contact.adv_lat))
            + struct.pack("<i", int(contact.adv_lon))
        )
        self.request_expect_frame(
            payload,
            expected_codes=RESP_OK,
            empty_error="empty response to ADD_UPDATE_CONTACT",
            err_error="device returned ERR for ADD_UPDATE_CONTACT",
            unexpected_error=lambda frame: f"unexpected response code for ADD_UPDATE_CONTACT: {frame[0]}",
        )

    def sync_next_message(self) -> MessageEvent | None:
        frame = self.request_expect_frame(
            bytes([CMD_SYNC_NEXT_MESSAGE]),
            expected_codes=(RESP_NO_MORE_MESSAGES, RESP_CONTACT_MSG_RECV, RESP_CHANNEL_MSG_RECV, RESP_CONTACT_MSG_RECV_V3, RESP_CHANNEL_MSG_RECV_V3),
            empty_error="empty response to SYNC_NEXT_MESSAGE",
            err_error="device returned ERR for SYNC_NEXT_MESSAGE",
            unexpected_error=lambda next_frame: f"unexpected response code for SYNC_NEXT_MESSAGE: {next_frame[0]}",
        )
        if frame[0] == RESP_NO_MORE_MESSAGES:
            return None
        return parse_message(frame)

    def drain_queued_messages(
        self,
        *,
        treat_timeout_as_empty: bool = False,
        on_attempt=None,
        max_messages: int | None = None,
        should_stop=None,
    ) -> QueueDrainResult:
        sync_attempt = 0
        messages: list[MessageEvent] = []
        limit = None if max_messages is None or int(max_messages) <= 0 else int(max_messages)
        while limit is None or len(messages) < limit:
            if should_stop is not None and bool(should_stop()):
                return QueueDrainResult(
                    messages=messages,
                    sync_attempts=sync_attempt,
                    queue_empty_via_timeout=False,
                    queue_empty_error="",
                    hit_message_limit=False,
                )
            sync_attempt += 1
            if on_attempt is not None:
                on_attempt(sync_attempt)
            try:
                message = self.sync_next_message()
            except MeshCoreError as exc:
                error_message = str(exc)
                if treat_timeout_as_empty and error_message in (
                    "serial timeout while reading 1 bytes, got 0",
                    "empty response to SYNC_NEXT_MESSAGE",
                ):
                    return QueueDrainResult(
                        messages=messages,
                        sync_attempts=sync_attempt,
                        queue_empty_via_timeout=True,
                        queue_empty_error=error_message,
                        hit_message_limit=False,
                    )
                raise
            if message is None:
                return QueueDrainResult(
                    messages=messages,
                    sync_attempts=sync_attempt,
                    queue_empty_via_timeout=False,
                    queue_empty_error="",
                    hit_message_limit=False,
                )
            messages.append(message)
        return QueueDrainResult(
            messages=messages,
            sync_attempts=sync_attempt,
            queue_empty_via_timeout=False,
            queue_empty_error="",
            hit_message_limit=True,
        )

    def get_channel(self, channel_idx: int) -> ChannelInfo:
        frame = self.request_expect_frame(
            bytes([CMD_GET_CHANNEL, channel_idx & 0xFF]),
            expected_codes=RESP_CHANNEL_INFO,
            empty_error="empty response to GET_CHANNEL",
            err_error=f"device returned ERR for GET_CHANNEL idx={channel_idx}",
            unexpected_error=lambda next_frame: f"expected CHANNEL_INFO, got code {next_frame[0]}",
        )
        return parse_channel_info(frame)

    def set_channel(self, channel_idx: int, channel_name: str, channel_secret: bytes | None = None) -> None:
        if not 0 <= int(channel_idx) <= 255:
            raise ValueError("channel_idx must be in range 0..255")
        normalized_name = normalize_meshcore_channel_name(channel_name)
        if not normalized_name:
            raise ValueError("channel name is required")
        name_bytes = normalized_name.encode("utf-8")[:32]
        name_bytes = name_bytes.ljust(32, b"\x00")
        channel_secret = derive_meshcore_channel_secret(normalized_name, channel_secret)
        self.request_expect_frame(
            bytes([CMD_SET_CHANNEL, channel_idx & 0xFF]) + name_bytes + bytes(channel_secret),
            expected_codes=RESP_OK,
            empty_error="empty response to SET_CHANNEL",
            err_error=f"device returned ERR for SET_CHANNEL idx={channel_idx}",
            unexpected_error=lambda frame: f"expected OK response to SET_CHANNEL, got code {frame[0]}",
        )

    def get_radio_stats(self) -> RadioStats:
        frame = self.request_expect_frame(
            bytes([56, 1]),
            expected_codes=RESP_STATS,
            empty_error="empty response to GET_STATS radio",
            err_error="device returned ERR for GET_STATS radio",
            unexpected_error=lambda next_frame: f"expected STATS response, got code {next_frame[0]}",
        )
        return parse_radio_stats(frame)

    def get_core_stats(self) -> CoreStats:
        frame = self.request_expect_frame(
            bytes([56, 0]),
            expected_codes=RESP_STATS,
            empty_error="empty response to GET_STATS core",
            err_error="device returned ERR for GET_STATS core",
            unexpected_error=lambda next_frame: f"expected STATS response, got code {next_frame[0]}",
        )
        return parse_core_stats(frame)

    def get_self_telemetry(self) -> SelfTelemetry:
        self.send_frame(bytes([CMD_GET_SELF_TELEMETRY, 0, 0, 0]))
        frame = self._frame_hub.await_telemetry_response_frame(empty_error="empty response to GET_SELF_TELEMETRY")
        if frame[0] == RESP_ERR:
            raise MeshCoreError("device returned ERR for GET_SELF_TELEMETRY")
        if frame[0] != PUSH_TELEMETRY_RESPONSE:
            raise MeshCoreError(f"unexpected response code for GET_SELF_TELEMETRY: {frame[0]}")
        return parse_self_telemetry(frame)

    def get_battery_info(self) -> BatteryInfo:
        frame = self.request_expect_frame(
            bytes([0x14]),
            expected_codes=RESP_BATT_AND_STORAGE,
            empty_error="empty response to GET_BAT",
            err_error="device returned ERR for GET_BAT",
            unexpected_error=lambda next_frame: (
                f"expected BATT_AND_STORAGE response to GET_BAT, got code {next_frame[0]}"
            ),
        )
        return parse_battery_info(frame)

    def wait_for_frame(
        self,
        *,
        timeout_secs: float | None = None,
        empty_error: str = "empty frame",
    ) -> bytes:
        deadline_monotonic = None
        if timeout_secs is not None:
            deadline_monotonic = time.monotonic() + max(0.0, float(timeout_secs))
        return self._await_next_reader_owned_frame(
            deadline_monotonic=deadline_monotonic,
            empty_error=empty_error,
        )


MeshCoreSerialClient = MeshCoreClient


def discover_ports() -> list[dict[str, str]]:
    return discover_serial_ports()


def auto_pick_port() -> str:
    ports = discover_ports()
    if not ports:
        raise MeshCoreError("no serial ports found; pass --port explicitly")
    for port in ports:
        text = " ".join(port.values()).lower()
        if "heltec" in text or "cp210" in text or "usb serial" in text or "ch340" in text:
            return port["device"]
    return ports[0]["device"]


def open_client(args: argparse.Namespace) -> MeshCoreClient:
    port = args.port or auto_pick_port()
    return MeshCoreClient(port=port, baudrate=args.baudrate, timeout=args.timeout)


def print_device_info(device_info: DeviceInfo) -> None:
    print(f"firmware_ver: {device_info.firmware_ver}")
    print(f"semantic_version: {device_info.semantic_version}")
    print(f"build_date: {device_info.firmware_build_date}")
    print(f"model: {device_info.manufacturer_model}")
    print(f"max_contacts: {device_info.max_contacts_div_2 * 2}")
    print(f"max_channels: {device_info.max_channels}")
    print(f"ble_pin: {device_info.ble_pin}")


def print_self_info(self_info: SelfInfo) -> None:
    print(f"name: {self_info.name}")
    print(f"public_key: {format_hex(self_info.public_key)}")
    print(f"adv_type: {self_info.adv_type}")
    print(f"tx_power_dbm: {self_info.tx_power_dbm}")
    print(f"max_tx_power: {self_info.max_tx_power}")
    print(f"radio_freq_hz_x1000: {self_info.radio_freq}")
    print(f"radio_bw_hz_x1000: {self_info.radio_bw}")
    print(f"radio_sf: {self_info.radio_sf}")
    print(f"radio_cr: {self_info.radio_cr}")
    print(f"lat: {format_latlon(self_info.adv_lat):.6f}")
    print(f"lon: {format_latlon(self_info.adv_lon):.6f}")
    print(f"multi_acks: {self_info.multi_acks}")
    print(f"advert_loc_policy: {self_info.advert_loc_policy}")
    print(f"telemetry_modes: {self_info.telemetry_modes}")
    print(f"manual_add_contacts: {self_info.manual_add_contacts}")


def print_contact(contact: Contact) -> None:
    print(f"pubkey={format_hex(contact.public_key)} name={contact.adv_name!r} type={contact.adv_type} flags={contact.flags} lastmod={contact.lastmod} lat={format_latlon(contact.adv_lat):.6f} lon={format_latlon(contact.adv_lon):.6f}")


def print_message(event: MessageEvent) -> None:
    print(f"message_code={event.code} payload_hex={event.payload.hex()}")


def cmd_ports(_args: argparse.Namespace) -> int:
    ports = discover_ports()
    if not ports:
        print("No serial ports found.")
        return 1
    for port in ports:
        print(f"{port['device']}: {port['description']} | {port['manufacturer']} | {port['product']} | {port['hwid']}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        device_info = client.query_device(args.protocol_version)
        print_device_info(device_info)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        device_info = client.query_device(args.protocol_version)
        self_info = client.app_start(args.app_name, args.app_version)
        print("[device]")
        print_device_info(device_info)
        print()
        print("[self]")
        print_self_info(self_info)
    return 0


def cmd_time_get(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        epoch = client.get_device_time()
        print(f"epoch: {epoch}")
        print(f"utc: {datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()}")
    return 0


def cmd_time_set(args: argparse.Namespace) -> int:
    epoch = args.epoch if args.epoch is not None else utc_now_epoch()
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        client.set_device_time(epoch)
        print(f"set epoch: {epoch}")
        print(f"utc: {datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()}")
    return 0


def cmd_time_sync(args: argparse.Namespace) -> int:
    epoch = utc_now_epoch()
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        before = client.get_device_time()
        client.set_device_time(epoch)
        after = client.get_device_time()
        print(f"before: {before} ({datetime.fromtimestamp(before, tz=timezone.utc).isoformat()})")
        print(f"after: {after} ({datetime.fromtimestamp(after, tz=timezone.utc).isoformat()})")
    return 0


def cmd_contacts(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        cursor, contacts = client.get_contacts(args.since)
        print(f"contacts: {len(contacts)}")
        print(f"next_since: {cursor}")
        for contact in contacts:
            print_contact(contact)
    return 0


def handle_push(client: MeshCoreSerialClient, frame: bytes, auto_sync_messages: bool) -> None:
    code = frame[0]
    if code == PUSH_MSG_WAITING and auto_sync_messages:
        result = client.drain_queued_messages()
        for event in result.messages:
            print_message(event)
        print("queue empty")
        return
    else:
        print(f"push_code={code} payload_hex={frame[1:].hex()}")


def cmd_listen(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        self_info = client.app_start(args.app_name, args.app_version)
        print(f"connected: {self_info.name} {client.port}")
        if args.sync_time:
            client.set_device_time(utc_now_epoch())
            print("time synced")
        print("listening...")
        while True:
            frame = client.wait_for_frame()
            handle_push(client, frame, auto_sync_messages=not args.no_message_sync)


def cmd_advert(args: argparse.Namespace) -> int:
    with open_client(args) as client:
        client.query_device(args.protocol_version)
        client.app_start(args.app_name, args.app_version)
        if args.name:
            client.set_advert_name(args.name)
            print(f"advert name updated: {args.name}")
        client.send_self_advert(flood=args.flood)
        print("advert sent")
    return 0


def fetch_probe(port: str, baudrate: int = DEFAULT_BAUDRATE, timeout: float = DEFAULT_TIMEOUT, protocol_version: int = DEFAULT_PROTOCOL_VERSION) -> DeviceInfo:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        return client.query_device(protocol_version)


def fetch_info(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[DeviceInfo, SelfInfo]:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        return client.query_device(protocol_version), client.app_start(app_name, app_version)


def fetch_time(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> int:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_device_time()


def sync_time(
    port: str,
    epoch: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[int, int]:
    target = epoch if epoch is not None else utc_now_epoch()
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        before = client.get_device_time()
        client.set_device_time(target)
        after = client.get_device_time()
        return before, after


def fetch_contacts(
    port: str,
    since: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[int, list[Contact]]:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_contacts(since)


def fetch_channels(
    port: str,
    max_channels: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> list[ChannelInfo]:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        device = client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        count = max_channels if max_channels is not None else device.max_channels
        return [client.get_channel(index) for index in range(max(0, count))]


def set_channel_config(
    *,
    port: str,
    channel_idx: int,
    channel_name: str,
    channel_secret: bytes | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
) -> ChannelInfo:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.set_channel(channel_idx, channel_name, channel_secret)
        return client.get_channel(channel_idx)


def fetch_radio_stats(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> RadioStats:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_radio_stats()


def fetch_core_stats(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> CoreStats:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_core_stats()


def fetch_self_telemetry(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> SelfTelemetry:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_self_telemetry()


def fetch_battery_info(
    port: str,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> BatteryInfo:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.get_battery_info()


def fetch_connect_snapshot(
    port: str,
    since: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[DeviceInfo, SelfInfo, int, list[Contact], list[ChannelInfo], RadioStats | None, SelfTelemetry | None]:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        device = client.query_device(protocol_version)
        self_info = client.app_start(app_name, app_version)
        cursor, contacts = client.get_contacts(since)
        channels = [client.get_channel(index) for index in range(device.max_channels)]
        try:
            radio_stats = client.get_radio_stats()
        except MeshCoreError:
            radio_stats = None
        try:
            self_telemetry = client.get_self_telemetry()
        except MeshCoreError:
            self_telemetry = None
        return device, self_info, cursor, contacts, channels, radio_stats, self_telemetry


def send_advert(
    port: str,
    flood: bool = False,
    name: str | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> None:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        if name:
            client.set_advert_name(name)
        client.send_self_advert(flood=flood)


def send_contact_text(
    port: str,
    destination_public_key: bytes,
    text: str,
    timestamp: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> tuple[SentMessageInfo, bool]:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        sent = client.send_contact_text_message(destination_public_key, text, timestamp=timestamp)
        ack_timeout = max(5.0, min((sent.suggested_timeout_ms / 1000.0) * 1.2, 30.0))
        return sent, client.wait_for_ack(sent.expected_ack, ack_timeout)


def send_channel_text(
    port: str,
    channel_idx: int,
    text: str,
    timestamp: int | None = None,
    baudrate: int = DEFAULT_BAUDRATE,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: int = DEFAULT_PROTOCOL_VERSION,
    app_version: int = DEFAULT_APP_VERSION,
    app_name: str = DEFAULT_APP_NAME,
) -> SentMessageInfo:
    with MeshCoreSerialClient(port=port, baudrate=baudrate, timeout=timeout) as client:
        client.query_device(protocol_version)
        client.app_start(app_name, app_version)
        return client.send_channel_text_message(channel_idx, text, timestamp=timestamp)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", help="Serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--protocol-version", type=int, default=DEFAULT_PROTOCOL_VERSION)
    parser.add_argument("--app-version", type=int, default=DEFAULT_APP_VERSION)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Meshcorium companion USB client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ports_parser = subparsers.add_parser("ports", help="List serial ports")
    ports_parser.set_defaults(func=cmd_ports)

    probe_parser = subparsers.add_parser("probe", help="Query device info")
    add_common_arguments(probe_parser)
    probe_parser.set_defaults(func=cmd_probe)

    info_parser = subparsers.add_parser("info", help="Query device info and self info")
    add_common_arguments(info_parser)
    info_parser.set_defaults(func=cmd_info)

    time_parser = subparsers.add_parser("time", help="Get or set device clock")
    time_subparsers = time_parser.add_subparsers(dest="time_command", required=True)

    time_get = time_subparsers.add_parser("get", help="Read device time")
    add_common_arguments(time_get)
    time_get.set_defaults(func=cmd_time_get)

    time_set = time_subparsers.add_parser("set", help="Set device time")
    add_common_arguments(time_set)
    time_set.add_argument("--epoch", type=int, help="Epoch seconds in UTC; default is current UTC time")
    time_set.set_defaults(func=cmd_time_set)

    time_sync = time_subparsers.add_parser("sync", help="Sync device time to current UTC")
    add_common_arguments(time_sync)
    time_sync.set_defaults(func=cmd_time_sync)

    contacts_parser = subparsers.add_parser("contacts", help="Download contacts list")
    add_common_arguments(contacts_parser)
    contacts_parser.add_argument("--since", type=int)
    contacts_parser.set_defaults(func=cmd_contacts)

    listen_parser = subparsers.add_parser("listen", help="Listen for push events")
    add_common_arguments(listen_parser)
    listen_parser.add_argument("--sync-time", action="store_true", help="Set device time on connect")
    listen_parser.add_argument("--no-message-sync", action="store_true", help="Do not auto-fetch queued messages on PUSH_MSG_WAITING")
    listen_parser.set_defaults(func=cmd_listen)

    advert_parser = subparsers.add_parser("advert", help="Send self advert")
    add_common_arguments(advert_parser)
    advert_parser.add_argument("--flood", action="store_true", help="Send flood advert instead of zero-hop")
    advert_parser.add_argument("--name", help="Update advert name before sending")
    advert_parser.set_defaults(func=cmd_advert)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except MeshCoreError as exc:
        print(f"Meshcorium error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
