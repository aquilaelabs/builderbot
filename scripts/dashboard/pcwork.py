"""A person's Windows PC lent to a project (R270 steps 6 and 7): the Windows
companion lends a fixed table of verbs per project, and the project's
sessions ask for them with `bb pc VERB`, under the project's Claude may: Use
a lent PC (deny by default; ask puts each use in front of the person at the
PC; auto runs it). Nothing here is a command string: a verb is a name from
VERBS, and what it runs on the PC (which executable, which build command,
which log) is set in the app by its person, for their own machine.

    editor-start / editor-stop    the project's editor (Unity, Unreal, Godot)
    game-start / game-stop        the project's built game
    build                         the project's Windows build, its log back
    shot                          a picture of the screen, into dist/pc/
    log                           the editor's log, its tail
    editor-call                   one HTTP request to the editor's local
                                  interface (Unreal's Remote Control, a
                                  Unity or Godot bridge), its answer back

The app holds a long poll on the device door (pc-work) for the projects it
lends, runs what it is handed, and posts the result (pc-result). A lend
lapses when the app stops asking, so a PC switched off is not offered. The
paths in what comes back are the project's, not the PC's: the app maps its
folder to /workspace/PROJECT (step 7).
"""
import base64
import secrets
import threading
import time
from pathlib import Path

VERBS = ("editor-start", "editor-stop", "game-start", "game-stop", "build", "shot", "log", "editor-call")
LEND_TTL = 90           # seconds a lend lasts without the app asking again
WAIT_MAX = 25
RESULT_WAIT = 600       # how long a session waits for a verb (a build is long)
SHOT_MAX = 8 << 20
TEXT_MAX = 256 << 10
CALL_METHODS = ("GET", "POST", "PUT", "DELETE")

WORKSPACE = None
mode_of = None          # project -> "deny" | "ask" | "auto" (prefs pc)
notify = None           # (uid, text, level) -> None: onto the person's bell
_cv = threading.Condition()
LENDS = {}              # device id -> {"account", "name", "projects": {project: [verbs]}, "at"}
REQS = {}               # request id -> the request


def configure(*, workspace, mode_fn, notify_fn=None):
    globals().update(WORKSPACE=Path(workspace), mode_of=mode_fn, notify=notify_fn)


def _live(now=None):
    now = now or time.time()
    return {d: l for d, l in LENDS.items() if now - l["at"] < LEND_TTL}


def lend(device, account, name, projects, uid=""):
    """The app says what it lends (each pc-work call): {project: [verbs]},
    cut to the table's verbs."""
    clean = {str(p): [v for v in vs if v in VERBS] for p, vs in (projects or {}).items() if isinstance(vs, list)}
    with _cv:
        LENDS[device] = {"account": account, "uid": uid, "name": name,
                         "projects": {p: v for p, v in clean.items() if v}, "at": time.time()}


def lent(project):
    """What a project's sessions may ask for now: [{device, name, account,
    verbs}], the PCs lending it."""
    with _cv:
        return [{"device": d, "name": l["name"], "account": l["account"], "uid": l.get("uid", ""),
                 "verbs": l["projects"][project]}
                for d, l in _live().items() if project in l["projects"]]


def ask(project, verb, args, why, by):
    """A session's ask: ({id, state}, 200) once handed to a PC, or a refusal.
    The dial decides: deny refuses, ask and auto go to the PC, which asks
    its person on ask."""
    if verb not in VERBS:
        return {"error": f"no such verb: {verb}; one of {', '.join(VERBS)}"}, 400
    mode = mode_of(project) if mode_of else "deny"
    if mode == "deny":
        return {"error": f"{project}'s settings do not let a session use a lent PC (Claude may: Use a lent PC is Deny)"}, 403
    pcs = [p for p in lent(project) if verb in p["verbs"]]
    if not pcs:
        return {"error": f"no PC lends {verb} to {project} now: its person sets it up in the Windows companion, "
                         "which lends it while it runs"}, 409
    a = dict(args or {})
    if verb == "editor-call":
        m = str(a.get("method") or "GET").upper()
        path = str(a.get("path") or "/")
        if m not in CALL_METHODS or not path.startswith("/") or len(path) > 2000:
            return {"error": "editor-call takes a method (GET, POST, PUT, DELETE) and a path starting with /"}, 400
        a = {"method": m, "path": path, "body": str(a.get("body") or "")[:TEXT_MAX]}
    else:
        a = {}
    rid = "pc_" + secrets.token_hex(6)
    req = {"id": rid, "project": project, "verb": verb, "args": a, "why": str(why or "")[:300], "by": by,
           "mode": mode, "device": pcs[0]["device"], "pc": pcs[0]["name"], "state": "waiting",
           "at": int(time.time()), "result": None}
    with _cv:
        REQS[rid] = req
        _cv.notify_all()
    if notify:
        notify(pcs[0]["uid"], f"{by} asked {pcs[0]['name']} to {verb} for {project}"
               + (f": {req['why']}" if req["why"] else ""), "info")
    return {"id": rid, "state": "waiting", "pc": pcs[0]["name"], "mode": mode}, 200


def work(device, wait=0):
    """The PC's long poll: the requests waiting for it, now handed over."""
    end = time.time() + min(float(wait or 0), WAIT_MAX)
    with _cv:
        while True:
            mine = [r for r in REQS.values() if r["device"] == device and r["state"] == "waiting"]
            if mine or time.time() >= end:
                for r in mine:
                    r["state"] = "running"
                return [{k: r[k] for k in ("id", "project", "verb", "args", "why", "by", "mode")} for r in mine]
            _cv.wait(max(0.1, end - time.time()))


def result(device, rid, body):
    """What the PC did: {ok, text?, picture? (base64 png), refused?}. A
    picture lands in the project's dist/pc/ as a capture."""
    with _cv:
        r = REQS.get(str(rid or ""))
        if not r or r["device"] != device:
            return {"error": "no such request for this device"}, 404
    out = {"ok": bool(body.get("ok")), "text": str(body.get("text") or "")[:TEXT_MAX],
           "refused": bool(body.get("refused"))}
    pic = body.get("picture")
    if pic and r["verb"] == "shot":
        try:
            data = base64.b64decode(str(pic), validate=True)
        except ValueError:
            data = b""
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= SHOT_MAX:
            d = WORKSPACE / r["project"] / "dist" / "pc"
            d.mkdir(parents=True, exist_ok=True)
            name = f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
            (d / name).write_bytes(data)
            out["picture"] = f"dist/pc/{name}"
    with _cv:
        r["state"], r["result"] = ("refused" if out["refused"] else "done"), out
        _cv.notify_all()
    return {"ok": True}, 200


def wait_result(project, rid, wait=0):
    """A session's read of its ask, held until the PC answers or `wait`
    runs out: the request, with its result once there is one."""
    end = time.time() + min(float(wait or 0), WAIT_MAX)
    with _cv:
        while True:
            r = REQS.get(str(rid or ""))
            if not r or r["project"] != project:
                return {"error": "no such request for this project"}, 404
            if r["state"] in ("done", "refused") or time.time() >= end:
                if r["state"] == "waiting" and time.time() - r["at"] > RESULT_WAIT:
                    r["state"] = "lapsed"
                return {k: r[k] for k in ("id", "verb", "state", "pc", "result")}, 200
            _cv.wait(max(0.1, end - time.time()))

