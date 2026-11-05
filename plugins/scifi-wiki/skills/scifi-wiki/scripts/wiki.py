#!/usr/bin/env python3
"""Render a set of markdown documents as a sci-fi wiki: one Quarto website, derived, never hand-edited.

    wiki.py init     SITE_DIR                 copy the theme into SITE_DIR and write a starter wiki.json
    wiki.py scaffold DOC.md [DOC.md ...]      print a wiki.json for these documents (chapters + sections)
    wiki.py lint     SITE_DIR/wiki.json       check the sources against the wiki grammar (exit 1 on an error)
    wiki.py stage    SITE_DIR/wiki.json       write the .qmd pages, _quarto.yml and _sidebar.yml
    wiki.py build    SITE_DIR/wiki.json       lint + stage + `quarto render` -> SITE_DIR/_site/
    wiki.py check    SITE_DIR/wiki.json       run every chart and briefing query once (needs the metrics URL)

The grammar: each source file has one `# ` title and an intro; each `## ` section is one page; the first sentence of
a section is its card text. Facts live in the markdown (tables, Mermaid); plates are mood art and say nothing.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"
MANIFEST = ".wiki-staged"   # every file the last stage wrote; clean deletes these and nothing else
SECS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
_ADR_FILE = re.compile(r"^(\d{4})-[\w.-]+\.md$")
_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")   # (bang, text, target): a link or an image
_FENCE = re.compile(r"^\s*(```|~~~)")


class WikiError(Exception):
    pass


# --- reading the sources -------------------------------------------------------------------------------------------

def slugify(text: str) -> str:
    """'3. The merge line (D4)' -> 'the-merge-line': numbering, parentheticals and markup dropped, 40 chars max."""
    text = re.sub(r"\s*\([^)]*\)", "", re.sub(r"^\d+\.\s*", "", text))
    text = re.sub(r"[`*_]", "", text)
    return re.sub(r"[\W_]+", "-", text.lower()).strip("-")[:40].strip("-")


def gh_anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: '3. The `x` line' -> '3-the-x-line'."""
    text = re.sub(r"[`*]", "", heading).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def pandoc_id(heading: str) -> str:
    """The id Quarto (pandoc) gives a heading: like GitHub's, but leading non-letters dropped."""
    text = re.sub(r"[`*]", "", heading).strip().lower()
    text = re.sub(r"\s+", "-", re.sub(r"[^\w\s.-]", "", text))
    return re.sub(r"^[^a-z\u00c0-\uffff]+", "", text) or "section"


def split_sections(md: str) -> tuple[str, str, list[tuple[str, str]]]:
    """-> (title, intro, [(heading, body)]), split on `## ` outside code fences. A second `# ` stays in the body."""
    fence, title = False, ""
    intro: list[str] = []
    sections: list[list] = []
    for line in md.splitlines():
        if _FENCE.match(line):
            fence = not fence
        if not fence and line.startswith("# ") and not title and not sections:
            title = line[2:].strip()
        elif not fence and line.startswith("## "):
            sections.append([line[3:].strip(), []])
        elif sections:
            sections[-1][1].append(line)
        else:
            intro.append(line)
    return title, "\n".join(intro).strip(), [(h, "\n".join(b).strip()) for h, b in sections]


def first_sentence(body: str) -> str:
    """The card text: the first sentence of the first prose paragraph, markup stripped, 180 chars max."""
    for para in body.split("\n\n"):
        p = para.strip()
        if p and not p.startswith(("```", "~~~", "|", "-", "*", ">", "#", "<", ":::", "!")) and not re.match(r"\d+\.", p):
            p = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", " ".join(p.split()))
            p = re.sub(r"[*`]", "", p)
            return (p.split(". ")[0].rstrip(".:") + ".")[:180]
    return ""


def clean_heading(heading: str) -> str:
    return re.sub(r"^\d+\.\s*", "", heading).strip()


