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
import re
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


_STAMP = re.compile(r"\s*\(([0-9a-f]{7,40}(?:, [0-9a-f]{7,40})*)\)$")   # --short=7 grows on ambiguity


def numbered(d):
    """The Unreleased entries as [(n, text, [shas])], n counting from 1 in
    the section's order — the handle `edit` takes. Numbers are positional
    and not stored: the section is short-lived by design, and an id scheme
    on a list a bump erases would outlive its usefulness by one release."""
    out = []
    for i, line in enumerate(unreleased(d), 1):
        body = line[2:].strip()
        m = _STAMP.search(body)
        shas = m.group(1).split(", ") if m else []
        out.append((i, body[:m.start()] if m else body, shas))
    return out


def edit(d, n, text, sha=""):
    """Reword Unreleased entry n, for a change that tweaks something already
    logged this cycle: a second line about the same thing tells the reader
    about one change twice, and the honest record is one line that is right.

    The stamp the entry had stays and this commit's joins it, so "when did
    that change" still answers for both. Only Unreleased is editable — a
    dated section is a release somebody may have read, and history is not
    corrected in place.
    """
    text = " ".join(str(text or "").split())
    if not text:
        return {"error": "an empty changelog entry says nothing to anybody"}
    if len(text) > 300:
        return {"error": "keep an entry under 300 characters — it is one line "
                         "of a list a person reads, not the whole story"}
    rows = numbered(d)
    try:
        n = int(n)
    except (TypeError, ValueError):
        return {"error": "which entry? `bb changelog unreleased` numbers them"}
    if not 1 <= n <= len(rows):
        return {"error": f"no unreleased entry {n} — `bb changelog unreleased` "
                         f"lists {len(rows)}; a dated section is history and stays as it is"}
    _, _, shas = rows[n - 1]
    if sha and sha not in shas:
        shas = shas + [sha]
    entry = f"- {text}" + (f" ({', '.join(shas)})" if shas else "")
    cur = read(d) or ""
    out, inside, seen, done = [], False, 0, False
    for ln in cur.splitlines():
        if ln.strip() == UNRELEASED:
            inside = True
        elif inside and ln.startswith("## "):
            inside = False
        elif inside and ln.strip().startswith("- ") and not done:
            seen += 1
            if seen == n:
                out.append(entry)
                done = True
                continue
        out.append(ln)
    try:
        path(d).write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {FILE}: {e}"}
    return {"ok": True, "n": n}


def unroll(d, version):
    """Dissolve a version's dated section back into Unreleased.

    The undo of roll(), for a bump somebody thought better of: the section's
    entries rejoin whatever has been logged since, so the next bump dates the
    whole group together. Only sensible while the version is unreleased —
    that judgment is the caller's, since tags are git's and this module is
    deliberately path-pure.

    The section's entries go at the TOP of Unreleased: add() appends, so the
    section entries are older than anything logged after the bump, and the
    oldest-first order the file keeps should survive the round trip.
    """
    text = read(d)
    if text is None:
        return False
    lines = text.splitlines()
    # The section: its heading, and its entry lines up to the next heading.
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith(f"## {version} —")), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    section = [ln for ln in lines[start + 1:end] if ln.strip().startswith("- ")]
    rest = lines[:start] + lines[end:]
    # Merge into an existing Unreleased, or the dissolved section becomes it.
    at = next((i for i, ln in enumerate(rest)
               if ln.strip() == UNRELEASED), None)
    if at is None:
        out = rest[:start] + [UNRELEASED, ""] + section + [""] + rest[start:]
    else:
        # Immediately before the first existing entry, so the merged run is
        # one contiguous list rather than two groups with a seam.
        j = next((i for i in range(at + 1, len(rest))
                  if rest[i].strip().startswith("- ")
                  or rest[i].startswith("## ")), len(rest))
        out = rest[:j] + section + rest[j:]
    try:
        path(d).write_text("\n".join(_tidy(out)) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _tidy(lines):
    """Collapse the blank-line runs the surgery above can leave behind."""
    out = []
    for ln in lines:
        if not ln.strip() and out and not out[-1].strip():
            continue
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


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


def sections(text):
    """The whole file as [{"title", "entries": [{"text", "shas"}]}], newest
    first as the file is written: Unreleased, then each dated release. For
    the welcome panel, which shows BuilderBot's own changelog and marks
    where the reader last looked."""
    out, cur = [], None
    for line in (text or "").splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "entries": []}
            out.append(cur)
            continue
        if cur is not None and line.strip().startswith("- "):
            body = line.strip()[2:].strip()
            m = _STAMP.search(body)
            cur["entries"].append({"text": body[:m.start()].rstrip() if m else body,
                                   "shas": m.group(1).split(", ") if m else []})
    return out
