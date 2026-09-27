"""Behind `bb reel` (cmd_reel in bb): eyes on change over time (R95).

A screenshot shows one moment; what a session cannot see is an element
popping in or a transition. So: the frames of a recording that CHANGED,
each stamped with its time, tiled into one sheet a session reads at a
glance, beside a JSON of when each change came and how much moved. The
source is anything that draws: a video file, a page Playwright records
while a script drives it, the emulator's screenrecord, an X display.

Arguments: the source (--video FILE | --url URL | --emu PKG | --display :N),
--seconds N for a recording, --drive FILE for the script that works the
surface meanwhile, --name NAME for the reel's directory under dist/reel/,
--threshold T (ffmpeg's scene score, 0..1, that counts as a change) and
--fps N (how often the recording is looked at). BB_REEL_OUT is dist/reel,
BB_REEL_FFMPEG the ffmpeg binary, BB_REEL_NODE_PATH and BB_REEL_CHROME what
the page source needs, BB_REEL_ADB the emulator's adb.
"""
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
COLS, WIDTH = 4, 480          # the sheet: four frames across, each 480px wide


def die(msg):
    sys.exit(f"[builderbot] ERROR: {msg}")


def ffmpeg():
    return os.environ.get("BB_REEL_FFMPEG") or shutil.which("ffmpeg") or die(
        "ffmpeg is not on this node: it is a toolchain recipe on the Tools tab")


def run(argv, timeout=600, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, **kw)


def font():
    return next((f for f in FONTS if os.path.exists(f)), "")


# ---- the reel itself: from a video to a sheet and a log ------------------------

def reel(video, out, threshold, fps):
    """The frames that changed, stamped and tiled. Returns the log."""
    os.makedirs(out, exist_ok=True)
    frames = os.path.join(out, "frames")
    shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames)
    meta = os.path.join(out, "meta.txt")
    # ffmpeg picks the frames: the first, and each whose scene score against
    # the one before is over the threshold. `metadata=print` writes that
    # score per kept frame and showinfo its time; both are read back below.
    vf = (f"fps={fps},select='gt(scene,{threshold})+eq(n,0)',"
          f"metadata=print:file={meta},showinfo")
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-i", video, "-vf", vf, "-fps_mode", "vfr",
             os.path.join(frames, "%04d.png")])
    if r.returncode:
        die(f"ffmpeg could not read {video}: {(r.stderr or '').strip()[-300:]}")
    times = [float(m) for m in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr or "")]
    scores = []
    try:
        with open(meta, encoding="utf-8") as f:
            for ln in f:
                m = re.search(r"lavfi\.scene_score=([0-9.]+)", ln)
                if m:
                    scores.append(float(m.group(1)))
    except OSError:
        pass
    files = sorted(x for x in os.listdir(frames) if x.endswith(".png"))
    log = []
    for i, name in enumerate(files):
        log.append({"frame": i, "file": f"frames/{name}",
                    "t": round(times[i], 2) if i < len(times) else None,
                    # One score per kept frame, in order; the first is kept
                    # whatever it scored, and its score is against nothing.
                    "change": round(scores[i], 3) if i and i < len(scores) else 0.0})
    # The sheet: each frame scaled to one width and stamped with its time in
    # the corner, tiled four across. Without a font the stamp is left off and
    # frames.json is the map from position to time.
    n = len(files)
    if n:
        rows = (n + COLS - 1) // COLS
        fnt = font()
        stamp = (f",drawtext=fontfile={fnt}:text='%{{pts\\:hms}}':x=8:y=8:fontsize=22:"
                 f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6") if fnt else ""
        # The stamps come from the frames' own times: fed back at the same
        # timestamps by concat, so drawtext's pts is the time in the video.
        listing = os.path.join(out, "list.txt")
        with open(listing, "w", encoding="utf-8") as f:
            for i, name in enumerate(files):
                t = log[i]["t"] or 0.0
                nxt = log[i + 1]["t"] if i + 1 < n and log[i + 1]["t"] is not None else t + 1
                f.write(f"file '{os.path.join(frames, name)}'\nduration {max(0.04, nxt - t):.3f}\n")
            f.write(f"file '{os.path.join(frames, files[-1])}'\n")
        r = run([ffmpeg(), "-hide_banner", "-nostdin", "-f", "concat", "-safe", "0", "-i", listing,
                 # nb_frames: the list ends with the last frame once more so
                 # its duration counts, and that copy is not a tile.
                 "-vf", f"scale={WIDTH}:-2{stamp},tile={COLS}x{rows}:nb_frames={n}:padding=4:color=#202020",
                 "-frames:v", "1", "-update", "1", "-y", os.path.join(out, "sheet.png")])
        if r.returncode:
            die(f"ffmpeg could not tile the sheet: {(r.stderr or '').strip()[-300:]}")
        os.unlink(listing)
    for x in (meta,):
        with open(x, "a"):
            pass
        os.unlink(x)
    with open(os.path.join(out, "frames.json"), "w", encoding="utf-8") as f:
        json.dump({"source": video, "threshold": threshold, "fps": fps, "frames": log}, f, indent=1)
    return log


# ---- the sources: each ends with a video file ---------------------------------------

def from_url(url, seconds, drive, out):
    """A page recorded by Playwright while a script drives it, the way bb
    shot opens one. The driver gets the page and the seconds it has."""
    node_path, chrome = os.environ.get("BB_REEL_NODE_PATH", ""), os.environ.get("BB_REEL_CHROME", "")
    if not chrome:
        die("no browser here: Playwright's Chromium is a toolchain recipe on the Tools tab")
    vdir = os.path.join(out, "video")
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
                        os.environ.get("BB_REEL_AUTH", "")], input=script, capture_output=True,
                       text=True, timeout=seconds + 120, check=False, env=env)
    if r.returncode:
        die(f"the recording did not finish: {(r.stderr or '').strip()[-400:]}")
    vids = [os.path.join(vdir, x) for x in os.listdir(vdir) if x.endswith(".webm")]
    if not vids:
        die("Playwright recorded nothing")
    return vids[0]


