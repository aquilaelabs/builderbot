"""Behind `bb settings` (cmd_settings in bb): a project's settings as the
dashboard holds them (dashboard/prefs.py), read for a session or bb-tty,
and the three a session may set (build, test, outputs), which go through
the approval queue.

The first argument is the verb, `set` or `show`, then the dashboard
directory and the project. For `set`, BB_SET_FIELD and BB_SET_VALUE are
the field and its value; for `show`, BB_SETTINGS_JSON=1 asks for the
record as JSON. DASHBOARD_STATE says where the dashboard's files are and
BB_ACCOUNT_UID which seat this session sits in.
"""
import contextlib
import json
import os
import sys

import dash

verb, here, proj = sys.argv[1], sys.argv[2], sys.argv[3]


def set_field():
    sys.path.insert(0, here)
    import prefs, pending
    def _w(path, obj):
        tmp = str(path) + ".tmp"
        with open(tmp, "w") as f: json.dump(obj, f)
        os.replace(tmp, path)
    prefs.configure(state=os.environ["DASHBOARD_STATE"], write_json=_w)
    pending.configure(state=os.environ["DASHBOARD_STATE"], write_json=_w)
    field, value = os.environ["BB_SET_FIELD"], os.environ["BB_SET_VALUE"]
    r = prefs.session_set(proj, **{field: value})
    if r.get("error"):
        print("[builderbot] ERROR: " + r["error"], file=sys.stderr); raise SystemExit(1)
    if r.get("held"):
        print(f"held for approval: {field} for {proj} lands in its settings when the operator "
              "approves it on the notebook; you are told on a later turn what they decided")
    else:
        print(f"set {field} for {proj}: {value}")


