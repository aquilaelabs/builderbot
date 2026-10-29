"""BuilderBot's own scanners on each node (R145, the operator, 26 Oct).

The Scanners page, in the Containers group beside nginx, deploys one
compose project of the three static analysis scanners (Semgrep, Trivy,
mobsfscan) to each node that holds projects and runs them there on a
schedule. A run scans the projects whose node it is, never a project's
extra nodes, so nothing is scanned twice, and a project moved to another
node is scanned on its new node next run. The agent sends each SARIF up
to the controller over its own API, as sync's put sends files, so nothing
of the controller's is mounted on a node (R163); the controller keeps them
in its state beside the folder a host scanner may still write to
(SCANNER_REPORTS_PATH, deprecated in 0.9.0), and findings.py reads both.

  STATE/scanners.json      {"schedule": {"on", "cron", "due", "last", "skipped"},
                            "nodes": {nid: {"versions": {...}, "deployed": t,
                            "last": {at, job, error, by, late, projects}}},
                            "latest": {"at", "versions", "error"}}
  STATE/scan-reports/NID/  the SARIF a node's run sent up, one per scanner

The compose file carries the three as one-shot services under a profile,
so a `compose up` starts none; a run (the agent's scan job, scan.py there)
is `compose run --rm` per scanner with that node's project copies mounted
read-only at /src/NAME, and the SARIF lands in ./reports beside the file.
The versions are pinned per node when it is deployed or updated (as nginx's
image is, R192), and a weekly check reads Docker Hub and PyPI for newer.
"""
import contextlib
import json
import os
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path

STATE = None
write_json = None
node_list = None         # () -> the nodes (nodes.node_list)
node_name = None         # nid -> its name
project_nodes = None     # () -> {project: primary node id} (nodes.project_nodes)
project_names = None     # () -> every project's name
job_add = None           # (principal, placement, type, spec) -> {job} | {error}
job_state = None         # jid -> "queued" | "running" | ... | ""
next_after = None        # schedules.next_after(cron, after)
cron_words = None        # schedules.words(cron)
_lock = threading.Lock()
_rev = 0

SCANNERS = ("semgrep", "trivy", "mobsfscan")
# The pins a fresh deploy takes, moved on purpose a release at a time, and
# what the weekly check compares against.
VERSIONS = {"semgrep": "1.179.0", "trivy": "0.75.0", "mobsfscan": "0.4.5"}
IMAGES = {"semgrep": "semgrep/semgrep", "trivy": "aquasec/trivy"}
SEMGREP_TAGS_URL = os.environ.get("BB_SEMGREP_TAGS_URL") or "https://hub.docker.com/v2/repositories/semgrep/semgrep/tags?page_size=100"
TRIVY_TAGS_URL = os.environ.get("BB_TRIVY_TAGS_URL") or "https://hub.docker.com/v2/repositories/aquasec/trivy/tags?page_size=100"
MOBSFSCAN_URL = os.environ.get("BB_MOBSFSCAN_URL") or "https://pypi.org/pypi/mobsfscan/json"
CHECK_EVERY = 7 * 86400
CHECK_DELAY = float(os.environ.get("BB_SCANNER_CHECK_DELAY") or 300)
AUTOCHECK = os.environ.get("BB_SCANNER_AUTOCHECK", "1") != "0"
DEFAULT_CRON = "0 4 * * 0"
TIMEOUT = 4 * 3600
MAX_REPORT = 64 << 20
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PRINCIPAL = "scanners"


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = Path(deps["state"])


# ---- the record ---------------------------------------------------------------

def _file():
    return STATE / "scanners.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        d = {}
    d.setdefault("schedule", {"on": False, "cron": DEFAULT_CRON})
    d.setdefault("nodes", {})
    d.setdefault("latest", {})
    return d


def _save(d):
    global _rev
    write_json(_file(), d)
    _rev += 1


def rev():
    return _rev


def record(nid):
    return dict(_load()["nodes"].get(str(nid)) or {})


def _reports_dir(nid):
    return STATE / "scan-reports" / re.sub(r"[^A-Za-z0-9_-]", "_", str(nid))


def container_name(nid):
    base = re.sub(r"[^a-z0-9-]", "-", str(node_name(nid) or nid).lower()).strip("-") or "node"
    return f"scanners-{base}"[:60]


