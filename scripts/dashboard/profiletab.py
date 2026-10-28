"""The signed-in account's own settings: the Profile page.

Anybody signed in, because this is about themselves, which is why it is not
behind the admin gate the Users page wears. Out of server.py (R77): the
server holds the door and writes the reply, with a fresh sign-in cookie when
the account's name changes, since that is what the cookie is signed over.
"""
from fields import field
from timing import timed

# The server's, set by configure(): the account store, the Claude login an
# account's home carries, the Claude plugins an account installed per node,
# and the nodes' names.
users = None
claude_email = None      # uid -> the Claude account signed in for it, or ""
agent_emails = None      # uid -> {agent id: the accounts it is signed in as} (B296)
plugins_of = None        # (uid, {node id: name}) -> its plugins, as the nodes last said
node_names = None        # () -> {node id: name}
logs_of = None           # me -> the account's conversations with Claude (transcripts.mine)
devices = None           # devices.py: the account's signed-in devices (R272), listed and signed out
logins = None            # logins.py: the account's browser sign-ins (R158 step 8), listed and ended
reach = None             # reach.py: where the bell reaches the person (R149)
smtp_set = None          # () -> whether a mail server is set, for the email destination's hint
mfa = None               # mfa.py: the account's second factors (R127)
audit = None             # db.audit
two_factor_required = None   # account -> whether a role of it requires a second factor


def configure(**deps):
    globals().update(deps)


def view(me):
    """The tab's read. (payload, status)."""
    uid = users.uid_of(me)
    rec = users.get(me["name"]) or {}
    # Each part timed by name (timing.py), for the trace to say which is slow.
    with timed("profile:what_may"):
        may = users.what_may(me["name"])
    with timed("profile:claude"):
        claude = claude_email(uid)
    with timed("profile:plugins"):
        plugs = plugins_of(uid, node_names())
    # Still in the read the phone app's contract names (test/device-api.json),
    # though the page lists them in each notebook's Sessions view now.
    with timed("profile:logs"):
        logs = logs_of(me)
    acct = users.get(me["name"]) or {}
    return {"name": me["name"], "uid": uid,
            "role": rec.get("role", "user"),
            # What this account may do, said once (R255 step 5).
            "what_may": may,
            "profile": users.profile(me),
            "git": users.git_identity(me),
            "git_ready": users.git_ready(me),
            "claude": claude,
            # ...and every agent's, by its id (B296).
            "agents": agent_emails(uid) if agent_emails else {},
            # The Claude plugins this account installed, per
            # node, as the nodes last said (plugins.py).
            "plugins": plugs,
            # The account's own conversations with Claude, newest first
            # (transcripts.py): the phone app's; the page reads them per
            # project.
            "logs": logs,
            # The apps signed in as this account on its own machines
            # (R272), newest call first: what Disconnect acts on.
            "devices": devices.listed(acct) if devices else [],
            # The browsers signed in as this account (R158 step 8), each
            # bound to the browser it was made in, this one first.
            "signins": logins.rows(uid, me.get("lid") or "") if logins else [],
            # Its second factors (R127), never a secret, and whether a role
            # of it requires one.
            "two_factor": mfa.summary(uid) if mfa else {"on": False},
            "two_factor_required": bool(two_factor_required and two_factor_required(acct))}, 200


def _fresh(uid, req, origin):
    """Whether this request carries a fresh second factor: a code from the
    authenticator, an unused recovery code, or a passkey's answer to the
    challenge 2fa-fresh handed out (R127)."""
    code = str(req.get("code") or "").strip()
    if code:
        return mfa.totp_check(uid, code) or mfa.recovery_use(uid, code)
    pk = req.get("passkey") if isinstance(req.get("passkey"), dict) else None
    return bool(pk) and mfa.passkey_check(uid, origin, str(pk.get("id") or ""), pk.get("client"),
                                          pk.get("auth"), pk.get("sig"))


