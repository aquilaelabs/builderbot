#!/usr/bin/env python3
"""The notebook's Git view: what a project's repository holds, read out for
the page, and the handful of things the page may do to it (roadmap R36).

Every answer is git plumbing run on the CONTROLLER against
the project's tree on the share (the one place with the credentials, the
worktrees and every account's author) and shaped for the page: the
uncommitted changes, the recent history with parents (the page draws the
lanes), one commit with its files and diff, a file's uncommitted diff, and
the branches with how far each stands from main and its upstream, marked
with whose worktree sits on it.

Deliberately narrow at the boundary. A sha is forty hex characters or
fewer, a path is one `git ls-files` or `git status` reported, a ref is one
`git for-each-ref` handed out. Nothing typed into a URL reaches a command
line as anything but a checked value. Output is capped: a diff past
DIFF_MAX bytes is cut with a line saying so, because a page is not the
place to read a vendored library's arrival.

Path-pure like changelog.py: functions take the project's directory,
configure() only knows where the workspace and the worktrees are.
"""
import os
import sys
import re
import shutil
import hashlib
import subprocess
import threading
from pathlib import Path

# Its own directory on the path, so a test can load this file alone (git.mjs
# does) and still find statefile beside it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statefile  # noqa: E402
from fields import field  # noqa: E402
from names import claude_session  # noqa: E402

WORKSPACE = None
WORKTREES = None
STATE = None
TELL = None               # notify.tell: type a line into a session, injected
TMUX_NAME = None
ACCOUNTS = None           # () -> {uid: account name}, injected: whose a branch is
OWNER_UID = None          # () -> the owner's uid: the project directory is their tree
WORKING = None            # (project, uid) -> whether that account's Claude session there is mid-prompt
# ...and what in_use() and verb() need from the server:
OWNER_NAME = None         # () -> the owner's account name, for "your" or theirs
SESSION_OPEN = None       # project -> whether the owner's Claude session is open in its directory
SESSIONS = None           # () -> every session running, for the ask
GIT_ENV = None            # (account, project) -> what git runs under: the author, the credentials
MAY_PUSH = None           # project -> whether it was cloned with push rights
EXCLUDE = None            # tree -> the code map kept out of a new repository
AUDIT = None              # (principal, action, project, detail) -> the audit row

LOG_MAX = 100             # commits the graph shows
DIFF_MAX = 200_000        # bytes of diff the page is handed
SHA_RE = re.compile(r"^[0-9a-f]{4,40}$")
US = "\x1f"
# git's id for a tree with nothing in it: the base of a branch with no shared history.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def configure(*, workspace, worktrees=None, tell=None, tmux_name=None, state=None,
              accounts=None, owner_uid=None, working=None, owner_name=None, session_open=None,
              sessions=None, git_env=None, may_push=None, exclude=None, audit=None):
    globals().update(WORKSPACE=Path(workspace),
                     WORKTREES=Path(worktrees) if worktrees else Path(workspace) / ".worktrees",
                     TELL=tell, TMUX_NAME=tmux_name, ACCOUNTS=accounts, OWNER_UID=owner_uid,
                     WORKING=working, OWNER_NAME=owner_name, SESSION_OPEN=session_open,
                     SESSIONS=sessions, GIT_ENV=git_env, MAY_PUSH=may_push, EXCLUDE=exclude,
                     AUDIT=audit,
                     STATE=Path(state) if state else None)


# ---- reading a tree without running what it carries (B153) -----------------
#
# A session can write .git/config, .git/hooks and .gitattributes in its own
# project, and git EXECUTES what those name: core.fsmonitor on status, a
# textconv driver on diff, a hook on checkout. The controller ran
# `git -C <tree>` as the dashboard's account whenever somebody opened the Git
# view, so a session on a node could have code run here by waiting for that.
# Measured, not supposed: all three fire.
#
# What stops it is that each of those is NAMED by the tree but DEFINED in
# config. With a git dir of the controller's own the definitions are ours: an
# attribute naming a driver we do not define is ignored, the hooks are ours,
# fsmonitor is ours. The worktree is still attached, so status and diff read
# the real tree and answer honestly. Measured too: none of the three runs, and
# status still reports the dirty file.
#
# Objects are borrowed through alternates rather than copied, and refs are
# mirrored by READING them off the filesystem rather than by asking git in the
# tree, which would be the same exposure one step smaller. gitrelay owns that
# reading already, for git's network half (B148).
#
# WRITES go the same way, with the parts of the tree that are DATA rather than
# instructions kept: its objects, so a commit's objects land where the session
# will look for them, and its index, so what somebody staged is what gets
# committed. What the command moved in our refs is written back into the tree
# afterwards, under compare-and-swap, and a merge left in conflict has its
# state files carried across so the session can still finish it.
#
# One thing writes have that reads do not: a filter the tree names decides what
# CONTENT git stores, so skipping it is not free the way skipping a textconv
# driver is. The distinction that makes this safe is where the filter is
# DEFINED. git-lfs is installed into the system config by the image, outside
# any tree, so it still applies here and an LFS repository still commits
# pointers. A filter in the tree's OWN config is the attacker-controlled one,
# it does not apply, and rather than quietly commit raw bytes the controller
# refuses the write and says a terminal has to do it.
#
# The write dir is a second directory, not the read one: reads run constantly
# off the poll and rebuild the mirror as they go, and a mirror being rebuilt
# under a commit is how the two would corrupt each other.

# Keys copied out of the tree's config into ours: the ones the view reports
# and the ones a fetch or a push needs. An allowlist rather than a prefix,
# because `remote.<name>.uploadpack` and `receivepack` name a PROGRAM git runs
# for a local-path remote and they sit under the same prefix as the address.
CONFIG_KEEP = {"remote": ("url", "pushurl", "fetch", "push", "mirror", "prune", "tagopt"),
               "branch": ("remote", "pushremote", "merge", "rebase")}
