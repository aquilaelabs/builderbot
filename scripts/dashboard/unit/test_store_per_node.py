"""Each node keeps its own toolchains (R196, the operator, 12 Oct): the
agent's directory under the toolchain store is its node id, and an agent
with no id has none; the census says what sits at the top of the store."""
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
        state = {"stores": {"toolchains": self.store}}
        self.assertEqual(st.tc_root(state), "", "no id, no toolchain directory")
        self.assertEqual(st.use_scope(self.store, "not an id"), "", "only a node id is a directory")
        self.assertEqual(st.use_scope(self.store, "n_9381e721"), "n_9381e721")
        self.assertTrue(os.path.isdir(os.path.join(self.store, "n_9381e721")))
        self.assertEqual(st.tc_root(state), os.path.join(self.store, "n_9381e721"))
        os.makedirs(os.path.join(self.store, "n_9381e721", "go"))
        os.makedirs(os.path.join(self.store, "n_0ldd0ne1"))
        os.makedirs(os.path.join(self.store, "shared"))
        dirs = st.store_dirs(state)
        self.assertEqual(dirs["top"], ["go"], "its own directory's toolchains")
        self.assertEqual(sorted(dirs["roots"]), ["n_0ldd0ne1", "n_9381e721", "shared"])


if __name__ == "__main__":
    unittest.main()
