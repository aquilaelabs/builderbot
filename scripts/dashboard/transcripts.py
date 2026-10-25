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
out. A notebook's Sessions view offers each to resume, read, download,
delete, or make visible to every session on the project (shared(); the
operator, 22 Oct); otherwise only the account's own.
"""
import json
import re
import os
import threading
import time

import agents
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


# The conversations made visible to every session on their project:
# {project: {session id: {"uid": whose, "at": when}}}, in the state directory
# (a file absent is none made visible, so no migration brought it).
SHARED = None
write_json = None
_shared_lock = threading.Lock()
# A conversation written to this recently is a session still going: not
# deleted under it.
BUSY_S = 120


def configure(*, workspace, root_for, state=None, write_json=None):
    globals().update(WORKSPACE=Path(workspace), WORKTREES=Path(workspace) / ".worktrees",
                     root_for=root_for)
    if state is not None:
        globals().update(SHARED=Path(state) / "transcripts-shared.json", write_json=write_json)


def _shared_all():
    try:
        with open(SHARED) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def shared(project):
    """{session id: owner uid} for the conversations on the project made
    visible to every session there."""
    return {sid: str(v.get("uid") or "") for sid, v in (_shared_all().get(project) or {}).items()
            if isinstance(v, dict) and v.get("uid")}


def owner_of(uid, project, sid):
    """Whose conversation `sid` is, as `uid` may read it: its own, or one
    another account made visible on the project; None when neither."""
    if _find(uid, project, sid) is not None:
        return uid
    o = shared(project).get(sid or "")
    return o if o and _find(o, project, sid) is not None else None


def set_shared(uid, project, sid, on):
    """Make one of the account's own conversations visible to every session
    on the project, or private again. (payload, status)."""
    if _find(uid, project, sid) is None:
        return {"error": "no such conversation of yours"}, 404
    with _shared_lock:
        d = _shared_all()
        p = d.setdefault(project, {})
        if on:
            p[sid] = {"uid": uid, "at": int(time.time())}
        else:
            p.pop(sid, None)
            if not p:
                d.pop(project, None)
        write_json(SHARED, d)
    return {"ok": True, "shared": bool(on)}, 200


def delete(uid, project, sid):
    """Remove one of the account's own conversations, and its visibility
    with it. One still being written (a session going) is refused: its
    session would write it again. (payload, status)."""
    f = _find(uid, project, sid)
    if f is None:
        return {"error": "no such conversation of yours"}, 404
    try:
        if time.time() - f.stat().st_mtime < BUSY_S:
            return {"error": "a session is still writing this conversation: end it first"}, 409
        os.unlink(f)
    except OSError as e:
        return {"error": f"could not remove it: {e.strerror}"}, 500
    with _shared_lock:
        d = _shared_all()
        if sid in (d.get(project) or {}):
            d[project].pop(sid, None)
            if not d[project]:
                d.pop(project, None)
            write_json(SHARED, d)
    return {"ok": True}, 200


def visible(uid, project, name_of=lambda u: u):
    """Other accounts' conversations on the project made visible to every
    session there, newest first, each with whose it is."""
    rows = []
    for sid, o in shared(project).items():
        if o == uid:
            continue
        f = _find(o, project, sid)
        if f is None:
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        # ...each marked with its agent, as the account's own rows are (R95).
        rows.append({"project": project, "id": sid, "at": int(st.st_mtime), "bytes": st.st_size,
                     "first": _first_prompt(f), "by": name_of(o), "agent": agent_of(f)})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:MAX_LIST]


def _slug(path):
    return str(path).replace("/", "-")


# The coding agents beside Claude whose conversations are kept here too
# (R95 step 8): each session's own log, copied at the end of every turn by
# its Stop hook (bb-agent-hook) into an <agent>/ folder of the transcripts
# folder of the tree it works in, so the share and claudesync carry it
# exactly as they carry Claude Code's.
# Read from the agent table, so a new agent is not a second list to keep.
OTHER_AGENTS = tuple(a.id for a in agents.TABLE if a.id != "claude" and a.live)


def _dirs(uid, project):
    """Where this account's sessions on the project wrote: the project's
    own tree, the account's worktree of it, and each other agent's worktree
    of the account's (R95), each also under the name Claude Code itself
    gives a tree's folder (every character not a letter or a digit a dash),
    which is the one another agent's log is kept under."""
    base = Path(root_for(uid))
    out = []
    # ...and each slot's past the first (R143): u_x-2, u_x-codex-2.
    trees = [f"{uid}-{a}" for a in OTHER_AGENTS]
    trees += [f"{t}-{n}" for t in [uid, *trees] for n in range(2, agents.MAX_SLOTS + 1)]
    for p in (WORKSPACE / project, WORKTREES / project / uid,
              *(WORKTREES / project / t for t in trees)):
        for name in (_slug(p), re.sub(r"[^A-Za-z0-9]", "-", str(p))):
            if base / name not in out:
                out.append(base / name)
    return out


