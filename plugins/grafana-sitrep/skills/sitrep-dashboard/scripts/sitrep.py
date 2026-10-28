"""Build Grafana status sheets ("sitreps") and the history charts beside them.

Import this from a generator script that reads the ORIGINAL dashboard JSON and writes the new one, so a rerun
rebuilds the page from the same input. Never patch the output by hand: the next regeneration drops the patch.

    import sys; sys.path.insert(0, "<skill>/scripts"); import sitrep
    d = json.load(open("orig.json"))
    d["panels"] = [sitrep.sheet(...), sitrep.history(...), ...]
    sitrep.finish(d)

Needs the Business Text panel plugin (marcusolsson-dynamictext-panel; 6.2.0 is the tested version).
"""
import copy
import json
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _minify_js(src):
    """Whole-line comments, blank lines and indentation out: every sheet embeds the library, so this is paid once
    per sheet (a dozen sheets passed 140 KB). Only whole lines go, so code and strings are never touched; the
    library keeps no template literal across lines, which is what makes the indentation safe to drop."""
    return "\n".join(x.strip() for x in src.splitlines() if x.strip() and not x.strip().startswith("//"))


def _minify_css(src):
    return "\n".join(x.strip() for x in re.sub(r"/\*.*?\*/", "", src, flags=re.S).splitlines() if x.strip())


LIB = _minify_js((ASSETS / "briefing_lib.js").read_text())
CSS = _minify_css((ASSETS / "briefing.css").read_text())
# The verdict line's label on every sheet; None drops it (the yellow rule still marks the line). One sheet can
# differ: sheet(..., brief_label=...).
BRIEF_LABEL = "SITREP"
_UNSET = object()
FONTS = "https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap"
MIXED = {"type": "datasource", "uid": "-- Mixed --"}
LINK_HELPERS = ("repoA(", "prA(", "commitA(", "fileA(", "wfA(", "refA(", "linkify(", "via(")

# 00:00 UTC of the evaluation day. Grafana's browser timezone moves the axis, never this.
MIDNIGHT = "(time() - time() % 86400)"


def today(sel, by=""):
    """Rise of counter `sel` since 00:00 UTC.

    The midnight side is the last sample at or before 00:00 within a day, so a scrape gap across midnight still
    has a base. The bare `X @ midnight` form needs a sample AT 00:00 and returns nothing otherwise, which reads as
    "No data" all day. A series born today has no base and counts from 0.
    """
    b = f" by ({by})" if by else ""
    return f"(sum{b} ({sel}) - (sum{b} (last_over_time({sel}[1d] @ {MIDNIGHT})) or sum{b} ({sel}) * 0))"


def q(ref, expr, ds, legend=None, instant=True):
    """A Prometheus-compatible target. Sheets read instant values; charts pass instant=False."""
    t = {"datasource": ds, "refId": ref, "expr": expr, "instant": instant, "range": not instant}
    if legend:
        t["legendFormat"] = legend
    return t


def registry(url, ds, root="repos"):
    """An Infinity target reading a live repo registry, {"repos": [{"label", "slug"}]}: refId RP, which the
    renderer prefers over the static map. One registry for every sheet means no repo map is kept in the page."""
    return {
        "refId": "RP", "datasource": ds, "type": "json", "parser": "backend", "format": "table",
        "root_selector": root, "source": "url", "url": url, "url_options": {"method": "GET"},
        "columns": [{"selector": c, "text": c, "type": "string"} for c in ("label", "slug")],
    }


def walk(panels):
    """Every panel of a dashboard, the children of collapsed rows included. A collapsed row keeps its panels in
    `row["panels"]`, not at the top level: a check over `d["panels"]` alone never sees them."""
    for p in panels:
        yield p
        yield from p.get("panels", [])


