"""A project's node, stood in for in a unit test of signing.py's key work.

signing._on_node queues a sign-key job and waits for it. Here the job is run
the moment it is queued, by the real agent's sign_key (work.py, keyops.py)
against a toolchain store this machine has, its channel calls answered by
signing's own hand_over, take_result, handover_file and put_signed, as
channel.py answers them. So a test drives the controller's side and the
node's together, with the store's real keytool and apksigner, and nothing of
the controller runs a tool itself.
"""
import glob
import os
import shutil

import agentpkg

agent = agentpkg.load("builderbot_agent_signnode")
agent.log = lambda *a, **k: None


def _store(build_tools):
    for d in sorted(glob.glob("/mnt/SDK/*") + glob.glob("/sdk/*")):
        if not os.access(os.path.join(d, "jdk", "bin", "keytool"), os.X_OK):
            continue
        if build_tools and not agent.module("keyops").build_tools(d):
            continue
        return d
    return ""


# A store with a jdk, and one with the build-tools as well.
STORE = _store(False)
STORE_BT = _store(True)


class Job:
    def __init__(self, jid):
        self.job, self.outputs, self.lines = {"id": jid}, [], []

    def say(self, t):
        self.lines.append(t)


class Node:
    """Install with install(test, signing); `jobs` holds what ran, each
    with its spec, end state and log lines."""

    def __init__(self, signing, data, store):
        self.signing, self.data, self.store = signing, data, store
        self.jobs, self.n = {}, 0

    def add(self, principal, placement, type_, spec, project=""):
        self.n += 1
        jid = f"j_{self.n}"
        rec = {"id": jid, "type": type_, "spec": spec, "project": project, "node": placement.get("node"),
               "state": "running", "principal": principal}
        self.jobs[jid] = rec
        s, tok = self.signing, spec.get("handover")

        class Ctl:
            def call(_, verb, body=None, timeout=30):
                if verb == "signing-key":
                    got, st, _said = s.hand_over(tok, jid, (body or {}).get("package") or "")
                    return st, got
                if verb == "signing-result":
                    got, st = s.take_result(tok, jid, body or {})
                    return st, got
                return 404, {"error": verb}

            def fetch(_, path, dest, timeout=600):
                p = s.handover_file(tok, jid)
                if not p:
                    return 404, {}
                shutil.copyfile(p, dest)
                return 200, {}

            def upload(_, path, src, timeout=600, **kw):
                with open(src, "rb") as f:
                    got, st = s.put_signed(tok, jid, f, os.path.getsize(src))
                return st, got
        a = object.__new__(agent.Agent)
        a.state = {"user": "builder", "stores": {"data": self.data}}
        a.session_account = lambda: "sessions"
        a.drop_privileges = lambda env: {}
        a.ctl = Ctl()
        job = Job(jid)
        rec["state"], rec["code"] = a.sign_key(job, spec)
        rec["log"] = "".join(job.lines)
        return {"ok": True, "job": jid}

    def get(self, jid, with_log=True):
        return self.jobs.get(jid)


def install(test, signing, data, store=None):
    """The node, for one test: signing's node hooks pointed at it, the agent
    running as root over a store, all put back after."""
    node = Node(signing, data, STORE if store is None else store)
    for k in ("node_of", "node_get", "node_tools", "node_refuses", "job_add", "job_get", "job_cancel"):
        test.addCleanup(setattr, signing, k, getattr(signing, k))
    signing.node_of = lambda p: "n_1"
    signing.node_get = signing.node_tools = signing.node_refuses = signing.job_cancel = None
    signing.job_add = node.add
    signing.job_get = node.get
    was_euid, was_root = agent.os.geteuid, agent.tc_root
    test.addCleanup(setattr, agent.os, "geteuid", was_euid)
    test.addCleanup(setattr, agent, "tc_root", was_root)
    agent.os.geteuid = lambda: 0
    agent.tc_root = lambda st: node.store
    # The job's own folder, on this machine's memory in a real node (B315):
    # here beside the data store, so a test sees what is left in each.
    was_work = agent.SIGN_WORK
    test.addCleanup(setattr, agent, "SIGN_WORK", was_work)
    agent.SIGN_WORK = os.path.join(os.path.dirname(data), "signwork")
    return node
