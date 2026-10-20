#!/usr/bin/env python3
"""A person's devices (R272 step 1): an app a person signed in with on a
machine of their own (the Windows companion today; the phone and an editor
in time), each holding a token of its own that acts as that person for the
app's calls and nothing else.

A device token is `bbd_` and a secret, kept as its sha256 in the store's
devices table, as a node's is. It is minted by the app's sign-in, which
checks the person's password once and never keeps it, and it is accepted
only on the device routes (/api/v1/device/*), which the server answers apart
from the dashboard's, so a device token can never read a page or start a
session. It is revoked from the Devices list, one at a time, and dies with
the account; changing the password leaves it, since the app never had it.

The account is found by its uid on every call, so a rename keeps a person's
devices and a removed account takes them with it. When the app last called
is written at most once a minute: what the Devices list shows, not a log.
"""
import hashlib
import secrets
import time

import db
import wssync
from db import _exec, _rows, mint

PREFIX = "bbd_"
KINDS = ("pc", "phone", "editor")
SEEN_EVERY = 60                 # seconds between writes of a device's last call
NAME_MAX = 60

USERS = None                    # () -> users.load(): who an account is, by uid
ACCESS = None                   # (account, project) -> "rw" | "r" | "": the editor's door, ftp.access_for
PROJECTS = None                 # (account) -> [project names this account may see]
WAIT_MAX = 25                   # seconds a device's long poll is held
# The door's compatibility window (R270 step 9, R79 step 8), as the agent's:
# an app says which door it speaks in X-BB-Door (none is 1) and which app and
# release it is in X-BB-App ("companion/0.3.1"), and one from before DOOR_MIN
# is refused with the way to update rather than half working. The controller
# says its own DOOR and DOOR_MIN in the projects and apps answers, so an app
# newer than its controller says so too. DOOR moves with a change an older
# app would misread; DOOR_MIN with the removal of what it superseded, never
# before the release after the apps were changed (test/device-api.json pins
# what each released app reads).
DOOR = 1
DOOR_MIN = 1


def door_refused(said, app=""):
    """Why an app speaking door `said` is refused, or "". `app` is its
    X-BB-App, named in the refusal when it said one."""
    try:
        n = int(said or 1)
    except (TypeError, ValueError):
        n = 0
    if n >= DOOR_MIN:
        return ""
    who = " ".join(str(app or "").split())[:60] or "this app"
    return (f"{who} speaks the controller's door {n} and the controller needs {DOOR_MIN} or newer: "
            "update the app from the Apps page, or let it update itself")


def configure(*, users, access=None, projects=None):
    global USERS, ACCESS, PROJECTS
    USERS, ACCESS, PROJECTS = users, access, projects
    wssync.configure_devices(name_of=_name_of)


def _name_of(did):
    rows = _rows("SELECT name FROM devices WHERE id = ?", (did,))
    return rows[0]["name"] if rows else did


def _hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _account(uid):
    """The account whose minted id this is, with its name, or None."""
    for name, rec in ((USERS() if USERS else {}).get("users") or {}).items():
        if isinstance(rec, dict) and rec.get("uid") == uid:
            return {**rec, "name": name}
    return None


def mint_for(account, name, kind):
    """A new device for this account: (its row, the token to hand the app
    once). The name is what the app says it is (the machine's), cut to
    fit; the kind one of KINDS."""
    uid = (account or {}).get("uid") or ""
    if not uid:
        return None, {"error": "only an account signs in a device"}
    if kind not in KINDS:
        return None, {"error": f"a device is one of {', '.join(KINDS)}"}
    name = " ".join(str(name or "").split())[:NAME_MAX] or "a device"
    secret = secrets.token_urlsafe(32)
    did, now = mint("d"), int(time.time())
    _exec("INSERT INTO devices (id, uid, name, kind, secret_hash, created, seen, revoked) "
          "VALUES (?, ?, ?, ?, ?, ?, ?, 0)", (did, uid, name, kind, _hash(secret), now, now))
    db.audit(f"user:{account.get('name', '')}", "device-signin", did, {"name": name, "kind": kind})
    return {"id": did, "name": name, "kind": kind, "created": now, "seen": now}, {"token": PREFIX + secret}


def authenticate(bearer):
    """A device token to its device and account, or the reason it is not
    one. Fail-closed as a node's is: unknown and revoked read the same."""
    bearer = (bearer or "").strip()
    if not bearer.startswith(PREFIX):
        return {"error": "not a device token"}
    rows = _rows("SELECT * FROM devices WHERE secret_hash = ?", (_hash(bearer[len(PREFIX):]),))
    if not rows or rows[0]["revoked"]:
        return {"error": "this device is signed out: sign in again"}
    d = rows[0]
    account = _account(d["uid"])
    if not account:
        return {"error": "this device is signed out: sign in again"}
    now = int(time.time())
    if not d["seen"] or now - d["seen"] >= SEEN_EVERY:
        _exec("UPDATE devices SET seen = ? WHERE id = ?", (now, d["id"]))
    return {"device": d["id"], "name": d["name"], "kind": d["kind"], "account": account}


def listed(account):
    """This account's devices, newest call first, never their secrets."""
    uid = (account or {}).get("uid") or ""
    if not uid:
        return []
    rows = _rows("SELECT id, name, kind, created, seen FROM devices WHERE uid = ? AND revoked = 0 "
                 "ORDER BY COALESCE(seen, created) DESC", (uid,))
    return [dict(r) for r in rows]


