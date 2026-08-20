"""SQLite persistence for the hybrid contacts model.

``contacts_cache`` is the persistent local mirror/store for contacts known to
the client. It keeps companion-derived transport fields plus backend-owned
residency/activity metadata. The live companion contact table remains a
transient runtime set and should not be treated as the durable full universe.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager

from meshcorium_client import Contact, MeshCoreError

CONTACT_STORE_SCHEMA_VERSION = 21
ADVERT_TYPE_REPEATER = 2
CONTACT_SCOPE = threading.local()


def _norm_key(pk: object) -> str:
    """Normalize a public key to lowercase hex, stripping whitespace."""
    return str(pk or "").strip().lower()


def _normalize_owner_id(owner_id: object) -> str:
    normalized = str(owner_id or "").strip().lower()
    return normalized if len(normalized) == 64 else ""


@contextmanager
def contact_scope(*, owner_id: str | None, access_all: bool):
    previous_owner_id = getattr(CONTACT_SCOPE, "owner_id", "")
    previous_access_all = getattr(CONTACT_SCOPE, "access_all", True)
    CONTACT_SCOPE.owner_id = _normalize_owner_id(owner_id)
    CONTACT_SCOPE.access_all = bool(access_all)
    try:
        yield
    finally:
        CONTACT_SCOPE.owner_id = previous_owner_id
        CONTACT_SCOPE.access_all = previous_access_all


def get_scoped_owner_id() -> str:
    return _normalize_owner_id(getattr(CONTACT_SCOPE, "owner_id", ""))


def get_scoped_access_all() -> bool:
    return bool(getattr(CONTACT_SCOPE, "access_all", True))


def _ensure_contact_store_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_store_meta (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            schema_version INTEGER NOT NULL,
            last_sync_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO contact_store_meta(singleton_id, schema_version, last_sync_at)
        VALUES (1, 0, 0)
        ON CONFLICT(singleton_id) DO NOTHING
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(contact_store_meta)")}
    if "last_sync_at" not in columns:
        conn.execute("ALTER TABLE contact_store_meta ADD COLUMN last_sync_at INTEGER NOT NULL DEFAULT 0")


def _get_contact_store_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_contact_store_meta(conn)
    row = conn.execute(
        "SELECT schema_version FROM contact_store_meta WHERE singleton_id = 1"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _set_contact_store_schema_version(conn: sqlite3.Connection, version: int) -> None:
    _ensure_contact_store_meta(conn)
    conn.execute(
        "UPDATE contact_store_meta SET schema_version = ? WHERE singleton_id = 1",
        (int(version),),
    )


def _set_contact_store_last_sync_at(conn: sqlite3.Connection, epoch: int) -> None:
    _ensure_contact_store_meta(conn)
    conn.execute(
        "UPDATE contact_store_meta SET last_sync_at = ? WHERE singleton_id = 1",
        (int(epoch),),
    )


def _get_contact_store_last_sync_at(conn: sqlite3.Connection) -> int:
    _ensure_contact_store_meta(conn)
    row = conn.execute(
        "SELECT last_sync_at FROM contact_store_meta WHERE singleton_id = 1"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _contacts_cache_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'contacts_cache'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _create_contacts_cache_current_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts_cache (
            owner_id TEXT NOT NULL DEFAULT '',
            public_key TEXT NOT NULL,
            adv_type INTEGER NOT NULL,
            flags INTEGER NOT NULL,
            path_len_byte INTEGER NOT NULL,
            out_path_len INTEGER NOT NULL,
            out_path_hash_len INTEGER NOT NULL,
            out_path TEXT NOT NULL,
            adv_name TEXT NOT NULL,
            last_advert INTEGER NOT NULL,
            adv_lat_raw INTEGER NOT NULL,
            adv_lon_raw INTEGER NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            has_location INTEGER NOT NULL DEFAULT 0,
            lastmod INTEGER NOT NULL,
            raw_payload_hex TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL,
            last_interaction_at INTEGER NOT NULL DEFAULT 0,
            last_public_traffic_at INTEGER NOT NULL DEFAULT 0,
            last_public_advert_at INTEGER NOT NULL DEFAULT 0,
            last_public_advert_mode TEXT NOT NULL DEFAULT '',
            last_materialized_at INTEGER NOT NULL DEFAULT 0,
            last_removed_from_node_at INTEGER NOT NULL DEFAULT 0,
            repeater_auth_password TEXT NOT NULL DEFAULT '',
            repeater_auth_saved_at INTEGER NOT NULL DEFAULT 0,
            is_local_self INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (owner_id, public_key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_lastmod
        ON contacts_cache(lastmod)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_public_key
        ON contacts_cache(public_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_owner_id
        ON contacts_cache(owner_id)
        """
    )


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, spec: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {spec}")


