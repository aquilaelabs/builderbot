"""prefs.py's Also sees setting: which paths a project may be shown on its
node (B378). test/reads.mjs proves the dialog; this proves the rule."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prefs  # noqa: E402


class Sees(unittest.TestCase):
    def test_a_share_on_the_node_is_a_place(self):
        for p in ("/mnt/media", "/workspace-dev", "/srv/data_1"):
            self.assertEqual(prefs.sees_problem(p), "", p)

    def test_the_machine_and_builderbot_are_never(self):
        for p in ("/etc", "/home/x", "/root", "/workspace", "/proc/1", "/usr/local"):
            self.assertTrue(prefs.sees_problem(p), p)

    def test_a_path_that_is_not_a_plain_absolute_one_is_refused(self):
        for p in ("mnt/media", "/mnt/../etc", "/mnt/me dia", "/mnt/$(x)", ""):
            self.assertTrue(prefs.sees_problem(p), p)

    def test_stored_list_drops_bad_and_repeated_and_caps(self):
        many = [f"/mnt/d{i}" for i in range(prefs.SEES_MAX + 3)]
        got = prefs._sees_of({"sees": ["/mnt/a/", "/mnt/a", "/etc", *many]})
        self.assertEqual(got[0], "/mnt/a")
        self.assertNotIn("/etc", got)
        self.assertEqual(len(got), prefs.SEES_MAX)

    def test_a_record_without_the_setting_sees_nothing(self):
        self.assertEqual(prefs._sees_of({}), [])
        self.assertEqual(prefs._sees_of({"sees": "nope"}), [])


if __name__ == "__main__":
    unittest.main()


class Gpu(unittest.TestCase):
    """The project's GPU setting (R102): on unless somebody said otherwise,
    and stored only when it is not the default."""

    def setUp(self):
        import statefile
        import tempfile
        self.state = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.state, True)
        ws = os.path.join(self.state, "ws")
        os.makedirs(os.path.join(ws, "alpha"))
        self.was = prefs.WORKSPACE if hasattr(prefs, "WORKSPACE") else None
        prefs.configure(write_json=statefile.write_json, state=self.state)

    def test_on_by_default_and_off_when_set(self):
        self.assertEqual((prefs.get("alpha") or {}).get("gpu", "on"), "on")
        r = prefs.set_prefs("alpha", gpu="off")
        self.assertNotIn("error", r or {})
        self.assertEqual(prefs.get("alpha")["gpu"], "off")
        prefs.set_prefs("alpha", gpu="on")
        self.assertEqual((prefs.get("alpha") or {}).get("gpu", "on"), "on")

    def test_anything_else_is_refused(self):
        self.assertIn("error", prefs.set_prefs("alpha", gpu="maybe"))

    def test_daily_snapshots_on_by_default_and_stored_only_when_off(self):
        # R105: a project with nothing said takes one a day, as before.
        self.assertTrue(prefs.get("alpha")["snapshots_on"])
        self.assertNotIn("error", prefs.set_prefs("alpha", snapshots_on="off") or {})
        self.assertFalse(prefs.get("alpha")["snapshots_on"])
        prefs.set_prefs("alpha", snapshots_on=True)
        self.assertTrue(prefs.get("alpha")["snapshots_on"])
        with open(prefs.FILE) as f:
            self.assertNotIn("snapshots_on", f.read(), "the default is never written")


class NodeChanged(unittest.TestCase):
    """B488: the dialog sends every field on every save, so only a change
    to the node is a node change; and the primary counts on its own, not
    only the set (a move onto a node already in the set is a move, seen on
    the dev instance). The stored record is stubbed in the dev instance's
    exact shape: no primary, one node in the set."""
    def setUp(self):
        saved = prefs.get
        self.addCleanup(setattr, prefs, "get", saved)
        prefs.get = lambda project: {"node": "", "nodes": ["n1"]}

    def test_the_same_node_set_sent_back_is_not_a_change(self):
        self.assertFalse(prefs.node_changed("p", {"node": "", "nodes": ["n1"], "git_name": "x"}))
        self.assertFalse(prefs.node_changed("p", {"git_name": "x"}))

    def test_the_primary_moving_within_the_set_is_a_change(self):
        self.assertTrue(prefs.node_changed("p", {"node": "n1", "nodes": ["n1"]}))
        self.assertTrue(prefs.node_changed("p", {"node": "n2"}))
        self.assertTrue(prefs.node_changed("p", {"nodes": ["n1", "n2"]}))


class BuildLocal(unittest.TestCase):
    """Gradle builds on the node's disk unless the project says otherwise
    (B439): on by default, and stored only when turned off."""

    def test_on_unless_turned_off(self):
        self.assertTrue(prefs._clean({})["build_local"])
        self.assertTrue(prefs._clean({"build_local": "yes"})["build_local"])
        self.assertFalse(prefs._clean({"build_local": False})["build_local"])


class Reaches(unittest.TestCase):
    """Also reaches (the operator, 7 Oct): the addresses a project's sessions
    may still reach where their node filters, each on the nodes it names."""

    def test_an_address_or_an_address_and_port(self):
        for e in ("192.168.1.20", "10.0.0.5:8080", "172.16.3.4:1"):
            self.assertEqual(prefs.reaches_problem(e), "", e)

    def test_what_is_not_one_is_refused_with_why(self):
        for e, why in [("nas.lan", "not an address"), ("192.168.1.0/24", "not an address"),
                       ("300.1.1.1", "0 to 255"), ("127.0.0.1", "this machine"),
                       ("224.0.0.1", "multicast"), ("10.231.0.9", "sessions themselves"),
                       ("1.2.3.4:70000", "port is 1 to 65535")]:
            self.assertIn(why, prefs.reaches_problem(e), e)

    def test_a_bare_address_is_every_node_and_repeats_merge(self):
        got = prefs._reaches_of({"reaches": ["192.168.1.20",
                                             {"addr": "10.0.0.5:8080", "nodes": ["n2"]},
                                             {"addr": "10.0.0.5:8080", "nodes": ["n1"]},
                                             {"addr": "10.0.0.6", "nodes": ["n1"]},
                                             {"addr": "10.0.0.6", "nodes": []},
                                             "nope"]})
        self.assertEqual(got, [{"addr": "192.168.1.20", "nodes": []},
                               {"addr": "10.0.0.5:8080", "nodes": ["n1", "n2"]},
                               {"addr": "10.0.0.6", "nodes": []}])

    def test_each_node_gets_only_what_names_it(self):
        saved = prefs.get
        self.addCleanup(setattr, prefs, "get", saved)
        prefs.get = lambda p: {"reaches": [{"addr": "192.168.1.20", "nodes": []},
                                           {"addr": "10.0.0.5:8080", "nodes": ["n2"]}]}
        self.assertEqual(prefs.reaches_on("x", "n1"), ["192.168.1.20"])
        self.assertEqual(prefs.reaches_on("x", "n2"), ["192.168.1.20", "10.0.0.5:8080"])
