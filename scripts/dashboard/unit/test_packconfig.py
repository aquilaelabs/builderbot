"""What a pack is configured with per node (R172): each answer checked by
its field's kind, a secret sealed and shown only as set, the hello's rows
with the secrets opened and the environment names a verb reads, a pack's
answers dropped with it, and every seal refreshed after the key changed."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import packconfig  # noqa: E402

FIELDS = [{"name": "api_key", "label": "API key", "kind": "secret", "env": "HEX_KEY", "required": True},
          {"name": "region", "label": "Region", "kind": "choice", "choices": [{"value": "eu", "label": "EU"}, {"value": "us", "label": "US"}], "env": "HEX_REGION"},
          {"name": "verbose", "label": "Verbose", "kind": "switch", "env": "HEX_VERBOSE"},
          {"name": "hosts", "label": "Hosts", "kind": "list", "env": "HEX_HOSTS",
           "fields": [{"name": "name", "label": "Name", "kind": "text"}, {"name": "key", "label": "Key", "kind": "secret"}]},
          {"name": "projects", "label": "Projects", "kind": "projects"}]


class Keeper(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.sealed = []
        packconfig.configure(state=self.d.name, write_json=lambda p, o: open(p, "w").write(json.dumps(o)),
                             seal=lambda b: b"S" + b, unseal=lambda b: b[1:], sealing=lambda: True, store_root=lambda nid: "/mnt/SDK/n_1")

    def tearDown(self):
        packconfig.configure(state="/nonexistent", write_json=None, seal=None, unseal=None, sealing=None, store_root=None)
        self.d.cleanup()

    def test_answers_are_checked_kept_sealed_and_shown_as_set(self):
        self.assertIn("required", packconfig.set_values("n_1", "hexkit", FIELDS, {"region": "eu"})["error"])
        self.assertIn("one of", packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "k1", "region": "mars"})["error"])
        self.assertIn("lists project names", packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "k1", "projects": "web"})["error"])
        r = packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "k1", "region": "eu", "verbose": True,
                                                            "hosts": [{"name": "a", "key": "ka"}], "projects": ["web", "web", "app"]})
        self.assertEqual(r["values"], {"api_key": True, "region": "eu", "verbose": True, "hosts": [{"name": "a", "key": True}], "projects": ["app", "web"]})
        raw = json.load(open(os.path.join(self.d.name, "packconfig.json")))["n_1"]["hexkit"]
        self.assertTrue(raw["api_key"].startswith("sealed:") and raw["hosts"][0]["key"].startswith("sealed:"))
        self.assertNotIn("k1", json.dumps(raw))
        # A secret left empty keeps what it had; "clear" takes it out.
        r = packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "", "region": "us", "hosts": [{"name": "a", "key": ""}]})
        self.assertEqual((r["values"]["api_key"], r["values"]["region"], r["values"]["hosts"][0]["key"]), (True, "us", True))
        self.assertIn("required", packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "clear"})["error"])

    def test_the_hello_carries_the_opened_values_and_the_env_names(self):
        packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "k1", "region": "eu", "verbose": True, "hosts": [{"name": "a", "key": "ka"}], "projects": ["web"]})
        packconfig.set_values("n_1", "other", [{"name": "x", "kind": "text"}], {"x": "y"})
        rows = packconfig.for_node("n_1", {"hexkit": FIELDS})
        self.assertEqual(len(rows), 1, "a pack whose manifest the controller no longer holds is not handed")
        row = rows[0]
        self.assertEqual((row["pack"], row["store"], row["values"]["api_key"], row["values"]["hosts"][0]["key"]), ("hexkit", "/mnt/SDK/n_1", "k1", "ka"))
        self.assertEqual(row["env"], {"HEX_KEY": "k1", "HEX_REGION": "eu", "HEX_VERBOSE": "1", "HEX_HOSTS": json.dumps([{"name": "a", "key": "ka"}])})
        self.assertEqual(packconfig.for_node("n_2", {"hexkit": FIELDS}), [])
        packconfig.forget("n_1", "hexkit")
        self.assertEqual(packconfig.for_node("n_1", {"hexkit": FIELDS}), [])
        self.assertEqual(packconfig.get("n_1", "hexkit", FIELDS)["api_key"], False)

    def test_seals_are_refreshed_after_the_key_changed(self):
        packconfig.set_values("n_1", "hexkit", FIELDS, {"api_key": "k1", "hosts": [{"name": "a", "key": "ka"}]})
        packconfig.configure(seal=lambda b: b"T" + b, unseal=lambda b: b[1:])
        self.assertEqual(packconfig.seal_all(again=True), 2)
        self.assertEqual(packconfig.for_node("n_1", {"hexkit": FIELDS})[0]["values"]["api_key"], "k1")


if __name__ == "__main__":
    unittest.main()
