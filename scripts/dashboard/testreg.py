#!/usr/bin/env python3
"""The notebook's test registry: what each test protects, and what it costs.

Two records that only mean something together.

THE REGISTRY is written by hand, the way the roadmap and the tracker are: a
line per test saying what behavior it protects and what it actually exercises
— which fixtures, which stubs, what is real and what is faked. That last half
is the part nobody can recover from the code in a hurry, and it is what
decides whether a red run is a bug or a fixture. The deal is the same as the
roadmap's: when you write or change a test, record it in the same change.

THE TIMING is not written by hand at all. It is parsed out of what the runner
printed, because a self-reported estimate is a guess that ages, and the whole
reason to keep this is to answer "what is the suite actually spending its time
on" with a number somebody measured. A short history per test rather than only
the last run, so a test that got slow is tellable from one that always was.

WHAT A TEST IS CALLED HERE. Not its prose. The names in this suite are
sentences and the continuations begin with "..." — they are written to be read
in order, and they get reworded. So a test is keyed on where the RUNNER puts
it, `<file>#<ordinal>`, and the prose is a field. Renaming a test therefore
keeps its registry entry, which is the point.

Ordinals move when a test is inserted above one, so ingest does not trust them
blindly: it aligns the roster it just read against the roster it had, longest
common subsequence on the names first and then position for whatever is left
over. A rename in place matches by position; an insertion matches by name; the
entries follow their tests either way. What genuinely arrived or genuinely
went is what is left, and that is the drift report — which is the failure mode
this whole file exists to catch, because a registry that has quietly stopped
describing the code is worse than no registry.

Same arrangement as todo.py and bugs.py: the server or the `bb` CLI hands over
write_json and the state directory; nothing here reaches back.
"""
import json
import os
import re
import sys

# `bb` execs this module by path, so its directory is not on sys.path the way
# it is for the dashboard's own import. Same reasoning as bugs.py: one module
# object per process, because statefile's in-process half is a dict in there.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import time
from pathlib import Path

write_json = None
STATE = None
FILE = None

# How many durations to keep per test. Short on purpose: this is read to see
# whether something got slower, not to plot it, and every one of these is paid
# for in the file every session's `bb tests` reads.
KEEP = 5

# ...and how many run summaries. Enough to say "the suite was 11 minutes last
# week and is 4 now", which is the only question the header asks of them.
KEEP_RUNS = 20

MAX_TEXT = 2000
MAX_TESTS = 4000        # a roster this size is a runner that has run away


def configure(*, write_json, state):
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "tests.json"


_lock = statefile.on(lambda: FILE)


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


def _project(d, project):
    return d.setdefault("projects", {}).setdefault(
        project, {"tests": {}, "runs": []})


# ---- reading what the runner printed ---------------------------------------
# The dashboard's own runner, which is a shell script and 24 node files rather
# than a framework: it prints a banner per file, one line per result, and a
# total per file. With BB_TEST_TIMING=1 each result carries the seconds since
# the previous one, which is that test's duration — the harness measures it
# that way because there is nothing else between two results.
#
# SKIP and TODO are parsed although this suite emits neither today. They cost
# wall time wherever they exist and the registry has to be able to say so; a
# parser that only knows the two statuses one runner happens to print is a
# parser that has to be rewritten the day a test is skipped.
BANNER = re.compile(r"^\[dashboard-test\] == (\S+) ==\s*$")
RESULT = re.compile(r"^(PASS|FAIL|SKIP|TODO)\s+(?:\[\+([0-9.]+)s\]\s+)?(.+?)\s*$")
FILETOT = re.compile(r"^(\d+) passed, (\d+) failed(?: in ([0-9.]+)s)?\s*$")
STATUS = {"PASS": "pass", "FAIL": "fail", "SKIP": "skip", "TODO": "todo"}


