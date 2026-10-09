"""Claude Code on the nodes: which version each runs, what the latest is,
and the one way it is updated.

A session runs on a node, and the node carries Claude Code in the session
account's home (the native installer). The agent probes `claude --version`
there on every heartbeat, so the controller always knows what each node
runs; what it did not know was what is out. This asks the installer's own
answer, the `latest` file the install script reads first, once after the
controller starts, then on the toolchains' clock (weekly, and when a node
starts) and on a press of Check for updates on a node's Toolchains tab,
where Claude Code is a row like any toolchain (R145): installed there on
purpose, never by the provisioner, and required for a session. A node
behind is a row in the bell and says so on that row.

UPDATING IS A PERSON'S, NEVER A SESSION'S. Install on the Toolchains tab is an
administrator's action (the node handler refuses anybody else, a session's
token included); it ends every Claude session on that node first, since a
conversation mid-turn is the wrong place to swap the binary under, and
queues a job the agent runs as the session account: the installer, then,
where the agent is root, a copy of the binary into a root-owned directory
the session's PATH reads before the account's own. That copy is what a
session runs and what the account cannot write, so `claude update` typed
in a session changes nothing that runs, and the auto-updater is off there
already (bb-tty exports DISABLE_AUTOUPDATER). Nobody starts the sessions
again: the project rows do, when a person presses them; while the job
runs those rows are held with the reason.

No bb verb reaches any of this, on purpose.
"""
import os
import re
import threading
import time
import http.client
import urllib.request

LATEST_URL = (os.environ.get("BB_CLAUDE_LATEST_URL")
              or "https://downloads.claude.ai/claude-code-releases/latest")
CHECK_DELAY = float(os.environ.get("BB_CLAUDE_CHECK_DELAY") or 20)
JOB = "claude-update"
VER = re.compile(r"(\d+\.\d+\.\d+)")

nodes = None               # nodes.py: node, node_list, job_add, jobs_for, session_kill
node_sessions = None       # server.node_tmux_sessions
tmux_base = None           # server.tmux_base
audit = None
_lock = threading.Lock()
_latest = {"version": "", "at": 0, "error": "", "checking": False}
# {node id: when} for an update pressed and not yet queued: ending the
# node's sessions comes first and is a round trip each, and in those
# seconds the hold read nothing, so a project's Claude button was live and
# a press on it started a session the update was about to end (the
# operator, 29 Sep). The job is the fact once it exists; this is the fact
# until then.
_pressed = {}


def configure(*, nodes_module, node_sessions, tmux_base, audit=None):
    globals().update(nodes=nodes_module, node_sessions=node_sessions,
                     tmux_base=tmux_base, audit=audit)


def check():
    """Ask what the latest Claude Code is, now. Returns the record."""
    with _lock:
        if _latest["checking"]:
            return dict(_latest)
        _latest["checking"] = True
    version, error = "", ""
    try:
        with urllib.request.urlopen(LATEST_URL, timeout=15) as r:   # noqa: S310 (a fixed https URL, or a test's file://)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            text = r.read(200).decode("utf-8", "replace").strip()
        m = VER.match(text)
        if m:
            version = m.group(1)
        else:
            error = f"unexpected answer from the download service: {text[:40]!r}"
    except (OSError, http.client.HTTPException, ValueError) as e:   # URLError and a timeout are OSErrors; a bad URL is a ValueError
        error = f"could not reach the download service: {e}"[:200]
    with _lock:
        _latest.update(checking=False, at=int(time.time()), error=error)
        if version:
            _latest["version"] = version
        return dict(_latest)


def latest():
    with _lock:
        return dict(_latest)


def installed(n):
    """The version a node reports, or "" (no session account, or no
    Claude Code for it): `1.2.3` out of `1.2.3 (Claude Code)`."""
    m = VER.search(str(((n.get("reported") or {}).get("session") or {}).get("claude") or ""))
    return m.group(1) if m else ""


def _tup(v):
    return tuple(int(x) for x in v.split("."))


def behind(n):
    i, cur = installed(n), latest()["version"]
    return bool(i and cur and _tup(i) < _tup(cur))


def update_done(job, state):
    """The census catches up with an update the moment it finishes (B249).
    The version the controller compares rides the agent's census, which
    rides its hello every ten minutes, so the bell and the row said an
    update was out for up to ten minutes after the job installed it. The
    job's last line names what it measured, and that is what the row says
    until the next hello replaces the whole record. The agent says hello
    right after as well; this covers the seconds between, and a hello that
    did not land."""
    if state != "succeeded" or nodes is None or not job:
        return None
    full = nodes.job(job["id"], with_log=True) or {}
    # A removal (R145): none now, so the row and the session gate say so
    # before the next hello does.
    if (job.get("spec") or full.get("spec") or {}).get("action") == "remove":
        nodes.reported_set(job["node"], "session", "claude", "")
        return None
    m = re.search(r"Claude Code (\S+) is what a session here runs now", full.get("log") or "")
    if m:
        nodes.reported_set(job["node"], "session", "claude", m.group(1) + " (Claude Code)")
    return None


def updating(node_id):
    """True while an update job is queued or running on the node: the fact
    the holds and the section read, taken from the job list rather than a
    flag, so a restart cannot leave a hold up with nothing behind it."""
    if nodes is None:
        return False
    if time.time() - _pressed.get(node_id, 0) < 120:
        return True
    return any(j.get("type") == JOB for j in nodes.jobs_for(node_id, n=20, type=JOB, active=True))


def rows():
    out = {}
    for n in nodes.node_list() if nodes else []:
        if n.get("kind") != "agent":
            continue
        out[n["id"]] = {"name": n["name"], "installed": installed(n), "behind": behind(n),
                        "updating": updating(n["id"]), "live": bool(n.get("live"))}
    return out


