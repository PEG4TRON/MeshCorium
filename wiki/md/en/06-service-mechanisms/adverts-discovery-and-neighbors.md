# Adverts, Discovery, and Neighbors

MeshCore uses several discovery mechanisms. An advert distributes a signed identity and public node properties. Control discovery queries nearby nodes. A repeater's neighbor table stores recent zero-hop advertisements. These mechanisms are related, but they do not form one routing table.

## Advert as a public identity card

`PAYLOAD_TYPE_ADVERT` contains:

```text
public_key  32 bytes
timestamp    4 bytes
signature   64 bytes
appdata      variable
```

The Ed25519 signature covers `public_key + timestamp + appdata`. A receiver can verify that the advert was created by the identity owner and was not modified in transit.

An advert is not encrypted. Any receiver can see:

- public key;
- timestamp;
- node type;
- name;
- coordinates, when published;
- packet path and region metadata.

Do not place confidential information in the name or owner information.

## Appdata flags

Published format:

| Value | Meaning |
|---:|---|
| `0x01` | Chat/Companion |
| `0x02` | Repeater |
| `0x03` | Room Server |
| `0x04` | Sensor |
| `0x10` | Latitude/longitude present |
| `0x20` | Feature 1 reserved |
| `0x40` | Feature 2 reserved |
| `0x80` | Name present |

Values `0x01–0x04` encode the role in the low part of the flags byte. The other bits indicate optional fields.

Coordinates are stored as signed integers:

```text
stored = degrees · 1,000,000
```

For example, `52.520000` becomes `52520000`.

## Appdata size limit

`MAX_ADVERT_DATA_SIZE = 32`. These 32 bytes include flags, coordinates, feature fields, and the name.

The CLI documents a maximum name length of:

- up to 32 bytes without location;
- up to 24 bytes with location.

These are bytes, not Unicode characters. Non-ASCII UTF-8 characters consume multiple bytes. A client must truncate at a valid UTF-8 sequence boundary.

## Flood advert

Command:

```text
advert
```

This creates a flood advert. Repeaters append path entries. A receiver can save both the identity and the route by which the advert arrived.

Benefits:

- discovery over multiple hops;
- contact-metadata updates;
- route creation toward the source;
- repeater mapping.

Cost:

- the advert is large because of its public key and signature;
- every forwarding step repeats its airtime;
- a dense mesh receives many duplicates;
- a short interval can overload the channel.

## Zero-hop advert

Command:

```text
advert.zerohop
```

The packet should remain within the local radio neighborhood. It is useful for:

- checking a radio profile;
- neighbor discovery;
- local setup;
- updating nearby devices without a flood;
- antenna and SNR diagnostics.

A zero-hop advert does not prove multi-hop connectivity.

## Intervals

### Flood advert interval

```text
get flood.advert.interval
set flood.advert.interval <3..168 hours>
```

Documented defaults:

- Repeater: 12 hours;
- Sensor: 0.

`0` usually disables periodic advertising, but role- and version-specific behavior should be checked.

### Zero-hop interval

```text
get advert.interval
set advert.interval <60..240 minutes>
```

The value is rounded down to a multiple of two. Default is `0`.

Periodic zero-hop adverts help maintain neighbor tables, but a large number of local nodes still consumes shared airtime.

## Timestamp and freshness

The signature protects timestamp integrity, but does not guarantee that the sender's clock is correct. A node with bad time may publish an advert from the “future” or from a very old date.

A client needs a policy that:

- does not overwrite newer metadata with older metadata;
- accounts for reboot and clock reset;
- does not delete a contact solely because an advert is old;
- displays locally observed last-heard time separately from advert time.

`last heard` is local receive time. `advert timestamp` is sender time.

## Control discovery

`PAYLOAD_TYPE_CONTROL` subtypes `DISCOVER_REQ` and `DISCOVER_RESP` are intended for local discovery.

### Request

```text
flags       1 byte
type_filter 1 byte
tag         4 bytes
since       4 bytes optional
```

- upper nibble `0x8` — request subtype;
- lowest bit — `prefix_only`;
- `type_filter` selects roles;
- `tag` is a random correlation identifier;
- `since` limits responses by time.

### Response

```text
flags  1 byte
snr    1 byte signed, SNR×4
tag    4 bytes
pubkey 8 or 32 bytes
```

- upper nibble `0x9`;
- lower nibble — node type;
- tag is copied from the request;
- key may be a prefix or full key.

## Why discovery is zero-hop

In `Mesh.cpp`, the relevant subset of control packets is processed only when the path is empty. This prevents a flood of responses across the entire mesh and limits disclosure of local topology.

Use adverts and path discovery for multi-hop discovery rather than a broadcast control query.

## Neighbor table

Repeater command:

```text
neighbors
```

Output is limited to the eight most recent adverts. Each line is:

```text
{pubkey-prefix}:{timestamp}:{snr*4}
```

The table describes recent zero-hop neighbors, not:

- every reachable node;
- every saved contact;
- every hop in a direct path;
- guaranteed bidirectional links;
- currently online users.

An advert may have been received once before the neighbor disappeared.

## Removal and rediscovery

```text
neighbor.remove <pubkey_prefix>
discover.neighbors
```

A prefix may match multiple entries. According to the documentation, an empty prefix or a space removes all matching entries. Removal is not a block rule: a later advert adds the neighbor again.

`discover.neighbors` initiates a local query; responses refresh the table.

## Auto-add contacts

Companion firmware has auto-add flags for advert types and an overwrite-oldest mode. This is contact-storage behavior, not radio routing. Receiving an advert does not have to create a contact automatically; user policy may require confirmation.

Auto-add in a dense public network is risky:

- the contact table fills;
- old entries are evicted;
- malicious adverts create churn;
- hash collisions complicate selection.

## Advert path

A Companion can request the stored advert path with `CMD_GET_ADVERT_PATH`. It is the route over which a particular advert reached the device. It can be used as a direct-path candidate, but:

- it may be stale;
- it is selected by first-wins behavior;
- it may contain a mobile repeater;
- the reverse direction may be worse;
- hash size must be stored together with the count.

## Diagnostics

### No zero-hop advert

Check:

- frequency, BW, SF, and CR;
- sync word and firmware family;
- antenna;
- RSSI and noise floor;
- RX state;
- packet parser and logs.

### Zero-hop works, flood does not

Check:

- `repeat` on the neighboring repeater;
- `flood.max.advert`;
- region policy;
- seen and loop detection;
- path-hash compatibility;
- duty budget and queue.

### Advert works, messages do not

An advert is public and does not require a peer secret. Check the contact key, path, encryption and MAC, and the reverse ACK route.

## Related articles

- [Service Payloads](/wiki/service-payloads)
- [Flood Routing](/wiki/flood-routing)
- [RSSI, SNR, and Link Quality](/wiki/rssi-snr-and-link-quality)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>
