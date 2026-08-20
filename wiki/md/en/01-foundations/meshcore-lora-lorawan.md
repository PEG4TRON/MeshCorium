# MeshCore, LoRa, and LoRaWAN

LoRa, LoRaWAN, and MeshCore belong to different layers. Confusing them leads to wrong expectations: looking for a gateway where a repeater is needed, trying to apply OTAA to MeshCore, or assuming that two devices are compatible merely because both are labeled LoRa.

![MeshCore and LoRaWAN](/attachments/en/meshcore-vs-lorawan.svg?v=2)

## LoRa is the physical modulation

LoRa is a radio modulation based on Chirp Spread Spectrum. It defines how bits are represented in the RF signal and how a receiver recovers them. LoRa PHY includes:

- carrier frequency;
- bandwidth;
- spreading factor;
- coding rate;
- preamble and sync word;
- PHY header and CRC;
- transmit power and receiver modes.

LoRa by itself does not define contacts, chats, routes, servers, application addresses, or network-join rules. LoRa can carry LoRaWAN, MeshCore, Meshtastic, a proprietary binary protocol, or test data.

## LoRaWAN is a standardized LPWAN architecture

LoRaWAN defines a MAC layer and a network architecture. End devices transmit LoRaWAN uplinks; one or more gateways receive them and forward them over IP to a Network Server. The server removes duplicates, validates frame counters and MICs, schedules downlinks, and performs other MAC functions.

Typical LoRaWAN concepts include:

- Gateway and concentrator;
- Network Server, Application Server, and Join Server;
- DevEUI, JoinEUI, AppKey/NwkKey;
- OTAA and ABP;
- uplink and downlink;
- confirmed and unconfirmed frames;
- ADR;
- RX1 and RX2;
- Classes A, B, and C.

A normal LoRaWAN end device does not retransmit frames from another end device. The topology is called star-of-stars: gateways provide access points to a centralized network layer.

## MeshCore is an independent mesh protocol

MeshCore defines its own packet format and routing rules. Nodes receive a LoRa frame, parse the MeshCore header, and may forward the packet using flood routing or a direct path.

Core MeshCore concepts include:

- Ed25519 identity;
- advert;
- contact and group channel;
- route type;
- path hash;
- flood/direct routing;
- returned path;
- ACK and multipart;
- regions and transport codes.

A Network Server is not required. A repeater operates on the same LoRa channel and retransmits MeshCore packets over RF rather than forwarding them to a central server over Ethernet.

## Layer-by-layer comparison

| Property | MeshCore | LoRaWAN |
|---|---|---|
| Physical radio bearer | LoRa PHY | LoRa PHY |
| Main topology | Multi-hop mesh | Star-of-stars |
| Intermediate device | Repeater receives and retransmits a packet | Gateway receives a frame and forwards it to a server over backhaul |
| Control center | Not mandatory | Network Server is part of the architecture |
| Identity | MeshCore public key | DevEUI/JoinEUI and session context |
| Network admission | Advert/contact exchange and channel secrets | OTAA or ABP |
| Routing | Flood/direct path inside the radio mesh | End device → gateway → server; downlink through a selected gateway |
| Acknowledgment | MeshCore ACK over a reverse radio route | Confirmed frame and LoRaWAN downlink |
| Groups | Shared channel secret and group payload | LoRaWAN multicast context |
| Regional scope | MeshCore regions/transport codes | LoRaWAN regional parameters and channel plan |

## Why matching frequency is not enough

PHY parameters must match before any frame can be received. Even when they do, the receiver obtains bytes belonging to a different protocol. A LoRaWAN header does not match MeshCore `VVPPPPRR`, and a MeshCore packet does not contain LoRaWAN MHDR, FHDR, and MIC in the expected format.

Three outcomes are possible:

1. **The PHY differs.** The receiver cannot decode the frame at all.
2. **The PHY matches, but the protocol differs.** The radio chip outputs bytes, but firmware rejects them as unknown or corrupt.
3. **The PHY and protocol match, but keys differ.** The packet parses, yet its payload fails authentication or does not belong to a known contact or channel.

## A repeater is not a gateway

A LoRaWAN gateway normally contains a multichannel concentrator and can receive multiple frequencies and spreading factors at once. A MeshCore repeater is commonly built around a normal single-channel LoRa transceiver and operates with one radio profile at a time.

A gateway does not create a multi-hop LoRaWAN route through neighboring gateways. A MeshCore repeater does create an additional RF hop. Their engineering requirements therefore differ:

- a gateway requires reliable IP backhaul;
- a repeater requires good radio visibility to neighboring MeshCore nodes;
- a gateway may receive many LoRaWAN channels;
- a MeshCore repeater must match the network's specific radio profile;
- loss of a gateway affects server access;
- loss of a repeater breaks direct paths that use it.

## ADR and a manually coordinated radio profile

LoRaWAN ADR allows the server to manage an end device's data rate and transmit power within a regional plan. In MeshCore, all participants sharing a channel must remain compatible. If one node changes SF or BW on its own, it effectively moves into a different radio network.

Changing a MeshCore profile is therefore a migration operation:

- define the new parameter set;
- verify hardware support on every node;
- choose an update order;
- preserve temporary access through `tempradio` or a physical console;
- update critical repeaters;
- only then move client devices.

## LoRaWAN regional parameters and regulation

LoRaWAN regional parameters are part of the LoRaWAN standard, while legal limits come from national spectrum regulation. MeshCore remains subject to those rules. Frequency, EIRP, duty cycle, channel access, and permitted bandwidth depend on the country and sub-band.

Do not copy a LoRaWAN channel mask into MeshCore without checking it. Likewise, a documented MeshCore default must not be assumed legal in every country.

## Sharing spectrum

MeshCore and LoRaWAN may operate in the same license-exempt band and interfere with one another. Even with different sync words or parameters, a strong nearby signal can:

- make CAD report a busy channel;
- raise the noise floor;
- overload the receiver input;
- corrupt a weak packet;
- increase delays and retry counts.

Frequency, bandwidth, power, and transmit timing should be coordinated not only within a MeshCore network, but also with other users of the band.

## When to use LoRaWAN and when to use MeshCore

LoRaWAN is a natural fit when many low-power sensors send small amounts of data to server infrastructure and gateways have backhaul.

MeshCore is a natural fit when local autonomous communication between people or devices is required, Internet access is not guaranteed, and multi-hop retransmission is useful.

The systems can be integrated through a bridge, but the bridge must translate application data. One wire format cannot be routed directly as the other.

## Related articles

- [The MeshCore Radio Model](/wiki/meshcore-radio-model)
- [LoRa Modulation and Parameters](/wiki/lora-modulation-and-parameters)
- [MeshCore Radio Profiles and Hardware](/wiki/radio-profile-and-hardware)
- [Compatibility and Migration](/wiki/compatibility-and-migration)

## Sources

- <https://www.semtech.com/lora/what-is-lora>
- <https://lora-alliance.org/resource_hub/what-is-lorawan/>
- <https://lora-alliance.org/lorawan-for-developers/>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
