"""Regression tests for the skill's scripts. Standard library only; the harness tests need `node`.

    python3 -m unittest discover -s tests      (from the skill directory; also on Python 3.9)
"""
import copy
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
import grafana_api  # noqa: E402
import sheet_harness  # noqa: E402
import sitrep  # noqa: E402

VM = {"type": "prometheus", "uid": "vm"}
PG = {"type": "grafana-postgresql-datasource", "uid": "pg"}
HARNESS = str(SKILL / "scripts" / "sheet_harness.py")


def mini_sheet(pid, y, body=None, **kw):
    body = body or "const v = one('A'); const html = page('01', 'T', brief(v == null ? 'none' : 'v ' + v) + ln('v', num(v), v == null ? 'nd' : 'ok'));"
    return sitrep.sheet(pid, f"sheet {pid}", "", {"h": 4, "w": 8, "x": 0, "y": y}, [sitrep.q("A", "up", VM)], body, ds=VM, **kw)


def sql_sheet(pid, y, body, refs=("A",)):
    return sitrep.sheet(pid, f"sql {pid}", "", {"h": 4, "w": 8, "x": 0, "y": y},
                        [sitrep.sql(r, f"SELECT count(*) AS n FROM t_{r.lower()} WHERE s = '$schema_type' AND d = '$schema'", PG)
                         for r in refs], body, ds=PG)


# two tables: A's count drives one line, B's another; the verdict reads both
TWO = ("const ta = table('A'), tb = table('B'); const na = ta.length ? ta[0].n : null, nb = tb.length ? tb[0].n : null;"
       " const html = page('01', 'T', brief('x') + ln('from A', na == null ? '—' : int(na), na == null ? 'nd' : 'ok')"
       " + ln('from B', nb == null ? '—' : int(nb), nb == null ? 'nd' : 'ok'));")


def run_js(s):
    js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def collapsed(pid, y, kids):
    r = sitrep.row(pid, f"row {pid}", y)
    r.update(collapsed=True, panels=kids)
    return r


