"""The appliance image (R160 step 1): image/ holds one definition the
installed editions are made from, and its parts share their numbers through
image/partitions.sh. What can be held without building the image is held
here: the partition UUIDs agree across the build, the initramfs, fstab and
GRUB; the image carries every package the node's provisioner and the VM
host name for Debian; the slot tool reads the command line; the installer
has its stage and first-boot actions and the first-boot unit calls them
where they are laid out; the Debian family treats the image's packages as
fixed; the workflow pins the mkosi build.sh pins."""
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
IMG = os.path.join(ROOT, "image")
EXTRA = os.path.join(IMG, "mkosi.extra")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def shell_vars(path):
    out = {}
    for line in read(path).splitlines():
        m = re.match(r"^([A-Z_]+)=([^#\s]+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def sh(script, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=e, cwd=ROOT)


class Partitions(unittest.TestCase):
    def setUp(self):
        self.p = shell_vars(os.path.join(IMG, "partitions.sh"))

    def test_the_initramfs_mounts_the_data_partition_named_here(self):
        script = read(EXTRA, "etc", "initramfs-tools", "scripts", "init-bottom", "builderbot-os")
        self.assertIn(f"by-partuuid/{self.p['BB_PART_DATA']}", script)

    def test_fstab_names_the_esp_here(self):
        self.assertIn(f"PARTUUID={self.p['BB_PART_ESP']}  /boot/efi", read(EXTRA, "etc", "fstab"))

    def test_grub_boots_each_slot_by_its_partition_and_finds_the_esp_by_its_serial(self):
        g = read(IMG, "grub.cfg")
        self.assertIn(f"root=PARTUUID={self.p['BB_PART_ROOT_A']} ", g)
        self.assertIn(f"root=PARTUUID={self.p['BB_PART_ROOT_B']} ", g)
        self.assertIn(f"--fs-uuid --set=root {self.p['BB_ESP_FSUUID']}", g)
        self.assertIn("bbslot=a", g)
        self.assertIn("bbslot=b", g)
        self.assertIn("overlayroot=tmpfs", g)

    def test_the_build_lays_the_disk_out_by_these_names(self):
        b = read(IMG, "build.sh")
        for k in ("BB_PART_BIOS", "BB_PART_ESP", "BB_PART_ROOT_A", "BB_PART_ROOT_B", "BB_PART_DATA",
                  "BB_SIZE_ESP_MIB", "BB_SIZE_SLOT_MIB", "BB_SIZE_DATA_MIB", "BB_ESP_FSUUID", "BB_ESP_LABEL", "BB_DATA_LABEL"):
            self.assertIn(k, b, k)


class Packages(unittest.TestCase):
    def packages(self):
        conf = read(IMG, "mkosi.conf")
        body = conf.split("Packages=", 1)[1]
        return {line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")}

    def test_the_image_carries_what_the_debian_node_provisioner_installs(self):
        r = sh(". nodes/families/deb.sh; for k in base python pycrypto session reel wg nft; do pkg_names $k; done")
        self.assertEqual(r.returncode, 0, r.stderr)
        want = set(r.stdout.split())
        self.assertTrue(want, "the family names nothing")
        self.assertEqual(want - self.packages(), set())

    def test_the_image_carries_the_vm_host_feature(self):
        # vmhost_pkgs is past the provisioner's library return, so its deb
        # line is read as text.
        m = re.search(r'deb:x86_64\)\s+echo "([^"]+)"', read(ROOT, "nodes", "provision-linux.sh"))
        self.assertTrue(m, "vmhost_pkgs has no deb:x86_64 line")
        want = set(m.group(1).split())
        self.assertTrue(want)
        self.assertEqual(want - self.packages(), set())

    def test_the_controllers_own_list_reads_for_the_image(self):
        r = sh("bash scripts/lib/controller-packages.sh deb core tools host")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("python3", r.stdout.split())
        self.assertNotIn("@docker", r.stdout)

    def test_the_kernel_boots_the_slot(self):
        for p in ("linux-image-amd64", "initramfs-tools", "overlayroot", "grub-efi-amd64-bin", "grub-pc-bin", "squashfs-tools", "zfs-dkms"):
            self.assertIn(p, self.packages(), p)


class SlotTool(unittest.TestCase):
    TOOL = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "slot")

    def run_tool(self, *args, cmdline="bbslot=b quiet", esp=None):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "cmdline")
            with open(c, "w", encoding="utf-8") as f:
                f.write(cmdline + "\n")
            return sh(f"bash {self.TOOL} {' '.join(args)}", {"BB_CMDLINE": c, "BB_ESP": esp or os.path.join(d, "esp"),
                                                             "BB_OS_RELEASE": os.path.join(d, "none")})

    def test_the_slot_is_read_from_the_command_line(self):
        self.assertEqual(self.run_tool("current").stdout.strip(), "b")
        self.assertEqual(self.run_tool("other").stdout.strip(), "a")
        self.assertEqual(self.run_tool("current", cmdline="bbslot=a").stdout.strip(), "a")

    def test_a_boot_that_names_no_slot_is_said(self):
        r = self.run_tool("current", cmdline="root=/dev/sda1 ro")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a BuilderBot OS boot", r.stderr)

    def test_next_is_slot_a_until_grub_says_otherwise_and_cannot_be_set_without_the_esp(self):
        self.assertEqual(self.run_tool("next").stdout.strip(), "a")
        r = self.run_tool("next", "b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is the ESP mounted", r.stderr)
        self.assertEqual(self.run_tool("next", "c").returncode, 2)


