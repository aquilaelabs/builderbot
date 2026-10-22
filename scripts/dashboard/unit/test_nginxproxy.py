"""One nginx per node (nginxproxy.py, R171): the routes kept here become
nginx's config and a compose file with everything inline; a certificate is
checked as nginx would load it, kept 0600, and never shown back."""
import contextlib
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

    def test_a_route_from_a_row_takes_a_hostname_the_pair_covers(self):
        # The Docker row's Add route with a hostname (the operator, 13 Oct):
        # a subdomain under the pair's domain, refused outside it, and the
        # name joins the shared Hostnames list.
        was = npx.apply
        npx.apply = lambda nid, *a: {"ok": True}
        self.addCleanup(setattr, npx, "apply", was)
        with npx._lock:
            st = npx._load(); st["n1"] = {"certs": {"example.com": {"set": True}}}; npx._save(st)
        bad = npx.add_route("n1", 8080, "example.com", None, None, None, host="other.org")
        self.assertIn("does not cover other.org", bad["error"])
        r = npx.add_route("n1", 8080, "example.com", None, None, None, host="App.Example.com")
        self.assertEqual(r["route"], {"host": "app.example.com", "path": "/", "port": 8080, "tls": True, "cert": "example.com"})
        self.assertIn("app.example.com", [h["name"] for h in npx.hostnames()], "typed once, offered everywhere after")
        plain = npx.add_route("n1", 8081, "", None, None, None, host="plain.example.org")
        self.assertEqual((plain["route"]["host"], plain["route"]["tls"]), ("plain.example.org", False), "a name with no pair is 80 alone")
        none = npx.add_route("n1", 8082, "example.com", None, None, None)
        self.assertEqual(none["route"]["host"], "example.com", "no hostname typed: the pair's own domain, as before")
        # A port routed already takes another hostname (B729: the site at
        # its domain and at www, one port); the same name and port again is
        # the refusal.
        www = npx.add_route("n1", 8082, "example.com", None, None, None, host="www.example.com")
        self.assertEqual((www["route"]["host"], www["route"]["port"]), ("www.example.com", 8082), "a second hostname for the port")
        twice = npx.add_route("n1", 8082, "example.com", None, None, None, host="www.example.com")
        self.assertIn("already has a route: www.example.com/", twice["error"])

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


class FakeDevapp:
    MAIN = "main"
    SYSTEM = "System"
    FILE = "devapps.json"

    def __init__(self, deployed):
        import threading
        self.deployed = set(deployed)
        self._lock = threading.Lock()
        self.write_json = lambda path, d: None

    def _load(self):
        return {n: {"main": {"source": "file", "for": self.SYSTEM}} for n in self.deployed}

    def is_file_source(self, name):
        return name in self.deployed

    def _read_rec(self, name, inst):
        return {"node": {"nginx-vps": "n1", "nginx-box": "n2"}.get(name, "")}

    def forget_container(self, name):
        self.deployed.discard(name)
        return []


class FakeContainers:
    def __init__(self):
        self.written = {}

    def update_container(self, name, text, env):
        self.written[name] = text
        return {"ok": True}


class FakeDevactions:
    def __init__(self):
        self.rebuilt = []

    def rebuild(self, name, inst, gate=False):
        self.rebuilt.append(name)
        return {"job": f"j-{len(self.rebuilt)}"}


class WideNames(unittest.TestCase):
    """A pair on a public box (R93): the names it answers for beyond the
    node's own routes, a wildcard always among them."""
    def test_a_wildcard_and_an_unrouted_name_are_wide(self):
        rec = {"routes": [{"host": "app.example.com"}],
               "certs": {"example.com": {"set": True, "names": "*.example.com, example.com"},
                         "app.example.com": {"set": True, "names": "app.example.com"},
                         "gone.example.com": {"set": False, "names": "*.gone.example.com"}}}
        self.assertEqual(npx.wide_names(rec), {"example.com": ["*.example.com", "example.com"]})

    def test_the_subject_stands_in_for_names(self):
        rec = {"routes": [], "certs": {"x.org": {"set": True, "names": "", "subject": "x.org"}}}
        self.assertEqual(npx.wide_names(rec), {"x.org": ["x.org"]})


