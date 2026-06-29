# Repeater CLI Commands — Audit & Alignment Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Audit all repeater CLI commands in Meshcorium codebase, compare with MeshCore firmware reference protocol, verify correctness of proxying, and fix any misalignments.

**Date:** 2026-06-29

---

## Phase 1: Inventory (already done — see below)

### 1.1 Our repeater API endpoints

| Endpoint | Line | Purpose | Status |
|----------|------|---------|--------|
| `POST /api/repeater/login` | 14191 | Auth to repeater (password + public_key) | ✅ Works (fixed 2026-06-29) |
| `POST /api/repeater/cli` | 14215 | Batch CLI commands via bg session | ✅ Works (fixed 2026-06-29) |
| `POST /api/repeater/auth/delete` | 14241 | Delete cached repeater password | ⚠️ Not tested |

### 1.2 Client-side repeater methods (meshcorium_client.py)

| Method | Line | Signature | Status |
|--------|------|-----------|--------|
| `parse_repeater_login_push()` | 394 | Frame parser | ✅ Protocol-compliant |
| `send_repeater_login()` | 1936 | Login to repeater via contact msg | ✅ |
| `wait_for_repeater_login()` | 1951 | Wait for login response | ✅ |
| `login_to_repeater()` | 1971 | Full login cycle with retry | ✅ `_repeater_authenticated` flag added |
| `send_repeater_cli_command()` | 2012 | Send CLI as `txt_type=1` contact msg | ✅ Call signature fixed |

### 1.3 Transport mechanism

```text
HTTP POST /api/repeater/cli {commands: ["location-gps", "ver"]}
  → _run_command_via_background_session()
    → bg thread: kind == "repeater_cli_batch"
      → login_to_repeater(destination, password)
      → send_repeater_cli_command(destination, cmd) for each cmd
        → send_contact_text_message(txt_type=1, payload=cmd)
```

✅ Architecture confirmed: Meshcorium is a **transparent proxy**. It does NOT parse, validate, or filter CLI commands. Any string passed in `commands[]` is forwarded to the firmware as-is via `send_contact_text_message(txt_type=0x01)`.

---

## Phase 2: Reference vs Our Code — Comparison

### 2.1 Reference CLI commands (from MeshCore `CommonCLI.cpp` + `docs/cli_commands.md`)

~80+ commands grouped by category:

| Category | Commands | Our Frontend |
|----------|----------|-------------|
| **Operational** | poweroff, shutdown, reboot, clkreboot, clock, advert, start ota, erase | ❌ None |
| **Neighbors** | neighbors, neighbor.remove, discover.neighbors | ❌ None |
| **Stats** | clear stats, stats-core, stats-radio, stats-packets | ❌ None |
| **Logging** | log start, log stop, log erase, log | ❌ None |
| **Info** | ver, board | ❌ None |
| **Radio config** | get/set radio, get/set tx, tempradio, get/set freq, get/set radio.rxgain | ❌ None |
| **System config** | get/set name, get/set lat, get/set lon, get/set prv.key, password, guest.password, owner.info, adc.multiplier, public.key, ver, role, powersaving | ❌ None |
| **Routing** | get/set repeat, path.hash.mode, loop.detect, txdelay, direct.txdelay, rxdelay, dutycycle, af, int.thresh, agc.reset.interval, multi.acks, flood.advert.interval, advert.interval, flood.max, flood.max.unscoped, flood.max.advert | ❌ None |
| **ACL** | setperm, get acl, get/set allow.read.only | ❌ None |
| **Region** | region load/save/allowf/denyf/get/home/default/put/def/remove/list | ❌ None |
| **GPS** | gps on/off/sync/setloc/advert | ✅ **location-gps** (only one!) |
| **Sensors** | sensor list/get/set | ❌ None |
| **Bridge** | get/set bridge.type/enabled/delay/source/baud/channel/secret | ❌ None |
| **Power mgmt** | get bootloader.ver, pwrmgt.support/source/bootreason/bootmv | ❌ None |

### 2.2 What's wired up in our frontend

| Frontend page/component | CLI command sent | Status |
|--------------------------|-----------------|--------|
| `/contacts/repeater/:key/location-gps` | `location-gps` | ✅ Working (2026-06-29) |
| *(nothing else)* | — | ❌ All other ~80 commands are backend-only, no frontend UI |

### 2.3 What's FINE (no action needed)

~ ~~Meshcorium correctly proxies ALL reference CLI commands. Since it does not parse command strings, ANY command from the reference list works transparently through `/api/repeater/cli`.~~ ✅

~ ~~Transport layer: `txt_type=0x01` matches reference protocol. Login handshake is protocol-compliant.~~ ✅

~ ~~Login state caching (`_repeater_authenticated`) is correct for the stateless-HTTP-on-serial model.~~ ✅

~ ~~JSON serialization: `RepeaterLoginResult` and `SentMessageInfo` now properly converted to dicts.~~ ✅

~ ~~Button label: "Connect"/"Подключиться" instead of confusing "Apply"/"Применить".~~ ✅

~ ~~Inline error handling: 500 on CLI no longer redirects to /login.~~ ✅

