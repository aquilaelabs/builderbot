"""Behind `bb devapp` (cmd_devapp in bb): this project's dev instance, and what
a session may be given over it under the project's one setting (Claude may:
Run its container). Everything here goes through the controller's API like
`bb root` and `bb phone`, because the daemon is the controller's connection
to the node; nothing runs docker anywhere.

The first argument is the verb: status, rebuild, test (the test command's
arguments after it), edit (new, env and remove, which BB_DEV_VERB names),
ls, or ctl (log, start, stop and restart, which BB_DEV_VERB names).
BB_DEV_AUTH is the auth header, BB_DEV_PROJECT the project, BB_DEV_INSTANCE
and BB_DEV_CONTAINER which of its containers, BB_DEV_WHY the reason a person
reads, BB_DEV_FILE and BB_DEV_SET the env file and whether it is being set,
BB_DEV_NAME the container a ctl verb acts on.
"""
import os
import sys
import time
import urllib.parse

import bbapi
import waits


def status():
    d = bbapi.call("/api/devapp", {"project": os.environ["BB_DEV_PROJECT"],
                                   "instance": os.environ.get("BB_DEV_INSTANCE", ""),
                                   "container": os.environ.get("BB_DEV_CONTAINER", ""),
                                   "action": "state"},
                   auth=os.environ["BB_DEV_AUTH"])
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    st = d.get("state") if isinstance(d.get("state"), dict) else d
    if not st.get("compose"):
        print("no compose file here, so there is no dev instance")
        raise SystemExit(0)
    print(f"  {'instance':<12} {st.get('name') or '-'}")
    print(f"  {'running':<12} {'yes' if st.get('running') else 'no'}")
    print(f"  {'daemon':<12} " + ("answering" if st.get("available")
                                  else (st.get("why") or "not reachable")))
    if st.get("built_rev"):
        print(f"  {'built from':<12} {st['built_rev']}")
    elif st.get("needs_build"):
        print(f"  {'built from':<12} nothing here yet")
    miss = st.get("missing_env") or []
    if miss:
        # Kept by BuilderBot for this container, never a file in the project.
        print(f"  {'env':<12} missing " + ", ".join(miss[:6])
              + (" …" if len(miss) > 6 else "") + "; bb devapp env prints it and bb devapp env set "
              "replaces it where the project's settings allow, else the operator's Env on the Docker tab")
    job = st.get("job") or {}
    if job.get("running"):
        print(f"  {'job':<12} {job.get('step') or 'working'}")
    elif job.get("error"):
        print(f"  {'job':<12} last one failed: {str(job['error'])[:120]}")


def rebuild():
    proj = os.environ["BB_DEV_PROJECT"]
    auth = os.environ["BB_DEV_AUTH"]
    post = lambda b: bbapi.call("/api/devapp", b | {"project": proj, "instance": os.environ.get("BB_DEV_INSTANCE", ""),  # noqa: E731
                                                    "container": os.environ.get("BB_DEV_CONTAINER", "")}, auth=auth)

    def look():
        d = post({"action": "state"})
        if d.get("error"):
            sys.exit(f"[builderbot] ERROR: {d['error']}")
        return d.get("state") if isinstance(d.get("state"), dict) else d

    # What it was built from before, because that is the only signal that says a
    # build HAPPENED. A job that succeeded is not news to the row (job_view
    # returns nothing for one), so "no job running" reads the same three seconds
    # before it starts and the moment after it finishes, and taking either for
    # success is how this said "rebuilt" over a build that had not begun.
    was = (look().get("built_rev") or "")
    r = post({"action": "rebuild", "why": os.environ.get("BB_DEV_WHY", "")})
    if r.get("error"):
        # The refusal names the dial, so it is printed as it came.
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("id") and not r.get("started"):
        # This project is on `ask`: nothing is building yet, a person has the
        # reason in front of them, and the wait is theirs. Allowing starts the
        # build, and from there this is the same poll as any other rebuild.
        rid = r["id"]
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{rid}), waiting up "
              "to 15 minutes for Allow on the dashboard's Docker tab or bell", file=sys.stderr)
        o = waits.outcome(auth, rid, "the rebuild was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'the rebuild would not start'}")
    print("[builderbot] rebuilding; it runs on the node's daemon and takes minutes",
          file=sys.stderr)
    # Polled rather than streamed: the job's log belongs to the row, and what a
    # session needs is the step while it waits and the verdict at the end. A
    # build that pulls can take half an hour, which is the cap here.
    last, seen, waited = "", False, 0.0
    while waited < 3600:
        time.sleep(3)
        waited += 3
        st = look()
        job = st.get("job") or {}
        step = str(job.get("step") or "")
        if step and step != last:
            print(f"  {step}", file=sys.stderr)
            last = step
        if job.get("running"):
            seen = True
            continue
        if job.get("error"):
            tail = str(job.get("log") or "")[-1200:]
            if tail:
                print(tail)
            sys.exit(f"[builderbot] ERROR: the rebuild failed: {str(job['error'])[:200]}")
        if seen or (st.get("built_rev") or "") != was:
            print(f"[builderbot] rebuilt {st.get('built_rev') or ''}; "
                  f"{st.get('name') or 'the instance'} is "
                  + ("up" if st.get("running")
                     else "built and not running" if st.get("await_env")
                     else "not running"))
            if st.get("await_env"):
                print("[builderbot] its env is not filled in: bb devapp env set FILE writes it where "
                      "the project's settings allow, else the operator's Env on the Docker tab",
                      file=sys.stderr)
            raise SystemExit(0)
        if waited >= 21:
            sys.exit("[builderbot] ERROR: no build appeared within twenty seconds; "
                     "this project's row on the Docker tab has what happened")
    sys.exit("[builderbot] ERROR: the rebuild is still going after an hour; its row on the Docker tab has it")