def versions_of(rec):
    """What a node runs: its pins, or the defaults for one deployed before
    pins were kept."""
    v = rec.get("versions") if isinstance(rec.get("versions"), dict) else {}
    return {s: str(v.get(s) or VERSIONS[s]) for s in SCANNERS}


# ---- the compose file ---------------------------------------------------------

def compose_text(nid, rec):
    """The three scanners as one-shot services under the scan profile:
    nothing starts at an up; a run is `compose run --rm` per service with
    the projects mounted at /src by the agent. Cache volumes are docker's
    own, named; the reports land in ./reports beside the file."""
    v = versions_of(rec)
    excl = "--exclude node_modules --exclude .git --exclude .worktrees --exclude .claude"
    return "\n".join([
        "# Written by BuilderBot from the Scanners page (scanners.py); Deploy and Update rewrite it.",
        "services:",
        "  semgrep:",
        f"    image: {IMAGES['semgrep']}:{v['semgrep']}",
        "    profiles: [scan]",
        "    working_dir: /src",
        "    volumes:",
        "      - ./reports:/reports",
        "      - semgrep_cache:/root/.semgrep",
        "    # p/default: the registry's curated rules, no account needed; a",
        "    # `# nosemgrep: RULE` line with its reason answers a finding.",
        f"    command: semgrep scan --config p/default --metrics off --sarif --output /reports/semgrep.sarif {excl} /src",
        "  trivy:",
        f"    image: {IMAGES['trivy']}:{v['trivy']}",
        "    profiles: [scan]",
        "    volumes:",
        "      - ./reports:/reports",
        "      - trivy_cache:/cache",
        "    command: fs --cache-dir /cache --scanners vuln,secret,misconfig --format sarif --output /reports/trivy.sarif --skip-dirs node_modules --skip-dirs .worktrees /src",
        "  mobsfscan:",
        "    image: python:3.12-slim",
        "    profiles: [scan]",
        "    volumes:",
        "      - ./reports:/reports",
        "      - mobsfscan_cache:/root/.cache/pip",
        "    # Its exit 1 means it found something, which is not a failed scan.",
        f"    command: sh -c \"pip install --quiet --no-cache-dir mobsfscan=={v['mobsfscan']} && mobsfscan --sarif -o /reports/mobsfscan.sarif /src; s=$$?; [ $$s -le 1 ]\"",
        "volumes:",
        "  semgrep_cache:",
        "  trivy_cache:",
        "  mobsfscan_cache:",
        "",
    ])


def _spec(nid, rec, plan, extra=None):
    """A compose job's spec for this node's scanners: the file, the plan."""
    return {"name": container_name(nid), "files": {"compose.yml": compose_text(nid, rec)}, "plan": plan, **(extra or {})}


# ---- which nodes and projects -------------------------------------------------

def holders():
    """{nid: [projects]} for every project with a node: the node a project
    is bound to holds it, and its extra nodes never do here."""
    out = {}
    for p, nid in (project_nodes() if project_nodes else {}).items():
        if nid:
            out.setdefault(str(nid), []).append(p)
    return {k: sorted(v) for k, v in out.items()}


def _agent_nodes():
    return [n for n in (node_list() if node_list else []) if n.get("kind") == "agent" and n.get("state") not in ("retired", "pending")]


def uncovered():
    """The projects no scanner covers, each with why: no node, a node that
    hosts containers only, or a node with no scanners deployed."""
    held = holders()
    nodes = {n["id"]: n for n in _agent_nodes()}
    recs = _load()["nodes"]
    out = []
    for p in sorted(project_names() if project_names else []):
        nid = (project_nodes() or {}).get(p, "") if project_nodes else ""
        if not nid:
            out.append({"project": p, "why": "no node"})
        elif nid not in nodes:
            out.append({"project": p, "why": "its node is not enrolled now"})
        elif (nodes[nid].get("config") or {}).get("host_only"):
            out.append({"project": p, "why": f"{nodes[nid].get('name') or nid} hosts containers only"})
        elif not (recs.get(nid) or {}).get("deployed"):
            out.append({"project": p, "why": f"no scanners on {nodes[nid].get('name') or nid}"})
    del held
    return out


# ---- deploy, update, remove ---------------------------------------------------

