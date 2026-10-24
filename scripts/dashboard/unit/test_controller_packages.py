"""The controller's one package list (R90 step 2): config/controller-packages.tsv,
read by the Dockerfile and by a bare-metal install through the same reader,
so the image and the installer cannot drift. Every family the provisioner
has is a column; what the controller cannot run without names a package
in each; the image's column is the list the image always installed."""
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LIST = os.path.join(ROOT, "config", "controller-packages.tsv")
READER = os.path.join(ROOT, "scripts", "lib", "controller-packages.sh")
NEEDS = {"core", "tools", "image", "vendor", "docker", "host"}


def rows():
    head, out = None, []
    for line in open(LIST, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        cells = line.split("\t")
        if head is None:
            head = cells
            continue
        out.append(dict(zip(head, cells, strict=False)) | {"_n": len(cells)})
    return head, out


def read(family, *needs, env=None):
    return subprocess.run(["bash", READER, family, *needs], capture_output=True, text=True,
                          timeout=30, check=False, env=env)


class TheList(unittest.TestCase):
    def test_a_column_for_every_family_the_provisioner_has(self):
        head, _ = rows()
        fams = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "nodes", "families")) if f.endswith(".sh"))
        self.assertEqual(head[:2], ["what", "need"])
        self.assertEqual(sorted(head[2:]), fams)

    def test_every_row_is_whole(self):
        head, rs = rows()
        self.assertGreater(len(rs), 50)
        for r in rs:
            self.assertEqual(r["_n"], len(head), r["what"])
            self.assertIn(r["need"], NEEDS, r["what"])
            for fam in head[2:]:
                self.assertTrue(r[fam].strip(), f"{r['what']}: {fam} is blank; - says none")

    def test_the_image_column_is_plain_packages(self):
        # The image installs the deb cells as they are: no alternatives, no
        # docker_install marker, nothing left to a machine's repositories.
        _, rs = rows()
        for r in rs:
            self.assertNotIn("|", r["deb"], r["what"])
            self.assertFalse(r["deb"].startswith("@"), r["what"])
            self.assertNotEqual(r["deb"], "-", r["what"])

    def test_what_the_controller_needs_is_named_everywhere(self):
        head, rs = rows()
        for r in rs:
            if r["need"] != "core":
                continue
            for fam in head[2:]:
                self.assertNotEqual(r[fam], "-", f"{r['what']} is core and {fam} names nothing for it")


class TheReader(unittest.TestCase):
    def test_one_entry_per_line_for_the_needs_asked(self):
        _, rs = rows()
        r = read("deb", "core", "tools", "image")
        self.assertEqual(r.returncode, 0, r.stderr)
        want = [x for row in rs if row["need"] in ("core", "tools", "image") for x in row["deb"].split()]
        self.assertEqual(r.stdout.split("\n")[:-1], want)

    def test_none_is_left_out_and_alternatives_kept_whole(self):
        r = read("suse", "vendor", "docker")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = r.stdout.split()
        self.assertIn("nodejs24|nodejs22|nodejs20|nodejs", got)
        self.assertIn("@docker", got)
        self.assertNotIn("-", read("gentoo", "tools").stdout.split())

    def test_an_unknown_family_is_refused(self):
        r = read("nope", "core")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no column for family nope", r.stderr)

    def test_another_list_for_a_test(self):
        d = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"ctlpkgs-{os.getpid()}.tsv")
        with open(d, "w", encoding="utf-8") as f:
            f.write("# a comment\nwhat\tneed\tdeb\nx\tcore\tpkg-x\ny\ttools\t-\n")
        try:
            r = read("deb", "core", "tools", env=dict(os.environ, LIST=d))
            self.assertEqual(r.stdout, "pkg-x\n", r.stderr)
        finally:
            os.unlink(d)


class TheImage(unittest.TestCase):
    def test_the_dockerfile_reads_the_list_and_names_no_package_itself(self):
        text = open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()
        self.assertIn("controller-packages.sh deb core tools image", text)
        self.assertIn("controller-packages.sh deb vendor docker", text)
        self.assertIn("COPY config/controller-packages.tsv", text)
        # The packages that used to be spelled out in the two install layers.
        for name in ("ripgrep fd-find fzf", "docker-ce-cli docker-compose-plugin", "libicu74 libssl3"):
            self.assertNotIn(name, text)


if __name__ == "__main__":
    unittest.main()
