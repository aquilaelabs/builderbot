"""The VM manager (R91): the OS asked for in words found in the catalog, a
person's OS refused to a session, the project's limits and the node's room
said in one sentence, a create recorded and queued as its node's vm job, the
job's end landing on the record; and the agent building its commands from its
own table, reading a publisher's checksum file, and refusing anything outside
the shapes it takes."""
import json
import os
import shutil
import subprocess
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

    def test_a_vm_s_hardware_is_checked_before_its_node_sees_it(self):
        # R100: a thread another VM is pinned to is refused unless shared, a
        # memory ceiling under its start is refused (none is its start), the
        # shared folder is the project's own, and a device is an
        # administrator's.
        self.f.nodes["n1"]["reported"]["vms"] = [{"name": "bbvm-web-a", "hw": {"cpuset": [2, 3]}}]
        hw, why = vms.hardware({"hw": {"cpuset": [3, 4]}}, "web", "n1", False, 2048)
        self.assertIsNone(hw)
        self.assertIn("bbvm-web-a is pinned", why)
        self.assertEqual(vms.hardware({"hw": {"cpuset": [3, 4]}}, "web", "n1", False, 2048, but="bbvm-web-a")[0]["cpuset"], [3, 4])
        self.assertEqual(vms.hardware({"hw": {"cpuset": [4, 3], "share_cpus": True}}, "web", "n1", False, 2048)[0]["cpuset"], [3, 4])
        self.assertIn("under what it starts", vms.hardware({"hw": {"mem_max_mb": 1024}}, "web", "n1", False, 2048)[1])
        self.assertEqual(vms.hardware({"hw": {"mem_max_mb": 0}}, "web", "n1", False, 2048)[0]["mem_max_mb"], 2048)
        sh = vms.hardware({"hw": {"share": {"path": "data/in", "ro": True}}}, "web", "n1", False, 2048)[0]["share"]
        self.assertEqual(sh, {"path": "/workspace/web/data/in", "tag": "project", "ro": True})
        self.assertIn("inside the project", vms.hardware({"hw": {"share": {"path": "../api"}}}, "web", "n1", False, 2048)[1])
        dev = {"devices": [{"type": "usb", "vendor": "046d", "product": "c52b"}]}
        self.assertIn("administrator", vms.hardware({"hw": dev}, "web", "n1", False, 2048)[1])
        self.assertEqual(vms.hardware({"hw": dev}, "web", "n1", True, 2048)[0]["devices"], dev["devices"])
        self.assertIn("administrator", vms.vbios("user:test", {"node": "n1", "addr": "0000:01:00.0"}, False)["error"])
        import base64
        self.f.nodes["n1"]["reported"]["features"]["vmhost"]["installed"] = True
        self.assertIn("not a vBIOS", vms.vbios("user:test", {"node": "n1", "addr": "0000:01:00.0",
                                                            "rom": base64.b64encode(b"MZ" + b"\0" * 4000).decode()}, True).get("error", ""))
        ok = vms.vbios("user:test", {"node": "n1", "addr": "0000:01:00.0", "rom": base64.b64encode(b"\x55\xaa" + b"\0" * 4000).decode()}, True)
        self.assertTrue(ok.get("ok"), ok)
        self.assertTrue(self.f.jobs[-1][2]["rom"])
        # The LAN is a person's: a session's own VM stays behind its
        # project's firewall.
        self.assertIn("a person's", vms.hardware({"hw": {"net": "lan"}}, "web", "n1", False, 2048, person=False)[1])
        self.assertEqual(vms.hardware({"hw": {"net": "project"}}, "web", "n1", False, 2048, person=False)[0], {"net": "project"})
        r = self.new(hw={"cpuset": [0, 1], "net": "lan"}, autostart=True)
        self.assertTrue(r.get("ok"), r)
        spec = self.f.jobs[-1][2]
        self.assertEqual((spec["hw"], spec["autostart"]), ({"cpuset": [0, 1], "net": "lan"}, True))

    def test_a_usb_device_is_given_to_a_vm_and_taken_back(self):
        # R116: named as the node's census names it; an administrator's;
        # refused for one the host uses, one not here, and one another VM
        # here holds; a take names what the VM holds, plugged in or not.
        r = self.new()
        self.assertTrue(r.get("ok"), r)
        vms.vm_done({"node": "n1", "spec": {"action": "create", "domain": "bbvm-web-db"}, "error": ""}, "succeeded")
        stick = {"vendor": "0x0781", "product": "0x5583", "name": "SanDisk Ultra Fit", "serial": "4C53", "port": "1-3", "bus": 1, "use": []}
        boot = {"vendor": "0x0781", "product": "0x5583", "name": "SanDisk Ultra Fit", "serial": "BOOT", "port": "1-4", "bus": 1,
                "use": ["the host boots from it (sda1 is /)"]}
        mouse = {"vendor": "0x046d", "product": "0xc52b", "name": "Receiver", "serial": "", "port": "1-5", "bus": 1, "use": []}
        self.f.nodes["n1"]["reported"]["vm_host"] = {"usb": [stick, boot, mouse], "pci": [], "cpus": [], "iommu": False}
        self.f.nodes["n1"]["reported"]["vms"] = [{"name": "bbvm-web-db", "state": "running", "usb": []},
                                                 {"name": "bbvm-web-other", "state": "stopped", "usb": [{"vendor": "0x046d", "product": "0xc52b", "serial": "", "port": "1-5"}]}]
        act = lambda a, usb, admin=True: vms.act("user:t", "web", "db", a, {"usb": usb, "_admin": admin})  # noqa: E731
        self.assertIn("administrator", act("usb-give", stick, admin=False)["error"])
        self.assertIn("vendor and product", act("usb-give", {"vendor": "0781"})["error"])
        self.assertIn("boots from it", act("usb-give", {"vendor": "0x0781", "product": "0x5583", "serial": "BOOT"})["error"])
        self.assertIn("not plugged into box", act("usb-give", {"vendor": "0x1234", "product": "0x5678"})["error"])
        self.assertIn("take it back", act("usb-give", {"vendor": "0x046d", "product": "0xc52b", "port": "1-5"})["error"])
        r = act("usb-give", {"vendor": "0x0781", "product": "0x5583", "serial": "4C53"})
        self.assertTrue(r.get("ok"), r)
        spec = self.f.jobs[-1][2]
        self.assertEqual((spec["action"], spec["usb"]["serial"], spec["usb"]["port"], spec["usb"]["name"]),
                         ("usb-give", "4C53", "1-3", "SanDisk Ultra Fit"))
        self.assertEqual(self.f.audits[-1][1], "vm-usb-give")
        self.assertIn("does not hold", act("usb-take", {"vendor": "0x1234", "product": "0x5678"})["error"])
        self.f.nodes["n1"]["reported"]["vms"][0]["usb"] = [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "port": "1-3", "name": "SanDisk Ultra Fit"}]
        self.f.nodes["n1"]["reported"]["vm_host"]["usb"] = [boot]      # pulled out: still taken back by name
        r = act("usb-take", {"vendor": "0x0781", "product": "0x5583", "serial": "4C53"})
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.f.jobs[-1][2]["action"], "usb-take")
        # The view names what each VM holds.
        row = next(v for v in vms.view(["web"]) if v["name"] == "db")
        self.assertEqual(row["usb"][0]["name"], "SanDisk Ultra Fit")

    def test_a_refused_job_leaves_the_agent_s_reason_on_the_row(self):
        # B191: the agent's refusal from the job's log, not "exit 64".
        self.new()
        vms.vm_done({"id": "j1", "node": "n1", "spec": {"action": "create", "domain": "bbvm-web-db"}, "error": "exit 64"}, "failed")
        self.assertEqual(vms.view()[0]["error"], "exit 64", "with no log to read, the code is all there is")
        vms.job_tail = lambda jid: "image: cached\nrefused: /workspace/web/docs is not a folder on this node\n"
        self.addCleanup(setattr, vms, "job_tail", None)
        vms.vm_done({"id": "j1", "node": "n1", "spec": {"action": "create", "domain": "bbvm-web-db"}, "error": "exit 64"}, "failed")
        self.assertEqual(vms.view()[0]["error"], "/workspace/web/docs is not a folder on this node")

    def test_the_os_is_found_however_it_is_said(self):
        for said, want in (("Debian 12", "debian-12"), ("debian", "debian-13"), ("ubuntu-24.04", "ubuntu-24.04"),
                           ("rocky", "rocky-10"), ("Ubuntu 26.04 LTS", "ubuntu-26.04"), ("noble", "ubuntu-24.04"),
                           ("AlmaLinux 9", "almalinux-9"), ("centos stream", "centos-9"), ("arch", "arch-latest"),
                           ("leap 16", "opensuse-16.0"), ("tumbleweed", "opensuse-tumbleweed"), ("gentoo", "gentoo-latest")):
            self.assertEqual((vms.find_os(said)[0] or {}).get("id"), want, said)
        # Images with no BIOS boot partition hang under SeaBIOS (B198).
        for said in ("debian", "gentoo"):
            self.assertEqual(vms.find_os(said)[0].get("boot"), "uefi", said)
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

    def test_a_report_from_before_a_vm_was_made_is_an_earlier_vms(self):
        # Made again under a name an earlier VM had: the node's report, taken
        # before, describes that one (B319), and its address is nobody's now.
        self.new()
        d = vms._load()
        rec = next(iter(d["vms"].values()))
        rec.update(state="running", made_at=2000)
        vms._save(d)
        self.f.nodes["n1"]["reported"].update(at=1000, vms=[{"name": "bbvm-web-db", "state": "running",
                                                             "ip": "10.232.0.9", "guest": {"hostname": "old"}}])
        row = vms.view()[0]
        self.assertEqual((row["state"], row["ip"], row["guest"]), ("running", "", {}))
        self.f.nodes["n1"]["reported"].update(at=3000, vms=[{"name": "bbvm-web-db", "state": "running", "ip": "10.232.0.12"}])
        self.assertEqual(vms.view()[0]["ip"], "10.232.0.12")

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
            # Its own account is not the sessions', which cloud-init would give sudo.
            self.assertEqual(self.f.jobs[-1][2]["user"], "admin")
            self.assertIn("something else", self.new(name="n2", node_agent=True, user="builder")["error"])
            vms.vm_done({"node": "n1", "spec": {"action": "remove", "domain": "bbvm-web-db"}}, "succeeded")
            self.assertEqual(retired, ["n_vm"])
        finally:
            vms.enroll_script = vms.node_retire = vms.node_mark = None

    def test_a_vm_refused_makes_no_node_row_to_stand_in_the_way(self):
        # A create past the cap minted the node's enroll row first, and the
        # next try was refused by that row's name (R97's walk, 21 Oct).
        made, dropped = [], []
        vms.enroll_script = lambda by, req: made.append(req) or {"id": "n_vm", "script": "#!/usr/bin/env bash\n# BuilderBot: enroll x"}
        vms.node_discard = lambda by, nid: dropped.append(nid)
        try:
            self.f.caps = dict(self.f.caps, count=1)
            self.new()
            self.assertIn("may hold 1 VMs", self.new(name="b", node_agent=True)["error"])
            self.assertEqual(made, [])
            # ...and one refused by the node after its row was made takes it off.
            self.f.caps = dict(self.f.caps, count=4)
            self.f.job_add = lambda *a, **k: {"error": "the node is offline"}
            vms.configure(state=vms.STATE, write_json=vms.write_json, node=vms.node, node_list=vms.node_list,
                          job_add=self.f.job_add, audit=vms.audit, prefs_get=vms.prefs_get,
                          enroll_script=vms.enroll_script, node_discard=vms.node_discard)
            self.assertIn("offline", self.new(name="c", node_agent=True)["error"])
            self.assertEqual(dropped, ["n_vm"])
        finally:
            vms.enroll_script = vms.node_discard = None

    def test_from_an_installer(self):
        # R99: a person's VM from an ISO on the node, with further disks, a
        # MAC and a screen password; never a session's, never a node.
        self.f.nodes["n1"]["reported"]["vm_isos"] = [{"name": "ubuntu-26.04-live-server-amd64.iso", "mb": 3100}]
        r = self.new(os="", iso="ubuntu-26.04-live-server-amd64.iso", keys=[], disks=[20], mac="52:54:00:aa:bb:cc",
                     console_password="pw", boot="uefi")
        self.assertTrue(r.get("ok"), r)
        spec = self.f.jobs[-1][2]
        self.assertEqual((spec["installer"], spec["disks"], spec["mac"], spec["boot"]),
                         ({"iso": "ubuntu-26.04-live-server-amd64.iso"}, [20], "52:54:00:aa:bb:cc", "uefi"))
        self.assertNotIn("image", spec)
        self.assertIn("not on box", self.new(name="b", os="", iso="other.iso", keys=[])["error"])
        self.assertIn("a person's", vms.create("session:web", "web", {"name": "c", "iso": "ubuntu-26.04-live-server-amd64.iso"},
                                                ["n1"], session=True)["error"])
        self.assertIn("MAC", self.new(name="d", mac="01:00:5e:00:00:01")["error"])
        self.assertIn("eight", self.new(name="e", console_password="far-too-long")["error"])

    def test_an_iso_is_fetched_against_its_sha256(self):
        r = vms.iso("user:test", "iso-add", {"node": "n1", "url": "https://releases.example/ubuntu.iso", "sha256": "a" * 64})
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.f.jobs[-1][2]["iso"], {"name": "ubuntu.iso", "url": "https://releases.example/ubuntu.iso", "sha256": "a" * 64})
        self.assertIn("SHA-256", vms.iso("user:test", "iso-add", {"node": "n1", "url": "https://x/y.iso"})["error"])
        self.assertIn("https", vms.iso("user:test", "iso-add", {"node": "n1", "url": "http://x/y.iso", "sha256": "a" * 64})["error"])

    def test_an_uploaded_iso_is_spooled_hashed_and_fetched_by_its_job_alone(self):
        import hashlib
        import io
        body = b"\x00" * 4096
        r = vms.iso_upload("user:test", io.BytesIO(body), len(body), "n1", "own.iso")
        self.assertTrue(r.get("ok"), r)
        spec = self.f.jobs[-1][2]
        self.assertEqual(spec["iso"]["sha256"], hashlib.sha256(body).hexdigest())
        path = vms.upload_path(spec["iso"]["upload"])
        self.assertEqual(path.read_bytes(), body)
        self.assertIn("ended early", vms.iso_upload("user:test", io.BytesIO(body[:10]), len(body), "n1", "x.iso")["error"])
        vms.vm_done({"node": "n1", "spec": spec}, "succeeded")
        self.assertIsNone(vms.upload_path(spec["iso"]["upload"]), "the spool is emptied when its job ends")

    def test_a_disk_grows_and_never_shrinks(self):
        self.new()
        vms.vm_done({"node": "n1", "spec": {"action": "create", "domain": "bbvm-web-db"}}, "succeeded")
        self.assertIn("never shrinks", vms.act("user:test", "web", "db", "disk-grow", {"disk": "vda", "gb": 5})["error"])
        r = vms.act("user:test", "web", "db", "disk-grow", {"disk": "vda", "gb": 40})
        self.assertTrue(r.get("ok"), r)
        self.assertEqual((self.f.jobs[-1][2]["disk"], self.f.jobs[-1][2]["gb"]), ("vda", 40))
        r = vms.act("user:test", "web", "db", "disk-add", {"gb": 50})
        self.assertTrue(r.get("ok"), r)
        vms.vm_done({"node": "n1", "spec": {"action": "disk-add", "domain": "bbvm-web-db", "gb": 50}}, "succeeded")
        self.assertEqual([v for v in vms.view() if v["name"] == "db"][0]["disks"], [50])

    def test_who_is_on_a_vm_is_on_its_row_while_it_lasts(self):
        self.new()
        before = vms.rev()
        a = vms.present("web/db", "screen", "Ada")
        b = vms.present("web/db", "screen", "Ben")
        c = vms.present("web/db", "console", "Ada", "u_ada")
        self.assertNotEqual(vms.rev(), before, "the page re-reads when somebody comes or goes")
        row = [v for v in vms.view() if v["name"] == "db"][0]
        self.assertEqual(row["on"], {"screen": [{"name": "Ada", "uid": ""}, {"name": "Ben", "uid": ""}],
                                     "console": [{"name": "Ada", "uid": "u_ada"}]})
        self.assertEqual(vms.holders("web/db", "console", but="u_ada"), [])
        self.assertFalse(vms.may_take("u_ben", "web/db"))
        vms.take("u_ben", "web/db")
        self.assertTrue(vms.may_take("u_ben", "web/db"), "a take-over is good for its minute")
        for t in (a, b, c):
            vms.gone(t)
        self.assertEqual([v for v in vms.view() if v["name"] == "db"][0]["on"], {})

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
                                       "mem_mb": 2048, "snapshots": ["clean"], "screen": False, "iso": "",
                                   "autostart": False, "hw": {"cpuset": [], "devices": [], "net": "project"}, "usb": []}])
        self.assertEqual(got["vm_pool"], {"free_mb": 39000, "total_mb": 60000})

    def test_the_domains_builderbot_did_not_make_reach_the_record_by_name_state_and_size(self):
        # R165 step 1: read-only on the VMs page, so only what names and
        # sizes one is kept, each to its shape.
        import nodes
        got = nodes._census({"vms_other": [{"name": "win11", "state": "running", "vcpus": 4, "mem_mb": 8192, "disk": "/x"},
                                           {"name": "bad name!", "state": "running"}, "junk",
                                           {"name": "old-box", "state": "shut <b>off</b>", "vcpus": "2"}]})
        self.assertEqual(got["vms_other"], [{"name": "win11", "state": "running", "vcpus": 4, "mem_mb": 8192},
                                            {"name": "old-box", "state": "shut boffb", "vcpus": 0, "mem_mb": 0}])
        self.assertEqual(vms.others.__doc__ is not None, True)

    def test_a_usb_device_s_name_and_use_reach_the_record(self):
        # R116: the fields that name a device again and say what the host
        # does with it, each kept to its shape; a VM's devices as named; the
        # IOMMU feature's two facts.
        import nodes
        got = nodes._census({"vm_host": {"usb": [{"vendor": "0x0781", "product": "0x5583", "name": "SanDisk <b>Ultra</b>", "serial": "4C53 0001",
                                                   "port": "1-3.2", "bus": 1, "dev": 7, "speed": "5000", "driver": "usb-storage,uas", "ctl": "0000:00:14.0",
                                                   "use": ["sda1 is mounted at /mnt/x", 7]}],
                                         "pci": [{"addr": "0000:00:14.0", "class": "0x0c0330", "vendor": "0x8086", "device": "0x1234",
                                                  "group": "7", "driver": "xhci_hcd", "host": "sda1 is mounted at /mnt/x"}]},
                             "vms": [{"name": "bbvm-web-db", "state": "running", "usb": [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53",
                                                                                            "port": "bad port", "name": "Stick"}, "junk"]}],
                             "features": {"vmhost": {"installed": True, "kvm": True}, "iommu": {"installed": True, "on": False}}})
        u = got["vm_host"]["usb"][0]
        self.assertEqual((u["name"], u["serial"], u["port"], u["bus"], u["speed"], u["driver"], u["ctl"], u["use"]),
                         ("SanDisk bUltra/b", "4C530001", "1-3.2", 1, "5000", "usb-storage,uas", "0000:00:14.0", ["sda1 is mounted at /mnt/x"]))
        self.assertEqual(got["vm_host"]["pci"][0]["host"], "sda1 is mounted at /mnt/x")
        self.assertEqual(got["vms"][0]["usb"], [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "port": "", "name": "Stick"}])
        self.assertEqual(got["features"]["iommu"], {"installed": True, "on": False})


