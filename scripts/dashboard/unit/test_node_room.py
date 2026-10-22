"""A node short of room says so on the bell (R110, the operator, 22 Oct):
a disk or store under the floor, said once where a store shares the root
filesystem's numbers, and memory judged over ten minutes, not one sample."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nodes  # noqa: E402


def node(nid, sample, live=True):
    return {"id": nid, "name": nid + "-box", "kind": "agent", "live": live, "reported": {"sample": sample}}


class Room(unittest.TestCase):
    def rows(self, ns, rings=None):
        with mock.patch.object(nodes, "node_list", lambda: ns), \
             mock.patch.object(nodes, "samples", lambda nid: (rings or {}).get(nid, [])):
            return nodes.room_attention(10, 92, label=lambda r: {"root": "root"}.get(r, r))

    def test_a_disk_under_the_floor_and_a_store_on_it_said_once(self):
        smp = {"disks": {"root": [4 * 1024, 100 * 1024], "docker": [4 * 1024, 100 * 1024]},
               "stores": {"data": 4 * 1024, "toolchains": 300 * 1024},
               "store_totals": {"data": 100 * 1024, "toolchains": 900 * 1024}}
        [r] = self.rows([node("n1", smp)])
        self.assertEqual([x["what"] for x in r["short"]], ["root"], "the same filesystem is said once")
        self.assertEqual((r["short"][0]["free_gb"], r["mem"], r["key"]), (4.0, None, "room:n1:root"))

    def test_a_vm_s_own_disk_filling_and_the_pool_under_its_reserve(self):
        n = node("n1", {})
        n["reported"].update({"vms": [{"name": "bbvm-web-db", "root_fs": [9300, 10000]},
                                      {"name": "bbvm-web-ok", "root_fs": [2000, 10000]}],
                              "vm_pool": {"free_mb": 5 * 1024, "total_mb": 200 * 1024}})
        [r] = self.rows([n])
        self.assertEqual([x["what"] for x in r["short"]], ["the VM web-db's disk", "where its VM disks grow"])

    def test_a_vm_s_every_filesystem_and_its_memory_over_ten_minutes(self):
        now = time.time()
        n = node("n1", {})
        n["reported"]["vms"] = [{"name": "bbvm-web-db", "guest": {"fs": [["/", 1000, 10000], ["/var/lib/data", 950, 1000]]}}]
        ring = [{"at": now - 60 * i, "vm_mem": {"bbvm-web-db": [50, 1000]}} for i in range(4)]
        [r] = self.rows([n], {"n1": ring})
        self.assertEqual([x["what"] for x in r["short"]], ["the VM web-db's /var/lib/data", "the VM web-db's memory"])
        self.assertEqual(r["short"][1]["used_pct"], 95)

    def test_room_enough_says_nothing_and_an_away_node_is_skipped(self):
        smp = {"disks": {"root": [50 * 1024, 100 * 1024]}, "stores": {}, "store_totals": {}}
        self.assertEqual(self.rows([node("n1", smp), node("n2", {"disks": {"root": [1, 100]}}, live=False)]), [])

    def test_memory_over_ten_minutes_not_one_sample(self):
        now = time.time()
        full = [{"at": now - 60 * i, "mem_mb": 1000, "mem_used_mb": 950} for i in range(5)]
        [r] = self.rows([node("n1", {})], {"n1": full})
        self.assertEqual((r["mem"], r["short"], r["key"]), (95, [], "room:n1::mem"))
        spike = [{"at": now - 60, "mem_mb": 1000, "mem_used_mb": 990}]
        self.assertEqual(self.rows([node("n1", {})], {"n1": spike}), [], "one sample is no pressure")
        old = [{"at": now - 3000 - 60 * i, "mem_mb": 1000, "mem_used_mb": 990} for i in range(5)]
        self.assertEqual(self.rows([node("n1", {})], {"n1": old}), [], "an hour ago is not now")


    def test_a_build_is_refused_under_the_floor_where_docker_keeps_its_images(self):
        def short(disks):
            n = node("n1", {"disks": disks})
            with mock.patch.object(nodes, "node", lambda nid: n if nid == "n1" else None):
                return nodes.room_short("n1", 10)
        self.assertIn("4.0 GB free for Docker's images", short({"docker": [4 * 1024, 100 * 1024], "root": [50 * 1024, 100 * 1024]}))
        self.assertEqual(short({"docker": [40 * 1024, 100 * 1024], "root": [1 * 1024, 100 * 1024]}), "",
                         "Docker's own disk decides where the node says it")
        self.assertIn("2.0 GB", short({"root": [2 * 1024, 100 * 1024]}), "the root's where it does not")
        self.assertEqual(short({}), "", "a node that said neither is not refused")



class Prune(unittest.TestCase):
    """The prunes the Containers page and the hourly room keeper run (R110
    step 3): docker's own words for each, and nothing else asked of it."""

    def test_each_kind_is_its_docker_command_and_no_other_is_run(self):
        import devapp
        ran = []
        with mock.patch.object(devapp, "_run", lambda argv, timeout=0: ran.append(argv[1:]) or {"code": 0, "out": "Total reclaimed space: 1GB"}):
            for k in ("images", "volumes", "unused", "cache"):
                self.assertTrue(devapp.prune(k).get("ok"), k)
            self.assertIn("error", devapp.prune("everything"))
        self.assertEqual(ran, [["image", "prune", "-f"], ["volume", "prune", "-f"],
                               ["image", "prune", "-a", "-f", "--filter", "until=336h"],
                               ["builder", "prune", "-f", "--filter", "until=168h"]])


if __name__ == "__main__":
    unittest.main()
