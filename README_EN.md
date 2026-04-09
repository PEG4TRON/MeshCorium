# Meshcorium

## Project Purpose

MeshCorium is a self-hosted MeshCore client with a hybrid contact system.

The project provides a unified interface for working with a MeshCore node through companion firmware and is intended for local deployment on a Linux host located next to the node.

Current primary transport:

- `USB serial`

`v0.5.3 -- Docker + USB` release status:

- `USB serial` — primary and validated connection path
- `BLE` — additional experimental path, not a replacement for USB
- `Wi-Fi` — UI placeholder only, real transport not implemented yet
- `Docker Compose` — included release deployment variant alongside the ordinary launcher/systemd flow

## Key Features

- Python backend with a local web UI
- Vue frontend for the main application surfaces
- channels, messages, and direct conversations
- contacts management backed by a local backend DB
- notifications with unread/mention/direct counters
- different notification sounds for different event types
- maps, routes, and route-trace tools
- remote repeater/room-server management through the companion session
- systemd-friendly launcher for local installation as a service

## Architecture In Short

- `meshcorium_web.py` — backend, HTTP API, SSE, session orchestration, local SQLite DBs
- `meshcorium_client.py` — MeshCore companion transport/protocol layer
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

This does not replace the ordinary launcher or systemd flow. It is an additional way to run the same release.

Default bind mounts in `docker-compose.yml`:

- `/etc/meshcorium` -> container config directory `/etc/meshcorium`
- `/var/lib/meshcorium` -> container runtime data directory `/var/lib/meshcorium`
- `/var/log/meshcorium` -> container log directory `/var/log/meshcorium`

The compose file also forwards one USB serial device by default:

- `${MESHCORIUM_SERIAL_DEVICE:-/dev/ttyUSB0}`

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
- BLE inside Docker is not a validated scenario yet; USB serial remains the primary expected transport

## Updating From `v0.5.0` / `v0.5.1`

Recommended update flow:

1. Stop the currently running MeshCorium instance.
   If it is installed as a service:
   - `sudo systemctl stop meshcorium.service`

2. Back up user data from the old installation:
   - `data/meshcorium_messages.sqlite3`
   - `data/meshcorium_contacts.sqlite3`
   - `data/client_settings.json`

3. Extract `v0.5.3 -- Docker + USB` into a new directory next to the old installation.

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
- Keep the old installation directory as a rollback copy until `v0.5.3` is confirmed to work correctly.

## Remove The systemd Service

```bash
./meshcorium-launcher.sh --service-remove
```

## Useful Notes

- If `web/dist` is already present, the launcher can use the existing frontend build as a fallback.
- The current release profile is focused on `USB` companion-node connectivity.
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
