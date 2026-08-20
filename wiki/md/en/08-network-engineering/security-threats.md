# Radio-Layer Threats in MeshCore

MeshCore security is composed of several mechanisms: Ed25519 identities and signatures, shared secrets, AES-128 encryption, a truncated HMAC, passwords and ACLs, and routing policy. They protect different properties. The radio channel remains observable and can always be blocked or filled with arbitrary signals.

## Threat model

Relevant adversaries include:

1. a passive listener using a LoRa receiver or SDR;
2. a legitimate participant in a public or group channel;
3. the operator of a malicious repeater;
4. an attacker with physical access to a node;
5. a transmitter creating interference or jamming;
6. a compromised bridge or client;
7. accidentally faulty custom firmware.

## What is protected

### Advert signature

The signature allows a receiver to verify that advert application data was signed by the private key belonging to the advertised identity. It protects against in-transit modification of the name or coordinates and against simple impersonation of another public key.

It does not prove the real-world identity of a person and does not hide advert data.

### Peer encryption

A shared secret derived between identities is used for AES-128 encryption and an HMAC over the ciphertext. It protects message contents from nodes that do not know the secret.

### Group secret

A channel secret excludes outsiders, but every member who knows the shared key can create a valid group packet and can place any display name inside it. There is no individual non-repudiation unless the application adds a separate signature.

### ACL and password controls

ACLs and passwords limit remote administration or application login. They do not protect radio availability.

## Passive observation

An observer can collect:

- frequency, bandwidth, spreading factor, and coding rate;
- transmission time and duration;
- route type and payload type;
- path-hash size and count;
- transport codes;
- short source and destination hashes;
- public adverts and locations;
- ciphertext length;
- ACK and response patterns.

Even without reading the text, an observer may infer active nodes, backbone structure, operating hours, and social relationships.

### Reducing metadata leakage

The current protocol cannot hide metadata completely. You can reduce exposure by:

- not publishing coordinates unless needed;
- using neutral node names;
- limiting flood scope;
- avoiding unnecessary adverts;
- avoiding continuous trace activity;
- avoiding predictable high-value traffic patterns;
- protecting logs.

Traffic padding would consume additional airtime and is not part of the standard protocol policy.

## Replay

If an attacker records and retransmits a packet, the seen table may suppress it while its packet hash remains cached. After cache expiry or a reboot, the same packet may be processed again.

A timestamp narrows the replay window only if clocks are correct and the application validates freshness. Critical commands should include:

- an operation identifier;
- a monotonic counter or nonce;
- a freshness window;
- idempotent execution;
- persistent storage of recently accepted identifiers.

The generic text protocol is not a transaction system.

## Packet injection

Packet-format version 1 uses a two-byte cipher MAC: a 16-bit truncated HMAC. For a particular secret context, a random forgery has an approximate success probability of 1 in 65,536 per attempt. Flooding permits many attempts, making rate limits and scope controls important.

This does not mean an attacker immediately decrypts data. High-rate forgery still creates denial of service and gives a non-zero chance of an accepted MAC.

A high-security custom application may use `RAW_CUSTOM` with a modern AEAD construction, a longer authentication tag, and a replay counter. Interoperability and application-level routing then become the developer's responsibility.

## Key compromise

### Node private key

An attacker holding a node's private key can:

- sign adverts;
- derive peer shared secrets as that node;
- satisfy ACL checks tied to that key;
- decrypt captured or stored traffic to the extent permitted by the protocol and keys.

Recovery procedure:

1. Create a new identity.
2. Remove the old contact and ACL entries.
3. Distribute the new public key through an out-of-band trusted method.
4. Rotate group secrets.
5. Update server permissions.
6. Treat the old identity as revoked.

The MeshCore radio protocol does not publish a global certificate revocation list.

### Channel secret

Any holder can read future channel traffic and create valid group packets. Create a new channel secret and distribute it securely to the remaining participants.

## Malicious repeater

A repeater sees metadata and controls forwarding. It can:

- selectively drop packets;
- delay packets;
- replay traffic;
- attract routes through fast adverts or retransmission;
- alter unprotected routing fields;
- create duplicate branches;
- record topology;
- violate duty-cycle limits.

End-to-end encryption hides payload contents but does not guarantee delivery. Mesh routing does not require repeaters to be trusted for confidentiality, but it necessarily depends on them for availability.