def _apply_contact_store_migration(conn: sqlite3.Connection, version: int) -> None:
    if version == 1:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts_cache (
                public_key TEXT PRIMARY KEY,
                adv_type INTEGER NOT NULL DEFAULT 0,
                flags INTEGER NOT NULL DEFAULT 0,
                out_path_len INTEGER NOT NULL DEFAULT 0,
                out_path_hash_len INTEGER NOT NULL DEFAULT 0,
                out_path TEXT NOT NULL DEFAULT '',
                adv_name TEXT NOT NULL DEFAULT '',
                last_advert INTEGER NOT NULL DEFAULT 0,
                lastmod INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contacts_cache_lastmod
            ON contacts_cache(lastmod)
            """
        )
        return
    migration_columns = {
        2: ("adv_lat_raw", "INTEGER NOT NULL DEFAULT 0"),
        3: ("adv_lon_raw", "INTEGER NOT NULL DEFAULT 0"),
        4: ("lat", "REAL NOT NULL DEFAULT 0"),
        5: ("lon", "REAL NOT NULL DEFAULT 0"),
        6: ("has_location", "INTEGER NOT NULL DEFAULT 0"),
        7: ("path_len_byte", "INTEGER NOT NULL DEFAULT 0"),
        8: ("raw_payload_hex", "TEXT NOT NULL DEFAULT ''"),
        9: ("updated_at", "INTEGER NOT NULL DEFAULT 0"),
        10: ("last_interaction_at", "INTEGER NOT NULL DEFAULT 0"),
        11: ("last_materialized_at", "INTEGER NOT NULL DEFAULT 0"),
        12: ("last_removed_from_node_at", "INTEGER NOT NULL DEFAULT 0"),
        14: ("is_local_self", "INTEGER NOT NULL DEFAULT 0"),
        17: ("repeater_auth_password", "TEXT NOT NULL DEFAULT ''"),
        18: ("repeater_auth_saved_at", "INTEGER NOT NULL DEFAULT 0"),
        19: ("last_public_traffic_at", "INTEGER NOT NULL DEFAULT 0"),
        20: ("last_public_advert_at", "INTEGER NOT NULL DEFAULT 0"),
        21: ("last_public_advert_mode", "TEXT NOT NULL DEFAULT ''"),
    }
    if int(version) == 13:
        _ensure_contact_store_meta(conn)
        return
    if int(version) == 15:
        _ensure_contact_store_meta(conn)
        return
    if int(version) == 16:
        _rebuild_contacts_cache_with_owner_scope(conn)
        _ensure_contact_store_meta(conn)
        return
    column = migration_columns.get(int(version))
    if column is None:
        raise ValueError(f"unsupported contact store migration version: {version}")
    _ensure_column(conn, "contacts_cache", column[0], column[1])


def init_contact_store_schema(conn: sqlite3.Connection) -> None:
    current_version = _get_contact_store_schema_version(conn)
    # GUARD: if DB has contacts_cache with data but schema_version is 0,
    # the meta table was corrupted (likely WAL not checkpointed after crash).
    # Do NOT replay migrations — just set the correct version and continue.
    if not _contacts_cache_exists(conn):
        pass  # table doesn't exist — proceed with normal creation below
    elif current_version == 0:
        # DB has data but schema_version claims 0 — WAL corruption after crash.
        # Check if contacts_cache actually has rows to confirm it's a real DB.
        row_count = conn.execute(
            "SELECT COUNT(*) FROM contacts_cache"
        ).fetchone()[0]
        if row_count > 0:
            logging.warning(
                "contacts_cache has %d rows but schema_version=0 "
                "(likely WAL not checkpointed after crash). "
                "Setting schema_version=%d and skipping migrations.",
                row_count, CONTACT_STORE_SCHEMA_VERSION
            )
            _set_contact_store_schema_version(
                conn, CONTACT_STORE_SCHEMA_VERSION
            )
            return
    if not _contacts_cache_exists(conn):
        _create_contacts_cache_current_schema(conn)
        _set_contact_store_schema_version(conn, CONTACT_STORE_SCHEMA_VERSION)
        return
    if current_version >= CONTACT_STORE_SCHEMA_VERSION:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contacts_cache_lastmod
            ON contacts_cache(lastmod)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contacts_cache_public_key
            ON contacts_cache(public_key)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contacts_cache_owner_id
            ON contacts_cache(owner_id)
            """
        )
        return
    next_version = max(1, current_version + 1)
    for version in range(next_version, CONTACT_STORE_SCHEMA_VERSION + 1):
        _apply_contact_store_migration(conn, version)
        _set_contact_store_schema_version(conn, version)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_lastmod
        ON contacts_cache(lastmod)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_public_key
        ON contacts_cache(public_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contacts_cache_owner_id
        ON contacts_cache(owner_id)
        """
    )


def _rebuild_contacts_cache_with_owner_scope(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS contacts_cache_v16")
    conn.execute(
        """
        CREATE TABLE contacts_cache_v16 (
            owner_id TEXT NOT NULL DEFAULT '',
            public_key TEXT NOT NULL,
            adv_type INTEGER NOT NULL,
            flags INTEGER NOT NULL,
            path_len_byte INTEGER NOT NULL,
            out_path_len INTEGER NOT NULL,
            out_path_hash_len INTEGER NOT NULL,
            out_path TEXT NOT NULL,
            adv_name TEXT NOT NULL,
            last_advert INTEGER NOT NULL,
            adv_lat_raw INTEGER NOT NULL,
            adv_lon_raw INTEGER NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            has_location INTEGER NOT NULL DEFAULT 0,
            lastmod INTEGER NOT NULL,
            raw_payload_hex TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL,
            last_interaction_at INTEGER NOT NULL DEFAULT 0,
            last_materialized_at INTEGER NOT NULL DEFAULT 0,
            last_removed_from_node_at INTEGER NOT NULL DEFAULT 0,
            is_local_self INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (owner_id, public_key)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO contacts_cache_v16 (
            owner_id,
            public_key,
            adv_type,
            flags,
            path_len_byte,
            out_path_len,
            out_path_hash_len,
            out_path,
            adv_name,
            last_advert,
            adv_lat_raw,
            adv_lon_raw,
            lat,
            lon,
            has_location,
            lastmod,
            raw_payload_hex,
            updated_at,
            last_interaction_at,
            last_materialized_at,
            last_removed_from_node_at,
            is_local_self
        )
        SELECT
            '',
            public_key,
            adv_type,
            flags,
            path_len_byte,
            out_path_len,
            out_path_hash_len,
            out_path,
            adv_name,
            last_advert,
            adv_lat_raw,
            adv_lon_raw,
            lat,
            lon,
            has_location,
            lastmod,
            raw_payload_hex,
            updated_at,
            last_interaction_at,
            last_materialized_at,
            last_removed_from_node_at,
            is_local_self
        FROM contacts_cache
        """
    )
    conn.execute("DROP TABLE contacts_cache")
    conn.execute("ALTER TABLE contacts_cache_v16 RENAME TO contacts_cache")


def contact_cache_row_to_dict(row: sqlite3.Row) -> dict:
    contact = {
        "owner_id": _normalize_owner_id(row["owner_id"]),
        "public_key": _norm_key(row["public_key"]),
        "adv_type": int(row["adv_type"] or 0),
        "flags": int(row["flags"] or 0),
        "path_len_byte": int(row["path_len_byte"] or 0),
        "out_path_len": int(row["out_path_len"] or 0),
        "out_path_hash_len": int(row["out_path_hash_len"] or 0),
        "out_path": str(row["out_path"] or ""),
        "adv_name": str(row["adv_name"] or ""),
        "last_advert": int(row["last_advert"] or 0),
        "adv_lat_raw": int(row["adv_lat_raw"] or 0),
        "adv_lon_raw": int(row["adv_lon_raw"] or 0),
        "lat": float(row["lat"] or 0.0),
        "lon": float(row["lon"] or 0.0),
        "has_location": bool(row["has_location"]),
        "lastmod": int(row["lastmod"] or 0),
        "raw_payload_hex": str(row["raw_payload_hex"] or ""),
        "updated_at": int(row["updated_at"] or 0),
        "last_interaction_at": int(row["last_interaction_at"] or 0),
        "last_public_traffic_at": int(row["last_public_traffic_at"] or 0),
        "last_public_advert_at": int(row["last_public_advert_at"] or 0),
        "last_public_advert_mode": str(row["last_public_advert_mode"] or ""),
        "last_materialized_at": int(row["last_materialized_at"] or 0),
        "last_removed_from_node_at": int(row["last_removed_from_node_at"] or 0),
        "repeater_auth_saved": bool(str(row["repeater_auth_password"] or "").strip()),
        "repeater_auth_saved_at": int(row["repeater_auth_saved_at"] or 0),
        "is_local_self": bool(row["is_local_self"]),
    }
    contact["companion"] = {
        "public_key": contact["public_key"],
        "adv_type": contact["adv_type"],
        "flags": contact["flags"],
        "path_len_byte": contact["path_len_byte"],
        "out_path_len": contact["out_path_len"],
        "out_path_hash_len": contact["out_path_hash_len"],
        "out_path": contact["out_path"],
        "adv_name": contact["adv_name"],
        "last_advert": contact["last_advert"],
        "adv_lat_raw": contact["adv_lat_raw"],
        "adv_lon_raw": contact["adv_lon_raw"],
        "lat": contact["lat"],
        "lon": contact["lon"],
        "has_location": contact["has_location"],
        "lastmod": contact["lastmod"],
        "raw_payload_hex": contact["raw_payload_hex"],
    }
    contact["backend"] = {
        "owner_id": contact["owner_id"],
        "cache_updated_at": contact["updated_at"],
        "last_interaction_at": contact["last_interaction_at"],
        "last_public_traffic_at": contact["last_public_traffic_at"],
        "last_public_advert_at": contact["last_public_advert_at"],
        "last_public_advert_mode": contact["last_public_advert_mode"],
        "last_materialized_at": contact["last_materialized_at"],
        "last_removed_from_node_at": contact["last_removed_from_node_at"],
        "repeater_auth_saved": contact["repeater_auth_saved"],
        "repeater_auth_saved_at": contact["repeater_auth_saved_at"],
        "is_local_self": contact["is_local_self"],
    }
    return contact


def list_cached_contacts_raw(db_lock: threading.Lock, db_path: str, limit: int | None = None) -> list[dict]:
    scoped_owner_id = get_scoped_owner_id()
    access_all = get_scoped_access_all()
    if not access_all and not scoped_owner_id:
        return []
    sql = """
        SELECT
            owner_id,
            public_key,
            adv_type,
            flags,
            path_len_byte,
            out_path_len,
            out_path_hash_len,
            out_path,
            adv_name,
            last_advert,
            adv_lat_raw,
            adv_lon_raw,
            lat,
            lon,
            has_location,
            lastmod,
            raw_payload_hex,
            updated_at,
            last_interaction_at,
            last_public_traffic_at,
            last_public_advert_at,
            last_public_advert_mode,
            last_materialized_at,
            last_removed_from_node_at,
            repeater_auth_password,
            repeater_auth_saved_at,
            is_local_self
        FROM contacts_cache
    """
    params: list[object] = []
    if not access_all and scoped_owner_id:
        sql += "\nWHERE owner_id = ?"
        params.append(scoped_owner_id)
    if access_all and scoped_owner_id:
        sql += "\nORDER BY CASE WHEN owner_id = ? THEN 0 ELSE 1 END, lastmod DESC, last_advert DESC, updated_at DESC, public_key ASC"
        params.append(scoped_owner_id)
    else:
        sql += "\nORDER BY lastmod DESC, last_advert DESC, updated_at DESC, public_key ASC"
    if limit is not None:
        if limit <= 0:
            pass  # no limit
        else:
            safe_limit = max(1, min(int(limit), 5000))
            sql += "\nLIMIT ?"
            params.append(safe_limit)
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, tuple(params)).fetchall()
    contacts = [contact_cache_row_to_dict(row) for row in rows]
    if not access_all:
        return contacts
    deduped: list[dict] = []
    seen_public_keys: set[str] = set()
    for contact in contacts:
        public_key = str(contact.get("public_key") or "").strip().lower()
        if len(public_key) != 64 or public_key in seen_public_keys:
            continue
        deduped.append(contact)
        seen_public_keys.add(public_key)
    return deduped


def get_cached_contact_raw(db_lock: threading.Lock, db_path: str, public_key: str) -> dict | None:
    target = _norm_key(public_key)
    if len(target) != 64:
        return None
    scoped_owner_id = get_scoped_owner_id()
    access_all = get_scoped_access_all()
    if not access_all and not scoped_owner_id:
        return None
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not access_all and scoped_owner_id:
            row = conn.execute(
                """
                SELECT
                    owner_id,
                    public_key,
                    adv_type,
                    flags,
                    path_len_byte,
                    out_path_len,
                    out_path_hash_len,
                    out_path,
                    adv_name,
                    last_advert,
                    adv_lat_raw,
                    adv_lon_raw,
                    lat,
                    lon,
                    has_location,
                    lastmod,
                    raw_payload_hex,
                    updated_at,
                    last_interaction_at,
                    last_public_traffic_at,
                    last_public_advert_at,
                    last_public_advert_mode,
                    last_materialized_at,
                    last_removed_from_node_at,
                    repeater_auth_password,
                    repeater_auth_saved_at,
                    is_local_self
                FROM contacts_cache
                WHERE owner_id = ? AND public_key = ?
                LIMIT 1
                """,
                (scoped_owner_id, target),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT
                    owner_id,
                    public_key,
                    adv_type,
                    flags,
                    path_len_byte,
                    out_path_len,
                    out_path_hash_len,
                    out_path,
                    adv_name,
                    last_advert,
                    adv_lat_raw,
                    adv_lon_raw,
                    lat,
                    lon,
                    has_location,
                    lastmod,
                    raw_payload_hex,
                    updated_at,
                    last_interaction_at,
                    last_public_traffic_at,
                    last_public_advert_at,
                    last_public_advert_mode,
                    last_materialized_at,
                    last_removed_from_node_at,
                    repeater_auth_password,
                    repeater_auth_saved_at,
                    is_local_self
                FROM contacts_cache
                WHERE public_key = ?
                ORDER BY CASE WHEN owner_id = ? THEN 0 ELSE 1 END, updated_at DESC, lastmod DESC
                LIMIT 1
                """,
                (target, scoped_owner_id),
            ).fetchone()
    return contact_cache_row_to_dict(row) if row is not None else None


def persist_contacts_cache(db_lock: threading.Lock, db_path: str, contacts: list[dict], now_epoch: int) -> None:
    owner_id = get_scoped_owner_id()
    valid = [(pk, c) for c in contacts if len(pk := _norm_key(c.get("public_key"))) == 64]
    if not valid:
        return
    if not owner_id:
        return
    valid_keys = [pk for pk, _ in valid]
    placeholders = ",".join("?" * len(valid_keys))
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing = {
            row["public_key"]: row
            for row in conn.execute(
                f"SELECT public_key, last_interaction_at, last_public_traffic_at, last_public_advert_at, last_public_advert_mode, last_materialized_at, last_removed_from_node_at, repeater_auth_password, repeater_auth_saved_at, is_local_self"
                f" FROM contacts_cache WHERE owner_id = ? AND public_key IN ({placeholders})",
                [owner_id, *valid_keys],
            ).fetchall()
        }
        rows = []
        for pk, c in valid:
            prev = existing.get(pk)
            rows.append((
                owner_id,
                pk,
                int(c.get("adv_type") or 0),
                int(c.get("flags") or 0),
                int(c.get("path_len_byte") or 0),
                int(c.get("out_path_len") or 0),
                int(c.get("out_path_hash_len") or 0),
                str(c.get("out_path") or ""),
                str(c.get("adv_name") or ""),
                int(c.get("last_advert") or 0),
                int(c.get("adv_lat_raw") or 0),
                int(c.get("adv_lon_raw") or 0),
                float(c.get("lat") or 0.0),
                float(c.get("lon") or 0.0),
                1 if c.get("has_location") else 0,
                int(c.get("lastmod") or 0),
                str(c.get("raw_payload_hex") or ""),
                int(now_epoch),
                int(prev["last_interaction_at"] if prev else 0),
                int(prev["last_public_traffic_at"] if prev else 0),
                int(max(int(prev["last_public_advert_at"] if prev else 0), int(c.get("last_advert") or 0))),
                str(prev["last_public_advert_mode"] if prev else ""),
                int(prev["last_materialized_at"] if prev else 0),
                int(prev["last_removed_from_node_at"] if prev else 0),
                str(prev["repeater_auth_password"] if prev else ""),
                int(prev["repeater_auth_saved_at"] if prev else 0),
                int(prev["is_local_self"] if prev else 0),
            ))
        conn.executemany(
            """
            INSERT INTO contacts_cache (
                owner_id,
                public_key,
                adv_type,
                flags,
                path_len_byte,
                out_path_len,
                out_path_hash_len,
                out_path,
                adv_name,
                last_advert,
                adv_lat_raw,
                adv_lon_raw,
                lat,
                lon,
                has_location,
                lastmod,
                raw_payload_hex,
                updated_at,
                last_interaction_at,
                last_public_traffic_at,
                last_public_advert_at,
                last_public_advert_mode,
                last_materialized_at,
                last_removed_from_node_at,
                repeater_auth_password,
                repeater_auth_saved_at,
                is_local_self
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, public_key) DO UPDATE SET
                adv_type=excluded.adv_type,
                flags=excluded.flags,
                path_len_byte=excluded.path_len_byte,
                out_path_len=excluded.out_path_len,
                out_path_hash_len=excluded.out_path_hash_len,
                out_path=excluded.out_path,
                adv_name=excluded.adv_name,
                last_advert=excluded.last_advert,
                adv_lat_raw=excluded.adv_lat_raw,
                adv_lon_raw=excluded.adv_lon_raw,
                lat=excluded.lat,
                lon=excluded.lon,
                has_location=excluded.has_location,
                lastmod=excluded.lastmod,
                raw_payload_hex=excluded.raw_payload_hex,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        _set_contact_store_last_sync_at(conn, now_epoch)
        conn.commit()


def get_contact_cache_metadata(
    db_lock: threading.Lock,
    db_path: str,
    *,
    now_epoch: int,
    stale_after_secs: int,
) -> dict:
    safe_stale_after_secs = max(0, int(stale_after_secs))
    owner_id = get_scoped_owner_id()
    access_all = get_scoped_access_all()
    if not access_all and not owner_id:
        return {
            "cached_contacts_total": 0,
            "last_sync_at": 0,
            "latest_cache_row_updated_at": 0,
            "is_empty": True,
            "is_stale": True,
            "stale_after_secs": safe_stale_after_secs,
        }
    with db_lock, sqlite3.connect(db_path) as conn:
        init_contact_store_schema(conn)
        if not access_all and owner_id:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS cached_contacts_total,
                    MAX(updated_at) AS latest_cache_row_updated_at
                FROM contacts_cache
                WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchone()
            cached_contacts_total = int(row[0] or 0) if row else 0
            latest_cache_row_updated_at = int(row[1] or 0) if row and row[1] is not None else 0
        else:
            rows = conn.execute(
                """
                SELECT public_key, owner_id, updated_at
                FROM contacts_cache
                ORDER BY CASE WHEN owner_id = ? THEN 0 ELSE 1 END, updated_at DESC, public_key ASC
                """,
                (owner_id,),
            ).fetchall()
            seen_public_keys: set[str] = set()
            cached_contacts_total = 0
            latest_cache_row_updated_at = 0
            for public_key, row_owner_id, updated_at in rows:
                normalized_public_key = _norm_key(public_key)
                if len(normalized_public_key) != 64 or normalized_public_key in seen_public_keys:
                    continue
                seen_public_keys.add(normalized_public_key)
                cached_contacts_total += 1
                latest_cache_row_updated_at = max(latest_cache_row_updated_at, int(updated_at or 0))
        last_sync_at = _get_contact_store_last_sync_at(conn)
    is_empty = cached_contacts_total == 0
    is_stale = last_sync_at <= 0 or (safe_stale_after_secs > 0 and int(now_epoch) - last_sync_at >= safe_stale_after_secs)
    return {
        "cached_contacts_total": cached_contacts_total,
        "last_sync_at": last_sync_at,
        "latest_cache_row_updated_at": latest_cache_row_updated_at,
        "is_empty": is_empty,
        "is_stale": is_stale,
        "stale_after_secs": safe_stale_after_secs,
    }


def cached_contact_to_model(contact: dict) -> Contact:
    public_key_hex = _norm_key(contact.get("public_key"))
    if len(public_key_hex) != 64:
        raise MeshCoreError("cached contact public_key must be 64 hex chars")
    out_path_hex = str(contact.get("out_path") or "").strip().lower()
    return Contact(
        public_key=bytes.fromhex(public_key_hex),
        adv_type=int(contact.get("adv_type") or 0),
        flags=int(contact.get("flags") or 0),
        path_len_byte=int(contact.get("path_len_byte") or 0),
        out_path_len=int(contact.get("out_path_len") or 0),
        out_path_hash_len=int(contact.get("out_path_hash_len") or 0),
        out_path=bytes.fromhex(out_path_hex) if out_path_hex else b"",
        adv_name=str(contact.get("adv_name") or ""),
        last_advert=int(contact.get("last_advert") or 0),
        adv_lat=int(contact.get("adv_lat_raw") or 0),
        adv_lon=int(contact.get("adv_lon_raw") or 0),
        lastmod=int(contact.get("lastmod") or 0),
        raw_payload_hex=str(contact.get("raw_payload_hex") or ""),
    )


def touch_cached_contact(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
    now_epoch: int,
    *,
    interaction: bool = False,
    materialized: bool = False,
) -> None:
    target = _norm_key(public_key)
    if len(target) != 64:
        return
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return
    fields: list[str] = []
    params: list[object] = []
    if interaction:
        fields.append("last_interaction_at = ?")
        params.append(int(now_epoch))
    if materialized:
        fields.append("last_materialized_at = ?")
        params.append(int(now_epoch))
        fields.append("last_removed_from_node_at = 0")
    if not fields:
        return
    params.append(target)
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE contacts_cache SET {', '.join(fields)} WHERE owner_id = ? AND public_key = ?",
            tuple([*params[:-1], owner_id, params[-1]]),
        )
        conn.commit()


def touch_cached_contact_packet_activity(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
    now_epoch: int,
    *,
    advert_mode: str | None = None,
) -> bool:
    target = _norm_key(public_key)
    if len(target) != 64:
        return False
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return False
    fields = [
        "last_interaction_at = ?",
        "last_public_traffic_at = ?",
    ]
    params: list[object] = [
        int(now_epoch),
        int(now_epoch),
    ]
    normalized_mode = str(advert_mode or "").strip().lower()
    if normalized_mode in {"direct", "flood"}:
        fields.append("last_public_advert_at = ?")
        params.append(int(now_epoch))
        fields.append("last_public_advert_mode = ?")
        params.append(normalized_mode)
    params.append(target)
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE contacts_cache SET {', '.join(fields)} WHERE owner_id = ? AND public_key = ?",
            tuple([*params[:-1], owner_id, params[-1]]),
        )
        conn.commit()
        return bool(cursor.rowcount)


def touch_cached_contact_packet_activity_by_prefix(
    db_lock: threading.Lock,
    db_path: str,
    pubkey_prefix: str,
    now_epoch: int,
) -> bool:
    prefix = _norm_key(pubkey_prefix)
    owner_id = get_scoped_owner_id()
    if len(prefix) != 12 or not owner_id:
        return False
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE contacts_cache
            SET last_interaction_at = ?,
                last_public_traffic_at = ?
            WHERE owner_id = ? AND substr(public_key, 1, 12) = ?
            """,
            (int(now_epoch), int(now_epoch), owner_id, prefix),
        )
        conn.commit()
        return bool(cursor.rowcount)


def set_cached_contact_route(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
    *,
    out_path_len: int,
    out_path_hash_len: int,
    out_path: str,
    now_epoch: int,
    interaction: bool = False,
) -> bool:
    target = _norm_key(public_key)
    if len(target) != 64:
        return False
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return False
    next_out_path_len = int(out_path_len)
    next_hash_len = int(out_path_hash_len)
    next_out_path = str(out_path or "").strip().lower()
    if next_out_path_len < 0:
        path_len_byte = 0xFF
        next_hash_len = 0
        next_out_path = ""
    else:
        if next_out_path_len > 63:
            raise MeshCoreError("contact route hop count must be <= 63")
        if next_hash_len < 1 or next_hash_len > 4:
            raise MeshCoreError("contact route hash size must be between 1 and 4 bytes")
        expected_hex_len = next_out_path_len * next_hash_len * 2
        if len(next_out_path) != expected_hex_len:
            raise MeshCoreError("contact route hex length does not match hop count and hash size")
        path_len_byte = ((next_hash_len - 1) << 6) | (next_out_path_len & 0x3F)
    fields = [
        "path_len_byte = ?",
        "out_path_len = ?",
        "out_path_hash_len = ?",
        "out_path = ?",
        "updated_at = ?",
    ]
    params: list[object] = [
        int(path_len_byte),
        int(next_out_path_len),
        int(next_hash_len),
        next_out_path,
        int(now_epoch),
    ]
    if interaction:
        fields.append("last_interaction_at = ?")
        params.append(int(now_epoch))
    params.append(target)
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE contacts_cache SET {', '.join(fields)} WHERE owner_id = ? AND public_key = ?",
            tuple([*params[:-1], owner_id, params[-1]]),
        )
        conn.commit()
        return bool(cursor.rowcount)


