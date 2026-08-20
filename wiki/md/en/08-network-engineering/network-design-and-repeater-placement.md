# Network Design and Repeater Placement

A repeater should create new, reliable links rather than merely increase the number of radios at one location. Height, Fresnel-zone clearance, noise floor, and the bidirectional link budget usually matter more than maximum transmit power.

![Repeater placement](/attachments/en/repeater-placement.svg?v=2)

## Start with requirements

Before choosing a rooftop or mast, define:

- the required coverage area;
- the number of users and sensors;
- critical communication directions;
- acceptable latency;
- required delivery probability;
- required autonomy;
- whether emergency traffic must be supported;
- permitted frequency, EIRP, and duty cycle;
- how the site can be serviced physically.

A network for ten hikers and a network for one hundred fixed sensors have different constraints even when they use the same radio profile.

## Topology types

### Sparse mesh

Nodes are far apart and each repeater is critical. The advantage is little duplicate traffic. The disadvantages are single points of failure and long paths.

A sparse network needs:

- a large fade margin;
- backup power;
- at least two independent directions through the backbone where possible;
- monitoring of every hop.

### Dense mesh

Many links overlap. The advantage is the availability of alternative paths. The disadvantages are flood amplification, collisions, and hash collisions.

A dense network needs:

- direct routing;
- regions;
- a sensible `txdelay` value;
- infrequent adverts;
- removal or disabling of repeaters that add no useful connectivity.

### Linear chain

This topology is common in valleys, along roads, and in tunnels. One failed node can split the network. Add bypass links or two independently placed nodes at critical points.

### Star-like topology

A high central repeater hears many edge nodes. This is convenient, but it creates a bottleneck and a single RF point of failure. A second hub should be at another site, not on the same mast and power supply.

### Mesh islands

Local groups may be connected by one weak or infrequent bridge hop. Traffic between islands should be scoped; otherwise every flood crosses all local areas.

## Choosing a site

A good site:

- has radio visibility in the required directions;
- is above local obstructions;
- has a low noise floor;
- allows a short RF cable;
- has safe power and grounding;
- is accessible for maintenance;
- is not next to a powerful transmitter unless suitable filtering is installed;
- is protected from water and temperature extremes.

A high but noisy broadcast site can perform worse than a lower, quiet site.

## Height and Fresnel-zone clearance

Raising an antenna by 5–10 metres often helps more than adding `+3 dB` of transmit power. Greater height can:

- establish line of sight;
- clear the Fresnel zone;
- reduce building and vegetation loss;
- enlarge the collision domain.

The last point is important. A very high repeater may hear several dense regions and participate in every flood. Coverage and capacity must therefore be optimised together.

## Antenna pattern

A high-gain omnidirectional antenna does not radiate equally in every direction. Its vertical beam becomes narrow. A repeater on a hill can place clients below it in a pattern null.

For a point-to-point backbone link, a directional antenna:

- increases link budget;
- rejects noise from other directions;
- reduces the collision domain;
- requires accurate alignment;
- is unsuitable as a general local repeater unless a second radio or antenna is used.

## Long cable or radio near the antenna

Long coaxial cable consumes antenna gain and can pick up interference. It is often preferable to place the radio in a weatherproof enclosure near the antenna and run power or data down the structure, provided that:

- the enclosure tolerates the temperature range;
- power is surge-protected;
- condensation is controlled;
- remote recovery is possible;
- the MCU and radio cannot overheat in direct sunlight.

## Power system

### Mains power

Use a UPS, surge protection, and a safe shutdown strategy. Verify that the supply does not brown out at maximum transmitter or external-PA current.

### Solar power

A simplified daily energy budget is:

```text
Eday = RX_current · 24 h + TX_current · TX_hours + MCU/peripherals
```

A repeater normally receives continuously. It is incorrect to calculate the system only from its relatively infrequent transmissions. Solar design must account for:

