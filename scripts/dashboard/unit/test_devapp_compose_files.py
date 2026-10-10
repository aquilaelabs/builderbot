"""Every compose file in a project, each sent to Docker on its own (the
operator, 10 Oct): which files are found, the folder each one's compose
calls run in, and the name Send offers, named for what the project is called
now rather than its folder."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


class ComposeFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="composefiles-"))
        self.was = {k: getattr(devapp, k, None) for k in
                    ("WORKSPACE", "STATE", "FILE", "OWNERS", "ENVDIR", "write_json", "label_of")}
        ws, st = self.tmp / "ws", self.tmp / "state"
        st.mkdir()
        devapp.configure(workspace=ws, state=st, write_json=write_json)
        p = ws / "Clanker-Detector"
        for rel in ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.override.yml",
                    "site/compose.yaml", "api/v2/compose.yml", "node_modules/x/compose.yml",
                    "a/b/c/d/compose.yml", ".hidden/compose.yml", "notes.yml"):
            (p / rel).parent.mkdir(parents=True, exist_ok=True)
            (p / rel).write_text("services: {}\n")
        (p / "site" / ".env.example").write_text("SITE=1\n")
        (p / ".env.example").write_text("ROOT=1\n")
        os.symlink(p / "site" / "compose.yaml", p / "linked-compose.yml")
        self.p = p

    def tearDown(self):
        for k, v in self.was.items():
            setattr(devapp, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_compose_file_is_found_the_roots_own_first(self):
        self.assertEqual(devapp.compose_files("Clanker-Detector"),
                         ["docker-compose.yml", "docker-compose.prod.yml", "api/v2/compose.yml",
                          "site/compose.yaml"])

    def test_an_override_a_link_a_skipped_folder_and_too_deep_are_not(self):
        got = devapp.compose_files("Clanker-Detector")
        for no in ("docker-compose.override.yml", "linked-compose.yml", "node_modules/x/compose.yml",
                   "a/b/c/d/compose.yml", ".hidden/compose.yml", "notes.yml"):
            self.assertNotIn(no, got)

    def test_a_container_made_from_a_file_in_a_folder_runs_compose_there(self):
        r = devapp.create_instance("Clanker-Detector", "site", compose="site/compose.yaml")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(devapp.compose_file("Clanker-Detector", "site"), self.p / "site" / "compose.yaml")
        argv = devapp._compose("Clanker-Detector", "site", "config")
        self.assertEqual(argv[argv.index("--project-directory") + 1], str(self.p / "site"))
        self.assertEqual(devapp.example_file("Clanker-Detector", "site"), self.p / "site" / ".env.example")
        r = devapp.create_instance("Clanker-Detector", "api", compose="api/v2/compose.yml")
        self.assertTrue(r.get("ok"), r)
        self.assertFalse(devapp.example_file("Clanker-Detector", "api").is_file(),
                         "a folder with no example of its own does not take the root's")
        self.assertEqual(devapp.missing_env("Clanker-Detector", "api"), [])
        # ...and the project's own container stays on the root's file.
        argv = devapp._compose("Clanker-Detector", devapp.MAIN, "config")
        self.assertEqual(argv[argv.index("--project-directory") + 1], str(self.p))
        self.assertEqual(devapp.compose_file("Clanker-Detector"), self.p / "docker-compose.yml")

    def test_a_file_that_is_not_one_of_its_compose_files_is_refused(self):
        for bad in ("../other/compose.yml", "notes.yml", "linked-compose.yml"):
            r = devapp.create_instance("Clanker-Detector", "x", compose=bad)
            self.assertIn("has no compose file", r.get("error", ""), bad)

    def test_send_offers_the_shown_name_with_the_files_folder_or_variant(self):
        devapp.label_of = lambda p: "Turing Lens" if p == "Clanker-Detector" else p
        self.assertEqual(devapp.send_name("Clanker-Detector"), "turing-lens")
        self.assertEqual(devapp.send_name("Clanker-Detector", "site/compose.yaml"), "turing-lens-site")
        self.assertEqual(devapp.send_name("Clanker-Detector", "docker-compose.prod.yml"), "turing-lens-prod")
        devapp.create_instance("Clanker-Detector", "turing-lens-site", compose="site/compose.yaml")
        self.assertEqual(devapp.send_name("Clanker-Detector", "site/compose.yaml"), "turing-lens-site-2")

    def test_a_project_never_renamed_is_offered_its_own_container_first(self):
        devapp.label_of = lambda p: p
        self.assertEqual(devapp.send_name("Clanker-Detector"), "Clanker-Detector")


    def test_a_file_compose_cannot_read_says_what_compose_said(self):
        """The Artifacts row carried "compose cannot read it" and nothing of
        why (Turing Lens, 10 Oct): compose's own last lines go with it."""
        was = devapp._run
        devapp._run = lambda *a, **k: {"code": 15, "out": "noise\nservice \"web\" refers to undefined network front: invalid compose project"}
        try:
            self.assertIsNone(devapp._config("Clanker-Detector"))
            self.assertIn("undefined network front", devapp.config_error())
            devapp._run = lambda *a, **k: {"code": 0, "out": "{}"}
            self.assertEqual(devapp._config("Clanker-Detector"), {})
            self.assertEqual(devapp.config_error(), "", "a read that worked clears it")
        finally:
            devapp._run = was

if __name__ == "__main__":
    unittest.main()
