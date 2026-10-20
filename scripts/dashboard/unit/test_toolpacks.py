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

    def test_a_platform_is_os_and_arch_and_the_refusal_names_the_wildcard(self):
        # B111: the doc and the refusal agree: linux/* is any architecture,
        # a bare * is refused, and the refusal shows the wildcard's form.
        ok = json.loads(json.dumps(GOOD))
        ok["platforms"] = ["linux/*", "darwin/*"]
        self.assertEqual(toolpacks.validate(ok)[1], [])
        bare = json.loads(json.dumps(GOOD))
        bare["platforms"] = ["*"]
        said = " | ".join(toolpacks.validate(bare)[1])
        self.assertIn("linux/*", said)
        self.assertIn("darwin/*", said)

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
                                         "verify": ["{dir}/bin/hexkit", "--version"],
                                         # B83: what the install marks executable
                                         "exec": ["{dir}/bin/hexkit"], "exec_dirs": ["{dir}/bin"]})
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

    def test_remove_is_refused_while_a_node_holds_it(self):
        # B84: its files would stay in that store with no row left to
        # uninstall them from, and the pack added back would read installed.
        toolpacks.add(self.url, toolpacks.fetch(self.url)["commit"], "operator")
        r = toolpacks.remove("hexkit", ["bb-dev-sandbox"])
        self.assertEqual(r["installed"], ["bb-dev-sandbox"])
        self.assertIn("hexkit is installed on bb-dev-sandbox: uninstall it there first", r["error"])
        self.assertEqual([x["name"] for x in toolpacks.recipes()], ["hexkit"], "still in the catalog")


class MadeHere(unittest.TestCase):
    """A pack made on the controller, with no repository of its own: a
    pasted manifest or an uploaded archive, kept as a repository here, each
    approved version a commit, and carried to the nodes as a git bundle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.uploads = {}

        def unpack(aid, dest):
            # projects.unpack_archive's part, with its checks, is its own
            # suite's: here an upload is files written where it is asked.
            files = self.uploads.pop(aid, None)
            if files is None:
                return {"error": "that upload has gone"}
            for rel, body in files.items():
                os.makedirs(os.path.dirname(os.path.join(dest, rel)) or dest, exist_ok=True)
                with open(os.path.join(dest, rel), "w") as f:
                    f.write(body)
            return {"files": len(files)}
        toolpacks.configure(state=self.tmp.name, write_json=statefile.write_json, unpack=unpack)

    def paste(self, manifest):
        return toolpacks.stage(json.dumps(manifest))

    def test_a_pasted_manifest_is_kept_as_a_commit_made_here(self):
        m = json.loads(json.dumps(GOOD))
        m.pop("guidance")
        seen = self.paste(m)
        self.assertNotIn("error", seen, seen)
        self.assertTrue(seen["here"] and seen["staged"] and seen["files"] == ["bbtool.json"])
        r = toolpacks.add_staged(seen["staged"], "operator")
        self.assertTrue(r.get("ok"), r)
        rec = toolpacks.packs()["hexkit"]
        self.assertTrue(rec["hosted"] and rec["url"] == "here:hexkit" and len(rec["commit"]) == 40)
        row = toolpacks.recipe(rec)
        self.assertEqual(row["source"]["url"], "bundle:toolpacks/hexkit.bundle")
        self.assertTrue(row["pack"]["here"])
        [(arc, f)] = toolpacks.hosted_files()
        self.assertEqual(arc, "config/toolpacks/hexkit.bundle")
        self.assertTrue(f.is_file())
        self.assertEqual(json.loads(toolpacks.source("hexkit")["text"])["label"], "Hex kit")
        # The same again is no new version; a change is one, on top of it.
        again = toolpacks.add_staged(self.paste(m)["staged"], "operator")
        self.assertTrue(again["unchanged"] and toolpacks.packs()["hexkit"]["commit"] == rec["commit"])
        m["label"] = "Hex kit 2"
        newer = toolpacks.add_staged(self.paste(m)["staged"], "operator")
        self.assertTrue(newer["replaced"] and not newer["unchanged"])
        self.assertNotEqual(newer["pack"]["commit"], rec["commit"])
        r = subprocess.run(["git", "--git-dir", os.path.join(self.tmp.name, "toolpacks", "hexkit.git"),
                            "rev-parse", "main~1"], capture_output=True, text=True, check=False)
        self.assertEqual(r.stdout.strip(), rec["commit"], "the earlier version is the new one's parent")
        # Removed, its repository and bundle go with it.
        self.assertTrue(toolpacks.remove("hexkit").get("ok"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "toolpacks", "hexkit.git")))
        self.assertEqual(toolpacks.hosted_files(), [])

    def test_an_uploaded_archive_with_its_guidance(self):
        self.uploads["a" * 16] = {"bbtool.json": json.dumps(GOOD), "GUIDE.md": "Read me first.",
                                  "bin/hexkit": "#!/bin/sh\n", ".git/config": "[core]\n"}
        seen = toolpacks.stage(archive="a" * 16)
        self.assertNotIn("error", seen, seen)
        self.assertEqual(seen["guidance"], "Read me first.")
        self.assertNotIn(".git/config", seen["files"], "an uploaded repository's own history is left out")
        self.assertTrue(toolpacks.add_staged(seen["staged"], "operator").get("ok"))

    def test_a_pack_without_about_is_still_a_row(self):
        # B106: about is optional, and the catalog drops a row without one.
        import toolchains
        m = {"name": "bare", "platforms": ["linux/amd64"], "verbs": {"go": {"run": ["{dir}/go"]}}}
        self.assertTrue(toolpacks.add_staged(self.paste(m)["staged"], "operator").get("ok"))
        rows = toolchains.load_toolchains(toolpacks.recipes())
        self.assertEqual([r["name"] for r in rows if r.get("pack")], ["bare"])

    def test_what_is_refused(self):
        self.assertIn("paste a bbtool.json", toolpacks.stage("  ")["error"])
        self.assertIn("is not JSON", toolpacks.stage("{nope")["error"])
        bad = json.loads(json.dumps(GOOD))
        bad["name"] = "Bad Name"
        self.assertIn("needs fixing", self.paste(bad)["error"])
        self.assertIn("is not there", self.paste(GOOD)["error"], "a guidance file the paste cannot carry")
        self.uploads["b" * 16] = {"README.md": "no manifest"}
        self.assertIn("has no bbtool.json", toolpacks.stage(archive="b" * 16)["error"])
        self.assertIn("has gone", toolpacks.add_staged("c" * 16, "operator")["error"])
        self.assertIn("has gone", toolpacks.add_staged("../x", "operator")["error"])
        self.assertIn("not a pack made here", toolpacks.source("hexkit")["error"])
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "toolpacks", "staging")), [],
                         "nothing refused is left staged")


if __name__ == "__main__":
    unittest.main()
