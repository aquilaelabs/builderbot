#!/usr/bin/env python3
"""House rules: what the operator has decided about working on this project.

The notebook already carries three things a session is handed before it types
anything: the roadmap, the open bugs, and Claude's own memories. This is the
fourth, and it is the only one of them the operator writes and a session
cannot. That is the whole point, and it is the line the Briefing tab draws:

    a MEMORY is Claude's, and Claude may rewrite or forget it;
    a RULE is the operator's, and Claude may not.

Both sides write them, the way both sides write the roadmap and the tracker.
What is asymmetric is narrower than "who may write": a session may add a rule
and change or drop ITS OWN, and may not touch one of the operator's. That is
the only guarantee worth having (a session cannot rewrite the instruction it
is being held to), and everything else follows the shape the rest of the
notebook already has.

The first version of this file had no author and no log, and reached for a
wall to make up for it: sessions could not write at all. That was the wrong
fix for the right worry. What makes the roadmap safe to share is not a lock,
it is that every change carries who made it and lands in a history nobody can
quietly edit. So that is what this has now.

Two things still hold the line. bb-tty's claude_scope() denies Edit, Write and
NotebookEdit on the file, so the only way in is a verb that checks ownership;
and the whole-list replace behind the tab is a person's, because a session
rewriting every rule at once is the thing the per-rule check exists to stop.
Read is left alone deliberately: a conditional rule is named in the prompt
and not quoted there, so a session has to be able to go and read one.

WHY NOT CLAUDE.md, which is the obvious first answer: that file is checked in,
so a session can edit its own instructions and does; and it is about the
PROJECT, read by anybody who clones it. A rule about how the operator wants to
be worked with is about the operator. So the split is this: CLAUDE.md describes
the project and either side writes it; rules describe how the operator wants a
session to work here, live in /config, are never committed, and only the
operator writes them.

STANDING AND CONDITIONAL, which is the axis that matters and is not topic.
Everything standing is in the prompt of every session started here, forever,
so the cost is paid again on every conversation, and one project's notebook
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

Same arrangement as roadmap.py and bugs.py: the server or the bb CLI hands over
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
actor = None
STATE = None
FILE = None


def configure(*, write_json, state, actor=None):
    globals().update(write_json=write_json, STATE=Path(state), actor=actor)
    globals()["FILE"] = Path(state) / "rules.json"
    # The approval queue (roadmap #27): see roadmap.configure.
    pending.configure(write_json=write_json, state=state)
    pending.applier("rules", replay)

def _by_whom():
    """{"who": name} for the account behind this change, or {}.

    "you" and "claude" say a person or a session and stop there; with two
    people on a project that answers nothing about which of them it was.
    The Nodes tab's audit has recorded the account since accounts existed
    (server._principal), and this is the same thing for the notebook.
    """
    name = str((actor() if actor else "") or "")[:60]
    return {"who": name} if name else {}



def replay(project, verb, args):
    """A held rule, replayed on approval, or an edit that rode behind one."""
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

# Long enough for a real rule (the worked example that prompted this is four
# short paragraphs) and short enough that nobody pastes a document in.
MAX_TEXT = 2000
MAX_RULES = 40
MAX_TRIGGERS = 12

# Global rules (R63) live under a key no project can be called: a project is a
# directory on the projects share, and `*` is not a name one can have. So the
# same store, the same shapes, the same history and the same triggers serve
# both, and only the reading differs.
GLOBAL = "*"

# The global rules BuilderBot itself ships. Read-only on purpose: the next
# image would bring an edited one back, and a change nobody can see reverted
# is worse than no change, so the operator turns one off instead.
#
# THE LINE BETWEEN THESE AND THE BRIEFING, which is the question worth being
# able to answer: the briefing states what is TRUE of this machine (there is
# no display, the toolchain is the store, you have no sudo), and none of it
# has an on and an off. A rule is an OBLIGATION, so it is a thing the operator
# might scope differently, disagree with, or want to see and turn off, and it
# belongs where they can. Nothing is said in both places, because a session
# that reads it twice pays twice and the two copies drift.
BUILTIN = [
    {"name": "stay-in-project",
     "text": "Work in this project only: never read, write or look for context in"
             " another project under /workspace. If something seems to be"
             " missing, ask."},
    {"name": "ask-do-not-install",
     "text": "Never install a tool with a system package manager: it is invisible"
             " to `bb toolchains` and gone when the node is rebuilt. Say what is"
             " missing; installing is the operator's."},
    {"name": "no-credentials-in-the-repo", "fixed": True,
     "text": "Never write a credential into a repository: not in a test fixture,"
             " not in CI config, not in an .env file that is not gitignored."},
    {"name": "say-what-you-observed", "fixed": True,
     "text": "Report what happened, not what should have: a failed test with its"
             " output, a skipped step as skipped. Never claim a success you did"
             " not see, and never route around a refusal with a local"
             " workaround."},
    {"name": "file-what-you-find",
     "text": "What you notice goes on the record, not only in a reply: a bug"
             " with `bb bug add`, work worth doing with `bb roadmap add`. Tick"
             " items off as you finish them."},
    {"name": "side-quests",
     "text": "A bug met mid-task is fixed only when your own change caused it"
             " or it blocks the work: the smallest fix, in its own commit, said"
             " in the reply. Anything else is filed and left. One level deep:"
             " a bug found while fixing one of those is filed, not chased."},
    {"name": "own-branches",
     "text": "A branch another account's session works on (claude/<their"
             " name>) is theirs: merge, rebase or delete it only when asked"
             " to, after saying whose it is."},
    {"name": "stay-responsive",
     "text": "A test run never holds a reply. Start it in the background;"
             " answer questions while it runs; a change asked for meanwhile is"
             " queued until it ends, and said so."},
    {"name": "ask-before-unshelving",
     "text": "A shelved roadmap item is the operator's decision, whatever a"
             " request sounds like: do not work on it, read for it or draft for"
             " it. `bb roadmap unshelve N WHY` asks for it back; wait for the"
             " approval."},
    {"name": "ship-to-dist",
     "text": "Shippable build output goes in this project's dist/, named with"
             " `bb version --file` and gitignored; nothing else goes there. The"
             " Artifacts tab lists dist/."},
]

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


def _off():
    """The names of the shipped global rules the operator has turned off."""
    with _lock:
        d = load()
    got = (d.get("projects") or {}).get(GLOBAL) or {}
    return {str(n) for n in (got.get("disabled") or [])}


def builtins():
    """The global rules BuilderBot ships, each marked as read-only and
    carrying whether it is currently off."""
    off = _off()
    out = []
    for i, r in enumerate(BUILTIN):
        fixed = bool(r.get("fixed"))
        r = _clean(dict(r), i)
        r["scope"], r["builtin"], r["by"] = "global", True, "builderbot"
        # A fixed rule has no switch: it is not a preference about how work is
        # done but what makes the rest of the record worth reading (a report
        # that is true, a repository with no secret in it). The tab does not
        # list it and a save that names it is ignored, so a session cannot
        # talk anyone into turning it off either.
        r["fixed"] = fixed
        r["disabled"] = (not fixed) and r["name"] in off
        out.append(r)
    return out


def globals_now():
    """Every rule that applies to every project: the shipped ones, then the
    operator's own. What the Controller settings list shows."""
    own = [dict(r, scope="global", builtin=False) for r in rules(GLOBAL)]
    return builtins() + own


