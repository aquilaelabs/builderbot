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
  not, so nothing here may use those flags to tell the two apart: the serial
  is the only honest test, and an emulator's is emulator-NNNN.

The phone is kept on an adb server of its own on the node (ANDROID_ADB_SERVER_PORT),
so a session's plain `adb devices` there shows the emulator and nothing else.

**A connection has one owner.** The account that connects a phone is the only
one that can disconnect it, and the only one asked when a session wants to
touch it: a request from a session goes to the owner's bell and Phone tab and
nobody else's. Everybody else sees the connection and cannot drive it.
"""
import hashlib
import json
import ipaddress
import re
import threading
import time
from pathlib import Path

from fields import field

write_json = None
STATE = None
FILE = None
WORKSPACE = None
nodes = None          # the node module, set by server.py once it is up: run_wait, phone_nodes, node
# What an allowed rebuild request actually calls, set by server.py: devactions'
# own rebuild(project, instance). Injected rather than imported so this module
# keeps having one dependency (the node registry), and so the request queue
# stays a queue rather than growing an opinion about compose.
rebuilder = None
# ...and what a rebuild request may do first (ask_rebuild): make a container
# of the project, pinned to a branch when it asked for one, and write its env.
# devactions.make_instance and devapp.write_env.
instance_maker = None
env_writer = None
ctl_runner = None
remover = None
# containers.create_container, injected the same way: what Allow on a container
# ask calls (R71). None where no docker path is wired up. container_free is
# its name check, asked before a request is queued (B309), and
# container_builds whether the file would build from an empty directory
# (B329), asked at the same moment.
container_maker = None
# signing.start(principal, project, file, route), set by the server: what
# Allow on a session's `bb sign` runs (R106), queued as the session asked.
signer = None
# What Allow on a session's key change runs (R106 step 6), set by the
# server: keymaker(action, project, args) -> (payload, status), where
# action is generate (args: key, route) or map (args: package, key).
keymaker = None
container_free = None
container_builds = None
# ...and what verb() needs to know about the one asking, set by server.py
# beside the rest: the account store, the projects an account sees, the
# node a project builds on and its Run its container dial, a container's
# node held to its project's (R79), the dial's refusal, and the sessions'
# networks told when a container is made (R79).
users = None
leasing = None        # phonelease, set by server.py: a phone lent to a project (R113)
project_names = None
project_node = None
dial = None
on_project_node = None
run_denied = ""
net_nudge = None
# ...and what artifact_verb() needs: a path in a project's dist/ resolved the
# safe way (artifacts.resolve), and the Artifacts tab's list to answer with.
resolve_artifact = None
artifact_list = None

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
    """{"nodes": {node id: {owner, owner_name, ip, serial, model, at}},
        "ips": {node id: the address last used there},
        "known": {node id: [{ip, model, serial, first, last, by}]}}

    `known` is the phones this node has paired or connected, newest first:
    the pairing key is in the node account's ~/.android, so a remembered
    phone needs Connect and nothing else, and the tab offers exactly that."""
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


def by_node(uid):
    """{node id: {owner, mine, lease}} for every node with a phone connected,
    from one read of the store and no adb: what a project row says about its
    node's phone (R120). `lease` is {project, by_name, left} or None."""
    out, now = {}, time.time()
    for nid, rec in (load().get("nodes") or {}).items():
        if not isinstance(rec, dict):
            continue
        got = rec.get("lease") if isinstance(rec.get("lease"), dict) else None
        if got and got.get("until") and now > got["until"]:
            got = None
        out[nid] = {"node": nid, "owner": rec.get("owner_name") or "somebody", "mine": rec.get("owner") == uid,
                    "model": rec.get("model") or "",
                    "lease": ({"project": got.get("project") or "", "by_name": got.get("by_name") or "",
                               "left": int(got["until"] - now) if got.get("until") else None} if got else None)}
    return out


def _put(nid, rec):
    d = load()
    if rec is None:
        d["nodes"].pop(nid, None)
    else:
        d["nodes"][nid] = rec
    save(d)


KNOWN_MAX = 8      # per node; a desk does not hold more phones than this


def _remember(d, nid, ip, model, serial, name):
    """Note a phone on this node's remembered list, in place if it is one
    already there. A phone is the same phone by model when the model is
    known and by address until it is: a pairing knows only the address,
    and the connect that follows fills the model in on the same row. The
    address is updated either way: DHCP moves it, the phone does not
    change."""
    rows = [r for r in (d.setdefault("known", {}).get(nid) or []) if isinstance(r, dict)]
    now = int(time.time())
    same = [r for r in rows if (model and r.get("model", "").lower() == model.lower())
            or (not model or not r.get("model")) and r.get("ip") == ip]
    if same:
        row = same[0]
        rows.remove(row)
        row.update(ip=ip, last=now, by=name or row.get("by", ""))
        if model:
            row["model"] = model
        if serial:
            row["serial"] = serial
    else:
        row = {"ip": ip, "model": model or "", "serial": serial or "",
               "first": now, "last": now, "by": name or ""}
    d["known"][nid] = ([row] + rows)[:KNOWN_MAX]


def known(nid):
    return [r for r in (load().get("known", {}).get(nid) or []) if isinstance(r, dict)]


def forget(nid, ip):
    """Drop one remembered phone by address. The pairing key on the node
    stays (this is the list's memory, not adb's), so the phone can be
    connected again by typing its address."""
    if not _valid_ip(ip):
        return {"error": f"not an IPv4 address: {ip}"}
    d = load()
    rows = [r for r in (d.get("known", {}).get(nid) or []) if isinstance(r, dict)]
    keep = [r for r in rows if r.get("ip") != ip]
    if len(keep) == len(rows):
        return {"error": f"nothing remembered at {ip} on this node"}
    d.setdefault("known", {})[nid] = keep
    save(d)
    return {"ok": True}


# ---- adb, on the node ------------------------------------------------------

