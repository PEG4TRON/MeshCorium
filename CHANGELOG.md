# Changelog

## v0.7.1

Release `MeshCorium v0.7.1 -- BUGFIX` fixes a message loading bug that appeared in active chats with a large backlog of unread messages.

### Message history loading fix

- Fixed a bug where only the messages immediately around the first unread marker were loaded when entering a chat, preventing the UI from reaching the most recent messages through normal scrolling.
- Added the ability to load newer messages by scrolling toward the bottom of the chat, symmetrical to the existing scroll-up-to-load-earlier behavior.
- The «scroll to newest» button now automatically loads all the way to the absolute newest message in the database instead of stopping at the edge of the current local window.
- Backend: added `after_message_id` parameter to `/api/messages/channel` and `/api/messages/contact` endpoints.

## Dev / Unreleased

- No unreleased notes yet after `v0.7.1`.

## v0.7.0

Release `MeshCorium v0.7.0 -- Docker + USB + BLE + WIFI/LAN` promotes the previously experimental Wi-Fi/LAN TCP transport into the published release profile and aligns the runtime so post-connect behavior is transport-aware across USB, BLE, and Wi-Fi/LAN.

### Wi-Fi / LAN transport

- Wi-Fi/LAN TCP companion transport is now part of the release bundle through `meshcorium_wifi_transport.py` and `WIFI_TRANSPORT_TYPE` router integration.
- The connection UI now exposes a real manual `host:port` Wi-Fi/LAN connect flow instead of a placeholder-only transport tab.
- Saved/startup connection handling, phonebar transport state, and settings-side connection selection now understand Wi-Fi/LAN endpoints as first-class transport profiles.

### Runtime parity and message flow

- Active session routing for SSE, API requests, and post-connect screens was extended so Contacts, Messages, Maps, Settings, and shell runtime logic follow the actual active transport instead of assuming USB-only `selectedPort` semantics.
- Bootstrap now performs an initial queued-message drain after `ready` so message history does not wait for a later `MSG_WAITING` event before appearing.
- Wi-Fi frame read timeouts are now treated as transient idle gaps rather than fatal reader failures, reducing disconnects during long idle periods or heavy channel history reads.
- Conversation previews now stay aligned between the open chat and the dialog card list by applying fresh `/api/messages/conversations` preview data to live on-node dialog rows.

### Docker and packaging

- Docker release metadata now uses `v0.7.0` labels.
- The release Docker bundle continues to build the frontend inside Docker build and includes the current backend/frontend code used by the ordinary launcher runtime, including Wi-Fi/LAN transport support.
- Launcher-side frontend builds now reserve a larger default Node heap, reducing Vite out-of-memory failures on weaker hosts during release startup/build paths.

## v0.6.1

Release `MeshCorium v0.6.1 -- Docker + USB + BLE` is based on `v0.6.0` and keeps the same runtime variants while adding browser-side unread notifications and unread badge propagation into the tab title.

### Notifications and browser UX

- Browser notifications are now emitted for unread growth across all unread types after the current owner-scope and mute filters are applied.
- The browser tab title now receives a combined unread badge so MeshCorium remains visible even when the tab is in the background.
- Notification permission is requested from a real user gesture inside the shell so browser delivery works without breaking initial page load.

### Docker and runtime

- Docker release metadata now uses `v0.6.1` labels.
- The release Docker bundle continues to build the frontend inside Docker build and includes the current backend/frontend code used by the ordinary launcher runtime.

## v0.6.0

Release `MeshCorium v0.6.0 -- Docker + USB + BLE` promotes the post-`v0.5.3` development work into a release. The key difference from `v0.5.3 -- Docker + USB` is that BLE is now shipped as an available node connection path alongside the permanent USB serial transport, while Docker remains part of the ordinary release bundle.

### Connection and transports

- BLE connection to a MeshCore companion node is now available alongside the permanent USB serial transport.
- USB serial remains a first-class supported path and is not being removed.
- BLE support now includes discovery, node selection, PIN entry, connect flow, unpair action, pairing status, and separate BLE history in the connection UI.
- Backend transport handling was moved further toward the adapter model: USB serial and BLE are handled by transport-specific adapters while higher-level backend code uses universal connection/session calls.
- Known-node persistence was added for successful connections, transport type, BLE address, public key, node name, and saved BLE PIN state.
- BLE PIN handling was changed from repeated dynamic rotation to one-time managed initialization after the first successful user-provided PIN connection, with the saved PIN kept in the known-node DB.
- Wi-Fi remains a UI placeholder and is not yet a real transport.

### MeshCore node settings

