"""A toolchain install asks its source's host first (R82): a machine with
no internet is told in one sentence, naming the host, before anything is
touched."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import sdkmeta  # noqa: E402


class Reach(unittest.TestCase):
    def test_the_source_host_is_the_catalogs(self):
        self.assertEqual(sdkmeta.source_host(sdkmeta.toolchain("node")), "nodejs.org")
        self.assertEqual(sdkmeta.source_host(sdkmeta.toolchain("android:ndk")), "dl.google.com")
        self.assertEqual(sdkmeta.source_host({"source": {"kind": "command"}}), "")

    def test_a_musl_system_takes_the_musl_build_where_there_is_one(self):
        url = {"linux/amd64": "glibc", "linux-musl/amd64": "musl", "linux/arm64": "arm"}
        with mock.patch.object(sdkmeta, "this_platform", return_value="linux/amd64"):
            with mock.patch.object(sdkmeta.glob, "glob", return_value=["/lib/ld-musl-x86_64.so.1"]):
                self.assertEqual(sdkmeta.for_platform(url), "musl")
                self.assertEqual(sdkmeta.for_platform({"linux/amd64": "glibc"}), "glibc")
            with mock.patch.object(sdkmeta.glob, "glob", return_value=[]):
                self.assertEqual(sdkmeta.for_platform(url), "glibc")

    def test_a_name_that_does_not_resolve_is_said(self):
        with mock.patch("socket.getaddrinfo", side_effect=OSError("no")):
            self.assertIn("could not be looked up", sdkmeta.unreachable("nodejs.org"))

    def test_a_host_that_does_not_answer_is_said(self):
        with mock.patch("socket.getaddrinfo", return_value=[]), \
             mock.patch("socket.create_connection", side_effect=OSError(113, "No route to host")):
            self.assertIn("nodejs.org did not answer (No route to host)", sdkmeta.unreachable("nodejs.org"))

    def test_a_host_that_answers_is_nothing(self):
        conn = mock.MagicMock()
        with mock.patch("socket.getaddrinfo", return_value=[]), \
             mock.patch("socket.create_connection", return_value=conn):
            self.assertEqual(sdkmeta.unreachable("nodejs.org"), "")


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# sdk_install itself, under bb's set -e, with the session guard (not what is
# asked here) answered yes: reach answers 1 exactly when it has the sentence,
# and the assignment that took it ended the install there in silence (B144).
RUN = r"""set -euo pipefail
REPO="$1" STORE="$2"
die() { echo "DIE: $*"; exit 3; }
source "$REPO/scripts/lib/sdk.sh"
sdk_operator_only() { :; }
SDK_META="$REPO/scripts/lib/sdkmeta.py"
sdk_root() { echo "$STORE"; }
sdk_install go
echo "went on"
"""


class InstallSays(unittest.TestCase):
    def test_an_install_with_no_internet_says_so_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(REPO, "config", "toolchains.json")) as f:
                text = f.read().replace("go.dev", "nowhere.invalid")
            cat = os.path.join(d, "cat.json")
            with open(cat, "w") as f:
                json.dump(json.loads(text), f)
            r = subprocess.run(["bash", "-c", RUN, "run", REPO, os.path.join(d, "store")],
                               capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, BB_TOOLCHAINS_JSON=cat))
            said = r.stdout + r.stderr
            self.assertEqual(r.returncode, 3, said)
            self.assertIn("go cannot be installed here: nowhere.invalid could not be looked up", said)
            self.assertFalse(os.path.exists(os.path.join(d, "store", "go")))

if __name__ == "__main__":
    unittest.main()
