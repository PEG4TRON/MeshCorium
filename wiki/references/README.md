# MeshCore Radio — English Technical Wiki

This category covers the MeshCore radio layer: from signal propagation and LoRa parameters to packet formats, flood/direct routing, service mechanisms, and network engineering.

The material reflects the project state as of **June 30, 2026**. MeshCore evolves quickly, so parameter values and compatibility details must always be checked against the installed firmware version.

![MeshCore radio model](attachments/meshcore-radio-model.svg)

## Scope of this category

Included:

- LoRa PHY and the RF signal chain;
- the `freq`, `bw`, `sf`, `cr`, `tx`, and `radio.rxgain` parameters;
- the physical LoRa frame and the MeshCore packet;
- flood, direct, path discovery, regions, and transport codes;
- advert, discovery, ACK, trace, and multipart mechanisms;
- RSSI, SNR, noise floor, statistics, and diagnostics;
- repeater placement, network capacity, and scaling;
- radio-layer threats and firmware compatibility.

Outside this category, except where a short mention is necessary:

- the BLE/USB/Wi-Fi Companion Protocol;
- mobile application user interfaces;
- contact and message storage in a particular client;
- complete Room Server and Sensor administration;
- firmware builds and application development.

## Main clarification: MeshCore is not LoRaWAN

MeshCore uses **LoRa** radio modulation, but it does not use the mandatory LoRaWAN architecture. MeshCore packets are received and retransmitted by the nodes themselves. Basic operation does not require a LoRaWAN Gateway, Network Server, Join Server, OTAA, ABP, DevEUI, or RX1/RX2 windows.

The distinction is covered in detail in [MeshCore, LoRa, and LoRaWAN](01-foundations/meshcore-lora-lorawan.md).

## Recommended reading order

1. [The MeshCore Radio Model](01-foundations/meshcore-radio-model.md)
2. [Node Roles](01-foundations/node-roles.md)
3. [MeshCore, LoRa, and LoRaWAN](01-foundations/meshcore-lora-lorawan.md)
4. [LoRa Modulation and Parameters](03-lora-phy/lora-modulation-and-parameters.md)
5. [MeshCore Packet Format](04-meshcore-packets/packet-format.md)
6. [Flood Routing](05-routing/flood-routing.md)
7. [Direct Routing and Path Discovery](05-routing/direct-routing-and-path-discovery.md)
8. [ACKs, Retries, and Multipart Packets](06-service-mechanisms/acknowledgements-retries-and-multipart.md)
9. [RSSI, SNR, and Link Quality](07-monitoring/rssi-snr-and-link-quality.md)
10. [Network Design and Repeater Placement](08-network-engineering/network-design-and-repeater-placement.md)

## Notation

- `code` denotes a parameter, command, packet field, or constant;
- **bold text** denotes a concept that is important to the topic;
- byte sizes refer to the currently published MeshCore Packet v1 format;
- CLI ranges come from the official documentation and may be further limited by the hardware;
- regulatory limits are provided only as orientation: applicable frequencies, EIRP, and duty cycle depend on the country, sub-band, and device class.

## Section map

- [01 — Foundations](01-foundations/)
- [02 — Radio Theory](02-radio-theory/)
- [03 — LoRa PHY](03-lora-phy/)
- [04 — MeshCore Packets](04-meshcore-packets/)
- [05 — Routing](05-routing/)
- [06 — Service Mechanisms](06-service-mechanisms/)
- [07 — Monitoring](07-monitoring/)
- [08 — Network Engineering](08-network-engineering/)

The complete table of contents is in [SUMMARY.md](SUMMARY.md), and the source list is in [SOURCES.md](SOURCES.md).
