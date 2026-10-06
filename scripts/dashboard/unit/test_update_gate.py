"""An agent update waits for its node to go quiet (B516). The agent refuses
a self-update while another job runs, and a node a session builds and tests
on all day refused every press of Update agent. So while one is queued the
node is handed nothing new, and the update once the node is idle; one that
waited UPDATE_QUIET_S is failed, naming what kept the node busy."""
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class UpdateGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        nodes.configure(state=self.tmp)
        # The controller's own row, made an agent node with room for four, so
        # what holds a job back below is the gate and not a full slot.
        self.n = nodes.LOCAL
        nodes._exec("UPDATE nodes SET kind = 'agent', concurrency = 4 WHERE id = ?", (self.n,))

    def job(self, jid, type, state="queued", node=None, ago=0):
        nodes._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source, spec, outputs, "
                    "state, node, queued) VALUES (?, ?, '', 'test', '{}', '{}', '{}', '[]', ?, ?, ?)",
                    (jid, type, state, self.n if node is None else node, int(time.time()) - ago))

    def state(self, jid):
        return nodes._rows("SELECT state, error FROM jobs WHERE id = ?", (jid,))[0]

    def test_a_quiet_node_takes_its_update(self):
        self.job("u1", "self-update")
        got = nodes.job_next(self.n, 0)
        self.assertEqual((got["id"], got["state"]), ("u1", "assigned"))

    def test_a_busy_node_takes_work_when_no_update_waits(self):
        self.job("r1", "build", state="running")
        self.job("q1", "build", node="")
        self.assertEqual(nodes.job_next(self.n, 0)["id"], "q1")

    def test_a_busy_node_is_handed_nothing_while_the_update_waits(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update")
        self.job("q1", "build", node="")
        self.assertIsNone(nodes.job_next(self.n, 0))
        self.assertEqual(self.state("u1")["state"], "queued")
        self.assertEqual(self.state("q1")["state"], "queued")
        nodes._exec("UPDATE jobs SET state = 'succeeded' WHERE id = 'r1'")
        got = nodes.job_next(self.n, 0)
        self.assertEqual(got["id"], "u1", "the update goes first once the node is quiet")

    def test_an_update_that_never_found_the_node_quiet_fails_saying_why(self):
        self.job("r1", "build", state="running")
        self.job("r2", "test", state="assigned")
        self.job("u1", "self-update", ago=nodes.UPDATE_QUIET_S + 5)
        nodes.job_next(self.n, 0)
        got = self.state("u1")
        self.assertEqual(got["state"], "failed")
        self.assertIn("never went quiet", got["error"])
        self.assertIn("1 build", got["error"])
        self.assertIn("1 test", got["error"])

    def test_another_nodes_update_holds_nothing_here(self):
        self.job("u1", "self-update", node="elsewhere")
        self.assertIsNone(nodes._update_gate(self.n))

    def test_the_controllers_own_runner_is_not_gated(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update", ago=nodes.UPDATE_QUIET_S + 5)
        # runner="controller" never consults the gate: an agent's update is
        # not its to hand over or to fail.
        nodes.job_next(self.n, 0, runner="controller")
        self.assertEqual(self.state("u1")["state"], "queued")

    def test_the_row_knows_which_jobs_run_and_which_wait(self):
        self.job("r1", "build", state="running")
        self.job("u1", "self-update")
        row = next(r for r in nodes.node_list() if r["id"] == self.n)
        self.assertEqual(sorted((j["type"], j["state"]) for j in row["jobs"]),
                         [("build", "running"), ("self-update", "queued")])


class HeldJobs(unittest.TestCase):
    """The agent counts a job until the controller takes its end, and posts
    its log before its end. A job this side dropped had every log post
    refused, so the agent held it forever and refused every update as busy
    (B519)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        nodes.configure(state=self.tmp)
        self.n = nodes.LOCAL
        nodes._exec("UPDATE nodes SET kind = 'agent' WHERE id = ?", (self.n,))

    def job(self, jid, type, state="queued"):
        nodes._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source, spec, outputs, "
                    "state, node, queued) VALUES (?, ?, '', 'test', '{}', '{}', '{}', '[]', ?, ?, ?)",
                    (jid, type, state, self.n, int(time.time())))

    def test_a_log_for_a_job_with_no_row_is_taken_and_the_job_told_to_stop(self):
        got = nodes.job_log(self.n, "j_gone", [{"seq": 1, "chunk": "x"}])
        self.assertTrue(got.get("ok") and got.get("cancel"), got)
        self.assertEqual(nodes._rows("SELECT COUNT(*) AS n FROM job_logs WHERE job_id = 'j_gone'")[0]["n"], 0)

    def test_another_nodes_job_is_still_refused(self):
        self.job("j_x", "exec", state="running")
        nodes._exec("UPDATE jobs SET node = 'elsewhere' WHERE id = 'j_x'")
        self.assertIn("error", nodes.job_log(self.n, "j_x", []))

    def test_the_hello_keeps_what_the_agent_holds_that_this_side_finished(self):
        self.job("j_run", "exec", state="running")
        self.job("j_done", "exec", state="succeeded")
        self.assertEqual(nodes.jobs_held(self.n, ["j_run", "j_done", "j_gone"]), ["j_done", "j_gone"])

    def test_the_update_handed_over_carries_what_this_side_settled(self):
        nodes._exec("UPDATE nodes SET agent = ?, concurrency = 4 WHERE id = ?", ('{"held": ["j_gone"]}', self.n))
        self.job("u1", "self-update")
        nodes._exec("UPDATE jobs SET node = ? WHERE id = 'u1'", (self.n,))
        got = nodes.job_next(self.n, 0)
        self.assertEqual(got["spec"].get("settled"), ["j_gone"])

    def test_an_update_refused_as_busy_names_them(self):
        self.job("u1", "self-update", state="assigned")
        nodes._exec("UPDATE nodes SET agent = ? WHERE id = ?", ('{"held": ["j_gone"]}', self.n))
        nodes.job_result(self.n, "u1", "failed", 75, "exit 75")
        err = nodes._rows("SELECT error FROM jobs WHERE id = 'u1'")[0]["error"]
        self.assertIn("j_gone", err)
        self.assertIn("press Update agent again", err)


_spec = importlib.util.spec_from_file_location(
    "builderbot_agent_held", os.path.join(os.path.dirname(__file__), "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)
agent.log = lambda *a, **k: None


class AgentFlush(unittest.TestCase):
    """The agent's half: a log refused for good is dropped, so the job's end
    is posted and the job leaves the count; one that failed on the way is
    kept and tried again."""

    def flush(self, status):
        class Ctl:
            def call(self, verb, body=None, timeout=30):
                return status, {"error": "not this node's job"} if status != 200 else {"ok": True}
        class Agent:
            ctl = Ctl()
        j = agent.Job(Agent(), {"id": "j_gone"})
        j.say("a line\n")
        return j.flush(), j.pending

    def test_a_refused_log_is_dropped(self):
        self.assertEqual(self.flush(400), (True, []))

    def test_a_post_is_kept_under_the_controllers_cap(self):
        # B520: 40 kB of batch and then a whole 32 kB chunk went over 64 kB.
        sent = []
        class Ctl:
            def call(self, verb, body=None, timeout=30):
                sent.append(len(agent.json.dumps(body)))
                return 200, {"ok": True}
        class Agent:
            ctl = Ctl()
        j = agent.Job(Agent(), {"id": "j_big"})
        j.say("A" * 39 * 1024)
        j.say("B" * 32 * 1024)
        j.say("\u00e9" * 8 * 1024)
        self.assertTrue(j.flush())
        self.assertLessEqual(max(sent), 64 * 1024, sent)
        # The controller's cap, read from its source: importing server.py
        # opens /config.
        import ast
        src = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], "id", "") == "MAX_BODY_FOR")
        caps = eval(compile(ast.Expression(node.value), "server.py", "eval"))  # noqa: S307 (our own constant)
        self.assertGreaterEqual(caps["/api/v1/agent/log"], 6 * 72 * 1024,
                                "the controller takes the largest post the agent can make")

    def test_an_update_does_not_count_what_the_controller_settled(self):
        class Agent:
            controller_digest = ""
        a = agent.Agent.__new__(agent.Agent)
        a.lock, a.jobs = agent.threading.Lock(), {"j_self": 1, "j_cdcb12b7": 1, "j_live": 1}
        a.ctl = type("Ctl", (), {"call": lambda *x, **k: (503, b"")})()
        a.controller_digest = ""
        class J:
            job = {"id": "j_self"}
            lines = []
            def say(self, t): self.lines.append(t)
        j = J()
        self.assertEqual(a.self_update(j, {"settled": ["j_cdcb12b7"]}), ("failed", 75))
        self.assertIn("j_live", j.lines[-1])
        self.assertNotIn("j_cdcb12b7", j.lines[-1])
        a.jobs.pop("j_live")
        # Past the busy check: the download is the next step, refused here.
        self.assertEqual(a.self_update(j, {"settled": ["j_cdcb12b7"]}), ("failed", 69))

    def test_a_log_that_did_not_arrive_is_kept(self):
        done, pending = self.flush(502)
        self.assertFalse(done)
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
