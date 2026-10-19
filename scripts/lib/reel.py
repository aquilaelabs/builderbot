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
--threshold T (ffmpeg's scene score, 0..1, against the frame before, that
counts as a change; without it a frame is kept on any small patch changing
from the last frame kept, see PATCH: --patch N is its bar), --max N (how many frames the sheet holds) and
--fps N (how often the recording is looked at: every frame it has unless
this says fewer; see recorded_fps). BB_CAPTURE_OUT is dist/reel,
BB_CAPTURE_FFMPEG the ffmpeg binary, BB_CAPTURE_NODE_PATH and BB_CAPTURE_CHROME what
the page source needs, BB_CAPTURE_ADB the emulator's adb.

Only the sheet and frames.json land in dist/reel/NAME (R96): the recording
and the full-size frames are working files, under the capture's scratch
directory (capture.scratch), which frames.json names in `work` and in each
frame's `file`. frames.json also says who asked and when (capture.maker),
which is what the Artifacts view shows and what the sweep goes by.
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
# The default since R261 (the operator, 17 Oct): a frame is kept when any
# 8x8 patch of it differs from the LAST FRAME KEPT by more than `hi` (ffmpeg's
# mpdecimate), not when the whole frame's score against the frame before it
# passes a bar. Against the frame before, a slow scroll never counted, each
# frame a few pixels on from the last however far the page went; and a whole-
# frame bar dropped a tap circle on a phone recording (a few percent of the
# screen). A patch's bar catches a letter, a tap circle and a cursor alike,
# and the last kept frame catches change that adds up. --threshold asks for
# the scene score instead, at that bar.
# The patch's bar is --patch N, a pixel's mean difference across the patch
# (1 to 255; 12 by default, ffmpeg's own): lower keeps fainter change, higher
# only bolder. Its lower bar and the share of patches past it scale with it.
PATCH = 12


def decimate(patch):
    """The filter for a patch's bar of `patch` (a pixel's mean difference)."""
    hi = max(1, round(patch * 64))
    return f"mpdecimate=hi={hi}:lo={max(1, round(hi * 5 / 12))}:frac=0.33"
# ...and a run of motion (frames kept less than RUN_GAP apart: a scroll, a
# slide) is thinned to where it starts and where it settles and a few frames
# between, so a sheet holds at most MAX_FRAMES and a scroll is not sixty.
MAX_FRAMES = 40
RUN_GAP = 0.15
PAGE_FRAMES = 12              # a sheet page: three rows of four


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


def thin(log, cap=MAX_FRAMES, gap=RUN_GAP):
    """At most `cap` of the kept frames: the first, where each run of motion
    starts and where it settles, and between those frames spaced evenly over
    the time things were moving. A frame dropped here is a working file
    removed; the log keeps the rest, renumbered."""
    if len(log) <= cap:
        return log
    runs, cur = [], [log[0]]
    for f in log[1:]:
        if f["t"] is not None and cur[-1]["t"] is not None and f["t"] - cur[-1]["t"] < gap:
            cur.append(f)
        else:
            runs.append(cur)
            cur = [f]
    runs.append(cur)
    must = {id(r[0]) for r in runs} | {id(r[-1]) for r in runs}
    budget = cap - len(must)
    moving = sum((r[-1]["t"] or 0) - (r[0]["t"] or 0) for r in runs)
    step = moving / budget if budget > 0 and moving > 0 else float("inf")
    keep = []
    for r in runs:
        last = None
        for f in r:
            if id(f) in must or (last is not None and (f["t"] or 0) - last >= step):
                keep.append(f)
                last = f["t"] or 0
    # More runs than the sheet holds: the moments things settled, and the first.
    if len(keep) > cap:
        settled = [log[0]] + [r[-1] for r in runs if r[-1] is not log[0]]
        keep = settled if len(settled) <= cap else [settled[round(i * (len(settled) - 1) / (cap - 1))] for i in range(cap)]
    kept = {id(f) for f in keep}
    for f in log:
        if id(f) not in kept and f.get("file"):
            try:
                os.unlink(f["file"])
            except OSError:
                pass
    for i, f in enumerate(keep):
        f["frame"] = i
    return keep


