"""docs.py, behind bb tool docs: the page range it draws and what it says
when the office toolchain that makes a PDF of anything else is missing.
Reading and drawing need markitdown and PyMuPDF, which the documents
toolchain carries and this tier does not; those were walked by hand
against the real toolchains (30 Sep)."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import docs  # noqa: E402
import poppler  # noqa: E402


def refused(fn, *a):
    err = io.StringIO()
    with redirect_stderr(err), unittest.TestCase().assertRaises(SystemExit):
        fn(*a)
    return err.getvalue()


class Span(unittest.TestCase):
    def test_the_spellings(self):
        self.assertEqual(docs.span("3", 10), (3, 3))
        self.assertEqual(docs.span("2-4", 10), (2, 4))
        self.assertEqual(docs.span("7-", 10), (7, 10))
        self.assertEqual(docs.span("8-40", 10), (8, 10))

    def test_what_is_refused(self):
        for s in ("0", "5-2", "x", "-3", ""):
            self.assertIn("--pages", refused(docs.span, s, 10), s)
        self.assertIn("it has 10 pages", refused(docs.span, "11", 10))


class AsPdf(unittest.TestCase):
    def test_a_pdf_is_itself(self):
        self.assertEqual(docs.as_pdf("/x/a.PDF", "/tmp"), "/x/a.PDF")

    def test_anything_else_needs_the_office_toolchain_and_says_so(self):
        was = os.environ.pop("BB_DOCS_SOFFICE", None)
        try:
            with tempfile.TemporaryDirectory() as d:
                msg = refused(docs.as_pdf, "deck.pptx", d)
        finally:
            if was is not None:
                os.environ["BB_DOCS_SOFFICE"] = was
        self.assertIn("office toolchain", msg)
        self.assertIn("bb tool docs read", msg)


class Usage(unittest.TestCase):
    def test_read_with_nothing_names_the_formats(self):
        self.assertIn(".docx", refused(docs.read, []))

    def test_an_unknown_verb(self):
        self.assertIn("bb tool docs read", refused(docs.main, ["show", "x"]))


class Poppler(unittest.TestCase):
    """The pdftoppm and pdfinfo the documents toolchain puts on a node for
    Claude Code's own PDF reader (R103): what it answers before PyMuPDF is
    needed. Drawing pages was walked with Claude Code itself reading a PDF
    through them (30 Sep)."""

    def exits(self, *argv):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as e:
            poppler.main(list(argv))
        return e.exception.code, err.getvalue()

    def test_the_version_check_claude_code_makes_answers(self):
        code, said = self.exits("pdftoppm", "-v")
        self.assertEqual(code, 0)
        self.assertIn("pdftoppm version", said)

    def test_what_is_refused_is_poppler_shaped(self):
        self.assertEqual(self.exits("pdftoppm", "-jpeg", "one.pdf")[0], 99)
        code, said = self.exits("pdftoppm", "-singlefile", "a.pdf", "p")
        self.assertEqual(code, 99)
        self.assertIn("Command Line Error", said)
        self.assertEqual(self.exits("pdftoppm", "-r", "x", "a.pdf", "p")[0], 99)
        self.assertEqual(self.exits("pdfinfo")[0], 99)
        self.assertEqual(self.exits("pdftotext", "a.pdf")[0], 99)


if __name__ == "__main__":
    unittest.main()
