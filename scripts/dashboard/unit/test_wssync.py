"""A node's projects as a synced copy (R162): the controller's wssync.py and
the agent's, end to end in one process, over a connection that hands each
call to the controller's module the way channel.py would."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import db  # noqa: E402
import wssync as ctl_sync  # noqa: E402
import agentpkg  # noqa: E402

AGENT = agentpkg.load("wssync")
node_sync = AGENT.module("wssync")


class Nodes:
    hints = []

    @staticmethod
    def node(nid):
        return {"id": nid, "name": nid, "config": {"workspace": "sync"}}

    @classmethod
    def sync_hint(cls, nid, project, rev):
        cls.hints.append((nid, project, rev))


class Wire:
    """The agent's Controller, answered by the controller's module."""

    def __init__(self, nid):
        self.nid, self.down = nid, False

    def call(self, verb, body, timeout=0):
        if self.down:
            return 0, {"error": "ConnectionRefusedError"}
        assert verb == "sync"
        act, project = body.get("action"), body.get("project", "")
        if act == "projects":
            out, code = ctl_sync.projects(self.nid), 200
        elif act == "state":
            out, code = ctl_sync.state(self.nid, project)
        else:
            out, code = ctl_sync.since(self.nid, project, body.get("rev"))
        return code, json.loads(json.dumps(out))

    def fetch(self, path, dest, timeout=0):
        if self.down:
            return 0, "down"
        q = urllib.parse.parse_qs(path.partition("?")[2])
        p, no = ctl_sync.file_path(self.nid, q["project"][0], q["path"][0])
        if no:
            return no[1], ""
        shutil.copyfile(p, dest)
        return 200, ""

    def upload(self, path, src, timeout=0):
        if self.down:
            return 0, {"error": "down"}
        q = urllib.parse.parse_qs(path.partition("?")[2], keep_blank_values=True)
        with open(src, "rb") as f:
            body = f.read()
        out, code = ctl_sync.put(self.nid, q["project"][0], q, io.BytesIO(body), len(body))
        return code, json.loads(json.dumps(out))


class Agent:
    def __init__(self, nid, data):
        self.state = {"stores": {"data": data}}
        self.ctl = Wire(nid)
        self.hello_at = 1

    def session_account(self):
        return ""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wssync-")
        db.configure(state=os.path.join(self.tmp, "state"))
        self.ws = os.path.join(self.tmp, "controller")
        write(f"{self.ws}/alpha/a.txt", "one\n")
        write(f"{self.ws}/alpha/src/b.py", "print('b')\n")
        os.symlink("src/b.py", f"{self.ws}/alpha/b-link")
        write(f"{self.ws}/alpha/node_modules/x/index.js", "skipped\n")
        write(f"{self.ws}/alpha/.git/HEAD", "ref: refs/heads/main\n")
        write(f"{self.ws}/alpha/.git/index.lock", "a moment's\n")
        ctl_sync._index.clear()
        ctl_sync._scanned.clear()
        ctl_sync._conflicts.clear()
        Nodes.hints.clear()
        ctl_sync.configure(workspace=self.ws, nodes_module=Nodes, bound_nodes=lambda p: ["n1", "n2"])
        ctl_sync.configure_projects(lambda: ["alpha"])
        self.n = {k: node_sync.WorkspaceSync(Agent(k, os.path.join(self.tmp, k, "data")),
                                             root=os.path.join(self.tmp, k, "workspace"))
                  for k in ("n1", "n2")}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def turn(self, *names, times=2):
        """Ticks of the named nodes' loops; two, since a change goes up once
        it has held still for one."""
        for _ in range(times):
            for k in names or self.n:
                ctl_sync._scanned.clear()       # the controller's scan, not rate-limited here
                # What the held work request would hand this node's agent.
                mine = {p: r for n, p, r in Nodes.hints if n == k}
                Nodes.hints[:] = [h for h in Nodes.hints if h[0] != k]
                if mine:
                    self.n[k].nudge(mine)
                self.n[k].step()

    def at(self, k, rel):
        return os.path.join(self.tmp, k, "workspace", "alpha", rel)

    def test_a_first_copy_is_the_project_less_what_is_not_synced(self):
        self.turn("n1", times=1)
        self.assertEqual(read(self.at("n1", "a.txt")), "one\n")
        self.assertEqual(read(self.at("n1", "src/b.py")), "print('b')\n")
        self.assertEqual(os.readlink(self.at("n1", "b-link")), "src/b.py")
        self.assertEqual(read(self.at("n1", ".git/HEAD")), "ref: refs/heads/main\n")
        self.assertFalse(os.path.exists(self.at("n1", "node_modules")))
        self.assertFalse(os.path.exists(self.at("n1", ".git/index.lock")))
        self.assertTrue(self.n["n1"].status()["alpha"]["ready"])

    def test_a_save_on_one_node_reaches_the_controller_and_the_other_node(self):
        self.turn()
        write(self.at("n1", "a.txt"), "two\n")
        write(self.at("n1", "src/new.py"), "new\n")
        os.remove(self.at("n1", "src/b.py"))
        self.turn("n1")
        self.assertEqual(read(f"{self.ws}/alpha/a.txt"), "two\n")
        self.assertEqual(read(f"{self.ws}/alpha/src/new.py"), "new\n")
        self.assertFalse(os.path.exists(f"{self.ws}/alpha/src/b.py"))
        self.assertIn(("n2", "alpha"), [(n, p) for n, p, _ in Nodes.hints])
        self.turn("n2", times=1)
        self.assertEqual(read(self.at("n2", "a.txt")), "two\n")
        self.assertEqual(read(self.at("n2", "src/new.py")), "new\n")
        self.assertFalse(os.path.exists(self.at("n2", "src/b.py")))

    def test_a_write_on_the_controller_reaches_both_nodes(self):
        self.turn()
        write(f"{self.ws}/alpha/a.txt", "from vs code\n")
        ctl_sync.changed("alpha")
        for k in self.n:
            self.n[k].nudge({"alpha": 0})
        self.turn(times=1)
        self.assertEqual(read(self.at("n1", "a.txt")), "from vs code\n")
        self.assertEqual(read(self.at("n2", "a.txt")), "from vs code\n")

    def test_the_same_file_changed_on_two_nodes_keeps_both(self):
        self.turn()
        write(self.at("n1", "a.txt"), "n1's\n")
        write(self.at("n2", "a.txt"), "n2's\n")
        self.turn("n1")
        self.turn("n2")
        self.assertEqual(read(f"{self.ws}/alpha/a.txt"), "n1's\n")
        kept = [f for f in os.listdir(f"{self.ws}/alpha") if f.startswith("a.conflict-n2-")]
        self.assertEqual(len(kept), 1, os.listdir(f"{self.ws}/alpha"))
        self.assertEqual(read(f"{self.ws}/alpha/{kept[0]}"), "n2's\n")
        self.assertEqual(read(self.at("n2", "a.txt")), "n1's\n")
        self.turn()
        self.assertEqual(read(self.at("n1", kept[0])), "n2's\n")
        self.assertEqual(read(self.at("n2", kept[0])), "n2's\n")
        self.assertEqual([c["kept_as"] for c in ctl_sync.conflicts(lambda p: True)], [kept[0]])

    def test_a_conflict_inside_git_is_kept_out_of_the_tree(self):
        self.turn()
        write(self.at("n1", ".git/HEAD"), "ref: refs/heads/one\n")
        write(self.at("n2", ".git/HEAD"), "ref: refs/heads/two\n")
        self.turn("n1")
        self.turn("n2")
        self.assertEqual(read(f"{self.ws}/alpha/.git/HEAD"), "ref: refs/heads/one\n")
        kept = ctl_sync.conflicts(lambda p: True)[0]["kept_as"]
        self.assertTrue(kept.startswith(".git/bbsync-conflicts/n2-") and kept.endswith("/HEAD"), kept)

    def test_changes_made_while_the_controller_was_away_go_up_when_it_is_back(self):
        self.turn()
        self.n["n1"].agent.ctl.down = True
        write(self.at("n1", "a.txt"), "offline\n")
        self.turn("n1")
        self.assertEqual(read(f"{self.ws}/alpha/a.txt"), "one\n")
        # ...and across a restart of the agent: the record is on disk.
        again = node_sync.WorkspaceSync(Agent("n1", os.path.join(self.tmp, "n1", "data")),
                                        root=os.path.join(self.tmp, "n1", "workspace"))
        self.n["n1"] = again
        self.turn("n1", times=3)
        self.assertEqual(read(f"{self.ws}/alpha/a.txt"), "offline\n")

    def test_a_file_already_there_and_different_is_kept_not_overwritten(self):
        write(self.at("n1", "a.txt"), "was here first\n")
        self.turn("n1", times=3)
        self.assertEqual(read(self.at("n1", "a.txt")), "one\n")
        kept = [f for f in os.listdir(f"{self.ws}/alpha") if f.startswith("a.conflict-n1-")]
        self.assertEqual(read(f"{self.ws}/alpha/{kept[0]}"), "was here first\n")

    def test_a_node_not_bound_to_the_project_is_refused(self):
        self.assertIn("not a project this node", ctl_sync.state("n9", "alpha")[0]["error"])
        self.assertEqual(ctl_sync.file_path("n1", "alpha", "../escape")[1][1], 400)
        self.assertEqual(ctl_sync.file_path("n1", "alpha", "node_modules/x/index.js")[1][1], 400)

    def test_both_sides_skip_the_same_things(self):
        self.assertEqual(node_sync.SKIP_DIRS, ctl_sync.SKIP_DIRS)
        self.assertEqual(node_sync.MAX_FILE, ctl_sync.MAX_FILE)


if __name__ == "__main__":
    unittest.main()
