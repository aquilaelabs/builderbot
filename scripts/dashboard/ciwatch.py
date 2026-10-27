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
reads, with one exception a person presses for (R117 step 4): a moving
label and an action a major behind each carry their fix, the one line
that changes, and fix() writes that line into the project's working tree,
uncommitted, for the Git view's Changes to show. It never commits and
never pushes: that stays somebody's, on their branch.
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
# What a kept look was made by. A look kept by older code is no look at all:
# after an update fixed how a stopped run was judged, the bell went on
# showing the old verdict for up to a day, since nothing was due again
# (3 Oct). Moved whenever what a look finds changes meaning.
FORMAT = 3
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
    """What the last look found, or {} before the first, or when it was
    made by a BuilderBot that judged differently (FORMAT)."""
    try:
        rec = json.loads(_file(project).read_text())
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) and rec.get("format") == FORMAT else {}


# ---- the tree ------------------------------------------------------------------

# The comment beside a commit pin says its version ("# v4, pinned by commit"):
# the v and the number, never the comma after them.
USES = re.compile(r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s]*)?@([^\s#]+)\s*(?:#\s*(v?\d[\w.]*))?")


# Where a tree keeps its workflows: GitHub's, then Gitea's and Forgejo's,
# which read the same YAML (a repository on the lab Gitea read as having
# none, B92). A file under .github is named by itself, as the page has
# always shown it; one under the others carries its directory, so two
# hosts' ci.yml are two findings.
WORKFLOW_DIRS = (".github/workflows", ".gitea/workflows", ".forgejo/workflows")


def _workflow_files(project):
    """[(where-name, path)] for every workflow file in the tree, in
    WORKFLOW_DIRS order."""
    out = []
    for d in WORKFLOW_DIRS:
        for f in sorted((WORKSPACE / project / d).glob("*.y*ml")):
            out.append((f.name if d == WORKFLOW_DIRS[0] else f"{d}/{f.name}", f))
    return out


def has_workflows(project):
    """Whether the tree has a workflow directory any host reads."""
    return any((WORKSPACE / project / d).is_dir() for d in WORKFLOW_DIRS)


def workflows(project):
    """[(file:line, kind, value)] for every runs-on and uses: in the tree's
    workflows, read as text: nothing in them is run. A commit pin's value
    carries its comment's version, and is not offered a fix (see look)."""
    out = []
    for name, f in _workflow_files(project):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r"\s*runs-on:\s*(.+?)\s*(#.*)?$", line)
            if m and "${{" not in m.group(1):
                out.append((f"{name}:{i}", "runs-on", m.group(1)))
            m = USES.match(line)
            if m:
                # A commit pin carries its version in the comment beside it.
                ref = m.group(2) if not re.fullmatch(r"[0-9a-f]{40}", m.group(2)) else (m.group(3) or "")
                out.append((f"{name}:{i}", "uses", f"{m.group(1)}@{ref}"))
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


# ---- a fix, pressed ----------------------------------------------------------------

WORKFLOW_FILE = re.compile(r"[A-Za-z0-9._-]+\.ya?ml")


def fix(project, where):
    """Write the fix the last look found at `where` (FILE:LINE) into the
    project's working tree: that one line, `from` replaced by `to`, and
    nothing else. Read from the kept look, never from the request, so a
    caller names a finding and cannot hand in text; refused when the line
    no longer says what the look saw (the tree moved since), which a Look
    now answers. {ok, file, line, from, to} or {error}."""
    rec = read(project)
    hit = next((f for f in rec.get("findings") or [] if f.get("where") == where and f.get("fix")), None)
    if not hit:
        return {"error": "no fix for that line in the last look: Look now looks again"}
    name, _, num = str(where).rpartition(":")
    folder, _, base = name.rpartition("/")
    folder = folder or WORKFLOW_DIRS[0]
    if folder not in WORKFLOW_DIRS or not WORKFLOW_FILE.fullmatch(base) or not num.isdigit():
        return {"error": f"not a workflow line: {where}"}
    path = WORKSPACE / project / folder / base
    try:
        lines = path.read_text().split("\n")
    except OSError as e:
        return {"error": f"cannot read {name}: {e.strerror or e}"}
    i = int(num) - 1
    old, new = hit["fix"]["from"], hit["fix"]["to"]
    if not 0 <= i < len(lines) or old not in lines[i]:
        return {"error": f"{name}:{num} no longer says {old}: Look now looks again"}
    lines[i] = lines[i].replace(old, new, 1)
    try:
        path.write_text("\n".join(lines))
    except OSError as e:
        return {"error": f"cannot write {name}: {e.strerror or e}"}
    return {"ok": True, "file": f"{folder}/{base}", "line": i + 1, "from": old, "to": new,
            "out": f"{name}:{num} now names {new}: commit it, or send it to Claude, from Changes"}


# ---- one look --------------------------------------------------------------------

NOTICE = re.compile(r"deprecat|will (?:be )?(?:migrat|remov|retir|stop)|no longer (?:be )?support|end of life",
                    re.I)


def look(project):
    """Look now, keep what was found, and return it."""
    found, run, err = [], {}, ""
    token = cilogs._token(project)
    flows = workflows(project)
    # Watching is nobody's work in the moment (R159): it takes the token
    # of anyone on the project signed in now, and pauses, said on the
    # project, while nobody who gave one is.
    import gitcreds                                         # noqa: PLC0415
    if not token and gitcreds.STATE and gitcreds.givers(project):
        err = "paused: nobody who gave this project a token is signed in; it looks again when one is"
    for where, kind, val in flows:
        # A moving label is GitHub's: a Gitea or Forgejo runner's labels are
        # its own config, which moves only when its admin moves it.
        if kind == "runs-on" and not where.startswith("."):
            for os_ in re.findall(r"\b(ubuntu|windows|macos)-latest\b", val):
                found.append({"kind": "label", "sev": "warn", "where": where,
                              "fix": {"from": f"{os_}-latest", "to": PINNED[os_]},
                              "text": f"Asks GitHub for {os_}-latest, which GitHub switches to a newer "
                                      f"{os_.capitalize() if os_ != 'macos' else 'macOS'} on its own schedule, so the "
                                      f"build can break with no change of yours. Naming {PINNED[os_]} "
                                      "instead keeps it where it is until you move it."})
        elif kind == "uses":
            action, _, ref = val.partition("@")
            have = _major(ref)
            new = _newest_major(action, token) if have is not None else None
            if have is not None and new is not None and new > have:
                # Offered as a fix only where the line names a tag (v3, v3.1):
                # a commit pin is somebody's deliberate choice, and its new
                # commit is not a thing to guess.
                pinned = not re.fullmatch(r"v?\d+(?:\.\d+)*", ref or "")
                found.append({"kind": "action", "sev": "note", "where": where,
                              **({} if pinned else {"fix": {"from": f"{action}@{ref}", "to": f"{action}@v{new}"}}),
                              "text": f"Uses {action} {ref}, and v{new} is out. Old versions stop working "
                                      "when GitHub retires what they run on, which is how a build that "
                                      "passed for months suddenly fails."})
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
            # ...and a check that passed since on a release (a tag's run of
            # the same workflow, the commit main was at) is passing again:
            # a workflow that runs on main only when its own files change
            # kept a failure from weeks before on the bell for good.
            passed = {}
            for r in runs:
                if r["status"] == "completed" and r["conclusion"] == "success" \
                        and (r["branch"] == main or r.get("event") == "release"):
                    passed[r["name"]] = max(passed.get(r["name"], ""), r["at"])
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
                if r["conclusion"] != "success" and passed.get(r["name"], "") <= r["at"]:
                    found.append({"kind": "run", "sev": "bad", "where": f"run {r['id']}",
                                  "text": f"The {r['name']} check {ended(r['conclusion'])} on {r['branch']}"
                                          f" ({_when(r['at'])}). A session can read why with "
                                          f"bb ci-log {r['id']}.",
                                  "url": r.get("url", "")})
            if newest:
                run = {k: newest[k] for k in ("id", "name", "branch", "conclusion", "at")}
                run["ended"] = ended(newest["conclusion"])
                found += _notices(repo, token, newest["id"])
        except cilogs.Refused as e:
            err = str(e)
    rec = {"format": FORMAT, "at": int(time.time()), "repo": repo, "workflows": len({w.split(':')[0] for w, _, _ in flows}),
           "run": run, "findings": found[:40], "error": err}
    if write_json:
        write_json(_file(project), rec)
    return rec


def ended(conclusion):
    """GitHub's conclusion as words: "failure" is "failed"."""
    return {"success": "passed", "failure": "failed", "timed_out": "timed out", "skipped": "was skipped",
            "action_required": "is waiting on an approval", "startup_failure": "failed to start"}.get(
        conclusion, "was stopped" if conclusion and conclusion.startswith("cancel") else conclusion or "ended")


def _when(at):
    """GitHub's 2026-10-03T00:44:51Z as 3 Oct, 00:44 UTC."""
    m = re.match(r"\d{4}-(\d\d)-(\d\d)T(\d\d:\d\d)", at or "")
    if not m:
        return "at an unknown time"
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{int(m.group(2))} {months[int(m.group(1)) - 1]}, {m.group(3)} UTC"


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
    if not has_workflows(project):
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
    """[{project, text, id, key}] for the projects whose main branch's
    newest run failed, for the bell: drawn while true, and put away by its
    key (the run) until another run fails (bellseen)."""
    out = []
    for p in projects:
        for f in _cached(p).get("findings") or []:
            if f.get("sev") == "bad":
                out.append({"kind": "ci", "project": p, "text": f["text"], "id": f.get("where", ""),
                            # One word: the page sends a row's keys joined by
                            # spaces, and "run N" was two (B331).
                            "url": f.get("url", ""), "key": f"ci:{p}@{''.join(str(f.get('where', '')).split())}"})
    return out
