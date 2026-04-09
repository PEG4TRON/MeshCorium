#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
import typing
from pathlib import Path
from dataclasses import dataclass, field, replace
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from contact_backend import ContactBackend
import contact_groups
import contact_service
import contact_store
from mobile_push import (
    build_mobile_push_status,
    init_mobile_push_db_schema,
    register_mobile_push_device,
    send_mobile_push_notification,
    sync_mobile_push_muted_conversations,
    unregister_mobile_push_device,
)
from meshcorium_client import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_VERSION,
    DEFAULT_BAUDRATE,
    DEFAULT_PROTOCOL_VERSION,
    DEFAULT_TIMEOUT,
    MESHCORE_PUBLIC_CHANNEL_NAME,
    MESHCORE_PUBLIC_CHANNEL_PSK_HEX,
    PUSH_LOG_RX_DATA,
    PUSH_NEW_ADVERT,
    PUSH_RAW_DATA,
    PUSH_MSG_WAITING,
    MeshCoreError,
    MeshCoreSerialClient,
    PUSH_SEND_CONFIRMED,
    RESP_CHANNEL_MSG_RECV_V3,
    RESP_CONTACT_MSG_RECV_V3,
    derive_meshcore_channel_secret,
    format_hex,
    format_latlon,
    ack_codes_match,
    is_meshcore_public_channel_name,
    normalize_meshcore_channel_name,
    parse_channel_message_v3,
    parse_contact_message_v3,
    parse_send_confirmed_push,
    parse_message,
    utc_now_epoch,
)
from meshcorium_transport import (
    DEFAULT_CONNECTION_ROUTER,
    ConnectionDescriptor,
    SERIAL_TRANSPORT_TYPE,
)
from meshcorium_ble_transport import BLE_TRANSPORT_TYPE, BleTransportUnavailable
from meshcorium_serial_transport import SerialException

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LEGACY_LOG_PATH = LOG_DIR / "meshcore_web.log"
LOG_PATH = LOG_DIR / "meshcorium_web.log"
DELIVERY_DEBUG_LOG_PATH = LOG_DIR / "message_delivery_debug.log"
READ_DEBUG_LOG_PATH = LOG_DIR / "message_read_debug.log"
CONTACT_DEBUG_LOG_PATH = LOG_DIR / "contact_residency_debug.log"
ROUTE_TRACE_DEBUG_LOG_PATH = LOG_DIR / "route_trace_debug.log"
FRONTEND_DIAGNOSTIC_LOG_PATH = LOG_DIR / "frontend_diagnostics.log"
BACKGROUND_QUEUE_DRAIN_BATCH_LIMIT = 2
BACKGROUND_MAINTENANCE_IDLE_GRACE_SECS = 1.0
BACKGROUND_QUEUE_DRAIN_INTERACTIVE_IDLE_GRACE_SECS = 1.5
BACKGROUND_FRAME_POLL_TIMEOUT_SECS = 0.25
BACKGROUND_SEND_COMMAND_TIMEOUT_SECS = 35.0
DATA_DIR = PROJECT_ROOT / "data"
LEGACY_DB_PATH = DATA_DIR / "meshcore_messages.sqlite3"
LEGACY_CONTACTS_DB_PATH = DATA_DIR / "meshcore_contacts.sqlite3"
DB_PATH = DATA_DIR / "meshcorium_messages.sqlite3"
CONTACTS_DB_PATH = DATA_DIR / "meshcorium_contacts.sqlite3"
CLIENT_SETTINGS_PATH = DATA_DIR / "client_settings.json"
ICONS_DIR = PROJECT_ROOT / "icons"
SOUNDS_DIR = PROJECT_ROOT / "sounds"
VENDOR_DIR = PROJECT_ROOT / "vendor"
WALLPAPPERS_DIR = PROJECT_ROOT / "other" / "wallpappers"
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST_DIR = WEB_DIR / "dist"
DB_LOCK = threading.Lock()
CLIENT_SETTINGS_LOCK = threading.Lock()
DELIVERY_DEBUG_LOCK = threading.Lock()
READ_DEBUG_LOCK = threading.Lock()
CONTACT_DEBUG_LOCK = threading.Lock()
ROUTE_TRACE_DEBUG_LOCK = threading.Lock()
FRONTEND_DIAGNOSTIC_LOCK = threading.Lock()
CONNECTION_LOCKS: dict[str, threading.Lock] = {}
CONNECTION_RUNTIME_GUARD = threading.Lock()
LISTENER_STOPS: dict[str, set[threading.Event]] = {}
EVENT_SUBSCRIBERS: dict[str, set[queue.Queue]] = {}
EVENT_SUBSCRIBERS_GUARD = threading.Lock()
BACKGROUND_SESSIONS: dict[str, "BackgroundCompanionSession"] = {}
BACKGROUND_SESSIONS_GUARD = threading.Lock()
PENDING_RECONNECTS: dict[str, threading.Event] = {}
PENDING_RECONNECTS_GUARD = threading.Lock()
PENDING_RECONNECT_META: dict[str, dict] = {}
ROUTE_TRACE_JOBS: dict[str, "RouteTraceJob"] = {}
ROUTE_TRACE_JOBS_GUARD = threading.Lock()
MESSAGE_BODY_MAX_BYTES = 192
PAGE_BACKGROUND_PRESET_IDS = {"default", "aurora", "grid"}
PAGE_BACKGROUND_BLUR_DEFAULT_PX = 14
PAGE_BACKGROUND_BLUR_MAX_PX = 32
CHAT_BACKGROUND_PRESET_IDS = {"chat-backplane-blue"}
WALLPAPER_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
ALLOWED_WALLPAPER_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}
CONTACT_FLAG_STAR = 0x01
SYSTEM_FAVORITES_GROUP = "favorites"
BASE_NODE_NON_FAVORITE_CONTACT_LIMIT = 50
SERVICE_RECONNECT_DELAY_SECS = 5.0
CONTACT_ACTIVE_TIMEOUT_SECS = 60 * 60
REPEATER_ACTIVE_TIMEOUT_SECS = 15 * 60
CONTACT_EVICTION_SWEEP_INTERVAL_SECS = 60
CONTACT_ACTIVE_TIMEOUT_MIN_SECS = 5 * 60
CONTACT_ACTIVE_TIMEOUT_MAX_SECS = 7 * 24 * 60 * 60
REPEATER_ACTIVE_TIMEOUT_MIN_SECS = 60
REPEATER_ACTIVE_TIMEOUT_MAX_SECS = 24 * 60 * 60
CONTACT_EVICTION_SWEEP_INTERVAL_MIN_SECS = 15
CONTACT_EVICTION_SWEEP_INTERVAL_MAX_SECS = 60 * 60
SIGNAL_METRICS_DEFAULT_RETENTION_DAYS = 7
SIGNAL_METRICS_MIN_RETENTION_DAYS = 1
SIGNAL_METRICS_MAX_RETENTION_DAYS = 365
SIGNAL_METRICS_DEFAULT_POLL_SECONDS = 15
SIGNAL_METRICS_MIN_POLL_SECONDS = 5
SIGNAL_METRICS_MAX_POLL_SECONDS = 300
EMOJI_CHOICES = [
    "😀", "😁", "😂", "🤣", "😃", "😄", "😅", "😉", "😊", "🙂", "🙃", "😍", "🥰", "😘", "😎", "🤔",
    "🤨", "😐", "😑", "😶", "😏", "😴", "😌", "🤗", "🫡", "🤝", "👍", "👎", "👏", "🙌", "🙏", "💪",
    "🫶", "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🔥", "✨", "⭐", "⚡", "☀️", "🌙", "🌧️",
    "❄️", "☕", "🍺", "🍕", "🎉", "🎯", "🎵", "🎮", "📡", "🛰️", "📍", "📣", "📷", "🔋", "🔒", "🔓",
    "✅", "❌", "⚠️", "❗", "❓", "⏳", "⌛", "🚀", "🚁", "🚗", "🚨", "🏠", "🌍", "🐝", "👾", "🤖", "🛠️"
]


def _display_project_path(path: os.PathLike[str] | str) -> str:
    try:
        return os.path.relpath(os.fspath(path), os.fspath(PROJECT_ROOT))
    except ValueError:
        return os.fspath(path)


def _default_client_settings() -> dict:
    sound_files = _list_sound_files()
    default_regular = sound_files[0] if sound_files else ""
    default_mention = sound_files[1] if len(sound_files) > 1 else default_regular
    default_direct = sound_files[2] if len(sound_files) > 2 else default_regular
    return {
        "auto_connect_on_service_start": False,
        "startup_use_last_successful": True,
        "startup_connection_key": "",
        "access_all_meshcorium_contacts": True,
        "contact_active_timeout_secs": CONTACT_ACTIVE_TIMEOUT_SECS,
        "repeater_active_timeout_secs": REPEATER_ACTIVE_TIMEOUT_SECS,
        "contact_eviction_sweep_interval_secs": CONTACT_EVICTION_SWEEP_INTERVAL_SECS,
        "contact_residency_preserve_repeaters_on_node": False,
        "contact_full_table_behavior": "evict_oldest",
        "signal_metrics_retention_days": SIGNAL_METRICS_DEFAULT_RETENTION_DAYS,
        "signal_metrics_poll_seconds": SIGNAL_METRICS_DEFAULT_POLL_SECONDS,
        "frontend_diagnostics_enabled": True,
        "notifications_sound_enabled": True,
        "notification_regular_sound_file": default_regular,
        "notification_mention_sound_file": default_mention,
        "notification_direct_sound_file": default_direct,
        "page_background_id": "default",
        "chat_background_id": "chat-backplane-blue",
        "page_background_blur_enabled": False,
        "page_background_blur_px": PAGE_BACKGROUND_BLUR_DEFAULT_PX,
        "muted_conversations": {},
        "muted_conversations_updated_at": 0,
        "auth_enabled": False,
        "auth_username": "",
        "auth_password_hash": "",
        "auth_password_salt": "",
        "auth_session_secret": "",
        "saved_connections": [],
        "last_successful_key": "",
        "last_successful_config": None,
        "self_location_overrides": {},
    }


def _normalize_signal_metrics_retention_days(value: object) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = SIGNAL_METRICS_DEFAULT_RETENTION_DAYS
    return max(SIGNAL_METRICS_MIN_RETENTION_DAYS, min(SIGNAL_METRICS_MAX_RETENTION_DAYS, days))


def _normalize_signal_metrics_poll_seconds(value: object) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = SIGNAL_METRICS_DEFAULT_POLL_SECONDS
    return max(SIGNAL_METRICS_MIN_POLL_SECONDS, min(SIGNAL_METRICS_MAX_POLL_SECONDS, seconds))


def _normalize_contact_active_timeout_secs(value: object) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = CONTACT_ACTIVE_TIMEOUT_SECS
    return max(CONTACT_ACTIVE_TIMEOUT_MIN_SECS, min(CONTACT_ACTIVE_TIMEOUT_MAX_SECS, seconds))


def _normalize_repeater_active_timeout_secs(value: object) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = REPEATER_ACTIVE_TIMEOUT_SECS
    return max(REPEATER_ACTIVE_TIMEOUT_MIN_SECS, min(REPEATER_ACTIVE_TIMEOUT_MAX_SECS, seconds))


def _normalize_contact_eviction_sweep_interval_secs(value: object) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = CONTACT_EVICTION_SWEEP_INTERVAL_SECS
    return max(CONTACT_EVICTION_SWEEP_INTERVAL_MIN_SECS, min(CONTACT_EVICTION_SWEEP_INTERVAL_MAX_SECS, seconds))


def _normalize_contact_full_table_behavior(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"evict_oldest", "reject_new"}:
        return mode
    return "evict_oldest"


def _list_sound_files() -> list[str]:
    if not os.path.isdir(SOUNDS_DIR):
        return []
    items = [
        entry
        for entry in os.listdir(SOUNDS_DIR)
        if entry.lower().endswith(".mp3") and os.path.isfile(os.path.join(SOUNDS_DIR, entry))
    ]
    return sorted(items, key=lambda item: item.lower())


def _normalize_notification_sound_file(value: object, available_files: list[str], fallback: str = "") -> str:
    selected = os.path.basename(str(value or "").strip())
    if selected in available_files:
        return selected
    fallback_name = os.path.basename(str(fallback or "").strip())
    if fallback_name in available_files:
        return fallback_name
    return available_files[0] if available_files else ""


def _list_wallpaper_files() -> list[str]:
    if not WALLPAPPERS_DIR.is_dir():
        return []
    items = [
        entry.name
        for entry in WALLPAPPERS_DIR.iterdir()
        if entry.is_file() and entry.suffix.lower() in ALLOWED_WALLPAPER_EXTENSIONS
    ]
    return sorted(items, key=lambda item: item.lower())


def _normalize_wallpaper_filename(value: object) -> str:
    raw_name = os.path.basename(str(value or "").strip().replace("\\", "/"))
    if not raw_name:
        return ""
    stem, suffix = os.path.splitext(raw_name)
    suffix = suffix.lower()
    if suffix not in ALLOWED_WALLPAPER_EXTENSIONS:
        return ""
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "-", stem).strip(" ._-")
    if not safe_stem:
        return ""
    return f"{safe_stem}{suffix}"


def _normalize_page_background_id(value: object, available_wallpapers: list[str] | None = None) -> str:
    raw_value = str(value or "").strip()
    if raw_value in PAGE_BACKGROUND_PRESET_IDS:
        return raw_value
    if raw_value.startswith("wallpaper:"):
        normalized_name = _normalize_wallpaper_filename(raw_value.removeprefix("wallpaper:"))
        wallpaper_files = available_wallpapers if available_wallpapers is not None else _list_wallpaper_files()
        if normalized_name and normalized_name in wallpaper_files:
            return f"wallpaper:{normalized_name}"
    return "default"


def _normalize_chat_background_id(value: object, available_wallpapers: list[str] | None = None) -> str:
    raw_value = str(value or "").strip()
    if raw_value in CHAT_BACKGROUND_PRESET_IDS:
        return raw_value
    if raw_value.startswith("wallpaper:"):
        normalized_name = _normalize_wallpaper_filename(raw_value.removeprefix("wallpaper:"))
        wallpaper_files = available_wallpapers if available_wallpapers is not None else _list_wallpaper_files()
        if normalized_name and normalized_name in wallpaper_files:
            return f"wallpaper:{normalized_name}"
    return "chat-backplane-blue"


def _normalize_page_background_blur_px(value: object) -> int:
    try:
        blur_px = int(value)
    except (TypeError, ValueError):
        blur_px = PAGE_BACKGROUND_BLUR_DEFAULT_PX
    return max(0, min(PAGE_BACKGROUND_BLUR_MAX_PX, blur_px))


def _build_wallpaper_url(file_name: str) -> str:
    return f"/wallpappers/{quote(file_name)}"


def _store_wallpaper_file(filename: object, content_base64: object) -> str:
    normalized_name = _normalize_wallpaper_filename(filename)
    if not normalized_name:
        raise ValueError("unsupported wallpaper filename")
    encoded_payload = str(content_base64 or "").strip()
    if not encoded_payload:
        raise ValueError("wallpaper content is required")
    if "," in encoded_payload and encoded_payload.lower().startswith("data:"):
        encoded_payload = encoded_payload.split(",", 1)[1]
    try:
        payload = base64.b64decode(encoded_payload, validate=True)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise ValueError("wallpaper content is not valid base64") from exc
    if not payload:
        raise ValueError("wallpaper file is empty")
    if len(payload) > WALLPAPER_UPLOAD_MAX_BYTES:
        raise ValueError(f"wallpaper file is too large: {len(payload)} bytes")
    os.makedirs(WALLPAPPERS_DIR, exist_ok=True)
    stem, suffix = os.path.splitext(normalized_name)
    candidate_name = normalized_name
    counter = 2
    while (WALLPAPPERS_DIR / candidate_name).exists():
        candidate_name = f"{stem}-{counter}{suffix}"
        counter += 1
    (WALLPAPPERS_DIR / candidate_name).write_bytes(payload)
    return candidate_name


def _normalize_muted_conversations(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_mode in value.items():
        key = str(raw_key or "").strip().lower()
        mode = str(raw_mode or "").strip().lower()
        if not key:
            continue
        if mode == "all":
            result[key] = "all"
        elif mode == "regular" and result.get(key) != "all":
            result[key] = "regular"
    return result


def _normalize_muted_conversations_updated_at(value: object) -> int:
    try:
        updated_at = int(value)
    except (TypeError, ValueError):
        updated_at = 0
    return max(0, updated_at)


def _normalize_self_location_overrides(value: object) -> dict[str, dict[str, float | int]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, float | int]] = {}
    for raw_owner_id, raw_entry in value.items():
        owner_id = _normalize_owner_id(raw_owner_id)
        if not owner_id or not isinstance(raw_entry, dict):
            continue
        try:
            lat = round(float(raw_entry.get("lat")), 6)
            lon = round(float(raw_entry.get("lon")), 6)
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        result[owner_id] = {
            "lat": lat,
            "lon": lon,
            "updated_at": int(raw_entry.get("updated_at") or 0),
        }
    return result


def _normalize_saved_connection(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    normalized_config = _normalize_connection_config(entry)
    if normalized_config is None:
        return None
    port = str(normalized_config.get("port") or "")
    baudrate = int(normalized_config.get("baudrate", DEFAULT_BAUDRATE))
    timeout = float(normalized_config.get("timeout", DEFAULT_TIMEOUT))
    protocol_version = int(normalized_config.get("protocol_version", DEFAULT_PROTOCOL_VERSION))
    app_version = int(normalized_config.get("app_version", DEFAULT_APP_VERSION))
    app_name = str(normalized_config.get("app_name", DEFAULT_APP_NAME))
    node_name = str(entry.get("node_name") or "").strip()
    public_key = str(entry.get("public_key") or "").strip().lower()
    if len(public_key) != 64:
        public_key = ""
    manufacturer_model = str(entry.get("manufacturer_model") or "").strip()
    connection_type = _normalize_saved_connection_type(
        entry.get("connection_type")
        or normalized_config.get("transport_type")
        or _infer_saved_connection_type(port)
    )
    key = str(entry.get("key") or _build_saved_connection_history_key(normalized_config, public_key=public_key)).strip()
    last_connected_at = int(entry.get("last_connected_at") or 0)
    return {
        "key": key,
        "port": port,
        "baudrate": baudrate,
        "timeout": timeout,
        "protocol_version": protocol_version,
        "app_version": app_version,
        "app_name": app_name,
        "node_name": node_name,
        "public_key": public_key,
        "manufacturer_model": manufacturer_model,
        "connection_type": connection_type,
        "last_connected_at": last_connected_at,
        "transport_type": str(normalized_config.get("transport_type") or "serial"),
        "transport_id": str(normalized_config.get("transport_id") or port),
        "display_label": str((normalized_config.get("connection") or {}).get("display_label") or entry.get("display_label") or port),
        "connection": dict(normalized_config.get("connection") or {}),
    }


def _normalize_connection_config(config: object) -> dict | None:
    if not isinstance(config, dict):
        return None
    try:
        descriptor = DEFAULT_CONNECTION_ROUTER.from_request(config)
    except (TypeError, ValueError):
        return None
    connection_id = descriptor.port if descriptor.transport_type == SERIAL_TRANSPORT_TYPE else descriptor.transport_id
    return _normalize_session_config(
        port=connection_id,
        baudrate=descriptor.baudrate,
        timeout=descriptor.timeout,
        protocol_version=int(config.get("protocol_version", DEFAULT_PROTOCOL_VERSION)),
        app_version=int(config.get("app_version", DEFAULT_APP_VERSION)),
        app_name=str(config.get("app_name", DEFAULT_APP_NAME)),
        transport_type=descriptor.transport_type,
        transport_id=descriptor.transport_id,
        display_label=descriptor.display_label,
    )


def _normalize_client_settings(data: object) -> dict:
    base = _default_client_settings()
    raw = data if isinstance(data, dict) else {}
    sound_files = _list_sound_files()
    wallpaper_files = _list_wallpaper_files()
    auth_username = _normalize_auth_username(raw.get("auth_username", base["auth_username"]))
    auth_password_hash = str(raw.get("auth_password_hash") or "").strip()
    auth_password_salt = str(raw.get("auth_password_salt") or "").strip()
    auth_session_secret = str(raw.get("auth_session_secret") or "").strip()
    auth_enabled = bool(raw.get("auth_enabled", base["auth_enabled"])) and bool(auth_username and auth_password_hash and auth_password_salt)
    saved_connections: list[dict] = []
    for item in list(raw.get("saved_connections") or []):
        normalized = _normalize_saved_connection(item)
        if normalized is not None:
            saved_connections.append(normalized)
    saved_connections.sort(key=lambda item: (int(item.get("last_connected_at") or 0), item["key"]), reverse=True)
    last_successful_config = _normalize_connection_config(raw.get("last_successful_config"))
    return {
        "auto_connect_on_service_start": bool(raw.get("auto_connect_on_service_start", base["auto_connect_on_service_start"])),
        "startup_use_last_successful": bool(raw.get("startup_use_last_successful", base["startup_use_last_successful"])),
        "startup_connection_key": str(raw.get("startup_connection_key") or "").strip(),
        "access_all_meshcorium_contacts": bool(raw.get("access_all_meshcorium_contacts", base["access_all_meshcorium_contacts"])),
        "contact_active_timeout_secs": _normalize_contact_active_timeout_secs(raw.get("contact_active_timeout_secs", base["contact_active_timeout_secs"])),
        "repeater_active_timeout_secs": _normalize_repeater_active_timeout_secs(raw.get("repeater_active_timeout_secs", base["repeater_active_timeout_secs"])),
        "contact_eviction_sweep_interval_secs": _normalize_contact_eviction_sweep_interval_secs(raw.get("contact_eviction_sweep_interval_secs", base["contact_eviction_sweep_interval_secs"])),
        "contact_residency_preserve_repeaters_on_node": bool(raw.get("contact_residency_preserve_repeaters_on_node", base["contact_residency_preserve_repeaters_on_node"])),
        "contact_full_table_behavior": _normalize_contact_full_table_behavior(raw.get("contact_full_table_behavior", base["contact_full_table_behavior"])),
        "signal_metrics_retention_days": _normalize_signal_metrics_retention_days(raw.get("signal_metrics_retention_days", base["signal_metrics_retention_days"])),
        "signal_metrics_poll_seconds": _normalize_signal_metrics_poll_seconds(raw.get("signal_metrics_poll_seconds", base["signal_metrics_poll_seconds"])),
        "frontend_diagnostics_enabled": bool(raw.get("frontend_diagnostics_enabled", base["frontend_diagnostics_enabled"])),
        "notifications_sound_enabled": bool(raw.get("notifications_sound_enabled", base["notifications_sound_enabled"])),
        "notification_regular_sound_file": _normalize_notification_sound_file(
            raw.get("notification_regular_sound_file", base["notification_regular_sound_file"]),
            sound_files,
            base["notification_regular_sound_file"],
        ),
        "notification_mention_sound_file": _normalize_notification_sound_file(
            raw.get("notification_mention_sound_file", base["notification_mention_sound_file"]),
            sound_files,
            base["notification_mention_sound_file"],
        ),
        "notification_direct_sound_file": _normalize_notification_sound_file(
            raw.get("notification_direct_sound_file", base["notification_direct_sound_file"]),
            sound_files,
            base["notification_direct_sound_file"],
        ),
        "page_background_id": _normalize_page_background_id(raw.get("page_background_id", base["page_background_id"]), wallpaper_files),
        "chat_background_id": _normalize_chat_background_id(raw.get("chat_background_id", base["chat_background_id"]), wallpaper_files),
        "page_background_blur_enabled": bool(raw.get("page_background_blur_enabled", base["page_background_blur_enabled"])),
        "page_background_blur_px": _normalize_page_background_blur_px(raw.get("page_background_blur_px", base["page_background_blur_px"])),
        "muted_conversations": _normalize_muted_conversations(raw.get("muted_conversations", base["muted_conversations"])),
        "muted_conversations_updated_at": _normalize_muted_conversations_updated_at(raw.get("muted_conversations_updated_at", base["muted_conversations_updated_at"])),
        "auth_enabled": auth_enabled,
        "auth_username": auth_username,
        "auth_password_hash": auth_password_hash,
        "auth_password_salt": auth_password_salt,
        "auth_session_secret": auth_session_secret,
        "saved_connections": saved_connections,
        "last_successful_key": str(raw.get("last_successful_key") or "").strip(),
        "last_successful_config": last_successful_config,
        "self_location_overrides": _normalize_self_location_overrides(raw.get("self_location_overrides", base["self_location_overrides"])),
    }


def _load_client_settings_unlocked() -> dict:
    if not os.path.isfile(CLIENT_SETTINGS_PATH):
        return _default_client_settings()
    try:
        with open(CLIENT_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            return _normalize_client_settings(json.load(fh))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        logging.exception("failed to load client settings path=%s", CLIENT_SETTINGS_PATH)
        return _default_client_settings()


def _save_client_settings_unlocked(settings: dict) -> dict:
    normalized = _normalize_client_settings(settings)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CLIENT_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(normalized, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return normalized


def _get_client_settings() -> dict:
    with CLIENT_SETTINGS_LOCK:
        return _load_client_settings_unlocked()


def _build_connection_key(config: dict) -> str:
    transport_type = str(config.get("transport_type") or (config.get("connection") or {}).get("transport_type") or "serial").strip().lower() or "serial"
    transport_id = str(config.get("transport_id") or (config.get("connection") or {}).get("transport_id") or config.get("port") or "").strip()
    baudrate = int(config.get("baudrate") or (config.get("connection") or {}).get("baudrate") or DEFAULT_BAUDRATE)
    if transport_type == "serial":
        return f'{_normalize_port_value(transport_id)}::{baudrate}'
    return f"{transport_type}::{transport_id}::{baudrate}"


def _redact_connection_payload(connection: object) -> dict:
    payload = dict(connection or {}) if isinstance(connection, dict) else {}
    payload.pop("pin", None)
    return payload


def _normalize_owner_id(value: object) -> str:
    owner_id = str(value or "").strip().lower()
    return owner_id if len(owner_id) == 64 else ""


def _get_self_location_override(owner_id: object) -> dict[str, float | int] | None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return None
    settings = _get_client_settings()
    overrides = _normalize_self_location_overrides(settings.get("self_location_overrides"))
    entry = overrides.get(normalized_owner_id)
    return dict(entry) if entry else None


def _set_self_location_override(owner_id: object, lat: object, lon: object) -> dict:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        raise ValueError("owner_id is required")
    lat_value = round(float(lat), 6)
    lon_value = round(float(lon), 6)
    if not (-90.0 <= lat_value <= 90.0):
        raise ValueError("lat must be in range -90..90")
    if not (-180.0 <= lon_value <= 180.0):
        raise ValueError("lon must be in range -180..180")
    with CLIENT_SETTINGS_LOCK:
        settings = _load_client_settings_unlocked()
        overrides = _normalize_self_location_overrides(settings.get("self_location_overrides"))
        overrides[normalized_owner_id] = {
            "lat": lat_value,
            "lon": lon_value,
            "updated_at": int(time.time()),
        }
        settings["self_location_overrides"] = overrides
        return _save_client_settings_unlocked(settings)


def _clear_self_location_override(owner_id: object) -> dict:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return _get_client_settings()
    with CLIENT_SETTINGS_LOCK:
        settings = _load_client_settings_unlocked()
        overrides = _normalize_self_location_overrides(settings.get("self_location_overrides"))
        overrides.pop(normalized_owner_id, None)
        settings["self_location_overrides"] = overrides
        return _save_client_settings_unlocked(settings)


def _apply_self_location_override(self_info: dict | None) -> dict | None:
    if not isinstance(self_info, dict):
        return self_info
    owner_id = _normalize_owner_id(self_info.get("public_key"))
    override = _get_self_location_override(owner_id)
    if not override:
        return dict(self_info)
    result = dict(self_info)
    result["lat"] = float(override["lat"])
    result["lon"] = float(override["lon"])
    result["location_override_scope"] = "local"
    return result


def _get_access_all_meshcorium_contacts() -> bool:
    return bool(_get_client_settings().get("access_all_meshcorium_contacts", True))


def _resolve_owner_id_for_port(port: str | None = None) -> str:
    normalized_port = _normalize_port_value(port)
    if normalized_port:
        session = _get_background_session(normalized_port)
        if session is not None:
            with session.snapshot_lock:
                return _normalize_owner_id((session.self_info or {}).get("public_key"))
    with BACKGROUND_SESSIONS_GUARD:
        sessions = list(BACKGROUND_SESSIONS.values())
    for session in sessions:
        with session.snapshot_lock:
            if session.active:
                owner_id = _normalize_owner_id((session.self_info or {}).get("public_key"))
                if owner_id:
                    return owner_id
    settings = _get_client_settings()
    saved_connections = list(settings.get("saved_connections") or [])
    if normalized_port:
        matching_entries = [
            entry
            for entry in saved_connections
            if _normalize_port_value((entry or {}).get("port")) == normalized_port
        ]
        matching_entries.sort(key=lambda entry: int((entry or {}).get("last_connected_at") or 0), reverse=True)
        for entry in matching_entries:
            owner_id = _normalize_owner_id((entry or {}).get("public_key"))
            if owner_id:
                return owner_id
    startup_connection_key = str(settings.get("startup_connection_key") or "").strip()
    if startup_connection_key:
        for entry in saved_connections:
            if str((entry or {}).get("key") or "").strip() == startup_connection_key:
                owner_id = _normalize_owner_id((entry or {}).get("public_key"))
                if owner_id:
                    return owner_id
    return ""


MESSAGE_SCOPE = threading.local()


@contextmanager
def _message_owner_scope(owner_id: str | None, access_all: bool, *, channel_identity: str | None = None) -> typing.Iterator[None]:
    previous_owner_id = getattr(MESSAGE_SCOPE, "owner_id", "")
    previous_access_all = getattr(MESSAGE_SCOPE, "access_all", True)
    previous_channel_identity = getattr(MESSAGE_SCOPE, "channel_identity", "")
    MESSAGE_SCOPE.owner_id = _normalize_owner_id(owner_id)
    MESSAGE_SCOPE.access_all = bool(access_all)
    MESSAGE_SCOPE.channel_identity = str(channel_identity or "").strip()
    try:
        yield
    finally:
        MESSAGE_SCOPE.owner_id = previous_owner_id
        MESSAGE_SCOPE.access_all = previous_access_all
        MESSAGE_SCOPE.channel_identity = previous_channel_identity


@contextmanager
def _contact_owner_scope(
    port: str | None = None,
    owner_id: str | None = None,
    *,
    access_all: bool | None = None,
):
    resolved_owner_id = _normalize_owner_id(owner_id) or _resolve_owner_id_for_port(port)
    resolved_access_all = _get_access_all_meshcorium_contacts() if access_all is None else bool(access_all)
    with _message_owner_scope(resolved_owner_id, resolved_access_all):
        with contact_store.contact_scope(
            owner_id=resolved_owner_id,
            access_all=resolved_access_all,
        ):
            yield resolved_owner_id


def _normalize_saved_connection_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"usb", "wifi", "ble"}:
        return normalized
    return "usb"


def _infer_saved_connection_type(port: object) -> str:
    label = str(port or "").strip().lower()
    if not label:
        return "usb"
    if any(token in label for token in ("ble", "bluetooth")):
        return "ble"
    if (
        label.startswith("tcp://")
        or label.startswith("udp://")
        or label.startswith("ws://")
        or label.startswith("wss://")
        or label.startswith("http://")
        or label.startswith("https://")
        or "/" not in label and ":" in label
    ):
        return "wifi"
    return "usb"


def _build_saved_connection_history_key(config: dict, *, public_key: str | None = None) -> str:
    base_key = _build_connection_key(config)
    normalized_public_key = str(public_key or "").strip().lower()
    if len(normalized_public_key) == 64:
        return f"{normalized_public_key}::{base_key}"
    return base_key


def _format_saved_connection_label(entry: dict) -> str:
    node_name = str(entry.get("node_name") or "").strip()
    port = _normalize_port_value(entry.get("port"))
    baudrate = int(entry.get("baudrate", DEFAULT_BAUDRATE))
    if node_name:
        return f"{node_name} · {port} @ {baudrate}"
    return f"{port} @ {baudrate}"


def _looks_like_hex_node_name(value: object) -> bool:
    text = str(value or "").strip().lower()
    if len(text) not in {32, 64}:
        return None
    return all(ch in "0123456789abcdef" for ch in text)


def _record_successful_connection(config: dict, self_info: dict | None = None, device_info: dict | None = None) -> dict:
    normalized_config = _normalize_connection_config(config)
    if normalized_config is None:
        return _get_client_settings()
    with CLIENT_SETTINGS_LOCK:
        settings = _load_client_settings_unlocked()
        public_key = str((self_info or {}).get("public_key") or "").strip().lower()
        if len(public_key) != 64:
            public_key = ""
        key = _build_saved_connection_history_key(normalized_config, public_key=public_key)
        legacy_key = _build_connection_key(normalized_config)
        now_ts = int(time.time())
        next_saved = []
        replaced = False
        startup_connection_key = str(settings.get("startup_connection_key") or "").strip()
        for entry in settings["saved_connections"]:
            entry_key = str(entry.get("key") or "").strip()
            entry_public_key = str(entry.get("public_key") or "").strip().lower()
            same_entry = (
                entry_key == key
                or (public_key and entry_public_key == public_key)
                or (not public_key and entry_key == legacy_key)
            )
            if not same_entry:
                next_saved.append(entry)
                continue
            updated = dict(entry)
            updated.update(normalized_config)
            updated["key"] = key
            updated["last_connected_at"] = now_ts
            next_node_name = str((self_info or {}).get("name") or "").strip()
            if _looks_like_hex_node_name(next_node_name):
                next_node_name = str(entry.get("node_name") or "").strip()
            updated["node_name"] = next_node_name
            updated["public_key"] = public_key
            updated["manufacturer_model"] = str((device_info or {}).get("manufacturer_model") or entry.get("manufacturer_model") or "").strip()
            updated["connection_type"] = _normalize_saved_connection_type(
                entry.get("connection_type")
                or normalized_config.get("transport_type")
                or _infer_saved_connection_type(normalized_config.get("port"))
            )
            next_saved.append(updated)
            replaced = True
            if startup_connection_key in {entry_key, entry_public_key}:
                startup_connection_key = key
        if not replaced:
            next_node_name = str((self_info or {}).get("name") or "").strip()
            if _looks_like_hex_node_name(next_node_name):
                next_node_name = ""
            next_saved.append({
                "key": key,
                **normalized_config,
                "last_connected_at": now_ts,
                "node_name": next_node_name,
                "public_key": public_key,
                "manufacturer_model": str((device_info or {}).get("manufacturer_model") or "").strip(),
                "connection_type": _normalize_saved_connection_type(
                    normalized_config.get("transport_type") or _infer_saved_connection_type(normalized_config.get("port"))
                ),
            })
        settings["saved_connections"] = next_saved
        settings["startup_connection_key"] = startup_connection_key
        settings["last_successful_key"] = key
        settings["last_successful_config"] = normalized_config
        return _save_client_settings_unlocked(settings)


def _forget_saved_connection(key: object) -> dict:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return _get_client_settings()
    with CLIENT_SETTINGS_LOCK:
        settings = _load_client_settings_unlocked()
        settings["saved_connections"] = [
            entry
            for entry in list(settings.get("saved_connections") or [])
            if str((entry or {}).get("key") or "").strip() != normalized_key
        ]
        if str(settings.get("startup_connection_key") or "").strip() == normalized_key:
            settings["startup_connection_key"] = ""
        if str(settings.get("last_successful_key") or "").strip() == normalized_key:
            settings["last_successful_key"] = ""
            settings["last_successful_config"] = None
        return _save_client_settings_unlocked(settings)


def _update_client_settings(payload: dict) -> dict:
    with CLIENT_SETTINGS_LOCK:
        settings = _load_client_settings_unlocked()
        if "auto_connect_on_service_start" in payload:
            settings["auto_connect_on_service_start"] = bool(payload.get("auto_connect_on_service_start"))
        if "startup_use_last_successful" in payload:
            settings["startup_use_last_successful"] = bool(payload.get("startup_use_last_successful"))
        if "startup_connection_key" in payload:
            settings["startup_connection_key"] = str(payload.get("startup_connection_key") or "").strip()
        if "access_all_meshcorium_contacts" in payload:
            settings["access_all_meshcorium_contacts"] = bool(payload.get("access_all_meshcorium_contacts"))
        if "contact_active_timeout_secs" in payload:
            settings["contact_active_timeout_secs"] = _normalize_contact_active_timeout_secs(payload.get("contact_active_timeout_secs"))
        if "repeater_active_timeout_secs" in payload:
            settings["repeater_active_timeout_secs"] = _normalize_repeater_active_timeout_secs(payload.get("repeater_active_timeout_secs"))
        if "contact_eviction_sweep_interval_secs" in payload:
            settings["contact_eviction_sweep_interval_secs"] = _normalize_contact_eviction_sweep_interval_secs(payload.get("contact_eviction_sweep_interval_secs"))
        if "contact_residency_preserve_repeaters_on_node" in payload:
            settings["contact_residency_preserve_repeaters_on_node"] = bool(payload.get("contact_residency_preserve_repeaters_on_node"))
        if "contact_full_table_behavior" in payload:
            settings["contact_full_table_behavior"] = _normalize_contact_full_table_behavior(payload.get("contact_full_table_behavior"))
        if "signal_metrics_retention_days" in payload:
            settings["signal_metrics_retention_days"] = _normalize_signal_metrics_retention_days(payload.get("signal_metrics_retention_days"))
        if "signal_metrics_poll_seconds" in payload:
            settings["signal_metrics_poll_seconds"] = _normalize_signal_metrics_poll_seconds(payload.get("signal_metrics_poll_seconds"))
        if "frontend_diagnostics_enabled" in payload:
            settings["frontend_diagnostics_enabled"] = bool(payload.get("frontend_diagnostics_enabled"))
        if "notifications_sound_enabled" in payload:
            settings["notifications_sound_enabled"] = bool(payload.get("notifications_sound_enabled"))
        available_sound_files = _list_sound_files()
        if "notification_regular_sound_file" in payload:
            settings["notification_regular_sound_file"] = _normalize_notification_sound_file(
                payload.get("notification_regular_sound_file"),
                available_sound_files,
                settings.get("notification_regular_sound_file", ""),
            )
        if "notification_mention_sound_file" in payload:
            settings["notification_mention_sound_file"] = _normalize_notification_sound_file(
                payload.get("notification_mention_sound_file"),
                available_sound_files,
                settings.get("notification_mention_sound_file", ""),
            )
        if "notification_direct_sound_file" in payload:
            settings["notification_direct_sound_file"] = _normalize_notification_sound_file(
                payload.get("notification_direct_sound_file"),
                available_sound_files,
                settings.get("notification_direct_sound_file", ""),
            )
        available_wallpaper_files = _list_wallpaper_files()
        if "page_background_id" in payload:
            settings["page_background_id"] = _normalize_page_background_id(
                payload.get("page_background_id"),
                available_wallpaper_files,
            )
        if "chat_background_id" in payload:
            settings["chat_background_id"] = _normalize_chat_background_id(
                payload.get("chat_background_id"),
                available_wallpaper_files,
            )
        if "page_background_blur_enabled" in payload:
            settings["page_background_blur_enabled"] = bool(payload.get("page_background_blur_enabled"))
        if "page_background_blur_px" in payload:
            settings["page_background_blur_px"] = _normalize_page_background_blur_px(payload.get("page_background_blur_px"))
        if "muted_conversations" in payload:
            incoming_muted = _normalize_muted_conversations(payload.get("muted_conversations"))
            incoming_updated_at = _normalize_muted_conversations_updated_at(payload.get("muted_conversations_updated_at"))
            current_updated_at = _normalize_muted_conversations_updated_at(settings.get("muted_conversations_updated_at"))
            current_muted = _normalize_muted_conversations(settings.get("muted_conversations"))
            if incoming_updated_at <= 0:
                incoming_updated_at = int(time.time() * 1000)
            if current_updated_at and incoming_updated_at < current_updated_at and incoming_muted != current_muted:
                logging.info(
                    "ignoring stale muted_conversations update incoming_updated_at=%s current_updated_at=%s",
                    incoming_updated_at,
                    current_updated_at,
                )
            else:
                settings["muted_conversations"] = incoming_muted
                settings["muted_conversations_updated_at"] = max(current_updated_at, incoming_updated_at)
        if "self_location_overrides" in payload:
            settings["self_location_overrides"] = _normalize_self_location_overrides(payload.get("self_location_overrides"))
        auth_username_present = "auth_username" in payload
        auth_enabled_present = "auth_enabled" in payload
        auth_password_present = "auth_password" in payload
        if auth_username_present:
            settings["auth_username"] = _normalize_auth_username(payload.get("auth_username"))
        if auth_password_present:
            raw_password = str(payload.get("auth_password") or "")
            if raw_password.strip():
                salt = _generate_auth_salt()
                settings["auth_password_salt"] = salt
                settings["auth_password_hash"] = _hash_auth_password(raw_password, salt)
            elif not settings.get("auth_password_hash"):
                settings["auth_password_salt"] = ""
                settings["auth_password_hash"] = ""
        if auth_enabled_present:
            settings["auth_enabled"] = bool(payload.get("auth_enabled"))
        if settings.get("auth_enabled"):
            if not settings.get("auth_username"):
                raise ValueError("auth username is required when local authorization is enabled")
            if not settings.get("auth_password_hash") or not settings.get("auth_password_salt"):
                raise ValueError("set a password before enabling local authorization")
            if not settings.get("auth_session_secret"):
                settings["auth_session_secret"] = _generate_auth_session_secret()
        normalized = _save_client_settings_unlocked(settings)
    _prune_signal_metrics(_normalize_signal_metrics_retention_days(normalized.get("signal_metrics_retention_days")))
    return normalized


def _resolve_startup_connection_config(settings: dict) -> dict | None:
    normalized = _normalize_client_settings(settings)
    if not normalized["auto_connect_on_service_start"]:
        return None
    try:
        available_connection_ids = {
            str((item or {}).get("transport_id") or (item or {}).get("device") or "").strip()
            for item in list(DEFAULT_CONNECTION_ROUTER.discover() or [])
            if str((item or {}).get("transport_id") or (item or {}).get("device") or "").strip()
        }
    except Exception:
        available_connection_ids = set()

    def _validate_available(config: dict | None) -> dict | None:
        normalized_config = _normalize_connection_config(config)
        if normalized_config is None:
            return None
        target_id = str(normalized_config.get("transport_id") or normalized_config.get("port") or "").strip()
        if available_connection_ids and target_id not in available_connection_ids:
            logging.info(
                "startup auto-connect skipped unavailable connection=%s baudrate=%s",
                target_id,
                normalized_config.get("baudrate"),
            )
            return None
        return normalized_config

    if normalized["startup_use_last_successful"]:
        return _validate_available(normalized.get("last_successful_config"))
    selected_key = str(normalized.get("startup_connection_key") or "").strip()
    if not selected_key:
        return None
    for entry in normalized["saved_connections"]:
        if str(entry.get("key")) == selected_key:
            return _validate_available(entry)
    return None


def _cancel_pending_reconnect(port: str) -> None:
    normalized_port = _normalize_port_value(port)
    if not normalized_port:
        return
    session = _get_background_session(normalized_port)
    if session is not None:
        with session.snapshot_lock:
            session.reconnect_scheduled_at = 0
            session.reconnect_delay_secs = 0.0
            session.next_reconnect_at = 0
    with PENDING_RECONNECTS_GUARD:
        event = PENDING_RECONNECTS.pop(normalized_port, None)
        PENDING_RECONNECT_META.pop(normalized_port, None)
    if event is not None:
        event.set()


def _classify_background_session_exception(exc: Exception, *, queue_drain_active: bool = False) -> dict:
    message = str(exc or "").strip()
    lowered = message.lower()
    if message == "serial client closed":
        return {
            "failure_kind": "client-closed",
            "stop_kind": "reader-closed",
            "reason": message,
            "auto_reconnect": False,
            "error_event": False,
        }
    if message == "serial timeout while reading 1 bytes, got 0":
        if queue_drain_active:
            return {
                "failure_kind": "queue-drain-timeout",
                "stop_kind": "queue-drain-timeout",
                "reason": message,
                "auto_reconnect": True,
                "error_event": False,
            }
        return {
            "failure_kind": "read-timeout",
            "stop_kind": "serial-read-timeout",
            "reason": message,
            "auto_reconnect": True,
            "error_event": False,
        }
    if "serial timeout while reading" in lowered:
        if queue_drain_active:
            return {
                "failure_kind": "queue-drain-timeout",
                "stop_kind": "queue-drain-timeout",
                "reason": message,
                "auto_reconnect": True,
                "error_event": False,
            }
        return {
            "failure_kind": "serial-timeout-burst",
            "stop_kind": "serial-read-timeout",
            "reason": message,
            "auto_reconnect": True,
            "error_event": False,
        }
    if message == "empty response to SYNC_NEXT_MESSAGE":
        return {
            "failure_kind": "queue-drain-timeout" if queue_drain_active else "read-timeout",
            "stop_kind": "queue-drain-timeout" if queue_drain_active else "serial-read-timeout",
            "reason": message,
            "auto_reconnect": True,
            "error_event": False,
        }
    if isinstance(exc, SerialException):
        return {
            "failure_kind": "serial-port-failure",
            "stop_kind": "serial-failure",
            "reason": message or exc.__class__.__name__,
            "auto_reconnect": True,
            "error_event": True,
        }
    if isinstance(exc, BleTransportUnavailable):
        return {
            "failure_kind": "ble-unavailable",
            "stop_kind": "ble-unavailable",
            "reason": message or exc.__class__.__name__,
            "auto_reconnect": False,
            "error_event": True,
        }
    if isinstance(exc, sqlite3.Error):
        return {
            "failure_kind": "storage-failure",
            "stop_kind": "storage-failure",
            "reason": message or exc.__class__.__name__,
            "auto_reconnect": False,
            "error_event": True,
        }
    if "unexpected frame" in lowered or "unexpected response" in lowered or "unexpected frame prefix" in lowered:
        return {
            "failure_kind": "protocol-frame-error",
            "stop_kind": "protocol-error",
            "reason": message,
            "auto_reconnect": True,
            "error_event": True,
        }
    return {
        "failure_kind": "session-failure",
        "stop_kind": "serial-failure",
        "reason": message or exc.__class__.__name__,
        "auto_reconnect": True,
        "error_event": True,
    }


def _build_ble_transport_diagnostics(error_message: object) -> dict:
    message = str(error_message or "").strip()
    lowered = message.lower()
    kind = "ble-unavailable"
    hints = [
        "Check that the MeshCore node advertises BLE and is within range.",
        "Retry scanning after restarting the node BLE/companion firmware.",
    ]
    if "python package 'bleak' is not installed" in lowered:
        kind = "python-dependency-missing"
        hints = [
            "Install Python dependency `bleak` from requirements.txt.",
            "Restart meshcorium.service after dependency installation.",
        ]
    elif "bluetooth.service is not active" in lowered:
        kind = "bluez-inactive"
        hints = [
            "Install BlueZ if it is missing.",
            "Start bluetooth.service and verify it is active.",
        ]
    elif "d-bus access denied" in lowered or "operation not permitted" in lowered:
        kind = "dbus-access-denied"
        hints = [
            "Verify the service user can access the system D-Bus BlueZ API.",
            "Check host sandboxing and systemd service permissions.",
        ]
    elif "no linux bluetooth adapters found" in lowered or "no bluetooth adapters found" in lowered:
        kind = "adapter-missing"
        hints = [
            "Attach or enable a Linux Bluetooth adapter such as hci0 or hci1.",
            "Check adapter power/block state with bluetoothctl or rfkill.",
            "If multiple adapters exist, pass the intended adapter_id.",
        ]
    elif "not paired" in lowered:
        kind = "pairing-required"
        hints = [
            "Pair the MeshCore BLE device with this Linux host before connecting.",
            "Verify the configured BLE PIN and retry pairing if BlueZ still reports Not paired.",
            "If using a desktop Bluetooth agent, complete the pairing prompt before retrying Meshcorium connect.",
        ]
    elif "not found during pre-connect scan" in lowered:
        kind = "ble-device-not-advertising"
        hints = [
            "The device is present in BlueZ history but was not seen in the active BLE advertising window.",
            "Keep the MeshCore node awake and advertising, then retry scan/connect.",
            "If this repeats under a VM, reattach the USB Bluetooth adapter or try a different adapter/controller passthrough mode.",
        ]
    elif "eoferror" in lowered:
        kind = "ble-dbus-connection-closed"
        hints = [
            "BlueZ/D-Bus closed the BLE operation while enabling or using GATT.",
            "Check kernel logs for HCI timeouts or LE connection aborts.",
            "Reattach the Bluetooth adapter or try a more stable Linux-supported BLE adapter.",
        ]
    elif "timed out before nus became ready" in lowered or "connect timed out" in lowered:
        kind = "ble-connect-timeout"
        hints = [
            "The BLE device was resolved, but BlueZ/Bleak did not complete connect/NUS setup in time.",
            "Check whether the node disconnected, went to sleep, or stopped advertising during connect.",
            "If this happens under a VM, reattach the USB Bluetooth adapter or use a more stable adapter/controller passthrough mode.",
        ]
    return {
        "kind": kind,
        "message": message,
        "hints": hints,
    }


def _compute_background_reconnect_delay(failure_kind: str | None, reconnect_attempts: int) -> float:
    attempts = max(1, int(reconnect_attempts or 0))
    kind = str(failure_kind or "").strip().lower()
    if kind == "queue-drain-timeout":
        return max(0.5, min(0.5 * (2 ** max(0, attempts - 1)), 4.0))
    if kind in {"read-timeout", "serial-timeout-burst"}:
        return max(0.75, min(0.75 * (2 ** max(0, attempts - 1)), 6.0))
    if kind == "protocol-frame-error":
        return max(1.5, min(1.5 * (2 ** max(0, attempts - 1)), 12.0))
    if kind == "serial-port-failure":
        return max(float(SERVICE_RECONNECT_DELAY_SECS), min(float(SERVICE_RECONNECT_DELAY_SECS) * (2 ** max(0, attempts - 1)), 30.0))
    return max(float(SERVICE_RECONNECT_DELAY_SECS), min(float(SERVICE_RECONNECT_DELAY_SECS) * (2 ** max(0, attempts - 1)), 20.0))


def _schedule_background_reconnect(
    config: dict,
    reason: str,
    delay_secs: float = SERVICE_RECONNECT_DELAY_SECS,
    *,
    failure_kind: str | None = None,
) -> None:
    normalized_config = _normalize_connection_config(config)
    if normalized_config is None:
        return
    port = normalized_config["port"]
    session = _get_background_session(port)
    effective_delay_secs = float(delay_secs)
    reconnect_attempts = 0
    if session is not None:
        with session.snapshot_lock:
            session.last_reconnect_reason = str(reason or "")
            session.reconnect_scheduled_at = utc_now_epoch()
            effective_delay_secs = _compute_background_reconnect_delay(
                failure_kind if failure_kind is not None else session.last_failure_kind,
                int(session.reconnect_attempts or 0),
            )
            session.reconnect_delay_secs = float(effective_delay_secs)
            session.next_reconnect_at = int(session.reconnect_scheduled_at + max(0.0, float(effective_delay_secs)))
            reconnect_attempts = int(session.reconnect_attempts or 0)
        _log_delivery_debug(
            "bg_reconnect_scheduled",
            port=port,
            reason=str(reason or ""),
            failure_kind=str(failure_kind if failure_kind is not None else (session.last_failure_kind if session is not None else "") or ""),
            delay_secs=float(effective_delay_secs),
            next_reconnect_at=int(session.next_reconnect_at if session is not None else 0),
            reconnect_attempts=int(reconnect_attempts or 0),
        )
    schedule_signature = {
        "reason": str(reason or ""),
        "failure_kind": str(failure_kind or (session.last_failure_kind if session is not None else "") or ""),
        "delay_secs": round(float(effective_delay_secs), 3),
        "next_reconnect_at": int(session.next_reconnect_at if session is not None else 0),
        "reconnect_attempts": int(reconnect_attempts or 0),
    }
    with PENDING_RECONNECTS_GUARD:
        existing_event = PENDING_RECONNECTS.get(port)
        existing_meta = PENDING_RECONNECT_META.get(port)
        if existing_event is not None and existing_meta == schedule_signature:
            return
    _cancel_pending_reconnect(port)
    cancel_event = threading.Event()
    with PENDING_RECONNECTS_GUARD:
        PENDING_RECONNECTS[port] = cancel_event
        PENDING_RECONNECT_META[port] = dict(schedule_signature)

    def _runner() -> None:
        logging.info(
            "scheduled background reconnect port=%s baudrate=%s delay_secs=%s reason=%s",
            port,
            normalized_config["baudrate"],
            effective_delay_secs,
            reason,
        )
        if cancel_event.wait(effective_delay_secs):
            return
        with BACKGROUND_SESSIONS_GUARD:
            existing = BACKGROUND_SESSIONS.get(port)
        if existing and existing.thread and existing.thread.is_alive() and not existing.stop_event.is_set():
            _cancel_pending_reconnect(port)
            return
        pending_session = _get_background_session(port)
        if pending_session is not None:
            with pending_session.snapshot_lock:
                pending_session.reconnect_scheduled_at = 0
                pending_session.reconnect_delay_secs = 0.0
                pending_session.next_reconnect_at = 0
        try:
            _start_background_session(normalized_config)
            logging.info("background reconnect started port=%s baudrate=%s", port, normalized_config["baudrate"])
            _log_delivery_debug(
                "bg_reconnect_started",
                port=port,
                reason=str(reason or ""),
                delay_secs=float(effective_delay_secs),
            )
        finally:
            with PENDING_RECONNECTS_GUARD:
                current = PENDING_RECONNECTS.get(port)
                if current is cancel_event:
                    PENDING_RECONNECTS.pop(port, None)
                    PENDING_RECONNECT_META.pop(port, None)

    threading.Thread(target=_runner, name=f"meshcore-reconnect-{port}", daemon=True).start()


def _list_active_sessions() -> list[dict]:
    with BACKGROUND_SESSIONS_GUARD:
        sessions = list(BACKGROUND_SESSIONS.values())
    items = []
    for session in sessions:
        snapshot = _build_session_snapshot(session)
        if not snapshot["active"]:
            continue
        items.append(
            {
                "connection": dict(snapshot.get("connection") or {}),
                "port": snapshot["port"],
                "baudrate": snapshot["baudrate"],
                "transport_type": str(snapshot.get("transport_type") or "serial"),
                "transport_id": str(snapshot.get("transport_id") or snapshot["port"]),
                "self_name": str((snapshot.get("self") or {}).get("name") or "").strip(),
                "queue_drain_in_progress": bool((snapshot.get("queue_state") or {}).get("drain_in_progress")),
                "queue_drain_requested": bool((snapshot.get("queue_state") or {}).get("drain_requested")),
                "queue_last_reason": str((snapshot.get("queue_state") or {}).get("last_reason") or ""),
                "queue_last_overflow_risk": bool((snapshot.get("queue_state") or {}).get("last_overflow_risk")),
                "queue_last_drain_message_count": int((snapshot.get("queue_state") or {}).get("last_drain_message_count") or 0),
                "queue_last_drain_cycles": int((snapshot.get("queue_state") or {}).get("last_drain_cycles") or 0),
                "key": _build_connection_key(snapshot),
            }
        )
    items.sort(key=lambda item: (item["self_name"], item["port"]))
    return items


def _list_recovering_sessions() -> list[dict]:
    with BACKGROUND_SESSIONS_GUARD:
        sessions = list(BACKGROUND_SESSIONS.values())
    items = []
    for session in sessions:
        snapshot = _build_session_snapshot(session, include_contacts=False, include_channels=False)
        stop_state = snapshot.get("stop_state") or {}
        if snapshot["active"]:
            continue
        if not int(stop_state.get("reconnect_attempts") or 0) and not int(stop_state.get("next_reconnect_at") or 0):
            continue
        items.append(
            {
                "connection": dict(snapshot.get("connection") or {}),
                "port": snapshot["port"],
                "baudrate": snapshot["baudrate"],
                "transport_type": str(snapshot.get("transport_type") or "serial"),
                "transport_id": str(snapshot.get("transport_id") or snapshot["port"]),
                "self_name": str((snapshot.get("self") or {}).get("name") or "").strip(),
                "last_failure_kind": str(stop_state.get("last_failure_kind") or ""),
                "last_reconnect_reason": str(stop_state.get("last_reconnect_reason") or ""),
                "reconnect_attempts": int(stop_state.get("reconnect_attempts") or 0),
                "reconnect_scheduled_at": int(stop_state.get("reconnect_scheduled_at") or 0),
                "reconnect_delay_secs": float(stop_state.get("reconnect_delay_secs") or 0.0),
                "next_reconnect_at": int(stop_state.get("next_reconnect_at") or 0),
                "key": _build_connection_key(snapshot),
            }
        )
    items.sort(key=lambda item: (item["self_name"], item["port"]))
    return items


def _build_client_settings_payload() -> dict:
    settings = _get_client_settings()
    resolved = _resolve_startup_connection_config(settings)
    sound_files = _list_sound_files()
    wallpaper_files = _list_wallpaper_files()
    return {
        "settings": {
            "auto_connect_on_service_start": bool(settings.get("auto_connect_on_service_start")),
            "startup_use_last_successful": bool(settings.get("startup_use_last_successful")),
            "startup_connection_key": str(settings.get("startup_connection_key") or ""),
            "access_all_meshcorium_contacts": bool(settings.get("access_all_meshcorium_contacts", True)),
            "contact_active_timeout_secs": _normalize_contact_active_timeout_secs(settings.get("contact_active_timeout_secs")),
            "repeater_active_timeout_secs": _normalize_repeater_active_timeout_secs(settings.get("repeater_active_timeout_secs")),
            "contact_eviction_sweep_interval_secs": _normalize_contact_eviction_sweep_interval_secs(settings.get("contact_eviction_sweep_interval_secs")),
            "contact_residency_preserve_repeaters_on_node": bool(settings.get("contact_residency_preserve_repeaters_on_node", False)),
            "contact_full_table_behavior": _normalize_contact_full_table_behavior(settings.get("contact_full_table_behavior")),
            "signal_metrics_retention_days": _normalize_signal_metrics_retention_days(settings.get("signal_metrics_retention_days")),
            "signal_metrics_poll_seconds": _normalize_signal_metrics_poll_seconds(settings.get("signal_metrics_poll_seconds")),
            "frontend_diagnostics_enabled": bool(settings.get("frontend_diagnostics_enabled", True)),
            "notifications_sound_enabled": bool(settings.get("notifications_sound_enabled")),
            "notification_regular_sound_file": _normalize_notification_sound_file(settings.get("notification_regular_sound_file"), sound_files),
            "notification_mention_sound_file": _normalize_notification_sound_file(settings.get("notification_mention_sound_file"), sound_files),
            "notification_direct_sound_file": _normalize_notification_sound_file(settings.get("notification_direct_sound_file"), sound_files),
            "page_background_id": _normalize_page_background_id(settings.get("page_background_id"), wallpaper_files),
            "chat_background_id": _normalize_chat_background_id(settings.get("chat_background_id"), wallpaper_files),
            "page_background_blur_enabled": bool(settings.get("page_background_blur_enabled")),
            "page_background_blur_px": _normalize_page_background_blur_px(settings.get("page_background_blur_px")),
            "muted_conversations": _normalize_muted_conversations(settings.get("muted_conversations")),
            "muted_conversations_updated_at": _normalize_muted_conversations_updated_at(settings.get("muted_conversations_updated_at")),
            "self_location_overrides": _normalize_self_location_overrides(settings.get("self_location_overrides")),
            "auth_enabled": bool(settings.get("auth_enabled")),
            "auth_username": _normalize_auth_username(settings.get("auth_username")),
            "auth_password_configured": bool(settings.get("auth_password_hash")),
        },
        "notification_sound_files": sound_files,
        "wallpaper_files": [
            {
                "name": file_name,
                "url": _build_wallpaper_url(file_name),
            }
            for file_name in wallpaper_files
        ],
        "saved_connections": [
            {
                "key": str(entry.get("key") or ""),
                "label": _format_saved_connection_label(entry),
                "connection": dict(entry.get("connection") or {}),
                "port": entry["port"],
                "baudrate": int(entry["baudrate"]),
                "transport_type": str(entry.get("transport_type") or "serial"),
                "transport_id": str(entry.get("transport_id") or entry.get("port") or ""),
                "node_name": str(entry.get("node_name") or ""),
                "public_key": str(entry.get("public_key") or ""),
                "manufacturer_model": str(entry.get("manufacturer_model") or ""),
                "connection_type": _normalize_saved_connection_type(entry.get("connection_type")),
                "last_connected_at": int(entry.get("last_connected_at") or 0),
            }
            for entry in settings.get("saved_connections", [])
        ],
        "last_successful_key": str(settings.get("last_successful_key") or ""),
        "last_successful_config": settings.get("last_successful_config"),
        "resolved_startup_connection": resolved,
        "active_sessions": _list_active_sessions(),
        "recovering_sessions": _list_recovering_sessions(),
    }


def _normalize_auth_username(value: object) -> str:
    return str(value or "").strip()[:64]


def _generate_auth_salt() -> str:
    return secrets.token_hex(16)


def _generate_auth_session_secret() -> str:
    return secrets.token_hex(32)


def _hash_auth_password(password: str, salt_hex: str) -> str:
    password_bytes = str(password or "").encode("utf-8")
    salt_bytes = bytes.fromhex(str(salt_hex or ""))
    if not password_bytes:
        raise ValueError("auth password is required")
    if not salt_bytes:
        raise ValueError("auth password salt is invalid")
    digest = hashlib.pbkdf2_hmac("sha256", password_bytes, salt_bytes, 200_000)
    return digest.hex()


def _verify_auth_password(password: str, settings: dict | None = None) -> bool:
    current = settings or _get_client_settings()
    expected_hash = str(current.get("auth_password_hash") or "")
    salt_hex = str(current.get("auth_password_salt") or "")
    if not expected_hash or not salt_hex:
        return False
    try:
        actual_hash = _hash_auth_password(password, salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(actual_hash, expected_hash)


def _is_local_auth_enabled(settings: dict | None = None) -> bool:
    current = settings or _get_client_settings()
    return bool(
        current.get("auth_enabled")
        and str(current.get("auth_username") or "").strip()
        and str(current.get("auth_password_hash") or "").strip()
        and str(current.get("auth_password_salt") or "").strip()
    )


def _build_auth_cookie(username: str, session_secret: str) -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_hex(12)
    payload = f"{username}:{issued_at}:{nonce}"
    signature = hmac.new(session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _build_auth_cookie_header(cookie_value: str, max_age: int = 30 * 24 * 60 * 60) -> str:
    return f"meshcorium_auth={cookie_value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={int(max_age)}"


def _build_auth_cookie_clear_header() -> str:
    return "meshcorium_auth=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


def _extract_cookie_value(cookie_header: str, key: str) -> str:
    for chunk in str(cookie_header or "").split(";"):
        if "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        if name.strip() == key:
            return value.strip()
    return ""


def _is_authenticated_request(handler: "MeshcoriumWebHandler", settings: dict | None = None) -> bool:
    current = settings or _get_client_settings()
    if not _is_local_auth_enabled(current):
        return True
    cookie_value = _extract_cookie_value(handler.headers.get("Cookie", ""), "meshcorium_auth")
    if not cookie_value:
        return False
    parts = cookie_value.split(":")
    if len(parts) != 4:
        return False
    username, issued_at_raw, nonce, signature = parts
    expected_username = str(current.get("auth_username") or "").strip()
    session_secret = str(current.get("auth_session_secret") or "").strip()
    if not expected_username or not session_secret or username != expected_username:
        return False
    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        return False
    if issued_at <= 0 or (time.time() - issued_at) > 30 * 24 * 60 * 60:
        return False
    payload = f"{username}:{issued_at}:{nonce}"
    expected_signature = hmac.new(session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def _normalize_login_next_path(next_path: str = "/") -> str:
    next_value = next_path if str(next_path or "").startswith("/") else "/"
    if next_value in {"", "/", "/connect", "/settings"}:
        return "/messages"
    return next_value


def _build_login_html(next_path: str = "/", error_message: str = "", username: str = "") -> str:
    next_value = _normalize_login_next_path(next_path)
    error_block = ""
    if error_message:
        safe_error = json.dumps(str(error_message))
        error_block = f'<div id="login-error" class="login-error">{json.loads(safe_error)}</div>'
    else:
        error_block = '<div id="login-error" class="login-error collapsed"></div>'
    safe_username = json.dumps(str(username or ""))
    safe_next = json.dumps(next_value)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Meshcorium Login</title>
  <style>
    :root {{
      color-scheme: dark;
      --login-bg: #2d2a37;
      --login-panel: #433f51;
      --login-panel-edge: rgba(255,255,255,0.08);
      --login-input: #26232f;
      --login-input-edge: rgba(255,255,255,0.12);
      --login-accent: #1fc4ee;
      --login-accent-hover: #39cff5;
      --login-text: #f2f4fb;
      --login-muted: rgba(242,244,251,0.78);
      --login-error-bg: rgba(214, 71, 71, 0.15);
      --login-error-edge: rgba(214, 71, 71, 0.45);
      --login-cancel: rgba(255,255,255,0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Segoe UI", system-ui, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(31,196,238,0.12), transparent 32%),
        linear-gradient(180deg, #24212c 0%, #312d3a 100%);
      color: var(--login-text);
      padding: 20px;
    }}
    .login-shell {{
      width: min(100%, 360px);
      background: var(--login-panel);
      border: 1px solid var(--login-panel-edge);
      border-radius: 16px;
      padding: 18px 16px 16px;
      box-shadow: 0 28px 80px rgba(0,0,0,0.34);
    }}
    .login-host {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--login-text);
      font-size: 15px;
      margin-bottom: 18px;
    }}
    .login-host-dot {{
      width: 14px;
      height: 14px;
      border: 1.5px solid rgba(255,255,255,0.82);
      border-radius: 50%;
      position: relative;
    }}
    .login-host-dot::before,
    .login-host-dot::after {{
      content: "";
      position: absolute;
      inset: 2px;
      border-radius: 50%;
      border-top: 1px solid rgba(255,255,255,0.72);
      border-bottom: 1px solid rgba(255,255,255,0.72);
    }}
    .login-copy {{
      margin: 0 0 14px;
      color: var(--login-muted);
      font-size: 15px;
      line-height: 1.45;
    }}
    .login-form {{
      display: grid;
      gap: 14px;
    }}
    .login-field {{
      display: grid;
      gap: 8px;
    }}
    .login-label {{
      color: var(--login-text);
      font-size: 14px;
    }}
    .login-input-wrap {{
      position: relative;
    }}
    .login-input {{
      width: 100%;
      height: 46px;
      border-radius: 10px;
      border: 1px solid var(--login-input-edge);
      background: var(--login-input);
      color: var(--login-text);
      padding: 0 14px;
      font-size: 16px;
      outline: none;
      transition: border-color .18s ease, box-shadow .18s ease;
    }}
    .login-input:focus {{
      border-color: var(--login-accent);
      box-shadow: 0 0 0 3px rgba(31,196,238,0.16);
    }}
    .login-password-toggle {{
      position: absolute;
      right: 10px;
      top: 50%;
      transform: translateY(-50%);
      border: 0;
      background: transparent;
      color: rgba(255,255,255,0.8);
      cursor: pointer;
      font-size: 17px;
      padding: 4px 6px;
    }}
    .login-password-toggle:hover {{ color: #fff; }}
    .login-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 2px;
    }}
    .login-button {{
      min-width: 92px;
      height: 42px;
      border-radius: 10px;
      border: 0;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
    }}
    .login-button-primary {{
      background: var(--login-accent);
      color: #072531;
    }}
    .login-button-primary:hover {{ background: var(--login-accent-hover); }}
    .login-button-secondary {{
      background: var(--login-cancel);
      color: var(--login-text);
    }}
    .login-error {{
      border-radius: 10px;
      border: 1px solid var(--login-error-edge);
      background: var(--login-error-bg);
      color: #ffd9d9;
      padding: 10px 12px;
      font-size: 14px;
      line-height: 1.4;
    }}
    .collapsed {{ display: none !important; }}
  </style>
</head>
<body>
  <main class="login-shell">
    <div class="login-host">
      <span class="login-host-dot" aria-hidden="true"></span>
      <span id="login-hostname"></span>
    </div>
    <p class="login-copy">Этот сайт просит вас войти.</p>
    {error_block}
    <form id="login-form" class="login-form">
      <div class="login-field">
        <label class="login-label" for="login-username">Имя пользователя</label>
        <div class="login-input-wrap">
          <input id="login-username" class="login-input" type="text" autocomplete="username" spellcheck="false">
        </div>
      </div>
      <div class="login-field">
        <label class="login-label" for="login-password">Пароль</label>
        <div class="login-input-wrap">
          <input id="login-password" class="login-input" type="password" autocomplete="current-password">
          <button id="login-password-toggle" class="login-password-toggle" type="button" aria-label="Показать пароль">◉</button>
        </div>
      </div>
      <div class="login-actions">
        <button class="login-button login-button-primary" type="submit">Войти</button>
        <button id="login-cancel" class="login-button login-button-secondary" type="button">Отмена</button>
      </div>
    </form>
  </main>
  <script>
    const nextPath = {safe_next};
    const initialUsername = {safe_username};
    const hostNode = document.getElementById('login-hostname');
    const userNode = document.getElementById('login-username');
    const passwordNode = document.getElementById('login-password');
    const errorNode = document.getElementById('login-error');
    const toggleNode = document.getElementById('login-password-toggle');
    hostNode.textContent = window.location.host || 'Meshcorium';
    userNode.value = initialUsername;
    document.getElementById('login-cancel').addEventListener('click', () => {{
      window.location.href = 'about:blank';
    }});
    toggleNode.addEventListener('click', () => {{
      const nextType = passwordNode.type === 'password' ? 'text' : 'password';
      passwordNode.type = nextType;
      toggleNode.setAttribute('aria-label', nextType === 'password' ? 'Показать пароль' : 'Скрыть пароль');
    }});
    document.getElementById('login-form').addEventListener('submit', async (event) => {{
      event.preventDefault();
      errorNode.classList.add('collapsed');
      errorNode.textContent = '';
      try {{
        const response = await fetch('/api/auth/login', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            username: userNode.value,
            password: passwordNode.value,
          }}),
        }});
        const data = await response.json();
        if (!response.ok) {{
          throw new Error(data.error || `HTTP ${{response.status}}`);
        }}
        window.location.href = nextPath || '/';
      }} catch (error) {{
        errorNode.textContent = error.message || 'Не удалось войти.';
        errorNode.classList.remove('collapsed');
      }}
    }});
  </script>
</body>
</html>"""


def _build_contact_debug_payload(port: str | None = None, public_key: str | None = None) -> dict:
    active_port = _normalize_port_value(port)
    session = _get_background_session(active_port) if active_port else None
    live_contacts = []
    if session:
        with session.snapshot_lock:
            live_contacts = list(session.contacts or [])
    with _contact_owner_scope(port=active_port):
        return CONTACT_BACKEND.build_debug_payload(
            active_port=active_port,
            live_contacts=live_contacts,
            public_key=public_key,
            stale_after_secs=max(
                _get_contact_active_timeout_secs(),
                _get_repeater_active_timeout_secs(),
            ),
            policy={
                "contact_active_timeout_secs": _get_contact_active_timeout_secs(),
                "repeater_active_timeout_secs": _get_repeater_active_timeout_secs(),
                "contact_eviction_sweep_interval_secs": _get_contact_eviction_sweep_interval_secs(),
                "preserve_favorites_on_node": True,
                "preserve_direct_history_on_node": True,
                "preserve_repeaters_on_node": _get_contact_residency_preserve_repeaters_on_node(),
                "full_table_behavior": _get_contact_full_table_behavior(),
            },
            recent_events=_read_json_log_tail(CONTACT_DEBUG_LOG_PATH, 60),
        )


def _get_contact_active_timeout_secs() -> int:
    return _normalize_contact_active_timeout_secs(_get_client_settings().get("contact_active_timeout_secs"))


def _get_repeater_active_timeout_secs() -> int:
    return _normalize_repeater_active_timeout_secs(_get_client_settings().get("repeater_active_timeout_secs"))


def _get_contact_eviction_sweep_interval_secs() -> int:
    return _normalize_contact_eviction_sweep_interval_secs(_get_client_settings().get("contact_eviction_sweep_interval_secs"))


def _get_contact_residency_preserve_favorites_on_node() -> bool:
    return True


def _get_contact_residency_preserve_repeaters_on_node() -> bool:
    return bool(_get_client_settings().get("contact_residency_preserve_repeaters_on_node", False))


def _get_contact_full_table_behavior() -> str:
    return _normalize_contact_full_table_behavior(_get_client_settings().get("contact_full_table_behavior"))


def _attempt_service_startup_auto_connect() -> None:
    settings = _get_client_settings()
    config = _resolve_startup_connection_config(settings)
    if config is None:
        logging.info("service startup auto-connect disabled")
        return
    try:
        _start_background_session(config)
        logging.info(
            "service startup auto-connect scheduled port=%s baudrate=%s",
            config["port"],
            config["baudrate"],
        )
    except Exception:
        logging.exception(
            "service startup auto-connect failed port=%s baudrate=%s",
            config["port"],
            config["baudrate"],
        )


@dataclass
class RepeaterRuntimeTracker:
    full_keys: dict[str, int] = field(default_factory=dict)
    provisional_tokens: dict[str, int] = field(default_factory=dict)


@dataclass
class BackgroundCompanionSession:
    config: dict
    stop_event: threading.Event = field(default_factory=threading.Event)
    ready_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    client: MeshCoreSerialClient | None = None
    command_queue: queue.PriorityQueue = field(default_factory=queue.PriorityQueue)
    snapshot_lock: threading.Lock = field(default_factory=threading.Lock)
    command_sequence: int = 0
    active_command_kind: str = ""
    active_command_started_at: float = 0.0
    last_command_activity_at: float = 0.0
    last_frame_activity_at: float = 0.0
    active: bool = False
    error: str | None = None
    stop_reason: str | None = None
    intentional_stop: bool = False
    last_stop_kind: str | None = None
    last_stop_reason: str | None = None
    last_failure_kind: str | None = None
    last_reconnect_reason: str | None = None
    reconnect_scheduled_at: int = 0
    reconnect_delay_secs: float = 0.0
    next_reconnect_at: int = 0
    reconnect_attempts: int = 0
    last_connected_at: int = 0
    last_failure_at: int = 0
    device: dict | None = None
    self_info: dict | None = None
    collections_ready: bool = False
    contacts: list[dict] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)
    radio_stats: dict | None = None
    self_telemetry: dict | None = None
    battery_info: dict | None = None
    repeater_tracker: RepeaterRuntimeTracker = field(default_factory=RepeaterRuntimeTracker)
    last_contact_auto_sync_at: float = 0.0
    queue_drain_in_progress: bool = False
    queue_drain_requested: bool = False
    queue_last_reason: str = ""
    queue_last_started_at: int = 0
    queue_last_finished_at: int = 0
    queue_last_empty_at: int = 0
    queue_last_drain_message_count: int = 0
    queue_last_drain_cycles: int = 0
    queue_last_sync_attempts: int = 0
    queue_last_empty_via_timeout: bool = False
    queue_last_hit_batch_limit: bool = False
    queue_last_overflow_risk: bool = False
    last_interactive_command_at: float = 0.0


@dataclass
class RouteTraceJob:
    job_id: str
    port: str
    conn_kwargs: dict
    selected_public_keys: list[str]
    route_path_hash_len: int
    sequential: bool
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.monotonic)
    status: str = "queued"
    cancel_reason: str = ""
    result: dict | None = None
    thread: threading.Thread | None = None


def configure_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    if os.path.isfile(LEGACY_LOG_PATH) and not os.path.isfile(LOG_PATH):
        os.replace(LEGACY_LOG_PATH, LOG_PATH)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            console_handler,
            logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        ],
        force=True,
    )


def _log_delivery_debug(event: str, **fields) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": str(event),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with DELIVERY_DEBUG_LOCK:
        with open(DELIVERY_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _ack_hexes_match(expected_ack_hex: str | None, received_ack_hex: str | None) -> bool:
    expected = str(expected_ack_hex or "").strip().lower()
    received = str(received_ack_hex or "").strip().lower()
    if not expected or not received:
        return False
    try:
        return ack_codes_match(bytes.fromhex(expected), bytes.fromhex(received))
    except ValueError:
        return False


def _log_read_debug(event: str, **fields) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": str(event),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with READ_DEBUG_LOCK:
        with open(READ_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _log_contact_debug(event: str, **fields) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": str(event),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with CONTACT_DEBUG_LOCK:
        with open(CONTACT_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _log_route_trace_debug(event: str, **fields) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": str(event),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with ROUTE_TRACE_DEBUG_LOCK:
        with open(ROUTE_TRACE_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _log_frontend_diagnostic(kind: str, **fields) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "kind": str(kind),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with FRONTEND_DIAGNOSTIC_LOCK:
        with open(FRONTEND_DIAGNOSTIC_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _read_json_log_tail(path: str, limit: int = 50) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-safe_limit:]
    except OSError:
        return []
    items: list[dict] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def init_message_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        if _sqlite_table_exists(conn, "messages") and "owner_id" not in _sqlite_table_columns(conn, "messages"):
            _rebuild_messages_table_with_owner_scope(conn)
        if _sqlite_table_exists(conn, "messages") and "channel_identity" not in _sqlite_table_columns(conn, "messages"):
            _rebuild_messages_table_with_channel_identity(conn)
        if _sqlite_table_exists(conn, "contact_messages") and "owner_id" not in _sqlite_table_columns(conn, "contact_messages"):
            _rebuild_contact_messages_table_with_owner_scope(conn)
        if _sqlite_table_exists(conn, "signal_metrics") and "owner_id" not in _sqlite_table_columns(conn, "signal_metrics"):
            _rebuild_signal_metrics_table_with_owner_scope(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                message_kind TEXT NOT NULL,
                channel_idx INTEGER,
                channel_identity TEXT NOT NULL DEFAULT '',
                from_self INTEGER NOT NULL DEFAULT 0,
                send_status TEXT,
                expected_ack_hex TEXT,
                acked_at INTEGER,
                sender_timestamp INTEGER,
                received_at INTEGER NOT NULL,
                snr REAL,
                path_len INTEGER,
                path_hashes TEXT,
                txt_type INTEGER,
                text TEXT NOT NULL,
                payload_hex TEXT NOT NULL,
                UNIQUE(owner_id, message_kind, channel_identity, channel_idx, sender_timestamp, text)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_channel
            ON messages(owner_id, message_kind, channel_identity, channel_idx, sender_timestamp, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                pubkey_prefix TEXT NOT NULL,
                from_self INTEGER NOT NULL DEFAULT 0,
                send_status TEXT,
                expected_ack_hex TEXT,
                acked_at INTEGER,
                sender_timestamp INTEGER,
                received_at INTEGER NOT NULL,
                snr REAL,
                path_len INTEGER,
                path_hashes TEXT,
                txt_type INTEGER,
                text TEXT NOT NULL,
                payload_hex TEXT NOT NULL,
                signature_hex TEXT,
                UNIQUE(owner_id, pubkey_prefix, sender_timestamp, text)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contact_messages_prefix
            ON contact_messages(owner_id, pubkey_prefix, sender_timestamp, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                recorded_at INTEGER NOT NULL,
                snr REAL,
                noise_floor REAL,
                repeaters REAL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_signal_metrics_recorded_at
            ON signal_metrics(owner_id, recorded_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS node_channel_slots (
                owner_id TEXT NOT NULL,
                channel_idx INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                channel_secret_hex TEXT NOT NULL DEFAULT '',
                channel_hash TEXT NOT NULL DEFAULT '',
                channel_identity TEXT NOT NULL,
                is_public INTEGER NOT NULL DEFAULT 0,
                last_seen_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (owner_id, channel_idx)
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_node_channel_slots_identity
            ON node_channel_slots(owner_id, channel_identity)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_node_channel_slots_seen
            ON node_channel_slots(owner_id, last_seen_at)
            """
        )
        _ensure_column(conn, "messages", "from_self", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "messages", "channel_identity", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "signal_metrics", "repeaters", "REAL")
        _ensure_column(conn, "contact_messages", "from_self", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "messages", "send_status", "TEXT")
        _ensure_column(conn, "messages", "expected_ack_hex", "TEXT")
        _ensure_column(conn, "messages", "acked_at", "INTEGER")
        _ensure_column(conn, "messages", "is_read", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "messages", "is_mention_read", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "messages", "path_hashes", "TEXT")
        _ensure_column(conn, "contact_messages", "send_status", "TEXT")
        _ensure_column(conn, "contact_messages", "expected_ack_hex", "TEXT")
        _ensure_column(conn, "contact_messages", "acked_at", "INTEGER")
        _ensure_column(conn, "contact_messages", "is_read", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "contact_messages", "is_mention_read", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "contact_messages", "path_hashes", "TEXT")
        conn.execute("UPDATE messages SET is_read = 1 WHERE from_self = 1 AND COALESCE(is_read, 0) = 0")
        conn.execute("UPDATE contact_messages SET is_read = 1 WHERE from_self = 1 AND COALESCE(is_read, 0) = 0")
        conn.execute("UPDATE messages SET is_mention_read = 1 WHERE from_self = 1 AND COALESCE(is_mention_read, 0) = 0")
        conn.execute("UPDATE contact_messages SET is_mention_read = 1 WHERE from_self = 1 AND COALESCE(is_mention_read, 0) = 0")
        if _sqlite_table_exists(conn, "mention_read_messages"):
            conn.execute(
                """
                UPDATE messages
                SET is_mention_read = 1
                WHERE id IN (
                    SELECT message_id
                    FROM mention_read_messages
                    WHERE message_table = 'channel'
                )
                """
            )
            conn.execute(
                """
                UPDATE contact_messages
                SET is_mention_read = 1
                WHERE id IN (
                    SELECT message_id
                    FROM mention_read_messages
                    WHERE message_table = 'contact'
                )
                """
            )
            conn.execute("DROP TABLE mention_read_messages")
        if _sqlite_table_exists(conn, "read_markers"):
            conn.execute("DROP TABLE read_markers")
        _prune_signal_metrics_locked(
            conn,
            _normalize_signal_metrics_retention_days(_get_client_settings().get("signal_metrics_retention_days")),
        )
        conn.commit()


def _init_contact_db_schema(conn: sqlite3.Connection) -> None:
    contact_store.init_contact_store_schema(conn)
    init_mobile_push_db_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_groups (
            name TEXT PRIMARY KEY
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_group_tags (
            group_name TEXT NOT NULL,
            public_key TEXT NOT NULL,
            PRIMARY KEY (group_name, public_key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contact_group_tags_group
        ON contact_group_tags(group_name)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contact_group_tags_public_key
        ON contact_group_tags(public_key)
        """
    )
    conn.execute(
        "DELETE FROM contact_group_tags WHERE lower(group_name) = ?",
        (SYSTEM_FAVORITES_GROUP,),
    )
    conn.execute(
        "DELETE FROM contact_groups WHERE lower(name) = ?",
        (SYSTEM_FAVORITES_GROUP,),
    )


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        LIMIT 1
        """,
        (str(table_name or "").strip(),),
    ).fetchone()
    return row is not None


def _sqlite_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if str(row[1] or "").strip()
    ]


def _rebuild_messages_table_with_channel_identity(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS messages_v3_identity")
    conn.execute(
        """
        CREATE TABLE messages_v3_identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL DEFAULT '',
            message_kind TEXT NOT NULL,
            channel_idx INTEGER,
            channel_identity TEXT NOT NULL DEFAULT '',
            from_self INTEGER NOT NULL DEFAULT 0,
            send_status TEXT,
            expected_ack_hex TEXT,
            acked_at INTEGER,
            sender_timestamp INTEGER,
            received_at INTEGER NOT NULL,
            snr REAL,
            path_len INTEGER,
            path_hashes TEXT,
            txt_type INTEGER,
            text TEXT NOT NULL,
            payload_hex TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_mention_read INTEGER NOT NULL DEFAULT 0,
            UNIQUE(owner_id, message_kind, channel_identity, channel_idx, sender_timestamp, text)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO messages_v3_identity (
            id,
            owner_id,
            message_kind,
            channel_idx,
            channel_identity,
            from_self,
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            is_read,
            is_mention_read
        )
        SELECT
            id,
            owner_id,
            message_kind,
            channel_idx,
            '',
            COALESCE(from_self, 0),
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            COALESCE(is_read, 0),
            COALESCE(is_mention_read, 0)
        FROM messages
        """
    )
    conn.execute("DROP TABLE messages")
    conn.execute("ALTER TABLE messages_v3_identity RENAME TO messages")


def _rebuild_messages_table_with_owner_scope(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS messages_v2_owner")
    conn.execute(
        """
        CREATE TABLE messages_v2_owner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL DEFAULT '',
            message_kind TEXT NOT NULL,
            channel_idx INTEGER,
            from_self INTEGER NOT NULL DEFAULT 0,
            send_status TEXT,
            expected_ack_hex TEXT,
            acked_at INTEGER,
            sender_timestamp INTEGER,
            received_at INTEGER NOT NULL,
            snr REAL,
            path_len INTEGER,
            path_hashes TEXT,
            txt_type INTEGER,
            text TEXT NOT NULL,
            payload_hex TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_mention_read INTEGER NOT NULL DEFAULT 0,
            UNIQUE(owner_id, message_kind, channel_idx, sender_timestamp, text)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO messages_v2_owner (
            id,
            owner_id,
            message_kind,
            channel_idx,
            from_self,
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            is_read,
            is_mention_read
        )
        SELECT
            id,
            '',
            message_kind,
            channel_idx,
            COALESCE(from_self, 0),
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            COALESCE(is_read, 0),
            COALESCE(is_mention_read, 0)
        FROM messages
        """
    )
    conn.execute("DROP TABLE messages")
    conn.execute("ALTER TABLE messages_v2_owner RENAME TO messages")


def _rebuild_contact_messages_table_with_owner_scope(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS contact_messages_v2_owner")
    conn.execute(
        """
        CREATE TABLE contact_messages_v2_owner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL DEFAULT '',
            pubkey_prefix TEXT NOT NULL,
            from_self INTEGER NOT NULL DEFAULT 0,
            send_status TEXT,
            expected_ack_hex TEXT,
            acked_at INTEGER,
            sender_timestamp INTEGER,
            received_at INTEGER NOT NULL,
            snr REAL,
            path_len INTEGER,
            path_hashes TEXT,
            txt_type INTEGER,
            text TEXT NOT NULL,
            payload_hex TEXT NOT NULL,
            signature_hex TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            is_mention_read INTEGER NOT NULL DEFAULT 0,
            UNIQUE(owner_id, pubkey_prefix, sender_timestamp, text)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO contact_messages_v2_owner (
            id,
            owner_id,
            pubkey_prefix,
            from_self,
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            signature_hex,
            is_read,
            is_mention_read
        )
        SELECT
            id,
            '',
            pubkey_prefix,
            COALESCE(from_self, 0),
            send_status,
            expected_ack_hex,
            acked_at,
            sender_timestamp,
            received_at,
            snr,
            path_len,
            path_hashes,
            txt_type,
            text,
            payload_hex,
            signature_hex,
            COALESCE(is_read, 0),
            COALESCE(is_mention_read, 0)
        FROM contact_messages
        """
    )
    conn.execute("DROP TABLE contact_messages")
    conn.execute("ALTER TABLE contact_messages_v2_owner RENAME TO contact_messages")


def _rebuild_signal_metrics_table_with_owner_scope(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS signal_metrics_v2_owner")
    conn.execute(
        """
        CREATE TABLE signal_metrics_v2_owner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT NOT NULL DEFAULT '',
            recorded_at INTEGER NOT NULL,
            snr REAL,
            noise_floor REAL,
            repeaters REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO signal_metrics_v2_owner (
            id,
            owner_id,
            recorded_at,
            snr,
            noise_floor,
            repeaters
        )
        SELECT
            id,
            '',
            recorded_at,
            snr,
            noise_floor,
            repeaters
        FROM signal_metrics
        """
    )
    conn.execute("DROP TABLE signal_metrics")
    conn.execute("ALTER TABLE signal_metrics_v2_owner RENAME TO signal_metrics")


def _sqlite_table_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _sqlite_table_exists(conn, table_name):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0] or 0) if row else 0


def _copy_sqlite_table_if_target_empty(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    table_name: str,
) -> int:
    if not _sqlite_table_exists(source_conn, table_name) or not _sqlite_table_exists(target_conn, table_name):
        return 0
    if _sqlite_table_row_count(target_conn, table_name) > 0:
        return 0
    source_columns = _sqlite_table_columns(source_conn, table_name)
    target_columns = _sqlite_table_columns(target_conn, table_name)
    common_columns = [column for column in target_columns if column in source_columns]
    if not common_columns:
        return 0
    select_sql = f"SELECT {', '.join(common_columns)} FROM {table_name}"
    rows = source_conn.execute(select_sql).fetchall()
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in common_columns)
    insert_sql = (
        f"INSERT OR REPLACE INTO {table_name} "
        f"({', '.join(common_columns)}) VALUES ({placeholders})"
    )
    target_conn.executemany(insert_sql, rows)
    return len(rows)


def _migrate_contact_store_meta_last_sync(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection) -> int:
    if not _sqlite_table_exists(source_conn, "contact_store_meta") or not _sqlite_table_exists(target_conn, "contact_store_meta"):
        return 0
    source_row = source_conn.execute(
        """
        SELECT last_sync_at
        FROM contact_store_meta
        WHERE singleton_id = 1
        LIMIT 1
        """
    ).fetchone()
    if source_row is None:
        return 0
    source_last_sync_at = int(source_row[0] or 0)
    target_row = target_conn.execute(
        """
        SELECT last_sync_at
        FROM contact_store_meta
        WHERE singleton_id = 1
        LIMIT 1
        """
    ).fetchone()
    target_last_sync_at = int(target_row[0] or 0) if target_row is not None else 0
    if source_last_sync_at <= target_last_sync_at:
        return 0
    target_conn.execute(
        "UPDATE contact_store_meta SET last_sync_at = ? WHERE singleton_id = 1",
        (source_last_sync_at,),
    )
    return 1


def _migrate_legacy_contact_db_if_needed() -> None:
    if not os.path.isfile(LEGACY_DB_PATH):
        return
    with sqlite3.connect(LEGACY_DB_PATH) as source_conn, sqlite3.connect(CONTACTS_DB_PATH) as target_conn:
        source_conn.row_factory = sqlite3.Row
        target_conn.row_factory = sqlite3.Row
        _init_contact_db_schema(target_conn)
        migrated = {
            "contact_store_meta": _migrate_contact_store_meta_last_sync(source_conn, target_conn),
            "contacts_cache": _copy_sqlite_table_if_target_empty(source_conn, target_conn, "contacts_cache"),
            "contact_groups": _copy_sqlite_table_if_target_empty(source_conn, target_conn, "contact_groups"),
            "contact_group_tags": _copy_sqlite_table_if_target_empty(source_conn, target_conn, "contact_group_tags"),
        }
        target_conn.execute(
            "DELETE FROM contact_group_tags WHERE lower(group_name) = ?",
            (SYSTEM_FAVORITES_GROUP,),
        )
        target_conn.execute(
            "DELETE FROM contact_groups WHERE lower(name) = ?",
            (SYSTEM_FAVORITES_GROUP,),
        )
        target_conn.commit()
    if any(migrated.values()):
        logging.info(
            "migrated legacy contact data from %s to %s meta=%s cache=%s groups=%s tags=%s",
            LEGACY_DB_PATH,
            CONTACTS_DB_PATH,
            migrated["contact_store_meta"],
            migrated["contacts_cache"],
            migrated["contact_groups"],
            migrated["contact_group_tags"],
        )


def _migrate_named_db_files_if_needed() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(LEGACY_DB_PATH) and not os.path.isfile(DB_PATH):
        os.replace(LEGACY_DB_PATH, DB_PATH)
    if os.path.isfile(LEGACY_CONTACTS_DB_PATH) and not os.path.isfile(CONTACTS_DB_PATH):
        os.replace(LEGACY_CONTACTS_DB_PATH, CONTACTS_DB_PATH)


def init_contact_db() -> None:
    _migrate_named_db_files_if_needed()
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(CONTACTS_DB_PATH) as conn:
        _init_contact_db_schema(conn)
        conn.commit()
    _migrate_legacy_contact_db_if_needed()


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, spec: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {spec}")


def _prune_signal_metrics_locked(conn: sqlite3.Connection, retention_days: int) -> None:
    cutoff = utc_now_epoch() - (_normalize_signal_metrics_retention_days(retention_days) * 86400)
    conn.execute("DELETE FROM signal_metrics WHERE recorded_at < ?", (cutoff,))


def _prune_signal_metrics(retention_days: int) -> None:
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        _prune_signal_metrics_locked(conn, retention_days)
        conn.commit()


def _normalize_repeater_tracker_public_key(value: object) -> str:
    public_key = str(value or "").strip().lower()
    if len(public_key) != 64:
        return ""
    try:
        bytes.fromhex(public_key)
    except ValueError:
        return ""
    return public_key


def _normalize_repeater_tracker_token(value: object) -> str:
    token = str(value or "").strip().lower()
    if not token or len(token) % 2 != 0:
        return ""
    try:
        bytes.fromhex(token)
    except ValueError:
        return ""
    return token


def _extract_last_repeater_path_token(path_hashes: object) -> str:
    raw = str(path_hashes or "").strip()
    if not raw:
        return ""
    last_token = ""
    for part in raw.split("->"):
        token = _normalize_repeater_tracker_token(part)
        if token:
            last_token = token
    return last_token


def _is_repeater_adv_type(value: object) -> bool:
    try:
        return int(value or 0) == 2
    except (TypeError, ValueError):
        return False


def _collect_known_repeater_public_keys_locked(session: BackgroundCompanionSession) -> set[str]:
    known = {
        public_key
        for public_key in (session.repeater_tracker.full_keys or {}).keys()
        if len(public_key) == 64
    }
    for contact in list(session.contacts or []):
        if not _is_repeater_adv_type((contact or {}).get("adv_type")):
            continue
        public_key = _normalize_repeater_tracker_public_key((contact or {}).get("public_key"))
        if public_key:
            known.add(public_key)
    return known


def _merge_provisional_token_locked(session: BackgroundCompanionSession, token: str, timestamp: int) -> None:
    normalized = _normalize_repeater_tracker_token(token)
    if not normalized:
        return
    tracker = session.repeater_tracker
    known_public_keys = _collect_known_repeater_public_keys_locked(session)
    full_matches = [public_key for public_key in known_public_keys if public_key.startswith(normalized)]
    if len(full_matches) == 1:
        resolved_public_key = full_matches[0]
        tracker.full_keys[resolved_public_key] = max(
            int(tracker.full_keys.get(resolved_public_key) or 0),
            int(timestamp),
        )
        return
    merged_timestamp = int(timestamp)
    canonical = normalized
    for existing_token, existing_seen in list((tracker.provisional_tokens or {}).items()):
        if (
            existing_token == normalized
            or existing_token.startswith(normalized)
            or normalized.startswith(existing_token)
        ):
            merged_timestamp = max(merged_timestamp, int(existing_seen or 0))
            if len(existing_token) > len(canonical):
                canonical = existing_token
            tracker.provisional_tokens.pop(existing_token, None)
    tracker.provisional_tokens[canonical] = merged_timestamp


def _merge_full_repeater_identity_locked(
    session: BackgroundCompanionSession,
    public_key: str,
    timestamp: int,
) -> None:
    normalized_public_key = _normalize_repeater_tracker_public_key(public_key)
    if not normalized_public_key:
        return
    tracker = session.repeater_tracker
    merged_timestamp = max(
        int(timestamp),
        int((tracker.full_keys or {}).get(normalized_public_key) or 0),
    )
    for token, token_seen in list((tracker.provisional_tokens or {}).items()):
        if normalized_public_key.startswith(str(token or "")):
            merged_timestamp = max(merged_timestamp, int(token_seen or 0))
            tracker.provisional_tokens.pop(token, None)
    tracker.full_keys[normalized_public_key] = merged_timestamp


def _prune_repeater_tracker_locked(
    session: BackgroundCompanionSession,
    now_epoch: int | None = None,
) -> None:
    now = int(now_epoch or utc_now_epoch())
    cutoff = now - 120
    tracker = session.repeater_tracker
    tracker.full_keys = {
        public_key: int(last_seen)
        for public_key, last_seen in (tracker.full_keys or {}).items()
        if int(last_seen) >= cutoff
    }
    tracker.provisional_tokens = {
        token: int(last_seen)
        for token, last_seen in (tracker.provisional_tokens or {}).items()
        if int(last_seen) >= cutoff
    }
    known_public_keys = _collect_known_repeater_public_keys_locked(session)
    for public_key in known_public_keys:
        if len(public_key) == 64:
            _merge_full_repeater_identity_locked(
                session,
                public_key,
                int((tracker.full_keys or {}).get(public_key) or cutoff),
            )


def _bootstrap_repeater_tracker_from_contacts_locked(
    session: BackgroundCompanionSession,
    contacts: list[dict] | None,
    now_epoch: int | None = None,
) -> None:
    now = int(now_epoch or utc_now_epoch())
    for contact in list(contacts or []):
        public_key = _normalize_repeater_tracker_public_key((contact or {}).get("public_key"))
        if not public_key or not _is_repeater_adv_type((contact or {}).get("adv_type")):
            continue
        try:
            path_len = int((contact or {}).get("out_path_len") or 0)
        except (TypeError, ValueError):
            path_len = 0
        try:
            last_advert = int((contact or {}).get("last_advert") or 0)
        except (TypeError, ValueError):
            last_advert = 0
        if path_len == 0 and last_advert > 0 and (now - last_advert) <= 120:
            _merge_full_repeater_identity_locked(session, public_key, last_advert)
    _prune_repeater_tracker_locked(session, now_epoch=now)


def _touch_repeater_activity(
    session: BackgroundCompanionSession,
    public_key: str | None = None,
    pubkey_prefix: str | None = None,
    path_hashes: str | None = None,
    observed_at: int | None = None,
) -> None:
    timestamp = int(observed_at or utc_now_epoch())
    with session.snapshot_lock:
        normalized_public_key = _normalize_repeater_tracker_public_key(public_key)
        if normalized_public_key:
            _merge_full_repeater_identity_locked(session, normalized_public_key, timestamp)
        else:
            prefix = _normalize_repeater_tracker_token(str(pubkey_prefix or "").strip().lower()[:12])
            if prefix:
                _merge_provisional_token_locked(session, prefix, timestamp)
        last_path_token = _extract_last_repeater_path_token(path_hashes)
        if last_path_token:
            _merge_provisional_token_locked(session, last_path_token, timestamp)
        _prune_repeater_tracker_locked(session, now_epoch=timestamp)


def _get_recent_repeater_count(session: BackgroundCompanionSession, now_epoch: int | None = None) -> int:
    with session.snapshot_lock:
        _prune_repeater_tracker_locked(session, now_epoch=now_epoch)
        return len(session.repeater_tracker.full_keys) + len(session.repeater_tracker.provisional_tokens)


def _record_signal_metrics_sample(
    radio_stats: dict | None,
    recorded_at: int | None = None,
    *,
    repeaters: int | float | None = None,
    owner_id: str | None = None,
) -> None:
    if not isinstance(radio_stats, dict) and repeaters is None:
        return
    normalized_owner_id, _ = _resolve_owner_scope(owner_id, False)
    if not normalized_owner_id:
        return
    snr = radio_stats.get("last_snr") if isinstance(radio_stats, dict) else None
    noise_floor = radio_stats.get("noise_floor") if isinstance(radio_stats, dict) else None
    if snr is None and noise_floor is None and repeaters is None:
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO signal_metrics (owner_id, recorded_at, snr, noise_floor, repeaters)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_owner_id,
                int(recorded_at or utc_now_epoch()),
                None if snr is None else float(snr),
                None if noise_floor is None else float(noise_floor),
                None if repeaters is None else float(repeaters),
            ),
        )
        _prune_signal_metrics_locked(
            conn,
            _normalize_signal_metrics_retention_days(_get_client_settings().get("signal_metrics_retention_days")),
        )
        conn.commit()


def get_signal_metrics_chart(
    range_seconds: int | None = None,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict:
    settings = _get_client_settings()
    retention_days = _normalize_signal_metrics_retention_days(settings.get("signal_metrics_retention_days"))
    retention_seconds = retention_days * 86400
    try:
        requested_seconds = retention_seconds if range_seconds is None else int(range_seconds)
    except (TypeError, ValueError):
        requested_seconds = retention_seconds
    selected_range_seconds = max(60, min(retention_seconds, requested_seconds))
    if selected_range_seconds <= 300:
        bucket_secs = 5
    elif selected_range_seconds <= 600:
        bucket_secs = 10
    elif selected_range_seconds <= 1800:
        bucket_secs = 30
    elif selected_range_seconds <= 3600:
        bucket_secs = 60
    elif selected_range_seconds <= 10800:
        bucket_secs = 300
    elif selected_range_seconds <= 21600:
        bucket_secs = 600
    elif selected_range_seconds <= 43200:
        bucket_secs = 900
    elif selected_range_seconds <= 86400:
        bucket_secs = 1800
    elif selected_range_seconds <= 604800:
        bucket_secs = 21600
    else:
        bucket_secs = 86400
    cutoff = utc_now_epoch() - selected_range_seconds
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT recorded_at, snr, noise_floor, repeaters
            FROM signal_metrics
            WHERE {owner_where} AND recorded_at >= ? AND (snr IS NOT NULL OR noise_floor IS NOT NULL OR repeaters IS NOT NULL)
            ORDER BY recorded_at ASC
            """,
            owner_params + (cutoff,),
        ).fetchall()
    buckets: dict[int, dict] = {}
    for row in rows:
        recorded_at = int(row["recorded_at"] or 0)
        bucket_at = (recorded_at // bucket_secs) * bucket_secs
        bucket = buckets.setdefault(
            bucket_at,
            {
                "snr_sum": 0.0,
                "snr_count": 0,
                "snr_min": None,
                "snr_max": None,
                "noise_sum": 0.0,
                "noise_count": 0,
                "noise_min": None,
                "noise_max": None,
                "repeaters_sum": 0.0,
                "repeaters_count": 0,
                "repeaters_min": None,
                "repeaters_max": None,
            },
        )
        if row["snr"] is not None:
            snr_value = float(row["snr"])
            bucket["snr_sum"] += snr_value
            bucket["snr_count"] += 1
            bucket["snr_min"] = snr_value if bucket["snr_min"] is None else min(float(bucket["snr_min"]), snr_value)
            bucket["snr_max"] = snr_value if bucket["snr_max"] is None else max(float(bucket["snr_max"]), snr_value)
        if row["noise_floor"] is not None:
            noise_value = float(row["noise_floor"])
            bucket["noise_sum"] += noise_value
            bucket["noise_count"] += 1
            bucket["noise_min"] = noise_value if bucket["noise_min"] is None else min(float(bucket["noise_min"]), noise_value)
            bucket["noise_max"] = noise_value if bucket["noise_max"] is None else max(float(bucket["noise_max"]), noise_value)
        if row["repeaters"] is not None:
            repeaters_value = float(row["repeaters"])
            bucket["repeaters_sum"] += repeaters_value
            bucket["repeaters_count"] += 1
            bucket["repeaters_min"] = repeaters_value if bucket["repeaters_min"] is None else min(float(bucket["repeaters_min"]), repeaters_value)
            bucket["repeaters_max"] = repeaters_value if bucket["repeaters_max"] is None else max(float(bucket["repeaters_max"]), repeaters_value)
    points = [
        {
            "ts": bucket_at,
            "snr": None if not data["snr_count"] else round(data["snr_sum"] / max(1, data["snr_count"]), 2),
            "snr_count": int(data["snr_count"]),
            "snr_min": None if data["snr_min"] is None else round(float(data["snr_min"]), 2),
            "snr_max": None if data["snr_max"] is None else round(float(data["snr_max"]), 2),
            "noise_floor": None if not data["noise_count"] else round(data["noise_sum"] / max(1, data["noise_count"]), 2),
            "noise_count": int(data["noise_count"]),
            "noise_min": None if data["noise_min"] is None else round(float(data["noise_min"]), 2),
            "noise_max": None if data["noise_max"] is None else round(float(data["noise_max"]), 2),
            "repeaters": None if not data["repeaters_count"] else round(data["repeaters_sum"] / max(1, data["repeaters_count"]), 2),
            "repeaters_count": int(data["repeaters_count"]),
            "repeaters_min": None if data["repeaters_min"] is None else round(float(data["repeaters_min"]), 2),
            "repeaters_max": None if data["repeaters_max"] is None else round(float(data["repeaters_max"]), 2),
        }
        for bucket_at, data in sorted(buckets.items())
    ]
    snr_values = [float(point["snr"]) for point in points if point["snr"] is not None]
    noise_values = [float(point["noise_floor"]) for point in points if point["noise_floor"] is not None]
    repeater_values = [float(point["repeaters"]) for point in points if point["repeaters"] is not None]
    return {
        "range_seconds": selected_range_seconds,
        "retention_days": retention_days,
        "poll_seconds": _normalize_signal_metrics_poll_seconds(settings.get("signal_metrics_poll_seconds")),
        "bucket_secs": bucket_secs,
        "points": points,
        "snr_latest_value": None if not snr_values else points[[index for index, point in enumerate(points) if point["snr"] is not None][-1]]["snr"],
        "snr_min_value": None if not snr_values else round(min(snr_values), 2),
        "snr_max_value": None if not snr_values else round(max(snr_values), 2),
        "snr_avg_value": None if not snr_values else round(sum(snr_values) / len(snr_values), 2),
        "noise_latest_value": None if not noise_values else points[[index for index, point in enumerate(points) if point["noise_floor"] is not None][-1]]["noise_floor"],
        "noise_min_value": None if not noise_values else round(min(noise_values), 2),
        "noise_max_value": None if not noise_values else round(max(noise_values), 2),
        "noise_avg_value": None if not noise_values else round(sum(noise_values) / len(noise_values), 2),
        "repeaters_latest_value": None if not repeater_values else points[[index for index, point in enumerate(points) if point["repeaters"] is not None][-1]]["repeaters"],
        "repeaters_min_value": None if not repeater_values else round(min(repeater_values), 2),
        "repeaters_max_value": None if not repeater_values else round(max(repeater_values), 2),
        "repeaters_avg_value": None if not repeater_values else round(sum(repeater_values) / len(repeater_values), 2),
    }


def _get_connection_lock(descriptor: ConnectionDescriptor) -> threading.Lock:
    with CONNECTION_RUNTIME_GUARD:
        lock = CONNECTION_LOCKS.get(descriptor.lock_key)
        if lock is None:
            lock = threading.Lock()
            CONNECTION_LOCKS[descriptor.lock_key] = lock
        return lock


@contextmanager
def _connection_access(descriptor: ConnectionDescriptor):
    lock = _get_connection_lock(descriptor)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _connection_descriptor_from_kwargs(kwargs: dict) -> ConnectionDescriptor:
    return DEFAULT_CONNECTION_ROUTER.from_request(kwargs)


@contextmanager
def _connection_access_from_kwargs(session_kwargs: dict):
    with _connection_access(_connection_descriptor_from_kwargs(session_kwargs)):
        yield


def _open_meshcore_client(session_kwargs: dict) -> MeshCoreSerialClient:
    return DEFAULT_CONNECTION_ROUTER.open_client(_connection_descriptor_from_kwargs(session_kwargs))


def _router_client_factory(**kwargs) -> MeshCoreSerialClient:
    return DEFAULT_CONNECTION_ROUTER.open_client(_connection_descriptor_from_kwargs(kwargs))


def _register_listener_stop(port: str, stop_event: threading.Event) -> None:
    with CONNECTION_RUNTIME_GUARD:
        listeners = LISTENER_STOPS.setdefault(port, set())
        listeners.add(stop_event)


def _unregister_listener_stop(port: str, stop_event: threading.Event) -> None:
    with CONNECTION_RUNTIME_GUARD:
        listeners = LISTENER_STOPS.get(port)
        if not listeners:
            return
        listeners.discard(stop_event)
        if not listeners:
            LISTENER_STOPS.pop(port, None)


def _request_listener_stop(port: str) -> None:
    with CONNECTION_RUNTIME_GUARD:
        listeners = list(LISTENER_STOPS.get(port, set()))
    for stop_event in listeners:
        stop_event.set()


def _register_event_subscriber(port: str, sink: queue.Queue) -> None:
    with EVENT_SUBSCRIBERS_GUARD:
        subscribers = EVENT_SUBSCRIBERS.setdefault(port, set())
        subscribers.add(sink)


def _unregister_event_subscriber(port: str, sink: queue.Queue) -> None:
    with EVENT_SUBSCRIBERS_GUARD:
        subscribers = EVENT_SUBSCRIBERS.get(port)
        if not subscribers:
            return
        subscribers.discard(sink)
        if not subscribers:
            EVENT_SUBSCRIBERS.pop(port, None)


def _broadcast_event(port: str, payload: dict) -> None:
    with EVENT_SUBSCRIBERS_GUARD:
        subscribers = list(EVENT_SUBSCRIBERS.get(port, set()))
    for sink in subscribers:
        try:
            sink.put_nowait(payload)
        except queue.Full:
            try:
                sink.get_nowait()
            except queue.Empty:
                pass
            try:
                sink.put_nowait(payload)
            except queue.Full:
                continue


def _broadcast_global_event(payload: dict) -> None:
    with EVENT_SUBSCRIBERS_GUARD:
        subscribers = {
            sink
            for sinks in EVENT_SUBSCRIBERS.values()
            for sink in sinks
        }
    for sink in subscribers:
        try:
            sink.put_nowait(payload)
        except queue.Full:
            try:
                sink.get_nowait()
            except queue.Empty:
                pass
            try:
                sink.put_nowait(payload)
            except queue.Full:
                continue


def _clone_route_trace_payload(value: dict | None) -> dict | None:
    if value is None:
        return None
    return json.loads(json.dumps(value))


def _register_route_trace_job(job: RouteTraceJob) -> None:
    with ROUTE_TRACE_JOBS_GUARD:
        ROUTE_TRACE_JOBS[job.job_id] = job


def _get_route_trace_job(job_id: str) -> RouteTraceJob | None:
    with ROUTE_TRACE_JOBS_GUARD:
        return ROUTE_TRACE_JOBS.get(str(job_id or ""))


def _discard_route_trace_job(job_id: str, *, expected: RouteTraceJob | None = None) -> None:
    normalized_job_id = str(job_id or "")
    if not normalized_job_id:
        return
    with ROUTE_TRACE_JOBS_GUARD:
        current = ROUTE_TRACE_JOBS.get(normalized_job_id)
        if current is None:
            return
        if expected is not None and current is not expected:
            return
        ROUTE_TRACE_JOBS.pop(normalized_job_id, None)


def _request_route_trace_job_cancel(job: RouteTraceJob | None, reason: str = "") -> bool:
    if job is None:
        return False
    normalized_reason = str(reason or "").strip()
    if normalized_reason and not job.cancel_reason:
        job.cancel_reason = normalized_reason
    job.cancel_event.set()
    return True


def _cancel_route_trace_jobs_for_port(port: str, *, reason: str, except_job_id: str | None = None) -> None:
    normalized_port = str(port or "")
    normalized_except = str(except_job_id or "")
    with ROUTE_TRACE_JOBS_GUARD:
        jobs = [
            job
            for job in ROUTE_TRACE_JOBS.values()
            if job.port == normalized_port and job.job_id != normalized_except
        ]
    for job in jobs:
        _request_route_trace_job_cancel(job, reason)


def _broadcast_route_trace_event(
    job: RouteTraceJob,
    status: str,
    *,
    trace: dict | None = None,
    message: str = "",
    reason: str = "",
) -> None:
    payload = {
        "event": "contact-route-trace",
        "job_id": str(job.job_id),
        "status": str(status or ""),
        "trace": _clone_route_trace_payload(trace),
        "message": str(message or ""),
        "reason": str(reason or job.cancel_reason or ""),
    }
    _broadcast_event(job.port, payload)


def _build_session_snapshot(
    session: BackgroundCompanionSession,
    *,
    include_contacts: bool = True,
    include_channels: bool = True,
) -> dict:
    contacts_snapshot: list[dict] | None = None
    with session.snapshot_lock:
        now_epoch = utc_now_epoch()
        live_contacts = list(session.contacts or [])
        channels = list(session.channels) if include_channels else []
        collections_ready = bool(session.collections_ready)
        session_self_info = dict(session.self_info or {}) if session.self_info else None
        effective_self_info = _apply_self_location_override(session_self_info)
        _prune_repeater_tracker_locked(session, now_epoch=now_epoch)
        recent_repeaters_count = len(session.repeater_tracker.full_keys) + len(session.repeater_tracker.provisional_tokens)
        snapshot = {
            "connection": _redact_connection_payload(session.config.get("connection")),
            "active": bool(session.active),
            "error": session.error,
            "stop_state": {
                "port": str(session.config["port"]),
                "connection": _redact_connection_payload(session.config.get("connection")),
                "intentional": bool(session.intentional_stop),
                "stop_reason": str(session.stop_reason or ""),
                "last_stop_kind": str(session.last_stop_kind or ""),
                "last_stop_reason": str(session.last_stop_reason or ""),
                "last_failure_kind": str(session.last_failure_kind or ""),
                "last_reconnect_reason": str(session.last_reconnect_reason or ""),
                "reconnect_scheduled_at": int(session.reconnect_scheduled_at or 0),
                "reconnect_delay_secs": float(session.reconnect_delay_secs or 0.0),
                "next_reconnect_at": int(session.next_reconnect_at or 0),
                "reconnect_attempts": int(session.reconnect_attempts or 0),
                "last_connected_at": int(session.last_connected_at or 0),
                "last_failure_at": int(session.last_failure_at or 0),
            },
            "device": session.device,
            "self": effective_self_info,
            "collections_ready": collections_ready,
            "contacts_count": len(live_contacts) if collections_ready else None,
            "channels_count": len(session.channels) if collections_ready else None,
            "recent_repeaters_count": recent_repeaters_count,
            "radio_stats": session.radio_stats,
            "self_telemetry": session.self_telemetry,
            "battery_info": session.battery_info,
            "queue_state": {
                "drain_in_progress": bool(session.queue_drain_in_progress),
                "drain_requested": bool(session.queue_drain_requested),
                "last_reason": str(session.queue_last_reason or ""),
                "last_started_at": int(session.queue_last_started_at or 0),
                "last_finished_at": int(session.queue_last_finished_at or 0),
                "last_empty_at": int(session.queue_last_empty_at or 0),
                "last_drain_message_count": int(session.queue_last_drain_message_count or 0),
                "last_drain_cycles": int(session.queue_last_drain_cycles or 0),
                "last_sync_attempts": int(session.queue_last_sync_attempts or 0),
                "last_empty_via_timeout": bool(session.queue_last_empty_via_timeout),
                "last_hit_batch_limit": bool(session.queue_last_hit_batch_limit),
                "last_overflow_risk": bool(session.queue_last_overflow_risk),
            },
            "port": str(session.config["port"]),
            "baudrate": int(session.config["baudrate"]),
            "timeout": float(session.config["timeout"]),
            "transport_type": str(session.config.get("transport_type") or "serial"),
            "transport_id": str(session.config.get("transport_id") or session.config["port"]),
            "protocol_version": int(session.config["protocol_version"]),
            "app_version": int(session.config["app_version"]),
            "app_name": str(session.config["app_name"]),
        }
    with _contact_owner_scope(
        port=str((snapshot.get("stop_state") or {}).get("port") or ""),
        owner_id=(session_self_info or {}).get("public_key"),
    ):
        contacts_snapshot = CONTACT_BACKEND.compose_snapshot(live_contacts) if collections_ready else []
    snapshot["contact_summary"] = _build_contact_count_summary(contacts_snapshot, snapshot.get("device"))
    if include_channels:
        snapshot["channels"] = channels
    if include_contacts:
        snapshot["contacts"] = _compact_contacts_for_client(contacts_snapshot)
    return snapshot


def _get_background_session(port: str) -> BackgroundCompanionSession | None:
    with BACKGROUND_SESSIONS_GUARD:
        return BACKGROUND_SESSIONS.get(port)


def _carry_background_session_state(source: BackgroundCompanionSession, target: BackgroundCompanionSession) -> None:
    with source.snapshot_lock, target.snapshot_lock:
        target.command_sequence = int(source.command_sequence or 0)
        target.active_command_kind = str(source.active_command_kind or "")
        target.active_command_started_at = float(source.active_command_started_at or 0.0)
        target.last_command_activity_at = float(source.last_command_activity_at or 0.0)
        target.last_frame_activity_at = float(source.last_frame_activity_at or 0.0)
        target.error = source.error
        target.stop_reason = source.stop_reason
        target.intentional_stop = source.intentional_stop
        target.last_stop_kind = source.last_stop_kind
        target.last_stop_reason = source.last_stop_reason
        target.last_failure_kind = source.last_failure_kind
        target.last_reconnect_reason = source.last_reconnect_reason
        target.reconnect_scheduled_at = source.reconnect_scheduled_at
        target.reconnect_delay_secs = float(source.reconnect_delay_secs or 0.0)
        target.next_reconnect_at = int(source.next_reconnect_at or 0)
        target.reconnect_attempts = int(source.reconnect_attempts or 0)
        target.last_connected_at = int(source.last_connected_at or 0)
        target.last_failure_at = int(source.last_failure_at or 0)
        target.device = dict(source.device or {}) if source.device else None
        target.self_info = dict(source.self_info or {}) if source.self_info else None
        target.collections_ready = bool(source.collections_ready)
        target.contacts = list(source.contacts or [])
        target.channels = list(source.channels or [])
        target.radio_stats = dict(source.radio_stats or {}) if source.radio_stats else None
        target.self_telemetry = dict(source.self_telemetry or {}) if source.self_telemetry else None
        target.battery_info = dict(source.battery_info or {}) if source.battery_info else None
        target.repeater_tracker = RepeaterRuntimeTracker(
            full_keys=dict((source.repeater_tracker.full_keys or {})),
            provisional_tokens=dict((source.repeater_tracker.provisional_tokens or {})),
        )
        target.last_contact_auto_sync_at = float(source.last_contact_auto_sync_at or 0.0)
        target.queue_drain_in_progress = bool(source.queue_drain_in_progress)
        target.queue_drain_requested = bool(source.queue_drain_requested)
        target.queue_last_reason = str(source.queue_last_reason or "")
        target.queue_last_started_at = int(source.queue_last_started_at or 0)
        target.queue_last_finished_at = int(source.queue_last_finished_at or 0)
        target.queue_last_empty_at = int(source.queue_last_empty_at or 0)
        target.queue_last_drain_message_count = int(source.queue_last_drain_message_count or 0)
        target.queue_last_drain_cycles = int(source.queue_last_drain_cycles or 0)
        target.queue_last_sync_attempts = int(source.queue_last_sync_attempts or 0)
        target.queue_last_empty_via_timeout = bool(source.queue_last_empty_via_timeout)
        target.queue_last_hit_batch_limit = bool(source.queue_last_hit_batch_limit)
        target.queue_last_overflow_risk = bool(source.queue_last_overflow_risk)


def _background_command_priority(kind: str) -> int:
    normalized = str(kind or "").strip()
    if normalized in ("send_channel_text", "send_contact_text"):
        return 0
    if normalized in ("trace_route",):
        return 1
    if normalized in ("perform_contact_action", "save_channel", "set_node_name", "sync_device_time", "send_advert", "meshcore_params_snapshot", "apply_meshcore_params"):
        return 2
    if normalized in ("refresh_contacts", "remove_contacts", "sync_favorites_group", "export_self_contact"):
        return 3
    return 4


def _background_command_is_interactive(kind: str) -> bool:
    normalized = str(kind or "").strip()
    return normalized in ("send_channel_text", "send_contact_text", "trace_route")


def _background_should_defer_queue_drain(
    session: BackgroundCompanionSession,
    now_monotonic: float,
) -> bool:
    if not session.command_queue.empty():
        return True
    with session.snapshot_lock:
        active_command_kind = str(session.active_command_kind or "")
        last_interactive_command_at = float(session.last_interactive_command_at or 0.0)
    if _background_command_is_interactive(active_command_kind):
        return True
    return (
        last_interactive_command_at > 0.0
        and (now_monotonic - last_interactive_command_at) < BACKGROUND_QUEUE_DRAIN_INTERACTIVE_IDLE_GRACE_SECS
    )


def _background_serial_has_pending_input(client: MeshCoreSerialClient) -> bool:
    try:
        return int(getattr(client.serial, "in_waiting", 0) or 0) > 0
    except (AttributeError, OSError, ValueError, SerialException):
        return False


def _background_should_defer_housekeeping(
    session: BackgroundCompanionSession,
    client: MeshCoreSerialClient,
    now_monotonic: float,
) -> bool:
    if not session.command_queue.empty():
        return True
    if client.pending_push_count() > 0 or _background_serial_has_pending_input(client):
        return True
    with session.snapshot_lock:
        active_command_kind = str(session.active_command_kind or "")
        last_command_activity_at = float(session.last_command_activity_at or 0.0)
        last_frame_activity_at = float(session.last_frame_activity_at or 0.0)
    if _background_command_is_interactive(active_command_kind):
        return True
    last_busy_at = max(last_command_activity_at, last_frame_activity_at)
    return last_busy_at > 0 and (now_monotonic - last_busy_at) < BACKGROUND_MAINTENANCE_IDLE_GRACE_SECS


def _enqueue_background_command(session: BackgroundCompanionSession, payload: dict) -> None:
    kind = str(payload.get("kind") or "")
    with session.snapshot_lock:
        sequence = int(session.command_sequence or 0)
        session.command_sequence = sequence + 1
        now_monotonic = time.monotonic()
        session.last_command_activity_at = now_monotonic
        if _background_command_is_interactive(kind):
            session.last_interactive_command_at = now_monotonic
    payload["_bg_sequence"] = int(sequence)
    payload["_bg_enqueued_at"] = float(now_monotonic)
    session.command_queue.put((_background_command_priority(kind), sequence, payload))


def _set_background_session_contacts(port: str, live_contacts: list[dict] | None) -> None:
    session = _get_background_session(port)
    if not session:
        return
    with session.snapshot_lock:
        session.contacts = list(live_contacts or [])
        _bootstrap_repeater_tracker_from_contacts_locked(session, session.contacts)
        self_info = dict(session.self_info or {}) if session.self_info else None
    _freeze_self_contact_if_cached(self_info)


def _process_background_message_event(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    port: str,
    message,
) -> None:
    with session.snapshot_lock:
        owner_id = _normalize_owner_id((session.self_info or {}).get("public_key"))
    _log_delivery_debug(
        "bg_sync_message",
        port=port,
        resp_code=message.code,
        payload_hex=message.payload.hex(),
        payload_len=len(message.payload),
    )
    if message.code == RESP_CONTACT_MSG_RECV_V3:
        try:
            details = parse_contact_message_v3(message.payload)
            _log_delivery_debug(
                "bg_contact_msg_v3",
                port=port,
                pubkey_prefix=details.pubkey_prefix,
                path_len=details.path_len,
                snr=details.snr,
                txt_type=details.txt_type,
                sender_timestamp=details.sender_timestamp,
                text=details.text,
            )
            payload = {
                "event": "message",
                "message_type": "contact",
                "code": message.code,
                "pubkey_prefix": details.pubkey_prefix,
                "path_len": details.path_len,
                "path_hashes": details.path_hashes,
                "snr": details.snr,
                "txt_type": details.txt_type,
                "sender_timestamp": details.sender_timestamp,
                "signature_hex": details.signature_hex,
                "text": details.text,
                "payload_hex": message.payload.hex(),
            }
            payload["id"] = save_contact_message(payload, owner_id=owner_id)
            _notify_mobile_push_about_contact_message(
                session,
                port=port,
                pubkey_prefix=details.pubkey_prefix,
                message_id=int(payload["id"]),
                text=details.text,
            )
            try:
                auto_favorited = _promote_direct_sender_to_favorite(
                    client,
                    session,
                    port=port,
                    pubkey_prefix=details.pubkey_prefix,
                )
            except (MeshCoreError, SerialException, ValueError, sqlite3.Error):
                logging.exception(
                    "background direct-message auto-favorite failed port=%s pubkey_prefix=%s",
                    port,
                    details.pubkey_prefix,
                )
                auto_favorited = False
            payload["auto_favorited"] = bool(auto_favorited)
            _touch_repeater_activity(
                session,
                pubkey_prefix=details.pubkey_prefix if int(details.path_len) == 0 else None,
                path_hashes=details.path_hashes,
            )
            payload["recent_repeaters_count"] = _get_recent_repeater_count(session)
            _broadcast_event(port, payload)
            return
        except MeshCoreError:
            pass
    if message.code == RESP_CHANNEL_MSG_RECV_V3:
        try:
            details = parse_channel_message_v3(message.payload)
            channel_info = _resolve_channel_runtime_dict(session, owner_id=owner_id, channel_idx=details.channel_idx) or {}
            _log_delivery_debug(
                "bg_channel_msg_v3",
                port=port,
                channel_idx=details.channel_idx,
                path_len=details.path_len,
                snr=details.snr,
                txt_type=details.txt_type,
                sender_timestamp=details.sender_timestamp,
                text=details.text,
            )
            payload = {
                "event": "message",
                "message_type": "channel",
                "code": message.code,
                "channel_idx": details.channel_idx,
                "channel_identity": str(channel_info.get("channel_identity") or ""),
                "channel_name": _normalize_channel_name(channel_info.get("name")),
                "channel_secret_hex": _normalize_channel_secret_hex(channel_info.get("secret_hex")),
                "path_len": details.path_len,
                "path_hashes": details.path_hashes,
                "txt_type": details.txt_type,
                "sender_timestamp": details.sender_timestamp,
                "snr": details.snr,
                "text": details.text,
                "payload_hex": message.payload.hex(),
            }
            payload["id"] = save_channel_message(payload, owner_id=owner_id)
            _notify_mobile_push_about_channel_message(
                session,
                port=port,
                channel_idx=details.channel_idx,
                channel_identity=str(payload.get("channel_identity") or ""),
                message_id=int(payload["id"]),
                text=details.text,
            )
            _touch_repeater_activity(session, path_hashes=details.path_hashes)
            payload["recent_repeaters_count"] = _get_recent_repeater_count(session)
            _broadcast_event(port, payload)
            return
        except MeshCoreError:
            pass
    _broadcast_event(port, {"event": "message", "code": message.code, "payload_hex": message.payload.hex()})


def _request_background_queue_drain(session: BackgroundCompanionSession) -> None:
    session.queue_drain_requested = True


def _broadcast_queue_state(port: str, session: BackgroundCompanionSession, reason: str) -> None:
    with session.snapshot_lock:
        session.queue_last_reason = str(reason or "update")
    snapshot = _build_session_snapshot(session, include_contacts=False, include_channels=False)
    _broadcast_event(
        port,
        {
            "event": "queue-state",
            "reason": str(reason or "update"),
            "queue_state": snapshot.get("queue_state") or {},
        },
    )


def _replay_buffered_push_frames(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    port: str,
) -> None:
    while True:
        frames = client.pop_pending_push_frames()
        if not frames:
            return
        _log_delivery_debug(
            "bg_buffered_push_replay",
            port=port,
            buffered_count=len(frames),
            buffered_remaining=client.pending_push_count(),
        )
        for frame in frames:
            _handle_background_frame(client, session, port, frame, source="buffered")


def _drain_background_message_queue(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    port: str,
    baudrate: int,
) -> None:
    if session.queue_drain_in_progress:
        _request_background_queue_drain(session)
        _broadcast_queue_state(port, session, "deferred")
        _log_delivery_debug(
            "bg_msg_waiting_deferred",
            port=port,
            buffered_pushes=client.pending_push_count(),
        )
        return
    with session.snapshot_lock:
        session.queue_drain_in_progress = True
        _request_background_queue_drain(session)
        session.queue_last_reason = "started"
        session.queue_last_started_at = utc_now_epoch()
        session.queue_last_finished_at = 0
        session.queue_last_empty_at = 0
        session.queue_last_drain_message_count = 0
        session.queue_last_drain_cycles = 0
        session.queue_last_sync_attempts = 0
        session.queue_last_empty_via_timeout = False
        session.queue_last_hit_batch_limit = False
        session.queue_last_overflow_risk = False
    _broadcast_queue_state(port, session, "started")
    drain_started_at = time.monotonic()
    drain_cycles = 0
    drain_messages = 0
    _log_delivery_debug(
        "bg_queue_drain_started",
        port=port,
        buffered_pushes=client.pending_push_count(),
    )
    try:
        while session.queue_drain_requested:
            session.queue_drain_requested = False
            drain_cycles += 1
            with session.snapshot_lock:
                session.queue_last_drain_cycles = int(drain_cycles)
            if not session.command_queue.empty():
                _request_background_queue_drain(session)
                _broadcast_queue_state(port, session, "preempted")
                _log_delivery_debug(
                    "bg_queue_drain_preempted",
                    port=port,
                    pending_commands=session.command_queue.qsize(),
                    buffered_pushes=client.pending_push_count(),
                )
                break
            result = client.drain_queued_messages(
                treat_timeout_as_empty=True,
                max_messages=BACKGROUND_QUEUE_DRAIN_BATCH_LIMIT,
                on_attempt=lambda attempt: _log_delivery_debug(
                    "bg_sync_next_message_attempt",
                    port=port,
                    attempt=attempt,
                ),
                should_stop=lambda: bool(
                    session.stop_event.is_set()
                    or not session.command_queue.empty()
                ),
            )
            _replay_buffered_push_frames(client, session, port)
            if result.queue_empty_via_timeout:
                queue_empty_error = str(result.queue_empty_error or "serial timeout while reading 1 bytes, got 0")
                with session.snapshot_lock:
                    session.queue_last_empty_at = utc_now_epoch()
                    session.queue_last_sync_attempts = int(result.sync_attempts or 0)
                    session.queue_last_empty_via_timeout = True
                    session.queue_last_hit_batch_limit = False
                    session.queue_last_overflow_risk = False
                logging.warning(
                    "background sync_next_message soft-empty port=%s baudrate=%s after PUSH_MSG_WAITING error=%s",
                    port,
                    baudrate,
                    queue_empty_error,
                )
                _log_delivery_debug(
                    "bg_queue_timeout",
                    port=port,
                    attempt=result.sync_attempts,
                    error=queue_empty_error,
                )
                _broadcast_event(port, {"event": "queue-empty"})
                _broadcast_queue_state(port, session, "empty-timeout")
                continue
            if not result.messages:
                with session.snapshot_lock:
                    session.queue_last_empty_at = utc_now_epoch()
                    session.queue_last_sync_attempts = int(result.sync_attempts or 0)
                    session.queue_last_empty_via_timeout = False
                    session.queue_last_hit_batch_limit = False
                    session.queue_last_overflow_risk = False
                _log_delivery_debug(
                    "bg_queue_empty",
                    port=port,
                    attempt=result.sync_attempts,
                )
                _broadcast_event(port, {"event": "queue-empty"})
                _broadcast_queue_state(port, session, "empty")
                continue
            with session.snapshot_lock:
                session.queue_last_drain_message_count = int(drain_messages) + len(result.messages)
                session.queue_last_sync_attempts = int(result.sync_attempts or 0)
                session.queue_last_hit_batch_limit = bool(result.hit_message_limit)
                if result.hit_message_limit:
                    session.queue_last_overflow_risk = True
            for attempt_offset, message in enumerate(result.messages, start=1):
                _log_delivery_debug(
                    "bg_sync_next_message_success",
                    port=port,
                    attempt=max(1, result.sync_attempts - len(result.messages) + attempt_offset),
                    resp_code=message.code,
                )
                drain_messages += 1
                _process_background_message_event(client, session, port, message)
            if result.hit_message_limit:
                _request_background_queue_drain(session)
                _broadcast_queue_state(port, session, "batched-continue")
                _log_delivery_debug(
                    "bg_queue_batch_limit_hit",
                    port=port,
                    batch_limit=BACKGROUND_QUEUE_DRAIN_BATCH_LIMIT,
                    drained_messages=len(result.messages),
                    sync_attempts=result.sync_attempts,
                )
    finally:
        with session.snapshot_lock:
            session.queue_drain_in_progress = False
            session.queue_last_finished_at = utc_now_epoch()
            session.queue_last_drain_message_count = int(drain_messages)
            session.queue_last_drain_cycles = int(drain_cycles)
            if drain_cycles > 1 or drain_messages >= int(BACKGROUND_QUEUE_DRAIN_BATCH_LIMIT) * 2:
                session.queue_last_overflow_risk = True
        _broadcast_queue_state(port, session, "finished")
        _log_delivery_debug(
            "bg_queue_drain_finished",
            port=port,
            cycles=drain_cycles,
            messages=drain_messages,
            duration_ms=int((time.monotonic() - drain_started_at) * 1000),
            buffered_pushes=client.pending_push_count(),
        )


def _handle_background_frame(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    port: str,
    frame: bytes,
    *,
    source: str,
) -> None:
    with session.snapshot_lock:
        session.last_frame_activity_at = time.monotonic()
        owner_id = _normalize_owner_id((session.self_info or {}).get("public_key"))
    code = frame[0]
    _log_delivery_debug(
        "bg_frame",
        port=port,
        code=code,
        frame_hex=frame.hex(),
        frame_len=len(frame),
        source=source,
    )
    if code == PUSH_RAW_DATA:
        advert = _parse_raw_advert(frame)
        if advert is not None:
            if owner_id:
                with _contact_owner_scope(owner_id=owner_id, access_all=False):
                    CONTACT_BACKEND.touch_cached_contact_packet_activity(
                        str(advert.get("public_key") or ""),
                        advert_mode='direct' if int(advert.get("path_len") or 0) == 0 else 'flood',
                    )
            if _is_repeater_adv_type(advert.get("adv_type")) and int(advert.get("path_len") or 0) == 0:
                _touch_repeater_activity(
                    session,
                    public_key=str(advert.get("public_key") or ""),
                )
            _touch_repeater_activity(session, path_hashes=advert.get("path_hashes"))
            _log_delivery_debug(
                "bg_raw_advert",
                port=port,
                public_key=advert.get("public_key"),
                adv_type=advert.get("adv_type"),
                path_len=advert.get("path_len"),
                path_hashes=advert.get("path_hashes"),
                snr=advert.get("snr"),
                rssi=advert.get("rssi"),
                source=source,
            )
            _broadcast_event(port, {"event": "raw-advert", **advert, "recent_repeaters_count": _get_recent_repeater_count(session)})
            return
        _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})
        return
    if code == PUSH_NEW_ADVERT:
        try:
            _sync_contacts_from_client_in_background(
                client,
                session,
                port=port,
                min_interval_secs=5.0,
                reason="push-new-advert",
            )
        except (MeshCoreError, SerialException, ValueError, sqlite3.Error):
            logging.exception("background contacts auto-sync failed port=%s reason=push-new-advert", port)
        _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})
        return
    if code == PUSH_SEND_CONFIRMED:
        try:
            ack_bytes, trip_time_ms = parse_send_confirmed_push(frame)
        except MeshCoreError:
            logging.exception("failed to parse SEND_CONFIRMED push port=%s", port)
            _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})
            return
        ack_hex = ack_bytes.hex()
        delivered = mark_contact_message_delivered_by_ack(ack_hex, owner_id=owner_id)
        _log_delivery_debug(
            "bg_send_confirmed",
            port=port,
            ack_hex=ack_hex,
            trip_time_ms=trip_time_ms,
            delivered=delivered,
            source=source,
        )
        _broadcast_event(port, {"event": "send-confirmed", "ack_hex": ack_hex, "delivered": delivered})
        return
    if code == PUSH_LOG_RX_DATA:
        with session.snapshot_lock:
            current_channels = list(session.channels)
        parsed_group = _parse_log_rx_group_text(frame, current_channels)
        if parsed_group is not None:
            _touch_repeater_activity(session, path_hashes=parsed_group.get("path_hashes"))
            _log_delivery_debug("bg_log_rx_group_text", port=port, source=source, **parsed_group)
            repeated = mark_channel_message_repeated(
                parsed_group["channel_idx"],
                parsed_group["sender_timestamp"],
                parsed_group["text"],
                parsed_group["path_len"],
                parsed_group.get("path_hashes", ""),
                parsed_group.get("full_text", ""),
                owner_id=owner_id,
                channel_identity=parsed_group.get("channel_identity"),
            )
            if repeated is not None:
                _broadcast_event(
                    port,
                    {
                        "event": "channel-relayed",
                        "id": repeated["id"],
                        "channel_idx": parsed_group["channel_idx"],
                        "sender_timestamp": parsed_group["sender_timestamp"],
                        "text": parsed_group["text"],
                        "full_text": parsed_group.get("full_text", ""),
                        "path_len": parsed_group["path_len"],
                        "path_hashes": parsed_group.get("path_hashes", ""),
                        "recent_repeaters_count": _get_recent_repeater_count(session),
                        "send_status": repeated["send_status"],
                    },
                )
            return
        _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})
        return
    if code == PUSH_MSG_WAITING:
        _log_delivery_debug("bg_msg_waiting", port=port, source=source)
        _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})
        _request_background_queue_drain(session)
        if session.queue_drain_in_progress:
            _broadcast_queue_state(port, session, "deferred")
            return
        if _background_should_defer_queue_drain(session, time.monotonic()):
            _broadcast_queue_state(port, session, "interactive-wait")
            _log_delivery_debug(
                "bg_msg_waiting_interactive_wait",
                port=port,
                source=source,
                pending_commands=session.command_queue.qsize(),
                buffered_pushes=client.pending_push_count(),
            )
            return
        _drain_background_message_queue(client, session, port, int(session.config["baudrate"]))
        return
    _broadcast_event(port, {"event": "push", "code": code, "payload_hex": frame[1:].hex()})


def _count_favorite_live_contacts(live_contacts: list[dict] | None) -> int:
    return sum(
        1
        for contact in list(live_contacts or [])
        if bool(int((contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR)
    )


def _get_effective_node_contact_limit(live_contacts: list[dict] | None = None) -> int:
    return BASE_NODE_NON_FAVORITE_CONTACT_LIMIT


def _compact_contact_for_client(contact: dict) -> dict:
    return {
        "public_key": str(contact.get("public_key") or "").lower(),
        "adv_type": int(contact.get("adv_type") or 0),
        "flags": int(contact.get("flags") or 0),
        "path_len_byte": int(contact.get("path_len_byte") or 0),
        "out_path_len": int(contact.get("out_path_len") or 0),
        "out_path_hash_len": int(contact.get("out_path_hash_len") or 0),
        "out_path": str(contact.get("out_path") or ""),
        "adv_name": str(contact.get("adv_name") or ""),
        "last_advert": int(contact.get("last_advert") or 0),
        "lat": float(contact.get("lat") or 0.0),
        "lon": float(contact.get("lon") or 0.0),
        "has_location": bool(contact.get("has_location")),
        "updated_at": int(contact.get("updated_at") or 0),
        "last_interaction_at": int(contact.get("last_interaction_at") or 0),
        "last_materialized_at": int(contact.get("last_materialized_at") or 0),
        "last_removed_from_node_at": int(contact.get("last_removed_from_node_at") or 0),
        "pubkey_prefix": str(contact.get("pubkey_prefix") or "").lower(),
        "unread_count": int(contact.get("unread_count") or 0),
        "last_message_at": int(contact.get("last_message_at") or 0),
        "last_message_text": str(contact.get("last_message_text") or ""),
        "last_message_from_self": bool(contact.get("last_message_from_self")),
        "is_favorite": bool(contact.get("is_favorite")),
        "group_tags": list(contact.get("group_tags") or []),
        "is_on_node": bool(contact.get("is_on_node")),
        "is_local_self": bool(contact.get("is_local_self") or (contact.get("backend") or {}).get("is_local_self")),
    }


def _compact_contacts_for_client(contacts: list[dict] | None) -> list[dict]:
    return [_compact_contact_for_client(contact) for contact in list(contacts or [])]


def _build_contact_count_summary(contacts: list[dict] | None, device: dict | None = None) -> dict:
    all_contacts = list(contacts or [])
    live_contacts = [
        contact for contact in all_contacts
        if bool((contact or {}).get("is_on_node"))
    ]
    cached_only_contacts = [
        contact for contact in all_contacts
        if not bool((contact or {}).get("is_on_node"))
    ]
    node_favorites = sum(
        1 for contact in live_contacts
        if bool((contact or {}).get("is_favorite")) or bool(int((contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR)
    )
    node_direct_history = sum(
        1 for contact in live_contacts
        if int((contact or {}).get("last_message_at") or 0) > 0
    )
    db_repeaters = sum(
        1 for contact in all_contacts
        if int((contact or {}).get("adv_type") or 0) == 2
    )
    db_rooms = sum(
        1 for contact in all_contacts
        if int((contact or {}).get("adv_type") or 0) == 3
    )
    db_sensors = sum(
        1 for contact in all_contacts
        if int((contact or {}).get("adv_type") or 0) == 4
    )
    node_repeaters = sum(
        1 for contact in live_contacts
        if int((contact or {}).get("adv_type") or 0) == 2
    )
    node_rooms = sum(
        1 for contact in live_contacts
        if int((contact or {}).get("adv_type") or 0) == 3
    )
    node_sensors = sum(
        1 for contact in live_contacts
        if int((contact or {}).get("adv_type") or 0) == 4
    )
    node_resident = len(live_contacts)
    node_limit = max(0, int((device or {}).get("max_contacts_base") or (device or {}).get("max_contacts") or 0))
    policy_non_favorite_limit = max(0, int((device or {}).get("max_contacts_policy_non_favorite_limit") or 50))
    node_non_favorites = max(0, node_resident - node_favorites)
    db_contacts = max(0, len(all_contacts) - db_repeaters - db_rooms - db_sensors)
    node_contacts = max(0, node_resident - node_repeaters - node_rooms - node_sensors)
    return {
        "node_resident": int(node_resident),
        "node_limit": int(node_limit),
        "db_total": int(len(all_contacts)),
        "db_only": int(len(cached_only_contacts)),
        "node_favorites": int(node_favorites),
        "node_direct_history": int(node_direct_history),
        "node_non_favorites": int(node_non_favorites),
        "node_repeaters": int(node_repeaters),
        "node_rooms": int(node_rooms),
        "node_sensors": int(node_sensors),
        "node_contacts": int(node_contacts),
        "node_users": int(max(0, node_contacts + node_rooms + node_sensors)),
        "db_repeaters": int(db_repeaters),
        "db_rooms": int(db_rooms),
        "db_sensors": int(db_sensors),
        "db_contacts": int(db_contacts),
        "node_free": int(max(0, node_limit - node_resident)),
        "policy_non_favorite_limit": int(policy_non_favorite_limit),
        "policy_free": int(max(0, policy_non_favorite_limit - node_non_favorites)),
    }


def _compact_contact_payload(payload: dict) -> dict:
    result = dict(payload or {})
    if isinstance(result.get("contacts"), list):
        result["contacts"] = _compact_contacts_for_client(result.get("contacts"))
    return result


def _merge_core_stats_into_radio_stats(radio_stats: dict | None, core_stats) -> dict | None:
    if radio_stats is None and core_stats is None:
        return None
    merged = dict(radio_stats or {})
    if core_stats is not None:
        merged["uptime_secs"] = int(core_stats.uptime_secs)
        merged["core_battery_mv"] = int(core_stats.battery_mv)
        merged["core_errors"] = int(core_stats.errors)
        merged["core_queue_len"] = int(core_stats.queue_len)
    return merged


def _get_merged_radio_stats_with_client(client: MeshCoreSerialClient) -> dict | None:
    try:
        radio_stats = _radio_stats_to_dict(client.get_radio_stats())
    except (MeshCoreError, SerialException, ValueError):
        radio_stats = None
    try:
        core_stats = client.get_core_stats()
    except (MeshCoreError, SerialException, ValueError):
        core_stats = None
    return _merge_core_stats_into_radio_stats(radio_stats, core_stats)


MESHCORE_TELEM_MODE_DENY = 0
MESHCORE_TELEM_MODE_ALLOW_FLAGS = 1
MESHCORE_TELEM_MODE_ALLOW_ALL = 2

MESHCORE_ADVERT_LOC_NONE = 0
MESHCORE_ADVERT_LOC_SHARE = 1
MESHCORE_ADVERT_LOC_PREFS = 2

MESHCORE_AUTOADD_OVERWRITE_OLDEST = 1 << 0
MESHCORE_AUTOADD_CHAT = 1 << 1
MESHCORE_AUTOADD_REPEATER = 1 << 2
MESHCORE_AUTOADD_ROOM_SERVER = 1 << 3
MESHCORE_AUTOADD_SENSOR = 1 << 4


def _decode_meshcore_telemetry_modes(value: object) -> dict[str, int]:
    raw_value = int(value or 0) & 0xFF
    return {
        "base": raw_value & 0x03,
        "location": (raw_value >> 2) & 0x03,
        "environment": (raw_value >> 4) & 0x03,
    }


def _encode_meshcore_telemetry_modes(*, base: object, location: object, environment: object) -> int:
    return (
        (int(base or 0) & 0x03)
        | ((int(location or 0) & 0x03) << 2)
        | ((int(environment or 0) & 0x03) << 4)
    ) & 0xFF


def _parse_boolish(value: object, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _parse_int_or_default(value: object, *, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_float_or_default(value: object, *, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _require_int_range(name: str, value: object, *, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be in range {minimum}..{maximum}")
    return parsed


def _require_float_range(name: str, value: object, *, minimum: float, maximum: float) -> float:
    parsed = float(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be in range {minimum}..{maximum}")
    return parsed


def _validate_meshcore_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("name is required")
    if len(normalized.encode("utf-8")) > 32:
        raise ValueError("name must fit within 32 UTF-8 bytes")
    return normalized


def _collect_meshcore_params_with_client(
    client: MeshCoreSerialClient,
    *,
    device,
    self_info,
    radio_stats: dict | None = None,
    self_telemetry: dict | None = None,
    battery_info: dict | None = None,
) -> dict:
    device_dict = _device_info_to_dict(device)
    self_dict = _self_info_to_dict(self_info)
    telemetry_modes = _decode_meshcore_telemetry_modes(self_dict.get("telemetry_modes"))
    try:
        tuning_params = client.get_tuning_params()
    except (MeshCoreError, SerialException, ValueError):
        tuning_params = None
    try:
        custom_vars = client.get_custom_vars()
    except (MeshCoreError, SerialException, ValueError):
        custom_vars = {}
    try:
        autoadd_config = client.get_autoadd_config()
    except (MeshCoreError, SerialException, ValueError):
        autoadd_config = None
    try:
        allowed_repeat_ranges = client.get_allowed_repeat_freq_ranges()
    except (MeshCoreError, SerialException, ValueError):
        allowed_repeat_ranges = []
    try:
        core_stats = _core_stats_to_dict(client.get_core_stats())
    except (MeshCoreError, SerialException, ValueError):
        core_stats = None
    try:
        packet_stats = _packet_stats_to_dict(client.get_packet_stats())
    except (MeshCoreError, SerialException, ValueError):
        packet_stats = None
    try:
        device_time_epoch = int(client.get_device_time() or 0)
    except (MeshCoreError, SerialException, ValueError):
        device_time_epoch = None

    autoadd_flags = int(getattr(autoadd_config, "config", 0) or 0)
    autoadd_max_hops = int(getattr(autoadd_config, "max_hops", 0) or 0)
    gps_enabled = _parse_boolish(custom_vars.get("gps"), default=False)
    gps_interval = _parse_int_or_default(custom_vars.get("gps_interval"), default=0)
    current_freq_khz = int(round(float(self_dict.get("radio_freq_hz_x1000") or 0)))
    allowed_repeat_ranges_payload = [
        {
            "lower_freq_khz": int(item.lower_freq_khz),
            "upper_freq_khz": int(item.upper_freq_khz),
            "lower_freq_mhz": round(float(item.lower_freq_khz) / 1000.0, 3),
            "upper_freq_mhz": round(float(item.upper_freq_khz) / 1000.0, 3),
        }
        for item in allowed_repeat_ranges
    ]
    client_repeat_allowed = any(
        int(item.get("lower_freq_khz") or 0) <= current_freq_khz <= int(item.get("upper_freq_khz") or 0)
        for item in allowed_repeat_ranges_payload
        if isinstance(item, dict)
    )
    return {
        "radio": {
            "freq_mhz": round(float(self_dict.get("radio_freq_hz_x1000") or 0) / 1000.0, 3),
            "bw_khz": round(float(self_dict.get("radio_bw_hz_x1000") or 0) / 1000.0, 1),
            "sf": int(self_dict.get("radio_sf") or 0),
            "cr": int(self_dict.get("radio_cr") or 0),
            "tx_power_dbm": int(self_dict.get("tx_power_dbm") or 0),
            "max_tx_power": int(self_dict.get("max_tx_power") or 0),
            "client_repeat": bool(device_dict.get("client_repeat")),
            "client_repeat_allowed": client_repeat_allowed,
            "allowed_repeat_ranges": allowed_repeat_ranges_payload,
        },
        "identity": {
            "name": str(self_dict.get("name") or ""),
            "public_key": str(self_dict.get("public_key") or ""),
            "lat": self_dict.get("lat"),
            "lon": self_dict.get("lon"),
            "device_time_epoch": device_time_epoch,
            "device_time_utc": None if device_time_epoch is None else datetime.fromtimestamp(device_time_epoch, tz=timezone.utc).isoformat(),
            "manufacturer_model": str(device_dict.get("manufacturer_model") or ""),
            "semantic_version": str(device_dict.get("semantic_version") or ""),
            "firmware_build_date": str(device_dict.get("firmware_build_date") or ""),
            "max_contacts": int(device_dict.get("max_contacts") or 0),
            "max_channels": int(device_dict.get("max_channels") or 0),
        },
        "routing": {
            "multi_acks": int(self_dict.get("multi_acks") or 0),
            "manual_add_contacts_raw": int(self_dict.get("manual_add_contacts") or 0),
            "manual_add_only": bool(int(self_dict.get("manual_add_contacts") or 0) & 1),
            "telemetry_modes": telemetry_modes,
            "rx_delay_base": float(getattr(tuning_params, "rx_delay_base", 0.0) or 0.0),
            "airtime_factor": float(getattr(tuning_params, "airtime_factor", 0.0) or 0.0),
            "path_hash_mode": int(device_dict.get("path_hash_mode") or 0),
            "autoadd_config": autoadd_flags,
            "autoadd_max_hops": autoadd_max_hops,
            "autoadd_overwrite_oldest": bool(autoadd_flags & MESHCORE_AUTOADD_OVERWRITE_OLDEST),
            "autoadd_chat": bool(autoadd_flags & MESHCORE_AUTOADD_CHAT),
            "autoadd_repeater": bool(autoadd_flags & MESHCORE_AUTOADD_REPEATER),
            "autoadd_room_server": bool(autoadd_flags & MESHCORE_AUTOADD_ROOM_SERVER),
            "autoadd_sensor": bool(autoadd_flags & MESHCORE_AUTOADD_SENSOR),
        },
        "security": {
            "ble_pin": int(device_dict.get("ble_pin") or 0),
        },
        "region_gps": {
            "gps_enabled": gps_enabled,
            "gps_interval": gps_interval,
            "advert_loc_policy": int(self_dict.get("advert_loc_policy") or 0),
        },
        "bridge_hardware": {
            "manufacturer_model": str(device_dict.get("manufacturer_model") or ""),
            "semantic_version": str(device_dict.get("semantic_version") or ""),
            "firmware_build_date": str(device_dict.get("firmware_build_date") or ""),
            "core_stats": core_stats,
            "radio_stats": dict(radio_stats or {}) if radio_stats else None,
            "packet_stats": packet_stats,
            "self_telemetry": dict(self_telemetry or {}) if self_telemetry else None,
            "battery_info": dict(battery_info or {}) if battery_info else None,
        },
        "persisted_prefs": {
            "manual_add_contacts_raw": int(self_dict.get("manual_add_contacts") or 0),
            "telemetry_modes": telemetry_modes,
            "ble_pin": int(device_dict.get("ble_pin") or 0),
            "gps_enabled": gps_enabled,
            "gps_interval": gps_interval,
            "client_repeat": bool(device_dict.get("client_repeat")),
            "path_hash_mode": int(device_dict.get("path_hash_mode") or 0),
            "autoadd_config": autoadd_flags,
            "autoadd_max_hops": autoadd_max_hops,
            "rx_delay_base": float(getattr(tuning_params, "rx_delay_base", 0.0) or 0.0),
            "airtime_factor": float(getattr(tuning_params, "airtime_factor", 0.0) or 0.0),
        },
        "raw_custom_vars": dict(custom_vars),
        "capabilities": {
            "direct_radio_params": True,
            "direct_tx_power": True,
            "direct_tuning_params": True,
            "direct_other_params": True,
            "direct_device_pin": True,
            "direct_custom_vars": True,
            "direct_autoadd": True,
            "direct_path_hash_mode": True,
            "direct_device_time": True,
            "direct_send_advert": True,
            "remote_cli_bridge": False,
            "companion_cli_rescue_physical_only": True,
            "cli_only_owner_info": True,
            "cli_only_passwords": True,
            "cli_only_regions": True,
            "cli_only_bridge": True,
            "cli_only_acl": True,
        },
        "constraints": {
            "radio": {
                "freq_mhz_min": 300.0,
                "freq_mhz_max": 2500.0,
                "bw_khz_min": 7.0,
                "bw_khz_max": 500.0,
                "sf_min": 5,
                "sf_max": 12,
                "cr_min": 5,
                "cr_max": 8,
                "tx_power_dbm_min": -9,
                "tx_power_dbm_max": int(self_dict.get("max_tx_power") or 0),
                "client_repeat_requires_allowed_range": True,
                "client_repeat_allowed": client_repeat_allowed,
            },
            "identity": {
                "name_max_utf8_bytes": 32,
                "lat_min": -90.0,
                "lat_max": 90.0,
                "lon_min": -180.0,
                "lon_max": 180.0,
            },
            "routing": {
                "multi_acks_min": 0,
                "multi_acks_max": 1,
                "rx_delay_base_min": 0.0,
                "rx_delay_base_max": 20.0,
                "airtime_factor_min": 0.0,
                "airtime_factor_max": 9.0,
                "path_hash_mode_min": 0,
                "path_hash_mode_max": 2,
                "autoadd_max_hops_min": 0,
                "autoadd_max_hops_max": 64,
            },
            "security": {
                "ble_pin_zero_allowed": True,
                "ble_pin_min": 100000,
                "ble_pin_max": 999999,
            },
            "region_gps": {
                "gps_interval_min": 0,
                "gps_interval_max": 86400,
                "advert_loc_policy_min": 0,
                "advert_loc_policy_max": 2,
            },
        },
    }


def _apply_meshcore_params_with_client(
    client: MeshCoreSerialClient,
    *,
    protocol_version: int,
    app_version: int,
    app_name: str,
    group: str,
    patch: dict,
) -> dict:
    normalized_group = str(group or "").strip().lower()
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    current_snapshot = _collect_node_snapshot_with_client(
        client,
        protocol_version=protocol_version,
        app_version=app_version,
        app_name=app_name,
        include_channels=False,
    )
    current_params = dict(current_snapshot.get("meshcore_params") or {})
    if normalized_group == "radio":
        current_radio = dict(current_params.get("radio") or {})
        radio_needs_update = any(
            key in patch
            for key in ("freq_mhz", "bw_khz", "sf", "cr", "client_repeat")
        )
        if radio_needs_update:
            next_freq_mhz = _require_float_range(
                "freq_mhz",
                _parse_float_or_default(patch.get("freq_mhz"), default=float(current_radio.get("freq_mhz") or 0.0)),
                minimum=300.0,
                maximum=2500.0,
            )
            next_bw_khz = _require_float_range(
                "bw_khz",
                _parse_float_or_default(patch.get("bw_khz"), default=float(current_radio.get("bw_khz") or 0.0)),
                minimum=7.0,
                maximum=500.0,
            )
            next_sf = _require_int_range(
                "sf",
                _parse_int_or_default(patch.get("sf"), default=int(current_radio.get("sf") or 0)),
                minimum=5,
                maximum=12,
            )
            next_cr = _require_int_range(
                "cr",
                _parse_int_or_default(patch.get("cr"), default=int(current_radio.get("cr") or 0)),
                minimum=5,
                maximum=8,
            )
            next_client_repeat = _parse_boolish(patch.get("client_repeat"), default=bool(current_radio.get("client_repeat")))
            allowed_repeat_ranges = list(current_radio.get("allowed_repeat_ranges") or [])
            if next_client_repeat and allowed_repeat_ranges:
                freq_khz = int(round(next_freq_mhz * 1000.0))
                if not any(
                    int(item.get("lower_freq_khz") or 0) <= freq_khz <= int(item.get("upper_freq_khz") or 0)
                    for item in allowed_repeat_ranges
                    if isinstance(item, dict)
                ):
                    raise ValueError("client_repeat is not allowed for the selected frequency")
            client.set_radio_params(
                freq_mhz=next_freq_mhz,
                bw_khz=next_bw_khz,
                sf=next_sf,
                cr=next_cr,
                client_repeat=1 if next_client_repeat else 0,
            )
        if "tx_power_dbm" in patch:
            client.set_radio_tx_power(
                _require_int_range(
                    "tx_power_dbm",
                    _parse_int_or_default(patch.get("tx_power_dbm"), default=int(current_radio.get("tx_power_dbm") or 0)),
                    minimum=-9,
                    maximum=int(current_radio.get("max_tx_power") or 30),
                )
            )
    elif normalized_group == "identity":
        next_name = str(patch.get("name") or "").strip()
        if "name" in patch and next_name:
            client.set_advert_name(_validate_meshcore_name(next_name))
        if "lat" in patch or "lon" in patch:
            current_identity = dict(current_params.get("identity") or {})
            lat = _parse_float_or_default(patch.get("lat"), default=float(current_identity.get("lat") or 0.0))
            lon = _parse_float_or_default(patch.get("lon"), default=float(current_identity.get("lon") or 0.0))
            client.set_advert_coords(lat, lon)
    elif normalized_group == "routing":
        current_routing = dict(current_params.get("routing") or {})
        if any(
            key in patch
            for key in ("manual_add_only", "multi_acks", "telemetry_mode_base", "telemetry_mode_loc", "telemetry_mode_env")
        ):
            current_manual_add_raw = int(current_routing.get("manual_add_contacts_raw") or 0)
            manual_add_only = _parse_boolish(patch.get("manual_add_only"), default=bool(current_routing.get("manual_add_only")))
            next_manual_add_raw = (current_manual_add_raw & ~1) | (1 if manual_add_only else 0)
            current_telemetry = dict(current_routing.get("telemetry_modes") or {})
            telemetry_modes = _encode_meshcore_telemetry_modes(
                base=_parse_int_or_default(patch.get("telemetry_mode_base"), default=int(current_telemetry.get("base") or 0)),
                location=_parse_int_or_default(patch.get("telemetry_mode_loc"), default=int(current_telemetry.get("location") or 0)),
                environment=_parse_int_or_default(patch.get("telemetry_mode_env"), default=int(current_telemetry.get("environment") or 0)),
            )
            current_region_gps = dict(current_params.get("region_gps") or {})
            client.set_other_params(
                manual_add_contacts=next_manual_add_raw,
                telemetry_modes=telemetry_modes,
                advert_loc_policy=_parse_int_or_default(current_region_gps.get("advert_loc_policy"), default=0),
                multi_acks=_require_int_range(
                    "multi_acks",
                    _parse_int_or_default(patch.get("multi_acks"), default=int(current_routing.get("multi_acks") or 0)),
                    minimum=0,
                    maximum=1,
                ),
            )
        if "rx_delay_base" in patch or "airtime_factor" in patch:
            client.set_tuning_params(
                rx_delay_base=_require_float_range(
                    "rx_delay_base",
                    _parse_float_or_default(patch.get("rx_delay_base"), default=float(current_routing.get("rx_delay_base") or 0.0)),
                    minimum=0.0,
                    maximum=20.0,
                ),
                airtime_factor=_require_float_range(
                    "airtime_factor",
                    _parse_float_or_default(patch.get("airtime_factor"), default=float(current_routing.get("airtime_factor") or 0.0)),
                    minimum=0.0,
                    maximum=9.0,
                ),
            )
        if "path_hash_mode" in patch:
            client.set_path_hash_mode(
                _require_int_range(
                    "path_hash_mode",
                    _parse_int_or_default(patch.get("path_hash_mode"), default=int(current_routing.get("path_hash_mode") or 0)),
                    minimum=0,
                    maximum=2,
                )
            )
        if any(
            key in patch
            for key in ("autoadd_overwrite_oldest", "autoadd_chat", "autoadd_repeater", "autoadd_room_server", "autoadd_sensor", "autoadd_max_hops")
        ):
            next_autoadd = 0
            if _parse_boolish(patch.get("autoadd_overwrite_oldest"), default=bool(current_routing.get("autoadd_overwrite_oldest"))):
                next_autoadd |= MESHCORE_AUTOADD_OVERWRITE_OLDEST
            if _parse_boolish(patch.get("autoadd_chat"), default=bool(current_routing.get("autoadd_chat"))):
                next_autoadd |= MESHCORE_AUTOADD_CHAT
            if _parse_boolish(patch.get("autoadd_repeater"), default=bool(current_routing.get("autoadd_repeater"))):
                next_autoadd |= MESHCORE_AUTOADD_REPEATER
            if _parse_boolish(patch.get("autoadd_room_server"), default=bool(current_routing.get("autoadd_room_server"))):
                next_autoadd |= MESHCORE_AUTOADD_ROOM_SERVER
            if _parse_boolish(patch.get("autoadd_sensor"), default=bool(current_routing.get("autoadd_sensor"))):
                next_autoadd |= MESHCORE_AUTOADD_SENSOR
            client.set_autoadd_config(
                next_autoadd,
                max_hops=_require_int_range(
                    "autoadd_max_hops",
                    _parse_int_or_default(patch.get("autoadd_max_hops"), default=int(current_routing.get("autoadd_max_hops") or 0)),
                    minimum=0,
                    maximum=64,
                ),
            )
    elif normalized_group == "security":
        if "ble_pin" in patch:
            next_ble_pin = _parse_int_or_default(patch.get("ble_pin"), default=0)
            if next_ble_pin != 0 and not (100000 <= next_ble_pin <= 999999):
                raise ValueError("ble_pin must be 0 or a 6-digit PIN")
            client.set_device_pin(next_ble_pin)
    elif normalized_group in {"region-gps", "region_gps"}:
        current_region_gps = dict(current_params.get("region_gps") or {})
        if "gps_enabled" in patch:
            client.set_custom_var("gps", "1" if _parse_boolish(patch.get("gps_enabled"), default=bool(current_region_gps.get("gps_enabled"))) else "0")
        if "gps_interval" in patch:
            client.set_custom_var(
                "gps_interval",
                str(
                    _require_int_range(
                        "gps_interval",
                        _parse_int_or_default(patch.get("gps_interval"), default=int(current_region_gps.get("gps_interval") or 0)),
                        minimum=0,
                        maximum=86400,
                    )
                ),
            )
        if "advert_loc_policy" in patch:
            current_routing = dict(current_params.get("routing") or {})
            current_telemetry = dict(current_routing.get("telemetry_modes") or {})
            client.set_other_params(
                manual_add_contacts=int(current_routing.get("manual_add_contacts_raw") or 0),
                telemetry_modes=_encode_meshcore_telemetry_modes(
                    base=int(current_telemetry.get("base") or 0),
                    location=int(current_telemetry.get("location") or 0),
                    environment=int(current_telemetry.get("environment") or 0),
                ),
                advert_loc_policy=_require_int_range(
                    "advert_loc_policy",
                    _parse_int_or_default(patch.get("advert_loc_policy"), default=int(current_region_gps.get("advert_loc_policy") or 0)),
                    minimum=0,
                    maximum=2,
                ),
                multi_acks=int(current_routing.get("multi_acks") or 0),
            )
    else:
        raise ValueError(f"unsupported meshcore params group: {group}")
    return _collect_node_snapshot_with_client(
        client,
        protocol_version=protocol_version,
        app_version=app_version,
        app_name=app_name,
        include_channels=False,
    )


def _collect_node_snapshot_with_client(
    client: MeshCoreSerialClient,
    *,
    protocol_version: int,
    app_version: int,
    app_name: str,
    include_channels: bool = True,
) -> dict:
    device = client.query_device(protocol_version)
    self_info = client.app_start(app_name, app_version)
    device_dict = _device_info_to_dict(device)
    radio_stats = _get_merged_radio_stats_with_client(client)
    owner_id = _normalize_owner_id(getattr(self_info, "public_key", ""))
    if radio_stats is not None:
        _record_signal_metrics_sample(radio_stats, owner_id=owner_id)
    try:
        self_telemetry = _self_telemetry_to_dict(client.get_self_telemetry())
    except (MeshCoreError, SerialException, ValueError):
        self_telemetry = None
    try:
        battery_info = _battery_info_to_dict(client.get_battery_info())
    except (MeshCoreError, SerialException, ValueError):
        battery_info = None
    meshcore_params = _collect_meshcore_params_with_client(
        client,
        device=device,
        self_info=self_info,
        radio_stats=radio_stats,
        self_telemetry=self_telemetry,
        battery_info=battery_info,
    )
    channels: list[dict] = []
    if include_channels:
        try:
            channels = _channels_to_dict(
                [client.get_channel(index) for index in range(device.max_channels)],
                device_dict,
                owner_id=owner_id,
                access_all=False,
            )
        except (MeshCoreError, SerialException, ValueError):
            channels = []
    return {
        "device": device_dict,
        "self": _self_info_to_dict(self_info),
        "channels": channels,
        "radio_stats": radio_stats,
        "self_telemetry": self_telemetry,
        "battery_info": battery_info,
        "meshcore_params": meshcore_params,
    }


def _set_node_location_with_client(
    client: MeshCoreSerialClient,
    *,
    protocol_version: int,
    app_version: int,
    app_name: str,
    lat: float,
    lon: float,
) -> dict:
    self_info = client.app_start(app_name, app_version)
    client.set_advert_coords(lat, lon)
    client.set_other_params(
        manual_add_contacts=int(getattr(self_info, "manual_add_contacts", 0) or 0),
        telemetry_modes=int(getattr(self_info, "telemetry_modes", 0) or 0),
        advert_loc_policy=2,
        multi_acks=int(getattr(self_info, "multi_acks", 0) or 0),
    )
    return _collect_node_snapshot_with_client(
        client,
        protocol_version=protocol_version,
        app_version=app_version,
        app_name=app_name,
    )


def _sync_contacts_from_client_in_background(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    *,
    port: str,
    min_interval_secs: float = 0.0,
    reason: str,
) -> dict | None:
    now_monotonic = time.monotonic()
    if min_interval_secs > 0 and now_monotonic - float(session.last_contact_auto_sync_at or 0.0) < float(min_interval_secs):
        return None
    with _contact_owner_scope(port=port, access_all=False):
        refreshed = CONTACT_BACKEND.refresh_with_client(client, since=None)
    live_contacts = list(refreshed.get("live_contacts") or [])
    with session.snapshot_lock:
        session.contacts = live_contacts
        session.last_contact_auto_sync_at = now_monotonic
        _bootstrap_repeater_tracker_from_contacts_locked(session, live_contacts)
    _broadcast_contacts_snapshot(
        port,
        live_contacts,
        reason=reason,
        contacts_snapshot=refreshed.get("contacts"),
    )
    return refreshed


def _broadcast_contacts_snapshot(
    port: str,
    live_contacts: list[dict] | None,
    *,
    reason: str,
    contacts_snapshot: list[dict] | None = None,
) -> None:
    resolved_owner_id = _resolve_owner_id_for_port(port)
    session = _get_background_session(port)
    with _contact_owner_scope(port=port, owner_id=resolved_owner_id):
        contacts_payload = _compact_contacts_for_client(
            contacts_snapshot if contacts_snapshot is not None else CONTACT_BACKEND.compose_snapshot(live_contacts)
        )
    _broadcast_event(
        port,
        {
            "event": "contacts-sync",
            "reason": str(reason or "auto"),
            "contacts": contacts_payload,
            "contact_summary": _build_contact_count_summary(contacts_snapshot if contacts_snapshot is not None else CONTACT_BACKEND.compose_snapshot(live_contacts)),
            "recent_repeaters_count": _get_recent_repeater_count(session) if session else 0,
        },
    )


def _trim_mobile_push_text(text: object, limit: int = 180) -> str:
    raw = " ".join(str(text or "").strip().split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _message_has_mobile_mention(text: object, mention_name: object) -> bool:
    needle = str(mention_name or "").strip().lower()
    if not needle:
        return False
    return needle in str(text or "").lower()


def _resolve_channel_name_for_push(
    session: BackgroundCompanionSession,
    channel_idx: int,
    *,
    channel_identity: str | None = None,
) -> str:
    with session.snapshot_lock:
        owner_id = _normalize_owner_id((session.self_info or {}).get("public_key"))
    channel_info = _resolve_channel_runtime_dict(session, owner_id=owner_id, channel_idx=channel_idx)
    normalized_identity = str(channel_identity or "").strip()
    if channel_info is None and owner_id and normalized_identity:
        channel_info = _get_node_channel_slot(owner_id, channel_identity=normalized_identity)
    channel_name = _normalize_channel_name(
        (channel_info or {}).get("name") or (channel_info or {}).get("channel_name")
    )
    if channel_name:
        return channel_name
    if normalized_identity.startswith("public::"):
        public_name = normalized_identity.split("::", 1)[1].strip()
        if public_name:
            return public_name
    return f"Канал {channel_idx}"


def _resolve_channel_runtime_dict(
    session: BackgroundCompanionSession | None,
    *,
    owner_id: str | None = None,
    channel_idx: int,
) -> dict | None:
    if session is not None:
        with session.snapshot_lock:
            channels = list(session.channels or [])
        for channel in channels:
            try:
                if int((channel or {}).get("idx") or -1) == int(channel_idx):
                    return dict(channel or {})
            except (TypeError, ValueError, AttributeError):
                continue
    slot = _get_node_channel_slot(owner_id, channel_idx=channel_idx)
    if slot is None:
        return None
    return {
        "idx": int(slot.get("channel_idx") or -1),
        "name": str(slot.get("channel_name") or ""),
        "secret_hex": str(slot.get("channel_secret_hex") or ""),
        "hash": str(slot.get("channel_hash") or ""),
        "channel_identity": str(slot.get("channel_identity") or ""),
        "is_public": bool(slot.get("is_public")),
    }


def _normalize_channel_name(value: object) -> str:
    return str(value or "").strip()


def _normalize_meshcore_channel_name(value: object) -> str:
    return normalize_meshcore_channel_name(_normalize_channel_name(value))


def _is_meshcore_public_channel_name(channel_name: object) -> bool:
    return is_meshcore_public_channel_name(_normalize_channel_name(channel_name))


def _is_public_channel_name(channel_name: object) -> bool:
    return _normalize_channel_name(channel_name).startswith("#")


def _normalize_channel_secret_hex(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if len(normalized) == 32 else ""


def _resolve_channel_secret_hex_for_save(channel_name: object, channel_secret_hex: object = "") -> str:
    normalized_name = _normalize_meshcore_channel_name(channel_name)
    normalized_secret = _normalize_channel_secret_hex(channel_secret_hex)
    if not normalized_name:
        return normalized_secret
    try:
        return format_hex(
            derive_meshcore_channel_secret(
                normalized_name,
                bytes.fromhex(normalized_secret) if normalized_secret else None,
            )
        )
    except ValueError:
        return normalized_secret


def _is_canonical_meshcore_public_channel_config(channel_name: object, channel_secret_hex: object = "") -> bool:
    return (
        _is_meshcore_public_channel_name(channel_name)
        and _normalize_channel_secret_hex(channel_secret_hex) == MESHCORE_PUBLIC_CHANNEL_PSK_HEX
    )


def _channel_runtime_idx(channel: object) -> int:
    if isinstance(channel, dict):
        return int(channel.get("idx") or -1)
    return int(getattr(channel, "channel_idx", -1) or -1)


def _channel_runtime_name(channel: object) -> str:
    if isinstance(channel, dict):
        return _normalize_channel_name(channel.get("name"))
    return _normalize_channel_name(getattr(channel, "channel_name", ""))


def _channel_runtime_secret_hex(channel: object) -> str:
    if isinstance(channel, dict):
        return _normalize_channel_secret_hex(channel.get("secret_hex"))
    return _normalize_channel_secret_hex(format_hex(getattr(channel, "channel_secret", b"")))


def _guard_meshcore_public_channel_edit(existing_channel: object | None, requested_name: object, requested_secret_hex: object) -> None:
    if existing_channel is None:
        return
    existing_name = _channel_runtime_name(existing_channel)
    existing_secret_hex = _channel_runtime_secret_hex(existing_channel)
    if not _is_canonical_meshcore_public_channel_config(existing_name, existing_secret_hex):
        return
    next_name = _normalize_meshcore_channel_name(requested_name)
    next_secret_hex = _resolve_channel_secret_hex_for_save(next_name, requested_secret_hex)
    if next_name != MESHCORE_PUBLIC_CHANNEL_NAME or next_secret_hex != MESHCORE_PUBLIC_CHANNEL_PSK_HEX:
        raise ValueError("official MeshCore public channel #public has a fixed PSK and cannot be edited")


def _build_channel_identity(channel_name: object, channel_secret_hex: object = "") -> str:
    normalized_name = _normalize_meshcore_channel_name(channel_name)
    if not normalized_name:
        return ""
    if _is_public_channel_name(normalized_name):
        return f"public::{normalized_name.lower()}"
    normalized_secret = _normalize_channel_secret_hex(channel_secret_hex)
    if normalized_secret:
        return f"private::{hashlib.sha256(bytes.fromhex(normalized_secret)).hexdigest()}"
    return f"private-name::{normalized_name.lower()}"


def _channel_slot_row_to_dict(row: sqlite3.Row | tuple | None) -> dict | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        source = row
    else:
        source = {
            "owner_id": row[0],
            "channel_idx": row[1],
            "channel_name": row[2],
            "channel_secret_hex": row[3],
            "channel_hash": row[4],
            "channel_identity": row[5],
            "is_public": row[6],
            "last_seen_at": row[7],
        }
    return {
        "owner_id": _normalize_owner_id(source["owner_id"]),
        "channel_idx": int(source["channel_idx"] or 0),
        "channel_name": _normalize_channel_name(source["channel_name"]),
        "channel_secret_hex": _normalize_channel_secret_hex(source["channel_secret_hex"]),
        "channel_hash": str(source["channel_hash"] or "").strip().lower(),
        "channel_identity": str(source["channel_identity"] or "").strip(),
        "is_public": bool(source["is_public"]),
        "last_seen_at": int(source["last_seen_at"] or 0),
    }


def _list_node_channel_slots(owner_id: str | None) -> list[dict]:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return []
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT owner_id, channel_idx, channel_name, channel_secret_hex, channel_hash, channel_identity, is_public, last_seen_at
            FROM node_channel_slots
            WHERE owner_id = ?
            ORDER BY channel_idx ASC
            """,
            (normalized_owner_id,),
        ).fetchall()
    return [_channel_slot_row_to_dict(row) for row in rows if _channel_slot_row_to_dict(row) is not None]


def _get_node_channel_slot(
    owner_id: str | None,
    *,
    channel_idx: int | None = None,
    channel_identity: str | None = None,
    channel_name: str | None = None,
    channel_secret_hex: str | None = None,
) -> dict | None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return None
    candidate_identity = str(channel_identity or "").strip() or _build_channel_identity(channel_name, channel_secret_hex)
    queries: list[tuple[str, tuple[object, ...]]] = []
    if candidate_identity:
        queries.append((
            """
            SELECT owner_id, channel_idx, channel_name, channel_secret_hex, channel_hash, channel_identity, is_public, last_seen_at
            FROM node_channel_slots
            WHERE owner_id = ? AND channel_identity = ?
            LIMIT 1
        """,
            (normalized_owner_id, candidate_identity),
        ))
    if channel_idx is not None:
        queries.append((
            """
            SELECT owner_id, channel_idx, channel_name, channel_secret_hex, channel_hash, channel_identity, is_public, last_seen_at
            FROM node_channel_slots
            WHERE owner_id = ? AND channel_idx = ?
            LIMIT 1
        """,
            (normalized_owner_id, int(channel_idx)),
        ))
    if not queries:
        return None
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for query, params in queries:
            row = conn.execute(query, params).fetchone()
            if row is not None:
                return _channel_slot_row_to_dict(row)
    return None


def _persist_node_channel_slots(owner_id: str | None, channels: list[dict]) -> None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return
    records: list[dict] = []
    now_epoch = utc_now_epoch()
    for channel in list(channels or []):
        channel_idx = int((channel or {}).get("idx") or -1)
        channel_name = _normalize_channel_name((channel or {}).get("name"))
        channel_secret_hex = _normalize_channel_secret_hex((channel or {}).get("secret_hex"))
        if channel_idx < 0 or not channel_name:
            continue
        records.append(
            {
                "owner_id": normalized_owner_id,
                "channel_idx": channel_idx,
                "channel_name": channel_name,
                "channel_secret_hex": channel_secret_hex,
                "channel_hash": str((channel or {}).get("hash") or "").strip().lower(),
                "channel_identity": _build_channel_identity(channel_name, channel_secret_hex),
                "is_public": _is_public_channel_name(channel_name),
                "last_seen_at": now_epoch,
            }
        )
    if not records:
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        existing_rows = conn.execute(
            """
            SELECT owner_id, channel_idx, channel_name, channel_secret_hex, channel_hash, channel_identity, is_public, last_seen_at
            FROM node_channel_slots
            WHERE owner_id = ?
            """,
            (normalized_owner_id,),
        ).fetchall()
        existing_by_identity = {
            str(row["channel_identity"] or "").strip(): _channel_slot_row_to_dict(row)
            for row in existing_rows
            if str(row["channel_identity"] or "").strip()
        }
        for record in records:
            previous = existing_by_identity.get(record["channel_identity"])
            if not previous:
                continue
            previous_idx = int(previous.get("channel_idx") or -1)
            next_idx = int(record["channel_idx"] or -1)
            if previous_idx >= 0 and previous_idx != next_idx:
                conn.execute(
                    """
                    UPDATE messages
                    SET channel_idx = ?
                    WHERE owner_id = ? AND message_kind = 'channel' AND channel_idx = ?
                    """,
                    (next_idx, normalized_owner_id, previous_idx),
                )
        conn.executemany(
            """
            INSERT INTO node_channel_slots (
                owner_id,
                channel_idx,
                channel_name,
                channel_secret_hex,
                channel_hash,
                channel_identity,
                is_public,
                last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, channel_idx) DO UPDATE SET
                channel_name = excluded.channel_name,
                channel_secret_hex = excluded.channel_secret_hex,
                channel_hash = excluded.channel_hash,
                channel_identity = excluded.channel_identity,
                is_public = excluded.is_public,
                last_seen_at = excluded.last_seen_at
            """,
            [
                (
                    record["owner_id"],
                    record["channel_idx"],
                    record["channel_name"],
                    record["channel_secret_hex"],
                    record["channel_hash"],
                    record["channel_identity"],
                    1 if record["is_public"] else 0,
                    record["last_seen_at"],
                )
                for record in records
            ],
        )
        conn.commit()
    _backfill_channel_message_identities(normalized_owner_id)


def _resolve_node_channel_slot_idx(
    owner_id: str | None,
    *,
    channel_idx: int | None = None,
    channel_identity: str | None = None,
    channel_name: str | None = None,
    channel_secret_hex: str | None = None,
) -> int | None:
    slot = _get_node_channel_slot(
        owner_id,
        channel_idx=channel_idx,
        channel_identity=channel_identity,
        channel_name=channel_name,
        channel_secret_hex=channel_secret_hex,
    )
    if slot is None:
        return None if channel_idx is None else int(channel_idx)
    return int(slot.get("channel_idx") or 0)


def _resolve_channel_name_for_port(port: str | None, channel_idx: int) -> str:
    normalized_port = _normalize_port_value(port)
    if not normalized_port:
        return ""
    session = _get_background_session(normalized_port)
    if not session:
        return ""
    with session.snapshot_lock:
        channels = list(session.channels or [])
    for channel in channels:
        try:
            if int((channel or {}).get("idx") or -1) == int(channel_idx):
                return _normalize_channel_name((channel or {}).get("name"))
        except (TypeError, ValueError, AttributeError):
            continue
    return ""


@contextmanager
def _channel_history_scope(port: str | None, channel_idx: int, *, owner_id: str | None = None):
    resolved_owner_id = _normalize_owner_id(owner_id) or _resolve_owner_id_for_port(port)
    channel_name = _resolve_channel_name_for_port(port, channel_idx)
    channel_slot = _get_node_channel_slot(resolved_owner_id, channel_idx=channel_idx, channel_name=channel_name)
    if channel_slot is not None:
        channel_name = _normalize_channel_name(channel_slot.get("channel_name")) or channel_name
    channel_identity = str(
        (channel_slot or {}).get("channel_identity")
        or _build_channel_identity(
            channel_name,
            (channel_slot or {}).get("channel_secret_hex", ""),
        )
    ).strip()
    access_all = bool(_get_access_all_meshcorium_contacts() and _is_public_channel_name(channel_name))
    with _message_owner_scope(resolved_owner_id, access_all, channel_identity=channel_identity):
        with contact_store.contact_scope(
            owner_id=resolved_owner_id,
            access_all=access_all,
        ):
            yield {
                "owner_id": resolved_owner_id,
                "channel_name": channel_name,
                "channel_identity": channel_identity,
                "is_public": _is_public_channel_name(channel_name),
                "access_all": access_all,
            }


def _build_channel_unread_payload_for_port(port: str | None, mention_name: str) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    normalized_port = _normalize_port_value(port)
    session = _get_background_session(normalized_port) if normalized_port else None
    channels = []
    if session:
        with session.snapshot_lock:
            channels = list(session.channels or [])
    owner_id = _resolve_owner_id_for_port(normalized_port)
    if not channels:
        channels = [
            {
                "idx": int(item.get("channel_idx") or -1),
                "name": str(item.get("channel_name") or ""),
                "channel_identity": str(item.get("channel_identity") or ""),
            }
            for item in _list_node_channel_slots(owner_id)
        ]
    if not channels:
        return {}, {}
    owner_id = _resolve_owner_id_for_port(normalized_port)
    if not owner_id:
        return {}, {}

    identity_targets: dict[str, str] = {}
    idx_targets: dict[int, str] = {}
    for channel in channels:
        try:
            channel_idx = int((channel or {}).get("idx") or -1)
        except (TypeError, ValueError, AttributeError):
            continue
        if channel_idx < 0:
            continue
        channel_key = str(channel_idx)
        channel_identity = str((channel or {}).get("channel_identity") or "").strip()
        if channel_identity:
            identity_targets[channel_identity] = channel_key
        else:
            idx_targets[channel_idx] = channel_key

    if not identity_targets and not idx_targets:
        return {}, {}

    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    unread_summary: dict[str, dict[str, int]] = {}
    mention_summary: dict[str, dict[str, int]] = {}

    def _rows_to_payload(rows: list[sqlite3.Row], key_column: str, target_map: dict[str | int, str], count_key: str, first_key: str, last_key: str) -> dict[str, dict[str, int]]:
        payload: dict[str, dict[str, int]] = {}
        for row in rows:
            summary_value = row[key_column]
            if summary_value is None:
                continue
            target_key = target_map.get(summary_value)
            if not target_key:
                continue
            payload[target_key] = {
                count_key: int(row[count_key] or 0),
                first_key: int(row[first_key] or 0),
                last_key: int(row[last_key] or 0),
            }
        return payload

    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        if identity_targets:
            placeholders = ", ".join("?" for _ in identity_targets)
            identity_params = (owner_id, *identity_targets.keys())
            unread_rows = conn.execute(
                f"""
                SELECT
                    channel_identity,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM messages
                WHERE owner_id = ?
                  AND message_kind = 'channel'
                  AND channel_identity IN ({placeholders})
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                  {"" if not needle else "AND lower(text) NOT LIKE ?"}
                GROUP BY channel_identity
                ORDER BY channel_identity ASC
                """,
                identity_params if not needle else identity_params + (like_pattern,),
            ).fetchall()
            unread_summary.update(
                _rows_to_payload(
                    unread_rows,
                    "channel_identity",
                    identity_targets,
                    "unread_count",
                    "first_unread_id",
                    "last_unread_id",
                )
            )
            if needle:
                mention_rows = conn.execute(
                    f"""
                    SELECT
                        channel_identity,
                        COUNT(*) AS mention_count,
                        MIN(id) AS first_mention_id,
                        MAX(id) AS last_mention_id
                    FROM messages
                    WHERE owner_id = ?
                      AND message_kind = 'channel'
                      AND channel_identity IN ({placeholders})
                      AND from_self = 0
                      AND lower(text) LIKE ?
                      AND COALESCE(is_mention_read, 0) = 0
                    GROUP BY channel_identity
                    ORDER BY channel_identity ASC
                    """,
                    identity_params + (like_pattern,),
                ).fetchall()
                mention_summary.update(
                    _rows_to_payload(
                        mention_rows,
                        "channel_identity",
                        identity_targets,
                        "mention_count",
                        "first_mention_id",
                        "last_mention_id",
                    )
                )

        if idx_targets:
            placeholders = ", ".join("?" for _ in idx_targets)
            idx_params = (owner_id, *idx_targets.keys())
            unread_rows = conn.execute(
                f"""
                SELECT
                    channel_idx,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM messages
                WHERE owner_id = ?
                  AND message_kind = 'channel'
                  AND channel_idx IN ({placeholders})
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                  {"" if not needle else "AND lower(text) NOT LIKE ?"}
                GROUP BY channel_idx
                ORDER BY channel_idx ASC
                """,
                idx_params if not needle else idx_params + (like_pattern,),
            ).fetchall()
            unread_summary.update(
                _rows_to_payload(
                    unread_rows,
                    "channel_idx",
                    idx_targets,
                    "unread_count",
                    "first_unread_id",
                    "last_unread_id",
                )
            )
            if needle:
                mention_rows = conn.execute(
                    f"""
                    SELECT
                        channel_idx,
                        COUNT(*) AS mention_count,
                        MIN(id) AS first_mention_id,
                        MAX(id) AS last_mention_id
                    FROM messages
                    WHERE owner_id = ?
                      AND message_kind = 'channel'
                      AND channel_idx IN ({placeholders})
                      AND from_self = 0
                      AND lower(text) LIKE ?
                      AND COALESCE(is_mention_read, 0) = 0
                    GROUP BY channel_idx
                    ORDER BY channel_idx ASC
                    """,
                    idx_params + (like_pattern,),
                ).fetchall()
                mention_summary.update(
                    _rows_to_payload(
                        mention_rows,
                        "channel_idx",
                        idx_targets,
                        "mention_count",
                        "first_mention_id",
                        "last_mention_id",
                    )
                )

    return unread_summary, mention_summary


def _resolve_channel_send_idx_for_request(port: str | None, body: dict) -> int:
    requested_idx = body.get("channel_idx")
    requested_identity = str(body.get("channel_identity") or "").strip()
    requested_name = _normalize_channel_name(body.get("channel_name"))
    requested_secret_hex = _normalize_channel_secret_hex(body.get("channel_secret_hex"))
    owner_id = _resolve_owner_id_for_port(port)
    resolved_idx = _resolve_node_channel_slot_idx(
        owner_id,
        channel_idx=None if requested_idx in (None, "") else int(requested_idx),
        channel_identity=requested_identity,
        channel_name=requested_name,
        channel_secret_hex=requested_secret_hex,
    )
    if resolved_idx is None or resolved_idx < 0:
        raise ValueError("channel_idx is required")
    return int(resolved_idx)


def _resolve_contact_name_for_push(session: BackgroundCompanionSession, pubkey_prefix: str) -> str:
    normalized_prefix = str(pubkey_prefix or "").strip().lower()[:12]
    if not normalized_prefix:
        return "Direct message"
    with session.snapshot_lock:
        live_contacts = list(session.contacts or [])
    for contact in live_contacts:
        public_key = str((contact or {}).get("public_key") or "").strip().lower()
        if public_key.startswith(normalized_prefix):
            return str((contact or {}).get("adv_name") or "").strip() or normalized_prefix.upper()
    return normalized_prefix.upper()


def _notify_mobile_push_about_channel_message(
    session: BackgroundCompanionSession,
    *,
    port: str,
    channel_idx: int,
    channel_identity: str = "",
    message_id: int,
    text: str,
) -> None:
    with session.snapshot_lock:
        self_name = str((session.self_info or {}).get("name") or "").strip()
    channel_name = _resolve_channel_name_for_push(
        session,
        channel_idx,
        channel_identity=channel_identity,
    )
    is_mention = _message_has_mobile_mention(text, self_name)
    send_mobile_push_notification(
        PROJECT_ROOT,
        DB_LOCK,
        CONTACTS_DB_PATH,
        title=f"Упоминание: {channel_name}" if is_mention else channel_name,
        body=_trim_mobile_push_text(text) or "Новое сообщение",
        data={
            "kind": "channel",
            "port": str(port or ""),
            "channel_idx": int(channel_idx),
            "message_id": int(message_id),
            "mention": "1" if is_mention else "0",
        },
        dedupe_key=f"channel:{channel_idx}:{message_id}",
    )


def _notify_mobile_push_about_contact_message(
    session: BackgroundCompanionSession,
    *,
    port: str,
    pubkey_prefix: str,
    message_id: int,
    text: str,
) -> None:
    with session.snapshot_lock:
        self_name = str((session.self_info or {}).get("name") or "").strip()
    contact_name = _resolve_contact_name_for_push(session, pubkey_prefix)
    is_mention = _message_has_mobile_mention(text, self_name)
    send_mobile_push_notification(
        PROJECT_ROOT,
        DB_LOCK,
        CONTACTS_DB_PATH,
        title=f"Упоминание от {contact_name}" if is_mention else contact_name,
        body=_trim_mobile_push_text(text) or "Новое direct-сообщение",
        data={
            "kind": "contact",
            "port": str(port or ""),
            "pubkey_prefix": str(pubkey_prefix or "").strip().lower()[:12],
            "message_id": int(message_id),
            "mention": "1" if is_mention else "0",
        },
        dedupe_key=f"contact:{str(pubkey_prefix or '').strip().lower()[:12]}:{message_id}",
    )


def _promote_direct_sender_to_favorite(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    *,
    port: str,
    pubkey_prefix: str,
) -> bool:
    refreshed = _sync_contacts_from_client_in_background(
        client,
        session,
        port=port,
        reason="direct-message-sync",
    )
    contacts = list((refreshed or {}).get("live_contacts") or session.contacts or [])
    prefix = str(pubkey_prefix or "").strip().lower()
    matches = [
        contact
        for contact in contacts
        if str((contact or {}).get("public_key") or "").strip().lower().startswith(prefix)
    ]
    if len(matches) != 1:
        return False
    target = matches[0]
    if bool(int(target.get("flags", 0)) & CONTACT_FLAG_STAR):
        return False
    public_key = str(target.get("public_key") or "").strip().lower()
    if len(public_key) != 64:
        return False
    contact = client.get_contact_by_key(bytes.fromhex(public_key))
    client.update_contact(contact, flags=int(contact.flags) | CONTACT_FLAG_STAR)
    _sync_contacts_from_client_in_background(
        client,
        session,
        port=port,
        reason="direct-message-auto-favorite",
    )
    _log_contact_debug(
        "direct_message_auto_favorite",
        port=port,
        public_key=public_key,
        pubkey_prefix=prefix,
    )
    return True


def _run_contact_backend_result(port: str, action) -> dict:
    with _paused_background_session(port):
        with _contact_owner_scope(port=port, access_all=False):
            result = action()
    _set_background_session_contacts(port, result.get("live_contacts"))
    return _compact_contact_payload(result)


def _normalize_repeater_public_key_hex(value: object) -> str:
    public_key = str(value or "").strip().lower()
    if len(public_key) != 64:
        raise ValueError("public_key must be a 64-char hex string")
    try:
        bytes.fromhex(public_key)
    except ValueError as exc:
        raise ValueError("public_key must be valid hex") from exc
    return public_key


def _normalize_repeater_cli_commands(value: object) -> list[str]:
    if isinstance(value, str):
        commands = [value]
    elif isinstance(value, list):
        commands = value
    else:
        raise ValueError("commands must be a string or list")
    normalized = [str(item or "").strip() for item in commands if str(item or "").strip()]
    if not normalized:
        raise ValueError("at least one repeater command is required")
    return normalized


def _repeater_login_result_to_dict(result) -> dict:
    return {
        "success": bool(getattr(result, "success", False)),
        "public_key_prefix": str(getattr(result, "public_key_prefix", "") or ""),
        "route_flag": int(getattr(result, "route_flag", 0) or 0),
        "expected_ack_hex": bytes(getattr(result, "expected_ack", b"") or b"").hex(),
        "suggested_timeout_ms": int(getattr(result, "suggested_timeout_ms", 0) or 0),
        "is_admin": bool(getattr(result, "is_admin", False)),
        "login_tag": None if getattr(result, "login_tag", None) is None else int(getattr(result, "login_tag")),
        "acl_permissions": None if getattr(result, "acl_permissions", None) is None else int(getattr(result, "acl_permissions")),
        "firmware_level": None if getattr(result, "firmware_level", None) is None else int(getattr(result, "firmware_level")),
    }


def _prepare_repeater_contact_with_client(
    client: MeshCoreSerialClient,
    *,
    public_key: str,
    hard_device_limit: int,
) -> tuple[list[dict], bool]:
    _cursor, live_contact_models = client.get_contacts()
    live_contacts = CONTACT_BACKEND.prepare_snapshot(live_contact_models)
    was_on_node = any(
        str(contact.get("public_key") or "").strip().lower() == public_key
        for contact in list(live_contacts or [])
    )
    current_contacts = CONTACT_BACKEND.ensure_contact_on_node(
        client,
        public_key,
        max_contacts=_get_effective_node_contact_limit(live_contacts),
        live_contacts=live_contacts,
    )
    return current_contacts, (not was_on_node)


def _compute_repeater_login_wait_timeout_secs(public_key: str, current_contacts: list[dict] | None) -> float:
    normalized_public_key = str(public_key or "").strip().lower()
    target_contact = next(
        (
            contact
            for contact in list(current_contacts or [])
            if str((contact or {}).get("public_key") or "").strip().lower() == normalized_public_key
        ),
        None,
    )
    try:
        hop_count = int((target_contact or {}).get("out_path_len") or 0)
    except Exception:
        hop_count = 0
    if hop_count < 0:
        hop_count = 0
    return 10.0 + (float(hop_count) * 5.0)


def _resolve_repeater_auth_password(public_key: str, password: str | None) -> tuple[str, str]:
    provided_password = str(password or "")
    if provided_password:
        return provided_password, "provided"
    saved_password = CONTACT_BACKEND.get_cached_repeater_auth_password(public_key)
    if saved_password:
        return saved_password, "saved"
    raise ValueError("password is required")


def _login_to_repeater_with_client(
    client: MeshCoreSerialClient,
    *,
    public_key: str,
    password: str,
    hard_device_limit: int,
) -> tuple[dict, list[dict], bool]:
    current_contacts, materialized_on_node = _prepare_repeater_contact_with_client(
        client,
        public_key=public_key,
        hard_device_limit=hard_device_limit,
    )
    login_wait_timeout_secs = _compute_repeater_login_wait_timeout_secs(public_key, current_contacts)
    login_result = client.login_to_repeater(
        bytes.fromhex(public_key),
        str(password or ""),
        wait_timeout_secs=login_wait_timeout_secs,
    )
    if not login_result.success:
        raise MeshCoreError("repeater login failed")
    CONTACT_BACKEND.touch_cached_contact_packet_activity(public_key)
    try:
        favorite_result = CONTACT_BACKEND.perform_action_with_client(
            client,
            public_key=public_key,
            action="favorite",
            favorite=True,
            import_uri=None,
            route_path_len=None,
            route_path_hash_len=None,
            route_path_hex=None,
            hard_device_limit=hard_device_limit,
        )
        next_live_contacts = favorite_result.get("live_contacts")
        if isinstance(next_live_contacts, list):
            current_contacts = next_live_contacts
        materialized_on_node = bool(materialized_on_node or favorite_result.get("materialized_on_node"))
    except Exception:
        logging.exception("repeater login auto-favorite failed target=%s", public_key[:12])
    return _repeater_login_result_to_dict(login_result), current_contacts, materialized_on_node


def _run_repeater_cli_batch_with_client(
    client: MeshCoreSerialClient,
    *,
    public_key: str,
    password: str,
    commands: list[str],
    command_delay_secs: float = 0.2,
    hard_device_limit: int,
) -> dict:
    login_payload, current_contacts, materialized_on_node = _login_to_repeater_with_client(
        client,
        public_key=public_key,
        password=password,
        hard_device_limit=hard_device_limit,
    )
    command_results: list[dict] = []
    for index, command in enumerate(commands):
        sent = client.send_repeater_cli_command(bytes.fromhex(public_key), command)
        CONTACT_BACKEND.touch_cached_contact_packet_activity(public_key)
        command_results.append(
            {
                "command": command,
                "route_flag": int(getattr(sent, "route_flag", 0) or 0),
                "expected_ack_hex": bytes(getattr(sent, "expected_ack", b"") or b"").hex(),
                "suggested_timeout_ms": int(getattr(sent, "suggested_timeout_ms", 0) or 0),
            }
        )
        if index + 1 < len(commands):
            time.sleep(max(0.0, float(command_delay_secs)))
    return {
        "ok": True,
        "login": login_payload,
        "commands": command_results,
        "materialized_on_node": bool(materialized_on_node),
        "live_contacts": current_contacts,
    }


def _build_contact_groups_payload(port: str | None = None) -> dict:
    active_port = _normalize_port_value(port)
    session = _get_background_session(active_port) if active_port else None
    live_contacts = None
    if session:
        with session.snapshot_lock:
            if session.active:
                live_contacts = list(session.contacts or [])
    with _contact_owner_scope(port=active_port):
        return CONTACT_BACKEND.build_contact_groups_payload_for_scope("", live_contacts)


def _build_contact_groups_scope_key(*, port: str | None, baudrate: object | None) -> str:
    normalized_port = _normalize_port_value(port)
    if not normalized_port:
        return ""
    try:
        normalized_baudrate = int(baudrate if baudrate is not None else DEFAULT_BAUDRATE)
    except (TypeError, ValueError):
        normalized_baudrate = DEFAULT_BAUDRATE
    return _build_connection_key({"port": normalized_port, "baudrate": normalized_baudrate})


def _build_contact_groups_payload_for_scope(*, port: str | None, baudrate: object | None) -> dict:
    scope_key = _build_contact_groups_scope_key(port=port, baudrate=baudrate)
    active_port = _normalize_port_value(port)
    session = _get_background_session(active_port) if active_port else None
    live_contacts = None
    if session:
        with session.snapshot_lock:
            if session.active:
                live_contacts = list(session.contacts or [])
    with _contact_owner_scope(port=active_port):
        payload = CONTACT_BACKEND.build_contact_groups_payload_for_scope(scope_key, live_contacts)
    payload["scope"]["active_port"] = active_port
    payload["scope"]["active_baudrate"] = int(baudrate if str(baudrate or "").strip() else DEFAULT_BAUDRATE)
    return payload


def _normalize_session_config(
    *,
    port: str,
    baudrate: int,
    timeout: float,
    protocol_version: int,
    app_version: int,
    app_name: str,
    transport_type: str = "serial",
    transport_id: str = "",
    display_label: str = "",
    pin: str = "",
) -> dict:
    normalized_transport_type = str(transport_type or SERIAL_TRANSPORT_TYPE).strip().lower() or SERIAL_TRANSPORT_TYPE
    normalized_transport_id = str(transport_id or port or "").strip()
    if normalized_transport_type == SERIAL_TRANSPORT_TYPE:
        descriptor = ConnectionDescriptor.from_legacy_serial(
            port=normalized_transport_id,
            baudrate=baudrate,
            timeout=timeout,
            display_label=display_label or normalized_transport_id,
        )
        connection_id = descriptor.port
    else:
        descriptor = DEFAULT_CONNECTION_ROUTER.from_request(
            {
                "connection": {
                    "transport_type": normalized_transport_type,
                    "transport_id": normalized_transport_id,
                    "display_label": display_label or normalized_transport_id,
                    "baudrate": baudrate,
                    "timeout": timeout,
                    "pin": pin,
                }
            }
        )
        connection_id = descriptor.transport_id
    return {
        "port": connection_id,
        "baudrate": int(descriptor.baudrate),
        "timeout": float(descriptor.timeout),
        "protocol_version": int(protocol_version),
        "app_version": int(app_version),
        "app_name": str(app_name),
        "transport_type": descriptor.transport_type,
        "transport_id": descriptor.transport_id,
        "connection": descriptor.to_dict(include_secrets=bool(descriptor.pin)),
    }


def _normalize_port_value(port: object) -> str:
    value = str(port or "").strip()
    if not value or value == "-":
        return ""
    return value


def _load_channels_in_session(client: MeshCoreSerialClient, max_channels: int, *, owner_id: str | None = None) -> list[dict]:
    channels = []
    for channel_idx in range(max_channels):
        try:
            channels.append(client.get_channel(channel_idx))
        except (MeshCoreError, SerialException, ValueError):
            continue
    return _channels_to_dict(
        channels,
        {"max_channels": max_channels},
        owner_id=owner_id or _resolve_owner_id_for_port(getattr(client, "port", "")),
        access_all=False,
    )


def _run_background_session(session: BackgroundCompanionSession) -> None:
    port = str(session.config["port"])
    baudrate = int(session.config["baudrate"])
    timeout = float(session.config["timeout"])
    protocol_version = int(session.config["protocol_version"])
    app_version = int(session.config["app_version"])
    app_name = str(session.config["app_name"])
    session_kwargs = {
        "connection": dict(session.config.get("connection") or {}),
        "port": port,
        "baudrate": baudrate,
        "timeout": timeout,
        "transport_type": str(session.config.get("transport_type") or "serial"),
        "transport_id": str(session.config.get("transport_id") or port),
    }
    logging.info(
        "background session starting transport=%s connection=%s baudrate=%s",
        session_kwargs["transport_type"],
        session_kwargs["transport_id"],
        baudrate,
    )
    try:
        with _connection_access_from_kwargs(session_kwargs):
            with _open_meshcore_client(session_kwargs) as client:
                device = client.query_device(protocol_version)
                self_info = client.app_start(app_name, app_version)
                device_dict = _device_info_to_dict(device)
                self_dict = _self_info_to_dict(self_info)
                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                with session.snapshot_lock:
                    session.client = client
                    session.active = True
                    session.error = None
                    session.stop_reason = None
                    session.intentional_stop = False
                    session.last_stop_kind = "connected"
                    session.last_stop_reason = ""
                    session.last_failure_kind = None
                    session.last_reconnect_reason = None
                    session.reconnect_scheduled_at = 0
                    session.reconnect_delay_secs = 0.0
                    session.next_reconnect_at = 0
                    session.reconnect_attempts = 0
                    session.last_connected_at = utc_now_epoch()
                    session.device = device_dict
                    session.self_info = self_dict
                    session.collections_ready = False
                    session.contacts = []
                    session.channels = []
                    session.radio_stats = None
                    session.self_telemetry = None
                    session.battery_info = None
                    session.repeater_tracker = RepeaterRuntimeTracker()
                _adopt_unowned_contact_records(owner_id)
                _adopt_unowned_message_records(owner_id)
                _normalize_self_contact_message_records(owner_id)
                _record_successful_connection(session.config, self_dict, device_dict)
                radio_stats = _get_merged_radio_stats_with_client(client)
                try:
                    self_telemetry = _self_telemetry_to_dict(client.get_self_telemetry())
                except (MeshCoreError, SerialException, ValueError):
                    self_telemetry = None
                try:
                    battery_info = _battery_info_to_dict(client.get_battery_info())
                except (MeshCoreError, SerialException, ValueError):
                    battery_info = None
                try:
                    refreshed_contacts = {"next_since": 0, "live_contacts": [], "contacts": []}
                    with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                        refreshed_contacts = CONTACT_BACKEND.refresh_with_client(client, since=None)
                    contacts_dict = list(refreshed_contacts.get("live_contacts") or [])
                    with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                        contacts_dict = CONTACT_BACKEND.rebuild_live_contacts_from_policy(
                            client,
                            max_contacts=_get_effective_node_contact_limit(contacts_dict),
                            live_contacts=contacts_dict,
                        )
                    with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                        refreshed_contacts = CONTACT_BACKEND.build_live_contacts_result(contacts_dict)
                except (MeshCoreError, SerialException, ValueError):
                    logging.exception(
                        "background session initial contacts load failed port=%s baudrate=%s",
                        port,
                        baudrate,
                    )
                    contacts_dict = []
                    refreshed_contacts = {"next_since": 0, "live_contacts": [], "contacts": []}
                try:
                    channels_dict = _load_channels_in_session(client, device.max_channels, owner_id=owner_id)
                except (MeshCoreError, SerialException, ValueError):
                    logging.exception(
                        "background session initial channels load failed port=%s baudrate=%s",
                        port,
                        baudrate,
                    )
                    channels_dict = []
                with session.snapshot_lock:
                    session.collections_ready = True
                    session.contacts = contacts_dict
                    session.channels = channels_dict
                    session.radio_stats = radio_stats
                    session.self_telemetry = self_telemetry
                    session.battery_info = battery_info
                    _bootstrap_repeater_tracker_from_contacts_locked(session, contacts_dict)
                session.ready_event.set()
                _freeze_self_contact_if_cached(self_dict)
                _record_signal_metrics_sample(radio_stats, repeaters=_get_recent_repeater_count(session), owner_id=owner_id)
                recent_repeaters_count = _get_recent_repeater_count(session)
                logging.info(
                    "background session initial snapshot ready port=%s baudrate=%s contacts=%s channels=%s",
                    port,
                    baudrate,
                    len(contacts_dict),
                    len(channels_dict),
                )
                live_poll_timeout = min(float(timeout), 0.25) if timeout > 0 else 0.25
                if not client.set_serial_timeout(live_poll_timeout, suppress_errors=True):
                    logging.warning(
                        "background session post-start timeout reconfigure failed port=%s baudrate=%s timeout=%s",
                        port,
                        baudrate,
                        live_poll_timeout,
                    )
                full_contacts_snapshot = list(refreshed_contacts.get("contacts") or [])
                _broadcast_event(
                    port,
                    {
                        "event": "connected",
                        "device": device_dict,
                        "self": self_dict,
                        "collections_ready": True,
                        "contacts": full_contacts_snapshot,
                        "channels": channels_dict,
                        "contacts_count": len(contacts_dict),
                        "channels_count": len(channels_dict),
                        "recent_repeaters_count": recent_repeaters_count,
                        "radio_stats": radio_stats,
                        "self_telemetry": self_telemetry,
                        "battery_info": battery_info,
                    },
                )
                next_radio_stats_poll_at = time.monotonic() + _normalize_signal_metrics_poll_seconds(_get_client_settings().get("signal_metrics_poll_seconds"))
                next_contact_eviction_sweep_at = time.monotonic() + _get_contact_eviction_sweep_interval_secs()
                while not session.stop_event.is_set():
                    while True:
                        try:
                            _, _, command = session.command_queue.get_nowait()
                        except queue.Empty:
                            break
                        response_queue = command.get("response_queue")
                        kind = str(command.get("kind") or "")
                        command_sequence = int(command.get("_bg_sequence") or 0)
                        enqueued_at = float(command.get("_bg_enqueued_at") or 0.0)
                        command_started_at = time.monotonic()
                        pending_pushes_before = client.pending_push_count()
                        with session.snapshot_lock:
                            session.active_command_kind = kind
                            session.active_command_started_at = command_started_at
                            session.last_command_activity_at = command_started_at
                            if _background_command_is_interactive(kind):
                                session.last_interactive_command_at = command_started_at
                        _log_delivery_debug(
                            "bg_command_started",
                            port=port,
                            kind=kind,
                            sequence=command_sequence,
                            queue_wait_ms=(
                                int(max(0.0, (command_started_at - enqueued_at) * 1000.0))
                                if enqueued_at > 0.0
                                else None
                            ),
                            buffered_pushes_before=pending_pushes_before,
                            queue_drain_in_progress=bool(session.queue_drain_in_progress),
                        )
                        try:
                            if kind == "send_channel_text":
                                sent = client.send_channel_text_message(
                                    int(command["channel_idx"]),
                                    str(command["text"]),
                                    timestamp=int(command["timestamp"]),
                                )
                                _log_delivery_debug(
                                    "bg_command_send_channel_text",
                                    port=port,
                                    sequence=command_sequence,
                                    channel_idx=int(command["channel_idx"]),
                                    text=str(command["text"]),
                                    sender_timestamp=int(command["timestamp"]),
                                    expected_ack_hex=sent.expected_ack.hex(),
                                    suggested_timeout_ms=sent.suggested_timeout_ms,
                                    route_flag=sent.route_flag,
                                )
                                _log_delivery_debug(
                                    "bg_command_response_put",
                                    port=port,
                                    kind=kind,
                                    sequence=command_sequence,
                                    ok=True,
                                )
                                response_queue.put({"ok": True, "sent": sent})
                                continue
                            if kind == "get_device_time":
                                epoch = client.get_device_time()
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True, "epoch": int(epoch)})
                                continue
                            if kind == "sync_device_time":
                                target_epoch = int(command.get("epoch") or utc_now_epoch())
                                before = client.get_device_time()
                                client.set_device_time(target_epoch)
                                after = client.get_device_time()
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put(
                                    {
                                        "ok": True,
                                        "requested_epoch": target_epoch,
                                        "before": int(before),
                                        "after": int(after),
                                    }
                                )
                                continue
                            if kind == "send_advert":
                                advert_name = str(command.get("name") or "").strip()
                                if advert_name:
                                    client.set_advert_name(advert_name)
                                client.send_self_advert(flood=bool(command.get("flood", False)))
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True})
                                continue
                            if kind == "save_channel":
                                channel_dict, channels_dict = _save_channel_and_reload_with_client(
                                    client,
                                    session,
                                    None if command.get("channel_idx") in (None, "") else int(command.get("channel_idx")),
                                    str(command.get("channel_name") or ""),
                                    command.get("channel_secret_hex"),
                                )
                                with session.snapshot_lock:
                                    session.channels = channels_dict
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put(
                                    {
                                        "ok": True,
                                        "channel": channel_dict,
                                        "channels": channels_dict,
                                    }
                                )
                                continue
                            if kind == "send_contact_text":
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    sent, current_contacts, materialized_on_node = CONTACT_BACKEND.send_contact_text_with_client(
                                        client,
                                        public_key=str(command["public_key"]),
                                        text=str(command["text"]),
                                        sender_timestamp=int(command["timestamp"]),
                                        max_contacts=_get_effective_node_contact_limit(session.contacts),
                                        live_contacts=list(session.contacts),
                                    )
                                _set_background_session_contacts(port, current_contacts)
                                _log_delivery_debug(
                                    "bg_command_send_contact_text",
                                    port=port,
                                    sequence=command_sequence,
                                    public_key=str(command["public_key"]),
                                    text=str(command["text"]),
                                    sender_timestamp=int(command["timestamp"]),
                                    expected_ack_hex=sent.expected_ack.hex(),
                                    suggested_timeout_ms=sent.suggested_timeout_ms,
                                    route_flag=sent.route_flag,
                                )
                                _log_delivery_debug(
                                    "bg_command_response_put",
                                    port=port,
                                    kind=kind,
                                    sequence=command_sequence,
                                    ok=True,
                                )
                                response_queue.put({"ok": True, "sent": sent, "materialized_on_node": materialized_on_node})
                                continue
                            if kind == "trace_route":
                                trace_result = _run_route_probe_with_client(
                                    client,
                                    live_contacts=list(session.contacts),
                                    selected_public_keys=list(command.get("selected_public_keys") or []),
                                    route_path_hash_len=int(command.get("route_path_hash_len") or 2),
                                    sequential=bool(command.get("sequential", False)),
                                    cancel_event=command.get("cancel_event"),
                                    progress_callback=command.get("progress_callback"),
                                )
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put(trace_result)
                                continue
                            if kind == "refresh_contacts":
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    refreshed = CONTACT_BACKEND.refresh_with_client(
                                        client,
                                        since=None if command.get("since") in (None, "") else int(command.get("since")),
                                    )
                                _set_background_session_contacts(port, refreshed.get("live_contacts"))
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True, **refreshed})
                                continue
                            if kind == "remove_contacts":
                                hard_device_limit = int((session.device or {}).get("max_contacts") or 0)
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    result = CONTACT_BACKEND.remove_contacts_with_client(
                                        client,
                                        mode=str(command.get("mode") or "all"),
                                        protect_favorites=bool(command.get("protect_favorites", True)),
                                        hard_device_limit=hard_device_limit,
                                    )
                                _set_background_session_contacts(port, result.get("live_contacts"))
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True, **result})
                                continue
                            if kind == "perform_contact_action":
                                hard_device_limit = int((session.device or {}).get("max_contacts") or 0)
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    result = CONTACT_BACKEND.perform_action_with_client(
                                        client,
                                        public_key=command.get("public_key"),
                                        action=str(command.get("action") or ""),
                                        favorite=command.get("favorite"),
                                        import_uri=command.get("import_uri"),
                                        route_path_len=None if command.get("route_path_len") in (None, "") else int(command.get("route_path_len")),
                                        route_path_hash_len=None if command.get("route_path_hash_len") in (None, "") else int(command.get("route_path_hash_len")),
                                        route_path_hex=str(command.get("route_path_hex") or ""),
                                        hard_device_limit=hard_device_limit,
                                    )
                                _set_background_session_contacts(port, result.get("live_contacts"))
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True, **result})
                                continue
                            if kind == "export_self_contact":
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    uri = CONTACT_BACKEND.export_self_contact_uri_with_client(client)
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({"ok": True, "uri": uri})
                                continue
                            if kind == "sync_favorites_group":
                                with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                    result = CONTACT_BACKEND.sync_favorites_members_with_client(
                                        client,
                                        list(command.get("members") or []),
                                    )
                                _set_background_session_contacts(port, result.get("live_contacts"))
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({
                                    "ok": True,
                                    **result,
                                })
                                continue
                            if kind == "set_node_name":
                                next_name = str(command.get("name") or "").strip()
                                if not next_name:
                                    raise MeshCoreError("name is required")
                                client.set_advert_name(next_name)
                                self_info = client.app_start(app_name, app_version)
                                radio_stats = _get_merged_radio_stats_with_client(client)
                                try:
                                    self_telemetry = _self_telemetry_to_dict(client.get_self_telemetry())
                                except (MeshCoreError, SerialException, ValueError):
                                    self_telemetry = None
                                try:
                                    battery_info = _battery_info_to_dict(client.get_battery_info())
                                except (MeshCoreError, SerialException, ValueError):
                                    battery_info = None
                                try:
                                    max_channels = int((session.device or {}).get("max_channels") or 0)
                                    channels_dict = _load_channels_in_session(client, max_channels, owner_id=owner_id) if max_channels > 0 else list(session.channels)
                                except (MeshCoreError, SerialException, ValueError, AttributeError):
                                    channels_dict = list(session.channels)
                                self_dict = _self_info_to_dict(self_info)
                                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                                with session.snapshot_lock:
                                    session.self_info = self_dict
                                    session.radio_stats = radio_stats
                                    session.self_telemetry = self_telemetry
                                    session.battery_info = battery_info
                                    session.channels = channels_dict
                                    device_dict = dict(session.device or {})
                                _freeze_self_contact_if_cached(self_dict)
                                _adopt_unowned_contact_records(owner_id)
                                _adopt_unowned_message_records(owner_id)
                                _normalize_self_contact_message_records(owner_id)
                                recent_repeaters_count = _get_recent_repeater_count(session)
                                _record_signal_metrics_sample(radio_stats, repeaters=recent_repeaters_count, owner_id=owner_id)
                                _record_successful_connection(session.config, self_dict, device_dict)
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({
                                    "ok": True,
                                    "device": device_dict,
                                    "self": self_dict,
                                    "channels": channels_dict,
                                    "recent_repeaters_count": recent_repeaters_count,
                                    "radio_stats": radio_stats,
                                    "self_telemetry": self_telemetry,
                                    "battery_info": battery_info,
                                })
                                continue
                            if kind == "set_node_location":
                                lat = float(command.get("lat"))
                                lon = float(command.get("lon"))
                                snapshot = _set_node_location_with_client(
                                    client,
                                    protocol_version=protocol_version,
                                    app_version=app_version,
                                    app_name=app_name,
                                    lat=lat,
                                    lon=lon,
                                )
                                device_dict = dict(snapshot.get("device") or {})
                                self_dict = dict(snapshot.get("self") or {})
                                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                                with session.snapshot_lock:
                                    session.device = device_dict
                                    session.self_info = self_dict
                                    session.radio_stats = snapshot.get("radio_stats")
                                    session.self_telemetry = snapshot.get("self_telemetry")
                                    session.battery_info = snapshot.get("battery_info")
                                    session.channels = list(snapshot.get("channels") or [])
                                _freeze_self_contact_if_cached(self_dict)
                                _adopt_unowned_contact_records(owner_id)
                                _adopt_unowned_message_records(owner_id)
                                _normalize_self_contact_message_records(owner_id)
                                _record_successful_connection(session.config, self_dict, device_dict)
                                _clear_self_location_override(owner_id)
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({
                                    "ok": True,
                                    "device": device_dict,
                                    "self": self_dict,
                                    "channels": list(snapshot.get("channels") or []),
                                    "radio_stats": snapshot.get("radio_stats"),
                                    "self_telemetry": snapshot.get("self_telemetry"),
                                    "battery_info": snapshot.get("battery_info"),
                                })
                                continue
                            if kind == "meshcore_params_snapshot":
                                snapshot = _collect_node_snapshot_with_client(
                                    client,
                                    protocol_version=protocol_version,
                                    app_version=app_version,
                                    app_name=app_name,
                                    include_channels=False,
                                )
                                with session.snapshot_lock:
                                    session.device = dict(snapshot.get("device") or {})
                                    session.self_info = dict(snapshot.get("self") or {})
                                    session.radio_stats = snapshot.get("radio_stats")
                                    session.self_telemetry = snapshot.get("self_telemetry")
                                    session.battery_info = snapshot.get("battery_info")
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({
                                    "ok": True,
                                    **snapshot,
                                })
                                continue
                            if kind == "apply_meshcore_params":
                                snapshot = _apply_meshcore_params_with_client(
                                    client,
                                    protocol_version=protocol_version,
                                    app_version=app_version,
                                    app_name=app_name,
                                    group=str(command.get("group") or ""),
                                    patch=dict(command.get("patch") or {}),
                                )
                                self_dict = dict(snapshot.get("self") or {})
                                device_dict = dict(snapshot.get("device") or {})
                                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                                with session.snapshot_lock:
                                    session.device = device_dict
                                    session.self_info = self_dict
                                    session.radio_stats = snapshot.get("radio_stats")
                                    session.self_telemetry = snapshot.get("self_telemetry")
                                    session.battery_info = snapshot.get("battery_info")
                                _freeze_self_contact_if_cached(self_dict)
                                _adopt_unowned_contact_records(owner_id)
                                _adopt_unowned_message_records(owner_id)
                                _normalize_self_contact_message_records(owner_id)
                                _record_successful_connection(session.config, self_dict, device_dict)
                                _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=True)
                                response_queue.put({
                                    "ok": True,
                                    **snapshot,
                                })
                                continue
                            raise MeshCoreError(f"unsupported background command: {kind}")
                        except Exception as exc:
                            _log_delivery_debug(
                                "bg_command_failed",
                                port=port,
                                kind=kind,
                                sequence=command_sequence,
                                duration_ms=int((time.monotonic() - command_started_at) * 1000),
                                buffered_pushes_before=pending_pushes_before,
                                buffered_pushes_after=client.pending_push_count(),
                                error=str(exc),
                            )
                            _log_delivery_debug("bg_command_response_put", port=port, kind=kind, sequence=command_sequence, ok=False, error=str(exc))
                            response_queue.put({"ok": False, "error": str(exc)})
                        finally:
                            finished_at = time.monotonic()
                            with session.snapshot_lock:
                                session.active_command_kind = ""
                                session.active_command_started_at = 0.0
                                session.last_command_activity_at = finished_at
                                if _background_command_is_interactive(kind):
                                    session.last_interactive_command_at = finished_at
                            _replay_buffered_push_frames(client, session, port)
                            _log_delivery_debug(
                                "bg_command_finished",
                                port=port,
                                kind=kind,
                                sequence=command_sequence,
                                duration_ms=int((time.monotonic() - command_started_at) * 1000),
                                buffered_pushes_before=pending_pushes_before,
                                buffered_pushes_after=client.pending_push_count(),
                                queue_drain_in_progress=bool(session.queue_drain_in_progress),
                            )
                    if (
                        session.queue_drain_requested
                        and not session.queue_drain_in_progress
                        and session.command_queue.empty()
                        and not _background_serial_has_pending_input(client)
                        and not _background_should_defer_queue_drain(session, time.monotonic())
                    ):
                        _drain_background_message_queue(client, session, port, int(session.config["baudrate"]))
                        continue
                    if not session.command_queue.empty():
                        continue
                    now_monotonic = time.monotonic()
                    if (
                        now_monotonic >= next_contact_eviction_sweep_at
                        and not _background_should_defer_housekeeping(session, client, now_monotonic)
                    ):
                        try:
                            current_non_favorite_count = sum(
                                1
                                for contact in list(session.contacts or [])
                                if not bool(int((contact or {}).get("flags", 0)) & CONTACT_FLAG_STAR)
                            )
                            over_policy_limit = current_non_favorite_count > _get_effective_node_contact_limit(session.contacts)
                            with _contact_owner_scope(port=port, owner_id=owner_id, access_all=False):
                                current_contacts = CONTACT_BACKEND.evict_contacts_from_node(
                                    client,
                                    list(session.contacts),
                                    max_contacts=_get_effective_node_contact_limit(session.contacts),
                                    preserve_public_keys=set(),
                                    expired_only=not over_policy_limit,
                                )
                            _set_background_session_contacts(port, current_contacts)
                            _broadcast_contacts_snapshot(
                                port,
                                current_contacts,
                                reason="policy-sweep" if over_policy_limit else "expired-sweep",
                            )
                        except (MeshCoreError, SerialException, sqlite3.Error, ValueError) as exc:
                            logging.warning(
                                "background contact sweep failed port=%s baudrate=%s error=%s",
                                port,
                                baudrate,
                                exc,
                            )
                            _broadcast_event(
                                port,
                                {
                                    "event": "contacts-sweep-error",
                                    "message": str(exc),
                                },
                            )
                        next_contact_eviction_sweep_at = now_monotonic + _get_contact_eviction_sweep_interval_secs()
                    if (
                        now_monotonic >= next_radio_stats_poll_at
                        and not _background_should_defer_housekeeping(session, client, now_monotonic)
                    ):
                        radio_stats = _get_merged_radio_stats_with_client(client)
                        if radio_stats is not None:
                            with session.snapshot_lock:
                                session.radio_stats = radio_stats
                            recent_repeaters_count = _get_recent_repeater_count(session)
                            _record_signal_metrics_sample(radio_stats, repeaters=recent_repeaters_count, owner_id=owner_id)
                            _broadcast_event(
                                port,
                                {
                                    "event": "radio-stats",
                                    "recent_repeaters_count": recent_repeaters_count,
                                    "radio_stats": radio_stats,
                                },
                            )
                        next_radio_stats_poll_at = now_monotonic + _normalize_signal_metrics_poll_seconds(_get_client_settings().get("signal_metrics_poll_seconds"))
                    _replay_buffered_push_frames(client, session, port)
                    try:
                        with client.temporary_serial_timeout(BACKGROUND_FRAME_POLL_TIMEOUT_SECS):
                            frame = client.wait_for_frame(
                                timeout_secs=BACKGROUND_FRAME_POLL_TIMEOUT_SECS,
                                empty_error="serial timeout while reading 1 bytes, got 0",
                            )
                    except MeshCoreError as exc:
                        if str(exc) == "serial timeout while reading 1 bytes, got 0":
                            continue
                        raise
                    _handle_background_frame(client, session, port, frame, source="live")
    except (MeshCoreError, SerialException, sqlite3.Error, ValueError) as exc:
        stop_kind = "intentional-stop"
        stop_reason = str(session.stop_reason or exc)
        classification = {
            "failure_kind": "client-closed",
            "stop_kind": stop_kind,
            "reason": stop_reason,
            "auto_reconnect": False,
            "error_event": False,
        }
        with session.snapshot_lock:
            intentional_stop = bool(session.intentional_stop or session.stop_event.is_set())
            queue_drain_active = bool(session.queue_drain_in_progress or session.queue_drain_requested)
            if str(exc) == "serial client closed" and session.stop_event.is_set():
                intentional_stop = True
            if intentional_stop and str(exc) == "serial client closed":
                stop_kind = "reader-closed"
            elif not intentional_stop:
                classification = _classify_background_session_exception(exc, queue_drain_active=queue_drain_active)
                stop_kind = str(classification["stop_kind"])
                stop_reason = str(classification["reason"])
                session.active = False
            session.error = None if intentional_stop else stop_reason
            session.last_stop_kind = stop_kind
            session.last_stop_reason = stop_reason
            session.last_failure_kind = None if intentional_stop else str(classification["failure_kind"])
            if not intentional_stop:
                session.reconnect_attempts = int(session.reconnect_attempts or 0) + 1
                session.last_failure_at = utc_now_epoch()
        session.ready_event.set()
        if intentional_stop:
            _log_delivery_debug(
                "bg_session_stopped",
                port=port,
                stop_kind=stop_kind,
                stop_reason=stop_reason,
                auto_reconnect=False,
            )
            logging.info(
                "background session stopped intentionally port=%s baudrate=%s reason=%s",
                port,
                baudrate,
                stop_reason,
            )
        else:
            auto_reconnect = bool(classification.get("auto_reconnect", True))
            emit_error_event = bool(classification.get("error_event", True))
            if auto_reconnect:
                _schedule_background_reconnect(
                    session.config,
                    stop_reason,
                    failure_kind=str(classification["failure_kind"]),
                )
            else:
                with session.snapshot_lock:
                    session.reconnect_scheduled_at = 0
                    session.reconnect_delay_secs = 0.0
                    session.next_reconnect_at = 0
            _log_delivery_debug(
                "bg_session_stopped",
                port=port,
                failure_kind=str(classification["failure_kind"]),
                stop_kind=stop_kind,
                stop_reason=stop_reason,
                auto_reconnect=auto_reconnect,
                reconnect_attempts=int(session.reconnect_attempts or 0),
            )
            if emit_error_event:
                if str(classification["failure_kind"]) == "ble-unavailable":
                    logging.warning("background session unavailable port=%s baudrate=%s error=%s", port, baudrate, exc)
                else:
                    logging.exception("background session failed port=%s baudrate=%s error=%s", port, baudrate, exc)
                _broadcast_event(
                    port,
                    {
                        "event": "error",
                        "message": stop_reason,
                        "failure_kind": str(classification["failure_kind"]),
                        "stop_kind": stop_kind,
                        "auto_reconnect": auto_reconnect,
                    },
                )
            else:
                logging.warning("background session transient stop port=%s baudrate=%s error=%s", port, baudrate, stop_reason)
            _broadcast_event(
                port,
                {
                    "event": "disconnected",
                    "port": port,
                    "auto_reconnect": auto_reconnect,
                    "reason": stop_reason,
                    "failure_kind": str(classification["failure_kind"]),
                    "stop_kind": stop_kind,
                    "stop_reason": stop_reason,
                    "reconnect_attempts": int(session.reconnect_attempts or 0),
                    "reconnect_scheduled_at": int(session.reconnect_scheduled_at or 0),
                    "reconnect_delay_secs": float(session.reconnect_delay_secs or 0.0),
                    "next_reconnect_at": int(session.next_reconnect_at or 0),
                },
            )
    finally:
        with session.snapshot_lock:
            session.active = False
            session.client = None
        session.ready_event.set()
        logging.info("background session stopped port=%s baudrate=%s", port, baudrate)


def _wait_for_background_session(session: BackgroundCompanionSession, timeout_secs: float = 15.0) -> dict:
    if not session.ready_event.wait(timeout_secs):
        raise MeshCoreError("background companion session did not become ready in time")
    snapshot = _build_session_snapshot(session)
    if not snapshot["active"]:
        error_message = snapshot["error"] or "background companion session is not active"
        stop_state = snapshot.get("stop_state") or {}
        if (
            str(snapshot.get("transport_type") or "") == BLE_TRANSPORT_TYPE
            and str(stop_state.get("last_failure_kind") or "") == "ble-unavailable"
        ):
            raise BleTransportUnavailable(error_message)
        raise MeshCoreError(error_message)
    return snapshot


def _start_background_session(config: dict) -> BackgroundCompanionSession:
    port = str(config["port"])
    _cancel_pending_reconnect(port)
    existing = _get_background_session(port)
    if existing:
        same_config = existing.config == config and existing.thread and existing.thread.is_alive() and not existing.stop_event.is_set()
        if same_config:
            return existing
        _stop_background_session(port)
    session = BackgroundCompanionSession(config=config)
    if existing is not None:
        _carry_background_session_state(existing, session)
        session.intentional_stop = False
        session.stop_reason = None
    thread = threading.Thread(target=_run_background_session, args=(session,), name=f"meshcore-bg-{port}", daemon=True)
    session.thread = thread
    with BACKGROUND_SESSIONS_GUARD:
        BACKGROUND_SESSIONS[port] = session
    thread.start()
    return session


def _stop_background_session(port: str, join_timeout: float = 5.0, *, broadcast_disconnect: bool = True) -> dict | None:
    _cancel_pending_reconnect(port)
    with BACKGROUND_SESSIONS_GUARD:
        session = BACKGROUND_SESSIONS.get(port)
    if not session:
        return None
    snapshot = _build_session_snapshot(session)
    with session.snapshot_lock:
        session.intentional_stop = True
        session.stop_reason = "api-disconnect" if broadcast_disconnect else "paused-session"
        session.last_stop_kind = "intentional-stop"
        session.last_stop_reason = str(session.stop_reason or "")
        client = session.client
    session.stop_event.set()
    if client is not None:
        try:
            client.close()
        except Exception:
            logging.exception("background session client close failed port=%s", port)
    if session.thread and session.thread.is_alive():
        session.thread.join(join_timeout)
    with BACKGROUND_SESSIONS_GUARD:
        if BACKGROUND_SESSIONS.get(port) is session:
            BACKGROUND_SESSIONS.pop(port, None)
    if broadcast_disconnect:
        _broadcast_event(
            port,
            {
                "event": "disconnected",
                "port": port,
                "auto_reconnect": False,
                "reason": str(session.stop_reason or "intentional-stop"),
                "stop_kind": str(session.last_stop_kind or "intentional-stop"),
                "stop_reason": str(session.last_stop_reason or session.stop_reason or "intentional-stop"),
                "reconnect_attempts": int(session.reconnect_attempts or 0),
                "reconnect_scheduled_at": int(session.reconnect_scheduled_at or 0),
                "reconnect_delay_secs": float(session.reconnect_delay_secs or 0.0),
                "next_reconnect_at": int(session.next_reconnect_at or 0),
            },
        )
    return snapshot


@contextmanager
def _paused_background_session(port: str):
    snapshot = _stop_background_session(port, broadcast_disconnect=False)
    try:
        yield snapshot
    finally:
        if snapshot and snapshot.get("port") and snapshot.get("baudrate"):
            config = _normalize_session_config(
                port=str(snapshot["port"]),
                baudrate=int(snapshot["baudrate"]),
                timeout=float(snapshot.get("timeout", DEFAULT_TIMEOUT)),
                protocol_version=int(snapshot.get("protocol_version", DEFAULT_PROTOCOL_VERSION)),
                app_version=int(snapshot.get("app_version", DEFAULT_APP_VERSION)),
                app_name=str(snapshot.get("app_name", DEFAULT_APP_NAME)),
                transport_type=str(snapshot.get("transport_type") or "serial"),
                transport_id=str(snapshot.get("transport_id") or snapshot["port"]),
                display_label=str((snapshot.get("connection") or {}).get("display_label") or snapshot["port"]),
            )
            _start_background_session(config)


def _run_command_via_background_session(port: str, command: dict, timeout_secs: float = 10.0) -> dict:
    session = _get_background_session(port)
    if session is None or not session.thread or not session.thread.is_alive() or session.stop_event.is_set():
        raise MeshCoreError("background companion session is not active")
    with session.snapshot_lock:
        bootstrap_pending = bool(session.device and session.self_info and not session.collections_ready)
    if bootstrap_pending:
        raise MeshCoreError("background companion session is still initializing")
    response_queue: queue.Queue = queue.Queue(maxsize=1)
    payload = dict(command)
    payload["response_queue"] = response_queue
    _enqueue_background_command(session, payload)
    kind = str(payload.get("kind") or "")
    sequence = int(payload.get("_bg_sequence") or 0)
    enqueued_at = float(payload.get("_bg_enqueued_at") or time.monotonic())
    _log_delivery_debug(
        "bg_command_enqueued",
        port=port,
        kind=kind,
        sequence=sequence,
        timeout_secs=float(timeout_secs),
        pending_commands=session.command_queue.qsize(),
    )
    try:
        response = response_queue.get(timeout=timeout_secs)
    except queue.Empty as exc:
        _log_delivery_debug(
            "bg_command_response_timeout",
            port=port,
            kind=kind,
            sequence=sequence,
            timeout_secs=float(timeout_secs),
            wait_ms=int(max(0.0, (time.monotonic() - enqueued_at) * 1000.0)),
            pending_commands=session.command_queue.qsize(),
        )
        raise MeshCoreError("background command timed out") from exc
    _log_delivery_debug(
        "bg_command_response_received",
        port=port,
        kind=kind,
        sequence=sequence,
        wait_ms=int(max(0.0, (time.monotonic() - enqueued_at) * 1000.0)),
        ok=bool(response.get("ok")),
        error=str(response.get("error") or ""),
    )
    if not response.get("ok"):
        raise MeshCoreError(str(response.get("error") or "background command failed"))
    return response


def _resolve_owner_scope(owner_id: str | None = None, access_all: bool | None = None) -> tuple[str, bool]:
    scoped_owner_id = _normalize_owner_id(owner_id if owner_id is not None else getattr(MESSAGE_SCOPE, "owner_id", ""))
    scoped_access_all = getattr(MESSAGE_SCOPE, "access_all", _get_access_all_meshcorium_contacts())
    return scoped_owner_id, bool(scoped_access_all if access_all is None else access_all)


def _get_scoped_channel_identity() -> str:
    return str(getattr(MESSAGE_SCOPE, "channel_identity", "") or "").strip()


def _resolve_channel_message_identity(message: dict | None = None) -> str:
    scoped_identity = _get_scoped_channel_identity()
    if scoped_identity:
        return scoped_identity
    payload = dict(message or {})
    explicit_identity = str(payload.get("channel_identity") or "").strip()
    if explicit_identity:
        return explicit_identity
    return _build_channel_identity(payload.get("channel_name"), payload.get("channel_secret_hex"))


def _message_owner_clause(owner_id: str | None = None, access_all: bool | None = None, *, column: str = "owner_id") -> tuple[str, tuple]:
    normalized_owner_id, resolved_access_all = _resolve_owner_scope(owner_id, access_all)
    if resolved_access_all:
        return "1 = 1", ()
    if not normalized_owner_id:
        return "1 = 0", ()
    return f"{column} = ?", (normalized_owner_id,)


def _adopt_unowned_message_records(owner_id: str | None) -> None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE messages SET owner_id = ? WHERE COALESCE(owner_id, '') = ''", (normalized_owner_id,))
        conn.execute("UPDATE contact_messages SET owner_id = ? WHERE COALESCE(owner_id, '') = ''", (normalized_owner_id,))
        conn.execute("UPDATE signal_metrics SET owner_id = ? WHERE COALESCE(owner_id, '') = ''", (normalized_owner_id,))
        conn.commit()


def _normalize_self_contact_message_records(owner_id: str | None) -> None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return
    self_prefix = normalized_owner_id[:12]
    if len(self_prefix) != 12:
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE contact_messages
            SET from_self = 1,
                is_read = 1,
                is_mention_read = 1
            WHERE owner_id = ?
              AND lower(pubkey_prefix) = ?
            """,
            (normalized_owner_id, self_prefix),
        )
        conn.commit()


def _adopt_unowned_contact_records(owner_id: str | None) -> None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return
    with DB_LOCK, sqlite3.connect(CONTACTS_DB_PATH) as conn:
        contact_store.init_contact_store_schema(conn)
        conn.execute(
            "UPDATE contacts_cache SET owner_id = ? WHERE COALESCE(owner_id, '') = ''",
            (normalized_owner_id,),
        )
        conn.commit()


def _backfill_channel_message_identities(owner_id: str | None) -> None:
    normalized_owner_id = _normalize_owner_id(owner_id)
    if not normalized_owner_id:
        return
    slots = _list_node_channel_slots(normalized_owner_id)
    if not slots:
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        for slot in slots:
            channel_identity = str(slot.get("channel_identity") or "").strip()
            channel_idx = int(slot.get("channel_idx") or -1)
            if not channel_identity or channel_idx < 0:
                continue
            conn.execute(
                """
                UPDATE messages
                SET channel_identity = ?, channel_idx = ?
                WHERE owner_id = ?
                  AND message_kind = 'channel'
                  AND (
                    channel_identity = ?
                    OR (COALESCE(channel_identity, '') = '' AND channel_idx = ?)
                  )
                """,
                (
                    channel_identity,
                    channel_idx,
                    normalized_owner_id,
                    channel_identity,
                    channel_idx,
                ),
            )
        conn.commit()


def save_channel_message(message: dict, *, owner_id: str | None = None) -> int:
    normalized_owner_id, _ = _resolve_owner_scope(owner_id, False)
    if not normalized_owner_id:
        return 0
    channel_identity = _resolve_channel_message_identity(message)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO messages (
                owner_id,
                message_kind,
                channel_idx,
                channel_identity,
                from_self,
                send_status,
                expected_ack_hex,
                acked_at,
                sender_timestamp,
                received_at,
                snr,
                path_len,
                path_hashes,
                txt_type,
                text,
                payload_hex,
                is_read,
                is_mention_read
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_owner_id,
                "channel",
                int(message["channel_idx"]),
                channel_identity,
                1 if message.get("from_self") else 0,
                None if message.get("send_status") is None else str(message["send_status"]),
                None if message.get("expected_ack_hex") is None else str(message["expected_ack_hex"]),
                None if message.get("acked_at") is None else int(message["acked_at"]),
                int(message["sender_timestamp"]),
                int(time.time()),
                None if message.get("snr") is None else float(message["snr"]),
                int(message["path_len"]),
                None if message.get("path_hashes") is None else str(message["path_hashes"]),
                int(message["txt_type"]),
                str(message.get("text") or ""),
                str(message.get("payload_hex") or ""),
                1 if message.get("is_read") or message.get("from_self") else 0,
                1 if message.get("is_mention_read") or message.get("from_self") else 0,
            ),
        )
        if cursor.lastrowid:
            conn.commit()
            return int(cursor.lastrowid)
        row = conn.execute(
            """
            SELECT id
            FROM messages
            WHERE owner_id = ? AND message_kind = 'channel' AND channel_identity = ? AND channel_idx = ? AND sender_timestamp = ? AND text = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                normalized_owner_id,
                channel_identity,
                int(message["channel_idx"]),
                int(message["sender_timestamp"]),
                str(message.get("text") or ""),
            ),
        ).fetchone()
        conn.commit()
        return int(row[0]) if row else 0


def _resolve_history_window_offset(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    where_sql: str,
    params: tuple,
    limit: int,
    unread_filter_sql: str,
    unread_params: tuple,
    context_before: int = 24,
) -> int:
    first_unread = conn.execute(
        f"""
        SELECT id
        FROM {table_name}
        WHERE {where_sql} AND {unread_filter_sql}
        ORDER BY id ASC
        LIMIT 1
        """,
        params + unread_params,
    ).fetchone()
    if first_unread:
        count_before = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE {where_sql} AND id < ?
            """,
            params + (int(first_unread[0]),),
        ).fetchone()[0]
        return max(0, int(count_before) - context_before)
    total_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE {where_sql}
        """,
        params,
    ).fetchone()[0]
    return max(0, int(total_count) - int(limit))


def _resolve_anchor_history_offset(
    conn: sqlite3.Connection,
    table_name: str,
    where_sql: str,
    params: tuple,
    limit: int,
    anchor_message_id: int | None,
    context_before: int = 24,
) -> int | None:
    if anchor_message_id is None:
        return None
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE {where_sql} AND id < ?
        """,
        params + (int(anchor_message_id),),
    ).fetchone()
    if not row:
        return None
    return max(0, int(row[0]) - int(context_before))


def _resolve_before_history_offset(
    conn: sqlite3.Connection,
    table_name: str,
    where_sql: str,
    params: tuple,
    limit: int,
    before_message_id: int | None,
) -> int | None:
    if before_message_id is None:
        return None
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE {where_sql} AND id < ?
        """,
        params + (int(before_message_id),),
    ).fetchone()
    if not row:
        return None
    return max(0, int(row[0]) - int(limit))


def _count_rows(conn: sqlite3.Connection, table_name: str, where_sql: str, params: tuple) -> int:
    row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table_name}
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    return int(row[0] or 0) if row else 0

def list_channel_messages(
    channel_idx: int,
    limit: int = 200,
    anchor_message_id: int | None = None,
    before_message_id: int | None = None,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[dict]:
    safe_limit = max(1, min(int(limit), 500))
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if channel_identity:
            base_where = f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
            base_params = owner_params + (channel_identity,)
        else:
            base_where = f"{owner_where} AND message_kind = 'channel' AND channel_idx = ?"
            base_params = owner_params + (int(channel_idx),)
        offset = _resolve_before_history_offset(
            conn,
            table_name="messages",
            where_sql=base_where,
            params=base_params,
            limit=safe_limit,
            before_message_id=before_message_id,
        )
        if offset is None:
            offset = _resolve_anchor_history_offset(
                conn,
                table_name="messages",
                where_sql=base_where,
                params=base_params,
                limit=safe_limit,
                anchor_message_id=anchor_message_id,
            )
        if offset is None:
            total_count = _count_rows(conn, "messages", base_where, base_params)
            offset = max(0, total_count - safe_limit)
        rows = conn.execute(
            f"""
            SELECT
                id,
                owner_id,
                channel_idx,
                channel_identity,
                from_self,
                send_status,
                expected_ack_hex,
                acked_at,
                sender_timestamp,
                received_at,
                snr,
                path_len,
                path_hashes,
                txt_type,
                text,
                payload_hex,
                is_read
            FROM messages
            WHERE {base_where}
            ORDER BY sender_timestamp ASC, id ASC
            LIMIT ?
            OFFSET ?
            """,
            base_params + (safe_limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def get_channel_message_count(channel_idx: int, *, owner_id: str | None = None, access_all: bool | None = None) -> int:
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        where_sql = (
            f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
            if channel_identity
            else f"{owner_where} AND message_kind = 'channel' AND channel_idx = ?"
        )
        where_params = owner_params + ((channel_identity,) if channel_identity else (int(channel_idx),))
        return _count_rows(
            conn,
            "messages",
            where_sql,
            where_params,
        )


def get_channel_unique_outgoing_texts(
    channel_idx: int,
    limit: int = 20,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[str]:
    safe_limit = max(1, min(int(limit), 100))
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if channel_identity:
            where_sql = (
                f"{owner_where} AND message_kind = 'channel' AND channel_identity = ? "
                "AND from_self = 1 AND trim(COALESCE(text, '')) != ''"
            )
            where_params = owner_params + (channel_identity,)
        else:
            where_sql = (
                f"{owner_where} AND message_kind = 'channel' AND channel_idx = ? "
                "AND from_self = 1 AND trim(COALESCE(text, '')) != ''"
            )
            where_params = owner_params + (int(channel_idx),)
        rows = conn.execute(
            f"""
            SELECT
                trim(text) AS text,
                MAX(sender_timestamp) AS latest_sender_timestamp,
                MAX(id) AS latest_id
            FROM messages
            WHERE {where_sql}
            GROUP BY trim(text)
            ORDER BY latest_sender_timestamp DESC, latest_id DESC
            LIMIT ?
            """,
            where_params + (safe_limit,),
        ).fetchall()
    return [str(row["text"] or "").strip() for row in rows if str(row["text"] or "").strip()]


def get_channel_message_previews(*, owner_id: str | None = None, access_all: bool | None = None) -> dict[str, dict[str, object]]:
    owner_where, owner_params = _message_owner_clause(owner_id, access_all, column="m.owner_id")
    latest_owner_where, latest_owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                m.channel_idx,
                m.channel_identity,
                CASE
                    WHEN COALESCE(m.channel_identity, '') != '' THEN m.channel_identity
                    ELSE 'idx::' || CAST(m.channel_idx AS TEXT)
                END AS preview_key,
                m.text,
                m.from_self,
                m.sender_timestamp
            FROM messages m
            INNER JOIN (
                SELECT
                    CASE
                        WHEN COALESCE(channel_identity, '') != '' THEN channel_identity
                        ELSE 'idx::' || CAST(channel_idx AS TEXT)
                    END AS preview_key,
                    MAX(sender_timestamp) AS max_sender_timestamp,
                    MAX(id) AS max_id
                FROM messages
                WHERE {latest_owner_where} AND message_kind = 'channel'
                GROUP BY preview_key
            ) latest
              ON latest.preview_key = CASE
                    WHEN COALESCE(m.channel_identity, '') != '' THEN m.channel_identity
                    ELSE 'idx::' || CAST(m.channel_idx AS TEXT)
                 END
             AND latest.max_sender_timestamp = m.sender_timestamp
            WHERE {owner_where} AND m.message_kind = 'channel'
            ORDER BY m.id DESC
            """,
            latest_owner_params + owner_params,
        ).fetchall()
    previews: dict[str, dict[str, object]] = {}
    for row in rows:
        preview_key = str(row["preview_key"] or "").strip()
        if preview_key in previews:
            continue
        previews[preview_key] = {
            "text": str(row["text"] or ""),
            "from_self": bool(row["from_self"]),
            "sender_timestamp": int(row["sender_timestamp"] or 0),
        }
    return previews


def save_contact_message(message: dict, *, owner_id: str | None = None) -> int:
    normalized_owner_id, _ = _resolve_owner_scope(owner_id, False)
    if not normalized_owner_id:
        return 0
    message_prefix = str(message.get("pubkey_prefix") or "").lower()[:12]
    is_self_prefix = len(message_prefix) == 12 and normalized_owner_id.startswith(message_prefix)
    from_self = bool(message.get("from_self")) or is_self_prefix
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO contact_messages (
                owner_id,
                pubkey_prefix,
                from_self,
                send_status,
                expected_ack_hex,
                acked_at,
                sender_timestamp,
                received_at,
                snr,
                path_len,
                path_hashes,
                txt_type,
                text,
                payload_hex,
                signature_hex,
                is_read,
                is_mention_read
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_owner_id,
                message_prefix,
                1 if from_self else 0,
                None if message.get("send_status") is None else str(message["send_status"]),
                None if message.get("expected_ack_hex") is None else str(message["expected_ack_hex"]),
                None if message.get("acked_at") is None else int(message["acked_at"]),
                int(message["sender_timestamp"]),
                int(time.time()),
                None if message.get("snr") is None else float(message["snr"]),
                int(message["path_len"]),
                None if message.get("path_hashes") is None else str(message["path_hashes"]),
                int(message["txt_type"]),
                str(message.get("text") or ""),
                str(message.get("payload_hex") or ""),
                None if message.get("signature_hex") is None else str(message["signature_hex"]),
                1 if message.get("is_read") or from_self else 0,
                1 if message.get("is_mention_read") or from_self else 0,
            ),
        )
        if cursor.lastrowid:
            conn.commit()
            message_id = int(cursor.lastrowid)
        else:
            row = conn.execute(
                """
                SELECT id
                FROM contact_messages
                WHERE owner_id = ? AND pubkey_prefix = ? AND sender_timestamp = ? AND text = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    normalized_owner_id,
                    message_prefix,
                    int(message["sender_timestamp"]),
                    str(message.get("text") or ""),
                ),
            ).fetchone()
            conn.commit()
            message_id = int(row[0]) if row else 0
    with _contact_owner_scope(owner_id=normalized_owner_id, access_all=False):
        CONTACT_BACKEND.touch_cached_contact_packet_activity_by_prefix(str(message.get("pubkey_prefix") or ""))
    return message_id


def list_contact_messages(
    public_key: str,
    limit: int = 200,
    anchor_message_id: int | None = None,
    before_message_id: int | None = None,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[dict]:
    safe_limit = max(1, min(int(limit), 500))
    prefix = str(public_key).lower()[:12]
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        base_where = f"{owner_where} AND pubkey_prefix = ?"
        base_params = owner_params + (prefix,)
        offset = _resolve_before_history_offset(
            conn,
            table_name="contact_messages",
            where_sql=base_where,
            params=base_params,
            limit=safe_limit,
            before_message_id=before_message_id,
        )
        if offset is None:
            offset = _resolve_anchor_history_offset(
                conn,
                table_name="contact_messages",
                where_sql=base_where,
                params=base_params,
                limit=safe_limit,
                anchor_message_id=anchor_message_id,
            )
        if offset is None:
            total_count = _count_rows(conn, "contact_messages", base_where, base_params)
            offset = max(0, total_count - safe_limit)
        rows = conn.execute(
            f"""
            SELECT
                id,
                owner_id,
                pubkey_prefix,
                from_self,
                send_status,
                expected_ack_hex,
                acked_at,
                sender_timestamp,
                received_at,
                snr,
                path_len,
                path_hashes,
                txt_type,
                text,
                payload_hex,
                signature_hex,
                is_read
            FROM contact_messages
            WHERE {base_where}
            ORDER BY sender_timestamp ASC, id ASC
            LIMIT ?
            OFFSET ?
            """,
            base_params + (safe_limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def get_contact_message_count(public_key: str, *, owner_id: str | None = None, access_all: bool | None = None) -> int:
    prefix = str(public_key).lower()[:12]
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        return _count_rows(
            conn,
            "contact_messages",
            f"{owner_where} AND pubkey_prefix = ?",
            owner_params + (prefix,),
        )


def get_contact_unique_outgoing_texts(
    public_key: str,
    limit: int = 20,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[str]:
    safe_limit = max(1, min(int(limit), 100))
    prefix = str(public_key).lower()[:12]
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                trim(text) AS text,
                MAX(sender_timestamp) AS latest_sender_timestamp,
                MAX(id) AS latest_id
            FROM contact_messages
            WHERE {owner_where} AND pubkey_prefix = ? AND from_self = 1 AND trim(COALESCE(text, '')) != ''
            GROUP BY trim(text)
            ORDER BY latest_sender_timestamp DESC, latest_id DESC
            LIMIT ?
            """,
            owner_params + (prefix, safe_limit),
        ).fetchall()
    return [str(row["text"] or "").strip() for row in rows if str(row["text"] or "").strip()]


def mark_messages_read_up_to(
    conversation_kind: str,
    conversation_value: str,
    message_id: int,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> int:
    normalized_kind = str(conversation_kind or "").strip().lower()
    if normalized_kind not in {"channel", "contact"}:
        raise ValueError("conversation_kind must be channel or contact")
    next_value = int(message_id)
    if next_value <= 0:
        raise ValueError("message_id must be positive")
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        if normalized_kind == "channel":
            channel_idx = int(conversation_value)
            channel_where = (
                f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
                if channel_identity
                else f"{owner_where} AND message_kind = 'channel' AND channel_idx = ?"
            )
            channel_params = owner_params + ((channel_identity,) if channel_identity else (channel_idx,))
            conn.execute(
                f"""
                UPDATE messages
                SET is_read = 1
                WHERE {channel_where} AND id <= ?
                """,
                channel_params + (next_value,),
            )
            row = conn.execute(
                f"""
                SELECT MAX(id)
                FROM messages
                WHERE {channel_where} AND COALESCE(is_read, 0) = 1
                """,
                channel_params,
            ).fetchone()
        else:
            prefix = str(conversation_value or "").strip().lower()[:12]
            if not prefix:
                raise ValueError("contact conversation_value is required")
            conn.execute(
                f"""
                UPDATE contact_messages
                SET is_read = 1
                WHERE {owner_where} AND pubkey_prefix = ? AND id <= ?
                """,
                owner_params + (prefix, next_value),
            )
            row = conn.execute(
                f"""
                SELECT MAX(id)
                FROM contact_messages
                WHERE {owner_where} AND pubkey_prefix = ? AND COALESCE(is_read, 0) = 1
                """,
                owner_params + (prefix,),
            ).fetchone()
        conn.commit()
    _log_read_debug(
        "mark_messages_read_up_to",
        conversation_kind=normalized_kind,
        conversation_value=str(conversation_value or ""),
        message_id=next_value,
        stored_message_id=int(row[0]) if row and row[0] is not None else 0,
    )
    return int(row[0]) if row and row[0] is not None else 0


def set_mention_message_read_state(
    message_table: str,
    message_id: int,
    is_read: bool,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> bool:
    normalized_table = str(message_table or "").strip().lower()
    if normalized_table not in {"channel", "contact"}:
        raise ValueError("message_table must be channel or contact")
    next_id = int(message_id)
    if next_id <= 0:
        raise ValueError("message_id must be positive")
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        if normalized_table == "channel":
            conn.execute(
                f"""
                UPDATE messages
                SET is_mention_read = ?
                WHERE {owner_where} AND id = ?
                """,
                (1 if is_read else 0, *owner_params, next_id),
            )
        else:
            conn.execute(
                f"""
                UPDATE contact_messages
                SET is_mention_read = ?
                WHERE {owner_where} AND id = ?
                """,
                (1 if is_read else 0, *owner_params, next_id),
            )
        conn.commit()
    _log_read_debug("set_mention_message_read_state", message_table=normalized_table, message_id=next_id, is_read=bool(is_read))
    return True


def clear_message_db(*, owner_id: str | None = None, access_all: bool | None = None) -> int:
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        channel_deleted = conn.execute(f"DELETE FROM messages WHERE {owner_where}", owner_params).rowcount
        contact_deleted = conn.execute(f"DELETE FROM contact_messages WHERE {owner_where}", owner_params).rowcount
        conn.commit()
        return int(channel_deleted + contact_deleted)


def set_all_messages_read_state(
    is_read: bool,
    scope: str = "regular",
    mention_name: str = "",
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, int]:
    normalized_scope = str(scope or "regular").strip().lower()
    if normalized_scope not in {"regular", "mention", "direct", "channel"}:
        raise ValueError("scope must be regular, channel, mention, or direct")
    target = 1 if is_read else 0
    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        channel_updated = 0
        contact_updated = 0
        mention_channel_updated = 0
        mention_contact_updated = 0
        if normalized_scope == "regular":
            if needle:
                channel_updated = conn.execute(
                    f"UPDATE messages SET is_read = ? WHERE {owner_where} AND from_self = 0 AND lower(text) NOT LIKE ?",
                    (target, *owner_params, like_pattern),
                ).rowcount
                contact_updated = conn.execute(
                    f"UPDATE contact_messages SET is_read = ? WHERE {owner_where} AND from_self = 0 AND lower(text) NOT LIKE ?",
                    (target, *owner_params, like_pattern),
                ).rowcount
            else:
                channel_updated = conn.execute(
                    f"UPDATE messages SET is_read = ? WHERE {owner_where} AND from_self = 0",
                    (target, *owner_params),
                ).rowcount
                contact_updated = conn.execute(
                    f"UPDATE contact_messages SET is_read = ? WHERE {owner_where} AND from_self = 0",
                    (target, *owner_params),
                ).rowcount
        elif normalized_scope == "channel":
            if needle:
                channel_updated = conn.execute(
                    f"UPDATE messages SET is_read = ? WHERE {owner_where} AND from_self = 0 AND lower(text) NOT LIKE ?",
                    (target, *owner_params, like_pattern),
                ).rowcount
            else:
                channel_updated = conn.execute(
                    f"UPDATE messages SET is_read = ? WHERE {owner_where} AND from_self = 0",
                    (target, *owner_params),
                ).rowcount
        elif normalized_scope == "direct":
            contact_updated = conn.execute(
                f"UPDATE contact_messages SET is_read = ? WHERE {owner_where} AND from_self = 0",
                (target, *owner_params),
            ).rowcount
        else:
            if is_read:
                if needle:
                    mention_channel_updated = conn.execute(
                        f"""
                        UPDATE messages
                        SET is_mention_read = 1
                        WHERE {owner_where}
                          AND message_kind = 'channel'
                          AND from_self = 0
                          AND lower(text) LIKE ?
                          AND COALESCE(is_mention_read, 0) = 0
                        """,
                        owner_params + (like_pattern,),
                    ).rowcount
                    mention_contact_updated = conn.execute(
                        f"""
                        UPDATE contact_messages
                        SET is_mention_read = 1
                        WHERE {owner_where}
                          AND from_self = 0
                          AND lower(text) LIKE ?
                          AND COALESCE(is_mention_read, 0) = 0
                        """,
                        owner_params + (like_pattern,),
                    ).rowcount
            else:
                if needle:
                    mention_channel_updated = conn.execute(
                        f"""
                        UPDATE messages
                        SET is_mention_read = 0
                        WHERE {owner_where}
                          AND message_kind = 'channel'
                          AND from_self = 0
                          AND lower(text) LIKE ?
                          AND COALESCE(is_mention_read, 0) != 0
                        """,
                        owner_params + (like_pattern,),
                    ).rowcount
                    mention_contact_updated = conn.execute(
                        f"""
                        UPDATE contact_messages
                        SET is_mention_read = 0
                        WHERE {owner_where}
                          AND from_self = 0
                          AND lower(text) LIKE ?
                          AND COALESCE(is_mention_read, 0) != 0
                        """,
                        owner_params + (like_pattern,),
                    ).rowcount
                else:
                    mention_channel_updated = conn.execute(
                        f"""
                        UPDATE messages
                        SET is_mention_read = 0
                        WHERE {owner_where} AND COALESCE(is_mention_read, 0) != 0
                        """,
                        owner_params,
                    ).rowcount
                    mention_contact_updated = conn.execute(
                        f"""
                        UPDATE contact_messages
                        SET is_mention_read = 0
                        WHERE {owner_where} AND COALESCE(is_mention_read, 0) != 0
                        """,
                        owner_params,
                    ).rowcount
        conn.commit()
    _log_read_debug(
        "set_all_messages_read_state",
        scope=normalized_scope,
        is_read=bool(is_read),
        mention_name=needle,
        messages=int(channel_updated),
        contact_messages=int(contact_updated),
        mention_messages=int(mention_channel_updated),
        mention_contact_messages=int(mention_contact_updated),
    )
    return {
        "messages": int(channel_updated),
        "contact_messages": int(contact_updated),
        "mention_messages": int(mention_channel_updated),
        "mention_contact_messages": int(mention_contact_updated),
        "scope": normalized_scope,
    }


def get_message_debug_summary(
    mention_name: str = "",
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, int]:
    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if needle:
            regular_channel = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM messages WHERE {owner_where} AND from_self = 0 AND lower(text) NOT LIKE ?",
                owner_params + (like_pattern,),
            ).fetchone()["total"] or 0)
            regular_contact = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM contact_messages WHERE {owner_where} AND from_self = 0 AND lower(text) NOT LIKE ?",
                owner_params + (like_pattern,),
            ).fetchone()["total"] or 0)
            mention_channel = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM messages WHERE {owner_where} AND from_self = 0 AND lower(text) LIKE ?",
                owner_params + (like_pattern,),
            ).fetchone()["total"] or 0)
            mention_contact = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM contact_messages WHERE {owner_where} AND from_self = 0 AND lower(text) LIKE ?",
                owner_params + (like_pattern,),
            ).fetchone()["total"] or 0)
        else:
            regular_channel = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM messages WHERE {owner_where} AND from_self = 0",
                owner_params,
            ).fetchone()["total"] or 0)
            regular_contact = int(conn.execute(
                f"SELECT COUNT(*) AS total FROM contact_messages WHERE {owner_where} AND from_self = 0",
                owner_params,
            ).fetchone()["total"] or 0)
            mention_channel = 0
            mention_contact = 0
        direct_total = int(conn.execute(
            f"SELECT COUNT(*) AS total FROM contact_messages WHERE {owner_where} AND from_self = 0",
            owner_params,
        ).fetchone()["total"] or 0)
    return {
        "regular_messages": int(regular_channel + regular_contact),
        "regular_channel_messages": int(regular_channel),
        "regular_direct_messages": int(regular_contact),
        "mention_messages": int(mention_channel + mention_contact),
        "mention_channel_messages": int(mention_channel),
        "mention_direct_messages": int(mention_contact),
        "direct_messages": int(direct_total),
    }


def mark_conversation_messages_read(
    conversation_kind: str,
    conversation_value: str,
    mention_name: str = "",
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, int | str]:
    normalized_kind = str(conversation_kind or "").strip().lower()
    if normalized_kind not in {"channel", "contact"}:
        raise ValueError("conversation_kind must be channel or contact")
    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    regular_updated = 0
    mention_updated = 0
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        if normalized_kind == "channel":
            channel_idx = int(conversation_value)
            channel_where = (
                f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
                if channel_identity
                else f"{owner_where} AND message_kind = 'channel' AND channel_idx = ?"
            )
            channel_params = owner_params + ((channel_identity,) if channel_identity else (channel_idx,))
            regular_updated = conn.execute(
                f"""
                UPDATE messages
                SET is_read = 1
                WHERE {channel_where} AND from_self = 0
                """,
                channel_params,
            ).rowcount
            if needle:
                mention_updated = conn.execute(
                    f"""
                    UPDATE messages
                    SET is_mention_read = 1
                    WHERE {channel_where}
                      AND from_self = 0
                      AND lower(text) LIKE ?
                      AND COALESCE(is_mention_read, 0) = 0
                    """,
                    channel_params + (like_pattern,),
                ).rowcount
        else:
            prefix = str(conversation_value or "").strip().lower()[:12]
            if not prefix:
                raise ValueError("contact conversation_value is required")
            regular_updated = conn.execute(
                f"""
                UPDATE contact_messages
                SET is_read = 1
                WHERE {owner_where} AND pubkey_prefix = ? AND from_self = 0
                """,
                owner_params + (prefix,),
            ).rowcount
            if needle:
                mention_updated = conn.execute(
                    f"""
                    UPDATE contact_messages
                    SET is_mention_read = 1
                    WHERE {owner_where} AND pubkey_prefix = ?
                      AND from_self = 0
                      AND lower(text) LIKE ?
                      AND COALESCE(is_mention_read, 0) = 0
                    """,
                    owner_params + (prefix, like_pattern),
                ).rowcount
        conn.commit()
    _log_read_debug(
        "mark_conversation_messages_read",
        conversation_kind=normalized_kind,
        conversation_value=str(conversation_value or ""),
        mention_name=needle,
        regular_updated=int(regular_updated),
        mention_updated=int(mention_updated),
    )
    return {
        "conversation_kind": normalized_kind,
        "conversation_value": str(conversation_value or ""),
        "regular_updated": int(regular_updated),
        "mention_updated": int(mention_updated),
    }


def get_channel_unread_counts(*, owner_id: str | None = None, access_all: bool | None = None) -> dict[str, int]:
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        grouping_column = "channel_identity" if channel_identity else "channel_idx"
        selector_where = (
            f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
            if channel_identity
            else f"{owner_where} AND message_kind = 'channel'"
        )
        selector_params = owner_params + ((channel_identity,) if channel_identity else ())
        rows = conn.execute(
            f"""
            SELECT {grouping_column} AS channel_key, COUNT(*) AS unread_count
            FROM messages
            WHERE {selector_where} AND from_self = 0 AND COALESCE(is_read, 0) = 0
            GROUP BY {grouping_column}
            ORDER BY {grouping_column} ASC
            """,
            selector_params,
        ).fetchall()
    return {
        str(row["channel_key"] if channel_identity else int(row["channel_key"])): int(row["unread_count"] or 0)
        for row in rows
    }


def _list_scoped_channel_unread_mentions(
    mention_name: str,
    limit: int = 100,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[dict[str, object]]:
    needle = str(mention_name or "").strip().lower()
    safe_limit = max(1, min(int(limit), 200))
    channel_identity = _get_scoped_channel_identity()
    if not needle:
        return []
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    selector_where = (
        f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
        if channel_identity
        else f"{owner_where} AND message_kind = 'channel'"
    )
    selector_params = owner_params + ((channel_identity,) if channel_identity else ())
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, channel_idx, channel_identity, sender_timestamp, text
            FROM messages
            WHERE {selector_where}
              AND from_self = 0
              AND lower(text) LIKE ?
              AND COALESCE(is_mention_read, 0) = 0
            ORDER BY sender_timestamp DESC, id DESC
            LIMIT ?
            """,
            selector_params + (like_pattern, safe_limit),
        ).fetchall()
    return [
        {
            "conversation_kind": "channel",
            "id": int(row["id"] or 0),
            "channel_idx": None if row["channel_idx"] is None else int(row["channel_idx"]),
            "channel_identity": str(row["channel_identity"] or "").strip(),
            "pubkey_prefix": "",
            "sender_timestamp": int(row["sender_timestamp"] or 0),
            "text": str(row["text"] or ""),
        }
        for row in rows
    ]


def _list_contact_unread_mentions(
    mention_name: str,
    limit: int = 100,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> list[dict[str, object]]:
    needle = str(mention_name or "").strip().lower()
    safe_limit = max(1, min(int(limit), 200))
    if not needle:
        return []
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                id,
                pubkey_prefix,
                sender_timestamp,
                text
            FROM contact_messages
            WHERE {owner_where}
              AND from_self = 0
              AND lower(text) LIKE ?
              AND COALESCE(is_mention_read, 0) = 0
            ORDER BY sender_timestamp DESC, id DESC
            LIMIT ?
            """,
            owner_params + (like_pattern, safe_limit),
        ).fetchall()
    return [
        {
            "conversation_kind": "contact",
            "id": int(row["id"] or 0),
            "channel_idx": None,
            "channel_identity": "",
            "pubkey_prefix": "" if row["pubkey_prefix"] is None else str(row["pubkey_prefix"]).lower(),
            "sender_timestamp": int(row["sender_timestamp"] or 0),
            "text": str(row["text"] or ""),
        }
        for row in rows
    ]


def get_contact_message_stats(*, owner_id: str | None = None, access_all: bool | None = None) -> dict[str, dict[str, object]]:
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        stats_rows = conn.execute(
            f"""
            SELECT
                pubkey_prefix,
                COUNT(CASE WHEN from_self = 0 AND COALESCE(is_read, 0) = 0 THEN 1 END) AS unread_count,
                MAX(sender_timestamp) AS last_message_at
            FROM contact_messages
            WHERE {owner_where}
            GROUP BY pubkey_prefix
            """,
            owner_params,
        ).fetchall()
        preview_rows = conn.execute(
            f"""
            SELECT c.pubkey_prefix, c.text, c.from_self, c.sender_timestamp
            FROM contact_messages c
            INNER JOIN (
                SELECT pubkey_prefix, MAX(sender_timestamp) AS max_sender_timestamp
                FROM contact_messages
                WHERE {owner_where}
                GROUP BY pubkey_prefix
            ) latest
              ON latest.pubkey_prefix = c.pubkey_prefix
             AND latest.max_sender_timestamp = c.sender_timestamp
            WHERE {owner_where.replace("owner_id", "c.owner_id")}
            ORDER BY c.id DESC
            """,
            owner_params + owner_params,
        ).fetchall()
    previews: dict[str, dict[str, object]] = {}
    for row in preview_rows:
        prefix = str(row["pubkey_prefix"] or "").lower()
        if not prefix or prefix in previews:
            continue
        previews[prefix] = {
            "last_message_text": str(row["text"] or ""),
            "last_message_from_self": bool(row["from_self"]),
            "last_message_at": int(row["sender_timestamp"] or 0),
        }
    stats: dict[str, dict[str, object]] = {}
    for row in stats_rows:
        prefix = str(row["pubkey_prefix"] or "").lower()
        stats[prefix] = {
            "unread_count": int(row["unread_count"] or 0),
            "last_message_at": int(row["last_message_at"] or 0),
        }
    for prefix, preview in previews.items():
        stats.setdefault(prefix, {})
        stats[prefix].update(preview)
    return stats


def get_contact_unread_counts(*, owner_id: str | None = None, access_all: bool | None = None) -> dict[str, int]:
    stats = get_contact_message_stats(owner_id=owner_id, access_all=access_all)
    return {str(prefix): int(data.get("unread_count") or 0) for prefix, data in stats.items()}


def list_unread_mentions(
    mention_name: str,
    limit: int = 100,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
    port: str | None = None,
) -> list[dict[str, object]]:
    needle = str(mention_name or "").strip().lower()
    safe_limit = max(1, min(int(limit), 200))
    if not needle:
        return []
    like_pattern = f"%{needle}%"
    normalized_port = _normalize_port_value(port)
    if normalized_port:
        owner = _normalize_owner_id(owner_id) or _resolve_owner_id_for_port(normalized_port)
        session = _get_background_session(normalized_port)
        channels = []
        if session:
            with session.snapshot_lock:
                channels = list(session.channels or [])
        if not channels:
            channels = [
                {
                    "idx": int(item.get("channel_idx") or -1),
                    "name": str(item.get("channel_name") or ""),
                    "channel_identity": str(item.get("channel_identity") or ""),
                }
                for item in _list_node_channel_slots(owner)
            ]
        channel_entries: list[dict[str, object]] = []
        seen_channel_ids: set[int] = set()
        for channel in channels:
            try:
                channel_idx = int((channel or {}).get("idx") or -1)
            except (TypeError, ValueError, AttributeError):
                continue
            if channel_idx < 0:
                continue
            with _channel_history_scope(normalized_port, channel_idx, owner_id=owner) as channel_scope:
                resolved_channel_name = _normalize_channel_name(
                    channel_scope.get("channel_name") or (channel or {}).get("name")
                )
                resolved_channel_identity = str(
                    channel_scope.get("channel_identity") or (channel or {}).get("channel_identity") or ""
                ).strip()
                for entry in _list_scoped_channel_unread_mentions(
                    needle,
                    limit=safe_limit,
                    owner_id=channel_scope["owner_id"],
                    access_all=channel_scope["access_all"],
                ):
                    entry_id = int(entry.get("id") or 0)
                    if entry_id <= 0 or entry_id in seen_channel_ids:
                        continue
                    entry["channel_idx"] = channel_idx
                    entry["channel_name"] = resolved_channel_name
                    entry["channel_identity"] = resolved_channel_identity
                    seen_channel_ids.add(entry_id)
                    channel_entries.append(entry)
        contact_entries = _list_contact_unread_mentions(
            needle,
            limit=safe_limit,
            owner_id=owner,
            access_all=False,
        )
        merged = channel_entries + contact_entries
        merged.sort(key=lambda item: (int(item.get("sender_timestamp") or 0), int(item.get("id") or 0)), reverse=True)
        return merged[:safe_limit]
    channel_owner_where, channel_owner_params = _message_owner_clause(owner_id, access_all)
    contact_owner_where, contact_owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                'channel' AS conversation_kind,
                id,
                channel_idx,
                channel_identity,
                NULL AS pubkey_prefix,
                sender_timestamp,
                text
            FROM messages
            WHERE {channel_owner_where}
              AND message_kind = 'channel'
              AND from_self = 0
              AND lower(text) LIKE ?
              AND COALESCE(is_mention_read, 0) = 0
            UNION ALL
            SELECT
                'contact' AS conversation_kind,
                id,
                NULL AS channel_idx,
                NULL AS channel_identity,
                pubkey_prefix,
                sender_timestamp,
                text
            FROM contact_messages
            WHERE {contact_owner_where}
              AND from_self = 0
              AND lower(text) LIKE ?
              AND COALESCE(is_mention_read, 0) = 0
            ORDER BY sender_timestamp DESC, id DESC
            LIMIT ?
            """,
            channel_owner_params + (like_pattern,) + contact_owner_params + (like_pattern, safe_limit),
        ).fetchall()
    return [
        {
            "conversation_kind": str(row["conversation_kind"] or ""),
            "id": int(row["id"] or 0),
            "channel_idx": None if row["channel_idx"] is None else int(row["channel_idx"]),
            "channel_identity": "" if row["channel_identity"] is None else str(row["channel_identity"]).strip(),
            "pubkey_prefix": "" if row["pubkey_prefix"] is None else str(row["pubkey_prefix"]).lower(),
            "sender_timestamp": int(row["sender_timestamp"] or 0),
            "text": str(row["text"] or ""),
        }
        for row in rows
    ]


def get_channel_unread_summary(
    mention_name: str,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, dict[str, int]]:
    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        grouping_column = "channel_identity" if channel_identity else "channel_idx"
        selector_where = (
            f"{owner_where} AND message_kind = 'channel' AND channel_identity = ?"
            if channel_identity
            else f"{owner_where} AND message_kind = 'channel'"
        )
        selector_params = owner_params + ((channel_identity,) if channel_identity else ())
        if needle:
            rows = conn.execute(
                f"""
                SELECT
                    {grouping_column} AS channel_key,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM messages
                WHERE {selector_where}
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                  AND lower(text) NOT LIKE ?
                GROUP BY {grouping_column}
                ORDER BY {grouping_column} ASC
                """,
                selector_params + (like_pattern,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT
                    {grouping_column} AS channel_key,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM messages
                WHERE {selector_where}
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                GROUP BY {grouping_column}
                ORDER BY {grouping_column} ASC
                """,
                selector_params,
            ).fetchall()
    return {
        str(row["channel_key"] if channel_identity else int(row["channel_key"])): {
            "unread_count": int(row["unread_count"] or 0),
            "first_unread_id": int(row["first_unread_id"] or 0),
            "last_unread_id": int(row["last_unread_id"] or 0),
        }
        for row in rows
    }


def get_contact_unread_summary(
    mention_name: str,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, dict[str, int]]:
    needle = str(mention_name or "").strip().lower()
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all)
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if needle:
            rows = conn.execute(
                f"""
                SELECT
                    pubkey_prefix,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM contact_messages
                WHERE {owner_where}
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                  AND lower(text) NOT LIKE ?
                GROUP BY pubkey_prefix
                ORDER BY pubkey_prefix ASC
                """,
                owner_params + (like_pattern,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT
                    pubkey_prefix,
                    COUNT(*) AS unread_count,
                    MIN(id) AS first_unread_id,
                    MAX(id) AS last_unread_id
                FROM contact_messages
                WHERE {owner_where}
                  AND from_self = 0
                  AND COALESCE(is_read, 0) = 0
                GROUP BY pubkey_prefix
                ORDER BY pubkey_prefix ASC
                """,
                owner_params,
            ).fetchall()
    return {
        str(row["pubkey_prefix"] or "").lower(): {
            "unread_count": int(row["unread_count"] or 0),
            "first_unread_id": int(row["first_unread_id"] or 0),
            "last_unread_id": int(row["last_unread_id"] or 0),
        }
        for row in rows
        if str(row["pubkey_prefix"] or "").strip()
    }


def get_channel_mention_summary(
    mention_name: str,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, dict[str, int]]:
    needle = str(mention_name or "").strip().lower()
    if not needle:
        return {}
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all, column="m.owner_id")
    channel_identity = _get_scoped_channel_identity()
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        grouping_column = "m.channel_identity" if channel_identity else "m.channel_idx"
        selector_where = (
            f"{owner_where} AND m.message_kind = 'channel' AND m.channel_identity = ?"
            if channel_identity
            else f"{owner_where} AND m.message_kind = 'channel'"
        )
        selector_params = owner_params + ((channel_identity,) if channel_identity else ())
        rows = conn.execute(
            f"""
            SELECT
                {grouping_column} AS channel_key,
                COUNT(*) AS mention_count,
                MIN(m.id) AS first_mention_id,
                MAX(m.id) AS last_mention_id
            FROM messages m
            WHERE {selector_where}
              AND m.from_self = 0
              AND lower(m.text) LIKE ?
              AND COALESCE(m.is_mention_read, 0) = 0
            GROUP BY {grouping_column}
            ORDER BY {grouping_column} ASC
            """,
            selector_params + (like_pattern,),
        ).fetchall()
    return {
        str(row["channel_key"] if channel_identity else int(row["channel_key"])): {
            "mention_count": int(row["mention_count"] or 0),
            "first_mention_id": int(row["first_mention_id"] or 0),
            "last_mention_id": int(row["last_mention_id"] or 0),
        }
        for row in rows
    }


def get_contact_mention_summary(
    mention_name: str,
    *,
    owner_id: str | None = None,
    access_all: bool | None = None,
) -> dict[str, dict[str, int]]:
    needle = str(mention_name or "").strip().lower()
    if not needle:
        return {}
    like_pattern = f"%{needle}%"
    owner_where, owner_params = _message_owner_clause(owner_id, access_all, column="c.owner_id")
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
                c.pubkey_prefix,
                COUNT(*) AS mention_count,
                MIN(c.id) AS first_mention_id,
                MAX(c.id) AS last_mention_id
            FROM contact_messages c
            WHERE {owner_where}
              AND c.from_self = 0
              AND lower(c.text) LIKE ?
              AND COALESCE(c.is_mention_read, 0) = 0
            GROUP BY c.pubkey_prefix
            ORDER BY c.pubkey_prefix ASC
            """,
            owner_params + (like_pattern,),
        ).fetchall()
    return {
        str(row["pubkey_prefix"] or "").lower(): {
            "mention_count": int(row["mention_count"] or 0),
            "first_mention_id": int(row["first_mention_id"] or 0),
            "last_mention_id": int(row["last_mention_id"] or 0),
        }
        for row in rows
        if str(row["pubkey_prefix"] or "").strip()
    }

def _enrich_contacts_with_local_state(contacts: list[dict]) -> list[dict]:
    stats = get_contact_message_stats()
    groups = get_contact_groups()
    contact_groups_map: dict[str, list[str]] = {}
    for group_name, members in groups.items():
        for public_key in members:
            contact_groups_map.setdefault(public_key, []).append(group_name)
    enriched: list[dict] = []
    for item in contacts:
        contact = dict(item)
        prefix = str(contact.get("public_key") or "").lower()[:12]
        public_key = str(contact.get("public_key") or "").lower()
        local = stats.get(prefix, {})
        contact["pubkey_prefix"] = prefix
        contact["unread_count"] = int(local.get("unread_count") or 0)
        contact["last_message_at"] = int(local.get("last_message_at") or 0)
        contact["last_message_text"] = str(local.get("last_message_text") or "")
        contact["last_message_from_self"] = bool(local.get("last_message_from_self", False))
        contact["is_favorite"] = bool(int(contact.get("flags", 0)) & CONTACT_FLAG_STAR)
        group_tags = sorted(contact_groups_map.get(public_key, []))
        if contact["is_favorite"] and SYSTEM_FAVORITES_GROUP not in group_tags:
            group_tags.append(SYSTEM_FAVORITES_GROUP)
        contact["group_tags"] = sorted(group_tags, key=lambda value: value.lower())
        enriched.append(contact)
    return enriched


CONTACT_BACKEND = ContactBackend(
    db_lock=DB_LOCK,
    db_path=CONTACTS_DB_PATH,
    utc_now_epoch=utc_now_epoch,
    get_contact_timeout_secs=_get_contact_active_timeout_secs,
    get_repeater_timeout_secs=_get_repeater_active_timeout_secs,
    get_preserve_favorites_on_node=_get_contact_residency_preserve_favorites_on_node,
    get_preserve_repeaters_on_node=_get_contact_residency_preserve_repeaters_on_node,
    get_full_table_behavior=_get_contact_full_table_behavior,
    contact_flag_star=CONTACT_FLAG_STAR,
    system_favorites_group=SYSTEM_FAVORITES_GROUP,
    get_contact_message_stats=get_contact_message_stats,
    log_event=_log_contact_debug,
)


def save_outbound_channel_message(
    channel_idx: int,
    text: str,
    expected_ack_hex: str | None = None,
    sender_timestamp: int | None = None,
    *,
    owner_id: str | None = None,
    channel_identity: str | None = None,
    channel_name: str | None = None,
    channel_secret_hex: str | None = None,
) -> dict:
    resolved_sender_timestamp = int(sender_timestamp if sender_timestamp is not None else utc_now_epoch())
    message = {
        "channel_idx": int(channel_idx),
        "channel_identity": str(channel_identity or "").strip(),
        "channel_name": _normalize_channel_name(channel_name),
        "channel_secret_hex": _normalize_channel_secret_hex(channel_secret_hex),
        "from_self": True,
        "send_status": "sent",
        "expected_ack_hex": expected_ack_hex,
        "acked_at": None,
        "sender_timestamp": resolved_sender_timestamp,
        "snr": None,
        "path_len": -1,
        "path_hashes": "",
        "txt_type": 0,
        "text": text,
        "payload_hex": "",
        "is_read": True,
        "is_mention_read": True,
    }
    message["id"] = save_channel_message(message, owner_id=owner_id)
    message["received_at"] = int(time.time())
    return message


def mark_channel_message_repeated(
    channel_idx: int,
    sender_timestamp: int,
    text: str,
    path_len: int,
    path_hashes: str = "",
    full_text: str = "",
    *,
    owner_id: str | None = None,
    channel_identity: str | None = None,
) -> dict | None:
    message_text = str(text or "")
    message_full_text = str(full_text or "")
    if channel_idx < 0 or sender_timestamp <= 0 or (not message_text and not message_full_text):
        return None
    normalized_owner_id, _ = _resolve_owner_scope(owner_id, False)
    if not normalized_owner_id:
        return None
    candidate_texts = [value for value in (message_text, message_full_text) if value]
    normalized_channel_identity = str(channel_identity or "").strip()
    now = int(time.time())
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        placeholders = ", ".join("?" for _ in candidate_texts)
        channel_filter = "channel_identity = ?" if normalized_channel_identity else "channel_idx = ?"
        channel_value = normalized_channel_identity if normalized_channel_identity else int(channel_idx)
        row = conn.execute(
            f"""
            SELECT id, send_status
            FROM messages
            WHERE owner_id = ?
              AND message_kind = 'channel'
              AND {channel_filter}
              AND sender_timestamp = ?
              AND text IN ({placeholders})
            ORDER BY id DESC
            LIMIT 1
            """,
            (normalized_owner_id, channel_value, int(sender_timestamp), *candidate_texts),
        ).fetchone()
        if row is None:
            return None
        current_status = str(row["send_status"] or "")
        should_update_route = int(path_len) >= 0 or bool(str(path_hashes or "").strip())
        if current_status == "delivered" and not should_update_route:
            return {"id": int(row["id"]), "updated": False, "send_status": current_status, "path_hashes": str(path_hashes or "")}
        conn.execute(
            """
            UPDATE messages
            SET send_status = CASE WHEN send_status IN ('sent', 'pending') THEN 'delivered' ELSE send_status END,
                acked_at = CASE
                    WHEN send_status IN ('sent', 'pending') AND acked_at IS NULL THEN ?
                    ELSE acked_at
                END,
                path_len = CASE
                    WHEN ? >= 0 THEN ?
                    ELSE path_len
                END,
                path_hashes = CASE
                    WHEN ? != '' THEN ?
                    ELSE path_hashes
                END
            WHERE id = ?
            """,
            (now, int(path_len), int(path_len), str(path_hashes or ""), str(path_hashes or ""), int(row["id"])),
        )
        conn.commit()
        next_status = "delivered" if current_status in ("sent", "pending") else current_status
    _log_delivery_debug(
        "channel_repeat_db_update",
        channel_idx=channel_idx,
        sender_timestamp=sender_timestamp,
        text=message_text,
        full_text=message_full_text,
        path_len=path_len,
        path_hashes=path_hashes,
        id=int(row["id"]),
        previous_status=current_status,
        next_status=next_status,
    )
    return {
        "id": int(row["id"]),
        "updated": next_status != current_status,
        "send_status": next_status,
        "path_hashes": str(path_hashes or ""),
    }


def save_outbound_contact_message(
    public_key: str,
    text: str,
    expected_ack_hex: str | None = None,
    delivered: bool = False,
    sender_timestamp: int | None = None,
    *,
    owner_id: str | None = None,
) -> dict:
    resolved_sender_timestamp = int(sender_timestamp if sender_timestamp is not None else utc_now_epoch())
    message = {
        "pubkey_prefix": str(public_key).lower()[:12],
        "from_self": True,
        "send_status": "delivered" if delivered or not expected_ack_hex else "sent",
        "expected_ack_hex": expected_ack_hex,
        "acked_at": int(time.time()) if delivered else None,
        "sender_timestamp": resolved_sender_timestamp,
        "snr": None,
        "path_len": -1,
        "path_hashes": "",
        "txt_type": 0,
        "text": text,
        "payload_hex": "",
        "signature_hex": None,
        "is_read": True,
        "is_mention_read": True,
    }
    message["id"] = save_contact_message(message, owner_id=owner_id)
    message["received_at"] = int(time.time())
    return message


def mark_contact_message_delivered_by_ack(ack_hex: str, *, owner_id: str | None = None) -> int:
    code = str(ack_hex or "").lower()
    if not code:
        _log_delivery_debug("ack_ignored_empty")
        return 0
    normalized_owner_id, _ = _resolve_owner_scope(owner_id, False)
    if not normalized_owner_id:
        return 0
    now = int(time.time())
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, expected_ack_hex
            FROM contact_messages
            WHERE owner_id = ? AND expected_ack_hex IS NOT NULL AND from_self = 1
            """,
            (normalized_owner_id,),
        )
        matched_ids = [
            int(row["id"])
            for row in cursor.fetchall()
            if _ack_hexes_match(row["expected_ack_hex"], code)
        ]
        updated = 0
        if matched_ids:
            placeholders = ",".join("?" for _ in matched_ids)
            update_cursor = conn.execute(
                f"""
                UPDATE contact_messages
                SET send_status = 'delivered',
                    acked_at = CASE WHEN acked_at IS NULL THEN ? ELSE acked_at END
                WHERE id IN ({placeholders})
                """,
                (now, *matched_ids),
            )
            conn.commit()
            updated = int(update_cursor.rowcount)
    _log_delivery_debug("ack_db_update", ack_hex=code, updated=updated)
    return updated


def _serialize_trace_info(trace_info, *, round_trip_ms: int | None = None) -> dict:
    return {
        "tag": int(trace_info.tag),
        "auth_code": int(trace_info.auth_code),
        "flags": int(trace_info.flags),
        "path_hash_len": int(trace_info.path_hash_len),
        "path_hops": [
            {
                "hash_hex": None if hop.hash_hex is None else str(hop.hash_hex),
                "snr": None if hop.snr is None else float(hop.snr),
            }
            for hop in list(trace_info.path_hops or [])
        ],
        "final_snr": None if trace_info.final_snr is None else float(trace_info.final_snr),
        "round_trip_ms": None if round_trip_ms is None else int(round_trip_ms),
    }


def _find_live_contact_by_public_key(contacts: list | None, public_key_hex: str):
    target = str(public_key_hex or "").strip().lower()
    if not target:
        return None
    for contact in list(contacts or []):
        current_key = getattr(contact, "public_key", b"")
        if bytes(current_key).hex().lower() == target:
            return contact
    return None


def _build_route_trace_result(
    *,
    route_path_hash_len: int,
    hop_count: int,
    sequential: bool,
    status: str,
    steps: list[dict] | None = None,
    success: bool = False,
    cancelled: bool = False,
    failure_at_hop: int | None = None,
    failure_reason: str | None = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": True,
        "status": str(status or ""),
        "success": bool(success),
        "cancelled": bool(cancelled),
        "route_path_hash_len": int(route_path_hash_len),
        "hop_count": int(hop_count),
        "sequential": bool(sequential),
        "steps": list(steps or []),
        "failure_at_hop": None if failure_at_hop in (None, "") else int(failure_at_hop),
        "failure_reason": None if failure_reason in (None, "") else str(failure_reason),
        "error": None if error in (None, "") else str(error),
    }


def _upsert_route_trace_step(steps: list[dict], step: dict) -> None:
    prefix_hops = int(step.get("prefix_hops") or 0)
    for index, current in enumerate(steps):
        if int(current.get("prefix_hops") or 0) == prefix_hops:
            steps[index] = step
            return
    steps.append(step)
    steps.sort(key=lambda item: int(item.get("prefix_hops") or 0))


def _drop_route_trace_step(steps: list[dict], prefix_hops: int) -> None:
    steps[:] = [item for item in steps if int(item.get("prefix_hops") or 0) != int(prefix_hops)]


def _run_route_trace_job(job: RouteTraceJob) -> None:
    def publish_progress(event_status: str, trace: dict) -> None:
        with ROUTE_TRACE_JOBS_GUARD:
            current = ROUTE_TRACE_JOBS.get(job.job_id)
            if current is not None:
                current.result = _clone_route_trace_payload(trace)
                current.status = str(trace.get("status") or event_status or current.status)
        _broadcast_route_trace_event(job, event_status, trace=trace)

    try:
        if job.cancel_event.is_set():
            cancelled_result = _build_route_trace_result(
                route_path_hash_len=int(job.route_path_hash_len),
                hop_count=len(list(job.selected_public_keys or [])),
                sequential=bool(job.sequential),
                status="cancelled",
                steps=list((job.result or {}).get("steps") or []),
                success=False,
                cancelled=True,
                failure_reason=str(job.cancel_reason or "cancelled"),
            )
            _broadcast_route_trace_event(job, "cancelled", trace=cancelled_result, reason=str(job.cancel_reason or "cancelled"))
            return
        session = _get_background_session(job.port)
        if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
            result = _run_command_via_background_session(
                job.port,
                {
                    "kind": "trace_route",
                    "selected_public_keys": list(job.selected_public_keys),
                    "route_path_hash_len": int(job.route_path_hash_len),
                    "sequential": bool(job.sequential),
                    "cancel_event": job.cancel_event,
                    "progress_callback": publish_progress,
                },
                timeout_secs=120.0,
            )
        else:
            with _paused_background_session(job.port):
                with _open_meshcore_client(job.conn_kwargs) as client:
                    client.query_device(DEFAULT_PROTOCOL_VERSION)
                    client.app_start(DEFAULT_APP_NAME, DEFAULT_APP_VERSION)
                    live_contacts = client.get_contacts()[1]
                    result = _run_route_probe_with_client(
                        client,
                        live_contacts=live_contacts,
                        selected_public_keys=list(job.selected_public_keys),
                        route_path_hash_len=int(job.route_path_hash_len),
                        sequential=bool(job.sequential),
                        cancel_event=job.cancel_event,
                        progress_callback=publish_progress,
                    )
        with ROUTE_TRACE_JOBS_GUARD:
            current = ROUTE_TRACE_JOBS.get(job.job_id)
            if current is not None:
                current.result = _clone_route_trace_payload(result)
                current.status = str(result.get("status") or current.status)
        if result.get("cancelled"):
            _broadcast_route_trace_event(
                job,
                "cancelled",
                trace=result,
                reason=str(result.get("failure_reason") or job.cancel_reason or "cancelled"),
            )
            return
        _broadcast_route_trace_event(job, "completed", trace=result)
    except Exception as exc:
        failure_result = _build_route_trace_result(
            route_path_hash_len=int(job.route_path_hash_len),
            hop_count=len(list(job.selected_public_keys or [])),
            sequential=bool(job.sequential),
            status="cancelled" if job.cancel_event.is_set() else "error",
            steps=list((job.result or {}).get("steps") or []),
            success=False,
            cancelled=bool(job.cancel_event.is_set()),
            failure_reason="cancelled" if job.cancel_event.is_set() else "trace-error",
            error=str(exc),
        )
        with ROUTE_TRACE_JOBS_GUARD:
            current = ROUTE_TRACE_JOBS.get(job.job_id)
            if current is not None:
                current.result = _clone_route_trace_payload(failure_result)
                current.status = "cancelled" if job.cancel_event.is_set() else "error"
        _broadcast_route_trace_event(
            job,
            "cancelled" if job.cancel_event.is_set() else "error",
            trace=failure_result,
            message=str(exc),
            reason=str(job.cancel_reason or "cancelled" if job.cancel_event.is_set() else ""),
        )
    finally:
        _discard_route_trace_job(job.job_id, expected=job)


def _start_route_trace_job(
    *,
    port: str,
    conn_kwargs: dict,
    selected_public_keys: list[str],
    route_path_hash_len: int,
    sequential: bool,
) -> RouteTraceJob:
    normalized_port = str(port or "")
    job = RouteTraceJob(
        job_id=secrets.token_hex(12),
        port=normalized_port,
        conn_kwargs=dict(conn_kwargs),
        selected_public_keys=list(selected_public_keys),
        route_path_hash_len=int(route_path_hash_len),
        sequential=bool(sequential),
        result=_build_route_trace_result(
            route_path_hash_len=int(route_path_hash_len),
            hop_count=len(list(selected_public_keys or [])),
            sequential=bool(sequential),
            status="queued",
            steps=[],
        ),
    )
    _cancel_route_trace_jobs_for_port(normalized_port, reason="superseded", except_job_id=job.job_id)
    _register_route_trace_job(job)
    thread = threading.Thread(
        target=_run_route_trace_job,
        args=(job,),
        name=f"meshcorium-route-trace-{normalized_port}",
        daemon=True,
    )
    job.thread = thread
    thread.start()
    return job


def _run_route_probe_with_client(
    client: MeshCoreSerialClient,
    *,
    live_contacts: list | None,
    selected_public_keys: list[str],
    route_path_hash_len: int,
    sequential: bool,
    cancel_event: threading.Event | None = None,
    progress_callback=None,
) -> dict:
    selected_keys = [str(item or "").strip().lower() for item in list(selected_public_keys or []) if str(item or "").strip()]
    if not selected_keys:
        raise MeshCoreError("selected_public_keys is required for route probe")
    if route_path_hash_len not in (1, 2, 4, 8):
        raise MeshCoreError("route_path_hash_len must be one of 1, 2, 4, 8")
    hop_count = len(selected_keys)
    result = _build_route_trace_result(
        route_path_hash_len=int(route_path_hash_len),
        hop_count=int(hop_count),
        sequential=bool(sequential),
        status="running",
        steps=[],
    )
    probe_targets = list(range(1, hop_count + 1)) if sequential else [hop_count]
    previous_round_trip_ms: int | None = None
    last_probe_succeeded = False
    first_failed_hop: int | None = None

    def publish(event_status: str) -> None:
        if progress_callback is None:
            return
        progress_callback(str(event_status), _clone_route_trace_payload(result))

    def cancellation_result(reason: str) -> dict:
        nonlocal result
        result = {
            **result,
            "status": "cancelled",
            "success": False,
            "cancelled": True,
            "failure_reason": str(reason or "cancelled"),
            "failure_at_hop": None if first_failed_hop is None else int(first_failed_hop),
        }
        return result

    _log_route_trace_debug(
        "route_probe_start",
        selected_public_keys=selected_keys,
        route_path_hash_len=int(route_path_hash_len),
        sequential=bool(sequential),
        hop_count=int(hop_count),
        live_contact_count=0 if live_contacts is None else len(list(live_contacts)),
    )
    publish("started")
    for prefix_hops in probe_targets:
        if cancel_event is not None and cancel_event.is_set():
            return cancellation_result(str(getattr(cancel_event, "reason", "") or "cancelled"))
        path_hex = "".join(
            key[: route_path_hash_len * 2]
            for key in selected_keys[:prefix_hops]
        ).lower()
        path_bytes = bytes.fromhex(path_hex) if path_hex else b""
        if not path_bytes:
            _log_route_trace_debug(
                "route_probe_empty_path",
                prefix_hops=int(prefix_hops),
                path_hex=path_hex,
            )
            if first_failed_hop is None:
                first_failed_hop = prefix_hops
            step_result = {
                "prefix_hops": int(prefix_hops),
                "pending": False,
                "success": False,
                "segment_ms_estimate": None,
                "trace": None,
            }
            _upsert_route_trace_step(result["steps"], step_result)
            publish("progress")
            if not sequential:
                break
            continue
        pending_step = {
            "prefix_hops": int(prefix_hops),
            "pending": True,
            "success": False,
            "segment_ms_estimate": None,
            "trace": None,
        }
        _upsert_route_trace_step(result["steps"], pending_step)
        publish("progress")
        started = time.monotonic()
        try:
            send_timeout_secs = max(3.0, min(6.0, float(getattr(client.serial, "timeout", 0.0) or 0.0) * 12.0))
            with client.temporary_serial_timeout(send_timeout_secs):
                sent, trace_info = client.send_trace_path_probe(
                    path_bytes,
                    path_hash_len=route_path_hash_len,
                    timeout_secs=send_timeout_secs,
                    cancel_event=cancel_event,
                )
            if cancel_event is not None and cancel_event.is_set():
                _drop_route_trace_step(result["steps"], prefix_hops)
                return cancellation_result("cancelled")
            hop_timeout_secs = 4.5
            suggested_timeout_ms = int(sent.suggested_timeout_ms) if sent is not None else max(
                2500,
                int(prefix_hops) * 1500,
            )
            trace_tag = int(trace_info.tag) if trace_info is not None else int.from_bytes(sent.expected_ack, byteorder="little", signed=False)
            timeout_secs = max(
                12.0,
                min(
                    (float(suggested_timeout_ms) / 1000.0) * 1.5 + (prefix_hops * hop_timeout_secs),
                    75.0,
                ),
            )
            _log_route_trace_debug(
                "route_probe_sent",
                prefix_hops=int(prefix_hops),
                path_hex=path_hex,
                path_hash_len=int(route_path_hash_len),
                path_byte_len=len(path_bytes),
                expected_ack_hex=(sent.expected_ack.hex() if sent is not None else trace_tag.to_bytes(4, byteorder="little", signed=False).hex()),
                trace_tag=int(trace_tag),
                suggested_timeout_ms=int(suggested_timeout_ms),
                send_timeout_secs=float(send_timeout_secs),
                wait_timeout_secs=float(timeout_secs),
                route_flag=(int(sent.route_flag) if sent is not None else None),
                trace_data_arrived_before_resp_sent=bool(trace_info is not None and sent is None),
            )
            if trace_info is None:
                trace_info = client.wait_for_trace_data(
                    trace_tag,
                    timeout_secs,
                    cancel_event=cancel_event,
                )
            if cancel_event is not None and cancel_event.is_set():
                _drop_route_trace_step(result["steps"], prefix_hops)
                return cancellation_result("cancelled")
            round_trip_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
            success = trace_info is not None
            if success:
                segment_ms = round_trip_ms if previous_round_trip_ms is None else max(0, round_trip_ms - previous_round_trip_ms)
                previous_round_trip_ms = round_trip_ms
                last_probe_succeeded = prefix_hops == hop_count
            else:
                segment_ms = None
                if first_failed_hop is None:
                    first_failed_hop = prefix_hops
            serialized_trace = None if trace_info is None else _serialize_trace_info(trace_info, round_trip_ms=round_trip_ms)
            _log_route_trace_debug(
                "route_probe_result",
                prefix_hops=int(prefix_hops),
                success=bool(success),
                round_trip_ms=int(round_trip_ms),
                segment_ms_estimate=None if segment_ms is None else int(segment_ms),
                trace=serialized_trace,
            )
            step_result = {
                "prefix_hops": int(prefix_hops),
                "pending": False,
                "success": bool(success),
                "segment_ms_estimate": None if segment_ms is None else int(segment_ms),
                "trace": serialized_trace,
            }
            _upsert_route_trace_step(result["steps"], step_result)
            publish("progress")
            if not sequential and not success:
                break
        except Exception as exc:
            round_trip_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
            if cancel_event is not None and cancel_event.is_set():
                _drop_route_trace_step(result["steps"], prefix_hops)
                return cancellation_result("cancelled")
            if first_failed_hop is None:
                first_failed_hop = prefix_hops
            _log_route_trace_debug(
                "route_probe_error",
                prefix_hops=int(prefix_hops),
                path_hex=path_hex,
                round_trip_ms=int(round_trip_ms),
                error=str(exc),
            )
            step_result = {
                "prefix_hops": int(prefix_hops),
                "pending": False,
                "success": False,
                "segment_ms_estimate": None,
                "trace": None,
            }
            _upsert_route_trace_step(result["steps"], step_result)
            publish("progress")
            if not sequential:
                break
    _log_route_trace_debug(
        "route_probe_finish",
        success=bool(last_probe_succeeded),
        failure_at_hop=None if last_probe_succeeded else int(first_failed_hop or hop_count),
        step_count=len(list(result["steps"])),
    )
    result = {
        **result,
        "status": "completed",
        "success": bool(last_probe_succeeded),
        "cancelled": False,
        "failure_at_hop": None if last_probe_succeeded else int(first_failed_hop or hop_count),
        "failure_reason": None if last_probe_succeeded else "trace-timeout",
        "error": None,
    }
    return result



def _json_default(value):
    if isinstance(value, bytes):
        return format_hex(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value)!r}")


def _as_dict(obj):
    return json.loads(json.dumps(obj, default=_json_default))


def _device_info_to_dict(device):
    reported_max_contacts = device.max_contacts_div_2 * 2
    return {
        "firmware_ver": device.firmware_ver,
        "max_contacts": reported_max_contacts,
        "max_contacts_base": reported_max_contacts,
        "max_contacts_reported": reported_max_contacts,
        "max_contacts_policy_non_favorite_limit": BASE_NODE_NON_FAVORITE_CONTACT_LIMIT,
        "max_channels": device.max_channels,
        "ble_pin": device.ble_pin,
        "firmware_build_date": device.firmware_build_date,
        "manufacturer_model": device.manufacturer_model,
        "semantic_version": device.semantic_version,
        "client_repeat": int(getattr(device, "client_repeat", 0) or 0),
        "path_hash_mode": int(getattr(device, "path_hash_mode", 0) or 0),
    }


def _self_info_to_dict(info):
    return {
        "name": info.name,
        "public_key": format_hex(info.public_key),
        "adv_type": info.adv_type,
        "tx_power_dbm": info.tx_power_dbm,
        "max_tx_power": info.max_tx_power,
        "lat": format_latlon(info.adv_lat),
        "lon": format_latlon(info.adv_lon),
        "multi_acks": info.multi_acks,
        "advert_loc_policy": info.advert_loc_policy,
        "telemetry_modes": info.telemetry_modes,
        "manual_add_contacts": info.manual_add_contacts,
        "radio_freq_hz_x1000": info.radio_freq,
        "radio_bw_hz_x1000": info.radio_bw,
        "radio_sf": info.radio_sf,
        "radio_cr": info.radio_cr,
    }


def _self_telemetry_to_dict(telemetry):
    return {
        "public_key_prefix": telemetry.public_key_prefix,
        "battery_mv": telemetry.battery_mv,
        "battery_percent": telemetry.battery_percent,
        "voltage": telemetry.voltage,
        "raw_hex": telemetry.raw_hex,
    }


def _battery_info_to_dict(info):
    return {
        "level": info.level,
        "used_kb": info.used_kb,
        "total_kb": info.total_kb,
    }


def _core_stats_to_dict(stats) -> dict:
    return {
        "battery_mv": stats.battery_mv,
        "uptime_secs": stats.uptime_secs,
        "errors": stats.errors,
        "queue_len": stats.queue_len,
    }


def _freeze_self_contact_if_cached(self_info: dict | None) -> None:
    public_key = str((self_info or {}).get("public_key") or "").strip().lower()
    if len(public_key) != 64:
        return
    with _contact_owner_scope(owner_id=public_key, access_all=False):
        CONTACT_BACKEND.mark_cached_contact_as_local_self(public_key)


def _radio_stats_to_dict(stats) -> dict:
    return {
        "noise_floor": stats.noise_floor,
        "last_rssi": stats.last_rssi,
        "last_snr": stats.last_snr,
        "tx_air_secs": stats.tx_air_secs,
        "rx_air_secs": stats.rx_air_secs,
    }


def _packet_stats_to_dict(stats) -> dict:
    return {
        "received": stats.received,
        "sent": stats.sent,
        "sent_flood": stats.sent_flood,
        "sent_direct": stats.sent_direct,
        "recv_flood": stats.recv_flood,
        "recv_direct": stats.recv_direct,
        "recv_errors": stats.recv_errors,
    }


def _signed_byte(value: int) -> int:
    return value if value < 128 else value - 256


def _parse_raw_advert(frame: bytes) -> dict | None:
    if len(frame) < 4:
        return None
    snr = _signed_byte(frame[1]) / 4.0
    rssi = _signed_byte(frame[2])
    payload = frame[3:]
    if len(payload) < 3:
        return None

    header = payload[0]
    payload_type = (header & 0x3C) >> 2
    offset = 1
    route_type = header & 0x03
    if route_type in (0x00, 0x03):
        if len(payload) < offset + 4:
            return None
        offset += 4
    if len(payload) < offset + 1:
        return None
    path_byte = payload[offset]
    offset += 1
    path_hash_size = ((path_byte & 0xC0) >> 6) + 1
    path_len = path_byte & 0x3F
    path_size = path_len * path_hash_size
    if len(payload) < offset + path_size:
        return None
    path_bytes = payload[offset:offset + path_size]
    offset += path_size
    pkt_payload = payload[offset:]

    if payload_type != 0x04 or len(pkt_payload) < 32 + 4 + 64 + 1:
        return None

    adv_key = pkt_payload[:32].hex()
    flags = pkt_payload[100]
    adv_type = flags & 0x0F
    adv_name = ""
    if flags & 0x80:
        name_offset = 101
        if flags & 0x10:
            name_offset += 8
        if flags & 0x20:
            name_offset += 2
        if flags & 0x40:
            name_offset += 2
        if len(pkt_payload) > name_offset:
            adv_name = pkt_payload[name_offset:].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    return {
        "public_key": adv_key,
        "adv_type": adv_type,
        "adv_name": adv_name,
        "snr": snr,
        "rssi": rssi,
        "path_len": path_len,
        "path_hashes": _format_path_hashes(path_bytes, path_hash_size),
    }


def _decode_path_byte_len(path_len_raw: int) -> int:
    hash_size = ((path_len_raw & 0xC0) >> 6) + 1
    hash_count = path_len_raw & 0x3F
    return hash_size * hash_count


def _format_path_hashes(path_bytes: bytes, hash_size: int = 1) -> str:
    safe_hash_size = max(1, int(hash_size))
    if not path_bytes:
        return ""
    hops: list[str] = []
    for offset in range(0, len(path_bytes), safe_hash_size):
        chunk = path_bytes[offset:offset + safe_hash_size]
        if len(chunk) != safe_hash_size:
            break
        hops.append(chunk.hex().upper())
    return " -> ".join(hops)


def _aes_ecb_decrypt(key16: bytes, cipher_text: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key16), modes.ECB(), backend=default_backend()).decryptor()
    return decryptor.update(cipher_text) + decryptor.finalize()


def _decrypt_group_payload(psk: bytes, encrypted: bytes) -> bytes | None:
    if len(encrypted) <= 2:
        return None
    mac = encrypted[:2]
    cipher_text = encrypted[2:]
    key32 = bytes(psk[:32]).ljust(32, b"\x00")
    digest = hmac.new(key32, cipher_text, hashlib.sha256).digest()
    if digest[:2] != mac:
        return None
    if not cipher_text or len(cipher_text) % 16 != 0:
        return None
    key16 = bytes(psk[:16]).ljust(16, b"\x00")
    return _aes_ecb_decrypt(key16, cipher_text)


def _split_channel_sender_text(text: str) -> tuple[str, str]:
    colon_idx = text.find(":")
    if 0 < colon_idx < min(len(text) - 1, 50):
        sender = text[:colon_idx].strip()
        body = text[colon_idx + 1:].lstrip()
        if sender and ":" not in sender and "[" not in sender and "]" not in sender:
            return sender, body
    return "Unknown", text


def _parse_log_rx_group_text(frame: bytes, channels: list[dict]) -> dict | None:
    if len(frame) < 7:
        return None
    snr = _signed_byte(frame[1]) / 4.0
    rssi = _signed_byte(frame[2])
    raw = frame[3:]
    if len(raw) < 3:
        return None
    header = raw[0]
    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F
    if payload_type != 0x05:
        return None
    offset = 1
    if route_type in (0x00, 0x03):
        if len(raw) < offset + 4:
            return None
        offset += 4
    if len(raw) <= offset:
        return None
    path_len_raw = raw[offset]
    offset += 1
    path_hash_size = ((path_len_raw & 0xC0) >> 6) + 1
    path_hop_count = path_len_raw & 0x3F
    path_byte_len = _decode_path_byte_len(path_len_raw)
    if len(raw) < offset + path_byte_len:
        return None
    path_bytes = raw[offset:offset + path_byte_len]
    offset += path_byte_len
    payload = raw[offset:]
    if len(payload) <= 3:
        return None
    channel_hash = payload[0]
    encrypted = payload[1:]
    for channel in channels:
        secret_hex = str(channel.get("secret_hex") or "").strip().lower()
        if len(secret_hex) != 32:
            continue
        try:
            psk = bytes.fromhex(secret_hex)
        except ValueError:
            continue
        if hashlib.sha256(psk).digest()[0] != channel_hash:
            continue
        decrypted = _decrypt_group_payload(psk, encrypted)
        if decrypted is None or len(decrypted) < 6:
            continue
        txt_type = decrypted[4]
        if (txt_type >> 2) != 0:
            continue
        timestamp = int.from_bytes(decrypted[0:4], byteorder="little", signed=False)
        full_text = decrypted[5:].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        sender_name, body = _split_channel_sender_text(full_text)
        return {
            "channel_idx": int(channel.get("idx", -1)),
            "channel_name": _normalize_channel_name(channel.get("name")),
            "channel_identity": str(channel.get("channel_identity") or _build_channel_identity(channel.get("name"), secret_hex)).strip(),
            "channel_secret_hex": secret_hex,
            "channel_hash": f"{channel_hash:02x}",
            "sender_name": sender_name,
            "text": body,
            "full_text": full_text,
            "sender_timestamp": timestamp,
            "txt_type": txt_type,
            "snr": snr,
            "rssi": rssi,
            "path_len": path_hop_count,
            "path_hashes": _format_path_hashes(path_bytes, path_hash_size),
            "raw_hex": raw.hex(),
        }
    return None


def _channel_to_dict(channel, preview: dict | None = None) -> dict:
    name = channel.channel_name.strip()
    secret_hex = format_hex(channel.channel_secret)
    return {
        "idx": channel.channel_idx,
        "name": name,
        "description": "Channel configuration read from the node.",
        "secret_hex": secret_hex,
        "hash": channel.channel_hash,
        "channel_identity": _build_channel_identity(name, secret_hex),
        "is_public": _is_public_channel_name(name),
        "kind": "configured",
        "last_message_preview": (preview or {}).get("text", ""),
        "last_message_from_self": bool((preview or {}).get("from_self", False)),
        "last_message_ts": int((preview or {}).get("sender_timestamp", 0) or 0),
    }


def _channels_to_dict(
    channels: list,
    device: dict,
    *,
    owner_id: str | None = None,
    access_all: bool = False,
) -> list[dict]:
    previews = get_channel_message_previews(owner_id=owner_id, access_all=access_all)
    channel_dicts = [
        _channel_to_dict(
            channel,
            previews.get(_build_channel_identity(channel.channel_name, format_hex(channel.channel_secret)))
            or previews.get(f"idx::{int(channel.channel_idx)}")
            or previews.get(str(int(channel.channel_idx))),
        )
        for channel in sorted(channels, key=lambda item: item.channel_idx)
        if channel.channel_name.strip()
    ]
    _persist_node_channel_slots(owner_id, channel_dicts)
    return channel_dicts


def _decode_channel_secret(secret_hex: object) -> bytes | None:
    value = str(secret_hex or "").strip().lower()
    if not value:
        return None
    if len(value) != 32:
        raise ValueError("channel secret must be exactly 32 hex chars")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("channel secret must be valid hex") from exc


def _pick_first_free_channel_idx(channels: list, max_channels: int) -> int:
    used = {int(channel.channel_idx) for channel in channels if str(channel.channel_name or "").strip()}
    for idx in range(1, max(0, int(max_channels))):
        if idx not in used:
            return idx
    raise ValueError("no free channel slots available")


def _save_channel_and_reload_with_standalone_client(
    client: MeshCoreSerialClient,
    *,
    protocol_version: int,
    app_version: int,
    app_name: str,
    channel_idx: int | None,
    channel_name: str,
    channel_secret_hex: object,
) -> tuple[dict, list[dict]]:
    normalized_channel_name = _normalize_meshcore_channel_name(channel_name)
    resolved_channel_secret_hex = _resolve_channel_secret_hex_for_save(normalized_channel_name, channel_secret_hex)
    secret = _decode_channel_secret(resolved_channel_secret_hex)
    device = client.query_device(protocol_version)
    self_info = client.app_start(app_name, app_version)
    owner_id = _normalize_owner_id(getattr(self_info, "public_key", ""))
    existing_channels = _load_channels_in_session(client, int(device.max_channels), owner_id=owner_id)
    target_idx = int(channel_idx) if channel_idx is not None else _pick_first_free_channel_idx(existing_channels, device.max_channels)
    existing_channel = next((item for item in existing_channels if _channel_runtime_idx(item) == target_idx), None)
    _guard_meshcore_public_channel_edit(existing_channel, normalized_channel_name, resolved_channel_secret_hex)
    client.set_channel(target_idx, normalized_channel_name, secret)
    channels = _load_channels_in_session(client, int(device.max_channels), owner_id=owner_id)
    channel = next(
        (
            item
            for item in channels
            if int(item.channel_idx) == target_idx
        ),
        None,
    )
    if channel is None:
        channel = next(
            (
                item
                for item in existing_channels
                if int(item.channel_idx) == target_idx
            ),
            None,
        )
    device_dict = _device_info_to_dict(device)
    if channel is None:
        return (
            {
                "idx": target_idx,
                "name": normalized_channel_name,
                "description": "Channel configuration read from the node.",
                "secret_hex": resolved_channel_secret_hex,
                "hash": hashlib.sha256(bytes(secret or b"")).hexdigest()[:2] if secret else "",
                "kind": "configured",
                "last_message_preview": "",
                "last_message_from_self": False,
                "last_message_ts": 0,
            },
            _channels_to_dict(
                channels,
                device_dict,
                owner_id=owner_id,
                access_all=False,
            ),
        )
    return (
        _channel_to_dict(channel),
        _channels_to_dict(
            channels,
            device_dict,
            owner_id=owner_id,
            access_all=False,
        ),
    )


def _save_channel_and_reload(session_kwargs: dict, channel_idx: int | None, channel_name: str, channel_secret_hex: object) -> tuple[dict, list[dict]]:
    with _connection_access_from_kwargs(session_kwargs):
        with _open_meshcore_client(session_kwargs) as client:
            return _save_channel_and_reload_with_standalone_client(
                client,
                protocol_version=session_kwargs["protocol_version"],
                app_version=session_kwargs["app_version"],
                app_name=session_kwargs["app_name"],
                channel_idx=channel_idx,
                channel_name=channel_name,
                channel_secret_hex=channel_secret_hex,
            )


def _pick_first_free_channel_idx_from_dicts(channels: list[dict], max_channels: int) -> int:
    used = {
        int(channel.get("idx") or -1)
        for channel in list(channels or [])
        if str(channel.get("name") or "").strip()
    }
    for idx in range(1, max(0, int(max_channels))):
        if idx not in used:
            return idx
    raise ValueError("no free channel slots available")


def _save_channel_and_reload_with_client(
    client: MeshCoreSerialClient,
    session: BackgroundCompanionSession,
    channel_idx: int | None,
    channel_name: str,
    channel_secret_hex: object,
) -> tuple[dict, list[dict]]:
    normalized_channel_name = _normalize_meshcore_channel_name(channel_name)
    resolved_channel_secret_hex = _resolve_channel_secret_hex_for_save(normalized_channel_name, channel_secret_hex)
    secret = _decode_channel_secret(resolved_channel_secret_hex)
    owner_id = _normalize_owner_id((session.self_info or {}).get("public_key"))
    max_channels = int((session.device or {}).get("max_channels") or 0)
    existing_channels = _load_channels_in_session(client, max_channels, owner_id=owner_id) if max_channels > 0 else list(session.channels or [])
    target_idx = (
        int(channel_idx)
        if channel_idx is not None
        else _pick_first_free_channel_idx_from_dicts(existing_channels, max_channels)
    )
    existing_channel = next((item for item in existing_channels if _channel_runtime_idx(item) == target_idx), None)
    _guard_meshcore_public_channel_edit(existing_channel, normalized_channel_name, resolved_channel_secret_hex)
    client.set_channel(target_idx, normalized_channel_name, secret)
    channels_dict = _load_channels_in_session(client, max_channels, owner_id=owner_id) if max_channels > 0 else list(session.channels or [])
    channel_dict = next(
        (
            dict(item)
            for item in channels_dict
            if int(item.get("idx") or -1) == target_idx
        ),
        {
            "idx": target_idx,
            "name": normalized_channel_name,
            "description": "Channel configuration read from the node.",
            "secret_hex": resolved_channel_secret_hex,
            "hash": hashlib.sha256(bytes(secret or b"")).hexdigest()[:2] if secret else "",
            "kind": "configured",
            "last_message_preview": "",
            "last_message_from_self": False,
            "last_message_ts": 0,
        },
    )
    return channel_dict, channels_dict


def _load_channels_snapshot_with_client(
    client: MeshCoreSerialClient,
    *,
    protocol_version: int,
    app_version: int,
    app_name: str,
) -> tuple[dict, list[dict]]:
    device = client.query_device(protocol_version)
    self_info = client.app_start(app_name, app_version)
    owner_id = _normalize_owner_id(getattr(self_info, "public_key", ""))
    device_dict = _device_info_to_dict(device)
    channels_dict = _load_channels_in_session(client, int(device.max_channels), owner_id=owner_id)
    return device_dict, channels_dict


def _validate_message_body(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned.strip():
        raise ValueError("message text is empty")
    size = len(cleaned.encode("utf-8"))
    if size > MESSAGE_BODY_MAX_BYTES:
        raise ValueError(f"message text is too large: {size} bytes, max {MESSAGE_BODY_MAX_BYTES}")
    return cleaned


class MeshcoriumWebHandler(BaseHTTPRequestHandler):
    server_version = "MeshcoriumWeb/0.1"

    def _write_response_body(self, payload: bytes) -> bool:
        try:
            self.wfile.write(payload)
            return True
        except (BrokenPipeError, ConnectionResetError):
            logging.info("client disconnected during response path=%s", self.path)
            return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if self._handle_auth_guard(parsed, "GET"):
            return
        if self._is_vue_spa_path(parsed.path):
            self._send_connect_app_index()
            return
        legacy_redirect = self._legacy_redirect_path(parsed.path)
        if legacy_redirect:
            redirect_target = legacy_redirect
            if parsed.query:
                redirect_target = f"{redirect_target}?{parsed.query}"
            self._send_redirect(redirect_target)
            return
        if parsed.path == "/login":
            params = parse_qs(parsed.query)
            next_path = str(params.get("next", ["/"])[0] or "/")
            settings = _get_client_settings()
            self._send_html(_build_login_html(next_path, username=str(settings.get("auth_username") or "")))
            return
        if parsed.path.startswith("/connect-app/"):
            self._send_connect_app_file(parsed.path.removeprefix("/connect-app/"))
            return
        if parsed.path.startswith("/icons/"):
            self._send_icon_file(parsed.path.removeprefix("/icons/"))
            return
        if parsed.path.startswith("/sounds/"):
            self._send_sound_file(parsed.path.removeprefix("/sounds/"))
            return
        if parsed.path.startswith("/wallpappers/"):
            self._send_wallpaper_file(parsed.path.removeprefix("/wallpappers/"))
            return
        if parsed.path.startswith("/vendor/"):
            self._send_vendor_file(parsed.path.removeprefix("/vendor/"))
            return
        if parsed.path == "/api/ports":
            self._send_json({"ports": DEFAULT_CONNECTION_ROUTER.discover()})
            return
        if parsed.path == "/api/transports":
            params = parse_qs(parsed.query)
            requested_type = str(params.get("type", ["all"])[0] or "all").strip().lower()
            adapter_id = str(params.get("adapter_id", [""])[0] or "").strip()
            try:
                ble_timeout = max(1.0, min(15.0, float(params.get("timeout", ["5"])[0] or 5.0)))
            except (TypeError, ValueError):
                ble_timeout = 5.0
            valid_types = {"all", "serial", BLE_TRANSPORT_TYPE}
            if requested_type not in valid_types:
                self._send_json(
                    {"error": f"unsupported transport type: {requested_type}"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            transports = []
            if requested_type in {"all", "serial"}:
                transports.append(
                    {
                        "transport_type": "serial",
                        "available": True,
                        "connections": DEFAULT_CONNECTION_ROUTER.discover("serial"),
                    }
                )
            if requested_type in {"all", BLE_TRANSPORT_TYPE}:
                try:
                    ble_connections = DEFAULT_CONNECTION_ROUTER.discover(
                        BLE_TRANSPORT_TYPE,
                        timeout=ble_timeout,
                        adapter_id=adapter_id,
                    )
                    transports.append(
                        {
                            "transport_type": BLE_TRANSPORT_TYPE,
                            "available": True,
                            "connections": ble_connections,
                            "adapter_id": adapter_id,
                        }
                    )
                except BleTransportUnavailable as exc:
                    error_message = str(exc) or exc.__class__.__name__
                    transports.append(
                        {
                            "transport_type": BLE_TRANSPORT_TYPE,
                            "available": False,
                            "connections": [],
                            "adapter_id": adapter_id,
                            "error": error_message,
                            "diagnostics": _build_ble_transport_diagnostics(error_message),
                        }
                    )
            self._send_json({"transports": transports})
            return
        if parsed.path == "/api/contact-groups":
            params = parse_qs(parsed.query)
            self._send_json(
                _build_contact_groups_payload_for_scope(
                    port=params.get("port", [""])[0],
                    baudrate=params.get("baudrate", [""])[0],
                )
            )
            return
        if parsed.path == "/api/client-settings":
            self._send_json(_build_client_settings_payload())
            return
        if parsed.path == "/api/mobile-push/status":
            self._send_json(build_mobile_push_status(PROJECT_ROOT, DB_LOCK, CONTACTS_DB_PATH))
            return
        if parsed.path == "/api/contact-debug":
            params = parse_qs(parsed.query)
            self._send_json(
                _build_contact_debug_payload(
                    params.get("port", [""])[0],
                    params.get("public_key", [""])[0],
                )
            )
            return
        if parsed.path == "/api/signal-metrics":
            params = parse_qs(parsed.query)
            raw_range_seconds = params.get("range_seconds", [""])[0]
            port = params.get("port", [""])[0]
            range_seconds = None if raw_range_seconds in ("", None) else int(raw_range_seconds)
            with _contact_owner_scope(port=port):
                self._send_json(get_signal_metrics_chart(range_seconds))
            return
        if parsed.path == "/api/session":
            params = parse_qs(parsed.query)
            port = params.get("port", [""])[0]
            light = params.get("light", [""])[0] in {"1", "true", "yes"}
            if not port:
                self._send_json({"active": False})
                return
            session = _get_background_session(port)
            if not session:
                self._send_json({"active": False})
                return
            self._send_json(
                _build_session_snapshot(
                    session,
                    include_contacts=not light,
                    include_channels=not light,
                )
            )
            return
        if parsed.path == "/api/messages/channel":
            params = parse_qs(parsed.query)
            channel_idx = int(params.get("channel_idx", ["0"])[0])
            limit = int(params.get("limit", ["200"])[0])
            port = params.get("port", [""])[0]
            raw_anchor = params.get("anchor_message_id", [""])[0]
            anchor_message_id = None if raw_anchor in ("", None) else int(raw_anchor)
            raw_before = params.get("before_message_id", [""])[0]
            before_message_id = None if raw_before in ("", None) else int(raw_before)
            with _channel_history_scope(port, channel_idx):
                self._send_json({
                    "messages": list_channel_messages(channel_idx, limit, anchor_message_id=anchor_message_id, before_message_id=before_message_id),
                    "total_count": get_channel_message_count(channel_idx),
                    "sent_history": get_channel_unique_outgoing_texts(channel_idx, 20),
                })
            return
        if parsed.path == "/api/messages/contact":
            params = parse_qs(parsed.query)
            public_key = params.get("public_key", [""])[0]
            if not public_key:
                self._send_json({"error": "public_key is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            limit = int(params.get("limit", ["200"])[0])
            port = params.get("port", [""])[0]
            raw_anchor = params.get("anchor_message_id", [""])[0]
            anchor_message_id = None if raw_anchor in ("", None) else int(raw_anchor)
            raw_before = params.get("before_message_id", [""])[0]
            before_message_id = None if raw_before in ("", None) else int(raw_before)
            with _contact_owner_scope(port=port, access_all=False):
                self._send_json({
                    "messages": list_contact_messages(public_key, limit, anchor_message_id=anchor_message_id, before_message_id=before_message_id),
                    "total_count": get_contact_message_count(public_key),
                    "sent_history": get_contact_unique_outgoing_texts(public_key, 20),
                })
            return
        if parsed.path == "/api/events":
            self._stream_events(parsed)
            return
        if not parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if self._handle_auth_guard(parsed, "POST"):
            return
        try:
            body = self._read_json()
            conn = self._session_log_fields(body)
            if parsed.path == "/api/auth/login":
                settings = _get_client_settings()
                if not _is_local_auth_enabled(settings):
                    self._send_json({"ok": True, "auth_enabled": False})
                    return
                username = _normalize_auth_username(body.get("username"))
                password = str(body.get("password") or "")
                expected_username = str(settings.get("auth_username") or "")
                if username != expected_username or not _verify_auth_password(password, settings):
                    self._send_json({"error": "Неверный логин или пароль."}, status=HTTPStatus.UNAUTHORIZED)
                    return
                if not settings.get("auth_session_secret"):
                    settings["auth_session_secret"] = _generate_auth_session_secret()
                    with CLIENT_SETTINGS_LOCK:
                        _save_client_settings_unlocked(settings)
                cookie_value = _build_auth_cookie(username, str(settings.get("auth_session_secret") or ""))
                self._send_json(
                    {"ok": True, "auth_enabled": True},
                    headers={"Set-Cookie": _build_auth_cookie_header(cookie_value)},
                )
                return
            if parsed.path == "/api/auth/logout":
                self._send_json({"ok": True}, headers={"Set-Cookie": _build_auth_cookie_clear_header()})
                return
            if parsed.path == "/api/probe":
                logging.info("api probe requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session:
                    snapshot = _build_session_snapshot(session, include_contacts=False, include_channels=False)
                    if snapshot["active"] and snapshot["device"]:
                        self._send_json({"device": snapshot["device"], "source": "live-session"})
                        return
                session_kwargs = self._session_kwargs(body)
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            device = client.query_device(session_kwargs["protocol_version"])
                self._send_json({"device": _device_info_to_dict(device)})
                return
            if parsed.path == "/api/info":
                logging.info("api info requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session:
                    snapshot = _build_session_snapshot(session, include_contacts=False)
                    if snapshot["active"]:
                        self._send_json(
                            {
                                "device": snapshot["device"],
                                "self": snapshot["self"],
                                "channels": snapshot["channels"],
                                "radio_stats": snapshot["radio_stats"],
                                "self_telemetry": snapshot["self_telemetry"],
                                "battery_info": snapshot["battery_info"],
                            }
                        )
                        return
                session_kwargs = self._session_kwargs(body)
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            snapshot = _collect_node_snapshot_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                            )
                self._send_json(
                    {
                        "device": snapshot["device"],
                        "self": snapshot["self"],
                        "channels": snapshot["channels"],
                        "radio_stats": snapshot["radio_stats"],
                        "self_telemetry": snapshot["self_telemetry"],
                        "battery_info": snapshot["battery_info"],
                    }
                )
                return
            if parsed.path == "/api/node/meshcore-params":
                session_kwargs = self._session_kwargs(body)
                logging.info(
                    "api node/meshcore-params requested transport=%s connection=%s baudrate=%s",
                    conn["transport_type"],
                    conn["transport_id"],
                    conn["baudrate"],
                )
                session = _get_background_session(session_kwargs["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        session_kwargs["port"],
                        {
                            "kind": "meshcore_params_snapshot",
                        },
                        timeout_secs=15.0,
                    )
                    self._send_json({
                        "ok": True,
                        "device": response.get("device"),
                        "self": response.get("self"),
                        "radio_stats": response.get("radio_stats"),
                        "self_telemetry": response.get("self_telemetry"),
                        "battery_info": response.get("battery_info"),
                        "meshcore_params": response.get("meshcore_params") or {},
                    })
                    return
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            snapshot = _collect_node_snapshot_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                                include_channels=False,
                            )
                self._send_json({
                    "ok": True,
                    "device": snapshot.get("device"),
                    "self": snapshot.get("self"),
                    "radio_stats": snapshot.get("radio_stats"),
                    "self_telemetry": snapshot.get("self_telemetry"),
                    "battery_info": snapshot.get("battery_info"),
                    "meshcore_params": snapshot.get("meshcore_params") or {},
                })
                return
            if parsed.path == "/api/node/meshcore-params/apply":
                session_kwargs = self._session_kwargs(body)
                group = str(body.get("group") or "").strip()
                if not group:
                    raise ValueError("group is required")
                patch = body.get("patch") if isinstance(body.get("patch"), dict) else {}
                logging.info(
                    "api node/meshcore-params/apply requested transport=%s connection=%s baudrate=%s group=%s",
                    conn["transport_type"],
                    conn["transport_id"],
                    conn["baudrate"],
                    group,
                )
                session = _get_background_session(session_kwargs["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        session_kwargs["port"],
                        {
                            "kind": "apply_meshcore_params",
                            "group": group,
                            "patch": patch,
                        },
                        timeout_secs=18.0,
                    )
                    self._send_json({
                        "ok": True,
                        "device": response.get("device"),
                        "self": response.get("self"),
                        "radio_stats": response.get("radio_stats"),
                        "self_telemetry": response.get("self_telemetry"),
                        "battery_info": response.get("battery_info"),
                        "meshcore_params": response.get("meshcore_params") or {},
                    })
                    return
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            snapshot = _apply_meshcore_params_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                                group=group,
                                patch=patch,
                            )
                device_dict = dict(snapshot.get("device") or {})
                self_dict = dict(snapshot.get("self") or {})
                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                _adopt_unowned_contact_records(owner_id)
                _adopt_unowned_message_records(owner_id)
                _normalize_self_contact_message_records(owner_id)
                _freeze_self_contact_if_cached(self_dict)
                _record_successful_connection(session_kwargs, self_dict, device_dict)
                self._send_json({
                    "ok": True,
                    "device": device_dict,
                    "self": self_dict,
                    "radio_stats": snapshot.get("radio_stats"),
                    "self_telemetry": snapshot.get("self_telemetry"),
                    "battery_info": snapshot.get("battery_info"),
                    "meshcore_params": snapshot.get("meshcore_params") or {},
                })
                return
            if parsed.path == "/api/connect":
                session_kwargs = self._session_kwargs(body)
                light = bool(body.get("light"))
                logging.info("api connect requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _start_background_session(
                    _normalize_session_config(
                        port=session_kwargs["port"],
                        baudrate=session_kwargs["baudrate"],
                        timeout=session_kwargs["timeout"],
                        protocol_version=session_kwargs["protocol_version"],
                        app_version=session_kwargs["app_version"],
                        app_name=session_kwargs["app_name"],
                        transport_type=session_kwargs["transport_type"],
                        transport_id=session_kwargs["transport_id"],
                        display_label=str((session_kwargs.get("connection") or {}).get("display_label") or session_kwargs["transport_id"]),
                        pin=str((session_kwargs.get("connection") or {}).get("pin") or ""),
                    )
                )
                snapshot = _wait_for_background_session(session)
                response_snapshot = _build_session_snapshot(
                    session,
                    include_contacts=not light,
                    include_channels=not light,
                )
                logging.info(
                    "api connect completed port=%s baudrate=%s contacts=%s channels=%s collections_ready=%s node=%s",
                    conn["port"],
                    conn["baudrate"],
                    response_snapshot.get("contacts_count")
                    if response_snapshot.get("contacts_count") is not None
                    else "pending",
                    response_snapshot.get("channels_count")
                    if response_snapshot.get("channels_count") is not None
                    else "pending",
                    bool(response_snapshot.get("collections_ready")),
                    (response_snapshot["self"] or {}).get("name", "-"),
                )
                self._send_json(
                    {
                        "device": response_snapshot["device"],
                        "self": response_snapshot["self"],
                        "collections_ready": response_snapshot.get("collections_ready"),
                        "next_since": None,
                        "contacts": response_snapshot.get("contacts") or [],
                        "channels": response_snapshot.get("channels") or [],
                        "contacts_count": response_snapshot["contacts_count"],
                        "contact_summary": response_snapshot.get("contact_summary") or {},
                        "channels_count": response_snapshot["channels_count"],
                        "radio_stats": response_snapshot["radio_stats"],
                        "self_telemetry": response_snapshot["self_telemetry"],
                        "battery_info": response_snapshot["battery_info"],
                        "connection": response_snapshot.get("connection") or {},
                        "port": response_snapshot.get("port"),
                        "baudrate": response_snapshot.get("baudrate"),
                        "transport_type": response_snapshot.get("transport_type"),
                        "transport_id": response_snapshot.get("transport_id"),
                    }
                )
                return
            if parsed.path == "/api/client-settings":
                normalized_settings = _update_client_settings(body or {})
                if "muted_conversations" in (body or {}):
                    sync_mobile_push_muted_conversations(
                        DB_LOCK,
                        CONTACTS_DB_PATH,
                        muted_conversations=normalized_settings.get("muted_conversations"),
                    )
                response_payload = _build_client_settings_payload()
                _broadcast_global_event(
                    {
                        "event": "client-settings",
                        "settings": response_payload.get("settings", {}),
                    }
                )
                self._send_json(response_payload)
                return
            if parsed.path == "/api/client-settings/forget-connection":
                normalized_settings = _forget_saved_connection((body or {}).get("key"))
                response_payload = _build_client_settings_payload()
                _broadcast_global_event(
                    {
                        "event": "client-settings",
                        "settings": response_payload.get("settings", {}),
                    }
                )
                self._send_json(response_payload)
                return
            if parsed.path == "/api/frontend-diagnostic":
                diagnostic_kind = str(body.get("kind") or body.get("event") or "frontend-event").strip() or "frontend-event"
                payload = body if isinstance(body, dict) else {}
                forwarded_fields = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"kind"}
                }
                _log_frontend_diagnostic(
                    diagnostic_kind,
                    remote_addr=str(self.client_address[0] if self.client_address else ""),
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    **forwarded_fields,
                )
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/wallpapers/upload":
                saved_name = _store_wallpaper_file(body.get("filename"), body.get("content_base64"))
                normalized_settings = _update_client_settings({
                    "page_background_id": f"wallpaper:{saved_name}",
                })
                response_payload = _build_client_settings_payload()
                response_payload["uploaded_wallpaper"] = {
                    "name": saved_name,
                    "url": _build_wallpaper_url(saved_name),
                }
                _broadcast_global_event(
                    {
                        "event": "client-settings",
                        "settings": response_payload.get("settings", {}),
                    }
                )
                self._send_json(response_payload)
                return
            if parsed.path == "/api/mobile-push/register":
                device = register_mobile_push_device(
                    DB_LOCK,
                    CONTACTS_DB_PATH,
                    installation_id=str(body.get("installation_id") or ""),
                    fcm_token=str(body.get("fcm_token") or ""),
                    base_url=str(body.get("base_url") or ""),
                    device_label=str(body.get("device_label") or ""),
                    app_version=str(body.get("app_version") or ""),
                    notifications_enabled=bool(body.get("notifications_enabled", True)),
                    muted_regular_keys=[
                        str(value or "")
                        for value in list(body.get("muted_regular_keys") or [])
                    ],
                    muted_all_keys=[
                        str(value or "")
                        for value in list(body.get("muted_all_keys") or [])
                    ],
                )
                self._send_json(
                    {
                        "ok": True,
                        "device": device,
                        "push_status": build_mobile_push_status(PROJECT_ROOT, DB_LOCK, CONTACTS_DB_PATH),
                    }
                )
                return
            if parsed.path == "/api/mobile-push/unregister":
                removed = unregister_mobile_push_device(
                    DB_LOCK,
                    CONTACTS_DB_PATH,
                    installation_id=str(body.get("installation_id") or ""),
                    fcm_token=str(body.get("fcm_token") or ""),
                )
                self._send_json({"ok": True, "removed": removed})
                return
            if parsed.path == "/api/channels":
                logging.info("api channels requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session:
                    snapshot = _build_session_snapshot(session, include_contacts=False)
                    if snapshot["active"]:
                        if not bool(snapshot.get("collections_ready")):
                            self._send_json(
                                {
                                    "channels": snapshot.get("channels") or [],
                                    "channels_count": snapshot.get("channels_count"),
                                    "collections_ready": False,
                                    "pending": True,
                                    "source": "startup-pending",
                                }
                            )
                            return
                        self._send_json(
                            {
                                "channels": snapshot["channels"],
                                "channels_count": snapshot.get("channels_count"),
                                "collections_ready": True,
                                "source": "live-session",
                            }
                        )
                        return
                session_kwargs = self._session_kwargs(body)
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            _device_dict, channels_dict = _load_channels_snapshot_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                            )
                    self._send_json({"channels": channels_dict})
                return
            if parsed.path == "/api/channels/save":
                session_kwargs = self._session_kwargs(body)
                raw_channel_idx = body.get("channel_idx")
                channel_idx = None if raw_channel_idx in (None, "") else int(raw_channel_idx)
                channel_name = str(body.get("channel_name") or "").strip()
                if not channel_name:
                    raise ValueError("channel_name is required")
                logging.info(
                    "api channels/save requested port=%s baudrate=%s idx=%s name=%s",
                    conn["port"],
                    conn["baudrate"],
                    channel_idx,
                    channel_name,
                )
                session = _get_background_session(session_kwargs["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "save_channel",
                            "channel_idx": channel_idx,
                            "channel_name": channel_name,
                            "channel_secret_hex": body.get("channel_secret_hex"),
                        },
                        timeout_secs=20.0,
                    )
                    channel_dict = dict(response.get("channel") or {})
                    channels_dict = list(response.get("channels") or [])
                else:
                    with _paused_background_session(session_kwargs["port"]):
                        channel_dict, channels_dict = _save_channel_and_reload(
                            session_kwargs,
                            channel_idx,
                            channel_name,
                            body.get("channel_secret_hex"),
                        )
                self._send_json({"channel": channel_dict, "channels": channels_dict})
                return
            if parsed.path == "/api/time/get":
                logging.info("api time/get requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "get_device_time",
                        },
                        timeout_secs=10.0,
                    )
                    epoch = int(response.get("epoch") or 0)
                else:
                    session_kwargs = self._session_kwargs(body)
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                epoch = client.get_device_time()
                self._send_json(
                    {
                        "epoch": epoch,
                        "utc": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
                    }
                )
                return
            if parsed.path == "/api/time/sync":
                logging.info("api time/sync requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                requested_epoch = utc_now_epoch()
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "sync_device_time",
                            "epoch": requested_epoch,
                        },
                        timeout_secs=12.0,
                    )
                    before = int(response.get("before") or 0)
                    after = int(response.get("after") or 0)
                    requested_epoch = int(response.get("requested_epoch") or requested_epoch)
                else:
                    session_kwargs = self._session_kwargs(body)
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                before = client.get_device_time()
                                client.set_device_time(requested_epoch)
                                after = client.get_device_time()
                self._send_json(
                    {
                        "requested_epoch": requested_epoch,
                        "before": before,
                        "before_utc": datetime.fromtimestamp(before, tz=timezone.utc).isoformat(),
                        "after": after,
                        "after_utc": datetime.fromtimestamp(after, tz=timezone.utc).isoformat(),
                    }
                )
                return
            if parsed.path == "/api/contacts":
                logging.info("api contacts requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                refresh = bool(body.get("refresh", False))
                session = _get_background_session(conn["port"])
                if session and not refresh:
                    snapshot = _build_session_snapshot(session, include_channels=False)
                    if snapshot["active"]:
                        if not bool(snapshot.get("collections_ready")):
                            with _contact_owner_scope(port=conn["port"]):
                                cached_contacts = CONTACT_BACKEND.list_cached_contacts(body.get("limit"))
                            self._send_json({
                                "next_since": None,
                                "contacts": _compact_contacts_for_client(cached_contacts),
                                "contact_summary": _build_contact_count_summary(cached_contacts),
                                "source": "cache+startup-pending",
                                "collections_ready": False,
                                "pending": True,
                            })
                            return
                        self._send_json({
                            "next_since": None,
                            "contacts": snapshot["contacts"],
                            "contact_summary": snapshot.get("contact_summary") or {},
                            "source": "cache+live-session",
                            "collections_ready": True,
                        })
                        return
                if not refresh:
                    with _contact_owner_scope(port=conn["port"]):
                        cached_contacts = CONTACT_BACKEND.list_cached_contacts(body.get("limit"))
                    self._send_json({
                        "next_since": None,
                        "contacts": _compact_contacts_for_client(cached_contacts),
                        "contact_summary": _build_contact_count_summary(cached_contacts),
                        "source": "cache",
                    })
                    return
                session_kwargs = self._session_kwargs(body)
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    refreshed = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "refresh_contacts",
                            "since": body.get("since"),
                        },
                        timeout_secs=20.0,
                    )
                else:
                    with _paused_background_session(conn["port"]):
                        with _contact_owner_scope(port=conn["port"], access_all=False):
                            refreshed = CONTACT_BACKEND.refresh_snapshot(
                                session_kwargs,
                                since=body.get("since"),
                                client_factory=_router_client_factory,
                                connection_access=_connection_access_from_kwargs,
                            )
                contacts_dict = list(refreshed.get("live_contacts") or [])
                cursor = refreshed.get("next_since")
                _set_background_session_contacts(conn["port"], contacts_dict)
                logging.info(
                    "api contacts refresh completed port=%s baudrate=%s contacts=%s next_since=%s",
                    conn["port"],
                    conn["baudrate"],
                    len(contacts_dict),
                    cursor,
                )
                with _contact_owner_scope(port=conn["port"]):
                    full_contacts = refreshed.get("contacts") or CONTACT_BACKEND.compose_snapshot(contacts_dict)
                    self._send_json(
                        {
                            "next_since": cursor,
                            "contacts": _compact_contacts_for_client(full_contacts),
                            "contact_summary": _build_contact_count_summary(full_contacts),
                            "source": "companion-refresh",
                        }
                    )
                return
            if parsed.path == "/api/contacts/cache":
                with _contact_owner_scope(port=conn["port"]):
                    self._send_json(
                        CONTACT_BACKEND.build_cache_payload(
                            stale_after_secs=max(
                                _get_contact_active_timeout_secs(),
                                _get_repeater_active_timeout_secs(),
                            ),
                            limit=body.get("limit"),
                            public_key=body.get("public_key"),
                        )
                    )
                return
            if parsed.path == "/api/contacts/delete":
                session_kwargs = self._session_kwargs(body)
                mode = str(body.get("mode") or "all")
                protect_favorites = bool(body.get("protect_favorites", True))
                logging.info(
                    "api contacts/delete requested port=%s baudrate=%s mode=%s protect_favorites=%s",
                    conn["port"],
                    conn["baudrate"],
                    mode,
                    protect_favorites,
                )
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    result = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "remove_contacts",
                            "mode": mode,
                            "protect_favorites": protect_favorites,
                        },
                        timeout_secs=30.0,
                    )
                else:
                    with _paused_background_session(conn["port"]):
                        with _contact_owner_scope(port=conn["port"], access_all=False):
                            result = CONTACT_BACKEND.remove_contacts_and_reload(
                                session_kwargs,
                                mode=mode,
                                protect_favorites=protect_favorites,
                                client_factory=_router_client_factory,
                                connection_access=_connection_access_from_kwargs,
                            )
                _set_background_session_contacts(conn["port"], result.get("live_contacts"))
                logging.info(
                    "api contacts/delete completed port=%s baudrate=%s mode=%s removed=%s remaining=%s max_contacts=%s",
                    conn["port"],
                    conn["baudrate"],
                    mode,
                    int(result.get("removed") or 0),
                    int(result.get("remaining") or 0),
                    int(result.get("max_contacts") or 0),
                )
                self._send_json(result)
                return
            if parsed.path == "/api/advert":
                logging.info("api advert requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "send_advert",
                            "name": body.get("advert_name") or "",
                            "flood": bool(body.get("flood", False)),
                        },
                        timeout_secs=12.0,
                    )
                else:
                    session_kwargs = self._session_kwargs(body)
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                advert_name = body.get("advert_name") or None
                                if advert_name:
                                    client.set_advert_name(advert_name)
                                client.send_self_advert(flood=bool(body.get("flood", False)))
                logging.info("api advert completed port=%s baudrate=%s", conn["port"], conn["baudrate"])
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/node/name":
                session_kwargs = self._session_kwargs(body)
                new_name = str(body.get("name") or "").strip()
                if not new_name:
                    raise ValueError("name is required")
                logging.info("api node/name requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "set_node_name",
                            "name": new_name,
                        },
                        timeout_secs=12.0,
                    )
                    self._send_json({
                        "ok": True,
                        "device": response.get("device"),
                        "self": response.get("self"),
                        "channels": response.get("channels") or [],
                        "radio_stats": response.get("radio_stats"),
                        "self_telemetry": response.get("self_telemetry"),
                        "battery_info": response.get("battery_info"),
                    })
                    return
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            client.set_advert_name(new_name)
                            snapshot = _collect_node_snapshot_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                            )
                device_dict = dict(snapshot["device"] or {})
                self_dict = dict(snapshot["self"] or {})
                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                _adopt_unowned_contact_records(owner_id)
                _adopt_unowned_message_records(owner_id)
                _normalize_self_contact_message_records(owner_id)
                _freeze_self_contact_if_cached(self_dict)
                _record_successful_connection(session_kwargs, self_dict, device_dict)
                session = _get_background_session(conn["port"])
                if session:
                    with session.snapshot_lock:
                        session.device = device_dict
                        session.self_info = self_dict
                        session.radio_stats = snapshot["radio_stats"]
                        session.self_telemetry = snapshot["self_telemetry"]
                        session.battery_info = snapshot["battery_info"]
                        session.channels = list(snapshot["channels"] or [])
                self._send_json({
                    "ok": True,
                    "device": device_dict,
                    "self": self_dict,
                    "channels": list(snapshot["channels"] or []),
                    "radio_stats": snapshot["radio_stats"],
                    "self_telemetry": snapshot["self_telemetry"],
                    "battery_info": snapshot["battery_info"],
                })
                return
            if parsed.path == "/api/node/self-location":
                session_kwargs = self._session_kwargs(body)
                scope = str(body.get("scope") or "local").strip().lower()
                lat = round(float(body.get("lat")), 6)
                lon = round(float(body.get("lon")), 6)
                if not (-90.0 <= lat <= 90.0):
                    raise ValueError("lat must be in range -90..90")
                if not (-180.0 <= lon <= 180.0):
                    raise ValueError("lon must be in range -180..180")
                logging.info(
                    "api node/self-location requested port=%s baudrate=%s scope=%s lat=%.6f lon=%.6f",
                    conn["port"],
                    conn["baudrate"],
                    scope,
                    lat,
                    lon,
                )
                if scope == "local":
                    owner_id = _resolve_owner_id_for_port(conn["port"])
                    if not owner_id:
                        raise ValueError("active node owner_id is required for local position override")
                    _set_self_location_override(owner_id, lat, lon)
                    session = _get_background_session(conn["port"])
                    if session:
                        snapshot = _build_session_snapshot(session, include_contacts=False)
                        self._send_json({
                            "ok": True,
                            "scope": "local",
                            "device": snapshot.get("device"),
                            "self": snapshot.get("self"),
                            "channels": snapshot.get("channels") or [],
                            "radio_stats": snapshot.get("radio_stats"),
                            "self_telemetry": snapshot.get("self_telemetry"),
                            "battery_info": snapshot.get("battery_info"),
                        })
                        return
                    self._send_json({"ok": True, "scope": "local"})
                    return
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "set_node_location",
                            "lat": lat,
                            "lon": lon,
                        },
                        timeout_secs=15.0,
                    )
                    self._send_json({
                        "ok": True,
                        "scope": "global",
                        "device": response.get("device"),
                        "self": response.get("self"),
                        "channels": response.get("channels") or [],
                        "radio_stats": response.get("radio_stats"),
                        "self_telemetry": response.get("self_telemetry"),
                        "battery_info": response.get("battery_info"),
                    })
                    return
                with _paused_background_session(session_kwargs["port"]):
                    with _connection_access_from_kwargs(session_kwargs):
                        with _open_meshcore_client(session_kwargs) as client:
                            snapshot = _set_node_location_with_client(
                                client,
                                protocol_version=session_kwargs["protocol_version"],
                                app_version=session_kwargs["app_version"],
                                app_name=session_kwargs["app_name"],
                                lat=lat,
                                lon=lon,
                            )
                device_dict = dict(snapshot["device"] or {})
                self_dict = dict(snapshot["self"] or {})
                owner_id = _normalize_owner_id(self_dict.get("public_key"))
                _adopt_unowned_contact_records(owner_id)
                _adopt_unowned_message_records(owner_id)
                _normalize_self_contact_message_records(owner_id)
                _freeze_self_contact_if_cached(self_dict)
                _clear_self_location_override(owner_id)
                _record_successful_connection(session_kwargs, self_dict, device_dict)
                session = _get_background_session(conn["port"])
                if session:
                    with session.snapshot_lock:
                        session.device = device_dict
                        session.self_info = self_dict
                        session.radio_stats = snapshot["radio_stats"]
                        session.self_telemetry = snapshot["self_telemetry"]
                        session.battery_info = snapshot["battery_info"]
                        session.channels = list(snapshot["channels"] or [])
                self._send_json({
                    "ok": True,
                    "scope": "global",
                    "device": device_dict,
                    "self": self_dict,
                    "channels": list(snapshot["channels"] or []),
                    "radio_stats": snapshot["radio_stats"],
                    "self_telemetry": snapshot["self_telemetry"],
                    "battery_info": snapshot["battery_info"],
                })
                return
            if parsed.path == "/api/disconnect":
                logging.info("api disconnect requested port=%s baudrate=%s", conn["port"], conn["baudrate"])
                _stop_background_session(conn["port"])
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/messages/clear":
                with _contact_owner_scope(port=conn["port"]):
                    deleted = clear_message_db()
                logging.info("api messages/clear completed deleted=%s", deleted)
                self._send_json({"ok": True, "deleted": deleted})
                return
            if parsed.path == "/api/messages/read-state":
                is_read = bool(body.get("is_read", False))
                scope = str(body.get("scope") or "regular")
                mention_name = str(body.get("mention_name") or "")
                source = str(body.get("source") or "").strip()
                with _contact_owner_scope(port=conn["port"]):
                    updated = set_all_messages_read_state(is_read, scope=scope, mention_name=mention_name)
                if source:
                    _log_read_debug(
                        "messages_read_state_request",
                        source=source,
                        scope=scope,
                        is_read=bool(is_read),
                        mention_name=mention_name,
                        messages=int(updated.get("messages") or 0),
                        contact_messages=int(updated.get("contact_messages") or 0),
                        mention_messages=int(updated.get("mention_messages") or 0),
                        mention_contact_messages=int(updated.get("mention_contact_messages") or 0),
                    )
                logging.info(
                    "api messages/read-state completed scope=%s is_read=%s messages=%s contact_messages=%s mention_messages=%s mention_contact_messages=%s",
                    scope,
                    is_read,
                    updated["messages"],
                    updated["contact_messages"],
                    updated["mention_messages"],
                    updated["mention_contact_messages"],
                )
                self._send_json({"ok": True, **updated})
                return
            if parsed.path == "/api/messages/debug-summary":
                mention_name = str(body.get("mention_name") or "")
                with _contact_owner_scope(port=conn["port"]):
                    summary = get_message_debug_summary(mention_name)
                self._send_json({"ok": True, **summary})
                return
            if parsed.path == "/api/messages/conversation/read":
                conversation_kind = str(body.get("conversation_kind") or "")
                conversation_value = str(body.get("conversation_value") or "")
                mention_name = str(body.get("mention_name") or "")
                if conversation_kind == "channel":
                    with _channel_history_scope(conn["port"], int(conversation_value or 0)):
                        updated = mark_conversation_messages_read(conversation_kind, conversation_value, mention_name=mention_name)
                else:
                    with _contact_owner_scope(port=conn["port"], access_all=False):
                        updated = mark_conversation_messages_read(conversation_kind, conversation_value, mention_name=mention_name)
                self._send_json({"ok": True, **updated})
                return
            if parsed.path == "/api/messages/read-up-to":
                conversation_kind = str(body.get("conversation_kind") or "")
                conversation_value = str(body.get("conversation_value") or "")
                message_id = int(body.get("message_id", 0))
                if conversation_kind == "channel":
                    with _channel_history_scope(conn["port"], int(conversation_value or 0)):
                        stored = mark_messages_read_up_to(conversation_kind, conversation_value, message_id)
                else:
                    with _contact_owner_scope(port=conn["port"], access_all=False):
                        stored = mark_messages_read_up_to(conversation_kind, conversation_value, message_id)
                self._send_json({"ok": True, "message_id": stored})
                return
            if parsed.path == "/api/messages/mention-read-state":
                message_table = str(body.get("message_table") or "")
                message_id = int(body.get("message_id", 0))
                is_read = bool(body.get("is_read", True))
                with _contact_owner_scope(port=conn["port"]):
                    set_mention_message_read_state(message_table, message_id, is_read)
                self._send_json({"ok": True})
                return
            if parsed.path == "/api/messages/unread":
                mention_name = str(body.get("mention_name") or "")
                include_entries = bool(body.get("include_entries", True))
                with _contact_owner_scope(port=conn["port"]):
                    owner_id = _resolve_owner_id_for_port(conn["port"])
                    channel_unread_summary, channel_mention_summary = _build_channel_unread_payload_for_port(conn["port"], mention_name)
                    contact_unread_summary = get_contact_unread_summary(mention_name, owner_id=owner_id, access_all=False)
                    contact_mention_summary = get_contact_mention_summary(mention_name, owner_id=owner_id, access_all=False)
                    self._send_json(
                        {
                            "channel_unread_counts": {key: int(value["unread_count"]) for key, value in channel_unread_summary.items()},
                            "contact_unread_counts": {key: int(value["unread_count"]) for key, value in contact_unread_summary.items()},
                            "channel_first_unread_ids": {key: int(value["first_unread_id"]) for key, value in channel_unread_summary.items()},
                            "contact_first_unread_ids": {key: int(value["first_unread_id"]) for key, value in contact_unread_summary.items()},
                            "channel_last_unread_ids": {key: int(value["last_unread_id"]) for key, value in channel_unread_summary.items()},
                            "contact_last_unread_ids": {key: int(value["last_unread_id"]) for key, value in contact_unread_summary.items()},
                            "channel_mention_counts": {key: int(value["mention_count"]) for key, value in channel_mention_summary.items()},
                            "contact_mention_counts": {key: int(value["mention_count"]) for key, value in contact_mention_summary.items()},
                            "channel_first_mention_ids": {key: int(value["first_mention_id"]) for key, value in channel_mention_summary.items()},
                            "contact_first_mention_ids": {key: int(value["first_mention_id"]) for key, value in contact_mention_summary.items()},
                            "channel_last_mention_ids": {key: int(value["last_mention_id"]) for key, value in channel_mention_summary.items()},
                            "contact_last_mention_ids": {key: int(value["last_mention_id"]) for key, value in contact_mention_summary.items()},
                            "mention_entries": list_unread_mentions(mention_name, port=conn["port"]) if include_entries else [],
                        }
                    )
                return
            if parsed.path == "/api/contact-groups/save":
                scope_key = _build_contact_groups_scope_key(
                    port=body.get("port"),
                    baudrate=body.get("baudrate"),
                )
                with _contact_owner_scope(port=body.get("port")):
                    self._send_json(
                        {
                            "ok": True,
                            **CONTACT_BACKEND.save_contact_group(
                                str(body.get("group_name") or ""),
                                list(body.get("members") or []),
                                scope_key=scope_key,
                            ),
                        }
                    )
                return
            if parsed.path == "/api/contact-groups/delete":
                scope_key = _build_contact_groups_scope_key(
                    port=body.get("port"),
                    baudrate=body.get("baudrate"),
                )
                with _contact_owner_scope(port=body.get("port")):
                    self._send_json(
                        {
                            "ok": True,
                            **CONTACT_BACKEND.delete_contact_group(
                                str(body.get("group_name") or ""),
                                scope_key=scope_key,
                            ),
                        }
                    )
                return
            if parsed.path == "/api/contact-groups/rename":
                scope_key = _build_contact_groups_scope_key(
                    port=body.get("port"),
                    baudrate=body.get("baudrate"),
                )
                with _contact_owner_scope(port=body.get("port")):
                    self._send_json(
                        {
                            "ok": True,
                            **CONTACT_BACKEND.rename_contact_group(
                                str(body.get("old_name") or ""),
                                str(body.get("new_name") or ""),
                                scope_key=scope_key,
                            ),
                        }
                    )
                return
            if parsed.path == "/api/contact-groups/favorites-sync":
                session_kwargs = self._session_kwargs(body)
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    result = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "sync_favorites_group",
                            "members": list(body.get("members") or []),
                        },
                        timeout_secs=20.0,
                    )
                else:
                    result = _run_contact_backend_result(
                        conn["port"],
                        lambda: CONTACT_BACKEND.sync_favorites_group(
                            session_kwargs,
                            list(body.get("members") or []),
                            client_factory=_router_client_factory,
                            connection_access=_connection_access_from_kwargs,
                        ),
                    )
                self._send_json(result)
                return
            if parsed.path == "/api/contacts/import":
                session_kwargs = self._session_kwargs(body)
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    result = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "perform_contact_action",
                            "public_key": None,
                            "action": "import",
                            "favorite": None,
                            "import_uri": str(body.get("uri") or ""),
                        },
                        timeout_secs=20.0,
                    )
                    _set_background_session_contacts(conn["port"], result.get("live_contacts"))
                    self._send_json(_compact_contact_payload(result))
                else:
                    result = _run_contact_backend_result(
                        conn["port"],
                        lambda: CONTACT_BACKEND.perform_action(
                            session_kwargs,
                            public_key=None,
                            action="import",
                            favorite=None,
                            import_uri=str(body.get("uri") or ""),
                            client_factory=_router_client_factory,
                            connection_access=_connection_access_from_kwargs,
                        ),
                    )
                    self._send_json(result)
                return
            if parsed.path == "/api/contacts/export-self":
                session_kwargs = self._session_kwargs(body)
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "export_self_contact",
                        },
                        timeout_secs=15.0,
                    )
                    uri = response.get("uri")
                else:
                    with _paused_background_session(conn["port"]):
                        with _contact_owner_scope(port=conn["port"], access_all=False):
                            uri = CONTACT_BACKEND.export_self_contact_uri(
                                session_kwargs,
                                client_factory=_router_client_factory,
                                connection_access=_connection_access_from_kwargs,
                            )
                self._send_json({"ok": True, "uri": uri})
                return
            if parsed.path in (
                "/api/contacts/share",
                "/api/contacts/export",
                "/api/contacts/reset-path",
                "/api/contacts/set-path",
                "/api/contacts/delete-one",
                "/api/contacts/delete-backend-one",
                "/api/contacts/favorite",
            ):
                session_kwargs = self._session_kwargs(body)
                public_key = str(body.get("public_key") or "").strip().lower()
                action_map = {
                    "/api/contacts/share": "share",
                    "/api/contacts/export": "export",
                    "/api/contacts/reset-path": "reset-path",
                    "/api/contacts/set-path": "set-path",
                    "/api/contacts/delete-one": "delete",
                    "/api/contacts/delete-backend-one": "delete-backend",
                    "/api/contacts/favorite": "favorite",
                }
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    result = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "perform_contact_action",
                            "public_key": public_key,
                            "action": action_map[parsed.path],
                            "favorite": body.get("favorite"),
                            "import_uri": None,
                            "route_path_len": body.get("route_path_len"),
                            "route_path_hash_len": body.get("route_path_hash_len"),
                            "route_path_hex": body.get("route_path_hex"),
                        },
                        timeout_secs=20.0,
                    )
                    _set_background_session_contacts(conn["port"], result.get("live_contacts"))
                    self._send_json(_compact_contact_payload(result))
                else:
                    result = _run_contact_backend_result(
                        conn["port"],
                        lambda: CONTACT_BACKEND.perform_action(
                            session_kwargs,
                            public_key=public_key,
                            action=action_map[parsed.path],
                            favorite=body.get("favorite"),
                            import_uri=None,
                            route_path_len=None if body.get("route_path_len") in (None, "") else int(body.get("route_path_len")),
                            route_path_hash_len=None if body.get("route_path_hash_len") in (None, "") else int(body.get("route_path_hash_len")),
                            route_path_hex=str(body.get("route_path_hex") or ""),
                            client_factory=_router_client_factory,
                            connection_access=_connection_access_from_kwargs,
                        ),
                    )
                    self._send_json(result)
                return
            if parsed.path == "/api/contacts/trace-route/start":
                selected_public_keys = [str(item or "").strip().lower() for item in list(body.get("selected_public_keys") or []) if str(item or "").strip()]
                route_path_hash_len = int(body.get("route_path_hash_len") or 2)
                sequential = bool(body.get("sequential", False))
                if not selected_public_keys:
                    raise ValueError("selected_public_keys is required")
                job = _start_route_trace_job(
                    port=conn["port"],
                    conn_kwargs=self._conn_kwargs(body),
                    selected_public_keys=selected_public_keys,
                    route_path_hash_len=route_path_hash_len,
                    sequential=sequential,
                )
                self._send_json(
                    {
                        "ok": True,
                        "job_id": str(job.job_id),
                        "trace": _clone_route_trace_payload(job.result),
                    }
                )
                return
            if parsed.path == "/api/contacts/trace-route/cancel":
                job_id = str(body.get("job_id") or "").strip()
                if not job_id:
                    raise ValueError("job_id is required")
                job = _get_route_trace_job(job_id)
                cancelled = _request_route_trace_job_cancel(job, str(body.get("reason") or "cancelled"))
                self._send_json({"ok": True, "job_id": job_id, "cancelled": bool(cancelled)})
                return
            if parsed.path == "/api/contacts/trace-route":
                selected_public_keys = [str(item or "").strip().lower() for item in list(body.get("selected_public_keys") or []) if str(item or "").strip()]
                route_path_hash_len = int(body.get("route_path_hash_len") or 2)
                sequential = bool(body.get("sequential", False))
                if not selected_public_keys:
                    raise ValueError("selected_public_keys is required")
                session = _get_background_session(conn["port"])
                if session and session.thread and session.thread.is_alive() and not session.stop_event.is_set():
                    result = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "trace_route",
                            "selected_public_keys": selected_public_keys,
                            "route_path_hash_len": route_path_hash_len,
                            "sequential": sequential,
                        },
                        timeout_secs=60.0,
                    )
                else:
                    with _paused_background_session(conn["port"]):
                        with _open_meshcore_client(self._conn_kwargs(body)) as client:
                            client.query_device(DEFAULT_PROTOCOL_VERSION)
                            client.app_start(DEFAULT_APP_NAME, DEFAULT_APP_VERSION)
                            live_contacts = client.get_contacts()[1]
                            result = _run_route_probe_with_client(
                                client,
                                live_contacts=live_contacts,
                                selected_public_keys=selected_public_keys,
                                route_path_hash_len=route_path_hash_len,
                                sequential=sequential,
                            )
                self._send_json(result)
                return
            if parsed.path == "/api/messages/channel/send":
                channel_idx = _resolve_channel_send_idx_for_request(conn["port"], body)
                owner_id = _resolve_owner_id_for_port(conn["port"])
                channel_slot = _get_node_channel_slot(
                    owner_id,
                    channel_idx=channel_idx,
                    channel_identity=str(body.get("channel_identity") or "").strip(),
                    channel_name=_normalize_channel_name(body.get("channel_name")),
                    channel_secret_hex=_normalize_channel_secret_hex(body.get("channel_secret_hex")),
                )
                resolved_channel_identity = str(
                    (channel_slot or {}).get("channel_identity")
                    or str(body.get("channel_identity") or "").strip()
                    or _build_channel_identity(body.get("channel_name"), body.get("channel_secret_hex"))
                ).strip()
                resolved_channel_name = _normalize_channel_name(
                    (channel_slot or {}).get("channel_name") or body.get("channel_name")
                )
                resolved_channel_secret_hex = _normalize_channel_secret_hex(
                    (channel_slot or {}).get("channel_secret_hex") or body.get("channel_secret_hex")
                )
                text = _validate_message_body(body.get("text", ""))
                logging.info(
                    "api messages/channel/send requested port=%s baudrate=%s channel=%s bytes=%s",
                    conn["port"],
                    conn["baudrate"],
                    channel_idx,
                    len(text.encode("utf-8")),
                )
                sender_timestamp = utc_now_epoch()
                active_session = _get_background_session(conn["port"])
                sent = None
                if active_session and active_session.active and active_session.thread and active_session.thread.is_alive():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "send_channel_text",
                            "channel_idx": channel_idx,
                            "text": text,
                            "timestamp": sender_timestamp,
                        },
                        timeout_secs=BACKGROUND_SEND_COMMAND_TIMEOUT_SECS,
                    )
                    sent = response.get("sent")
                else:
                    session_kwargs = self._session_kwargs(body)
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                sent = client.send_channel_text_message(
                                    channel_idx,
                                    text,
                                    timestamp=sender_timestamp,
                                )
                expected_ack_hex = None
                if sent is not None:
                    expected_ack = getattr(sent, "expected_ack", b"")
                    expected_ack_hex = bytes(expected_ack).hex() if expected_ack else None
                message = save_outbound_channel_message(
                    channel_idx,
                    text,
                    expected_ack_hex=expected_ack_hex,
                    sender_timestamp=sender_timestamp,
                    owner_id=owner_id,
                    channel_identity=resolved_channel_identity,
                    channel_name=resolved_channel_name,
                    channel_secret_hex=resolved_channel_secret_hex,
                )
                _log_delivery_debug(
                    "api_channel_send_saved",
                    id=message["id"],
                    channel_idx=channel_idx,
                    text=text,
                    sender_timestamp=sender_timestamp,
                    send_status=message["send_status"],
                    expected_ack_hex=message["expected_ack_hex"],
                )
                self._send_json({"ok": True, "message": message, "max_body_bytes": MESSAGE_BODY_MAX_BYTES})
                return
            if parsed.path == "/api/messages/contact/send":
                public_key = str(body.get("public_key") or "").strip().lower()
                if len(public_key) != 64:
                    raise ValueError("public_key must be a 64-char hex string")
                text = _validate_message_body(body.get("text", ""))
                logging.info(
                    "api messages/contact/send requested port=%s baudrate=%s target=%s bytes=%s",
                    conn["port"],
                    conn["baudrate"],
                    public_key[:12],
                    len(text.encode("utf-8")),
                )
                _log_delivery_debug(
                    "api_contact_send_request",
                    port=conn["port"],
                    baudrate=conn["baudrate"],
                    public_key=public_key,
                    pubkey_prefix=public_key[:12],
                    text=text,
                )
                sender_timestamp = utc_now_epoch()
                active_session = _get_background_session(conn["port"])
                if active_session and active_session.active and active_session.thread and active_session.thread.is_alive():
                    response = _run_command_via_background_session(
                        conn["port"],
                        {
                            "kind": "send_contact_text",
                            "public_key": public_key,
                            "text": text,
                            "timestamp": sender_timestamp,
                        },
                        timeout_secs=BACKGROUND_SEND_COMMAND_TIMEOUT_SECS,
                    )
                    sent = response["sent"]
                else:
                    with _paused_background_session(conn["port"]):
                        with _contact_owner_scope(port=conn["port"], access_all=False):
                            send_result = CONTACT_BACKEND.send_contact_text(
                                self._session_kwargs(body),
                                public_key=public_key,
                                text=text,
                                sender_timestamp=sender_timestamp,
                                client_factory=_router_client_factory,
                                connection_access=_connection_access_from_kwargs,
                            )
                        sent = send_result["sent"]
                _log_delivery_debug(
                    "api_contact_send_resp_sent",
                    port=conn["port"],
                    public_key=public_key,
                    pubkey_prefix=public_key[:12],
                    text=text,
                    sender_timestamp=sender_timestamp,
                    expected_ack_hex=sent.expected_ack.hex(),
                    suggested_timeout_ms=sent.suggested_timeout_ms,
                    route_flag=sent.route_flag,
                )
                message = save_outbound_contact_message(
                    public_key,
                    text,
                    sent.expected_ack.hex(),
                    False,
                    sender_timestamp=sender_timestamp,
                    owner_id=_resolve_owner_id_for_port(conn["port"]),
                )
                _log_delivery_debug(
                    "api_contact_send_saved",
                    id=message["id"],
                    public_key=public_key,
                    pubkey_prefix=public_key[:12],
                    text=text,
                    sender_timestamp=sender_timestamp,
                    send_status=message["send_status"],
                    expected_ack_hex=message["expected_ack_hex"],
                )
                self._send_json({
                    "ok": True,
                    "message": message,
                    "max_body_bytes": MESSAGE_BODY_MAX_BYTES,
                    "materialized_on_node": bool(
                        response.get("materialized_on_node")
                        if active_session and active_session.active and active_session.thread and active_session.thread.is_alive()
                        else send_result.get("materialized_on_node")
                    ),
                })
                return
            if parsed.path == "/api/repeater/login":
                public_key = _normalize_repeater_public_key_hex(body.get("public_key"))
                with _contact_owner_scope(port=conn["port"], access_all=False):
                    remember_auth = bool(body.get("remember_auth"))
                    password, password_source = _resolve_repeater_auth_password(public_key, body.get("password"))
                    session_kwargs = self._session_kwargs(body)
                    logging.info(
                        "api repeater/login requested port=%s baudrate=%s target=%s password_source=%s remember_auth=%s",
                        conn["port"],
                        conn["baudrate"],
                        public_key[:12],
                        password_source,
                        remember_auth,
                    )
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                device = client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                login_payload, _current_contacts, materialized_on_node = _login_to_repeater_with_client(
                                    client,
                                    public_key=public_key,
                                    password=password,
                                    hard_device_limit=int(device.max_contacts_div_2 * 2),
                                )
                    if remember_auth and password_source == "provided":
                        CONTACT_BACKEND.set_cached_repeater_auth_password(public_key, password)
                    contact_payload = CONTACT_BACKEND.get_cached_contact(public_key)
                self._send_json({
                    "ok": True,
                    "login": login_payload,
                    "materialized_on_node": bool(materialized_on_node),
                    "auth_saved": bool((contact_payload or {}).get("backend", {}).get("repeater_auth_saved")),
                    "contact": contact_payload,
                })
                return
            if parsed.path == "/api/repeater/cli":
                public_key = _normalize_repeater_public_key_hex(body.get("public_key"))
                with _contact_owner_scope(port=conn["port"], access_all=False):
                    password, password_source = _resolve_repeater_auth_password(public_key, body.get("password"))
                    commands = _normalize_repeater_cli_commands(body.get("commands", body.get("command")))
                    command_delay_secs = max(0.0, min(float(body.get("command_delay_secs", 0.2)), 2.0))
                    session_kwargs = self._session_kwargs(body)
                    logging.info(
                        "api repeater/cli requested port=%s baudrate=%s target=%s commands=%s password_source=%s",
                        conn["port"],
                        conn["baudrate"],
                        public_key[:12],
                        len(commands),
                        password_source,
                    )
                    with _paused_background_session(session_kwargs["port"]):
                        with _connection_access_from_kwargs(session_kwargs):
                            with _open_meshcore_client(session_kwargs) as client:
                                device = client.query_device(session_kwargs["protocol_version"])
                                client.app_start(session_kwargs["app_name"], session_kwargs["app_version"])
                                result = _run_repeater_cli_batch_with_client(
                                    client,
                                    public_key=public_key,
                                    password=password,
                                    commands=commands,
                                    command_delay_secs=command_delay_secs,
                                    hard_device_limit=int(device.max_contacts_div_2 * 2),
                                )
                self._send_json({
                    "ok": True,
                    "login": result["login"],
                    "commands": result["commands"],
                    "materialized_on_node": bool(result.get("materialized_on_node")),
                })
                return
            if parsed.path == "/api/repeater/auth/delete":
                public_key = _normalize_repeater_public_key_hex(body.get("public_key"))
                with _contact_owner_scope(port=conn["port"], access_all=False):
                    logging.info(
                        "api repeater/auth/delete requested port=%s baudrate=%s target=%s",
                        conn["port"],
                        conn["baudrate"],
                        public_key[:12],
                    )
                    deleted = CONTACT_BACKEND.clear_cached_repeater_auth_password(public_key)
                    self._send_json({
                        "ok": True,
                        "deleted": bool(deleted),
                        "contact": CONTACT_BACKEND.get_cached_contact(public_key),
                    })
                return
        except (MeshCoreError, SerialException, sqlite3.Error, ValueError) as exc:
            conn = self._session_log_fields(locals().get("body"))
            if isinstance(exc, BleTransportUnavailable):
                logging.warning(
                    "api request unavailable path=%s port=%s baudrate=%s error=%s",
                    parsed.path,
                    conn["port"],
                    conn["baudrate"],
                    exc,
                )
            else:
                logging.exception(
                    "api request failed path=%s port=%s baudrate=%s error=%s",
                    parsed.path,
                    conn["port"],
                    conn["baudrate"],
                    exc,
                )
            error_payload = {"error": str(exc)}
            if isinstance(exc, BleTransportUnavailable):
                error_payload["transport_type"] = BLE_TRANSPORT_TYPE
                error_payload["diagnostics"] = _build_ble_transport_diagnostics(str(exc))
            self._send_json(error_payload, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args) -> None:
        return

    def _conn_kwargs(self, body: dict) -> dict:
        descriptor = DEFAULT_CONNECTION_ROUTER.from_request(body)
        connection_id = descriptor.port if descriptor.transport_type == SERIAL_TRANSPORT_TYPE else descriptor.transport_id
        return {
            "connection": descriptor.to_dict(include_secrets=bool(descriptor.pin)),
            "port": connection_id,
            "baudrate": int(descriptor.baudrate),
            "timeout": float(descriptor.timeout),
            "transport_type": descriptor.transport_type,
            "transport_id": descriptor.transport_id,
            "protocol_version": int(body.get("protocol_version", DEFAULT_PROTOCOL_VERSION)),
        }

    def _session_kwargs(self, body: dict) -> dict:
        kwargs = self._conn_kwargs(body)
        kwargs["app_version"] = int(body.get("app_version", DEFAULT_APP_VERSION))
        kwargs["app_name"] = body.get("app_name", DEFAULT_APP_NAME)
        return kwargs

    def _session_log_fields(self, body: dict | None) -> dict[str, str]:
        if not isinstance(body, dict):
            return {"port": "-", "baudrate": "-", "transport_type": "-", "transport_id": "-"}
        try:
            descriptor = DEFAULT_CONNECTION_ROUTER.from_request(body)
        except (TypeError, ValueError):
            return {"port": "-", "baudrate": "-", "transport_type": "-", "transport_id": "-"}
        connection_id = descriptor.port if descriptor.transport_type == SERIAL_TRANSPORT_TYPE else descriptor.transport_id
        return {
            "port": connection_id,
            "baudrate": str(descriptor.baudrate),
            "transport_type": descriptor.transport_type,
            "transport_id": descriptor.transport_id,
        }

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self._write_response_body(payload)

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self._write_response_body(payload)

    def _is_auth_exempt_path(self, path: str) -> bool:
        if path in {"/login", "/api/auth/login", "/api/auth/logout"}:
            return True
        if path.startswith("/icons/") or path.startswith("/vendor/") or path.startswith("/sounds/") or path.startswith("/wallpappers/") or path.startswith("/connect-app/"):
            return True
        if path in {"/api/mobile-push/register", "/api/mobile-push/unregister"}:
            return True
        return False

    def _is_vue_spa_path(self, path: str) -> bool:
        normalized = str(path or "").rstrip("/") or "/"
        if normalized in {"/", "/connect", "/contacts", "/contacts/groups", "/messages", "/maps", "/maps/route-checks", "/settings"}:
            return True
        if normalized.startswith("/contacts/repeater-login/"):
            return True
        if normalized.startswith("/contacts/repeater/"):
            return True
        return normalized.startswith("/settings/")

    def _legacy_redirect_path(self, path: str) -> str | None:
        normalized = str(path or "").rstrip("/") or "/"
        if normalized == "/legacy" or normalized == "/legacy/messages":
            return "/messages"
        if normalized == "/legacy/maps":
            return "/maps"
        if normalized == "/legacy/contacts" or normalized.startswith("/legacy/contacts/"):
            return normalized.removeprefix("/legacy")
        if normalized == "/legacy/settings" or normalized.startswith("/legacy/settings/"):
            return normalized.removeprefix("/legacy")
        return False

    def _handle_auth_guard(self, parsed, method: str) -> bool:
        settings = _get_client_settings()
        if not _is_local_auth_enabled(settings):
            return False
        if self._is_auth_exempt_path(parsed.path):
            return False
        if _is_authenticated_request(self, settings):
            return False
        if parsed.path.startswith("/api/"):
            self._send_json({"error": "authentication required", "auth_required": True}, status=HTTPStatus.UNAUTHORIZED)
            return True
        next_path = parsed.path or "/"
        if parsed.query:
            next_path = f"{next_path}?{parsed.query}"
        self._send_html(
            _build_login_html(next_path, username=str(settings.get("auth_username") or "")),
            status=HTTPStatus.UNAUTHORIZED,
        )
        return True

    def _send_icon_file(self, rel_path: str) -> None:
        normalized = os.path.normpath("/" + rel_path).lstrip("/")
        full_path = ICONS_DIR / normalized
        try:
            resolved = full_path.resolve(strict=True)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            resolved.relative_to(ICONS_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = resolved.read_bytes()
        lower_name = resolved.name.lower()
        if lower_name.endswith(".png"):
            content_type = "image/png"
        elif lower_name.endswith(".svg"):
            content_type = "image/svg+xml"
        else:
            content_type = "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self._write_response_body(payload)

    def _send_sound_file(self, rel_path: str) -> None:
        safe_name = os.path.basename(rel_path)
        full_path = os.path.join(SOUNDS_DIR, safe_name)
        if not os.path.isfile(full_path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with open(full_path, "rb") as fh:
            payload = fh.read()
        lower_name = safe_name.lower()
        if lower_name.endswith(".mp3"):
            content_type = "audio/mpeg"
        else:
            content_type = "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self._write_response_body(payload)

    def _send_wallpaper_file(self, rel_path: str) -> None:
        safe_name = _normalize_wallpaper_filename(rel_path)
        if not safe_name:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        full_path = WALLPAPPERS_DIR / safe_name
        try:
            resolved = full_path.resolve(strict=True)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            resolved.relative_to(WALLPAPPERS_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = resolved.read_bytes()
        content_type = ALLOWED_WALLPAPER_EXTENSIONS.get(resolved.suffix.lower(), "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self._write_response_body(payload)

    def _send_vendor_file(self, rel_path: str) -> None:
        normalized = os.path.normpath("/" + rel_path).lstrip("/")
        full_path = VENDOR_DIR / normalized
        try:
            resolved = full_path.resolve(strict=True)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            resolved.relative_to(VENDOR_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = resolved.read_bytes()
        lower_name = resolved.name.lower()
        if lower_name.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        elif lower_name.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        else:
            content_type = "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self._write_response_body(payload)

    def _send_redirect(self, location: str, status: HTTPStatus = HTTPStatus.FOUND) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_connect_app_index(self) -> None:
        index_path = WEB_DIST_DIR / "index.html"
        if not index_path.is_file():
            logging.error("vue build missing at %s; legacy frontend fallback has been removed", index_path)
            self._send_html(
                "<!doctype html><meta charset=\"utf-8\"><title>Meshcorium build missing</title>"
                "<h1>Meshcorium Vue build is missing</h1>"
                "<p>Run the frontend build and restart the service.</p>",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self._send_html(index_path.read_text(encoding="utf-8"))

    def _send_connect_app_file(self, rel_path: str) -> None:
        normalized = os.path.normpath("/" + rel_path).lstrip("/")
        full_path = WEB_DIST_DIR / normalized
        try:
            resolved = full_path.resolve(strict=True)
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            resolved.relative_to(WEB_DIST_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = resolved.read_bytes()
        guessed_type, guessed_encoding = mimetypes.guess_type(str(resolved))
        content_type = guessed_type or "application/octet-stream"
        if content_type.startswith("text/") and "charset=" not in content_type:
            content_type = f"{content_type}; charset=utf-8"
        if resolved.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif resolved.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif resolved.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif resolved.suffix == ".svg":
            content_type = "image/svg+xml"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if guessed_encoding:
            self.send_header("Content-Encoding", guessed_encoding)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _stream_events(self, parsed) -> None:
        params = parse_qs(parsed.query)
        port = params.get("port", [""])[0]
        if not port:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing port")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sink: queue.Queue = queue.Queue(maxsize=256)
        _register_event_subscriber(port, sink)
        logging.info("sse subscribe requested port=%s", port)
        try:
            session = _get_background_session(port)
            if session:
                snapshot = _build_session_snapshot(session)
                if snapshot["active"] and snapshot["device"] and snapshot["self"]:
                    connected_payload = {
                        "event": "connected",
                        "device": snapshot["device"],
                        "self": snapshot["self"],
                        "collections_ready": bool(snapshot.get("collections_ready")),
                        "contacts_count": snapshot.get("contacts_count"),
                        "contact_summary": snapshot.get("contact_summary") or {},
                        "channels_count": snapshot.get("channels_count"),
                        "recent_repeaters_count": snapshot.get("recent_repeaters_count"),
                        "radio_stats": snapshot["radio_stats"],
                        "self_telemetry": snapshot["self_telemetry"],
                        "battery_info": snapshot["battery_info"],
                    }
                    if bool(snapshot.get("collections_ready")):
                        connected_payload["contacts"] = snapshot.get("contacts") or []
                        connected_payload["channels"] = snapshot.get("channels") or []
                    self._sse(connected_payload)
            while True:
                try:
                    payload = sink.get(timeout=15.0)
                except queue.Empty:
                    self._sse({"event": "heartbeat"})
                    continue
                self._sse(payload)
        except (BrokenPipeError, ConnectionResetError):
            logging.info("sse disconnected port=%s", port)
            return
        except (sqlite3.Error, ValueError) as exc:
            logging.exception("sse failed port=%s error=%s", port, exc)
            try:
                self._sse({"event": "error", "message": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                return
        finally:
            _unregister_event_subscriber(port, sink)

    def _sse(self, payload: dict) -> None:
        message = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        if not self._write_response_body(message):
            raise BrokenPipeError("client disconnected during SSE write")
        self.wfile.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Meshcorium web client")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    return parser


def main() -> int:
    configure_logging()
    _migrate_named_db_files_if_needed()
    init_message_db()
    init_contact_db()
    try:
        sync_mobile_push_muted_conversations(
            DB_LOCK,
            CONTACTS_DB_PATH,
            muted_conversations=_get_client_settings().get("muted_conversations"),
        )
    except sqlite3.Error:
        logging.exception("failed to synchronize mobile push mute state on startup")
    args = build_parser().parse_args()
    _attempt_service_startup_auto_connect()
    server = ThreadingHTTPServer((args.host, args.port), MeshcoriumWebHandler)
    logging.info(
        "server starting host=%s port=%s log=%s messages_db=%s contacts_db=%s",
        args.host,
        args.port,
        _display_project_path(LOG_PATH),
        _display_project_path(DB_PATH),
        _display_project_path(CONTACTS_DB_PATH),
    )
    print(f"Meshcorium listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("server stopped by keyboard interrupt")
        return 130
    finally:
        server.server_close()
        logging.info("server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
