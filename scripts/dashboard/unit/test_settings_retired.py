"""A setting that no longer exists is cleared off disk at start: apps_token,
the GitHub token the apps' releases were read with while the repository was
private, is not left in /config once the apps come from public releases."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402
import statefile  # noqa: E402


class Retired(unittest.TestCase):
    def test_a_saved_token_is_cleared_and_the_rest_kept(self):
        with tempfile.TemporaryDirectory() as t:
            settings.configure(write_json=statefile.write_json, state=t)
            with open(os.path.join(t, "settings.json"), "w") as f:
                json.dump({"apps_token": "ghp_secret", "apps_android": True}, f)
            self.assertEqual(settings.retire(), ["apps_token"])
            with open(os.path.join(t, "settings.json")) as f:
                self.assertEqual(json.load(f), {"apps_android": True})
            self.assertEqual(settings.retire(), [], "once")
            self.assertNotIn("apps_token", settings.KEYS, "and it is no setting any more")


if __name__ == "__main__":
    unittest.main()
