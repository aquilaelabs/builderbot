#!/usr/bin/env python3
"""Everything behind the dashboard's memory book: what Claude remembers here.

Claude Code keeps per-project memories in `~/.claude/projects/<slug>/memory/`:
one markdown file per fact, plus MEMORY.md, an index of one line each that is
loaded into every session started in that project. The index is not a summary
of the files: it is the only part always in context, and the files are read
only when recall reaches for one. That is why it is edited here as a field
on the memory it names rather than as a document of its own. Claude writes
them; nobody reads them. That is the gap this exists to close: CLAUDE.md goes through a
pull request and a transcript is on screen, but a memory accumulates silently
and steers every later session, so a wrong one is both permanent and invisible.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server. The one rule that matters: a filesystem path is never
built from what the browser sent. A project name is matched against the
directories actually under /workspace and a file name against the directory's
own listing, so nothing the page posts can name a path that was not already
there to be named.
"""
import os as _os
import sys as _sys
# Beside this file, whichever way it was loaded: bb's own Python loads the
# modules by path, where a plain sibling import finds nothing.
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from names import running_session   # noqa: E402
from fields import field   # noqa: E402
import agents
import functools
import hashlib
import inspect
import json
import re
import threading
import time
from pathlib import Path
import statefile  # noqa: E402

# The server's, injected rather than imported: importing the server from a
# module the server imports is a circle. Same shape as toolchains.py.
run = None
WORKSPACE = None
CLAUDE_PROJECTS = None
tmux_name = None
write_json = None
actor = None
STATE = None
LOG_FILE = None


def configure(*, run, workspace, claude_projects, tmux_name,
              write_json=None, state=None):
    """Hand over the server's helpers.

    write_json and state arrived with the change log; optional so the bb CLI,
    which only reads the log, can configure with just those two through
    configure_log below.
    """
    globals().update(run=run, WORKSPACE=Path(workspace),
                     CLAUDE_PROJECTS=Path(claude_projects), tmux_name=tmux_name)
    if state is not None:
        configure_log(write_json=write_json, state=state)


def configure_log(*, write_json, state, actor=None):
    globals().update(write_json=write_json, STATE=Path(state), actor=actor)
    globals()["LOG_FILE"] = Path(state) / "memory-log.json"

def _by_whom():
    """{"who": name} for the account behind this change, or {}.

    "you" and "claude" say a person or a session and stop there; with two
    people on a project that answers nothing about which of them it was.
    The Nodes page's audit has recorded the account since accounts existed
    (server._principal), and this is the same thing for the notebook.
    """
    name = str((actor() if actor else "") or "")[:60]
    return {"who": name} if name else {}



_log_lock = threading.Lock()

# What the dashboard did to a project's memories, kept: the one half of the
# memory story that can be logged here at all. Claude writes its memories
# through its own tooling, straight to the files; those changes have no event
# to record, only mtimes. So this log answers "what did the notebook change,
# and when", which is exactly the half nobody could reconstruct.
MAX_HISTORY = 300


def _log(project, by, ev):
    if LOG_FILE is None:
        return
    with _log_lock:
        try:
            d = json.loads(LOG_FILE.read_text())
            if not isinstance(d, dict) or not isinstance(d.get("projects"), dict):
                d = {"projects": {}}
        except (OSError, ValueError):
            d = {"projects": {}}
        h = d["projects"].setdefault(project, [])
        h.append({"at": int(time.time()),
                  "by": "claude" if by == "claude" else "you", **agents.asker(by),
                  **_by_whom(), **ev})
        del h[:-MAX_HISTORY]
        try:
            write_json(LOG_FILE, d)
        except OSError:
            pass


def history(project, limit=None, since=None, find=None):
    """The notebook's memory changes, newest first, same filters as the other
    two logs."""
    if LOG_FILE is None:
        return []
    with _log_lock:
        try:
            d = json.loads(LOG_FILE.read_text())
            h = (d.get("projects") or {}).get(project) or []
        except (OSError, ValueError):
            h = []
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        try:
            cut = int(since)
            out = [e for e in out if e.get("at", 0) >= cut]
        except (TypeError, ValueError):
            pass
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if any(needle in str(e.get(k, "")).lower()
                      for k in ("text", "note", "act"))]
    try:
        n = int(limit) if limit is not None else None
    except (TypeError, ValueError):
        n = None
    if n is not None and n > 0:
        out = out[:n]
    return out


