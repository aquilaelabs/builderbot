"""Behind `bb devapp` (cmd_devapp in bb): this project's dev instance, and what
a session may be given over it under the project's one setting (Claude may:
Run its container). Everything here goes through the controller's API like
`bb root` and `bb phone`, because the daemon is the controller's connection
to the node; nothing runs docker anywhere.

The first argument is the verb: status, rebuild, new, test (the test
command's arguments after it), edit (env and remove, which BB_DEV_VERB
names), ls, or ctl (log, start, stop and restart, which BB_DEV_VERB names).
BB_DEV_AUTH is the auth header, BB_DEV_PROJECT the project, BB_DEV_INSTANCE
and BB_DEV_CONTAINER which of its containers, BB_DEV_WHY the reason a person
reads, BB_DEV_FILE and BB_DEV_SET the env file and whether it is being set,
BB_DEV_REF the branch a new container builds from, BB_DEV_NAME the container
a ctl verb acts on.
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
        print("no compose file at this project's root (docker-compose.yml or compose.yml), so there is "
              "no dev instance: with one there, bb devapp new builds it from this tree")
        raise SystemExit(0)
    print(f"  {'instance':<12} {st.get('name') or '-'}")
    print(f"  {'running':<12} {'yes' if st.get('running') else 'no'}")
    print(f"  {'daemon':<12} " + ("answering" if st.get("available")
                                  else (st.get("why") or "not reachable")))
    if st.get("built_rev"):
        print(f"  {'built from':<12} {st['built_rev']}")
    elif st.get("needs_build"):
        print(f"  {'built from':<12} nothing here yet")
    if st.get("running"):
        _answers_at(st.get("name") or "")
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


def _answers_at(name):
    """Where a running instance answers, said with its status. A session
    has a network of its own, so localhost and the machine's address there
    are the session's and nothing of the node's: one that asked 127.0.0.1
    for its containers was refused, took them for down, and could not say
    so anywhere (29 Sep). Best effort: the list is the node's to give, and
    a node that is slow with it costs this one line."""
    try:
        d = bbapi.call("/api/docker?project=" + urllib.parse.quote(os.environ["BB_DEV_PROJECT"]),
                       auth=os.environ["BB_DEV_AUTH"], timeout=60)
    except Exception:                                   # noqa: BLE001
        return
    row = next((i for i in (d.get("instances") or []) if i.get("name") == name), None) \
        if isinstance(d, dict) else None
    url = ((row or {}).get("route") or {}).get("url") or ""
    if not url:
        if row is not None and not row.get("ports"):
            print(f"  {'answers at':<12} nowhere: its compose file publishes no port")
        return
    host = urllib.parse.urlsplit(url).hostname or ""
    others = [p.split("->")[0].rsplit(":", 1)[-1] for p in (row.get("ports") or [])]
    others = [p for p in others if p.isdigit() and f":{p}/" not in url and not url.endswith(f":{p}")]
    print(f"  {'answers at':<12} {url}" + (f" (and on {host}: " + ", ".join(others) + ")" if others else ""))
    print(f"  {'':<12} from a session too: localhost here is the session's own, never the node's")


def _client(instance=None):
    """post and look for one of this project's containers: the one
    BB_DEV_INSTANCE or BB_DEV_CONTAINER names, or `instance` when given (a
    container `new` just made)."""
    proj, auth = os.environ["BB_DEV_PROJECT"], os.environ["BB_DEV_AUTH"]
    which = ({"instance": os.environ.get("BB_DEV_INSTANCE", ""),
              "container": os.environ.get("BB_DEV_CONTAINER", "")}
             if instance is None else {"instance": instance, "container": ""})

    def post(b, timeout=30):
        return bbapi.call("/api/devapp", b | {"project": proj} | which, auth=auth, timeout=timeout)

    def look(patient=False):
        # `state` parses the compose on the instance's node, which on a slow
        # node is longer than one request's thirty seconds; this verb said
        # "timed out" and stopped while the rebuild went on to succeed
        # (B266). Given the time, and in the poll a slow look is a look to
        # try again rather than the verb's last word.
        d = post({"action": "state"}, timeout=180)
        if d.get("error"):
            if patient and "timed out" in str(d["error"]).lower():
                return None
            sys.exit(f"[builderbot] ERROR: {d['error']}")
        return d.get("state") if isinstance(d.get("state"), dict) else d

    return post, look


def rebuild():
    auth = os.environ["BB_DEV_AUTH"]
    post, look = _client()
    # What it was built from before, because that is the only signal that says a
    # build HAPPENED. A job that succeeded is not news to the row (job_view
    # returns nothing for one), so "no job running" reads the same three seconds
    # before it starts and the moment after it finishes, and taking either for
    # success is how this said "rebuilt" over a build that had not begun.
    was = (look().get("built_rev") or "")
    # As patient as the look: the controller checks the instance on its node
    # before it answers, and on a slow round trip there the default thirty
    # seconds ran out while the build went ahead (B298).
    r = post({"action": "rebuild", "why": os.environ.get("BB_DEV_WHY", "")}, timeout=180)
    if r.get("error") and "timed out" in str(r["error"]).lower():
        # Not a refusal: the request reached the controller, which may have
        # started the build before this stopped waiting for its answer. The
        # poll below reports the build, or says that none appeared.
        print("[builderbot] the controller has not answered the rebuild in three minutes; "
              "it may have started it, so this watches for the build", file=sys.stderr)
        r = {}
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
        r = {"job": o.get("out")}
    _watch(look, was, auth, r.get("job") or "")


def _watch(look, was, auth, job_id=""):
    """Follow a build that has been asked for to its verdict: the step while
    it runs, then built, failed, or that none appeared. `was` is what the
    container was built from before, "" for one never built. `job_id` is
    the build's job when the answer named one, and is what is followed
    then: the row alone missed a rebuild of an unchanged commit that ended
    between two looks, since it saw neither a running job nor a new
    revision, and said no build appeared over one that had (B312)."""
    what = "rebuild" if was else "build"
    print(f"[builderbot] {what}ing; it runs on the node's daemon and takes minutes",
          file=sys.stderr)
    # Polled rather than streamed: the job's log belongs to the row, and what a
    # session needs is the step while it waits and the verdict at the end. A
    # build that pulls can take half an hour, which is the cap here.
    last, seen, waited = "", False, 0.0
    while waited < 3600:
        time.sleep(3)
        waited += 3
        if job_id:
            j = bbapi.call(f"/api/v1/jobs?id={job_id}", auth=auth)
            if j.get("error") and "state" not in j:
                sys.exit(f"[builderbot] ERROR: {j['error']}")
            step = str(j.get("step") or "")
            if step and step != last:
                print(f"  {step}", file=sys.stderr)
                last = step
            if j.get("state") not in ("succeeded", "failed", "canceled"):
                continue
            if j["state"] != "succeeded":
                tail = str(j.get("log") or "")[-1200:]
                if tail:
                    print(tail)
                sys.exit(f"[builderbot] ERROR: the {what} {j['state']}: {str(j.get('error') or '')[:200]}")
            seen, job_id = True, ""
        st = look(patient=True)
        if st is None:
            continue
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
            sys.exit(f"[builderbot] ERROR: the {what} failed: {str(job['error'])[:200]}")
        if seen or (st.get("built_rev") or "") != was:
            print(f"[builderbot] {'rebuilt' if was else 'built'} {st.get('built_rev') or ''}; "
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
    sys.exit(f"[builderbot] ERROR: the {what} is still going after an hour; its row on the Docker tab has it")


def new():
    """This project sent to Docker, the way the Artifacts tab's Send does: a
    container made from its own compose file on its own node, then built and
    started, with this waiting for the verdict. BB_DEV_INSTANCE names it;
    unnamed, the controller gives it the project's own name while it has
    none and one beside it after. BB_DEV_REF pins the branch it builds from
    and BB_DEV_FILE is its env. On `ask` one request carries all of it and
    Allow makes and builds it; on `auto` it is made, then built as `bb
    devapp rebuild` builds."""
    auth = os.environ["BB_DEV_AUTH"]
    post, _ = _client()
    body = {"action": "new", "why": os.environ.get("BB_DEV_WHY", ""),
            "ref": os.environ.get("BB_DEV_REF", "")}
    path = os.environ.get("BB_DEV_FILE", "")
    if path:
        body["text"] = open(path, encoding="utf-8").read()
    r = post(body)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    inst = r.get("instance") or ""
    name = r.get("name") or inst
    if r.get("id"):
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{r['id']}) to send it to "
              f"Docker as {name}, waiting up to 15 minutes for Allow on the dashboard's Docker tab "
              "or bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "it was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it would not start'}")
        _watch(_client(inst)[1], "", auth, str(o.get("out") or ""))
        return
    print(f"[builderbot] created {name}", file=sys.stderr)
    # The rebuild verb as it is, aimed at the container just made: the same
    # request, the same patience with a slow controller and the same watch.
    os.environ["BB_DEV_INSTANCE"], os.environ["BB_DEV_CONTAINER"] = inst, ""
    rebuild()


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
        # Ended with a newline whatever was stored, so a line appended to
        # this output stands on its own (B314).
        text = d.get("text") or ""
        sys.stdout.write(text if not text or text.endswith("\n") else text + "\n")
        if d.get("seeded"):
            print("[builderbot] nothing is stored yet: that is the project's .env.example",
                  file=sys.stderr)
        raise SystemExit(0)
    body = {"action": "remove" if verb == "remove" else "env-set", "why": os.environ.get("BB_DEV_WHY", "")}
    if text is not None:
        body["text"] = text
    r = post(body)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("id"):
        # On ask: Allow removes it, or writes the env and builds nothing,
        # since the card said env set and the rebuild is the next ask.
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{r['id']}), waiting up "
              "to 15 minutes for Allow on the dashboard's Docker tab or bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "it was not allowed")
        if o.get("code"):
            sys.exit(f"[builderbot] ERROR: {o.get('out') or 'it would not start'}")
        print("[builderbot] allowed, and removed: its env and data stay for a remake" if verb == "remove"
              else "[builderbot] allowed, and its env is saved; bb devapp rebuild applies it")
        raise SystemExit(0)
    if verb == "remove":
        print("[builderbot] removed" + (": its daemon did not answer, so the row is gone and whatever "
                                        "ran there still runs" if r.get("forgot") else "; its env and data stay for a remake"))
    else:
        print("[builderbot] its env is saved; bb devapp rebuild applies it")


def ls():
    proj = os.environ["BB_DEV_PROJECT"]
    # The listing is a read on the node, which right after a build starts
    # there took longer than the client's thirty seconds and stopped with
    # "timed out" (B310): the look's patience, and a timeout that names the
    # reason rather than the clock.
    d = bbapi.call("/api/docker?project=" + urllib.parse.quote(proj), auth=os.environ["BB_DEV_AUTH"],
                   timeout=180)
    if d.get("error") and not (d.get("instances") or d.get("containers")):
        if "timed out" in str(d["error"]).lower():
            sys.exit("[builderbot] ERROR: the node did not list its containers in three minutes; "
                     "a build just started there is the usual reason, and bb jobs says whether one "
                     "is running. Try again when it is done")
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


VERBS = {"status": status, "rebuild": rebuild, "new": new, "test": test, "edit": edit, "ls": ls, "ctl": ctl}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