def detect(video, work, threshold, fps, patch=PATCH, frames=None, span=(None, None)):
    """The frames that changed, as [{t, change, file}]: by default (threshold
    None) the first and each with a patch changed from the last one kept
    (decimate, --patch), its score read against that kept frame; with a
    threshold, each whose scene score against the frame before is over it.
    Written as pictures under `frames`, or none at all (a dry run). `span`
    (--from, --to) looks at that stretch alone, its times the recording's."""
    meta = os.path.join(work, "meta.txt")
    pick = (f"{decimate(patch)},select='gte(scene,0)'" if threshold is None
            else f"select='gt(scene,{threshold})+eq(n,0)'")
    vf = (f"{f'fps={fps},' if fps else ''}{pick},"
          f"metadata=print:file={meta},showinfo")
    # passthrough, not vfr: the image writer runs at 25 a second, and vfr
    # dropped a kept frame landing within a 25th of the one before (77 of
    # 219 in a phone's 53fps scroll, 17 Oct), the times below, read before
    # that drop, then stamping each frame after it with another's time.
    dest = [os.path.join(frames, "%04d.png")] if frames else ["-f", "null", "-"]
    window = ([*(["-ss", f"{span[0]:g}"] if span[0] is not None else []),
               *(["-to", f"{span[1]:g}"] if span[1] is not None else []), "-copyts"]
              if span[0] is not None or span[1] is not None else [])
    r = run([ffmpeg(), "-hide_banner", "-nostdin", *window, "-i", video, "-vf", vf, "-fps_mode", "passthrough", *dest])
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
        os.unlink(meta)
    except OSError:
        pass
    files = sorted(x for x in os.listdir(frames) if x.endswith(".png")) if frames else [None] * len(times)
    return [{"frame": i, "file": os.path.join(frames or "", name) if name else None,
             "t": round(times[i], 2) if i < len(times) else None,
             # One score per kept frame, in order; the first is kept
             # whatever it scored, and its score is against nothing.
             "change": round(scores[i], 5) if i and i < len(scores) else 0.0}
            for i, name in enumerate(files)]


def runs_of(log, gap=RUN_GAP):
    """The runs of motion, as [(start, end, frames)]: frames kept less than
    `gap` apart are one run."""
    out, last = [], None
    for f in log:
        if last is None or f["t"] is None or f["t"] - last >= gap:
            out.append([f["t"], f["t"], 0])
        out[-1][1] = f["t"]
        out[-1][2] += 1
        last = f["t"]
    return [tuple(r) for r in out]