class Image(unittest.TestCase):
    """The image kept up to date (R192): the registry's tag list read into
    the newest release line's alpine tag and its digest, a node pinned to
    it when deployed or updated, and behind until it is."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.nodes = [{"id": "n1", "name": "vps", "kind": "agent", "state": "online"},
                      {"id": "n2", "name": "box", "kind": "agent", "state": "online"}]
        npx.configure(state=self.tmp, write_json=write_json, node_list=lambda: self.nodes,
                      node_name=lambda nid: {"n1": "vps", "n2": "box"}.get(nid, nid), taken_ports=lambda *a: [])
        self.was = npx.TAGS_URL
        self.addCleanup(setattr, npx, "TAGS_URL", self.was)
        npx.TAGS_URL = f"file://{self.tmp}/tags.json"
        self.tags({"1.27-alpine": "a", "1.29-alpine-slim": "c", "1.29-alpine": "b", "stable-alpine": "d", "1.28-alpine": "e"})

    def tags(self, named):
        write_json(f"{self.tmp}/tags.json",
                   {"results": [{"name": n, "digest": "sha256:" + d * 64} for n, d in named.items()]})

    def test_the_check_keeps_the_newest_line_and_a_node_is_behind_until_pinned(self):
        self.assertEqual(npx.latest_image(), {}, "nothing before a check")
        self.assertEqual(npx.image_ref({}), "nginx:1.27-alpine", "the line's tag alone, unpinned")
        self.assertEqual(npx.behind({}), "", "nothing to be behind yet")
        lt = npx.check_image()
        self.assertEqual((lt["tag"], lt["digest"], lt["error"]), ("1.29-alpine", "sha256:" + "b" * 64, ""),
                         "the newest X.Y-alpine, not -slim, stable- or an older line")
        self.assertGreater(lt["at"], 0)
        self.assertEqual(npx.behind(npx.record("n1")), "1.29-alpine", "unpinned is behind whatever is newest")
        self.assertEqual(npx.pin_latest("n1"), {"tag": "1.29-alpine", "digest": "sha256:" + "b" * 64})
        rec = npx.record("n1")
        self.assertEqual(npx.image_ref(rec), "nginx:1.29-alpine@sha256:" + "b" * 64)
        self.assertEqual(npx.behind(rec), "", "pinned to the newest: not behind")
        self.assertIn("    image: nginx:1.29-alpine@sha256:" + "b" * 64, npx.compose_text("n1", rec),
                      "the compose file pulls exactly that")
        # The line moves: the node is behind again, to the new digest.
        self.tags({"1.29-alpine": "f"})
        npx.check_image()
        self.assertEqual(npx.behind(npx.record("n1")), "1.29-alpine")
        rows = npx.attention(lambda nid: nid == "n1")
        self.assertEqual([(r["kind"], r["node"], r["id"], r["digest"]) for r in rows],
                         [("nginx", "vps", "n1", "sha256:" + "f" * 64)], "the bell's row, for the deployed one alone")
        self.assertIn("1.29-alpine (" + "b" * 12 + ")", rows[0]["from"])
        self.assertIn("1.29-alpine (" + "f" * 12 + ")", rows[0]["to"])
        self.assertTrue(rows[0]["rebuild"], "the same tag built again is said as a newer build (B27)")
        self.assertEqual(npx.behind_named("nginx-box"), "1.29-alpine", "the Docker row's flag, by the container's name")
        self.assertEqual(npx.behind_named("radarr"), "", "...and nothing for another row")
        # A registry that does not answer keeps the last answer and says why.
        npx.TAGS_URL = f"file://{self.tmp}/nope.json"
        lt = npx.check_image()
        self.assertIn("could not reach the registry", lt["error"])
        self.assertEqual(lt["tag"], "1.29-alpine", "the last answer kept")
        view = npx.view(FakeDevapp({"nginx-vps"}), lambda *a: {})
        self.assertEqual(view["latest"]["tag"], "1.29-alpine")
        self.assertEqual((view["nodes"][0]["image"]["ref"], view["nodes"][0]["behind"]),
                         ("nginx:1.29-alpine@sha256:" + "b" * 64, "1.29-alpine"))

    def test_update_pins_and_rebuilds_and_deploy_pins_a_new_one(self):
        dv, ct, da = FakeDevapp({"nginx-vps"}), FakeContainers(), FakeDevactions()
        self.assertIn("not deployed", npx.update("n2", ct, da, dv)["error"])
        # No check yet: Update reads the registry itself.
        r = npx.update("n1", ct, da, dv)
        self.assertEqual((r["ok"], r["to"], r["job"]), (True, "1.29-alpine", "j-1"), r)
        self.assertIn("image: nginx:1.29-alpine@sha256:" + "b" * 64, ct.written["nginx-vps"])
        self.assertEqual(da.rebuilt, ["nginx-vps"])
        r = npx.update("n1", ct, da, dv)
        self.assertTrue(r.get("same") and "already runs" in r["note"], "nothing to move to is said, not rebuilt")
        self.assertEqual(da.rebuilt, ["nginx-vps"])
        # A new one is pinned to the newest line as it is written.
        class Making(FakeContainers):
            def create_container(self, name, text, env, node="", for_project=""):
                self.written[name] = text
                return {"ok": True}
        mk = Making()
        self.assertEqual(npx.deploy("n2", mk, da, FakeDevapp(set()))["job"], "j-2")
        self.assertIn("image: nginx:1.29-alpine@sha256:" + "b" * 64, mk.written["nginx-box"])

    def test_deploy_takes_the_name_of_an_uninstalled_node_s_nginx(self):
        class Making(FakeContainers):
            def create_container(self, name, text, env, node="", for_project=""):
                self.written[name] = node
                return {"ok": True}
        # n2 "box" was uninstalled with its nginx still recorded; n3 is the
        # machine enrolled again under the same name (B204).
        self.nodes[1]["state"] = "retired"
        self.nodes.append({"id": "n3", "name": "box", "kind": "agent", "state": "online"})
        npx.node_name = lambda nid: {"n1": "vps", "n2": "box", "n3": "box"}.get(nid, nid)
        dv, mk = FakeDevapp({"nginx-vps", "nginx-box"}), Making()
        self.assertEqual(npx.deploy("n3", mk, FakeDevactions(), dv)["job"], "j-1")
        self.assertEqual(mk.written, {"nginx-box": "n3"})
        # One whose node is still enrolled keeps its name.
        self.nodes[1]["state"] = "offline"
        self.assertIn("already on the Containers page", npx.deploy("n3", Making(), FakeDevactions(), FakeDevapp({"nginx-box"}))["error"])


class DaemonMemo(unittest.TestCase):
    """The two daemon reads per row are kept DAEMON_TTL seconds (B717): a
    tab polling every few seconds paid a probe job per node per poll."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.asked = []
        npx.configure(state=self.tmp, write_json=write_json,
                      node_list=lambda: [{"id": "n1", "name": "vps", "kind": "agent", "state": "online"}],
                      node_name=lambda nid: "vps", taken_ports=lambda *a: self.asked.append("ports") or ["80 (web)"])
        npx._daemon_memo.clear()
        self.dv = FakeDevapp({"nginx-vps"})
        self.dv.on_node = lambda nid: contextlib.nullcontext()
        self.dv.job_rev = lambda: self.jrev
        self.jrev = "1"

    def state(self, name, inst):
        self.asked.append("state")
        return {"up": True}

    def test_a_second_view_within_the_ttl_reads_nothing_from_the_daemon(self):
        v1 = npx.view(self.dv, self.state)
        self.assertEqual((v1["nodes"][0]["state"], v1["nodes"][0]["clash"]), ({"up": True}, ["80 (web)"]))
        self.assertEqual(self.asked, ["state", "ports"])
        v2 = npx.view(self.dv, self.state)
        self.assertEqual(self.asked, ["state", "ports"], "the memo answered")
        self.assertEqual(v2["nodes"][0]["clash"], ["80 (web)"])

    def test_a_write_to_the_record_or_a_compose_job_reads_fresh(self):
        npx.view(self.dv, self.state)
        npx.add_hostname("www.example.com")
        npx.view(self.dv, self.state)
        self.assertEqual(self.asked, ["state", "ports", "state", "ports"], "the record moved, so the daemon was asked again")
        self.jrev = "2"
        npx.view(self.dv, self.state)
        self.assertEqual(len(self.asked), 6, "a compose job ended, so the daemon was asked again")
        npx.view(self.dv, self.state)
        self.assertEqual(len(self.asked), 6)

    def test_the_nodes_are_read_at_once(self):
        """Two nodes whose daemons each take half a second: the view waits
        for the slower, not for both (the operator, 18 Oct)."""
        import time
        npx.configure(state=self.tmp, write_json=write_json,
                      node_list=lambda: [{"id": "n1", "name": "vps", "kind": "agent", "state": "online"},
                                         {"id": "n2", "name": "box", "kind": "agent", "state": "online"}],
                      node_name=lambda nid: {"n1": "vps", "n2": "box"}[nid], taken_ports=lambda *a: time.sleep(0.5) or [])
        t0 = time.monotonic()
        v = npx.view(self.dv, lambda *a: time.sleep(0.5) or {"up": True})
        self.assertLess(time.monotonic() - t0, 1.3, "the slower node (1 s), not both added up (1.5 s)")
        self.assertEqual([r["node"] for r in v["nodes"]], ["n1", "n2"], "in the nodes' order")

    def test_the_memo_runs_out(self):
        npx.view(self.dv, self.state)
        with npx._memo_lock:
            exp, key, st, cl = npx._daemon_memo["n1"]
            npx._daemon_memo["n1"] = (0.0, key, st, cl)
        npx.view(self.dv, self.state)
        self.assertEqual(len(self.asked), 4)


if __name__ == "__main__":
    unittest.main()
