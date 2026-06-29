# Repeater Connection Caching — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Eliminate redundant serial reconnection + device query + app_start + relogin on every `/api/repeater/login` and `/api/repeater/cli` HTTP request by routing repeater operations through the persistent background session client.

**Architecture:** The `BackgroundCompanionSession` already holds a live `MeshCoreSerialClient` (open serial connection, device queried, app started). Currently HTTP handlers bypass it and open their own temporary connections. The fix extends the background `command_queue` with two new command types — `repeater_login` and `repeater_cli_batch` — so the bg thread executes them on its existing client without closing/reopening the serial port.

**Tech Stack:** Python 3.11+, `meshcorium_client.py` (MeshCoreSerialClient), `meshcorium_web.py` (BaseHTTPRequestHandler + background session)

**Repeater password storage:** Already implemented — stored in `contacts_cache.repeater_auth_password` (SQLite column, schema v21), CRUD via `contact_store.py`/`contact_backend.py`, resolved at runtime by `_resolve_repeater_auth_password()`. After successful login, password is persisted: `CONTACT_BACKEND.set_cached_repeater_auth_password(public_key, password)`. Frontend: `ContactsView.vue` has `basic_admin_password`/`basic_guest_password` fields. No new storage work needed — the new queued command flow will use `_resolve_repeater_auth_password()` identically to the current handlers.

---

## Current Flow (problematic)

```
HTTP POST /api/repeater/login
  → _paused_background_session()        # stops bg thread, releases serial port
  → _open_meshcore_client()              # OPENS NEW serial connection
  → client.query_device()                # re-queries device info
  → client.app_start()                   # re-starts app
  → client.login_to_repeater()           # login handshake
  → client.close()                       # closes port
  → resume background session            # bg thread reopens its own connection

Same sequence repeats for /api/repeater/cli.
```

## Target Flow (after fix)

```
HTTP POST /api/repeater/cli
  → _enqueue_background_command(type="repeater_cli_batch", ...)
  → wait for bg thread to execute on existing session.client
  → return result

No serial reconnection. No device re-query. No app restart. Login reused if already authenticated.
```

---

## Files to Change

| File | What |
|------|------|
| `meshcorium/meshcorium_web.py` | Add command types, queue dispatch, HTTP handler rewrite |
| `meshcorium/meshcorium_client.py` | Add `send_repeater_login()` idempotency/is_authenticated flag |

---

### Task 1: Add repeater authentication state tracking to MeshCoreClient

**Objective:** Prevent redundant login handshake when client is already authenticated to repeater.

**Files:**
- Modify: `meshcorium/meshcorium_client.py` (~line 1550, `__init__`; ~line 1934, `send_repeater_login`)

**Step 1: Add `_repeater_authenticated` flag**

In `MeshCoreClient.__init__()`, after existing field initializations:

```python
self._repeater_authenticated: bool = False
```

**Step 2: Set flag on successful login, reset on close**

In `send_repeater_login()` (line 1934), after successful send — the caller `login_to_repeater()` at line 1969 handles the wait. Insert at start of `login_to_repeater()`:

```python
def login_to_repeater(self, password: str, timeout: float = 12.0) -> dict:
    # NEW: skip if already authenticated
    if self._repeater_authenticated:
        logging.debug("repeater: reusing existing authentication")
        return {"ok": True, "already_authenticated": True}
    # ... existing code ...
    # After successful wait_for_repeater_login:
    self._repeater_authenticated = True
```

In `close()` (~line 1575), reset:

```python
def close(self) -> None:
    self._repeater_authenticated = False
    # ... existing close code ...
```

**Step 3: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_client.py`
Expected: no output (success)

**Step 4: Commit**

```bash
git add meshcorium/meshcorium_client.py
git commit -m "feat: add repeater auth state tracking to MeshCoreClient"
```

---

### Task 2: Add repeater_login command type to background session

**Objective:** Allow background thread to execute repeater login on existing client.

**Files:**
- Modify: `meshcorium/meshcorium_web.py` (command processing loop)

**Step 1: Find the command dispatch loop**

Grep: `grep -n "command_type\|_process_command\|command_queue" meshcorium/meshcorium_web.py | head -10`

Identify where commands like `load-contacts`, `update-settings` etc. are dispatched.

**Step 2: Add `repeater_login` case to dispatch**

In the command-processing loop (likely inside `_run_background_session`), add alongside existing command types:

```python
elif command_type == "repeater_login":
    password = command.get("password", "")
    public_key = command.get("public_key", "")
    try:
        login_result = session.client.login_to_repeater(password)
        _set_background_command_result(
            session, command_id,
            {"ok": True, "login": login_result, "public_key": public_key}
        )
    except Exception as e:
        _set_background_command_result(
            session, command_id,
            {"ok": False, "error": str(e)}
        )
