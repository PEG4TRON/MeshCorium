# Statistics and Logging

MeshCore diagnostics should be based on counters and raw events rather than a subjective statement that it “used to work.” Firmware provides core, radio, and packet statistics, a neighbor table, and RX logging.

## Commands

```text
stats-core
stats-radio
stats-packets
clear stats
log start
log stop
log erase
log
neighbors
```

Some commands are serial-only. A remote request may return structured statistics through MeshCore request/response when supported by the role and ACL.

## Core statistics

They commonly include:

- battery millivolts;
- uptime;
- outbound-queue length;
- free packet count;
- debug and error flags.

### Battery

Low voltage affects more than shutdown:

- TX voltage sag reduces output or resets the MCU;
- a PA causes brownout;
- ADC calibration may be wrong;
- a solar node may behave differently at night.

Correlate battery readings with TX failures and reset reason.

### Uptime

Uptime reveals unexpected reboots. If a contact disappears periodically, compare reset reason and boot voltage.

### Queue length

A growing queue is an early sign of:

- congestion;
- exhausted duty budget;
- CAD reporting busy;
- a packet storm;
- an excessively slow radio profile;
- stuck TX.

One instantaneous value is insufficient. Record maximum and time series.

### Free packets

The packet pool is shared by RX, delayed inbound packets, and outbound packets. A low free count increases loss risk even when RF quality is good.

## Error flags

In the current dispatcher:

| Flag | Cause |
|---|---|
| `ERR_EVENT_FULL` | Packet-pool allocation failed |
| `ERR_EVENT_CAD_TIMEOUT` | Channel remained busy beyond the maximum duration |
| `ERR_EVENT_STARTRX_TIMEOUT` | Radio stayed outside RX for more than eight seconds |

`clear stats` resets counters and flags. Save a snapshot first.

## Radio statistics

The CLI describes:

- noise floor;
- last RSSI;
- last SNR;
- total airtime;
- receive errors.

The dispatcher separately accounts for TX airtime and receive airtime. Exact output depends on the role implementation.

### Last RSSI and SNR

These are values from the latest packet, not averages. Store them with a timestamp and sample count.

### Total airtime

The counter accumulates since boot or clear. To estimate observed duty cycle:

```text
observed duty = total_tx_airtime / observation_time
```

Convert units if the counter is in milliseconds. Compare with configured `dutycycle` and queue delays.

### RX errors

Definition depends on the wrapper: it may include CRC or header errors, parser failures, or hardware status. Record firmware version when comparing results.

## Packet statistics

Published statistics may include:

- received packets;
- sent packets;
- sent flood;
- sent direct;
- received flood;
- received direct;
- direct duplicates;
- flood duplicates;
- posted and post-push counters for server roles.

Not every role implements every counter identically.

## Derived metrics

### Flood duplication factor

```text
dup_factor = flood_duplicates / unique_flood_received
```

Some duplication is normal in dense coverage. A rise after adding a repeater suggests excessive overlap or poor `txdelay`.

### Forwarding ratio

```text
forward_ratio = sent_flood / received_flood
```

Interpret it in light of local destinations, duplicates, limits, and region denies.

### Direct-success proxy

```text
ACK_received / direct_messages_sent
```

Exclude payloads that do not expect ACKs.

### Queue pressure

Record:

- average queue depth;
- maximum queue depth;
- time above a threshold;
- minimum free packet count;
- drops and full flags.

### Airtime per useful message

```text
TX airtime / confirmed user messages
```

An increase suggests retries, flood overhead, or service traffic.

## RX logging

```text
log start
log stop
log
log erase
```

Internal log storage is limited. Long captures can:

- fill flash;
- increase flash wear;
- alter timing;
- contain sensitive metadata;
- consume CPU and I/O.

Use a bounded capture window and export through serial.

## Recommended log fields

A minimum packet record should contain:

- local timestamp;
- RX or TX;
- raw length;
- payload type;
- route F or D;
- path size and count;
- short source/destination hashes where applicable;
- RSSI and SNR;
- packet hash;
- action: local, forward, or drop;
- drop reason;
- scheduled delay;
- queue depth.

Raw ciphertext can be useful for protocol debugging, but remains sensitive traffic metadata.

## Clock synchronization

Correlating several repeaters requires synchronized clocks. CLI:

```text
clock
clock sync
time <epoch_seconds>
```

If clocks diverge, forwarding order cannot be reconstructed precisely. For millisecond analysis, external synchronization and a known offset matter more than whole-second Unix timestamps.

## Baseline collection

Before a change, save:

- firmware version;
- board;
- radio profile;
- routing settings;
- region tree;
- uptime;
- counters;
- queue and free counts;
- noise floor;
- 10–30 minutes of logs under normal load.

Repeat the same observation period after the change.

## Common patterns

### Flood congestion

- `recv_flood`, `sent_flood`, and duplicates rise quickly;
- queue grows;
- direct ACKs are delayed;
- airtime is high;
- CAD timeouts may appear.

### RF interference

- high noise floor;
- rising CRC or RX errors;
- sent counts normal while receive counts fall;
- queue may remain small.

### Broken direct path

- direct sent count grows;
- no ACK;
- flood and zero-hop behavior otherwise normal;
- path reset fixes it.

### Packet-pool exhaustion

- free count approaches zero;
- `ERR_EVENT_FULL` appears;
- bursts disappear;
- delayed queue, large `rxdelay`, or a storm is present.

### Radio stuck

- `STARTRX_TIMEOUT` appears;
- RX counters stop increasing;
- reboot temporarily repairs it;
- inspect IRQ, RF switch, and wrapper.

## Export and analysis

For long-term monitoring, store CSV or JSON outside the node:

```text
timestamp,node,uptime,noise,rssi,snr,tx_airtime,rx_flood,tx_flood,dup_flood,queue,free,flags
```

Plot separately:

- noise floor;
- queue depth;
- airtime rate;
- duplicate rate;
- ACK ratio;
- reboot events.

Do not create one composite score without retaining raw metrics.

## Privacy

Logs may reveal:

- public-key prefixes;
- route topology;
- active times;
- message lengths;
- locations from adverts;
- administrative operations.

Limit access, retention, and publication.

## Related articles

- [RSSI, SNR, and Link Quality](/wiki/rssi-snr-and-link-quality)
- [Interference and Radio Reception Problems](/wiki/interference-and-radio-problems)
- [Channel Access, Queues, and Delays](/wiki/channel-access-queues-and-delays)
- [Capacity and Scaling](/wiki/capacity-and-scaling)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.h>
