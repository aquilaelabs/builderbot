"""Behind `bb phone` (cmd_phone in bb): what phone each node carries, and one adb
command put in front of the operator with its reason, run when they allow it.

The first argument is the verb (status or run); for run the rest are the adb
arguments. BB_PHONE_AUTH is the auth header, BB_PHONE_WHY the sentence the
operator reads, BB_PHONE_PROJECT the project asking.
"""
import os
import sys

import bbapi
import waits


def status():
    d = bbapi.call("/api/phone", auth=os.environ["BB_PHONE_AUTH"])
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: could not reach the dashboard at {bbapi.url()}: {d['error']}")
    rows = d.get("nodes") or []
    if not rows:
        print("phone:   no node carries adb; a phone is driven from a node")
    for n in rows:
        p = n.get("phone")
        who = (n.get("owner") or {}).get("name")
        print("{:<16} {}".format(n.get("name", "?") + ":",
              "{} ({}){}".format(p.get("model") or "phone", p.get("serial"), f", connected by {who}" if who else "")
              if p else ("not dialing in" if not n.get("live") else "no phone connected")))
    for a in d.get("asks") or []:
        print("waiting: #{} {} ({} on {})".format(a.get("id"), a.get("why"), a.get("project") or "a session", a.get("node_name")))


def run():
    post = lambda body: bbapi.call("/api/phone", body, auth=os.environ["BB_PHONE_AUTH"])  # noqa: E731


    # The project names the node, and the node's phone names who is asked: a
    # session's token carries its project; a person running this names theirs.
    r = post({"action": "ask", "why": os.environ["BB_PHONE_WHY"], "cmd": sys.argv[2:],
              "project": os.environ.get("BB_PHONE_PROJECT", "")})
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr); sys.exit(1)
    rid = r["id"]
    print(f"[builderbot] asked {r.get('to') or 'the operator'} (#{rid}), waiting up to 15 minutes "
          "for Allow on the dashboard's Phone tab", file=sys.stderr)
    # Polled rather than pushed: this is a shell command waiting on a person, and
    # a person is slow in a way no callback improves.
    o = waits.outcome(os.environ["BB_PHONE_AUTH"], rid, "the operator said no")
    sys.stdout.write(o.get("out") or "")
    sys.exit(o.get("code") or 0)


VERBS = {"status": status, "run": run}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
