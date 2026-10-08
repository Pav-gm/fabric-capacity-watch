#!/usr/bin/env python3
"""
End-to-end test of the KQL in a local Kusto emulator. Never runs against Fabric.

    docker run -d --name kustainer -e ACCEPT_EULA=Y -m 4G -p 8080:8080 \
        mcr.microsoft.com/azuredataexplorer/kustainer-linux:latest
    pip install numpy
    python tests/run_tests.py

What it does:
  1. creates a scratch database and deploys kql/01-tables.kql and kql/02-functions.kql
  2. loads synthetic capacity events (tests/sample_events.py) into the landing table
  3. checks the update policy filled CapacityOperations
  4. compares every minute of CapacityMinuteAll() with the Python model in
     tests/reference.py, for both smoothing modes
  5. checks that each scenario reads the way a capacity admin would expect
  6. loads synthetic capacity overview events and checks CapacityFabricCheck()
  7. runs every dashboard tile query in dashboard/ for every capacity
"""
import argparse
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

from kql import Kusto, KustoError  # noqa: E402
import reference  # noqa: E402
import sample_events  # noqa: E402

COLS = ["utilization_pct", "carry_min", "delay_pct", "interactive_reject_pct", "background_reject_pct"]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest(k, lines):
    for i in range(0, len(lines), 3000):
        k.mgmt('.ingest inline into table CapacityEventsRaw with (format="json", '
               'ingestionMappingReference="CapacityEventsRaw_mapping") <|\n' + "\n".join(lines[i:i + 3000]))


def settings_with(functions_kql, **overrides):
    """The CapacityWatchSettings() command from 02-functions.kql with some values replaced."""
    start = functions_kql.index(".create-or-alter function with (folder = \"CapacityWatch\", docstring = \"Capacity Watch settings\")")
    end = functions_kql.index("// ----", start)
    block = functions_kql[start:end]
    for key, value in overrides.items():
        import re
        block, n = re.subn(rf'"{key}":\s*[^,\n]+', f'"{key}": {value}', block)
        assert n == 1, key
    return ".execute database script <|\n" + block


def compare_with_reference(k, events_path, frm, to, smoothing):
    ref = {(r[1], r[2].strftime("%Y-%m-%dT%H:%M:%SZ")): r for r in reference.model(events_path, frm, to, smoothing)}
    rows = k.query(f"CapacityMinuteAll(datetime({iso(frm)}), datetime({iso(to)})) "
                   f"| project capacity_name, ts, {', '.join(COLS)}, throttle_stage")
    worst, stage_diff, missing = {c: 0.0 for c in COLS}, 0, 0
    for row in rows:
        key = (row["capacity_name"], row["ts"][:19] + "Z")
        r = ref.get(key)
        if r is None:
            missing += 1
            continue
        vals = dict(zip(COLS, [r[4], r[5], r[6], r[7], r[8]]))
        for c in COLS:
            worst[c] = max(worst[c], abs((row[c] or 0.0) - vals[c]))
        stage_diff += row["throttle_stage"] != r[9]
    ok = missing == 0 and len(rows) == len(ref) and stage_diff == 0 and all(
        worst[c] <= (0.0011 if c == "carry_min" else 0.011) for c in COLS)
    detail = f"{len(rows)} capacity-minutes, max diff " + ", ".join(f"{c} {worst[c]:.4f}" for c in COLS) + \
             f", stage mismatches {stage_diff}, unmatched {missing}"
    check(f"CapacityMinuteAll matches the Python model ({smoothing} smoothing)", ok, detail)


