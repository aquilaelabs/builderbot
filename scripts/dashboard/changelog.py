#!/usr/bin/env python3
"""The user-facing record of what changed, kept beside the VERSION it dates.

This file exists because commit messages are the wrong document for a person
using the app. A commit says what happened to the code, in the code's terms;
a changelog line says what changed for the person holding the product. The
operator's rule, and the reason sessions are told to write these separately:
the pull request information does not need to be the same.

**How it accrues, and why bumping is not part of it.** Entries land under
`## Unreleased` as work is done — each stamped with the commit it describes —
and the file simply grows. A version bump then renames that section to the
new version with the date. The bump is only the date break: whoever presses
it, and whenever they press it, nothing that was logged is lost waiting. That
decoupling is what lets the operator keep the number while sessions keep the
record.

**Shape.** CHANGELOG.md, one per versioned thing: the project's beside its
VERSION, a component's beside its own. `## Unreleased` on top while anything
is unreleased, dated `## X.Y.Z — YYYY-MM-DD` sections below, newest first.
Close enough to the Keep a Changelog convention to be read by anyone who has
seen one, without promising conformance this module does not check.

**Deliberately path-pure.** Every function takes the directory that holds the
file. Which directory a project or component maps to is version.py's question
(_sub resolves and prefix-checks it, because components arrive from a
browser); answering it twice here would be a second copy that drifts. So this
module has no configure() and no state — the callers that already resolved
the directory hand it over.
"""
from pathlib import Path

FILE = "CHANGELOG.md"

HEADER = "# Changelog\n"
UNRELEASED = "## Unreleased"


def path(d):
    return Path(d) / FILE


def read(d):
    """The whole file, or None where there is none. None and empty differ:
    a project with no changelog has not opted in, and the tab says how."""
    try:
        return path(d).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def unreleased(d):
    """The entry lines waiting for a bump to date them."""
    return unreleased_text(read(d))


def unreleased_text(text):
    """The same, from text already in hand — so a caller that needs both the
    file and the count pays for one read, not two."""
    if text is None:
        return []
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() == UNRELEASED:
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside and line.strip().startswith("- "):
            out.append(line.strip())
    return out


def add(d, text, sha=""):
    """Log one user-facing change under Unreleased, creating what is missing.

    The sha is the commit the entry describes — passed in rather than looked
    up, keeping this module free of git. It goes at the end of the line in
    parentheses: quiet enough to skim past, present enough that "when did
    that change" has a one-step answer.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return {"error": "an empty changelog entry says nothing to anybody"}
    if len(text) > 300:
        return {"error": "keep an entry under 300 characters — it is one line "
                         "of a list a person reads, not the whole story"}
    entry = f"- {text}" + (f" ({sha})" if sha else "")
    cur = read(d)
    try:
        if cur is None:
            path(d).write_text(f"{HEADER}\n{UNRELEASED}\n\n{entry}\n",
                               encoding="utf-8")
            return {"ok": True, "created": True}
        lines = cur.splitlines()
        if UNRELEASED in (ln.strip() for ln in lines):
            # Append at the end of the Unreleased section, keeping arrival
            # order: the section reads as a story of the cycle, oldest first.
            out, inside, done = [], False, False
            for ln in lines:
                if ln.strip() == UNRELEASED:
                    inside = True
                elif inside and not done and ln.startswith("## "):
                    while out and not out[-1].strip():
                        out.pop()
                    out.extend([entry, ""])
                    done = True
                    inside = False
                out.append(ln)
            if not done:
                while out and not out[-1].strip():
                    out.pop()
                out.append(entry)
            path(d).write_text("\n".join(out) + "\n", encoding="utf-8")
        else:
            # No Unreleased section: the last bump rolled it away, or the
            # file was written by hand. Reopen one above the dated history.
            out, placed = [], False
            for ln in lines:
                if not placed and ln.startswith("## "):
                    out.extend([UNRELEASED, "", entry, ""])
                    placed = True
                out.append(ln)
            if not placed:
                out.extend(["", UNRELEASED, "", entry])
            path(d).write_text("\n".join(out) + "\n", encoding="utf-8")
        return {"ok": True}
    except OSError as e:
        return {"error": f"could not write {FILE}: {e}"}


def roll(d, version, date):
    """Date the Unreleased section as `version`, ready to commit with it.

    Returns True when there was something to roll. An empty cycle rolls
    nothing rather than writing a section holding only a date — the warning
    about that belongs at the moment of bumping, not in the shipped file.
    """
    if not unreleased(d):
        return False
    text = read(d)
    out, renamed = [], False
    for ln in text.splitlines():
        if not renamed and ln.strip() == UNRELEASED:
            # Only the first: unreleased() counted entries from the first
            # heading, and a hand-edited file with a stray duplicate must not
            # gain two identical version sections in one roll.
            out.append(f"## {version} — {date}")
            renamed = True
        else:
            out.append(ln)
    try:
        path(d).write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True
