"""A project's git token, as the controller keeps it (R135): one line, the
URL git's credential store would write (scheme, user, token, host), in
/config/gitcreds/<project>, 0600, sealed under the install key where there
is one, so a copy of /config pushes nowhere.

git is handed the token by git-credential-bb, a credential helper beside this
file that opens the line for the host git asks about; git's own store,
which reads only plain lines, is not used. Readers in the dashboard ask
read_line. Sealing is the server's: seal, unseal and sealing are set by it
from signing's, as for the signing keys and two-factor secrets.

A token a person gives a project is kept in their own key store
(accountkeys.py, sealed under their key; the operator, 27 Oct), and the
project's file then says `account:UID:ID`, nothing secret, one line per
person who gave one (R159: every git action is a person's, with their own
token). A person's own git work (their session's bb git, their presses in
the Git view, the release they cut, the wiki they sync) is handed their own
token, while they hold a live sign-in anywhere (logins.live); signed out
everywhere, their sessions' bb git waits for them. Work that is nobody's
in the moment (watching CI) takes the token of any giver signed in now and
pauses while none is. A project keeps no token of its own; a line kept as
the project's from before (an install with no key to seal a store with)
is read as it was until a person gives theirs. Tokens kept as a project's
before 0.8.0 go to the project owner's store at the first start that can
seal them (adopt).
"""
import base64
import contextlib
import contextvars
import os
import re
import shlex
import urllib.parse
from pathlib import Path

STATE = None
# Whose work a git command is (R159): the server sets it for a person's
# request, so a call that names no account (version.release, the wiki's
# push, the address check) is handed theirs.
ACTING = contextvars.ContextVar("gitcreds_acting", default="")
seal = None               # bytes -> bytes
unseal = None             # bytes -> bytes, or raises
sealing = None            # () -> whether an install key is loaded now
SEALED = "bbseal:"
LINKED = "account:"
HELPER = Path(__file__).resolve().with_name("git-credential-bb")


_KEEP = object()


def configure(*, state, seal_fn=_KEEP, unseal_fn=_KEEP, sealing_fn=_KEEP):
    """Where the tokens are, and (from the server) the install key's seal;
    a hook not passed is left as it was, so a module that only knows the
    state (projects, cilogs, forgerelease) never takes the seal away."""
    globals()["STATE"] = Path(state)
    for name, fn in (("seal", seal_fn), ("unseal", unseal_fn), ("sealing", sealing_fn)):
        if fn is not _KEEP:
            globals()[name] = fn


def path(project):
    return STATE / "gitcreds" / project