def payload():
    """What the Nodes tab reads: the latest known, when it was asked, and
    each agent node's own version against it."""
    cur = latest()
    return {"latest": cur["version"], "checked": cur["at"], "error": cur["error"],
            "checking": cur["checking"], "nodes": rows()}


def attention(project_nodes):
    """Bell rows: every live agent node whose Claude Code is behind and not
    already updating, with the projects that run sessions there."""
    out = []
    for n in nodes.node_list() if nodes else []:
        if n.get("kind") != "agent" or not n.get("live") or not behind(n) or updating(n["id"]):
            continue
        out.append({"kind": "claude", "node": n["name"], "id": n["id"],
                    "from": installed(n), "to": latest()["version"],
                    "projects": sorted(p for p, nid in project_nodes.items() if nid == n["id"])})
    return out


def holds(reap=False):
    """{node id: why} while no session can start on a node's Claude Code:
    while it is being updated (the project rows start them again after),
    and where it is not installed at all, which the node's Toolchains tab
    does on purpose (R145: the provisioner no longer installs it).

    reap: only the holds that end a session already running, for the
    sweep. Not installed is not one: a running session shows it was there,
    so the reading is stale or wrong, and the sweep ended the harness's
    sessions every second on it (B540); remove() ends them itself."""
    out = {}
    for n in nodes.node_list() if nodes else []:
        if n.get("kind") != "agent":
            continue
        if updating(n["id"]):
            out[n["id"]] = (f"Claude Code is updating on {n['name']}: its Claude sessions were ended for "
                            "it, and start again from the project rows when it is done")
        elif missing(n) and not reap:
            out[n["id"]] = (f"Claude Code is not installed on {n['name']}: its Toolchains tab installs it")
    return out


def missing(n):
    """True when a node runs a session account and has measured no Claude
    Code for it: a session there has nothing to run."""
    se = (n.get("reported") or {}).get("session") or {}
    return bool(se.get("up")) and "claude" in se and not installed(n)


def remove(principal, node_id):
    """End the Claude sessions on the node and queue the job that takes
    Claude Code off it (R145), the update job's other action."""
    n = nodes.node(node_id) if nodes else None
    if not n or n.get("kind") != "agent":
        return {"error": "only an agent node runs Claude Code"}
    if not installed(n):
        return {"error": f"Claude Code is not installed on {n['name']}"}
    if updating(node_id):
        return {"error": f"a Claude Code job is already queued on {n['name']}"}
    ended = []
    for s in node_sessions() if node_sessions else []:
        if s.get("node_id") == node_id and tmux_base(s["name"]).startswith("claude-"):
            r = nodes.session_kill(node_id, s.get("node_name") or s["name"])
            if not r.get("error"):
                ended.append(s["name"])
    r = nodes.job_add(principal, {"node": node_id}, JOB, {"timeout": 300, "action": "remove", "ended": ended})
    if r.get("ok") and audit:
        audit(principal, "node-claude-remove", node_id, {"ended": ended})
    return r


def update(principal, node_id):
    """End the Claude sessions on the node and queue the update job. The
    caller has already decided who may ask: the node handler, which is an
    administrator's and refuses a session's token."""
    n = nodes.node(node_id) if nodes else None
    if not n:
        return {"error": "no such node"}
    if n.get("kind") != "agent":
        return {"error": "only an agent node runs Claude Code"}
    if not n.get("live"):
        return {"error": f"{n['name']} is not dialing in; nothing reaches it right now"}
    se = (n.get("reported") or {}).get("session") or {}
    if not se.get("up"):
        return {"error": f"{n['name']} runs no session account, so there is no Claude Code there to update"}
    if updating(node_id):
        return {"error": f"an update is already queued on {n['name']}"}
    _pressed[node_id] = time.time()
    try:
        ended = []
        for s in node_sessions() if node_sessions else []:
            if s.get("node_id") == node_id and tmux_base(s["name"]).startswith("claude-"):
                r = nodes.session_kill(node_id, s.get("node_name") or s["name"])
                if not r.get("error"):
                    ended.append(s["name"])
        r = nodes.job_add(principal, {"node": node_id}, JOB,
                          {"timeout": 900, "to": latest()["version"], "ended": ended})
    finally:
        _pressed.pop(node_id, None)
    if r.get("ok"):
        if audit:
            audit(principal, "node-claude-update", node_id, {"to": latest()["version"], "ended": ended})
        r = r | {"ended": ended}
    return r


def start_hold(project, node_id):
    """A sentence when a Claude session on this node has to wait for Claude
    Code, or "": an update running there holds every start until it ends.
    Nothing updates by itself: a node stays on what it has until Update is
    pressed (the switch that updated a node behind before a session started
    went on 7 Oct, the operator's)."""
    n = nodes.node(node_id) if nodes else None
    if not n or n.get("kind") != "agent":
        return ""
    if updating(node_id):
        return (f"Claude Code is updating on {n['name']}: press Claude on {project} again when its "
                "row comes back")
    return ""


def start():
    """One check soon after the controller starts. After that it is asked on
    the toolchains' own clock (toolchains.node_checks_due: weekly, and when
    a node starts) and on a press of Check for updates, like every other
    toolchain (R145). The update itself is never on a clock: a press."""
    def once():
        time.sleep(CHECK_DELAY)
        try:
            check()
        except Exception as e:                                      # noqa: BLE001 (a thread must not die loudly)
            print(f"dashboard: claude code check: {e}", flush=True)
    threading.Thread(target=once, name="claude-code", daemon=True).start()
