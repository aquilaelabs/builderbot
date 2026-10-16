"""The Help page's docs (R258): the ones docs/README.md lists, in its
groups; one read by its name and nothing else; a search that finds a line
with the section it is under."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import helpdocs  # noqa: E402

README = """# The docs

## Setting it up

- [install.md](install.md): the checklist
- [gone.md](gone.md): listed, but not there

## Using it

- [usage.md](usage.md): how it is used
"""


class HelpDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "README.md").write_text(README)
        (d / "install.md").write_text("# Installing\n\n## The token\n\nPaste the runner token here.\n\n| what | where |\n|---|---|\n| token | the env |\n")
        (d / "usage.md").write_text("# Using it\n\nNothing about tokens here, but a session.\n")
        (d / "secret.md").write_text("# Not listed\n\ntoken\n")
        helpdocs.configure(docs=d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_listing_is_readmes_groups_of_docs_that_exist(self):
        j, code = helpdocs.listing()
        self.assertEqual(code, 200)
        self.assertEqual(j["home"], "README")
        self.assertEqual([g["group"] for g in j["groups"]], ["Setting it up", "Using it"])
        self.assertEqual([d["name"] for d in j["groups"][0]["docs"]], ["install"])
        self.assertEqual(j["groups"][0]["docs"][0]["title"], "Installing")

    def test_a_doc_is_read_by_a_listed_name_only(self):
        self.assertEqual(helpdocs.read("install")[0]["title"], "Installing")
        for bad in ("secret", "../README", "/etc/passwd", "install.md", ""):
            self.assertEqual(helpdocs.read(bad)[1], 404, bad)

    def test_search_finds_the_line_and_its_section(self):
        j, _ = helpdocs.search("runner token")
        self.assertEqual(len(j["results"]), 1)
        r = j["results"][0]
        self.assertEqual((r["doc"], r["heading"], r["anchor"]), ("install", "The token", "wk-the-token"))
        rows = helpdocs.search("token env")[0]["results"]
        self.assertEqual([x["text"] for x in rows], ["token · the env"])
        self.assertFalse(any(x["doc"] == "secret" for x in helpdocs.search("token")[0]["results"]))
        self.assertEqual(helpdocs.search("t")[0]["results"], [])


if __name__ == "__main__":
    unittest.main()
