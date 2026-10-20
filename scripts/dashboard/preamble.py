#!/usr/bin/env python3
"""What every session on a project starts with, assembled once.

Three stores contribute to the block bb-tty hands `claude` as
`--append-system-prompt`: the house rules first (how the operator wants this
worked on comes before what there is to work on), then the open roadmap, then
the open bugs. That order and those joins used to live in bb-tty as shell,
which was fine while the launcher was the only reader, and stopped being fine
the moment the Briefing tab wanted to SHOW a person what their sessions are
sent. Two assemblies of the same text drift, and the one that drifts is the
one nobody runs.

So it is here, the launcher asks for it through `bb preamble`, and the tab
renders exactly the string that goes in front of a session rather than an
approximation of it.

The cap is part of the answer, not a caller's business. It used to be the
kernel's: a single argv entry cannot exceed MAX_ARG_STRLEN, 131072 bytes on
Linux, and past it `exec` answers "Argument list too long" and the pane dies
without saying why. bb-tty writes this to a file now and passes
--append-system-prompt-file, so that ceiling is gone and the number here is
about what a session should be asked to read: every conversation pays for all
of it, so a list that runs past this is one nobody has pruned. When the block
is cut, the cut is made at a line boundary and says so in the text, so a
session is told that it is reading part of a list rather than all of one.
"""

import os
import re
import sys
from pathlib import Path

# The three stores, set by configure(). Named here so the module reads as
# what it is on its own, and so a typo is a lint finding rather than a
# NameError on somebody's first session of the day.
rules_mod = roadmap_mod = bugs_mod = None

# The projects share, for deciding which parts of the briefing apply to this
# project. From the environment rather than configure(), because both readers
# (the server and bb) already run with it set and neither has to be taught.
WORKSPACE = os.environ.get("WORKSPACE", "/workspace")

# What the rules may take of a session's prompt, in bytes (share.py): over
# it the named rules say less before one is left out. Sixteen kilobytes is
# about four thousand tokens. The roadmap and the bugs had shares once and
# are counts now (R202): a session read two hundred titles cut short on
# every conversation and used few, and the items a prompt names arrive on
# that prompt instead (mentioned).
SHARES = {"rules": 16 * 1024}

# Where the briefing's core ends (config/templates/briefing.md): the lines
# that hold every time come first, then the house rules, then the rest of
# the briefing as reference (R200 step 5). What is read first and short is
# what is followed; a rule after five thousand words of how-to was read at
# the same weight as the how-to.
_CORE_END = "<!-- BUILDERBOT:CORE-END -->"
# The rest of the template is topics (R202): each `## Heading` after the
# core carries a TOPIC marker with its slug and a gist, the block carries
# the index of them where the TOPICS marker stands, and `bb help TOPIC`
# prints one when the work reaches it. A session read the whole manual
# on every conversation (38 KB of 62) and the rules at its volume.
_TOPICS = "<!-- BUILDERBOT:TOPICS -->"
_TOPIC = re.compile(r"^<!-- BUILDERBOT:TOPIC ([a-z][a-z0-9-]*): (.*?) -->$")


live_fn = None


def configure(*, rules_mod, roadmap_mod, bugs_mod, live=None, prefs_mod=None):
    """The three stores, injected rather than imported.

    Same shape as every other module here: server.py owns configuring them,
    and `bb` hands in the same three after configuring them itself. `live`
    is the server's: what build is running, for the briefing (R75 step 5);
    bb, which has no server, hands in nothing and the part is left out.
    """
    global live_fn
    live_fn = live
    globals().update(rules_mod=rules_mod, roadmap_mod=roadmap_mod, bugs_mod=bugs_mod,
                     prefs_mod=prefs_mod)


prefs_mod = None
# Whether a project's node reports an NVIDIA card, from the server (R102):
# a fact about the machine, not the tree, so the briefing's GPU section is
# decided by it and costs a session on a node without one nothing.
node_gpu = None
_TESTCHANGE = "<!-- BUILDERBOT:TESTCHANGE -->"
# What a change asked for during a test run does, in the words a session
# reads: the project's setting (prefs.TEST_CHANGE), one answer per project
# where two house rules could say opposite things.
TEST_CHANGE_SAID = {
    "wait": ("a new ask never cuts in. Finish the ask in hand, run the tests, fix what "
             "failed and run them again until they pass, then take the next ask; say it "
             "is queued when it arrives."),
    "restart": ("a new ask cuts into whatever test run is going, a suite run in the middle of "
                "the work or the gate at its end: end that run by the pid you started it with "
                "(kill its process group, never by name), take the new ask, and run again "
                "afterwards. What the cut run had found is still yours to fix before the run "
                "that lands; say what you cut and why."),
}


