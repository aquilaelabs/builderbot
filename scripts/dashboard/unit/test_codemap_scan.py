"""bb map's scanners against what the tree really holds: the JS scanner's
words are JavaScript's own, an expression arrow is a function that ends
where its expression does and holds its calls, a shell function ends at
its own `}` and calls what the files around it define, quoted shell text
calls nothing, a selector is read part by part (B576), a file of closures
lists them (B577), and Astro, Vue and Svelte files are read (B578)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402


def scan(text, path="a.js"):
    sink = codemap.Sink(path)
    {".sh": codemap.scan_sh, ".py": codemap.scan_python}.get(
        Path(path).suffix, codemap.scan_html if Path(path).suffix in (".html", ".astro") else codemap.scan_js)(text, sink)
    return sink


def defs(sink):
    return {(d["name"], d["line"], d["end"]) for d in sink.defs}


def calls(sink):
    return {(c["name"], c["line"], c["caller"]) for c in sink.calls}


class JavaScript(unittest.TestCase):
    def test_another_languages_words_are_names_here(self):
        s = scan("function open(x){ return select(x); }\nconst when = t => t;\nopen(1);\n")
        self.assertIn(("open", 1, 1), defs(s))
        self.assertIn(("when", 2, 2), defs(s))
        self.assertIn(("select", 1, "open"), calls(s))

    def test_a_property_called_interface_is_no_class(self):
        s = scan("function f(net, rn){\n  if (net.interface && rn.interface) g();\n"
                 "  const x = {interface: '', routes: []};\n}\n")
        self.assertEqual({d["name"] for d in s.defs}, {"f"})

    def test_an_async_arrow_is_named_for_what_it_is_assigned_to(self):
        s = scan("function f(){\n  const send = async () => {\n    post();\n  };\n}\n")
        self.assertIn(("send", 2, 4), defs(s))
        self.assertIn(("post", 3, "send"), calls(s))

    def test_an_expression_arrow_ends_with_its_expression_and_holds_its_calls(self):
        s = scan("const pick = (a, b) => [a, b]\n  .map(x => fmt(x))\n  .join(',');\n"
                 "const t = {render: (el) => draw(el), open: () => load()};\n")
        self.assertIn(("pick", 1, 3), defs(s))
        self.assertIn(("fmt", 2, "pick"), calls(s))
        self.assertIn(("draw", 4, "render"), calls(s))
        self.assertIn(("load", 4, "open"), calls(s))

    def test_a_keyword_method_and_a_spaced_function_expression(self):
        s = scan("class A {\n  async delete(uri) {\n    go(uri);\n  }\n"
                 "  m() { try { x(); } catch (e) { y(); } }\n}\nModule._load = function (req) {\n  return 1;\n};\n")
        self.assertTrue({("delete", 2, 4), ("m", 5, 5), ("_load", 7, 9)} <= defs(s), defs(s))
        self.assertNotIn("catch", {d["name"] for d in s.defs})
        self.assertIn(("go", 3, "delete"), calls(s))

    def test_a_comment_above_a_method_does_not_hide_it(self):
        s = scan("const o = {\n  a: 1,\n  // says what shown does, at length\n  shown(){ go(); },\n};\n")
        self.assertIn(("shown", 4, 4), defs(s))

    def test_a_call_in_a_condition_is_no_method(self):
        s = scan("function f(){\n  if (stage(id, clean(v))){\n    x();\n  }\n}\n")
        self.assertNotIn("clean", {d["name"] for d in s.defs})
        self.assertIn(("clean", 2, "f"), calls(s))

    def test_optional_and_keyword_named_calls_are_calls(self):
        s = scan("function f(k){\n  KINDS[k]?.open?.(k);\n  p.catch(e => 0).finally(done);\n"
                 "  for (const x of (list || [])) use(x);\n}\n")
        names = {c["name"] for c in s.calls}
        self.assertTrue({"open", "catch", "finally", "use"} <= names, names)
        self.assertNotIn("of", names)

    def test_php_closures_are_listed_with_what_they_are_handed_to(self):
        text = "<?php\nadd_action('init', function () {\n  x();\n});\nadd_filter('a', fn() => 'closed');\n"
        with tempfile.TemporaryDirectory() as d:
            Path(d, "f.php").write_text(text)
            idx = codemap.build(d)
            out = codemap.q_defs(idx, "f.php")
        self.assertEqual(out, ["2-4  function (anonymous) passed to add_action",
                               "5  function (anonymous) passed to add_filter"])


class OtherProjects(unittest.TestCase):
    """What running the map over every project this one reads found."""

    def test_typescript_return_types_generics_and_jsx_text(self):
        s = scan("export const add = (a: Vec, b: Vec): Vec => a.map(f);\n"
                 "class S {\n  private bound(b: Vec, arts: (number | null)[]): [number, number] {\n"
                 "    const m = new Map<number, Set<number>>();\n  }\n}\n"
                 "function prep(i: In): { a: A[]; b: B } {\n  go();\n}\n"
                 "function C() {\n  return <p>it isn't set, 3 class-item mods</p>;\n}\n"
                 "function D() {\n  return <td>{p ? <S x={1} /> : '-'}</td>;\n}\n", "a.tsx")
        got = defs(s)
        for want in [("add", 1, 1), ("bound", 3, 5), ("prep", 7, 9), ("C", 10, 12), ("D", 13, 15)]:
            self.assertIn(want, got)
        self.assertNotIn("item", {d["name"] for d in s.defs})
        self.assertIn(("Map", 4, "bound"), calls(s))

    def test_a_private_method_and_a_destructured_constructor(self):
        s = scan("class G {\n  /**\n   * doc\n   */\n  constructor({ now = Date.now } = {}) {\n"
                 "    this.#drift();\n  }\n  #drift() { x(); }\n  say(a, extra = {}) { y(); }\n}\n")
        self.assertTrue({("constructor", 5, 7), ("drift", 8, 8), ("say", 9, 9)} <= defs(s), defs(s))

    def test_kotlin_names_its_function_whatever_another_language_calls_the_word(self):
        s = scan("class A {\n  fun record(x: Int) {\n  }\n  override fun open(): Boolean {\n    return true\n  }\n"
                 "  fun of(id: Int): String {\n    return \"\"\n  }\n"
                 "  private fun <T> List<T>.move(a: Int): List<T> {\n    return this\n  }\n"
                 "  fun pair(): Pair<Uri, String>? {\n    return null\n  }\n}\n"
                 "interface V {\n  fun onText(t: String)\n}\n", "A.kt")
        got = {(n, a, b) for n, a, b in defs(s)}
        for want in [("record", 2, 3), ("open", 4, 6), ("of", 7, 9), ("move", 10, 12), ("pair", 13, 15),
                     ("onText", 18, 18)]:
            self.assertIn(want, got)

    def test_event_attributes_class_lists_and_named_iifes(self):
        text = ('<button onclick="jump(\'errors\'); other()">x</button>\n<script>\n'
                "function jump(w){ el.classList.toggle('ghost', on); el.className = 'btn ' + (d ? 'red' : 'blue'); }\n"
                "function other(){}\n(function initGuide() { boot(); })();\n</script>\n")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "p.html").write_text(text)
            Path(d, "vendor.js").write_text("var a=1;" * 4000)
            idx = codemap.build(d)
            self.assertIn(("jump", "(markup)"), {(c["name"], c["caller"]) for c in idx["calls"]})
            self.assertIn(("other", "(markup)"), {(c["name"], c["caller"]) for c in idx["calls"]})
            drawn = {d_["what"] for d_ in idx["draws"] if d_["kind"] == "class"}
            self.assertTrue({"ghost", "btn", "red", "blue"} <= drawn, drawn)
            self.assertEqual(codemap.q_unused(idx), ["nothing in this page or python module is unused by this measure"])
            self.assertEqual(idx["files"]["vendor.js"]["defs"], [])

    def test_tests_by_their_directory_and_suites_through_an_import(self):
        self.assertTrue(codemap.is_test("tests/e2e/e2e_runlock.mjs"))
        self.assertFalse(codemap.is_test("tests/e2e/helpers.mjs"))
        self.assertEqual(codemap.strings_draw("progress.json"), [])
        with tempfile.TemporaryDirectory() as d:
            Path(d, "public").mkdir()
            Path(d, "tests").mkdir()
            Path(d, "public/engine.js").write_text("function step(){}\nmodule.exports = {step};\n")
            Path(d, "tests/engine.test.js").write_text("const E = require('../public/engine.js');\nE.step();\n")
            idx = codemap.build(d)
            self.assertEqual(codemap.q_suites(idx, ["public/engine.js"]),
                             ["tests/engine.test.js  (1: public/engine.js)"])


class Caution(unittest.TestCase):
    """The answers a session deletes by say to grep first, and a plan says
    how much of it the map guessed (the operator, 8 Oct)."""

    def test_nothing_calls_and_unused_say_grep_first(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "p.js").write_text("function lonely(){}\n")
            idx = codemap.build(d)
            said = codemap.q_who_calls(idx, "lonely", d)
            self.assertTrue(said[0].startswith("nothing calls lonely"))
            self.assertIn("grep -rn lonely before deleting", said[1])
            self.assertIn("grep each before deleting", codemap.q_unused(idx)[0])

    def test_a_plan_says_what_it_measured_and_what_the_map_guessed(self):
        self.assertEqual(codemap.account_line({"measured": 3, "callers": 1, "file": 0, "by_name": []}),
                         "suites: 3 of 4 changed functions placed by what a covered run measured, "
                         "1 through their callers in the map")
        line = codemap.account_line({"measured": 0, "callers": 0, "file": 2, "by_name": ["a.py"]})
        self.assertIn("a.py no covered run has seen, so planned by the map's reading alone", line)
        self.assertEqual(codemap.account_line({"measured": 0, "callers": 0, "file": 0, "by_name": []}), "")


class Shadowing(unittest.TestCase):
    """A parameter, a local or a named argument that takes a function's name
    is not that function passed by name (B590, report #95)."""

    def test_parameters_locals_and_named_arguments_do_not_pass_the_function(self):
        src = ("object G {\n    fun reach(s: FloatArray?): Float = 1f\n"
               "    fun add(outcome: Int, reach: Float = -1f) {\n        if (reach >= 0f) { x(reach) }\n    }\n"
               "    fun t() {\n        val reach = s[1]\n        y(reach)\n        add(1, reach = 0.6f)\n"
               "    }\n    fun u() = list.map(::reach)\n}\n")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "G.kt").write_text(src)
            idx = codemap.build(d)
            got = [line for line in codemap.q_who_calls(idx, "reach", d) if line.startswith("G.kt:")]
            self.assertEqual(len(got), 1, got)          # only u's ::reach, the reference itself
            self.assertIn(":11 ", got[0])

    def test_a_const_arrow_is_still_the_function_its_name_says(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.js").write_text("function load(){\n  const rowFor = (x) => {\n    return x;\n  };\n"
                                        "  return list.map(rowFor);\n}\nload();\n")
            idx = codemap.build(d)
            self.assertEqual(codemap.q_unused(idx), ["nothing in this page or python module is unused by this measure"])


class Fingerprint(unittest.TestCase):
    def test_the_scanners_version_is_this_files_own_fingerprint(self):
        import hashlib
        self.assertEqual(codemap.SCANNER,
                         hashlib.sha1(Path(codemap.__file__).read_bytes()).hexdigest()[:12])
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.py").write_text("def f():\n    pass\n")
            idx = codemap.build(d)
            self.assertEqual({e["scan"] for e in idx["files"].values()}, {codemap.SCANNER})


class SecondPass(unittest.TestCase):
    """The second pass over every read project (8 Oct)."""

    def test_an_extension_on_a_generic_type_with_two_parameters(self):
        s = scan("object R {\n    private fun Map<String, Any?>.long(k: String): Long? = when (val v = this[k]) {\n"
                 "        else -> null\n    }\n}\n", "R.kt")
        self.assertIn(("long", 2, 4), defs(s))
        s = scan("function pair<A, B>(a: A, b: B): [A, B] {\n  return [a, b];\n}\n", "a.ts")
        self.assertIn(("pair", 1, 3), defs(s))

    def test_a_method_is_never_called_unused(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "fs.js").write_text("class FS {\n  createDirectory(u) {\n    return u;\n  }\n}\nregister(new FS());\n")
            self.assertEqual(codemap.q_unused(codemap.build(d)), ["nothing in this page or python module is unused by this measure"])

    def test_two_files_importing_one_module_are_not_each_others_suites(self):
        with tempfile.TemporaryDirectory() as d:
            for f, t in {"src/solver.ts": "export function solve() {}\n",
                         "src/App.tsx": "import { solve } from './solver';\nexport function App() { solve(); }\n",
                         "src/solver.test.ts": "import { solve } from './solver';\nsolve();\n"}.items():
                Path(d, f).parent.mkdir(parents=True, exist_ok=True)
                Path(d, f).write_text(t)
            idx = codemap.build(d)
            self.assertEqual(codemap.q_suites(idx, ["src/App.tsx"]), ["no suite names anything these files define or draw"])
            self.assertTrue(codemap.q_suites(idx, ["src/solver.ts"])[0].startswith("src/solver.test.ts"))


class ThirdPass(unittest.TestCase):
    """The third pass (9 Oct)."""

    def test_a_suite_reaches_the_pages_globals_not_a_local_of_the_same_name(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "page.js").write_text("function draw(){\n  const done = () => 1;\n  done();\n}\n"
                                          "function openTab(){}\n")
            Path(d, "test").mkdir()
            Path(d, "test/a.mjs").write_text("import { done } from './lib.mjs';\nopenTab();\ndone();\n")
            Path(d, "test/b.mjs").write_text("import { done } from './lib.mjs';\ndone();\n")
            idx = codemap.build(d)
            self.assertEqual(codemap.q_suites(idx, ["page.js"]), ["test/a.mjs  (1: openTab())"])


class FourthPass(unittest.TestCase):
    """The fourth pass (9 Oct)."""

    def test_a_parameters_default_is_not_a_definition(self):
        s = scan('function pick(id, why = () => "") {\n  return why(id);\n}\n'
                 "function mock({ token = 1, now = () => Date.now() } = {}) {}\n"
                 "const f = (a, cb = async () => 0) => cb(a);\n", "a.js")
        self.assertEqual({d[0] for d in defs(s)} - {"(anonymous)"}, {"pick", "mock", "f"})

    def test_a_call_in_a_template_in_a_default_is_the_functions(self):
        # B761: `${Math.round(v)}` in a default parameter's arrow was read as
        # called from the scope around the function, at file scope and inside
        # another function alike; a call outside a template there already was f's.
        s = scan("function chart(id, fmt = v => `${Math.round(v)}%`){\n  return fmt(id);\n}\n"
                 "function outer(){\n  function inner(x, say = n => `${String(n)}`){ return say(x); }\n}\n", "a.js")
        got = {(c["name"], c["caller"]) for c in s.calls}
        self.assertIn(("round", "chart"), got)
        self.assertIn(("String", "inner"), got)
        self.assertNotIn(("round", "(top level)"), got)

    def test_a_suite_naming_a_directory_reaches_the_files_in_it(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "scripts/inner").mkdir(parents=True)
            Path(d, "scripts/inner/mod.py").write_text("def work():\n    return 1\n")
            Path(d, "test").mkdir()
            Path(d, "test/a.mjs").write_text("const P = 'scripts/inner';\n")
            Path(d, "test/b.mjs").write_text("const Q = 'scripts/innerness';\n")
            idx = codemap.build(d)
            self.assertEqual(codemap.q_suites(idx, ["scripts/inner/mod.py"]), ["test/a.mjs  (1: scripts/inner/)"])

    def test_a_section_under_a_bare_rule_is_read(self):
        s = scan("# " + "-" * 40 + "\n# the connection\n\nX = 1\n# " + "-" * 40 + "\n# jobs\n", "a.py")
        self.assertEqual([(x["name"], x["line"]) for x in s.sections], [("the connection", 1), ("jobs", 5)])

    def test_a_handler_or_a_stand_in_inside_a_call_still_is(self):
        s = scan("rows.forEach(b => b.onclick = () => go(b));\n"
                 "page.evaluate(() => { draw = () => { boom(); }; });\n", "a.js")
        names = {d[0] for d in defs(s)}
        self.assertTrue({"onclick", "draw"} <= names, names)
        self.assertIn(("go", 1, "onclick"), calls(s))


class Shell(unittest.TestCase):
    def test_a_nested_function_ends_at_its_own_brace(self):
        s = scan("outer() {\n    inner() {\n        die x\n    }\n    inner\n}\n", "a.sh")
        self.assertEqual(defs(s), {("outer", 1, 6), ("inner", 2, 4)})
        self.assertIn(("inner", 5, "outer"), calls(s))

    def test_quoted_text_calls_nothing_and_a_trap_does(self):
        s = scan('log() { :; }\nrun() { :; }\nf() {\n    log "run this: $(run)"\n'
                 "    echo 'log it'\n    trap 'log' EXIT\n}\n", "a.sh")
        got = {(c["name"], c["line"]) for c in s.calls if c["caller"] == "f"}
        self.assertEqual(got, {("log", 4), ("run", 4), ("log", 6)})

    def test_a_script_calls_what_it_sources_and_a_library_what_sources_it(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "lib").mkdir()
            Path(d, "lib/common.sh").write_text("die() { exit 1; }\n")
            Path(d, "lib/util.sh").write_text("helper() {\n    die nope\n}\n")
            Path(d, "tool").write_text('#!/bin/bash\n. "$(dirname "$0")/lib/common.sh"\n'
                                       '. "$(dirname "$0")/lib/util.sh"\nhelper || die "no"\n')
            idx = codemap.build(d)
            got = {(c["file"], c["name"]) for c in idx["calls"]}
            self.assertIn(("tool", "die"), got)
            self.assertIn(("tool", "helper"), got)
            self.assertIn(("lib/util.sh", "die"), got)
            # a function added to the library is seen called without the
            # script changing
            Path(d, "lib/common.sh").write_text("die() { exit 1; }\nwarn() { :; }\n")
            Path(d, "tool").touch()
            os.utime(Path(d, "lib/common.sh"), (1, 1))
            Path(d, "lib/util.sh").write_text("helper() {\n    warn nope\n}\n")
            idx = codemap.load(d)
            self.assertIn(("lib/util.sh", "warn"), {(c["file"], c["name"]) for c in idx["calls"]})


class Markup(unittest.TestCase):
    def test_a_selector_is_read_part_by_part_and_not_inside_a_value(self):
        self.assertEqual(codemap.strings_draw('a.al-skip[href="#main"]'), [("al-skip", "class")])
        self.assertEqual(codemap.strings_draw("div#x.y > span.k"),
                         [("x", "id"), ("y", "class"), ("k", "class")])
        self.assertEqual(codemap.strings_draw("index.html"), [])

    def test_an_extension_in_python_is_no_class_and_a_file_named_whole_is_named(self):
        s = scan('EXT = ".c"\nPATH = "builderbot-agent.py"\n', "m.py")
        self.assertEqual({(d["what"], d["kind"]) for d in s.draws}, {("builderbot-agent.py", "file")})

    def test_an_astro_component_is_read_with_its_frontmatter(self):
        s = scan("---\nconst t = title();\n---\n<a class=\"al-skip\" href=\"#main\">x</a>\n"
                 "<script>\nfunction go(){ run(); }\n</script>\n", "B.astro")
        self.assertIn(("title", 2, "(top level)"), calls(s))
        self.assertIn(("go", 6, 6), defs(s))
        self.assertIn(("al-skip", "class"), {(d["what"], d["kind"]) for d in s.draws})

    def test_an_empty_answer_names_what_the_map_does_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "site.css").write_text(".x{}")
            self.assertEqual(codemap.not_read_note(d),
                             ["(not indexed here, so not in that answer: 1 .css; grep them)"])


if __name__ == "__main__":
    unittest.main()
