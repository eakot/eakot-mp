"""scifi-graph: check, adrs, merge, estimate, build, and the renderer's pure half under Node."""
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import scifi_graph as sg  # noqa: E402

EXAMPLE = SKILL / "examples" / "helix.graph.json"
JS = SKILL / "assets" / "scifi-graph.js"


def tiny() -> dict:
    return {"schema": sg.SCHEMA, "nodes": [
        {"id": "g", "kind": "goal", "state": "open", "title": "Goal", "gains": ["+3 faster", "safer"]},
        {"id": "e", "kind": "epic", "parent": "g", "state": "open", "title": "Epic"},
        {"id": "t1", "kind": "task", "parent": "e", "state": "done", "title": "One", "cost": {"actual": 4}},
        {"id": "t2", "kind": "task", "parent": "e", "state": "open", "title": "Two"},
    ], "edges": [{"from": "t1", "to": "t2"}]}


class Check(unittest.TestCase):
    def errors(self, g: dict) -> list[str]:
        return sg.check(g)[0]

    def test_example_is_clean(self):
        errs, _ = sg.check(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(errs, [])

    def test_tiny_is_clean_and_warns_about_nd(self):
        errs, warns = sg.check(tiny())
        self.assertEqual(errs, [])
        self.assertTrue(any("N/D" in w for w in warns))

    def test_duplicate_dangling_and_self(self):
        g = tiny()
        g["nodes"].append(dict(g["nodes"][0]))
        g["edges"] += [{"from": "t1", "to": "nope"}, {"from": "t2", "to": "t2"}]
        errs = " | ".join(self.errors(g))
        self.assertIn("duplicate id", errs)
        self.assertIn("does not exist", errs)
        self.assertIn("depends on itself", errs)

    def test_cycle_is_named(self):
        g = tiny()
        g["edges"].append({"from": "t2", "to": "t1"})
        self.assertTrue(any("cycle" in e and "t1" in e for e in self.errors(g)))

    def test_parent_loop_and_goal_with_parent(self):
        g = tiny()
        g["nodes"][1]["parent"] = "t1"
        g["nodes"][0]["parent"] = "e"
        errs = " | ".join(self.errors(g))
        self.assertIn("loops", errs)
        self.assertIn("no parent", errs)

    def test_cost_rules(self):
        g = tiny()
        g["nodes"][2]["cost"] = {"actual": 0 - 1}
        g["nodes"][3]["cost"] = {"estimate": 5, "low": 6, "high": 9}
        g["nodes"][1]["cost"] = {"guess": 1}
        errs = " | ".join(self.errors(g))
        self.assertIn("≥ 0", errs)
        self.assertIn("low ≤ estimate ≤ high", errs)
        self.assertIn("takes only", errs)

    def test_non_finite_and_wrong_types_are_errors_not_crashes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "nan.json"
            f.write_text('{"schema":"scifi-graph/1","nodes":[{"id":"a","state":"open","cost":{"estimate":NaN}}]}')
            self.assertEqual(sg.main(["build", str(f), "-o", str(Path(d) / "x.html")]), 1)
            self.assertFalse((Path(d) / "x.html").exists())
        g = tiny()
        g["topics"] = [{"id": "t"}]
        g["nodes"][1]["parent"] = ["g"]
        g["nodes"][2]["topic"] = ["t"]
        g["edges"].append({"from": [1], "to": "t2"})
        errs = " | ".join(self.errors(g))
        self.assertIn("parent must be a string", errs)
        self.assertIn("topic must be a string", errs)
        self.assertIn("names a node that does not exist", errs)
        g = tiny()
        g["nodes"][2]["cost"] = {"actual": float("inf")}
        self.assertTrue(any("≥ 0" in e for e in self.errors(g)))

    def test_deep_nesting_is_reported(self):
        g = {"schema": sg.SCHEMA, "nodes": [{"id": "n0", "kind": "epic", "state": "open"}]}
        g["nodes"] += [{"id": f"n{i}", "kind": "task", "state": "open", "parent": f"n{i - 1}"} for i in range(1, 40)]
        self.assertTrue(any("deep" in e for e in self.errors(g)))

    def test_protocol_relative_url_is_refused(self):
        g = tiny()
        g["nodes"][0]["url"] = "//elsewhere.example/x"
        self.assertTrue(any("url" in e for e in self.errors(g)))
        g["nodes"][0]["url"] = "/same/origin"
        self.assertEqual(self.errors(g), [])

    def test_bad_url_and_schema(self):
        g = tiny()
        g["schema"] = "x"
        g["nodes"][0]["url"] = "javascript:alert(1)"
        errs = " | ".join(self.errors(g))
        self.assertIn("schema", errs)
        self.assertIn("url", errs)


class Adrs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "0001-base.md").write_text(
            "# 0001 — The base\n\n- **Status:** Accepted (2301-01-01)\n\n## Decision\n\n"
            "1. **D1 — do the thing.** Because.\n\n## Gains\n\n- +3 the thing is done\n- one more gain\n", encoding="utf-8")
        (self.dir / "0002-next.md").write_text(
            "# ADR 0002 — Next\n\n**Status:** Proposed\n**Builds on:** [ADR 0001](0001-base.md); amends nothing\n"
            "**Extends:** ADR 0009 (not here)\n\n## Decision\n\n### D1 — first\n\n### D2 — second\n\n"
            "## Context\n\nBuilds on: ADR 0001 (body text is not a header)\n", encoding="utf-8")
        (self.dir / "0003-dropped.md").write_text("# 0003 — Dropped\n\n- **Status:** Rejected\n", encoding="utf-8")
        (self.dir / "README.md").write_text("# index\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_goals_edges_gains(self):
        g = sg.adrs(self.dir, "r", "https://x.example/adr")
        by = {n["id"]: n for n in g["nodes"]}
        self.assertEqual(set(by), {"adr:r/0001", "adr:r/0002"})          # rejected and README skipped
        self.assertEqual(by["adr:r/0001"]["state"], "done")
        self.assertEqual(by["adr:r/0001"]["title"], "The base")
        self.assertEqual(by["adr:r/0001"]["gains"], ["+3 the thing is done", "one more gain"])
        self.assertEqual(by["adr:r/0001"]["decides"], ["D1 — do the thing"])
        self.assertEqual(by["adr:r/0002"]["state"], "open")
        self.assertEqual(by["adr:r/0002"]["decides"], ["D1 — first", "D2 — second"])
        self.assertNotIn("gains", by["adr:r/0002"])                       # no section, no invented gains
        self.assertEqual(g["edges"], [{"from": "adr:r/0001", "to": "adr:r/0002", "kind": "builds-on"}])
        self.assertEqual(by["adr:r/0001"]["url"], "https://x.example/adr/0001-base.md")
        self.assertEqual(sg.check(g)[0], [])


class MergeEstimate(unittest.TestCase):
    def test_merge_first_wins_and_drops_dangling(self):
        a = tiny()
        b = {"schema": sg.SCHEMA, "nodes": [{"id": "g", "kind": "goal", "state": "done", "title": "other"},
                                            {"id": "x", "kind": "task", "state": "open"}],
             "edges": [{"from": "x", "to": "t2"}, {"from": "x", "to": "ghost"}], "notes": ["n"]}
        m = sg.merge([a, b])
        self.assertEqual([n["id"] for n in m["nodes"]], ["g", "e", "t1", "t2", "x"])
        self.assertEqual(next(n for n in m["nodes"] if n["id"] == "g")["title"], "Goal")
        self.assertIn({"from": "x", "to": "t2"}, m["edges"])
        self.assertFalse(any(e["to"] == "ghost" for e in m["edges"]))
        self.assertEqual(m["notes"], ["n"])

    def graph(self, actuals: list[float], topic: str = "a", other: list[float] = ()) -> dict:
        nodes = [{"id": f"d{i}", "kind": "task", "state": "done", "topic": topic, "cost": {"actual": v},
                  "closed": "2301-06-20"} for i, v in enumerate(actuals)]
        nodes += [{"id": f"o{i}", "kind": "task", "state": "done", "topic": "b", "cost": {"actual": v},
                   "closed": "2301-06-20"} for i, v in enumerate(other)]
        nodes.append({"id": "open", "kind": "task", "state": "open", "topic": topic})
        return {"schema": sg.SCHEMA, "nodes": nodes, "edges": []}

    def test_same_topic_quartiles(self):
        g = sg.estimate(self.graph([1, 2, 3, 4, 5]), today=dt.date(2301, 6, 24))
        c = next(n for n in g["nodes"] if n["id"] == "open")["cost"]
        self.assertEqual((c["low"], c["estimate"], c["high"]), (2, 3, 4))
        self.assertTrue(g["notes"][-1].startswith("≈ estimates:"))

    def test_pools_topics_under_min_samples(self):
        g = sg.estimate(self.graph([10], other=[1, 1, 1, 1]), today=dt.date(2301, 6, 24))
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "open")["cost"]["estimate"], 1)

    def test_window_and_nd(self):
        g = self.graph([5, 5, 5, 5, 5])
        for n in g["nodes"]:
            if n["state"] == "done":
                n["closed"] = "2301-01-01"
        g = sg.estimate(g, today=dt.date(2301, 6, 24))
        self.assertNotIn("cost", next(n for n in g["nodes"] if n["id"] == "open"))   # no sample: N/D, not 0

    def test_active_is_never_estimated_and_few_samples_give_no_range(self):
        g = self.graph([2])
        g["nodes"].append({"id": "busy", "kind": "task", "state": "active", "topic": "a"})
        g = sg.estimate(g, today=dt.date(2301, 6, 24))
        self.assertNotIn("cost", next(n for n in g["nodes"] if n["id"] == "busy"))
        self.assertEqual(next(n for n in g["nodes"] if n["id"] == "open")["cost"], {"estimate": 2})

    def test_estimate_never_overwrites(self):
        g = self.graph([1, 2, 3, 4, 5])
        g["nodes"][-1]["cost"] = {"estimate": 99}
        g = sg.estimate(g, today=dt.date(2301, 6, 24))
        self.assertEqual(g["nodes"][-1]["cost"], {"estimate": 99})