- the worst winter month;
- several consecutive cloudy days;
- reduced battery capacity at low temperature;
- self-discharge;
- charger efficiency;
- battery ageing.

Power-saving sleep reduces availability and requires an explicit protocol design rather than being enabled casually.

## Weatherproofing

Use:

- an enclosure with a suitable IP rating;
- cable glands facing downward;
- drip loops;
- a vent membrane to control condensation;
- UV-resistant cable;
- sealed RF connectors;
- corrosion-compatible metals;
- lightning protection;
- strain relief.

A perfectly sealed enclosure can still accumulate condensation from moist air trapped during assembly.

## Redundancy

A backup route should be independent in more than name. Prefer:

- a different site;
- a different power source;
- a different RF path;
- different cable and antenna hardware;
- a different access operator where practical.

Two repeaters on one mast and one UPS do not protect against lightning, a site outage, or common interference.

## Backbone and edge roles

Distinguish between:

- **backbone repeaters** — stable, elevated nodes linking areas;
- **edge repeaters** — nodes providing local user coverage;
- **mobile repeaters** — temporary coverage extensions.

Direct paths through the backbone should remain stable. A mobile repeater should not be the only bridge between two areas.

## Frequency and profile planning

One MeshCore segment needs a common radio profile. A large deployment may use several profiles connected by an application-level bridge, but this complicates:

- identity mapping;
- loop prevention;
- duplicate suppression;
- channel-secret management;
- monitoring;
- regulatory compliance.

Use regions and direct routing first. Splitting frequencies is justified when there is measured airtime congestion or persistent interference.

## Pre-deployment survey

1. Select candidate sites using terrain profiles.
2. Measure spectrum occupancy and noise at each site.
3. Install temporary nodes at the intended height.
4. Run bidirectional packet tests.
5. Collect RSSI, SNR, and PDR for at least several hours.
6. Repeat tests during a busy period.
7. Build a graph of candidate links.
8. Choose a topology with reserve paths.
9. Estimate flood load.
10. Run a pilot before permanent installation.

## Link matrix

Create a table such as:

| From \ To | R1 | R2 | R3 | Edge A |
|---|---:|---:|---:|---:|
| R1 | — | PDR/SNR | ... | ... |
| R2 | ... | — | ... | ... |

Measure both directions independently. Use the matrix to identify:

- articulation points;
- links with low margin;
- excessively long routes;
- redundant sites that add no useful path.

## Acceptance test

After permanent installation:

- verify antenna VSWR;
- measure transmit power and EIRP;
- record the noise floor;
- perform zero-hop tests;
- perform flood discovery;
- obtain a direct path;
- run traces in both directions;
- send packets of several sizes;
- measure the ACK ratio;
- inspect queue length and airtime during a busy period;
- simulate the loss of one repeater;
- verify recovery and path reset.

## Node documentation

For every repeater, record:

- public key and name;
- role, firmware, and board;
- coordinates and altitude;
- radio profile;
- configured TX power and measured EIRP;
- antenna, cable, and filter details;
- power system;
- region policy;
- routing settings;
- normal neighbour baseline;
- serial recovery procedure;
- maintenance date.

Private keys and passwords belong in protected storage, not on a public map.

## When a repeater is unnecessary

Warning signs include:

- it does not make any new node reachable;
- it has the same neighbours as a nearby repeater;
- its flood-send count is high, but few useful paths pass through it;
- duplicate traffic increased after it was installed;
- the site is noisy and causes poor paths to win the first-packet race;
- the antenna installation is poor;
- it is mobile and repeatedly breaks cached paths.

Removing an unnecessary repeater can improve both latency and PDR.

## Related articles

- [Propagation and coverage](/wiki/propagation-and-coverage)
- [Link budget](/wiki/frequency-power-and-link-budget)
- [Capacity and scaling](/wiki/capacity-and-scaling)
- [Statistics](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://www.etsi.org/technologies/short-range-devices>
