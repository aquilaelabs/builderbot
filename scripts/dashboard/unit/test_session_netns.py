"""bb-session's network for a session (R79, B325): the veth's far end is put
in the session's namespace by the namespace's file, never by the init's
pid, which the ip that bb-session runs (inside the PID namespace it
unshared) cannot see."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


session = load("bb_session_netns", os.path.join(ROOT, "nodes", "bb-session"))


class Netns(unittest.TestCase):
    def test_the_far_end_goes_in_by_the_namespace_file(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        dfd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, dfd)
        calls = []
        with mock.patch.object(session, "_ip", lambda *a: calls.append(a)), \
                mock.patch.object(session, "_sysctl", lambda *a: None), \
                mock.patch.object(session.os.path, "exists", lambda p: False):
            session.net_attach({"slots": 4, "base": (10 << 24) | (231 << 16)}, 4242, "proj", dfd)
        add = next(c for c in calls if c[:2] == ("link", "add"))
        self.assertEqual(add[-2:], ("netns", "/proc/4242/ns/net"))


if __name__ == "__main__":
    unittest.main()
