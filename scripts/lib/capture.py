"""What a session looks with (R95): one capture per source, shared by
`bb capture shot` and `bb capture reel`. A source is anything that draws: a page Playwright
opens, the running emulator's screen, an X display. A shot is that source
at rest (frames a quarter second apart until a second of them match); a
reel is its recording, which reel.py turns into the frames that changed.

As a program: `capture.py shot --emu [PKG] | --display :N [--settle|--now]
[--drive FILE] [--mark] OUT` takes the picture, `capture.py mark FILE URL...`
records a page's shot as a capture, `capture.py ls DIST` lists the
captures under a project's dist/ and `capture.py prune DIST [--days N]
[NAME...]` removes them (R96). BB_CAPTURE_FFMPEG is the ffmpeg binary,
BB_CAPTURE_ADB the emulator's adb, BB_CAPTURE_NODE_PATH and BB_CAPTURE_CHROME what a
page needs, BB_CAPTURE_AUTH the credential a dashboard page takes, and
BB_CAPTURE_SCRATCH where the working files go.

What stays and what goes (R96): dist/ is what a project ships and the
Artifacts view lists it, so a capture leaves there only what a person reads
(a reel's sheet.png and frames.json, a shot's png), each with a record of who
asked and when, and the working files (the recording, the full-size frames)
go to this machine's own disk under BB_CAPTURE_SCRATCH. Nothing knows when
a capture is done with: two sessions on one project may each be reading a
reel the other made, so nothing is removed by need. They go by age, the
project's "captures kept" days (artifacts.py sweeps when the tab draws, prune
here does it from a node), or by name when the one who made it says so.
"""
import getpass
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf")


def die(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


def ffmpeg():
    return os.environ.get("BB_CAPTURE_FFMPEG") or shutil.which("ffmpeg") or die(
        "ffmpeg is not on this node: it is a toolchain recipe on the Tools tab")


def run(argv, timeout=600, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, **kw)


def font():
    return next((f for f in FONTS if os.path.exists(f)), "")


def maker():
    """Who asked and when, written into a capture's record so the Artifacts
    tab can say whose it is: the session's account (BB_ACCOUNT_NAME), else
    the unix user, and the node (R96)."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = ""
    return {"by": os.environ.get("BB_ACCOUNT_NAME") or user, "at": int(time.time()),
            "node": os.environ.get("BB_NODE", "")}


def scratch(name):
    """The working files' directory for one capture: the recording and the
    full-size frames live on this machine's own disk (BB_CAPTURE_SCRATCH,
    else /tmp/bb-capture-UID), never in dist/ on the share, which lists
    what ships (R96). Made empty: a capture made again under the same name
    starts over."""
    base = os.environ.get("BB_CAPTURE_SCRATCH") or os.path.join(
        os.environ.get("TMPDIR") or "/tmp", f"bb-capture-{os.getuid()}")
    d = os.path.join(base, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


# ---- what is under dist/: the captures, and their sweep -------------------------

CAPTURE_DIRS = ("reel", "emu", "shot")


def record_of(path):
    """A capture's record, {} when it has none: a reel's frames.json, a
    shot's dot-file beside it (.NAME.json, which the tab's listing skips)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def captures(dist):
    """Every capture under a project's dist/, newest first: a reel is a
    directory under reel/ with sheet.png, a shot a png under emu/ or shot/. Each is
    {name, kind, path (relative to dist), file, at, by, node, size}, with
    at and by from its record when it has one, else the file's own time and
    nobody. The same rule on both sides: artifacts.py reads this for the
    tab, prune below applies it on a node."""
    out = []
    reel = os.path.join(dist, "reel")
    if os.path.isdir(reel):
        for name in sorted(os.listdir(reel)):
            d = os.path.join(reel, name)
            sheet = os.path.join(d, "sheet.png")
            if name.startswith(".") or not os.path.isdir(d) or not os.path.isfile(sheet):
                continue
            rec = record_of(os.path.join(d, "frames.json"))
            st = os.stat(sheet)
            out.append({"name": name, "kind": "reel", "path": f"reel/{name}/sheet.png", "file": d,
                        "at": int(rec.get("at") or st.st_mtime), "by": str(rec.get("by") or ""),
                        "node": str(rec.get("node") or ""), "size": st.st_size,
                        "frames": len(rec.get("frames") or [])})
    for sub in ("emu", "shot"):
        here = os.path.join(dist, sub)
        if not os.path.isdir(here):
            continue
        for fn in sorted(os.listdir(here)):
            p = os.path.join(here, fn)
            if fn.startswith(".") or not os.path.isfile(p):
                continue
            rec = record_of(os.path.join(here, f".{fn}.json"))
            st = os.stat(p)
            out.append({"name": fn, "kind": "shot", "path": f"{sub}/{fn}", "file": p,
                        "at": int(rec.get("at") or st.st_mtime), "by": str(rec.get("by") or ""),
                        "node": str(rec.get("node") or ""), "size": st.st_size})
    return sorted(out, key=lambda c: -c["at"])


