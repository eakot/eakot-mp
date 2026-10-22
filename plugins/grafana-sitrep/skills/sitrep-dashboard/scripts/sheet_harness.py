#!/usr/bin/env python3
"""Run every status sheet of a generated dashboard against LIVE data, without deploying it. Needs `node`.

    python3 sheet_harness.py dashboard.json http://victoria:8428 [--var node=10.0.0.5:9100 --var job=hosts] [--panel 3]

Each sheet's instant targets go to the Prometheus-compatible API at the URL, with `$var` / `${var}` replaced
from `--var`. The answers are shaped like the frames Grafana hands the Business Text panel, the sheet's
helper code runs in node, and its text prints as the operator would read it: SITREP line, then each
`label .... value [TAG]`. Run it once per entity a templated page can show (every host, an empty variable,
a host that does not exist): a deploy-and-screenshot loop takes minutes per try, this takes seconds.

Exit 1 when a helper throws, or a sheet prints `undefined`, `NaN` or `[object Object]`, or has no SITREP line.

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
import urllib.parse
import urllib.request

SHIM = """const context = { handlebars: { registerHelper: (n, f) => { OUT = f().s; }, SafeString: function (s) { this.s = s; } },
  panelData: { series: %s } };
let OUT = null;
"""


def subst(expr, vars_):
    for k, v in sorted(vars_.items(), key=lambda kv: -len(kv[0])):
        expr = expr.replace("${%s}" % k, v).replace("$" + k, v)
    return expr.replace("$__interval", "5m").replace("$__rate_interval", "5m")


def query(base, expr):
    url = base.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.load(r)
    if d.get("status") != "success":
        raise RuntimeError(f"{d.get('errorType')}: {d.get('error')}")
    return d["data"]["result"]


def text(markup):
    t = markup.replace('</span><span class="ti">', " ")  # "01 Host", not "01Host"
    t = re.sub(r"</div>", "\n", t)
    t = re.sub(r'<span class="tg">([^<]*)</span>', r"  [\1]", t)
    t = re.sub(r'<span class="v">', " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return "\n".join(x for x in html.unescape(t).splitlines() if x.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard")
    ap.add_argument("prom_url")
    ap.add_argument("--var", action="append", default=[], help="name=value, repeatable")
    ap.add_argument("--panel", type=int, action="append", help="only these panel ids")
    a = ap.parse_args()
    vars_ = dict(v.split("=", 1) for v in a.var)
    d = json.load(open(a.dashboard))
    sheets = [p for p in d["panels"] if p.get("type") == "marcusolsson-dynamictext-panel"]
    sheets = [p for p in sheets if not a.panel or p["id"] in a.panel]
    fails = 0
    for p in sheets:
        series = []
        for t in p.get("targets", []):
            if "expr" not in t:
                print(f"  (skipped non-PromQL target {t.get('refId')})", file=sys.stderr)
                continue
            try:
                res = query(a.prom_url, subst(t["expr"], vars_))
            except Exception as e:  # a query the datasource rejects is a defect too
                print(f"[{p['id']}] {p['title']}: target {t['refId']} FAILED: {e}")
                fails += 1
                continue
            for r in res:
                labels = {k: v for k, v in r["metric"].items() if k != "__name__"}
                series.append({"refId": t["refId"], "fields": [{"type": "number", "labels": labels,
                                                                "values": [float(r["value"][1])]}]})
        js = SHIM % json.dumps(series) + p["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        print(f"── [{p['id']}] {p['title']}")
        if r.returncode:
            print("FAIL helper threw:", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode)
            fails += 1
            continue
        out = text(r.stdout)
        print(out + "\n")
        if re.search(r"\bundefined\b|\bNaN\b|\[object Object\]", out):
            print("FAIL undefined/NaN on the sheet\n")
            fails += 1
        if "SITREP" not in out:
            print("FAIL no SITREP line\n")
            fails += 1
    print(f"{len(sheets)} sheet(s), {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
