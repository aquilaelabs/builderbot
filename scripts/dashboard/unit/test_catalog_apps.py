"""Docker apps in the catalog (R170 step 7): an app entry's folder fetched at
the commit the signed index pins, its archive's sha256 checked; bbapp.json
and compose.yml read from it and the compose held to a person's own app's
rules; kept with the entry's tier and pin, so New container offers it; and
the Library lists it as an Apps card until it is kept."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library  # noqa: E402
import nasapps  # noqa: E402
import toolpacks  # noqa: E402

COMPOSE = 'services:\n  whoami:\n    image: traefik/whoami:v1.10.4\n    ports:\n      - "${PORT}:80"\n'
META = {"name": "whoami", "label": "whoami", "about": "A tiny web server.", "port": 8089, "platforms": ["linux/amd64"]}


def git(d, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", d, *a], capture_output=True, check=True, env=env).stdout


class CatalogApps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        nasapps.configure(state=self.tmp, write_json=lambda p, d: Path(p).write_text(json.dumps(d)))
        repo = self.tmp / "repo"
        (repo / "packs" / "apps" / "whoami").mkdir(parents=True)
        (repo / "packs" / "apps" / "whoami" / "bbapp.json").write_text(json.dumps(META))
        (repo / "packs" / "apps" / "whoami" / "compose.yml").write_text(COMPOSE)
        git(str(repo), "init", "-q")
        git(str(repo), "add", "-A")
        git(str(repo), "commit", "-qm", "app")
        self.commit = git(str(repo), "rev-parse", "HEAD").decode().strip()
        tar = git(str(repo), "archive", "--format=tar", "HEAD", "packs/apps/whoami")
        self.entry = {"name": "whoami", "kind": "app", "url": f"file://{repo}", "commit": self.commit,
                      "sha256": hashlib.sha256(tar).hexdigest(), "path": "packs/apps/whoami", "tier": "vetted", "about": "A tiny web server."}
        self.env = mock.patch.dict(os.environ, {"BB_TOOLPACKS_FILE_URLS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_an_app_is_kept_from_its_pin_with_its_tier(self):
        r = nasapps.add_catalog(self.entry, by="ann", fetch=toolpacks.fetch_folder)
        self.assertEqual(r.get("app"), "whoami", r)
        got = next(a for a in nasapps.catalog() if a["id"] == "whoami")
        self.assertEqual((got["tier"], got["port"]), ("vetted", 8089))
        self.assertEqual(nasapps._load()["whoami"]["pin"]["commit"], self.commit)

    def test_a_folder_not_as_vetted_is_refused(self):
        bad = dict(self.entry, sha256="0" * 64)
        self.assertIn("not what the catalog vetted", nasapps.add_catalog(bad, fetch=toolpacks.fetch_folder)["error"])
        self.assertIn("no app", nasapps.add_catalog(None, fetch=toolpacks.fetch_folder)["error"])
        self.assertNotIn("whoami", nasapps._load())

    def test_the_library_offers_it_until_it_is_kept(self):
        idx = {"packs": [self.entry]}
        tc = {"items": [], "platform": "linux/amd64"}
        rows = library.rows(tc, [], [], idx, {})
        card = next(r for r in rows if r["name"] == "whoami")
        self.assertEqual((card["kind"], card["verb"], card["tier"]), ("app", "install", "vetted"))
        self.assertEqual(card["catalog"]["commit"], self.commit)
        kept = library.rows(tc, [], [{"id": "whoami", "name": "whoami", "what": "x", "port": 8089, "tier": "vetted"}], idx, {})
        self.assertEqual(len([r for r in kept if r["name"] == "whoami"]), 1, "kept, it is the app's own card alone")
        self.assertNotIn("catalog", next(r for r in kept if r["name"] == "whoami"))


if __name__ == "__main__":
    unittest.main()
