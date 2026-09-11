#!/usr/bin/env python3
"""What every session on a project starts with, assembled once.

Three stores contribute to the block bb-tty hands `claude` as
`--append-system-prompt`: the house rules first (how the operator wants this
worked on comes before what there is to work on), then the open roadmap, then
the open bugs. That order and those joins used to live in bb-tty as shell,
which was fine while the launcher was the only reader — and stopped being fine
the moment the Briefing tab wanted to SHOW a person what their sessions are
sent. Two assemblies of the same text drift, and the one that drifts is the
one nobody runs.

So it is here, the launcher asks for it through `bb preamble`, and the tab
renders exactly the string that goes in front of a session rather than an
approximation of it.

The cap is part of the answer, not a caller's business. A single argv entry
cannot exceed MAX_ARG_STRLEN — 131072 bytes on Linux — and past it `exec`
answers "Argument list too long" and the pane dies without saying why. 100000
leaves room for the rest of the command line. When the block is cut, the cut
is made at a line boundary and says so in the text, so a session is told that
it is reading part of a list rather than all of one.
"""

# The three stores, set by configure(). Named here so the module reads as
# what it is on its own, and so a typo is a lint finding rather than a
# NameError on somebody's first session of the day.
rules_mod = todo_mod = bugs_mod = None

MAX = 100000

CUT = ("[the rest of this list did not fit in the prompt — `bb roadmap`"
       " and `bb bug` show all of it]")


def configure(*, rules_mod, todo_mod, bugs_mod):
    """The three stores, injected rather than imported.

    Same shape as every other module here: server.py owns configuring them,
    and `bb` hands in the same three after configuring them itself.
    """
    globals().update(rules_mod=rules_mod, todo_mod=todo_mod, bugs_mod=bugs_mod)


def parts(project):
    """The three pieces, in the order a session reads them.

    Each store answers "" when it has nothing, and an empty piece contributes
    no blank line: a project with no bugs must not start its sessions with a
    gap where the tracker would have been.
    """
    out = []
    for name, fn in (("rules", lambda: rules_mod.block(project)),
                     ("roadmap", lambda: todo_mod.prompt(project)),
                     ("bugs", lambda: bugs_mod.prompt(project))):
        try:
            text = (fn() or "").strip("\n")
        except Exception:
            # One store failing is a smaller thing than no session: bb-tty
            # swallowed each of these separately for exactly this reason.
            text = ""
        if text:
            out.append((name, text))
    return out


def block(project):
    """The whole thing, uncapped."""
    return "\n\n".join(t for _, t in parts(project))


def fit(text):
    """(what a session gets, whether it was cut, how big it was).

    The cut lands on a line boundary rather than mid-line, and never inside a
    UTF-8 character — `head -c` was happy to do both.
    """
    raw = text.encode("utf-8")
    if len(raw) <= MAX:
        return text, False, len(raw)
    cut = raw[:MAX].decode("utf-8", "ignore")
    cut = cut[:cut.rfind("\n") + 1] if "\n" in cut else cut
    return cut + CUT, True, len(raw)


def payload(project):
    """What the Briefing tab draws, and what `bb preamble --json` prints."""
    whole = block(project)
    text, capped, size = fit(whole)
    return {"text": text, "bytes": size, "max": MAX, "capped": capped,
            "parts": [{"name": n, "bytes": len(t.encode("utf-8"))}
                      for n, t in parts(project)]}
