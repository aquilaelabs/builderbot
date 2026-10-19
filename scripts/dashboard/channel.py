"""The node agent's channel: the verbs behind /api/v1/agent/ (docs/nodes.md §4).

Four of the six landed in phase 3 (enroll, hello, work, log, result), plus
download, which is how a node gets the agent in the first place and how
self-update fetches the next one. artifact and source are phase 6's, when
there is a workspace to ship and an artifact store to land in.

Out of server.py (R77): the server keeps the HTTP (the token from the
Authorization header, a file streamed, a body read, the long-poll's empty
answer) and calls one function here, which says what the verb means. Each
answers (payload, status), a file as {path or body, ctype, headers}.
"""
import base64
import re

import claudegrant
import db
import ftp
import nodes
import plugins
import runners
import signing
import toolchains
import wssync
import claudesync
import workspace
from fields import field

# The server's, set by configure(): an account's home (home_for).
home_for = None
# Whether dev features are offered (settings' offer_unvetted), set by server.py.
unvetted_ok = lambda: False  # noqa: E731

# The sign jobs a key has been handed to (R106): once per job, so a node
# that asks twice is refused the second time rather than given it again.
_keys_given = set()

# The last fault auto_sysdeps met on each node, by id: hello logs one when
# it changes, not on every poll.
_sysdeps_said = {}


def configure(**deps):
    globals().update(deps)


def _answer(r):
    return r, (400 if r.get("error") else 200)


def _node_only(auth):
    """The refusal for a verb only a node's token may use, or None."""
    if auth.get("error") or auth.get("kind") != "node":
        return {"error": auth.get("error") or "a node's token"}, 401
    return None


# ---- the verbs that serve or take a FILE, on any method ---------------------------

def fetch(verb, auth, q, authed):
    """A file the agent fetches: a job's workspace snapshot (source), a job
    input from the project's dist/ (file), or the agent, the bb bundle or a
    provisioner (download). `authed()` is whether the request also carries
    the operator's own login."""
    if verb == "source":
        # A job's workspace snapshot, by digest (docs/nodes.md §6). The
        # digest is the file name, so nothing else is reachable here.
        if (no := _node_only(auth)):
            return no
        path = workspace.path_for(q.get("digest", [""])[0])
        if path is None:
            return {"error": "no such snapshot: the tree has "
                             "moved on; queue the job again"}, 404
        return {"path": path, "ctype": "application/x-tar", "headers": {}}, 200
    if verb == "file":
        # A job input from the project's dist/, such as the APK an emulator
        # job installs (docs/nodes.md phase 9). Only the job's own node,
        # only while it runs, only dist/.
        if (no := _node_only(auth)):
            return no
        j = nodes.job(q.get("job", [""])[0], with_log=False)
        if not j or j["node"] != auth["node"] or j["state"] not in nodes.JOB_ACTIVE:
            return {"error": "not this node's running job"}, 403
        path = workspace.file_path(j.get("project") or "", q.get("path", [""])[0])
        if path is None:
            return {"error": "no such file in the project's dist/"}, 404
        return {"path": path, "ctype": "application/octet-stream", "headers": {}}, 200
    what = q.get("what", [""])[0]
    if what == "bundle":
        # bb, its library and the catalog, for a node installing a
        # toolchain into its own store (docs/nodes.md §6).
        if (no := _node_only(auth)):
            return no
        b = workspace.bundle()
        return {"body": b["body"], "ctype": "application/x-tar",
                "headers": {"X-Bundle-Digest": b["digest"]}}, 200
    # The file itself. Any token gets it: the provisioner fetches
    # it with the enroll token before there is a node, and so does
    # the operator's own login, for reading it in a browser.
    if auth.get("error") and not authed():
        return {"error": auth["error"]}, 401
    # A Mac is a dev feature until one has been proven end to end (the
    # operator, 12 Oct): its provisioner is served only with Offer dev
    # features on, which is also when the Enroll dialog names it.
    if what == "provisioner-macos" and not unvetted_ok():
        return {"error": "enrolling a Mac is a dev feature: turn on Offer dev features in Settings"}, 404
    if what in ("provisioner", "provisioner-macos"):
        # The provisioner too, from the copy this image carries: the
        # Enroll dialog's command names it, and a machine with an
        # enroll token is what has to get it (B133), a Mac's as well
        # as a Linux machine's (B150).
        p = workspace.REPO / "nodes" / ("provision-macos.sh" if what == "provisioner-macos"
                                        else "provision-linux.sh")
        body = p.read_bytes() if p.is_file() else b""
        if not body:
            return {"error": "this controller ships no provisioner"}, 404
        return {"body": body, "ctype": "text/x-shellscript; charset=utf-8", "headers": {}}, 200
    f = nodes.agent_file()
    if not f["body"]:
        return {"error": "this controller ships no agent"}, 404
    return {"body": f["body"], "ctype": "text/x-python; charset=utf-8",
            "headers": {"X-Agent-Digest": f["digest"]}}, 200


