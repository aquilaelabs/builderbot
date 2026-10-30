"""The Windows companion's project list says a project's lock as the device
door reports it (R128): nothing when it is not locked, locked when the lock
leaves this account in, locked against you when it holds this account out."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "apps", "windows"))
from bbcompanion import core  # noqa: E402


class LockWord(unittest.TestCase):
    def test_a_lock_is_said_by_whom_it_holds(self):
        self.assertEqual(core.lock_word({"locked": False, "locked_why": ""}), "")
        self.assertEqual(core.lock_word({}), "")
        self.assertEqual(core.lock_word(None), "")
        self.assertEqual(core.lock_word({"locked": True, "locked_why": ""}), ", locked")
        self.assertEqual(core.lock_word({"locked": True, "locked_why": "alpha is locked by own"}), ", locked against you")


if __name__ == "__main__":
    unittest.main()
