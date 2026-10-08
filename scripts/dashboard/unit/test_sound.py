"""sound.py, behind bb tool sound (R107): a preset and a seed make the same
sound every time, each preset makes something of its own length and shape,
a tone sweeps where it is told, and a WAV is written without ffmpeg. The
OGG and the pictures are ffmpeg's, walked by hand against the store's
(3 Oct)."""
import io
import os
import random
import sys
import tempfile
import unittest
import wave
from itertools import pairwise
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import sound  # noqa: E402


def make(kind, seed):
    return sound.synth(sound.preset(kind, random.Random(seed)), seed)


class Synth(unittest.TestCase):
    def test_a_seed_makes_the_same_sound_and_another_a_variation(self):
        self.assertEqual(make("blip", 5), make("blip", 5))
        self.assertNotEqual(make("blip", 5), make("blip", 6))

    def test_every_preset_is_a_sound_brought_to_one_loudness(self):
        for kind in sound.PRESETS:
            s = make(kind, 11)
            self.assertGreater(len(s), sound.RATE // 50, kind)       # longer than 20 ms
            self.assertLess(len(s), sound.RATE * 5, kind)            # and shorter than 5 s
            self.assertAlmostEqual(max(abs(x) for x in s), 0.8, places=6, msg=kind)

    def test_an_explosion_is_longer_than_a_blip(self):
        self.assertGreater(len(make("explosion", 2)), len(make("blip", 2)))

    def test_a_tone_is_its_length_and_its_pitch(self):
        s = sound.tone(1000, 100)
        self.assertEqual(len(s), sound.RATE // 10)
        # A 1 kHz sine crosses zero about 200 times in 100 ms.
        crossings = sum(1 for a, b in pairwise(s) if a < 0 <= b or a >= 0 > b)
        self.assertTrue(180 <= crossings <= 220, crossings)
        up = sound.tone(500, 100, to=2000)
        first = sum(1 for a, b in pairwise(up[:2205]) if a < 0 <= b)
        last = sum(1 for a, b in pairwise(up[-2205:]) if a < 0 <= b)
        self.assertGreater(last, first * 1.5)          # 1250 to 2000 Hz against 500 to 1250


class Verbs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.cwd)
        self.ff = sound.ffmpeg
        sound.ffmpeg = lambda: ""
        self.addCleanup(setattr, sound, "ffmpeg", self.ff)

    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            sound.main(list(argv))
        return out.getvalue()

    def refused(self, *argv):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as e:
            sound.main(list(argv))
        return str(e.exception)

    def test_without_ffmpeg_it_is_a_wav_and_says_why(self):
        out = self.run_main("make", "pickup", "--seed", "4")
        self.assertIn("dist/sound/pickup-4.wav", out)
        self.assertIn("no ffmpeg", out)
        with wave.open("dist/sound/pickup-4.wav") as w:
            self.assertEqual((w.getnchannels(), w.getframerate()), (1, sound.RATE))
        self.assertIn("dist/sound/beep.wav", self.run_main("tone", "880", "--ms", "80", "--name", "beep"))

    def test_what_it_refuses(self):
        self.assertIn("presets", self.refused("make", "kazoo"))
        self.assertIn("whole number", self.refused("make", "blip", "--seed", "x"))
        self.assertIn("20 to 20000", self.refused("tone", "5"))
        self.assertIn("numbers", self.refused("tone", "loud"))
        self.assertIn("letters", self.refused("make", "blip", "--name", "../x"))
        self.assertIn("no verb", self.refused("sing"))

    def test_say_and_hear_without_the_audio_toolchain_name_it(self):
        os.environ.pop("SDK_ROOT", None)
        self.assertIn("audio toolchain", self.refused("say", "hello"))
        open("x.wav", "wb").close()
        self.assertIn("audio toolchain", self.refused("hear", "x.wav"))


if __name__ == "__main__":
    unittest.main()