```

**Step 3: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_web.py`

**Step 4: Commit**

```bash
git add meshcorium/meshcorium_web.py
git commit -m "feat: add repeater_login command to background session"
```

---

### Task 3: Add repeater_cli_batch command type

**Objective:** Allow background thread to execute CLI commands on existing client.

**Files:**
- Modify: `meshcorium/meshcorium_web.py` (command dispatch)

**Step 1: Add `repeater_cli_batch` case**

```python
elif command_type == "repeater_cli_batch":
    password = command.get("password", "")
    commands = command.get("commands", [])
    try:
        login_result = session.client.login_to_repeater(password)
        results = []
        for cmd in commands:
            resp = session.client.send_repeater_cli_command(cmd)
            results.append({"command": cmd, "response": resp})
        _set_background_command_result(
            session, command_id,
            {"ok": True, "results": results}
        )
    except Exception as e:
        _set_background_command_result(
            session, command_id,
            {"ok": False, "error": str(e)}
        )
```

**Step 2: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_web.py`

**Step 3: Commit**

```bash
git add meshcorium/meshcorium_web.py
git commit -m "feat: add repeater_cli_batch command to background session"
```

---

### Task 4: Rewrite HTTP handler `/api/repeater/login` to use queued command

**Objective:** Replace the `_open_meshcore_client` + `_paused_background_session` dance with a simple queued command.

**Files:**
- Modify: `meshcorium/meshcorium_web.py` (do_POST handler around line 14159)

**Step 1: Find current handler**

Read current `/api/repeater/login` handler (line 14159, ±40 lines context).

**Step 2: Replace with queued command version**

Replace the entire handler block with:

```python
if parsed.path == "/api/repeater/login":
    password = str(body.get("password") or "")
    if not password:
        raise ValueError("password is required")
    session = _get_background_session(conn["port"])
    if not session or not session.client:
        # Fallback: open fresh connection if no bg client available
        with _open_meshcore_client(session_kwargs) as client:
            device = client.query_device()
            client.app_start()
            login_payload, login_timing = _login_to_repeater_with_client(
                client, session, password
            )
        self._send_json({
            "ok": True,
            "login": login_payload,
            "device": device,
        })
        return
    # Use existing background client
    result = _enqueue_and_wait(session, {
        "type": "repeater_login",
        "password": password,
        "public_key": session.repeater_tracker.get("current_repeater_public_key", ""),
    })
    self._send_json(result)
    return
```

**Step 3: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_web.py`

**Step 4: Commit**

```bash
git add meshcorium/meshcorium_web.py
git commit -m "refactor: /api/repeater/login uses bg session client"
```

---

### Task 5: Rewrite HTTP handler `/api/repeater/cli` to use queued command

**Objective:** Same as Task 4 but for CLI endpoint.

**Files:**
- Modify: `meshcorium/meshcorium_web.py` (do_POST handler around line 14195)

**Step 1: Find current handler**

Read current `/api/repeater/cli` handler (line 14195, ±50 lines context).

**Step 2: Replace with queued command version**

Replace the entire handler block with:

```python
if parsed.path == "/api/repeater/cli":
    password = _resolve_repeater_auth_password(conn, body)
    if not password:
        raise ValueError("repeater password not configured")
    commands = body.get("commands") or []
    if not commands:
        raise ValueError("commands list is required")
    session = _get_background_session(conn["port"])
    if not session or not session.client:
        # Fallback: open fresh connection if no bg client
        with _paused_background_session(session_kwargs["port"]):
            with _connection_access_from_kwargs(session_kwargs):
                with _open_meshcore_client(session_kwargs) as client:
                    client.query_device()
                    client.app_start()
                    results = _run_repeater_cli_batch_with_client(
                        client, session, password, commands
                    )
        self._send_json({"ok": True, "results": results})
        return
    # Use existing background client
    result = _enqueue_and_wait(session, {
        "type": "repeater_cli_batch",
        "password": password,
        "commands": commands,
    })
    self._send_json(result)
    return
```

