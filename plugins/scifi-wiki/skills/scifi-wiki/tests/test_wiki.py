"""wiki.py: the grammar, the links, lint, and a whole stage of the example (no network, no Quarto)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import wiki  # noqa: E402

EXAMPLES = HERE.parent / "examples"


def site_copy(tmp: Path) -> Path:
    site = tmp / "site"
    wiki.cmd_init(site)
    shutil.copytree(EXAMPLES / "docs", site / "docs")
    shutil.copy(EXAMPLES / "wiki.json", site / "wiki.json")
    return site


class Grammar(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(wiki.slugify("3. The merge line (D4)"), "the-merge-line")
        self.assertEqual(wiki.slugify("`bin/x` *runs*"), "bin-x-runs")

    def test_split_ignores_fenced_headings(self):
        md = "# T\n\nintro\n\n## A\n\n```\n## not a section\n```\n\n## B\n\nb"
        title, intro, secs = wiki.split_sections(md)
        self.assertEqual((title, intro), ("T", "intro"))
        self.assertEqual([h for h, _ in secs], ["A", "B"])
        self.assertIn("## not a section", secs[0][1])

    def test_first_sentence_skips_tables_and_fences(self):
        body = "| a | b |\n|---|---|\n\n```\ncode\n```\n\nThe [bus](x.md) holds `80 %`. More."
        self.assertEqual(wiki.first_sentence(body), "The bus holds 80 %.")


class Lint(unittest.TestCase):
    def test_non_latin_headings_have_slugs(self):
        self.assertEqual(wiki.slugify("2. Питание (D4)"), "питание")
        self.assertEqual([lv for lv, _ in wiki.lint_markdown("# Т\n\nи\n\n## Питание\n\nТекст.\n", "d.md")], [])

    def test_dangling_relative_link_without_source_url(self):
        with tempfile.TemporaryDirectory() as t:
            site = site_copy(Path(t))
            cfg = json.loads((site / "wiki.json").read_text())
            cfg["source_url"] = ""
            (site / "wiki.json").write_text(json.dumps(cfg))
            found = wiki.lint(wiki.load_config(site / "wiki.json"))
            self.assertTrue(any(lv == "error" and "source_url" in m for lv, m in found))

    def test_unclosed_fence_and_missing_title(self):
        found = wiki.lint_markdown("intro\n\n## A\n\n```\nx\n", "d.md")
        msgs = " ".join(m for _, m in found)
        self.assertIn("never closed", msgs)
        self.assertIn("no `# ` title", msgs)

    def test_duplicate_page_names(self):
        found = wiki.lint_markdown("# T\n\ni\n\n## 1. Power\n\nP.\n\n## 2. Power\n\nQ.\n", "d.md")
        self.assertTrue(any(lv == "error" and "same page name" in m for lv, m in found))

    def test_mapped_section_renamed(self):
        with tempfile.TemporaryDirectory() as t:
            site = site_copy(Path(t))
            cfg = json.loads((site / "wiki.json").read_text())
            cfg["chapters"][0]["sections"]["gravity"] = {}
            (site / "wiki.json").write_text(json.dumps(cfg))
            found = wiki.lint(wiki.load_config(site / "wiki.json"))
            self.assertTrue(any(lv == "error" and "'gravity'" in m for lv, m in found))

    def test_example_is_clean(self):
        with tempfile.TemporaryDirectory() as t:
            site = site_copy(Path(t))
            self.assertEqual([f for f in wiki.lint(wiki.load_config(site / "wiki.json")) if f[0] == "error"], [])

    def test_config_rejects_unknown_chart(self):
        with tempfile.TemporaryDirectory() as t:
            site = site_copy(Path(t))
            cfg = json.loads((site / "wiki.json").read_text())
            cfg["chapters"][0]["sections"]["power"]["charts"] = ["nope"]
            (site / "wiki.json").write_text(json.dumps(cfg))
            with self.assertRaises(wiki.WikiError):
                wiki.load_config(site / "wiki.json")


class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = site_copy(Path(self.tmp.name))
        self.cfg = wiki.load_config(self.site / "wiki.json")
        self.stats = wiki.Site(self.cfg).stage()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pages_and_counts(self):
        self.assertEqual(self.stats["pages"], 3)
        self.assertEqual(self.stats["decisions"], 2)
        names = sorted(p.name for p in (self.site / "systems").glob("*.qmd"))
        self.assertEqual(names, ["01-life-support.qmd", "02-power.qmd", "03-where-it-stands.qmd", "index.qmd"])

    def test_links_point_at_the_wiki(self):
        page = (self.site / "systems" / "01-life-support.qmd").read_text()
        self.assertIn("](../decisions.html#adr-0001)", page)
        self.assertIn("```{mermaid}", page)
        self.assertIn('data-chart="targets"', page)

    def test_non_wiki_link_goes_to_source_url(self):
        index = (self.site / "systems" / "index.qmd").read_text()
        self.assertIn("](https://github.com/OWNER/REPO/blob/main/examples/docs/adr/README.md)", index)

    def test_ledger_strips_status_marker(self):
        led = (self.site / "decisions.qmd").read_text()
        self.assertIn("Radiator vanes follow hull temperature", led)
        self.assertNotIn("**Proposed**", led)
        self.assertLess(led.index('id="adr-0002"'), led.index('id="adr-0001"'))

    def test_void_plates_without_art(self):
        self.assertIn("plate-void", (self.site / "index.qmd").read_text())
        self.assertIn("hero", self.stats["plates_missing"])

    def test_quarto_yml_navbar(self):
        yml = (self.site / "_quarto.yml").read_text()
        for href in ("index.qmd", "systems/index.qmd", "telemetry.qmd", "decisions.qmd"):
            self.assertIn(json.dumps(href), yml)

    def test_restage_is_idempotent(self):
        before = (self.site / "systems" / "02-power.qmd").read_text()
        wiki.Site(self.cfg).stage()
        self.assertEqual(before, (self.site / "systems" / "02-power.qmd").read_text())

    def test_keeps_files_it_did_not_write(self):
        (self.site / "systems" / "mine.qmd").write_text("mine")
        (self.site / "systems" / "notes.txt").write_text("mine")
        wiki.Site(self.cfg).stage()
        self.assertEqual((self.site / "systems" / "mine.qmd").read_text(), "mine")
        self.assertTrue((self.site / "systems" / "notes.txt").exists())

    def test_refuses_to_overwrite_a_foreign_page(self):
        (self.site / ".wiki-staged").write_text("")       # as if index.qmd were the user's own
        with self.assertRaises(wiki.WikiError):
            wiki.Site(self.cfg).stage()

    def test_section_anchor_lands_on_its_page(self):
        s = wiki.Site(self.cfg)
        self.assertEqual(s.rewrite_link("ship-systems.md#2-power", "docs", 1), "../systems/02-power.html")
        self.assertEqual(s.rewrite_link("#1-life-support", "docs", 1, "docs/ship-systems.md"),
                         "../systems/01-life-support.html")

    def test_relative_image_is_copied(self):
        (self.site / "docs" / "img").mkdir()
        (self.site / "docs" / "img" / "a.png").write_bytes(b"png")
        s = wiki.Site(self.cfg)
        self.assertEqual(s.rewrite("![x](img/a.png)", "docs", 1), "![x](../media/docs/img/a.png)")
        self.assertTrue((self.site / "media" / "docs" / "img" / "a.png").exists())

    def test_image_symlinked_out_of_root_is_not_copied(self):
        outside = Path(self.tmp.name) / "secret.png"
        outside.write_bytes(b"secret")
        (self.site / "docs" / "leak.png").symlink_to(outside)
        s = wiki.Site(self.cfg)
        self.assertEqual(s.rewrite("![x](leak.png)", "docs", 1), "![x](leak.png)")
        self.assertFalse((self.site / "media" / "docs" / "leak.png").exists())

    def test_html_attributes_are_escaped(self):
        page = (self.site / "index.qmd").read_text()
        self.assertIn('data-q="count(ALERTS{alertstate=&quot;firing&quot;}) or vector(0)"', page)


if __name__ == "__main__":
    unittest.main()
