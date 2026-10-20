"""bb map unused over python too (11 Oct): it measured the page's functions
alone and answered "nothing on the page is unused" for a python file, which
hid two dead functions. A python function counts as unused only when its
name appears nowhere in the tree but its definition, and never when a
decorator registers it (Flask's routes and hooks, MediaReducer's app.py)."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402


class Unused(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "app.py").write_text(
            "import flask\napp = flask.Flask(__name__)\n\n\n"
            "@app.route('/')\ndef home():\n    return used()\n\n\n"
            "def used():\n    return 1\n\n\n"
            "def dead_one():\n    return 2\n\n\n"
            "ROUTES = {'x': 'named_in_a_string'}\n\n\n"
            "def named_in_a_string():\n    return 3\n")
        f = "app.py"
        defs = [{"file": f, "name": n, "line": ln, "kind": "def"}
                for n, ln in (("home", 6), ("used", 10), ("dead_one", 14), ("named_in_a_string", 21))]
        self.idx = {"files": {f: {"lang": "python", "defs": defs, "refs": {}}}, "defs": defs,
                    "calls": [{"name": "used", "file": f}], "draws": []}

    def test_a_dead_python_function_is_named_and_the_reached_ones_are_not(self):
        out = "\n".join(codemap.q_unused(self.idx, None, str(self.root)))
        self.assertIn("app.py:14  dead_one", out)
        for n in ("home", "used", "named_in_a_string"):
            self.assertNotIn(f"  {n}", out, f"{n} is reached: decorated, called, or named in a string")

    def test_a_clean_python_file_says_python_not_page(self):
        (self.root / "app.py").write_text((self.root / "app.py").read_text().replace("def dead_one():\n    return 2\n", ""))
        self.idx["files"]["app.py"]["defs"] = [d for d in self.idx["defs"] if d["name"] != "dead_one"]
        self.assertEqual(codemap.q_unused(self.idx, "app.py", str(self.root)),
                         ["nothing in this python module is unused by this measure (app.py)"])


class UnusedClasses(unittest.TestCase):
    """bb map unused over a page's stylesheet (B79): R60 swept the classes
    nothing names and took .gl0 to .gl4, which nb-git.js builds as
    gl${lane % 5}, for dead. A template's head or tail names a family."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "index.html").write_text(
            "<style>\n.gl0{stroke:red} .gl4{stroke:blue}\n.sk-word{x:1}\n.fxtab .row{y:2}\n"
            "@media (max-width:600px){.gone{z:3} .used{z:4}}\n</style>\n<div class=\"used row\"></div>\n")
        (self.root / "page.js").write_text(
            "const a = `<path class=\"gl${lane % 5}\"/>`;\n"
            "const b = `<i class=\"loading sk-${shape}\">`;\n"
            "const c = `<div class=\"doctab ${kind}tab\">`;\n")
        (self.root / "test").mkdir()
        (self.root / "test" / "x.mjs").write_text("page.$('.gone')\n")
        files = {"index.html": {"lang": "html", "defs": [], "refs": {}},
                 "page.js": {"lang": "js", "defs": [], "refs": {}},
                 "test/x.mjs": {"lang": "js", "defs": [], "refs": {}}}
        self.idx = {"files": files, "defs": [], "calls": [], "draws": []}

    def test_a_template_built_class_is_used_and_a_dead_one_is_named(self):
        self.assertEqual(codemap.unused_classes(self.idx, None, str(self.root)), [("index.html", "gone")],
                         "gl0 and gl4 by their head, sk-word likewise, fxtab by its tail; a suite naming .gone does not render it")
        out = "\n".join(codemap.q_unused(self.idx, "index.html", str(self.root)))
        self.assertIn("index.html  .gone", out)
        self.assertNotIn(".gl0", out)

    def test_the_git_graph_lanes_are_styled_and_not_read_as_dead(self):
        repo = Path(__file__).resolve().parents[3]
        html = (repo / "scripts/dashboard/index.html").read_text()
        for n in range(5):
            self.assertRegex(html, rf"\.gl{n}\{{stroke:var\(--", f".gl{n} gives lane {n} its color")
        idx = {"files": {f: {} for f in ("scripts/dashboard/index.html", "scripts/dashboard/nb-git.js")}}
        self.assertFalse([c for _, c in codemap.unused_classes(idx, None, str(repo)) if c.startswith("gl")])


if __name__ == "__main__":
    unittest.main()