def remove(c):
    """One capture gone: a reel's directory, a shot and its record, and a
    reel's working files on this machine (the recording, the full-size
    frames), which frames.json names in `work`. Only a directory under the
    capture scratch: the record is a file on the share, and it names what
    is deleted (report 42: the work stayed behind)."""
    if c["kind"] == "reel":
        work = str(record_of(os.path.join(c["file"], "frames.json")).get("work") or "")
        base = os.path.realpath(os.environ.get("BB_CAPTURE_SCRATCH") or os.path.join(
            os.environ.get("TMPDIR") or "/tmp", f"bb-capture-{os.getuid()}"))
        if work and os.path.dirname(os.path.realpath(work)) == base and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(c["file"], ignore_errors=True)
    else:
        for p in (c["file"], os.path.join(os.path.dirname(c["file"]), f".{c['name']}.json")):
            try:
                os.unlink(p)
            except OSError:
                pass


def prune(dist, days=None, names=()):
    """The captures removed: those named, and every one older than `days`
    (0 or None keeps them all). By age and never by need: a capture is
    somebody's until the project's days are up, whoever else is on the
    project. Returns the removed rows."""
    gone = []
    for c in captures(dist):
        if c["name"] in names or (days and c["at"] < time.time() - days * 86400):
            remove(c)
            gone.append(c)
    return gone



# ---- one frame of a source, for a shot at rest ----------------------------------

def _adb():
    return os.environ.get("BB_CAPTURE_ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")


def emu_ready(adb):
    r = run([adb, "get-state"], timeout=20)
    if r.returncode or "device" not in (r.stdout or ""):
        die("no emulator is running: bb emu start boots one")


def in_front(adb, pkg):
    """Whether PKG already owns the screen: the focused window is its (an
    activity, a dialog of its), or its keyboard is up, since an IME's
    window is never the focused one. Read from the window manager's dump,
    where the focus line names the package and every window its own."""
    r = run([adb, "shell", "dumpsys", "window", "windows"], timeout=20)
    out = r.stdout or ""
    m = re.search(r"mCurrentFocus=Window\{[^}]*\s([\w.]+)(?:/[^\s}]*)?\}", out)
    if m and m.group(1) == pkg:
        return True
    for block in re.split(r"(?=\n\s*Window #\d+ )", out):
        if "InputMethod" in block.split("\n", 1)[0] and re.search(rf"package={re.escape(pkg)}\b", block) \
                and re.search(r"isVisible=true|mHasSurface=true", block):
            return True
    # ...and asked directly, since the window dump's wording moves between
    # releases: an app that is also the keyboard, up over its own setup
    # screen, read as not in front, and the launch took the keyboard down
    # (report #68, B529). The input method service says whose keyboard is
    # showing; the activity manager names the activity resumed on top.
    ime = run([adb, "shell", "dumpsys", "input_method"], timeout=20).stdout or ""
    cur = re.search(r"mCurMethodId=([\w.]+)/", ime)
    if cur and cur.group(1) == pkg and re.search(r"mInputShown=true", ime):
        return True
    act = run([adb, "shell", "dumpsys", "activity", "activities"], timeout=20).stdout or ""
    top = re.search(r"(?:topResumedActivity|mResumedActivity|ResumedActivity)[=:][^\n]*?\s([\w.]+)/", act)
    return bool(top and top.group(1) == pkg)