# Runs after the panel renders: links open in a new tab (the sanitizer drops `target`), and each flow() graph gets
# its edges, drawn in svg built through the DOM because html <svg> does not survive the sanitizer.
AFTER_RENDER = r"""
context.element.querySelectorAll('a[href^="https://"]').forEach((el) => { el.target = '_blank'; el.rel = 'noopener noreferrer'; });
// Drawn again once the web font is in (it narrows every box: drawn before, the arrows drift ~26 px a column)
// and on every resize of the graph.
const drawFlow = (f) => {
  const src = f.querySelector('.fe'); if (!src) return;
  let E; try { E = JSON.parse(src.textContent); } catch (e) { return; }
  f.querySelectorAll('svg.fsvg').forEach((s) => s.remove());
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg'), base = f.getBoundingClientRect();
  svg.setAttribute('class', 'fsvg'); svg.setAttribute('width', f.scrollWidth); svg.setAttribute('height', f.scrollHeight);
  const defs = document.createElementNS(NS, 'defs'), mk = document.createElementNS(NS, 'marker'), tip = document.createElementNS(NS, 'path');
  mk.setAttribute('id', 'fh'); mk.setAttribute('viewBox', '0 0 8 8'); mk.setAttribute('refX', '8'); mk.setAttribute('refY', '4');
  mk.setAttribute('markerWidth', '7'); mk.setAttribute('markerHeight', '7'); mk.setAttribute('orient', 'auto');
  tip.setAttribute('d', 'M0,0 L8,4 L0,8 z'); tip.setAttribute('style', 'fill:#8b949e;stroke:none'); mk.appendChild(tip); defs.appendChild(mk); svg.appendChild(defs);
  const at = (k) => { const b = f.querySelector('.' + k + ' .fb'); if (!b) return null; const r = b.getBoundingClientRect();
    return { l: r.left - base.left + f.scrollLeft, r: r.right - base.left + f.scrollLeft, t: r.top - base.top + f.scrollTop, b: r.bottom - base.top + f.scrollTop }; };
  E.forEach(([a, b, kind]) => {
    const p = at(a), q = at(b); if (!p || !q) return;
    // same row: side to side. Rows apart: out of the source's bottom centre (under its state word), into the
    // target's top centre, with a dot at the start, so a long arrow never reads as leaving a box it only crosses.
    const sameRow = Math.abs(p.t - q.t) < 4; let d, x0, y0;
    if (sameRow) { const y = (p.t + p.b) / 2, dx = Math.max(16, (q.l - p.r) / 2); x0 = p.r; y0 = y; d = `M${p.r},${y} C${p.r + dx},${y} ${q.l - dx},${y} ${q.l},${y}`; }
    else { const x1 = (p.l + p.r) / 2, x2 = (q.l + q.r) / 2, down = q.t > p.b;
      x0 = x1; y0 = down ? p.b + 16 : p.t;
      d = down ? `M${x1},${y0} C${x1},${y0 + 40} ${x2},${q.t - 40} ${x2},${q.t}` : `M${x1},${y0} C${x1},${y0 - 40} ${x2},${q.b + 56} ${x2},${q.b + 16}`;
      const dot = document.createElementNS(NS, 'circle'); dot.setAttribute('cx', x0); dot.setAttribute('cy', y0); dot.setAttribute('r', 3); dot.setAttribute('class', kind); svg.appendChild(dot); }
    const path = document.createElementNS(NS, 'path'); path.setAttribute('d', d); path.setAttribute('class', kind); path.setAttribute('marker-end', 'url(#fh)'); svg.appendChild(path);
  });
  f.style.position = 'relative'; f.insertBefore(svg, f.firstChild);
};
context.element.querySelectorAll('.flow').forEach((f) => {
  drawFlow(f);
  // not keyed on f's scroll size: the stale svg holds that size up, so a font swap would never redraw
  if (document.fonts) { document.fonts.ready.then(() => drawFlow(f)); document.fonts.addEventListener('loadingdone', () => drawFlow(f)); }
  if (window.ResizeObserver) new ResizeObserver(() => drawFlow(f)).observe(f.querySelector('.fr') || f);
});
"""
AFTER_RENDER = _minify_js(AFTER_RENDER)


