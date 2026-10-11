"""Behind `bb root` (cmd_root in bb): one command as root on the project's node
(roadmap R38), the phone's shape applied to root: the reason and the exact
command in front of a person, Allow runs it on the node, Deny says no.

The first argument is the verb (status or run); for run the rest are the
command. BB_PHONE_AUTH is the auth header, BB_PHONE_WHY the sentence an
administrator reads, BB_PHONE_PROJECT the project asking.
"""
import os
import sys

import bbapi
import waits


def status():
    d = bbapi.call("/api/phone", auth=os.environ["BB_PHONE_AUTH"])
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: could not reach the dashboard at {bbapi.url()}: {d['error']}")
    asks = [a for a in (d.get("asks") or []) if a.get("kind") == "root"]
    if not asks:
        print("root:    nothing is waiting")
    for a in asks:
        print("waiting: #{} {} ({} on {}): {}".format(a.get("id"), a.get("why"), a.get("project") or "a session",
                                                     a.get("node_name"), " ".join(a.get("cmd") or [])))


def run():
    post = lambda body: bbapi.call("/api/phone", body, auth=os.environ["BB_PHONE_AUTH"])  # noqa: E731

    # A file under /tmp: on a sandbox node a session's /tmp is its own view
    # (bb-session), and the root command runs outside it, so the file is not
    # there and the command failed with a bare exit code (B253). Said before
    # the ask, since the person allowing it cannot see it either.
    for a in sys.argv[2:]:
        if a.startswith(("/tmp/", "/var/tmp/", "/dev/shm/")) and os.path.exists(a):
            print(f"[builderbot] note: {a} is under a directory that is this session's own view on a "
                  "sandbox node; the root command runs outside it and will not find the file there. "
                  "A path under the project tree is seen by both.", file=sys.stderr)
    r = post({"action": "ask", "kind": "root", "why": os.environ["BB_PHONE_WHY"], "cmd": sys.argv[2:],
              "project": os.environ.get("BB_PHONE_PROJECT", ""),
              # A node the project hosts containers on, when named (--node).
              **({"node": os.environ["BB_PHONE_NODE"]} if os.environ.get("BB_PHONE_NODE") else {})})
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr); sys.exit(1)
    rid = r["id"]
    print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{rid}) for root on {r.get('node') or 'the node'}, "
          "waiting up to 15 minutes for Allow on the dashboard's Nodes tab or bell", file=sys.stderr)
    o = waits.outcome(os.environ["BB_PHONE_AUTH"], rid, "the administrator said no")
    sys.stdout.write(o.get("out") or "")
    sys.exit(o.get("code") or 0)


VERBS = {"status": status, "run": run}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