# ext:: and fd:: are not addresses: they are commands git runs to reach one.
RUNS_A_COMMAND = re.compile(r"^\s*(ext|fd)::", re.I)
# What the tree's config may name that decides the CONTENT git writes, as
# against the much longer list of what it may name that git merely runs. A
# textconv is not here: it decides how a diff is shown and never what is
# stored, so skipping it costs a prettier diff and nothing else.
FILTERS = re.compile(r"^filter\.")
MERGERS = re.compile(r"^merge\.[^.]+\.driver$")
# A merge or a revert in progress is these files beside the refs. They are
# per-operation state, mirrored in with the refs and back out with them, so a
# conflict the dashboard started is one the session can finish.
STATE_FILES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "ORIG_HEAD",
               "CHERRY_PICK_HEAD", "REVERT_HEAD", "AUTO_MERGE")
ZERO = "0" * 40


def _own(repo, write=False):
    """A git dir of the controller's for reading `repo`, or None.

    None means "could not build one", and the caller falls back to the tree: a
    Git view that goes blank is worse than one still doing what it always did.
    The refusal says so in the log rather than passing quietly.
    """
    if STATE is None:
        return None
    try:
        import gitrelay                                    # noqa: PLC0415
        common = Path(repo) / ".git"
        if common.is_symlink() or not common.is_dir():
            return None
        common = common.resolve()
        d = (STATE / "gitview"
             / (hashlib.sha256(str(common).encode()).hexdigest()[:16] + (".w" if write else "")))
        for sub in ("refs/heads", "refs/tags", "objects/info", "hooks"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        _atomic(d / "objects" / "info" / "alternates", f"{common / 'objects'}\n")
        if write:
            # A loose ref left by the last write would shadow the mirror below
            # and the next one would read a branch the tree no longer has
            # there. The mirror is the only truth in this directory.
            for sub in ("heads", "tags", "remotes"):
                shutil.rmtree(d / "refs" / sub, ignore_errors=True)
            (d / "refs" / "heads").mkdir(parents=True, exist_ok=True)
            _carry(common, d)
        # The tree's remotes and upstreams, which the view reports and which sit
        # in config beside the dangerous keys. `git config --file` is a plain
        # file read that runs nothing. Only these two prefixes: every other key
        # in that file is one the tree wanted us to obey.
        #
        # Composed and written ONCE. Writing a base and then appending keys left
        # a window in which a concurrent read saw a config with no remotes, and
        # this runs on the poll path where there is always another read about
        # to happen: the Git view lost its upstream at random.
        got = subprocess.run(["git", "config", "--file", str(common / "config"),
                              "--get-regexp", r"^(remote|branch)\."],
                             capture_output=True, text=True, timeout=10, check=False)
        sections = {}
        for line in (got.stdout or "").splitlines():
            key, _, val = line.partition(" ")
            bits = key.split(".")
            if len(bits) < 3 or bits[-1].lower() not in CONFIG_KEEP.get(bits[0], ()):
                continue
            if bits[-1].lower() in ("url", "pushurl") and RUNS_A_COMMAND.match(val):
                continue
            sections.setdefault((bits[0], ".".join(bits[1:-1])), []).append((bits[-1], val))
        text = ["[core]", "\trepositoryformatversion = 0", "\tbare = false",
                # Housekeeping in somebody else's repository is not ours to
                # start: writes here land in the tree's object store, and an
                # auto gc would repack and prune it on our schedule.
                "[gc]", "\tauto = 0",
                '[protocol "ext"]', "\tallow = never",
                '[protocol "fd"]', "\tallow = never"]
        for (kind, name), pairs in sorted(sections.items()):
            text.append(f'[{kind} "{gitrelay._q(name)[1:-1]}"]')
            text += [f"\t{k} = {gitrelay._q(v)}" for k, v in pairs]
        _atomic(d / "config", "\n".join(text) + "\n")
        tree_refs = gitrelay.refs(common)
        _atomic(d / "packed-refs", "# pack-refs with: sorted \n"
                + "".join(f"{tree_refs[n]} {n}\n" for n in sorted(tree_refs)))
        # gitrelay's shape: a symbolic ref needs the `ref: ` prefix, and git
        # rejects the whole directory without it.
        h = gitrelay.head(common) or "refs/heads/main"
        _atomic(d / "HEAD", f"ref: {h}\n" if h.startswith("refs/") else f"{h}\n")
        return d
    except Exception as e:                                  # noqa: BLE001
        print(f"dashboard: reading {repo} through the controller's own git dir failed "
              f"({e}); falling back to the tree, which runs what the tree carries (B153)",
              flush=True)
        return None


def _atomic(path, text):
    """Write `text` at `path`, all of it or none of it: statefile.write_text,
    whose temporary name is unique per call. A fixed `.new` raced with itself
    here: the Git view polls, two reads built the mirror at once, and the
    second rename found the file already moved, which _own answered by
    falling back to the tree (B153, git.mjs asserts the log carries no
    fallback)."""
    statefile.write_text(path, text)


def _carry(src, dst):
    """The merge-in-progress files from one git dir to another, both ways round.

    Absent in the source means absent in the destination: a merge finished in
    the tree has to stop being a merge in our copy, and one we abandoned has to
    stop being one in the tree.
    """
    for name in STATE_FILES:
        a, b = Path(src) / name, Path(dst) / name
        try:
            if a.is_file() and not a.is_symlink():
                shutil.copyfile(a, b)
            elif b.exists():
                b.unlink()
        except OSError:
            pass


def _refs_of(d):
    """{refname: object id} in a git dir of ours, by asking git in it.

    Symbolic refs are left out, which is the mirror's rule too, so the before
    and the after are the same shape. It matters: a fetch writes
    refs/remotes/origin/HEAD pointing at origin/main, and carrying both across
    is two updates for one ref, which git refuses as the contradiction it is.
    """
    out = {}
    try:
        got = subprocess.run(["git", f"--git-dir={d}", "for-each-ref",
                              f"--format=%(refname){US}%(objectname){US}%(symref)"],
                             capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return out
    for line in (got.stdout or "").splitlines():
        name, oid, symref = (line.split(US) + ["", ""])[:3]
        if name and oid and not symref:
            out[name] = oid
    return out


def _upstreams_of(d):
    """{key: value} for the branch.* config in a git dir: what `push -u` sets.

    The one thing a write puts in CONFIG rather than in a ref. Our config is a
    mirror rebuilt from the tree every time, so an upstream set here would be
    thrown away on the next write and the branch would ask to be pushed with
    -u forever.
    """
    out = {}
    try:
        got = subprocess.run(["git", f"--git-dir={d}", "config", "--get-regexp", r"^branch\."],
                             capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return out
    for line in (got.stdout or "").splitlines():
        key, _, val = line.partition(" ")
        bits = key.split(".")
        if len(bits) >= 3 and bits[-1].lower() in CONFIG_KEEP["branch"]:
            out[key] = val
    return out


def _head_of(d):
    """What HEAD names in a git dir of ours: a ref, or a commit when detached."""
    for args in (["symbolic-ref", "-q", "HEAD"], ["rev-parse", "-q", "--verify", "HEAD"]):
        try:
            got = subprocess.run(["git", f"--git-dir={d}", *args], capture_output=True,
                                 text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    return ""


def _in_tree(repo, hooks, *args, stdin=None):
    """One ref command in the TREE's git dir; "" or what went wrong.

    The only thing that runs there, and the narrowest command git has for it.
    Hooks are pointed at an empty directory of ours because git runs a
    `reference-transaction` hook on an update, and that hook is the tree's.
    """
    try:
        r = subprocess.run(["git", f"--git-dir={Path(repo) / '.git'}",
                            "-c", f"core.hooksPath={hooks}", *args],
                           input=stdin, capture_output=True, text=True,
                           timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return "" if r.returncode == 0 else ((r.stderr or r.stdout or "").strip() or "git failed")


def _apply(repo, d, before, head_before, ups_before=None):
    """Move into the tree whatever the command moved in our git dir.

    Compare-and-swap on every ref: the old value is what the tree held when
    the mirror was taken, so a transaction that would land on top of something
    changed in the tree meanwhile fails rather than overwriting it.
    """
    said = []
    for key, val in sorted(_upstreams_of(d).items()):
        if (ups_before or {}).get(key) != val:
            # `git config --file` edits a file and runs nothing, which is why
            # the tree's config is safe to write even though it is not safe to
            # obey.
            subprocess.run(["git", "config", "--file", str(Path(repo) / ".git" / "config"),
                            key, val], capture_output=True, timeout=10, check=False)
    after = _refs_of(d)
    lines = [f"update {n} {oid} {before.get(n, ZERO)}"
             for n, oid in sorted(after.items()) if before.get(n) != oid]
    lines += [f"delete {n} {before[n]}" for n in sorted(before) if n not in after]
    if lines:
        said.append(_in_tree(repo, d / "hooks", "update-ref", "--stdin",
                             stdin="".join(f"{ln}\n" for ln in lines)))
    head_after = _head_of(d)
    if head_after and head_after != head_before:
        said.append(_in_tree(repo, d / "hooks",
                             *(["symbolic-ref", "HEAD", head_after] if head_after.startswith("refs/")
                               else ["update-ref", "--no-deref", "HEAD", head_after])))
    _carry(d, Path(repo) / ".git")
    return "; ".join(s for s in said if s)


def _tree_drivers(repo, merging=False):
    """The keys in the TREE's own config that decide what content git writes.

    Empty for almost every repository. A filter counts for anything that puts
    bytes in or takes them out of the working tree; a merge driver counts only
    for a merge. What the OPERATOR installed is not here and still applies:
    git-lfs lives in the system config, which is not a tree's to write.
    """
    try:
        got = subprocess.run(["git", "config", "--file", str(Path(repo) / ".git" / "config"),
                              "--name-only", "--get-regexp", r"^(filter|merge)\."],
                             capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({k for k in (got.stdout or "").split()
                   if FILTERS.match(k) or (merging and MERGERS.match(k))})


def _no_drivers(repo, merging=False):
    """Why this repository's files are not the controller's to write, or None."""
    keys = _tree_drivers(repo, merging)
    if not keys or _own(repo) is None:
        return None
    named = ", ".join(keys[:3]) + (f" and {len(keys) - 3} more" if len(keys) > 3 else "")
    return {"error": f"this repository defines {named} in its own .git/config. Git runs the "
                     f"programs those name, the dashboard does not run a tree's own programs, "
                     f"and what it stored would be the unfiltered bytes. Do this one from a "
                     f"terminal, or ask Claude"}


def _git(repo, *args, timeout=20):
    """stdout of one git READ in `repo`, or None when it failed.

    Through the controller's own git dir where one can be built, so the tree's
    hooks, fsmonitor and diff drivers are not this process's to run (B153).
    """
    own = _own(repo)
    argv = (["git", f"--git-dir={own}", f"--work-tree={repo}", *args] if own
            else ["git", "-C", str(repo), *args])
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    if own:
        # The tree's index, so what somebody staged in their own checkout is
        # what status reports. An index is data git reads, not a place it is
        # told to run anything.
        env["GIT_INDEX_FILE"] = str(Path(repo) / ".git" / "index")
    try:
        r = subprocess.run(argv, capture_output=True,
                           text=True, timeout=timeout, check=False, env=env)
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

    `who` is the account the branch belongs to (branch_owner), by name.
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
    names = ACCOUNTS() if ACCOUNTS else {}
    # Which refs main already contains, in one call rather than one per row,
    # and for the REMOTE refs too (roadmap R69 step 1). Until this the
    # "only on <host>" fold knew nothing about its own rows, so the one safe
    # delete, a branch whose every commit is already on main, was the one
    # thing the view could not offer.
    merged_refs = set((_git(repo, "for-each-ref", "--merged", main, "--format=%(refname)",
                            "refs/heads", "refs/remotes") or "").split()) if main else set()
    rows = []
    for line in out.splitlines():
        f = line.split(US)
        if len(f) < 7:
            continue
        name, ref, short, when, up, track, head = f[:7]
        remote = ref.startswith("refs/remotes/")
        # The full ref: origin/HEAD's SHORT name is "origin", so the check on
        # the short name let it through as a branch called origin.
        if remote and ref.endswith("/HEAD"):
            continue
        ahead = behind = 0
        m = re.search(r"ahead (\d+)", track or "")
        if m:
            ahead = int(m.group(1))
        m = re.search(r"behind (\d+)", track or "")
        if m:
            behind = int(m.group(1))
        ma = mb = 0
        same = False
        if main and not remote and name != main:
            lr = _git(repo, "rev-list", "--left-right", "--count", f"{main}...{name}")
            if lr:
                parts = lr.split()
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    mb, ma = int(parts[0]), int(parts[1])
            # Commits main lacks, but nothing in them main does not already
            # have: work that shipped another way, a revert, a rebuild
            # elsewhere (R69 step 3). Ancestry alone calls that "N commits
            # waiting", which is what sent somebody merge-tree archaeology to
            # find out that merging it would move no file. Three dots, so the
            # question is what the branch ADDS since they parted, which does
            # not stop being true the next time main moves.
            #
            # A READ, through _git. It went through _run once, and _run
            # rebuilds the write directory before it starts: this is on the
            # Git view's poll path, so every poll tore the refs and the merge
            # state out from under whatever write was in flight (B203).
            # --quiet answers 0 for no difference, and _git answers None for
            # anything else, a failure included, which reads as "not the
            # same" and is the safe way to be wrong.
            if ma:
                same = _git(repo, "diff", "--quiet", f"{main}...{name}") is not None
        wt = trees.get(ref, "")
        rows.append({"name": name, "remote": remote, "head": head.strip() == "*",
                     "short": short, "when": int(when or 0), "upstream": up,
                     "ahead": ahead, "behind": behind,
                     "main_ahead": ma, "main_behind": mb,
                     # Nothing on it that main lacks: the row's one question
                     # is "is this work waiting, or done", and this is done.
                     # True of a remote row as readily as a local one, which
                     # is what lets the fold offer Delete on the safe ones.
                     "merged": bool(main) and name != main and ref in merged_refs,
                     # Commits main lacks that change nothing main lacks.
                     "same": same,
                     "worktree": wt,
                     "who": "" if remote else names.get(
                         branch_owner(repo, name, trees, main, names), "")})
    return {"main": main, "branches": rows}


def remote_url(repo):
    """origin's address, or "" when there is none."""
    return (_git(repo, "remote", "get-url", "origin") or "").strip()


def compare(repo, name):
    """A branch against main: the commits main lacks and the diff main would
    take, which is what a pull request page shows before its button. Read
    here so that page is not needed to look before Merge into main."""
    name = _ok_branch(name)
    main = _main_branch(repo)
    if not name or not _has_branch(repo, name):
        return {"error": "no such branch"}
    if not main:
        return {"error": "no main branch to compare against"}
    if name == main:
        return {"error": f"{main} is the branch the others are compared against"}
    fmt = US.join(["%H", "%h", "%an", "%at", "%s"])
    commits = []
    for line in (_git(repo, "log", f"--format={fmt}", f"{main}..{name}") or "").splitlines():
        f = line.split(US)
        if len(f) == 5:
            commits.append({"sha": f[0], "short": f[1], "author": f[2],
                            "when": int(f[3] or 0), "subject": f[4]})
    # From where the two part: git's three-dot form, except for a branch
    # that shares no history with main at all, which three dots answer
    # with nothing. Against the empty tree, everything on it is the diff.
    base = (_git(repo, "merge-base", main, name) or "").strip() or EMPTY_TREE
    files = []
    for line in (_git(repo, "diff", "--numstat", base, name) or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            files.append({"path": parts[2],
                          "added": int(parts[0]) if parts[0].isdigit() else None,
                          "removed": int(parts[1]) if parts[1].isdigit() else None})
    diff = _git(repo, "diff", "--no-color", base, name, timeout=30) or ""
    return {"name": name, "main": main, "commits": commits, "files": files, "diff": _cap(diff)}


def _main_branch(repo):
    for cand in ("main", "master"):
        if _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{cand}") is not None:
            return cand
    return ""


def _worktrees(repo):
    """{ref: path} for every worktree of the repository, the main one
    included; `git worktree list --porcelain` names both."""
    out = _git(repo, "worktree", "list", "--porcelain") or ""
    trees, path = {}, ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and path:
            trees[line[len("branch "):]] = path
    return trees


UID_RE = re.compile(r"^u_[0-9a-f]{8}$")


def branch_owner(repo, branch, trees=None, main=None, names=None):
    """The uid of the account whose session a branch is, or "" for nobody's.

    Checked out in <worktrees>/<project>/<uid>, it is that account's; the
    branch the project directory itself is on is the owner's, whose session
    works there; claude/<name> for an account that exists is that account's,
    so a branch outlives its worktree as its author's. main is everybody's.
    The names were read off the branch alone once, so the owner's session's
    claude/<topic> branches were labelled as sessions of accounts called
    <topic>.
    """
    main = _main_branch(repo) if main is None else main
    if not branch or branch == main:
        return ""
    trees = _worktrees(repo) if trees is None else trees
    at = trees.get(f"refs/heads/{branch}")
    if at:
        p = Path(at).resolve()
        if p == Path(repo).resolve():
            return (OWNER_UID() if OWNER_UID else "") or ""
        if WORKTREES and UID_RE.match(p.name) \
                and p.parent == (WORKTREES / Path(repo).name).resolve():
            return p.name
    if branch.startswith("claude/"):
        names = (ACCOUNTS() if ACCOUNTS else {}) if names is None else names
        want = branch[len("claude/"):]
        return next((uid for uid, n in names.items() if n == want), "")
    return ""


# What changes the project directory's working tree, the owner's (B236):
# action -> (what, for "only X can ..."; the question an administrator is put).
TREE_WRITES = {
    "commit": ("commit in it", "Commit in {who}'s working tree?"),
    "discard": ("discard a change in it", "Discard this change in {who}'s working tree?"),
    "revert": ("revert a commit in it", "Revert this commit in {who}'s working tree?"),
    "pull": ("pull into it", "Pull into {who}'s working tree?"),
    "switch": ("switch its branch", "Switch {who}'s working tree to another branch?"),
}


def not_yours(repo, action, args, uid, kind="", admin=False):
    """What stands between this account and doing this to a branch that is
    another account's session's (branch_owner): {} for nothing, {"error"} for
    a refusal, {"confirm"} for the question to put before sending it again
    with `confirmed`.

    The operator's rule, 24 Sep. A branch's own account does as it likes with
    it, and main is everybody's. Anybody else who is not an administrator may
    not merge it, merge into it, have a session merge or rebase it, switch to
    it or delete it. An administrator may, since an administrator controls
    everything, with two guards on a merge: never while that account's Claude
    session on the project is working, because a branch mid-prompt holds
    whatever half of the change has landed; and only when asked, each time,
    naming whose it is.
    """
    args = args if isinstance(args, dict) else {}
    names = ACCOUNTS() if ACCOUNTS else {}
    # The project directory is the owner's session's tree (B236): what writes
    # its working files or moves its branch is the owner's, or an
    # administrator's who is asked and waits for that session to finish.
    tree = TREE_WRITES.get(action) or (TREE_WRITES["switch"] if action == "branch" and args.get("switch") else None)
    owner = (OWNER_UID() if OWNER_UID else "") or ""
    if tree and owner and owner != uid:
        who = names.get(owner) or "the owner"
        what, ask = tree
        if not admin:
            return {"error": f"the project directory is {who}'s working tree: only {who} can {what}"}
        if WORKING and WORKING(Path(repo).name, owner):
            return {"error": f"{who}'s Claude session is working in the project directory: "
                             f"{what} when it is waiting"}
        if not args.get("confirmed"):
            return {"confirm": f"{ask.format(who=who)}\n\nThe project directory is {who}'s working tree."}
    if action == "merge":
        name = str(args.get("name") or "")
        into = str(args.get("into") or "") or (status(repo).get("branch") or "")
        ask = f"Merge {name} into {into}?"
        pairs = [(name, "merges it"), (into, "merges into it")]
    elif action == "ask" and kind in ("merge", "rebase"):
        name = str(args.get("branch") or "")
        ask = f"Ask Claude to {kind} {name} {'into' if kind == 'merge' else 'onto'} {_main_branch(repo)}?"
        pairs = [(name, f"has Claude {kind} it")]
    elif action in ("switch", "delete"):
        ask = ""
        pairs = [(str(args.get("name") or ""), "switches to it" if action == "switch" else "deletes it")]
    else:
        return {}
    main, trees = _main_branch(repo), _worktrees(repo)
    for b, what in pairs:
        o = branch_owner(repo, b, trees, main, names)
        if not o or o == uid:
            continue
        who = names.get(o) or "another account"
        if not admin:
            return {"error": f"{b} is {who}'s session's branch: only {who} {what}"}
        if not ask:
            continue                 # an administrator switches and deletes as git allows
        if WORKING and WORKING(Path(repo).name, o):
            return {"error": f"{who}'s Claude session is working right now: "
                             f"{ask[0].lower()}{ask[1:-1]} when it is waiting"}
        if not args.get("confirmed"):
            return {"confirm": f"{ask}\n\n{b} is {who}'s session's branch."}
    return {}


def _cap(text):
    b = text.encode("utf-8", "replace")
    if len(b) <= DIFF_MAX:
        return text
    cut = b[:DIFF_MAX].decode("utf-8", "ignore")
    return cut + f"\n… cut at {DIFF_MAX // 1000}kB; the rest is in the repository\n"


def payload(project, what, sha="", path="", n=None, branch=""):
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
    if what == "compare":
        return compare(repo, branch)
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
# A remote's name: the first segment of a row like origin/claude/x, and
# never a path of its own.
REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
NET_TIMEOUT = 120


def _creds(repo):
    """The credential helper for this project, out of the CONTROLLER's own
    record rather than out of the tree's config.

    B153 is why this is needed at all: the mirror copies `remote.*` and
    `branch.*` from the tree and nothing else, because a credential helper is
    a command the tree names and this process is not going to run what a
    checkout asks it to. The consequence was a Git view that could read
    everything and reach nothing: Fetch and Pull on an https remote died on
    "could not read Username for https://...: terminal prompts disabled",
    which is git saying it had no credential and no terminal to ask at.

    There is one, and it is ours: linking the project wrote it to
    /config/gitcreds/<project> (projects.write_token), so naming it here
    trusts the tree with nothing. Added rather than substituted, so a
    controller that authenticates through gh for everything keeps doing so.
    """
    try:
        import projects                                     # noqa: PLC0415
        return projects.token_helper(Path(repo).name)
    except (ImportError, TypeError, OSError):
        return ""                       # no projects module, its STATE unset (TypeError), or the file unreadable


def _run(repo, *args, env=None, timeout=30, index=True):
    """{code, out} of one git command, stderr folded into out.

    Through the controller's own git dir where one can be built, so what the
    tree's config names is not this process's to run (B153). `index=False` for
    a command that has no business with the working tree: plumbing that reads
    objects and writes objects, where handing it the tree's index would let it
    stage things under somebody who is working in that checkout.
    """
    with _writing(repo):
        return _run_locked(repo, *args, env=env, timeout=timeout, index=index)


# One write at a time per repository. The write directory is ONE directory per
# tree, emptied and mirrored afresh at the start of every write and carried
# back at the end, so two writes overlapping is the second deleting the refs
# the first is standing on. The server answers each request on its own
# thread, so that takes two people, or one person and a session, and nothing
# rarer than that.
_write_locks = {}
_write_locks_guard = threading.Lock()


def _writing(repo):
    key = str(Path(repo).resolve())
    with _write_locks_guard:
        return _write_locks.setdefault(key, threading.RLock())


def _run_locked(repo, *args, env=None, timeout=30, index=True):
    own = _own(repo, write=True)
    before, head_before, ups_before = {}, "", {}
    if own:
        before, head_before = _refs_of(own), _head_of(own)
        ups_before = _upstreams_of(own)
        argv = ["git", f"--git-dir={own}", f"--work-tree={repo}", *args]
    else:
        argv = ["git", "-C", str(repo), *args]
    # ...and the credential, which the mirror deliberately does not carry.
    cred = _creds(repo)
    if cred:
        # The empty helper first resets git's list, so the shared gh helper
        # the image installs globally is not asked ahead of the project's
        # own token and does not receive it back (the review of 26 Sep).
        argv[1:1] = ["-c", "credential.helper=", "-c", f"credential.helper={cred}"]
    e = {**os.environ, **(env or {}), "GIT_TERMINAL_PROMPT": "0"}
    if own:
        # The tree's object store, so a commit's objects land where the
        # session looks for them rather than in a directory of ours.
        e["GIT_OBJECT_DIRECTORY"] = str(Path(repo) / ".git" / "objects")
        if index:
            e["GIT_INDEX_FILE"] = str(Path(repo) / ".git" / "index")
    try:
        r = subprocess.run(argv, capture_output=True,
                           text=True, timeout=timeout, check=False, env=e)
    except subprocess.TimeoutExpired:
        return {"code": 124, "out": f"git {args[0]} took longer than {timeout}s"}
    except OSError as ex:
        return {"code": 1, "out": str(ex)}
    out = ((r.stdout or "") + (r.stderr or "")).strip()[-4000:]
    if own:
        said = _apply(repo, own, before, head_before, ups_before)
        if said and not r.returncode:
            return {"code": 1, "out": f"{args[0]} ran, but the tree still stands where it "
                                      f"did: {said}"}
    return {"code": r.returncode, "out": out}


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
    # The one action for a tree that has no repository: a project adopted
    # from a directory, or unpacked from an archive that carried none, can
    # otherwise never be versioned, built into dist/ or pushed, and the Git
    # view showed "nothing to show" with no way on. On main, nothing
    # committed: the first commit is the person's or a session's.
    if action == "init":
        if is_repo(repo):
            return {"error": "already a git repository"}
        r = _run(repo, "init", "-b", "main", timeout=30)
        return _done(r, "a repository, on main, with nothing committed yet", repo)
    if not is_repo(repo):
        return {"error": "not a git repository"}
    if action in ("pull", "switch", "revert", "commit", "discard"):
        # Every one of these writes the working tree through git's filters.
        # `merge` asks lower down, where it is known whether this one checks
        # anything out; fetch, push and the branch verbs never touch a file.
        no = _no_drivers(repo)
        if no:
            return no
    if action == "fetch":
        r = _run(repo, "fetch", "--prune", env=env, timeout=NET_TIMEOUT)
        return _done(r, "fetched", repo)
    if action == "pull":
        if _dirty(repo):
            return {"error": "there are uncommitted changes: commit or discard them first, so a pull cannot land on top of them"}
        r = _run(repo, "pull", "--ff-only", env=env, timeout=NET_TIMEOUT)
        if r["code"] and "diverged" in r["out"] or r["code"] and "Not possible to fast-forward" in r["out"]:
            return {"error": "the branch and its upstream have both moved: this only fast-forwards; merge or rebase from a shell, or ask Claude"}
        return _done(r, "pulled", repo)
    if action == "push":
        if not may_push:
            return {"error": "this project has no push rights: they are granted in the clone dialog, once"}
        st = status(repo)
        branch = st.get("branch") or ""
        if not branch or branch == "(detached)":
            return {"error": "not on a branch"}
        r = (_run(repo, "push", env=env, timeout=NET_TIMEOUT) if st.get("upstream")
             else _run(repo, "push", "-u", "origin", branch, env=env, timeout=NET_TIMEOUT))
        return _done(r, "pushed", repo)
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
            return {"error": "there are uncommitted changes: commit or discard them before switching, so they cannot be carried onto the wrong branch"}
        r = _run(repo, "switch", "--", name, env=env)
        return _done(r, f"on {name}")
    if action == "merge":
        # Into the branch the tree is ON, which is what git does and the only
        # thing a person can reason about from a row: to put a feature into
        # main you Switch to main and press Merge on the feature. Nothing
        # here switches for you: a button that moved the tree under you on
        # the way to doing something else is how you lose track of where you
        # are.
        name = _ok_branch(args.get("name"))
        if not name or not _has_branch(repo, name):
            return {"error": "no such branch"}
        here = (status(repo).get("branch") or "")
        into = _ok_branch(args.get("into")) if args.get("into") else here
        if not into or into == "(detached)":
            return {"error": "not on a branch"}
        if name == into:
            return {"error": f"{name} is the branch the tree is on" if into == here
                             else f"{name} cannot be merged into itself"}
        # Two branches with no commit in common (B234). git refuses them by
        # default, because it is usually the wrong branch; here it is how a
        # project that began without a repository comes together, so the
        # page asks and sends `unrelated` with the answer. Asked last on each
        # path below, after every refusal that stands whatever the answer.
        unrelated = _git(repo, "merge-base", f"refs/heads/{into}", f"refs/heads/{name}") is None \
            and _has_branch(repo, into)
        ask_first = {"error": f"{name} and {into} share no history", "unrelated": True} \
            if unrelated and not args.get("unrelated") else None
        if into != here:
            # Into a branch the tree is NOT on: main, from wherever the tree
            # stands. The pull request button does exactly this on a server,
            # and nobody's checkout moves; here it is a temporary worktree on
            # `into`, merged in and removed, so the session working in the
            # project directory sees nothing change under it. Only main: the
            # other direction, main into the branch you are on, is the
            # in-place merge below, and anything else is a shell's.
            main = _main_branch(repo)
            if into != main:
                # No main at all (B164): a repository whose only branches
                # are neither main nor master. The name was interpolated
                # empty and the refusal read "or on :".
                if not main:
                    return {"error": f"this project has no main or master branch, so there is "
                                     f"nothing to merge into: a merge from here lands on {here}"}
                return {"error": f"a merge from here lands on {here}, or on {main}: "
                                 f"Switch to {into} to merge into it"}
            if not _has_branch(repo, into):
                return {"error": "no such branch"}
            behind = _behind_upstream(repo, into)
            if behind:
                return {"error": behind}
            return ask_first or _merge_off_tree(repo, name, into, env, unrelated=unrelated)
        no = _no_drivers(repo, merging=True)
        if no:
            return no
        if _dirty(repo):
            return {"error": "there are uncommitted changes: commit or discard them first, "
                             "so the merge is its own commit"}
        if into == _main_branch(repo):
            behind = _behind_upstream(repo, into)
            if behind:
                return {"error": behind}
        if ask_first:
            return ask_first
        r = _run(repo, "merge", "--no-edit", *(["--allow-unrelated-histories"] if unrelated else []),
                 name, env=env)
        if r["code"]:
            # LEFT IN CONFLICT on purpose, where revert aborts. A conflicted
            # merge is a state this view already knows: the Changes section
            # lists the files and offers the merge in progress to the
            # session, which is the one thing that can finish it. Aborting
            # would throw that away to say the same sentence.
            if any(f["state"] == "conflict" for f in status(repo).get("files", [])):
                return {"error": f"{name} does not merge into {into} cleanly: the files are "
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
            return {"error": "there are uncommitted changes: commit or discard them first, so the revert is its own commit"}
        extra = ["-m", "1"] if len(parents) > 1 else []
        r = _run(repo, "revert", "--no-edit", *extra, sha, env=env)
        if r["code"]:
            _run(repo, "revert", "--abort", env=env)
            return {"error": "the revert does not apply cleanly, so it was abandoned; ask Claude to do it by hand"}
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
            return {"error": "that is the branch the tree is on; switch first"}
        if name == _main_branch(repo):
            return {"error": f"{name} is the main branch; it stays"}
        r = _run(repo, "branch", "-D" if args.get("force") else "-d", "--", name, env=env)
        if r["code"] and "not fully merged" in r["out"] and not args.get("force"):
            # git's own answer is about COMMITS, and it is right about those.
            # Whether anything would be LOST is a different question, and for
            # work that shipped another way the answer is no: say which of
            # the two this is, so the second press is a decision rather than
            # a shrug (R69 step 3).
            main = _main_branch(repo)
            same = bool(main) and _run(repo, "diff", "--quiet", f"{main}...{name}",
                                       index=False)["code"] == 0
            return {"error": (f"{name} has commits that are on no other branch, but nothing in "
                              f"them that {main} does not already have: deleting it loses the "
                              "history and no work") if same else
                             f"{name} has commits that are on no other branch: deleting it loses them",
                    "unmerged": True, "same": same}
        return _done(r, f"{name} deleted")
    if action == "delete-remote":
        # The branch on the git host, which is a push that removes a ref
        # rather than anything local (R69 step 1). Offered only where it
        # cannot lose work: every commit on it is already on main, checked
        # HERE and not only in the view, because what the row says and what
        # the button does have to be the same fact.
        if not may_push:
            return {"error": "this project has no push rights: they are granted in the clone dialog, once"}
        full = str(args.get("name") or "")
        remote, _, branch = full.partition("/")
        if not REMOTE_RE.fullmatch(remote) or not _ok_branch(branch):
            return {"error": "not a remote branch"}
        ref = f"refs/remotes/{remote}/{branch}"
        if _git(repo, "show-ref", "--verify", "--quiet", ref) is None:
            return {"error": f"there is no {full} here; Fetch first"}
        main = _main_branch(repo)
        if not main:
            return {"error": "this project has no main or master branch to judge a delete against"}
        if branch in ("main", "master", "HEAD"):
            return {"error": f"{full} is the main branch on the host; it stays"}
        if _run(repo, "merge-base", "--is-ancestor", ref, main, index=False)["code"]:
            return {"error": f"{full} has commits {main} does not: merge it first, or remove it "
                             "on the host, where the warning is the host's to give"}
        r = _run(repo, "push", remote, "--delete", branch, env=env, timeout=NET_TIMEOUT)
        if r["code"]:
            return _done(r, "", repo)
        # The remote-tracking ref goes with it, by the ordinary path rather
        # than by hand, so the view redraws from what the remote now says.
        _run(repo, "fetch", "--prune", env=env, timeout=NET_TIMEOUT)
        return {"ok": True, "out": f"{full} deleted on {remote}"}
    return {"error": "unknown action"}


def _behind_upstream(repo, branch):
    """Why a merge into `branch` should wait, or "" when it should not.

    A merge into a branch whose upstream has moved is how a copy of main on
    the share ends up 294 commits behind the git host and one commit ahead of
    it at the same time: the merge is fine, and then it cannot go anywhere
    without a reconcile nobody asked for (R69 step 2). The network bar
    already says pull first when both have moved; this is the same sentence
    said before the thing that causes it, rather than after.
    """
    up = (_git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
               f"{branch}@{{upstream}}") or "").strip()
    if not up:
        return ""
    n = (_git(repo, "rev-list", "--count", f"{branch}..{up}") or "").strip()
    if not n.isdigit() or not int(n):
        return ""
    return (f"{branch} here is {n} commit{'' if n == '1' else 's'} behind {up}: Pull first, so "
            f"the merge lands on what the host already has rather than leaving {branch} "
            "both ahead and behind")


def _merge_off_tree(repo, name, into, env, unrelated=False):
    """Merge `name` into `into` with nothing checked out; {ok, out} or {error}.

    The pull request button's job, and nobody's checkout moves. This used to
    stand on `into` in a temporary worktree; it is plumbing now, which is
    better on every count that matters here. No files are written, so the tree
    a session is working in is untouched and no content filter is involved,
    which is what lets it run on a repository the controller will not commit
    in. It is also the merge git itself does: the same three-way, the same
    message, the same two parents in the same order.
    """
    a = (_git(repo, "rev-parse", "--verify", f"refs/heads/{into}") or "").strip()
    b = (_git(repo, "rev-parse", "--verify", f"refs/heads/{name}") or "").strip()
    if not a or not b:
        return {"error": "no such branch"}
    if _git(repo, "merge-base", "--is-ancestor", b, a) is not None:
        return {"ok": True, "out": f"{name} is already in {into}"}
    msg = f"Merge branch '{name}' into {into}"
    if _git(repo, "merge-base", "--is-ancestor", a, b) is not None:
        new, msg = b, f"{into}: fast-forward to {name}"
    else:
        # git 2.38 (Oct 2022) and the oldest thing this module requires of
        # git; `bb doctor` checks for it by name, because the controller and
        # a node are built from different Ubuntus and have differed by a
        # release without anything saying so.
        r = _run(repo, "merge-tree", "--write-tree",
                 *(["--allow-unrelated-histories"] if unrelated else []), a, b, env=env, index=False)
        first = ((r["out"] or "").splitlines() or [""])[0].strip()
        if r["code"] or not SHA_RE.match(first):
            return {"error": f"{name} does not merge into {into} cleanly: Send to Claude "
                             f"with merge into {into} picked, and it resolves the clash "
                             f"on its branch"}
        r = _run(repo, "commit-tree", first, "-p", a, "-p", b, "-m", msg, env=env, index=False)
        new = ((r["out"] or "").splitlines() or [""])[0].strip()
        if r["code"] or not SHA_RE.match(new):
            return {"error": r["out"] or "could not make the merge commit"}
    r = _run(repo, "update-ref", "-m", msg, f"refs/heads/{into}", new, a, env=env, index=False)
    if r["code"]:
        return {"error": r["out"] or f"could not move {into}"}
    return {"ok": True, "out": f"merged {name} into {into}"}


# What git says when it wanted a credential and had neither one nor a
# terminal to ask at. It is the truth and it names nothing a person can do,
# which is the half this replaces.
NO_CRED = re.compile(r"could not read Username|could not read Password|Authentication failed", re.I)


def _done(r, said, repo=None):
    if r["code"]:
        out = r["out"] or f"git failed ({r['code']})"
        if repo is not None and NO_CRED.search(out):
            return {"error": _no_cred_why(repo, out)}
        return {"error": out}
    return {"ok": True, "out": r["out"] or said}


def _no_cred_why(repo, out):
    """The refusal for a network action the host would not let through.

    Two different situations wear one message from git, so they are told
    apart here: a project with no stored token has nothing to authenticate
    with, and one with a token that the host rejected has the wrong token.
    Both name what to do; git's own line names only what happened.
    """
    host = ""
    m = re.search(r"https?://([^/'\"\s]+)", out)
    if m:
        host = m.group(1)
    where = f"{host} " if host else ""
    if _creds(repo):
        return (f"{where}rejected the token stored for this project: it is expired, revoked "
                "or made for another scope. The project's settings dialog takes a new one "
                "under Access token.")
    return (f"this project has no access token stored, and {where}asks for one: put it in the "
            "project's settings dialog under Access token, or point the remote at ssh. "
            "Git said it had no credential and no terminal to ask at.")


# ---- Send to Claude (R36 step 3) --------------------------------------------
# A commit, a diff, a branch or a conflict, handed to the project's session
# as a line the operator could have typed, the way a roadmap step and the
# version question arrive. The line names what was picked precisely enough
# for the session to go and read it itself (a sha, a path, a branch), and
# says what is being asked; it never carries the diff, which the session
# can read from the tree, and which would be a page of text in a prompt.

ASKS = {
    "review":  "review it: what it changes, and anything worth fixing",
    "explain": "explain what it changes and why, in plain words",
    "revert":  "revert it (a new commit undoing it) and say what that undoes",
    "rebase":  "rebase it onto {main}, resolving anything that conflicts, and say what moved",
    "merge":   "merge it into {main} (fast-forward if you can, a merge commit if not) and say what it brought in",
    "conflicts": "the tree is mid-merge with conflicts: resolve them, finish the merge, and say what you decided in each file",
    "diff":    "look at the uncommitted change and say whether it is right, before it is committed",
}


def ask(repo, project, kind, args, sessions=(), session=""):
    """Compose the ask and type it into `session`: the presser's own Claude
    session on the project (B235). The bare name alone was the owner's, so a
    second account's press typed into the owner's conversation."""
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
    line = f"From the operator, on the Git view of {project}: {about}; {what}."
    session = session or TMUX_NAME("claude-" + project)
    r = TELL(session, line, sessions)
    if r.get("error"):
        return r
    return {"ok": True, "sent": bool(r.get("sent")), "session": session, "text": line}


# ---- the Git view's actions, one call from the dashboard's /api/git ----------

def in_use(project, action, args, uid):
    """Why the project directory's own Claude session keeps this action off
    it right now, or "". Both a switch and a merge rewrite the working tree.
    A merge is not a switch, but it lands other people's files in a
    directory a session is reading and editing right now, which is the same
    surprise for the same reason, so it waits for the same moment.

    A merge INTO ANOTHER branch (into: main, from wherever the tree stands)
    is done with plumbing and checks nothing out, so it moves nothing here
    and the session is no reason to refuse it: that is the merge the
    operator makes to accept a session's work while it keeps working."""
    lands_here = action == "switch" or (
        action == "merge" and str(args.get("into") or "")
        in ("", status(WORKSPACE / project).get("branch") or ""))
    if not lands_here:
        return ""
    # The project directory is the owner's session's tree. A switch waits
    # while that session is open at all, since it changes the branch the
    # session is on; a merge only while it is WORKING, since a session at
    # its prompt sees the changed files when it next reads them, and it
    # was one merely open that refused the operator's own merge, 24 Sep.
    # "your" to the owner: "the owner's" read as somebody else's.
    owner_uid = OWNER_UID()
    whose = "your" if uid == owner_uid else f"{OWNER_NAME()}'s"
    if action == "switch":
        if SESSION_OPEN(project):
            return (f"{whose} Claude session is running in this directory; end it "
                    "before switching the branch under it")
    elif WORKING(project, owner_uid):
        return f"{whose} Claude session is working in this directory; merge when it is waiting"
    return ""


def verb(project, action, req, me, *, prefix, principal):
    """One of the Git view's actions (roadmap R36 step 2), once server.py
    has let this account act on the project and in_use() has said the tree
    is free: `ask` puts a question to the presser's own session, and
    anything else is act() under the account's author and the project's
    own credentials, audited. {ok} or {error}."""
    if action == "ask":
        # The presser's own session, by the name the roadmap's send uses
        # (B235): the bare name alone was the owner's.
        return ask(WORKSPACE / project, project, field(req, "kind"), req.get("args") or {},
                   SESSIONS(), session=prefix + claude_session(project))
    r = act(WORKSPACE / project, action, req.get("args") or {}, env=GIT_ENV(me, project),
            may_push=MAY_PUSH(project))
    if action == "init" and r.get("ok"):
        EXCLUDE(WORKSPACE / project)      # the code map is never the project's
    if r.get("ok"):
        AUDIT(principal, "git-" + action, project,
              {k: v for k, v in (req.get("args") or {}).items()
               if k in ("name", "sha", "path", "at")})
    return r
