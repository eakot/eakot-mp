---
name: sitrep-dashboard
description: Refactor a Grafana dashboard into dense "sitrep" status sheets — a monospace mission briefing with a one-line verdict, then a table of contents of every number (label ...... value [OK/WARN/ACT]), every git entity a link — beside the history charts. Use when asked to make a dashboard readable at a glance, denser, less "big numbers", sci-fi / briefing / terminal styled, or to fix panels that read "No data", impossible peaks, or rows of zeros.
---

# Sitrep dashboards

A sitrep page answers the operator's questions in the order that missing one would hurt. Each answer is a
**status sheet**, built from these parts:

- **SITREP line.** One sentence that names the move, or says there is none.
- **Contents lines.** A list of every number behind that sentence, each with a state tag.
- **History chart.** A time series beside the sheet showing how the number got there.

Big digits, gauges and rows of stat tiles are replaced, not restyled.

```
 01  LANES
 ┃SITREP┃ 2 slot(s) idle for cause: no-supply.
 slots busy ............................... 1 / 3   OK
 slots stuck .................................. 0   OK
 ▸ FREE SLOTS — WHY IDLE
 no-supply · queue empty — refill .............. ×2  ACT
 ▸ TODAY, 00:00 UTC → NOW
 unintended idle ......................... 4.2 lane-h WARN
```

## 1. The role you take

**You sit in the operator's chair for the whole job.** The operator does not design the page; they
*read* it at the start of the day with one question: *is it going well, and if not, whose move is it?*

Work as that reader:

1. Ask the operator's questions (§2) of every panel.
2. Answer each one yourself, from the live data and the rendered page.
3. Write down every answer that took longer than a glance, or came out wrong. Each of those is a defect.

**Only rulings go to the human.** Ask the person for these and nothing else:

- what "today" means;
- which idle or red state is intended;
- the threshold behind each WARN and ACT;
- the ranking by cost, if you cannot read it from postmortems or history.

Everything else you decide, and the panel description records the decision. Do not ask "should I add
links?" or "do you want a verdict line?". The answer is always yes, and it is in this file.

## 2. The operator's questions, and the answer each one forces

Every principle below was a complaint on a real page. The dated defects are in `reference/traps.md`.

**Q: "Is the day going well?"**
**A:** Every sheet opens with a SITREP line. It states the verdict *and* the move: "Production is NOT
running main for: api ▸ deploy". "2 gates red" is not enough. When everything is fine, say so plainly:
"All 7 deploy gates green — production runs main". The page's top row is the most expensive question.
Rank the rest by what missing each one cost: hours of stale production, idle capacity, work that read
done but didn't land, budget, goal, instrument health.

**Q: "I see big digits. What do they mean?"**
**A:** Use a table of contents, not tiles. One line per number: `label ..... value [TAG]`, with a
sub-head per group. A dense page that reads top to bottom beats a sparse one that needs hovering. The
label is the human name. A unit or a qualifier rides in the value (`4.2 lane-h`, `RED 3h 10m`) or in a
dim note under the line.

**Q: "Do I have to do something about this line?"**
**A:** Every line carries a state tag, and the tags mean the same thing on every sheet:

| Tag | Meaning |
|---|---|
| `OK` | fine |
| `WARN` | look |
| `ACT` | someone must act |
| `INFO` | idle *on purpose* |
| `N/D` | no data |
| `····` | context, not a state |

Only ACT blinks. INFO is what keeps intended idleness (budget, end of day) from shouting like a defect,
so classify every state as intended or a defect before you write a threshold. The thresholds go in the
panel description.

**Q: "Where do I click to act on it?"**
**A:** Every git entity is a link: repo, PR, issue, commit, workflow, file and branch search. So is
every reference inside free text, `api#297`, `owner/name#3` or a bare `#12`, which takes the row's own
repo. Links open in a new tab, so the dashboard never navigates away. Resolve repos through one registry,
either a live table or the generator's map, never a per-sheet copy. An entity the registry does not know
stays **plain text**, because a guessed link 404s.

**Q: "What is `node N39323102473`?"**
**A:** A machine id is never the label: the meaning (the title) is, and it links to the work. The id
stays on the line dimmed, as the link to its file or record. An id with no link and no meaning comes
off the page.

**Q: "Why does every line start its text somewhere else?"**
**A:** Fixed-length fields lead the line, each in its own fixed-width column (`fx(w, html)`): the id,
lane, model, uptime, and any field drawn from a small known set (a topic: pad the column to the
longest value). Free text, the title, a PR ref and so on, comes after them. Each line then reads
like a table row, and the eye finds the title at the same column on every line. A short field
placed after the title moves around and reads as noise. A number in a column is fixed-width too:
pad it, so "22 h" and " 5 h" end at the same column. A duration in a column is `durCol(s)` (two
units, each padded to two places with a figure space, right-aligned to 9 characters); `dur(s)` is
for a value inside a sentence.

