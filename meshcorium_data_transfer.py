from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable

PACKAGE_FORMAT = "meshcorium-data-transfer"
PACKAGE_VERSION = 1
DEFAULT_CHANNEL_SLOT_LIMIT = 40
MAX_PREVIEW_CONFLICTS = 200

CATEGORY_CONTACTS = "contacts"
CATEGORY_CHANNEL_DIALOGS = "channel_dialogs"
CATEGORY_DIRECT_DIALOGS = "direct_dialogs"
CATEGORY_KNOWN_NODES = "known_nodes"
CATEGORY_SIGNAL_METRICS = "signal_metrics"

ALL_CATEGORIES = (
    CATEGORY_CONTACTS,
    CATEGORY_CHANNEL_DIALOGS,
    CATEGORY_DIRECT_DIALOGS,
    CATEGORY_KNOWN_NODES,
    CATEGORY_SIGNAL_METRICS,
)

CONTACTS_CACHE_COLUMNS = (
    "owner_id",
    "public_key",
    "adv_type",
    "flags",
    "path_len_byte",
    "out_path_len",
    "out_path_hash_len",
    "out_path",
    "adv_name",
    "last_advert",
    "adv_lat_raw",
    "adv_lon_raw",
    "lat",
    "lon",
    "has_location",
    "lastmod",
    "raw_payload_hex",
    "updated_at",
    "last_interaction_at",
    "last_public_traffic_at",
    "last_public_advert_at",
    "last_public_advert_mode",
    "last_materialized_at",
    "last_removed_from_node_at",
    "repeater_auth_password",
    "repeater_auth_saved_at",
    "is_local_self",
)
CONTACT_GROUP_COLUMNS = ("name",)
CONTACT_GROUP_TAG_COLUMNS = ("group_name", "public_key")
CHANNEL_MESSAGE_COLUMNS = (
    "owner_id",
    "message_kind",
    "channel_idx",
    "channel_identity",
    "from_self",
    "send_status",
    "expected_ack_hex",
    "acked_at",
    "sender_timestamp",
    "received_at",
    "snr",
    "path_len",
    "path_hashes",
    "txt_type",
    "text",
    "payload_hex",
    "is_read",
    "is_mention_read",
)
DIRECT_MESSAGE_COLUMNS = (
    "owner_id",
    "pubkey_prefix",
    "from_self",
    "send_status",
    "expected_ack_hex",
    "acked_at",
    "sender_timestamp",
    "received_at",
    "snr",
    "path_len",
    "path_hashes",
    "txt_type",
    "text",
    "payload_hex",
    "signature_hex",
    "is_read",
    "is_mention_read",
)
SIGNAL_METRIC_COLUMNS = (
    "owner_id",
    "recorded_at",
    "snr",
    "noise_floor",
    "repeaters",
)
CHANNEL_SLOT_COLUMNS = (
    "owner_id",
    "channel_idx",
    "channel_name",
    "channel_secret_hex",
    "channel_hash",
    "channel_identity",
    "is_public",
    "last_seen_at",
)
KNOWN_NODE_COLUMNS = (
    "public_key",
    "node_name",
    "manufacturer_model",
    "ble_address",
    "ble_adapter_id",
    "ble_pin_active",
    "ble_pin_pending",
    "ble_pin_previous",
    "ble_pin_custom",
    "ble_pin_managed",
    "ble_last_pair_repair_at",
    "ble_last_successful_pair_at",
    "created_at",
    "updated_at",
    "last_seen_at",
    "last_successful_at",
)
KNOWN_NODE_TRANSPORT_COLUMNS = (
    "key",
    "public_key",
    "transport_type",
    "transport_id",
    "port",
    "baudrate",
    "timeout",
    "protocol_version",
    "app_version",
    "app_name",
    "display_label",
    "adapter_id",
    "connection_json",
    "metadata_json",
    "created_at",
    "updated_at",
    "last_successful_at",
    "last_attempted_at",
    "attempted_only",
)


def _now() -> int:
    return int(time.time())


def _normalize_categories(values: Iterable[object] | None) -> list[str]:
    normalized: list[str] = []
    for value in list(values or []):
        key = str(value or "").strip().lower()
        if key in ALL_CATEGORIES and key not in normalized:
            normalized.append(key)
    return normalized or list(ALL_CATEGORIES)


def _text(value: object) -> str:
    return str(value or "").strip()


def _lower_text(value: object) -> str:
    return _text(value).lower()


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default)


def _float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_int(value: object) -> int:
    return 1 if bool(value) else 0


def _owner_id(value: object) -> str:
    normalized = _lower_text(value)
    return normalized if len(normalized) == 64 else ""


def _channel_name(value: object) -> str:
    return _text(value)


def _channel_secret_hex(value: object) -> str:
    normalized = "".join(ch for ch in str(value or "").strip().lower() if ch in "0123456789abcdef")
    if len(normalized) == 32:
        return normalized
    return ""