REPLY_SAID = {
    "minimal": ("Replies to the person: minimal, their setting. Answer in as few "
                "words as carry it: the outcome, what to look at, what is left; no preamble, "
                "no recap of the work. The notebook, commits, code and files are written as ever."),
}
ASKS_SAID = {
    "more": ("Questions to the person: more, their setting. Check with them before a "
             "judgment call that shapes the work (which of two readings, which approach, "
             "whether to widen or narrow what was asked), in one message naming the "
             "options and which you would take; make only the routine calls yourself."),
    "fewer": ("Questions to the person: fewer, their setting. Make the routine calls "
              "yourself and say which you made; ask only where two readings of the ask "
              "would lead to materially different work."),
    "rarely": ("Questions to the person: rarely, their setting. Ask only when going on "
               "under any assumption would be unsafe or would make the work useless; "
               "otherwise state the assumption in the reply and go on."),
}


def person_part(reply, asks):
    """The part of the block that is this person's own settings: how Claude
    writes to them and how often it asks them. "" when neither is set."""
    said = [t for t in (REPLY_SAID.get(reply or "", ""), ASKS_SAID.get(asks or "", "")) if t]
    return "## Replies\n\n" + "\n\n".join(said) if said else ""


# The projects this one reads (prefs.reads), said where the session will
# act on it: their trees are at /workspace/NAME read-only, and their
# notebooks answer to bb from inside them. Nothing when there are none:
# the shipped rule already says to stay in the project.
_READS = "<!-- BUILDERBOT:READS -->"


def sees_line(project):
    """The places on its node this project is shown (prefs.sees), said so a
    session knows they are there and that nothing else of the node is."""
    sees = []
    if prefs_mod is not None:
        try:
            sees = list((prefs_mod.get(project) or {}).get("sees") or [])
        except Exception:                                            # noqa: BLE001
            sees = []
    if not sees:
        return ""
    return (f"Of the shares and disks mounted on its node, this project is shown "
            f"{', '.join(sees)}, as the node has each; one that is missing here is not on "
            f"this node.")


# registry.label, set by the server (R154): the name a project is shown
# under, which is not its directory once a name has been used before.
label_of = None
# The project's id as it is written (registry.pid): P3.
id_of = None


def _shown(project):
    """A project as a session should name it to a person: its shown name,
    with its directory beside it when the two differ."""
    lab = label_of(project) if label_of else project
    return project if not lab or lab == project else f"{lab} (directory {project})"


def identity_line(project):
    """The project's id, and its shown name where that is not the directory:
    the person says the name, every path takes the directory, and the id
    names it for good, renamed or not."""
    lab = label_of(project) if label_of else project
    pid = id_of(project) if id_of else ""
    said = f"This project's id is {pid}, which never changes; `bb -p {pid}` names it." if pid else ""
    if not lab or lab == project:
        return said
    return (f"This project is shown as {lab}; its directory is /workspace/{project}, which every "
            f"path and `bb -p` use. Call it {lab} when you speak of it."
            + (f" Its id is {pid}, which never changes." if pid else ""))


def reads_line(project):
    reads = []
    if prefs_mod is not None:
        try:
            reads = list((prefs_mod.get(project) or {}).get("reads") or [])
        except Exception:                                            # noqa: BLE001
            reads = []
    if not reads:
        return ""
    names = ", ".join(_shown(r) for r in reads)
    return (f"This project reads {names}: each is at /workspace/NAME, read-only, and "
            f"`bb -p NAME` in front of `bb roadmap`, `bb bug`, `bb rules`, `bb design`, "
            f"`bb tests` or `bb map` makes the verb answer for it, so its notebook and its code "
            f"are yours to read, and its containers answer from here on this project's nodes, so "
            f"`bb -p NAME devapp` says where its page is and `bb capture shot` photographs it; "
            f"`bb -p NAME transcripts` lists this account's own conversations with Claude there "
            f"and `show ID` prints one, and their files are under ~/.claude/projects read-only. "
            f"Nothing there is yours to change: a write to its tree fails, a write to its notebook is "
            f"refused, and its containers are not yours to start or stop; a session on that project is "
            f"what changes them.")


