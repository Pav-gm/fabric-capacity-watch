#!/usr/bin/env python3
"""
Independent Python model of the Capacity Watch math, used to cross-check
CapacityMinuteAll() in the Kusto emulator. It works per operation and per
minute with plain arrays, not with the difference arrays the KQL uses.

    python tests/reference.py events.jsonl --from 2026-10-08T00:00:00Z --to 2026-10-08T18:00:00Z > reference.tsv

Prints one row per capacity per minute. With --emit-fabric-events it instead
prints synthetic capacity overview events (Summary every 30 s, State on each
throttling change) built from the model, to test the optional overview tables.

Needs numpy.
"""
import argparse
import json
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

OPERATION = "Microsoft.Fabric.CapacityOperationEvents.Operation"
WARMUP_DAYS, BG_MIN, IA_MIN = 2, 1440, 5
HORIZONS = (10, 60, 1440)   # interactive delay, interactive rejection, background rejection


def parse(t):
    if t is None:
        return None
    t = t.replace("Z", "+00:00")
    if "." in t:  # trim fractions to microseconds
        head, rest = t.split(".", 1)
        frac, tz = rest[:-6], rest[-6:]
        t = f"{head}.{frac[:6]}{tz}"
    return datetime.fromisoformat(t)


def floor_min(dt):
    return dt.replace(second=0, microsecond=0)


def round_half_up(x):
    return math.floor(x + 0.5)


def sku_cu(sku):
    if sku and re.fullmatch(r"F\d+", sku):
        return float(sku[1:])
    return {"FT1": 64.0, "P1": 64.0, "P2": 128.0, "P3": 256.0, "P4": 512.0, "P5": 1024.0,
            "EM1": 8.0, "EM2": 16.0, "EM3": 32.0}.get(sku)


def stage(delay, ia, bg):
    if bg > 100:
        return "Background rejection"
    if ia > 100:
        return "Interactive rejection"
    if delay > 100:
        return "Interactive delay"
    return "None"


