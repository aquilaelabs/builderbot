#!/usr/bin/env python3
"""Everything behind New project and Link to GitHub.

Making a project is two operations that look alike and behave nothing alike.
`git init` is local, bounded, and done before a spinner would render. A clone
or a first push is a network operation that can take minutes — and until this
file existed it ran inside the HTTP request that asked for it. Close the tab,
sleep the phone, walk out of wifi range, and the work carried on with nobody
left to report to; the page's own error text said as much ("check the Projects
card before trying again"), which is a note explaining a design rather than a
bug. Every other long job here — installing an SDK, removing one — is a
background worker with a row on screen and a way to stop it. This makes these
two the same.

The line is drawn at the network, not at the button: `init` stays synchronous,
because a busy row that appears and vanishes within one frame is worse than no
row at all.

What is *checked* stays synchronous either way. A name that is not a name, a
directory that already exists, a project that is not a repo, a repo that
already has a remote — those are instant, and they belong in the dialog the
operator is still looking at, not in a job they have to go and read.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server.
"""
import json
import os
import re
import shutil
import signal
import threading
import time
from pathlib import Path

def sanitize_name(raw):
    """A typed name, as the directory it will become — GitHub's own behaviour.

    GitHub does not refuse "My New App": it replaces what it cannot use with a
    dash and shows you what you are about to get. This refused it, which is
    friction for nothing — the operator retypes what the machine had already
    worked out. So the same rule, applied here, and the name a repository
    would have had is the name the directory gets.

    Three departures, all because this ends up as a directory rather than a
    repository:

    - a leading dot, dash or underscore is dropped. GitHub is happy with
      `.github`; the project scan skips anything starting with a dot, so such
      a directory would be created and then never appear. Dropping `_` also
      keeps `_work` — the runner's tree, which the scan skips by name — from
      being reachable through a name that sanitizes into it.
    - runs of dashes collapse. GitHub leaves `my---app` alone; nobody means it.
    - trailing dashes go, which are always an artifact of the replacement
      rather than anything typed on purpose.

    Empty is returned as empty and refused by the caller: there is a
    difference between "that is not a name" and a name this quietly invented.
    """
    s = re.sub(r"[^A-Za-z0-9._-]", "-", (raw or "").strip())
    s = re.sub(r"-{2,}", "-", s)
    return s.lstrip("._-").rstrip("-")[:100]


def _field(req, key):
    """One string field out of a request body — see server.field, which is the
    same rule at the same boundary. JSON carries types, and a name that
    arrives as a number reaches .strip() and takes the handler with it."""
    v = req.get(key)
    return v if isinstance(v, str) else ""


# The server's. Injected rather than imported, because importing the server
# from a module the server imports is a circle — same shape as packages.py.
run = None
WORKSPACE = None
agent_keys = None
gh_authed = None
ensure_deploy_alias = None
repo_path = None
build_claude_md = None
PROJECT_NAME = None
GITHUB_URL = None
# Renaming's own share of the injection: where the state, the home volume and
# the dev-instance data live, and how a compose project name is spelled.
STATE = None
HOME = None
DEVDATA = None
write_json = None
pname = None


def configure(*, run, workspace, agent_keys, gh_authed, ensure_deploy_alias,
              repo_path, build_claude_md, project_name, github_url,
              state, home, devdata, write_json, pname):
    """Hand over the server's helpers."""
    globals().update(
        run=run, WORKSPACE=Path(workspace), agent_keys=agent_keys,
        gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
        repo_path=repo_path, build_claude_md=build_claude_md,
        PROJECT_NAME=project_name, GITHUB_URL=github_url,
        STATE=Path(state), HOME=Path(home), DEVDATA=Path(devdata),
        write_json=write_json, pname=pname)


# ---------------------------------------------------------------------------
# renaming
#
# A project's NAME is its key in a dozen places, and every one of them fails
# the same quiet way when it is missed: the directory is there under its new
# name, and its roadmap, its bugs, its dev-instance data or its version history
# simply are not. Nothing errors. So the places are a table rather than a
# sequence of statements — the defence against forgetting one is being able to
# read the whole list in a single screen — and what moved is reported back
# rather than summarised as success.

