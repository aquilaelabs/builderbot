#!/usr/bin/env python3
"""A physical phone on the end of wireless adb, driven from a node.

The controller carries no adb and holds no phone: whichever node has adb in
its store is where a handset is paired, connected and spoken to, and every
adb command here is a job on that node, waited for (nodes.run_wait). Several
nodes can each hold their own phone, and a project's sessions reach the one
on the project's node.

Why wireless and not USB: a node is a VM or somebody's machine, and the
handset sits on the desk. Android's Wireless debugging is the way in, and
`adb connect` is outbound, so it works from behind NAT too.

Three things about adb drive the details:

- **The pairing port is not the connect port.** The phone shows one on the
  "Pair device with pairing code" screen and a different one on the Wireless
  debugging screen itself, and people reliably try the first.
- **The connect port moves.** Android picks a new one every time debugging is
  toggled, so a remembered port goes stale. The node scans for it rather than
  asking the operator to go and read a number again.
- **adb calls a TCP phone an emulator.** `adb -e` selects it and `adb -d` does
  not, so nothing here may use those flags to tell the two apart — the serial
  is the only honest test, and an emulator's is emulator-NNNN.

The phone is kept on an adb server of its own on the node (ANDROID_ADB_SERVER_PORT),
so a session's plain `adb devices` there shows the emulator and nothing else.

**A connection has one owner.** The account that connects a phone is the only
one that can disconnect it, and the only one asked when a session wants to
touch it: a request from a session goes to the owner's bell and Phone tab and
nobody else's. Everybody else sees the connection and cannot drive it.
"""
import re
import threading
import time
from pathlib import Path

write_json = None
STATE = None
FILE = None
WORKSPACE = None
nodes = None          # the node module, set by server.py once it is up: run_wait, phone_nodes, node

# The phone's own adb server on the node, apart from the default one the
# emulator and a session's plain adb use.
ADB_PORT = "5038"

# An IPv4 address and nothing else. This becomes an argument to adb, so it is
# validated here rather than trusted: the tab is a table of actions, not a
# command line.
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# The window Android picks a wireless-debugging port from. Wider than it needs
# to be on any phone seen so far; a scan takes about a minute on the node and
# only happens when the operator asks to connect without a port.
PORT_LO, PORT_HI = 30000, 45000


def configure(*, write_json, state, workspace):
    globals().update(write_json=write_json, STATE=Path(state),
                     WORKSPACE=Path(workspace))
    globals()["FILE"] = Path(state) / "phone.json"


_lock = threading.Lock()


def load():
    """{"nodes": {node id: {owner, owner_name, ip, serial, model, at}}}."""
    try:
        d = __import__("json").loads(FILE.read_text())
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict) or not isinstance(d.get("nodes"), dict):
        d = {"nodes": {}}
    return d


def save(d):
    write_json(FILE, d)


def _rec(nid):
    return load()["nodes"].get(nid)


def _put(nid, rec):
    d = load()
    if rec is None:
        d["nodes"].pop(nid, None)
    else:
        d["nodes"][nid] = rec
    save(d)


# ---- adb, on the node ------------------------------------------------------

def _adb(nid, *args, timeout=30, files=None, sizes=None, project="", by="phone"):
    """One adb command on the node's phone server. Never `-e` or `-d` — see
    the module docstring. {"code", "out"}; an unreachable node is a failure
    with the reason as its output."""
    if nodes is None:
        return {"code": 1, "out": "the node registry is not available on this controller"}
    r = nodes.run_wait(by, nid, ["adb", *args],
                       env={"ANDROID_ADB_SERVER_PORT": ADB_PORT},
                       timeout=timeout, files=files, sizes=sizes, project=project)
    if r.get("error"):
        return {"code": 1, "out": r["error"]}
    return {"code": r.get("code") or 0, "out": r.get("out") or ""}


# What each node's adb last reported, kept a while: every probe is a job on
# the node, so the tab does not ask on every poll — it asks when opened,
# when something is pressed, and when a request is about to run.
_dev_cache = {}
_dev_fail = {}           # nodes whose last probe did not run, by id
DEV_TTL = 60.0


