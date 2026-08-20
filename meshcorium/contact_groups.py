from __future__ import annotations

import sqlite3
import threading

SCOPED_GROUP_PREFIX = "@@scope="


def _normalize_scope_key(value: object) -> str:
    return str(value or "").strip().lower()


def _encode_group_storage_name(group_name: str, scope_key: str) -> str:
    normalized_group_name = str(group_name or "").strip()
    normalized_scope_key = _normalize_scope_key(scope_key)
    if not normalized_scope_key:
        return normalized_group_name
    return f"{SCOPED_GROUP_PREFIX}{normalized_scope_key}@@{normalized_group_name}"


def _decode_group_storage_name(stored_name: object) -> tuple[str, str]:
    value = str(stored_name or "").strip()
    if not value.startswith(SCOPED_GROUP_PREFIX):
        return "", value
    marker_end = value.find("@@", len(SCOPED_GROUP_PREFIX))
    if marker_end < 0:
        return "", value
    scope_key = _normalize_scope_key(value[len(SCOPED_GROUP_PREFIX):marker_end])
    visible_name = value[marker_end + 2:].strip()
    if not visible_name:
        return "", value
    return scope_key, visible_name


def _resolve_group_storage_name(
    conn: sqlite3.Connection,
    group_name: str,
    *,
    scope_key: str,
) -> str | None:
    normalized_group_name = str(group_name or "").strip()
    if not normalized_group_name:
        return None
    scoped_name = _encode_group_storage_name(normalized_group_name, scope_key)
    if scoped_name == normalized_group_name:
        row = conn.execute("SELECT name FROM contact_groups WHERE name = ? LIMIT 1", (normalized_group_name,)).fetchone()
        return normalized_group_name if row is not None else scoped_name
    found = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM contact_groups WHERE name IN (?, ?)",
            (scoped_name, normalized_group_name),
        ).fetchall()
    }
    if scoped_name in found:
        return scoped_name
    if normalized_group_name in found:
        return normalized_group_name
    return scoped_name


