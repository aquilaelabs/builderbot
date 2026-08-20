#!/usr/bin/env python3
"""Everything behind the dashboard's memory book — what Claude remembers here.

Claude Code keeps per-project memories in `~/.claude/projects/<slug>/memory/`:
one markdown file per fact, plus MEMORY.md, an index of one line each that is
loaded into every session started in that project. Claude writes them; nobody
reads them. That is the gap this exists to close — CLAUDE.md goes through a
pull request and a transcript is on screen, but a memory accumulates silently
and steers every later session, so a wrong one is both permanent and invisible.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server. The one rule that matters: a filesystem path is never
built from what the browser sent. A project name is matched against the
directories actually under /workspace and a file name against the directory's
own listing, so nothing the page posts can name a path that was not already
there to be named.
"""
import re
import time
from pathlib import Path

# The server's, injected rather than imported: importing the server from a
# module the server imports is a circle. Same shape as packages.py.
run = None
WORKSPACE = None
CLAUDE_PROJECTS = None
tmux_name = None


def configure(*, run, workspace, claude_projects, tmux_name):
    """Hand over the server's helpers."""
    globals().update(run=run, WORKSPACE=Path(workspace),
                     CLAUDE_PROJECTS=Path(claude_projects), tmux_name=tmux_name)


# The index Claude loads at the start of every session in the project. Not a
# memory itself — it is the table of contents — which is why it cannot be
# deleted here and why deleting a memory has to edit it.
INDEX = "MEMORY.md"

# A memory is a paragraph and some frontmatter. This is a hundred times that,
# and exists so a file that is somehow enormous is reported rather than read
# into the payload of every poll.
MAX_BYTES = 32 * 1024

# Enough that a real memory directory is never truncated, low enough that a
# directory someone has filled with something else does not become the whole
# response.
MAX_FILES = 200


def memory_dir(project):
    """Where a project's memories live, or None if that is not a project.

    The name is checked against /workspace rather than joined onto it. This is
    the only place in the dashboard where operator input becomes a filesystem
    path, and a name that came back off the real listing cannot climb out of
    the directory it was listed from.
    """
    if not project or "/" in project or project in (".", ".."):
        return None
    try:
        d = WORKSPACE / project
        if not d.is_dir():
            return None
    except OSError:
        return None
    # The same slug Claude Code uses for transcripts: the working directory's
    # path with the slashes turned into dashes.
    return CLAUDE_PROJECTS / str(d).replace("/", "-") / "memory"


FIELD_RE = re.compile(r"^\s*(\w+):\s*(.*?)\s*$")
LINK_RE = re.compile(r"\]\(([^)\s]+)")


def _front(text):
    """name / description / type out of a memory's frontmatter.

    Four keys of a YAML subset, parsed by hand: the dashboard is stdlib-only,
    and a `key: value` reader is not worth being the first dependency in it.
    Anything unrecognized is simply not summarized — the raw file is right
    there in the editor, and this only fills in the row above it.
    """
    out = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = FIELD_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # `type` is nested under `metadata:`, and the nesting is the only
        # thing distinguishing it — so take it wherever it appears rather than
        # tracking indentation for one field.
        if key in ("name", "description", "type") and val:
            out.setdefault(key, val.strip("'\""))
    return out


def _read(p):
    """One memory file as a row, or None if it cannot be read."""
    try:
        st = p.stat()
        raw = "" if st.st_size > MAX_BYTES else p.read_text(errors="replace")
    except OSError:
        return None
    f = _front(raw)
    return {"file": p.name,
            "name": f.get("name") or p.stem,
            "description": f.get("description", ""),
            "type": f.get("type", ""),
            "when": int(st.st_mtime),
            "bytes": st.st_size,
            # Empty for an oversized file, which the page reports rather than
            # offering an editor over a truncation.
            "text": raw,
            "big": st.st_size > MAX_BYTES}


def count(project):
    """How many memories this project has — for the row's book icon.

    Read on every status poll, so it is a directory listing and nothing more.
    A count rather than a boolean because the number is the whole reason to
    open the book: two is a project Claude barely knows, twenty is one where
    a wrong memory has had time to matter.
    """
    d = memory_dir(project)
    if d is None:
        return 0
    try:
        return sum(1 for p in d.glob("*.md") if p.name != INDEX and p.is_file())
    except OSError:
        return 0