def harness(dash, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(dash, f)
    try:
        return subprocess.run([sys.executable, HARNESS, f.name, *args], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(f.name)


def fixture(data):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


class Finish(unittest.TestCase):
    def test_duplicate_id_inside_collapsed_row(self):
        d = {"panels": [mini_sheet(6, 0), collapsed(50, 4, [mini_sheet(6, 5)])]}
        with self.assertRaisesRegex(SystemExit, "duplicate panel id 6"):
            sitrep.finish(d)

    def test_overlap_inside_collapsed_row(self):
        d = {"panels": [collapsed(50, 0, [mini_sheet(1, 1), mini_sheet(2, 3)])]}
        with self.assertRaisesRegex(SystemExit, "in row 50"):
            sitrep.finish(d)

    def test_collapsed_row_is_its_own_grid(self):
        # a child's cells may repeat a top-level panel's: the row opens below and pushes the rest down
        d = {"panels": [collapsed(50, 0, [mini_sheet(1, 1)]), mini_sheet(2, 1)]}
        sitrep.finish(d)

    def test_child_above_its_row(self):
        d = {"panels": [mini_sheet(1, 0), collapsed(50, 4, [mini_sheet(2, 2)])]}
        with self.assertRaisesRegex(SystemExit, "above the row"):
            sitrep.finish(d)


class Carry(unittest.TestCase):
    SRC = [sitrep.row(9, "expanded", 0)] + [
        {"id": i, "type": "stat", "title": f"p{i}", "gridPos": {"h": 4, "w": 10, "x": 0, "y": 1}} for i in (6, 7, 8)
    ] + [collapsed(20, 9, [{"id": 21, "type": "stat", "title": "nested", "gridPos": {"h": 3, "w": 4, "x": 0, "y": 10}}])]

    def test_pack_renumber_and_check(self):
        r, y = sitrep.carry_panels(self.SRC, [6, 7, 8, 21], 4, "Drill-down")
        self.assertEqual((y, r["collapsed"], r["id"]), (5, True, 1000))
        self.assertEqual([c["id"] for c in r["panels"]], [1006, 1007, 1008, 1021])
        self.assertEqual([(c["gridPos"]["x"], c["gridPos"]["y"]) for c in r["panels"]], [(0, 5), (10, 5), (0, 9), (10, 9)])
        sitrep.finish({"panels": [mini_sheet(6, 0), r]})  # the new sheet's id 6 no longer collides

    def test_unknown_id(self):
        with self.assertRaisesRegex(SystemExit, "no panel with id"):
            sitrep.carry_panels(self.SRC, [99], 0, "x")

    def test_carry_rows_names_the_alternative(self):
        with self.assertRaisesRegex(SystemExit, "carry_panels"):
            sitrep.carry_rows(self.SRC, 0)


class Coverage(unittest.TestCase):
    SRC = [{"id": 1, "title": "a", "targets": [{"expr": 'sum by (transport, proxy) (rate(conn_fail_total{x="y"}[5m]))'}]},
           {"id": 2, "title": "b", "targets": [{"expr": "histogram_quantile(0.95, sum by (le) (rate(lat_bucket[$__interval])))"}]}]

    def test_unmapped_original_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "panel 2 'b' is not mapped"):
            sitrep.coverage(self.SRC, {1: 10}, [{"id": 10}])

    def test_none_target_is_unmapped(self):
        with self.assertRaisesRegex(SystemExit, "panel 1 'a' is not mapped"):
            sitrep.coverage(self.SRC, {1: None, 2: 10}, [{"id": 10}])

    def test_drop_needs_reason_and_target_must_exist(self):
        with self.assertRaisesRegex(SystemExit, "needs its reason"):
            sitrep.coverage(self.SRC, {1: "dropped:", 2: 10}, [{"id": 10}])
        with self.assertRaisesRegex(SystemExit, "does not have"):
            sitrep.coverage(self.SRC, {1: 10, 2: "covered-by:11"}, [{"id": 10, "title": "n"}])

    def test_malformed_targets_are_refused_not_crashed(self):
        for bad in ("covered-by:abc", "covered-by:", True):
            with self.assertRaisesRegex(SystemExit, "is not a new id"):
                sitrep.coverage(self.SRC, {1: bad, 2: 10}, [{"id": 10}])

    def test_unknown_target_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "maps to 9999"):
            sitrep.coverage(self.SRC, {1: 9999, 2: 10}, [{"id": 10}])

    def test_parity_ignores_inf_nan_in_any_case(self):
        names, _ = sitrep.promql_parts("clamp_max(x_total, +Inf) or y_total > NaN or z > inf")
        self.assertEqual(names, {"x_total", "y_total", "z"})

    def test_table(self):
        t = sitrep.coverage(self.SRC, {1: 10, 2: "dropped:no reader"}, [{"id": 10, "title": "new"}], {1: "why?"})
        self.assertIn("| 1 | a | why? | 10 new |", t)
        self.assertIn("dropped: no reader", t)

    def test_parity_names_what_the_redraw_lost(self):
        new = [{"id": 10, "targets": [{"expr": "sum by (transport) (rate(conn_fail_total[5m]))"}]}]
        w = sitrep.parity(self.SRC, new)
        self.assertTrue(any("'proxy'" in x for x in w), w)
        self.assertTrue(any("lat_bucket" in x for x in w), w)
        self.assertFalse(any("conn_fail_total" in x or "histogram_quantile" in x or "rate" in x for x in w), w)


