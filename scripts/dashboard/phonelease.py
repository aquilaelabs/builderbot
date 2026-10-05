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
import hashlib
import importlib.util
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
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
    apps, the newest screenshot a session took of it, and the newest
    recording's reel."""
    got = lease(nid)
    if not got:
        return None
    d = WORKSPACE / got["project"] / "dist" / "phone"
    shots = sorted(d.glob("shot-*.png"))
    # ...and the newest recording's reel, the frames that changed with their
    # times, beside its video (the operator, 5 Oct).
    sheets = sorted(d.glob("record-*-sheet.png"))
    video = sheets[-1].name.replace("-sheet.png", ".mp4") if sheets else ""
    return dict(got, left=int(got["until"] - time.time()) if got.get("until") else None,
                shot=f"dist/phone/{shots[-1].name}" if shots else "",
                reel=f"dist/phone/{sheets[-1].name}" if sheets else "",
                video=f"dist/phone/{video}" if video and (d / video).is_file() else "",
                recording=bool(_recording.get(nid) and time.time() < _recording[nid]["until"]))


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
        # In nanoseconds: a recording's sheet written in the same second as
        # the poll before it was never drawn, with whole seconds here.
        try:
            m = p.stat().st_mtime_ns
        except OSError:
            m = 0
        live = 1 if nid in _recording else 0
        out.append(f"{nid}:{got.get('project')}:{got.get('at')}:{len(got.get('pkgs') or [])}:{m}:{live}")
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


# A recording started and left running on the phone while a session works it
# (the operator, 5 Oct): one job is a recording and each touch another, and
# a node runs one at a time, so a glide asked during `bb phone record N` ran
# after it ended and was never in it. start leaves screenrecord running on
# the phone and answers at once; stop interrupts it (which closes the file
# whole), pulls it and uploads it. In memory, per node: a controller restart
# forgets one, and screenrecord ends on its own --time-limit.
REC_LIVE_MAX = 180          # screenrecord's own ceiling
_recording = {}


def _rec_start(project, nid, serial, args):
    if nid in _recording and time.time() < _recording[nid]["until"]:
        return {"error": "a recording is already going on this phone: bb phone record stop collects it"}, 409
    try:
        secs = max(1, min(REC_LIVE_MAX, int(args.get("seconds") or 60)))
    except (TypeError, ValueError):
        secs = 60
    tmp = f"/data/local/tmp/bb-rec-{secrets.token_hex(6)}.mp4"
    r = _shell(nid, serial, f"nohup screenrecord --time-limit {secs} --bit-rate 4000000 {tmp} "
                            ">/dev/null 2>&1 &", project, timeout=30)
    if r.get("code"):
        return {"error": "the phone did not start recording: " + " ".join((r.get("out") or "").split())[-200:]}, 502
    now = time.time()
    _recording[nid] = {"file": tmp, "until": now + secs, "project": project}
    return {"ok": True, "until": int(now + secs),
            "out": f"recording, for up to {secs} s: work the phone, then bb phone record stop"}, 200


def _rec_stop(project, nid, serial, args):
    cur = _recording.pop(nid, None)
    if not cur or cur.get("project") != project:
        return {"error": "no recording is going on this phone: bb phone record start begins one"}, 409
    tmp = cur["file"]
    script = (f'adb -s "$1" shell "pkill -INT screenrecord; sleep 2"; adb -s "$1" pull {tmp} "$2"; rc=$?; '
              f'adb -s "$1" shell rm -f {tmp}; [ "$rc" = 0 ] && [ -s "$2" ]')
    return _reeled(project, _pulled(project, nid, serial, "record", "mp4", script, 120,
                                    f"a recording of the phone lent to {project}",
                                    ok=lambda b: b"moov" in b, what="recording"))


REEL = Path(__file__).resolve().parent.parent / "lib" / "reel.py"


