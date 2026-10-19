"""R77: a tool pack installs on a node the way a shipped toolchain does. A
copy laid out as the bundle a node unpacks (scripts/bb, scripts/lib and the
catalog, with the packs' toolpacks.json beside it, as workspace.bundle()
writes it) installs a pack repository at its pinned commit into a scratch
store, runs its install steps and its verify, and puts its bin on PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import statefile  # noqa: E402
import toolpacks  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        pack = os.path.join(t, "pack")
        os.makedirs(os.path.join(pack, "bin"))
        with open(os.path.join(pack, "bin", "hexkit"), "w") as f:
            f.write("#!/bin/sh\necho \"hexkit 1.0\"; for a in \"$@\"; do echo \"arg[$a]\"; done\n")
        os.chmod(os.path.join(pack, "bin", "hexkit"), 0o755)
        with open(os.path.join(pack, "install.sh"), "w") as f:
            f.write("#!/bin/sh\necho fetched > \"$(dirname \"$0\")/payload.txt\"\n")
        with open(os.path.join(pack, "bbtool.json"), "w") as f:
            json.dump({"name": "hexkit", "platforms": ["linux/amd64", "linux/arm64"],
                       "install": {"steps": [["sh", "{dir}/install.sh"]], "verify": ["{dir}/bin/hexkit"]},
                       "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
                       "verbs": {"dump": {"run": ["{dir}/bin/hexkit", "{args}"]}}}, f)
        git("init", "-q", cwd=pack)
        git("add", "-A", cwd=pack)
        git("commit", "-qm", "pack", cwd=pack)
        self.commit = git("rev-parse", "HEAD", cwd=pack)
        # A later commit the operator never approved: the install must not take it.
        with open(os.path.join(pack, "bin", "hexkit"), "w") as f:
            f.write("#!/bin/sh\necho unapproved\n")
        git("commit", "-qam", "later", cwd=pack)
        os.environ["BB_TOOLPACKS_FILE_URLS"] = "1"
        self.addCleanup(os.environ.pop, "BB_TOOLPACKS_FILE_URLS", None)
        toolpacks.configure(state=t, write_json=statefile.write_json)
        r = toolpacks.add("file://" + pack, self.commit, "operator")
        self.assertTrue(r.get("ok"), r)
        # The bundle's layout: what workspace.bundle() tars, plus toolpacks.json.
        self.b = os.path.join(t, "bundle")
        shutil.copytree(os.path.join(REPO, "scripts", "lib"), os.path.join(self.b, "scripts", "lib"))
        shutil.copy(os.path.join(REPO, "scripts", "bb"), os.path.join(self.b, "scripts", "bb"))
        os.makedirs(os.path.join(self.b, "config"))
        shutil.copy(os.path.join(REPO, "config", "toolchains.json"), os.path.join(self.b, "config"))
        with open(os.path.join(self.b, "config", "toolpacks.json"), "w") as f:
            f.write(toolpacks.catalog_json())
        self.store = os.path.join(t, "store")
        os.makedirs(self.store)
        # As a job runs it on a node: no session around it.
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        self.env["SDK_ROOT"] = self.store

    def bb(self, *a):
        return subprocess.run(["bash", os.path.join(self.b, "scripts", "bb"), *a], capture_output=True, text=True,
                              env=self.env, timeout=120, check=False)

    def test_installs_at_the_approved_commit_and_joins_the_environment(self):
        r = self.bb("toolchains", "install", "hexkit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("hexkit 1.0", r.stdout + r.stderr, "the verify ran, on the approved commit's file")
        d = [os.path.join(self.store, x, "hexkit") for x in os.listdir(self.store)
             if os.path.isdir(os.path.join(self.store, x, "hexkit"))][0]
        self.assertEqual(git("rev-parse", "HEAD", cwd=d), self.commit)
        with open(os.path.join(d, "payload.txt")) as f:
            self.assertEqual(f.read().strip(), "fetched", "its install steps ran")
        env = self.bb("toolchains", "env").stdout
        self.assertIn(os.path.join(d, "bin"), env, "its bin is on PATH")
        # bb tool PACK VERB: the manifest's words, the caller's in place of
        # {args}, each a word of its own and nothing a shell reads.
        r = self.bb("tool", "hexkit", "dump", "a b", "$(id)")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("arg[a b]\narg[$(id)]", r.stdout)
        r = self.bb("tool", "hexkit")
        self.assertIn("bb tool hexkit dump", r.stdout, "the pack's verbs listed")
        r = self.bb("tool", "hexkit", "nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hexkit has no verb nope: dump", r.stderr)
        self.assertIn("bb tool hexkit dump|", self.bb("tool").stdout.replace("dump ...", "dump|"))
        r = self.bb("tool", "nosuch")
        self.assertIn("no tool called nosuch", r.stderr)
        # Switched off for the project (its settings' Toolchains group): bb
        # refuses its verbs by that name and leaves it off PATH.
        self.env["BB_TOOLCHAINS_OFF"] = "hexkit"
        r = self.bb("tool", "hexkit", "dump", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hexkit is switched off for this project", r.stderr)
        self.assertIn("bb tool hexkit dump ...   (switched off for this project", self.bb("tool").stdout,
                      "the listing says so too")


if __name__ == "__main__":
    unittest.main()
