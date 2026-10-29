#!/usr/bin/env python3
"""Run every status sheet of a generated dashboard against data, without deploying it. Needs `node`.

    python3 sheet_harness.py dashboard.json http://victoria:8428 [--var node=10.0.0.5:9100 --var job=hosts] [--panel 3]
    GRAFANA_TOKEN_FILE=... python3 sheet_harness.py dashboard.json --grafana https://grafana.example
    python3 sheet_harness.py dashboard.json --fixture fixture.json
    python3 sheet_harness.py dashboard.json --empty
    python3 sheet_harness.py dashboard.json --fixture fixture.json --empty B,7:C [--allow-ok "schemas without"]
    python3 sheet_harness.py dashboard.json --dump-sql sql/ --var schema=prod

Where the data comes from, one of:
- a Prometheus-compatible URL: each sheet's targets go to its /api/v1/query;
- `--grafana <url>`: the same queries through Grafana's datasource proxy
  (/api/datasources/proxy/uid/<uid>/api/v1/query, the uid from each target), for a datasource only Grafana can
  reach. The token is read as render_check.py reads it (GRAFANA_TOKEN or GRAFANA_TOKEN_FILE), never from argv;
- `--fixture file.json`: canned answers, `{refId: [[labels, value], ...]}` for every sheet, or
  `{"<panel id>": {refId: ...}}` per sheet. A refId of an SQL (or Infinity) target takes a table instead:
  `{"rows": [{"col": value, ...}, ...]}`, one frame with one field per column, typed from its first non-null
  value — the shape the Postgres plugin hands Business Text, and what `table(ref)` reads. `[]` is no data for
  either. Fill it from whatever query tool you have; it is also the shape of a regression test and of the
  hostile inputs (`constructor#5`, an apostrophe, `<b>`);
- `--empty`: every target answers nothing. A mandatory run: every number must read N/D, and a line tagged OK
  fails, because "no data" is not "fine".

`--empty REF[,REF]` together with a source empties only the named refIds (`7:C` = refId C of panel 7 only): one
query of a page coming back empty while the others are full, which is how a source really fails. A line may then
stay OK when its value comes from a query that still answers; name each such line with `--allow-ok <text>` (a
substring of the line), so the exception is written down. The "OK on no data" and "number on no data" checks
run as in a full `--empty`.

SQL targets (`rawSql`) run live only through `--grafana`, by Grafana's `/api/ds/query`, which runs any SQL the
datasource account may: a guarded setup blocks it, and then the fixture is the route. `--dump-sql DIR` writes
each SQL target, its `--var`s substituted and Grafana's macros (`$__timeFilter(...)`) left as they are, to
`DIR/<panel>-<refId>.sql` and exits: run them on a local copy of the schema, or hand them to someone with a
read-only DSN.

`$var` / `${var}` are replaced from `--var`, whole names only (`$schema` never eats the start of `$schema_type`). The same
values feed `context.grafana.replaceVariables` inside the sheet. The answers are shaped like the frames Grafana hands the Business Text
panel, the sheet's helper code runs in node, and its text prints as the operator would read it: the verdict line,
then each `label .... value [TAG]`. Run it once per entity a templated page can show (every host, an empty
variable, a host that does not exist): a deploy-and-screenshot loop takes minutes per try, this takes seconds.
Sheets inside collapsed rows run too. With a live source, every history chart's targets also run once as a range
query over the last 6 h: a query the datasource rejects (a 422) fails here, not on the page.

Exit 1 when a query fails, a helper throws, or a sheet prints `undefined`, `NaN` or `[object Object]`, or has no
verdict line (`class="br"`).

What it does not reproduce: an Infinity target runs only from a fixture (live, it is skipped and reported),
and an SQL target's live answer needs `--grafana`. `__name__` is left out of the labels: do not let a sheet
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

# --var values reach the sheet as context.grafana.replaceVariables, longest name first (globalThis.VARS_IN, set by
# render()).
SHIM = """const context = { handlebars: { registerHelper: (n, f) => { OUT = f().s; }, SafeString: function (s) { this.s = s; } },
  panelData: { series: %s },
  grafana: { replaceVariables: (s) => (globalThis.VARS_IN || []).reduce((o, [k, v]) =>
    o.replace(new RegExp('[$][{]' + k + '[}]|[$]' + k + '(?![A-Za-z0-9_])', 'g'), () => v), String(s)) } };
