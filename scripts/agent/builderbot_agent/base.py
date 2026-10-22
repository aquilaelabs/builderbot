"""What every part of the agent shares: the constants naming the node's paths and tools, the log, and the small runners of a command."""
import contextlib
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time


# Where the enrollment lands. Overridable for tests, which run a throwaway
# agent against a throwaway controller and must not touch /etc.
NODE_JSON = os.environ.get("BUILDERBOT_NODE_JSON", "/etc/builderbot/node.json")
DEFAULT_STORES = {"data": "/var/lib/builderbot/data",
                  "toolchains": "/var/lib/builderbot/toolchains",
                  "cache": "/var/lib/builderbot/cache",
                  # What this node keeps of a project's built artifacts, so
                  # an emulator or a container here starts from a local copy
                  # rather than pulling one over the link every time, which
                  # is free on a LAN and is not on a node in somebody's
                  # cloud. Per project underneath (artifact_dir), because a
                  # VM may be several projects' node.
                  "artifacts": "/var/lib/builderbot/artifacts",
                  # What a dev instance KEEPS: the databases, the uploads, the
                  # caches its containers write, under <appdata>/<project>/
                  # <instance>. A store like the other four (R17 step 2), so
                  # the node reports its path and its headroom and the config
                  # plane edits it there. It used to be BB_DEV_DATA_DIR on the
                  # CONTROLLER, which is a fact about a node kept on the wrong
                  # machine, and an optional /devdata mount to go with it.
                  "appdata": "/var/lib/builderbot/appdata"}

# The session half (roadmap #24): the ttyd this node runs bb-tty under, the
# ports it binds, and the address. Seams for the suite, which runs a ttyd
# that only records what it was asked, and for a node whose ports are taken.
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
# How often a node whose loop is held by a census says it is still there
# (census_beating): well inside the controller's three missed polls.
BEAT_S = 20

# Where a store may NOT be put. The stores are directories this agent
# creates, fills, and (for the cache) empties on request, so a store
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


