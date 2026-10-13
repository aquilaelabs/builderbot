"""The versions a node's projects pin (B712): read off their Gradle files,
each a row of its own on the node's Toolchains tab, installed by the store's
own listing, and nothing from an agent that does not list versions."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402
import toolchains  # noqa: E402


class Pins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        app = self.ws / "shebang" / "app"
        voice = self.ws / "shebang" / "voice"
        app.mkdir(parents=True)
        voice.mkdir(parents=True)
        (app / "build.gradle.kts").write_text('android {\n    compileSdk = 37\n    buildToolsVersion = "36.0.0"\n}\n')
        (voice / "build.gradle.kts").write_text('android {\n    compileSdk = 37\n    ndkVersion = "29.0.14206865"\n}\n')
        # What a build writes is not read: a pin inside build/ is a copy.
        (voice / "build").mkdir()
        (voice / "build" / "build.gradle").write_text('ndkVersion "1.0.0"\n')
        (self.ws / "plain").mkdir()
        (self.ws / "plain" / "README.md").write_text("no gradle here\n")
        self.was = (toolchains.project_nodes, toolchains.WORKSPACE)
        toolchains.project_nodes = lambda: {"shebang": "n_1", "plain": "n_1", "elsewhere": "n_2"}
        toolchains.WORKSPACE = self.ws

    def tearDown(self):
        toolchains.project_nodes, toolchains.WORKSPACE = self.was
        self.tmp.cleanup()

    def test_pins_are_read_off_the_gradle_files(self):
        pins = toolchains.gradle_pins(self.ws / "shebang")
        self.assertEqual(pins, {"platforms;android-37": ["app/build.gradle.kts", "voice/build.gradle.kts"],
                                "build-tools;36.0.0": ["app/build.gradle.kts"],
                                "ndk;29.0.14206865": ["voice/build.gradle.kts"]})
        self.assertEqual(toolchains.gradle_pins(self.ws / "plain"), {})
        self.assertEqual(toolchains.gradle_pins(self.ws / "missing"), {})

    def test_a_pin_the_store_lacks_is_a_row_to_install(self):
        rep = {"store_dirs": {"android": ["ndk", "build-tools", "platforms"],
                              "versions": {"ndk": ["30.0.16248370"], "build-tools": ["37.0.0"],
                                           "platforms": ["android-37.0"]}}}
        rows = {r["name"]: r for r in toolchains.pin_rows("n_1", rep)}
        self.assertEqual(sorted(rows), ["android:build-tools;36.0.0", "android:ndk;29.0.14206865",
                                        "android:platforms;android-37"])
        ndk = rows["android:ndk;29.0.14206865"]
        self.assertFalse(ndk["installed"])
        self.assertEqual(ndk["label"], "Android NDK 29.0.14206865")
        self.assertIn("shebang (voice/build.gradle.kts)", ndk["about"])
        self.assertIn("lacks it", ndk["about"])
        self.assertEqual(ndk["pinned_by"], ["shebang"])
        # compileSdk 37 is held by the level's base, android-37.0.
        plat = rows["android:platforms;android-37"]
        self.assertTrue(plat["installed"])
        self.assertEqual(plat["label"], "Android SDK Platform 37")
        self.assertIn("holds it", plat["about"])

    def test_another_node_and_an_old_agent_get_no_rows(self):
        rep = {"store_dirs": {"android": ["ndk"], "versions": {"ndk": []}}}
        self.assertEqual(toolchains.pin_rows("n_2", rep), [])
        self.assertEqual(toolchains.pin_rows("n_1", {"store_dirs": {"android": ["ndk"]}}), [])

    def test_a_pin_is_held_by_its_directory(self):
        self.assertTrue(toolchains.pin_held("ndk;29.0.1", {"ndk": ["29.0.1", "30.0.2"]}))
        self.assertFalse(toolchains.pin_held("ndk;29.0.1", {"ndk": ["30.0.2"]}))
        self.assertTrue(toolchains.pin_held("platforms;android-36", {"platforms": ["android-36"]}))
        self.assertTrue(toolchains.pin_held("platforms;android-36", {"platforms": ["android-36.1"]}))
        self.assertFalse(toolchains.pin_held("platforms;android-36", {"platforms": ["android-360"]}))


class CensusKeepsVersions(unittest.TestCase):
    def test_the_versions_an_agent_lists_survive_the_census(self):
        got = nodes._census({"store_dirs": {"top": ["go"], "android": ["ndk"],
                                            "versions": {"ndk": ["30.0.1", "29.0.1"], "odd": "no", "platforms": []}}})
        self.assertEqual(got["store_dirs"]["versions"], {"ndk": ["30.0.1", "29.0.1"], "platforms": []})

    def test_an_agent_that_lists_none_leaves_the_key_out(self):
        got = nodes._census({"store_dirs": {"top": ["go"], "android": ["ndk"]}})
        self.assertNotIn("versions", got["store_dirs"])


if __name__ == "__main__":
    unittest.main()
