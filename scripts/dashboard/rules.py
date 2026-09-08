#!/usr/bin/env python3
"""House rules: what the operator has decided about working on this project.

The notebook already carries three things a session is handed before it types
anything — the roadmap, the open bugs, and Claude's own memories. This is the
fourth, and it is the only one of them the operator writes and a session
cannot. That is the whole point, and it is the line the Briefing tab draws:

    a MEMORY is Claude's, and Claude may rewrite or forget it;
    a RULE is the operator's, and Claude may not.

Both sides write them, the way both sides write the roadmap and the tracker.
What is asymmetric is narrower than "who may write": a session may add a rule
and change or drop ITS OWN, and may not touch one of the operator's. That is
the only guarantee worth having — a session cannot rewrite the instruction it
is being held to — and everything else follows the shape the rest of the
notebook already has.

The first version of this file had no author and no log, and reached for a
wall to make up for it: sessions could not write at all. That was the wrong
fix for the right worry. What makes the roadmap safe to share is not a lock,
it is that every change carries who made it and lands in a history nobody can
quietly edit — so that is what this has now.

Two things still hold the line. bb-tty's claude_scope() denies Edit, Write and
NotebookEdit on the file, so the only way in is a verb that checks ownership;
and the whole-list replace behind the tab is a person's, because a session
rewriting every rule at once is the thing the per-rule check exists to stop.
Read is left alone deliberately — a conditional rule is named in the prompt
and not quoted there, so a session has to be able to go and read one.

WHY NOT CLAUDE.md, which is the obvious first answer: that file is checked in,
so a session can edit its own instructions and does; and it is about the
PROJECT, read by anybody who clones it. A rule about how the operator wants to
be worked with is about the operator. So the split is — CLAUDE.md describes
the project and either side writes it; rules describe how the operator wants a
session to work here, live in /config, are never committed, and only the
operator writes them.

STANDING AND CONDITIONAL, which is the axis that matters and is not topic.
Everything standing is in the prompt of every session started here, forever,
so the cost is paid again on every conversation — one project's notebook
reached 16KB and made its sessions unstartable. A rule that only matters when
somebody touches the agent should not be paid for on a CSS change. So a rule
with a trigger is CONDITIONAL: the standing block carries one line naming it,
and its text arrives on the turn the trigger fires, through the two hooks that
already exist for exactly this kind of aside (bb-prompt-relay reads the
prompt, bb-work-note sees the file about to be edited).

There is no kind field. A rule is conditional exactly when it has a trigger,
because two ways to say the same thing is two things to keep in step.

The honest limit, which the tab states rather than implying otherwise: this is
not the sibling-project deny list. That one is a refusal from the file tools.
A rule is a request the model can still fumble.

Same arrangement as todo.py and bugs.py: the server or the bb CLI hands over
write_json and the state directory; nothing here reaches back.
"""
import fnmatch
import json
import os
import re
import sys
import time

# `bb` execs this module by path, so its directory is not on sys.path the way
# it is for the dashboard's own import. Same reasoning as bugs.py: one module
# object per process, because statefile's in-process half is a dict in there.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import pending  # noqa: E402
from pathlib import Path  # noqa: E402

write_json = None
STATE = None
FILE = None


def configure(*, write_json, state):
    globals().update(write_json=write_json, STATE=Path(state))
    globals()["FILE"] = Path(state) / "rules.json"
    # The approval queue (roadmap #27) — see todo.configure.
    pending.configure(write_json=write_json, state=state)
    pending.applier("rules", replay)


def replay(project, verb, args):
    """A held rule, replayed on approval — or an edit that rode behind one."""
    if verb == "add":
        return add(project, args.get("name", ""), args.get("text", ""),
                   paths=args.get("paths", ""), words=args.get("words", ""), by="claude",
                   doc=args.get("doc", ""), check=args.get("check", ""))
    if verb == "edit":
        return edit(project, args.get("name", ""), text=args.get("text"),
                    paths=args.get("paths"), words=args.get("words"), by="claude",
                    doc=args.get("doc"), check=args.get("check"))
    return {"error": f"not a rules change that can be replayed: {verb}"}


# flock on the file itself, so a `bb` process and the dashboard wait for each
# other rather than overwriting. See statefile.py; bugs.py's comment has the
# measurement that made it a lock rather than a threading.Lock.
_lock = statefile.on(lambda: FILE)

# A name is what the standing block calls a conditional rule and what
# `bb rules show` takes, so it has to be typeable and stable.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# Long enough for a real rule — the worked example that prompted this is four
# short paragraphs — and short enough that nobody pastes a document in.
MAX_TEXT = 2000
MAX_RULES = 40
MAX_TRIGGERS = 12