# Where the configuration plane's tools are (docs/nodes.md §12, phase 5).
# bb-sandbox is the one copy of the mount logic, installed by the provisioner:
# its presence is what says this node was set up as a sandbox, and a
# `system` job is refused without it. The netplan seams exist so the tests
# can stand in for both without a root shell.
SANDBOX_BIN = os.environ.get("BUILDERBOT_SANDBOX_BIN", "/usr/local/sbin/bb-sandbox")
# Where the agent's own unit is kept through a restart it did not ask for
# (B538): a systemd drop-in, and needrestart's configuration directory.
UNIT_DROPIN = "/etc/systemd/system/builderbot-agent.service.d/builderbot.conf"
NEEDRESTART_DIR = "/etc/needrestart"
# What the GPU display's unit last said (bb-sandbox gpu-display, R20): one
# line, read into the census so the row says it.
GPU_DISPLAY_STATE = os.environ.get("BUILDERBOT_GPU_DISPLAY_STATE", "/run/builderbot-gpu-display")
# The machine's sysfs, where the card and its driver are read from. The
# suite's is a tree of its own with a card in it, so what it checks does
# not depend on the box it runs on; lspci is not asked then.
SYS_ROOT = os.environ.get("BUILDERBOT_SYS_ROOT", "/sys")
# The NVIDIA driver's name in a toolchain job: alone, or with the package
# apt is to install after a colon (nvidia-driver:nvidia-driver-610-open).
DRIVER = "nvidia-driver"
# ...and the container toolkit, the second of the machine's own rows there.
TOOLKIT = "nvidia-container-toolkit"
# The session's view (R35): the root helper that builds it, the file that
# tells it this machine's layout, and the sudo rule that is the session
# account's only way to it. Installed and kept by this agent from the bundle,
# on a node set up as a sandbox; the seams are for the suite.
SESSION_BIN = os.environ.get("BUILDERBOT_SESSION_BIN", "/usr/local/sbin/bb-session")
# Where root keeps its own copy of the two tools it installs from a bundle
# (bb-sandbox out of the provisioner, and bb-session): root-owned, 0700,
# written from the tar as it is unpacked and never from the toolchain store,
# which belongs to the job account. Reading them from the store let any job,
# and so any session through bb run, plant root code that landed on the
# next hello (the review of 26 Sep).
TOOLS_DIR = os.environ.get("BUILDERBOT_TOOLS_DIR", "/var/lib/builderbot/agent/tools")
ROOT_TOOLS = ("nodes/provision-linux.sh", "nodes/bb-session")
# Where an updated Claude Code is pinned, root-owned, for the sessions (claude_update).
CLAUDE_DIR = "/usr/local/lib/builderbot/claude"
# ...and the other coding agents (R95 step 2), each in a folder of its own
# under this one: AGENTS_DIR/codex/codex, AGENTS_DIR/copilot/copilot.
AGENTS_DIR = os.environ.get("BUILDERBOT_AGENTS_DIR", "/usr/local/lib/builderbot/agents")
# How each is installed, by the job the controller's agent table names for
# it (scripts/dashboard/agents.py update_job): a table lookup, never a
# command from the controller. Each vendor's own installer, run as the
# session account into its home: `script` fetched fresh each time, the
# version asked for in `pin` (formatted with the version), `env` formatted
# with the home, and the binary it leaves at `bin` under the home. A test
# stands its own script in with BUILDERBOT_<ID>_INSTALLER. Checked against
# Codex CLI 0.163.0 and Copilot CLI 1.0.102 (22 Oct).
# Each coding agent's sign-in and sign-out jobs, by the controller's agent
# table (agents.py login_job, logout_job), to the agent `bb login --flow` and
# `bb login --out` are run for. Claude's are the claude-login and
# claude-logout of old, which name no agent.
AGENT_LOGINS = {"codex-login": "codex", "copilot-login": "copilot"}
AGENT_LOGOUTS = {"codex-logout": "codex", "copilot-logout": "copilot"}
AGENT_INSTALLS = {
    "codex-update": {"id": "codex", "command": "codex", "product": "Codex CLI", "reported": "codex",
                     "script": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
                     "pin": ("CODEX_RELEASE", "{v}"), "env": {"CODEX_INSTALL_DIR": "{home}/.local/bin"},
                     "bin": ".local/bin/codex"},
    "copilot-update": {"id": "copilot", "command": "copilot", "product": "Copilot CLI", "reported": "copilot",
                       "script": "curl -fsSL https://gh.io/copilot-install | bash",
                       "pin": ("VERSION", "v{v}"), "env": {"PREFIX": "{home}/.local"},
                       "bin": ".local/bin/copilot"},
}
SESSION_CONF = os.environ.get("BUILDERBOT_SESSION_CONF", "/etc/bb-session.conf")
SESSION_SUDOERS = os.environ.get("BUILDERBOT_SESSION_SUDOERS", "/etc/sudoers.d/builderbot-session")
# Each session kept to its own project's network (R79): the folder this agent
# shares with bb-session (its resolver file for sessions, its mark that the
# table is in place, and a file per session saying which project an address
# is), the table it keeps, the range sessions are addressed from, and the mark
# the table puts on what it let through, which is all Docker's forwarding is
# told to let past: a table that is gone lets nothing through, not everything.
SESSNET_DIR = os.environ.get("BUILDERBOT_SESSNET_DIR", "/run/bb-session-net")
SESSNET_TABLE = "builderbot_sessnet"
SESSNET_CIDR = "10.231.0.0/16"
SESSNET_MARK = 0x10000000
IPTABLES_BIN = os.environ.get("BUILDERBOT_IPTABLES_BIN", "iptables")
DOCKER_BIN = os.environ.get("BUILDERBOT_DOCKER_BIN", "docker")
RESOLV_UPSTREAM = ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf")
# What is not the internet: every private, shared, loopback, link-local and
# multicast range. A session reaches none of it but what the sets name.
SESSNET_LOCAL = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
                 "172.16.0.0/12", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/3")
# Where the node's synced copy of its projects is (R162), which is what a
# session works in. The seam is for the suite: it runs its agent as a session account, and inside a
# session's view /workspace is the view's own read-only root.
SHARE = os.environ.get("BUILDERBOT_SHARE", "/workspace")
# The pane a respawn may run again: bb-tty's launcher of a coding agent
# (claude-run.sh, codex-run.sh, copilot-run.sh, R95), in the project's
# cache folder and started inside the project's view when the node builds one.
_PATHCH = r"[A-Za-z0-9._/@+-]"
RESPAWNABLE = (rf"(?:sudo -n {re.escape(SESSION_BIN)} enter(?: --[a-z]+ {_PATHCH}+)* -- )?"
               rf"{_PATHCH}*/builderbot/(?:u/u_[0-9a-f]{{8}}/)?"
               rf"project/[A-Za-z0-9._-]+/(?:claude|codex|copilot)-run\.sh")
