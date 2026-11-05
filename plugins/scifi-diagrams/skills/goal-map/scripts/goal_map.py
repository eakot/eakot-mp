#!/usr/bin/env python3
"""goal-map: goals as a pan/zoom star map, from one JSON file (schema `goal-map/1`).

    goal_map.py check goals.json                 validate; exit 1 on any error
    goal_map.py build goals.json -o map.html     one self-contained page; no network request

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
sys.path.insert(0, str(HERE.parents[2] / "shared"))
import page  # noqa: E402  (shared/page.py)

SCHEMA = "goal-map/1"
STATES = {"open", "closed"}
URL = re.compile(r"^(https?://|/|\./|\.\./|#)")


def _count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def check(data: object) -> tuple[list[str], list[str]]:
    """Errors (the page would lie or break) and warnings (it would be thinner than it could be)."""
    err: list[str] = []
    warn: list[str] = []
    if not isinstance(data, dict):
        return ["the file is not a JSON object"], warn
    if data.get("schema") != SCHEMA:
        err.append(f'schema must be "{SCHEMA}", got {data.get("schema")!r}')
    topics = data.get("topics", [])
    if not isinstance(topics, list):
        err.append("topics must be a list")
        topics = []
    topic_ids = [t.get("id") for t in topics if isinstance(t, dict)]
    if len(topic_ids) > 6:
        warn.append(f"{len(topic_ids)} topics; past the sixth they draw as 'other'")
    goals = data.get("goals")
    if not isinstance(goals, list) or not goals:
        return err + ["goals must be a non-empty list"], warn
    by_id: dict[str, dict] = {}
    for i, g in enumerate(goals):
        if not isinstance(g, dict) or not isinstance(g.get("id"), str) or not g["id"]:
            err.append(f"goals[{i}]: id must be a non-empty string")
            continue
        where = f"goal {g['id']!r}"
        if g["id"] in by_id:
            err.append(f"{where}: duplicate id")
            continue
        by_id[g["id"]] = g
        if g.get("state") not in STATES:
            err.append(f"{where}: state must be one of {sorted(STATES)}")
        total, done = g.get("total"), g.get("completed")
        if not _count(total) or not _count(done):
            err.append(f"{where}: total and completed must be whole numbers ≥ 0")
        elif done > total:
            err.append(f"{where}: completed ({done}) is more than total ({total})")
        if g.get("url") is not None and not URL.match(str(g["url"])):
            err.append(f"{where}: url must be http(s) or relative, got {g['url']!r}")
        if topic_ids and g.get("topic") not in topic_ids:
            warn.append(f"{where}: topic {g.get('topic')!r} is not in topics, so it draws as 'other'")
        kids = g.get("kids", [])
        if not isinstance(kids, list):
            err.append(f"{where}: kids must be a list")
            continue
        for k, c in enumerate(kids):
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("done"), bool):
                err.append(f"{where}: kids[{k}] needs an id and done: true|false")
            elif c.get("url") is not None and not URL.match(str(c["url"])):
                err.append(f"{where}: kids[{k}] url must be http(s) or relative")
        if kids and _count(total) and _count(done) and (len(kids) != total or sum(c.get("done") is True for c in kids if isinstance(c, dict)) != done):
            warn.append(f"{where}: kids list ({len(kids)}) does not match total/completed ({done}/{total})")
    for gid, g in by_id.items():
        p = g.get("parent")
        if p is None or p == "":
            continue
        if p not in by_id:
            err.append(f"goal {gid!r}: parent {p!r} does not exist")
            continue
        seen, a = set(), gid
        while a:
            if a in seen:
                err.append(f"goal {gid!r}: parent chain loops")
                break
            seen.add(a)
            a = by_id.get(a, {}).get("parent")
    return err, warn


def build(data: dict) -> str:
    css = (ASSETS / "goal-map.css").read_text(encoding="utf-8")
    js = (ASSETS / "goal-map.js").read_text(encoding="utf-8")
    boot = "GoalMap.render(document.getElementById('gm'), JSON.parse(document.getElementById('gm-data').textContent));"
    return page.page(data.get("title") or "Goal map", [css], [js], '<section id="gm"></section>', boot, data, "gm-data")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("goals")
    b = sub.add_parser("build")
    b.add_argument("goals")
    b.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)
    data = json.loads(Path(args.goals).read_text(encoding="utf-8"))
    errors, warnings = check(data)
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    for x in errors:
        print(f"error: {x}", file=sys.stderr)
    if errors:
        return 1
    if args.cmd == "check":
        print(f"ok: {len(data['goals'])} goals")
        return 0
    Path(args.out).write_text(build(data), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
