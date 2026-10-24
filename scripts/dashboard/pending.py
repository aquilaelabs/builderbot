"""What a session wants to add to the notebook, held for the operator.

Per project, the operator says how much they want to be in the loop on what
a session ENTERS into each of the three tabs, meaning a roadmap item, a bug
report or a house rule (roadmap #27, decided 7 Sep):

    auto   it lands as it always has, marked as the session's
    ask    it is held here; the operator approves or denies it on the notebook
    deny   it is refused, with a sentence the session can quote in its reply

Creation only. Modifying what is already on a list (ticking an item off,
noting a bug, rewording a step) passes under every setting: the stale-read
guard and the history already cover those, and the setting is about how
much enters the notebook, not a lock on it. The one exception is a change
aimed at something that is itself still held: details or a step added to a
held roadmap item, a note on a held bug. Those ride behind the record they
depend on, land after it, and are denied with it.

HOLD THE INTENT, NOT THE CHANGE. A record is the call that would have been
made (verb and arguments) plus one line describing it. Approval replays the
call, in order; denial applies nothing. So there is no undo to write, and a
list never shows an entry that was not agreed to. This is the opposite of a
notebook batch (roadmap.py), which lands changes as they happen and defers only
the record of them.

THE NUMBER IS RESERVED WHEN THE RECORD IS HELD, not when it lands. A session
writes `add`, then `info R12`, then `step add R12` (the template tells it
to), so it has to be told the number at once, and the store beside this one
keeps that number out of anyone else's hands until the record is settled. A
denied add leaves a gap in the numbering, which the roadmap already documents
as normal. Rules are keyed by name and reserve nothing.

WHERE THE GATE SITS: in roadmap.add, bugs.add and rules.add, keyed on
by == "claude", not in bb and not in the server. bb imports those modules
directly on the controller, and a node's verbs relay through the server into
the same bb, so the module is the one chokepoint that covers both. The
dashboard's own writes (by="you") never come here. The dependents are the
one piece that lives in bb, because only bb knows the verb and its
arguments; the module sees a closure.

Replays run through `applier`s the three modules register when they are
configured, and a thread-local flag tells their gate the call is a replay
rather than a fresh add, so the record lands instead of being held again,
and the module's own log marks the event approved.

Approving and denying is the operator's, on the notebook or through the
endpoint; a session's token is turned away there (users.may), the same as
for the rules. bb has a read-only `pending` verb on each tab so a session
can see what it has waiting.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import agents  # noqa: E402
import prefs  # noqa: E402

write_json = None
FILE = None
STATE = None

KINDS = ("roadmap", "bugs", "rules", "settings", "design", "wiki")
MODES = ("auto", "ask", "deny")
# What each tab calls an entry, for the refusal and the held line.
NOUN = {"roadmap": "roadmap items", "bugs": "bug reports", "rules": "rules",
        "settings": "build and test settings", "wiki": "wiki pages"}
# Held records per project. A session that files sixty things nobody has
# looked at is a session talking to itself; the limit says so.
MAX_PENDING = 60
MAX_HISTORY = 300
MAX_SUMMARY = 300


def configure(*, write_json, state):
    """Idempotent: every store that gates through here configures it, and
    the first one wins nothing: they all pass the same two values."""
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "pending.json"
    # The mode lives with the project's other settings. Under the dashboard
    # prefs is configured already; under bb it is not, and this is the only
    # reader here.
    if prefs.FILE is None:
        prefs.configure(write_json=write_json, state=state)


_lock = statefile.on(lambda: FILE)

# Replay, per tab: kind -> callable(project, verb, args) -> the module's
# result. Registered by roadmap/bugs/rules.configure, so nothing here imports
# them (they import this).
_apply = {}


def applier(kind, fn):
    _apply[kind] = fn


_tl = threading.local()


def replaying():
    """True while a held call is being replayed, read by the three gates so
    the replay lands rather than being held a second time, and by their logs
    so the event says it was approved."""
    return bool(getattr(_tl, "on", False))


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            d.setdefault("history", {})
            d.setdefault("settled", {})
            d.setdefault("next", 1)
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}, "history": {}, "settled": {}, "next": 1}


def save(d):
    write_json(FILE, d)


def mode(project, kind):
    """auto, ask or deny for one tab of one project; auto unless set."""
    if kind not in KINDS:
        return "auto"
    try:
        return (prefs.get(project).get("gate") or {}).get(kind) or "auto"
    except (OSError, ValueError, TypeError):  # a broken prefs file, or prefs not configured (open(None))
        return "auto"


def refusal(kind):
    """The sentence a session gets under deny: quotable, and it says what
    to do instead."""
    label = {"roadmap": "Add to roadmap", "bugs": "File bugs", "rules": "Add rules",
             "settings": "Fill in build and test", "design": "Add to the design",
             "wiki": "Write the wiki"}.get(kind, kind)
    return (f"this project's setting Agents may: {label} is deny, so this "
            f"was not filed: say it in your reply instead, and the operator adds it "
            "if they agree")


def _log(d, project, ev):
    h = d["history"].setdefault(project, [])
    h.append({"at": int(time.time()), **ev})
    del h[:-MAX_HISTORY]


def hold(project, kind, verb, args, summary, number=None, after=None, by="claude"):
    """Keep one call for the operator. Returns {"held": record}."""
    if kind not in KINDS:
        return {"error": f"not a tab: {kind}"}
    with _lock:
        d = load()
        rs = d["projects"].setdefault(project, [])
        if len(rs) >= MAX_PENDING:
            return {"error": f"{MAX_PENDING} changes are already waiting for the "
                             "operator here; say the rest in your reply"}
        rec = {"id": d["next"], "kind": kind, "verb": verb,
               "args": args if isinstance(args, dict) else {},
               "summary": " ".join(str(summary or "").split())[:MAX_SUMMARY],
               "number": number, "after": after,
               "by": "claude" if by == "claude" else "you", **agents.asker(by),
               "at": int(time.time())}
        d["next"] += 1
        rs.append(rec)
        _log(d, project, {"act": "held", "id": rec["id"], "kind": kind,
                          "number": number, "text": rec["summary"], "by": rec["by"]})
        save(d)
    return {"held": rec}


def held(project, kind, number):
    """The open record that CREATES `number` on `kind`'s tab, or None. How bb
    finds out that R12 is not on the list because it is waiting here."""
    if number is None:
        return None
    with _lock:
        for r in load()["projects"].get(project) or []:
            if r.get("kind") == kind and r.get("verb") == "add" \
                    and str(r.get("number")) == str(number):
                return r
    return None


def listing(project, kind=None):
    with _lock:
        rs = list(load()["projects"].get(project) or [])
    rs.sort(key=lambda r: r.get("id", 0))
    return [r for r in rs if kind is None or r.get("kind") == kind]


def count(project):
    return len(listing(project))


def counts():
    """{project: how many waiting}, for the project row, so the bell and the
    notebook band read it off the poll."""
    with _lock:
        d = load()
    return {p: len(v) for p, v in d["projects"].items() if v}


def revisions():
    """{project: a number that moves when the band has to re-read}: the ids
    waiting plus how many have been settled, which changes on every hold,
    approval and denial."""
    with _lock:
        d = load()
    out = {}
    for p, v in d["projects"].items():
        out[p] = sum(r.get("id", 0) for r in v) * 1000 + len(d["settled"].get(p) or [])
    for p, v in d["settled"].items():
        out.setdefault(p, len(v))
    return out


def _dependents(rs, ids):
    """Every open record that rides behind one of `ids`, transitively."""
    out, frontier = set(), set(ids)
    while frontier:
        nxt = {r["id"] for r in rs if r.get("after") in frontier and r["id"] not in out}
        out |= frontier
        frontier = nxt - out
    return out


def _settle(d, project, rec, act, why="", by="you"):
    s = d["settled"].setdefault(project, [])
    s.append({**rec, "act": act, "why": why, "settled_at": int(time.time()),
              "told": False})
    del s[:-MAX_HISTORY]
    _log(d, project, {"act": act, "id": rec["id"], "kind": rec["kind"],
                      "number": rec.get("number"), "text": rec.get("summary", ""),
                      "by": by, **({"why": why} if why else {})})


def approve(project, ids, by="you"):
    """Replay the chosen records, in the order they were made.

    A record whose parent is still waiting is skipped rather than replayed
    into a list that does not hold its item: the modal ticks the parent by
    default, and the skip says what it waits on. A replay that fails (the
    list is full, the rule's name clashed) is settled as failed with the
    module's own reason, and reported; it is not left waiting, because the
    operator already answered it.
    """
    want = {int(i) for i in ids if str(i).lstrip("-").isdigit()}
    out = {"approved": [], "failed": [], "skipped": []}
    with _lock:
        d = load()
        rs = d["projects"].get(project) or []
        picked = sorted((r for r in rs if r["id"] in want), key=lambda r: r["id"])
        done_ids = set()
        for rec in picked:
            parent = rec.get("after")
            if parent is not None and parent not in done_ids \
                    and any(r["id"] == parent for r in rs):
                out["skipped"].append({"id": rec["id"], "summary": rec["summary"],
                                       "why": f"waits on #{parent}, which is still held"})
                continue
            fn = _apply.get(rec["kind"])
            if fn is None:
                out["failed"].append({"id": rec["id"], "summary": rec["summary"],
                                      "why": f"nothing here can replay a {rec['kind']} change"})
                continue
            _tl.on = True
            try:
                r = fn(project, rec.get("verb"), dict(rec.get("args") or {}))
            except Exception as e:  # noqa: BLE001  (one bad replay must not strand the rest)
                r = {"error": f"{type(e).__name__}: {e}"}
                print(f"dashboard: pending: replay #{rec['id']} on {project} failed: {r['error']}",
                      file=sys.stderr, flush=True)
            finally:
                _tl.on = False
            r = r if isinstance(r, dict) else {"error": "no answer"}
            rs[:] = [x for x in rs if x["id"] != rec["id"]]
            if r.get("error"):
                _settle(d, project, rec, "failed", why=str(r["error"]), by=by)
                out["failed"].append({"id": rec["id"], "summary": rec["summary"],
                                      "why": str(r["error"])})
            else:
                done_ids.add(rec["id"])
                _settle(d, project, rec, "approved", by=by)
                out["approved"].append({"id": rec["id"], "summary": rec["summary"],
                                        "number": rec.get("number")})
        d["projects"][project] = rs
        if not rs:
            d["projects"].pop(project, None)
        save(d)
    return out


def deny(project, ids, by="you"):
    """Drop the chosen records and everything that rode behind them."""
    want = {int(i) for i in ids if str(i).lstrip("-").isdigit()}
    out = {"denied": []}
    with _lock:
        d = load()
        rs = d["projects"].get(project) or []
        gone = _dependents(rs, {r["id"] for r in rs if r["id"] in want})
        for rec in sorted((r for r in rs if r["id"] in gone), key=lambda r: r["id"]):
            why = "" if rec["id"] in want else "denied with the change it depended on"
            _settle(d, project, rec, "denied", why=why, by=by)
            out["denied"].append({"id": rec["id"], "summary": rec["summary"],
                                  "number": rec.get("number")})
        rs = [r for r in rs if r["id"] not in gone]
        d["projects"][project] = rs
        if not rs:
            d["projects"].pop(project, None)
        save(d)
    return out


def settled_line(project):
    """One sentence for the session about what the operator decided since it
    was last told, and told, so the next prompt does not repeat it. "" when
    nothing was decided. Per project rather than per session: normally one
    session works a project, and a second one hearing the news is cheaper
    than the first one never hearing it."""
    with _lock:
        d = load()
        s = d["settled"].get(project) or []
        fresh = [x for x in s if not x.get("told")]
        if not fresh:
            return ""
        for x in fresh:
            x["told"] = True
        save(d)
    bits = []
    for x in fresh:
        what = x.get("summary", "")[:80]
        tag = ""
        if x.get("number") is not None and x.get("kind") in ("roadmap", "bugs"):
            tag = ("R" if x["kind"] == "roadmap" else "B") + str(x["number"]) + " "
        elif x.get("kind") == "rules" and x.get("number"):
            tag = f"rule {x['number']} "
        act = {"approved": "approved", "denied": "denied",
               "failed": "could not be applied"}.get(x.get("act"), x.get("act"))
        why = f" ({x['why']})" if x.get("why") else ""
        bits.append(f"{tag}{what!r} was {act}{why}")
    return ("The operator has answered what you had waiting: "
            + "; ".join(bits) + ".")


def history(project, limit=None, since=None, find=None):
    with _lock:
        h = list(load()["history"].get(project) or [])
    out = sorted(h, key=lambda e: -e.get("at", 0))
    if since is not None:
        out = [e for e in out if e.get("at", 0) >= int(since)]
    if find:
        needle = str(find).lower()
        out = [e for e in out
               if any(needle in str(e.get(k, "")).lower()
                      for k in ("text", "why", "act", "kind"))]
    if limit:
        out = out[:int(limit)]
    return out


def payload(project):
    """What the notebook's band and the review modal draw from."""
    try:
        gate = dict(prefs.get(project).get("gate") or {})
    except (OSError, ValueError, TypeError):  # as mode(): a broken prefs file, or prefs not configured
        gate = {}
    rs = listing(project)
    by_kind = {k: sum(1 for r in rs if r.get("kind") == k) for k in KINDS}
    # The revision of this answer, as revisions() counts it, so the band
    # records what it read and not the page's later token (B201).
    with _lock:
        d = load()
    rev = (sum(r.get("id", 0) for r in d["projects"].get(project) or []) * 1000
           + len(d["settled"].get(project) or []))
    return {"project": project, "pending": rs, "counts": by_kind, "rev": rev,
            "gate": {k: gate.get(k) or "auto" for k in KINDS}}


# ---- the approvals, one call from the dashboard -----------------------------

def verb(name, act, req):
    """Approve or deny what a session has waiting (roadmap #27), once
    server.py has let a PERSON at it: a session approving its own additions
    is the setting not existing. The reply carries what each record became
    (approved, failed with the store's own reason, or skipped because its
    parent is still waiting) and the queue as it now stands, so the modal
    redraws from one answer. (payload, status)."""
    ids_ = req.get("ids") if isinstance(req.get("ids"), list) else []
    if act == "approve":
        r = approve(name, ids_)
    elif act == "deny":
        r = deny(name, ids_)
    else:
        return {"error": "action is approve or deny"}, 400
    return r | payload(name), 200