def _build_channel_identity(channel_name: object, channel_secret_hex: object = "") -> str:
    normalized_name = _channel_name(channel_name)
    if not normalized_name:
        return ""
    if normalized_name.strip().lower() == "#public":
        return f"public::{normalized_name.lower()}"
    normalized_secret = _channel_secret_hex(channel_secret_hex)
    if normalized_secret:
        return f"private::{hashlib.sha256(bytes.fromhex(normalized_secret)).hexdigest()}"
    return f"private-name::{normalized_name.lower()}"


def _channel_slot_limit(value: object) -> int:
    numeric = _int(value, DEFAULT_CHANNEL_SLOT_LIMIT)
    return max(2, numeric or DEFAULT_CHANNEL_SLOT_LIMIT)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
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


def _fetch_rows(
    conn: sqlite3.Connection,
    table_name: str,
    columns: Iterable[str],
    *,
    where_sql: str = "",
    params: Iterable[object] = (),
    order_sql: str = "",
) -> list[dict]:
    if not _table_exists(conn, table_name):
        return []
    sql = f"SELECT {', '.join(columns)} FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    if order_sql:
        sql += f" ORDER BY {order_sql}"
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [{column: row[column] for column in columns} for row in rows]


def _get_existing_row(
    conn: sqlite3.Connection,
    table_name: str,
    columns: Iterable[str],
    key_columns: Iterable[str],
    row: dict,
) -> dict | None:
    if not _table_exists(conn, table_name):
        return None
    keys = list(key_columns)
    params = tuple(row.get(column) for column in keys)
    sql = (
        f"SELECT {', '.join(columns)} FROM {table_name} "
        f"WHERE {' AND '.join(f'{column} = ?' for column in keys)} LIMIT 1"
    )
    conn.row_factory = sqlite3.Row
    found = conn.execute(sql, params).fetchone()
    if found is None:
        return None
    return {column: found[column] for column in columns}


def _insert_row(conn: sqlite3.Connection, table_name: str, columns: Iterable[str], row: dict) -> None:
    column_list = list(columns)
    conn.execute(
        f"INSERT INTO {table_name} ({', '.join(column_list)}) VALUES ({', '.join('?' for _ in column_list)})",
        tuple(row.get(column) for column in column_list),
    )


def _update_row(
    conn: sqlite3.Connection,
    table_name: str,
    columns: Iterable[str],
    key_columns: Iterable[str],
    row: dict,
) -> None:
    key_set = set(key_columns)
    writable_columns = [column for column in columns if column not in key_set]
    conn.execute(
        f"UPDATE {table_name} SET {', '.join(f'{column} = ?' for column in writable_columns)} "
        f"WHERE {' AND '.join(f'{column} = ?' for column in key_columns)}",
        tuple(row.get(column) for column in writable_columns) + tuple(row.get(column) for column in key_columns),
    )


def _rows_equal(existing: dict | None, incoming: dict | None, columns: Iterable[str]) -> bool:
    if existing is None or incoming is None:
        return False
    return all(existing.get(column) == incoming.get(column) for column in columns)


def _build_diff(existing: dict, incoming: dict, columns: Iterable[str], key_columns: Iterable[str]) -> list[dict]:
    ignored_keys = set(key_columns)
    diff: list[dict] = []
    for column in columns:
        if column in ignored_keys:
            continue
        left = existing.get(column)
        right = incoming.get(column)
        if left == right:
            continue
        diff.append(
            {
                "field": column,
                "existing": left,
                "incoming": right,
            }
        )
    return diff


def _conflict_key(row: dict, key_columns: Iterable[str]) -> str:
    return " | ".join(f"{column}={row.get(column)!r}" for column in key_columns)


def _append_conflict(
    preview: dict,
    *,
    category: str,
    item_type: str,
    key_columns: Iterable[str],
    columns: Iterable[str],
    existing: dict,
    incoming: dict,
    note: str = "",
) -> None:
    preview["summary"]["conflicts"] += 1
    if len(preview["conflicts"]) >= MAX_PREVIEW_CONFLICTS:
        preview["conflicts_truncated"] += 1
        return
    preview["conflicts"].append(
        {
            "category": category,
            "item_type": item_type,
            "key": _conflict_key(incoming, key_columns),
            "note": note,
            "diff": _build_diff(existing, incoming, columns, key_columns),
            "existing": existing,
            "incoming": incoming,
        }
    )


def _append_warning(preview: dict, *, category: str, code: str, message: str, details: dict | None = None) -> None:
    preview["summary"]["warnings"] += 1
    preview["warnings"].append(
        {
            "category": category,
            "code": code,
            "message": message,
            "details": dict(details or {}),
        }
    )


