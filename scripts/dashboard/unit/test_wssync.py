"""A node's projects as a synced copy (R162): the controller's wssync.py and
the agent's, end to end in one process, over a connection that hands each
call to the controller's module the way channel.py would."""
import hashlib
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
        self.fetched, self.cut = [], 0

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
        self.fetched.append(path.partition("?")[0])
        if path.startswith("sync-tar"):
            write, no = ctl_sync.tar_writer(self.nid, q["project"][0])
            if no:
                return no[1], ""
            buf = io.BytesIO()
            write(buf)
            data = buf.getvalue()[:self.cut] if self.cut else buf.getvalue()
            with open(dest, "wb") as f:
                f.write(data)
            return 200, ""
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

    def hello_again(self, why):
        self.hello_at = 0

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
        ctl_sync.configure(workspace=self.ws, nodes_module=Nodes,
                           bound_nodes=lambda p: ["n1", "n2"] if p == "alpha" else [])
        write(f"{self.ws}/beta/lib.py", "shared = 1\n")
        ctl_sync.configure_projects(lambda: ["alpha", "beta"])
        ctl_sync.configure_reads(lambda p: ["beta"] if p == "alpha" else [])
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

    def test_a_node_cannot_plant_what_git_runs_on_the_controller(self):
        """B618: the controller runs git in every tree, and git runs what its
        config and hooks name, so a node's write of either is refused and
        audited; an ordinary config change (an upstream) still lands."""
        def put(rel, body=b"", link=""):
            q = {"path": [rel], "base": [""], "mode": ["420"]}
            if link:
                q["link"] = [link]
            return ctl_sync.put("n1", "alpha", q, io.BytesIO(body), len(body))
        fsmon = b"[core]\n\tfsmonitor = touch /tmp/pwned\n"
        out, code = put(".git/config", fsmon)
        self.assertEqual(code, 403, out)
        self.assertIn("core.fsmonitor", out["error"])
        self.assertFalse(os.path.exists(f"{self.ws}/alpha/.git/config"))
        for bad in (b'[filter "x"]\n\tclean = sh -c id\n', b"[include]\n\tpath = /etc/evil\n",
                    b'[alias]\n\tst = !sh -c id\n', b"[core]\n\tworktree = /\n"):
            self.assertEqual(put(".git/config", bad)[1], 403, bad)
        self.assertEqual(put(".git/modules/sub/config", fsmon)[1], 403, "a submodule's config too")
        self.assertEqual(put(".git/hooks/post-checkout", b"#!/bin/sh\nid\n")[1], 403)
        self.assertEqual(put(".git", b"gitdir: /etc\n")[1], 403, "a .git file naming another repository")
        self.assertEqual(put("src/escape", link="../../../etc/passwd")[1], 403, "a link climbing out")
        self.assertEqual(put(".git/refs/heads/x", link="main")[1], 403, "a link inside .git")
        fine = b'[branch "main"]\n\tremote = origin\n\tmerge = refs/heads/main\n[alias]\n\tst = status\n'
        out, code = put(".git/config", fine)
        self.assertEqual(code, 200, out)
        self.assertEqual(read(f"{self.ws}/alpha/.git/config"), fine.decode())
        self.assertEqual(put("src/link", link="../a.txt")[1], 200, "a link inside the project is fine")

    def test_a_git_config_the_controller_already_holds_comes_back_as_already_so(self):
        """B732: the controller writes the project's own credential helper
        into its config and the sync carries that down, so the node sending
        the same bytes back is not planting anything; refused, the file
        stayed pending on every tick and every push from the node was
        refused as behind. The same bytes are already so; different ones
        that name a program are still refused."""
        helper = b"[credential]\n\thelper = \n\thelper = store --file=/config/gitcreds/alpha\n"
        os.makedirs(f"{self.ws}/alpha/.git", exist_ok=True)
        with open(f"{self.ws}/alpha/.git/config", "wb") as f:
            f.write(helper)
        def put(body, base=""):
            q = {"path": [".git/config"], "base": [base], "mode": ["420"]}
            return ctl_sync.put("n1", "alpha", q, io.BytesIO(body), len(body))
        out, code = put(helper)
        self.assertEqual(code, 200, out)
        self.assertEqual(out.get("sha"), hashlib.sha256(helper).hexdigest())
        self.assertEqual(read(f"{self.ws}/alpha/.git/config"), helper.decode())
        # ...and one that differs elsewhere (an upstream the node's push set)
        # while naming no program the controller's does not already run.
        more = helper + b'[branch "topic"]\n\tremote = origin\n\tmerge = refs/heads/topic\n'
        out, code = put(more, base=out["sha"])
        self.assertEqual(code, 200, out)
        self.assertEqual(read(f"{self.ws}/alpha/.git/config"), more.decode())
        base = out["sha"]
        other = more + b"[core]\n\tfsmonitor = touch /tmp/pwned\n"
        out, code = put(other, base=base)
        self.assertEqual(code, 403, out)
        self.assertIn("core.fsmonitor", out["error"], "the key the node adds, not the one the controller already runs")
        swapped = more.replace(b"/config/gitcreds/alpha", b"/tmp/elsewhere")
        out, code = put(swapped, base=base)
        self.assertEqual(code, 403, out)
        self.assertIn("credential.helper", out["error"], "the same key pointed elsewhere is a new program")

    def test_a_node_bound_to_a_project_is_told_at_once(self):
        """The settings dialog binding a project (or changing what it reads)
        hints every synced node, and the hint makes the agent ask again
        which projects it holds rather than wait for its own next look."""
        Nodes.sync_node_ids = staticmethod(lambda: frozenset({"n1", "n2"}))
        try:
            self.turn("n1")
            self.n["n1"].asked_at = 10 ** 9           # its own next look is far off
            ctl_sync.held_changed()
            mine = {p: r for nid, p, r in Nodes.hints if nid == "n1"}
            self.assertIn("", mine)
            self.n["n1"].nudge(mine)
            self.assertEqual(self.n["n1"].asked_at, 0.0)
        finally:
            del Nodes.sync_node_ids

    def test_a_first_copy_is_the_project_less_what_is_not_synced(self):
        self.turn("n1", times=1)
        self.assertEqual(read(self.at("n1", "a.txt")), "one\n")
        self.assertEqual(read(self.at("n1", "src/b.py")), "print('b')\n")
        self.assertEqual(os.readlink(self.at("n1", "b-link")), "src/b.py")
        self.assertEqual(read(self.at("n1", ".git/HEAD")), "ref: refs/heads/main\n")
        self.assertFalse(os.path.exists(self.at("n1", "node_modules")))
        self.assertFalse(os.path.exists(self.at("n1", ".git/index.lock")))
        self.assertTrue(self.n["n1"].status()["alpha"]["ready"])

    def test_the_copy_says_its_state_where_a_session_reads_it_and_it_never_syncs(self):
        self.turn("n1")
        with open(self.at("n1", ".git/.bbsync-state")) as f:
            st = json.load(f)
        self.assertEqual((st["ready"], st["pending"]), (True, 0))
        self.assertEqual(st["rev"], ctl_sync.rev_of("alpha"))
        self.turn("n1")
        self.assertFalse(os.path.exists(f"{self.ws}/alpha/.git/.bbsync-state"))

    def test_a_project_a_bound_project_reads_comes_down_read_only(self):
        self.turn()
        beta = os.path.join(self.tmp, "n1", "workspace", "beta", "lib.py")
        self.assertEqual(read(beta), "shared = 1\n")
        self.assertTrue(self.n["n1"].projects["beta"].ro)
        # A change here is never sent; the controller's version comes back.
        write(beta, "changed on the node\n")
        self.turn("n1", times=3)
        self.assertEqual(read(f"{self.ws}/beta/lib.py"), "shared = 1\n")
        # ...and the controller's changes come down, to every node reading it.
        write(f"{self.ws}/beta/lib.py", "shared = 2\n")
        ctl_sync.changed("beta")
        self.assertIn(("n2", "beta"), [(n, p) for n, p, _ in Nodes.hints])
        self.turn(times=1)
        self.assertEqual(read(beta), "shared = 2\n")
        self.assertEqual(read(os.path.join(self.tmp, "n2", "workspace", "beta", "lib.py")), "shared = 2\n")

    def test_a_node_may_read_a_read_project_and_never_write_it(self):
        self.assertEqual(ctl_sync.state("n1", "beta")[1], 200)
        out, code = ctl_sync.put("n1", "beta", {"path": ["lib.py"], "base": [""]}, io.BytesIO(b"x"), 1)
        self.assertEqual(code, 403)
        self.assertIn("read-only", out["error"])
        self.assertEqual(ctl_sync.projects("n1")["reads"], {"beta": ctl_sync.rev_of("beta")})

    def test_nothing_is_copied_while_the_share_is_still_mounted_there(self):
        # A node moving off the share (R163) hears it is synced before its
        # storage apply has unmounted /workspace: it waits, and says why.
        real = os.path.ismount
        root = self.n["n1"].root
        os.makedirs(root, exist_ok=True)
        node_sync.os.path.ismount = lambda p: p == root or real(p)
        try:
            self.turn("n1", times=1)
        finally:
            node_sync.os.path.ismount = real
        self.assertFalse(os.path.exists(self.at("n1", "a.txt")))
        self.assertEqual(self.n["n1"].status()["alpha"]["error"], node_sync.MOUNTED)
        self.turn("n1", times=1)
        self.assertEqual(read(self.at("n1", "a.txt")), "one\n")
        self.assertEqual(self.n["n1"].status()["alpha"]["error"], "")

    def test_a_project_that_is_gone_is_not_held_though_its_settings_remain(self):
        ctl_sync.configure_projects(lambda: ["alpha", "beta", "gone"])
        ctl_sync.configure_reads(lambda p: ["beta", "lost"] if p == "alpha" else [])
        ctl_sync.configure(workspace=self.ws, nodes_module=Nodes,
                           bound_nodes=lambda p: ["n1"] if p in ("alpha", "gone") else [])
        got = ctl_sync.projects("n1")
        self.assertEqual((sorted(got["projects"]), sorted(got["reads"])), (["alpha"], ["beta"]))

    def test_a_second_accounts_worktree_goes_both_ways(self):
        # B615: a worktree the controller holds comes down to the project's
        # nodes, one made on a node goes up, and its .git line is each
        # side's own, never sent.
        wt = f"{self.ws}/.worktrees/alpha/u_12345678"
        write(f"{wt}/.git", f"gitdir: {self.ws}/alpha/.git/worktrees/u_12345678\n")
        write(f"{wt}/notes.txt", "from the controller\n")
        self.assertIn(".worktrees/alpha/u_12345678", ctl_sync.projects("n1")["projects"])
        self.turn("n1")
        there = os.path.join(self.tmp, "n1", "workspace", ".worktrees", "alpha", "u_12345678")
        self.assertEqual(read(f"{there}/notes.txt"), "from the controller\n")
        # Made on the node: its worktree directory, and git's record of it in
        # the project's own .git, which reaches the controller with alpha.
        mine = os.path.join(self.tmp, "n1", "workspace", ".worktrees", "alpha", "u_87654321")
        write(f"{mine}/.git", "gitdir: somewhere the node chose\n")
        write(f"{mine}/work.py", "x = 1\n")
        write(self.at("n1", ".git/worktrees/u_87654321/HEAD"), "ref: refs/heads/claude/dev2\n")
        self.n["n1"].asked_at = 0
        self.turn("n1", times=4)
        up = f"{self.ws}/.worktrees/alpha/u_87654321"
        self.assertEqual(read(f"{up}/work.py"), "x = 1\n")
        self.assertEqual(read(f"{up}/.git"), f"gitdir: {self.ws}/alpha/.git/worktrees/u_87654321\n",
                         "the controller writes git's own line; the node's is never taken")
        self.assertIn("is not a project", ctl_sync.may("n9", ".worktrees/alpha/u_87654321"),
                      "a worktree is its project's nodes' alone")

    def test_a_nodes_index_wins_over_one_refreshed_here(self):
        # B617: git status on the controller rewrote .git/index; the node's
        # own index after a commit then lost to it and came back stale.
        write(f"{self.ws}/alpha/.git/index", "index before\n")
        self.turn("n1")
        base = ctl_sync._load("alpha")[".git/index"]["sha"]
        write(f"{self.ws}/alpha/.git/index", "index refreshed here\n")
        ctl_sync.scan("alpha", force=True)
        body = b"index after the commit\n"
        out, code = ctl_sync.put("n1", "alpha", {"path": [".git/index"], "base": [base]}, io.BytesIO(body), len(body))
        self.assertEqual((code, out.get("conflict")), (200, None), out)
        self.assertEqual(read(f"{self.ws}/alpha/.git/index"), "index after the commit\n")
        self.assertFalse(any("bbsync-conflicts" in c["kept_as"] for c in ctl_sync._conflicts))

    def test_a_first_copy_is_one_download(self):
        self.turn("n1", times=1)
        self.assertEqual(self.n["n1"].agent.ctl.fetched, ["sync-tar"] * len(self.n["n1"].projects))  # one a project
        self.assertEqual(read(self.at("n1", "src/b.py")), "print('b')\n")

    def test_a_cut_off_download_is_made_up_file_by_file(self):
        self.n["n1"].agent.ctl.cut = 2048
        self.turn("n1", times=1)
        self.assertEqual(read(self.at("n1", "a.txt")), "one\n")
        self.assertEqual(read(self.at("n1", "src/b.py")), "print('b')\n")
        self.assertEqual(read(self.at("n1", ".git/HEAD")), "ref: refs/heads/main\n")
        self.assertIn("sync-file", self.n["n1"].agent.ctl.fetched)

    def test_a_save_is_seen_by_the_watcher_without_walking_the_tree(self):
        if node_sync._inotify() is None:
            self.skipTest("no inotify here")
        self.turn()
        was, node_sync.WALK_EVERY = node_sync.WALK_EVERY, 1e9
        try:
            self.assertTrue(self.n["n1"].projects["alpha"].watch)
            write(self.at("n1", "src/deep/new.py"), "in a new directory\n")
            write(self.at("n1", "a.txt"), "watched\n")
            self.turn("n1", times=3)
            self.assertEqual(read(f"{self.ws}/alpha/a.txt"), "watched\n")
            self.assertEqual(read(f"{self.ws}/alpha/src/deep/new.py"), "in a new directory\n")
        finally:
            node_sync.WALK_EVERY = was

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
