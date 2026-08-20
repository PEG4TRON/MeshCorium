# MeshCore User Payloads

User payloads carry text, requests, responses, and application datagrams. They share the common packet container but use different wrappers and trust models.

## Private addressed message

`REQ`, `RESPONSE`, `TXT_MSG`, and `PATH` use the addressed encrypted wrapper:

| Field | Size | Meaning |
|---|---:|---|
| destination hash | 1 byte | First byte of the destination public key in v1 |
| source hash | 1 byte | First byte of the sender public key |
| cipher MAC | 2 bytes | Truncated HMAC of the ciphertext |
| ciphertext | Remaining bytes | AES-encrypted application data |

A hash only selects candidate contacts. The final match is established by successful MAC verification using the contact's secret.

## `PAYLOAD_TYPE_TXT_MSG`

Plaintext:

| Field | Size |
|---|---:|
| timestamp | 4 bytes |
| `txt_type + attempt` | 1 byte |
| message | Remaining bytes |

In the flags byte:

- upper 6 bits — `txt_type`;
- lower 2 bits — attempt `0..3`.

Documented `txt_type` values:

| Value | Meaning |
|---:|---|
| `0x00` | Plain text |
| `0x01` | CLI command |
| `0x02` | Signed plain text |

### Timestamp

The timestamp helps make messages unique, synchronize history, and calculate the ACK checksum. Incorrect clocks can cause:

- unexpected message ordering;
- conflicts in duplicate logic;
- rejection of server requests that validate time;
- incorrect synchronization.

Managed nodes provide `clock`, `clock sync`, and `time` commands.

### Attempt

The two low bits represent up to four attempts. A retry should preserve the meaning of the original message while changing what the protocol expects to distinguish another attempt or packet hash.

A client must not retry indefinitely without an ACK; doing so creates flood amplification.

### CLI command

A CLI message carries command text inside an encrypted addressed message. The remote node also applies login and ACL checks. CLI commands do not produce the same ordinary discrete ACK behavior as user text; command output is returned through response or text mechanisms defined by the implementation.

### Signed text

Signed text begins with a four-byte sender-public-key prefix followed by text and a signature or client-specific structure. The existence of this type does not guarantee identical display or verification in every client. An interoperable implementation must check the Companion Protocol and client code.

## `PAYLOAD_TYPE_REQ`

After decryption:

```text
timestamp: 4 bytes
request data: application-defined
```

Common request values in `BaseChatMesh` include:

| Value | Name | Meaning |
|---:|---|---|
| `0x01` | get stats | Request Repeater or Room Server statistics |
| `0x02` | keepalive | Maintain a logical connection |

Other requests may be defined by Sensor, Room Server, or custom firmware. Do not assume the first application byte is part of one global registry without checking the implementation.

## `PAYLOAD_TYPE_RESPONSE`

The response body is opaque application data. There is no universal envelope beyond the encrypted wrapper. Its format is chosen by the request and server role.

An implementation must know:

- which request initiated the response;
- expected length;
- field endianness;
- application-schema version;
- timeout and whether multiple responses are possible.

## `PAYLOAD_TYPE_GRP_TXT`

Wrapper:

| Field | Size |
|---|---:|
| channel hash | 1 byte |
| cipher MAC | 2 bytes |
| ciphertext | Remaining bytes |

Plaintext uses the text-message layout: timestamp, flags, and a string. Normal group text has the form:

```text
<sender name>: <message body>
```

The sender name is data that any holder of the channel secret can create. A group channel does not authenticate the individual author.

### Channel hash

Channel hash is the first byte of SHA-256 over the shared key. If hashes collide, the client tries known channels with the same hash and validates their MACs. Like an address hash, it is an index, not a cryptographically unique identifier.

## `PAYLOAD_TYPE_GRP_DATA`

The wrapper is the same, while plaintext is:

| Field | Size |
|---|---:|
| data type | 2 bytes |
| data length | 1 byte |
| data | Specified length |

`data type` allocates an application namespace. The official `number_allocations.md` lists ranges such as:

| Range | Purpose |
|---|---|
| `0000–00FF` | Internal/reserved |
| `0100` | MeshCore Open |
| `0110–011F` | Ripple |
| `FF00–FFFF` | Development/POC |

Use the development range while building a project. A published project should request a permanent allocation to avoid collisions with other applications.

### Checking `data length`

The receiver must check:

```text
data_len <= available_plaintext
```

AES padding may add trailing zeroes. Reading “to the end of the decrypted buffer” without using `data_len` produces false data.

## `PAYLOAD_TYPE_ANON_REQ`

Its wrapper differs:

| Field | Size |
|---|---:|
| destination hash | 1 byte |
| sender public key | 32 bytes |
| cipher MAC | 2 bytes |
| ciphertext | Remaining bytes |

Typical plaintext forms include:

### Room Server login

```text
timestamp: 4
sync timestamp: 4
password: remaining
```

The sync timestamp tells the server from what point the client wants messages.

### Repeater/Sensor login

```text
timestamp: 4
password: remaining
```

### Repeater metadata requests

Published subtypes exist for regions, owner information, and clock/status. They contain a timestamp, request subtype, reply-path length, and reply path.

Anonymous means “the sender is not yet established in contact context,” not “no public key exists.” The full key is visible in wrapper metadata.

## `PAYLOAD_TYPE_RAW_CUSTOM`

This payload has no standard internal format. The application defines:

- addressing;
- encryption;
- integrity;
- versioning;
- fragmentation;
- acknowledgment;
- replay protection.

The current `Mesh.cpp` processes raw custom data as direct and does not flood-forward it by default. Custom firmware may change this, but then network compatibility must be considered explicitly.

## Sizes and padding

AES operates in 16-byte blocks. Even a short plaintext creates at least one cipher block, plus the 2-byte MAC and wrapper. Plan in bytes, not characters.

Example for a 17-byte private plaintext:

- padded to 32 bytes of ciphertext;
- 2-byte MAC;
- 2 bytes of source and destination hashes;
- 36-byte MeshCore payload total;
- plus packet header, path, and optional transport codes.

## Choosing a type

| Task | Payload |
|---|---|
| Message to a known contact | `TXT_MSG` |
| Command or structured-data request | `REQ/RESPONSE` |
| Message to all members of a shared channel | `GRP_TXT` |
| Binary telemetry on a shared channel | `GRP_DATA` |
| First login from an unknown peer | `ANON_REQ` |
| Completely custom protocol | `RAW_CUSTOM` |

Do not encode binary data as Base64 text without a reason: it expands payload by roughly one third and increases airtime.

## Related articles

- [Addressing, Identity, and Encryption](/wiki/addressing-identity-and-encryption)
- [Service Payloads](/wiki/service-payloads)
- [ACKs, Retries, and Multipart Packets](/wiki/acknowledgements-retries-and-multipart)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/number_allocations.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
