#!/usr/bin/env python3
"""bb-ftpd: one project's file tree over FTPS, for the people its settings
name (R151, the operator, 7 Oct).

The node agent starts one of these per project that has file access turned
on, as the session account, with the project's directory as the root.
Nobody's password is known here: each login's name and password go to the
agent as one JSON line on stdout, and the agent asks the controller, which
answers the access that account has on this project ("r", "rw", or none).
The answer comes back as one JSON line on stdin. Nothing is cached, so an
access taken away in the settings holds from the next login.

TLS is required on the control and the data connection: the password is
the account's BuilderBot password, the same one that signs in to the
dashboard, and plain FTP would send it across the network as written. The
certificate is made on the first start and kept beside the node's state;
a client is asked to trust it once.

    bb-ftpd --root DIR --port N --cert FILE [--bind ADDR] [--project NAME]

Passive data connections use the nine ports after N, which is why the
controller keeps ten ports apart between projects on one node.
"""
import argparse
import itertools
import json
import logging
import os
import sys
import threading
import time

from pyftpdlib.authorizers import AuthenticationFailed, DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.servers import ThreadedFTPServer

READ = "elr"
WRITE = "elradfmwMT"
PASSIVE = 9


def make_cert(path):
    """A self-signed certificate and its key in one PEM file, readable by
    this account alone."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "BuilderBot file access")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256()))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    os.replace(path + ".new", path)


class Asker:
    """One question at a time to the agent over the pipes this process was
    started with. A login waits its turn; a dead pipe is a refusal."""

    def __init__(self, out=sys.stdout, inp=sys.stdin):
        self.out, self.inp = out, inp
        self.lock = threading.Lock()
        self.ids = itertools.count(1)

    def ask(self, user, password, addr):
        with self.lock:
            n = next(self.ids)
            try:
                self.out.write(json.dumps({"id": n, "user": user, "password": password, "addr": addr}) + "\n")
                self.out.flush()
                line = self.inp.readline()
            except (OSError, ValueError):
                return {}
        try:
            got = json.loads(line) if line else {}
        except ValueError:
            return {}
        return got if isinstance(got, dict) and got.get("id") == n else {}


class Authorizer(DummyAuthorizer):
    """Every login asked of the controller, through the agent; the table
    pyftpdlib keeps holds only the access the last answer gave."""

    def __init__(self, root, asker):
        super().__init__()
        self.root = os.path.realpath(root)
        self.asker = asker

    def validate_authentication(self, username, password, handler):
        addr = handler.remote_ip if handler is not None else ""
        got = self.asker.ask(username, password, addr)
        access = got.get("access")
        if access not in ("r", "rw"):
            raise AuthenticationFailed(got.get("why") or "Authentication failed.")
        with self.lock_table():
            if self.has_user(username):
                self.remove_user(username)
            self.add_user(username, "", self.root, perm=WRITE if access == "rw" else READ,
                          msg_login=f"Signed in with {'read and write' if access == 'rw' else 'read'} access.")
            # The repository's own store is read-only whatever the access:
            # a file written into .git by hand is how a history is broken.
            git = os.path.join(self.root, ".git")
            if access == "rw" and os.path.isdir(git):
                self.override_perm(username, git, READ, recursive=True)

    _table = threading.Lock()

    def lock_table(self):
        return self._table


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bb-ftpd")
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--cert", required=True)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--project", default="")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        sys.stderr.write(f"bb-ftpd: {a.root} is not a directory\n")
        return 2
    if not os.path.isfile(a.cert):
        make_cert(a.cert)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format=f"[bb-ftpd {a.project or a.port}] %(message)s")

    class Handler(TLS_FTPHandler):
        certfile = a.cert
        tls_control_required = True
        tls_data_required = True
        passive_ports = range(a.port + 1, a.port + 1 + PASSIVE)
        banner = f"BuilderBot file access{': ' + a.project if a.project else ''}"
        permit_foreign_addresses = False
        timeout = 600

    # Ends with the agent that started it: an agent updating itself is a new
    # process, which starts its own server on the same port, and an orphan
    # left on it would refuse every login with nobody to ask.
    parent = os.getppid()

    def orphaned():
        while os.getppid() == parent:
            time.sleep(2)
        os._exit(0)
    threading.Thread(target=orphaned, daemon=True).start()

    Handler.authorizer = Authorizer(a.root, Asker())
    server = ThreadedFTPServer((a.bind, a.port), Handler)
    server.max_cons = 64
    server.max_cons_per_ip = 16
    # Bound: the agent reads this line to know the port is held.
    sys.stderr.write(f"bb-ftpd: listening on {a.bind}:{a.port}\n")
    sys.stderr.flush()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
