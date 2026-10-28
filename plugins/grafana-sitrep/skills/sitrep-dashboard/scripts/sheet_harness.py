#!/usr/bin/env python3
"""Run every status sheet of a generated dashboard against data, without deploying it. Needs `node`.

    python3 sheet_harness.py dashboard.json http://victoria:8428 [--var node=10.0.0.5:9100 --var job=hosts] [--panel 3]
    GRAFANA_TOKEN_FILE=... python3 sheet_harness.py dashboard.json --grafana https://grafana.example
    python3 sheet_harness.py dashboard.json --fixture fixture.json
    python3 sheet_harness.py dashboard.json --empty

Where the data comes from, one of:
- a Prometheus-compatible URL: each sheet's targets go to its /api/v1/query;
- `--grafana <url>`: the same queries through Grafana's datasource proxy
  (/api/datasources/proxy/uid/<uid>/api/v1/query, the uid from each target), for a datasource only Grafana can
  reach. The token is read as render_check.py reads it (GRAFANA_TOKEN or GRAFANA_TOKEN_FILE), never from argv;
- `--fixture file.json`: canned answers, `{refId: [[labels, value], ...]}` for every sheet, or
  `{"<panel id>": {refId: [...]}}` per sheet. Fill it from whatever query tool you have; it is also the shape
  of a regression test and of the hostile inputs (`constructor#5`, an apostrophe, `<b>`);
- `--empty`: every target answers nothing. A mandatory run: every number must read N/D, and a line tagged OK
  fails, because "no data" is not "fine".

`$var` / `${var}` are replaced from `--var`. The answers are shaped like the frames Grafana hands the Business Text
panel, the sheet's helper code runs in node, and its text prints as the operator would read it: the verdict line,
then each `label .... value [TAG]`. Run it once per entity a templated page can show (every host, an empty
variable, a host that does not exist): a deploy-and-screenshot loop takes minutes per try, this takes seconds.
Sheets inside collapsed rows run too. With a live source, every history chart's targets also run once as a range
query over the last 6 h: a query the datasource rejects (a 422) fails here, not on the page.

Exit 1 when a query fails, a helper throws, or a sheet prints `undefined`, `NaN` or `[object Object]`, or has no
verdict line (`class="br"`).

What it does not reproduce: non-PromQL targets (Infinity, SQL) are skipped, so a sheet reading them sees an
empty frame, which its N/D path must survive anyway. `__name__` is left out of the labels: do not let a sheet
depend on it — copy the name into a plain label with label_replace(..., "metric", "$1", "__name__", "(.*)").
"""
import argparse
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grafana_api  # noqa: E402

SHIM = """const context = { handlebars: { registerHelper: (n, f) => { OUT = f().s; }, SafeString: function (s) { this.s = s; } },
  panelData: { series: %s } };
let OUT = null;
"""
SHEET = "marcusolsson-dynamictext-panel"
RANGE_S, STEP_S = 6 * 3600, 300


def walk(panels):
    """Every panel, the children of collapsed rows included (they sit in row["panels"], not at the top)."""
    for p in panels:
        yield p
        yield from p.get("panels", [])


def subst(expr, vars_):
    """--var values, then Grafana's built-ins as the 6-hour run sees them. Longest name first: $__range_s before
    $__range."""
    now_ms = int(time.time()) * 1000
    built = {"__rate_interval": "5m", "__interval_ms": "300000", "__interval": "5m", "__range_ms": str(RANGE_S * 1000),
             "__range_s": str(RANGE_S), "__range": "6h", "__from": str(now_ms - RANGE_S * 1000), "__to": str(now_ms)}
    for k, v in sorted({**built, **vars_}.items(), key=lambda kv: -len(kv[0])):
        expr = expr.replace("${%s}" % k, v).replace("$" + k, v)
    return expr