- `/settings/node/meshcore-params` was expanded into dedicated MeshCore parameter pages.
- Radio settings now include regional presets, including a Russia preset, and safer backend application through the companion client instead of direct serial-only paths.
- BLE snapshot/apply operations now include pacing and short cooldowns to reduce the chance of overloading BLE-connected nodes during repeated heavy settings reads or writes.
- A separate battery settings page was added under `/settings/node/battery`.
- Battery profile settings allow per-node voltage range calibration for displayed battery percentage.

### Meshcorium data and owner-scope features

- Meshcorium settings now include separate controls for global contacts, messages, and channels across owner IDs.
- Global channel access can place channels from the local DB into free node IDX slots and remove the channels that were added by that mode when it is disabled.
- Channel metadata now tracks where channels exist on nodes and which IDX slots they occupy.
- Dialog/channel editing was extended with delete flows that remove channel IDX data from the node where applicable.
- Category-based DB import/export was added to `/settings/meshcorium`; imports merge with existing data, ignore exact duplicates, and surface conflicts where user choice is needed.

### Messages, notifications, and channels

- Message and unread handling was adjusted so owner-scope filtering affects counters, notification badges, and conversation visibility consistently.
- Mute / mentions-only behavior was corrected so ordinary unread badges and notification entries do not appear when a conversation is muted except for mentions.
- Channel list and conversation flows were updated around global-channel visibility and node IDX availability.

### UI and UX

- The connection float was redesigned around transport modes, with BLE-specific states and history separated from USB serial state.
- The phonebar is transport-aware: USB and BLE use different connection icons, while battery percentage is shown only for BLE/Wi-Fi style connections.
- Battery icons were added next to the phonebar battery percentage.
- Sync icons and active sync/scan animations were unified around `icons/sync.svg`.
- Dropdowns were improved with scroll handling and optional filtering when the menu does not fit on screen.
- Duplicate hover hints were removed where button text already explains the action.
- Route-level loading components were added for heavier Vue screens.
- Static visual assets such as background images are now cache-friendly for the browser.

### Battery history

- Battery readings are persisted per node owner ID.
- The battery page now includes a DB-backed graph with presets for 6 hours, 12 hours, 1 day, 1 week, 1 month, and custom ranges.
- The graph supports density control by averaging samples at lower density.
- Optional sunlight context can be shown under the graph when node geo is valid; all-zero coordinates are treated as missing geo.
- Battery history retention can be configured for 7 days, 1 month, 3 months, 6 months, or 1 year.

### Launcher and runtime

- Launcher venv handling was hardened so partial or missing virtual environments are recreated more reliably.
- Launcher can add the current user to serial-access groups detected from USB serial devices, such as `dialout`.
- Frontend build behavior remains compatible with a prebuilt `web/dist` fallback, while still rebuilding locally when Node/NPM are present.
- Docker was updated for the current runtime: the image now includes the new backend modules required by `meshcorium_web.py`, mounts host `/dev` and read-only `/run/udev` for launcher-like device visibility, and mounts host `/run/dbus` so BLE can use host BlueZ from inside the container.
- The Docker image tag and release label now use `v0.6.0` metadata instead of the old `v0.5.3-docker` label.

## v0.5.3

Release `v0.5.3 -- Docker + USB` is based on post-`v0.5.2` development work and adds the first official Docker packaging variant alongside the ordinary USB release workflow.

### Docker and runtime layout

- The release bundle now includes both:
  - the ordinary local launcher / systemd runtime
  - a Docker Compose runtime variant
- Added:
  - `Dockerfile`
  - `docker-compose.yml`
  - `docker/docker-entrypoint.sh`
  - `.dockerignore`
  - `defaults/client_settings.json`
- Docker runtime layout is now:
  - `/etc/meshcorium` for config
  - `/var/lib/meshcorium` for runtime data and SQLite DBs
  - `/var/log/meshcorium` for logs
- `meshcorium_web.py` now supports environment-driven runtime paths so the same backend can run in both local and containerized layouts without losing the ordinary `data/` + `logs/` defaults.

### Release notes

- USB/serial remains the validated primary transport.
- Docker is now an official packaging/deployment variant in the release bundle.
- BLE remains experimental groundwork and is not yet considered fully debugged or validated.

## Next release

### Docker and runtime layout

- Added a Docker deployment variant to the release bundle:
  - `Dockerfile`
  - `docker-compose.yml`
- Docker layout is prepared around:
  - `/etc/meshcorium` for config
  - `/var/lib/meshcorium` for runtime data
  - `/var/log/meshcorium` for logs
- `meshcorium_web.py` now supports environment-driven runtime paths via:
  - `MESHCORIUM_CONFIG_DIR`
  - `MESHCORIUM_DATA_DIR`
  - `MESHCORIUM_LOG_DIR`
  - optional `MESHCORIUM_CLIENT_SETTINGS_PATH`
