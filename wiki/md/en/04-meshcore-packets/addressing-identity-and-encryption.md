# Addressing, Identity, and Encryption

MeshCore uses public keys as persistent node identities. To save airtime, addressed packets carry a short hash or prefix rather than a complete key. The full key is stored with the contact and is used to calculate a shared secret and verify advert signatures.

## Sizes in the current implementation

| Object | Size |
|---|---:|
| Public key | 32 bytes |
| Internal private-key representation | 64 bytes |
| Generation seed | 32 bytes |
| Ed25519 signature | 64 bytes |
| Shared secret | 32 bytes |
| AES key | First 16 bytes of the shared secret |
| Cipher block | 16 bytes |
| Packet v1 cipher MAC | 2 bytes |
| Legacy source/destination hash | 1 byte |

A specific companion or CLI may import or export keys in a format different from the internal `LocalIdentity` representation. Do not transform a private key manually without verifying the firmware's official function.

## Identity

When creating a `LocalIdentity`, firmware obtains a random 32-byte seed and generates an Ed25519 key pair. The public key can be distributed in adverts and contact or QR exports. The private key must remain on a trusted device.

Identity determines:

- the contact;
- sender/receiver shared secrets;
- advert signatures;
- remote-administration ACLs;
- short node and path hashes;
- continuity after a device upgrade.

A node name is not an identity. Two devices may use the same name while holding different keys. Cloning a private key creates two physical instances of one identity and breaks routing and security assumptions.

## Advert signature

An advert contains:

```text
public key | timestamp | signature | appdata
```

The signed message is:

```text
public key + timestamp + appdata
```

A receiver verifies the Ed25519 signature using the full public key carried in the advert. This allows an unknown node's advert to be verified without a pre-existing shared secret and rejects modified appdata.

The signature does not hide the node name, coordinates, or type. An advert is public.

## Shared secret

Known peers use `ed25519_key_exchange` between the local private key and the remote public key. Both sides calculate the same 32-byte shared secret.

An anonymous request also includes the sender's full public key so that the destination can calculate a shared secret before creating a contact.

A cryptographic shared secret does not by itself imply social or administrative trust. An unknown sender may still need to pass a service login, password, or ACL check.

## Addressed wrapper

REQ, RESPONSE, TXT_MSG, and PATH share an outer structure:

```text
destination_hash: 1 byte
source_hash:      1 byte
cipher_mac:       2 bytes
ciphertext:       remaining bytes
```

The receiver first compares the destination hash with the short hash of its own identity. It then searches contacts that match the source hash. In the current `BaseChatMesh`, several candidates may exist; the firmware calculates a secret for each and attempts MAC verification and decryption.

A successful MAC check identifies the correct contact. This is necessary because one byte provides only 256 values, so collisions are unavoidable in a large network.

## Path hash and address hash

Both are derived from a public key, but serve different purposes:

- destination and source hashes select payload candidates;
- path hashes select the next repeater;
- path hashes may be 1–3 bytes;
- payload version v1 still specifies 1-byte source and destination hashes.

Increasing `path.hash.mode` does not automatically enlarge address hashes or the cipher MAC.

## Current encryption implementation

In `Utils.cpp`, firmware:

1. uses 16 bytes of the shared secret as an AES-128 key;
2. encrypts data in 16-byte blocks;
3. zero-pads the final partial block;
4. calculates HMAC-SHA256 over the ciphertext using the 32-byte shared secret;
5. stores the first 2 HMAC bytes before the ciphertext;
6. verifies the MAC before decrypting on receive.

The code names this sequence `encryptThenMAC` and `MACThenDecrypt`.

The current AES implementation encrypts each block directly and does not carry an IV or nonce in the wrapper. Do not describe it as GCM, CBC, or ChaCha20. An interoperable client must reproduce the published code rather than choosing a modern mode by assumption.

## Padding

Plaintext is padded with zero bytes to a 16-byte boundary. The decrypt function returns a length that is a multiple of 16. Each payload format must determine its real content length:

- text may be null-terminated or bounded by a companion-protocol frame length;
- PATH calculates the length of nested fields;
- RESPONSE length depends on the application schema.

Trailing padding bytes must not be treated as message content.

## Short MAC

Packet v1 stores only 2 bytes of HMAC, providing 65,536 possible values. This reduces overhead and is an efficient accidental-error filter, but active-forgery resistance is limited to 16 bits per attempt.

Practical consequences:

- a matching MAC must not be treated as a long-term digital signature;
- rate limiting and flood restrictions matter against packet injection;
- future payload versions may use a longer MAC;
- an application requiring stronger protection may use `RAW_CUSTOM` and its own AEAD scheme, but then it must also solve routing and compatibility.

## Group channel

A group payload has no individual source and destination hashes. Its wrapper is:

```text
channel_hash: 1 byte
cipher_mac:   2 bytes
ciphertext:   remaining bytes
```

Every channel member knows the same secret, and any of them can construct a valid group packet. Therefore, the sender name inside group text is **not authenticated as an individual identity**. The shared channel provides confidentiality from outsiders and integrity against parties without the key, but does not prove which member transmitted a message.

Signed text can add a separate identity proof where the format and client support it.

## Anonymous request

The wrapper is:

```text
destination_hash: 1 byte
sender_public_key: 32 bytes
cipher_mac: 2 bytes
ciphertext
```

The full key increases airtime, but lets the destination calculate a secret for an unknown peer. It is used for Room Server, Repeater, and Sensor login and for higher-level discovery-like requests.

## Metadata that remains visible

Even an encrypted packet reveals:

- transmission time;
- frequency and PHY parameters;
- length;
- route type;
- payload type;
- transport codes;
- path hashes and hop count;
- short source/destination hashes for some payloads;
- repeated packet-hash patterns.

An observer can perform traffic analysis without decrypting text.

## Private-key handling

- never publish the output of `get prv.key`;
- do not store exports in a publicly accessible cloud location;
- keep an encrypted backup;
- do not run two active radios with one identity;
- after compromise, create a new identity and update contacts and ACLs;
- verify that a backup exists before factory reset;
- protect a repeater private key as carefully as its administrator password.

## What each mechanism proves

| Mechanism | Proves | Does not prove |
|---|---|---|
| LoRa CRC | No detected accidental PHY error | Sender identity |
| Cipher MAC | Knowledge of the shared secret and ciphertext integrity | A specific member of a group channel |
| Advert signature | Possession of the advertised identity's private key | The real-world truth of a name or location |
| ACK checksum | Association between ACK and message | Identity outside the protected exchange context |
| Password/ACL | Application permission | Radio-route quality |

## Related articles

- [Packet Format](/wiki/packet-format)
- [User Payloads](/wiki/user-payloads)
- [Radio-Layer Threats](/wiki/security-threats)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Identity.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Utils.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/MeshCore.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
