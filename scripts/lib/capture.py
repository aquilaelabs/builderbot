"""What a session looks with (R95): one capture per source, shared by
`bb capture shot` and `bb capture reel`. A source is anything that draws: a page Playwright
opens, the running emulator's screen, an X display. A shot is that source
at rest (frames a quarter second apart until a second of them match); a
reel is its recording, which reel.py turns into the frames that changed.

As a program: `capture.py shot --emu [PKG] | --display :N [--settle|--now]
[--drive FILE] OUT` takes the picture. BB_CAPTURE_FFMPEG is the ffmpeg binary,
BB_CAPTURE_ADB the emulator's adb, BB_CAPTURE_NODE_PATH and BB_CAPTURE_CHROME what a
page needs, BB_CAPTURE_AUTH the credential a dashboard page takes.
"""
import argparse
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



# ---- one frame of a source, for a shot at rest ----------------------------------

def _adb():
    return os.environ.get("BB_CAPTURE_ADB") or shutil.which("adb") or die(
        "adb is not on this node: bb emu says what the emulator needs")


def emu_ready(adb):
    r = run([adb, "get-state"], timeout=20)
    if r.returncode or "device" not in (r.stdout or ""):
        die("no emulator is running: bb emu start boots one")


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


def drive(script, env):
    """The script that works the surface before the picture, with the
    surface's own handle in its environment ($ADB, or DISPLAY)."""
    if script:
        subprocess.run(["sh", script], timeout=600, check=False, env=dict(os.environ, **env))


def shot(a):
    if a.emu is not None:
        adb = _adb()
        emu_ready(adb)
        if a.emu:
            run([adb, "shell", "monkey", "-p", a.emu, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
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
    print(a.out)


# ---- the sources: each ends with a video file ---------------------------------------

def from_url(url, seconds, drive, out):
    """A page recorded by Playwright while a script drives it, the way bb
    capture shot opens one. The driver gets the page and the seconds it has."""
    node_path, chrome = os.environ.get("BB_CAPTURE_NODE_PATH", ""), os.environ.get("BB_CAPTURE_CHROME", "")
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
                        os.environ.get("BB_CAPTURE_AUTH", "")], input=script, capture_output=True,
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
    adb = os.environ.get("BB_CAPTURE_ADB") or shutil.which("adb") or die(
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
                       env=dict(os.environ, ADB=adb, BB_CAPTURE_SECONDS=str(seconds)))
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
            "provisioner adds Xvfb and xdotool (nodes/provision-linux.sh); bb capture reel --display "
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
                       env=dict(os.environ, DISPLAY=display, BB_CAPTURE_SECONDS=str(seconds)))
    rec.wait(timeout=seconds + 60)
    if not os.path.exists(video) or os.path.getsize(video) < 100:
        die(f"nothing was recorded from {display}")
    return video



def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("what", choices=["shot"])
    ap.add_argument("--emu", nargs="?", const="")
    ap.add_argument("--display")
    ap.add_argument("--drive")
    ap.add_argument("--settle", dest="settle", action="store_true", default=True)
    ap.add_argument("--now", dest="settle", action="store_false")
    ap.add_argument("out")
    a = ap.parse_args()
    if (a.emu is None) == (a.display is None):
        die("one source: --emu [PKG] or --display :N")
    if a.drive and not os.path.isfile(a.drive):
        die(f"no such driver: {a.drive}")
    shot(a)


if __name__ == "__main__":
    main()