**Q: "The text is cut off. What does it say?"**
**A:** Text too long for its line goes to a hover tooltip (`item(text, state, wrap, tip)`), not to
an ellipsis that nobody can expand. Keep on the line only what fits, and move the long remainder
(a task, a verdict) to the tooltip. A name is never shortened at the **source** to fit some other
view: when a feed clips a field to fit a graph box, add a full-length field beside it for the sheet.
Shorten at render time only, and keep the clipped copy only where the narrow view needs it.
A name is plain text, too: when it comes from markdown (a plan row, an issue title), the feed strips
the emphasis (`**held**` → `held`) where it reads the name, so no view shows the asterisks. Strip
only the `**…**` pairs: a lone `*` (`test_*.py`) is part of the name.

**Q: "What happened in the last hour?"**
**A:** A history chart's bucket is the source's write cadence: an exporter that writes every
5 minutes gets `interval: "5m"`. Finer only repeats the same sample; coarser hides detail the data
has. Name the bucket in the title ("— 5-minute average"). Grafana's `interval` is only a minimum,
and Grafana widens buckets to fit the panel's pixels. So set the page's default range so the finest
chart still draws one bar per bucket (about 12 h for 5-minute buckets). Give each per-day or weekly
chart its own range (`timeFrom: "14d"`), so a short page default does not cut it to one bar.

**Q: "Can I trust this number?"** This one is asked most, and it has four answers:

- **No data is not zero.** A missing value reads `—` and `N/D`, never `0` and `OK`. If the sheet's
  own source is down, the SITREP says the numbers are stale.
- **No impossible values.** A stack of 3 slots must not peak at 14.6. Chart a *gauge* averaged per
  bucket (`avg_over_time(g[$__interval])`, `min 0`), never `increase()` of a total booked when work
  finishes. Say the unit, and say what the stack may legitimately exceed and why.
- **"Today" must survive a gap.** Use `sitrep.today()`, which takes the last sample before midnight,
  not a sample *at* midnight. Every today-number states which day it means.
- **Classify against real history before shipping.** Replay a day of recorded data through any new
  category rule and ask whether the operator would recognise the split. A bucket stuck at 0 on day
  one means the rule is wrong.

**Q: "Which host is this about?"** (a templated page: one host, one repo, one service at a time)
**A:** Keep the original's template variables, and filter every target by them. Each sheet names the
entity it shows, from one identity query (`node_uname_info{instance="$node"}` → name, VM id, kernel),
so a screenshot passed around still says whose numbers these are. An empty or unknown variable is a
state too: every sheet then reads N/D, and the first SITREP says "no host picked", not "all clear". Dry-run
each sheet on several entities before shipping (§3 step 5): a node, a VM, one without systemd, one that
does not exist. A rule that holds on the host you built it on can misfire on its siblings.

**Q: "Is it red on every host, or only here?"**
**A:** Before a failure gets ACT, query it across the whole fleet. A failure that every host shares is
the template, not this host: the IPMI units that fail on every VM with no BMC are INFO, and the note
says "fails on every host". The same goes for a counter every guest shares (identical receive drops
on every VM on one LAN): it is context, not loss. A per-entity page that shouts a fleet-wide constant
teaches the reader to skip the ACT tag.

**Q: "It says the collector failed. Is the sheet blank?"**
**A:** A health flag is not the data. Check the series the sheet *reads*, not the producer's own
verdict on itself. node-exporter reports `pressure` as failed on a kernel with no irq PSI file, while
the memory, CPU and I/O series it reads are all there. So a failed producer whose series are present
is INFO ("partial"), and only a failed producer whose series are gone is WARN. Map each producer to
one series it must yield, and test that series for presence.

**Q: "It fills in 4,811 days?"**
**A:** A forecast is only as good as its window. A 24-hour `deriv` on a disk that does not move
extrapolates noise into years. Cap the horizon at a few multiples of the window (30 days for a 24-hour
fit), and show anything further out as "not filling within 30 d". A precise-looking number that nobody
should act on is worse than none.

**Q: "What time is that?"**
**A:** Display in the reader's zone: `timezone: browser` on every dashboard, and the server default
too. Compute "today" in the zone the operator ruled, and print it in the sub-head
(`today, 00:00 UTC → now`).

