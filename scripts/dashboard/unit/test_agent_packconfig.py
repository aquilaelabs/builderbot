"""The agent's half of a pack's configuration (R172): the hello's rows
written as one env file per pack under the store's .bb/config, readable by
the session account alone, a pack no longer named losing its file, and
nothing rewritten while the rows have not changed."""
import os
import stat
import tempfile
import unittest

import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_packconfig")
agent.log = lambda *a, **k: None


class Fake(agent.PackConfigMixin):
    def session_account(self):
        return "nobody-here"


class Written(unittest.TestCase):
    def test_env_files_written_owned_private_and_removed(self):
        with tempfile.TemporaryDirectory() as store:
            a = Fake()
            rows = [{"pack": "hexkit", "store": store, "values": {}, "env": {"HEX_KEY": "k1", "HEX_VERBOSE": "1", "bad name": "x", "HEX_LINE": "a\nb"}},
                    {"pack": "other", "store": store, "env": {"O": "1"}},
                    {"pack": "Bad Name", "store": store, "env": {"X": "1"}},
                    {"pack": "nowhere", "store": "relative", "env": {"X": "1"}}]
            a.pack_config_want(rows)
            d = os.path.join(store, ".bb", "config")
            self.assertEqual(sorted(os.listdir(d)), ["hexkit.env", "other.env"])
            self.assertEqual(open(os.path.join(d, "hexkit.env")).read(), "HEX_KEY=k1\nHEX_VERBOSE=1\n")
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "hexkit.env")).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
            os.utime(os.path.join(d, "hexkit.env"), (1, 1))
            a.pack_config_want(rows)
            self.assertEqual(os.stat(os.path.join(d, "hexkit.env")).st_mtime, 1, "unchanged rows write nothing")
            a.pack_config_want(rows[:1])
            self.assertEqual(sorted(os.listdir(d)), ["hexkit.env"])


if __name__ == "__main__":
    unittest.main()
