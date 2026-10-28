"""A model router on a node (R144 step 1, router.py): the keys kept sealed,
the compose file with LiteLLM, its database and Ollama, a route per
provider with a key, Deploy and Remove as a written container, a project
allowed with a key of its own made at the router and handed to its
sessions with the router in their network's peers, the models read."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import router     # noqa: E402
import signing    # noqa: E402
import statefile  # noqa: E402

KEY = b"m" * 32


class FakeLiteLLM(BaseHTTPRequestHandler):
    seen = []

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeLiteLLM.seen.append((self.path, self.headers.get("Authorization"), body))
        if self.path == "/key/generate":
            return self._send({"key": "sk-proj-" + body.get("key_alias", "")})
        return self._send({"ok": True})

    def do_GET(self):
        FakeLiteLLM.seen.append((self.path, self.headers.get("Authorization"), None))
        if self.path == "/model/info":
            return self._send({"data": [{"model_name": "anthropic/*", "litellm_params": {"model": "anthropic/*"}, "model_info": {}},
                                        {"model_name": "anthropic/claude-sonnet-5-5", "litellm_params": {"model": "anthropic/claude-sonnet-5-5"},
                                         "model_info": {"max_input_tokens": 200000, "input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05}}]})
        if self.path == "/v1/models":
            return self._send({"data": [{"id": "openai/gpt-6-luna"}]})
        if self.path.startswith("/key/info"):
            return self._send({"info": {"spend": 1.25}})
        return self._send({"error": "no"}, 404)

    def log_message(self, format, *args):
        del format, args


class FakeDevapp:
    MAIN, SYSTEM = "main", "__system"

    def __init__(self):
        self.files = {}

    def is_file_source(self, name):
        return name in self.files

    def _read_rec(self, name, inst):
        return self.files.get(name, {})

    def forget_container(self, name):
        self.files.pop(name, None)


class FakeContainers:
    def __init__(self, devapp):
        self.devapp = devapp
        self.written = {}

    def create_container(self, name, text, env, node="", for_project=""):
        self.written[name] = text
        self.devapp.files[name] = {"node": node, "for": for_project}
        return {"ok": True}

    def update_container(self, name, text, env):
        self.written[name] = text
        return {"ok": True}


class FakeDevactions:
    def __init__(self, devapp):
        self.devapp = devapp
        self.rebuilt = []

    def rebuild(self, name, inst, gate=False):
        self.rebuilt.append(name)
        return {"job": f"j-{len(self.rebuilt)}"}

    def remove_instance(self, name, inst):
        self.devapp.files.pop(name, None)
        return {"ok": True}


class Router(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        FakeLiteLLM.seen = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLiteLLM)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.jobs = []
        router.configure(state=self.tmp, write_json=statefile.write_json, seal=signing.seal, unseal=signing.unseal,
                         sealing=lambda: signing.MASTER is not None,
                         node_list=lambda: [{"id": "n1", "name": "GPU Box", "state": "online"}],
                         node_name=lambda nid: "GPU Box", node_addr=lambda nid: "127.0.0.1",
                         project_names=lambda: ["web", "app"],
                         job_add=lambda principal, pl, typ, spec: (self.jobs.append((typ, spec)) or {"job": f"j{len(self.jobs)}"}),
                         job_get=lambda jid: None)
        self.devapp = FakeDevapp()
        self.containers = FakeContainers(self.devapp)
        self.devactions = FakeDevactions(self.devapp)
        self.port = self.srv.server_port

    def test_the_keys_are_kept_sealed_and_the_compose_routes_each_provider(self):
        r = router.set_keys("n1", {"providers": {"anthropic": "sk-ant-secret", "openai": ""},
                                   "custom": [{"name": "lab", "base": "https://lab.example/v1/", "key": "lab-secret"}], "ollama": True})
        self.assertTrue(r.get("ok"), r)
        raw = open(os.path.join(self.tmp, "router.json")).read()
        self.assertNotIn("sk-ant-secret", raw)
        self.assertNotIn("lab-secret", raw)
        self.assertIn("bbseal:", raw)
        st = router.status("n1")
        self.assertEqual((st["providers"]["anthropic"], st["providers"]["openai"], st["custom"][0]["name"], st["ollama"]["on"]), (True, False, "lab", True))
        rec = router.record("n1")
        rec["port"] = self.port
        text = router.compose_text("n1", rec, gpu=True)
        self.assertIn("ANTHROPIC_API_KEY: \"sk-ant-secret\"", text, "the node's compose carries the key, the controller's record a seal")
        self.assertIn("CUSTOM_0_KEY: \"lab-secret\"", text)
        self.assertIn(f"\"127.0.0.1:{self.port}:4000\"", text, "published on the node's address alone")
        self.assertIn("ollama/ollama", text)
        self.assertIn("driver: nvidia", text)
        conf = router.litellm_config(rec)
        self.assertIn('model_name: "anthropic/*"', conf)
        self.assertNotIn('"openai/*"\n', conf.split("lab/*")[0], "no key, no route")
        self.assertIn('model_name: "lab/*"', conf)
        self.assertIn('api_base: "https://lab.example/v1"', conf)
        self.assertIn('model: "ollama_chat/*"', conf)
        self.assertIn("master_key: os.environ/LITELLM_MASTER_KEY", conf)
        self.assertIn("name is letters", router.set_keys("n1", {"custom": [{"name": "Bad Name", "base": "https://x"}]})["error"])
        r = router.set_keys("n1", {"providers": {"anthropic": "clear"}})
        self.assertFalse(router.status("n1")["providers"]["anthropic"])
        self.assertEqual(router.seal_all(again=True) >= 3, True)

    def test_deploy_allow_and_the_sessions_reach_it(self):
        self.assertIn("nothing behind it", router.deploy("n1", self.containers, self.devactions, self.devapp)["error"])
        router.set_keys("n1", {"providers": {"openai": "sk-x"}})
        with router._lock:
            d = router._load()
            d["n1"]["port"] = self.port
            router._save(d)
        r = router.deploy("n1", self.containers, self.devactions, self.devapp)
        self.assertEqual((r.get("job"), r.get("name")), ("j-1", "router-gpu-box"), r)
        self.assertTrue(router.deployed(self.devapp, "n1"))
        self.assertTrue(router.record("n1")["deployed"])
        self.assertIn("router-gpu-box", self.containers.written)
        # A project allowed: a key of its own from the router, sealed here.
        self.assertIn("no such project", router.allow("n1", "nope")["error"])
        self.assertTrue(router.allow("n1", "web", "ann")["ok"])
        path, auth, body = next(x for x in FakeLiteLLM.seen if x[0] == "/key/generate")
        self.assertTrue(auth.startswith("Bearer sk-"))
        self.assertEqual(body["key_alias"], "builderbot-web")
        self.assertNotIn("sk-proj-builderbot-web", open(os.path.join(self.tmp, "router.json")).read())
        got = router.for_project("web")
        self.assertEqual((got["url"], got["key"], got["node"]), (f"http://127.0.0.1:{self.port}/v1", "sk-proj-builderbot-web", "n1"))
        self.assertEqual(router.for_project("app"), {})
        self.assertEqual(router.peers_for("web"), [("127.0.0.1", self.port)])
        own = router.with_peers({"web": {"compose": set(), "names": set(), "peers": set(), "hosts": set()}})
        self.assertIn(("127.0.0.1", self.port), own["web"]["peers"])
        self.assertIn(("127.0.0.1", self.port), router.with_peers({})["web"]["peers"], "a project with nothing else here still gets the router")
        self.assertNotIn("app", router.with_peers({}))
        # The models with their context and price, the spend by project.
        m = router.refresh_models("n1")
        ids = {x["id"]: x for x in m["models"]}
        self.assertEqual(ids["anthropic/claude-sonnet-5-5"]["context"], 200000)
        self.assertAlmostEqual(ids["anthropic/claude-sonnet-5-5"]["in_cost"], 3e-06)
        self.assertIn("openai/gpt-6-luna", ids)
        self.assertEqual([x["id"] for x in router.models_for("web") if x["wild"]], [])
        self.assertEqual(router.refresh_spend("n1"), {"web": 1.25})
        self.assertEqual(router.spend_for("web"), 1.25)
        self.assertIsNone(router.spend_for("app"))
        # Ollama's models, pulled and removed as exec jobs on the node.
        self.assertIn("not on", router.ollama_pull("n1", "qwen2.5-coder:7b")["error"])
        router.set_keys("n1", {"ollama": True})
        self.assertTrue(router.ollama_pull("n1", "qwen2.5-coder:7b")["job"])
        self.assertEqual(self.jobs[-1][1]["argv"][:4], ["docker", "exec", "router-gpu-box-ollama-1", "ollama"])
        self.assertEqual(router.status("n1")["ollama"]["models"], ["qwen2.5-coder:7b"])
        self.assertIn("ollama/qwen2.5-coder:7b", [x["id"] for x in router.refresh_models("n1")["models"]])
        router.ollama_remove("n1", "qwen2.5-coder:7b")
        self.assertEqual(router.status("n1")["ollama"]["models"], [])
        # Not allowed any more; removed altogether.
        self.assertTrue(router.disallow("n1", "web")["ok"])
        self.assertEqual(router.for_project("web"), {})
        self.assertTrue(router.remove("n1", self.devactions, self.devapp)["ok"])
        self.assertFalse(router.record("n1").get("deployed"))
        self.assertEqual(len(router.at_rest()), 2, "the provider key and the master key, kept")


if __name__ == "__main__":
    unittest.main()
