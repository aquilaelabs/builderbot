#!/usr/bin/env python3
"""One version identity per project, rendered for whatever is asking.

**Why this is not one string.** The obvious design — pick a version, write it
everywhere — cannot be built. An Android `versionCode` must be a monotonically
increasing integer; a Firefox `manifest.json` version must be dot-separated
digits; npm wants semver; Python wants PEP 440. Those formats genuinely
disagree, so a scheme insisting on one literal string breaks on the first real
artifact.

So there is **one input and several renderings**. The input is three parts:

  target   the VERSION file at the project root — MAJOR.MINOR.PATCH, one line,
           hand-edited. The only part a person ever decides, and a statement
           about where the project is going rather than where it has been.
  ordinal  `git rev-list --count HEAD` — the ordering a sha cannot give. Two
           bugs stamped abc1234 and def5678 do not say which came first, which
           is exactly what "first spotted in" has to answer.
  sha      the short commit — exact identity, no order.

**Why rev-list --count and not `git describe`'s count.** They look
interchangeable and are not. `git describe` counts commits *since the last
tag*, so that number RESETS to zero every time a tag is cut. Feed it to
Android's versionCode and the first build after a release is rejected: Play
requires the code to be strictly greater than the last one uploaded, forever.
rev-list counts every commit reachable from HEAD, never resets, and works
before the first tag exists — which matters here, where there are none yet.
Not a CI run number either: rev-list is reproducible from any checkout, works
offline, and survives a workflow being renamed.

Two honest limits on the ordinal, written here so nobody later mistakes it for
a globally unique id. It counts commits reachable from HEAD, so a branch and
main can produce the same number — fine, because only main builds publish a
code. And it only rises while history does: a squash or a force-push that
drops commits from main lowers it, which for an app already on Play is
unrecoverable. Do not rewrite the trunk of a project that ships an APK.

**A tag on HEAD drops the -dev suffix.** `0.4.0-dev.390` sorts before `0.4.0`
under semver, which is the correct relationship between heading for something
and arriving, and it comes free rather than needing a rule.

**A project with no VERSION file still answers**, falling back to
`git describe --tags --always --dirty` and saying so. Every project can be
asked; one that has not opted in should degrade, not fail.

**A repo can ship two products, and then one number is a lie.** An APK and a
browser extension in one tree do not share a maturity: the extension can be at
2.1 while the app is new at 0.3, and bumping minor for an app feature would
silently move the extension's user-visible version for whoever installed it.

So a *component* is any directory holding its own VERSION file — discovered,
not configured, the same deal `dist/` is. The root VERSION is the project's
and is what an unqualified `bb version` answers, unchanged. A component
answers for itself.

Only the target splits. The sha is the repo's either way, and the ordinal
becomes the count of commits that touched THAT directory: still strictly
increasing, so versionCode and AMO stay satisfied, but an untouched product's
version stops moving every time its neighbour is edited. That churn is the
whole reason to split them — a shipped extension should not appear to change
because somebody edited the app.

**Who may move it.** A per-project policy, because most of the coding here
happens through prompts and by bump time nobody remembers what three weeks
contained. `locked` (the default) keeps it entirely with the operator; `patch`,
`minor` and `open` delegate progressively more. Enforced here rather than
requested in a prompt — the point of the setting is not relying on the model's
judgment. It stops `bb version bump` and the file tools; it does not stop
Bash, the same honest limit the sibling-project deny list has. What actually
makes a bad bump recoverable is that VERSION is committed: every move is in
`git log` with a date and a message saying who made it.
"""
import json
import os
import re
import subprocess
import threading
from pathlib import Path

WORKSPACE = None
STATE = None
FILE = None
write_json = None
# Injected rather than imported, the way notebook.py takes them: the CLI loads
# these modules by path, and importing them again here would make a second
# copy with its own configuration and its own idea of where the state lives.
todo = None
bugs = None

