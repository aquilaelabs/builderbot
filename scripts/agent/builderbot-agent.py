#!/usr/bin/env python3
"""BuilderBot's node agent: one file, standard library only, dialing OUT.

A node runs this under systemd. It enrolls once with a token the operator
minted on the Nodes tab, then loops for the life of the machine: say hello,
ask for work, run what it is given, report what happened. The controller
never connects to a node — a node needs no open port, no inbound rule and no
key the controller could lose — and the credential it holds opens nothing
but its own row (docs/nodes.md §4, §8).

The protocol is six verbs over plain HTTP, and this file speaks four of them
plus the download that fetches itself:

    POST /api/v1/agent/enroll     once: the enroll token in, the node token out
    POST /api/v1/agent/hello      on connect and every ten minutes: the census,
                                  and the ids of the jobs still running here
    POST /api/v1/agent/work       the long-poll: a heartbeat sample in, a job
                                  (or 204, or {"cancel": [ids]}) out, held up
                                  to `poll` seconds
    POST /api/v1/agent/log        chunks of a running job's output, by sequence;
                                  the reply carries `cancel: true` once the
                                  operator has stopped that job
    POST /api/v1/agent/result     the terminal state (succeeded, failed,
                                  canceled), exit code and a one-line error
    GET  /api/v1/agent/download   the agent the controller ships — self-update

Three rules this file keeps that are worth knowing before changing it:

  * The agent is the DURABLE side of a job (door 5). A controller restart
    must never kill running work: log chunks that could not be posted are
    kept and re-sent by sequence number, the result is retried until it is
    acknowledged, and a job started before the controller went away finishes
    and reports late.
  * The node enforces its own capabilities (door 7). A job that requires a
    capability this node was not enrolled with is refused HERE, whatever the
    controller's row says — the row is a claim, the enrollment is the fact.
  * Jobs never run as root. The unit runs the agent as root so that phase 5's
    system jobs (mounts, network) can, but an exec job drops to the account
    the provisioner enrolled — the same `bb` that docker runs as — before it
    runs anything. A session that reaches this box through a job has the
    reach it already had over ssh, and no more.
  * Sessions run here too (roadmap #24), and as a THIRD account. Beside the
    jobs this keeps two ttyds up — the same two the controller's dashboard
    hook starts — running bb-tty from the bb bundle the controller ships,
    so a Claude session on this node's projects lives on this node, with
    this node's toolchains and the projects share it mounts. They run as
    the session account the provisioner made (--session-user), which is in
    no docker group: docker is root on any machine with a daemon, and the
    account a session works as is the one thing here to keep away from it.

Runs anywhere Python 3.8+ is, with nothing installed:

    builderbot-agent enroll --controller URL --token bbe_… [--user bb]
                            [--session-user builder] [--store data=/path]
                            [--pin sha256:…]
    builderbot-agent run            # the loop; what the unit runs
    builderbot-agent status         # what this node is, and does it answer
"""
import contextlib
import errno
import glob
import hashlib
import http.client
import ipaddress
import json
import os
import platform
import pty
import re
import select
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request

# WINDOW.BUILD, and the two halves answer different questions.
#
# The WINDOW is the project's semver minor, and it is the compatibility
# promise: while BuilderBot is 0.4.x, any 0.4 agent works with any 0.4
# controller and the other way round. 0.5.0 is where that promise ends and
# where breaking changes and the removal of stale compatibility paths belong.
# A test holds this half to the VERSION file, so the two cannot drift apart
# quietly — see test/agent.mjs.
#
# The BUILD is this file's own counter and moves only when this file moves,
# which is why it is not BuilderBot's patch number: most patches ship no new
# agent. It does NOT reset at a window boundary — 0.5.28 follows 0.4.27 — so
# that "which of these two is newer" always has an answer. A reset would put
# the same number on two different agents, and a number that cannot say which
# is newer is the reason the flat protocol number this replaced was useless.
AGENT_VERSION = "0.5.63"
# Where the enrollment lands. Overridable for tests, which run a throwaway
# agent against a throwaway controller and must not touch /etc.
NODE_JSON = os.environ.get("BUILDERBOT_NODE_JSON", "/etc/builderbot/node.json")
DEFAULT_STORES = {"data": "/var/lib/builderbot/data",
                  "packages": "/var/lib/builderbot/packages",
                  "cache": "/var/lib/builderbot/cache",
                  # What this node keeps of a project's built artifacts, so
                  # an emulator or a container here starts from a local copy
                  # rather than pulling one over the link every time — which
                  # is free on a LAN and is not on a node in somebody's
                  # cloud. Per project underneath (artifact_dir), because a
                  # VM may be several projects' node.
                  "artifacts": "/var/lib/builderbot/artifacts"}

# The session half (roadmap #24): the ttyd this node runs bb-tty under, the
# ports it binds, and the address. Seams for the suite — which runs a ttyd
# that only records what it was asked — and for a node whose ports are taken.
# The bind address defaults to the address the default route leaves by (the
# LAN one the controller reaches), not the loopback: the controller's proxy
# dials in from another machine. Phase 10b's firewall keeps it to the
# controller; until then nothing but the network's own rules does.
TTYD_BIN = os.environ.get("BUILDERBOT_TTYD_BIN", "ttyd")
SESSION_PORT = int(os.environ.get("BUILDERBOT_SESSION_PORT") or 7681)
SESSION_BIND = os.environ.get("BUILDERBOT_SESSION_BIND", "")
# What the census reports about it, kept by the Agent and read by census():
# the census is a function of the machine, and the session's state is the
# one part of the machine this process itself is holding.
SESSION = {}

# Where a store may NOT be put. The stores are directories this agent
# creates, fills, and — for the cache — empties on request, so a store
# pointed at a system tree is a delete waiting to happen: `--cache /etc`
# would make Clear cache remove every directory under /etc. Refused here and
# again on the controller, deliberately twice: the tab should say no before
# anybody presses, and the node should refuse whatever it is told, which is
# the same reasoning as the capability check (docs/nodes.md §15 door 7).
STORE_DENY_EXACT = {"/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib",
                    "/lib32", "/lib64", "/libx32", "/media", "/mnt", "/opt",
                    "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp",
                    "/usr", "/var"}
STORE_DENY_UNDER = ("/bin/", "/boot/", "/dev/", "/etc/", "/lib/", "/lib32/",
                    "/lib64/", "/libx32/", "/proc/", "/root/", "/run/",
                    "/sbin/", "/sys/", "/usr/", "/var/log/", "/var/run/",
                    "/var/lock/", "/var/spool/", "/var/cache/")


def _can_chown(path):
    """Whether this filesystem lets root change a file's owner.

    The discriminator between a local disk and a squashed NFS export, asked
    rather than guessed from the mount type: squashing is the server's
    policy and does not show in fstab. A chown to root:root is the test
    because it is a no-op locally and refused wherever ownership is the
    export's to decide.
    """
    probe = os.path.join(path, f".bb-chown-probe.{os.getpid()}")
    try:
        with open(probe, "w"):
            pass
    except OSError:
        return True          # cannot even write: the copy will say so itself
    try:
        os.chown(probe, 0, 0)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            os.remove(probe)


def store_path_ok(path):
    """"" if this is a safe place for a store, else why not. A bare
    top-level directory is refused as well as a system one: /mnt is where
    mounts live, not a store, and putting one there scatters directories
    across the mount root."""
    p = str(path or "").rstrip("/") or "/"
    if not p.startswith("/"):
        return f"{path!r} is not an absolute path"
    if " " in p or ".." in p.split("/"):
        return f"{path!r} must be a plain absolute path, with no spaces or .."
    if p in STORE_DENY_EXACT:
        return (f"{p} is a system directory (or the root of the mounts) — "
                "a store is a directory of its own, like /var/lib/builderbot/x "
                "or /mnt/<share>/<dir>")
    for bad in STORE_DENY_UNDER:
        if (p + "/").startswith(bad):
            return f"{p} is inside {bad.rstrip('/')}, which this agent will not write to"
    return ""
def make_store(path):
    """Create a store directory, and say which directories that actually
    brought into being.

    The list is the whole point. A store at /mnt/tank/bb/packages may have
    made two directories or none, and there is no way to tell afterwards —
    an empty /mnt/tank/bb could be ours or could be the operator's. So it is
    recorded at the moment of creation, and nothing outside that record is
    ever removed.
    """
    p = os.path.abspath(str(path))
    made, probe = [], p
    while probe and probe != "/" and not os.path.exists(probe):
        made.append(probe)
        probe = os.path.dirname(probe)
    os.makedirs(p, exist_ok=True)
    made.reverse()                      # shallowest first: the order they appeared
    return made


def prune_made(made):
    """Remove the directories in `made` that are now empty, deepest first.

    rmdir rather than a check-then-delete: it fails with ENOTEMPTY by
    itself, so there is no window between deciding a directory is empty and
    removing it. The first one that will not go stops the walk — a parent of
    something that is still there cannot be empty either — and a mountpoint
    is never touched, because removing the directory a share is mounted on
    is how you delete the thing you meant to detach.

    Returns (removed, [(path, why)]).
    """
    removed, kept = [], []
    for d in reversed(list(made or [])):
        if os.path.ismount(d):
            kept.append((d, "it is a mountpoint"))
            break
        try:
            os.rmdir(d)
            removed.append(d)
        except OSError as e:
            kept.append((d, e.strerror or "it would not go"))
            break
    return removed, kept


def mount_covering(path, mounts):
    """The bb-sandbox mount this path would live inside, or None.

    The deepest match wins, so /mnt/tank/builderbot/packages is answered by
    /mnt/tank rather than by /mnt if both are configured. This is what makes
    an unmounted share detectable: the mount is in fstab, the directory
    under it is not, and mkdir would quietly make a local one.
    """
    p = str(path or "").rstrip("/")
    best = None
    for m in mounts or []:
        mp = str(m.get("path") or "").rstrip("/")
        if not mp:
            continue
        if p == mp or p.startswith(mp + "/"):
            if best is None or len(mp) > len(str(best.get("path") or "").rstrip("/")):
                best = m
    return best


def dir_bytes(path):
    """What is in there, in bytes, or None if it cannot be told quickly.
    `du` rather than a walk: one C process instead of a stat per file, which
    matters on the far end of an NFS link."""
    try:
        out = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=180, check=False)
        return int(out.stdout.split()[0]) if out.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


# Where the configuration plane's tools are (docs/nodes.md §12, phase 5).
# bb-sandbox is the one copy of the mount logic, installed by the provisioner
# — its presence is what says this node was set up as a sandbox, and a
# `system` job is refused without it. The netplan seams exist so the tests
# can stand in for both without a root shell.
SANDBOX_BIN = os.environ.get("BUILDERBOT_SANDBOX_BIN", "/usr/local/sbin/bb-sandbox")
NETPLAN_DIR = os.environ.get("BUILDERBOT_NETPLAN_DIR", "/etc/netplan")
NETPLAN_BIN = os.environ.get("BUILDERBOT_NETPLAN_BIN", "netplan")
NETPLAN_FILE = "90-builderbot.yaml"
# How long a network change has to dial back in before it is reverted.
DIAL_BACK_S = 180
# How long after a ttyd start this will try another. A port already taken
# would otherwise spin the loop on a failing exec. Settable only so the suite
# can stop waiting on it — the test that proves a dead ttyd is started again
# waits exactly this long, and it was the slowest interval in the suite.
SESSION_RETRY_S = int(os.environ.get("BUILDERBOT_SESSION_RETRY_S") or 30)
# The Actions runner as a per-node service (docs/nodes.md §14, phase 7):
# where it lives, and — for the tests — a tarball to unpack instead of the
# GitHub release download.
RUNNER_DIR = os.environ.get("BUILDERBOT_RUNNER_DIR", "/var/lib/builderbot/runner")
# The machine's package manager, for a recipe's `system` packages. Seams for
# the suite, which must not touch the box it runs on.
APT_BIN = os.environ.get("BUILDERBOT_APT_BIN", "apt-get")
# Seconds per "minute" of the idle rule; the suite sets 1.
IDLE_UNIT = float(os.environ.get("BUILDERBOT_IDLE_UNIT", "60"))


def has_systemd():
    """Whether the runner can be a service here. A VM has systemd; a
    container (this image in the node role) and a guest machine without it
    run the runner in the foreground under the agent instead. The suite
    pins the answer with BUILDERBOT_SYSTEMD so both paths are exercised
    whichever box runs it."""
    pin = os.environ.get("BUILDERBOT_SYSTEMD", "")
    if pin in ("0", "1"):
        return pin == "1"
    return os.path.isdir("/run/systemd/system")
DPKG_BIN = os.environ.get("BUILDERBOT_DPKG_BIN", "dpkg")
# ...and the RHEL family's pair, for a node provisioned on Rocky (nodes/provision-linux.sh
# takes either): a recipe names its packages per family under `system.apt`
# and `system.dnf`, and the agent uses the list for the manager it has.
DNF_BIN = os.environ.get("BUILDERBOT_DNF_BIN", "dnf")
RPM_BIN = os.environ.get("BUILDERBOT_RPM_BIN", "rpm")
# NetworkManager's CLI, the network backend where there is no netplan (the
# RHEL family). Settable for the same reason as netplan's: the suite stubs it.
NMCLI_BIN = os.environ.get("BUILDERBOT_NMCLI_BIN", "nmcli")
# The other package managers and network backends this agent can drive —
# one pair per family, detected on the machine, never told by the
# controller. Each settable so the suite can point one at a stub or at a
# path that does not exist.
PACMAN_BIN = os.environ.get("BUILDERBOT_PACMAN_BIN", "pacman")
ZYPPER_BIN = os.environ.get("BUILDERBOT_ZYPPER_BIN", "zypper")
APK_BIN = os.environ.get("BUILDERBOT_APK_BIN", "apk")
XBPS_QUERY_BIN = os.environ.get("BUILDERBOT_XBPS_QUERY_BIN", "xbps-query")
XBPS_INSTALL_BIN = os.environ.get("BUILDERBOT_XBPS_INSTALL_BIN", "xbps-install")
EMERGE_BIN = os.environ.get("BUILDERBOT_EMERGE_BIN", "emerge")
BREW_BIN = os.environ.get("BUILDERBOT_BREW_BIN", "brew")
# The session ports' firewall rule the provisioner wrote, which names the
# controller's address: the agent keeps it true when that address moves.
NFT_BIN = os.environ.get("BUILDERBOT_NFT_BIN", "nft")
FIREWALL_CMD = os.environ.get("BUILDERBOT_FIREWALL_CMD", "firewall-cmd")
SESSION_NFT = os.environ.get("BUILDERBOT_SESSION_NFT", "/etc/builderbot/session-ports.nft")
FIREWALL_EVERY_S = 60
NETWORKD_DIR = os.environ.get("BUILDERBOT_NETWORKD_DIR", "/etc/systemd/network")
NETWORKCTL_BIN = os.environ.get("BUILDERBOT_NETWORKCTL_BIN", "networkctl")
INTERFACES_FILE = os.environ.get("BUILDERBOT_INTERFACES_FILE", "/etc/network/interfaces")
IFUP_BIN = os.environ.get("BUILDERBOT_IFUP_BIN", "ifup")
IFDOWN_BIN = os.environ.get("BUILDERBOT_IFDOWN_BIN", "ifdown")
WICKED_BIN = os.environ.get("BUILDERBOT_WICKED_BIN", "wicked")
SYSCONFIG_NET_DIR = os.environ.get("BUILDERBOT_SYSCONFIG_NET_DIR", "/etc/sysconfig/network")
DHCPCD_CONF = os.environ.get("BUILDERBOT_DHCPCD_CONF", "/etc/dhcpcd.conf")
OS_RELEASE = os.environ.get("BUILDERBOT_OS_RELEASE", "/etc/os-release")
RUNNER_TARBALL = os.environ.get("BUILDERBOT_RUNNER_TARBALL", "")
RUNNER_RELEASES = "https://api.github.com/repos/actions/runner/releases/latest"
# Gitea's runner: one static binary, fetched from gitea.com's releases, or a
# prebuilt one named here for the suite.
ACT_RUNNER_BIN = os.environ.get("BUILDERBOT_ACT_RUNNER_BIN", "")
ACT_RUNNER_RELEASES = "https://gitea.com/api/v1/repos/gitea/act_runner/releases/latest"

def runner_slot(url):
    """The slot a runner's address maps to: its host and path, lowercase,
    letters, digits, dots and dashes, so it can name a directory on the
    node, a token file on the controller and a row on the tab. One runner
    per slot per node, since a runner's name on its host is the node's.
    The same function lives in scripts/dashboard/nodes.py; the two must agree."""
    rest = re.sub(r"^[a-z]+://", "", str(url or "").strip().lower()).rstrip("/")
    rest = re.sub(r"\.git$", "", rest)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9.]+", "-", rest)).strip("-.")[:60]


def _runner_record(d):
    """The runner's own record of its registration in directory d, whichever
    runner: GitHub's writes agentName and gitHubUrl (with a BOM), act_runner
    writes name, address and id. {} when none is registered there."""
    try:
        with open(os.path.join(d, ".runner"), encoding="utf-8-sig") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def runner_dirs():
    """Every directory holding a registered runner: RUNNER_DIR itself for a
    runner registered before a node could hold several (its unit names that
    path, so it stays), and RUNNER_DIR/<slot> for each since. [(dir, record)]."""
    out = []
    rec = _runner_record(RUNNER_DIR)
    if rec:
        out.append((RUNNER_DIR, rec))
    try:
        subs = sorted(os.listdir(RUNNER_DIR))
    except OSError:
        subs = []
    for sub in subs:
        d = os.path.join(RUNNER_DIR, sub)
        rec = _runner_record(d) if os.path.isdir(d) else {}
        if rec:
            out.append((d, rec))
    return out