class Live:
    """A Prometheus-compatible API, direct or through Grafana's datasource proxy."""

    def __init__(self, prom_url=None, grafana=None, vars_=None):
        self.prom, self.vars = prom_url, vars_ or {}
        self.grafana = grafana_api.base_of(grafana) if grafana else None
        self.tok = grafana_api.token() if grafana else None
        if self.grafana:
            grafana_api.preflight(self.grafana, self.tok)

    def base(self, panel, target):
        if self.prom:
            return self.prom.rstrip("/")
        uid = (target.get("datasource") or {}).get("uid")
        if not uid or uid == "-- Mixed --":
            uid = (panel.get("datasource") or {}).get("uid")
        if not uid or uid == "-- Mixed --":
            raise RuntimeError("no datasource uid on the target or the panel")
        return f"{self.grafana}/api/datasources/proxy/uid/{urllib.parse.quote(subst(uid, self.vars))}"

    def get(self, url):
        req = urllib.request.Request(url)
        if self.tok:
            req.add_header("Authorization", f"Bearer {self.tok}")
        try:
            with grafana_api.urlopen(req) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:  # a 422 carries the datasource's reason in its body
            try:
                d = json.load(e)
            except ValueError:
                raise RuntimeError(f"HTTP {e.code}") from None
        if d.get("status") != "success":
            raise RuntimeError(f"{d.get('errorType')}: {d.get('error')}")
        return d["data"]["result"]

    def instant(self, panel, target):
        q = urllib.parse.urlencode({"query": subst(target["expr"], self.vars)})
        return [(r["metric"], float(r["value"][1])) for r in self.get(f"{self.base(panel, target)}/api/v1/query?{q}")]

    def range(self, panel, target):
        now = int(time.time())
        q = urllib.parse.urlencode({"query": subst(target["expr"], self.vars), "start": now - RANGE_S, "end": now,
                                    "step": STEP_S})
        return self.get(f"{self.base(panel, target)}/api/v1/query_range?{q}")


class Fixture:
    """Canned answers: {refId: [[labels, value], ...]} for every sheet, or {"<panel id>": {...}} per sheet.
    A sheet or refId the fixture does not name fails: a typo must not pass as a quiet run. No data is `[]`."""

    def __init__(self, data, empty=False):
        self.data, self.empty = data, empty
        self.per_panel = bool(data) and all(re.fullmatch(r"\d+", k) for k in data)

    def instant(self, panel, target):
        if self.empty:
            return []
        refs = self.data
        if self.per_panel:
            if str(panel["id"]) not in self.data:
                raise KeyError(f"panel {panel['id']} is not in the fixture")
            refs = self.data[str(panel["id"])]
        if target["refId"] not in refs:
            raise KeyError(f"refId {target['refId']} is not in the fixture (give [] for no data)")
        return [(dict(lb), float(v)) for lb, v in refs[target["refId"]]]


def text(markup):
    t = markup.replace('</span><span class="ti">', " ")  # "01 Host", not "01Host"
    t = re.sub(r"</div>", "\n", t)
    t = re.sub(r'<span class="tg">([^<]*)</span>', r"  [\1]", t)
    t = re.sub(r'<span class="v">', " ", t)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)  # tags only: a literal "<20 %" in the text stays
    return "\n".join(x for x in html.unescape(t).splitlines() if x.strip())