def sheet(pid, title, desc, grid, targets, body_js, *, ds, repos=None, forge="https://github.com", registry_target=None,
          consts=None, brief_label=_UNSET, locale="en-US"):
    """One status sheet: a Business Text panel whose helper renders the HTML that `body_js` assigns to `html`.

    `desc` is the panel's (i) text: say what each line means, where it comes from, its thresholds, and any GAP the
    sheet cannot see. `repos` maps a repo label to owner/name for the links; `registry_target` (see registry())
    replaces it with a live table and is added only to sheets that render a link.

    `consts` passes generator data into the sheet: {"TN": topic_names} becomes `const TN = <json>;` before the
    body. Never build `body_js` with `%` or an f-string: a JS `%` (modulo) breaks the one, a JS `{` the other.
    `brief_label` replaces BRIEF_LABEL for this sheet (None: no label). `locale` sets int()'s digit grouping.
    """
    helper = f"sitrep{pid}"
    label = BRIEF_LABEL if brief_label is _UNSET else brief_label
    lib = (LIB.replace("/*FORGE*/'https://github.com'", json.dumps(forge)).replace("/*REPOS*/{}", json.dumps(repos or {}))
           .replace("/*LOCALE*/'en-US'", json.dumps(locale)).replace("/*BRIEF_LABEL*/'SITREP'", json.dumps(label)))
    if registry_target and any(f in body_js for f in LINK_HELPERS):
        targets = targets + [registry_target]
    head = ""
    for k, v in (consts or {}).items():
        if not re.fullmatch(r"[A-Za-z_$][\w$]*", k):
            raise SystemExit(f"sheet {pid}: const name {k!r} is not a JS identifier")
        head += f"const {k} = {json.dumps(v, ensure_ascii=False)};\n"
    js = lib + "\n// ---- this sheet ----\n" + head + body_js.strip() + f"\nHB.registerHelper('{helper}', () => new HB.SafeString(html));\n"
    uids = {json.dumps(t["datasource"], sort_keys=True) for t in targets}
    return {
        "id": pid, "type": "marcusolsson-dynamictext-panel", "title": title, "description": desc, "gridPos": grid,
        "datasource": MIXED if len(uids) > 1 else targets[0]["datasource"], "targets": targets,
        "options": {
            "renderMode": "data", "content": "{{{%s}}}" % helper, "defaultContent": "{{{%s}}}" % helper,
            "editors": ["helpers", "afterRender", "styles"], "editor": {"format": "auto", "language": "html"},
            "helpers": js, "styles": CSS, "wrap": True, "status": "", "contentPartials": [],
            # Grafana's sanitizer drops `target`; put it back so a link never navigates the dashboard away
            "afterRender": AFTER_RENDER,
            "externalStyles": [{"id": "fonts", "url": FONTS}],
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def history(pid, title, desc, grid, targets, *, interval, time_from=None, unit="short", stack=True, bars=False,
            colors=None, signed=False):
    """A time series beside a sheet. Sample a GAUGE and average it per bucket (avg_over_time(g[$__interval])):
    a stack of slots can then never exceed the slot count. `increase()` of a total booked when work seals puts a
    3-hour job into one bucket and draws the peak nobody believes.

    `interval` is the bucket, and it has no default: set it to the source's write cadence (an exporter pass every
    5 min -> "5m"). Finer only repeats one sample; coarser hides what the data has. Name it in the title
    ("— 5-minute average"). `time_from` pins this chart's own range ("14d") for a per-day or weekly chart on a page
    whose default range is set for the finest chart.

    `signed=True` drops the axis floor of 0 for a chart that goes below zero by design: the outflow side of
    opened_closed(), or traffic in above / out below. A line chart is otherwise floored at 0 (no gauge here can
    be negative), and the floor silently cuts the whole negative half away."""
    over = [{"matcher": {"id": "byRegexp", "options": rx},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]} for rx, c in (colors or {}).items()]
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "gridPos": grid,
        "datasource": targets[0]["datasource"], "targets": targets, "interval": interval,
        "fieldConfig": {"defaults": {
            "unit": unit, "min": None if bars or signed else 0, "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "bars" if bars else "line", "fillOpacity": 80 if bars else 35, "lineWidth": 1,
                       "stacking": {"mode": "normal" if stack else "none", "group": "A"}, "showPoints": "never"},
        }, "overrides": over},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
        **({"timeFrom": time_from} if time_from else {}),
    }


def opened_closed(opened, closed, by, ds, net=None):
    """Targets for a flow chart: inflow above zero, outflow below, one pair per `by` value, so "is the backlog
    collapsing?" is answered by which side is taller. `net` optionally draws the sum as a line."""
    t = [q("A", f"sum by ({by}) ({opened})", ds, "{{%s}} opened" % by, instant=False),
         q("B", f"-sum by ({by}) ({closed})", ds, "{{%s}} closed" % by, instant=False)]
    if net:
        t.append(q("C", net, ds, "net change", instant=False))
    return t


