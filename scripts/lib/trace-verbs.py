"""Behind `bb dashboard trace [SECONDS]` (cmd_dashboard in bb): what the
dashboard was asked over the last SECONDS, from the ring the server keeps
(server.py trace_since), grouped by endpoint and by who asked, with how many
times and how long each took. BB_TRACE_AUTH is the auth header.
"""
import os
import sys
import time

import bbapi


def main():
    try:
        secs = max(1, int(sys.argv[1] if len(sys.argv) > 1 else 60))
    except ValueError:
        sys.exit("[builderbot] ERROR: bb dashboard trace [SECONDS]")
    d = bbapi.call(f"/api/trace?since={int(time.time()) - secs}", auth=os.environ["BB_TRACE_AUTH"])
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    rows = d.get("rows") or []
    print(f"asked over the last {secs}s: {d.get('total', 0)} requests, {len(rows)} distinct")
    # How much of one core the server spent, and its threads: near 1.0 is a
    # server short of CPU, which slows every request whatever it asks for.
    if d.get("busy") is not None:
        print(f"the server spent {round(d['busy'] * 100)}% of one core over the window, {d.get('threads', '?')} threads now")
    if rows:
        print(f"{'n':>5}  {'max ms':>7}  {'avg ms':>7}  {'cpu ms':>6}  {'by':<8} {'from':<8} request")
    for r in rows:
        print(f"{r['n']:>5}  {r.get('ms_max', 0):>7}  {r.get('ms_avg', 0):>7}  {r.get('cpu_avg', 0):>6}  {r['by']:<8} {r['agent']:<8} "
              f"{r['method']} {r['path']}")
    # Where the time went (timing.py): each named part, its total first. A
    # request whose cpu ms is far under its avg ms spent the rest waiting.
    secs_ = d.get("sections") or []
    if secs_:
        print("where the time went (named parts, most total first):")
        print(f"{'n':>5}  {'total ms':>8}  {'avg ms':>7}  {'max ms':>7}  part")
        for p in secs_:
            print(f"{p['n']:>5}  {p['sum']:>8}  {p['avg']:>7}  {p['max']:>7}  {p['name']}")
    slow = d.get("slow") or []
    if slow:
        print("slowest (over 500ms; long polls left out):")
        for s in slow:
            parts = ", ".join(f"{k} {v}" for k, v in (s.get("parts") or {}).items())
            print(f"  {s['ms']:>6}ms  cpu {s.get('cpu', 0):>5}ms  {time.strftime('%H:%M:%S', time.localtime(s['at']))}  "
                  f"{s['by']}/{s['agent']}  {s['method']} {s['path']}" + (f"  [{parts}]" if parts else ""))


if __name__ == "__main__":
    main()
