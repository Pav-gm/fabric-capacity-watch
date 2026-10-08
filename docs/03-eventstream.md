# Step 3: Stream the capacity events into the Eventhouse

An Eventstream subscribes to the capacity events and writes them into `CapacityEventsRaw`. This
step is done in the Fabric UI (option A). Option B does the same through the REST API.

Before you start: [Step 2](02-eventhouse.md) is done, so the table `CapacityEventsRaw` exists.

## Option A: Fabric UI

### Create the Eventstream and add the sources

1. In the `Capacity Watch` workspace: **New item > Eventstream**, name it `CapacityWatchEvents`.
2. Select **Add source** (or **Connect data sources**), search for
   **Fabric capacity operation events**, and select **Connect**.
   - **Event types**: keep `Microsoft.Fabric.CapacityOperationEvents.Operation`.
   - **Event scope**: pick the capacity to watch. Only capacities where you are capacity admin
     work.
   - Give the source a name such as `ops-<capacity name>`, then **Add**.
3. Repeat step 2 for every capacity you want to watch. One source per capacity.
4. Optional, recommended: **Add source > Fabric capacity overview events** for the same
   capacity, with both event types (`Microsoft.Fabric.Capacity.Summary` and
   `Microsoft.Fabric.Capacity.State`). Name it `overview-<capacity name>`. These are Fabric's own
   numbers every 30 seconds; they land in `CapacitySummary` and `CapacityStateChanges` and let
   you check the rebuilt numbers.

All sources flow into the Eventstream's default stream. That is fine: the update policies in
the KQL database split the events by type.

### Add the Eventhouse destination

5. Select **Add destination > Eventhouse**, choose **Direct ingestion**, name it
   `capacity-watch-eventhouse`, and pick the workspace and the `CapacityWatch` Eventhouse.
   **Save**. Connect the default stream to it if the canvas did not do it.
   Direct ingestion skips the Eventstream processor, which is cheaper; the KQL database does
   all the processing.
6. Select **Publish**.
7. In **Live view**, select **Configure** on the Eventhouse destination. The **Get data** wizard
   opens in the Eventhouse:
   - Pick the **existing table** `CapacityEventsRaw` (not a new table).
   - Keep the suggested data connection name and select **Next**. Wait for a sample of events;
     on a quiet capacity this can take a few minutes.
   - On **Inspect the data**, the format should be **JSON** and the preview should show the
     columns `specversion`, `type`, `source`, `subject`, `id`, `time`, `dataschemaversion` and
     `data` filled in. They match by name, so the wizard maps them by itself.
   - **Finish**, then **Close**.

Another way in: **Real-Time hub > Fabric events > Fabric capacity operation events >
Create eventstream** creates the Eventstream with the source already added.

## Option B: Fabric REST API

Useful to set up several capacities at once or to rebuild the setup from code. The identity
calling the API must be capacity admin on every capacity in the sources. Microsoft documents the
whole flow in
[Consume events with Eventstream REST APIs](https://learn.microsoft.com/fabric/real-time-hub/consume-events-with-event-stream-rest-api)
and [Eventstream with an Eventhouse direct ingestion destination by API](https://learn.microsoft.com/fabric/real-time-intelligence/event-streams/api-kusto-pull-destination).

The topology (definition part `eventstream.json`), with one pair of sources per capacity:

```json
{
  "sources": [
    {
      "name": "ops-my-capacity",
      "type": "FabricCapacityOperationEvents",
      "properties": {
        "eventScope": "Capacity",
        "capacityId": "<capacity id>",
        "includedEventTypes": ["Microsoft.Fabric.CapacityOperationEvents.Operation"],
        "filters": []
      }
    },
    {
      "name": "overview-my-capacity",
      "type": "FabricCapacityOverviewEvents",
      "properties": {
        "eventScope": "Capacity",
        "capacityId": "<capacity id>",
        "includedEventTypes": ["Microsoft.Fabric.Capacity.Summary", "Microsoft.Fabric.Capacity.State"],
        "filters": []
      }
    }
  ],
  "destinations": [
    {
      "name": "capacity-watch-eventhouse",
      "type": "Eventhouse",
      "properties": {
        "dataIngestionMode": "DirectIngestion",
        "workspaceId": "<workspace id>",
        "itemId": "<Eventhouse item id>",
        "tableName": "CapacityEventsRaw",
        "connectionName": "capacity-watch-connection",
        "mappingRuleName": "CapacityEventsRaw_mapping"
      },
      "inputNodes": [{ "name": "capacity-events" }]
    }
  ],
  "streams": [
    {
      "name": "capacity-events",
      "type": "DefaultStream",
      "properties": {},
      "inputNodes": [{ "name": "ops-my-capacity" }, { "name": "overview-my-capacity" }]
    }
  ],
  "operators": [],
  "compatibilityLevel": "1.1"
}
```

Check the destination properties against Microsoft's page before you send it: a direct
ingestion destination with the wrong set of properties is accepted but stays in a Warning state
and ingests nothing. `CapacityEventsRaw_mapping` is created by `kql/01-tables.kql`.

## Check

Wait 5 to 10 minutes, then:

```bash
python scripts/kql.py query --cluster "<Query URI>" --database CapacityWatch "CapacityWatchHealth()"
```

The row for `CapacityOperations` should say `Receiving events`. If you added overview events,
`CapacitySummary` should say the same. Anything starting with `Problem` is covered in
[08-troubleshooting.md](08-troubleshooting.md).

Done when: `CapacityWatchHealth()` shows `Receiving events` for the operation events.

Remember: Fabric does not send history. Data starts now, and because background work is smoothed
over 24 hours, utilization only reaches its true level after one full day.

Next: [04-validate.md](04-validate.md)
