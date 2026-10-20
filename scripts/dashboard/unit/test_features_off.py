"""Features switched off for a whole install from its environment (R81):
which request is which feature's, the sentence it is refused with, and a
name that is not a feature switching nothing off."""
import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import featuresoff  # noqa: E402


class FeaturesOff(unittest.TestCase):
    def load(self, names, why=""):
        with mock.patch.dict(os.environ, {"FEATURES_OFF": names, "FEATURES_OFF_WHY": why}):
            m = importlib.reload(featuresoff)
            m.off()
        self.addCleanup(importlib.reload, featuresoff)
        return m

    def test_nothing_off_refuses_nothing(self):
        m = self.load("")
        self.assertEqual(m.refused("POST", "/api/v1/nodes", {"action": "add"}), "")

    def test_each_feature_takes_its_requests(self):
        m = self.load("tunnel,ftp,phone,devices,apps,image-updates,runner,enroll", "a classroom install")
        cases = [
            ("POST", "/api/settings", {"set": {"tunnel_host": "x"}}, "tunnel"),
            ("POST", "/api/settings", {"set": {"apps_android": False}}, "apps"),
            ("POST", "/api/project-ftp", {"action": "set"}, "ftp"),
            ("POST", "/api/phone", {"action": "pair"}, "phone"),
            ("POST", "/api/artifacts", {"action": "push"}, "phone"),
            ("POST", "/api/v1/device/signin", {}, "devices"),
            ("GET", "/api/apps", None, "apps"),
            ("POST", "/api/images", {"action": "check"}, "image-updates"),
            ("POST", "/api/devapp", {"action": "update"}, "image-updates"),
            ("POST", "/api/v1/nodes", {"action": "runner-token"}, "runner"),
            ("POST", "/api/v1/nodes", {"action": "add"}, "enroll"),
        ]
        for method, path, req, feat in cases:
            why = m.refused(method, path, req)
            self.assertTrue(why.endswith("is off: a classroom install"), (path, req, why))
            self.assertIn(m.FEATURES[feat][1:], why)

    def test_what_is_not_a_feature_goes_on(self):
        m = self.load("phone,enroll,image-updates")
        self.assertEqual(m.refused("POST", "/api/phone", {"action": "ask"}), "", "a session's ask is not pairing")
        self.assertEqual(m.refused("POST", "/api/v1/nodes", {"action": "update-agent"}), "")
        self.assertEqual(m.refused("POST", "/api/devapp", {"action": "rebuild"}), "")
        self.assertEqual(m.refused("POST", "/api/settings", {"set": {"log_days": 7}}), "")

    def test_the_controllers_shell_has_its_sentence(self):
        m = self.load("shell", "a shared classroom install")
        self.assertEqual(m.sentences(), {"shell": "A terminal on the controller itself is off: a shared classroom install"})

    def test_a_name_that_is_not_a_feature_switches_nothing_off(self):
        m = self.load("tunel,enroll")
        self.assertEqual(list(m.off()), ["enroll"])
        self.assertEqual(m.off()["enroll"], m.WHY_DEFAULT)


if __name__ == "__main__":
    unittest.main()
