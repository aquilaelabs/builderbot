"""The key sign-in cookies are signed with (R135): with an install key it is
made from the key and kept nowhere, so a copy of /config forges no sign-in,
and the file an install kept before is removed; without one it is a random
secret kept in /config as before, the same across restarts."""
import ast
import hashlib
import hmac
import os
import shutil
import tempfile
import unittest
from pathlib import Path

SRC = os.path.join(os.path.dirname(__file__), "..", "server.py")


def lift(state, keyfile):
    with open(SRC) as f:
        tree = ast.parse(f.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_session_secret")
    ns = {"STATE": Path(state), "Path": Path, "os": os, "hmac": hmac, "hashlib": hashlib}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), SRC, "exec"), ns)  # noqa: S102 (our own source)  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
    old = os.environ.get("BB_SIGNING_SECRET_FILE")
    os.environ["BB_SIGNING_SECRET_FILE"] = keyfile
    try:
        return ns["_session_secret"]()
    finally:
        if old is None:
            os.environ.pop("BB_SIGNING_SECRET_FILE", None)
        else:
            os.environ["BB_SIGNING_SECRET_FILE"] = old


class CookieSecret(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state, self.key = self.tmp / "config", self.tmp / "key"
        self.state.mkdir()

    def test_without_a_key_it_is_kept_in_config_and_stays(self):
        a = lift(self.state, str(self.key))
        self.assertTrue((self.state / "dashboard-secret").is_file())
        self.assertEqual(lift(self.state, str(self.key)), a)

    def test_with_a_key_it_is_made_from_it_and_kept_nowhere(self):
        lift(self.state, str(self.key))
        self.key.write_text("k" * 32)
        a = lift(self.state, str(self.key))
        self.assertFalse((self.state / "dashboard-secret").exists(), "the file kept before goes")
        self.assertEqual(a, lift(self.state, str(self.key)), "the same across restarts")
        self.key.write_text("j" * 32)
        self.assertNotEqual(a, lift(self.state, str(self.key)), "another key, another secret")
        self.assertEqual(os.listdir(self.state), [], "nothing of it in /config")


if __name__ == "__main__":
    unittest.main()