def parse(text):
    """The runner's output as a roster: [{suite, ord, name, status, ms}].

    Tolerant of a line it does not know, because this is fed whole run logs —
    a `bb` error, a stray warning and a python traceback all appear in one,
    and none of them is a result.
    """
    out, suites, suite, n = [], {}, "", 0
    for raw in text.splitlines():
        # A timestamped log (the shape `bb tests ingest` is usually handed)
        # carries an epoch in front. Stripped here rather than asked for, so
        # the same command takes a log either way.
        line = re.sub(r"^\d{9,}\.\d+ ", "", raw)
        m = BANNER.match(line)
        if m:
            suite, n = m.group(1), 0
            suites.setdefault(suite, {"wall": None, "passed": None, "failed": None})
            continue
        m = FILETOT.match(line)
        if m and suite:
            suites[suite].update(passed=int(m.group(1)), failed=int(m.group(2)),
                                 wall=float(m.group(3)) if m.group(3) else None)
            continue
        m = RESULT.match(line)
        if m and suite:
            n += 1
            out.append({"suite": suite, "ord": n, "name": m.group(3)[:400],
                        "status": STATUS[m.group(1)],
                        "ms": int(float(m.group(2)) * 1000) if m.group(2) else None})
            if len(out) > MAX_TESTS:
                break
    return out, suites


# ---- keeping an entry with its test ----------------------------------------

def _align(old, new):
    """Match the roster we had against the one just read, per file.

    Longest common subsequence on the NAMES, so inserting a test in the middle
    of a file moves nobody's entry: the unchanged names around it still line
    up. Whatever neither side matched is then paired by position, which is
    what catches a rename — same place, different words.

    Returns {new index: old index}, and anything unpaired is genuinely new or
    genuinely gone.
    """
    a, b = [x["name"] for x in old], [x["name"] for x in new]
    # Standard LCS table. These are per-file rosters — a couple of hundred at
    # most — so the quadratic table is cheaper than being clever.
    t = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            t[i][j] = t[i + 1][j + 1] + 1 if a[i] == b[j] else max(t[i + 1][j], t[i][j + 1])
    pairs, i, j = {}, 0, 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            pairs[j] = i
            i, j = i + 1, j + 1
        elif t[i + 1][j] >= t[i][j + 1]:
            i += 1
        else:
            j += 1
    # ...and the leftovers by position, which is a rename: the test is where
    # it was and says something else. Only one candidate each way, or this
    # would pair a deletion here with an addition somewhere else entirely.
    freeA = [x for x in range(len(a)) if x not in pairs.values()]
    freeB = [x for x in range(len(b)) if x not in pairs]
    for x, y in zip(freeA, freeB):
        # Positional, so only when nothing matched between them moved far: two
        # ordinals apart is an edit, twenty is a coincidence.
        if abs(x - y) <= 2:
            pairs[y] = x
    return pairs


def ingest(project, text, by="you"):
    """Record a run: durations onto the tests, and what drifted.

    Returns the drift — added, gone, renamed — because that is the answer
    somebody wants at the moment of ingesting, not on a tab they might open.
    """
    roster, suites = parse(text)
    if not roster:
        return {"error": "nothing in that looks like a test run — "
                         "is it the runner's output, and was BB_TEST_TIMING=1 set?"}
    now = int(time.time())
    added, gone, renamed = [], [], []
    with _lock:
        d = load()
        p = _project(d, project)
        was = p.get("tests") or {}
        # Grouped per file, because that is the unit the runner orders and the
        # only scope in which an ordinal means anything.
        by_suite = {}
        for r in roster:
            by_suite.setdefault(r["suite"], []).append(r)
        fresh = {}
        for suite, rows in by_suite.items():
            old = sorted([t | {"key": k} for k, t in was.items()
                          if t.get("suite") == suite],
                         key=lambda t: int(t.get("ord") or 0))
            pairs = _align(old, rows)
            for idx, r in enumerate(rows):
                key = f"{suite}#{r['ord']}"
                prev = old[pairs[idx]] if idx in pairs else None
                e = {"suite": suite, "ord": r["ord"], "name": r["name"],
                     "status": r["status"], "seen": now,
                     "protects": (prev or {}).get("protects", ""),
                     "notes": (prev or {}).get("notes", ""),
                     "ms": list((prev or {}).get("ms") or [])}
                if r["ms"] is not None:
                    e["ms"].append(r["ms"])
                    del e["ms"][:-KEEP]
                fresh[key] = e
                if prev is None:
                    added.append({"key": key, "name": r["name"]})
                elif prev["name"] != r["name"]:
                    renamed.append({"key": key, "was": prev["name"], "now": r["name"]})
        # Anything in a file the run did not touch is left alone: ingesting one
        # file's log must not report every other file as deleted. Only a suite
        # that RAN is reconciled.
        ran = set(by_suite)
        for k, t in was.items():
            if t.get("suite") not in ran:
                fresh[k] = t
        for suite, rows in by_suite.items():
            old = [t | {"key": k} for k, t in was.items() if t.get("suite") == suite]
            kept = {t["name"] for t in rows}
            for t in old:
                if t["name"] not in kept and not any(
                        r["was"] == t["name"] for r in renamed):
                    gone.append({"key": t["key"], "name": t.get("name", "")})
        p["tests"] = fresh
        # Kept rather than only returned: the drift is the thing this file
        # exists to catch, and an answer that only exists in the terminal of
        # whoever ingested is an answer nobody reads twice.
        p["drift"] = {"at": now, "added": added[:200], "gone": gone[:200],
                      "renamed": renamed[:200]}
        p.setdefault("runs", []).append({
            "at": now, "by": "claude" if by == "claude" else "you",
            "n": len(roster), "suites": len(by_suite),
            "wall": round(sum(s["wall"] or 0 for s in suites.values()), 1),
            "ms": sum(r["ms"] or 0 for r in roster)})
        del p["runs"][:-KEEP_RUNS]
        save(d)
    return {"ok": True, "n": len(roster), "suites": sorted(by_suite),
            "added": added, "gone": gone, "renamed": renamed}