def touch_cached_contact_by_prefix(
    db_lock: threading.Lock,
    db_path: str,
    pubkey_prefix: str,
    now_epoch: int,
    *,
    interaction: bool = False,
) -> None:
    prefix = _norm_key(pubkey_prefix)
    owner_id = get_scoped_owner_id()
    if len(prefix) != 12 or not interaction or not owner_id:
        return
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE contacts_cache
            SET last_interaction_at = ?
            WHERE owner_id = ? AND substr(public_key, 1, 12) = ?
            """,
            (int(now_epoch), owner_id, prefix),
        )
        conn.commit()


def mark_cached_contacts_removed_from_node(
    db_lock: threading.Lock,
    db_path: str,
    public_keys: list[str],
    removed_at: int,
) -> None:
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return
    keys = [pk for public_key in public_keys if len(pk := _norm_key(public_key)) == 64]
    if not keys:
        return
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            UPDATE contacts_cache
            SET last_removed_from_node_at = ?
            WHERE owner_id = ? AND public_key = ?
            """,
            [(int(removed_at), owner_id, public_key) for public_key in keys],
        )
        conn.commit()


def delete_cached_contact(db_lock: threading.Lock, db_path: str, public_key: str) -> bool:
    target = _norm_key(public_key)
    if len(target) != 64:
        return False
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return False
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM contacts_cache WHERE owner_id = ? AND public_key = ?", (owner_id, target))
        conn.commit()
        return bool(cursor.rowcount)


