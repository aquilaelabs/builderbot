"""BuilderBot's own terminal (R133 step 6) is on unless switched off: a
fresh install reads it on, and it is a setting of its own, no longer a dev
switch that a controller without DEBUG_MODE puts back off."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402


class OwnTerminal(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        settings.configure(write_json=lambda p, d: Path(p).write_text(json.dumps(d)), state=self.d)

    def test_a_fresh_install_has_it_on(self):
        self.assertIs(settings.get("own_terminal"), True)

    def test_it_is_not_a_debug_switch(self):
        self.assertNotIn("own_terminal", settings.DEBUG_KEYS)
        Path(self.d, "settings.json").write_text(json.dumps({"own_terminal": False}))
        settings.reset_debug()
        self.assertIs(settings.get("own_terminal"), False, "switched off stays off, debug or not")


if __name__ == "__main__":
    unittest.main()
