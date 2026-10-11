"""The home tunnel the controller runs itself (tunnel.py, R176): a token
read for its ids and never printed, the process started from the settings
and stopped when they go, and the hostname's record and the tunnel's rules
written through Cloudflare's API."""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402
import tunnel  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, "..", "test", "cloudflared-stub.sh")
ACCOUNT, TUNNEL = "a" * 32, "12345678-1234-1234-1234-123456789abc"
TOKEN = base64.b64encode(json.dumps({"a": ACCOUNT, "t": TUNNEL, "s": "secret"}).encode()).decode()


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


class FakeHTTP:
    """Cloudflare's API as a dict of answers, and what was asked of it."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, req, timeout=30):
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((req.get_method(), req.full_url.replace(tunnel.API, ""), body))
        key = (req.get_method(), req.full_url.replace(tunnel.API, ""))
        result = self.answers.get(key, {"success": True, "result": None})

        class R(io.BytesIO):
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False
        return R(json.dumps(result).encode())


class Tunnel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        settings.configure(write_json=write_json, state=self.tmp)
        tunnel.configure(settings_mod=settings, dash_port=7680)
        self.was = tunnel.BIN
        tunnel.BIN = STUB
        self.addCleanup(setattr, tunnel, "BIN", self.was)
        self.addCleanup(lambda: settings.set_many({"tunnel_token": ""}) and tunnel.apply())

    def test_a_token_reads_as_its_account_and_tunnel_and_nothing_else_is_one(self):
        self.assertEqual(tunnel.decode_token(TOKEN), {"account": ACCOUNT, "tunnel": TUNNEL})
        self.assertEqual(tunnel.decode_token("not a token"), {})
        self.assertEqual(tunnel.decode_token(base64.b64encode(b'{"a": "x"}').decode()), {})

    def test_the_settings_hold_the_secret_and_never_show_it(self):
        self.assertIn("hostname", settings.set_many({"tunnel_host": "not a host"})["error"])
        self.assertEqual(settings.set_many({"tunnel_host": "BB.Example.com", "tunnel_token": TOKEN})["set"],
                         ["tunnel_host", "tunnel_token"])
        eff = settings.effective()
        self.assertEqual((eff["tunnel_host"]["value"], eff["tunnel_token"]["value"], eff["tunnel_token"]["set"]),
                         ("bb.example.com", "", True))
        self.assertEqual(settings.secret("tunnel_token"), TOKEN)
        self.assertNotIn(TOKEN, json.dumps(settings.payload()))

    def test_the_process_follows_the_settings(self):
        settings.set_many({"tunnel_host": "bb.example.com", "tunnel_token": TOKEN})
        st = tunnel.apply()
        self.assertTrue(st["running"] and st["configured"], st)
        for _ in range(50):
            if tunnel.status()["connected"]:
                break
            time.sleep(0.1)
        st = tunnel.status()
        self.assertTrue(st["connected"], st)
        self.assertEqual(st["host"], "bb.example.com")
        self.assertNotIn(TOKEN, json.dumps(st), "the token is nowhere in what the tab reads")
        self.assertEqual(st["ids"], {"account": ACCOUNT, "tunnel": TUNNEL})
        self.assertIs(tunnel.apply()["running"], True, "applied again with the same token, it keeps running")
        settings.set_many({"tunnel_token": ""})
        st = tunnel.apply()
        self.assertFalse(st["running"] or st["configured"], st)

    def test_the_hostname_record_and_the_rules_are_written_through_the_api(self):
        settings.set_many({"tunnel_host": "bb.example.com", "tunnel_token": TOKEN})
        http = FakeHTTP({("GET", "/zones?name=example.com"): {"success": True, "result": [{"id": "z1", "name": "example.com"}]},
                         ("GET", "/zones/z1/dns_records?name=bb.example.com"): {"success": True, "result": []}})
        tunnel.urlopen = http
        self.addCleanup(setattr, tunnel, "urlopen", __import__("urllib.request").request.urlopen)
        r = tunnel.publish("api-tok")
        self.assertTrue(r.get("ok"), r)
        methods = [(m, p) for m, p, _ in http.calls]
        self.assertIn(("POST", "/zones/z1/dns_records"), methods)
        self.assertIn(("PUT", f"/accounts/{ACCOUNT}/cfd_tunnel/{TUNNEL}/configurations"), methods)
        rec = next(b for m, p, b in http.calls if m == "POST")
        self.assertEqual((rec["type"], rec["name"], rec["content"], rec["proxied"]),
                         ("CNAME", "bb.example.com", f"{TUNNEL}.cfargotunnel.com", True))
        cfg = next(b for m, p, b in http.calls if m == "PUT")
        self.assertEqual(cfg["config"]["ingress"][0],
                         {"hostname": "bb.example.com", "path": "^/api/v1/agent/", "service": "http://localhost:7680"})
        self.assertEqual(cfg["config"]["ingress"][1:], [{"hostname": "bb.example.com", "service": "http_status:404"},
                                                        {"service": "http_status:404"}])
        self.assertEqual(len(r["did"]), 2)
        # A name that already has an address record is not taken over.
        http.answers[("GET", "/zones/z1/dns_records?name=bb.example.com")] = {
            "success": True, "result": [{"id": "r1", "type": "A", "content": "1.2.3.4"}]}
        self.assertIn("already has an address record", tunnel.publish("api-tok")["error"])


if __name__ == "__main__":
    unittest.main()


class RouteCheck(unittest.TestCase):
    """Registered is not routed (the operator, 11 Oct): the name is asked,
    and only this controller's own answer reads as reaching it."""
    def answer(self, code, ctype, body):
        import email.message
        import urllib.error

        def fake(req, timeout=15):
            self.asked = req.full_url
            h = email.message.Message()
            if ctype:
                h["Content-Type"] = ctype
            if code >= 400:
                raise urllib.error.HTTPError(req.full_url, code, "x", h, io.BytesIO(body))

            class R(io.BytesIO):
                status, headers = code, h

                def __enter__(self_):
                    return self_

                def __exit__(self_, *a):
                    return False
            return R(body)
        was = tunnel.urlopen
        tunnel.urlopen = fake
        self.addCleanup(setattr, tunnel, "urlopen", was)

    def test_this_controllers_answer_reaches_it(self):
        self.answer(405, "application/json", b'{"error": "POST"}')
        self.assertEqual(tunnel.route_check("bb.example.com"), (True, ""))
        self.assertEqual(self.asked, "https://bb.example.com/api/v1/agent/route-check")

    def test_an_empty_200_is_somebody_else(self):
        self.answer(200, "", b"")
        ok, said = tunnel.route_check("bb.example.com")
        self.assertFalse(ok)
        self.assertIn("answers 200 on the agent's API with nothing", said)
        self.assertIn("HTTP localhost:", said)

    def test_a_page_is_somebody_else_too(self):
        self.answer(404, "text/html", b"<html>not found</html>")
        self.assertFalse(tunnel.route_check("bb.example.com")[0])
