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


if __name__ == "__main__":
    unittest.main()