def effective(project):
    """What a session in this project actually works under: the global rules
    that are on, then the project's own. One list, because to a session the
    only difference that matters is whether it may change a rule, and the
    marks already say that."""
    if project == GLOBAL:
        return globals_now()
    return [r for r in globals_now() if not r.get("disabled")] + rules(project)


def _clean(r, i):
    """One rule off the wire, with everything it is allowed to carry.

    Triggers are split on whitespace and commas so the field can be typed as
    either; a trigger that is only punctuation is dropped rather than kept as
    a pattern that matches everything it is put beside.
    """
    def bits(v):
        # Both shapes: the tab sends a list it has already split, the CLI and
        # a hand-edited file send the line somebody typed. Taking str() of a
        # list is how "scripts/agent" once became "['scripts/agent']": a
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
    # project root by whoever runs `bb rules check`, which is a session on its
    # own tree, so it is no more than the session could type.
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


def _rev_of(rows):
    """One project's rules as a number that moves when any of them does. The
    same sum revisions() publishes, so what the tab loaded, what the poll
    watches and what a save is checked against are one value."""
    raw = json.dumps(rows or [], sort_keys=True)
    return sum(ord(c) * (i + 1) for i, c in enumerate(raw)) % 1000000007


# What a project with no rules hashes to. The poll used to say 0 for a
# project absent from the file while the payload said this, so the panel
# read itself as behind and fetched its rules (and the code base beside
# them) twice more on every first open (B218).
EMPTY_REV = _rev_of([])


