"""The coding agents' sign-ins sealed on a node (R126, tokenseal.py): the
node seals with an account's public key and cannot open what it sealed;
the controller makes the key from the install key; a key wrapped to the
agent's boot secret opens only there; a value outside the group, a wrong
key or a damaged seal is refused."""
import importlib.util
import json
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "tokenseal", os.path.join(os.path.dirname(__file__), "..", "..", "agent", "builderbot_agent", "tokenseal.py"))
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)

KEY = b"an install key of at least sixteen bytes"


class TokenSeal(unittest.TestCase):
    def test_sealed_on_the_node_opened_with_the_controllers_key(self):
        a = ts.secret(KEY, "n_1", "u_1")
        blob = ts.seal(ts.public(a), b'{"claudeAiOauth": "x"}', {"agent": "claude", "email": "p@example.com"})
        head = ts.header(blob)
        self.assertEqual((head["agent"], head["email"]), ("claude", "p@example.com"))
        self.assertNotIn(b"claudeAiOauth", blob, "the token is not in the clear")
        self.assertEqual(ts.open_with(ts.key_for(a, head["R"]), blob), b'{"claudeAiOauth": "x"}')

    def test_another_account_or_node_cannot_open_it(self):
        a = ts.secret(KEY, "n_1", "u_1")
        blob = ts.seal(ts.public(a), b"secret")
        R = ts.header(blob)["R"]
        for other in (ts.secret(KEY, "n_2", "u_1"), ts.secret(KEY, "n_1", "u_2"), ts.secret(b"another install key!", "n_1", "u_1")):
            with self.assertRaises(ts.Refused):
                ts.open_with(ts.key_for(other, R), blob)

    def test_each_seal_is_its_own(self):
        a = ts.secret(KEY, "n_1", "u_1")
        b1, b2 = ts.seal(ts.public(a), b"same"), ts.seal(ts.public(a), b"same")
        self.assertNotEqual(ts.header(b1)["R"], ts.header(b2)["R"])
        self.assertNotEqual(b1, b2)

    def test_a_damaged_seal_is_refused(self):
        a = ts.secret(KEY, "n_1", "u_1")
        blob = bytearray(ts.seal(ts.public(a), b"secret"))
        blob[-40] ^= 1
        with self.assertRaises(ts.Refused):
            ts.open_with(ts.key_for(a, ts.header(bytes(blob))["R"]), bytes(blob))

    def test_values_outside_the_group_are_refused(self):
        for bad in ("1", format(ts.P - 1, "x"), "0", format(ts.P + 5, "x"), "zz"):
            with self.assertRaises(ts.Refused):
                ts.element(bad)

    def test_a_wrap_opens_only_with_the_agents_boot_secret(self):
        e = ts.boot_secret()
        C, blob = ts.wrap(ts.public(e), {"abc": b"\x01" * 32})
        self.assertEqual(ts.unwrap(e, C, blob), {"abc": b"\x01" * 32})
        with self.assertRaises(ts.Refused):
            ts.unwrap(ts.boot_secret(), C, blob)

    def test_the_header_carries_no_secret(self):
        a = ts.secret(KEY, "n_1", "u_1")
        head = ts.header(ts.seal(ts.public(a), b"secret", {"agent": "codex"}))
        self.assertEqual(set(head), {"agent", "R"})
        json.dumps(head)


if __name__ == "__main__":
    unittest.main()
