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

Runs anywhere Python 3.8+ is, with nothing installed:

    builderbot-agent enroll --controller URL --token bbe_… [--user bb]
                            [--store data=/path] [--pin sha256:…]
    builderbot-agent run            # the loop; what the unit runs
    builderbot-agent status         # what this node is, and does it answer
"""
import contextlib
import glob
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request

AGENT_VERSION = "17"
PROTOCOL = 1
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
# The Actions runner as a per-node service (docs/nodes.md §14, phase 7):
# where it lives, and — for the tests — a tarball to unpack instead of the
# GitHub release download.
RUNNER_DIR = os.environ.get("BUILDERBOT_RUNNER_DIR", "/var/lib/builderbot/runner")
RUNNER_TARBALL = os.environ.get("BUILDERBOT_RUNNER_TARBALL", "")
RUNNER_RELEASES = "https://api.github.com/repos/actions/runner/releases/latest"
# Tailscale, for Funnel (docs/nodes.md §7, phase 8): a seam so the tests can
# stand in for it, like the rest of the tools the agent drives.
TAILSCALE_BIN = os.environ.get("BUILDERBOT_TAILSCALE_BIN", "tailscale")


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


def store_id(path):
    """A stable id for a store, from a marker inside it — the same file the
    controller reads for its own (nodes.store_id).

    Two machines mounting one share cannot recognize each other by path: the
    controller reaches the SDK share through Unraid's FUSE layer while this
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
# relative to the store (bb sdk's layout), for the census to find without
# PATH knowing about it. `android` is a directory, not a command.
STORE_TOOLS = {"java": ("jdk/bin/java",), "flutter": ("flutter/bin/flutter",),
               "dotnet": ("dotnet/dotnet",), "go": ("go/bin/go",),
               "node": ("node/bin/node",), "swift": ("swift/usr/bin/swift",),
               "cargo": ("rust/cargo/bin/cargo",),
               "android-sdk": ("android/cmdline-tools", "android/platform-tools"),
               "emulator": ("android/emulator/emulator",)}


def _toolchains(state):
    """What this node can build with: on PATH, or in its packages store.
    The census's `toolchains` is what package-build placement selects on."""
    tc = {}
    store = (state.get("stores") or {}).get("packages") or ""
    def find(name):
        for rel in STORE_TOOLS.get(name, ()):
            p = os.path.join(store, rel)
            if store and os.path.exists(p):
                return p
        return shutil.which(name)
    j = find("java")
    if j:
        m = re.search(r'version "([^"]+)"', _run([j, "-version"]))
        tc["java"] = m.group(1) if m else "present"
    for name in ("flutter", "dotnet", "node", "go", "swift", "cargo"):
        p = find(name)
        if p and os.path.isfile(p):
            arg = "version" if name == "go" else "--version"
            key = "rust" if name == "cargo" else name
            tc[key] = _clean_version((_run([p, arg], timeout=20).splitlines() or [""])[0])
    if find("android-sdk"):
        tc["android-sdk"] = "present"
    if find("emulator"):
        tc["emulator"] = "present"
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


def store_dirs(state):
    """What is actually IN the packages store, as directory names.

    The census's `toolchains` above is a placement summary — six names, so a
    job can select on them — and it was being read as an inventory of the
    whole catalog, which called four installed packages missing on a store
    the controller could see for itself. `bb sdk` puts each package in
    <root>/<name>, and android's parts under <root>/android/, so the names
    ARE the inventory and this is one listdir.
    """
    store = (state.get("stores") or {}).get("packages") or ""
    out = {"top": [], "android": []}
    if not store:
        return out
    with contextlib.suppress(OSError):
        out["top"] = sorted(x for x in os.listdir(store) if not x.startswith("."))[:64]
    with contextlib.suppress(OSError):
        out["android"] = sorted(os.listdir(os.path.join(store, "android")))[:64]
    return out


