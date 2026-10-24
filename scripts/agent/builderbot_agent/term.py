"""BuilderBot's own terminal on a node (R133): a pty per browser tab, served
on the screen relay's port (screen.py), which every node's firewall already
opens to the controller alone.

The controller is the only caller. It signs what the terminal is (its kind
and the words ttyd's --url-arg would have passed) and the minute, keyed with
the hash of this node's own token, as it signs a VM's screen. What runs is
exactly what the node's ttyd for that kind runs (the session agent records
it as it starts them, term_kinds): bb-tty, or bb-session tty where accounts
are their own users (R125), so the token, the grant and the account's own
user are decided where they always were. Nothing here reads what passes.

The wire, inside binary websocket frames: from the browser a type byte then
its body (0 keys typed, 1 a resize as JSON {cols, rows}); to the browser the
pty's bytes as they come. A read-only terminal drops every key and keeps
the resizes. When the program ends the socket closes with why.
"""
import base64
import fcntl
import hmac
import hashlib
import json
import os
import select
import signal
import struct
import subprocess
import termios
import time

SKEW_S = 120
READ_MAX = 65536
# A terminal's words: what ttyd's --url-arg handed bb-tty, one per ?arg=.
ARG_MAX = 32
WORD_MAX = 4096


def sign(key, blob, when):
    return hmac.new(key.encode(), f"term.{blob}.{int(when)}".encode(), hashlib.sha256).hexdigest()


def signed(key, blob, when, sig, now=None):
    """Whether the controller signed this terminal, this minute. `key` may
    be several: the current and the one before a rotation."""
    try:
        when = int(when)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    keys = key if isinstance(key, list) else [key]
    return abs(now - when) <= SKEW_S and any(hmac.compare_digest(sign(k, blob, when), str(sig or "")) for k in keys)


def pack(spec):
    """The signed blob for {kind, argv, cols, rows}: URL-safe base64 of its JSON."""
    return base64.urlsafe_b64encode(json.dumps(spec, separators=(",", ":")).encode()).decode().rstrip("=")


def unpack(blob):
    """{kind, argv, cols, rows} from a blob, or None for anything else."""
    try:
        d = json.loads(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict) or d.get("kind") not in ("rw", "ro", "ctr"):
        return None
    argv = d.get("argv")
    if not isinstance(argv, list) or len(argv) > ARG_MAX \
            or not all(isinstance(a, str) and 0 < len(a) <= WORD_MAX and "\0" not in a for a in argv):
        return None
    return {"kind": d["kind"], "argv": argv, "cols": _dim(d.get("cols"), 80), "rows": _dim(d.get("rows"), 24)}


def _dim(v, default):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return v if 1 <= v <= 1000 else default


def resize(fd, cols, rows):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def spawn(how, words, cols, rows):
    """The kind's program on a new pty: (process, master fd). `how` is the
    session agent's record of it: argv, env, who (user, group,
    extra_groups, as subprocess takes them) and cwd. subprocess forks in C,
    which a threaded agent needs (a Python fork can deadlock in the child);
    setsid -c makes the pty the program's controlling terminal, so a resize
    reaches tmux as SIGWINCH."""
    master, slave = os.openpty()
    resize(master, cols, rows)
    # The terminal it is talking to, as ttyd said it: xterm.js speaks
    # xterm-256color, and tmux refuses a terminal it has no entry for.
    env = {**dict(how.get("env") or {}), "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    try:
        p = subprocess.Popen(["setsid", "-c"] + list(how["argv"]) + list(words),
                             stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                             cwd=how.get("cwd") or "/", env=env, **(how.get("who") or {}))
    except (OSError, ValueError):
        os.close(master)
        raise
    finally:
        os.close(slave)
    return p, master


def _ended(p):
    """How the program ended, in words, once it has; "" while it runs."""
    code = p.poll()
    if code is None:
        return ""
    if code < 0:
        return f"ended by signal {-code}"
    return "ended" if code == 0 else f"ended with exit code {code}"


def _close(p):
    """The program ended when its tab is: hung up, then made to go. A tmux
    client ends here; the tmux session it was attached to does not."""
    for sig in (signal.SIGHUP, signal.SIGKILL):
        if p.poll() is not None:
            return
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                p.send_signal(sig)
            except ProcessLookupError:
                return
        try:
            p.wait(2)
            return
        except subprocess.TimeoutExpired:
            continue


def relay(conn, frames, frame, spec, how, alive=None):
    """One tab: the pty's program and the browser's socket joined until
    either ends. `frames` reads the browser's frames, `frame` makes one.
    `alive`, asked every few seconds, says why the terminal may no longer
    be open (a grant taken away, R133 step 9), and it is then ended."""
    p, fd = spawn(how, spec["argv"], spec["cols"], spec["rows"])
    ro = spec["kind"] == "ro"
    why = ""
    check = time.monotonic() + 5
    try:
        while True:
            ready, _, _ = select.select([conn, fd], [], [], 5 if alive else 30)
            if fd in ready:
                try:
                    got = os.read(fd, READ_MAX)
                except OSError:
                    got = b""
                if not got:
                    # The pty can end before the program is reaped: its
                    # code waited for a moment, so the tab says it (B327).
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    why = _ended(p) or "ended"
                    break
                conn.sendall(frame(got))
            if conn in ready:
                got = conn.recv(READ_MAX)
                if not got:
                    return
                for op, data in frames.feed(got):
                    if op == 8:
                        return
                    if op == 9:
                        conn.sendall(frame(data, 10))
                    elif op in (1, 2) and data:
                        kind, body = data[0], data[1:]
                        if kind in (0, 0x30) and not ro:          # 0, or "0" from a text frame
                            os.write(fd, body)
                        elif kind in (1, 0x31):
                            try:
                                d = json.loads(body)
                                resize(fd, _dim(d.get("cols"), 80), _dim(d.get("rows"), 24))
                            except (ValueError, AttributeError):
                                pass
            if not ready and _ended(p):
                why = _ended(p) or "ended"
                break
            if alive and time.monotonic() >= check:
                check = time.monotonic() + 5
                why = alive() or ""
                if why:
                    break
        # The close says why, for the tab to show: 1000 and the words.
        reason = why.encode()[:120]
        conn.sendall(frame(struct.pack(">H", 1000) + reason, 8))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        _close(p)
