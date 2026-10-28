#!/usr/bin/env python3
"""House rules: what the operator has decided about working on this project.

The notebook already carries three things a session is handed before it types
anything: the roadmap, the open bugs, and Claude's own memories. This is the
fourth, and it is the only one of them the operator writes and a session
cannot. That is the whole point, and it is the line the Briefing tab draws:

    a MEMORY is the session's, and an agent may rewrite or forget it;
    a RULE is the operator's, and an agent may not.

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
A rule is a request the model can still fumble, except where it names the
commands it refuses (R200): those a hook stops on a session's shell call,
with the rule as the reason (bb-rule-hook, scripts/lib/cmdmatch.py).

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
import agents  # noqa: E402
import pending  # noqa: E402
import share  # noqa: E402
# The shell reader the guard on a node uses too (scripts/lib, which a node
# carries where it does not carry this directory).
_lib = os.path.join(os.path.dirname(_here), "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)
import rulehook  # noqa: E402
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
    The Nodes page's audit has recorded the account since accounts existed
    (server._principal), and this is the same thing for the notebook.
    """
    name = str((actor() if actor else "") or "")[:60]
    return {"who": name} if name else {}



def replay(project, verb, args):
    """A held rule, replayed on approval, or an edit that rode behind one."""
    if verb == "add":
        return add(project, args.get("name", ""), args.get("text", ""),
                   paths=args.get("paths", ""), words=args.get("words", ""), by="claude",
                   doc=args.get("doc", ""), check=args.get("check", ""),
                   refuse=args.get("refuse", ""), replaces=args.get("replaces", ""),
                   why=args.get("why", ""))
    if verb == "edit":
        return edit(project, args.get("name", ""), text=args.get("text"),
                    paths=args.get("paths"), words=args.get("words"), by="claude",
                    doc=args.get("doc"), check=args.get("check"),
                    refuse=args.get("refuse"), replaces=args.get("replaces"), why=args.get("why"))
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
MAX_TEXT = 8000
# What is kept and what a session is sent are two things (share.py). A
# standing rule is read whole into every session, so those are the ones
# counted: forty. A named one costs its name and is read when it fires, so
# a project may keep many more of them.
MAX_RULES = 40
MAX_NAMED = 2000
MAX_TRIGGERS = 100
# What a rule may refuse outright (R200 step 3): commands as typed, the start
# of each one a session's Bash call may not run while the rule is on.
MAX_REFUSE = 200

# Global rules (R63) live under a key no project can be called: a project is a
# directory on the projects share, and `*` is not a name one can have. So the
# same store, the same shapes, the same history and the same triggers serve
# both, and only the reading differs.
GLOBAL = "*"

# The global rules BuilderBot itself ships. Read-only on purpose: the next
# image would bring an edited one back, and a change nobody can see reverted
# is worse than no change, so the operator turns one off instead.
#
# THE LINE BETWEEN THESE AND THE BRIEFING (the operator, 2 Oct): a rule is a
# global rule when there is value in turning it off, and otherwise it is said
# in the briefing. So each of these is a way of working an operator might
# reasonably not want (let a session install with root asks, keep the tracker
# quiet, chase what it meets, skip the walk in the app for speed), and what no
# operator would ever switch off (no credential in a repository, a true
# report, another person's branch left alone, the project's own files) is in
# config/templates/briefing.md, where it costs nothing to keep and cannot be
# turned off by a press or by a session's request. Nothing is said in both
# places, because a session that reads it twice pays twice and the two copies
# drift.
BUILTIN = [
    {"name": "ask-do-not-install",
     "text": "Never install a tool with a system package manager: it is invisible"
             " to `bb toolchains` and gone when the node is rebuilt. Say what is"
             " missing and which toolchain carries it (`bb toolchains`); installing is"
             " the operator's, from the Library.",
     # Refused, not only said (R200): the one rule here a command shows
     # being broken, so the guard stops it with this text as the reason.
     "refuse": ["apt install", "apt-get install", "apt-get -y install", "aptitude install",
                "dnf install", "yum install", "zypper install", "apk add",
                "pacman -S", "brew install", "snap install",
                # A dry run installs nothing (an audit found one, 12 Oct).
                "!apt-get install* -s*", "!apt-get install* --simulate*", "!apt install* -s*",
                "!apt install* --simulate*", "!dnf install* --assumeno*"]},
    {"name": "file-what-you-find",
     "text": "What you notice goes on the record as you meet it, not only in a"
             " reply: a bug with `bb bug add`, work worth doing with `bb roadmap"
             " add`. Close what you finish as it lands: `bb bug fix`, `bb roadmap"
             " step done`, `bb roadmap done`."},
    {"name": "side-quests",
     "text": "A bug met mid-task is fixed only when your own change caused it"
             " or it blocks the work: the smallest fix, in its own commit, said"
             " in the reply. Anything else is filed and left. One level deep:"
             " a bug found while fixing one of those is filed, not chased."},
    {"name": "prove-in-the-app",
     "text": "Tests passing is not done: where the project has a dev instance"
             " (`bb devapp`) or an app on the emulator, use the change there the way"
             " a person would before calling it done (`bb capture shot` or `reel`"
             " to see it), and say what you saw."},
]

