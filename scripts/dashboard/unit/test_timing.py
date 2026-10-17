"""Where a request's time went (timing.py): its named parts and its own
thread's CPU, kept per thread so two requests at once never mix."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import timing  # noqa: E402


class Timing(unittest.TestCase):
    def test_parts_add_up_by_name_and_reset(self):
        timing.start()
        with timing.timed("a"):
            time.sleep(0.02)
        with timing.timed("a"):
            time.sleep(0.01)
        with timing.timed("b"):
            pass
        cpu, parts = timing.finish()
        self.assertGreaterEqual(parts["a"], 25)
        self.assertIn("b", parts)
        self.assertGreaterEqual(cpu, 0)
        self.assertEqual(timing.finish()[1], {})

    def test_cpu_is_the_threads_own_not_its_waiting(self):
        timing.start()
        time.sleep(0.05)
        cpu, _ = timing.finish()
        self.assertLess(cpu, 30)

    def test_two_threads_keep_their_own(self):
        got = {}

        def work(name, ms):
            timing.start()
            with timing.timed(name):
                time.sleep(ms / 1000)
            got[name] = timing.finish()[1]
        ts = [threading.Thread(target=work, args=("x", 20)), threading.Thread(target=work, args=("y", 5))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(set(got["x"]), {"x"})
        self.assertEqual(set(got["y"]), {"y"})

    def test_timed_outside_a_request_is_harmless(self):
        timing._here.__dict__.clear()
        with timing.timed("nowhere"):
            pass


if __name__ == "__main__":
    unittest.main()
