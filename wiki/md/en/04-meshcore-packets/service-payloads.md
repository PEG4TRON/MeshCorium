# MeshCore Service Payloads

Service packets keep the mesh operational: they announce identities, acknowledge delivery, return routes, measure paths, and perform local discovery. They consume the same airtime as user messages, so their frequency affects network capacity.

## `PAYLOAD_TYPE_ADVERT`

An advert announces a node and its public properties.

| Field | Size |
|---|---:|
| public key | 32 bytes |
| timestamp | 4 bytes |
| signature | 64 bytes |
| appdata | Remaining bytes |

Appdata:

| Field | Size | Condition |
|---|---:|---|
| flags | 1 | Always when appdata exists |
| latitude | 4 | `has location` |
| longitude | 4 | `has location` |
| feature 1 | 2 | Reserved flag |
| feature 2 | 2 | Reserved flag |
| name | Remaining bytes | `has name` |

Node flags:

| Value | Type/field |
|---:|---|
| `0x01` | Chat node |
| `0x02` | Repeater |
| `0x03` | Room Server |
| `0x04` | Sensor |
| `0x10` | Location present |
| `0x20` | Feature 1 |
| `0x40` | Feature 2 |
| `0x80` | Name present |

The first four values represent a type in the low bits, not four independent bit flags. Code should extract the type according to the implementation rather than treating `flags & 0x03` as two simultaneous properties.

The signature covers public key, timestamp, and appdata. A modified advert is rejected. A valid but old advert still requires a separate freshness policy.

## `PAYLOAD_TYPE_ACK`

ACK payload:

```text
checksum: 4 bytes
```

The checksum is a CRC over the original message timestamp, text, and sender public key. It associates the acknowledgment with a specific message without repeating the whole payload.

An ACK may be:

- a separate packet;
- `extra` inside a returned path;
- part of a multipart or Multi-ACK sequence.

A CLI command does not trigger a normal ACK under the same rules.

## `PAYLOAD_TYPE_PATH`

PATH uses the addressed wrapper and peer-secret encryption. Its plaintext is:

| Field | Size |
|---|---:|
| path length | 1 byte |
| path | size × count |
| extra type | 1 byte |
| extra | Remaining bytes |

A returned path describes a route back to the author of the original message. `extra type` may carry an ACK or RESPONSE, avoiding another packet.

When no extra payload exists, the current implementation adds dummy type `0xFF` and random bytes so that the packet hash is unique.

## `PAYLOAD_TYPE_TRACE`

Trace follows a supplied direct path and collects SNR at each hop. In the current code, a packet contains:

- trace tag;
- authentication code;
- flags, including path-identity size;
- supplied path in the payload;
- accumulated SNR values in the packet path area.

Each intermediate node verifies that its identity is next, then appends `SNR × 4`. At the end, the destination invokes a trace callback.

Trace describes the quality of specific receptions at test time. It is not a permanent link-budget measurement and does not prove that the reverse path is symmetric.

## `PAYLOAD_TYPE_MULTIPART`

The first payload byte is:

```text
upper 4 bits: remaining count
lower 4 bits: embedded payload type
```

The current common implementation explicitly handles multipart ACKs. Other embedded types are future or implementation-specific.

Multipart must not be treated as a universal fragmentation layer for arbitrary large messages. That would require:

- a sequence identifier;
- ordering;
- timeout;
- deduplication;
- maximum total size;
- retransmission policy.

The current format does not fully define these properties.

## `PAYLOAD_TYPE_CONTROL`

Control data is usually unencrypted. The first flags byte is:

```text
upper 4 bits: subtype
lower bits: subtype-specific flags
```

Published discovery subtypes are:

### `DISCOVER_REQ`

| Field | Size |
|---|---:|
| flags | 1 |
| type filter | 1 |
| tag | 4 |
| since | 4, optional |

Subtype `0x8` occupies the upper nibble. The lowest bit means `prefix_only`. A random tag associates replies with the request.

### `DISCOVER_RESP`

| Field | Size |
|---|---:|
| flags | 1 |
| SNR | 1, signed ×4 |
| tag | 4 |
| public key | 8 or 32 |

Subtype `0x9` occupies the upper nibble; the lower nibble contains node type. The response echoes the request tag.

In `Mesh.cpp`, some control packets are allowed only at zero hop: a direct control packet with a nonempty path is released without further processing. This limits discovery to the local area.

## Reserved `0x0C–0x0E`

Reserved types have no published format. Rules:

- do not use them on a shared network;
- do not depend on current drop behavior;
- do not assume future semantics;
- use `RAW_CUSTOM` or a separate test network for experiments.

## Service traffic and scaling

At high SF, an advert over 100 bytes can remain on air much longer than a short text. A flood advert is retransmitted by multiple nodes. Discovery creates one request and potentially many responses. Trace crosses every hop and returns data.

Use service mechanisms only as needed:

- infrequent flood adverts for stationary nodes;
- zero-hop discovery for local diagnostics;
- trace during troubleshooting rather than continuously;
- Multi-ACK only when justified by the loss model;
- region scope to limit propagation.

## Summary

| Type | Public | Encrypted | Typical routing |
|---|---|---|---|
| ADVERT | Yes | No, but signed | Zero-hop or flood |
| ACK | Checksum visible | ACK contains no text | Direct or flood by context |
| PATH | Wrapper visible | Yes | Returned to the author |
| TRACE | Route data visible | Authentication depends on implementation | Direct |
| MULTIPART | Subtype visible | Depends on embedded type | Commonly direct ACK |
| CONTROL | Usually yes | Usually no | Some subtypes are zero-hop only |

## Related articles

- [Adverts, Discovery, and Neighbors](/wiki/adverts-discovery-and-neighbors)
- [ACKs, Retries, and Multipart Packets](/wiki/acknowledgements-retries-and-multipart)
- [Trace and Route Diagnostics](/wiki/trace-and-route-diagnostics)
- [Airtime, Duty Cycle, and Capacity](/wiki/airtime-duty-cycle-and-capacity)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
