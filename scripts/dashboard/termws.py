"""BuilderBot's own terminal, the controller's half (R133): the page's
websocket at /termws, answered here.

server.py decides everything first, as it does for /term: whose terminal
it is, whether this account may open it, where it runs, and the words
ttyd's --url-arg would have handed bb-tty (the account, and for a node the
session token, the name and the owner mark). This module only carries it:

  * a terminal on this controller runs bb-tty with those words in a pty of
    its own, through the node agent's own term.py (loaded by path, so the
    two ends are one implementation);
  * a terminal on a node is a websocket to that node's screen relay at
    /term, signed with the node's screen key over the terminal it is (the
    kind and the words) and the minute, then spliced byte for byte.

The wire is the same at every hop: binary frames, the browser's a type
byte (0 keys, 1 a resize as JSON) and its body, the terminal's the pty's
bytes; the close says why it ended. `alive()`, asked every few seconds,
ends a terminal whose grant was taken away while it was open (step 9).
"""
import base64
import hashlib
import importlib.util
import os
import selectors
import socket
import struct
import time
import urllib.parse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CHECK_S = 5
AGENT_DIR = ""      # the node agent's directory, set by configure()
_term = {}


def configure(*, agent_dir):
    global AGENT_DIR
    AGENT_DIR = agent_dir
    _term.clear()


def term():
    """The node agent's term.py, loaded once by path: stdlib alone."""
    if "mod" not in _term:
        spec = importlib.util.spec_from_file_location(
            "bb_agent_term", os.path.join(str(AGENT_DIR), "builderbot_agent", "term.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _term["mod"] = mod
    return _term["mod"]


def frame(payload, opcode=2):
    """A frame from this end: never masked."""
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


class Frames:
    """The browser's frames as they arrive: (opcode, payload) once whole."""
    def __init__(self):
        self.buf = b""

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            b = self.buf
            if len(b) < 2:
                return out
            op, n, i = b[0] & 0x0F, b[1] & 0x7F, 2
            if n == 126:
                if len(b) < 4:
                    return out
                n, i = struct.unpack(">H", b[2:4])[0], 4
            elif n == 127:
                if len(b) < 10:
                    return out
                n, i = struct.unpack(">Q", b[2:10])[0], 10
            masked = b[1] & 0x80
            if len(b) < i + (4 if masked else 0) + n:
                return out
            mask = b[i:i + 4] if masked else b"\0\0\0\0"
            i += 4 if masked else 0
            body = b[i:i + n]
            key = (mask * (n // 4 + 1))[:n]
            data = (int.from_bytes(body, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big") if n else b""
            self.buf = b[i + n:]
            out.append((op, data))


def accept_key(client_key):
    # SHA-1 because RFC 6455 says so: the accept key is a handshake, not a secret.
    return base64.b64encode(hashlib.sha1((client_key + WS_GUID).encode()).digest()).decode()  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1


def upgrade(handler):
    """Answer the browser's handshake on the handler's own connection, or
    "" for a request that is not one."""
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if "websocket" not in handler.headers.get("Upgrade", "").lower() or not key:
        return ""
    handler.close_connection = True
    handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n").encode())
    handler.wfile.flush()
    return "ok"


def close(conn, why, code=1000):
    """End the browser's socket saying why, for its tab. 4001 says this
    tab is to be opened through ttyd instead (a node not yet updated)."""
    try:
        conn.sendall(frame(struct.pack(">H", code) + str(why).encode()[:120], 8))
    except OSError:
        pass


def local(conn, words, *, bbtty, env, cwd, ro, cols, rows, alive):
    """A terminal on this controller: bb-tty with its words in a pty."""
    t = term()
    spec = {"kind": "ro" if ro else "rw", "argv": list(words), "cols": cols, "rows": rows}
    how = {"argv": [bbtty], "env": dict(env, **({"BB_TTY_RO": "1"} if ro else {})), "who": {}, "cwd": cwd}
    try:
        t.relay(conn, Frames(), frame, spec, how, alive=alive)
    except OSError as e:
        close(conn, f"the terminal could not start here: {e}")


def node(conn, *, host, port, key, kind, words, cols, rows, alive):
    """A terminal on a node: its screen relay's /term, signed, then the
    two sockets spliced until either closes or `alive` says no more."""
    t = term()
    blob = t.pack({"kind": kind, "argv": list(words), "cols": cols, "rows": rows})
    when = int(time.time())
    q = urllib.parse.urlencode({"a": blob, "t": when, "s": t.sign(key, blob, when)})
    try:
        up = socket.create_connection((host, port), timeout=5)
    except OSError:
        return close(conn, f"the node did not answer on {host}:{port}")
    try:
        ckey = base64.b64encode(os.urandom(16)).decode()
        up.sendall((f"GET /term?{q} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                    f"Connection: Upgrade\r\nSec-WebSocket-Key: {ckey}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        up.settimeout(15)
        while b"\r\n\r\n" not in head and len(head) < 8192:
            got = up.recv(4096)
            if not got:
                break
            head += got
        line, _, rest = head.partition(b"\r\n\r\n")
        if b" 101 " not in line.split(b"\r\n")[0]:
            said = rest.decode("utf-8", "replace").strip() or line.split(b"\r\n")[0].decode("latin-1")
            return close(conn, f"the node refused the terminal: {said}"[:120])
        up.settimeout(None)
        if rest:
            conn.sendall(rest)
        sel = selectors.DefaultSelector()
        sel.register(up, selectors.EVENT_READ, conn)
        sel.register(conn, selectors.EVENT_READ, up)
        check = time.monotonic() + CHECK_S
        try:
            while True:
                for k, _ in sel.select(timeout=CHECK_S):
                    data = k.fileobj.recv(65536)
                    if not data:
                        return None
                    k.data.sendall(data)
                if time.monotonic() >= check:
                    check = time.monotonic() + CHECK_S
                    why = alive() if alive else ""
                    if why:
                        return close(conn, why)
        finally:
            sel.close()
    except OSError:
        return None
    finally:
        up.close()
