"""time-charts: check catches what would make a chart lie; build makes one closed, self-contained page."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import time_charts as tc  # noqa: E402

EXAMPLE = json.loads((SKILL / "examples" / "series.json").read_text(encoding="utf-8"))


def doc(**chart):
    base = {"title": "t", "xs": [1, 2, 3], "series": [{"label": "a", "values": [1, None, 3]}]}
    base.update(chart)
    return {"schema": "time-charts/1", "title": "x", "charts": [base]}


class Check(unittest.TestCase):
    def errors(self, d):
        return tc.check(d)[0]

    def test_example_is_clean(self):
        self.assertEqual(self.errors(EXAMPLE), [])

    def test_schema(self):
        d = doc()
        d["schema"] = "other"
        self.assertTrue(any("schema" in e for e in self.errors(d)))

    def test_length_mismatch(self):
        self.assertTrue(any("one value per x" in e for e in self.errors(doc(series=[{"label": "a", "values": [1]}]))))

    def test_milliseconds(self):
        self.assertTrue(any("milliseconds" in e for e in self.errors(doc(xs=[1.7e12, 1.7e12 + 1, 1.7e12 + 2]))))

    def test_unsorted_x(self):
        self.assertTrue(any("increasing" in e for e in self.errors(doc(xs=[3, 2, 1]))))

    def test_string_value(self):
        self.assertTrue(any("numbers or null" in e for e in self.errors(doc(series=[{"label": "a", "values": [1, "2", 3]}]))))

    def test_negative_in_stack(self):
        self.assertTrue(any("negative" in e for e in self.errors(doc(kind="area", series=[{"label": "a", "values": [1, -2, 3]}]))))

    def test_kind(self):
        self.assertTrue(any("kind" in e for e in self.errors(doc(kind="pie"))))

    def test_many_series_warns(self):
        d = doc(series=[{"label": str(i), "values": [1, 2, 3]} for i in range(8)])
        self.assertEqual(self.errors(d), [])
        self.assertTrue(tc.check(d)[1])


class Build(unittest.TestCase):
    def test_self_contained(self):
        html = tc.build(EXAMPLE)
        self.assertIn("uPlot", html)
        self.assertIn("TimeCharts.render", html)
        self.assertNotIn("https://fonts", html)
        self.assertNotRegex(html, r'<(script|link)[^>]+(src|href)="https?:')

    def test_title_cannot_close_the_script(self):
        d = copy.deepcopy(EXAMPLE)
        d["charts"][0]["title"] = "</script><script>alert(1)</script>"
        html = tc.build(d)
        data = html.split('id="tc-data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data)["charts"][0]["title"], d["charts"][0]["title"])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "page.html"
            self.assertEqual(tc.main(["build", str(SKILL / "examples" / "series.json"), "-o", str(out)]), 0)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class FromSpec(unittest.TestCase):
    def test_maps_the_schema(self):
        js = (
            "const T=require(process.argv[1]);"
            "const o=T.fromSpec({kind:'area',unit:'%',xs:[1,2],ref:5,series:[{label:'a',values:[1,2]}]});"
            "console.log(JSON.stringify(o));"
        )
        out = subprocess.run(["node", "-e", js, str(SKILL / "assets" / "charts.js")], capture_output=True, text=True, check=True)
        o = json.loads(out.stdout)
        self.assertEqual(o["kind"], "stack")
        self.assertEqual(o["series"][0], {"name": "a", "vals": [1, 2], "color": "var(--t1)"})
        self.assertEqual(o["ref"]["vals"], [5, 5])


if __name__ == "__main__":
    unittest.main()
