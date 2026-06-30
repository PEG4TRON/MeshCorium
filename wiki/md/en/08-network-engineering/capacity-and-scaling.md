# MeshCore Capacity and Scaling

A mesh network does not create additional spectrum. Every forwarding transmission consumes airtime on the same shared medium. As the number of nodes grows, flood traffic and collisions can increase faster than useful application traffic.

![Growth of radio load](/attachments/en/capacity-scaling.svg?v=2)

## The useful unit of load

Count **radio transmissions**, not only application messages.

For a direct message over `H` links:

```text
TXdata ≈ H
TXack  ≈ Hreverse
```

For a flood:

```text
TXflood ≈ 1 + number of repeaters that forward the unique packet
```

Then add retries, adverts, discovery, trace packets, and responses.

## Collision domains

Capacity must be evaluated for each group of nodes whose transmissions interfere with one another. Two distant segments can transmit simultaneously if they neither hear each other nor overload a common receiver. A high backbone repeater can merge those segments into one larger collision domain.

For this reason, total network-wide airtime is less useful than airtime measured at every critical site.

## Calculating useful load

For each traffic class:

```text
Load = rate · serialized_size_toa · forwarding_factor
```

Possible classes include:

- personal text;
- group text;
- sensor datagrams;
- flood adverts;
- zero-hop adverts;
- ACK packets;
- room synchronisation;
- remote CLI traffic;
- trace traffic.

The serialized size includes the path and encryption padding.

## Flood amplification

In a dense area, one flood is heard by `N` repeaters. Random delay and the seen-packet table reduce forwarding, but hidden nodes may not hear the first retransmission and may transmit their own copies anyway.

Amplification depends on:

- geometry;
- `txdelay`;
- packet airtime;
- hidden nodes;
- `rxdelay`;
- duplicate-cache behaviour;
- path and hash collisions;
- queue state;
- `flood.max`;
- region policy.

The forwarding factor cannot safely be assumed to equal one.

## Direct-routing efficiency

After path discovery, direct routing uses one chain of nodes. The saving is especially large for:

- frequent peer-to-peer messages;
- telemetry sent repeatedly to one server;
- remote administration;
- room synchronisation.

A stale path, however, causes failed transmissions and retries. Cache policy must balance discovery cost against route freshness.

## Group channels

Group text is normally flooded because it has multiple recipients. A popular public channel can become the dominant capacity consumer.

Mitigations include:

- assigning a region scope;
- limiting flood depth;
- dividing thematic channels by area;
- avoiding media and large binary transfers;
- rate-limiting bots;
- suppressing duplicate notifications;
- using a Room Server for history instead of repeated rebroadcast when that application model fits.

A private channel is not automatically direct. The shared key selects the encryption context; the route is selected separately.

## Advert budget

Assume 100 repeaters, each sending one flood advert every 12 hours. That creates 200 original adverts per day. If each advert is forwarded by five nodes on average, the backbone carries roughly 1,000 radio transmissions per day for repeater adverts alone.

If the interval is accidentally changed to 10 minutes, the original advert rate rises by a factor of 72. A single fleet-wide parameter can therefore dominate the network.

## The sensor synchronisation problem

Suppose 100 sensors report every five minutes. Their average rate appears low, but if their clocks are aligned and all transmit at `:00`, they create a burst.

Use jitter:

```text
next_tx = nominal_period + random_jitter
```

Other useful techniques are:

- report on change;
- aggregation;
- local buffering;
- no ACK for non-critical samples;
- a random initial phase;
- smaller payloads.

## Hop count and delivery probability

If the success probability of each link is `p`, the approximate one-way end-to-end probability over `H` links is:

```text
P = p^H
```

For `p = 0.95`:

| Hops | One-way probability |
|---:|---:|
| 1 | 95% |
| 3 | 86% |
| 5 | 77% |
| 10 | 60% |

A confirmed round trip must also succeed over the reverse links. A route made from many marginal links therefore has poor confirmed-delivery performance even before congestion is considered.

## High SF and capacity