# {file: [the keys inside it whose sub-dicts are keyed by project]}. None means
# the file's own top level is the keyed dict.
_KEYED = {
    "todos.json":         ["projects", "unsaved", "history", "batch"],
    "bugs.json":          ["projects", "history", "batch"],
    "versions.json":      ["projects"],
    "findings-log.json":  ["projects"],
    "last-sessions.json": ["sessions"],
    "devapps.json":       [None],
}

# Files holding a flat list of project names.
_LISTED = ["excluded-projects.json", "locked-projects.json",
           "pinned-projects.json"]


def _rename_in_json(path, old, new):
    """Move a project's entries inside one state file. True if anything moved."""
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict):
        return False
    moved = False
    for key in _KEYED.get(path.name, []):
        holder = d if key is None else d.get(key)
        if isinstance(holder, dict) and old in holder:
            holder[new] = holder.pop(old)
            moved = True
    if moved:
        write_json(path, d)
    return moved


def _rename_in_list(path, old, new):
    """The same, for a file that is a flat list of names."""
    try:
        with open(path) as f:
            v = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(v, list) or old not in v:
        return False
    write_json(path, sorted({new if x == old else x for x in v}))
    return True


def _rename_tabs(old, new):
    """Open tabs naming the project. Returns (rewritten, dropped).

    A notebook tab is rewritten — its arg IS the project name, and the operator
    would expect to come back to it. A terminal tab is dropped instead: its arg
    encodes a session name (`claude:X:r:<id>`, `sh:2:X`) that no longer exists,
    and rewriting one would offer a Resume onto a transcript recorded under the
    old directory. Dropping is the honest answer, and it is reported.
    """
    path = STATE / "tabs.json"
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0, 0
    tabs = d.get("tabs")
    if not isinstance(tabs, list):
        return 0, 0
    keep, rewritten, dropped = [], 0, 0
    for t in tabs:
        if not isinstance(t, dict):
            keep.append(t)
            continue
        if t.get("kind") == "todo" and t.get("arg") == old:
            t["arg"] = new
            t["label"] = "Notebook: " + new
            rewritten += 1
        elif t.get("kind") == "term" and _names_project(t.get("arg", ""), old):
            dropped += 1
            continue
        keep.append(t)
    if rewritten or dropped:
        d["tabs"] = keep
        # The panes reference tab ids, and a dropped tab leaves a dangling one.
        # The page already tolerates that (it renders "no tab here"), so this
        # does not try to rebuild the layout — it would be guessing at what the
        # operator wants on screen.
        write_json(path, d)
    return rewritten, dropped


def _names_project(arg, name):
    """Whether a terminal tab's argument is a session in this project.

    The two shapes bb-tty accepts: `claude:<project>[:...]` and
    `sh:<n>:<project>`. Split rather than matched with a prefix, because a
    project called `app` must not claim `app-2`'s tabs.
    """
    parts = str(arg).split(":")
    if len(parts) >= 2 and parts[0] == "claude":
        return parts[1] == name
    if len(parts) >= 3 and parts[0] == "sh":
        return parts[2] == name
    return False


# Prompts off, and ssh in batch mode: a key the agent does not hold has to
# fail with a message rather than block on a username prompt no HTTP request
# can answer. accept-new because the first contact with github.com on a fresh
# home volume is expected, not an attack to refuse.
def _mv(src, dst, label, moved, failed):
    """Move one path, recording which it was. Missing is not a failure — most
    projects have never had a dev instance or a CI log."""
    try:
        if not src.exists():
            return
        if dst.exists():
            failed.append(f"{label}: {dst.name} was already there")
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        moved.append(label)
    except OSError as e:
        failed.append(f"{label}: {e}")


