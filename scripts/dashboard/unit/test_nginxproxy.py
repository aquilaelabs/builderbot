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
        self.assertEqual(r["routes"][0], {"host": "www.example.com", "path": "/", "port": 8080, "tls": True})
        self.assertEqual(npx.record("n1")["routes"], r["routes"])
        self.assertEqual(npx.container_name("n1"), "nginx-vps-box")

    def test_the_config_has_a_server_per_host_and_closes_the_rest(self):
        routes = npx.clean_routes([{"host": "www.example.com", "path": "/", "port": 8080},
                                   {"host": "www.example.com", "path": "/relay", "port": 8788, "tls": False}])
        conf = npx.nginx_conf(routes, has_cert=True)
        self.assertIn("server_name _; return 444;", conf)
        self.assertIn("listen 443 ssl;", conf)
        self.assertIn("ssl_certificate /etc/nginx/certs/cert.pem;", conf)
        self.assertIn("location /relay/ { proxy_pass http://127.0.0.1:8788; }", conf)
        self.assertIn("location / { proxy_pass http://127.0.0.1:8080; }", conf)
        self.assertLess(conf.index("location /relay/"), conf.index("location / "), "the longest path first")
        plain = npx.nginx_conf(routes, has_cert=False)
        self.assertNotIn("443", plain, "no certificate, no 443")
        # A * route is the default server itself: no second one beside it.
        star = npx.nginx_conf(npx.clean_routes([{"host": "*", "path": "/", "port": 8089}]), has_cert=True)
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
        r = npx.set_cert("n1", self.cert, self.key)
        self.assertEqual((r["cert"]["set"], r["cert"]["subject"]), (True, "www.example.com"))
        self.assertGreater(r["cert"]["expires"], 0)
        key = os.path.join(self.tmp, "nginx", "n1", "key.pem")
        self.assertEqual(oct(os.stat(key).st_mode & 0o777), "0o600")
        text = npx.compose_text("n1", npx.record("n1"))
        self.assertIn("tls_key:\n    content: |\n      -----BEGIN PRIVATE KEY-----", text)
        self.assertIn("mode: 0400", text)
        npx.drop_cert("n1")
        self.assertFalse(os.path.exists(key))
        self.assertNotIn("cert", npx.record("n1"))

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
        conf = npx.nginx_conf(rec["routes"], False, rec)
        self.assertEqual(conf.count("ssl_certificate /etc/nginx/certs/example.com/cert.pem;"), 2,
                         "both subdomains' servers use the domain's pair")
        text = npx.compose_text("n1", rec)
        self.assertIn("tls_cert_example_com:\n    content: |", text, "the pair rides the compose file once")
        npx.set_cert("n1", self.cert, self.key, host="a.example.com")
        self.assertEqual(npx.cert_for(npx.record("n1"), "a.example.com"), "a.example.com", "its own wins")
        npx.drop_cert("n1", host="a.example.com")
        npx.drop_cert("n1", host="example.com")

    def test_a_hostname_may_have_its_own_beside_the_default(self):
        """One certificate per hostname (R175): a site on another domain
        behind the same nginx gets its own, the rest use the default."""
        npx.save_routes("n1", [{"host": "www.example.com", "path": "/", "port": 8080},
                               {"host": "www.other.net", "path": "/", "port": 8081}])
        self.assertIn("hostname like", npx.set_cert("n1", self.cert, self.key, host="bad host")["error"])
        self.assertEqual(npx.set_cert("n1", self.cert, self.key, host="WWW.Other.net")["host"], "www.other.net")
        rec = npx.record("n1")
        self.assertTrue(rec["certs"]["www.other.net"]["set"] and "cert" not in rec)
        conf = npx.nginx_conf(rec["routes"], False, rec)
        self.assertIn("ssl_certificate /etc/nginx/certs/www.other.net/cert.pem;", conf)
        self.assertNotIn("server_name www.example.com;\n    ssl_certificate", conf.replace("    listen 443 ssl;\n", ""))
        self.assertEqual(conf.count("listen 443 ssl"), 1, "only the hostname with a certificate answers on 443")
        npx.set_cert("n1", self.cert, self.key)
        rec = npx.record("n1")
        conf = npx.nginx_conf(rec["routes"], True, rec)
        self.assertEqual(conf.count("listen 443 ssl"), 3, "the default covers the rest, and the catch-all")
        self.assertIn("ssl_certificate /etc/nginx/certs/cert.pem;", conf)
        text = npx.compose_text("n1", rec)
        self.assertIn("target: /etc/nginx/certs/www.other.net/cert.pem", text)
        self.assertIn("tls_cert_www_other_net:\n    content: |", text)
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "nginx", "n1", "certs", "www.other.net", "key.pem")).st_mode & 0o777), "0o600")
        npx.drop_cert("n1", host="www.other.net")
        self.assertNotIn("www.other.net", npx.record("n1").get("certs") or {})
        self.assertNotIn("certs/www.other.net", npx.compose_text("n1", npx.record("n1")))


if __name__ == "__main__":
    unittest.main()
