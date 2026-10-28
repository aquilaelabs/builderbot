"""Scheduled scripts (R117): an administrator's own cron in BuilderBot, as
Unraid's User Scripts are. Each schedule is a script, a timetable in cron's
five fields (said in words: "Sundays at 4:00"), the node it runs on, and
whether it runs there as the node's jobs account or as root (a sandbox node
alone, as `bb root run` is). Every run is a job, its log on the Jobs page.

Kept out of every session's reach: the scripts are in the controller's own
state (<state>/schedules.json, never the share), the API refuses a session's
token, and bb has no verb for them. The page is its own role area
(`schedules`), an administrator's, given to no other role by default.

The timer (tick) fires a schedule's job on the minute it is due; one run of
a schedule at a time, so one still going when the next falls due is said
and that run skipped; and a run the controller was down for is run once
when it comes back and said, never once per minute it missed.

The static analysis scan was the first built-in schedule; since 0.9.0 it
is the Scanners page's own (R145, scanners.py), and migration 0016 moved
an install's scan schedule there.
"""
import calendar
import json
import re
import secrets
import threading
import time
from pathlib import Path

FILE = None                  # <state>/schedules.json, set by configure()
write_json = None
_lock = threading.Lock()

MAX = 64                     # schedules kept
SCRIPT_MAX = 64 * 1024
# A run is stopped after a day unless its schedule says less (the scan's
# four hours): the form asks nothing about it (the operator, 26 Oct), and a
# hung script holds its node's job slot no longer than that.
TIMEOUT_MAX = 24 * 3600
TIMEOUT_DEFAULT = TIMEOUT_MAX
# A tick later than this past a run's minute is a controller that was down
# for it: run once, and say how late.
LATE_S = 180
AS = ("job", "root")
SCAN_ID = "scan"           # the row the built-in scan kept before 0.9.0, unlisted now (migration 0016)
DAYS = ("Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays")
DAY_NAMES = {d[:3].lower(): i for i, d in enumerate(DAYS)}
MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def configure(*, state, write_json):
    globals().update(FILE=Path(state) / "schedules.json", write_json=write_json)


# ---- the timetable -----------------------------------------------------------

# A week's 7 is its Sunday as well as 0, as cron's is.
_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field(text, lo, hi, names=None):
    """One cron field as the set of values it allows, or None when it is
    not one: *, N, A-B, a list of those, each with a /STEP."""
    out = set()
    for part in str(text).lower().split(","):
        base, _, step = part.partition("/")
        if step and not step.isdigit():
            return None
        n = int(step) if step else 1
        if n < 1:
            return None
        if base == "*":
            a, b = lo, hi
        else:
            a_s, _, b_s = base.partition("-")
            vals = []
            for v in (a_s, b_s) if b_s else (a_s,):
                if names and v in names:
                    vals.append(names[v])
                elif v.isdigit():
                    vals.append(int(v))
                else:
                    return None
            a, b = vals[0], vals[-1]
            if not (lo <= a <= hi and lo <= b <= hi and a <= b):
                return None
            if not b_s and not step:
                b = a
        out.update(range(a, b + 1, n))
    return out or None


def parse(expr):
    """(minutes, hours, days of the month, months, days of the week, dom
    named, dow named) for five cron fields, or None."""
    parts = str(expr or "").split()
    if len(parts) != 5:
        return None
    sets = []
    for i, (p, (lo, hi)) in enumerate(zip(parts, _FIELDS, strict=True)):
        s = _field(p, lo, hi, MONTH_NAMES if i == 3 else DAY_NAMES if i == 4 else None)
        if s is None:
            return None
        sets.append({0 if v == 7 else v for v in s} if i == 4 else s)
    return (*sets, parts[2] != "*", parts[4] != "*")


def next_after(expr, after):
    """The next minute after `after` (epoch seconds) the timetable names, in
    this controller's local time, or None. A day matches as cron's does:
    with both its day of the month and its day of the week named, either."""
    p = parse(expr)
    if not p:
        return None
    mins, hours, doms, months, dows, dom_named, dow_named = p
    t = time.localtime(int(after) - int(after) % 60 + 60)
    y, mo, d = t.tm_year, t.tm_mon, t.tm_mday
    for _ in range(366 * 5):
        if mo in months:
            wd = (calendar.weekday(y, mo, d) + 1) % 7      # cron's 0 is Sunday
            day_ok = (d in doms or wd in dows) if dom_named and dow_named \
                else (d in doms) if dom_named else (wd in dows)
            if day_ok:
                for h in sorted(hours):
                    for m in sorted(mins):
                        at = time.mktime((y, mo, d, h, m, 0, 0, 0, -1))
                        if at > after:
                            return int(at)
        d += 1
        if d > calendar.monthrange(y, mo)[1]:
            d, mo = 1, mo + 1
            if mo > 12:
                mo, y = 1, y + 1
    return None