def _preview_generic_rows(
    preview: dict,
    *,
    conn: sqlite3.Connection,
    category: str,
    item_type: str,
    table_name: str,
    columns: Iterable[str],
    key_columns: Iterable[str],
    incoming_rows: Iterable[dict],
) -> None:
    column_list = list(columns)
    key_list = list(key_columns)
    for raw_row in list(incoming_rows or []):
        incoming = {column: raw_row.get(column) for column in column_list}
        preview["summary"]["incoming_rows"] += 1
        existing = _get_existing_row(conn, table_name, column_list, key_list, incoming)
        if existing is None:
            preview["summary"]["new_rows"] += 1
            continue
        if _rows_equal(existing, incoming, column_list):
            preview["summary"]["exact_duplicates"] += 1
            continue
        _append_conflict(
            preview,
            category=category,
            item_type=item_type,
            key_columns=key_list,
            columns=column_list,
            existing=existing,
            incoming=incoming,
        )


def _import_generic_rows(
    result: dict,
    *,
    conn: sqlite3.Connection,
    category: str,
    table_name: str,
    columns: Iterable[str],
    key_columns: Iterable[str],
    incoming_rows: Iterable[dict],
    overwrite_conflicts: bool,
) -> None:
    column_list = list(columns)
    key_list = list(key_columns)
    for raw_row in list(incoming_rows or []):
        incoming = {column: raw_row.get(column) for column in column_list}
        result["summary"]["incoming_rows"] += 1
        existing = _get_existing_row(conn, table_name, column_list, key_list, incoming)
        if existing is None:
            _insert_row(conn, table_name, column_list, incoming)
            result["summary"]["imported_rows"] += 1
            continue
        if _rows_equal(existing, incoming, column_list):
            result["summary"]["exact_duplicates"] += 1
            continue
        result["summary"]["conflicts"] += 1
        if overwrite_conflicts:
            _update_row(conn, table_name, column_list, key_list, incoming)
            result["summary"]["overwritten_rows"] += 1
        else:
            result["summary"]["skipped_conflicts"] += 1
            result["warnings"].append(
                {
                    "category": category,
                    "code": "conflict-skipped",
                    "message": f"Skipped conflicting row in {table_name}",
                    "details": {"key": _conflict_key(incoming, key_list)},
                }
            )


def _normalize_channel_slot_row(row: dict) -> dict:
    channel_name = _channel_name(row.get("channel_name"))
    secret_hex = _channel_secret_hex(row.get("channel_secret_hex"))
    return {
        "owner_id": _owner_id(row.get("owner_id")),
        "channel_idx": _int(row.get("channel_idx"), -1),
        "channel_name": channel_name,
        "channel_secret_hex": secret_hex,
        "channel_hash": _lower_text(row.get("channel_hash")),
        "channel_identity": _text(row.get("channel_identity")) or _build_channel_identity(channel_name, secret_hex),
        "is_public": _bool_int(row.get("is_public")),
        "last_seen_at": _int(row.get("last_seen_at")),
    }


def _normalize_channel_message_row(row: dict) -> dict:
    normalized = {column: row.get(column) for column in CHANNEL_MESSAGE_COLUMNS}
    normalized["owner_id"] = _owner_id(normalized.get("owner_id"))
    normalized["message_kind"] = "channel"
    normalized["channel_idx"] = _int(normalized.get("channel_idx"), -1)
    normalized["channel_identity"] = _text(normalized.get("channel_identity"))
    normalized["from_self"] = _bool_int(normalized.get("from_self"))
    normalized["acked_at"] = _int(normalized.get("acked_at"))
    normalized["sender_timestamp"] = _int(normalized.get("sender_timestamp"))
    normalized["received_at"] = _int(normalized.get("received_at"))
    normalized["is_read"] = _bool_int(normalized.get("is_read"))
    normalized["is_mention_read"] = _bool_int(normalized.get("is_mention_read"))
    return normalized


