"""A branch's line (R112, the operator, 22 Oct): the release it works
toward, said with bb version line or read off a branch named for it; a dev
build there heads for it, and its version moves to it and nowhere else."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


class Line(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.p = self.ws / "app"
        self.p.mkdir()
        git("init", "-q", "-b", "main", cwd=self.p)
        (self.p / "VERSION").write_text("0.6.1\n")
        (self.p / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n### Added\n\n- a thing\n")
        git("add", ".", cwd=self.p)
        git("commit", "-qm", "one", cwd=self.p)
        git("tag", "v0.6.1", cwd=self.p)
        git("commit", "-q", "--allow-empty", "-m", "two", cwd=self.p)
        for name, value in (("WORKSPACE", self.ws), ("FILE", self.ws / "versions.json")):
            p = mock.patch.object(version, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.ws)])
        import json
        (self.ws / "versions.json").write_text(json.dumps({"projects": {"app": {"policy": "open"}}}))

    def semver(self):
        return version.render("app")["forms"]["semver"]

    def test_main_has_no_line_and_builds_from_version(self):
        self.assertEqual(version.line("app"), "")
        self.assertTrue(self.semver().startswith("0.6.1-dev."))

    def test_a_branch_named_for_a_release_heads_for_it(self):
        git("checkout", "-q", "-b", "claude/0.7.0", cwd=self.p)
        self.assertEqual(version.line("app"), "0.7.0")
        self.assertTrue(self.semver().startswith("0.7.0-dev."), self.semver())

    def test_set_line_overrides_the_name_and_none_goes_back(self):
        git("checkout", "-q", "-b", "fixes", cwd=self.p)
        self.assertEqual(version.line("app"), "")
        self.assertTrue(version.set_line("app", "v0.6.2").get("ok"))
        self.assertEqual(version.line("app"), "0.6.2")
        self.assertTrue(self.semver().startswith("0.6.2-dev."))
        self.assertIn("not a version", version.set_line("app", "soon")["error"])
        version.set_line("app", "")
        self.assertEqual(version.line("app"), "")

    def test_a_line_older_than_version_is_not_a_target(self):
        git("checkout", "-q", "-b", "old/0.5.9", cwd=self.p)
        self.assertTrue(self.semver().startswith("0.6.1-dev."))

    def test_a_bump_moves_only_to_the_line(self):
        git("checkout", "-q", "-b", "claude/0.6.2", cwd=self.p)
        r = version.bump("app", "minor", by="you")
        self.assertIn("works toward 0.6.2", r.get("error", ""))
        r = version.bump("app", "patch", by="you")
        self.assertNotIn("error", r, r)
        self.assertEqual((self.p / "VERSION").read_text().strip(), "0.6.2")


if __name__ == "__main__":
    unittest.main()