def payload(project, live=()):
    """Everything the book shows for one project, or None if it is not one."""
    d = memory_dir(project)
    if d is None:
        return None
    index, memories = "", []
    try:
        found = sorted(p for p in d.glob("*.md") if p.is_file())
    except OSError:
        found = []
    for p in found[:MAX_FILES]:
        if p.name == INDEX:
            m = _read(p)
            index = m["text"] if m else ""
            continue
        m = _read(p)
        if m:
            memories.append(m)
    memories.sort(key=lambda m: -m["when"])

    # The two ways the index and the files drift apart. Neither breaks
    # anything outright, which is exactly why they need saying: a dangling
    # pointer is a line of every session's context spent on a file that is
    # gone, and an unlisted memory is one Claude only sees if recall happens
    # to surface it.
    listed = {h for h in LINK_RE.findall(index) if h.endswith(".md")}
    present = {m["file"] for m in memories}
    issues = [{"level": "warning",
               "text": f"the index points at {h}, which is not here"}
              for h in sorted(listed - present)]
    issues += [{"level": "warning",
                "text": f"{f} is not in the index — Claude sees it only when "
                        "recall surfaces it, not at the start of every session"}
               for f in sorted(present - listed)]
    if len(found) > MAX_FILES:
        issues.append({"level": "warning",
                       "text": f"{len(found) - MAX_FILES} more files here are not shown"})

    session = tmux_name("claude-" + project)
    return {"project": project, "dir": str(d), "index": index,
            "memories": memories, "issues": issues,
            "exists": d.is_dir(),
            # The page offers the note only when there is somewhere to put it.
            "session": session if session in set(live) else None}


def _target(d, file):
    """The path this file name means, or None if it does not name one here.

    The index is allowed by name because it may not exist yet — saving is how
    it gets created. Everything else has to already be in the directory, which
    is what makes the name safe: it came from the listing.
    """
    if not file or "/" in file or not file.endswith(".md"):
        return None
    if file == INDEX:
        return d / INDEX
    try:
        if not (d / file).is_file():
            return None
    except OSError:
        return None
    return d / file


def _write(p, text):
    """Replace a file's contents atomically.

    Through a temporary file in the same directory: a half-written memory is
    still loaded at the next session start, and a truncated frontmatter block
    is worse than the text it replaced.
    """
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(p)


def save(project, file, text):
    d = memory_dir(project)
    if d is None:
        return {"error": f"not a project: {project}"}
    p = _target(d, file)
    if p is None:
        return {"error": f"no memory called {file} here"}
    if len(text.encode()) > MAX_BYTES:
        return {"error": "too large to be a memory"}
    # Newline-terminated: these are read by Claude as markdown, and a file
    # whose last line has no ending runs into whatever follows it.
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _write(p, text)
    except OSError as e:
        return {"error": f"could not write {file}: {e}"}
    return {"ok": True, "when": int(time.time())}


def _unindex(d, file):
    """Drop the index line pointing at a file that is going away.

    Deleting the file alone would leave every future session loading a pointer
    to nothing — which reads to Claude as a memory that exists and cannot be
    found, the most confusing of the available outcomes.
    """
    p = d / INDEX
    try:
        lines = p.read_text(errors="replace").splitlines(keepends=True)
    except OSError:
        return
    kept = [ln for ln in lines if file not in LINK_RE.findall(ln)]
    if len(kept) != len(lines):
        try:
            _write(p, "".join(kept))
        except OSError:
            pass


def delete(project, file):
    d = memory_dir(project)
    if d is None:
        return {"error": f"not a project: {project}"}
    if file == INDEX:
        # The index is regenerated from nothing by no one — Claude appends to
        # it. Emptying it is a save; removing it loses the pointers to every
        # memory at once, which is never what one bin icon should mean.
        return {"error": "the index is not a memory — edit it instead"}
    p = _target(d, file)
    if p is None:
        return {"error": f"no memory called {file} here"}
    try:
        p.unlink()
    except OSError as e:
        return {"error": f"could not remove {file}: {e}"}
    _unindex(d, file)
    return {"ok": True}


# No digits, deliberately — see notify().
NOTE = ("I edited your memory files for this project from the dashboard. "
        "Please re-read them before relying on what you remember here.")


def notify(project, live=()):
    """Type the note into this project's Claude pane, without pressing Enter.

    What makes an edit land in a session that is *already running* is Claude
    reading the files again, and the only channel into a running session is its
    terminal. Enter is deliberately not sent: the dashboard's "waiting" covers
    a session sitting at its prompt and one showing a permission dialog alike,
    and a blind Enter into the second would answer it. So the line is left in
    the input box for the operator to send when they look — and it is written
    without digits, because typing a digit is how that dialog picks an option.
    """
    d = memory_dir(project)
    if d is None:
        return {"error": f"not a project: {project}"}
    session = tmux_name("claude-" + project)
    if session not in set(live):
        return {"error": "no Claude session running here"}
    r = run(["tmux", "send-keys", "-t", session, "-l", "--", NOTE], timeout=10)
    if r["code"] != 0:
        return r
    return {"ok": True, "typed": NOTE}