def sheets(log, out, work):
    """The sheet pages: each frame scaled to one width and stamped with its
    time in the corner, four across, PAGE_FRAMES to a page (sheet.png, then
    sheet-2.png and on), so a page stays readable where one sheet of forty
    phone frames was nine thousand pixels tall. Without a font the stamp is
    left off and frames.json is the map from position to time. Returns the
    pages' names."""
    for old in os.listdir(out):
        if re.fullmatch(r"sheet(-\d+)?\.png", old):
            os.unlink(os.path.join(out, old))
    fnt = font()
    stamp = (f",drawtext=fontfile={fnt}:text='%{{pts\\:hms}}':x=8:y=8:fontsize=22:"
             f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6") if fnt else ""
    pages = []
    for p0 in range(0, len(log), PAGE_FRAMES):
        part = log[p0:p0 + PAGE_FRAMES]
        n, rows = len(part), (len(part) + COLS - 1) // COLS
        name = "sheet.png" if not p0 else f"sheet-{p0 // PAGE_FRAMES + 1}.png"
        # The stamps come from the frames' own times: fed back at the same
        # timestamps by concat, so drawtext's pts is the time in the video.
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as f:
            for i, fr in enumerate(part):
                t = fr["t"] or 0.0
                nxt = part[i + 1]["t"] if i + 1 < n and part[i + 1]["t"] is not None else t + 1
                f.write(f"file '{fr['file']}'\nduration {max(0.04, nxt - t):.3f}\n")
            f.write(f"file '{part[-1]['file']}'\n")
        # Each page starts its clock at its first frame's time.
        r = run([ffmpeg(), "-hide_banner", "-nostdin", "-f", "concat", "-safe", "0", "-i", listing,
                 # nb_frames: the list ends with the last frame once more so
                 # its duration counts, and that copy is not a tile.
                 "-vf", f"setpts=PTS+{part[0]['t'] or 0}/TB,scale={WIDTH}:-2{stamp},tile={COLS}x{rows}:nb_frames={n}:padding=4:color=#202020",
                 "-frames:v", "1", "-update", "1", "-y", os.path.join(out, name)])
        if r.returncode:
            die(f"ffmpeg could not tile the sheet: {(r.stderr or '').strip()[-300:]}")
        os.unlink(listing)
        pages.append(name)
    return pages


def dry_run(video, work, threshold, fps, patch=PATCH, cap=MAX_FRAMES, span=(None, None)):
    """What a reel at these settings would hold, nothing drawn: the frames in
    the recording, how many changed, the runs of motion they make, and how
    many the sheet would keep on how many pages."""
    found = detect(video, work, threshold, fps, patch, span=span)
    keep = thin([dict(f) for f in found], cap)
    return {"recorded": frame_count(video), "changed": len(found), "runs": runs_of(found),
            "kept": len(keep), "pages": (len(keep) + PAGE_FRAMES - 1) // PAGE_FRAMES,
            "last": found[-1]["t"] if found else None}


def reel(video, out, work, threshold, fps, patch=PATCH, cap=MAX_FRAMES, span=(None, None)):
    """The frames that changed, stamped and tiled: the sheet pages and
    frames.json into `out` (the reel's directory under dist/), the frames
    themselves under `work`. Returns the log."""
    os.makedirs(out, exist_ok=True)
    frames = os.path.join(work, "frames")
    shutil.rmtree(frames, ignore_errors=True)
    os.makedirs(frames)
    found = detect(video, work, threshold, fps, patch, frames, span)
    log = thin(found, cap)
    pages = sheets(log, out, work) if log else []
    with open(os.path.join(out, "frames.json"), "w", encoding="utf-8") as f:
        # fps: how often it was looked at; recorded_fps: what it had. The
        # same number unless --fps asked for fewer. changed: how many the
        # scan found before a run of motion was thinned to the sheet.
        had = recorded_fps(video)
        json.dump(maker() | {"source": video, "work": work, "threshold": threshold,
                             "method": "scene" if threshold is not None else "decimate",
                             "patch": None if threshold is not None else patch, "max": cap,
                             "from": span[0], "to": span[1],
                             "fps": fps or had, "recorded_fps": had, "changed": len(found),
                             "sheets": pages, "frames": log}, f, indent=1)
    return log


def frame_count(video):
    """How many frames the recording has, counted, or 0."""
    r = run([ffmpeg(), "-hide_banner", "-nostdin", "-i", video, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"])
    m = re.findall(r"frame=\s*(\d+)", r.stderr or "")
    return int(m[-1]) if m else 0


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
    ap.add_argument("--patch", type=float, default=PATCH)
    ap.add_argument("--max", type=int, default=MAX_FRAMES)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--from", dest="start", type=float)
    ap.add_argument("--to", dest="end", type=float)
    a = ap.parse_args()
    picked = [k for k in ("video", "url", "emu", "display") if getattr(a, k) is not None]
    if len(picked) != 1:
        die("one source: --video FILE, --url URL, --emu [PKG] or --display :N")
    if not 1 <= a.patch <= 255:
        die("--patch is a pixel's mean difference across a patch: 1 to 255 (12 by default)")
    if a.max < 2:
        die("--max is how many frames the sheet holds: 2 or more")
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
    # A dry run (the operator, 17 Oct): what a reel at these settings would
    # hold, counted and nothing drawn, so --patch and --max can be chosen
    # before the sheet is made: how many frames changed, how many runs of
    # motion, and how many the sheet would keep on how many pages.
    span = (a.start, a.end)
    if a.dry:
        d = dry_run(video, work, a.threshold, a.fps, a.patch, a.max, span)
        how = f"--threshold {a.threshold:g}" if a.threshold is not None else f"--patch {a.patch:g}"
        runs = d["runs"]
        print(f"[builderbot] dry run at {how}, --max {a.max}: {d['changed']} of {d['recorded']} frames changed"
              + (f" (the last at {d['last']}s)" if d["last"] is not None else "")
              + f", in {len(runs)} run{'s' if len(runs) != 1 else ''} of motion; the sheet would keep {d['kept']}"
              + f" on {d['pages']} page{'s' if d['pages'] != 1 else ''}", file=sys.stderr)
        # Each run with its span and how many frames moved in it: where the
        # thinning takes the most is where --from and --to see it whole.
        for t0, t1, n in runs:
            print(f"  {t0 if t0 is not None else '?':>7}s to {t1 if t1 is not None else '?':>7}s  {n:>4} frame{'s' if n != 1 else ''}")
        if d["kept"] < d["changed"]:
            print(f"[builderbot] {d['changed'] - d['kept']} changed frames would be thinned out of runs of motion"
                  f" (each run keeps where it starts and settles): --from S --to S reels one run whole, and"
                  f" --max higher keeps more of all of them", file=sys.stderr)
        if a.video is None:
            print(f"[builderbot] the recording is at {video}; --video it to reel it without recording again",
                  file=sys.stderr)
        return
    log = reel(video, out, work, a.threshold, a.fps, a.patch, a.max, span)
    with open(os.path.join(out, "frames.json"), encoding="utf-8") as f:
        rec = json.load(f)
    pages = rec.get("sheets") or ["sheet.png"]
    print(f"[builderbot] {len(log)} frame{'s' if len(log) != 1 else ''} changed"
          + (f" over {log[-1]['t']}s" if log and log[-1]['t'] else "")
          + (f" ({rec['changed']} before runs of motion were thinned)" if rec.get("changed", len(log)) > len(log) else "")
          + f": {os.path.join(out, pages[0])}"
          + (f" and {len(pages) - 1} more page{'s' if len(pages) > 2 else ''} ({', '.join(pages[1:])})" if len(pages) > 1 else "")
          + f", frames.json beside it; the frames are under {work}", file=sys.stderr)
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
        print(f"[builderbot] nothing changed: no patch of the screen moved past --patch {a.patch:g} from the "
              f"first frame; a fainter change needs --patch lower" if a.threshold is None else
              f"[builderbot] nothing moved past a scene score of {a.threshold}: a smaller change (a typed "
              f"letter is about 0.0004 on a phone screen) needs --threshold lower, or none at all, which "
              f"keeps any patch that changes", file=sys.stderr)


if __name__ == "__main__":
    main()
