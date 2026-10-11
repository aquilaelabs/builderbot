"""bb-session's --cuda word (R102): on or off, a word and its value so the
agent can read a launcher line back and respawn it."""
import importlib.machinery
import importlib.util
import os
import re
import unittest
import agentpkg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


session = load("bb_session", os.path.join(HERE, "..", "..", "..", "nodes", "bb-session"))
agent = agentpkg.load("bb_agent")


class Cuda(unittest.TestCase):
    BASE = ["--project", "p", "--account", "u_1", "--home", "/home/x", "--cwd", "/workspace/p"]

    def test_off_and_on(self):
        self.assertTrue(session.args(self.BASE + ["--cuda", "off"])[0]["no_cuda"])
        self.assertFalse(session.args(self.BASE + ["--cuda", "on"])[0]["no_cuda"])
        self.assertNotIn("no_cuda", session.args(self.BASE)[0])

    def test_anything_else_is_refused(self):
        for bad in (["--cuda", "maybe"], ["--no-cuda"], ["--cuda"]):
            with self.assertRaises(session.Refused):
                session.args(self.BASE + bad)

    def test_a_launcher_line_with_it_is_one_the_agent_respawns(self):
        run = "/home/x/.cache/builderbot/u/u_0000abcd/project/p/claude-run.sh"
        line = (f"sudo -n {agent.SESSION_BIN} enter --project p --account u_0000abcd --home /home/x "
                f"--cwd /workspace/p --cuda off --env /home/x/.cache/e -- {run}")
        self.assertIsNotNone(re.fullmatch(agent.RESPAWNABLE, line))
        # ...and a bare flag with no value would not have been.
        self.assertIsNone(re.fullmatch(agent.RESPAWNABLE, line.replace("--cuda off", "--no-cuda")))


if __name__ == "__main__":
    unittest.main()