# What the standing block costs before it is worth saying out loud on the tab.
# Not a refusal: the operator decides what their sessions are worth paying
# for. This is the number that makes that a decision rather than a surprise.
LOUD_CHARS = 1500


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def save(d):
    write_json(FILE, d)


def _project(d, name):
    return d["projects"].setdefault(name, {"rules": []})


def _clean(r, i):
    """One rule off the wire, with everything it is allowed to carry.

    Triggers are split on whitespace and commas so the field can be typed as
    either; a trigger that is only punctuation is dropped rather than kept as
    a pattern that matches everything it is put beside.
    """
    def bits(v):
        # Both shapes: the tab sends a list it has already split, the CLI and
        # a hand-edited file send the line somebody typed. Taking str() of a
        # list is how "scripts/agent" once became "['scripts/agent']" — a
        # trigger that matches nothing and looks like it should.
        if isinstance(v, (list, tuple)):
            parts = [str(x) for x in v]
        else:
            parts = re.split(r"[,\s]+", str(v or ""))
        parts = [p.strip() for p in parts]
        return [p for p in parts if p and re.search(r"[A-Za-z0-9]", p)][:MAX_TRIGGERS]

    # Slugged rather than refused: somebody types "agent compat" and means
    # agent-compat, and handing them back "rule-2" for a space is the kind of
    # small rudeness that makes a surface feel like it is arguing.
    name = re.sub(r"[^a-z0-9]+", "-", str(r.get("name") or "").strip().lower())
    name = name.strip("-")[:40].strip("-")
    if not NAME_RE.match(name):
        name = f"rule-{i + 1}"
    # A framework's two halves (roadmap R31): the document in the repo that
    # defines it in full, and the command that verifies it. A path is kept
    # repo-relative and cannot climb; a command is any line, run from the
    # project root by whoever runs `bb rules check` — a session, on its own
    # tree — so it is no more than the session could type.
    doc = str(r.get("doc") or "").strip().replace("\\", "/").lstrip("/")[:200]
    if ".." in doc.split("/"):
        doc = ""
    return {"name": name,
            "text": str(r.get("text") or "").strip()[:MAX_TEXT],
            "paths": bits(r.get("paths")),
            "words": [w.lower() for w in bits(r.get("words"))],
            "doc": doc,
            "check": " ".join(str(r.get("check") or "").split())[:300],
            # Whose it is, and therefore who may change it later. Defaulting
            # to the operator is deliberate: this field arrived after rules
            # did, and a rule written before it existed was written on the
            # tab, which is theirs.
            "by": "claude" if r.get("by") == "claude" else "you",
            "at": int(r.get("at") or time.time())}


def conditional(r):
    """A rule is conditional exactly when it has something to fire on."""
    return bool(r.get("paths") or r.get("words"))


def replace(project, rules):
    """Write the whole list, which is what the tab's Save sends.

    Whole rather than per-rule because the tab is an editor: somebody rewords
    two rules and reorders them before pressing Save, and replaying that as
    four operations is four chances to land half of it.
    """
    if not isinstance(rules, list):
        return {"error": "expected a list of rules"}
    if len(rules) > MAX_RULES:
        return {"error": f"{MAX_RULES} rules is the limit — every standing one "
                         "is read into every session that starts here"}
    with _lock:
        was = {x.get("name"): x for x in
               ((load().get("projects") or {}).get(project) or {}).get("rules") or []}
    keep, seen = [], set()
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        # A rule keeps the author it had. The tab is the operator's, but
        # reading and tidying a session's rule there should not quietly make
        # it theirs — that is a decision, and it has its own button.
        prev = was.get(str(r.get("name") or "").strip().lower())
        c = _clean({**r, "by": r.get("by") or (prev or {}).get("by")}, i)
        if not c["text"]:
            continue                       # an empty rule is a deleted one
        # Names are how a conditional rule is referred to and read, so two of
        # them cannot share one. Suffixed rather than refused: the operator is
        # mid-edit and losing the text would be the worse answer.
        base, n = c["name"], 2
        while c["name"] in seen:
            c["name"] = f"{base}-{n}"
            n += 1
        seen.add(c["name"])
        keep.append(c)
    with _lock:
        d = load()
        before = {x.get("name") for x in (_project(d, project).get("rules") or [])}
        now = {x["name"] for x in keep}
        for n in sorted(now - before):
            _log(d, project, "you", {"act": "add", "name": n})
        for n in sorted(before - now):
            _log(d, project, "you", {"act": "remove", "name": n})
        if now & before:
            _log(d, project, "you", {"act": "save", "name": "",
                                     "text": f"{len(now & before)} kept"})
        _project(d, project)["rules"] = keep
        save(d)
    return {"ok": True, "n": len(keep)}