def _preview_channel_dialogs(preview: dict, conn: sqlite3.Connection, payload: dict) -> None:
    imported_slots = [_normalize_channel_slot_row(item) for item in list(payload.get("node_channel_slots") or [])]
    imported_messages = [_normalize_channel_message_row(item) for item in list(payload.get("messages") or [])]
    existing_slots = _fetch_rows(
        conn,
        "node_channel_slots",
        CHANNEL_SLOT_COLUMNS,
        order_sql="owner_id ASC, channel_idx ASC",
    )
    slot_limit = _channel_slot_limit(payload.get("max_channels"))
    working_by_owner: dict[str, list[dict]] = {}
    for row in existing_slots:
        owner = _owner_id(row.get("owner_id"))
        working_by_owner.setdefault(owner, []).append(_normalize_channel_slot_row(row))
    assigned_identity_idx: dict[tuple[str, str], int | None] = {}
    for slot in imported_slots:
        preview["summary"]["incoming_rows"] += 1
        owner = slot["owner_id"]
        identity = slot["channel_identity"]
        if not owner or not identity:
            _append_warning(
                preview,
                category=CATEGORY_CHANNEL_DIALOGS,
                code="invalid-channel-slot",
                message="Ignored imported channel slot without owner_id or channel_identity.",
                details={"slot": slot},
            )
            continue
        owner_slots = working_by_owner.setdefault(owner, [])
        by_identity = {item["channel_identity"]: item for item in owner_slots if item.get("channel_identity")}
        by_idx = {int(item["channel_idx"]): item for item in owner_slots if _int(item.get("channel_idx"), -1) >= 0}
        existing = by_identity.get(identity)
        if existing is not None:
            remapped = dict(slot)
            remapped["channel_idx"] = existing["channel_idx"]
            assigned_identity_idx[(owner, identity)] = existing["channel_idx"]
            if _rows_equal(existing, remapped, CHANNEL_SLOT_COLUMNS):
                preview["summary"]["exact_duplicates"] += 1
            else:
                _append_conflict(
                    preview,
                    category=CATEGORY_CHANNEL_DIALOGS,
                    item_type="node_channel_slot",
                    key_columns=("owner_id", "channel_identity"),
                    columns=CHANNEL_SLOT_COLUMNS,
                    existing=existing,
                    incoming=remapped,
                    note=(
                        f"Imported channel slot is mapped to local idx {existing['channel_idx']} "
                        f"because the channel identity already exists."
                    ),
                )
            continue
        desired_idx = _int(slot.get("channel_idx"), -1)
        assigned_idx = desired_idx if desired_idx >= 0 and desired_idx not in by_idx and desired_idx < slot_limit else None
        if assigned_idx is None:
            free_idx = None
            for idx in range(1, slot_limit):
                if idx not in by_idx:
                    free_idx = idx
                    break
            if free_idx is None:
                assigned_identity_idx[(owner, identity)] = None
                _append_warning(
                    preview,
                    category=CATEGORY_CHANNEL_DIALOGS,
                    code="no-free-channel-slots",
                    message=f"No free channel slots available for owner {owner[:12]} within limit {slot_limit}.",
                    details={"owner_id": owner, "channel_identity": identity, "slot_limit": slot_limit},
                )
                continue
            assigned_idx = free_idx
            if desired_idx != free_idx:
                _append_warning(
                    preview,
                    category=CATEGORY_CHANNEL_DIALOGS,
                    code="channel-slot-remap",
                    message=f"Imported channel slot {identity} will be mapped to free idx {free_idx} instead of occupied idx {desired_idx}.",
                    details={"owner_id": owner, "channel_identity": identity, "from_idx": desired_idx, "to_idx": free_idx},
                )
        assigned_identity_idx[(owner, identity)] = assigned_idx
        owner_slots.append({**slot, "channel_idx": assigned_idx})
        preview["summary"]["new_rows"] += 1
    for message in imported_messages:
        preview["summary"]["incoming_rows"] += 1
        owner = message["owner_id"]
        identity = _text(message.get("channel_identity"))
        if not owner:
            _append_warning(
                preview,
                category=CATEGORY_CHANNEL_DIALOGS,
                code="invalid-channel-message",
                message="Ignored imported channel message without owner_id.",
                details={"message": message},
            )
            continue
        assigned_idx = None
        if identity:
            assigned_idx = assigned_identity_idx.get((owner, identity))
            if assigned_idx is None:
                local_slot = _get_existing_row(
                    conn,
                    "node_channel_slots",
                    CHANNEL_SLOT_COLUMNS,
                    ("owner_id", "channel_identity"),
                    {"owner_id": owner, "channel_identity": identity},
                )
                assigned_idx = _int((local_slot or {}).get("channel_idx"), -1) if local_slot else None
        if assigned_idx is None and identity:
            _append_warning(
                preview,
                category=CATEGORY_CHANNEL_DIALOGS,
                code="channel-message-skipped-no-slot",
                message=f"Imported channel messages for {identity} cannot be merged because there is no free channel slot.",
                details={"owner_id": owner, "channel_identity": identity},
            )
            continue
        remapped = dict(message)
        if assigned_idx is not None and assigned_idx >= 0:
            remapped["channel_idx"] = assigned_idx
        existing = _get_existing_row(
            conn,
            "messages",
            CHANNEL_MESSAGE_COLUMNS,
            ("owner_id", "message_kind", "channel_identity", "channel_idx", "sender_timestamp", "text"),
            remapped,
        )
        if existing is None:
            preview["summary"]["new_rows"] += 1
            continue
        if _rows_equal(existing, remapped, CHANNEL_MESSAGE_COLUMNS):
            preview["summary"]["exact_duplicates"] += 1
            continue
        _append_conflict(
            preview,
            category=CATEGORY_CHANNEL_DIALOGS,
            item_type="channel_message",
            key_columns=("owner_id", "message_kind", "channel_identity", "channel_idx", "sender_timestamp", "text"),
            columns=CHANNEL_MESSAGE_COLUMNS,
            existing=existing,
            incoming=remapped,
        )


