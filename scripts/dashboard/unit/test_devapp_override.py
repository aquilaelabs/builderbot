"""An instance's override (the operator, 17 Oct): another compose file from
the project's tree laid over its own with compose's -f after -f, for that
one container; never one outside the tree, never the file it is built from,
never loaded by itself, and carried to an agent node with the base file."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
import devactions  # noqa: E402


def write_json(path, d):
    with open(path, "w") as f:
        json.dump(d, f)


class Override(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="override-"))
        self.was = {k: getattr(devapp, k, None) for k in
                    ("WORKSPACE", "STATE", "FILE", "OWNERS", "ENVDIR", "write_json", "label_of")}
        ws, st = self.tmp / "ws", self.tmp / "state"
        st.mkdir()
        devapp.configure(workspace=ws, state=st, write_json=write_json)
        p = ws / "alpha"
        for rel in ("compose.yml", "compose.override.yml", "deploy/staging.override.yml", "other/compose.yml"):
            (p / rel).parent.mkdir(parents=True, exist_ok=True)
            (p / rel).write_text("services:\n  web:\n    build: .\n")
        (self.tmp / "outside.yml").write_text("services: {}\n")
        self.assertTrue(devapp.create_instance("alpha", "web-a").get("ok"))

    def tearDown(self):
        for k, v in self.was.items():
            setattr(devapp, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_override_files_include_the_override_ones(self):
        got = devapp.override_files("alpha")
        self.assertIn("compose.override.yml", got)
        self.assertIn("deploy/staging.override.yml", got)
        self.assertNotIn("compose.override.yml", devapp.compose_files("alpha"))

    def test_one_from_the_tree_is_laid_over_with_a_second_f(self):
        self.assertTrue(devapp.set_override("alpha", "web-a", "deploy/staging.override.yml").get("ok"))
        argv = devapp._compose("alpha", "web-a", "config")
        fs = [argv[i + 1] for i, a in enumerate(argv) if a == "-f"]
        self.assertEqual(len(fs), 2)
        self.assertTrue(fs[0].endswith("compose.yml") and fs[1].endswith("deploy/staging.override.yml"), fs)

    def test_none_is_one_f_and_nothing_loads_by_itself(self):
        argv = devapp._compose("alpha", "web-a", "config")
        self.assertEqual(argv.count("-f"), 1)
        self.assertTrue(devapp.set_override("alpha", "web-a", "compose.override.yml").get("ok"))
        self.assertTrue(devapp.set_override("alpha", "web-a", "").get("ok"))
        self.assertEqual(devapp._compose("alpha", "web-a", "config").count("-f"), 1)

    def test_outside_the_tree_or_its_own_file_is_refused(self):
        self.assertIn("no compose file", devapp.set_override("alpha", "web-a", "../outside.yml")["error"])
        self.assertIn("no compose file", devapp.set_override("alpha", "web-a", "nope.yml")["error"])
        self.assertIn("built from", devapp.set_override("alpha", "web-a", "compose.yml")["error"])

    def test_it_travels_to_an_agent_node_with_the_base_file(self):
        devapp.set_override("alpha", "web-a", "compose.override.yml")
        files = devactions._plan_spec("alpha", "web-a", "up")["files"]
        self.assertIn("override.yml", files)
        steps = devactions._plan("alpha", "web-a", "up")
        self.assertIn("{cdir}/override.yml", steps[0]["argv"])

    def test_two_instances_each_lay_their_own(self):
        self.assertTrue(devapp.create_instance("alpha", "web-b").get("ok"))
        devapp.set_override("alpha", "web-a", "compose.override.yml")
        devapp.set_override("alpha", "web-b", "deploy/staging.override.yml")
        a = devapp._compose("alpha", "web-a", "config")
        b = devapp._compose("alpha", "web-b", "config")
        self.assertTrue(a[-2].endswith("compose.override.yml") or "compose.override.yml" in " ".join(a))
        self.assertIn("staging.override.yml", " ".join(b))
        self.assertNotIn("staging.override.yml", " ".join(a))
        self.assertNotEqual(a[a.index("--project-name") + 1], b[b.index("--project-name") + 1])


if __name__ == "__main__":
    unittest.main()
