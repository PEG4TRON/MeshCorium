# MeshCore Packet Format

The currently published Packet Format v1 defines one container for routing and multiple payload types. The radio chip treats the entire container as the LoRa payload.

![MeshCore packet format](/attachments/en/meshcore-packet.svg?v=2)

## Overall structure

```text
[header][transport_codes optional][path_length][path][payload]
```

| Field | Size | Purpose |
|---|---:|---|
| `header` | 1 byte | Route type, payload type, payload version |
| `transport_codes` | 4 bytes, optional | Two `uint16_t` values for transport routes |
| `path_length` | 1 byte | Encodes path-hash count and size |
| `path` | 0–64 bytes | Sequence of intermediate identifiers |
| `payload` | 0–184 bytes | Data whose format depends on payload type |

Current implementation constants:

```text
MAX_PACKET_PAYLOAD = 184
MAX_PATH_SIZE      = 64
MAX_TRANS_UNIT     = 255
```

The complete length must fit in `MAX_TRANS_UNIT`. A 64-byte path and a 184-byte payload cannot both be filled to their individual maxima when transport codes and other fields are present, because the total would exceed 255 bytes.

## Header `VVPPPPRR`

Bits are numbered from the least significant bit:

```text
bit 7                           bit 0
+----+----+----+----+----+----+----+----+
| V  | V  | P  | P  | P  | P  | R  | R  |
+----+----+----+----+----+----+----+----+
```

- `RR`, bits 0–1 — route type;
- `PPPP`, bits 2–5 — payload type;
- `VV`, bits 6–7 — payload version.

Masks in `Packet.h`:

```text
PH_ROUTE_MASK = 0x03
PH_TYPE_MASK  = 0x0F
PH_VER_MASK   = 0x03
```

## Route type

| Value | Constant | Meaning |
|---:|---|---|
| `0x00` | `ROUTE_TYPE_TRANSPORT_FLOOD` | Flood with transport codes |
| `0x01` | `ROUTE_TYPE_FLOOD` | Normal flood |
| `0x02` | `ROUTE_TYPE_DIRECT` | Direct path |
| `0x03` | `ROUTE_TYPE_TRANSPORT_DIRECT` | Direct with transport codes |

A transport route adds four bytes immediately after the header. The parser decides whether those bytes exist solely from the route bits. An incorrect route type shifts the boundary of every following field.

## Payload type

| Value | Constant | Purpose |
|---:|---|---|
| `0x0` | `PAYLOAD_TYPE_REQ` | Addressed request |
| `0x1` | `PAYLOAD_TYPE_RESPONSE` | Response |
| `0x2` | `PAYLOAD_TYPE_TXT_MSG` | Private text message |
| `0x3` | `PAYLOAD_TYPE_ACK` | Acknowledgment |
| `0x4` | `PAYLOAD_TYPE_ADVERT` | Identity advertisement |
| `0x5` | `PAYLOAD_TYPE_GRP_TXT` | Group text |
| `0x6` | `PAYLOAD_TYPE_GRP_DATA` | Group datagram |
| `0x7` | `PAYLOAD_TYPE_ANON_REQ` | Request from an unknown sender |
| `0x8` | `PAYLOAD_TYPE_PATH` | Returned path |
| `0x9` | `PAYLOAD_TYPE_TRACE` | Trace with per-hop SNR |
| `0xA` | `PAYLOAD_TYPE_MULTIPART` | Element of a sequence |
| `0xB` | `PAYLOAD_TYPE_CONTROL` | Control and discovery |
| `0xC–0xE` | reserved | Do not use as implemented functions |
| `0xF` | `PAYLOAD_TYPE_RAW_CUSTOM` | Application-defined content |

Payload type tells the receiver how to interpret the remaining bytes. It does not define routing: the same payload type may be flooded or sent direct where the implementation permits.

## Payload version

| `VV` bits | Version | Status |
|---:|---:|---|
| `00` | 1 | Current published version |
| `01` | 2 | Reserved for future use |
| `10` | 3 | Reserved |
| `11` | 4 | Reserved |

The current `Dispatcher::tryParsePacket` rejects any version above `PAYLOAD_VER_1`. A v2 value cannot be used for experimentation while expecting existing repeaters to forward it transparently.

## Transport codes

The field contains:

