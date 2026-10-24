"""Whether a bug reproduces (R124): always, sometimes, once or untried, kept
beside How to reproduce. A session that gives the steps says how often they
showed it; a person's report is untried until somebody says; an edit moves
it; the page's older edits leave it alone; a held report keeps it. Every
bug and report from before the field reads as untried, with nothing
rewritten. bb report carries it to the diagnostics, and bb bug add --report N
carries a report's words, area, repro and answer into the tracker."""
import ast
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import bugs  # noqa: E402
import reports  # noqa: E402



def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Field(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (Path(self.tmp) / "ws" / "p").mkdir(parents=True)
        bugs.configure(write_json=write_json, state=self.tmp, workspace=str(Path(self.tmp) / "ws"))

    def test_a_persons_report_is_untried_until_somebody_says(self):
        r = bugs.add("p", "the picker loses its pick", repro="1. pick 2. rotate")
        self.assertEqual(r["bug"]["reproduces"], "untried")
        r = bugs.add("p", "it crashes", repro="open it", reproduces="always")
        self.assertEqual(r["bug"]["reproduces"], "always")
        self.assertIn("one of: always, sometimes, once, untried",
                      bugs.add("p", "x", reproduces="often").get("error", ""))

    def test_a_session_with_steps_says_how_often_they_showed_it(self):
        r = bugs.add("p", "it crashes", by="claude", repro="open it")
        self.assertIn("--reproduces always, sometimes, once", r.get("error", ""))
        self.assertTrue(bugs.add("p", "no steps, no question", by="claude").get("ok"))
        self.assertEqual(bugs.add("p", "it crashes", by="claude", repro="open it",
                                  reproduces="sometimes")["bug"]["reproduces"], "sometimes")

    def test_an_edit_moves_it_and_one_that_does_not_send_it_leaves_it(self):
        b = bugs.add("p", "it crashes", repro="open it", reproduces="once")["bug"]
        e = bugs.edit("p", b["id"], reproduces="always")
        self.assertEqual(e["bug"]["reproduces"], "always")
        self.assertTrue([h for h in bugs.history("p") if h.get("act") == "edited" and "reproduces" in h.get("note", "")],
                        "the History names it")
        self.assertIn("one of", bugs.edit("p", b["id"], reproduces="never").get("error", ""))
        got, _ = bugs.verb("p", "edit", {"id": b["id"], "title": "it crashes on open", "repro": "open it"},
                           sessions=lambda: [], prefix="")
        self.assertEqual(next(x for x in got["bugs"] if x["id"] == b["id"])["reproduces"], "always",
                         "a page from before the field does not reset it")
        got, _ = bugs.verb("p", "add", {"title": "from the page", "reproduces": "sometimes"},
                           sessions=lambda: [], prefix="")
        self.assertEqual(next(x for x in got["bugs"] if x["title"] == "from the page")["reproduces"], "sometimes")

    def test_the_brief_names_the_flag(self):
        bugs.add("p", "one open")
        self.assertIn("--reproduces always|sometimes|once|untried", bugs.brief("p"))


class Older(unittest.TestCase):
    def test_a_report_from_before_the_field_reads_as_untried(self):
        # No migration writes it onto older rows (a patch carries none):
        # every reader takes a missing answer as untried.
        self.assertEqual(bugs.REPRODUCES_WORDS.get({}.get("reproduces") or "untried"), "not tried")


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reports.configure(write_json=write_json, state=self.tmp)

    def test_a_report_keeps_its_answer_and_says_it(self):
        r = reports.add("p", "it hangs", repro="bb emu start", reproduces="sometimes")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(reports._view(reports._load()["reports"][-1])["reproduces"], "sometimes")
        self.assertEqual(reports._load()["reports"][-1]["reproduces"], "sometimes")
        self.assertEqual(reports.add("p", "no answer")["ok"], True)
        self.assertEqual(reports._load()["reports"][-1]["reproduces"], "untried")
        self.assertIn("one of", reports.add("p", "x", reproduces="often").get("error", ""))


SRC = os.path.join(HERE, "..", "..", "lib", "bug-verbs.py")


class ReportFlags(unittest.TestCase):
    def test_the_flags_are_taken(self):
        with open(SRC) as f:
            tree = ast.parse(f.read())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pull_flags")
        ns = {"sys": sys, "os": os}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), SRC, "exec"), ns)  # noqa: S102 (our own source)  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
        with contextlib.redirect_stdout(io.StringIO()):
            got = ns["pull_flags"](["t", "--repro", "open it", "--reproduces", "once", "--report", "127"])
        self.assertEqual(got, ("t", {"repro": "open it", "reproduces": "once", "report": "127"}))


if __name__ == "__main__":
    unittest.main()