# What the notebook's Design view holds, said in the briefing when there is
# one, so a project designed before its first line of code is built to the
# design from the start (the operator, 28 Sep): the themes, the pages by
# name, the rules, and where bb design show reads each.
_DESIGN = "<!-- BUILDERBOT:DESIGN -->"


def design_line(project):
    try:
        import design                                    # beside this module
        rec = design.saved(project)
    except Exception:                                    # noqa: BLE001
        return ""
    dial = _design_dial(project)
    fill = {"auto": "a save of yours lands",
            "ask": "a save of yours waits for the operator's approval on the notebook",
            "deny": "the project refuses a session's save, so say in your reply what you would put there"}[dial]
    if not rec:
        # Nothing designed beforehand (the operator, 29 Sep): build as you
        # would, then put what you arrived at into the notebook so the next
        # session finds it there.
        return ("The notebook's Design view is empty: no theme, no page, no design rule. Build as you "
                "would and choose the look yourself; then put what you arrived at into the design with "
                "`bb design save` (the themes with their colors as tokens, the type, corners, space and "
                "motion you settled on, the pages you built, the rules you followed; `bb design schema` "
                "prints the shape) so the next session finds it there. "
                f"Under the project's dial Claude may: Add to the design, {fill}.")
    lang, pages = rec["language"], rec["pages"]
    themes = ", ".join(t["name"] for t in lang["themes"])
    own = sum(len(t.get("rules") or []) for t in lang["themes"]) + sum(len(p.get("rules") or []) for p in pages)
    bits = [f"{len(lang['themes'])} theme{'' if len(lang['themes']) == 1 else 's'} ({themes})"]
    if pages:
        bits.append(f"{len(pages)} page{'' if len(pages) == 1 else 's'}: "
                    + ", ".join(p["name"] or f"page {p['id']}" for p in pages[:8]) + (", ..." if len(pages) > 8 else ""))
    # The default theme's rules are the design's; the other themes' and
    # the pages' are their own.
    mine = design.lead(lang)["rules"]
    own -= len(mine)
    if mine or own:
        bits.append(f"{len(mine)} design rule{'' if len(mine) == 1 else 's'}"
                    + (f" and {own} of a theme's or a page's own" if own else ""))
    left = design.open_choices(lang)
    if left:
        bits.append(", ".join(left) + " not chosen yet")
    empty = _no_code_yet(project)
    return (f"This project's notebook holds a design already: {'; '.join(bits)}. "
            + ("The tree has no code yet, so the design, the rules and the roadmap are the "
               "specification: build to them from the first file. " if empty else "")
            + "Read `bb design show` before laying out or styling anything, `bb design show NAME` for "
              "one page or one theme. docs/design-language.md is yours to write and commit with the work "
              "(`bb design file > docs/design-language.md`); the notebook never writes it into the tree by itself. What the "
              "design leaves open and you had to decide (a color it does not name, a page it does not have, "
              "a choice of its language nobody has made) "
              f"goes back into it with `bb design save` so it is complete; under the project's dial, {fill}.")


def _design_dial(project):
    """The project's dial Claude may: Add to the design, as pending reads it."""
    try:
        import pending                                   # beside this module
        return pending.mode(project, "design") or "auto"
    except Exception:                                    # noqa: BLE001
        return "auto"


def _no_code_yet(project):
    """True when the tree holds nothing but its git, its docs and its
    notes: a project made on the dashboard and designed before it is built."""
    try:
        names = [n for n in os.listdir(os.path.join(str(WORKSPACE), project)) if not n.startswith(".")]
    except OSError:
        return False
    return all(n in ("docs", "README.md", "CLAUDE.md", "LICENSE", "dist") for n in names)


def test_change_line(project):
    mode = "wait"
    if prefs_mod is not None:
        try:
            mode = (prefs_mod.get(project) or {}).get("test_change") or "wait"
        except Exception:                                            # noqa: BLE001
            mode = "wait"
    return TEST_CHANGE_SAID.get(mode, TEST_CHANGE_SAID["wait"])


