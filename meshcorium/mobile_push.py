from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_SERVICE_ACCOUNT_FILENAME = "firebase_service_account.json"
PUSH_CHANNEL_ID = "meshcorium_messages"

_ACCESS_TOKEN_LOCK = threading.Lock()
_ACCESS_TOKEN_CACHE: dict[str, object] = {
    "token": "",
    "expires_at": 0,
    "project_id": "",
    "client_email": "",
}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, spec: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {spec}")


def init_mobile_push_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mobile_push_devices (
            installation_id TEXT PRIMARY KEY,
            fcm_token TEXT NOT NULL,
            base_url TEXT NOT NULL DEFAULT '',
            device_label TEXT NOT NULL DEFAULT '',
            app_version TEXT NOT NULL DEFAULT '',
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            muted_regular_keys TEXT NOT NULL DEFAULT '[]',
            muted_all_keys TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_token_refresh_at INTEGER NOT NULL,
            last_push_sent_at INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            last_message_key TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_push_devices_token
        ON mobile_push_devices(fcm_token)
        """
    )
    _ensure_column(conn, "mobile_push_devices", "base_url", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "mobile_push_devices", "device_label", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "mobile_push_devices", "app_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "mobile_push_devices", "notifications_enabled", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "mobile_push_devices", "muted_regular_keys", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "mobile_push_devices", "muted_all_keys", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "mobile_push_devices", "created_at", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "mobile_push_devices", "updated_at", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "mobile_push_devices", "last_token_refresh_at", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "mobile_push_devices", "last_push_sent_at", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "mobile_push_devices", "last_error", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "mobile_push_devices", "last_message_key", "TEXT NOT NULL DEFAULT ''")


def register_mobile_push_device(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    installation_id: str,
    fcm_token: str,
    base_url: str = "",
    device_label: str = "",
    app_version: str = "",
    notifications_enabled: bool = True,
    muted_regular_keys: list[str] | tuple[str, ...] | None = None,
    muted_all_keys: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    normalized_installation_id = str(installation_id or "").strip()
    normalized_token = str(fcm_token or "").strip()
    if not normalized_installation_id:
        raise ValueError("installation_id is required")
    if not normalized_token:
        raise ValueError("fcm_token is required")
    normalized_muted_regular_keys = _normalize_mobile_push_mute_keys(muted_regular_keys)
    normalized_muted_all_keys = _normalize_mobile_push_mute_keys(muted_all_keys)
    now = int(time.time())
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        conn.execute(
            "DELETE FROM mobile_push_devices WHERE fcm_token = ? AND installation_id != ?",
            (normalized_token, normalized_installation_id),
        )
        conn.execute(
            """
            INSERT INTO mobile_push_devices (
                installation_id,
                fcm_token,
                base_url,
                device_label,
                app_version,
                notifications_enabled,
                muted_regular_keys,
                muted_all_keys,
                created_at,
                updated_at,
                last_token_refresh_at,
                last_push_sent_at,
                last_error,
                last_message_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', '')
            ON CONFLICT(installation_id) DO UPDATE SET
                fcm_token = excluded.fcm_token,
                base_url = excluded.base_url,
                device_label = excluded.device_label,
                app_version = excluded.app_version,
                notifications_enabled = excluded.notifications_enabled,
                muted_regular_keys = excluded.muted_regular_keys,
                muted_all_keys = excluded.muted_all_keys,
                updated_at = excluded.updated_at,
                last_token_refresh_at = excluded.last_token_refresh_at
            """,
            (
                normalized_installation_id,
                normalized_token,
                str(base_url or "").strip(),
                str(device_label or "").strip(),
                str(app_version or "").strip(),
                1 if notifications_enabled else 0,
                json.dumps(normalized_muted_regular_keys, ensure_ascii=True),
                json.dumps(normalized_muted_all_keys, ensure_ascii=True),
                now,
                now,
                now,
            ),
        )
        conn.commit()
    return {
        "installation_id": normalized_installation_id,
        "base_url": str(base_url or "").strip(),
        "device_label": str(device_label or "").strip(),
        "app_version": str(app_version or "").strip(),
        "notifications_enabled": bool(notifications_enabled),
        "muted_regular_keys": normalized_muted_regular_keys,
        "muted_all_keys": normalized_muted_all_keys,
        "updated_at": now,
    }


def sync_mobile_push_muted_conversations(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    muted_conversations: dict[str, str] | None,
) -> dict[str, object]:
    normalized_map: dict[str, str] = {}
    for raw_key, raw_mode in dict(muted_conversations or {}).items():
        key = str(raw_key or "").strip().lower()
        mode = str(raw_mode or "").strip().lower()
        if not key:
            continue
        if mode == "all":
            normalized_map[key] = "all"
        elif mode == "regular" and normalized_map.get(key) != "all":
            normalized_map[key] = "regular"
    muted_regular_keys = _normalize_mobile_push_mute_keys(
        [key for key, mode in normalized_map.items() if mode in {"regular", "all"}]
    )
    muted_all_keys = _normalize_mobile_push_mute_keys(
        [key for key, mode in normalized_map.items() if mode == "all"]
    )
    now = int(time.time())
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        cursor = conn.execute(
            """
            UPDATE mobile_push_devices
            SET muted_regular_keys = ?, muted_all_keys = ?, updated_at = ?
            """,
            (
                json.dumps(muted_regular_keys, ensure_ascii=True),
                json.dumps(muted_all_keys, ensure_ascii=True),
                now,
            ),
        )
        conn.commit()
    return {
        "updated_devices": int(cursor.rowcount or 0),
        "muted_regular_keys": muted_regular_keys,
        "muted_all_keys": muted_all_keys,
        "updated_at": now,
    }


def unregister_mobile_push_device(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    installation_id: str = "",
    fcm_token: str = "",
) -> int:
    normalized_installation_id = str(installation_id or "").strip()
    normalized_token = str(fcm_token or "").strip()
    if not normalized_installation_id and not normalized_token:
        raise ValueError("installation_id or fcm_token is required")
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        if normalized_installation_id and normalized_token:
            cursor = conn.execute(
                """
                DELETE FROM mobile_push_devices
                WHERE installation_id = ? OR fcm_token = ?
                """,
                (normalized_installation_id, normalized_token),
            )
        elif normalized_installation_id:
            cursor = conn.execute(
                "DELETE FROM mobile_push_devices WHERE installation_id = ?",
                (normalized_installation_id,),
            )
        else:
            cursor = conn.execute(
                "DELETE FROM mobile_push_devices WHERE fcm_token = ?",
                (normalized_token,),
            )
        conn.commit()
        return int(cursor.rowcount or 0)


def list_mobile_push_devices(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
) -> list[dict[str, object]]:
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                installation_id,
                base_url,
                device_label,
                app_version,
                notifications_enabled,
                muted_regular_keys,
                muted_all_keys,
                created_at,
                updated_at,
                last_token_refresh_at,
                last_push_sent_at,
                last_error,
                last_message_key
            FROM mobile_push_devices
            ORDER BY updated_at DESC, installation_id ASC
            """
        ).fetchall()
    return [
        {
            "installation_id": str(row["installation_id"] or ""),
            "base_url": str(row["base_url"] or ""),
            "device_label": str(row["device_label"] or ""),
            "app_version": str(row["app_version"] or ""),
            "notifications_enabled": bool(row["notifications_enabled"]),
            "muted_regular_keys": _parse_mobile_push_mute_keys(row["muted_regular_keys"]),
            "muted_all_keys": _parse_mobile_push_mute_keys(row["muted_all_keys"]),
            "created_at": int(row["created_at"] or 0),
            "updated_at": int(row["updated_at"] or 0),
            "last_token_refresh_at": int(row["last_token_refresh_at"] or 0),
            "last_push_sent_at": int(row["last_push_sent_at"] or 0),
            "last_error": str(row["last_error"] or ""),
            "last_message_key": str(row["last_message_key"] or ""),
        }
        for row in rows
    ]


def build_mobile_push_status(
    project_root: str | os.PathLike[str],
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
) -> dict[str, object]:
    service_account_path = resolve_service_account_path(project_root)
    credentials = _load_service_account(service_account_path)
    devices = list_mobile_push_devices(db_lock, db_path)
    return {
        "configured": credentials is not None,
        "service_account_path": str(service_account_path),
        "service_account_exists": service_account_path.is_file(),
        "project_id": str((credentials or {}).get("project_id") or ""),
        "registered_devices_count": len(devices),
        "devices": devices,
    }


def send_mobile_push_notification(
    project_root: str | os.PathLike[str],
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    title: str,
    body: str,
    data: dict[str, object] | None = None,
    dedupe_key: str = "",
) -> dict[str, int | bool | str]:
    normalized_title = str(title or "").strip()
    normalized_body = str(body or "").strip()
    payload_data = {str(key): str(value) for key, value in dict(data or {}).items() if value is not None}
    payload_data.setdefault("title", normalized_title)
    payload_data.setdefault("body", normalized_body)
    service_account_path = resolve_service_account_path(project_root)
    credentials = _load_service_account(service_account_path)
    if credentials is None:
        return {
            "configured": False,
            "attempted": 0,
            "sent": 0,
            "failed": 0,
            "skipped_duplicate": 0,
            "removed_invalid_tokens": 0,
            "error": "firebase_service_account.json not configured",
        }
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        conn.row_factory = sqlite3.Row
        device_rows = conn.execute(
            """
            SELECT installation_id, fcm_token, last_message_key, muted_regular_keys, muted_all_keys
            FROM mobile_push_devices
            WHERE notifications_enabled = 1 AND length(trim(fcm_token)) > 0
            ORDER BY updated_at DESC, installation_id ASC
            """
        ).fetchall()
    if not device_rows:
        return {
            "configured": True,
            "attempted": 0,
            "sent": 0,
            "failed": 0,
            "skipped_duplicate": 0,
            "removed_invalid_tokens": 0,
            "error": "",
        }
    try:
        access_token = _get_access_token(credentials)
    except (OSError, ValueError, KeyError, urllib.error.HTTPError) as exc:
        logging.warning("mobile push access-token fetch failed error=%s", exc)
        return {
            "configured": True,
            "attempted": len(device_rows),
            "sent": 0,
            "failed": len(device_rows),
            "skipped_duplicate": 0,
            "removed_invalid_tokens": 0,
            "error": str(exc),
        }
    sent = 0
    failed = 0
    skipped_duplicate = 0
    removed_invalid_tokens = 0
    now = int(time.time())
    for row in device_rows:
        installation_id = str(row["installation_id"] or "")
        fcm_token = str(row["fcm_token"] or "")
        last_message_key = str(row["last_message_key"] or "")
        muted_regular_keys = set(_parse_mobile_push_mute_keys(row["muted_regular_keys"]))
        muted_all_keys = set(_parse_mobile_push_mute_keys(row["muted_all_keys"]))
        if dedupe_key and dedupe_key == last_message_key:
            skipped_duplicate += 1
            continue
        mute_key = _resolve_mobile_push_mute_key(payload_data)
        is_mention = str(payload_data.get("mention") or "").strip() == "1"
        if mute_key:
            if mute_key in muted_all_keys:
                continue
            if not is_mention and mute_key in muted_regular_keys:
                continue
        try:
            _send_fcm_message(
                credentials=credentials,
                access_token=access_token,
                fcm_token=fcm_token,
                data=payload_data,
            )
        except urllib.error.HTTPError as exc:
            error_body = _safe_http_error_body(exc)
            failed += 1
            _update_push_error(
                db_lock,
                db_path,
                installation_id=installation_id,
                error=f"{exc.code} {error_body}".strip(),
            )
            if exc.code in {404, 410} or "UNREGISTERED" in error_body or "registration-token-not-registered" in error_body:
                removed_invalid_tokens += unregister_mobile_push_device(
                    db_lock,
                    db_path,
                    installation_id=installation_id,
                )
            logging.warning(
                "mobile push send failed installation_id=%s code=%s body=%s",
                installation_id,
                exc.code,
                error_body,
            )
        except (OSError, ValueError, KeyError) as exc:
            failed += 1
            _update_push_error(
                db_lock,
                db_path,
                installation_id=installation_id,
                error=str(exc),
            )
            logging.warning(
                "mobile push send failed installation_id=%s error=%s",
                installation_id,
                exc,
            )
        else:
            sent += 1
            _mark_push_sent(
                db_lock,
                db_path,
                installation_id=installation_id,
                sent_at=now,
                dedupe_key=dedupe_key,
            )
    return {
        "configured": True,
        "attempted": len(device_rows),
        "sent": sent,
        "failed": failed,
        "skipped_duplicate": skipped_duplicate,
        "removed_invalid_tokens": removed_invalid_tokens,
        "error": "",
    }


def _normalize_mobile_push_mute_keys(keys: list[str] | tuple[str, ...] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_key in keys or []:
        key = str(raw_key or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _parse_mobile_push_mute_keys(raw_value: object) -> list[str]:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return []
    try:
        parsed = json.loads(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return _normalize_mobile_push_mute_keys([str(item or "") for item in parsed])


def _resolve_mobile_push_mute_key(payload_data: dict[str, str]) -> str:
    kind = str(payload_data.get("kind") or "").strip().lower()
    if kind == "channel":
        channel_idx = str(payload_data.get("channel_idx") or "").strip()
        return f"channel:{channel_idx}" if channel_idx else ""
    if kind == "contact":
        pubkey_prefix = str(payload_data.get("pubkey_prefix") or "").strip().lower()[:12]
        return f"contact:{pubkey_prefix}" if pubkey_prefix else ""
    return ""


def resolve_service_account_path(project_root: str | os.PathLike[str]) -> Path:
    override = str(os.getenv("MESHCORIUM_FCM_SERVICE_ACCOUNT_JSON") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path(project_root) / "data" / DEFAULT_SERVICE_ACCOUNT_FILENAME


def _load_service_account(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logging.exception("failed to read firebase service account path=%s", path)
        return None
    required = ("project_id", "client_email", "private_key")
    if not all(str(raw.get(key) or "").strip() for key in required):
        logging.warning("firebase service account is missing required fields path=%s", path)
        return None
    return {
        "project_id": str(raw.get("project_id") or "").strip(),
        "client_email": str(raw.get("client_email") or "").strip(),
        "private_key": str(raw.get("private_key") or ""),
        "token_uri": str(raw.get("token_uri") or FCM_DEFAULT_TOKEN_URI).strip(),
    }


def _send_fcm_message(
    *,
    credentials: dict[str, str],
    access_token: str,
    fcm_token: str,
    data: dict[str, str],
) -> None:
    project_id = str(credentials["project_id"])
    request_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    payload = {
        "message": {
            "token": str(fcm_token),
            "android": {
                "priority": "high",
            },
            "data": data,
        }
    }
    request = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def _get_access_token(credentials: dict[str, str]) -> str:
    now = int(time.time())
    with _ACCESS_TOKEN_LOCK:
        cached_token = str(_ACCESS_TOKEN_CACHE.get("token") or "")
        cached_expires_at = int(_ACCESS_TOKEN_CACHE.get("expires_at") or 0)
        cached_project_id = str(_ACCESS_TOKEN_CACHE.get("project_id") or "")
        cached_client_email = str(_ACCESS_TOKEN_CACHE.get("client_email") or "")
        if (
            cached_token
            and cached_expires_at - 60 > now
            and cached_project_id == str(credentials.get("project_id") or "")
            and cached_client_email == str(credentials.get("client_email") or "")
        ):
            return cached_token
        token, expires_at = _fetch_access_token(credentials, now)
        _ACCESS_TOKEN_CACHE.update(
            {
                "token": token,
                "expires_at": expires_at,
                "project_id": str(credentials.get("project_id") or ""),
                "client_email": str(credentials.get("client_email") or ""),
            }
        )
        return token


def _fetch_access_token(credentials: dict[str, str], now: int) -> tuple[str, int]:
    assertion = _build_jwt_assertion(credentials, now)
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        str(credentials.get("token_uri") or FCM_DEFAULT_TOKEN_URI),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8"))
    access_token = str(raw.get("access_token") or "").strip()
    expires_in = int(raw.get("expires_in") or 3600)
    if not access_token:
        raise ValueError("failed to obtain firebase access token")
    return access_token, now + max(60, expires_in)


def _build_jwt_assertion(credentials: dict[str, str], now: int) -> str:
    header = _b64url_json({"alg": "RS256", "typ": "JWT"})
    claims = _b64url_json(
        {
            "iss": str(credentials["client_email"]),
            "scope": FCM_SCOPE,
            "aud": str(credentials.get("token_uri") or FCM_DEFAULT_TOKEN_URI),
            "iat": now,
            "exp": now + 3600,
        }
    )
    signing_input = f"{header}.{claims}".encode("utf-8")
    private_key = serialization.load_pem_private_key(
        str(credentials["private_key"]).encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{header}.{claims}.{_b64url(signature)}"


def _b64url_json(payload: dict[str, object]) -> str:
    return _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _safe_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _mark_push_sent(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    installation_id: str,
    sent_at: int,
    dedupe_key: str,
) -> None:
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        conn.execute(
            """
            UPDATE mobile_push_devices
            SET
                last_push_sent_at = ?,
                updated_at = ?,
                last_error = '',
                last_message_key = CASE WHEN ? != '' THEN ? ELSE last_message_key END
            WHERE installation_id = ?
            """,
            (int(sent_at), int(sent_at), str(dedupe_key or ""), str(dedupe_key or ""), str(installation_id or "")),
        )
        conn.commit()


def _update_push_error(
    db_lock: threading.Lock,
    db_path: str | os.PathLike[str],
    *,
    installation_id: str,
    error: str,
) -> None:
    now = int(time.time())
    with db_lock, sqlite3.connect(db_path) as conn:
        init_mobile_push_db_schema(conn)
        conn.execute(
            """
            UPDATE mobile_push_devices
            SET updated_at = ?, last_error = ?
            WHERE installation_id = ?
            """,
            (now, str(error or "").strip(), str(installation_id or "")),
        )
        conn.commit()