class Agent(unittest.TestCase):
    def setUp(self):
        import agentpkg
        self.agent = agentpkg.load("builderbot_agent_vms")
        self.av = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".vms"]

    def test_the_domains_it_did_not_make_are_listed_and_never_ours(self):
        # R165 step 1: a name without the prefix, or with it and without the
        # agent's marker, is somebody else's; one with both is BuilderBot's
        # and stays out of this list.
        from unittest import mock
        def virsh(argv, timeout=0, **kw):
            verb = argv[len(self.av.VIRSH)]
            if verb == "list":
                return "bbvm-web-db\nwin11\nbbvm-fake\nbad/name\n"
            name = argv[len(self.av.VIRSH) + 1]
            if verb == "dumpxml":
                return f"<domain><metadata><bb:vm xmlns:bb='{self.av.META_NS}'/></metadata></domain>" if name == "bbvm-web-db" else "<domain/>"
            if verb == "dominfo":
                return {"win11": "State:          running\nCPU(s):         4\nMax memory:     8388608 KiB\n",
                        "bbvm-fake": "State:          shut off\nCPU(s):         1\nMax memory:     1048576 KiB\n"}.get(name, "")
            return ""
        with mock.patch.object(self.av, "_run", side_effect=virsh), mock.patch.object(self.av.shutil, "which", return_value="/usr/bin/virsh"):
            self.assertEqual(self.av.vms_other(), [{"name": "win11", "state": "running", "vcpus": 4, "mem_mb": 8192},
                                                   {"name": "bbvm-fake", "state": "stopped", "vcpus": 1, "mem_mb": 1024}])

    def test_on_the_controllers_own_machine_a_vm_job_runs_as_the_agent(self):
        # R165 step 1: the wall's file says the machine is the controller's
        # own, and there the job keeps root rather than dropping to the jobs
        # account, which is out of libvirt's group on that machine.
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            wall = os.path.join(d, "wall")
            with mock.patch.dict(os.environ, {"BB_WALL_FILE": wall}):
                self.assertFalse(self.av.own_here())
                open(wall, "w").close()
                self.assertTrue(self.av.own_here())

    def test_a_publisher_s_checksums_are_read_in_each_style(self):
        h = "a" * 64
        self.assertEqual(self.av.sums_lookup(f"{h} *ubuntu.img\n{'b' * 64} *other.img\n", "ubuntu.img"), h)
        self.assertEqual(self.av.sums_lookup(f"{'c' * 128}  debian-13-generic-amd64.qcow2\n",
                                             "debian-13-generic-amd64.qcow2"), "c" * 128)
        self.assertEqual(self.av.sums_lookup(f"# x\nSHA256 (Rocky.qcow2) = {h}\n", "Rocky.qcow2"), h)
        self.assertEqual(self.av.sums_lookup("d" * 128 + "\n", "alpine.qcow2"), "d" * 128)
        self.assertEqual(self.av.sums_lookup(f"{h} *other.img\n", "missing.img"), "")

    def test_a_running_vm_s_root_filesystem_from_its_guest_agent(self):
        from unittest import mock
        said = ("fs.count             : 2\nfs.0.name            : vda15\nfs.0.mountpoint      : /boot/efi\n"
                "fs.0.used-bytes      : 6\nfs.0.total-bytes     : 10\nfs.1.name            : vda1\n"
                "fs.1.mountpoint      : /\nfs.1.used-bytes      : 3221225472\nfs.1.total-bytes     : 10737418240\n")
        with mock.patch.object(self.av, "_run", return_value=said):
            self.assertEqual(self.av.guest_root("bbvm-web-db"), [3072, 10240])
        with mock.patch.object(self.av, "_run", return_value="error: Guest agent is not responding"):
            self.assertIsNone(self.av.guest_root("bbvm-web-db"))

    def test_a_vm_s_guest_agent_facts_and_its_balloon_memory(self):
        from unittest import mock
        said = ("hostname             : web-db\nos.pretty-name       : Debian GNU/Linux 13 (trixie)\n"
                "os.kernel-release    : 6.12.48-amd64\nuser.count           : 1\n"
                "if.0.name            : lo\nif.0.addr.0.addr     : 127.0.0.1\n"
                "if.1.name            : enp1s0\nif.1.addr.0.addr     : 10.232.0.12\nif.1.addr.1.addr     : fe80::1\n"
                "fs.0.mountpoint      : /\nfs.0.used-bytes      : 3221225472\nfs.0.total-bytes     : 10737418240\n"
                "fs.1.mountpoint      : /var/lib/data\nfs.1.used-bytes      : 1048576\nfs.1.total-bytes     : 2097152\n")
        with mock.patch.object(self.av, "_run", return_value=said):
            g = self.av.guest_facts("bbvm-web-db")
        self.assertEqual((g["hostname"], g["os"], g["kernel"], g["users"], g["ips"]),
                         ("web-db", "Debian GNU/Linux 13 (trixie)", "6.12.48-amd64", 1, ["10.232.0.12"]))
        self.assertEqual(g["fs"], [["/", 3072, 10240], ["/var/lib/data", 1, 2]])
        stats = ("Domain: 'bbvm-web-db'\n  balloon.current=2097152\n  balloon.usable=104857\n  balloon.available=2000000\n"
                 "Domain: 'bbvm-web-new'\n  balloon.current=1048576\n\nDomain: 'someone-else'\n  balloon.usable=1\n")
        ran = []
        with mock.patch.object(self.av, "_run", side_effect=lambda argv, timeout=0: ran.append(argv) or (stats if "domstats" in argv else "")):
            self.assertEqual(self.av.vm_memory(), {"bbvm-web-db": [102, 1953]})
        self.assertTrue(any("dommemstat" in a and "bbvm-web-new" in a for a in ran), "a VM with no stats period is given one")

    def test_an_image_s_size_is_read_so_a_disk_is_never_smaller(self):
        from unittest import mock
        ran = mock.Mock(stdout=json.dumps({"virtual-size": 21474836480}))
        with mock.patch.object(self.av.subprocess, "run", return_value=ran):
            self.assertEqual(self.av.image_bytes("/v/gentoo.qcow2"), 20 * 2**30)
        with mock.patch.object(self.av.subprocess, "run", side_effect=OSError):
            self.assertEqual(self.av.image_bytes("/v/none.qcow2"), 0)

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

    def test_the_screen_relay_takes_the_controller_s_signature_alone(self):
        sc = sys.modules[self.agent.Agent.__module__.rsplit(".", 1)[0] + ".screen"]
        key = sc.screen_key("bbn_secret")
        import hashlib
        self.assertEqual(key, hashlib.sha256(b"secret").hexdigest(), "the controller's stored hash of the token")
        t = 1_800_000_000
        sig = sc.sign(key, "bbvm-web-db", t)
        self.assertTrue(sc.signed(key, "bbvm-web-db", t, sig, now=t + 30))
        self.assertFalse(sc.signed(key, "bbvm-web-db", t, sig, now=t + 600), "a minute's signature, not forever")
        self.assertFalse(sc.signed(key, "bbvm-web-other", t, sig, now=t), "for one VM, not another")
        self.assertFalse(sc.signed(sc.screen_key("bbn_other"), "bbvm-web-db", t, sig, now=t), "this node's key")
        # A masked client frame read back whole, split across reads.
        payload, mask = b"RFB 003.008\n", b"\x01\x02\x03\x04"
        frame = bytes([0x82, 0x80 | len(payload)]) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        fr = sc._Frames()
        self.assertEqual(fr.feed(frame[:5]), [])
        self.assertEqual(fr.feed(frame[5:]), [(2, payload)])

    def test_a_vm_s_hardware_lands_in_its_domain_and_reads_back(self):
        # R100: what clean() lets through, apply() writes, and read() finds
        # again, so the row says what the VM has.
        hw = sys.modules[self.av.__name__.rsplit(".", 1)[0] + ".vmhw"]
        x = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00", mac="52:54:00:12:34:56")
        want, why = hw.clean({"cpuset": [3, 2], "mem_max_mb": 4096, "net": "lan",
                              "share": {"path": "/workspace/web/data", "tag": "project", "ro": True},
                              "devices": [{"type": "usb", "vendor": "0x046d", "product": "0xc52b"},
                                          {"type": "pci", "addr": "0000:01:00.0", "rom": "0000-01-00.0.rom"}]}, 2, 2048)
        self.assertEqual(why, "")
        out = hw.apply(x, want, 2, 2048, "enp1s0", "bbvm-n00", "/v/vbios", fsd=hw.VIRTIOFSD_WRAP).replace('"', "'").replace(" />", "/>")
        self.assertIn(f"<binary path='{hw.VIRTIOFSD_WRAP}'/>", out, "VM host's wrapper, which maps the VM's uids to the folder's owner")
        self.assertIn("<vcpupin vcpu='0' cpuset='2'/>", out)
        self.assertIn("<memballoon model='virtio'", out)
        self.assertIn("<mac address='52:54:00:12:34:56'/>", out, "its MAC kept, so a DHCP reservation holds")
        self.assertIn("<source dev='enp1s0' mode='bridge'/>", out)
        self.assertIn("<driver type='virtiofs'", out)
        self.assertIn("<readonly/>", out)
        self.assertIn("<vendor id='0x046d'/>", out)
        self.assertIn("<rom file='/v/vbios/0000-01-00.0.rom'/>", out)
        self.assertEqual(hw.rom_name("0000:01:00.0"), "0000-01-00.0.rom", "the name vbios_dump writes is one clean() takes")
        back = hw.read(out)
        self.assertEqual((back["cpuset"], back["mem_max_mb"], back["net"], back["share"]["path"], len(back["devices"])),
                         ([2, 3], 4096, "lan", "/workspace/web/data", 2))
        # Taken off again: an empty record clears what it set.
        bare = hw.read(hw.apply(out, {"cpuset": [], "mem_max_mb": 2048, "net": "project", "share": {}, "devices": []},
                                2, 2048, "enp1s0", "bbvm-n00", "/v/vbios"))
        self.assertEqual((bare["cpuset"], bare.get("mem_max_mb"), bare["net"], bare.get("share"), bare["devices"]),
                         ([], None, "project", None, []))
        self.assertIsNone(hw.clean({"share": {"path": "/etc", "tag": "project"}}, 2, 2048)[0])
        self.assertIsNone(hw.clean({"devices": [{"type": "pci", "addr": "1:2"}]}, 2, 2048)[0])

    def test_a_usb_device_is_read_off_sysfs_named_again_and_written_as_a_hostdev(self):
        # R116 steps 1 and 3: the census from a sysfs laid out as the
        # kernel's (a stick behind a controller, with a mounted partition;
        # a receiver; a hub left out), the device found again by serial or
        # port, the hostdev XML, and the numbers refreshed after a replug.
        hw = sys.modules[self.av.__name__.rsplit(".", 1)[0] + ".vmhw"]
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        pci = os.path.join(root, "devices/pci0000:00/0000:00:14.0")
        def dev(path, **files):
            os.makedirs(path, exist_ok=True)
            for k, v in files.items():
                with open(os.path.join(path, k), "w") as f:
                    f.write(v + "\n")
        dev(f"{pci}/usb1/1-3", idVendor="0781", idProduct="5583", manufacturer="SanDisk", product="Ultra Fit", serial="4C53",
            busnum="1", devnum="7", speed="5000", bDeviceClass="00")
        dev(f"{pci}/usb1/1-3/1-3:1.0/host4/target4:0:0/4:0:0:0/block/sdb")
        os.makedirs(f"{root}/bus/usb/devices", exist_ok=True)
        os.symlink("/nonexistent/usb-storage", f"{pci}/usb1/1-3/1-3:1.0/driver")
        dev(f"{pci}/usb1/1-4", idVendor="046d", idProduct="c52b", product="Receiver", busnum="1", devnum="8", speed="12", bDeviceClass="00")
        dev(f"{pci}/usb1/1-5", idVendor="05e3", idProduct="0610", product="Hub", busnum="1", devnum="9", bDeviceClass="09")
        for d in ("1-3", "1-4", "1-5"):
            os.symlink(f"{pci}/usb1/{d}", f"{root}/bus/usb/devices/{d}")
        os.makedirs(f"{root}/bus/pci/devices", exist_ok=True)
        dev(pci, **{"class": "0x0c0330", "vendor": "0x8086", "device": "0x1234"})
        os.symlink(pci, f"{root}/bus/pci/devices/0000:00:14.0")
        os.makedirs(f"{root}/kernel/iommu_groups/7/devices", exist_ok=True)
        os.symlink(f"{root}/kernel/iommu_groups/7", f"{pci}/iommu_group")
        from unittest import mock
        with mock.patch.object(hw, "_mounts", return_value={"/dev/sdb1": "/mnt/x"}), mock.patch.object(hw, "_lan_pci", return_value=""):
            got = hw.host_hw(root)
        usb = {u["port"]: u for u in got["usb"]}
        self.assertEqual(sorted(usb), ["1-3", "1-4"], "the hub is the host's own")
        st = usb["1-3"]
        self.assertEqual((st["name"], st["serial"], st["bus"], st["dev"], st["speed"], st["driver"], st["ctl"]),
                         ("SanDisk Ultra Fit", "4C53", 1, 7, "5000", "usb-storage", "0000:00:14.0"))
        self.assertEqual(st["use"], ["sdb1 is mounted at /mnt/x"])
        self.assertEqual(usb["1-4"]["use"], [])
        ctl = got["pci"][0]
        self.assertEqual((ctl["addr"], ctl["group"], ctl["host"]), ("0000:00:14.0", "7", "sdb1 is mounted at /mnt/x"), "the controller carries what the host uses")
        self.assertTrue(got["iommu"])
        # Named again: by serial among alike ones, by port with no serial.
        twins = [dict(st, serial="A", port="1-1", dev=3), dict(st, serial="B", port="1-2", dev=4), dict(st, serial="", port="1-6", dev=5), dict(st, serial="", port="1-7", dev=6)]
        self.assertEqual(hw.usb_find(twins, {"vendor": st["vendor"], "product": st["product"], "serial": "B"})["dev"], 4)
        self.assertEqual(hw.usb_find(twins, {"vendor": st["vendor"], "product": st["product"], "serial": "", "port": "1-7"})["dev"], 6)
        self.assertIsNone(hw.usb_find(twins, {"vendor": "0x0000", "product": "0x0000"}))
        self.assertIsNone(hw.usb_want({"vendor": "0781", "product": "0x5583"}))
        self.assertIsNone(hw.usb_want({"vendor": "0x0781", "product": "0x5583", "port": "../x"}))
        # The hostdev: optional at start, and by its numbers when alike.
        x = hw.usb_hostdev(st).replace('"', "'").replace(" />", "/>")
        self.assertIn("<source startupPolicy='optional'><vendor id='0x0781'/><product id='0x5583'/></source>", x)
        self.assertIn("<address bus='1' device='7'/>", hw.usb_hostdev(st, by_address=True).replace('"', "'").replace(" />", "/>"))
        dom = f"<domain><devices>{hw.usb_hostdev(st, by_address=True)}</devices></domain>"
        kept = [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "port": "1-3"}]
        self.assertIsNone(hw.usb_refresh(dom, kept, [st]), "still where it was")
        moved = hw.usb_refresh(dom, kept, [dict(st, dev=12)])
        self.assertIn('device="12"', moved)
        self.assertIsNone(hw.usb_refresh(dom, kept, []), "pulled out: its numbers stay, and the source is optional")

    def test_a_usb_give_attaches_live_and_keeps_the_device_by_name(self):
        # R116 step 3: give runs virsh attach-device --persistent with the
        # hostdev, keeps the device by name beside the disk, and says now or
        # at the next start; take detaches it; the refusals say why.
        from unittest import mock
        hw = sys.modules[self.av.__name__.rsplit(".", 1)[0] + ".vmhw"]
        vmdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, vmdir, True)
        os.makedirs(os.path.join(vmdir, "disks"))
        a = object.__new__(self.agent.Agent)
        a.state = {}
        said, ran = [], []

        class Job:
            def say(self, x):
                said.append(x)
        stick = {"vendor": "0x0781", "product": "0x5583", "name": "SanDisk Ultra Fit", "serial": "4C53", "port": "1-3", "bus": 1, "dev": 7, "use": []}
        boot = dict(stick, serial="BOOT", port="1-4", dev=8, use=["the host boots from it (sda1 is /)"])
        state = {"domstate": "running\n"}

        def run(argv, **kw):
            ran.append(argv)
            out = state["domstate"] if "domstate" in argv else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        with mock.patch.object(self.av, "VM_DIR", vmdir), mock.patch.object(self.av.subprocess, "run", side_effect=run), \
                mock.patch.object(self.av, "_run", return_value="bbvm-web-db\nbbvm-web-other\n"), \
                mock.patch.object(hw, "host_hw", return_value={"usb": [stick, boot], "pci": [], "cpus": [], "iommu": False}), \
                mock.patch.object(self.av, "lan_iface", return_value="eth0"):
            who = {}
            give = lambda usb: a._vm_usb(Job(), {"usb": usb}, "bbvm-web-db", who, give=True)  # noqa: E731
            self.assertEqual(give({"vendor": "0781"}), ("failed", 64))
            self.assertEqual(give({"vendor": "0x0781", "product": "0x5583", "serial": "BOOT"}), ("failed", 75))
            self.assertIn("boots from it", said[-1])
            self.assertEqual(give({"vendor": "0x1111", "product": "0x2222"}), ("failed", 66))
            self.assertEqual(give({"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "name": "SanDisk Ultra Fit"}), ("succeeded", 0))
            attach = next(x for x in ran if "attach-device" in x)
            self.assertEqual(attach[-1], "--persistent")
            with open(attach[-2]) as f:
                xml = f.read()
            self.assertIn('bus="1" device="7"', xml, "two alike here: by its numbers")
            self.assertEqual(self.av.usb_kept("bbvm-web-db")[0]["serial"], "4C53")
            self.assertIn("now, and keeps it at its next start", said[-1])
            # Another VM holds it now: refused by name.
            self.av.usb_keep("bbvm-web-other", [{"vendor": "0x0781", "product": "0x5583", "serial": "BOOT", "port": "1-4"}])
            self.av.usb_keep("bbvm-web-db", [])
            self.assertEqual(give({"vendor": "0x0781", "product": "0x5583", "serial": "BOOT"}), ("failed", 75))
            self.av.usb_keep("bbvm-web-other", [])
            self.av.usb_keep("bbvm-web-db", [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "port": "1-3", "name": "SanDisk Ultra Fit"}])
            # Taken back, the stick pulled out meanwhile: struck off the list.
            state["domstate"] = "shut off\n"
            with mock.patch.object(hw, "host_hw", return_value={"usb": [boot], "pci": [], "cpus": [], "iommu": False}):
                self.assertEqual(a._vm_usb(Job(), {"usb": {"vendor": "0x0781", "product": "0x5583", "serial": "4C53"}}, "bbvm-web-db", who, give=False),
                                 ("succeeded", 0))
            self.assertIn("detach-device", ran[-1])
            self.assertEqual(self.av.usb_kept("bbvm-web-db"), [])
            self.assertIn("the host's again", said[-1])
            # The start of a VM given a device by its numbers points the
            # hostdev at where the device is now.
            self.av.usb_keep("bbvm-web-db", [{"vendor": "0x0781", "product": "0x5583", "serial": "4C53", "port": "1-3", "name": "SanDisk Ultra Fit"}])
            dom = f"<domain><devices>{hw.usb_hostdev(stick, by_address=True)}</devices></domain>"
            with mock.patch.object(hw, "host_hw", return_value={"usb": [dict(stick, dev=12), boot], "pci": [], "cpus": [], "iommu": False}), \
                    mock.patch.object(self.av.subprocess, "run", side_effect=lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0, dom if "dumpxml" in argv else "", "")):
                self.assertEqual(a._vm_start(Job(), {}, "bbvm-web-db", who), ("succeeded", 0))
            self.assertTrue(any("define" in x for x in ran[-4:]), ran[-4:])
            with open(os.path.join(vmdir, "disks", "bbvm-web-db.xml")) as f:
                self.assertIn('device="12"', f.read())

    def test_the_domain_carries_its_marker_and_a_screen_on_the_loopback(self):
        x = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00")
        self.assertIn("<bb:vm xmlns:bb='https://builderbot.dev/vm/1' project='web'/>", x.replace('"', "'"))
        self.assertIn("host-passthrough", x)
        u = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00", boot="uefi",
                               fw=("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"), nvram="/v/d_VARS.fd")
        self.assertIn("<loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE_4M.fd</loader>", u)
        self.assertIn("<nvram format='qcow2'>/v/d_VARS.fd</nvram>", u, "qcow2, which a UEFI VM's snapshot needs")
        self.assertIn("machine='q35'", u)
        self.assertNotIn("<loader", x)
        # A screen for the dock (R99), on the loopback alone: the agent's
        # relay is the only way to it.
        self.assertIn("<graphics type='vnc' listen='127.0.0.1' autoport='yes'/>", x)
        self.assertIn("discard='unmap'", x)
        i = self.av.domain_xml("bbvm-web-win", "web", 2, 4096, "/v/w.qcow2", "/v/iso/ubuntu.iso", "bbvm-n00",
                               installer=True, extra=["/v/w-d1.qcow2"], mac="52:54:00:12:34:56", vnc_pw="s3cret")
        self.assertIn("<boot dev='cdrom'/><boot dev='hd'/>", i)
        self.assertIn("<target dev='vdb' bus='virtio'/><serial>bb", i)
        self.assertIn("-vdb</serial>", i)
        self.assertIn("<mac address='52:54:00:12:34:56'/>", i.replace('"', "'"))
        self.assertIn("passwd='s3cret'", i.replace('"', "'"))
        # A VM made a node is on the LAN by the host's own interface, where
        # the controller reaches it (R97's walk: behind the NAT it was not).
        self.assertIn("<source network='bbvm-n00'/>", x.replace('"', "'"))
        n = self.av.domain_xml("bbvm-web-db", "web", 2, 2048, "/v/d.qcow2", "/v/s.iso", "bbvm-n00", lan="enp1s0")
        self.assertIn("<interface type='direct'><source dev='enp1s0' mode='bridge'/>", n.replace('"', "'"))
        self.assertNotIn("bbvm-n00", n)
        ud = self.av.user_data("db", "builder", [KEY])
        self.assertIn("ssh_pwauth: false", ud)
        self.assertIn("    uid: 2000", ud, "one uid on every image, the one a shared folder's files are inside")
        # bash brought in where the image has none (Alpine), and the enroll
        # started from sh, which every image has.
        self.assertIn("apk add --no-cache bash sudo", ud)
        self.assertNotIn("bb-enroll", ud)
        en = self.av.user_data("db", "builder", [KEY], self.av.ENROLL_HEAD + "x")
        self.assertIn("[sh, -c, 'command -v bash", en)
        self.assertIn("bash /root/bb-enroll.sh", en)
        # Alpine's account takes its key, and the whole stays YAML cloud-init reads.
        self.assertIn('sed -i "s/^builder:!/builder:*/" /etc/shadow', ud)
        try:
            import yaml
        except ImportError:
            return
        self.assertEqual(yaml.safe_load(en)["runcmd"][0][0], "sh")
        self.assertIn(json.dumps(KEY), ud)