def deploy(nid, by=""):
    """The scanners put on a node: its versions pinned to what is newest
    known, the compose file written on the node and its images pulled, as a
    compose job there."""
    n = next((x for x in _agent_nodes() if x["id"] == nid), None)
    if not n:
        return {"error": "no such node"}
    if (n.get("config") or {}).get("host_only"):
        return {"error": f"{n.get('name') or nid} hosts containers only: it holds no project to scan"}
    with _lock:
        d = _load()
        rec = dict(d["nodes"].get(str(nid)) or {})
        rec["versions"] = dict(latest_versions())
        d["nodes"][str(nid)] = rec
        _save(d)
    r = job_add(f"{PRINCIPAL}:{by or 'page'}", {"node": nid}, "compose",
                _spec(nid, rec, [{"name": "pull", "argv": ["docker", "compose", "-f", "{cdir}/compose.yml", "--profile", "scan", "pull"], "timeout": 1800}]))
    if r.get("error"):
        return r
    with _lock:
        d = _load()
        d["nodes"].setdefault(str(nid), {}).update(deployed=int(time.time()), versions=rec["versions"], deploy_job=r["job"])
        _save(d)
    return {"ok": True, "job": r["job"], "versions": rec["versions"]}


def deploy_all(by=""):
    """Deploy on every node that holds projects and has none yet."""
    out = {}
    recs = _load()["nodes"]
    for nid in holders():
        if (recs.get(nid) or {}).get("deployed"):
            continue
        out[nid] = deploy(nid, by)
    return {"ok": True, "nodes": out}


def update(nid, by=""):
    """The newer versions pinned on the node and pulled."""
    rec = record(nid)
    if not rec.get("deployed"):
        return {"error": "not deployed there: Deploy puts the scanners on the node"}
    lt = latest_versions()
    if versions_of(rec) == lt:
        return {"ok": True, "same": True, "note": "it runs the newest versions known"}
    return deploy(nid, by)


def remove(nid, by=""):
    """The scanners taken off a node: its compose project down and gone,
    the record and the reports it sent kept no more."""
    rec = record(nid)
    if not rec.get("deployed"):
        return {"error": "not deployed there"}
    r = job_add(f"{PRINCIPAL}:{by or 'page'}", {"node": nid}, "compose",
                _spec(nid, rec, [{"name": "down", "argv": ["docker", "compose", "-f", "{cdir}/compose.yml", "--profile", "scan", "down", "--volumes", "--rmi", "all"], "timeout": 1800}]))
    with _lock:
        d = _load()
        d["nodes"].pop(str(nid), None)
        _save(d)
    shutil.rmtree(_reports_dir(nid), ignore_errors=True)
    return {"ok": True, "job": r.get("job", ""), "note": r.get("error", "")}


# ---- the versions: a weekly check, Update when behind ---------------------------

def latest_versions():
    """The newest versions known: the last check's where it found newer,
    else the defaults."""
    lt = _load()["latest"]
    v = lt.get("versions") if isinstance(lt.get("versions"), dict) else {}
    return {s: str(v.get(s) or VERSIONS[s]) for s in SCANNERS}


def _newest(tags):
    """The highest plain x.y.z among tag names."""
    best = None
    for t in tags:
        if VERSION_RE.match(str(t)):
            parts = tuple(int(x) for x in str(t).split("."))
            if best is None or parts > best[0]:
                best = (parts, str(t))
    return best[1] if best else ""


def _fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "BuilderBot"}), timeout=30) as r:
        return json.loads(r.read())


def check_versions():
    """Docker Hub's tag lists and PyPI read now; what is newer than the
    defaults kept as latest, the error otherwise."""
    found, errors = {}, []
    for s, url in (("semgrep", SEMGREP_TAGS_URL), ("trivy", TRIVY_TAGS_URL)):
        try:
            d = _fetch_json(url)
            tags = [t.get("name") for t in (d.get("results") or []) if isinstance(t, dict)]
            v = _newest(tags)
            if v:
                found[s] = v
        except (OSError, ValueError, AttributeError) as e:
            errors.append(f"{s}: {type(e).__name__}")
    try:
        d = _fetch_json(MOBSFSCAN_URL)
        v = str((d.get("info") or {}).get("version") or "")
        if VERSION_RE.match(v):
            found["mobsfscan"] = v
    except (OSError, ValueError, AttributeError) as e:
        errors.append(f"mobsfscan: {type(e).__name__}")
    with _lock:
        d = _load()
        d["latest"] = {"at": int(time.time()), "versions": {s: max(found.get(s, VERSIONS[s]), VERSIONS[s], key=lambda x: tuple(int(p) for p in x.split(".")))
                                                            for s in SCANNERS},
                       "error": "; ".join(errors)}
        _save(d)
    return d["latest"]