def _adb(nid, *args, timeout=30, files=None, sizes=None, project="", by="phone", probe=False):
    """One adb command on the node's phone server. Never `-e` or `-d`; see
    the module docstring. {"code", "out"}; an unreachable node is a failure
    with the reason as its output.

    `probe` is for a READ nobody asked to see, the device listing: a probe
    job moves no revision and is dropped once its answer is read. Listed,
    it was a row on the Jobs tab per node per minute, all reading "exec adb
    devices -l", and each one moved the revision the Docker manager
    refetches its whole listing on. A push or an install is a record and
    stays one."""
    if nodes is None:
        return {"code": 1, "out": "the node registry is not available on this controller"}
    r = nodes.run_wait(by, nid, ["adb", *args],
                       env={"ANDROID_ADB_SERVER_PORT": ADB_PORT},
                       timeout=timeout, files=files, sizes=sizes, project=project,
                       forget=probe)
    if r.get("error"):
        return {"code": 1, "out": r["error"]}
    return {"code": r.get("code") or 0, "out": r.get("out") or ""}


# What each node's adb last reported, kept a while: every probe is a job on
# the node, so the tab does not ask on every poll. It asks when opened,
# when something is pressed, and when a request is about to run.
_dev_cache = {}
_dev_fail = {}           # nodes whose last probe did not run, by id
DEV_TTL = 60.0


def no_adb(nid):
    """True when the node's census says it carries no adb, so there is
    nothing to probe. An agent too old to report toolchains is asked, as
    it always was."""
    n = nodes.node(nid) if nodes is not None and nid else None
    tc = ((n or {}).get("reported") or {}).get("toolchains")
    if not isinstance(tc, dict):
        return False
    return not (tc.get("adb") or tc.get("android-sdk"))


