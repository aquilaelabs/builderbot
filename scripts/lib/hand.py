#!/usr/bin/env python3
"""A finger's path through points, for a glide (R127): bb emu touch glide
and bb phone touch glide play what this makes, so a keyboard under test
meets a stroke shaped like a person's rather than a ruler's.

    hand.py X Y X Y... [--hand steady|normal|shaky|ruler] [--seed N] [DIALS]

A person's stroke bows between letters, speeds up between them and slows
over them, passes a letter and comes back, lingers on it, and wobbles all
the way. A glide keyboard decodes a word partly from that shape, so the
straight, even stroke the injectors drew (five letters at 150 ms each, in
straight lines) tested it against input nobody produces (the operator,
5 Oct, watching one). The dials, each with the hand's own value unless
named:

  --curve F       how far the path bows between two points, as a share of
                  the distance between them (0 straight, 1 a wide arc)
  --speed PX      pixels a second along the path, eased into and out of
                  each point the way a reach is (minimum jerk)
  --shake PX      the wobble: low-passed noise of about this many pixels
  --overshoot PX  how far past a point the finger goes before it comes back
  --dwell MS      how long it lingers on each point
  --ms MS         instead of --speed: each leg between two points takes this
  --seed N        the same seed makes the same path again; one is drawn and
                  printed when none is given, so any run can be repeated

The path is a sample every DT ms from the touch down to the lift, as
(ms, x, y) in screen pixels. The first sample is the first point and the
last is the last point exactly, so the key named is the key met. Run as a
script it prints them, one a line, with the summary on stderr.
"""
import math
import random
import sys

DT = 10                 # ms between samples: a touch panel's own rate or finer
MAX_MS = 6000           # a glide longer than this is a mistake in the points or the speed

# The hands. ruler is the stroke the injectors drew before this: straight,
# even, nothing else, for a test that wants exactly the points it names.
HANDS = {
    "ruler": {"curve": 0.0, "speed": 2000, "shake": 0.0, "overshoot": 0, "dwell": 0},
    "steady": {"curve": 0.15, "speed": 1100, "shake": 0.6, "overshoot": 3, "dwell": 40},
    "normal": {"curve": 0.3, "speed": 800, "shake": 1.5, "overshoot": 8, "dwell": 70},
    "shaky": {"curve": 0.5, "speed": 550, "shake": 4.0, "overshoot": 16, "dwell": 110},
}
DEFAULT = "normal"
RANGES = {"curve": (0, 1), "speed": (50, 10000), "shake": (0, 30), "overshoot": (0, 60),
          "dwell": (0, 2000), "ms": (1, 5000)}


def _jerk(u):
    """Minimum-jerk easing, the profile a reach follows: slow out of a
    point, fast between, slow into the next."""
    return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5


