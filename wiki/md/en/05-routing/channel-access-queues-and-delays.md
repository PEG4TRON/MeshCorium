# Channel Access, Queues, and Delays

MeshCore has no central airtime scheduler. Every node decides independently when to transmit. CAD, randomized delays, queues, priorities, and a duty-cycle budget reduce conflicts, but do not provide deterministic guarantees.

## Half-duplex scheduler

The dispatcher main loop is conceptually:

```text
radio loop
→ finish current TX
→ AGC and noise-floor maintenance
→ delayed inbound queue
→ new RX packets
→ outbound queue
```

While `outbound` is transmitting, other radio activity waits for completion or timeout. After TX, the radio returns to receive mode.

## Channel Activity Detection

CAD looks for LoRa chirp structure. In the MeshCore abstraction, the radio reports `isReceiving()`. If the channel is busy:

- the start of the busy period is recorded;
- the next check is delayed;
- `ERR_EVENT_CAD_TIMEOUT` is set after the maximum duration;
- transmission may be forced so a stuck busy state cannot block the queue forever.

Base-dispatcher defaults are:

```text
CAD retry delay: 200 ms
CAD busy max:    4000 ms
```

A specific role may override the delay with a randomized value.

## Why CAD is not Ethernet-style CCA

LoRa CAD normally detects preamble or symbol structure, not all RF energy. Possible failures include:

- another LoRa profile is not detected;
- narrowband interference does not look like LoRa;
- a hidden node cannot be heard by the sender;
- a strong adjacent signal overloads the receiver without valid CAD;
- two nodes finish CAD at the same time.

CAD reduces risk, but packet collision remains a normal event in a radio mesh.

## Hidden nodes

```text
A ----> B <---- C
```

A and C are both audible at B, but cannot hear each other. Each believes the channel is free and transmits, so packets overlap at B.

Random delay helps statistically. Other mitigations are:

- reduce synchronization of traffic;
- add a repeater audible to both sides;
- change placement;
- separate channels or scopes;
- reduce airtime;
- use retries with jitter.

## Capture effect and near-far behavior

If one packet is much stronger than another, a receiver may decode the stronger packet. This capture effect is not reliable and can create unfairness: a nearby high-power node suppresses a distant node.

Excessive TX power in a dense mesh can reduce total delivery performance. Power control matters for network fairness as well as battery and regulation.

## Outbound queue

`PacketManager` provides:

- `queueOutbound(packet, priority, scheduled_for)`;
- `getNextOutbound(now)`;
- total and free counts;
- removal of entries;
- an inbound delayed queue.

The queue stores pointers into a packet pool. If the pool is empty, `obtainNewPacket` sets `ERR_EVENT_FULL`. An incoming packet may also be lost when no object is available.

## Priorities

In `DispatcherAction`, priority is encoded in the high bits and delay in the lower 24 bits. Current behavior includes:

- direct forwarding receives high priority;
- flood priority degrades as path count grows;
- an application can assign its own priority;
- the scheduled time must arrive before selection.

Priority orders ready packets. It cannot interrupt a current TX and does not bypass the duty budget.

## `txdelay`

Flood-delay factor is `0..2`, with documented default `0.5`. The window is scaled relative to estimated packet airtime. A longer packet deserves a wider window because a collision is more expensive.

If too small:

- several repeaters transmit almost together;
- duplicate count rises;
- the packet may fail at the next hop.

If too large:

- route discovery slows;
- ACKs may time out;
- the queue grows;
- users may resend manually.

## `direct.txdelay`

The direct factor defaults to `0.2`. Normally there is one next hop, but delay still provides turnaround time and reduces contention with other packets.

If short path hashes collide, two nodes may both believe they are next. A longer delay reduces collision probability but does not repair incorrect routing; use a larger path-hash size.

## `rxdelay`

Experimental receive delay ranges from `0..20`, default `0`. The dispatcher obtains a packet score from the radio wrapper and calculates a nonlinear delay capped at 32 seconds.

A strong packet is processed immediately; a weaker packet waits. The goal is to let a higher-quality flood branch win and suppress weak duplicates.

Measure:

- median latency;
- P95 and P99 latency;
- number of forwarded flood packets;
- PDR at edge nodes;
- ACK timeout rate;
- queue depth.

## Duty-cycle budget

Before selecting a packet, the dispatcher refills `tx_budget_ms`. If the budget is below a fraction of estimated maximum packet airtime, TX is delayed.

After `TX_DONE`, actual time is deducted. If little remains, the next allowed transmit time is calculated.

Consequences:

- bursts exhaust budget quickly;
- even a high-priority ACK must wait;
- one long packet can delay several short packets;
- queue length is an early overload indicator;
- a 50% software default does not make it safe for a node to occupy half of a shared network's airtime.

## Delayed inbound queue

A delayed flood packet occupies an object from the pool. A large stream of weak packets may fill the pool before processing. `rxdelay` and pool size are therefore related.

On exhaustion:

- the radio receives bytes but no packet object can be allocated;
- a warning or error is set;
- the packet is lost before routing or application processing.

## Radio-stuck detection

The dispatcher tracks whether the radio remains outside RX for more than eight seconds. If so, it sets `ERR_EVENT_STARTRX_TIMEOUT`. Possible causes are:

- stuck TX or IRQ state;
- wrapper failed to return to RX;
- incorrect RF-switch state;
- hardware failure;
- a long blocking operation.

The error flag does not necessarily recover the radio automatically; inspect logs and the board implementation.

## Interference threshold and noise calibration

```text
get int.thresh
set int.thresh <value>
```

The value is passed to `triggerNoiseFloorCalibrate`. Its semantics depend on the wrapper and chip. Default `0.0` usually means disabled or default behavior.

Do not copy a threshold between boards without measurement; RSSI offsets and calibration differ.

## AGC reset interval

```text
get agc.reset.interval
set agc.reset.interval <seconds>
```

The interval is rounded down to a multiple of four, and `0` disables it. Reset may help after strong interference, but creates a moment when the receiver is not ready. Use it only for confirmed AGC deafness.

## Symptom-based tuning

| Symptom | Check |
|---|---|
| High flood duplicate count | `txdelay`, density, hidden nodes |
| Slow direct delivery | Duty budget, queue, `direct.txdelay` |
| Edge nodes disappear after enabling `rxdelay` | Receive delay too large |
| `ERR_EVENT_FULL` | Packet pool, queue, packet storm |
| `CAD_TIMEOUT` | Continuous activity, stuck RX, interference |
| `STARTRX_TIMEOUT` | Wrapper, IRQ, RF switch, blocking code |
| ACK arrives after UI timeout | Queue priority, airtime, multi-hop delay |

## Tuning method

Change one parameter at a time:

1. save baseline counters;
2. define repeatable test traffic;
3. measure PDR, latency, duplicates, and queue depth;
4. change `txdelay` or another single setting;
5. repeat the same test;
6. check edge links and busy-hour behavior;
7. restore baseline if results worsen.

Changing SF, power, delay, and regions simultaneously prevents attribution of the result.

## Related articles

- [The LoRa Frame and Radio Operating Cycle](/wiki/lora-frame-and-radio-cycle)
- [Flood Routing](/wiki/flood-routing)
- [Statistics and Logging](/wiki/statistics-and-logging)
- [Interference and Radio Reception Problems](/wiki/interference-and-radio-problems)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