NETPLAN_DIR = os.environ.get("BUILDERBOT_NETPLAN_DIR", "/etc/netplan")
NETPLAN_BIN = os.environ.get("BUILDERBOT_NETPLAN_BIN", "netplan")
NETPLAN_FILE = "90-builderbot.yaml"
# How long a network change has to dial back in before it is reverted.
DIAL_BACK_S = 180
# How long after a ttyd start this will try another. A port already taken
# would otherwise spin the loop on a failing exec. Settable only so the suite
# can stop waiting on it: the test that proves a dead ttyd is started again
# waits exactly this long, and it was the slowest interval in the suite.
SESSION_RETRY_S = int(os.environ.get("BUILDERBOT_SESSION_RETRY_S") or 30)
# The Actions runner as a per-node service (docs/nodes.md §14, phase 7):
# where it lives, and, for the tests, a tarball to unpack instead of the
# GitHub release download.
RUNNER_DIR = os.environ.get("BUILDERBOT_RUNNER_DIR", "/var/lib/builderbot/runner")
# The machine's package manager, for a recipe's `system` packages. Seams for
# the suite, which must not touch the box it runs on.
APT_BIN = os.environ.get("BUILDERBOT_APT_BIN", "apt-get")
# Seconds per "minute" of the idle rule; the suite sets 1.
IDLE_UNIT = float(os.environ.get("BUILDERBOT_IDLE_UNIT", "60"))
# The session names a coding agent runs under (claude-<project>): the live
# rows of the controller's agent table (scripts/dashboard/agents.py, R95),
# copied rather than imported since the agent carries no dashboard module;
# unit/test_agents.py holds the two to each other.
AGENT_PREFIXES = ("claude-", "codex-", "copilot-")


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
# The other package managers and network backends this agent can drive:
# one pair per family, detected on the machine, never told by the
# controller. Each settable so the suite can point one at a stub or at a
# path that does not exist.
PACMAN_BIN = os.environ.get("BUILDERBOT_PACMAN_BIN", "pacman")
ZYPPER_BIN = os.environ.get("BUILDERBOT_ZYPPER_BIN", "zypper")
APK_BIN = os.environ.get("BUILDERBOT_APK_BIN", "apk")
XBPS_QUERY_BIN = os.environ.get("BUILDERBOT_XBPS_QUERY_BIN", "xbps-query")
# What apt's repositories carry, as opposed to what dpkg has installed: asked
# only to pick among a recipe's alternatives ("libasound2t64|libasound2").
APT_CACHE_BIN = os.environ.get("BUILDERBOT_APT_CACHE_BIN", "apt-cache")
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
# gitea/act_runner became gitea/runner upstream (the old address answers
# 301, the assets are gitea-runner-<ver>-<os>-<arch>); the binary keeps the
# act_runner command set, and keeps its name here.
ACT_RUNNER_RELEASES = "https://gitea.com/api/v1/repos/gitea/runner/releases/latest"


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


_said = {}


def log_once(key, msg, every=3600):
    """log(), but the same `msg` under `key` at most once per `every`
    seconds, with how many times it came up meanwhile. For a loop that
    meets the same fault on every tick: a sync step failing every five
    seconds was 17,000 identical journal lines a day (the operator, 12 Oct)."""
    now = time.monotonic()
    last, n, was = _said.get(key, (-1e9, 0, None))
    if msg == was and now - last < every:
        _said[key] = (last, n + 1, was)
        return
    log(msg + (f" (and {n} more times since)" if n and msg == was else ""))
    _said[key] = (now, 0, msg)


def hello_again(agent, why):
    """Ask the agent for a fresh hello with its reason in the journal
    (Agent.hello_again); a stand-in driven in a test has only the clock."""
    fn = getattr(agent, "hello_again", None)
    if fn:
        fn(why)
    else:
        agent.hello_at = 0


# The files a node writes itself, each kept to this and one earlier
# generation (cap_file): the terminal server's and the runners' were
# appended to for the life of the machine.
NODE_LOG_MAX = 16 * 1024 * 1024
RUNNER_DIAG_KEEP = 20       # newest files in a runner's _diag


def cap_file(path, limit=NODE_LOG_MAX):
    """Copy-truncate `path` into `path`.1 once it passes `limit`: the
    writers hold it open with O_APPEND, so they go on at the new end. True
    when it was cut."""
    try:
        if os.path.getsize(path) <= limit:
            return False
        shutil.copyfile(path, path + ".1")
        with open(path, "r+b") as f:
            f.truncate(0)
        return True
    except OSError:
        return False


