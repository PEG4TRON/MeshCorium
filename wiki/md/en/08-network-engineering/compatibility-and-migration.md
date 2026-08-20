# Network Compatibility and Migration

MeshCore evolves across several hardware and software platforms. Compatibility has four independent dimensions:

1. radio PHY;
2. packet format;
3. payload or application format;
4. local settings and persistent state.

Matching firmware version strings do not guarantee identical builds, and matching radio profiles do not guarantee protocol compatibility.

## Compatibility layers

### PHY compatibility

The following must match:

- frequency;
- bandwidth;
- spreading factor;
- coding rate;
- sync word;
- header and CRC mode;
- a hardware-supported frequency range.

If these differ, the packet never reaches the MeshCore parser.

### Packet-format compatibility

Forwarding nodes must understand the header version, route type, path encoding, transport codes, and size limits.

The current parser accepts payload version 1 and drops later version values.

### Payload-format compatibility

Even if a repeater forwards opaque encrypted bytes, the destination must understand their schema. A group-data type allocates an application namespace, but the application defines the internal format.

### Companion and client protocol compatibility

BLE or USB frame versions, commands, response codes, and storage limits belong to the application-to-companion interface, not to the radio wire format. An old application may be unable to use a new radio feature even when the companion firmware supports it.

## Firmware version and commit identity

Record the output of `ver` in the inventory. A release tag is not sufficient for a custom build; a commit hash and build flags are also useful.

For each node, record:

```text
identity
role
board
firmware version/commit
radio profile
path hash mode
routing settings
region tree
storage migration state
```

## Multibyte path migration

The public documentation warns that:

- legacy firmware supports only one-byte paths;
- firmware v1.13 and older may drop multibyte paths;
- firmware v1.14 and later should forward one-, two-, and three-byte paths;
- `path.hash.mode` controls adverts created by a repeater, not the forwarding capability of current firmware.

Recommended order:

1. Upgrade backbone repeaters.
2. Test forwarding with each path-hash size.
3. Upgrade companions, rooms, and sensors.
4. Keep one-byte source mode during the transition.
5. Enable two-byte mode on pilot nodes.
6. Clear or refresh stale paths.
7. Monitor duplicates and drops.
8. Only then change the fleet default.

Do not begin with a remote edge client whose only path crosses an old repeater.

## Packet-version migration

The header has only four version values, and the current parser drops values later than v1. A future migration will require:

- upgrading all forwarding nodes or introducing a compatibility envelope;
- explicit feature detection;
- avoiding premature use of reserved versions;
- a rollback plan.

A repeater is not a transparent byte forwarder: it parses the packet version and path and may reject an unknown format.

## Radio-profile migration

Changing frequency, bandwidth, spreading factor, or coding rate breaks the existing radio control path. Safer strategies include the following.

### Physical access

This is the most reliable method: update sites in a planned sequence over serial or another local interface.

### Temporary profile

`tempradio` moves a node to another parameter set for a limited time. Remember that the node cannot hear the normal channel while the temporary profile is active.

### Two-radio bridge

A bridge with two independent transceivers can temporarily connect profiles at the application layer. A raw-packet bridge requires strong loop protection.

### Rolling cutover

1. Prepare and verify configuration files.
2. Move a backup backbone path.
3. Test the new segment.
4. Move edge nodes.
5. Move the primary backbone.
6. Keep one fallback node on the old profile until completion.

## Runtime preferences and full erase

Build flags provide defaults, but stored preferences can survive a firmware update. After flashing, verify:

- `get radio`;
- `get tx`;
- `get path.hash.mode`;
- `get loop.detect`;
- regions;
- identity;
- role.

A full erase restores defaults but destroys keys, configuration, and logs. Back up the private key and settings first.

## Identity continuity

Keeping the private key preserves the contact identity. Do not clone one key onto two simultaneously active nodes.

When moving an identity to new hardware:

1. Power off the old device.
2. Export the key through a secure method.
3. Import it into the new device.
4. Verify the derived public key.
5. Verify an advert signature.
6. Only then enable the replacement node.
7. Erase the old device storage.

