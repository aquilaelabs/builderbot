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


if __name__ == "__main__":
    unittest.main()
