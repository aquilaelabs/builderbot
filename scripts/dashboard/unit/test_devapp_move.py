"""Moving a project's own container to another project (devapp.move_instance,
the operator, 8 Oct): rekeyed under the new project with the compose name it
already had, so its containers, env file and data directory are untouched,
pinned to the node it is on, its owner and branch said for the new home."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devactions  # noqa: E402
import devapp  # noqa: E402
import relocate  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Scripts(unittest.TestCase):
    """The pack and unpack scripts ride the plan's argv, where the agent
    rewrites the {cdir} placeholder wherever it stands: a variable of that
    name in the python pointed the helper's mount at the compose directory
    while the tar had gone into in/ (B659). And a failed stage's row says
    what the job last wrote, not where to look (B658)."""

    def test_the_scripts_never_spell_the_placeholder(self):
        for text in (relocate.PACK_PY, relocate.UNPACK_PY):
            self.assertNotIn("{cdir}", text)
            self.assertNotIn("cdir", text, "not even as a name, so an edit cannot bring it back")
        self.assertIn("filling the empty volume", relocate.UNPACK_PY, "an empty volume from a failed try is filled")
        self.assertIn("writing over what the volume", relocate.UNPACK_PY,
                      "one with files is written over, said in the log (the dialog warned; the operator, 14 Oct)")
        self.assertNotIn("remove it first", relocate.UNPACK_PY, "no longer refused")

    def test_a_failed_step_says_its_last_telling_line(self):
        """A compose step's row carries the last line that says something
        (B658: the whole tail, newlines flattened, read as a wall)."""
        out = (" Network x_default Creating \n Network x_default Created \n Container x-db-1 Creating \n"
               " service:db:1 Error response from daemon: No such image: mariadb:11 \n Container x-web-1 Creating \n"
               "Error response from daemon: No such image: mariadb:11\n")
        self.assertEqual(devactions.last_line(out), "Error response from daemon: No such image: mariadb:11")
        self.assertEqual(devactions.last_line("$ docker compose up\n Container x Creating \n"), "Container x Creating",
                         "with nothing telling, the last line there is")
        self.assertEqual(devactions.last_line(""), "")

    def test_a_failed_stage_carries_the_last_line_written(self):
        class Q:
            def job(self, jid, with_log=False):
                return {"id": jid, "log": "compose\n$ python3 -c\n    code\nmaking the volume x\ntar: can't open '/i/vol-0.tgz': No such file or directory\nTraceback (most recent call last):\n    more\n"}
        saved = devapp.queue
        devapp.queue = Q()
        try:
            self.assertEqual(relocate._last_said({"id": "j_1"}), "tar: can't open '/i/vol-0.tgz': No such file or directory")
        finally:
            devapp.queue = saved


class Move(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ws = Path(self.tmp) / "ws"
        for p in ("MediaReducer-Dev", "MediaReducer", "Bare"):
            (ws / p).mkdir(parents=True)
        for p in ("MediaReducer-Dev", "MediaReducer"):
            (ws / p / "docker-compose.yml").write_text("services: {}\n")
        self.nodes = {"MediaReducer-Dev": ["n1"], "MediaReducer": ["n1"], "Bare": ["n1"], "Far": ["n2"]}
        devapp.configure(workspace=ws, state=self.tmp, write_json=write_json,
                         project_nodes=lambda p: self.nodes.get(p, []),
                         project_node=lambda p: (self.nodes.get(p) or [""])[0])
        write_json(devapp.FILE, {
            "MediaReducer-Dev": {"main": {"ref": "claude/aquilaelabs-links", "built_ref": "abc"}},
            "mediareducer-test-plex": {"main": {"source": "file", "for": "MediaReducer-Dev"}}})

    def test_it_keeps_its_name_env_and_data(self):
        was = (devapp._pname("MediaReducer-Dev"), devapp.env_path("MediaReducer-Dev"))
        r = devapp.move_instance("MediaReducer-Dev", "main", "MediaReducer")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual((r["instance"], r["name"], r["dropped_ref"]),
                         ("mediareducer-dev", "mediareducer-dev", "claude/aquilaelabs-links"))
        self.assertEqual((devapp._pname("MediaReducer", "mediareducer-dev"),
                          devapp.env_path("MediaReducer", "mediareducer-dev")), was)
        d = devapp._load()
        self.assertNotIn("MediaReducer-Dev", d)
        rec = d["MediaReducer"]["mediareducer-dev"]
        self.assertEqual(rec.get("node"), "n1", "pinned where its data is")
        self.assertNotIn("ref", rec)
        self.assertEqual(devapp.owner_of("MediaReducer", "mediareducer-dev"), "MediaReducer")
        self.assertEqual(devapp.compose_file("MediaReducer", "mediareducer-dev").parent.name, "MediaReducer")

    def test_what_it_refuses(self):
        self.assertIn("project picker", devapp.move_instance("mediareducer-test-plex", "main", "MediaReducer")["error"])
        self.assertIn("no compose file", devapp.move_instance("MediaReducer-Dev", "main", "Bare")["error"])
        self.assertIn("another project", devapp.move_instance("MediaReducer-Dev", "main", "MediaReducer-Dev")["error"])
        self.assertIn("no instance", devapp.move_instance("MediaReducer-Dev", "nope", "MediaReducer")["error"])
        (Path(self.tmp) / "ws" / "Far").mkdir()
        (Path(self.tmp) / "ws" / "Far" / "compose.yml").write_text("services: {}\n")
        self.assertIn("out of reach", devapp.move_instance("MediaReducer-Dev", "main", "Far")["error"])
        d = devapp._load()
        d["MediaReducer"] = {"mediareducer-dev": {}}
        write_json(devapp.FILE, d)
        self.assertIn("already has", devapp.move_instance("MediaReducer-Dev", "main", "MediaReducer")["error"])


if __name__ == "__main__":
    unittest.main()