# The index Claude loads at the start of every session in the project. Not a
# memory itself (it is the table of contents), which is why it cannot be
# deleted here and why deleting a memory has to edit it.
INDEX = "MEMORY.md"

# A memory is a paragraph and some frontmatter. This is a hundred times that,
# and exists so a file that is somehow enormous is reported rather than read
# into the payload of every poll.
MAX_BYTES = 32 * 1024

# Enough that a real memory directory is never truncated, low enough that a
# directory someone has filled with something else does not become the whole
# response.
MAX_FILES = 2000


def memory_dir(project, home=None):
    """Where a project's memories live for one account (its home's
    .claude/projects, or the box's own when no home is named), or None if
    that is not a project.

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
    # path with every character that is not a letter or a digit a dash
    # (B349: its slashes alone named a folder Claude never writes for a
    # project like ep.silon). One named the old way, and not yet the new,
    # is read where it is.
    root = Path(home) / ".claude" / "projects" if home else CLAUDE_PROJECTS
    new = root / re.sub(r"[^A-Za-z0-9]", "-", str(d)) / "memory"
    old = root / str(d).replace("/", "-") / "memory"
    return old if old != new and old.is_dir() and not new.is_dir() else new


FIELD_RE = re.compile(r"^\s*(\w+):\s*(.*?)\s*$")
LINK_RE = re.compile(r"\]\(([^)\s]+)")
# A [[name]] in a memory's body: a link to another memory by its `name:` slug
# (the instructions Claude writes them under say so). Unlike the index line
# it is checked only against the memories that exist here (roadmap #4).
WIKI_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# One index line: `- [Title](file.md) <em dash> hook`, the separator Claude Code's
# own memory index uses, written here as its escape (the house rule voice). It is read as an
# em dash but arrives as whatever the keyboard produced, so any of the dashes
# is accepted and only the em dash is written back.
INDEX_RE = re.compile(r"^\s*[-*]\s*\[(?P<title>[^\]]*)\]\((?P<file>[^)\s]+)\)"
                      r"\s*(?:[\u2014\u2013-]|:)?\s*(?P<hook>.*?)\s*$")

# What a memory's `type` is allowed to be: the four Claude Code documents.
# A select rather than a text field on the page, and checked again here.
TYPES = ("user", "feedback", "project", "reference")

# A new memory's file name, which is also its `name:` field. The same shape
# Claude uses: lowercase words joined by single dashes. This is the one string
# the browser sends that becomes a file that did not exist before, so it is
# matched whole rather than sanitized: a name that is not this is refused,
# not repaired into something the operator did not type.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SLUG = 60


def _index_rows(text):
    """MEMORY.md as rows: index lines parsed, everything else kept verbatim.

    Anything that is not a line pointing at a `.md` file (a heading someone
    added, a blank line) comes back as raw and is written out untouched. The
    index is defined as one line per memory, but nothing enforces that, and
    losing a line the operator typed is a worse bug than carrying it.
    """
    rows = []
    for line in text.splitlines():
        m = INDEX_RE.match(line)
        if m and m.group("file").endswith(".md") and "/" not in m.group("file"):
            rows.append({"raw": line, "file": m.group("file"),
                         "title": m.group("title").strip(),
                         "hook": m.group("hook").strip()})
        else:
            rows.append({"raw": line})
    return rows


def _line(file, title, hook):
    """One index line, from the two fields the panel edits.

    The brackets and the parenthesis are the syntax, so they cannot survive
    inside a title that is going between them: a title carrying a `]` would
    write a line that reads back as a different one, or as none.
    """
    title = re.sub(r"[\[\]()]", "", (title or "").replace("\n", " ")).strip()
    hook = (hook or "").replace("\n", " ").strip()
    return f"- [{title or Path(file).stem}]({file})" + (f" \u2014 {hook}" if hook else "")


def _front(text):
    """name / description / type out of a memory's frontmatter.

    Four keys of a YAML subset, parsed by hand: the dashboard is stdlib-only,
    and a `key: value` reader is not worth being the first dependency in it.
    Anything unrecognized is simply not summarized: the raw file is right
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
        # thing distinguishing it, so take it wherever it appears rather than
        # tracking indentation for one field.
        if key in ("name", "description", "type") and val:
            out.setdefault(key, val.strip("'\""))
    return out


