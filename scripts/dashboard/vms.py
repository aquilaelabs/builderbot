"""The VM manager (R91): a project's VMs on the nodes whose VM host feature is
installed, made, started, stopped, snapshotted and removed as `vm` jobs the
agent runs from its own fixed table (scripts/agent/builderbot_agent/vms.py).

A VM's record lives here, in /config/vms.json, keyed by "PROJECT/NAME": which
node, which OS, its size, who made it and what its last job did. What it is
doing now (running, its address, its snapshots) is the node's census, laid
over the record when the page or a session reads it, so nothing here polls.

The OS is picked from config/vm-images.json by a name a person or a session
says ("debian", "ubuntu 24.04", "rocky-10"); one with a license to accept is
a person's to make, never a session's. Each project has a network of its own
on each node, a /24 out of VM_NET, given once and kept.
"""
import difflib
import ipaddress
import json
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG_FILE = HERE.parent.parent / "config" / "vm-images.json"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
SNAP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
KEY_RE = re.compile(r"(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]{20,800}( [^\n]{0,100})?")
# The project networks, a /24 each out of this range: clear of the sessions'
# 10.231.0.0/16 (SESSNET_CIDR), Docker's 172.16/12 and libvirt's own
# 192.168.122.0/24.
VM_NET = ipaddress.ip_network("10.232.0.0/16")
DEFAULTS = {"vcpus": 2, "mem_mb": 2048, "disk_gb": 20}
ACTIONS = ("start", "stop", "restart", "remove", "snapshot", "revert", "snapshot-rm")
# Room a node keeps for itself: memory beyond what its VMs are given, and
# disk in the VM pool beyond theirs.
NODE_KEEP_MB = 2048
POOL_KEEP_GB = 10

STATE = None
write_json = None
node = None
node_list = None
job_add = None
audit = None
prefs_get = None
nodes_rev = None
enroll_script = None       # nodes.enroll_script, for a VM made a node (step 14)
node_retire = None         # (principal, node id): its node retired with it
node_mark = None           # (node id, host node id): the row says it is a VM there
_lock = threading.Lock()
_rev = [0]
_seen = {"nodes": None, "sig": 0}


def configure(*, state, write_json, node, node_list, job_add, audit, prefs_get, nodes_rev=lambda: 0,
              enroll_script=None, node_retire=None, node_mark=None, node_discard=None):
    globals().update(STATE=Path(state), write_json=write_json, node=node, node_list=node_list,
                     job_add=job_add, audit=audit, prefs_get=prefs_get, nodes_rev=nodes_rev,
                     enroll_script=enroll_script, node_retire=node_retire, node_mark=node_mark,
                     node_discard=node_discard)


def rev():
    """Moves when a record is written or a node's census says something new
    of its VMs: read again only when the nodes' own revision has moved, so
    the poll that carries this costs nothing between hellos."""
    nr = nodes_rev()
    if nr != _seen["nodes"]:
        _seen["nodes"] = nr
        _seen["sig"] = hash(json.dumps([(n["id"], (n.get("reported") or {}).get("vms")) for n in node_list()],
                                       sort_keys=True, default=str))
    return f"{_rev[0]}.{_seen['sig'] & 0xffffff:x}"


def _file():
    return STATE / "vms.json"


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("vms", {})
    d.setdefault("nets", {})
    return d


def _save(d):
    write_json(_file(), d)
    _rev[0] += 1


def catalog():
    try:
        return json.loads(CATALOG_FILE.read_text()).get("images") or []
    except (OSError, ValueError):
        return []


def find_os(said):
    """(the catalog entry, "") for what was asked, or (None, the sentence that
    says what there is). Matched by id, by alias, or by a family and its
    version written any way ("Debian 12", "ubuntu-26.04", "rocky")."""
    want = re.sub(r"[\s_]+", "-", str(said or "").strip().lower())
    if not want:
        return None, "name an OS: " + ", ".join(i["id"] for i in catalog())
    for img in catalog():
        if want == img["id"] or want in img.get("aliases", ()) or want == img["name"].lower().replace(" ", "-"):
            return img, ""
    m = re.fullmatch(r"([a-z]+)-?([0-9.]+)?(-lts)?", want)
    if m:
        fam, ver = m.group(1), m.group(2) or ""
        for img in catalog():
            # The family by its own name or by an alias ("leap 16").
            if (img.get("family") == fam or fam in img.get("aliases", ())) \
                    and (not ver or img["id"].split("-", 1)[1].startswith(ver)):
                return img, ""
    near = difflib.get_close_matches(want, [i["id"] for i in catalog()], n=3, cutoff=0.4)
    return None, (f"no OS called {said} in the catalog" + (f"; the nearest: {', '.join(near)}" if near else "")
                  + f". It has: {', '.join(i['id'] for i in catalog())}")