def rename(req):
    """Rename a project — the directory, and everything keyed to its old name.

    Guarded rather than clever. A live session, a dev instance with containers
    still on the daemon, or another project job in flight all mean the answer
    is "not now": each of them holds the old name somewhere this cannot reach,
    and renaming underneath one produces a mess with no single owner. Those
    three are checked by the caller, which can see tmux and the daemon.

    The directory moves first. It is the step most likely to fail and the only
    one that fails cleanly — if it does, nothing else has been touched. Every
    store after it is best-effort and reported: a project whose roadmap did not
    follow is worth knowing about, and is still better than one that says it
    renamed successfully and quietly dropped it.
    """
    old = _field(req, "name").strip()
    new = sanitize_name(_field(req, "to"))
    if not old or not PROJECT_NAME.fullmatch(old):
        return {"error": "unknown project"}, 400
    src = WORKSPACE / old
    if not src.is_dir():
        return {"error": f"{old} is not a project under the workspace"}, 400
    if not new:
        return {"error": "a name needs at least one letter or digit in it"}, 400
    if new == old:
        return {"error": f"{old} is already its name"}, 400
    dest = WORKSPACE / new
    if dest.exists():
        return {"error": f"{new} already exists in the workspace"}, 400
    with _lock:
        if _job["running"]:
            return {"error": f"already {DOING.get(_job['kind'], 'working on')} "
                             f"{_job['name']}"}, 409
    try:
        src.rename(dest)
    except OSError as e:
        return {"error": f"could not rename the directory: {e}"}, 500

    moved, failed = [], []
    for name in _KEYED:
        try:
            if _rename_in_json(STATE / name, old, new):
                moved.append(name)
        except OSError as e:                       # write_json can fail
            failed.append(f"{name}: {e}")
    for name in _LISTED:
        try:
            if _rename_in_list(STATE / name, old, new):
                moved.append(name)
        except OSError as e:
            failed.append(f"{name}: {e}")
    try:
        rewritten, dropped = _rename_tabs(old, new)
        if rewritten:
            moved.append(f"{rewritten} open notebook tab(s)")
        if dropped:
            moved.append(f"{dropped} terminal tab(s) closed — their sessions "
                         f"were named for the old directory")
    except OSError as e:
        failed.append(f"tabs.json: {e}")

    _mv(STATE / "devenv" / f"{old}.env", STATE / "devenv" / f"{new}.env",
        "the dev instance's env", moved, failed)
    _mv(STATE / "ci-logs" / old, STATE / "ci-logs" / new,
        "archived CI logs", moved, failed)
    # The compose project name is derived and sanitized, so these two are not
    # simply the project's name with a prefix on it.
    _mv(DEVDATA / pname(old), DEVDATA / pname(new),
        "the dev instance's data", moved, failed)
    # Claude Code's own directory: the transcripts AND the memories, which live
    # inside it. Its slug is the working directory's path with the slashes
    # turned into dashes — the same rule memory.py reads it by.
    _mv(HOME / ".claude" / "projects" / str(src).replace("/", "-"),
        HOME / ".claude" / "projects" / str(dest).replace("/", "-"),
        "Claude's transcripts and memories", moved, failed)
    return {"ok": True, "name": new, "from": old,
            "moved": moved, "failed": failed}, 200


def _git_env():
    return dict(os.environ, GIT_TERMINAL_PROMPT="0",
                GIT_SSH_COMMAND="ssh -o BatchMode=yes "
                                "-o StrictHostKeyChecking=accept-new")


# ---- the one job ----------------------------------------------------------
# One at a time, like the package worker and for the same reason: these are
# minutes long, and a queue that did not survive a page reload would be a
# promise the page could not keep. `step` is a phrase, not a percentage —
# git's progress is a carriage-return animation on stderr, and parsing it to
# redraw it was rejected once already on the packages tab. The page draws an
# ellipsis after whatever this says.
# What each kind is called while it is happening, for the one message that
# has to name it. The page has its own copy for the row it draws.
DOING = {"clone": "cloning", "link": "linking"}

_job = {"running": False, "kind": "", "name": "", "step": "", "at": 0.0,
        "error": "", "note": "", "aborting": False}
_lock = threading.Lock()
_proc = None                  # the git process, so an abort can reach it
_dest = None                  # the directory this job made, if it made one


