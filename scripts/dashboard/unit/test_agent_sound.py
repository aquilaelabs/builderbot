"""The node agent's sound in its census (R107): ALSA's cards read from
/proc/asound/cards, the virtual ones apart, and the sound server installed.
Drives _sound against a cards file of the test's own."""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "builderbot_agent", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

CARDS = """ 0 [PCH            ]: HDA-Intel - HDA Intel PCH
                      HDA Intel PCH at 0xf7f10000 irq 32
 1 [Dummy          ]: Dummy - Dummy
                      Dummy 1
 2 [Loopback       ]: Loopback - Loopback
                      Loopback 1
"""


class Sound(unittest.TestCase):
    def setUp(self):
        self.was = agent.ASOUND_CARDS
        self.addCleanup(setattr, agent, "ASOUND_CARDS", self.was)

    def test_real_cards_and_virtual_ones_apart(self):
        with tempfile.NamedTemporaryFile("w", suffix=".cards", delete=False) as f:
            f.write(CARDS)
        self.addCleanup(os.unlink, f.name)
        agent.ASOUND_CARDS = f.name
        s = agent._sound()
        self.assertEqual(s["cards"], ["HDA Intel PCH"])
        self.assertEqual(s["virtual"], ["Dummy", "Loopback"])
        self.assertIn(s["server"], ("", "pipewire", "pulseaudio"))

    def test_no_sound_loaded_is_no_cards(self):
        agent.ASOUND_CARDS = "/nonexistent/asound/cards"
        s = agent._sound()
        self.assertEqual((s["cards"], s["virtual"]), ([], []))


if __name__ == "__main__":
    unittest.main()