def prune_dir(d, keep):
    """The newest `keep` files directly in `d`, the rest removed. How many."""
    try:
        files = sorted((e for e in os.scandir(d) if e.is_file()), key=lambda e: e.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    gone = 0
    for e in files[keep:]:
        with contextlib.suppress(OSError):
            os.unlink(e.path)
            gone += 1
    return gone


# Docker's json-file logs on a node, per container: three files of 20 MB.
CONTAINER_LOG_OPTS = {"max-size": "20m", "max-file": "3"}

# The bridge driver's option for a network's default bind address.
HOST_BINDING = "com.docker.network.bridge.host_binding_ipv4"


def daemon_json_with_ip(text, on):
    """/etc/docker/daemon.json as it should read with published ports bound
    to 127.0.0.1 by default (`ip`, docker's own default bind address) or not
    (R190): the file's other keys kept, a file that is not JSON left alone.
    Returns the new text, or None when nothing has to change."""
    try:
        d = json.loads(text) if text.strip() else {}
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    # Two keys: `ip` is the default bridge's, and every network compose makes
    # is a user-defined one, which takes its bind address from
    # default-network-opts instead (a hosting node, 11 Oct: with `ip` alone,
    # aquilaeLabs's 8380 and 8381 answered from the internet).
    want = "127.0.0.1" if on else None
    before = json.dumps(d, sort_keys=True)
    opts = d.get("default-network-opts") if isinstance(d.get("default-network-opts"), dict) else {}
    br = opts.get("bridge") if isinstance(opts.get("bridge"), dict) else {}
    if want is None:
        d.pop("ip", None)
        br.pop(HOST_BINDING, None)
    else:
        d["ip"] = want
        br[HOST_BINDING] = want
    if br:
        opts["bridge"] = br
    else:
        opts.pop("bridge", None)
    if opts:
        d["default-network-opts"] = opts
    else:
        d.pop("default-network-opts", None)
    # ...and every container's log bounded (the operator, 12 Oct): the
    # json-file driver keeps all of it by default, so a chatty container
    # filled the disk under /var/lib/docker. Only where nobody chose a
    # driver or its options: a node's own logging arrangement is kept.
    if d.get("log-driver", "json-file") == "json-file" and "log-opts" not in d:
        d["log-opts"] = dict(CONTAINER_LOG_OPTS)
    if json.dumps(d, sort_keys=True) == before:
        return None
    return json.dumps(d, indent=2) + "\n"


def own_path():
    """The file a node runs and a self-update writes over: the zip the
    controller shipped (this package inside it), or from a checkout the
    entry beside the package (bundle.py)."""
    outer = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return outer if os.path.isfile(outer) else os.path.join(outer, "builderbot-agent.py")


def own_digest():
    """The digest of what this process runs, as the controller names its own:
    the zip's bytes, or from a checkout the zip its sources make."""
    outer = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        if os.path.isfile(outer):
            with open(outer, "rb") as f:
                body = f.read()
        else:
            from .bundle import build
            body = build(outer)
        return "sha256:" + hashlib.sha256(body).hexdigest()
    except OSError:
        return ""


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

    _run cannot tell those apart (it hands back stdout or stderr and drops
    the status), so a binary that ABORTS on startup read as a tool that
    printed something odd, and _clean_version called that "present". The node
    then advertised a toolchain it cannot run, and the controller placed work
    there that could only fail on arrival. Measured on bb-sandbox-redhat,
    where the toolchain store's dotnet dies every census while the row said
    the node had .NET.

    Death by SIGNAL, or a probe that never comes back, is the line. A
    non-zero EXIT is not: `flutter --version` as root and rustup with no
    default toolchain both exit non-zero with a sentence, and both mean the
    tool is installed and being awkward, which is what "present" is for.

    There is no attempt to stop a crashing probe dumping core, because there
    is no way to from here. This ran under `ulimit -c 0` for one build on the
    theory that a version probe has no business leaving a core file, and the
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
    because the census runs every ten minutes and the interesting part (the
    tool's own first line, which is the whole diagnosis) does not change; a
    restart says it again, which is when somebody is looking anyway.
    """
    if name in _PROBE_SAID:
        return
    _PROBE_SAID.add(name)
    # The whole of what it said, newlines folded, not its first line, which
    # was the first cut of this and threw the answer away: .NET's startup
    # failures open with "Process terminated." on a line of their own and put
    # the reason on the next one, so the log carried the half that says
    # nothing and dropped the half somebody has to act on.
    said = " ".join((out or "").split())[:300]
    log(f"toolchain: {path} {why} when asked its version, so {name} is not in "
        f"this node's census" + (f". It said: {said}" if said else ""))


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
