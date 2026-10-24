"""Two-factor sign-in's parts (R127): the authenticator's codes against RFC
6238's own vector, recovery codes good once, the P-256 check against
signatures openssl makes, and a passkey registered and used end to end with
an authenticator played here (its signatures openssl's)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mfa  # noqa: E402

ORIGIN = "https://bb.example:7680"
HAS_OPENSSL = shutil.which("openssl") is not None


def cbor_enc(v):
    """Just enough CBOR to play an authenticator."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError(n)
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return head(3, len(b)) + b
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor_enc(k) + cbor_enc(x) for k, x in v.items())
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor_enc(x) for x in v)
    raise TypeError(type(v))


class Key:
    """A P-256 key in openssl, signing what it is handed."""
    def __init__(self, d):
        self.pem = os.path.join(d, "k.pem")
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", self.pem],
                       check=True, capture_output=True)
        der = subprocess.run(["openssl", "ec", "-in", self.pem, "-pubout", "-outform", "DER"],
                             check=True, capture_output=True).stdout
        pt = der[-65:]
        assert pt[0] == 4
        self.x, self.y = int.from_bytes(pt[1:33], "big"), int.from_bytes(pt[33:], "big")
        self.d = d

    def sign(self, msg):
        f = os.path.join(self.d, "m")
        Path(f).write_bytes(msg)
        return subprocess.run(["openssl", "dgst", "-sha256", "-sign", self.pem, f],
                              check=True, capture_output=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        mfa.configure(STATE=Path(self.tmp), seal=None, unseal=None, sealing=lambda: False)
        mfa._misses.clear()


class Totp(Base):
    def test_rfc_6238_s_vector(self):
        key = b"12345678901234567890"
        self.assertEqual(mfa.totp_now(key, at=59), "287082")
        self.assertEqual(mfa.totp_now(key, at=1111111109), "081804")

    def test_set_up_by_a_first_code_then_each_code_once(self):
        got = mfa.totp_begin("u_1", "dev3")
        self.assertIn("otpauth://totp/BuilderBot%3Adev3?secret=", got["uri"])
        key = mfa._secret_of(mfa.record("u_1")["totp_pending"])
        self.assertIn("error", mfa.totp_confirm("u_1", "000000" if mfa.totp_now(key) != "000000" else "111111"))
        self.assertEqual(mfa.totp_confirm("u_1", mfa.totp_now(key)), {"ok": True})
        self.assertTrue(mfa.enabled("u_1"))
        self.assertFalse(mfa.totp_check("u_1", mfa.totp_now(key)), "the code that confirmed it is used")
        self.assertTrue(mfa.totp_check("u_1", mfa.totp_now(key, at=time.time() + 30)))

    def test_a_sealed_secret_never_lands_in_the_file(self):
        mfa.configure(seal=lambda b: b"S" + b[::-1], unseal=lambda b: b[1:][::-1], sealing=lambda: True)
        mfa.totp_begin("u_1", "dev3")
        raw = (Path(self.tmp) / "two-factor.json").read_text()
        self.assertIn("sealed", raw)
        self.assertNotIn("plain", raw)
        self.assertEqual(oct(os.stat(Path(self.tmp) / "two-factor.json").st_mode & 0o777), "0o600")


class Recovery(Base):
    def test_ten_codes_each_good_once_and_new_ones_replace_them(self):
        codes = mfa.recovery_make("u_1")
        self.assertEqual(len(codes), 10)
        self.assertNotIn(codes[0], json.dumps(mfa.load()), "kept as hashes")
        self.assertTrue(mfa.recovery_use("u_1", codes[0].upper()))
        self.assertFalse(mfa.recovery_use("u_1", codes[0]))
        mfa.recovery_make("u_1")
        self.assertFalse(mfa.recovery_use("u_1", codes[1]))


class Misses(Base):
    def test_slowed_after_five_and_held_after_ten(self):
        waits = [mfa.missed("acct:u_1", "addr:1.2.3.4") for _ in range(10)]
        self.assertEqual(waits[:4], [0, 0, 0, 0])
        self.assertGreater(waits[4], 0)
        self.assertGreater(mfa.held("acct:u_1"), 0)
        self.assertEqual(mfa.held("acct:u_2"), 0, "another account is not held")


@unittest.skipUnless(HAS_OPENSSL, "openssl is not here")
class Passkey(Base):
    def setUp(self):
        super().setUp()
        self.key = Key(self.tmp)

    def test_the_curve_check_takes_openssl_s_signatures_and_nothing_else(self):
        sig = self.key.sign(b"hello")
        self.assertTrue(mfa.ecdsa_p256_verify(self.key.x, self.key.y, b"hello", sig))
        self.assertFalse(mfa.ecdsa_p256_verify(self.key.x, self.key.y, b"hellp", sig))
        self.assertFalse(mfa.ecdsa_p256_verify(self.key.x, self.key.y + 1, b"hello", sig))

    def _client(self, kind, chal, origin=ORIGIN):
        return mfa.b64u(json.dumps({"type": kind, "challenge": chal, "origin": origin}).encode())

    def _register(self, cred=b"cred-1"):
        chal = mfa.challenge("u_1", "create")
        cose = {1: 2, 3: -7, -1: 1, -2: self.key.x.to_bytes(32, "big"), -3: self.key.y.to_bytes(32, "big")}
        auth = (hashlib.sha256(b"bb.example").digest() + bytes([0x41]) + (0).to_bytes(4, "big")
                + bytes(16) + len(cred).to_bytes(2, "big") + cred + cbor_enc(cose))
        att = mfa.b64u(cbor_enc({"fmt": "none", "attStmt": {}, "authData": auth}))
        return mfa.passkey_add("u_1", ORIGIN, "laptop", self._client("webauthn.create", chal), att)

    def _assert(self, count, origin=ORIGIN, cred=b"cred-1"):
        chal = mfa.challenge("u_1", "get")
        client = self._client("webauthn.get", chal, origin)
        auth = hashlib.sha256(b"bb.example").digest() + bytes([0x05]) + count.to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(mfa.unb64u(client)).digest())
        return mfa.passkey_check("u_1", ORIGIN, mfa.b64u(cred), client, mfa.b64u(auth), mfa.b64u(sig))

    def test_registered_then_signed_in_with(self):
        got = self._register()
        self.assertEqual(got.get("name"), "laptop", got)
        self.assertTrue(mfa.enabled("u_1"))
        self.assertTrue(self._assert(1))
        self.assertFalse(self._assert(1), "a counter that did not move is a copied authenticator")
        self.assertTrue(self._assert(2))

    def test_an_answer_for_another_page_or_another_key_is_refused(self):
        self._register()
        self.assertFalse(self._assert(3, origin="https://evil.example"))
        self.assertFalse(self._assert(4, cred=b"cred-2"))

    def test_a_challenge_is_good_once(self):
        chal = mfa.challenge("u_1", "create")
        mfa._take_challenge("u_1", "create")
        self.assertIsNone(mfa._take_challenge("u_1", "create"))
        self.assertTrue(chal)


if __name__ == "__main__":
    unittest.main()