def push_state(state, proj):
    """{rights, auth}: rights is whether the controller granted a push at all;
    auth is "ssh", "token", "none" (an https remote with no credential) or
    "" (no origin)."""
    try:
        rights = isinstance(json.load(open(os.path.join(state, "push-rights.json"))).get(proj), dict)
    except (OSError, ValueError, AttributeError):
        rights = False
    tree = os.path.join(os.environ.get("WORKSPACE", "/workspace"), proj)
    url = helper = ""
    try:
        import subprocess
        url = subprocess.run(["git", "-C", tree, "remote", "get-url", "origin"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()
        helper = subprocess.run(["git", "-C", tree, "config", "--local", "--get-all", "credential.helper"],
                                capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        pass
    auth = ("" if not url
            else "ssh" if url.startswith(("git@", "ssh://")) or (":" in url and "://" not in url)
            else "token" if "store --file=" in helper
            else "none")
    return {"rights": rights, "auth": auth}


def _bb_owner(state):
    try:
        us = json.load(open(os.path.join(state, "users.json"))).get("users") or {}
    except (OSError, ValueError, AttributeError):
        return ""
    return next((u.get("uid") or "" for u in us.values() if isinstance(u, dict) and u.get("role") == "owner"), "")


def _owner_of(state, proj):
    try:
        rec = (json.load(open(os.path.join(state, "project-owners.json"))).get("projects") or {}).get(proj) or {}
    except (OSError, ValueError, AttributeError):
        rec = {}
    return rec.get("owner") or _bb_owner(state)


def show():
    state = os.environ["DASHBOARD_STATE"]
    prefs = dash.load("prefs", here)
    prefs.configure(state=state, write_json=lambda *a: None)
    rec = dict(prefs.get(proj) or {})
    # The model, the effort and any commit-author override are the ACCOUNT's on
    # this project, not the project's (prefs.for_user): two people on one project
    # are two authors on two models. BB_ACCOUNT_UID names the seat; no seat means
    # nothing set, which is claude's own default.
    _mine = prefs.for_user(os.environ.get("BB_ACCOUNT_UID", ""), proj) if proj else {}
    rec["model"], rec["effort"] = _mine.get("model", ""), _mine.get("effort", "")
    # ...and each other agent's pair (R95 step 19), which its launcher reads
    # at exec as Claude's reads these two.
    rec.update({k: v for k, v in _mine.items() if k.endswith(("_model", "_effort"))})
    try:
        locks = json.load(open(os.path.join(state, "locked-projects.json")))
    except (OSError, ValueError):
        locks = {}
    lk = locks.get(proj) if isinstance(locks, dict) else None
    # Locked AGAINST this seat (R119): an administrator's lock holds
    # everybody, its owner's everybody but the owner. The owner as
    # membership.owner_of reads it: the record's, or BuilderBot's owner for a
    # project from before there were owners, who is also the seat with no
    # uid of its own.
    rec["locked"] = isinstance(lk, dict) and (bool(lk.get("admin")) or (
        os.environ.get("BB_ACCOUNT_UID", "") or _bb_owner(state)) != _owner_of(state, proj))
    rec["project"] = proj
    # The toolchains this project's sessions may not use (R77), whole: the
    # shipped ones switched off here, and every tool pack not switched on.
    # bb-tty takes them out of a session's PATH and its view of the store.
    try:
        packs = list((json.load(open(os.path.join(state, "toolpacks.json"))).get("packs") or {}))
    except (OSError, ValueError, AttributeError):
        packs = []
    on = set(rec.get("packs_on") or [])
    rec["toolchains_off"] = sorted(set(rec.get("tc_off") or []) | {p for p in packs if p not in on})
    # Whether a push can happen at all (B734): the rights the controller
    # granted (push-rights.json, the clone dialog's or Link to a git host),
    # and what the remote authenticates with: an ssh address carries its
    # key, an https one needs the token the controller scoped into the
    # tree's config, and one with neither is refused by git with a prompt
    # error, late. Read from the files, never by running git's network half.
    rec["push"] = push_state(state, proj)
    # The commit identity is the ACCOUNT's (users.py's git_identity), for bb-tty
    # to put in a session's environment: BB_ACCOUNT_UID names the seat, and no
    # seat means the owner's. Read from the store directly rather than through
    # users.py, which wants the dashboard's configure(); the shape is two fields.
    def _identity(uid):
        """(name, email, found): found says the seat matched an account at all,
        so a stale uid (a deleted account, an old tab) is not read as an
        account with no author and told to fill in a Profile it cannot open."""
        try:
            with open(os.path.join(state, "users.json")) as f:
                store = json.load(f).get("users") or {}
        except (OSError, ValueError):
            return "", "", False
        for u in store.values():
            if not isinstance(u, dict):
                continue
            if (uid and u.get("uid") == uid) or (not uid and u.get("role") == "owner"):
                pr = u.get("prefs") if isinstance(u.get("prefs"), dict) else {}
                return (str(pr.get("git_name") or pr.get("full_name") or ""),
                        str(pr.get("git_email") or pr.get("email") or ""), True)
        return "", "", False
    rec["git_name"], rec["git_email"], _found = _identity(os.environ.get("BB_ACCOUNT_UID", ""))
    # ...with this project's override ahead of it, field by field, the way
    # users.identity_over resolves it. So somebody whose Profile carries no email
    # can still commit here, which is the whole point of the override.
    if _mine.get("git_name"):
        rec["git_name"] = _mine["git_name"]
        _found = True
    if _mine.get("git_email"):
        rec["git_email"] = _mine["git_email"]
        _found = True
    if _found:
        rec["git_ready"] = bool(rec["git_name"] and rec["git_email"])
    if os.environ.get("BB_SETTINGS_JSON") == "1":
        print(json.dumps(rec))
        raise SystemExit(0)
    print(f"{proj}:")
    # Nodes by the names the Nodes page shows (B58): the record keeps ids,
    # which say nothing to a person or a session reading this.
    named = {}
    with contextlib.suppress(Exception):
        nodes = dash.load("nodes", here)
        nodes.db.open_readonly(state)
        named = {n["id"]: n["name"] for n in nodes.node_list(all=True)}
    for k in ("node", "nodes", "reads", "sees", "model", "effort", "build", "test", "outputs", "policy", "locked",
              "toolchains_off"):
        v = rec.get(k)
        if v in (None, "", [], False):
            continue
        if k in ("node", "nodes"):
            v = [named.get(x, x) for x in v] if isinstance(v, list) else named.get(v, v)
        print(f"  {k:<8} {', '.join(v) if isinstance(v, list) else v}")
    # The agents' settings as the dialog names them, so a session can read
    # its own dials (the review of 26 Sep: the briefing said the refusal
    # names the setting, and nothing here showed it).
    print("  Agents' settings:")
    print(f"    While a test runs: a change asked for   {rec.get('test_change') or 'wait'}")
    print(f"    Tests run                               {rec.get('tests_in') or 'node'}")
    print(f"    Captures kept (days; 0 keeps them)      {rec.get('capture_days', 7)}")
    print(f"    Snapshots kept (days; 0 takes none)     {rec.get('snapshot_days', 14)}")
    print(f"    Dev builds kept of each (0 keeps all)   {rec.get('dev_keep', 3)}")
    # Every dial, each as it stands. The five the notebook gates are kept
    # together under `gate`, and read from the record's top they were never
    # found: the list showed two dials of seven, and a session told that
    # its save goes through Add to the design could not see that dial (two
    # reports from other projects, 29 Sep).
    gate = rec.get("gate") if isinstance(rec.get("gate"), dict) else {}
    for label, key in (("Add to roadmap", "roadmap"), ("File bugs", "bugs"), ("Add rules", "rules"),
                       ("Fill in build and test", "settings"), ("Add to the design", "design"),
                       ("Write the wiki", "wiki")):
        print(f"    Agents may: {label:<28} {gate.get(key) or 'auto'}")
    for label, key, dflt in (("Run its container", "devbuild", "deny"),
                             # R91: its VMs, bb vm.
                             ("Make VMs", "makevms", "deny"),
                             ("Report BuilderBot bugs", "report", "auto"),
                             # R106: signing a build, and its keys and mapping.
                             ("Sign a build", "sign", "ask"),
                             ("Manage signing keys", "keys", "ask"),
                             # R138: the tag and the forge's release.
                             ("Tag and publish a release", "release", "ask"),
                             # R270 step 6: a person's PC lent by the companion.
                             ("Use a lent PC", "pc", "deny")):
        print(f"    Agents may: {label:<28} {rec.get(key) or dflt}")
    # Who may move the version is version.py's policy rather than a prefs
    # dial, and an owner who set every dial above to auto still found it
    # locked (report #48): printed with them, in the dial's own words.
    try:
        version = dash.load("version", here)
        version.configure(workspace=os.environ.get("WORKSPACE", "/workspace"), state=state,
                          write_json=lambda *a: None)
        print(f"    Agents may: {'Move the version':<28} {version.policy(proj)}")
    except Exception as e:  # noqa: BLE001 (an unreadable policy is said, not a crash)
        print(f"    Agents may: {'Move the version':<28} unknown ({str(e)[:60]})")


def set_node():
    """The project's node from a shell on the controller (R84), saved as its
    Settings page saves it. A project with containers is sent to that page:
    moving it there keeps them on the node they run on, which needs the
    running dashboard."""
    sys.path.insert(0, here)
    import prefs, dash
    def _w(path, obj):
        tmp = str(path) + ".tmp"
        with open(tmp, "w") as f: json.dump(obj, f)
        os.replace(tmp, path)
    state = os.environ["DASHBOARD_STATE"]
    prefs.configure(state=state, write_json=_w)
    # The running dashboard's hooks, which a shell has none of: no container
    # to pin (one with containers is refused below), and a session or a
    # network to tell is the dashboard's next look at the setting.
    prefs.WORKSPACE = os.environ.get("WORKSPACE", "/workspace")
    prefs.pin_instances = lambda name: []
    prefs.end_agents = lambda name: {}
    prefs.net_nudge = lambda: None
    want = os.environ["BB_SET_VALUE"].strip()
    with contextlib.suppress(OSError, ValueError):
        if (json.load(open(os.path.join(state, "devapps.json"))) or {}).get(proj):
            sys.exit(f"[builderbot] ERROR: {proj} has containers: change its node on its Settings page, "
                     "which keeps them on the machine they run on")
    nodes = dash.load("nodes", dash.beside(os.path.join(here, "nodes.py")))
    nodes.db.open_readonly(state)
    hit = [n for n in nodes.node_list() if n.get("kind") == "agent" and n.get("state") != "retired"
           and want in (n.get("id"), n.get("name"))]
    if not hit:
        sys.exit(f"[builderbot] ERROR: no node called {want}: bb nodes lists them")
    body, code = prefs.dialog_save(proj, {"node": hit[0]["id"]}, "")
    if body.get("error"):
        sys.exit("[builderbot] ERROR: " + body["error"])
    print(f"{proj} works on {hit[0]['name']} ({hit[0]['id']})")


{"set": set_field, "show": show, "node": set_node}[verb]()
