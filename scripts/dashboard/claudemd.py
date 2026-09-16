#!/usr/bin/env python3
"""A project's environment block: where it lives, what it should say, and
whether what it says is from this BuilderBot.

The block is rendered from the template the image ships
(config/templates/project-CLAUDE.md) into a project's CLAUDE.local.md, and
everything here is a read of one of those two files: the span between the
markers, the parts that apply to this tree, the compatibility window on the
line under the begin marker, and the pair of files a new project starts
with. No state and nothing to configure, so bb's own Python and the server
read the same answers. Out of server.py (R60), which held it for want of a
home.
"""
import os
import re
from pathlib import Path


# Where the image keeps the CLAUDE.md the environment block is copied from.
# Same file `bb claude-md` reads; overridable only so the tests can point at a
# checkout instead of an installed image.
TEMPLATE_MD = Path(os.environ.get("TEMPLATE_MD",
                                  "/opt/builderbot/templates/project-CLAUDE.md"))
ENV_BEGIN = "<!-- BUILDERBOT:ENV:BEGIN -->"
ENV_END = "<!-- BUILDERBOT:ENV:END -->"


def md_file(d):
    """Where a project's environment block lives, for a project DIRECTORY.

    `CLAUDE.local.md`, which is the render and is gitignored: the template in
    this repo is the source, and a rendered block is an artifact, so git
    carries the template and the project's own notes and never the output
    (roadmap R50). Claude Code loads it beside CLAUDE.md (2.1.270 names it
    "the local file" among the instruction files it reads), so a session is
    briefed by both without either importing the other.

    Falls back to CLAUDE.md, which is where every block written before the
    move still is. That fallback is the migration and nothing else: the first
    `bb claude-md --update` moves the block out and leaves the notes, and from
    then on the old place holds none. Without it every project would read as
    having no block at all the moment this shipped, which is the state that
    ghosts the Claude button.
    """
    d = Path(d)
    local = d / "CLAUDE.local.md"
    return local if local.is_file() else d / "CLAUDE.md"


