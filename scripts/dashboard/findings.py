#!/usr/bin/env python3
"""What the scanner used to say, so a finding that goes away leaves a trace.

The other three notebook views keep a log because somebody *did* something:
a step reworded, a bug closed, a memory written. Nothing here is written by
anyone: the scan runs on the host, the container gets a read-only report, and
between two runs a finding can simply stop being in it. Fixed, or the file
went, or a rule changed on the host, or the scanner never reached that
project: the report cannot tell those apart and neither can this. What it can
say is *it was here on the 3rd and it is not here now*, which is the question
worth answering and had no answer at all before.

So this log is derived rather than recorded: each read of the report is
compared against the last one, and the difference is the entry.

**What counts as the same finding.** (rule, path) within a project,
deliberately not the line. Line numbers move whenever anything is inserted
above them, so a key including the line turns one edit into a gone-and-found
pair for every finding below it, and a log full of that is a log nobody reads.
The cost is that three hits of one rule in one file are one row here; when
that count changes the entry says so rather than pretending something new
appeared.

**The first read of a project seeds silently.** Logging everything as "found"
on the day this was added would stamp a discovery date on findings older than
the feature, and a confidently wrong date is worse than none.

**An empty report is not the same as a clean one.** If a project is absent
from the scan entirely (the scanner failed, or never covered it), every
finding it had would read as fixed. That is exactly the SARIF trap the rest of
this project is careful about, so `seen()` is told whether the project was
actually covered, and a project that was not covered is left alone.
"""
import json
import os
import posixpath
import re
import sys

# `bb` execs this module by path, so its directory is not on sys.path the way
# it is when the dashboard imports it. One module object per process either
# way: the in-process half of the lock is a dict in there.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import time
from pathlib import Path

write_json = None
STATE = None
FILE = None
WORKSPACE = Path("/workspace")

def configure(*, write_json, state, workspace=None):
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "findings-log.json"
    if workspace is not None:
        globals()["WORKSPACE"] = Path(workspace)


# The same lock the roadmap and the tracker take, and for the same reason: the
# dashboard is one process and a `bb` invocation is another, and a threading
# lock guards the threads of one. Both would load, both mutate their own copy,
# both write, and os.replace makes each write atomic while doing nothing about
# the second landing on top of the first. See statefile.py.
_lock = statefile.on(lambda: FILE)

# Room for a working record, the same as the roadmap's and the tracker's. A
# weekly scan over a handful of projects will not reach this; a rule that
# flickers on and off would, and the cap is what stops it pushing everything
# else out of the file.
MAX_HISTORY = 300


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def save(d):
    write_json(FILE, d)


def _key(row):
    """(rule, path). See the module docstring for why the line is left out."""
    return "\t".join([str(row.get("rule") or ""), str(row.get("path") or "")])


def _digest(rows):
    """The current report for one project, as {key: {what the log needs}}."""
    out = {}
    for r in rows:
        k = _key(r)
        cur = out.get(k)
        if cur is None:
            out[k] = {"rule": r.get("rule") or "", "path": r.get("path") or "",
                      "level": r.get("level") or "warning",
                      "desc": (r.get("desc") or "")[:200], "n": 1}
        else:
            cur["n"] += 1
            # The worst level a file has for this rule is the one worth
            # keeping: a note beside an error should not read as a note.
            if _RANK.get(r.get("level"), 1) > _RANK.get(cur["level"], 1):
                cur["level"] = r.get("level") or cur["level"]
    return out


_RANK = {"note": 0, "warning": 1, "error": 2}


