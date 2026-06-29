# MeshCorium

Basic project overview:

- Full Russian README: [README_RU.md](./README_RU.md)
- Full English README: [README_EN.md](./README_EN.md)
- Changelog: [CHANGELOG.md](./CHANGELOG.md)

MeshCorium is a self-hosted MeshCore client with a hybrid contact system and a local web interface for working with a MeshCore node through companion firmware.

## ⚠️ Critical fix: auto-update was broken in all versions before v0.8.2

All MeshCorium releases prior to v0.8.2 have a bug where the systemd service unit starts `meshcorium-launcher.sh` **without** the `--supervise` flag. This means the supervisor loop (GitHub release polling, self-update lifecycle) never starts — your installation will never discover or install updates.

**Fix (one command, safe for all versions):**

```bash
cd /opt/MeshCorium && curl -sSL https://raw.githubusercontent.com/PEG4TRON/MeshCorium/main/fix-autoupdate.sh | bash
```

Or if curl is not available:

```bash
cd /opt/MeshCorium && wget -qO- https://raw.githubusercontent.com/PEG4TRON/MeshCorium/main/fix-autoupdate.sh | bash
```

What the script does:
- Detects your MeshCorium installation and version
- Checks if the launcher supports `--supervise` (versions ≥ 0.5.0)
- Creates a timestamped backup of the systemd unit
- Adds `--supervise` to the `ExecStart` line
- Runs `systemd-analyze verify` to validate
- Reloads and restarts the service

**Docker users**: The Docker entrypoint runs `meshcorium/meshcorium_web.py` directly (no launcher). To fix, copy the script into the running container:

```bash
docker cp fix-autoupdate.sh meshcorium:/tmp/
docker exec meshcorium bash /tmp/fix-autoupdate.sh
```

Then update your `docker-compose.yml` to use the latest image.

After the fix, supervisor will poll GitHub every 30 minutes. When a new release is found, a green "U" badge appears on the bell icon — click it, go to Settings → About, and press "Install Update".

Current release `0.8.2--auto-update-fix` is a critical hotfix: adds missing `--supervise` flag to systemd service `ExecStart`, enabling the self-update lifecycle that was broken in all previous releases.

## Preview

[![Watch the MeshCorium video overview](https://img.youtube.com/vi/m--5rg7x7uU/hqdefault.jpg)](https://youtu.be/m--5rg7x7uU)

![MeshCorium screenshot](./SCREENSHOT.png)

## Release Status

The latest published release is `MeshCorium v0.8.3 -- Fixes & Mobile App`.

### v0.8.3 — Fixes & Mobile App

- **CRITICAL**: Added `--supervise` to `ExecStart` in systemd unit template. Without it, auto-update never worked — supervisor loop (GitHub polling, `.meshcorium_update_available`, install/rollback) was never started.
- Existing installations must run `meshcorium-launcher.sh --install` after upgrading to apply the fix.

### v0.8.1 — mobile-ux-quality

- **Messages**: fixed broken scroll-to-bottom button — direct jump to newest DB messages with `latest=true` API, ghost channel detection (empty `channel_identity`), infinite-loop guard in scroll-to-newest.
- **Mobile UI**: Send button repositioned (right, symmetric to GIF), paper-plane icon without text, message timestamp moved to bubble footer with year in format.
- **Icon system**: all emoji replaced with stroke-based SVG icons in cyan-to-blue gradient, `MobileDockButton` supports SVG URLs.
- **Components**: `MobileNodebar` and `MobileDockBar` extracted from duplicative HTML in `MessagesView`.
- **CSS engineering**: `100vh`→`100dvh`, unified border-radius CSS vars, `:active`/`:focus-visible`/`transition` across all interactive elements, skeleton loaders, `@supports` replacing `.is-firefox` classes.
- **Performance**: RAF debounce for conversation list scroll metrics.
- **Docker**: image includes `.meshcorium_version`, `/api/update/check` reports `0.8.2`, all root Python files explicitly listed in Dockerfile.

### v0.7.0 — Docker + USB + BLE + WIFI/LAN

Key `v0.7.0` differences relative to `v0.6.1`:

- Wi-Fi/LAN TCP transport is now part of the release profile with a manual `host:port` connection flow instead of a placeholder-only transport tab.
- Runtime session routing was extended so post-connect screens, SSE listeners, message history bootstrap, and dialog previews behave transport-aware across USB, BLE, and Wi-Fi/LAN.
- Docker release metadata was bumped to `v0.7.0`, and the Docker bundle still builds the current frontend/backend version from the release tree, including Wi-Fi/LAN transport support.

Core `v0.6.x` / `v0.7.x` differences relative to `v0.5.3 -- Docker + USB`:

- BLE node connection is now available next to USB serial through a Linux / BlueZ transport adapter.
- USB serial remains permanent and is not being removed.
- The connection UI now separates USB, BLE, and Wi-Fi/LAN modes, with BLE pairing/PIN handling, BLE node history, and manual TCP `host:port` Wi-Fi/LAN connection.
- MeshCorium now keeps a known-node DB for successful connections, transport metadata, public keys, BLE addresses, and saved BLE PINs.
- MeshCore node settings were expanded with parameter pages, radio presets, and safer BLE pacing for heavy operations.
- Meshcorium settings now include broader owner-scope controls for contacts, messages, and channels, plus category-based DB import/export.
- Channel IDX handling was expanded so channels from the local DB can be placed into free node slots and later removed when global-channel mode is disabled.
- UI/UX was refreshed across the connection float, phonebar, dropdowns, sync animations, route loading, battery display, and notification/message flows.
- BLE/Wi-Fi battery percentage, battery profiles, and DB-backed battery history charts were added.
- The launcher was hardened around venv setup, frontend build fallback, and USB serial access groups.
- Docker was aligned with the current runtime: it now includes the current backend modules, uses host BlueZ through D-Bus for BLE, exposes host `/dev` so USB serial discovery behaves like the ordinary launcher path, and ships the Wi-Fi/LAN transport module in the same image.

Runtime variants:

- ordinary local launcher / systemd operation
- Docker Compose operation with USB, BLE host integration, and Wi-Fi/LAN TCP transport

Upgrade information is documented in:

- [README_RU.md](./README_RU.md)
- [README_EN.md](./README_EN.md)
- [CHANGELOG.md](./CHANGELOG.md)

---

**⚠️ Release note:** Due to issues with the AI agent used during the release process, releases v0.7.1 through v0.7.4 experienced deployment and integrity problems. **v0.8.0 is considered the first fully working release** after this period. Users on v0.7.1–v0.7.4 should upgrade to v0.8.2 or later.

---

**⚠️ Примечание к релизам:** Из-за проблем с ИИ-агентом, использованным в процессе выпуска, релизы v0.7.1–v0.7.4 имели проблемы с деплоем и целостностью. **v0.8.0 считается первым полностью исправным релизом** после этого периода. Пользователям v0.7.1–v0.7.4 рекомендуется обновиться до v0.8.2 или выше.