def _files(uid, project):
    """Every conversation of this account's on the project: (file, agent)."""
    for d in _dirs(uid, project):
        for sub, agent in ((d, "claude"), *((d / a, a) for a in OTHER_AGENTS)):
            try:
                found = [f for f in sub.glob("*.jsonl") if f.is_file()]
            except OSError:
                continue
            for f in found:
                yield f, agent


def agent_of(f):
    """The coding agent a conversation's file is with: its folder says."""
    return f.parent.name if f.parent.name in OTHER_AGENTS else "claude"


def dirs(uid, project):
    """The same, for the server's resume offer (B489): an account is offered
    its own newest conversation, never another account's."""
    return _dirs(uid, project)


def _first_prompt(path):
    """The first thing the person typed, for the row: a line, cut short."""
    if agent_of(path) != "claude":
        t = next((t for t in _agent_turns(path, agent_of(path), None, 0, first=True)[0] if t["who"] == "you"), None)
        return " ".join(t["text"].split())[:120] if t else ""
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
        on = shared(project) if SHARED is not None else {}
        for f, agent in _files(uid, project):
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_size == 0:
                continue
            # Which coding agent's (R95): Claude Code's at the top of the
            # folder, another agent's in its own folder beside them. Only
            # ever this account's own, whichever agent it used.
            rows.append({"project": project, "id": f.stem, "at": int(st.st_mtime),
                         "bytes": st.st_size, "first": _first_prompt(f),
                         "shared": f.stem in on, "agent": agent})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows[:MAX_LIST]


def _find(uid, project, sid):
    if not sid or "/" in sid or sid.startswith(".") or not all(c.isalnum() or c == "-" for c in sid):
        return None
    for d in _dirs(uid, project):
        for sub in (d, *(d / a for a in OTHER_AGENTS)):
            f = sub / f"{sid}.jsonl"
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
    if agent_of(f) != "claude":
        return _agent_render(f, agent_of(f), project, sid, tz, tail)
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


# The reader's cap on one tool's answer: the folded line is a glance, and the
# download holds the whole of it.
TURN_RESULT_MAX = 4000


def turns(uid, project, sid, tz=None, tail=0):
    """(payload, status) for the dashboard's reader (R83): the conversation as
    turns, {who: "you" | "claude" | "system", at, text, tools: [{call, result,
    error}]}, each tool's answer attached to the call it answers, from the
    same records render() writes the text download from."""
    f = _find(uid, project, sid)
    if f is None:
        return {"error": "no such conversation of yours on this project"}, 404
    if agent_of(f) != "claude":
        got, partial = _agent_turns(f, agent_of(f), tz, tail)
        a = agent_of(f)
        return {"project": project, "id": sid, "partial": partial, "turns": got, "agent": a,
                "agent_name": (agents.get(a).name if agents.get(a) else a)}, 200
    out, calls, total, partial = [], {}, 0, False
    try:
        size = f.stat().st_size
        with open(f, encoding="utf-8", errors="replace") as fh:
            if tail and size > tail:
                fh.seek(size - tail)
                fh.readline()
                partial = True
            for line in fh:
                if total > MAX_OUT:
                    partial = True
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("isSidechain"):
                    continue
                kind, msg = d.get("type"), d.get("message") or {}
                content = msg.get("content")
                stamp = _when(d, tz)
                if kind == "user":
                    for b in content if isinstance(content, list) else []:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                            text = _result_text(b)
                            calls[b["tool_use_id"]].update(result=text[:TURN_RESULT_MAX], cut=len(text) > TURN_RESULT_MAX,
                                                           error=bool(b.get("is_error")))
                            total += min(len(text), TURN_RESULT_MAX)
                    texts = [t for t in _texts(content) if t.strip()]
                    if texts:
                        who = "system" if d.get("isMeta") or d.get("isCompactSummary") else "you"
                        out.append({"who": who, "at": stamp, "text": "\n".join(texts), "tools": []})
                        total += sum(len(t) for t in texts)
                elif kind == "assistant":
                    for b in content if isinstance(content, list) else []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and str(b.get("text") or "").strip():
                            out.append({"who": "claude", "at": stamp, "text": str(b["text"]), "tools": []})
                            total += len(b["text"])
                        elif b.get("type") == "tool_use":
                            if not out or out[-1]["who"] != "claude":
                                out.append({"who": "claude", "at": stamp, "text": "", "tools": []})
                            call = {"call": _tool_line(b), "result": "", "cut": False, "error": False}
                            out[-1]["tools"].append(call)
                            calls[str(b.get("id") or "")] = call
    except OSError as e:
        return {"error": f"could not read it: {e}"}, 500
    return {"project": project, "id": sid, "partial": partial, "turns": out}, 200


