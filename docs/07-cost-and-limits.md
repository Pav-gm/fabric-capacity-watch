# Cost and limits

## What it costs

Almost everything is billed to the capacity that hosts the `Capacity Watch` workspace. Publishing
the events is billed to each watched capacity. Rates are Microsoft's published consumption rates
(links below); they can change.

| Part | Meter | Rate | Per day |
| --- | --- | --- | --- |
| Eventhouse | Eventhouse UpTime | 2 CU minimum while online, and a continuous stream keeps it online | about 172,800 CU-s |
| Eventstream | Eventstream Per Hour | 0.222 CU-hours per hour while events flow | about 19,200 CU-s |
| Eventstream | Data Traffic Per GB | 0.342 CU-hours per GB | about 1,200 CU-s per GB; most capacities send well under 1 GB a day |
| Fabric events | Event listener | 0.0222 CU-hours per hour, per source | about 1,900 CU-s per source |
| Fabric events | Event operations, delivery | 0.000011111 CU-hours (0.04 CU-s) per event | 4,000 CU-s per 100,000 events |
| Fabric events | Event operations, publish (on the watched capacity) | 0.04 CU-s per event | 4,000 CU-s per 100,000 events |
| Activator | One rule every 5 minutes | Activator meters | small; check it in the Metrics app |
| Storage | OneLake | billed separately from CU | small: a few GB a month at most |

The Eventstream sends events straight to the Eventhouse (direct ingestion), so there is no
Eventstream processor charge.

**Total on the hosting capacity: about 200,000 CU-s a day, an average of about 2.3 CU.** Most of it
is the Eventhouse minimum, which does not grow with the number of capacities you watch. Share of a
day by SKU:

| SKU | CU-s per day | Capacity Watch share |
| --- | --- | --- |
| F2 | 172,800 | over 100%: do not host it here |
| F4 | 345,600 | about 60% |
| F8 | 691,200 | about 30% |
| F16 | 1,382,400 | about 15% |
| F32 | 2,764,800 | about 7% |
| F64 | 5,529,600 | about 4% |
| F128 | 11,059,200 | about 2% |

### How many events you have

After a day:

```kql
CapacityEventsRaw
| where ['time'] > ago(1d)
| summarize events = count(), mb = round(sum(estimate_data_size(*)) / 1e6, 1) by ['type']
```

Each operation event costs about 0.04 CU-s to deliver (hosting capacity) and 0.04 CU-s to publish
(watched capacity). A capacity with 500,000 operations a day adds about 20,000 CU-s to each side.

### Measure the real cost

The Metrics app on the hosting capacity shows the `Capacity Watch` workspace items (Eventhouse,
Eventstream, Activator). If the hosting capacity is also one you watch, Capacity Watch measures
itself:

```kql
CapacityDailyUsage(7d)
| where workspace_name == "Capacity Watch"
| project day, capacity_label, cu_s, share_of_sku_day_pct
```

Microsoft documents that publish operations show up as "Fabric Events Publisher", with an item kind
that starts with `FabricEvents-`.

### Keeping it small

- Host it on a capacity with room (see the table), or on the watched capacity if that is F32 or
  bigger.
- Overview events are optional. Without them you save one listener per capacity and about 2,900
  events a day per capacity, and lose `CapacityFabricCheck()`.
- Keep dashboard refresh at 5 minutes or slower.

## Limits

- **Preview.** Capacity operation events are in preview. Field names can change. The raw landing
  table keeps every event for 3 days exactly as received, so the typed tables can be rebuilt after a
  fix (see [troubleshooting](08-troubleshooting.md)).
- **No history.** Data starts when you connect the stream. Background smoothing needs a full day
  before utilization is right.
- **Capacity admin.** Only capacity admins can stream a capacity's events, and the stream keeps
  running as the person who created it. If they lose the role or leave, events pause; Fabric keeps
  them for 24 hours.
- **No Git or deployment pipelines** for an Eventstream with a capacity operation events source.
  Keep the `Capacity Watch` workspace out of Git integration.
- **Best-effort delivery.** Duplicates are removed; a lost event is not recovered.
- **What is not modeled:** P SKU autoscale, capacity overage billing, surge protection and
  Autoscale Billing for Spark. Details in
  [00-how-fabric-measures-capacity.md](00-how-fabric-measures-capacity.md#where-the-rebuilt-numbers-can-differ-from-fabrics).
- **Three days of carry-forward history.** Every query rebuilds carry-forward from three days
  before the period it shows. A capacity overloaded for longer than that shows less carry-forward
  than Fabric does.
- **Personal data.** Every operation event names the user or service principal that ran it.

## Sources

- [Eventhouse and KQL database consumption](https://learn.microsoft.com/fabric/real-time-intelligence/real-time-intelligence-consumption)
- [Eventhouse minimum capacity](https://learn.microsoft.com/fabric/real-time-intelligence/eventhouse-smart-capacity-control)
- [Eventstream capacity consumption](https://learn.microsoft.com/fabric/real-time-intelligence/event-streams/monitor-capacity-consumption)
- [Azure, Fabric and Business events capacity consumption](https://learn.microsoft.com/fabric/real-time-hub/fabric-events-capacity-consumption)
- [Add a Fabric capacity operation events source to an eventstream (limitations)](https://learn.microsoft.com/fabric/real-time-intelligence/event-streams/add-source-fabric-capacity-operation-events)
- [Subscribe permissions for Azure and Fabric events](https://learn.microsoft.com/fabric/real-time-hub/fabric-events-subscribe-permission)

Next: [08-troubleshooting.md](08-troubleshooting.md)
