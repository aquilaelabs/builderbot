"""Copilot CLI's sign-in sealed with the others (R126 step 3): its config,
which holds the token beside its settings, is sealed whole, the seal's
header names the GitHub login, and the Installed page reads the login from
the header while the copy is shut, in either seal format (B407)."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "agent"))
from builderbot_agent import tokens  # noqa: E402

spec = importlib.util.spec_from_file_location("loginlist", HERE.parent / "lib" / "login-list.py")
loginlist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loginlist)


class CopilotSeal(unittest.TestCase):
    def test_the_config_is_one_of_the_files_sealed_and_its_header_names_the_login(self):
        self.assertIn(("copilot", os.path.join(".copilot", "config.json")), tokens.FILES)
        data = b'// managed by Copilot CLI\n// do not edit\n{"lastLoggedInUser": {"login": "octocat"}, "token": "gho_x"}'
        self.assertEqual(tokens.about("copilot", data, "/nowhere"), {"agent": "copilot", "email": "octocat"})
        self.assertEqual(tokens.about("copilot", b"not json", "/nowhere"), {"agent": "copilot"})

    def test_the_login_list_reads_a_shut_seal_s_header_in_either_format(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        home = os.path.join(tmp, "users", "u_12345678")
        os.makedirs(home)
        saved = loginlist.SEAL_DIR
        loginlist.SEAL_DIR = os.path.join(tmp, "seals")
        self.addCleanup(setattr, loginlist, "SEAL_DIR", saved)
        os.makedirs(os.path.join(loginlist.SEAL_DIR, "u_12345678"))
        for magic in (b"BBTOK2\n", b"BBTOK1\n"):
            with open(os.path.join(loginlist.SEAL_DIR, "u_12345678", "copilot.seal"), "wb") as f:
                f.write(magic + json.dumps({"agent": "copilot", "email": "octocat"}).encode() + b"\nsealedbytes")
            self.assertEqual(loginlist.copilot_of(home), {"email": "octocat", "plan": ""}, magic)
        # A dangling link into the opened copy, the copy shut, is the same: still a sign-in.
        os.makedirs(os.path.join(home, ".copilot"))
        os.symlink("/run/bb-tokens/u_12345678/copilot.json", os.path.join(home, ".copilot", "config.json"))
        self.assertEqual(loginlist.copilot_of(home), {"email": "octocat", "plan": ""})
        os.unlink(os.path.join(loginlist.SEAL_DIR, "u_12345678", "copilot.seal"))
        self.assertIsNone(loginlist.copilot_of(home))


if __name__ == "__main__":
    unittest.main()