def artifact(auth, q, stream, length):
    """A file a job produced, raw in the body: into the project's dist/ with
    its provenance beside it. Only the job's own node, only while the job
    runs; a result already posted closes it."""
    if (no := _node_only(auth)):
        return no
    j = nodes.job(q.get("job", [""])[0], with_log=False)
    if not j or j["node"] != auth["node"]:
        return {"error": "not this node's job"}, 403
    if j["state"] not in nodes.JOB_ACTIVE:
        return {"error": "the job has ended"}, 409
    # A signed build says what signed it (R106 step 4): the route, the
    # certificate the node verified, and the schemes that verified. Only a
    # sign job's, and only in the shape it can have.
    extra = {}
    if j.get("type") == "sign":
        cert = q.get("cert", [""])[0].upper()
        schemes = q.get("schemes", [""])[0]
        route = q.get("signed", [""])[0]
        key = q.get("key", [""])[0] or signing.DEFAULT
        if re.fullmatch(r"[0-9A-F]{64}", cert) and route in ("play", "sideload") \
                and re.fullmatch(r"[a-z0-9.,]{0,40}", schemes) and signing.KEY_NAME.fullmatch(key):
            extra = {"signed": {"route": route, "cert": cert, "key": key,
                                "schemes": [x for x in schemes.split(",") if x],
                                "from": str((j.get("spec") or {}).get("file") or "")}}
            rotated = q.get("rotated", [""])[0]
            if rotated and signing.KEY_NAME.fullmatch(rotated):
                extra["signed"]["rotated_from"] = rotated
    r = workspace.artifact_put(j, q.get("name", [""])[0], stream, length, extra=extra)
    if not r.get("error"):
        db.audit(auth["principal"], "artifact", j["id"],
                 {"path": r["path"], "sha256": r["sha256"]})
    return _answer(r)


# ---- the node's own verbs, behind its token ---------------------------------------

# ---- a node's projects as a synced copy (R162, wssync.py) -------------------------

def sync_file(auth, q):
    """One file of a synced project, for the node's copy."""
    if (no := _node_only(auth)):
        return no
    path, no = wssync.file_path(auth["node"], q.get("project", [""])[0], q.get("path", [""])[0])
    if no:
        return no
    return {"path": path, "ctype": "application/octet-stream", "headers": {}}, 200


def sync_tar(auth, q):
    """A synced project whole, as a tar stream, for a node's first copy."""
    if (no := _node_only(auth)):
        return no
    write, no = wssync.tar_writer(auth["node"], q.get("project", [""])[0])
    if no:
        return no
    return {"stream": write, "ctype": "application/x-tar", "headers": {}}, 200


def sync_put(auth, q, stream, length):
    """One file the node changed, raw in the body."""
    if (no := _node_only(auth)):
        return no
    return wssync.put(auth["node"], q.get("project", [""])[0], q, stream, length)


# ---- a synced node's Claude conversations (B613, claudesync.py) -----------------

def claude_file(auth, q):
    """One of an account's transcript files, for a synced node's copy."""
    if (no := _node_only(auth)):
        return no
    path, no = claudesync.file_path(auth["node"], q.get("uid", [""])[0], q.get("path", [""])[0])
    if no:
        return no
    return {"path": path, "ctype": "application/octet-stream", "headers": {}}, 200


def claude_put(auth, q, stream, length):
    """One transcript file the node wrote: whole, its new tail, or gone."""
    if (no := _node_only(auth)):
        return no
    return claudesync.put(auth["node"], q, stream, length)


# ---- an image shipped between two nodes (R166, devactions.py) -------------------

def devimage_put(auth, q, stream, length):
    """The build node's saved image, raw in the body, for its shipping job."""
    if (no := _node_only(auth)):
        return no
    import devactions
    return devactions.image_put(auth["node"], q, stream, length)


def devdata_put(auth, q, stream, length):
    """A copied or moved instance's packed data, from its old node's job."""
    if (no := _node_only(auth)):
        return no
    import relocate
    return relocate.data_put(auth["node"], q, stream, length)


