"""The systems a node can be: what Enroll node's pulldown offers, and which
provisioner family file the built script carries for each (R204).

An entry is a distribution as a person knows their machine (what
os-release's PRETTY_NAME says); its family is the provisioner file under
nodes/families/, shared by the distributions that take the same packages,
package verbs and docker repository. Vetting is per entry, like the git
hosts' and hypervisors' (forges.py, vmtemplate.py): a walk on Rocky vets
Rocky and not AlmaLinux until Alma is walked. An entry without a vetted
line is offered only behind Offer dev features, tagged dev.
"""
from pathlib import Path

import forges

FAMILIES_DIR = Path(__file__).resolve().parent.parent.parent / "nodes" / "families"

SYSTEMS = [
    {"id": "ubuntu", "name": "Ubuntu 24.04 or later", "family": "deb", "ids": ["ubuntu"],
     "vetted": "bb-sandbox and the dev pair's bb-dev-sandbox (Ubuntu 24.04 and 26.04), in daily use"},
    {"id": "rocky", "name": "Rocky Linux 9", "family": "rhel", "ids": ["rocky"],
     "vetted": "2026-10-13: bb-dev-sandbox-rh (Rocky 9.8) on the dev pair: enroll, toolchains, storage, "
               "a synced project, a container, nginx, a Gitea runner, a shell and a Claude session"},
    {"id": "debian", "name": "Debian 12 or later", "family": "deb", "ids": ["debian", "raspbian"], "vetted": ""},
    {"id": "almalinux", "name": "AlmaLinux 9", "family": "rhel", "ids": ["almalinux"], "vetted": ""},
    {"id": "rhel", "name": "Red Hat Enterprise Linux 9", "family": "rhel", "ids": ["rhel"], "vetted": ""},
    {"id": "centos", "name": "CentOS Stream 9", "family": "rhel", "ids": ["centos"], "vetted": ""},
    {"id": "fedora", "name": "Fedora", "family": "rhel", "ids": ["fedora"], "vetted": ""},
    {"id": "arch", "name": "Arch Linux", "family": "arch", "ids": ["arch", "archlinux", "manjaro"], "vetted": ""},
    {"id": "opensuse", "name": "openSUSE Leap or Tumbleweed", "family": "suse",
     "ids": ["opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"], "vetted": ""},
    {"id": "alpine", "name": "Alpine Linux", "family": "alpine", "ids": ["alpine"], "vetted": ""},
    {"id": "void", "name": "Void Linux", "family": "void", "ids": ["void"], "vetted": ""},
    {"id": "gentoo", "name": "Gentoo", "family": "gentoo", "ids": ["gentoo"], "vetted": ""},
]
DEFAULT = "ubuntu"


def get(sid):
    """The entry with this id, or None."""
    return next((s for s in SYSTEMS if s["id"] == sid), None)


def allowed(sid):
    """Whether this system may be picked here: vetted, or dev features on."""
    s = get(sid)
    return bool(s) and (bool(s["vetted"]) or bool(forges.unvetted_ok and forges.unvetted_ok()))


def offered():
    """The pulldown's entries: every vetted one, and the rest when Offer dev
    features is on, each saying whether it is vetted."""
    return [{"id": s["id"], "name": s["name"], "family": s["family"], "vetted": bool(s["vetted"])}
            for s in SYSTEMS if allowed(s["id"])]


def family_file(sid):
    """The provisioner family file the built script carries for this system."""
    s = get(sid)
    return FAMILIES_DIR / f"{s['family']}.sh" if s else None