def devices(nid, force=False):
    """Everything attached to the node's phone server, split by what it is.
    An emulator is emulator-NNNN; anything else reached it over TCP and is a
    real device, whatever adb's own -e/-d flags may think."""
    c = _dev_cache.get(nid)
    if c and not force and time.monotonic() - c["at"] < DEV_TTL:
        return list(c["devs"])
    r = _adb(nid, "devices", "-l", timeout=20)
    if r["code"] != 0:
        # A probe that did not run — the node's one slot taken by a push, an
        # agent behind, a node away — is not a node with no phone. The last
        # answer stands, and phone_on() is told not to draw a conclusion.
        _dev_fail[nid] = True
        return list(c["devs"]) if c else []
    _dev_fail.pop(nid, None)
    out = []
    for line in r["out"].splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line and " " not in line:
            continue
        if line.startswith("[builderbot]") or line.startswith("*"):
            continue
        serial = line.split()[0]
        state = line.split()[1] if len(line.split()) > 1 else "?"
        model = ""
        m = re.search(r"model:(\S+)", line)
        if m:
            model = m.group(1).replace("_", " ")
        out.append({"serial": serial, "state": state, "model": model,
                    "kind": "emulator" if serial.startswith("emulator-") else "phone"})
    _dev_cache[nid] = {"at": time.monotonic(), "devs": list(out)}
    return out


def phone_on(nid, force=False):
    """The phone connected on this node, or None. The first that is not an
    emulator. A record with no phone behind it any more is dropped here, so
    an owner whose handset went away is not an owner of nothing."""
    if not nid:
        return None
    for d in devices(nid, force):
        if d["kind"] == "phone" and d["state"] == "device":
            return d
    # Only on a probe that RAN and found nothing: a failed one says nothing
    # about the handset, and an owner evicted on it would come back to a
    # phone anybody could claim.
    rec = _rec(nid)
    if rec and force and not _dev_fail.get(nid):
        _put(nid, None)
    return None


def device_rev():
    """A token for "what is attached changed", for the revisions poll. From
    the cache only — this is read every second and a job per read would be
    a queue of nothing."""
    return ",".join(sorted(f"{nid}:{d['serial']}:{d['state']}"
                           for nid, c in _dev_cache.items() for d in c["devs"]))


def _valid_ip(ip):
    return bool(IP_RE.match(str(ip or ""))) and all(
        0 <= int(p) <= 255 for p in str(ip).split("."))


def _valid_port(p):
    try:
        n = int(p)
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= 65535 else 0


# ---- who may drive a node's phone ------------------------------------------

def owner_of(nid):
    rec = _rec(nid)
    return {"uid": rec["owner"], "name": rec.get("owner_name") or "somebody"} if rec else None


def may_drive(nid, uid):
    """Whether this account may connect, disconnect and answer for the phone
    on this node: nobody holds it, or this account does."""
    rec = _rec(nid)
    return not rec or rec.get("owner") == uid


def _held_by_other(nid, uid):
    rec = _rec(nid)
    if rec and rec.get("owner") != uid:
        return {"error": f"the phone on this node was connected by "
                         f"{rec.get('owner_name') or 'somebody else'}, and only they "
                         "can disconnect it or answer for it"}
    return None


def pair(nid, ip, port, code, uid, name):
    """`adb pair` on the node, with everything checked before it becomes an
    argument. Pairing does not connect, so it takes no owner."""
    held = _held_by_other(nid, uid)
    if held:
        return held
    if not _valid_ip(ip):
        return {"error": f"not an IPv4 address: {ip}"}
    n = _valid_port(port)
    if not n:
        return {"error": f"not a port: {port}"}
    code = re.sub(r"\D", "", str(code or ""))
    if len(code) != 6:
        return {"error": "the pairing code is the six digits on the phone"}
    r = _adb(nid, "pair", f"{ip}:{n}", code, timeout=45, by=f"user:{name}")
    if "Successfully paired" not in r["out"]:
        return {"error": (r["out"].strip().splitlines() or ["pairing failed"])[-1]}
    d = load()
    d.setdefault("ips", {})[nid] = ip
    save(d)
    return {"ok": True, "message": r["out"].strip().splitlines()[-1]}


