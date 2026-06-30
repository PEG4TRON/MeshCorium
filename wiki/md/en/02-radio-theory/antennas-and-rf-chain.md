# Antennas and the RF Chain

The radio chip is only one part of a link. Between its RF pin and free space are a matching network, RF switch, filters, connectors, cable, and antenna. On receive, the same chain works in reverse. A fault in any one element can consume all of the benefit from a high SF or high transmit power.

## The antenna as a matched system

An antenna converts current in a conductor into an electromagnetic field and back again. It is designed for a specific frequency range and installation environment. A product labeled “868/915 MHz antenna” is not guaranteed to remain tuned identically inside an enclosure, on a metal mast, and in a user's hand.

Important properties are:

- resonant frequency;
- input impedance;
- matched bandwidth;
- gain;
- radiation pattern;
- polarization;
- efficiency.

**Gain** does not create energy. An antenna redistributes radiation by direction. A high-gain vertical collinear antenna normally compresses the vertical lobe: it may improve a horizontal path while making communication worse to a node far above or below it.

## 50 Ω and matching

Most LoRa modules, cables, and instruments are designed for 50 Ω systems. A mismatched load reflects part of the power back toward the source.

Common indicators are:

- **Return Loss** — how much weaker the reflected signal is than the incident signal;
- **SWR/VSWR** — the ratio of standing-wave maxima and minima;
- **S11** — the complex reflection coefficient measured with a VNA.

Low SWR does not guarantee high radiation efficiency. A 50 Ω resistor has perfect matching but is not a useful antenna. Matching, radiation pattern, and real field performance must be evaluated together.

## Ground plane and counterpoise

A quarter-wave monopole uses a conductive surface or counterpoise as the other half of the antenna system. A small PCB, battery, and cable can become part of the antenna. Changing the enclosure or wire length shifts the tuning.

For a fixed node:

- use a design with a defined ground plane;
- keep the radiator away from nearby metal;
- preserve the specified distance from the mast;
- avoid routing the feed cable along the active part of the antenna unless required by the design;
- measure the antenna in its installed configuration.

## Polarization

Vertical polarization is common for terrestrial links. Two vertical antennas minimize polarization loss. A portable radio lying horizontally can lose a significant part of the margin.

Reflections partially change polarization, so an urban link may continue to work but become unstable. Stationary nodes should use consistent orientation.

## Cable loss

Coaxial loss increases with frequency and cable length. A thin pigtail is convenient inside an enclosure, but poor for a long rooftop run. If antenna gain is `+5 dBi` and the cable loses `5 dB`, the result is nearly the same as a zero-gain antenna mounted directly at the radio.

Practical rules:

- place the radio close to the antenna;
- use a short cable;
- select cable using its loss specification at the operating frequency;
- include every adapter in the budget;
- weatherproof outdoor joints;
- do not apply side load to U.FL/IPEX connectors.

Moisture inside a connector changes impedance and causes corrosion. Protect outdoor joints with self-amalgamating tape or a proper sealed assembly without trapping water inside.

## Connectors

- **SMA** and **RP-SMA** look similar but use different center contacts. A wrong pair may screw together mechanically without making electrical contact.
- **U.FL/IPEX** is rated for a limited number of mating cycles and is easily damaged by side loading.
- adapters add small losses and additional failure points;
- a cheap “868/915 MHz” cable without a data sheet may have unpredictable attenuation.

Before enabling the transmitter, verify that the antenna is connected to the correct port. Transmitting into an open circuit can damage an external PA and some modules.

## Transmit chain

A typical chain is:

```text
LoRa transceiver → matching → PA → filter → RF switch → connector → cable → antenna
```

Not every board includes every block. An external PA increases conducted power but requires:

- correct enable timing;
- a power supply with sufficient current capacity;
- harmonic filtering;
- the correct `set tx` drive level;
- EIRP accounting;
- thermal management.

Setting maximum `tx` on a module with an additional amplifier may exceed the PA's safe input or the legal EIRP. The official CLI explicitly warns that the parameter controls the LoRa chip level; total output depends on the board.

## Filters

A low-pass or band-pass filter suppresses harmonics and strong out-of-band signals. It also has insertion loss, so it attenuates the wanted signal. A filter is useful when the improvement from interference rejection exceeds its loss.

At sites near FM, DMR, LTE, or a strong telemetry transmitter, the problem is often not exact frequency overlap but front-end overload. A narrow filter ahead of the LNA can significantly improve reception.

## Receive chain and LNA

An **LNA** amplifies a weak signal, but it also amplifies noise and can overload in the presence of strong signals. Built-in boosted gain (`radio.rxgain`) may improve sensitivity on supported SX12xx/LR1110 devices, but at a noisy site it may reduce dynamic range.

Signs of overload include:

- poor reception of weak MeshCore packets near a powerful transmitter;
- an abnormally high reported noise floor;
- better PDR after reducing gain or adding a filter;
- the problem follows the operating schedule of a nearby radio system;
- moving the node a few meters changes the result.

AGC adapts gain but cannot correct saturation that occurs before the controllable stage. MeshCore provides an AGC reset interval on supported implementations; use it after measurement, not as a universal fix.

## Built-in antennas and enclosures

PCB and ceramic antennas are sensitive to:

- the battery;
- a display shield;
- a USB cable;
- the user's hand;
- a metal enclosure;
- PCB orientation;
- ground-clearance quality.

When comparing boards, keep orientation and power mode identical. A USB cable can act as a counterpoise and temporarily improve or degrade the result.

## Lightning and static protection

A high outdoor antenna requires proper engineering controls:

- a grounded mast;
- a coaxial surge protector;
- a short bonding path to the equipotential system;
- protection on power and data lines;
- compliance with building and electrical codes.

A surge protector adds insertion loss, but protects equipment and people. An improvised high installation without safe grounding is more dangerous than having no repeater.

## Checking the RF chain

A minimum test sequence is:

1. visually inspect connectors and cable;
2. check continuity without shorting center conductor to shield where the design permits;
3. measure S11/VSWR with a VNA in the assembled state;
4. measure conducted power with a suitable attenuator and power meter or analyzer;
5. check spectrum and harmonics;
6. compare receive performance with a known-good node;
7. run a bidirectional packet test.

Never connect a high-power transmitter directly to a sensitive analyzer input without a correctly rated attenuator.

## Practical antenna selection

For a portable device, mechanical reliability and acceptable efficiency in multiple orientations matter most. For a repeater, priorities are:

- outdoor installation;
- a known radiation pattern;
- low cable loss;
- polarization matching the network;
- weather resistance;
- avoiding excessive gain that creates deep vertical nulls;
- compliance with allowed EIRP.

A “longer” antenna is not automatically better. It may be intended for a different band or contain a decorative coil without efficient matching.

## Related articles

- [Frequency, Power, and Link Budget](/wiki/frequency-power-and-link-budget)
- [Signal Propagation and Coverage](/wiki/propagation-and-coverage)
- [MeshCore Radio Profiles and Hardware](/wiki/radio-profile-and-hardware)
- [Interference and Radio Reception Problems](/wiki/interference-and-radio-problems)

## Sources

- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://www.etsi.org/technologies/short-range-devices>