# What the briefing says a session never does, refused by the guard as well
# (R200 step 3). Not rules, and not switchable, for the reason BUILTIN gives:
# each is a mistake that only ever costs something (a shell killing itself,
# an emulator nobody can stop or save, a commit identity written over the
# one the account carries), so the line in config/templates/briefing.md and
# its refusal here are one decision said twice, and nothing a session or a
# project's dial turns off.
ALWAYS = [
    {"name": "pkill-by-pid",
     "text": "A `pkill -f PATTERN` or `pgrep -f PATTERN` run from a tool call matches the shell running"
             " that call, because the pattern is on its command line: pkill kills it, and a wait on"
             " pgrep never ends (B736). `bb proc PATTERN` lists what holds it, `bb proc stop PATTERN`"
             " ends it and `bb proc wait PATTERN` waits for it to go, never touching the call's own"
             " shell; or end a process by its pid, or with `pkill -x NAME`.",
     "refuse": ["pkill -f", "pkill --full", "pkill -* -f", "pkill -*f",
                "pgrep -f", "pgrep --full", "pgrep -* -f", "pgrep -*f"]},
    {"name": "emulator-through-bb",
     "text": "The emulator is started with `bb emu start` and stopped with `bb emu stop`, never the"
             " emulator binary: bb picks the GPU, waits for the boot, keeps the log and saves its"
             " state on stop.",
     "refuse": ["emulator -avd", "emulator @*"]},
    # Only a call that is not in the background (`foreground`): a run started
    # with run_in_background is what the line asks for (the operator, 12 Oct:
    # a run held every reply, so a new ask could never cut into it).
    {"name": "tests-in-the-background",
     "text": "Start a build, a test run, a probe or a dev instance's rebuild in the background,"
             " the way your tool runs one detached (Claude Code's run_in_background), and wait on its"
             " notification, answering meanwhile: one in the foreground holds every reply until it"
             " ends, so a new ask cannot cut into it the way the project's While a test runs setting"
             " says. The unit tier (bb tests unit) is quick enough to run either way.",
     # A probe is a run against the kept fixture, a rebuild is minutes of a
     # job, and a build can be longer than either (the operator, 16 Oct:
     # messages queued behind them, on every project as on this one).
     "refuse": ["bb build", "bb test", "bb tests run", "bb tests preflight", "bb tests lab", "bb tests coverage",
                "bb tests probe", "bb devapp rebuild",
                "bb dashboard test", "*/dashboard/test/run.sh",
                "!bb tests preflight* --dry*",          # the plan only: nothing runs (B698)
                # ...and a verb's usage, which runs nothing either (B278).
                "!bb * --help*", "!bb * -h", "!bb *help"],
     "foreground": True},
    # ...and the wait for one is not a foreground loop either (the operator,
    # 16 Oct: a session went unresponsive while it watched a gate's log).
    # The waiter's own test is the shape read: a grep for "exited", the line
    # a background run's notification file ends on.
    {"name": "notified-not-waited",
     "text": "A run started in the background says when it ends: its notification arrives by"
             " itself. Never wait for it in the foreground with a loop over its log (until grep"
             " ... exited; do sleep): that holds every reply as a foreground run does, so a"
             " message sent meanwhile goes unread until it ends. Go on with other work, or end the"
             " turn, and act on the notification.",
     "refuse": ["grep *exited*"],
     "foreground": True},
    # git's network half goes through bb git (the operator, 27 Oct): the
    # controller holds the credential and the project's git policy and its
    # secret scan stand in front of it, so a session's own git push or fetch,
    # with a token it was handed, would go round all three. A local git
    # (commit, branch, log, a worktree) is the session's own.
    {"name": "git-through-bb",
     "text": "A session reaches a remote only through bb git: `bb git push`, `bb git fetch`, `bb git pull`"
             " and `bb git ls-remote`, which the controller runs with the project's credential, under"
             " its git policy and its scan for secrets. git's own push, fetch, pull, ls-remote and"
             " remote update are refused, with a token or without; everything local to the repository"
             " is git's as ever.",
     "refuse": [f"git{pre} {verb}" for verb in ("push", "fetch", "pull", "ls-remote", "remote update")
                for pre in ("", " -C *", " -c *", " -C * -c *", " -c * -C *", " --git-dir=*",
                            " --git-dir *", " --work-tree=*", " --no-pager", " -P")]},
    {"name": "identity-is-given",
     "text": "Your commit identity arrives as git's environment, so a commit that cannot find an"
             " author is a fault to report with `bb report`, not one to fix with git config"
             " --global user.name or user.email.",
     # The account's own, never a throwaway repository's: a test fixture
     # sets an identity in its scratch repo, which an audit found (12 Oct).
     "refuse": ["git config --global user.name", "git config --global user.email"]},
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


def project_off(project):
    """The names of the global rules turned off for this project alone (the
    operator, 2 Oct): a rule worth having everywhere can still be wrong for
    one project, and turning it off there is the project's own choice."""
    with _lock:
        d = load()
    got = (d.get("projects") or {}).get(project) or {}
    return {str(n) for n in (got.get("globals_off") or [])}


def set_project_off(project, names, by="you"):
    """Which global rules are off for this project: the whole set, as the
    Briefing's Save sends it. A name that is not a global rule is dropped."""
    if project == GLOBAL:
        return
    known = {r["name"] for r in globals_now()}
    want = {str(n).strip().lower() for n in (names or [])} & known
    with _lock:
        d = load()
        p = _project(d, project)
        was = {str(n) for n in (p.get("globals_off") or [])}
        if want == was:
            return
        for n in sorted(want - was):
            _log(d, project, by, {"act": "disable-here", "name": n})
        for n in sorted(was - want):
            _log(d, project, by, {"act": "enable-here", "name": n})
        if want:
            p["globals_off"] = sorted(want)
        else:
            p.pop("globals_off", None)
        save(d)


def builtins():
    """The global rules BuilderBot ships, each marked as read-only and
    carrying whether it is currently off."""
    off = _off()
    out = []
    for i, r in enumerate(BUILTIN):
        r = _clean(dict(r), i)
        r["scope"], r["builtin"], r["by"] = "global", True, "builderbot"
        # Every one has a switch: what nobody would turn off is said in the
        # briefing instead (see BUILTIN).
        r["disabled"] = r["name"] in off
        out.append(r)
    return out


def globals_now():
    """Every rule that applies to every project: the shipped ones, then the
    operator's own. What every project's Briefing lists under its own rules."""
    own = [dict(r, scope="global", builtin=False) for r in rules(GLOBAL)]
    return builtins() + own


def effective(project):
    """What a session in this project actually works under: the global rules
    that are on, then the project's own. One list, because to a session the
    only difference that matters is whether it may change a rule, and the
    marks already say that."""
    if project == GLOBAL:
        return globals_now()
    here = project_off(project)
    own = rules(project)
    # A project rule that names the global rule it replaces (R200 step 4)
    # takes that one's place: a session here reads the project's alone,
    # rather than both and an instruction to prefer one.
    gone = {r.get("replaces") for r in own if r.get("replaces")}
    on = [r for r in globals_now()
          if not r.get("disabled") and r["name"] not in here and r["name"] not in gone]
    return on + own + _design_rules(project)


def _design_rules(project):
    """The design's rules (the notebook's Design view, design.py), in this
    module's shape: the operator's, with triggers like any other, so the
    hooks hand one over on the turn it applies and the briefing names it.
    Read from the store beside this one; nothing when there is none."""
    try:
        import design                                    # beside this module
    except ImportError:
        return []
    try:
        return design.rules_for(project, STATE)
    except Exception:                                    # noqa: BLE001
        return []


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
            # Why the rule is what it is, kept for `bb rules show` and the
            # tab, never sent in the block (R202): a reason read at a rule's
            # volume dilutes the rule.
            "why": str(r.get("why") or "").strip()[:MAX_TEXT],
            # Commands it refuses outright (R200 step 3), each the start of a
            # command as typed; commas between them, since one has spaces.
            "refuse": _refusals(r.get("refuse")),
            # The global rule this one takes the place of in its project.
            "replaces": _slug(r.get("replaces")),
            # Whose it is, and therefore who may change it later. Defaulting
            # to the operator is deliberate: this field arrived after rules
            # did, and a rule written before it existed was written on the
            # tab, which is theirs.
            "by": "claude" if r.get("by") == "claude" else "you",
            "at": int(r.get("at") or time.time())}


