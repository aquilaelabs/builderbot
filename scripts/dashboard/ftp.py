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
import socket
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
node_info = None             # node id -> {"name", "addr", "has_ftp": True|False|None}

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


def configure(*, state, workspace, write_json, users, audit, project_node, ask_hello=None, node_info=None):
    globals().update(FILE=Path(state) / "ftp.json", WORKSPACE=Path(workspace), write_json=write_json,
                     users=users, audit=audit, project_node=project_node, ask_hello=ask_hello,
                     node_info=node_info)


def _node(node):
    return (node_info(node) if node and node_info else None) or {}


def missing_why(node):
    """Why `node` cannot run file access before anything is tried, or "":
    the ftp toolchain not in its store, as its last report says. Unknown is
    not missing."""
    n = _node(node)
    if n.get("has_ftp") is False:
        return (f"{n.get('name') or 'its node'} does not have the ftp toolchain: "
                "install it on the Toolchains page")
    return ""


def _answers(addr, port, timeout=0.8):
    """True when something accepts a connection there, False when it is
    refused, None when nothing was heard (a firewall that drops, a node
    that is away)."""
    try:
        with socket.create_connection((addr, port), timeout=timeout):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return None


def ports_taken(node, port):
    """Of the port and the nine after it, the ones something on `node`
    already answers on, asked from here at once. Empty when none do, or
    when the node's address is not known."""
    addr = _node(node).get("addr") or ""
    if not addr:
        return []
    got = {}
    ts = [threading.Thread(target=lambda p=p: got.__setitem__(p, _answers(addr, p)), daemon=True)
          for p in range(port, port + SPAN)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(2)
    return sorted(p for p, v in got.items() if v)


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
    return {"on": bool(rec.get("on")), "port": port, "editor": bool(rec.get("editor")),
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
        # The editor's door (R159): the same people and access, through the
        # controller's Files API rather than an FTPS server on the node.
        if "editor" in req:
            rec["editor"] = bool(req.get("editor"))
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
                                 "pick one under Nodes in its settings"}, 400
            why = _port_why(project, rec["port"], node, d)
            if why:
                return {"error": f"port {rec['port']}: {why}"}, 400
            # Something else on the node already on it (the operator, 7
            # Oct): asked when it is turned on or moved, never of the
            # project's own server, which holds the port it already has.
            was = _clean(d.get(project))
            # Read without the lock, which save holds: one dict read.
            mine = (_status.get(node) or {}).get(project) or {}
            ours = mine.get("up") and mine.get("port") == rec["port"]
            if (not was["on"] or was["port"] != rec["port"]) and not ours:
                taken = ports_taken(node, rec["port"])
                if taken:
                    name = _node(node).get("name") or "its node"
                    which = (f"port {taken[0]} is" if len(taken) == 1
                             else "ports " + ", ".join(map(str, taken)) + " are")
                    return {"error": f"{which} already in use on {name}; the server needs {rec['port']} "
                                     f"and the {SPAN - 1} after it free, so pick another"}, 400
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
    audit(by, "ftp", project, {"on": rec["on"], "port": rec["port"], "editor": rec["editor"],
                               "access": rec["access"]})
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
    # Nothing heard yet: a node without the toolchain has nothing to run.
    if rec["on"] and not st and node:
        why = missing_why(node)
        if why:
            st = {"up": False, "why": why}
    return {"missing": missing_why(node), "on": rec["on"], "editor": rec["editor"],
            "port": rec["port"] or free_port(project, node),
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
    access, why = access_for(u, project, "ftp")
    if not access:
        audit(u["name"], "ftp-login-refused", project, {"addr": addr, "why": why})
        return {"access": "", "why": why}
    audit(u["name"], "ftp-login", project, {"addr": addr, "access": access})
    return {"access": access}


def access_for(u, project, door):
    """(access, why): what this account may do with `project`'s files
    through `door`, "ftp" (the node's FTPS server) or "editor" (the Files
    API the VS Code extension uses, R159). "r" or "rw", or "" with the
    sentence why not. The one answer both doors give, asked afresh on every
    login and every request, so access taken away holds from the next one.
    A session is never a person and has the tree already: none."""
    rec = get(project)
    if not u or u.get("session"):
        return "", "This account has no file access to this project."
    if not rec["on" if door == "ftp" else "editor"]:
        return "", ("File access over FTPS is off for this project." if door == "ftp" else
                    "Opening this project in an editor is off in its settings (File access).")
    access = rec["access"].get(users.uid_of(u), "")
    # Taken off the project since: its access went with it.
    if access and not users.may_see(u, project):
        access = ""
    # ...and no more than the account's roles give on this project (R152
    # (f)): a role without File access refuses even the project's owner.
    lvl = users.roles.level_of(u, "files", project, users.may_work)
    if access and not lvl:
        return "", "Your roles give no file access to this project."
    if access == "rw" and lvl == "read":
        access = "r"
    if not access:
        return "", "This account has no file access to this project."
    return access, ""