# --- the config ----------------------------------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["_site"] = path.resolve().parent
    cfg["_root"] = (cfg["_site"] / cfg.get("root", ".")).resolve()
    keys = [c.get("key") for c in cfg.get("chapters", [])]
    if not keys:
        raise WikiError("wiki.json: no chapters")
    for c in cfg["chapters"]:
        for req in ("key", "file"):
            if not c.get(req):
                raise WikiError(f"wiki.json: a chapter has no {req!r}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", c["key"]):
            raise WikiError(f"wiki.json: chapter key {c['key']!r} must be lowercase letters, digits and dashes")
    if len(set(keys)) != len(keys):
        raise WikiError("wiki.json: two chapters share a key")
    reserved = {"assets", "art", "theme", "_site", "index", "telemetry", "decisions"}
    if reserved & set(keys):
        raise WikiError(f"wiki.json: chapter key(s) {sorted(reserved & set(keys))} are reserved")
    charts = cfg.get("charts", {})
    for c in cfg["chapters"]:
        for slug, sec in (c.get("sections") or {}).items():
            for cid in sec.get("charts", []):
                if cid not in charts:
                    raise WikiError(f"wiki.json: {c['key']}/{slug} uses chart {cid!r}, which `charts` does not define")
    for cid in cfg.get("home_charts", []):
        if cid not in charts:
            raise WikiError(f"wiki.json: home_charts names {cid!r}, which `charts` does not define")
    return cfg


def read_source(cfg: dict, chapter: dict) -> str:
    p = cfg["_root"] / chapter["file"]
    if not p.is_file():
        raise WikiError(f"{chapter['file']}: not found under root {cfg['_root']}")
    return p.read_text(encoding="utf-8")


# --- lint: the refactoring checklist, made executable -------------------------------------------------------------

def lint_markdown(md: str, rel: str) -> list[tuple[str, str]]:
    """-> [(level, message)] for one source; level is 'error' or 'warn'."""
    out: list[tuple[str, str]] = []
    fence, h1, line_no = False, 0, 0
    for line_no, line in enumerate(md.splitlines(), 1):
        if _FENCE.match(line):
            fence = not fence
            continue
        if not fence and line.startswith("# "):
            h1 += 1
    if fence:
        out.append(("error", f"{rel}: a code fence is never closed; every section after it would vanish"))
    if h1 == 0:
        out.append(("error", f"{rel}: no `# ` title; the chapter needs one"))
    elif h1 > 1:
        out.append(("warn", f"{rel}: {h1} `# ` headings; only the first is the title, the rest render as body text"))
    title, intro, sections = split_sections(md)
    if not sections:
        out.append(("error", f"{rel}: no `## ` sections; each `## ` becomes one page"))
    if not intro.strip():
        out.append(("warn", f"{rel}: no intro under the title; the chapter index page opens with it"))
    seen: dict[str, str] = {}
    for heading, body in sections:
        slug = slugify(heading)
        if not slug:
            out.append(("error", f"{rel}: `## {heading}` has no letters to name its page"))
            continue
        if slug in seen:
            out.append(("error", f"{rel}: `## {heading}` and `## {seen[slug]}` make the same page name {slug!r}"))
        seen[slug] = heading
        if not first_sentence(body):
            out.append(("warn", f"{rel}: `## {heading}` does not open with a prose sentence; its card will be blank"))
        n = body.count("\n") + 1
        if n > 250:
            out.append(("warn", f"{rel}: `## {heading}` is {n} lines; split it, a page reads best under ~250"))
        if re.search(r"^#{5,} ", body, re.M):
            out.append(("warn", f"{rel}: `## {heading}` nests below `####`; the page's contents list stops at ###"))
    return out


