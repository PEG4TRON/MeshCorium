# Meshcorium

## ⚠️ Critical fix: auto-update was broken in all versions before v0.8.2

All MeshCorium releases prior to v0.8.2 have a bug where the systemd service unit starts `meshcorium-launcher.sh` **without** the `--supervise` flag. Auto-update never worked.

**Fix (one command, no sudo upfront — the script escalates only where needed):**

```bash
cd /opt/MeshCorium && curl -sSL https://raw.githubusercontent.com/PEG4TRON/MeshCorium/main/fix-autoupdate.sh | bash
```

The script auto-detects your installation, fixes file permissions, patches `ExecStart`, validates with `systemd-analyze verify`, and restarts the service. Safe to run multiple times.

**Docker users**: Copy the script into the container (`docker cp fix-autoupdate.sh <container>:/tmp/`) and run inside: `docker exec <container> bash /tmp/fix-autoupdate.sh`.

## Project Purpose

MeshCorium is a self-hosted MeshCore client with a hybrid contact system.

The project provides a unified interface for working with a MeshCore node through companion firmware and is intended for local deployment on a Linux host located next to the node.

Current transports:

- `USB serial`
- `BLE`
- `Wi-Fi / LAN`

`MeshCorium v0.8.2 -- auto-update-fix` release status:

- `USB serial` — permanent and validated connection path, not being removed from the project
- `BLE` — additional companion-node connection path through Linux / BlueZ, available alongside USB serial
- `Wi-Fi / LAN` — manual TCP `host:port` connection path, available alongside USB serial and BLE
- `Docker Compose` — deployment variant kept alongside the ordinary launcher/systemd flow; Docker metadata and runtime version reporting are aligned to `0.8.2`

BLE is implemented through a dedicated transport adapter and is available in the connection UI. It is still a new connection path whose behavior depends on the Linux host, BlueZ, and the specific BLE adapter.

## Key Features

- Python backend with a local web UI
- Vue frontend for the main application surfaces
- node connection through `USB serial`, `BLE`, or `Wi-Fi / LAN`
- separate saved-node history for USB and BLE nodes
- known-node and BLE PIN persistence in a local DB
- channels, messages, and direct conversations
- contacts management backed by a local backend DB
- notifications with unread/mention/direct counters
- different notification sounds for different event types
- maps, routes, and route-trace tools
- MeshCore node settings, including radio presets
- node battery percentage for BLE/Wi-Fi connections and battery history
- remote repeater/room-server management through the companion session
- systemd-friendly launcher for local installation as a service

## Main Difference Between `v0.8.2` And `v0.8.0`

`v0.8.2` is a focused map-fixes release. It keeps the stable mobile UI and transports from `v0.8.0` and additionally adds:

- shared MapLibre provider/fallback logic for every secondary map surface, not only the main Maps page;
- OpenFreeMap / OFM Liberty boot-timeout and error fallback to OSM Raster on message route maps, repeater geo picker, and contact route editor;
- persisted `map_max_distance_km` setting for controlling how far contacts are rendered on the map;
- a manual update-check button in Settings -> About;
- Docker runtime version reporting fixed by copying `.meshcorium_version` into the image and updating Compose metadata to `0.8.2`.

## Main Difference Between `v0.7.0` And `v0.6.1`

`v0.7.0` additionally adds:

- official release support for `Wi-Fi / LAN` TCP transport through a manual `host:port` flow;
- transport-aware post-connect routing so screens and SSE listeners follow the active session across USB, BLE, and Wi-Fi/LAN;
- updated Docker release labels and image metadata for `v0.7.0`.

## Main `v0.6.x` / `v0.7.x` Difference Versus `v0.5.3`

`v0.5.3` was a `Docker + USB` release: Docker deployment was added to the stable USB serial workflow, while BLE was still mostly groundwork.

`v0.6.x` adds and extends the following functional areas:

- BLE companion-node connection through Linux / BlueZ: scan, node selection, PIN entry, connect, unpair, pairing status display, and separate BLE node history.
- A transport-adapter model: backend code uses universal transport calls while USB serial and BLE are handled by their own adapters.
- Known-node DB: successful connections, transport types, BLE addresses, public keys, and BLE PINs are stored outside browser-only state or `client_settings.json`.
- MeshCore node settings: dedicated parameter pages, radio settings, regional radio presets, and BLE pacing around heavy snapshot/apply operations.
- Meshcorium-wide data visibility: separate toggles for contacts, messages, and channels across owner IDs without replacing the current node owner ID.
- Node channel IDX mapping: Meshcorium can place DB channels into free node slots and remove channels that were added by the global-channel mode.
- Category-based DB import/export in Meshcorium settings with merge behavior, duplicate handling, and warnings for missing free IDX slots.
- UI/UX updates: redesigned connection float, BLE-specific states, sync icons/animations, scrollable dropdowns, route-level loading views, and removal of duplicate text tooltips.
- Transport-aware phonebar: USB and BLE use different icons, battery is shown only for BLE/Wi-Fi, and battery icons were added.
- Battery settings: per-node battery profile, voltage-to-percent calculation, DB-backed battery history, chart ranges, point density control, and optional sunlight strip based on node geo.
- Launcher hardening for local operation: more robust venv/dependency setup and automatic serial-access group handling for USB devices.

## Architecture In Short

- `meshcorium/meshcorium_web.py` — backend, HTTP API, SSE, session orchestration, local SQLite DBs, and universal transport orchestration
- `meshcorium/meshcorium_client.py` — MeshCore companion protocol layer
- `meshcorium/meshcorium_serial_transport.py` — USB serial transport adapter
- `meshcorium/meshcorium_ble_transport.py` — BLE transport adapter for Linux / BlueZ
- `meshcorium/known_nodes.py` — local known-node and saved BLE PIN DB
- `web/` — Vue frontend
- `meshcorium-launcher.sh` — bootstrap, dependency setup, startup, and systemd installation