def _runner_state(d, rec):
    """One runner as the census reports it: what it registered as and
    whether its listener is up, read from its own files."""
    labels = []
    with contextlib.suppress(OSError):
        with open(os.path.join(d, ".builderbot-labels")) as f:
            labels = [x for x in f.read().split(",") if x]
    # GitHub's runner listens as bin/Runner.Listener; act_runner as
    # `<dir>/act_runner daemon`, in the foreground under this agent.
    pg = (_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Listener")])
          or _run(["pgrep", "-f", os.path.join(d, "act_runner") + " daemon"]))
    # WHERE ITS OUTPUT GOES, which only this machine knows. Under systemd
    # svc.sh writes the unit's name into .service and the listener's output
    # is the journal's; in the foreground it is runner.log under the data
    # store. Empty when there is no unit, and the controller reads the file.
    unit = ""
    if has_systemd():
        with contextlib.suppress(OSError):
            with open(os.path.join(d, ".service")) as f:
                unit = f.read().strip()[:120]
    url = str(rec.get("gitHubUrl") or rec.get("address") or "")[:200]
    # GitHub's .runner says agentName and gitHubUrl; act_runner's says name
    # and address, which is also how the two are told apart.
    return {"installed": True, "slot": runner_slot(url),
            "name": str(rec.get("agentName") or rec.get("name") or "")[:80],
            "url": url, "forge": "gitea" if "address" in rec else "github",
            "unit": unit, "labels": labels[:16], "active": bool(pg),
            "busy": bool(_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Worker")]))}
# Tailscale, for Funnel (docs/nodes.md §7, phase 8): a seam so the tests can
# stand in for it, like the rest of the tools the agent drives.
TAILSCALE_BIN = os.environ.get("BUILDERBOT_TAILSCALE_BIN", "tailscale")


def _zombie(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[-1].split()[0] == "Z"
    except (OSError, IndexError):
        return False


def log(msg):
    # journald stamps its own time; a bare line reads best in `journalctl -u`.
    print(f"[builderbot-agent] {msg}", file=sys.stderr, flush=True)


def own_digest():
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            return "sha256:" + hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# the connection

class Controller:
    """One controller, one credential, one way to talk to it.

    TLS is verified by PIN, not by CA: the controller's certificate digest is
    learned at enrollment (given with --pin, or trusted on first use and
    printed so it can be checked) and every later connection must present
    the same one. A LAN dashboard with a self-signed certificate is exactly
    the case, and a CA is a later layer (docs/nodes.md §4). Plain http is
    allowed and said plainly: the token then travels in the clear, which is
    no worse than the dashboard's own credential already does on that
    network — and no better.
    """

    def __init__(self, url, token, pin=""):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise SystemExit(f"controller URL is not http(s)://host[:port]: {url}")
        self.url, self.token, self.pin = url.rstrip("/"), token, pin
        self.scheme, self.host = u.scheme, u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base = u.path.rstrip("/")

    def _conn(self, timeout):
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE       # the pin below is the check
        c = http.client.HTTPSConnection(self.host, self.port, timeout=timeout,
                                        context=ctx)
        c.connect()
        seen = "sha256:" + hashlib.sha256(c.sock.getpeercert(True)).hexdigest()
        if self.pin and seen != self.pin:
            c.close()
            raise ssl.SSLError(f"controller certificate changed: pinned "
                               f"{self.pin[:19]}…, presented {seen[:19]}…")
        self.seen_pin = seen
        return c

    def call(self, verb, body=None, timeout=30, method="POST", raw=False):
        """(status, decoded body). Status 0 means no answer at all —
        the controller is down or unreachable — and is the case the loop
        backs off on rather than treating as a refusal."""
        try:
            c = self._conn(timeout)
            hdrs = {"Authorization": "Bearer " + self.token,
                    "User-Agent": f"builderbot-agent/{AGENT_VERSION}"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                hdrs["Content-Type"] = "application/json"
            c.request(method, f"{self.base}/api/v1/agent/{verb}", data, hdrs)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        if raw:
            return r.status, payload
        if r.status == 204 or not payload:
            return r.status, {}
        try:
            return r.status, json.loads(payload)
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}

    def fetch(self, path, dest, timeout=600):
        """GET a large body straight to a file. (status, digest-header)
        — the snapshot and the bundle both arrive this way, and neither
        belongs in memory twice."""
        try:
            c = self._conn(timeout)
            c.request("GET", f"{self.base}/api/v1/agent/{path}", None,
                      {"Authorization": "Bearer " + self.token,
                       "User-Agent": f"builderbot-agent/{AGENT_VERSION}"})
            r = c.getresponse()
            if r.status != 200:
                r.read()
                c.close()
                return r.status, ""
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            c.close()
            os.replace(tmp, dest)
            return 200, (r.getheader("X-Snapshot-Digest") or r.getheader("X-Bundle-Digest") or "")
        except (OSError, http.client.HTTPException) as e:
            return 0, str(e)

    def upload(self, path, src, timeout=600):
        """POST a file as the raw body. (status, decoded answer)."""
        try:
            size = os.path.getsize(src)
            c = self._conn(timeout)
            c.putrequest("POST", f"{self.base}/api/v1/agent/{path}")
            c.putheader("Authorization", "Bearer " + self.token)
            c.putheader("User-Agent", f"builderbot-agent/{AGENT_VERSION}")
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(size))
            c.endheaders()
            with open(src, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    c.send(chunk)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        try:
            return r.status, json.loads(payload) if payload else {}
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}


# ---------------------------------------------------------------------------
# the census and the sample

def _run(argv, timeout=5):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


_PROBE_SAID = set()


def _probe(argv, timeout=5):
    """Ask a tool for its version: what it said, and whether it ANSWERED.

    _run cannot tell those apart — it hands back stdout or stderr and drops
    the status — so a binary that ABORTS on startup read as a tool that
    printed something odd, and _clean_version called that "present". The node
    then advertised a toolchain it cannot run, and the controller placed work
    there that could only fail on arrival. Measured on bb-sandbox-redhat,
    where the packages store's dotnet dies every census while the row said
    the node had .NET.

    Death by SIGNAL, or a probe that never comes back, is the line. A
    non-zero EXIT is not: `flutter --version` as root and rustup with no
    default toolchain both exit non-zero with a sentence, and both mean the
    tool is installed and being awkward, which is what "present" is for.

    There is no attempt to stop a crashing probe dumping core, because there
    is no way to from here. This ran under `ulimit -c 0` for one build on the
    theory that a version probe has no business leaving a core file — and the
    kernel ignores RLIMIT_CORE when core_pattern is a PIPE, which is what
    both machines here have (apport on one, systemd-coredump on the other).
    Measured, not assumed: the limit reads back as 0 and the process is
    dumped anyway. The dumps stop when the tool does; what this can do is
    say which binary it was, which is the part nobody had.
    """
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           check=False)
    except subprocess.TimeoutExpired:
        return "", f"did not answer within {timeout}s"
    except (OSError, subprocess.SubprocessError) as e:
        return "", str(e)[:80]
    out = (p.stdout or p.stderr).strip()
    return out, (f"died on signal {-p.returncode}" if p.returncode < 0 else "")


def _probe_died(name, path, out, why):
    """Say it once, and leave the name out of the census.

    Out, because reporting a toolchain that cannot start is what lets the
    controller send work here that can only fail. Once per agent process,
    because the census runs every ten minutes and the interesting part — the
    tool's own first line, which is the whole diagnosis — does not change; a
    restart says it again, which is when somebody is looking anyway.
    """
    if name in _PROBE_SAID:
        return
    _PROBE_SAID.add(name)
    # The whole of what it said, newlines folded — not its first line, which
    # was the first cut of this and threw the answer away: .NET's startup
    # failures open with "Process terminated." on a line of their own and put
    # the reason on the next one, so the log carried the half that says
    # nothing and dropped the half somebody has to act on.
    said = " ".join((out or "").split())[:300]
    log(f"toolchain: {path} {why} when asked its version, so {name} is not in "
        f"this node's census" + (f" — it said: {said}" if said else ""))


def _mem():
    tot = avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    tot = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return tot, max(0, tot - avail)


def _sshd_listening():
    # Port 22 in LISTEN (state 0A) in either table — cheaper and truer than
    # asking systemd, which does not know about a dropbear.
    for tab in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(tab) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if cols[1].endswith(":0016") and cols[3] == "0A":
                        return True
        except OSError:
            continue
    return False


STORE_ID_FILE = ".bb-store-id"


# ---------------------------------------------------------------------------
# the package store, scoped by platform (roadmap R19)
#
# One share can serve a Linux box, a Mac and a Windows machine only if their
# binaries do not land on top of each other: the store's root is therefore
# <store>/<os>-<arch> — linux-x86_64, darwin-arm64 — and everything else
# (the layout, the probes, the census, the bundle) is relative to that. The
# operator's setting stays the share; the scope is this machine's own fact.
# What is the same bytes on every host — the Android system images, tens of
# gigabytes — lives once under <store>/shared and each scope's android tree
# links to it, because sdkmanager and Gradle want one ANDROID_HOME and
# would otherwise fetch a second copy per platform. (The one-time move of a
# flat store into its scope ran on 9 Sep 2026 and was taken out again.)


def pkg_scope():
    """This machine's scope directory name: <os>-<arch> as uname spells them."""
    return f"{platform.system().lower()}-{platform.machine() or 'unknown'}"


def pkg_root(state):
    """Where THIS machine's packages live: the packages store's scope
    directory, or "" when the node has no packages store."""
    store = (state.get("stores") or {}).get("packages") or ""
    return os.path.join(store, pkg_scope()) if store else ""


def share_images(store, say=None):
    """The standing rule of the layout, kept each hello: the Android system
    images live once under <store>/shared/android/system-images, and this
    scope's android/system-images is a symlink to them. A scope whose
    android tree grew a real directory there (a first install on a fresh
    store) has it moved under shared and linked; a scope with an android
    tree and no images gets the link so an install lands in the shared
    copy from the start."""
    say = say or (lambda t: log(t))
    if not store or not os.path.isdir(store):
        return
    scoped = os.path.join(store, pkg_scope())
    mine = os.path.join(scoped, "android", "system-images")
    shared = os.path.join(store, "shared", "android", "system-images")
    if os.path.islink(mine):
        return
    if os.path.isdir(mine):
        try:
            if not os.path.isdir(shared):
                os.makedirs(os.path.dirname(shared), exist_ok=True)
                os.rename(mine, shared)
            else:
                # Both exist: fold what is only here into the shared copy.
                for e in os.listdir(mine):
                    if not os.path.exists(os.path.join(shared, e)):
                        os.rename(os.path.join(mine, e), os.path.join(shared, e))
                if os.listdir(mine):
                    say(f"packages store: {mine} still holds images the shared copy also has — "
                        "remove it by hand and the link is made on the next start")
                    return
                os.rmdir(mine)
            say("packages store: the android system images are shared across platforms")
        except OSError as ex:
            say(f"packages store: could not share the system images: {ex}")
            return
    if os.path.isdir(shared) and os.path.isdir(os.path.join(scoped, "android")) and not os.path.lexists(mine):
        with contextlib.suppress(OSError):
            os.symlink(os.path.relpath(shared, os.path.dirname(mine)), mine)


def fix_flat_links(store, say=None):
    """The other standing rule, and it is a repair: a symlink inside this
    scope that still points at the FLAT store it was made in.

    Before R19 a store was one directory; now everything lives under
    <store>/<os>-<arch>. The move brought the trees across, and the links
    inside them kept naming where they used to be — so this scope's
    android/cmdline-tools/latest still pointed at <store>/android-tools,
    which no longer exists. Nothing said so: the PATH entry for it was
    silently dropped for being a directory that is not there, `bb packages`
    reported "no cmdline-tools" beside a store that has them, and every
    sdkmanager call on the node failed to be found (B105).

    Narrow on purpose: only a link that is broken AND whose target is the
    same path one level up from the scope, which is the one thing the move
    could have produced. Anything else is somebody's own arrangement.
    """
    say = say or (lambda t: log(t))
    scoped = os.path.join(store or "", pkg_scope())
    if not store or not os.path.isdir(scoped):
        return
    for root, dirs, names in os.walk(scoped):
        # The link may be a directory entry, so both lists are walked; three
        # levels is as deep as any of these go, and a store holds gigabytes
        # of SDK below that nothing here should be reading.
        if root[len(scoped):].count(os.sep) >= 3:
            dirs[:] = []
        for name in list(dirs) + names:
            path = os.path.join(root, name)
            if not os.path.islink(path) or os.path.exists(path):
                continue
            target = os.readlink(path)
            if not target.startswith(store + os.sep):
                continue
            rest = target[len(store) + 1:]
            fixed = os.path.join(scoped, rest)
            if not os.path.exists(fixed):
                continue
            with contextlib.suppress(OSError):
                os.remove(path)
                os.symlink(fixed, path)
                say(f"packages store: {path} pointed at the flat store; "
                    f"repointed at {fixed}")


def store_id(path):
    """A stable id for a store, from a marker inside it — the same file the
    controller reads for its own (nodes.store_id).

    Two machines mounting one share cannot recognize each other by path: the
    controller reaches the package store through Unraid's FUSE layer while this
    node reaches the same bytes over NFS, and neither mount string can be
    derived from the other. The file answers exactly, whatever the transport.
    Read-only here: the controller creates it, so a node with a read-only
    store still reports the right id and never writes to one it should not.
    """
    try:
        with open(os.path.join(path, STORE_ID_FILE)) as f:
            return f.read().strip()[:64]
    except OSError:
        return ""


def _stores(stores, used=False):
    out = {}
    for role, path in (stores or {}).items():
        try:
            st = os.statvfs(path)
            out[role] = {"path": path, "id": store_id(path),
                         "free_mb": st.f_bavail * st.f_frsize // (1024 * 1024),
                         "total_mb": st.f_blocks * st.f_frsize // (1024 * 1024)}
            if role == "packages":
                out[role]["scope"] = pkg_scope()      # where THIS machine's packages are, under path
        except OSError:
            # Not there is a different fact from full: reported as null so
            # the row says "missing" rather than "0MB free".
            out[role] = {"path": path, "free_mb": None, "total_mb": None}
            continue
        if used:
            # What the store itself holds — the cache's size is the number
            # the row shows beside its Clear (docs/nodes.md §6). du, at the
            # census only: a walk of a big cache is not a per-poll cost.
            n = _run(["du", "-sm", path], timeout=60).split()
            out[role]["used_mb"] = int(n[0]) if n and n[0].isdigit() else None
    return out


# Where a toolchain installed into the packages store keeps its command,
# relative to the store (bb packages's layout), for the census to find without
# PATH knowing about it. `android` is a directory, not a command.
def _lay_path(store, entry, rel):
    """A layout path against the store. `root:` means the store itself;
    anything else is under the package's own directory."""
    if rel.startswith("root:"):
        return os.path.join(store, rel[5:])
    return os.path.join(store, entry["dir"], rel) if rel else \
        os.path.join(store, entry["dir"])


def store_layout(state):
    """What the controller last told us about where packages land, or the
    built-in answer for a controller too old to say.

    The fallback is deliberately the old tables: a node whose controller
    predates this must keep working, and a node whose controller is newer
    must follow it rather than a copy of its own that can drift.
    """
    got = state.get("layout")
    return got if isinstance(got, list) and got else BUILTIN_LAYOUT


# The answer this agent shipped with, used only when the controller does not
# send one. Kept short and honest: it is a fallback, not a second authority.
BUILTIN_LAYOUT = [
    {"name": "jdk", "dir": "jdk", "bin": ["bin"], "env": {"JAVA_HOME": ""},
     "tool": "bin/java", "reports": "java"},
    {"name": "flutter", "dir": "flutter", "bin": ["bin"], "env": {},
     "tool": "bin/flutter", "reports": "flutter"},
    {"name": "dotnet", "dir": "dotnet", "bin": ["", "tools"],
     "env": {"DOTNET_ROOT": ""}, "tool": "dotnet", "reports": "dotnet"},
    {"name": "go", "dir": "go", "bin": ["bin"], "env": {}, "tool": "bin/go",
     "reports": "go"},
    {"name": "lint-tools", "dir": "lint-tools", "bin": ["bin"], "env": {},
     "tool": "bin/shellcheck", "reports": "shellcheck"},
    {"name": "node", "dir": "node", "bin": ["bin"], "env": {}, "tool": "bin/node",
     "reports": "node"},
    {"name": "swift", "dir": "swift", "bin": ["usr/bin"], "env": {},
     "tool": "usr/bin/swift", "reports": "swift"},
    {"name": "rust", "dir": "rust", "bin": ["cargo/bin"],
     "env": {"RUSTUP_HOME": "rustup", "CARGO_HOME": "cargo"},
     "tool": "cargo/bin/cargo", "reports": "rust"},
    {"name": "zig", "dir": "zig", "bin": [""], "env": {}, "tool": "zig", "reports": ""},
    {"name": "android-tools", "dir": "android-tools",
     "bin": ["root:android/cmdline-tools/latest/bin", "root:android/platform-tools"],
     "env": {}, "tool": "cmdline-tools/bin/sdkmanager", "reports": ""},
    {"name": "android:emulator", "dir": "android", "bin": ["root:android/emulator"],
     "env": {}, "tool": "root:android/emulator/emulator", "reports": "emulator"},
]

STORE_TOOLS = {"java": ("jdk/bin/java",), "flutter": ("flutter/bin/flutter",),
               "dotnet": ("dotnet/dotnet",), "go": ("go/bin/go",),
               "node": ("node/bin/node",), "swift": ("swift/usr/bin/swift",),
               "cargo": ("rust/cargo/bin/cargo",),
               # The BINARIES, not the directories they sit in. Checking the
               # directories called android-sdk present on a node whose
               # cmdline-tools was an empty folder and whose platform-tools
               # did not exist — so toolchain_gap admitted a job needing adb
               # and it failed there instead of being refused here.
               "android-sdk": ("android/platform-tools/adb",
                               "android/cmdline-tools/latest/bin/sdkmanager",
                               "android/cmdline-tools/bin/sdkmanager"),
               "emulator": ("android/emulator/emulator",),
               # adb on its own: a phone is driven from whichever node has
               # it, and the Phone tab's picker reads this.
               "adb": ("android/platform-tools/adb",),
               # web-ext beside it: pushing a Firefox extension to the phone
               # is web-ext driving that adb, on the same node.
               "web-ext": ("node/bin/web-ext",)}


def _toolchains(state):
    """What this node can build with: on PATH, or in its packages store.
    The census's `toolchains` is what package-build placement selects on."""
    tc = {}
    store = pkg_root(state)
    by_report = {}
    for entry in store_layout(state):
        if entry.get("reports") and entry.get("tool"):
            by_report[entry["reports"]] = entry

    def find(name):
        entry = by_report.get(name)
        if store and entry:
            p = _lay_path(store, entry, entry["tool"])
            if os.path.exists(p):
                return p
        for rel in STORE_TOOLS.get(name, ()):
            p = os.path.join(store, rel)
            if store and os.path.exists(p):
                return p
        return shutil.which(name)
    j = find("java")
    if j:
        out, dead = _probe([j, "-version"])
        if dead:
            _probe_died("java", j, out, dead)
        else:
            m = re.search(r'version "([^"]+)"', out)
            tc["java"] = m.group(1) if m else "present"
    for name in ("flutter", "dotnet", "node", "go", "swift", "cargo"):
        p = find(name)
        if p and os.path.isfile(p):
            arg = "version" if name == "go" else "--version"
            key = "rust" if name == "cargo" else name
            out, dead = _probe([p, arg], timeout=20)
            if dead:
                _probe_died(key, p, out, dead)
            else:
                tc[key] = _clean_version((out.splitlines() or [""])[0])
    p = find("android-sdk")
    if p and os.path.isfile(p):
        tc["android-sdk"] = "present"
    p = find("emulator")
    if p and os.path.isfile(p):
        tc["emulator"] = "present"
    p = find("adb")
    if p and os.path.isfile(p):
        tc["adb"] = "present"
    p = find("web-ext")
    if p and os.path.isfile(p):
        tc["web-ext"] = "present"
    return tc


def _clean_version(text):
    """A version line, or "present" when the tool answered with something
    else. `flutter --version` as root leads with "Woah! You appear to be
    trying to run flu…" and rustup with "error: rustup could not choose a
    version" — both mean the thing is there, and neither is a version, so
    putting them on a row as one is worse than saying nothing."""
    line = (text or "").strip()
    if not line or not re.search(r"\d+\.\d+", line[:80]) or re.match(
            r"(?i)\s*(error|warning|woah|note)\b", line):
        return "present"
    return line[:40]


def read_catalog(into):
    """The catalog the bundle carries, or {} when it cannot be read."""
    try:
        with open(os.path.join(into, "config", "packages.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def sysdeps_missing(cat, name, fam, query):
    """(the recipe's system packages missing on this machine, and (family,
    names) when its recipe lists them for another family only). Asked by
    exit code, never by output: dpkg -s and pacman -Q both print a sentence
    on stderr for a missing package, which read as "installed" when the
    text was the test, and rpm -q prints "not installed" on stdout."""
    pkg = next((p for p in cat.get("packages") or [] if p.get("name") == name), {})
    system = pkg.get("system") or {}
    want = [str(x) for x in (system.get(fam) or []) if x][:64] if fam else []
    if not want:
        other = next((k for k in ("apt", "dnf", "pacman", "zypper", "apk", "xbps", "emerge")
                      if k != fam and system.get(k)), "")
        return [], ((other, [str(x) for x in system[other][:64]]) if other else None)
    missing = []
    for x in want:
        if not query:
            missing.append(x)          # emerge: no query, --noreplace skips the installed
            continue
        try:
            p = subprocess.run(query + [x], capture_output=True, timeout=30, check=False)
            if p.returncode != 0:
                missing.append(x)
        except (OSError, subprocess.SubprocessError):
            missing.append(x)
    return missing, None


def held_recipes(state, cat):
    """The catalog recipes with system packages whose directory the store
    holds, complete or not: browsers from before the module still need the
    libraries."""
    store = pkg_root(state)
    if not store:
        return []
    dirs = {e["name"]: e.get("dir") for e in store_layout(state) if e.get("name")}
    out = []
    for p in cat.get("packages") or []:
        name = p.get("name")
        if not name or not p.get("system"):
            continue
        d = dirs.get(name) or name
        if os.path.isdir(os.path.join(store, d)):
            out.append(name)
    return out


def sysdeps_now(state):
    """The census's answer (roadmap R51): {family, unmet: {recipe: [pkg]}},
    from the bundle the store already holds; nothing until one is there."""
    store = pkg_root(state)
    into = os.path.join(store, ".bb", "current") if store else ""
    if not into or not os.path.isdir(into):
        return {}
    cat = read_catalog(into)
    fam, query, _ = pkg_backend()
    if not fam or not cat:
        return {}
    unmet = {}
    for name in held_recipes(state, cat):
        missing, _ = sysdeps_missing(cat, name, fam, query)
        if missing:
            unmet[name] = missing
    return {"family": fam, "unmet": unmet}


def store_dirs(state):
    """What is actually IN the packages store, as directory names.

    The census's `toolchains` above is a placement summary — six names, so a
    job can select on them — and it was being read as an inventory of the
    whole catalog, which called four installed packages missing on a store
    the controller could see for itself. `bb packages` puts each package in
    <root>/<name>, and android's parts under <root>/android/, so the names
    ARE the inventory and this is one listdir.
    """
    store = pkg_root(state)
    out = {"top": [], "android": []}
    if not store:
        return out
    with contextlib.suppress(OSError):
        out["top"] = sorted(x for x in os.listdir(store) if not x.startswith("."))[:64]
    with contextlib.suppress(OSError):
        out["android"] = sorted(os.listdir(os.path.join(store, "android")))[:64]
    # A directory is not a package. The playwright recipe used to be its
    # browsers alone, and a store from then has the directory without the
    # module the recipe now carries — so the row said installed and offered
    # nothing, while bb shot on the node could not find the module. A layout
    # that names the file which completes it (`needs`) is checked here, and
    # the controller reads a name in this list as not installed.
    for entry in store_layout(state):
        need = entry.get("needs")
        if not need or entry.get("dir", "").startswith("android"):
            continue
        d = os.path.join(store, entry["dir"])
        if os.path.isdir(d) and not os.path.exists(os.path.join(d, need)):
            out.setdefault("incomplete", []).append(entry["name"])
    return out


def sdk_images(state):
    """The android system images in this node's packages store, and which of
    its AVDs are built on each.

    A directory walk, deliberately — not `bb packages images`, which is the same
    listing plus a `du -sk` per image. The controller's own copy can afford
    that; a node cannot. The packages store is commonly an NFS export here
    and the tree runs to tens of gigabytes, so a size measured every census
    would be minutes of stat traffic every ten minutes for a number the
    catalog already knows: an image is a guest artifact, identical on every
    host, and its download size comes from Google's index on the controller.

    The AVD half is not derivable anywhere else, which is why it is here. An
    AVD names one image exactly — `image.sysdir.1=system-images/android-36/
    google_apis/x86_64/` — and will not boot without it, so it is the whole
    of the answer to "can this one go?".
    """
    stores = state.get("stores") or {}
    store = pkg_root(state)
    if not store:
        return []
    base = os.path.join(store, "android", "system-images")
    rows = []
    for api in sorted(_listdir(base))[:64]:
        for kind in sorted(_listdir(os.path.join(base, api)))[:16]:
            for abi in sorted(_listdir(os.path.join(base, api, kind)))[:8]:
                d = os.path.join(base, api, kind, abi)
                if not os.path.isdir(d) or not _listdir(d):
                    continue          # an empty directory is not an image
                rows.append({"id": f"system-images;{api};{kind};{abi}",
                             "api": api, "kind": kind, "abi": abi, "avds": []})
    if not rows:
        return rows
    by_id = {r["id"]: r for r in rows}
    home = os.path.join(stores.get("data") or "/tmp", "avd")   # as sdk_env sets it
    for name in sorted(_listdir(home))[:64]:
        if not name.endswith(".avd"):
            continue
        try:
            with open(os.path.join(home, name, "config.ini"), encoding="utf-8",
                      errors="replace") as f:
                text = f.read(65536)
        except OSError:
            continue
        # Spaces around the = are allowed: avdmanager writes them, the
        # emulator's own rewrites do not, and both turn up in one directory.
        m = re.search(r"(?m)^\s*image\.sysdir\.1\s*=\s*(\S+)", text)
        if not m:
            continue
        want = m.group(1).rstrip("/").replace("/", ";")
        if want in by_id:
            by_id[want]["avds"].append(name[:-4])
    return rows


def _listdir(path):
    if not path:
        return []
    try:
        return [x for x in os.listdir(path) if not x.startswith(".")]
    except OSError:
        return []


def sdk_env(state, who=None):
    """The environment a job runs with on this node: the packages store as
    the package store root, its android/ directory as ANDROID_HOME, its jdk as
    JAVA_HOME, every toolchain it holds on PATH, and AVDs under the data
    store. What the image gets from its Dockerfile, a node gets from here.

    EVERY job, not only a bb verb. It used to be applied in the bb branch of
    Job.exec alone, so `bb build` and `bb test` — a plain exec — ran with a
    bare PATH: measured on a real node, java and go were both NOT-ON-PATH
    and JAVA_HOME unset, on a node whose census reported java 21.0.12.1 and
    go present. The placement gate said yes and then ./gradlew could not
    find a compiler (bug #45).
    """
    stores = state.get("stores") or {}
    store = pkg_root(state)
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8"}
    if store:
        android = os.path.join(store, "android")
        env.update({"SDK_ROOT": store, "BUILDER_HOME": store, "BB_NODE_PACKAGES": "1",
                    "ANDROID_HOME": android, "ANDROID_SDK_ROOT": android})
        front = []
        for entry in store_layout(state):
            for rel in entry.get("bin") or []:
                d = _lay_path(store, entry, rel)
                if os.path.isdir(d) and d not in front:
                    front.append(d)
            for k, v in (entry.get("env") or {}).items():
                d = _lay_path(store, entry, v)
                if os.path.exists(d):
                    env.setdefault(k, d)
        # The store ahead of the system PATH: a node that carries its own JDK
        # is meant to build with that one, not with whatever the distribution
        # happens to have.
        env["PATH"] = ":".join(front + [env["PATH"]])
    env["ANDROID_AVD_HOME"] = os.path.join(stores.get("data") or "/tmp", "avd")
    # Where CI logs are archived on this node (roadmap #24, step 4). The
    # workflows honor BB_CI_LOG_DIR and so does `bb ci-log`; without it the
    # runner kept them under its own home, 0700, where a session on the node
    # — a different account — could not read them. The data store is the
    # one directory both accounts see, and the runner's .env (written by
    # _apply_runner) names the same path, so the archive and the reader
    # agree without either being configured by hand.
    env["BB_CI_LOG_DIR"] = ci_log_dir(state)
    return env


def ci_log_dir(state):
    return os.path.join((state.get("stores") or {}).get("data") or "/tmp", "ci-logs")


def runner_env_text(state):
    """The runner's .env: the SAME environment sdk_env hands every other job
    on this node, one KEY=VALUE per line, which the runner reads into every
    job it runs. It carried only BB_CI_LOG_DIR until 8 Sep, so a CI job's
    PATH was the bare system's — no node, no Playwright, no store — while a
    session or a bb job on the same machine had the toolchain. The browser
    suite then skipped with exit 0 and every 'dashboard tests' run on
    bb-sandbox was green without running a test (bug B74). Sorted, so the
    text is stable and runner_env_sync can compare it byte for byte.
    """
    return "".join(f"{k}={v}\n" for k, v in sorted(sdk_env(state).items()))


def sdk_versions(state):
    """What `bb packages versions` reports on this node: {name: version}.

    The SAME generator the controller runs for its own list, so the two
    describe one store the same way. Before this, a node's versions came
    from _toolchains() — a six-name placement summary with crude parsing —
    and the Tools tab showed "present" beside a package the controller could
    name a version for, an unstripped "go version go1.27.0 linux/amd64", and
    nothing at all for the NDK. One store, two descriptions of it.

    Run from a bundle already cached in the packages store, which a package
    job puts there: no round trip, no second copy of the probe logic, and
    nothing reported at all until a job has run — which is the honest answer
    rather than a summary standing in for an inventory.
    """
    store = pkg_root(state)
    if not store:
        return {}
    bbdir = os.path.join(store, ".bb")
    try:
        cands = [os.path.join(bbdir, d) for d in os.listdir(bbdir)]
        cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        return {}
    env = dict(os.environ)
    env.update(sdk_env(state))
    for c in cands[:3]:
        bb = os.path.join(c, "scripts", "bb")
        if not os.path.isfile(bb):
            continue
        try:
            p = subprocess.run(["bash", bb, "packages", "versions"], capture_output=True,
                               text=True, timeout=120, check=False, env=env)
        except (OSError, subprocess.SubprocessError):
            return {}
        out = {}
        for line in (p.stdout or "").splitlines():
            f = line.rstrip().split("\t")
            if len(f) == 4 and f[1] not in ("", "-"):
                out[f[0][:40]] = f[1][:40]
        return out
    return {}


def census(state):
    """What this machine is. Asked at hello — every ten minutes — so the
    slow questions (docker, java) are allowed here and not in the sample."""
    tot, _ = _mem()
    tc = _toolchains(state)
    gpu = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]) \
        if shutil.which("nvidia-smi") else ""
    return {
        "cpu": os.cpu_count() or 0, "mem_mb": tot,
        "os": f"{platform.system().lower()} {platform.machine()} "
              f"{_os_release()}".strip(),
        # The two the placement selector matches on, as fields of their own:
        # a selector should not have to parse the display string above.
        "system": platform.system().lower(), "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "docker": _run(["docker", "version", "--format", "{{.Server.Version}}"])
        if shutil.which("docker") else "",
        # The daemon's OWN id, which is how the controller tells two VMs that
        # have worn one address apart — a rebuilt sandbox, a second machine
        # given the old one's IP. It used to read it over ssh with `docker
        # info`, and that reader went when the Docker tab stopped judging an
        # agent node by the controller's ssh (B111); reported here, the same
        # value arrives by the route the work already takes.
        "docker_id": _run(["docker", "info", "--format", "{{.ID}}"], timeout=15)
        if shutil.which("docker") else "",
        "gpu": gpu.splitlines()[0][:80] if gpu else "",
        "sshd": _sshd_listening(),
        "stores": _stores(state.get("stores"), used=True),
        "toolchains": tc,
        "store_dirs": store_dirs(state),
        # Which held recipes need system packages this machine lacks
        # (roadmap R51): read here, so the Tools tab and the row can say so
        # before a build fails on a missing library.
        "sysdeps": sysdeps_now(state),
        # The android system images the store holds, and the AVDs built on
        # them (roadmap #20). Not part of store_dirs: it reaches three levels
        # down and reads the data store's AVD configs as well.
        "images": sdk_images(state),
        # The configuration plane's reported half (docs/nodes.md §12): what
        # is mounted and from where, and the address this machine is on.
        # The row draws the operator's desired config against these.
        "sandbox": os.access(SANDBOX_BIN, os.X_OK),
        "mounts": mounts_now(),
        "network": network_now(),
        # Which of the machine's own tools a system job would go through.
        "distro": distro_now(),
        # The same report the controller makes for itself, so one store is
        # not described two ways (roadmap #19).
        "packages_versions": sdk_versions(state),
        "services": services_now(),
        # The session half (roadmap #24), as this process is holding it.
        "session": session_now(state),
    }


def session_now(state):
    """Whether this node runs sessions, and what a proxy needs to reach
    them: the ports, the account, whether the projects share is mounted at
    /workspace (a session without it has nothing to work on), and which
    Claude the session account has. Empty until the agent has tried once,
    so an old census never claims a node it has not measured."""
    if not SESSION:
        return {}
    out = dict(SESSION)
    out["workspace"] = os.path.ismount("/workspace")
    # ...and writable: a projects share mounted read-only was the right
    # arrangement for a Docker-only sandbox (nothing there wrote source), and
    # is the wrong one for a machine that runs sessions — Claude could not
    # save a file, and the home's transcripts link cannot be made on it.
    # The kernel answers EROFS for root too, so this is an honest probe.
    out["writable"] = out["workspace"] and os.access("/workspace", os.W_OK)
    home = out.pop("home", "")
    out.pop("bind", None)
    # Claude Code as the session account has it: its own ~/.local/bin (the
    # native installer's home) or ~/.npm-global/bin first, the system after.
    dirs = [os.path.join(home, ".local", "bin"), os.path.join(home, ".npm-global", "bin")] if home else []
    claude = ""
    for d in dirs + ["/usr/local/bin", "/usr/bin"]:
        exe = os.path.join(d, "claude")
        if os.access(exe, os.X_OK):
            # Through the probe, for the same reason the toolchains go through
            # it: a binary that is there and cannot START used to hand its own
            # crash text back as the version, forty characters of it, on the
            # doctor card. A claude that cannot run is a node that cannot hold
            # a session, so it reports as none and says why in the log.
            out_, dead = _probe([exe, "--version"], timeout=15)
            if dead:
                _probe_died("claude", exe, out_, dead)
            else:
                claude = out_.split("\n")[0][:40] or "installed"
            break
    out["claude"] = claude
    # This machine's boot, in the form bb-tty's boot_id() computes: a
    # terminal's URL carries the boot it was opened in, and bb-tty refuses
    # to START a session from a tab older than the machine's current run.
    # On a node that has to be the node's boot, not the controller's — the
    # controller stamps this into a node-bound terminal's URL for the page.
    out["boot"] = boot_id()
    # ...and how long ago that boot was. A network mount lands a moment
    # after the agent starts, so a census taken in that moment says the
    # share is missing; with the uptime beside it the controller can say
    # "just came up, not mounted yet" rather than "add the mount".
    out["up_s"] = uptime_s()
    return out


def uptime_s():
    """Seconds since this machine booted, or -1 when it cannot be read."""
    try:
        if platform.system() == "Darwin":
            m = re.search(r"sec\s*=\s*(\d+)", _run(["sysctl", "-n", "kern.boottime"]))
            return int(time.time() - int(m.group(1))) if m else -1
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return -1


def boot_id():
    """PID 1's start time paired with the host's boot time — the same pair,
    in the same shape, as the controller's server.boot_id and bb-tty's."""
    try:
        with open("/proc/1/stat") as f:
            start = f.read().rsplit(")", 1)[1].split()[19]
        with open("/proc/stat") as f:
            btime = next(l for l in f if l.startswith("btime ")).split()[1]
        return f"{btime}.{start}"
    except (OSError, IndexError, StopIteration):
        return ""


def services_now():
    """The managed services on this node and their state — today the
    Actions runner: registered as what, with which labels, and whether its
    listener is up. Read from the runner's own files, so a runner installed
    by hand reports the same way one installed from the tab does."""
    out = {}
    # Every runner on this node, one per git host, and the first of them
    # under the old single key too, for a controller from before the list.
    out["runners"] = [_runner_state(d, rec) for d, rec in runner_dirs()]
    out["actions-runner"] = out["runners"][0] if out["runners"] else {"installed": False}
    # Tailscale: whether it is here, this node's MagicDNS name (the funnel
    # URL is https://<that>), and which https ports are funnelled to which
    # local ports — read from tailscale's own status, so a funnel set by
    # hand reports the same as one set from the tab.
    ts = {"installed": bool(shutil.which(TAILSCALE_BIN) or os.access(TAILSCALE_BIN, os.X_OK)),
          "dns": "", "funnel": {}}
    if ts["installed"]:
        try:
            st = json.loads(_run([TAILSCALE_BIN, "status", "--json"], timeout=15) or "{}")
            ts["dns"] = str((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
            sv = json.loads(_run([TAILSCALE_BIN, "serve", "status", "--json"], timeout=15) or "{}")
            allow = sv.get("AllowFunnel") or {}
            for hostport, web in (sv.get("Web") or {}).items():
                if not allow.get(hostport):
                    continue
                https = hostport.rsplit(":", 1)[-1]
                for h in (web.get("Handlers") or {}).values():
                    m = re.search(r":(\d+)/?$", str(h.get("Proxy") or ""))
                    if m:
                        ts["funnel"][https] = int(m.group(1))
        except (ValueError, AttributeError):
            pass
    out["tailscale"] = ts
    return out


def mounts_now():
    """Every mount bb-sandbox manages, as it reads them: fstab's line and
    whether it is really mounted. Empty on a node with no bb-sandbox."""
    if not os.access(SANDBOX_BIN, os.X_OK):
        return []
    out = _run([SANDBOX_BIN, "list", "--json"])
    try:
        got = json.loads(out)
    except ValueError:
        return []
    got = [m for m in got if isinstance(m, dict)] if isinstance(got, list) else []
    # A mount fstab has and the kernel does not is tried once, here, and
    # the server's sentence kept beside it: "not mounted" on the row said
    # nothing about WHY, and the why was the whole story when the sandbox
    # moved to an address the host's export did not name — the mount was
    # refused with "access denied by server", nofail let the boot go on,
    # and nothing anywhere repeated the refusal. Root only: mount is.
    if os.geteuid() == 0:
        for m in got:
            if m.get("mounted") or not str(m.get("path") or "").startswith("/"):
                continue
            err = mount_try(m["path"])
            if err:
                m["error"] = err
            else:
                m["mounted"] = True
                m["real"] = m.get("source") or ""
    # A mount that is there and answers Stale file handle is worse than one
    # that is missing: every list of mounts calls it fine and every read
    # fails (roadmap R41; builderbot-dev's up failed on exactly this, 15
    # Sep). Remounting on this side does not help when the export was
    # re-created under it on the host, so the fix is named as the host's.
    for m in got:
        if m.get("mounted") and str(m.get("path") or "").startswith("/"):
            try:
                os.statvfs(m["path"])
            except OSError as e:
                if e.errno == errno.ESTALE:
                    m["stale"] = True
                    m["error"] = ("mounted, but the handle is stale: the export was re-created "
                                  "under it on the host; re-export it there (Unraid: the share's "
                                  "NFS setting off and on, or a pool the mover leaves alone), "
                                  "then Apply storage here")
    return got


def mount_try(path):
    """`mount PATH` from fstab, and what it said when it failed — the last
    line, which for NFS is the server's own reason. "" on success. Half a
    minute at most: an NFS server that is down keeps mount retrying in the
    foreground for two, and a census must not wait that out."""
    try:
        p = subprocess.run(["mount", path], capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return "mount gave no answer in 30s — the server is not reachable"
    except OSError as e:
        return str(e)[:200]
    if p.returncode == 0:
        return ""
    lines = [ln.strip() for ln in (p.stderr or p.stdout).splitlines() if ln.strip()]
    return (lines[-1] if lines else f"mount exited {p.returncode}")[:200]


def _client_allows(client, addr):
    """Whether one client entry of an NFS export ('*', a CIDR, an address,
    a hostname) admits addr. A name it cannot resolve is not a refusal."""
    c = client.strip()
    if not c or c.startswith("*") or c == "(everyone)":
        return True
    try:
        ip = ipaddress.ip_address(addr.split("/")[0])
        if "/" in c:
            return ip in ipaddress.ip_network(c, strict=False)
        return ipaddress.ip_address(c) == ip
    except ValueError:
        return True


def export_gaps(addr):
    """The NFS mounts in fstab whose server exports them to named clients
    that do not include addr — the address this node is about to move to.
    From `showmount -e` on each server; a server that does not answer, or
    a machine without showmount, contributes nothing rather than a refusal.
    The Unraid rule the docs prescribe names exactly one address, so a
    node that moves without the rule moving loses every share at once."""
    if not addr or not _have("showmount"):
        return []
    gaps, seen = [], {}
    for m in mounts_now():
        if not str(m.get("type") or "").startswith("nfs"):
            continue
        host, _, exp = str(m.get("source") or "").partition(":")
        if not host or not exp.startswith("/"):
            continue
        if host not in seen:
            seen[host] = _run(["showmount", "-e", "--no-headers", host], timeout=15)
        for line in seen[host].splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[0].startswith("Export list"):
                continue
            path, clients = parts[0], " ".join(parts[1:])
            if exp != path and not exp.startswith(path.rstrip("/") + "/"):
                continue
            if not any(_client_allows(c, addr) for c in clients.split(",")):
                gaps.append(f"{host} exports {path} to {clients}, not to {addr.split('/')[0]}")
    return gaps


def network_now():
    """The address the machine is on, as facts rather than as intent: the
    interface the default route leaves by, its addresses, the gateway, and
    the resolvers. From `ip -j`, which every distro this can run on has."""
    net = {"interface": "", "addresses": [], "gateway": "", "dns": []}
    try:
        routes = json.loads(_run(["ip", "-j", "route", "show", "default"]) or "[]")
        for r in routes:
            if isinstance(r, dict) and r.get("dev"):
                net["interface"] = str(r["dev"])[:32]
                net["gateway"] = str(r.get("gateway") or "")[:64]
                break
        if net["interface"]:
            addrs = json.loads(_run(["ip", "-j", "addr", "show", "dev", net["interface"]]) or "[]")
            for a in addrs:
                for i in (a.get("addr_info") or []) if isinstance(a, dict) else []:
                    if i.get("family") == "inet" and i.get("local"):
                        net["addresses"].append(f"{i['local']}/{i.get('prefixlen', 32)}")
    except (ValueError, OSError):
        pass
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    net["dns"].append(line.split()[1][:64])
    except (OSError, IndexError):
        pass
    return net


def _os_release():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------------------
# the machine's own tools
#
# A system job from the controller says WHAT — an address and a gateway, a
# mount, the packages a recipe needs — and never how: the spec is the same
# for every node. The how is this machine's, and it is detected here rather
# than assumed: which package manager is installed, and which service owns
# the network. Each backend renders the same desired state into its own
# commands, and the census reports which one a node has, so the row can say
# what a change would go through before it is sent. Debian/Ubuntu (apt,
# netplan) and the RHEL family (dnf, NetworkManager) are the two so far;
# another distribution is another backend here, not another job spec.

def _have(binary):
    """A binary on PATH, or an absolute path that is executable — the suite
    points the *_BIN settings at stubs by path."""
    return bool(shutil.which(binary)) or os.access(binary, os.X_OK)


def pkg_backend():
    """(name, query argv, install argv) for the package manager this machine
    has, keyed by the tool that answers whether a package is installed —
    since that is the half every check needs — and, where two families
    share one (rpm: dnf and zypper), by the installer beside it. The name
    is the key a recipe lists its system packages under (`system.apt`,
    `system.dnf`, ...). Empty when it is none of them, which is a machine
    this agent cannot install packages on: a recipe's packages are named
    for the owner there."""
    if _have(DPKG_BIN):
        return "apt", [DPKG_BIN, "-s"], [APT_BIN, "install", "-y", "-qq"]
    if _have(RPM_BIN) and _have(ZYPPER_BIN) and not _have(DNF_BIN):
        return "zypper", [RPM_BIN, "-q"], [ZYPPER_BIN, "-n", "-q", "install", "-y"]
    if _have(RPM_BIN) and _have(DNF_BIN):
        # Both, not rpm alone: rpm is an ordinary package on Arch and Alpine
        # (rpm-tools), and a node with it and no dnf is not a dnf machine.
        return "dnf", [RPM_BIN, "-q"], [DNF_BIN, "-y", "-q", "install"]
    if _have(PACMAN_BIN):
        return "pacman", [PACMAN_BIN, "-Q"], [PACMAN_BIN, "-S", "--noconfirm", "--needed"]
    if _have(APK_BIN):
        return "apk", [APK_BIN, "info", "-e"], [APK_BIN, "add", "-q"]
    if _have(XBPS_QUERY_BIN):
        return "xbps", [XBPS_QUERY_BIN], [XBPS_INSTALL_BIN, "-y"]
    if _have(EMERGE_BIN):
        # No query short of portage-utils: everything asked for is emerged
        # with --noreplace, which is portage's own "if missing".
        return "emerge", [], [EMERGE_BIN, "--quiet", "--noreplace"]
    if _have(BREW_BIN) or os.path.exists("/opt/homebrew/bin/brew"):
        # macOS: Homebrew, as the account that owns it — the agent runs as
        # that account on a guest node, which is what brew wants.
        brew = BREW_BIN if _have(BREW_BIN) else "/opt/homebrew/bin/brew"
        return "brew", [brew, "list", "--versions"], [brew, "install", "--quiet"]
    return "", [], []


class NetplanNet:
    """Debian and Ubuntu: one YAML file of our own under /etc/netplan, and
    `netplan apply`. The snapshot is the file's previous text (None when
    there was none), which is exactly what restore puts back."""
    name = "netplan"

    @staticmethod
    def available():
        return _have(NETPLAN_BIN)

    @staticmethod
    def ready(iface):
        return ""

    @staticmethod
    def render(iface, mode, addr, gw, dns):
        lines = ["network:", "  version: 2", "  ethernets:", f"    {iface}:"]
        if mode == "dhcp":
            lines.append("      dhcp4: true")
        else:
            lines += ["      dhcp4: false", f"      addresses: [{addr}]"]
            if gw:
                lines += ["      routes:", "        - to: default", f"          via: {gw}"]
            if dns:
                lines += ["      nameservers:", f"        addresses: [{', '.join(dns)}]"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def snapshot(iface):
        try:
            with open(os.path.join(NETPLAN_DIR, NETPLAN_FILE)) as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def same(desired, before):
        return desired == before

    @staticmethod
    def _write(text):
        path = os.path.join(NETPLAN_DIR, NETPLAN_FILE)
        if text is None:
            with contextlib.suppress(OSError):
                os.remove(path)
            return path
        os.makedirs(NETPLAN_DIR, exist_ok=True)
        with open(path, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
        return path

    def apply(self, agent, job, iface, desired, before):
        path = self._write(desired)
        job.say(f"wrote {path}:\n{desired}")
        job.flush()                      # the last words before the cord is cut
        return agent._sh(job, [NETPLAN_BIN, "apply"])

    def restore(self, agent, job, iface, before):
        self._write(before)
        agent._sh(job, [NETPLAN_BIN, "apply"])


class NetworkManagerNet:
    """The RHEL family (and any machine NetworkManager runs): the ipv4 keys
    of the connection on the interface, through nmcli, then `con up` to
    make it live. The snapshot is those keys as they were, and restore is
    the same modify with the old values."""
    name = "networkmanager"
    FIELDS = ("ipv4.method", "ipv4.addresses", "ipv4.gateway", "ipv4.dns",
              "ipv4.ignore-auto-dns")

    @staticmethod
    def available():
        return _have(NMCLI_BIN) and _run([NMCLI_BIN, "-t", "-g", "RUNNING", "general"]) == "running"

    @staticmethod
    def conn(iface):
        # By exit code, not by output: for a device that does not exist
        # nmcli prints "Error: Device 'x' not found." and exits 10, and
        # _run would hand that sentence back as the connection's name.
        try:
            p = subprocess.run([NMCLI_BIN, "-t", "-g", "GENERAL.CONNECTION", "device", "show", iface],
                               capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        return p.stdout.strip() if p.returncode == 0 else ""

    def ready(self, iface):
        if not self.conn(iface):
            return (f"NetworkManager has no connection on {iface} — once, at the console: "
                    f"nmcli con add type ethernet ifname {iface} con-name {iface}")
        return ""

    @staticmethod
    def render(iface, mode, addr, gw, dns):
        if mode == "dhcp":
            return {"ipv4.method": "auto", "ipv4.addresses": "", "ipv4.gateway": "",
                    "ipv4.dns": "", "ipv4.ignore-auto-dns": "no"}
        return {"ipv4.method": "manual", "ipv4.addresses": addr, "ipv4.gateway": gw,
                "ipv4.dns": ",".join(dns), "ipv4.ignore-auto-dns": "yes" if dns else "no"}

    def snapshot(self, iface):
        con = self.conn(iface)
        return {"_con": con, **{f: _run([NMCLI_BIN, "-t", "-g", f, "con", "show", con])
                                for f in self.FIELDS}}

    @staticmethod
    def same(desired, before):
        return all((before or {}).get(k, "").strip() == v for k, v in desired.items())

    def apply(self, agent, job, iface, desired, before):
        con = before["_con"]
        argv = [NMCLI_BIN, "con", "mod", con]
        for k in self.FIELDS:
            argv += [k, desired[k]]
        job.say(f"NetworkManager connection {con!r} on {iface}: "
                + " ".join(f"{k}={desired[k] or '-'}" for k in self.FIELDS) + "\n")
        job.flush()
        rc = agent._sh(job, argv)
        return rc or agent._sh(job, [NMCLI_BIN, "con", "up", con])

    def restore(self, agent, job, iface, before):
        con = before["_con"]
        argv = [NMCLI_BIN, "con", "mod", con]
        for k in self.FIELDS:
            argv += [k, before.get(k, "")]
        agent._sh(job, argv)
        agent._sh(job, [NMCLI_BIN, "con", "up", con])


class FilesNet:
    """The shape shared by the backends that are files plus a reload: render
    the desired state as {path: text-or-None}, snapshot the same paths as
    they are, write, run the reload, and restore by writing the snapshot
    back and reloading again. None for a path means "not there", both in
    what is wanted and in what was found, so a file this created is removed
    again on revert."""
    name = ""

    def ready(self, iface):
        return ""

    @staticmethod
    def same(desired, before):
        return desired == before

    def snapshot(self, iface):
        out = {}
        for path in self.paths(iface):
            try:
                with open(path) as f:
                    out[path] = f.read()
            except OSError:
                out[path] = None
        return out

    @staticmethod
    def _write(files):
        for path, text in files.items():
            if text is None:
                with contextlib.suppress(OSError):
                    os.remove(path)
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                os.fchmod(f.fileno(), 0o644)
                f.write(text)

    def apply(self, agent, job, iface, desired, before):
        self._write(desired)
        for path, text in desired.items():
            job.say(f"wrote {path}:\n{text}" if text is not None else f"removed {path}\n")
        job.flush()                      # the last words before the cord is cut
        return self.reload(agent, job, iface)

    def restore(self, agent, job, iface, before):
        self._write(before)
        self.reload(agent, job, iface)


class NetworkdNet(FilesNet):
    """systemd-networkd (Arch and its derivatives on a server install, and
    anything else that chose it): one .network file of our own for the
    interface, and `networkctl reload`."""
    name = "systemd-networkd"

    @staticmethod
    def available():
        return _have(NETWORKCTL_BIN) and os.path.isdir(NETWORKD_DIR) \
            and _run(["systemctl", "is-active", "systemd-networkd"]) == "active"

    @staticmethod
    def paths(iface):
        # networkd applies the FIRST .network file, in lexical order, that
        # matches a device and ignores the rest; the distribution's own sit
        # at 10- and 20-, so ours sorts ahead of them or it is never read
        # — and the job would then report success with the old address.
        return [os.path.join(NETWORKD_DIR, f"00-builderbot-{iface}.network")]

    def render(self, iface, mode, addr, gw, dns):
        lines = ["[Match]", f"Name={iface}", "", "[Network]"]
        if mode == "dhcp":
            lines.append("DHCP=yes")
        else:
            lines.append(f"Address={addr}")
            if gw:
                lines.append(f"Gateway={gw}")
            lines += [f"DNS={d}" for d in dns]
        return {self.paths(iface)[0]: "\n".join(lines) + "\n"}

    def reload(self, agent, job, iface):
        rc = agent._sh(job, [NETWORKCTL_BIN, "reload"])
        return rc or agent._sh(job, [NETWORKCTL_BIN, "reconfigure", iface])


class IfupdownNet(FilesNet):
    """/etc/network/interfaces — Debian without netplan, Raspberry Pi OS
    before NetworkManager, Alpine's ifupdown-ng. The interface's own stanza
    in that file is replaced with ours (the rest of the file is kept as it
    is), then the interface is cycled with ifdown/ifup."""
    name = "ifupdown"
    MARK = "# BuilderBot: this interface, as the controller set it"

    @staticmethod
    def available():
        return _have(IFUP_BIN) and os.path.isfile(INTERFACES_FILE)

    @staticmethod
    def paths(iface):
        return [INTERFACES_FILE]

    @staticmethod
    def _without(text, iface):
        """The file minus the interface's stanza: its `auto`/`allow-*`
        line and its `iface` block up to the next top-level keyword."""
        out, skipping = [], False
        for line in text.splitlines():
            if line.strip() == IfupdownNet.MARK:
                continue                  # ours from last time: rendered again below
            w = line.split()
            top = bool(w) and not line[0].isspace()
            if top and w[0] in ("iface",) and len(w) > 1 and w[1] == iface:
                skipping = True
                continue
            if top and w[0] in ("auto", "allow-hotplug") and iface in w[1:]:
                rest = [x for x in w[1:] if x != iface]
                if rest:
                    out.append(w[0] + " " + " ".join(rest))
                continue
            if top and w[0] in ("iface", "auto", "allow-hotplug", "mapping", "source", "source-directory"):
                skipping = False
            if not skipping:
                out.append(line)
        return "\n".join(out).rstrip("\n") + ("\n" if out else "")

    def render(self, iface, mode, addr, gw, dns):
        try:
            with open(INTERFACES_FILE) as f:
                base = self._without(f.read(), iface)
        except OSError:
            base = ""
        lines = [self.MARK, f"auto {iface}"]
        if mode == "dhcp":
            lines.append(f"iface {iface} inet dhcp")
        else:
            lines.append(f"iface {iface} inet static")
            lines.append(f"    address {addr}")
            if gw:
                lines.append(f"    gateway {gw}")
            if dns:
                lines.append(f"    dns-nameservers {' '.join(dns)}")
        return {INTERFACES_FILE: base + ("\n" if base and not base.endswith("\n\n") else "")
                + "\n".join(lines) + "\n"}

    def reload(self, agent, job, iface):
        agent._sh(job, [IFDOWN_BIN, iface])
        return agent._sh(job, [IFUP_BIN, iface])


class WickedNet(FilesNet):
    """SUSE Leap's wicked: ifcfg-IFACE for the address, ifroute-IFACE for
    the default route, and the static resolvers in netconfig's config, then
    `wicked ifreload` and `netconfig update`."""
    name = "wicked"

    @staticmethod
    def available():
        return _have(WICKED_BIN) and os.path.isdir(SYSCONFIG_NET_DIR) \
            and _run(["systemctl", "is-active", "wicked"]) == "active"

    @staticmethod
    def paths(iface):
        return [os.path.join(SYSCONFIG_NET_DIR, f"ifcfg-{iface}"),
                os.path.join(SYSCONFIG_NET_DIR, f"ifroute-{iface}"),
                os.path.join(SYSCONFIG_NET_DIR, "config")]

    def render(self, iface, mode, addr, gw, dns):
        ifcfg, ifroute, config = self.paths(iface)
        out = {}
        if mode == "dhcp":
            out[ifcfg] = "STARTMODE='auto'\nBOOTPROTO='dhcp'\n"
            out[ifroute] = None
        else:
            out[ifcfg] = f"STARTMODE='auto'\nBOOTPROTO='static'\nIPADDR='{addr}'\n"
            out[ifroute] = f"default {gw} - {iface}\n" if gw else None
        # netconfig's config is a shared file: only its static-DNS line moves.
        try:
            with open(config) as f:
                text = f.read()
        except OSError:
            text = ""
        kept = [l for l in text.splitlines() if not l.startswith("NETCONFIG_DNS_STATIC_SERVERS=")]
        kept.append(f'NETCONFIG_DNS_STATIC_SERVERS="{" ".join(dns) if mode == "static" else ""}"')
        out[config] = "\n".join(kept) + "\n"
        return out

    def reload(self, agent, job, iface):
        rc = agent._sh(job, [WICKED_BIN, "ifreload", iface])
        agent._sh(job, ["netconfig", "update", "-f"])
        return rc


class DhcpcdNet(FilesNet):
    """dhcpcd on its own (Void's default): a static address is a marked
    block in dhcpcd.conf for the interface, and the daemon is restarted."""
    name = "dhcpcd"
    MARK = "# BuilderBot: "

    @staticmethod
    def available():
        return _have("dhcpcd") and os.path.isfile(DHCPCD_CONF) and bool(_run(["pgrep", "-x", "dhcpcd"]))

    @staticmethod
    def paths(iface):
        return [DHCPCD_CONF]

    def render(self, iface, mode, addr, gw, dns):
        try:
            with open(DHCPCD_CONF) as f:
                text = f.read()
        except OSError:
            text = ""
        out, skipping = [], False
        for line in text.splitlines():
            if line.rstrip() == self.MARK + iface:
                skipping = True
                continue
            if skipping and line.startswith(self.MARK + "end"):
                skipping = False
                continue
            if not skipping:
                out.append(line)
        base = "\n".join(out).rstrip("\n")
        if mode == "static":
            block = [self.MARK + iface, f"interface {iface}", f"static ip_address={addr}"]
            if gw:
                block.append(f"static routers={gw}")
            if dns:
                block.append(f"static domain_name_servers={' '.join(dns)}")
            block.append(self.MARK + "end")
            base = (base + "\n\n" if base else "") + "\n".join(block)
        return {DHCPCD_CONF: base + "\n"}

    def reload(self, agent, job, iface):
        for argv in (["sv", "restart", "dhcpcd"], ["rc-service", "dhcpcd", "restart"],
                     ["systemctl", "restart", "dhcpcd"]):
            if _have(argv[0]):
                return agent._sh(job, argv)
        return agent._sh(job, ["dhcpcd", "-n", iface])


def net_backend():
    """The service that owns this machine's network, or None. In the order
    that resolves a machine with two of them: netplan renders to whichever
    of NetworkManager and networkd is under it, so a file of ours beside
    its files is the change it expects; NetworkManager over networkd where
    both run; the file-based ones only when nothing above them is running."""
    for b in (NetplanNet(), NetworkManagerNet(), NetworkdNet(), WickedNet(),
              IfupdownNet(), DhcpcdNet()):
        if b.available():
            return b
    return None


def controller_ip(url):
    """The address the controller's hostname resolves to now — IPv4 first,
    the way the provisioner chose it — or "" when it does not resolve."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not host:
        return ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return ""
    for fam, _t, _p, _c, sa in infos:
        if fam == socket.AF_INET:
            return sa[0]
    return infos[0][4][0] if infos else ""


def init_now():
    """Which init runs this machine — what a service of ours is, there."""
    if platform.system() == "Darwin":
        return "launchd"
    if os.path.isdir("/run/systemd/system"):
        return "systemd"
    if _have("rc-service"):
        return "openrc"
    if os.path.isdir("/etc/sv") and _have("sv"):
        return "runit"
    return ""


def distro_now():
    """What this machine is, as the facts the agent picks its commands by:
    the distribution and its family from /etc/os-release, its package
    manager, and its network backend. In the census, so the controller and
    the row can say which tools a change would go through."""
    d = {"id": "", "family": "", "pretty": "", "pkg": "", "network": "", "init": ""}
    like = ""
    if platform.system() == "Darwin":
        # No os-release on a Mac; sw_vers is the same fact. Its own family:
        # brew for packages, no network backend (a Mac's address is its
        # owner's), launchd for a service.
        brew = _have(BREW_BIN) or os.path.exists("/opt/homebrew/bin/brew")
        d.update({"id": "macos", "family": "macos",
                  "pretty": ("macOS " + _run(["sw_vers", "-productVersion"])).strip(),
                  "pkg": "brew" if brew else "", "network": "", "init": "launchd"})
        return d
    try:
        with open(OS_RELEASE, errors="replace") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                v = v.strip().strip('"')
                if k == "ID":
                    d["id"] = v[:32]
                elif k == "ID_LIKE":
                    like = v
                elif k == "PRETTY_NAME":
                    d["pretty"] = v[:80]
    except OSError:
        pass
    # A derivative lands with its parent through ID_LIKE: Mint, Pop!_OS and
    # Kali with Debian; Fedora, CentOS Stream, Rocky and Alma with RHEL;
    # Manjaro, EndeavourOS and CachyOS with Arch; Leap and Tumbleweed with
    # SUSE. The independents are their own family.
    ids = {d["id"], *like.split()}
    for family, members in (("debian", {"debian", "ubuntu", "raspbian"}),
                            ("rhel", {"rhel", "fedora", "centos", "rocky", "almalinux"}),
                            ("arch", {"arch", "archlinux", "manjaro"}),
                            ("suse", {"suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}),
                            ("alpine", {"alpine"}), ("void", {"void"}), ("gentoo", {"gentoo"}),
                            ("nixos", {"nixos"}), ("slackware", {"slackware"})):
        if ids & members:
            d["family"] = family
            break
    else:
        d["family"] = d["id"]
    d["pkg"] = pkg_backend()[0]
    b = net_backend()
    d["network"] = b.name if b else ""
    d["init"] = init_now()
    return d


class Sampler:
    """CPU as a percentage over the interval since the last sample — which
    is the poll interval, so the number on the row is 'the last 25 seconds'
    and not an instant nobody can act on."""

    def __init__(self):
        self.last = self._stat()

    @staticmethod
    def _stat():
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().split()[1:]]
            return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)
        except (OSError, ValueError, IndexError):
            return 0, 0

    def sample(self, state, running):
        now = self._stat()
        dt, di = now[0] - self.last[0], now[1] - self.last[1]
        self.last = now
        tot, used = _mem()
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = 0.0
        return {"cpu_pct": round(100.0 * (dt - di) / dt, 1) if dt > 0 else 0.0,
                "load1": round(load1, 2), "mem_mb": tot, "mem_used_mb": used,
                "stores": _stores(state.get("stores")), "running": running}


# ---------------------------------------------------------------------------
# node.json

def load_state():
    try:
        with open(NODE_JSON) as f:
            return json.load(f)
    except OSError as e:
        raise SystemExit(f"{NODE_JSON} is missing — enroll this node first: "
                         "builderbot-agent enroll --controller URL --token …") from e
    except ValueError as e:
        raise SystemExit(f"{NODE_JSON} is not JSON ({e}); enroll again") from e


def save_state(state):
    d = os.path.dirname(NODE_JSON)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = NODE_JSON + ".tmp"
    with open(tmp, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(state, f, indent=2)
    os.replace(tmp, NODE_JSON)


# ---------------------------------------------------------------------------
# jobs

class Job(threading.Thread):
    """One job, on its own thread, reporting as it goes.

    Output is posted in batches by sequence number; a batch the controller
    did not acknowledge stays in `pending` and goes with the next one, so
    nothing is lost across a controller restart and nothing is doubled (the
    controller drops a sequence it already has). The result is retried with
    backoff until acknowledged — this thread is the record of the job until
    the controller has it.
    """

    def __init__(self, agent, job):
        super().__init__(daemon=True, name=job["id"])
        self.agent, self.job = agent, job
        self.pending, self.seq = [], 0
        self.lock = threading.Lock()
        # A cancel is a fact about the job on the controller's row, and it
        # reaches here two ways: named in a work reply, or as `cancel: true`
        # on the reply to a log post. Either sets this; the child is killed
        # from the exec loop, and the result says "canceled" rather than
        # "failed" so the row does not read as the command's own fault.
        self.canceled = False
        self.proc = None
        self.outputs = []        # what the job left behind, for the result
        self.pending_step = ""   # the word for the row, sent with the next log
        # The write end of this job's pty, for a job that needs one. Only a
        # conversation does: `claude auth login` prints a URL and waits for a
        # code, and a pipe would leave the prompt sitting in a buffer nobody
        # ever sees. None for every other job, and the log loop checks.
        self.tty = None

    def cancel(self):
        self.canceled = True
        p = self.proc
        if p is not None and p.poll() is None:
            self._kill(p)

    def step(self, name):
        """What this job is doing now, for the row. Rides the next log post
        rather than taking a verb of its own — the agent is already talking
        to the controller every half second while a job runs."""
        with self.lock:
            self.pending_step = str(name)[:60]

    def say(self, text):
        # One line that alone exceeds a body would be refused forever, and
        # everything behind it with it; split rather than let that happen.
        with self.lock:
            for i in range(0, len(text), 32 * 1024):
                self.seq += 1
                self.pending.append({"seq": self.seq, "chunk": text[i:i + 32 * 1024]})

    BATCH = 40 * 1024      # under the controller's 64KB body cap, with headroom

    def flush(self):
        """Post what is pending, in bodies the controller will accept. A job
        that ran on while the controller was down can have megabytes waiting;
        they go in order, a slice at a time, and stop at the first refusal."""
        while True:
            with self.lock:
                batch, size = [], 0
                while self.pending and size < self.BATCH:
                    batch.append(self.pending.pop(0))
                    size += len(batch[-1]["chunk"])
            if not batch:
                with self.lock:
                    step, self.pending_step = self.pending_step, ""
                if step:
                    self.agent.ctl.call("log", {"job": self.job["id"], "chunks": [],
                                                "step": step}, timeout=20)
                return True
            with self.lock:
                step, self.pending_step = self.pending_step, ""
            body = {"job": self.job["id"], "chunks": batch}
            if step:
                body["step"] = step
            st, r = self.agent.ctl.call("log", body, timeout=20)
            if st != 200:
                with self.lock:
                    self.pending = batch + self.pending
                return False
            if r.get("cancel") and not self.canceled:
                self.cancel()
            # ...and anything the controller wants typed INTO this job. The
            # only downward channel a running job has is this reply, which is
            # why `cancel` has always ridden it; a sign-in's code rides it the
            # same way. One line, and only a job that opened a pty has
            # anywhere to put it.
            if r.get("input") and self.tty is not None:
                with contextlib.suppress(OSError):
                    os.write(self.tty, (str(r["input"]) + "\n").encode())

    def run(self):
        spec = self.job.get("spec") or {}
        error = ""
        # What this job is, before it is anything else: a job that fails
        # without having said a word leaves the row with an exit code and an
        # empty log, and there is nothing to look at but the number. Every
        # path below can now only ADD to this line.
        self.say(f"{self.job.get('type') or 'exec'}"
                 + (f": {spec['apply']}" if spec.get("apply") else "") + "\n")
        try:
            if self.job.get("type") == "self-update":
                state, code = self.agent.self_update(self, spec)
            elif self.job.get("type") == "system":
                state, code = self.agent.system(self, spec)
            elif self.job.get("type") == "compose":
                state, code = self.agent.compose(self, spec)
            elif self.job.get("type") == "package":
                state, code = self.agent.package(self, spec)
                # A recipe landed or left: the session environment is built
                # from the store's layout at ttyd's start, so a session
                # opened after this would still not find the new tool on
                # PATH (lint-tools on bb-sandbox, measured). The loop
                # restarts the ttyds; tmux sessions survive it.
                self.agent.session_renew()
            elif self.job.get("type") == "cache-clear":
                state, code = self.agent.cache_clear(self, spec)
            elif self.job.get("type") == "claude-login":
                state, code = self.claude_login(spec)
            elif self.job.get("type") == "tell":
                state, code = self.agent.tell(self, spec)
            else:
                state, code = self.exec(spec)
        except Exception as e:                       # noqa: BLE001 — reported, not raised
            self.say(f"agent error: {type(e).__name__}: {e}\n")
            state, code, error = "failed", 70, f"agent error: {type(e).__name__}"
        if self.canceled:
            state, error = "canceled", "stopped by the operator"
        elif state == "failed" and not error:
            error = f"exit {code}"
        # Door 5: keep trying. The controller may be gone for a while; the
        # answer waits here, with backoff, until it is taken.
        delay = 1
        while True:
            if self.flush():
                st, _ = self.agent.ctl.call(
                    "result", {"job": self.job["id"], "state": state, "exit": code,
                               "error": error, "outputs": self.outputs},
                    timeout=20)
                if st == 200:
                    break
                if st in (400, 401, 403, 404):
                    log(f"{self.job['id']}: result refused ({st}); dropping it")
                    break
            time.sleep(delay)
            delay = min(delay * 2, 60)
        self.agent.finished(self)
        if state == "succeeded" and self.job.get("type") == "self-update":
            self.agent.reexec()

    def claude_login(self, spec):
        """`claude auth login` on this machine, under a pty, as the SESSION
        account (roadmap R47).

        A job of its own and not an exec, for two reasons that both matter.
        It drops to the session account rather than the enrolled job one —
        those are different accounts on purpose, and the credential has to
        land in the home a Claude session will read it from, owned by the
        account that will read it. And it wants a PTY: the flow prints a URL
        and then a prompt with no newline after it, which down a pipe sits in
        a buffer nobody ever sees.

        The conversation is the job's own log going up and `input` on the
        reply to a log post coming down — the same channel `cancel` has used
        since the start. Nothing new is opened toward this machine.
        """
        who_name = self.agent.session_account()
        env = dict(sdk_env(self.agent.state))
        env.update({"BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
                    "BUILDERBOT_JOB": self.job["id"]})
        try:
            who = self.agent.as_user(env, who_name)
        except RuntimeError as e:
            self.say(f"refused: {e}\n")
            return "failed", 78
        if not who_name:
            self.say("refused: this node reports no session account, so there is "
                     "no home for a Claude login to land in\n")
            return "failed", 78
        into = self.agent.bundle(self, who)
        if not into:
            return "failed", 69
        # The BuilderBot account, so the bundle's own user_home resolves the
        # same per-account home bb-tty gives a session here. Resolved there
        # rather than here: one implementation of "where does this account
        # live on this machine", and it is that one.
        env["BUILDER_HOME"] = env.get("HOME", "")
        env["BB_ACCOUNT_UID"] = str(spec.get("uid") or "")
        argv = ["bash", os.path.join(into, "scripts", "bb"), "login", "--flow"]
        master, slave = pty.openpty()
        self.say("signing in to Claude on this machine — the URL follows\n")
        try:
            self.proc = subprocess.Popen(
                argv, stdin=slave, stdout=slave, stderr=slave,
                cwd="/tmp", env=env, start_new_session=True, close_fds=True, **who)
        except (OSError, ValueError) as e:
            os.close(master), os.close(slave)
            self.say(f"could not start the sign-in: {e}\n")
            return "failed", 70
        os.close(slave)
        self.tty = master
        deadline = time.time() + int(spec.get("timeout") or 900)
        try:
            while True:
                if time.time() > deadline:
                    self.say("the sign-in was not finished in time\n")
                    self.cancel()
                    return "failed", 75
                try:
                    r, _, _ = select.select([master], [], [], 0.5)
                except (OSError, ValueError):
                    break
                if r:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.say(chunk.decode("utf-8", "replace"))
                if self.proc.poll() is not None:
                    break
        finally:
            self.tty = None
            with contextlib.suppress(OSError):
                os.close(master)
        code = self.proc.wait()
        return ("succeeded" if code == 0 else "failed"), code

    def exec(self, spec):
        need = spec.get("requires") or []
        if isinstance(need, str):
            need = [need]
        held = set(self.agent.state.get("capabilities") or [])
        missing = [c for c in need if c not in held]
        if missing or "system" in need:
            # Door 7, in one line: the node refuses what it was not enrolled
            # to do, and says which capability was asked for. "system" is not
            # a capability an exec can ask for at all — root work is its own
            # job type, and only the configuration plane queues it.
            self.say(f"refused: this node is not enrolled for {', '.join(missing or need)}\n")
            return "failed", 77
        argv = [str(a) for a in (spec.get("argv") or [])]
        stores = self.agent.state.get("stores") or {}
        cwd = spec.get("cwd") or stores.get("data") or "/tmp"
        # The node's own toolchains, for EVERY job — a build is the case this
        # whole store exists for, and it was the one case that did not get
        # them (bug #45).
        env = dict(sdk_env(self.agent.state))
        env.update({"BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
                    "BUILDERBOT_JOB": self.job["id"]})
        who = self.agent.drop_privileges(env)
        bbv = [str(a) for a in (spec.get("bb") or [])]
        if bbv:
            # A bb verb, run from the bundle this controller ships with the
            # store as its SDK (docs/nodes.md phase 9): `bb emu start` on a
            # node is this. In a directory of the project's under the data
            # store, so what the verb writes has somewhere to be collected from.
            into = self.agent.bundle(self, who)
            if not into:
                return "failed", 69
            argv = ["bash", os.path.join(into, "scripts", "bb")] + bbv
            project = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("project") or "project"))
            cwd = os.path.join(stores.get("data") or "/tmp", "emu", project)
            self.agent.own_dir(cwd, who)
            env["BB_PROJECT"] = str(spec.get("project") or "")
        if not argv:
            self.say("refused: empty argv\n")
            return "failed", 64
        if not os.path.isdir(cwd):
            cwd = "/tmp"
        for k, v in (spec.get("env") or {}).items():
            env[str(k)] = str(v)
        # Inputs: files from the project's dist/, fetched into the working
        # directory by name — an APK for the emulator to install.
        for f in (spec.get("files") or [])[:8]:
            name = os.path.basename(str(f))
            # Into this node's artifact store for the project, and used from
            # there: a second emulator run on the same build copies nothing,
            # and on a node across a slow link that is the difference the
            # store exists for. The size decides whether it is the same file
            # — the controller sends no digest for a dist/ path.
            keep = self.agent.artifact_dir(spec.get("project"), who)
            dest = os.path.join(keep or cwd, name)
            want = spec.get("sizes", {}).get(str(f)) if isinstance(spec.get("sizes"), dict) else None
            if keep and os.path.isfile(dest) and want and os.path.getsize(dest) == want:
                self.say(f"{f} is already on this node ({want} bytes)\n")
            else:
                st, _ = self.agent.ctl.fetch(
                    f"file?job={self.job['id']}&path={urllib.parse.quote(str(f))}", dest)
                if st != 200:
                    self.say(f"could not fetch {f} from the controller ({st})\n")
                    return "failed", 69
                if who:
                    with contextlib.suppress(OSError):
                        os.chown(dest, who["user"], who["group"])
                self.say(f"fetched {f} ({os.path.getsize(dest)} bytes)"
                         + (f" into {keep}" if keep else "") + "\n")
            if keep and os.path.dirname(dest) != cwd:
                link = os.path.join(cwd, name)
                with contextlib.suppress(OSError):
                    if os.path.lexists(link):
                        os.remove(link)
                    os.symlink(dest, link)
        # A job with a source runs in a workspace of its own (docs/nodes.md
        # §6): the snapshot, materialized under the data store, with the
        # project's persistent cache beside it in the environment.
        src = self.job.get("source") or {}
        ws = None
        if src.get("digest"):
            ws = self.agent.materialize(self, src, who)
            if ws is None:
                return "failed", 66
            cwd = ws
            env["BUILDERBOT_WORKSPACE"] = ws
            project = re.sub(r"[^A-Za-z0-9._-]", "_", str(src.get("project") or spec.get("project") or "project"))
            cache = os.path.join(stores.get("cache") or "/tmp", project)
            self.agent.own_dir(cache, who)
            env["BUILDERBOT_CACHE"] = cache
            env["BUILDERBOT_PROJECT"] = project
            self.say(f"workspace {ws} ({src.get('files', '?')} files); cache {cache}\n")
        try:
            timeout = float(spec.get("timeout") or 3600)
        except (TypeError, ValueError):
            timeout = 3600
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True,
                                 **who)
        except OSError as e:
            self.say(f"could not start {argv[0]}: {e}\n")
            return "failed", 126
        self.proc = p
        if self.canceled:                 # asked to stop while it was starting
            self._kill(p)
        # The pipe is read on its own thread, and this one posts on a clock.
        # Reading and posting on one thread meant a job that printed a line
        # and then worked in silence never posted the line — readline blocked
        # until the next one — so the row sat at "assigned" with nothing in
        # its log, and a cancel sent on the log reply could not arrive.
        def pump():
            try:
                for line in p.stdout:
                    self.say(line.decode("utf-8", "replace"))
            except (OSError, ValueError):
                pass                      # the pipe went with the process
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline = time.time() + timeout
        killed = False
        while reader.is_alive():
            reader.join(0.5)
            if self.pending:
                self.flush()
            if time.time() > deadline and not killed:
                self.say(f"timed out after {int(timeout)}s — killing it\n")
                self._kill(p)
                killed = True
        p.wait()
        self.proc = None
        if self.canceled:
            self.say("stopped\n")
            state, code = "canceled", 130
        elif killed:
            state, code = "failed", 124
        else:
            state, code = ("succeeded" if p.returncode == 0 else "failed"), p.returncode
        if ws is not None:
            self.agent.finish_workspace(self, ws, spec, state)
        elif state == "succeeded" and spec.get("outputs"):
            # No snapshot, but outputs asked for: what a bb verb wrote in
            # its directory comes back the same way a build's do.
            self.agent.deliver(self, cwd, spec.get("outputs") or [])
        return state, code

    @staticmethod
    def _kill(p):
        # The whole session, not just the leader: a build spawns children
        # that would otherwise keep the pipe open and the job "running".
        try:
            os.killpg(p.pid, 15)
            time.sleep(2)
            os.killpg(p.pid, 9)
        except OSError:
            pass


class Agent:
    def __init__(self, state):
        self.state = state
        self.ctl = Controller(state["controller"], state["token"], state.get("pin", ""))
        self.jobs = {}
        self.lock = threading.Lock()
        self.sampler = Sampler()
        self.poll = 25
        self.hello_at = 0
        self.controller_digest = ""
        self.warned_caps = False
        # The session half (roadmap #24): the two ttyd processes, the bundle
        # they run bb-tty from, and when the last start was tried.
        self.ttyd = []
        self.session_bundle = ""          # the digest the ttyds run from
        self.session_digest = ""          # the digest bundle() last fetched
        self.session_tried = 0
        self.session_stale = ""           # a newer bundle's directory, for the loop to restart onto
        self.session_bound = ""           # the address the ttyds were bound to, to notice it moving
        self.session_mount = None         # (mounted, writable) as the last census said, to notice it moving
        self.fw_checked = 0.0             # when the session ports' firewall rule was last checked
        # The runner as a child of this process where there is no systemd:
        # run.sh in the foreground, supervised here.
        self.runner_procs = {}            # runner directory -> its process
        self.runner_tried = {}            # runner directory -> when it was last started

    # -- privilege ---------------------------------------------------------
    def drop_privileges(self, env):
        """Popen keywords that make the child the enrolled account — empty
        when there is nothing to drop (not root, or enrolled as root on
        purpose). Popen's own user/group/extra_groups rather than a
        preexec_fn: this process has job threads, and a fork hook that runs
        between fork and exec can deadlock on a lock another thread held."""
        return self.as_user(env, self.state.get("user") or "")

    def as_user(self, env, user):
        """The same, for a named account: jobs drop to the enrolled one,
        sessions to the session one (roadmap #24), and they are different
        accounts on purpose."""
        if os.geteuid() != 0 or not user or user == "root":
            return {}
        import grp
        import pwd
        try:
            pw = pwd.getpwnam(user)
        except KeyError as e:
            raise RuntimeError(f"enrolled account {user!r} does not exist here") from e
        env.update({"HOME": pw.pw_dir, "USER": user, "LOGNAME": user})
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        return {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": groups}

    # -- the channel -------------------------------------------------------
    def hello(self):
        # `running` is the list of job ids this process still holds. The
        # controller reconciles against it: a job its row says is running
        # here that this agent does not know was lost with a restart, and is
        # failed there rather than left running forever (docs/nodes.md §9).
        # The layout's one standing rule, kept by the running agent (never
        # by `enroll`, which may run with a store it cannot write yet).
        try:
            share_images((self.state.get("stores") or {}).get("packages") or "")
            fix_flat_links((self.state.get("stores") or {}).get("packages") or "")
        except OSError as e:
            log(f"packages store: could not share the images ({e})")
        c = census(self.state)
        se = c.get("session") or {}
        self.session_mount = (bool(se.get("workspace")), bool(se.get("writable"))) if se else None
        st, r = self.ctl.call("hello", {"census": c,
                                        "version": AGENT_VERSION,
                                        "digest": own_digest(),
                                        "running": self.running_ids()}, timeout=30)
        if st == 200:
            self.hello_at = time.time()
            self.poll = int(r.get("poll") or 25)
            self.controller_digest = (r.get("agent") or {}).get("digest") or ""
            # Where packages land, from the controller's catalog. Kept on the
            # record so a job started before the next hello still has it, and
            # only replaced when the controller actually sends one — an older
            # controller says nothing and this node keeps its built-in answer.
            lay = r.get("layout")
            if isinstance(lay, list) and lay and lay != self.state.get("layout"):
                self.state["layout"] = lay
                save_state(self.state)
            # The idle rule for Claude sessions (the controller's idle.py),
            # kept in node.json so it is enforced here while the controller
            # is down — a node's sessions outlive a controller restart on
            # purpose; the rule about when they end must not.
            im = r.get("session_idle_minutes")
            if isinstance(im, int) and im >= 0 and im != self.state.get("session_idle_minutes"):
                self.state["session_idle_minutes"] = im
                save_state(self.state)
                log(f"sessions: idle rule is {im} minute(s)" if im else "sessions: no idle rule")
            n = r.get("node") or {}
            # The row's capabilities are the controller's claim; the ones
            # this node ENFORCES are the ones it enrolled with, kept in
            # node.json. Logged when they differ so the disagreement is
            # visible on the box, and never silently adopted.
            claimed = set(n.get("capabilities") or [])
            held = set(self.state.get("capabilities") or [])
            # Once per process, not per hello: a node enrolled before the
            # controller stopped asking about capabilities has fewer than the
            # row claims, and saying so every ten minutes forever is noise
            # about a difference nothing acts on until a job requires one.
            if claimed - held and not self.warned_caps:
                self.warned_caps = True
                log(f"controller lists {', '.join(sorted(claimed - held))} "
                    "for this node; not enrolled for it here, and jobs "
                    "needing it will be refused. Re-enroll to adopt them.")
            log(f"hello: node {n.get('id')} ({n.get('name')}), state "
                f"{n.get('state')}, poll {self.poll}s")
            # The sessions this node runs use the bb the controller ships;
            # when that moves, fetch it and restart the ttyds onto it. The
            # running sessions are tmux's and survive the restart — only the
            # next connection runs the new bb-tty. Never fatal: the session
            # half must not take the job half down with it — a packages
            # store this process cannot write is a node with no sessions,
            # not a node with no agent.
            self.session_try(r.get("bundle") or "")
            self.runner_env_sync()
        return st, r

    def runner_env_sync(self):
        """Every runner's .env, kept equal to what runner_env_text says now:
        the node's toolchain and where CI logs are archived. _apply_runner
        writes it at install; a runner installed before this agent knew a
        line (bb-sandbox's was) ran with less. Rewritten when it differs, and
        the service cycled so the runner reads it, only while it is idle: a
        restart under a running job would kill the job."""
        for d, _rec in runner_dirs():
            self._runner_env_sync(d)

    def _runner_env_sync(self, d):
        want = runner_env_text(self.state)
        try:
            with open(os.path.join(d, ".env")) as f:
                have = f.read()
        except OSError:
            have = ""
        if have == want:
            return
        if _run(["pgrep", "-f", os.path.join(d, "bin/Runner.Worker")]):
            return                          # busy: next hello
        env = {}
        who = self.as_user(env, self.state.get("user") or "")
        self.own_dir(ci_log_dir(self.state), who)
        with contextlib.suppress(OSError):
            os.chmod(ci_log_dir(self.state), 0o755)
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(want)
        if who:
            with contextlib.suppress(OSError):
                os.chown(os.path.join(d, ".env"), who["user"], who["group"])
        log("runner: its .env now carries the node's toolchain and the CI log directory; restarting the runner to read it")
        if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
            quiet = type("Q", (), {"say": staticmethod(lambda t: None)})()
            self._sh(quiet, ["bash", "./svc.sh", "stop"], cwd=d)
            self._sh(quiet, ["bash", "./svc.sh", "start"], cwd=d)
        else:
            self.runner_stop(d)
            self.runner_start(who, d=d)

    def running(self):
        with self.lock:
            return len(self.jobs)

    def running_ids(self):
        with self.lock:
            return sorted(self.jobs)

    def finished(self, job):
        with self.lock:
            self.jobs.pop(job.job["id"], None)

    def cancel(self, ids):
        with self.lock:
            hit = [self.jobs[i] for i in ids if i in self.jobs]
        for j in hit:
            log(f"job {j.job['id']}: canceled by the controller")
            j.cancel()

    def loop(self):
        delay = 1
        # What is THIS process's to end, ended by it. The ttyds go: a stop of
        # the unit is an update or a reboot, and the new agent starts its own.
        # The tmux servers they attached do not — they are their own daemons,
        # the sessions are inside them, and a conversation should survive an
        # agent update the way it survives a ttyd restart.
        #
        # That was already the intent and systemd was undoing it: the default
        # KillMode=control-group takes every process in the cgroup after this
        # handler returns, tmux included, so Update agent ended every session
        # on the machine (B107). The unit says KillMode=process now, which
        # means the jobs are this handler's to end too — with control-group
        # systemd was killing those, and leaving a build running while the
        # controller re-queues it is the one thing that change could have
        # cost.
        def bye(*_):
            with self.lock:
                running = list(self.jobs.values())
            for j in running:
                j.cancel()
            self.session_stop()
            self.runner_stop()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, bye)
        # The session half first, so the first hello's census already says
        # it is up: the bundle fetch answers with its own digest, so nothing
        # from hello is needed to start. A controller that is down fails the
        # fetch and the hello alike, and the hello that eventually succeeds
        # starts the sessions then.
        self.session_try()
        while True:
            if time.time() - self.hello_at > 600:
                st, r = self.hello()
                if st == 401:
                    log(f"refused: {r.get('error')} — this node's credential "
                        "is no longer good. Re-enroll with a new token.")
                    time.sleep(300)
                    continue
                if st != 200:
                    log(f"controller not answering ({st} {r.get('error', '')}); "
                        f"retrying in {delay}s")
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                delay = 1
            self.session_check()
            self.session_mount_check()
            self.session_firewall_check()
            self.session_idle_reap()
            self.runner_check()
            n = self.running()
            # The controller counts what is running here from its own rows
            # and wakes a held poll when a job ends, so the poll is held at
            # full length whether or not anything is running. The count in
            # the sample is for the row's numbers, not for placement.
            wait = self.poll
            sample = self.sampler.sample(self.state, n)
            # The sessions this node runs ride the heartbeat (roadmap #24),
            # so the dashboard's Sessions card lists them beside its own.
            if self.ttyd:
                sample["sessions"] = self.sessions_now()
            # ...and what each account here is signed in to Claude as, on its
            # own slower clock, so the controller's record is true without a
            # session having to run (B104). Absent from most heartbeats,
            # which the controller reads as "no news" rather than as none.
            logins = self.logins_now()
            if logins is not None:
                sample["logins"] = logins
            st, r = self.ctl.call("work", {"sample": sample, "running": n, "wait": wait},
                                  timeout=wait + 15)
            if st == 204:
                continue
            if st == 200 and r.get("cancel"):
                # Not a job: the ids of jobs here the operator has stopped.
                self.cancel([str(i) for i in r["cancel"]])
                continue
            if st == 200 and r.get("kill_sessions"):
                # ...or sessions here the operator ended from the Sessions
                # card: the session account's tmux is only reachable as it.
                self.kill_sessions([str(x) for x in r["kill_sessions"]])
                continue
            if st == 200 and r.get("tmux"):
                # ...or keys for a session here: the phone keyboard's row,
                # a console's line, a macro — typed into the pane as the
                # dashboard would type them into its own tmux.
                self.tmux_ops(r["tmux"] if isinstance(r["tmux"], list) else [])
                continue
            if st == 200 and r.get("hello"):
                # The controller refused something on the strength of a
                # census that may have gone stale — the census rides hello
                # every ten minutes, which is fine for a display and too
                # coarse for a gate. Say it again now, so the retry the
                # operator is about to make reasons about this machine as it
                # is rather than as it was.
                self.hello_at = 0
                continue
            if st == 200 and r.get("id"):
                self.take(r)
                continue
            if st == 401:
                log(f"refused: {r.get('error')} — re-enroll with a new token")
                self.hello_at = 0
                time.sleep(300)
                continue
            log(f"work: {st} {r.get('error', '')}; retrying in {delay}s")
            self.hello_at = 0                 # say hello again on the way back
            time.sleep(delay)
            delay = min(delay * 2, 60)

    def take(self, job):
        with self.lock:
            if job["id"] in self.jobs:
                return
            j = Job(self, job)
            self.jobs[job["id"]] = j
        log(f"job {job['id']}: {job.get('type')} "
            f"{' '.join((job.get('spec') or {}).get('argv') or [])[:80]}")
        j.start()

    # -- self-update (door 4) ------------------------------------------------
    def self_update(self, job, spec):
        want = spec.get("digest") or self.controller_digest
        if self.running() > 1:
            job.say("busy: other jobs are running; try again when they finish\n")
            return "failed", 75
        st, body = self.ctl.call("download", None, timeout=60, method="GET", raw=True)
        if st != 200:
            job.say(f"download failed: {st}\n")
            return "failed", 69
        got = "sha256:" + hashlib.sha256(body).hexdigest()
        if want and got != want:
            job.say(f"digest mismatch: wanted {want[:19]}…, got {got[:19]}…\n")
            return "failed", 65
        if got == own_digest():
            job.say("already current\n")
            return "succeeded", 0
        me = os.path.abspath(__file__)
        tmp = me + ".new"
        with open(tmp, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o755)
        os.replace(tmp, me)
        job.say(f"installed {got[:19]}…; restarting\n")
        return "succeeded", 0

    # -- the workspace (docs/nodes.md §6, phase 6) ------------------------------
    def own_dir(self, path, who):
        """Make a directory the enrolled account can use — a job runs as it,
        and this process is root."""
        os.makedirs(path, exist_ok=True)
        if who:
            with contextlib.suppress(OSError):
                os.chown(path, who["user"], who["group"])

    def materialize(self, job, src, who):
        """The job's source, on disk: the snapshot by digest — from the
        cache store when this node has fetched it before, from the
        controller otherwise, checked against its digest either way — and
        unpacked into a directory of the job's own under the data store."""
        stores = self.state.get("stores") or {}
        digest = str(src.get("digest") or "")
        hexd = digest.split(":", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", hexd):
            job.say(f"refused: not a snapshot digest: {digest!r}\n")
            return None
        snaps = os.path.join(stores.get("cache") or "/tmp", "snapshots")
        os.makedirs(snaps, exist_ok=True)
        tar_path = os.path.join(snaps, hexd + ".tar")
        if not os.path.isfile(tar_path):
            job.say(f"fetching snapshot {hexd[:12]}…\n")
            st, _ = self.ctl.fetch(f"source?digest={hexd}", tar_path)
            if st != 200:
                job.say(f"the controller has no snapshot {hexd[:12]} ({st}) — the tree "
                        "has moved on; queue the job again\n")
                return None
        h = hashlib.sha256()
        with open(tar_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != hexd:
            os.remove(tar_path)
            job.say("the cached snapshot did not match its digest; dropped it — queue the job again\n")
            return None
        ws = os.path.join(stores.get("data") or "/tmp", "jobs", job.job["id"], "workspace")
        shutil.rmtree(os.path.dirname(ws), ignore_errors=True)
        os.makedirs(ws)
        with tarfile.open(tar_path) as tar:
            # Python 3.12's filter refuses paths that escape the target;
            # older interpreters get the members checked by hand.
            if hasattr(tarfile, "data_filter"):
                tar.extractall(ws, filter="data")
            else:
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/"):
                        raise RuntimeError(f"snapshot member escapes the workspace: {m.name}")
                tar.extractall(ws)
        if who:
            for d, _dirs, files in os.walk(os.path.dirname(ws)):
                for x in [d] + [os.path.join(d, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        return ws

    def finish_workspace(self, job, ws, spec, state):
        """After the command: on success upload what the outputs globs
        match and delete the job's directory; on failure keep it for
        inspection and drop the older kept one for the same project, so
        a run of failures does not fill the store."""
        jobdir = os.path.dirname(ws)
        project = str((job.job.get("source") or {}).get("project") or "")
        if state == "succeeded":
            self.deliver(job, ws, spec.get("outputs") or [])
            shutil.rmtree(jobdir, ignore_errors=True)
            return
        # Kept: this one. Dropped: any earlier kept failure of the same project.
        marker = os.path.join(jobdir, "project")
        with contextlib.suppress(OSError):
            with open(marker, "w") as f:
                f.write(project)
        jobs_root = os.path.dirname(jobdir)
        for other in os.listdir(jobs_root) if os.path.isdir(jobs_root) else []:
            od = os.path.join(jobs_root, other)
            if od == jobdir or other in self.jobs:
                continue
            try:
                with open(os.path.join(od, "project")) as f:
                    if f.read() == project:
                        shutil.rmtree(od, ignore_errors=True)
            except OSError:
                continue
        job.say(f"the workspace is kept at {ws} for a look; the next failure of "
                f"{project or 'this project'} replaces it\n")
        job.outputs.append({"kind": "workspace", "path": ws})

    def deliver(self, job, base, outputs):
        """Upload what the outputs globs match under `base` as artifacts.
        dist/<basename>, which is what a person looks for; two matches
        sharing a name are told apart by the directory the second came
        from, so a debug and a release APK of the same name both arrive."""
        seen = set()
        for pat in list(outputs)[:16]:
            for hit in sorted(glob.glob(os.path.join(base, str(pat)), recursive=True)):
                if not os.path.isfile(hit):
                    continue
                rel = os.path.relpath(hit, base)
                name = os.path.basename(rel)
                if name in seen:
                    parent = os.path.basename(os.path.dirname(rel)) or "2"
                    name = f"{parent}-{name}"
                seen.add(name)
                st, r = self.ctl.upload(f"artifact?job={job.job['id']}&name={name}", hit)
                if st == 200 and not r.get("error"):
                    job.say(f"artifact {r['path']} ({os.path.getsize(hit)} bytes)\n")
                    job.outputs.append({"kind": "artifact", "path": r["path"],
                                        "size": r.get("size"), "sha256": r.get("sha256")})
                else:
                    job.say(f"could not deliver {rel}: {r.get('error') or st}\n")

    def bundle(self, job, who):
        """bb, its library and the catalog, from the controller by digest
        into the packages store; the directory it runs from, or '' when it
        could not be fetched. Shared by package jobs, bb verbs, and — with
        no job, so `job` may be None and the log is this process's — the
        sessions this node runs (roadmap #24). `.bb/current` points at the
        newest unpacked copy, which is what a shell on this node puts on its
        PATH."""
        say = job.say if job else (lambda t: log(t.rstrip("\n")))
        store = pkg_root(self.state)
        if not store:
            say("refused: this node has no packages store\n")
            return ""
        self.own_dir(store, who)
        bbdir = os.path.join(store, ".bb")
        os.makedirs(bbdir, exist_ok=True)
        tar_path = os.path.join(bbdir, "bundle.tar")
        st, digest = self.ctl.fetch("download?what=bundle", tar_path)
        if st != 200:
            say(f"could not fetch bb from the controller ({st})\n")
            return ""
        hexd = digest.split(":", 1)[-1]
        into = os.path.join(bbdir, hexd[:16] or "bundle")
        if not os.path.isdir(into):
            with tarfile.open(tar_path) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(into, filter="data")
                else:
                    tar.extractall(into)
            os.chmod(os.path.join(into, "scripts", "bb"), 0o755)
            for x in ("bb-tty", "bb-work-note", "bb-prompt-relay"):
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(into, "scripts", "dashboard", x), 0o755)
            say(f"bb {hexd[:12]} unpacked into {into}\n")
        with contextlib.suppress(OSError):
            tmp = os.path.join(bbdir, ".current.new")
            if os.path.lexists(tmp):
                os.unlink(tmp)
            os.symlink(os.path.basename(into), tmp)
            os.replace(tmp, os.path.join(bbdir, "current"))
        if who:
            for d, _dirs, files in os.walk(into):
                for x in [d] + [os.path.join(d, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        # Fetched by a job while the ttyds run an older copy: leave the
        # restart to the loop's session_check, which owns self.ttyd — this
        # may be a job's thread. Without this the sessions ran whatever
        # bundle the ttyds started on until the next hello, up to ten
        # minutes, and a bb-tty that old looked for a transcript where the
        # bundle before it kept them.
        self.prune_bundles(bbdir, into)
        if self.ttyd and self.session_bundle and digest != self.session_bundle:
            self.session_stale = into
        self.session_digest = digest
        return into

    @staticmethod
    def prune_bundles(bbdir, keep):
        """Drop the bundles nothing is going to run again.

        Every delivery unpacks into a directory named for its digest, and
        nothing removed them: 33 of them in four days on the first node to be
        looked at, one per commit that touches bb. Small each, unbounded
        together.

        What has to survive: the newest, which the ttyds run and `current`
        names; the three newest, which versions() probes for an SDK
        inventory; and, for a while, whatever an already-open shell has on
        its PATH. That last one is why there is an age floor and not a bare
        count — a session started after `current` went on PATH holds no
        digest at all, so the floor is a grace period for the shells that
        predate it rather than a permanent requirement.
        """
        keep_n, floor = 5, time.time() - 48 * 3600
        try:
            names = [d for d in os.listdir(bbdir) if len(d) == 16
                     and all(c in "0123456789abcdef" for c in d)]
            dirs = [os.path.join(bbdir, d) for d in names
                    if os.path.isdir(os.path.join(bbdir, d))]
            dirs.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            return
        for d in dirs[keep_n:]:
            with contextlib.suppress(OSError):
                if d != keep and os.path.getmtime(d) < floor:
                    shutil.rmtree(d)

    # -- the session half (roadmap #24) ---------------------------------------
    def session_account(self):
        """The account sessions run as, or "" when this node runs none: the
        one the provisioner made when this process is root, and this
        process's own when it is not (a container node runs the agent as
        the image's builder and sessions as the same)."""
        if os.geteuid() == 0:
            return self.state.get("session_user") or ""
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name

    def session_env(self, into):
        """What every session on this node inherits, through ttyd: this
        node's toolchains (sdk_env), the bundle's scripts and the account's
        own bin directories on PATH, the role, and how to reach the
        controller — the URL and the certificate pin the agent enrolled
        with, never its token. bb's relayed verbs carry the session's own
        token, which rides in on the terminal's URL."""
        env = dict(sdk_env(self.state))
        who = self.as_user(env, self.session_account())
        if not who:
            env.update({"HOME": os.path.expanduser("~"), "USER": self.session_account(),
                        "LOGNAME": self.session_account()})
        home = env["HOME"]
        # The SYMLINK on PATH, not the digest it points at (bug #66). A ttyd
        # restart onto a new bundle only reaches new connections: a tmux
        # session's shell was started whenever it was started and keeps the
        # PATH it was given, so a session that has been open since before an
        # update went on running the bundle it began with. What that looks
        # like is a typo — `bb tests` printing bb's usage on a node whose
        # controller has the verb — rather than a machine that is behind.
        #
        # Through `current`, every bb invocation in every shell, however old,
        # runs whatever was delivered last. The name is resolved at exec, so
        # there is nothing to restart and nothing to keep in step; `into` is
        # still the resolved path everywhere else, because the census has to
        # report the digest actually running rather than a symlink.
        store = pkg_root(self.state)
        link = os.path.join(store, ".bb", "current") if store else ""
        bbdir = link if link and os.path.isdir(link) else into
        env["PATH"] = ":".join([os.path.join(bbdir, "scripts"),
                                os.path.join(home, ".local", "bin"),
                                os.path.join(home, ".npm-global", "bin"), env["PATH"]])
        # AVDs under the account's own ~/.android rather than the data store,
        # which the job account owns: a session's `bb emu create` has to be
        # able to write where its emulator keeps state.
        env.pop("ANDROID_AVD_HOME", None)
        env.update({"BUILDER_HOME": home, "BUILDERBOT_ROLE": "node",
                    "BB_CONTROLLER": self.ctl.url, "BB_CONTROLLER_PIN": self.state.get("pin", ""),
                    "BB_NODE": self.state.get("name") or "", "BUILDERBOT_NODE": self.state.get("node_id", ""),
                    "WORKSPACE": "/workspace", "LANG": "C.UTF-8"})
        return env, who

    def session_bind(self):
        if SESSION_BIND:
            return SESSION_BIND
        for a in (network_now().get("addresses") or []):
            if ":" not in a:
                return a.split("/")[0]
        return "0.0.0.0"

    def session_start(self, into, retry=False):
        """The two ttyds — writable, and the read-only twin an account
        without a shell is shown — running bb-tty from the bundle, as the
        session account, on the LAN address. What 15-dashboard.sh does on
        the controller, done here by the process that is already up."""
        self.session_stop()
        bbtty = os.path.join(into, "scripts", "dashboard", "bb-tty")
        user = self.session_account()
        if not user or not os.path.isfile(bbtty):
            SESSION.update(up=False, port=0, ro_port=0, user=user, bundle=self.session_bundle,
                           why="no session account" if not user else "the bundle carries no bb-tty")
            return
        if not shutil.which(TTYD_BIN) and not os.access(TTYD_BIN, os.X_OK):
            SESSION.update(up=False, port=0, ro_port=0, user=user, bundle=self.session_bundle,
                           why="ttyd is not installed here")
            return
        env, who = self.session_env(into)
        bind = self.session_bind()
        self.session_bound = bind
        logf = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp", "ttyd.log")
        base = [TTYD_BIN, "--interface", bind, "--url-arg", "--max-clients", "16",
                "-t", "reconnect=5"]
        self.session_stale = ""
        try:
            out = open(logf, "ab")
            for port, extra in ((SESSION_PORT, ["--writable"]), (SESSION_PORT + 1, [])):
                self.ttyd.append(subprocess.Popen(
                    base[:1] + ["--port", str(port)] + base[1:] + extra + [bbtty],
                    cwd=env["HOME"] if os.path.isdir(env["HOME"]) else "/",
                    env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out, **who))
            out.close()
        except (OSError, RuntimeError) as e:
            self.session_stop()
            SESSION.update(up=False, port=0, ro_port=0, user=user, bundle=self.session_bundle,
                           why=f"ttyd could not start: {e}"[:120])
            log(f"sessions: ttyd could not start: {e}")
            return
        # STARTED IS NOT UP. A ttyd whose port is taken exits at once, and
        # reporting it up on the strength of the Popen is how a node served
        # sessions from a bundle four deliveries old for a day: the agent's
        # self-update re-executed this process and the ttyds it had started
        # stayed on the ports as orphans, every later start failed the same
        # way in silence, and the census named the bundle nobody was
        # running. So the start is watched for a moment; one that died has
        # its port looked at, and a stray bb-tty ttyd there — one of ours,
        # from a process that is gone — is ended and the start tried once
        # more. Anything else on the port is named and left alone.
        died = self._session_died()
        if died and not retry:
            stray = [self._port_holder(pt) for pt in died]
            ours = [(pid, cmd) for pid, cmd in stray
                    if pid and "ttyd" in cmd and "bb-tty" in cmd]
            if ours and len(ours) == len(stray):
                for pid, _ in ours:
                    log(f"sessions: port held by a ttyd of an earlier agent process (pid {pid}); ending it")
                    self._end_pid(pid)
                self.session_stop()
                return self.session_start(into, retry=True)
        if died:
            held = "; ".join(f"port {pt}: " + (f"pid {pid} ({cmd[:40]})" if pid else "taken")
                             for pt, (pid, cmd) in zip(died, [self._port_holder(pt) for pt in died]))  # noqa: B905 (3.9 on Rocky)
            self.session_stop()
            SESSION.update(up=False, port=0, ro_port=0, user=user, bundle=self.session_bundle,
                           why=f"ttyd could not bind — {held}"[:160])
            log(f"sessions: ttyd could not bind — {held}")
            return
        SESSION.update(up=True, port=SESSION_PORT, ro_port=SESSION_PORT + 1, user=user,
                       home=env["HOME"], bind=bind, bundle=self.session_bundle, why="")
        log(f"sessions: ttyd on {bind}:{SESSION_PORT} (read-only twin on {SESSION_PORT + 1}) "
            f"as {user}, bb {self.session_bundle[7:19]}")

    def _session_died(self):
        """The ports whose ttyd exited within the first moment of its start —
        a bind failure shows as an exit in well under a second."""
        for _ in range(6):
            time.sleep(0.25)
            if any(p.poll() is not None for p in self.ttyd):
                break
        return [SESSION_PORT + i for i, p in enumerate(self.ttyd) if p.poll() is not None]

    @staticmethod
    def _port_holder(port):
        """(pid, cmdline) of what listens on a TCP port, or (0, "") when
        nothing does or it cannot be told. ss is iproute2's and is on every
        node this runs on; the pid needs this process to own the socket or
        be root, which it is on a VM."""
        try:
            p = subprocess.run(["ss", "-Hltnp", f"sport = :{port}"], capture_output=True,
                               text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return 0, ""
        m = re.search(r"pid=(\d+)", p.stdout or "")
        if not m:
            return 0, "taken" if (p.stdout or "").strip() else ""
        pid = int(m.group(1))
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            cmd = ""
        return pid, cmd

    @staticmethod
    def _end_pid(pid):
        """SIGTERM, a moment, then SIGKILL; reaped if it was this process's
        child — an orphan left over from before a re-exec still is."""
        for sig, wait in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
            with contextlib.suppress(OSError):
                os.kill(pid, sig)
            end = time.time() + wait
            while time.time() < end:
                with contextlib.suppress(OSError):
                    os.waitpid(pid, os.WNOHANG)
                if not os.path.exists(f"/proc/{pid}") or _zombie(pid):
                    return
                time.sleep(0.1)

    def session_stop(self):
        for p in self.ttyd:
            with contextlib.suppress(OSError):
                p.terminate()
        for p in self.ttyd:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                p.wait(5)
        self.ttyd = []

    def session_try(self, digest=None):
        """session_refresh, never fatal: the session half must not take the
        job half down with it — a packages store this process cannot write
        is a node with no sessions, not a node with no agent."""
        try:
            self.session_refresh(digest)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            SESSION.update(up=False, port=0, ro_port=0, user=self.session_account(),
                           bundle="", why=f"{e}"[:120])
            log(f"sessions: not started — {e}")

    def session_refresh(self, digest=None):
        """The bundle the controller ships against the one the ttyds run
        from: fetched and swapped in when they differ, and at the start of
        this process (no digest to compare — the fetch answers with one),
        which is when sessions start."""
        if self.ttyd and (digest is None or digest == self.session_bundle):
            return
        if not self.session_account():
            SESSION.update(up=False, port=0, ro_port=0, user="", bundle="",
                           why="no session account — provision with --session-user")
            return
        env = {}
        who = self.as_user(env, self.session_account())
        into = self.bundle(None, who)
        if not into:
            return
        self.session_bundle = self.session_digest or digest
        self.session_tried = time.time()
        self.session_start(into)

    def _tmux(self, argv, timeout=10):
        """tmux as the session account — its server, its sessions. The
        environment is the account's own (HOME and the default socket
        path follow the uid), not this process's: the agent under systemd
        has no TMUX_TMPDIR and must not inherit one from a test."""
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8"}
        for k in ("TMUX_TMPDIR",):
            if k in os.environ:
                env[k] = os.environ[k]
        who = self.as_user(env, self.session_account())
        if not who:
            env["HOME"] = os.path.expanduser("~")
        try:
            p = subprocess.run(["tmux", *argv], env=env, capture_output=True, text=True,
                               timeout=timeout, check=False, **who)
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            log(f"sessions: tmux {argv[0]}: {e}")
            return None
        if p.returncode != 0 and argv[0] != "list-panes":
            # list-panes fails whenever no server is up, which is the normal
            # state of a node nobody has opened a terminal on; anything else
            # failing is worth a line.
            log(f"sessions: tmux {' '.join(argv)}: {(p.stderr or '').strip()[:120]}")
        return p.stdout if p.returncode == 0 else None

    def sessions_now(self):
        """The session account's tmux sessions, for the heartbeat: name,
        attached, the active pane's directory and title. Empty when the
        server is not up, which is the normal state of a node nobody has
        opened a terminal on yet."""
        out = self._tmux(["list-panes", "-a", "-F",
                          "#{session_name}\t#{pane_active}\t#{session_attached}\t"
                          "#{pane_current_path}\t#{pane_title}"])
        rows = []
        for line in (out or "").splitlines():
            parts = line.split("\t", 4)
            if len(parts) == 5 and parts[1] == "1":
                rows.append({"name": parts[0], "attached": parts[2].strip() not in ("", "0"),
                             "cwd": parts[3], "title": parts[4]})
        return rows[:64]

    # What each account on this machine is signed in to Claude as, refreshed
    # at most this often. It is two file reads per account and no subprocess
    # per account, but it is also news that changes about once a week, and
    # the heartbeat runs every poll.
    LOGINS_EVERY = 300

    def logins_now(self):
        """Which Anthropic account each BuilderBot account here is signed in
        as, or None when there is nothing new to say (B104).

        The controller holds no credential and learns of a login only when
        something on the machine tells it. That used to be a session's hook
        and nothing else, so a node signed in with no session running stayed
        "not signed in" on the card until somebody opened one — and after a
        sign-out, the way back needed the very thing the card was refusing.
        The agent is already here and already tends these homes, so it says
        so on the heartbeat.

        Asked of the BUNDLE rather than read here: where an account lives on
        this machine is bb's answer, and a second copy of that rule in this
        file is how the two would drift. `.bb/current` is the copy a shell on
        this node already runs, so this costs no fetch.
        """
        now = time.time()
        if now - getattr(self, "_logins_at", 0) < self.LOGINS_EVERY:
            return None
        self._logins_at = now
        store = pkg_root(self.state)
        bb = os.path.join(store, ".bb", "current", "scripts", "bb") if store else ""
        if not (bb and os.path.isfile(bb)):
            return None
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8"}
        try:
            who = self.as_user(env, self.session_account())
        except RuntimeError:
            return None
        if not who:
            return None
        try:
            p = subprocess.run(["bash", bb, "login", "--list"], env=env,
                               capture_output=True, text=True, timeout=20,
                               check=False, **who)
            rows = json.loads(p.stdout) if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return rows[:64] if isinstance(rows, list) else None

    def kill_sessions(self, names):
        for name in names:
            log(f"sessions: ending {name} — asked from the dashboard")
            self._tmux(["kill-session", "-t", "=" + name])

    def tell(self, job, spec):
        """One line into a Claude session here, and Enter only if it
        visibly arrived: the notebook's Send to Claude, run where the pane
        is. The controller's notify.tell does exactly this in its own tmux
        and cannot in this one, so the rule is repeated rather than
        approximated: a session waiting at its prompt echoes what is typed
        and a permission dialog swallows it, and pressing Enter into a
        dialog blind is the one thing this must never do. Exit 0 sent, 3
        typed but left unsent for a person to look at, 2 no such session."""
        sess = str(spec.get("session") or "")
        text = " ".join(str(spec.get("text") or "").split())
        if not sess or not text:
            job.say("nothing to say, or nobody to say it to\n")
            return "failed", 2
        names = {str((r or {}).get("name") or "") for r in (self.sessions_now() or [])}
        if sess not in names:
            job.say(f"no session called {sess} is running here\n")
            return "failed", 2
        # A long line lands in claude's box folded into "[Pasted text #1]"
        # (the TUI reads a burst of typed characters as a paste), so the
        # placeholder counts as the echo; whitespace is collapsed because
        # the box wraps a long line at word boundaries with an indent.
        mark = " ".join(text[:40].split())
        def seen():
            flat = " ".join((self._tmux(["capture-pane", "-p", "-J", "-t", sess]) or "").split())
            return flat.count(mark) + flat.count("[Pasted text")
        was = seen()
        if self._tmux(["send-keys", "-t", sess, "-l", "--", text]) is None:
            job.say("tmux would not take the line\n")
            return "failed", 1
        # The same look-window as the controller's: two quarter-second
        # looks, one more per 120 characters, since a TUI re-renders as it
        # takes input and a long line is not on screen inside a short one.
        for _ in range(2 + len(text) // 120):
            time.sleep(0.25)
            if seen() > was:
                if self._tmux(["send-keys", "-t", sess, "Enter"]) is None:
                    job.say("the line is in the box but Enter did not go\n")
                    return "failed", 1
                job.say(f"sent to {sess}\n")
                return "succeeded", 0
        job.say(f"typed into {sess} but not sent: the pane did not echo it, so something "
                "other than the prompt has the keyboard\n")
        return "failed", 3

    def tmux_ops(self, ops):
        """Keys into a session here, as the dashboard sends them into its
        own tmux (server._keys, _say, _send). Only send-keys and copy-mode,
        only at a session by exact name: the controller composed the
        argv, and this node still decides what it will run. `page` and
        `respawn` are the two decisions made here — PgUp at a prompt enters
        copy mode where inside a full-screen program it is the program's key,
        and a respawn has to find the launcher — because both depend on
        something only this side can see."""
        for op in ops[:16]:
            if not isinstance(op, dict):
                continue
            sess = str(op.get("session") or "")
            if not sess:
                continue
            # A bare name, not `=name`: these take a target-PANE, and the
            # exact-match prefix is target-session syntax — measured, as
            # "can't find pane: =…". tmux tries the exact name first anyway.
            page = op.get("page")
            if page in ("up", "down"):
                flags = self._tmux(["display-message", "-p", "-t", sess,
                                    "#{alternate_on} #{pane_in_mode}"]) or ""
                alt, mode = (flags.split() + ["0", "0"])[:2]
                if page == "up":
                    argv = ["send-keys", "-t", sess, "PPage"] if alt == "1" \
                        else ["copy-mode", "-eu", "-t", sess]
                else:
                    argv = ["send-keys", "-t", sess, "-X", "page-down"] if mode == "1" \
                        else ["send-keys", "-t", sess, "NPage"]
                self._tmux(argv)
                continue
            # Restart this session's own process onto its launcher, which is
            # what the dashboard asks for when a project's model, effort or
            # permission rung changes. `-k` replaces the pane's process and
            # keeps the tmux session, so every browser attached to it stays
            # where it is; `--respawn` tells the launcher to resume the newest
            # transcript, so the conversation continues rather than restarting.
            #
            # The launcher's PATH is read off the pane rather than composed
            # here. On a node the session belongs to one of several accounts
            # and the file is in that account's home, which this side would
            # have to reconstruct — while tmux already knows, because bb-tty
            # starts the pane on that script and nothing else. Hence the
            # claude-run- name, and hence checking it before running it: the
            # controller asked for a respawn, it did not say what to execute.
            if op.get("respawn"):
                cmd = (self._tmux(["display-message", "-p", "-t", sess,
                                   "#{pane_start_command}"]) or "").strip()
                if re.fullmatch(r"\S*/builderbot/claude-run-[^/\s]+\.sh", cmd):
                    self._tmux(["respawn-pane", "-k", "-t", sess, cmd, "--respawn"])
                continue
            argv = [str(a) for a in (op.get("argv") or [])][:12]
            if argv[:1] not in (["send-keys"], ["copy-mode"]) or "-t" not in argv:
                continue
            # The target is this op's session, whatever the argv says.
            argv[argv.index("-t") + 1] = sess
            self._tmux(argv)

    def session_renew(self):
        """Ask the loop to restart the ttyds onto the current bundle with a
        freshly built environment — from a job's thread, so only the flag
        is set here."""
        store = pkg_root(self.state)
        into = os.path.realpath(os.path.join(store, ".bb", "current")) if store else ""
        if into and os.path.isdir(into) and self.ttyd:
            self.session_stale = into

    def session_firewall_check(self):
        """Once a minute: the session ports' rule names the controller's
        address as it resolved when the node was provisioned, and a
        controller that moved — a new lease, a new host behind the same
        name — would find 7681 and 7682 dropped for it from then on. So the
        name is resolved again here and the rule rewritten when the answer
        changed: the nftables file the Debian path wrote and re-applied, or
        firewalld's rich rules replaced. Root only, which is a managed node;
        a guest has no such rule and skips."""
        if time.time() - self.fw_checked < FIREWALL_EVERY_S or os.geteuid() != 0:
            return
        self.fw_checked = time.time()
        ip = controller_ip(self.state.get("controller") or "")
        if not ip:
            return
        fam = "ip6" if ":" in ip else "ip"
        if os.path.isfile(SESSION_NFT):
            try:
                with open(SESSION_NFT) as f:
                    text = f.read()
            except OSError:
                return
            m = re.search(r"tcp dport \{ 7681, 7682 \} (ip6?) saddr (\S+) accept", text)
            if not m or m.group(2) == ip:
                return
            new = text.replace(m.group(0), f"tcp dport {{ 7681, 7682 }} {fam} saddr {ip} accept")
            try:
                with open(SESSION_NFT, "w") as f:
                    f.write(new)
            except OSError as e:
                log(f"session ports: could not rewrite {SESSION_NFT}: {e}")
                return
            rc = subprocess.run([NFT_BIN, "-f", SESSION_NFT], capture_output=True, check=False).returncode
            log(f"session ports: the controller's address moved ({m.group(2)} -> {ip}); "
                f"rule rewritten{'' if rc == 0 else ' but nft refused it (' + str(rc) + ')'}")
            return
        if _have(FIREWALL_CMD) and _run([FIREWALL_CMD, "--state"]) == "running":
            rules = _run([FIREWALL_CMD, "--permanent", "--list-rich-rules"], timeout=20).splitlines()
            ours = [r for r in rules if 'port="7681"' in r or 'port="7682"' in r]
            have = {re.search(r'source address="([^"]+)"', r).group(1)
                    for r in ours if re.search(r'source address="([^"]+)"', r)}
            if not ours or have == {ip}:
                return
            for r in ours:
                subprocess.run([FIREWALL_CMD, "--permanent", f"--remove-rich-rule={r}"], capture_output=True, check=False)
            ffam = "ipv6" if ":" in ip else "ipv4"
            for port in (7681, 7682):
                subprocess.run([FIREWALL_CMD, "--permanent", f'--add-rich-rule=rule family="{ffam}" source '
                                f'address="{ip}" port port="{port}" protocol="tcp" accept'],
                               capture_output=True, check=False)
            subprocess.run([FIREWALL_CMD, "--reload"], capture_output=True, check=False)
            log(f"session ports: the controller's address moved ({', '.join(sorted(have)) or '?'} -> {ip}); "
                "firewalld rules replaced")

    def session_idle_reap(self):
        """End this node's Claude sessions past the idle rule — the
        controller's idle.py, enforced here from node.json. Claude sessions
        by name (claude-<project>, u_xxxx~claude-<project>), by tmux's own
        session_activity, once per minute."""
        limit = self.state.get("session_idle_minutes") or 0
        if limit <= 0 or time.time() - getattr(self, "_idle_at", 0) < IDLE_UNIT:
            return
        self._idle_at = time.time()
        out = self._tmux(["list-sessions", "-F", "#{session_name}\t#{session_activity}"])
        for line in (out or "").splitlines():
            if "\t" not in line:
                continue
            name, act = line.split("\t", 1)
            try:
                last = float(act.strip())
            except ValueError:
                continue
            claude = name.startswith("claude-") or "~claude-" in name
            if claude and time.time() - last > limit * IDLE_UNIT:
                log(f"sessions: ending {name} — idle {limit} minute(s), the controller's rule")
                self._tmux(["kill-session", "-t", "=" + name])

    def session_mount_check(self):
        """Once a loop: is the projects share at /workspace as the last
        census said — mounted, and writable? A census rides hello every ten
        minutes, and the first one after a boot is taken before the network
        mounts land (the unit orders after remote-fs.target now, but a mount
        with nofail can still be late, and a Mac's owner mounts the share by
        hand), so it says the share is missing and the controller ghosts
        every Claude button bound here for the rest of those ten minutes.
        So the fact is measured each loop — two stats — and a change says
        hello again at once."""
        if not SESSION or self.session_mount is None:
            return
        try:
            mounted = os.path.ismount("/workspace")
            now = (mounted, mounted and os.access("/workspace", os.W_OK))
        except OSError:
            return
        if now != self.session_mount:
            log(f"sessions: the projects share at /workspace is {'mounted' if now[0] else 'not mounted'}"
                f"{' read-only' if now[0] and not now[1] else ''} now; telling the controller")
            self.session_mount = now
            self.hello_at = 0

    def session_check(self):
        """Once a loop: a ttyd that died is started again, not more often
        than SESSION_RETRY_S — a port already taken would otherwise
        spin this loop on a failing exec — and ttyds running an older
        bundle than the one a job just fetched are restarted onto it. The
        sessions are tmux's either way and survive; a client attached at
        that moment reconnects.

        And a node whose own address moved — DHCP handed it another, the
        interface came back on a new one — has ttyds bound to an address
        nothing reaches any more, while the controller already dials the
        new one (it follows every hello). So the bind is compared to the
        machine's address now, and a change restarts the ttyds onto it."""
        if self.ttyd and self.session_bound and not SESSION_BIND and not self.session_stale:
            now = self.session_bind()
            if now != self.session_bound:
                store = pkg_root(self.state)
                into = os.path.realpath(os.path.join(store, ".bb", "current")) if store else ""
                if into and os.path.isdir(into):
                    log(f"sessions: this node's address moved ({self.session_bound} -> {now}); "
                        "restarting ttyd onto it")
                    self.session_stale = into
        if self.session_stale and self.ttyd and os.path.isdir(self.session_stale):
            log("sessions: the bundle or the store changed; restarting ttyd so new sessions see it")
            self.session_bundle = self.session_digest
            self.session_tried = time.time()
            self.session_start(self.session_stale)
            return
        if not self.ttyd or all(p.poll() is None for p in self.ttyd):
            return
        if time.time() - self.session_tried < SESSION_RETRY_S:
            return
        log("sessions: a ttyd exited; starting again")
        self.session_tried = time.time()
        store = pkg_root(self.state)
        into = os.path.realpath(os.path.join(store, ".bb", "current")) if store else ""
        if into and os.path.isdir(into):
            # .bb/current is whatever was fetched last, so the census names
            # what this start actually runs.
            self.session_bundle = self.session_digest or self.session_bundle
            self.session_start(into)

    def artifact_dir(self, project, who=None, make=True):
        """This node's copy of one project's artifacts. Per project, because
        a node may be several projects' node and two of them may both ship
        an app-release.apk."""
        root = (self.state.get("stores") or {}).get("artifacts") or ""
        if not root:
            return ""
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(project or "")) or "_"
        d = os.path.join(root, name)
        if make:
            self.own_dir(d, who)
        return d

    # -- compose, locally (docs/nodes.md §7; roadmap #18) ----------------------
    def compose(self, job, spec):
        """One dev-instance action, run with the node's OWN docker.

        The controller still decides WHAT: it sends an ordered plan of argvs
        with the compose file and env beside them, and does the bookkeeping
        when this ends. What moved here is the execution — which is the whole
        point, because it is what let a node need an ssh key from the
        controller on top of the token it enrolled with. Nothing dials in
        now; docker is local.
        """
        if not shutil.which("docker"):
            job.say("refused: this node has no docker\n")
            return "failed", 78
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("name") or "compose"))
        cdir = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp",
                            "compose", name)
        who = self.drop_privileges({})
        self.own_dir(cdir, who)
        job.say(f"compose for {name} in {cdir}\n")
        # The compose file and the env, as the controller holds them: this
        # node never reads the project's tree for them, so a file edited on
        # the controller is the one that runs here.
        for fname, body in (spec.get("files") or {}).items():
            base = os.path.basename(str(fname))
            if not base or base.startswith("."):
                base = base or "file"
            path = os.path.join(cdir, base)
            with open(path, "w") as f:
                f.write(str(body))
            if who:
                with contextlib.suppress(OSError):
                    os.chown(path, who["user"], who["group"])
            job.say(f"wrote {base} ({len(str(body))} bytes)\n")
        # The bind directories, made here rather than by a throwaway
        # container over ssh — this process is already on the machine that
        # has them, and docker creating a missing bind source as root is the
        # failure the whole mechanism exists to avoid.
        for d in (spec.get("dirs") or [])[:32]:
            d = str(d)
            if not d.startswith("/") or ".." in d.split("/"):
                job.say(f"skipping a bind directory that is not a plain path: {d}\n")
                continue
            try:
                os.makedirs(d, exist_ok=True)
                if who:
                    with contextlib.suppress(OSError):
                        os.chown(d, who["user"], who["group"])
                job.say(f"bind directory {d}\n")
            except OSError as e:
                # A bind source this machine cannot make. Whether that ends
                # the job depends on whether docker could do better: it runs
                # as root, so an agent that is root and failed has proved
                # docker will fail too, and a stale NFS handle or a file in
                # the way defeats any privilege. Then the up cannot work and
                # is not tried: docker would report the same mkdir in worse
                # words ("mkdir /devdata: file exists" over a stale handle,
                # measured 15 Sep). An unprivileged agent (a guest node)
                # names it and carries on, since docker may still make it.
                why = e.strerror or str(e)
                hopeless = (os.geteuid() == 0 or e.errno == errno.ESTALE
                            or isinstance(e, (NotADirectoryError, FileExistsError)))
                hint = (": the mount under it is stale; remount it on this node"
                        if e.errno == errno.ESTALE or "stale" in why.lower() else "")
                if not hopeless:
                    job.say(f"could not make {d}: {why}; this agent is not root, so docker may still\n")
                    continue
                job.say(f"could not make {d}: {why}{hint}\n")
                job.outputs.append({"kind": "compose", "steps_done": 0, "failed_at": "preparing"})
                return "failed", 73
        done = 0
        for stp in (spec.get("plan") or [])[:8]:
            if job.canceled:
                job.say("stopped\n")
                job.outputs.append({"kind": "compose", "steps_done": done})
                return "canceled", 130
            argv = [str(a).replace("{cdir}", cdir) for a in (stp.get("argv") or [])]
            if not argv:
                continue
            job.step(str(stp.get("name") or "working"))
            # The command, then its output — a log of output with no command
            # is unreadable, and the controller's own runner has always
            # written this line.
            job.say("$ " + " ".join(argv) + "\n")
            # The agent's OWN environment is the base here, unlike an exec
            # job: docker on this node should behave as it does for the
            # account that runs it — a proxy, a DOCKER_CONFIG, a rootless
            # socket are all the node's own arrangement, and a compose that
            # ignored them would work by luck.
            env = dict(os.environ)
            env.update(sdk_env(self.state))
            env.update({k: str(v).replace("{cdir}", cdir)
                        for k, v in (stp.get("env") or {}).items()})
            st_, code = job.exec({"argv": argv, "cwd": cdir, "env": env,
                                  "timeout": stp.get("timeout") or 1800})
            if st_ != "succeeded":
                job.outputs.append({"kind": "compose", "steps_done": done,
                                    "failed_at": stp.get("name")})
                return st_, code
            done += 1
        job.outputs.append({"kind": "compose", "steps_done": done})
        return "succeeded", 0

    def cache_clear(self, job, spec):
        """Drop this node's build caches — one project's, or all of them.
        The one thing that goes wrong with caches is a full disk, and this
        is the button for it (docs/nodes.md §6)."""
        root = (self.state.get("stores") or {}).get("cache") or ""
        if not root or not os.path.isdir(root):
            job.say("no cache store here\n")
            return "succeeded", 0
        project = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("project") or ""))
        targets = [os.path.join(root, project)] if project else \
                  [os.path.join(root, d) for d in os.listdir(root)]
        n = 0
        for t in targets:
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
                job.say(f"removed {t}\n")
                n += 1
        job.say(f"cleared {n} director{'y' if n == 1 else 'ies'}\n")
        self.hello()
        return "succeeded", 0

    # -- toolchains (docs/nodes.md §6) --------------------------------------------
    def package(self, job, spec):
        """`bb packages install|remove NAME` against this node's packages store,
        with the bb the controller ships: the bundle (bb, its library, the
        catalog) is fetched by digest into the store and run from there as
        the enrolled account, SDK_ROOT pointing at the store. One catalog,
        per-node state — the census reports what landed."""
        store = pkg_root(self.state)
        if not store:
            job.say("refused: this node has no packages store\n")
            return "failed", 78
        action = spec.get("action")
        names = [re.sub(r"[^A-Za-z0-9:;._-]", "", str(n)) for n in (spec.get("names") or [])][:8]
        if action not in ("install", "remove", "sysdeps") or (not names and action != "sysdeps"):
            job.say("refused: a package job installs or removes named packages, "
                    "or installs the system packages the held ones need\n")
            return "failed", 64
        who = self.drop_privileges({})
        into = self.bundle(job, who)
        if not into:
            return "failed", 69
        if action == "sysdeps":
            return self.sysdeps(job, names, into)
        bad = 0
        for name in names:
            # Which one it is on, for the tab's "Installing …". Only compose
            # jobs set this before, so a package job on a node drew the verb
            # with nothing after it — and the image picker, which draws its
            # own progress only when the step names an image, drew none.
            job.step(name)
            if action == "install" and not self._system_deps(job, name, into):
                bad += 1
                continue
            job.say(f"== bb packages {action} {name}\n")
            st_, code = job.exec({"argv": ["bash", os.path.join(into, "scripts", "bb"),
                                            "packages", action, name],
                                   "cwd": store, "timeout": spec.get("timeout") or 3600,
                                   "env": sdk_env(self.state)})
            if st_ != "succeeded":
                bad += 1
                if st_ == "canceled":
                    return st_, code
        self.hello()
        if bad:
            job.say(f"{bad} of {len(names)} did not {action}\n")
            return "failed", 1
        return "succeeded", 0

    def _system_deps(self, job, name, into):
        """A recipe's `system.apt` (or `system.dnf`, on the RHEL family)
        packages, from the catalog the bundle
        carries: installed here, as root, on a node this agent may
        administer (the sandbox stamp — roadmap #23 refines it to a class);
        named and left to the owner anywhere else. The recipe itself runs
        as the job account, which is why this cannot be part of it.
        Playwright's browsers launched from the store and died on
        libatk-1.0.so.0 behind a stack that said the browser had closed.
        False when the install was tried and failed; a missing package on a
        node this cannot administer is a warning, not a refusal — the
        download is still worth having, and the tool names what is missing
        when it is used."""
        cat = read_catalog(into)
        fam, query, install = pkg_backend()
        missing, other = sysdeps_missing(cat, name, fam, query)
        # Which family this machine is decides which list applies. A recipe
        # that names packages for the other family only is not wrong, it is
        # incomplete for this node: say so with the names it does have, so
        # the owner can find their equivalents, and carry on to the recipe.
        if other:
            job.say(f"{name} needs system packages its recipe names for {other[0]} only; "
                    f"this node's are its owner's to install; the {other[0]} names: "
                    f"{' '.join(other[1])}\n")
        if not missing:
            return True
        if not self.administers():
            job.say(f"{name} needs system packages this node's owner installs — "
                    f"not this agent, which does not administer the machine: "
                    f"{' '.join(missing)}\n")
            return True
        job.say(f"== system packages for {name}: {' '.join(missing)}\n")
        return self._install_system(job, name, fam, install, missing)

    def administers(self):
        """Whether this agent may install system packages here: root, on a
        node provisioned as a sandbox (the stamp; roadmap R23 refines it to
        a class). Anywhere else the machine is its owner's."""
        return os.geteuid() == 0 and os.access(SANDBOX_BIN, os.X_OK)

    def sysdeps(self, job, names, into):
        """Install the system packages the recipes already on the store need
        here, without touching the recipes (roadmap R51). The store is a
        share, so a package installed from one node is on every node that
        mounts it, while the libraries it needs are each machine's own: a
        node enrolled afterwards has dotnet and not libicu, and the only
        gesture that installed libicu was reinstalling dotnet onto the share
        for everybody. Named recipes, or every held one when none are."""
        cat = read_catalog(into)
        fam, query, install = pkg_backend()
        if not fam:
            job.say("refused: no package manager this agent knows is on this machine\n")
            return "failed", 78
        held = held_recipes(self.state, cat)
        want = [n for n in names if n in held] if names else held
        if names and not want:
            job.say(f"none of {' '.join(names)} is on this node's store, so nothing here needs anything\n")
            return "succeeded", 0
        todo = {}
        for name in want:
            missing, other = sysdeps_missing(cat, name, fam, query)
            if other:
                job.say(f"{name}: its recipe names packages for {other[0]} only, not {fam}; "
                        f"the {other[0]} names: {' '.join(other[1])}\n")
            if missing:
                todo[name] = missing
        if not todo:
            job.say(f"every system package the held recipes need is installed here ({fam})\n")
            return "succeeded", 0
        if not self.administers():
            job.say("refused: this agent does not administer the machine, so its owner "
                    "installs these: "
                    + "; ".join(f"{n}: {' '.join(m)}" for n, m in todo.items()) + "\n")
            return "failed", 77
        bad = 0
        for name, missing in todo.items():
            job.step(name)
            job.say(f"== system packages for {name}: {' '.join(missing)}\n")
            if not self._install_system(job, name, fam, install, missing):
                bad += 1
        self.hello()
        if bad:
            job.say(f"{bad} of {len(todo)} did not install\n")
            return "failed", 1
        return "succeeded", 0

    def _install_system(self, job, name, fam, install, missing):
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        try:
            # emerge builds from source: fifteen minutes is a package
            # manager's clock, not a compiler's.
            p = subprocess.run([*install, *missing], env=env, capture_output=True, text=True,
                               timeout=4 * 3600 if fam == "emerge" else 900, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{install[0]}: {e}\n")
            return False
        if p.returncode != 0:
            job.say((p.stdout or "")[-2000:] + (p.stderr or "")[-2000:])
            job.say(f"{name}: its system packages did not install (exit {p.returncode})\n")
            return False
        return True

    # -- the configuration plane (docs/nodes.md §12, phase 5) -----------------
    def system(self, job, spec):
        """Apply the desired storage or network config the controller holds
        for this node — the one root-privileged thing the agent does. Not
        dropped to the enrolled account, because mounts and addresses are
        root's; offered by the controller only to nodes that enrolled as a
        sandbox, and refused here without bb-sandbox, which is the stamp."""
        what = spec.get("apply")
        # Per verb, not one stamp for all of them (roadmap #23): storage and
        # network edit fstab and netplan, which only a machine provisioned
        # as a sandbox — a MANAGED node — hands over. A runner needs only its
        # tarball and a funnel only tailscale, and a container node (this
        # image in the node role) or a guest machine has neither the stamp
        # nor any reason to be refused either of those.
        if what in ("storage", "network", "root") and not os.access(SANDBOX_BIN, os.X_OK):
            job.say(f"refused: {what} edits this machine's own configuration, and this node "
                    f"was not provisioned as a BuilderBot sandbox ({SANDBOX_BIN} is not here)\n")
            return "failed", 77
        cfg = spec.get("config") if isinstance(spec.get("config"), dict) else {}
        if what == "root":
            return self._apply_root(job, cfg)
        if what == "storage":
            return self._apply_storage(job, cfg)
        if what == "network":
            return self._apply_network(job, cfg)
        if what == "runner":
            return self._apply_runner(job, cfg)
        if what == "funnel":
            return self._apply_funnel(job, cfg)
        job.say(f"refused: unknown system job {what!r}\n")
        return "failed", 64

    def _sh(self, job, argv, cwd=None, timeout=300):
        """One command, its output into the job's log, its exit code back.

        `cwd` matters more than it looks: the runner's own svc.sh resolves
        everything relative to where it is invoked and refuses with "Must run
        from runner root or install is corrupt" anywhere else — which is
        exactly what a registered-but-serviceless runner came from.
        """
        job.say("$ " + " ".join(argv) + "\n")
        try:
            p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{argv[0]}: {e}\n")
            return 1
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.strip():
                job.say(line + "\n")
        return p.returncode

    def _apply_root(self, job, cfg):
        """One command as root, that a person allowed (roadmap R38). The
        controller queues this only after an administrator read the reason
        and the exact command and pressed Allow; the job's log opens with
        both and who it was, so the Jobs tab is the record. Nothing about
        the command is interpreted here: it is run as given, as root, once,
        and its output and exit code go back. Not sudo — there is no second
        command without a second question."""
        argv = [str(a) for a in (cfg.get("argv") or []) if str(a)]
        if not argv:
            job.say("refused: nothing to run\n")
            return "failed", 64
        job.say(f"# root on this node, allowed by {cfg.get('by') or 'the operator'}: "
                f"{cfg.get('why') or '(no reason given)'}\n")
        try:
            timeout = max(1, min(int(cfg.get("timeout") or 600), 3600))
        except (TypeError, ValueError):
            timeout = 600
        # The same shape as Job.exec — its own process group, output pumped
        # as it comes, the log posted on a clock so a cancel can arrive and
        # land — minus the drop to the enrolled account, which is the point.
        # Not _sh: that blocks until the command ends with nothing posted,
        # so a cancel had nothing to reach and a timeout killed only the
        # direct child.
        job.say("$ " + " ".join(argv) + "\n")
        job.flush()
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        except OSError as e:
            job.say(f"could not start {argv[0]}: {e}\n")
            return "failed", 126
        job.proc = p
        if job.canceled:
            job._kill(p)

        def pump():
            try:
                for line in p.stdout:
                    job.say(line.decode("utf-8", "replace"))
            except (OSError, ValueError):
                pass
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline, killed = time.time() + timeout, False
        while reader.is_alive():
            reader.join(0.5)
            if job.pending:
                job.flush()
            if time.time() > deadline and not killed:
                job.say(f"timed out after {timeout}s — killing it\n")
                job._kill(p)
                killed = True
        p.wait()
        job.proc = None
        if job.canceled:
            job.say("stopped\n")
            return "canceled", 130
        if killed:
            return "failed", 124
        return ("succeeded" if p.returncode == 0 else "failed"), p.returncode

    def _apply_storage(self, job, cfg):
        """Mounts as a diff against what bb-sandbox has — remove what is no
        longer wanted, add or rewrite what is (add-nfs/add-share rewrite an
        existing fstab line, so this is idempotent) — then the stores, which
        are this agent's own file. Ends with a hello, so the row shows the
        applied state now rather than at the next census."""
        want = [m for m in (cfg.get("mounts") or []) if isinstance(m, dict)]
        have = {m.get("path"): m for m in mounts_now()}
        bad = 0
        for path in have:
            if not any(w.get("path") == path for w in want):
                if self._sh(job, [SANDBOX_BIN, "remove", path]) != 0:
                    bad += 1
        for w in want:
            path, src = str(w.get("path") or ""), str(w.get("source") or "")
            kind, ro = str(w.get("type") or "nfs"), bool(w.get("ro"))
            if not path.startswith("/") or not src:
                job.say(f"skipping a mount with no path or source: {w!r}\n")
                bad += 1
                continue
            verb = "add-share" if kind == "virtiofs" else "add-nfs"
            if self._sh(job, [SANDBOX_BIN, verb, f"{src}:{path}" + (":ro" if ro else "")]) != 0:
                bad += 1
        stores = cfg.get("stores") if isinstance(cfg.get("stores"), dict) else {}
        if stores:
            # Read the mounts back AFTER applying them: what a store may sit
            # on is what is mounted now, not what was asked for.
            live = mounts_now()
            mine = dict(self.state.get("stores") or {})
            # What this agent created for each store, so a move can take
            # back exactly that and nothing else.
            marks = dict(self.state.get("store_made") or {})
            for role, path in stores.items():
                if role not in DEFAULT_STORES:
                    continue
                why = store_path_ok(path)
                if why:
                    job.say(f"refused {role} store: {why}\n")
                    bad += 1
                    continue
                # The silent failure this exists to stop: a share that is in
                # fstab but not mounted leaves its mountpoint an ordinary
                # empty directory, mkdir cheerfully makes the store inside
                # it, and everything then lands on the node's own disk while
                # the row reports a healthy store with plenty of room. So a
                # store under a configured mount is refused unless that
                # mount is really mounted — fix the share, or take the entry
                # out and mean it locally.
                cover = mount_covering(path, live)
                if cover and not os.path.ismount(str(cover.get("path") or "")):
                    job.say(f"refused {role} store {path}: it is inside {cover.get('path')}, "
                            f"which is configured as a {cover.get('type') or 'nfs'} mount from "
                            f"{cover.get('source') or '?'} and is NOT mounted. Writing there would "
                            f"put {role} on this node's own disk and look like it worked. Fix the "
                            f"mount, or remove it from this node's mounts if {path} is meant to be "
                            f"local.\n")
                    bad += 1
                    continue
                try:
                    made = make_store(path)
                except OSError as e:
                    job.say(f"{role} store {path} could not be made: {e.strerror}\n")
                    bad += 1
                    continue
                if made:
                    job.say(f"{role}: made {', '.join(made)}\n")
                was = str(mine.get(role) or "")
                if was and was.rstrip("/") != str(path).rstrip("/"):
                    if not self._move_store(job, role, was, str(path)):
                        # The move did not happen, so nothing was written to
                        # the new place: leave no litter behind either.
                        for d in prune_made(made)[0]:
                            job.say(f"{role}: removed {d} again — the move did not happen\n")
                        bad += 1
                        continue
                    self._retire_store(job, role, was, marks.get(role) or [])
                    marks[role] = made
                else:
                    # Same path. Keep the original record — it says what was
                    # made for this store the FIRST time, which is what a
                    # later move has to clean up — and add anything this run
                    # had to put back.
                    prev = list(marks.get(role) or [])
                    marks[role] = prev + [d for d in made if d not in prev]
                mine[role] = str(path)
                job.say(f"{role} store: {path}\n")
            self.state["stores"] = mine
            self.state["store_made"] = marks
            save_state(self.state)
        self.hello()
        if bad:
            job.say(f"{bad} of the changes did not apply — the rest did\n")
            return "failed", 1
        job.say("storage applied\n")
        return "succeeded", 0

    def _move_store(self, job, role, old, new):
        """Repointing a store used to leave its contents behind: the node
        started using an empty directory and the toolchains, AVDs or built
        artifacts stayed where they were, with nothing saying so. So the
        contents come across first, and the job only repoints if they did.

        The source is never deleted — the same rule the node-change
        migration keeps (roadmap #17). A half-finished move must leave the
        old store able to serve, and reclaiming the space is the operator's
        to do once they can see both.

        `cache` is the exception: it is rebuildable by definition, and a
        cold cache costs the next build time and never correctness, so
        copying tens of gigabytes of it across a link would be work for
        nothing.
        """
        if not os.path.isdir(old):
            job.say(f"{role}: nothing at {old} to bring across\n")
            return True
        if role == "cache":
            job.say(f"{role}: leaving {old} where it is — a cache is rebuildable, "
                    f"and the new one starts cold\n")
            return True
        try:
            if not os.listdir(old):
                job.say(f"{role}: {old} is empty, nothing to bring across\n")
                return True
        except OSError as e:
            job.say(f"{role}: cannot read {old}: {e.strerror}\n")
            return False
        size = dir_bytes(old)
        try:
            free = shutil.disk_usage(new).free
        except OSError as e:
            # The share the store is being pointed at, not reachable from
            # here. Said plainly: an unguarded disk_usage raised out of the
            # job and came back as "agent error: FileNotFoundError", which
            # names the exception rather than the path.
            job.say(f"refused: {new} cannot be read ({e.strerror}). Nothing was moved "
                    f"and {role} still points at {old}.\n")
            return False
        if size is not None:
            job.say(f"{role}: bringing {size // 1048576}MB across from {old}; "
                    f"{free // 1048576}MB free at {new}\n")
            if size > free:
                job.say(f"refused: {new} has not got room for it. Nothing was moved and "
                        f"{role} still points at {old}.\n")
                return False
        else:
            job.say(f"{role}: bringing {old} across (size unknown)\n")
        # cp -a, not shutil: it keeps ownership, times and links, and one C
        # process beats a per-file round trip over NFS. Six hours, because
        # a packages store is tens of gigabytes and this is the one system
        # job that can legitimately take that long.
        #
        # ...but not ownership where ownership is not the mover's to keep. A
        # share exported all_squash — which is what the projects and SDK
        # shares here ARE, so that a file written from any machine is owned
        # the way the array expects — refuses every chown, and `cp -a` then
        # exits non-zero after copying every byte correctly. The store move
        # read that as a failed copy and refused to repoint, with the data
        # sitting in the new place: "Operation not permitted", four times,
        # and a job that says the copy failed when it did not.
        argv = ["cp", "-a"]
        if not _can_chown(new):
            argv.append("--no-preserve=ownership")
            job.say(f"{new} squashes ownership (an all_squash export, most likely), so "
                    f"the copy keeps times, modes and links and the export decides the "
                    f"owner — which is the arrangement, not a loss.\n")
        if self._sh(job, argv + [os.path.join(old, "."), new + "/"], timeout=21600) != 0:
            job.say(f"refused: the copy failed. {role} still points at {old}, "
                    f"which is untouched.\n")
            return False
        job.say(f"{role}: copied. The old copy at {old} is left in place — "
                f"delete it yourself once you are satisfied.\n")
        return True

    def _retire_store(self, job, role, old, made):
        """After a store has moved, take back the directories this agent
        made for it — and only those, and only if they are empty.

        Which is usually none of them, and saying so matters: the move keeps
        the old copy on purpose, so the store directory is not empty and
        rmdir refuses it. That is the correct outcome, not a failure, and
        the log says which path is still holding data so it can be removed
        deliberately. The empty case is real too — a store that was
        configured and never written to leaves directories behind that
        nobody wants.
        """
        if not made:
            job.say(f"{role}: {old} was not made by this agent, so it is left alone\n")
            return
        removed, kept = prune_made(made)
        if removed:
            job.say(f"{role}: removed {', '.join(removed)} — made for this store "
                    f"and empty now\n")
        for path, why in kept:
            job.say(f"{role}: {path} stays ({why})"
                    + (": the old copy is in there; remove it yourself when you are "
                       "satisfied the move worked\n" if "empty" in (why or "").lower()
                       else "\n"))

    def _apply_network(self, job, cfg):
        """Commit/confirm, because this is the one change that can cut the
        cord it arrives on (docs/nodes.md §12): render the desired address
        through whichever backend owns this machine's network — netplan, or
        NetworkManager — apply it, then dial the controller from wherever
        the machine landed. No answer within DIAL_BACK_S and the previous
        config is put back and applied again, and the failure is reported
        on reconnect. The spec is the same whatever the backend."""
        backend = net_backend()
        if backend is None:
            job.say("refused: network changes need a backend this agent drives — netplan, "
                    "NetworkManager, systemd-networkd, wicked, ifupdown or dhcpcd — and "
                    f"{_os_release() or 'this node'} has none of them running; set the address "
                    "by hand, or on a node that has one\n")
            return "failed", 77
        net = cfg.get("network") if isinstance(cfg.get("network"), dict) else cfg
        iface = str(net.get("interface") or network_now().get("interface") or "")
        if not iface:
            job.say("refused: no interface named and no default route to read one from\n")
            return "failed", 65
        mode = "static" if net.get("mode") == "static" else "dhcp"
        addr, gw = str(net.get("address") or ""), str(net.get("gateway") or "")
        dns = [str(d) for d in (net.get("dns") or []) if str(d)]
        if mode == "static" and not addr:
            job.say("refused: a static address needs an address\n")
            return "failed", 65
        why = backend.ready(iface)
        if why:
            job.say(f"refused: {why}\n")
            return "failed", 77
        # The one check that would have saved the operator's evening: the
        # host's NFS exports name this node's address, so a node that moves
        # loses its mounts unless the rule moves first — and the mount
        # fails quietly under nofail, at the next boot, on a share the
        # sessions need. Asked of the servers before anything changes.
        gaps = export_gaps(addr) if mode == "static" else []
        if gaps:
            job.say("refused: the host's NFS exports admit this node's current address and not "
                    "the new one, so the shares would not mount after the move. Change the rule "
                    "on the host first (Unraid: Shares -> the share -> NFS Security Settings), "
                    "then apply again:\n  " + "\n  ".join(gaps) + "\n")
            return "failed", 77
        desired = backend.render(iface, mode, addr, gw, dns)
        before = backend.snapshot(iface)
        if backend.same(desired, before):
            job.say(f"already applied — {backend.name} already has this config\n")
            return "succeeded", 0
        if backend.apply(self, job, iface, desired, before) != 0:
            backend.restore(self, job, iface, before)
            return "failed", 1
        job.say(f"applied; dialing the controller back from the new address "
                f"(up to {DIAL_BACK_S}s)\n")
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            st, _ = self.hello()
            if st == 200:
                job.say(f"dialed back in from {network_now().get('addresses') or ['?']}\n")
                return "succeeded", 0
            # Never past the deadline: a fixed five seconds means a window
            # shorter than five seconds still costs five, which is what the
            # test that shortens DIAL_BACK_S was paying twice over.
            time.sleep(max(0.0, min(5.0, deadline - time.time())))
        job.say(f"could not reach the controller within {DIAL_BACK_S}s — reverting\n")
        backend.restore(self, job, iface, before)
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            if self.hello()[0] == 200:
                break
            time.sleep(max(0.0, min(5.0, deadline - time.time())))
        job.say("reverted to the previous network config\n")
        return "failed", 68

    def _apply_runner(self, job, cfg):
        """The Actions runner as a service on this node (phase 7): fetched
        from GitHub's releases, registered with a token the controller mints
        on request — the PAT stays in the controller's root-only stash and
        the token lives for an hour — and run under systemd as the enrolled
        account by the runner's own svc.sh. Removal deregisters first, so
        GitHub does not keep a ghost. Labels are the tab's, the node's name
        among them, and are written beside the runner for the census."""
        want = bool(cfg.get("want", True))
        who = self.drop_privileges({})
        user = self.state.get("user") or "root"
        url = str(cfg.get("url") or "")
        slot = str(cfg.get("slot") or "") or runner_slot(url)
        # This runner's directory, one per git host: the one already
        # registered for this address (RUNNER_DIR itself for a runner from
        # before a node could hold several), else RUNNER_DIR/<slot>.
        d = self._runner_dir_for(slot, url)
        # Which host's runner: what is installed decides a removal, the
        # record decides an install.
        installed = _runner_record(d)
        if (installed.get("address") if installed else cfg.get("forge") == "gitea"):
            return self._apply_act_runner(job, cfg, want, who, d, installed, slot)
        if not want:
            if not os.path.isfile(os.path.join(d, ".runner")):
                job.say("no runner is installed here\n")
                return "succeeded", 0
            st, r = self.ctl.call("runner-token", {"kind": "remove", "slot": slot}, timeout=60)
            if st != 200 or not r.get("token"):
                job.say(f"could not get a removal token from the controller: {r.get('error', st)}\n")
                return "failed", 69
            self.runner_stop(d)
            if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "remove", "--token", r["token"]])
            if code != 0:
                job.say("deregistration did not complete; remove the runner in GitHub's settings if it lingers\n")
            shutil.rmtree(d, ignore_errors=True)
            self.hello()
            job.say("runner removed\n")
            return "succeeded", 0
        if not url.startswith("https://github.com/"):
            job.say(f"refused: the runner registers with a GitHub org or repo URL, not {url!r}\n")
            return "failed", 65
        labels = [re.sub(r"[^A-Za-z0-9._-]", "", str(x)) for x in (cfg.get("labels") or [])]
        labels = [x for x in labels if x][:16] or ["builderbot", "self-hosted"]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", str(cfg.get("name") or socket.gethostname()))[:64]
        os.makedirs(d, exist_ok=True)
        if not os.path.isfile(os.path.join(d, "config.sh")):
            tar_path = os.path.join(d, "runner.tar.gz")
            if RUNNER_TARBALL:
                shutil.copyfile(RUNNER_TARBALL, tar_path)
                job.say(f"using the runner tarball at {RUNNER_TARBALL}\n")
            else:
                arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm"}.get(platform.machine(), "x64")
                osname = "osx" if platform.system() == "Darwin" else "linux"
                job.say("asking GitHub for the latest runner release…\n")
                try:
                    with urllib.request.urlopen(RUNNER_RELEASES, timeout=30) as r:
                        rel = json.load(r)
                    asset = next(a["browser_download_url"] for a in rel.get("assets", [])
                                 if a.get("name", "").startswith(f"actions-runner-{osname}-{arch}-")
                                 and a["name"].endswith(".tar.gz"))
                except (OSError, ValueError, StopIteration, KeyError) as e:
                    job.say(f"could not find the runner release: {e}\n")
                    return "failed", 69
                job.say(f"downloading {asset}\n")
                job.flush()
                try:
                    with urllib.request.urlopen(asset, timeout=600) as r, open(tar_path, "wb") as f:
                        shutil.copyfileobj(r, f)
                except OSError as e:
                    job.say(f"download failed: {e}\n")
                    return "failed", 69
            with tarfile.open(tar_path) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(d, filter="data")
                else:
                    tar.extractall(d)
            os.remove(tar_path)
        self.own_dir(d, who)
        if who:
            for dd, _dirs, files in os.walk(d):
                for x in [dd] + [os.path.join(dd, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        # A runner that is already configured locally refuses to be
        # configured again — `--replace` is about taking a NAME back on
        # GitHub's side, not about overwriting .runner here. So a Reinstall
        # after a half-finished install (registered, service not installed)
        # failed with "Cannot configure the runner because it is already
        # configured", and the retry was blocked by the state the first
        # attempt left. Clear it first, and mean it: deregister properly if
        # the controller will mint a removal token, and failing that take the
        # local config out of the way so this can proceed — a runner left on
        # GitHub's side is replaced by name a moment later.
        # The registration token FIRST, before anything standing is touched:
        # a reinstall whose token could not be minted used to stop and
        # uninstall the working runner, clear its registration, and only
        # then find out, leaving the node with no runner at all.
        st, r = self.ctl.call("runner-token", {"kind": "registration", "slot": slot}, timeout=60)
        if st != 200 or not r.get("token"):
            # One line, reason last: the row reads the log's last line.
            kept = ", so the runner already here is left as it was" if os.path.isfile(os.path.join(d, ".runner")) else ""
            job.say(f"could not get a registration token from the controller{kept}: {r.get('error', st)}\n")
            return "failed", 69
        if os.path.isfile(os.path.join(d, ".runner")):
            job.say("a runner is already configured here; clearing it before reinstalling\n")
            if os.path.isfile(os.path.join(d, "svc.sh")):
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            st, rr = self.ctl.call("runner-token", {"kind": "remove", "slot": slot}, timeout=60)
            gone = False
            if st == 200 and rr.get("token"):
                gone = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "remove",
                                                  "--token", rr["token"]]) == 0
            if not gone:
                job.say("deregistration did not complete; taking the local config out of the "
                        "way so the reinstall can proceed. The old runner is replaced by name.\n")
                for junk in (".runner", ".credentials", ".credentials_rsaparams", ".service"):
                    with contextlib.suppress(OSError):
                        os.remove(os.path.join(d, junk))
        job.say(f"registering {name} with {url} [{','.join(labels)}]\n")
        code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "--unattended", "--replace",
                                          "--url", url, "--token", r["token"], "--name", name,
                                          "--labels", ",".join(labels), "--work", "_work"])
        if code != 0:
            return "failed", code
        with open(os.path.join(d, ".builderbot-labels"), "w") as f:
            f.write(",".join(labels))
        # The runner reads .env into every job it runs: the node's toolchain,
        # so CI sees what bb build sees, and where the workflows' archive
        # step lands — see runner_env_text. The log directory is made here,
        # readable, so the session account can read what lands in it.
        logs = ci_log_dir(self.state)
        self.own_dir(logs, who)
        with contextlib.suppress(OSError):
            os.chmod(logs, 0o755)
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(runner_env_text(self.state))
        if os.path.isfile(os.path.join(d, "svc.sh")) and has_systemd():
            for verb in (["install", user], ["start"]):
                if self._sh(job, ["bash", "./svc.sh", *verb], cwd=d) != 0:
                    # Registered but not serviced is a real state, and the
                    # row should say so rather than showing nothing: the
                    # census reads .runner, which exists by now.
                    self.hello()
                    job.say("the runner is registered with GitHub but its service did "
                            "not install — it will not pick up jobs until it does\n")
                    return "failed", 1
        else:
            # No systemd — a container node (this image in the node role),
            # or a guest machine without it (roadmap #23). The runner is
            # run.sh in the foreground under this agent, which supervises it
            # and takes it down with itself; the census's pgrep of
            # Runner.Listener reports it exactly as it would the service.
            if not self.runner_start(who, job, d):
                return "failed", 1
            job.say("no systemd here: the runner runs in the foreground under this agent\n")
        self.hello()
        job.say("runner installed and started\n")
        return "succeeded", 0

    @staticmethod
    def _runner_dir_for(slot, url=""):
        """Where a runner for this address lives, or would: the directory
        already registered for it, else RUNNER_DIR/<slot>."""
        want = url.rstrip("/").lower()
        for d, rec in runner_dirs():
            have = str(rec.get("gitHubUrl") or rec.get("address") or "").rstrip("/").lower()
            if (want and have == want) or (not want and runner_slot(have) == slot):
                return d
        return os.path.join(RUNNER_DIR, slot) if slot else RUNNER_DIR

    def _apply_act_runner(self, job, cfg, want, who, d, installed, slot):
        """Gitea's or Forgejo's runner (R53): act_runner, one static binary,
        registered with a token the controller fetches from the host's API
        with the node's own credential, and run as `act_runner daemon` in
        the foreground under this agent, which supervises it the way it
        does GitHub's runner on a node without systemd. Every label is
        `name:host`, so a job lands on this machine's own toolchain rather
        than in a container, which is what a BuilderBot node is for."""
        exe = os.path.join(d, "act_runner")
        if not want:
            if not installed:
                job.say("no runner is installed here\n")
                return "succeeded", 0
            rid = str(installed.get("id") or "")
            st, r = self.ctl.call("runner-token", {"kind": "remove", "slot": slot, "runner_id": rid}, timeout=60)
            if st != 200 or r.get("error"):
                job.say(f"could not delete the runner on its host: {r.get('error', st)}; "
                        "taking the local one down anyway\n")
            self.runner_stop(d)
            shutil.rmtree(d, ignore_errors=True)
            self.hello()
            job.say("runner removed\n")
            return "succeeded", 0
        url = str(cfg.get("url") or "")
        # http as well as https: a Gitea on the LAN, and the controller
        # accepted the address the same way when the token was stored.
        if not url.startswith(("https://", "http://")):
            job.say(f"refused: the runner registers with an https address (or http on your own network), not {url!r}\n")
            return "failed", 65
        labels = [re.sub(r"[^A-Za-z0-9._-]", "", str(x)) for x in (cfg.get("labels") or [])]
        labels = [x for x in labels if x][:16] or ["builderbot", "self-hosted"]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", str(cfg.get("name") or socket.gethostname()))[:64]
        os.makedirs(d, exist_ok=True)
        if not os.path.isfile(exe):
            if ACT_RUNNER_BIN:
                shutil.copyfile(ACT_RUNNER_BIN, exe)
                job.say(f"using the act_runner at {ACT_RUNNER_BIN}\n")
            else:
                arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm-7"}.get(platform.machine(), "amd64")
                job.say("asking gitea.com for the latest act_runner release…\n")
                try:
                    with urllib.request.urlopen(ACT_RUNNER_RELEASES, timeout=30) as r:
                        rel = json.load(r)
                    asset = next(a["browser_download_url"] for a in rel.get("assets", [])
                                 if re.fullmatch(rf"act_runner-[0-9.]+-linux-{arch}", a.get("name", "")))
                except (OSError, ValueError, StopIteration, KeyError) as e:
                    job.say(f"could not find the act_runner release: {e}\n")
                    return "failed", 69
                job.say(f"downloading {asset}\n")
                job.flush()
                try:
                    with urllib.request.urlopen(asset, timeout=600) as r, open(exe, "wb") as f:
                        shutil.copyfileobj(r, f)
                except OSError as e:
                    job.say(f"download failed: {e}\n")
                    return "failed", 69
            os.chmod(exe, 0o755)
        self.own_dir(d, who)
        # The registration token first, so a token that cannot mint leaves
        # a runner already standing as it was.
        st, r = self.ctl.call("runner-token", {"kind": "registration", "slot": slot}, timeout=60)
        if st != 200 or not r.get("token"):
            kept = ", so the runner already here is left as it was" if installed else ""
            job.say(f"could not get a registration token from the controller{kept}: {r.get('error', st)}\n")
            return "failed", 69
        if installed:
            job.say("a runner is already registered here; deleting it on its host before registering again\n")
            self.runner_stop(d)
            self.ctl.call("runner-token", {"kind": "remove", "slot": slot,
                                           "runner_id": str(installed.get("id") or "")}, timeout=60)
            with contextlib.suppress(OSError):
                os.remove(os.path.join(d, ".runner"))
        job.say(f"registering {name} with {url} [{','.join(labels)}]\n")
        code = self._run_as(job, who, d, [exe, "register", "--no-interactive", "--instance", url,
                                          "--token", r["token"], "--name", name,
                                          "--labels", ",".join(f"{x}:host" for x in labels)])
        if code != 0:
            return "failed", code
        with open(os.path.join(d, ".builderbot-labels"), "w") as f:
            f.write(",".join(labels))
        logs = ci_log_dir(self.state)
        self.own_dir(logs, who)
        with contextlib.suppress(OSError):
            os.chmod(logs, 0o755)
        # act_runner reads .env into every job it runs, as GitHub's does.
        with open(os.path.join(d, ".env"), "w") as f:
            f.write(runner_env_text(self.state))
        self.own_dir(d, who)
        if not self.runner_start(who, job, d):
            return "failed", 1
        self.hello()
        job.say("runner installed and started\n")
        return "succeeded", 0

    def runner_start(self, who, job=None, d=None):
        """The runner in directory d as a child of this process, as the
        enrolled account, its output into runner.log under the data store:
        GitHub's run.sh, or `act_runner daemon`. Its own session, so a stop
        reaches the listener and the workers it forks alike."""
        d = d or RUNNER_DIR
        say = job.say if job else (lambda t: log(t.rstrip("\n")))
        if os.path.isfile(os.path.join(d, "run.sh")):
            argv = ["bash", "./run.sh"]
        elif os.path.isfile(os.path.join(d, "act_runner")):
            argv = [os.path.join(d, "act_runner"), "daemon"]
        else:
            say("the runner has nothing to start: no run.sh and no act_runner\n")
            return False
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
               "HOME": d}
        if who:
            import pwd
            with contextlib.suppress(KeyError):
                env["HOME"] = pwd.getpwuid(who["user"]).pw_dir
        logf = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp", "runner.log")
        try:
            out = open(logf, "ab")
            self.runner_procs[d] = subprocess.Popen(argv, cwd=d, env=env,
                                                    stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                                    start_new_session=True, **who)
            out.close()
        except (OSError, RuntimeError) as e:
            say(f"the runner could not start: {e}\n")
            self.runner_procs.pop(d, None)
            return False
        self.runner_tried[d] = time.time()
        log(f"runner: {' '.join(argv)} started in the foreground (pid {self.runner_procs[d].pid}), log {logf}")
        return True

    def runner_stop(self, d=None):
        """Stop the runner in directory d, or every one this agent started."""
        for dd in ([d] if d else list(self.runner_procs)):
            p = self.runner_procs.pop(dd, None)
            if p is None or p.poll() is not None:
                continue
            for sig, wait in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 3.0)):
                with contextlib.suppress(OSError):
                    os.killpg(p.pid, sig)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.wait(wait)
                    break

    def runner_check(self):
        """Once a loop: every configured runner this agent is responsible
        for that is not running is started (after this agent restarted, or
        after it exited), not more often than every thirty seconds each.
        GitHub's runner is systemd's where there is systemd; act_runner is
        always this agent's. One already listening from an earlier agent
        process is left to it."""
        for d, _rec in runner_dirs():
            if has_systemd() and not os.path.isfile(os.path.join(d, "act_runner")):
                continue
            p = self.runner_procs.get(d)
            if p is not None and p.poll() is None:
                continue
            if time.time() - self.runner_tried.get(d, 0) < 30:
                continue
            if (_run(["pgrep", "-f", os.path.join(d, "bin/Runner.Listener")])
                    or _run(["pgrep", "-f", os.path.join(d, "act_runner") + " daemon"])):
                self.runner_tried[d] = time.time()
                continue                    # an earlier agent's; working
            log(f"runner {os.path.basename(d)}: not running; starting" if p is None
                else f"runner {os.path.basename(d)}: exited ({p.returncode}); starting again")
            self.runner_start(self.drop_privileges({}), d=d)

    def _apply_funnel(self, job, cfg):
        """Tailscale Funnel for one local port on https 443 (docs/nodes.md
        §7): tailscale's own CLI does the certificate, the DNS and the
        firewall, and its status is what the census reports afterwards."""
        if not (shutil.which(TAILSCALE_BIN) or os.access(TAILSCALE_BIN, os.X_OK)):
            job.say("refused: tailscale is not installed on this node\n")
            return "failed", 77
        try:
            port = int(cfg.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            job.say("refused: a funnel forwards to a port number\n")
            return "failed", 65
        if cfg.get("on", True):
            code = self._sh(job, [TAILSCALE_BIN, "funnel", "--bg", "--https=443",
                                  f"http://127.0.0.1:{port}"])
        else:
            code = self._sh(job, [TAILSCALE_BIN, "funnel", "--https=443", "off"])
        self.hello()
        if code != 0:
            return "failed", code
        job.say(("funnel on: https://" + (services_now().get("tailscale") or {}).get("dns", "?")
                 + f" -> 127.0.0.1:{port}\n") if cfg.get("on", True) else "funnel off\n")
        return "succeeded", 0

    def _run_as(self, job, who, cwd, argv):
        """One command as the enrolled account, in the runner's directory,
        its output into the log. config.sh refuses to run as root."""
        job.say("$ " + " ".join(a if "--token" not in argv[max(0, i - 1)] else "…" for i, a in enumerate(argv)) + "\n")
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
               "HOME": cwd}
        who2 = dict(who)
        if who:
            import pwd
            with contextlib.suppress(KeyError):
                env["HOME"] = pwd.getpwuid(who["user"]).pw_dir
        try:
            p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=600, check=False, **who2)
        except (OSError, subprocess.SubprocessError) as e:
            job.say(f"{argv[0]}: {e}\n")
            return 1
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            if line.strip():
                job.say(line + "\n")
        return p.returncode

    def reexec(self):
        # The ttyds first: execv keeps the children and loses every handle
        # to them, so the new image would find its ports held by processes
        # it cannot see and serve nothing new for as long as they lived.
        # The sessions are tmux's and stay; the new agent starts ttyd from
        # the bundle that is current, which is the point of updating.
        self.session_stop()
        log("re-executing the new agent")
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "run"])


# ---------------------------------------------------------------------------
# commands

def cmd_enroll(args):
    opts = {"--controller": "", "--token": "", "--user": "bb", "--pin": "",
            "--session-user": ""}
    stores = dict(DEFAULT_STORES)
    it = iter(args)
    for a in it:
        if a == "--store":
            role, _, path = next(it, "").partition("=")
            if role not in DEFAULT_STORES:
                raise SystemExit("--store takes " + ", ".join(f"{r}=/path" for r in DEFAULT_STORES))
            why = store_path_ok(path)
            if why:
                raise SystemExit(f"--store {role}: {why}")
            stores[role] = path
        elif a in opts:
            opts[a] = next(it, "")
        else:
            raise SystemExit(f"unknown option {a}")
    if not opts["--controller"] or not opts["--token"]:
        raise SystemExit("enroll needs --controller URL and --token bbe_…")
    if not opts["--token"].startswith("bbe_"):
        raise SystemExit("that is not an enrollment token (they start bbe_); "
                         "mint one on the controller's Nodes tab")
    marks = {}
    for role, path in stores.items():
        # A store that cannot be made is reported, not fatal: its free space
        # reads as zero on the row, which is the true answer. What each one
        # DID create is kept, so that if the store is moved later the
        # directories this put there can be taken back and nothing else.
        try:
            marks[role] = make_store(path)
        except OSError as e:
            print(f"note: {role} store {path} could not be created ({e.strerror}); "
                  "it will report no space until it exists")
    ctl = Controller(opts["--controller"], opts["--token"], opts["--pin"])
    state = {"controller": ctl.url, "user": opts["--user"], "stores": stores,
             "store_made": marks}
    # The account sessions run as (roadmap #24), when this agent runs as
    # root. Recorded even when empty, so `status` shows the decision.
    state["session_user"] = opts["--session-user"]
    st, r = ctl.call("enroll", {"census": census(state), "version": AGENT_VERSION,
                                "digest": own_digest(), "user": opts["--user"]},
                     timeout=30)
    if st != 200:
        raise SystemExit(f"enrollment refused ({st}): {r.get('error', 'no answer')}")
    if ctl.scheme == "https":
        pin = opts["--pin"] or getattr(ctl, "seen_pin", "")
        state["pin"] = pin
        if not opts["--pin"]:
            print(f"pinned the controller's certificate on first use: {pin}\n"
                  f"  check it against the controller; a different one next "
                  f"time is refused")
    else:
        print("note: plain http — the node token travels unencrypted on this "
              "network, as the dashboard's own credential does. Put TLS in "
              "front of the controller and re-enroll to pin it.")
    state.update({"node_id": r["node_id"], "token": r["token"],
                  "name": r.get("name", ""), "capabilities": r.get("capabilities", []),
                  "enrolled": int(time.time()), "scheme": ctl.scheme})
    save_state(state)
    print(f"enrolled as node {r['node_id']} ({r.get('name')}) — "
          f"capabilities: {', '.join(r.get('capabilities') or []) or 'none'}")
    print(f"  credential in {NODE_JSON} (0600); jobs run as {opts['--user']}"
          + (f", sessions as {opts['--session-user']}" if opts["--session-user"] else ""))


def cmd_run():
    state = load_state()
    log(f"node {state.get('node_id')} → {state.get('controller')}, agent "
        f"{AGENT_VERSION} {own_digest()[:19]}…")
    Agent(state).loop()


def cmd_status():
    state = load_state()
    shown = {k: v for k, v in state.items() if k != "token"}
    print(json.dumps(shown, indent=2))
    ctl = Controller(state["controller"], state["token"], state.get("pin", ""))
    st, r = ctl.call("hello", {"census": census(state), "version": AGENT_VERSION,
                               "digest": own_digest()}, timeout=20)
    if st == 200:
        n = r.get("node") or {}
        cur = (r.get("agent") or {}).get("digest") == own_digest()
        print(f"controller answers: this is node {n.get('id')} ({n.get('name')}), "
              f"state {n.get('state')}; agent {'current' if cur else 'differs from the controller’s'}")
    else:
        print(f"controller: {st} {r.get('error', 'no answer')}")
        sys.exit(1)


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "enroll":
        cmd_enroll(argv[1:])
    elif cmd == "run":
        cmd_run()
    elif cmd == "status":
        cmd_status()
    elif cmd == "sample":
        print(json.dumps(Sampler().sample(load_state(), 0), indent=2))
    else:
        print(__doc__.split("Runs anywhere")[-1].strip() if cmd in ("", "-h", "--help")
              else f"unknown command {cmd}", file=sys.stderr)
        sys.exit(0 if cmd in ("", "-h", "--help") else 64)


if __name__ == "__main__":
    main(sys.argv[1:])
