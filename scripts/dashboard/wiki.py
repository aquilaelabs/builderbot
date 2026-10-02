"""A project's wiki (R112): pages a person or Claude writes, kept by the
controller, readable on the notebook's Wiki view and through `bb wiki`.

Kept as a git repository of the controller's own under STATE/wiki/PROJECT,
in the shape a forge's wiki has: one Markdown file per page at the top,
named for the page with its spaces as dashes (Home.md, Build-and-test.md),
_Sidebar.md and _Footer.md as GitHub reads them. So the wiki has a history
for nothing, an export is `git archive`, and putting it on GitHub (or a
Gitea or GitLab, whose wikis are the same thing) is a push to the
repository's REPO.wiki.git, with no conversion either way. A project with no
remote has a wiki all the same; it is only never pushed.

Never in the project's tree: a session can rewrite every file there, and a
wiki the controller pushes with the project's credentials must not be one
whose .git/config a session wrote. The remote's address is derived here,
from the push rights the operator granted (projects.load_push) or, for a
public pull, from the tree's origin read as data, and nothing in this
repository's config names a program.

A session writes under the project's dial, Claude may: Write the wiki
(pending.py): auto lands it, ask holds it for the operator, deny refuses
it. Pushing and pulling are a person's, from the view: they reach outside.
"""
import contextlib
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import pending  # noqa: E402

STATE = None
WORKSPACE = None
# Set by configure: the push rights for a project ({repo, host} or None),
# its credential helper line, an address parser and the git environment.
push_record = None
token_helper = None
parse_url = None
read_config = None
git_env = None

MAX_PAGES = 500
MAX_PAGE = 512 * 1024
MAX_NAME = 100
# What a page name may not carry: what a file name on any of the three
# forges, or a path, would read as something else.
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f#%]')
SPECIAL = ("_Sidebar", "_Footer")


class Refused(Exception):
    pass


# What a session is told under Claude may: Write the wiki is hidden, for a
# read as for a write: the wiki is the people's alone on this project.
HIDDEN = ("this project's wiki is hidden from Claude (Claude may: Write the wiki is hidden), "
          "so it can be neither read nor written from a session; ask the person if you need what is in it")


def hidden_for(project, session):
    """The refusal for a session's read of a hidden wiki, else ""."""
    return HIDDEN if session and pending.mode(project, "wiki") == "hidden" else ""


def configure(*, state, workspace, write_json, push_record_fn=None, token_helper_fn=None,
              parse_fn=None, config_fn=None, env_fn=None):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), push_record=push_record_fn,
                     token_helper=token_helper_fn, parse_url=parse_fn, read_config=config_fn,
                     git_env=env_fn)
    pending.configure(write_json=write_json, state=state)
    pending.applier("wiki", replay)


# ---- names -------------------------------------------------------------------

def file_of(name):
    """The page's file: its name with spaces as dashes, .md. Refused with
    the reason for a name no forge would read back as this page."""
    n = " ".join(str(name or "").split())
    if n.lower().endswith(".md"):
        n = n[:-3]
    if not n:
        raise Refused("a page needs a name")
    if len(n) > MAX_NAME:
        raise Refused(f"a page's name is at most {MAX_NAME} characters")
    if _BAD.search(n) or n.startswith(".") or (n.startswith("_") and n not in SPECIAL):
        raise Refused(f"{n!r} cannot be a page's name: no / \\ : * ? \" < > | # %, no leading dot, "
                      "and an underscore starts only _Sidebar and _Footer")
    return n.replace(" ", "-") + ".md"


def title_of(file):
    return file[:-3].replace("-", " ")


# ---- the repository ------------------------------------------------------------

def repo(project):
    return STATE / "wiki" / project


def _env():
    base = git_env() if git_env else dict(os.environ)
    env = {k: v for k, v in base.items()
           if not k.startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX", "GIT_CONFIG",
                                "GIT_AUTHOR", "GIT_COMMITTER"))}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(project, *args, timeout=60, check=True, env=None):
    r = subprocess.run(["git", "-C", str(repo(project)), *args], capture_output=True, text=True,
                       timeout=timeout, check=False, env=env or _env())
    if check and r.returncode:
        raise Refused((r.stderr or r.stdout or "git failed").strip().splitlines()[-1][:300])
    return r


def _ensure(project):
    d = repo(project)
    if not (d / ".git").is_dir():
        d.mkdir(parents=True, exist_ok=True)
        _git(project, "init", "--quiet")
        _git(project, "config", "core.hooksPath", "/dev/null")
        _git(project, "config", "commit.gpgsign", "false")
        _git(project, "config", "credential.helper", "")
    return d