def domain(project, name):
    """The libvirt name: bbvm-, the project and the VM, in what libvirt and a
    hostname both take."""
    slug = re.sub(r"[^a-z0-9-]+", "-", project.lower()).strip("-")[:24] or "p"
    return f"bbvm-{slug}-{name}"


def hosts():
    """The nodes a VM can go on: an agent node, not retired, whose VM host
    feature is installed and whose machine has /dev/kvm."""
    out = []
    for n in node_list():
        fe = ((n.get("reported") or {}).get("features") or {}).get("vmhost") or {}
        if n.get("kind") == "agent" and n.get("state") not in ("retired", "pending") and fe.get("installed") and fe.get("kvm"):
            out.append(n)
    return out


def _subnet(d, project, nid):
    """The project's /24 on that node, given once and kept."""
    nets = d["nets"].setdefault(nid, {})
    if project in nets:
        return nets[project]
    used = set(nets.values())
    for sub in VM_NET.subnets(new_prefix=24):
        if str(sub) not in used:
            nets[project] = str(sub)
            return str(sub)
    raise RuntimeError("every project network on this node is taken")


def nets_on(nid):
    """{project: its VM network} on one node, for the sessions' rules there."""
    return dict(_load()["nets"].get(nid) or {})


def _live(n):
    """What the node's census says of the VMs on it, by domain name."""
    return {v.get("name"): v for v in ((n or {}).get("reported") or {}).get("vms") or [] if isinstance(v, dict)}


def view(projects=None):
    """Every VM record, the node's census laid over it, for the page and for
    `bb vm list`: only the projects named, when `projects` is given."""
    d = _load()
    nodes = {n["id"]: n for n in node_list()}
    out = []
    for key, rec in sorted(d["vms"].items()):
        if projects is not None and rec.get("project") not in projects:
            continue
        n = nodes.get(rec.get("node"))
        live = _live(n).get(rec.get("domain"))
        row = dict(rec, key=key, node_name=(n or {}).get("name") or rec.get("node"), node_live=bool((n or {}).get("live")))
        if live:
            # The node's list, with what this side's own jobs made since its
            # last report.
            snaps = list(live.get("snapshots") or [])
            snaps += [x for x in rec.get("snaps") or [] if x not in snaps]
            row.update(state=live.get("state") or "unknown", ip=live.get("ip") or "", snapshots=snaps)
            # A node VM is on the LAN, where the host sees no lease of its:
            # its address is the one its agent dials in from.
            if rec.get("node_id") and not row["ip"]:
                vn = nodes.get(rec["node_id"]) or {}
                row["ip"] = (vn.get("agent") or {}).get("addr") or ""
        elif rec.get("state") == "made" and time.time() - rec.get("made_at", 0) < 180:
            # Made a moment ago and not in the node's report yet: its record's
            # "made", which the page reads as starting, not missing, which it
            # read for one poll (R97's walk).
            pass
        elif rec.get("state") not in ("making", "failed", "removing"):
            # Made, and the node's last report does not list it: not there.
            row.update(state="missing" if (n or {}).get("reported", {}).get("vms") is not None else "unknown")
        out.append(row)
    return out


def payload(projects=None):
    return {"vms": view(projects), "images": [{k: i.get(k) for k in ("id", "name", "family", "person", "why")}
                                               for i in catalog()],
            "hosts": [{"id": n["id"], "name": n["name"], "live": bool(n.get("live")),
                       "arch": (n.get("reported") or {}).get("arch") or "",
                       "pool": (n.get("reported") or {}).get("vm_pool") or {},
                       "mem_mb": (n.get("reported") or {}).get("mem_mb") or 0} for n in hosts()]}