def _import_channel_dialogs(result: dict, conn: sqlite3.Connection, payload: dict, *, overwrite_conflicts: bool) -> list[str]:
    imported_slots = [_normalize_channel_slot_row(item) for item in list(payload.get("node_channel_slots") or [])]
    imported_messages = [_normalize_channel_message_row(item) for item in list(payload.get("messages") or [])]
    existing_slots = _fetch_rows(conn, "node_channel_slots", CHANNEL_SLOT_COLUMNS, order_sql="owner_id ASC, channel_idx ASC")
    slot_limit = _channel_slot_limit(payload.get("max_channels"))
    touched_owners: set[str] = set()
    working_by_owner: dict[str, list[dict]] = {}
    for row in existing_slots:
        owner = _owner_id(row.get("owner_id"))
        working_by_owner.setdefault(owner, []).append(_normalize_channel_slot_row(row))
    assigned_identity_idx: dict[tuple[str, str], int | None] = {}
    for slot in imported_slots:
        result["summary"]["incoming_rows"] += 1
        owner = slot["owner_id"]
        identity = slot["channel_identity"]
        if not owner or not identity:
            result["summary"]["warnings"] += 1
            result["warnings"].append(
                {
                    "category": CATEGORY_CHANNEL_DIALOGS,
                    "code": "invalid-channel-slot",
                    "message": "Ignored imported channel slot without owner_id or channel_identity.",
                    "details": {"slot": slot},
                }
            )
            continue
        owner_slots = working_by_owner.setdefault(owner, [])
        by_identity = {item["channel_identity"]: item for item in owner_slots if item.get("channel_identity")}
        by_idx = {int(item["channel_idx"]): item for item in owner_slots if _int(item.get("channel_idx"), -1) >= 0}
        existing = by_identity.get(identity)
        if existing is not None:
            remapped = dict(slot)
            remapped["channel_idx"] = existing["channel_idx"]
            assigned_identity_idx[(owner, identity)] = existing["channel_idx"]
            if _rows_equal(existing, remapped, CHANNEL_SLOT_COLUMNS):
                result["summary"]["exact_duplicates"] += 1
                continue
            result["summary"]["conflicts"] += 1
            if overwrite_conflicts:
                _update_row(
                    conn,
                    "node_channel_slots",
                    CHANNEL_SLOT_COLUMNS,
                    ("owner_id", "channel_idx"),
                    remapped,
                )
                result["summary"]["overwritten_rows"] += 1
                by_identity[identity] = remapped
                touched_owners.add(owner)
            else:
                result["summary"]["skipped_conflicts"] += 1
            continue
        desired_idx = _int(slot.get("channel_idx"), -1)
        assigned_idx = desired_idx if desired_idx >= 0 and desired_idx not in by_idx and desired_idx < slot_limit else None
        if assigned_idx is None:
            free_idx = None
            for idx in range(1, slot_limit):
                if idx not in by_idx:
                    free_idx = idx
                    break
            if free_idx is None:
                assigned_identity_idx[(owner, identity)] = None
                result["summary"]["warnings"] += 1
                result["warnings"].append(
                    {
                        "category": CATEGORY_CHANNEL_DIALOGS,
                        "code": "no-free-channel-slots",
                        "message": f"No free channel slots available for owner {owner[:12]} within limit {slot_limit}.",
                        "details": {"owner_id": owner, "channel_identity": identity, "slot_limit": slot_limit},
                    }
                )
                continue
            assigned_idx = free_idx
            if desired_idx != free_idx:
                result["summary"]["warnings"] += 1
                result["warnings"].append(
                    {
                        "category": CATEGORY_CHANNEL_DIALOGS,
                        "code": "channel-slot-remap",
                        "message": f"Imported channel slot {identity} was mapped to free idx {free_idx} instead of occupied idx {desired_idx}.",
                        "details": {"owner_id": owner, "channel_identity": identity, "from_idx": desired_idx, "to_idx": free_idx},
                    }
                )
        assigned_identity_idx[(owner, identity)] = assigned_idx
        row_to_insert = {**slot, "channel_idx": assigned_idx}
        _insert_row(conn, "node_channel_slots", CHANNEL_SLOT_COLUMNS, row_to_insert)
        owner_slots.append(row_to_insert)
        result["summary"]["imported_rows"] += 1
        touched_owners.add(owner)
    for message in imported_messages:
        result["summary"]["incoming_rows"] += 1
        owner = message["owner_id"]
        identity = _text(message.get("channel_identity"))
        if not owner:
            result["summary"]["warnings"] += 1
            result["warnings"].append(
                {
                    "category": CATEGORY_CHANNEL_DIALOGS,
                    "code": "invalid-channel-message",
                    "message": "Ignored imported channel message without owner_id.",
                    "details": {"message": message},
                }
            )
            continue
        assigned_idx = None
        if identity:
            assigned_idx = assigned_identity_idx.get((owner, identity))
            if assigned_idx is None:
                local_slot = _get_existing_row(
                    conn,
                    "node_channel_slots",
                    CHANNEL_SLOT_COLUMNS,
                    ("owner_id", "channel_identity"),
                    {"owner_id": owner, "channel_identity": identity},
                )
                assigned_idx = _int((local_slot or {}).get("channel_idx"), -1) if local_slot else None
        if assigned_idx is None and identity:
            result["summary"]["warnings"] += 1
            result["warnings"].append(
                {
                    "category": CATEGORY_CHANNEL_DIALOGS,
                    "code": "channel-message-skipped-no-slot",
                    "message": f"Skipped imported channel messages for {identity} because no free channel slot is available.",
                    "details": {"owner_id": owner, "channel_identity": identity},
                }
            )
            continue
        remapped = dict(message)
        if assigned_idx is not None and assigned_idx >= 0:
            remapped["channel_idx"] = assigned_idx
        existing = _get_existing_row(
            conn,
            "messages",
            CHANNEL_MESSAGE_COLUMNS,
            ("owner_id", "message_kind", "channel_identity", "channel_idx", "sender_timestamp", "text"),
            remapped,
        )
        if existing is None:
            _insert_row(conn, "messages", CHANNEL_MESSAGE_COLUMNS, remapped)
            result["summary"]["imported_rows"] += 1
            touched_owners.add(owner)
            continue
        if _rows_equal(existing, remapped, CHANNEL_MESSAGE_COLUMNS):
            result["summary"]["exact_duplicates"] += 1
            continue
        result["summary"]["conflicts"] += 1
        if overwrite_conflicts:
            _update_row(
                conn,
                "messages",
                CHANNEL_MESSAGE_COLUMNS,
                ("owner_id", "message_kind", "channel_identity", "channel_idx", "sender_timestamp", "text"),
                remapped,
            )
            result["summary"]["overwritten_rows"] += 1
            touched_owners.add(owner)
        else:
            result["summary"]["skipped_conflicts"] += 1
    return sorted(touched_owners)


