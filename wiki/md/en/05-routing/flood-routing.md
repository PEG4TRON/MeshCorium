# Flood Routing

Flood routing delivers a packet without a pre-known path. Every eligible repeater that sees the packet for the first time may append its identifier to the path and schedule a delayed retransmission. The mechanism is simple and tolerant of unknown topology, but it creates more transmissions than direct routing.

![Flood and Direct](/attachments/en/flood-vs-direct.svg?v=2)

## Route types

Flood routing is represented by two values:

- `ROUTE_TYPE_FLOOD` — normal flood;
- `ROUTE_TYPE_TRANSPORT_FLOOD` — flood with transport codes for region scope.

In both cases the path is built as the packet propagates. The transport form adds four bytes of transport codes and region filtering.

## Packet progression

A simplified repeater algorithm is:

1. receive and parse the LoRa payload;
2. validate packet version and sizes;
3. apply transport and region filtering;
4. perform payload-specific validation;
5. check the seen table;
6. process locally when applicable;
7. check `allowPacketForward` and flood limits;
8. ensure another path entry fits;
9. append the node's path hash;
10. calculate retransmit delay;
11. queue the packet for transmission.

In `Mesh::routeRecvPacket`, retransmission priority depends on the current path-entry count: packets from nearer sources receive higher priority than packets already far from their origin.

## Why randomized delay is used

If three repeaters hear one packet and all transmit immediately, their copies collide. Each therefore chooses a delay within a randomized window.

While waiting, a repeater may hear the same packet forwarded by another node. The seen table then shows that the packet is already propagating, allowing the redundant transmission to be suppressed or rendered unnecessary.

CLI parameter:

```text
get txdelay
set txdelay <0..2>
```

The documented default is `0.5`. A higher value widens the window:

- lower probability of simultaneous TX;
- higher end-to-end latency;
- greater chance that direct or ACK traffic overtakes flood traffic in the queue;
- a weak or busy node may miss an application timeout.

`txdelay=0` removes the window and is suitable only for controlled tests with very few nodes.

## First packet wins

When the same packet arrives over several routes, the current implementation processes the first valid copy. Later copies are duplicates.

This is fast and simple, but not necessarily optimal:

- the first route may have more hops;
- a strong short route may lose because of random delay;
- the route may include a mobile repeater;
- queue load can distort arrival order;
- the best route in one direction may not be best in reverse.

The returned path represents the copy that won, not a globally calculated shortest path.

## Path accumulation

Before forwarding, a repeater appends a hash of its identity. Entry size is determined by the packet's encoded path mode: 1, 2, or 3 bytes.

The path serves several purposes:

- records the actual flood chain;
- allows the destination to return a reciprocal route;
- limits packet length;
- supports loop detection;
- provides hop count for diagnostics.

If `(count + 1) × hash_size > MAX_PATH_SIZE`, forwarding stops regardless of `flood.max`.

## Hop-count limits

CLI:

```text
get flood.max
set flood.max <0..64>
```

The documented default is `64`. This is the forwarding limit for ordinary flood traffic, but the path may fill earlier because storage is limited to 64 bytes.

Separate limits exist for:

```text
flood.max.unscoped
flood.max.advert
```

- `flood.max.unscoped` limits packets without region scope;
- `flood.max.advert` limits adverts, with documented default `8`.

The meaning of `0` should be verified in the code for the specific firmware version; it may mean no propagation rather than unlimited propagation.

## Unscoped flood

A packet without transport codes follows ordinary flood rules. In a large network, this allows an old or foreign client to flood through every region.

Instead of fully applying `region denyf *`, a small `flood.max.unscoped` can preserve local legacy communication while preventing network-wide propagation.

## Flood adverts

An advert is relatively large: it contains a 32-byte public key, 64-byte signature, timestamp, and appdata. Flooding it is more expensive than sending a short ACK.

Relevant settings are:

```text
flood.advert.interval <3..168 hours>
advert.interval <60..240 minutes>  # zero-hop when enabled
flood.max.advert <0..64>
```

The documented flood-advert interval default is 12 hours for a Repeater and 0 for a Sensor, although role-specific builds may differ.

Frequent adverts in a dense mesh consume airtime and seen-table capacity. A stationary repeater's interval should be chosen according to discovery needs, not a desire to continuously “ping” the network.

## Duplicate suppression

The seen table stores hashes of packets already processed. Another copy from a different neighbor is discarded. This is the primary mechanism that stops ordinary flood propagation.

It is not absolute:

- a changed payload creates another packet hash;
- short retention may allow a late copy after expiry;
- a hash collision may suppress a different packet;
- a reboot clears volatile state;
- incompatible custom firmware may rebuild a packet differently.

Hop limits, path size, and loop detection provide additional safeguards.

## `rxdelay`: favoring a strong copy

Experimental setting:

```text
get rxdelay
set rxdelay <0..20>
```

When enabled, the dispatcher calculates a score from SNR and packet length. A strong copy is processed immediately; a weaker copy is placed in the delayed inbound queue. The intention is to let a better branch propagate first so weaker branches later see a duplicate.

Risks include:

- increased latency on weak but unique links;
- score does not equal long-term reliability;
- different versions may calculate it differently;
- a large delay may interact badly with ACK timeouts.

Test the parameter against statistics rather than enabling it globally without comparison.

## Regions

Transport flood carries a region-derived code. A repeater may:

- allow the scope;
- deny the scope;
- apply parent/child policy;
- handle wildcard or unscoped traffic separately.

Regions reduce flood extent and are a primary scaling tool for multiple local meshes sharing radio connectivity. They are not encryption: the code is visible and acts only as a forwarding filter.

## Packet storms

A storm occurs when a packet stops being recognized as a duplicate and circulates until maximum path or hop limits are reached. Causes may include:

- bad or custom firmware modifying payload during forwarding;
- a bridge importing a packet as new;
- a loop through incompatible protocols;
- unstable packet hashing;
- disabled loop detection.

Signs include rapidly increasing flood send/receive counters, repeated messages, a full TX queue, exhausted duty budget, delayed direct ACKs, and repeated hashes in the path.

Mitigations include temporarily setting `repeat off`, enabling loop detection, reducing `flood.max`, isolating the suspect repeater, and examining raw logs.

## Example propagation

```text
A → R1 → R3 → B
 \→ R2 -/
```

1. A sends a flood with an empty path.
2. R1 and R2 hear A, append their hashes, and wait for random delay.
3. R1 transmits first.
4. R3 receives path `[R1]`, appends itself, and sends `[R1,R3]`.
5. R2 may hear the copy and suppress its own transmission.
6. B decrypts the payload and returns `[R1,R3]` as a direct path in the order required by the returned-path implementation.

If R1 disappears later, the cached direct path fails until a new flood discovery is performed.

## When flood is justified

- no path is known;
- the destination is mobile and the cached path is stale;
- a group channel is intended for broad distribution;
- an advert must update topology;
- an emergency message should try multiple branches;
- local discovery is insufficient.

## When flood should be avoided

- a working direct path already exists;
- traffic is periodic telemetry;
- the network is dense and the scope is too broad;
- the payload is large;
- a retry is caused only by a lost ACK;
- repeated adverts carry no new information.

## Related articles

- [Direct Routing and Path Discovery](/wiki/direct-routing-and-path-discovery)
- [Path Hashes, Duplicates, and Loops](/wiki/path-hashes-duplicates-and-loops)
- [Regions and Transport Codes](/wiki/regions-and-transport-codes)
- [Capacity and Scaling](/wiki/capacity-and-scaling)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
