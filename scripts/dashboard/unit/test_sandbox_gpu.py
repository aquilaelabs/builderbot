"""bb-sandbox's gpu-driver and gpu-container verbs, run as the bash they are against stand-in
tools (R102). The agent and server suites stub bb-sandbox whole, so nothing
ran this script's own lines, and its `set -euo pipefail` ended a real
install without a word on the dev node (30 Sep): the lookup of the installed
branch asked dpkg for packages that were not there. This runs the helper
extracted from the provisioner, with apt, dpkg, modinfo, ubuntu-drivers and
id stood in for, and reads what it ran and what it said."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROVISIONER = os.path.join(HERE, "..", "..", "..", "nodes", "provision-linux.sh")
REAL = ("bash", "sh", "cat", "grep", "awk", "sed", "sort", "tail", "head", "tr", "seq", "sleep",
        "basename", "cut", "uname", "rm", "chmod", "printf", "env", "readlink", "mktemp", "dirname", "ls", "date")


class GpuDriver(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        with open(os.environ.get("BB_TEST_PROVISIONER") or PROVISIONER, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"^cat > \"\$BBSANDBOX_TMP\" <<'BBSANDBOX'\n(.*?)^BBSANDBOX$", text, re.S | re.M)
        self.helper = os.path.join(self.dir, "bb-sandbox")
        with open(self.helper, "w", encoding="utf-8") as f:
            f.write(m.group(1))
        for t in REAL:
            real = shutil.which(t)
            if real:
                os.symlink(real, os.path.join(self.bin, t))
        self.log = os.path.join(self.dir, "ran")
        self.state = os.path.join(self.dir, "installed")      # "VERSION PACKAGE" once a driver is on
        self.tool("id", 'echo 0')
        self.tool("lspci", 'echo "04:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA104 [GeForce RTX 3070 Ti] [10de:2482]"')
        self.tool("pgrep", "exit 1")
        self.tool("nvidia-smi", "exit 9")
        self.tool("modinfo", f'[ -s "{self.state}" ] && {{ cut -d" " -f1 "{self.state}"; exit 0; }}; exit 1')
        self.tool("dpkg-query", f'''case "$*" in
  *nvidia-driver\\**) [ -s "{self.state}" ] && {{ echo "$(cut -d' ' -f2 "{self.state}") ii "; exit 0; }}; exit 1 ;;
  *) [ -s "{self.state}" ] && echo "$(cut -d' ' -f2 "{self.state}") ii "; echo "libnvidia-gl-610 ii "; echo "firefox ii "; exit 0 ;;
esac''')
        self.tool("apt-get", f'echo "apt-get $*" >> "{self.log}"; case "$*" in *purge*) rm -f "{self.state}" ;; esac; exit 0')
        self.tool("ubuntu-drivers", f'''echo "ubuntu-drivers $*" >> "{self.log}"
case "$2" in nvidia:610) echo "610.57.04 nvidia-driver-610" > "{self.state}" ;; *) echo "595.91.07 nvidia-driver-595-open" > "{self.state}" ;; esac''')

    def tool(self, name, body):
        f = os.path.join(self.bin, name)
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + body + "\n")
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)

    def run_helper(self, *args):
        p = subprocess.run([shutil.which("bash"), self.helper, *args], capture_output=True, text=True,
                           timeout=60, check=False, env={"PATH": self.bin, "HOME": self.dir})
        ran = ""
        if os.path.exists(self.log):
            with open(self.log) as f:
                ran = f.read()
        return p.returncode, p.stdout + p.stderr, ran

    def toolkit(self):
        """Stand-ins for what the container toolkit's verbs touch: NVIDIA's
        package source over curl, gpg, docker, nvidia-ctk and systemctl, and
        the helper's two files moved under the scratch directory."""
        self.list = os.path.join(self.dir, "nvidia-container-toolkit.list")
        self.key = os.path.join(self.dir, "nvidia-container-toolkit-keyring.gpg")
        self.ctk = os.path.join(self.dir, "toolkit")
        with open(self.helper, encoding="utf-8") as f:
            text = f.read()
        text, n = re.subn(r"^NVCT_LIST=.*$", f"NVCT_LIST={self.list}", text, flags=re.M)
        text, k = re.subn(r"^NVCT_KEY=.*$", f"NVCT_KEY={self.key}", text, flags=re.M)
        self.assertEqual((n, k), (1, 1))
        with open(self.helper, "w", encoding="utf-8") as f:
            f.write(text)
        self.tool("curl", f'''echo "curl $*" >> "{self.log}"
case "$*" in
  *gpgkey*) echo "-----BEGIN PGP PUBLIC KEY BLOCK-----" ;;
  *.list*) echo "deb https://nvidia.github.io/libnvidia-container/stable/deb/\\$(ARCH) /" ;;
  *) exit 22 ;;
esac''')
        self.tool("gpg", 'while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done; cat > "$out"')
        self.tool("docker", "exit 0")
        self.tool("nvidia-ctk", f'echo "nvidia-ctk $*" >> "{self.log}"')
        self.tool("systemctl", f'echo "systemctl $*" >> "{self.log}"')
        self.tool("apt-get", f'''echo "apt-get $*" >> "{self.log}"
case "$*" in
  *install*nvidia-container-toolkit*) echo on > "{self.ctk}" ;;
  *purge*) rm -f "{self.ctk}" "{self.state}" ;;
esac; exit 0''')
        self.tool("dpkg-query", f'''[ -s "{self.ctk}" ] && {{ echo "nvidia-container-toolkit ii "; echo "libnvidia-container1 ii "; }}
echo "docker-ce ii "; exit 0''')

    def driver_on(self):
        with open(self.state, "w") as f:
            f.write("610.57.04 nvidia-driver-610\n")

    def test_the_toolkit_adds_nvidias_source_installs_and_restarts_docker(self):
        self.toolkit()
        self.driver_on()
        rc, said, ran = self.run_helper("gpu-container", "install")
        self.assertEqual(rc, 0, said)
        with open(self.list) as f:
            src = f.read()
        self.assertIn(f"deb [signed-by={self.key}] https://nvidia.github.io/libnvidia-container", src)
        self.assertTrue(os.path.getsize(self.key))
        lines = ran.splitlines()
        install = next(i for i, ln in enumerate(lines) if " install " in ln and "nvidia-container-toolkit" in ln)
        self.assertIn("DPkg::Lock::Timeout", lines[install])
        configure = lines.index("nvidia-ctk runtime configure --runtime=docker")
        self.assertLess(install, configure)
        self.assertLess(configure, lines.index("systemctl restart docker"))

    def test_the_toolkit_waits_for_the_driver(self):
        self.toolkit()
        rc, said, ran = self.run_helper("gpu-container", "install")
        self.assertNotEqual(rc, 0)
        self.assertIn("driver is not installed", said)
        self.assertEqual(ran, "")
        self.assertFalse(os.path.exists(self.list))

    def test_a_source_that_does_not_answer_leaves_nothing_behind(self):
        self.toolkit()
        self.driver_on()
        self.tool("curl", "exit 22")
        rc, said, ran = self.run_helper("gpu-container", "install")
        self.assertNotEqual(rc, 0)
        self.assertIn("could not fetch", said)
        self.assertFalse(os.path.exists(self.list))
        self.assertFalse(os.path.exists(self.key))
        self.assertNotIn("apt-get", ran)

    def test_removing_the_toolkit_takes_its_source_with_it(self):
        self.toolkit()
        for f in (self.list, self.key, self.ctk):
            with open(f, "w") as h:
                h.write("x\n")
        rc, said, ran = self.run_helper("gpu-container", "remove")
        self.assertEqual(rc, 0, said)
        purge = [ln for ln in ran.splitlines() if " purge " in ln][0]
        self.assertIn("nvidia-container-toolkit", purge)
        self.assertIn("libnvidia-container1", purge)
        self.assertNotIn("docker-ce", purge)
        self.assertIn("nvidia-ctk runtime configure --runtime=docker --unset", ran)
        self.assertLess(ran.index("--unset"), ran.index(" purge "))
        self.assertIn("systemctl restart docker", ran)
        self.assertFalse(os.path.exists(self.list) or os.path.exists(self.key))

    def test_a_picked_branch_on_a_machine_with_no_driver(self):
        rc, said, ran = self.run_helper("gpu-driver", "install", "nvidia-driver-610")
        self.assertEqual(rc, 0, said)
        self.assertIn("ubuntu-drivers install nvidia:610", ran)
        self.assertIn("installed the NVIDIA driver 610.57.04", said)
        self.assertIn("takes the card at the next boot", said)

    def test_the_recommended_one_when_none_is_named(self):
        rc, said, ran = self.run_helper("gpu-driver", "install")
        self.assertEqual(rc, 0, said)
        self.assertRegex(ran, r"ubuntu-drivers install\n")
        self.assertIn("installed the NVIDIA driver 595.91.07", said)

    def test_a_name_that_is_not_a_driver_package_is_refused(self):
        rc, said, ran = self.run_helper("gpu-driver", "install", "nvidia-driver-610; reboot")
        self.assertNotEqual(rc, 0)
        self.assertIn("is not a driver package", said)
        self.assertNotIn("ubuntu-drivers", ran)

    def test_another_branch_waits_for_the_installed_one_to_be_removed(self):
        with open(self.state, "w") as f:
            f.write("595.91.07 nvidia-driver-595-open\n")
        rc, said, ran = self.run_helper("gpu-driver", "install", "nvidia-driver-610")
        self.assertNotEqual(rc, 0)
        self.assertIn("remove it first", said)
        self.assertNotIn("ubuntu-drivers", ran)

    def test_remove_purges_the_drivers_packages_and_only_those(self):
        with open(self.state, "w") as f:
            f.write("610.57.04 nvidia-driver-610\n")
        rc, said, ran = self.run_helper("gpu-driver", "remove")
        self.assertEqual(rc, 0, said)
        purge = [ln for ln in ran.splitlines() if " purge " in ln][0]
        self.assertIn("nvidia-driver-610", purge)
        self.assertIn("libnvidia-gl-610", purge)
        self.assertNotIn("firefox", purge)
        self.assertIn("DPkg::Lock::Timeout", purge)

    def test_refresh_reads_the_package_lists_again(self):
        rc, said, ran = self.run_helper("gpu-driver", "refresh")
        self.assertEqual(rc, 0, said)
        self.assertIn("update", ran)

    def test_the_display_does_not_install_the_driver(self):
        rc, said, ran = self.run_helper("gpu")
        self.assertNotEqual(rc, 0)
        self.assertIn("Toolchains tab", said)
        self.assertEqual(ran, "")


if __name__ == "__main__":
    unittest.main()