def export_package(
    *,
    categories: Iterable[object] | None,
    messages_db_path: str,
    contacts_db_path: str,
    known_nodes_db_path: str,
) -> dict:
    selected = _normalize_categories(categories)
    package = {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "exported_at": _now(),
        "categories": {},
    }
    summary = {
        "selected_categories": list(selected),
        "contacts": 0,
        "channel_dialogs": 0,
        "direct_dialogs": 0,
        "known_nodes": 0,
        "signal_metrics": 0,
    }
    if CATEGORY_CONTACTS in selected:
        with sqlite3.connect(contacts_db_path) as conn:
            payload = {
                "contacts_cache": _fetch_rows(conn, "contacts_cache", CONTACTS_CACHE_COLUMNS, order_sql="owner_id ASC, public_key ASC"),
                "contact_groups": _fetch_rows(conn, "contact_groups", CONTACT_GROUP_COLUMNS, order_sql="name ASC"),
                "contact_group_tags": _fetch_rows(conn, "contact_group_tags", CONTACT_GROUP_TAG_COLUMNS, order_sql="group_name ASC, public_key ASC"),
            }
        package["categories"][CATEGORY_CONTACTS] = payload
        summary[CATEGORY_CONTACTS] = sum(len(rows) for rows in payload.values())
    if CATEGORY_CHANNEL_DIALOGS in selected:
        with sqlite3.connect(messages_db_path) as conn:
            payload = {
                "messages": _fetch_rows(conn, "messages", CHANNEL_MESSAGE_COLUMNS, where_sql="message_kind = ?", params=("channel",), order_sql="owner_id ASC, channel_idx ASC, sender_timestamp ASC, received_at ASC"),
                "node_channel_slots": _fetch_rows(conn, "node_channel_slots", CHANNEL_SLOT_COLUMNS, order_sql="owner_id ASC, channel_idx ASC"),
                "max_channels": DEFAULT_CHANNEL_SLOT_LIMIT,
            }
        package["categories"][CATEGORY_CHANNEL_DIALOGS] = payload
        summary[CATEGORY_CHANNEL_DIALOGS] = len(payload["messages"]) + len(payload["node_channel_slots"])
    if CATEGORY_DIRECT_DIALOGS in selected:
        with sqlite3.connect(messages_db_path) as conn:
            payload = {
                "contact_messages": _fetch_rows(conn, "contact_messages", DIRECT_MESSAGE_COLUMNS, order_sql="owner_id ASC, pubkey_prefix ASC, sender_timestamp ASC, received_at ASC"),
            }
        package["categories"][CATEGORY_DIRECT_DIALOGS] = payload
        summary[CATEGORY_DIRECT_DIALOGS] = len(payload["contact_messages"])
    if CATEGORY_SIGNAL_METRICS in selected:
        with sqlite3.connect(messages_db_path) as conn:
            payload = {
                "signal_metrics": _fetch_rows(conn, "signal_metrics", SIGNAL_METRIC_COLUMNS, order_sql="owner_id ASC, recorded_at ASC"),
            }
        package["categories"][CATEGORY_SIGNAL_METRICS] = payload
        summary[CATEGORY_SIGNAL_METRICS] = len(payload["signal_metrics"])
    if CATEGORY_KNOWN_NODES in selected:
        with sqlite3.connect(known_nodes_db_path) as conn:
            payload = {
                "known_nodes": _fetch_rows(conn, "known_nodes", KNOWN_NODE_COLUMNS, order_sql="last_successful_at DESC, public_key ASC"),
                "known_node_transports": _fetch_rows(conn, "known_node_transports", KNOWN_NODE_TRANSPORT_COLUMNS, order_sql="updated_at DESC, key ASC"),
            }
        package["categories"][CATEGORY_KNOWN_NODES] = payload
        summary[CATEGORY_KNOWN_NODES] = len(payload["known_nodes"]) + len(payload["known_node_transports"])
    return {
        "package": package,
        "summary": summary,
    }


