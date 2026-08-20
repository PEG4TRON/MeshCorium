from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable


def _now() -> int:
    return int(time.time())


def _public_key(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text) else ""


def _text(value: object) -> str:
    return str(value or "").strip()


def _ble_pin(value: object) -> str:
    text = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if text == "0":
        return ""
    return text if len(text) == 6 else ""


def _json_dict(value: object) -> str:
    if not isinstance(value, dict):
        value = {}
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json_dict(value: object) -> dict:
    try:
        payload = json.loads(str(value or "{}"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS known_nodes (
            public_key TEXT PRIMARY KEY,
            node_name TEXT NOT NULL DEFAULT '',
            manufacturer_model TEXT NOT NULL DEFAULT '',
            ble_address TEXT NOT NULL DEFAULT '',
            ble_adapter_id TEXT NOT NULL DEFAULT '',
            ble_pin_active TEXT NOT NULL DEFAULT '',
            ble_pin_pending TEXT NOT NULL DEFAULT '',
            ble_pin_previous TEXT NOT NULL DEFAULT '',
            ble_pin_custom INTEGER NOT NULL DEFAULT 0,
            ble_pin_managed INTEGER NOT NULL DEFAULT 1,
            ble_last_pair_repair_at INTEGER NOT NULL DEFAULT 0,
            ble_last_successful_pair_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            last_seen_at INTEGER NOT NULL DEFAULT 0,
            last_successful_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS known_node_transports (
            key TEXT PRIMARY KEY,
            public_key TEXT NOT NULL DEFAULT '',
            transport_type TEXT NOT NULL,
            transport_id TEXT NOT NULL,
            port TEXT NOT NULL DEFAULT '',
            baudrate INTEGER NOT NULL DEFAULT 0,
            timeout REAL NOT NULL DEFAULT 0,
            protocol_version INTEGER NOT NULL DEFAULT 0,
            app_version INTEGER NOT NULL DEFAULT 0,
            app_name TEXT NOT NULL DEFAULT '',
            display_label TEXT NOT NULL DEFAULT '',
            adapter_id TEXT NOT NULL DEFAULT '',
            connection_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            last_successful_at INTEGER NOT NULL DEFAULT 0,
            last_attempted_at INTEGER NOT NULL DEFAULT 0,
            attempted_only INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_known_node_transports_public_key
        ON known_node_transports(public_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_known_node_transports_endpoint
        ON known_node_transports(transport_type, transport_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_known_nodes_ble_address
        ON known_nodes(ble_address)
        """
    )
    conn.commit()


def record_successful_connection(
    conn: sqlite3.Connection,
    *,
    key: str,
    config: dict,
    self_info: dict | None = None,
    device_info: dict | None = None,
    pin: object = "",
) -> dict:
    conn.row_factory = sqlite3.Row
    now_ts = _now()
    public_key = _public_key((self_info or {}).get("public_key"))
    transport_type = _text(config.get("transport_type") or "serial").lower() or "serial"
    transport_id = _text(config.get("transport_id") or config.get("port"))
    connection = dict(config.get("connection") or {})
    connection.pop("pin", None)
    node_name = _text((self_info or {}).get("name"))
    manufacturer_model = _text((device_info or {}).get("manufacturer_model"))
    active_pin = _ble_pin(pin) or _ble_pin((device_info or {}).get("ble_pin"))
    adapter_id = _text(connection.get("adapter_id") or config.get("adapter_id"))

    if public_key:
        existing = conn.execute(
            "SELECT created_at, ble_pin_active, ble_pin_pending, ble_pin_previous, ble_pin_custom FROM known_nodes WHERE public_key = ?",
            (public_key,),
        ).fetchone()
        created_at = int(existing["created_at"] or now_ts) if existing else now_ts
        existing_pin_active = ""
        existing_pin_pending = ""
        existing_pin_previous = ""
        existing_pin_custom = 0
        if existing:
            existing_pin_active = str(existing["ble_pin_active"] or "")
            existing_pin_pending = str(existing["ble_pin_pending"] or "")
            existing_pin_previous = str(existing["ble_pin_previous"] or "")
            existing_pin_custom = int(existing["ble_pin_custom"] or 0)
        next_pin_active = active_pin or existing_pin_active
        conn.execute(
            """
            INSERT INTO known_nodes (
                public_key, node_name, manufacturer_model, ble_address, ble_adapter_id,
                ble_pin_active, ble_pin_pending, ble_pin_previous, ble_pin_custom,
                ble_pin_managed, created_at, updated_at, last_seen_at, last_successful_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_key) DO UPDATE SET
                node_name = excluded.node_name,
                manufacturer_model = COALESCE(NULLIF(excluded.manufacturer_model, ''), known_nodes.manufacturer_model),
                ble_address = CASE WHEN excluded.ble_address != '' THEN excluded.ble_address ELSE known_nodes.ble_address END,
                ble_adapter_id = CASE WHEN excluded.ble_adapter_id != '' THEN excluded.ble_adapter_id ELSE known_nodes.ble_adapter_id END,
                ble_pin_active = CASE WHEN excluded.ble_pin_active != '' THEN excluded.ble_pin_active ELSE known_nodes.ble_pin_active END,
                ble_pin_pending = CASE WHEN excluded.ble_pin_active != '' THEN '' ELSE known_nodes.ble_pin_pending END,
                ble_pin_previous = CASE
                    WHEN excluded.ble_pin_active != '' AND known_nodes.ble_pin_active != '' AND excluded.ble_pin_active != known_nodes.ble_pin_active
                    THEN known_nodes.ble_pin_active
                    ELSE known_nodes.ble_pin_previous
                END,
                updated_at = excluded.updated_at,
                last_seen_at = excluded.last_seen_at,
                last_successful_at = excluded.last_successful_at
            """,
            (
                public_key,
                node_name,
                manufacturer_model,
                transport_id if transport_type == "ble" else "",
                adapter_id if transport_type == "ble" else "",
                next_pin_active,
                existing_pin_pending,
                existing_pin_previous,
                existing_pin_custom,
                1,
                created_at,
                now_ts,
                now_ts,
                now_ts,
            ),
        )

    conn.execute(
        """
        INSERT INTO known_node_transports (
            key, public_key, transport_type, transport_id, port, baudrate, timeout,
            protocol_version, app_version, app_name, display_label, adapter_id,
            connection_json, metadata_json, created_at, updated_at,
            last_successful_at, last_attempted_at, attempted_only
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(key) DO UPDATE SET
            public_key = excluded.public_key,
            transport_type = excluded.transport_type,
            transport_id = excluded.transport_id,
            port = excluded.port,
            baudrate = excluded.baudrate,
            timeout = excluded.timeout,
            protocol_version = excluded.protocol_version,
            app_version = excluded.app_version,
            app_name = excluded.app_name,
            display_label = excluded.display_label,
            adapter_id = excluded.adapter_id,
            connection_json = excluded.connection_json,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at,
            last_successful_at = excluded.last_successful_at,
            last_attempted_at = excluded.last_attempted_at,
            attempted_only = 0
        """,
        (
            key,
            public_key,
            transport_type,
            transport_id,
            _text(config.get("port") or transport_id),
            int(config.get("baudrate") or 0),
            float(config.get("timeout") or 0),
            int(config.get("protocol_version") or 0),
            int(config.get("app_version") or 0),
            _text(config.get("app_name")),
            _text(connection.get("display_label") or config.get("display_label") or transport_id),
            adapter_id,
            _json_dict(connection),
            _json_dict({"manufacturer_model": manufacturer_model}),
            now_ts,
            now_ts,
            now_ts,
            now_ts,
        ),
    )
    conn.commit()
    return get_transport(conn, key) or {}


def list_successful_connections(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            t.*,
            n.node_name,
            n.manufacturer_model,
            n.ble_pin_custom
        FROM known_node_transports AS t
        LEFT JOIN known_nodes AS n ON n.public_key = t.public_key
        WHERE t.attempted_only = 0 AND t.last_successful_at > 0
        ORDER BY t.last_successful_at DESC, t.updated_at DESC
        """
    ).fetchall()
    return [_transport_row_to_dict(row) for row in rows]


def get_transport(conn: sqlite3.Connection, key: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT t.*, n.node_name, n.manufacturer_model, n.ble_pin_custom
        FROM known_node_transports AS t
        LEFT JOIN known_nodes AS n ON n.public_key = t.public_key
        WHERE t.key = ?
        """,
        (str(key or "").strip(),),
    ).fetchone()
    return _transport_row_to_dict(row) if row else None


def forget_connection(conn: sqlite3.Connection, key: object) -> None:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return
    row = conn.execute("SELECT public_key FROM known_node_transports WHERE key = ?", (normalized_key,)).fetchone()
    public_key = str(row[0] or "") if row else ""
    conn.execute("DELETE FROM known_node_transports WHERE key = ?", (normalized_key,))
    if public_key:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM known_node_transports WHERE public_key = ?",
            (public_key,),
        ).fetchone()[0]
        if not int(remaining or 0):
            conn.execute("DELETE FROM known_nodes WHERE public_key = ?", (public_key,))
    conn.commit()


def find_latest_successful_config(conn: sqlite3.Connection) -> dict | None:
    items = list_successful_connections(conn)
    return _entry_config(items[0]) if items else None


def find_config_by_key(conn: sqlite3.Connection, key: object) -> dict | None:
    item = get_transport(conn, str(key or "").strip())
    if not item or int(item.get("last_connected_at") or 0) <= 0:
        return None
    return _entry_config(item)


def get_ble_pin_for_address(conn: sqlite3.Connection, address: object) -> str:
    normalized = _text(address).upper()
    if not normalized:
        return ""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT n.ble_pin_active, n.ble_pin_pending, n.ble_pin_previous
        FROM known_nodes AS n
        JOIN known_node_transports AS t ON t.public_key = n.public_key
        WHERE lower(n.ble_address) = lower(?) OR (t.transport_type = 'ble' AND lower(t.transport_id) = lower(?))
        ORDER BY t.last_successful_at DESC, n.updated_at DESC
        LIMIT 1
        """,
        (normalized, normalized),
    ).fetchone()
    if not row:
        return ""
    return _ble_pin(row["ble_pin_active"]) or _ble_pin(row["ble_pin_pending"]) or _ble_pin(row["ble_pin_previous"])


def get_ble_pin(conn: sqlite3.Connection, *, public_key: object = "", address: object = "") -> str:
    normalized_public_key = _public_key(public_key)
    normalized_address = _text(address).upper()
    conn.row_factory = sqlite3.Row
    if normalized_public_key:
        row = conn.execute(
            """
            SELECT ble_pin_active, ble_pin_pending, ble_pin_previous
            FROM known_nodes
            WHERE public_key = ?
            LIMIT 1
            """,
            (normalized_public_key,),
        ).fetchone()
        if row:
            resolved = _ble_pin(row["ble_pin_active"]) or _ble_pin(row["ble_pin_pending"]) or _ble_pin(row["ble_pin_previous"])
            if resolved:
                return resolved
    if normalized_address:
        return get_ble_pin_for_address(conn, normalized_address)
    return ""


def is_ble_pin_custom(conn: sqlite3.Connection, *, public_key: object = "", address: object = "") -> bool:
    normalized_public_key = _public_key(public_key)
    normalized_address = _text(address)
    if not normalized_public_key and not normalized_address:
        return False
    conn.row_factory = sqlite3.Row
    if normalized_public_key:
        row = conn.execute("SELECT ble_pin_custom FROM known_nodes WHERE public_key = ?", (normalized_public_key,)).fetchone()
    else:
        row = conn.execute("SELECT ble_pin_custom FROM known_nodes WHERE lower(ble_address) = lower(?)", (normalized_address,)).fetchone()
    return bool(row and int(row["ble_pin_custom"] or 0))


def mark_ble_pin_custom(conn: sqlite3.Connection, *, public_key: object, address: object = "", pin: object = "") -> None:
    normalized_public_key = _public_key(public_key)
    if not normalized_public_key:
        return
    now_ts = _now()
    active_pin = _ble_pin(pin)
    conn.execute(
        """
        INSERT INTO known_nodes (
            public_key, ble_address, ble_pin_active, ble_pin_custom, ble_pin_managed,
            created_at, updated_at, last_seen_at
        )
        VALUES (?, ?, ?, 1, 0, ?, ?, ?)
        ON CONFLICT(public_key) DO UPDATE SET
            ble_address = CASE WHEN excluded.ble_address != '' THEN excluded.ble_address ELSE known_nodes.ble_address END,
            ble_pin_active = CASE WHEN excluded.ble_pin_active != '' THEN excluded.ble_pin_active ELSE known_nodes.ble_pin_active END,
            ble_pin_pending = '',
            ble_pin_custom = 1,
            ble_pin_managed = 0,
            updated_at = excluded.updated_at,
            last_seen_at = excluded.last_seen_at
        """,
        (normalized_public_key, _text(address), active_pin, now_ts, now_ts, now_ts),
    )
    conn.commit()


def begin_ble_pin_rotation(conn: sqlite3.Connection, *, public_key: object, address: object, next_pin: object) -> None:
    normalized_public_key = _public_key(public_key)
    if not normalized_public_key:
        return
    now_ts = _now()
    conn.execute(
        """
        INSERT INTO known_nodes (
            public_key, ble_address, ble_pin_pending, ble_pin_managed,
            created_at, updated_at, last_seen_at
        )
        VALUES (?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(public_key) DO UPDATE SET
            ble_address = CASE WHEN excluded.ble_address != '' THEN excluded.ble_address ELSE known_nodes.ble_address END,
            ble_pin_pending = excluded.ble_pin_pending,
            ble_pin_managed = 1,
            updated_at = excluded.updated_at,
            last_seen_at = excluded.last_seen_at
        """,
        (normalized_public_key, _text(address), _ble_pin(next_pin), now_ts, now_ts, now_ts),
    )
    conn.commit()


def commit_ble_pin_rotation(conn: sqlite3.Connection, *, public_key: object, next_pin: object) -> None:
    normalized_public_key = _public_key(public_key)
    active_pin = _ble_pin(next_pin)
    if not normalized_public_key or not active_pin:
        return
    now_ts = _now()
    conn.execute(
        """
        UPDATE known_nodes
        SET ble_pin_previous = CASE
                WHEN ble_pin_active != '' AND ble_pin_active != ? THEN ble_pin_active
                ELSE ble_pin_previous
            END,
            ble_pin_active = ?,
            ble_pin_pending = '',
            ble_pin_custom = 0,
            ble_pin_managed = 1,
            updated_at = ?,
            last_seen_at = ?
        WHERE public_key = ?
        """,
        (active_pin, active_pin, now_ts, now_ts, normalized_public_key),
    )
    conn.commit()


def rollback_ble_pin_rotation(conn: sqlite3.Connection, *, public_key: object) -> None:
    normalized_public_key = _public_key(public_key)
    if not normalized_public_key:
        return
    now_ts = _now()
    conn.execute(
        """
        UPDATE known_nodes
        SET ble_pin_pending = '',
            updated_at = ?,
            last_seen_at = ?
        WHERE public_key = ?
        """,
        (now_ts, now_ts, normalized_public_key),
    )
    conn.commit()


def migrate_saved_connections(conn: sqlite3.Connection, entries: Iterable[dict]) -> int:
    migrated = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = _text(entry.get("key"))
        if not key:
            continue
        config = {
            "port": _text(entry.get("port") or entry.get("transport_id")),
            "baudrate": int(entry.get("baudrate") or 0),
            "timeout": float(entry.get("timeout") or 0),
            "protocol_version": int(entry.get("protocol_version") or 0),
            "app_version": int(entry.get("app_version") or 0),
            "app_name": _text(entry.get("app_name")),
            "transport_type": _text(entry.get("transport_type") or entry.get("connection_type") or "serial").lower(),
            "transport_id": _text(entry.get("transport_id") or entry.get("port")),
            "connection": dict(entry.get("connection") or {}),
        }
        self_info = {
            "public_key": _public_key(entry.get("public_key")),
            "name": _text(entry.get("node_name")),
        }
        device_info = {"manufacturer_model": _text(entry.get("manufacturer_model"))}
        record_successful_connection(conn, key=key, config=config, self_info=self_info, device_info=device_info)
        migrated += 1
    return migrated


def _transport_row_to_dict(row: sqlite3.Row) -> dict:
    connection = _load_json_dict(row["connection_json"])
    metadata = _load_json_dict(row["metadata_json"])
    transport_type = _text(row["transport_type"]) or "serial"
    transport_id = _text(row["transport_id"] or row["port"])
    node_name = _text(row["node_name"])
    manufacturer_model = _text(row["manufacturer_model"] or metadata.get("manufacturer_model"))
    return {
        "key": _text(row["key"]),
        "port": _text(row["port"] or transport_id),
        "baudrate": int(row["baudrate"] or 0),
        "timeout": float(row["timeout"] or 0),
        "protocol_version": int(row["protocol_version"] or 0),
        "app_version": int(row["app_version"] or 0),
        "app_name": _text(row["app_name"]),
        "transport_type": transport_type,
        "transport_id": transport_id,
        "display_label": _text(row["display_label"] or connection.get("display_label") or transport_id),
        "connection": connection,
        "node_name": node_name,
        "public_key": _text(row["public_key"]),
        "manufacturer_model": manufacturer_model,
        "connection_type": "usb" if transport_type == "serial" else transport_type,
        "last_connected_at": int(row["last_successful_at"] or 0),
        "last_attempted_at": int(row["last_attempted_at"] or 0),
        "attempted_only": bool(row["attempted_only"]),
        "ble_pin_custom": bool(row["ble_pin_custom"]) if "ble_pin_custom" in row.keys() else False,
    }


def _entry_config(entry: dict) -> dict:
    return {
        "port": entry["port"],
        "baudrate": int(entry["baudrate"]),
        "timeout": float(entry["timeout"]),
        "protocol_version": int(entry["protocol_version"]),
        "app_version": int(entry["app_version"]),
        "app_name": str(entry["app_name"] or ""),
        "transport_type": str(entry["transport_type"] or "serial"),
        "transport_id": str(entry["transport_id"] or entry["port"]),
        "connection": dict(entry.get("connection") or {}),
    }