# Where the environment briefing is written. The image puts config/templates/
# at /opt/builderbot/templates/ (see the Dockerfile), which is NOT where it
# sits in a checkout, and the first version of this looked only at the checkout
# layout: every session on a real controller got no briefing at all and nothing
# said so. So: the override first, then the installed path, then the checkout
# beside this module, and a miss is said out loud rather than swallowed.
BRIEFING_PATHS = [Path(os.environ["BRIEFING_MD"])] if os.environ.get("BRIEFING_MD") else [
    Path("/opt/builderbot/templates/briefing.md"),
    Path(__file__).resolve().parents[2] / "config" / "templates" / "briefing.md",
]
_IF = re.compile(r"<!-- BUILDERBOT:IF ([^>]*?) *-->")
_END = "<!-- BUILDERBOT:END -->"


def briefing(project, gates=True):
    """How this machine works, as every session on it is told (R63), whole:
    the core, the project's own lines and every topic. `gates` off keeps
    the sections the tree would leave out, for `bb help TOPIC` on a
    project that is not an Android one.

    It used to be a 53KB block rendered into every project as CLAUDE.md and
    pushed again whenever the template moved, which is drift by construction:
    the copy is what a session reads and nothing keeps it current. Assembled
    here instead, from one file, at the moment a session starts, so there is
    no copy to be out of date and nothing to push.

    What is in it is what would surprise somebody. The `bb` reference that
    made up most of the old block is a `bb <verb> -h` away and does not need
    paying for on every conversation.

    The parts that only apply to some projects are marked in the file with
    the evidence that decides them, the same way the template marks its own,
    and the evidence is a glob against the project's tree because the tree is
    what the controller and every node agree about.
    """
    text = None
    for cand in BRIEFING_PATHS:
        try:
            text = cand.read_text()
            break
        except OSError:
            continue
    if text is None:
        # Loud, and in the prompt: a session that is not told how this machine
        # works should know that, and so should whoever reads the Briefing tab.
        return ("[the environment briefing is missing from this image, so what "
                "follows is the rules and the lists only. Say so in your reply.]")
    tree = Path(WORKSPACE or "/workspace") / project
    out, skip = [], False
    for line in text.split("\n"):
        m = _IF.search(line)
        if m:
            bits = m.group(1).split()
            # `node:gpu` is evidence the node gives rather than the tree.
            skip = gates and not any((bool(node_gpu and node_gpu(project)) if g == "node:gpu" else _has(tree, g))
                                     for g in bits[1:])
            continue
        if _END in line:
            skip = False
            continue
        if not skip:
            # A block skipped between two blank lines leaves one of them,
            # not both: the template has no double blank of its own.
            if not line.strip() and out and not out[-1].strip():
                continue
            if line.strip() in (_READS, _DESIGN):
                said = "\n\n".join(x for x in (identity_line(project), reads_line(project),
                                                sees_line(project), packs_line(project)) if x) \
                    if line.strip() == _READS else design_line(project)
                if said:
                    out.append(said)
                elif out and not out[-1].strip():
                    continue
                continue
            out.append(test_change_line(project) if line.strip() == _TESTCHANGE else line)
    return "\n".join(out).strip("\n")


def split(text):
    """(the text with its topics taken out and the index put where the
    TOPICS marker stands, [(slug, title, gist, body)] in order)."""
    kept, topics, cur = [], [], None
    for line in text.split("\n"):
        m = _TOPIC.match(line.strip())
        if m and kept and kept[-1].startswith("## "):
            cur = [m.group(1), kept.pop()[3:].strip(), m.group(2).strip(), []]
            topics.append(cur)
            continue
        if cur is not None and line.startswith("## "):
            cur = None
        if cur is not None:
            cur[3].append(line)
            continue
        kept.append(line)
    index = ""
    if topics:
        index = ("Topics of this briefing, each read with `bb help TOPIC` when the work reaches it:\n"
                 + "\n".join(f"- {slug}: {gist}" for slug, _, gist, _ in topics))
    out = "\n".join(kept).replace(_TOPICS, index)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, [(slug, title, gist, "\n".join(body).strip("\n")) for slug, title, gist, body in topics]


def topics(project):
    """[(slug, gist, bytes)] of the topics a session here is pointed at."""
    return [(slug, gist, len(body.encode("utf-8"))) for slug, _, gist, body in split(briefing(project))[1]]