def _refusals(v):
    """A rule's refusals, from a list or the line somebody typed."""
    parts = [str(x) for x in v] if isinstance(v, (list, tuple)) else str(v or "").split(",")
    out = []
    for p in parts:
        p = " ".join(p.split())[:120]
        # One that is all wildcards would refuse every command there is.
        if p and re.search(r"[A-Za-z0-9]", p) and p not in out:
            out.append(p)
    return out[:MAX_REFUSE]


def _slug(v):
    n = re.sub(r"[^a-z0-9]+", "-", str(v or "").strip().lower()).strip("-")[:40].strip("-")
    return n if NAME_RE.match(n) else ""


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
    over = _over([r for r in rules if isinstance(r, dict)])
    if over:
        return {"error": over}
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
              "by": "claude" if by == "claude" else "you", **agents.asker(by),
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


def add(project, name, text, paths="", words="", by="claude", doc="", check="", refuse="", replaces="", why=""):
    """One rule, appended. The session's verb; the tab replaces the list.

    A session's rule is marked as its own, which is what lets it change one
    later and what tells the next session, reading the block, that this line
    is a note from a session rather than an instruction from the operator.
    """
    if not str(text or "").strip():
        return {"error": "a rule needs something to say"}
    if project == GLOBAL and by == "claude":
        return {"error": _NOT_YOURS}
    bad = _replaces_bad(project, replaces)
    if bad:
        return {"error": bad}
    # The gate (roadmap #27): a session's rule may be held or refused per
    # project. Keyed by the name it would get, which the replay re-derives.
    if by == "claude" and not pending.replaying():
        g = pending.mode(project, "rules")
        if g == "deny":
            return {"error": pending.refusal("rules")}
        if g == "ask":
            r = _clean({"name": name, "text": text, "paths": paths,
                        "words": words, "by": by, "doc": doc, "check": check,
                        "refuse": refuse, "replaces": replaces, "why": why}, 0)
            return pending.hold(project, "rules", "add",
                                {"name": r["name"], "text": text,
                                 "paths": paths, "words": words, "doc": doc, "check": check,
                                 "refuse": r["refuse"], "replaces": r["replaces"], "why": r["why"]},
                                summary=f"{r['name']}: {r['text']}", number=r["name"])
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        r = _clean({"name": name, "text": text, "paths": paths,
                    "words": words, "by": by, "doc": doc, "check": check,
                    "refuse": refuse, "replaces": replaces, "why": why}, len(rs))
        over = _over(rs + [r])
        if over:
            return {"error": over}
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
              "would add and why, and they add it from a project's Briefing")


