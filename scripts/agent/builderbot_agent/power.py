"""The machine's power and its own packages (R164 step 3): a UPS through
NUT, read for the census (on line, on battery, low battery; charge, the
minutes left, the load) so the bell says when the machine runs on battery,
with upsmon's clean shutdown the feature's own; and the host's own package
updates on a bare-metal install (apt), counted once an hour for the census
and applied by the host-update job, which says when a restart is needed
and restarts only when the job says to. BuilderBot OS keeps apt diverted:
its updates are whole images (osimage.py), and nothing here runs there.
"""
import os
import re
import shutil
import subprocess
import time

from .osimage import os_release
from .stores import save_state

UPS_NAME = "ups"
CHECK_EVERY_S = 3600
REBOOT_FLAG = "/var/run/reboot-required"
STATUS_WORDS = {"OL": "on line", "OB": "on battery", "LB": "low battery", "CHRG": "charging", "DISCHRG": "discharging",
                "FSD": "shutting down", "OFF": "off", "BYPASS": "on bypass", "RB": "replace battery"}


def _out(argv, timeout=20, env=None):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env)
        return p.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def ups_now():
    """{model, status, words, charge, runtime_s, load, answers} from upsc,
    {} without NUT; `answers` false where NUT is here but the UPS does not
    answer (cable out, driver down), which is its own row on the bell."""
    upsc = shutil.which("upsc")
    if not upsc:
        return {}
    out = {"model": "", "status": "", "words": "", "charge": None, "runtime_s": None, "load": None, "answers": False}
    for line in _out([upsc, f"{UPS_NAME}@localhost"]).splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "device.model" or (k == "ups.model" and not out["model"]):
            out["model"] = v[:64]
        elif k == "ups.status":
            out["status"] = v[:32]
            out["words"] = ", ".join(STATUS_WORDS.get(w, w.lower()) for w in v.split()[:4])
            out["answers"] = True
        elif k in ("battery.charge", "battery.runtime", "ups.load"):
            try:
                n = int(float(v))
            except ValueError:
                continue
            out[{"battery.charge": "charge", "battery.runtime": "runtime_s", "ups.load": "load"}[k]] = n
    return out


def host_updates_now(state):
    """{pending, security, reboot, checked} for a bare-metal install on a
    Debian-family system, counted once an hour as root (apt-get update,
    then a simulated upgrade), kept in node.json between; {} on BuilderBot
    OS, without apt, or as anybody but root. `reboot` is the flag a kernel
    or libc update leaves."""
    apt = shutil.which("apt-get")
    if not apt or os.geteuid() != 0 or os_release():
        return {}
    was = state.get("host_updates") if isinstance(state.get("host_updates"), dict) else {}
    if was and time.time() - int(was.get("checked") or 0) < CHECK_EVERY_S:
        return {**was, "reboot": os.path.exists(REBOOT_FLAG)}
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C")
    _out([apt, "-qq", "update"], timeout=300, env=env)
    sim = _out([apt, "-s", "-o", "Debug::NoLocking=true", "upgrade"], timeout=120, env=env)
    pending = security = 0
    m = re.search(r"(\d+) upgraded, (\d+) newly installed", sim)
    if m:
        pending = int(m.group(1)) + int(m.group(2))
    security = sum(1 for ln in sim.splitlines() if ln.startswith("Inst ") and re.search(r"[Ss]ecurity", ln))
    now = {"pending": pending, "security": security, "checked": int(time.time())}
    state["host_updates"] = now
    save_state(state)
    return {**now, "reboot": os.path.exists(REBOOT_FLAG)}


class PowerMixin:
    """Agent's host-update job: one of the parts class Agent (agent.py) is made of."""

    def _apply_host_update(self, job, cfg):
        say = job.say
        apt = shutil.which("apt-get")
        if os.geteuid() != 0 or not apt:
            say("refused: the system's packages are root's to update with apt, and this agent is not root or has no apt\n")
            return "failed", 77
        if os_release():
            say("refused: BuilderBot OS updates as a whole image (Controller settings, Updates), never package by package\n")
            return "failed", 64
        quiet = ["env", "DEBIAN_FRONTEND=noninteractive", "LC_ALL=C", apt]
        say("apt-get update\n")
        if self._sh(job, quiet + ["-q", "update"], timeout=600) != 0:
            return "failed", 1
        say("apt-get upgrade: every package to its newest, the configuration files kept as they are\n")
        rc = self._sh(job, quiet + ["-y", "-q", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold", "upgrade"], timeout=7200)
        if rc != 0:
            return "failed", rc
        self._sh(job, quiet + ["-y", "-q", "autoremove"], timeout=600)
        self.state.pop("host_updates", None)
        save_state(self.state)
        reboot = os.path.exists(REBOOT_FLAG)
        if reboot and cfg.get("reboot") is True:
            say("a restart is needed and was asked for: the machine restarts in a minute\n")
            self.hello_again("the system's packages updated; restarting")
            self._sh(job, ["shutdown", "-r", "+1", "BuilderBot: restarting after the system's updates"], timeout=30)
        elif reboot:
            say("done; a restart is needed to run the new kernel or libraries: This machine's Reboot does it\n")
            self.hello_again("the system's packages updated; a restart is needed")
        else:
            say("done; nothing needs a restart\n")
            self.hello_again("the system's packages updated")
        return "succeeded", 0