def job():
    """The job record for the status payload."""
    with _lock:
        j = dict(_job)
    j["for"] = int(time.time() - j["at"]) if j["at"] else 0
    return j


def busy_name():
    """The project a running job is writing, so the list can say so.

    A half-finished clone is a directory with a `.git` in it and not much
    else, which the project listing reads as a repo in a strange state and
    reports as a problem. It is not a problem, it is a clone — but only this
    module knows that.
    """
    with _lock:
        return _job["name"] if _job["running"] else ""


def _step(text):
    with _lock:
        _job["step"] = text


def _register(p):
    global _proc
    _proc = p


def dismiss():
    """Clear the last outcome. The record holds it after the job ends so that
    a failure survives the page being closed — but then it has to be possible
    to say it has been read, or the card carries it forever."""
    with _lock:
        if _job["running"]:
            return {"error": "it is still running"}
        _job.update(error="", note="", kind="", name="", at=0.0)
    return {"ok": True}


def abort():
    """Stop the running job and clean up after it."""
    with _lock:
        if not _job["running"]:
            return {"error": "nothing is running"}
        _job["aborting"] = True
    p = _proc
    if p is not None:
        try:
            # The group, not the process: git clone waits on git-remote-https,
            # and killing only the parent leaves the child holding the
            # directory that is about to be removed.
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return {"ok": True}


def _finish(error="", note=""):
    with _lock:
        _job.update(running=False, step="", error=error, note=note,
                    aborting=False)


def _start(kind, name, fn):
    """Hand one job to a thread. The caller has already validated everything."""
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, kind=kind, name=name, step="starting",
                    at=time.time(), error="", note="", aborting=False)
    threading.Thread(target=_wrap, args=(fn,), daemon=True).start()
    return True


def _wrap(fn):
    try:
        error, note = fn()
    except Exception as e:                                  # noqa: BLE001
        # A worker thread that dies silently leaves the job "running" forever
        # and the buttons dead with it. Whatever went wrong, it ends here.
        error, note = f"unexpected failure: {e}", ""
    finally:
        _register(None)
    _finish(error, note)


def _aborted():
    with _lock:
        return _job["aborting"]


# ---- creating -------------------------------------------------------------

def create(req):
    """Create a project under /workspace, as a (payload, status) pair.

    A fresh local repo is done by the time this returns. A clone is validated
    and claimed here — the name checked, the directory made — and then handed
    to the worker, because the fetch is the part that takes minutes.

    mkdir is the claim: it is atomic, so two requests racing on one name get
    one directory and one clean "already exists". On failure the directory
    this request just made is removed — never one that was already there,
    which is the FileExistsError branch returning first.
    """
    mode = _field(req, "mode")
    if mode not in ("init", "clone"):
        return {"error": "unknown mode"}, 400
    url = _field(req, "url").strip()
    about, key_url = "", ""
    if mode == "clone":
        if not GITHUB_URL.fullmatch(url):
            return {"error": "not a GitHub repository address — "
                             "use https://github.com/owner/repo or "
                             "git@github.com:owner/repo.git"}, 400
        # The repository's own name, unless the operator gave one. It used to
        # be derived and nothing else, on the reasoning that the repo already
        # knows what it is called — which is true right up until you want two
        # checkouts of it. Deploying an app from a public repo is exactly that
        # case: three Radarrs are three directories and one repository. So the
        # field is optional and defaults to this, and typing nothing still
        # gets the old behaviour. Notes are not asked for either way — they
        # are drafted from the code after the clone.
        name = sanitize_name(_field(req, "name"))
        if not name:
            name = re.split(r"[/:]", url.rstrip("/"))[-1]
            name = sanitize_name(name[:-4] if name.endswith(".git") else name)
        # An optional deploy key, by name. The name is only ever matched
        # against what the agent actually holds — nothing from the request is
        # written into a file or a config line; the matched key's own public
        # line is. When one is chosen the clone goes through a per-repo alias,
        # which also leaves the remote pointing at that alias, so pushes keep
        # using the right key without anyone re-doing this by hand.
        keyname = _field(req, "key").strip()
        if keyname:
            match = next((k for k in agent_keys() if k["name"] == keyname), None)
            if match is None:
                return {"error": f"the agent holds no key named {keyname}"}, 400
            alias = ensure_deploy_alias(match["name"], match["pub"])
            key_url = f"git@{alias}:{repo_path(url)}.git"
    else:
        name = sanitize_name(_field(req, "name"))
        about = _field(req, "about").strip()
    # After sanitizing, the only way to fail this is an empty name — every
    # other shape has already been turned into something legal. Kept as the
    # gate rather than replaced by `if not name`, because it is the invariant
    # the rest of this file and the path handling below rely on, and an
    # assertion that cannot fire is cheaper than one that was removed.
    if not PROJECT_NAME.fullmatch(name):
        return {"error": "a name needs at least one letter or digit in it"}, 400
    # Asked before the directory is claimed, so a refused second job does not
    # leave an empty directory behind it.
    if mode == "clone":
        with _lock:
            if _job["running"]:
                return {"error": f"already {DOING.get(_job['kind'], 'working on')} "
                                 f"{_job['name']}"}, 409
    dest = WORKSPACE / name
    with _mkdir_lock:
        try:
            dest.mkdir()
        except FileExistsError:
            return {"error": f"{name} already exists in the workspace"}, 400
        except OSError as e:
            return {"error": f"cannot create {name}: {e}"}, 500
    if mode == "init":
        return _init(dest, name, about)
    global _dest
    _dest = dest
    if not _start("clone", name, lambda: _clone(dest, key_url or url)):
        shutil.rmtree(dest, ignore_errors=True)             # made a moment ago
        return {"error": "another project job is already running"}, 409
    return {"ok": True, "name": name, "started": True}, 200


