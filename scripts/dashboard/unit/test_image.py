"""The appliance image (R160 step 1): image/ holds one definition the
installed editions are made from, and its parts share their numbers through
image/partitions.sh. What can be held without building the image is held
here: the partition UUIDs agree across the build, the initramfs, fstab and
GRUB; the image carries every package the node's provisioner and the VM
host name for Debian; the slot tool reads the command line; the installer
has its stage and first-boot actions and the first-boot unit calls them
where they are laid out; the Debian family treats the image's packages as
fixed; the workflow pins the mkosi build.sh pins."""
import json
import os
import re
import shutil
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

    def test_the_projects_under_srv_are_kept_on_the_data_partition(self):
        # B437: the staged WORKSPACE is /srv/builderbot/projects, and the
        # root is a tmpfs overlay, so /srv is bound from /var.
        script = read(EXTRA, "etc", "initramfs-tools", "scripts", "init-bottom", "builderbot-os")
        self.assertIn('mount --bind "${rootmnt}/var/lib/builderbot-os/srv" "${rootmnt}/srv"', script)
        self.assertIn("WORKSPACE_DIR=/srv/builderbot/projects", read(ROOT, "nodes", "install-controller.sh"))

    def test_fstab_names_the_esp_here(self):
        self.assertIn(f"PARTUUID={self.p['BB_PART_ESP']}  /boot/efi", read(EXTRA, "etc", "fstab"))

    def test_grub_boots_each_slot_by_its_partition_and_finds_the_esp_by_its_serial(self):
        g = read(IMG, "grub.cfg")
        self.assertIn(f'set root_a="root=PARTUUID={self.p["BB_PART_ROOT_A"]}"', g)
        self.assertIn(f'set root_b="root=PARTUUID={self.p["BB_PART_ROOT_B"]}"', g)
        self.assertIn(f"--fs-uuid --set=root {self.p['BB_ESP_FSUUID']}", g)
        self.assertIn("bbslot=a", g)
        self.assertIn("bbslot=b", g)
        self.assertIn("overlayroot=tmpfs", g)

    def test_the_disk_is_laid_out_by_these_names(self):
        lay = read(IMG, "lay-disk")
        for k in ("BB_PART_BIOS", "BB_PART_ESP", "BB_PART_ROOT_A", "BB_PART_ROOT_B", "BB_PART_DATA",
                  "BB_SIZE_ESP_MIB", "BB_SIZE_SLOT_MIB", "BB_SIZE_DATA_MIB", "BB_ESP_FSUUID", "BB_ESP_LABEL", "BB_DATA_LABEL"):
            self.assertIn(k, lay, k)
        b = read(IMG, "build.sh")
        for k in ("BB_SIZE_ESP_MIB", "BB_SIZE_SLOT_MIB", "BB_SIZE_DATA_MIB"):
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

    def test_the_image_carries_every_tool_lay_disk_asks_for(self):
        # B446: the installer runs the image's own lay-disk on the ISO, so each
        # tool it checks for has to come with a package the image lists.
        lay = read(IMG, "lay-disk")
        tools = set(re.search(r"for t in ([^;]+); do command -v", lay).group(1).split())
        carried = {"sfdisk": "fdisk", "mkfs.vfat": "dosfstools", "mkfs.ext4": "e2fsprogs",
                   "grub-install": "grub-common", "grub-editenv": "grub-common", "partprobe": "parted"}
        self.assertEqual(tools - set(carried), set(), "a tool lay-disk asks for that this test does not map to its package")
        self.assertEqual({carried[t] for t in tools} - self.packages(), set())

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
        # Enabled by the post-install script, not a link in the extra tree
        # (a symlink does not travel with the tree, B417).
        post = read(IMG, "mkosi.postinst")
        self.assertIn("systemctl enable builderbot-os-firstboot.service builderbot-os-installer.service builderbot-os-health.service", post)
        self.assertFalse(os.path.exists(os.path.join(EXTRA, "etc", "systemd", "system", "multi-user.target.wants")))

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

    def test_the_disk_is_laid_out_by_one_script_the_image_carries(self):
        # R160 step 2: build.sh lays the image's disk out with lay-disk and
        # puts lay-disk, the numbers and GRUB's menu into the image, where
        # the installer runs the same script on a person's disk.
        b = read(IMG, "build.sh")
        self.assertIn('bash "$HERE/lay-disk" "$LOOP"', b)
        self.assertNotIn("sfdisk --quiet", b, "the layout lives in lay-disk alone")
        for f in ("lay-disk", "partitions.sh", "grub.cfg"):
            self.assertIn(f'"$TREE/usr/lib/builderbot-os/{f}"', b)
        lay = read(IMG, "lay-disk")
        self.assertIn('. "$HERE/partitions.sh"', lay)
        self.assertIn("--grow", lay)
        inst = read(EXTRA, "usr", "lib", "builderbot-os", "installer")
        self.assertIn('bash "$LIB/lay-disk" "$pick"', inst)
        self.assertIn("--grow", inst)
        self.assertIn("lib/builderbot-os/features", inst)
        unit = read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-installer.service")
        self.assertIn("ConditionKernelCommandLine=bbinstaller=1", unit)
        self.assertIn("TTYPath=/dev/tty1", unit)

    def test_the_iso_boots_the_same_root_live_with_the_installer(self):
        b = read(IMG, "build.sh")
        self.assertIn("grub-mkrescue -o", b)
        self.assertIn("live/filesystem.squashfs", b)
        g = read(IMG, "iso-grub.cfg")
        self.assertIn("boot=live components bbinstaller=1", g)
        self.assertIn("/live/vmlinuz", g)
        conf = read(IMG, "mkosi.conf")
        for p in ("live-boot", "live-boot-initramfs-tools", "whiptail"):
            self.assertIn(p, conf, p)
        wf = read(ROOT, ".github", "workflows", "build-image.yml")
        self.assertIn("xorriso mtools", wf)
        self.assertIn("out/builderbot-os-*.iso", wf)

    def test_the_first_boot_turns_on_the_features_the_installer_was_asked_for(self):
        inst = read(ROOT, "nodes", "install-controller.sh")
        self.assertIn('OS_FEATURES_FILE="$P/var/lib/builderbot-os/features"', inst)
        self.assertIn('"${OS_FEATURES[@]}"', inst)
        self.assertIn("vmhost|firewall|iommu) OS_FEATURES+=(--feature", inst)

    def test_nothing_is_published_before_the_image_boots(self):
        # R160 step 5: the publish job waits on the boot job, which waits
        # on the build; step 6: the weekly schedule builds with the day's
        # snapshot and keeps the package diff.
        wf = read(ROOT, ".github", "workflows", "build-image.yml")
        self.assertRegex(wf, r"appliance-boot:\n    needs: appliance\n")
        self.assertRegex(wf, r"appliance-publish:\n    needs: appliance-boot\n")
        self.assertIn("hostfwd=tcp:127.0.0.1:7680-:7680", wf)
        self.assertIn("github.event_name == 'schedule'", wf)
        self.assertIn("builderbot-os-*.packages", wf)
        self.assertIn('"$OUT/$NAME.packages"', read(IMG, "build.sh"))

    def test_a_stick_loads_the_slot_into_memory_when_grub_says_so(self):
        # R161 step 1: bb_toram=1 in grubenv turns root= into the copy in
        # memory and names the slot's partition; the initramfs script and
        # hook do the copy, and the slot tool reads and sets the switch.
        p = shell_vars(os.path.join(IMG, "partitions.sh"))
        g = read(IMG, "grub.cfg")
        self.assertIn('if [ "$bb_toram" = 1 ]', g)
        self.assertIn(f'root=/dev/loop0 bbslotdev=PARTUUID={p["BB_PART_ROOT_A"]} bbtoram=1', g)
        self.assertIn(f'root=/dev/loop0 bbslotdev=PARTUUID={p["BB_PART_ROOT_B"]} bbtoram=1', g)
        self.assertIn("$root_a rootfstype=squashfs", g)
        top = read(EXTRA, "etc", "initramfs-tools", "scripts", "local-top", "builderbot-os-toram")
        self.assertIn("od -An -t u8 -j 40 -N 8", top)
        self.assertIn("losetup /dev/loop0 /run/bbroot/root.squashfs", top)
        hook = read(EXTRA, "etc", "initramfs-tools", "hooks", "builderbot-os")
        self.assertIn("copy_exec /sbin/losetup", hook)
        self.assertIn("loop", read(EXTRA, "etc", "initramfs-tools", "modules").split())
        tool = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "slot")
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "cmdline")
            open(c, "w").write("root=/dev/loop0 bbslotdev=PARTUUID=x bbtoram=1 bbslot=a\n")
            r = sh(f"bash {tool} status", {"BB_CMDLINE": c, "BB_ESP": os.path.join(d, "esp"), "BB_OS_RELEASE": os.path.join(d, "none")})
            self.assertIn("root in memory: yes", r.stdout)
            self.assertEqual(sh(f"bash {tool} ram", {"BB_CMDLINE": c, "BB_ESP": os.path.join(d, "esp")}).stdout.strip(), "off")

    def test_a_trial_slot_is_counted_by_grub_and_marked_good_by_the_health_check(self):
        # R161 step 2: GRUB counts the boots of a slot on trial and goes
        # back after two without the health check's word; Safe mode boots
        # the slot held; the slot tool sets and ends a trial in GRUB's
        # environment, which grub-editenv reads back.
        g = read(IMG, "grub.cfg")
        self.assertIn('if [ "$bb_trial" = 1 ]', g)
        self.assertIn('set bb_slot="$bb_prev"', g)
        self.assertIn("save_env bb_slot bb_trial bb_tries bb_fell_back", g)
        self.assertIn('menuentry "Safe mode', g)
        self.assertIn("bbsafe=1", g)
        unit = read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-health.service")
        self.assertIn("ConditionKernelCommandLine=bbslot", unit)
        self.assertIn("ExecStart=/usr/lib/builderbot-os/health", unit)
        self.assertIn('bash "$SLOT" good', read(EXTRA, "usr", "lib", "builderbot-os", "health"))
        if not shutil.which("grub-editenv"):
            self.skipTest("no grub-editenv here")
        tool = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "slot")
        with tempfile.TemporaryDirectory() as d:
            esp = os.path.join(d, "esp"); os.makedirs(os.path.join(esp, "grub"))
            c = os.path.join(d, "cmdline"); open(c, "w").write("bbslot=a\n")
            env = {"BB_CMDLINE": c, "BB_ESP": esp, "BB_OS_RELEASE": os.path.join(d, "none")}
            self.assertEqual(sh(f"bash {tool} next b", env).returncode, 0)
            r = sh(f"bash {tool} trial a 0.9.1", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = sh(f"grub-editenv {esp}/grub/grubenv list", env).stdout
            for want in ("bb_slot=b", "bb_trial=1", "bb_tries=0", "bb_prev=a", "bb_ver_b=0.9.1"):
                self.assertIn(want, got, got)
            st = sh(f"bash {tool} status", env).stdout
            self.assertIn("trial: slot b, 0 boot(s) so far, back to slot a", st)
            self.assertEqual(sh(f"bash {tool} good", env).returncode, 0)
            got = sh(f"grub-editenv {esp}/grub/grubenv list", env).stdout
            self.assertIn("bb_trial=0", got)
            self.assertEqual(sh(f"bash {tool} fell-back", env).stdout.strip(), "no")
            sh(f"grub-editenv {esp}/grub/grubenv set bb_fell_back=1", env)
            self.assertEqual(sh(f"bash {tool} fell-back", env).stdout.strip(), "yes")
            self.assertEqual(sh(f"bash {tool} fell-back", env).stdout.strip(), "no", "read once, then cleared")

    def test_the_boots_own_settings_reach_the_controller_from_the_esp_and_the_command_line(self):
        # R161 step 6: builderbot.env on the ESP and builderbot.debug=1 on
        # the command line land in /run/builderbot-os/env, a short list of
        # names only, which the controller's unit reads if it is there.
        tool = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "env")
        with tempfile.TemporaryDirectory() as d:
            esp = os.path.join(d, "esp"); os.makedirs(esp)
            open(os.path.join(esp, "builderbot.env"), "w").write("# the stick's own\r\nDEBUG_MODE=1\r\nTZ=Europe/Paris\nPATH=/evil\nBB_RELEASE_LINE=0.9\nBB_RELEASE_CHANNEL=dev\n" + " " * 3000 + "\n")
            c = os.path.join(d, "cmdline"); open(c, "w").write("bbslot=a quiet\n")
            run = os.path.join(d, "run")
            r = sh(f"bash {tool}", {"BB_ESP": esp, "BB_OS_RUN": run, "BB_CMDLINE": c})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(open(os.path.join(run, "env")).read().splitlines(), ["DEBUG_MODE=1", "TZ=Europe/Paris", "BB_RELEASE_LINE=0.9", "BB_RELEASE_CHANNEL=dev"])
            self.assertEqual(open(os.path.join(run, "net")).read(), "", "a stick that names no network settings")
            with open(os.path.join(esp, "builderbot.env"), "a") as f:
                f.write("BB_HOSTNAME=tower\nBB_NET_ADDRESS=192.0.2.20\nBB_NET_DNS=1.1.1.1,9.9.9.9;x\n")
            sh(f"bash {tool}", {"BB_ESP": esp, "BB_OS_RUN": run, "BB_CMDLINE": c})
            self.assertNotIn("BB_NET_ADDRESS", open(os.path.join(run, "env")).read(), "the network's keys are not the controller's")
            self.assertEqual(open(os.path.join(run, "net")).read().splitlines(), ["BB_HOSTNAME=tower", "BB_NET_ADDRESS=192.0.2.20", "BB_NET_DNS=1.1.1.1,9.9.9.9x"])
            os.unlink(os.path.join(esp, "builderbot.env"))
            open(c, "w").write("bbslot=a builderbot.debug=1\n")
            sh(f"bash {tool}", {"BB_ESP": esp, "BB_OS_RUN": run, "BB_CMDLINE": c})
            self.assertEqual(open(os.path.join(run, "env")).read().splitlines(), ["DEBUG_MODE=1"])
            open(c, "w").write("bbslot=a\n")
            sh(f"bash {tool}", {"BB_ESP": esp, "BB_OS_RUN": run, "BB_CMDLINE": c})
            self.assertEqual(open(os.path.join(run, "env")).read(), "", "off at a start that did not ask")
        # ...and the stick is laid with the file at its fixed 4 KiB behind
        # the marker the stick maker writes --set into (R161 step 12).
        lay = read(IMG, "lay-disk")
        self.assertIn('"$MNT/builderbot.env"', lay)
        self.assertIn("# builderbot.env BB-STICK-ENV-1", lay)
        # ...and the prepared configuration's 64 KiB (R161 step 8), taken off
        # the stick by a root step before the controller starts.
        self.assertIn('"$MNT/builderbot/firstboot.json"', lay)
        self.assertIn("BB-FIRSTBOOT-1", lay)
        # ...and the catalog's mirror's 64 MiB (R169 step 6).
        self.assertIn('"$MNT/builderbot/catalog-mirror.bin"', lay)
        self.assertIn("BB-MIRROR-1", lay)
        self.assertIn("ExecStart=-/usr/lib/builderbot-os/firstboot-take",
                      read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-env.service"))
        self.assertTrue(os.access(os.path.join(EXTRA, "usr", "lib", "builderbot-os", "firstboot-take"), os.X_OK))
        unit = read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-env.service")
        self.assertIn("Before=builderbot-controller.service systemd-networkd.service", unit)
        self.assertIn("ExecStart=-/usr/lib/builderbot-os/net", unit)
        self.assertIn("builderbot-os-env.service", read(IMG, "mkosi.postinst"))
        self.assertIn("EnvironmentFile=-/run/builderbot-os/env", read(ROOT, "nodes", "install-controller.sh"))

    def test_the_sticks_network_settings_write_a_network_file_before_dhcps(self):
        # R161 step 12: BB_NET_ADDRESS and its mask, gateway and DNS become a
        # runtime .network file that sorts before the image's 80-dhcp one;
        # anything that is not an address leaves DHCP standing.
        tool = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "net")
        self.assertTrue(os.access(tool, os.X_OK))
        self.assertIn("80-dhcp.network", read(IMG, "mkosi.postinst"))
        with tempfile.TemporaryDirectory() as d:
            run, nd = os.path.join(d, "run"), os.path.join(d, "network")
            os.makedirs(run)
            env = {"BB_OS_RUN": run, "BB_NETWORK_DIR": nd, "BB_NET_NO_APPLY": "1"}
            out = os.path.join(nd, "10-builderbot-stick.network")

            def boot(lines):
                open(os.path.join(run, "net"), "w").write("".join(x + "\n" for x in lines))
                return sh(f"bash {tool}", env)
            r = boot(["BB_HOSTNAME=tower", "BB_NET_ADDRESS=192.0.2.20", "BB_NET_MASK=255.255.255.0", "BB_NET_GATEWAY=192.0.2.1", "BB_NET_DNS=1.1.1.1,9.9.9.9"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("the hostname is tower", r.stdout)
            self.assertEqual(open(out).read(), "[Match]\nName=en* eth*\n\n[Network]\nAddress=192.0.2.20/24\nGateway=192.0.2.1\nDNS=1.1.1.1\nDNS=9.9.9.9\n")
            boot(["BB_NET_ADDRESS=10.0.0.5", "BB_NET_MASK=16"])
            self.assertEqual(open(out).read(), "[Match]\nName=en* eth*\n\n[Network]\nAddress=10.0.0.5/16\n", "a mask as its length, no gateway or DNS")
            boot(["BB_NET_ADDRESS=10.0.0.5"])
            self.assertIn("Address=10.0.0.5/24", open(out).read(), "24 when the mask is left out")
            for bad in (["BB_NET_ADDRESS=10.0.0.300"], ["BB_NET_ADDRESS=10.0.0.5", "BB_NET_MASK=255.0.255.0"],
                        ["BB_NET_ADDRESS=10.0.0.5", "BB_NET_MASK=33"], ["BB_NET_ADDRESS=10.0.0.5", "BB_NET_GATEWAY=router"]):
                boot(["BB_NET_ADDRESS=10.0.0.5"])
                r = boot(bad)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse(os.path.exists(out), bad)
                self.assertIn("DHCP stands", r.stderr)
            r = boot(["BB_NET_ADDRESS=10.0.0.5", "BB_NET_DNS=1.1.1.1,dns.example"])
            self.assertEqual(open(out).read().count("DNS="), 1)
            self.assertIn("dns.example in BB_NET_DNS is not an IPv4 address", r.stderr)
            r = boot(["BB_HOSTNAME=Not_A_Host"])
            self.assertFalse(os.path.exists(out), "no address, DHCP")
            self.assertIn("is not a hostname", r.stderr)

    @unittest.skipUnless(shutil.which("sfdisk"), "sfdisk is not here")
    def test_the_data_partition_grows_to_its_disk_up_to_the_cap(self):
        # R161 step 13: a stick bigger than the image has its data partition,
        # the last, grown to the disk's end at boot, no further than
        # BB_DATA_MAX, and never shrunk; a last partition that is not the
        # data partition is left as it is.
        tool = os.path.join(EXTRA, "usr", "lib", "builderbot-os", "grow")
        self.assertIn("ExecStart=-/usr/lib/builderbot-os/grow", read(EXTRA, "usr", "lib", "systemd", "system", "builderbot-os-env.service"))
        v = shell_vars(os.path.join(IMG, "partitions.sh"))
        with tempfile.TemporaryDirectory() as d:
            run = os.path.join(d, "run"); os.makedirs(run)
            disk = os.path.join(d, "disk.img")

            def lay(mib, data_uuid=v["BB_PART_DATA"]):
                with open(disk, "wb") as f:
                    f.truncate(64 << 20)
                table = ("label: gpt\nstart=2048, size=2048, name=bios\nsize=4MiB, name=esp\nsize=4MiB, name=a\nsize=4MiB, name=b\n"
                         f"size=16MiB, uuid={data_uuid}, name=bbdata\n")
                r = subprocess.run(["sfdisk", "--quiet", disk], input=table, capture_output=True, text=True, check=False)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(disk, "r+b") as f:
                    f.truncate(mib << 20)       # the image written to a bigger stick

            def grow(cap=""):
                open(os.path.join(run, "env"), "w").write(f"BB_DATA_MAX={cap}\n" if cap else "")
                r = sh(f"bash {tool}", {"BB_GROW_DISK": disk, "BB_OS_RUN": run, "BB_PARTITIONS": os.path.join(IMG, "partitions.sh")})
                self.assertEqual(r.returncode, 0, r.stderr)
                t = json.loads(subprocess.run(["sfdisk", "--json", disk], capture_output=True, text=True, check=True).stdout)["partitiontable"]
                return r.stdout, t["partitions"][-1]["size"] // 2048, t["lastlba"]
            lay(256)
            out, mib, last = grow()
            self.assertIn("the data partition is", out)
            self.assertGreater(mib, 200)
            self.assertEqual(last, (256 << 11) - 34, "the backup GPT moved to the disk's end")
            self.assertEqual(grow()[0], "", "nothing to say once it is grown")
            lay(256)
            self.assertEqual(grow("64M")[1], 64)
            self.assertEqual(grow("32M")[1], 64, "never shrunk")
            lay(256)
            out, mib, _ = grow("lots")
            self.assertIn("is not a size", out)
            self.assertGreater(mib, 200, "a cap that is not a size is no cap")
            lay(256, data_uuid="00000000-0000-4000-8000-000000000001")
            out, mib, _ = grow()
            self.assertIn("not the data partition", out)
            self.assertEqual(mib, 16)

    def test_the_disk_is_xz_and_the_stick_variant_runs_from_memory(self):
        # R161 step 5: xz, which the stick maker opens with Python's own
        # library; the stick's disk is the same with bb_toram=1 set.
        b = read(IMG, "build.sh")
        self.assertIn('xz -q -T0 -6 "$RAW"', b)
        self.assertIn('grub-editenv "$MNT/grub/grubenv" set bb_toram=1', b)
        self.assertIn("stick.raw.xz", read(ROOT, ".github", "workflows", "build-image.yml"))
        self.assertTrue(os.access(os.path.join(ROOT, "tools", "builderbot-stick.py"), os.X_OK))

    def test_build_sh_says_how_without_root(self):
        r = sh("bash image/build.sh --help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--tree-only", r.stdout)


if __name__ == "__main__":
    unittest.main()
