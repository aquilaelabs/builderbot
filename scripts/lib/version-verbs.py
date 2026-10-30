"""Behind `bb version` (cmd_version in bb): this project's version identity in
whatever form is asking. Everything that decides what a version IS lives
in dashboard/version.py, because the notebook needs the same answers;
this resolves the words and prints what the module returns.

Arguments: version.py's path, the project, then the words (--code, --quad,
--json, bump PART, init X.Y.Z, unbump, --list, --for DIR, ...).
BB_WORKSPACE says where the projects are, DASHBOARD_STATE where the
dashboard's files are, and BB_VERSION_TREE names a worktree when the
question is asked from one.
"""
import json
import os
import sys

import dash

_here = dash.beside(sys.argv[1])
version = dash.load("version", _here)
write_json = dash.statefile(_here).write_json

# The changelog rides with the version: a bump dates its Unreleased section
# in the same commit, so the module that bumps needs the module that rolls.
changelog = dash.load("changelog", _here)

version.configure(workspace=os.environ.get("BB_WORKSPACE", "/workspace"),
                  state=os.environ.get("DASHBOARD_STATE", "/config"),
                  write_json=write_json, changelog_mod=changelog)

proj, argv = sys.argv[2], sys.argv[3:]

# --for NAME asks about a component: a directory with its own VERSION file.
# Pulled out of argv first so it can sit anywhere, which is what anybody
# typing `bb version --for extension --code` expects.
comp = ""
if "--for" in argv:
    i = argv.index("--for")
    if i + 1 >= len(argv):
        print("--for needs a component directory", file=sys.stderr)
        raise SystemExit(1)
    comp = argv[i + 1]
    argv = argv[:i] + argv[i + 2:]

USAGE = ("bb version [--for DIR] "
         "[--semver|--code|--quad|--win|--msi|--pep440|--file|--json]\n"
         "bb version --list                 every version this repo carries\n"
         "bb version [--for DIR] bump major|minor|patch\n"
         "bb version [--for DIR] set X.Y.Z     straight to a later version, as one bump; from a\n"
         "                                     number never released, its changelog notes come along\n"
         "bb version [--for DIR] unbump        take the last bump or set back, while unreleased: its\n"
         "                                     changelog section returns to Unreleased (once: the one\n"
         "                                     before it stays)\n"
         "bb version [--for DIR] init X.Y.Z    give one its first VERSION\n"
         "bb version policy                    what a session may move here\n"
         "bb version forward BRANCH            merge a released patch line (0.6.2) into this branch's\n"
         "                                     later line: its fixes carried, this line's number kept,\n"
         "                                     the changelog's sections placed by version\n"
         "bb version backport COMMIT           a fix from a later line onto this patch line, its\n"
         "                                     changelog entries under this line's Unreleased\n"
         "bb version [--for DIR] release --why \"...\"   tag this commit and publish the release, as\n"
         "                                     Release on the Artifacts view does (Agents may: Tag and\n"
         "                                     publish a release)\n"
         "A section dated under the wrong number: unbump, then set the number you meant.")


