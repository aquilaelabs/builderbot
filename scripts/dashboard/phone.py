#!/usr/bin/env python3
"""A physical phone on the end of wireless adb, and what to push to it.

Why wireless and not USB: there is no /dev/bus/usb in this container, and even
with it passed through the handset would have to be plugged into the server
rather than sitting on the desk. Android's Wireless debugging is the only way
in, and it works — the container is NAT'd on Docker's bridge, which blocks the
multicast `adb mdns` discovery needs but leaves outbound TCP alone, and
`adb connect` is outbound.

Three things about that arrangement drive the whole design:

- **The pairing port is not the connect port.** The phone shows one on the
  "Pair device with pairing code" screen and a different one on the Wireless
  debugging screen itself, and people reliably try the first.
- **The connect port moves.** Android picks a new one every time debugging is
  toggled, so a remembered port goes stale. `find_port` scans for it rather
  than asking the operator to go and read a number again.
- **adb calls a TCP phone an emulator.** `adb -e` selects it and `adb -d` does
  not, so nothing here may use those flags to tell the two apart — the serial
  is the only honest test, and an emulator's is emulator-NNNN.

The pairing itself is kept by adb in ~/.android, which is on the home volume,
so it survives a container restart and is a one-time cost rather than a
per-session one.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

run = None
write_json = None
STATE = None
FILE = None
WORKSPACE = None

# The window Android picks a wireless-debugging port from. Wider than it needs
# to be on any phone seen so far; a scan of it takes about a minute and only
# happens when the operator asks to connect.
PORT_LO, PORT_HI = 30000, 45000

# An IPv4 address and nothing else. This becomes an argument to adb, so it is
# validated here rather than trusted: the panel is a table of actions, not a
# command line.
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def configure(*, write_json, state, workspace):
    globals().update(write_json=write_json, STATE=Path(state),
                     WORKSPACE=Path(workspace))
    globals()["FILE"] = Path(state) / "phone.json"


_lock = threading.Lock()

# What the operator last connected to, so coming back after a restart is one
# tap rather than a trip to the phone's settings. The port is NOT kept: it
# moves, and a remembered one that no longer works is worse than none.
def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def save(d):
    write_json(FILE, d)


# The phone is kept on an adb server of its own, away from the default 5037
# that `bb emu` and a session's plain `adb` use.
#
# That is the boundary this whole module rests on. A session that runs `adb
# devices` talks to 5037 and sees the emulator and nothing else: not a rule it
# is asked to honour, an address it was never given. Reaching the phone means
# coming through `bb phone`, which asks the operator first.
#
# Honest about what it is: a session could set ANDROID_ADB_SERVER_PORT itself
# and go straight there. Inside one container, with Bash, nothing here can be
# a wall. What it can be is a door that is shut by default, so touching the
# phone is a deliberate act rather than an incidental one — the same bargain
# the sibling-project deny list makes.
ADB_PORT = os.environ.get("BB_PHONE_ADB_PORT", "5038")

# Which web-ext to use. A name normally, resolved on PATH; the test harness
# points it at its own stub by absolute path, so what the suite reports does
# not depend on whether the box it runs on happens to have the real one
# installed. That has already caught this out once.
WEBEXT_BIN = os.environ.get("BB_WEBEXT_BIN", "web-ext")


def _env():
    e = dict(os.environ)
    e["ANDROID_ADB_SERVER_PORT"] = ADB_PORT
    return e


def _adb(*args, timeout=30):
    """One adb command, on the phone's own server. Never `-e` or `-d` — see
    the module docstring."""
    try:
        p = subprocess.run(["adb", *args], capture_output=True, text=True,
                           timeout=timeout, env=_env())
        return {"code": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}
    except (OSError, subprocess.SubprocessError) as e:
        return {"code": 1, "out": str(e)}


def devices():
    """Everything attached, split by what it actually is.

    An emulator is emulator-NNNN. Anything else on this list reached us over
    TCP and is a real device, whatever adb's own -e/-d flags may think.
    """
    out = []
    for line in _adb("devices", "-l")["out"].splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line and " " not in line:
            continue
        serial = line.split()[0]
        state = line.split()[1] if len(line.split()) > 1 else "?"
        model = ""
        m = re.search(r"model:(\S+)", line)
        if m:
            model = m.group(1).replace("_", " ")
        out.append({"serial": serial, "state": state, "model": model,
                    "kind": "emulator" if serial.startswith("emulator-") else "phone"})
    return out


def phone():
    """The connected phone, or None. The first one that is not an emulator."""
    for d in devices():
        if d["kind"] == "phone" and d["state"] == "device":
            return d
    return None


def _valid_ip(ip):
    return bool(IP_RE.match(str(ip or ""))) and all(
        0 <= int(p) <= 255 for p in str(ip).split("."))


def _valid_port(p):
    try:
        n = int(p)
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= 65535 else 0


def pair(ip, port, code):
    """`adb pair`, with everything checked before it becomes an argument."""
    if not _valid_ip(ip):
        return {"error": f"not an IPv4 address: {ip}"}
    n = _valid_port(port)
    if not n:
        return {"error": f"not a port: {port}"}
    code = re.sub(r"\D", "", str(code or ""))
    if len(code) != 6:
        return {"error": "the pairing code is the six digits on the phone"}
    r = _adb("pair", f"{ip}:{n}", code, timeout=45)
    if "Successfully paired" not in r["out"]:
        return {"error": (r["out"].strip().splitlines() or ["pairing failed"])[-1]}
    d = load(); d["ip"] = ip; save(d)
    return {"ok": True, "message": r["out"].strip().splitlines()[-1]}


def find_port(ip, lo=PORT_LO, hi=PORT_HI):
    """Which port the phone is listening on for `adb connect`.

    Scanned rather than asked for. Android picks a new one every time wireless
    debugging is toggled, so the number on the phone's screen is only true
    until it is not, and sending the operator back to read it again each time
    is the kind of small friction that stops a thing being used. mDNS would
    answer this for free and cannot: multicast does not cross the bridge this
    container is NAT'd behind.
    """
    if not _valid_ip(ip):
        return None
    found = []

    def probe(p):
        if found:
            return
        s = socket.socket()
        s.settimeout(0.35)
        try:
            if s.connect_ex((ip, p)) == 0:
                found.append(p)
        except OSError:
            pass
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=400) as pool:
        pool.map(probe, range(lo, hi + 1))
    return found[0] if found else None


def connect(ip, port=None):
    """Connect, finding the port when one is not given."""
    if not _valid_ip(ip):
        return {"error": f"not an IPv4 address: {ip}"}
    # A port that was given and is nonsense is an error, not a reason to go
    # looking: scanning would paper over a typo and connect to something the
    # operator did not ask for.
    if port not in (None, "", 0):
        n = _valid_port(port)
        if not n:
            return {"error": f"not a port: {port}"}
    else:
        n = find_port(ip)
        if not n:
            return {"error": f"nothing on {ip} is listening for adb — is "
                             "wireless debugging still on? It hands out a new "
                             "port every time it is toggled."}
    r = _adb("connect", f"{ip}:{n}", timeout=30)
    if "connected to" not in r["out"]:
        return {"error": (r["out"].strip().splitlines() or ["connect failed"])[-1]}
    d = load(); d["ip"] = ip; save(d)
    return {"ok": True, "serial": f"{ip}:{n}"}


def disconnect(serial=""):
    p = phone()
    target = serial or (p or {}).get("serial") or ""
    if not target:
        return {"error": "no phone is connected"}
    _adb("disconnect", target, timeout=15)
    return {"ok": True}


# ---- what there is to push -------------------------------------------------
# Discovered rather than browsed to. The dashboard has no file browser and
# should not grow one for this; it already knows what the projects are, and a
# WebExtension announces itself with a manifest. So the card can offer "the
# extension in StreamLift, last changed two hours ago" instead of asking
# somebody to remember a path.
#
# Bounded deliberately: three levels down, skipping the directories that are
# always large and never the answer. A source tree is not a haystack to search
# exhaustively, and this runs when the card asks rather than on the poll.
SKIP_DIRS = {"node_modules", ".git", "web-ext-artifacts", "build", "dist",
             ".venv", "venv", "target", ".gradle", "__pycache__"}
MAX_DEPTH = 3


def _manifest_is_extension(path):
    """A WebExtension manifest, as opposed to any other manifest.json.

    npm, Android and half the tooling in existence use that filename, so the
    test is the field only a browser extension has.
    """
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or "manifest_version" not in d:
        return None
    if not isinstance(d.get("name"), str):
        return None
    return {"name": d.get("name", ""), "version": str(d.get("version", "")),
            "mv": d.get("manifest_version")}


def _newest(dirpath, cap=3000):
    """When this source last changed. Capped: a runaway tree must not turn a
    card refresh into a filesystem walk of the whole share."""
    newest, seen = 0, 0
    for p in Path(dirpath).rglob("*"):
        if seen >= cap:
            break
        parts = set(p.parts)
        if parts & SKIP_DIRS:
            continue
        try:
            if p.is_file():
                seen += 1
                newest = max(newest, int(p.stat().st_mtime))
        except OSError:
            continue
    return newest


def extensions(projects=()):
    """Every WebExtension source directory across the projects, newest first.

    `projects` is the list the dashboard already has, so this never decides for
    itself what a project is — one rule for that, and it lives elsewhere.
    """
    out = []
    for name in projects:
        root = WORKSPACE / name
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            mf = d / "manifest.json"
            if mf.is_file():
                info = _manifest_is_extension(mf)
                if info:
                    out.append({
                        "project": name,
                        # Relative, because that is what the operator reads and
                        # what the server validates a push against.
                        "path": str(d.relative_to(WORKSPACE)),
                        "name": info["name"], "version": info["version"],
                        "mv": info["mv"], "changed": _newest(d)})
                    continue        # no nesting an extension inside an extension
            if depth >= MAX_DEPTH:
                continue
            try:
                for c in d.iterdir():
                    if c.is_dir() and not c.name.startswith(".") \
                            and c.name not in SKIP_DIRS:
                        stack.append((c, depth + 1))
            except OSError:
                continue
    return sorted(out, key=lambda e: -e["changed"])


# ---- pushing one to the phone ----------------------------------------------
# `web-ext run` is Mozilla's own tool and the only supported way in: an XPI is
# not an APK, so `adb install` is not it, and Firefox for Android will not take
# an extension off the filesystem. web-ext drives adb plus Firefox's remote
# debugging socket to install the add-on TEMPORARILY — it is gone when Firefox
# restarts, which is the development loop rather than an install.
#
# It stays running on purpose. The process watches the source and reloads the
# add-on on every change, which is the thing that makes it worth a button, and
# stopping it is how you end the session.
_job = {"running": False, "what": "", "serial": "", "apk": "", "state": "",
        "error": "", "lines": [], "started": 0}
_proc = None

# The line web-ext prints when the add-on is actually on the phone. Everything
# before it is preparation, and reporting success earlier would be the same
# mistake `bb emu start` was making with wait-for-device.
INSTALLED = "as a temporary add-on"

# What this will drive, most-preferred first. A table rather than a field: the
# panel picks from what is installed on the device, and nothing else reaches
# the command line.
FIREFOX_APKS = ("org.mozilla.firefox_beta", "org.mozilla.fenix",
                "org.mozilla.firefox", "org.mozilla.firefox_nightly")


def firefox_apks(serial):
    """Which of the Firefoxes we know about are on the device."""
    if not serial:
        return []
    out = _adb("-s", serial, "shell", "pm", "list", "packages", timeout=20)["out"]
    have = {ln.strip().replace("package:", "") for ln in out.splitlines()}
    return [a for a in FIREFOX_APKS if a in have]


def push_state():
    with _lock:
        return dict(_job, lines=list(_job["lines"])[-12:])


def _reader(proc):
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip()
        if not line:
            continue
        with _lock:
            _job["lines"].append(line)
            del _job["lines"][:-40]
            if INSTALLED in line:
                _job["state"] = "running"
            elif _job["state"] == "starting" and line.lower().startswith("error"):
                _job["error"] = line
    proc.wait()
    with _lock:
        if _job["state"] != "running" and not _job["error"]:
            _job["error"] = "web-ext stopped before the add-on was installed"
        _job["running"] = False
        _job["state"] = "stopped"


def push(source, serial, apk):
    """Start web-ext against a discovered source directory.

    Every argument is checked against something the server already knows —
    the discovered extensions, the attached devices, the Firefoxes on the
    phone — rather than taken as given. This is one of the few places the web
    UI causes a program to run, and the house rule is that such a thing is a
    lookup and not a command line.
    """
    import shutil
    if shutil.which(WEBEXT_BIN) is None:
        return {"error": "web-ext is not installed. Add it to EXTRA_NPM_PACKAGES "
                         "on the container and restart — installing it by hand "
                         "here would not survive an image update."}
    with _lock:
        if _job["running"]:
            return {"error": f"already pushing {_job['what']} — stop it first"}
    d = (WORKSPACE / source).resolve()
    if not str(d).startswith(str(WORKSPACE) + "/") or not (d / "manifest.json").is_file():
        return {"error": f"not an extension source directory: {source}"}
    if apk not in FIREFOX_APKS:
        return {"error": f"not a Firefox this knows: {apk}"}
    if not any(x["serial"] == serial and x["kind"] == "phone" for x in devices()):
        return {"error": "that phone is not connected"}
    # --adb-port so web-ext talks to the phone's server rather than the
    # default one, which does not have the phone on it.
    cmd = [WEBEXT_BIN, "run", "--target=firefox-android", f"--adb-port={ADB_PORT}",
           f"--adb-device={serial}", f"--firefox-apk={apk}",
           f"--source-dir={d}", "--no-input", "--adb-remove-old-artifacts"]
    global _proc
    with _lock:
        _job.update(running=True, what=source, serial=serial, apk=apk,
                    state="starting", error="", lines=[], started=int(time.time()))
    try:
        _proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 cwd=str(d), start_new_session=True, env=_env())
    except OSError as e:
        with _lock:
            _job.update(running=False, state="stopped", error=str(e))
        return {"error": str(e)}
    threading.Thread(target=_reader, args=(_proc,), daemon=True).start()
    return {"ok": True}


def stop_push():
    """End the session. The add-on goes with it on the next Firefox restart —
    it was never installed in the lasting sense."""
    global _proc
    p = _proc
    if p is None or p.poll() is not None:
        with _lock:
            _job.update(running=False, state="stopped")
        return {"ok": True}
    try:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    except OSError:
        pass
    with _lock:
        _job.update(running=False, state="stopped")
    return {"ok": True}


def payload(projects=()):
    """Everything the card shows, in one answer."""
    import shutil
    p = phone()
    # Whether a push is possible at all. Reported rather than discovered on
    # click, so the button can ghost with the reason on it — the same way the
    # git commands ghost outside a repo. A control that looks alive and then
    # explains itself only once pressed is a worse control.
    return {"devices": devices(), "phone": p, "asks": requests_open(),
            "webext": shutil.which(WEBEXT_BIN) is not None,
            "ip": load().get("ip", ""),
            "apks": firefox_apks((p or {}).get("serial", "")),
            "extensions": extensions(projects),
            "push": push_state()}


# ---- asking first ----------------------------------------------------------
# Anything a session wants to do to the phone is submitted here and waits for
# the operator to allow it. The session never runs the command itself — it
# describes what it wants, and on approval THIS process runs it and hands back
# the output. So "did Claude touch my phone" has one answer and it is on the
# card.
#
# A reason is required rather than optional. "adb shell pm uninstall x" with no
# explanation is a decision the operator has to reverse-engineer under time
# pressure, which is how people click Allow on things they should not.
#
# In memory and not on disk, deliberately: a request that outlived a restart
# would be a question about a moment that has passed, answered blind.
_reqs = []
_req_seq = 0
MAX_REQS = 20

# How long a session will wait before giving up. Long enough to walk to the
# dashboard, short enough that a forgotten request does not hold a session
# open forever.
WAIT_SECONDS = 300


def _req_public(r):
    return {"id": r["id"], "at": r["at"], "why": r["why"], "cmd": r["cmd"],
            "state": r["state"], "by": r["by"]}


def requests_open():
    with _lock:
        return [_req_public(r) for r in _reqs if r["state"] == "pending"]


def ask(why, argv, by="claude"):
    """A session asking to reach the phone. Returns the request's id."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for — the operator is answering a "
                         "question about a command they did not write"}
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) for a in argv):
        return {"error": "nothing to run"}
    if len(argv) > 40 or any(len(a) > 500 for a in argv):
        return {"error": "that command is too long to put in front of somebody"}
    if not phone():
        return {"error": "no phone is connected"}
    global _req_seq
    with _lock:
        _req_seq += 1
        r = {"id": _req_seq, "at": int(time.time()), "why": why,
             "cmd": list(argv), "state": "pending", "by": by,
             "out": "", "code": None}
        _reqs.append(r)
        del _reqs[:-MAX_REQS]
    return {"ok": True, "id": r["id"]}


def _find(rid):
    for r in _reqs:
        if r["id"] == rid:
            return r
    return None


def decide(rid, allow):
    """The operator's answer. Allowing runs it here, so the session never
    reaches the phone itself."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return {"error": "not a request"}
    with _lock:
        r = _find(rid)
        if r is None:
            return {"error": "no such request"}
        if r["state"] != "pending":
            return {"error": f"that one was already {r['state']}"}
        r["state"] = "running" if allow else "denied"
    if not allow:
        return {"ok": True}
    res = _adb(*r["cmd"], timeout=120)
    with _lock:
        r.update(state="done", out=res["out"][-8000:], code=res["code"])
    return {"ok": True}


def outcome(rid):
    """What became of a request, for the session that is waiting on it."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return {"error": "not a request"}
    with _lock:
        r = _find(rid)
        if r is None:
            return {"error": "no such request"}
        return {"ok": True, "state": r["state"], "out": r["out"],
                "code": r["code"], "why": r["why"]}
