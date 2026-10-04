"""A real phone lent to a project (R113): its owner lends the phone connected on
a node to one project on that node for a while, and that project's sessions
see and drive the project's own app on it, the way they do the emulator, with
no ask per command.

What a lease allows is the project's app and nothing else, so lending the
phone is not handing over the phone:

    install   one of the project's own builds from its dist/; the package it
              carries joins the lease's packages
    start / stop   a package of the lease's
    ime       pick a lease package's keyboard as the input method
    touch     tap, swipe, a timed glide, text and a few keys, only while one
              of the lease's packages is in front or is the keyboard
    ui        the screen's layout (uiautomator), under the same condition
    log       a lease package's logcat
    shot / record   the screen, into the project's dist/phone/ as a capture

Anything else (another app, Settings, a shell) is still `bb phone run --why`,
which asks the owner one command at a time, as before.

Everything runs over adb from the node (phone._adb, a node job), never on the
phone's side: the companion app gains no permission for this, so it looks to
Play Protect exactly as it did. A lease ends by itself when its time is up,
when the phone is disconnected, and when the owner takes it back.
"""
import base64
import re
import shlex
import time
from pathlib import Path

import phone

WORKSPACE = None
project_node = None     # project -> its node id (server.py sets it)
may_see = None          # (who, project) -> bool

HOURS = (1, 4, 0)       # 0 is until taken back
MAX_PKGS = 8
RECORD_MAX = 30
KEYS = {"back": "KEYCODE_BACK", "enter": "KEYCODE_ENTER", "del": "KEYCODE_DEL",
        "tab": "KEYCODE_TAB", "space": "KEYCODE_SPACE", "up": "KEYCODE_DPAD_UP",
        "down": "KEYCODE_DPAD_DOWN", "left": "KEYCODE_DPAD_LEFT", "right": "KEYCODE_DPAD_RIGHT",
        "escape": "KEYCODE_ESCAPE"}
PKG = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


def configure(*, workspace, project_node_fn, may_see_fn):
    globals().update(WORKSPACE=Path(workspace), project_node=project_node_fn, may_see=may_see_fn)


# ---- the lease ------------------------------------------------------------------

def lease(nid):
    """The phone on this node's lease, or None; an expired one is ended here."""
    rec = phone._rec(nid) if nid else None
    got = (rec or {}).get("lease")
    if not isinstance(got, dict):
        return None
    if got.get("until") and time.time() > got["until"]:
        rec.pop("lease", None)
        phone._put(nid, rec)
        return None
    return got


def leased_to(project):
    """(node id, lease) for the phone lent to this project, or (node id, None)."""
    nid = project_node(project) if project_node else ""
    got = lease(nid) if nid else None
    return nid, (got if got and got.get("project") == project else None)


def lend(nid, who, project, hours):
    """The owner lends the phone on `nid` to `project` for `hours` (0: until
    taken back). The project must be on that node, since its sessions reach
    the phone through it, and one the owner works on."""
    uid = phone.users.uid_of(who)
    rec = phone._rec(nid)
    if not rec or rec.get("owner") != uid:
        return {"error": "only the account that connected this phone lends it"}
    if not phone.phone_on(nid):
        return {"error": "no phone is connected on this node"}
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = -1
    if hours not in HOURS:
        return {"error": "lend it for 1 or 4 hours, or until you take it back"}
    if not project or (may_see and not may_see(who, project)):
        return {"error": f"not a project of yours: {project}"}
    if project_node(project) != nid:
        return {"error": f"{project} runs on another node, so its sessions cannot reach this phone"}
    now = int(time.time())
    rec["lease"] = {"project": project, "at": now, "until": now + hours * 3600 if hours else 0,
                    "by": uid, "by_name": who.get("name") or "", "pkgs": []}
    phone._put(nid, rec)
    return {"ok": True, "lease": rec["lease"]}


def view(nid):
    """The lease as the Phone tab shows it: who has it, for how long, its
    apps, and the newest screenshot a session took of it."""
    got = lease(nid)
    if not got:
        return None
    shots = sorted((WORKSPACE / got["project"] / "dist" / "phone").glob("shot-*.png"))
    return dict(got, left=int(got["until"] - time.time()) if got.get("until") else None,
                shot=f"dist/phone/{shots[-1].name}" if shots else "")


def rev():
    """What the Phone tab watches to show a lent phone live: the lease record
    and the newest screenshot of each project a phone is lent to, by mtime,
    so a session's shot reaches the owner's tab on the next poll. Stats only."""
    try:
        d = phone.load()
    except Exception:  # noqa: BLE001 (a poll never fails over this)
        return ""
    out = []
    for nid, rec in sorted((d.get("nodes") or {}).items()):
        got = (rec or {}).get("lease") if isinstance(rec, dict) else None
        if not isinstance(got, dict):
            continue
        p = WORKSPACE / str(got.get("project") or "_") / "dist" / "phone"
        try:
            m = int(p.stat().st_mtime)
        except OSError:
            m = 0
        out.append(f"{nid}:{got.get('project')}:{got.get('at')}:{len(got.get('pkgs') or [])}:{m}")
    return ",".join(out)


