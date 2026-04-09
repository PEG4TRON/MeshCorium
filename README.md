# MeshCorium

Basic project overview:

- Full Russian README: [README_RU.md](./README_RU.md)
- Full English README: [README_EN.md](./README_EN.md)
- Changelog: [CHANGELOG.md](./CHANGELOG.md)

MeshCorium is a self-hosted MeshCore client with a hybrid contact system and a local web interface for working with a MeshCore node through companion firmware.

The development tree now also includes a Docker Compose packaging variant for the next release, while keeping the ordinary launcher/systemd runtime path intact.

## Release Status

This `v0.5.3 -- Docker + USB` release keeps USB/serial as the validated connection path.
BLE discovery and connection plumbing are included as experimental groundwork,
but BLE operation is not yet fully debugged or validated.

The release bundle now includes two supported runtime variants:

- ordinary local launcher / systemd operation
- Docker Compose operation

Upgrade information from `v0.5.0` is documented in:

- [README_RU.md](./README_RU.md)
- [README_EN.md](./README_EN.md)
- [CHANGELOG.md](./CHANGELOG.md)

![MeshCorium screenshot](./SCREENSHOT.png)