def seen(project, rows, covered=True):
    """Compare this read against the last, and log what changed.

    `covered` is whether the scan actually looked at this project. A report
    that simply does not mention it says nothing about its findings, and
    treating that as "everything was fixed" is the exact SARIF mistake this
    project refuses to make elsewhere, so it returns without touching
    anything.

    Returns the number of entries written, which is zero on the overwhelming
    majority of calls: this runs on every read of the report, and the report
    changes weekly.
    """
    if not covered:
        return 0
    now = _digest(rows)
    with _lock:
        d = load()
        p = d["projects"].setdefault(project, {})
        was = p.get("seen")
        if was is None:
            # First sight of this project: take the snapshot, write no
            # history. See the module docstring.
            p["seen"] = now
            save(d)
            return 0
        events = []
        at = int(time.time())
        for k, cur in now.items():
            old = was.get(k)
            if old is None:
                events.append({"at": at, "act": "found", **_row(cur)})
            elif old.get("n") != cur.get("n") or old.get("level") != cur.get("level"):
                events.append({"at": at, "act": "changed", **_row(cur),
                               "was": f"{old.get('n', 1)} x {old.get('level', '?')}"})
        for k, old in was.items():
            if k not in now:
                events.append({"at": at, "act": "gone", **_row(old)})
        if not events:
            return 0
        h = d.setdefault("history", {}).setdefault(project, [])
        h.extend(events)
        del h[:-MAX_HISTORY]
        p["seen"] = now
        save(d)
    return len(events)


def _row(v):
    return {"rule": v.get("rule", ""), "path": v.get("path", ""),
            "level": v.get("level", "warning"), "desc": v.get("desc", ""),
            "n": v.get("n", 1)}


def history(project, limit=None, since=None, find=None):
    """What the scanner has stopped and started saying here, newest first.

    The same three filters the roadmap's and the tracker's logs take, narrowed
    here rather than by the caller for the same reason: the reader that matters
    most is a session, and a log dumped whole costs more context than the one
    line wanted from it.
    """
    with _lock:
        h = load().get("history", {}).get(project) or []
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        # An absolute epoch, the same as the roadmap's and the tracker's take.
        # Both callers already compute it (the CLI from a day count or a
        # date, the panel from its dropdown), and having one of the four logs
        # mean something different by the same argument is a trap.
        cut = _int(since)
        if cut is not None:
            out = [e for e in out if e.get("at", 0) >= cut]
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if needle in " ".join([str(e.get("rule", "")), str(e.get("path", "")),
                                      str(e.get("desc", "")), str(e.get("act", "")),
                                      str(e.get("level", ""))]).lower()]
    n = _int(limit)
    out = out if n in (None, 0) else out[:n]
    # Shaped like the other three logs (at / act / text / note / by), so the
    # same pane renders it and the same eye reads it. `by` is empty on
    # purpose: nobody here did this, which is the one honest thing to say
    # about a finding that stopped being reported.
    return [{"at": e.get("at", 0), "act": e.get("act", "changed"),
             "text": e.get("path") or "(no path)",
             "by": "",
             "note": " · ".join(x for x in [
                 e.get("level", ""),
                 e.get("rule", ""),
                 f"x{e['n']}" if e.get("n", 1) > 1 else "",
                 f"was {e['was']}" if e.get("was") else "",
             ] if x)}
            for e in out]


def revisions():
    """{project: how many things have happened to its findings}.

    The poll's cheap way to notice the log moved, the same shape the tracker
    uses: one read of the file for every project rather than one each.
    """
    with _lock:
        h = load().get("history", {})
    return {p: len(rows) for p, rows in h.items()}


def _int(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---- the reports themselves ---------------------------------------------
# What the scanner on the host left under /reports: SARIF read into flat
# findings, each attributed to the project its path names, the reports a
# whole cycle behind their siblings left out, and the counts the status
# poll carries. Here rather than in server.py, beside the
# history those reads feed (R60): the server hands in the project list it
# already holds, and nothing in here knows who is asking.
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}")
REPORTS = Path(os.environ.get("FINDINGS_DIR", "/reports"))
# The reports the nodes' own scanners sent up (R145, scanners.report_files),
# set by the server: read beside the host folder, which is deprecated.
STATE_REPORTS = None


