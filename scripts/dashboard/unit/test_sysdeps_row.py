"""A node's system-packages job on the Toolchains page: whether it worked is
what the census still finds unmet, not whether the recipe is in the store
(it is, before and after), and the reason on the row is the package
manager's, read from the agent's own section of the log."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolchains  # noqa: E402

HERE = {"playwright", "node"}


class Finished(unittest.TestCase):
    def test_a_job_that_worked_is_done(self):
        rep = {"sysdeps": {"family": "dnf", "unmet": {}}}
        self.assertEqual(toolchains.finished("sysdeps", ["playwright"], HERE, rep, "succeeded"),
                         (["playwright"], []))

    def test_what_is_still_unmet_failed(self):
        rep = {"sysdeps": {"family": "dnf", "unmet": {"playwright": ["libXtst"]}}}
        self.assertEqual(toolchains.finished("sysdeps", ["playwright"], HERE, rep, "failed"),
                         ([], ["playwright"]))

    def test_no_names_is_every_held_recipe(self):
        rep = {"sysdeps": {"unmet": {"dotnet": ["libicu"]}}}
        self.assertEqual(toolchains.finished("sysdeps", [], HERE, rep, "failed"), ([], ["dotnet"]))

    def test_a_failed_job_with_nothing_unmet_still_says_so(self):
        self.assertEqual(toolchains.finished("sysdeps", ["playwright"], HERE, {}, "failed"),
                         ([], ["playwright"]))

    def test_install_and_remove_are_read_from_the_store(self):
        self.assertEqual(toolchains.finished("install", ["node", "go"], HERE, {}, "failed"), (["node"], ["go"]))
        self.assertEqual(toolchains.finished("remove", ["node", "go"], HERE, {}, "failed"), (["go"], ["node"]))


class Reason(unittest.TestCase):
    def why(self, log, name="playwright"):
        class Nodes:
            @staticmethod
            def job_tail(job_id, n=0):
                return log
        was, toolchains.nodes = toolchains.nodes, Nodes
        toolchains._node_errors_seen.clear()
        try:
            return toolchains._node_errors("j_1", [name], "sysdeps")[name]
        finally:
            toolchains.nodes = was

    def test_the_package_managers_own_words(self):
        got = self.why("== system packages for playwright: libXtst google-noto-color-emoji-fonts\n"
                       "Error: Unable to find a match: google-noto-color-emoji-fonts\n"
                       "playwright: its system packages did not install (exit 1)\n1 of 1 did not install\n")
        self.assertIn("Unable to find a match: google-noto-color-emoji-fonts", got)
        self.assertTrue(got.endswith("sysdeps failed on the node"))

    def test_a_refusal_is_the_reason(self):
        got = self.why("refused: this agent does not administer the machine, so its owner installs these: playwright: libXtst\n")
        self.assertIn("does not administer the machine", got)


if __name__ == "__main__":
    unittest.main()
