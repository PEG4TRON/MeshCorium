# Direct Routing and Path Discovery

Direct routing forwards a packet along a pre-supplied sequence of path hashes. `Direct` means **directed routing**, not one RF hop. A path containing ten repeaters is still direct routing.

![Flood and Direct](/attachments/en/flood-vs-direct.svg?v=2)

## Route types

- `ROUTE_TYPE_DIRECT`;
- `ROUTE_TYPE_TRANSPORT_DIRECT`.

Transport Direct additionally carries region transport codes. The route remains source-routed: the packet contains the sequence of next hops.

## How a repeater forwards a direct packet

In the current `Mesh::onRecvPacket`:

1. verify that path-hash count is greater than zero;
2. an ACK may receive early local processing;
3. compare the first path entry with the node identity;
4. check `allowPacketForward`;
5. use the seen table to reject a duplicate;
6. remove the node's own entry from the path;
7. queue the packet at high priority with `direct.txdelay`.

A node that is not the next hop releases the packet. Unlike flood routing, many neighboring nodes do not retransmit the same copy.

## Final hop

When the path becomes empty, the packet is treated as having reached the destination area. For addressed payloads, the node compares the destination hash and attempts decryption with known peer secrets.

Several identities may share the same short destination hash. Only successful MAC verification and decryption identify the destination.

## Discovering a route through flood

A typical path-discovery sequence is:

1. the sender has no cached path;
2. it sends an addressed packet as flood;
3. repeaters append their hashes;
4. the destination receives the winning copy;
5. it creates `PAYLOAD_TYPE_PATH` using the accumulated route;
6. it returns PATH to the original sender;
7. the sender stores the contact's `out_path`;
8. later packets use direct routing.

A returned path may carry an extra ACK or RESPONSE, confirming the first packet without another separate transmission.

## Reciprocal path assumption

The mechanism assumes that the node chain can be used in reverse. Real radio links may be asymmetric because of:

- different TX power;
- different antennas;
- interference local to one endpoint;
- hidden-node collisions;
- queue and duty-budget state;
- mobility;
- direction-dependent antenna patterns.

A route may therefore be discovered in one direction while the ACK cannot return. Receiving an advert also does not prove bidirectional direct connectivity.

## First path, shortest path, and best path

The current algorithm does not calculate a global metric. The first successfully processed flood copy wins. It may be:

- the fastest at that moment;
- the route with the fewest hops;
- the route with the strongest SNR;
- or simply the route with a fortunate random delay.

It is a **first path**, not a guaranteed shortest or best path. `rxdelay` can favor stronger copies, but does not turn the network into a link-state protocol.

## Path storage

A Companion contact normally includes:

- `out_path_len`;
- up to `MAX_PATH_SIZE` bytes of path;
- timestamp of the latest advert;
- identity and node type.

Treat the path as a cache, not proof that every repeater is currently available.

Useful client policies include:

- clear the path after several failed attempts;
- update it after a new advert or path response;
- display hop count and last-update time;
- do not use an old path as online status;
- provide manual reset.

## `CMD_RESET_PATH`

The Companion Protocol contains a reset-path command. It removes the stored route to a contact, causing the next transmission to use discovery and flood.

Reset is appropriate when:

- one hop is powered off;
- a mobile repeater has moved;
- the network changed path-hash mode;
- direct ACKs fail consistently;
- a newer advert indicates another path;
- a contact was imported with a stale route.

## Stale path

Typical symptoms are:

- the contact remains visible;
- direct delivery receives no confirmation;
- other nodes work normally;
- the message succeeds after reset and flood.

This is not necessarily a key problem. The packet may never reach the destination, so decryption is never attempted.

## Direct retransmit delay

CLI:

```text
get direct.txdelay
set direct.txdelay <0..2>
```

The documented default is `0.2`, lower than the flood default of `0.5`. Usually only one designated next hop forwards a direct packet, so there are fewer contenders.

Zero delay minimizes latency but may collide with a response while a previous flood or nearby TX is still active. A small amount of jitter is useful.

## Priority

In `Mesh.cpp`, normal direct forwarding is queued with priority `0`, described as the highest priority. Flood priority degrades as path count increases. This helps:

- prevent an ACK from waiting behind distant flood traffic;
- clear direct routes quickly;
- reduce application timeouts;
- limit queue growth.

Duty-cycle budget can still delay transmission. Priority does not override legal or software limits.

## Direct ACK

An ACK travels back over a path contained in the packet or context. An intermediate node may process it locally for statistics, remove itself from the path, and forward it.

If the ACK is lost, the sender cannot distinguish a lost message from a lost acknowledgment. Without idempotency, a retry may repeat a user action.

## Multipart ACK

Multi-ACK uses `PAYLOAD_TYPE_MULTIPART`. Intermediate nodes may create additional delayed ACK copies. This can improve acknowledgment probability on a poor route, but multiplies airtime. Enable it only after measurement.

## Mobile repeaters

A mobile repeater may form an excellent route while positioned between two segments. After it leaves:

- the packet reaches the previous hop;
- the next hash is no longer audible;
- forwarding stops;
- the sender waits for timeout;
- the path remains cached until policy clears it.

A fallback policy should reset the path and run flood discovery after a limited number of failures. Falling back too aggressively creates floods after isolated packet loss.

## Changing path-hash size

A direct packet carries encoded hash size. Firmware ≥1.14 is expected to forward 1–3-byte entries; older versions may drop multibyte packets.

During migration:

- update the backbone first;
- let sources create multibyte paths only after testing;
- cached 1-byte paths remain valid while the network still forwards them;
- imported contact paths must preserve encoded `path_len`, not only raw bytes.

## Route repair

MeshCore does not perform full local repair at every broken hop. The main repair method is a new flood discovery from the sender.

One possible application strategy is:

```text
1st failure: retry direct
2nd failure: retry direct with a longer timeout
3rd failure: reset path
4th attempt: flood discovery
```

Thresholds depend on airtime and criticality. Aggressive flood fallback may be justified in emergency communications, but not in a sensor network.

## Direct-route diagnostics

1. check path age;
2. display hop count and path details;
3. run a trace;
4. verify that adjacent repeaters are visible zero-hop;
5. compare `n_recv_direct` and `n_sent_direct` at each hop;
6. inspect duplicate counters;
7. inspect TX queue and duty budget;
8. reset the path and repeat;
9. compare the new route with the old one.

## Related articles

- [Flood Routing](/wiki/flood-routing)
- [Trace and Route Diagnostics](/wiki/trace-and-route-diagnostics)
- [ACKs, Retries, and Multipart Packets](/wiki/acknowledgements-retries-and-multipart)
- [Path Hashes, Duplicates, and Loops](/wiki/path-hashes-duplicates-and-loops)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>
