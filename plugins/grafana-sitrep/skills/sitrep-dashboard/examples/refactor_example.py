#!/usr/bin/env python3
"""Worked example: a deploy page whose stat tiles read as "many zeros" becomes one sheet plus its history.

    python3 refactor_example.py orig.json new.json

Copy this file next to your dashboard and replace the queries. The shape is the point: read the original, build
every panel, `finish()`, write. Panels you keep unchanged are deep-copied from the original by id.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sitrep  # noqa: E402

PROM = {"type": "prometheus", "uid": "prometheus"}
REPOS = {"api": "acme/api", "web": "acme/web"}  # or sitrep.registry(<url>, <infinity ds>) for a live table

src = json.loads(Path(sys.argv[1]).read_text())
old = {p["id"]: p for p in src["panels"]}
panels, y = [], 0

panels.append(sitrep.row(100, "Is production running main?", y))
y += 1
panels.append(sitrep.sheet(
    1, "Deploy gates — main → production",
    "One line per deploy workflow on each repo's main. **RED for** = time since its current red streak began; "
    "cancelled and skipped runs are not verdicts. Any red means production is NOT running main: the link opens the "
    "workflow's runs. Thresholds: any red = ACT. Source: `ci_workflow_red_seconds`, every 5 min. "
    "GAP: no series says which commit production runs, so a green gate on a stale deploy reads green.",
    {"h": 10, "w": 8, "x": 0, "y": y},
    [sitrep.q("A", 'max by (repo, workflow) (ci_workflow_red_seconds{workflow=~"(?i)deploy.*"})', PROM)],
    r"""
const by = {};
for (const r of rows('A')) (by[r.labels.repo] = by[r.labels.repo] || []).push(r);
const lines = [], red = [];
for (const repo of Object.keys(by).sort()) {
  lines.push(sub(repoA(repo)));
  for (const r of by[repo].sort((x, y) => y.value - x.value)) {
    if (r.value > 0) red.push(`${repo} ▸ ${r.labels.workflow}`);
    lines.push(ln(wfA(repo, r.labels.workflow), r.value > 0 ? `RED ${dur(r.value)}` : 'green', r.value > 0 ? 'bad' : 'ok'));
  }
}
const verdict = !rows('A').length ? 'No deploy gate reporting — the exporter is down or the filter is wrong.'
  : red.length ? `Production is NOT running main for: ${red.map(esc).join(', ')}.`
  : `All ${rows('A').length} deploy gates green — production runs main.`;
const html = page('01', 'Deploy gates', brief(verdict) + lines.join(''));
""",
    ds=PROM, repos=REPOS,
))
panels.append(sitrep.history(
    2, "Deploy gates red — 5-minute average",
    "How many deploy gates were red, per 5 minutes, by repo. Reads the `ci_workflow_red` gauge (0/1 per gate) averaged "
    "per bucket, so the stack never exceeds the gate count.",
    {"h": 10, "w": 16, "x": 8, "y": y},
    [sitrep.q("A", 'sum by (repo) (avg_over_time(ci_workflow_red{workflow=~"(?i)deploy.*"}[$__interval]))', PROM, "{{repo}}", instant=False)],
    interval="5m",  # the exporter's pass: one bucket per sample written
))
y += 10

# a panel nobody asked a question of goes last, collapsed, or away; this one is kept as the instrument check
if 7 in old:
    kept = copy.deepcopy(old[7])
    kept["gridPos"] = {"h": 6, "w": 24, "x": 0, "y": y}
    panels.append(kept)
    y += 6

src["panels"] = panels
Path(sys.argv[2]).write_text(json.dumps(sitrep.finish(src, time_range="12h"), indent=1, ensure_ascii=False) + "\n")
print(f"{len(panels)} panels, height {y}")