# ---- another agent's conversation (R95 step 8) -------------------------------
# Codex CLI writes a rollout, a line per record ({timestamp, type, payload}:
# a response_item a message, a function call or its output); Copilot CLI an
# events log ({type, data, timestamp}: user.message, assistant.message,
# tool.execution_start and _complete); Grok Build its updates.jsonl, a line
# per ACP session update (user_message_chunk and agent_message_chunk, a
# message streamed in pieces; tool_call and tool_call_update, by toolCallId).
# Each read here into the same turns Claude Code's are, the reader's and the
# download's. Read against the shapes Codex CLI 0.163.0 and Copilot CLI
# 1.0.102 write and Grok Build's user guide names (25 Oct); a record of any
# other shape is passed over, never a failure.

# What Codex puts in front of a conversation as the person's words, which
# the person did not type.
_CODEX_PREAMBLE = ("<environment_context>", "<user_instructions>", "<permissions", "<developer")


def _texts_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("text")) \
        if isinstance(content, list) else ""


def _acp_text(c):
    """The words in an ACP content block, or a list of them, a tool's
    content items ({type: content, content: {type: text, text}}) among them."""
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return str(c.get("text") or "") or _acp_text(c.get("content"))
    if isinstance(c, list):
        return "\n".join(t for t in (_acp_text(x) for x in c) if t)
    return ""


def _by_event(lines):
    """Grok Build's updates in the order it raised them, by the number its
    event ids end in: a turn's first chunk can be written after the rest.
    A line with no id keeps the place of the one before it."""
    keyed, last = [], 0
    for i, line in enumerate(lines):
        m = re.search(r'"eventId":\s*"[^"]*-(\d+)"', line)
        last = int(m.group(1)) if m else last
        keyed.append((last, i, line))
    return [line for _, _, line in sorted(keyed)]


def _args(a):
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return a
    if isinstance(a, dict):
        cmd = a.get("command")
        if isinstance(cmd, list):
            cmd = cmd[2] if len(cmd) == 3 and cmd[1] in ("-lc", "-c") else " ".join(map(str, cmd))
        if cmd:
            return f"$ {cmd}"
        for k in ("path", "file_path", "pattern", "query", "url", "input"):
            if a.get(k):
                return str(a[k])[:2000]
        return json.dumps(a, ensure_ascii=False)[:2000]
    return str(a or "")


