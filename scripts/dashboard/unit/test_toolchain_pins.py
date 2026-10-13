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


class Implied(unittest.TestCase):
    """What a build needs with no line pinning it (R215): the build-tools its
    Android Gradle plugin defaults to, and an emulator image for compileSdk."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.proj = self.ws / "shebang"
        (self.proj / "app").mkdir(parents=True)
        (self.proj / "app" / "build.gradle.kts").write_text("android {\n    compileSdk = 37\n}\n")
        self.was = (toolchains.project_nodes, toolchains.WORKSPACE)
        toolchains.project_nodes = lambda: {"shebang": "n_1"}
        toolchains.WORKSPACE = self.ws

    def tearDown(self):
        toolchains.project_nodes, toolchains.WORKSPACE = self.was
        self.tmp.cleanup()

    def catalog(self, text):
        (self.proj / "gradle").mkdir(exist_ok=True)
        (self.proj / "gradle" / "libs.versions.toml").write_text(text)

    def test_the_plugin_version_is_read_where_a_project_names_it(self):
        self.assertEqual(toolchains.agp_version(self.proj), ("", ""))
        self.catalog('[versions]\nagp = "9.4.1"\n[plugins]\n'
                     'android-application = { id = "com.android.application", version.ref = "agp" }\n')
        self.assertEqual(toolchains.agp_version(self.proj), ("9.4.1", "gradle/libs.versions.toml"))
        self.catalog('[plugins]\nandroid-library = { id = "com.android.library", version = "8.9.2" }\n')
        self.assertEqual(toolchains.agp_version(self.proj), ("8.9.2", "gradle/libs.versions.toml"))
        self.catalog("[versions]\nkotlin = \"2.2.0\"\n")
        (self.proj / "settings.gradle.kts").write_text(
            'plugins {\n    id("com.android.application") version "8.13.0" apply false\n}\n')
        self.assertEqual(toolchains.agp_version(self.proj), ("8.13.0", "settings.gradle.kts"))
        (self.proj / "settings.gradle.kts").unlink()
        (self.proj / "build.gradle").write_text(
            "buildscript {\n  dependencies {\n    classpath 'com.android.tools.build:gradle:7.4.2'\n  }\n}\n")
        self.assertEqual(toolchains.agp_version(self.proj), ("7.4.2", "build.gradle"))

    def test_each_plugin_release_defaults_to_one_build_tools(self):
        for ver, bt in (("9.4.1", "36.0.0"), ("9.0.0", "36.0.0"), ("8.13.0", "35.0.0"), ("8.7.0", "35.0.0"),
                        ("8.6.1", "34.0.0"), ("8.2.0", "34.0.0"), ("8.1.4", "33.0.1"), ("8.0.0", "33.0.1"),
                        ("7.4.2", "30.0.3"), ("7.0.4", "30.0.2")):
            self.assertEqual(toolchains.agp_build_tools(ver), bt, ver)
        # Older than the table, newer than it, or not a version: no guess.
        for ver in ("4.2.2", "10.0.0", "", "latest"):
            self.assertEqual(toolchains.agp_build_tools(ver), "", ver)

    def test_what_a_build_needs_without_pinning_it(self):
        self.catalog('[versions]\nagp = "9.4.1"\n[plugins]\n'
                     'android-application = { id = "com.android.application", version.ref = "agp" }\n')
        self.assertEqual(toolchains.gradle_needs(self.proj), {
            "build-tools;36.0.0": ["gradle/libs.versions.toml: the Android Gradle plugin 9.4.1 defaults to it"],
            "system-images;android-37;google_apis;x86_64": ["app/build.gradle.kts: compileSdk 37"]})
        # A pinned buildToolsVersion is the project's own answer.
        (self.proj / "app" / "build.gradle.kts").write_text(
            'android {\n    compileSdk = 37\n    buildToolsVersion = "37.0.0"\n}\n')
        self.assertNotIn("build-tools;36.0.0", toolchains.gradle_needs(self.proj))

    def test_the_rows_say_what_implies_them_and_whether_the_store_holds_it(self):
        self.catalog('[versions]\nagp = "9.4.1"\n[plugins]\n'
                     'android-application = { id = "com.android.application", version.ref = "agp" }\n')
        rep = {"store_dirs": {"versions": {"build-tools": ["37.0.0"], "platforms": ["android-37.0"]}},
               "images": [{"id": "system-images;android-36;google_apis_playstore;x86_64", "api": "36"}]}
        rows = {r["name"]: r for r in toolchains.pin_rows("n_1", rep)}
        self.assertEqual(sorted(rows), ["android:build-tools;36.0.0", "android:platforms;android-37",
                                        "android:system-images;android-37;google_apis;x86_64"])
        bt = rows["android:build-tools;36.0.0"]
        self.assertFalse(bt["installed"])
        self.assertEqual(bt["label"], "Android SDK Build-Tools 36.0.0")
        self.assertIn("the Android Gradle plugin 9.4.1 defaults to it", bt["about"])
        self.assertIn("lacks it", bt["about"])
        im = rows["android:system-images;android-37;google_apis;x86_64"]
        self.assertFalse(im["installed"], "a 36 image is not a 37 one")
        self.assertEqual(im["label"], "Android emulator image 37")
        self.assertIn("compileSdk 37", im["about"])
        self.assertIn("lacks one", im["about"])
        # Any flavor of the level counts as held.
        rep["images"].append({"id": "system-images;android-37;google_apis_playstore;x86_64", "api": "37"})
        rows = {r["name"]: r for r in toolchains.pin_rows("n_1", rep)}
        self.assertTrue(rows["android:system-images;android-37;google_apis;x86_64"]["installed"])
        # An agent that reports no images cannot say a level is missing.
        del rep["images"]
        self.assertNotIn("android:system-images;android-37;google_apis;x86_64",
                         {r["name"] for r in toolchains.pin_rows("n_1", rep)})


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
