"""The code map reads data files (R167): a setting where compose, the env
file, the Unraid template and a JSON file define it, each at its line, a
Markdown file's headings as sections, and where the code reads a setting
as a call of it from `env`."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402


class DataFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".env.example").write_text("# the port\nDASHBOARD_PORT=7680\nOTHER=1\n")
        (self.tmp / "docker-compose.yml").write_text("services:\n  web:\n    image: x\n    environment:\n      DASHBOARD_PORT: ${DASHBOARD_PORT:-7680}\n")
        (self.tmp / "t.xml").write_text('<Container>\n  <Config Name="Port" Target="DASHBOARD_PORT"/>\n</Container>\n')
        (self.tmp / "s.json").write_text('{\n "alpha": {"beta": 1}\n}\n')
        (self.tmp / "README.md").write_text("# Title\n\n## Installing\nwords\n")
        (self.tmp / "serve.py").write_text('import os\nPORT = int(os.environ.get("DASHBOARD_PORT", "7680"))\nX = os.getenv("OTHER")\n')
        (self.tmp / "run.sh").write_text('#!/bin/bash\necho "${DASHBOARD_PORT:-7680}" "$DASHBOARD_PORT"\n')
        (self.tmp / "bad.yml").write_text("a: 1\n  b: 2\n")
        self.idx = codemap.build(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def found(self, name):
        return sorted((d["file"], d["line"], d["kind"]) for d in self.idx["defs"] if d["name"] == name)

    def test_a_setting_is_found_where_each_file_defines_it(self):
        self.assertEqual(self.found("DASHBOARD_PORT"), [(".env.example", 2, "setting"), ("docker-compose.yml", 5, "setting"), ("t.xml", 2, "setting")])
        self.assertEqual(self.found("beta"), [("s.json", 2, "key")])
        self.assertEqual([d["parent"] for d in self.idx["defs"] if d["name"] == "beta"], ["alpha"])

    def test_a_markdown_files_headings_are_its_sections(self):
        self.assertEqual([(s["name"], s["line"]) for s in self.idx["files"]["README.md"]["sections"]], [("Title", 1), ("Installing", 3)])
        self.assertEqual(self.found("Installing"), [("README.md", 3, "heading")])

    def test_where_the_code_reads_a_setting_is_a_call_from_env(self):
        reads = sorted((c["file"], c["line"]) for c in self.idx["calls"] if c["name"] == "DASHBOARD_PORT" and c["qual"] == "env")
        self.assertEqual(reads, [("run.sh", 2), ("serve.py", 2)], "one call per line, however many times the line names it")
        self.assertEqual([c["file"] for c in self.idx["calls"] if c["name"] == "OTHER"], ["serve.py"])

    def test_a_file_that_does_not_parse_is_said_not_crashed(self):
        bad = [d["name"] for d in self.idx["files"]["bad.yml"]["defs"]]
        self.assertTrue(bad and bad[0].startswith("(not read:"), bad)


if __name__ == "__main__":
    unittest.main()
