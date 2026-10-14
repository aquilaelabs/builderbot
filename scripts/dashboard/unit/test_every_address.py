"""Where a compose file publishes on every address (devapp.every_address,
R217): the literal, or a variable defaulting to 0.0.0.0, read as text so the
variable's name can be said; nothing when the file names no address."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devapp  # noqa: E402
from test_devapp_ship import write_json  # noqa: E402


class EveryAddress(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        devapp.configure(workspace=self.ws, state=self.tmp, write_json=write_json)
        write_json(devapp.FILE, {"alpha": {"main": {}}})

    def compose(self, text):
        (self.ws / "alpha" / "docker-compose.yml").write_text(text)

    def test_a_variable_defaulting_to_every_address_is_named(self):
        self.compose('services:\n  registry:\n    ports:\n      - "${REGISTRY_BIND:-0.0.0.0}:${REGISTRY_PORT:-8787}:8787"\n'
                     '      - "${REGISTRY_ADMIN_BIND:-127.0.0.1}:${REGISTRY_ADMIN_PORT:-8789}:8789"\n'
                     '  worker:\n    ports:\n      - ${WORKER_BIND:-0.0.0.0}:8788:8788\n')
        self.assertEqual(devapp.every_address("alpha"), {"vars": ["REGISTRY_BIND", "WORKER_BIND"], "literal": False})

    def test_the_literal_is_said_as_such(self):
        self.compose('services:\n  web:\n    ports:\n      - "0.0.0.0:8080:80"\n')
        self.assertEqual(devapp.every_address("alpha"), {"vars": [], "literal": True})

    def test_a_file_naming_no_address_leaves_it_to_the_daemon(self):
        self.compose('services:\n  web:\n    ports:\n      - "8080:80"\n      - "${WEB_PORT:-8081}:81"\n      - "127.0.0.1:9000:9000"\n'
                     '      - "${BIND}:9001:9001"\n')
        self.assertIsNone(devapp.every_address("alpha"), "a variable with no default is the env's to decide")
        (self.ws / "alpha" / "docker-compose.yml").unlink()
        self.assertIsNone(devapp.every_address("alpha"), "no file, nothing to say")


if __name__ == "__main__":
    unittest.main()
