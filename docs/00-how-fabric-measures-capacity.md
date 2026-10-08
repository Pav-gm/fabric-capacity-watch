# How Fabric measures capacity (and what Capacity Watch rebuilds)

Read this once before you trust any number on the dashboard. Everything here comes from
Microsoft's documentation, linked at the end. Capacity Watch rebuilds these measures from the
events Fabric sends; it does not invent its own.

## Capacity units

A Fabric capacity gives you a number of capacity units (CU) every second. The number is in the
SKU name: an F64 gives 64 CU per second, which is 64 x 86,400 = 5,529,600 CU-seconds per day.
Every operation (a notebook run, a report query, a pipeline copy, an Eventhouse staying online)
uses some CU-seconds.

## Smoothing: why "over 100%" is not the same as "throttled"

Fabric lets an operation run as fast as it can (bursting) and then spreads its cost over future
time (smoothing), in 30-second timepoints:

- **Background** operations (scheduled refreshes, notebooks, pipelines) are spread over 24 hours.
- **Interactive** operations (report queries and similar) are spread over at least 5 minutes, and
  up to 64 minutes for big ones.

**Utilization** is the smoothed CU in use right now divided by what the SKU provides. Because of
bursting, utilization can go above 100% for a while without anything bad happening.

## Carry-forward

When smoothed usage in a timepoint is above 100%, the extra is **carried forward** into the next
timepoints. When a timepoint has room to spare, the carry-forward is paid back (**burndown**).
Capacity Watch shows carry-forward in minutes of full capacity: a carry-forward of 30 minutes
means the capacity owes 30 minutes of its entire SKU.

## The three throttling measures

Fabric decides whether to throttle by looking ahead. For each of three horizons it adds up the
CU that is already booked for that horizon (smoothed usage of operations that already ran, which
will keep landing in the coming timepoints) plus the carry-forward, and divides by what the SKU
provides in that time:

| Measure | Horizon | Over 100% means |
| --- | --- | --- |
| Interactive delay | next 10 minutes | new interactive operations wait 20 seconds |
| Interactive rejection | next 60 minutes | new interactive operations are rejected (reports fail) |
| Background rejection | next 24 hours | everything new is rejected, including scheduled jobs |

Up to 10 minutes of future capacity can be used without any throttling (overage protection).
Microsoft's own example: an interactive delay of 250% means Fabric is trying to fit 25 minutes
of work into the next 10 minutes.

Two consequences that surprise people:

1. **A short spike is usually harmless.** A burst of report queries is smoothed over a few
   minutes, so its booked share disappears quickly. A capacity can show 105% for five minutes and
   never delay anything. This is the most common "we hit capacity" false alarm.
2. **Sustained background load is not harmless.** Background work is smoothed over 24 hours, so
   what ran today is still booked for the next hour. If the 24-hour smoothed load stays above
   100%, the 60-minute measure is above 100% too, and Fabric rejects report queries even though
   no single job looks big. The fix is to reduce or move background work, or scale up.

Real-Time Intelligence items (Eventhouse, Eventstream) skip the delay stage and are only throttled
from the rejection stage.

## What resets things

- **Scaling up** pays back carry-forward faster, because every timepoint has more room.
- **Pausing and resuming** bills all booked usage and carry-forward at once and starts from zero.
  Capacity Watch detects a resume (the capacity gets a new activation ID) and resets there too.
- Only **billable** operations count. Preview features that Fabric does not bill yet show up in
  the events (release type `Preview`) but are excluded from utilization and throttling.

## How Capacity Watch rebuilds the numbers

From every capacity operation event it takes the CU-seconds, the interactive or background type
and the smoothing window Fabric reports on the event (setting `smoothing = "window"`; the
alternative `"type"` uses 24 hours and 5 minutes). Then, per capacity and per minute, it computes:

- utilization (background and interactive separately),
- carry-forward, with burndown and the reset on resume,
- the three throttling measures above, from the usage already booked at that minute,
- the throttling stage, rejected and delayed operations seen in the events,
- for the future: what is already booked if nothing new runs (the dashed "projected" line).

The KQL is tested minute by minute against an independent Python model (`tests/`).

## Where the rebuilt numbers can differ from Fabric's

- **The first day.** Background work is smoothed over 24 hours, and the stream only knows about
  operations from when you connected it. Utilization ramps up from zero over the first 24 hours.
  Trust the numbers after one full day.
- **Granularity.** Fabric works in 30-second timepoints, Capacity Watch in 1-minute steps.
- **History window.** Each query rebuilds carry-forward from three days before the period you ask
  for. A capacity that has been overloaded for longer than that may show less carry-forward than
  Fabric does.
- **Features Capacity Watch does not model:** P SKU autoscale, capacity overage billing (when it
  is enabled, throttling starts later), surge protection, and Autoscale Billing for Spark (Spark
  is billed pay-as-you-go and not smoothed).
- **Delivery.** Fabric delivers events on a best-effort basis. Duplicates are removed; a missing
  event is simply missing.

If you also stream the capacity **overview** events (optional, see
[03-eventstream.md](03-eventstream.md)), Fabric sends its own utilization and throttling measures
every 30 seconds, and `CapacityFabricCheck()` tells you how close the rebuilt numbers are.

## Sources

- [Understand the Fabric capacity throttling policy](https://learn.microsoft.com/fabric/enterprise/throttling)
- [Metrics app compute page: throttling and overages](https://learn.microsoft.com/fabric/enterprise/metrics-app-compute-page)
- [Metrics app calculations](https://learn.microsoft.com/fabric/enterprise/metrics-app-calculations)
- [Explore Fabric capacity operation events](https://learn.microsoft.com/fabric/real-time-hub/explore-fabric-capacity-operation-events)
- [Explore Fabric capacity overview events](https://learn.microsoft.com/fabric/real-time-hub/explore-fabric-capacity-overview-events)
- [Pause and resume your capacity](https://learn.microsoft.com/fabric/enterprise/pause-resume)