def fail(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def lands_line(prefix=""):
    """Where the number here lives against the branch builds come from,
    when they differ: version.lands, the same words the Artifacts view's
    version row shows. A bump on a branch already merged, unpushed, looked
    like the project's version while main still had the old one (B338)."""
    now = version.lands(proj, comp).get("now")
    if now:
        print(prefix + now)


def policy_line():
    pol = version.policy(proj)
    allowed = version.allows(pol)
    # `start` delegates no PART and still delegates something: the first
    # version. Said plainly, or a session reads "the operator only" and does
    # not try the one thing it may do.
    return (f"{pol}" + (f": a session may move {', '.join(allowed)}"
                        if allowed else
                        ": a session may give it its first version, and move nothing after"
                        if pol == "start" else ": the operator only"))


if argv and argv[0] == "bump":
    if len(argv) < 2:
        fail("bb version bump major|minor|patch")
    # `by` is not a flag: this runs AS the session, so the only honest value
    # is the one the policy is about. The operator's bumps come from the
    # dashboard, which calls bump() directly.
    r = version.bump(proj, argv[1], by="claude", comp=comp)
    if r.get("error"):
        fail(r["error"])
    print(f"{proj}{'/' + comp if comp else ''} {r['was']} -> {r['target']}  "
          f"({r['part']}, committed {r['commit']}, not pushed)")
    if r.get("note"):
        print(f"note: {r['note']}")
    lands_line()
    raise SystemExit(0)

if argv and argv[0] == "set":
    if len(argv) < 2:
        fail("bb version set X.Y.Z: a later version, moved to in one commit")
    r = version.jump(proj, argv[1], by="claude", comp=comp)
    if r.get("error"):
        fail(r["error"])
    print(f"{proj}{'/' + comp if comp else ''} {r['was']} -> {r['target']}  "
          f"({r['part']}, committed {r['commit']}, not pushed)")
    if r.get("note"):
        print(f"note: {r['note']}")
    lands_line()
    raise SystemExit(0)

if argv and argv[0] == "unbump":
    r = version.unbump(proj, by="claude", comp=comp)
    if r.get("error"):
        fail(r["error"])
    print(f"{proj}{'/' + comp if comp else ''} {r['was']} -> {r['target']}  "
          f"(returned, committed {r['commit']}, not pushed); its changelog "
          "section is back in Unreleased")
    lands_line()
    raise SystemExit(0)

if argv and argv[0] == "init":
    if len(argv) < 2:
        fail("bb version init X.Y.Z [--for DIR]")
    r = version.init(proj, argv[1], by="claude", comp=comp)
    if r.get("error"):
        fail(r["error"])
    print(f"{proj}{'/' + comp if comp else ''} is now {r['target']}  "
          f"(committed {r['commit']}, not pushed)")
    lands_line()
    raise SystemExit(0)

if argv and argv[0] == "release":
    # bb version release (R138): the tag on this commit and the forge's
    # release, made on the controller with the project's own credentials,
    # which this session never holds. Under Agents may: Tag and publish a
    # release: auto releases at once, ask waits for the project's owner.
    import bbapi
    import waits
    rest = argv[1:]
    # Help is help: `bb version release -h` was sent on as a release with
    # no reason (Shebang-DevBoard, 5 Oct), refused only because the tag
    # already existed. Anything but --why and its sentence is refused by name.
    if "-h" in rest or "--help" in rest:
        print('bb version [--for DIR] release --why "..."   tag this commit, push the tag and publish the\n'
              "    forge's release (GitHub, Gitea or GitLab), as Release on the Artifacts view does. Under\n"
              "    Agents may: Tag and publish a release: auto releases at once, ask waits for the\n"
              "    project's owner, deny refuses. A release whose Android APK could not be signed (bb\n"
              "    sign status) is refused before the tag; --without-apk releases it anyway, to be\n"
              "    signed after with bb sign release. --dev cuts the dev build's tag instead (vX.Y.Z-dev.N):\n"
              "    no bump, no changelog section; CI publishes it as a pre-release for the dev channel.\n"
              "    From any branch but the one builds ship from, a release is a dev one unless --stable\n"
              "    says otherwise; the first line printed names the channel it lands on.\n"
              'bb version [--for DIR] release --edit --why "..." [--tag TAG] [--notes FILE] [--attach FILE]...\n'
              "    change the published release: its notes replaced whole (- reads stdin), a file from\n"
              "    dist/ or the committed tree attached (one of the same name replaced), (asset:NAME) in\n"
              "    the notes the address of an attached file, (file:PATH) a committed picture shown from\n"
              "    the repository at its pushed commit, never a download: the way for a screenshot. TAG\n"
              "    is the version's own unless named. The same dial; on ask, every edit is its own ask.\n"
              'bb version [--for DIR] release --remove NAME [--remove NAME]... --why "..." [--tag TAG]\n'
              "    take files off the published release, named as the forge lists them: its own ask,\n"
              "    never part of an edit, the names checked against the release before anybody is asked.")
        raise SystemExit(0)
    why = ""
    if "--why" in rest:
        i = rest.index("--why")
        if i + 1 >= len(rest):
            fail("--why needs the sentence after it")
        why = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    # A release whose Android APK could not be signed is refused before the
    # tag unless this says to go on (R134 step 4).
    unsigned = "--without-apk" in rest
    # A dev pre-release (R179): the dev build's tag, vX.Y.Z-dev.N, on the
    # dev channel, its release page CI's.
    dev = "--dev" in rest
    # ...and a stable one from a branch other than main is said in so many
    # words (R190 step 1): without it, it is a dev one.
    stable = "--stable" in rest
    rest = [x for x in rest if x not in ("--without-apk", "--dev", "--stable")]
    if rest:
        fail(f"bb version release takes --why \"...\" [--without-apk] [--dev|--stable] and nothing else, not {rest[0]}")
    auth = os.environ.get("BB_VERSION_AUTH", "")
    r = bbapi.call("/api/version", {"action": "release", "project": proj, "component": comp, "why": why, "dev": dev,
                                    "stable": stable, "unsigned": unsigned}, auth=auth, timeout=240)
    if r.get("error"):
        fail(f"[builderbot] ERROR: {r['error']}")
    if r.get("channel"):
        print(f"[builderbot] {r['channel']}", file=sys.stderr)
    if r.get("id") and not r.get("released"):
        print(f"[builderbot] asked {r.get('to') or 'the project owner'} (#{r['id']}) to release, waiting up "
              "to 15 minutes for Approve in their bell", file=sys.stderr)
        o = waits.outcome(auth, r["id"], "the release was not allowed")
        if o.get("code"):
            fail(f"[builderbot] ERROR: {o.get('out') or 'it was not released'}")
        print(o.get("out") or "released")
        raise SystemExit(0)
    rel = r.get("released") or {}
    print(f"{rel.get('tag')} on {rel.get('sha')}" + (", pushed" if rel.get("pushed") else "")
          + (f"; {rel['note']}" if rel.get("note") else ""))
    forge = rel.get("forge") or {}
    if forge.get("url"):
        print(f"the release: {forge['url']}")
    elif forge.get("error"):
        print(f"no release on the forge: {forge['error']}")
    raise SystemExit(0)

if argv and argv[0] == "rehearse":
    # A release rehearsed (R190 step 2): the project's release-rehearsal
    # workflow started on this branch through the controller, which holds
    # the forge's token. It builds what a tag would and publishes nothing.
    import bbapi
    if any(x in ("-h", "--help") for x in argv[1:]):
        print("bb version rehearse   run every build a release's tag runs on this branch, as it is pushed,\n"
              "    publishing nothing (.github/workflows/release-rehearsal.yml); tag once it is green.\n"
              "    The run's summary lists the files the release would carry (.release-files).")
        raise SystemExit(0)
    if argv[1:]:
        fail(f"bb version rehearse takes nothing more, not {argv[1]}")
    wf = "release-rehearsal.yml"
    if not (version.root(proj) / ".github/workflows" / wf).is_file():
        fail(f"{proj} has no .github/workflows/{wf} to rehearse a release with")
    branch = version.branch_of(proj)
    if not branch:
        fail("HEAD is not on a branch: a rehearsal runs a pushed branch")
    here = version._git(proj, "rev-parse", "HEAD") or ""
    there = version._git(proj, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}") or ""
    if here.strip() != there.strip():
        fail(f"{branch} here is not what was last pushed: bb git push it first, since the rehearsal builds "
             "the remote's branch")
    r = bbapi.call("/api/forge", {"project": proj, "verb": "run dispatch",
                                  "args": {"pos": [wf], "flags": {"ref": branch}}},
                   auth=os.environ.get("BB_VERSION_AUTH", ""), timeout=120)
    if isinstance(r, dict) and r.get("error"):
        fail(f"[builderbot] ERROR: {r['error']}")
    print(f"the release rehearsal is started on {branch} at {here.strip()[:7]}: bb forge run list shows it, "
          "bb ci-log reads it, and its summary lists what a release from here would carry")
    raise SystemExit(0)

if argv and argv[0] == "line":
    # The release this branch works toward (R112): read, set, or `none` back
    # to what the branch's name says.
    if len(argv) > 1:
        r = version.set_line(proj, "" if argv[1].lower() == "none" else argv[1])
        if r.get("error"):
            fail(r["error"])
    b, ln = version.branch_of(proj), version.line(proj)
    tgt = (version.target(proj)[0] or "")
    print(f"{b or 'HEAD'}: " + (f"works toward {ln}, so a build here is {version.render(proj)['forms']['semver']}"
                               if ln else f"no line: builds take {tgt or 'no version'} from {version.VERSION_FILE}")
          + ("" if not ln else ("; its bump goes to " + ln)))
    raise SystemExit(0)

if argv and argv[0] == "forward":
    # A released patch line merged into this branch's later line (R112 step
    # 3): its fixes carried, this line's number kept, the changelog stitched.
    r = version.forward(proj, argv[1] if len(argv) > 1 else "")
    if r.get("error"):
        fail(r["error"])
    print(r.get("said") or "done")
    for c in r.get("carried", [])[:20]:
        print(f"  {c}")
    if r.get("commit"):
        print(f"committed {r['commit']}")
    raise SystemExit(0)

if argv and argv[0] == "backport":
    # A fix made on a later line carried back onto this patch line (R112
    # step 4), its changelog entries with it.
    r = version.backport(proj, argv[1] if len(argv) > 1 else "")
    if r.get("error"):
        fail(r["error"])
    print(r.get("said") or "done")
    if r.get("commit"):
        print(f"committed {r['commit']}")
    raise SystemExit(0)

if argv and argv[0] == "policy":
    # Read-only on purpose: a session should be able to see the limit it is
    # held to and never to move it.
    print(f"{proj}: {policy_line()}")
    print("a person changes this with Agents may: Move the version in the project's settings,"
          " or on its Artifacts view; bb version set X.Y.Z moves to a later version in one step")
    raise SystemExit(0)

if argv and argv[0] == "--list":
    # What this repo actually carries. One line for a normal project; more
    # only where somebody put a VERSION file in a subdirectory.
    rows = [("", version.render(proj))] + [
        (c, version.render(proj, c)) for c in version.components(proj)]
    for name, rv in rows:
        label = f"{proj}/{name}" if name else proj
        print(f"  {label:<28} {rv['forms']['semver'] or '(none)'}")
    if len(rows) == 1:
        print("\n  one version for the whole repo. A directory with its own "
              "VERSION\n  file becomes a component with its own; see "
              "`bb version --for DIR`.")
    raise SystemExit(0)

v = version.render(proj, comp)
forms = v["forms"]

if argv and argv[0] == "--json":
    print(json.dumps(v, indent=1))
    raise SystemExit(0)

# --win is an alias rather than its own form: a Windows VERSIONINFO resource
# and a Firefox manifest want the identical four-integer string, and shipping
# two names for one value is cheaper than making somebody work that out.
FLAGS = {"--semver": "semver", "--code": "code", "--quad": "quad",
         "--win": "quad", "--moz": "quad", "--msi": "msi",
         "--pep440": "pep440", "--file": "file"}
if argv:
    key = FLAGS.get(argv[0])
    if key is None:
        fail(USAGE)
    if v.get("error"):
        fail(v["error"])
    if forms[key] is None:
        fail(
             f"no {argv[0]} form here: {proj} has no VERSION file, and that "
             "format cannot be produced without one")
    print(forms[key])
    raise SystemExit(0)

# The human summary.
if v.get("error"):
    print(f"{proj}: {v['error']}")
if forms["semver"]:
    # Not "[released]" beside "+dirty": HEAD being tagged does not make an
    # uncommitted tree the release, and the two claims side by side read as a
    # contradiction because they are one.
    print(f"{proj}{'/' + comp if comp else ''} {forms['semver']}"
          + ("   [released]" if v["released"] and not v["dirty"] else ""))
else:
    print(f"{proj}: no version could be determined")
# "building towards" until the tag exists, and that is the whole distinction
# between the two gestures: a bump decides the number, the tag says it
# happened. Said in the summary, because a session reading this is exactly
# who needs to know which of the two has occurred.
print(("  released as       " if v["released"] else "  building towards  ") + (
    v["target"] or ("(VERSION is there but unreadable; see above)"
                    if v.get("error") else "(no VERSION file; add one to opt in)")))
if v["released"]:
    print(f"  tag               {v['tag']}  (on this commit)")
elif v["target"]:
    print("  not released yet  Release on the Artifacts view, or bb version release "
          "--why under Agents may: Tag and publish a release, tags this commit and "
          "pushes it")
if v["ordinal"] is not None:
    print(f"  ordinal           {v['ordinal']}")
if v["sha"]:
    print(f"  commit            {v['sha']}"
          + ("  (working tree dirty)" if v["dirty"] else ""))
    lands_line("  branch            ")

# What this container is running, but only where that is a comparison rather
# than a coincidence: BB_VERSION is the image's, and the image is built from
# THIS repo. Beside any other project's version it would be noise.
own = not comp and (version.root(proj) / "config/templates/briefing.md").is_file()
running = os.environ.get("BB_VERSION", "").strip()
if own and running:
    print(f"  running here      {running}")
    if forms["semver"] and running != forms["semver"]:
        print("                    differs from this checkout; the box serves"
              " whatever image it last pulled")

print(f"  who may bump      {policy_line()}")

comps = version.components(proj)
if comps and not comp:
    print(f"  components        {', '.join(comps)}"
          f"   (bb version --for {comps[0]})")
since = version.since_bump(proj, comp)
if since.get("commits"):
    print(f"  since that target {since['commits']} commit"
          + ("" if since["commits"] == 1 else "s"))
if v.get("warn"):
    print(f"  warning           {v['warn']}")

other = [(f, forms[k]) for f, k in (("--code", "code"), ("--quad/--win", "quad"),
                                    ("--msi", "msi"), ("--pep440", "pep440"),
                                    ("--file", "file")) if forms[k]]
if other:
    print()
    for flag, val in other:
        print(f"  {flag:<12} {val}")