_mkdir_lock = threading.Lock()


def _init(dest, name, about):
    r = run(["git", "init", "-b", "main", str(dest)], timeout=30)
    if r["code"] != 0:
        shutil.rmtree(dest, ignore_errors=True)             # made a moment ago
        return {"error": r["out"].strip()[-2000:] or "git init failed"}, 500
    return {"ok": True, "name": name, "note": _write_md(dest, about, False)}, 200


def _clone(dest, url):
    """The worker half of a clone: fetch, then draft the CLAUDE.md."""
    _step("cloning")
    r = run(["git", "clone", "--progress", "--", url, str(dest)],
            timeout=1800, env=_git_env(), register=_register)
    if _aborted():
        shutil.rmtree(dest, ignore_errors=True)             # made by this job
        return "stopped — the half-cloned directory was removed", ""
    if r["code"] != 0:
        shutil.rmtree(dest, ignore_errors=True)
        return r["out"].strip()[-2000:] or "git clone failed", ""
    _step("reading the repository")
    return "", _write_md(dest, "", True)


def _write_md(dest, about, cloned):
    """The CLAUDE.md, and the sentence describing what happened to it.

    A cloned repo that already carries one keeps it; one that does not gets a
    draft read out of its own files. A fresh local repo gets the operator's
    notes.
    """
    md = dest / "CLAUDE.md"
    if md.is_file():
        return "kept the repository's own CLAUDE.md"
    if cloned:
        about = describe_repo(dest) or ""
    body = build_claude_md(about)
    if body is None:
        return "no CLAUDE.md template in this image; none written"
    try:
        md.write_text(body)
    except OSError as e:
        return f"could not write CLAUDE.md: {e}"
    if not about:
        return "CLAUDE.md created from the template"
    # Said out loud because it is a file this dashboard added to somebody
    # else's tree: it is not in the repository's history, and a `git status`
    # that opens with an unexpected untracked file is a small mystery worth
    # not creating.
    return ("CLAUDE.md drafted from the repository's own files — untracked, "
            "commit or delete it" if cloned else "CLAUDE.md created from your notes")


# ---- linking --------------------------------------------------------------

