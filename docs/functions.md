# Function reference

All functions live in the `CapacityWatch` folder of the KQL database. `kql/01-tables.kql` creates
the tables and the three update policy functions; `kql/02-functions.kql` creates the rest. Times
ending in `_utc` or named `ts` are UTC; columns ending in `_local` use the `time_zone` setting.

## For people

| Function | Returns |
| --- | --- |
| `CapacityStatus()` | One row per capacity: `state`, a one-line `verdict`, current utilization, carry-forward and the three throttling measures, the 24-hour peaks, rejected operations, and `throttling_ends_local` while throttled |
| `CapacityTimeline(lookback, step = 5m)` | Per capacity and step: the worst minute of utilization, background and interactive share, carry-forward and the three measures. Covers the lookback plus the next 24 hours; `actual_pct` is filled for the past and `projected_pct` for the future |
| `CapacityOverageEpisodes(lookback)` | One row per stretch above 100%, until carry-forward was paid back: start, end, `episode_kind` (Blip, Short, Sustained, Long, Full day), worst `throttle_stage`, peaks, rejected operations, `still_open` |
| `CapacityDailyUsage(lookback)` | CU-seconds per local day, capacity and workspace, with `share_of_sku_day_pct`. Preview operations are reported separately as `non_billable_cu_s` |
| `CapacityTopItems(hours = 24)` | Items by CU-seconds in the last N hours against the N hours before, with the change and the share of the SKU |
| `CapacityThrottledOps(hours = 24)` | Rejected and delayed operations by item, with the number of distinct users affected |
| `CapacityList()` | The capacities in the stream, with SKU and last event |
| `CapacityWatchHealth()` | One row per event type: whether events arrive and reach their typed table |

## For alerts

| Function | Returns |
| --- | --- |
| `CapacityAlertLevels(hours = 24)` | Alert level (`ok`, `warning`, `critical`) and `reason` per capacity per minute |
| `CapacityAlerts()` | The current level per capacity |
| `CapacityAlertHistory(hours = 24)` | Every level change in the last N hours |
| `CapacityAlertChanges()` | Level changes in the last `alert_window_min` minutes. Activator runs this one |

## Comparing with Fabric (needs capacity overview events)

| Function | Returns |
| --- | --- |
| `CapacityFabricMinutes(lookback)` | Fabric's own utilization, throttling measures and carry-forward per capacity per minute |
| `CapacityFabricCompare(lookback)` | Rebuilt and Fabric values side by side, per capacity per minute |
| `CapacityFabricCheck(lookback = 1d)` | Per capacity: minutes compared, mean and 95th percentile difference in utilization, stage agreement |

## Building blocks

| Function | Returns |
| --- | --- |
| `CapacityWatchSettings()` | The settings (a dynamic bag). Edit and run `kql/02-functions.kql` again |
| `CapacitySkuCU(sku)` | CU per second for a SKU name: `F64` is 64. Trial is 64, P1 to P5 and EM1 to EM3 are mapped too |
| `CapacityOps(from_time, to_time)` | Deduplicated operations with `cu_s`, `is_interactive`, `billable`, `rejected`, `delayed`, `sku_cu` and the smoothing window (`win_start`, `win_end`) |
| `CapacityMinuteAll(from_time, to_time)` | The engine: one row per capacity per minute. Minutes after now are projections (`is_projection`) |
| `CapacityMinute(lookback)` | The engine for past minutes only |
| `CapacityEpisodesOf(minutes)` | Turns per-minute rows into episodes; used by `CapacityOverageEpisodes` and `CapacityStatus` |
| `CapacityOperationsFromRaw()`, `CapacitySummaryFromRaw()`, `CapacityStateFromRaw()` | Update policy functions: turn raw events into typed rows |

## Per-minute columns (`CapacityMinuteAll`, `CapacityMinute`)

| Column | Meaning |
| --- | --- |
| `utilization_pct` | Smoothed billable CU in use, as a percentage of the SKU |
| `background_pct`, `interactive_pct` | The same, split by operation type |
| `carry_min` | Carry-forward, in minutes of the full SKU |
| `delay_pct` | Fabric's 10-minute measure. Over 100%: interactive operations are delayed |
| `interactive_reject_pct` | Fabric's 60-minute measure. Over 100%: interactive operations are rejected |
| `background_reject_pct` | Fabric's 24-hour measure. Over 100%: all new operations are rejected |
| `throttle_stage` | `None`, `Interactive delay`, `Interactive rejection` or `Background rejection` |
| `over_streak_min` | Minutes in a row above 100% utilization |
| `rejected_ops`, `delayed_ops` | Operations reported as rejected or delayed in that minute |
| `rejected_recent` | Rejected operations in the last `rejection_lookback_min` minutes |
| `non_billable_cu_s` | CU-seconds of preview operations, which do not count |
| `restarted` | The capacity was resumed in that minute (new activation) |
| `is_projection` | The minute is in the future: only work that already ran is counted |

## Settings (`CapacityWatchSettings()`)

| Setting | Default | Meaning |
| --- | --- | --- |
| `time_zone` | `UTC` | IANA time zone for local times and daily totals |
| `smoothing` | `window` | `window` uses the smoothing window on each event; `type` uses 24 hours for background and 5 minutes for interactive work |
| `interactive_window_min`, `background_window_min` | 5, 1440 | Windows for `type` smoothing, and the fallback when an event has no usable window |
| `eval_lag_min` | 1 | The newest minutes ignored because their events are still arriving |
| `warmup_days` | 2 | Extra history read before each period, so carry-forward starts right |
| `delay_horizon_min`, `interactive_reject_horizon_min`, `background_reject_horizon_min` | 10, 60, 1440 | Fabric's three throttling horizons |
| `warning_over_streak_min` | 10 | Warning after this many minutes in a row over 100% (0 turns it off) |
| `rejection_lookback_min` | 15 | Critical while any operation was rejected in this many minutes |
| `alert_window_min` | 5 | Must equal how often Activator runs `CapacityAlertChanges()` |