MAX_HISTORY = 300


def _log(d, project, by, ev):
    """Record one change, inside the lock and before the save it describes, so
    the record and the change land together or neither does. Same shape as
    todo.py's — one merged history is what `bb history` reads."""
    h = d.setdefault("history", {}).setdefault(project, [])
    h.append({"at": int(time.time()),
              "by": "claude" if by == "claude" else "you",
              **({"approved": True} if pending.replaying() else {}), **ev})
    del h[:-MAX_HISTORY]


def history(project, limit=None, since=None, find=None):
    with _lock:
        d = load()
    rows = list((d.get("history") or {}).get(project) or [])
    if since:
        rows = [r for r in rows if r.get("at", 0) >= since]
    if find:
        f = str(find).lower()
        rows = [r for r in rows
                if any(f in str(r.get(k, "")).lower()
                       for k in ("name", "text", "why", "act"))]
    rows.sort(key=lambda r: -r.get("at", 0))
    return rows[:limit] if limit else rows


def add(project, name, text, paths="", words="", by="claude", doc="", check=""):
    """One rule, appended. The session's verb — the tab replaces the list.

    A session's rule is marked as its own, which is what lets it change one
    later and what tells the next session, reading the block, that this line
    is a note from a session rather than an instruction from the operator.
    """
    if not str(text or "").strip():
        return {"error": "a rule needs something to say"}
    # The gate (roadmap #27): a session's rule may be held or refused per
    # project. Keyed by the name it would get, which the replay re-derives.
    if by == "claude" and not pending.replaying():
        g = pending.mode(project, "rules")
        if g == "deny":
            return {"error": pending.refusal("rules")}
        if g == "ask":
            r = _clean({"name": name, "text": text, "paths": paths,
                        "words": words, "by": by, "doc": doc, "check": check}, 0)
            return pending.hold(project, "rules", "add",
                                {"name": r["name"], "text": text,
                                 "paths": paths, "words": words, "doc": doc, "check": check},
                                summary=f"{r['name']} — {r['text']}", number=r["name"])
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        if len(rs) >= MAX_RULES:
            return {"error": f"{MAX_RULES} rules is the limit here"}
        r = _clean({"name": name, "text": text, "paths": paths,
                    "words": words, "by": by, "doc": doc, "check": check}, len(rs))
        taken = {x.get("name") for x in rs}
        base, n = r["name"], 2
        while r["name"] in taken:
            r["name"] = f"{base}-{n}"
            n += 1
        rs.append(r)
        _log(d, project, by, {"act": "add", "name": r["name"], "text": r["text"][:200]})
        save(d)
    return {"ok": True, "rule": r}


def _mine(rs, name, by):
    """The rule by that name, when this writer may change it.

    A session may change its own and not the operator's; the operator may
    change anything. The refusal says which it is rather than pretending the
    rule is not there — "no such rule" for one you can see is the answer that
    sends somebody looking for a typo.
    """
    for i, r in enumerate(rs):
        if r.get("name") == name:
            if by == "claude" and r.get("by") != "claude":
                return None, ("that rule is the operator's — you can read it and "
                              "cannot change it. Say what you think is wrong with "
                              "it in your reply; they edit it on the Briefing tab")
            return i, ""
    return None, f"no rule called {name} here"


def edit(project, name, *, text=None, paths=None, words=None, by="claude",
         doc=None, check=None):
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        i, why = _mine(rs, str(name or "").strip().lower(), by)
        if why:
            return {"error": why}
        was = dict(rs[i])
        merged = dict(was)
        for k, v in (("text", text), ("paths", paths), ("words", words),
                     ("doc", doc), ("check", check)):
            if v is not None:
                merged[k] = v
        rs[i] = _clean(merged, i)
        rs[i]["name"] = was["name"]          # renaming is not what edit is for
        rs[i]["by"] = was.get("by", "you")
        _log(d, project, by, {"act": "edit", "name": was["name"],
                              "text": rs[i]["text"][:200], "was": was["text"][:200]})
        save(d)
    return {"ok": True, "rule": rs[i]}


def remove(project, name, why="", by="claude"):
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        i, bad = _mine(rs, str(name or "").strip().lower(), by)
        if bad:
            return {"error": bad}
        gone = rs.pop(i)
        _log(d, project, by, {"act": "remove", "name": gone["name"],
                              "text": gone["text"][:200], "why": str(why or "")[:300]})
        save(d)
    return {"ok": True, "removed": gone["name"]}


