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
    if rows:
        print(f"{'n':>5}  {'max ms':>7}  {'avg ms':>7}  {'by':<8} {'from':<8} request")
    for r in rows:
        print(f"{r['n']:>5}  {r.get('ms_max', 0):>7}  {r.get('ms_avg', 0):>7}  {r['by']:<8} {r['agent']:<8} "
              f"{r['method']} {r['path']}")
    slow = d.get("slow") or []
    if slow:
        print("slowest (over 500ms):")
        for s in slow:
            print(f"  {s['ms']:>6}ms  {time.strftime('%H:%M:%S', time.localtime(s['at']))}  "
                  f"{s['by']}/{s['agent']}  {s['method']} {s['path']}")


if __name__ == "__main__":
    main()
