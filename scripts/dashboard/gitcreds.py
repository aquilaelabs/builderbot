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

import unlocks            # the opened tokens and their handouts (R158 step 5)

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
    # The project's own line is the first that is not a giver's (R157: a
    # token moved to the project sits beside the `account:` lines).
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.startswith(LINKED)]
    text = lines[0].strip() if lines else ""
    if text.startswith(SEALED):
        try:
            text = unseal(base64.b64decode(text[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked, or damaged: no token)
            return ""
    return text.splitlines()[0] if text else ""


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


def read_line(project, uid=None, live_only=True, why="read"):
    """The credential line git work on this project is handed, plain, or
    "" for none: the acting person's own (`uid`, else ACTING) when they
    gave one and are signed in, else any giver's who is signed in now,
    else a line kept as the project's own from before. Each opening is a
    use the person reads on their Profile (`why` says what for)."""
    uid = acting() if uid is None else uid
    g = givers(project)
    if uid and any(u == uid for u, _ in g) and (not live_only or _live(uid)):
        line = _accounts().forge_line(uid, given_by(project, uid), why=why, project=project, by=uid)
        if line or _locked(uid):
            return line
    for u, fid in g:
        if (not live_only or _live(u)) and not _locked(u):
            line = _accounts().forge_line(u, fid, why=why, project=project, by=uid or "")
            if line:
                return line
    try:
        return open_text(path(project).read_text())
    except OSError:
        return ""


def own_line(project):
    """Whether the project keeps a line of its own (from before accounts,
    or moved to it when its giver took their key, R157)."""
    try:
        return bool(open_text(path(project).read_text()))
    except OSError:
        return False


def keep_as_own(project, line):
    """`line` kept as the project's own, sealed, before its givers' lines:
    what a project's background work runs with when the person whose token
    it was holds their own key (R157)."""
    if not line or "\n" in line:
        return False
    _settled(project)
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    rows = givers(project)
    fd = os.open(path(project), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(_kept(line) + "\n" + "".join(f"{LINKED}{u}:{f}\n" for u, f in rows))
    return True


def _locked(uid):
    """Whether the account's store is under a key of its own and shut
    (unlocks), so its tokens open for nobody now."""
    try:
        return bool(unlocks.locked(uid))
    except Exception:                                       # noqa: BLE001
        return False


def usable(project, uid):
    """What git work by `uid` on this project would run with (R159):
    {"by": uid or "", "mine": bool, "live": bool, "given": bool, "why": ""}.
    `why` says, in a sentence, what stops a push when nothing would run."""
    uid = uid or acting()
    g = givers(project)
    mine = given_by(project, uid) if uid else ""
    if mine:
        if _locked(uid):
            return {"by": uid, "mine": True, "live": _live(uid), "given": True, "locked": True,
                    "why": "your key store is locked: unlock it on your Profile (Your key store), and your "
                           "pushes and pulls run with your token"}
        if _live(uid):
            return {"by": uid, "mine": True, "live": True, "given": True, "why": ""}
        return {"by": uid, "mine": True, "live": False, "given": True,
                "why": "your token for this project is used only while you are signed in, and you are "
                       "signed out everywhere: bb git waits for you to sign in to the dashboard"}
    other = next((u for u, _ in g if _live(u) and not _locked(u)), "")
    if other:
        return {"by": other, "mine": False, "live": True, "given": False, "why": ""}
    if g and not own_line(project):
        shut = [u for u, _ in g if _live(u) and _locked(u)]
        return {"by": "", "mine": False, "live": False, "given": False,
                "why": ("everyone signed in who gave this project a token has their key store locked: one of them "
                        "unlocks it on their Profile, or give yours in the project's settings") if shut else
                       "nobody who gave this project a token is signed in: give yours in the project's "
                       "settings, or wait for one of them"}
    if own_line(project):
        return {"by": "", "mine": False, "live": True, "given": False, "why": ""}
    return {"by": "", "mine": False, "live": False, "given": False,
            "why": "this project has no git token: give yours in the project's settings"}


def _write_givers(project, rows, keep_own=True):
    _settled(project)
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    if not rows and not (keep_own and own_line(project)):
        forget(project)
        return
    try:
        own = [ln for ln in path(project).read_text().splitlines() if ln.strip() and not ln.startswith(LINKED)][:1] if keep_own else []
    except OSError:
        own = []
    fd = os.open(path(project), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(x + "\n" for x in own) + "".join(f"{LINKED}{u}:{f}\n" for u, f in rows))


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
        # The entries it replaced: every project linked to one now uses the
        # one kept, so no project is left on a token that is gone.
        if got.get("replaced"):
            remap(uid, got["replaced"], got["id"])
    return helper(project)


def remap(uid, olds, new):
    """Each project linked to one of `uid`'s entries `olds` linked to `new`
    instead: the replaced token's projects keep a token, the current one."""
    olds = {str(o) for o in olds}
    d = STATE / "gitcreds"
    for f in sorted(d.iterdir()) if d.is_dir() else []:
        rows = givers(f.name)
        if any(u == uid and x in olds for u, x in rows):
            moved = [(u, new if u == uid and x in olds else x) for u, x in rows]
            _write_givers(f.name, list(dict.fromkeys(moved)))


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
        if not text or givers(f.name):
            continue
        line = open_text(text)
        uid = owner_of(f.name) if line else ""
        m = re.match(r"https?://([^:@/]*):[^@/]*@", line)
        if not uid or not m:
            continue
        got, _code = _accounts().link_forge(uid, line.rsplit("@", 1)[-1], line, urllib.parse.unquote(m.group(1)))
        if got.get("ok"):
            # The owner's now, in their store: the project's own line goes.
            _write_givers(f.name, [(uid, got["id"])], keep_own=False)
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


def helpers(project, uid=None, why="git"):
    """The credential helpers for git work on this project, in the order
    git asks them (R159): a handout of the acting person's own token, when
    they gave this project one and are signed in with their store open;
    else a handout of any signed-in giver's whose store is open; then the
    project's helper for a line kept as the project's own from before. A
    handout (unlocks.handout) is the opened line in a file of its own for
    the window, so the helper opens nothing itself and each opening is a
    use on the person's Profile (R158 step 5)."""
    uid = acting() if uid is None else uid
    out = []
    g = givers(project)
    handed = ""
    for u, fid in ([(uid, given_by(project, uid))] if uid and given_by(project, uid) else []) + [x for x in g if x[0] != uid]:
        if not _live(u) or _locked(u):
            continue
        e = _accounts().entry_for(u, fid)
        if not e:
            continue
        handed = unlocks.handout(u, project, fid, why=why, by=uid or "", host=e["host"], login=e["login"])
        if handed:
            break
    if handed:
        out.append(f"!{shlex.quote(str(HELPER))} {shlex.quote(handed)}")
    if not g or own_line(project):
        h = helper(project)
        if h:
            out.append(h)
    return out


def git_c(project, uid=None, why="git"):
    """git's -c arguments that hand a command BuilderBot's credential for this
    project, wherever it is kept (the account's own store, the project's),
    whatever the tree's own config names: every git that reaches a remote
    for BuilderBot goes through these or through helpers() written into a
    config of its own (the operator, 27 Oct). [] where there is none."""
    hs = helpers(project, uid, why)
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
