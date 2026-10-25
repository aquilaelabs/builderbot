"""Who a project belongs to and who joins it (the operator, 1 Oct).

Every project has an OWNER, an account: whoever made it, and BuilderBot's
owner for a project from before there were owners. The owner, and
BuilderBot's owner, may hand it to another account, make it INVITE ONLY,
and invite people.

INVITE ONLY is the owner's restriction on administrators. An administrator
sees every project and could always put any of them on any account's list,
their own included (by a role on it, on the Roles page); on an invite-only project only its
owner and BuilderBot's owner change who is on it, and everybody else comes
in by accepting an invitation. BuilderBot's owner is never kept out: it can
add itself to any project (the operator, 1 Oct).

HANDING IT ON: BuilderBot's owner moves a project to another account at
once. The project's own owner OFFERS it instead (the operator, 1 Oct): the
offer waits in the other person's bell like an invitation, and the project
changes hands only when they accept, and only if the one who offered still
owns it then. One offer per project at a time; a new one replaces it.

An INVITATION names an existing account, user or administrator. It waits in
the invitee's bell with Accept and Decline: accepting puts the project on
their list (users.take_on), declining drops it, and the one who invited, the
owner, or BuilderBot's owner may withdraw it. A session does none of this.

Two stores, keyed by project so a rename carries them (projects._KEYED):
project-owners.json {"projects": {name: {owner: uid, invite_only: bool}}}
and invites.json {"next": n, "projects": {name: [invite, ...]}}. Owners are
kept by uid, so renaming an account does not orphan anything.
"""
import json
import threading
import time
from pathlib import Path

import roles
import users

STATE = None
write_json = None
_lock = threading.RLock()


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


def _st():
    """The state directory: the server's, or the users store's where only
    that is configured (bb users removes an account with users.py alone)."""
    return STATE or users.STATE


def _write(name, d):
    w = write_json or users.write_json
    if w:
        w(_st() / name, d)
    else:
        (_st() / name).write_text(json.dumps(d))