def bring_up(adb, pkg):
    """Put PKG on the screen when it is not already there. Not when it is:
    a launch restarts its launcher activity, which takes down the dialog,
    the deep screen or the keyboard a session just drove into place, and
    the shot came back with the app's front page instead (B387)."""
    if pkg and not in_front(adb, pkg):
        run([adb, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)


def display_ready(display):
    num = display.lstrip(":").split(".")[0]
    if not num.isdigit() or not os.path.exists(f"/tmp/.X11-unix/X{num}"):
        die(f"no X display {display} on this node: a server install has none, and the "
            "provisioner adds Xvfb and xdotool (nodes/provision-linux.sh); bb capture reel --display "
            "then records one an app was started on (Xvfb :9 & DISPLAY=:9 the-app &)")


def display_size(display):
    """The display's size from xdpyinfo where the node has it; without it
    the size an Xvfb started for this is given (1280x800)."""
    size = "1280x800"
    if shutil.which("xdpyinfo"):
        r = run(["xdpyinfo", "-display", display], timeout=10)
        m = re.search(r"dimensions:\s+(\d+x\d+)", r.stdout or "")
        if m:
            size = m.group(1)
    return size


def frame_emu(adb):
    r = subprocess.run([adb, "exec-out", "screencap", "-p"], capture_output=True, timeout=30, check=False)
    if r.returncode or not r.stdout:
        die("screencap failed: " + (r.stderr or b"").decode("utf-8", "replace").strip()[-200:])
    return r.stdout


def frame_display(display, size):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "x11grab",
                        "-video_size", size, "-i", display, "-frames:v", "1", "-f", "image2pipe",
                        "-vcodec", "png", "-"], capture_output=True, timeout=30, check=False)
    if r.returncode or not r.stdout:
        die(f"nothing was grabbed from {display}: " + (r.stderr or b"").decode("utf-8", "replace").strip()[-200:])
    return r.stdout


def at_rest(grab, settle=True, quiet=4, cap=6.0):
    """The frame once `quiet` grabs a quarter second apart are the same
    bytes, or the last one after `cap` seconds with a word on stderr: a
    surface that never stops moving is pictured as it is. Two matching
    frames were not enough: they came before an element that lands a second
    later, so the quiet is a whole second."""
    last = grab()
    if not settle:
        return last
    still, until = 0, time.time() + cap
    while time.time() < until and still < quiet:
        time.sleep(0.25)
        nxt = grab()
        still = still + 1 if nxt == last else 0
        last = nxt
    if still < quiet:
        print(f"[builderbot] still moving after {cap:.0f} seconds; shot as it is", file=sys.stderr)
    return last


# A timed touch for a drive script on the emulator ($BB_TOUCH tap|hold|glide,
# touch.py): adb's input verbs are too slow to time a gesture (R101).
TOUCH = f"python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'touch.py')}"


def drive(script, env):
    """The script that works the surface before the picture, with the
    surface's own handle in its environment ($ADB and $BB_TOUCH, or DISPLAY)."""
    if script:
        subprocess.run(["sh", script], timeout=600, check=False, env=dict(os.environ, BB_TOUCH=TOUCH, **env))


def shot(a):
    """One picture at rest into a.out; with --mark, a record beside it
    (.NAME.json: who, when, from what) for the Artifacts view and the sweep."""
    if a.emu is not None:
        adb = _adb()
        emu_ready(adb)
        bring_up(adb, a.emu)
        drive(a.drive, {"ADB": adb})
        png = at_rest(lambda: frame_emu(adb), a.settle)
    else:
        display_ready(a.display)
        size = display_size(a.display)
        drive(a.drive, {"DISPLAY": a.display})
        png = at_rest(lambda: frame_display(a.display, size), a.settle)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(png)
    if a.mark:
        mark(a.out, f"emu {a.emu}".strip() if a.emu is not None else f"display {a.display}")
    print(a.out)