def words(expr):
    """A timetable as a person says it: "every 15 minutes", "hourly at :30",
    "daily at 4:00", "Sundays at 4:00", "on the 1st at 4:00"; the fields
    themselves where none of those says it."""
    p = parse(expr)
    if not p:
        return "not a timetable"
    mins, hours, doms, months, dows, dom_named, dow_named = p
    parts = str(expr).split()
    every_month = len(months) == 12
    one = lambda s: len(s) == 1  # noqa: E731
    at = f"{min(hours)}:{min(mins):02d}" if one(mins) and one(hours) else ""
    if parts[0] == "*" and parts[1] == "*" and not dom_named and not dow_named and every_month:
        return "every minute"
    m = re.fullmatch(r"\*/(\d+)", parts[0])
    if m and parts[1] == "*" and not dom_named and not dow_named and every_month:
        return f"every {m.group(1)} minutes"
    if one(mins) and parts[1] == "*" and not dom_named and not dow_named and every_month:
        return f"hourly at :{min(mins):02d}"
    if not at or not every_month:
        return f"cron {expr}"
    if not dom_named and not dow_named:
        return f"daily at {at}"
    if dow_named and not dom_named:
        if dows == {1, 2, 3, 4, 5}:
            return f"weekdays at {at}"
        return f"{', '.join(DAYS[i] for i in sorted(dows))} at {at}"
    if dom_named and not dow_named and one(doms):
        n = min(doms)
        suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"on the {n}{suf} at {at}"
    return f"cron {expr}"


# ---- the store ------------------------------------------------------------------

def _load():
    try:
        d = json.loads(FILE.read_text())
        if isinstance(d, dict) and isinstance(d.get("schedules"), dict):
            return d
    except (OSError, ValueError, AttributeError):
        pass
    return {"schedules": {}}


def _save(d):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(FILE, d)


def listing():
    """Every schedule, the built-in scan first, each with its words and its
    next run."""
    # The scan's own row, the one built in before 0.9.0, is the Scanners
    # page's now (migration 0016); one left behind is not listed.
    d = {k: v for k, v in _load()["schedules"].items() if k != SCAN_ID}
    rows = d
    now = time.time()
    out = []
    for s in rows.values():
        r = dict(s)
        r["words"] = words(r.get("cron"))
        r["next_at"] = next_after(r.get("cron"), now) if r.get("on") else None
        out.append(r)
    return out


def get(sid):
    return next((s for s in listing() if s["id"] == sid), None)


def _clean(req, was):
    """A schedule as the page sends it, held to its shapes: the fields given
    over what was, each checked, or (None, why)."""
    s = dict(was)
    if "name" in req:
        s["name"] = re.sub(r"\s+", " ", str(req.get("name") or "")).strip()[:80]
        if not s["name"]:
            return None, "a schedule needs a name"
    if "cron" in req:
        cron = re.sub(r"\s+", " ", str(req.get("cron") or "")).strip()
        if not parse(cron):
            return None, ("a timetable is cron's five fields, minute hour day month weekday: "
                          f"'0 4 * * 0' is Sundays at 4:00, not '{cron[:40]}'")
        s["cron"] = cron
    if "node" in req:
        s["node"] = str(req.get("node") or "")[:40]
    if "as" in req:
        if req.get("as") not in AS:
            return None, "a schedule runs as the node's jobs account (job) or as root (root)"
        s["as"] = req["as"]
    if "timeout" in req:
        try:
            s["timeout"] = max(60, min(TIMEOUT_MAX, int(req.get("timeout"))))
        except (TypeError, ValueError):
            return None, "a timeout is a number of seconds"
    if "script" in req:
        script = str(req.get("script") or "")
        if len(script.encode()) > SCRIPT_MAX:
            return None, f"a script is at most {SCRIPT_MAX // 1024} KB"
        if not script.strip():
            return None, "a schedule needs a script"
        s["script"] = script
    if "on" in req:
        s["on"] = req.get("on") is True
    return s, ""


