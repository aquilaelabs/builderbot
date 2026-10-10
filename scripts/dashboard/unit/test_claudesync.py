"""A synced node's Claude conversations (B613): the controller's
claudesync.py and the agent's mirror, end to end in one process, over a
connection that hands each call to the controller's module the way
channel.py would."""
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
import claudesync as ctl_cs  # noqa: E402
import agentpkg  # noqa: E402

AGENT = agentpkg.load("claudesync")
node_cs = AGENT.module("claudesync")

UID = "u_0123abcd"
OTHER = "u_99999999"


class Wire:
    """The agent's Controller, answered by the controller's module."""

    def __init__(self, nid):
        self.nid = nid
        self.sent = []          # (mode, bytes) of every put

    def call(self, verb, body, timeout=0):
        path, _, query = verb.partition("?")
        if path == "claude":
            return 200, json.loads(json.dumps(ctl_cs.listing(self.nid)))
        assert path == "claude-put"
        q = urllib.parse.parse_qs(query, keep_blank_values=True)
        out, code = ctl_cs.put(self.nid, q, io.BytesIO(b""), 0)
        self.sent.append((q["mode"][0], 0))
        return code, out

    def fetch(self, path, dest, timeout=0):
        q = urllib.parse.parse_qs(path.partition("?")[2])
        p, no = ctl_cs.file_path(self.nid, q["uid"][0], q["path"][0])
        if no or p is None:
            return no[1], ""
        shutil.copyfile(p, dest)
        return 200, ""

    def upload(self, path, src, timeout=0, offset=0, length=None):
        q = urllib.parse.parse_qs(path.partition("?")[2], keep_blank_values=True)
        with open(src, "rb") as f:
            f.seek(offset)
            body = f.read() if length is None else f.read(length)
        self.sent.append((q["mode"][0], len(body)))
        out, code = ctl_cs.put(self.nid, q, io.BytesIO(body), len(body))
        return code, json.loads(json.dumps(out))


class WsSync:
    """What the mirror reads of the agent's wssync: its mode, its root, the
    projects it holds and where its records go."""

    def __init__(self, root, data, held, ro=()):
        import threading
        self.mode, self.root, self.lock = "sync", root, threading.Lock()
        self.projects = {n: type("P", (), {"ro": n in ro})() for n in held}
        self.data = data

    def record_dir(self):
        os.makedirs(self.data, exist_ok=True)
        return self.data

    def owner(self):
        return None