def mark(path, source):
    """The record beside a shot (.NAME.json: who, when, from what), which
    makes it a capture the Artifacts view lists and the sweep removes."""
    with open(os.path.join(os.path.dirname(os.path.abspath(path)), f".{os.path.basename(path)}.json"),
              "w", encoding="utf-8") as f:
        json.dump(maker() | {"source": source}, f)


# ---- the sources: each ends with a video file ---------------------------------------

def from_url(url, seconds, drive, work):
    """A page recorded by Playwright while a script drives it, the way bb
    capture shot opens one. The driver gets the page and the seconds it has.
    The recording lands under `work`, the capture's scratch directory."""
    node_path, chrome = os.environ.get("BB_CAPTURE_NODE_PATH", ""), os.environ.get("BB_CAPTURE_CHROME", "")
    if not chrome:
        die("no browser here: Playwright's Chromium is a toolchain recipe on the Tools tab")
    vdir = os.path.join(work, "video")
    shutil.rmtree(vdir, ignore_errors=True)
    os.makedirs(vdir)
    script = r"""
const { chromium } = require("playwright");
const [exe, url, seconds, drive, vdir, auth] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch({ executablePath: exe });
  const bearer = /^bbs_/.test(auth || "");
  const [username, password] = !bearer && (auth || "").includes(":") ? auth.split(/:(.*)/) : [null, null];
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 },
    recordVideo: { dir: vdir, size: { width: 1280, height: 800 } },
    ...(username ? { httpCredentials: { username, password } } : {}) });
  if (bearer) await ctx.setExtraHTTPHeaders({ authorization: "Bearer " + auth });
  const page = await ctx.newPage();
  const started = Date.now();
  await page.goto(url, { waitUntil: "domcontentloaded" }).catch(e => console.error("goto: " + e.message));
  if (drive) {
    const mod = await import(drive);
    await (mod.default || mod.drive)(page, { seconds: +seconds, ctx, browser: b });
  }
  const left = +seconds * 1000 - (Date.now() - started);
  if (left > 0) await page.waitForTimeout(left);
  await ctx.close();
  await b.close();
})();
"""
    env = dict(os.environ, NODE_PATH=node_path)
    r = subprocess.run(["node", "-", chrome, url, str(seconds), drive or "", vdir,
                        os.environ.get("BB_CAPTURE_AUTH", "")], input=script, capture_output=True,
                       text=True, timeout=seconds + 120, check=False, env=env)
    if r.returncode:
        die(f"the recording did not finish: {(r.stderr or '').strip()[-400:]}")
    vids = [os.path.join(vdir, x) for x in os.listdir(vdir) if x.endswith(".webm")]
    if not vids:
        die("Playwright recorded nothing")
    return vids[0]


