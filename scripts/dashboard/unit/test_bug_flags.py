"""bb bug add's flags (diagnostics #112): --help prints the usage, an
unknown flag is refused, and neither is glued onto the title the way
`bb bug add "T" --help` filed "T --help"; after -- every word is the title's."""
import ast
import contextlib
import io
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "bug-verbs.py")


def lift(name):
    """The function alone: the script it lives in runs on import."""
    with open(SRC) as f:
        tree = ast.parse(f.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"sys": sys, "os": os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), SRC, "exec"), ns)  # noqa: S102 (our own source)  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
    return ns[name]


def pull_flags():
    return lift("pull_flags")


class Flags(unittest.TestCase):
    def setUp(self):
        self.pf = pull_flags()

    def run_it(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                return self.pf(args), None, out.getvalue(), err.getvalue()
            except SystemExit as e:
                return None, e.code, out.getvalue(), err.getvalue()

    def test_help_prints_usage_and_files_nothing(self):
        got, code, out, _ = self.run_it(["a title", "--help"])
        self.assertIsNone(got)
        self.assertEqual(code, 0)
        self.assertIn("usage: bb bug add TITLE", out)

    def test_an_unknown_flag_is_refused(self):
        got, code, _, err = self.run_it(["a title", "--severity-high"])
        self.assertIsNone(got)
        self.assertEqual(code, 1)
        self.assertIn("does not take --severity-high", err)

    def test_the_known_ones_still_work(self):
        got, _, _, _ = self.run_it(["a", "title", "--sev", "low", "--area", "x"])
        self.assertEqual(got, ("a title", {"severity": "low", "area": "x"}))

    def test_after_two_dashes_every_word_is_the_title(self):
        got, _, _, _ = self.run_it(["--area", "x", "--", "--weird", "title"])
        self.assertEqual(got, ("--weird title", {"area": "x"}))



class OwnTree(unittest.TestCase):
    """B743: on BuilderBot's own tree a bug naming bb is this tracker's."""

    def test_builderbot_source_is_its_own(self):
        bt = lift("builderbot_tree")
        self.assertTrue(bt(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

    def test_another_tree_is_not(self):
        import tempfile
        bt = lift("builderbot_tree")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "scripts"))
            with open(os.path.join(d, "scripts", "bb"), "w") as f:
                f.write("#!/bin/sh\n")
            self.assertFalse(bt(d))


if __name__ == "__main__":
    unittest.main()
