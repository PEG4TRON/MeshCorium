"""Tests for _sanitize_message_timestamp display guard (read-side only).

The helper must:
- keep sender_ts when it is within 1 hour of wall clock;
- fall back to fallback_ts (received_at) when out of tolerance;
- fall back to now when fallback_ts is missing/zero;
- never rewrite stored data (guaranteed by design: it is pure and stateless).

Plus sort_timestamp mechanics (Option 3):
- backfill SQL must match helper semantics;
- hourly sweep must touch only future-dated / NULL-sort rows.
"""

import ast
import os
import sqlite3
import time

WEB_PY = os.path.join(os.path.dirname(__file__), "..", "meshcorium", "meshcorium_web.py")


def _load_sanitize_helper():
    """Extract _sanitize_message_timestamp from meshcorium_web.py without importing the module."""
    with open(WEB_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_sanitize_message_timestamp":
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            ns = {"time": time}
            exec(compile(module, WEB_PY, "exec"), ns)
            return ns["_sanitize_message_timestamp"]
    raise AssertionError("_sanitize_message_timestamp not found in meshcorium_web.py")


sanitize = _load_sanitize_helper()
_YEAR = 365 * 86400

BACKFILL_SQL = """
UPDATE messages
SET sort_timestamp = CASE
    WHEN abs(sender_timestamp - ?) > 3600 THEN received_at
    ELSE sender_timestamp
END
"""

SWEEP_SQL = """
UPDATE messages
SET sort_timestamp = CASE
    WHEN abs(sender_timestamp - ?) > 3600 THEN received_at
    ELSE sender_timestamp
END
WHERE sort_timestamp IS NULL
   OR (sender_timestamp > ? AND sort_timestamp != received_at)
"""


def _now():
    return int(time.time())


def _make_table(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, sender_timestamp INTEGER, received_at INTEGER NOT NULL, sort_timestamp INTEGER)"
    )
    conn.executemany(
        "INSERT INTO messages (id, sender_timestamp, received_at, sort_timestamp) VALUES (?, ?, ?, ?)",
        rows,
    )
    return conn


class TestSanitizeMessageTimestamp:
    def test_normal_timestamp_kept(self):
        now = _now()
        assert sanitize(now - 60) == now - 60

    def test_future_beyond_tolerance_falls_back_to_received_at(self):
        now = _now()
        future = now + 30 * _YEAR
        assert sanitize(future, now - 5) == now - 5

    def test_past_beyond_tolerance_falls_back(self):
        now = _now()
        past = now - 400 * 86400
        assert sanitize(past, now - 10) == now - 10

    def test_fallback_zero_uses_now(self):
        now = _now()
        future = now + 50 * _YEAR
        result = sanitize(future, 0)
        assert abs(result - now) <= 2

    def test_fallback_none_uses_now(self):
        now = _now()
        future = now + 10 * _YEAR
        result = sanitize(future)
        assert abs(result - now) <= 2

    def test_exact_tolerance_boundary(self):
        now = _now()
        assert sanitize(now + 3600) == now + 3600
        assert sanitize(now + 3601, now - 5) == now - 5

    def test_zero_and_none_unchanged(self):
        assert sanitize(0) == 0
        assert sanitize(None) == 0

    def test_garbage_input_returns_zero(self):
        assert sanitize("not-a-number") == 0
        assert sanitize(None, _now()) == 0

    def test_received_at_preferred_over_now(self):
        now = _now()
        future = now + 100 * _YEAR
        assert sanitize(future, now - 100) == now - 100


class TestSortTimestampBackfill:
    def test_backfill_matches_helper_semantics(self):
        now = _now()
        rows = [
            (1, now - 60, now - 61, None),           # normal live message
            (2, now + 30 * _YEAR, now - 5, None),    # corrupt future (the stand case)
            (3, now - 400 * 86400, now - 10, None),  # far past
            (4, now + 1800, now - 1, None),          # within tolerance, slightly future
            (5, 0, now - 3, None),                   # zero ts -> rank by received_at
        ]
        conn = _make_table(rows)
        conn.execute(BACKFILL_SQL, (now,))
        out = dict(conn.execute("SELECT id, sort_timestamp FROM messages ORDER BY id").fetchall())
        conn.close()
        assert out[1] == now - 60                    # normal: sender kept
        assert out[2] == now - 5                     # future: received_at
        assert out[3] == now - 10                    # far past: received_at
        assert out[4] == now + 1800                  # in tolerance: sender kept
        assert out[5] == now - 3                     # ts=0: received_at (rank by arrival)

    def test_sweep_touches_only_future_or_null_rows(self):
        now = _now()
        rows = [
            (1, now - 60, now - 61, now - 60),                  # normal: not touched
            (2, now + 30 * _YEAR, now - 5, now + 30 * _YEAR),   # future not yet fixed: touched
            (3, now + 30 * _YEAR, now - 5, now - 5),            # future already fixed: not touched
            (4, now + 1800, now - 1, now + 1800),               # in tolerance: not touched
            (5, now - 60, now - 61, None),                      # NULL sort: touched
        ]
        conn = _make_table(rows)
        threshold = now + 3600
        cur = conn.execute(SWEEP_SQL, (now, threshold))
        updated = cur.rowcount
        out = dict(conn.execute("SELECT id, sort_timestamp FROM messages ORDER BY id").fetchall())
        conn.close()
        assert updated == 2, f"expected 2 updates, got {updated}"
        assert out[2] == now - 5
        assert out[5] == now - 60   # CASE: in tolerance -> sender kept
        # untouched rows keep their values
        assert out[1] == now - 60
        assert out[3] == now - 5
        assert out[4] == now + 1800