def take_back(nid, who, admin=False):
    rec = phone._rec(nid)
    if not rec or not rec.get("lease"):
        return {"ok": True}
    if rec.get("owner") != phone.users.uid_of(who) and not admin:
        return {"error": "only the phone's owner, or an administrator, takes it back"}
    rec.pop("lease", None)
    phone._put(nid, rec)
    return {"ok": True}


def _add_pkg(nid, pkg):
    rec = phone._rec(nid)
    got = (rec or {}).get("lease")
    if not got:
        return
    pkgs = [p for p in got.get("pkgs") or [] if p != pkg]
    got["pkgs"] = ([pkg] + pkgs)[:MAX_PKGS]
    phone._put(nid, rec)


# ---- what a session does with it ----------------------------------------------

def _shell(nid, serial, script, project, timeout=60):
    """One shell line on the phone, through the node's adb."""
    return phone._adb(nid, "-s", serial, "shell", script, timeout=timeout,
                      by=f"session:{project}", probe=True)


def _ours_in_front(pkgs):
    """A shell test that passes when one of `pkgs` is the window in front or
    the input method: a session testing its keyboard types into another app,
    which is the point of a keyboard."""
    pats = "|".join(f"*{p}/*" for p in pkgs) or "*bb-none/*"
    return ('f=$(dumpsys window | grep -m1 mCurrentFocus); '
            'i=$(settings get secure default_input_method); '
            f'case "$f $i" in {pats}) ;; *) echo "bb-not-yours: $f"; exit 3;; esac; ')


def _capture(project, kind, ext, data):
    out = WORKSPACE / project / "dist" / "phone"
    out.mkdir(parents=True, exist_ok=True)
    name = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"
    (out / name).write_bytes(data)
    return f"dist/phone/{name}"


def _b64(out):
    blob = "".join(x.strip() for x in out.splitlines() if re.fullmatch(r"[A-Za-z0-9+/=]+", x.strip()))
    return base64.b64decode(blob) if blob else b""


def use(project, op, args):
    """A session's verb on the phone lent to its project. (payload, status)."""
    args = args if isinstance(args, dict) else {}
    nid, got = leased_to(project)
    if not got:
        return {"error": f"no phone is lent to {project}: its owner lends one from the Phone tab, on its node, "
                         "and bb phone run --why asks for one command meanwhile"}, 403
    dev = phone.phone_on(nid)
    if not dev:
        return {"error": "the lent phone is not connected right now"}, 409
    serial, pkgs = dev["serial"], list(got.get("pkgs") or [])
    left = int(got["until"] - time.time()) if got.get("until") else None
    if op == "status":
        return {"project": project, "model": dev.get("model") or "phone", "pkgs": pkgs,
                "by": got.get("by_name"), "left": left}, 200
    if op == "shot":
        r = _shell(nid, serial, "screencap -p | base64 -w 0", project, timeout=90)
        data = _b64(r["out"])
        if r["code"] or not data.startswith(b"\x89PNG"):
            return {"error": "the phone gave no screenshot: " + r["out"][-200:]}, 502
        return {"path": _capture(project, "shot", "png", data)}, 200
    if op == "record":
        try:
            secs = max(1, min(RECORD_MAX, int(args.get("seconds") or 10)))
        except (TypeError, ValueError):
            secs = 10
        f = "/data/local/tmp/bb-record.mp4"
        r = _shell(nid, serial, f"screenrecord --time-limit {secs} --bit-rate 4000000 {f} && "
                                f"base64 -w 0 {f}; rm -f {f}", project, timeout=secs + 120)
        data = _b64(r["out"])
        if r["code"] or len(data) < 1000:
            return {"error": "the phone gave no recording: " + r["out"][-200:]}, 502
        return {"path": _capture(project, "record", "mp4", data)}, 200
    if op == "install":
        return _install(project, nid, serial, str(args.get("file") or ""))
    pkg = str(args.get("pkg") or (pkgs[0] if pkgs else ""))
    if op in ("start", "stop", "ime", "log"):
        if pkg not in pkgs:
            return {"error": f"{pkg or 'that'} is not one of this lease's apps: install the build "
                             "with bb phone install first" + (f" (it has {', '.join(pkgs)})" if pkgs else "")}, 403
        q = shlex.quote(pkg)
        if op == "start":
            r = _shell(nid, serial, f"monkey -p {q} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 "
                                    f"&& echo started {q}", project)
        elif op == "stop":
            r = _shell(nid, serial, f"am force-stop {q} && echo stopped {q}", project)
        elif op == "ime":
            r = _shell(nid, serial, f"s=$(ime list -a -s | grep -m1 '^{pkg}/'); "
                                    '[ -n "$s" ] || { echo "no keyboard in that app"; exit 4; }; '
                                    'ime enable "$s" && ime set "$s"', project)
        else:
            try:
                n = max(50, min(5000, int(args.get("lines") or 500)))
            except (TypeError, ValueError):
                n = 500
            r = _shell(nid, serial, f"p=$(pidof -s {q}); [ -n \"$p\" ] || {{ echo '{pkg} is not running'; exit 4; }}; "
                                    f"logcat -d -t {n} --pid=$p", project, timeout=90)
        return {"code": r["code"], "out": r["out"]}, 200
    if op in ("touch", "ui"):
        guard = _ours_in_front(pkgs)
        if op == "ui":
            r = _shell(nid, serial, guard + "uiautomator dump /data/local/tmp/bb-ui.xml >/dev/null "
                                    "&& cat /data/local/tmp/bb-ui.xml", project, timeout=90)
        else:
            cmd = _touch(args)
            if isinstance(cmd, dict):
                return cmd, 400
            r = _shell(nid, serial, guard + cmd, project)
        if "bb-not-yours" in r["out"]:
            return {"error": "none of this lease's apps is in front or is the keyboard, so the phone is "
                             "not touched: bb phone start PKG first (" + r["out"].strip()[-160:] + ")"}, 409
        return {"code": r["code"], "out": r["out"]}, 200
    return {"error": f"unknown: {op}"}, 400


