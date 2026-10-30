"""Apps a NAS runs (R164 step 2): the catalog's shape, each app's compose
naming only blanks its environment fills, every image pinned to a tag, and
render holding the blanks to their shapes and making the secrets it is not
given."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nasapps  # noqa: E402


class Catalog(unittest.TestCase):
    def test_every_app_is_whole_and_pinned(self):
        for a in nasapps.catalog():
            app = nasapps.APPS[a["id"]]
            blanks = set(re.findall(r"\$\{([A-Z_]+)\}", app["compose"]))
            r = nasapps.render(a["id"], "/mnt/tank/apps/x", "/mnt/tank/media", "1000:1000", "Europe/Paris")
            self.assertNotIn("error", r, a["id"])
            keys = {ln.split("=", 1)[0] for ln in r["env"].splitlines() if ln}
            self.assertTrue(blanks <= keys, f"{a['id']}: {blanks - keys} not in its environment")
            for m in re.finditer(r"image: (\S+)", app["compose"]):
                self.assertRegex(m.group(1), r"^[\w./-]+:[\w.-]+$", f"{a['id']}: {m.group(1)} is not pinned to a tag")
                self.assertNotIn(":latest", m.group(1))
            self.assertIn(f"PORT={a['port']}", r["env"])

    def test_render_holds_the_blanks_and_makes_the_secrets(self):
        self.assertIn("no app called", nasapps.render("nope", "/mnt/a")["error"])
        self.assertIn("under /mnt", nasapps.render("jellyfin", "/home/x", "/mnt/m")["error"])
        self.assertIn("media or files folder", nasapps.render("jellyfin", "/mnt/tank/apps/j", "")["error"])
        self.assertIn("uid:gid", nasapps.render("jellyfin", "/mnt/tank/apps/j", "/mnt/m", ids="bob")["error"])
        self.assertIn("Region/City", nasapps.render("jellyfin", "/mnt/tank/apps/j", "/mnt/m", tz="not a zone!")["error"])
        self.assertIn("1 to 65535", nasapps.render("jellyfin", "/mnt/tank/apps/j", "/mnt/m", port=70000)["error"])
        r = nasapps.render("homeassistant", "/mnt/tank/apps/ha/", "", "1001:1001", "Europe/Paris", 8123)
        self.assertEqual(r["env"], "DATA=/mnt/tank/apps/ha\nPUID=1001\nPGID=1001\nTZ=Europe/Paris\nPORT=8123\n", "no media blank for an app without one")
        r = nasapps.render("nextcloud", "/mnt/tank/apps/nc", "/mnt/tank/files", secrets={"ADMIN_PASSWORD": "chosen one"})
        env = dict(ln.split("=", 1) for ln in r["env"].splitlines())
        self.assertEqual(env["ADMIN_PASSWORD"], "chosen one")
        self.assertGreaterEqual(len(env["DB_PASSWORD"]), 20, "a secret not given is made")
        self.assertIn("one line", nasapps.render("nextcloud", "/mnt/tank/apps/nc", "/mnt/tank/files", secrets={"DB_PASSWORD": "a\nb"})["error"])


COMPOSE = """services:
  notes:
    image: ghcr.io/example/notes:2.4.1
    ports:
      - "${PORT}:8080"
    volumes:
      - ${DATA}/notes:/data
"""


class Sideloaded(unittest.TestCase):
    """An app of a person's own (R170 step 3): checked before it is kept,
    kept beside the shipped ones at tier sideloaded, rendered as they are."""
    def setUp(self):
        import tempfile
        self.d = tempfile.TemporaryDirectory()
        import json
        nasapps.configure(state=self.d.name, write_json=lambda p, o: open(p, "w").write(json.dumps(o)))

    def tearDown(self):
        nasapps.configure(state="/nonexistent", write_json=None)
        self.d.cleanup()

    def test_the_check_holds_a_compose_to_the_shipped_rules(self):
        self.assertIn("paste", nasapps.check("")["error"])
        self.assertIn("services mapping", nasapps.check("x: 1\n")["error"])
        self.assertIn("not pinned", nasapps.check("services:\n  a:\n    image: foo\n")["error"])
        self.assertIn("not pinned", nasapps.check("services:\n  a:\n    image: foo:latest\n")["error"])
        self.assertIn("never built", nasapps.check("services:\n  a:\n    image: foo:1\n    build: .\n")["error"])
        self.assertIn("unknown blank SECRET", nasapps.check("services:\n  a:\n    image: foo:1\n    environment:\n      K: ${SECRET}\n    ports: ['${PORT}:1']\n")["error"])
        self.assertIn("${PORT}", nasapps.check("services:\n  a:\n    image: foo:1\n")["error"])
        seen = nasapps.check(COMPOSE)
        self.assertEqual(seen["blanks"], ["DATA", "PORT"])
        self.assertFalse(seen["media"])
        self.assertEqual(seen["services"][0]["image"], "ghcr.io/example/notes:2.4.1")

    def test_added_kept_rendered_and_removed(self):
        self.assertIn("shipped app", nasapps.add("jellyfin", "x", "y", 80, COMPOSE)["error"])
        self.assertIn("id is", nasapps.add("Notes!", "x", "y", 80, COMPOSE)["error"])
        self.assertIn("port", nasapps.add("notes", "Notes", "my notes", "x", COMPOSE)["error"])
        r = nasapps.add("notes", "Notes", "my notes", 8080, COMPOSE, by="ann")
        self.assertEqual(r["app"], "notes")
        self.assertIn("added already", nasapps.add("notes", "Notes", "my notes", 8080, COMPOSE)["error"])
        row = next(a for a in nasapps.catalog() if a["id"] == "notes")
        self.assertEqual((row["tier"], row["name"], row["port"], row["media"], row["by"]), ("sideloaded", "Notes", 8080, False, "ann"))
        self.assertEqual(next(a for a in nasapps.catalog() if a["id"] == "jellyfin")["tier"], "official")
        self.assertEqual(nasapps.source("notes")["compose"], COMPOSE)
        out = nasapps.render("notes", "/mnt/tank/apps/notes", port=8081)
        self.assertEqual(out["compose"], COMPOSE)
        self.assertIn("PORT=8081", out["env"])
        self.assertTrue(nasapps.add("notes", "Notes 2", "my notes", 8080, COMPOSE, replace=True)["replaced"])
        self.assertEqual(nasapps.source("notes")["name"], "Notes 2")
        self.assertEqual(nasapps.remove("notes"), {"ok": True})
        self.assertIn("error", nasapps.remove("notes"))
        self.assertFalse(any(a["id"] == "notes" for a in nasapps.catalog()))


if __name__ == "__main__":
    unittest.main()
