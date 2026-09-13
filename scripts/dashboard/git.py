#!/usr/bin/env python3
"""The notebook's Git view: what a project's repository holds, read out for
the page, and the handful of things the page may do to it (roadmap R36).

Every answer is git plumbing run on the CONTROLLER against
the project's tree on the share — the one place with the credentials, the
worktrees and every account's author — and shaped for the page: the
uncommitted changes, the recent history with parents (the page draws the
lanes), one commit with its files and diff, a file's uncommitted diff, and
the branches with how far each stands from main and its upstream, marked
with whose worktree sits on it.

Deliberately narrow at the boundary. A sha is forty hex characters or
fewer, a path is one `git ls-files` or `git status` reported, a ref is one
`git for-each-ref` handed out — nothing typed into a URL reaches a command
line as anything but a checked value. Output is capped: a diff past
DIFF_MAX bytes is cut with a line saying so, because a page is not the
place to read a vendored library's arrival.

Path-pure like changelog.py: functions take the project's directory,
configure() only knows where the workspace and the worktrees are.
"""
import os
import re
import subprocess
from pathlib import Path

WORKSPACE = None
WORKTREES = None
TELL = None               # notify.tell: type a line into a session, injected
TMUX_NAME = None

LOG_MAX = 100             # commits the graph shows
DIFF_MAX = 200_000        # bytes of diff the page is handed
SHA_RE = re.compile(r"^[0-9a-f]{4,40}$")
US = "\x1f"


def configure(*, workspace, worktrees=None, tell=None, tmux_name=None):
    globals().update(WORKSPACE=Path(workspace),
                     WORKTREES=Path(worktrees) if worktrees else Path(workspace) / ".worktrees",
                     TELL=tell, TMUX_NAME=tmux_name)


