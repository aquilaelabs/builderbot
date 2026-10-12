"""A toolchain batch from a fresh store (the operator, 12 Oct): every name
runs, the tab counts through the batch, a meter is its last frame in the
log, and a JDK written with its build is the release that is installed."""
import os
import subprocess
import sys
import unittest

import agentpkg  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

agent = agentpkg.load("builderbot_agent_batch")
agent.log = lambda *a, **k: None
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


class LastFrame(unittest.TestCase):
    def test_a_meter_is_the_frame_it_ended_on(self):
        f = agent._last_frame
        self.assertEqual(f("[=   ] 3% Unzipping a\r[==  ] 50% Unzipping b\r[====] 100% Unzipping c\r\n"),
                         "[====] 100% Unzipping c\n")
        self.assertEqual(f("plain line\n"), "plain line\n")
        self.assertEqual(f("Loading...   \r"), "Loading...")


class Progress(unittest.TestCase):
    def test_the_count_moves_with_the_step(self):
        names = ["dotnet", "jdk", "android-tools", "android:platforms"]

        class Nodes:
            LOCAL = "local"

            @staticmethod
            def node(nid):
                return {"id": "n1", "name": "box", "kind": "agent", "state": "online", "live": True,
                        "reported": {"os": "linux x86_64", "store_dirs": {"top": [], "android": []},
                                     "stores": {"toolchains": {"path": "/s", "scope": "n1"}}}}

            @staticmethod
            def jobs_for(node_id=None, type=None, n=50, active=False, **k):
                return [{"id": "j1", "state": "running", "step": "android-tools",
                         "spec": {"action": "install", "names": names}}] if active else []

            @staticmethod
            def job_tail(jid, n=4000):
                return ""

            def __getattr__(self, name):
                return lambda *a, **k: None
        was = toolchains.nodes
        toolchains.nodes = Nodes()
        try:
            job = toolchains.payload_for_node("n1")["job"]
        finally:
            toolchains.nodes = was
        self.assertEqual(job["passed"], ["dotnet", "jdk"])
        self.assertEqual(job["queue"], ["android:platforms"])
        self.assertEqual(job["current"], "android-tools")


class NoCut(unittest.TestCase):
    def test_the_cap_is_a_refusal_and_well_above_the_catalog(self):
        self.assertGreater(agent.TC_NAMES_MAX, len(toolchains.TOOLCHAINS or range(40)))
        src = open(os.path.join(REPO, "scripts", "agent", "builderbot_agent", "work.py")).read()
        self.assertNotIn('(spec.get("names") or [])][:', src, "no batch is cut short without a word")


class SameRelease(unittest.TestCase):
    def test_a_build_suffix_is_the_same_release(self):
        sh = ('inst=21.0.12.1; latest=21.0.12.1+1; '
              'if [ "${inst%%+*}" = "${latest%%+*}" ]; then echo current; else echo update; fi')
        self.assertEqual(subprocess.run(["bash", "-c", sh], capture_output=True, text=True).stdout.strip(), "current")
        src = open(os.path.join(REPO, "scripts", "lib", "sdk.sh")).read()
        self.assertIn('[ "${inst%%+*}" = "${latest%%+*}" ]', src, "the check compares the release, not the build")


if __name__ == "__main__":
    unittest.main()
