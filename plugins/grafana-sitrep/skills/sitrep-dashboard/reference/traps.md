# Traps: what broke on the first sitrep page, and the fix now in the assets

Each trap was found on a live page, either by the operator reading it or by a fresh-context reviewer
trying to break it. The fixes are already in `assets/` and `scripts/`. This file says why they are
there, so nobody "simplifies" one away.

| # | What the operator saw | Cause | Fix |
|---|---|---|---|
| 1 | A slot chart peaking at **14.6 of 3** slots | `increase()` of a total that is booked when work finishes. After a 5-hour scrape gap, the whole gap landed in one bucket. | Chart a gauge sampled every pass, as `avg_over_time(g[$__interval])`, with `min 0`. A gap then draws as a gap. (`sitrep.history`) |
| 2 | *Unintended idle today* and *Busy share today*: **No data** all day | `X @ midnight` needs a sample exactly at 00:00, and an exporter gap across midnight left none. | `last_over_time(X[1d] @ midnight)`, plus `or sum(X)*0` for a series born today. (`sitrep.today`) |
| 3 | *Deploy gate red for*: "just many zeros", and the repo names were not readable | One stat tile per series: big digits, names truncated, 0 meaning green. | One sheet line per gate: `repo ▸ workflow ...... green [OK]`. Only red is a number. |
| 4 | *Issues closed per day*, with no way to tell whether the backlog was collapsing | Only the outflow was charted. | Inflow above zero and outflow below, per repo, plus a net line. (`sitrep.opened_closed`) |
| 5 | `node N39323102473` on the sheet | The machine id was shown as the label. | The title is the label and links to the work. The id stays on the line, dimmed, as the link to its file; trap 16 moved it into the leading fixed columns. |
| 6 | A link that opened inside the dashboard's own tab | Grafana's HTML sanitizer strips `target`. | The `afterRender` hook puts back `target=_blank` and `rel=noopener`. |
| 7 | `constructor#5` became a link to `https://github.com/function Object()...` | The repo map was a plain object, so the lookup walked into `Object.prototype`. | Use a `Map`. |
| 8 | "don't" became `don&` + a link to **issue #39** + `;t` | Escaping turned `'` into `&#39;`, and the linkifier then matched `#39`. | Escape first, then link, with `&` in the lookbehind. |
| 9 | With the registry down, every repo got a guessed link that 404s | Guard keyed on "the map is non-empty", which an empty feed defeats. | A repo with no known slug stays plain text. Fail closed. |
| 10 | "The thin horizontal lines mess the reading" | A decorative scanline background. | `background: none`. Decoration that crosses text is noise. |
| 11 | Times in UTC on one panel and local time on the next | The default timezone was set per dashboard, and inconsistently. | Set `timezone: browser` on every dashboard, and `GF_DATE_FORMATS_DEFAULT_TIMEZONE=browser`. "Today" is the UTC day, and the description says so. |
| 12 | A day-one chart with one category stuck at 0, although the operator could see the waiting | The rule classified the wait the operator meant (local checks) as work. | Replay a day of real data through a new classifier before shipping it, and ask "would the operator recognise this split?" |
| 13 | The "same" data meant different things on two sheets | Each sheet carried its own copy of the repo map and of the helpers. | Use one library, one registry and one generator. The page never carries hand-edited copies. |
| 14 | A pack file shown as one run-on paragraph; then, with its newlines kept, as markdown headings with `&#39;` printed literally | `page()` collapses newlines so the template literals stay compact. Kept newlines are worse: the panel's markdown pass ends the HTML block at the file's first blank line and renders the rest as markdown. | Show a file with `raw(text)`: it escapes the text and writes each newline as `&#10;`, which survives both. |
| 15 | Slot and activity charts read only "per hour", though the exporter writes every 5 minutes | The bucket was a round `1h`, not the source's cadence. And on the 14-day default range, Grafana widened even a 5-minute bucket to about 30 minutes to fit the pixels. | `interval` = the write cadence (`history(..., interval=)` has no default). The page default range drops to about 12 h; per-day and weekly charts pin `timeFrom: "14d"`. |
| 16 | In-flight lines whose title, topic and id started at a different column on every line | Variable text (title, topic) came first, and the fixed fields (lane, model, uptime) trailed it. | Fixed fields lead the line in `fx()` columns, and a small-set field (topic) gets a column padded to its longest value. Free text follows. |
| 17 | A task text cut off mid-sentence by the ellipsis, with no way to read the rest | The line carried a 110-character clip of text that never fits. | The task leaves the line and shows whole on hover (`item(..., tip)`). |
| 18 | Node names cut at half the line's width | The feed reused a title clipped to 48 characters to fit a Node Graph box. | The feed carries the full name beside the clipped one, and the sheet reads the full one. Never clip at the source for another view. |
| 19 | `(**held**)` with its asterisks in every node name | Plan rows are markdown, and the name was passed through as written. | The feed strips `**…**` emphasis where it reads the name. A lone `*` stays. |
| 20 | A traffic chart, "in above, out below", with no out side at all | `history()` floors every line chart at 0. That is right for a gauge, and it silently cuts away the negative half of a flow. `opened_closed()` drawn as lines had the same latent defect. | `history(..., signed=True)` drops the floor. Bars were never floored. |
| 21 | "Failed IPMI units: 2 — ACT" on every host page | `openipmi`/`ipmievd` come from the VM template and fail on every host with no BMC. The sheet classified one host's units without looking at the fleet. | Query a failure fleet-wide before tagging it. A failure every host shares is INFO, with the note "fails on every host". |
| 22 | "Collectors failing: pressure, conntrack — WARN, sheet lines are N/D" on a PVE node whose memory-stall line read fine | `node_scrape_collector_success == 0` means one file failed, not that the series are gone: the node lacks the irq-PSI and conntrack-stats files. | Map each producer to a series it must yield and test that series for presence. Failed with the series present = INFO "partial". Failed with the series gone = WARN. |
| 23 | "Fills in ~4811d 14h at the 24-h trend" | A 24-hour `deriv` on a disk that does not move, divided into the free space. | Cap the forecast at 30 days for a 24-hour window. Further out reads "not filling within 30 d". |
| 24 | (caught before shipping) A sheet keyed on `labels.__name__` from `count by (__name__)` | Whether a frame's labels carry `__name__` depends on the datasource and the query, so the key was never reliable. | `label_replace` the name into a plain label (`metric`). `sheet_harness.py` leaves `__name__` out, so a sheet that relies on it fails the dry run. |
| 25 | A wait column reading `415 h 21 m`, `9 h 52 m`, `2 h 13 m`: the digits never lined up | The duration was formatted per value: its width followed the number, and HTML collapsed any padding space. | `durCol(s)`: two units, each number padded to two places with a figure space (U+2007, not collapsed, a digit's width), the value right-aligned to 9 characters. |
| 26 | A lane graph whose nodes said `done` inside the circle, in the ring colour, and again in the legend; the name and topic hung under the circle and collided | Grafana's Node Graph draws circles only: mainstat inside, title and subtitle under it. | `flow()`: a rectangle per node with id, name and topic inside, and the state written once under it. Node Graph is not used for sitrep graphs. |
| 27 | A merge graph 31 rows tall and one node wide | The layered layout puts every node of a fan-out in one column: 31 PRs, each pointing at `main`, made 31 rows. | Chain the fan-out by the queue's own order (train link order, oldest first, longest wait first): one row per queue. |
| 28 | A `label_replace` chain that maps `topic="none"` and `topic=""` to one name failed with **422 `duplicate output timeseries`**, on the page only | Two input series became one label set at the output, which VictoriaMetrics refuses. The instant check of one series never showed it. | A renaming `label_replace` that can merge values always gets an outer aggregation: `sum by (topic) (label_replace(...))`. `sheet_harness.py` runs every history target as a range query, and fails on the 422. |
| 29 | A history chart of two sources (hook events + a server counter) with **whole weeks missing** | `sum(A) + sum(B)` is empty for any bucket where one side has no sample. | `(sum(A) or vector(0)) + (sum(B) or vector(0))`, on a history chart only. On a sheet an empty side stays N/D, never 0. |
| 30 | `sheet_harness.py` reported `0 failure(s)`, and the sheets in the collapsed drill-down rows had never run | It read only the top-level `d["panels"]`; a collapsed row keeps its panels in `row["panels"]`. | The harness walks the children of collapsed rows, and `--panel` finds them. |
| 31 | Carried original panels 6, 9 and 10 took the ids of new sheets 6, 9 and 10, and `finish()` passed | `finish()` checked ids and overlap at the top level only; Grafana renumbers a duplicate silently, and a link to it breaks. | `finish()` checks ids across the whole tree, and each collapsed row's grid on its own. `carry_panels()` renumbers what it carries (`id_offset`). |
| 32 | The harness printed `rare failures,  none` for `rare failures, <20 % of attempts > none`; the browser was right | Its tag stripper `<[^>]+>` ate a literal `<` up to the next `>`. | Strip real tags only, `</?[a-zA-Z][^>]*>`. |
| 33 | Every sheet failed "no SITREP line" once the page dropped the label | The check looked for the word, not the line. | The harness checks for `class="br"`; `brief_label=None` drops the word. |
| 34 | `TypeError: not enough arguments for format string` from a generator | `body_js` built as `r"""...""" % (json.dumps(names),)`, and the JS had a `%` (a modulo in a plural rule). Python 3.9 then rejected the f-string rewrite, a backslash inside `{}`. | `sheet(..., consts={"TN": names})` emits `const TN = <json>;`: no formatting of JS at all. Generators run on Python 3.9. |
| 35 | `render_check.py` got 401 `Invalid API key`, and finding out why took a long time | `GRAFANA_TOKEN` held the MCP gateway's token, not a Grafana service-account token. | Every script checks the token against the API first and says which kind it looks like (`glsa_` or not). |
| 36 | A twelve-sheet page could not be deployed by the agent at all: 140 KB of JSON as one tool-call argument | Each sheet embeds the renderer and the CSS. | `scripts/deploy.py` posts the file itself, so size no longer matters. `sheet()` also embeds the library without comments and indentation: a sheet is about a sixth smaller (20.8 → 17.5 KB on the example). |

## Not traps, but rulings

These needed the operator, so ask them. On a page with no operator in the loop (a background job), set
each one yourself, write it in the panel's (i) as "this page's ruling", and list every such ruling in the
hand-over, so the operator can overturn it in one reply:

- **What "today" means.** Here it is the UTC calendar day, whatever the display zone.
- **Which idle is intended.** Here budget and end-of-day are INFO; everything else is ACT.
- **The threshold behind each WARN and ACT.**
- **The page order.** It ranks the questions by what missing each one has cost.

A usage page (who uses a tool, how often) adds rulings of its own. Expect them, and record each in the (i):

- **One person under two logins.** Keep an alias map in the generator and name it in the (i); with no map,
  say a person with two logins counts twice.
- **What "active" means.** Which event kinds count: a connection with no call, yes or no.
- **An item idle on purpose.** A scheduled or on-demand item (a doctor-type check run once a week) is INFO
  when unused, not WARN.
- **"Current version" when the metric carries only content hashes.** The majority hash plus the date it was
  first seen, marked as a heuristic.
