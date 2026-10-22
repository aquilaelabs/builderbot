"""A patch line's own rules (R112 step 5): a house rule named patch, or
patch-SOMETHING, says in its files what a patch release may not change, and
the check preflight runs on a patch line fails on a changed file under it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

CHECK = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "rules-check.py")
RULES = [{"name": "patch", "paths": ["scripts/dashboard/statemigrations"], "text": "A patch adds no migration."},
         {"name": "patch-api", "paths": ["docs/api.md"], "text": "A patch keeps the API."},
         {"name": "tests", "paths": ["scripts"], "text": "not a patch rule"}]


def run(files, rules=RULES):
    tree = tempfile.mkdtemp()
    r = subprocess.run([sys.executable, CHECK, tree, "--patch", *files], capture_output=True, text=True,
                       env=dict(os.environ, RULES_JSON=json.dumps(rules)))
    os.rmdir(tree)
    return r.returncode, r.stdout


class Patch(unittest.TestCase):
    def test_a_change_under_a_patch_rule_fails_naming_it(self):
        code, out = run(["scripts/dashboard/statemigrations/0004_x.py", "scripts/bb"])
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL  patch: a patch line may not change scripts/dashboard/statemigrations/0004_x.py", out)
        self.assertIn("PASS  patch-api", out)
        self.assertNotIn("tests", out, "only the patch rules are this check's")

    def test_clean_passes_and_none_says_how_to_add_one(self):
        self.assertEqual(run(["scripts/bb"])[0], 0)
        code, out = run(["scripts/bb"], rules=[])
        self.assertEqual(code, 0)
        self.assertIn("no patch rule here", out)


if __name__ == "__main__":
    unittest.main()
