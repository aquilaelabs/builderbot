"""The ACME client (R150) against a directory of its own: an account made,
an order placed, the HTTP-01 and DNS-01 challenges presented through the
caller's hooks and polled valid, the order finalized with a CSR for the
names, the chain fetched; a refused order says what the server said; and
the nginx page's config carries a challenge's line on every port-80 server
while it is being answered."""
import base64
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import acme  # noqa: E402
import nginxproxy as npx  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class FakeAcme(http.server.BaseHTTPRequestHandler):
    """Enough of RFC 8555 to issue: nonces, newAccount, newOrder, an
    authorization with both challenges, finalize and the certificate; the
    challenge's answer is checked through what the test's hook recorded."""
    state = {}

    def log_message(self, format, *args):
        del format, args

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Replay-Nonce", "nonce-" + os.urandom(4).hex())
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200); self.send_header("Replay-Nonce", "n1"); self.end_headers()

    def do_GET(self):
        base = f"http://{self.headers['Host']}"
        if self.path == "/directory":
            return self._json(200, {"newNonce": base + "/nonce", "newAccount": base + "/acct", "newOrder": base + "/order"})
        if self.path == "/nonce":
            return self._json(204, {})
        self._json(404, {"detail": "no such thing"})

    def do_POST(self):
        base = f"http://{self.headers['Host']}"
        n = int(self.headers.get("Content-Length") or 0)
        jws = json.loads(self.rfile.read(n) or b"{}")
        protected = json.loads(_b64d(jws["protected"]))
        payload = json.loads(_b64d(jws["payload"])) if jws.get("payload") else None
        st = FakeAcme.state
        st.setdefault("seen", []).append((self.path, payload))
        if "jwk" in protected:
            st["jwk"] = protected["jwk"]
        if self.path == "/acct":
            return self._json(201, {"status": "valid"}, {"Location": base + "/acct/1"})
        if self.path == "/order":
            if st.get("refuse"):
                return self._json(403, {"type": "urn:ietf:params:acme:error:rejectedIdentifier", "detail": st["refuse"]})
            st["names"] = [i["value"] for i in payload["identifiers"]]
            st["order"] = {"status": "pending", "authorizations": [base + "/authz/1"], "finalize": base + "/finalize"}
            return self._json(201, st["order"], {"Location": base + "/order/1"})
        if self.path == "/authz/1":
            chs = [{"type": "http-01", "url": base + "/chal/http", "token": "tok-http-0123456789", "status": st.get("http", "pending")},
                   {"type": "dns-01", "url": base + "/chal/dns", "token": "tok-dns-0123456789", "status": st.get("dns", "pending")}]
            status = ("valid" if "valid" in (st.get("http"), st.get("dns"))
                      else "invalid" if "invalid" in (st.get("http"), st.get("dns")) else "pending")
            return self._json(200, {"status": status, "identifier": {"type": "dns", "value": st["names"][0]}, "challenges": chs})
        if self.path.startswith("/chal/"):
            kind = self.path.rsplit("/", 1)[1]
            # Validated through what the hook presented: the key authorization
            # the client computed, against the account key's thumbprint.
            jwk = json.dumps(st["jwk"], sort_keys=True, separators=(",", ":")).encode()
            thumb = base64.urlsafe_b64encode(hashlib.sha256(jwk).digest()).decode().rstrip("=")
            want = f"tok-{kind}-0123456789.{thumb}"
            got = st.get("presented", {}).get(kind)
            if kind == "dns":
                want = base64.urlsafe_b64encode(hashlib.sha256(want.encode()).digest()).decode().rstrip("=")
            st[kind] = "valid" if got == want else "invalid"
            return self._json(200, {"status": st[kind]})
        if self.path == "/finalize":
            csr = x509.load_der_x509_csr(_b64d(payload["csr"]))
            names = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
            st["csr_names"] = list(names)
            ca = ec.generate_private_key(ec.SECP256R1())
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fake CA")]))
                    .public_key(csr.public_key()).serial_number(7).not_valid_before(now - timedelta(days=1))
                    .not_valid_after(now + timedelta(days=90)).sign(ca, hashes.SHA256()))
            st["chain"] = cert.public_bytes(serialization.Encoding.PEM).decode()
            st["order"] = {"status": "valid", "certificate": base + "/cert"}
            return self._json(200, st["order"])
        if self.path == "/order/1":
            return self._json(200, st["order"])
        if self.path == "/cert":
            body = st["chain"].encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/pem-certificate-chain")
            self.send_header("Replay-Nonce", "n9")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"detail": "no such thing"})


