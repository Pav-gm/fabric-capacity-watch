# Troubleshooting

Start with the health check. It tells you which part of the chain is broken:

```kql
CapacityWatchHealth()
```

## Access and sign-in

**`check_access.py` shows `[no]` for a capacity.** You are not a capacity admin there. A Fabric
admin adds you in **Admin portal > Capacity settings > (capacity) > Capacity administrators**. For F
SKUs, the owner of the capacity resource in Azure can do it too.

**`check_access.py` shows `[?]` for a capacity.** You have no rights on it at all, so it is not even
visible to you. Same fix.

**Sign-in fails in the scripts.** Run `az login` again. Without an Azure subscription use
`az login --allow-no-subscriptions`. With several tenants use `az login --tenant <tenant domain>`.

**`kql.py` gets HTTP 401 or 403.** Check that `--cluster` is the KQL database's **Query URI** (not
the ingestion URI) and that you are Contributor or higher on the workspace.

## The stream

**"Fabric capacity operation events" is not offered as a source.** The workspace must run on a
Fabric (F) or Trial capacity. Microsoft may also not offer Fabric events in every region; any
exceptions are listed at the top of
[Explore Fabric capacity operation events](https://learn.microsoft.com/fabric/real-time-hub/explore-fabric-capacity-operation-events).

**Status `Problem: no events in the last day`.**

1. Open the Eventstream. If no events reach the default stream, the source is the problem: check
   that the source's capacity is the one you meant, and that something ran on it.
2. If events reach the stream but not the Eventhouse, the destination is not finished: in **Live
   view** select **Configure** on the Eventhouse destination and complete **Get data** with the
   existing table `CapacityEventsRaw` ([03-eventstream.md](03-eventstream.md), step 7).
3. A destination created through the REST API with the wrong set of properties stays in a
   **Warning** state and ingests nothing. Compare it with Microsoft's
   [direct ingestion API page](https://learn.microsoft.com/fabric/real-time-intelligence/event-streams/api-kusto-pull-destination).
4. Look for ingestion errors:

   ```kql
   .show ingestion failures | where Table == "CapacityEventsRaw" | top 20 by FailedOn desc
   ```

**Rows arrive in `CapacityEventsRaw` but `data` or other columns are empty.** The destination does
not use the mapping. Run `CapacityEventsRaw | take 5` to see what arrives, then select
**Configure** on the destination again and pick the existing table and the mapping
`CapacityEventsRaw_mapping`.

**Status `Quiet: no events in the last hour`.** Normal if nothing ran on the capacity. Otherwise the
event subscription may be paused: **Real-Time hub > Fabric events > Fabric capacity operation
events** lists every consumer with a **Status**. For a paused one, **... > View details** shows the
reason. The usual one is that the person who created the source is no longer capacity admin (or
left). Give them the role back, or delete the source and add it again as a current capacity admin.
Fabric keeps events for 24 hours while paused, and resuming can take a couple of hours.

**The hosting capacity was paused and resumed.** Eventstream sources and destinations do not
restart by themselves after a resume. Open the Eventstream and activate them again.

**The workspace is connected to Git and the Eventstream fails to sync.** An Eventstream with a
capacity operation events source does not support Git integration or deployment pipelines. Keep it
in a workspace that is not connected to Git.

## The KQL database

**Status `Problem: events reach CapacityEventsRaw but not CapacityOperations`.** The update policy
is missing or failing. Run `kql/01-tables.kql` again, then check:

```kql
.show table CapacityOperations policy update
.show ingestion failures | where Table == "CapacityOperations" | top 20 by FailedOn desc
```

After the fix, copy the missed events from the landing table (it keeps 3 days):

```kql
.set-or-append CapacityOperations <|
    CapacityOperationsFromRaw()
    | where event_id !in ((CapacityOperations | project event_id))
```

**Microsoft renamed or added a field (the events are in preview).** Adjust
`CapacityOperationsFromRaw()` in `kql/01-tables.kql`, run the file again and copy the missed events
with the command above. Look at a raw event to see the new shape:

```kql
CapacityEventsRaw | where ['type'] == "Microsoft.Fabric.CapacityOperationEvents.Operation" | take 1 | project data
```

**A deploy line says `FAIL`.** The line after it has Kusto's reason. Running a file again is safe.

## The numbers

**Utilization is too low on the first day.** Expected: background work is smoothed over 24 hours
and the stream has no history. Wait one full day.

**The numbers differ from the Metrics app.** See [04-validate.md](04-validate.md) for what to
compare, and the known reasons in
[00-how-fabric-measures-capacity.md](00-how-fabric-measures-capacity.md#where-the-rebuilt-numbers-can-differ-from-fabrics).
P SKUs with autoscale, capacity overage billing and surge protection change when Fabric throttles,
and Capacity Watch does not model them.

**A capacity is missing.** `CapacityList()` shows capacities with events in the last 30 days. Add
a source for it in the Eventstream.

## The dashboard

**Tiles say they cannot resolve `_capacity`.** The parameter's variable name must be exactly
`_capacity` ([05-dashboard.md](05-dashboard.md#2-add-the-capacity-parameter)).

**Tiles are slow or time out.** Shorten the periods in the tile queries (for example `24h` to `12h`,
`7d` to `3d`) and refresh less often. Every tile rebuilds carry-forward from three days before its
period.

**Viewers see empty tiles.** With pass-through identity they also need read access to the KQL
database ([05-dashboard.md](05-dashboard.md#5-share-it)).

## Alerts

**No messages at all.** Test delivery with a temporary rule on `CapacityAlerts()`
([06-alerts.md](06-alerts.md#3-test-that-messages-arrive)). Check that the rule is running in the
`CapacityWatchAlerts` Activator item, and that its creator still has access to the workspace.

**The same change arrives twice.** The rule runs more often than `alert_window_min` minutes. Make
them equal.

**Changes are missed.** The rule runs less often than `alert_window_min` minutes. Make them equal.
