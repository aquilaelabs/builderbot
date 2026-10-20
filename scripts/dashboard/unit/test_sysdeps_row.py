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

    def test_a_long_reason_starts_at_a_line_not_mid_word(self):
        # B83: a tool pack's install, as bb-dev-sandbox logged it; the row
        # was cut by characters from the end and began '3pack · * branch'.
        out = "Permission denied: " + "x" * 300
        got = self.why("== bb toolchains install wordy\n"
                       "[builderbot] fetching wordy at 047e27a1b2c3 into /mnt/bbdata/toolchains/n_6d799c7c/wordy\n"
                       "From http://192.168.1.16:3000/labadmin/r3pack\n"
                       " * branch            047e27a1b2c3d4e5f60718293a4b5c6d7e8f9012 -> FETCH_HEAD\n"
                       f"[builderbot] ERROR: wordy installed but /mnt/bbdata/toolchains/n_6d799c7c/wordy/bin/wordy does not run: {out}\n"
                       "[builderbot] WARN: install failed (exit 1); removing the partial /mnt/bbdata/toolchains/n_6d799c7c/wordy\n",
                       name="wordy")
        self.assertTrue(got.startswith("ERROR: wordy installed but"), got[:80])
        self.assertNotIn("FETCH_HEAD", got)
        self.assertTrue(got.endswith("failed on the node"), got[-60:])
        self.assertLessEqual(len(got), 400)
        # ...and one line too long for the row keeps its start, cut at a word.
        got = toolchains._reason(["ERROR: the tool said " + "word " * 120], "install failed on the node")
        self.assertTrue(got.startswith("ERROR: the tool said word") and got.endswith("… · install failed on the node"), got)
        self.assertLessEqual(len(got), 400)


if __name__ == "__main__":
    unittest.main()