class Issue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAcme)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/directory"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeAcme.state = {}
        acme.POLL_S, acme.POLL_FOR = 0.05, 5

    def test_http01_end_to_end(self):
        cleaned = []
        def present(kind, name, token, value):
            self.assertEqual((kind, name, token), ("http-01", "www.example.com", "tok-http-0123456789"))
            FakeAcme.state.setdefault("presented", {})["http"] = value
        client = acme.Client(self.url, acme.account_key_new(), contact="mailto:a@example.com")
        chain, key = client.issue(["www.example.com", "example.com"], "http-01", present, lambda *a: cleaned.append(a))
        self.assertIn("-----BEGIN CERTIFICATE-----", chain)
        self.assertIn("PRIVATE KEY-----", key)
        self.assertEqual(FakeAcme.state["csr_names"], ["www.example.com", "example.com"])
        self.assertEqual(len(cleaned), 1, "the challenge taken down once")
        self.assertEqual(FakeAcme.state["seen"][0][1].get("contact"), ["mailto:a@example.com"])
        self.assertGreater(acme.expires(chain), 0)

    def test_dns01_presents_the_hashed_value(self):
        def present(kind, name, token, value):
            self.assertEqual(kind, "dns-01")
            FakeAcme.state.setdefault("presented", {})["dns"] = value
        chain, _ = acme.Client(self.url, acme.account_key_new()).issue(["a.example.com"], "dns-01", present)
        self.assertIn("CERTIFICATE", chain)

    def test_a_wrong_answer_and_a_refused_order_say_why(self):
        with self.assertRaises(acme.AcmeError) as got:
            acme.Client(self.url, acme.account_key_new()).issue(["b.example.com"], "http-01", lambda *a: None)
        self.assertIn("invalid", str(got.exception))
        FakeAcme.state = {"refuse": "that name is not allowed"}
        with self.assertRaises(acme.AcmeError) as got:
            acme.Client(self.url, acme.account_key_new()).issue(["c.example.com"], "http-01", lambda *a: None)
        self.assertIn("that name is not allowed", str(got.exception))


class ChallengeInNginx(unittest.TestCase):
    def test_the_tokens_line_is_on_every_port_80_server(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        npx.configure(state=tmp, write_json=lambda p, d, mode=0o644: open(p, "w").write(json.dumps(d)),
                      node_list=lambda: [], node_name=lambda nid: nid, taken_ports=lambda *a: [])
        routes = [{"host": "www.example.com", "path": "/", "port": 8080, "tls": True, "cert": ""}]
        rec = {"routes": routes, "acme_tokens": {"tok-http-0123456789": "tok-http-0123456789.THUMBPRINT"}}
        conf = npx.nginx_conf(routes, rec)
        line = 'location = /.well-known/acme-challenge/tok-http-0123456789 { default_type text/plain; return 200 "tok-http-0123456789.THUMBPRINT"; }'
        self.assertEqual(conf.count(line), 2, "the hostname's port-80 server and the default one")
        self.assertIn("location / { return 444; }", conf)
        self.assertNotIn(line, npx.nginx_conf(routes, {"routes": routes}))
        bad = npx.nginx_conf(routes, {"routes": routes, "acme_tokens": {"x y": "z"}})
        self.assertNotIn("acme-challenge", bad, "a token that is not one is not written into the config")


if __name__ == "__main__":
    unittest.main()
