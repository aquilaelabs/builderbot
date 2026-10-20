"""The doctor's runner token line names the node and the repository its
runner serves, and a failed one carries the way to the page a new token is
given on, where it named a node id and a token slot with nothing to press
(B71)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import doctor  # noqa: E402

OUT = ("  [FAIL] runner token for 192.168.1.16-3000-lab-hello on n_495a2118: its host rejected it (revoked or expired?)\n"
       "  [ok]   runner token for github.com-acme-app on n_11111111: stored root-only, and its host accepts it\n")


class RunnerLine(unittest.TestCase):
    def checks(self, named):
        doctor.configure(run=lambda argv, timeout: {"out": OUT, "code": 1}, wait_for_boot=lambda: None,
                         runner_named=named)
        doctor.refresh()
        return doctor.payload()["checks"]

    def test_the_node_and_repository_by_name_and_the_way_to_fix_it(self):
        names = {"n_495a2118": ("bb-dev-sandbox-rh", "lab/hello"), "n_11111111": ("box", "acme/app")}
        bad, good = self.checks(lambda nid, slot: names[nid])
        self.assertEqual(bad["text"], "the CI runner token for lab/hello on bb-dev-sandbox-rh: "
                                      "its host rejected it (revoked or expired?)")
        self.assertEqual(bad["href"], "#/build/runner/n_495a2118")
        self.assertIn("new token", bad["detail"])
        self.assertEqual(good["text"], "the CI runner token for acme/app on box: stored root-only, and its host accepts it")
        self.assertNotIn("href", good, "a passing check has nothing to press")

    def test_a_node_it_cannot_name_keeps_the_line(self):
        def boom(nid, slot):
            raise KeyError(nid)
        bad, _ = self.checks(boom)
        self.assertTrue(bad["text"].startswith("runner token for 192.168.1.16-3000-lab-hello on n_495a2118"))


if __name__ == "__main__":
    unittest.main()
