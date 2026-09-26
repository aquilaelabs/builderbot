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

MAX = 200000

CUT = ("[the rest of this list did not fit in the prompt; `bb roadmap`"
       " and `bb bug` show all of it]")


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
_TESTCHANGE = "<!-- BUILDERBOT:TESTCHANGE -->"
# What a change asked for during a test run does, in the words a session
# reads: the project's setting (prefs.TEST_CHANGE), one answer per project
# where two house rules could say opposite things.
TEST_CHANGE_SAID = {
    "wait": ("a new ask never cuts in. Finish the ask in hand, run the tests, fix what "
             "failed and run them again until they pass, then take the next ask; say it "
             "is queued when it arrives."),
    "restart": ("a new ask may cut into the final test run only, the gate after the work "
                "is done and committed: end that run by the pid you started it with (kill "
                "its process group, never by name), make the change, and start the run again. "
                "Work still in progress on the ask in hand, including fixing failures from "
                "a run made in the middle of it, finishes first; the new ask waits until then."),
}


# ---- terse: the block with its filler words dropped ------------------------
# What a person reads in the notebook and what a session reads need not be
# the same text (the operator, 25 Sep): a third of the words in a block are
# function words, and a model reads telegraphic prose fine. Deterministic on
# purpose, never a model: a summariser could rewrite meaning, and this only
# removes words that carry none. What it never touches: code spans and
# indented command lines, names and labels (nothing capitalised is dropped),
# numbers, and the words that turn a sentence around, which are the KEEP
# list and win over the filler list.
# "or", "rather than", "by", "be", "then" and "so" turn a sentence too (the
# review of 26 Sep read "rather than working from the title" tersed to the
# opposite, and "Fixed or Security" to a list of one), so they are kept.
_FILL = frozenset("the a an of to and is are was were been being it its this that "
                  "these those there here which who whom in on at for with as from into "
                  "very just also some such any each".split())
_KEEP = frozenset("not never no nor unless only before after until if when while without "
                  "except but must may cannot always first last same other another every "
                  "all none or rather than by be then so".split())
_PHRASES = [("in order to", "to"), ("as well as", "and"), ("so that", "so"),
            ("make sure", "ensure"), ("at the moment", "now"), ("a number of", "several"),
            ("the fact that", "that")]
_PUNCT = ".,;:"


def _terse_words(seg):
    # The segment's own edges kept: a code span sits between two of these,
    # and the space either side of it is what keeps it a word.
    lead = seg[:len(seg) - len(seg.lstrip(" "))]
    trail = seg[len(seg.rstrip(" ")):]
    seg = seg.strip(" ")
    for a, b in _PHRASES:
        seg = re.sub(re.escape(a), b, seg, flags=re.IGNORECASE)
    out = []
    quoted = False
    for tok in seg.split(" "):
        core = tok.strip(_PUNCT + "()\"'")
        # Inside double quotes nothing is dropped: a quoted label is a name.
        # A token carrying a bracket or a quote stays whole: dropping it took
        # the bracket with it, and the sentence lost its shape.
        opens = tok.count('"')
        keep_whole = any(c in tok for c in "()\"") or quoted
        if (core and core.islower() and core in _FILL and core not in _KEEP
                and "-" not in tok and not keep_whole):
            punct = tok[len(tok.rstrip(_PUNCT)):]
            if punct and out:
                out[-1] = out[-1].rstrip(_PUNCT) + punct
        else:
            out.append(tok)
        if opens % 2:
            quoted = not quoted
    return lead + " ".join(t for t in out if t != "") + trail


def terse(text):
    """`text` with its filler words dropped, outside code. A code span can
    wrap onto the next line, so the backticks are counted across a
    paragraph rather than a line: counted per line, the words after a
    wrapped span were read as code, or code as words."""
    out, para = [], []

    def flush():
        if not para:
            return
        segs = "\n".join(para).split("`")
        for i in range(0, len(segs), 2):
            segs[i] = "\n".join(_terse_words(ln) for ln in segs[i].split("\n"))
        out.extend("`".join(segs).split("\n"))
        para.clear()

    for line in (text or "").split("\n"):
        if not line.strip() or line.startswith(("    ", "\t")):
            flush()
            out.append(line)
            continue
        para.append(line)
    flush()
    return "\n".join(out)


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


def _brief_mode(project):
    if prefs_mod is None:
        return "full"
    try:
        return (prefs_mod.get(project) or {}).get("brief") or "full"
    except Exception:                                                # noqa: BLE001
        return "full"


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


def briefing(project):
    """How this machine works, as every session on it is told (R63).

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
            skip = not any(_has(tree, g) for g in bits[1:])
            continue
        if _END in line:
            skip = False
            continue
        if not skip:
            # A block skipped between two blank lines leaves one of them,
            # not both: the template has no double blank of its own.
            if not line.strip() and out and not out[-1].strip():
                continue
            out.append(test_change_line(project) if line.strip() == _TESTCHANGE else line)
    return "\n".join(out).strip("\n")


def _has(tree, pattern):
    try:
        return any(True for _ in tree.glob(pattern))
    except (OSError, ValueError):
        return False


def parts(project, reply="", asks=""):
    """The pieces, in the order a session reads them.

    The briefing first, because it is what the rest is said in terms of; then
    how the operator wants this worked on; then what there is to work on.

    Each store answers "" when it has nothing, and an empty piece contributes
    no blank line: a project with no bugs must not start its sessions with a
    gap where the tracker would have been.
    """
    out = []
    mode = _brief_mode(project)
    for name, fn in (("briefing", lambda: briefing(project)),
                     # What is running, as a fact rather than a guess (R75
                     # step 5): a session argued from a build it assumed once.
                     ("live", lambda: live_fn() if live_fn else ""),
                     ("replies", lambda: person_part(reply, asks)),
                     ("rules", lambda: rules_mod.block(project)),
                     ("roadmap", lambda: roadmap_mod.prompt(project)),
                     ("bugs", lambda: bugs_mod.prompt(project))):
        try:
            text = (fn() or "").strip("\n")
        except Exception as e:                              # noqa: BLE001
            # One store failing is a smaller thing than no session: bb-tty
            # swallowed each of these separately for exactly this reason.
            # Broad because each store is its own module; the log names it.
            text = ""
            print(f"dashboard: preamble: {name} for {project} left out: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        if text and mode == "terse" and name != "live":
            text = terse(text)
        if text:
            out.append((name, text))
    return out


def block(project, reply="", asks=""):
    """The whole thing, uncapped."""
    return "\n\n".join(t for _, t in parts(project, reply, asks))


def fit(text):
    """(what a session gets, whether it was cut, how big it was).

    The cut lands on a line boundary rather than mid-line, and never inside a
    UTF-8 character; `head -c` was happy to do both.
    """
    raw = text.encode("utf-8")
    if len(raw) <= MAX:
        return text, False, len(raw)
    cut = raw[:MAX].decode("utf-8", "ignore")
    cut = cut[:cut.rfind("\n") + 1] if "\n" in cut else cut
    return cut + CUT, True, len(raw)


def payload(project, reply="", asks=""):
    """What the Briefing tab draws, and what `bb preamble --json` prints.
    `reply` and `asks` are the asker's own settings on the project (prefs
    USER_CHOICES): how Claude writes to them and how often it asks them."""
    ps = parts(project, reply, asks)
    whole = "\n\n".join(t for _, t in ps)
    text, capped, size = fit(whole)
    return {"text": text, "bytes": size, "max": MAX, "capped": capped,
            "parts": [{"name": n, "bytes": len(t.encode("utf-8"))} for n, t in ps]}
