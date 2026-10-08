#!/usr/bin/env python3
"""
Onboarding check: what you can monitor and where you can put Capacity Watch.
Read-only: it lists capacities and workspaces and changes nothing.

    az login
    pip install -r scripts/requirements.txt
    python scripts/check_access.py
    python scripts/check_access.py --capacity "my-f64" --workspace "Capacity Watch"

It checks:
  - which capacities you are a capacity admin on (needed to stream their events)
  - which workspaces you are Admin, Member or Contributor on, and whether they
    run on a Fabric (F) or Trial capacity (needed for the Eventstream and Eventhouse)
It cannot check tenant settings; see docs/01-onboarding.md for those.
"""
import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

FABRIC = "https://api.fabric.microsoft.com"
POWERBI = "https://api.powerbi.com"
SCOPES = {FABRIC: "https://api.fabric.microsoft.com/.default",
          POWERBI: "https://analysis.windows.net/powerbi/api/.default"}

_credential = None
_tokens = {}


def token(scope):
    global _credential
    if scope not in _tokens:
        if _credential is None:
            try:
                from azure.identity import AzureCliCredential, ChainedTokenCredential, InteractiveBrowserCredential
            except ImportError:
                sys.exit("Install azure-identity first: pip install -r scripts/requirements.txt")
            _credential = ChainedTokenCredential(AzureCliCredential(), InteractiveBrowserCredential())
        _tokens[scope] = _credential.get_token(scope).token
    return _tokens[scope]


def get_json(url):
    base = FABRIC if url.startswith(FABRIC) else POWERBI
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token(SCOPES[base])})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{e.code} from {url}: {body}")


def get_all(url):
    """Follow Fabric continuation links."""
    items = []
    while url:
        page = get_json(url)
        items.extend(page.get("value", []))
        url = page.get("continuationUri")
    return items


def signed_in_as():
    try:
        payload = token(SCOPES[FABRIC]).split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims.get("upn") or claims.get("unique_name") or claims.get("appid"), claims.get("tid")
    except Exception:
        return None, None


def is_fabric_sku(sku):
    return bool(sku) and (sku.startswith("F") or sku.startswith("P"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capacity", action="append", default=[], help="capacity you want to monitor (repeatable)")
    ap.add_argument("--workspace", help="workspace you want to put Capacity Watch in")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    a = ap.parse_args()

    user, tenant = signed_in_as()
    findings = {"signed_in_as": user, "tenant_id": tenant, "capacities": [], "workspaces": [], "problems": []}

    # Power BI's capacity list says what access you have on each capacity
    try:
        caps = get_json(POWERBI + "/v1.0/myorg/capacities").get("value", [])
    except RuntimeError as e:
        caps = []
        findings["problems"].append(f"Could not list capacities: {e}")
    by_id = {c["id"].lower(): c for c in caps}
    for c in caps:
        findings["capacities"].append({
            "name": c.get("displayName"), "id": c.get("id"), "sku": c.get("sku"), "region": c.get("region"),
            "state": c.get("state"), "your_access": c.get("capacityUserAccessRight"),
            "can_stream_events": c.get("capacityUserAccessRight") == "Admin" and is_fabric_sku(c.get("sku"))})

    try:
        wss = get_all(FABRIC + "/v1/workspaces?roles=Admin,Member,Contributor")
    except RuntimeError as e:
        wss = []
        findings["problems"].append(f"Could not list workspaces: {e}")
    for w in wss:
        if w.get("type") == "Personal":
            continue
        cap = by_id.get((w.get("capacityId") or "").lower())
        sku = cap.get("sku") if cap else None
        findings["workspaces"].append({
            "name": w.get("displayName"), "id": w.get("id"), "capacity": cap.get("displayName") if cap else None,
            "capacity_id": w.get("capacityId"), "sku": sku,
            "can_host": True if is_fabric_sku(sku) else (None if w.get("capacityId") and not cap else False)})

    for name in a.capacity:
        match = [c for c in findings["capacities"] if (c["name"] or "").lower() == name.lower()]
        if not match:
            findings["problems"].append(f"Capacity '{name}' is not visible to you. Ask a Fabric admin to make you a capacity admin on it.")
        elif not is_fabric_sku(match[0]["sku"]):
            findings["problems"].append(f"'{name}' is a {match[0]['sku']} capacity. Capacity events cover Fabric (F) and Premium (P) capacities.")
        elif not match[0]["can_stream_events"]:
            findings["problems"].append(f"You are not a capacity admin on '{name}' (access: {match[0]['your_access']}).")
    if a.workspace:
        match = [w for w in findings["workspaces"] if (w["name"] or "").lower() == a.workspace.lower()]
        if not match:
            findings["problems"].append(f"Workspace '{a.workspace}' not found among workspaces where you are Admin, Member or Contributor.")
        elif match[0]["can_host"] is False:
            findings["problems"].append(f"Workspace '{a.workspace}' is not on a Fabric or Trial capacity.")
    if not any(c["can_stream_events"] for c in findings["capacities"]):
        findings["problems"].append("You are not a capacity admin on any capacity, so you cannot stream capacity events yet.")

    if a.json:
        print(json.dumps(findings, indent=1))
        return
    print(f"Signed in as: {user or 'unknown'}  (tenant {tenant or 'unknown'})\n")
    print("Capacities you can see:")
    for c in findings["capacities"] or []:
        mark = "yes" if c["can_stream_events"] else "no "
        print(f"  [{mark}] {c['name']}  {c['sku']}  {c['region']}  {c['state']}  your access: {c['your_access']}")
    if not findings["capacities"]:
        print("  (none)")
    print("  [yes] = Fabric or Premium capacity where you are capacity admin, so you can stream its events\n")
    print("Workspaces where you can create items:")
    for w in findings["workspaces"]:
        mark = {True: "yes", False: "no ", None: "?  "}[w["can_host"]]
        print(f"  [{mark}] {w['name']}  on {w['capacity'] or w['capacity_id'] or 'no capacity'}  {w['sku'] or ''}")
    if not findings["workspaces"]:
        print("  (none)")
    print("  [yes] = on a Fabric capacity, can host the Eventstream and Eventhouse; [?] = capacity not visible to you\n")
    if findings["problems"]:
        print("To fix before you start:")
        for p in findings["problems"]:
            print("  - " + p)
    else:
        print("Looks good. Next: docs/02-eventhouse.md")


if __name__ == "__main__":
    main()
