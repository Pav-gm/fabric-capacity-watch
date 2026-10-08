#!/usr/bin/env python3
"""
Generate synthetic Fabric capacity operation events (CloudEvents, the same shape
Real-Time hub sends) for testing the Capacity Watch KQL without a real tenant.

Usage:
    python tests/sample_events.py > sample_events.jsonl
    python tests/sample_events.py --now 2026-10-08T18:00:00Z > sample_events.jsonl

Scenarios (all relative to --now, default: the current time):
  contoso-f64       F64. Steady background base near 84%, plus a 4 minute burst of
                    report queries 6 hours ago that pushes it just over 100%.
                    Expected: "Spikes, no throttling", alert stays ok.
                    Also contains duplicated events and a large non-billable
                    (Preview) operation that must NOT count toward utilization.
  contoso-f4        F4 overloaded at about 130% for two days, with rejected
                    report queries, then scaled up to F8 30 hours ago.
                    Expected: interactive and then background rejection, then recovery.
  contoso-f2        F2 near 95%, with report queries over the last 14 minutes
                    pushing it over 100%. With so little room left, Fabric starts
                    delaying interactive work. Expected: warning.
  contoso-restart   F2 overloaded at 150%, then paused and resumed 3 hours ago
                    (new activationId). Expected: carry-forward resets to 0.
"""
import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

TENANT = "00000000-0000-0000-0000-000000000001"
SUB = "00000000-0000-0000-0000-000000000002"


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f0Z")


def make_event(cap, ws, item, op_name, kind, start, duration_s, cu_s, *, utilization="Background",
               status="Success", release="Public", activation=None, sku=None, window_min=None,
               delay_ms=0, event_id=None, identity=("User", "someone@contoso.com")):
    end = start + timedelta(seconds=duration_s)
    emitted = end + timedelta(seconds=random.randint(2, 20))
    if window_min is None:
        window_min = 5 if utilization == "Interactive" else 24 * 60
    # Fabric smooths from the 30 second timepoint after the operation ends
    win_start = end.replace(microsecond=0) + timedelta(seconds=30 - end.second % 30)
    win_end = win_start + timedelta(minutes=window_min)
    return {
        "specversion": "1.0",
        "type": "Microsoft.Fabric.CapacityOperationEvents.Operation",
        "source": TENANT,
        "subject": f"/capacities/{cap['id']}/workspaces/{ws['id'] if ws else ''}/items/{item['id'] if item else ''}",
        "id": event_id or str(uuid.uuid4()),
        "time": iso(emitted),
        "dataschemaversion": "1.1",
        "data": {
            "subscriptionId": SUB,
            "tenantId": TENANT,
            "capacityId": cap["id"],
            "capacityName": cap["name"],
            "capacityFriendlyName": cap["name"],
            "capacitySku": sku or cap["sku"],
            "activationId": activation or cap["activation"],
            "workspaceId": ws["id"] if ws else None,
            "workspaceName": ws["name"] if ws else None,
            "itemId": item["id"] if item else None,
            "itemName": item["name"] if item else None,
            "itemKind": kind,
            "capacityUnitMs": round(cu_s * 1000.0, 3),
            "durationMs": int(duration_s * 1000),
            "throttlingDelayMs": delay_ms,
            "operationId": str(uuid.uuid4()),
            "status": status,
            "operationStartTime": iso(start),
            "releaseType": release,
            "operationName": op_name,
            "utilizationType": utilization,
            "windowStartTime": iso(win_start),
            "windowEndTime": iso(win_end),
            "isVirtualWorkspaceName": False,
            "isVirtualItemName": False,
            "workloadAutoscaleCapacityUnitsLimit": 0,
            "consumptionStartTime": iso(start),
            "identityType": identity[0],
            "identityValue": identity[1],
        },
    }


def cap(name, sku):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, name)), "name": name, "sku": sku,
            "activation": str(uuid.uuid5(uuid.NAMESPACE_DNS, name + "-a1"))}


def ws_item(ws_name, item_name):
    ws = {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, ws_name)), "name": ws_name}
    item = {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, ws_name + "/" + item_name)), "name": item_name}
    return ws, item


def steady_background(events, c, start, end, pct, sku_cu, ws, item, **kw):
    """One background op per minute sized so the 24 h smoothed load settles at pct of the SKU."""
    per_min = pct * sku_cu * 60.0
    t = start
    while t < end:
        cu = per_min * random.uniform(0.9, 1.1)
        events.append(make_event(c, ws, item, "Notebook Scheduled Run", "SynapseNotebook", t, 50, cu, **kw))
        t += timedelta(minutes=1)


