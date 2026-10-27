"""What each session on a project is changing, and where two of them collide.

Since roadmap #24 more than one person can work a project at once, each in a
worktree of their own. That makes them SAFE (they cannot overwrite each other
or commit each other's work) and it does not make them coordinated: two people
can still spend an afternoon rewriting the same function and find out at the
merge.

This is what tells them earlier. Two sources, and the cheaper one is the
truthful one:

  * GIT, which is exact. Every tree's uncommitted work is `git status`, and a
    file changed in two trees at once is a collision, full stop. No hook, no
    heuristic, nothing to keep in step with a model's intentions.
  * THE HOOK, which is finer and best-effort. A PreToolUse hook sees the file
    an edit is about to touch and guesses the enclosing symbol from the text
    around it. Function-level, and a guess, recorded as one.

Git is asked live and stored nowhere: a record of what a tree contains would
be a second copy of something git already answers, and the copy is the one
that goes stale. Only the hook's notes are written down, because nothing else
remembers them.

Deliberately no UI. The operator asked for the notes to exist and to be
readable from the command line, and a tab for them can come later if they turn
out to be worth looking at.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

STATE = Path("/config")
WORKSPACE = Path("/workspace")
write_json = None
_lock = threading.RLock()

# How long a hook note is worth reporting. A session that touched a file an
# hour ago and has not come back to it is not "currently changing" it, which is
# the claim these notes are read as making.
NOTE_TTL = 3600


def configure(*, state, workspace, write_json):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace),
                     write_json=write_json)


def _file():
    return STATE / "session-work.json"


def _git(cwd, *args):
    try:
        # GIT_OPTIONAL_LOCKS=0: a status here is a read, and without it git
        # refreshes the index and writes it, which on a synced project is a
        # change the node's own next index then conflicted with (B617).
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                           text=True, timeout=20, check=False,
                           env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def trees(project, worktrees):
    """{label: path} for every working tree this project is being worked in.

    The project directory is the owner's; the rest are worktrees named for the
    account id that owns them, which is how they are laid out on disk.
    """
    out = {"": WORKSPACE / project}
    root = Path(worktrees) / project
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir():
                out[d.name] = d
    except OSError:
        pass
    return {k: v for k, v in out.items() if v.is_dir()}


def changed(path):
    """Files with uncommitted work in this tree, staged or not, plus the
    untracked ones; a new file two people both added is a collision too.

    Porcelain v1 because its shape has been stable for a decade: XY, a space,
    then the path. A rename carries `old -> new` and the new name is the one
    that matters here.
    """
    out = set()
    for ln in _git(path, "status", "--porcelain", "--untracked-files=all"):
        name = ln[3:] if len(ln) > 3 else ""
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        name = name.strip().strip('"')
        if name:
            out.add(name)
    return out


def collisions(project, worktrees, names=None):
    """[{file, trees: [label, ...]}] for files being changed in more than one
    tree at once. `names` maps a tree's label to an account name.

    Ordered by how many trees are involved and then by path, so the worst is
    first and the answer is stable enough to diff between runs.
    """
    names = names or {}
    seen = {}
    for label, path in trees(project, worktrees).items():
        for f in changed(path):
            seen.setdefault(f, []).append(names.get(label, label or "owner"))
    out = [{"file": f, "trees": sorted(who)}
           for f, who in seen.items() if len(who) > 1]
    out.sort(key=lambda r: (-len(r["trees"]), r["file"]))
    return out


# --- the hook's notes ------------------------------------------------------
#
# One record per (project, session), holding the files it has touched and the
# symbol it was in when it touched them. Written by the hook on every edit and
# read by `bb work`; nothing else depends on it, so a hook that never runs
# leaves the git half working on its own.

def key(uid, agent="", slot=1):
    """The notes' key for one session: the account, and the coding agent
    after a slash when it is not Claude (R95). One person's Claude and Codex
    sessions on a project are two sessions, each told when the other has
    the file it is about to edit; Claude's key is the account alone, as it
    always was. A slot past the first (R143) adds its number after a #:
    one person's two Claude sessions are two sessions too."""
    agent = str(agent or "")
    k = str(uid) if agent in ("", "claude") else f"{uid}/{agent}"
    return k + (f"#{slot}" if str(slot).isdigit() and int(slot) > 1 else "")


def said(k, names=None):
    """A notes key as a reader says it: the account's name (from `names`, a
    uid to name map, or the key itself), and which coding agent's session
    it is: "sam (Claude Code)", "sam (Codex CLI)"."""
    k, _, slot = str(k).partition("#")
    uid, _, agent = k.partition("/")
    who = (names or {}).get(uid) or uid or "owner"
    product = agent or "Claude Code"
    try:
        # Loaded by path from bb work too (dash.load), so the table beside
        # this file is put on the path first (B229).
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import agents
        a = agents.get(agent or "claude")
        product = a.product if a else product
    except ImportError:
        pass
    return f"{who} ({product}{f' {slot}' if slot else ''})"


def note(project, session, path, symbol=""):
    """Record that `session` is editing `path`, inside `symbol` if known."""
    project, session = str(project), str(session)
    if not project or not session or not path:
        return
    with _lock:
        d = _load()
        rec = d.setdefault(project, {}).setdefault(session, {})
        files = rec.setdefault("files", {})
        syms = files.setdefault(str(path)[:400], [])
        if symbol and symbol not in syms:
            syms.append(str(symbol)[:120])
            del syms[8:]
        rec["at"] = int(time.time())
        write_json(_file(), d)


def notes(project, live=None):
    """{session: {files: {path: [symbol, ...]}, at}} for this project.

    Stale ones are dropped on read rather than swept: a session that ended, or
    one that has not touched anything for an hour, is not "currently changing"
    anything, and that is the claim a reader takes from this.
    """
    now = time.time()
    out = {}
    for session, rec in (_load().get(str(project)) or {}).items():
        if live is not None and session not in live:
            continue
        if now - (rec.get("at") or 0) > NOTE_TTL:
            continue
        out[session] = rec
    return out


def others_touching(project, session, path, live=None):
    """Which OTHER sessions have this file among their notes. The question the
    hook asks before an edit, and the reason the notes exist."""
    return sorted(s for s, rec in notes(project, live).items()
                  if s != session and str(path) in (rec.get("files") or {}))


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}
