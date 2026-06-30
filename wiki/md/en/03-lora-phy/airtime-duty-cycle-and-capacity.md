# Airtime, Duty Cycle, and Network Capacity

Airtime is the period during which one packet's radio signal occupies the channel. In a mesh it is the basic unit of cost: every hop creates another transmission, flood routing creates multiple competing transmissions, and an ACK travels back in the opposite direction.

## Calculating airtime

Symbol duration is:

```text
Tsym = 2^SF / BW
```

Preamble duration is:

```text
Tpreamble = (Npreamble + 4.25) · Tsym
```

The number of payload symbols depends on:

- payload length;
- SF;
- CR;
- PHY CRC presence;
- explicit or implicit header;
- LDRO.

The total is:

```text
ToA = Tpreamble + Npayload_symbols · Tsym
```

Use the parameters of the actual build for an exact calculation. Online calculators often assume LoRaWAN and add a LoRaWAN frame size; for MeshCore, enter the actual serialized MeshCore packet length.

## Example for 250 kHz, SF11, CR 4/5

With an eight-symbol preamble, explicit header, and CRC, approximate airtime is:

| LoRa payload | Airtime |
|---:|---:|
| 20 bytes | about 330 ms |
| 50 bytes | about 575 ms |
| 100 bytes | about 944 ms |
| 184 bytes | about 1.56 s |

This is one radio transmission only. A packet crossing three repeaters is transmitted four times at different points in the network. In a flood, coverage areas overlap, so those transmissions compete inside the same collision domain.

## Useful length is smaller than the MeshCore payload limit

MeshCore documents a payload field up to 184 bytes. User text must also accommodate:

- destination and source hashes;
- cipher MAC;
- timestamp;
- flags and attempt number;
- block-cipher padding;
- the text itself.

A transport route adds 4 bytes of transport codes, while the path grows with hop count. Therefore “184 bytes” does not mean 184 text characters and does not produce the same airtime on every route.

Unicode characters use multiple UTF-8 bytes. An emoji may use four or more bytes when modifiers are included.

## End-to-end cost

A rough estimate is:

```text
E = ToAdata · Ntx_data + ToAack · Ntx_ack + ToAretry
```

`Ntx_data` is the actual number of radio transmissions for the data packet. For a direct route of `H` links without duplicates:

```text
Ntx_data = H
```

Here, a hop is a link between nodes. For flood traffic, the count depends on how many nodes actually retransmit, not only on the final route length.

## Duty cycle

Duty cycle is the fraction of time spent transmitting within an interval:

```text
Duty = TX_time / Total_time
```

At 1%, a device may transmit for 36 seconds per hour. Legal rules may use another accounting interval, LBT/AFA, dwell-time limits, or different sub-bands. Always check the applicable country and current regulations.

## `dutycycle` in MeshCore

The official CLI for firmware v1.15.0+ documents:

```text
get dutycycle
set dutycycle <1..100>
```

Examples from the documentation:

- `100` — no software limit;
- `50` — technical default;
- `10` — 10%;
- `1` — 1%.

**The 50% default is not a legal recommendation.** It is a firmware setting. Applicable limits in many license-exempt sub-bands may be far stricter.

## Legacy airtime factor

The `af` parameter is deprecated from v1.15.0. Its model is:

```text
after TX, remain silent for approximately ToA · af
long-term duty ≈ 1 / (1 + af)
```

Examples:

| `af` | Approximate duty |
|---:|---:|
| 1 | 50% |
| 2 | 33% |
| 3 | 25% |
| 9 | 10% |

The newer `dutycycle` setting is clearer, but during migration of older nodes check how the firmware converts stored values.

## Airtime budget in the dispatcher

The current dispatcher uses a refillable budget. Actual TX duration is deducted after each transmission. The budget refills over time in proportion to the configured duty cycle.

If little budget remains, the next transmission is delayed. This affects:

- ACK latency;
- outbound-queue length;
- remote CLI;
- room synchronization;
- behavior during a flood storm.

A software budget protects one node. It does not coordinate the aggregate duty cycle of all network devices.

## Capacity of one collision domain

The channel is theoretically available 100% of the time, but safe practical utilization is much lower because of:

- random collisions;
- hidden nodes;
- preamble detection and turnaround time;
- retries;
- unequal SNR;
- adverts and discovery;
- queue delays;
- duty-cycle rules.

At high load a nonlinear feedback loop appears: more packets cause more collisions, which cause more retries, which create still more packets. This is congestion collapse.

## Flood impact

A direct path with four hops creates four transmissions. A flood in a dense area may be heard by ten repeaters; random delay and duplicate suppression reduce the number of retransmissions, but several TX events may still occur.

Mechanisms that limit the cost include:

- `flood.max`;
- `flood.max.unscoped`;
- `flood.max.advert`;
- regions and transport codes;
- `txdelay`;
- `rxdelay`;
- loop detection;
- retaining a direct path.

## Advert intervals

An advert is useful for discovery and path updates, but it is control traffic. If each of 100 nodes sends a long flood advert every few minutes, the network spends a large portion of airtime without carrying user messages.

A stationary repeater does not need to prove its unchanged existence frequently. Select the interval based on:

- node mobility;
- contact-aging requirements;
- network density;
- route length;
- advert size;
- region scope.

## Evaluating a network

Collect the following over a representative period:

- `total_airtime` on every critical repeater;
- sent and received flood/direct counters;
- duplicate counters;
- queue length;
- ACK success rate;
- average packet size and hop count;
- advert and sensor-report intervals.

Then divide traffic into:

1. user traffic;
2. routing and discovery;
3. acknowledgments;
4. retries;
5. redundant duplicates.

Optimization should begin by reducing the last two categories, not by restricting useful messages.

## Reducing airtime

- use direct routing after discovery;
- shorten text and binary payloads;
- do not publish telemetry when the value has not changed;
- randomize sensor intervals;
- limit flood scope;
- reduce advert frequency;
- avoid unnecessarily high SF or strong CR;
- do not enable Multi-ACK without a reason;
- repair poor links that cause retries;
- separate independent areas by frequency or scope where allowed.

## Related articles

- [LoRa Modulation and Parameters](/wiki/lora-modulation-and-parameters)
- [Flood Routing](/wiki/flood-routing)
- [ACKs, Retries, and Multipart Packets](/wiki/acknowledgements-retries-and-multipart)
- [Capacity and Scaling](/wiki/capacity-and-scaling)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- <https://docdb.cept.org/document/845>
