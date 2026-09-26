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
    try:
        locks = json.load(open(os.path.join(state, "locked-projects.json")))
    except (OSError, ValueError):
        locks = []
    rec["locked"] = proj in (locks if isinstance(locks, list) else [])
    rec["project"] = proj
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
    for k in ("node", "model", "effort", "build", "test", "outputs", "policy", "locked"):
        v = rec.get(k)
        if v in (None, "", [], False):
            continue
        print(f"  {k:<8} {', '.join(v) if isinstance(v, list) else v}")
    # The Claude settings as the dialog names them, so a session can read
    # its own dials (the review of 26 Sep: the briefing said the refusal
    # names the setting, and nothing here showed it).
    print("  Claude settings:")
    print(f"    During a test run, a change asked for   {rec.get('test_change') or 'wait'}")
    print(f"    Briefing a session reads                {rec.get('brief') or 'full'}")
    print(f"    Tests run                               {rec.get('tests_in') or 'node'}")
    for label, key in (("Add to roadmap", "roadmap"), ("File bugs", "bugs"), ("Add rules", "rules"),
                       ("Fill in build and test", "settings"), ("Run its container", "devbuild"),
                       ("Report BuilderBot bugs", "report")):
        if rec.get(key) not in (None, ""):
            print(f"    Claude may: {label:<28} {rec.get(key)}")


{"set": set_field, "show": show}[verb]()
