---
name: scifi-wiki
description: Refactor a set of markdown documents (architecture notes, runbooks, ADRs) into a sci-fi wiki — one static Quarto site with a page per `##` section, chapter cards, a decision ledger, live PromQL charts and a SITREP briefing, derived from the sources and never hand-edited. Use when asked to turn docs into a browsable site, a wiki, a "sci-fi" / HUD / mission-control documentation portal, or to restructure long markdown files so each section stands alone as a page.
---

# Sci-fi wiki

A wiki here is a **rendering**, not a second copy. The markdown files stay the truth; `scripts/wiki.py` stages
them into a Quarto website, and nobody edits the staged pages. A change to a source file changes the site at the
next build.

The job has two halves, in this order:

1. **Refactor the markdown** so it reads as a wiki: every `##` section stands alone as a page.
2. **Render it**: config, lint, build, then look at the result.

Requirements: Python 3.9+ (stdlib only) and [Quarto](https://quarto.org) 1.4+ for `build`. Optional: Pillow and
a ComfyUI server for plates; a Prometheus-compatible API with CORS for live charts; Playwright to screenshot.

## 1. The wiki grammar

`wiki.py` reads each source with these rules. The refactoring is making the files obey them.

| Source | Becomes |
|---|---|
| the first `# ` line | the chapter title |
| the text before the first `## ` | the chapter's index page, above its cards |
| each `## ` section | one page, `NN-<slug>.html`; the slug drops numbering, `(…)` and markup |
| the first sentence of a section | that page's card text |
| a link to another source file | a link to that file's chapter |
| a link to `NNNN-*.md` in the ledger dir | `decisions.html#adr-NNNN` |
| any other relative link | `source_url` + the path (the file on the forge) |
| a ```` ```mermaid ```` block | a diagram, themed to the site |

Refactor toward these rules:

- **One topic per `##`.** A section that answers two questions becomes two sections. Under about 250 lines a page
  reads in one sitting; `lint` warns above that.
- **Open every section with the claim.** The first sentence is the card a reader picks from, so it states what is
  true ("The reactor feeds two buses, and a bus never carries more than 80 %"), not what follows ("This section
  describes…").
- **Facts go in text, tables and Mermaid, never in pictures.** Plates are mood art. The image model garbles
  text, and a picture cannot be grepped or diffed.
- **Number sections when order matters** (`## 3. The merge line`). The page name ignores the number, so
  renumbering does not break a link.
- **Keep headings stable.** `wiki.json` maps plates and charts by section slug. Renaming a heading is a lint
  error until the map follows it.
- **Link, don't restate.** Link to a decision record or another chapter rather than copying its text. The
  ledger collects every record the chapters cite.
- **End with where it stands** (a "Where it stands" section): what is done and what is open. Readers look for it.

Do not invent content while refactoring. Move, split, retitle and tighten. A gap you find goes to the
author as a question, not into the page as a guess.

## 2. The config: `wiki.json`

It lives in the site directory, which is the Quarto project. `root` is where the source paths start, relative to
the site directory.

```json
{
  "title": "HELIX // ship systems", "subtitle": "…", "root": "..",
  "source_url": "https://github.com/OWNER/REPO/blob/main/", "repo_url": "https://github.com/OWNER/REPO",
  "plate": "hero",
  "chapters": [
    {"key": "systems", "file": "docs/ship-systems.md", "nav": "Ship systems", "plate": "systems",
     "blurb": "…card text; defaults to the intro's first sentence…", "strict": false,
     "sections": {"life-support": {"plate": "air", "charts": ["targets"]}}}
  ],
  "ledger": {"dir": "docs/adr", "index": "docs/adr/README.md", "always": ["0007"], "all": false},
  "metrics": {"url": "http://prometheus:9090", "name": "Prometheus"},
  "charts": {"targets": {"title": "Targets up, by job", "kind": "line", "range": "1d", "step": "15m",
                         "label": "job", "q": "sum by (job)(up)", "panel": "https://grafana/d/uid?viewPanel=2"}},
  "briefing": [{"label": "Targets down", "q": "count(up == 0) or vector(0)", "rule": "ok_if_le:0"}],
  "home_charts": ["targets"],
  "pages": [{"href": "map.html", "title": "Goal map", "text": "…", "art": "hero"}]
}
```

- **A section without an entry** in `sections` gets the chapter's plate and no charts. `"strict": true` makes
  an unmapped section a lint error, so every new section gets its own art.
- **`charts`.** `kind` is `line`, `stack` or `bars`. Also: `range` and `step` (`15m`, `1h`, `1d`, `1w`), `label`
  (which label names a series), `order` (a comma list that pins series order), `ref` plus `refname` (a dashed
  threshold line), `unit`, and `panel` (a link to the dashboard panel the chart mirrors). Charts are drawn by
  [uPlot](https://github.com/leeoniya/uPlot) 1.6.32, vendored under `assets/vendor/` with its MIT licence and
  checksums. It is the same engine as Grafana's time-series panels: 22 KB gzipped, and it stays fast at 100k
  points. A reader can zoom (drag across a chart, Ctrl+wheel or pinch), reset (double-click), hide a series
  (click its legend entry), read every series at a point (the crosshair tooltip shows raw values, even on a stack)
  and open the numbers as a table. The marks follow the dataviz method: at most four series, then "other";
  2 px lines; direct end labels plus a legend.
- **`briefing`.** This is the SITREP sheet, in the same grammar as `grafana-sitrep`. It opens with a verdict
  line, followed by one contents line for each number: `label ..... value TAG`. The tags are `OK` (fine), `WARN`
  (look), `ACT` (someone must act; it blinks), `INFO` (idle on purpose) and `N/D` (no data). An empty query result
  is `N/D`, never 0. Write `or vector(0)` only where zero is true. The verdict names the move: it is the worst
  line's `move` text, or `briefing_ok` when every line is fine. Each line takes:

  | Field | Meaning |
  |---|---|
  | `q` | the query |
  | `of` | a total, shown as ` / total` |
  | `rule` | `ok_if_ge:N`, `ok_if_le:N`, `warn_if_lt:N`, `act_if_ge:N,warn_if_ge:M` or `info` |
  | `steps` | sitrep's thresholds, e.g. `[[null,"ok"],[5,"warn"],[10,"bad"]]` |
  | `fmt` | `int`, `pct`, `bytes` or `dur` |
  | `unit` | appended to the value |
  | `note` | a dim line under the contents line |
  | `names` | a query whose series names are listed under the line, e.g. the firing alerts |

  An entry `{"head": "ALARMS"}` is a sub-head. `briefing_title` names the sheet.
- **`pages`.** These are hand-made `.qmd` pages that live in the site directory and get a card and a nav entry.
  Put their scripts under `resources`.

`wiki.py scaffold docs/*.md` prints a first `wiki.json`, with a chapter for each file and an entry for each
section.

## 3. The procedure

```bash
S=<this skill's directory>
python3 $S/scripts/wiki.py init site/                  # theme, fonts, starter wiki.json, .gitignore
python3 $S/scripts/wiki.py scaffold doc/a.md doc/b.md  # paste into site/wiki.json, then edit
python3 $S/scripts/wiki.py lint  site/wiki.json        # the grammar, as errors and warnings
python3 $S/scripts/wiki.py build site/wiki.json        # lint + stage + quarto render -> site/_site/
python3 $S/scripts/wiki.py check site/wiki.json        # every chart/briefing query returns a series
```

1. **Inventory.** List the documents and the questions a reader brings to them. One chapter per file is the
   default. Merge two files only if they answer the same question.
2. **Refactor** each file to §1. Show the author the diff of the sources; the site needs no review of its own.
3. **Scaffold and edit `wiki.json`.** Choose plates, attach charts only where a number makes the section's
   claim, and write the briefing lines so the first is the one that would hurt most to miss.
4. **Lint until it has no errors.** Treat each warning as a refactoring hint, not noise.
5. **Build and look at it.** Serve `site/_site/` (`python3 -m http.server -d site/_site`) and screenshot the
   home page, one chapter index, one long page and the ledger. Check four things:
   - card text that reads as a sentence;
   - no Mermaid diagram wider than the page;
   - charts that draw, or say "unreachable" when the endpoint is down;
   - no console errors.
6. **Plates (optional).** Add a scene for each plate name to `wiki.json` under `"plates": {"prompts": {...}}`,
   then run `python3 $S/scripts/plates.py site/wiki.json --comfy http://HOST:8188`. Until a plate exists, the page
   shows a starfield void.
7. **Publish.** `site/_site/` is plain static files. Build it in CI from the sources so that the site cannot drift
   from them. Commit the theme, `wiki.json`, `art/` and any hand-made pages. Never commit the staged `.qmd` files:
   `init` writes a `.gitignore` that excludes them.

## 4. Live data, honestly

The charts and briefing run their PromQL from the **reader's browser**, so the site stays static:

- The metrics API must answer with `Access-Control-Allow-Origin`. VictoriaMetrics does this by default.
  Prometheus needs a proxy that adds the header.
- A reader who cannot reach the endpoint sees "metrics endpoint unreachable", never a blank or a zero.
- The briefing's verdict counts only the lines it could read. With none read, it says NO LINK.
- Embedding Grafana is not needed. Each chart can link to the panel it mirrors (`panel`).

Do not point a public site at a private metrics endpoint. The query text is in the page source.

## 5. Relation to grafana-sitrep

The two plugins share one reading grammar and one set of tag colours, so an operator reads them the same way:

| | `grafana-sitrep` | `scifi-wiki` |
|---|---|---|
| Where it renders | inside Grafana (Business Text panels) | a static site: no server, no Grafana |
| What it is for | the daily status page: is it going well, whose move is it | the system explained, with its numbers live beside the text |
| Sheet | `brief()` + `ln()` + `sub()`, from `briefing_lib.js` | `briefing` in `wiki.json`: same verdict line, contents lines, tags and N/D rule |
| History charts | Grafana's time-series panels (uPlot) | uPlot 1.6.32 in the page, with the same drag-zoom feel |
| Graph views | `flow()`: rows of boxes | Mermaid blocks in the markdown |

If the reader has Grafana and opens the page daily, use `grafana-sitrep`. If the page has to work without
Grafana, or explains how the system works, use `scifi-wiki`. Link a wiki chart to its Grafana panel with `panel`.

## 6. Theme

The theme is dark and uses three fonts: Orbitron for headings, Exo 2 for body text and Share Tech Mono for HUD
text. All three are vendored under the SIL OFL, so a page makes no third-party request. The corners are cut, a
faint deck grid and scanlines sit in the background, and the series colours were validated for colour-vision
deficiency on the deck colour. To restyle, edit `theme/wiki.scss` (Bootstrap variables) and `assets/wiki.css`
(the components) in your site directory. `init` never overwrites them.