~ ~~Password storage: persists in `contacts_cache.repeater_auth_password`.~~ ✅

~ ~~`/api/repeater/auth/delete` — deletes cached password, standard HTTP DELETE semantics, no protocol issues.~~ ✅

---

## Phase 3: Items Needing Fix/Improvement

### 🔧 Item 1: Frontend only exposes ONE of ~80 CLI commands

**Current state:** Only `location-gps` has a frontend UI page. All other commands (ver, neighbors, stats, radio config, etc.) are API-only with no user interface.

**Severity:** Low (feature gap, not a bug)

**Action:** Add command-picker UI to repeater management panel — either a text input for arbitrary commands, or curated command launchers for common actions (ver, neighbors, stats-radio, etc.).

**Files:** `ContactsView.vue` (repeater management panel), `en.js`/`ru.js` (i18n)

---

### 🔧 Item 2: `_repeater_login_result_to_dict()` field mapping completeness

**Current state:** Converter at line 6597 extracts fields from `RepeaterLoginResult`. Need to verify all fields in the dataclass are captured in the dict output.

**Severity:** Medium (potential silent data loss in API response)

**Action:** Read the dataclass definition of `RepeaterLoginResult`, compare with dict keys in `_repeater_login_result_to_dict()`, ensure 1:1 mapping.

**Files:** `meshcorium_client.py` (dataclass), `meshcorium_web.py` (converter line 6597)

---

### 🔧 Item 3: `send_contact_text_message()` return type — `SentMessageInfo` fields

**Current state:** Our serialization extracts `route_flag`, `expected_ack_hex`, `suggested_timeout_ms`. Reference code at lines 6724-6728 uses the same fields.

**Severity:** Low (already matches reference)

**Action:** READ-ONLY verification — confirm no additional fields exist on `SentMessageInfo` that should be serialized but aren't.

**Files:** `meshcorium_client.py` (dataclass definition)

---

### 🔧 Item 4: Command delay (`command_delay_secs=0.2`) 

**Current state:** `_run_repeater_cli_batch_with_client()` uses `command_delay_secs=0.2` between commands. In our bg session dispatcher, there is NO DELAY — commands sent sequentially without pause.

**Severity:** Medium (may cause firmware buffer overflow with many commands)

**Action:** Add `time.sleep(0.2)` between `send_repeater_cli_command()` calls in the bg dispatcher `repeater_cli_batch` block, matching the delay in `_run_repeater_cli_batch_with_client`.

**Files:** `meshcorium_web.py` (dispatcher block ~7577-7581)

---

### 🔧 Item 5: Error handling — CLI command failure

**Current state:** If one command in a batch fails, the error is swallowed silently (`resp` may contain error info but we don't check it). The reference code propagates errors per-command.

**Severity:** Medium (user can't tell which command failed)

**Action:** Check `resp` for error indicators (if `SentMessageInfo` has `ok` or `error` fields), include per-command status in results dict.

**Files:** `meshcorium_web.py` (dispatcher block ~7577-7581), `meshcorium_client.py` (`SentMessageInfo` dataclass)

---

### 🔧 Item 6: `/api/repeater/auth/delete` — unchanged by our refactoring

**Current state:** This endpoint was NOT touched by the bg-session refactoring. It still uses the old pattern of `_contact_owner_scope` + `_resolve_repeater_auth_password`. Should be verified working.

**Severity:** Low (separate endpoint, may still work)

**Action:** READ-ONLY check — verify this endpoint is functional. If broken, refactor to use `_run_command_via_background_session()` with a new `kind == "repeater_auth_delete"` command.

**Files:** `meshcorium_web.py` (handler ~14241)

---

## Summary

| # | Item | Action | Severity |
|---|------|--------|----------|
| ~ | All 80+ CLI commands proxied correctly | ✅ No action | — |
| ~ | Transport layer (`txt_type=0x01`) | ✅ No action | — |
| ~ | Login, auth, JSON serialization | ✅ Fixed 2026-06-29 | — |
| ~ | Button label, inline error, password storage | ✅ Fixed 2026-06-29 | — |
| 1 | Only location-gps in frontend | 💡 Feature: add CLI command UI | Low |
| 2 | `_repeater_login_result_to_dict()` completeness | 🔍 Verify field mapping | Medium |
| 3 | `SentMessageInfo` fields completeness | 🔍 Verify field mapping | Low |
| 4 | Missing command delay in bg dispatcher | 🔧 Add `time.sleep(0.2)` | Medium |
| 5 | Per-command error reporting | 🔧 Check resp for errors | Medium |
| 6 | `/api/repeater/auth/delete` untested | 🔍 Read-only audit | Low |

---

## Execution Order

**Read-only checks first:**
- Item 2: Verify `_repeater_login_result_to_dict()` field mapping
- Item 3: Verify `SentMessageInfo` field mapping
- Item 6: Audit `/api/repeater/auth/delete` handler

**Fixes (non-breaking):**
- Item 4: Add command delay to bg dispatcher
- Item 5: Add per-command error reporting

**Future feature:**
- Item 1: Frontend CLI command UI (separate plan)