def by_name(rows):
    return {r["capacity_name"]: r for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster", default="http://localhost:8080")
    ap.add_argument("--database", default="CapacityWatchTest")
    ap.add_argument("--keep", action="store_true", help="keep the scratch database afterwards")
    a = ap.parse_args()
    if not (a.cluster.startswith("http://localhost") or a.cluster.startswith("http://127.0.0.1")):
        sys.exit("These tests load synthetic data. Run them only against the local emulator.")

    admin = Kusto(a.cluster, "NetDefaultDB")
    try:
        if a.database in {r["DatabaseName"] for r in admin.mgmt(".show databases")}:
            admin.mgmt(f".drop database {a.database} ifexists")
        admin.mgmt(f".create database {a.database} volatile")
    except KustoError as e:
        sys.exit(f"Cannot reach the Kusto emulator at {a.cluster}: {e}")
    k = Kusto(a.cluster, a.database)

    tables_kql = open(os.path.join(ROOT, "kql", "01-tables.kql"), encoding="utf-8").read()
    functions_kql = open(os.path.join(ROOT, "kql", "02-functions.kql"), encoding="utf-8").read()
    for name, text in (("01-tables.kql", tables_kql), ("02-functions.kql", functions_kql)):
        ok, res = k.run_script(text)
        check(f"{name} deploys", ok, f"{len(res)} commands")

    # ---- synthetic operation events --------------------------------------------------------
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    events = sample_events.generate(now)
    lines = [__import__("json").dumps(e, separators=(",", ":")) for e in events]
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    t0 = time.time()
    ingest(k, lines)
    counts = {r["t"]: r["n"] for r in k.query(
        "union withsource=t CapacityEventsRaw, CapacityOperations | summarize n = count() by t")}
    check("update policy copies every operation event", counts.get("CapacityOperations") == len(lines) ==
          counts.get("CapacityEventsRaw"), f"{counts}, loaded in {time.time() - t0:.0f}s")

    # alert changes are only reported for the last few minutes, so test them first
    k.run_script(settings_with(functions_kql, alert_window_min=30))
    changes = k.query("CapacityAlertChanges()")
    k.run_script(settings_with(functions_kql))
    check("CapacityAlertChanges reports contoso-f2 going from ok to warning",
          any(r["capacity_name"] == "contoso-f2" and r["previous_level"] == "ok" and r["alert_level"] == "warning"
              for r in changes), f"{[(r['capacity_name'], r['previous_level'], r['alert_level']) for r in changes]}")

    # ---- every minute against the independent model -------------------------------------
    frm, to = now - timedelta(hours=40), now - timedelta(minutes=30)
    compare_with_reference(k, tmp.name, frm, to, "window")
    k.run_script(settings_with(functions_kql, smoothing='"type"'))
    compare_with_reference(k, tmp.name, frm, to, "type")
    k.run_script(settings_with(functions_kql))

    # ---- scenarios -------------------------------------------------------------------------
    st = by_name(k.query("CapacityStatus()"))
    check("contoso-f64: short spike, not throttled",
          st["contoso-f64"]["state"] == "Spikes, no throttling" and st["contoso-f64"]["worst_stage_24h"] == "None",
          st["contoso-f64"]["verdict"])
    check("contoso-f2: little headroom, Fabric delays interactive work now",
          st["contoso-f2"]["state"] == "Throttling now" and st["contoso-f2"]["throttle_stage_now"] == "Interactive delay",
          st["contoso-f2"]["verdict"])
    check("contoso-f4: throttled earlier, recovered after the scale-up",
          st["contoso-f4"]["state"] == "Throttled in the last 24 hours" and st["contoso-f4"]["throttle_stage_now"] == "None",
          st["contoso-f4"]["verdict"])
    check("contoso-restart: pause and resume clears the overload",
          st["contoso-restart"]["restarts_24h"] == 1 and st["contoso-restart"]["carry_min"] == 0
          and st["contoso-restart"]["throttle_stage_now"] == "None", st["contoso-restart"]["verdict"])

    eps = k.query("CapacityOverageEpisodes(4d)")
    f4 = [e for e in eps if e["capacity_name"] == "contoso-f4"]
    check("contoso-f4 episode reaches background rejection with 180 rejected operations",
          len(f4) == 1 and f4[0]["throttle_stage"] == "Background rejection" and f4[0]["rejected_ops"] == 180,
          f"{[(e['episode_kind'], e['throttle_stage'], e['rejected_ops']) for e in f4]}")
    f64 = [e for e in eps if e["capacity_name"] == "contoso-f64"]
    check("contoso-f64 episode is a blip with no throttling",
          len(f64) == 1 and f64[0]["episode_kind"] == "Blip" and f64[0]["throttle_stage"] == "None",
          f"{[(e['episode_kind'], e['throttle_stage'], e['over_100_min']) for e in f64]}")

    al = by_name(k.query("CapacityAlerts()"))
    check("current alert levels", al["contoso-f2"]["alert_level"] == "warning" and
          all(al[c]["alert_level"] == "ok" for c in ("contoso-f64", "contoso-f4", "contoso-restart")),
          ", ".join(f"{c}={r['alert_level']}" for c, r in al.items()))

    day = k.query("CapacityDailyUsage(1d) | where capacity_name == 'contoso-f64' "
                  "| summarize cu_s = sum(cu_s), non_billable_cu_s = sum(non_billable_cu_s)")[0]
    check("preview operations are reported but not billed", day["non_billable_cu_s"] == 2000000.0,
          f"billable {day['cu_s']:.0f} CU-s, non-billable {day['non_billable_cu_s']:.0f} CU-s")
    top = k.query("CapacityTopItems(24)")
    check("top items include Fabric's own operations without a workspace",
          any(r["workspace_name"] == "(Fabric, no workspace)" for r in top), f"{len(top)} rows")
    timeline = k.query("CapacityTimeline(2h, 15m) | summarize actual = countif(isnotnull(actual_pct)), "
                       "projected = countif(isnotnull(projected_pct))")[0]
    check("timeline has actual and projected points", timeline["actual"] > 0 and timeline["projected"] > 0,
          f"{timeline}")
    thr = [r for r in k.query("CapacityThrottledOps(72)") if r["capacity_name"] == "contoso-f4"]
    check("contoso-f4: the rejected operations are listed by item",
          len(thr) == 1 and thr[0]["item_name"] == "Finance model" and thr[0]["rejected_ops"] == 180,
          f"{[(r['item_name'], r['rejected_ops']) for r in thr]}")
    hist = k.query("CapacityAlertHistory(24)")
    check("alert history shows contoso-f2 going from ok to warning",
          any(r["capacity_name"] == "contoso-f2" and r["previous_level"] == "ok" and r["alert_level"] == "warning"
              for r in hist), f"{len(hist)} changes")
    health = {r["target_table"]: r for r in k.query("CapacityWatchHealth()")}
    check("health: operation events arriving, overview events not streamed",
          health["CapacityOperations"]["status"] == "Receiving events"
          and health["CapacitySummary"]["status"] == "Not streamed (optional)",
          f"{health['CapacityOperations']['status']} / {health['CapacitySummary']['status']}")

    # ---- optional overview events -----------------------------------------------------------
    # same warm-up as the comparison above, so carry-forward starts from the same history
    rows = reference.model(tmp.name, now - timedelta(hours=40), now - timedelta(minutes=30), "window")
    fab = reference.emit_fabric_events([r for r in rows if r[2] >= now - timedelta(hours=22)])
    ingest(k, [__import__("json").dumps(e, separators=(",", ":")) for e in fab])
    fc = by_name(k.query("CapacityFabricCheck(1d)"))
    check("CapacityFabricCheck agrees with matching overview events", len(fc) == 4 and all(
        r["mean_abs_diff_utilization"] <= 0.01 and r["stage_agreement_pct"] >= 99.9 for r in fc.values()),
        ", ".join(f"{c}: {r['minutes_compared']} min, util diff {r['mean_abs_diff_utilization']}, "
                  f"stage agreement {r['stage_agreement_pct']}%" for c, r in fc.items()))
    health = {r["target_table"]: r for r in k.query("CapacityWatchHealth()")}
    check("health: overview events arriving", health["CapacitySummary"]["status"] == "Receiving events"
          and health["CapacityStateChanges"]["typed_rows_last_day"] > 0, health["CapacitySummary"]["status"])

    # ---- dashboard tiles --------------------------------------------------------------------
    dash = os.path.join(ROOT, "dashboard")
    labels = [r["capacity_label"] for r in k.query(open(os.path.join(dash, "parameter-capacity.kql"),
                                                         encoding="utf-8").read())]
    check("dashboard parameter lists every capacity", sorted(labels) == sorted(st), ", ".join(labels))
    errors, row_counts = [], {}
    for f in sorted(os.listdir(dash)):
        if not f.endswith(".kql") or f.startswith("parameter"):
            continue
        text = open(os.path.join(dash, f), encoding="utf-8").read()
        row_counts[f] = 0
        for label in labels:
            try:
                row_counts[f] += len(k.query(f'let _capacity = "{label}";\n' + text))
            except KustoError as e:
                errors.append(f"{f} for {label}: {str(e)[:300]}")
    # no rejected or delayed operations in the last 24 hours in the sample data, so that tile may be empty
    empty = [f for f, n in row_counts.items() if n == 0 and f != "09-throttled-operations.kql"]
    check(f"all {len(row_counts)} dashboard tile queries run and return rows", not errors and not empty,
          "; ".join(errors) or (f"empty: {empty}" if empty else ", ".join(f"{f[:2]}: {n}" for f, n in row_counts.items())))

    os.unlink(tmp.name)
    if not a.keep:
        admin.mgmt(f".drop database {a.database} ifexists")
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