# The scan, run ON THE NODE: the phone is on the node's network, not the
# controller's. Python because every node has it (the agent needs it) and
# the fixture node has no bb to run.
SCAN = r"""
import socket, sys
from concurrent.futures import ThreadPoolExecutor
ip, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
found = []
def probe(p):
    if found: return
    s = socket.socket(); s.settimeout(0.35)
    try:
        if s.connect_ex((ip, p)) == 0: found.append(p)
    except OSError: pass
    finally: s.close()
with ThreadPoolExecutor(max_workers=400) as pool: pool.map(probe, range(lo, hi + 1))
print(found[0] if found else 0)
"""


def find_port(nid, ip, by="phone"):
    """Which port the phone is listening on for `adb connect`, scanned from
    the node. Android picks a new one every time wireless debugging is
    toggled, so the number on the phone's screen is only true until it is
    not, and sending the operator back to read it each time is the kind of
    small friction that stops a thing being used."""
    if not _valid_ip(ip) or nodes is None:
        return None
    r = nodes.run_wait(by, nid, ["python3", "-c", SCAN, ip, str(PORT_LO), str(PORT_HI)],
                       timeout=120)
    try:
        n = int((r.get("out") or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        n = 0
    return n or None


def connect(nid, ip, port, uid, name):
    """Connect on the node, finding the port when one is not given, and take
    the connection: whoever connects is who answers for it."""
    held = _held_by_other(nid, uid)
    if held:
        return held
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
        n = find_port(nid, ip, by=f"user:{name}")
        if not n:
            return {"error": f"nothing on {ip} is listening for adb from the node — "
                             "is wireless debugging still on? It hands out a new "
                             "port every time it is toggled."}
    r = _adb(nid, "connect", f"{ip}:{n}", timeout=30, by=f"user:{name}")
    if "connected to" not in r["out"]:
        return {"error": (r["out"].strip().splitlines() or ["connect failed"])[-1]}
    dev = phone_on(nid, force=True) or {}
    _put(nid, {"owner": uid, "owner_name": name, "ip": ip,
               "serial": dev.get("serial") or f"{ip}:{n}",
               "model": dev.get("model") or "", "at": int(time.time())})
    d = load()
    d.setdefault("ips", {})[nid] = ip
    save(d)
    return {"ok": True, "serial": f"{ip}:{n}"}


def disconnect(nid, uid, name):
    """The owner ends it. Nobody else: a connection somebody else made is
    theirs to drop, and the refusal names them."""
    held = _held_by_other(nid, uid)
    if held:
        return held
    p = phone_on(nid)
    target = (p or {}).get("serial") or (_rec(nid) or {}).get("serial") or ""
    if not target and not _rec(nid):
        return {"error": "no phone is connected on this node"}
    if target:
        _adb(nid, "disconnect", target, timeout=15, by=f"user:{name}")
    _put(nid, None)
    phone_on(nid, force=True)
    return {"ok": True}


# ---- what the tab and the Artifacts view read ------------------------------

def _node_row(n, uid, probe):
    rec = _rec(n["id"])
    dev = phone_on(n["id"], force=probe) if n["live"] else None
    return {"id": n["id"], "name": n["name"], "live": n["live"],
            "phone": dev, "ip": load().get("ips", {}).get(n["id"], ""),
            "owner": owner_of(n["id"]) if rec else None,
            "mine": bool(rec and rec.get("owner") == uid),
            "may_drive": may_drive(n["id"], uid)}


def payload(uid, node="", probe=False, admin=False):
    """The tab's data for one account: every node a phone can be driven
    from, which of them holds one and whose it is, and the requests waiting
    on THIS account — phone requests on the phone's owner, root requests on
    an administrator. `probe` asks the picked node's adb again now."""
    rows = []
    for n in (nodes.phone_nodes() if nodes is not None else []):
        rows.append(_node_row(n, uid, probe and n["id"] == node))
    return {"nodes": rows, "asks": requests_open(uid, admin)}


def summary(nid, uid, node=None):
    """What the Artifacts view needs to offer Install and Push for the
    account reading it: is a phone on this project's node, is it THIS
    account's connection (only the owner drives it), does the node carry
    web-ext (a push is web-ext beside that adb), which Firefoxes the phone
    has, and how an install or a push is going."""
    p = phone_on(nid) if nid else None
    rec = _rec(nid) if nid else None
    tc = ((node or {}).get("reported") or {}).get("toolchains") or {}
    return {"phone": p, "node": nid, "node_name": (node or {}).get("name", ""),
            "owner": owner_of(nid) if rec else None,
            "mine": bool(rec and rec.get("owner") == uid),
            "webext": bool(isinstance(tc, dict) and tc.get("web-ext")),
            "apks": firefox_apks(nid, (p or {}).get("serial", "")) if p else [],
            "push": push_state(), "install": install_state()}


# ---- pushing an extension, on the node -------------------------------------
# `web-ext run` is Mozilla's own tool and the only supported way in: an XPI is
# not an APK, so `adb install` is not it, and Firefox for Android will not
# take an extension off the filesystem. web-ext drives adb plus Firefox's
# remote debugging socket to install the add-on TEMPORARILY — it is gone when
# Firefox restarts, which is the development loop rather than an install.
#
# It runs as a job on the node that holds the phone, and stays running on
# purpose: stopping the job is how you end the session. The .xpi is fetched
# onto the node by the agent (a file from the project's dist/), unpacked
# there, and handed to web-ext as a source directory.
FIREFOX_APKS = ("org.mozilla.firefox_beta", "org.mozilla.fenix",
                "org.mozilla.firefox", "org.mozilla.firefox_nightly")
INSTALLED = "as a temporary add-on"
_apk_cache = {}


def firefox_apks(nid, serial):
    """Which of the Firefoxes we know about are on the phone. Kept a minute,
    like the device list: a package listing is a job on the node."""
    if not serial:
        return []
    c = _apk_cache.get(nid)
    if c and time.monotonic() - c["at"] < DEV_TTL:
        return list(c["apks"])
    out = _adb(nid, "-s", serial, "shell", "pm", "list", "packages", timeout=20)["out"]
    have = {ln.strip().replace("package:", "") for ln in out.splitlines()}
    apks = [a for a in FIREFOX_APKS if a in have]
    _apk_cache[nid] = {"at": time.monotonic(), "apks": apks}
    return apks


# Unpack beside the fetched file, then hand web-ext the directory. Python's
# zipfile because every node has python3 and not every node has unzip; the
# extraction refuses an entry that would land outside the directory.
PUSH_SH = r"""
set -e
f="$1"; apk="$2"; serial="$3"; port="$4"
d="${f%.xpi}.unpacked"
rm -rf "$d"; mkdir -p "$d"
python3 - "$f" "$d" <<'PY'
import os, sys, zipfile
f, d = sys.argv[1], os.path.realpath(sys.argv[2])
with zipfile.ZipFile(f) as z:
    for m in z.namelist():
        if not os.path.realpath(os.path.join(d, m)).startswith(d + os.sep):
            sys.exit("that archive tries to write outside itself")
    z.extractall(d)
PY
test -f "$d/manifest.json" || { echo "no manifest.json inside — not a WebExtension package"; exit 1; }
cd "$d"
exec web-ext run --target=firefox-android --no-reload --adb-port="$port"   --adb-device="$serial" --firefox-apk="$apk" --source-dir=. --no-input   --adb-remove-old-artifacts
"""

_push = {"job": "", "node": "", "what": "", "at": 0, "owner": ""}


def push_state():
    """The push as the tab shows it, read from the job it is: running while
    the job is, `running` once web-ext says the add-on is on the phone,
    `error` when the job ended before it did."""
    with _lock:
        cur = dict(_push)
    if not cur["job"] or nodes is None:
        return {"running": False, "what": "", "state": "", "error": "", "lines": [], "started": 0}
    j = nodes.job(cur["job"]) or {}
    log = j.get("log") or ""
    live = j.get("state") in ("queued", "assigned", "running")
    lines = [ln for ln in log.splitlines() if ln.strip()][-12:]
    state = "running" if INSTALLED in log else ("starting" if live else "stopped")
    err = ""
    if not live and INSTALLED not in log:
        err = (lines or ["web-ext stopped before the add-on was installed"])[-1]
    return {"running": live, "what": cur["what"], "state": state, "error": err,
            "lines": lines, "started": cur["at"], "job": cur["job"]}


def push(nid, node, rel, size, project, apk, uid, name, by="phone"):
    """Start web-ext on the node against an .xpi from the project's dist/.
    The owner's to do: a push touches the phone somebody else connected."""
    held = _held_by_other(nid, uid)
    if held:
        return held
    if push_state()["running"]:
        return {"error": f"already pushing {_push['what']} — stop it first"}
    dev = phone_on(nid)
    if not dev:
        return {"error": "no phone is connected on this project's node"}
    tc = ((node or {}).get("reported") or {}).get("toolchains") or {}
    if not (isinstance(tc, dict) and tc.get("web-ext")):
        return {"error": f"web-ext is not on {(node or {}).get('name') or 'that node'} — "
                         "a push is web-ext beside the phone's adb, so install it there"}
    if apk not in FIREFOX_APKS:
        return {"error": f"not a Firefox this knows: {apk}"}
    stores = (node or {}).get("reported", {}).get("stores") or {}
    root = (stores.get("artifacts") or {}).get("path") or (stores.get("data") or {}).get("path") or "/tmp"
    if (stores.get("artifacts") or {}).get("path"):
        root = f"{root}/{re.sub(r'[^A-Za-z0-9._-]', '_', str(project or '')) or '_'}"
    dest = f"{root}/{Path(rel).name}"
    r = nodes.job_add(by, {"node": nid}, "exec",
                      {"argv": ["sh", "-c", PUSH_SH, "push", dest, apk, dev["serial"], ADB_PORT],
                       "env": {"ANDROID_ADB_SERVER_PORT": ADB_PORT},
                       "timeout": 12 * 3600, "files": [rel], "sizes": {rel: size},
                       "project": project}, project)
    if r.get("error"):
        return r
    with _lock:
        _push.update(job=r["job"], node=nid, what=rel, at=int(time.time()), owner=uid)
    return {"ok": True, "job": r["job"]}


def stop_push(uid, by="phone"):
    """End the session. The add-on goes with it on the next Firefox restart —
    it was never installed in the lasting sense. The owner's, like the push."""
    with _lock:
        cur = dict(_push)
    if not cur["job"]:
        return {"ok": True}
    if cur["owner"] != uid:
        return {"error": "that push is the connection owner's to stop"}
    if nodes is not None and push_state()["running"]:
        nodes.job_cancel(by, cur["job"])
    with _lock:
        _push.update(job="", node="", what="", at=0, owner="")
    return {"ok": True}


# ---- asking first ----------------------------------------------------------
# Anything a session wants to do to the phone is submitted here and waits for
# the connection's OWNER to allow it. The session never runs the command
# itself — it describes what it wants, and on approval the node runs it and
# the output comes back. So "did Claude touch my phone" has one answer and it
# is on the tab of the person who connected it.
#
# A reason is required rather than optional. "adb shell pm uninstall x" with no
# explanation is a decision the owner has to reverse-engineer under time
# pressure, which is how people click Allow on things they should not.
#
# In memory and not on disk, deliberately: a request that outlived a restart
# would be a question about a moment that has passed, answered blind.
_reqs = []
_req_seq = 0
MAX_REQS = 20

# How long a session will wait before giving up. Fifteen minutes: the
# ordinary case is that the tab is behind three others and the request is
# noticed on the next glance, and a request that expires before it is seen
# is worse than one that waits.
WAIT_SECONDS = 900


def _req_public(r):
    # `left` so the tab can count down: an approval that quietly stops being
    # possible, with the button still sitting there, is a worse failure than
    # being told it has gone.
    return {"id": r["id"], "at": r["at"], "why": r["why"], "cmd": r["cmd"],
            "state": r["state"], "by": r["by"], "node": r["node"],
            "node_name": r["node_name"], "project": r["project"],
            "kind": r.get("kind") or "phone",
            "left": max(0, WAIT_SECONDS - (int(time.time()) - r["at"]))}


def _for(r, uid, admin):
    """Whether a request waits on this account: a phone request on the
    account that connected the phone, a root request on any administrator."""
    if r["to"] == "admins":
        return bool(admin)
    return r["to"] == uid


def requests_open(uid=None, admin=False):
    """What is waiting: everything, or only what waits on this account —
    `admin` says whether it is one, which is who a root request waits on."""
    with _lock:
        for r in _reqs:
            if r["state"] == "pending" and time.time() - r["at"] > WAIT_SECONDS:
                r["state"] = "expired"
        return [_req_public(r) for r in _reqs
                if r["state"] == "pending" and (uid is None or _for(r, uid, admin))]


def ask(why, argv, nid, node_name, project, by="claude"):
    """A session asking to reach the phone on its project's node. The
    request goes to whoever connected that phone. Returns the request's id."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for — the operator is answering a "
                         "question about a command they did not write"}
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) for a in argv):
        return {"error": "nothing to run"}
    if len(argv) > 40 or any(len(a) > 500 for a in argv):
        return {"error": "that command is too long to put in front of somebody"}
    if not nid:
        return {"error": f"{project or 'this project'} has no node, so there is no phone "
                         "to reach — a phone is driven from the project's node"}
    rec = _rec(nid)
    if not rec or not phone_on(nid):
        return {"error": f"no phone is connected on {node_name or nid} — somebody "
                         "connects one on the Phone tab with that node picked"}
    return _queue("phone", why, argv, nid, node_name, project, by, rec["owner"],
                  rec.get("owner_name") or "the owner")


def _queue(kind, why, argv, nid, node_name, project, by, to, to_name):
    global _req_seq
    with _lock:
        _req_seq += 1
        r = {"id": _req_seq, "at": int(time.time()), "why": why, "kind": kind,
             "cmd": list(argv), "state": "pending", "by": by,
             "node": nid, "node_name": node_name or nid, "project": project,
             "to": to, "out": "", "code": None}
        _reqs.append(r)
        del _reqs[:-MAX_REQS]
    return {"ok": True, "id": r["id"], "to": to_name}


def ask_root(why, argv, nid, node_name, project, sandbox, by="claude"):
    """A session asking for ONE command as root on its project's node
    (roadmap R38). Not sudo, which would be every command from then on
    with nobody reading them, and not a sudo that pretends — this is the
    phone's shape applied to root: the reason and the exact command go to
    the administrators, one of them allows or denies, and the node runs
    that command and nothing else. Only a node provisioned as a sandbox
    (a MANAGED node) takes it: somebody's own machine is not the
    controller's to run root on, whoever asks."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for — the operator is answering a "
                         "question about a root command they did not write"}
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) for a in argv):
        return {"error": "nothing to run"}
    if len(argv) > 40 or any(len(a) > 500 for a in argv):
        return {"error": "that command is too long to put in front of somebody"}
    if not nid:
        return {"error": f"{project or 'this project'} has no node, so there is no machine "
                         "to run anything on as root — root is asked for on the project's node"}
    if not sandbox:
        return {"error": f"{node_name or nid} was not provisioned as a BuilderBot sandbox, so "
                         "root there is its owner's and not something this can ask for"}
    return _queue("root", why, argv, nid, node_name, project, by, "admins", "the administrators")


