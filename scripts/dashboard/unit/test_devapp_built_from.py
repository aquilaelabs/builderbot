"""What bb devapp says a build was made from (B735): a commit, or for a
container written here, which has no repository, its definition hashed,
said as that rather than as a hash a session takes for a commit and cannot
find."""
import importlib.util
import os
import sys
import unittest

LIB = os.path.join(os.path.dirname(__file__), "..", "..", "lib")
sys.path.insert(0, LIB)
spec = importlib.util.spec_from_file_location("devapp_verbs", os.path.join(LIB, "devapp-verbs.py"))
assert spec and spec.loader
verbs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verbs)


class BuiltFrom(unittest.TestCase):
    def test_a_project_build_is_a_commit_with_its_branch(self):
        self.assertEqual(verbs.built_from({"built_rev": "921f1b2"}), "commit 921f1b2")
        self.assertEqual(verbs.built_from({"built_rev": "921f1b2", "built_ref": "site"}), "commit 921f1b2 on site")

    def test_a_written_container_says_it_is_its_definition(self):
        said = verbs.built_from({"built_rev": "d6bc34e", "written": True})
        self.assertTrue(said.startswith("its definition d6bc34e"), said)
        self.assertNotIn("commit", said)


if __name__ == "__main__":
    unittest.main()
