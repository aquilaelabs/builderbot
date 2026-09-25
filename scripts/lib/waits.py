"""What a bb verb waits on, written once: a person's Allow, or a job's end.

Six verbs put a request in front of a person and wait for the answer (bb
phone run, bb root run, bb container new, bb devapp rebuild, new, env set,
remove, start, stop, restart), and each carried the same fifteen-minute poll
of /api/phone with its own copy of the three ways it ends. Two more (bb run,
bb emu on a node) queue a job and stream its log until it stops, with the same
loop twice. This is those loops, each kept once; the sentence a refusal is
said with stays with the verb, because "the operator said no" and "the
rebuild was not allowed" are different verbs' words.

Polled rather than pushed: a shell command waiting on a person, and a person
is slow in a way no callback improves.
"""
import sys
import time

import bbapi


def outcome(auth, rid, denied):
    """What became of ask #rid, once a second for up to fifteen minutes: the
    outcome once it is done. A refusal from the API ends the verb with its
    sentence, a No with `denied` (the verb's own words), and silence with the
    quarter hour's."""
    for _ in range(900):
        time.sleep(1)
        o = bbapi.call("/api/phone", {"action": "outcome", "id": rid}, auth=auth)
        if o.get("error"):
            sys.exit(f"[builderbot] ERROR: {o['error']}")
        if o["state"] == "denied":
            sys.exit(f"[builderbot] {denied}")
        if o["state"] == "done":
            return o
    sys.exit("[builderbot] nobody answered within fifteen minutes")


def follow(auth, jid):
    """Job jid's log streamed to stdout as it grows, once a second until the
    job stops: the row as it ended, and its state (succeeded, failed or
    canceled). A refusal from the API ends the verb with its sentence."""
    shown = 0
    while True:
        j = bbapi.call(f"/api/v1/jobs?id={jid}", auth=auth)
        if j.get("error"):
            sys.exit(f"[builderbot] ERROR: {j['error']}")
        log = j.get("log") or ""
        if len(log) > shown:
            sys.stdout.write(log[shown:])
            sys.stdout.flush()
            shown = len(log)
        if j["state"] in ("succeeded", "failed", "canceled"):
            return j, j["state"]
        time.sleep(1)