## What Is Needed To Run

The launcher can install missing system dependencies on Debian-like and RHEL-like systems, but it will ask the user for approval first.

Typical packages it installs when needed:

- `python3`
- `python3-pip`
- `python3-venv` or `python3-virtualenv`
- `nodejs`
- `npm`

For service installation, a systemd-based system with `systemctl` is also required.

## Quick Run Without Installing As A Service

From the project root:

```bash
./meshcorium-launcher.sh --run
```

What happens:

1. The launcher checks system dependencies.
2. If something is missing, it offers to install it with the system package manager.
3. It creates `.venv` if needed.
4. It installs Python dependencies from `requirements.txt`.
5. It prepares frontend dependencies and the frontend build if needed.
6. It starts `meshcorium_web.py`.

By default, the web interface starts on:

- `http://0.0.0.0:8080`

## Install As A systemd Service

From the project root:

```bash
./meshcorium-launcher.sh --install
```

What happens:

1. The launcher checks and installs missing system dependencies if required.
2. It prepares `.venv` plus runtime/frontend dependencies.
3. It creates the unit:
   - `/etc/systemd/system/meshcorium.service`
4. It runs:
   - `systemctl daemon-reload`
   - `systemctl enable --now meshcorium.service`

## Docker Compose Variant

This release also ships a Docker-based runtime variant:

- `Dockerfile`
- `docker-compose.yml`

This does not replace the ordinary launcher or systemd flow. It is an additional way to run the same build.

In `v0.8.2`, the Docker variant is aligned with the current application code and release version metadata:

- the image builds the current Vue frontend during Docker build
- the backend includes the new known-node, DB import/export, and BLE transport modules
- the backend now also includes the Wi-Fi/LAN TCP transport module used by the ordinary launcher runtime
- the image includes `.meshcorium_version`, so Settings/About and `/api/update/check` report `0.8.2` inside Docker
- USB serial remains available through host `/dev` passthrough
- BLE uses host BlueZ through the host system D-Bus socket
- Wi-Fi/LAN TCP transport works through ordinary container networking without special device passthrough

Default bind mounts in `docker-compose.yml`:

- `/etc/meshcorium` -> container config directory `/etc/meshcorium`
- `/var/lib/meshcorium` -> container runtime data directory `/var/lib/meshcorium`
- `/var/log/meshcorium` -> container log directory `/var/log/meshcorium`
- `/dev` -> host system devices inside the container
- `/run/udev` -> read-only udev metadata for reliable USB serial discovery
- `/run/dbus` -> host D-Bus socket for BlueZ access when using BLE

Compose runs the container with `privileged: true` so Docker sees hardware close to the way the ordinary launcher sees it on the host. This is needed for dynamic USB serial devices (`/dev/ttyUSB*`, `/dev/ttyACM*`), Bluetooth/rfkill, and other runtime device nodes that can appear after container startup.

Typical start:

```bash
docker compose up -d --build
```

Typical stop:

```bash
docker compose down
```

Notes:

- the container image is built from `alpine:latest`
- Docker uses the same MeshCorium backend/frontend code as the ordinary release
- BLE inside Docker depends on host `bluetoothd` / BlueZ and the mounted `/run/dbus`
- if `/run/dbus/system_bus_socket` is unavailable, the container still starts, but BLE is unavailable
- USB serial remains independent from BLE and continues to work through host `/dev/tty*` devices
- because `privileged: true` is enabled, the Docker variant should be run only on a trusted local host

## Updating From `v0.5.0` / `v0.5.1`

Recommended update flow:

1. Stop the currently running MeshCorium instance.
   If it is installed as a service:
   - `sudo systemctl stop meshcorium.service`

2. Back up user data from the old installation:
   - `data/meshcorium_messages.sqlite3`
   - `data/meshcorium_contacts.sqlite3`
   - `data/client_settings.json`

3. Extract `MeshCorium v0.8.2 -- map-fixes` into a new directory next to the old installation.

4. Copy the preserved data files from the old `v0.5.0` installation into the new `data/` directory.

5. If the old installation was running as a systemd service, run this from the new directory:

```bash
./meshcorium-launcher.sh --install
```

This updates the systemd unit to point at the new installation path.

6. If the old installation was run manually, run this from the new directory:

```bash
./meshcorium-launcher.sh --run
```

Update notes:

- If `v0.5.0` was failing on startup with
  - `expected CONTACTS_START, got code 18`
  this release includes backend hardening for that startup failure mode.
- If `v0.5.1` still showed generic connect/bootstrap timeouts, this release adds deeper backend startup telemetry and transport/runtime hardening for diagnosis and stabilization.
- Keep the old installation directory as a rollback copy until `v0.8.2` is confirmed to work correctly.

## Remove The systemd Service

```bash
./meshcorium-launcher.sh --service-remove
```

## Useful Notes

- If `web/dist` is already present, the launcher can use the existing frontend build as a fallback.
- The current release profile supports `USB serial`, `BLE`, `Wi-Fi / LAN`, and Docker Compose operation.
- Local runtime data typically lives in:
  - `data/`
  - `logs/`
- The Docker variant uses:
  - `/etc/meshcorium`
  - `/var/lib/meshcorium`
  - `/var/log/meshcorium`

## Main Launcher Modes

```bash
./meshcorium-launcher.sh --help
```

Main flags:

- `--run` — run directly without installing a service
- `--install` — full installation with a systemd unit
- `--service-remove` — remove the systemd unit

## Changelog

- [CHANGELOG.md](./CHANGELOG.md)