if __name__ == "__main__":
    unittest.main()


class Verbs(unittest.TestCase):
    """bb vm's hardware words (R100): what is named is sent, none takes it
    off, and what is not a hardware word is left for the verb."""

    def setUp(self):
        import importlib.util
        lib = os.path.join(HERE, "..", "..", "lib")
        sys.path.insert(0, lib)
        spec = importlib.util.spec_from_file_location("vm_verbs", os.path.join(lib, "vm-verbs.py"))
        self.v = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v)

    def test_hardware_words(self):
        hw, left = self.v.hw_opts(["--os", "debian", "--pin", "2,3", "--mem-max", "8G", "--share", "/data/", "--ro",
                                   "--autostart", "--why", "x"], ("--autostart",))
        self.assertEqual(hw, {"cpuset": [2, 3], "mem_max_mb": 8192, "share": {"path": "data", "ro": True}})
        self.assertEqual(left, ["--os", "debian", "--autostart", "--why", "x"])
        self.assertEqual(self.v.hw_opts(["--pin", "none", "--mem-max", "none", "--share", "none"], ())[0],
                         {"cpuset": [], "mem_max_mb": 0, "share": {}})
        self.assertEqual(self.v.hw_said({"hw": {"cpuset": [2, 3], "net": "lan"}, "autostart": True}),
                         "pinned to threads 2, 3 · on the LAN · starts with its host")