def link(req):
    """Point an existing local repo at an *empty* GitHub repository and push.

    Empty-only is the safety property: `git ls-remote` must come back with no
    refs before anything is pushed, so this can never write over a repository
    that already holds work. The one thing it will create is a repo that does
    not exist at all — PAT path only, always private — because "not found"
    from GitHub is the one answer that proves there is nothing there to harm.

    Auth mirrors the clone: a picked deploy key means an ssh alias, no key
    means the PAT answers for https — and with neither, this refuses up front
    instead of letting the push discover it.

    Everything above is local and instant, so it is answered here. The
    ls-remote, the create and the push are the network, and go to the worker.
    """
    name = _field(req, "name").strip()
    url = _field(req, "url").strip()
    keyname = _field(req, "key").strip()
    try:
        here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
    except OSError:
        here = set()
    if name not in here:
        return {"error": f"unknown project: {name}"}, 400
    dest = str(WORKSPACE / name)
    if run(["git", "-C", dest, "rev-parse", "--is-inside-work-tree"],
           timeout=10)["out"].strip() != "true":
        return {"error": f"{name} is not a git repository"}, 400
    if run(["git", "-C", dest, "remote"], timeout=10)["out"].strip():
        return {"error": f"{name} already has a remote"}, 400
    if not GITHUB_URL.fullmatch(url):
        return {"error": "not a GitHub repository address — use "
                         "https://github.com/owner/repo or "
                         "git@github.com:owner/repo.git"}, 400
    path = repo_path(url)
    pat = gh_authed()
    if keyname:
        match = next((k for k in agent_keys() if k["name"] == keyname), None)
        if match is None:
            return {"error": f"the agent holds no key named {keyname}"}, 400
        remote = f"git@{ensure_deploy_alias(match['name'], match['pub'])}:{path}.git"
    elif pat:
        # Plain https: gh's credential helper (wired at startup) answers for
        # it, so nothing secret lands in .git/config.
        remote = f"https://github.com/{path}.git"
    else:
        return {"error": "no PAT is configured and no deploy key was picked — "
                         "a push needs one of the two"}, 400
    if not _start("link", name,
                  lambda: _link(dest, name, path, remote, bool(keyname), pat)):
        return {"error": "another project job is already running"}, 409
    return {"ok": True, "name": name, "started": True}, 200


def _link(dest, name, path, remote, keyed, pat):
    """The worker half: prove the remote is empty, then set it and push.

    There is no lock around check-then-add: two racing links resolve at
    `git remote add`, which refuses a duplicate origin, and the loser's error
    says exactly that.
    """
    env = _git_env()
    created = ""
    _step("checking the repository is empty")
    # split_err: emptiness is judged on stdout alone. ssh's first-contact
    # "Permanently added github.com ..." note arrives on stderr with exit 0,
    # and combined it made a genuinely empty repository look occupied.
    r = run(["git", "ls-remote", "--", remote], timeout=120, env=env,
            split_err=True, register=_register)
    if _aborted():
        return "stopped — nothing was changed", ""
    if r["code"] != 0:
        blame = (r["err"] + r["out"]).strip()
        if "not found" in blame.lower() and keyed:
            # Creating it here would not help: a brand-new repo has no deploy
            # keys, so the push over this alias still fails — and a retry
            # would then trip over the half-done state. Say what the fix
            # actually is instead.
            return ("GitHub reports the repository as not found over ssh. "
                    "Create it (empty) on GitHub and add this deploy key to it "
                    "first" + (", or leave the key on none to use the PAT"
                               if pat else "") + ".", "")
        if "not found" in blame.lower() and pat:
            _step("creating it on GitHub")
            c = run(["gh", "repo", "create", path, "--private"], timeout=60,
                    register=_register)
            if c["code"] != 0:
                return c["out"].strip()[-2000:] or "gh repo create failed", ""
            created = f"created {path} on GitHub (private); "
        else:
            return blame[-2000:] or "cannot reach that repository", ""
    elif r["out"].strip():
        return ("that repository is not empty — linking only targets empty "
                "repositories, so nothing can be overwritten"), ""

    a = run(["git", "-C", dest, "remote", "add", "origin", remote], timeout=10)
    if a["code"] != 0:
        return a["out"].strip() or "remote add failed", ""
    if run(["git", "-C", dest, "rev-parse", "-q", "--verify", "HEAD"],
           timeout=10)["code"] != 0:
        return "", created + "remote set — nothing committed yet, so nothing was pushed"
    _step("pushing")
    p = run(["git", "-C", dest, "push", "-u", "origin", "HEAD"],
            timeout=1800, env=env, register=_register)
    if _aborted():
        # The remote stays either way: it is correct configuration, and a push
        # is the retryable part — from here or from any shell.
        return "stopped — the remote is set; the push did not finish", ""
    if p["code"] != 0:
        return created + "the remote was set, but the push failed:\n" \
            + p["out"].strip()[-2000:], ""
    branch = run(["git", "-C", dest, "symbolic-ref", "--short", "-q", "HEAD"],
                 timeout=10)["out"].strip() or "HEAD"
    return "", f"{created}pushed {branch}"