def md_block(path):
    """The environment block of a CLAUDE.md, markers included, or None.

    The same span `bb claude-md` compares: everything below the end marker is
    the project's own writing and is never read here.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    lines, out = text.splitlines(), []
    for line in lines:
        if not out and ENV_BEGIN not in line:
            continue
        out.append(line)
        if ENV_END in line:
            return "\n".join(out)
    return None                          # no begin marker, or no end after it


_MD_IF = re.compile(r"<!-- BUILDERBOT:IF ([^>]*?) *-->")
_MD_END = "<!-- BUILDERBOT:END -->"


def md_for(tree):
    """The template's block as THIS project should have it.

    Parts of the file only apply to some projects (Android, the dev instance),
    and every project used to carry both on every session. The template
    marks them with the evidence that decides each one:

        <!-- BUILDERBOT:IF android *.gradle android AndroidManifest.xml -->

    The patterns live there and not here on purpose. `bb claude-md` renders
    the same block when it writes the file, and two lists of evidence would
    have each side reporting the other's answer as drift forever, which is
    exactly what happened the first time this was written with the conditions
    in the code. The template is the one copy; both readers are a glob.

    Evidence in the TREE rather than on the machine, for the same reason: the
    projects share is mounted by the controller and every node, so they all
    read the same answer.
    """
    want = md_block(TEMPLATE_MD)
    if want is None:
        return None
    out, skip = [], False
    for line in want.split("\n"):
        m = _MD_IF.search(line)
        if m:
            bits = m.group(1).split()
            skip = not (bits and any(_has(tree, p) for p in bits[1:]))
            continue
        if _MD_END in line:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)


def _has(tree, pattern):
    try:
        return any(True for _ in Path(tree).glob(pattern))
    except (OSError, ValueError):
        return False


def md_state(path):
    """"current" | "stale" | "unmarked" | "unknown" for a project's CLAUDE.md.

    Compared here rather than by shelling out to `bb claude-md` once per project
    on every fifteen-second poll: the comparison is two file reads, and a
    subprocess per project per poll is not.
    """
    want = md_for(Path(path).parent)
    if want is None:
        return "unknown"                 # no template to compare against
    have = md_block(path)
    if have is None:
        return "unmarked"
    return "current" if have == want else "stale"


_WINDOW_RE = re.compile(r"BUILDERBOT:ENV:WINDOW (\d+\.\d+)")


def md_window(path):
    """The compatibility window a CLAUDE.md's environment block was written
    for ("0.4", from the BUILDERBOT:ENV:WINDOW line under the begin marker),
    or "" for a block that predates the line. Only the line inside the
    markers counts, so a project's own notes cannot claim one. Empty means
    "cannot say", read the way nodes.agent_window reads it: never as a gap."""
    m = _WINDOW_RE.search(md_block(path) or "")
    return m.group(1) if m else ""


def md_gap(path):
    """A sentence when a project's block is from an EARLIER compatibility
    window than the template this controller ships, else "".

    The window is the same promise the agent's is (nodes.agent_window): while
    BuilderBot is 0.5.x, a 0.5 block briefs a session truthfully enough for
    it to work, and drift inside the window (a feature the block does not
    mention yet) is routine: the row offers the update, and nothing stops
    for it. A block from an earlier window is the state a session is refused,
    ghosted and ended over, until it is updated (compat_reap_once, bb-tty,
    the row's button): it describes a BuilderBot that no longer exists, so it
    would brief a session about verbs that are gone.

    A block from a LATER window is not that, and holding one was a bug the
    operator hit: it happens on the project whose checkout IS the next
    version, where the container has simply not been rebuilt yet. Nothing is
    broken there (the block over-promises rather than misleading, and the
    session's own `bb` comes from the container either way), and the remedy
    the message offered made it worse, since restamping the block DOWN to the
    container's window immediately contradicts the tree it was generated
    from, and updating the container puts it back. A gate whose fix
    oscillates is not a gate. So: ahead is drift, told once, stopping
    nothing.
    """
    ours, theirs = md_window(TEMPLATE_MD), md_window(path)
    if not ours or not theirs or ours == theirs:
        return ""
    if _win(theirs) > _win(ours):
        return ""
    return (f"CLAUDE.md's environment block is from an older compatibility window "
            f"({theirs} against {ours}): a session briefed with it would be told about "
            "a different BuilderBot. The update link on the row fixes it in one press")


def _win(w):
    """A window as a comparable pair. Unreadable sorts lowest, which only
    reaches a comparison the callers have already guarded with `if not`."""
    try:
        return tuple(int(x) for x in str(w).split(".")[:2])
    except ValueError:
        return (0, 0)


def build_claude_md(about, tree=None):
    """A new project's two files, as (block, notes).

    The block is what goes in CLAUDE.local.md and is not committed; the notes
    are CLAUDE.md, the operator's own when they gave any and the template's
    placeholder section otherwise.

    The same pair `bb claude-md --init` writes; building it here as well means
    the notes land in one write instead of a copy the operator then has to
    edit.

    `tree` is where it is about to land, and it is rendered for that tree, or
    the first poll after creating the project reports drift against the file
    this just wrote. A cloned repository with a compose file in it gets that
    section from the start; an empty one gets neither and gains one when the
    evidence arrives.
    """
    try:
        text = TEMPLATE_MD.read_text()
    except OSError:
        return None                      # no template: older image, say so
    block = md_for(tree) if tree is not None else md_block(TEMPLATE_MD)
    if block is None:
        return None
    i = text.find(ENV_END)
    tail = text[i + len(ENV_END):] if i >= 0 else ""
    if about:
        tail = "## About this project\n\n" + about.rstrip() + "\n"
    # Starting at its own first heading: the separator under the end marker
    # divided two halves of one file, and there is nothing to divide in a
    # file of its own. Line by line rather than lstrip of a character set,
    # which would also eat the first dash of real content.
    lines = tail.splitlines()
    while lines and lines[0].strip() in ("", "---"):
        lines.pop(0)
    return block, "\n".join(lines) + ("\n" if lines else "")
