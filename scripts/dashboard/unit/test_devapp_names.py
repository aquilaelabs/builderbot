"""An instance answers to both its names (B338): the one it was made with
(bb devapp new NAME, its record's key) and the one the Containers page lists
it under after a rename there, which every bb devapp verb takes; an
instance name two projects share names neither."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class Names(unittest.TestCase):
    def setUp(self):
        saved = (devapp._load, devapp._names)
        self.addCleanup(lambda: setattr(devapp, "_load", saved[0]) or setattr(devapp, "_names", saved[1]))
        devapp._load = lambda: {"aquilaeLabs": {"aquilaelabs-site": {}, "main": {}},
                                "other": {"shared": {}}, "third": {"shared": {}}}
        devapp._names = lambda: {("aquilaeLabs", "aquilaelabs-site"): "aquilaelabs-astrojs",
                                 ("other", "shared"): "other-web", ("third", "shared"): "third-web"}

    def test_by_the_name_the_page_lists(self):
        self.assertEqual(devapp.row_named("aquilaelabs-astrojs"), ("aquilaeLabs", "aquilaelabs-site"))

    def test_by_its_own_name(self):
        self.assertEqual(devapp.row_named("aquilaelabs-site"), ("aquilaeLabs", "aquilaelabs-site"))

    def test_a_name_two_projects_share_names_neither(self):
        self.assertIsNone(devapp.row_named("shared"))


if __name__ == "__main__":
    unittest.main()