let OUT = null;
"""
SHEET = "marcusolsson-dynamictext-panel"
RANGE_S, STEP_S = 6 * 3600, 300


def walk(panels):
    """Every panel, the children of collapsed rows included (they sit in row["panels"], not at the top)."""
    for p in panels:
        yield p
        yield from p.get("panels", [])


def subst(expr, vars_, builtins=True):
    """--var values, then Grafana's built-ins as the 6-hour run sees them. Longest name first: $__range_s before
    $__range, and a whole name only: $schema never eats the start of $schema_type. SQL leaves the built-ins (and macros such as $__timeFilter) to the
    datasource: builtins=False."""
    now_ms = int(time.time()) * 1000
    built = {} if not builtins else {"__rate_interval": "5m", "__interval_ms": "300000", "__interval": "5m", "__range_ms": str(RANGE_S * 1000),
             "__range_s": str(RANGE_S), "__range": "6h", "__from": str(now_ms - RANGE_S * 1000), "__to": str(now_ms)}
    for k, v in sorted({**built, **vars_}.items(), key=lambda kv: -len(kv[0])):
        # a whole name only: with $schema given and $schema_type not, "$schema_type" must stay, not become "prod_type"
        expr = re.sub(r"\$\{%s\}|\$%s(?!\w)" % (re.escape(k), re.escape(k)), lambda m: v, expr)
    return expr


class Live:
    """A Prometheus-compatible API, direct or through Grafana's datasource proxy."""

    def __init__(self, prom_url=None, grafana=None, vars_=None):
        self.prom, self.vars, self.unchecked, self.ds_cache = prom_url, vars_ or {}, 0, {}
        self.grafana = grafana_api.base_of(grafana) if grafana else None
        self.tok = grafana_api.token() if grafana else None
        if self.grafana:
            if not self.tok:
                raise SystemExit("--grafana needs a service-account token: set GRAFANA_TOKEN or GRAFANA_TOKEN_FILE")
            grafana_api.preflight(self.grafana, self.tok)

    def resolve(self, panel, target):
        """(type, uid) of a target's datasource; type None when it cannot be told. A mixed panel's untyped target,
        or a legacy datasource given by name, is looked up in Grafana when there is one."""
        ref = target.get("datasource")
        if not ref or (isinstance(ref, dict) and ref.get("uid") in (None, "-- Mixed --")):
            ref = panel.get("datasource")
        if isinstance(ref, dict) and ref.get("uid") == "-- Mixed --":
            ref = None
        kind = ref.get("type") if isinstance(ref, dict) else None
        uid = ref.get("uid") if isinstance(ref, dict) else None
        if (not kind or kind == "datasource") and self.grafana and ref:
            key = subst(uid if isinstance(ref, dict) else str(ref), self.vars)
            if key not in self.ds_cache:
                path = f"/api/datasources/uid/{urllib.parse.quote(key)}" if isinstance(ref, dict) else \
                    f"/api/datasources/name/{urllib.parse.quote(key)}"
                try:
                    d = grafana_api.call(self.grafana, path, self.tok)
                    self.ds_cache[key] = (d.get("type"), d.get("uid"))
                except Exception:
                    self.ds_cache[key] = (None, None)
            kind, uid = self.ds_cache[key]
        return (None if kind == "datasource" else kind), uid

    def base(self, panel, target):
        if self.prom:
            return self.prom.rstrip("/")
        uid = self.resolve(panel, target)[1]
        if not uid:
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
                raise RuntimeError(f"HTTP {e.code} {e.msg}") from None
            if not isinstance(d, dict) or "status" not in d:  # Grafana's own refusal, not the datasource's
                raise RuntimeError(f"HTTP {e.code} {(d or {}).get('message') if isinstance(d, dict) else e.msg}") from None
        if d.get("status") != "success":
            raise RuntimeError(f"{d.get('errorType')}: {d.get('error')}")
        return d["data"]["result"]

    def instant(self, panel, target):
        q = urllib.parse.urlencode({"query": subst(target["expr"], self.vars)})
        return [(r["metric"], float(r["value"][1])) for r in self.get(f"{self.base(panel, target)}/api/v1/query?{q}")]

    def frames(self, panel, target):
        if is_sql(target):
            if not self.grafana:
                raise Unchecked("an SQL target runs only through --grafana (its /api/ds/query); or use a fixture")
            return self.sql(panel, target)
        if "expr" not in target:
            raise Unchecked("not a PromQL or SQL target (Infinity?): give it in a fixture")
        return number_frames(target["refId"], self.instant(panel, target))

    def sql(self, panel, target):
        """One SQL target through Grafana's /api/ds/query: the datasource expands its own macros over the last 6 h."""
        uid = self.resolve(panel, target)[1]
        if not uid:
            raise RuntimeError("no datasource uid on the target or the panel")
        now_ms = int(time.time()) * 1000
        q = dict(target, rawSql=subst(target["rawSql"], self.vars, builtins=False),
                 datasource={"uid": subst(uid, self.vars)}, format=target.get("format") or "table")
        body = {"from": str(now_ms - RANGE_S * 1000), "to": str(now_ms), "queries": [q]}
        failed = None
        try:
            d = grafana_api.call(self.grafana, "/api/ds/query", self.tok, body)
        except urllib.error.HTTPError as e:  # a rejected query: 400 with the datasource's reason in results
            try:
                d = json.load(e)
            except ValueError:
                raise RuntimeError(f"HTTP {e.code} {e.msg}") from None
            if not isinstance(d, dict) or "results" not in d:
                raise RuntimeError(f"HTTP {e.code} {(d or {}).get('message') if isinstance(d, dict) else e.msg}") from None
            failed = e.code
        # a refused or failed query is never read as "no data": no answer for the refId, an error, or an HTTP
        # error status with no reason given all fail the target
        res = (d.get("results") or {}).get(target["refId"])
        if not isinstance(res, dict):
            raise RuntimeError(f"no result for refId {target['refId']}" + (f" (HTTP {failed})" if failed else ""))
        if res.get("error") or failed or (res.get("status") or 200) >= 400:
            raise RuntimeError(res.get("error") or f"HTTP {failed or res.get('status')}, no reason given")
        out = []
        for fr in res.get("frames") or []:
            vals = (fr.get("data") or {}).get("values") or []
            fields = [{"name": f.get("name"), "type": f.get("type") or "other", "labels": f.get("labels") or {},
                       "values": vals[i] if i < len(vals) else []}
                      for i, f in enumerate((fr.get("schema") or {}).get("fields") or [])]
            out.append({"refId": target["refId"], "fields": fields})
        return out

    def range(self, panel, target):
        now = int(time.time())
        q = urllib.parse.urlencode({"query": subst(target["expr"], self.vars), "start": now - RANGE_S, "end": now,
                                    "step": STEP_S})
        return self.get(f"{self.base(panel, target)}/api/v1/query_range?{q}")