def generate(now):
    random.seed(42)
    ev = []

    # ---- contoso-f64: a blip, not a capacity hit --------------------------------
    c = cap("contoso-f64", "F64")
    ws_etl, nb = ws_item("Sales", "nb_silver_gold")
    ws_rep, model = ws_item("Sales", "Sales model")
    steady_background(ev, c, now - timedelta(days=4), now, 0.84, 64, ws_etl, nb)
    t = now - timedelta(days=4)
    while t < now:  # light report traffic: about 0.5% of the SKU
        ev.append(make_event(c, ws_rep, model, "Query", "SemanticModel", t, 2, 0.005 * 64 * 60,
                             utilization="Interactive"))
        t += timedelta(minutes=1)
    burst = now - timedelta(hours=6)
    for i in range(13):  # 13 heavy queries in 4 minutes, about 17% of the SKU once smoothed
        q = make_event(c, ws_rep, model, "Query", "SemanticModel", burst + timedelta(seconds=18 * i), 15,
                       0.17 * 64 * 300 / 13, utilization="Interactive")
        ev.append(q)
        ev.append(json.loads(json.dumps(q)))  # delivered twice: must be counted once
    # a few heavier queries that Fabric smooths over 15 minutes instead of 5: tests "window" smoothing
    for i in range(6):
        ev.append(make_event(c, ws_rep, model, "Query", "SemanticModel", now - timedelta(hours=3, minutes=7 * i), 40,
                             0.02 * 64 * 900, utilization="Interactive", window_min=15))
    # a big preview (non-billable) job: must not count toward throttling
    ev.append(make_event(c, ws_etl, nb, "Preview Workload Run", "SynapseNotebook", now - timedelta(hours=2),
                         600, 2_000_000, release="Preview"))
    # Fabric's own operations have no workspace or item
    ev.append(make_event(c, None, None, "Fabric Events Publisher", None, now - timedelta(minutes=30), 1, 5,
                         identity=("FabricService", "Fabric Service")))

    # ---- contoso-f4: real overload, then scale-up to F8 -------------------------
    c = cap("contoso-f4", "F4")
    ws_etl, nb = ws_item("Finance", "pl_nightly")
    ws_rep, model = ws_item("Finance", "Finance model")
    resize = now - timedelta(hours=30)
    steady_background(ev, c, now - timedelta(days=4), resize, 1.30, 4, ws_etl, nb)
    steady_background(ev, c, resize, now, 0.50, 4, ws_etl, nb, sku="F8")
    t = now - timedelta(hours=60)
    while t < resize:  # report queries refused while the capacity is throttled
        ev.append(make_event(c, ws_rep, model, "Query", "SemanticModel", t, 0, 0.0, utilization="Interactive",
                             status="Rejected"))
        t += timedelta(minutes=10)

    # ---- contoso-f2: report queries pushing a tight capacity over 100% now -------
    c = cap("contoso-f2", "F2")
    ws_etl, nb = ws_item("Operations", "nb_load")
    ws_rep, model = ws_item("Operations", "Ops model")
    steady_background(ev, c, now - timedelta(days=4), now, 0.95, 2, ws_etl, nb)
    t = now - timedelta(minutes=14)
    while t < now - timedelta(seconds=30):
        ev.append(make_event(c, ws_rep, model, "Query", "SemanticModel", t, 5, 0.15 * 2 * 60,
                             utilization="Interactive"))
        t += timedelta(minutes=1)

    # ---- contoso-restart: overloaded, then paused and resumed --------------------
    c = cap("contoso-restart", "F2")
    ws_etl, nb = ws_item("Data Science", "nb_heavy")
    resume = now - timedelta(hours=3)
    steady_background(ev, c, now - timedelta(days=4), resume - timedelta(minutes=5), 1.50, 2, ws_etl, nb)
    steady_background(ev, c, resume, now, 0.20, 2, ws_etl, nb,
                      activation=str(uuid.uuid5(uuid.NAMESPACE_DNS, "contoso-restart-a2")))

    ev.sort(key=lambda e: e["time"])
    return ev


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", help="UTC time the scenarios end at, e.g. 2026-10-08T18:00:00Z")
    args = ap.parse_args()
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    for e in generate(now):
        print(json.dumps(e, separators=(",", ":")))