# ---- drafting a CLAUDE.md from a cloned tree ------------------------------

def _readme_intro(dest):
    """The first prose paragraph of the repo's README, or None.

    Headings, badges and raw HTML are skipped — the first thing most READMEs
    hold is a wall of shields, and a CLAUDE.md that opens with badge markup
    describes the README, not the project."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = dest / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            return None
        out = []
        for para in text.split("\n\n"):
            # Filtered line by line, not paragraph by paragraph: the most
            # common README opens "# Title\nprose" with no blank line
            # between, and skipping that whole block threw away the prose
            # with the heading.
            lines = [l for l in para.splitlines()
                     if l.strip() and not l.lstrip().startswith(
                         ("#", "<", "![", "[![", "---", "=", "|", "```", ">"))]
            if not lines:
                continue
            out.append(re.sub(r"\s+", " ", " ".join(lines)).strip())
            if sum(map(len, out)) > 400:
                break
        return " ".join(out)[:600] or None
    return None


def _build_hints(dest):
    """Build/test commands read off the tree's own marker files.

    Heuristics, deliberately shallow: the point is a first draft that names
    the toolchain, not a build system parser. Wrong guesses are cheap here —
    the section carries a note saying to verify it."""
    hints = []
    try:
        scripts = (json.loads((dest / "package.json").read_text())
                   .get("scripts") or {})
        hints += [f"- **{k}:** `npm run {k}`"
                  for k in ("build", "test", "lint", "dev") if k in scripts]
    except (OSError, ValueError):
        pass
    if (dest / "gradlew").is_file():
        hints += ["- **Build:** `./gradlew build`"
                  + (" — `./gradlew assembleDebug` for an APK"
                     if (dest / "app").is_dir() else ""),
                  "- **Test:** `./gradlew test`"]
    if (dest / "Cargo.toml").is_file():
        hints += ["- **Build:** `cargo build`", "- **Test:** `cargo test`"]
    if (dest / "go.mod").is_file():
        hints += ["- **Build:** `go build ./...`", "- **Test:** `go test ./...`"]
    if (dest / "pyproject.toml").is_file():
        hints.append("- **Python:** `pyproject.toml` present — `uv pip install -e .`"
                     + ("; `pytest`" if (dest / "tests").is_dir() else ""))
    if (dest / "Makefile").is_file():
        hints.append("- **Make:** a `Makefile` is present — see its targets")
    return hints


def describe_repo(dest):
    """A drafted project section for a repo that arrived without a CLAUDE.md:
    the README's own first paragraph, plus whatever the marker files say about
    building it. None when the tree says nothing — the template's placeholder
    section is more honest than an empty guess."""
    parts = [p for p in (_readme_intro(dest),) if p]
    hints = _build_hints(dest)
    if hints:
        parts.append("What the tree suggests:\n\n" + "\n".join(hints))
    if not parts:
        return None
    parts.append("<!-- Drafted automatically at clone time from the repository's "
                 "own files. Have a session verify this against the code and "
                 "flesh it out. -->")
    return "\n\n".join(parts)
