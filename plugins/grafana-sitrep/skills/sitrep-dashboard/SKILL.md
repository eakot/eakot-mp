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
**A:** A machine id is never the label. Lead with the meaning: the title or the task. Push the id to
the end of the line, dimmed, and make it the link to its file or record. An id with no link and no
meaning comes off the page.

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

**Q: "What time is that?"**
**A:** Display in the reader's zone: `timezone: browser` on every dashboard, and the server default
too. Compute "today" in the zone the operator ruled, and print it in the sub-head
(`today, 00:00 UTC → now`).

**Q: "Is the backlog collapsing?"**
**A:** Show a flow as a pair. Inflow goes above zero and outflow below it, per entity, with a net
line. A one-sided count (closed per day) cannot answer the question it was built for.

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
   or away.
2. **Answer as the operator.** Query every series live. Mark each defect:
   - an impossible value;
   - "No data";
   - a row of zeros;
   - an unreadable label;
   - a meaningless id;
   - an entity with no link.

   Find the cause of each one in the query, not the style. Most "ugly" panels are wrong panels.
3. **Get the rulings.** Ask the human, in one message, only the rulings listed in §1 that the data and
   history cannot settle.
4. **Group and rank.** Arrange one row per question, most expensive first. The sheet goes on the left
   (`w` 8–12), its history to the right, both the same height. Number the sheets `01`, `01·B`, `02`, and
   so on.
5. **Generate, don't hand-edit.** Write a generator that reads the *original* JSON and writes the new
   one, using `scripts/sitrep.py` (`sheet`, `history`, `today`, `opened_closed`, `registry`, `finish`).
   Start from `examples/refactor_example.py`. Keep the generator, the original and the assets together,
   so the next change is a rerun. Write the JSON in the file's own format (indent, `ensure_ascii`): the diff then
   shows the change, not a reformat. `finish()` refuses overlapping or over-wide panels.
6. **Render and check.** Run `scripts/render_check.py <url> shot.png` (it reads the token from
   `GRAFANA_TOKEN`; it scrolls the page, because Grafana renders a panel only once it is in view). It checks for:
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
| Values | `dur`, `pct`, `num`, `usd`; `lvl(x, [[0,'ok'],[2,'warn'],[6,'bad']])`; `worst(states)` |
| Layout | `page(no, title, body)`, `brief`, `sub`, `ln(label, value, state, note)`, `item(text, state, wrap)`, `foot`, `raw(text)` for a file shown as written |
| Columns | `<div class="cols">…</div>` |

Rules:

- **Escape everything from data.** Use `esc()`, or `linkify()`, which escapes first. Never interpolate
  a label raw.
- **Write the verdict last.** Compute it from the same values the lines show, so the two cannot
  disagree. Its priority order is the sheet's: stuck/red first, then silent drivers, then idle for
  cause, then the all-clear.
- **Cap lists.** Show five items, then `+N more`. Long free text wraps (`item(..., true)`). Everything
  else truncates with an ellipsis.

## 5. Files

| Path | What it is |
|---|---|
| `assets/briefing_lib.js` | The renderer, embedded into every sheet. Change it here, then regenerate. |
| `assets/briefing.css` | The style: flat background, monospace, state colours. |
| `scripts/sitrep.py` | Panel builders and the `today()` and layout checks. |
| `scripts/render_check.py` | The headless render plus the checks from step 6. |
| `examples/refactor_example.py` | A deploy page refactored end to end. |
| `reference/traps.md` | Every defect the first page shipped with, its cause, and the fix in these files. |

Requires the **Business Text** panel plugin (`marcusolsson-dynamictext-panel`, tested on 6.2.0 with
Grafana 11.3). Live tables (a registry, a work feed) need the **Infinity** datasource. Pin both
versions in the Grafana install. The font is fetched from Google Fonts and falls back to the system
monospace.
