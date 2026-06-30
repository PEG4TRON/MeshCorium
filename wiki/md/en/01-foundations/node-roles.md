# MeshCore Node Roles

A role determines which application functions are available on a node and under what conditions it creates, receives, or forwards packets. A role must not be confused with a board model: the same hardware platform can run different firmware variants, and the same role can run on different microcontrollers and LoRa transceivers.

## Summary table

| Role | Primary purpose | User interface | Continuous forwarding |
|---|---|---|---|
| Companion | Radio interface for an application and the user's personal identity | BLE, USB, Wi-Fi, or another companion transport | Usually no; depends on the firmware and mode |
| Repeater | Routing and coverage extension | Console and remote administration | Yes, when `repeat` is enabled and policy allows the packet |
| Room Server | Shared room and message storage | Remote requests/responses and administrative CLI | May participate in routing, depending on implementation |
| Sensor | Publishing and serving sensor data | Requests, telemetry, sometimes CLI | Depends on build and settings |
| Bridge | Moving data between MeshCore and an external transport | Serial port, network, or a dedicated interface | Not necessarily; implementation-defined |
| KISS Modem | Low-level access to the radio or packets | KISS-like interface | Controlled by the host application |

Exact feature support depends not only on the role, but also on compile-time flags, flash/RAM capacity, transport type, and firmware version.

## Companion

A Companion connects the LoRa network to a client application. It commonly stores or manages:

- the user's local identity;
- the contact list;
- cached direct paths;
- group channels and their secrets;
- incoming and outgoing message queues;
- radio-profile settings;
- advert, path-discovery, and ACK logic.

A Companion is not the same thing as a smartphone. The smartphone or web client is the interface; the Companion is the physical LoRa device running MeshCore firmware. The link between an application and the Companion may use BLE, USB, Wi-Fi, or another transport, but that is a separate channel and is not part of the LoRa mesh.

In the basic model, a Companion should not be treated as infrastructure routing equipment. Some client firmware variants provide off-grid or client-repeat modes, but their behavior, power consumption, and compatibility should be evaluated separately from a standard stationary repeater.

## Repeater

A Repeater is a specialized routing node. It continuously listens to the air, parses the route type, checks constraints, and places a packet into the retransmission queue when appropriate.

Typical responsibilities include:

- appending its own path hash to a flood packet;
- forwarding a direct packet when its hash is the next hop;
- suppressing packets already seen;
- enforcing `flood.max`, region filters, and duty-cycle limits;
- applying `txdelay`, `direct.txdelay`, and, when configured, `rxdelay`;
- detecting suspicious routing loops;
- transmitting its own adverts;
- exposing statistics and a list of recent neighbors.

The `repeat` parameter disables forwarding and turns the device into an observer. Such a node can still receive packets and collect statistics, but it no longer extends routes.

### Stationary operation

A direct path stores a sequence of intermediate nodes. A stationary repeater is therefore more predictable than a mobile one. If a route was discovered through a vehicle-mounted or handheld node, moving that node can break direct delivery until a new path discovery is performed.

### Power

A repeater should spend most of its time in RX. Power saving may be possible, but sleep periods reduce the chance of receiving an unscheduled packet. Use `powersaving` only after checking how the specific firmware implements its sleep and receive windows.

## Room Server

A Room Server provides a shared application room. A client can log in, synchronize messages, and submit a new post. It is not equivalent to an Internet server: all communication still travels as MeshCore packets and is constrained by airtime, payload size, and route length.

A Room Server has an identity and can publish an advert. At the radio level, login normally begins with an anonymous request containing the sender's public key and encrypted data. After context is established, normal request/response or text payloads are used.

A server function does not imply unlimited capacity. A popular room reached over many hops can generate substantial two-way traffic: login, synchronization, replies, messages, and ACKs.

## Sensor

A Sensor publishes or serves measurements. In a simple implementation it may:

- periodically send a group datagram;
- respond to an addressed request;
- report battery voltage and local measurements;
- use an allocated data type in `PAYLOAD_TYPE_GRP_DATA`.

The exact format of sensor commands is not fully universal: some request types are defined by application firmware. Separate the base MeshCore payload from the application's data schema.

Important design variables for sensors are:

- publication interval;
- message size;
- whether ACKs are required;
- sleep strategy;
- permitted duty cycle;
- probability that many sensors transmit at once.

Synchronizing hundreds of sensors to transmit on the exact minute creates collisions. Intervals should be randomized.

## Bridge

A Bridge connects MeshCore to another system, such as MQTT, Home Assistant, an IP service, a serial link, or a separate radio network. It may act only as an application endpoint, or it may also forward MeshCore packets.

The main bridge risk is an uncontrolled loop. If a packet is exported into another domain and later re-imported as a new packet, the normal duplicate cache may not recognize it. A bridge needs explicit rules for:

- which payloads may be exported;
- how message identity is preserved;
- how TTL or hop count is limited;
- how reverse import is prevented;
- where MeshCore encryption terminates.

## KISS Modem

KISS Modem mode provides lower-level access than a normal Companion. A host application can create or read frames through a simple framing protocol. This is useful for experiments and integrations, but it transfers responsibility to the external program:

- set a valid radio profile;
- obey duty-cycle limits;
- validate packet lengths and types;
- avoid routing loops;
- do not transmit reserved values as if they were implemented features.

KISS mode does not turn MeshCore into AX.25 and does not make it compatible with arbitrary packet-radio software without an adapter.

## Identity and role

A role is published in advert appdata flags, while identity is defined by the key pair. Changing the role should not automatically change the key. If a device is reinstalled while preserving its private key, other nodes may recognize the same identity with a different advert type.

This is useful during upgrades, but it requires care: saved contacts, ACL entries, and trust are tied to the key, not to the enclosure label or BLE name.

## Choosing a role

### Smartphone access is required

Use a Companion. Choose the supported host transport first, then the board, runtime, and radio profile.

### Coverage must be extended

Use a stationary Repeater with a good antenna, continuous power, and a known location. Height and a low noise floor matter more than maximum transmit power.

### A shared offline room is required

Use a Room Server. Before deployment, estimate synchronization load and the number of hops to the main users.

### Telemetry is required

Use a Sensor or custom firmware based on MeshCore. Define the data type, interval, encryption, and retry policy in advance.

### Integration is required

Use a Bridge or KISS interface, but only with a separate security model and explicit loop prevention.

## Common incorrect assumptions

- **Every MeshCore node repeats packets.** No. Forwarding depends on the role, build, `repeat` setting, and policy.
- **A Repeater stores all user messages.** Not necessarily; its primary function is routing.
- **A Room Server is the central server for the network.** No. Other nodes continue communicating without it.
- **A Companion is a LoRaWAN end device.** No. It uses the MeshCore protocol over LoRa PHY.
- **The same board always has the same capabilities.** No. Firmware and enabled compile-time features are decisive.

## Related articles

- [The MeshCore Radio Model](/wiki/meshcore-radio-model)
- [Adverts, Discovery, and Neighbors](/wiki/adverts-discovery-and-neighbors)
- [Network Design and Repeater Placement](/wiki/network-design-and-repeater-placement)
- [Compatibility and Migration](/wiki/compatibility-and-migration)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/tree/main/examples>
