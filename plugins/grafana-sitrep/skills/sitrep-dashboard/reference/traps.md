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
| 5 | `node N39323102473` on the sheet | The machine id was shown as the label. | The title is the label and links to the work. The id moves to the end of the line, dimmed, and links to its file. |
| 6 | A link that opened inside the dashboard's own tab | Grafana's HTML sanitizer strips `target`. | The `afterRender` hook puts back `target=_blank` and `rel=noopener`. |
| 7 | `constructor#5` became a link to `https://github.com/function Object()...` | The repo map was a plain object, so the lookup walked into `Object.prototype`. | Use a `Map`. |
| 8 | "don't" became `don&` + a link to **issue #39** + `;t` | Escaping turned `'` into `&#39;`, and the linkifier then matched `#39`. | Escape first, then link, with `&` in the lookbehind. |
| 9 | With the registry down, every repo got a guessed link that 404s | Guard keyed on "the map is non-empty", which an empty feed defeats. | A repo with no known slug stays plain text. Fail closed. |
| 10 | "The thin horizontal lines mess the reading" | A decorative scanline background. | `background: none`. Decoration that crosses text is noise. |
| 11 | Times in UTC on one panel and local time on the next | The default timezone was set per dashboard, and inconsistently. | Set `timezone: browser` on every dashboard, and `GF_DATE_FORMATS_DEFAULT_TIMEZONE=browser`. "Today" is the UTC day, and the description says so. |
| 12 | A day-one chart with one category stuck at 0, although the operator could see the waiting | The rule classified the wait the operator meant (local checks) as work. | Replay a day of real data through a new classifier before shipping it, and ask "would the operator recognise this split?" |
| 13 | The "same" data meant different things on two sheets | Each sheet carried its own copy of the repo map and of the helpers. | Use one library, one registry and one generator. The page never carries hand-edited copies. |
| 14 | A pack file shown as one run-on paragraph; then, with its newlines kept, as markdown headings with `&#39;` printed literally | `page()` collapses newlines so the template literals stay compact. Kept newlines are worse: the panel's markdown pass ends the HTML block at the file's first blank line and renders the rest as markdown. | Show a file with `raw(text)`: it escapes the text and writes each newline as `&#10;`, which survives both. |

## Not traps, but rulings

These needed the operator, so ask them:

- **What "today" means.** Here it is the UTC calendar day, whatever the display zone.
- **Which idle is intended.** Here budget and end-of-day are INFO; everything else is ACT.
- **The threshold behind each WARN and ACT.**
- **The page order.** It ranks the questions by what missing each one has cost.
