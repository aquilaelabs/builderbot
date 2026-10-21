"""Every helper the provisioner calls is defined (B166): R204's split into a
core and family files took svc_enable, svc_install, svc_active, svc_stop,
svc_restart and is_vm out of the core and put them nowhere, and nothing
noticed for eight days, since bash only says so when the line runs. A name
with an underscore, called where a command goes, must be a function of the
core's or of a family file's."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
NODES = os.path.join(HERE, "..", "..", "..", "nodes")
CALL = re.compile(r"(?:^|[;&|]\s*|\b(?:if|then|else|do|!)\s+)([a-z]+_[a-z0-9_]+)\b(?!=)")


class Defined(unittest.TestCase):
    def test_every_helper_called_is_defined(self):
        core = open(os.path.join(NODES, "provision-linux.sh"), encoding="utf-8").read()
        fams = [open(os.path.join(NODES, "families", f), encoding="utf-8").read()
                for f in sorted(os.listdir(os.path.join(NODES, "families"))) if f.endswith(".sh")]
        defined = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", "\n".join([core, *fams]), re.M))
        self.assertTrue({"svc_enable", "svc_install", "svc_active", "is_vm"} <= defined)
        called = {}
        inside = ""                 # a heredoc being read past: text, a unit, python
        for n, line in enumerate(core.splitlines(), 1):
            if inside:
                inside = "" if line.strip() == inside else inside
                continue
            m = re.search(r"<<-?\s*['\"]?([A-Z][A-Z0-9_]*)['\"]?", line)
            if m and m.group(1) != "BBSANDBOX":      # bb-sandbox's own body is code, and checked
                inside = m.group(1)
            if line.lstrip().startswith("#"):
                continue
            for m in CALL.finditer(line.strip()):
                called.setdefault(m.group(1), n)
        missing = {k: v for k, v in called.items() if k not in defined}
        self.assertEqual(missing, {}, "called by the provisioner and defined nowhere (name: first line)")


if __name__ == "__main__":
    unittest.main()