def preview_package(
    *,
    package: dict,
    categories: Iterable[object] | None,
    messages_db_path: str,
    contacts_db_path: str,
    known_nodes_db_path: str,
) -> dict:
    selected = _normalize_categories(categories)
    payload_categories = package.get("categories") if isinstance(package, dict) else {}
    payload_categories = payload_categories if isinstance(payload_categories, dict) else {}
    preview = {
        "selected_categories": list(selected),
        "summary": {
            "incoming_rows": 0,
            "new_rows": 0,
            "exact_duplicates": 0,
            "conflicts": 0,
            "warnings": 0,
        },
        "conflicts": [],
        "conflicts_truncated": 0,
        "warnings": [],
    }
    if CATEGORY_CONTACTS in selected:
        payload = payload_categories.get(CATEGORY_CONTACTS) if isinstance(payload_categories.get(CATEGORY_CONTACTS), dict) else {}
        with sqlite3.connect(contacts_db_path) as conn:
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_CONTACTS, item_type="contacts_cache", table_name="contacts_cache", columns=CONTACTS_CACHE_COLUMNS, key_columns=("owner_id", "public_key"), incoming_rows=payload.get("contacts_cache") or [])
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_CONTACTS, item_type="contact_groups", table_name="contact_groups", columns=CONTACT_GROUP_COLUMNS, key_columns=("name",), incoming_rows=payload.get("contact_groups") or [])
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_CONTACTS, item_type="contact_group_tags", table_name="contact_group_tags", columns=CONTACT_GROUP_TAG_COLUMNS, key_columns=("group_name", "public_key"), incoming_rows=payload.get("contact_group_tags") or [])
    if CATEGORY_CHANNEL_DIALOGS in selected:
        payload = payload_categories.get(CATEGORY_CHANNEL_DIALOGS) if isinstance(payload_categories.get(CATEGORY_CHANNEL_DIALOGS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            _preview_channel_dialogs(preview, conn, payload)
    if CATEGORY_DIRECT_DIALOGS in selected:
        payload = payload_categories.get(CATEGORY_DIRECT_DIALOGS) if isinstance(payload_categories.get(CATEGORY_DIRECT_DIALOGS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_DIRECT_DIALOGS, item_type="contact_messages", table_name="contact_messages", columns=DIRECT_MESSAGE_COLUMNS, key_columns=("owner_id", "pubkey_prefix", "sender_timestamp", "text"), incoming_rows=payload.get("contact_messages") or [])
    if CATEGORY_SIGNAL_METRICS in selected:
        payload = payload_categories.get(CATEGORY_SIGNAL_METRICS) if isinstance(payload_categories.get(CATEGORY_SIGNAL_METRICS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_SIGNAL_METRICS, item_type="signal_metrics", table_name="signal_metrics", columns=SIGNAL_METRIC_COLUMNS, key_columns=("owner_id", "recorded_at"), incoming_rows=payload.get("signal_metrics") or [])
    if CATEGORY_KNOWN_NODES in selected:
        payload = payload_categories.get(CATEGORY_KNOWN_NODES) if isinstance(payload_categories.get(CATEGORY_KNOWN_NODES), dict) else {}
        with sqlite3.connect(known_nodes_db_path) as conn:
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_KNOWN_NODES, item_type="known_nodes", table_name="known_nodes", columns=KNOWN_NODE_COLUMNS, key_columns=("public_key",), incoming_rows=payload.get("known_nodes") or [])
            _preview_generic_rows(preview, conn=conn, category=CATEGORY_KNOWN_NODES, item_type="known_node_transports", table_name="known_node_transports", columns=KNOWN_NODE_TRANSPORT_COLUMNS, key_columns=("key",), incoming_rows=payload.get("known_node_transports") or [])
    return preview


def import_package(
    *,
    package: dict,
    categories: Iterable[object] | None,
    messages_db_path: str,
    contacts_db_path: str,
    known_nodes_db_path: str,
    overwrite_conflicts: bool,
) -> dict:
    selected = _normalize_categories(categories)
    payload_categories = package.get("categories") if isinstance(package, dict) else {}
    payload_categories = payload_categories if isinstance(payload_categories, dict) else {}
    result = {
        "selected_categories": list(selected),
        "summary": {
            "incoming_rows": 0,
            "imported_rows": 0,
            "overwritten_rows": 0,
            "exact_duplicates": 0,
            "conflicts": 0,
            "skipped_conflicts": 0,
            "warnings": 0,
        },
        "warnings": [],
        "touched_channel_owners": [],
    }
    if CATEGORY_CONTACTS in selected:
        payload = payload_categories.get(CATEGORY_CONTACTS) if isinstance(payload_categories.get(CATEGORY_CONTACTS), dict) else {}
        with sqlite3.connect(contacts_db_path) as conn:
            _import_generic_rows(result, conn=conn, category=CATEGORY_CONTACTS, table_name="contacts_cache", columns=CONTACTS_CACHE_COLUMNS, key_columns=("owner_id", "public_key"), incoming_rows=payload.get("contacts_cache") or [], overwrite_conflicts=overwrite_conflicts)
            _import_generic_rows(result, conn=conn, category=CATEGORY_CONTACTS, table_name="contact_groups", columns=CONTACT_GROUP_COLUMNS, key_columns=("name",), incoming_rows=payload.get("contact_groups") or [], overwrite_conflicts=overwrite_conflicts)
            _import_generic_rows(result, conn=conn, category=CATEGORY_CONTACTS, table_name="contact_group_tags", columns=CONTACT_GROUP_TAG_COLUMNS, key_columns=("group_name", "public_key"), incoming_rows=payload.get("contact_group_tags") or [], overwrite_conflicts=overwrite_conflicts)
            conn.commit()
    if CATEGORY_CHANNEL_DIALOGS in selected:
        payload = payload_categories.get(CATEGORY_CHANNEL_DIALOGS) if isinstance(payload_categories.get(CATEGORY_CHANNEL_DIALOGS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            touched = _import_channel_dialogs(result, conn, payload, overwrite_conflicts=overwrite_conflicts)
            conn.commit()
            result["touched_channel_owners"].extend(touched)
    if CATEGORY_DIRECT_DIALOGS in selected:
        payload = payload_categories.get(CATEGORY_DIRECT_DIALOGS) if isinstance(payload_categories.get(CATEGORY_DIRECT_DIALOGS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            _import_generic_rows(result, conn=conn, category=CATEGORY_DIRECT_DIALOGS, table_name="contact_messages", columns=DIRECT_MESSAGE_COLUMNS, key_columns=("owner_id", "pubkey_prefix", "sender_timestamp", "text"), incoming_rows=payload.get("contact_messages") or [], overwrite_conflicts=overwrite_conflicts)
            conn.commit()
    if CATEGORY_SIGNAL_METRICS in selected:
        payload = payload_categories.get(CATEGORY_SIGNAL_METRICS) if isinstance(payload_categories.get(CATEGORY_SIGNAL_METRICS), dict) else {}
        with sqlite3.connect(messages_db_path) as conn:
            _import_generic_rows(result, conn=conn, category=CATEGORY_SIGNAL_METRICS, table_name="signal_metrics", columns=SIGNAL_METRIC_COLUMNS, key_columns=("owner_id", "recorded_at"), incoming_rows=payload.get("signal_metrics") or [], overwrite_conflicts=overwrite_conflicts)
            conn.commit()
    if CATEGORY_KNOWN_NODES in selected:
        payload = payload_categories.get(CATEGORY_KNOWN_NODES) if isinstance(payload_categories.get(CATEGORY_KNOWN_NODES), dict) else {}
        with sqlite3.connect(known_nodes_db_path) as conn:
            _import_generic_rows(result, conn=conn, category=CATEGORY_KNOWN_NODES, table_name="known_nodes", columns=KNOWN_NODE_COLUMNS, key_columns=("public_key",), incoming_rows=payload.get("known_nodes") or [], overwrite_conflicts=overwrite_conflicts)
            _import_generic_rows(result, conn=conn, category=CATEGORY_KNOWN_NODES, table_name="known_node_transports", columns=KNOWN_NODE_TRANSPORT_COLUMNS, key_columns=("key",), incoming_rows=payload.get("known_node_transports") or [], overwrite_conflicts=overwrite_conflicts)
            conn.commit()
    result["touched_channel_owners"] = sorted({owner for owner in result["touched_channel_owners"] if owner})
    return result
