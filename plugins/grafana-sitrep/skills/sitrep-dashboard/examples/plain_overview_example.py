#!/usr/bin/env python3
"""Worked example: a FULL REDRAW of a usage page into one plain-language sheet for readers outside the team (HR,
management), read from EVENT telemetry (one sample of value 1 per event).

    python3 plain_overview_example.py plain_overview_orig.json new.json
    python3 ../scripts/sheet_harness.py new.json --fixture plain_overview_fixture.json
    python3 ../scripts/sheet_harness.py new.json --empty

What it shows:
- no state tags (every line `····`), no system names, whole words with correct plurals, grouped big numbers;
- the verdict line with no "SITREP" label (`brief_label=None`);
- generator data passed in through `consts`, never by formatting the JS;
- a column header that shares its widths with the rows (`cols()`);
- the coverage map of a full redraw: every original panel mapped, refused when one is not, and the table printed
  for the hand-over; then the parity lint.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sitrep  # noqa: E402

VM = {"type": "prometheus", "uid": "vm"}
EV = "ai_tool_event"
# What each event kind means, in the reader's words. A kind missing here shows as itself, escaped.
KINDS = {"search": "questions to company systems instead of a manual search", "edit": "changes drafted by the tool"}

src = json.loads(Path(sys.argv[1]).read_text())
# The original is what Grafana shows: export.py writes it; a copy written by hand is checked before anything else.
sitrep.expect_original(src, panels=4, queries=3, ends={(2, "A"): "count_over_time(ai_tool_event[14d]))"})
panels = [sitrep.row(100, "Who uses AI tools, and how often?", 0)]
panels.append(sitrep.sheet(
    1, "AI tools — the last 14 days",
    "**People** = distinct logins with at least one event in the last 14 days. **Regular** = used on 7 or more of "
    "those 14 days (counted per calendar day, UTC). **What they did** = events by kind, over the same 14 days. "
    "Source: the `ai_tool_event` telemetry, one sample per event. One person with two logins counts twice: the alias "
    "map is empty on this page. CANNOT COUNT: team headcount is not in the telemetry, so there is no \"% of the team\".",
    {"h": 12, "w": 10, "x": 0, "y": 1},
    [sitrep.q("A", f"count(count by (login) (count_over_time({EV}[14d])))", VM),
     # active days per person: one 1 per day with any event, summed over 14 one-day steps
     sitrep.q("B", f"sum by (login) (count_over_time((count by (login) (count_over_time({EV}[1d])) > 0)[14d:1d]))", VM),
     sitrep.q("C", f"sum by (kind) (count_over_time({EV}[14d]))", VM)],
    r"""
const KN = new Map(Object.entries(KINDS));  // a Map: a kind named `constructor` must not find Object.prototype
const people = one('A'), days = rows('B'), kinds = rows('C').sort((x, y) => y.value - x.value);
const regular = days.filter((r) => r.value >= 7).length;
const P = (n) => `${int(n)} ${plural(n, ['person', 'people'])}`;
const T = cols([[8, 'times', 'r'], [0, 'what was done']]);
const lines = [
  sub('people'),
  ln('used an AI tool at least once', people == null ? '—' : P(people), people == null ? 'nd' : 'idle'),
  ln('used it on 7 days or more', days.length ? P(regular) : '—', days.length ? 'idle' : 'nd'),
  sub('what they did'),
  kinds.length ? T.hdr + kinds.slice(0, 5).map((r) => item(T.row([int(r.value), esc(KN.get(r.labels.kind) || r.labels.kind)]))).join('')
    : ln('events', '—', 'nd'),
];
const verdict = people == null ? 'No usage data for the last 14 days: the telemetry is not arriving.'
  : `${P(people)} used AI tools in the last 14 days; ${P(regular)} on 7 days or more.`;
const html = page('01', 'AI tools', brief(verdict) + lines.join('') + foot('Last 14 days. Team size is not counted here, so there is no share of the team.'));
""",
    ds=VM, consts={"KINDS": KINDS}, brief_label=None,
))
panels.append(sitrep.history(
    2, "People who used an AI tool — per day",
    "Distinct logins with at least one event, per UTC day.",
    {"h": 12, "w": 14, "x": 10, "y": 1},
    [sitrep.q("A", f"count(count by (login) (count_over_time({EV}[$__interval])))", VM, "people", instant=False)],
    interval="1d", time_from="30d", bars=True, stack=False,
))

src["panels"] = panels
# Full redraw: every original panel is accounted for, or the generator stops.
print(sitrep.coverage(json.loads(Path(sys.argv[1]).read_text())["panels"], {
    1: 1, 2: 1, 3: 2, 4: "covered-by:1",  # the "how to read" text moved into the sheet's words and its (i)
}, panels, questions={1: "how many people use it?", 2: "what do they use it for?", 3: "is use growing?",
                      4: "what does a kind mean?"}))
for w in sitrep.parity(json.loads(Path(sys.argv[1]).read_text())["panels"], panels):
    print("parity:", w)
Path(sys.argv[2]).write_text(json.dumps(sitrep.finish(src, time_range="30d"), indent=1, ensure_ascii=False) + "\n")
