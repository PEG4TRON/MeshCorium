# Signal Propagation and Coverage

A distance map is not a radio-coverage map. Height, terrain profile, Fresnel-zone clearance, obstacle materials, polarization, noise, and multipath all matter between two points. The same equipment may work over tens of kilometers across open terrain and fail after a few city blocks in dense construction.

## Line of sight

**Line of Sight** means there is no geometric obstruction between the antennas. That alone is not enough for a reliable link: a volume called the Fresnel zone surrounds the direct line. If a hill, roof, or trees intrude into it, diffraction and additional loss occur.

Radio visibility is also limited by Earth curvature. Raising both antennas is usually more effective than a small increase in power because it simultaneously:

- extends the radio horizon;
- reduces Fresnel-zone obstruction;
- places fewer buildings and trees in the path;
- reduces local screening by the enclosure and ground.

## Fresnel zone

A radio wave does not propagate as an infinitely thin ray. The first Fresnel zone is widest near the midpoint of the path. Its radius can be estimated as:

```text
r1 ≈ 17.3 · sqrt(d1 · d2 / (f · D))
```

where distances `d1`, `d2`, and `D` are in kilometers and frequency `f` is in GHz.

The zone need not be completely clear, but substantial obstruction increases loss and instability. On a long route, even a visually small hill can block an important part of the volume.

## Diffraction

Diffraction allows part of the signal to bend around an obstacle edge. A link can therefore exist without optical visibility, but it has extra loss and is usually less stable:

- changes in vegetation moisture change attenuation;
- a small antenna movement changes the interference pattern;
- different frequencies diffract differently;
- a weak diffracted signal is more easily overwhelmed by local noise.

A positive SNR on one packet does not imply a large link margin.

## Reflections and multipath

In cities and indoors, the signal arrives over multiple paths after reflecting from walls, metal structures, ground, and water. Copies have different delays and phases, so they can reinforce or cancel one another.

LoRa is more tolerant of some multipath conditions than many narrowband systems, but it is not immune. Typical signs are:

- a large change after moving an antenna by tens of centimeters;
- high RSSI with poor SNR;
- one side of a building works while another does not;
- a moving node alternates between strong and weak spots.

Changing antenna position or height is often more useful than increasing power.

## Vegetation

Leaves and branches absorb and scatter RF energy. Attenuation depends on:

- frequency;
- depth of the wooded section;
- moisture;
- season;
- canopy density;
- antenna height.

A link that works in winter may degrade noticeably in summer. Wet foliage after rain often adds loss. A critical repeater path should not be evaluated in only one season.

## Buildings and materials

Materials have different attenuation:

- timber and drywall are usually easier to penetrate;
- brick and concrete are worse;
- reinforced concrete adds shielding from steel reinforcement;
- energy-efficient windows may contain metallic coatings;
- metal roofs and shipping containers behave as shields;
- elevator shafts and technical ducts create complex multipath.

Placing an antenna by a window does not always help if the glass is metallized. Moving the antenna outside over a short, good-quality cable often gives a larger improvement.

## Ground proximity and portable devices

A device at chest height or in a pocket is attenuated by the user's body. An antenna near the ground experiences:

- strong reflections;
- a distorted radiation pattern;
- Fresnel-zone obstruction;
- extra loss from vegetation and vehicles.

A field test must keep device position consistent. Comparing a packet sent with the antenna raised overhead to one sent from a pocket is not a fair equipment comparison.

## Polarization

Vertical whip antennas should be aligned consistently. Rotating one antenna by 90° creates polarization mismatch and can cause a substantial loss.

A mobile device constantly changes orientation, so the link needs reserve margin. A stationary repeater's antenna orientation should be mechanically fixed and rechecked after installation.

## Terrain and digital models

Useful inputs for preliminary design include:

- an elevation profile between sites;
- building and forest height;
- Earth-curvature correction for long routes;
- first-Fresnel-zone calculation;
- clutter or land-cover models.

A model does not know the local noise floor, a bad cable, actual tree height, or nearby metal structures. Calculations identify candidate sites; field testing confirms them.

## Repeater coverage area

Coverage should not be drawn as a perfect circle. Real coverage contains lobes and shadows. A good repeater site should provide:

- a reliable bidirectional link in at least two useful directions;
- low local interference;
- a safe antenna installation point;
- stable power;
- no long, lossy coaxial run;
- reserve SNR and PDR.

A repeater on a high site may hear too much of a dense network and increase flood load. Coverage must therefore be considered together with [network capacity](/wiki/capacity-and-scaling).

## How to measure a route

One RSSI value is not enough. A field test should include a series of messages or test packets:

1. fix the radio profile and TX power;
2. record antenna model, cable, and height;
3. transmit at least several dozen packets;
4. measure PDR in both directions;
5. retain RSSI and SNR for each received packet;
6. verify ACKs and the direct path;
7. repeat at a different time of day;
8. retest after rain or seasonal foliage change if the route is critical.

For a mobile route, a point map is useful, but each coordinate should be accompanied by time, orientation, and device state.

## Common mistakes

### “It is only two kilometers on the map”

A ridge, reinforced-concrete district, or deep shadow may lie between the sites. Geographic distance does not include obstacle loss.

### “RSSI is high, so the link is good”

High RSSI may include strong interference. Check SNR and PDR.

### “Use maximum power”

If the weak point is the receiver, cable, or Fresnel zone, more power helps little and may violate EIRP limits or overload nearby receivers.

### “The repeater hears clients, so clients will hear the repeater”

The link may be asymmetric. Test the reverse direction.

## Related articles

- [Frequency, Power, and Link Budget](/wiki/frequency-power-and-link-budget)
- [Antennas and the RF Chain](/wiki/antennas-and-rf-chain)
- [Interference and Radio Reception Problems](/wiki/interference-and-radio-problems)
- [Network Design and Repeater Placement](/wiki/network-design-and-repeater-placement)

## Sources

- <https://www.semtech.com/lora/what-is-lora>
- <https://www.etsi.org/technologies/short-range-devices>
