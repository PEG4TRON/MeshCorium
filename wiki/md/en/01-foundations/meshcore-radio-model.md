# The MeshCore Radio Model

MeshCore transmits its own packets through a LoRa transceiver. The radio chip creates the physical LoRa frame, while the firmware places a MeshCore header, path, and payload inside it. The network does not require a mandatory base station: compatible nodes listen to the shared channel and, when their role and configuration permit, process or retransmit a received packet.

![MeshCore radio model](/attachments/en/meshcore-radio-model.svg?v=2)

## The shared radio channel

A typical node's LoRa radio operates in **half-duplex** mode: it either transmits or receives. While a node is transmitting, it cannot listen to the same channel at the same time. Devices with matching `frequency`, `bandwidth`, `spreading factor`, `coding rate`, and other PHY settings form a single contention domain for the air interface.

The physical transmission is not addressed to one receiver. Every node within radio range receives the electromagnetic signal. Addressing begins only after demodulation: the firmware parses the MeshCore packet and decides whether it is intended for this node, should be forwarded, or should be discarded.

This leads to three important properties:

1. **A node can hear a packet without being its destination.** Encryption protects the content, but it does not hide the fact that a transmission occurred, its length, or some routing metadata.
2. **Every transmission consumes a shared resource.** The longer a packet remains on air, the greater the collision probability and the less airtime remains for other nodes.
3. **Retransmission is a new radio transmission.** A message that crosses five hops consumes the channel at least six times: the original transmission plus five retransmissions. ACKs and retries add more transmissions.

## Node, neighbor, and hop

A **node** is a network participant with a MeshCore identity and a LoRa radio. A node that can be received without an intermediate retransmission is a **radio neighbor**. This is not necessarily a saved contact and not necessarily a permanent relationship: neighbor status depends on current transmit power, antennas, terrain, interference, and device position.

A **hop** is one radio transition between two nodes. If A can hear B directly, A → B is one hop. If a packet travels A → R1 → R2 → B, the source and destination are three hops apart.

A **path** is a sequence of identifiers for intermediate nodes. A **route** is a broader concept: the delivery method, including the routing type and the path being used. In MeshCore, a direct packet can still be multi-hop. The word `direct` means forwarding over a supplied path, not necessarily direct radio visibility between source and destination.

## What happens after a message is sent

A simplified sequence for a private message is:

1. The application passes text to the companion.
2. The firmware selects a stored direct path or starts with flood routing if no usable path exists.
3. It builds the payload: timestamp, text type, attempt number, and message body.
4. The data is encrypted with the shared secret between source and destination, and a MAC is added.
5. A MeshCore packet is created with a route type, payload type, and path.
6. The packet is placed in the transmit queue.
7. The dispatcher waits for an allowed transmit time, checks channel state, and starts TX.
8. Radio neighbors demodulate the LoRa frame and parse the MeshCore packet.
9. The destination attempts to decrypt the data; repeaters apply flood or direct forwarding rules.
10. After successful delivery, an ACK may be generated, which requires a separate return route.

`TX Done` confirms only that the radio chip has finished transmitting. It does not prove that a neighbor received the packet, that the packet reached the destination, or that an application processed it.

## Flood and direct as two phases

MeshCore combines two mechanisms:

- **Flood routing** distributes a packet when no route is known in advance. Eligible repeaters receive a copy, wait for a randomized delay, and compete to forward it. Path hashes accumulate along the route.
- **Direct routing** uses a known sequence of hops. Only the node whose hash appears next in the path forwards the packet. The consumed path entry is removed after forwarding.

A typical communication lifecycle is: the first packet is flooded, the receiver returns a path, and later messages travel direct. This reduces load, but it makes delivery dependent on path freshness. If a mobile or powered-off repeater disappears, the path must be discovered again.

See [Flood Routing](/wiki/flood-routing) and [Direct Routing and Path Discovery](/wiki/direct-routing-and-path-discovery).

## What actually creates the mesh

The mesh does not come from LoRa modulation itself. LoRa provides physical transmission. The mesh is created by software rules:

- interpreting the route type;
- accumulating or consuming path entries;
- deciding whether forwarding is allowed;
- suppressing duplicates;
- delaying competing retransmissions;
- limiting hop count;
- filtering regions;
- constructing return paths and ACKs.

Two devices with matching LoRa settings but without a compatible MeshCore format may detect each other's RF signal, yet they cannot interpret the packet or participate in routing.

## Collision domain

All nodes capable of affecting one another's reception belong to a **collision domain**. It is often larger than the area of reliable decoding. A weak transmitter may not be decodable but can still raise the noise floor or corrupt another packet.

Hidden nodes are especially problematic. A and C may not hear each other, while both are received strongly by repeater B. A clear-channel check at A will not detect C's transmission, so their packets may collide at B. CAD and randomized delay reduce this risk but cannot eliminate it completely.

## Why more repeaters are not always better

Every additional repeater may create a useful new path. In a dense area, however, it also:

- receives the same flood packets;
- competes for retransmission;
- generates adverts;
- increases duplicate count and path size;
- consumes duty-cycle budget;
- raises collision probability.

A useful repeater should open coverage to new territory or create an independent backup path. Installing several nodes on the same roof with nearly identical coverage usually increases load more than resilience.

## Terms that must not be confused

| Term | Meaning |
|---|---|
| Radio neighbor | A node reachable in one hop |
| Contact | A saved identity in a client or companion |
| Direct | Routing over a supplied path |
| Zero-hop | A packet with no intermediate hop |
| Radio broadcast | All compatible receivers can physically hear the signal |
| Group message | An encrypted shared-channel payload, usually distributed by flood |
| Gateway | A LoRaWAN term; not a synonym for a MeshCore repeater |

## A practical layered model

For network analysis, it is useful to think in four layers:

1. **RF environment:** frequency, antenna, noise, terrain, power.
2. **LoRa PHY:** BW, SF, CR, preamble, sync word, CRC.
3. **MeshCore transport:** header, route type, path, regions, payload type.
4. **Application data:** text, request, telemetry, group datagram.

A problem in a lower layer breaks every layer above it. A wrong key does not explain the absence of RSSI, while good RSSI does not prove a compatible radio profile or a valid payload.

## Related articles

- [Node Roles](/wiki/node-roles)
- [LoRa Modulation and Parameters](/wiki/lora-modulation-and-parameters)
- [MeshCore Packet Format](/wiki/packet-format)
- [Channel Access, Queues, and Delays](/wiki/channel-access-queues-and-delays)
- [Capacity and Scaling](/wiki/capacity-and-scaling)

## Sources

- <https://github.com/meshcore-dev/MeshCore>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
