"""A project's CI watched from the day it is linked (R117), on every
BuilderBot and for every project, with nothing set up in the repository.

Shebang-DevBoard's CI had failed for weeks on an action GitHub had moved
past (setup-android v3 asking for an SDK package Google stopped serving),
and the move of ubuntu-latest to Ubuntu 26 was seen only because a session
happened to read a run's annotations (2 Oct). Both were on GitHub to be
read; nothing read them. This does, once when a project is linked and
then once a day:

  - the tree's workflows: a hosted job on a moving label (ubuntu-latest),
    and each action against its newest release's major version;
  - on GitHub, with the controller's token (cilogs.py): whether the newest
    finished run on the main branch passed, and the warnings and notices
    GitHub wrote on it, which is where it announces a retired Node or a
    runner image about to move.

What it finds is kept per project (STATE/ciwatch/PROJECT.json) and read
by the Git view, bb catchup and, for a red main branch, the bell. It only
reads: a fix is a change somebody makes on a branch.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import cilogs

STATE = Path("/config")
WORKSPACE = Path("/workspace")
write_json = None
projects_fn = None      # () -> every project name

EVERY = 24 * 3600
DELAY = int(os.environ.get("BB_CIWATCH_DELAY", "600"))
RELEASE_TTL = 24 * 3600
PINNED = {"ubuntu": "ubuntu-24.04", "windows": "windows-2025", "macos": "macos-15"}
_lock = threading.Lock()
_busy = set()


def configure(*, state, workspace, write_json_fn, projects=None):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), write_json=write_json_fn,
                     projects_fn=projects)


def _file(project):
    return STATE / "ciwatch" / f"{project}.json"


def read(project):
    """What the last look found, or {} before the first."""
    try:
        return json.loads(_file(project).read_text())
    except (OSError, ValueError):
        return {}


# ---- the tree ------------------------------------------------------------------

# The comment beside a commit pin says its version ("# v4, pinned by commit"):
# the v and the number, never the comma after them.
USES = re.compile(r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s]*)?@([^\s#]+)\s*(?:#\s*(v?\d[\w.]*))?")


def workflows(project):
    """[(file:line, kind, value)] for every runs-on and uses: in the tree's
    workflows, read as text: nothing in them is run."""
    out = []
    for f in sorted((WORKSPACE / project / ".github" / "workflows").glob("*.y*ml")):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r"\s*runs-on:\s*(.+?)\s*(#.*)?$", line)
            if m and "${{" not in m.group(1):
                out.append((f"{f.name}:{i}", "runs-on", m.group(1)))
            m = USES.match(line)
            if m:
                # A commit pin carries its version in the comment beside it.
                ref = m.group(2) if not re.fullmatch(r"[0-9a-f]{40}", m.group(2)) else (m.group(3) or "")
                out.append((f"{f.name}:{i}", "uses", f"{m.group(1)}@{ref}"))
    return out


def _major(ref):
    m = re.match(r"v?(\d+)", ref or "")
    return int(m.group(1)) if m else None


def _newest_major(action, token):
    """The newest release's major of owner/repo, cached a day across every
    project; None when GitHub does not say."""
    cache = STATE / "ciwatch" / "_releases.json"
    try:
        seen = json.loads(cache.read_text())
    except (OSError, ValueError):
        seen = {}
    hit = seen.get(action)
    if hit and time.time() - hit.get("at", 0) < RELEASE_TTL:
        return hit.get("major")
    try:
        tag = cilogs._get(f"/repos/{action}/releases/latest", token).get("tag_name", "")
    except cilogs.Refused:
        tag = ""
    major = _major(tag)
    seen[action] = {"major": major, "tag": tag, "at": int(time.time())}
    if write_json:
        write_json(cache, seen)
    return major


# ---- one look --------------------------------------------------------------------

NOTICE = re.compile(r"deprecat|will (?:be )?(?:migrat|remov|retir|stop)|no longer (?:be )?support|end of life",
                    re.I)


def look(project):
    """Look now, keep what was found, and return it."""
    found, run, err = [], {}, ""
    token = cilogs._token(project)
    flows = workflows(project)
    for where, kind, val in flows:
        if kind == "runs-on":
            for os_ in re.findall(r"\b(ubuntu|windows|macos)-latest\b", val):
                found.append({"kind": "label", "sev": "warn", "where": where,
                              "text": f"runs on {os_}-latest, which GitHub moves to a new release on its own date: "
                                      f"runs-on: {PINNED[os_]} moves only in a commit"})
        elif kind == "uses":
            action, _, ref = val.partition("@")
            have = _major(ref)
            new = _newest_major(action, token) if have is not None else None
            if have is not None and new is not None and new > have:
                found.append({"kind": "action", "sev": "note", "where": where,
                              "text": f"{action}@{ref}: v{new} is out. An action a major behind is where a "
                                      "retired Node or a retired package breaks a run"})
    repo = cilogs.repo_of(project)
    if repo and flows:
        try:
            runs = cilogs.runs(project, 30)["runs"]
            main = _main_branch(project)
            # Each workflow by its newest run on main that came to a verdict:
            # a run stopped because a newer one superseded it, or skipped,
            # says nothing about the code (BuilderBot's android app run,
            # stopped by its successor, read as red on the first look).
            verdict = {}
            for r in runs:
                if r["status"] != "completed" or (main and r["branch"] != main):
                    continue
                # GitHub spells a stopped run its own way; matched by its stem.
                if r["conclusion"].startswith("cancel") or r["conclusion"] in ("skipped", "neutral") \
                        or r["name"] in verdict:
                    continue
                verdict[r["name"]] = r
            newest = None
            for r in verdict.values():
                if newest is None or r["at"] > newest["at"]:
                    newest = r
                if r["conclusion"] != "success":
                    found.append({"kind": "run", "sev": "bad", "where": f"run {r['id']}",
                                  "text": f"the newest {r['name']} run on {r['branch']} {ended(r['conclusion'])}: "
                                          f"bb ci-log {r['id']} reads it"})
            if newest:
                run = {k: newest[k] for k in ("id", "name", "branch", "conclusion", "at")}
                run["ended"] = ended(newest["conclusion"])
                found += _notices(repo, token, newest["id"])
        except cilogs.Refused as e:
            err = str(e)
    rec = {"at": int(time.time()), "repo": repo, "workflows": len({w.split(':')[0] for w, _, _ in flows}),
           "run": run, "findings": found[:40], "error": err}
    if write_json:
        write_json(_file(project), rec)
    return rec


def ended(conclusion):
    """GitHub's conclusion as words: "failure" is "failed"."""
    return {"success": "passed", "failure": "failed", "timed_out": "timed out", "skipped": "was skipped",
            "action_required": "is waiting on an approval", "startup_failure": "failed to start"}.get(
        conclusion, "was stopped" if conclusion and conclusion.startswith("cancel") else conclusion or "ended")