def open_text(text):
    """A file's content as its plain line: opened if sealed, "" when it
    cannot be (another install key, or none)."""
    text = (text or "").strip()
    if text.startswith(SEALED):
        try:
            text = unseal(base64.b64decode(text[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked, or damaged: no token)
            return ""
    lines = text.splitlines()
    return lines[0] if lines else ""


def _accounts():
    import accountkeys                                      # noqa: PLC0415
    if accountkeys.STATE is None and STATE is not None:
        accountkeys.configure(state=STATE)
    return accountkeys


def _live(uid):
    """Whether this person holds a live sign-in now (logins.live); a store
    with no logins module beside it (a test, bb's own python) reads every
    account as signed in."""
    try:
        import logins                                       # noqa: PLC0415
        if logins.STATE is None and STATE is not None:
            logins.configure(state=STATE)
        return logins.live(uid)
    except ImportError:
        return True


def givers(project):
    """Who has given this project a token: [(uid, entry id)], in the order
    they gave, from the project's `account:` lines; an entry from before
    ids is named by its host."""
    try:
        text = path(project).read_text()
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith(LINKED):
            uid, _, fid = ln[len(LINKED):].partition(":")
            if uid and (uid, fid) not in out:
                out.append((uid, fid))
    return out


def linked_to(project):
    """(uid, entry id) of the first account that gave the project a token
    (its owner's, from the move off a project's own), or ("", "")."""
    g = givers(project)
    return g[0] if g else ("", "")


def given_by(project, uid):
    """The entry id of the token `uid` gave this project, or ""."""
    return next((fid for u, fid in givers(project) if u == uid), "")


def acting():
    return ACTING.get() or ""


def read_line(project, uid=None, live_only=True):
    """The credential line git work on this project is handed, plain, or
    "" for none: the acting person's own (`uid`, else ACTING) when they
    gave one and are signed in, else any giver's who is signed in now,
    else a line kept as the project's own from before."""
    uid = acting() if uid is None else uid
    g = givers(project)
    if uid and any(u == uid for u, _ in g) and (not live_only or _live(uid)):
        return _accounts().forge_line(uid, given_by(project, uid))
    for u, fid in g:
        if not live_only or _live(u):
            line = _accounts().forge_line(u, fid)
            if line:
                return line
    if g:
        return ""
    try:
        return open_text(path(project).read_text())
    except OSError:
        return ""


def usable(project, uid):
    """What git work by `uid` on this project would run with (R159):
    {"by": uid or "", "mine": bool, "live": bool, "given": bool, "why": ""}.
    `why` says, in a sentence, what stops a push when nothing would run."""
    uid = uid or acting()
    g = givers(project)
    mine = given_by(project, uid) if uid else ""
    if mine:
        if _live(uid):
            return {"by": uid, "mine": True, "live": True, "given": True, "why": ""}
        return {"by": uid, "mine": True, "live": False, "given": True,
                "why": "your token for this project is used only while you are signed in, and you are "
                       "signed out everywhere: bb git waits for you to sign in to the dashboard"}
    other = next((u for u, _ in g if _live(u)), "")
    if other:
        return {"by": other, "mine": False, "live": True, "given": False, "why": ""}
    if g:
        return {"by": "", "mine": False, "live": False, "given": False,
                "why": "nobody who gave this project a token is signed in: give yours in the project's "
                       "settings, or wait for one of them"}
    if helper(project):
        return {"by": "", "mine": False, "live": True, "given": False, "why": ""}
    return {"by": "", "mine": False, "live": False, "given": False,
            "why": "this project has no git token: give yours in the project's settings"}


def _write_givers(project, rows):
    _settled(project)
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    if not rows:
        forget(project)
        return
    fd = os.open(path(project), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(f"{LINKED}{u}:{f}\n" for u, f in rows))


def link_account(project, uid, fid):
    """The project given `uid`'s token: their line added, or theirs
    replaced when they had given one; the other givers stay."""
    rows = [(u, f) for u, f in givers(project) if u != uid] + [(uid, fid)]
    _write_givers(project, rows)


def unlink_person(project, uid):
    """`uid`'s token no longer given to this project; the others stay."""
    rows = [(u, f) for u, f in givers(project) if u != uid]
    if len(rows) == len(givers(project)):
        return False
    _write_givers(project, rows)
    return True


def linked_projects(uid, fid=None):
    """The projects this account gave a token, or one entry of it."""
    d = STATE / "gitcreds"
    return [f.name for f in (sorted(d.iterdir()) if d.is_dir() else [])
            if any(u == uid and (fid is None or x == fid) for u, x in givers(f.name))]


def keep_for(project, uid, line, login):
    """A token a person gave the project, into their own store and the
    project linked to it. The helper line, or "" when the install has no
    key to seal their store with (then kept as the project's own)."""
    got, _code = _accounts().link_forge(uid, line.rsplit("@", 1)[-1], line, login) if uid else ({"error": "no one"}, 400)
    if got.get("error"):
        write_line(project, line)
    else:
        link_account(project, uid, got["id"])
    return helper(project)


def adopt(owner_of):
    """Each token kept as a project's own (from before tokens were a
    person's) moved into its project owner's store, the project linked to
    it: BuilderBot's owner where a project has none (owner_of says). Done
    once a key can seal it; returns how many moved."""
    if not (seal and sealing and sealing()):
        return 0
    d = STATE / "gitcreds"
    n = 0
    for f in (sorted(d.iterdir()) if d.is_dir() else []):
        try:
            text = f.read_text().strip()
        except OSError:
            continue
        if not text or text.startswith(LINKED):
            continue
        line = open_text(text)
        uid = owner_of(f.name) if line else ""
        m = re.match(r"https?://([^:@/]*):[^@/]*@", line)
        if not uid or not m:
            continue
        got, _code = _accounts().link_forge(uid, line.rsplit("@", 1)[-1], line, urllib.parse.unquote(m.group(1)))
        if got.get("ok"):
            link_account(f.name, uid, got["id"])
            n += 1
    return n


def _gone_file():
    return STATE / "gitcreds-gone.json"


def _gone():
    try:
        import json                                         # noqa: PLC0415
        d = json.loads(_gone_file().read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _gone_save(d):
    import statefile                                        # noqa: PLC0415
    statefile.write_json(_gone_file(), d, mode=0o600)


def unlink_account(uid, name):
    """An account's key store gone (purged, or the account deleted): its
    line goes from every project it gave a token, and a project left with
    nobody's says so (gone_rows) until somebody gives theirs. Returns the
    projects that lost their last."""
    hit = linked_projects(uid)
    if not hit:
        return []
    import time                                             # noqa: PLC0415
    d = _gone()
    lost = []
    for p in hit:
        unlink_person(p, uid)
        if not givers(p):
            lost.append(p)
            d[p] = {"name": name, "at": int(time.time())}
    _gone_save(d)
    return lost


def gone_projects():
    """The projects whose git access went with an account."""
    return list(_gone())


def gone_rows(projects):
    """The bell's rows, kind git-unlinked, for these projects."""
    d = _gone()
    return [{"kind": "git-unlinked", "id": p, "project": p, "name": str(d[p].get("name") or ""),
             "at": int(d[p].get("at") or 0), "bad": True, "key": f"gitgone:{p}@{int(d[p].get('at') or 0)}",
             "why": f"its git access was linked to {d[p].get('name') or 'an account'}'s token, which is gone: "
                    "give it a token of its own, or link another account's, in its settings"}
            for p in projects if isinstance(d.get(p), dict)]


def _settled(project):
    """A project given git access again says no more that it lost it."""
    d = _gone()
    if d.pop(project, None) is not None:
        with contextlib.suppress(OSError):
            _gone_save(d)


def helpers(project, uid=None):
    """The credential helpers for git work on this project, in the order
    git asks them (R159): the acting person's own store, when they gave
    this project a token or keep one for its host and are signed in now;
    then the project's helper, which answers with any signed-in giver's
    token, or with a line kept as the project's own from before."""
    uid = acting() if uid is None else uid
    out = []
    if uid and _accounts().forges_of(uid) and _live(uid):
        out.append(f"!{shlex.quote(str(HELPER))} --account {shlex.quote(str(STATE))} {shlex.quote(uid)} "
                   f"{shlex.quote(project)}")
    h = helper(project)
    if h:
        out.append(h)
    return out


def git_c(project, uid=None):
    """git's -c arguments that hand a command BuilderBot's credential for this
    project, wherever it is kept (the account's own store, the project's),
    whatever the tree's own config names: every git that reaches a remote
    for BuilderBot goes through these or through helpers() written into a
    config of its own (the operator, 27 Oct). [] where there is none."""
    hs = helpers(project, uid)
    return ["-c", "credential.helper=", *[x for h in hs for x in ("-c", f"credential.helper={h}")]] if hs else []


def _kept(line):
    if seal and sealing and sealing():
        return SEALED + base64.b64encode(seal(line.encode())).decode()
    return line


def write_line(project, line):
    _settled(project)
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd = os.open(path(project), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(_kept(line) + "\n")


def helper(project):
    """The credential.helper value for a project that has a token, or ""."""
    f = path(project)
    return f"!{shlex.quote(str(HELPER))} {shlex.quote(str(f))}" if f.is_file() else ""


def names_helper(value, project):
    """Whether a repository's credential.helper value is this project's, in
    either form: git-credential-bb, or git's store from before R135."""
    f = str(path(project))
    return f"store --file={f}" in value or (str(HELPER) in value and f in value)


def forget(project):
    with contextlib.suppress(OSError):
        path(project).unlink()


def seal_all(again=False):
    """Every line kept open sealed, once the install has a key: at start.
    `again`, after the install key changed (R154): every sealed one sealed
    once more, under today's key. Returns how many."""
    if not (seal and sealing and sealing()):
        return 0
    d = STATE / "gitcreds"
    n = 0
    for f in (sorted(d.iterdir()) if d.is_dir() else []):
        try:
            text = f.read_text().strip()
        except OSError:
            continue
        if text.startswith(LINKED):
            continue
        if text and not text.startswith(SEALED):
            write_line(f.name, text.splitlines()[0])
            n += 1
        elif again and text and (line := open_text(text)):
            write_line(f.name, line)
            n += 1
    return n