A high spreading factor improves weak-signal decoding, but a packet may occupy the channel for seconds. If an entire segment is moved to a “long-range” profile:

- capacity falls;
- the hidden-node overlap window becomes longer;
- radios remain unavailable for reception during transmission for longer;
- duty-cycle budget is consumed faster;
- queues and latency grow.

Where topology permits, improve backbone sites and antennas and retain a moderate profile instead of using the slowest possible settings everywhere.

## Regions as scaling boundaries

Region scope reduces the number of repeaters that process a local flood. A useful hierarchy follows real traffic locality:

```text
Country
├── Metro-A
│   ├── District-1
│   └── District-2
└── Metro-B
```

Most traffic should remain within a district or metropolitan area. Country-wide scope should be exceptional.

Regions that are too small increase administrative complexity and break useful reachability. Regions that are too large do not reduce load.

## Hash size and network scale

A one-byte path hash has a meaningful collision risk once a network contains tens of identities. Two- and three-byte hashes reduce route ambiguity but add overhead.

A few bytes of overhead are usually cheaper than a duplicate branch or a failed ACK. Upgrade the backbone for multibyte support before the network becomes large.

## Room Server load

A room creates bidirectional sessions involving:

- login;
- synchronisation from a timestamp;
- multiple responses;
- posts;
- acknowledgements;
- keepalives.

If 50 clients reconnect and synchronise at once after an outage, both the server and its route receive a burst. Use:

- randomised reconnect backoff;
- page and batch limits;
- a bounded history;
- region-local rooms;
- queue monitoring;
- direct paths.

## Capacity targets

Do not design a channel for 100% of theoretical airtime. Reserve capacity for:

- emergency traffic;
- retries;
- hidden nodes;
- route discovery;
- maintenance;
- packet-size variation;
- external interference.

The safe target must be established by measurement. When queue length and latency start growing non-linearly, the network is already beyond a comfortable operating point.

## Saturation metrics

Monitor:

- channel utilisation;
- TX airtime rate;
- queue P95 and maximum;
- minimum free packet-pool count;
- CAD-busy duration;
- duplicate ratio;
- ACK ratio;
- median and P95 latency;
- retries per confirmed message;
- flood-to-direct ratio.

### Early warning signs

- messages are occasionally delayed but eventually arrive;
- ACK packets arrive after the user-interface timeout;
- duplicate traffic grows faster than unique traffic;
- queues no longer return to zero;
- busy periods degrade much more than the average period.

### Congestion collapse

- retries dominate useful traffic;
- queues remain full;
- the packet pool is exhausted;
- direct traffic is starved by flood traffic;
- the duty-cycle budget cannot recover;
- users resend manually, adding still more load.

## Scaling plan

1. Measure current load.
2. Classify traffic.
3. Move repeated peer flows to direct routing.
4. Reduce advert frequency.
5. Introduce regions.
6. Desynchronise sensor traffic.
7. Upgrade path-hash mode.
8. Disable unnecessary repeaters.
9. Improve weak links.
10. If necessary, split radio channels and add a controlled bridge.

## Controlled bridge

Separating a deployment across two PHY channels can increase spatial or frequency capacity, but the bridge must:

- forward only authorised application messages;
- preserve a stable message identifier;
- never reflect a packet back to its ingress channel;
- enforce rate limits;
- translate scopes deliberately;
- log loop indicators;
- form an explicit security boundary.

Blindly repeating raw packets between channels can create a permanent loop.

## Capacity worksheet

For each flow, record:

| Flow | Rate/h | Bytes | ToA | Average forwarding TX | ACK TX | Airtime/h |
|---|---:|---:|---:|---:|---:|---:|
| Local text | | | | | | |
| Group | | | | | | |
| Sensor | | | | | | |
| Advert | | | | | | |
| Administration | | | | | | |

Add a 30–100% reserve depending on uncertainty, then confirm the result with a field test.

## Related articles

- [Airtime and duty cycle](/wiki/airtime-duty-cycle-and-capacity)
- [Flood routing](/wiki/flood-routing)
- [Regions](/wiki/regions-and-transport-codes)
- [Statistics](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