def _replaces_bad(project, replaces):
    """Why `replaces` cannot be what a rule says it takes the place of, or
    "": only a project's rule replaces, and only a global rule that exists."""
    n = _slug(replaces)
    if not n:
        return ""
    if project == GLOBAL:
        return "a global rule applies everywhere; only a project's rule replaces one"
    if n not in {r["name"] for r in globals_now()}:
        return (f"there is no global rule called {n}; `bb rules --global` lists them")
    return ""


def _builtin_names():
    return {r["name"] for r in builtins()}


def _switchable_names():
    return {r["name"] for r in builtins()}


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
         doc=None, check=None, refuse=None, replaces=None, why=None):
    if project == GLOBAL and by == "claude":
        return {"error": _NOT_YOURS}
    if project == GLOBAL and str(name or "").strip().lower() in _builtin_names():
        return {"error": "that rule ships with BuilderBot and is read-only: turn "
                         "it off for a project, or for every project, from a project's Briefing"}
    bad = _replaces_bad(project, replaces)
    if bad:
        return {"error": bad}
    with _lock:
        d = load()
        p = _project(d, project)
        rs = p.setdefault("rules", [])
        i, bad = _mine(rs, str(name or "").strip().lower(), by)
        if bad:
            return {"error": bad}
        was = dict(rs[i])
        merged = dict(was)
        for k, v in (("text", text), ("paths", paths), ("words", words),
                     ("doc", doc), ("check", check), ("refuse", refuse), ("replaces", replaces),
                     ("why", why)):
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
                         "it off for a project, or for every project, from a project's Briefing"}
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


