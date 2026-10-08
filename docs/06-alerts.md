# Step 6: Alerts

One Activator rule runs `CapacityAlertChanges()` every 5 minutes. The function returns a row only
when a capacity's alert level changed, so you get one message when a capacity gets into trouble and
one when it is back to normal, not a message every 5 minutes. Short spikes that Fabric does not
throttle never alert.

This step is done in the Fabric UI.

## The levels

| Level | When | Setting |
| --- | --- | --- |
| `critical` | Fabric rejects work: the 60-minute or the 24-hour measure is over 100%, or an operation was rejected in the last 15 minutes | `rejection_lookback_min` |
| `warning` | Fabric delays interactive work: the 10-minute measure is over 100%, or utilization has been over 100% for 10 minutes in a row | `warning_over_streak_min` (0 turns the streak rule off) |
| `ok` | Anything else, including short spikes | |

Each row carries a plain-language `reason`, for example "Fabric rejects new interactive work such
as report queries (60-minute measure at 134%)".

## 1. Create a KQL queryset

In the `Capacity Watch` workspace: **New item > KQL Queryset**, name it `CapacityWatchQueries`, and
connect it to the `CapacityWatch` database. Run:

```kql
CapacityAlertChanges()
```

It normally returns no rows. That is expected: it only returns rows in the 5 minutes after a level
changes.

## 2. Set the alert

With the query above in the editor, select **Set alert** on the top ribbon:

| Section | Value |
| --- | --- |
| Details | Rule name `Capacity level change` |
| Monitor | Every **5 minutes**. This must equal `alert_window_min` in `CapacityWatchSettings()` (default 5). A shorter interval sends some changes twice and a longer one misses some. |
| Condition | Alert on every row the query returns (each row is one level change) |
| Action | **Send email**, or **Teams** to people, a group chat or a channel |
| Subject or headline | `Capacity @capacity_label is @alert_level` |
| Notes | `@reason. It was @previous_level. Time: @as_of_local` |
| Context | `utilization_pct`, `delay_pct`, `interactive_reject_pct`, `background_reject_pct`, `carry_min` |
| Save location | The `Capacity Watch` workspace, a new Activator item named `CapacityWatchAlerts` |

Type each `@` reference and pick the column from the list rather than pasting it, so Activator links
it to the query result. Then **Create**.

## 3. Test that messages arrive

A real level change might not happen for days, so test delivery once:

1. In the same queryset, run `CapacityAlerts()`. It always returns one row per capacity with its
   current level.
2. **Set alert** on it with the same action and a rule name such as `Delivery test`.
3. Wait for one message per capacity, then delete the test rule (**Rules** pane in the queryset,
   **...** next to the rule).

Done when: the test messages arrived, the test rule is deleted and `Capacity level change` is
active.

## Tuning

The alert values live in `CapacityWatchSettings()` at the top of `kql/02-functions.kql`. After a
change, run that file again (see [02-eventhouse.md](02-eventhouse.md#3-run-the-scripts)).

| Setting | Default | Change it when |
| --- | --- | --- |
| `warning_over_streak_min` | 10 | You get warnings for long stretches over 100% that you consider normal (raise it), or you only care about real throttling (set 0) |
| `rejection_lookback_min` | 15 | Rejected operations are rare and you want to hear about each one sooner or later |
| `alert_window_min` | 5 | You change how often the Activator rule runs (keep them equal) |

A capacity that sits right at a limit can go back and forth between two levels. If that gets noisy,
raise `warning_over_streak_min`, or take it as a sign the capacity needs attention.

## Without the Eventhouse: Fabric's own capacity alert

Real-Time hub has a ready-made alert on capacity overview events: **Real-Time hub > Fabric events >
Capacity overview events > Set alert**, with templates such as "Alert when a capacity metric exceeds
a threshold" on `interactiveDelayThresholdPercentage`, `interactiveRejectionThresholdPercentage`
or `backgroundRejectionThresholdPercentage`. It is quick to set up and needs no Eventhouse, but it
works per capacity and tells you a number, not what ran. Both can run side by side. Microsoft's
walkthrough: [Monitor Fabric capacity health with capacity overview events](https://learn.microsoft.com/fabric/real-time-hub/tutorial-monitor-capacity-threshold).

Next: [07-cost-and-limits.md](07-cost-and-limits.md)
