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


CATEGORY = "### "
MAX_TEXT = 300


def groups(d):
    """The Unreleased section as [{name, entries: [{text, shas}]}].

    A category is a `### Name` subsection, which is the shape Keep a Changelog
    uses and the one this file was already close to — so a reader who has seen
    one is not learning a private format, and a diff of a recategorised entry
    is a moved line rather than a rewritten file.

    Entries logged before any category sit in a group whose name is "", first,
    because that is where they are in the file. It only exists when something
    is in it.

    ORDER IS THE FILE'S, and deliberately. Categories and the entries in them
    are arranged by hand, so what a reader meets first is what somebody
    decided should come first — not what happened to be committed earliest.
    The commits are still on every line and still answer "when did that
    change"; they just no longer decide the running order.
    """
    out, cur = [], {"name": "", "entries": []}
    inside = False
    for line in (read(d) or "").splitlines():
        if line.strip() == UNRELEASED:
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if not inside:
            continue
        if line.startswith(CATEGORY):
            if cur["entries"] or cur["name"]:
                out.append(cur)
            cur = {"name": line[len(CATEGORY):].strip(), "entries": []}
            continue
        if line.strip().startswith("- "):
            body = line.strip()[2:].strip()
            m = _STAMP.search(body)
            cur["entries"].append({"text": body[:m.start()] if m else body,
                                   "shas": m.group(1).split(", ") if m else []})
    if cur["entries"] or cur["name"]:
        out.append(cur)
    return out


def _clean_text(t):
    t = " ".join(str(t or "").split())
    if not t:
        raise _Refused("an empty changelog entry says nothing to anybody")
    if len(t) > MAX_TEXT:
        raise _Refused(f"keep an entry under {MAX_TEXT} characters — it is one "
                       "line of a list a person reads, not the whole story")
    return t


def _clean_name(n):
    n = " ".join(str(n or "").split())
    if len(n) > 40:
        raise _Refused("a category is a word or two, not a sentence")
    if "\n" in n or n.startswith("#"):
        raise _Refused("a category name cannot carry markdown of its own")
    return n


