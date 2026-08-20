# ACKs, Retries, and Multipart Packets

MeshCore reliability is built over an unreliable radio medium. LoRa CRC detects a damaged frame, but it does not tell the sender that delivery occurred. For end-to-end confirmation, the destination creates an ACK that must travel over a separate reverse route.

![Message and ACK flow](/attachments/en/ack-flow.svg?v=2)

## Levels of success

Distinguish these events:

1. a packet was created and queued;
2. the radio started TX;
3. the radio reported `TX_DONE`;
4. at least one neighbor received the packet;
5. repeaters forwarded it;
6. the destination decrypted the payload;
7. the application processed the message;
8. an ACK was created;
9. the ACK returned to the sender.

`TX_DONE` proves only event 3. A user interface should not display “delivered” before an end-to-end ACK when the protocol expects one.

## ACK format

`PAYLOAD_TYPE_ACK` payload:

```text
checksum: uint32 little-endian
```

The checksum is calculated from the timestamp, message text, and sender public key. It allows the sender to match the ACK to the original message.

An ACK does not repeat the ciphertext, saving airtime. A 32-bit checksum is not a digital signature; trust comes from the protected exchange and route context.

## Discrete and bundled ACKs

### Discrete ACK

A separate ACK packet travels over the reverse path.

Advantages:

- simple;
- can be sent after processing;
- separately measurable.

Disadvantages:

- another packet;
- another preamble and header overhead;
- another chance of collision.

### Bundled ACK

A returned path has `extra type` and `extra` fields. An ACK can be embedded in PATH, which the destination already needs to return after flood discovery.

This saves one transmission sequence, especially for the first message sent without a known path.

According to the documentation, CLI commands do not trigger either a discrete or bundled generic ACK. Command output is an application response.

## Retry and attempt

Text flags store an attempt number in two bits, `0..3`. A client can mark up to four attempts within the current format.

A retry is needed when no ACK arrives, but the cause is ambiguous:

- the data packet was lost;
- the destination received it but the ACK was lost;
- the direct path is stale;
- the ACK was delayed in a queue;
- duty budget was exhausted;
- the UI timeout is too short;
- the destination processed the message slowly.

Retries must therefore be **idempotent** at the application layer. A duplicate text can be hidden using checksum and timestamp. Repeating a command such as “open valve” without an operation ID can be dangerous.

## Timeout

A timeout must account for:

```text
data airtime × hops
+ retransmit delays
+ queue delays
+ destination processing
+ ACK airtime × reverse hops
+ duty-cycle wait
```

A fixed two-second timeout is unsuitable for an SF11 packet crossing ten hops. Too short causes unnecessary retries; too long makes the interface unresponsive.

The Companion example uses a base timeout and per-hop factors. An interoperable client should use path length and radio settings rather than one constant for every network.

## ACK over a direct path

On the reverse route, each repeater may:

- notify local logic that an ACK was observed;
- check the seen table;
- remove its path entry;
- queue the ACK at high priority.

If one hop disappears, the ACK cannot return even if the data packet was delivered. The sender then retries. The destination must suppress duplicate application delivery.

## Early received ACK

The code checks an ACK even when a direct packet still has a nonempty path before forwarding it. This allows an intermediate node to update local state or statistics, then continue the route.

An intermediate observation is not confirmation to the sender; the ACK still has to cross the remaining path.

## Multi-ACK

CLI:

```text
get multi.acks
set multi.acks 0|1
```

Default is `0`. When enabled, an implementation may transmit additional ACK copies.

`createMultiAck` creates `PAYLOAD_TYPE_MULTIPART`:

```text
byte 0:
  upper nibble = remaining ACK count
  lower nibble = PAYLOAD_TYPE_ACK
bytes 1..:
  ACK payload
```

Copies are separated in time. The objective is to increase the probability that at least one ACK crosses a poor reverse path.

The cost is:

- more airtime;
- more congestion;
- duplicate ACKs in queues;
- worse performance for other traffic in a dense network.

Multi-ACK does not repair a broken path: every copy follows the same chain.

## Multipart is not general fragmentation

The current common code processes multipart ACKs. A remaining-count field alone is insufficient for generic large-payload reassembly:

- no global sequence ID;
- no offset;
- no total length;
- no standard selective repeat;
- no common reassembly schema.

A custom application must not split arbitrary data while assuming that every MeshCore client will reassemble it automatically.

## Duplicate suppression at the destination

The destination should remember a message checksum and timestamp for at least the retry window. Otherwise, a lost ACK causes the message to appear twice.

Commands and transactions should include an application operation ID in the encrypted body:

```text
operation_id | command | parameters
```

The server stores completed IDs and returns the same result without repeating the side effect.

## ACKs and group messages

Group text has many receivers. A generic ACK from every member would create ACK implosion. Group delivery is therefore usually best-effort or uses a constrained application-specific mechanism.

“Sent to channel” does not mean every member received it. Use an addressed request/response for critical commands to specific nodes.

## ACKs and Room Server operations

Room and remote commands may be confirmed by an application response rather than a generic ACK. Separate:

- radio delivery;
- server acceptance of a request;
- server commit of a message;
- client synchronization of the result.

A generic ACK confirms a packet, not necessarily successful execution of an operation.

## Example retry policy

```text
attempt 0: direct over cached path
attempt 1: direct after short jitter
attempt 2: reset stale path and run flood discovery
attempt 3: retry over the new path
```

Not every system needs all four attempts. A Sensor may stop after one; an emergency client may use a more resilient policy.

Backoff should include randomness so that two nodes do not repeat the same collision in lockstep.

## Diagnosing a missing ACK

1. verify in destination logs that the data arrived;
2. verify that an ACK was created;
3. inspect the reverse path;
4. compare direct send/receive counters at each hop;
5. inspect duty budget and queue;
6. check for path-hash collision;
7. trace both directions;
8. increase the application timeout;
9. enable Multi-ACK temporarily for comparison;
10. do not leave it enabled without airtime analysis.

## Related articles

- [Direct Routing and Path Discovery](/wiki/direct-routing-and-path-discovery)
- [Airtime, Duty Cycle, and Capacity](/wiki/airtime-duty-cycle-and-capacity)
- [Trace and Route Diagnostics](/wiki/trace-and-route-diagnostics)
- [User Payloads](/wiki/user-payloads)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
