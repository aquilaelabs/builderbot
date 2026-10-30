"""The dashboard's own TLS (R158 step 2): the mode read from the settings,
a self-signed pair made for the names and kept with its key sealed, one
socket serving https and http by the first byte, and the status the
Connection section and the Doctor read."""
import http.client
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signing  # noqa: E402
import tls      # noqa: E402

KEY = bytes(range(32))


class Mode(unittest.TestCase):
    def test_the_mode_reads_as_set_else_from_the_hostname(self):
        self.assertEqual(tls.mode_of({"tls_mode": "", "tls_host": ""}.get), "http")
        self.assertEqual(tls.mode_of({"tls_mode": "", "tls_host": "bb.example.com"}.get), "self")
        self.assertEqual(tls.mode_of({"tls_mode": "http", "tls_host": "bb.example.com"}.get), "http")
        self.assertEqual(tls.mode_of({"tls_mode": "ACME", "tls_host": "x"}.get), "acme")


class Pair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        tls.RUN_DIR = self.tmp
        tls.configure(state=self.tmp, seal_fn=signing.seal, unseal_fn=signing.unseal,
                      sealing_fn=lambda: signing.MASTER is not None)
        tls._ctx, tls._pending = None, {}
        self.addCleanup(lambda: setattr(tls, "_ctx", None))

    def test_self_signed_for_the_names_kept_with_the_key_sealed(self):
        st = tls.apply({"tls_mode": "self", "tls_host": "bb.example.com"}.get, names=["192.168.1.10"])
        self.assertEqual((st["mode"], st["on"], st["kind"]), ("self", True, "self"))
        self.assertIn("bb.example.com", st["names"])
        self.assertRegex(st["fingerprint"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        self.assertGreater(st["expires"], 0)
        self.assertTrue(st["key_sealed"])
        raw = open(os.path.join(self.tmp, "tls", "key.pem")).read()
        self.assertTrue(raw.startswith("bbseal:") and "PRIVATE KEY" not in raw)
        self.assertIn("BEGIN CERTIFICATE", tls.certificate_pem())
        self.assertEqual([f for f in os.listdir(self.tmp) if f.startswith("builderbot-tls-")], [], "the opened key is gone after the load")
        # Applied again with the same names: the pair stays.
        fp = st["fingerprint"]
        self.assertEqual(tls.apply({"tls_mode": "self", "tls_host": "bb.example.com"}.get, names=["192.168.1.10"])["fingerprint"], fp)
        # Off again: no context, the pair kept for next time.
        self.assertFalse(tls.apply({"tls_mode": "http", "tls_host": "bb.example.com"}.get)["on"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "tls", "cert.pem")))

    def test_one_port_serves_both(self):
        tls.apply({"tls_mode": "self", "tls_host": "localhost"}.get, names=["127.0.0.1"])

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"tls": isinstance(self.connection, ssl.SSLSocket)}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                del format, args

        class S(ThreadingHTTPServer):
            daemon_threads = True

            def get_request(self):
                sock, addr = super().get_request()
                return tls.wrap(sock), addr

        srv = S(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        port = srv.server_port
        plain = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        plain.request("GET", "/"); self.assertEqual(json.loads(plain.getresponse().read()), {"tls": False})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sec = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ctx)
        sec.request("GET", "/"); self.assertEqual(json.loads(sec.getresponse().read()), {"tls": True})
        # The certificate served is the one kept.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw, ctx.wrap_socket(raw, server_hostname="localhost") as s:
            der = s.getpeercert(binary_form=True)
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        got = ":".join(f"{b:02X}" for b in x509.load_der_x509_certificate(der).fingerprint(hashes.SHA256()))
        self.assertEqual(got, tls.fingerprint())


if __name__ == "__main__":
    unittest.main()