def put(d, gs):
    """Write the Unreleased section from the structure `groups` returns.

    The whole section at once, because that is what an editor sends: a person
    rearranging a list is not making one edit, and applying their result as a
    sequence of moves would let a failure halfway leave a shape nobody asked
    for.

    An empty group is dropped rather than written as a heading with nothing
    under it — a category with no entries is a category somebody emptied.
    """
    try:
        rows = []
        for g in (gs or []):
            name = _clean_name((g or {}).get("name"))
            ents = []
            for e in ((g or {}).get("entries") or []):
                shas = [str(x) for x in (e or {}).get("shas") or []
                        if re.fullmatch(r"[0-9a-f]{7,40}", str(x))]
                ents.append((_clean_text((e or {}).get("text")), shas))
            if ents:
                rows.append((name, ents))
    except _Refused as e:
        return {"error": str(e)}
    # The uncategorised group carries no heading, so the file can only put it
    # first: written after a category its entries read as that category's,
    # which is what a reversed arrangement did. Hoisted rather than refused —
    # somebody rearranging categories is not asking about this one.
    rows.sort(key=lambda r: 0 if not r[0] else 1)
    lines = []
    for name, ents in rows:
        if name:
            if lines:
                lines.append("")
            lines.append(CATEGORY + name)
            lines.append("")
        lines.extend(f"- {t}" + (f" ({', '.join(sh)})" if sh else "") for t, sh in ents)
    cur = read(d) or ""
    out, inside, put_it = [], False, False
    for ln in cur.splitlines():
        if ln.strip() == UNRELEASED:
            inside = True
            out.append(ln)
            out.append("")
            out.extend(lines)
            put_it = True
            continue
        if inside and ln.startswith("## "):
            inside = False
            out.append("")
            out.append(ln)
            continue
        if inside:
            continue
        out.append(ln)
    if not put_it:
        # No Unreleased section: the last bump dated it away. It reopens ABOVE
        # the dated releases, because the file is newest first and what is
        # accruing is newer than anything that shipped. Appending it to the
        # end put the new cycle under the history.
        at = next((i for i, ln in enumerate(out) if ln.startswith("## ")), len(out))
        out = out[:at] + ["", UNRELEASED, ""] + lines + [""] + out[at:]
    try:
        path(d).write_text("\n".join(_tidy(out)) + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {FILE}: {e}"}
    return {"ok": True, "entries": sum(len(e) for _, e in rows),
            "categories": len([n for n, _ in rows if n])}


def add(d, text, sha="", cat=""):
    """Log one user-facing change under Unreleased, creating what is missing.

    The sha is the commit the entry describes — passed in rather than looked
    up, keeping this module free of git. It goes at the end of the line in
    parentheses: quiet enough to skim past, present enough that "when did that
    change" has a one-step answer.

    `cat` puts it in a category, making one at the END of the section if it is
    new. The end, because a session logging a change does not get to decide
    where a category sits in what a reader meets — that is an arrangement, and
    arrangements are the operator's.
    """
    try:
        text, cat = _clean_text(text), _clean_name(cat)
    except _Refused as e:
        return {"error": str(e)}
    if read(d) is None:
        entry = f"- {text}" + (f" ({sha})" if sha else "")
        body = f"{CATEGORY}{cat}\n\n{entry}" if cat else entry
        try:
            path(d).write_text(f"{HEADER}\n{UNRELEASED}\n\n{body}\n", encoding="utf-8")
        except OSError as e:
            return {"error": f"could not write {FILE}: {e}"}
        return {"ok": True, "created": True}
    gs = groups(d)
    hit = next((g for g in gs if g["name"] == cat), None)
    if hit is None:
        hit = {"name": cat, "entries": []}
        # An uncategorised entry belongs above the categories, where the file
        # already puts them; a new category goes on the end.
        gs.insert(0, hit) if not cat else gs.append(hit)
    hit["entries"].append({"text": text, "shas": [sha] if sha else []})
    return put(d, gs)


_STAMP = re.compile(r"\s*\(([0-9a-f]{7,40}(?:, [0-9a-f]{7,40})*)\)$")   # --short=7 grows on ambiguity


def numbered(d):
    """The Unreleased entries as [(n, text, [shas], category)], n counting
    from 1 in the section's order — the handle every verb below takes.

    Numbers are positional and not stored: the section is short-lived by
    design, and an id scheme on a list a bump erases would outlive its
    usefulness by one release. They move when the section is rearranged,
    which is why anything naming one reads the list first.
    """
    out = []
    for g in groups(d):
        for e in g["entries"]:
            out.append((len(out) + 1, e["text"], list(e["shas"]), g["name"]))
    return out


class _Refused(Exception):
    """An operation saying no from inside one of the functions below."""


def _flat(d):
    """[(category, text, shas)] in the section's order."""
    return [(c, t, sh) for _, t, sh, c in numbered(d)]


def _regroup(rows, order=()):
    """Back to the group shape, with the categories in `order` — the
    arrangement already in the file — and any category new to it appended.

    Taking the order from the rows instead put a category wherever its
    earliest entry happened to sit, so a session moving one line into an
    existing category dragged that whole category to the front of somebody
    else's arrangement. A new category still lands at the end, which is what
    `add --cat` does and for the same reason: where a category sits is not a
    session's call.
    """
    out, at = [], {}
    for name in order:
        at[name] = {"name": name, "entries": []}
        out.append(at[name])
    for cat, text, shas in rows:
        if cat not in at:
            at[cat] = {"name": cat, "entries": []}
            out.append(at[cat])
        at[cat]["entries"].append({"text": text, "shas": shas})
    return out


def _apply(d, change):
    """Run `change` over the flat rows and write the result, keeping the
    categories where the file already had them."""
    order = [g["name"] for g in groups(d)]
    try:
        return put(d, _regroup(change(_flat(d)), order))
    except _Refused as e:
        return {"error": str(e)}


def _pick(rows, ns):
    """The 1-based numbers `ns` as indexes into rows, or a refusal.

    Refused for a number nobody has rather than silently doing less than
    asked: these verbs rewrite a list somebody is looking at.
    """
    want = []
    for n in ns:
        try:
            i = int(n)
        except (TypeError, ValueError):
            raise _Refused("which entry? `bb changelog unreleased` numbers them")
        if not 1 <= i <= len(rows):
            raise _Refused(f"no unreleased entry {i} — `bb changelog unreleased` "
                           f"lists {len(rows)}; a dated section is history, and "
                           f"`bb version unroll` is how one is reopened")
        if i - 1 in want:
            raise _Refused(f"entry {i} named twice")
        want.append(i - 1)
    return want


def edit(d, n, text=None, sha="", cat=None):
    """Reword Unreleased entry n, move it between categories, or both.

    The reword is for a change that tweaks something already logged this
    cycle: a second line about the same thing tells the reader about one
    change twice, and the honest record is one line that is right. The stamp
    the entry had stays and this commit's joins it, so "when did that change"
    still answers for both.

    `text` of None keeps the words — for a move, where retyping the whole
    line to change where it sits is a typo waiting to silently rewrite it.
    `cat` of None keeps the category. A caller that passes neither a sha nor
    new words changes nothing about what the entry says, and nothing should
    then be claiming to have caused it.

    A move files the entry at the END of the named category, which is where
    `add --cat` puts one. The two used to disagree: a move kept the line's
    running position, and an uncategorised line's position is the top of the
    section, so filing a cycle's entries one at a time stacked each category
    up backwards. Same gesture, same place, either way.

    Only Unreleased is editable: a dated section is a release somebody may
    have read.
    """
    def go(rows):
        [i] = _pick(rows, [n])
        was_cat, was_text, shas = rows[i]
        if sha and sha not in shas:
            shas = shas + [sha]
        words = was_text if text is None else _clean_text(text)
        if cat is None:
            return rows[:i] + [(was_cat, words, shas)] + rows[i + 1:]
        to = _clean_name(cat)
        rest = rows[:i] + rows[i + 1:]
        last = max((j for j, r in enumerate(rest) if r[0] == to), default=None)
        at = len(rest) if last is None else last + 1
        return rest[:at] + [(to, words, shas)] + rest[at:]
    r = _apply(d, go)
    if not r.get("error"):
        r["n"] = int(n)
    return r


def remove(d, n):
    """Drop one Unreleased entry.

    For a line that stopped being true — the change it described was undone,
    or a later one replaced it — where rewording would leave the reader with a
    note about something that never shipped. The commit is untouched; this is
    the record of what a person sees, not of what happened to the code.
    """
    def go(rows):
        [i] = _pick(rows, [n])
        return rows[:i] + rows[i + 1:]
    return _apply(d, go)


def merge(d, ns, text, cat=None):
    """Fold several Unreleased entries into one line carrying all their
    commits.

    Two lines about one change tell the reader about it twice, and that
    happens whenever a thing is built across commits that each looked like
    their own story at the time. The new line lands where the EARLIEST of them
    was and in that one's category unless told otherwise, and it carries every
    commit in the order they were already in.
    """
    def go(rows):
        want = _pick(rows, ns)
        if len(want) < 2:
            raise _Refused("merge takes two entries or more")
        shas, seen = [], set()
        for i in want:
            for sh in rows[i][2]:
                if sh not in seen:
                    seen.add(sh)
                    shas.append(sh)
        at = min(want)
        line = (rows[at][0] if cat is None else _clean_name(cat),
                _clean_text(text), shas)
        return [line if j == at else r
                for j, r in enumerate(rows) if j == at or j not in want]
    return _apply(d, go)


def split(d, n):
    """Break one Unreleased entry into one line per commit it carries.

    The way back out of a merge, and the way to drop a single commit from a
    line: split, then remove the one that stopped being true. Each line keeps
    the text and the category, because there is no way to know which words
    belonged to which commit — they are there to be reworded, which is the
    next thing you do.
    """
    def go(rows):
        [i] = _pick(rows, [n])
        cat, text, shas = rows[i]
        if len(shas) < 2:
            raise _Refused(f"entry {int(n)} carries "
                           f"{'one commit' if shas else 'no commit'}, so there "
                           f"is nothing to split it along")
        return rows[:i] + [(cat, text, [sh]) for sh in shas] + rows[i + 1:]
    return _apply(d, go)


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


_SERIES = re.compile(r"^(\d+)\.(\d+)(?:\.|\b)")


def series_of(title):
    """The MAJOR.MINOR a dated section belongs to, or "" for a title that is
    not a version — `Unreleased`, and anything hand-written."""
    m = _SERIES.match((title or "").strip())
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def since_minor(secs):
    """`sections` trimmed to what is unreleased plus the newest minor series.

    The About panel is read by somebody asking what changed in the build in
    front of them, and the whole file is the wrong answer there: it grows for
    the life of the project. So the panel shows everything unreleased and the
    dated releases of the newest minor — 0.6.2, 0.6.1, 0.6.0 — and nothing
    older. When 0.7.0 is cut, 0.6's releases fall off it in that one gesture,
    without anybody pruning a file.

    Nothing is deleted and nothing is lost: CHANGELOG.md keeps every release
    forever and stays the place to read them, which is why the panel says how
    many it is not showing rather than quietly ending.

    Returns (kept, held, series).
    """
    at = next((i for i, s in enumerate(secs) if series_of(s.get("title"))), None)
    if at is None:
        return list(secs), 0, ""
    series = series_of(secs[at]["title"])
    keep = list(secs[:at])
    # The file is newest first, so the series' own releases are contiguous
    # from here; the first section that is not one of them ends the list.
    for s in secs[at:]:
        if series_of(s.get("title")) != series:
            break
        keep.append(s)
    return keep, len(secs) - len(keep), series


def sections(text):
    """The whole file as [{"title", "entries": [{"text", "shas", "cat"}]}],
    newest first as the file is written: Unreleased, then each dated release.
    For the welcome panel, which shows BuilderBot's own changelog and marks
    where the reader last looked.

    The entries stay FLAT, each carrying the category it sits under, rather
    than nesting. The panel draws a line under what is new since the reader
    last looked, and finding that line means counting entries in the order
    they are written; nesting would make every consumer walk two levels to do
    it, for a grouping the renderer can do by watching the name change.
    """
    out, cur, cat = [], None, ""
    for line in (text or "").splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "entries": []}
            cat = ""
            out.append(cur)
            continue
        if cur is not None and line.startswith(CATEGORY):
            cat = line[len(CATEGORY):].strip()
            continue
        if cur is not None and line.strip().startswith("- "):
            body = line.strip()[2:].strip()
            m = _STAMP.search(body)
            cur["entries"].append({"text": body[:m.start()].rstrip() if m else body,
                                   "shas": m.group(1).split(", ") if m else [],
                                   "cat": cat})
    return out
