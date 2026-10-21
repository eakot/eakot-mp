"""Build Grafana status sheets ("sitreps") and the history charts beside them.

Import this from a generator script that reads the ORIGINAL dashboard JSON and writes the new one, so a rerun
rebuilds the page from the same input. Never patch the output by hand: the next regeneration drops the patch.

    import sys; sys.path.insert(0, "<skill>/scripts"); import sitrep
    d = json.load(open("orig.json"))
    d["panels"] = [sitrep.sheet(...), sitrep.history(...), ...]
    sitrep.finish(d)

Needs the Business Text panel plugin (marcusolsson-dynamictext-panel; 6.2.0 is the tested version).
"""
import json
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LIB = (ASSETS / "briefing_lib.js").read_text()
CSS = (ASSETS / "briefing.css").read_text()
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


def sheet(pid, title, desc, grid, targets, body_js, *, ds, repos=None, forge="https://github.com", registry_target=None):
    """One status sheet: a Business Text panel whose helper renders the HTML that `body_js` assigns to `html`.

    `desc` is the panel's (i) text: say what each line means, where it comes from, its thresholds, and any GAP the
    sheet cannot see. `repos` maps a repo label to owner/name for the links; `registry_target` (see registry())
    replaces it with a live table and is added only to sheets that render a link.
    """
    helper = f"sitrep{pid}"
    lib = LIB.replace("/*FORGE*/'https://github.com'", json.dumps(forge)).replace("/*REPOS*/{}", json.dumps(repos or {}))
    if registry_target and any(f in body_js for f in LINK_HELPERS):
        targets = targets + [registry_target]
    js = lib + "\n// ---- this sheet ----\n" + body_js.strip() + f"\nHB.registerHelper('{helper}', () => new HB.SafeString(html));\n"
    uids = {json.dumps(t["datasource"], sort_keys=True) for t in targets}
    return {
        "id": pid, "type": "marcusolsson-dynamictext-panel", "title": title, "description": desc, "gridPos": grid,
        "datasource": MIXED if len(uids) > 1 else targets[0]["datasource"], "targets": targets,
        "options": {
            "renderMode": "data", "content": "{{{%s}}}" % helper, "defaultContent": "{{{%s}}}" % helper,
            "editors": ["helpers", "afterRender", "styles"], "editor": {"format": "auto", "language": "html"},
            "helpers": js, "styles": CSS, "wrap": True, "status": "", "contentPartials": [],
            # Grafana's sanitizer drops `target`; put it back so a link never navigates the dashboard away
            "afterRender": "context.element.querySelectorAll('a[href^=\"https://\"]').forEach((el) => { el.target = '_blank'; el.rel = 'noopener noreferrer'; });",
            "externalStyles": [{"id": "fonts", "url": FONTS}],
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def history(pid, title, desc, grid, targets, *, unit="short", stack=True, bars=False, colors=None):
    """A time series beside a sheet. Sample a GAUGE and average it per bucket (avg_over_time(g[$__interval])):
    a stack of slots can then never exceed the slot count. `increase()` of a total booked when work seals puts a
    3-hour job into one bucket and draws the peak nobody believes."""
    over = [{"matcher": {"id": "byRegexp", "options": rx},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]} for rx, c in (colors or {}).items()]
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "gridPos": grid,
        "datasource": targets[0]["datasource"], "targets": targets, "interval": "1h",
        "fieldConfig": {"defaults": {
            "unit": unit, "min": None if bars else 0, "color": {"mode": "palette-classic"},
            "custom": {"drawStyle": "bars" if bars else "line", "fillOpacity": 80 if bars else 35, "lineWidth": 1,
                       "stacking": {"mode": "normal" if stack else "none", "group": "A"}, "showPoints": "never"},
        }, "overrides": over},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def opened_closed(opened, closed, by, ds, net=None):
    """Targets for a flow chart: inflow above zero, outflow below, one pair per `by` value, so "is the backlog
    collapsing?" is answered by which side is taller. `net` optionally draws the sum as a line."""
    t = [q("A", f"sum by ({by}) ({opened})", ds, "{{%s}} opened" % by, instant=False),
         q("B", f"-sum by ({by}) ({closed})", ds, "{{%s}} closed" % by, instant=False)]
    if net:
        t.append(q("C", net, ds, "net change", instant=False))
    return t


def row(pid, title, y):
    return {"id": pid, "type": "row", "title": title, "collapsed": False, "panels": [], "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}}


def finish(d):
    """Page-wide settings, then refuse a layout Grafana would silently reflow."""
    d["timezone"] = "browser"  # every timestamp in the reader's zone; "today" stays the UTC day the queries define
    cells = {}
    for p in d["panels"]:
        g = p["gridPos"]
        if g["x"] + g["w"] > 24:
            raise SystemExit(f"panel {p['id']} {p.get('title')!r} is wider than the grid")
        for yy in range(g["y"], g["y"] + g["h"]):
            for xx in range(g["x"], g["x"] + g["w"]):
                if (xx, yy) in cells:
                    raise SystemExit(f"panel {p['id']} overlaps panel {cells[(xx, yy)]} at x={xx} y={yy}")
                cells[(xx, yy)] = p["id"]
    ids = [p["id"] for p in d["panels"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate panel id")
    return d