def mark_cached_contact_as_local_self(db_lock: threading.Lock, db_path: str, public_key: str) -> bool:
    target = _norm_key(public_key)
    if len(target) != 64:
        return False
    owner_id = get_scoped_owner_id()
    if not owner_id:
        return False
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE contacts_cache
            SET is_local_self = 1
            WHERE owner_id = ? AND public_key = ?
            """,
            (owner_id, target),
        )
        conn.commit()
        return bool(cursor.rowcount)


def get_cached_contact_repeater_auth_password(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
) -> str:
    target = _norm_key(public_key)
    if len(target) != 64:
        return ""
    scoped_owner_id = get_scoped_owner_id()
    access_all = get_scoped_access_all()
    if not access_all and not scoped_owner_id:
        return ""
    with db_lock, sqlite3.connect(db_path) as conn:
        if not access_all and scoped_owner_id:
            row = conn.execute(
                """
                SELECT repeater_auth_password
                FROM contacts_cache
                WHERE owner_id = ? AND public_key = ?
                LIMIT 1
                """,
                (scoped_owner_id, target),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT repeater_auth_password
                FROM contacts_cache
                WHERE public_key = ?
                ORDER BY CASE WHEN owner_id = ? THEN 0 ELSE 1 END, updated_at DESC, lastmod DESC
                LIMIT 1
                """,
                (target, scoped_owner_id),
            ).fetchone()
    return str(row[0] or "") if row else ""