def carry_rows(panels, y, *, drop=(), prefix=""):
    """The original's COLLAPSED rows, re-anchored from `y` down, for a page that keeps its deep panels as a
    drill-down below the sheets (a community dashboard: Node Exporter Full has 14 such rows and ~120 panels).
    `drop` names rows the sheets replace. An expanded row is refused: its panels are top-level, finish() would
    have to check them, and they would push the sheets off the first screen: carry_panels() moves chosen panels
    of an expanded row into a collapsed one. Returns (rows, next_y)."""
    out = []
    for p in panels:
        if p.get("type") != "row" or p.get("title") in drop:
            continue
        if not p.get("collapsed"):
            raise SystemExit(f"row {p.get('title')!r} is expanded: collapse it in the original, drop it, "
                             "or carry its panels with carry_panels()")
        r = json.loads(json.dumps(p))
        base, r["gridPos"]["y"] = r["gridPos"]["y"], y
        for c in r.get("panels", []):
            c["gridPos"]["y"] = y + 1 + max(0, c["gridPos"]["y"] - base - 1)
        if prefix:
            r["title"] = f"{prefix}{p.get('title', '')}"
        out.append(r)
        y += 1
    return out, y


def carry_panels(src_panels, ids, y, title, *, id_offset=1000, row_id=None):
    """Chosen original panels, as-is, in ONE collapsed row at `y`: the carrier for a dashboard whose rows are
    expanded (carry_rows() refuses those). Panels are deep-copied in the order of `ids`, packed left to right and
    wrapped at the grid's 24 columns, each keeping its size. Every id becomes id + `id_offset`, so a carried
    original cannot take the id of a new sheet (Grafana would renumber one of them silently, and break links to
    it); the row itself is `row_id`, by default `id_offset`. Also the first step of a full redraw: carry as-is,
    then redraw panel by panel. Returns (row, next_y)."""
    by_id = {p["id"]: p for p in walk(src_panels) if "id" in p}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"carry_panels: no panel with id {missing} in the original")
    out, x, top, h = [], 0, y + 1, 0
    for i in ids:
        c = copy.deepcopy(by_id[i])
        g = c["gridPos"]
        if x + g["w"] > 24:
            x, top, h = 0, top + h, 0
        c["id"], c["gridPos"] = i + id_offset, {"h": g["h"], "w": g["w"], "x": x, "y": top}
        x, h = x + g["w"], max(h, g["h"])
        out.append(c)
    r = row(id_offset if row_id is None else row_id, title, y)
    r.update(collapsed=True, panels=out)
    return r, y + 1


def coverage(src_panels, mapping, new_panels=None, questions=None):
    """The record of a full redraw: where each original panel's information went. `mapping` is
    {old_id: new_id | "covered-by:<id>" | "dropped:<reason>"} over every original panel but rows; `questions`
    optionally {old_id: "the question it answered"}. Refuses an unmapped original, an unknown target and a bare
    "dropped", so nothing leaves the page silently. Returns the coverage table (markdown) for the hand-over."""
    src = [p for p in walk(src_panels) if p.get("type") != "row"]
    new = {p["id"]: p for p in walk(new_panels or [])}
    errs = [f"original panel {p['id']} {p.get('title')!r} is not mapped" for p in src if p["id"] not in mapping]
    known = {p["id"] for p in src}
    errs += [f"mapping names panel {k}, which the original does not have" for k in mapping if k not in known]
    out = ["| old | title | question | new home |", "|---|---|---|---|"]
    for p in src:
        to = mapping.get(p["id"])
        if to is None:
            continue
        if isinstance(to, str) and to.startswith("dropped:"):
            if not to[8:].strip():
                errs.append(f"panel {p['id']}: a drop needs its reason")
            home = f"dropped: {to[8:].strip()}"
        else:
            nid = int(to[11:]) if isinstance(to, str) and to.startswith("covered-by:") else to
            if not isinstance(nid, int):
                errs.append(f"panel {p['id']}: {to!r} is not a new id, covered-by:<id> or dropped:<reason>")
                continue
            if new_panels is not None and nid not in new:
                errs.append(f"panel {p['id']} maps to {nid}, which the new page does not have")
                continue
            t = new[nid].get("title", "") if nid in new else ""
            home = f"{'covered by ' if isinstance(to, str) else ''}{nid} {t}".strip()
        q = (questions or {}).get(p["id"], "")
        out.append(f"| {p['id']} | {p.get('title', '')} | {q} | {home} |".replace("\n", " "))
    if errs:
        raise SystemExit("coverage:\n  " + "\n  ".join(errs))
    return "\n".join(out)


