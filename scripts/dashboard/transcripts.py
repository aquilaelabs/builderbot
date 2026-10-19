"""A session's conversation as a text a person can keep: what they said,
what Claude said, every command it ran and what came back, from the
transcript Claude Code writes as it goes.

Claude Code keeps one .jsonl per session under the account's projects
directory on the share (/workspace/.claude/<uid>/projects/<slug>/, the
working directory's path with its slashes turned to dashes: common.sh's
claude_projects_link), which is why the controller can read a node's
sessions here. This lists an account's own, newest first, and renders one
as plain text: a turn a line, the tool calls with their command and the
whole of what the tool answered, so `bb roadmap` and its reply are in it
as they were. Claude's private reasoning is not conversation and is left
out. The Profile page offers each as a download; only the account's own.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path("/workspace")
WORKTREES = WORKSPACE / ".worktrees"
# root_for(uid): the account's ~/.claude/projects, which is its directory
# on the share (server.home_for through lib/common.sh's user_home).
root_for = None
MAX_LIST = 60
# The most text one download carries: past this it says so and stops, since
# a person wants a file that opens. A day-long session's transcript runs to
# hundreds of megabytes on disk (the briefing rides on every turn) and
# renders to a tenth of that in a couple of seconds, so this is a fence,
# not a limit anybody meets.
MAX_OUT = 256 * 1024 * 1024


def configure(*, workspace, root_for):
    globals().update(WORKSPACE=Path(workspace), WORKTREES=Path(workspace) / ".worktrees",
                     root_for=root_for)


def _slug(path):
    return str(path).replace("/", "-")


def _dirs(uid, project):
    """Where this account's sessions on the project wrote: the project's
    own tree, and the account's worktree of it."""
    base = Path(root_for(uid))
    return [base / _slug(WORKSPACE / project),
            base / _slug(WORKTREES / project / uid)]


def dirs(uid, project):
    """The same, for the server's resume offer (B489): an account is offered
    its own newest conversation, never another account's."""
    return _dirs(uid, project)


def _first_prompt(path):
    """The first thing the person typed, for the row: a line, cut short."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(400):
                line = fh.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "user" or d.get("isSidechain"):
                    continue
                for text in _texts((d.get("message") or {}).get("content")):
                    if text.strip():
                        return " ".join(text.split())[:120]
    except OSError:
        pass
    return ""


def _texts(content):
    """The text blocks of a message, whatever shape the content came in."""
    if isinstance(content, str):
        return [content]
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(str(b.get("text") or ""))
        elif isinstance(b, str):
            out.append(b)
    return out


def mine(uid, projects):
    """This account's sessions on these projects, newest first:
    [{project, id, at, bytes, first}]."""
    rows = []
    for project in projects:
        for d in _dirs(uid, project):
            try:
                files = [f for f in d.glob("*.jsonl") if f.is_file()]
            except OSError:
                continue
            for f in files:
                try:
                    st = f.stat()
                except OSError:
                    continue
                if st.st_size == 0:
                    continue
                rows.append({"project": project, "id": f.stem, "at": int(st.st_mtime),
                             "bytes": st.st_size, "first": _first_prompt(f)})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:MAX_LIST]


def _find(uid, project, sid):
    if not sid or "/" in sid or sid.startswith(".") or not all(c.isalnum() or c == "-" for c in sid):
        return None
    for d in _dirs(uid, project):
        f = d / f"{sid}.jsonl"
        if f.is_file():
            return f
    return None


def raw(uid, project, sid):
    """The transcript file itself, for a synced node resuming it (B613):
    its path, or None."""
    return _find(uid, project, sid)


def zone(name):
    """The zone a download's stamps are written in: the browser's, which
    the link carries, since that is the zone the dashboard beside it shows
    times in; the controller's own when the name is not a zone."""
    try:
        return ZoneInfo(name) if name and len(name) < 64 and "/" in name or name == "UTC" else None
    except (KeyError, ValueError, OSError):
        return None