def _reeled(project, answer):
    """A recording that landed, with its reel beside it: the frames that
    changed, each stamped with its time, tiled into one picture
    (record-...-sheet.png), which is what the owner's tab shows and what a
    session reads at a glance (the operator, 5 Oct). Best effort: a
    recording is kept whether or not its sheet could be made."""
    res, st = answer
    if st != 200 or not res.get("path"):
        return answer
    mp4 = WORKSPACE / project / res["path"]
    try:
        with tempfile.TemporaryDirectory() as t:
            env = dict(os.environ, BB_CAPTURE_OUT=t, BB_CAPTURE_FFMPEG=shutil.which("ffmpeg") or "ffmpeg")
            subprocess.run([sys.executable, str(REEL), "--video", str(mp4), "--name", "r",
                            "--threshold", "0.0002"], env=env, capture_output=True, timeout=240, check=False)
            sheet = Path(t) / "r" / "sheet.png"
            if sheet.is_file():
                dest = mp4.with_name(mp4.stem + "-sheet.png")
                shutil.copyfile(sheet, dest)
                res = dict(res, sheet=f"dist/phone/{dest.name}")
    except (OSError, subprocess.SubprocessError):
        pass
    return res, st


def _shot(project, nid, serial):
    """The phone's screen, as a file the node uploads rather than as base64
    in the job's log (report #53): a big phone's screenshot is megabytes,
    and the log reaches the controller 40 KB at a time, so a Pixel 11 Pro
    XL's ran out its 90 s and arrived as a timeout."""
    return _pulled(project, nid, serial, "shot", "png", 'adb -s "$1" exec-out screencap -p > "$2" && [ -s "$2" ]',
                   90, f"screenshot of the phone lent to {project}",
                   ok=lambda b: b.startswith(b"\x89PNG"), what="screenshot")


def _pulled(project, nid, serial, kind, ext, script, timeout, title, ok, what):
    """A file the phone makes, written on the node by `script` (its $1 the
    phone's serial, $2 the file), uploaded by the agent into dist/ as the
    job's output, and moved under dist/phone/ like the rest. In /tmp, which
    the job account may write: the data store's root is not, and the shot
    died on "Permission denied" there (report #56); older ones of this kind
    are cleared first, since a failed run leaves its file behind."""
    name = f"bb-{kind}-{secrets.token_hex(6)}.{ext}"
    sh = f'find . -maxdepth 1 -name "bb-{kind}-*.{ext}" -mmin +10 -delete 2>/dev/null; ' + script
    r = phone.nodes.run_wait(f"session:{project}", nid, ["sh", "-c", sh, "_", serial, name],
                             env={"ANDROID_ADB_SERVER_PORT": phone.ADB_PORT}, timeout=timeout,
                             project=project, outputs=[name], title=title, cwd="/tmp")
    if r.get("error"):
        return {"error": f"the phone gave no {what}: " + r["error"]}, 502
    got = WORKSPACE / project / "dist" / name
    try:
        data = got.read_bytes()
    except OSError:
        data = b""
    finally:
        got.unlink(missing_ok=True)
    if r.get("code") or not ok(data):
        return {"error": f"the phone gave no {what}: " + " ".join((r.get("out") or "").split())[-200:]}, 502
    return {"path": _capture(project, kind, ext, data)}, 200


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
        return _shot(project, nid, serial)
    if op == "record" and str(args.get("action") or "") in ("start", "stop"):
        return (_rec_start if args.get("action") == "start" else _rec_stop)(project, nid, serial, args)
    if op == "record":
        try:
            secs = max(1, min(RECORD_MAX, int(args.get("seconds") or 10)))
        except (TypeError, ValueError):
            secs = 10
        # Recorded on the phone, ended by its own --time-limit so the file is
        # closed whole, pulled onto the node, and uploaded as a file: read
        # out of the job's log as base64 it arrived cut short, 13 KB with no
        # moov box, which nothing plays (report #57).
        tmp = f"/data/local/tmp/bb-rec-{secrets.token_hex(6)}.mp4"
        script = (f'adb -s "$1" shell screenrecord --time-limit {secs} --bit-rate 4000000 {tmp} '
                  f'&& adb -s "$1" pull {tmp} "$2"; rc=$?; adb -s "$1" shell rm -f {tmp}; '
                  '[ "$rc" = 0 ] && [ -s "$2" ]')
        return _reeled(project, _pulled(project, nid, serial, "record", "mp4", script, secs + 120,
                                        f"a {secs} s recording of the phone lent to {project}",
                                        ok=lambda b: b"moov" in b, what="recording"))
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
        if op == "touch" and str((args or {}).get("kind")) == "glide":
            g = _glide(project, nid, serial, guard, args)
            if g is not None:
                return g
        if op == "ui":
            r = _shell(nid, serial, guard + "uiautomator dump /data/local/tmp/bb-ui.xml >/dev/null "
                                    "&& cat /data/local/tmp/bb-ui.xml", project, timeout=90)
        else:
            cmd = _touch(args)
            if isinstance(cmd, dict):
                return cmd, 400
            r = _shell(nid, serial, guard + cmd, project)
            if str((args or {}).get("kind")) == "glide" and not r["code"]:
                # Said, so a session reading a typed "H" for a glided word
                # knows why (report #56): points are a tap and slides, not
                # one held stroke.
                r = dict(r, out=r["out"] + "[builderbot] this node cannot build the glide injector "
                                           "(javac and Android build-tools), so the points were sent as "
                                           "separate swipes, which a keyboard reads as taps\n")
        if "bb-not-yours" in r["out"]:
            return {"error": "none of this lease's apps is in front or is the keyboard, so the phone is "
                             "not touched: bb phone start PKG first (" + r["out"].strip()[-160:] + ")"}, 409
        return {"code": r["code"], "out": r["out"]}, 200
    return {"error": f"unknown: {op}"}, 400