def devdata_file(auth, q):
    """That data, for the new node's unpacking job."""
    if (no := _node_only(auth)):
        return no
    import relocate
    path, no = relocate.data_path(auth["node"], q)
    if no:
        return no
    return {"path": path, "ctype": "application/x-tar", "headers": {}}, 200


def devimage_file(auth, q):
    """That image, for the instance node's loading job."""
    if (no := _node_only(auth)):
        return no
    import devactions
    path, no = devactions.image_path(auth["node"], q)
    if no:
        return no
    return {"path": path, "ctype": "application/x-tar", "headers": {}}, 200


def _sync(nid, req):
    act = field(req, "action")
    project = field(req, "project")
    if act == "projects":
        return wssync.projects(nid), 200
    if act == "state":
        return wssync.state(nid, project)
    if act == "since":
        return wssync.since(nid, project, req.get("rev"))
    return {"error": f"no such sync action: {act}"}, 400


def verb(name, auth, req, addr):
    """Enrollment with an enroll token, and a node's own verbs with its
    token: its runner's token, hello, its sessions, a job's log and its
    result. `addr` is where the node is, as seen from here. The long-poll
    is work()'s."""
    if name == "enroll":
        if auth["kind"] != "enroll":
            return {"error": "an enrollment token is needed "
                             "here, not a node's"}, 403
        return _answer(nodes.enroll(auth, req.get("census"), addr,
                                    field(req, "version"), field(req, "digest"),
                                    field(req, "user")))
    if auth["kind"] != "node":
        return {"error": "an enrollment token enrolls, and "
                         "nothing else"}, 403
    nid = auth["node"]
    if name == "sync":
        return _sync(nid, req)
    if name == "claude":
        # What the controller has of the transcripts of the projects this
        # node holds, for its mirror to compare (B613).
        return claudesync.listing(nid), 200
    if name == "runner-token":
        # A registration or removal token for the node's runner, minted
        # now from the root-only stash and never stored: the PAT stays
        # here, the hour-long token goes to the node that asked.
        kind = "remove" if field(req, "kind") == "remove" else "registration"
        slot = re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60]
        r = runners.mint(kind, nid, slot, field(req, "runner_id"))
        db.audit(auth["principal"], "runner-token", nid, {"kind": kind, "ok": not r.get("error")})
        return _answer(r)
    if name == "signing-key":
        # A project's signing key for the sign job running on this node
        # (R106): only that job's own node, only while it runs, once. The
        # spec names the route and never carries a secret, so a session
        # reading the job sees which key and not the key.
        j = nodes.job(field(req, "job"), with_log=False)
        if not j or j.get("type") != "sign" or j["node"] != nid or j["state"] not in nodes.JOB_ACTIVE:
            return {"error": "not this node's running sign job"}, 403
        if j["id"] in _keys_given:
            return {"error": "the key was handed to this job already"}, 409
        spec = j.get("spec") or {}
        route = str(spec.get("route") or "")
        project = j.get("project") or ""
        # Which key: the one the job names, else the one the build's package
        # is mapped to, which the node read from the build (step 6), else
        # the project's default.
        package = field(req, "package")
        key = str(spec.get("key") or "") or signing.key_for(project, package, route)
        # A retired sideload key signs nothing alone: its builds go out with
        # the key it was rotated to and the proof (R106 step 7).
        if route == "sideload":
            key = signing.successor(project, key)
        got = signing.secret(project, route, key)
        if not got:
            return {"error": f"{project} has no {signing.WORDS.get(route, route)} named {key}"
                             + (f" (what {package} is mapped to)" if package and not spec.get("key") else "")}, 404
        blob, rec = got
        _keys_given.add(j["id"])
        db.audit(auth["principal"], "signing-key", j["id"],
                 {"project": project, "route": route, "key": key, "package": package,
                  "sha256": rec.get("sha256")})
        out = {"keystore": base64.b64encode(blob).decode(), "alias": rec.get("alias"),
               "type": rec.get("type"), "store_pass": rec.get("store_pass"), "key": key,
               "key_pass": rec.get("key_pass"), "sha256": rec.get("sha256")}
        if route == "sideload" and rec.get("rotated_from"):
            prev = signing.secret(project, route, rec["rotated_from"])
            proof = signing.lineage(project, key)
            if prev and proof:
                out["previous"] = {"keystore": base64.b64encode(prev[0]).decode(), "alias": prev[1].get("alias"),
                                   "store_pass": prev[1].get("store_pass"), "key_pass": prev[1].get("key_pass"),
                                   "key": rec["rotated_from"], "sha256": prev[1].get("sha256")}
                out["lineage"] = base64.b64encode(proof).decode()
        return out, 200
    if name == "hello":
        r = nodes.hello(nid, req.get("census"), addr,
                        field(req, "version"), field(req, "digest"),
                        req.get("running"), keep=req.get("keep"))
        # A managed node whose store holds a toolchain it lacks the
        # system libraries for installs them itself (toolchains.py).
        # Broad because this rides every hello, and a fault in the
        # housekeeping must not put every node offline; said once per
        # node per message, so the log names it without repeating it.
        try:
            toolchains.auto_sysdeps(nid)
        except Exception as e:                      # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if _sysdeps_said.get(nid) != msg:
                _sysdeps_said[nid] = msg
                print(f"[dashboard] auto sysdeps on {nid} skipped: {msg}", flush=True)
        return _answer(r)
    if name == "beat":
        # Alive, while its loop is held by a census (nodes.beat).
        nodes.beat(nid)
        return {"ok": True}, 200
    if name == "ftp-auth":
        # One FTP login on this node's bb-ftpd (R151), relayed by its agent:
        # the name and password checked as a sign-in checks them, and the
        # access this project gives that account. Never kept.
        return ftp.login(nid, field(req, "project"), req.get("user"), req.get("password"),
                         field(req, "addr")), 200
    if name == "ftp":
        # What the node's servers are doing, after each change.
        return ftp.report(nid, req.get("servers"))
    if name == "sessions":
        # The node's sessions as they are now, sent when one changed
        # rather than on the poll's turn.
        return _answer(nodes.sessions_report(nid, req.get("sessions")))
    if name == "log":
        return _answer(nodes.job_log(nid, field(req, "job"), req.get("chunks"), req.get("step")))
    if name == "result":
        return _answer(nodes.job_result(nid, field(req, "job"), field(req, "state"),
                                        req.get("exit"), field(req, "error"),
                                        req.get("outputs")))
    return {"error": "not found"}, 404