def _num(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 20000 else None


def _touch(a):
    """The input line for a touch, from checked numbers and words only."""
    kind = str(a.get("kind") or "")
    if kind == "tap":
        x, y = _num(a.get("x")), _num(a.get("y"))
        if x is None or y is None:
            return {"error": "tap X Y, in screen pixels"}
        return f"input tap {x} {y}"
    if kind == "hold":
        x, y, ms = _num(a.get("x")), _num(a.get("y")), _num(a.get("ms") or 600)
        if None in (x, y, ms):
            return {"error": "hold X Y --ms N"}
        return f"input swipe {x} {y} {x} {y} {ms}"
    if kind == "glide":
        pts = a.get("points") if isinstance(a.get("points"), list) else []
        nums = [_num(v) for v in pts]
        if len(nums) < 4 or len(nums) % 2 or None in nums or len(nums) > 200:
            return {"error": "glide X Y X Y..., at least two points"}
        step = _num(a.get("ms") or 40)
        if step is None or step > 2000:
            return {"error": "--ms is the time between points, at most 2000"}
        xy = list(zip(nums[0::2], nums[1::2], strict=True))
        pause = f"sleep {step / 1000:.3f}; "
        line = f"input motionevent DOWN {xy[0][0]} {xy[0][1]}; "
        for x, y in xy[1:]:
            line += pause + f"input motionevent MOVE {x} {y}; "
        return line + f"input motionevent UP {xy[-1][0]} {xy[-1][1]}"
    if kind == "text":
        t = str(a.get("text") or "")
        if not t or len(t) > 500:
            return {"error": "text needs 1 to 500 characters"}
        # input text takes %s for a space and the rest quoted for the shell.
        return "input text " + shlex.quote(t.replace(" ", "%s"))
    if kind == "key":
        k = KEYS.get(str(a.get("key") or "").lower())
        if not k:
            return {"error": "key is one of " + ", ".join(sorted(KEYS))}
        return f"input keyevent {k}"
    return {"error": "touch is tap, hold, glide, text or key"}


def _install(project, nid, serial, rel):
    """One of the project's own builds from its dist/, installed, and the
    package it carries added to the lease (aapt2 from the node's
    android-tools reads it, as bb sign does)."""
    rel = rel.lstrip("./")
    if not rel.startswith("dist/") or ".." in rel.split("/") or not rel.endswith(".apk"):
        return {"error": "install an .apk from this project's dist/"}, 400
    f = WORKSPACE / project / rel
    if not f.is_file():
        return {"error": f"no {rel} in {project}"}, 404
    node = phone.nodes.node(nid) if phone.nodes is not None else None
    dest = phone.install_dest(node or {}, project, rel)
    script = ('adb -s "$2" install -r "$1" || exit $?; '
              'bt=$(ls -d "$ANDROID_HOME"/build-tools/* 2>/dev/null | sort -V | tail -1); '
              '[ -x "$bt/aapt2" ] && echo "bb-package: $("$bt/aapt2" dump packagename "$1")"')
    r = phone.nodes.run_wait(f"session:{project}", nid, ["sh", "-c", script, "_", dest, serial],
                             env={"ANDROID_ADB_SERVER_PORT": phone.ADB_PORT}, timeout=600,
                             files=[rel], sizes={rel: f.stat().st_size}, project=project)
    if r.get("error"):
        return {"error": r["error"]}, 502
    out = r.get("out") or ""
    if r.get("code") or "Success" not in out:
        return {"error": " ".join(out.split())[-300:] or "the install failed"}, 502
    m = re.search(r"bb-package: (\S+)", out)
    pkg = m.group(1) if m and PKG.match(m.group(1)) else ""
    if not pkg:
        return {"error": "installed, but its package could not be read: the node needs android-tools "
                         "from the Toolchains tab for the lease to know it"}, 502
    _add_pkg(nid, pkg)
    return {"ok": True, "pkg": pkg}, 200