def rules(project):
    with _lock:
        d = load()
    got = (d.get("projects") or {}).get(project) or {}
    return [r for r in (got.get("rules") or []) if isinstance(r, dict)]


def block(project):
    """What goes in front of every session started here, or "".

    Standing rules in full; conditional ones as one line each saying they
    exist and how to read them. That line is what stops a trigger that misses
    being a rule the session never heard of — the worse of the two failures,
    because the session cannot even know to ask.
    """
    rs = rules(project)
    if not rs:
        return ""
    # WHOSE each one is, marked, because a session's own note must not reach
    # the next session wearing the operator's authority. Same reason the
    # roadmap marks the items a session added.
    out = ["House rules for this project. The ones marked [yours] are notes a"
           " session left; you may change or drop those with `bb rules`. The"
           " rest are the operator's — you can read them and cannot change"
           " them, and if one seems wrong the move is to say so in your"
           " reply.\n"]
    # A rule with a framework behind it says where it is defined and how it
    # is checked, so the session reads the one and runs the other.
    def frame(r):
        bits = []
        if r.get("doc"):
            bits.append(f"defined in full in {r['doc']} — read it before this work")
        if r.get("check"):
            bits.append(f"checked by `bb rules check {r['name']}` — run it before calling the work done")
        return (" (" + "; ".join(bits) + ")") if bits else ""
    for r in rs:
        if not conditional(r):
            out.append((("[yours] " if r.get("by") == "claude" else "")
                        + r["text"] + frame(r)) + "\n")
    named = [r for r in rs if conditional(r)]
    if named:
        out.append("These apply to particular work rather than to everything, "
                   "so they are named here and not quoted. Read one with "
                   "`bb rules show <name>` when it is relevant — and you will "
                   "also be told, on the turn it becomes relevant:")
        for r in named:
            first = (r["text"].strip().splitlines() or [""])[0]
            mine = "[yours] " if r.get("by") == "claude" else ""
            out.append(f"  {r['name']} — {mine}{first[:90]}{frame(r)}")
    return "\n".join(out).strip()


def covers(r, path):
    """Whether a rule's files include this repo-relative path — the same
    reading `matching` gives a file about to be edited: a glob, or a bare
    directory meaning everything under it."""
    for pat in r.get("paths") or []:
        pat = pat.strip().rstrip("/")
        if not pat:
            continue
        if fnmatch.fnmatch(path, pat) or path == pat or path.startswith(pat + "/"):
            return True
    return False


def matching(project, *, prompt="", path=""):
    """The conditional rules a prompt or a file about to be edited fires.

    Words match on a word boundary rather than as substrings: a rule triggered
    by "node" should not fire on "nodes.py" being mentioned in passing, and
    should not fire on the word "anode" at all.

    Paths are globs against the project-relative path, and a bare directory
    name is taken as everything under it — `scripts/agent` is what somebody
    types and `scripts/agent/**` is what they mean.
    """
    low = str(prompt or "").lower()
    rel = str(path or "").lstrip("/")
    out = []
    for r in rules(project):
        if not conditional(r):
            continue
        hit = any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low)
                  for w in r.get("words") or []) if low else False
        if not hit and rel:
            for g in r.get("paths") or []:
                pat = g if any(c in g for c in "*?[") else g.rstrip("/") + "/**"
                if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, g):
                    hit = True
                    break
        if hit:
            out.append(r)
    return out


def payload(project):
    """The tab's read: the rules, and what the standing half costs.

    The cost is the point of showing it. "Is this rule worth keeping" is not a
    question anybody can answer without knowing what it is charged for, and
    the charge is on every session started in this project.
    """
    rs = rules(project)
    b = block(project)
    return {"project": project, "rules": rs,
            "standing": sum(1 for r in rs if not conditional(r)),
            "conditional": sum(1 for r in rs if conditional(r)),
            "chars": len(b), "loud": len(b) > LOUD_CHARS, "max": MAX_RULES}


def counts():
    """{project: how many rules} — for the project row, like the rest."""
    with _lock:
        d = load()
    return {p: len(v.get("rules") or [])
            for p, v in (d.get("projects") or {}).items()}


def revisions():
    """{project: a number that moves when the tab has to re-read}.

    The rules themselves, hashed: there is no run or ingest here to count, and
    a length would miss a reword — which is most of what editing a rule is.
    """
    with _lock:
        d = load()
    out = {}
    for p, v in (d.get("projects") or {}).items():
        raw = json.dumps(v.get("rules") or [], sort_keys=True)
        out[p] = sum(ord(c) * (i + 1) for i, c in enumerate(raw)) % 1000000007
    return out
