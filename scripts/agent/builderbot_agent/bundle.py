"""The agent as a node gets it: one zip, the entry as its __main__.py and this
package beside it. Python runs a zip whose __main__.py is at its root as it
runs a script, whatever the file is called, so a node keeps one file at one
path, and its unit (python3 FILE run), its self-update (the body written over
that file) and the provisioner's download are what they were when the agent
was one file: an agent from before the split updates across it.

The bytes are the same for the same sources, so the digest a node compares
is a digest of the sources: members sorted, a fixed timestamp, stored rather
than compressed (a zlib on the controller and one on a node need not agree).
Stdlib only and no relative import: the controller loads this file by path.
"""
import io
import os
import zipfile

ENTRY = "builderbot-agent.py"
PACKAGE = "builderbot_agent"


def sources(src_dir):
    """(name in the zip, path on disk), in the zip's order."""
    out = [("__main__.py", os.path.join(src_dir, ENTRY))]
    pkg = os.path.join(src_dir, PACKAGE)
    for name in sorted(os.listdir(pkg)):
        if name.endswith(".py"):
            out.append((f"{PACKAGE}/{name}", os.path.join(pkg, name)))
    return out


# A shebang before the zip, as zipapp writes one: Python finds a zip by its
# end, so the line costs nothing, and the file runs as a program again. The
# provisioner runs it as "$AGENT enroll" and the unit as "$AGENT run", both
# written when the agent was one script, and a zip with no first line made
# both "Exec format error": a new node could not enroll (the operator,
# 11 Oct), and a node that took the zip would not have started after a
# reboot, the agent's own restarts going through sys.executable.
SHEBANG = b"#!/usr/bin/env python3\n"


def build(src_dir):
    """The zip's bytes, from the entry and the package in src_dir."""
    buf = io.BytesIO()
    buf.write(SHEBANG)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for arc, path in sources(src_dir):
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            with open(path, "rb") as f:
                z.writestr(info, f.read())
    return buf.getvalue()


def newest(src_dir):
    """The newest mtime among the sources: when a cached build is stale."""
    return max(os.stat(p).st_mtime for _, p in sources(src_dir))
