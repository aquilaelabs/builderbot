"""Whether a node is quiet enough to time anything on (R108).

A session measuring speed (a decoder's latency, a build's length, a suite's
seconds) reads its result against a machine it shares, and from inside its
own view it sees its own processes and nothing else: the load average says
the machine is busy and never why. The node's agent sees all of it and says
so on every heartbeat (its load, memory and card, and what runs there by
KIND: emulators, Gradle, compilers, browsers, media, docker builds, Claude),
and the controller knows the jobs on it and which Claude sessions are
working. This joins the two into one answer with a verdict:

    quiet       nothing else is using the machine much: a timing means
                something
    busy        other work is running: a timing is worth a second run, and
                one compared with another taken at another time is not
                comparable
    saturated   the machine has more to do than cores to do it: a timing is
                the machine's, not the code's
    unknown     the node has not reported lately

Another project's work is counted and never named: a session sees its own
project, and that a build of something else is running is all it needs.
"""
import time

STALE_S = 90


def verdict(sample, jobs, sessions_working, now=None):
    """(word, [reasons]) from a node's last heartbeat sample, its active jobs
    ([{type, mine}]) and how many Claude sessions are working there."""
    now = now or time.time()
    if not sample or now - int(sample.get("at") or 0) > STALE_S:
        age = int(now - int(sample.get("at") or 0)) if sample and sample.get("at") else None
        return "unknown", [f"the node has not reported for {age} s" if age else "the node has not reported"]
    cores = int(sample.get("cores") or 0) or 1
    load = float(sample.get("load1") or 0) / cores
    cpu = float(sample.get("cpu_pct") or 0)
    mem = (float(sample.get("mem_used_mb") or 0) / float(sample["mem_mb"]) * 100) if sample.get("mem_mb") else 0
    kinds = {k: v for k, v in (sample.get("kinds") or {}).items() if v and k != "claude"}
    others = [j for j in jobs if not j.get("mine")]
    why = []
    if load >= 1.0:
        why.append(f"load {sample.get('load1')} on {cores} cores")
    if cpu >= 85:
        why.append(f"CPU {cpu:g}% over the last heartbeat")
    if mem >= 92:
        why.append(f"memory {mem:.0f}% used")
    if why:
        return "saturated", why
    if load >= 0.5:
        why.append(f"load {sample.get('load1')} on {cores} cores")
    if cpu >= 40:
        why.append(f"CPU {cpu:g}%")
    if float(sample.get("gpu_pct") or 0) >= 30:
        why.append(f"the card at {sample.get('gpu_pct'):g}%")
    if kinds:
        why.append("running: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
    if others:
        why.append(f"{len(others)} job{'s' if len(others) != 1 else ''} of other projects")
    if sessions_working > 1:
        why.append(f"{sessions_working - 1} other Claude session{'s' if sessions_working != 2 else ''} working")
    return ("busy", why) if why else ("quiet", [])


def report(node, jobs, sessions_working, project=""):
    """The answer `bb node busy` prints, for one node: the numbers, what runs
    there by kind, the jobs by type (this project's marked), and the verdict.
    `node` is the node record; `jobs` its active jobs."""
    s = ((node or {}).get("reported") or {}).get("sample") or {}
    rows = [{"type": j.get("type") or "?", "mine": (j.get("project") or "") == project} for j in jobs]
    word, why = verdict(s, rows, sessions_working)
    by = {}
    for r in rows:
        key = r["type"] + (" (yours)" if r["mine"] else "")
        by[key] = by.get(key, 0) + 1
    return {"node": (node or {}).get("name") or "", "at": int(s.get("at") or 0),
            "verdict": word, "why": why,
            "cores": int(s.get("cores") or ((node or {}).get("reported") or {}).get("cpu") or 0),
            "load1": s.get("load1"), "cpu_pct": s.get("cpu_pct"),
            "mem_used_mb": s.get("mem_used_mb"), "mem_mb": s.get("mem_mb"),
            "gpu_pct": s.get("gpu_pct"), "gpu_mem_used_mb": s.get("gpu_mem_used_mb"),
            "gpu_mem_mb": s.get("gpu_mem_mb"), "gpu_procs": s.get("gpu_procs"),
            "kinds": s.get("kinds") or {}, "jobs": by, "sessions_working": sessions_working}