def _project_of(uri, known, nonproject=frozenset()):
    """Which mounted project a scanner-recorded path belongs to.

    The scanner records where *it* saw the code, which is never where this
    container mounts it, so the only reliable anchor is a path component that
    matches a directory in the workspace.

    A component that matches a directory in the share that is NOT a project
    (the toolchain store, the runner's tree, anything else living in there)
    attributes to IGNORED rather than to nothing. The host scanner sweeps the
    whole share, so the flutter checkout alone lands thousands of findings,
    and filing those as "unattributed" buried the handful of genuinely
    unplaceable paths under them: 9,000 rows of vendored toolchain wearing the
    label that was meant to say "look at this one, its path is wrong".

    `nonproject` is everything in the share minus the projects, so this needs
    no list of what to skip and nothing has to be excluded on the scanner.
    """
    parts = [p for p in uri.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        if part in known:
            return part, "/".join(parts[i + 1:]) or part
        if part in nonproject:
            return IGNORED, "/".join(parts[i:])
    return None, "/".join(parts)


# The sentinel a finding attributes to when its path resolves into a directory
# the dashboard knows and deliberately does not treat as a project. Impossible
# as a real project name (a slash never survives a directory name).
IGNORED = "not/a/project"


def share_siblings():
    """Shares mounted beside the projects folder, by the name the host calls them.

    The subtraction below derives "not a project" from what sits INSIDE
    /workspace, which worked while /workspace was the whole development share:
    the toolchain store was a directory in it, so it fell out for free. Pointing
    /workspace at the projects folder (a better arrangement, and the one that
    cut most of this noise) took the toolchain store outside it, and 267 findings
    about downloaded Flutter, Go and Android toolchains went straight to
    "unattributed", which is the label meant for a path that is genuinely
    wrong. Improving the layout regressed the classifier.

    So the wider question is asked instead: what does this container mount from
    beside its own projects folder? /proc/self/mountinfo answers it:

        /development/projects -> /workspace
        /development/SDK      -> /sdk

    So `SDK` is a sibling of the projects folder, and a scanner sweeping the
    share reports its paths as SDK/flutter/... . Derived, so it keeps working
    wherever the shares are moved to next, and no list of what to skip.

    Two things it deliberately will not do. A mount whose source is a whole
    filesystem (root "/") says nothing about a directory name and is skipped.
    And a name that IS a valid project never enters the set, whatever it is
    mounted from: /mnt/user/appdata/BuilderBot would otherwise teach this to
    ignore the BuilderBot project's own findings, which is the one mistake
    here that would hide real work rather than noise.
    """
    try:
        with open("/proc/self/mountinfo") as f:
            return siblings_of(f.read(), str(WORKSPACE))
    except OSError:
        return set()


def siblings_of(mountinfo, workspace):
    """The parsing half of share_siblings, given the file's text.

    Split out to be driven with a real mount table rather than this one: the
    case that must not regress (a mount whose basename happens to be a
    project's name) cannot be produced by mounting something here."""
    src = {}
    for line in mountinfo.splitlines():
        bits = line.split()
        if len(bits) > 4:
            src[bits[4]] = bits[3]              # mount point -> path in source fs
    ws = src.get(workspace)
    if not ws or ws == "/":
        return set()
    parent = posixpath.dirname(ws)
    out = set()
    for point, path in src.items():
        if point == workspace or path == "/":
            continue
        if posixpath.dirname(path) == parent:
            name = posixpath.basename(path)
            if name:
                out.add(name)
    return out


def nonproject_dirs(valid):
    """Top-level workspace directories that are not projects.

    Derived by subtraction rather than by recognizing each kind: everything in
    the share that is not a project worth reading findings for is one of these.
    That set is the one the card already computes (listed, not excluded, no
    error-level issue), so asking for it and taking the remainder needs no
    maintenance when a new sort of directory turns up in the share.

    Subtracting the *valid* projects rather than merely the listed ones is what
    makes it cover the case that started this. A share mapped inside the
    projects folder with nothing to mark it is still a directory, so the card
    lists it, as a project with an error, because it is not a repository. Take
    away only the listed names and its thousands of findings stay in play; take
    away the valid ones and it falls out with the rest.

    That width is the point. The toolchain store is the case that made it matter: on
    this box it lives *inside* the development share, so the host's scanner
    walks it like anything else and a report grew nine thousand findings
    attributed to a "project" that is a pile of downloaded toolchains. Those
    now attribute to IGNORED and are counted aside, rather than burying the
    handful of genuinely unplaceable paths that the "unattributed" label is
    for. Nothing had to be excluded on the scanner to get there.

    Listed fresh per parse; it is one readdir and one small file."""
    out = set()
    try:
        for d in WORKSPACE.iterdir():
            if d.is_dir() and d.name not in valid:
                out.add(d.name)
    except OSError:
        pass
    # ...plus the shares mounted beside the projects folder, which the
    # subtraction above cannot see now that it is not the whole share.
    out |= share_siblings()
    out -= set(valid)               # never a project, whatever it is mounted from
    return out


def _parse_run(runinfo, known, nonproject=frozenset()):
    """One SARIF run -> (tool name, rows)."""
    driver = (runinfo.get("tool") or {}).get("driver") or {}
    rules = {}
    for r in driver.get("rules") or []:
        rules[r.get("id")] = {
            "desc": ((r.get("shortDescription") or {}).get("text")
                     or (r.get("fullDescription") or {}).get("text") or ""),
            "help": ((r.get("help") or {}).get("text") or ""),
            "uri": r.get("helpUri") or "",
            "level": ((r.get("defaultConfiguration") or {}).get("level") or "warning"),
        }
    rows = []
    for res in runinfo.get("results") or []:
        # A finding the code itself suppressed (Semgrep's `# nosemgrep:`, a
        # SARIF in-source suppression) stays in the report with a
        # `suppressions` entry rather than leaving it, and was counted as if
        # nothing had been said: every line annotated on 2 Oct still showed.
        # Accepted unless the suppression itself says it was rejected.
        if any(isinstance(s, dict) and s.get("status", "accepted") != "rejected"
               for s in res.get("suppressions") or []):
            continue
        rid = res.get("ruleId") or "unknown"
        meta = rules.get(rid, {})
        msg = ((res.get("message") or {}).get("text") or "")
        loc = ((res.get("locations") or [{}])[0].get("physicalLocation") or {})
        uri = ((loc.get("artifactLocation") or {}).get("uri") or "?")
        line = ((loc.get("region") or {}).get("startLine") or 0)
        proj, rel = _project_of(uri, known, nonproject)
        # CVEs turn up in the rule id (Trivy) or the prose (most others).
        cves = sorted(set(CVE_RE.findall(" ".join([rid, msg, meta.get("desc", ""),
                                                   meta.get("help", "")]))))
        rows.append({
            "rule": rid,
            "level": res.get("level") or meta.get("level") or "warning",
            "desc": meta.get("desc") or msg.split("\n")[0],
            "message": msg.strip(),
            "uri": meta.get("uri", ""),
            "project": proj,
            "path": rel,
            "line": line,
            "cves": cves,
        })
    return driver.get("name") or "", rows


def parse_sarif(path, known, nonproject=frozenset()):
    """SARIF 2.1.0 -> flat findings. Tolerant: a malformed run is skipped, not
    fatal, because one bad report should not blank the whole page."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return {"file": path.name, "tool": "?", "error": str(e), "findings": []}

    tools, rows = [], []
    for runinfo in doc.get("runs") or []:
        # "Tolerant" has to mean it: SARIF in the wild has arrays where objects
        # belong, and one such run used to take the whole endpoint down with an
        # AttributeError rather than being skipped as documented.
        try:
            name, got = _parse_run(runinfo, known, nonproject)
        except (AttributeError, TypeError, IndexError, KeyError):
            continue
        if name and name not in tools:
            tools.append(name)
        rows.extend(got)
    # A file can hold runs from several tools; naming it after the last one seen
    # was arbitrary.
    return {"file": path.name, "tool": " + ".join(tools) or "?", "findings": rows}


def _valid_projects(ps):
    """The projects whose findings are worth surfacing: no error-level issue.

    A repo that is broken gets triaged in the Projects card first: its
    findings would only pad the numbers for code nobody can currently work on.
    A LOCKED one is not in that category and never was: locking says who runs
    it, not whether its code is worth reading about, and the operator asked
    for the analysis to keep working on a locked project."""
    return {p["name"] for p in ps
            if not any(i["level"] == "error" for i in p["issues"])}


def _sent_up():
    """The reports the nodes' scanners sent up (R145), or []."""
    try:
        return list(STATE_REPORTS()) if STATE_REPORTS else []
    except OSError:
        return []


def mounted():
    """Whether there is a reports directory, False for one that cannot even
    be looked at: pathlib's is_dir() raises for a mount gone stale under the
    container (NFS errno 116) rather than answering, and the status poll
    asks this every time (B326). A report a node's scanner sent up counts
    the same way (R145)."""
    if _sent_up():
        return True
    try:
        return REPORTS.is_dir()
    except OSError:
        return False


def report_files():
    """Every report: the ones the nodes' scanners sent up (R145), then those
    under REPORTS, the .sarif then the .sarif.json, each sorted; None when
    there is neither. A stale mount is one of those: counts() runs on every
    /api/status, and one unreadable directory answered the whole poll with
    an error and held every page on loading (B326)."""
    sent = _sent_up()
    if not mounted():
        return None
    try:
        host = (sorted(REPORTS.glob("*.sarif")) + sorted(REPORTS.glob("*.sarif.json"))) if REPORTS.is_dir() else []
    except OSError:
        # A mount that cannot be listed (stale) is nothing to read, unless
        # the nodes sent reports of their own.
        return sent or None
    return sent + host


def payload(ps):
    known = {p["name"] for p in ps}
    files = report_files()
    if files is None:
        return {"available": False, "reports": [], "projects": sorted(known)}
    # The same rule the counts apply: a report a whole cycle behind its
    # siblings is not read. Its scanner has probably died and left its last
    # good output in place, and this payload feeding the Analysis tab while
    # the counts refused the same file meant the tab could show findings the
    # rest of the page said did not exist: a stale COPY of a live report
    # doubled every rule it contained.
    dropped = stale_reports()
    files = [f for f in files if f.name not in dropped]
    # Only the projects worth reading findings for get attributed to: listed,
    # no error-level issue. Everything else under the share
    # (a project shut out, one that is broken, the toolchain store, a directory
    # nobody has explained) attributes to IGNORED and is counted aside.
    #
    # Counted rather than silently dropped: a report that quietly shrinks
    # reads as "covered everything" when it did not.
    valid = _valid_projects(ps)
    nonproject = nonproject_dirs(valid)
    reports, aside = [], 0
    for f in files:
        rep = parse_sarif(f, valid, nonproject)
        keep = []
        for r in rep["findings"]:
            if r["project"] == IGNORED:
                aside += 1
            else:
                keep.append(r)
        rep["findings"] = keep
        reports.append(rep)
    # One number, not one per reason. Two were never shown anywhere, and the
    # distinction they would draw (shut out on purpose vs. not a project) is
    # not one this code can make with attribution being "valid projects
    # only": a broken project and a vendored toolchain leave by the same
    # door, which is the point.
    return {"available": True, "projects": sorted(known),
            "aside": aside, "reports": reports}


# How far behind the newest report a report may be and still be believed.
#
# A scanner that dies leaves its PREVIOUS report in place (a host script worth
# having does not overwrite a good report with nothing), so a dead scanner and
# a live one are the same file to everything downstream. On 28 Aug a trivy that
# had been crashing for four days was still supplying most of this box's
# findings, against a directory layout that had been changed in between: the
# operator fixed the scanner's volume, the numbers did not move, and the fix
# looked broken.
#
# A day, and the size is the argument. One scan run writes every report within
# minutes of itself, so anything measured in hours is the same run. Re-running
# ONE scanner by hand (the obvious thing to do after fixing one) leaves its
# siblings a few hours behind, and they must not vanish for it. A report left
# behind by a scanner that failed is behind by a whole cycle, which for any
# cadence anybody runs is more than this.
STALE_AFTER = 86400


def reports_ages():
    """Each report, when it was written, and whether it is too far behind."""
    out = []
    try:
        files = _sent_up() + ((sorted(REPORTS.glob("*.sarif")) + sorted(REPORTS.glob("*.sarif.json"))) if REPORTS.is_dir() else [])
        for f in files:
            try:
                out.append({"name": f.name if f.parent == REPORTS else f"{f.parent.name}/{f.name}", "when": int(f.stat().st_mtime)})
            except OSError:
                pass
    except OSError:
        return []
    out.sort(key=lambda r: -r["when"])
    newest = out[0]["when"] if out else 0
    for r in out:
        r["behind"] = newest - r["when"]
        r["stale"] = r["behind"] >= STALE_AFTER
    return out


def stale_reports():
    """The names of the reports being left out, as a set."""
    return {r["name"] for r in reports_ages() if r["stale"]}


def reports_mtime():
    """Newest mtime among the scanner reports, so a client showing the
    findings tab can notice a re-run scan without anyone pressing reload."""
    try:
        files = _sent_up() + ((list(REPORTS.glob("*.sarif")) + list(REPORTS.glob("*.sarif.json"))) if REPORTS.is_dir() else [])
        return max((int(f.stat().st_mtime) for f in files), default=0)
    except OSError:
        return 0


# Per-project headline numbers, without every client fetching and parsing
# the full reports: the totals ride the status poll, cached on report mtime, because the SARIF can run to megabytes and the poll
# arrives every 15 seconds.
_counts = {"mtime": -1, "projects": {}, "heads": [], "ok": False}


def counts(ps):
    """{project: {level: count}} across every report, valid projects only:
    same rule as payload(). An unattributed path (the scanner saw a
    directory this workspace does not mount) counts under "", which the
    client labels rather than hiding: a finding with a bad path is still a
    finding. The cache holds the unfiltered counts: validity can change
    (a project locked, a permission fixed) without any report changing,
    so the filter runs per call and only the parse is cached."""
    # Keyed on the valid project names too: attribution matches path components
    # against them, so a project that appears (or stops being valid) between
    # scans would otherwise keep being counted the old way here while the
    # notebook's view, which parses fresh, files it correctly.
    known = {p["name"] for p in ps}
    valid = _valid_projects(ps)
    files = report_files() or []
    # A report a whole cycle behind its siblings is not read. Its scanner
    # failed and the host left the previous file in place, so what it contains
    # describes a tree that has since moved: counting it does not make the
    # picture more complete, it makes it wrong, and quietly. Said on the card
    # rather than merely done: see reports_ages.
    dropped = stale_reports()
    files = [f for f in files if f.name not in dropped]
    # Nanosecond mtime plus size, per file: a report parsed mid-write and
    # finished within the same second must not stay cached as "no findings"
    # until the next scan.
    try:
        stamp = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    except OSError:
        stamp = ()
    nonproject = nonproject_dirs(valid)
    key = (stamp, tuple(sorted(valid)), tuple(sorted(nonproject)),
           tuple(sorted(dropped)))
    if _counts["mtime"] != key:
        per, rows_by, broken, good = {}, {}, False, 0
        # Where the unplaceable ones came from, counted by the head of their
        # path. A bare number on that row says something is wrong and nothing
        # about what: the honest answer for the nine left here is "mobsfscan
        # reports file:/src, its own container path", which is a fact about a
        # scanner's configuration and not about any project. Two components,
        # because one is usually a scheme and three is usually a filename.
        heads = {}
        for f in files:
            rep = parse_sarif(f, valid, nonproject)
            broken = broken or bool(rep.get("error"))
            good += 0 if rep.get("error") else 1
            for row in rep["findings"]:
                if row["project"] == IGNORED:
                    continue        # the toolchain store et al: see _project_of
                lv = per.setdefault(row["project"] or "", {})
                lv[row["level"]] = lv.get(row["level"], 0) + 1
                rows_by.setdefault(row["project"] or "", []).append(row)
                if not row["project"]:
                    bits = [b for b in (row.get("path") or "").split("/") if b][:2]
                    head = "/".join(bits) or "(no path)"
                    heads[head] = heads.get(head, 0) + 1
        _counts["heads"] = sorted(
            ({"head": k, "n": v} for k, v in heads.items()),
            key=lambda h: -h["n"])[:4]
        # Whether anything here is readable at all, counted while the parse is
        # in hand rather than paid for again: the Analysis surfaces ghost on
        # this, and re-reading every report to answer "is there a report" would
        # be the expensive half of the poll run for a disabled button. A report
        # that parses and holds no findings is readable: a clean scan is a
        # result, not an absence.
        _counts["ok"] = good > 0
        # A report that failed to parse is not cached: half-written is the
        # usual reason, and the next poll should read it whole.
        _counts.update(mtime=None if broken else key, projects=per)
        # The findings log, written here because here is where the report is
        # known to have *changed*: this block runs on a new mtime and not on
        # the reads in between.
        #
        # Not on a broken or missing report, which is the whole point of the
        # guard: a half-written file, or a reports directory that is not there
        # this minute, has nothing to say about what was fixed, and logging
        # every finding as gone off one would be the SARIF mistake this
        # project is careful about everywhere else.
        #
        # Coverage is assumed for every known project when a report does parse,
        # and that assumption is specific to this setup rather than general:
        # the scanners are pointed at the whole development share, so a project
        # in it was in scope of the run whether or not it produced a row. Point
        # them at one project and this would need to learn better.
        if files and not broken:
            for name in known:
                seen(name, rows_by.get(name, []), covered=True)
    # No filter on the way out any more: nothing but a valid project (or the
    # empty key, which is an unattributed path) can be in there at all, and
    # the cache is keyed on the valid set so a change to it re-parses.
    return dict(_counts["projects"])


def reports_ok():
    """Whether the Analysis surfaces have anything they can actually read.

    Three ways to have nothing: no /reports mount, nothing in it, or nothing in
    it that parses, and a control that is off wants one answer, not three. Read
    after counts(), which is what fills it.
    """
    return bool(mounted() and _counts["ok"])


def heads():
    """Where the unplaceable findings came from, commonest first.

    Read after counts(), which is what fills it: the parse is cached and
    doing it twice to answer a subtitle would be the expensive half of the poll
    run for a line of text."""
    return list(_counts["heads"])


def view(ps, session=""):
    """payload() for the projects `ps` this account sees, and for a SESSION
    only its own project's findings.

    Scoped by the projects the server hands over, which for a session's
    token is the one project it was minted for: a finding in anybody else's
    code attributes to IGNORED and never reaches the payload. The count of
    what was attributed away does not go either. For the operator it means
    "the toolchain store and the vendored trees"; for a session it would be
    every other project on the share, and a number that moves when somebody
    else's code changes is a fact about their code.
    """
    r = payload(ps)
    if session:
        r.pop("aside", None)
        # Positively its own, rather than "not obviously somebody else's".
        # Attribution is by path component, so a report whose URIs are
        # relative to a project root places NOTHING and every row would
        # arrive here as unattributed: allowing those through would hand a
        # session the whole box the first time a scanner is configured
        # that way. A finding it cannot be told is in its own project is
        # one it does not get.
        for rep in r.get("reports") or []:
            rep["findings"] = [f for f in rep["findings"] if f.get("project") == session]
    return r
