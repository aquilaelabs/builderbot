"""bb doctor on a node says the docker daemons are the controller's to check
(B148): a node holds no /config, and the probe named a file that was not
there, or answered "no node" from a store it could not read."""
import os
import subprocess
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class DoctorOnNode(unittest.TestCase):
    def test_the_docker_row_says_where_it_is_checked(self):
        r = subprocess.run(["bash", os.path.join(REPO, "scripts", "bb"), "doctor"], capture_output=True, text=True,
                           timeout=180, env=dict(os.environ, BUILDERBOT_ROLE="node"), check=False)
        row = [ln for ln in r.stdout.splitlines() if "daemon" in ln]
        self.assertEqual(len(row), 1, r.stdout)
        self.assertIn("[skip] docker daemon: the controller checks it", row[0])


if __name__ == "__main__":
    unittest.main()