**Q: "Is the backlog collapsing?"**
**A:** Show a flow as a pair. Inflow goes above zero and outflow below it, per entity, with a net
line. A one-sided count (closed per day) cannot answer the question it was built for. A line chart is
floored at 0, which cuts the whole outflow off: pass `history(..., signed=True)` to any chart with a
side below zero (this includes traffic in and out).

**Q: "I can't read it."**
**A:** Use a monospace body, an uppercase display face for headers only, and a **flat monochrome
background**. Decoration never crosses text: no scanlines, no gradients, no grid behind values. Dim
grey is for what is secondary (ids, notes, sources). Colour means state, and only state. Keep names
readable. A column of zeros with truncated labels is a failure, even though every value in it is
correct.

**Q: "Why is it computed like that? What can't it see?"**
**A:** The panel description (the ⓘ) carries four things:

- the definition of each line;
- the source and how often it updates;
- the thresholds;
- the history of a fix: "it used to read X; that drew 14.6".

End with **GAP:**, naming what the sheet cannot see ("no production HTTP status series, so a 502 is
invisible here"). An unnamed gap reads as green.

## 3. Workflow

1. **Inventory.** Export the dashboard JSON. For every panel, write down the operator question it
   answers, its query, and what it shows *now*. A panel with no question goes to the bottom, collapsed,
   or away. A large community dashboard (Node Exporter Full: 14 rows, ~120 panels) keeps its deep rows
   as the drill-down: the sheets replace only its top rows of tiles and basic charts, and
   `carry_rows(src["panels"], y, drop=..., prefix="Drill-down · ")` carries the rest below them,
   collapsed. Keep the original's uid, so links to it still work.
2. **Answer as the operator.** Query every series live. Mark each defect:
   - an impossible value;
   - "No data";
   - a row of zeros;
   - an unreadable label;
   - a meaningless id;
   - an entity with no link.

   Find the cause of each one in the query, not the style. Most "ugly" panels are wrong panels.
3. **Get the rulings.** Ask the human, in one message, only the rulings listed in §1 that the data and
   history cannot settle. A threshold that an alert rule in the repo already pages on is not a ruling:
   copy it, and name the rule in the (i). When no one is there to answer (a background run), set the
   rest yourself, mark each one in the (i) as "this page's ruling", and list them all in the hand-over.
4. **Group and rank.** Arrange one row per question, most expensive first. The sheet goes on the left
   (`w` 8–12), its history to the right, both the same height. Number the sheets `01`, `01·B`, `02`, and
   so on.
5. **Generate, don't hand-edit.** Write a generator that reads the *original* JSON and writes the new
   one, using `scripts/sitrep.py` (`sheet`, `history`, `today`, `opened_closed`, `registry`, `finish`).
   `history` requires `interval`, the source's cadence; `finish(d, time_range=...)` sets the page default.
   Start from `examples/refactor_example.py`. Keep the generator, the original and the assets together,
   so the next change is a rerun. Write the JSON in the file's own format (indent, `ensure_ascii`): the diff then
   shows the change, not a reformat. `finish()` refuses overlapping or over-wide panels.

   **Then dry-run every sheet before you deploy:**
   `scripts/sheet_harness.py out.json <prom-url> --var node=... --var job=...`. It runs each sheet's
   queries against live data, runs the sheet's helper code in `node`, and prints the sheet as text,
   SITREP line first. It fails on a helper that throws, on `undefined` or `NaN` text, and on a sheet
   with no SITREP. Run it once per entity (step 2 of the "Which host?" answer) and once with a value
   that matches nothing. A deploy-and-screenshot round trip takes minutes; this takes seconds, and it is
   where most classification mistakes show up.
6. **Render and check.** Run `scripts/render_check.py <url> shot.png`. It reads the token from
   `GRAFANA_TOKEN`, or from the file `GRAFANA_TOKEN_FILE` names, such as the one mcp-grafana already
   keeps, so the token never passes through argv. It scrolls the page, because Grafana renders a panel
   only once it is in view. Put a templated page's variables in the URL (`&var-node=...`). It checks for:
   - zero sheets;
   - same-tab links;
   - `undefined` or `NaN` text;
   - sheets with no SITREP;
   - "No data" panels;
   - page errors.

   Then run the dashboard validator, if the repo has one.
7. **Walk-through, in the operator's chair.** Open the screenshot. Ask every §2 question of every
   sheet, and answer each in one sentence from the image alone. A question that takes more than a glance
   to answer is a defect: go back to step 2. Then try to break it, or hand it to a fresh-context
   reviewer. Feed in `constructor#5`, an apostrophe, an empty registry and a missing frame.
8. **Hand over.** In the change description, give the before and after of every defect from step 2,
   and every ruling with its source.

## 4. Writing a sheet

`body_js` must assign `html`. The library gives you:

| Group | Helpers |
|---|---|
| Data | `rows(ref)` → `[{labels, value}]`; `one(ref)`; `table(ref)` for Infinity or SQL frames |
| Links | `repoA`, `prA`, `commitA`, `fileA`, `wfA`, `refA`, `linkify(text, repo)` |
| Values | `dur` (inline), `durCol` (a fixed-width column), `pct`, `num`, `usd`; `lvl(x, [[0,'ok'],[2,'warn'],[6,'bad']])`; `worst(states)` |
| Layout | `page(no, title, body)`, `brief`, `sub`, `ln(label, value, state, note)`, `item(text, state, wrap, tip)` (`tip` = hover text), `fx(w, html)` (a fixed-width column of `w` ch), `foot`, `raw(text)` for a file shown as written |
| Columns | `<div class="cols">…</div>` |

Rules:

- **Escape everything from data.** Use `esc()`, or `linkify()`, which escapes first. Never interpolate
  a label raw.
- **Write the verdict last.** Compute it from the same values the lines show, so the two cannot
  disagree. Its priority order is the sheet's: stuck/red first, then silent drivers, then idle for
  cause, then the all-clear.
- **Cap lists.** Show five items, then `+N more`. Long free text that must be read wraps
  (`item(..., true)`), or else goes whole into the line's hover `tip`. An ellipsis is only a fallback
  for a narrow panel, never the only way to read the text.
- **Lead with the fixed fields.** `fx()` columns first, then the free text (see §2).
- **Never read `__name__` from a label.** To key a sheet by metric name, copy the name into a plain
  label in the query: `label_replace(..., "metric", "$1", "__name__", "(.*)")`, then read
  `labels.metric`.

## 5. Files

| Path | What it is |
|---|---|
| `assets/briefing_lib.js` | The renderer, embedded into every sheet. Change it here, then regenerate. |
| `assets/briefing.css` | The style: flat background, monospace, state colours. |
| `scripts/sitrep.py` | Panel builders (`sheet`, `history`, `opened_closed`, `carry_rows`), plus `today()` and the layout checks. |
| `scripts/render_check.py` | The headless render plus the checks from step 6. |
| `scripts/sheet_harness.py` | Runs every sheet against live data in `node` and prints it as text, before deploying (step 5). |
| `examples/refactor_example.py` | A deploy page refactored end to end. |
| `reference/traps.md` | Every defect the first page shipped with, its cause, and the fix in these files. |

## 6. Requirements

| Component | Version | Needed for |
|---|---|---|
| Grafana OSS | **11.3** (tested on 11.3.0) | the page. Status sheets are HTML plus JavaScript in a panel, so a newer major release needs a re-test |
| [Business Text](https://grafana.com/grafana/plugins/marcusolsson-dynamictext-panel/) panel (`marcusolsson-dynamictext-panel`) | **6.2.0** | every status sheet. 6.2.0 is the newest release that supports Grafana 11.x; 6.2.3 and later need Grafana 12.3 |
| [Infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/) datasource (`yesoreyeram-infinity-datasource`) | **3.7.1** | only sheets that read a live JSON table (a repo registry, a work feed). 3.7.1 is the last release that loads on 11.3 |
| [VictoriaMetrics](https://victoriametrics.com/) as the PromQL datasource | any current release | `sitrep.today()` puts a computed timestamp after `@` (`@ (time() - time() % 86400)`), which VictoriaMetrics accepts and Prometheus does not: Prometheus allows only a fixed timestamp, `start()` or `end()`. On Prometheus, rewrite `today()` before using it |
| Python | 3, standard library only | `scripts/sitrep.py` and the generators |
| [Playwright](https://playwright.dev/python/) with Chromium | any current release | only `scripts/render_check.py`: `pip install playwright && playwright install chromium` |
| [Node.js](https://nodejs.org/) | any current release | only `scripts/sheet_harness.py`, which runs the sheets' helper code outside Grafana |

Pin both Grafana plugins in the install, for example in Docker Compose:

```yaml
GF_INSTALL_PLUGINS: "marcusolsson-dynamictext-panel 6.2.0,yesoreyeram-infinity-datasource 3.7.1"
GF_DATE_FORMATS_DEFAULT_TIMEZONE: browser   # every timestamp in the reader's zone
```

The sheet font (Share Tech Mono) loads from Google Fonts and falls back to the system monospace.
