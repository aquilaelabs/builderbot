"""The node agent's GPU name in its census (B391): only an nvidia-smi that
answered is a name. Drives _gpu_name against a stand-in nvidia-smi on PATH."""
import importlib.util
import os
import shutil
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "builderbot_agent", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class StandIn(unittest.TestCase):
    """An nvidia-smi of the test's own, first on PATH."""

    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self.path

    def tearDown(self):
        os.environ["PATH"] = self.path

    def stand_in(self, body):
        f = os.path.join(self.bin, "nvidia-smi")
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + body + "\n")
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)


class GpuName(StandIn):
    def test_a_driver_that_answers_names_the_card(self):
        self.stand_in('echo "NVIDIA GeForce RTX 3070 Ti"')
        self.assertEqual(agent._gpu_name(), "NVIDIA GeForce RTX 3070 Ti")

    def test_a_driver_that_does_not_answer_is_no_name(self):
        self.stand_in('echo "NVIDIA-SMI has failed because it couldn\'t communicate with the NVIDIA driver."; exit 9')
        self.assertEqual(agent._gpu_name(), "")

    def test_no_nvidia_smi_is_no_name(self):
        os.environ["PATH"] = self.bin
        self.assertEqual(agent._gpu_name(), "")


class GpuSample(StandIn):
    """The card's gauges on every heartbeat: load and memory, two cards as
    one, nothing at all when no driver answers."""

    def test_one_card(self):
        self.stand_in('echo "37, 2048, 8192"')
        self.assertEqual(agent._gpu_sample(), {"gpu_pct": 37.0, "gpu_mem_used_mb": 2048, "gpu_mem_mb": 8192})

    def test_two_cards_are_one_gauge(self):
        self.stand_in('printf "10, 1000, 8000\\n30, 3000, 8000\\n"')
        self.assertEqual(agent._gpu_sample(), {"gpu_pct": 20.0, "gpu_mem_used_mb": 4000, "gpu_mem_mb": 16000})

    def test_no_driver_is_nothing(self):
        self.stand_in('echo "NVIDIA-SMI has failed"; exit 9')
        self.assertEqual(agent._gpu_sample(), {})
        os.environ["PATH"] = self.bin + "/none"
        self.assertEqual(agent._gpu_sample(), {})

    def test_a_card_without_a_reading_is_skipped(self):
        self.stand_in('echo "[N/A], [N/A], [N/A]"')
        self.assertEqual(agent._gpu_sample(), {})