def _rev(text):
    """A memory's revision: a short digest of the bytes that were loaded.

    The file is the unit here (a memory is one document somebody types into,
    not a row of fields), so there is no per-field revision to keep and
    nothing to count. The digest is what the editor carries back at Save, and
    a mismatch means the file moved underneath it (roadmap #26).

    Content rather than an mtime: a memory is written by the panel, by `bb`,
    and by a session using its own file tools, and only the last of those
    goes through this module at all. A digest catches every one of them, and
    is the same answer on both sides of a second.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _read(p):
    """One memory file as a row, or None if it cannot be read."""
    try:
        st = p.stat()
        raw = "" if st.st_size > MAX_BYTES else p.read_text(errors="replace")
    except OSError:
        return None
    f = _front(raw)
    return {"file": p.name, "rev": _rev(raw),
            "name": f.get("name") or p.stem,
            "description": f.get("description", ""),
            "type": f.get("type", ""),
            "when": int(st.st_mtime),
            "bytes": st.st_size,
            # Empty for an oversized file, which the page reports rather than
            # offering an editor over a truncation.
            "text": raw,
            "big": st.st_size > MAX_BYTES}


def census(project, home=None):
    """How many memories this project has, and a stamp that moves when any of
    them does; one walk of the directory for both.

    The count is for the row's book icon, and is a number rather than a
    boolean because the number is the whole reason to open the book: two is a
    project Claude barely knows, twenty is one where a wrong memory has had
    time to matter.

    The stamp is for the open notebook (roadmap #26): it is what tells a
    Memory view that it is looking at yesterday's files. Mtimes rather than
    the digests `payload` builds, because this runs for every project on
    every poll and reading every memory that often to answer "no change" is
    the kind of cost nobody notices until the share is slow. It is also the
    only thing that catches the writer who never passes through this module:
    a session editing a memory with its own file tools.
    """
    d = memory_dir(project, home)
    out = {"count": 0, "rev": ""}
    if d is None:
        return out
    n, newest = 0, 0
    try:
        for p in d.glob("*.md"):
            try:
                st = p.stat()
            except OSError:
                continue
            newest = max(newest, int(st.st_mtime))
            if p.name != INDEX:
                n += 1
    except OSError:
        return out
    # The index counts towards the stamp and not towards the number: it moves
    # when a line is retitled, which is a change the tab should re-read, and
    # it is not a memory.
    return {"count": n, "rev": f"{n}:{newest}"}


def count(project):
    """How many memories this project has, for the row's book icon."""
    return census(project)["count"]


def payload(project, live=(), home=None):
    """Everything the book shows for one project, or None if it is not one."""
    d = memory_dir(project, home)
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

    # The index is not a separate document to edit: it is one line belonging
    # to each memory, so it is served on the memory it belongs to. A memory
    # with no line gets empty fields, which is the same thing the page shows
    # for one whose line says nothing.
    byfile = {r["file"]: r for r in _index_rows(index) if "file" in r}
    for m in memories:
        r = byfile.get(m["file"], {})
        m["title"] = r.get("title", "")
        m["hook"] = r.get("hook", "")
        m["listed"] = m["file"] in byfile

    # The two ways the index and the files drift apart. Neither breaks
    # anything outright, which is exactly why they need saying: a dangling
    # pointer is a line of every session's context spent on a file that is
    # gone, and an unlisted memory is one Claude only sees if recall happens
    # to surface it.
    listed, present = set(byfile), {m["file"] for m in memories}
    # A line for a file that is gone has one fix, taking it out, and the
    # view offers it as a press (fix: "tidy"). It used to say "saving takes
    # the line out" beside a Save with nothing staged, which could not be
    # pressed (B455).
    issues = [{"level": "warning", "fix": "tidy",
               "text": f"the index points at {h}, which is not here"}
              for h in sorted(listed - present)]
    issues += [{"level": "warning",
                "text": f"{f} is not in the index: Claude sees it only when "
                        "recall surfaces it, not at the start of every session"}
               for f in sorted(present - listed)]
    # The third kind (roadmap #4): a [[name]] inside a memory naming no
    # memory here. The instructions allow one that is not written yet (it
    # marks something worth writing), but the same shape is what a rename
    # leaves behind, and it has bitten once: sole-operator.md pointed at a
    # memory that had been renamed under it, and nothing said so. Named by
    # file and by link, so the fix is one edit rather than a search.
    names = {m["name"] for m in memories} | {Path(m["file"]).stem for m in memories}
    for m in memories:
        for slug in sorted({x.strip() for x in WIKI_RE.findall(m.get("text") or "")}):
            if slug and slug not in names:
                issues.append({"level": "warning",
                               "text": f"{m['file']} links to [[{slug}]], which names "
                                       "no memory here: one still to write, or one "
                                       "that was renamed"})
    if len(found) > MAX_FILES:
        issues.append({"level": "warning",
                       "text": f"{len(found) - MAX_FILES} more files here are not shown"})

    session = running_session("", project, set(live))
    return {"project": project, "dir": str(d),
            "memories": memories, "issues": issues, "types": list(TYPES),
            # The index is regenerated from the lines the memories carry, so
            # it is one more document with one more revision: a stale client
            # rewriting it drops the line another writer just added, which is
            # the third of the three exposures roadmap #26 names.
            "index_rev": _rev(index),
            # The directory's own stamp, the same one the poll carries, so an
            # open book knows which polls are news and which are its own save
            # coming back.
            "rev": census(project)["rev"],
            "exists": d.is_dir(),
            # The page offers the note only when there is somewhere to put it.
            "session": session if session in set(live) else None}


def _target(d, file):
    """The path this file name means, or None if it does not name one here.

    Every name has to already be in the directory, which is what makes it
    safe: it came from the listing. The index is deliberately not reachable
    this way: it has one writer, save_index, below.
    """
    if not file or "/" in file or file == INDEX or not file.endswith(".md"):
        return None
    try:
        if not (d / file).is_file():
            return None
    except OSError:
        return None
    return d / file


def _write(p, text):
    """Replace a memory atomically, through statefile.write_text: a
    half-written memory is still loaded at the next session start, and a
    torn frontmatter block is worse than the text it replaced (B196)."""
    statefile.write_text(p, text)


_fallback_lock = threading.RLock()


def _serialized(fn):
    """One writer at a time per memory directory, across threads and processes.

    save, save_index, create and delete each read MEMORY.md, change it and
    write it back, and nothing held the read and the write together: two
    notebook tabs adding a memory at once both appended to the index they had
    read, one rename won, and the other memory was left on disk with no index
    line, which is exactly what create() promises cannot happen (B196).

    The lock file lives under the dashboard's state, keyed by the directory,
    not beside MEMORY.md: that directory is Claude Code's, and a stray file of
    ours in it is one more thing a session has to wonder about. Claude writes
    its own memories with its own tools and takes no lock of ours, so this
    serializes the dashboard against itself, which is the half that can be.
    """
    @functools.wraps(fn)
    def held(project, *a, **kw):
        home = inspect.signature(fn).bind(project, *a, **kw).arguments.get("home")
        d = memory_dir(project, home)
        state = globals().get("STATE")
        if d is None or state is None:
            with _fallback_lock:
                return fn(project, *a, **kw)
        lockdir = Path(state) / "memlocks"
        lockdir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(d).encode()).hexdigest()[:16]
        with statefile.locked(lockdir / key):
            return fn(project, *a, **kw)
    return held


