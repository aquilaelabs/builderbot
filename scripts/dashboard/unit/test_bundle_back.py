"""The bundle comes back by itself when it is gone from the toolchain store
while sessions run (the operator, 12 Oct: the store emptied by hand, and
"no bundle bb at .../.bb/current/scripts/bb, so no idle session's token is
refreshed" until the next job or session start fetched it)."""
import os
import shutil
import tempfile
import unittest

import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_bundle_back")
agent.log = lambda *a, **k: None


class BundleBack(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.store, True)
        self.fetched = []
        test = self

        class Fake(agent.SessionsMixin):
            state = {"stores": {"toolchains": self.store}}
            ttyd = ["running"]
            session_bundle = "sha256:same"

            def session_account(self):
                return ""

            def bundle(self, job, who):
                test.fetched.append(who)
                d = os.path.join(test.store, ".bb", "current", "scripts")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "bb"), "w") as f:
                    f.write("#!/bin/sh\n")
                os.chmod(os.path.join(d, "bb"), 0o755)
                return d

            def session_start(self, into):
                raise AssertionError("nothing restarts for the same digest")
        agent.tc_root = lambda state: state["stores"]["toolchains"]
        self.a = Fake()

    def test_fetched_when_gone_and_left_alone_when_there(self):
        self.a.session_refresh("sha256:same")
        self.assertEqual(len(self.fetched), 1, "gone from the store: fetched again")
        self.a._bundle_back_at = 0
        self.a.session_refresh("sha256:same")
        self.assertEqual(len(self.fetched), 1, "there: not fetched")

    def test_once_a_minute_at_most_while_it_will_not_come(self):
        self.a.bundle = lambda job, who: self.fetched.append(who) or ""
        self.a.session_refresh("sha256:same")
        self.a.session_refresh("sha256:same")
        self.assertEqual(len(self.fetched), 1)


if __name__ == "__main__":
    unittest.main()
