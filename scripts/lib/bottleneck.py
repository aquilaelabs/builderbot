#!/usr/bin/env python3
"""What bounded a run of the dashboard suites (R130), from its own numbers.

A run on more workers is only faster where the workers were waiting on each
other's share of the work; where one suite is the whole of a worker's time,
or the machine was already full, more workers change nothing. This reads
what the runner measured and says which it was, in one sentence a person or
a session can act on, and keeps the numbers beside the suites' timings.

    bottleneck.py RUN.json

RUN.json: {"workers": N, "cores": N, "start": t, "phase_end": t, "end": t,
           "suites": {name: secs}, "plan": {name: bucket}, "worker_end": {bucket: t},
           "load": [loadavg samples], "held_s": secs waited for room, "reruns": [names], "out": path}
"""
import json
import sys


def mins(s):
    s = int(round(s))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def judge(r):
    n, cores = max(1, r["workers"]), max(1, r.get("cores") or 1)
    phase = max(1.0, r["phase_end"] - r["start"])
    reruns = max(0.0, r["end"] - r["phase_end"])
    wall = phase + reruns
    suites = r.get("suites") or {}
    work = sum(suites.values())
    busy = work / (n * phase)
    per = {}
    for name, b in (r.get("plan") or {}).items():
        per.setdefault(str(b), []).append(name)
    ends = {str(b): t - r["start"] for b, t in (r.get("worker_end") or {}).items()}
    slow_b = max(ends, key=lambda b: ends[b]) if ends else ""
    in_slow = sorted(per.get(slow_b, []), key=lambda x: -suites.get(x, 0))
    top = in_slow[0] if in_slow else (max(suites, key=lambda x: suites[x]) if suites else "")
    top_s = suites.get(top, 0)
    held = float(r.get("held_s") or 0)
    load = r.get("load") or []
    mean_load = sum(load) / len(load) if load else 0.0
    facts = (f"{mins(wall)} wall ({mins(phase)} the run" + (f", {mins(reruns)} reruns" if reruns >= 1 else "")
             + f"); {mins(work)} of suites on {n} workers, {round(busy * 100)}% busy"
             + (f"; the floor is worker {int(slow_b) + 1 if slow_b.isdigit() else slow_b}, {mins(ends.get(slow_b, 0))}, "
                f"{top} {mins(top_s)} of it" if slow_b else "")
             + (f"; load {mean_load:.1f} on {cores} cores" if load else "")
             + (f"; workers held {mins(held)} waiting for room" if held >= 1 else ""))
    again = set(r.get("again") or [])
    flaky = [x for x in r.get("reruns") or [] if x not in again]
    if again:
        why = (f"{', '.join(sorted(again))} failed, and failed again alone: a real failure, read its output above"
               + (f"; {', '.join(flaky)} passed alone (flaky)" if flaky else ""))
    elif reruns > 0.25 * wall and flaky:
        why = (f"reruns took {mins(reruns)} of {mins(wall)}: {', '.join(flaky)} failed under load and passed alone; "
               "making them pass the first time is the biggest saving")
    elif top_s >= 0.6 * phase and busy < 0.8:
        why = (f"{top} is the floor, {round(top_s / phase * 100)}% of the run's time on its own: "
               f"splitting it shortens the run; more workers would not")
    elif held >= 0.2 * n * phase:
        why = (f"the machine was busy: the workers waited {mins(held)} in all for room to take their next "
               "suite, so this run went at the pace the node could give it, and more workers would only wait longer")
    elif load and mean_load >= 0.9 * cores:
        why = (f"the machine was full (load {mean_load:.1f} on {cores} cores): more workers will not help, "
               "and fewer would be about as fast")
    elif busy >= 0.85 and (not load or mean_load < 0.7 * cores):
        why = f"the workers were {round(busy * 100)}% busy with room on the machine: more workers would help"
    else:
        why = f"nothing stands out: the longest suite, {top}, took {mins(top_s)} of a {mins(phase)} run"
    return {"wall_s": round(wall), "run_s": round(phase), "reruns_s": round(reruns), "work_s": round(work),
            "workers": n, "cores": cores, "busy": round(busy, 2), "floor_suite": top, "floor_s": round(top_s),
            "load": round(mean_load, 1), "held_s": round(held), "facts": facts, "bound": why}


def main(argv):
    with open(argv[0]) as f:
        r = json.load(f)
    got = judge(r)
    print(f"[dashboard-test] took: {got['facts']}")
    print(f"[dashboard-test] bound: {got['bound']}")
    if r.get("out"):
        try:
            with open(r["out"], "w") as f:
                json.dump(got, f)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