def _used(d, project=None, nid=None):
    """What the VMs on record hold, added up: for one project, or one node."""
    tot = {"count": 0, "vcpus": 0, "mem_mb": 0, "disk_gb": 0}
    for rec in d["vms"].values():
        if (project and rec.get("project") != project) or (nid and rec.get("node") != nid):
            continue
        tot["count"] += 1
        for k in ("vcpus", "mem_mb", "disk_gb"):
            tot[k] += int(rec.get(k) or 0)
    return tot


def check_caps(d, project, nid, size):
    """The sentence a new VM of `size` is refused with, or "": the project's
    limits (its settings), then the node's own room (its memory and the VM
    pool's disk, less what it keeps for itself)."""
    caps = (prefs_get(project) or {}).get("vm_caps") or {}
    used = _used(d, project=project)
    words = {"count": "VMs", "vcpus": "vCPUs", "mem_mb": "MB of memory", "disk_gb": "GB of disk"}
    for k in ("count", "vcpus", "mem_mb", "disk_gb"):
        want = 1 if k == "count" else size[k]
        if k in caps and used[k] + want > caps[k]:
            return (f"{project}'s VMs may hold {caps[k]} {words[k]} in all and hold {used[k]}: this one would pass "
                    "that (an administrator raises it in the project's settings)")
    n = node(nid) or {}
    rep = n.get("reported") or {}
    on = _used(d, nid=nid)
    mem = int(rep.get("mem_mb") or 0)
    if mem and on["mem_mb"] + size["mem_mb"] > mem - NODE_KEEP_MB:
        return (f"{n.get('name', nid)} has {mem} MB of memory and its VMs are given {on['mem_mb']}: "
                f"{size['mem_mb']} more would leave it less than the {NODE_KEEP_MB} MB it keeps for itself")
    free = int((rep.get("vm_pool") or {}).get("free_mb") or 0) // 1024
    if (rep.get("vm_pool") or {}) and size["disk_gb"] > free - POOL_KEEP_GB:
        return (f"{n.get('name', nid)} has {free} GB free where VM disks go: a {size['disk_gb']} GB disk would leave it "
                f"less than the {POOL_KEEP_GB} GB it keeps")
    return ""


def _size(req):
    out = {}
    for k, dflt in DEFAULTS.items():
        v = req.get(k)
        try:
            out[k] = int(v) if v not in (None, "") else dflt
        except (TypeError, ValueError):
            return None, f"{k} is a whole number, not {v}"
    if not 1 <= out["vcpus"] <= 64 or not 256 <= out["mem_mb"] <= 262144 or not 2 <= out["disk_gb"] <= 4096:
        return None, "a VM takes 1 to 64 vCPUs, 256 MB to 256 GB of memory and a 2 GB to 4 TB disk"
    return out, ""