def _conflict(p, rev, what):
    """Refuse a write whose base is no longer what is on disk (roadmap #26).

    Answers with the file as it now stands, so whoever asked can show both
    and choose. A refusal that only says no leaves the words that were typed
    with nowhere to go, which is worse than the overwrite it prevented.

    No `by`: a memory is a file, and the writer that most often moves one is
    a session using its own file tools, which passes through nothing that
    could record a name. The time it changed is honest and is all there is.
    """
    if not rev:
        return None
    try:
        now = p.read_text(errors="replace") if p.is_file() else ""
        at = int(p.stat().st_mtime) if p.is_file() else 0
    except OSError:
        return None
    if _rev(now) == rev:
        return None
    return {"error": f"this {what} changed while you had it open",
            "conflict": {"rev": _rev(now), "current": now, "at": at}}


@_serialized
def save(project, file, text, rev=None, home=None):
    d = memory_dir(project, home)
    if d is None:
        return {"error": f"not a project: {project}"}
    if file == INDEX:
        return {"error": "the index is written from the memories themselves"}
    p = _target(d, file)
    if p is None:
        return {"error": f"no memory called {file} here"}
    if len(text.encode()) > MAX_BYTES:
        return {"error": "too large to be a memory"}
    if (bad := _conflict(p, rev, "memory")):
        return bad
    # Newline-terminated: these are read by Claude as markdown, and a file
    # whose last line has no ending runs into whatever follows it.
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _write(p, text)
    except OSError as e:
        return {"error": f"could not write {file}: {e}"}
    _log(project, "you", {"act": "edited", "text": file})
    return {"ok": True, "when": int(time.time())}