def describe(project, key, protects=None, notes=None):
    """The hand-written half. Either field, or both; "" clears one."""
    with _lock:
        d = load()
        p = _project(d, project)
        t = (p.get("tests") or {}).get(key)
        if not t:
            return {"error": f"no test called {key} here — `bb tests` lists them"}
        if protects is not None:
            t["protects"] = str(protects).strip()[:MAX_TEXT]
        if notes is not None:
            t["notes"] = str(notes).strip()[:MAX_TEXT]
        save(d)
    return {"ok": True, "test": t | {"key": key}}


def describe_many(project, rows):
    """Write many descriptions at once, from {key: {protects, notes}}.

    One load and one save for the lot. The per-test verb takes the file lock
    and rewrites the store each time it is called, which is right for a
    sentence somebody just typed and wrong for two thousand — a bulk fill
    through it is two thousand rewrites of a file that grows as it goes.

    Keys it does not recognize are counted and handed back rather than
    written: a description file that has drifted from the roster is the same
    failure this module exists to catch, and inventing a row for a test that
    is not there would hide it.
    """
    if not isinstance(rows, dict):
        return {"error": "expected an object of key -> {protects, notes}"}
    wrote, unknown = 0, []
    with _lock:
        d = load()
        p = _project(d, project)
        tests = p.get("tests") or {}
        for key, v in rows.items():
            t = tests.get(key)
            if not t:
                unknown.append(key)
                continue
            if not isinstance(v, dict):
                continue
            if "protects" in v:
                t["protects"] = str(v["protects"] or "").strip()[:MAX_TEXT]
            if "notes" in v:
                t["notes"] = str(v["notes"] or "").strip()[:MAX_TEXT]
            wrote += 1
        save(d)
    return {"ok": True, "wrote": wrote, "unknown": unknown[:50],
            "unknown_n": len(unknown)}


# ---- the heuristic ---------------------------------------------------------
# A test that takes 30.0s is not doing 30 seconds of work. It is waiting out
# something with a round number in it — a default timeout, a poll interval, a
# sleep — and those are the cheapest thing in a suite to fix, because the work
# is already done and only the waiting has to go.
#
# The rule is one-sided on purpose: a fixed wait lands just ABOVE its boundary,
# never below, because the boundary is the wait and everything after it is
# overhead. So 30.1s is a 30-second timeout and 29.6s is a test that happens to
# take 29.6 seconds. Being wrong in that direction costs somebody a look; being
# wrong the other way hides the thing this is for.
BOUNDARIES = (5, 10, 15, 20, 25, 30, 40, 45, 60, 75, 90, 120)
SLACK = 0.9             # seconds of overhead a real fixed wait picks up
FLOOR = 3.0             # below this, a round number is a coincidence


