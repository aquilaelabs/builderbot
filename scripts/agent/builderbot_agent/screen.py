"""A VM's screen for the dock (R99): a small websocket server on the
session address's SCREEN_PORT that relays one connection to one of this
machine's VMs' VNC, which libvirt listens for on the loopback alone.

The controller is the only caller: the port is opened to it alone, beside
the terminals' (sessions' firewall check), and each request carries the
controller's signature over the VM and the minute, keyed with the hash of
this node's own token, which both ends hold and nothing else does. The
browser's noVNC speaks RFB over it; nothing here reads what passes.
"""
import base64
import hashlib
import hmac
import os
import re
import select
import socket
import struct
import threading
import time
import urllib.parse

from .base import _run, log, log_once
from .vms import DOMAIN_RE, VIRSH

SCREEN_PORT = 7684
SKEW_S = 120
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def screen_key(token):
    """The signing key: the controller's stored hash of this node's token."""
    secret = str(token or "")
    secret = secret[4:] if secret.startswith("bbn_") else secret
    return hashlib.sha256(secret.encode()).hexdigest()


def sign(key, domain, when):
    return hmac.new(key.encode(), f"{domain}.{int(when)}".encode(), hashlib.sha256).hexdigest()


def signed(key, domain, when, sig, now=None):
    """Whether the signature is the controller's, for this VM, this minute."""
    try:
        when = int(when)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    return abs(now - when) <= SKEW_S and hmac.compare_digest(sign(key, domain, when), str(sig or ""))


def vnc_port(domain):
    """The loopback port libvirt gave the VM's VNC, or 0."""
    m = re.match(r"vnc://127\.0\.0\.1:(\d+)", _run(VIRSH + ["domdisplay", domain], timeout=10).strip())
    return 5900 + int(m.group(1)) if m else 0


def _frame(payload, opcode=2):
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    return head + payload


class _Frames:
    """The client's frames as they arrive: (opcode, payload) once whole."""
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
            data = bytes(c ^ mask[k % 4] for k, c in enumerate(b[i:i + n]))
            self.buf = b[i + n:]
            out.append((op, data))


def _refuse(conn, code, why):
    body = why.encode()
    conn.sendall(f"HTTP/1.1 {code} Refused\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)


def serve_one(conn, key):
    """One browser's screen: the request read, checked and answered, then
    the bytes relayed both ways until either end closes."""
    conn.settimeout(10)
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 8192:
        got = conn.recv(4096)
        if not got:
            return
        head += got
    lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
    path = lines[0].split(" ")[1] if len(lines[0].split(" ")) > 1 else ""
    hdr = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    domain = (q.get("vm") or [""])[0]
    if not DOMAIN_RE.fullmatch(domain):
        return _refuse(conn, 404, "no such VM")
    if not signed(key, domain, (q.get("t") or [""])[0], (q.get("s") or [""])[0]):
        return _refuse(conn, 403, "not signed by this node's controller")
    port = vnc_port(domain)
    if not port:
        return _refuse(conn, 409, "the VM is not running, or has no screen")
    # SHA-1 because RFC 6455 says so: the accept key is a handshake, not a secret.
    accept = base64.b64encode(hashlib.sha1((hdr.get("sec-websocket-key", "") + WS_GUID).encode()).digest()).decode()  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    proto = "binary" if "binary" in hdr.get("sec-websocket-protocol", "") else ""
    vnc = socket.create_connection(("127.0.0.1", port), timeout=5)
    vnc.settimeout(None)
    conn.settimeout(None)
    conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Accept: {accept}\r\n"
                  + (f"Sec-WebSocket-Protocol: {proto}\r\n" if proto else "") + "\r\n").encode())
    frames = _Frames()
    try:
        while True:
            ready, _, _ = select.select([conn, vnc], [], [], 60)
            if conn in ready:
                got = conn.recv(65536)
                if not got:
                    return
                for op, data in frames.feed(got):
                    if op == 8:
                        return
                    if op == 9:
                        conn.sendall(_frame(data, 10))
                    elif op in (0, 1, 2):
                        vnc.sendall(data)
            if vnc in ready:
                got = vnc.recv(65536)
                if not got:
                    return
                conn.sendall(_frame(got))
    finally:
        vnc.close()


class ScreenRelay:
    """The listener, on the address the terminals listen on, while this
    machine has VMs; a connection each in its own thread."""
    def __init__(self, agent):
        self.agent = agent

    def start(self):
        if os.geteuid() != 0:
            return
        threading.Thread(target=self.run, name="screen", daemon=True).start()

    def run(self):
        while True:
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                bound = self.agent.session_bind()
                srv.bind((bound, SCREEN_PORT))
                srv.listen(8)
                log(f"screen: VMs' screens relayed on {bound}:{SCREEN_PORT}, to the controller alone")
                while True:
                    conn, _ = srv.accept()
                    key = screen_key(self.agent.state.get("token"))
                    threading.Thread(target=self._one, args=(conn, key), daemon=True, name="screen-one").start()
            except OSError as e:
                log_once("screen-bind", f"screen: cannot listen on {SCREEN_PORT}: {e}")
                time.sleep(60)

    @staticmethod
    def _one(conn, key):
        try:
            serve_one(conn, key)
        except OSError:
            pass
        finally:
            conn.close()
