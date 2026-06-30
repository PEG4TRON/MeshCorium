# Frequency, Power, and Link Budget

Radio range is not determined by transmit power alone. A signal passes through a chain: transmitter → cable → antenna → free space → antenna → cable → receiver. Every element adds gain or loss. A **link budget** combines them into one calculation and shows whether the signal remains above receiver sensitivity with an adequate margin.

## Frequency and wavelength

Frequency `f` is the number of cycles per second. Wavelength is approximately:

```text
λ = c / f
```

where `c` is the speed of light. A convenient estimate is:

```text
λ, m ≈ 300 / f, MHz
```

Examples:

| Frequency | Wavelength |
|---:|---:|
| 433 MHz | about 0.69 m |
| 868 MHz | about 0.35 m |
| 915 MHz | about 0.33 m |
| 2.4 GHz | about 0.125 m |

Wavelength affects physical antenna size, diffraction, cable loss, and penetration through obstacles. A lower frequency does not guarantee greater range, but under otherwise equal conditions it usually bends around obstacles more effectively and requires a larger antenna.

## dB and dBm

A **decibel** (`dB`) is a relative logarithmic quantity. It is useful because gains and losses can be added directly.

- doubling power ≈ `+3 dB`;
- halving power ≈ `−3 dB`;
- multiplying by ten = `+10 dB`;
- dividing by ten = `−10 dB`.

**dBm** is absolute power relative to 1 mW:

```text
P(dBm) = 10 · log10(P(mW))
```

Reference values:

| dBm | Power |
|---:|---:|
| 0 dBm | 1 mW |
| 10 dBm | 10 mW |
| 14 dBm | about 25 mW |
| 20 dBm | 100 mW |
| 22 dBm | about 158 mW |
| 30 dBm | 1 W |

`set tx 22` configures the LoRa chip. If the board includes an external PA, actual power at the antenna connector may be higher. Conversely, imperfect matching and protection circuitry may reduce it.

## dBi, dBd, ERP, and EIRP

**dBi** expresses antenna gain relative to an ideal isotropic radiator. **dBd** expresses it relative to a half-wave dipole. The approximate relationship is:

```text
0 dBd ≈ 2.15 dBi
```

**EIRP** includes transmitter output power, feeder loss, and antenna gain:

```text
EIRP = TX power − cable loss − connector loss + antenna gain
```

For example:

```text
14 dBm − 2 dB + 5 dBi = 17 dBm EIRP
```

Regulatory limits are often specified as EIRP or ERP. Installing a higher-gain antenna may therefore require lowering `tx`.

## Receiver sensitivity

Sensitivity is the minimum signal level at which a receiver achieves a specified error rate. For LoRa it depends on:

- bandwidth;
- spreading factor;
- coding rate;
- radio-chip implementation;
- temperature and frequency error;
- board and power quality;
- the PER criterion used in the data sheet.

One sensitivity value cannot be used for every LoRa profile. Narrower bandwidth and higher SF generally improve sensitivity, but increase airtime.

## Basic link-budget calculation

The maximum allowable path loss can be estimated as:

```text
Lmax = Ptx + Gtx − Ltx + Grx − Lrx − Sensitivity
```

where:

- `Ptx` is transmitter power in dBm;
- `Gtx` and `Grx` are antenna gains in dBi;
- `Ltx` and `Lrx` are cable and connector losses in dB;
- `Sensitivity` is the negative receiver sensitivity value in dBm.

Example:

```text
Ptx          = 14 dBm
Gtx          =  2 dBi
Ltx          =  2 dB
Grx          =  2 dBi
Lrx          =  1 dB
Sensitivity  = -130 dBm

Lmax = 14 + 2 - 2 + 2 - 1 - (-130) = 145 dB
```

145 dB is the theoretical loss limit at sensitivity. A production link must not be designed right at that limit.

## Fade margin

**Fade margin** is reserve for changes in the environment. A fixed, clear line may need one margin; a forest, city, or mobile node may require much more.

Subtracting a 15 dB margin from the previous 145 dB leaves 130 dB of permissible calculated path loss. That reserve covers some of the following effects:

- rain and wet vegetation;
- changes in antenna position;
- multipath fading;
- noise-floor variation;
- temperature-related frequency drift;
- aging and moisture in connectors.

Link margin can be measured as the difference between actual received signal level and the threshold of reliable operation. For LoRa, however, RSSI, SNR, and PDR should be considered together rather than relying on RSSI alone.

## Free-space path loss

Free-space path loss is:

```text
FSPL(dB) = 32.44 + 20·log10(dkm) + 20·log10(fMHz)
```

The formula assumes free space, matched antennas, and no obstacles. It does not account for terrain, Fresnel-zone obstruction, buildings, or noise.

At a fixed distance, a higher frequency increases FSPL. Real links may behave differently because antenna dimensions, allowed power, and local interference also change.

## Why more power often does not solve the problem

An extra `+3 dB` is only twice the power. If a wall, forest, or polarization mismatch causes 20 dB of additional loss, raising power from 14 to 17 dBm changes very little.

More effective actions are often:

- raise the antenna;
- clear the Fresnel zone;
- remove a long, lossy cable;
- correct antenna polarization;
- reduce local interference;
- place a repeater where real radio visibility exists;
- choose a more appropriate LoRa profile.

## Bidirectional links

MeshCore often requires not only delivery of the original packet, but also a returned path or ACK. A link can be asymmetric because of:

- different board output powers;
- different antennas and cables;
- an external PA on only one side;
- different local noise floors;
- different installation heights;
- receiver overload from a strong local transmitter.

If B hears A well, that does not prove A hears B well. Trace data and bidirectional statistics are needed to verify both directions.

## Practical calculation table

For every critical link, build a table like this:

| Element | Value |
|---|---:|
| TX power at the connector | ... dBm |
| TX cable loss | ... dB |
| TX antenna gain | ... dBi |
| Calculated path loss | ... dB |
| RX antenna gain | ... dBi |
| RX cable loss | ... dB |
| Expected RSSI | ... dBm |
| Profile sensitivity | ... dBm |
| Margin | ... dB |

Then verify the calculation using real packets rather than an unmodulated carrier. PDR, ACK delivery, and route stability at different times of day are what matter.

## Related articles

- [Signal Propagation and Coverage](/wiki/propagation-and-coverage)
- [Antennas and the RF Chain](/wiki/antennas-and-rf-chain)
- [RSSI, SNR, and Link Quality](/wiki/rssi-snr-and-link-quality)
- [Network Design and Repeater Placement](/wiki/network-design-and-repeater-placement)

## Sources

- <https://www.semtech.com/lora/what-is-lora>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- <https://www.etsi.org/technologies/short-range-devices>
