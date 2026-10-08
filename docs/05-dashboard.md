# Step 5: Build the dashboard

The dashboard is a Real-Time Dashboard next to the Eventhouse. Every tile is a short query over the
stored functions. The queries are in [`dashboard/`](../dashboard), one file per tile, with the
visual settings in the comment at the top of each file. All of them are tested against the sample
data in `tests/`.

This step is done in the Fabric UI.

## 1. Create the dashboard and connect the database

1. In the `Capacity Watch` workspace: **New item > Real-Time Dashboard**, name it `Capacity Watch`.
2. **Add data source > KQL Database** (Eventhouse), pick the `CapacityWatch` database, **Connect**.

## 2. Add the capacity parameter

Most tiles show one capacity at a time. In edit mode: **Manage > Parameters > New parameter**:

| Setting | Value |
| --- | --- |
| Label | `Capacity` |
| Parameter type | Single selection |
| Variable name | `_capacity` |
| Data type | string |
| Source | Query, on the `CapacityWatch` data source, with the query in [`dashboard/parameter-capacity.kql`](../dashboard/parameter-capacity.kql) |
| Value column | `capacity_label` |
| Default value | First value of query |

## 3. Add the tiles

For each file below: **New tile** (or **New visual**), paste the whole file, **Run**, pick the
visual type named at the top of the file, then **Apply** and **Done**. Rename the tile to the title
in the file.

| File | Tile | Visual | Filtered by `_capacity` |
| --- | --- | --- | --- |
| `01-status.kql` | Capacity status | Table | no, all capacities |
| `02-utilization.kql` | Utilization, actual and already booked | Line chart | yes |
| `03-throttling.kql` | Throttling measures | Line chart | yes |
| `04-carry-forward.kql` | Carry-forward | Area chart | yes |
| `05-background-interactive.kql` | Background and interactive load | Stacked area chart | yes |
| `06-overage-episodes.kql` | Overage episodes, last 7 days | Table | yes |
| `07-usage-by-workspace.kql` | Share of the SKU day by workspace | Stacked column chart | yes |
| `08-top-items.kql` | Top items, last 24 hours | Table | yes |
| `09-throttled-operations.kql` | Rejected and delayed operations | Table | yes |
| `10-alert-history.kql` | Alert level changes | Table | no, all capacities |
| `11-stream-health.kql` | Stream health | Table | no |
| `12-fabric-check.kql` | Rebuilt against Fabric's numbers (only with overview events) | Table | no |

A layout that works: the status table across the top, then two tiles per row in the order above.
Add the conditional formatting rules described in the table tiles' comments: they make the state of
each capacity readable at a glance.

## 4. Refresh settings and save

**Manage > Refresh settings**: refresh every 5 minutes at most (15 minutes is plenty). Each refresh
runs every tile again, and the chart tiles read several days of events to rebuild carry-forward, so
more frequent refreshes cost Eventhouse compute for no benefit. If you turn on live refresh, set its
refresh rate limit to 5 minutes or more. Then **Save**.

## 5. Share it

**Share** sends a link. With the default data source setting (pass-through identity), a viewer
sees data only if they can also read the KQL database. To let people see the dashboard without
access to the database, switch the data source to the dashboard editor's identity. Details:
[Real-Time Dashboard permissions](https://learn.microsoft.com/fabric/real-time-intelligence/dashboard-permissions).

The rejected operations tile shows how many people were affected, not who. The identities are in
the database if you need them (see the privacy note in [onboarding](01-onboarding.md#privacy)).

## Reading it

- Start with **Capacity status**: `State` and `Verdict` say whether anything needs attention.
- **Utilization over 100% is not a problem by itself.** Look at the throttling measures: Fabric only
  delays or rejects work when one of them is over 100%.
- The lines after "now" are what is already booked if nothing new runs. They show when throttling
  ends without any action.
- Background load that stays near or above 100% for hours is the pattern that leads to rejected
  reports. The fix is to reduce or move background work, or scale up.
- **Share of the SKU day by workspace** shows who uses the capacity. **Top items** shows what
  changed against the day before.

## Time zones

Table tiles show local times (the `time_zone` setting in `CapacityWatchSettings()`). Chart tiles
plot `ts`, which is UTC. If your dashboard shows chart times in UTC and you want local time, replace
`ts` with `ts_local` in the chart queries; the functions return both.

## Keep a copy

When the dashboard is done, **Manage > Download file** saves it as JSON. Keep that file to restore
the dashboard or to create it again in another workspace with **Manage > Replace with file**. It
holds the IDs of your workspace and database, which is why this repo does not ship one and why
`dashboard/*.json` is git-ignored. If your copy of the repo is private, remove that line from
`.gitignore` and commit the file.

## Power BI instead

The same functions work from Power BI through its KQL database connector (DirectQuery), if you
want these numbers next to other reports. The Real-Time Dashboard is simpler and refreshes on its
own.

Done when: the status table lists every watched capacity and the charts change when you pick
another capacity.

Next: [06-alerts.md](06-alerts.md)