# The file a project declares its target in. One line, at the repo root.
VERSION_FILE = "VERSION"

# MAJOR.MINOR.PATCH and nothing else. Deliberately strict: the value of the
# file is that everything downstream can assume the shape, so "0.4" or
# "v0.4.0" should fail once here where it can be reported, rather than push
# the guessing into five renderers.
TARGET_RE = re.compile(r"^(\d{1,6})\.(\d{1,6})\.(\d{1,6})$")

# What a session may move, weakest to strongest. The default is the strongest
# because a version is a claim about the project: the operator should opt into
# delegating it rather than out.
POLICIES = ("locked", "patch", "minor", "open")
_ALLOWS = {"locked": (), "patch": ("patch",),
           "minor": ("patch", "minor"), "open": ("patch", "minor", "major")}

PARTS = ("major", "minor", "patch")

_lock = threading.Lock()


def configure(*, workspace, state, write_json, todo_mod=None, bugs_mod=None):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state),
                     write_json=write_json, todo=todo_mod, bugs=bugs_mod)
    globals()["FILE"] = Path(state) / "versions.json"


def root(project):
    return WORKSPACE / project


# How deep to look for a component. One level below the root, the same reach
# artifacts.py allows inside dist/: enough for app/ and extension/ side by
# side, not enough to invite a vendored tree's own VERSION file to show up as
# a product this project ships.
COMPONENT_DEPTH = 1

# Never descend into these looking for a component. dist/ holds outputs, not
# sources, and the rest are other people's trees.
_SKIP = {"node_modules", "vendor", "dist", "build", "target", ".git",
         "__pycache__", "venv", ".venv"}


def components(project):
    """Directories under the project that carry their own VERSION file.

    Empty for the overwhelming majority of projects, which ship one thing and
    want one number. A component exists because somebody put a file there.
    """
    base = root(project)
    out = []
    stack = [(base, 0)]
    while stack:
        d, depth = stack.pop()
        if depth > COMPONENT_DEPTH:
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_dir() or p.name.startswith(".") or p.name in _SKIP:
                continue
            if (p / VERSION_FILE).is_file():
                out.append(str(p.relative_to(base)))
            if depth < COMPONENT_DEPTH:
                stack.append((p, depth + 1))
    return sorted(out)


