# Interference and Radio Reception Problems

Poor reception is not always caused by a weak MeshCore signal. A receiver may be overloaded by a powerful neighboring system or by its own DC/DC converter, USB interface, or display. RSSI may then appear high while useful packets disappear.

## Co-channel interference

A transmitter uses the same frequency and bandwidth and overlaps a MeshCore packet. Sources include:

- another MeshCore network;
- LoRaWAN;
- Meshtastic or custom LoRa;
- a non-LoRa digital transmitter;
- an intentional jammer.

When packets overlap, the receiver may:

- decode the stronger one through capture effect;
- report a CRC error;
- fail to detect either;
- behave differently depending on SF and power difference.

## Adjacent-channel interference

A signal is nearby in frequency, but spectral skirts or limited receiver selectivity affect the channel. Risk is highest with:

- a close high-power transmitter;
- wide bandwidth;
- poor output filtering;
- a weak desired signal;
- an inexpensive front end without a band filter.

Moving the MeshCore frequency by a few tens of kilohertz may not help if the interferer overloads the entire LNA or mixer.

## Blocking and desensitization

**Blocking** occurs when a strong out-of-band signal reduces the ability to receive a weak wanted signal. It may not appear as in-channel RSSI, yet the gain stages are already saturated.

Example: a repeater shares a mast with a powerful VHF/UHF transmitter. Its high-gain antenna captures substantial energy, and the LoRa node becomes deaf even though desktop testing was successful.

Mitigations include:

- a band-pass filter;
- physical separation;
- antenna placement in a pattern null;
- a separate mast;
- disabling boosted gain;
- improved grounding and shielding;
- checking intermodulation products.

## Intermodulation

A nonlinear element mixes two strong signals and creates products such as:

```text
2f1 - f2
2f2 - f1
f1 + f2
```

One product may fall directly into the MeshCore channel even when the original transmitters are far away in frequency. Nonlinearity may occur in the receiver front end, a corroded connector, a PA, or another poor active device.

Diagnosis normally requires a spectrum analyzer and correlation with transmitter operating times.

## Wideband noise

A switching converter, USB 3 interface, HDMI cable, display ribbon, low-quality charger, or solar controller may raise the floor over a wide range.

Test sequence:

1. record noise floor with normal power;
2. unplug USB;
3. power from a battery;
4. disable display, GPS, Wi-Fi, and other peripherals;
5. disconnect the charger or solar controller;
6. compare spectrum and PDR.

If unplugging USB improves SNR by 10 dB, the problem is local to the installation rather than the route.

## Self-interference

A node can interfere with itself through:

- MCU clock harmonics;
- OLED or TFT refresh;
- GPS LNA or oscillator;
- BLE or Wi-Fi bursts;
- switching regulator;
- long unshielded wires;
- external-PA feedback.

Firmware may disable noisy peripherals during RX or TX, but this affects latency and requires board-specific integration.

## Receiver overload from local transmitters

Several radios at one site create near-field coupling. Even different frequencies can overload an LNA. Controls may require:

- antenna separation;
- calculated vertical or horizontal spacing;
- cavity or band filters;
- coordinated TX;
- shielding;
- measured isolation in dB.

A one-meter separation is not necessarily enough near a watt-level transmitter.

## AGC deafness

After a strong signal, AGC may remain in an unfavorable state. CLI:

```text
get agc.reset.interval
set agc.reset.interval <seconds>
```

`0` disables it; the interval is rounded to a multiple of four.

Use it only after confirming that failure follows a strong burst, comparing reception before and after a manual reset or reboot, selecting the longest practical interval, and checking for packet loss during reset.

This is a workaround, not a substitute for an RF filter.

## RX boosted gain

`radio.rxgain on` increases sensitivity, but can reduce headroom. It is useful at a quiet rural site. At a telecom site, `off` may produce better PDR even with a lower apparent RSSI.

Compare using a packet sequence, not one packet.

## `int.thresh`

The local interference threshold is passed to the wrapper's noise-floor calibration:

```text
get int.thresh
set int.thresh <value>
```

Units and semantics are implementation-specific. Do not configure it using another board's recipe. A wrong threshold can make the channel appear permanently busy or ignore real activity.

## Frequency error

Causes include:

- a poor crystal;
- incorrect TCXO configuration;
- temperature;
- a wrong reference frequency;
- board damage.

Signs include:

- one node cannot hear the network at narrow BW;
- communication changes during warm-up;
- behavior depends on temperature;
- the spectrum peak is offset;
- widening BW temporarily fixes it.

Measure with a frequency counter or spectrum analyzer, or compare against a reference radio.

## Antenna or RF-switch failure

Signs of an incorrect RF switch include:

- TX is visible only at very short range;
- RX receives only strong packets;
- a power meter shows low output;
- the receiver does not return after TX;
- the problem began after changing board variant.

Check pins, timing, DIO mapping, PA path, and the exact hardware revision.

## Collisions or RF noise?

### Collision pattern

- degradation during busy periods;
- rising duplicate counters;
- short packets work better than long packets;
- randomizing traffic helps;
- a spectrum display shows discrete LoRa bursts.

### Continuous-noise pattern

- noise floor is persistently high;
- disconnecting local electronics helps;
- changing frequency helps;
- packets fail even with one sender;
- the spectrum shows continuous or periodic emissions.

### Broken-route pattern

- zero-hop links are good;
- only one direct contact fails;
- path reset fixes it;
- trace stops at one hop.

## Tools

- MeshCore raw RX log;
- `stats-radio`;
- sequence-packet generator;
- SDR waterfall;
- spectrum analyzer;
- attenuator and signal generator;
- VNA for antenna and filter measurements;
- power meter;
- near-field probes;
- reference receiver.

An SDR waterfall is useful, but its own overload and dynamic-range limits must be considered.

## Diagnostic plan

1. verify radio profile and firmware;
2. run a short-range zero-hop test with attenuation;
3. compare a known-good antenna and cable;
4. measure noise floor;
5. disable local electronics;
6. collect RSSI/SNR/PDR series;
7. test another legal channel where permitted;
8. compare boosted-gain modes;
9. run trace;
10. measure spectrum and filtering;
11. only then change network-routing parameters.

## Reducing interference

- add a filter ahead of the receiver;
- shorten coax;
- improve grounding;
- shield digital electronics;
- add ferrite and common-mode suppression;
- plan frequencies;
- reduce TX power of nearby nodes;
- separate antennas;
- randomize sensor bursts;
- reduce airtime;
- relocate the repeater.

## Related articles

- [Antennas and the RF Chain](/wiki/antennas-and-rf-chain)
- [RSSI, SNR, and Link Quality](/wiki/rssi-snr-and-link-quality)
- [Channel Access, Queues, and Delays](/wiki/channel-access-queues-and-delays)
- [Statistics and Logging](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