@contextlib.contextmanager
def _locked(project):
    (STATE / "wiki").mkdir(parents=True, exist_ok=True)
    with open(STATE / "wiki" / f".{project}.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _has_head(project):
    return (repo(project) / ".git").is_dir() and _git(project, "rev-parse", "-q", "--verify", "HEAD",
                                                       check=False).returncode == 0


def rev(project):
    """What the view's poll compares: the wiki's reflog moves on every
    commit, a pull's included. A stat, never a git call."""
    try:
        return int((repo(project) / ".git" / "logs" / "HEAD").stat().st_mtime_ns)
    except OSError:
        return 0


def _blob(project, file):
    if not _has_head(project):
        return ""
    r = _git(project, "rev-parse", "-q", "--verify", f"HEAD:{file}", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _last(project, file):
    """Who changed a page last, and when."""
    r = _git(project, "log", "-1", "--format=%an%x00%at", "--", file, check=False)
    who, _, at = r.stdout.strip().partition("\0")
    return who, int(at or 0)


# ---- reading -------------------------------------------------------------------

def pages(project):
    """Every page at the top of the wiki, Home first, then by name, the
    sidebar and footer last: [{name, title, file, size, by, at}]."""
    if not _has_head(project):
        return []
    r = _git(project, "ls-tree", "-l", "HEAD")
    out = []
    for line in r.stdout.splitlines():
        meta, _, file = line.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob" or not file.endswith(".md"):
            continue
        by, at = _last(project, file)
        out.append({"name": file[:-3], "title": title_of(file), "file": file,
                    "size": int(parts[3]) if parts[3].isdigit() else 0, "by": by, "at": at,
                    "rev": parts[2]})
    order = lambda p: (p["name"] != "Home", p["name"] in SPECIAL, p["title"].lower())  # noqa: E731
    return sorted(out, key=order)


def page(project, name):
    """One page: {name, title, file, text, rev, by, at}; Refused when it
    is not there."""
    file = file_of(name)
    blob = _blob(project, file)
    if not blob:
        raise Refused(f"no page called {title_of(file)!r} in {project}'s wiki: bb wiki lists them")
    text = _git(project, "cat-file", "blob", blob).stdout
    by, at = _last(project, file)
    return {"name": file[:-3], "title": title_of(file), "file": file, "text": text,
            "rev": blob, "by": by, "at": at}


def history(project, limit=30):
    if not _has_head(project):
        return []
    r = _git(project, "log", f"-{int(limit)}", "--format=%h%x00%an%x00%at%x00%s")
    out = []
    for line in r.stdout.splitlines():
        h, by, at, subject = (line.split("\0") + ["", "", "", ""])[:4]
        out.append({"commit": h, "by": by, "at": int(at or 0), "what": subject})
    return out


# ---- writing -------------------------------------------------------------------

def _commit(project, message, who):
    name = (who or {}).get("name") or "BuilderBot"
    email = (who or {}).get("email") or "wiki@builderbot.invalid"
    env = dict(_env(), GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
               GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
    _git(project, "commit", "--quiet", "--no-verify", "-m", message, env=env)


def save(project, name, text, base="", who=None, why=""):
    """Write one page. `base` is the rev the writer read (empty for a new
    page): a page changed since is refused rather than overwritten."""
    file = file_of(name)
    text = str(text if text is not None else "")
    if len(text.encode("utf-8")) > MAX_PAGE:
        raise Refused(f"a page is at most {MAX_PAGE // 1024} KB")
    if not text.endswith("\n"):
        text += "\n"
    with _locked(project):
        _ensure(project)
        now = _blob(project, file)
        if now != (base or ""):
            raise Refused(f"{title_of(file)!r} changed since it was read" if base else
                          f"{title_of(file)!r} is already a page: open it and edit it")
        if not now and len(pages(project)) >= MAX_PAGES:
            raise Refused(f"a wiki holds at most {MAX_PAGES} pages")
        (repo(project) / file).write_text(text, encoding="utf-8")
        _git(project, "add", "--", file)
        if _git(project, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return {"ok": True, "name": file[:-3], "rev": now, "unchanged": True}
        verb = "Edit" if now else "Add"
        _commit(project, f"{verb} {title_of(file)}" + (f": {why}" if why else ""), who)
        return {"ok": True, "name": file[:-3], "rev": _blob(project, file)}


def remove(project, name, base="", who=None, why=""):
    file = file_of(name)
    with _locked(project):
        now = _blob(project, file)
        if not now:
            raise Refused(f"no page called {title_of(file)!r}")
        if base and base != now:
            raise Refused(f"{title_of(file)!r} changed since it was read")
        _git(project, "rm", "--quiet", "--", file)
        _commit(project, f"Remove {title_of(file)}" + (f": {why}" if why else ""), who)
        return {"ok": True}


def rename(project, old, new, who=None):
    a, b = file_of(old), file_of(new)
    if a == b:
        return {"ok": True, "name": b[:-3]}
    with _locked(project):
        if not _blob(project, a):
            raise Refused(f"no page called {title_of(a)!r}")
        if _blob(project, b):
            raise Refused(f"{title_of(b)!r} is already a page")
        _git(project, "mv", "--", a, b)
        _commit(project, f"Rename {title_of(a)} to {title_of(b)}", who)
        return {"ok": True, "name": b[:-3]}


def export_zip(project):
    """(filename, bytes) of the wiki as it stands: every file, as the
    forge's wiki would hold it, so it unpacks into one or into any folder
    of Markdown."""
    if not _has_head(project):
        raise Refused(f"{project}'s wiki has no pages yet")
    r = subprocess.run(["git", "-C", str(repo(project)), "archive", "--format=zip",
                        f"--prefix={project}-wiki/", "HEAD"],
                       capture_output=True, timeout=60, check=False, env=_env())
    if r.returncode:
        raise Refused("the wiki could not be packed: " + r.stderr.decode(errors="replace")[:200])
    return f"{project}-wiki.zip", r.stdout


# ---- the forge's wiki ----------------------------------------------------------

def remote(project):
    """{url, label, auth}: where this project's wiki lives on its forge,
    or {} when it has none. The granted push rights first, since those are
    the repository the controller's credentials reach; else the tree's
    origin as data, which only a public wiki can be read from."""
    rec = push_record(project) if push_record else None
    if isinstance(rec, dict) and rec.get("repo") and rec.get("host"):
        return {"url": f"https://{rec['host']}/{rec['repo']}.wiki.git",
                "label": f"{rec['host']}/{rec['repo']}", "auth": True}
    try:
        cfg = read_config(WORKSPACE / project / ".git") if read_config else {}
    except Exception:  # noqa: BLE001 (an unreadable config is no remote, said as such)
        cfg = {}
    url = ((cfg.get("remote.origin.url") or [""])[-1]) if isinstance(cfg, dict) else ""
    got = parse_url(url) if (parse_url and url) else None
    if got and got.get("host") and got.get("path"):
        return {"url": f"https://{got['host']}/{got['path']}.wiki.git",
                "label": f"{got['host']}/{got['path']}", "auth": False}
    return {}


def _net_env(project, rem):
    env = _env()
    helper = token_helper(project) if (token_helper and rem.get("auth")) else ""
    # One credential helper, the project's own, for this one call: nothing
    # stored in the wiki's config, so a later call with no rights has none.
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0=helper)
    return env


def _branch(project, rem, env):
    r = _git(project, "ls-remote", "--symref", rem["url"], "HEAD", check=False, env=env, timeout=60)
    if r.returncode:
        err = (r.stderr or "").strip()
        if "not found" in err.lower() or "not exist" in err.lower():
            raise Refused(f"{rem['label']} has no wiki yet: a forge makes the wiki's repository when its "
                          "first page is saved on the web, so make one page there (any text), then push")
        raise Refused(f"could not reach {rem['label']}'s wiki: {err.splitlines()[-1][:200] if err else 'no answer'}")
    m = re.search(r"ref: refs/heads/(\S+)\s+HEAD", r.stdout)
    return m.group(1) if m else ""


def pull(project, who=None):
    """Take the forge's wiki in: a fast-forward, or a merge of both sides
    when each has pages the other lacks. A page changed on both sides is
    left as it was and named, rather than merged into a muddle."""
    rem = remote(project)
    if not rem:
        raise Refused(f"{project} has no remote to read a wiki from")
    with _locked(project):
        _ensure(project)
        env = _net_env(project, rem)
        branch = _branch(project, rem, env)
        if not branch:
            raise Refused(f"{rem['label']}'s wiki is empty")
        _git(project, "fetch", "--quiet", rem["url"], f"+refs/heads/{branch}:refs/remotes/forge/{branch}",
             env=env, timeout=180)
        theirs = f"refs/remotes/forge/{branch}"
        if not _has_head(project):
            _git(project, "reset", "--quiet", "--hard", theirs)
            return {"ok": True, "took": "all", "pages": len(pages(project))}
        name = (who or {}).get("name") or "BuilderBot"
        email = (who or {}).get("email") or "wiki@builderbot.invalid"
        menv = dict(_env(), GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                    GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
        r = _git(project, "merge", "--no-edit", "--allow-unrelated-histories", theirs,
                 "-m", f"Take in the wiki from {rem['label']}", check=False, env=menv)
        if r.returncode:
            clash = _git(project, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
            _git(project, "merge", "--abort", check=False)
            raise Refused("both sides changed " + ", ".join(title_of(f) for f in clash[:8] if f.endswith(".md"))
                          + ": nothing was taken in. Make the page the same on one side, then pull again"
                          if clash else "the merge failed: " + (r.stderr or r.stdout).strip()[-200:])
        return {"ok": True, "took": "merged", "pages": len(pages(project))}


def push(project):
    """Send the wiki to the forge's: refused when the forge has a change
    this side has not taken in, which a pull settles first."""
    rem = remote(project)
    if not rem:
        raise Refused(f"{project} has no remote: export the wiki instead")
    if not rem.get("auth"):
        raise Refused(f"{project} has no push rights on {rem['label']}: grant them in the project's "
                      "remote dialog, then push")
    if not _has_head(project):
        raise Refused(f"{project}'s wiki has no pages yet")
    with _locked(project):
        env = _net_env(project, rem)
        branch = _branch(project, rem, env) or "master"
        r = _git(project, "push", "--porcelain", rem["url"], f"HEAD:refs/heads/{branch}",
                 check=False, env=env, timeout=180)
        if r.returncode:
            err = (r.stderr + r.stdout).lower()
            if "non-fast-forward" in err or "fetch first" in err or "rejected" in err:
                raise Refused(f"{rem['label']}'s wiki has changes this one has not taken in: Pull, then push")
            if "403" in err or "denied" in err or "permission" in err or "authentication" in err:
                raise Refused(f"{rem['label']} refused the push: the project's token may not reach its "
                              "wiki. GitHub's fine-grained tokens cannot write a wiki; a classic token "
                              "with the repo scope can")
            raise Refused("the push failed: " + (r.stderr or r.stdout).strip().splitlines()[-1][:200])
        return {"ok": True, "to": rem["label"], "branch": branch}


# ---- the notebook's and bb's door ------------------------------------------------

def view(project):
    rem = remote(project)
    return {"pages": pages(project), "rev": rev(project),
            "remote": {"label": rem.get("label", ""), "auth": bool(rem.get("auth"))} if rem else None,
            "gate": pending.mode(project, "wiki"), "history": history(project, 15)}


def replay(project, verb, args):
    """A held change, approved: the same call, as the session's."""
    a = args if isinstance(args, dict) else {}
    try:
        if verb == "save":
            return save(project, a.get("name"), a.get("text"), a.get("base") or "", a.get("who"), a.get("why") or "")
        if verb == "remove":
            return remove(project, a.get("name"), "", a.get("who"), a.get("why") or "")
    except Refused as e:
        return {"error": str(e)}
    return {"error": f"nothing to replay for wiki {verb}"}


def verb(project, req, who, session):
    """POST /api/wiki. (payload, status). `who` is {name, email}."""
    act = str(req.get("action") or "")
    name = req.get("name")
    try:
        if act in ("save", "remove", "rename") and session and not pending.replaying():
            g = pending.mode(project, "wiki")
            if g == "hidden":
                return {"error": HIDDEN}, 403
            if g == "deny":
                return {"error": pending.refusal("wiki")}, 403
            if g == "ask":
                if act == "rename":
                    return {"error": "a rename is a person's while Claude may: Write the wiki is ask"}, 403
                file = file_of(name)
                why = " ".join(str(req.get("why") or "").split())[:200]
                if act == "save":
                    text = str(req.get("text") or "")
                    if len(text.encode("utf-8")) > MAX_PAGE:
                        raise Refused(f"a page is at most {MAX_PAGE // 1024} KB")
                    summary = f"wiki: {'edit' if _blob(project, file) else 'add'} {title_of(file)}" + (f" ({why})" if why else "")
                    args = {"name": file[:-3], "text": text, "base": str(req.get("base") or ""), "who": who, "why": why}
                else:
                    summary = f"wiki: remove {title_of(file)}" + (f" ({why})" if why else "")
                    args = {"name": file[:-3], "who": who, "why": why}
                r = pending.hold(project, "wiki", act, args, summary=summary)
                if r.get("error"):
                    return r, 400
                return {"ok": True, "held": r["held"]}, 202
        why = " ".join(str(req.get("why") or "").split())[:200]
        if act == "save":
            return save(project, name, req.get("text"), str(req.get("base") or ""), who, why), 200
        if act == "remove":
            return remove(project, name, str(req.get("base") or ""), who, why), 200
        if act == "rename":
            return rename(project, name, req.get("to"), who), 200
        if session and pending.mode(project, "wiki") == "hidden":
            return {"error": HIDDEN}, 403
        if act in ("push", "pull"):
            if session:
                return {"error": f"a {act} reaches the forge, which is a person's: the Wiki view's {act.title()}"}, 403
            return (push(project) if act == "push" else pull(project, who)), 200
    except Refused as e:
        return {"error": str(e)}, 409 if "changed since" in str(e) or "already a page" in str(e) else 400
    return {"error": f"unknown action: {act}"}, 400


def rename_project(old, new):
    a, b = repo(old), repo(new)
    if a.is_dir() and not b.exists():
        a.rename(b)
    with contextlib.suppress(OSError):
        (STATE / "wiki" / f".{old}.lock").unlink()