import checks  # noqa: E402 (the cadence, R176)


def check_loop():
    time.sleep(CHECK_DELAY)
    while True:
        if AUTOCHECK and checks.due("scanners", int(_load()["latest"].get("at") or 0)):
            with contextlib.suppress(Exception):            # noqa: BLE001 (the loop outlives one bad answer)
                check_versions()
        time.sleep(600)


def behind(rec):
    """The scanners a deployed node runs older versions of than known."""
    v, lt = versions_of(rec), latest_versions()
    return {s: lt[s] for s in SCANNERS if v[s] != lt[s]}


# ---- the schedule and a run -----------------------------------------------------

def schedule():
    s = _load()["schedule"]
    cron = str(s.get("cron") or DEFAULT_CRON)
    return {"on": bool(s.get("on")), "cron": cron, "words": cron_words(cron) if cron_words else cron,
            "next_at": s.get("due") if s.get("on") else None, "last": s.get("last") or {}, "skipped": s.get("skipped") or {}}


def set_schedule(on=None, cron=None):
    with _lock:
        d = _load()
        s = d["schedule"]
        if cron is not None:
            cron = re.sub(r"\s+", " ", str(cron)).strip()
            if not next_after or next_after(cron, time.time()) is None:
                return {"error": "a timetable is cron's five fields, and this one names no minute"}
            s["cron"] = cron
            s.pop("due", None)
        if on is not None:
            s["on"] = bool(on)
            if not on:
                s.pop("due", None)
        _save(d)
    return {"ok": True, **schedule()}


def _run_on(nid, projects, by, late=""):
    """One run on a node: the scan job, with the projects whose node it is."""
    rec = record(nid)
    spec = _spec(nid, rec, [], {"projects": projects, "scanners": list(SCANNERS), "timeout": TIMEOUT,
                                "versions": versions_of(rec)})
    r = job_add(f"{PRINCIPAL}:{by or 'schedule'}", {"node": nid}, "scan", spec)
    with _lock:
        d = _load()
        d["nodes"].setdefault(str(nid), {})["last"] = {"at": int(time.time()), "job": r.get("job", ""), "error": r.get("error", ""),
                                                        "by": by, "late": late, "projects": projects}
        _save(d)
    return r


def run_now(by="", nid=""):
    """A run on one deployed node, or on every one, now; a node whose last
    run is still going is skipped and said."""
    recs = _load()["nodes"]
    held = holders()
    out = {}
    for n in ([nid] if nid else sorted(k for k in recs if recs[k].get("deployed"))):
        if not (recs.get(n) or {}).get("deployed"):
            out[n] = {"error": "not deployed there"}
            continue
        last = ((recs.get(n) or {}).get("last") or {}).get("job") or ""
        if last and job_state and job_state(last) in ("queued", "assigned", "running"):
            out[n] = {"error": "its last run is still going"}
            continue
        if not held.get(n):
            out[n] = {"error": "no project is bound to it"}
            continue
        out[n] = _run_on(n, held[n], by)
    with _lock:
        d = _load()
        d["schedule"]["last"] = {"at": int(time.time()), "by": by, "nodes": {k: v.get("job", "") or v.get("error", "") for k, v in out.items()}}
        _save(d)
    return {"ok": True, "nodes": out}


def tick(now=None):
    """The timer's minute, from the server's loop: the schedule fires when
    due on every deployed node, a missed minute runs once and is said late;
    the next due is kept."""
    now = time.time() if now is None else now
    d = _load()
    s = d["schedule"]
    if not s.get("on") or not next_after:
        return False
    due = s.get("due")
    if not due:
        with _lock:
            d = _load()
            d["schedule"]["due"] = next_after(s.get("cron") or DEFAULT_CRON, now)
            _save(d)
        return False
    if now < due:
        return False
    nxt = next_after(s.get("cron") or DEFAULT_CRON, now)
    late = f"{int((now - due) // 60)} min late" if now - due > 300 else ""
    with _lock:
        d = _load()
        d["schedule"]["due"] = nxt
        _save(d)
    run_now(by="schedule" + (f", {late}" if late else ""))
    return True