def create(principal, project, req, nodes_allowed, session=False):
    """A new VM for `project`: checked, recorded as making, and its create
    job queued on its node. `nodes_allowed` are the nodes the asker may put
    it on (a session: its project's own). The OS is a catalog name; one
    marked as a person's is refused to a session."""
    name = str(req.get("name") or "").strip().lower()
    if not NAME_RE.fullmatch(name):
        return {"error": f"a VM's name is letters, digits and dashes, up to 31, starting with a letter or digit: not {name or 'nothing'}"}
    img, why = find_os(req.get("os"))
    if not img:
        return {"error": why}
    if img.get("person"):
        return {"error": (f"{img['name']}: {img.get('why') or 'a person makes this one'}. "
                          + ("Ask a person to make it on the VMs page." if session else
                             "BuilderBot does not make it; a VM of your own with its installer is the way."))}
    size, why = _size(req)
    if not size:
        return {"error": why}
    keys = [str(k).strip() for k in (req.get("keys") or []) if str(k).strip()][:8]
    bad = [k[:30] for k in keys if not KEY_RE.fullmatch(k)]
    if bad:
        return {"error": f"not an ssh public key: {bad[0]}…"}
    if not keys:
        return {"error": "a VM needs an ssh public key to let anyone in: give one (bb vm new reads ~/.ssh/id_ed25519.pub)"}
    user = str(req.get("user") or "builder").strip().lower()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or user == "root":
        return {"error": f"the VM's account is a plain Linux name, not {user}"}
    can = [n for n in hosts() if n["id"] in nodes_allowed]
    want = str(req.get("node") or "")
    if want:
        pick = next((n for n in can if n["id"] == want or n["name"] == want), None)
        if not pick:
            return {"error": f"{want} is not a node {project} may put a VM on with VM host installed: "
                             + (", ".join(n["name"] for n in can) or "there is none yet (a node's Features section installs VM host)")}
    elif can:
        pick = can[0]
    else:
        return {"error": f"no node {project} works on has VM host installed: a node's Features section on the Nodes page installs it"}
    if not pick.get("live"):
        return {"error": f"{pick['name']}'s agent is not dialing in, so nothing from here reaches it"}
    arch = (pick.get("reported") or {}).get("arch") or "x86_64"
    src = (img.get("arch") or {}).get(arch)
    if not src:
        return {"error": f"{img['name']} has no image for {arch}, which {pick['name']} is"}
    key = f"{project}/{name}"
    # What refuses it, asked before a node row is made for it below: a
    # refusal after that left a waiting row behind, which then refused the
    # next try by its name.
    why = _refused(project, key, name, pick["id"], size)
    if why:
        return {"error": why}
    # Made a node as well (step 14): Enroll node's own script, for the
    # catalog's system, run by cloud-init at first boot, so the VM appears
    # on the Nodes page enrolled. `ctl` is the address the asker reached
    # this controller at, which the VM dials from its project network.
    enroll = None
    if req.get("node_agent") is True:
        sysid = {"ubuntu": "ubuntu", "debian": "debian", "rocky": "rocky", "fedora": "fedora",
                 "alpine": "alpine", "almalinux": "almalinux", "centos": "centos", "arch": "arch",
                 "opensuse": "opensuse", "gentoo": "gentoo"}.get(img.get("family") or "")
        if not sysid or enroll_script is None:
            return {"error": f"{img['name']} has no enroll script BuilderBot makes, so it cannot be made a node"}
        enroll = enroll_script(principal, {"name": f"{project}-{name}", "controller": str(req.get("ctl") or ""),
                                           "reach": "lan", "sessions": True, "system": sysid, "user": "bb",
                                           "script": True})
        if enroll.get("error"):
            return {"error": f"it cannot be made a node: {enroll['error']}"}
    with _lock:
        d = _load()
        why = _refused(project, key, name, pick["id"], size, d)
        if why:
            # ...and its row taken off again when something got in between.
            if enroll and node_discard:
                node_discard(principal, enroll["id"])
            return {"error": why}
        subnet = _subnet(d, project, pick["id"])
        dom = domain(project, name)
        spec = {"action": "create", "domain": dom, "project": project, "user": user, "keys": keys, **size,
                # Named by its subnet's place in VM_NET, which is the
                # project's alone on this node; short enough for a bridge.
                "network": f"bbvm-n{list(VM_NET.subnets(new_prefix=24)).index(ipaddress.ip_network(subnet)):02x}",
                "subnet": subnet,
                "image": {"id": img["id"] + "-" + arch, "url": src["url"], "sums": src["sums"],
                          "file": src["url"].rsplit("/", 1)[-1]},
                # UEFI for an image whose kernel resets under a BIOS boot
                # (Debian 13, on the dev node, 21 Oct); BIOS otherwise.
                "boot": "uefi" if img.get("boot") == "uefi" else "bios",
                "timeout": 3600}
        if enroll:
            spec["enroll"] = enroll["script"]
        r = job_add(principal, {"node": pick["id"]}, "vm", spec, project)
        if r.get("error"):
            if enroll and node_discard:
                node_discard(principal, enroll["id"])
            return r
        d["vms"][key] = {"project": project, "name": name, "node": pick["id"], "domain": dom, "os": img["id"],
                         "os_name": img["name"], "user": user, **size, "by": principal, "at": int(time.time()),
                         "state": "making", "job": r["job"], "error": "",
                         **({"node_id": enroll["id"]} if enroll else {})}
        _save(d)
    if enroll and node_mark:
        node_mark(enroll["id"], pick["id"])
    audit(principal, "vm-new", key, {"node": pick["id"], "os": img["id"], **size, "job": r["job"]})
    return {"ok": True, "key": key, "job": r["job"], "node": pick["name"], "domain": dom}