def revoke(account, did, by=""):
    """Sign one of this account's devices out. Another account's id is not
    found, the same as one that does not exist. `by` is an administrator
    doing it for them (R272 step 8: a lost laptop cut off without its
    owner), the audit's principal in place of the account's own."""
    uid = (account or {}).get("uid") or ""
    rows = _rows("SELECT id, name FROM devices WHERE id = ? AND uid = ? AND revoked = 0", (str(did or ""), uid))
    if not uid or not rows:
        return {"error": "no such device"}
    _exec("UPDATE devices SET revoked = 1 WHERE id = ?", (rows[0]["id"],))
    db.audit(f"user:{by or account.get('name', '')}", "device-signout", rows[0]["id"],
             {"name": rows[0]["name"], "of": account.get("name", "")})
    return {"ok": True}


# ---- the device's door: what its app may ask (/api/v1/device/VERB) ---------------
# The server reads the token and the HTTP; each verb here answers
# (payload, status). A device acts as its person through the same door the
# editor uses: a project the person may edit there (ftp.access_for's
# "editor" door) comes down and goes up, one they may read comes down only,
# any other is not there. The sync is the node's (wssync), with the device in
# a node's place: R270 step 2.

def _access(auth, project):
    if not project or not ACCESS:
        return ""
    got = ACCESS(auth["account"], project)
    return got[0] if isinstance(got, tuple) else (got or "")


def _nid(auth):
    return wssync.DEV + auth["device"]


APPS = None
PC = None               # pcwork.py: a PC lent to a project (R270 step 6)


def configure_pc(mod):
    globals()["PC"] = mod


def configure_apps(mod):
    """apps.py, for the apps verb and app-file: how a device's app keeps
    itself current (R270 step 9)."""
    globals()["APPS"] = mod


def verb(name, auth, req):
    """A JSON verb: whoami, projects, sync (state, since with an optional
    wait), apps (what this controller holds for the apps to update from)."""
    if auth.get("error"):
        return {"error": auth["error"]}, 401
    if name == "pc-work" and PC:
        # What the app lends, only on projects its person may edit, and the
        # requests waiting for it, held as a long poll.
        lends = req.get("projects") if isinstance(req.get("projects"), dict) else {}
        PC.lend(auth["device"], auth["account"]["name"], auth["name"],
                {p: v for p, v in lends.items() if _access(auth, p) == "rw"}, uid=auth["account"].get("uid", ""))
        try:
            wait = min(float(req.get("wait") or 0), WAIT_MAX)
        except (TypeError, ValueError):
            wait = 0
        return {"work": PC.work(auth["device"], wait)}, 200
    if name == "pc-result" and PC:
        return PC.result(auth["device"], req.get("id"), req)
    if name == "apps":
        v = APPS.view() if APPS else {"apps": []}
        return {"version": v.get("version", ""), "door": DOOR, "door_min": DOOR_MIN,
                "apps": [{k: a[k] for k in ("name", "version", "files")} for a in v["apps"] if a["offered"]]}, 200
    if name == "whoami":
        return {"device": auth["device"], "name": auth["name"], "kind": auth["kind"],
                "account": auth["account"]["name"]}, 200
    if name == "projects":
        out = []
        for p in (PROJECTS(auth["account"]) if PROJECTS else []):
            a = _access(auth, p)
            if a:
                out.append({"project": p, "access": a, "rev": wssync.rev_of(p)})
        return {"projects": out, "door": DOOR, "door_min": DOOR_MIN}, 200
    if name == "sync":
        act, project = str(req.get("action") or ""), str(req.get("project") or "")
        if not _access(auth, project):
            return {"error": f"{project or 'that project'} is not one this account may edit or read from an app: "
                             "its editor access is set in the project's settings"}, 403
        if act == "state":
            return wssync.state(_nid(auth), project)
        if act == "since":
            try:
                rev, wait = int(req.get("rev") or 0), min(float(req.get("wait") or 0), WAIT_MAX)
            except (TypeError, ValueError):
                return {"error": "rev and wait are numbers"}, 400
            if wait > 0:
                wssync.wait_moved(project, rev, wait)
            return wssync.since(_nid(auth), project, rev)
        return {"error": f"no such sync action: {act}"}, 400
    return {"error": f"no such verb: {name}"}, 404


def file_verb(name, auth, q):
    """A file down: sync-file (one file) or sync-tar (the project whole, for
    the first copy), or app-file (an app this controller holds). Answers
    the agent's shape: {path | stream, ctype, headers}, 200, or a refusal."""
    if auth.get("error"):
        return {"error": auth["error"]}, 401
    if name == "app-file":
        p = APPS.path(q.get("app", [""])[0], q.get("file", [""])[0]) if APPS else None
        if not p:
            return {"error": "this controller holds no such app file"}, 404
        return {"path": p, "ctype": "application/octet-stream", "headers": {}}, 200
    project = q.get("project", [""])[0]
    if not _access(auth, project):
        return {"error": "not a project this account may read from an app"}, 403
    if name == "sync-file":
        path, no = wssync.file_path(_nid(auth), project, q.get("path", [""])[0])
        return no if no else ({"path": path, "ctype": "application/octet-stream", "headers": {}}, 200)
    write, no = wssync.tar_writer(_nid(auth), project)
    return no if no else ({"stream": write, "ctype": "application/x-tar", "headers": {}}, 200)


def put(auth, q, stream, length):
    """A file up: sync-put, the node's, for a project its person may edit."""
    if auth.get("error"):
        return {"error": auth["error"]}, 401
    project = q.get("project", [""])[0]
    if _access(auth, project) != "rw":
        return {"error": f"{project or 'that project'} is read-only for this account"}, 403
    return wssync.put(_nid(auth), project, q, stream, length)
