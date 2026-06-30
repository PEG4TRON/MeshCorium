# MeshCore Radio Archive Manifest

Documentation snapshot: **June 30, 2026**.

## Contents

- substantive articles: **29**;
- thematic directories: **8**;
- SVG diagrams: **12**;
- words in substantive articles: **32,141**;
- Markdown files in the archive: **34**;
- full checksums file: **`CHECKSUMS.sha256`**.

## Tree

```text
Radio/
├── CHECKSUMS.sha256
├── MANIFEST.md
├── README.md
├── SOURCES.md
├── SUMMARY.md
├── VALIDATION.md
├── 01-foundations/
│   ├── meshcore-lora-lorawan.md
│   ├── meshcore-radio-model.md
│   └── node-roles.md
├── 02-radio-theory/
│   ├── antennas-and-rf-chain.md
│   ├── frequency-power-and-link-budget.md
│   └── propagation-and-coverage.md
├── 03-lora-phy/
│   ├── airtime-duty-cycle-and-capacity.md
│   ├── lora-frame-and-radio-cycle.md
│   ├── lora-modulation-and-parameters.md
│   └── radio-profile-and-hardware.md
├── 04-meshcore-packets/
│   ├── addressing-identity-and-encryption.md
│   ├── packet-format.md
│   ├── service-payloads.md
│   └── user-payloads.md
├── 05-routing/
│   ├── channel-access-queues-and-delays.md
│   ├── direct-routing-and-path-discovery.md
│   ├── flood-routing.md
│   ├── path-hashes-duplicates-and-loops.md
│   └── regions-and-transport-codes.md
├── 06-service-mechanisms/
│   ├── acknowledgements-retries-and-multipart.md
│   ├── adverts-discovery-and-neighbors.md
│   └── trace-and-route-diagnostics.md
├── 07-monitoring/
│   ├── interference-and-radio-problems.md
│   ├── rssi-snr-and-link-quality.md
│   └── statistics-and-logging.md
├── 08-network-engineering/
│   ├── capacity-and-scaling.md
│   ├── compatibility-and-migration.md
│   ├── network-design-and-repeater-placement.md
│   └── security-threats.md
└── attachments/
    ├── ack-flow.svg
    ├── capacity-scaling.svg
    ├── flood-vs-direct.svg
    ├── lora-frame.svg
    ├── lora-parameter-tradeoffs.svg
    ├── meshcore-packet.svg
    ├── meshcore-radio-model.svg
    ├── meshcore-vs-lorawan.svg
    ├── path-hash.svg
    ├── regions.svg
    ├── repeater-placement.svg
    └── signal-metrics.svg
```

## Article sizes

| File | Words | SHA-256 (first 12 characters) |
|---|---:|---|
| `01-foundations/meshcore-lora-lorawan.md` | 1,083 | `aee857631c12` |
| `01-foundations/meshcore-radio-model.md` | 1,207 | `b28432ddb282` |
| `01-foundations/node-roles.md` | 1,296 | `6c131256ddc7` |
| `02-radio-theory/antennas-and-rf-chain.md` | 1,233 | `f404e3d080a1` |
| `02-radio-theory/frequency-power-and-link-budget.md` | 982 | `9c4f22289c91` |
| `02-radio-theory/propagation-and-coverage.md` | 1,042 | `060eb1c01fbc` |
| `03-lora-phy/airtime-duty-cycle-and-capacity.md` | 999 | `b78b0d27ef8e` |
| `03-lora-phy/lora-frame-and-radio-cycle.md` | 1,067 | `f2db904f03b7` |
| `03-lora-phy/lora-modulation-and-parameters.md` | 1,041 | `847c1542efa3` |
| `03-lora-phy/radio-profile-and-hardware.md` | 1,009 | `b42f5ae5a5e7` |
| `04-meshcore-packets/addressing-identity-and-encryption.md` | 1,170 | `dbc46afbc4f8` |
| `04-meshcore-packets/packet-format.md` | 1,142 | `babf59924470` |
| `04-meshcore-packets/service-payloads.md` | 859 | `4a29509df6ef` |
| `04-meshcore-packets/user-payloads.md` | 977 | `d7e60ca444d4` |
| `05-routing/channel-access-queues-and-delays.md` | 1,170 | `b2c3ee184cbb` |
| `05-routing/direct-routing-and-path-discovery.md` | 1,159 | `3113b625882c` |
| `05-routing/flood-routing.md` | 1,294 | `5c1f3c6e528c` |
| `05-routing/path-hashes-duplicates-and-loops.md` | 1,104 | `2ae893f98952` |
| `05-routing/regions-and-transport-codes.md` | 949 | `273702ccd237` |
| `06-service-mechanisms/acknowledgements-retries-and-multipart.md` | 1,123 | `5e66ed20b171` |
| `06-service-mechanisms/adverts-discovery-and-neighbors.md` | 1,055 | `395249001ad7` |
| `06-service-mechanisms/trace-and-route-diagnostics.md` | 986 | `f9c8c0260705` |
| `07-monitoring/interference-and-radio-problems.md` | 1,087 | `e3439e4b360e` |
| `07-monitoring/rssi-snr-and-link-quality.md` | 1,026 | `53c023240f16` |
| `07-monitoring/statistics-and-logging.md` | 924 | `cd446595470a` |
| `08-network-engineering/capacity-and-scaling.md` | 1,217 | `cfa7d7bc1c31` |
| `08-network-engineering/compatibility-and-migration.md` | 1,255 | `346b2b25370a` |
| `08-network-engineering/network-design-and-repeater-placement.md` | 1,257 | `8d3b3f37ac75` |
| `08-network-engineering/security-threats.md` | 1,428 | `6136bd2244c2` |

Full checksums are stored in `CHECKSUMS.sha256`.