def from_emu(pkg, seconds, drive, out):
    """The running emulator's screenrecord while an adb-input script drives
    the app, with gfxinfo's framestats beside the reel: a software-rendered
    capture is about 10fps, so the timing is read there, not off the frames."""
    adb = os.environ.get("BB_REEL_ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")
    r = run([adb, "get-state"], timeout=20)
    if r.returncode or "device" not in (r.stdout or ""):
        die("no emulator is running: bb emu start boots one")
    if pkg:
        run([adb, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
        run([adb, "shell", "dumpsys", "gfxinfo", pkg, "reset"], timeout=20)
    rec = subprocess.Popen([adb, "shell", "screenrecord", "--time-limit", str(seconds), "/sdcard/bb-reel.mp4"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if drive:
        subprocess.run(["sh", drive], timeout=seconds + 60, check=False,
                       env=dict(os.environ, ADB=adb, BB_REEL_SECONDS=str(seconds)))
    rec.wait(timeout=seconds + 60)
    video = os.path.join(out, "screen.mp4")
    r = run([adb, "pull", "/sdcard/bb-reel.mp4", video], timeout=120)
    if r.returncode:
        die(f"could not pull the recording: {(r.stderr or r.stdout).strip()[-200:]}")
    if pkg:
        g = run([adb, "shell", "dumpsys", "gfxinfo", pkg, "framestats"], timeout=30)
        with open(os.path.join(out, "framestats.txt"), "w", encoding="utf-8") as f:
            f.write(g.stdout or "")
    return video


def from_display(display, seconds, drive, out):
    """An X display grabbed with x11grab while xdotool drives it. A server
    install has no X server: Xorg or Xvfb is the provisioner's to add."""
    num = display.lstrip(":").split(".")[0]
    if not num.isdigit() or not os.path.exists(f"/tmp/.X11-unix/X{num}"):
        die(f"no X display {display} on this node: a server install has none, and the "
            "provisioner adds Xvfb and xdotool (nodes/provision-linux.sh); bb reel --display "
            "then records one an app was started on (Xvfb :9 & DISPLAY=:9 the-app &)")
    video = os.path.join(out, "display.mp4")
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
                       env=dict(os.environ, DISPLAY=display, BB_REEL_SECONDS=str(seconds)))
    rec.wait(timeout=seconds + 60)
    if not os.path.exists(video) or os.path.getsize(video) < 100:
        die(f"nothing was recorded from {display}")
    return video


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--video")
    ap.add_argument("--url")
    ap.add_argument("--emu", nargs="?", const="")
    ap.add_argument("--display")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--drive")
    ap.add_argument("--name")
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args()
    picked = [k for k in ("video", "url", "emu", "display") if getattr(a, k) is not None]
    if len(picked) != 1:
        die("one source: --video FILE, --url URL, --emu [PKG] or --display :N")
    base = os.environ.get("BB_REEL_OUT") or os.path.join(os.getcwd(), "dist", "reel")
    name = a.name or (os.path.splitext(os.path.basename(a.video))[0] if a.video
                      else time.strftime("%Y%m%d-%H%M%S"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "reel"
    out = os.path.join(base, name)
    os.makedirs(out, exist_ok=True)
    if a.drive and not os.path.isfile(a.drive):
        die(f"no such driver: {a.drive}")
    drive = os.path.abspath(a.drive) if a.drive else ""
    video = (a.video if a.video else from_url(a.url, a.seconds, drive, out) if a.url
             else from_emu(a.emu, a.seconds, drive, out) if a.emu is not None
             else from_display(a.display, a.seconds, drive, out))
    if a.video and not os.path.isfile(video):
        die(f"no such video: {video}")
    log = reel(video, out, a.threshold, a.fps)
    print(f"[builderbot] {len(log)} frame{'s' if len(log) != 1 else ''} changed"
          + (f" over {log[-1]['t']}s" if log and log[-1]['t'] else "")
          + f": {os.path.join(out, 'sheet.png')} and frames.json beside it", file=sys.stderr)
    for f in log:
        print(f"  {f['frame']:>3}  {f['t'] if f['t'] is not None else '?':>7}s  change {f['change']:.3f}")


if __name__ == "__main__":
    main()
