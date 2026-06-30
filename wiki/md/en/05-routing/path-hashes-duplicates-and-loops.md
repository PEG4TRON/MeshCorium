# Path Hashes, Duplicates, and Loops

To save airtime, MeshCore stores a short prefix or hash in a path rather than a complete 32-byte public key. Shorter entries allow more hops in one packet, but increase the probability that two identities share the same value.

![Path-hash sizes](/attachments/en/path-hash.svg?v=2)

## Size encoding

In `path_length`:

- bits 0–5 — count;
- bits 6–7 — `hash_size - 1`.

| Mode | Entry | Possible values | Maximum in a 64-byte path |
|---:|---:|---:|---:|
| 0 | 1 byte | 256 | 64 entries |
| 1 | 2 bytes | 65,536 | 32 entries |
| 2 | 3 bytes | 16,777,216 | 21 entries |
| 3 | 4 bytes | Reserved | Unsupported |

The Repeater CLI setting `path.hash.mode` controls the hash size used in **that repeater's own adverts**. According to the documentation, firmware ≥1.14 should forward packets of every supported size regardless of local mode.

## Hash collisions

A collision occurs when two public keys have the same short prefix. Probability grows quickly because of the birthday effect.

For a uniform distribution, the approximate probability of at least one collision is:

```text
P ≈ 1 - exp(-n(n-1)/(2N))
```

where `N` is the number of possible hash values.

Reference values:

| Nodes | Size | Probability of at least one collision |
|---:|---:|---:|
| 20 | 1 byte | about 52% |
| 50 | 1 byte | about 99% |
| 100 | 2 bytes | about 7% |
| 500 | 2 bytes | about 85% |
| 1,000 | 3 bytes | about 3% |

This is the probability of a collision somewhere in the set, not the probability that a particular path fails. It nevertheless explains why 1-byte mode scales poorly as a network-wide unique identifier.

## What a path collision does

The first entry in a direct packet may match two neighboring nodes. Both may believe they are the next hop and forward it. Consequences include:

- branching of a direct route;
- unnecessary duplicates;
- different remaining paths;
- TX collisions;
- unexpected loops;
- increased duplicate counters.

The seen table may suppress some copies, but cannot guarantee correct selection, especially when the branches cannot hear each other.

Destination and source hash collisions are resolved by trying MAC verification and decryption against several contacts. A path has no cryptographic next-hop verification, so a larger hash reduces ambiguity.

## Packet hash and path hash are different

A **path hash** identifies a node within a route.

A **packet hash** identifies a packet for duplicate suppression. It is calculated from packet type and payload according to the implementation and stored in the seen table.

Do not use a path hash as a message ID or a packet hash as a node identity.

## Seen table

When a packet is first processed, its hash is recorded. Later copies are discarded. A seen table needs:

- finite capacity;
- an eviction policy;
- lifetime or cyclic replacement;
- protection against garbage traffic filling it.

If the table is too small for the traffic rate, an old entry may be evicted before a late copy arrives, allowing it to be forwarded again.

## First packet wins

Duplicate suppression makes the first copy the winner. This saves airtime but hides alternatives. For diagnostics, raw RX logs before suppression or explicit path and trace data are useful.

## Routing loops

A loop means a packet crosses the same repeater again. In a valid flood path, the node's own hash is already present, but legacy 1-byte collisions make a simple check ambiguous. MeshCore therefore provides `loop.detect` levels.

### `off`

No check for an existing own hash. The duplicate cache and maximum hop count are the only protection.

### `minimal`

Drop if the node's own hash is already present:

- 4 times for 1-byte entries;
- 2 times for 2-byte entries;
- 1 time for 3-byte entries.

This mode tolerates accidental short-hash collisions.

### `moderate`

Thresholds are:

- 2 for 1-byte;
- 1 for 2-byte;
- 1 for 3-byte.

### `strict`

Drop on the first match for every size.

Strict mode stops loops sooner, but in a 1-byte network it can mistake another node's colliding hash for its own and truncate a legitimate flood.

## Packet storms

A normal loop should stop at the seen table because the packet hash is already known. A storm becomes dangerous if each forwarding step changes the packet so that it receives another hash.

Possible causes include:

- custom firmware modifying payload or path incorrectly;
- a bridge repackaging data;
- a timestamp updated at every hop;
- unstable padding bytes;
- memory corruption;
- incompatible packet formats.

The packet may then continue until `flood.max` or path capacity is reached, producing dozens of transmissions.

## Choosing a hash mode

### 1 byte

Advantages:

- legacy compatibility;
- minimum overhead;
- up to 64 path entries.

Disadvantages:

- frequent collisions in large networks;
- false positives with strict loop detection;
- harder topology analysis.

### 2 bytes

A practical compromise for medium networks. A 32-hop storage limit is usually sufficient and collision probability is substantially lower.

### 3 bytes

Useful for large identity spaces, but limits a path to 21 entries and adds airtime to every packet. Very long routes are already poor for capacity, so this storage limit is rarely the primary problem.

## Compatibility

According to the CLI documentation:

- the feature appeared around firmware 1.13/1.14;
- v1.13 and older may drop multibyte paths;
- firmware ≥1.14 should forward all supported sizes;
- change modes only after enough repeaters have been upgraded.

In a mixed network, sources and adverts may remain on 1 byte temporarily even when the backbone already forwards 2- and 3-byte entries.

## Diagnosing a collision

Signs include:

- two nodes forward one direct packet;
- path details show identical prefixes;
- strict loop detection drops a packet where no real loop exists;
- removing one repeater suddenly repairs the route;
- switching to 2-byte mode solves the problem.

Confirmation requires complete public keys of neighboring nodes, not only prefixes.

## Security implications

A short path hash is not an authentication mechanism. An attacker may search for an identity with a desired prefix and attempt to become the next hop. Payload encryption hides text, but a malicious forwarder can:

- drop packets;
- delay them;
- replay them;
- analyze metadata;
- destabilize routes.

A larger path hash raises the cost of prefix matching, but does not replace cryptographic routing authentication.

## Practical policy

1. update all critical repeaters to a version with multibyte forwarding;
2. count unique identities;
3. measure maximum real route length;
4. enable 2-byte adverts on a limited group;
5. verify flood propagation and direct paths;
6. enable `loop.detect moderate` or `strict` where collision risk is acceptable;
7. monitor duplicates and drops;
8. move to 3 bytes only with a clear reason.

## Related articles

- [Packet Format](/wiki/packet-format)
- [Flood Routing](/wiki/flood-routing)
- [Compatibility and Migration](/wiki/compatibility-and-migration)
- [Radio-Layer Threats](/wiki/security-threats)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
