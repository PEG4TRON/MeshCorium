# Trace and Route Diagnostics

MeshCore trace follows a supplied direct path and collects the SNR measured by each intermediate node when receiving the packet. It analyzes a specific chain; it is not equivalent to IP traceroute using TTL probes.

## Format and processing

In the current `Mesh.cpp`, `PAYLOAD_TYPE_TRACE` is used only with direct routing. The payload begins with:

```text
trace_tag: 4 bytes
auth_code: 4 bytes
flags: 1 byte
supplied path: variable
```

The lower two flag bits encode path-identity size as a power of two for matching the supplied path. During forwarding, the packet's path area accumulates `SNR × 4` values rather than node hashes.

This is a special case: `packet->path` carries measurements while the route to future hops remains inside the payload.

## Processing at a hop

An intermediate node:

1. calculates the offset of the next identity in the supplied path;
2. compares it with its own identity;
3. checks forwarding permission and the seen table;
4. appends signed SNR multiplied by four;
5. queues the packet for direct retransmission.

When the supplied path is exhausted, the destination invokes `onTraceRecv` with the accumulated measurements.

## What each hop SNR means

Every value describes reception of the previous transmission:

```text
Source --SNR1--> R1 --SNR2--> R2 --SNR3--> Destination
```

- `SNR1` was measured by R1 receiving Source;
- `SNR2` was measured by R2 receiving R1;
- `SNR3` was measured by Destination receiving R2.

The value does not describe the reverse direction.

## Quarter-decibel scaling

SNR is stored in a signed byte in quarter-decibel units:

```text
wire_value = round(SNR_dB · 4)
SNR_dB = wire_value / 4
```

Examples:

| Signed byte | SNR |
|---:|---:|
| `40` | +10 dB |
| `4` | +1 dB |
| `0` | 0 dB |
| `-20` | −5 dB |
| `-48` | −12 dB |

The byte must not be decoded as unsigned: `0xEC` is `-20`, not 236.

## Trace tag

The tag associates an event or response with a request and distinguishes concurrent traces. It is not a persistent identity.

A client should:

- choose an unpredictable or unique value;
- keep the pending request until timeout;
- reject old responses with another tag;
- never use the tag as authentication.

## Authentication code

The authentication code protects the trace workflow according to the implementation. Public packet documentation does not define it as a universal cryptographic scheme. An interoperable implementation must follow the firmware code rather than assuming CRC or password semantics.

## Difference from IP traceroute

IP traceroute:

- sends a series of packets with increasing TTL;
- each router returns ICMP Time Exceeded;
- discovers a route without knowing the full path first.

MeshCore trace:

- uses an already supplied path;
- sends one packet through listed hops;
- lets each hop append SNR;
- does not discover an unknown route;
- does not measure IP-router latency.

Unknown destinations require path discovery first.

## What trace can reveal

- a weak hop inside a long chain;
- the location where forwarding stops;
- SNR changes after replacing an antenna;
- differences between two cached paths;
- an unstable mobile repeater;
- time-of-day or interference effects;
- a path-hash mismatch.

## What trace does not reveal

- exact RSSI at every hop when only SNR is carried;
- noise floor as a separate value;
- packet-loss probability from one sample;
- reverse-direction SNR;
- queue delay at each hop;
- the cause of no response;
- hidden alternative paths;
- nodes that heard the packet but were not the next hop.

## Partial trace

If the packet does not reach the end, partial data is available only when the implementation returns or logs it. A missing trace response alone does not identify the last successful hop: loss may occur in TX, RX, policy checks, forwarding, or response delivery.

To localize a fault:

1. trace to the full destination;
2. if it fails, shorten the path to an intermediate node;
3. inspect zero-hop neighbors around the suspect segment;
4. compare counters;
5. repeat several times.

## Repeated measurement

One trace is a snapshot. For statistics:

- repeat 20–100 times;
- add jitter between probes;
- calculate median and percentiles;
- record loss and no-response events;
- compare busy and quiet periods;
- do not run continuous high-rate monitoring over the radio mesh.

Trace itself creates traffic and can alter channel conditions.

## SNR and margin

High SNR does not always mean a good route:

- a hop can have high SNR but frequent collisions;
- the receiver may be overloaded by out-of-band energy;
- the next-hop queue may be full;
- the reverse path may be broken;
- an identity collision may cause two nodes to forward.

A low but stable negative SNR can still produce good LoRa PDR. Evaluate series of traces together with packet counters.

## Comparing before and after a change

When replacing an antenna or changing TX power, keep constant:

- radio profile;
- path;
- packet length;
- time and conditions;
- orientation;
- number of samples.

If path discovery selects another route, the comparison no longer isolates the hardware change.

## Companion command

The example Companion Protocol contains `CMD_SEND_TRACE_PATH` and push event `PUSH_CODE_TRACE_DATA`. The application-to-companion frame belongs to the Companion Protocol; the radio packet remains `PAYLOAD_TYPE_TRACE`.

A client should display:

- path-entry order;
- signed quarter-decibel SNR;
- missing hops;
- timestamp;
- tag;
- firmware and path-hash mode.

## Diagnostic scenario

Problem: a direct message A → D over path `[R1,R2,R3]` receives no ACK.

1. trace A → D ten times;
2. if all traces stop after R2, inspect R2→R3;
3. query neighbors on R2 and R3;
4. check whether R3's hash changed after reflashing;
5. run a reverse trace D → A;
6. compare SNR and loss;
7. inspect region policy on R3;
8. reset the path and run new discovery;
9. compare the new path.

## Security

Trace reveals topology and quality metadata. In a hostile environment, frequent traces help an observer:

- correlate identities;
- identify backbone repeaters;
- find weak hops;
- estimate activity periods.

Restrict remote diagnostics with ACLs and avoid publishing results unnecessarily.

## Related articles

- [Direct Routing and Path Discovery](/wiki/direct-routing-and-path-discovery)
- [RSSI, SNR, and Link Quality](/wiki/rssi-snr-and-link-quality)
- [Statistics and Logging](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>
