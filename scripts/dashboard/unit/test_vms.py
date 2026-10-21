"""The VM manager (R91): the OS asked for in words found in the catalog, a
person's OS refused to a session, the project's limits and the node's room
said in one sentence, a create recorded and queued as its node's vm job, the
job's end landing on the record; and the agent building its commands from its
own table, reading a publisher's checksum file, and refusing anything outside
the shapes it takes."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vms  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGJ0ZXN0a2V5Zm9ydGhldm1tYW5hZ2VydGVzdHMx test"


class Fake:
    def __init__(self):
        self.jobs = []
        self.audits = []
        self.caps = {"count": 4, "vcpus": 8, "mem_mb": 16384, "disk_gb": 200}
        self.nodes = {"n1": {"id": "n1", "name": "box", "kind": "agent", "state": "online", "live": True,
                             "reported": {"arch": "x86_64", "mem_mb": 16384, "vm_pool": {"free_mb": 200 * 1024},
                                          "features": {"vmhost": {"installed": True, "kvm": True}}, "vms": []}}}

    def job_add(self, by, placement, type_, spec, project=""):
        self.jobs.append((placement, type_, spec, project))
        return {"ok": True, "job": f"j{len(self.jobs)}"}


class Controller(unittest.TestCase):
    def setUp(self):
        self.f = Fake()
        vms.configure(state=tempfile.mkdtemp(), write_json=lambda p, d: p.write_text(json.dumps(d)),
                      node=lambda nid: self.f.nodes.get(nid), node_list=lambda: list(self.f.nodes.values()),
                      job_add=self.f.job_add, audit=lambda *a: self.f.audits.append(a),
                      prefs_get=lambda p: {"vm_caps": self.f.caps})

    def new(self, **kw):
        return vms.create("user:test", "web", {"name": "db", "os": "debian 13", "keys": [KEY], **kw}, ["n1"])

    def test_the_os_is_found_however_it_is_said(self):
        for said, want in (("Debian 12", "debian-12"), ("debian", "debian-13"), ("ubuntu-24.04", "ubuntu-24.04"),
                           ("rocky", "rocky-10"), ("Ubuntu 26.04 LTS", "ubuntu-26.04"), ("noble", "ubuntu-24.04"),
                           ("AlmaLinux 9", "almalinux-9"), ("centos stream", "centos-9"), ("arch", "arch-latest"),
                           ("leap 16", "opensuse-16.0"), ("tumbleweed", "opensuse-tumbleweed"), ("gentoo", "gentoo-latest")):
            self.assertEqual((vms.find_os(said)[0] or {}).get("id"), want, said)
        img, why = vms.find_os("debain 13")
        self.assertIsNone(img)
        self.assertIn("nearest: debian-13", why)

    def test_a_person_s_os_is_never_a_session_s(self):
        r = vms.create("session:web", "web", {"name": "w", "os": "windows", "keys": [KEY]}, ["n1"], session=True)
        self.assertIn("a person's to do", r["error"])
        self.assertIn("Ask a person", r["error"])
        self.assertEqual(self.f.jobs, [])

    def test_a_create_is_recorded_and_queued_on_its_node(self):
        r = self.new(vcpus=2, mem_mb=4096)
        self.assertTrue(r.get("ok"), r)
        placement, type_, spec, project = self.f.jobs[0]
        self.assertEqual((placement, type_, project), ({"node": "n1"}, "vm", "web"))
        self.assertEqual((spec["action"], spec["domain"], spec["mem_mb"], spec["subnet"]),
                         ("create", "bbvm-web-db", 4096, "10.232.0.0/24"))
        self.assertTrue(spec["image"]["url"].startswith("https://cloud.debian.org/"))
        self.assertEqual(vms.view()[0]["state"], "making")
        self.assertIn("already", self.new()["error"])

    def test_a_project_keeps_its_network_and_another_gets_its_own(self):
        self.new()
        vms.create("user:test", "api", {"name": "x", "os": "debian", "keys": [KEY]}, ["n1"])
        self.new(name="db2")
        subnets = [j[2]["subnet"] for j in self.f.jobs]
        self.assertEqual(subnets, ["10.232.0.0/24", "10.232.1.0/24", "10.232.0.0/24"])

    def test_the_project_s_limits_and_the_node_s_room_are_said(self):
        self.f.caps = dict(self.f.caps, count=1)
        self.new()
        self.assertIn("may hold 1 VMs in all", self.new(name="b")["error"])
        self.f.caps = dict(self.f.caps, count=4, disk_gb=4000)
        self.assertIn("less than the 2048 MB it keeps", self.new(name="c", mem_mb=14000)["error"])
        self.assertIn("less than the 10 GB it keeps", self.new(name="d", disk_gb=195)["error"])

    def test_made_a_node_it_carries_enroll_node_s_script_and_goes_with_it(self):
        made, retired, marked = [], [], []
        vms.enroll_script = lambda by, req: made.append(req) or {"id": "n_vm", "script": "#!/usr/bin/env bash\n# BuilderBot: enroll x"}
        vms.node_retire = lambda by, nid: retired.append(nid)
        vms.node_mark = lambda nid, host: marked.append((nid, host))
        try:
            r = self.new(node_agent=True, ctl="http://192.168.1.16:7680")
            self.assertTrue(r.get("ok"), r)
            self.assertEqual((made[0]["system"], made[0]["controller"], made[0]["sessions"]), ("debian", "http://192.168.1.16:7680", True))
            self.assertTrue(self.f.jobs[-1][2]["enroll"].startswith("#!/usr/bin/env bash\n# BuilderBot: enroll"))
            self.assertEqual(marked, [("n_vm", "n1")])
            vms.vm_done({"node": "n1", "spec": {"action": "remove", "domain": "bbvm-web-db"}}, "succeeded")
            self.assertEqual(retired, ["n_vm"])
        finally:
            vms.enroll_script = vms.node_retire = vms.node_mark = None

    def test_no_key_no_node_no_vm(self):
        self.assertIn("ssh public key", vms.create("user:test", "web", {"name": "a", "os": "debian"}, ["n1"])["error"])
        self.assertIn("no node web works on", vms.create("user:test", "web", {"name": "a", "os": "debian",
                                                                              "keys": [KEY]}, [])["error"])

    def test_the_job_s_end_lands_on_the_record(self):
        self.new()
        job = {"node": "n1", "spec": {"action": "create", "domain": "bbvm-web-db"}, "error": ""}
        vms.vm_done(job, "succeeded")
        self.assertEqual(vms._load()["vms"]["web/db"]["state"], "made")
        self.f.nodes["n1"]["reported"]["vms"] = [{"name": "bbvm-web-db", "state": "running", "ip": "10.232.0.12",
                                                   "snapshots": ["clean"]}]
        row = vms.view()[0]
        self.assertEqual((row["state"], row["ip"], row["snapshots"]), ("running", "10.232.0.12", ["clean"]))
        self.assertIn("no snapshot called gone", vms.act("user:test", "web", "db", "revert", {"snapshot": "gone"})["error"])
        # One its own job just made is there before the node says so.
        vms.vm_done({"node": "n1", "spec": {"action": "snapshot", "domain": "bbvm-web-db", "snapshot": "fresh"}}, "succeeded")
        self.assertTrue(vms.act("user:test", "web", "db", "revert", {"snapshot": "fresh"}).get("ok"))
        self.assertEqual(vms.view()[0]["snapshots"], ["clean", "fresh"])
        self.assertTrue(vms.act("user:test", "web", "db", "revert", {"snapshot": "clean"}).get("ok"))
        vms.act("user:test", "web", "db", "remove")
        vms.vm_done({"node": "n1", "spec": {"action": "remove", "domain": "bbvm-web-db"}}, "succeeded")
        self.assertEqual(vms._load()["vms"], {})


class Shipped(unittest.TestCase):
    """Every file under config/ the dashboard's modules read beside
    themselves is copied into the image: the catalog read empty on the dev
    instance because the Dockerfile left it out (B164)."""
    def test_every_config_file_read_is_in_the_image(self):
        import re as _re
        root = os.path.join(HERE, "..", "..", "..")
        docker = open(os.path.join(root, "Dockerfile"), encoding="utf-8").read()
        read = set()
        dash = os.path.join(root, "scripts", "dashboard")
        for f in os.listdir(dash):
            if f.endswith(".py"):
                read |= set(_re.findall(r'"config"\s*/\s*"([\w.-]+\.json)"', open(os.path.join(dash, f), encoding="utf-8").read()))
        self.assertIn("vm-images.json", read)
        missing = [f for f in sorted(read) if f"COPY config/{f} " not in docker]
        self.assertEqual(missing, [], "read from config/ and not copied into the image")


class Census(unittest.TestCase):
    """What a node reports of its VMs reaches the record: the cleaner keeps
    the VMs and their pool, field by field, and drops what is not ours."""
    def test_the_vms_and_their_pool_are_kept(self):
        import nodes
        got = nodes._census({"vms": [{"name": "bbvm-web-db", "state": "running", "ip": "10.232.0.12", "vcpus": 2,
                                      "mem_mb": 2048, "snapshots": ["clean", "no way!"]},
                                     {"name": "someone-elses", "state": "running"}],
                             "vm_pool": {"free_mb": 39000, "total_mb": 60000, "path": "/x"}})
        self.assertEqual(got["vms"], [{"name": "bbvm-web-db", "state": "running", "ip": "10.232.0.12", "vcpus": 2,
                                       "mem_mb": 2048, "snapshots": ["clean"]}])
        self.assertEqual(got["vm_pool"], {"free_mb": 39000, "total_mb": 60000})


class Agent(unittest.TestCase):
    def setUp(self):
        import agentpkg
        self.agent = agentpkg.load("builderbot_agent_vms")
        self.av = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".vms"]

    def test_a_publisher_s_checksums_are_read_in_each_style(self):
        h = "a" * 64
        self.assertEqual(self.av.sums_lookup(f"{h} *ubuntu.img\n{'b' * 64} *other.img\n", "ubuntu.img"), h)
        self.assertEqual(self.av.sums_lookup(f"{'c' * 128}  debian-13-generic-amd64.qcow2\n",
                                             "debian-13-generic-amd64.qcow2"), "c" * 128)
        self.assertEqual(self.av.sums_lookup(f"# x\nSHA256 (Rocky.qcow2) = {h}\n", "Rocky.qcow2"), h)
        self.assertEqual(self.av.sums_lookup("d" * 128 + "\n", "alpine.qcow2"), "d" * 128)
        self.assertEqual(self.av.sums_lookup(f"{h} *other.img\n", "missing.img"), "")

    def test_nothing_outside_the_shapes_reaches_a_command(self):
        a = object.__new__(self.agent.Agent)
        a.state = {}
        said = []

        class Job:
            def say(self, x):
                said.append(x)
        self.assertEqual(a.vm(Job(), {"action": "create", "domain": "bbvm-x; rm -rf /"}), ("failed", 64))
        self.assertEqual(a.vm(Job(), {"action": "explode", "domain": "bbvm-x"}), ("failed", 64))
        self.assertEqual(a.vm(Job(), {"action": "start", "domain": "someone-elses"}), ("failed", 64))

    def test_what_the_controller_sends_is_what_the_agent_takes(self):
        """Every catalog image, every arch, through the controller's create and
        into the agent's own shapes: the image id once carried an underscore
        (x86_64) the agent's shape refused, on the dev VM."""
        import vms as cv
        f = Fake()
        cv.configure(state=tempfile.mkdtemp(), write_json=lambda p, d: p.write_text(json.dumps(d)),
                     node=lambda nid: f.nodes.get(nid), node_list=lambda: list(f.nodes.values()),
                     job_add=f.job_add, audit=lambda *a: None, prefs_get=lambda p: {"vm_caps": {}})
        f.nodes["n1"]["reported"].update(mem_mb=10**6, vm_pool={"free_mb": 10**8})
        for arch in ("x86_64", "aarch64"):
            f.nodes["n1"]["reported"]["arch"] = arch
            for img in cv.catalog():
                if img.get("person") or arch not in img.get("arch", {}):
                    continue
                r = cv.create("user:t", "web", {"name": f"a{len(f.jobs)}", "os": img["id"], "keys": [KEY]}, ["n1"])
                self.assertTrue(r.get("ok"), (img["id"], arch, r))
                spec = f.jobs[-1][2]
                im = spec["image"]
                self.assertTrue(self.av.IMAGE_RE.fullmatch(im["id"]) and self.av.FILE_RE.fullmatch(im["file"]), im)
                self.assertTrue(self.av.DOMAIN_RE.fullmatch(spec["domain"]) and self.av.NETWORK_RE.fullmatch(spec["network"]), spec)

    def test_a_vm_reaches_the_internet_the_controller_and_its_own(self):
        t = self.av.vmnet_table([("192.168.1.16", 7680)])
        self.assertIn('iifname "bbvm-n*" oifname "bbvm-n*" drop', t)
        self.assertIn("elements = { 192.168.1.16 . 7680 }", t)
        self.assertIn("192.168.0.0/16", t)
        self.assertLess(t.index("@ctl accept"), t.index("192.168.0.0/16"), "the controller before the LAN's drop")
        self.assertIn('udp dport { 53, 67 } accept', t)
        self.assertNotIn("192.168.0.0/16", self.av.vmnet_table([], lan=True))

    def test_a_session_reaches_its_own_project_s_vms(self):
        sn = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".sessnet"]
        sessions = [{"addr": "10.231.0.5", "project": "web"}, {"addr": "10.231.0.6", "project": "api"}]
        own = {"web": {"vmnets": ["10.232.0.0/24"]}, "api": {"vmnets": ["not a net"]}}
        self.assertEqual(sn.sessnet_vms(sessions, own), [("10.231.0.5", "10.232.0.0/24")])
        self.assertIn("vms { 10.231.0.5 . 10.232.0.0/24 }", sn.sessnet_fill([], [], [], vms=sn.sessnet_vms(sessions, own)))
        t = sn.sessnet_table()
        self.assertLess(t.index("@vms goto pass"), t.index("@local reject"))

    def test_the_domain_carries_its_marker_and_no_graphics(self):
        x = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00")
        self.assertIn("<bb:vm xmlns:bb='https://builderbot.dev/vm/1' project='web'/>", x.replace('"', "'"))
        self.assertIn("host-passthrough", x)
        u = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00", boot="uefi",
                               fw=("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"), nvram="/v/d_VARS.fd")
        self.assertIn("<loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE_4M.fd</loader>", u)
        self.assertIn("/v/d_VARS.fd</nvram>", u)
        self.assertIn("machine='q35'", u)
        self.assertNotIn("<loader", x)
        self.assertNotIn("<graphics", x)
        ud = self.av.user_data("db", "builder", [KEY])
        self.assertIn("ssh_pwauth: false", ud)
        self.assertNotIn("runcmd", ud)
        self.assertIn("bash /root/bb-enroll.sh", self.av.user_data("db", "builder", [KEY], self.av.ENROLL_HEAD + "x"))
        self.assertIn(json.dumps(KEY), ud)


if __name__ == "__main__":
    unittest.main()