class Unchecked(Exception):
    """A target this source cannot run: reported and counted, never passed over in silence."""


def is_sql(t):
    return "rawSql" in t


def query_of(t):
    return t.get("rawSql") if is_sql(t) else t.get("expr")


def number_frames(ref, res):
    """Instant-query answers as Grafana hands them to Business Text: one number field per series."""
    return [{"refId": ref, "fields": [{"type": "number", "labels": {k: v for k, v in lb.items() if k != "__name__"},
                                       "values": [value]}]} for lb, value in res]


def field_type(values):
    v = next((x for x in values if x is not None), None)
    return "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else "string"


def table_frame(ref, rows):
    """{"rows": [{col: value}]} -> one frame, one field per column in first-seen order, typed from its first
    non-null value: the shape a Postgres or MySQL target hands Business Text."""
    names = []
    for r in rows:
        names += [k for k in r if k not in names]
    fields = []
    for n in names:
        vals = [r.get(n) for r in rows]
        fields.append({"name": n, "type": field_type(vals), "labels": {}, "values": vals})
    return [{"refId": ref, "fields": fields}]


class Fixture:
    """Canned answers: {refId: [[labels, value], ...] | {"rows": [...]}} for every sheet, or {"<panel id>": {...}}
    per sheet. A sheet or refId the fixture does not name fails: a typo must not pass as a quiet run. No data is
    `[]`."""

    def __init__(self, data):
        self.data = data
        self.per_panel = bool(data) and all(re.fullmatch(r"\d+", k) for k in data)

    def frames(self, panel, target):
        refs = self.data
        if self.per_panel:
            if str(panel["id"]) not in self.data:
                raise KeyError(f"panel {panel['id']} is not in the fixture")
            refs = self.data[str(panel["id"])]
        if target["refId"] not in refs:
            raise KeyError(f"refId {target['refId']} is not in the fixture (give [] for no data)")
        got = refs[target["refId"]]
        if isinstance(got, dict):
            if not isinstance(got.get("rows"), list):
                raise KeyError(f"refId {target['refId']}: a table is {{\"rows\": [{{column: value}}, ...]}}")
            return table_frame(target["refId"], got["rows"])
        return number_frames(target["refId"], [(dict(lb), float(v)) for lb, v in got])


