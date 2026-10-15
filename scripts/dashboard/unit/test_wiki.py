"""wiki.py (R112): a project's wiki, kept as a repository of forge-shaped
pages. Pages are written, read, refused when stale, held under ask and
refused under deny for a session, exported as a zip, and pushed to and
pulled from a stand-in for the forge's wiki (a bare repository on disk,
reached as the forge's address would be)."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pending  # noqa: E402
import prefs  # noqa: E402
import wiki  # noqa: E402

ME = {"name": "Tester", "email": "tester@example.invalid"}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data))


class Wiki(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.forge = self.tmp / "forge.wiki.git"
        self.rights = {}
        prefs.FILE = None
        wiki.configure(state=self.tmp / "state", workspace=self.tmp / "ws", write_json=write_json,
                       push_record_fn=lambda p: self.rights.get(p), token_helper_fn=lambda p: "",
                       parse_fn=None, config_fn=None, env_fn=None)
        # The forge's address, pointed at the stand-in.
        real = wiki.remote
        self.addCleanup(setattr, wiki, "remote", real)
        wiki.remote = lambda p: ({"url": str(self.forge), "label": "forge/app", "auth": True}
                                 if p in self.rights else {})

    def test_names_are_the_forge_files(self):
        self.assertEqual(wiki.file_of("Build and test"), "Build-and-test.md")
        self.assertEqual(wiki.file_of("_Sidebar"), "_Sidebar.md")
        for bad in ("a/b", "../x", ".hidden", "_mine", "", "x" * (wiki.MAX_NAME + 1), "what?"):
            with self.assertRaises(wiki.Refused, msg=bad):
                wiki.file_of(bad)

    def test_save_read_list_and_a_stale_write_is_refused(self):
        r = wiki.save("app", "Home", "# Welcome", who=ME)
        self.assertTrue(r["ok"])
        wiki.save("app", "Build and test", "run it", who=ME)
        p = wiki.page("app", "Home")
        self.assertEqual(p["text"], "# Welcome\n")
        self.assertEqual(p["by"], "Tester")
        self.assertEqual([x["name"] for x in wiki.pages("app")], ["Home", "Build-and-test"])
        # Somebody else's edit in between: the old read is refused.
        wiki.save("app", "Home", "# Hello", base=p["rev"], who=ME)
        with self.assertRaises(wiki.Refused):
            wiki.save("app", "Home", "# Mine", base=p["rev"], who=ME)
        with self.assertRaises(wiki.Refused):
            wiki.save("app", "Home", "# New", who=ME)            # not new: it is there
        wiki.rename("app", "Build and test", "Building", who=ME)
        wiki.remove("app", "Building", who=ME)
        self.assertEqual([x["name"] for x in wiki.pages("app")], ["Home"])
        self.assertGreaterEqual(len(wiki.history("app")), 4)

    def test_export_is_a_zip_of_the_pages(self):
        with self.assertRaises(wiki.Refused):
            wiki.export_zip("app")
        wiki.save("app", "Home", "hi", who=ME)
        name, data = wiki.export_zip("app")
        self.assertEqual(name, "app-wiki.zip")
        self.assertEqual(zipfile.ZipFile(io.BytesIO(data)).read("app-wiki/Home.md"), b"hi\n")

    def test_a_session_is_held_under_ask_and_refused_under_deny(self):
        write_json(self.tmp / "state" / "claude-prefs.json", {"projects": {"app": {"gate": {"wiki": "ask"}}}})
        prefs.configure(write_json=write_json, state=self.tmp / "state")
        r, st = wiki.verb("app", {"action": "save", "name": "Home", "text": "x"}, ME, True)
        self.assertEqual(st, 202, r)
        self.assertEqual(wiki.pages("app"), [])
        held = pending.listing("app", "wiki")
        self.assertEqual(len(held), 1)
        # A person's save lands whatever the dial says.
        r, st = wiki.verb("app", {"action": "save", "name": "Other", "text": "y"}, ME, False)
        self.assertEqual(st, 200, r)
        write_json(self.tmp / "state" / "claude-prefs.json", {"projects": {"app": {"gate": {"wiki": "deny"}}}})
        r, st = wiki.verb("app", {"action": "save", "name": "Home", "text": "x"}, ME, True)
        self.assertEqual(st, 403)
        self.assertIn("Write the wiki", r["error"])
        # Hidden: a session can neither write nor read it; a person still can.
        write_json(self.tmp / "state" / "claude-prefs.json", {"projects": {"app": {"gate": {"wiki": "hidden"}}}})
        r, st = wiki.verb("app", {"action": "save", "name": "New", "text": "x"}, ME, True)
        self.assertEqual(st, 403)
        self.assertIn("hidden", r["error"])
        self.assertTrue(wiki.hidden_for("app", True))
        self.assertEqual(wiki.hidden_for("app", False), "")
        self.assertEqual(wiki.verb("app", {"action": "save", "name": "New", "text": "x"}, ME, False)[1], 200)
        self.assertTrue(prefs.gate_ok("wiki", "hidden"))
        self.assertFalse(prefs.gate_ok("bugs", "hidden"))
        # A session never pushes.
        r, st = wiki.verb("app", {"action": "push"}, ME, True)
        self.assertEqual(st, 403)

    def test_push_then_pull_through_the_forge(self):
        with self.assertRaises(wiki.Refused):
            wiki.push("app")                                    # no remote at all
        self.rights["app"] = {"repo": "o/app", "host": "forge"}
        subprocess.run(["git", "init", "--bare", "--quiet", "-b", "master", str(self.forge)], check=True)
        wiki.save("app", "Home", "one", who=ME)
        self.assertTrue(wiki.push("app")["ok"])
        # The forge has it as a wiki would.
        out = subprocess.run(["git", "--git-dir", str(self.forge), "show", "master:Home.md"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, "one\n")
        # Somebody edits on the web: a push is refused until a pull.
        web = self.tmp / "web"
        subprocess.run(["git", "clone", "--quiet", str(self.forge), str(web)], check=True)
        (web / "Faq.md").write_text("asked\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="w", GIT_AUTHOR_EMAIL="w@x", GIT_COMMITTER_NAME="w",
                   GIT_COMMITTER_EMAIL="w@x")
        subprocess.run(["git", "-C", str(web), "add", "."], check=True)
        subprocess.run(["git", "-C", str(web), "commit", "--quiet", "-m", "web"], check=True, env=env)
        subprocess.run(["git", "-C", str(web), "push", "--quiet"], check=True)
        wiki.save("app", "Home", "two", base=wiki.page("app", "Home")["rev"], who=ME)
        with self.assertRaises(wiki.Refused) as e:
            wiki.push("app")
        self.assertIn("Pull", str(e.exception))
        # Replacing overwrites the forge's, which a person chooses knowingly.
        self.assertTrue(wiki.push("app", replace=True)["ok"])
        out = subprocess.run(["git", "--git-dir", str(self.forge), "ls-tree", "--name-only", "master"],
                             capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["Home.md"])
        subprocess.run(["git", "-C", str(web), "fetch", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(web), "reset", "--quiet", "--hard", "origin/master"], check=True)
        (web / "Faq.md").write_text("asked\n")
        subprocess.run(["git", "-C", str(web), "add", "."], check=True)
        subprocess.run(["git", "-C", str(web), "commit", "--quiet", "-m", "web again"], check=True, env=env)
        subprocess.run(["git", "-C", str(web), "push", "--quiet"], check=True)
        self.assertEqual(wiki.pull("app", ME)["took"], "merged")
        self.assertEqual(sorted(x["name"] for x in wiki.pages("app")), ["Faq", "Home"])
        self.assertTrue(wiki.push("app")["ok"])

    def test_a_pull_into_an_empty_wiki_takes_it_all(self):
        self.rights["app"] = {"repo": "o/app", "host": "forge"}
        subprocess.run(["git", "init", "--bare", "--quiet", "-b", "master", str(self.forge)], check=True)
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "--quiet", str(self.forge), str(seed)], check=True,
                       stderr=subprocess.DEVNULL)
        (seed / "Home.md").write_text("from the forge\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="w", GIT_AUTHOR_EMAIL="w@x", GIT_COMMITTER_NAME="w",
                   GIT_COMMITTER_EMAIL="w@x")
        subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "--quiet", "-m", "seed"], check=True, env=env)
        subprocess.run(["git", "-C", str(seed), "push", "--quiet", "origin", "HEAD:master"], check=True)
        self.assertEqual(wiki.pull("app", ME)["took"], "all")
        self.assertEqual(wiki.page("app", "Home")["text"], "from the forge\n")


if __name__ == "__main__":
    unittest.main()