def _agent_turns(f, agent, tz, tail, first=False):
    """([turn], partial) for another agent's conversation, in turns()'s
    shape: who you, claude (the agent, whichever it is) or system."""
    out, calls, partial, total = [], {}, False, 0

    def say(who, text, stamp):
        out.append({"who": who, "at": stamp, "text": text, "tools": []})

    def tool(call, key, stamp):
        if not out or out[-1]["who"] != "claude":
            say("claude", "", stamp)
        c = {"call": call, "result": "", "cut": False, "error": False}
        out[-1]["tools"].append(c)
        if key:
            calls[key] = c

    def result(key, text):
        c = calls.get(key)
        if c is not None:
            text = str(text or "")
            c.update(result=text[:TURN_RESULT_MAX], cut=len(text) > TURN_RESULT_MAX)
    try:
        size = f.stat().st_size
        with open(f, encoding="utf-8", errors="replace") as fh:
            if tail and size > tail:
                fh.seek(size - tail)
                fh.readline()
                partial = True
            for line in (_by_event(fh) if agent == "grok" else fh):
                # The first words: read until the person's turn has ended,
                # which for Grok is a message streamed in chunks.
                if total > MAX_OUT or (first and any(t["who"] == "you" for t in out) and out[-1]["who"] != "you"):
                    partial = partial or total > MAX_OUT
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                stamp = _when(d, tz)
                if agent == "grok":
                    u = d.get("update") if isinstance(d.get("update"), dict) \
                        else (d.get("params") or {}).get("update") if isinstance(d.get("params"), dict) else d
                    if not isinstance(u, dict):
                        continue
                    t = str(u.get("sessionUpdate") or "")
                    if t in ("user_message_chunk", "agent_message_chunk"):
                        text = _acp_text(u.get("content"))
                        if not text:
                            continue
                        who = "you" if t == "user_message_chunk" else "claude"
                        # One message streamed in pieces is one turn.
                        if out and out[-1]["who"] == who and not out[-1]["tools"]:
                            out[-1]["text"] += text
                        else:
                            say(who, text, stamp)
                        total += len(text)
                    elif t == "tool_call":
                        tool(f"{u.get('title') or u.get('kind') or 'tool'}: {_args(u.get('rawInput'))}",
                             str(u.get("toolCallId") or ""), stamp)
                    elif t == "tool_call_update" and u.get("status") in ("completed", "failed"):
                        r = u.get("rawOutput")
                        result(str(u.get("toolCallId") or ""),
                               _acp_text(u.get("content")) if r is None else r if isinstance(r, str)
                               else json.dumps(r, ensure_ascii=False)[:TURN_RESULT_MAX])
                elif agent == "codex":
                    p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
                    if d.get("type") != "response_item":
                        continue
                    t = p.get("type")
                    if t == "message":
                        text = _texts_of(p.get("content"))
                        if not text.strip():
                            continue
                        if p.get("role") == "user" and not text.lstrip().startswith(_CODEX_PREAMBLE):
                            say("you", text, stamp)
                        elif p.get("role") == "assistant":
                            say("claude", text, stamp)
                        total += len(text)
                    elif t in ("function_call", "custom_tool_call", "local_shell_call"):
                        tool(f"{p.get('name') or 'shell'}: {_args(p.get('arguments') or p.get('input') or p.get('action'))}",
                             str(p.get("call_id") or ""), stamp)
                    elif t in ("function_call_output", "custom_tool_call_output"):
                        o = p.get("output")
                        result(str(p.get("call_id") or ""), o.get("output") if isinstance(o, dict) else o)
                else:
                    data = d.get("data") if isinstance(d.get("data"), dict) else {}
                    t = str(d.get("type") or "")
                    if t == "user.message":
                        text = _texts_of(data.get("content") or data.get("message") or "")
                        if text.strip():
                            say("you", text, stamp)
                            total += len(text)
                    elif t == "assistant.message":
                        text = _texts_of(data.get("content") or data.get("message") or "")
                        if text.strip():
                            say("claude", text, stamp)
                            total += len(text)
                    elif t == "tool.execution_start":
                        tool(f"{data.get('toolName') or 'tool'}: {_args(data.get('arguments') or data.get('args'))}",
                             str(data.get("toolCallId") or data.get("id") or ""), stamp)
                    elif t == "tool.execution_complete":
                        r = data.get("result")
                        result(str(data.get("toolCallId") or data.get("id") or ""),
                               r.get("content") if isinstance(r, dict) else r)
    except OSError:
        return [], False
    return out, partial


def _agent_render(f, agent, project, sid, tz, tail):
    """render()'s (text, filename) for another agent's conversation."""
    name = {"codex": "ChatGPT", "copilot": "Copilot", "grok": "Grok"}.get(agent, agent)
    try:
        mtime = f.stat().st_mtime
    except OSError as e:
        return None, f"could not read it: {e}"
    started = datetime.fromtimestamp(mtime, timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    got, partial = _agent_turns(f, agent, tz, tail)
    out = [f"Conversation on {project} with {name}, session {sid}, last written {started}",
           f"What was said, every tool call with its command, and what each answered, as the log "
           f"{name}'s program wrote them.", ""]
    if partial:
        out += ["[the newest part of a longer conversation]", ""]
    for t in got:
        who = {"you": "You", "claude": name, "system": "System"}.get(t["who"], t["who"])
        if t["text"]:
            out += [f"{who} ({t['at']}):" if t["at"] else f"{who}:", t["text"], ""]
        for c in t["tools"]:
            out += [c["call"], "Result:" + (("\n" + c["result"]) if c["result"].strip() else " (nothing)"), ""]
    fname = f"{agent}-{project}-{time.strftime('%Y%m%d-%H%M', time.localtime(mtime))}-{sid[:8]}.txt"
    return "\n".join(out).rstrip() + "\n", fname


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
