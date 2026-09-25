"""Behind `bb changelog` (cmd_changelog in bb): this project's CHANGELOG.md
as dashboard/changelog.py reads it, the same module the notebook's
Changelog view and a version bump use.

Arguments: version.py's path, the project, then the words (--for DIR and
the verb). BB_WORKSPACE says where the projects are, DASHBOARD_STATE
where the dashboard's files are, and BB_VERSION_TREE names a worktree
when the question is asked from one.
"""
import os
import sys

import dash

_here = dash.beside(sys.argv[1])
version = dash.load("version", _here)
statefile = dash.statefile(_here)
changelog = dash.load("changelog", _here)
version.configure(workspace=os.environ.get("BB_WORKSPACE", "/workspace"),
                  state=os.environ.get("DASHBOARD_STATE", "/config"),
                  write_json=lambda *a: None)

proj, argv = sys.argv[2], sys.argv[3:]
comp = ""
if "--for" in argv:
    i = argv.index("--for")
    if i + 1 >= len(argv):
        print("--for needs a component directory", file=sys.stderr)
        raise SystemExit(1)
    comp = argv[i + 1]
    argv = argv[:i] + argv[i + 2:]

d = version._sub(proj, comp)
if d is None:
    print(f"no such component here: {comp}", file=sys.stderr)
    raise SystemExit(1)

# --cat NAME files the entry under a category, the `### Name` subsections a
# reader knows from Keep a Changelog. A new one lands at the END: where a
# category sits in what a reader meets is an arrangement, and arrangements
# are the operator's, on the Changelog editor.
cat, moving = "", False
if "--cat" in argv:
    i = argv.index("--cat")
    if i + 1 >= len(argv):
        print("--cat needs a category name", file=sys.stderr)
        raise SystemExit(1)
    cat, moving = argv[i + 1], True
    argv = argv[:i] + argv[i + 2:]

# A line corrected rather than changed. An edit normally names the commit
# that made the change, which is the point of the stamp; a pass over the
# wording, or a move between categories, is not a change and must not claim
# one. 22 entries all naming the commit that reworded them is a record of
# nothing.
stamp = True
if "--no-stamp" in argv:
    stamp = False
    argv = [a for a in argv if a != "--no-stamp"]

if argv and argv[0] == "add":
    if len(argv) < 2 or not argv[1].strip():
        print('bb changelog add "what changed, for the person using it" '
              '--cat NAME [--for DIR]\n' + changelog.rules(), file=sys.stderr)
        raise SystemExit(1)
    # A category is asked for rather than assumed. Filed under none, an entry
    # lands in a heap above the headings, and a changelog that is mostly heap
    # is what this repository's own had become: the refusal is where a session
    # learns which categories there are, since nothing else ever told it.
    if not cat.strip():
        print(changelog.rules(), file=sys.stderr)
        raise SystemExit(1)
    if not changelog.standard(changelog.canonical(cat)):
        print(f"filed under {cat!r}, which is this project's own category rather than one "
              "of the six; kept as typed", file=sys.stderr)
    # Stamped with HEAD: the instruction in the template is to log after
    # committing, so the sha names the commit the entry describes.
    sha = version._git(proj, "rev-parse", "--short=7", "HEAD") or ""
    r = changelog.add(d, argv[1], sha=sha, cat=cat)
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    n = len(changelog.unreleased(d))
    print(f"logged{' (new ' + changelog.FILE + ')' if r.get('created') else ''}: "
          f"{n} unreleased entr{'y' if n == 1 else 'ies'} now waiting for a bump")
    # ...and that the file is now modified. An entry is stamped with the commit
    # it describes, so it is written AFTER that commit and lands in the next
    # one: every entry but a session's last gets swept up by the commit that
    # follows it, and the last one sits in a dirty tree that Pull, Switch and
    # Merge all refuse on (B162). Said rather than committed here, because the
    # wording belongs with whatever commit the author is making next.
    print(f"{changelog.FILE} is modified now: commit it with your next commit",
          file=sys.stderr)
    raise SystemExit(0)

if argv and argv[0] == "unreleased":
    rows = changelog.numbered(d)
    if not rows:
        print("nothing unreleased here")
    seen = None
    for n, text, shas, group in rows:
        if group != seen:
            seen = group
            print(f"  {group or '(no category)'}")
        print(f"{n:3d}  {text}" + (f"  ({', '.join(shas)})" if shas else ""))
    raise SystemExit(0)

if argv and argv[0] == "edit":
    words = argv[2] if len(argv) > 2 else None
    if len(argv) < 2 or (words is None and not moving) or (words is not None and not words.strip()):
        print('bb changelog edit N "the line as it should read now" [--cat NAME]\n'
              "bb changelog edit N --cat NAME        move it, leaving the words alone",
              file=sys.stderr)
        raise SystemExit(1)
    # Nothing is claimed for a move on its own: the entry says what it said.
    sha = ""
    if stamp and words is not None:
        sha = version._git(proj, "rev-parse", "--short=7", "HEAD") or ""
    r = changelog.edit(d, argv[1], words, sha=sha, cat=cat if moving else None)
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    print(("reworded" if words is not None else "moved") + f" unreleased entry {r['n']}")
    raise SystemExit(0)

if argv and argv[0] == "merge":
    if len(argv) < 4 or not argv[-1].strip():
        print('bb changelog merge N M [...] "the one line for all of them" '
              '[--for DIR]', file=sys.stderr)
        raise SystemExit(1)
    r = changelog.merge(d, argv[1:-1], argv[-1], cat=cat or None)
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    print(f"merged into one entry; {r['entries']} unreleased now")
    raise SystemExit(0)

if argv and argv[0] == "split":
    if len(argv) < 2:
        print("bb changelog split N [--for DIR]", file=sys.stderr)
        raise SystemExit(1)
    r = changelog.split(d, argv[1])
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    print(f"split into one entry per commit; {r['entries']} unreleased now. "
          f"Reword them, or drop the one that stopped being true.")
    raise SystemExit(0)

if argv and argv[0] == "rm":
    if len(argv) < 2:
        print("bb changelog rm N [--for DIR]", file=sys.stderr)
        raise SystemExit(1)
    r = changelog.remove(d, argv[1])
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        raise SystemExit(1)
    print(f"dropped it; {r['entries']} unreleased now")
    raise SystemExit(0)

if argv:
    print("bb changelog [--for DIR]         read it\n"
          'bb changelog add "..." [--cat NAME]  log a user-facing change\n'
          "bb changelog unreleased          the entries waiting for a bump, numbered\n"
          'bb changelog edit N "..."        reword one of them; --cat NAME moves it,\n'
          "                                 and on its own moves it without rewording\n"
          "                                 (--no-stamp: a correction, not a change)\n"
          'bb changelog merge N M "..."     one line for several, carrying their commits\n'
          "bb changelog split N             back into one line per commit\n"
          "bb changelog rm N                drop one that stopped being true\n"
          "\nA category is a `### Name` subsection. Which ones exist and what\n"
          "order they and their lines sit in is the operator's, on the\n"
          "Changelog editor beside the version.",
          file=sys.stderr)
    raise SystemExit(1)

text = changelog.read(d)
if text is None:
    print(f"no {changelog.FILE} here yet; the first "
          f"`bb changelog add` creates it")
    raise SystemExit(0)
print(text, end="")
