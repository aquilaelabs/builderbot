"""R77: a tool pack's manifest, checked and cut to what BuilderBot reads,
fetched from a repository at a commit, kept pinned to it, and turned into
one catalog row of the recipe machinery's own shape."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import statefile  # noqa: E402
import toolpacks  # noqa: E402

GOOD = {
    "name": "hexkit", "label": "Hex kit", "about": "Looks inside binaries.",
    "platforms": ["linux/amd64", "linux/arm64"],
    "terms": [{"label": "MIT", "url": "https://opensource.org/license/mit"}],
    "install": {"steps": [["sh", "{dir}/install.sh"]], "verify": ["{dir}/bin/hexkit", "--version"]},
    "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
    "verbs": {"dump": {"about": "A file's bytes as hex.", "usage": "FILE",
                       "run": ["{dir}/bin/hexkit", "dump", "{args}"]},
              "report": {"about": "A report into dist/.", "usage": "FILE",
                         "run": ["python3", "{dir}/verbs/report.py", "--out", "{dist}", "{args}"]}},
    "guidance": "GUIDE.md",
}


def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t"))


class Manifest(unittest.TestCase):
    def test_a_good_manifest_is_kept_as_read(self):
        clean, errors = toolpacks.validate(GOOD)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(clean["verbs"]), ["dump", "report"])
        self.assertEqual(clean["layout"]["tool"], "bin/hexkit")

    def test_what_is_refused_and_why(self):
        bad = json.loads(json.dumps(GOOD))
        bad["name"] = "Hex Kit"
        bad["verbs"]["shell"] = {"run": ["bash", "-c", "{args}"]}
        bad["verbs"]["out"] = {"run": ["/usr/bin/curl", "{args}"]}
        bad["verbs"]["glued"] = {"run": ["{dir}/bin/hexkit", "--file={args}"]}
        bad["verbs"]["escape"] = {"run": ["{dir}/../../bin/sh"]}
        bad["install"]["steps"] = ["sh install.sh"]
        _, errors = toolpacks.validate(bad)
        said = " | ".join(errors)
        self.assertIn("name is 2 to 40", said)
        self.assertIn("verb shell runs bash", said, "a script outside the pack is refused")
        self.assertIn("verb out runs /usr/bin/curl", said)
        self.assertIn("{args} is a word of its own", said)
        self.assertIn("verb escape runs", said, "a path out of the pack is refused")
        self.assertIn("install step 1 is a list of words", said)

    def test_a_shipped_name_is_refused(self):
        _, errors = toolpacks.validate(GOOD, shipped=("hexkit",))
        self.assertTrue(any("BuilderBot ships" in e for e in errors), errors)


class Repository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "pack")
        os.makedirs(self.repo)
        git("init", "-q", cwd=self.repo)
        self.commit(GOOD, "Look before you leap.")
        os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
        self.addCleanup(os.environ.pop, "BB_TOOLPACKS_FILE_URLS", None)
        toolpacks.configure(state=self.tmp.name, write_json=statefile.write_json)
        self.url = "file://" + self.repo

    def commit(self, manifest, guide):
        with open(os.path.join(self.repo, "bbtool.json"), "w") as f:
            json.dump(manifest, f)
        with open(os.path.join(self.repo, "GUIDE.md"), "w") as f:
            f.write(guide)
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "pack", cwd=self.repo)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_fetch_add_and_the_recipe(self):
        seen = toolpacks.fetch(self.url)
        self.assertNotIn("error", seen, seen)
        self.assertEqual(seen["guidance"], "Look before you leap.")
        r = toolpacks.add(self.url, seen["commit"], "operator")
        self.assertTrue(r.get("ok"), r)
        row = toolpacks.recipes()[0]
        self.assertEqual(row["source"], {"kind": "git", "url": self.url, "commit": seen["commit"], "fresh_only": True,
                                         "then": [{"run": ["sh", "{dir}/install.sh"]}],
                                         "verify": ["{dir}/bin/hexkit", "--version"]})
        self.assertEqual(row["pack"]["by"], "operator")
        self.assertIn("dump", row["verbs"])
        self.assertEqual(json.loads(toolpacks.catalog_json())["toolchains"][0]["name"], "hexkit")

    def test_what_is_kept_is_what_was_shown(self):
        shown = toolpacks.fetch(self.url)["commit"]
        changed = json.loads(json.dumps(GOOD))
        changed["verbs"]["dump"]["run"] = ["{dir}/bin/other", "{args}"]
        self.commit(changed, "Changed after it was shown.")
        r = toolpacks.add(self.url, shown, "operator")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(toolpacks.packs()["hexkit"]["manifest"]["verbs"]["dump"]["run"][0], "{dir}/bin/hexkit",
                         "the commit approved, not the newer one")

    def test_a_repository_without_a_manifest_and_a_bad_address(self):
        os.remove(os.path.join(self.repo, "bbtool.json"))
        git("commit", "-q", "-am", "gone", cwd=self.repo)
        self.assertIn("has no bbtool.json", toolpacks.fetch(self.url)["error"])
        self.assertIn("a pack is a git repository's address", toolpacks.fetch("ftp://x/y")["error"])
        self.assertTrue(toolpacks.URL.fullmatch("http://192.168.1.16:3000/lab/hexkit.git"), "a LAN git host over http")

    def test_remove(self):
        toolpacks.add(self.url, toolpacks.fetch(self.url)["commit"], "operator")
        self.assertTrue(toolpacks.remove("hexkit").get("ok"))
        self.assertEqual(toolpacks.recipes(), [])
        self.assertIn("no tool pack called", toolpacks.remove("hexkit")["error"])


if __name__ == "__main__":
    unittest.main()