class Build(unittest.TestCase):
    def test_page_is_self_contained_and_script_safe(self):
        g = tiny()
        g["title"] = "Plan </script><script>alert(1)</script>"
        g["nodes"][0]["title"] = "</script><!-- x"
        html = sg.build(g)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertEqual(html.count("</script>"), html.count("<script"))     # no early close from the data
        self.assertIn("data:font/woff2;base64,", html)
        self.assertNotIn("url(fonts/", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
        self.assertIn("&lt;/script&gt;", html.split("<style>")[0])          # <title> escaped

    def test_cli_rejects_bad_graph(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps({"schema": sg.SCHEMA, "nodes": []}), encoding="utf-8")
            self.assertEqual(sg.main(["build", str(bad), "-o", str(Path(d) / "x.html")]), 1)
            self.assertFalse((Path(d) / "x.html").exists())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Renderer(unittest.TestCase):
    def prepare(self, graph: dict) -> dict:
        script = f"""
const G = require({json.dumps(str(JS))});
const m = G.prepare(JSON.parse(require('fs').readFileSync(0, 'utf8')));
const out = {{}};
for (const n of m.nodes.values()) out[n.id] = {{tree: n.tree, roll: n.roll, points: n.points,
  box: [n.x, n.y, n.w, n.h], up: n.up ? n.up.id : null}};
console.log(JSON.stringify({{nodes: out, totals: m.totals, bands: m.bands.map(b => b.label)}}));
"""
        r = subprocess.run(["node", "-e", script], input=json.dumps(graph), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_states_rollups_points(self):
        m = self.prepare(tiny())
        n = m["nodes"]
        self.assertEqual(n["t1"]["tree"], "unlocked")
        self.assertEqual(n["t2"]["tree"], "available")
        self.assertEqual(n["e"]["roll"]["spent"], 4)
        self.assertEqual(n["g"]["roll"]["togoNd"], 1)
        self.assertEqual(n["g"]["points"], 4)                       # +3 and an unweighted 1
        self.assertEqual(m["totals"]["pointsUnlocked"], 0)

    def test_locked_and_done_container_with_open_work(self):
        g = tiny()
        g["nodes"][0]["state"] = "done"                             # an Accepted ADR whose work is still open
        g["nodes"].append({"id": "t3", "kind": "task", "parent": "e", "state": "open"})
        g["edges"].append({"from": "t2", "to": "t3"})
        n = self.prepare(g)["nodes"]
        self.assertEqual(n["t3"]["tree"], "locked")
        self.assertNotEqual(n["g"]["tree"], "unlocked")

    def test_nesting_children_inside_parents_no_overlap(self):
        m = self.prepare(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        nodes = m["nodes"]
        for nid, n in nodes.items():
            if n["up"]:
                px, py, pw, ph = nodes[n["up"]]["box"]
                x, y, w, h = n["box"]
                self.assertTrue(px <= x and py <= y and x + w <= px + pw + 1e-6 and y + h <= py + ph + 1e-6, nid)
        groups: dict = {}
        for nid, n in nodes.items():
            groups.setdefault(n["up"], []).append(n["box"])
        for boxes in groups.values():
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    overlap = a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                    self.assertFalse(overlap, (a, b))
        self.assertEqual(m["bands"], ["Life support", "Propulsion", "Navigation", "Crew"])

    def test_builds_on_runs_forward(self):
        m = self.prepare(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        g = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        for e in g["edges"]:
            if e.get("kind") == "builds-on":
                a, b = m["nodes"][e["from"]]["box"], m["nodes"][e["to"]]["box"]
                self.assertLessEqual(a[0] + a[2], b[0], e)

    def test_survives_hostile_input(self):
        hostile = {"schema": sg.SCHEMA, "topics": [None, 3, {"id": 4}], "edges": [None, {"from": [1], "to": {}}],
                   "nodes": [None, 7, {"id": "g", "kind": 5, "state": None, "gains": "x", "decides": [5],
                                       "cost": {"estimate": -1, "actual": "9"}, "title": {"a": 1}, "topic": ["t"]},
                             {"id": "t", "parent": ["g"], "gains": [5, "+2 ok"]}]}
        m = self.prepare(hostile)
        self.assertEqual(m["totals"]["togo"], 0)                     # a negative estimate is N/D, not -1
        self.assertEqual(m["nodes"]["g"]["roll"]["togoNd"], 1)

    def test_a_very_deep_chain_draws(self):
        g = {"schema": sg.SCHEMA, "nodes": [{"id": "n0", "kind": "epic", "state": "open"}]}
        g["nodes"] += [{"id": f"n{i}", "state": "open", "parent": f"n{i - 1}"} for i in range(1, 20000)]
        m = self.prepare(g)
        self.assertEqual(len(m["nodes"]), 20000)

    def test_survives_a_cycle_and_a_parent_loop(self):
        g = copy.deepcopy(tiny())
        g["edges"].append({"from": "t2", "to": "t1"})
        g["nodes"][1]["parent"] = "t1"
        g["nodes"][2]["parent"] = "e"
        self.prepare(g)                                             # no hang, no throw


if __name__ == "__main__":
    unittest.main()
