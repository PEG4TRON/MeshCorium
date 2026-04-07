# Changelog

## dev

Current development state after the USB v0.5.0 release:

- Removed the old non-Vue legacy desktop/mobile frontend from runtime. Vue routes are now the active frontend contract; `/legacy/*` routes redirect to Vue equivalents, unknown non-API routes return 404, and a missing Vue build returns an explicit 503 instead of falling back to legacy UI.
- Introduced the connection abstraction layer for future non-USB transports: `ConnectionRouter`, `ConnectionDescriptor`, `SerialTransportAdapter`, `SerialPortTransport`, USB serial frame transport, and a transport-agnostic `MeshCoreClient` compatibility path.
- Added descriptor-aware backend connection payloads while preserving legacy `port` / `baudrate` USB compatibility.
- Added the first BLE transport implementation path behind the router:
  - Linux / BlueZ / `bleak` backend target.
  - Nordic UART Service UUID discovery.
  - raw BLE NUS payload flow without USB `<` / `>` framing.
  - BLE diagnostics for missing adapters, BlueZ/D-Bus failures, device advertising, connection timeout, and D-Bus disconnect cases.
- Added the first connection-screen BLE selector in Vue:
  - USB / BLE mode switch.
  - BLE scan through `/api/transports?type=ble`.
  - BLE device selector.
  - BLE pairing PIN input.
  - separate saved-node history for USB and BLE modes.
  - per-history-item forget action through `/api/client-settings/forget-connection`.
- Added `bleak` to Python requirements and extended launcher bootstrap planning for BlueZ.

Important BLE status:

- USB/serial is still the validated transport path.
- BLE is present in `dev`, but it is not fully debugged or validated yet.
- Live BLE testing was blocked by unstable VM Bluetooth passthrough and HCI controller failures on the available adapters, so BLE should be treated as experimental until verified on stable Linux/BlueZ hardware.

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