def devices(nid, force=False):
    """Everything attached to the node's phone server, split by what it is.
    An emulator is emulator-NNNN; anything else reached it over TCP and is a
    real device, whatever adb's own -e/-d flags may think."""
    c = _dev_cache.get(nid)
    if c and not force and time.monotonic() - c["at"] < DEV_TTL:
        return list(c["devs"])
    # Not asked of a node that has no adb: the census says what the node
    # carries, and a probe there is a job that fails on every poll, which
    # filled a fresh node's Jobs tab with 'could not start adb' rows (B138).
    # The tab says what is missing instead (no_adb).
    if no_adb(nid):
        _dev_fail[nid] = True
        return list(c["devs"]) if c else []
    r = _adb(nid, "devices", "-l", timeout=20, probe=True)
    if r["code"] != 0:
        # A probe that did not run (the node's one slot taken by a push, an
        # agent behind, a node away) is not a node with no phone. The last
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
    the cache only: this is read every second and a job per read would be
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
    _remember(d, nid, ip, "", "", name)
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
            return {"error": f"nothing on {ip} is listening for adb from the node. "
                             "Is wireless debugging still on? It hands out a new "
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
    _remember(d, nid, ip, dev.get("model") or "", dev.get("serial") or f"{ip}:{n}", name)
    save(d)
    return {"ok": True, "serial": f"{ip}:{n}"}


def disconnect(nid, uid, name, admin=False):
    """The owner ends it, or an administrator (R120, the operator 4 Oct): a
    phone left connected and lent is a machine-wide fact somebody has to be
    able to end. Nobody else: a connection another person made is theirs to
    drop, and the refusal names them. Its lease goes with it."""
    held = None if admin else _held_by_other(nid, uid)
    if held:
        return {"error": held["error"].replace("only they can", "only they, or an administrator, can")}
    p = phone_on(nid)
    target = (p or {}).get("serial") or (_rec(nid) or {}).get("serial") or ""
    if not target and not _rec(nid):
        return {"error": "no phone is connected on this node"}
    if target:
        _adb(nid, "disconnect", target, timeout=15, by=f"user:{name}")
    _put(nid, None)
    _forget_trust(nid)              # a phone gone takes what it allowed with it
    phone_on(nid, force=True)
    return {"ok": True}


# ---- what the tab and the Artifacts view read ------------------------------

def _node_row(n, uid, probe, who=None):
    rec = _rec(n["id"])
    dev = phone_on(n["id"], force=probe) if n["live"] else None
    return {"id": n["id"], "name": n["name"], "live": n["live"],
            "phone": dev, "ip": load().get("ips", {}).get(n["id"], ""),
            "known": known(n["id"]),
            "owner": owner_of(n["id"]) if rec else None,
            "mine": bool(rec and rec.get("owner") == uid),
            "may_drive": may_drive(n["id"], uid),
            # R113: who the phone is lent to, and (for its owner) which
            # projects on this node it could be.
            "lease": leasing.view(n["id"]) if leasing is not None else None,
            # Allowed for a session (the owner's to see and take back).
            "trust": trusts(n["id"]) if rec and rec.get("owner") == uid else [],
            "lendable": (sorted(p for p in project_names(who) if project_node(p) == n["id"])
                         if rec and rec.get("owner") == uid and who is not None
                         and project_names and project_node else [])}


def payload(uid, node="", probe=False, admin=False, project="", who=None):
    """The tab's data for one account: every node a phone can be driven
    from, which of them holds one and whose it is, and the requests waiting
    on THIS account: phone requests on the phone's owner, root requests on
    an administrator. `probe` asks the picked node's adb again now."""
    rows = []
    for n in (nodes.phone_nodes() if nodes is not None else []):
        rows.append(_node_row(n, uid, probe and n["id"] == node, who))
    return {"nodes": rows, "asks": requests_open(uid, admin, project)}


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
# remote debugging socket to install the add-on TEMPORARILY: it is gone when
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
test -f "$d/manifest.json" || { echo "no manifest.json inside: not a WebExtension package"; exit 1; }
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
        return {"error": f"already pushing {_push['what']}; stop it first"}
    dev = phone_on(nid)
    if not dev:
        return {"error": "no phone is connected on this project's node"}
    tc = ((node or {}).get("reported") or {}).get("toolchains") or {}
    if not (isinstance(tc, dict) and tc.get("web-ext")):
        return {"error": f"web-ext is not on {(node or {}).get('name') or 'that node'}: "
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
    """End the session. The add-on goes with it on the next Firefox restart.
    It was never installed in the lasting sense. The owner's, like the push."""
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
# itself: it describes what it wants, and on approval the node runs it and
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
    out = {"id": r["id"], "at": r["at"], "why": r["why"], "cmd": r["cmd"],
           "state": r["state"], "by": r["by"], "node": r["node"],
           "node_name": r["node_name"], "project": r["project"],
           "kind": r.get("kind") or "phone", "asker": r.get("asker") or "",
           "left": max(0, WAIT_SECONDS - (int(time.time()) - r["at"]))}
    # A container ask is approved by READING it, the way a root ask is
    # approved by reading its argv: the compose file is the request. The env
    # file is not shown whole, since that is where a token would be; its
    # keys are, so the reader knows what it sets.
    # ...and a rebuild that creates the container or writes its env says so,
    # with the env's keys for the same reason.
    if r.get("kind") == "rebuild":
        out["create"] = bool(r.get("create"))
        out["ctl"] = r.get("ctl") or ""
        if r.get("env") is not None:
            out["env_keys"] = [ln.split("=", 1)[0].strip() for ln in (r.get("env") or "").splitlines()
                               if "=" in ln and not ln.lstrip().startswith("#")]
    if r.get("kind") == "container":
        out["detail"] = r.get("compose") or ""
        out["env_keys"] = [ln.split("=", 1)[0].strip() for ln in (r.get("env") or "").splitlines()
                           if "=" in ln and not ln.lstrip().startswith("#")]
        out["name"] = r.get("name") or ""
        out["for"] = r.get("for") or ""
    return out


def _for(r, uid, admin):
    """Whether a request waits on this account. Routed by the SESSION that
    asked: a phone request goes to the account that connected the phone,
    which is the asker themselves when it is their own phone on their own
    session; a root request goes to the asker when their account is an
    administrator, and to every administrator when it is not, because a
    sandbox is a shared machine and root on it is not a user's to allow,
    while their own phone is. (A per-user grant for root on a sandbox is a
    design of its own, not written yet.)"""
    # Root and a rebuild are both an administrator's to allow: root because a
    # sandbox is shared, a rebuild because starting and stopping containers is
    # docker-write, which a user does not have on a project they otherwise own.
    if r.get("kind") in ("root", "rebuild", "container") and not admin:
        return False
    # A signing, or a key change, waits on the project's owner, whatever
    # their role.
    if r.get("kind") in ("sign", "sign-key"):
        return r["to"] == uid
    if r["to"] == "admins":
        return bool(admin)
    return r["to"] == uid


def requests_open(uid=None, admin=False, project=""):
    """What is waiting: everything, or only what waits on this account.
    `admin` says whether it is one, which is who a root request waits on.
    With `project`, a SESSION's read-only view instead: its own project's
    pending requests, so `bb root` and `bb phone` in a session can say what
    is waiting on somebody, though the session can answer none of it."""
    with _lock:
        for r in _reqs:
            if r["state"] == "pending" and time.time() - r["at"] > WAIT_SECONDS:
                r["state"] = "expired"
        if project:
            return [_req_public(r) for r in _reqs
                    if r["state"] == "pending" and r.get("project") == project]
        return [_req_public(r) for r in _reqs
                if r["state"] == "pending" and (uid is None or _for(r, uid, admin))]


def ask(why, argv, nid, node_name, project, by="claude", asker="", asker_uid=""):
    """A session asking to reach the phone on its project's node. The
    request goes to whoever connected that phone, the asker when it is
    their own. `asker` names the account whose session asks, for the row.
    Returns the request's id."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for: the operator is answering a "
                         "question about a command they did not write"}
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) and a for a in argv):
        return {"error": "nothing to run" if not argv else "an empty argument: the command "
                         "shown must be the command run"}
    if len(argv) > 40 or any(len(a) > 500 for a in argv):
        return {"error": "that command is too long to put in front of somebody"}
    if not nid:
        return {"error": f"{project or 'this project'} has no node, so there is no phone "
                         "to reach: a phone is driven from the project's node"}
    rec = _rec(nid)
    if not rec or not phone_on(nid):
        return {"error": f"no phone is connected on {node_name or nid}: somebody "
                         "connects one in the Phone tab, on that node"}
    return _allow_if_trusted(_queue("phone", why, argv, nid, node_name, project, by, rec["owner"],
                                     rec.get("owner_name") or "the owner", asker,
                                     extra={"asker_uid": asker_uid}))


# ---- Allow for this session (the operator, 4 Oct) ----------------------------
# Answering every command a session sends to a phone was too much: the
# owner's second answer, "Allow for this session", lets the commands that
# account's sessions in that project send to that phone run without asking
# again, for as long as the phone is lent to the project (an hour where it
# is not lent), until the owner takes it back from the Phone tab, the lease
# ends or the phone is disconnected. Kept in memory with the asks, so a
# controller restart asks again. A command so allowed is still an ask on
# the record, answered at once in the owner's name, so the log and the
# session's own wait read the same as for a press.
TRUST_S = 3600
_trust = {}             # (node id, project, asker uid) -> unix time it ends


def _trust_end(nid, project):
    got = leasing.lease(nid) if leasing is not None else None
    if got and got.get("project") == project:
        return got.get("until") or 0          # 0: until taken back
    return int(time.time()) + TRUST_S


def trusted(nid, project, asker_uid):
    """True while the owner has allowed this account's sessions in this
    project to drive the phone on this node without asking."""
    key = (nid, project, asker_uid)
    with _lock:
        if key not in _trust:
            return False
        end = _trust[key]
    got = leasing.lease(nid) if leasing is not None else None
    lent_here = bool(got and got.get("project") == project)
    # A grant made under a lease lasts the lease, not past it.
    if (end == 0 and not lent_here) or (end and end < time.time()):
        with _lock:
            _trust.pop(key, None)
        return False
    return True


def trusts(nid):
    """What the owner has allowed for a session on this node, for the Phone
    tab: [{project, asker, until}]."""
    out = []
    with _lock:
        keys = [k for k in _trust if k[0] == nid]
    for k in keys:
        if trusted(*k):
            with _lock:
                end = _trust.get(k)
                who = _trust_names.get(k, "")
            out.append({"project": k[1], "asker_uid": k[2], "asker": who, "until": end})
    return out


_trust_names = {}


def untrust(nid, uid, project="", asker_uid="", all_=False):
    """The owner asking every time again: one grant, or every one on the node."""
    rec = _rec(nid) or {}
    if rec.get("owner") != uid:
        return {"error": "only the account that connected the phone changes what it allows"}
    with _lock:
        for k in [k for k in _trust if k[0] == nid and (all_ or (k[1] == project and k[2] == asker_uid))]:
            _trust.pop(k, None)
            _trust_names.pop(k, None)
    return {"ok": True}


def wait_token(uid, admin=False):
    """What the companion app's live connection waits on (R125): a short
    hash of the asks waiting on this account, the lease revision and the
    grants. It moves exactly when the app has something new to post or to
    take out of the shade."""
    ids = sorted(r["id"] for r in requests_open(uid, admin))
    with _lock:
        held = sorted([*k, v] for k, v in _trust.items())
    lease = leasing.rev() if leasing is not None else ""
    raw = json.dumps([ids, lease, held], default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _forget_trust(nid):
    with _lock:
        for k in [k for k in _trust if k[0] == nid]:
            _trust.pop(k, None)
            _trust_names.pop(k, None)


def _allow_if_trusted(q):
    """A request just queued, answered at once in the owner's name when they
    allowed its session already; the request as _queue returned it."""
    if not q.get("ok"):
        return q
    with _lock:
        r = _find(q["id"])
    if r and r.get("kind") in ("phone", "phone-use") and trusted(r["node"], r["project"], r.get("asker_uid") or ""):
        with _lock:
            r["auto"] = True
        decide(r["id"], True, r["to"], "")
        q = {**q, "allowed": True}
    return q


def _queue(kind, why, argv, nid, node_name, project, by, to, to_name, asker="",
           extra=None):
    global _req_seq
    with _lock:
        _req_seq += 1
        r = {"id": _req_seq, "at": int(time.time()), "why": why, "kind": kind,
             "cmd": list(argv), "state": "pending", "by": by, "asker": asker,
             "node": nid, "node_name": node_name or nid, "project": project,
             "to": to, "out": "", "code": None}
        # What a kind needs and the others do not: a rebuild's instance. Kept
        # off _req_public: it decides a compose project and a data directory,
        # and the row already names the container it would rebuild.
        r.update(extra or {})
        _reqs.append(r)
        del _reqs[:-MAX_REQS]
    return {"ok": True, "id": r["id"], "to": to_name}


def ask_root(why, argv, nid, node_name, project, sandbox, by="claude",
             asker_uid="", asker_name="", asker_admin=False, locked=""):
    """A session asking for ONE command as root on its project's node
    (roadmap R38). Not sudo, which would be every command from then on
    with nobody reading them, and not a sudo that pretends. This is the
    phone's shape applied to root: the reason and the exact command go to
    a person, they allow or deny, and the node runs that command and
    nothing else. Which person is the session's own account when it is an
    administrator's (their ask, on their Nodes tab and bell), and every
    administrator when a user's session asks, because a sandbox is shared
    and root on it is not a user's to allow. Only a node provisioned as a
    sandbox (a MANAGED node) takes it: somebody's own machine is not the
    controller's to run root on, whoever asks."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for: the operator is answering a "
                         "question about a root command they did not write"}
    if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) and a for a in argv):
        # An empty argument is refused rather than dropped: what the person
        # reads must be exactly what the node runs.
        return {"error": "nothing to run" if not argv else "an empty argument: the command "
                         "shown must be the command run"}
    if len(argv) > 40 or any(len(a) > 500 for a in argv):
        return {"error": "that command is too long to put in front of somebody"}
    if not nid:
        return {"error": f"{project or 'this project'} has no node, so there is no machine "
                         "to run anything on as root: root is asked for on the project's node"}
    if not sandbox:
        return {"error": f"{node_name or nid} was not provisioned as a BuilderBot sandbox, so "
                         "root there is its owner's and not something this can ask for"}
    if locked:
        # Said now rather than after somebody pressed Allow: the lock is the
        # operator's decision that this machine is managed at its console.
        return {"error": locked}
    if asker_admin and asker_uid:
        return _queue("root", why, argv, nid, node_name, project, by, asker_uid,
                      f"{asker_name or 'you'} (your own account: it is on your Nodes tab and bell)",
                      asker_name)
    return _queue("root", why, argv, nid, node_name, project, by, "admins",
                  "the administrators", asker_name)