def lint(cfg: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        site = Site(cfg)
    except WikiError as e:
        return [("error", str(e))]
    for chapter in cfg["chapters"]:
        rel = chapter["file"]
        try:
            md = read_source(cfg, chapter)
        except WikiError as e:
            out.append(("error", str(e)))
            continue
        out += lint_markdown(md, rel)
        _, _, sections = split_sections(md)
        slugs = {slugify(h) for h, _ in sections}
        for slug in chapter.get("sections") or {}:
            if slug not in slugs:
                out.append(("error", f"{rel}: wiki.json maps section {slug!r}, which the file no longer has "
                                     f"(renamed? it has: {', '.join(sorted(slugs))})"))
        if chapter.get("strict"):
            for slug in sorted(slugs - set(chapter.get("sections") or {})):
                out.append(("error", f"{rel}: section {slug!r} is not in wiki.json and the chapter is strict"))
        src_dir = os.path.dirname(rel)
        fence = False
        for line in md.splitlines():
            if _FENCE.match(line):
                fence = not fence
            if fence:
                continue
            for bang, _, target in _LINK.findall(line):
                if target.startswith(("http://", "https://", "#", "mailto:", "/")):
                    continue
                path = target.partition("#")[0]
                if path and not (cfg["_root"] / src_dir / path).exists():
                    out.append(("warn" if bang else "error" if not cfg.get("source_url") else "warn",
                                f"{rel}: {'image' if bang else 'link'} {target!r} points at nothing under root"))
                elif path and not bang and site.rewrite_link(target, src_dir, 1, rel) == target:
                    out.append(("error", f"{rel}: link {target!r} is not a chapter or a decision record, and wiki.json "
                                         "has no source_url, so it would break on the site; set source_url"))
    plates = {p.stem for p in (cfg["_site"] / "art").glob("*.webp")} if (cfg["_site"] / "art").is_dir() else set()
    if plates:
        for name in sorted(wanted_plates(cfg) - plates):
            out.append(("warn", f"plate {name!r} is named in wiki.json but art/{name}.webp is missing; "
                                "the page shows the void pattern instead"))
    return out


# --- writing the pages ----------------------------------------------------------------------------------------------

def raw(block: str) -> str:
    return "```{=html}\n" + block + "\n```"


def front(title: str, subtitle: str = "", extra: str = "") -> str:
    out = f"---\ntitle: {json.dumps(title)}\n"
    if subtitle:
        out += f"subtitle: {json.dumps(subtitle)}\n"
    return out + extra + "---\n\n"


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


class Site:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.site: Path = cfg["_site"]
        self.root: Path = cfg["_root"]
        self.chapter_files = {c["file"]: c["key"] for c in cfg["chapters"]}
        led = cfg.get("ledger") or {}
        self.adr_dir = os.path.normpath(led["dir"]) if led.get("dir") else None
        self.plates = {p.stem for p in (self.site / "art").glob("*.webp")} if (self.site / "art").is_dir() else set()
        self.metrics = (cfg.get("metrics") or {}).get("url", "")
        self.written: list[str] = []
        # (source file, GitHub anchor) -> (chapter key, page name, id on that page or None)
        self.anchors: dict[tuple[str, str], tuple[str, str, str | None]] = {}
        for c in cfg["chapters"]:
            p = self.root / c["file"]
            if not p.is_file():
                continue
            _, _, sections = split_sections(p.read_text(encoding="utf-8"))
            for i, (heading, body) in enumerate(sections, 1):
                page = f"{i:02d}-{slugify(heading)}"
                self.anchors.setdefault((c["file"], gh_anchor(heading)), (c["key"], page, None))
                fence = False
                for line in body.splitlines():
                    if _FENCE.match(line):
                        fence = not fence
                    m = None if fence else re.match(r"^#{3,6} (.+?)\s*(\{[^}]*\})?\s*$", line)
                    if m:
                        self.anchors.setdefault((c["file"], gh_anchor(m.group(1))), (c["key"], page, pandoc_id(m.group(1))))

    def write(self, rel: str, data) -> None:
        """Write one staged file. A file already there was not written by wiki.py (clean removed those): refuse."""
        p = self.site / rel
        if p.exists():
            raise WikiError(f"{p} exists and wiki.py did not write it; move it, or rename the chapter key / page")
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, Path):
            shutil.copyfile(data, p)
        else:
            p.write_text(data, encoding="utf-8")
        self.written.append(rel)

    # links ---------------------------------------------------------------------
    def rewrite_link(self, target: str, src_dir: str, depth: int, src_file: str = "") -> str:
        """A repo-relative link -> the wiki page (and section) that renders it, else the source host, else unchanged."""
        if target.startswith(("http://", "https://", "mailto:", "/")):
            return target
        path, _, anchor = target.partition("#")
        up = "../" * depth
        resolved = os.path.normpath(os.path.join(src_dir, path)) if path else src_file
        if not resolved:
            return target
        m = _ADR_FILE.match(os.path.basename(path))
        if m and self.adr_dir and os.path.dirname(resolved) == self.adr_dir:
            return f"{up}decisions.html#adr-{m.group(1)}"
        if resolved in self.chapter_files:
            hit = self.anchors.get((resolved, anchor)) if anchor else None
            if hit:
                key, page, inner = hit
                return f"{up}{key}/{page}.html" + (f"#{inner}" if inner else "")
            return target if not path else f"{up}{self.chapter_files[resolved]}/index.html"
        base = self.cfg.get("source_url")
        if base and path:
            return f"{base.rstrip('/')}/{resolved}" + (f"#{anchor}" if anchor else "")
        return target

    def image(self, target: str, src_dir: str, depth: int) -> str:
        """A relative image -> a copy under media/ (the same tree as under root), so the site carries it."""
        if target.startswith(("http://", "https://", "data:", "/")):
            return target
        resolved = os.path.normpath(os.path.join(src_dir, target.partition("#")[0]))
        src = self.root / resolved
        if resolved.startswith("..") or not src.is_file():
            return target
        rel = f"media/{resolved}"
        if rel not in self.written:
            self.write(rel, src)
        return "../" * depth + rel

    def rewrite(self, md: str, src_dir: str, depth: int, src_file: str = "") -> str:
        def sub(m: re.Match) -> str:
            bang, text, target = m.groups()
            new = self.image(target, src_dir, depth) if bang else self.rewrite_link(target, src_dir, depth, src_file)
            return f"{bang}[{text}]({new})"
        out, fence = [], False
        for line in md.split("\n"):
            if _FENCE.match(line):
                fence = not fence
            out.append(line if fence else _LINK.sub(sub, line))
        return re.sub(r"^(\s*)```mermaid\s*$", r"\1```{mermaid}", "\n".join(out), flags=re.M)

    # pieces --------------------------------------------------------------------
    def plate(self, name: str | None, depth: int, hero: bool = False) -> str:
        cls = "plate plate-hero" if hero else "plate"
        if name and name in self.plates:
            return raw(f'<figure class="{cls}"><img src="{"../" * depth}art/{esc(name)}.webp" alt="" loading="lazy"></figure>')
        return raw(f'<figure class="{cls} plate-void" aria-hidden="true"><span></span></figure>')

    def card(self, href: str, no: str, title: str, text: str, art: str | None, depth: int) -> str:
        img = (f'<img src="{"../" * depth}art/{esc(art)}.webp" alt="" loading="lazy">' if art and art in self.plates
               else '<span class="card-void" aria-hidden="true"></span>')
        return (f'<a class="card" href="{esc(href)}">{img}<span class="card-no">{esc(no)}</span>'
                f'<span class="card-title">{esc(title)}</span><span class="card-text">{esc(text)}</span></a>')

    def chart_html(self, cid: str, compact: bool = False) -> str:
        c = self.cfg["charts"][cid]
        attrs = {"data-chart": cid, "data-vm": self.metrics, "data-q": c["q"], "data-kind": c.get("kind", "line"),
                 "data-range": c.get("range", "7d"), "data-step": c.get("step", "1h"), "data-title": c["title"]}
        for k in ("label", "ref", "refname", "unit", "order", "panel"):
            if k in c:
                attrs[f"data-{k}"] = str(c[k])
        a = " ".join(f'{k}="{esc(v)}"' for k, v in attrs.items())
        return f'<figure class="fc{" fc-compact" if compact else ""}" {a}></figure>'

    def briefing_html(self) -> str:
        """The SITREP sheet, in grafana-sitrep's grammar: a verdict line that names the move, then one contents line
        per number (`label ..... value TAG`), `{"head": ...}` entries as sub-heads, `note` as a dim line under."""
        rows = []
        for b in self.cfg.get("briefing", []):
            if "head" in b and "q" not in b:
                rows.append(f'<div class="sh">▸ {esc(b["head"])}</div>')
                continue
            attrs = " ".join(f'data-{k}="{esc(json.dumps(v) if isinstance(v, (list, dict)) else v)}"'
                             for k, v in b.items() if k != "note")
            rows.append(f'<div class="ln s-idle" {attrs}><span class="lb">{esc(b["label"])}</span><span class="dt"></span>'
                        f'<span class="v">···</span><span class="tg">····</span></div>')
            if b.get("note"):
                rows.append(f'<div class="nt">{esc(b["note"])}</div>')
        label = self.cfg.get("briefing_label", "SITREP")
        bl = f'<span class="bl">{esc(label)}</span> ' if label else ""
        ok = f' data-all-ok="{esc(self.cfg["briefing_ok"])}"' if self.cfg.get("briefing_ok") else ""
        return (f'<section class="briefing sheet" data-vm="{esc(self.metrics)}"{ok}><div class="hd"><span class="no">00</span>'
                f'<span class="ti">{esc(self.cfg.get("briefing_title", "Status"))}</span><span class="brief-clock"></span></div>'
                f'<div class="br s-idle">{bl}<span class="bv">ACQUIRING TELEMETRY…</span></div>'
                + "".join(rows) + "</section>")

    # pages ---------------------------------------------------------------------
    def stage_chapter(self, chapter: dict, sidebar: list) -> dict:
        key, rel = chapter["key"], chapter["file"]
        title, intro, sections = split_sections(read_source(self.cfg, chapter))
        title = title or key
        mapping = chapter.get("sections") or {}
        src_dir = os.path.dirname(rel)
        cards, pages = [], []
        for i, (heading, body) in enumerate(sections, 1):
            slug = slugify(heading)
            sec = mapping.get(slug, {})
            name = f"{i:02d}-{slug}"
            clean = clean_heading(heading)
            art = sec.get("plate", chapter.get("plate"))
            page = front(clean, title) + self.plate(art, 1) + "\n\n" + self.rewrite(body, src_dir, 1, rel) + "\n"
            if sec.get("charts"):
                page += ("\n## Live telemetry {.telemetry-head}\n\n"
                         + raw("\n".join(self.chart_html(c) for c in sec["charts"])) + "\n")
            self.write(f"{key}/{name}.qmd", page)
            pages.append({"href": f"{key}/{name}.qmd", "text": f"{i:02d} · {clean}"})
            cards.append(self.card(f"{name}.html", f"{i:02d}", clean, first_sentence(body), art, 1))
        index = front(title, chapter.get("subtitle", f"Rendered from {rel}"))
        index += self.plate(chapter.get("plate"), 1, hero=True) + "\n\n" + self.rewrite(intro, src_dir, 1, rel) + "\n\n"
        index += raw('<div class="cards">' + "".join(cards) + "</div>") + "\n"
        self.write(f"{key}/index.qmd", index)
        sidebar.append({"section": chapter.get("nav", title), "href": f"{key}/index.qmd", "contents": pages})
        return {"href": f"{key}/index.html", "title": title, "n": len(sections), "art": chapter.get("plate"),
                "text": chapter.get("blurb") or first_sentence(intro)}

    def stage_ledger(self) -> int:
        """decisions.qmd: every decision record the chapters cite (plus `always`), newest first."""
        led = self.cfg["ledger"]
        adr_dir = self.root / led["dir"]
        cited = set(str(n) for n in led.get("always", []))
        rel_dir = re.escape(os.path.basename(os.path.normpath(led["dir"])))
        for c in self.cfg["chapters"]:
            cited |= set(re.findall(rf"{rel_dir}/(\d{{4}})-", read_source(self.cfg, c)))
        if led.get("all"):
            cited |= {m.group(1) for p in adr_dir.glob("*.md") if (m := _ADR_FILE.match(p.name))}
        index_text = (self.root / led["index"]).read_text(encoding="utf-8") if led.get("index") else ""
        rows = []
        for num in sorted(cited, reverse=True):
            files = sorted(adr_dir.glob(f"{num}-*.md"))
            if not files:
                continue
            text = files[0].read_text(encoding="utf-8")
            head = re.sub(r"^\d{4}\.?\s*[—–:-]?\s*", "", text.splitlines()[0].lstrip("# ").strip())
            status_line = next((ln for ln in text.splitlines() if "Status:" in ln or "status:" in ln), "")
            m = re.search(r"tatus:\**\s*\**\s*([A-Za-z-]+)", status_line)
            status = (m.group(1) if m else "Unknown").capitalize()
            date = re.search(r"\d{4}-\d{2}-\d{2}", status_line) or re.search(r"\d{4}-\d{2}-\d{2}", text)
            row = re.search(rf"^\|\s*\[{num}\]\([^)]+\)\s*\|\s*(.+?)\s*\|\s*$", index_text, re.M)
            summary = re.sub(r";?\s*\*\*(Proposed|Accepted|Superseded|Rejected)\*\*[^|]*$", "", row.group(1)).strip() if row else ""
            summary = self.rewrite(summary, led["dir"], 0)
            src = os.path.normpath(os.path.join(led["dir"], files[0].name))
            url = f"{self.cfg['source_url'].rstrip('/')}/{src}" if self.cfg.get("source_url") else ""
            rows.append((num, head, status, date.group(0) if date else "", summary, url))
        title = led.get("title", "Decision ledger")
        body = front(title, led.get("subtitle", "Every decision record the wiki cites"))
        body += self.plate(led.get("plate"), 0, hero=True) + "\n\n"
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[2]] = counts.get(r[2], 0) + 1
        body += raw('<p class="ledger-count">' + " ".join(
            f'<span class="badge-{esc(s.lower())}">{n} {esc(s.lower())}</span>' for s, n in sorted(counts.items()))
            + "</p>") + "\n\n"
        for num, head, status, date, summary, url in rows:
            t = f'<a class="adr-title" href="{esc(url)}">{esc(head)}</a>' if url else f'<span class="adr-title">{esc(head)}</span>'
            body += raw(f'<div class="adr" id="adr-{num}"><span class="adr-no">{num}</span>'
                        f'<span class="adr-status badge-{esc(status.lower())}">{esc(status)}</span>'
                        f'<span class="adr-date">{date}</span>{t}</div>') + "\n\n"
            if summary:
                body += f"::: {{.adr-summary}}\n{summary}\n:::\n\n"
        self.write("decisions.qmd", body)
        return len(rows)

    def stage_telemetry(self) -> None:
        charts = self.cfg["charts"]
        page = front("Telemetry deck", f"Live from {self.cfg.get('metrics', {}).get('name', 'the metrics store')}",
                     "page-layout: full\ntoc: false\n")
        page += self.plate(self.cfg.get("telemetry_plate"), 0, hero=True) + "\n\n"
        page += ("Each chart runs its query from this browser. Hover for values, drag across a chart to zoom, "
                 "double-click to reset; *table* shows the numbers.\n\n")
        page += raw('<div class="deck">' + "".join(self.chart_html(c) for c in charts) + "</div>") + "\n"
        self.write("telemetry.qmd", page)

    def stage_index(self, cards: list[dict]) -> None:
        cfg = self.cfg
        page = front(cfg.get("title", "Wiki"), cfg.get("subtitle", ""), "page-layout: full\ntitle-block-banner: false\n")
        page += self.plate(cfg.get("plate"), 0, hero=True) + "\n\n"
        if cfg.get("briefing") or cfg.get("home_charts"):
            page += raw('<div class="home-grid">' + (self.briefing_html() if cfg.get("briefing") else "<div></div>")
                        + '<div class="home-charts">' + "".join(self.chart_html(c, True) for c in cfg.get("home_charts", []))
                        + "</div></div>") + "\n\n"
        if cfg.get("intro"):
            page += cfg["intro"].strip() + "\n\n"
        page += "## Read the system {.home-head}\n\n"
        page += raw('<div class="cards cards-wide">' + "".join(
            self.card(c["href"], f'{c.get("n", 0):02d}', c["title"], c.get("text", ""), c.get("art"), 0) for c in cards)
            + "</div>") + "\n\n"
        page += f"::: {{.colophon}}\n{cfg.get('colophon', 'Derived from the source documents; edit those, never this site.')}\n:::\n"
        self.write("index.qmd", page)

    def quarto_yml(self, extra_nav: list[dict]) -> str:
        cfg = self.cfg
        nav = [{"text": cfg.get("home_nav", "Briefing"), "href": "index.qmd"}]
        nav += [{"text": c.get("nav") or c["key"], "href": f"{c['key']}/index.qmd"} for c in cfg["chapters"]]
        nav += extra_nav
        right = [{"text": t["text"], "href": t["href"]} for t in cfg.get("nav_right", [])]
        if cfg.get("repo_url"):
            right.append({"icon": "github", "href": cfg["repo_url"], "aria-label": "Source"})
        resources = ["art/*.webp", "assets/fonts/*", "assets/vendor/*", "media/**"] + list(cfg.get("resources", []))
        website = {"title": cfg.get("title", "Wiki"), "favicon": "assets/favicon.svg", "page-navigation": True,
                   "bread-crumbs": False, "navbar": {"background": "#070b14", "left": nav}}
        if right:
            website["navbar"]["right"] = right
        website["page-footer"] = {"left": cfg.get("footer", "Derived from the source documents · edit those, never the site")}
        doc = {
            "project": {"type": "website", "output-dir": "_site", "resources": resources},
            "metadata-files": ["_sidebar.yml"],
            "website": website,
            "format": {"html": {
                "theme": ["darkly", "theme/wiki.scss"], "css": "assets/wiki.css",
                "include-in-header": "assets/preload.html", "include-after-body": "assets/wiki-js.html",
                "toc": True, "toc-title": "Sectors", "toc-depth": 3, "smooth-scroll": True, "anchor-sections": True,
                "code-copy": False, "highlight-style": "github-dark", "mermaid": {"theme": "default"},
                "link-external-newwindow": True}},
        }
        return "# Generated by wiki.py stage from wiki.json; edit wiki.json, not this file.\n" + to_yaml(doc)

    def stage(self) -> dict:
        self.clean()
        try:
            return self._stage()
        finally:
            (self.site / MANIFEST).write_text("\n".join(self.written) + "\n", encoding="utf-8")

    def _stage(self) -> dict:
        sidebar: list = [{"text": self.cfg.get("home_nav", "Briefing"), "href": "index.qmd"}]
        cards = [self.stage_chapter(c, sidebar) for c in self.cfg["chapters"]]
        extra_nav, n_adrs = [], 0
        for p in self.cfg.get("pages", []):           # hand-made pages that live in the site dir
            cards.append(p)
            extra_nav.append({"text": p.get("nav", p["title"]), "href": re.sub(r"\.html$", ".qmd", p["href"])})
        if self.cfg.get("charts"):
            self.stage_telemetry()
            cards.append({"href": "telemetry.html", "title": "Telemetry deck", "n": len(self.cfg["charts"]),
                          "text": "Every live chart, each zoomable and with a table view.",
                          "art": self.cfg.get("telemetry_plate")})
            extra_nav.append({"text": "Telemetry", "href": "telemetry.qmd"})
        if self.cfg.get("ledger"):
            n_adrs = self.stage_ledger()
            led = self.cfg["ledger"]
            cards.append({"href": "decisions.html", "title": led.get("title", "Decision ledger"), "n": n_adrs,
                          "text": "The decisions behind the system, with status and date.", "art": led.get("plate")})
            extra_nav.append({"text": led.get("nav", "Decisions"), "href": "decisions.qmd"})
        self.stage_index(cards)
        for p in self.cfg.get("pages", []):
            sidebar.append({"text": p.get("nav", p["title"]), "href": re.sub(r"\.html$", ".qmd", p["href"])})
        if self.cfg.get("charts"):
            sidebar.append({"text": "Telemetry deck", "href": "telemetry.qmd"})
        if self.cfg.get("ledger"):
            sidebar.append({"text": self.cfg["ledger"].get("title", "Decision ledger"), "href": "decisions.qmd"})
        self.write("_sidebar.yml", to_yaml({"website": {"sidebar": {
            "style": "docked", "collapse-level": 1, "contents": sidebar}}}))
        self.write("_quarto.yml", self.quarto_yml(extra_nav))
        stats = {"chapters": len(self.cfg["chapters"]), "pages": sum(c.get("n", 0) for c in cards[:len(self.cfg["chapters"])]),
                 "decisions": n_adrs, "charts": len(self.cfg.get("charts", {})),
                 "plates_missing": sorted(wanted_plates(self.cfg) - self.plates)}
        return stats

    def clean(self) -> None:
        """Delete what the last stage wrote (the manifest), then the directories it left empty. Nothing else."""
        mf = self.site / MANIFEST
        if not mf.exists():
            return
        dirs = set()
        for rel in mf.read_text(encoding="utf-8").split():
            p = (self.site / rel).resolve()
            if self.site not in p.parents:
                raise WikiError(f"{MANIFEST} names {rel!r}, outside the site; refusing")
            if p.is_file():
                p.unlink()
            dirs |= {d for d in p.parents if self.site in d.parents}
        for d in sorted(dirs, key=lambda d: -len(d.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        mf.unlink()


def wanted_plates(cfg: dict) -> set:
    names = {cfg.get("plate"), cfg.get("telemetry_plate"), (cfg.get("ledger") or {}).get("plate")}
    for c in cfg["chapters"]:
        names.add(c.get("plate"))
        names |= {s.get("plate") for s in (c.get("sections") or {}).values()}
    names |= {p.get("art") for p in cfg.get("pages", [])}
    return {n for n in names if n}


def to_yaml(obj, indent: int = 0) -> str:
    """Just enough YAML for Quarto's config (JSON scalars are valid YAML)."""
    pad = " " * indent
    if isinstance(obj, list):
        return "".join(f"{pad}- " + to_yaml(v, indent + 2).lstrip() for v in obj)
    if isinstance(obj, dict):
        return "".join(f"{pad}{k}:" + (f" {json.dumps(v)}\n" if not isinstance(v, (list, dict))
                                       else "\n" + to_yaml(v, indent + 2)) for k, v in obj.items())
    return f"{json.dumps(obj)}\n"


# --- commands --------------------------------------------------------------------------------------------------------

def cmd_init(site: Path) -> int:
    site.mkdir(parents=True, exist_ok=True)
    for sub in ("theme", "assets"):
        dst = site / sub
        if dst.exists():
            print(f"  keep {dst} (exists; delete it to take the plugin's copy)")
            continue
        shutil.copytree(TEMPLATE / sub, dst)
        print(f"  wrote {dst}")
    (site / "art").mkdir(exist_ok=True)
    cfg = site / "wiki.json"
    if not cfg.exists():
        shutil.copy(TEMPLATE / "wiki.json", cfg)
        print(f"  wrote {cfg} (edit root, chapters, metrics)")
    gi = site / ".gitignore"
    if not gi.exists():
        gi.write_text("# staged by wiki.py: the sources are the truth\n" + "\n".join(
            ["/_site/", "/.quarto/", "/.wiki-staged", "/media/", "/*.qmd", "/_quarto.yml", "/_sidebar.yml", "/*/*.qmd"]) + "\n", encoding="utf-8")
        print(f"  wrote {gi}")
    return 0


def cmd_scaffold(files: list[str]) -> int:
    chapters = []
    for f in files:
        md = Path(f).read_text(encoding="utf-8")
        title, intro, sections = split_sections(md)
        key = slugify(Path(f).stem) or "chapter"
        chapters.append({"key": key, "file": f, "nav": title or key, "plate": key,
                         "blurb": first_sentence(intro),
                         "sections": {slugify(h): {"plate": slugify(h), "charts": []} for h, _ in sections}})
    print(json.dumps({"title": "WIKI // name", "subtitle": "", "root": ".", "source_url": "", "plate": "hero",
                      "chapters": chapters}, indent=2, ensure_ascii=False))
    return 0


def report(findings: list[tuple[str, str]]) -> int:
    for level, msg in findings:
        print(f"  {'ERROR' if level == 'error' else 'warn '} {msg}")
    errors = sum(1 for lv, _ in findings if lv == "error")
    print(f"  lint: {errors} error(s), {len(findings) - errors} warning(s)")
    return 1 if errors else 0


def cmd_check(cfg: dict) -> int:
    url = (cfg.get("metrics") or {}).get("url")
    if not url:
        print("  no metrics.url in wiki.json; nothing to check")
        return 0
    now, bad = int(time.time()), 0

    def get(path: str, **params) -> list:
        with urllib.request.urlopen(f"{url}{path}?{urllib.parse.urlencode(params)}", timeout=20) as r:
            return json.load(r)["data"]["result"]

    def secs(s: str) -> int:
        return int(s[:-1]) * SECS[s[-1]]

    for cid, c in cfg.get("charts", {}).items():
        for q in filter(None, (c["q"], c.get("ref"))):
            n = len(get("/api/v1/query_range", query=q, start=now - secs(c.get("range", "7d")), end=now,
                        step=secs(c.get("step", "1h"))))
            bad += n == 0
            print(f"  {'ok   ' if n else 'EMPTY'} chart {cid}: {n} series")
    for b in cfg.get("briefing", []):
        for q in filter(None, (b["q"], b.get("of"))):
            n = len(get("/api/v1/query", query=q))
            bad += n == 0
            print(f"  {'ok   ' if n else 'EMPTY'} brief {b['label']}: {n} series")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("init", "scaffold", "lint", "stage", "build", "check"):
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "init":
            return cmd_init(Path(args[0]))
        if cmd == "scaffold":
            return cmd_scaffold(args)
        cfg = load_config(Path(args[0]))
        if cmd == "check":
            return cmd_check(cfg)
        if cmd in ("lint", "build"):
            rc = report(lint(cfg))
            if rc or cmd == "lint":
                return rc
        stats = Site(cfg).stage()
        print(f"  staged: {stats['chapters']} chapters, {stats['pages']} pages, {stats['decisions']} decisions, "
              f"{stats['charts']} charts")
        if stats["plates_missing"]:
            print(f"  plates missing (void pattern shown; render with plates.py): {', '.join(stats['plates_missing'])}")
        if cmd == "build":
            if not shutil.which("quarto"):
                raise WikiError("quarto is not on PATH; install Quarto 1.4+ (https://quarto.org)")
            subprocess.run(["quarto", "render"], cwd=cfg["_site"], check=True)
            print(f"  rendered -> {cfg['_site'] / '_site'}")
        return 0
    except (WikiError, json.JSONDecodeError, OSError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