def save(req, by):
    """Add or change one schedule: {schedule} or {error}."""
    sid = str(req.get("id") or "")
    with _lock:
        d = _load()
        rows = d["schedules"]
        if sid:
            was = rows.get(sid) if sid != SCAN_ID else None
            if not was:
                return {"error": "no such schedule" if sid != SCAN_ID else "the scan is the Scanners page's now"}
        else:
            if len(rows) >= MAX:
                return {"error": f"{MAX} schedules are kept, the most there may be"}
            sid = "s_" + secrets.token_hex(4)
            was = {"id": sid, "name": "", "cron": "", "node": "", "as": "job", "timeout": TIMEOUT_DEFAULT,
                   "script": "", "on": True, "by": by, "made": int(time.time())}
            for k in ("name", "cron", "script"):
                if not str(req.get(k) or "").strip():
                    return {"error": f"a new schedule needs its {k}"}
        s, why = _clean(req, was)
        if why:
            return {"error": why}
        if s.get("on") and not s.get("node"):
            return {"error": "pick the node it runs on before it is turned on"}
        s["changed"] = int(time.time())
        s["changed_by"] = by
        # Due from now, never for a minute that went by while it was off.
        s["due"] = next_after(s["cron"], time.time()) if s.get("on") else None
        rows[sid] = s
        _save(d)
        return {"schedule": get(sid)}


def remove(sid):
    with _lock:
        d = _load()
        if sid == SCAN_ID:
            return {"error": "the scan is the Scanners page's now"}
        if d["schedules"].pop(sid, None) is None:
            return {"error": "no such schedule"}
        _save(d)
        return {"ok": True}


def _record(sid, **fields):
    with _lock:
        d = _load()
        rows = d["schedules"]
        s = rows.get(sid)
        if s is None:
            return
        s.update(fields)
        rows[sid] = s
        _save(d)


# ---- running ----------------------------------------------------------------------

def _argv(s):
    """What the job runs: the script, by bash."""
    script = s.get("script") or ""
    env = s.get("env") or {}
    pre = "".join(f"export {k}={json.dumps(v)}\n" for k, v in env.items() if v)
    return ["bash", "-c", pre + script]


def fire(s, by, queue, late="", at=None):
    """One run of a schedule now, through `queue(s, argv, by)`, which answers
    {job} or {error}: the job queued, recorded as the schedule's last run,
    at `at` (the timer's minute) or now."""
    r = queue(s, _argv(s), by)
    _record(s["id"], last={"at": int(time.time() if at is None else at), "job": r.get("job", ""), "error": r.get("error", ""),
                           "late": late, "by": by})
    return r


def tick(queue, job_state, now=None):
    """The timer's minute: every schedule that is on and due fires, unless
    its last run is still going (said, that run skipped), and is due next
    at its next minute after now. `job_state(id)` answers a job's state or
    "". What fired, by id."""
    now = time.time() if now is None else now
    fired = []
    for s in listing():
        if not s.get("on"):
            continue
        raw = _load()["schedules"].get(s["id"]) or {}
        due = raw.get("due")
        if not due:
            _record(s["id"], due=next_after(s["cron"], now))
            continue
        if now < due:
            continue
        nxt = next_after(s["cron"], now)
        last = (raw.get("last") or {}).get("job") or ""
        if last and job_state(last) in ("queued", "assigned", "running"):
            _record(s["id"], due=nxt, skipped={"at": int(now), "due": int(due), "job": last})
            continue
        late = ""
        if now - due > LATE_S:
            late = time.strftime("%a %d %b %H:%M", time.localtime(due))
        fire({**s, **raw}, "schedule", queue, late=late, at=now)
        _record(s["id"], due=nxt)
        fired.append(s["id"])
    return fired


def attention(job_state):
    """The bell's rows (kind schedule): a schedule whose last run failed, or
    could not be queued, or was skipped because the one before was still
    going, each keyed on that run so a dismissal holds until the next."""
    out = []
    for s in listing():
        last, skip = s.get("last") or {}, s.get("skipped") or {}
        if last.get("error"):
            out.append({"kind": "schedule", "id": s["id"], "name": s.get("name", ""), "bad": True,
                        "why": last["error"], "at": last.get("at", 0), "key": f"sched:{s['id']}@{last.get('at', 0)}"})
        elif last.get("job") and job_state(last["job"]) == "failed":
            out.append({"kind": "schedule", "id": s["id"], "name": s.get("name", ""), "bad": True, "job": last["job"],
                        "why": "its last run failed", "at": last.get("at", 0), "key": f"sched:{s['id']}@{last.get('at', 0)}"})
        if skip.get("at") and skip.get("at", 0) > last.get("at", 0):
            out.append({"kind": "schedule", "id": s["id"], "name": s.get("name", ""), "bad": False,
                        "why": "a run was skipped: the one before it was still going", "at": skip["at"],
                        "key": f"sched-skip:{s['id']}@{skip['at']}"})
    return out
