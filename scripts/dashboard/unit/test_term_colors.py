"""A terminal's look keeps each scheme's colors as a person changed them
(R133, the operator, 25 Oct): by scheme, each a terminal color's name and a
#rrggbb, anything else dropped rather than kept."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import users  # noqa: E402


class Colors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        users.configure(state=self.tmp, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
        with users._lock:
            d = users.load()
            d["users"]["pat"] = {"uid": "u_00000001", "role": "admin", "projects": [], "password": "x",
                                 "created": 0, "seen": 0}
            users._save(d)

    def test_each_schemes_colors_are_kept_named_and_checked(self):
        got, st = users.own_prefs("pat", {"term": {"scheme": "amber", "colors": {
            "amber": {"background": "#102030", "brightRed": "#FF0000", "evil": "#000000", "cursor": "red;rm"},
            "nosuch": {"background": "#000000"}, "red": "not a dict"}}})
        self.assertEqual(st, 200, got)
        look = users.prefs(users.get("pat"))["term"]
        self.assertEqual(look["scheme"], "amber")
        self.assertEqual(look["colors"], {"amber": {"background": "#102030", "brightRed": "#ff0000"}})

    def test_reset_is_a_scheme_taken_away(self):
        users.own_prefs("pat", {"term": {"scheme": "blue", "colors": {"blue": {"foreground": "#abcdef"}}}})
        users.own_prefs("pat", {"term": {"scheme": "blue", "colors": {}}})
        self.assertEqual(users.prefs(users.get("pat"))["term"]["colors"], {})


if __name__ == "__main__":
    unittest.main()
