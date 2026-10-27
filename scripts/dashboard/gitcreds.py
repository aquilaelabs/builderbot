"""A project's git token, as the controller keeps it (R135): one line, the
URL git's credential store would write (scheme, user, token, host), in
/config/gitcreds/<project>, 0600, sealed under the install key where there
is one, so a copy of /config pushes nowhere.

git is handed the token by git-credential-bb, a credential helper beside this
file that opens the line for the host git asks about; git's own store,
which reads only plain lines, is not used. Readers in the dashboard ask
read_line. Sealing is the server's: seal, unseal and sealing are set by it
from signing's, as for the signing keys and two-factor secrets.

A token a person gives a repository is kept in their own key store
(accountkeys.py, sealed under their key; the operator, 27 Oct), and the
project's file then says `account:UID:ID`, nothing secret, naming that
entry. A person's own git work (their session's bb git, their presses in
the Git view) asks their own store first, the entry their project is
linked to or else their newest for the host git asks about, and the
project's after it (helpers). Tokens kept before that go to the project
owner's store at the first start that can seal them (adopt).
"""
import base64
import contextlib
import os
import re
import shlex
import urllib.parse
from pathlib import Path

STATE = None
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


def linked_to(project):
    """(uid, entry id) of the account entry a project's git access is linked
    to, or ("", ""); an entry from before ids is named by its host."""
    try:
        text = path(project).read_text().strip()
    except OSError:
        return "", ""
    if not text.startswith(LINKED):
        return "", ""
    uid, _, host = text[len(LINKED):].partition(":")
    return uid, host


def read_line(project):
    """The project's credential line, plain, or "" for none: a linked
    account's from its key store."""
    uid, fid = linked_to(project)
    if uid:
        return _accounts().forge_line(uid, fid)
    try:
        return open_text(path(project).read_text())
    except OSError:
        return ""


def link_account(project, uid, fid):
    """The project's git access linked to an entry of an account's store."""
    _settled(project)
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd = os.open(path(project), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"{LINKED}{uid}:{fid}\n")


def linked_projects(uid, fid=None):
    """The projects linked to this account, or to one entry of it."""
    d = STATE / "gitcreds"
    return [f.name for f in (sorted(d.iterdir()) if d.is_dir() else [])
            if linked_to(f.name)[0] == uid and (fid is None or linked_to(f.name)[1] == fid)]


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
    """An account's key store gone (purged, or the account deleted): every
    project linked to it loses its git access, and each says so (gone_rows)
    until it is given a token or linked again. Returns the projects."""
    hit = linked_projects(uid)
    if not hit:
        return []
    import time                                             # noqa: PLC0415
    d = _gone()
    for p in hit:
        forget(p)
        d[p] = {"name": name, "at": int(time.time())}
    _gone_save(d)
    return hit


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


def helpers(project, uid=""):
    """The credential helpers for git work on this project, in the order git
    asks them: the acting account's own store, when it keeps a token, then
    the project's (R154: theirs for their own work)."""
    out = []
    if uid and _accounts().forges_of(uid):
        out.append(f"!{shlex.quote(str(HELPER))} --account {shlex.quote(str(STATE))} {shlex.quote(uid)} "
                   f"{shlex.quote(project)}")
    h = helper(project)
    if h:
        out.append(h)
    return out


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
