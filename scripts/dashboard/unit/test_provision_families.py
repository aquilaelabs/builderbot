"""The provisioner's family files (R204): each declares the family, the
os-release IDs it is for, the tools it needs and the four functions the
core calls; and the core, sourcing the one beside it, takes a machine whose
ID the file names and refuses another by name."""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FAMILIES = os.path.join(ROOT, "nodes", "families")
CORE = os.path.join(ROOT, "nodes", "provision-linux.sh")


def family_block():
    """The core's lines from the family file's loading to the init check."""
    src = open(CORE, encoding="utf-8").read()
    a = src.index("# The family's own file:")
    b = src.index('INIT=""\n', a)
    return src[a:b]


def run_core(family, os_release):
    """The family block, with the machine's os-release values preset and the
    family file beside it: (FAMILY, FAMILY_WHY) as the core would hold them."""
    d = tempfile.mkdtemp()
    if family:
        with open(os.path.join(d, "provision-family.sh"), "w", encoding="utf-8") as f:
            f.write(open(os.path.join(FAMILIES, family + ".sh"), encoding="utf-8").read())
    script = os.path.join(d, "provision-linux.sh")
    pre = "".join(f'{k}="{v}"\n' for k, v in os_release.items())
    with open(script, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\nset -u\nFAMILY=\"${FAMILY:-}\"; FAMILY_WHY=\"\"\n" + pre + family_block()
                + 'printf "%s\\n%s\\n" "$FAMILY" "$FAMILY_WHY"\n')
    r = subprocess.run(["bash", script], capture_output=True, text=True, timeout=30, check=False)
    fam, why = (r.stdout.split("\n") + ["", ""])[:2]
    return fam, why, r.stderr


class FamilyFiles(unittest.TestCase):
    def test_each_declares_itself_and_its_functions(self):
        names = sorted(f[:-3] for f in os.listdir(FAMILIES) if f.endswith(".sh"))
        self.assertEqual(names, ["alpine", "arch", "deb", "gentoo", "rhel", "suse", "void"])
        for fam in names:
            r = subprocess.run(["bash", "-c", f'. "{FAMILIES}/{fam}.sh"; echo "$FAMILY_PICKED|$FAMILY_IDS|$FAMILY_NEED|$FAMILY_NAME"; '
                                              'declare -F pkg_refresh pkg pkg_names docker_install >/dev/null && echo fns; pkg_names base; pkg_names docker'],
                               capture_output=True, text=True, timeout=30, check=False)
            lines = r.stdout.strip().split("\n")
            picked, ids, need, name = lines[0].split("|")
            self.assertEqual(picked, fam)
            self.assertTrue(ids and need and name, fam)
            self.assertEqual(lines[1], "fns", fam)
            self.assertTrue(lines[2].strip() and lines[3].strip(), f"{fam}: base and docker packages are named")


class CoreLoadsOne(unittest.TestCase):
    def test_a_machine_the_file_names_is_its_family(self):
        fam, why, err = run_core("rhel", {"ID": "rocky", "ID_LIKE": "rhel centos fedora", "PRETTY_NAME": "Rocky Linux 9.8 (Blue Onyx)"})
        self.assertEqual((fam, why), ("rhel", ""), err)

    def test_a_derivative_the_table_never_met_is_taken_on_its_id_like(self):
        fam, why, err = run_core("deb", {"ID": "neon", "ID_LIKE": "ubuntu debian", "PRETTY_NAME": "KDE neon"})
        self.assertEqual((fam, why), ("deb", ""), err)

    def test_another_machine_is_refused_by_name(self):
        fam, why, err = run_core("deb", {"ID": "rocky", "ID_LIKE": "rhel centos fedora", "PRETTY_NAME": "Rocky Linux 9.8 (Blue Onyx)", "FAMILY": "rhel"})
        self.assertEqual(fam, "", err)
        self.assertIn("built for Debian and Ubuntu", why)
        self.assertIn("Rocky Linux 9.8", why)
        self.assertIn("Enroll node", why)

    def test_no_family_file_beside_the_core_is_said(self):
        fam, why, err = run_core(None, {"ID": "ubuntu", "ID_LIKE": "debian", "PRETTY_NAME": "Ubuntu 26.04 LTS", "FAMILY": "deb"})
        self.assertEqual(fam, "", err)
        self.assertIn("no family file", why)


if __name__ == "__main__":
    unittest.main()
