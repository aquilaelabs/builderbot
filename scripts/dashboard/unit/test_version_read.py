"""A VERSION file the controller could not read was taken as a project that
has not adopted one, and bb version --file then answered with git describe:
Shebang-DevBoard at 0.5.5 was told v0.5.4-13-g7766f70 and filed builds under
it (B524). A failed read falls back to the committed file, and only a file in
neither place is a project with no VERSION."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import version  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


class VersionRead(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        version.configure(workspace=self.ws, state=self.ws / ".state", write_json=lambda *a, **k: None)
        self.p = self.ws / "app"
        self.p.mkdir()
        subprocess.run([*GIT, "init", "-q", str(self.p)], check=True)

    def commit(self, text):
        (self.p / "VERSION").write_text(text)
        subprocess.run([*GIT, "-C", str(self.p), "add", "VERSION"], check=True)
        subprocess.run([*GIT, "-C", str(self.p), "commit", "-qm", "v"], check=True)

    def unreadable(self, err):
        real = Path.read_text

        def read(path, *a, **k):
            if path.name == "VERSION":
                raise err
            return real(path, *a, **k)
        return mock.patch.object(Path, "read_text", read)

    def test_a_read_that_fails_is_answered_from_the_committed_file(self):
        self.commit("0.5.5\n")
        with self.unreadable(OSError(5, "Input/output error")):
            self.assertEqual(version.target("app"), ("0.5.5", None))

    def test_a_read_that_fails_with_nothing_committed_says_so(self):
        (self.p / "VERSION").write_text("0.5.5\n")
        with self.unreadable(OSError(5, "Input/output error")):
            tgt, err = version.target("app")
        self.assertIsNone(tgt)
        self.assertIn("could not be read", err or "")

    def test_no_file_anywhere_is_a_project_that_has_not_opted_in(self):
        self.assertEqual(version.target("app"), (None, None))

    def test_the_file_on_disk_is_still_the_answer_when_it_reads(self):
        self.commit("0.5.5\n")
        (self.p / "VERSION").write_text("0.6.0\n")
        self.assertEqual(version.target("app"), ("0.6.0", None))


if __name__ == "__main__":
    unittest.main()