```text
transport_code_1: uint16 little-endian
transport_code_2: uint16 little-endian
```

The first code is derived from the region scope. The second is reserved. A zero or unknown value must not automatically be interpreted as global access; each node's region policy decides what to do.

See [Regions and Transport Codes](/wiki/regions-and-transport-codes).

## Encoding `path_length`

This field is not a byte count. It combines two values:

```text
bits 0..5: hash count, 0..63
bits 6..7: hash size - 1
```

| Upper bits | Size of one entry |
|---:|---:|
| `00` | 1 byte |
| `01` | 2 bytes |
| `10` | 3 bytes |
| `11` | Reserved/invalid |

Actual path length is:

```text
path_bytes = hash_count · hash_size
```

Examples:

| `path_length` | Decoding | Path bytes |
|---:|---|---:|
| `0x00` | 0 entries of 1 byte | 0 |
| `0x05` | 5 entries of 1 byte | 5 |
| `0x45` | 5 entries of 2 bytes | 10 |
| `0x8A` | 10 entries of 3 bytes | 30 |

The encoded maximum `hash_count=63` does not mean 63 entries always fit. With 2-byte hashes, `MAX_PATH_SIZE` permits at most 32 entries; with 3-byte hashes, at most 21.

## Path behavior in flood and direct routing

During flood routing, every forwarding node appends its own hash. The path grows outward from the source.

During direct routing, the path is supplied by the sender. The next repeater compares the first entry with its own identity, removes that entry, and forwards the remainder.

The same field is used in two different ways, so route type is essential for interpretation.

## Payload

The payload is the rest of the byte array after the path. There is no separate payload-length field; its size is calculated from the total LoRa-payload length and the fields already parsed.

Consequences:

- a corrupt `path_length` changes the payload boundary;
- the parser must check for buffer overrun;
- an unknown payload type must not be interpreted as text;
- encrypted payload may include padding to an AES block boundary.

## Little-endian integers

The public documentation states that 16-bit and 32-bit integer fields inside payloads use little-endian byte order. Transport codes are also copied as `uint16_t` values in the current code. An implementation on another architecture should serialize explicitly rather than copying a native structure without checking byte order.

## Incoming-packet validation

The current parser performs at least the following:

1. read the header;
2. reject an unsupported payload version;
3. read four bytes of codes for a transport route;
4. read `path_length`;
5. reject path mode `3`;
6. calculate `path_byte_len`;
7. check `MAX_PATH_SIZE` and available raw bytes;
8. treat the remaining bytes as payload;
9. reject a payload larger than 184 bytes.

Payload-specific code must then check its own minimum lengths. An addressed wrapper, for example, must contain a destination hash, source hash, and MAC.

## Packet hash and duplicates

`Packet::calculatePacketHash` creates an identifier for the seen table. Exact input matters for duplicate suppression: changing route metadata or payload may produce another hash and permit retransmission.

Packet hash is not path hash:

- packet hash identifies a specific transmission or content instance;
- path hash is a short node identifier inside a route.

## Special internal value `header = 0xFF`

Inside a `Packet` object, `0xFF` is used as a “do not retransmit” marker after local processing. It is an internal state and must not be interpreted as a separate wire-format packet type.

## Manual decoding example

Suppose a raw packet begins:

```text
09 03 A1 B2 C3 ...
```

`0x09 = 00001001b`:

- route bits `01` → flood;
- payload bits `0010` → TXT_MSG;
- version bits `00` → v1.

The next byte, `0x03`, means three 1-byte path hashes. `A1 B2 C3` are the path. The remaining bytes contain the addressed wrapper and encrypted text payload.

A real analyzer must account for transport routes, where four bytes of codes come immediately after the header.

## Compatibility

Firmware v1.12 and older handled legacy 1-byte path hashes and may drop multibyte paths. In a mixed-version network, update the forwarding backbone before enabling new hash modes on advert or message sources.

Reserved versions and payload types must not be used for local experiments on a shared network. Older repeaters may drop them, and future firmware may assign them a different meaning.

## Related articles

- [User Payloads](/wiki/user-payloads)
- [Service Payloads](/wiki/service-payloads)
- [Path Hashes, Duplicates, and Loops](/wiki/path-hashes-duplicates-and-loops)
- [Compatibility and Migration](/wiki/compatibility-and-migration)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/MeshCore.h>
