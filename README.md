# MeshCorium

Basic project overview:

- Full Russian README: [README_RU.md](./README_RU.md)
- Full English README: [README_EN.md](./README_EN.md)
- Changelog: [CHANGELOG.md](./CHANGELOG.md)

MeshCorium is a self-hosted MeshCore client with a hybrid contact system and a local web interface for working with a MeshCore node through companion firmware.

The development tree keeps the Docker Compose packaging variant from `v0.5.3` and now adds a functional BLE connection path alongside the permanent USB serial transport.

## Development Status

The latest published baseline is `v0.5.3 -- Docker + USB`.
The current `dev` branch is ahead of that release in user-facing functionality.

Key `dev` differences relative to `v0.5.3`:

- BLE node connection is now available next to USB serial through a Linux / BlueZ transport adapter.
- USB serial remains permanent and is not being removed.
- The connection UI now separates USB, BLE, and Wi-Fi placeholder modes, with BLE pairing/PIN handling and BLE node history.
- MeshCorium now keeps a known-node DB for successful connections, transport metadata, public keys, BLE addresses, and saved BLE PINs.
- MeshCore node settings were expanded with parameter pages, radio presets, and safer BLE pacing for heavy operations.
- Meshcorium settings now include broader owner-scope controls for contacts, messages, and channels, plus category-based DB import/export.
- Channel IDX handling was expanded so channels from the local DB can be placed into free node slots and later removed when global-channel mode is disabled.
- UI/UX was refreshed across the connection float, phonebar, dropdowns, sync animations, route loading, battery display, and notification/message flows.
- BLE/Wi-Fi battery percentage, battery profiles, and DB-backed battery history charts were added.
- The launcher was hardened around venv setup, frontend build fallback, and USB serial access groups.
- Docker was aligned with the dev runtime: it now includes the current backend modules and can use host BlueZ through D-Bus for BLE while keeping USB serial device passthrough.

Runtime variants remain:

- ordinary local launcher / systemd operation
- Docker Compose operation from the `v0.5.3` packaging work

Upgrade information from `v0.5.0` is documented in:

- [README_RU.md](./README_RU.md)
- [README_EN.md](./README_EN.md)
- [CHANGELOG.md](./CHANGELOG.md)

![MeshCorium screenshot](./SCREENSHOT.png)