def sdk_env(state, who=None):
    """The environment a bb verb runs with on this node: the packages store
    as the SDK root, its android/ directory as ANDROID_HOME, its jdk as
    JAVA_HOME, the tools on PATH, and AVDs under the data store. What the
    image gets from its Dockerfile, a node gets from here."""
    stores = state.get("stores") or {}
    store = stores.get("packages") or ""
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8"}
    if store:
        android = os.path.join(store, "android")
        jdk = os.path.join(store, "jdk")
        env.update({"SDK_ROOT": store, "BUILDER_HOME": store, "BB_NODE_PACKAGES": "1",
                    "ANDROID_HOME": android, "ANDROID_SDK_ROOT": android})
        if os.path.isdir(jdk):
            env["JAVA_HOME"] = jdk
        env["PATH"] = ":".join([os.path.join(jdk, "bin"),
                                os.path.join(android, "cmdline-tools", "latest", "bin"),
                                os.path.join(android, "platform-tools"),
                                os.path.join(android, "emulator"), env["PATH"]])
    env["ANDROID_AVD_HOME"] = os.path.join(stores.get("data") or "/tmp", "avd")
    return env


def sdk_versions(state):
    """What `bb sdk versions` reports on this node: {name: version}.

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
    store = (state.get("stores") or {}).get("packages") or ""
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
            p = subprocess.run(["bash", bb, "sdk", "versions"], capture_output=True,
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
        "gpu": gpu.splitlines()[0][:80] if gpu else "",
        "sshd": _sshd_listening(),
        "stores": _stores(state.get("stores"), used=True),
        "toolchains": tc,
        "store_dirs": store_dirs(state),
        # The configuration plane's reported half (docs/nodes.md §12): what
        # is mounted and from where, and the address this machine is on.
        # The row draws the operator's desired config against these.
        "sandbox": os.access(SANDBOX_BIN, os.X_OK),
        "mounts": mounts_now(),
        "network": network_now(),
        # The same report the controller makes for itself, so one store is
        # not described two ways (roadmap #19).
        "packages_versions": sdk_versions(state),
        "services": services_now(),
    }


def services_now():
    """The managed services on this node and their state — today the
    Actions runner: registered as what, with which labels, and whether its
    listener is up. Read from the runner's own files, so a runner installed
    by hand reports the same way one installed from the tab does."""
    out = {}
    cfg = os.path.join(RUNNER_DIR, ".runner")
    if os.path.isfile(cfg):
        try:
            # utf-8-sig, not utf-8: GitHub's config.sh writes .runner with a
            # BOM, and json.load on a plain utf-8 handle raises on it. That
            # fell into the except below and reported a correctly registered
            # runner as one whose name "did not come back" — indistinguishable
            # from the genuinely half-installed state this census exists to
            # tell apart.
            with open(cfg, encoding="utf-8-sig") as f:
                j = json.load(f)
        except (OSError, ValueError):
            j = {}
        labels = []
        with contextlib.suppress(OSError):
            with open(os.path.join(RUNNER_DIR, ".builderbot-labels")) as f:
                labels = [x for x in f.read().split(",") if x]
        pg = _run(["pgrep", "-f", os.path.join(RUNNER_DIR, "bin/Runner.Listener")])
        out["actions-runner"] = {"installed": True, "name": str(j.get("agentName") or "")[:80],
                                 "url": str(j.get("gitHubUrl") or "")[:200],
                                 "labels": labels[:16], "active": bool(pg),
                                 "busy": bool(_run(["pgrep", "-f", os.path.join(RUNNER_DIR, "bin/Runner.Worker")]))}
    else:
        out["actions-runner"] = {"installed": False}
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
    return [m for m in got if isinstance(m, dict)] if isinstance(got, list) else []


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
    except OSError:
        raise SystemExit(f"{NODE_JSON} is missing — enroll this node first: "
                         "builderbot-agent enroll --controller URL --token …")
    except ValueError as e:
        raise SystemExit(f"{NODE_JSON} is not JSON ({e}); enroll again")


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

    def run(self):
        spec = self.job.get("spec") or {}
        error = ""
        try:
            if self.job.get("type") == "self-update":
                state, code = self.agent.self_update(self, spec)
            elif self.job.get("type") == "system":
                state, code = self.agent.system(self, spec)
            elif self.job.get("type") == "compose":
                state, code = self.agent.compose(self, spec)
            elif self.job.get("type") == "package":
                state, code = self.agent.package(self, spec)
            elif self.job.get("type") == "cache-clear":
                state, code = self.agent.cache_clear(self, spec)
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
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "LANG": "C.UTF-8", "BUILDERBOT_NODE": self.agent.state.get("node_id", ""),
               "BUILDERBOT_JOB": self.job["id"]}
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
            env.update(sdk_env(self.agent.state))
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

    # -- privilege ---------------------------------------------------------
    def drop_privileges(self, env):
        """Popen keywords that make the child the enrolled account — empty
        when there is nothing to drop (not root, or enrolled as root on
        purpose). Popen's own user/group/extra_groups rather than a
        preexec_fn: this process has job threads, and a fork hook that runs
        between fork and exec can deadlock on a lock another thread held."""
        user = self.state.get("user") or ""
        if os.geteuid() != 0 or not user or user == "root":
            return {}
        import grp
        import pwd
        try:
            pw = pwd.getpwnam(user)
        except KeyError:
            raise RuntimeError(f"enrolled account {user!r} does not exist here")
        env.update({"HOME": pw.pw_dir, "USER": user, "LOGNAME": user})
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        return {"user": pw.pw_uid, "group": pw.pw_gid, "extra_groups": groups}

    # -- the channel -------------------------------------------------------
    def hello(self):
        # `running` is the list of job ids this process still holds. The
        # controller reconciles against it: a job its row says is running
        # here that this agent does not know was lost with a restart, and is
        # failed there rather than left running forever (docs/nodes.md §9).
        st, r = self.ctl.call("hello", {"census": census(self.state),
                                        "version": AGENT_VERSION,
                                        "digest": own_digest(),
                                        "running": self.running_ids()}, timeout=30)
        if st == 200:
            self.hello_at = time.time()
            self.poll = int(r.get("poll") or 25)
            self.controller_digest = (r.get("agent") or {}).get("digest") or ""
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
        return st, r

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
            n = self.running()
            # The controller counts what is running here from its own rows
            # and wakes a held poll when a job ends, so the poll is held at
            # full length whether or not anything is running. The count in
            # the sample is for the row's numbers, not for placement.
            wait = self.poll
            st, r = self.ctl.call("work", {"sample": self.sampler.sample(self.state, n),
                                           "running": n, "wait": wait},
                                  timeout=wait + 15)
            if st == 204:
                continue
            if st == 200 and r.get("cancel"):
                # Not a job: the ids of jobs here the operator has stopped.
                self.cancel([str(i) for i in r["cancel"]])
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
            for d, dirs, files in os.walk(os.path.dirname(ws)):
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
        could not be fetched. Shared by package jobs and bb verbs."""
        store = (self.state.get("stores") or {}).get("packages") or ""
        if not store:
            job.say("refused: this node has no packages store\n")
            return ""
        self.own_dir(store, who)
        bbdir = os.path.join(store, ".bb")
        os.makedirs(bbdir, exist_ok=True)
        tar_path = os.path.join(bbdir, "bundle.tar")
        st, digest = self.ctl.fetch("download?what=bundle", tar_path)
        if st != 200:
            job.say(f"could not fetch bb from the controller ({st})\n")
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
            job.say(f"bb {hexd[:12]} unpacked into {into}\n")
        if who:
            for d, dirs, files in os.walk(into):
                for x in [d] + [os.path.join(d, f) for f in files]:
                    with contextlib.suppress(OSError):
                        os.lchown(x, who["user"], who["group"])
        return into

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
                job.say(f"could not make {d}: {e.strerror}\n")
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
        """`bb sdk install|remove NAME` against this node's packages store,
        with the bb the controller ships: the bundle (bb, its library, the
        catalog) is fetched by digest into the store and run from there as
        the enrolled account, SDK_ROOT pointing at the store. One catalog,
        per-node state — the census reports what landed."""
        stores = self.state.get("stores") or {}
        store = stores.get("packages") or ""
        if not store:
            job.say("refused: this node has no packages store\n")
            return "failed", 78
        action = spec.get("action")
        names = [re.sub(r"[^A-Za-z0-9:;._-]", "", str(n)) for n in (spec.get("names") or [])][:8]
        if action not in ("install", "remove") or not names:
            job.say("refused: a package job installs or removes named packages\n")
            return "failed", 64
        who = self.drop_privileges({})
        into = self.bundle(job, who)
        if not into:
            return "failed", 69
        bad = 0
        for name in names:
            job.say(f"== bb sdk {action} {name}\n")
            st_, code = job.exec({"argv": ["bash", os.path.join(into, "scripts", "bb"),
                                            "sdk", action, name],
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

    # -- the configuration plane (docs/nodes.md §12, phase 5) -----------------
    def system(self, job, spec):
        """Apply the desired storage or network config the controller holds
        for this node — the one root-privileged thing the agent does. Not
        dropped to the enrolled account, because mounts and addresses are
        root's; offered by the controller only to nodes that enrolled as a
        sandbox, and refused here without bb-sandbox, which is the stamp."""
        if not os.access(SANDBOX_BIN, os.X_OK):
            job.say("refused: this node was not provisioned as a BuilderBot sandbox "
                    f"({SANDBOX_BIN} is not here), so it takes no system jobs\n")
            return "failed", 77
        what = spec.get("apply")
        cfg = spec.get("config") if isinstance(spec.get("config"), dict) else {}
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

    def _apply_storage(self, job, cfg):
        """Mounts as a diff against what bb-sandbox has — remove what is no
        longer wanted, add or rewrite what is (add-nfs/add-share rewrite an
        existing fstab line, so this is idempotent) — then the stores, which
        are this agent's own file. Ends with a hello, so the row shows the
        applied state now rather than at the next census."""
        want = [m for m in (cfg.get("mounts") or []) if isinstance(m, dict)]
        have = {m.get("path"): m for m in mounts_now()}
        bad = 0
        for path, m in have.items():
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
        if size is not None:
            free = shutil.disk_usage(new).free
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
        if self._sh(job, ["cp", "-a", os.path.join(old, "."), new + "/"], timeout=21600) != 0:
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
                    + (f" — the old copy is in there; remove it yourself when you are "
                       f"satisfied the move worked\n" if "empty" in (why or "").lower()
                       else "\n"))

    def _apply_network(self, job, cfg):
        """Commit/confirm, because this is the one change that can cut the
        cord it arrives on (docs/nodes.md §12): write the netplan file,
        apply it, then dial the controller from wherever the machine landed.
        No answer within DIAL_BACK_S and the previous file is put back and
        applied again, and the failure is reported on reconnect."""
        if not shutil.which(NETPLAN_BIN) and not os.access(NETPLAN_BIN, os.X_OK):
            job.say("refused: network changes need netplan on this node, and it "
                    "has none — set the address by hand, or on a node that has it\n")
            return "failed", 77
        net = cfg.get("network") if isinstance(cfg.get("network"), dict) else cfg
        iface = str(net.get("interface") or network_now().get("interface") or "")
        if not iface:
            job.say("refused: no interface named and no default route to read one from\n")
            return "failed", 65
        mode = "static" if net.get("mode") == "static" else "dhcp"
        lines = ["network:", "  version: 2", "  ethernets:", f"    {iface}:"]
        if mode == "dhcp":
            lines.append("      dhcp4: true")
        else:
            addr, gw = str(net.get("address") or ""), str(net.get("gateway") or "")
            if not addr:
                job.say("refused: a static address needs an address\n")
                return "failed", 65
            lines += ["      dhcp4: false", f"      addresses: [{addr}]"]
            if gw:
                lines += ["      routes:", f"        - to: default", f"          via: {gw}"]
            dns = [str(d) for d in (net.get("dns") or []) if str(d)]
            if dns:
                lines += ["      nameservers:", f"        addresses: [{', '.join(dns)}]"]
        text = "\n".join(lines) + "\n"
        path = os.path.join(NETPLAN_DIR, NETPLAN_FILE)
        before = None
        try:
            with open(path) as f:
                before = f.read()
        except OSError:
            pass
        if before == text:
            job.say("already applied — the netplan file has not changed\n")
            return "succeeded", 0
        os.makedirs(NETPLAN_DIR, exist_ok=True)
        with open(path, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
        job.say(f"wrote {path}:\n{text}")
        job.flush()                      # the last words before the cord is cut
        if self._sh(job, [NETPLAN_BIN, "apply"]) != 0:
            self._restore_netplan(job, path, before)
            return "failed", 1
        job.say(f"applied; dialing the controller back from the new address "
                f"(up to {DIAL_BACK_S}s)\n")
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            st, _ = self.hello()
            if st == 200:
                job.say(f"dialed back in from {network_now().get('addresses') or ['?']}\n")
                return "succeeded", 0
            time.sleep(5)
        job.say(f"could not reach the controller within {DIAL_BACK_S}s — reverting\n")
        self._restore_netplan(job, path, before)
        deadline = time.time() + DIAL_BACK_S
        while time.time() < deadline:
            if self.hello()[0] == 200:
                break
            time.sleep(5)
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
        d = RUNNER_DIR
        if not want:
            if not os.path.isfile(os.path.join(d, ".runner")):
                job.say("no runner is installed here\n")
                return "succeeded", 0
            st, r = self.ctl.call("runner-token", {"kind": "remove"}, timeout=60)
            if st != 200 or not r.get("token"):
                job.say(f"could not get a removal token from the controller: {r.get('error', st)}\n")
                return "failed", 69
            if os.path.isfile(os.path.join(d, "svc.sh")):
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "remove", "--token", r["token"]])
            if code != 0:
                job.say("deregistration did not complete; remove the runner in GitHub's settings if it lingers\n")
            shutil.rmtree(d, ignore_errors=True)
            self.hello()
            job.say("runner removed\n")
            return "succeeded", 0
        url = str(cfg.get("url") or "")
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
                arch = {"x86_64": "x64", "aarch64": "arm64", "armv7l": "arm"}.get(platform.machine(), "x64")
                job.say("asking GitHub for the latest runner release…\n")
                try:
                    with urllib.request.urlopen(RUNNER_RELEASES, timeout=30) as r:
                        rel = json.load(r)
                    asset = next(a["browser_download_url"] for a in rel.get("assets", [])
                                 if a.get("name", "").startswith(f"actions-runner-linux-{arch}-")
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
            for dd, dirs, files in os.walk(d):
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
        if os.path.isfile(os.path.join(d, ".runner")):
            job.say("a runner is already configured here; clearing it before reinstalling\n")
            if os.path.isfile(os.path.join(d, "svc.sh")):
                self._sh(job, ["bash", "./svc.sh", "stop"], cwd=d)
                self._sh(job, ["bash", "./svc.sh", "uninstall"], cwd=d)
            st, rr = self.ctl.call("runner-token", {"kind": "remove"}, timeout=60)
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
        st, r = self.ctl.call("runner-token", {"kind": "registration"}, timeout=60)
        if st != 200 or not r.get("token"):
            job.say(f"could not get a registration token from the controller: {r.get('error', st)}\n")
            return "failed", 69
        job.say(f"registering {name} with {url} [{','.join(labels)}]\n")
        code = self._run_as(job, who, d, [os.path.join(d, "config.sh"), "--unattended", "--replace",
                                          "--url", url, "--token", r["token"], "--name", name,
                                          "--labels", ",".join(labels), "--work", "_work"])
        if code != 0:
            return "failed", code
        with open(os.path.join(d, ".builderbot-labels"), "w") as f:
            f.write(",".join(labels))
        if os.path.isfile(os.path.join(d, "svc.sh")):
            for verb in (["install", user], ["start"]):
                if self._sh(job, ["bash", "./svc.sh", *verb], cwd=d) != 0:
                    # Registered but not serviced is a real state, and the
                    # row should say so rather than showing nothing: the
                    # census reads .runner, which exists by now.
                    self.hello()
                    job.say("the runner is registered with GitHub but its service did "
                            "not install — it will not pick up jobs until it does\n")
                    return "failed", 1
        self.hello()
        job.say("runner installed and started\n")
        return "succeeded", 0

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

    def _restore_netplan(self, job, path, before):
        if before is None:
            with contextlib.suppress(OSError):
                os.remove(path)
        else:
            with open(path, "w") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(before)
        self._sh(job, [NETPLAN_BIN, "apply"])

    def reexec(self):
        log("re-executing the new agent")
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "run"])


# ---------------------------------------------------------------------------
# commands

def cmd_enroll(args):
    opts = {"--controller": "", "--token": "", "--user": "bb", "--pin": ""}
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
    print(f"  credential in {NODE_JSON} (0600); jobs run as {opts['--user']}")


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