### Route attraction

A well-positioned or fast malicious repeater can retransmit a flood first, become part of the returned path, and then drop direct packets. The first-packet-wins behaviour makes this possible.

Mitigations include:

- comparing alternative paths;
- manually controlling paths for critical links;
- monitoring ACK and PDR by route or hop;
- blacklisting a suspicious node at the application level;
- maintaining redundant routes.

## Hash-collision attack

An attacker can generate key pairs until a short path prefix collides with another node. For one-byte hashes, this is inexpensive and may allow the attacker to appear as a false next hop.

Two- and three-byte path hashes raise the cost, but do not make routing cryptographically authenticated. A critical network should use longer hashes and maintain an inventory of known backbone identities.

## Forged and misleading adverts

Without the private key, an attacker cannot modify a signed advert belonging to another identity. The attacker can still:

- replay an old valid advert;
- create a new identity with a similar name;
- copy a display name;
- publish false coordinates under the attacker's own identity.

User interfaces should display a key fingerprint rather than trusting only a name.

## Jamming and denial of service

Any sufficiently strong transmitter can block an unlicensed channel. Encryption does not prevent this.

Possible attacks include:

- continuous noise;
- a flood of LoRa packets;
- reactive jamming;
- a valid MeshCore flood storm;
- malformed traffic that consumes parser or queue resources;
- advert or contact-table exhaustion.

Defences are limited but include:

- frequency agility or a planned manual migration;
- directional antennas;
- filtering;
- region and flood limits;
- rate limiting;
- validating packet structure before expensive cryptography;
- watchdog and recovery mechanisms;
- a backup out-of-band channel.

Do not respond merely by increasing transmit power without checking both regulation and the risk of escalation.

## Malformed packets

The parser validates version, path mode, and lengths. Each payload handler must also validate every offset before reading it.

Custom clients should:

- check minimum lengths;
- guard against integer overflow;
- decode signed fields correctly;
- limit memory allocation;
- distrust `data_len` until bounds have been checked;
- fuzz-test parsers;
- reject reserved values.

## Bridge loops

A bridge between radio channels or between radio and IP can transform a packet into a new packet, bypass the normal seen table, and create a storm.

A safe bridge needs:

- a globally stable message identifier;
- an ingress-interface tag;
- a no-return rule;
- a TTL or hop budget;
- rate limits;
- deduplication storage;
- an explicit payload allowlist;
- monitoring.

## Physical access

A device may expose:

- its private key;
- channel secrets;
- contacts;
- messages;
- the administrative password;
- logs.

Mitigations include:

- a locked enclosure;
- disabling unauthenticated debug interfaces;
- encrypted backups;
- secure boot and flash encryption where the platform supports them;
- erasing a device before transfer;
- tamper-evident seals;
- restricted serial access.

Not every MeshCore board has hardware-backed security. Physical compromise often means key compromise.

## Remote administration

The default administrative password `password` must be changed. In the current implementation, use of a password may add a node to the administrative ACL. Risks include:

- brute-force attempts over radio;
- password reuse;
- metadata interception;
- accidental disclosure because the documented CLI response echoes a newly set password.

Use a long, unique password, restrict administrative paths, and audit the ACL.

## Availability matters separately from secrecy

In a disaster-response network, encrypted text does not guarantee that the network remains operational. Also provide:

- multiple backbone paths;
- backup power;
- known-good firmware;
- flood-storm controls;
- monitoring;
- a documented fallback frequency or profile;
- a recovery procedure.

## Security checklist

- [ ] The default administrative password has been changed.
- [ ] Private keys are backed up and protected.
- [ ] Group secrets are unique.
- [ ] Coordinates are published deliberately.
- [ ] Firmware source and version are known.
- [ ] Loop detection and flood limits are configured.
- [ ] Multibyte path hashes are used when scale requires them.
- [ ] Remote commands are idempotent.
- [ ] Logs have a retention policy.
- [ ] Bridges are protected against loops.
- [ ] A key-rotation plan exists.
- [ ] An out-of-band recovery method exists.

## Related articles

- [Addressing and encryption](/wiki/addressing-identity-and-encryption)
- [Path hashes and loops](/wiki/path-hashes-duplicates-and-loops)
- [Compatibility](/wiki/compatibility-and-migration)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Identity.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Utils.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