def _over(rules):
    """Why a list of rules is more than a project keeps, or ""."""
    standing = sum(1 for r in rules if not conditional(r))
    if standing > MAX_RULES:
        return (f"{MAX_RULES} standing rules is the limit: each is read whole into every "
                "session that starts here. Give one a file or a word that calls for it, "
                "and it is read when that comes up")
    if len(rules) - standing > MAX_NAMED:
        return f"{MAX_NAMED} named rules is the limit here"
    return ""


def fitted(project, budget=None):
    """(what goes in front of every session started here, what it left out
    to keep to `budget`), or ("", "").

    Standing rules in full; conditional ones as one line each saying they
    exist and how to read them. That line is what stops a trigger that misses
    being a rule the session never heard of, which is the worse of the two failures,
    because the session cannot even know to ask.

    A standing rule is never said short: it is what a session is held to.
    Over its share of the prompt (share.py) it is the named ones that say
    less, their names without what calls for each, since the text of one
    arrives on the turn that calls for it either way.
    """
    rs = effective(project)
    if not rs:
        return "", ""
    return share.fitted([lambda: (_block(rs, True), ""),
                         lambda: (_block(rs, False), "what calls for each named rule")], budget)


def block(project):
    """The rules' block with nothing left out: `bb rules --prompt`."""
    return fitted(project)[0]


def _block(rs, triggers):
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
    def frame(r, short=False):
        bits = []
        if r.get("scope") == "global":
            bits.append("global")
        if r.get("design"):
            bits.append("the design's" if short else "the design's: bb design show reads it")
        if r.get("doc"):
            bits.append(f"defined in full in {r['doc']}, read first")
        if r.get("check"):
            bits.append(f"checked by `bb rules check {r['name']}`, run before handing back")
        named = [x for x in r.get("refuse") or [] if not x.startswith("!")]
        if named and not short:
            bits.append("a command it names is refused when you run it: " + ", ".join(named[:4])
                        + (", ..." if len(named) > 4 else ""))
        if r.get("replaces"):
            bits.append(f"in place of the global rule {r['replaces']}")
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
                   "about a word it names."
                   + (" One marked the design's is the notebook's Design view's, "
                      "and `bb design show <name>` reads it too."
                      if any(r.get("design") for r in named) else ""))
        if triggers:
            for r in named:
                on = "; ".join(x for x in [", ".join(r.get("paths") or []),
                                           ", ".join(r.get("words") or [])] if x)
                mine = "*" if r.get("by") == "claude" else ""
                out.append(f"  {mine}{r['name']}: {on}{frame(r, short=True)}")
        else:
            # The names alone, and the two things about one that a session
            # acts on without being called: which it must check before it
            # hands back, and which have a document to read first.
            out.append("The rules are longer than their share of your prompt, so this leaves out "
                       "what calls for each: `bb rules` lists them with it.")
            out.append("  " + ", ".join(("*" if r.get("by") == "claude" else "") + r["name"] for r in named))
            checked = [r["name"] for r in named if r.get("check")]
            if checked:
                out.append("Checked before handing back, each with `bb rules check NAME`: "
                           + ", ".join(checked) + ".")
            docs = [f"{r['name']} in {r['doc']}" for r in named if r.get("doc")]
            if docs:
                out.append("Defined in full, and read first: " + "; ".join(docs) + ".")
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