def model(events_path, frm, to, smoothing):
    scan_from = frm - timedelta(days=WARMUP_DAYS) - timedelta(minutes=BG_MIN) - timedelta(hours=1)
    ops = {}
    for line in open(events_path):
        e = json.loads(line)
        if e.get("type") != OPERATION:
            continue
        ts = parse(e["time"])
        if ts < scan_from:
            continue
        ops[e["id"]] = (ts, e["data"])          # duplicates collapse on the event id

    names, acts = {}, defaultdict(dict)
    for ts, d in ops.values():
        names[d["capacityId"]] = d["capacityName"]
        if d.get("activationId"):
            prev = acts[d["capacityId"]].get(d["activationId"])
            acts[d["capacityId"]][d["activationId"]] = min(prev, ts) if prev else ts
    next_act, restarts = {}, set()
    for cap, aa in acts.items():
        order = sorted(aa.items(), key=lambda kv: kv[1])
        for i, (act, start) in enumerate(order):
            next_act[(cap, act)] = order[i + 1][1] if i + 1 < len(order) else None
            if i > 0:
                restarts.add((cap, floor_min(start)))

    base = floor_min(scan_from)
    n = int((floor_min(to) - base).total_seconds() // 60) + 2
    idx = lambda dt: int((floor_min(dt) - base).total_seconds() // 60)
    caps = sorted(names)
    arr = {c: {"bg": np.zeros(n), "ia": np.zeros(n), "b": [np.zeros(n) for _ in HORIZONS],
               "sku": np.zeros(n), "rej": np.zeros(n)} for c in caps}

    for ts, d in ops.values():
        a = arr[d["capacityId"]]
        i_ts = idx(ts)
        cu = sku_cu(d.get("capacitySku")) or 0.0
        if 0 <= i_ts < n:
            a["sku"][i_ts] = max(a["sku"][i_ts], cu)
            if "reject" in (d.get("status") or "").lower():
                a["rej"][i_ts] += 1
        cu_s = (d.get("capacityUnitMs") or 0.0) / 1000.0
        if d.get("releaseType") == "Preview" or cu_s <= 0:
            continue
        interactive = (d.get("utilizationType") or "").lower() == "interactive"
        ws, we = parse(d.get("windowStartTime")), parse(d.get("windowEndTime"))
        if (smoothing == "window" and ws and we and we > ws and we - ws <= timedelta(hours=25)
                and abs(ws - ts) <= timedelta(hours=2)):
            win_start, win_len_min = ws, (we - ws).total_seconds() / 60.0
        else:
            win_start, win_len_min = ts, float(IA_MIN if interactive else BG_MIN)
        minutes = max(1, round_half_up(win_len_min))
        m0 = idx(win_start)
        m1 = m0 + minutes
        nxt = next_act.get((d["capacityId"], d.get("activationId")))
        if nxt is not None and idx(nxt) < m1:
            m1 = max(m0, idx(nxt))
        if m1 <= m0:
            continue
        rate = cu_s / (minutes * 60.0)
        lo, hi = max(m0, 0), min(m1, n)
        if lo >= hi:
            continue
        (a["ia"] if interactive else a["bg"])[lo:hi] += rate
        t = np.arange(lo, hi)
        for h, b in zip(HORIZONS, a["b"]):
            # booked at minute t for the next h minutes: the minutes of the window after t, capped at h
            b[lo:hi] += rate * np.minimum(h, (m1 - 1) - t) / h

    rows = []
    for cap in caps:
        a = arr[cap]
        sku = a["sku"].copy()
        known = np.nonzero(sku > 0)[0]
        if len(known):
            sku[:known[0]] = sku[known[0]]
            for i in range(known[0] + 1, n):
                if sku[i] == 0:
                    sku[i] = sku[i - 1]
        carry, streak = 0.0, 0
        for i in range(n - 1):
            m = base + timedelta(minutes=i)
            if m > to:
                break
            s = sku[i]
            util = (a["bg"][i] + a["ia"][i]) / s if s else 0.0
            carry = 0.0 if (cap, m) in restarts else max(0.0, carry + util - 1.0)
            if m >= frm:
                pcts = [100.0 * (a["b"][k][i] / s + carry / h) if s else 0.0 for k, h in enumerate(HORIZONS)]
                rows.append((cap, names[cap], m, s, 100.0 * util, carry, *pcts, stage(*pcts)))
    return rows


def emit_fabric_events(rows):
    """Synthetic overview events from the model: two Summary timepoints per minute, State on stage changes."""
    out, last_stage = [], {}
    for cap, name, m, s, util, carry, delay, ia, bg, st in rows:
        for half in (0, 30):
            ws = m + timedelta(seconds=half)
            data = {
                "capacityId": cap, "capacityName": name, "capacitySku": f"F{int(s)}" if s else None,
                "windowStartTime": ws.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                "windowEndTime": (ws + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                "baseCapacityUnits": int(s), "capacityUnitMs": util / 100.0 * s * 30000.0,
                "interactiveDelayThresholdPercentage": delay,
                "interactiveRejectionThresholdPercentage": ia,
                "backgroundRejectionThresholdPercentage": bg,
                "overageTotalCapacityUnitMs": carry * s * 60000.0,
                "capacityRegion": "east us",
            }
            out.append({"specversion": "1.0", "type": "Microsoft.Fabric.Capacity.Summary",
                        "source": "00000000-0000-0000-0000-000000000001", "subject": f"/capacities/{cap}",
                        "id": str(uuid.uuid4()), "time": (ws + timedelta(seconds=35)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                        "dataschemaversion": "1.0", "data": data})
        if last_stage.get(cap, "None") != st:
            reason = {"None": "NotOverloaded", "Interactive delay": "InteractiveDelay",
                      "Interactive rejection": "InteractiveRejected", "Background rejection": "AllRejected"}[st]
            out.append({"specversion": "1.0", "type": "Microsoft.Fabric.Capacity.State",
                        "source": "00000000-0000-0000-0000-000000000001", "subject": f"/capacities/{cap}",
                        "id": str(uuid.uuid4()), "time": m.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                        "dataschemaversion": "1.0",
                        "data": {"capacityId": cap, "capacityName": name, "capacitySku": f"F{int(s)}",
                                 "transitionTime": m.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
                                 "capacityState": "Active" if st == "None" else "Overloaded",
                                 "stateChangeReason": reason}})
            last_stage[cap] = st
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--smoothing", choices=["window", "type"], default="window")
    ap.add_argument("--emit-fabric-events", action="store_true")
    a = ap.parse_args()
    rows = model(a.events, floor_min(parse(a.frm)), floor_min(parse(a.to)), a.smoothing)
    if a.emit_fabric_events:
        for e in emit_fabric_events(rows):
            print(json.dumps(e, separators=(",", ":")))
        return
    print("capacity_name\tts\tutilization_pct\tcarry_min\tdelay_pct\tinteractive_reject_pct\tbackground_reject_pct\tthrottle_stage")
    for cap, name, m, s, util, carry, delay, ia, bg, st in rows:
        print(f"{name}\t{m.strftime('%Y-%m-%dT%H:%M:%SZ')}\t{util:.2f}\t{carry:.3f}\t{delay:.2f}\t{ia:.2f}\t{bg:.2f}\t{st}")


if __name__ == "__main__":
    main()
