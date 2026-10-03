"""A project's CI runs on the forge's own machines, read through the
controller's credential (R115).

A self-hosted job keeps its log where `bb ci-log` reads it; a job on
GitHub's runners keeps it on GitHub, and the API that hands it out wants a
token even for a public repository. A session holds no token, so it asked
the person to paste the failing part (Shebang-DevBoard, 2 Oct). The
controller does hold one: the project's own (gitcreds) or the shared PAT gh
answers with, and asks GitHub on the session's behalf. Read only: a run is
listed and a job's log is read, nothing is re-run or stopped.

GitHub only for now: a Gitea or GitLab project's runner is a node's, whose
log bb ci-log already reads.
"""
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE = Path("/config")
WORKSPACE = Path("/workspace")
push_record = None      # project -> {"repo", "host"} or None
read_config = None      # .git dir -> {key: [values]}
parse_url = None        # remote url -> {"host", "path"} or None

API = "https://api.github.com"
TAIL_LINES = 400        # of each failed job's log, the end, where the failure is
MAX_LOG = 2_000_000     # bytes read of one job's log


class Refused(Exception):
    """A request this module will not make, with the sentence to show."""


def configure(*, state, workspace, push_record_fn=None, config_fn=None, parse_fn=None):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), push_record=push_record_fn,
                     read_config=config_fn, parse_url=parse_fn)


def repo_of(project):
    """owner/name on github.com, from the granted push rights or the tree's
    origin, or "" when the project is not on github.com."""
    rec = push_record(project) if push_record else None
    if isinstance(rec, dict) and rec.get("repo"):
        return rec["repo"] if str(rec.get("host") or "").lower() == "github.com" else ""
    try:
        cfg = read_config(WORKSPACE / project / ".git") if read_config else {}
    except Exception:  # noqa: BLE001 (an unreadable config is no remote)
        cfg = {}
    url = ((cfg.get("remote.origin.url") or [""])[-1]) if isinstance(cfg, dict) else ""
    got = parse_url(url) if (parse_url and url) else None
    if got and str(got.get("host") or "").lower() == "github.com" and got.get("path"):
        return got["path"].removesuffix(".git")
    return ""


def _token(project):
    """The project's own token, else the shared PAT; "" when neither."""
    try:
        line = (STATE / "gitcreds" / project).read_text().strip().splitlines()[0]
        m = re.match(r"https?://[^:@/]*:([^@/]+)@github\.com$", line)
        if m:
            return urllib.parse.unquote(m.group(1))
    except (OSError, IndexError):
        pass
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _get(path, token, raw=False):
    # A run's, a job's annotations, and a repository's newest release (the
    # watcher's, ciwatch.py): nothing else is asked of GitHub with the token.
    if not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:actions/[A-Za-z0-9_/?=&.-]+"
                        r"|check-runs/\d+/annotations|releases/latest)", path):
        raise Refused("not a path this asks GitHub for")
    req = urllib.request.Request(API + path, headers={"User-Agent": "BuilderBot",
                                                      "Accept": "application/vnd.github+json"})
    # Unredirected: a job's log answers with a redirect to a storage host,
    # which must not be handed the token.
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        # The host is the literal API above and the path is checked against a pattern.
        with urllib.request.urlopen(req, timeout=60) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            body = r.read(MAX_LOG if raw else 4_000_000)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Refused("GitHub refused the controller's token for this repository's Actions: "
                          "it needs read access to actions (a fine-grained token's Actions: read)") from e
        if e.code == 404:
            raise Refused("GitHub has no such run, or the token cannot see this repository") from e
        if e.code == 410:
            raise Refused("GitHub no longer keeps that log: run logs expire after their retention days") from e
        raise Refused(f"GitHub answered {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise Refused(f"could not reach GitHub: {e}") from e
    return body.decode("utf-8", "replace") if raw else json.loads(body or b"{}")


def _setup(project):
    repo = repo_of(project)
    if not repo:
        raise Refused(f"{project} is not on github.com, so there is no hosted run to read")
    token = _token(project)
    if not token:
        raise Refused("the controller has no GitHub token for this project: give it one under the "
                      "project's settings (Git), or sign gh in on the controller")
    return repo, token


def runs(project, n=10):
    """The newest runs: {repo, runs: [{id, name, branch, event, status, conclusion, at, sha}]}."""
    repo, token = _setup(project)
    j = _get(f"/repos/{repo}/actions/runs?per_page={max(1, min(int(n), 30))}", token)
    out = []
    for r in (j.get("workflow_runs") or [])[:30]:
        out.append({"id": int(r.get("id") or 0), "attempt": int(r.get("run_attempt") or 1),
                    "name": str(r.get("name") or "")[:80], "branch": str(r.get("head_branch") or "")[:80],
                    "event": str(r.get("event") or "")[:30], "status": str(r.get("status") or "")[:20],
                    "conclusion": str(r.get("conclusion") or "")[:20], "at": str(r.get("created_at") or "")[:20],
                    "sha": str(r.get("head_sha") or "")[:12]})
    return {"repo": repo, "runs": out}


def _strip_stamp(line):
    # Every line of a job's log starts with an ISO time; the step names and
    # what the commands said are what a reader wants.
    return re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ", "", line)


def log(project, run=0):
    """One run's jobs, and the end of each failed job's log (all of them
    when none failed): {repo, run: {...}, jobs: [{name, conclusion, failed_step, log}]}.
    run 0 is the newest run that has finished."""
    repo, token = _setup(project)
    if not run:
        done = [r for r in runs(project, 15)["runs"] if r["status"] == "completed"]
        if not done:
            raise Refused("no finished run on GitHub yet")
        run = done[0]["id"]
    run = int(run)
    meta = _get(f"/repos/{repo}/actions/runs/{run}", token)
    jobs = (_get(f"/repos/{repo}/actions/runs/{run}/jobs?per_page=50", token).get("jobs") or [])[:50]
    # Failed is any finished end but a pass or a skip: a failure, a timeout,
    # or a job stopped part way, whose log says how far it got.
    failed = [j for j in jobs if j.get("conclusion") and j.get("conclusion") not in ("success", "skipped", "neutral")]
    out = []
    for j in jobs:
        step = next((s.get("name") for s in (j.get("steps") or [])
                     if s.get("conclusion") in ("failure", "timed_out")), "")
        row = {"id": int(j.get("id") or 0), "name": str(j.get("name") or "")[:120],
               "conclusion": str(j.get("conclusion") or j.get("status") or "")[:20], "failed_step": str(step)[:120]}
        if j in failed or not failed:
            text = _get(f"/repos/{repo}/actions/jobs/{row['id']}/logs", token, raw=True)
            lines = [_strip_stamp(x) for x in text.splitlines()]
            row["lines"] = len(lines)
            row["log"] = "\n".join(lines[-TAIL_LINES:])
        out.append(row)
    return {"repo": repo, "run": {"id": run, "name": str(meta.get("name") or "")[:80],
                                  "branch": str(meta.get("head_branch") or "")[:80],
                                  "conclusion": str(meta.get("conclusion") or meta.get("status") or "")[:20],
                                  "at": str(meta.get("created_at") or "")[:20],
                                  "url": str(meta.get("html_url") or "")[:200]},
            "jobs": out}
