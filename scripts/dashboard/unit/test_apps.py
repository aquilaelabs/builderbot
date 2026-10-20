"""apps: the seed file read once and put aside, the release a controller's
version picks, and the files kept only when their sha256 matches (R272
steps 3 and 4)."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import apps  # noqa: E402


class Apps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = {"apps_android": True, "apps_vscode": True, "apps_companion": True}

        def write(path, data):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(data))
        apps.configure(state=self.tmp, version=lambda: "0.7.0-dev.12+abc", setting=self.settings.get,
                       write_json=write)
        self.dev = True
        apps.unvetted_ok = lambda: self.dev

    def release(self, tag, files, bad=()):
        rel = self.tmp / "rel"
        rel.mkdir(exist_ok=True)
        assets = []
        for name in files:
            body = name.encode()
            (rel / name).write_bytes(body)
            sha = "0" * 64 if name in bad else hashlib.sha256(body).hexdigest()
            (rel / (name + ".sha256")).write_text(f"{sha}  {name}\n")
            assets += [{"name": name, "browser_download_url": f"file://{rel / name}"},
                       {"name": name + ".sha256", "browser_download_url": f"file://{rel / name}.sha256"}]
        return {"tag_name": tag, "assets": assets}

    def test_a_build_belongs_to_its_release(self):
        self.assertEqual(apps.base_version("0.7.0-dev.3160+43218c1"), "0.7.0")
        self.assertEqual(apps.base_version("v1.2.3"), "1.2.3")

    def test_the_matching_release_else_the_newest_published(self):
        rels = [{"tag_name": "v0.8.0", "draft": True}, {"tag_name": "v0.7.1"}, {"tag_name": "v0.7.0"}]
        self.assertEqual(apps._pick(rels, "0.7.0"), (rels[2], True))
        self.assertEqual(apps._pick(rels, "0.9.0"), (rels[1], False))

    def test_only_what_matches_its_sha256_is_kept_and_served(self):
        rel = self.release("v0.7.0", ["builderbot-app-0.7.0.apk", "builderbot-vscode-0.7.0.vsix",
                                      "builderbot-companion-0.7.0.exe", "builderbot-companion-0.7.0.pyz"],
                           bad={"builderbot-companion-0.7.0.pyz"})
        (self.tmp / "releases.json").write_text(json.dumps([rel]))
        apps.RELEASES_URL = f"file://{self.tmp / 'releases.json'}"
        v = apps.check()
        held = {a["name"]: [f["file"] for f in a["files"]] for a in v["apps"]}
        self.assertEqual(held["companion"], ["builderbot-companion-0.7.0.exe"])
        self.assertIn("does not match its sha256", v["problem"])
        self.assertTrue(apps.path("android", "builderbot-app-0.7.0.apk"))
        self.assertIsNone(apps.path("android", "../index.json"))
        self.assertIsNone(apps.path("companion", "builderbot-companion-0.7.0.pyz"))

    def test_the_companion_and_the_extension_are_dev_features(self):
        # The operator, 20 Oct: offered, fetched and served only with Offer
        # dev features on; the Android app is not one.
        rel = self.release("v0.7.0", ["builderbot-app-0.7.0.apk", "builderbot-vscode-0.7.0.vsix",
                                      "builderbot-companion-0.7.0.exe"])
        (self.tmp / "releases.json").write_text(json.dumps([rel]))
        apps.RELEASES_URL = f"file://{self.tmp / 'releases.json'}"
        apps.check()
        self.assertTrue(apps.path("vscode", "builderbot-vscode-0.7.0.vsix"))
        self.dev = False
        self.assertEqual([a["name"] for a in apps.view()["apps"]], ["android"])
        self.assertFalse(apps.offered("vscode") or apps.offered("companion"))
        self.assertIsNone(apps.path("vscode", "builderbot-vscode-0.7.0.vsix"))
        self.assertIsNone(apps.path("companion", "builderbot-companion-0.7.0.exe"))
        self.assertTrue(apps.path("android", "builderbot-app-0.7.0.apk"))

    def test_the_seed_is_read_once_and_put_aside(self):
        (self.tmp / "seed.json").write_text(json.dumps({"version": 1, "apps": ["companion"]}))
        got = {}
        self.assertEqual(apps.seed(got.update), {"apps_android": False, "apps_vscode": False, "apps_companion": True})
        self.assertEqual(got["apps_companion"], True)
        self.assertFalse((self.tmp / "seed.json").exists())
        self.assertTrue((self.tmp / "seed.json.applied").exists())
        self.assertEqual(apps.seed(got.update), {})


if __name__ == "__main__":
    unittest.main()
