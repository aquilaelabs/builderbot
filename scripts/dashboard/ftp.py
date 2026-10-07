"""A project's file access over FTP (R151, the operator, 7 Oct): whether it
is on, the port, and which accounts may sign in to it with read or read and
write, kept in ftp.json by project.

The server is the node's: the ftp toolchain's bb-ftpd, one per project,
started by the agent on the project's primary node from what hello hands it
(for_node). It never sees a password's answer. Each login is relayed by the
agent to the ftp-auth verb, which lands in login() here: the name and the
password checked as the dashboard's sign-in checks them, then the access
this project's settings give that account. Nothing is cached on the node,
so taking an access away holds from the next login.

Who may change any of it is the `ftp` grant, named only (roles.NAMED_ONLY),
so the owner has it and nobody else until a role names it.
"""
import threading
import time
from pathlib import Path

FILE = None
WORKSPACE = None
write_json = None
users = None
audit = None
project_node = None          # project -> its primary node id, "" for none
ask_hello = None             # node id -> the agent is told now, not in ten minutes
node_agent = None            # node id -> the version its agent runs, "" when unknown

# The first agent that runs bb-ftpd (FtpServers). One older takes hello's
# list and does nothing with it, so the section says so rather than waiting.
FTP_AGENT = (0, 7, 141)

ACCESS = ("r", "rw")
PORT_MIN, PORT_MAX = 1024, 65535
# The port and the nine after it, which bb-ftpd's passive data connections
# use (bbftp.PASSIVE): two projects on one node are kept this far apart.
SPAN = 10
# The node's own: the session terminals (the agent's SESSION_PORT and its
# read-only twin).
RESERVED = {7681: "the node's session terminal", 7682: "the node's read-only session terminal"}

_lock = threading.Lock()
# What each node's agent last said about its servers: {node: {project:
# {"up", "why", "addr", "port", "at"}}}. In memory: the agent says it again
# after every change and every hello.
_status = {}
# Failed logins by address, for the throttle: {addr: [times]}.
_fails = {}
FAIL_WINDOW_S = 300
FAIL_LIMIT = 10


def configure(*, state, workspace, write_json, users, audit, project_node, ask_hello=None, node_agent=None):
    globals().update(FILE=Path(state) / "ftp.json", WORKSPACE=Path(workspace), write_json=write_json,
                     users=users, audit=audit, project_node=project_node, ask_hello=ask_hello,
                     node_agent=node_agent)


def _too_old(version):
    """Why this agent version cannot run file access, or ""."""
    try:
        have = tuple(int(x) for x in str(version).split(".")[:3])
    except ValueError:
        return ""
    if len(have) == 3 and have < FTP_AGENT:
        return (f"its node's agent is {version}, and file access needs "
                f"{'.'.join(map(str, FTP_AGENT))} or newer: Update agent on the Nodes tab")
    return ""


def _load():
    import json
    try:
        d = json.loads(FILE.read_text())
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    return d if isinstance(d, dict) else {}