@_serialized
def save_index(project, entries, rev=None, home=None):
    """Rewrite MEMORY.md from the one line each memory carries.

    The index is regenerated rather than edited as text, so it cannot end up
    describing memories that are not there, but it is regenerated *in place*:
    a memory already listed keeps its position, because the order is the only
    thing in the file nobody can reconstruct, and the operator may well have
    put the important one at the top. New memories land at the end.

    Lines pointing at files that are gone come out, which is the second half
    of the warning the panel shows for them. Lines that are not index lines
    at all are left exactly where they were.
    """
    d = memory_dir(project, home)
    if d is None:
        return {"error": f"not a project: {project}"}
    want = {}
    for e in entries:
        f = e.get("file") if isinstance(e, dict) else None
        if isinstance(f, str) and _target(d, f) is not None and f not in want:
            want[f] = e
    p = d / INDEX
    try:
        before = p.read_text(errors="replace") if p.is_file() else ""
    except OSError as e:
        return {"error": f"could not read the index: {e}"}
    if rev and _rev(before) != rev:
        return {"error": "the index changed while you had it open",
                "conflict": {"rev": _rev(before), "current": before,
                             "at": int(p.stat().st_mtime) if p.is_file() else 0}}
    try:
        present = {q.name for q in d.glob("*.md") if q.is_file() and q.name != INDEX}
    except OSError:
        present = set(want)
    out, seen = [], set()
    for r in _index_rows(before):
        f = r.get("file")
        if f is None:
            out.append(r["raw"])
        elif f in seen:
            pass                      # a second line for the same memory
        elif f in want:
            seen.add(f)
            out.append(_line(f, want[f].get("title"), want[f].get("hook")))
        elif f in present:
            seen.add(f)
            out.append(r["raw"])      # a memory this payload said nothing about
        # What is left points at a file that is not here: dropped, which is the
        # second half of the warning the panel shows for it.
    for f, e in want.items():
        if f not in seen:
            out.append(_line(f, e.get("title"), e.get("hook")))
    text = "\n".join(out).rstrip("\n") + "\n" if out else ""
    if text == before:
        return {"ok": True, "unchanged": True}
    try:
        d.mkdir(parents=True, exist_ok=True)
        _write(p, text)
    except OSError as e:
        return {"error": f"could not write the index: {e}"}
    _log(project, "you", {"act": "edited", "text": INDEX})
    return {"ok": True, "when": int(time.time())}