def _find(rid):
    for r in _reqs:
        if r["id"] == rid:
            return r
    return None


def decide(rid, allow, uid, name="", admin=False):
    """The answer. Allowing runs it on the node, so the session never
    reaches the phone — or root — itself. Anybody else is refused: a phone
    question was put to the person who connected the phone, a root one to
    the administrators."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return {"error": "not a request"}
    with _lock:
        r = _find(rid)
        if r is None:
            return {"error": "no such request"}
        if not _for(r, uid, admin):
            return {"error": "that request is for the administrators"
                    if r["to"] == "admins" else
                    "that request is for the account that connected the phone"}
        if r["state"] != "pending":
            return {"error": f"that one was already {r['state']}"}
        r["state"] = "running" if allow else "denied"
    if not allow:
        return {"ok": True}
    if r.get("kind") == "root":
        res = _root(r["node"], r["cmd"], r["why"], by=f"user:{name}")
    else:
        res = _adb(r["node"], "-s", (_rec(r["node"]) or {}).get("serial") or "", *r["cmd"],
                   timeout=120, by=f"user:{name}") if (_rec(r["node"]) or {}).get("serial") \
            else _adb(r["node"], *r["cmd"], timeout=120, by=f"user:{name}")
    with _lock:
        r.update(state="done", out=res["out"][-8000:], code=res["code"])
    return {"ok": True}


def _root(nid, argv, why, by):
    """The one approved command, as root on the node: a system job the
    agent runs only on a sandbox node, with the reason and who allowed it
    written into its log so the Jobs tab is the record."""
    if nodes is None:
        return {"code": 1, "out": "the node registry is not available on this controller"}
    r = nodes.root_wait(by, nid, argv, why=why, timeout=600)
    if r.get("error"):
        return {"code": 1, "out": r["error"]}
    return {"code": r.get("code") or 0, "out": r.get("out") or ""}


def outcome(rid, project=""):
    """What became of a request, for the session that is waiting on it.
    `project` is the asking session's, and a request is answered only to
    the project that made it: ids are a small counter, and the output can
    be a getprop, a logcat, a file — one project's phone, not another's."""
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return {"error": "not a request"}
    with _lock:
        r = _find(rid)
        if r is None:
            return {"error": "no such request"}
        if project and r.get("project") != project:
            return {"error": "no such request"}
        return {"ok": True, "state": r["state"], "out": r["out"],
                "code": r["code"], "why": r["why"]}


# ---- installing an APK -----------------------------------------------------
# `adb install -r` replaces an existing install in place, keeping its data —
# so this is both "install" and "update", and there is no separate verb worth
# offering. Two failures are common enough to name rather than dump raw:
#
# - The installed copy was signed with a different key (a release build, or
#   one from the Play Store, against a debug build from here). Android refuses
#   the update outright and the only way through is uninstalling first, which
#   takes the app's data with it — a decision for the operator, on the phone.
# - A lower version code than what is installed. `-d` allows it but only for
#   debuggable packages, and passing it always would quietly turn a mistaken
#   downgrade into a successful one.
#
# Neither -g nor -t is passed: granting every runtime permission, or allowing
# test-only packages, makes the install behave unlike the one a real user
# would get, which is the opposite of what testing on a real handset is for.
_install = {"running": False, "what": "", "state": "", "error": "", "at": 0}


def install_state():
    with _lock:
        return dict(_install)


FAILURES = (
    ("INSTALL_FAILED_UPDATE_INCOMPATIBLE",
     "the copy already on the phone was signed with a different key — "
     "uninstall it there first, which also removes its data"),
    ("INSTALL_FAILED_VERSION_DOWNGRADE",
     "that build's version code is lower than the one installed"),
    ("INSTALL_FAILED_INSUFFICIENT_STORAGE", "the phone is out of space"),
    ("INSTALL_FAILED_INVALID_APK", "the phone would not read that as an APK"),
    ("INSTALL_PARSE_FAILED_NO_CERTIFICATES", "that APK is not signed"),
)


def _install_worker(nid, serial, rel, size, project, dest, by):
    r = _adb(nid, "-s", serial, "install", "-r", dest, timeout=600,
             files=[rel], sizes={rel: size}, project=project, by=by)
    out = r["out"]
    ok = r["code"] == 0 and "Success" in out
    err = ""
    if not ok:
        for token, said in FAILURES:
            if token in out:
                err = said
                break
        else:
            err = " ".join(out.split())[-300:] or "the install failed"
    with _lock:
        _install.update(running=False, state="done" if ok else "failed", error=err)


def install_apk(nid, node, rel, size, project, label="", by="phone"):
    """Install (or update) one APK from the project's dist/ on the phone
    connected to its node. The agent fetches the file into the node's
    artifacts store for the project (or its data store, without one), which
    is where the command names it."""
    with _lock:
        if _install["running"]:
            return {"error": f"already installing {_install['what']}"}
    dev = phone_on(nid)
    if not dev:
        return {"error": "no phone is connected on this project's node"}
    stores = node.get("stores") or {}
    root = (stores.get("artifacts") or {}).get("path") or (stores.get("data") or {}).get("path") or "/tmp"
    if (stores.get("artifacts") or {}).get("path"):
        root = f"{root}/{re.sub(r'[^A-Za-z0-9._-]', '_', str(project or '')) or '_'}"
    dest = f"{root}/{Path(rel).name}"
    with _lock:
        _install.update(running=True, what=label or Path(rel).name,
                        state="installing", error="", at=int(time.time()))
    threading.Thread(target=_install_worker,
                     args=(nid, dev["serial"], rel, size, project, dest, by),
                     daemon=True).start()
    return {"ok": True}