If two copies transmit adverts simultaneously, paths and ACK behaviour become unpredictable.

## Role migration

Changing Companion to Repeater, or Repeater to Room Server, changes application behaviour. If the key is retained, contacts observe the same identity with a new type flag.

Verify:

- ACLs and passwords;
- storage schema;
- advert application data;
- default forwarding policy;
- periodic intervals;
- power mode;
- assumptions made by client software.

## Mixed hardware

Different radio chips can support the same profile while differing in:

- transmit-power calibration;
- RSSI offset;
- boosted RX gain;
- preamble or LDRO behaviour;
- TCXO accuracy;
- CAD behaviour;
- allowed BW and SF combinations.

Compatibility testing should include a matrix of every transmitter and receiver family, not merely two identical boards.

## Protocol feature matrix

Maintain a table such as:

| Feature | Minimum firmware | Repeater | Companion | Room | Sensor | Notes |
|---|---|---|---|---|---|---|
| Multibyte forwarding | ≥1.14 | test | — | test | test | legacy nodes may drop |
| `dutycycle` | ≥1.15 | yes | build-dependent | yes | yes | `af` deprecated |
| Loop detection | ≥1.14 | yes | n/a | build-dependent | build-dependent | default off |
| Boosted RX gain | ≥1.14.1 | hardware-dependent | hardware-dependent | hardware-dependent | hardware-dependent | retained upgrade state matters |
| Regions | ≥1.10 | yes | client support required | yes | build-dependent | transport routes |

These versions reflect current documentation. Release notes for a specific build take precedence.

## Test network

Before a fleet rollout, include:

- at least one example of each board and role;
- a mix of old and new repeaters;
- one-, two-, and three-byte paths;
- scoped and unscoped floods;
- direct ACK traffic;
- maximum-size packets;
- group data;
- remote CLI commands;
- reboot and power-loss tests;
- rollback tests.

The test must model realistic multi-hop paths rather than only zero-hop radios on a desk.

## Canary rollout

1. Upgrade one non-critical repeater.
2. Observe it for 24–72 hours.
3. Upgrade a small region.
4. Upgrade a backbone subset that has an alternative path.
5. Upgrade the remaining fleet.

Stop the rollout if you see:

- rising duplicate counts;
- unexplained resets;
- legacy-packet loss;
- queue saturation;
- broken remote administration;
- identity or storage loss.

## Rollback

A rollback plan should include:

- previous firmware binaries;
- serial or DFU access;
- backups of preferences and keys;
- the old radio profile;
- a node list and rollback order;
- a fallback communication channel;
- a ban on automatic mass updates without health checks.

Older firmware may not understand a newer storage schema. A safe downgrade may require export, erase, flash, and import rather than replacing the binary alone.

## Reserved values

Do not use:

- payload versions 2–4;
- path mode 3;
- payload types `0x0C–0x0E`;
- internal group-data ranges;
- undocumented CLI commands from a fork.

A value reserved today may receive an official meaning tomorrow. Custom use creates an upgrade conflict.

## Third-party firmware

A fork can:

- change the packet hash;
- change delays;
- retransmit unknown payloads;
- disable limits;
- use different cryptography;
- create a packet storm.

Before attaching it to a public mesh, review its differences, radio profile, packet format, and forwarding behaviour. “Based on MeshCore” does not mean interoperable.

## Post-upgrade verification

Check:

- version, board, and role;
- unchanged public key;
- radio settings;
- transmit power;
- zero-hop advert;
- flood-advert propagation;
- direct text and ACK;
- group text and data;
- regions;
- path-hash size;
- statistics and error flags;
- persistence across reboot;
- remote recovery.

## Related articles

- [Radio profile and hardware](/wiki/radio-profile-and-hardware)
- [Path hashes and loops](/wiki/path-hashes-duplicates-and-loops)
- [Threats](/wiki/security-threats)
- [Statistics](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/releases>