def list_contact_groups(
    db_lock: threading.Lock,
    db_path: str,
    *,
    reserved_group_name: str,
    scope_key: str = "",
) -> dict[str, list[str]]:
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        group_rows = conn.execute(
            """
            SELECT name
            FROM contact_groups
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
        rows = conn.execute(
            """
            SELECT group_name, public_key
            FROM contact_group_tags
            ORDER BY group_name COLLATE NOCASE ASC, public_key COLLATE NOCASE ASC
            """
        ).fetchall()
    reserved = str(reserved_group_name or "").strip().lower()
    current_scope_key = _normalize_scope_key(scope_key)
    visible_to_raw: dict[str, str] = {}
    raw_to_visible: dict[str, str] = {}
    candidates: list[tuple[int, str, str]] = []
    for row in group_rows:
        raw_name = str(row["name"] or "").strip()
        row_scope_key, visible_name = _decode_group_storage_name(raw_name)
        if not visible_name or visible_name.lower() == reserved:
            continue
        if row_scope_key not in {"", current_scope_key}:
            continue
        precedence = 0 if row_scope_key == current_scope_key and current_scope_key else 1
        candidates.append((precedence, visible_name.lower(), raw_name))
        raw_to_visible[raw_name] = visible_name
    for _precedence, _sort_name, raw_name in sorted(candidates):
        visible_name = raw_to_visible.get(raw_name, "")
        if visible_name and visible_name not in visible_to_raw:
            visible_to_raw[visible_name] = raw_name
    groups: dict[str, list[str]] = {visible_name: [] for visible_name in visible_to_raw}
    for row in rows:
        raw_name = str(row["group_name"] or "").strip()
        public_key = str(row["public_key"] or "").strip().lower()
        visible_name = raw_to_visible.get(raw_name, "")
        if not visible_name or visible_to_raw.get(visible_name) != raw_name or not public_key:
            continue
        groups.setdefault(visible_name, []).append(public_key)
    return groups


def save_contact_group(
    db_lock: threading.Lock,
    db_path: str,
    *,
    group_name: str,
    members: list[str],
    reserved_group_name: str,
    scope_key: str = "",
) -> dict[str, list[str]]:
    normalized_group_name = str(group_name or "").strip()
    if not normalized_group_name:
        raise ValueError("group_name is required")
    if normalized_group_name.lower() == str(reserved_group_name or "").strip().lower():
        raise ValueError("group name is reserved")
    normalized_members = sorted(
        {
            str(public_key or "").strip().lower()
            for public_key in (members or [])
            if len(str(public_key or "").strip()) == 64
        }
    )
    with db_lock, sqlite3.connect(db_path) as conn:
        stored_group_name = _resolve_group_storage_name(
            conn,
            normalized_group_name,
            scope_key=scope_key,
        )
        if not stored_group_name:
            raise ValueError("group_name is required")
        conn.execute(
            """
            INSERT INTO contact_groups(name)
            VALUES(?)
            ON CONFLICT(name) DO NOTHING
            """,
            (stored_group_name,),
        )
        conn.execute("DELETE FROM contact_group_tags WHERE group_name = ?", (stored_group_name,))
        if normalized_members:
            conn.executemany(
                """
                INSERT INTO contact_group_tags(group_name, public_key)
                VALUES(?, ?)
                """,
                [(stored_group_name, public_key) for public_key in normalized_members],
            )
        conn.commit()
    return list_contact_groups(db_lock, db_path, reserved_group_name=reserved_group_name, scope_key=scope_key)


def delete_contact_group(
    db_lock: threading.Lock,
    db_path: str,
    *,
    group_name: str,
    reserved_group_name: str,
    scope_key: str = "",
) -> dict[str, list[str]]:
    normalized_group_name = str(group_name or "").strip()
    if not normalized_group_name:
        raise ValueError("group_name is required")
    if normalized_group_name.lower() == str(reserved_group_name or "").strip().lower():
        raise ValueError("group name is reserved")
    with db_lock, sqlite3.connect(db_path) as conn:
        stored_group_name = _resolve_group_storage_name(
            conn,
            normalized_group_name,
            scope_key=scope_key,
        )
        if not stored_group_name:
            raise ValueError("group not found")
        conn.execute("DELETE FROM contact_group_tags WHERE group_name = ?", (stored_group_name,))
        conn.execute("DELETE FROM contact_groups WHERE name = ?", (stored_group_name,))
        conn.commit()
    return list_contact_groups(db_lock, db_path, reserved_group_name=reserved_group_name, scope_key=scope_key)


def rename_contact_group(
    db_lock: threading.Lock,
    db_path: str,
    *,
    old_name: str,
    new_name: str,
    reserved_group_name: str,
    scope_key: str = "",
) -> dict[str, list[str]]:
    normalized_old_name = str(old_name or "").strip()
    normalized_new_name = str(new_name or "").strip()
    if not normalized_old_name:
        raise ValueError("old_name is required")
    if not normalized_new_name:
        raise ValueError("new_name is required")
    reserved = str(reserved_group_name or "").strip().lower()
    if normalized_old_name.lower() == reserved or normalized_new_name.lower() == reserved:
        raise ValueError("group name is reserved")
    with db_lock, sqlite3.connect(db_path) as conn:
        stored_old_name = _resolve_group_storage_name(
            conn,
            normalized_old_name,
            scope_key=scope_key,
        )
        if not stored_old_name:
            raise ValueError("group not found")
        scoped_new_name = _encode_group_storage_name(normalized_new_name, scope_key)
        collision = conn.execute(
            "SELECT 1 FROM contact_groups WHERE name = ? LIMIT 1",
            (scoped_new_name,),
        ).fetchone()
        if collision is not None and scoped_new_name != stored_old_name:
            raise ValueError("group already exists")
        conn.execute(
            """
            UPDATE contact_groups
            SET name = ?
            WHERE name = ?
            """,
            (scoped_new_name, stored_old_name),
        )
        conn.execute(
            """
            UPDATE contact_group_tags
            SET group_name = ?
            WHERE group_name = ?
            """,
            (scoped_new_name, stored_old_name),
        )
        conn.commit()
    return list_contact_groups(db_lock, db_path, reserved_group_name=reserved_group_name, scope_key=scope_key)


def delete_contact_local_overlay(
    db_lock: threading.Lock,
    db_path: str,
    *,
    public_key: str,
) -> None:
    target = str(public_key or "").strip().lower()
    if len(target) != 64:
        return
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM contact_group_tags WHERE public_key = ?", (target,))
        conn.commit()
