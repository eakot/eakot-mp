---
name: scifi-graph
description: Draw a plan as an RPG skill tree — decision records (ADRs) as goals ("point B") with the gains they unlock, the epics and issues that lead to them, their dependencies in the past (done, lit) and the future (open, dim), and the approximate cost of every node — as one zoomable, self-contained HTML map that shows more detail at each zoom step. Use when asked for a skill tree, tech tree, dependency map, roadmap graph, "plan as a map", "what does each goal cost", or to show what work unlocks which decision and what is left to reach it.
---

# scifi-graph: the plan as a skill tree

A **goal** is point B. It is a decision record or any other outcome you commit to, with the **gains** it unlocks.
The work that leads to it is **epics** and **tasks**. The page answers three questions at a glance:

1. **What is unlocked?** Lit nodes are done: the past.
2. **What can start now, and what waits?** These are the dim nodes: the future. A node marked *available* has every
   prerequisite done. A *locked* node waits on one that is still open.
3. **What does the rest cost?** Done work shows its actual cost. Open work shows an estimate, `≈$X (low–high)`.
   Every region shows the sum of what is inside it.

The map uses **semantic zoom**. Each zoom step opens regions one level deeper:

| Level | What it draws |
|---|---|
| **L0** | Goal regions in topic bands, with each goal's points, its gains, its progress, the cost spent and the ≈cost to go. Goal → goal `builds-on` edges. |
| **L1** | A goal opens into its epics, with their progress and costs, and into its **point B** star with all of its gains. |
| **L2** | An epic opens into task cards, each showing its state word and icon, its actual cost or estimate, and a link. |

A region opens only when its children are big enough on screen to read. Edges always join the outermost closed
region on each side, so a dependency stays visible at every level.

**Gestures:**

- Drag to pan.
- Use the wheel, a pinch or `+`/`-` to zoom.
- Double-click a region, or press Enter on it, to fly into it. `Esc` goes back out a level, and `0` fits the map.
- A topic chip focuses one branch.
- Every node is in the readout and in the table view. The table needs no colour to read.

Requirements: Python 3.9+ (standard library only). Node.js is optional; the tests use it to run the layout. A
Chromium browser is optional, for screenshots. The page makes **no network request**: fonts, CSS, JS and data are
all inline.

## The schema: `scifi-graph/1`

```json
{"schema": "scifi-graph/1", "title": "Refit plan", "generated": "2301-06-24T08:00Z", "currency": "USD",
 "topics": [{"id": "propulsion", "label": "Propulsion"}],
 "notes": ["6 % of spend named no task and is not attributed."],
 "nodes": [
  {"id": "adr:helix/0003", "kind": "goal", "label": "ADR 0003", "title": "Retrofit the ion drive",
   "state": "open", "status": "Proposed (2301-06-01)", "topic": "propulsion", "url": "https://…",
   "gains": ["+5 transit drops from 41 to 26 days", "+2 reaction mass lasts two more voyages"],
   "decides": ["D1 — continuous low burn", "D2 — the thermal loop carries the drive's heat"]},
  {"id": "helix#114", "kind": "epic", "parent": "adr:helix/0003", "title": "Drive power", "state": "open"},
  {"id": "helix#116", "kind": "task", "parent": "helix#114", "title": "Bus upgrade to 2 MW", "state": "active",
   "cost": {"estimate": 7.8, "low": 6.8, "high": 8.8}},
  {"id": "helix#115", "kind": "task", "parent": "helix#114", "title": "Headroom study", "state": "done",
   "closed": "2301-06-02", "cost": {"actual": 8.64}}],
 "edges": [{"from": "helix#115", "to": "helix#116", "kind": "needs"},
           {"from": "adr:helix/0002", "to": "adr:helix/0003", "kind": "builds-on"}]}
```

| Field | Meaning |
|---|---|
| `kind` | `goal` (point B, never has a parent), `epic` or `task`. Any node can hold children; `parent` nests them. |
| `state` | The source's own state: `done`, `active` (someone is on it now) or `open`. The renderer derives the tree state: **unlocked** = done, and for a container also nothing inside it still open. **available** = open with every prerequisite done. **locked** = waiting on an open prerequisite. |
| `edges` | Prerequisite → dependent. `needs` is between pieces of work; `builds-on` is between goals. |
| `cost` | `actual` for spent work, `estimate` with an optional `low`/`high` for open work. **A missing number is left out, never 0.** It shows as N/D and is counted as N/D in every sum above it. |
| `gains` | The goal's gains, one string each. A leading `+N` is the gain's weight; without one the weight is 1. A goal's points are the sum. Points count as unlocked when the goal is. |
| `decides` | What the goal decides. It is shown, marked "decides", when there are no gains. It never earns points. |
| `label` | The short name on a card. The default comes from the id: `repo#12` → `#12`, `adr:repo/0003` → `ADR 0003`. |
| `notes` | Lines under the HUD. Use them for what the numbers leave out, such as unattributed spend or the estimate method. |