class Installer(unittest.TestCase):
    INST = os.path.join(ROOT, "nodes", "install-controller.sh")

    def test_stage_and_firstboot_are_actions_its_help_names(self):
        r = sh(f"bash {self.INST} --help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--stage", r.stdout)
        self.assertIn("--firstboot", r.stdout)
        r = sh(f"BB_CONTROLLER_LIB=1 . {self.INST}; declare -F cmd_stage cmd_firstboot")
        self.assertEqual(r.stdout.split(), ["cmd_stage", "cmd_firstboot"], r.stderr)

    def test_the_first_boot_unit_runs_the_installer_where_it_is_laid_out_and_once(self):
        unit = read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-firstboot.service")
        self.assertIn("ExecStart=/opt/builderbot/nodes/install-controller.sh --firstboot", unit)
        self.assertIn("ConditionPathExists=!/etc/builderbot-controller/own-node", unit)
        inst = read(self.INST)
        self.assertIn('OWN_MARK="$ETC/own-node"', inst)
        self.assertIn('ETC="$P/etc/builderbot-controller"', inst)
        link = os.path.join(EXTRA, "etc", "systemd", "system", "multi-user.target.wants", "builderbot-os-firstboot.service")
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(link), os.readlink(link))))

    def test_the_postinst_stages_the_controller_from_the_checkout(self):
        post = read(IMG, "mkosi.postinst")
        self.assertIn("install-controller.sh\" --stage", post)
        self.assertIn("update-initramfs -u -k all", post)
        self.assertIn("dpkg-divert", post)

    def test_a_staged_service_is_enabled_and_not_started(self):
        prov = read(ROOT, "nodes", "provision-linux.sh")
        self.assertIn('BB_SVC_NO_START', prov)
        inst = read(self.INST)
        self.assertIn("BB_SVC_NO_START=1 service", inst)


class DebianOnTheImage(unittest.TestCase):
    def test_a_package_the_image_has_passes_and_one_it_lacks_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            rel = os.path.join(d, "release")
            open(rel, "w", encoding="utf-8").write("BUILDERBOT_OS_VERSION=test\n")
            env = {"BB_OS_RELEASE": rel}
            r = sh(". nodes/families/deb.sh; pkg_refresh && pkg bash 'no-such-package-zz|bash'", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = sh(". nodes/families/deb.sh; pkg bash no-such-package-zz", env)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not in the BuilderBot OS image: no-such-package-zz", r.stderr)


class Workflow(unittest.TestCase):
    def test_the_workflow_builds_with_the_mkosi_build_sh_pins(self):
        wf = read(ROOT, ".github", "workflows", "build-image.yml")
        self.assertIn("appliance:", wf)
        self.assertIn("MKOSI_PIN:-", wf)
        b = read(IMG, "build.sh")
        self.assertRegex(b, r'(?m)^MKOSI_PIN="\$\{MKOSI_PIN:-\d+(\.\d+)?\}"$')
        snap = read(IMG, "SNAPSHOT").strip()
        self.assertRegex(snap, r"^\d{8}T\d{6}Z$")

    def test_the_vm_disks_are_the_same_disk_converted(self):
        # R160 step 3: qcow2 and an OVA from the raw disk, never a fourth
        # layout; the descriptor's marks are the ones the build fills, and
        # the workflow installs what converts them.
        b = read(IMG, "build.sh")
        self.assertIn("qemu-img convert -O qcow2", b)
        self.assertIn("subformat=streamOptimized", b)
        ovf = read(IMG, "ovf.xml")
        for mark in ("@NAME@", "@VMDK@", "@VMDK_SIZE@", "@CAPACITY@"):
            self.assertIn(mark, ovf)
            self.assertIn(f"s|{mark}|", b)
        import xml.dom.minidom
        xml.dom.minidom.parseString(ovf)
        self.assertIn("qemu-utils", read(ROOT, ".github", "workflows", "build-image.yml"))

    def test_build_sh_says_how_without_root(self):
        r = sh("bash image/build.sh --help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--tree-only", r.stdout)


if __name__ == "__main__":
    unittest.main()
