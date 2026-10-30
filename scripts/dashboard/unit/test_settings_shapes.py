"""Each text setting is held to its own shape (B445): a hostname, an
address, a port, a word, an email, or one line as typed; until then every
text was held to a hostname's, so Connection's Served over, its email, the
mail server's port, security, sign-in name and From and the catalog's
address were refused."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402


class Shapes(unittest.TestCase):
    def setUp(self):
        settings.configure(state=tempfile.mkdtemp(), write_json=lambda p, d: open(p, "w").write(json.dumps(d)))

    def test_each_text_keeps_its_own_shape(self):
        good = {"tls_mode": "self", "tls_host": "bb.example.com", "tls_email": "me@example.com", "smtp_host": "smtp.example.com",
                "smtp_port": "587", "smtp_security": "ssl", "smtp_user": "Me@Example.com", "smtp_from": "BuilderBot <bb@example.com>",
                "catalog_url": "https://example.com/catalog/", "tunnel_host": "bb.example.com"}
        for k, v in good.items():
            self.assertNotIn("error", settings.set_many({k: v}), k)
            self.assertEqual(settings.get(k), v, k)

    def test_and_refuses_what_is_not(self):
        for k, v, said in (("smtp_port", "70000", "a port"), ("tls_email", "nobody", "an email address"),
                           ("catalog_url", "ftp://example.com/", "an address"), ("tunnel_host", "a b", "a hostname"),
                           ("tls_mode", "self signed", "one of the choices"), ("smtp_from", "a\nb", "one line")):
            self.assertIn(said, settings.set_many({k: v}).get("error", ""), k)

    def test_every_text_names_its_shape(self):
        for k, spec in settings.KEYS.items():
            if spec["kind"] == "text":
                self.assertIn(spec.get("shape"), settings.SHAPE_WORDS, k)


if __name__ == "__main__":
    unittest.main()
