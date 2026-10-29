"""Behind five probes bb makes of the machine it is on, for `bb doctor` and
the verbs that share its questions (gpu_gles_ok, project_node and
cmd_doctor in bb): does hardware GLES work here, which node a project is
assigned, whether the accounts carry a commit identity, whether any node
can run a session, and which account each coding agent on this machine is
signed in as.

The first argument is the probe: `egl` (prints the vendor, exits 1 for
none or for Mesa), `prefs PROJECT` (prints the project's node, or nothing),
`id`, `node NODES_PY`, `login` (Claude's) and `signed AGENT` (Codex's or
Copilot's: prints the account, exits 1 for none). DASHBOARD_STATE says where the
dashboard's files are.
"""
import ctypes
import json
import os
import sys

import dash

verb, args = sys.argv[1], sys.argv[2:]


def gles():
    try:
        egl = ctypes.CDLL("libEGL.so.1")
    except OSError:
        sys.exit(1)
    egl.eglQueryString.restype = ctypes.c_char_p
    d = egl.eglGetDisplay(0)
    if not d:
        sys.exit(1)
    maj, mnr = ctypes.c_int(), ctypes.c_int()
    if not egl.eglInitialize(d, ctypes.byref(maj), ctypes.byref(mnr)):
        sys.exit(1)
    v = egl.eglQueryString(d, 0x3053)
    v = v.decode() if v else ""
    # Mesa answering means llvmpipe: a display, but software behind it, which is
    # the trap this check exists to catch. Only a vendor driver counts.
    if not v or "Mesa" in v:
        sys.exit(1)
    print(v)


def prefs():
    """The repository's node: its project's (R138), as the server's overlay
    reads it, the repository's own record where it is in no project."""
    st = os.environ["DASHBOARD_STATE"]
    try:
        d = json.load(open(os.path.join(st, "claude-prefs.json")))
    except (OSError, ValueError):
        print("")
        return
    try:
        groups = (json.load(open(os.path.join(st, "project-repos.json"))).get("projects") or {})
    except (OSError, ValueError, AttributeError):
        groups = {}
    key = next((k for k, g in groups.items() if isinstance(g, dict) and args[0] in (g.get("members") or [])), "")
    ps = d.get("projects") or {}
    print(((ps.get(key) or {}).get("node") if key else "") or (ps.get(args[0]) or {}).get("node") or "")


def identity():
    try:
        d = json.load(open(os.path.join(os.environ["DASHBOARD_STATE"], "users.json")))
        us = d.get("users") or {}
    except Exception:                                                # noqa: BLE001
        us = {}
    def has(u):
        p = u.get("prefs") or {}                # users.profile() reads the same keys
        return bool((p.get("git_email") or p.get("email")) and (p.get("git_name") or p.get("full_name")))
    n, m = sum(1 for u in us.values() if has(u)), len(us)
    if not m:
        print("  [skip] no accounts yet")
    elif n == m:
        print(f"  [ok]   every account has a commit identity ({m})")
    elif n:
        # Not a warning: an account without one is told on its own Claude
        # buttons and Profile, and the operator's card is not where
        # somebody else's missing email belongs (the operator, 28 Sep).
        # Nothing here is theirs to fix.
        print(f"  [ok]   commit identity on {n} of {m} accounts")
        print("         an account without one is told on its own Claude buttons and Profile, not here")
    else:
        print("  [warn] no account has a commit identity yet: set one on the Profile page"
              " (the gear in the header) before opening a session")


def node():
    nodes = dash.load("nodes", dash.beside(args[0]))
    try:
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        rows = nodes.node_list()
    except Exception:                                                # noqa: BLE001
        print("  [skip] no node store yet: the dashboard creates it on boot")
        raise SystemExit(0) from None
    # The same test the sign-in and the terminal proxy make, in the same words:
    # an agent node, online, still dialing in, reporting a session half that is
    # up. Anything less cannot hold a session or a login.
    live = [n["name"] for n in rows
            if n["kind"] == "agent" and n["state"] == "online" and n.get("live") is not False
            and ((n.get("reported") or {}).get("session") or {}).get("up")]
    if live:
        print(f"  [ok]   {len(live)} node{'' if len(live) == 1 else 's'} can run a session "
              f"({', '.join(live[:4])})")
    else:
        print("  [warn] no node can run a session, and this container carries no Claude Code")
        print("         enroll one on the Nodes page, or wait for one to come back: a node")
        print("         that has just restarted or updated its agent is back in a minute")
    for n in rows:
        wall(nodes, n)


def wall(nodes, n):
    """The controller's own machine as a node (R90): whether the wall
    between its sessions and this controller holds, as its bb-session last
    told it (the census's isolation, `bb-session check`). Said in red when it
    does not, since no session starts there until it does."""
    if not nodes.own_machine(n) or n.get("state") == "retired":
        return
    rep = n.get("reported") or {}
    iso = rep.get("isolation") if isinstance(rep.get("isolation"), dict) else None
    name = n.get("name") or n.get("id")
    if n.get("state") != "online" or n.get("live") is False or iso is None:
        print(f"  [warn] the wall on this controller's own node ({name}) is not known: the node has not")
        print("         reported since it was enrolled, so no session runs there until it does")
    elif iso.get("sessions"):
        print(f"  [ok]   the wall holds on this controller's own node ({name}): its sessions reach")
        print("         none of the controller's state, secrets, ports or docker")
    else:
        print(f"  [FAIL] the wall on this controller's own node ({name}) is not in force, so no")
        print("         session starts there: " + str(iso.get("why") or "bb-session check failed")[:400])


def login():
    try:
        e = (json.load(open(os.path.expanduser("~/.claude.json"))).get("oauthAccount") or {}).get("emailAddress")
    except Exception:
        e = ""
    sys.stdout.write(f" ({e})" if e else "")


def signed():
    """Codex's, Copilot's or Grok's account here, read as `bb login --list` reads
    it (login-list.py), so doctor and the Installed page cannot disagree."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "login_list", os.path.join(os.path.dirname(os.path.abspath(__file__)), "login-list.py"))
    ll = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ll)
    got = {"codex": ll.codex_of, "copilot": ll.copilot_of, "grok": ll.grok_of}[args[0]](os.path.expanduser("~"))
    if not got or not got.get("email"):
        sys.exit(1)
    sys.stdout.write(f" ({got['email']})")


{"egl": gles, "prefs": prefs, "id": identity, "node": node, "login": login, "signed": signed}[verb]()
