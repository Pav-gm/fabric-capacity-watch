#!/usr/bin/env python3
"""
Run KQL scripts and queries against a Fabric Eventhouse (or the local Kusto emulator).

Deploy the tables and functions:
    python scripts/kql.py deploy --cluster <query URI> --database <KQL database> kql/01-tables.kql kql/02-functions.kql

Run a query or a management command:
    python scripts/kql.py query --cluster <query URI> --database <KQL database> "CapacityStatus()"
    python scripts/kql.py query --cluster <query URI> --database <KQL database> ".show tables"
    python scripts/kql.py query ... --format json "CapacityWatchHealth()"

Run a dashboard tile query, giving its parameter a value:
    python scripts/kql.py query ... --let _capacity="My capacity" @dashboard/02-utilization.kql

<query URI> is on the KQL database page in Fabric ("Query URI", looks like
https://<id>.<region>.kusto.fabric.microsoft.com). Sign in first with `az login`;
the script uses your Azure CLI sign-in, or opens a browser if that fails.
For the local emulator use --cluster http://localhost:8080 (no sign-in).

Only needs the Python standard library, plus azure-identity for Fabric.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_RESOURCE = "https://kusto.kusto.windows.net"


class KustoError(Exception):
    pass


class Kusto:
    def __init__(self, cluster, database):
        self.cluster = cluster.rstrip("/")
        self.database = database
        self.local = self.cluster.startswith("http://localhost") or self.cluster.startswith("http://127.0.0.1")
        # the local emulator must not go through a proxy
        handlers = [urllib.request.ProxyHandler({})] if self.local else []
        self.opener = urllib.request.build_opener(*handlers)
        self._credential = None
        self._scope = None

    def _token(self):
        if self.local:
            return None
        if self._credential is None:
            try:
                from azure.identity import AzureCliCredential, ChainedTokenCredential, InteractiveBrowserCredential
            except ImportError:
                raise KustoError("Install azure-identity first: pip install -r scripts/requirements.txt")
            self._credential = ChainedTokenCredential(AzureCliCredential(), InteractiveBrowserCredential())
            self._scope = self._resource() + "/.default"
        return self._credential.get_token(self._scope).token

    def _resource(self):
        # Kusto tells clients which token audience it accepts
        try:
            with self.opener.open(self.cluster + "/v1/rest/auth/metadata", timeout=30) as r:
                meta = json.load(r)
            return meta.get("AzureAD", {}).get("KustoServiceResourceId") or DEFAULT_RESOURCE
        except Exception:
            return DEFAULT_RESOURCE

    def _post(self, kind, text, timeout=600):
        headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json",
                   "x-ms-app": "capacity-watch"}
        token = self._token()
        if token:
            headers["Authorization"] = "Bearer " + token
        body = json.dumps({"db": self.database, "csl": text}).encode("utf-8")
        req = urllib.request.Request(f"{self.cluster}/v1/rest/{kind}", data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(raw)["error"]
                msg = err.get("@message") or err.get("message") or raw
            except Exception:
                msg = raw
            raise KustoError(f"HTTP {e.code}: {msg[:3000]}")

    @staticmethod
    def _primary(result):
        tables = result.get("Tables", [])
        if not tables:
            return [], []
        t = tables[0]
        cols = [c["ColumnName"] for c in t["Columns"]]
        rows = [r for r in t["Rows"] if not isinstance(r, dict)]
        for r in t["Rows"]:
            if isinstance(r, dict) and r.get("Exceptions"):
                raise KustoError("Query failed: " + str(r["Exceptions"][0])[:3000])
        return cols, rows

    def query(self, text):
        """Run a query; returns a list of dicts."""
        cols, rows = self._primary(self._post("query", text))
        return [dict(zip(cols, r)) for r in rows]

    def mgmt(self, text):
        """Run a management command; returns a list of dicts."""
        cols, rows = self._primary(self._post("mgmt", text))
        return [dict(zip(cols, r)) for r in rows]

    def run_script(self, text):
        """Run an `.execute database script` file; returns (ok, [(first line, result, reason)])."""
        results = []
        for row in self.mgmt(text):
            first = (row.get("CommandText") or "").strip().splitlines()[0][:110]
            results.append((first, row.get("Result"), row.get("Reason") or ""))
        return all(r[1] == "Completed" for r in results), results


def print_table(rows, fmt):
    if fmt == "json":
        print(json.dumps(rows, indent=1, default=str))
        return
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    vals = [["" if r[c] is None else (json.dumps(r[c]) if isinstance(r[c], (dict, list)) else str(r[c])) for c in cols]
            for r in rows]
    if fmt == "tsv":
        print("\t".join(cols))
        for v in vals:
            print("\t".join(v))
        return
    if fmt == "vertical":
        for v in vals:
            print("-" * 60)
            for c, x in zip(cols, v):
                print(f"{c:>30}: {x}")
        return
    width = [min(48, max([len(c)] + [len(v[i]) for v in vals])) for i, c in enumerate(cols)]
    print("  ".join(c[:w].ljust(w) for c, w in zip(cols, width)))
    for v in vals:
        print("  ".join(x[:w].ljust(w) for x, w in zip(v, width)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("deploy", "query"):
        p = sub.add_parser(name)
        p.add_argument("--cluster", required=True, help="Query URI of the KQL database, or http://localhost:8080")
        p.add_argument("--database", required=True, help="KQL database name")
    sub.choices["deploy"].add_argument("files", nargs="+", help=".kql files that start with .execute database script")
    sub.choices["query"].add_argument("text", help="KQL query, or @file.kql to read it from a file")
    sub.choices["query"].add_argument("--format", choices=["table", "vertical", "tsv", "json"], default="table")
    sub.choices["query"].add_argument("--let", action="append", default=[], metavar="NAME=VALUE",
                                      help="define a string parameter before the query, e.g. _capacity=\"My capacity\"")
    a = ap.parse_args()

    k = Kusto(a.cluster, a.database)
    try:
        if a.cmd == "deploy":
            all_ok = True
            for f in a.files:
                text = open(f, encoding="utf-8").read()
                ok, results = k.run_script(text)
                print(f"== {f}")
                for first, result, reason in results:
                    print(f"{'ok  ' if result == 'Completed' else 'FAIL'} {first}")
                    if result != "Completed":
                        print("     " + reason[:3000])
                all_ok = all_ok and ok
            sys.exit(0 if all_ok else 1)
        text = open(a.text[1:], encoding="utf-8").read() if a.text.startswith("@") else a.text
        lets = []
        for item in a.let:
            name, sep, value = item.partition("=")
            if not sep or not name.strip().isidentifier():
                ap.error(f"--let expects NAME=VALUE, got {item!r}")
            value = value.replace("\\", "\\\\").replace('"', '\\"')
            lets.append(f'let {name.strip()} = "{value}";\n')
        # management commands (.show, .alter, ...) go to the management endpoint
        if text.lstrip().startswith("."):
            print_table(k.mgmt(text), a.format)
        else:
            print_table(k.query("".join(lets) + text), a.format)
    except KustoError as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
