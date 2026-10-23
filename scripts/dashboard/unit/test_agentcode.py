"""Codex CLI and Copilot CLI as rows of a node's Toolchains page (R95 step
2): the census's version against the registry's latest, each install its
own job, and the node agent's half run against a stub installer, never a
vendor's."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import agentcode  # noqa: E402
import agents  # noqa: E402
import toolchains  # noqa: E402
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402


def node(codex="codex-cli 0.160.0", copilot="", up=True, **kw):
    return {"id": "n1", "name": "box", "kind": "agent", "live": True,
            "reported": {"sandbox": True, "session": {"up": up, "codex": codex, "copilot": copilot}}} | kw


class Nodes:
    def __init__(self, n):
        self.n, self.added, self.reported = n, [], []

    def node_list(self):
        return [self.n]

    def node(self, nid):
        return self.n

    def jobs_for(self, *a, **k):
        return []

    def job_add(self, principal, where, type_, spec):
        self.added.append((type_, spec))
        return {"ok": True, "job": "j_1"}

    def job(self, jid, with_log=False):
        return {"log": self.log}

    def reported_set(self, nid, half, key, value):
        self.reported.append((nid, half, key, value))


class Controller(unittest.TestCase):
    def setUp(self):
        self.was = (agentcode.nodes, agentcode.node_sessions, agentcode.tmux_base,
                    toolchains.agentcode, json.dumps(agentcode._latest))
        self.addCleanup(self.restore)
        agentcode._latest.clear()
        agentcode._latest["codex"] = {"version": "0.163.0", "at": 1, "error": "", "checking": False}

    def restore(self):
        agentcode.nodes, agentcode.node_sessions, agentcode.tmux_base, toolchains.agentcode, latest = self.was
        agentcode._latest.clear()
        agentcode._latest.update(json.loads(latest))

    def use(self, n):
        agentcode.nodes = Nodes(n)
        agentcode.node_sessions = lambda: []
        agentcode.tmux_base = lambda s: s
        return agentcode.nodes

    def test_codex_and_copilot_are_tracked_and_claude_is_not(self):
        self.assertEqual([a.id for a in agentcode.tracked()], ["codex", "copilot"])

    def test_the_version_is_read_out_of_what_each_prints(self):
        n = node(codex="codex-cli 0.163.0", copilot="GitHub Copilot CLI 1.0.102.")
        self.assertEqual(agentcode.installed(n, "codex"), "0.163.0")
        self.assertEqual(agentcode.installed(n, "copilot"), "1.0.102")

    def test_a_node_behind_has_a_row_offering_the_update(self):
        self.use(node())
        r = agentcode.row(node(), "codex")
        self.assertEqual((r["name"], r["label"], r["installed"], r["latest"], r["state"]),
                         ("codex-cli", "Codex CLI", "0.160.0", "0.163.0", "update"))
        self.assertEqual(agentcode.row(node(), "copilot")["state"], "absent")

    def test_no_session_account_no_row(self):
        self.use(node(up=False))
        self.assertIsNone(agentcode.row(node(up=False), "codex"))

    def test_the_latest_is_the_registry_s_version(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"name": "@openai/codex", "version": "0.170.1"}, f)
        self.addCleanup(os.unlink, f.name)
        with mock.patch.dict(os.environ, {"BB_CODEX_LATEST_URL": "file://" + f.name}):
            self.assertEqual(agentcode.check("codex")["version"], "0.170.1")

    def test_an_install_queues_the_table_s_job_for_the_latest(self):
        ns = self.use(node())
        r = agentcode.update("user:admin", "n1", "codex")
        self.assertTrue(r["ok"])
        self.assertEqual(ns.added, [("codex-update", {"timeout": 900, "to": "0.163.0", "ended": []})])

    def test_an_update_holds_that_agents_starts_as_claude_codes_does(self):
        ns = self.use(node())
        self.assertEqual(agentcode.start_hold("alpha", "n1", "codex"), "")
        ns.jobs_for = lambda *a, **k: [{"type": "codex-update"}] if k.get("type") == "codex-update" else []
        self.assertIn("is updating", agentcode.start_hold("alpha", "n1", "codex"))
        self.assertEqual(agentcode.start_hold("alpha", "n1", "copilot"), "")

    def test_a_removal_needs_it_installed(self):
        self.use(node(codex=""))
        self.assertIn("not installed", agentcode.remove("user:admin", "n1", "codex")["error"])

    def test_claude_is_not_this_module_s(self):
        self.use(node())
        with self.assertRaises(KeyError):
            agentcode.update("user:admin", "n1", "claude")

    def test_the_census_catches_up_when_the_job_ends(self):
        ns = self.use(node())
        ns.log = "installing\nCodex CLI 0.163.0 is what a session here runs now\n"
        agentcode.update_done({"id": "j_1", "type": "codex-update", "node": "n1", "spec": {}}, "succeeded")
        self.assertEqual(ns.reported, [("n1", "session", "codex", "0.163.0")])

    def test_the_toolchains_page_draws_both_beside_claude(self):
        self.use(node())
        toolchains.agentcode = agentcode
        names = [agentcode.row(node(), a.id)["name"] for a in agentcode.tracked()]
        self.assertEqual(names, [a.tool for a in agents.installable() if a.id != "claude"])


class NodeAgent(unittest.TestCase):
    """The node's half: AGENT_INSTALLS's row for the job, the installer run
    with the version pinned, the binary's version read back."""

    def setUp(self):
        self.mod = agentpkg.load("agentinstall")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        # The node's own agents folder is read first: on a node that carries
        # a real Codex the census found that one and not the stub (B251).
        self.mod.AGENTS_DIR = os.path.join(self.tmp.name, "agents")
        self.stub = os.path.join(self.tmp.name, "installer.sh")
        with open(self.stub, "w") as f:
            f.write('mkdir -p "$CODEX_INSTALL_DIR"\n'
                    'printf "#!/bin/sh\\necho codex-cli ${CODEX_RELEASE:-0.0.0}\\n" > "$CODEX_INSTALL_DIR/codex"\n'
                    'chmod +x "$CODEX_INSTALL_DIR/codex"\necho "stub installed $CODEX_RELEASE"\n')

    def run_job(self, spec, type_="codex-update"):
        said = []
        job = type("J", (), {})()
        job.job = {"type": type_}
        job.say = said.append
        job.pending = False
        job.proc = None
        job.flush = lambda: None
        job.cancel = lambda: None
        fake = type("A", (), {})()
        fake.state = {}
        fake.session_account = lambda: "builder"
        fake.as_user = lambda env, who: {}
        fake.session_renew = lambda: None
        fake.hello_again = lambda why: None
        env = {"BUILDERBOT_CODEX_INSTALLER": self.stub, "HOME": self.home}
        with mock.patch.dict(os.environ, env), \
                mock.patch("os.path.expanduser", return_value=self.home), \
                mock.patch("os.geteuid", return_value=1000):
            for m in self.mod._mods:
                if "sdk_env" in vars(m):
                    vars(m)["sdk_env"] = lambda state: {"HOME": self.home, "PATH": "/usr/bin:/bin"}
            got = self.mod.Agent.agent_update(fake, job, spec)
        return got, "".join(said)

    def test_the_installer_runs_with_the_version_and_the_binary_is_read_back(self):
        got, log = self.run_job({"to": "0.163.0"})
        self.assertEqual(got, ("succeeded", 0), log)
        self.assertIn("stub installed 0.163.0", log)
        self.assertIn("Codex CLI 0.163.0 is what a session here runs now", log)

    def test_a_job_the_table_does_not_name_is_refused(self):
        got, log = self.run_job({}, type_="exec")
        self.assertEqual(got, ("failed", 78))
        self.assertIn("no coding agent", log)

    def test_a_removal_takes_the_account_s_copy_off(self):
        self.run_job({"to": "0.163.0"})
        got, log = self.run_job({"action": "remove"})
        self.assertEqual(got, ("succeeded", 0))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "codex")))

    def test_the_census_reads_each_agent_under_its_key(self):
        self.run_job({"to": "0.163.0"})
        with mock.patch.dict(os.environ, {}):
            v = self.mod._agent_version(self.mod.AGENT_INSTALLS["codex-update"], self.home)
        self.assertEqual(v, "codex-cli 0.163.0")
        self.assertEqual(self.mod._agent_version(self.mod.AGENT_INSTALLS["copilot-update"], self.home), "")

    def test_the_node_s_table_matches_the_controller_s(self):
        for job, how in self.mod.AGENT_INSTALLS.items():
            a = agents.get(how["id"])
            self.assertEqual((a.update_job, a.command, a.product, a.reported),
                             (job, how["command"], how["product"], how["reported"]))


if __name__ == "__main__":
    unittest.main()
