# Step 2: Eventhouse, KQL database, tables and functions

Everything lands in one KQL database. You create it, then run two scripts that create the
tables and the functions the dashboard and the alert read.

## 1. Create the workspace (skip if you have one)

In Fabric: **Workspaces > New workspace**, name it `Capacity Watch`, and under **Advanced**
pick the Fabric capacity you chose in [onboarding](01-onboarding.md). Keep access to the people
who should see capacity usage by person.

## 2. Create the Eventhouse

In the workspace: **New item > Eventhouse**, name it `CapacityWatch`. Fabric creates a KQL
database with the same name inside it.

Open the KQL database and copy two values from its details pane:

- **Query URI**, which looks like `https://<id>.<region>.kusto.fabric.microsoft.com`
- **Database name**: `CapacityWatch`, unless you renamed it

## 3. Run the scripts

Pick one way.

**With Claude Code or a terminal** (signs in with your Azure CLI login):

```bash
python scripts/kql.py deploy --cluster "<Query URI>" --database CapacityWatch \
    kql/01-tables.kql kql/02-functions.kql
```

Every line should start with `ok`. Running it again is safe: nothing is dropped and no data is
lost.

**By hand in Fabric:** open the KQL database, select **Query with code** (or create a KQL
queryset connected to it), paste the whole content of `kql/01-tables.kql`, select it all and
run it. Then do the same with `kql/02-functions.kql`. Each file is one command
(`.execute database script`), so run each file as a whole.

## 4. Set your preferences

The settings live in a function at the top of `kql/02-functions.kql`:

```kql
CapacityWatchSettings() {
    dynamic({
        "time_zone": "UTC",            // e.g. "America/New_York"
        "smoothing": "window",
        ...
```

Change `time_zone` to the one you chose, and the alert values if you want (they are explained
in [06-alerts.md](06-alerts.md)). Then run `kql/02-functions.kql` again.

To keep more than 30 days of history, change `30d` in the `CapacityOperations` retention and
caching lines of `kql/01-tables.kql` and run it again.

## 5. Check

```bash
python scripts/kql.py query --cluster "<Query URI>" --database CapacityWatch \
    ".show tables | project TableName"
python scripts/kql.py query --cluster "<Query URI>" --database CapacityWatch \
    ".show functions | where Folder == 'CapacityWatch' | count"
```

You should see four tables (`CapacityEventsRaw`, `CapacityOperations`, `CapacitySummary`,
`CapacityStateChanges`) and 24 functions. (`.show` commands work through `kql.py query` too.)

Done when: both scripts ran with only `ok` lines.

## What the scripts create

| Object | What it is |
| --- | --- |
| `CapacityEventsRaw` | Landing table. The Eventstream writes every event here exactly as Fabric sends it. Kept 3 days. |
| `CapacityOperations` | One row per capacity operation, filled from the landing table by an update policy. Kept 30 days. |
| `CapacitySummary`, `CapacityStateChanges` | Fabric's own numbers, filled only if you also stream overview events. |
| `Capacity*()` functions | The math and every view the dashboard and alert use. Reference: [functions.md](functions.md). |

Next: [03-eventstream.md](03-eventstream.md)
