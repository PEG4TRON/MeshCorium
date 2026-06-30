# Regions and Transport Codes

Regions limit the propagation area of transport flood and direct packets. They support scaling and administrative zoning: local traffic does not have to cross an entire physically connected mesh.

![Regions](/attachments/en/regions.svg?v=2)

## What a region does

Region policy answers one question:

> Is this node allowed to forward a packet carrying this transport code?

It does not:

- encrypt the payload;
- hide the region name;
- calculate the best route;
- guarantee delivery inside the region;
- replace `flood.max`;
- change LoRa frequency.

Regions operate over a shared radio profile. A denied packet is still physically received and consumes airtime, but it is not forwarded farther.

## Transport routes

Route types are:

- `ROUTE_TYPE_TRANSPORT_FLOOD`;
- `ROUTE_TYPE_TRANSPORT_DIRECT`.

They place the following after the header:

```text
transport_code_1: 2 bytes
transport_code_2: 2 bytes
```

The first code is derived from scope or region. The second is reserved. A transport code is a compact identifier, not a full name and not a message-authentication code.

## Hierarchy

Regions form a tree rooted at wildcard `*`. Example:

```text
*
└── Europe
    └── Germany
        ├── Berlin
        └── Hamburg
```

The hierarchy describes nested areas. Actual forwarding policy depends on the configured regions and flood flags on each node.

CLI bulk loading supports a maximum depth of eight levels.

## Home region

```text
region home
region home <name>
```

The home region describes a node's membership. It may be used for scope selection and topology presentation. Setting a home region does not automatically deny every other packet.

## Default scope

```text
region default
region default <name>
region default <null>
```

The default region is applied to outgoing flood traffic when the application does not choose a scope explicitly. Clearing it returns to unscoped behavior.

An incorrect default may make messages invisible to parts of the network where that transport code is denied.

## Wildcard and unscoped traffic

Region `*` is both the root and the policy target for packets without scope.

```text
region allowf *
region denyf *
```

- `allowf *` permits unscoped flood traffic;
- `denyf *` drops it.

A softer alternative is:

```text
set flood.max.unscoped 3
```

This keeps legacy or unscoped traffic local to a few hops.

## Managing the region list

### Bulk load

```text
region load
region load <name> [F]
```

Indented interactive input creates parent-child relationships. `F` enables flooding.

After changes:

```text
region save
```

Without saving, changes may disappear after reboot.

### Creating a region

```text
region put <name> [parent]
```

Creates a region; the default parent is wildcard.

### Defining a hierarchy on one line

```text
region def <token> [<token> ...]
```

The cursor starts at `*`. A `name` token creates a child and moves the cursor there. `name|jump` or `name,jump` creates the node and moves the cursor to an existing region.

The operation may be partial: nodes created before an error remain in memory. Display and review the tree before `region save`.

### Flood policy

```text
region allowf <name>
region denyf <name>
region get <name>
```

`get` displays information and helps verify codes and flags.

## Design example

Suppose a country-wide network contains dense city segments:

```text
Country
├── City-A
│   ├── North
│   └── South
└── City-B
```

A reasonable policy is:

- local group messages use scope City-A;
- emergency traffic may use scope Country;
- border repeaters allow Country and their own city;
- internal edge repeaters deny the neighboring city;
- unscoped traffic is limited to a small hop count;
- advert scope is selected separately from user traffic.

This prevents City-A traffic from filling City-B queues even when several high repeaters can physically hear both areas.

## Transport-code collisions

A 16-bit code has finite space. If it is derived from a region name or scope, collisions are theoretically possible. Regions are therefore a routing-policy mechanism, not a security boundary.

An attacker who knows the code can create another packet with the same value. Payload security must still come from peer or channel keys and signatures.

## Transport Direct

A direct path already restricts forwarding to specific hops. A transport code adds a policy boundary: a repeater may refuse the packet even when its hash is next in the path.

This supports administrative separation, but creates a failure mode:

- the path was discovered before a policy change;
- one hop now denies the scope;
- the direct packet stops;
- a new flood in the same scope also cannot cross that node.

After region changes, rebuild paths and perform end-to-end tests.

## Regions and frequencies

Region scope does not replace frequency planning. Areas sharing one radio profile still interfere even when forwarding is denied. Very dense deployments may use different permitted channels or frequencies, but communication between them then requires a multi-radio bridge with loop protection.

## Migrating a legacy network

1. update repeaters with transport support;
2. create the region tree without denies;
3. assign home regions;
4. enable default scope on test sources;
5. verify transport flood and direct traffic;
6. limit unscoped hop count;
7. only then apply `denyf`;
8. save configuration and backups.

Applying `denyf *` too early may isolate old clients and remote administration paths.

## Diagnostics

If a scoped packet does not pass:

- check route type: transport or ordinary;
- display the region tree on every border repeater;
- verify `allowf` and `denyf`;
- verify default and home regions;
- compare the packet transport code with the region code;
- check `flood.max` and path size;
- reset a stale direct path;
- temporarily allow the scope and retry;
- check for mixed firmware.

## Safe operation

- do not treat region names as secrets;
- document codes and hierarchy;
- avoid frequent remote bulk changes;
- check partial `region def` failures;
- save only after review;
- maintain serial recovery access for border repeaters;
- never use a transport code as an ACL.

## Related articles

- [Flood Routing](/wiki/flood-routing)
- [Direct Routing and Path Discovery](/wiki/direct-routing-and-path-discovery)
- [Capacity and Scaling](/wiki/capacity-and-scaling)
- [Compatibility and Migration](/wiki/compatibility-and-migration)

## Sources

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
