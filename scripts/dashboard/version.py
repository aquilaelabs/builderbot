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
import re
import subprocess
import threading
from pathlib import Path

WORKSPACE = None
STATE = None
FILE = None
write_json = None

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


def configure(*, workspace, state, write_json):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state),
                     write_json=write_json)
    globals()["FILE"] = Path(state) / "versions.json"


def root(project):
    return WORKSPACE / project


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


def target(project):
    """(MAJOR.MINOR.PATCH, error). Both None-able; error explains a refusal."""
    p = root(project) / VERSION_FILE
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None                      # simply not adopted here yet
    line = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if not TARGET_RE.match(line):
        return None, (f"{VERSION_FILE} should hold one line of "
                      f"MAJOR.MINOR.PATCH; it holds {line[:40]!r}")
    return line, None


def parts(project):
    """Everything the renderings are built from, plus why any of it is missing."""
    tgt, err = target(project)
    ordinal = _git(project, "rev-list", "--count", "HEAD")
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


def render(project):
    """Every form of this project's version, and the parts they came from.

    A form that cannot honestly be produced is None rather than a guess. The
    caller says so; inventing a manifest version for a project with no VERSION
    file would put a wrong number in a shipped artifact, which is the one
    outcome worth more than a missing field.
    """
    p = dict(parts(project))
    tgt, ordinal, sha = p["target"], p["ordinal"], p["sha"]
    forms = {"semver": None, "code": None, "quad": None, "msi": None,
             "pep440": None, "file": None}
    p["released"] = bool(p["tag"]) and tgt is not None and p["tag"].lstrip("v") == tgt
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
            forms.update(semver=tgt, pep440=tgt, file=tgt, msi=tgt,
                         quad=f"{tgt}.0")
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
            forms["pep440"] = f"{tgt}.dev{ordinal}+{sha}"
            # No '+' and no build metadata: this ends up in filenames and in
            # URLs, where '+' is a space to something eventually.
            forms["file"] = f"{tgt}-dev.{ordinal}-{sha}"
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


def bump(project, part, by="claude"):
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
    tgt, err = target(project)
    if err:
        return {"error": err}
    if tgt is None:
        return {"error": f"{project} has no {VERSION_FILE} file yet — create "
                         f"one holding a line like 0.1.0 first"}
    if _git(project, "rev-parse", "--short=7", "HEAD") is None:
        return {"error": "not a git repository, or no commits yet"}
    # A partial commit takes the worktree copy, so a VERSION already staged as
    # part of something else would be quietly swept into this commit under a
    # message about a version bump. Refuse and say so.
    staged = _git(project, "diff", "--cached", "--name-only") or ""
    if VERSION_FILE in staged.splitlines():
        return {"error": f"{VERSION_FILE} is already staged for another "
                         "commit — commit or unstage that first"}
    new = next_version(tgt, part)
    p = root(project) / VERSION_FILE
    try:
        p.write_text(new + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {VERSION_FILE}: {e}"}
    # Who moved it, in the message, because that is the only place the
    # distinction survives: the commit identity is the container's either way.
    msg = f"Set version to {new}" + ("" if by == "operator" else " (session)")
    out = _git(project, "commit", "-m", msg, "--", VERSION_FILE, timeout=30)
    if out is None:
        # The file is written but uncommitted. Say both halves — a caller told
        # only "commit failed" would not know the target had already moved.
        return {"error": f"{VERSION_FILE} now reads {new}, but committing it "
                         f"failed — commit it by hand", "target": new}
    return {"ok": True, "was": tgt, "target": new, "part": part,
            "commit": _git(project, "rev-parse", "--short=7", "HEAD") or ""}


def since_bump(project):
    """What has happened since the target last moved — the case for a bump.

    The git half only. The counts that make the decision easy — roadmap items
    done, bugs fixed — come from the notebook's own dated logs and are added
    by the caller that has them.
    """
    at = _git(project, "log", "-1", "--format=%ct", "--", VERSION_FILE)
    if not (at or "").isdigit():
        return {"at": None, "commits": None}
    last = _git(project, "log", "-1", "--format=%H", "--", VERSION_FILE)
    n = _git(project, "rev-list", "--count", f"{last}..HEAD") if last else None
    return {"at": int(at), "commits": int(n) if (n or "").isdigit() else None}