def path(points, hand=DEFAULT, seed=None, ms=None, **dials):
    """The samples for a glide through `points` (pairs of screen pixels):
    {"samples": [(ms, x, y), ...], "seed", "hand", "dials", "took_ms",
    "points"}. A bad argument is a ValueError whose message names it."""
    if hand not in HANDS:
        raise ValueError("--hand is one of " + ", ".join(HANDS))
    d = dict(HANDS[hand])
    for k, v in dials.items():
        if k not in d:
            raise ValueError(f"no dial {k}")
        if v is not None:
            d[k] = _within(k, v)
    if ms is not None:
        ms = _within("ms", ms)
    try:
        pts = [(float(x), float(y)) for x, y in points]
    except (TypeError, ValueError) as e:
        raise ValueError("points are X Y pairs, in screen pixels") from e
    if len(pts) < 2:
        raise ValueError("a glide needs at least two points")
    if seed is None:
        seed = random.randrange(1 << 31)
    rng = random.Random(int(seed))
    shake = d["shake"]
    wob = [0.0, 0.0]

    def wobble():
        # A random walk pulled back to the center: a wobble, not static.
        for i in range(2):
            wob[i] = wob[i] * 0.8 + rng.gauss(0, shake * 0.5)
        return wob[0], wob[1]

    samples = [(0, pts[0][0], pts[0][1])]
    t = 0
    prev = pts[0]
    for p in pts[1:]:
        dx, dy = p[0] - prev[0], p[1] - prev[1]
        dist = math.hypot(dx, dy)
        legs = []
        over = d["overshoot"] * rng.uniform(0.3, 1.0) if dist > 0 else 0
        if over > 0:
            past = (p[0] + dx / dist * over, p[1] + dy / dist * over)
            legs = [(prev, past, True), (past, p, False)]
        else:
            legs = [(prev, p, True)]
        total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b, _ in legs) or 1.0
        for a, b, bowed in legs:
            leg = math.hypot(b[0] - a[0], b[1] - a[1])
            dur = ms * leg / total if ms is not None else leg / d["speed"] * 1000
            n = max(1, round(dur / DT))
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if bowed and leg > 0 and d["curve"] > 0:
                px, py = -(b[1] - a[1]) / leg, (b[0] - a[0]) / leg     # perpendicular
                bow = d["curve"] * leg * 0.5 * rng.uniform(-1, 1)
                ctrl = (mid[0] + px * bow, mid[1] + py * bow)
            else:
                ctrl = mid
            for k in range(1, n + 1):
                u = _jerk(k / n)
                x = (1 - u) ** 2 * a[0] + 2 * (1 - u) * u * ctrl[0] + u ** 2 * b[0]
                y = (1 - u) ** 2 * a[1] + 2 * (1 - u) * u * ctrl[1] + u ** 2 * b[1]
                wx, wy = wobble()
                t += DT
                samples.append((t, x + wx, y + wy))
        for _ in range(round(d["dwell"] * rng.uniform(0.6, 1.4) / DT)):
            wx, wy = wobble()
            t += DT
            samples.append((t, p[0] + wx, p[1] + wy))
        prev = p
        if t > MAX_MS:
            raise ValueError(f"that glide would take more than {MAX_MS // 1000} s: fewer points, "
                             "or a faster hand (--speed, or --ms per leg)")
    samples[-1] = (t, pts[-1][0], pts[-1][1])
    samples = [(int(s[0]), int(round(s[1])), int(round(s[2]))) for s in samples]
    return {"samples": samples, "seed": int(seed), "hand": hand, "dials": d, "took_ms": t,
            "points": len(pts)}


def _within(k, v):
    try:
        n = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"--{k} takes a number") from e
    lo, hi = RANGES[k]
    if not lo <= n <= hi:
        raise ValueError(f"--{k} is between {lo} and {hi}")
    return n


def summary(r):
    """One line saying what was sent."""
    return (f"{r['points']} points as a {r['hand']} hand, seed {r['seed']}: "
            f"{len(r['samples'])} samples over {r['took_ms'] / 1000:.2f} s")


FLAGS = ("hand", "seed", "ms", "curve", "speed", "shake", "overshoot", "dwell")


def parse(args):
    """The hand's flags taken out of a verb's arguments: (the rest, the
    keyword arguments for path()). A flag with no value, or a value that is
    not a number, is a ValueError naming it."""
    rest, opts = [], {}
    it = iter(args)
    for a in it:
        name = a[2:] if a.startswith("--") else ""
        if name in FLAGS:
            v = next(it, None)
            if v is None:
                raise ValueError(f"--{name} takes a value")
            if name == "seed":
                try:
                    v = int(v)
                except ValueError as e:
                    raise ValueError("--seed takes a whole number") from e
            elif name != "hand":
                v = _within(name, v)
            opts[name] = v
        else:
            rest.append(a)
    return rest, opts


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0 if argv else 1
    try:
        rest, opts = parse(argv)
        r = path(list(zip(rest[0::2], rest[1::2], strict=True)), **opts)
    except ValueError as e:
        sys.stderr.write(f"[builderbot] ERROR: {e}\n")
        return 1
    for t, x, y in r["samples"]:
        print(t, x, y)
    sys.stderr.write(summary(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
