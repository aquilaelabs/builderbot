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
    {"id": "debian", "name": "Debian 12 or later", "family": "deb", "ids": ["debian", "raspbian"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; VM host installed and removed; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (Debian 13)"},
    {"id": "almalinux", "name": "AlmaLinux 9", "family": "rhel", "ids": ["almalinux"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; VM host installed and removed; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (AlmaLinux 9.8)"},
    {"id": "rhel", "name": "Red Hat Enterprise Linux 9", "family": "rhel", "ids": ["rhel"], "vetted": "",
     "why": "not walked: its image needs a Red Hat subscription. Rocky Linux and AlmaLinux are its rebuilds, and both are"},
    {"id": "centos", "name": "CentOS Stream 9", "family": "rhel", "ids": ["centos"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; VM host installed and removed; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (CentOS Stream 9)"},
    {"id": "fedora", "name": "Fedora", "family": "rhel", "ids": ["fedora"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; VM host installed and removed; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (Fedora 44)"},
    {"id": "arch", "name": "Arch Linux", "family": "arch", "ids": ["arch", "archlinux", "manjaro"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; VM host installed and removed; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (Arch, kernel 7.2)"},
    {"id": "opensuse", "name": "openSUSE Leap or Tumbleweed", "family": "suse",
     "ids": ["opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"],
     "vetted": "2026-10-21, R97 on the dev pair: a VM made a node from its cloud image, enrolled; a toolchain installed and removed; nginx run as a container from a compose file; a project synced and a terminal opened through the controller; Uninstall, the machine's own account kept (Leap 16.0; VM host wants its full kernel, kernel-default, as its cloud image boots kernel-default-base)"},
    {"id": "alpine", "name": "Alpine Linux", "family": "alpine", "ids": ["alpine"], "vetted": ""},
    {"id": "void", "name": "Void Linux", "family": "void", "ids": ["void"], "vetted": "",
     "why": "not walked: Void publishes no cloud image for a VM to be made from, so it is walked only on a machine of its own"},
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
    return [{"id": s["id"], "name": s["name"], "family": s["family"], "vetted": bool(s["vetted"]),
             **({"why": s["why"]} if s.get("why") and not s["vetted"] else {})}
            for s in SYSTEMS if allowed(s["id"])]


def family_file(sid):
    """The provisioner family file the built script carries for this system."""
    s = get(sid)
    return FAMILIES_DIR / f"{s['family']}.sh" if s else None
