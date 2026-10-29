"""A pack kept from the vetted catalog, and the index moving its pin (R169
step 4): the Library's row for it carries the newer pin, the same address
and folder at another commit, so Catalog update opens the dialog on it with
what it changes marked; a pack by URL, one from another address or folder,
one the index withdrew and one at the pinned commit get none."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library  # noqa: E402

URL = "https://example.com/hexkit.git"


def item(commit, url=URL, path="", tier="vetted"):
    return {"name": "hexkit", "installed": True, "pack": {"url": url, "commit": commit, "path": path, "tier": tier, "verbs": ["dump"]}}


def entry(commit, **kw):
    return {"name": "hexkit", "url": URL, "commit": commit, "sha256": "a" * 64, "tier": "vetted", **kw}


def row(it, *entries):
    rows = library.rows({"items": [it], "platform": "linux/amd64"}, [], [], {"packs": list(entries)}, {})
    return [r for r in rows if r["name"] == "hexkit"]


class Repin(unittest.TestCase):
    def test_a_newer_pin_is_offered_on_the_kept_packs_row(self):
        got = row(item("1" * 40), entry("2" * 40))
        self.assertEqual(len(got), 1, "kept, the pack is its own row alone")
        self.assertEqual(got[0]["tier"], "vetted")
        self.assertEqual(got[0]["repin"], {"url": URL, "commit": "2" * 40, "sha256": "a" * 64, "path": "", "tier": "vetted"})

    def test_none_where_the_pin_is_the_one_kept_or_not_its_own(self):
        self.assertIsNone(row(item("2" * 40), entry("2" * 40))[0]["repin"])
        self.assertIsNone(row(item("1" * 40, url="https://example.com/other.git"), entry("2" * 40))[0]["repin"])
        self.assertIsNone(row(item("1" * 40, path="packs/hexkit"), entry("2" * 40))[0]["repin"])
        self.assertIsNone(row(item("1" * 40), entry("2" * 40, withdrawn=True))[0]["repin"])
        self.assertIsNone(row(item("1" * 40), entry("2" * 40, kind="app"))[0]["repin"])

    def test_a_folder_pack_follows_its_folder(self):
        got = row(item("1" * 40, path="packs/hexkit"), entry("2" * 40, path="packs/hexkit"))[0]["repin"]
        self.assertEqual((got["commit"], got["path"]), ("2" * 40, "packs/hexkit"))


if __name__ == "__main__":
    unittest.main()
