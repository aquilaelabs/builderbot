"""What the page may type into a terminal, and how it types it.

Every command the UI can run and every key it can press is an entry in a
table here, and the page posts the entry's name and nothing else. The
operator's own command lists are the one stored kind, typed into a terminal
the same way and never run in the server's process; the pins are which of
the Linux and git commands sit at the top of the Commands panel.

Out of server.py whole (R77): the tables, the pins and the lists, the
command cards' part of the status poll, and the three ways the page types
into a session (a key, a macro's lines, a message into Claude's input box).
The server holds the routes, and whose a session is.
"""
import json
import re
import shlex
from pathlib import Path

import agents

# Every command the UI can run, by name. The UI posts a key from this table and
# nothing else: no argument passthrough, no shell. A dashboard that accepted a
# command string would be a remote shell with extra steps, and there is already
# a real terminal one port over for anything not listed here.
#
# The bb commands a page sends from where it is about (the operator, 17 Oct:
# no card of bb commands, since every one of them has its page now: status
# on Home, the emulator on its page, the logs in Settings, the sign-in on
# its own). Typed into the real terminal rather than captured, so one that
# follows is ended with Ctrl-C exactly as if it had been typed.
MACROS = {
    # The last test run's output, followed while it is still running: the
    # Tests view's button sends this into the project's shell. A row used
    # to carry a tail of the job's log and redraw for every line of it.
    "tests-log":        ["bb", "tests", "log", "-f"],
}

# The Linux and git lists. Strings typed into the shell as-is, not
# argv lists like MACROS, because half of these are pipelines and shlex.join
# would quote the pipe into a literal. Still a table, for the same reason as
# MACROS: send-keys will happily type anything, so the page only ever names
# an entry. The label the card shows IS the command: these are buttons for
# things an operator would type, so hiding the text would only add mystery.
LINUX_MACROS = {
    "lx-clear": "clear",
    "lx-up":    "cd ..",
    "lx-ls":    "ls -lah",
    "lx-du":    "du -sh * | sort -rh | head -20",
    # Here and home: a shell is a node's, where /config (the controller's)
    # is not (the operator, 17 Oct).
    "lx-df":    "df -h . ~",
    "lx-free":  "free -h",
    "lx-ps":    "ps aux --sort=-%mem | head -15",
    "lx-ports": "lsof -nP -iTCP -sTCP:LISTEN",
}
GIT_MACROS = {
    "git-status": "git status",
    "git-log":    "git log --oneline --graph --decorate -15",
    "git-diff":   "git diff",
    "git-stat":   "git diff --stat",
    "git-branch": "git branch -av",
    "git-stash":  "git stash list",
    "git-fetch":  "git fetch --all --prune",
    "git-pull":   "git pull",
}
# No gh: a node carries none (the operator, 17 Oct), so its four buttons
# could only fail; a push is bb git push's, under the project's policy.
SHELL_MACROS = {**LINUX_MACROS, **GIT_MACROS}

# Keys an Android keyboard has no way to send. Names on the left are what the
# page posts; values are tmux key names. A table rather than passthrough for the
# same reason as MACROS: `send-keys` will happily type anything it is given.
TMUX_KEYS = {
    "escape": "Escape", "tab": "Tab", "enter": "Enter", "bspace": "BSpace",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pgup": "PPage", "pgdn": "NPage",
    "ctrl-c": "C-c", "ctrl-d": "C-d", "ctrl-z": "C-z", "ctrl-l": "C-l",
    "ctrl-r": "C-r", "ctrl-a": "C-a", "ctrl-e": "C-e", "ctrl-u": "C-u",
    "ctrl-k": "C-k", "ctrl-w": "C-w",
}

# Characters that are buried behind two taps on a phone keyboard. Sent with
# send-keys -l so tmux treats them as literal text, never as key names.
TMUX_LITERALS = {
    "pipe": "|", "tilde": "~", "slash": "/", "backslash": "\\", "dash": "-",
    "under": "_", "star": "*", "amp": "&", "dollar": "$", "caret": "^",
    "lt": "<", "gt": ">", "brace-l": "{", "brace-r": "}",
}


# What the stored half and the typing need from the server, set by
# configure(): how a state file is written, the one lock every
# read-edit-write of the server's state files takes, how a command is run,
# this container's tmux sessions and a name's session without its account
# prefix (tmux_base), and a node's session tmux through its agent.
write_json = None
lock = None
run = None
tmux_sessions = None
tmux_base = None
session_tmux = None

