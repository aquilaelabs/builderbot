"""A short read goes beside whatever holds a node's slot (B200), and a
machine log read is one (B654): a root system job marked light, with the
light lane's short timeout. Anything else root waits for the slot."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


class Lane(unittest.TestCase):
    def test_which_jobs_are_light(self):
        L = nodes.LIGHT_S
        self.assertTrue(nodes._light({"type": "exec", "spec": {"timeout": L}}))
        self.assertTrue(nodes._light({"type": "system", "spec": {"timeout": L, "light": True, "apply": "root"}}),
                        "a log read")
        self.assertFalse(nodes._light({"type": "system", "spec": {"timeout": L, "apply": "root"}}),
                         "a root command a person allowed waits for the slot")
        self.assertFalse(nodes._light({"type": "system", "spec": {"timeout": 600, "light": True}}),
                         "light only within the light lane's time")
        self.assertFalse(nodes._light({"type": "compose", "spec": {"timeout": 5}}))


if __name__ == "__main__":
    unittest.main()
