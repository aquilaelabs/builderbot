"""Each node's move off the shared <os>-<arch> directory (R196): what it
held is installed again into the node's own directory by one job, queued
once per node; and what no node runs from any more is offered for removal,
the old directory only once every node has moved, never `shared` or a live
node's."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402


def node(nid, name, scope, legacy=None, roots=(), state="online", top=()):
    dirs = {"top": list(top), "android": [], "roots": list(roots)}
    if legacy is not None:
        dirs["legacy"] = {"top": list(legacy), "android": []}
    return {"id": nid, "name": name, "kind": "agent", "state": state, "live": state == "online",
            "reported": {"os": "linux x86_64", "store_dirs": dirs,
                         "stores": {"toolchains": {"path": "/s", "id": "share1", "scope": scope}}}}


class Moves(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.queued, self.jobs, self.nodes_, self.local = [], {}, [], None
        test = self

        class Nodes:
            LOCAL = "local"

            @staticmethod
            def node(nid):
                return next((n for n in test.nodes_ if n["id"] == nid), None) if nid != "local" else test.local

            @staticmethod
            def node_list(all=False):
                return [n for n in test.nodes_ if all or n["state"] != "retired"]

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, active=False, **k):
                return [j for j in test.jobs.get(node_id, []) if not active or j["state"] in ("queued", "running")]
        saved = (toolchains.nodes, toolchains.STATE, toolchains.write_json, toolchains.node_job)
        self.addCleanup(lambda: setattr(toolchains, "nodes", saved[0]) or setattr(toolchains, "STATE", saved[1])
                        or setattr(toolchains, "write_json", saved[2]) or setattr(toolchains, "node_job", saved[3]))
        toolchains.nodes, toolchains.STATE = Nodes(), Path(self.tmp)
        toolchains.write_json = lambda p, d: Path(p).write_text(json.dumps(d))

        def nj(principal, nid, action, names, driver=""):
            test.queued.append((nid, action, list(names)))
            test.jobs.setdefault(nid, []).append({"state": "queued"})
            return {"ok": True}
        toolchains.node_job = nj

    def test_a_node_moves_once_what_the_shared_directory_held(self):
        self.nodes_ = [node("n_aaaa1111", "bb-sandbox", "n_aaaa1111", legacy=["jdk", "go", "swift"], top=["go"])]
        got = toolchains.names_in({"top": ["jdk", "go", "not-a-recipe"], "android": ["platform-tools"]})
        self.assertTrue({"jdk", "go", "android-tools"} <= set(got) and "not-a-recipe" not in got,
                        f"a listing read as the recipes it holds ({got})")
        self.assertEqual(toolchains.node_moves_due(), ["n_aaaa1111"])
        self.assertEqual(self.queued, [("n_aaaa1111", "install", ["jdk", "swift"])], "what it has not got, once")
        self.jobs.clear()
        self.assertEqual(toolchains.node_moves_due(), [], "not queued again")
        self.assertEqual(len(self.queued), 1)

    def test_a_node_still_on_the_shared_directory_does_not_move(self):
        self.nodes_ = [node("n_bbbb2222", "old", "linux-x86_64", legacy=["jdk"])]
        self.assertEqual(toolchains.node_moves_due(), [])

    def test_what_no_node_runs_from_is_offered_and_nothing_else(self):
        roots = ["linux-x86_64", "n_aaaa1111", "n_cccc3333", "n_dddd4444", "shared"]
        self.nodes_ = [node("n_aaaa1111", "bb-sandbox", "n_aaaa1111", roots=roots),
                       node("n_cccc3333", "redhat", "n_cccc3333", legacy=["jdk"], roots=roots),
                       node("n_dddd4444", "gone", "n_dddd4444", state="retired")]
        got = {c["dir"] for c in toolchains.cleanable("n_aaaa1111")}
        self.assertEqual(got, {"n_dddd4444"}, "a retired node's, but not the shared one while redhat has not moved")
        Path(self.tmp, "toolchain-moves.json").write_text(json.dumps({"n_cccc3333": {"at": 1, "names": ["jdk"]}}))
        got = {c["dir"]: c["what"] for c in toolchains.cleanable("n_aaaa1111")}
        self.assertEqual(set(got), {"linux-x86_64", "n_dddd4444"}, "once every node has moved, the shared one too")
        self.assertIn("gone's, a node since retired", got["n_dddd4444"])
        # ...but never while this controller keeps its own browsers there,
        # on the same share (bb capture shot's Playwright).
        import platform
        self.local = {"id": "local", "kind": "local", "state": "online",
                      "reported": {"stores": {"toolchains": {"path": "/s", "id": "share1"}}}}
        here = f"{platform.system().lower()}-{platform.machine()}"
        roots = [here, "n_aaaa1111", "n_cccc3333"]
        for n in self.nodes_:
            n["reported"]["store_dirs"]["roots"] = roots
        self.assertNotIn(here, {c["dir"] for c in toolchains.cleanable("n_aaaa1111")})


class HelloKeepsTheListing(unittest.TestCase):
    """The hello's whitelist of a node's census keeps the two lists the move
    reads (store_dirs.legacy and roots): with top, android and incomplete
    alone, a node on the new directory reported its old one as empty and no
    move was ever queued (bb-dev-sandbox, 12 Oct)."""

    def test_legacy_and_roots_come_through(self):
        import nodes
        got = nodes._census({"store_dirs": {"top": ["go"], "android": [], "incomplete": [],
                                            "roots": ["linux-x86_64", "n_aaaa1111", "shared"],
                                            "legacy": {"top": ["jdk", "android"], "android": ["platform-tools"], "junk": 1}}})
        self.assertEqual(got["store_dirs"]["roots"], ["linux-x86_64", "n_aaaa1111", "shared"])
        self.assertEqual(got["store_dirs"]["legacy"], {"top": ["jdk", "android"], "android": ["platform-tools"]})
        self.assertNotIn("legacy", nodes._census({"store_dirs": {"top": []}})["store_dirs"], "none reported, none kept")


if __name__ == "__main__":
    unittest.main()
