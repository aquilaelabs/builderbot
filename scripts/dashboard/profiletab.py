"""The signed-in account's own settings: the Profile tab.

Anybody signed in, because this is about themselves, which is why it is not
behind the admin gate the Users tab wears. Out of server.py (R77): the
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
plugins_of = None        # (uid, {node id: name}) -> its plugins, as the nodes last said
node_names = None        # () -> {node id: name}
logs_of = None           # me -> the account's conversations with Claude (transcripts.mine)


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
    with timed("profile:logs"):
        logs = logs_of(me)
    return {"name": me["name"], "uid": uid,
            "role": rec.get("role", "user"),
            # What this account may do, said once (R255 step 5).
            "what_may": may,
            "profile": users.profile(me),
            "git": users.git_identity(me),
            "git_ready": users.git_ready(me),
            "claude": claude,
            # The Claude plugins this account installed, per
            # node, as the nodes last said (plugins.py).
            "plugins": plugs,
            # The account's own conversations with Claude, newest first,
            # each a download of the whole exchange (transcripts.py).
            "logs": logs}, 200


def verb(me, act, req):
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
    return {"error": "unknown action"}, 400, None