- Ordinary launcher and systemd usage remain supported; Docker is an additional release variant, not a replacement.

## v0.5.2

Release `v0.5.2 -- USB` is based on post-`v0.5.1` development work and includes the following additional user-visible changes on top of `v0.5.1`.

### Stability and diagnostics

- Background-session startup now emits staged bootstrap telemetry into backend logs, so connect timeouts record the last completed bootstrap phase instead of failing with only a generic ready timeout.
- The companion client response-matching race was fixed so very fast replies are no longer orphaned and misreported as:
  - `empty response to APP_START`
  - `empty response to SEND_CHANNEL_MSG`
- Transport-boundary cleanup was completed: direct serial runtime construction is now confined to the adapter/discovery layer while active runtime paths stay on `ConnectionRouter -> MeshCoreClient(...)`.
- Frontend diagnostics logging now tolerates file permission/ownership issues without breaking request handling.

### Frontend and settings

- `/settings/about` now shows a branded sticky header with the MeshCorium logo and the current app version.
- MeshCore settings work in the Vue settings workspace was extended further on both backend and frontend sides.

### Release notes

- USB/serial remains the validated primary transport.
- BLE remains experimental groundwork and is not yet considered fully debugged or validated.

## v0.5.1

Release `v0.5.1 -- USB` is based on post-`v0.5.0` development work and includes the following user-visible changes relative to `v0.5.0`.

### Runtime and transport

- USB/serial remains the primary and permanent supported transport.
- Companion-session internals were refactored around a transport abstraction:
  - `ConnectionRouter`
  - `ConnectionDescriptor`
  - `SerialTransportAdapter`
  - transport-aware `MeshCoreClient`
- Descriptor-aware backend connection payloads were added while preserving legacy `port` / `baudrate` USB compatibility.
- Startup hardening was added for companion radios that can emit stray `CHANNEL_INFO` frames while the client is waiting for `CONTACTS_START`. This addresses a startup failure seen in `v0.5.0` as:
  - `expected CONTACTS_START, got code 18`
- BLE transport groundwork is included in this release tree as experimental code:
  - Linux / BlueZ / `bleak` backend path
  - Nordic UART Service discovery
  - BLE diagnostics and pairing PIN UI path
  - BLE is not yet considered fully debugged or validated
- A Wi-Fi connection mode placeholder was added to the connection float as a future expansion point. It is not implemented as a real transport in this release.

### Frontend and UX

- The old non-Vue legacy frontend was removed from runtime use.
- Vue routes are now the active frontend contract.
- `/legacy/*` routes redirect to Vue equivalents instead of loading the old UI.
- Unknown non-API routes return `404`.
- Missing Vue build now returns an explicit `503` instead of falling back to the old legacy frontend.
- Connection screen updates:
  - USB / BLE / Wi-Fi transport selector
  - separate saved-node history per transport mode
  - forget action for saved connection history entries
  - BLE pairing PIN is treated as transient input and is no longer persisted in browser storage

### Messaging, notifications, and contacts

- Message, unread, direct, and highlight flows were refined in the Vue frontend.
- Contact and workspace UX received multiple improvements across list presentation and detail views.
- Contact timeline fields and “last heard / advert / traffic” presentation were improved in the contact workspace.
- Direct-history message recall in the composer was extended and improved.
- Clicking sender / mention names in chat can open matching contacts.

### Repeater tooling

- Repeater management flow received multiple UI and persistence improvements.
- Saved repeater authorization support was added on the backend side.
- Repeater login float behavior was improved for retry handling and timeout cases.

### Launcher, docs, and packaging readiness

- Launcher bootstrap behavior was improved for raw Debian-like and RHEL-like systems.
- Launcher can install missing system dependencies with user approval.
- README set, screenshot, and release packaging layout were expanded compared to `v0.5.0`.
- Packaging groundwork and FHS-oriented planning were documented for future `deb` / `rpm` work.

### Important release notes

- USB/serial support is not being removed. BLE is an additional connection option, not a replacement.
- BLE code is included for forward progress, but USB remains the validated path for this release.
- If you are updating specifically to avoid the `expected CONTACTS_START, got code 18` startup failure from `v0.5.0`, this release contains the corresponding backend hardening.

## v0.5.0

Initial public USB release of MeshCorium.

Highlights:

- self-hosted MeshCore client with a hybrid contact system
- Python backend with local web interface
- Vue frontend for Messages, Contacts, Maps, and Settings
- local contact database with node-exported contact persistence
- unread, mention, and direct notification flows
- repeater and room-server management through companion session
- launcher with `--run`, `--install`, and `--service-remove`
- Debian-like and RHEL-like dependency bootstrap in the launcher

Notes:

- this release is focused on USB companion connectivity
- BLE transport is not included in this release
