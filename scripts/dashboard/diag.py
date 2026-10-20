#!/usr/bin/env python3
"""The controller's diagnostics: one read-only report of whether a fix
landed and whether anything on the controller says something is wrong.

Who reads it (server.py _diag, the gate): an administrator anywhere, and a
Claude session only when three things hold. The controller's debug switch is
on, the session's node is ticked for it on Debug settings, and the session's
account is an administrator. The last one is what makes this a middle ground
rather than a hole: a node is shared, so a per-node grant alone would hand the
report to every tester whose session runs there.

What it holds is what an operator would look at to answer "is it in, and is
it working": the build and the images this box has run, the switches, the
doctor's every check, each node's agent and session half, the job counts and
the recent failures, the error lines in the controller's own logs, and the
audit trail's recent rows. What it never holds is a credential, an
environment, a file from a project or a job's output: every string that
leaves here goes through redact(), and the log scan keeps only lines that
look like a fault.
"""

import collections
import json
import sys
import os
import re
import subprocess
import time
from pathlib import Path

# Injected by configure(); declared here so a reader and ruff can see them.
image_stamp = None        # () -> {"rev", "built", "version"}
uptime = None             # () -> "1-02:03:04"
doctor_payload = None     # () -> the Doctor card's payload
settings = None           # the settings module
nodes = None              # the node registry
db = None                 # the store
plugins = None            # plugins.py: each account's Claude plugins
reports = None            # reports.py: problems with BuilderBot, from any project's session
users = None              # the account store, for names
log_dir = None            # () -> Path of the controller's logs
state_dir = None          # () -> Path of /config, for its state version
IMAGE_LOG = Path(os.environ.get("BB_IMAGE_LOG", "/config/image-log.tsv"))

SECTIONS = ("controller", "images", "settings", "doctor", "nodes", "plugins", "jobs", "errors", "audit",
            "reports")


def configure(**deps):
    globals().update(deps)


# Anything shaped like a credential, wherever it turns up, in order: this
# product's own tokens and the forges', then an HTTP credential by its scheme
# (the scheme first, or `Authorization: Bearer X` loses the word Bearer and
# keeps X, which diag.mjs caught), then anything written as key=value or
# key: value under a name that means secret. Deliberately broad: a false
# positive costs a word.
_SECRETS = (
    re.compile(r"bb[a-z]_[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}"
               r"|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}"),
    re.compile(r"(?i)\b(?:token|password|passwd|secret|authorization|api[_-]?key)[\"']?\s*[:=]\s*[\"']?"
               r"[^\s\"',;]{6,}"),
)


def redact(text):
    out = str(text)
    for pat in _SECRETS:
        out = pat.sub("<redacted>", out)
    return out