class Sheet(unittest.TestCase):
    def test_consts_survive_percent_and_braces(self):
        s = mini_sheet(1, 0, "const html = page('01', 'T', brief(`${7 % 3} ${TN.a}`));", consts={"TN": {"a": "100 % {x}"}})
        self.assertIn('const TN = {"a": "100 % {x}"};', s["options"]["helpers"])
        with self.assertRaises(SystemExit):
            mini_sheet(1, 0, consts={"not-js": 1})

    def test_column_titles_are_escaped_once(self):
        s = mini_sheet(1, 0, "const html = page('01', 'T', brief('x') + cols([[8, 'p95 <1s', 'r'], [6, 'in&out'], [0, 'a\\'b']]).hdr);")
        js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertNotIn("&amp;amp;", out)
        self.assertNotIn("&amp;lt;", out)
        self.assertEqual(sheet_harness.text(out).splitlines()[-1].split(), ["p95", "<1s", "in&out", "a'b"])
        s = mini_sheet(1, 0, "const T = cols([[0, 'a & <b>', 'r']]); const html = page('01', 'T', brief('x') + T.hdr + T.row(['<b>&x']));")
        js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertIn("&lt;b&gt;&amp;x", out)
        self.assertIn("a &amp; &lt;b&gt;</div>", out)
        self.assertNotIn("&amp;amp;", out)

    def test_helpers_edge_values(self):
        s = mini_sheet(1, 0, "const T = cols([[6, 'a'], [4, 'n', 'r'], [0, 'b']]); const html = page('01', 'T', brief(int(-0.4)) + T.row([undefined, null, null]));")
        js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertNotIn("undefined", out)
        self.assertNotIn("-0", out)
        self.assertEqual(out.count("—"), 3)

    def test_bytes(self):
        s = mini_sheet(1, 0, "const html = page('01', 'T', brief([null, 0, 512, 1024, 1536, 1048064, 5.3 * 1024 ** 3, "
                             "123 * 1024 ** 3, -2048].map(bytes).join('|')));")
        self.assertIn("—|0 B|512 B|1.0 KB|1.5 KB|1.0 MB|5.3 GB|123 GB|-2.0 KB", run_js(s))
        with self.assertRaises(SystemExit):  # a library name now: a page's own `bytes` is refused
            mini_sheet(1, 0, "const bytes = 1; const html = page('01', 'T', brief('x'));")

    def test_int_keeps_nan_visible(self):
        s = mini_sheet(1, 0, "const html = page('01', 'T', brief(int(0 / 0) + '|' + int(-0.4) + '|' + int(1234)));")
        js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertIn("NaN|0|1,234", out)

    def test_shadowing_inside_a_block_is_allowed(self):
        body = "const f = (x) => {\nconst sub = x + 1;\nreturn sub;\n};\nif (true) {\nlet int = 2;\n}\n" \
               "const s = '{ const plural = 1';\nconst html = page('01', 'T', brief(String(f(1))));"
        mini_sheet(1, 0, body)
        with self.assertRaisesRegex(SystemExit, "plural"):
            mini_sheet(1, 0, "  const plural = 1;\n  const html = page('01', 'T', brief('x'));")

    def test_regex_literals_do_not_hide_a_redeclaration(self):
        for body in ("const a = /\\{/;\nconst plural = 1;", "const a = /\\}/;\nconst plural = 1;",
                     "const a = s.replace(/\\(/g, '');\nconst plural = 1;", "const a = /[{}]/;\nconst plural = 1;",
                     "const r = x / y; const plural = 1;"):
            self.assertIn("plural", sitrep.top_level_decls(body), body)
        # a regex with a brace inside a function still lets the function's own declarations shadow
        self.assertEqual(sitrep.top_level_decls("const f = (s) => {\n const sub = s.replace(/\\{/g, '');\n return sub;\n};"), {"f"})

    def test_const_also_declared_in_body_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "keep one"):
            mini_sheet(1, 0, "const TN = 2;\nconst html = page('01', 'T', brief('x'));", consts={"TN": 1})

    def test_redeclaring_a_library_name_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "plural"):
            mini_sheet(1, 0, "const plural = (n) => 'x';\nconst html = page('01', 'T', brief('a'));")
        with self.assertRaisesRegex(SystemExit, "taken by the library"):
            mini_sheet(1, 0, consts={"int": 1})
        # an inner scope may shadow freely
        mini_sheet(1, 0, "const f = () => { const a = 1; return a; };\nconst html = page('01', 'T', brief(String(f())));")

    def test_locale_is_checked_at_generation(self):
        for bad in ("ru_RU", None, ""):
            with self.assertRaisesRegex(SystemExit, "BCP 47"):
                mini_sheet(1, 0, locale=bad)
        mini_sheet(1, 0, locale="ru-RU")

    def test_fxr_escapes_and_pads(self):
        s = mini_sheet(1, 0, "const html = page('01', 'T', brief(fxr(6, '<b>') + '|' + fxr(4, 7)));")
        js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
        self.assertIn("\u2007\u2007&lt;b&gt;</span>", out)
        self.assertIn(">\u2007\u2007\u20077</span>", out)

    def test_minified_lib_renders_the_same(self):
        full = (SKILL / "assets" / "briefing_lib.js").read_text()
        body = ("const T = cols([[4, 'n', 'r'], [0, 'x']]);\n"
                "const html = page('01', 'T', brief(linkify(\"don't api#3\", 'api')) + T.hdr + item(T.row([int(12345), esc('<b>')]), 'ok', false, 'tip') +"
                " ln(repoA('api'), durCol(3700), 'warn') + flow([{label: 'q', nodes: [{key: 'a', html: 'A', state: 'bad', below: 'stuck'}]}], []));")
        outs = []
        for lib in (full, sitrep.LIB):
            saved, sitrep.LIB = sitrep.LIB, lib
            try:
                s = sitrep.sheet(1, "t", "", {"h": 4, "w": 8, "x": 0, "y": 0}, [sitrep.q("A", "up", VM)], body, ds=VM,
                                 repos={"api": "o/api"})
            finally:
                sitrep.LIB = saved
            js = sheet_harness.SHIM % "[]" + s["options"]["helpers"] + "\nprocess.stdout.write(String(OUT));\n"
            outs.append(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertLess(len(sitrep.LIB), 0.7 * len(full))


class Harness(unittest.TestCase):
    def test_text_keeps_a_literal_less_than(self):
        self.assertEqual(sheet_harness.text('<div class="it">rare failures, <20 % of attempts > none</div>'),
                         "rare failures, <20 % of attempts > none")

    def test_runs_sheets_inside_collapsed_rows(self):
        d = {"panels": [mini_sheet(1, 0), collapsed(50, 4, [mini_sheet(7, 5)])]}
        r = harness(d, "--fixture", fixture({"A": [[{}, 3]]}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[7] sheet 7", r.stdout)
        self.assertIn("2 sheet(s)", r.stdout)
        r = harness(d, "--fixture", fixture({"A": [[{}, 3]]}), "--panel", "7")
        self.assertIn("1 sheet(s)", r.stdout)

    def test_verdict_check_does_not_need_the_word(self):
        r = harness({"panels": [mini_sheet(1, 0, brief_label=None)]}, "--fixture", fixture({"A": [[{}, 1]]}))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("SITREP", r.stdout)
        r = harness({"panels": [mini_sheet(1, 0, "const html = page('01', 'T', ln('v', '1', 'ok'));")]}, "--empty")
        self.assertIn("FAIL no verdict line", r.stdout)

    def test_empty_run_fails_an_ok_on_no_data(self):
        bad = mini_sheet(1, 0, "const v = one('A') || 0; const html = page('01', 'T', brief('x') + ln('v', num(v), 'ok'));")
        r = harness({"panels": [bad]}, "--empty")
        self.assertEqual(r.returncode, 1)
        self.assertIn("OK on no data", r.stdout)
        self.assertEqual(harness({"panels": [mini_sheet(1, 0)]}, "--empty").returncode, 0)

    def test_empty_run_fails_a_number_on_an_untagged_sheet(self):
        plain = mini_sheet(1, 0, "const n = one('A') || 0; const html = page('01', 'T', brief('x') + ln('people', `${int(n)} people`, 'idle'));")
        r = harness({"panels": [plain]}, "--empty")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a number on no data", r.stdout)

    def test_empty_run_allows_static_numbers(self):
        ok = mini_sheet(1, 0, "const v = one('A'); const html = page('01', 'T', brief('x') + ln('retention', '30 days', 'idle')"
                              " + ln('people', v == null ? '—' : `${int(v)} people`, v == null ? 'nd' : 'idle'));")
        r = harness({"panels": [ok]}, "--empty")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_empty_run_probe_reads_labels(self):
        ok = mini_sheet(1, 0, "const n = rows('A').map((r) => r.labels.repo.toUpperCase()); const html = page('01', 'T', brief('x')"
                              " + ln('window', '30 days', 'idle') + ln('n', n.length ? n.join() : '—', n.length ? 'idle' : 'nd'));")
        r = harness({"panels": [ok]}, "--empty")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_sql_sheet_reads_a_table_fixture(self):
        body = ("const t = table('A'); const n = t.length ? t[0].n : null;"
                " const html = page('01', 'T', brief(n == null ? 'none' : 'tables ' + n + ' ' + esc(t[0].name)) + ln('n', n == null ? '—' : int(n), n == null ? 'nd' : 'ok'));")
        d = {"panels": [sql_sheet(1, 0, body)]}
        r = harness(d, "--fixture", fixture({"A": {"rows": [{"n": 7, "name": "<b>"}, {"n": None, "name": "x"}]}}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tables 7 <b>", r.stdout)
        self.assertNotIn("skipped", r.stderr)
        r = harness(d, "--fixture", fixture({"A": []}))
        self.assertIn("none", r.stdout)
        r = harness(d, "--fixture", fixture({"A": {"n": 1}}))
        self.assertIn("a table is", r.stdout)
        self.assertEqual(r.returncode, 1)

    def test_table_frame_types(self):
        f = sheet_harness.table_frame("A", [{"a": None, "b": "x"}, {"a": 2.5, "c": True}])[0]["fields"]
        self.assertEqual([(x["name"], x["type"], x["values"]) for x in f],
                         [("a", "number", [None, 2.5]), ("b", "string", ["x", None]), ("c", "boolean", [None, True])])

    def test_partial_empty(self):
        d = {"panels": [sql_sheet(1, 0, TWO, refs=("A", "B"))]}
        fx = fixture({"A": {"rows": [{"n": 3}]}, "B": {"rows": [{"n": 0}]}})
        r = harness(d, "--fixture", fx, "--empty", "A")
        self.assertEqual(r.returncode, 1)  # B's line stays OK, and nobody said that is right
        self.assertIn("OK on no data", r.stdout)
        self.assertIn("from A", r.stdout)
        r = harness(d, "--fixture", fx, "--empty", "A", "--allow-ok", "from B")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("allowed OK", r.stdout)
        for typo in ("2:A", "Z", "A,Z"):  # names no target: never a clean pass
            r = harness(d, "--fixture", fx, "--empty", typo, "--allow-ok", "from B")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("no target on a selected sheet", r.stdout)
        r = harness(d, "--fixture", fx, "--empty", "1:A", "--allow-ok", "from B")
        self.assertEqual(r.returncode, 0, r.stdout)
        r = harness(d, "--empty", "A")
        self.assertEqual(r.returncode, 2)  # a partial empty is not a source
        r = harness(d, "--empty", "--allow-ok", "x")
        self.assertEqual(r.returncode, 2)

    def test_partial_empty_catches_an_invented_number(self):
        body = ("const ta = table('A'), tb = table('B'); const n = ta.length ? ta[0].n : 0;"
                " const html = page('01', 'T', brief('x') + ln('people', `${int(n)} people`, 'idle') + ln('rows', `${int(tb[0].n)} rows`, 'idle'));")
        d = {"panels": [sql_sheet(1, 0, body, refs=("A", "B"))]}
        r = harness(d, "--fixture", fixture({"A": {"rows": [{"n": 3}]}, "B": {"rows": [{"n": 41}]}}), "--empty", "A")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("a number on no data, must read —: ['0 people']", r.stdout)  # B's "41 rows" is real, not flagged

    def test_prefix_variables(self):
        e = sheet_harness.subst("s = '$schema_type' AND d = '${schema}' AND $__timeFilter(t)",
                                {"schema": "prod", "schema_type": "hive"}, builtins=False)
        self.assertEqual(e, "s = 'hive' AND d = 'prod' AND $__timeFilter(t)")
        # only the shorter one given: the longer name stays as it is, it does not become "prod_type"
        self.assertEqual(sheet_harness.subst("$schema_type $schema", {"schema": "prod"}, builtins=False), "$schema_type prod")
        self.assertEqual(sheet_harness.subst("$__range_s $__range", {}), "21600 6h")

    def test_replace_variables_in_the_sheet(self):
        body = "const html = page('01', 'T', brief(context.grafana.replaceVariables('$schema_type/${schema}/$schema'))); "
        r = harness({"panels": [sql_sheet(1, 0, body)]}, "--fixture", fixture({"A": []}),
                    "--var", "schema=prod", "--var", "schema_type=hive")
        self.assertIn("hive/prod/prod", r.stdout)
        r = harness({"panels": [sql_sheet(1, 0, body)]}, "--fixture", fixture({"A": []}), "--var", "schema=prod")
        self.assertIn("$schema_type/prod/prod", r.stdout)

    def test_dump_sql(self):
        d = {"panels": [sql_sheet(1, 0, TWO, refs=("A", "B")), mini_sheet(2, 4)]}
        with tempfile.TemporaryDirectory() as out:
            r = harness(d, "--dump-sql", out, "--var", "schema=prod")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(sorted(os.listdir(out)), ["1-A.sql", "1-B.sql"])
            self.assertIn("d = 'prod'", Path(out, "1-A.sql").read_text())
            self.assertIn("unset: ['$schema_type']", r.stdout)

    def test_builtins_are_substituted(self):
        e = sheet_harness.subst("x[$__range_s] @ ${__to} $__from $__interval_ms $job", {"job": "j"})
        self.assertNotIn("$", e)
        self.assertNotIn("__", e)

    def test_a_run_that_checks_nothing_fails(self):
        d = {"panels": [mini_sheet(1, 0)]}
        r = harness(d, "--empty", "--panel", "999")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such panel", r.stdout)
        r = harness({"panels": [sitrep.row(1, "r", 0)]}, "--empty")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing to check", r.stdout)

    def test_per_panel_fixture(self):
        d = {"panels": [mini_sheet(1, 0), mini_sheet(2, 4)]}
        r = harness(d, "--fixture", fixture({"1": {"A": [[{}, 5]]}, "2": {"A": []}}))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("v 5", r.stdout)
        self.assertIn("none", r.stdout)

    def test_fixture_gap_fails(self):
        d = {"panels": [mini_sheet(1, 0), mini_sheet(2, 4)]}
        r = harness(d, "--fixture", fixture({"1": {"A": [[{}, 5]]}}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("panel 2 is not in the fixture", r.stdout)
        r = harness(d, "--fixture", fixture({"B": []}))
        self.assertIn("refId A is not in the fixture", r.stdout)


class FakeGrafana(http.server.BaseHTTPRequestHandler):
    """Grafana's datasource proxy and dashboard API, enough for the harness and deploy.py."""
    seen = []

    def log_message(self, *a):
        pass

    def reply(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        FakeGrafana.seen.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path.startswith("/hop"):
            self.send_response(302)
            self.send_header("Location", "http://evil.invalid/api/search")
            self.end_headers()
            return
        if self.headers.get("Authorization") != "Bearer glsa_good":
            return self.reply(401, {"message": "Invalid API key"})
        if self.path.startswith("/api/datasources/uid/vm") or self.path.startswith("/api/datasources/name/Prometheus"):
            return self.reply(200, {"type": "prometheus", "uid": "vm"})
        if self.path.startswith(("/api/datasources/uid/", "/api/datasources/name/")):
            return self.reply(404, {})
        if self.path.startswith("/api/search"):
            return self.reply(200, [])
        if self.path.startswith("/api/dashboards/uid/nope"):
            return self.reply(404, {"message": "Dashboard not found"})
        if self.path.startswith("/api/dashboards/uid/"):
            return self.reply(200, {"meta": {"folderUid": "fold1"}, "dashboard": {
                "uid": "u", "title": "Данные", "version": 9, "panels": [
                    {"id": 1, "type": "table", "targets": [{"refId": "A", "rawSql": "SELECT '\\{' AS x"}]},
                    {"id": 2, "type": "row", "collapsed": True, "panels": [
                        {"id": 3, "type": "text", "targets": []}]}]}})
        if "/api/v1/query_range" in self.path:
            if "label_replace" in self.path or "bad%28%28" in self.path:
                return self.reply(422, {"status": "error", "errorType": "422", "error": "duplicate output timeseries"})
            return self.reply(200, {"status": "success", "data": {"result": [{"metric": {}, "values": []}]}})
        if "/api/v1/query" in self.path:
            return self.reply(200, {"status": "success", "data": {"result": [{"metric": {"__name__": "up"}, "value": [0, "4"]}]}})
        self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeGrafana.seen.append(("POST", self.path, body))
        if self.path == "/api/ds/query":
            q = body["queries"][0]
            if "noref" in q["rawSql"]:
                return self.reply(400, {"results": {}})
            if "silent500" in q["rawSql"]:
                return self.reply(200, {"results": {q["refId"]: {"status": 500}}})
            if "bad" in q["rawSql"]:
                return self.reply(400, {"results": {q["refId"]: {"error": "syntax error at or near \"bad\"", "status": 400}}})
            return self.reply(200, {"results": {q["refId"]: {"status": 200, "frames": [{
                "schema": {"fields": [{"name": "n", "type": "number"}, {"name": "name", "type": "string"}]},
                "data": {"values": [[11], ["t1"]]}}]}}})
        self.reply(200, {"status": "success", "url": "/d/u/x", "version": 2})


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGrafana)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_env(self, cmd, token):
        env = dict(os.environ, GRAFANA_TOKEN=token)
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

    def dash(self):
        chart = sitrep.history(2, "chart", "", {"h": 4, "w": 16, "x": 8, "y": 0},
                               [sitrep.q("A", 'label_replace(up, "a", "$1", "b", "(.*)")', VM, instant=False)], interval="5m")
        loki = {"id": 3, "type": "logs", "title": "logs", "gridPos": {"h": 4, "w": 8, "x": 0, "y": 4},
                "datasource": {"type": "loki", "uid": "lk"}, "targets": [{"refId": "A", "expr": '{job="x"} |= "err"'}]}
        templ = sitrep.history(4, "templated", "", {"h": 4, "w": 16, "x": 8, "y": 4},
                               [sitrep.q("A", 'up{job="$job"}', VM, instant=False)], interval="5m")
        return {"uid": "u", "panels": [mini_sheet(1, 0), chart, loki, templ]}

    def test_grafana_proxy_and_range_failure(self):
        FakeGrafana.seen = []
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.dash(), f)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "glsa_good")
        self.assertIn("v 4", r.stdout)
        self.assertIn("range target A FAILED", r.stdout)
        self.assertIn("duplicate output timeseries", r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any(p.startswith("/api/datasources/proxy/uid/vm/api/v1/query?") for _, p, _ in FakeGrafana.seen))
        # the Loki panel and the target with an unset $job are not sent to the PromQL API
        self.assertIn("1 failure(s)", r.stdout)
        self.assertFalse(any("lk" in p or "job" in p for _, p, _ in FakeGrafana.seen if isinstance(p, str)))

    def untyped(self):
        mixed = {"id": 5, "type": "timeseries", "title": "mixed", "gridPos": {"h": 4, "w": 8, "x": 0, "y": 8},
                 "datasource": {"type": "datasource", "uid": "-- Mixed --"}, "targets": [{"refId": "A", "uid": "x",
                 "datasource": {"uid": "vm"}, "expr": "bad(("}]}
        legacy = {"id": 6, "type": "graph", "title": "legacy", "gridPos": {"h": 4, "w": 8, "x": 8, "y": 8},
                  "datasource": "Prometheus", "targets": [{"refId": "A", "expr": "bad(("}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"uid": "u", "panels": [mini_sheet(1, 0), mixed, legacy]}, f)
        return f.name

    def test_untyped_datasource_is_resolved_through_grafana(self):
        r = self.run_env([sys.executable, HARNESS, self.untyped(), "--grafana", self.url], "glsa_good")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("[5] mixed: range target A FAILED", r.stdout)
        self.assertIn("[6] legacy: range target A FAILED", r.stdout)

    def test_untyped_datasource_without_grafana_is_unchecked_not_silent(self):
        r = subprocess.run([sys.executable, HARNESS, self.untyped(), self.url + "/api/datasources/proxy/uid/vm"],
                           capture_output=True, text=True, timeout=120)
        self.assertIn("UNCHECKED [5] mixed", r.stdout)
        self.assertIn("2 target(s) UNCHECKED", r.stdout)

    def test_blank_and_hidden_targets_are_not_run(self):
        chart = sitrep.history(2, "chart", "", {"h": 4, "w": 16, "x": 8, "y": 0},
                               [sitrep.q("A", "up", VM, instant=False), sitrep.q("B", "", VM, instant=False),
                                dict(sitrep.q("C", "bad((", VM, instant=False), hide=True)], interval="5m")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"uid": "u", "panels": [mini_sheet(1, 0), chart]}, f)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "glsa_good")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("(range, 6 h): A 1 series", r.stdout)

    def test_grafana_without_a_token_says_so(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GRAFANA_TOKEN")}
        r = subprocess.run([sys.executable, HARNESS, self.untyped(), "--grafana", self.url], capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs a service-account token", r.stderr)

    def test_deploy_network_failure_is_a_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.dash(), f)
        # preflight succeeds here; the dashboard host does not exist, so the failure is the network's
        env = dict(os.environ, GRAFANA_TOKEN="glsa_good")
        code = ("import sys, runpy; sys.path.insert(0, %r); import grafana_api; grafana_api.preflight = lambda b, t: None; "
                "sys.argv = ['deploy.py', %r, 'http://127.0.0.1:9/d/u']; runpy.run_path(%r, run_name='__main__')"
                % (str(SKILL / "scripts"), f.name, str(SKILL / "scripts" / "deploy.py")))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("reading the current dashboard", r.stderr)

    def test_sql_through_grafana(self):
        FakeGrafana.seen = []
        body = ("const t = table('A'); const html = page('01', 'T', brief(t.length ? t[0].name + ' ' + t[0].n : 'none')"
                " + ln('n', t.length ? int(t[0].n) : '—', t.length ? 'ok' : 'nd'));")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"uid": "u", "panels": [sql_sheet(1, 0, body)]}, f)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url, "--var", "schema=prod",
                          "--var", "schema_type=hive"], "glsa_good")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("t1 11", r.stdout)
        q = [b for m, p, b in FakeGrafana.seen if p == "/api/ds/query"][0]["queries"][0]
        self.assertIn("s = 'hive' AND d = 'prod'", q["rawSql"])  # not 'prod_type'
        self.assertEqual(q["datasource"], {"uid": "pg"})
        # the same SQL straight at a Prometheus URL is not run, and says so
        r = subprocess.run([sys.executable, HARNESS, f.name, self.url], capture_output=True, text=True, timeout=60)
        self.assertIn("UNCHECKED [1]", r.stdout)
        self.assertIn("1 target(s) UNCHECKED", r.stdout)

    def test_sql_rejected_by_the_datasource_fails(self):
        s = sql_sheet(1, 0, TWO)
        s["targets"][0]["rawSql"] = "SELECT bad"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"uid": "u", "panels": [s]}, f)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "glsa_good")
        self.assertEqual(r.returncode, 1)
        self.assertIn('target A FAILED: syntax error at or near "bad"', r.stdout)
        for raw, msg in (("SELECT noref", "no result for refId A (HTTP 400)"), ("SELECT silent500", "HTTP 500, no reason given")):
            s["targets"][0]["rawSql"] = raw
            with open(f.name, "w") as g:
                json.dump({"uid": "u", "panels": [s]}, g)
            r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "glsa_good")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(msg, r.stdout)

    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "orig.json")
            cmd = [sys.executable, str(SKILL / "scripts" / "export.py"), self.url + "/d/u/slug?kiosk", "u", str(out)]
            r = self.run_env(cmd, "glsa_good")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("2 panel(s), 1 quer(ies)", r.stdout)
            d = json.loads(out.read_text())
            self.assertEqual(d["panels"][0]["targets"][0]["rawSql"], "SELECT '\\{' AS x")
            self.assertIn("Данные", out.read_text())  # UTF-8, not \\u escapes
            sitrep.expect_original(d, panels=2, queries=1, ends={(1, "A"): "AS x"})
            with self.assertRaises(SystemExit):
                sitrep.expect_original(d, ends={(1, "A"): "AS y"})
            with self.assertRaises(SystemExit):
                sitrep.expect_original(d, panels=3)
            r = self.run_env(cmd, "glsa_good")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("--force", r.stderr)
            r = self.run_env(cmd[:-2] + ["nope", str(Path(tmp, "x.json"))], "glsa_good")
            self.assertIn("no such uid", r.stderr)

    def test_redirect_without_a_token_is_followed(self):
        req = urllib.request.Request(self.url + "/hop")
        with self.assertRaises(urllib.error.URLError) as e:  # followed to evil.invalid, which does not resolve
            grafana_api.urlopen(req, timeout=5)
        self.assertNotIn("refused", str(e.exception))

    def test_redirect_is_not_followed_with_the_token(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.dash(), f)
        r = self.run_env([sys.executable, str(SKILL / "scripts" / "deploy.py"), f.name, self.url + "/hop"], "glsa_good")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused, the token would follow", r.stderr)

    def test_wrong_token_is_named(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.dash(), f)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "gateway-token")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT a Grafana service-account token", r.stderr)
        self.assertNotIn("gateway-token", r.stderr)
        self.assertIn("host tried:   127.0.0.1:", r.stderr)
        self.assertIn("token from:   GRAFANA_TOKEN", r.stderr)
        r = self.run_env([sys.executable, HARNESS, f.name, "--grafana", self.url], "glsa_other_instance")
        self.assertIn("token prefix: glsa_", r.stderr)
        self.assertIn("not that instance", r.stderr)

    def test_deploy_keeps_the_folder(self):
        FakeGrafana.seen = []
        d = copy.deepcopy(self.dash())
        d["id"] = 42
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(d, f)
        r = self.run_env([sys.executable, str(SKILL / "scripts" / "deploy.py"), f.name, self.url + "/d/u/x?kiosk"], "glsa_good")
        self.assertEqual(r.returncode, 0, r.stderr)
        post = [b for m, p, b in FakeGrafana.seen if m == "POST"][0]
        self.assertEqual((post["folderUid"], post["overwrite"], post["dashboard"]["id"], post["dashboard"]["uid"]),
                         ("fold1", True, None, "u"))


if __name__ == "__main__":
    unittest.main()