@_serialized
def create(project, name, title, hook, mtype, body, home=None):
    """Write a new memory, and give it its line in the index.

    Both halves or neither: a file with no index line is invisible until
    recall happens to surface it, which is the failure mode the panel warns
    about, and it should not be the thing the panel's own button produces.
    """
    d = memory_dir(project, home)
    if d is None:
        return {"error": f"not a project: {project}"}
    name = (name or "").strip()
    if not SLUG_RE.match(name) or len(name) > MAX_SLUG:
        return {"error": "a name is lowercase words joined by dashes, "
                         f"up to {MAX_SLUG} characters"}
    if mtype not in TYPES:
        return {"error": f"a memory is one of: {', '.join(TYPES)}"}
    hook = (hook or "").replace("\n", " ").strip()
    if not hook:
        return {"error": "a memory needs a one-line description: it is what "
                         "recall matches against"}
    body = (body or "").strip()
    if not body:
        return {"error": "a memory with no body is a title with nothing behind it"}
    file = name + ".md"
    p = d / file
    try:
        d.mkdir(parents=True, exist_ok=True)
        if p.exists():
            return {"error": f"{file} is already here"}
    except OSError as e:
        return {"error": f"could not reach the memory directory: {e}"}
    text = (f"---\nname: {name}\ndescription: {hook}\n"
            f"metadata:\n  type: {mtype}\n---\n\n{body}\n")
    if len(text.encode()) > MAX_BYTES:
        return {"error": "too large to be a memory"}
    try:
        # Exclusive: two panels open on the same project should not have the
        # second one silently replace the first one's memory.
        with open(p, "x") as fh:
            fh.write(text)
    except FileExistsError:
        return {"error": f"{file} is already here"}
    except OSError as e:
        return {"error": f"could not write {file}: {e}"}
    ip = d / INDEX
    try:
        before = ip.read_text(errors="replace") if ip.is_file() else ""
        _write(ip, (before.rstrip("\n") + "\n" if before.strip() else "")
               + _line(file, title, hook) + "\n")
    except OSError as e:
        return {"error": f"{file} was written, but the index was not: {e}"}
    _log(project, "you", {"act": "wrote", "text": file, "note": hook})
    return {"ok": True, "file": file}


def _unindex(d, file):
    """Drop the index line pointing at a file that is going away.

    Deleting the file alone would leave every future session loading a pointer
    to nothing, which reads to Claude as a memory that exists and cannot be
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


@_serialized
def delete(project, file, home=None):
    d = memory_dir(project, home)
    if d is None:
        return {"error": f"not a project: {project}"}
    if file == INDEX:
        # Removing it loses the pointer to every memory at once, which is
        # never what one bin icon should mean. It is not offered (there is no
        # row for it any more), so this is the belt to that braces.
        return {"error": "the index is not a memory"}
    p = _target(d, file)
    if p is None:
        return {"error": f"no memory called {file} here"}
    try:
        p.unlink()
    except OSError as e:
        return {"error": f"could not remove {file}: {e}"}
    _unindex(d, file)
    _log(project, "you", {"act": "forgot", "text": file})
    return {"ok": True}


# ---- the Memory panel's verbs, one call from the dashboard -------------------

# The roadmap's unsaved mark, set by server.py: a memory edit marks the same
# flag the list does (roadmap.mark_unsaved).
mark_unsaved = None

# The actions of verb() that write. The server counts a person's edit for
# the sessions' catch-up by these, and a history read is not one of them
# (B296).
WRITES = ("save", "index", "create", "delete")


def verb(proj, act, req, home):
    """Edit, delete or create one of this project's memories, rewrite the
    index, or read the history, once server.py has let this account at the
    project. `home` is whose memories: the reader's own home, never the
    owner's (B67). The project and file names go through untouched because
    this module is the thing that checks them against what is on disk.
    (payload, status)."""
    file = field(req, "file")
    if act == "save":
        r = save(proj, file, field(req, "text"), rev=field(req, "rev"), home=home)
    elif act == "index":
        r = save_index(proj, [e for e in (req.get("lines") or []) if isinstance(e, dict)],
                       rev=field(req, "rev"), home=home)
    elif act == "create":
        r = create(proj, field(req, "name"), field(req, "title"),
                   field(req, "hook"), field(req, "type"),
                   field(req, "body"), home=home)
    elif act == "delete":
        r = delete(proj, file, home=home)
    elif act == "history":
        return {"history": history(
            proj, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))}, 200
    else:
        return {"error": f"unknown action: {act}"}, 400
    # One Save for the project, not one per thing in the panel: a memory
    # edit marks the same flag the list does, and the one button spends the
    # one line telling a session about all of it.
    if not r.get("error"):
        mark_unsaved(proj, "memory")
    # A conflict answers 200 (see the roadmap's). The whole file as it now
    # stands rides back in it, which is what lets the editor show both
    # versions instead of just losing the typing.
    return r, (400 if r.get("error") and not r.get("conflict") else 200)
