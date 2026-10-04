"""Start on boot (R122): a container's restart policy is read with the list,
set by boot-on and boot-off through the same verb as start and stop, kept
for an instance of BuilderBot's own, and put back by the next listing when a
rebuild has reset it. Drives devapp and containers against a stand-in
docker that records what it was asked."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import containers  # noqa: E402
import devapp  # noqa: E402


class Boot(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.policy = {"aaaaaaaaaaaa": "no", "bbbbbbbbbbbb": "unless-stopped"}
        self.store = {"app": {"main": {}}}
        saved = {k: getattr(devapp, k) for k in ("_run", "_load", "_rec", "write_json", "_targets") if hasattr(devapp, k)}
        self.addCleanup(lambda: [setattr(devapp, k, v) for k, v in saved.items()])
        csaved = containers._targets
        self.addCleanup(setattr, containers, "_targets", csaved)

        def run(argv, timeout=None):
            self.asked.append(argv[1:])
            if argv[1] == "inspect":
                return {"code": 0, "out": "\n".join(f"{i}0000 {self.policy[i]}" for i in argv[4:])}
            if argv[1] == "update":
                pol = argv[3]
                for n in argv[4:]:
                    self.policy[{"app-main-web-1": "aaaaaaaaaaaa", "other": "bbbbbbbbbbbb"}[n]] = pol
                return {"code": 0, "out": ""}
            return {"code": 0, "out": ""}
        devapp._run = run
        devapp._load = lambda: self.store
        devapp._rec = lambda d, p, i: d[p][i]
        devapp.write_json = lambda path, d: None
        self.rows = [{"id": "aaaaaaaaaaaa", "name": "app-main-web-1", "project": devapp._pname("app", "main"), "ours": True},
                     {"id": "bbbbbbbbbbbb", "name": "other", "project": "", "ours": False}]

    def test_the_list_says_which_start_on_boot(self):
        devapp._boot_read(self.rows)
        self.assertEqual([r["boot"] for r in self.rows], [False, True])

    def test_boot_on_sets_the_policy_and_keeps_it_for_an_instance(self):
        containers._targets = lambda name: [self.rows[0]]
        r = containers.container_ctl("app-main-web-1", "boot-on")
        self.assertTrue(r["ok"], r)
        self.assertIn(["update", "--restart", "unless-stopped", "app-main-web-1"], self.asked)
        self.assertIs(self.store["app"]["main"]["boot"], True)

    def test_a_rebuild_that_reset_it_is_put_back_by_the_listing(self):
        self.store["app"]["main"]["boot"] = True             # chosen before a rebuild reset it to "no"
        devapp._boot_read(self.rows)
        self.assertIn(["update", "--restart", "unless-stopped", "app-main-web-1"], self.asked)
        self.assertTrue(self.rows[0]["boot"])
        self.assertTrue(self.rows[1]["boot"])               # not ours: read, never written

    def test_anything_else_is_refused(self):
        self.assertIn("error", containers.container_ctl("x", "boot-maybe"))


if __name__ == "__main__":
    unittest.main()