def test():
    proj = os.environ["BB_DEV_PROJECT"]
    auth = os.environ["BB_DEV_AUTH"]
    # Two minutes, not the client's default thirty seconds. The controller checks
    # the instance before it answers, and each check is a round trip through the
    # agent to the node; on an unlucky poll cycle that ran past thirty seconds,
    # this gave up saying "timed out", and the controller started the run anyway.
    # So a fifteen-minute suite ran unattended inside the container, its output
    # going to a job nobody was reading, holding the node's one slot, while the
    # caller was told nothing had been timed (B202, four sightings on 21 Sep).
    START_WAIT = 120
    r = bbapi.call("/api/devapp", {"project": proj, "instance": os.environ.get("BB_DEV_INSTANCE", ""),
                                   "container": os.environ.get("BB_DEV_CONTAINER", ""),
                                   "action": "test", "args": sys.argv[2:]}, auth=auth, timeout=START_WAIT)
    if r.get("error"):
        # The one refusal that does not mean nothing happened.
        if "timed out" in str(r["error"]).lower():
            sys.exit(f"[builderbot] ERROR: the controller did not answer within {START_WAIT}s. The run MAY "
                     "HAVE STARTED anyway: `bb jobs` lists a `test` job on this project if it did, "
                     "`bb jobs ID` is its log, and starting another run on top of it breaks both")
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    jid = r.get("job") or ""
    print(f"[builderbot] testing {proj} inside its dev instance ({jid})", file=sys.stderr)
    shown = 0
    for _ in range(3600):
        time.sleep(1)
        j = bbapi.call(f"/api/v1/jobs?id={jid}", auth=auth)
        # A row has an `error` of its own (the sentence the tab shows for how it
        # ended); only an answer with no job in it is the API refusing.
        if j.get("error") and "state" not in j:
            sys.exit(f"[builderbot] ERROR: {j['error']}")
        log = j.get("log") or ""
        if len(log) > shown:
            sys.stdout.write(log[shown:]); sys.stdout.flush(); shown = len(log)
        if j.get("state") in ("succeeded", "failed", "canceled"):
            code = j.get("exit_code")
            if j["state"] == "succeeded":
                sys.exit(0)
            print(f"[builderbot] {j.get('error') or 'the tests failed'} (exit {code})", file=sys.stderr)
            sys.exit(code if isinstance(code, int) and code else 1)
    sys.exit("[builderbot] ERROR: the tests are still going after an hour; the job is on the Jobs tab")