# Which commands the operator keeps at the top of the card. Stored beside the
# other state for the same reason the tab strip is: this is one machine with one
# operator, and a pin made on the desktop should be there on the phone.
PINS_FILE = None             # <state>/pinned-commands.json, set by configure()

# The operator's own command lists. Stored, never executed here: pressing one
# types its lines into a terminal exactly as `bb` macros do. That is why this is
# not the "arbitrary command string" the API refuses everywhere else: the text
# goes to a tty the same authenticated operator is already sitting at, and they
# could have typed it themselves. Nothing runs in the server's own process.
CUSTOM_FILE = None           # <state>/custom-commands.json, set by configure()
CUSTOM_MAX = 40                 # macros
CUSTOM_TITLE_MAX = 60           # characters
CUSTOM_LINES_MAX = 20           # lines per macro
CUSTOM_LINE_MAX = 500           # characters per line


def configure(*, state, write_json, lock, run, tmux_sessions, tmux_base, session_tmux):
    globals().update(write_json=write_json, lock=lock, run=run, tmux_sessions=tmux_sessions,
                     tmux_base=tmux_base, session_tmux=session_tmux,
                     PINS_FILE=Path(state) / "pinned-commands.json",
                     CUSTOM_FILE=Path(state) / "custom-commands.json")