GLIDE_SRC = Path(__file__).with_name("BbGlide.java")
HAND = Path(__file__).resolve().parent.parent / "lib" / "hand.py"


def _hand():
    """scripts/lib/hand.py, the finger's path a glide plays (R127), loaded
    by path the way artifacts.py loads capture.py: the one copy bb emu
    touch uses too, so both glides move the same way."""
    if "_hand_mod" not in globals():
        spec = importlib.util.spec_from_file_location("bb_hand", HAND)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        globals()["_hand_mod"] = mod
    return globals()["_hand_mod"]

# Built once per source on the node (cached in /tmp by the source's hash),
# pushed, and run as the shell user. Exit 90: the node has no javac or
# Android build-tools to build it with, and the caller falls back to points.
_GLIDE_SH = r"""
d=/tmp/bb-glide-$3
if [ ! -s "$d/classes.dex" ]; then
  mkdir -p "$d/cls" && printf %s "$4" > "$d/BbGlide.java" &&
  aj=$(ls "$ANDROID_HOME"/platforms/android-*/android.jar 2>/dev/null | sort -V | tail -1) &&
  bt=$(ls -d "$ANDROID_HOME"/build-tools/*/ 2>/dev/null | sort -V | tail -1) &&
  [ -n "$aj" ] && [ -n "$bt" ] && command -v javac >/dev/null &&
  javac --release 11 -cp "$aj" -d "$d/cls" "$d/BbGlide.java" >/dev/null 2>&1 &&
  "${bt}d8" --min-api 26 --lib "$aj" --output "$d" "$d/cls/BbGlide.class" >/dev/null 2>&1 ||
  { echo "bb-glide-unbuilt"; exit 90; }
fi
adb -s "$1" push "$d/classes.dex" /data/local/tmp/bb-glide.dex >/dev/null && adb -s "$1" shell "$2"
"""


