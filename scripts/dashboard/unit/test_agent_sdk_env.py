"""The node agent's sdk_env: a toolchain's layout env is a path under its
directory, set only when it exists, or `=VALUE`, set as given (B548: the
playwright toolchain says PLAYWRIGHT_SKIP_BROWSER_GC=1, so a project's own
Playwright installing into the shared store adds its browsers without
sweeping the store's own)."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "builderbot_agent_env", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
agent.log = lambda *a, **k: None


class SdkEnv(unittest.TestCase):
    def test_a_literal_is_set_and_a_path_only_when_it_is_there(self):
        store = tempfile.mkdtemp()
        os.makedirs(os.path.join(store, "playwright", "node_modules", ".bin"))
        layout = [{"name": "playwright", "dir": "playwright",
                   "bin": ["node_modules/.bin"],
                   "env": {"PLAYWRIGHT_BROWSERS_PATH": "", "NODE_PATH": "node_modules",
                           "PLAYWRIGHT_SKIP_BROWSER_GC": "=1", "NOT_THERE": "missing"}}]
        saved = (agent.tc_root, agent.store_layout)
        self.addCleanup(lambda: (setattr(agent, "tc_root", saved[0]), setattr(agent, "store_layout", saved[1])))
        agent.tc_root = lambda state: store
        agent.store_layout = lambda state: layout
        env = agent.sdk_env({"stores": {}})
        self.assertEqual(env["PLAYWRIGHT_SKIP_BROWSER_GC"], "1")
        self.assertEqual(env["PLAYWRIGHT_BROWSERS_PATH"], os.path.join(store, "playwright"))
        self.assertEqual(env["NODE_PATH"], os.path.join(store, "playwright", "node_modules"))
        self.assertNotIn("NOT_THERE", env)

    def test_the_catalog_tells_playwright_not_to_sweep(self):
        cat = json.load(open(os.path.join(HERE, "..", "..", "..", "config", "toolchains.json")))
        pw = next(t for t in cat["toolchains"] if t["name"] == "playwright")
        self.assertEqual(pw["layout"]["env"]["PLAYWRIGHT_SKIP_BROWSER_GC"], "=1")


if __name__ == "__main__":
    unittest.main()
