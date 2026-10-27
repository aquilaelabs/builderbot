"""Migration 0007 (the operator, 26 Oct): every agent node keeps each session
and each project's containers to their own network; one that had switched
either off has it on again, a hosting-only node's sessions' switch is left as
it was, and what reads a node with no switch stored reads it as on."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


class NetworksOn(unittest.TestCase):
    def test_switched_off_comes_back_on(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, config TEXT NOT NULL)")
        rows = {"off": {"session_net": False, "container_net": False},
                "host": {"host_only": True, "session_net": False, "container_net": False},
                "unset": {}, "local": {"session_net": False}}
        for k, c in rows.items():
            db.execute("INSERT INTO nodes VALUES (?, ?, ?)", (k, "local" if k == "local" else "agent", json.dumps(c)))
        db.executescript((HERE / "migrations" / "0007_networks_on.sql").read_text())
        got = {k: json.loads(c) for k, c in db.execute("SELECT id, config FROM nodes")}
        self.assertEqual((got["off"]["session_net"], got["off"]["container_net"]), (True, True))
        self.assertEqual((got["host"]["session_net"], got["host"]["container_net"]), (False, True),
                         "a hosting-only node runs no sessions: only its containers' switch moves")
        self.assertEqual(got["unset"], {}, "nothing stored stays nothing, which reads as on")
        self.assertEqual(got["local"], {"session_net": False}, "the controller's own row is not an agent's")


class ReadsAsOn(unittest.TestCase):
    def test_no_switch_stored_is_on(self):
        import nodes
        saved = nodes.node
        self.addCleanup(setattr, nodes, "node", saved)
        conf = {"a": {}, "h": {"host_only": True}, "x": {"session_net": False, "container_net": False}}
        nodes.node = lambda nid: {"id": nid, "kind": "agent", "config": conf[nid]}
        self.assertEqual((nodes.session_net_on("a"), nodes.container_net_on("a")), (True, True))
        self.assertEqual((nodes.session_net_on("h"), nodes.container_net_on("h")), (False, True))
        # The switches went in 0.9.0 (R146): a key an older build left reads as on.
        self.assertEqual((nodes.session_net_on("x"), nodes.container_net_on("x")), (True, True))
        self.assertIn("went in 0.9.0", nodes.node_session_net("user:t", "x", False).get("error", ""))
        self.assertIn("went in 0.9.0", nodes.node_container_net("user:t", "x", False).get("error", ""))


if __name__ == "__main__":
    unittest.main()