**Step 3: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_web.py`

**Step 4: Commit**

```bash
git add meshcorium/meshcorium_web.py
git commit -m "refactor: /api/repeater/cli uses bg session client"
```

---

### Task 6: Add `_enqueue_and_wait()` helper if not exists

**Objective:** A helper that enqueues a command and blocks until the background thread processes it.

**Files:**
- Add to/modify: `meshcorium/meshcorium_web.py`

**Step 1: Check if already exists**

Grep: `grep -n "_enqueue_and_wait\|_set_background_command_result\|_enqueue_background_command" meshcorium/meshcorium_web.py | head -10`

If `_enqueue_background_command()` already exists, use it. Otherwise implement:

```python
import threading

def _enqueue_and_wait(session: BackgroundCompanionSession, command: dict, timeout: float = 30.0) -> dict:
    """Enqueue a command to background session and wait for result."""
    import uuid
    command_id = str(uuid.uuid4())[:8]
    command["command_id"] = command_id
    result_event = threading.Event()
    result_holder = {}
    
    # Store the event so the bg thread can signal when done
    if not hasattr(session, '_command_events'):
        session._command_events = {}
    session._command_events[command_id] = (result_event, result_holder)
    
    session.command_queue.put(command)
    
    if not result_event.wait(timeout=timeout):
        session._command_events.pop(command_id, None)
        return {"ok": False, "error": f"command {command_id} timed out after {timeout}s"}
    
    session._command_events.pop(command_id, None)
    return result_holder.get("result", {"ok": False, "error": "no result"})
```

**Step 2: Wire `_set_background_command_result` to signal the event**

In the bg thread command dispatch (where results are stored), after computing the result:

```python
# After processing command_type, signal waiting threads
if hasattr(session, '_command_events') and command_id in session._command_events:
    event, holder = session._command_events[command_id]
    holder["result"] = computed_result
    event.set()
```

**Step 3: Verify syntax**

Run: `python3 -m py_compile meshcorium/meshcorium_web.py`

**Step 4: Commit**

```bash
git add meshcorium/meshcorium_web.py
git commit -m "feat: add _enqueue_and_wait helper for bg command results"
```

---

### Task 7: Integration test on test stand

**Objective:** Verify the caching works — first login takes normal time, second login is instant.

**Steps:**

1. Deploy to 192.168.4.3
2. Send first `/api/repeater/login` — expect normal response time (~3-5s)
3. Send second `/api/repeater/login` — expect immediate response (<500ms, `already_authenticated: true`)
4. Send `/api/repeater/cli` — expect no re-login overhead
5. Check logs: no `_open_meshcore_client` calls for repeater endpoints

---

### Task 8: Frontend — remove auto-relogin on CLI failure

**Objective:** Currently frontend redirects to `/login` on 500 from CLI. With cached connection, 500 should be a retryable error, not session loss.

**Files:**
- Modify: `web/src/views/ContactsView.vue` (or wherever repeater CLI is called)

**Step 1: Find the CLI error handler**

Grep: `grep -n "repeater.*cli\|location-gps\|api/repeater" web/src/views/ContactsView.vue | head -10`

**Step 2: Change 500 handling**

Instead of redirecting to login on 500 from repeater CLI, show an inline error toast:

```javascript
} catch (e) {
  if (e.status === 500) {
    // Don't redirect — show inline error
    repeaterCliError.value = t('contacts.repeater.cliRetryHint')
  } else if (e.status === 401) {
    // Real auth loss — redirect
    window.location.href = '/login'
  }
}
```

**Step 3: Verify build**

Run: `cd web && npm run build 2>&1 | tail -5`
Expected: `built in Xs`

**Step 4: Commit**

```bash
git add web/src/views/ContactsView.vue web/dist/
git commit -m "fix: don't redirect to login on repeater CLI 500"
```

---

## Summary

| Task | Files | Lines (est.) | TDD |
|------|-------|-------------|-----|
| 1 | `meshcorium_client.py` | +8 | No (hardware-dependent) |
| 2 | `meshcorium_web.py` | +15 | No |
| 3 | `meshcorium_web.py` | +20 | No |
| 4 | `meshcorium_web.py` | −30 +15 | No |
| 5 | `meshcorium_web.py` | −40 +20 | No |
| 6 | `meshcorium_web.py` | +30 | No |
| 7 | Deploy + manual | — | Integration |
| 8 | `ContactsView.vue` | +5 | Build check |

**Total:** ~90 lines of new code, ~70 lines removed.

## Risks

- **Race condition:** bg thread might be mid-operation when HTTP handler enqueues. Mitigation: command queue is already thread-safe.
- **Timeout:** If bg thread is stuck on serial read, queued command will time out. Fallback to old behavior in that case (already coded in Tasks 4-5).
- **Session.client is None:** After bg thread crash/restart, `session.client` may be None. Fallback handled.
