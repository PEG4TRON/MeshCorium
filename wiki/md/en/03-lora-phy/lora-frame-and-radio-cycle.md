# The LoRa Frame and Radio Operating Cycle

A MeshCore packet is not transmitted by itself. Firmware serializes it into a byte array and passes it to the radio driver. The LoRa transceiver adds the physical preamble, sync word, PHY header, and optional CRC.

![LoRa PHY frame](/attachments/en/lora-frame.svg?v=2)

## Two nested formats

It is useful to separate the layers:

```text
LoRa PHY frame
└── LoRa payload
    └── MeshCore packet
        ├── MeshCore header
        ├── transport codes
        ├── path
        └── MeshCore payload
```

A LoRa CRC failure normally means the MeshCore parser never receives a valid byte array. A MeshCore MAC failure happens later: the physical frame was received successfully, but encrypted data failed authentication.

## Preamble

The preamble is a sequence of chirps used by the receiver to detect a LoRa signal and synchronize. It is followed by special end-of-preamble symbols and the sync word.

A receiver may pass through these states:

1. listen to the channel;
2. detect a preamble;
3. validate the sync word;
4. demodulate the header;
5. receive the payload;
6. check the CRC;
7. produce an `RX_DONE` interrupt or an error.

A false preamble detection keeps the radio busy even when no complete packet is received.

## Sync word

The sync word helps filter frames from another logical network. It is not encrypted and is not a password. Devices using another sync word can still cause interference, and a spectrum or protocol analyzer can determine signal parameters.

If two independent MeshCore segments should not process each other's packets, consider frequency and bandwidth as well as the sync word. PHY separation reduces logical overlap, but both networks still share the same spectrum.

## Explicit and implicit headers

In **explicit header mode**, the PHY header contains information required to decode the payload, including its length. This is convenient for variable-length packets.

In **implicit header mode**, length and some parameters are agreed in advance. This reduces overhead but requires exact configuration matching.

The MeshCore build and radio wrapper define the mode. It should not be changed independently on one node.

## CRC

The LoRa payload CRC detects accidental transmission errors. It is not cryptographic integrity:

- CRC does not prevent deliberate forgery;
- a valid CRC does not authenticate the sender;
- a damaged frame is discarded before MeshCore processing;
- the MeshCore cipher MAC separately authenticates encrypted payload data.

An advert additionally carries an Ed25519 signature because its public data must be verifiable without a shared secret.

## Receive cycle

On an always-listening node, the radio enters RX after `begin()`. The driver polls IRQ state or receives a callback.

A typical processing sequence is:

```text
RX raw bytes
→ record RSSI/SNR
→ allocate a Packet from the pool
→ parse header/transport/path/payload
→ validate version and length
→ calculate score and estimated airtime
→ process now or place in delayed processing
→ release or queue for retransmission
```

In the current `Dispatcher.cpp`, a flood packet may be placed into a delayed inbound queue: a low-score copy waits while a stronger copy is processed first. If the network has already seen the same transmission during that delay, the later copy is suppressed as a duplicate.

## Transmit cycle

An outgoing packet first waits in the outbound queue. Before transmission, the dispatcher:

1. refills the duty-cycle budget;
2. checks whether `next_tx_time` has arrived;
3. checks whether the radio is receiving;
4. delays the attempt if CAD or busy state is reported;
5. serializes the MeshCore packet;
6. estimates a maximum TX duration;
7. calls `startSendRaw`;
8. waits for `TX_DONE` or timeout;
9. accounts for actual airtime;
10. returns the radio to RX.

During TX, the node cannot receive another packet. Long airtime therefore reduces not only throughput, but also the probability of hearing an incoming message.

## CAD and receiving state

Channel Activity Detection attempts to detect LoRa-like activity. In MeshCore, the transmit decision is tied to the busy or receiving state reported by the radio wrapper.

If the channel remains busy, transmission is delayed by `getCADFailRetryDelay()`. After a maximum busy duration, an error flag may be set and a forced attempt may occur so that a stuck radio state cannot block the queue forever.

CAD does not guarantee a collision-free transmission:

- a hidden node may not be audible to the sender;
- another transmission may start immediately after the check;
- another SF or BW may not always be detected;
- strong non-LoRa interference behaves differently;
- two nodes may choose similar random delays.

## IRQ events and errors

Typical hardware events are:

| Event | Meaning |
|---|---|
| `PREAMBLE_DETECTED` | A candidate LoRa signal was found |
| `HEADER_VALID` | The PHY header was decoded |
| `HEADER_ERROR` | The header is corrupt or incompatible |
| `RX_DONE` | The payload was received |
| `CRC_ERROR` | Payload CRC mismatch |
| `TX_DONE` | Physical transmission completed |
| `TIMEOUT` | The operation did not complete within its window |

Exact IRQ names differ across SX127x, SX126x, LR1110, and libraries. MeshCore accesses them through a radio-wrapper abstraction.

## AGC and noise-floor calibration

Automatic gain control selects gain for the current signal. Strong out-of-band signals may leave the front end in an unfavorable state. MeshCore has hooks for noise-floor calibration and AGC reset.

This does not mean a periodic reset is always beneficial. Frequent resets can create RX gaps. Configure them only after a repeatable test.

## Transmission timeout

The dispatcher estimates airtime and sets an expiry with margin. If `TX_DONE` does not arrive, the packet is released and an error is recorded. This prevents permanent blocking, but it does not guarantee an application-level retry.

User-message retry behavior is controlled by attempt and ACK logic, not by the radio timeout alone.

## Maximum size

A MeshCore packet must fit within `MAX_TRANS_UNIT`. Serialization includes:

- 1-byte header;
- 4-byte transport codes for a transport route;
- 1-byte path metadata;
- actual path bytes;
- payload.

A longer path consumes space and increases airtime. Even when the payload is within `MAX_PACKET_PAYLOAD`, the complete packet must still pass the total-length check.

## Layered diagnostics

| Symptom | Likely layer |
|---|---|
| No preamble or RSSI | Frequency, antenna, or radio state |
| Header error | Incompatible PHY or weak signal |
| CRC error | Collision, interference, or insufficient margin |
| MeshCore unsupported version | PHY received, protocol incompatible |
| Invalid path length | Corrupt or incompatible packet |
| MAC/decrypt failure | Key, hash collision, or damaged payload |
| No ACK | Forward or return route, destination, queue, or timeout |

## Related articles

- [MeshCore Packet Format](/wiki/packet-format)
- [Channel Access, Queues, and Delays](/wiki/channel-access-queues-and-delays)
- [Statistics and Logging](/wiki/statistics-and-logging)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>
- <https://github.com/jgromes/RadioLib>