# The tool packs added here (R77), name to {label, guidance}: set by the
# server (toolpacks.packs) and by bb preamble, which reads the same file.
packs_of = None


def _packs_on(project):
    """The packs this project's settings switch on that are still added."""
    if packs_of is None or prefs_mod is None:
        return {}
    try:
        on = (prefs_mod.get(project) or {}).get("packs_on") or []
        have = packs_of() or {}
    except Exception:                                                # noqa: BLE001
        return {}
    return {n: have[n] for n in on if n in have}


def packs_line(project):
    """The tool packs a session here may use, said where it learns its
    project; "" when the project uses none."""
    on = _packs_on(project)
    if not on:
        return ""
    names = ", ".join(f"{(r.get('label') or n)} (`bb tool {n}`)" for n, r in sorted(on.items()))
    return (f"This project's sessions may use the tool packs {names}: `bb tool NAME` lists a pack's verbs, "
            f"and `bb help tool-NAME` prints what the pack says about using them. A person here added each; "
            f"none is shipped with BuilderBot.")


def topic(project, slug):
    """One topic's text, headed, for `bb help TOPIC`; None when there is
    none by that name. Every topic answers, the tree's gates aside: a
    question about the emulator on a project with no Android is still a
    question. tool-NAME is a tool pack's own guidance, for a project that
    uses the pack (R77)."""
    if slug.startswith("tool-"):
        rec = _packs_on(project).get(slug[5:])
        if rec is not None:
            return (f"## {rec.get('label') or slug[5:]} (a tool pack)\n\n"
                    + (rec.get("guidance") or f"The pack says nothing more: `bb tool {slug[5:]}` lists its verbs."))
    for s, title, _, body in split(briefing(project, gates=False))[1]:
        if s == slug:
            return f"## {title}\n\n{body}"
    return None


def _has(tree, pattern):
    try:
        return any(True for _ in tree.glob(pattern))
    except (OSError, ValueError):
        return False


def parts(project, reply="", asks=""):
    """The pieces, in the order a session reads them, each as (name, text,
    what it left out to keep to its share).

    The briefing's core first, then the house rules, then the person's own
    settings: what a session is held to, short, before anything it reads
    for reference (R200). Then the rest of the briefing, what is running,
    and what there is to work on.

    Each store answers "" when it has nothing, and an empty piece contributes
    no blank line: a project with no bugs must not start its sessions with a
    gap where the tracker would have been.
    """
    out = []
    whole = {}

    def brief(half):
        if "text" not in whole:
            whole["text"] = split(briefing(project))[0]
        core, mark, rest = whole["text"].partition(_CORE_END)
        if not mark:                       # a template without the mark: all of it is the briefing
            core, rest = "", core
        return (core if half == "core" else rest), ""

    for name, fn in (("core", lambda: brief("core")),
                     ("rules", lambda: rules_mod.fitted(project, SHARES["rules"])),
                     ("replies", lambda: (person_part(reply, asks), "")),
                     ("briefing", lambda: brief("rest")),
                     # What is running, as a fact rather than a guess (R75
                     # step 5): a session argued from a build it assumed once.
                     ("live", lambda: (live_fn() if live_fn else "", "")),
                     ("roadmap", lambda: (roadmap_mod.brief(project), "")),
                     ("bugs", lambda: (bugs_mod.brief(project), ""))):
        try:
            text, left = fn()
            text = (text or "").strip("\n")
        except Exception as e:                              # noqa: BLE001
            # One store failing is a smaller thing than no session: bb-tty
            # swallowed each of these separately for exactly this reason.
            # Broad because each store is its own module; the log names it.
            text, left = "", ""
            print(f"dashboard: preamble: {name} for {project} left out: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        if text:
            out.append((name, text, left))
    return out


# ---- what a prompt names on the record (R202) ---------------------------------
# The block carries counts; the items and bugs a prompt is about arrive on
# that prompt, through the hook every prompt already runs, the way a named
# rule does: the titles whose words the person typed, or whose number they
# said, the best three of each, once a conversation.
_STOP = set("""a an the and or of to in on for with from by at as is are was were be been being it its
this that these those not no yes you your we our they them their there here what which who when where
how why do does did done have has had will would can could should may might into over under about after
before than then also only any all some each one two new old more most very just like than when while
make makes made take takes took get gets got put puts set sets use uses used using work works working
look looks looking see sees seen want wants need needs still again same other another thing things way
fix fixes fixed add adds added change changes changed""".split())
_NUMBERED = re.compile(r"\b([RB])(\d+)\b")
MENTIONED_EACH = 3


def _words(text):
    """The words of a title or a prompt worth matching on: four letters or
    more, a trailing s dropped, the common ones out."""
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9_-]{3,}", str(text or "").lower()):
        w = w[:-1] if w.endswith("s") and len(w) > 4 else w
        if w not in _STOP:
            out.add(w)
    return out