def _ago(t):
    try:
        s = int(time.time() - float(t))
    except (TypeError, ValueError):
        return ""
    if s < 120:
        return f"{s}s ago"
    if s < 7200:
        return f"{s // 60}m ago"
    if s < 172800:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _git():
    try:
        return subprocess.run(["git", "--version"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def controller():
    st = image_stamp() or {}
    return {"version": st.get("version") or "", "rev": st.get("rev", "")[:12],
            "built": st.get("built") or "", "uptime": uptime(),
            "agent_shipped": (nodes.agent_file() or {}).get("version", ""),
            "bundle": (nodes.bundle_digest() or "")[:16], "git": _git(), **_state()}


def _state():
    """The /config state version (stateversion.py): what the upgrade check
    reads first, and why an upgrade is held when one is."""
    if not state_dir:
        return {}
    try:
        import stateversion
        n, by = stateversion.read(state_dir())
        return {"state": n, "state_by": by, "state_current": stateversion.current(),
                "state_held": stateversion.HELD}
    except Exception as e:                       # noqa: BLE001 (a report never fails on one section)
        return {"state_error": str(e)[:200]}


def images(n=8):
    """The last images this box ran, from the entrypoint's own record."""
    try:
        lines = IMAGE_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [redact(x) for x in lines[-n:]]


def settings_now():
    got = settings.payload() if hasattr(settings, "payload") else {}
    vals = (got or {}).get("settings") or {}
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in vals.items()}


def doctor():
    d = doctor_payload() or {}
    return {"when": _ago(d.get("when")) if d.get("when") else "never",
            "checks": [{"level": c.get("level"), "text": redact(c.get("text", "")),
                        "detail": redact(c.get("detail", ""))}
                       for c in d.get("checks") or []]}


def nodes_now():
    shipped = (nodes.agent_file() or {}).get("version", "")
    out = []
    for n in nodes.node_list(all=True):
        if n.get("kind") != "agent" or n.get("state") == "retired":
            continue
        rep, ag = n.get("reported") or {}, n.get("agent") or {}
        se = rep.get("session") if isinstance(rep.get("session"), dict) else {}
        iso = rep.get("isolation") if isinstance(rep.get("isolation"), dict) else {}
        out.append({
            "name": n.get("name"), "id": n.get("id"), "state": n.get("state"),
            "live": n.get("live") is not False, "last_seen": _ago(ag.get("last_seen")),
            "agent": ag.get("version") or "?", "agent_current": ag.get("version") == shipped,
            "git": str(rep.get("git") or "")[:40],
            "session": {"up": bool(se.get("up")), "why": redact(se.get("why") or ""),
                        "workspace": bool(se.get("workspace")), "writable": se.get("writable"),
                        "bundle": str(se.get("bundle") or "")[7:23]},
            "views": {"built": bool(iso.get("sessions")), "why": redact(iso.get("why") or "")},
            "mount_errors": [redact(f"{m.get('path')}: {m.get('error')}")
                             for m in rep.get("mounts") or []
                             if isinstance(m, dict) and m.get("error")][:4],
        })
    return out


def plugins_now():
    """The Claude plugins each account installed, per node, by name: what a
    session that behaves oddly may be carrying beside BuilderBot's own hooks
    and briefing (plugins.py). Names and versions only."""
    who = {u.get("uid"): n for n, u in (users.load().get("users") or {}).items()}
    where = {n["id"]: n.get("name") for n in nodes.node_list(all=True)}
    return [{"account": who.get(uid, uid), "node": where.get(nid, nid),
             "plugins": [p["id"] + (f" {p['version']}" if p.get("version") else "")
                         + (" (off)" if p.get("enabled") is False else "")
                         + (f" (project {p['project']})" if p.get("scope") == "project" else "")
                         for p in rows]}
            for uid, per in sorted(plugins.everyone().items()) for nid, rows in sorted(per.items())]


def jobs(failed_n=15):
    since = int(time.time()) - 86400
    counts = {r["state"]: r["n"] for r in db._rows(
        "SELECT state, COUNT(*) AS n FROM jobs WHERE queued >= ? GROUP BY state", (since,))}
    names = {n["id"]: n.get("name") for n in nodes.node_list(all=True)}
    failed = db._rows(
        "SELECT id, type, project, node, state, exit_code, error, ended, queued FROM jobs "
        "WHERE state NOT IN ('succeeded', 'queued', 'running') "
        "ORDER BY COALESCE(ended, queued) DESC LIMIT ?", (int(failed_n),))
    return {"last_24h": counts,
            "failed": [{"id": j["id"], "type": j["type"], "project": j["project"],
                        "node": names.get(j["node"], j["node"]), "state": j["state"],
                        "exit": j["exit_code"], "error": redact(j["error"] or "")[:200],
                        "when": _ago(j["ended"] or j["queued"])} for j in failed]}


# What a fault looks like in the controller's own log. Everything else in it
# is traffic, and traffic is where a request line with a project's words in
# it would be, so it stays out.
_FAULT = re.compile(r"Traceback|Error\b|ERROR|\[warn\]|\bWARN|exception|failed|refused|timed out",
                    re.IGNORECASE)


def errors(n=40, scan=4000):
    out = []
    d = log_dir()
    for name in ("builderbot.log", "dashboard.log"):
        try:
            with open(Path(d) / name, encoding="utf-8", errors="replace") as f:
                tail = collections.deque(f, maxlen=scan)
        except OSError:
            continue
        out += [f"{name}: {redact(x.rstrip())[:300]}" for x in tail if _FAULT.search(x)]
    return out[-n:]


def audit(n=30):
    return [{"when": _ago(r.get("at")), "who": redact(r.get("principal", "")),
             "action": r.get("action", ""), "target": redact(r.get("target", ""))}
            for r in db.audit_tail(n)]


def reports_now(n=40):
    """What sessions and people have reported about BuilderBot, newest
    first, when each was made. Their
    words were redacted when they were stored. One that carries its
    reporter's conversation names the file it is in, which the downloaded
    diagnostics carry beside this report rather than inside it (the
    operator, 2 Oct: a conversation is often megabytes)."""
    return [r | {"when": _ago(r.get("at"))}
            | ({"conversation": r["conversation"] | {"file": f"conversations/report-{r['id']}.txt"}}
               if r.get("conversation") else {})
            for r in reports.listing(n=n)]


_BUILD = {"controller": controller, "images": images, "settings": settings_now,
          "doctor": doctor, "nodes": nodes_now, "plugins": plugins_now, "jobs": jobs, "errors": errors,
          "audit": audit, "reports": reports_now}


def report(sections=None):
    """The whole report, or the sections asked for. A section that fails says
    so in place rather than taking the rest down with it."""
    unknown = [s for s in (sections or []) if s not in _BUILD]
    if unknown:
        return {"error": f"no section {', '.join(unknown)}: the sections are {', '.join(SECTIONS)}"}
    want = [s for s in (sections or SECTIONS) if s in _BUILD]
    out = {"at": int(time.time())}
    for s in want:
        try:
            out[s] = _BUILD[s]()
        except Exception as e:                                   # noqa: BLE001 (each section is another module's; one failing is reported in place)
            out[s] = {"error": redact(f"{type(e).__name__}: {e}")[:200]}
            print(f"dashboard: diag: section {s} failed: {out[s]['error']}",
                  file=sys.stderr, flush=True)
    return json.loads(json.dumps(out, default=str))
