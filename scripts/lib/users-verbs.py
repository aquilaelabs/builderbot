"""Behind `bb users` (cmd_users in bb): the dashboard's accounts
(dashboard/users.py): list them, set a password, add one, or mint a
session token for one project.

The first argument is the verb (list, passwd, add, token), then users.py's
path. `token` takes the project and, optionally, the account the token is
for; `passwd` and `add` take the account's name (and --role for add), with
the password in BB_USERS_PW, read rather than passed. DASHBOARD_STATE says
where the store is.
"""
import json
import os
import sys

import dash

verb, py, args = sys.argv[1], sys.argv[2], sys.argv[3:]
users = dash.load("users", dash.beside(py))


# A real write, not a no-op: the signing key is made on first use and kept
# in the store, and a token signed with a key that was never written is one
# the dashboard cannot verify.
def write_json(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


users.configure(state=os.environ["DASHBOARD_STATE"], write_json=write_json)


def token():
    uid = ""
    if args[1]:
        uid = (users.load()["users"].get(args[1]) or {}).get("uid") or ""
        if not uid:
            sys.exit(f"[builderbot] ERROR: no account called {args[1]}")
    print(users.mint_session(args[0], uid=uid))


def accounts():
    sub, rest = verb, args
    pw = os.environ.get("BB_USERS_PW", "")
    if sub == "list":
        rows = users.all_users()
        if not rows:
            print("no accounts yet; open the dashboard and it will ask you to "
                  "make the owner")
        for u in rows:
            seen = "never" if not u["seen"] else f"{(int(__import__('time').time()) - u['seen']) // 86400}d ago"
            projects = ", ".join(u["projects"]) or "-"
            print(f'{u["name"]:<24} {u["role"]:<8} seen {seen:<10} {projects}')
        raise SystemExit(0)
    name = rest[0]
    # --seen (B135): the account starts having read the guide and this
    # image's changelog, for one a script makes for somebody it shows the
    # dashboard to already (a seeded teammate, a classroom's accounts), where
    # the welcome window opened over everything at the first sign-in.
    seen = "--seen" in rest

    def mark_seen():
        if seen:
            users.prefs_set(name, {"welcome_seen": True,
                                   "image_seen": os.environ.get("BB_IMAGE_REV", "").strip()[:40]})
    # The owner, as the first-run page makes it (R84): for a setup scripted
    # from a shell rather than clicked through. Refused once there is one.
    if sub == "claim":
        r = users.claim(name, pw)
        if r.get("error"):
            print(r["error"], file=sys.stderr)
            raise SystemExit(1)
        mark_seen()
        print(f"{name}: created as the owner")
        raise SystemExit(0)
    if sub == "passwd":
        r = users.set_password(name, pw)
    else:
        role = "user"
        if "--role" in rest:
            role = rest[rest.index("--role") + 1]
        # No accounts at all means this is the first one, and the first one is the
        # owner whatever was asked for: a store whose only account cannot
        # administer it is a store nobody can use.
        # Made as the first-run page makes it (users.claim), so it has an id
        # like every other account: written by hand here it had none, and
        # the owner had no transcripts, no projects of its own and tokens
        # naming nobody (diag report #116).
        if not users.all_users():
            r = users.claim(name, pw)
            if r.get("error"):
                print(r["error"], file=sys.stderr)
                raise SystemExit(1)
            mark_seen()
            print(f"{name}: created as the owner, since it is the first account")
            raise SystemExit(0)
        r = users.add(name, pw, role=role)
        if not r.get("error"):
            mark_seen()
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    print(f'{name}: {"password changed" if sub == "passwd" else "created"}')


{"token": token, "list": accounts, "passwd": accounts, "add": accounts, "claim": accounts}[verb]()
