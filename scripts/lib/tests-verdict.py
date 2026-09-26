"""Behind `bb tests last` and the end of `bb tests run` (tests_verdict in
bb): what went wrong, from a run's own log. Per file, its failed
assertions by name and, when it printed no totals line, the fact that it
died and the line it died on. Nothing here re-runs anything.

BB_VERDICT_LOG is the run log's path.
"""
import os
import re
import sys

try:
    with open(os.environ["BB_VERDICT_LOG"], errors="replace") as f:
        lines = f.read().splitlines()
except OSError as e:
    sys.exit(f"[builderbot] ERROR: no run log to read: {e}")

BANNER = re.compile(r"^\[(?:dashboard-test|builderbot)\] == (\S+) ==")
# The same file run again, alone, after it failed in the whole run (run.sh,
# B124): its result decides whether the first failure was the file's or the
# run's.
AGAIN = re.compile(r"^\[(?:dashboard-test|builderbot)\] == (\S+) again ==")
# ` in Xs` only when the run was timed: `bb dashboard test FILE` prints the
# bare form, and a verdict that required the seconds read a passing file as a
# crash, which is the one thing this tool must never do.
TOTALS = re.compile(r"^(\d+) passed, (\d+) failed(?: in ([\d.]+)s)?")
FAIL = re.compile(r"^FAIL\s+(?:\[\+[\d.]+s\]\s+)?(.*)")
# What a crashed file's death looks like. Node puts the message on its own
# line after the banner it prints, so the first of these AFTER the last PASS
# is the thing to quote.
DIED = re.compile(r"^(?:\w+Error|Error|AssertionError)\b.*|^[a-zA-Z.]+: .*(?:Timeout|exceeded|not defined|is not a function).*")

files, again, cur = [], {}, None
for ln in lines:
    m = AGAIN.match(ln)
    if m:
        cur = {"name": m.group(1), "fails": [], "totals": None, "why": "", "tail": []}
        again[m.group(1)] = cur
        continue
    m = BANNER.match(ln)
    if m:
        cur = {"name": m.group(1), "fails": [], "totals": None, "why": "", "tail": []}
        files.append(cur)
        continue
    if cur is None:
        continue
    f = FAIL.match(ln)
    if f:
        cur["fails"].append(f.group(1).strip())
    m = TOTALS.match(ln)
    if m:
        cur["totals"] = (int(m.group(1)), int(m.group(2)),
                         float(m.group(3) or 0))
    # The harness's own lines are not the suite's last words.
    if not ln.startswith("PASS") and not ln.startswith("[dashboard-test]"):
        cur["tail"].append(ln)
        del cur["tail"][:-40]

bad = []
for f in files:
    if f["totals"] is None:
        # Died. Quote the first line that looks like a cause, and the file and
        # line from the stack under it when there is one.
        why, where = "", ""
        for ln in f["tail"]:
            s = ln.strip()
            if not why and DIED.match(s):
                why = s
            m = re.search(r"at (\S+\.mjs):(\d+):\d+", ln)
            if m and not where:
                where = f"{m.group(1).split('/')[-1]}:{m.group(2)}"
        f["why"] = why or "ended without reporting a total"
        f["where"] = where
        bad.append(f)
    elif f["totals"][1]:
        f["where"] = ""
        bad.append(f)

if not files:
    sys.exit("[builderbot] ERROR: that log has no test output in it")
# A file that failed in the run and passed alone, in a world of its own, is
# flaky: named, and not a failure. One that failed alone as well is.
passed_alone = lambda f: (again.get(f["name"]) or {}).get("totals") and not again[f["name"]]["totals"][1]
# What each file actually ran, which for a flaky one is its RETRY's total: the
# first attempt crashed part way and its own total is short or missing, so
# counting that reported a run's worth of checks as having gone missing
# against the run before it (B178).
counted = lambda f: (again[f["name"]]["totals"] if passed_alone(f) else f["totals"])
checks = sum(t[0] + t[1] for t in map(counted, files) if t)
flaky = [f for f in bad if passed_alone(f)]
bad = [f for f in bad if not passed_alone(f)]
for f in bad:
    f["again"] = f["name"] in again
if flaky:
    print()
    print("== flaky: failed in the whole run, passed alone ==")
    for f in flaky:
        first = f["fails"][0] if f["fails"] else (f["why"] or "crashed")
        print(f"  {f['name']}  {first[:140]}")
        # A file that died with no check failing and no cause matched: its
        # last words, so the next time has evidence rather than a name (B267).
        if not f["fails"]:
            for ln in [x for x in f["tail"] if x.strip()][-3:]:
                print(f"      | {ln.strip()[:140]}")
if not bad:
    print(f"all {len(files)} suites passed: {checks} checks"
          + (f", {len(flaky)} of them flaky (above)" if flaky else ""))
    sys.exit(0)

print()
print("== what went wrong ==")
for f in bad:
    if f["totals"] is None:
        print(f"  {f['name']}  CRASHED" + (f" at {f['where']}" if f.get("where") else ""))
        print(f"      {f['why'][:160]}")
        # What had already gone wrong before it died. A crash is usually the
        # SECOND symptom (a click on something an earlier assertion has just
        # said is not there) and printing only the death sends the next
        # reader to the wrong line.
        if f["fails"]:
            print(f"      {len(f['fails'])} assertion{'' if len(f['fails']) == 1 else 's'}"
                  " had already failed:")
            for x in f["fails"][:10]:
                print(f"        {x[:148]}")
            if len(f["fails"]) > 10:
                print(f"        ...and {len(f['fails']) - 10} more")
        print("      no totals line, so nothing after this point in that file ran")
    else:
        print(f"  {f['name']}  {f['totals'][1]} failed")
        for x in f["fails"][:10]:
            print(f"      {x[:150]}")
        if len(f["fails"]) > 10:
            print(f"      ...and {len(f['fails']) - 10} more")
print(f"{len(bad)} of {len(files)} suites have problems: {checks} checks ran"
      + (" (each failed again alone)" if all(f.get("again") for f in bad) else "")
      + (f"; {len(flaky)} more flaky" if flaky else ""))
sys.exit(1)