def _git(repo, *args, timeout=20):
    """stdout of one git command in `repo`, or None when it failed."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=timeout, check=False,
                           env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def is_repo(repo):
    return _git(repo, "rev-parse", "--is-inside-work-tree") is not None


def has_remote(repo):
    return bool((_git(repo, "remote") or "").strip())


def status(repo):
    """The branch the tree is on and its uncommitted changes.

        {"branch", "upstream", "ahead", "behind", "files": [{"path", "state"}]}

    `state` is one word the page can show: modified, added, deleted,
    renamed, untracked, conflict.
    """
    out = _git(repo, "status", "--porcelain=v2", "--branch", "--untracked-files=normal")
    if out is None:
        return {"error": "not a git repository"}
    st = {"branch": "", "upstream": "", "ahead": 0, "behind": 0, "files": []}
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            st["branch"] = line[len("# branch.head "):]
        elif line.startswith("# branch.upstream "):
            st["upstream"] = line[len("# branch.upstream "):]
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                st["ahead"], st["behind"] = int(m.group(1)), int(m.group(2))
        elif line.startswith("1 ") or line.startswith("2 "):
            parts = line.split(" ", 8 if line.startswith("1 ") else 9)
            xy = parts[1]
            path = parts[-1]
            if line.startswith("2 "):
                # "2 XY sub mH mI mW hH hI Xscore path\torig"
                path = path.split("\t")[0]
            code = (xy[0] if xy[0] != "." else xy[1])
            state = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed",
                     "C": "copied", "T": "typechange", "U": "conflict"}.get(code, "modified")
            st["files"].append({"path": path, "state": state,
                                "staged": xy[0] != "."})
        elif line.startswith("u "):
            st["files"].append({"path": line.split(" ", 10)[-1], "state": "conflict", "staged": False})
        elif line.startswith("? "):
            st["files"].append({"path": line[2:], "state": "untracked", "staged": False})
    return st


def log(repo, n=LOG_MAX):
    """The recent history across every branch, newest first, each commit
    with its parents so the page can lay the lanes out:

        [{"sha", "short", "parents": [...], "author", "when", "refs": [...],
          "subject"}]
    """
    n = max(1, min(int(n or LOG_MAX), 500))
    fmt = US.join(["%H", "%h", "%P", "%an", "%at", "%D", "%s"])
    out = _git(repo, "log", "--all", "--date-order", f"--max-count={n}",
               f"--format={fmt}")
    if out is None:
        return []
    rows = []
    for line in out.splitlines():
        f = line.split(US)
        if len(f) < 7:
            continue
        refs = [r.strip() for r in f[5].split(",") if r.strip()]
        rows.append({"sha": f[0], "short": f[1], "parents": f[2].split(),
                     "author": f[3], "when": int(f[4] or 0), "refs": refs,
                     "subject": f[6]})
    return rows


def show(repo, sha):
    """One commit: its message, author, files with counts, and its diff."""
    if not SHA_RE.match(str(sha or "")):
        return {"error": "not a commit"}
    fmt = US.join(["%H", "%h", "%an", "%ae", "%at", "%P", "%D", "%B"])
    head = _git(repo, "show", "--no-patch", f"--format={fmt}", sha)
    if head is None:
        return {"error": "no such commit"}
    f = head.rstrip("\n").split(US)
    if len(f) < 8:
        return {"error": "no such commit"}
    stat = _git(repo, "show", "--format=", "--numstat", "-m", "--first-parent", sha) or ""
    files = []
    for line in stat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            files.append({"path": parts[2],
                          "added": int(parts[0]) if parts[0].isdigit() else None,
                          "removed": int(parts[1]) if parts[1].isdigit() else None})
    # A merge shows no patch on its own; against its first parent it shows
    # what the merge brought in, which is what the reader asked.
    diff = _git(repo, "show", "--format=", "--no-color", "-m", "--first-parent", "-p",
                sha, timeout=30) or ""
    return {"sha": f[0], "short": f[1], "author": f[2], "email": f[3], "when": int(f[4] or 0),
            "parents": f[5].split(), "refs": [r.strip() for r in f[6].split(",") if r.strip()],
            "message": f[7].strip(), "files": files, "diff": _cap(diff)}


def diff(repo, path):
    """A file's uncommitted change against the last commit: staged and
    unstaged together, or the whole file as added when it is untracked."""
    known = set((_git(repo, "ls-files", "--", ".") or "").splitlines())
    st = status(repo)
    listed = {f["path"] for f in st.get("files", [])}
    if path not in known and path not in listed:
        return {"error": "not a file this repository reports"}
    if path in listed and path not in known:
        # Untracked: everything is new. Shown the way git would after `add -N`.
        out = _git(repo, "diff", "--no-color", "--no-index", "--", "/dev/null", path) or ""
        if not out:
            try:
                body = (Path(repo) / path).read_text(errors="replace")
            except OSError:
                body = ""
            out = f"--- /dev/null\n+++ b/{path}\n" + "".join(f"+{ln}\n" for ln in body.splitlines())
        return {"path": path, "diff": _cap(out)}
    out = _git(repo, "diff", "--no-color", "HEAD", "--", path)
    if out is None:
        out = _git(repo, "diff", "--no-color", "--", path) or ""
    return {"path": path, "diff": _cap(out)}


def branches(repo):
    """Every local branch (and the remote-tracking ones), newest commit
    first, with how far each stands from main and from its upstream, which
    one the tree is on, and whose worktree sits on it:

        [{"name", "remote": bool, "head": bool, "short", "when", "upstream",
          "ahead", "behind", "main_ahead", "main_behind", "worktree", "who"}]
    """
    fmt = US.join(["%(refname:short)", "%(refname)", "%(objectname:short)",
                   "%(committerdate:unix)", "%(upstream:short)", "%(upstream:track)",
                   "%(HEAD)"])
    out = _git(repo, "for-each-ref", "--sort=-committerdate", f"--format={fmt}",
               "refs/heads", "refs/remotes")
    if out is None:
        return {"error": "not a git repository"}
    main = _main_branch(repo)
    trees = _worktrees(repo)
    rows = []
    for line in out.splitlines():
        f = line.split(US)
        if len(f) < 7:
            continue
        name, ref, short, when, up, track, head = f[:7]
        remote = ref.startswith("refs/remotes/")
        if remote and name.endswith("/HEAD"):
            continue
        ahead = behind = 0
        m = re.search(r"ahead (\d+)", track or "")
        if m:
            ahead = int(m.group(1))
        m = re.search(r"behind (\d+)", track or "")
        if m:
            behind = int(m.group(1))
        ma = mb = 0
        if main and not remote and name != main:
            lr = _git(repo, "rev-list", "--left-right", "--count", f"{main}...{name}")
            if lr:
                parts = lr.split()
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    mb, ma = int(parts[0]), int(parts[1])
        wt = trees.get(ref, "")
        rows.append({"name": name, "remote": remote, "head": head.strip() == "*",
                     "short": short, "when": int(when or 0), "upstream": up,
                     "ahead": ahead, "behind": behind,
                     "main_ahead": ma, "main_behind": mb,
                     "worktree": wt, "who": _who_of(wt, name)})
    return {"main": main, "branches": rows}


def _main_branch(repo):
    for cand in ("main", "master"):
        if _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{cand}") is not None:
            return cand
    return ""


def _worktrees(repo):
    """{ref: path} for every worktree of the repository, the main one
    included — `git worktree list --porcelain` names both."""
    out = _git(repo, "worktree", "list", "--porcelain") or ""
    trees, path = {}, ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and path:
            trees[line[len("branch "):]] = path
    return trees


def _who_of(worktree, branch):
    """The account name a worktree or branch belongs to: a session's tree is
    <worktrees>/<project>/<uid> on a branch named claude/<account>."""
    if branch.startswith("claude/"):
        return branch[len("claude/"):]
    return ""


def _cap(text):
    b = text.encode("utf-8", "replace")
    if len(b) <= DIFF_MAX:
        return text
    cut = b[:DIFF_MAX].decode("utf-8", "ignore")
    return cut + f"\n… cut at {DIFF_MAX // 1000}kB — the rest is in the repository\n"


def payload(project, what, sha="", path="", n=None):
    """One question about one project, for the route."""
    repo = WORKSPACE / project
    if not is_repo(repo):
        return {"error": "not a git repository"}
    if what == "status":
        return status(repo)
    if what == "log":
        return {"commits": log(repo, n or LOG_MAX)}
    if what == "show":
        return show(repo, sha)
    if what == "diff":
        return diff(repo, path)
    if what == "branches":
        return branches(repo)
    if what in ("", "all"):
        return {"status": status(repo), "commits": log(repo, n or LOG_MAX),
                **branches(repo)}
    return {"error": "unknown question"}


# ---- the actions (R36 step 2) ----------------------------------------------
# Each one is a FIXED git command with checked arguments, the way every
# executing endpoint on this dashboard is a table lookup and never a string:
# a ref through check-ref-format, a sha through SHA_RE against the log, a
# path against what status reports, a message as an argument and never in a
# shell. Run under the acting account's author (GIT_AUTHOR_*, given as
# `env`) and the project's own credentials (the repository's helper and
# ssh alias, in its config already), which is why they run here and not on
# a node. Refusals are sentences; nothing here guesses.

BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]{1,120}$")
NET_TIMEOUT = 120


def _run(repo, *args, env=None, timeout=30):
    """{code, out} of one git command, stderr folded into out."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=timeout, check=False,
                           env={**os.environ, **(env or {}), "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return {"code": 124, "out": f"git {args[0]} took longer than {timeout}s"}
    except OSError as e:
        return {"code": 1, "out": str(e)}
    return {"code": r.returncode, "out": ((r.stdout or "") + (r.stderr or "")).strip()[-4000:]}


def _ok_branch(name):
    name = str(name or "").strip()
    if not BRANCH_RE.match(name) or name.endswith("/") or ".." in name or name.endswith(".lock"):
        return ""
    return name


def _has_branch(repo, name):
    return _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{name}") is not None


def _dirty(repo):
    st = status(repo)
    return [f["path"] for f in st.get("files", []) if f["state"] != "untracked"]


def act(repo, action, args, env=None, may_push=True):
    """Do one thing to the repository; {ok, out, ...} or {error}."""
    args = args if isinstance(args, dict) else {}
    if not is_repo(repo):
        return {"error": "not a git repository"}
    if action == "fetch":
        r = _run(repo, "fetch", "--prune", env=env, timeout=NET_TIMEOUT)
        return _done(r, "fetched")
    if action == "pull":
        if _dirty(repo):
            return {"error": "there are uncommitted changes — commit or discard them first, so a pull cannot land on top of them"}
        r = _run(repo, "pull", "--ff-only", env=env, timeout=NET_TIMEOUT)
        if r["code"] and "diverged" in r["out"] or r["code"] and "Not possible to fast-forward" in r["out"]:
            return {"error": "the branch and its upstream have both moved — this only fast-forwards; merge or rebase from a shell, or ask Claude"}
        return _done(r, "pulled")
    if action == "push":
        if not may_push:
            return {"error": "this project has no push rights — they are granted in the clone dialog, once"}
        st = status(repo)
        branch = st.get("branch") or ""
        if not branch or branch == "(detached)":
            return {"error": "not on a branch"}
        r = (_run(repo, "push", env=env, timeout=NET_TIMEOUT) if st.get("upstream")
             else _run(repo, "push", "-u", "origin", branch, env=env, timeout=NET_TIMEOUT))
        return _done(r, "pushed")
    if action == "branch":
        name = _ok_branch(args.get("name"))
        if not name:
            return {"error": "a branch name is letters, digits and . _ / -"}
        if _has_branch(repo, name):
            return {"error": f"{name} already exists"}
        at = str(args.get("at") or "HEAD")
        if at != "HEAD" and not SHA_RE.match(at):
            return {"error": "not a commit"}
        r = _run(repo, "branch", "--", name, at, env=env)
        if r["code"]:
            return {"error": r["out"] or "could not create the branch"}
        if args.get("switch"):
            return act(repo, "switch", {"name": name}, env=env)
        return {"ok": True, "out": f"{name} created at {at[:7] if at != 'HEAD' else 'HEAD'}"}
    if action == "switch":
        name = _ok_branch(args.get("name"))
        if not name or not _has_branch(repo, name):
            return {"error": "no such branch"}
        if _dirty(repo):
            return {"error": "there are uncommitted changes — commit or discard them before switching, so they cannot be carried onto the wrong branch"}
        r = _run(repo, "switch", "--", name, env=env)
        return _done(r, f"on {name}")
    if action == "merge":
        # Into the branch the tree is ON, which is what git does and the only
        # thing a person can reason about from a row: to put a feature into
        # main you Switch to main and press Merge on the feature. Nothing
        # here switches for you — a button that moved the tree under you on
        # the way to doing something else is how you lose track of where you
        # are.
        name = _ok_branch(args.get("name"))
        if not name or not _has_branch(repo, name):
            return {"error": "no such branch"}
        into = (status(repo).get("branch") or "")
        if not into or into == "(detached)":
            return {"error": "not on a branch"}
        if name == into:
            return {"error": f"{name} is the branch the tree is on"}
        if _dirty(repo):
            return {"error": "there are uncommitted changes — commit or discard them first, "
                             "so the merge is its own commit"}
        r = _run(repo, "merge", "--no-edit", name, env=env)
        if r["code"]:
            # LEFT IN CONFLICT on purpose, where revert aborts. A conflicted
            # merge is a state this view already knows: the Changes section
            # lists the files and offers the merge in progress to the
            # session, which is the one thing that can finish it. Aborting
            # would throw that away to say the same sentence.
            if any(f["state"] == "conflict" for f in status(repo).get("files", [])):
                return {"error": f"{name} does not merge into {into} cleanly — the files are "
                                 "under Changes, with the button that hands the merge to Claude"}
            _run(repo, "merge", "--abort", env=env)
            return {"error": r["out"] or "could not merge"}
        return _done(r, f"merged {name} into {into}")
    if action == "revert":
        sha = str(args.get("sha") or "")
        if not SHA_RE.match(sha):
            return {"error": "not a commit"}
        parents = (_git(repo, "show", "--no-patch", "--format=%P", sha) or "").split()
        if not parents:
            return {"error": "no such commit"}
        if _dirty(repo):
            return {"error": "there are uncommitted changes — commit or discard them first, so the revert is its own commit"}
        extra = ["-m", "1"] if len(parents) > 1 else []
        r = _run(repo, "revert", "--no-edit", *extra, sha, env=env)
        if r["code"]:
            _run(repo, "revert", "--abort", env=env)
            return {"error": "the revert does not apply cleanly — it was abandoned; ask Claude to do it by hand"}
        return _done(r, "reverted")
    if action == "commit":
        msg = " ".join(str(args.get("message") or "").split())
        if not msg:
            return {"error": "a commit needs a message"}
        st = status(repo)
        listed = [f["path"] for f in st.get("files", [])]
        if not listed:
            return {"error": "nothing to commit"}
        want = args.get("paths")
        paths = [p for p in (want if isinstance(want, list) else listed) if p in listed]
        if not paths:
            return {"error": "none of those is a changed file"}
        r = _run(repo, "add", "-A", "--", *paths, env=env)
        if r["code"]:
            return {"error": r["out"] or "could not stage"}
        r = _run(repo, "commit", "-m", msg, "--", *paths, env=env)
        if r["code"]:
            return {"error": r["out"] or "could not commit"}
        return {"ok": True, "out": r["out"], "commit": (_git(repo, "rev-parse", "--short=7", "HEAD") or "").strip()}
    if action == "discard":
        path = str(args.get("path") or "")
        st = status(repo)
        f = next((x for x in st.get("files", []) if x["path"] == path), None)
        if not f:
            return {"error": "not a changed file"}
        if f["state"] == "untracked":
            r = _run(repo, "clean", "-f", "--", path, env=env)
        else:
            r = _run(repo, "restore", "--staged", "--worktree", "--", path, env=env)
        return _done(r, f"{path} discarded")
    if action == "delete":
        name = _ok_branch(args.get("name"))
        if not name or not _has_branch(repo, name):
            return {"error": "no such branch"}
        st = status(repo)
        if name == st.get("branch"):
            return {"error": "that is the branch the tree is on — switch first"}
        if name == _main_branch(repo):
            return {"error": f"{name} is the main branch; it stays"}
        r = _run(repo, "branch", "-D" if args.get("force") else "-d", "--", name, env=env)
        if r["code"] and "not fully merged" in r["out"] and not args.get("force"):
            return {"error": f"{name} has commits that are on no other branch — deleting it loses them",
                    "unmerged": True}
        return _done(r, f"{name} deleted")
    return {"error": "unknown action"}


def _done(r, said):
    if r["code"]:
        return {"error": r["out"] or f"git failed ({r['code']})"}
    return {"ok": True, "out": r["out"] or said}


# ---- Send to Claude (R36 step 3) --------------------------------------------
# A commit, a diff, a branch or a conflict, handed to the project's session
# as a line the operator could have typed — the way a roadmap step and the
# version question arrive. The line names what was picked precisely enough
# for the session to go and read it itself (a sha, a path, a branch), and
# says what is being asked; it never carries the diff, which the session
# can read from the tree, and which would be a page of text in a prompt.

ASKS = {
    "review":  "review it: what it changes, and anything worth fixing",
    "explain": "explain what it changes and why, in plain words",
    "revert":  "revert it — a new commit undoing it — and say what that undoes",
    "rebase":  "rebase it onto {main}, resolving anything that conflicts, and say what moved",
    "merge":   "merge it into {main} — fast-forward if you can, a merge commit if not — and say what it brought in",
    "conflicts": "the tree is mid-merge with conflicts: resolve them, finish the merge, and say what you decided in each file",
    "diff":    "look at the uncommitted change and say whether it is right, before it is committed",
}


def ask(repo, project, kind, args, sessions=()):
    """Compose the ask and type it into the project's session."""
    if TELL is None or TMUX_NAME is None:
        return {"error": "no way to reach a session from here"}
    args = args if isinstance(args, dict) else {}
    main = _main_branch(repo) or "main"
    what = ASKS.get(kind)
    if not what:
        return {"error": "not a thing to ask"}
    what = what.format(main=main)
    sha, path, branch = str(args.get("sha") or ""), str(args.get("path") or ""), str(args.get("branch") or "")
    if sha:
        if not SHA_RE.match(sha) or _git(repo, "cat-file", "-e", f"{sha}^{{commit}}") is None:
            return {"error": "not a commit"}
        subject = (_git(repo, "show", "--no-patch", "--format=%s", sha) or "").strip()
        about = f"commit {sha[:7]} ({subject})"
    elif path:
        listed = {f["path"] for f in status(repo).get("files", [])}
        if path not in listed:
            return {"error": "not a changed file"}
        about = f"the uncommitted change to {path}"
    elif branch:
        if not _ok_branch(branch) or not _has_branch(repo, branch):
            return {"error": "no such branch"}
        about = f"the branch {branch}"
    elif kind == "conflicts":
        about = "the merge in progress"
    else:
        return {"error": "nothing picked"}
    line = f"From the operator, on the Git view of {project}: {about} — {what}."
    session = TMUX_NAME("claude-" + project)
    r = TELL(session, line, sessions)
    if r.get("error"):
        return r
    return {"ok": True, "sent": bool(r.get("sent")), "session": session, "text": line}
