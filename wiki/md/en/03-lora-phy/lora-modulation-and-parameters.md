# LoRa Modulation and Parameters

LoRa uses Chirp Spread Spectrum: a symbol is encoded as a frequency shift of a wideband chirp signal. The receiver maps the chirp shift to a symbol number. This approach permits decoding at low signal-to-noise ratios, but it does not remove the constraints of shared bandwidth and airtime.

![LoRa parameter trade-offs](/attachments/en/lora-parameter-tradeoffs.svg?v=2)

## Chirp Spread Spectrum

A **chirp** is a signal whose frequency changes over time. In a basic LoRa symbol, the sweep spans the selected bandwidth. Information is represented by a cyclic shift of the chirp.

Advantages of CSS include:

- processing gain from long symbols and spread spectrum;
- resistance to narrowband interference;
- the ability to receive signals below the wideband noise floor in SNR terms;
- useful tolerance of frequency offset and multipath.

Limitations include:

- low useful data rate at high SF;
- long airtime;
- high cost of retransmissions;
- limited capacity in one channel;
- imperfect orthogonality between different spreading factors in a real receiver.

## Bandwidth

`BW` is the spectrum occupied by the LoRa signal. Supported values depend on the radio chip. The MeshCore CLI documents 7.8 to 500 kHz for `tempradio`, but not every board supports every combination.

A wider BW:

- shortens symbol duration;
- increases data rate;
- reduces airtime;
- admits more noise power;
- requires more free spectrum.

A narrower BW does the opposite. When comparing RSSI and noise floor, remember that a wider filter integrates more noise. Theoretical thermal noise rises by about 3 dB whenever BW doubles.

## Spreading Factor

`SF` determines the number of possible symbol states: `2^SF`. Symbol duration is:

```text
Tsym = 2^SF / BW
```

At 250 kHz BW:

| SF | Symbol duration |
|---:|---:|
| 7 | 0.512 ms |
| 9 | 2.048 ms |
| 11 | 8.192 ms |
| 12 | 16.384 ms |

Increasing SF by one roughly doubles symbol duration. The packet remains on air longer and network capacity falls.

A higher SF generally provides:

- more processing gain;
- a lower required SNR;
- better probability of decoding a weak signal;
- lower data rate;
- more airtime;
- a larger time window in which a collision can occur.

A high SF does not increase transmitter power or repair a poor antenna. It changes the encoding method.

## Coding Rate

LoRa adds Forward Error Correction. Modes are commonly written `4/5`, `4/6`, `4/7`, and `4/8`: one to four check bits are added for every four information bits.

In the MeshCore CLI, `cr` is the denominator, from `5` to `8`:

| CLI `cr` | LoRa CR |
|---:|---:|
| 5 | 4/5 |
| 6 | 4/6 |
| 7 | 4/7 |
| 8 | 4/8 |

More redundancy can correct some errors, but increases the number of payload symbols. Coding rate cannot recover a packet from a severe collision if the preamble or header was not detected.

## Symbol rate and bit rate

Symbol rate is:

```text
Rs = BW / 2^SF
```

An approximate raw bit rate is:

```text
Rb ≈ SF · Rs · 4/CRdenominator
```

This is not user-text throughput. The following overheads must be subtracted:

- preamble;
- PHY header;
- CRC;
- MeshCore header and path;
- MAC and encryption padding;
- ACKs;
- retransmissions;
- wait intervals and duty-cycle restrictions.

For a mesh, the relevant quantity is **useful end-to-end throughput**, which is further divided by the number of hops.

## Low Data Rate Optimization

With very long symbols, oscillator timing error has a larger effect on demodulation. Low Data Rate Optimization (`LDRO`, `DE`) changes internal coding to improve robustness for long symbols.

LDRO is often enabled automatically when `Tsym ≥ 16 ms`, but exact behavior depends on the radio library and chip. A mismatch between transmitter and receiver can break compatibility.

## Preamble

The preamble allows the receiver to:

- detect a LoRa signal;
- settle AGC;
- estimate frequency offset;
- synchronize to the start of the frame.

A longer preamble can help special sleep modes or unstable oscillators, but increases airtime linearly. It should not be lengthened without a reason in a normal always-listening MeshCore network.

## Sync word

The sync word separates logical networks at the PHY layer. With a different sync word, a receiver normally does not pass the payload to firmware. It is not cryptographic protection and does not prevent RF interference: another transmission still occupies spectrum and may overload the receiver.

## TX power

Power affects the signal level at every receiver. Increasing it:

- improves link budget;
- increases energy use;
- may exceed EIRP limits;
- raises the risk of overloading nearby receivers;
- increases interference to other band users;
- does not improve sensitivity in the reverse direction.

Power should be selected after antenna, placement, and profile design, not used as the first tuning method.

## Spreading-factor orthogonality

Different SF values are often called orthogonal. A laboratory receiver may separate signals using different SFs, but real orthogonality is limited by:

- power differences;
- frequency error;
- time overlap;
- RF-chain nonlinearity;
- receiver saturation;
- the implementation of the specific chip.

A nearby transmission with another SF must not be assumed harmless.

## Selecting parameters as a system

SF, BW, and CR cannot be optimized independently. For example:

- raising SF doubles airtime;
- halving BW doubles it again;
- stronger coding adds more symbols;
- a flood crossing four repeaters repeats that airtime at every hop.

A locally “long-range” setting can reduce the entire network's ability to deliver messages.

## Practical profile patterns

### Dense local network

Use a moderate SF and sufficient BW to keep airtime short. Obtain range through good repeater placement.

### Sparse network with long paths

A higher SF may be justified, but strict flood limits, infrequent adverts, and duty-cycle control become essential.

### Mobile nodes

SNR and timing margin are needed, but an excessively long packet is more exposed to channel changes during motion.

### Sensor network

Optimize for short payloads, randomized transmit times, and no unnecessary ACKs. Hundreds of high-SF devices can saturate a channel quickly.

## Compatibility checklist

For two nodes to exchange MeshCore packets, at least the following must match:

- frequency;
- bandwidth;
- spreading factor;
- coding rate;
- sync word;
- header and CRC mode;
- supported chip frequency range;
- MeshCore packet format and payload version.

Matching the first four parameters alone does not guarantee firmware compatibility.

## Related articles

- [The LoRa Frame and Radio Operating Cycle](/wiki/lora-frame-and-radio-cycle)
- [Airtime, Duty Cycle, and Capacity](/wiki/airtime-duty-cycle-and-capacity)
- [MeshCore Radio Profiles and Hardware](/wiki/radio-profile-and-hardware)
- [MeshCore, LoRa, and LoRaWAN](/wiki/meshcore-lora-lorawan)

## Sources

- <https://www.semtech.com/lora/what-is-lora>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1276>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- <https://github.com/jgromes/RadioLib>