def rev(project):
    """The number a save of this project's rules is checked against."""
    with _lock:
        return _rev_of(((load().get("projects") or {}).get(project) or {}).get("rules") or [])


def replace(project, rules, rev=None, force=False):
    """Write the whole list, which is what the tab's Save sends.

    Whole rather than per-rule because the tab is an editor: somebody rewords
    two rules and reorders them before pressing Save, and replaying that as
    four operations is four chances to land half of it.
    """
    if not isinstance(rules, list):
        return {"error": "expected a list of rules"}
    if len(rules) > MAX_RULES:
        return {"error": f"{MAX_RULES} rules is the limit: every standing one "
                         "is read into every session that starts here"}
    with _lock:
        was = {x.get("name"): x for x in
               ((load().get("projects") or {}).get(project) or {}).get("rules") or []}
    # A saved global rule cannot take a shipped one's name: the built-ins are
    # not in this list, so a collision would shadow one and leave two rules
    # answering to the same `bb rules show`. Suffixed, the way a duplicate
    # inside the list already is.
    keep = []
    # ...and a project's rule cannot take a GLOBAL rule's name, shipped or the
    # operator's. `bb rules show NAME` walks the global rules first, so a
    # project rule that shared one was shadowed by it and could never be read
    # by name. Names carry no other meaning: sharing one is not how a project
    # overrides anything (see block() for what is).
    seen = set(_builtin_names()) if project == GLOBAL else {
        str(x.get("name") or "") for x in globals_now()}
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            continue
        # A rule keeps the author it had. The tab is the operator's, but
        # reading and tidying a session's rule there should not quietly make
        # it theirs. That is a decision, and it has its own button.
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
        # The tab writes the WHOLE list, so a list that moved since it was
        # loaded is somebody else's work about to be overwritten: a rule a
        # session added with `bb rules add`, one an administrator approved
        # from the pending queue, another person's reword (B195). It used to
        # go through, and the log then said "you removed" a rule the person
        # saving had never seen. Checked inside the lock that guards the
        # write, against the number the tab was handed when it loaded, and
        # answered as a conflict rather than an error so the page can show
        # both sides: nothing typed is thrown away by a refusal.
        cur = _rev_of(_project(d, project).get("rules") or [])
        if rev is not None and not force and int(rev) != cur:
            return {"conflict": True, "rev": cur,
                    "error": "these rules changed while you had them open: a session or "
                             "another person wrote to them"}
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
    roadmap.py's, since one merged history is what `bb history` reads."""
    h = d.setdefault("history", {}).setdefault(project, [])
    h.append({"at": int(time.time()),
              "by": "claude" if by == "claude" else "you",
              **_by_whom(),
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
    """One rule, appended. The session's verb; the tab replaces the list.

    A session's rule is marked as its own, which is what lets it change one
    later and what tells the next session, reading the block, that this line
    is a note from a session rather than an instruction from the operator.
    """
    if not str(text or "").strip():
        return {"error": "a rule needs something to say"}
    if project == GLOBAL and by == "claude":
        return {"error": _NOT_YOURS}
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
                                summary=f"{r['name']}: {r['text']}", number=r["name"])
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        if len(rs) >= MAX_RULES:
            return {"error": f"{MAX_RULES} rules is the limit here"}
        r = _clean({"name": name, "text": text, "paths": paths,
                    "words": words, "by": by, "doc": doc, "check": check}, len(rs))
        taken = {x.get("name") for x in rs}
        if project != GLOBAL:
            taken |= {str(x.get("name") or "") for x in globals_now()}
        base, n = r["name"], 2
        while r["name"] in taken:
            r["name"] = f"{base}-{n}"
            n += 1
        rs.append(r)
        _log(d, project, by, {"act": "add", "name": r["name"], "text": r["text"][:200]})
        save(d)
    return {"ok": True, "rule": r}


# Said the way `bb toolchains install` says its refusal: a sentence a session
# can quote back, naming who does it and where, rather than a door that looks
# like a fault.
_NOT_YOURS = ("a global rule reaches every project on this BuilderBot, so only "
              "the operator adds or changes one. Say in your reply what you "
              "would add and why, and they add it in Controller settings")


def _builtin_names():
    return {r["name"] for r in builtins()}


def _switchable_names():
    return {r["name"] for r in builtins() if not r.get("fixed")}


def save_global(rule_list, disabled=None, by="you"):
    """The global rules as the dialog saves them: the operator's own list, and
    which shipped ones are off, in one go.

    One call rather than two because the dialog has one Save, and a built-in
    turned off by a press that half-landed is the state nobody can explain.
    `disabled` of None leaves the shipped ones as they are, so a caller that
    only means to rewrite the list cannot silently switch them all back on.
    """
    r = replace(GLOBAL, rule_list)
    if r.get("error"):
        return r
    if disabled is None:
        return r
    want = {str(n).strip().lower() for n in disabled} & _switchable_names()
    with _lock:
        d = load()
        p = _project(d, GLOBAL)
        was = {str(n) for n in (p.get("disabled") or [])}
        if want != was:
            for n in sorted(want - was):
                _log(d, GLOBAL, by, {"act": "disable", "name": n})
            for n in sorted(was - want):
                _log(d, GLOBAL, by, {"act": "enable", "name": n})
            p["disabled"] = sorted(want)
            save(d)
    return r


def _mine(rs, name, by):
    """The rule by that name, when this writer may change it.

    A session may change its own and not the operator's; the operator may
    change anything. The refusal says which it is rather than pretending the
    rule is not there. "No such rule" for one you can see is the answer that
    sends somebody looking for a typo.
    """
    for i, r in enumerate(rs):
        if r.get("name") == name:
            if by == "claude" and r.get("by") != "claude":
                return None, ("that rule is the operator's: you can read it and "
                              "cannot change it. Say what you think is wrong with "
                              "it in your reply; they edit it on the Briefing tab")
            return i, ""
    return None, f"no rule called {name} here"


def edit(project, name, *, text=None, paths=None, words=None, by="claude",
         doc=None, check=None):
    if project == GLOBAL and by == "claude":
        return {"error": _NOT_YOURS}
    if project == GLOBAL and str(name or "").strip().lower() in _builtin_names():
        return {"error": "that rule ships with BuilderBot and is read-only: turn "
                         "it off in Controller settings rather than editing it"}
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
    if project == GLOBAL and by == "claude":
        return {"error": _NOT_YOURS}
    if project == GLOBAL and str(name or "").strip().lower() in _builtin_names():
        return {"error": "that rule ships with BuilderBot and is read-only: turn "
                         "it off in Controller settings rather than editing it"}
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
    being a rule the session never heard of, which is the worse of the two failures,
    because the session cannot even know to ask.
    """
    rs = effective(project)
    if not rs:
        return ""
    # WHOSE each one is, marked, because a session's own note must not reach
    # the next session wearing the operator's authority. Same reason the
    # roadmap marks the items a session added.
    # Short, because every session pays for it: the one thing it has to
    # carry is whose each rule is.
    out = ["House rules in effect here. * marks a session's own note, which"
           " you may change or drop with `bb rules`; the rest are the"
           " operator's, and you cannot change them, so say in your reply if"
           " one seems wrong."
           + (" A rule marked (global) is set for every project on this"
              " BuilderBot." if any(r.get("scope") == "global" for r in rs) else "")
           # Specific beats general, and it is said rather than computed: a
           # project's rule and a global one that disagree cannot be found by
           # matching their words, and a session is the one reader here that
           # can tell when two pieces of prose contradict. "Say so" is what
           # tells the operator about a conflict nobody spotted while writing.
           + (" Where one of this project's rules and a global one disagree,"
              " follow the project's, and say so in your reply."
              if any(r.get("scope") == "global" for r in rs)
              and any(r.get("scope") != "global" for r in rs) else "")
           + "\n"]
    # A rule with a framework behind it says where it is defined and how it
    # is checked, so the session reads the one and runs the other.
    def frame(r):
        bits = []
        if r.get("scope") == "global":
            bits.append("global")
        if r.get("doc"):
            bits.append(f"defined in full in {r['doc']}, read first")
        if r.get("check"):
            bits.append(f"checked by `bb rules check {r['name']}`, run before handing back")
        return (" (" + "; ".join(bits) + ")") if bits else ""
    for r in rs:
        if not conditional(r):
            out.append((("* " if r.get("by") == "claude" else "")
                        + r["text"] + frame(r)) + "\n")
    named = [r for r in rs if conditional(r)]
    if named:
        # Name and triggers only, no excerpt: the triggers are what say when
        # to read one, and the text arrives whole on the turn a trigger fires
        # (bb-work-note on a covered file, bb-prompt-relay on a word). An
        # excerpt here was ninety characters a session paid for on every
        # conversation and read on none.
        out.append("Named, not quoted: `bb rules show <name>` reads one, and "
                   "its text arrives on the turn you edit a file or are asked "
                   "about a word it names.")
        for r in named:
            on = "; ".join(x for x in [", ".join(r.get("paths") or []),
                                       ", ".join(r.get("words") or [])] if x)
            mine = "*" if r.get("by") == "claude" else ""
            out.append(f"  {mine}{r['name']}: {on}{frame(r)}")
    return "\n".join(out).strip()


def covers(r, path):
    """Whether a rule's files include this repo-relative path, by the same
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
    name is taken as everything under it: `scripts/agent` is what somebody
    types and `scripts/agent/**` is what they mean.
    """
    low = str(prompt or "").lower()
    rel = str(path or "").lstrip("/")
    out = []
    for r in effective(project):
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


def _stem(pat):
    """A path trigger up to its first wildcard, with a bare directory read the
    way matching() reads it: `scripts/agent` means everything under it."""
    pat = str(pat or "").strip().lstrip("/")
    cut = min([pat.find(c) for c in "*?[" if c in pat] or [len(pat)])
    return pat[:cut].rstrip("/")


def _paths_meet(a, b):
    """Could these two path triggers fire on the same file? Equal, one a glob
    the other satisfies, or one's fixed part inside the other's. A pattern with
    no fixed part at all (`*.md`) meets only its equal: it would otherwise
    meet everything, and a note on every row is a note nobody reads."""
    if a == b:
        return True
    if fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
        return True
    sa, sb = _stem(a), _stem(b)
    if not sa or not sb:
        return False
    return sa == sb or sa.startswith(sb + "/") or sb.startswith(sa + "/")


def overlaps(rule, others):
    """Which of `others` fire where `rule` fires, and on what:
    [{"name", "words": [...], "paths": [...]}].

    For the person WRITING a project rule, who until this could not see the
    global ones at all: the conflict worth preventing starts with not knowing
    a rule about the same ground already exists. Mechanical on purpose and
    honest about its limit. It compares triggers, so it says nothing about
    two STANDING rules that disagree in meaning; no matching could, which is
    why precedence is stated to the session as a principle (see block()).
    It decides nothing: both rules still reach the session.
    """
    out = []
    mine_w = {w.lower() for w in rule.get("words") or []}
    mine_p = list(rule.get("paths") or [])
    for o in others:
        w = sorted(mine_w & {x.lower() for x in o.get("words") or []})
        pp = sorted({q for q in o.get("paths") or [] for m in mine_p if _paths_meet(m, q)})
        if w or pp:
            out.append({"name": o.get("name") or "", "words": w, "paths": pp})
    return out


def payload(project):
    """The tab's read: the rules, and what the standing half costs.

    The cost is the point of showing it. "Is this rule worth keeping" is not a
    question anybody can answer without knowing what it is charged for, and
    the charge is on every session started in this project.
    """
    # `rules` stays this project's OWN, because the tab writes that list back
    # whole and a global rule is not its to rewrite. The counts are over what
    # a session is actually handed, global ones included, since that is what
    # the characters are charged for.
    own = rules(project)
    eff = effective(project)
    b = block(project)
    glob = [r for r in eff if r.get("scope") == "global"]
    # Each of the project's rules with the global ones it shares ground with,
    # for the row. Decoration on the way out only: _clean keeps a fixed set
    # of fields, so this never comes back in on a save.
    if project != GLOBAL:
        own = [dict(r, overlaps=overlaps(r, glob)) for r in own]
    return {"project": project, "rules": own,
            "global": glob,
            "standing": sum(1 for r in eff if not conditional(r)),
            "conditional": sum(1 for r in eff if conditional(r)),
            "chars": len(b), "loud": len(b) > LOUD_CHARS, "max": MAX_RULES}


def counts():
    """{project: how many rules}, for the project row, like the rest."""
    with _lock:
        d = load()
    return {p: len(v.get("rules") or [])
            for p, v in (d.get("projects") or {}).items()}


def revisions():
    """{project: a number that moves when the tab has to re-read}.

    The rules themselves, hashed: there is no run or ingest here to count, and
    a length would miss a reword, which is most of what editing a rule is.
    """
    with _lock:
        d = load()
    out = {}
    for p, v in (d.get("projects") or {}).items():
        out[p] = _rev_of(v.get("rules") or [])
    return out
