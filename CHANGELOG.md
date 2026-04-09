# Changelog

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