class GpuDriver(unittest.TestCase):
    """Where the driver stands, read from sysfs and modinfo (R102): the row
    has to tell not installed, installed and waiting for a reboot, running,
    and removed but still loaded apart, before nvidia-smi can answer."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        # No apt on PATH: what apt says is GpuDriverApt's, and the real
        # ubuntu-drivers takes seconds.
        self.path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin
        self.addCleanup(os.environ.__setitem__, "PATH", self.path)

    def card(self, bound="nouveau", vendor="0x10de", cls="0x030000"):
        d = os.path.join(self.root, "bus", "pci", "devices", "0000:04:00.0")
        os.makedirs(d, exist_ok=True)
        for name, text in (("vendor", vendor), ("class", cls), ("device", "0x2482")):
            with open(os.path.join(d, name), "w") as f:
                f.write(text + "\n")
        if bound:
            drv = os.path.join(self.root, "bus", "pci", "drivers", bound)
            os.makedirs(drv, exist_ok=True)
            os.symlink(drv, os.path.join(d, "driver"))

    def loaded(self, version):
        d = os.path.join(self.root, "module", "nvidia")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "version"), "w") as f:
            f.write(version + "\n")

    def modinfo(self, version=""):
        f = os.path.join(self.bin, "modinfo")
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + (f'echo "{version}"\n' if version
                                      else 'echo "modinfo: ERROR: Module nvidia not found." >&2; exit 1\n'))
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)
        return f

    def read(self, mod=""):
        got = agent._gpu_driver(sys_root=self.root, modinfo=self.modinfo(mod))
        return {k: got[k] for k in ("installed", "loaded", "bound")} if got else got

    def test_no_nvidia_card_is_nothing(self):
        self.card(vendor="0x1234")
        self.assertEqual(self.read(), {})

    def test_nouveau_with_no_driver_installed(self):
        self.card("nouveau")
        self.assertEqual(self.read(), {"installed": "", "loaded": "", "bound": "nouveau"})

    def test_installed_and_waiting_for_a_reboot(self):
        self.card("nouveau")
        self.assertEqual(self.read("580.95.05"), {"installed": "580.95.05", "loaded": "", "bound": "nouveau"})

    def test_running_the_card(self):
        self.card("nvidia")
        self.loaded("580.95.05")
        self.assertEqual(self.read("580.95.05"), {"installed": "580.95.05", "loaded": "580.95.05", "bound": "nvidia"})

    def test_removed_but_still_loaded(self):
        self.card("nvidia")
        self.loaded("580.95.05")
        self.assertEqual(self.read(), {"installed": "", "loaded": "580.95.05", "bound": "nvidia"})

    def test_an_update_built_for_the_newest_kernel_alone_is_installed_not_removed(self):
        # bb-sandbox, 8 Oct: apt took 595.91.07's module off the running
        # kernel and put 595.99.02's on the newest one only.
        self.card("nvidia")
        self.loaded("595.91.07")
        mods = os.path.join(self.root, "lib-modules")
        for k in ("7.0.0-30-generic", "7.0.0-34-generic", "7.0.0-38-generic", "kernel"):
            os.makedirs(os.path.join(mods, k))
        f = os.path.join(self.bin, "modinfo")
        with open(f, "w") as h:
            h.write('#!/bin/sh\n[ "$1" = -k ] && [ "$2" = 7.0.0-38-generic ] && { echo 595.99.02; exit 0; }\nexit 1\n')
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)
        got = agent._gpu_driver(sys_root=self.root, modinfo=f, modules_root=mods, running="7.0.0-34-generic")
        self.assertEqual((got["installed"], got["loaded"]), ("595.99.02", "595.91.07"))
        # ...and an older kernel's module is not the one a restart boots.
        got = agent._gpu_driver(sys_root=self.root, modinfo=f, modules_root=mods, running="7.0.0-40-generic")
        self.assertEqual(got["installed"], "")

    def test_a_card_with_no_driver_bound(self):
        self.card(bound="")
        self.assertEqual(self.read()["bound"], "")


class GpuDriverApt(unittest.TestCase):
    """What apt says about the driver (R102): the branches on offer for the
    row's pulldown, the package installed, what it would update to, and the
    one recommended for the card. Stand-ins for apt-cache, dpkg-query and
    ubuntu-drivers on PATH."""

    SEARCH = ("nvidia-driver-590 - NVIDIA driver metapackage (transitional package)\n"
              "nvidia-driver-595 - NVIDIA driver metapackage\n"
              "nvidia-driver-595-open - NVIDIA driver (open kernel) metapackage\n"
              "nvidia-driver-610 - NVIDIA driver metapackage\n"
              "nvidia-driver-580-server - NVIDIA Server Driver metapackage\n")
    POLICY = ("nvidia-driver-595:\n  Installed: 595.91.07-0ubuntu1\n  Candidate: 595.95.01-0ubuntu1\n"
              "nvidia-driver-595-open:\n  Installed: (none)\n  Candidate: 595.95.01-0ubuntu1\n"
              "nvidia-driver-610:\n  Installed: (none)\n  Candidate: 610.57.04-0ubuntu0.26.04.3\n")

    def setUp(self):
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin
        self.addCleanup(os.environ.__setitem__, "PATH", self.path)

    def tool(self, name, body):
        f = os.path.join(self.bin, name)
        with open(f, "w") as h:
            h.write("#!/bin/sh\n" + body + "\n")
        os.chmod(f, os.stat(f).st_mode | stat.S_IEXEC)

    def tools(self, installed=True, recommends=True):
        self.tool("apt-cache", f'case "$1" in search) printf \'{self.SEARCH}\' ;; policy) printf \'{self.POLICY}\' ;; esac')
        self.tool("dpkg-query", "printf 'nvidia-driver-595 595.91.07-0ubuntu1 ii \\n'" if installed else "exit 1")
        if recommends:
            self.tool("ubuntu-drivers", "printf 'vendor   : NVIDIA Corporation\\ndriver   : nvidia-driver-595 - distro non-free recommended\\n"
                                        "driver   : nvidia-driver-610 - distro non-free\\n'")

    def test_no_apt_is_nothing(self):
        self.assertEqual(agent._gpu_driver_apt(), {})

    def test_the_branches_on_offer_newest_first_without_transitional_or_server_ones(self):
        self.tools()
        got = agent._gpu_driver_apt()
        self.assertEqual([o["pkg"] for o in got["options"]],
                         ["nvidia-driver-610", "nvidia-driver-595", "nvidia-driver-595-open"])
        self.assertEqual(got["options"][0]["version"], "610.57.04")
        self.assertEqual([o["open"] for o in got["options"]], [False, False, True])

    def test_the_installed_package_and_what_it_would_update_to(self):
        self.tools()
        got = agent._gpu_driver_apt()
        self.assertEqual((got["package"], got["pkg_version"], got["candidate"]),
                         ("nvidia-driver-595", "595.91.07-0ubuntu1", "595.95.01-0ubuntu1"))
        self.assertEqual(got["recommended"], "nvidia-driver-595")

    def test_nothing_installed_and_no_recommendation(self):
        self.tools(installed=False, recommends=False)
        got = agent._gpu_driver_apt()
        self.assertEqual((got["package"], got["candidate"], got["recommended"]), ("", "", ""))
        self.assertEqual(len(got["options"]), 3)

    def test_a_package_name_apt_may_be_asked_for(self):
        for ok in ("nvidia-driver", "nvidia-driver-610", "nvidia-driver-595-open"):
            self.assertTrue(agent.DRIVER_PKG.fullmatch(ok), ok)
        for bad in ("nvidia-driver-610; rm -rf /", "nvidia-driver-61", "firefox", "nvidia-driver-610-server", ""):
            self.assertFalse(agent.DRIVER_PKG.fullmatch(bad), bad)


if __name__ == "__main__":
    unittest.main()