def load_pins():
    try:
        v = json.loads(PINS_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(v, list):
        return []
    return sorted({x for x in v if isinstance(x, str) and x in SHELL_MACROS})


def load_custom():
    """The stored custom macros, validated on the way out.

    Read back through the same checks the writer applies, so a hand-edited file
    cannot put something in the page that the page could not have saved.
    """
    try:
        v = json.loads(CUSTOM_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(v, list):
        return []
    out, seen = [], set()
    for m in v[:CUSTOM_MAX]:
        if not isinstance(m, dict):
            continue
        mid, title, lines = m.get("id"), m.get("title"), m.get("lines")
        if not isinstance(mid, str) or not re.fullmatch(r"c[0-9]{1,6}", mid) or mid in seen:
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(lines, list) or not lines:
            continue
        lines = [l for l in lines[:CUSTOM_LINES_MAX]
                 if isinstance(l, str) and l.strip() and len(l) <= CUSTOM_LINE_MAX]
        if not lines:
            continue
        seen.add(mid)
        out.append({"id": mid, "title": title.strip()[:CUSTOM_TITLE_MAX], "lines": lines})
    return out


def save_custom(macros):
    write_json(CUSTOM_FILE, macros)


def clean_lines(body):
    """Split an edit box into command lines.

    Blank lines and comment-only lines are dropped rather than typed: pressing
    Enter on an empty line is noise in a terminal, and a stored macro that
    silently includes them looks like it did something wrong.
    """
    lines = []
    for raw in (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        # Control characters would go through send-keys -l as literal bytes and
        # could move the cursor or clear the screen mid-macro.
        line = "".join(ch for ch in line if ch == "\t" or ord(ch) >= 32)
        if line.strip():
            lines.append(line[:CUSTOM_LINE_MAX])
    return lines[:CUSTOM_LINES_MAX]


def save_pins(names):
    write_json(PINS_FILE, sorted(set(names)))


def cards():
    """The Commands panel's part of the status poll: the Linux and git
    lists, which of them are pinned, and the operator's own lists."""
    return {
        # From their tables for the same reason as MACROS. `need` is what
        # the button requires of the active shell's directory; the page
        # ghosts accordingly.
        "linux": [{"name": k, "label": v} for k, v in LINUX_MACROS.items()],
        "gitcmds": [{"name": k, "label": v, "need": "git"} for k, v in GIT_MACROS.items()],
        "pinned": load_pins(),
        "custom": load_custom(),
    }


# ---- the verbs, one call each from the dashboard ------------------------------

def _answer(r):
    return r, (400 if r.get("error") else 200)


def pin(name, on):
    """Pin or unpin a command. Names are keys from the Linux and git lists,
    so the file can never grow an entry the panel would not know what to do
    with. (payload, status)."""
    if name not in SHELL_MACROS:
        return {"error": f"unknown command: {name}"}, 400
    with lock:
        names = set(load_pins())
        names.add(name) if on else names.discard(name)
        try:
            save_pins(names)
        except OSError as e:
            return {"error": f"could not save: {e}"}, 500
    return {"pinned": sorted(names)}, 200


def custom_edit(action, req):
    """Save or delete one of the operator's own command lists. Ids are
    minted here rather than accepted from the page, so the file cannot grow
    a key that came from a request, and every stored list is addressable by
    something this server chose. (payload, status)."""
    with lock:                   # read, edit, write: one at a time
        macros = load_custom()
        if action == "delete":
            mid = req.get("id")
            macros = [m for m in macros if m["id"] != mid]
        elif action == "save":
            title = (req.get("title") or "").strip()[:CUSTOM_TITLE_MAX]
            lines = clean_lines(req.get("body"))
            if not title:
                return {"error": "a title is required"}, 400
            if not lines:
                return {"error": "no commands to run"}, 400
            mid = req.get("id")
            if mid and any(m["id"] == mid for m in macros):
                macros = [{"id": m["id"], "title": title, "lines": lines}
                          if m["id"] == mid else m for m in macros]
            else:
                if len(macros) >= CUSTOM_MAX:
                    return {"error": f"at most {CUSTOM_MAX} custom commands"}, 400
                used = {int(m["id"][1:]) for m in macros}
                mid = "c" + str(max(used, default=0) + 1)
                macros.append({"id": mid, "title": title, "lines": lines})
        else:
            return {"error": "unknown action"}, 400
        try:
            save_custom(macros)
        except OSError as e:
            return {"error": f"could not save: {e}"}, 500
        return {"custom": load_custom()}, 200


def press(session, key, on_node):
    """One key from the tables pressed in a session, or a page up or down,
    once the server has said the session is the caller's: on a node through
    its agent (`on_node`, its session row), here through tmux. (payload,
    status)."""
    if on_node:
        # The same table, queued for the node's agent (roadmap #24); the
        # paging decision is the agent's, on the pane it can see.
        real = on_node["node_name"]
        if key in ("pgup", "pgdn"):
            op = {"session": real, "page": "up" if key == "pgup" else "down"}
        elif key in TMUX_KEYS:
            op = {"session": real, "argv": ["send-keys", "-t", real, TMUX_KEYS[key]]}
        elif key in TMUX_LITERALS:
            op = {"session": real, "argv": ["send-keys", "-t", real, "-l", "--",
                                            TMUX_LITERALS[key]]}
        else:
            return {"error": f"unknown key: {key}"}, 400
        return _answer(session_tmux(on_node["node_id"], [op]))
    # Only sessions that currently exist, never an arbitrary -t argument.
    if session not in {s["name"] for s in tmux_sessions()}:
        return {"error": f"no such session: {session}"}, 400
    # Paging is how a finger scrolls: a drag reaches nothing (the terminal
    # sits on tmux's alternate screen, and xterm.js turns only wheel events
    # into anything tmux sees), so PgUp at a prompt enters copy mode a page
    # up and PgDn pages back, copy mode ending by itself at the bottom
    # (-e). The tmux config binds a real keyboard's PgUp the same way, but
    # send-keys goes straight to the pane, past the key table that binding
    # lives in, so the same decision is made here, as commands. Inside a
    # full-screen program (less, vim) the key is the program's.
    if key in ("pgup", "pgdn"):
        flags = run(["tmux", "display-message", "-p", "-t", session,
                     "#{alternate_on} #{pane_in_mode}"], timeout=10)
        alt, mode = (flags["out"].split() + ["0", "0"])[:2]
        if key == "pgup":
            cmd = ["send-keys", "-t", session, "PPage"] if alt == "1" \
                else ["copy-mode", "-eu", "-t", session]
        else:
            cmd = ["send-keys", "-t", session, "-X", "page-down"] if mode == "1" \
                else ["send-keys", "-t", session, "NPage"]
        return run(["tmux", *cmd], timeout=10), 200
    # Any other key is meant for the program, so a pane scrolled back into
    # copy mode leaves it first: there an arrow moved tmux's cursor over the
    # history and a letter did nothing, and the program never heard either
    # (the operator, 23 Oct, at Codex's approval list).
    if key in TMUX_KEYS or key in TMUX_LITERALS:
        mode = run(["tmux", "display-message", "-p", "-t", session, "#{pane_in_mode}"], timeout=10)
        if mode["out"].strip() == "1":
            run(["tmux", "send-keys", "-t", session, "-X", "cancel"], timeout=10)
    if key in TMUX_KEYS:
        return run(["tmux", "send-keys", "-t", session, TMUX_KEYS[key]], timeout=10), 200
    if key in TMUX_LITERALS:
        return run(["tmux", "send-keys", "-t", session, "-l", "--",
                    TMUX_LITERALS[key]], timeout=10), 200
    return {"error": f"unknown key: {key}"}, 400


def say(want, text, on_node):
    """Type a message into a CLAUDE session and press Enter, once the server
    has said it is this account's own conversation and that it is running.
    Control characters are stripped, so a message cannot move the cursor,
    clear the screen, or carry an escape sequence: what is left is text into
    Claude's own input box, which is what the person would have typed if
    they had a terminal. (payload, status)."""
    text = "".join(ch for ch in str(text) if ch == "\t" or ord(ch) >= 32)[:CUSTOM_LINE_MAX]
    if not text.strip():
        return {"error": "nothing to say"}, 400
    if on_node:
        # Into the conversation on the node, through its agent: the same
        # two keystrokes, the same narrowing (roadmap #24).
        real = on_node["node_name"]
        return _answer(session_tmux(on_node["node_id"], [
            {"session": real, "argv": ["send-keys", "-t", real, "-l", "--", text]},
            {"session": real, "argv": ["send-keys", "-t", real, "Enter"]}]))
    r = run(["tmux", "send-keys", "-t", want, "-l", "--", text], timeout=10)
    if r["code"] != 0:
        return {"error": r["out"].strip()[:200] or "send failed"}, 500
    run(["tmux", "send-keys", "-t", want, "Enter"], timeout=10)
    return {"ok": True}, 200


def send(session, name, cid, on_node):
    """Type a macro's command lines into a shell session and press Enter,
    once the server has said the session is the caller's. Two kinds, and
    neither is a command string from the request: a name from the fixed
    tables, or the id of one of the operator's own lists. What lands in the
    terminal is exactly what they would have typed, in a tty they are
    already sitting at. (payload, status)."""
    if cid:
        m = next((x for x in load_custom() if x["id"] == cid), None)
        if not m:
            return {"error": f"unknown custom command: {cid}"}, 400
        lines = m["lines"]
    elif name in MACROS:
        lines = [shlex.join(MACROS[name])]
    elif name in SHELL_MACROS:
        lines = [SHELL_MACROS[name]]
    else:
        return {"error": f"unknown macro: {name}"}, 400
    if session not in {s["name"] for s in tmux_sessions()} and not on_node:
        return {"error": f"no such session: {session}"}, 400
    # Never into an agent's session: that would not run the command, it
    # would submit it as a prompt.
    agent, _stem = agents.of_session(tmux_base(session))
    if agent:
        return {"error": f"refusing to type into a {agent.name} session"}, 400
    sent = lines[0] if len(lines) == 1 else f"{len(lines)} commands"
    if on_node:
        # A shell on the node: the same lines, through its agent.
        real = on_node["node_name"]
        ops = [{"session": real, "argv": ["send-keys", "-t", real, "C-e", "C-u"]}]
        for line in lines:
            ops.append({"session": real, "argv": ["send-keys", "-t", real, "-l", "--", line]})
            ops.append({"session": real, "argv": ["send-keys", "-t", real, "Enter"]})
        return _answer(session_tmux(on_node["node_id"], ops) | {"sent": sent})
    # Clear whatever was half-typed at the prompt first, or the command
    # arrives glued to the end of it. End-of-line then kill-line, which is
    # readline editing and not a signal: Ctrl-C would also interrupt
    # whatever is running in there, which is not what pressing a button
    # labeled `bb status` should be able to do.
    run(["tmux", "send-keys", "-t", session, "C-e", "C-u"], timeout=10)
    # Typed one after another without waiting. That is what happens when a
    # person types ahead too: the tty buffers the input and the shell reads
    # each line when it is ready for one.
    for line in lines:
        # `--`: a line that starts with a dash ("-la", "--version") is
        # otherwise read by tmux as flags and refused as "unknown flag",
        # after the prompt has already been cleared: a macro that just
        # silently did nothing.
        r = run(["tmux", "send-keys", "-t", session, "-l", "--", line], timeout=10)
        if r["code"] != 0:
            return r, 200
        r = run(["tmux", "send-keys", "-t", session, "Enter"], timeout=10)
        if r["code"] != 0:
            return r, 200
    return r | {"sent": sent}, 200