def suspect(ms):
    """The boundary this duration is sitting on, or None."""
    if not ms:
        return None
    s = ms / 1000.0
    if s < FLOOR:
        return None
    for b in BOUNDARIES:
        if 0 <= s - b <= SLACK:
            return b
    return None


# ---- what the tab and the CLI both read ------------------------------------

def _latest(t):
    return (t.get("ms") or [None])[-1]


def payload(project):
    """Everything the Tests view shows, computed rather than stored.

    Rollups and flags are derived on read: they are cheap, and a stored total
    is a number that goes wrong quietly the first time something else writes.
    """
    with _lock:
        d = load()
        p = (d.get("projects") or {}).get(project) or {}
    tests = []
    for key, t in (p.get("tests") or {}).items():
        ms = _latest(t)
        hist = t.get("ms") or []
        tests.append({
            "key": key, "suite": t.get("suite", ""), "ord": t.get("ord", 0),
            "name": t.get("name", ""), "status": t.get("status", ""),
            "protects": t.get("protects", ""), "notes": t.get("notes", ""),
            "ms": ms, "history": hist[-KEEP:], "seen": t.get("seen", 0),
            # A continuation only reads correctly next to the test it follows,
            # and this view sorts by duration — which would otherwise strand
            # every "..." line miles from the sentence it finishes.
            "cont": t.get("name", "").startswith("..."),
            "suspect": suspect(ms),
            # Was it slower than it used to be? Against the median of what came
            # before rather than the previous run, which on this box is noise.
            "was": _median(hist[:-1]) if len(hist) > 1 else None,
        })
    # The sentence a continuation belongs to: the nearest test above it in the
    # file that is not itself a continuation. Resolved here, once, so no
    # renderer has to know the rule.
    order = sorted(tests, key=lambda t: (t["suite"], t["ord"]))
    lead = {}
    for t in order:
        if not t["cont"]:
            lead[t["suite"]] = t["name"]
        elif t["suite"] in lead:
            t["after"] = lead[t["suite"]]
    suites = {}
    for t in tests:
        s = suites.setdefault(t["suite"], {"suite": t["suite"], "n": 0, "ms": 0,
                                           "suspect": 0, "recover": 0,
                                           "undocumented": 0, "fail": 0, "skip": 0})
        s["n"] += 1
        s["ms"] += t["ms"] or 0
        if t["suspect"]:
            s["suspect"] += 1
            s["recover"] += t["suspect"] * 1000
        if not t["protects"]:
            s["undocumented"] += 1
        if t["status"] == "fail":
            s["fail"] += 1
        if t["status"] in ("skip", "todo"):
            s["skip"] += 1
    runs = p.get("runs") or []
    drift = p.get("drift") or {}
    return {
        "drift": drift,
        "project": project,
        "tests": sorted(tests, key=lambda t: (-(t["ms"] or 0), t["suite"], t["ord"])),
        "suites": sorted(suites.values(), key=lambda s: -s["ms"]),
        "runs": runs[-KEEP_RUNS:],
        "total_ms": sum(t["ms"] or 0 for t in tests),
        "n": len(tests),
        "suspect": sum(1 for t in tests if t["suspect"]),
        "recover_ms": sum(t["suspect"] * 1000 for t in tests if t["suspect"]),
        "undocumented": sum(1 for t in tests if not t["protects"]),
        # The last run's own wall time, for the honest gap between what the
        # tests cost and what the suite costs: the difference is the harness.
        "last_wall_ms": int((runs[-1].get("wall") or 0) * 1000) if runs else 0,
    }


def _median(xs):
    xs = sorted(x for x in xs if x)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) // 2


def counts():
    """{project: how many tests are on record} — for the poll, like the rest."""
    with _lock:
        d = load()
    return {p: len((v.get("tests") or {})) for p, v in (d.get("projects") or {}).items()}


def revisions():
    """{project: how many runs have been ingested} — the tab's re-read token,
    the same shape bugs.revisions() has. A run is the only thing that changes
    the timings; a description edit changes one row and the panel drew it."""
    with _lock:
        d = load()
    return {p: len(v.get("runs") or []) for p, v in (d.get("projects") or {}).items()}
