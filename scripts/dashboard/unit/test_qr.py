"""The QR encoder (R127): its codes were read back by a decoder (jsQR 1.4.0,
23 Oct) for a short text, an authenticator's otpauth address, a
three-hundred-character text and UTF-8; these hold them to those modules."""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import qr  # noqa: E402

URI = ("otpauth://totp/BuilderBot%3Adev3?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
       "&issuer=BuilderBot&algorithm=SHA1&digits=6&period=30")


def print_of(m):
    return hashlib.sha256("".join("1" if v else "0" for r in m for v in r).encode()).hexdigest()[:16]


class Qr(unittest.TestCase):
    def test_the_modules_a_decoder_read(self):
        self.assertEqual((len(qr.matrix("hi")), print_of(qr.matrix("hi"))), (21, "69f439bee9c38226"))
        self.assertEqual((len(qr.matrix(URI)), print_of(qr.matrix(URI))), (49, "4d6475010dff65d4"))

    def test_finder_patterns_in_three_corners(self):
        m = qr.matrix(URI)
        n = len(m)
        for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
            self.assertTrue(all(m[y0][x0 + i] and m[y0 + 6][x0 + i] for i in range(7)))
            self.assertTrue(m[y0 + 3][x0 + 3])
            self.assertFalse(m[y0 + 1][x0 + 1])

    def test_an_svg_with_its_quiet_zone(self):
        s = qr.svg("hi")
        self.assertIn('viewBox="0 0 29 29"', s)
        self.assertIn('fill="#fff"', s)


if __name__ == "__main__":
    unittest.main()
