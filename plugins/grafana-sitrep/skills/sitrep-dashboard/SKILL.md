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

A usage page brings its own typical rulings (one person under two logins, what counts as "active", an
item idle on purpose, "current version" from content hashes): see the end of `reference/traps.md`.

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

**Q: "What depends on what, and where is it stuck?"**
**A:** A graph view is rows of **rectangles**, drawn by `flow(rows, edges)`: one row per lane or
queue, its nodes in their real order left to right. The text sits *inside* the box, fixed fields
first (id, then the name, then the topic or the wait); the state reads **once, under** the box, in
its level's colour. Dependencies are arrows between boxes. Do not use Grafana's Node Graph for a
sitrep graph: its circles put the state inside and the name under the node, repeat the state as
a ring colour that needs a legend, and stack every node of a fan-out into one column (31 PRs drew
31 rows). Order a fan-out into chains by the queue's own order instead. A row flows toward its
exit: the back of the queue on the left, the front (next to leave, longest wait) on the right,
beside where it goes. Drawn front-first, a red stuck item "leads to" a yellow one and the reader
takes the arrow for a dependency. Say in the footer that an arrow inside a row is order.

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

**Q: "Each sample is an event. How do I count them?"** (event telemetry: one sample of value 1 per
call, `ai_skill_call{login="ann"} 1 <ts>`, not a gauge or a counter)
**A:** Count samples, never `increase` or `rate` them. Four forms answer most questions:

| Question | Query |
|---|---|
| events per bucket | `sum(count_over_time(x[$__interval]))` |
| active days per entity, last 14 | `sum by (login) (count_over_time((count by (login) (count_over_time(x[1d])) > 0)[14d:1d]))` |
| last seen, seconds ago | `time() - max by (login) (tlast_over_time(x[30d]))` (VictoriaMetrics) |
| distinct entities per bucket | `count(count by (login) (count_over_time(x[$__interval])))` |

No event in the window is no series at all, not a 0: the sheet's N/D path is the normal case for a quiet
entity, so run the empty fixture (§3 step 5).

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

