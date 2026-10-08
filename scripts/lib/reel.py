"""Behind `bb capture reel` (cmd_capture in bb): eyes on change over time (R95).

A screenshot shows one moment; what a session cannot see is an element
popping in or a transition. So: the frames of a recording that CHANGED,
each stamped with its time, tiled into one sheet a session reads at a
glance, beside a JSON of when each change came and how much moved. The
source is anything that draws: a video file, a page Playwright records
while a script drives it, the emulator's screenrecord, an X display.

Arguments: the source (--video FILE | --url URL | --emu PKG | --display :N),
--seconds N for a recording, --drive FILE for the script that works the
surface meanwhile, --name NAME for the reel's directory under dist/reel/,
--threshold T (ffmpeg's scene score, 0..1, that counts as a change; see
THRESHOLD for the defaults) and
--fps N (how often the recording is looked at: every frame it has unless
this says fewer; see recorded_fps). BB_CAPTURE_OUT is dist/reel,
BB_CAPTURE_FFMPEG the ffmpeg binary, BB_CAPTURE_NODE_PATH and BB_CAPTURE_CHROME what
the page source needs, BB_CAPTURE_ADB the emulator's adb.

Only the sheet and frames.json land in dist/reel/NAME (R96): the recording
and the full-size frames are working files, under the capture's scratch
directory (capture.scratch), which frames.json names in `work` and in each
frame's `file`. frames.json also says who asked and when (capture.maker),
which is what the Artifacts tab shows and what the sweep goes by.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

COLS, WIDTH = 4, 480          # the sheet: four frames across, each 480px wide


from capture import die, ffmpeg, font, from_display, from_emu, from_url, maker, run, scratch  # noqa: F401


# ---- the reel itself: from a video to a sheet and a log ------------------------

# What counts as a change, by source. ffmpeg's scene score is the whole
# frame's mean difference, so it scales with how much of the screen moved:
# measured on a 1080x2400 keyboard screen (30 Sep), a typed letter scores
# about 0.0004, a key's preview bubble 0.0026, a blinking text cursor 0.0001,
# and a still frame 0.00005. At 0.02 every one of those was dropped, and a
# reel of eight seconds of typing was one frame (Shebang-DevBoard, 30 Sep).
# The emulator's is 0.0002: every letter, not the cursor. A page and an X
# display keep 0.02, where a change is usually a region and a browser's
# encoder is noisier; --threshold asks for another.
THRESHOLD = {"emu": 0.0002}
THRESHOLD_DEFAULT = 0.02


def recorded_fps(video):
    """Frames a second the recording actually has, measured, or 0.0.

    Counted rather than read off the header: screenrecord writes variable
    frame rate, and its header's rate is a ceiling, not what it managed.
    Under software rendering the emulator manages about 10; on a card,
    several times that. The reel used to look at every recording 10 times
    a second whatever it had, so a 60fps capture of a keyboard's slide was
    cut back to the 10fps a software one had (Shebang-DevBoard, 1 Oct)."""
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-i", video, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"])
    err = r.stderr or ""
    frames = re.findall(r"frame=\s*(\d+)", err)
    # The input's whole duration, not the time= of the last frame copied,
    # which stops a frame short and read 10 as 10.5.
    secs = (re.findall(r"Duration:\s*(\d+):(\d+):([0-9.]+)", err)
            or re.findall(r"time=(\d+):(\d+):([0-9.]+)", err))
    if not frames or not secs:
        return 0.0
    h, m, s = secs[-1]
    t = int(h) * 3600 + int(m) * 60 + float(s)
    return round(int(frames[-1]) / t, 1) if t > 0 else 0.0


def reel(video, out, work, threshold, fps):
    """The frames that changed, stamped and tiled: the sheet and frames.json
    into `out` (the reel's directory under dist/), the frames themselves
    under `work`. Returns the log."""
    os.makedirs(out, exist_ok=True)
    frames = os.path.join(work, "frames")
    shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames)
    meta = os.path.join(work, "meta.txt")
    # ffmpeg picks the frames: the first, and each whose scene score against
    # the one before is over the threshold. `metadata=print` writes that
    # score per kept frame and showinfo its time; both are read back below.
    vf = (f"{f'fps={fps},' if fps else ''}select='gt(scene,{threshold})+eq(n,0)',"
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
        log.append({"frame": i, "file": os.path.join(frames, name),
                    "t": round(times[i], 2) if i < len(times) else None,
                    # One score per kept frame, in order; the first is kept
                    # whatever it scored, and its score is against nothing.
                    "change": round(scores[i], 5) if i and i < len(scores) else 0.0})
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
        listing = os.path.join(work, "list.txt")
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
        # fps: how often it was looked at; recorded_fps: what it had. The
        # same number unless --fps asked for fewer.
        had = recorded_fps(video)
        json.dump(maker() | {"source": video, "work": work, "threshold": threshold,
                             "fps": fps or had, "recorded_fps": had,
                             "frames": log}, f, indent=1)
    return log


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--video")
    ap.add_argument("--url")
    ap.add_argument("--emu", nargs="?", const="")
    ap.add_argument("--display")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--drive")
    ap.add_argument("--name")
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--fps", type=int, default=0)
    a = ap.parse_args()
    picked = [k for k in ("video", "url", "emu", "display") if getattr(a, k) is not None]
    if len(picked) != 1:
        die("one source: --video FILE, --url URL, --emu [PKG] or --display :N")
    if a.threshold is None:
        a.threshold = THRESHOLD.get(picked[0], THRESHOLD_DEFAULT)
    base = os.environ.get("BB_CAPTURE_OUT") or os.path.join(os.getcwd(), "dist", "reel")
    name = a.name or (os.path.splitext(os.path.basename(a.video))[0] if a.video
                      else time.strftime("%Y%m%d-%H%M%S"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "reel"
    out = os.path.join(base, name)
    os.makedirs(out, exist_ok=True)
    if a.drive and not os.path.isfile(a.drive):
        die(f"no such driver: {a.drive}")
    if a.video and not os.path.isfile(a.video):
        die(f"no such video: {a.video}")
    drive = os.path.abspath(a.drive) if a.drive else ""
    work = scratch(name)
    video = (a.video if a.video else from_url(a.url, a.seconds, drive, work) if a.url
             else from_emu(a.emu, a.seconds, drive, work, out) if a.emu is not None
             else from_display(a.display, a.seconds, drive, work))
    log = reel(video, out, work, a.threshold, a.fps)
    print(f"[builderbot] {len(log)} frame{'s' if len(log) != 1 else ''} changed"
          + (f" over {log[-1]['t']}s" if log and log[-1]['t'] else "")
          + f": {os.path.join(out, 'sheet.png')} and frames.json beside it; the frames are under {work}",
          file=sys.stderr)
    for f in log:
        print(f"  {f['frame']:>3}  {f['t'] if f['t'] is not None else '?':>7}s  change {f['change']:.5f}")
    # What a frame here is worth: a 250 ms slide is two or three frames of a
    # software-rendered emulator, so where the recording is that sparse the
    # reel says so, and where the real timing is.
    had = recorded_fps(video)
    if had and had < 20:
        print(f"[builderbot] the recording has about {had:g} frames a second, so anything shorter than "
              f"{1000 / had:.0f} ms can fall between two of them"
              + (": framestats.txt beside the reel has the app's own frame timing" if a.emu is not None
                 else "") + "; a reel does not show motion finer than that", file=sys.stderr)
    # One frame is the first one alone: nothing moved enough to count, which
    # is not the same as nothing having happened, and says how to look closer.
    if len(log) == 1:
        print(f"[builderbot] nothing moved past a scene score of {a.threshold}: a smaller change (a typed "
              f"letter is about 0.0004 on a phone screen) needs --threshold lower", file=sys.stderr)


if __name__ == "__main__":
    main()
