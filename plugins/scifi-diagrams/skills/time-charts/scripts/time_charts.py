#!/usr/bin/env python3
"""time-charts: zoomable time-series charts (uPlot) from one JSON file (schema `time-charts/1`).

    time_charts.py check series.json                 validate; exit 1 on any error
    time_charts.py build series.json -o page.html    one self-contained page; uPlot inlined, no network request

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
sys.path.insert(0, str(HERE.parents[2] / "shared"))
import page  # noqa: E402  (shared/page.py)

SCHEMA = "time-charts/1"
KINDS = {"line", "area", "bars", "step"}


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)   # 1e999 is inf


def check(doc: object) -> tuple[list[str], list[str]]:
    """Errors (the page would lie or break) and warnings."""
    err: list[str] = []
    warn: list[str] = []
    if not isinstance(doc, dict):
        return ["the file is not a JSON object"], warn
    if doc.get("schema") != SCHEMA:
        err.append(f'schema must be "{SCHEMA}", got {doc.get("schema")!r}')
    charts = doc.get("charts")
    if not isinstance(charts, list) or not charts:
        return err + ["charts must be a non-empty list"], warn
    for i, c in enumerate(charts):
        where = f"charts[{i}]"
        if not isinstance(c, dict):
            err.append(f"{where}: not an object")
            continue
        where = f"chart {c.get('title', i)!r}"
        if c.get("kind", "line") not in KINDS:
            err.append(f"{where}: kind must be one of {sorted(KINDS)}")
        xs = c.get("xs")
        if not isinstance(xs, list) or not all(_num(x) for x in xs):
            err.append(f"{where}: xs must be a list of unix seconds")
            continue
        if any(b <= a for a, b in zip(xs, xs[1:])):
            err.append(f"{where}: xs must be strictly increasing")
        if xs and xs[0] > 1e11:
            err.append(f"{where}: xs look like milliseconds; uPlot wants seconds")
        series = c.get("series")
        if not isinstance(series, list) or not series:
            err.append(f"{where}: series must be a non-empty list")
            continue
        if len(series) > 6:
            warn.append(f"{where}: {len(series)} series; past the sixth they share the 'other' hue — fold or facet")
        for k, s in enumerate(series):
            if not isinstance(s, dict) or not isinstance(s.get("label"), str):
                err.append(f"{where}: series[{k}] needs a label")
                continue
            vals = s.get("values")
            if not isinstance(vals, list) or len(vals) != len(xs):
                err.append(f"{where}: series {s['label']!r} needs one value per x ({len(xs)})")
            elif not all(v is None or _num(v) for v in vals):
                err.append(f"{where}: series {s['label']!r} values must be numbers or null (null = no sample, never 0)")
            elif c.get("kind") in ("area", "bars") and any(_num(v) and v < 0 for v in vals):
                err.append(f"{where}: series {s['label']!r} is stacked and has a negative value")
        for key in ("ref", "ymax"):
            if key in c and not _num(c[key]):
                err.append(f"{where}: {key} must be a number")
    return err, warn


def build(doc: dict) -> str:
    vendor = ASSETS / "vendor"
    css = [(vendor / "uPlot.min.css").read_text(encoding="utf-8"), (ASSETS / "charts.css").read_text(encoding="utf-8")]
    js = [(vendor / "uPlot.iife.min.js").read_text(encoding="utf-8"), (ASSETS / "charts.js").read_text(encoding="utf-8")]
    boot = "TimeCharts.render(document.getElementById('tc'), JSON.parse(document.getElementById('tc-data').textContent));"
    return page.page(doc.get("title") or "Time charts", css, js, '<div id="tc"></div>', boot, doc, "tc-data")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("doc")
    b = sub.add_parser("build")
    b.add_argument("doc")
    b.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)
    try:
        doc = page.load_json(args.doc)
    except ValueError as e:                             # bad JSON, NaN or Infinity
        print(f"error: {args.doc}: {e}", file=sys.stderr)
        return 1
    errors, warnings = check(doc)
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    for x in errors:
        print(f"error: {x}", file=sys.stderr)
    if errors:
        return 1
    if args.cmd == "check":
        print(f"ok: {len(doc['charts'])} charts")
        return 0
    Path(args.out).write_text(build(doc), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