**Q: "Someone outside the team reads this. What does it mean?"** (HR, management: "how many people use
it, how often?")
**A:** Write that sheet in the reader's words, not the operator's:

- **No state tags.** Every line is `····` context (or `N/D`): ACT and WARN mean nothing to this reader.
- **No verdict label.** `sheet(..., brief_label=None)` drops "SITREP"; the yellow rule still marks the line.
- **No system names.** Say what was done ("questions to company systems instead of a manual search"), not
  which system did it (MCP, skills, hooks).
- **Whole words**, with the right plural: `${int(n)} ${plural(n, ['person', 'people'])}`, or in Russian
  `plural(n, ['человек', 'человека', 'человек'])`. Never "15 чел.". Big numbers grouped: `int(n)`, in the
  sheet's `locale`.
- **The (i) explains every term** and says what cannot be counted. If team headcount is not in the
  telemetry, there is no "% of the team", and the (i) says why.

`examples/plain_overview_example.py` is one such sheet.

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
   or away. Keep the original's uid, so links to it still work. Then pick one of two modes:
   - **Keep.** The legacy panels stay as a drill-down below the sheets. A large community dashboard
     (Node Exporter Full: 14 rows, ~120 panels) keeps its deep rows: the sheets replace only its top
     rows of tiles and basic charts, and `carry_rows(src["panels"], y, drop=..., prefix="Drill-down · ")`
     carries its collapsed rows below them. Panels of an *expanded* row go with
     `carry_panels(src["panels"], ids, y, title)`: copied as-is into one collapsed row, packed, and
     renumbered (`id_offset`, 1000 by default), so they cannot take a new sheet's id.
   - **Full redraw.** No legacy panel survives, and every one is accounted for. Write the map first:
     for each original panel, the question it answered and the new panel that answers it now. Keep it in
     the generator as `sitrep.coverage(src["panels"], {old_id: new_id | "covered-by:<id>" |
     "dropped:<reason>"}, new_panels, questions)`: it refuses an unmapped original, an unknown target and
     a drop with no reason, and returns the coverage table for the hand-over. Then check **information
     parity**: every metric, filter, `by (...)` dimension, window and statistic (avg, p50, p95, count)
     of every original target is on some new panel. `sitrep.parity(src["panels"], new_panels)` lints the
     metric names and `by (...)` labels; the windows and statistics you check by eye. The original's
     "how to read" text panels move into the sheets and their (i). A legacy statistical quirk is kept and
     labelled (`*`, the reason in the footer), not silently "fixed". `carry_panels()` is a fine first
     step: carry as-is, then redraw panel by panel.
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
   Start from `examples/refactor_example.py` (keep mode) or `examples/plain_overview_example.py` (full
   redraw). Keep the generator, the original and the assets together, so the next change is a rerun.
   Write the JSON in the file's own format (indent, `ensure_ascii`): the diff then shows the change, not a
   reformat. `finish()` refuses overlapping or over-wide panels and duplicate ids, inside collapsed rows
   too. Pass generator data to a sheet with `consts={"TN": names}`, never by `%`-formatting or f-stringing
   the JS (a JS `%` or `{` breaks it).

   **Then dry-run every sheet before you deploy:** `scripts/sheet_harness.py out.json <source>`. It runs
   each sheet's queries, runs the sheet's helper code in `node`, and prints the sheet as text, verdict line
   first. It fails on a query the datasource rejects, a helper that throws, `undefined` or `NaN` text, and
   a sheet with no verdict line. Sheets in collapsed rows run too, and with a live source every history
   chart's targets run once as a range query (a `duplicate output timeseries` 422 shows only there). The
   source is one of:
   - `<prom-url>`, the datasource's own URL, when you can reach it;
   - `--grafana <url>`, through Grafana's datasource proxy, when only Grafana can reach the datasource
     (an in-cluster URL). It needs a Grafana service-account token (step 6);
   - `--fixture file.json`, `{refId: [[labels, value], ...]}`, filled from whatever query tool you have
     (an MCP server's one-expression-at-a-time query is enough). Keep the hostile inputs in one:
     `constructor#5`, an apostrophe, `<b>`;
   - `--empty`, **mandatory**: every target answers nothing. Every number must read N/D, and a line
     tagged OK fails the run. It catches the sheets that say "0 · OK" with no data.

   Add `--var node=...` per entity (step 2 of the "Which host?" answer), and run once with a value that
   matches nothing. A deploy-and-screenshot round trip takes minutes; this takes seconds, and it is where
   most classification mistakes show up.
6. **Deploy, render and check.** Deploy with `scripts/deploy.py out.json <grafana-url> [--folder <uid>]`:
   the file goes straight to `/api/dashboards/db`, so its size does not matter (a dozen sheets is over
   100 KB, too large to pass reliably as a tool-call argument) and the token never passes through you.
   Every script reads the token from `GRAFANA_TOKEN`, or from the file `GRAFANA_TOKEN_FILE` names, never
   from argv. It must be a **Grafana service-account token** (`glsa_…`): a gateway's token, such as the
   one an MCP server in front of Grafana takes, gets 401 "Invalid API key", and the scripts check this
   first and say so. With no token at all, hand the operator the file to import in the UI.

   Then run `scripts/render_check.py <url> shot.png`. It scrolls the page, because Grafana renders a panel
   only once it is in view. Put a templated page's variables in the URL (`&var-node=...`). It checks for:
   - zero sheets;
   - same-tab links;
   - `undefined` or `NaN` text;
   - sheets with no SITREP;
   - "No data" panels;
   - page errors.

   Playwright is optional. Without it, open the page and check the same list by hand, the browser
   console included. Then run the dashboard validator, if the repo has one.
7. **Walk-through, in the operator's chair.** Open the screenshot. Ask every §2 question of every
   sheet, and answer each in one sentence from the image alone. A question that takes more than a glance
   to answer is a defect: go back to step 2. Then try to break it, or hand it to a fresh-context
   reviewer. Feed in `constructor#5`, an apostrophe, an empty registry and a missing frame.
8. **Hand over.** In the change description, give the before and after of every defect from step 2,
   and every ruling with its source. For a full redraw, add the coverage table (old title → question →
   new panel), and name every place where the redraw is *more* precise than the original (a server-side
   histogram quantile in place of a worst-series approximation, say): a number that moved is otherwise
   read as a bug.

## 4. Writing a sheet

`body_js` must assign `html`. The library gives you:

| Group | Helpers |
|---|---|
| Data | `rows(ref)` → `[{labels, value}]`; `one(ref)`; `table(ref)` for Infinity or SQL frames |
| Links | `repoA`, `prA`, `commitA`, `fileA`, `wfA`, `refA`, `linkify(text, repo)` |
| Values | `dur` (inline), `durCol` (a fixed-width column), `pct`, `num`, `usd`, `int` (grouped digits, the sheet's `locale`), `plural(n, forms)` (`[one, other]` or `[one, few, many]`); `lvl(x, [[0,'ok'],[2,'warn'],[6,'bad']])`; `worst(states)` |
| Layout | `page(no, title, body)`, `brief` (its label: `sheet(brief_label=...)` or `sitrep.BRIEF_LABEL`, `None` for none), `sub`, `ln(label, value, state, note)`, `item(text, state, wrap, tip)` (`tip` = hover text), `fx(w, html)` (a fixed-width column of `w` ch), `fxr(w, n)` (the same, right-aligned, for a number), `foot`, `raw(text)` for a file shown as written |
| Tables | `cols([[w, 'title', 'r'], ...])` → `{hdr, row(values)}`: the header line and every row share one width spec; `w = 0` is free text |
| Graphs | `flow(rows, edges, {w, lines})`: rows of rectangles, text inside, state under; edges drawn after render. Fill the box: `<div class="w2">` wraps a task or verdict over two lines, the whole of it in `tip` |
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
| `scripts/sitrep.py` | Panel builders (`sheet`, `history`, `opened_closed`, `carry_rows`, `carry_panels`), `today()`, the layout checks, and the full-redraw record (`coverage`, `parity`). |
| `scripts/sheet_harness.py` | Runs every sheet in `node` against live data, Grafana's proxy, a fixture or nothing, and prints it as text, before deploying (step 5). |
| `scripts/deploy.py` | Posts the generated file to Grafana (step 6). |
| `scripts/render_check.py` | The headless render plus the checks from step 6. |
| `scripts/grafana_api.py` | The token reader and preflight the three scripts share. |
| `examples/refactor_example.py` | A deploy page refactored end to end (keep mode). |
| `examples/plain_overview_example.py` | A plain-language sheet over event telemetry, as a full redraw with its coverage map; its original and fixture beside it. |
| `tests/test_sitrep.py` | Regression tests: `python3 -m unittest discover -s tests`. |
| `reference/traps.md` | Every defect the first page shipped with, its cause, and the fix in these files. |

## 6. Requirements

| Component | Version | Needed for |
|---|---|---|
| Grafana OSS | **11.3** (tested on 11.3.0) | the page. Status sheets are HTML plus JavaScript in a panel, so a newer major release needs a re-test |
| [Business Text](https://grafana.com/grafana/plugins/marcusolsson-dynamictext-panel/) panel (`marcusolsson-dynamictext-panel`) | **6.2.0** | every status sheet. 6.2.0 is the newest release that supports Grafana 11.x; 6.2.3 and later need Grafana 12.3 |
| [Infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/) datasource (`yesoreyeram-infinity-datasource`) | **3.7.1** | only sheets that read a live JSON table (a repo registry, a work feed). 3.7.1 is the last release that loads on 11.3 |
| [VictoriaMetrics](https://victoriametrics.com/) as the PromQL datasource | any current release | `sitrep.today()` puts a computed timestamp after `@` (`@ (time() - time() % 86400)`), which VictoriaMetrics accepts and Prometheus does not: Prometheus allows only a fixed timestamp, `start()` or `end()`. On Prometheus, rewrite `today()` before using it |
| Python | **3.9** or later, standard library only | `scripts/` and the generators. 3.9 is the macOS system Python, so a generator must run there too: no backslash inside an f-string's `{}`, no reused quote inside one, no `match` |
| [Playwright](https://playwright.dev/python/) with Chromium | any current release, optional | only `scripts/render_check.py`: `pip install playwright && playwright install chromium`. Without it, check the page by hand (step 6) |
| [Node.js](https://nodejs.org/) | any current release | only `scripts/sheet_harness.py`, which runs the sheets' helper code outside Grafana |

Pin both Grafana plugins in the install, for example in Docker Compose:

```yaml
GF_INSTALL_PLUGINS: "marcusolsson-dynamictext-panel 6.2.0,yesoreyeram-infinity-datasource 3.7.1"
GF_DATE_FORMATS_DEFAULT_TIMEZONE: browser   # every timestamp in the reader's zone
```

The sheet font (Share Tech Mono) loads from Google Fonts and falls back to the system monospace.