def _main_branch(project):
    head = WORKSPACE / project / ".git" / "refs" / "remotes" / "origin" / "HEAD"
    try:
        m = re.match(r"ref: refs/remotes/origin/(\S+)", head.read_text())
        return m.group(1) if m else ""
    except OSError:
        return ""


def _notices(repo, token, run_id):
    """The warnings GitHub wrote on a run that announce a change coming."""
    out, said = [], set()
    jobs = (cilogs._get(f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=20", token).get("jobs") or [])[:20]
    for j in jobs:
        try:
            notes = cilogs._get(f"/repos/{repo}/check-runs/{int(j.get('id') or 0)}/annotations", token)
        except cilogs.Refused:
            continue
        for a in (notes if isinstance(notes, list) else [])[:50]:
            msg = " ".join(str(a.get("message") or "").split())
            if a.get("annotation_level") in ("warning", "notice") and NOTICE.search(msg) and msg[:120] not in said:
                said.add(msg[:120])
                out.append({"kind": "notice", "sev": "warn", "where": f"run {run_id}",
                            "text": msg[:400]})
    return out[:8]


def claim(project):
    """True when nothing is looking at this project now, and it is yours."""
    with _lock:
        if project in _busy:
            return False
        _busy.add(project)
        return True


def release(project):
    with _lock:
        _busy.discard(project)


def look_soon(project):
    """A look on its own thread, at most one per project at a time: what a
    link or a press asks for, without holding the request."""
    if not claim(project):
        return False

    def go():
        try:
            look(project)
        except Exception as e:                                      # noqa: BLE001 (a look must not take the server)
            print(f"dashboard: ci watch {project}: {e}", flush=True)
        finally:
            release(project)
    threading.Thread(target=go, name=f"ciwatch-{project}", daemon=True).start()
    return True


def due(project, now=None):
    """Whether a project wants a look: it has workflows and its last look is
    a day old or never happened."""
    if not (WORKSPACE / project / ".github" / "workflows").is_dir():
        return False
    return (now or time.time()) - read(project).get("at", 0) >= EVERY


def start():
    """Once a day for each project with workflows, the first round DELAY
    after the controller starts. A daemon thread, so it dies with the
    server."""
    def loop():
        time.sleep(DELAY)
        while True:
            for p in (projects_fn() if projects_fn else []):
                if not due(p) or not claim(p):
                    continue
                try:
                    look(p)
                except Exception as e:                              # noqa: BLE001 (a loop must not die)
                    print(f"dashboard: ci watch {p}: {e}", flush=True)
                finally:
                    release(p)
            time.sleep(3600)
    threading.Thread(target=loop, name="ciwatch", daemon=True).start()


_seen = {}


def _cached(project):
    """read(), kept by the file's mtime: the bell asks on every poll."""
    try:
        mt = _file(project).stat().st_mtime
    except OSError:
        return {}
    hit = _seen.get(project)
    if not hit or hit[0] != mt:
        hit = _seen[project] = (mt, read(project))
    return hit[1]


def red(projects):
    """[{project, text, id}] for the projects whose main branch's newest
    run failed, for the bell; drawn while true, nothing to dismiss."""
    out = []
    for p in projects:
        for f in _cached(p).get("findings") or []:
            if f.get("sev") == "bad":
                out.append({"project": p, "text": f["text"], "id": f.get("where", "")})
    return out