def edit():
    proj, auth = os.environ["BB_DEV_PROJECT"], os.environ["BB_DEV_AUTH"]
    verb, setting = os.environ["BB_DEV_VERB"], os.environ.get("BB_DEV_SET") == "1"
    post = lambda b: bbapi.call("/api/devapp", b | {"project": proj, "instance": os.environ.get("BB_DEV_INSTANCE", ""),  # noqa: E731
                                                    "container": os.environ.get("BB_DEV_CONTAINER", "")}, auth=auth)
    path = os.environ.get("BB_DEV_FILE", "")
    text = open(path, encoding="utf-8").read() if path else None
    if verb == "env" and not setting:
        d = post({"action": "env-get"})
        if d.get("error"):
            sys.exit(f"[builderbot] ERROR: {d['error']}")
        sys.stdout.write(d.get("text") or "")
        if d.get("seeded"):
            print("[builderbot] nothing is stored yet: that is the project's .env.example",
                  file=sys.stderr)
        raise SystemExit(0)
    body = {"action": {"new": "new", "remove": "remove"}.get(verb, "env-set"), "why": os.environ.get("BB_DEV_WHY", "")}
    if text is not None:
        body["text"] = text
    r = post(body)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("id"):
        # On ask: one request, and Allow runs all of it, the build included.
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{r['id']}), waiting up "
              "to 15 minutes for Allow on the dashboard's Docker tab or bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "it was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it would not start'}")
        print("[builderbot] allowed, and removed: its env and data stay for a remake" if verb == "remove"
              else "[builderbot] allowed, and building: bb devapp says how far it got")
        raise SystemExit(0)
    if verb == "remove":
        print("[builderbot] removed" + (": its daemon did not answer, so the row is gone and whatever "
                                        "ran there still runs" if r.get("forgot") else "; its env and data stay for a remake"))
    elif verb == "new" and r.get("needs_ack"):
        print(f"[builderbot] created {r.get('instance') or 'it'}, and it cannot be built from here yet: "
              f"{r['needs_ack']}")
    else:
        print(f"[builderbot] created {r.get('instance') or 'it'}; bb devapp rebuild builds and starts it"
              if verb == "new" else "[builderbot] its env is saved; bb devapp rebuild applies it")


def ls():
    proj = os.environ["BB_DEV_PROJECT"]
    d = bbapi.call("/api/docker?project=" + urllib.parse.quote(proj), auth=os.environ["BB_DEV_AUTH"])
    if d.get("error") and not (d.get("instances") or d.get("containers")):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    blind = bool(d.get("blind"))
    rows = []
    for i in d.get("instances") or []:
        if i.get("owner") != proj:
            continue
        kind = ("written here" if i.get("source") == "file" else
                "its own" if i.get("project") == proj else f"built from {i.get('project')}")
        state = "?" if blind else "running" if i.get("running") else "stopped" if i.get("exists") else "down"
        rows.append((i.get("name") or "", kind, state, " ".join(i.get("ports") or [])))
    for c in d.get("containers") or []:
        if c.get("owner") != proj:
            continue
        rows.append((c.get("name") or c.get("id") or "", "not ours", c.get("state") or "?",
                     " ".join(c.get("ports") or [])))
    if not rows:
        print(f"nothing belongs to {proj} on its node: the operator puts a container under a "
              "project on its row on the Docker tab")
        raise SystemExit(0)
    w = max(len(r[0]) for r in rows)
    for name, kind, state, ports in sorted(rows):
        print(f"  {name:<{w}}  {kind:<14} {state:<8} {ports}".rstrip())
    if blind:
        print("[builderbot] the daemon did not answer, so what is running is not known", file=sys.stderr)
    print("[builderbot] bb devapp log NAME reads one; bb devapp start|stop|restart NAME, and "
          "--container NAME on the other verbs, act on one where the project's settings allow",
          file=sys.stderr)


def ctl():
    auth, verb, name = os.environ["BB_DEV_AUTH"], os.environ["BB_DEV_VERB"], os.environ["BB_DEV_NAME"]
    r = bbapi.call("/api/dockerctl", {"action": "logs" if verb == "log" else verb, "container": name,
                                      "why": os.environ.get("BB_DEV_WHY", "")}, auth=auth)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if verb == "log":
        sys.stdout.write(r.get("text") or "")
        raise SystemExit(0)
    if r.get("id"):
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{r['id']}), waiting up "
              "to 15 minutes for Allow on the dashboard's Docker tab or bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "it was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it did not happen'}")
        print(f"[builderbot] allowed: {o.get('out') or verb}")
        raise SystemExit(0)
    print(f"[builderbot] {r.get('out') or verb}")


VERBS = {"status": status, "rebuild": rebuild, "test": test, "edit": edit, "ls": ls, "ctl": ctl}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
