"""bb settings names a project's nodes as the Nodes page does, not by the ids
the record keeps (B58); an id with no node left behind it is printed as it is."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")
LIB = os.path.join(DASH, "..", "lib")
sys.path.insert(0, DASH)
import db  # noqa: E402


class NodeNames(unittest.TestCase):
    def test_nodes_by_name(self):
        st = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, st, True)
        db.configure(state=st)
        db.migrate()
        cols = [r["name"] if isinstance(r, dict) else r[1] for r in db._rows("PRAGMA table_info(nodes)")]
        row = dict.fromkeys(cols, "")
        row.update(id="n_abc123", name="bigbox", kind="agent", state="online", created=1)
        for c in ("services", "labels", "agent", "reported", "routing", "config"):
            if c in row:
                row[c] = "{}"
        row["capabilities"] = "[]"
        db._exec(f"INSERT INTO nodes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 tuple(row[c] for c in cols))
        with open(os.path.join(st, "claude-prefs.json"), "w") as f:
            json.dump({"projects": {"alpha": {"node": "n_abc123", "nodes": ["n_abc123", "n_gone"]}}}, f)
        out = subprocess.run([sys.executable, os.path.join(LIB, "settings-verbs.py"), "show", DASH, "alpha"],
                             env={**os.environ, "DASHBOARD_STATE": st, "PYTHONPATH": LIB},
                             capture_output=True, text=True, check=False).stdout
        self.assertIn("  node     bigbox\n", out)
        self.assertIn("  nodes    bigbox, n_gone\n", out)


if __name__ == "__main__":
    unittest.main()