def _refused(project, key, name, node_id, size, d=None):
    """Why a new VM may not be made, or "": its name taken, a cap, or no
    room for the project's network."""
    d = d if d is not None else _load()
    if key in d["vms"]:
        return f"{project} has a VM called {name} already"
    why = check_caps(d, project, node_id, size)
    if why:
        return why
    try:
        _subnet(d, project, node_id)
    except RuntimeError as e:
        return str(e)
    return ""


def act(principal, project, name, action, req=None):
    """One action on a VM on record: queued as its node's vm job."""
    req = req or {}
    key = f"{project}/{name}"
    if action not in ACTIONS:
        return {"error": f"no such VM action: {action}; one of {', '.join(ACTIONS)}"}
    with _lock:
        d = _load()
        rec = d["vms"].get(key)
        if not rec:
            return {"error": f"{project} has no VM called {name}"}
        if rec.get("state") in ("making", "removing") and action != "remove":
            return {"error": f"{name} is {rec['state']}: wait for that to end"}
        n = node(rec["node"]) or {}
        if not n.get("live"):
            return {"error": f"{n.get('name') or rec['node']}'s agent is not dialing in, so nothing from here reaches {name}"}
        spec = {"action": action, "domain": rec["domain"], "timeout": 900}
        if action in ("snapshot", "revert", "snapshot-rm"):
            snap = str(req.get("snapshot") or "")
            if not SNAP_RE.fullmatch(snap):
                return {"error": f"a snapshot's name is letters, digits, dots, dashes and underscores: not {snap or 'nothing'}"}
            spec["snapshot"] = snap
            if action == "snapshot":
                spec["note"] = str(req.get("note") or "")[:200]
            known = set((_live(n).get(rec["domain"]) or {}).get("snapshots", [])) | set(rec.get("snaps") or [])
            if action != "snapshot" and snap not in known:
                return {"error": f"{name} has no snapshot called {snap}"}
        if action == "stop" and req.get("force"):
            spec["force"] = True
        r = job_add(principal, {"node": rec["node"]}, "vm", spec, project)
        if r.get("error"):
            return r
        rec["job"] = r["job"]
        rec["error"] = ""
        if action == "remove":
            rec["state"] = "removing"
        _save(d)
    audit(principal, f"vm-{action}", key, {"job": r["job"], **({"snapshot": spec["snapshot"]} if "snapshot" in spec else {})})
    return {"ok": True, "job": r["job"]}


def vm_done(job, state):
    """A vm job ended: the record learns what it did. A create that failed is
    kept, failed, with the reason, for a person to remove; a remove that
    succeeded takes the record."""
    spec = job.get("spec") or {}
    dom = spec.get("domain")
    with _lock:
        d = _load()
        key = next((k for k, r in d["vms"].items() if r.get("domain") == dom and r.get("node") == job.get("node")), None)
        if not key:
            return
        rec = d["vms"][key]
        ok = state == "succeeded"
        if spec.get("action") == "remove" and ok:
            gone = d["vms"].pop(key)
            # Its node goes with it, credential and all (step 14).
            if gone.get("node_id") and node_retire:
                node_retire(f"vm:{key}", gone["node_id"])
        elif spec.get("action") == "create":
            rec["state"] = "made" if ok else "failed"
            rec["made_at"] = int(time.time())
            rec["error"] = "" if ok else (job.get("error") or f"its create job {state}; the job's log says why")[:300]
        elif ok and spec.get("action") in ("snapshot", "snapshot-rm"):
            # What its own jobs did, kept until the node's next report says
            # so too: a revert pressed right after a snapshot finds it.
            snaps = [x for x in rec.get("snaps") or [] if x != spec.get("snapshot")]
            rec["snaps"] = snaps + ([spec["snapshot"]] if spec.get("action") == "snapshot" else [])
        elif not ok:
            if spec.get("action") == "remove":
                rec["state"] = "made"
            rec["error"] = (job.get("error") or f"{spec.get('action')} {state}; the job's log says why")[:300]
        _save(d)