_PROMQL_WORDS = {"by", "without", "on", "ignoring", "group_left", "group_right", "bool", "offset", "and", "or",
                 "unless", "inf", "nan", "atan2", "start", "end"}


def promql_parts(expr):
    """(metric names, grouping labels) an expression reads. A lint, not a parser: strings, label matchers, ranges
    and template variables are cut out first, and what is left that is not a function call is a metric."""
    e = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', '""', expr)
    e = re.sub(r"\$\{[^}]*\}|\$\w+", "", e)
    e = re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", e)
    labels = set()
    for m in re.finditer(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\(([^)]*)\)", e):
        labels |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    e = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", e)
    names = {m.group(1) for m in re.finditer(r"(?<![\w.])([A-Za-z_:][\w:]*)\b(?!\s*\()", e)}
    return names - _PROMQL_WORDS, labels


def parity(src_panels, new_panels):
    """Every metric and every `by (...)` label an original target read, that no target on the new page reads:
    the information a redraw would drop without anyone noticing. Returns warning lines; empty means parity."""
    def parts(panels):
        out = {}
        for p in walk(panels):
            for t in p.get("targets", []):
                if t.get("expr"):
                    n, lb = promql_parts(t["expr"])
                    out.setdefault(p["id"], (p.get("title", ""), set(), set()))
                    out[p["id"]][1].update(n)
                    out[p["id"]][2].update(lb)
        return out
    old, new = parts(src_panels), parts(new_panels)
    have_n = set().union(*(v[1] for v in new.values())) if new else set()
    have_l = set().union(*(v[2] for v in new.values())) if new else set()
    warn = []
    for pid, (title, names, labels) in sorted(old.items()):
        for n in sorted(names - have_n):
            warn.append(f"panel {pid} {title!r}: metric {n} is read by no new panel")
        for lb in sorted(labels - have_l):
            warn.append(f"panel {pid} {title!r}: grouping label {lb!r} appears in no new panel's by (...)")
    return warn


def row(pid, title, y):
    return {"id": pid, "type": "row", "title": title, "collapsed": False, "panels": [], "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}}


def finish(d, *, time_range=None):
    """Page-wide settings, then refuse a layout Grafana would silently reflow. `time_range` ("12h") is the page's
    default: short enough that the finest history chart draws one bar per bucket (Grafana's `interval` is only a
    minimum, and it widens buckets to fit the panel's pixels)."""
    d["timezone"] = "browser"  # every timestamp in the reader's zone; "today" stays the UTC day the queries define
    if time_range:
        d["time"] = {"from": f"now-{time_range}", "to": "now"}
    # The top level is one grid; each collapsed row's panels are another, laid out from the row down when it opens.
    _check_grid(d["panels"], "")
    for r in d["panels"]:
        if r.get("type") == "row" and r.get("panels"):
            kids = r["panels"]
            if not r.get("collapsed"):
                raise SystemExit(f"row {r['id']} {r.get('title')!r} is expanded but holds panels: Grafana drops them")
            low = min(c["gridPos"]["y"] for c in kids)
            if low < r["gridPos"]["y"] + 1:
                raise SystemExit(f"row {r['id']} {r.get('title')!r}: a panel sits at y={low}, above the row's "
                                 f"first line y={r['gridPos']['y'] + 1}")
            _check_grid(kids, f" in row {r['id']} {r.get('title')!r}")
    # ids are unique across the whole tree: Grafana renumbers a duplicate silently, and a link to it breaks
    seen = {}
    for p in walk(d["panels"]):
        if p["id"] in seen:
            raise SystemExit(f"duplicate panel id {p['id']}: {seen[p['id']]!r} and {p.get('title')!r}")
        seen[p["id"]] = p.get("title")
    return d


def _check_grid(panels, where):
    cells = {}
    for p in panels:
        g = p["gridPos"]
        if g["x"] + g["w"] > 24:
            raise SystemExit(f"panel {p['id']} {p.get('title')!r}{where} is wider than the grid")
        for yy in range(g["y"], g["y"] + g["h"]):
            for xx in range(g["x"], g["x"] + g["w"]):
                if (xx, yy) in cells:
                    raise SystemExit(f"panel {p['id']}{where} overlaps panel {cells[(xx, yy)]} at x={xx} y={yy}")
                cells[(xx, yy)] = p["id"]
