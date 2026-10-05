"""hand.py, the finger's path a glide plays (R127): what every hand keeps
(the ends, the sample rate, repeatability) and what tells the hands apart
(a ruler is straight and even; a shaky hand bows, overshoots and wobbles
more than a steady one)."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import hand  # noqa: E402

PTS = [(100, 1000), (600, 1000), (600, 1400)]


def off_line(samples, a, b):
    """The farthest any sample strays from the straight line a to b."""
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    return max(abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / length for _, x, y in samples)


class Path(unittest.TestCase):
    def test_every_hand_starts_and_ends_on_the_points_at_dt(self):
        for name in hand.HANDS:
            r = hand.path(PTS, hand=name, seed=7)
            s = r["samples"]
            self.assertEqual(s[0], (0, 100, 1000), name)
            self.assertEqual(s[-1][1:], (600, 1400), name)
            self.assertEqual([b[0] - a[0] for a, b in zip(s, s[1:], strict=False)], [hand.DT] * (len(s) - 1), name)
            self.assertEqual(s[-1][0], r["took_ms"])

    def test_a_seed_repeats_the_path_and_another_does_not(self):
        a, b, c = (hand.path(PTS, seed=s)["samples"] for s in (1, 1, 2))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertIsInstance(hand.path(PTS)["seed"], int)

    def test_a_ruler_is_straight_and_even(self):
        r = hand.path(PTS[:2], hand="ruler", seed=3)
        s = r["samples"]
        self.assertEqual({y for _, _, y in s}, {1000})
        self.assertEqual(max(x for _, x, _ in s), 600, "no overshoot")
        # 500 px at 2000 px/s is 250 ms, eased: 25 samples.
        self.assertEqual(len(s), 26)

    def test_a_shaky_hand_strays_more_than_a_steady_one(self):
        steady = hand.path(PTS[:2], hand="steady", seed=5)["samples"]
        shaky = hand.path(PTS[:2], hand="shaky", seed=5)["samples"]
        self.assertGreater(off_line(shaky, *PTS[:2]), off_line(steady, *PTS[:2]))
        self.assertGreater(max(x for _, x, _ in shaky), 600, "a shaky hand overshoots")
        self.assertGreater(len(shaky), len(steady), "...and is slower")

    def test_ms_sets_each_legs_time_and_a_dial_overrides_the_hands(self):
        r = hand.path(PTS, hand="ruler", ms=200, seed=1)
        self.assertEqual(r["took_ms"], 400)
        r = hand.path(PTS[:2], hand="ruler", speed=1000, seed=1)
        self.assertEqual(r["took_ms"], 500)
        self.assertEqual(r["dials"]["speed"], 1000)

    def test_bad_arguments_are_named(self):
        bad: list[tuple[dict, str]] = [({"hand": "paw"}, "--hand"), ({"speed": 1}, "--speed"),
                                       ({"curve": "x"}, "--curve"), ({"ms": 9000}, "--ms")]
        for kw, word in bad:
            with self.assertRaises(ValueError, msg=kw) as e:
                hand.path(PTS, **kw)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(ValueError):
            hand.path(PTS[:1])
        with self.assertRaises(ValueError) as e:
            hand.path([(0, 0), (20000, 20000), (0, 0), (20000, 20000)], hand="shaky", speed=50)
        self.assertIn("more than", str(e.exception))


class Parse(unittest.TestCase):
    def test_the_flags_come_out_and_the_rest_stays(self):
        rest, opts = hand.parse(["1", "2", "--hand", "shaky", "3", "4", "--seed", "9", "--speed", "700", "--pre", "100"])
        self.assertEqual(rest, ["1", "2", "3", "4", "--pre", "100"])
        self.assertEqual(opts, {"hand": "shaky", "seed": 9, "speed": 700.0})

    def test_a_flag_without_a_value_is_named(self):
        for bad in (["--seed"], ["--seed", "x"], ["--shake", "lots"]):
            with self.assertRaises(ValueError) as e:
                hand.parse(bad)
            self.assertIn(bad[0], str(e.exception))


if __name__ == "__main__":
    unittest.main()
