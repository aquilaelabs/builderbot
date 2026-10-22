"""Ending Claude sessions nobody has used for a while: on this container, and
on every node, by the node itself.

One controller-scoped setting: minutes of inactivity after which a Claude
session is ended, 0 for never. A session's activity is tmux's own
`session_activity` (the last time anything was typed into it or written by
it), so a session that Claude is still working in is not idle, and one
sitting at a prompt with nobody attached for an hour is.

Two enforcers, one rule. This container ends its own sessions from a thread
here. A node ends its own: the value rides the hello reply (nodes.py reads
it through `idle_minutes`, injected by server.py), the agent keeps it in
node.json and checks its tmux on every loop, so the rule holds while the
controller is down, which is the case the operator asked for: a node's
sessions outlive a controller restart on purpose, and the one thing that
must not outlive it is the rule about when they end.

Only Claude sessions. A shell is cheap and is somebody's; a Claude session
is the thing that costs, and the thing that was found still running the
morning after.
"""
import os
import subprocess
import sys
import threading
import time

import agents

_state = None
_write_json = None
_changed = lambda: None          # noqa: E731  (the server nudges the nodes)
_log = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731  (the server's log is its stderr)

DEFAULT_MINUTES = 0
# Seconds per "minute". The suite sets it to 1 so a rule of one minute can be
# seen to act in a second; nothing else ever changes it.
UNIT = float(os.environ.get("BUILDERBOT_IDLE_UNIT", "60"))


def configure(*, state, write_json, changed=None, log=None):
    global _state, _write_json, _changed, _log
    _state = state
    _write_json = write_json
    if changed:
        _changed = changed
    if log:
        _log = log


def _file():
    return os.path.join(str(_state), "idle.json")


def minutes():
    """The rule: minutes idle before a Claude session is ended; 0 = never."""
    try:
        import json
        with open(_file()) as f:
            n = int(json.load(f).get("minutes", DEFAULT_MINUTES))
        return max(0, n)
    except (OSError, ValueError, TypeError):
        return DEFAULT_MINUTES


def set_minutes(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return {"error": "minutes must be a number"}
    if n < 0 or n > 100000:
        return {"error": "minutes: 0 for never, or up to 100000"}
    _write_json(_file(), {"minutes": n})
    _changed()
    return {"ok": True, "minutes": n}


def payload():
    return {"minutes": minutes()}


def is_claude(name):
    """An agent's session by name: claude-<project>, or an account's
    u_xxxx~claude-<project>, for every live agent in the table (R95), so
    the idle rule ends a Codex session as it ends a Claude one."""
    return agents.is_session(name.split("~", 1)[1] if "~" in name else name)


def idle_sessions(list_output, limit_min, now=None):
    """The Claude sessions past the rule, from tmux's
    `#{session_name}\\t#{session_activity}` lines. Pure, for the tests and
    for the agent, which carries a copy of this logic rather than importing
    a module it does not have."""
    if limit_min <= 0:
        return []
    now = time.time() if now is None else now
    out = []
    for line in (list_output or "").splitlines():
        if "\t" not in line:
            continue
        name, act = line.split("\t", 1)
        try:
            last = float(act.strip())
        except ValueError:
            continue
        if is_claude(name) and now - last > limit_min * UNIT:
            out.append(name)
    return out


def reap_once():
    """End this container's idle Claude sessions. Returns the names ended."""
    limit = minutes()
    if limit <= 0:
        return []
    try:
        p = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_activity}"],
                           capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if p.returncode != 0:
        return []                     # no server: nothing to end
    ended = []
    for name in idle_sessions(p.stdout, limit):
        r = subprocess.run(["tmux", "kill-session", "-t", "=" + name],
                           capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0:
            ended.append(name)
            _log(f"idle: ended {name} after no activity for {limit} minute(s), the Settings page's rule")
    return ended


def _loop():
    while True:
        time.sleep(max(1.0, UNIT))
        try:
            reap_once()
        except Exception as e:        # noqa: BLE001  (a reaper must not die)
            _log(f"idle: {e}")


def start():
    threading.Thread(target=_loop, name="idle", daemon=True).start()
