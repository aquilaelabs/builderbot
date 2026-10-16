"""Registry images kept up to date (imagecheck.py, R195): an image reference
read into its registry, repository and tag; a node's pulled digest compared
with what the registry serves; a container behind until Update pulls it."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import imagecheck  # noqa: E402


def write_json(path, d):
    Path(path).write_text(json.dumps(d))


class FakeDevapp:
    MAIN = "main"
    SYSTEM = "System"
    DOCKER = "docker"

    def __init__(self, cfg, pulled):
        self.cfg, self.pulled = cfg, pulled

    def _load(self):
        return {"radarr": {"main": {"source": "file", "node": "n1"}}, "site": {"main": {"node": "n1"}},
                "nginx-vps": {"main": {"source": "file", "node": "n1", "for": "System"}}}

    def owner_of(self, p, i):
        return "System" if p == "nginx-vps" else p

    def _instance_node(self, p, i):
        return "n1"

    def _pname(self, p, i):
        return p

    def on_node(self, nid):
        import contextlib
        return contextlib.nullcontext()

    def _config(self, p, i):
        return self.cfg.get(p)

    def _services(self, cfg):
        return cfg.get("services") or {}

    def _run(self, argv, timeout=0):
        img = argv[-1]
        if img not in self.pulled:
            return {"code": 1, "out": "Error: No such image"}
        return {"code": 0, "out": json.dumps([f"{img.rsplit(':', 1)[0]}@{self.pulled[img]}"])}


class ImageCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        A, B = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        self.A, self.B = A, B
        self.dv = FakeDevapp({"radarr": {"services": {"app": {"image": "lscr.io/linuxserver/radarr:latest"},
                                                      "db": {"image": "mariadb:11"}}},
                              "site": {"services": {"web": {"build": {"context": "."}},
                                                    "db": {"image": "mariadb:11"},
                                                    "cache": {"image": "redis@" + A}}}},
                             {"lscr.io/linuxserver/radarr:latest": A, "mariadb:11": B})
        imagecheck.configure(state=self.tmp, write_json=write_json, devapp_module=self.dv)
        self.addCleanup(setattr, imagecheck, "DIGESTS_FILE", imagecheck.DIGESTS_FILE)
        imagecheck.DIGESTS_FILE = f"{self.tmp}/digests.json"
        write_json(imagecheck.DIGESTS_FILE, {"lscr.io/linuxserver/radarr:latest": B, "mariadb:11": B})

    def test_a_reference_is_read_as_a_registry_would(self):
        self.assertEqual(imagecheck.parse_ref("mariadb:11"), ("registry-1.docker.io", "library/mariadb", "11"))
        self.assertEqual(imagecheck.parse_ref("linuxserver/radarr"), ("registry-1.docker.io", "linuxserver/radarr", "latest"))
        self.assertEqual(imagecheck.parse_ref("ghcr.io/aquilaelabs/builderbot:latest"),
                         ("ghcr.io", "aquilaelabs/builderbot", "latest"))
        self.assertEqual(imagecheck.parse_ref("localhost:5000/app:1"), ("localhost:5000", "app", "1"))
        self.assertIsNone(imagecheck.parse_ref("nginx:1.29-alpine@sha256:" + "c" * 64), "pinned by digest: not asked")

    def test_only_registry_images_by_tag_are_asked(self):
        self.assertEqual(imagecheck.registry_images("site", "main"), [("db", "mariadb:11")],
                         "not the built one, not the one pinned by digest")

    def test_behind_until_updated_and_the_bell_row(self):
        r = imagecheck.check()
        self.assertEqual((r["checked"], r["behind"]), (2, 1), "nginx (System) is its own tab's")
        self.assertEqual([b["image"] for b in imagecheck.of("radarr")["behind"]], ["lscr.io/linuxserver/radarr:latest"],
                         "radarr's moved; its mariadb is the registry's own")
        self.assertEqual(imagecheck.of("site")["behind"], [])
        self.assertGreater(imagecheck.last_at(), 0)
        rows = imagecheck.attention(lambda nid: {"n1": "vps"}[nid])
        self.assertEqual([(r["kind"], r["node"], r["containers"]) for r in rows],
                         [("image", "vps", [{"name": "radarr", "images": ["lscr.io/linuxserver/radarr:latest"]}])])
        imagecheck.forget("radarr")
        self.assertEqual(imagecheck.of("radarr")["behind"], [], "Update pulled it")
        self.assertEqual(imagecheck.attention(lambda nid: nid), [])

    def test_the_bell_row_holds_only_the_projects_the_account_may_act_on(self):
        imagecheck.check()
        self.assertEqual(imagecheck.of("radarr")["project"], "radarr", "the check records whose it is")
        self.assertEqual(imagecheck.attention(lambda nid: nid, allowed=lambda p: p == "site"), [],
                         "radarr's update is news only to who may act on radarr")
        self.assertEqual(len(imagecheck.attention(lambda nid: nid, allowed=lambda p: p == "radarr")), 1)
        # An answer from before the check recorded the project: found by name.
        d = json.loads(imagecheck._file().read_text())
        d["radarr"].pop("project")
        write_json(imagecheck._file(), d)
        self.assertEqual(len(imagecheck.attention(lambda nid: nid, allowed=lambda p: p == "radarr")), 1)

    def test_an_image_never_pulled_is_not_compared_and_a_registry_that_will_not_say_is_said(self):
        self.dv.pulled.pop("mariadb:11")
        write_json(imagecheck.DIGESTS_FILE, {"lscr.io/linuxserver/radarr:latest": self.A})
        imagecheck.check()
        self.assertEqual(imagecheck.of("radarr")["behind"], [])
        self.assertEqual(imagecheck.of("site")["error"], "", "never pulled: nothing asked")


if __name__ == "__main__":
    unittest.main()
