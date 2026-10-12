"""Each node keeps its own toolchains (R196, the operator, 12 Oct): the
agent's directory under the toolchain store is its node id, never the
<os>-<arch> one every machine of a platform shared; the census says what is
still in that old one, and what sits at the top of the store; a clean job
takes off only what the controller offered and never the node's own."""
import os
import shutil
import tempfile
import unittest

import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_store")
agent.log = lambda *a, **k: None


class OwnDirectory(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.store, True)
        self.stores = agent.stores if hasattr(agent, "stores") else __import__("builderbot_agent_store.stores", fromlist=["x"])
        self.addCleanup(self.stores._SCOPE.update, name="")
        self.stores._SCOPE.update(name="")

    def test_the_node_id_is_the_directory_and_the_roots_are_reported(self):
        st = self.stores
        os.makedirs(os.path.join(self.store, st.legacy_scope(), "jdk"))
        self.assertEqual(st.tc_scope(), st.legacy_scope(), "the shared one stands in before the id is known")
        self.assertEqual(st.use_scope(self.store, "not an id"), st.legacy_scope(), "only a node id is a directory")
        self.assertEqual(st.use_scope(self.store, "n_9381e721"), "n_9381e721")
        self.assertTrue(os.path.isdir(os.path.join(self.store, "n_9381e721")))
        state = {"stores": {"toolchains": self.store}}
        self.assertEqual(st.tc_root(state), os.path.join(self.store, "n_9381e721"))
        os.makedirs(os.path.join(self.store, "n_9381e721", "go"))
        os.makedirs(os.path.join(self.store, "n_0ldd0ne1"))
        dirs = st.store_dirs(state)
        self.assertEqual(dirs["top"], ["go"], "its own directory's toolchains")
        self.assertNotIn("legacy", dirs, "the shared directory is nobody's business any more")
        self.assertEqual(sorted(dirs["roots"]), sorted([st.legacy_scope(), "n_0ldd0ne1", "n_9381e721"]))


if __name__ == "__main__":
    unittest.main()
