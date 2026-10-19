#!/usr/bin/env python3
"""Build the companion app (R270) as one file that runs on any machine with
Python 3.9 or newer: dist/builderbot-companion-VERSION.pyz, the app's package
and the four node-agent modules its sync is (the package's version, its base,
the connection and the sync), nothing else of the agent's. The signed .exe
for Windows is a CI job's (PyInstaller over the same entry point).

    tools/companion-build.py --version X.Y.Z [--out FILE]
"""
import argparse
import os
import zipapp
import shutil
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(REPO, "scripts", "agent", "builderbot_agent")
APP = os.path.join(REPO, "windows", "bbcompanion")
AGENT_MODULES = ("__init__.py", "base.py", "controller.py", "wssync.py")


def build(version, out):
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(APP, os.path.join(tmp, "bbcompanion"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(tmp, "builderbot_agent"))
        for m in AGENT_MODULES:
            shutil.copy2(os.path.join(AGENT, m), os.path.join(tmp, "builderbot_agent", m))
        with open(os.path.join(tmp, "bbcompanion", "VERSION"), "w") as f:
            f.write(version + "\n")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        zipapp.create_archive(tmp, out, interpreter="/usr/bin/env python3", main="bbcompanion.__main__:entry")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = a.out or os.path.join(REPO, "dist", f"builderbot-companion-{a.version}.pyz")
    print(build(a.version, out))


if __name__ == "__main__":
    main()
