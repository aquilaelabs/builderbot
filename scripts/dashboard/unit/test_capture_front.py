"""bb capture shot --emu PKG launches PKG only when it is not on the
screen. An app that is also the keyboard, up over its own setup screen, read
as not in front and the launch took the keyboard down (report #68, B529)."""
import importlib.util
import os
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("capture", os.path.join(HERE, "..", "..", "lib", "capture.py"))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

PKG = "dev.shebang.devboard"


class InFront(unittest.TestCase):
    def ask(self, window="", ime="", act=""):
        def run(argv, timeout=0):
            which = argv[3]
            out = {"window": window, "input_method": ime, "activity": act}[which]
            return types.SimpleNamespace(stdout=out, returncode=0)
        was = capture.run
        capture.run = run
        try:
            return capture.in_front("adb", PKG)
        finally:
            capture.run = was

    def test_its_keyboard_showing_is_in_front(self):
        ime = f"mCurMethodId={PKG}/.ime.DevBoardIme\n  mInputShown=true\n"
        self.assertTrue(self.ask(window="mCurrentFocus=null\n", ime=ime))

    def test_its_activity_resumed_on_top_is_in_front(self):
        act = f"  topResumedActivity=ActivityRecord{{1a2b u0 {PKG}/.settings.SetupActivity t12}}\n"
        self.assertTrue(self.ask(act=act))

    def test_another_app_is_not(self):
        act = "  topResumedActivity=ActivityRecord{1a2b u0 com.android.launcher3/.Launcher t1}\n"
        ime = f"mCurMethodId={PKG}/.ime.DevBoardIme\n  mInputShown=false\n"
        self.assertFalse(self.ask(ime=ime, act=act))


if __name__ == "__main__":
    unittest.main()