def _git(project, *args, timeout=10):
    """One git command in the project, or None if it failed.

    None rather than an exception on purpose: every caller here is asking a
    question that has a reasonable "cannot tell" answer — no repo, no commits,
    no tags — and none of them should turn that into a stack trace.
    """
    try:
        r = subprocess.run(["git", "-C", str(root(project)), *args],
                           capture_output=True, text=True,
                           timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _sub(project, comp):
    """The directory a version question is about — the root, or a component.

    Resolved and prefix-checked rather than joined: `comp` can arrive from a
    browser, and `../..` must not turn this into a reader of arbitrary VERSION
    files on the box.
    """
    base = root(project).resolve()
    if not comp:
        return base
    try:
        d = (root(project) / comp).resolve(strict=True)
    except OSError:
        return None
    if not str(d).startswith(str(base) + "/") or not d.is_dir():
        return None
    return d


def target(project, comp=""):
    """(MAJOR.MINOR.PATCH, error). Both None-able; error explains a refusal."""
    d = _sub(project, comp)
    if d is None:
        return None, f"no such component here: {comp}"
    p = d / VERSION_FILE
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None                      # simply not adopted here yet
    line = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if not TARGET_RE.match(line):
        return None, (f"{VERSION_FILE} should hold one line of "
                      f"MAJOR.MINOR.PATCH; it holds {line[:40]!r}")
    return line, None


def parts(project, comp=""):
    """Everything the renderings are built from, plus why any of it is missing."""
    tgt, err = target(project, comp)
    # A component counts only the commits that touched it. Still monotonic —
    # commits accumulate, they do not un-happen — so versionCode and AMO are
    # as satisfied as before; but the extension stops appearing to change
    # every time the app beside it is edited.
    ordinal = _git(project, "rev-list", "--count", "HEAD",
                   *(["--", comp] if comp else []))
    sha = _git(project, "rev-parse", "--short=7", "HEAD")
    if sha is None:
        return {"target": tgt, "error": err or "not a git repository, or no commits yet",
                "ordinal": None, "sha": None, "tag": "", "dirty": False,
                "describe": None}
    # --exact-match so this is "is HEAD *itself* released", not "what was the
    # last release" — the whole question the -dev suffix turns on.
    tag = _git(project, "describe", "--tags", "--exact-match", "HEAD") or ""
    dirty = bool(_git(project, "status", "--porcelain"))
    return {"target": tgt, "error": err,
            "ordinal": int(ordinal) if (ordinal or "").isdigit() else None,
            "sha": sha, "tag": tag, "dirty": dirty,
            "describe": _git(project, "describe", "--tags", "--always", "--dirty")}


def render(project, comp=""):
    """Every form of this project's version, and the parts they came from.

    A form that cannot honestly be produced is None rather than a guess. The
    caller says so; inventing a manifest version for a project with no VERSION
    file would put a wrong number in a shipped artifact, which is the one
    outcome worth more than a missing field.
    """
    p = dict(parts(project, comp))
    p["component"] = comp
    tgt, ordinal, sha = p["target"], p["ordinal"], p["sha"]
    forms = {"semver": None, "code": None, "quad": None, "msi": None,
             "pep440": None, "file": None}
    p["released"] = bool(p["tag"]) and tgt is not None and p["tag"].removeprefix("v") == tgt
    # The ordinal is the one form that needs no VERSION file: it is pure git,
    # and it is the one Android cannot ship without.
    if ordinal is not None:
        forms["code"] = str(ordinal)
    if tgt and ordinal is not None and sha:
        if p["released"]:
            # On the tag itself: the target IS the version, in every form.
            # On a release the ordinal drops out of every form. MSI's
            # three fields are exactly major.minor.patch, so the target is
            # already the right string; the quad pads the unused fourth.
            # A dirty tree on the tag is NOT the release, and the two forms
            # that can say so do. The digit-only forms cannot carry a mark;
            # anything built from them here is mislabeled, which the summary's
            # dirty flag is the only warning for.
            mark = "dirty" if p["dirty"] else ""
            forms.update(semver=tgt + (f"+{mark}" if mark else ""),
                         pep440=tgt + (f"+{mark}" if mark else ""),
                         file=tgt + (f"-{mark}" if mark else ""),
                         msi=tgt, quad=f"{tgt}.0")
        else:
            mark = ".dirty" if p["dirty"] else ""
            a3, b3, _c3 = tgt.split(".")
            forms["semver"] = f"{tgt}-dev.{ordinal}+{sha}{mark}"
            # Four dot-separated numbers, and one string that happens to be
            # correct in two unrelated ecosystems. Firefox: safely inside both
            # the toolkit version format and AMO's stricter one, which rejects
            # the semver form outright — if this is ever submitted to AMO
            # rather than self-distributed, run it past their validator first.
            # Windows: exactly the shape a VERSIONINFO resource wants, four
            # integers for FileVersion/ProductVersion, and the same four a
            # .NET assembly version takes.
            forms["quad"] = f"{tgt}.{ordinal}"
            # MSI is the exception that earns its own form. Windows Installer
            # IGNORES the fourth field when deciding whether a package is an
            # upgrade, so two builds differing only in the ordinal are the
            # same version to it and the upgrade silently does not fire. Three
            # fields, with the ordinal promoted into the one that is read.
            forms["msi"] = f"{a3}.{b3}.{ordinal}"
            forms["pep440"] = f"{tgt}.dev{ordinal}+{sha}{mark}"
            # No '+' and no build metadata: this ends up in filenames and in
            # URLs, where '+' is a space to something eventually. The dirty
            # mark stays — an artifact built from uncommitted work must not
            # wear the name of a build the sha can reproduce.
            forms["file"] = f"{tgt}-dev.{ordinal}-{sha}" + ("-dirty" if p["dirty"] else "")
    elif p["describe"]:
        # No VERSION file. Say what git says, in the one field that can hold
        # an arbitrary string, and leave the format-constrained ones empty.
        forms["semver"] = forms["file"] = p["describe"]
    # Every field of the Windows forms is a 16-bit integer, and MSI's first
    # two are 8-bit. The target is hand-written and small; the ordinal is the
    # one that grows on its own, so it is the one worth watching. Reported
    # rather than clamped — a silently truncated version number is how two
    # different builds end up claiming to be the same one.
    if ordinal is not None and ordinal > 65535:
        p["warn"] = (f"the ordinal is {ordinal}, past the 65535 a Windows "
                     "version field holds — --quad and --msi are unsafe here")
    p["forms"] = forms
    return p


# --------------------------------------------------------------------------
# Who may move it

def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("projects"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"projects": {}}


def policy(project):
    p = load()["projects"].get(project) or {}
    v = p.get("policy")
    return v if v in POLICIES else "locked"


def set_policy(project, value):
    """The operator's call only — there is no CLI verb that reaches this."""
    if value not in POLICIES:
        return {"error": f"policy must be one of {', '.join(POLICIES)}"}
    with _lock:
        d = load()
        d["projects"].setdefault(project, {})["policy"] = value
        write_json(FILE, d)
    return {"ok": True, "policy": value}


def allows(pol):
    """Which parts a policy delegates — for display; may() is the gate."""
    return _ALLOWS.get(pol, ())


def may(project, part, by="claude"):
    """Whether `by` may move `part` here — the reason, or None if allowed."""
    if part not in PARTS:
        return f"part must be one of {', '.join(PARTS)}"
    if by == "operator":
        return None
    pol = policy(project)
    if part in _ALLOWS[pol]:
        return None
    if pol == "locked":
        return (f"{project}'s version is locked to the operator. They can "
                f"change that on the project's Artifacts tab.")
    return (f"{project}'s policy is '{pol}', so a session may move "
            f"{' or '.join(_ALLOWS[pol]) or 'nothing'} but not {part}.")


def next_version(tgt, part):
    a, b, c = (int(x) for x in tgt.split("."))
    if part == "major":
        return f"{a + 1}.0.0"
    if part == "minor":
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


def init(project, value, by="claude", comp=""):
    """Give a project — or a component — its first VERSION, and commit it.

    This exists because the guardrail would otherwise be a dead end: the file
    tools are denied on VERSION, so nothing a session or the panel can do
    would create the first one, and the tab was left telling the operator to
    make a file by hand in a terminal. A rule with no sanctioned path is a
    rule people route around.

    `locked` refuses this the way it refuses a bump. Under any delegating
    policy a session may create one: if the operator has handed over some of
    the moving, handing over the starting point is the same decision, and a
    new project with no version at all is the case worth unblocking.
    """
    if by != "operator" and policy(project) == "locked":
        return {"error": f"{project}'s version is locked to the operator. They "
                         f"can give it one on the project's Artifacts tab."}
    value = str(value or "").strip()
    if not TARGET_RE.match(value):
        return {"error": f"a version is MAJOR.MINOR.PATCH, like 0.1.0 — "
                         f"not {value[:40]!r}"}
    where = _sub(project, comp)
    if where is None:
        return {"error": f"no such directory here: {comp}"}
    p = where / VERSION_FILE
    if p.exists():
        # Not an error worth dressing up: the thing being asked for is already
        # true, and changing it is what bump is.
        return {"error": f"{comp + '/' if comp else ''}{VERSION_FILE} already "
                         f"exists — use a bump to change it"}
    if _git(project, "rev-parse", "--short=7", "HEAD") is None:
        return {"error": "not a git repository, or no commits yet — a version "
                         "needs history to count"}
    try:
        p.write_text(value + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {VERSION_FILE}: {e}"}
    rel = str(p.relative_to(root(project).resolve()))
    msg = (f"Add {comp} VERSION at {value}" if comp
           else f"Add VERSION at {value}") + ("" if by == "operator" else " (session)")
    _git(project, "add", "--", rel)
    if _git(project, "commit", "-m", msg, "--", rel, timeout=30) is None:
        return {"error": f"{rel} now reads {value}, but committing it failed — "
                         f"commit it by hand", "target": value}
    return {"ok": True, "target": value, "component": comp,
            "commit": _git(project, "rev-parse", "--short=7", "HEAD") or ""}


def candidates(project):
    """Directories that could become a component — one level down, no VERSION.

    Offered so that creating the second product's version is a choice from
    what is actually there rather than a path typed from memory.
    """
    base = root(project)
    out = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.is_dir() or p.name.startswith(".") or p.name in _SKIP:
            continue
        if not (p / VERSION_FILE).is_file():
            out.append(p.name)
    return out


def bump(project, part, by="claude", comp=""):
    """Move the target and commit that one file.

    Committing rather than leaving the tree dirty is the whole reason this is
    a function and not a text field. An uncommitted VERSION rides along in
    whatever a session commits next, which is how a version bump ends up
    inside a commit about something else and stops being findable. One path,
    one generated message, never pushed.
    """
    why = may(project, part, by)
    if why:
        return {"error": why}
    tgt, err = target(project, comp)
    if err:
        return {"error": err}
    if tgt is None:
        return {"error": f"{project} has no {VERSION_FILE} file yet — create "
                         f"one holding a line like 0.1.0 first"}
    where = _sub(project, comp)
    if where is None:
        return {"error": f"no such component here: {comp}"}
    # Every git path below is relative to the repo root, not the component.
    rel = str((where / VERSION_FILE).relative_to(root(project).resolve()))
    if _git(project, "rev-parse", "--short=7", "HEAD") is None:
        return {"error": "not a git repository, or no commits yet"}
    # A partial commit takes the worktree copy, so a VERSION already staged as
    # part of something else would be quietly swept into this commit under a
    # message about a version bump. Refuse and say so.
    staged = _git(project, "diff", "--cached", "--name-only") or ""
    if rel in staged.splitlines():
        return {"error": f"{VERSION_FILE} is already staged for another "
                         "commit — commit or unstage that first"}
    # And the unstaged twin, which is worse: a hand edit sitting in the
    # worktree would be absorbed into this commit, so the log would say
    # "(session)" over a change the operator made. The log being trustworthy
    # about who moved the version is the design's whole safety story.
    unstaged = _git(project, "diff", "--name-only", "--", rel) or ""
    if unstaged.strip():
        return {"error": f"{VERSION_FILE} has uncommitted changes — commit "
                         "or discard those first, so this bump's commit "
                         "records only its own move"}
    new = next_version(tgt, part)
    p = where / VERSION_FILE
    try:
        p.write_text(new + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {VERSION_FILE}: {e}"}
    # Who moved it, in the message, because that is the only place the
    # distinction survives: the commit identity is the container's either way.
    msg = (f"Set {comp} version to {new}" if comp
           else f"Set version to {new}") + ("" if by == "operator" else " (session)")
    # `git commit -- path` only knows tracked paths, so a VERSION that has
    # never been committed — created by hand five minutes ago — needs the add.
    # For a tracked file this is a no-op as far as the partial commit cares.
    _git(project, "add", "--", rel)
    out = _git(project, "commit", "-m", msg, "--", rel, timeout=30)
    if out is None:
        # The file is written but uncommitted. Say both halves — a caller told
        # only "commit failed" would not know the target had already moved.
        return {"error": f"{VERSION_FILE} now reads {new}, but committing it "
                         f"failed — commit it by hand", "target": new}
    return {"ok": True, "was": tgt, "target": new, "part": part, "component": comp,
            "commit": _git(project, "rev-parse", "--short=7", "HEAD") or ""}


def evidence(project, comp=""):
    """What has happened since the target last moved — the case for a bump.

    This is the reason the controls are worth building rather than just a
    number being displayed. Most of the coding here happens through prompts,
    so by bump time nobody remembers what the last three weeks contained; the
    notebook's own dated logs do, and they are the only place that knows. Two
    roadmap items finished reads as a minor, four bug fixes and nothing else
    reads as a patch, and that is a two-second judgment instead of scrolling
    git log trying to reconstruct it.

    Counts only, and deliberately no suggested verdict — the same principle
    the emulator benchmarking item settled on. Evidence the operator reads
    beats a recommendation this side cannot justify.
    """
    e = dict(since_bump(project, comp))
    at = e.get("at")
    e["done"] = e["fixed"] = None
    if at is None:
        # No commit has ever touched VERSION, so there is no window to count
        # over. None rather than 0: "nothing happened" and "there is nothing
        # to measure from" are different answers.
        return e
    if todo is not None:
        e["done"] = sum(1 for x in todo.history(project, since=at)
                        if x.get("act") == "done")
    if bugs is not None:
        e["fixed"] = sum(1 for x in bugs.history(project, since=at)
                         if x.get("act") == "fixed")
    return e


def payload(project):
    """Everything the Artifacts tab head needs, in one read.

    `versions` is the project's own first, then one per component. Almost
    always a list of one — a component exists only because somebody put a
    VERSION file in a directory.
    """
    out = one(project)
    out["versions"] = [one(project, c) for c in components(project)]
    return out


def one(project, comp=""):
    """One version block: the project's, or a component's."""
    v = render(project, comp)
    pol = policy(project)
    return {
        "component": comp,
        "project": project, "target": v["target"], "forms": v["forms"],
        "ordinal": v["ordinal"], "sha": v["sha"], "dirty": v["dirty"],
        "released": v["released"], "tag": v["tag"],
        "error": v.get("error"), "warn": v.get("warn"),
        "policy": pol, "policies": list(POLICIES), "allows": list(allows(pol)),
        # What the container is running, which is only a comparison for the
        # project the image is built from. Any other project's tab would be
        # showing it an unrelated number.
        # Only the project's own line compares against the image: BB_VERSION
        # is built from the repo, not from one directory inside it.
        "running": None if comp else _running_here(project),
        "next": {part: (next_version(v["target"], part) if v["target"] else None)
                 for part in PARTS},
        "since": evidence(project, comp),
        # Only on the project's own block: a component is added from the one
        # place that lists what could become one.
        "candidates": [] if comp else candidates(project),
    }


def _running_here(project):
    if not (root(project) / "config/templates/project-CLAUDE.md").is_file():
        return None
    return os.environ.get("BB_VERSION", "").strip() or None


def since_bump(project, comp=""):
    """What has happened since the target last moved — the case for a bump.

    The git half only. The counts that make the decision easy — roadmap items
    done, bugs fixed — come from the notebook's own dated logs and are added
    by the caller that has them.
    """
    where = _sub(project, comp)
    if where is None:
        return {"at": None, "commits": None}
    rel = str((where / VERSION_FILE).relative_to(root(project).resolve()))
    at = _git(project, "log", "-1", "--format=%ct", "--", rel)
    if not (at or "").isdigit():
        return {"at": None, "commits": None}
    last = _git(project, "log", "-1", "--format=%H", "--", rel)
    # Narrowed to the component too: "what has happened here since" should not
    # count the app's commits when the question is about the extension.
    n = _git(project, "rev-list", "--count", f"{last}..HEAD",
             *(["--", comp] if comp else [])) if last else None
    return {"at": int(at), "commits": int(n) if (n or "").isdigit() else None}