def _read(name, empty):
    try:
        with open(_st() / name, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else empty
    except (OSError, ValueError):
        return empty


def _keyed(ps, merge=None):
    """{project: value} by project key (R138): an entry written under a
    repository's name before it was put in a project (an import, a clone, a
    folder recorded since migration 0010 ran) counts for its project, the
    project's own entry first; `merge` joins two that land on one key."""
    out = {}
    for k in sorted(ps, key=lambda k: users.key_of(k) != k):
        key = users.key_of(k)
        if key in out and merge:
            out[key] = merge(out[key], ps[k])
        else:
            out.setdefault(key, ps[k])
    return out


def _owners():
    d = _read("project-owners.json", {})
    d["projects"] = _keyed(d.get("projects") if isinstance(d.get("projects"), dict) else {})
    return d


def _invites():
    d = _read("invites.json", {})
    d["projects"] = _keyed(d.get("projects") if isinstance(d.get("projects"), dict) else {},
                           merge=lambda a, b: (a if isinstance(a, list) else []) + (b if isinstance(b, list) else []))
    d.setdefault("next", 1)
    return d


def _by_uid(uid):
    return next((u for u in users.all_users() if u.get("uid") == uid), None)


def _name_of(uid):
    return (_by_uid(uid) or {}).get("name") or ""


def owner_of(project):
    """The owning account's uid: the record's, or BuilderBot's owner. Kept
    by project (R138): a repository's owner is its project's."""
    rec = _owners()["projects"].get(users.key_of(project)) or {}
    return rec.get("owner") or users.owner_uid()


def owner_name(project):
    """The owning account's name, for a sentence or a row."""
    return _name_of(owner_of(project))


def invite_only(project):
    return bool((_owners()["projects"].get(users.key_of(project)) or {}).get("invite_only"))


def _is_bb_owner(me):
    return (me or {}).get("role") == "owner" and not (me or {}).get("session")


def may_manage(me, project):
    """Whether `me` may change the owner, the restriction and invitations:
    the project's owner, and BuilderBot's owner. Never a session."""
    if not me or me.get("session"):
        return False
    return _is_bb_owner(me) or users.uid_of(me) == owner_of(project)


def may_change_members(me, project):
    """Whether `me` may put this project on an account's list, or take it
    off one: whoever manages it, and, unless it is invite only, any
    administrator, as before owners existed."""
    if may_manage(me, project):
        return True
    return users.is_admin(me) and not invite_only(project)


def member_refusal(me, project, joining=False):
    """"" when `me` may change who is on `project`, else why not. `joining`
    is `me` adding themselves: BuilderBot's owner may join an invite-only
    project that way (R135), the one difference from an administrator,
    who waits for an invitation."""
    if may_change_members(me, project):
        return ""
    if joining and (me or {}).get("role") == "owner":
        return ""
    who = _name_of(owner_of(project)) or "its owner"
    if invite_only(project):
        return (f"{project} is invite only: {who} invites people to it, "
                "and an administrator joins by accepting one")
    return f"only {who} or an administrator changes who is on {project}"


def on_create(project, account):
    """Whoever made a project owns it."""
    project = users.key_of(project)
    u = users.get(account) if account else None
    if not u or not u.get("uid"):
        return
    with _lock:
        d = _owners()
        d["projects"].setdefault(project, {})["owner"] = u["uid"]
        _write("project-owners.json", d)
    # ...and holds PROJECT_owner on it (R152).
    users.give_owner_role(project, u["uid"])


def adopt(key, first):
    """A project (R138) owned as the repository it was made from was, invite
    only if that one was: what migration 0010 does for every repository."""
    with _lock:
        d = _owners()
        was = d["projects"].get(first) or {}
        rec = {k: was[k] for k in ("owner", "invite_only") if was.get(k)}
        if rec:
            d["projects"][key] = rec
            _write("project-owners.json", d)


def forget_account(uid):
    """An account removed: its invitations go, and a project it owned
    falls back to BuilderBot's owner rather than to nobody."""
    with _lock:
        i = _invites()
        changed = False
        for p, rows in i["projects"].items():
            keep = [r for r in rows if r.get("uid") != uid and r.get("by") != uid]
            if len(keep) != len(rows):
                i["projects"][p] = keep
                changed = True
        if changed:
            _write("invites.json", i)
        d = _owners()
        moved = False
        for rec in d["projects"].values():
            if rec.get("owner") == uid:
                rec.pop("owner", None)
                moved = True
        if moved:
            _write("project-owners.json", d)


def forget_project(project, live=()):
    """A project that will never be listed again (a create that never took,
    one deleted for good): its owner, its invitations, every account's roles
    on it and its PROJECT_owner role go (B95). Left, the Profile and the
    Roles page went on naming an owner of a clone that had failed and of
    one purged, two of them under one label. `live` is every live
    project's directory: a role name is cut to a length, so one another
    live project's owner role shares is kept."""
    project = str(project or "")
    if not project:
        return
    with _lock:
        d = _owners()
        if d["projects"].pop(project, None) is not None:
            _write("project-owners.json", d)
        i = _invites()
        if i["projects"].pop(project, None) is not None:
            _write("invites.json", i)
    users.forget_project(project)
    name = roles.owner_role_name(project)
    if not any(roles.owner_role_name(p) == name for p in live if p != project):
        roles.remove(name)
        users.forget_role(name)


def prune_gone(registry):
    """Every project's owner, owner role and account entries put away where
    the project is gone for good or was never made (no record, or purged):
    what forget_project does at the time, for what happened before it did
    (B95). A trashed project keeps them, for Put back. How many went."""
    recs = {k: (registry.get(k) or {}).get("state") for k in registry.labels()}
    if not recs:
        return 0                  # no record read at all is no reason to drop anything
    live = [k for k, st in recs.items() if st == "live"]
    gone = {p for p in _owners()["projects"] if recs.get(p) in (None, "purged")}
    for n, r in roles.all_roles().items():
        note = str(r.get("note") or "")
        if n.endswith("_owner") and note.startswith("the owner of "):
            p = note[len("the owner of "):]
            if recs.get(p) in (None, "purged") and roles.owner_role_name(p) == n:
                gone.add(p)
    for p in sorted(gone):
        forget_project(p, live=live)
    return len(gone)


def members(project):
    """The accounts this project is on, by name, BuilderBot's owner first."""
    project = users.key_of(project)
    out = []
    for u in users.all_users():
        have = u.get("projects") or []
        if "*" in have or project in have:
            out.append(u.get("name") or "")
    return sorted(out, key=lambda n: (n != users.owner_name(), n.lower()))


def view(me, project):
    """The project dialog's People: who owns it, whether it is invite only,
    who is on it, who is invited, and what `me` may do about any of it."""
    project = users.key_of(project)
    o = owner_of(project)
    every = _invites()["projects"].get(project) or []
    rows = [r for r in every if r.get("kind") != "owner"]
    offer = next((r for r in every if r.get("kind") == "owner"), None)
    manage = may_manage(me, project)
    invite = manage or (users.is_admin(me) and not invite_only(project))
    on = set(members(project))
    return {"project": project, "owner": _name_of(o), "invite_only": invite_only(project),
            "may_manage": manage,
            "may_invite": invite,
            "members": sorted(on),
            # Ownership offered and not yet accepted (the project's owner
            # hands it on; BuilderBot's owner moves it at once).
            "offer": {"id": offer["id"], "name": _name_of(offer["uid"]), "at": offer.get("at", 0)} if offer else None,
            "bb_owner": _is_bb_owner(me),
            "invites": [
                {"id": r["id"], "name": _name_of(r["uid"]), "by": _name_of(r.get("by") or ""),
                 "at": r.get("at", 0), "role": r.get("role") or ""} for r in rows],
            # Who could be invited or made owner: every account, named, and
            # only to somebody who may invite or manage (B21); a member has
            # no use for the controller's whole list of accounts.
            "accounts": sorted(u.get("name") or "" for u in users.all_users()) if invite else [],
            # The roles an invitation may offer: those on a project (R155).
            "roles": sorted(n for n, r in roles.all_roles().items()
                            if r.get("scope") == "projects" and not n.endswith("_owner"))}


def set_owner(me, project, owner="", restrict=None):
    """Hand the project to another account, and/or make it invite only.
    (payload, status)."""
    project = users.key_of(project)
    if not may_manage(me, project):
        return {"error": f"only {project}'s owner, or BuilderBot's, changes who owns it "
                         "and whether it is invite only"}, 403
    offered = ""
    moved_to = ""
    with _lock:
        d = _owners()
        rec = d["projects"].setdefault(project, {})
        if owner:
            u = users.get(owner)
            if not u or not u.get("uid"):
                return {"error": f"no account called {owner}"}, 400
            if u["uid"] == owner_of(project):
                pass
            elif _is_bb_owner(me):
                rec["owner"] = u["uid"]
                # The owner works on what it owns, and holds its owner role.
                users.take_on(owner, project)
                moved_to = u["uid"]
            else:
                # The project's own owner offers it: it changes hands when
                # the other person accepts, from their bell.
                i = _invites()
                rows = [r for r in i["projects"].get(project) or [] if r.get("kind") != "owner"]
                rows.append({"id": int(i["next"]), "uid": u["uid"], "by": users.uid_of(me),
                             "at": int(time.time()), "kind": "owner"})
                i["projects"][project] = rows
                i["next"] = int(i["next"]) + 1
                _write("invites.json", i)
                offered = owner
        if restrict is not None:
            rec["invite_only"] = bool(restrict)
        _write("project-owners.json", d)
    if moved_to:
        users.give_owner_role(project, moved_to)
    return view(me, project) | ({"offered": offered} if offered else {}), 200


def invite(me, project, name, role=""):
    """Invite an existing account to the project, as a role on it: being on
    a project is holding a role there (R155), so an invitation says which
    one, and accepting gives it. (payload, status)."""
    project = users.key_of(project)
    if not (may_manage(me, project) or (users.is_admin(me) and not invite_only(project))):
        return {"error": member_refusal(me, project) or "you may not invite people to it"}, 403
    u = users.get(name)
    if not u or not u.get("uid"):
        return {"error": f"no account called {name}"}, 400
    r = roles.get(role) if role else None
    if not r or r.get("scope") != "projects":
        return {"error": "pick the role they are invited as: a role on a project"}, 400
    if name in members(project):
        return {"error": f"{name} is on {project} already"}, 400
    with _lock:
        d = _invites()
        rows = d["projects"].setdefault(project, [])
        if any(r.get("uid") == u["uid"] for r in rows):
            return {"error": f"{name} is invited to {project} already"}, 400
        rows.append({"id": int(d["next"]), "uid": u["uid"], "by": users.uid_of(me),
                     "at": int(time.time()), "role": role})
        d["next"] = int(d["next"]) + 1
        _write("invites.json", d)
    return view(me, project), 200


def _find(d, iid):
    for p, rows in d["projects"].items():
        for r in rows:
            if r.get("id") == iid:
                return p, r
    return None, None


def withdraw(me, iid):
    """The one who invited, or whoever manages the project, takes it back."""
    with _lock:
        d = _invites()
        p, r = _find(d, iid)
        if not r:
            return {"error": "no such invitation"}, 404
        if r.get("by") != users.uid_of(me) and not may_manage(me, p):
            return {"error": "only who invited them, or the project's owner, withdraws it"}, 403
        d["projects"][p] = [x for x in d["projects"][p] if x.get("id") != iid]
        _write("invites.json", d)
    return view(me, p), 200


def answer(me, iid, accept):
    """The invitee's Accept or Decline, from the bell. (payload, status)."""
    if not me or me.get("session"):
        return {"error": "a person answers an invitation"}, 403
    with _lock:
        d = _invites()
        p, r = _find(d, iid)
        if not r or r.get("uid") != users.uid_of(me):
            return {"error": "no such invitation for you"}, 404
        d["projects"][p] = [x for x in d["projects"][p] if x.get("id") != iid]
        _write("invites.json", d)
    if accept and r.get("kind") == "owner":
        # Only from whoever still owns it: an offer made before the project
        # changed hands another way is no longer theirs to make.
        if r.get("by") != owner_of(p):
            return {"error": f"{p} changed hands since that was offered, so it is not theirs to give"}, 409
        with _lock:
            d = _owners()
            d["projects"].setdefault(p, {})["owner"] = users.uid_of(me)
            _write("project-owners.json", d)
        users.give_owner_role(p, users.uid_of(me))
    if accept:
        got = users.take_on(me.get("name") or "", p)
        if got.get("error"):
            return got, 400
        # The role it was offered as: what makes them on it (R155).
        if r.get("role"):
            users.give_project_role(p, users.uid_of(me), r["role"])
    return {"ok": True, "project": p, "joined": bool(accept),
            "owner": bool(accept) and r.get("kind") == "owner"}, 200


def mine(me):
    """The invitations waiting on this account, for its bell."""
    uid = users.uid_of(me)
    if not uid or (me or {}).get("session"):
        return []
    out = []
    for p, rows in _invites()["projects"].items():
        for r in rows:
            if r.get("uid") == uid:
                out.append({"id": r["id"], "project": p, "by": _name_of(r.get("by") or ""),
                            "at": r.get("at", 0), "kind": r.get("kind") or "join",
                            "role": r.get("role") or ""})
    return out


def verb(me, req):
    """POST /api/members. (payload, status)."""
    act = str(req.get("action") or "view")
    project = str(req.get("project") or "")
    if act == "accept" or act == "decline":
        try:
            return answer(me, int(req.get("id")), act == "accept")
        except (TypeError, ValueError):
            return {"error": "which invitation?"}, 400
    if act == "withdraw":
        try:
            return withdraw(me, int(req.get("id")))
        except (TypeError, ValueError):
            return {"error": "which invitation?"}, 400
    if not project:
        return {"error": "which project?"}, 400
    if act == "view":
        return view(me, project), 200
    if act == "set":
        r = req.get("invite_only")
        return set_owner(me, project, str(req.get("owner") or ""), None if r is None else bool(r))
    if act == "invite":
        return invite(me, project, str(req.get("name") or ""), str(req.get("role") or ""))
    return {"error": f"unknown action {act!r}"}, 400
