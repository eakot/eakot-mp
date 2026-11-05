"""goal-map: check catches what would make the map lie; build makes one closed, self-contained page."""
import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import goal_map as gm  # noqa: E402

EXAMPLE = json.loads((SKILL / "examples" / "goals.json").read_text(encoding="utf-8"))


def doc(*goals):
    return {"schema": "goal-map/1", "title": "x", "topics": [{"id": "a", "label": "A"}],
            "goals": list(goals) or [{"id": "1", "title": "t", "topic": "a", "state": "open", "total": 2, "completed": 1}]}


def goal(**kw):
    g = {"id": "1", "title": "t", "topic": "a", "state": "open", "total": 2, "completed": 1}
    g.update(kw)
    return g


class Check(unittest.TestCase):
    def errors(self, d):
        return gm.check(d)[0]

    def test_example_is_clean(self):
        self.assertEqual(gm.check(EXAMPLE), ([], []))

    def test_schema(self):
        d = doc()
        d["schema"] = "goal-map/2"
        self.assertTrue(any("schema" in e for e in self.errors(d)))

    def test_duplicate_id(self):
        self.assertTrue(any("duplicate" in e for e in self.errors(doc(goal(), goal()))))

    def test_completed_over_total(self):
        self.assertTrue(any("more than total" in e for e in self.errors(doc(goal(completed=3)))))

    def test_counts_are_whole_numbers(self):
        for bad in (-1, 1.5, "2", True):
            self.assertTrue(self.errors(doc(goal(total=bad))), bad)

    def test_state(self):
        self.assertTrue(any("state" in e for e in self.errors(doc(goal(state="done")))))

    def test_parent_missing_and_loop(self):
        self.assertTrue(any("does not exist" in e for e in self.errors(doc(goal(parent="9")))))
        loop = doc(goal(id="1", parent="2"), goal(id="2", parent="1"))
        self.assertTrue(any("loops" in e for e in self.errors(loop)))

    def test_unsafe_url(self):
        self.assertTrue(any("url" in e for e in self.errors(doc(goal(url="javascript:alert(1)")))))

    def test_unknown_topic_warns(self):
        errors, warnings = gm.check(doc(goal(topic="zzz")))
        self.assertEqual(errors, [])
        self.assertTrue(any("other" in w for w in warnings))


class Build(unittest.TestCase):
    def test_self_contained(self):
        html = gm.build(EXAMPLE)
        self.assertIn("GoalMap.render", html)
        self.assertNotRegex(html, r'<(script|link)[^>]+(src|href)="https?:')

    def test_title_cannot_close_the_script(self):
        d = copy.deepcopy(EXAMPLE)
        d["goals"][0]["title"] = "</script><script>alert(1)</script>"
        html = gm.build(d)
        data = html.split('id="gm-data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data)["goals"][0]["title"], d["goals"][0]["title"])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Prepare(unittest.TestCase):
    def run_node(self, data):
        js = (
            "const G=require(process.argv[1]); const d=JSON.parse(process.argv[2]); const m=G.prepare(d);"
            "console.log(JSON.stringify({goals:m.goals.map(g=>({id:g.id,slot:g.slot,pct:g.pct,parent:g.parent,ready:g.ready,"
            "r:Math.hypot(g.x,g.y),x:g.x})),sectors:m.sectors.map(s=>s.t),totals:m.totals}));"
        )
        out = subprocess.run(["node", "-e", js, str(SKILL / "assets" / "goal-map.js"), json.dumps(data)],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_example_lays_out(self):
        m = self.run_node(EXAMPLE)
        self.assertEqual(len(m["goals"]), len(EXAMPLE["goals"]))
        self.assertEqual(m["sectors"], [t["id"] for t in EXAMPLE["topics"]])
        self.assertTrue(all(isinstance(g["x"], (int, float)) for g in m["goals"]))
        moon = next(g for g in m["goals"] if g["id"] == "111")
        self.assertEqual(moon["parent"], "110")

    def test_nearer_done_is_nearer_the_core(self):
        d = doc(goal(id="1", total=10, completed=9), goal(id="2", total=10, completed=1))
        g = {x["id"]: x for x in self.run_node(d)["goals"]}
        self.assertLess(g["1"]["r"], g["2"]["r"])

    def test_seventh_topic_is_other_and_ready_flag(self):
        d = doc(goal(id="1", topic="nope", total=2, completed=2))
        g = self.run_node(d)["goals"][0]
        self.assertEqual(g["slot"], 0)
        self.assertTrue(g["ready"])

    def test_parent_loop_is_dropped(self):
        d = doc(goal(id="1", parent="2"), goal(id="2", parent="1"))
        self.assertTrue(all(g["parent"] == "" or g["parent"] in ("1", "2") for g in self.run_node(d)["goals"]))


if __name__ == "__main__":
    unittest.main()
