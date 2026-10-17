"""bb map find names a value declared in a file of the index when no
function or type has the name (report #66, B527): a Kotlin table in a
companion object, a python module's constant, a shell variable."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("codemap", os.path.join(HERE, "..", "..", "lib", "codemap.py"))
codemap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codemap)

FILES = {
    "app/BarModels.kt": "class Bar {\n    companion object {\n        val ACTIONS: Map<String, String> = linkedMapOf(\n        )\n    }\n}\n",
    "lib/toolchains.py": "import os\n\nTC_CHECK_EVERY = 7 * 86400\nif TC_CHECK_EVERY == 1:\n    pass\n",
    "bin/run.sh": "#!/bin/sh\nexport SUITE_TIMEOUT=1500\n",
}


class ValueDecls(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for f, text in FILES.items():
            (self.root / f).parent.mkdir(parents=True, exist_ok=True)
            (self.root / f).write_text(text)
        self.idx = {"defs": [], "files": {"app/BarModels.kt": {"lang": "js"},
                                          "lib/toolchains.py": {"lang": "py"},
                                          "bin/run.sh": {"lang": "sh"}}}

    def find(self, name):
        return codemap.q_find(self.idx, name, root=self.root)

    def test_a_kotlin_property_in_a_companion_object(self):
        self.assertEqual(self.find("ACTIONS"), ["app/BarModels.kt:3  declared as a value"])

    def test_a_python_module_constant_and_not_its_comparison(self):
        self.assertEqual(self.find("TC_CHECK_EVERY"), ["lib/toolchains.py:3  declared as a value"])

    def test_a_shell_variable(self):
        self.assertEqual(self.find("SUITE_TIMEOUT"), ["bin/run.sh:2  declared as a value"])

    def test_still_nothing_for_a_name_nobody_declares(self):
        self.assertEqual(self.find("NOWHERE"), ["nothing defines NOWHERE"])


class ABundleIsNotRead(unittest.TestCase):
    """B804: a name nothing defines was looked for as a page-level let in
    every page script, a one-line bundle the index skips among them, and
    code_only over Shebang-DevBoard's 290 kB xterm.js took fifty seconds."""

    def test_a_minified_page_script_is_skipped_at_once(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "web").mkdir()
        (root / "web" / "page.js").write_text("let shown = 1;\n")
        (root / "web" / "xterm.js").write_text("let lost=1;" + "var a=1;function b(){return a/2}" * 9000 + "\n")
        idx = {"defs": [], "files": {"web/page.js": {"lang": "js"}, "web/xterm.js": {"lang": "js"}}}
        self.assertEqual(codemap.script_bodies(root, "web/xterm.js"), [])
        self.assertEqual([f for f, _, _ in codemap.page_bindings(idx, root, "shown")], ["web/page.js"])
        self.assertEqual(codemap.page_bindings(idx, root, "lost"), [])


class TheSummary(unittest.TestCase):
    """B806: the summary counted every file the brace scanner reads as js,
    so a Kotlin tree read as 44 js, and named a file it could not write."""

    def test_counted_by_extension_and_said_unkept_when_it_was_not_written(self):
        idx = {"files": {"a/Main.kt": {"lang": "js"}, "a/Other.kt": {"lang": "js"},
                         "build.gradle.kts": {"lang": "js"}, "gradlew": {"lang": "sh"}},
               "defs": [], "calls": [], "draws": [], "built": 0, "scanned": 4, "kept": False}
        first, kept = codemap.summary(idx)[:2]
        self.assertTrue(first.startswith("4 files (2 kt, 1 kts, 1 sh;"), first)
        self.assertIn("in memory", kept)
        idx["kept"] = True
        self.assertIn("into .bb-map/", codemap.summary(idx)[1])


if __name__ == "__main__":
    unittest.main()
