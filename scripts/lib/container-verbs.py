"""Behind `bb container` (cmd_container in bb): a container asked for with its
compose file and a reason (roadmap R71), which an administrator reads on the
bell and allows or denies; Allow hands the file to the Containers page's own New
container path and starts the build.

The first argument is the verb (status or new). For new, BB_PHONE_AUTH is the
auth header, BB_PHONE_WHY the reason, BB_PHONE_PROJECT the project asking,
BB_C_NAME the container's name, BB_C_COMPOSE and BB_C_ENV the files to send,
BB_C_NODE the node and BB_C_FOR the project it is for.
"""
import os
import sys

import bbapi
import waits


def status():
    d = bbapi.call("/api/phone", auth=os.environ["BB_PHONE_AUTH"])
    asks = [a for a in d.get("asks") or [] if a.get("kind") == "container"]
    if not asks:
        print("container: nothing is waiting")
    for a in asks:
        print("waiting: #{} {} ({}): {}".format(a.get("id"), a.get("name") or "?",
              a.get("node_name") or "the default node", a.get("why")))


def new():
    post = lambda body: bbapi.call("/api/phone", body, auth=os.environ["BB_PHONE_AUTH"])  # noqa: E731
    compose = open(os.environ["BB_C_COMPOSE"], encoding="utf-8", errors="replace").read()
    env = open(os.environ["BB_C_ENV"], encoding="utf-8", errors="replace").read() if os.environ.get("BB_C_ENV") else ""
    r = post({"action": "ask", "kind": "container", "why": os.environ["BB_PHONE_WHY"],
              "name": os.environ["BB_C_NAME"], "compose": compose, "env": env,
              "node": os.environ.get("BB_C_NODE", ""), "for": os.environ.get("BB_C_FOR", ""),
              "project": os.environ.get("BB_PHONE_PROJECT", "")})
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr); sys.exit(1)
    if not r.get("id"):
        # Done at once: the setting is auto and it is this project's own.
        print(f"[builderbot] created {r.get('name') or 'it'}; the build is a job on the Jobs page")
        sys.exit(0)
    rid = r["id"]
    print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{rid}): the compose file is on their "
          "bell, waiting up to 15 minutes for Allow", file=sys.stderr)
    o = waits.outcome(os.environ["BB_PHONE_AUTH"], rid, "the administrator said no")
    if o.get("code"):
        print(f"[builderbot] ERROR: {o.get('out') or 'refused'}", file=sys.stderr); sys.exit(1)
    print(f"[builderbot] allowed: {o.get('out')} (the build is a job on the Jobs page)")
    sys.exit(0)


VERBS = {"status": status, "new": new}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
