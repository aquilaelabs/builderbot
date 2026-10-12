"""A node's logs, bounded and readable (the operator, 12 Oct): one reader
for every job's output that posts a meter's last frame even when it never
prints a newline, files kept to a size and directories to a count, a fault
said once an hour rather than on every tick, and output dropped while the
controller was away marked where the gap is."""
import os
import shutil
import subprocess
import tempfile
import unittest

import agentpkg  # noqa: E402

agent = agentpkg.load("builderbot_agent_logs")
said = []
agent.log = lambda m: said.append(m)


class Sink:
    def __init__(self):
        self.text = []

    def say(self, t):
        self.text.append(t)


class Reader(unittest.TestCase):
    def run_child(self, script, keep_blank=True):
        p = subprocess.Popen(["python3", "-c", script], stdout=subprocess.PIPE)
        sink = Sink()
        agent.pump(sink, p.stdout, keep_blank=keep_blank).join(20)
        p.wait()
        p.stdout.close()
        return sink.text

    def test_lines_and_a_redrawn_meter(self):
        got = self.run_child("import sys; sys.stdout.write('one\\n[=  ] 10%\\r[== ] 50%\\r[===] 100%\\ndone\\n')")
        self.assertEqual(got, ["one\n", "[===] 100%\n", "done\n"])

    def test_a_meter_that_never_prints_a_newline_is_posted_as_it_goes(self):
        got = self.run_child("import sys\nfor i in range(20000): sys.stdout.write(f'{i:>8} %\\r')\nsys.stdout.flush()")
        self.assertTrue(got, "something was posted")
        self.assertTrue(all(len(t) < 100 for t in got), "each post is a frame, not the whole meter")
        self.assertIn("19999", got[-1])

    def test_blank_lines_dropped_where_asked(self):
        self.assertEqual(self.run_child("print('a'); print(); print('b')", keep_blank=False), ["a\n", "b\n"])


class Files(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_a_file_past_its_size_is_cut_to_one_earlier_generation(self):
        f = os.path.join(self.d, "ttyd.log")
        with open(f, "w") as out:
            out.write("x" * 100)
        self.assertFalse(agent.cap_file(f, 1000))
        self.assertTrue(agent.cap_file(f, 10))
        self.assertEqual(os.path.getsize(f + ".1"), 100)
        self.assertEqual(os.path.getsize(f), 0)

    def test_a_directory_keeps_its_newest(self):
        for i in range(5):
            p = os.path.join(self.d, f"Worker_{i}.log")
            open(p, "w").close()
            os.utime(p, (1000 + i, 1000 + i))
        self.assertEqual(agent.prune_dir(self.d, 2), 3)
        self.assertEqual(sorted(os.listdir(self.d)), ["Worker_3.log", "Worker_4.log"])


class Once(unittest.TestCase):
    def test_the_same_fault_is_said_once_then_counted(self):
        said.clear()
        for _ in range(5):
            agent.log_once("k", "sync: boom")
        self.assertEqual(said, ["sync: boom"])
        agent.log_once("k", "sync: another")
        self.assertEqual(said[-1], "sync: another")


class Dropped(unittest.TestCase):
    def test_the_notice_sits_where_the_gap_is(self):
        class A:
            pass
        j = agent.Job(A(), {"id": "j1"})
        j.PENDING_CAP = 100
        for i in range(10):
            j.say(f"{i:02d}" * 10)
        seqs = [c["seq"] for c in j.pending]
        self.assertIn("dropped here", j.pending[0]["chunk"])
        self.assertEqual(seqs, sorted(seqs), "the notice's seq comes before the chunks that were kept")
        self.assertEqual(len(set(seqs)), len(seqs))


if __name__ == "__main__":
    unittest.main()