def set_cached_contact_repeater_auth_password(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
    password: str,
    now_epoch: int,
) -> bool:
    target = _norm_key(public_key)
    owner_id = get_scoped_owner_id()
    if len(target) != 64 or not owner_id:
        return False
    password_value = str(password or "")
    with db_lock, sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            """
            SELECT
                owner_id,
                public_key,
                adv_type,
                flags,
                path_len_byte,
                out_path_len,
                out_path_hash_len,
                out_path,
                adv_name,
                last_advert,
                adv_lat_raw,
                adv_lon_raw,
                lat,
                lon,
                has_location,
                lastmod,
                raw_payload_hex,
                updated_at,
                last_interaction_at,
                last_public_traffic_at,
                last_public_advert_at,
                last_public_advert_mode,
                last_materialized_at,
                last_removed_from_node_at,
                repeater_auth_password,
                repeater_auth_saved_at,
                is_local_self
            FROM contacts_cache
            WHERE public_key = ?
            ORDER BY CASE WHEN owner_id = ? THEN 0 ELSE 1 END, updated_at DESC, lastmod DESC
            LIMIT 1
            """,
            (target, owner_id),
        ).fetchone()
        base = dict(existing) if existing is not None else {}
        cursor = conn.execute(
            """
            INSERT INTO contacts_cache (
                owner_id,
                public_key,
                adv_type,
                flags,
                path_len_byte,
                out_path_len,
                out_path_hash_len,
                out_path,
                adv_name,
                last_advert,
                adv_lat_raw,
                adv_lon_raw,
                lat,
                lon,
                has_location,
                lastmod,
                raw_payload_hex,
                updated_at,
                last_interaction_at,
                last_public_traffic_at,
                last_public_advert_at,
                last_public_advert_mode,
                last_materialized_at,
                last_removed_from_node_at,
                repeater_auth_password,
                repeater_auth_saved_at,
                is_local_self
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, public_key) DO UPDATE SET
                repeater_auth_password = excluded.repeater_auth_password,
                repeater_auth_saved_at = excluded.repeater_auth_saved_at,
                updated_at = excluded.updated_at
            """,
            (
                owner_id,
                target,
                int(base.get("adv_type") or 0),
                int(base.get("flags") or 0),
                int(base.get("path_len_byte") or 0),
                int(base.get("out_path_len") or 0),
                int(base.get("out_path_hash_len") or 0),
                str(base.get("out_path") or ""),
                str(base.get("adv_name") or ""),
                int(base.get("last_advert") or 0),
                int(base.get("adv_lat_raw") or 0),
                int(base.get("adv_lon_raw") or 0),
                float(base.get("lat") or 0.0),
                float(base.get("lon") or 0.0),
                1 if base.get("has_location") else 0,
                int(base.get("lastmod") or 0),
                str(base.get("raw_payload_hex") or ""),
                int(now_epoch),
                int(base.get("last_interaction_at") or 0),
                int(base.get("last_public_traffic_at") or 0),
                int(base.get("last_public_advert_at") or 0),
                str(base.get("last_public_advert_mode") or ""),
                int(base.get("last_materialized_at") or 0),
                int(base.get("last_removed_from_node_at") or 0),
                password_value,
                int(now_epoch),
                int(base.get("is_local_self") or 0),
            ),
        )
        conn.commit()
        return bool(cursor.rowcount)


def clear_cached_contact_repeater_auth_password(
    db_lock: threading.Lock,
    db_path: str,
    public_key: str,
    now_epoch: int,
) -> bool:
    target = _norm_key(public_key)
    owner_id = get_scoped_owner_id()
    if len(target) != 64 or not owner_id:
        return False
    with db_lock, sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE contacts_cache
            SET repeater_auth_password = '', repeater_auth_saved_at = 0, updated_at = ?
            WHERE owner_id = ? AND public_key = ?
            """,
            (int(now_epoch), owner_id, target),
        )
        conn.commit()
        return bool(cursor.rowcount)


def contact_residency_timeout_secs(contact: dict, *, contact_timeout_secs: int, repeater_timeout_secs: int) -> int:
    return int(repeater_timeout_secs) if int(contact.get("adv_type") or 0) == ADVERT_TYPE_REPEATER else int(contact_timeout_secs)


def contact_activity_epoch(contact: dict) -> int:
    return max(
        int(contact.get("last_interaction_at") or 0),
        int(contact.get("last_materialized_at") or 0),
        int(contact.get("updated_at") or 0),
        int(contact.get("last_advert") or 0),
    )
