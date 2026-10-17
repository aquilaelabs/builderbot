"""What a dev container's build ships beside the app (the operator, 17 Oct):
an image-only service its last build did not ship stops the build until a
person says yes to exactly that set; the first build takes what is there as
the baseline; a session carries no yes. And an env never steers compose
itself (COMPOSE_FILE, COMPOSE_PROJECT_NAME, COMPOSE_PROFILES)."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import devapp  # noqa: E402

APP = {"services": {"web": {"build": {"context": "."}}, "db": {"image": "postgres:16"}}}
MORE = {"services": {**APP["services"], "gitea": {"image": "gitea:1.24"}, "gitea-seed": {"image": "gitea:1.24"}}}


class Beside(unittest.TestCase):
    def setUp(self):
        self.rec = {}
        for name, fn in (("_read_rec", lambda p, i=devapp.MAIN: self.rec),
                         ("is_file_source", lambda p, i=devapp.MAIN: False),
                         ("_set_beside", lambda p, i, names: self.rec.__setitem__("beside", sorted(names)))):
            m = mock.patch.object(devapp, name, fn)
            m.start(); self.addCleanup(m.stop)

    def gate(self, cfg, yes=""):
        with mock.patch.object(devapp, "_config", lambda p, i=devapp.MAIN, env_extra=None: cfg):
            return devapp._beside_gate("alpha", "main", yes)

    def test_image_only_services_are_what_rides_beside(self):
        self.assertEqual(devapp.beside_services(MORE), ["db", "gitea", "gitea-seed"])

    def test_the_first_build_takes_the_baseline(self):
        self.assertEqual(self.gate(APP), "")
        self.assertEqual(self.rec["beside"], ["db"])

    def test_a_new_one_stops_the_build_and_names_it(self):
        self.gate(APP)
        why = self.gate(MORE)
        self.assertIn("gitea, gitea-seed", why)
        self.assertIn("beside the app", why)
        self.assertEqual(self.rec["beside"], ["db"])
        self.assertEqual(devapp.beside_new("alpha", "main", MORE), ["gitea", "gitea-seed"])

    def test_a_persons_yes_to_that_set_lets_it_ship_and_is_kept(self):
        self.gate(APP)
        self.assertNotEqual(self.gate(MORE, yes="not-the-digest"), "")
        self.assertEqual(self.gate(MORE, yes=devapp.beside_digest(["gitea", "gitea-seed"])), "")
        self.assertEqual(self.rec["beside"], ["db", "gitea", "gitea-seed"])
        self.assertEqual(self.gate(MORE), "")

    def test_one_taken_out_and_put_back_is_asked_about_again(self):
        self.gate(APP)
        self.gate(MORE, yes=devapp.beside_digest(["gitea", "gitea-seed"]))
        self.gate(APP)
        self.assertNotEqual(self.gate(MORE), "")


class ComposeControl(unittest.TestCase):
    def test_an_env_that_steers_compose_is_named(self):
        self.assertEqual(devapp.compose_control("A=1\nCOMPOSE_PROFILES=lab\nexport COMPOSE_FILE=x.yml\n# COMPOSE_PROJECT_NAME=no\n"),
                         ["COMPOSE_PROFILES", "COMPOSE_FILE"])
        self.assertEqual(devapp.compose_control("PORT=8080\nCOMPOSE_HTTP_TIMEOUT=200\n"), [])

    def test_writing_one_is_refused(self):
        r = devapp.write_env("alpha", "PORT=1\nCOMPOSE_PROFILES=lab\n", "main")
        self.assertIn("COMPOSE_PROFILES is not an env setting here", r.get("error", ""))


if __name__ == "__main__":
    unittest.main()
