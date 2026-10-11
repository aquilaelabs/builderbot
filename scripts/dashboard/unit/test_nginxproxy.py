"""One nginx per node (nginxproxy.py, R171): the routes kept here become
nginx's config and a compose file with everything inline; a certificate is
checked as nginx would load it, kept 0600, and never shown back."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nginxproxy as npx  # noqa: E402


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        npx.configure(state=self.tmp, write_json=write_json, node_list=lambda: [],
                      node_name=lambda nid: {"n1": "vps box"}.get(nid, nid), taken_ports=lambda *a: [])

    def test_routes_are_checked_and_kept(self):
        self.assertIn("hostname", npx.save_routes("n1", [{"host": "bad host", "port": "80"}])["error"])
        self.assertIn("port", npx.save_routes("n1", [{"host": "www.example.com", "port": "x"}])["error"])
        self.assertIn("path", npx.save_routes("n1", [{"host": "*", "path": "no-slash", "port": "80"}])["error"])
        r = npx.save_routes("n1", [{"host": "WWW.Example.com", "path": "/", "port": "8080", "tls": True},
                                   {"host": "www.example.com", "path": "/relay", "port": 8788, "tls": False}])
        self.assertEqual(r["routes"][0], {"host": "www.example.com", "path": "/", "port": 8080, "tls": True, "cert": ""})
        self.assertEqual(npx.record("n1")["routes"], r["routes"])
        self.assertEqual(npx.container_name("n1"), "nginx-vps-box")

    def test_the_config_has_a_server_per_host_and_closes_the_rest(self):
        routes = npx.clean_routes([{"host": "www.example.com", "path": "/", "port": 8080},
                                   {"host": "www.example.com", "path": "/relay", "port": 8788, "tls": False}])
        rec = {"certs": {"example.com": {"set": True}}}
        conf = npx.nginx_conf(routes, rec)
        self.assertIn("server_name _; return 444;", conf)
        self.assertIn("listen 443 ssl;", conf)
        self.assertIn("ssl_certificate /etc/nginx/certs/example.com/cert.pem;", conf, "its domain's pair")
        self.assertIn("listen 443 ssl default_server; server_name _; ssl_reject_handshake on; return 444;", conf,
                      "the catch-all refuses the handshake with no pair at all (R188)")
        self.assertIn("location /relay/ { proxy_pass http://127.0.0.1:8788; }", conf)
        self.assertIn("location / { proxy_pass http://127.0.0.1:8080; }", conf)
        self.assertLess(conf.index("location /relay/"), conf.index("location / "), "the longest path first")
        plain = npx.nginx_conf(routes, {})
        self.assertNotIn("listen 443 ssl;", plain, "no pair covers it: 80 alone")
        self.assertIn("ssl_reject_handshake", plain, "...and the catch-all still refuses 443")
        # A route's own pick wins over its domain's pair.
        picked = npx.clean_routes([{"host": "www.example.com", "path": "/", "port": 8080, "cert": "other.net"}])
        rec2 = {"certs": {"example.com": {"set": True}, "other.net": {"set": True}}}
        self.assertIn("certs/other.net/cert.pem", npx.nginx_conf(picked, rec2))
        self.assertIn("certificate is one the node holds", npx.clean_routes([{"host": "a.b", "path": "/", "port": 1, "cert": "bad key"}])["error"])
        # A * route is the default server itself: no second one beside it.
        star = npx.nginx_conf(npx.clean_routes([{"host": "*", "path": "/", "port": 8089, "cert": "example.com"}]), rec)
        self.assertEqual(star.count("default_server"), 2, "one for 80 and one for 443, both the * route's")
        self.assertNotIn("return 444", star)

    def test_the_compose_file_carries_it_all_inline(self):
        npx.save_routes("n1", [{"host": "*", "path": "/", "port": "3000"}])
        text = npx.compose_text("n1", npx.record("n1"))
        self.assertIn("image: nginx:1.27-alpine", text)
        self.assertIn("network_mode: host", text)
        self.assertIn("nginx_conf:\n    content: |\n", text)
        self.assertIn("      location / { proxy_pass http://127.0.0.1:3000; }", text)
        self.assertNotIn("tls_cert", text)
        # nginx's variables survive compose's own interpolation: $$host, never $host.
        self.assertIn("proxy_set_header Host $$host;", text)
        self.assertNotRegex(text, r"[^$]\$host")


class Certificate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        npx.configure(state=self.tmp, write_json=write_json, node_list=lambda: [],
                      node_name=lambda nid: nid, taken_ports=lambda *a: [])
        if not shutil.which("openssl"):
            self.skipTest("no openssl here to make a certificate with")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                        "-subj", "/CN=www.example.com", "-addext", "subjectAltName=DNS:www.example.com",
                        "-keyout", f"{self.tmp}/k.pem", "-out", f"{self.tmp}/c.pem"],
                       check=True, capture_output=True)
        self.cert = open(f"{self.tmp}/c.pem").read()
        self.key = open(f"{self.tmp}/k.pem").read()

    def test_a_pair_is_checked_kept_0600_and_summarized(self):
        self.assertIn("PEM", npx.check_cert("nope", self.key)["error"])
        self.assertIn("PEM", npx.check_cert(self.cert, "nope")["error"])
        other = subprocess.run(["openssl", "genrsa", "2048"], capture_output=True, text=True, check=True).stdout
        self.assertIn("do not load together", npx.check_cert(self.cert, other)["error"])
        npx.save_routes("n1", [{"host": "www.example.com", "path": "/", "port": 8080}])
        r = npx.set_cert("n1", self.cert, self.key)
        self.assertEqual((r["cert"]["set"], r["cert"]["subject"], r["host"]), (True, "www.example.com", "www.example.com"),
                         "kept under the domain its names say")
        self.assertGreater(r["cert"]["expires"], 0)
        key = os.path.join(self.tmp, "nginx", "n1", "certs", "www.example.com", "key.pem")
        self.assertEqual(oct(os.stat(key).st_mode & 0o777), "0o600")
        text = npx.compose_text("n1", npx.record("n1"))
        self.assertIn("tls_key_www_example_com:\n    content: |\n      -----BEGIN PRIVATE KEY-----", text)
        self.assertIn("mode: 0400", text)
        self.assertIn("which certificate", npx.drop_cert("n1")["error"])
        npx.drop_cert("n1", "www.example.com")
        self.assertFalse(os.path.exists(key))
        self.assertNotIn("www.example.com", npx.record("n1").get("certs") or {})

    def test_two_domains_pairs_stand_side_by_side_and_a_default_from_before_is_read_in(self):
        """A pair is kept under the domain its names say, so two domains'
        pairs stand side by side and the same names again are a renewal
        (B657: turinglens.com's pair went when another was saved as the
        default); a default from before R188 is read in as a listed pair."""
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                        "-subj", "/CN=*.aquilae.test", "-addext", "subjectAltName=DNS:*.aquilae.test,DNS:aquilae.test",
                        "-keyout", f"{self.tmp}/k2.pem", "-out", f"{self.tmp}/c2.pem"],
                       check=True, capture_output=True)
        cert2, key2 = open(f"{self.tmp}/c2.pem").read(), open(f"{self.tmp}/k2.pem").read()
        self.assertEqual(npx.set_cert("n1", self.cert, self.key)["host"], "www.example.com")
        r = npx.set_cert("n1", cert2, key2)
        self.assertEqual(r["host"], "aquilae.test", r)
        rec = npx.record("n1")
        self.assertEqual(sorted(rec["certs"]), ["aquilae.test", "www.example.com"], "side by side")
        self.assertNotIn("cert", rec, "no default")
        self.assertEqual(npx.cert_for(rec, "a.aquilae.test"), "aquilae.test")
        self.assertEqual(npx.cert_for(rec, "a.aquilae.test", "www.example.com"), "www.example.com", "a pick wins")
        npx.set_cert("n1", self.cert, self.key)
        self.assertEqual(len(npx.record("n1")["certs"]), 2, "the same names again are a renewal, not a third")
        self.assertEqual(npx.domain_of("*.example.com, example.com"), "example.com")
        # A default from before: its summary under rec["cert"] and its files
        # at the node's own directory become a listed pair under its domain.
        st = npx._load(); st["n1"]["cert"] = dict(st["n1"]["certs"]["www.example.com"]); npx._save(st)
        d = npx._cert_dir("n1"); d.mkdir(parents=True, exist_ok=True)
        (d / "cert.pem").write_text(self.cert); (d / "key.pem").write_text(self.key)
        npx.drop_cert("n1", host="www.example.com")
        rec = npx.record("n1")
        self.assertNotIn("cert", rec)
        self.assertTrue(rec["certs"]["www.example.com"]["set"], "read in under its domain")
        self.assertTrue((npx._cert_dir("n1", "www.example.com") / "key.pem").is_file(), "its files moved")
        npx.drop_cert("n1", host="www.example.com"); npx.drop_cert("n1", host="aquilae.test")

    def test_a_domains_certificate_covers_its_subdomains(self):
        """One pair per domain (the operator, 11 Oct): saved under
        example.com it serves a.example.com and b.example.com, and another
        domain's pair its own; a hostname's own still wins over its domain's."""
        npx.save_routes("n1", [{"host": "a.example.com", "path": "/", "port": 8080},
                               {"host": "b.example.com", "path": "/", "port": 8081},
                               {"host": "www.other.net", "path": "/", "port": 8082}])
        self.assertEqual(npx.set_cert("n1", self.cert, self.key, host="example.com")["host"], "example.com")
        rec = npx.record("n1")
        self.assertEqual(npx.cert_for(rec, "a.example.com"), "example.com")
        self.assertEqual(npx.cert_for(rec, "www.other.net"), "", "another domain is not covered")
        self.assertEqual(npx.cert_for(rec, "com"), "", "the top label is nobody's")
        conf = npx.nginx_conf(rec["routes"], rec)
        self.assertEqual(conf.count("ssl_certificate /etc/nginx/certs/example.com/cert.pem;"), 2,
                         "both subdomains' servers use the domain's pair")
        text = npx.compose_text("n1", rec)
        self.assertIn("tls_cert_example_com:\n    content: |", text, "the pair rides the compose file once")
        npx.set_cert("n1", self.cert, self.key, host="a.example.com")
        self.assertEqual(npx.cert_for(npx.record("n1"), "a.example.com"), "a.example.com", "its own wins")
        npx.drop_cert("n1", host="a.example.com")
        npx.drop_cert("n1", host="example.com")

    def test_a_hostname_may_have_its_own_named_by_hand(self):
        """One pair per hostname (R175), filed under a name typed rather
        than the one its names say: a site on another domain behind the
        same nginx gets its own, the rest answer on 80 alone."""
        npx.save_routes("n1", [{"host": "www.example.com", "path": "/", "port": 8080},
                               {"host": "www.other.net", "path": "/", "port": 8081}])
        self.assertIn("known by a name like", npx.set_cert("n1", self.cert, self.key, host="bad host")["error"])
        self.assertEqual(npx.set_cert("n1", self.cert, self.key, host="WWW.Other.net")["host"], "www.other.net")
        rec = npx.record("n1")
        self.assertTrue(rec["certs"]["www.other.net"]["set"] and "cert" not in rec)
        conf = npx.nginx_conf(rec["routes"], rec)
        self.assertIn("ssl_certificate /etc/nginx/certs/www.other.net/cert.pem;", conf)
        self.assertNotIn("server_name www.example.com;\n    ssl_certificate", conf.replace("    listen 443 ssl;\n", ""))
        self.assertEqual(conf.count("listen 443 ssl"), 2, "the hostname with a pair, and the catch-all that refuses")
        text = npx.compose_text("n1", rec)
        self.assertIn("target: /etc/nginx/certs/www.other.net/cert.pem", text)
        self.assertIn("tls_cert_www_other_net:\n    content: |", text)
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "nginx", "n1", "certs", "www.other.net", "key.pem")).st_mode & 0o777), "0o600")
        npx.drop_cert("n1", host="www.other.net")
        self.assertNotIn("www.other.net", npx.record("n1").get("certs") or {})
        self.assertNotIn("certs/www.other.net", npx.compose_text("n1", npx.record("n1")))


if __name__ == "__main__":
    unittest.main()
