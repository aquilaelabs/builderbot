"""Behind five probes bb makes of the machine it is on, for `bb doctor` and
the verbs that share its questions (gpu_gles_ok, project_node and
cmd_doctor in bb): does hardware GLES work here, which node a project is
assigned, whether the accounts carry a commit identity, whether any node
can run a session, and which Claude account this machine is signed in as.

The first argument is the probe: `egl` (prints the vendor, exits 1 for
none or for Mesa), `prefs PROJECT` (prints the project's node, or nothing),
`id`, `node NODES_PY` and `login`. DASHBOARD_STATE says where the
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
    try:
        d = json.load(open(os.path.join(os.environ["DASHBOARD_STATE"], "claude-prefs.json")))
        print((d.get("projects") or {}).get(args[0], {}).get("node") or "")
    except (OSError, ValueError):
        print("")


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


def login():
    try:
        e = (json.load(open(os.path.expanduser("~/.claude.json"))).get("oauthAccount") or {}).get("emailAddress")
    except Exception:
        e = ""
    sys.stdout.write(f" ({e})" if e else "")


{"egl": gles, "prefs": prefs, "id": identity, "node": node, "login": login}[verb]()
