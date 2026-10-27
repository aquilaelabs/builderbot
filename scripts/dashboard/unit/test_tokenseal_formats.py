"""The two seal formats side by side (R158 step 3): a 0.9 node seals with
X25519 and ChaCha20-Poly1305, a 0.8.x node the way before, and the
controller opens either and moves the old one to the new at the next
terminal its person opens; the install key's seal the same way."""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signing  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "bb_tokenseal_formats", os.path.join(os.path.dirname(__file__), "..", "..", "agent", "builderbot_agent", "tokenseal.py"))
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)
KEY = bytes(range(32))


class NodeSeals(unittest.TestCase):
    def test_the_new_seal_opens_with_the_controllers_key_and_nobody_elses(self):
        a = ts.secret(KEY, "n_1", "u_1")
        self.assertEqual(len(a), 32)
        pub = ts.public(a)
        self.assertTrue(ts.is_v2(pub))
        blob = ts.seal(pub, b'{"claudeAiOauth": "x"}', {"agent": "claude"})
        self.assertTrue(blob.startswith(ts.MAGIC))
        head = ts.header(blob)
        self.assertTrue(ts.is_v2(head["R"]))
        self.assertEqual(ts.open_with(ts.key_for(a, head["R"]), blob), b'{"claudeAiOauth": "x"}')
        for other in (ts.secret(KEY, "n_2", "u_1"), ts.secret(b"another install key!", "n_1", "u_1")):
            with self.assertRaises(ts.Refused):
                ts.open_with(ts.key_for(other, head["R"]), blob)
        bad = bytearray(blob); bad[-1] ^= 1
        with self.assertRaises(ts.Refused):
            ts.open_with(ts.key_for(a, head["R"]), bytes(bad))

    def test_the_old_seal_is_still_opened(self):
        a1 = ts.secret1(KEY, "n_1", "u_1")
        pub1 = ts.public(a1)
        self.assertEqual(len(pub1) > 64, True)
        blob = ts.seal(pub1, b"old", {"agent": "codex"})
        self.assertTrue(blob.startswith(ts.MAGIC1))
        R = ts.header(blob)["R"]
        self.assertFalse(ts.is_v2(R))
        self.assertEqual(ts.open_with(ts.key_for(a1, R), blob), b"old")
        with self.assertRaises(ts.Refused):
            ts.key_for(ts.secret(KEY, "n_1", "u_1"), R)

    def test_a_wrap_of_each_kind(self):
        for e in (ts.boot_secret(), ts.secret1(KEY, "boot", "x")):
            C, blob = ts.wrap(ts.public(e), {"r1": b"k" * 32})
            self.assertEqual(ts.unwrap(e, C, blob), {"r1": b"k" * 32})
            with self.assertRaises(ts.Refused):
                ts.unwrap(ts.boot_secret() if isinstance(e, bytes) else ts.secret1(KEY, "other", "x"), C, blob)


class ControllerSeals(unittest.TestCase):
    def setUp(self):
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))

    def test_new_seals_are_the_vetted_kind_and_old_ones_still_open(self):
        new = signing.seal(b"secret")
        self.assertTrue(new.startswith(signing.MAGIC))
        self.assertEqual(signing.unseal(new), b"secret")
        self.assertTrue(signing.current(new))
        # The format before, as 0.8.x wrote it.
        import hashlib
        import hmac
        enc, mac = signing._subkeys(KEY)
        nonce = b"n" * 16
        ct = bytes(a ^ b for a, b in zip(b"secret", signing._stream(enc, nonce, 6), strict=True))
        old = signing.MAGIC1 + nonce + ct + hmac.new(mac, signing.MAGIC1 + nonce + ct, hashlib.sha256).digest()
        self.assertEqual(signing.unseal(old), b"secret")
        self.assertTrue(signing.old_format(old))
        self.assertFalse(signing.current(old), "sealed again at the next start")
        bad = bytearray(new); bad[-1] ^= 1
        with self.assertRaises(signing.Locked):
            signing.unseal(bytes(bad))

    def test_the_format_is_told_by_its_magic(self):
        self.assertTrue(signing.old_format(signing.MAGIC1 + b"x" * 60))
        self.assertFalse(signing.old_format(signing.seal(b"y")))
        self.assertFalse(signing.old_format(b""))


if __name__ == "__main__":
    unittest.main()