Topic hues are fixed: the first six topics in `topics` get one hue each, and every later topic is "other" (grey).
That keeps colour following the topic, not its rank. The palette passes the dataviz validator against the dark
surface. Identity never rests on colour alone, because every node carries an icon, a state word and a label.

## Procedure

1. **Goals from the decision records.** `scifi_graph.py adrs docs/adr --repo NAME --url-base URL -o goals.json`
   reads `NNNN-*.md` files:
   - **title:** the first `#` line.
   - **state:** the `Status:` line. Accepted or implemented means done; rejected or withdrawn records are skipped.
   - **gains:** a `## Gains` section, one `-` bullet per gain.
   - **decides:** the `D1 — …` items under `## Decision`.
   - **builds-on edges:** the header lines `Builds on:`, `Extends:`, `Amends:`, `Supersedes:` and `Depends on:`.

   Pass `--topic` per directory, or set `topic` on the goals afterwards.
   - **Gains are written, never inferred.** If a record has no `## Gains` section, it shows "decides" and earns no
     points.
   - **Add the section to records that lack it,** if the user wants points. Ask the owner of the record what each
     gain is worth: a weight is a ruling, not a measurement.
2. **The work, from the tracker.** For each goal, build an epics and tasks file in the same schema:
   - **Epics.** The tracking issues that name the goal become epics with `parent` set to the goal.
   - **Tasks.** The sub-issues of each epic become its tasks.
   - **Edges.** These come only from what the tracker records:
     - native "blocked by" links;
     - stacked pull requests, where one PR's base branch is another PR's head;
     - explicit "after #N" fields.

     Never invent an edge from similar titles.
   - **Close dates.** Record `closed` on done tasks.
3. **Actual cost.** Sum what each task's work cost. Agent sessions are a good source: the session cost goes to the
   issue its prompt names. Work that names no task stays unattributed. Say how much there is in `notes`; never spread
   it over tasks.
4. **Merge and estimate.** Run `scifi_graph.py merge work.json goals.json -o plan.json`; the first definition of an
   id wins. Then run `scifi_graph.py estimate plan.json -o plan.json`. It fills each open task that has no estimate
   with the median actual cost of done tasks of the same kind and topic in the last 30 days, as p25–p75. With fewer
   than 5 such tasks it pools all topics. With none, the cost stays N/D. It also adds the method to `notes`.
5. **Check and build.** Run `scifi_graph.py check plan.json`, then `scifi_graph.py build plan.json -o tree.html`.
   `check` rejects these, and `build` refuses to write a page while any of them remain:
   - duplicate ids;
   - dangling edges or parents;
   - cycles, named node by node;
   - a goal with a parent;
   - a negative or malformed cost;
   - a `javascript:` url.
6. **Look at it.** Open the page, or screenshot it at three zooms. Check that the L0 summaries are readable and that
   one epic and one task open as you zoom. Then check the readout of one locked node: its NEEDS list should name what
   it waits on.

`examples/` holds a full worked example, HELIX, a fictional ship's refit:

- five records in `examples/adr/` with `## Gains` sections and `Builds on:` lines;
- `examples/work.json`, the epics and tasks;
- `examples/helix.graph.json`, the result of merge + estimate.

Rebuild it with:

```sh
S=scripts/scifi_graph.py
python3 $S adrs examples/adr --repo helix --url-base https://example.org/helix/adr -o /tmp/goals.json
# set each goal's topic, then:
python3 $S merge examples/work.json /tmp/goals.json -o /tmp/plan.json
python3 $S estimate /tmp/plan.json --min-samples 3 -o examples/helix.graph.json
python3 $S build examples/helix.graph.json -o /tmp/helix.html
```

## Embedding it in a site

`assets/scifi-graph.js` and `assets/scifi-graph.css`, together with `../../shared/theme.css`, are all a site needs:

```html
<div id="tree"></div>
<script src="scifi-graph.js"></script>
<script>SciFiGraph.render(document.getElementById("tree"), graph);</script>
```

`graph` can come from anywhere that emits the schema. A site with live data can assemble the graph in the browser,
for example from PromQL info series, and then call `render`. Copy the files in and keep the version comment at the
top of the JS. Don't hot-link them.

## What it is not

- **Not a Gantt chart.** The x axis is dependency order, not time. Open work has no dates, and invented dates are
  worse than none.
- **Not a progress tracker.** For "how far along is each goal", use the `goal-map` skill. For history over time, use
  `time-charts`.
- **Not a library graph layout.** The layout is nested layered DAGs in about 200 lines. A plan of a few hundred
  nodes draws in well under a second. Past about 2,000 nodes, split the plan by topic into several pages.
