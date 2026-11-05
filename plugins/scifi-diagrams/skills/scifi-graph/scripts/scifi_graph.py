#!/usr/bin/env python3
"""scifi-graph: a plan drawn as an RPG skill tree, from one JSON file (schema `scifi-graph/1`).

    scifi_graph.py check    graph.json                 validate; exit 1 on any error
    scifi_graph.py adrs     docs/adr --repo NAME       ADR files -> goal nodes, builds-on edges, gains (JSON on stdout)
    scifi_graph.py merge    a.json b.json … -o out     one graph from several (first definition of an id wins)
    scifi_graph.py estimate graph.json -o out          ≈cost for open tasks from what done tasks actually cost
    scifi_graph.py build    graph.json -o tree.html    one self-contained page; no network request

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
sys.path.insert(0, str(HERE.parents[2] / "shared"))
import page  # noqa: E402  (shared/page.py)

SCHEMA = "scifi-graph/1"
KINDS = {"goal", "epic", "task"}
STATES = {"done", "active", "open"}
EDGE_KINDS = {"needs", "builds-on"}
COST_KEYS = {"actual", "estimate", "low", "high"}


# ---- check ---------------------------------------------------------------------------------------------------------
def check(graph: object) -> tuple[list[str], list[str]]:
    """Errors (the page would lie or break) and warnings (it would be thinner than it could be)."""
    err: list[str] = []
    warn: list[str] = []
    if not isinstance(graph, dict):
        return ["the file is not a JSON object"], warn
    if graph.get("schema") != SCHEMA:
        err.append(f'schema must be "{SCHEMA}", got {graph.get("schema")!r}')
    topics = graph.get("topics", [])
    topic_ids = {t.get("id") for t in topics if isinstance(t, dict)} if isinstance(topics, list) else set()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return err + ["nodes must be a non-empty list"], warn
    by_id: dict[str, dict] = {}
    for i, n in enumerate(nodes):
        where = f"nodes[{i}]"
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"]:
            err.append(f"{where}: id must be a non-empty string")
            continue
        nid = n["id"]
        where = f"node {nid!r}"
        if nid in by_id:
            err.append(f"{where}: duplicate id")
            continue
        by_id[nid] = n
        if n.get("kind", "task") not in KINDS:
            err.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if n.get("state") not in STATES:
            err.append(f"{where}: state must be one of {sorted(STATES)}")
        if not isinstance(n.get("title", ""), str):
            err.append(f"{where}: title must be a string")
        url = n.get("url")
        if url is not None and not (isinstance(url, str) and page.SAFE_URL.match(url)):
            err.append(f"{where}: url must be http(s) or a same-origin path, got {url!r}")
        for key in ("parent", "topic", "label", "status", "closed"):
            if n.get(key) is not None and not isinstance(n[key], str):
                err.append(f"{where}: {key} must be a string")
        cost = n.get("cost")
        if cost is not None:
            if not isinstance(cost, dict) or set(cost) - COST_KEYS:
                err.append(f"{where}: cost takes only {sorted(COST_KEYS)}")
            else:
                for k, v in cost.items():
                    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
                        err.append(f"{where}: cost.{k} must be a number ≥ 0 (a missing cost is left out, never 0)")
                lo, est, hi = cost.get("low"), cost.get("estimate"), cost.get("high")
                if all(isinstance(v, (int, float)) for v in (lo, est, hi)) and not lo <= est <= hi:
                    err.append(f"{where}: cost needs low ≤ estimate ≤ high")
        for key in ("gains", "decides"):
            v = n.get(key)
            if v is not None and (not isinstance(v, list) or not all(isinstance(s, str) for s in v)):
                err.append(f"{where}: {key} must be a list of strings")
        if n.get("gains") and n.get("kind") != "goal":
            warn.append(f"{where}: gains are drawn only on goals")
        if topic_ids and isinstance(n.get("topic"), str) and n["topic"] not in topic_ids:
            warn.append(f"{where}: topic {n['topic']!r} is not in topics, so it draws as 'other'")
    for nid, n in by_id.items():
        p = n.get("parent")
        if p is None or not isinstance(p, str):
            continue
        if p not in by_id:
            err.append(f"node {nid!r}: parent {p!r} does not exist")
        elif n.get("kind") == "goal":
            err.append(f"node {nid!r}: a goal is point B and has no parent")
    depth_cap = 32
    for nid in by_id:                                  # containment must be a forest, and a shallow one
        seen, a = set(), nid
        while isinstance(a, str) and a in by_id:
            if a in seen:
                err.append(f"node {nid!r}: parent chain loops")
                break
            seen.add(a)
            a = by_id[a].get("parent")
        else:
            if len(seen) > depth_cap:
                err.append(f"node {nid!r}: nested {len(seen)} deep; the map draws at most {depth_cap} levels")
    succ: dict[str, list[str]] = {}
    for i, e in enumerate(graph.get("edges", []) or []):
        if not isinstance(e, dict):
            err.append(f"edges[{i}]: not an object")
            continue
        a, b = e.get("from"), e.get("to")
        if not isinstance(a, str) or not isinstance(b, str) or a not in by_id or b not in by_id:
            err.append(f"edges[{i}]: {a!r} -> {b!r} names a node that does not exist")
            continue
        if a == b:
            err.append(f"edges[{i}]: {a!r} depends on itself")
            continue
        if e.get("kind", "needs") not in EDGE_KINDS:
            err.append(f"edges[{i}]: kind must be one of {sorted(EDGE_KINDS)}")
        succ.setdefault(a, []).append(b)
    state: dict[str, int] = {}                          # 1 = on the stack, 2 = finished

    def dfs(u: str, path: list[str]) -> None:
        state[u] = 1
        path.append(u)
        for v in succ.get(u, []):
            if state.get(v) == 1:
                cyc = path[path.index(v):] + [v]
                err.append("edges form a cycle: " + " -> ".join(cyc))
            elif v not in state:
                dfs(v, path)
        path.pop()
        state[u] = 2

    sys.setrecursionlimit(max(10000, 4 * len(by_id)))
    for u in list(succ):
        if u not in state:
            dfs(u, [])
    kids = {n.get("parent") for n in by_id.values() if isinstance(n.get("parent"), str)}
    nd = [nid for nid, n in by_id.items() if nid not in kids and n.get("state") != "done"
          and "estimate" not in (n.get("cost") or {})]
    if nd:
        warn.append(f"{len(nd)} open task(s) have no estimate and show as N/D (run `estimate` to fill them)")
    return err, warn


# ---- adrs ----------------------------------------------------------------------------------------------------------
ADR_FILE = re.compile(r"^(\d{3,5})-[\w.-]+\.md$")
HEADER_LINK = re.compile(r"^\W*(builds on|extends|amends|supersedes|depends on)\b", re.I)
ADR_REF = re.compile(r"\(((?:\.{1,2}/)?(?:[\w.-]+/)*?)(\d{3,5})-[\w.-]+\.md[^)]*\)|\bADR[ -](\d{3,5})\b")
DECISION_ITEM = re.compile(r"\*\*D(\d+)\s*[—–-]\s*(.+?)\*\*|^#{3,4}\s*D(\d+)\s*[—–-]\s*(.+)$", re.M)


def _section(text: str, name: str) -> str:
    m = re.search(rf"^##\s+{name}\b.*$", text, re.M | re.I)
    if not m:
        return ""
    rest = text[m.end():]
    end = re.search(r"^##\s", rest, re.M)
    return rest[: end.start()] if end else rest


def parse_adr(path: Path, repo: str, url_base: str = "", topic: str = "") -> tuple[dict, list[dict]]:
    text = path.read_text(encoding="utf-8")
    num = ADR_FILE.match(path.name).group(1)
    nid = f"adr:{repo}/{num}"
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else path.stem
    title = re.sub(rf"^(ADR\s*)?0*{int(num)}\s*[—–:-]\s*", "", title)
    status_m = re.search(r"\*\*Status:?\*\*:?\s*(.+)$", text, re.M | re.I)
    status = re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", status_m.group(1)).strip() if status_m else ""
    status = status[:80]
    state = "done" if re.match(r"accepted|implemented|done", status, re.I) else "open"
    gains = [re.sub(r"^\s*[-*]\s+", "", ln).strip() for ln in _section(text, "Gains").splitlines() if re.match(r"^\s*[-*]\s+\S", ln)]
    decides = []
    for m in DECISION_ITEM.finditer(_section(text, "Decision")):
        d, head = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        decides.append(f"D{d} — {head.strip().rstrip('.:')}")
    node = {"id": nid, "kind": "goal", "title": title, "state": state, "status": status, "label": f"ADR {num}"}
    if url_base:
        node["url"] = url_base.rstrip("/") + "/" + path.name
    if topic:
        node["topic"] = topic
    if gains:
        node["gains"] = gains
    if decides:
        node["decides"] = decides[:12]
    edges = []
    head = text.split("\n## ", 1)[0]
    for line in head.splitlines():
        if not HEADER_LINK.match(line):
            continue
        for m in ADR_REF.finditer(line):
            other = m.group(2) or m.group(3)
            if other and other.lstrip("0") != num.lstrip("0"):
                edges.append({"from": f"adr:{repo}/{other.zfill(len(num))}", "to": nid, "kind": "builds-on"})
    return node, edges


def adrs(directory: Path, repo: str, url_base: str = "", topic: str = "", skip: str = "rejected|withdrawn") -> dict:
    nodes, edges = [], []
    for path in sorted(directory.iterdir()):
        if not ADR_FILE.match(path.name):
            continue
        node, es = parse_adr(path, repo, url_base, topic)
        if skip and re.match(skip, node["status"], re.I):
            continue
        nodes.append(node)
        edges.extend(es)
    ids = {n["id"] for n in nodes}
    seen = set()
    uniq = []
    for e in edges:
        k = (e["from"], e["to"])
        if e["from"] in ids and k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"schema": SCHEMA, "title": f"{repo} decisions", "nodes": nodes, "edges": uniq}


# ---- merge ---------------------------------------------------------------------------------------------------------
def merge(graphs: list[dict]) -> dict:
    out = {"schema": SCHEMA, "title": graphs[0].get("title", ""), "topics": [], "nodes": [], "edges": [], "notes": []}
    for key in ("generated", "currency"):
        for g in graphs:
            if g.get(key):
                out[key] = g[key]
                break
    seen_t, seen_n, seen_e = set(), set(), set()
    for g in graphs:
        for t in g.get("topics", []):
            if t.get("id") not in seen_t:
                seen_t.add(t.get("id"))
                out["topics"].append(t)
        for n in g.get("nodes", []):
            if n.get("id") not in seen_n:
                seen_n.add(n.get("id"))
                out["nodes"].append(n)
        for e in g.get("edges", []):
            k = (e.get("from"), e.get("to"), e.get("kind", "needs"))
            if k not in seen_e:
                seen_e.add(k)
                out["edges"].append(e)
        out["notes"] += [s for s in g.get("notes", []) if s not in out["notes"]]
    ids = seen_n
    out["edges"] = [e for e in out["edges"] if e.get("from") in ids and e.get("to") in ids]
    if not out["topics"]:
        del out["topics"]
    if not out["notes"]:
        del out["notes"]
    return out


# ---- estimate ------------------------------------------------------------------------------------------------------
def _quantiles(xs: list[float]) -> tuple[float, float, float]:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0], xs[0], xs[0]
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def estimate(graph: dict, window_days: int = 30, min_samples: int = 5, today: dt.date | None = None) -> dict:
    """Fill estimate (and low/high from 3 samples up) on open tasks without one: the median (p25–p75) of what done tasks of the same kind
    and topic cost in the window; all topics pooled when fewer than `min_samples`; no samples -> left N/D."""
    today = today or dt.date.today()
    parents = {n.get("parent") for n in graph["nodes"] if isinstance(n.get("parent"), str)}
    leaves = [n for n in graph["nodes"] if n["id"] not in parents and n.get("kind", "task") != "goal"]

    def recent(n: dict) -> bool:
        c = n.get("closed")
        if not c:
            return True
        try:
            return (today - dt.date.fromisoformat(str(c)[:10])).days <= window_days
        except ValueError:
            return True

    samples = [n for n in leaves if n.get("state") == "done" and isinstance((n.get("cost") or {}).get("actual"), (int, float)) and recent(n)]
    filled = 0
    for n in leaves:
        if n.get("state") != "open" or "estimate" in (n.get("cost") or {}):
            continue                                    # done and active work keep what they have
        kind = n.get("kind", "task")
        same = [s["cost"]["actual"] for s in samples if s.get("kind", "task") == kind and s.get("topic") == n.get("topic")]
        pool = same if len(same) >= min_samples else [s["cost"]["actual"] for s in samples if s.get("kind", "task") == kind]
        if not pool:
            continue
        lo, mid, hi = _quantiles(pool)
        cost = dict(n.get("cost") or {})
        cost["estimate"] = round(mid, 4)
        if len(pool) >= 3:                              # fewer samples give a point, not a range that reads as certain
            cost.update(low=round(lo, 4), high=round(hi, 4))
        n["cost"] = cost
        filled += 1
    graph.setdefault("notes", [])
    graph["notes"] = [s for s in graph["notes"] if not s.startswith("≈ estimates:")]
    graph["notes"].append(f"≈ estimates: median (p25–p75) of {len(samples)} done tasks' actual cost in the last "
                          f"{window_days} days, same kind and topic (pooled under {min_samples}); {filled} filled")
    return graph


# ---- build ---------------------------------------------------------------------------------------------------------
def build(graph: dict) -> str:
    css = (ASSETS / "scifi-graph.css").read_text(encoding="utf-8")
    js = (ASSETS / "scifi-graph.js").read_text(encoding="utf-8")
    boot = ("SciFiGraph.render(document.getElementById('sg'),"
            " JSON.parse(document.getElementById('sg-data').textContent));")
    return page.page(graph.get("title") or "Skill tree", [css], [js], '<div id="sg"></div>', boot, graph, "sg-data")


def _load(path: str) -> dict:
    return page.load_json(path)


def _write(data: object, out: str | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("graph")
    a = sub.add_parser("adrs")
    a.add_argument("dir")
    a.add_argument("--repo", required=True, help="the id prefix: nodes are adr:<repo>/<NNNN>")
    a.add_argument("--url-base", default="", help="link each ADR as <url-base>/<file>")
    a.add_argument("--topic", default="")
    a.add_argument("-o", "--out")
    mg = sub.add_parser("merge")
    mg.add_argument("graphs", nargs="+")
    mg.add_argument("-o", "--out")
    e = sub.add_parser("estimate")
    e.add_argument("graph")
    e.add_argument("--window-days", type=int, default=30)
    e.add_argument("--min-samples", type=int, default=5)
    e.add_argument("-o", "--out")
    b = sub.add_parser("build")
    b.add_argument("graph")
    b.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "adrs":
        _write(adrs(Path(args.dir), args.repo, args.url_base, args.topic), args.out)
        return 0
    if args.cmd == "merge":
        _write(merge([_load(p) for p in args.graphs]), args.out)
        return 0
    try:
        graph = _load(args.graph)
    except ValueError as e:                             # bad JSON, NaN or Infinity
        print(f"error: {args.graph}: {e}", file=sys.stderr)
        return 1
    errors, warnings = check(graph)
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    for x in errors:
        print(f"error: {x}", file=sys.stderr)
    if errors:
        return 1
    if args.cmd == "check":
        print(f"ok: {len(graph['nodes'])} nodes, {len(graph.get('edges', []))} edges")
        return 0
    if args.cmd == "estimate":
        _write(estimate(graph, args.window_days, args.min_samples), args.out)
        return 0
    Path(args.out).write_text(build(graph), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
