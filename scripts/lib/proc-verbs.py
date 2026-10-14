#!/usr/bin/env python3
"""bb proc [PATTERN] | stop PATTERN [--grace S] | wait PATTERN [--timeout S]

This account's processes whose command line holds PATTERN, read from /proc
and never the ones this call runs under: its own shell, the tool call that
started it and everything above them. That is the whole difference from
`pgrep -f` and `pkill -f` run from a tool call, which match the call's own
shell because the pattern is on its command line (B736: on Turing Lens, 14
Oct, a cleanup step killed its own run that way, and a wait loop on
`! pgrep -f` could never end).

  bb proc PATTERN              pid, how long it has run, and its command line
  bb proc stop PATTERN         SIGTERM to each, SIGKILL to what is left after
                               --grace seconds (3), and what it ended
  bb proc wait PATTERN         returns once none is left, or exits 1 after
                               --timeout seconds (600), saying what is left

A pattern is plain text, matched as a substring of the command line; an
empty one lists every process of this account's that is not this call.
"""
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tidy  # noqa: E402  (proc_info, ancestors: the same reading of /proc)

PROC = os.environ.get("BB_PROC_ROOT", tidy.PROC)


def started(pid):
    """Seconds since the process started, or None."""
    try:
        with open(os.path.join(PROC, str(pid), "stat"), encoding="utf-8") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open(os.path.join(PROC, "uptime"), encoding="utf-8") as f:
            up = float(f.read().split()[0])
        return max(0, int(up - ticks / os.sysconf("SC_CLK_TCK")))
    except (OSError, ValueError, IndexError):
        return None


def matching(pattern, spare=None):
    """[(pid, args)] of this account's processes whose command line holds
    pattern, never this call's ancestry nor a bb proc run itself."""
    uid = os.getuid()
    spare = tidy.ancestors(root=PROC) if spare is None else spare
    out = []
    for pid in os.listdir(PROC):
        if not pid.isdigit() or int(pid) in spare:
            continue
        info = tidy.proc_info(pid, PROC)
        if not info or info[2] != uid:
            continue
        args = info[1] or info[0]
        # Another bb proc, which carries the pattern as its argument the way
        # a pgrep would: never a match, whichever call it belongs to.
        if "proc-verbs.py" in args:
            continue
        if pattern in args:
            out.append((int(pid), args))
    return out


def ago(s):
    if s is None:
        return "?"
    return f"{s}s" if s < 120 else f"{s // 60}m" if s < 7200 else f"{s // 3600}h"


def say(rows):
    for pid, args in rows:
        print(f"{pid:>7}  {ago(started(pid)):>5}  {args[:200]}")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie is gone for every purpose here: it holds nothing but its slot.
    try:
        with open(os.path.join(PROC, str(pid), "stat"), encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def flag(argv, name, default):
    if name in argv:
        i = argv.index(name)
        try:
            v = float(argv[i + 1])
        except (IndexError, ValueError):
            sys.exit(f"[builderbot] ERROR: {name} takes a number of seconds")
        del argv[i:i + 2]
        return v
    return default


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    verb = argv[0] if argv and argv[0] in ("stop", "wait") else "list"
    rest = argv[1:] if verb != "list" else argv
    grace = flag(rest, "--grace", 3.0)
    timeout = flag(rest, "--timeout", 600.0)
    pattern = " ".join(rest)
    if verb != "list" and not pattern.strip():
        sys.exit(f"[builderbot] ERROR: bb proc {verb} takes a pattern: a word of the command line, "
                 "never empty, so it cannot reach every process of yours")
    rows = matching(pattern)
    if verb == "list":
        if not rows:
            print(f"[builderbot] nothing of yours runs with {pattern!r} in its command line" if pattern
                  else "[builderbot] nothing of yours runs besides this call")
            return 1
        say(rows)
        return 0
    if verb == "wait":
        end = time.time() + timeout
        while rows and time.time() < end:
            time.sleep(0.5)
            rows = [r for r in matching(pattern) if alive(r[0])]
        if rows:
            print(f"[builderbot] still running after {int(timeout)}s:", file=sys.stderr)
            say(rows)
            return 1
        print(f"[builderbot] nothing with {pattern!r} in its command line is running")
        return 0
    # stop
    if not rows:
        print(f"[builderbot] nothing of yours runs with {pattern!r} in its command line: nothing ended")
        return 0
    for pid, _ in rows:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    end = time.time() + grace
    left = [r for r in rows if alive(r[0])]
    while left and time.time() < end:
        time.sleep(0.2)
        left = [r for r in left if alive(r[0])]
    for pid, _ in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    killed = {p for p, _ in left}
    for pid, args in rows:
        print(f"[builderbot] ended {pid}{' (killed: it ignored SIGTERM)' if pid in killed else ''}: {args[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
