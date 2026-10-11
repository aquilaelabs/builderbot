"""bb-sandbox uninstall's flags and its summary (the operator, 11 Oct): the
three rings (--stores, --configured, --doors) parse, the summary says which
are going and which stay, an unknown flag is refused by name, and nothing
is touched until "uninstall" is typed. Run as the bash it is, extracted
from the provisioner the way test_sandbox_gpu does, with id standing in
for root; the summary and the question come before any write, so a "no"
at the prompt proves the parse without a machine to take apart."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROVISIONER = os.path.join(HERE, "..", "..", "..", "nodes", "provision-linux.sh")
REAL = ("bash", "sh", "cat", "grep", "awk", "sed", "sort", "tail", "head", "tr", "cut", "rm",
        "printf", "env", "mktemp", "dirname", "basename", "python3", "readlink", "uname", "date")


class Uninstall(unittest.TestCase):
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
        with open(os.path.join(self.bin, "id"), "w") as h:
            h.write("#!/bin/sh\necho 0\n")
        os.chmod(os.path.join(self.bin, "id"), 0o755)

    def run_it(self, *args, answer="no\n"):
        return subprocess.run([shutil.which("bash"), self.helper, "uninstall", *args], input=answer,
                              capture_output=True, text=True, timeout=60, check=False,
                              env={"PATH": self.bin, "HOME": self.dir})

    def test_unknown_flag_is_refused_by_name(self):
        r = self.run_it("--everything")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uninstall takes --yes, --stores, --configured and --doors", r.stderr)
        self.assertNotIn("goes:", r.stdout)

    def test_rings_say_what_goes_and_nothing_moves_on_no(self):
        r = self.run_it("--stores", "--doors")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("left as it was", r.stderr)
        self.assertIn("the session firewall rules and the sessions' own networks", r.stdout)
        self.assertIn("also:  the stores on this disk", r.stdout)
        self.assertIn("also:  cloudflared and its token, Tailscale's login, the port 22 rule, the nginx container", r.stdout)
        self.assertNotIn("also:  the mounts BuilderBot used", r.stdout)
        self.assertIn("Un-enroll deregisters it first", r.stdout)
        self.assertNotIn(", the stores", r.stdout)

    def test_without_the_rings_the_stores_and_mounts_stay(self):
        r = self.run_it()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("also:", r.stdout)
        self.assertIn("everything on the shares (other nodes may use them), the stores", r.stdout)
        self.assertIn("Type uninstall to go on", r.stdout)


class Heredocs(unittest.TestCase):
    """A backtick in an unquoted heredoc is a command, not markup: the
    provisioner's closing words held `sudo bb-sandbox`, and every run ended
    by opening the menu on whatever terminal it had (B636, 11 Oct)."""
    def test_no_backtick_runs_from_text(self):
        with open(os.environ.get("BB_TEST_PROVISIONER") or PROVISIONER, encoding="utf-8") as f:
            lines = f.read().split("\n")
        inside, found = None, []
        for i, line in enumerate(lines, 1):
            if inside:
                if line.strip() == inside:
                    inside = None
                elif "`" in line:
                    found.append(f"{i}: {line}")
                continue
            m = re.search(r"<<-?\s*([A-Za-z_]+)\s*$", line)
            if m and "'" not in line.split("<<", 1)[1]:
                inside = m.group(1)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