def run_sheet(p, src, empty):
    """Print one sheet; return its failure count."""
    fails, series = 0, []
    for t in p.get("targets", []):
        if "expr" not in t:
            print(f"  (skipped non-PromQL target {t.get('refId')})", file=sys.stderr)
            continue
        try:
            res = src.instant(p, t)
        except Exception as e:  # a query the datasource rejects is a defect too
            print(f"[{p['id']}] {p['title']}: target {t['refId']} FAILED: {e}")
            fails += 1
            continue
        for labels, value in res:
            labels = {k: v for k, v in labels.items() if k != "__name__"}
            series.append({"refId": t["refId"], "fields": [{"type": "number", "labels": labels, "values": [value]}]})
    js = SHIM % json.dumps(series) + p["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    print(f"── [{p['id']}] {p['title']}")
    if r.returncode:
        print("FAIL helper threw:", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode)
        return fails + 1
    out = text(r.stdout)
    print(out + "\n")
    if re.search(r"\bundefined\b|\bNaN\b|\[object Object\]", out):
        print("FAIL undefined/NaN on the sheet\n")
        fails += 1
    if 'class="br"' not in r.stdout:  # the structure, not the label: a page may rename or drop "SITREP"
        print("FAIL no verdict line (brief())\n")
        fails += 1
    if empty:
        ok = [x.strip() for x in out.splitlines() if x.rstrip().endswith("[OK]")]
        if ok:
            print(f"FAIL OK on no data, must read N/D: {ok[:3]}\n")
            fails += 1
        # a sheet with no tags (a plain-language one) shows a made-up number only in its values: none may hold a digit
        vals = [html.unescape(re.sub(r"<[^>]*>", "", v)) for v in re.findall(
            r'<span class="(?:v|fx fxr)"[^>]*>(.*?)</span>', r.stdout)]
        made = [v for v in vals if re.search(r"\d", v)]
        if made:
            print(f"FAIL a number on no data, must read —: {made[:3]}\n")
            fails += 1
    return fails


def promql(p, t):
    """Whether a target is PromQL: its datasource type, or the panel's, names Prometheus or VictoriaMetrics.
    A carried Loki or SQL panel also has an `expr`, and the PromQL API would reject it."""
    ds = t.get("datasource") if isinstance(t.get("datasource"), dict) and t["datasource"].get("type") else p.get("datasource")
    kind = (ds or {}).get("type", "") if isinstance(ds, dict) else ""
    return "expr" in t and ("prometheus" in kind or "victoria" in kind)


def run_history(p, src):
    """Run a chart's PromQL targets once as range queries; return its failure count."""
    fails, got = 0, []
    for t in p.get("targets", []):
        if not promql(p, t):
            continue
        left = re.findall(r"\$\{?[A-Za-z_]\w*", subst(t["expr"], src.vars))  # not $1 of label_replace
        if left:
            print(f"  ([{p['id']}] target {t['refId']} skipped: {sorted(set(left))} not given with --var)", file=sys.stderr)
            continue
        try:
            got.append(f"{t['refId']} {len(src.range(p, t))} series")
        except Exception as e:
            print(f"[{p['id']}] {p.get('title')}: range target {t['refId']} FAILED: {e}")
            fails += 1
    if got:
        print(f"── [{p['id']}] {p.get('title')} (range, 6 h): {', '.join(got)}")
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard")
    ap.add_argument("prom_url", nargs="?")
    ap.add_argument("--grafana", metavar="URL", help="query through this Grafana's datasource proxy")
    ap.add_argument("--fixture", metavar="FILE", help="canned answers instead of a datasource")
    ap.add_argument("--empty", action="store_true", help="every target answers nothing")
    ap.add_argument("--var", action="append", default=[], help="name=value, repeatable")
    ap.add_argument("--panel", type=int, action="append", help="only these panel ids")
    a = ap.parse_args()
    if sum(map(bool, (a.prom_url, a.grafana, a.fixture, a.empty))) != 1:
        ap.error("give exactly one source: a Prometheus URL, --grafana, --fixture or --empty")
    vars_ = dict(v.split("=", 1) for v in a.var)
    if a.fixture or a.empty:
        src = Fixture(json.loads(Path(a.fixture).read_text()) if a.fixture else {}, empty=a.empty)
    else:
        src = Live(a.prom_url, a.grafana, vars_)
    d = json.loads(Path(a.dashboard).read_text())
    panels = [p for p in walk(d["panels"]) if not a.panel or p.get("id") in a.panel]
    sheets = [p for p in panels if p.get("type") == SHEET]
    fails = sum(run_sheet(p, src, a.empty) for p in sheets)
    charts = []
    if isinstance(src, Live):
        charts = [p for p in panels if p.get("type") not in (SHEET, "row") and any(promql(p, t) for t in p.get("targets", []))]
        fails += sum(run_history(p, src) for p in charts)
    print(f"{len(sheets)} sheet(s), {len(charts)} chart(s), {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