def _clean(rec):
    rec = rec if isinstance(rec, dict) else {}
    try:
        port = int(rec.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    acc = rec.get("access") if isinstance(rec.get("access"), dict) else {}
    return {"on": bool(rec.get("on")), "port": port,
            "access": {str(k): v for k, v in acc.items() if v in ACCESS}}


def get(project):
    with _lock:
        return _clean(_load().get(project))


def _port_why(project, port, node, d):
    """Why this port cannot be this project's on `node`, or ""."""
    if not PORT_MIN <= port <= PORT_MAX - (SPAN - 1):
        return f"a port from {PORT_MIN} to {PORT_MAX - (SPAN - 1)}, since the nine after it carry the data"
    for p, why in RESERVED.items():
        if port <= p < port + SPAN:
            return f"{p} is {why}; pick a port at least {SPAN} away from it"
    for other, rec in d.items():
        rec = _clean(rec)
        if other == project or not rec["on"] or not rec["port"]:
            continue
        if node and project_node(other) == node and abs(rec["port"] - port) < SPAN:
            return (f"{other} uses {rec['port']} to {rec['port'] + SPAN - 1} on the same node; "
                    f"keep {SPAN} ports apart, since each server uses its port and the nine after it")
    return ""


def free_port(project, node, d=None):
    """The first port from 2121 up, in steps of SPAN, that nothing on the
    node takes: the one a project is offered when it has none."""
    d = _load() if d is None else d
    port = 2121
    while port <= PORT_MAX - SPAN and _port_why(project, port, node, d):
        port += SPAN
    return port


def save(project, req, by):
    """{on, port, access: {uid: "r"|"rw"|""}} as the settings send it. The
    caller has checked the ftp grant. (payload, status)."""
    node = project_node(project) or ""
    with _lock:
        d = _load()
        rec = _clean(d.get(project))
        if "on" in req:
            rec["on"] = bool(req.get("on"))
        if "port" in req:
            try:
                rec["port"] = int(req.get("port") or 0)
            except (TypeError, ValueError):
                return {"error": "the port is a number"}, 400
        if rec["on"] and not rec["port"]:
            rec["port"] = free_port(project, node, d)
        if rec["on"]:
            if not node:
                return {"error": "this project has no node to run its file access on: "
                                 "pick one under Where it runs"}, 400
            why = _port_why(project, rec["port"], node, d)
            if why:
                return {"error": f"port {rec['port']}: {why}"}, 400
        if isinstance(req.get("access"), dict):
            known = {users.uid_of(u) for u in users.all_users()}
            for uid, a in req["access"].items():
                uid = str(uid)
                if uid not in known:
                    continue
                if a in ACCESS:
                    rec["access"][uid] = a
                else:
                    rec["access"].pop(uid, None)
        d[project] = rec
        write_json(FILE, d, mode=0o600)
    audit(by, "ftp", project, {"on": rec["on"], "port": rec["port"], "access": rec["access"]})
    if node and ask_hello:
        ask_hello(node)
    return view(project, True), 200


def for_node(node):
    """What `node`'s agent runs: every project whose primary node it is,
    with file access on and a tree to serve. Rides hello."""
    out = []
    with _lock:
        d = _load()
    for project, rec in sorted(d.items()):
        rec = _clean(rec)
        if rec["on"] and rec["port"] and project_node(project) == node \
                and (WORKSPACE / project).is_dir():
            out.append({"project": project, "port": rec["port"], "root": f"/workspace/{project}"})
    return out


def report(node, servers):
    """The agent's word on its servers: [{project, up, why, addr, port}]."""
    rows = {}
    for s in servers if isinstance(servers, list) else []:
        if not isinstance(s, dict) or not s.get("project"):
            continue
        rows[str(s["project"])[:120]] = {"up": bool(s.get("up")), "why": str(s.get("why") or "")[:300],
                                         "addr": str(s.get("addr") or "")[:80],
                                         "port": int(s.get("port") or 0), "at": int(time.time())}
    with _lock:
        _status[node] = rows
    return {"ok": True}, 200


def view(project, may_set):
    """What the settings' File access section draws: the record, every
    account that can see the project with its access, and what the node
    said about the server."""
    rec = get(project)
    node = project_node(project) or ""
    people = []
    for u in sorted(users.all_users(), key=lambda u: u["name"].lower()):
        if not users.may_see(u, project):
            continue
        uid = users.uid_of(u)
        people.append({"uid": uid, "name": u["name"], "access": rec["access"].get(uid, ""),
                       "role": u.get("role") or "user"})
    with _lock:
        st = dict((_status.get(node) or {}).get(project) or {})
    # Nothing heard yet: an agent too old to run it never will be.
    if rec["on"] and not st and node and node_agent:
        why = _too_old(node_agent(node) or "")
        if why:
            st = {"up": False, "why": why}
    return {"on": rec["on"], "port": rec["port"] or free_port(project, node),
            "node": node, "people": people, "status": st, "may_set": bool(may_set), "span": SPAN}


def _throttled(addr):
    now = time.time()
    with _lock:
        ts = [t for t in _fails.get(addr, []) if now - t < FAIL_WINDOW_S]
        _fails[addr] = ts
        if len(_fails) > 1000:
            for a in [a for a, v in _fails.items() if not v]:
                _fails.pop(a, None)
        return len(ts) >= FAIL_LIMIT


def _failed(addr):
    with _lock:
        _fails.setdefault(addr, []).append(time.time())


def login(node, project, name, password, addr):
    """One FTP login, relayed by `node`'s agent: {"access": "r"|"rw"} when
    this account may, else {"access": "", "why"}. The why is the server's
    to show and says no more than a sign-in page would."""
    addr = str(addr or "")[:80]
    denied = {"access": "", "why": "Authentication failed."}
    rec = get(project)
    if not rec["on"] or project_node(project) != node:
        return denied
    if _throttled(addr):
        return {"access": "", "why": "Too many failed logins from this address; try again in a few minutes."}
    u = users.authenticate(str(name or ""), str(password or ""))
    if not u:
        _failed(addr)
        audit(f"ftp:{addr}", "ftp-login-failed", project, {"name": str(name or "")[:60]})
        return denied
    access = rec["access"].get(users.uid_of(u), "")
    # Taken off the project since: its access went with it.
    if access and not users.may_see(u, project):
        access = ""
    if not access:
        audit(u["name"], "ftp-login-refused", project, {"addr": addr})
        return {"access": "", "why": "This account has no file access to this project."}
    audit(u["name"], "ftp-login", project, {"addr": addr, "access": access})
    return {"access": access}
