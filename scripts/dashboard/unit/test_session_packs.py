"""A session asks for a tool pack from the vetted catalog (R169 step 5): the
project's Install a tool pack dial (ask by default) kept as the others are,
the briefing naming the catalog and the dial, an ask held for the
administrators with the index's pin, and bb tool's own words kept out of a
pack's name."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402
import preamble  # noqa: E402
import prefs  # noqa: E402
import toolpacks  # noqa: E402


class SessionPacks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "ws" / "alpha").mkdir(parents=True)
        prefs.configure(state=self.tmp, write_json=lambda p, d: Path(p).write_text(json.dumps(d)))

    def test_the_dial_is_ask_unless_set(self):
        self.assertEqual(prefs.get("alpha")["installpacks"], "ask")
        self.assertIn("error", prefs.set_prefs("alpha", installpacks="maybe"))
        prefs.set_prefs("alpha", installpacks="deny")
        self.assertEqual(prefs.get("alpha")["installpacks"], "deny")
        prefs.set_prefs("alpha", installpacks="ask")
        self.assertNotIn("installpacks", prefs._load()["projects"].get("alpha", {}), "the default is not written")

    def test_the_briefing_names_the_catalog_and_the_dial(self):
        was = preamble.prefs_mod
        preamble.prefs_mod = prefs
        self.addCleanup(setattr, preamble, "prefs_mod", was)
        prefs.set_prefs("alpha", installpacks="deny")
        line = preamble.packs_line("alpha")
        self.assertIn("bb tool search WORDS", line)
        self.assertIn("Install a tool pack is deny", line)

    def test_an_ask_is_held_with_the_pin(self):
        entry = {"name": "hexkit", "url": "https://example.com/hex", "commit": "a" * 40, "sha256": "b" * 64, "path": "", "tier": "vetted"}
        self.assertIn("error", phone.ask_pack("", "alpha", entry))
        r = phone.ask_pack("to read firmware dumps", "alpha", entry, asker_name="ann")
        self.assertTrue(r.get("ok"))
        held = next(x for x in phone._reqs if x["id"] == r["id"])
        self.assertEqual((held["kind"], held["pack"]["commit"], held["cmd"]), ("pack", "a" * 40, ["tool", "install", "hexkit"]))

    def test_bb_tools_own_words_are_not_pack_names(self):
        m, errs = toolpacks.validate({"name": "install", "label": "x", "platforms": ["linux/amd64"],
                                      "verbs": {"go": {"run": ["{dir}/x"]}}})[:2]
        self.assertTrue(any("bb tool's own words" in e for e in errs), errs)


class Touches(unittest.TestCase):
    """R169 step 4: a pack says what it touches, the hosts its install
    fetches from and whether it needs root; Look shows both, and one that
    needs root is an administrator's to add."""
    def test_touches_is_held_to_its_shape(self):
        base = {"name": "hexkit", "label": "Hex", "platforms": ["linux/amd64"], "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
                "verbs": {"dump": {"run": ["{dir}/bin/hexkit"]}}}
        m, errs = toolpacks.validate(dict(base, touches={"hosts": ["github.com", "dl.example.org"], "root": True}))
        self.assertEqual(m["touches"], {"hosts": ["github.com", "dl.example.org"], "root": True})
        _, errs = toolpacks.validate(dict(base, touches={"hosts": ["https://x"], "root": "yes"}))
        self.assertTrue(any("touches.hosts" in e for e in errs) and any("touches.root" in e for e in errs), errs)
        m, _ = toolpacks.validate(base)
        self.assertEqual(m["touches"], {"hosts": [], "root": False})

if __name__ == "__main__":
    unittest.main()
