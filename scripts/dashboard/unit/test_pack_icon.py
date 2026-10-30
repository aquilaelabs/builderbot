"""A pack's or an app's own icon on its Library card (R182): named in its
manifest, read from its files at the commit it is pinned to, held to the
image its name says and the size cap, kept under the state and taken away
with it, never anything but bytes the server hands back as an image."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nasapps  # noqa: E402
import toolpacks  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16"/></svg>'
BASE = {"name": "hexkit", "label": "Hex kit", "about": "Looks inside binaries.", "platforms": ["linux/amd64"],
        "install": {"steps": [["sh", "{dir}/install.sh"]]}, "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
        "verbs": {"dump": {"about": "A file as hex.", "usage": "FILE", "run": ["{dir}/bin/hexkit", "dump", "{args}"]}}}


def reader(files):
    def read(rel, cap):
        b = files.get(rel)
        return None if b is None else b[:cap + 1]
    return read


class Icon(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        toolpacks.configure(state=self.d, write_json=lambda p, v: Path(p).write_text(json.dumps(v)))
        nasapps.configure(state=self.d, write_json=lambda p, v: Path(p).write_text(json.dumps(v)))

    def examine(self, icon_name, data):
        m = dict(BASE, icon=icon_name)
        files = {"bbtool.json": json.dumps(m).encode()}
        if data is not None:
            files[icon_name] = data
        return toolpacks._examine(reader(files), (), "none")

    def test_the_manifest_names_a_png_webp_or_svg_inside_the_pack(self):
        self.assertEqual(toolpacks.validate(dict(BASE, icon="art/icon.png"))[1], [])
        for bad in ("/etc/icon.png", "../icon.png", "icon.gif", "icon"):
            self.assertTrue(any("icon names a PNG, WebP or SVG" in e for e in toolpacks.validate(dict(BASE, icon=bad))[1]), bad)

    def test_its_bytes_are_the_image_its_name_says_and_under_the_cap(self):
        self.assertIn("icon_bytes", self.examine("icon.png", PNG))
        self.assertIn("icon_bytes", self.examine("icon.svg", SVG))
        self.assertIn("not a PNG image", self.examine("icon.png", b"<html>").get("error", ""))
        self.assertIn("not an SVG image", self.examine("icon.svg", b"plain text").get("error", ""))
        self.assertIn("64 KB at most", self.examine("icon.png", PNG + b"\0" * toolpacks.ICON_MAX).get("error", ""))
        self.assertIn("it is not there", self.examine("icon.png", None).get("error", ""))

    def test_it_is_kept_by_the_packs_name_served_by_its_type_and_taken_away_with_it(self):
        got = self.examine("icon.svg", SVG)
        self.assertEqual(toolpacks._keep_icon("hexkit", got), "svg")
        self.assertEqual(toolpacks.icon_of("hexkit"), (SVG, "image/svg+xml"))
        self.assertEqual(toolpacks._keep_icon("hexkit", self.examine("icon.png", PNG)), "png")
        self.assertEqual(toolpacks.icon_of("hexkit")[1], "image/png", "a new type replaces the old file")
        self.assertEqual(len(list((Path(self.d) / "pack-icons").iterdir())), 1)
        self.assertIsNone(toolpacks.icon_of("../hexkit"))
        toolpacks._keep_icon("hexkit", {})
        self.assertIsNone(toolpacks.icon_of("hexkit"))

    def test_an_apps_icon_is_kept_by_its_id_and_held_to_the_same_rules(self):
        self.assertEqual(nasapps.keep_icon("whoami", PNG, "png"), "png")
        self.assertEqual(nasapps.icon_of("whoami"), (PNG, "image/png"))
        self.assertEqual(nasapps.keep_icon("whoami", b"<html>", "png"), "", "not an image, not kept")
        self.assertIsNone(nasapps.icon_of("whoami"))
        self.assertIsNone(nasapps.icon_of("../x"))


if __name__ == "__main__":
    unittest.main()
