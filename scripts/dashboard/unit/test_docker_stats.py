"""What a container is using now (R216): `docker stats` read once per ask
into numbers the row can sum, sizes as bytes and percentages as floats."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class Stats(unittest.TestCase):
    LINE = ('{"Name":"web-app-1","CPUPerc":"0.50%","MemUsage":"12.7MiB / 21.4MiB","MemPerc":"2.66%",'
            '"NetIO":"1.2kB / 648B","PIDs":"22"}')

    def test_a_line_is_read_into_numbers(self):
        got = devapp.parse_stats(self.LINE + "\nnot json\n")
        self.assertEqual(list(got), ["web-app-1"])
        s = got["web-app-1"]
        self.assertEqual(s["cpu"], 0.5)
        self.assertEqual(s["mem"], int(12.7 * 1024 * 1024))
        self.assertEqual(s["mem_limit"], int(21.4 * 1024 * 1024))
        self.assertEqual(s["mem_pct"], 2.66)
        self.assertEqual((s["rx"], s["tx"]), (1200, 648))
        self.assertEqual(s["pids"], 22)

    def test_sizes_in_every_unit_docker_prints(self):
        for text, want in (("0B", 0), ("648B", 648), ("1.2kB", 1200), ("3MB", 3_000_000),
                           ("1GiB", 1024 ** 3), ("2.5GB", 2_500_000_000), ("", 0), ("--", 0)):
            self.assertEqual(devapp._size_bytes(text), want, text)

    def test_a_container_with_no_name_and_a_blank_field_are_harmless(self):
        got = devapp.parse_stats('{"CPUPerc":"1%"}\n{"Name":"x","CPUPerc":"","MemUsage":"--","NetIO":"","PIDs":""}')
        self.assertEqual(got, {"x": {"cpu": 0.0, "mem": 0, "mem_limit": 0, "mem_pct": 0.0, "rx": 0, "tx": 0, "pids": 0}})

    def test_the_guard_lets_the_reads_through_in_their_one_shape_only(self):
        g = devapp._guard
        self.assertEqual(g([devapp.DOCKER, "stats", "--no-stream", "--format", "{{json .}}"]), "")
        self.assertEqual(g([devapp.DOCKER, "images", "--format", "{{json .}}"]), "")
        self.assertEqual(g([devapp.DOCKER, "volume", "ls", "--format", "{{json .}}"]), "")
        self.assertEqual(g([devapp.DOCKER, "system", "df", "--format", "{{json .}}"]), "")
        # ...and the two prunes the view offers, each the one flag alone.
        self.assertEqual(g([devapp.DOCKER, "image", "prune", "-f"]), "")
        self.assertEqual(g([devapp.DOCKER, "volume", "prune", "-f"]), "")
        for argv in (["stats"], ["stats", "--format", "{{json .}}"], ["images", "-q"],
                     ["volume", "rm", "x"], ["volume", "prune"], ["volume", "prune", "-f", "--filter", "x"],
                     ["image", "prune", "-a", "-f"], ["image", "rm", "x"], ["system", "prune", "-a"]):
            self.assertTrue(g([devapp.DOCKER] + argv), argv)


if __name__ == "__main__":
    unittest.main()