class Agent:
    def __init__(self, nid):
        self.ctl = Wire(nid)


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class Mirror(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="claudesync-")
        self.ctl_ws = os.path.join(self.tmp, "controller")
        self.node_ws = os.path.join(self.tmp, "node", "workspace")
        os.makedirs(self.node_ws)
        # Path parity, as in life: both sides name a project's folder by
        # /workspace/NAME, so the controller is configured with the node's
        # path for the names and keeps its files in a tree of its own.
        ctl_cs.configure(workspace=self.node_ws, held=lambda nid: ["alpha"] if nid == "n1" else [])
        self.real_root = ctl_cs.root
        ctl_cs.root = lambda: ctl_cs.Path(self.ctl_ws) / ".claude"
        self.agent = Agent("n1")
        self.ws = WsSync(self.node_ws, os.path.join(self.tmp, "node", "data"), ["alpha", "beta"], ro={"beta"})
        self.m = node_cs.ClaudeMirror(self.agent, self.ws)
        self.slug = node_cs.slug(f"{self.node_ws}/alpha")

    def tearDown(self):
        ctl_cs.root = self.real_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def node_file(self, uid, rel):
        return os.path.join(self.node_ws, ".claude", uid, "projects", self.slug, rel)

    def ctl_file(self, uid, rel):
        return os.path.join(self.ctl_ws, ".claude", uid, "projects", self.slug, rel)

    def tick(self, fresh=True):
        if fresh:
            self.m.listed_at = 0.0
        self.m.step()

    # -- the rules, without the wire ---------------------------------------------------
    def test_plan(self):
        k, mem = f"{UID}/s/conv.jsonl", f"{UID}/s/memory/a.md"
        big = node_cs.PULL_MAX + 1
        p = node_cs.plan
        self.assertEqual(p({k: [5, 1000]}, {}, {}, True), [("push", k)], "new here goes up")
        self.assertEqual(p({}, {k: [5, 1000]}, {}, True), [("pull", k)], "small and new there comes down")
        self.assertEqual(p({}, {k: [big, 1000]}, {}, True), [], "a long one waits for a resume")
        self.assertEqual(p({}, {k: [5, 1000]}, {}, False), [], "nothing comes down on a stale listing")
        self.assertEqual(p({k: [5, 1000]}, {k: [5, 1000]}, {}, True), [("agree", k)])
        self.assertEqual(p({}, {mem: [5, 1000]}, {mem: [5, 1000]}, True), [("drop-there", mem)],
                         "a memory removed here goes there")
        self.assertEqual(p({mem: [5, 1000]}, {}, {mem: [5, 1000]}, True), [("drop-here", mem)],
                         "a memory removed there goes here")
        self.assertEqual(p({}, {k: [5, 1000]}, {k: [5, 1000]}, True), [("forget", k)],
                         "a conversation removed here is not removed there")
        self.assertEqual(p({}, {k: [5, 1000]}, {k: None}, True), [],
                         "...nor fetched again")
        self.assertEqual(p({k: [5, 1000]}, {}, {k: [5, 1000]}, True), [("forget", k)],
                         "one removed there is kept here")

    def test_worktree_and_prefix(self):
        ws = "/workspace"
        self.assertEqual(node_cs.project_of("-workspace-alpha", ws, ["alpha"]), "alpha")
        self.assertEqual(node_cs.project_of("-workspace--worktrees-alpha-u-0123abcd", ws, ["alpha"]), "alpha")
        self.assertEqual(node_cs.project_of("-workspace-alphabet", ws, ["alpha"]), "",
                         "a project whose name starts another's is not claimed")
        self.assertEqual(node_cs.project_of("-workspace-beta", ws, ["alpha"]), "")

    # -- end to end ----------------------------------------------------------------------
    def test_up_as_a_tail_then_down(self):
        conv = "11111111-2222-3333-4444-555555555555.jsonl"
        write(self.node_file(UID, conv), '{"turn": 1}\n')
        self.tick()
        self.assertEqual(read(self.ctl_file(UID, conv)), '{"turn": 1}\n')
        self.assertEqual(self.agent.ctl.sent[-1][0], "whole")
        write(self.node_file(UID, conv), '{"turn": 2}\n', mode="a")
        self.tick(fresh=False)
        self.assertEqual(read(self.ctl_file(UID, conv)), '{"turn": 1}\n{"turn": 2}\n')
        self.assertEqual(self.agent.ctl.sent[-1], ("append", len('{"turn": 2}\n')),
                         "a transcript goes up as its new tail")
        n = len(self.agent.ctl.sent)
        self.tick()
        self.tick()
        self.assertEqual(len(self.agent.ctl.sent), n, "agreed files are not sent again")
        # A memory written on the controller (the Memory tab) comes down.
        write(self.ctl_file(UID, "memory/note.md"), "remember\n")
        self.tick()
        self.assertEqual(read(self.node_file(UID, "memory/note.md")), "remember\n")
        self.tick()
        self.assertEqual(len(self.agent.ctl.sent), n, "what came down does not go back up")
        # ...and removed there, goes here.
        os.remove(self.ctl_file(UID, "memory/note.md"))
        self.tick()
        self.assertFalse(os.path.exists(self.node_file(UID, "memory/note.md")))

    def test_a_tail_that_does_not_match_goes_whole(self):
        conv = "c.jsonl"
        write(self.node_file(UID, conv), "aaaa\n")
        self.tick()
        write(self.ctl_file(UID, conv), "zzzz\nmore\n")   # not the bytes the node sent
        write(self.node_file(UID, conv), "bbbbbbbbbbbbbbbbbbbb\n", mode="a")
        self.tick()          # append refused (409): the controller's size is noted
        self.tick(fresh=False)
        self.tick(fresh=False)
        self.assertEqual(read(self.ctl_file(UID, conv)), read(self.node_file(UID, conv)))

    def test_a_long_conversation_waits_for_a_resume(self):
        write(self.ctl_file(UID, "long.jsonl"), "x" * (node_cs.PULL_MAX + 10))
        self.tick()
        self.assertFalse(os.path.exists(self.node_file(UID, "long.jsonl")))

    def test_only_the_projects_it_holds(self):
        other = os.path.join(self.node_ws, ".claude", UID, "projects", node_cs.slug(f"{self.node_ws}/beta"), "x.jsonl")
        write(other, "read-only project's\n")
        self.tick()
        self.assertEqual(self.agent.ctl.sent, [], "a project it only reads is not sent")
        q = {"uid": [UID], "path": [node_cs.slug(f"{self.node_ws}/beta") + "/x.jsonl"], "mode": ["whole"]}
        out, code = ctl_cs.put("n1", q, io.BytesIO(b"x"), 1)
        self.assertEqual(code, 403, out)
        q = {"uid": [UID], "path": [self.slug + "/../../../../etc/x"], "mode": ["whole"]}
        self.assertEqual(ctl_cs.put("n1", q, io.BytesIO(b"x"), 1)[1], 400)
        q = {"uid": ["root"], "path": [self.slug + "/x"], "mode": ["whole"]}
        self.assertEqual(ctl_cs.put("n1", q, io.BytesIO(b"x"), 1)[1], 400)

    def test_accounts_kept_apart(self):
        write(self.node_file(UID, "a.jsonl"), "mine\n")
        write(self.node_file(OTHER, "b.jsonl"), "theirs\n")
        self.tick()
        self.assertEqual(read(self.ctl_file(UID, "a.jsonl")), "mine\n")
        self.assertEqual(read(self.ctl_file(OTHER, "b.jsonl")), "theirs\n")
        self.assertFalse(os.path.exists(self.ctl_file(UID, "b.jsonl")))

    def test_the_folder_is_made_for_claude_projects_link(self):
        self.tick()
        self.assertTrue(os.path.isdir(os.path.join(self.node_ws, ".claude")))
        self.assertTrue(os.path.isfile(os.path.join(self.node_ws, ".claude", ".bbignore")))

    def test_nothing_while_mounted_or_not_synced(self):
        self.ws.mode = "off"
        self.tick()
        self.assertFalse(os.path.exists(os.path.join(self.node_ws, ".claude")))


if __name__ == "__main__":
    unittest.main()
