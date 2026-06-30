# MeshCore Radio Profiles and Hardware

A radio profile is the set of PHY parameters that allows nodes to demodulate one another. MeshCore does not automatically adapt the rest of the network when one device changes its profile: a node with incompatible settings disappears from the shared channel.

## Main command

The official CLI provides:

```text
get radio
set radio <freq>,<bw>,<sf>,<cr>
```

Parameters:

| Field | Units | Documented range |
|---|---|---|
| `freq` | MHz | chip-dependent; `tempradio` accepts 300–2500 |
| `bw` | kHz | `tempradio`: 7.8–500 |
| `sf` | — | 5–12 |
| `cr` | denominator | 5–8, meaning 4/5 through 4/8 |

The documentation gives a default of `869.525,250,11,5`, but a specific build, regional preset, or board may differ. Check local regulation before copying this value.

`set radio` requires a reboot to take effect.

## Temporary profile

```text
tempradio <freq>,<bw>,<sf>,<cr>,<timeout_mins>
```

A temporary profile is not saved and is cleared after a reboot or timeout. It is useful for:

- network migration;
- temporary access to a node on another profile;
- field testing;
- recovery of a misconfigured repeater.

The risk is that the remote node becomes unreachable on the main channel after the switch. Always have a return plan.

## Frequency

Separate commands are available:

```text
get freq
set freq <MHz>
```

`set freq` is documented as serial-only and requires a reboot. This is a sensible safeguard: changing frequency remotely would immediately break the management channel.

The selected frequency must:

- be supported by the transceiver;
- match the board's matching network, filters, and antenna;
- be legal in the country;
- account for neighboring services and the channel plan;
- match every participant in the segment.

A transceiver with a wide advertised range does not make the entire board RF front end wideband. A 915 MHz module may contain filters and matching that perform poorly at 433 MHz.

## Power

```text
get tx
set tx <dBm>
```

The CLI documents `1–22 dBm`, but the actual range depends on chip and board. The value controls the LoRa-chip output. An external PA can change the final power.

Check:

- maximum chip power;
- permissible PA input;
- supply voltage and current;
- EIRP;
- heat dissipation;
- harmonics;
- receive stability of nearby nodes.

## RX boosted gain

For supported SX12xx and LR1110 devices on firmware v1.14.1+:

```text
get radio.rxgain
set radio.rxgain on|off
```

The documented default is `on`. An upgrade from an older version may leave the stored setting `off` because of a known issue, so read it explicitly after migration.

Boosted gain can improve sensitivity at a quiet site, but does not replace filtering in a strong RF environment. Compare PDR and noise floor in both modes.

## Build flags

Default values may be set by:

- `LORA_FREQ`;
- `LORA_BW`;
- `LORA_SF`;
- `LORA_CR`;
- `LORA_TX_POWER`.

Runtime preferences commonly override build defaults after they have been saved. Reflashing without erasing storage may therefore not apply new build values. A migration plan must account for whether the filesystem or preferences are preserved.

## Other PHY parameters

The user-facing CLI does not expose every radio setting. Other relevant implementation parameters include:

- sync word;
- preamble length;
- CRC mode;
- explicit or implicit header;
- LDRO;
- TCXO voltage and startup delay;
- DIO mapping;
- RF-switch control;
- regulator mode;
- image calibration.

These are set by the board and radio wrapper. Two custom builds with matching `freq,bw,sf,cr` may still be incompatible.

## Transceiver families

### SX1276/SX1278

An older generation with register-based control and many common modules. Chip revision, matching range, and DIO wiring matter.

### SX1261/SX1262/SX1268

A newer command-based generation with improved power behavior and separate RX-gain modes. SX1262 commonly supports up to +22 dBm, but the module may impose lower limits.

### LLCC68

A relative of SX126x with restrictions on some parameter ranges. Do not assume it is fully equivalent to SX1262 without checking the data sheet and wrapper.

### SX128x

Operates around 2.4 GHz and has different propagation, bandwidth, and regulatory characteristics. A sub-GHz antenna is not compatible.

### LR1110

A multifunction transceiver with LoRa and additional capabilities. Support for specific functions depends on the MeshCore wrapper.

### STM32WL

A microcontroller with an integrated sub-GHz radio. The board still needs matching, RF switching, and a reference oscillator.

## RadioLib and wrappers

MeshCore uses a radio abstraction, commonly implemented over RadioLib. Custom wrappers map chip differences into operations such as:

- `begin`;
- `startSendRaw`;
- `recvRaw`;
- `isReceiving`;
- `getLastRSSI/SNR`;
- `getEstAirtimeFor`;
- noise-floor calibration;
- AGC reset.

Compatibility depends not only on the RadioLib version, but also on wrapper patches, board parameters, and wiring.

## TCXO and frequency stability

A TCXO provides better frequency stability, especially over temperature. An incorrect control voltage or startup delay can cause complete loss of communication or unstable RX.

A low-cost crystal may drift more. Narrow bandwidths and some high-SF profiles impose tighter frequency-error requirements; outdoor temperatures may reveal a problem that is invisible on the bench.

## RF switch

Many boards use a separate switch for TX and RX. Incorrect pin assignments or timing can cause:

- transmission into a disconnected path;
- the receiver being isolated from the antenna;
- a PA operating without a load;
- TX energy damaging the LNA;
- reception of only very strong signals.

The board definition must match the exact hardware revision.

## Moving a network to a new profile

A safe sequence is:

1. inventory every repeater and client;
2. verify frequency, BW, SF, and CR support;
3. check regulatory limits;
4. record current settings;
5. update firmware for protocol compatibility;
6. arrange temporary windows or physical access;
7. migrate backbone repeaters;
8. verify connectivity;
9. migrate edge nodes;
10. remove temporary bridges.

Do not change the only remote repeater through which the remaining nodes are managed before establishing another access path.

## Post-configuration checks

- `get radio`;
- `get tx`;
- `get radio.rxgain`;
- `ver` and `board`;
- a zero-hop advert;
- a bidirectional packet test;
- RSSI and SNR;
- direct path and ACK;
- RX-error statistics;
- actual output power and EIRP.

## Related articles

- [LoRa Modulation and Parameters](/wiki/lora-modulation-and-parameters)
- [Compatibility and Migration](/wiki/compatibility-and-migration)
- [Antennas and the RF Chain](/wiki/antennas-and-rf-chain)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/tree/main/src/helpers/radiolib>
- <https://github.com/jgromes/RadioLib>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