def ask_sign(why, project, file, route, to_uid, to_name, asker_name="", principal="", key=""):
    """A session asking to sign a build with one of its project's keys, on a
    project whose dial is `ask` (Claude may: Sign a release, R106). It goes
    to the project's owner, who reads which build and which key; Allow
    queues the signing as the session's own."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for: --why \"...\" (a release for testers, the Play upload ...)"}
    if not to_uid:
        return {"error": f"{project} has no owner to ask"}
    cmd = ["sign", str(file), "--for", str(route)] + (["--key", str(key)] if key else [])
    return _queue("sign", why, cmd, "", "", project, "claude",
                  to_uid, to_name, asker_name,
                  extra={"file": str(file), "route": str(route), "principal": principal, "key": str(key or "")})


def ask_keys(why, project, action, args, to_uid, to_name, asker_name=""):
    """A session proposing a new key or a package's key, on a project whose
    Manage signing keys dial is `ask` (R106 step 6). It goes to the project's
    owner: a new sideload key is an app's identity for good, which is why a
    person says yes to it."""
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what it is for: --why \"...\""}
    if not to_uid:
        return {"error": f"{project} has no owner to ask"}
    if action == "generate":
        cmd = ["sign", "key", "new", str(args.get("key")), "--for", str(args.get("route"))]
    elif action == "map":
        cmd = ["sign", "map", str(args.get("package")), str(args.get("key") or "default")]
    elif action == "rotate":
        cmd = ["sign", "rotate", str(args.get("from")), str(args.get("to"))]
    else:
        return {"error": f"not a key change: {action}"}
    return _queue("sign-key", why, cmd, "", "", project, "claude", to_uid, to_name, asker_name,
                  extra={"action": action, "args": dict(args)})


def ask_rebuild(why, project, instance, name, asker_uid="", asker_name="",
                asker_admin=False, env=None, create=False, target="", ctl="",
                node="", remove=False, ref=""):
    """A session asking to rebuild its project's dev instance, for a project
    whose dial is on `ask` (Claude may: Run its container, in the project's
    settings).

    The phone's shape applied to a build: the reason and what it would do go
    to a person, they allow or deny, and allowing starts the build. The same
    request may also carry, in the order Allow runs them, creating a
    container of the project (`create`: its own, or another beside it) and
    the env to write first (`env`): the operator's widenings of the dial, 24
    and 26 Sep. A container it creates may be pinned to a branch (`ref`)
    before that build, as Send to Docker's Build from pins one. What a
    container IS stays out of the session's hands: it is the project's own
    compose file on the project's node, never one the session names.

    `project` is the asking session's, which is who the answer goes back to;
    `target` is the container's own key when it is not that project's
    instance (one written here that belongs to it). `ctl` asks instead to
    start, stop or restart the container called `name` on `node`, one that
    belongs to the project and that BuilderBot may not have started.
    """
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": f"say what the {ctl or 'rebuild'} is for: the operator is "
                         "answering a question about work they did not start"}
    if env is not None and len(str(env)) > 65536:
        return {"error": "that env file is over 64KB, and this holds settings, not data"}
    to, to_name = (("admins", "the administrators") if not (asker_admin and asker_uid)
                   else (asker_uid, f"{asker_name or 'you'} (your own account: it is "
                                    "on the Docker tab and your bell)"))
    ref = str(ref or "") if create else ""
    cmd = (["devapp", ctl, name] if ctl
           else ["devapp", "new", name] + (["--branch", ref] if ref else []) if create
           else ["devapp", "remove", name] if remove
           else ["devapp", "env", "set", name] if env is not None
           else ["devapp", "rebuild", name])
    return _queue("rebuild", why, cmd, node, "", project, "claude", to, to_name, asker_name,
                  extra={"instance": str(instance or ""), "create": bool(create), "remove": bool(remove),
                         "env": None if env is None else str(env),
                         "target": str(target or ""), "ctl": str(ctl or ""),
                         "name": str(name or ""), "ref": ref})


def ask_container(why, name, compose, env, nid, node_name, project, for_project="",
                  asker_name=""):
    """A session asking for a CONTAINER: a compose file it wrote, built and
    started on a node once an administrator approves (roadmap R71).

    The root shape applied to docker. The session names nothing docker runs:
    it hands over the file, and Allow gives that file to the same function
    the Docker tab's New container uses, which asks compose to parse it before
    anything is registered. To the administrators always, whoever asks: a
    container is root-shaped power on the node, and starting one is
    docker-write, which no user account holds.
    """
    why = " ".join(str(why or "").split())[:300]
    if not why:
        return {"error": "say what the container is for: the administrator is answering "
                         "a question about a file they did not write"}
    name = " ".join(str(name or "").split())
    if not name or len(name) > 60:
        return {"error": "a container needs a name, under sixty characters"}
    compose = str(compose or "")
    if not compose.strip():
        return {"error": "nothing to build: hand over the compose file"}
    if len(compose) > 64000 or len(str(env or "")) > 16000:
        return {"error": "that is too long to put in front of somebody: a compose file "
                         "under 64kB and an env file under 16kB"}
    where = node_name or nid or "the default node"
    return _queue("container", why, ["container", "create", name, "on", where],
                  nid, node_name, project, "claude", "admins", "the administrators",
                  asker_name,
                  extra={"name": name, "compose": compose, "env": str(env or ""),
                         "for": str(for_project or "")})


def _find(rid):
    for r in _reqs:
        if r["id"] == rid:
            return r
    return None


def decide(rid, allow, uid, name="", admin=False, session=False):
    """The answer. Allowing runs it on the node, so the session never
    reaches the phone (or root) itself. Anybody else is refused: a phone
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
            return {"error": "root on a sandbox is a shared machine's: an administrator "
                             "allows it, not a user; your own phone is yours to allow"
                    if r.get("kind") == "root" and not admin else
                    "that request is for the administrator whose session asked"
                    if r.get("kind") == "root" else
                    "that request is for the account that connected the phone"}
        if r["state"] != "pending":
            return {"error": f"that one was already {r['state']}"}
        r["state"] = "running" if allow else "denied"
    # Allow for this session: this one runs, and the next ones from the same
    # account's sessions in this project to this phone do not ask.
    if allow and session and r.get("kind") in ("phone", "phone-use"):
        key = (r["node"], r["project"], r.get("asker_uid") or "")
        end = _trust_end(r["node"], r["project"])
        with _lock:
            _trust[key] = end
            _trust_names[key] = r.get("asker") or ""
    if not allow:
        return {"ok": True}
    if r.get("kind") == "rebuild":
        # Answered at once and not on a thread: the rebuild is a JOB, so
        # starting it returns as soon as it is queued, and the session that
        # asked follows the job the same way it would have without the
        # question. The request's `out` is that job's id, which is all the
        # session needs to stop waiting on the answer and start waiting on
        # the build.
        if rebuilder is None:
            with _lock:
                r.update(state="done", out="no rebuild is wired up here", code=1)
            return {"ok": True}
        # What the request carried beyond the build, in the order it needs:
        # the container made, then its env, then the build that uses both.
        # Or a start, stop or restart of one container, and nothing else.
        res = {}
        key = r.get("target") or r["project"]
        if r.get("ctl"):
            res = (ctl_runner(r.get("node") or "", r.get("name") or "", r["ctl"])
                   if ctl_runner is not None else {"error": "nothing here starts a container"}) or {}
            with _lock:
                r.update(state="done", code=1 if res.get("error") else 0,
                         out=str(res.get("error") or res.get("out") or r["ctl"]))
            return {"error": res["error"]} if res.get("error") else {"ok": True}
        if r.get("remove"):
            # Taken out of the manager: its env and data stay for a remake.
            res = (remover(key, r.get("instance") or "") if remover is not None
                   else {"error": "nothing here removes a container"}) or {}
            with _lock:
                r.update(state="done", code=1 if res.get("error") else 0,
                         out=str(res.get("error") or res.get("job") or "removed"))
            return {"error": res["error"]} if res.get("error") else {"ok": True}
        if r.get("create") and instance_maker is not None:
            res = instance_maker(key, r.get("instance") or "", ref=r.get("ref") or "") or {}
        if not res.get("error") and r.get("env") is not None and env_writer is not None:
            res = env_writer(key, r["env"], r.get("instance") or "") or {}
        # Allow does what the card said: a fresh container is created,
        # written and built, one ask for the three; an env set on one that
        # exists is written and not built, the way the auto path leaves the
        # rebuild for the session to ask for next (the review of 24 Sep, when
        # Allow on "env set" bounced a running container nobody was told
        # would move).
        if not res.get("error") and (r.get("create") or r.get("env") is None):
            # Allow is the answer the project's `ask` puts a person in front
            # of, so the build does not stop again at the confirmation a
            # person's own Build on the row gives (the operator, 26 Sep).
            res = rebuilder(key, r.get("instance") or "", gate=False) or {}
        elif not res.get("error"):
            res = {"job": "env written"}
        with _lock:
            r.update(state="done", code=1 if res.get("error") else 0,
                     out=str(res.get("error") or res.get("job") or "started"))
        # A refusal comes back to whoever pressed Allow, not only to the
        # session: the risk gate is the one that fires here, and it is the
        # operator's own acknowledgement that is missing, which they can
        # only give by pressing Rebuild on the row, where the risks are
        # actually listed. Silently ending the request would leave them
        # believing they had started a build.
        if res.get("error"):
            return {"error": res["error"]}
        return {"ok": True}
    if r.get("kind") == "sign":
        # Queued as the session's own, the way the auto path does it; the
        # job's id is what the session follows next.
        res = (signer(r.get("principal") or "", r["project"], r.get("file") or "", r.get("route") or "",
                      r.get("key") or "")
               if signer is not None else ({"error": "nothing here signs"}, 400))
        got = res[0] if isinstance(res, tuple) else res
        with _lock:
            r.update(state="done", code=1 if got.get("error") else 0,
                     out=str(got.get("error") or got.get("job") or "started"))
        return {"error": got["error"]} if got.get("error") else {"ok": True}
    if r.get("kind") == "sign-key":
        res = (keymaker(r.get("action") or "", r["project"], r.get("args") or {})
               if keymaker is not None else ({"error": "nothing here makes keys"}, 400))
        got = res[0] if isinstance(res, tuple) else res
        with _lock:
            r.update(state="done", code=1 if got.get("error") else 0,
                     out=str(got.get("error") or "done"))
        return {"error": got["error"]} if got.get("error") else {"ok": True}
    if r.get("kind") == "container":
        # Two steps and both said: the container registered through the
        # Docker tab's own path, which refuses a file compose cannot read,
        # then its build started as a job, whose id is what the session
        # waits on next. A refusal at either step comes back to whoever
        # pressed Allow as well as to the session, for the same reason a
        # refused rebuild does: they believe they started something.
        if container_maker is None:
            with _lock:
                r.update(state="done", out="no container path is wired up here", code=1)
            return {"ok": True}
        res = container_maker(r.get("name") or "", r.get("compose") or "",
                              r.get("env") or "", r.get("node") or "", r.get("for") or "") or {}
        if not res.get("error") and rebuilder is not None:
            # The administrator read the compose file itself to allow this.
            built = rebuilder(res.get("project") or "", res.get("instance") or "", gate=False) or {}
            if built.get("error"):
                res = {"error": f"{res.get('name') or r.get('name')} is registered on the "
                                f"Docker tab, and its build did not start: {built['error']}"}
            else:
                res = {"job": built.get("job"), "name": res.get("name")}
        with _lock:
            r.update(state="done", code=1 if res.get("error") else 0,
                     out=str(res.get("error") or res.get("job") or res.get("name") or "created"))
        if res.get("error"):
            return {"error": res["error"]}
        return {"ok": True}
    if r.get("kind") == "phone-use":
        # A lent phone's command, allowed by its owner (R120): run as the
        # lease would have run it, on a thread (a recording takes its
        # seconds), its answer kept as JSON for the session's verb to read.
        def finish_use():
            try:
                res, st = leasing.use(r["project"], r.get("op") or "", r.get("args") or {})
            except Exception as e:                                     # noqa: BLE001 (said, not raised)
                res, st = {"error": str(e)}, 500
            with _lock:
                r.update(state="done", out=json.dumps(res)[-8000:], code=0 if st == 200 else 1)
        threading.Thread(target=finish_use, daemon=True, name=f"phone-use-{rid}").start()
        return {"ok": True, "state": "running"}
    if r.get("kind") == "root":
        # Answered at once, run on a thread: a root command may take ten
        # minutes, and the browser's Allow, behind whatever proxy, must
        # not hang for it. The request is `running` meanwhile, the session
        # polls its outcome, and the record is what the thread updates.
        def finish():
            res = _root(r["node"], r["cmd"], r["why"], by=f"user:{name}")
            with _lock:
                r.update(state="done", out=res["out"][-8000:], code=res["code"])
        threading.Thread(target=finish, daemon=True, name=f"root-{rid}").start()
        return {"ok": True, "state": "running"}
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
    be a getprop, a logcat, a file. One project's phone, not another's."""
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
# `adb install -r` replaces an existing install in place, keeping its data,
# so this is both "install" and "update", and there is no separate verb worth
# offering. Two failures are common enough to name rather than dump raw:
#
# - The installed copy was signed with a different key (a release build, or
#   one from the Play Store, against a debug build from here). Android refuses
#   the update outright and the only way through is uninstalling first, which
#   takes the app's data with it, a decision for the operator, on the phone.
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
     "the copy already on the phone was signed with a different key; "
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


def install_dest(node, project, rel):
    """Where the agent fetches a dist/ file for an install on this node: its
    artifacts store for the project, or its data store without one. A node's
    record keeps its stores under `reported`; a caller may hand them at the
    top instead. Reading only the top sent a lease's install (which hands
    the record) to /tmp while the agent fetched into the store (report #52)."""
    stores = node.get("stores") or (node.get("reported") or {}).get("stores") or {}
    root = (stores.get("artifacts") or {}).get("path") or (stores.get("data") or {}).get("path") or "/tmp"
    if (stores.get("artifacts") or {}).get("path"):
        root = f"{root}/{re.sub(r'[^A-Za-z0-9._-]', '_', str(project or '')) or '_'}"
    return f"{root}/{Path(rel).name}"


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
    dest = install_dest(node, project, rel)
    with _lock:
        _install.update(running=True, what=label or Path(rel).name,
                        state="installing", error="", at=int(time.time()))
    threading.Thread(target=_install_worker,
                     args=(nid, dev["serial"], rel, size, project, dest, by),
                     daemon=True).start()
    return {"ok": True}


# ---------------------------------------------------------------------------
# the Phone tab's verbs and the asking, one call from the dashboard

def tab_view(uid, *, admin, project, node="", probe=False, scope=None, ua="", addr="", who=None):
    """The tab's data for this account, plus this browser's own address when
    it is a phone.

    The whole point of the IP field is a number the operator has to go and
    read off the device, and when the dashboard is being viewed ON that
    device, the server already has it: the client address of this very
    request. Docker's bridge does not masquerade it, so what arrives is the
    real LAN address rather than the gateway's.

    Only offered for an Android client. From a desktop the client address
    is the desktop's, which is emphatically not the phone, and filling the
    field with it would be a confident wrong answer, the worst kind.
    """
    out = payload(uid, node=node, probe=probe, admin=admin, project=project, who=who)
    # The rows are the nodes this account's projects build on, as every
    # node-shaped surface is (the server's _node_scope, handed in as scope):
    # the list carried every phone node's name, address and handset to a
    # session (the probe of 26 Sep).
    # The row's node is its `id`: filtering on a `node` key no row has
    # emptied the list for every scoped asker, so a session's bb phone status
    # said "no node carries adb" beside a phone connected on its node
    # (report #51, 4 Oct).
    if scope is not None and isinstance(out.get("nodes"), list):
        out["nodes"] = [r for r in out["nodes"] if r.get("id") in scope]
    if "Android" in ua:
        try:
            ip = ipaddress.ip_address(addr)
            if ip.is_private and not ip.is_loopback:
                out["you"] = str(ip)
        except ValueError:
            pass
    return out


def verb(action, req, who, fresh):
    """Pair, connect, disconnect or forget a phone, a session's ask (adb,
    root, a container) and a person's answer, once server.py has said which
    of these this caller may use at all. Every argument is checked against
    something already known rather than taken as given. (payload, status);
    a change that succeeds carries the tab's fresh data, fresh(), which the
    server reads with this request's own address."""
    act = action
    uid, me = users.uid_of(who), who.get("name") or "somebody"
    nid = field(req, "node")
    if act in ("pair", "connect", "disconnect", "forget"):
        if nodes is None or not nid or not nodes.node(nid):
            return {"error": "pick a node: a phone is driven from "
                             "a node that has adb"}, 400
        if act != "forget" and not nodes.node(nid).get("live"):
            return {"error": f"{nodes.node(nid)['name']} is not dialing "
                             "in; nothing reaches its adb right now"}, 400
    if act == "pair":
        r = pair(nid, field(req, "ip"), field(req, "port"), field(req, "code"), uid, me)
    elif act == "connect":
        r = connect(nid, field(req, "ip"), field(req, "port") or None, uid, me)
    elif act == "disconnect":
        r = disconnect(nid, uid, me, admin=users.is_admin(who))
    elif act == "forget":
        r = forget(nid, field(req, "ip"))
    elif act == "ask":
        # A session asking to reach the phone on its project's node,
        # or, with kind "root", for one command as root there (roadmap
        # R38). It runs nothing itself; the account that connected that
        # phone, or an administrator, is asked, and on Allow the node
        # runs it. The project is the session's own; a person asking
        # through the API names one they may see.
        proj = who.get("session") or field(req, "project")
        if proj and not who.get("session") and not users.may_see(who, proj):
            proj = ""
        pnid = project_node(proj) if proj else ""
        pn = nodes.node(pnid) if pnid and nodes is not None else None
        # Whose session asks: the account behind the token (a session on
        # a node is minted for one), or the person calling the API. The
        # answer is routed to them where it can be: their own phone,
        # or root when they are an administrator.
        acct = users.account_of(who) or {}
        asker_uid = str(acct.get("uid") or "")
        asker_name = str(acct.get("name") or "")
        if field(req, "kind") == "container":
            # A container asked for (roadmap R71): the compose file the
            # session wrote, on the node it names or the project's own.
            # Always the administrators', whoever asks. The node is
            # resolved here so the row can say where, and so a name that
            # is not a node is refused before anybody is asked.
            cnode = field(req, "node")
            target = None
            if cnode and nodes is not None:
                target = nodes.node(cnode) or next(
                    (n for n in nodes.node_list() if n.get("name") == cnode), None)
                if not target:
                    return {"error": f"no node called {cnode}"}, 400
            elif pn:
                target = pn
            # The same check the New container form gets: a project
            # that exists and this account may see. A session's ask
            # belongs to its own project unless it names another, so the
            # session that asked can see what it asked for.
            under = field(req, "for") or (who.get("session") or "")
            if under and under not in project_names(who):
                return {"error": f"not a project: {under}"}, 400
            # ...and it lands on that project's node: a node named that
            # is not the project's is refused now, since a container
            # anywhere else is out of reach of the project's sessions
            # (R79, the operator 25 Sep); a project with no node has to
            # be given one first.
            if under:
                why, un = on_project_node(under, target["id"] if target else "")
                if why:
                    return {"error": why}, 400
                target = nodes.node(un) if nodes is not None else None
            # A session's is under its project's dial, Claude may: Run
            # its container, like every other container verb (B250, the
            # operator, 24 Sep: at auto it was still asked). Refused at
            # deny; at auto, its own project's on its own node is made
            # now and built, the way Allow would; one for another project
            # or on a node it names is always a person's.
            sess = who.get("session") or ""
            if sess:
                mode = dial(sess)
                if mode == "deny":
                    return {"error": run_denied}, 403
                if mode == "auto" and under == sess and not cnode:
                    r = container_maker(field(req, "name"), req.get("compose"),
                                        req.get("env"), "", under)
                    if r.get("error"):
                        return r, 400
                    net_nudge()
                    # Built whatever the compose asks for: auto is the
                    # project's answer (the operator, 26 Sep).
                    built = rebuilder(r["project"], r["instance"], gate=False) or {}
                    if built.get("error"):
                        return r | {"error": f"{r['name']} is registered on the Docker "
                                             f"tab, and its build did not start: {built['error']}"}, 400
                    return r | {"job": built.get("job")}, 200
            # A name nothing could build under is refused here, before the
            # request is on anybody's bell (B309), with the words the
            # create would use.
            why = container_free(field(req, "name")) if container_free is not None else ""
            if not why and container_builds is not None:
                why = container_builds(field(req, "name"), str(req.get("compose") or ""),
                                       str(req.get("env") or ""))
            if why:
                return {"error": why}, 400
            r = ask_container(field(req, "why"), field(req, "name"),
                              req.get("compose"), req.get("env"),
                              target["id"] if target else "",
                              target["name"] if target else "", proj,
                              for_project=under, asker_name=asker_name)
        elif field(req, "kind") == "root":
            r = ask_root(field(req, "why"), req.get("cmd"), pnid if pn else "",
                         pn["name"] if pn else "", proj,
                         bool(((pn or {}).get("reported") or {}).get("sandbox")),
                         asker_uid=asker_uid, asker_name=asker_name,
                         asker_admin=users.is_admin(acct),
                         locked=(nodes.node_locked(pn) or nodes.root_refused(pn)) if pn else "")
        else:
            r = ask(field(req, "why"), req.get("cmd"), pnid if pn else "",
                    pn["name"] if pn else "", proj, asker=asker_name, asker_uid=str(asker_uid or ""))
    elif act == "lend":
        if not nid or not _rec(nid):
            return {"error": "no phone is connected on that node"}, 400
        r = leasing.lend(nid, who, field(req, "project"), req.get("hours"))
    elif act == "take-back":
        r = leasing.take_back(nid, who, admin=users.is_admin(who))
        if r.get("ok"):
            _forget_trust(nid)          # what was allowed for a session went with the lease
    elif act == "look":
        # The owner watching what a session does: a screenshot of the lent
        # phone now, into the project's dist/phone/ beside the session's.
        got = leasing.lease(nid) if nid else None
        if not got or (_rec(nid) or {}).get("owner") != uid:
            return {"error": "only the owner looks at a lent phone from here"}, 403
        r, st = leasing.use(got["project"], "shot", {})
        if st != 200:
            return r, st
    elif act == "use":
        # A session's verb on the phone lent to its project (R113): its own
        # project only, and phonelease says what a lease allows. Since R120
        # (the operator, 4 Oct) every one but reading the lease ASKS the
        # phone's owner, and runs on their Allow: whether a session drives a
        # phone is its owner's call each time, not a project's setting.
        proj = who.get("session") or field(req, "project")
        if not proj or (not who.get("session") and not users.may_see(who, proj)):
            return {"error": "which project's phone?"}, 400
        op = field(req, "op")
        if op == "status" or not who.get("session"):
            return leasing.use(proj, op, req.get("args"))
        lnid, got = leasing.leased_to(proj)
        # What would be refused anyway is refused now, not after its owner
        # was asked (report #52): no lease, a file outside dist/, an app
        # that is not the lease's.
        no = leasing.check(proj, op, req.get("args"))
        if no:
            return no
        rec = _rec(lnid) or {}
        args = req.get("args") if isinstance(req.get("args"), dict) else {}
        shown = ["bb", "phone", str(op)[:20]] + [f"{k}={str(v)[:120]}" for k, v in sorted(args.items())][:8]
        why = " ".join(str(req.get("why") or "").split())[:300] or f"{op} on the phone lent to {proj}"
        nname = (nodes.node(lnid) or {}).get("name") if nodes is not None else lnid
        acct = users.account_of(who) or {}
        r = _allow_if_trusted(_queue("phone-use", why, shown, lnid, nname, proj, f"session:{proj}",
                                     rec.get("owner") or "", rec.get("owner_name") or "its owner",
                                     asker=acct.get("name") or who.get("name") or "",
                                     extra={"op": str(op)[:20], "args": args,
                                            "asker_uid": str(who.get("uid") or "")}))
        return {"asked": r["id"], "to": r["to"], "allowed": bool(r.get("allowed"))}, 200
    elif act == "allow" or act == "deny":
        r = decide(req.get("id"), act == "allow", uid, me, admin=users.is_admin(who),
                   session=act == "allow" and bool(req.get("session")))
    elif act == "untrust":
        r = untrust(nid, uid, field(req, "project"), field(req, "asker_uid"), all_=bool(req.get("all")))
    elif act == "outcome":
        r = outcome(req.get("id"), project=who.get("session") or "")
        if not r.get("error"):
            return r, 200
    else:
        return {"error": f"unknown action: {act}"}, 400
    if r.get("error"):
        return r, 400
    return r | fresh(), 200


def artifact_verb(project, act, req, *, uid, me, by):
    """The Artifacts tab's phone buttons: push an .xpi from the project's
    dist/ to the phone on its node, install an .apk there, or stop a push,
    once server.py has let this person (never a session) work on the
    project. The path is resolved against dist/ and unpacked before
    anything runs; push_dir never sees a caller-supplied path. (payload,
    status)."""
    nid = project_node(project)
    node = nodes.node(nid) if nid and nodes is not None else None
    # Both verbs touch the phone, so both are the connection owner's:
    # the phone is on somebody's desk, and they are the one who said
    # yes to it. The tab ghosts the buttons for anybody else; this is
    # the line that holds.
    if act in ("push", "install"):
        if not node:
            return {"error": f"{project} has no node, and a phone is "
                             "driven from the project's node"}, 400
        if not phone_on(nid):
            return {"error": f"no phone is connected on {node['name']}: "
                             "connect one in the Phone tab, on that node"
                             ""}, 400
        held = owner_of(nid)
        if held and held["uid"] != uid:
            return {"error": f"the phone on {node['name']} was connected "
                             f"by {held['name']}; only they can push to "
                             "it or install on it"}, 400
        if not held:
            return {"error": f"the phone on {node['name']} has no owner: "
                             "connect it in the Phone tab, on its node first"}, 400
    if act == "push":
        # A temporary add-on, through web-ext on the phone's node. A push
        # is a decision, made each time; nothing auto-pushes on a change.
        rel = field(req, "path")
        f = resolve_artifact(project, rel)
        if f is None or f.suffix.lower() != ".xpi":
            return {"error": "not an .xpi in this project's dist/"}, 400
        r = push(nid, node, rel, f.stat().st_size, project, field(req, "apk"),
                 uid, me, by=by)
    elif act == "install":
        # An APK, installed for real and kept, unlike the extension push,
        # which is a temporary add-on. `adb install -r` replaces an
        # existing copy in place and keeps its data, so this is the update
        # path too and there is no second verb.
        rel = field(req, "path")
        f = resolve_artifact(project, rel)
        if f is None or f.suffix.lower() not in (".apk",):
            return {"error": "not an .apk in this project's "
                             "dist/"}, 400
        r = install_apk(nid, {"stores": (node.get("reported") or {}).get("stores") or {}},
                        rel, f.stat().st_size, project, label=rel, by=by)
    elif act == "stop":
        r = stop_push(uid, by=by)
    else:
        return {"error": f"unknown action: {act}"}, 400
    if r.get("error"):
        return r, 400
    return r | {"artifacts": artifact_list(project)} | summary(nid, uid, node), 200
