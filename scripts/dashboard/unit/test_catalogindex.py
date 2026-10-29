"""The vetted catalog's index (R169 step 2): signed by the maintainers'
key, verified against the public half the install ships before an entry
is read, a tampered or re-signed index refused with the one before kept,
each entry held to its shape, and a withdrawn pack the install holds put
on the bell."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import catalogindex  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    HAVE = True
except ImportError:
    HAVE = False

ENTRY = {"name": "ghidra", "url": "https://example.com/packs/ghidra", "commit": "a" * 40, "sha256": "b" * 64, "tier": "vetted", "withdrawn": False,
         "about": "a decompiler", "platforms": ["linux/amd64"]}


@unittest.skipUnless(HAVE, "the cryptography library signs the test's index")
class Index(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        catalogindex.configure(state=self.d)
        catalogindex._cache.update(at=0.0, index=None, error="")
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        pubfile = os.path.join(self.d, "catalog.pub")
        open(pubfile, "w").write("builderbot-catalog-ed25519 " + self.pub.hex() + "\n")
        catalogindex.PUB_FILE = pubfile

    def signed(self, packs):
        data = json.dumps({"version": 1, "generated": "2026-10-28T00:00:00Z", "packs": packs}).encode()
        sig = "builderbot-catalog-ed25519-signature " + self.priv.sign(data).hex() + "\n"
        return data, sig

    def test_a_signed_index_is_read_and_a_tampered_one_refused_with_the_last_kept(self):
        data, sig = self.signed([ENTRY, {"name": "Bad Name", "url": "https://x", "commit": "c" * 40, "sha256": "d" * 64}])
        files = {"index.json": data, "index.sig": sig.encode()}
        r = catalogindex.fetch("https://catalog.example/", opener=lambda u: files[u.rsplit("/", 1)[1]])
        self.assertNotIn("error", r, r)
        self.assertEqual([p["name"] for p in r["index"]["packs"]], ["ghidra"], "an entry out of shape is left out")
        self.assertEqual(r["index"]["packs"][0]["tier"], "vetted")
        self.assertTrue(os.path.exists(os.path.join(self.d, "catalog-index.json")))
        # Changed on the way: refused, the one before answered beside the reason.
        tampered = data.replace(b'"withdrawn": false', b'"withdrawn": true')
        files2 = {"index.json": tampered, "index.sig": sig.encode()}
        r2 = catalogindex.fetch("https://catalog.example/", opener=lambda u: files2[u.rsplit("/", 1)[1]])
        self.assertIn("does not match", r2["error"])
        self.assertEqual([p["name"] for p in r2["index"]["packs"]], ["ghidra"], "the index kept before stands")
        # Signed by another key: the same refusal.
        other = ed25519.Ed25519PrivateKey.generate()
        files3 = {"index.json": data, "index.sig": ("builderbot-catalog-ed25519-signature " + other.sign(data).hex()).encode()}
        self.assertIn("does not match", catalogindex.fetch("https://catalog.example/", opener=lambda u: files3[u.rsplit("/", 1)[1]])["error"])
        # The network gone: the one before, with the reason.
        def down(u):
            raise OSError("no route")
        r4 = catalogindex.fetch("https://catalog.example/", opener=down)
        self.assertIn("did not answer", r4["error"])
        self.assertEqual(len(r4["index"]["packs"]), 1)
        # Another address under Controller settings: neither the cache nor
        # the kept index is the old catalog's answer (B443).
        r5 = catalogindex.index("https://other.example/", opener=down)
        self.assertIn("did not answer", r5["error"])
        self.assertIsNone(r5["index"])
        self.assertEqual(len(catalogindex.index("https://catalog.example/", opener=down)["index"]["packs"]), 1)

    def test_without_a_shipped_key_nothing_is_trusted(self):
        catalogindex.PUB_FILE = os.path.join(self.d, "none.pub")
        data, sig = self.signed([ENTRY])
        self.assertIn("ships no catalog key", catalogindex.verify(data, sig))

    def test_a_withdrawn_pack_the_install_holds_is_on_the_bell(self):
        data, sig = self.signed([dict(ENTRY, withdrawn=True), dict(ENTRY, name="fine")])
        files = {"index.json": data, "index.sig": sig.encode()}
        catalogindex.fetch("https://catalog.example/", opener=lambda u: files[u.rsplit("/", 1)[1]])
        self.assertEqual(catalogindex.withdrawn(["ghidra", "fine", "other"]), ["ghidra"])
        rows = catalogindex.attention(["ghidra", "fine"])
        self.assertEqual((rows[0]["kind"], rows[0]["name"], rows[0]["key"]), ("pack", "ghidra", "pack:withdrawn:ghidra"))
        self.assertIn("remove it", rows[0]["said"])
        # Within the hour the kept copy answers without the network.
        self.assertEqual(len(catalogindex.index("https://catalog.example/", opener=down_fail)["index"]["packs"]), 2)


def down_fail(u):
    raise AssertionError("the kept index should have answered")


class Folders(unittest.TestCase):
    def test_an_entry_in_a_folder_keeps_its_path_and_a_bad_one_is_dropped(self):
        # R170 step 6: the catalog's own packs live in folders of its repository.
        good = {**ENTRY, "name": "jdk", "path": "packs/official/jdk", "kind": "app"}
        bad = {**ENTRY, "name": "evil", "path": "../etc"}
        plain = {**ENTRY, "name": "plain"}
        idx, why = catalogindex.parse(json.dumps({"version": 1, "generated": "x", "packs": [good, bad, plain]}).encode())
        self.assertEqual(why, "")
        self.assertEqual([(p["name"], p["path"], p["kind"]) for p in idx["packs"]], [("jdk", "packs/official/jdk", "app"), ("plain", "", "pack")])


class Kinds(unittest.TestCase):
    def test_an_entrys_kind_and_folder_are_kept(self):
        # R170 steps 6 and 7, R172: a pack, a Docker app or a service, in a folder of its repository.
        rows = [{**ENTRY, "name": "jdk", "path": "packs/official/jdk"}, {**ENTRY, "name": "whoami", "kind": "app", "path": "packs/apps/whoami"},
                {**ENTRY, "name": "model-router", "kind": "service"}, {**ENTRY, "name": "evil", "path": "../etc"}, {**ENTRY, "name": "odd", "kind": "thing"}]
        idx, why = catalogindex.parse(json.dumps({"version": 1, "generated": "x", "packs": rows}).encode())
        self.assertEqual(why, "")
        self.assertEqual([(p["name"], p["kind"], p["path"]) for p in idx["packs"]],
                         [("jdk", "pack", "packs/official/jdk"), ("whoami", "app", "packs/apps/whoami"), ("model-router", "service", ""), ("odd", "pack", "")])


if __name__ == "__main__":
    unittest.main()
