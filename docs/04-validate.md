# Step 4: Check the numbers

Before you build the dashboard, make sure events arrive and the numbers make sense. All queries
below run with `python scripts/kql.py query --cluster "<Query URI>" --database CapacityWatch "<query>"`
or in a KQL queryset connected to the database.

## Right after connecting the stream

```kql
CapacityWatchHealth()
```

One row per event type. `CapacityOperations` should say `Receiving events`. With overview events,
`CapacitySummary` should too (`CapacityStateChanges` only gets rows when the capacity state changes,
so it can stay empty).

```kql
CapacityList()
```

One row per watched capacity, with its SKU and how many events arrived in the last 24 hours. A
capacity that is missing has no source in the Eventstream, or nothing has run on it yet.

```kql
CapacityOps(ago(1h), now())
| summarize operations = count(), cu_s = sum(cu_s) by capacity_label, workspace_name, item_kind, operation_name
| order by cu_s desc
```

What ran in the last hour. Operations without a workspace are Fabric's own (for example the event
publishing that this setup adds), shown elsewhere as `(Fabric, no workspace)`.

## After one full day

Background work is smoothed over 24 hours and the stream has no history, so utilization only
reaches its true level after a day. Then:

```kql
CapacityStatus()
```

One row per capacity: `state`, a one-line `verdict`, current utilization, the three throttling
measures and the peaks of the last 24 hours.

### Compare with the Capacity Metrics app

Open the Metrics app compute page for the same capacity and pick a recent day in the ribbon chart,
so the charts show every 30-second timepoint.

| Capacity Watch | Metrics app (compute page) | What to expect |
| --- | --- | --- |
| `utilization_pct`, `background_pct`, `interactive_pct` from `CapacityMinute(1d)` | Utilization tab | Same shape and level. Capacity Watch uses 1-minute steps, the app 30 seconds |
| `delay_pct`, `interactive_reject_pct`, `background_reject_pct` | Throttling tab (Interactive delay, Interactive rejection, Background rejection) | Same values within a few points, and over 100% at the same times |
| `carry_min` | Overages tab, Cumulative % | Rises and returns to zero at the same times. Units differ: Capacity Watch shows minutes of full capacity |
| `CapacityDailyUsage(2d)` by workspace | Items matrix, CU (s), filtered to the same day | Close. Capacity Watch days follow `time_zone`; if the totals look shifted, compare with `time_zone` set to `UTC` |

A query for a quick side by side:

```kql
CapacityMinute(1d)
| where capacity_label == "<capacity>"
| project ts, utilization_pct, delay_pct, interactive_reject_pct, background_reject_pct, carry_min, throttle_stage
| order by ts asc
```

### Compare with Fabric's own numbers (if you stream overview events)

```kql
CapacityFabricCheck(1d)
```

| Column | Good after the first day |
| --- | --- |
| `minutes_compared` | close to 1,440 per capacity |
| `mean_abs_diff_utilization` | under 2 percentage points |
| `stage_agreement_pct` | above 98% |

These limits are rules of thumb, not guarantees. For the minutes that disagree:

```kql
CapacityFabricCompare(1d)
| where throttle_stage != fabric_stage or abs(utilization_pct - fabric_utilization_pct) > 5
| order by ts asc
```

Known reasons for differences are listed in
[00-how-fabric-measures-capacity.md](00-how-fabric-measures-capacity.md#where-the-rebuilt-numbers-can-differ-from-fabrics).
If the rebuilt numbers stay off, try `"smoothing": "type"` in `CapacityWatchSettings()` (run
`kql/02-functions.kql` again) and compare once more.

Done when: `CapacityStatus()` matches what the Metrics app shows for the same day, or
`CapacityFabricCheck(1d)` is within the limits above.

Next: [05-dashboard.md](05-dashboard.md)