class Empty:
    """Every target answers nothing, or (`refs`) only the named ones: "A" any panel's A, "7:A" panel 7's."""

    def __init__(self, src=None, refs=None):
        self.src, self.refs, self.matched = src, refs, set()

    def emptied(self, panel, target):
        if self.refs is None:
            return True
        hit = {target["refId"], f"{panel['id']}:{target['refId']}"} & self.refs
        self.matched |= hit
        return bool(hit)

    def frames(self, panel, target):
        return [] if self.emptied(panel, target) else self.src.frames(panel, target)

    def __getattr__(self, k):  # resolve, range, vars, unchecked: the wrapped live source's
        return getattr(self.src, k)


def text(markup):
    t = markup.replace('</span><span class="ti">', " ")  # "01 Host", not "01Host"
    t = re.sub(r"</div>", "\n", t)
    t = re.sub(r'<span class="tg">([^<]*)</span>', r"  [\1]", t)
    t = re.sub(r'<span class="v">', " ", t)
    t = re.sub(r"</?[a-zA-Z][^>]*>", "", t)  # tags only: a literal "<20 %" in the text stays
    return "\n".join(x for x in html.unescape(t).splitlines() if x.strip())


PROBE = 987654.0


def live(t):
    """A target Grafana would run: a query that is not blank, and not hidden."""
    return bool(str(query_of(t) or "").strip()) and not t.get("hide")


def fed(t):
    """A target the sheet reads: a live query, or a target with no query field at all (Infinity), which only a
    fixture can answer."""
    return not t.get("hide") and (live(t) or ("expr" not in t and "rawSql" not in t))


# The probe's labels answer any key, so a sheet that reads r.labels.repo renders instead of throwing. Only the
# probe's own frames: a frame that kept its real data keeps its real labels.
PROBE_SHIM = "SERIES_IN.forEach((f) => { if (f.probe) f.fields.forEach((x) => { x.labels = new Proxy({}, { get: (o, k) => " \
    "(typeof k === 'string' && k !== 'toJSON' && k !== 'then' ? 'probe' : undefined) }); }); });\n"


