"""What an account puts away from its bell (bellseen.py, R144): an update to
one version, for that account alone, back when a newer version is out; what
stops work cannot be put away."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bellseen  # noqa: E402


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


def rows(go_to="1.28.0", agent_to="0.7.159", window=False):
    return [{"kind": "toolchain", "id": "n1", "node": "box", "projects": [],
             "tools": [{"name": "claude-code", "label": "Claude Code", "from": "1.0", "to": "1.2"},
                       {"name": "go", "label": "Go", "from": "1.27.0", "to": go_to}]},
            {"kind": "agent", "id": "n1", "node": "box", "from": "0.7.157", "to": agent_to,
             "window": window, "projects": []}]


class BellSeen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bellseen.configure(state=self.tmp, write_json=write_json)

    def test_each_tool_and_agent_row_carries_its_versioned_key(self):
        out, hidden = bellseen.filter_rows("u1", rows())
        self.assertEqual(hidden, 0)
        self.assertEqual([t["key"] for t in out[0]["tools"]], ["tc:n1:claude-code@1.2", "tc:n1:go@1.28.0"])
        self.assertEqual(out[1]["key"], "agent:n1@0.7.159")

    def test_a_dismissal_is_one_accounts_and_one_versions(self):
        bellseen.dismiss("u1", ["tc:n1:go@1.28.0", "agent:n1@0.7.159"])
        out, hidden = bellseen.filter_rows("u1", rows())
        self.assertEqual(([t["name"] for t in out[0]["tools"]], len(out), hidden), (["claude-code"], 1, 2))
        self.assertEqual(len(bellseen.filter_rows("u2", rows())[0]), 2, "another account still sees both")
        out, _ = bellseen.filter_rows("u1", rows(go_to="1.29.0", agent_to="0.7.160"))
        self.assertEqual([t["name"] for t in out[0]["tools"]], ["claude-code", "go"], "a newer version notes again")
        self.assertEqual(len(out), 2)

    def test_a_row_with_every_tool_put_away_goes(self):
        bellseen.dismiss("u1", ["tc:n1:claude-code@1.2", "tc:n1:go@1.28.0"])
        out, hidden = bellseen.filter_rows("u1", rows())
        self.assertEqual(([r["kind"] for r in out], hidden), (["agent"], 2))

    def test_out_of_window_cannot_be_put_away(self):
        out, _ = bellseen.filter_rows("u1", rows(window=True))
        self.assertNotIn("key", out[1])
        bellseen.dismiss("u1", ["agent:n1@0.7.159"])
        self.assertEqual(len(bellseen.filter_rows("u1", rows(window=True))[0]), 2)

    def test_show_again_and_refusals(self):
        bellseen.dismiss("u1", ["tc:n1:go@1.28.0"])
        self.assertEqual(bellseen.restore("u1")[0]["restored"], 1)
        self.assertEqual(bellseen.filter_rows("u1", rows())[1], 0)
        self.assertEqual(bellseen.dismiss("", ["x"])[1], 400)
        self.assertEqual(bellseen.dismiss("u1", [])[1], 400)


if __name__ == "__main__":
    unittest.main()