def _when(d, tz=None):
    """The line's stamp: Claude Code writes UTC, and a person reads the log
    beside a dashboard that shows their own time."""
    t = str(d.get("timestamp") or "")
    try:
        at = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _tool_line(b):
    """One tool call as the person would read it: the command for a shell,
    the path for a read or an edit, the input otherwise."""
    name = str(b.get("name") or "tool")
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if name == "Bash":
        head = f"$ {inp.get('command', '')}"
        return head + (f"\n  ({inp['description']})" if inp.get("description") else "")
    for key in ("file_path", "path", "pattern", "url", "command", "prompt", "query"):
        if inp.get(key):
            return f"{name}: {inp[key]}"
    return f"{name}: " + json.dumps(inp, ensure_ascii=False)[:2000]


def _result_text(b):
    c = b.get("content")
    if isinstance(c, str):
        return c
    parts = []
    for x in c if isinstance(c, list) else []:
        if isinstance(x, dict) and x.get("type") == "text":
            parts.append(str(x.get("text") or ""))
        elif isinstance(x, dict) and x.get("type") == "image":
            parts.append("[an image]")
    return "\n".join(parts)


def render(uid, project, sid, tz=None, tail=0):
    """(text, filename) for one of the account's sessions, or (None, why).
    `tz` is the zone the stamps are written in (zone()), or the controller's.
    `tail`, when not 0, is how many bytes of a longer file are read, from its
    end: read from the start, a day-long conversation (900 MB on 19 Oct)
    outran `bb transcripts show`'s wait and printed nothing."""
    f = _find(uid, project, sid)
    if f is None:
        return None, "no such conversation of yours on this project"
    try:
        mtime = f.stat().st_mtime
    except OSError as e:
        return None, f"could not read it: {e}"
    started = datetime.fromtimestamp(mtime, timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    out = [f"Conversation on {project}, session {sid}, last written {started}",
           "What was said, every tool call with its command, and what each answered, as the "
           "transcript Claude Code wrote holds them. A line headed System is what BuilderBot "
           "or Claude Code put in front of Claude (a hook's verdict, a subagent's report, a "
           "summary after the context filled). Claude's private reasoning is not in it.", ""]
    total = 0
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            size = f.stat().st_size
            if tail and size > tail:
                fh.seek(size - tail)
                fh.readline()                          # to the next whole record
                out.append(f"[the newest {tail // (1024 * 1024)} MB of {size // (1024 * 1024)} MB]")
                out.append("")
            for line in fh:
                if total > MAX_OUT:
                    out.append("[cut here: the conversation is longer than this download carries]")
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("isSidechain"):
                    continue
                kind, msg = d.get("type"), d.get("message") or {}
                stamp = _when(d, tz)
                if kind == "user":
                    content = msg.get("content")
                    for b in content if isinstance(content, list) else []:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            text = _result_text(b)
                            out.append(("Result (error):" if b.get("is_error") else "Result:") + (("\n" + text) if text.strip() else " (nothing)"))
                            total += len(text)
                            out.append("")
                    texts = [t for t in _texts(content) if t.strip()]
                    if texts:
                        who = "System" if d.get("isMeta") or d.get("isCompactSummary") else "You"
                        out.append(f"{who} ({stamp}):" if stamp else f"{who}:")
                        out.extend(texts)
                        total += sum(len(t) for t in texts)
                        out.append("")
                elif kind == "assistant":
                    content = msg.get("content")
                    for b in content if isinstance(content, list) else []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and str(b.get("text") or "").strip():
                            out.append(f"Claude ({stamp}):" if stamp else "Claude:")
                            out.append(str(b["text"]))
                            total += len(b["text"])
                            out.append("")
                        elif b.get("type") == "tool_use":
                            out.append(_tool_line(b))
    except OSError as e:
        return None, f"could not read it: {e}"
    name = f"claude-{project}-{time.strftime('%Y%m%d-%H%M', time.localtime(mtime))}-{sid[:8]}.txt"
    return "\n".join(out).rstrip() + "\n", name


# ---- what the conversations did, against the house rules (R200 step 6) -----

AUDIT_DAYS = 7
_EXAMPLES = 3
# How much of one transcript the audit reads, from its end: a day-long
# conversation is hundreds of megabytes (the block rides on every turn), on
# the share, and reading all of it timed out the verb (B689). The newest
# part is what the number is about; a file cut is said as `partial`.
AUDIT_MAX_BYTES = 48 * 1024 * 1024


def _simple_commands(command):
    """The commands a shell line runs, as cmdmatch reads them, imported
    from scripts/lib the way rules.py does."""
    import os
    import sys
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import cmdmatch
    return cmdmatch.commands(command)


def audit(uid, project, judge, days=AUDIT_DAYS):
    """How this account's conversations on the project have kept to the
    rules that can be counted, over the last `days`: each Bash call a guard
    refuses (or would have, before it refused anything), by the guard's
    name with a few of the commands; how many calls asked `bb map` against
    how many searched the code (grep -r, rg, git grep, the Grep and Glob
    tools); and how many calls the guard did refuse. `judge(command, background)` is the
    guard's name for a shell line or "". A turn a person can read is
    counted, never Claude's reasoning; nothing here leaves the account."""
    since = time.time() - max(1, int(days)) * 86400
    out = {"days": int(days), "conversations": 0, "partial": 0, "bash": 0, "guards": {}, "examples": {},
           "map": 0, "grep": 0, "refused": 0}
    # A transcript writes one call into more than one record (a resumed or
    # summarized conversation carries its history again): counted once, by
    # the call's own id.
    seen = set()
    for d in _dirs(uid, project):
        try:
            files = [f for f in d.glob("*.jsonl") if f.is_file() and f.stat().st_mtime >= since]
        except OSError:
            continue
        for f in files:
            out["conversations"] += 1
            try:
                src = f.open("rb")
            except OSError:
                continue
            with src:
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                if size > AUDIT_MAX_BYTES:
                    src.seek(size - AUDIT_MAX_BYTES)
                    src.readline()                     # to the next whole record
                    out["partial"] += 1
                for raw in src:
                    line = raw.decode("utf-8", "replace")
                    # Most of a transcript is text and the briefing again;
                    # only a line with a tool in it is worth parsing.
                    if '"tool_use"' not in line and "Refused by" not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    content = ((rec.get("message") or {}).get("content")) if isinstance(rec, dict) else None
                    for b in content if isinstance(content, list) else []:
                        if not isinstance(b, dict):
                            continue
                        key = b.get("id") or b.get("tool_use_id")
                        if key:
                            if (b.get("type"), key) in seen:
                                continue
                            seen.add((b.get("type"), key))
                        if b.get("type") == "tool_result" and "Refused by" in _result_text(b)[:200]:
                            out["refused"] += 1
                        if b.get("type") != "tool_use":
                            continue
                        name = b.get("name")
                        if name in ("Grep", "Glob"):
                            out["grep"] += 1
                            continue
                        if name != "Bash":
                            continue
                        cmd = str((b.get("input") or {}).get("command") or "")
                        out["bash"] += 1
                        # Once a call each: a search of the code (grep -r,
                        # rg, git grep), not a grep filtering a pipe.
                        mapped = searched = False
                        for w in _simple_commands(cmd):
                            if w[:1] == ["bb"] and "map" in w[1:4]:
                                mapped = True
                            elif w[:1] in (["rg"], ["ag"]) or w[:2] == ["git", "grep"] or (
                                    w[:1] in (["grep"], ["egrep"]) and any(
                                        x == "--recursive" or (x.startswith("-") and not x.startswith("--")
                                                               and ("r" in x or "R" in x)) for x in w[1:])):
                                searched = True
                        out["map"] += mapped
                        out["grep"] += searched
                        hit = judge(cmd, bool((b.get("input") or {}).get("run_in_background")))
                        if hit:
                            out["guards"][hit] = out["guards"].get(hit, 0) + 1
                            ex = out["examples"].setdefault(hit, [])
                            if len(ex) < _EXAMPLES:
                                ex.append(cmd[:200])
    return out
