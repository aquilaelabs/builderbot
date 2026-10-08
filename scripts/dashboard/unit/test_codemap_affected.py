"""codemap.affected never plans a lab suite (B395): a lab suite needs a real
service and is run by name, so whichever road reaches it, the drawn names
or the covered run, it leaves the plan."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402


def index():
    page = "scripts/dashboard/tab-x.js"
    fn = {"file": page, "name": "send", "line": 1, "end": 3}
    return {
        "files": {page: {"lang": "js", "defs": [fn],
                         "draws": [{"what": "/api/thing", "kind": "path", "line": 2}]}},
        "defs": [fn],
        "calls": [],
        "draws": [{"file": "scripts/dashboard/test/cards.mjs", "what": "/api/thing", "kind": "path", "line": 9},
                  {"file": "scripts/dashboard/test/lab-node.mjs", "what": "/api/thing", "kind": "path", "line": 9}],
    }, fn


class Affected(unittest.TestCase):
    def test_a_drawn_name_plans_its_suites_but_never_a_lab_one(self):
        idx, _ = index()
        suites, _, _, _ = codemap.affected(idx, None, {"scripts/dashboard/tab-x.js": [(2, 2)]})
        self.assertIn("cards", suites)
        self.assertNotIn("lab-node", suites)

    def test_a_covered_run_that_saw_a_lab_suite_does_not_plan_it(self):
        idx, fn = index()
        cov = {"suites": {"lab-node": {codemap.fid(fn): 3}, "cards": {codemap.fid(fn): 1}}}
        suites, _, _, _ = codemap.affected(idx, cov, {"scripts/dashboard/tab-x.js": [(2, 2)]})
        self.assertIn("cards", suites)
        self.assertNotIn("lab-node", suites)


if __name__ == "__main__":
    unittest.main()
