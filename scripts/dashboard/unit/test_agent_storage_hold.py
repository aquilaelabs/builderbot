"""A store move holds the node's sessions while it runs (R120 step 7): the
agent writes the hold where every session's gate reads it before the move,
says how far it has got as it goes, and takes it away however the move ends,
from the place it wrote it even when the toolchain store itself moved."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agentpkg  # noqa: E402
agent = agentpkg.load("builderbot_agent_storage_hold")
agent.log = lambda *a, **k: None
agent.mounts_now = lambda: []


class Job:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


class StorageHold(unittest.TestCase):
    def setUp(self):
        self.hold = os.path.join(tempfile.mkdtemp(), "hold.json")
        self.a = object.__new__(agent.Agent)
        self.a.state = {"name": "shed", "stores": {"toolchains": "/old/tc", "cache": "/old/cache"}}
        self.a._hold_file = lambda: self.hold
        self.a.hello = lambda: None

    def apply(self, stores, during):
        self.a._apply_stores = during
        return self.a._apply_storage(Job(), {"mounts": [], "stores": stores})

    def test_a_move_is_held_while_it_runs_and_lifted_after(self):
        seen = {}

        def during(job, stores, cfg):
            with open(self.hold) as f:
                seen.update(json.load(f))
            return 0
        self.assertEqual(self.apply({"toolchains": "/new/tc"}, during), ("succeeded", 0))
        self.assertEqual(seen["node"], "shed")
        self.assertIn("moving its toolchains store", seen["said"])
        self.assertFalse(os.path.exists(self.hold), "lifted once it is done")

    def test_a_move_that_fails_lifts_the_hold_too(self):
        def during(job, stores, cfg):
            raise RuntimeError("the copy blew up")
        with self.assertRaises(RuntimeError):
            self.apply({"toolchains": "/new/tc"}, during)
        self.assertFalse(os.path.exists(self.hold))

    def test_the_hold_is_lifted_where_it_was_written(self):
        # The toolchain store moving repoints the bundle mid-apply; the hold
        # file the sessions read is the one written at the start.
        def during(job, stores, cfg):
            self.a._hold_file = lambda: os.path.join(tempfile.mkdtemp(), "elsewhere.json")
            self.a._hold("moving its toolchains store to /new/tc: 50% copied")
            return 0
        self.apply({"toolchains": "/new/tc"}, during)
        self.assertFalse(os.path.exists(self.hold))

    def test_progress_keeps_when_it_began(self):
        self.a._hold_at = self.hold
        self.a._hold("moving its data store")
        with open(self.hold) as f:
            first = json.load(f)
        self.a._hold("moving its data store to /x: 10% copied")
        with open(self.hold) as f:
            later = json.load(f)
        self.assertEqual(later["since"], first["since"])
        self.assertIn("10% copied", later["said"])

    def test_a_cache_move_or_no_move_holds_nobody(self):
        seen = []

        def during(job, stores, cfg):
            seen.append(os.path.exists(self.hold))
            return 0
        self.apply({"cache": "/new/cache"}, during)
        self.apply({"toolchains": "/old/tc"}, during)
        self.assertEqual(seen, [False, False])


class StoreOnAMount(unittest.TestCase):
    """A store inside a configured mount goes there only when the mount is
    there and is the share it names (the operator, 23 Oct)."""

    def run_apply(self, mount):
        a = object.__new__(agent.Agent)
        a.state = {"name": "shed", "stores": {"artifacts": "/var/lib/builderbot/artifacts"}}
        a.write_session_profile = lambda job: None
        saved = (agent.mounts_now, agent.save_state, os.path.ismount)
        self.addCleanup(lambda: (setattr(agent, "mounts_now", saved[0]), setattr(agent, "save_state", saved[1]),
                                 setattr(os.path, "ismount", saved[2])))
        agent.mounts_now = lambda: [mount]
        agent.save_state = lambda st: None
        os.path.ismount = lambda p: p == mount["path"]
        job = Job()
        bad = a._apply_stores(job, {"artifacts": mount["path"] + "/art"}, {})
        return bad, "".join(job.said), a.state["stores"]["artifacts"]

    def test_a_stale_mount_is_refused(self):
        bad, said, now = self.run_apply({"path": "/srv/share", "source": "nas:/x", "real": "nas:/x",
                                         "mounted": True, "stale": True})
        self.assertEqual(bad, 1)
        self.assertIn("stale", said)
        self.assertEqual(now, "/var/lib/builderbot/artifacts")

    def test_a_mount_from_another_export_is_refused(self):
        bad, said, now = self.run_apply({"path": "/srv/share", "source": "nas:/x", "real": "nas:/old",
                                         "mounted": True})
        self.assertEqual(bad, 1)
        self.assertIn("mounted from nas:/old rather than nas:/x", said)
        self.assertEqual(now, "/var/lib/builderbot/artifacts")


if __name__ == "__main__":
    unittest.main()