def render(p, series, probe=False, vars_=None):
    data = json.dumps(series)
    if probe:
        data = "(() => { const SERIES_IN = %s; %s return SERIES_IN; })()" % (data, PROBE_SHIM)
    v = json.dumps(sorted((vars_ or {}).items(), key=lambda kv: -len(kv[0])))
    js = f"globalThis.VARS_IN = {v};\n" + SHIM % data + p["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True)


def values(markup):
    """The value of every contents line and every right-aligned cell, as text."""
    return [html.unescape(re.sub(r"<[^>]*>", "", v)) for v in re.findall(
        r'<span class="(?:v|fx fxr)"[^>]*>(.*?)</span>', markup)]


def run_sheet(p, src, vars_=None, allow_ok=()):
    """Print one sheet; return its failure count."""
    fails, series, emptied = 0, [], []
    for t in p.get("targets", []):
        if not fed(t):
            continue
        if isinstance(src, Empty) and src.emptied(p, t):
            emptied.append(t)
        try:
            series += src.frames(p, t)
        except Unchecked as e:
            print(f"UNCHECKED [{p['id']}] {p['title']}: target {t.get('refId')} — {e}")
            src.unchecked = getattr(src, "unchecked", 0) + 1
        except KeyError as e:
            if live(t):
                print(f"[{p['id']}] {p['title']}: target {t['refId']} FAILED: {e}")
                fails += 1
            else:  # an Infinity target the fixture does not name: the sheet sees no frame for it
                print(f"  (skipped target {t.get('refId')}: no query field, and not in the fixture)", file=sys.stderr)
        except Exception as e:  # a query the datasource rejects is a defect too
            print(f"[{p['id']}] {p['title']}: target {t['refId']} FAILED: {e}")
            fails += 1
    r = render(p, series, vars_=vars_)
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
    if emptied:
        ok = [x.strip() for x in out.splitlines() if x.rstrip().endswith("[OK]")]
        allowed = [x for x in ok if any(a in x for a in allow_ok)]
        if allowed:
            print(f"allowed OK (--allow-ok): {allowed[:3]}")
        ok = [x for x in ok if x not in allowed]
        if ok:
            print(f"FAIL OK on no data, must read N/D: {ok[:3]}\n")
            fails += 1
        # A sheet with no tags (a plain-language one) shows a made-up number only in its values. A value with a digit
        # that also shows when the emptied targets answer PROBE is static text ("30 days"), or comes from a target that
        # still answers; one that shows only on no data was invented for it ("0 people").
        keep = [f for f in series if f["refId"] not in {t["refId"] for t in emptied}]
        probe = keep + [{"refId": t["refId"], "probe": True, "fields": [{"name": "value", "type": "number", "labels": {},
                                                                          "values": [PROBE]}]} for t in emptied]
        pr = render(p, probe, probe=True, vars_=vars_)
        static = set(values(pr.stdout))
        made = [v for v in values(r.stdout) if re.search(r"\d", v) and v not in static]
        if made and pr.returncode:
            print(f"NOTE numbers on no data, not checked (the sheet throws on probe data): {made[:3]}\n")
        elif made:
            print(f"FAIL a number on no data, must read —: {made[:3]}\n")
            fails += 1
    return fails


def is_promql(kind):
    return "prometheus" in kind or "victoria" in kind


def run_history(p, src):
    """Run a chart's PromQL targets once as range queries; return its failure count. A carried Loki or SQL panel
    also has an `expr`, so the datasource type decides; a target whose type cannot be told is reported UNCHECKED,
    never passed over in silence."""
    fails, got = 0, []
    for t in p.get("targets", []):
        if not live(t) or is_sql(t):  # a carried SQL table or chart: its query is not range-checked here
            continue
        kind = src.resolve(p, t)[0]
        if kind is None:
            print(f"UNCHECKED [{p['id']}] {p.get('title')}: target {t['refId']} — datasource type unknown "
                  "(no type on the target or panel; --grafana resolves it)")
            src.unchecked += 1
            continue
        if not is_promql(kind):
            print(f"  ([{p['id']}] target {t['refId']} skipped: a {kind} datasource)", file=sys.stderr)
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


def dump_sql(panels, out, vars_):
    """Every SQL target, --vars substituted, Grafana's macros left: to run on a local copy of the schema."""
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in panels:
        for t in p.get("targets", []):
            if is_sql(t) and live(t):
                f = out / f"{p['id']}-{t['refId']}.sql"
                sql = subst(t["rawSql"], vars_, builtins=False)
                f.write_text(sql.rstrip() + "\n")
                left = sorted(set(re.findall(r"\$\{?(?!__)[A-Za-z_]\w*", sql)))  # not $__timeFilter, not $1
                print(f"{f}  [{p.get('title')}]" + (f"  unset: {left}" if left else ""))
                n += 1
    print(f"{n} SQL target(s) written")
    return 0 if n else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dashboard")
    ap.add_argument("prom_url", nargs="?")
    ap.add_argument("--grafana", metavar="URL", help="query through this Grafana's datasource proxy")
    ap.add_argument("--fixture", metavar="FILE", help="canned answers instead of a datasource")
    ap.add_argument("--empty", nargs="?", const="*", metavar="REF[,REF]",
                    help="every target answers nothing; with REFs and a source, only these refIds (A, or 7:A)")
    ap.add_argument("--allow-ok", action="append", default=[], metavar="TEXT",
                    help="with --empty REFs: a line containing TEXT may stay OK (its value comes from another query)")
    ap.add_argument("--dump-sql", metavar="DIR", help="write every SQL target to DIR/<panel>-<refId>.sql and exit")
    ap.add_argument("--var", action="append", default=[], help="name=value, repeatable")
    ap.add_argument("--panel", type=int, action="append", help="only these panel ids")
    a = ap.parse_args()
    vars_ = dict(v.split("=", 1) for v in a.var)
    d = json.loads(Path(a.dashboard).read_text())
    panels = [p for p in walk(d["panels"]) if not a.panel or p.get("id") in a.panel]
    if a.dump_sql:
        return dump_sql(panels, Path(a.dump_sql), vars_)
    partial = a.empty not in (None, "*")
    if sum(map(bool, (a.prom_url, a.grafana, a.fixture, a.empty == "*"))) != 1:
        ap.error("give exactly one source: a Prometheus URL, --grafana, --fixture or --empty"
                 + (" (--empty REF,... empties part of a source, it is not one)" if partial else ""))
    if a.allow_ok and not partial:
        ap.error("--allow-ok goes with --empty REF,...: with every target empty, no line may read OK")
    if a.empty == "*":
        src = Empty()
    else:
        src = Fixture(json.loads(Path(a.fixture).read_text())) if a.fixture else Live(a.prom_url, a.grafana, vars_)
        if partial:
            src = Empty(src, {x.strip() for x in a.empty.split(",") if x.strip()})
    sheets = [p for p in panels if p.get("type") == SHEET]
    fails = sum(run_sheet(p, src, vars_, a.allow_ok) for p in sheets)
    if partial and src.refs - src.matched:  # a typo in --empty must not pass as a clean empty run
        print(f"FAIL --empty {sorted(src.refs - src.matched)}: no target on a selected sheet has that refId")
        fails += 1
    charts = []
    if isinstance(src, Live) or (isinstance(src, Empty) and isinstance(src.src, Live)):
        charts = [p for p in panels if p.get("type") not in (SHEET, "row") and any(live(t) and not is_sql(t) for t in p.get("targets", []))]
        fails += sum(run_history(p, src) for p in charts)
    # a run that checked nothing is not a pass
    missing = sorted(set(a.panel or []) - {p.get("id") for p in panels})
    if missing:
        print(f"FAIL --panel {missing}: no such panel")
        fails += 1
    if not sheets and not charts:
        print("FAIL nothing to check: no status sheet (and no chart, with a live source) selected")
        fails += 1
    left = f", {src.unchecked} target(s) UNCHECKED" if getattr(src, "unchecked", 0) else ""
    print(f"{len(sheets)} sheet(s), {len(charts)} chart(s), {fails} failure(s){left}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