def mentioned(project, text, told=()):
    """(what to say, the names to remember) for the open roadmap items and
    bugs that `text`, what a person typed, names: by number (R4, B7) or by
    two or more words shared with the title. `told` is what this
    conversation was handed already, left out."""
    words = _words(text)
    numbered = {(k, int(n)) for k, n in _NUMBERED.findall(str(text or ""))}
    if not words and not numbered:
        return "", []
    told = set(told or ())

    def label(kind, n):
        try:
            import ids                                   # beside this module
            return ids.label(kind, n)
        except Exception:                                # noqa: BLE001
            return f"{'R' if kind == 'roadmap' else 'B'}{n}"

    found = []
    try:
        rows = [r for r in roadmap_mod.items(project) if not r.get("shelved")]
    except Exception:                                    # noqa: BLE001
        rows = []
    for r in rows:
        name = f"roadmap-{r.get('id')}"
        score = len(words & _words(r.get("text", ""))) + (10 if ("R", r.get("id")) in numbered else 0)
        if name in told or score < 2:
            continue
        steps = [s for s in r.get("steps") or [] if not s.get("done")]
        found.append((score, 0, name, f"{label('roadmap', r['id'])} {str(r.get('text', ''))[:140]}"
                      + (f" ({len(steps)} step{'s' if len(steps) != 1 else ''} open)" if steps else "")
                      + f": `bb roadmap show {label('roadmap', r['id'])}`"))
    try:
        bugs = bugs_mod.open_bugs(project)
    except Exception:                                    # noqa: BLE001
        bugs = []
    for b in bugs:
        name = f"bug-{b.get('id')}"
        score = len(words & _words(b.get("title", ""))) + (10 if ("B", b.get("id")) in numbered else 0)
        if name in told or score < 2:
            continue
        found.append((score, 1, name, f"{label('bugs', b['id'])} [{b.get('severity', 'medium')}] "
                      f"{str(b.get('title', ''))[:140]}: `bb bug show {label('bugs', b['id'])}`"))
    if not found:
        return "", []
    keep = []
    for kind in (0, 1):
        keep += sorted([f for f in found if f[1] == kind], key=lambda f: -f[0])[:MENTIONED_EACH]
    return ("On the record, named by what you were asked:\n"
            + "\n".join(f"- {line}" for _, _, _, line in keep)), [name for _, _, name, _ in keep]


def block(project, reply="", asks=""):
    """The whole thing, as a session is sent it."""
    return "\n\n".join(t for _, t, _ in parts(project, reply, asks))


def payload(project, reply="", asks=""):
    """What the Briefing tab draws, and what `bb preamble --json` prints.
    `reply` and `asks` are the asker's own settings on the project (prefs
    USER_CHOICES): how Claude writes to them and how often it asks them.
    Each part carries its size, its share where it has one, and what it
    left out to keep to it; `notes` says the last in a sentence each, for
    whoever opens the terminal."""
    ps = parts(project, reply, asks)
    text = "\n\n".join(t for _, t, _ in ps)
    return {"text": text, "bytes": len(text.encode("utf-8")),
            # The name the project is shown under, which the launcher names
            # the session by (the Claude app listed folders otherwise).
            "name": (label_of(project) if label_of else "") or project,
            "id": id_of(project) if id_of else "",
            # What is pointed at rather than sent: the topics, with what
            # each would cost, so the tab says what the block leaves out.
            "topics": [{"slug": s, "gist": g, "bytes": b} for s, g, b in topics(project)],
            "parts": [{"name": n, "bytes": len(t.encode("utf-8")),
                       **({"share": SHARES[n]} if n in SHARES else {}),
                       **({"left": left} if left else {})} for n, t, left in ps],
            "notes": [f"the {n} part is over its share of a session's prompt and leaves out {left}"
                      for n, _, left in ps if left]}