def _glide(project, nid, serial, guard, args):
    """A glide as one held stroke (R126), or None when the node cannot build
    the injector, for the caller's points instead; a bad argument is its
    refusal."""
    a = args if isinstance(args, dict) else {}
    pts = a.get("points") if isinstance(a.get("points"), list) else []
    nums = [_num(v) for v in pts]
    if len(nums) < 4 or len(nums) % 2 or None in nums or len(nums) > 200:
        return {"error": "glide X Y X Y..., at least two points"}, 400
    # The path between the points is a hand's (R127): the injector plays
    # one sample every hand.DT ms, which is what its first argument says.
    hand = _hand()
    hopts = a.get("hand") if isinstance(a.get("hand"), dict) else {}
    try:
        stroke = hand.path(list(zip(nums[0::2], nums[1::2], strict=True)), ms=a.get("ms") or None,
                           **{k: v for k, v in hopts.items() if k in hand.FLAGS and k != "ms"})
    except ValueError as e:
        return {"error": str(e)}, 400
    try:
        src = GLIDE_SRC.read_text()
    except OSError:
        return None
    h = hashlib.sha256(src.encode()).hexdigest()[:12]
    # Numbers only on the phone's command line, behind the same guard a tap has.
    flat = [n for _, x, y in stroke["samples"] for n in (x, y)]
    on_phone = guard + "CLASSPATH=/data/local/tmp/bb-glide.dex app_process / BbGlide " + \
        " ".join(str(n) for n in [hand.DT, *flat])
    secs = 60 + stroke["took_ms"] // 1000
    r = phone.nodes.run_wait(f"session:{project}", nid, ["sh", "-c", _GLIDE_SH, "_", serial, on_phone, h, src],
                             env={"ANDROID_ADB_SERVER_PORT": phone.ADB_PORT}, timeout=secs + 120,
                             project=project, title=f"glide on the phone lent to {project}", cwd="/tmp")
    if r.get("error"):
        return {"error": "the glide did not run: " + r["error"]}, 502
    out = r.get("out") or ""
    if r.get("code") == 90 and "bb-glide-unbuilt" in out:
        return None
    if "bb-not-yours" in out:
        return {"error": "none of this lease's apps is in front or is the keyboard, so the phone is "
                         "not touched: bb phone start PKG first (" + out.strip()[-160:] + ")"}, 409
    # Said, with the seed, so the same stroke can be sent again.
    return {"code": r.get("code") or 0, "out": out + "glide: " + hand.summary(stroke) + "\n",
            "seed": stroke["seed"]}, 200


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


def _dist_apk(project, rel):
    """(path, rel) of one of the project's own builds, or a refusal: an .apk
    under its dist/, named relative to the project or absolutely inside it
    (a session gave the whole path once and was refused after its owner
    had already been asked, report #52)."""
    root = WORKSPACE / project
    if rel.startswith("/"):
        try:
            rel = str(Path(rel).relative_to(root))
        except ValueError:
            return {"error": "install an .apk from this project's dist/"}, 400
    rel = rel.removeprefix("./")
    if not rel.startswith("dist/") or ".." in rel.split("/") or not rel.endswith(".apk"):
        return {"error": "install an .apk from this project's dist/"}, 400
    f = root / rel
    if not f.is_file():
        return {"error": f"no {rel} in {project}"}, 404
    return f, rel


def check(project, op, args):
    """The refusal a verb would meet, said before its owner is asked (report
    #52: a path the install refuses had already put an Allow in their bell):
    (payload, status), or None when it is worth asking about."""
    args = args if isinstance(args, dict) else {}
    nid, got = leased_to(project)
    if not got:
        return use(project, op, args)                  # the refusal, in its words
    if op == "install":
        r = _dist_apk(project, str(args.get("file") or ""))
        return r if isinstance(r[0], dict) else None
    pkgs = list(got.get("pkgs") or [])
    pkg = str(args.get("pkg") or (pkgs[0] if pkgs else ""))
    if op in ("start", "stop", "ime", "log") and pkg not in pkgs:
        return {"error": f"{pkg or 'that'} is not one of this lease's apps: install the build "
                         "with bb phone install first" + (f" (it has {', '.join(pkgs)})" if pkgs else "")}, 403
    return None


def _install(project, nid, serial, rel):
    """One of the project's own builds from its dist/, installed, and the
    package it carries added to the lease (aapt2 from the node's
    android-tools reads it, as bb sign does)."""
    r = _dist_apk(project, rel)
    if isinstance(r[0], dict):
        return r
    f, rel = r
    node = phone.nodes.node(nid) if phone.nodes is not None else None
    dest = phone.install_dest(node or {}, project, rel)
    script = ('adb -s "$2" install -r "$1" || exit $?; '
              'bt=$(ls -d "$ANDROID_HOME"/build-tools/* 2>/dev/null | sort -V | tail -1); '
              '[ -x "$bt/aapt2" ] && echo "bb-package: $("$bt/aapt2" dump packagename "$1")"')
    r = phone.nodes.run_wait(f"session:{project}", nid, ["sh", "-c", script, "_", dest, serial],
                             env={"ANDROID_ADB_SERVER_PORT": phone.ADB_PORT}, timeout=600,
                             files=[rel], sizes={rel: f.stat().st_size}, project=project,
                             title=f"install {rel} on the phone lent to {project}")
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