class Ask(unittest.TestCase):
    """A session's VM change asked of the administrators shows them the
    hardware in bb vm's own words, and keeps what the Allow will need."""

    def test_the_bell_says_what_is_asked(self):
        import phone
        seen = {}
        self.addCleanup(setattr, phone, "_queue", phone._queue)
        phone._queue = lambda kind, why, shown, *a, **kw: seen.update(shown=shown, extra=kw.get("extra")) or {"id": 1}
        phone.ask_vm("pin it", "web", {"action": "hardware", "name": "db", "hw": {"cpuset": [2, 3], "mem_max_mb": 0,
                                                                                  "share": {"path": "data", "ro": True}}}, "s")
        self.assertEqual(seen["shown"][-7:], ["--pin", "2,3", "--mem-max", "none", "--share", "data", "--ro"])
        phone.ask_vm("bigger", "web", {"action": "disk-grow", "name": "db", "disk": "vdb", "gb": 60}, "s")
        self.assertEqual((seen["shown"][-2:], seen["extra"]["vm"]["gb"], seen["extra"]["vm"]["disk"]), (["vdb", "60G"], 60, "vdb"))
        # A USB device to a VM (R116), as bb vm usb names it.
        phone.ask_vm("the stick", "web", {"action": "usb-give", "name": "db", "usb": {"vendor": "0x0781", "product": "0x5583", "serial": "4C53"}}, "s")
        self.assertEqual(seen["shown"], ["vm", "usb", "db", "give", "0781:5583:4C53"])
        self.assertEqual(seen["extra"]["vm"]["usb"]["serial"], "4C53")
        phone.ask_vm("back", "web", {"action": "usb-take", "name": "db", "usb": {"vendor": "0x0781", "product": "0x5583", "port": "1-3"}}, "s")
        self.assertEqual(seen["shown"], ["vm", "usb", "db", "take", "0781:5583", "--port", "1-3"])
