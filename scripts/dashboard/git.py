#!/usr/bin/env python3
"""The notebook's Git view: what a project's repository holds, read out for
the page (roadmap R36, step 1).

Read-only here. Every answer is git plumbing run on the CONTROLLER against
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

LOG_MAX = 100             # commits the graph shows
DIFF_MAX = 200_000        # bytes of diff the page is handed
SHA_RE = re.compile(r"^[0-9a-f]{4,40}$")
US = "\x1f"


def configure(*, workspace, worktrees=None):
    globals().update(WORKSPACE=Path(workspace),
                     WORKTREES=Path(worktrees) if worktrees else Path(workspace) / ".worktrees")


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