def two_factor(me, act, req, origin):
    """Profile's Two-factor section (R127). (payload, status)."""
    uid, name = users.uid_of(me), me["name"]
    who = f"user:{name}"
    first = not mfa.enabled(uid)
    if act == "2fa-totp-begin":
        return mfa.totp_begin(uid, name), 200
    if act == "2fa-totp-confirm":
        r = mfa.totp_confirm(uid, req.get("code"))
        if r.get("error"):
            return r, 400
        audit(who, "2fa-add", name, {"what": "authenticator"})
        # The first factor comes with its recovery codes, shown once.
        return {**r, "recovery": mfa.recovery_make(uid) if first else []}, 200
    if act == "2fa-passkey-begin":
        return {"challenge": mfa.challenge(uid, "create"), "user": mfa.b64u(uid.encode()), "name": name,
                "exclude": mfa.passkey_ids(uid)}, 200
    if act == "2fa-passkey-add":
        r = mfa.passkey_add(uid, origin, req.get("name"), req.get("client"), req.get("att"), prf=req.get("prf") is True)
        if r.get("error"):
            return r, 400
        audit(who, "2fa-add", name, {"what": "passkey", "name": r.get("name")})
        return {**r, "recovery": mfa.recovery_make(uid) if first else []}, 200
    if act == "2fa-fresh":
        # A passkey's challenge, for a change that wants a fresh factor.
        return {"challenge": mfa.challenge(uid, "get"), "ids": mfa.passkey_ids(uid)}, 200
    if act == "2fa-trust-remove":
        mfa.trust_remove(uid, str(req.get("id") or ""))
        audit(who, "2fa-remove", name, {"what": "remembered browser"})
        return {"ok": True}, 200
    if act in ("2fa-remove", "2fa-recovery"):
        if not first and not _fresh(uid, req, origin):
            return {"error": "that needs your second factor now: a code from your app, a recovery code, or your passkey",
                    "fresh": True}, 403
        if act == "2fa-recovery":
            audit(who, "2fa-recovery", name, {})
            return {"ok": True, "recovery": mfa.recovery_make(uid)}, 200
        what = str(req.get("what") or "")
        if what == "totp":
            mfa.totp_remove(uid)
        elif what.startswith("passkey:"):
            mfa.passkey_remove(uid, what[8:])
        else:
            return {"error": "remove what: totp or passkey:ID"}, 400
        if not mfa.enabled(uid):
            # The last factor gone: its recovery codes and remembered
            # browsers go with it.
            mfa.remove_all(uid)
        audit(who, "2fa-remove", name, {"what": what.split(":")[0]})
        return {"ok": True}, 200
    return None


def verb(me, act, req, origin=""):
    """Change the password, or save the profile and, last, the account's
    name. (payload, status, renamed): `renamed` is the account under its new
    name when the name moved, for the server to sign a fresh cookie over,
    and None otherwise."""
    if act == "password":
        r = users.change_password(me["name"], str(req.get("current") or ""),
                                  str(req.get("password") or ""))
        return r, (400 if r.get("error") else 200), None
    if act == "save":
        r = users.profile_set(me["name"], req.get("profile") or {})
        if r.get("error"):
            return r, 400, None
        # The account name last, because it is what the cookie is signed
        # over: the answer carries a fresh one so the page stays signed
        # in, and Basic callers simply use the new name.
        to = field(req, "account").strip()
        renamed = None
        if to and to != me["name"]:
            rr = users.rename(me["name"], to)
            if rr.get("error"):
                return rr, 400, None
            me = renamed = users.get(to)
        return {"ok": True, "name": me["name"], "profile": users.profile(me),
                "git": users.git_identity(me), "git_ready": users.git_ready(me)}, 200, renamed
    if str(act).startswith("2fa-") and mfa:
        got = two_factor(me, act, req, origin)
        if got:
            return got[0], got[1], None
    if act == "reach-list":
        return {"dest": reach.list_for(me.get("uid") or ""), "kinds": [[k, reach.KIND_WORDS[k]] for k in reach.KINDS],
                "channels": {k: {"label": v["label"], "fields": [[n, lb, sc] for n, lb, sc in v["fields"]]} for k, v in reach.CHANNELS.items()},
                "mail": bool(smtp_set and smtp_set())}, 200, None
    if act == "reach-set":
        r = reach.set_dest(me.get("uid") or "", req)
        if not r.get("error") and audit:
            audit(f"user:{me['name']}", "reach-set", r["dest"]["kind"], {})
        return r, (400 if r.get("error") else 200), None
    if act == "reach-remove":
        r = reach.remove(me.get("uid") or "", field(req, "id"))
        return r, (400 if r.get("error") else 200), None
    if act == "reach-test":
        r = reach.test(me.get("uid") or "", field(req, "id"), me.get("name") or "")
        return r, (400 if r.get("error") else 200), None
    if act == "signin-out":
        # A browser's sign-in ended from here (R158 step 8): its cookie
        # answers nothing from its next request.
        lid = field(req, "id")
        if not logins or not any(r["id"] == lid for r in logins.rows(me.get("uid") or "")):
            return {"error": "no such sign-in"}, 404, None
        logins.drop(me.get("uid") or "", lid)
        return {"ok": True, "this": lid == (me.get("lid") or "")}, 200, None
    if act == "device-signout":
        r = devices.revoke(users.get(me["name"]) or {}, field(req, "device")) if devices else {"error": "no devices here"}
        return r, (400 if r.get("error") else 200), None
    return {"error": "unknown action"}, 400, None