def work(auth, req, addr, alive):
    """The heartbeat and the long-poll in one: the sample is recorded first,
    so a node that is only ever waiting still reads as alive and its
    numbers still move; then the request is held until a job is there for
    this node, or the wait runs out, or `alive()` says the node hung up.
    (job, 200), None for nothing to do, or a refusal and its status."""
    if auth["kind"] != "node":
        return {"error": "an enrollment token enrolls, and "
                         "nothing else"}, 403
    nid = auth["node"]
    nodes.heartbeat(nid, req.get("sample"), addr, req.get("running"))
    logins = req["sample"].get("logins") if isinstance(req.get("sample"), dict) else None
    _logins(nid, logins)
    # ...and the Claude plugins each account there installed, which
    # ride the same rows (plugins.py).
    plugins.report(nid, logins)
    try:
        wait = min(nodes.POLL_S, max(0.0, float(req.get("wait", nodes.POLL_S))))
    except (TypeError, ValueError):
        wait = nodes.POLL_S
    j = nodes.job_next(nid, wait, runner="node", alive=alive)
    return None if j is None else (j, 200)


def _logins(nid, rows):
    """What a node's agent says each account on it is signed in to Claude
    as (B104). Absent from most heartbeats, and then nothing happens.

    This is the report that does not come from a session's own token, and
    it is worth being clear about what that means: a node could name an
    account and an email that are not so. It could also read every
    session's token and run as those accounts, because it runs them, so
    the weakening is small, and what it buys is a row that is true when
    nothing is running: a sign-in or a sign-out made there shows without a
    session having to open first.

    Written only when it says something new, because a heartbeat must not
    cost a write per node per poll.
    """
    if not isinstance(rows, list):
        return
    for r in rows[:64]:
        if not isinstance(r, dict):
            continue
        uid = str(r.get("uid") or "")
        if not re.fullmatch(r"u_[0-9a-f]{8}", uid):
            continue
        home = home_for(uid)
        if not home:
            continue
        email = " ".join(str(r.get("email") or "").split())[:120]
        on = claudegrant.on(home, nid)
        if email:
            if on.get("email") == email:
                continue                       # already what we have
            claudegrant.report(home, nid, email, str(r.get("plan") or ""))
        elif on:
            claudegrant.report(home, nid, "", signed_in=False)