# ---- the reports a node sends up ----------------------------------------------

def take_report(nid, scanner, stream, length, projects=""):
    """One SARIF from a node's run, kept as that node's for that scanner;
    what findings.py reads beside /reports."""
    if scanner not in SCANNERS:
        return {"error": "not a scanner here"}, 400
    if length < 0 or length > MAX_REPORT:
        return {"error": f"over {MAX_REPORT >> 20} MB: not taken"}, 413
    d = _reports_dir(nid)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{scanner}.sarif.new"
    left = length
    with open(tmp, "wb") as f:
        while left > 0:
            chunk = stream.read(min(65536, left))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    if left:
        tmp.unlink(missing_ok=True)
        return {"error": "short body"}, 400
    try:
        json.loads(tmp.read_bytes())
    except ValueError:
        tmp.unlink(missing_ok=True)
        return {"error": "not JSON"}, 400
    os.replace(tmp, d / f"{scanner}.sarif")
    with _lock:
        rec = _load()
        r = rec["nodes"].setdefault(str(nid), {})
        r.setdefault("reports", {})[scanner] = {"at": int(time.time()), "size": length, "projects": projects}
        _save(rec)
    return {"ok": True}, 200


def report_files():
    """Every SARIF a node sent up, newest run first by node."""
    root = STATE / "scan-reports"
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir():
            out += sorted(d.glob("*.sarif"))
    return out


# ---- the page and the bell ----------------------------------------------------

def view():
    """The Scanners page: each agent node with its scanners' state, the
    schedule, the versions known, and the projects nothing covers."""
    d = _load()
    held = holders()
    lt = latest_versions()
    rows = []
    for n in _agent_nodes():
        nid = n["id"]
        rec = d["nodes"].get(nid) or {}
        last = rec.get("last") or {}
        st = job_state(last.get("job")) if job_state and last.get("job") else ""
        rows.append({"node": nid, "name": n.get("name") or nid, "live": n.get("live"),
                     "host_only": bool((n.get("config") or {}).get("host_only")),
                     "deployed": bool(rec.get("deployed")), "deployed_at": rec.get("deployed", 0),
                     "versions": versions_of(rec) if rec.get("deployed") else {}, "behind": behind(rec) if rec.get("deployed") else {},
                     "projects": held.get(nid, []), "last": {**last, "state": st},
                     "reports": rec.get("reports") or {}, "deploy_job": rec.get("deploy_job", ""),
                     "deploy_state": job_state(rec.get("deploy_job")) if job_state and rec.get("deploy_job") else ""})
    return {"nodes": rows, "schedule": schedule(), "latest": {**d["latest"], "versions": lt}, "defaults": VERSIONS,
            "uncovered": uncovered(), "rev": _rev}


def attention():
    """The bell's rows: a run that failed on a node, and a node behind the
    newest versions, each kind scan."""
    out = []
    d = _load()
    names = {n["id"]: n.get("name") or n["id"] for n in _agent_nodes()}
    for nid, rec in d["nodes"].items():
        if nid not in names or not rec.get("deployed"):
            continue
        last = rec.get("last") or {}
        st = job_state(last.get("job")) if job_state and last.get("job") else ""
        if last.get("error") or st == "failed":
            out.append({"kind": "scan", "node": names[nid], "id": nid, "what": "failed",
                        "said": last.get("error") or "its last run failed", "job": last.get("job", ""),
                        "key": f"scan-failed:{nid}:{last.get('at', 0)}"})
        b = behind(rec)
        if b:
            out.append({"kind": "scan", "node": names[nid], "id": nid, "what": "behind",
                        "said": ", ".join(f"{s} {v}" for s, v in sorted(b.items())),
                        "key": "scan-behind:" + nid + ":" + ",".join(sorted(b.values()))})
    return out


def forget_node(nid):
    """A node retired: its record and its reports go."""
    with _lock:
        d = _load()
        if d["nodes"].pop(str(nid), None) is not None:
            _save(d)
    shutil.rmtree(_reports_dir(nid), ignore_errors=True)
