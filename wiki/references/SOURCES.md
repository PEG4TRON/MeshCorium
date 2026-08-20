# Sources and Methodology

## Primary MeshCore sources

Protocol and parameter descriptions are based primarily on the official `meshcore-dev/MeshCore` repository:

- repository: <https://github.com/meshcore-dev/MeshCore>
- FAQ: <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- CLI: <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- Packet Format: <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- Payload Format: <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- Number Allocations: <https://github.com/meshcore-dev/MeshCore/blob/main/docs/number_allocations.md>
- `Packet.h`: <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- `Mesh.cpp`: <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- `Dispatcher.cpp`: <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- Companion firmware example: <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>

Documentation and source code are considered together. Where an assumed behavior conflicts with the current code or an explicitly published wire format, the current code and published wire format take priority. This wiki does not treat internal behavior of a specific third-party client as part of the MeshCore protocol.

## LoRa PHY sources

- Semtech, What is LoRa: <https://www.semtech.com/lora/what-is-lora>
- Semtech, AN1200.22 LoRa Modulation Basics: available from Semtech transceiver pages, for example <https://www.semtech.com/products/wireless-rf/lora-connect/sx1276>
- Semtech SX1261/SX1262: <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- RadioLib: <https://github.com/jgromes/RadioLib>

## LoRaWAN sources

- LoRa Alliance, What is LoRaWAN: <https://lora-alliance.org/resource_hub/what-is-lorawan/>
- LoRaWAN for Developers: <https://lora-alliance.org/lorawan-for-developers/>

LoRaWAN is used only for comparison. LoRaWAN mechanisms must not be transferred automatically to MeshCore.

## Regulatory sources

- CEPT/ECO, ERC Recommendation 70-03: <https://docdb.cept.org/document/845>
- ETSI, Short Range Devices: <https://www.etsi.org/technologies/short-range-devices>
- ETSI EN 300 220 series: documents are available in the ETSI catalogue.

Regulatory tables change. Before deploying a node, check national rules, the current revision of the recommendations, and the parameters for the specific sub-band.

## Limitations

- The wiki describes the publicly available project state as of June 30, 2026.
- Reserved values are not presented as implemented features.
- Experimental parameters are identified explicitly.
- A CLI command being present does not imply support on every board or in every role.
- Range calculations are estimates; terrain, antennas, noise, and installation quality can change the result by tens of decibels.
