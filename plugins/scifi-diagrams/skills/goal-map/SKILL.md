---
name: goal-map
description: Draw goals as a sci-fi star map — one sector per topic around a core, each goal a body sized by its sub-goals, ringed by how much is done and placed nearer the core the nearer it is to done; moons for sub-goals; pan, wheel/pinch zoom, fly-in, a readout and a table view, as one self-contained HTML page. Use when asked for a goal map, a progress map of goals or epics, "how far along is each goal", tracking issues with sub-issues as a map, OKR / initiative progress at a glance, or a mission-control view of goals by topic.
---

# Goal map

A goal map answers **how far along each goal is**, all goals at once. One JSON file (schema `goal-map/1`) holds the
goals; `scripts/goal_map.py` checks it and builds one HTML file that makes no network request.

Requirements: Python 3.9+ (stdlib only). Optional: Node to run the layout test; Playwright to screenshot.

## How to read it

- **A sector per topic,** in the order of `topics`, each in its fixed hue (the theme's `--t1`…`--t6`; a seventh
  topic and anything unlisted is the neutral "other"). The colour is the topic and never changes.
- **A goal is a body.** Its size is its number of sub-goals (`total`). Its ring is `completed / total`. Its distance
  to the core is how far it has to go: a finished goal has reached the core's ring.
- **A dashed spinning track** means every sub-goal is done but the goal is still open: it is ready to close.
- **A moon** (a goal with `parent`) orbits its parent on a tether.
- **Zoom shows more.** Titles appear from ×1.4, a satellite per sub-goal (filled = done) from ×2.2.
- **The core** is everything: done over total, top-level goals only, so a moon is not counted twice.

Drag to pan; wheel or pinch to zoom at the pointer; double-click (or Enter on a focused goal) flies in; `+` `-`
zoom, `0` resets. A topic chip dims the other topics and frames that sector. The readout lists the sub-goals with
links; **TABLE VIEW** holds every number, so nothing depends on colour.

## The schema

```json
{"schema": "goal-map/1", "title": "HELIX — goal map", "generated": "2301-06-24 08:00Z",
 "notes": ["one line each, under the HUD"],
 "topics": [{"id": "life-support", "label": "Life support"}, {"id": "propulsion", "label": "Propulsion"}],
 "goals": [{"id": "110", "label": "#110", "title": "Ion drive retrofit", "topic": "propulsion",
            "state": "open", "total": 9, "completed": 2, "url": "https://example.org/issues/110",
            "parent": null,
            "kids": [{"id": "#219", "title": "Fit the bus", "done": true, "url": "https://example.org/issues/219"}]}]}
```

| Field | Meaning |
|---|---|
| `state` | `open` or `closed` |
| `total`, `completed` | whole numbers, `completed ≤ total`. A goal with no sub-goals is 0/0 and sits by its state |
| `parent` | another goal's `id`: this goal is its moon |
| `kids` | optional; the readout's list and the satellites. If given, it should agree with `total`/`completed` (a warning) |
| `url` | `http(s)` or relative; anything else is rejected |

## Procedure

1. **Find the goals, don't register them.** A good default for an issue tracker: a goal is any issue with at least
   three sub-issues, or a `goal` label; its progress is its sub-issues closed over total (GitHub returns
   `sub_issues_summary {total, completed}` on every issue). Its topic is the label or project field the team already
   uses. Closed goals stay on the map for a while (30 days is a good window) so a finish is seen.
2. **Write the JSON.** One `topics` entry per sector, at most six.
3. `python3 scripts/goal_map.py check goals.json` — fix every error, read every warning.
4. `python3 scripts/goal_map.py build goals.json -o map.html`.
5. **Look at it.** Open or screenshot the page at ×1 and zoomed into the busiest sector: labels must not collide,
   moons must sit clear of their parent. The checker checks data, not layout.

## Goal map or skill tree?

- **`goal-map`** — *how far along is each goal?* Progress only: no dependencies, no cost.
- **`scifi-graph`** — *what leads to what, and what does it cost?* The same goals as point B of a skill tree, the
  work that leads to them, the gains they unlock and the ≈cost still to go.
- **`time-charts`** — *how did a number move?* A goal's burn-up over time belongs there.

All three share `shared/theme.css`, so they sit on one page as one system.