def from_emu(pkg, seconds, drive, work, out):
    """The running emulator's screenrecord (into `work`) while an adb-input
    script drives the app, with gfxinfo's framestats beside the reel (in
    `out`): a software-rendered capture is about 10fps, so the timing is
    read there, not off the frames."""
    adb = os.environ.get("BB_CAPTURE_ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")
    r = run([adb, "get-state"], timeout=20)
    if r.returncode or "device" not in (r.stdout or ""):
        die("no emulator is running: bb emu start boots one")
    if pkg:
        bring_up(adb, pkg)
        run([adb, "shell", "dumpsys", "gfxinfo", pkg, "reset"], timeout=20)
    rec = subprocess.Popen([adb, "shell", "screenrecord", "--time-limit", str(seconds), "/sdcard/bb-reel.mp4"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if drive:
        subprocess.run(["sh", drive], timeout=seconds + 60, check=False,
                       env=dict(os.environ, ADB=adb, BB_TOUCH=TOUCH, BB_CAPTURE_SECONDS=str(seconds)))
    rec.wait(timeout=seconds + 60)
    video = os.path.join(work, "screen.mp4")
    r = run([adb, "pull", "/sdcard/bb-reel.mp4", video], timeout=120)
    if r.returncode:
        die(f"could not pull the recording: {(r.stderr or r.stdout).strip()[-200:]}")
    if pkg:
        g = run([adb, "shell", "dumpsys", "gfxinfo", pkg, "framestats"], timeout=30)
        with open(os.path.join(out, "framestats.txt"), "w", encoding="utf-8") as f:
            f.write(g.stdout or "")
    return video


def from_display(display, seconds, drive, work):
    """An X display grabbed with x11grab (into `work`) while xdotool drives
    it. A server install has no X server: Xorg or Xvfb is the provisioner's
    to add."""
    num = display.lstrip(":").split(".")[0]
    if not num.isdigit() or not os.path.exists(f"/tmp/.X11-unix/X{num}"):
        die(f"no X display {display} on this node: a server install has none, and the "
            "provisioner adds Xvfb and xdotool (nodes/provision-linux.sh); bb capture reel --display "
            "then records one an app was started on (Xvfb :9 & DISPLAY=:9 the-app &)")
    video = os.path.join(work, "display.mp4")
    # The display's size from xdpyinfo where the node has it; without it the
    # grab is of the size an Xvfb started for this is given (1280x800).
    size = "1280x800"
    if shutil.which("xdpyinfo"):
        r = run(["xdpyinfo", "-display", display], timeout=10)
        m = re.search(r"dimensions:\s+(\d+x\d+)", r.stdout or "")
        if m:
            size = m.group(1)
    rec = subprocess.Popen([ffmpeg(), "-hide_banner", "-nostdin", "-y", "-f", "x11grab", "-framerate", "15",
                            "-video_size", size, "-i", display, "-t", str(seconds), video],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if drive:
        subprocess.run(["sh", drive], timeout=seconds + 60, check=False,
                       env=dict(os.environ, DISPLAY=display, BB_CAPTURE_SECONDS=str(seconds)))
    rec.wait(timeout=seconds + 60)
    if not os.path.exists(video) or os.path.getsize(video) < 100:
        die(f"nothing was recorded from {display}")
    return video



def ago(t):
    """An age as a person says it, for ls."""
    s = max(0, int(time.time() - t))
    return (f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s // 3600}h" if s < 86400
            else f"{s // 86400}d") + " ago"


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("what", choices=["shot", "ls", "prune", "mark"])
    ap.add_argument("--emu", nargs="?", const="")
    ap.add_argument("--display")
    ap.add_argument("--drive")
    ap.add_argument("--settle", dest="settle", action="store_true", default=True)
    ap.add_argument("--now", dest="settle", action="store_false")
    ap.add_argument("--mark", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("out")
    ap.add_argument("names", nargs="*")
    a = ap.parse_args()
    if a.what == "mark":
        # A page's shot, taken by bb capture shot's browser: `out` is the
        # file and the names are the URLs it was taken from.
        mark(a.out, " ".join(a.names))
        return
    if a.what in ("ls", "prune"):
        # `out` is the project's dist/ here, and the names are captures to
        # remove now whatever their age.
        if a.what == "prune" and not a.names and a.days is None:
            die("bb capture prune NAME... removes those; --days N removes every capture older than that")
        rows = prune(a.out, a.days, set(a.names)) if a.what == "prune" else captures(a.out)
        missing = set(a.names) - {c["name"] for c in rows}
        if missing:
            die(f"no such capture: {', '.join(sorted(missing))}; bb capture ls names them")
        for c in rows:
            print(f"  {c['kind']:<5} {c['name']:<32} {ago(c['at']):>8}  {c['by'] or 'nobody'}"
                  + (f"  {c['frames']} frames" if c["kind"] == "reel" else ""))
        if a.what == "prune":
            print(f"[builderbot] {len(rows)} capture{'s' if len(rows) != 1 else ''} removed", file=sys.stderr)
        elif not rows:
            print("[builderbot] no captures in dist/reel, dist/emu or dist/shot", file=sys.stderr)
        return
    if (a.emu is None) == (a.display is None):
        die("one source: --emu [PKG] or --display :N")
    if a.drive and not os.path.isfile(a.drive):
        die(f"no such driver: {a.drive}")
    shot(a)


if __name__ == "__main__":
    main()
