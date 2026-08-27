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


def configure(*, run, workspace, agent_keys, gh_authed, ensure_deploy_alias,
              repo_path, build_claude_md, project_name, github_url):
    """Hand over the server's helpers."""
    globals().update(
        run=run, WORKSPACE=Path(workspace), agent_keys=agent_keys,
        gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
        repo_path=repo_path, build_claude_md=build_claude_md,
        PROJECT_NAME=project_name, GITHUB_URL=github_url)


# Prompts off, and ssh in batch mode: a key the agent does not hold has to
# fail with a message rather than block on a username prompt no HTTP request
# can answer. accept-new because the first contact with github.com on a fresh
# home volume is expected, not an attack to refuse.
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
        name = _field(req, "name").strip()
        if not name:
            name = re.split(r"[/:]", url.rstrip("/"))[-1]
            name = name[:-4] if name.endswith(".git") else name
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
        name = _field(req, "name").strip()
        about = _field(req, "about").strip()
    if not PROJECT_NAME.fullmatch(name):
        return {"error": "a project name is one path segment: letters, digits, "
                         "dots, dashes, underscores, starting with a letter "
                         "or digit"}, 400
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