def guards(project):
    """What the Bash guard refuses in this project (R200 step 3): each rule
    in effect that refuses something, then the briefing's never-do lines,
    as {name, text, refuse, by}. What a node's guard caches."""
    out = [{"name": r["name"], "text": r["text"], "refuse": list(r["refuse"]),
            "by": r.get("by") or "you"}
           for r in effective(project) if r.get("refuse")]
    return out + [dict(g, by="builderbot") for g in ALWAYS]


def refusing(project, command, background=False):
    """(the guard that refuses this shell line, the command as read) or
    None, over what is in effect here."""
    return rulehook.refused(guards(project), command, background)


def by_names(project, names):
    """The rules in effect here with these names, in their order."""
    want = [str(n) for n in names or []]
    have = {r["name"]: r for r in effective(project)}
    return [have[n] for n in want if n in have]


def said(hit, *, path="", again=False):
    """The fired rules as a session is told them: on the turn a file or a
    prompt calls for them, or again after a summary (`again`). One wording
    for both hooks and for the controller's answer to a node's."""
    if not hit:
        return ""
    if again:
        lead = ("Your conversation was just summarized. These house rules were raised earlier in "
                "it and still hold; they are in full here because a summary does not carry them:")
    elif path:
        lead = f"House rules cover {path}, which you are about to edit:"
    else:
        lead = "House rules for this project cover what you are about to do:"
    out = [lead]
    for r in hit:
        who = ("* a note a session left, yours to change" if r.get("by") == "claude"
               else "the operator's, not yours to change")
        doc = f"\nDefined in full in {r['doc']}; read it first." if r.get("doc") else ""
        chk = f"\nRun `bb rules check {r['name']}` before calling the work done." if r.get("check") else ""
        out.append(f"\n[{r['name']}] ({who})\n{r['text']}{doc}{chk}")
    return "\n".join(out)


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
    # Every global rule that is on everywhere, each saying whether it is off
    # here, so the tab can offer the switch; what a session is handed is
    # `eff`, which leaves the ones off here out.
    here = project_off(project) if project != GLOBAL else set()
    every = [dict(r, off_here=r["name"] in here) for r in globals_now()]
    # Each of the project's rules with the global ones it shares ground with,
    # for the row. Decoration on the way out only: _clean keeps a fixed set
    # of fields, so this never comes back in on a save.
    if project != GLOBAL:
        own = [dict(r, overlaps=overlaps(r, glob)) for r in own]
    return {"project": project, "rules": own,
            "global": every if project != GLOBAL else glob,
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
        # The rules and which global ones are off here: a switch flipped in
        # another window is news for this tab too.
        out[p] = _rev_of((v.get("rules") or [])
                         + ([{"globals_off": v["globals_off"]}] if v.get("globals_off") else []))
    return out


# ---- the Rules tab's saves, one call from the dashboard ----------------------

def verb(name, act, req):
    """The operator's house rules for one project: the whole list, saved,
    once server.py has let a PERSON at it (a session is refused there, by
    name). Whole rather than per-rule because the tab is an editor rather
    than a form: somebody rewords two rules and drops a third before
    pressing Save, and replaying that as five operations is five chances to
    land half of it. (payload, status)."""
    if act != "save":
        return {"error": "unknown action"}, 400
    r = replace(name, req.get("rules") or [], rev=req.get("rev"),
                force=bool(req.get("force")))
    if r.get("conflict"):
        # 200, with what is there now: the roadmap's shape for the same
        # moment, so the page can put both versions in front of the
        # person instead of a toast over a form it then has to guess at.
        return {"conflict": True, "error": r["error"],
                "current": payload(name) | {"rev": rev(name)}}, 200
    if r.get("error"):
        return r, 400
    # Which global rules are off here, saved with the list: one Save.
    if isinstance(req.get("globals_off"), list):
        set_project_off(name, req["globals_off"])
    return payload(name) | {"rev": rev(name)}, 200


def global_verb(act, req):
    """The rules that apply to EVERY project (R63), saved by an
    administrator. A shipped rule is read-only and is turned off rather
    than edited, so the only thing this writes for one is whether it is
    on. (payload, status)."""
    if act != "save":
        return {"error": "unknown action"}, 400
    # `disabled` only when the caller sent one: absent means leave the
    # shipped rules as they are rather than switching them all back on.
    off = req.get("disabled")
    r = save_global(req.get("rules") or [], off if isinstance(off, list) else None)
    if r.get("error"):
        return r, 400
    return {"rules": globals_now()}, 200
