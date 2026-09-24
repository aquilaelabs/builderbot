#!/usr/bin/env python3
"""One version identity per project, rendered for whatever is asking.

**Why this is not one string.** The obvious design (pick a version, write it
everywhere) cannot be built. An Android `versionCode` must be a monotonically
increasing integer; a Firefox `manifest.json` version must be dot-separated
digits; npm wants semver; Python wants PEP 440. Those formats genuinely
disagree, so a scheme insisting on one literal string breaks on the first real
artifact.

So there is **one input and several renderings**. The input is three parts:

  target   the VERSION file at the project root: MAJOR.MINOR.PATCH, one line,
           hand-edited. The only part a person ever decides, and a statement
           about where the project is going rather than where it has been.
  ordinal  `git rev-list --count HEAD`, the ordering a sha cannot give. Two
           bugs stamped abc1234 and def5678 do not say which came first, which
           is exactly what "first spotted in" has to answer.
  sha      the short commit: exact identity, no order.

**Why rev-list --count and not `git describe`'s count.** They look
interchangeable and are not. `git describe` counts commits *since the last
tag*, so that number RESETS to zero every time a tag is cut. Feed it to
Android's versionCode and the first build after a release is rejected: Play
requires the code to be strictly greater than the last one uploaded, forever.
rev-list counts every commit reachable from HEAD, never resets, and works
before the first tag exists, which matters here, where there are none yet.
Not a CI run number either: rev-list is reproducible from any checkout, works
offline, and survives a workflow being renamed.

Two honest limits on the ordinal, written here so nobody later mistakes it for
a globally unique id. It counts commits reachable from HEAD, so a branch and
main can produce the same number. That is fine, because only main builds
publish a code. And it only rises while history does: a squash or a force-push
that drops commits from main lowers it, which for an app already on Play is
unrecoverable. Do not rewrite the trunk of a project that ships an APK.
And adopting this scheme in a CLONED repo that already published elsewhere
needs one check first: Play requires the next versionCode to exceed the last
one ever uploaded, and this repo's commit count bears no relation to codes a
previous maintainer picked by hand. Compare `bb version --code` against the
app's last published code before shipping: if it is not higher, the store
will refuse the build, and nothing here can know that.

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

So a *component* is any directory holding its own VERSION file: discovered,
not configured, the same deal `dist/` is. The root VERSION is the project's
and is what an unqualified `bb version` answers, unchanged. A component
answers for itself.

Only the target splits. The sha is the repo's either way, and the ordinal
becomes the count of commits that touched THAT directory: still strictly
increasing, so versionCode and AMO stay satisfied, but an untouched product's
version stops moving every time its neighbour is edited. That churn is the
whole reason to split them: a shipped extension should not appear to change
because somebody edited the app.

**Who may move it.** A per-project policy, because most of the coding here
happens through prompts and by bump time nobody remembers what three weeks
contained. `locked` (the default) keeps it entirely with the operator; `patch`,
`minor` and `open` delegate progressively more. Enforced here rather than
requested in a prompt, because the point of the setting is not relying on the
model's judgment. It stops `bb version bump` and the file tools; it does not
stop Bash, the same honest limit the sibling-project deny list has. What
actually makes a bad bump recoverable is that VERSION is committed: every move
is in `git log` with a date and a message saying who made it.
"""
import os as _os
import sys as _sys
# Beside this file, whichever way it was loaded: bb's own Python loads the
# modules by path, where a plain sibling import finds nothing.
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from names import claude_session   # noqa: E402
import json
import os
import re
import subprocess
import sys

# `bb` execs this module by path, so its directory is not on sys.path the way
# it is when the dashboard imports it. One module object per process either
# way: the in-process half of the lock is a dict in there.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402
import time
from pathlib import Path

WORKSPACE = None
STATE = None
FILE = None
write_json = None
# Injected rather than imported, the way notebook.py takes them: the CLI loads
# these modules by path, and importing them again here would make a second
# copy with its own configuration and its own idea of where the state lives.
roadmap = None
bugs = None
changelog = None
tell = None
tmux_name = None

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
# `start` is the one that delegates nothing and still unblocks something:
# a project with NO version can be given its first one by a session, and
# every move after that stays the operator's. Creating a version and moving
# one are different decisions (the first has no claim to overwrite), and
# without this the only way to let a session write the first VERSION was to
# hand it the bumping as well.
POLICIES = ("locked", "start", "patch", "minor", "open")
_ALLOWS = {"locked": (), "start": (), "patch": ("patch",),
           "minor": ("patch", "minor"), "open": ("patch", "minor", "major")}
# Which policies let a session create the FIRST version. Not derived from
# _ALLOWS: `start` delegates no part and is exactly this permission.
_MAY_INIT = ("start", "patch", "minor", "open")

PARTS = ("major", "minor", "patch")

# The same lock the roadmap and the tracker take, and for the same reason: the
# dashboard is one process and a `bb` invocation is another, and a threading
# lock guards the threads of one. Both would load, both mutate their own copy,
# both write, and os.replace makes each write atomic while doing nothing about
# the second landing on top of the first. See statefile.py.
_lock = statefile.on(lambda: FILE)


def configure(*, workspace, state, write_json, roadmap_mod=None, bugs_mod=None,
              changelog_mod=None, tell_fn=None, tmux_name_fn=None):
    globals().update(WORKSPACE=Path(workspace), STATE=Path(state),
                     write_json=write_json, roadmap=roadmap_mod, bugs=bugs_mod,
                     changelog=changelog_mod, tell=tell_fn,
                     tmux_name=tmux_name_fn)
    globals()["FILE"] = Path(state) / "versions.json"


def root(project):
    return WORKSPACE / project


# Never treat these as a component. dist/ holds outputs, not sources, and
# the rest are other people's trees.
_SKIP = {"node_modules", "vendor", "dist", "build", "target", ".git",
         "__pycache__", "venv", ".venv", "gradle", "test", "tests", "docs"}


def components(project):
    """Directories one level under the project that carry their own VERSION.

    Exactly one level, and the same one candidates() offers and init()
    accepts: three functions with three different ideas of where a component
    may live is how a VERSION file ends up created somewhere the tab never
    finds. One level also keeps a vendored tree's own VERSION two levels down
    from showing up as a product this project ships.

    Empty for the overwhelming majority of projects, which ship one thing and
    want one number. A component exists because somebody put a file there.
    """
    base = root(project)
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    return sorted(p.name for p in entries
                  if p.is_dir() and not p.name.startswith(".")
                  and p.name not in _SKIP
                  and (p / VERSION_FILE).is_file())


def _git(project, *args, timeout=10, env=None):
    """One git command in the project, or None if it failed.

    None rather than an exception on purpose: every caller here is asking a
    question that has a reasonable "cannot tell" answer (no repo, no commits,
    no tags), and none of them should turn that into a stack trace.

    `env` is what a commit carries over the process's own: the account's
    git identity (users.git_env), so an operator's bump is theirs and not
    whatever the repository or the box happens to have configured.
    """
    # GIT_OPTIONAL_LOCKS=0: a status here is a read, and the index lock it
    # would otherwise take can make a session's git in the same tree fail
    # with index.lock: File exists (B155). A commit still takes the locks it
    # needs; only the optional one is skipped.
    try:
        r = subprocess.run(["git", "-C", str(root(project)), *args],
                           capture_output=True, text=True,
                           timeout=timeout, check=False,
                           env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", **(env or {})})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _sub(project, comp):
    """The directory a version question is about: the root, or a component.

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


def _relspec(project, where):
    """The pathspec git is asked about, from the RESOLVED directory.

    Never the caller's raw spelling: `--for ./extension`, a trailing slash, or
    a symlinked alias all resolve to the same directory but name different
    pathspecs, and rev-list against the raw string counts the wrong commits
    or none. The file being read and the history being counted have to be the
    same place.
    """
    try:
        return str(where.relative_to(root(project).resolve()))
    except (AttributeError, ValueError):
        return None


def _repo(project):
    """The repo-wide facts, gathered once. None where there is no repo.

    Everything here is identical for the project and every component (only the
    target and the ordinal are per-directory), so callers rendering several
    blocks pass this in rather than paying four subprocesses per block for the
    same four answers.
    """
    sha = _git(project, "rev-parse", "--short=7", "HEAD")
    if sha is None:
        return None
    return {"sha": sha,
            "dirty": bool(_git(project, "status", "--porcelain")),
            "describe": _git(project, "describe", "--tags", "--always", "--dirty"),
            # Every tag on HEAD, not describe --exact-match's single pick:
            # release detection has to ask "is THIS thing's tag here", and a
            # component's answer is a differently named tag than the root's.
            "tags": (_git(project, "tag", "--points-at", "HEAD") or "").splitlines()}


def parts(project, comp="", repo=None):
    """Everything the renderings are built from, plus why any of it is missing."""
    tgt, err = target(project, comp)
    repo = _repo(project) if repo is None else repo
    if repo is None:
        return {"target": tgt, "error": err or "not a git repository (Init on the Git view makes one), or no commits yet",
                "ordinal": None, "sha": None, "tag": "", "dirty": False,
                "describe": None, "released": False}
    where = _sub(project, comp)
    rel = _relspec(project, where) if comp else None
    # A component counts only the commits that touched it. Still monotonic,
    # because commits accumulate and do not un-happen, so versionCode and AMO
    # are as satisfied as before; but the extension stops appearing to change
    # every time the app beside it is edited.
    ordinal = None
    if not comp or rel:
        ordinal = _git(project, "rev-list", "--count", "HEAD",
                       *(["--", rel] if rel else []))
    # Released means a tag for THIS thing is on HEAD. The root's is vX.Y.Z;
    # a component's is <dir>-vX.Y.Z, because the repo-wide tag says nothing
    # about the component: a project release that happens to share the
    # extension's number must not stamp a mid-cycle extension build as its
    # release.
    if tgt is None:
        tag = ""
    elif comp:
        want = f"{comp}-v{tgt}"
        tag = want if want in repo["tags"] else ""
    else:
        tag = next((t for t in repo["tags"]
                    if t.removeprefix("v") == tgt), "")
    return {"target": tgt, "error": err,
            "ordinal": int(ordinal) if (ordinal or "").isdigit() else None,
            "sha": repo["sha"], "tag": tag, "dirty": repo["dirty"],
            "describe": repo["describe"], "released": bool(tag)}


def render(project, comp="", repo=None):
    """Every form of this project's version, and the parts they came from.

    A form that cannot honestly be produced is None rather than a guess. The
    caller says so; inventing a manifest version for a project with no VERSION
    file would put a wrong number in a shipped artifact, which is the one
    outcome worth more than a missing field.
    """
    p = dict(parts(project, comp, repo=repo))
    p["component"] = comp
    tgt, ordinal, sha = p["target"], p["ordinal"], p["sha"]
    forms = {"semver": None, "code": None, "quad": None, "msi": None,
             "pep440": None, "file": None}
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
            # the semver form outright. If this is ever submitted to AMO
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
            # mark stays, because an artifact built from uncommitted work must
            # not wear the name of a build the sha can reproduce.
            forms["file"] = f"{tgt}-dev.{ordinal}-{sha}" + ("-dirty" if p["dirty"] else "")
    elif p["describe"]:
        # No VERSION file. Say what git says, in the one field that can hold
        # an arbitrary string, and leave the format-constrained ones empty.
        forms["semver"] = forms["file"] = p["describe"]
    # Every field of the Windows forms is a 16-bit integer, and MSI's first
    # two are 8-bit. The target is hand-written and small; the ordinal is the
    # one that grows on its own, so it is the one worth watching. Reported
    # rather than clamped: a silently truncated version number is how two
    # different builds end up claiming to be the same one.
    if ordinal is not None and ordinal > 65535:
        p["warn"] = (f"the ordinal is {ordinal}, past the 65535 a Windows "
                     "version field holds, so --quad and --msi are unsafe here")
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
    """The operator's call only: there is no CLI verb that reaches this."""
    if value not in POLICIES:
        return {"error": f"policy must be one of {', '.join(POLICIES)}"}
    with _lock:
        d = load()
        d["projects"].setdefault(project, {})["policy"] = value
        write_json(FILE, d)
    return {"ok": True, "policy": value}


def allows(pol):
    """Which parts a policy delegates, for display; may() is the gate."""
    return _ALLOWS.get(pol, ())


def may(project, part, by="claude"):
    """Whether `by` may move `part` here: the reason, or None if allowed."""
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
    if pol == "start":
        return (f"{project}'s policy is 'start': a session may give it its first "
                f"version and no more. Moving it is the operator's, on the "
                f"project's Artifacts tab.")
    return (f"{project}'s policy is '{pol}', so a session may move "
            f"{' or '.join(_ALLOWS[pol]) or 'nothing'} but not {part}.")


def _ships_from(project):
    """The remote branch a build of this project actually comes from, or "".

    `origin/HEAD` when the remote published one, else origin/main, else
    origin/master. REMOTE rather than local, and that is the whole point: the
    question is which commit an image is built from, and the answer is
    whatever the remote's default branch points at, not whatever this
    checkout happens to be standing on.
    """
    ref = _git(project, "symbolic-ref", "--short", "-q",
               "refs/remotes/origin/HEAD")
    if ref:
        return ref
    for cand in ("origin/main", "origin/master"):
        if _git(project, "rev-parse", "--verify", "--quiet",
                f"refs/remotes/{cand}") is not None:
            return cand
    return ""


def release(project, comp="", env=None, may_push=True, push=True):
    """Cut the release: an annotated tag on this commit, pushed.

    THE TWO GESTURES, and why there are two. A bump moves the number and
    closes the changelog under it, in one commit: that is deciding what this
    release IS. Tagging says it HAPPENED, and until the tag exists every
    build reads `X.Y.Z-dev.<ordinal>+<sha>`, which sorts before X.Y.Z,
    because heading for something is not arriving. From the tag on, a build
    of that commit renders as the bare number.

    So this does not move VERSION and does not write the changelog: both
    were settled by the bump. It marks the commit and publishes the mark.

    The tag's name is the same one `parts()` looks for, `vX.Y.Z`, and
    `<dir>-vX.Y.Z` for a component; otherwise `released` would stay false on
    a tag this very function made.

    Never `--force`, and no way to move or delete a tag from here: a
    published tag is somebody else's checkout, and taking one back is a
    thing to do deliberately in a terminal, having thought about it.
    """
    tgt, err = target(project, comp)
    if err:
        return {"error": err}
    if tgt is None:
        thing = f"{project}/{comp}" if comp else project
        return {"error": f"{thing} has no version to release yet; give it one first"}
    where = _sub(project, comp)
    if where is None:
        return {"error": f"no such component here: {comp}"}
    sha = _git(project, "rev-parse", "--short=7", "HEAD")
    if sha is None:
        return {"error": "not a git repository (Init on the Git view makes one), or no commits yet"}
    name = f"{comp}-v{tgt}" if comp else f"v{tgt}"
    if _git(project, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}") is not None:
        # Which commit it is on, because "it already exists" and "it is on
        # the commit you are looking at" are different situations and only
        # one of them is a problem.
        on = _git(project, "rev-list", "-n", "1", "--abbrev-commit", name) or "?"
        here = "this commit" if on and sha.startswith(on) or on.startswith(sha) else on
        return {"error": f"{name} already exists, on {here}. A published tag is not "
                         f"moved from here: bump to the next number, or move it "
                         f"yourself in a terminal if it was never pushed."}
    # A dirty tree is not what the tag would mark: the tag names a commit,
    # and the files beside it are not in it.
    if (_git(project, "status", "--porcelain") or "").strip():
        return {"error": "there are uncommitted changes: commit or discard them "
                         "first, so the tag marks what is actually in the commit"}
    # The commit that SHIPS is not always the commit you are standing on.
    #
    # Work lands through a pull request, so what CI builds and the box runs is
    # the merge commit on the default branch, while this checkout stays on the
    # branch that was merged. Tagging here names a commit no image was ever
    # built from, and leaves the build that did ship reading `-dev` forever.
    # Measured on 0.5.0 (B94): HEAD was the branch tip, origin/main was the
    # merge of it, and the running image was built from the merge.
    #
    # Refused only when HEAD is strictly BEHIND that branch, which is exactly
    # that case. Ahead of it, or off it entirely, is a deliberate situation
    # and not this function's to second-guess. A project with no remote, or no
    # default branch on it, is not checked at all.
    ships = _ships_from(project)
    if ships:
        # Fetched first, or the tracking ref is whatever this checkout last
        # heard and the guard quietly fails to fire, which is the bug again.
        # A release is the moment to be current about it; a fetch that cannot
        # run leaves the old answer rather than stopping the release. Short,
        # because a remote that is slow or gone must cost a moment and not a
        # hang: this is a guard, and the release is still the point.
        _git(project, "fetch", "--quiet", "origin", timeout=20, env=env)
        tip = _git(project, "rev-parse", "--short=7", ships)
        if (tip and tip != sha
                and _git(project, "merge-base", "--is-ancestor",
                         "HEAD", ships) is not None):
            branch = ships.split("/", 1)[-1]
            return {"error": f"this tree is on {sha}, and {ships} has moved past "
                             f"it to {tip}. A build comes from {branch}, so a tag "
                             f"here would name a commit nothing was ever built "
                             f"from. Check out {branch} and pull, then release."}
    msg = f"{comp} {tgt}" if comp else f"{project} {tgt}"
    if _git(project, "tag", "-a", name, "-m", msg, env=env) is None:
        return {"error": f"could not create the tag {name}"}
    out = {"ok": True, "tag": name, "sha": sha, "target": tgt, "pushed": False}
    if not push:
        return out
    if not may_push:
        # The tag is made either way: a project with no push rights still
        # gets its marker, and the sentence says what is missing rather than
        # undoing the half that worked.
        out["note"] = (f"{name} is on this commit here. This project has no push "
                       f"rights, so nothing was sent to GitHub.")
        return out
    r = _git(project, "push", "origin", f"refs/tags/{name}", timeout=120, env=env)
    if r is None:
        out["note"] = (f"{name} is on this commit here, but the push failed; run "
                       f"`git push origin {name}` when the remote is reachable.")
        return out
    out["pushed"] = True
    return out


def next_version(tgt, part):
    a, b, c = (int(x) for x in tgt.split("."))
    if part == "major":
        return f"{a + 1}.0.0"
    if part == "minor":
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


def _cl_guard(project, where):
    """Refuse, before anything is mutated, a roll that would sweep a staged
    changelog edit.

    The bump commit takes the changelog's worktree state along with VERSION,
    which is right for unreleased entry lines (dating them is what a bump
    means for them), but an edit the operator staged for a commit of their
    own (a typo fix in a dated section, say) would be silently absorbed into
    "Set version to X" and vanish from their pending commit. Same sweep, same
    refusal, as the VERSION guards beside it. Checked only when a roll would
    actually happen: with nothing unreleased the commit never touches the
    file, and a staged edit is none of this function's business.
    """
    if changelog is None or where is None or not changelog.unreleased(where):
        return None
    rel = str((where / changelog.FILE).relative_to(root(project).resolve()))
    staged = (_git(project, "diff", "--cached", "--name-only") or "").splitlines()
    if rel in staged:
        return (f"{rel} is staged for another commit, and this would sweep "
                "that edit into the version commit: commit or unstage it first")
    return None


# The one hook a repository gets on its own version, and the reason it
# exists: a project may carry the same number somewhere else, and a bump that
# moves one and not the other commits a lie.
#
# BuilderBot is the case. Its minor IS the compatibility window, stamped again
# in the agent's AGENT_VERSION and in the CLAUDE.md template's WINDOW line, and
# 0.5.0 only came out consistent because a person moved both by hand before
# pressing Bump (B91). A test holds the three equal, but only after the
# commit, and only if somebody runs it.
#
# Generic on purpose: this module serves every project and must not know what
# an agent is. A repo declares its own stamps by carrying an executable
# `tools/version-stamp`, run from the repo root with the new version and the
# part that moved. Whatever it changes is committed with VERSION, so the bump
# stays one commit. A repo without one is unaffected.
STAMP_HOOK = "tools/version-stamp"


def _stamp(project, value, part, env=None):
    """Run the repo's own stamp hook. ([paths it changed], "") or ([], why)."""
    r = root(project)
    hook = r / STAMP_HOOK
    if not (hook.is_file() and os.access(hook, os.X_OK)):
        return [], ""
    # status, not diff: a stamp may CREATE a file, and an untracked one is
    # invisible to `git diff`. That is how the first version of this committed
    # VERSION alone while the hook's own output sat in the worktree.
    def touched():
        out = _git(project, "status", "--porcelain", "--untracked-files=all") or ""
        got = set()
        for line in out.splitlines():
            if len(line) > 3:
                got.add(line[3:].split(" -> ")[-1].strip().strip('"'))
        return got

    before = touched()
    try:
        p = subprocess.run([str(hook), value, part], cwd=str(r),
                           capture_output=True, text=True, timeout=60,
                           check=False,
                           env={**os.environ, **env} if env else None)
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"{STAMP_HOOK} could not be run, so nothing was moved: {e}"
    if p.returncode != 0:
        return [], (f"{STAMP_HOOK} failed, so nothing was moved: "
                    + ((p.stdout or "") + (p.stderr or "")).strip()[-300:])
    return sorted(touched() - before), ""


def _seal(project, where, ver_rel, value, msg, env=None, extra=()):
    """Roll the changelog, stage, and commit: the tail init and bump share.

    Every failure names what actually happened to BOTH files, because by this
    point the worktree is already mutated: an error that mentions only
    VERSION leaves a silently dated changelog for somebody to find later. A
    changelog that cannot be staged (gitignored, most likely) does not take
    the whole commit down with it: VERSION still commits, and the note says
    what was left behind.
    """
    cl_rel = None
    note = ""
    if changelog is not None and changelog.roll(
            where, value, time.strftime("%Y-%m-%d")):
        cl_rel = str((where / changelog.FILE)
                     .relative_to(root(project).resolve()))
    if _git(project, "add", "--", ver_rel) is None:
        return {"error": f"could not stage {ver_rel}. Is it gitignored? It "
                         f"now reads {value}"
                         + (f", and {cl_rel} is dated for it" if cl_rel else ""),
                "target": value}
    paths = [ver_rel]
    # Whatever the repo's own stamp hook moved, in the same commit: the point
    # of the hook is that these numbers travel together.
    for x in extra:
        if _git(project, "add", "--", x) is None:
            note = (note + "; " if note else "") + f"{x} was changed by {STAMP_HOOK} but could not be staged"
        else:
            paths.append(x)
    if cl_rel is not None:
        if _git(project, "add", "--", cl_rel) is None:
            note = (f"{cl_rel} was dated for {value} but could not be staged "
                    "(gitignored?), so it is not in the commit")
        else:
            paths.append(cl_rel)
    if _git(project, "commit", "-m", msg, "--", *paths, timeout=30, env=env) is None:
        return {"error": f"{ver_rel} now reads {value}"
                         + (f" and {cl_rel} is dated for it" if cl_rel else "")
                         + ", but committing failed; commit by hand",
                "target": value}
    return {"ok": True, "target": value,
            "commit": _git(project, "rev-parse", "--short=7", "HEAD") or "",
            **({"note": note} if note else {})}


def init(project, value, by="claude", comp="", env=None):
    """Give a project, or a component, its first VERSION, and commit it.

    This exists because the guardrail would otherwise be a dead end: the file
    tools are denied on VERSION, so nothing a session or the panel can do
    would create the first one, and the tab was left telling the operator to
    make a file by hand in a terminal. A rule with no sanctioned path is a
    rule people route around.

    `locked` refuses this the way it refuses a bump. `start` allows it and
    nothing else, which is the whole reason that policy exists; the
    delegating policies allow it too, because handing over the moving and
    withholding the starting point would be a strange place to draw a line.
    """
    if by != "operator" and policy(project) not in _MAY_INIT:
        return {"error": f"{project}'s version is locked to the operator. They can "
                         f"give it one on the project's Artifacts tab, or set Claude "
                         f"access there to 'may start one'."}
    value = str(value or "").strip()
    if not TARGET_RE.match(value):
        return {"error": f"a version is MAJOR.MINOR.PATCH, like 0.1.0, "
                         f"not {value[:40]!r}"}
    where = _sub(project, comp)
    if where is None:
        return {"error": f"no such directory here: {comp}"}
    rel_dir = _relspec(project, where) if comp else ""
    if comp and (("/" in (rel_dir or "")) or where.name in _SKIP):
        # One level, matching where components() looks and candidates()
        # offers: a VERSION created deeper would sit orphaned: real on disk,
        # invisible on the tab, unrollable from anywhere.
        return {"error": "a component lives one level under the project, and "
                         f"{rel_dir or comp} is somewhere the tab would never "
                         "show"}
    p = where / VERSION_FILE
    if p.exists():
        # Not an error worth dressing up: the thing being asked for is already
        # true, and changing it is what bump is.
        return {"error": f"{comp + '/' if comp else ''}{VERSION_FILE} already "
                         f"exists; use a bump to change it"}
    if _git(project, "rev-parse", "--short=7", "HEAD") is None:
        return {"error": "not a git repository, or no commits yet: a version "
                         "needs history to count"}
    why = _cl_guard(project, where)
    if why:
        return {"error": why}
    try:
        p.write_text(value + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {VERSION_FILE}: {e}"}
    rel = str(p.relative_to(root(project).resolve()))
    msg = (f"Add {comp} VERSION at {value}" if comp
           else f"Add VERSION at {value}") + ("" if by == "operator" else " (session)")
    # Entries logged before the project had a version describe the work that
    # BECAME this first version, so _seal dates them as its section. Left
    # unreleased they would ride into the NEXT bump and be labeled as changes
    # since a release they are actually part of.
    r = _seal(project, where, rel, value, msg, env=env)
    if r.get("ok"):
        r["component"] = comp
    return r


def candidates(project):
    """Directories that could become a component: one level down, no VERSION.

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


def bump(project, part, by="claude", comp="", env=None):
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
        # Naming the component when there is one: telling somebody the
        # PROJECT has no VERSION while bumping the extension blames a file
        # that exists, and "create one" points at the exact hand-written
        # path the file-tool deny list closes. init is the sanctioned door.
        thing = f"{project}/{comp}" if comp else project
        forflag = f" --for {comp}" if comp else ""
        return {"error": f"{thing} has no {VERSION_FILE} yet; give it one "
                         f"with `bb version init 0.1.0{forflag}`, or from "
                         "the Artifacts tab"}
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
                         "commit; commit or unstage that first"}
    # And the unstaged twin, which is worse: a hand edit sitting in the
    # worktree would be absorbed into this commit, so the log would say
    # "(session)" over a change the operator made. The log being trustworthy
    # about who moved the version is the design's whole safety story.
    unstaged = _git(project, "diff", "--name-only", "--", rel) or ""
    if unstaged.strip():
        return {"error": f"{VERSION_FILE} has uncommitted changes: commit "
                         "or discard those first, so this bump's commit "
                         "records only its own move"}
    why = _cl_guard(project, where)
    if why:
        return {"error": why}
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
    # _seal dates the changelog's Unreleased section as this version and
    # commits it with VERSION: the bump is the date break, and splitting the
    # two across commits would let one land without the other. Uncommitted
    # ENTRY lines are swept in deliberately (dating them is what a bump means
    # for them); a STAGED edit was refused above, before anything moved.
    # The repo's own stamps, before the commit is made: a hook that fails
    # stops the bump rather than leaving a number moved and its twin behind.
    # Only for the project itself: a component's version is its own and does
    # not carry the repository's promises.
    extra = []
    if not comp:
        extra, why = _stamp(project, new, part, env=env)
        if why:
            try:
                p.write_text(tgt + "\n", encoding="utf-8")
            except OSError:
                pass
            return {"error": why}
    r = _seal(project, where, rel, new, msg, env=env, extra=extra)
    if r.get("ok"):
        r.update(was=tgt, part=part, component=comp, stamped=extra)
    return r


def evidence(project, comp=""):
    """What has happened since the target last moved: the case for a bump.

    This is the reason the controls are worth building rather than just a
    number being displayed. Most of the coding here happens through prompts,
    so by bump time nobody remembers what the last three weeks contained; the
    notebook's own dated logs do, and they are the only place that knows. Two
    roadmap items finished reads as a minor, four bug fixes and nothing else
    reads as a patch, and that is a two-second judgment instead of scrolling
    git log trying to reconstruct it.

    Counts only, and deliberately no suggested verdict, on the same principle
    the emulator benchmarking item settled on. Evidence the operator reads
    beats a recommendation this side cannot justify.
    """
    e = dict(since_bump(project, comp))
    at = e.get("at")
    e["done"] = e["fixed"] = None
    if comp:
        # The notebook's logs are per project, with no way to say which
        # product a done item or a fixed bug belonged to, so for a component
        # they would present the sibling's work as this one's case for a
        # bump, the exact mislabeling the split exists to prevent. The commit
        # count above is honestly narrowed; these two are omitted rather than
        # wrong.
        return e
    if at is None:
        # No commit has ever touched VERSION, so there is no window to count
        # over. None rather than 0: "nothing happened" and "there is nothing
        # to measure from" are different answers.
        return e
    if roadmap is not None:
        e["done"] = sum(1 for x in roadmap.history(project, since=at)
                        if x.get("act") == "done")
    if bugs is not None:
        e["fixed"] = sum(1 for x in bugs.history(project, since=at)
                         if x.get("act") == "fixed")
    return e


def payload(project):
    """Everything the Artifacts tab head needs, in one read.

    The project's own block is the top level; `versions` holds ONLY the
    components' blocks, almost always none, because a component exists only if
    somebody put a VERSION file in a directory. The repo-wide git facts are
    gathered once and shared: they are identical for every block, and a tab
    fetch should not pay four subprocesses per component for the same four
    answers.
    """
    repo = _repo(project)
    out = one(project, repo=repo)
    out["versions"] = [one(project, c, repo=repo) for c in components(project)]
    return out


def one(project, comp="", repo=None):
    """One version block: the project's, or a component's."""
    v = render(project, comp, repo=repo)
    pol = policy(project)
    d = _sub(project, comp)
    # One read serves both changelog fields. `has_changelog` is False both
    # when there is no file and when the directory itself failed to resolve.
    # The tab treats the two the same, and a component that vanished mid-read
    # already surfaces through its render error.
    text = changelog.read(d) if (changelog is not None and d) else None
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
        # The changelog beside this VERSION: how many entries wait for a
        # bump to date them, and whether the file exists at all.
        "unreleased": len(changelog.unreleased_text(text)) if text is not None else 0,
        "has_changelog": text is not None,
        # For the undo control: where an unbump would land, and whether the
        # current number is already a release somewhere in history. HEAD's
        # tags say "is this build the release", this says "was this NUMBER
        # ever released", and only the second makes it immutable.
        "prev": prev_target(project, comp) if v["target"] else None,
        "sealed": (_release_tag_exists(project, v["target"], comp)
                   if v["target"] else False),
    }


def _running_here(project):
    if not (root(project) / "config/templates/briefing.md").is_file():
        return None
    return os.environ.get("BB_VERSION", "").strip() or None


def prev_target(project, comp=""):
    """What VERSION held before its last change: the value an unbump returns
    to. None where there is nothing earlier: the file's first commit."""
    where = _sub(project, comp)
    if where is None:
        return None
    rel = str((where / VERSION_FILE).relative_to(root(project).resolve()))
    last = _git(project, "log", "-1", "--format=%H", "--", rel)
    if not last:
        return None
    old = (_git(project, "show", f"{last}~1:{rel}") or "").strip()
    return old if TARGET_RE.match(old) else None


def _release_tag_exists(project, tgt, comp=""):
    """Whether this version was ever tagged as a release, anywhere in
    history, not just on HEAD. Released numbers are immutable."""
    want = f"{comp}-v{tgt}" if comp else f"v{tgt}"
    tags = (_git(project, "tag", "-l", want) or "").strip()
    if tags:
        return True
    # The root convention tolerates an unprefixed tag too.
    return bool(not comp and (_git(project, "tag", "-l", tgt) or "").strip())


def unbump(project, by="claude", comp="", env=None):
    """Take the target back to its previous value; the code stays.

    For a bump somebody thought better of: nothing about the tree reverts,
    the number returns to what it was, and the changelog section the bump
    dated dissolves back into Unreleased alongside anything logged since, so
    the next bump dates the whole group together as one release.

    Only while unreleased. A version that has a release tag is a number
    somebody may have installed, and installed numbers are immutable. The
    answer there is to bump forward, not to reuse.
    """
    tgt, err = target(project, comp)
    if err:
        return {"error": err}
    if tgt is None:
        return {"error": "no VERSION here to take back"}
    prev = prev_target(project, comp)
    if prev is None:
        return {"error": f"{tgt} is this {'component' if comp else 'project'}'s "
                         "first version, and there is nothing earlier to return to"}
    if tuple(map(int, prev.split("."))) >= tuple(map(int, tgt.split("."))):
        # The last change was itself a return (or a hand edit downward), and
        # "undoing" it would move the target UP while claiming to take it
        # back. An unbump only ever goes down; forward is what bump is for.
        return {"error": f"the last change here already returned the version "
                         f"(from {prev}); bump forward when it is ready again"}
    # The policy question is the same one the bump asked: undoing a minor
    # moves the minor, and a session allowed to move it forward is allowed to
    # move it back.
    part = next((n for n, a, b in zip(PARTS, tgt.split("."), prev.split("."), strict=False)
                 if a != b), "patch")
    why = may(project, part, by)
    if why:
        return {"error": why}
    if _release_tag_exists(project, tgt, comp):
        return {"error": f"{tgt} is released: a tagged number may be on "
                         "somebody's device, so it cannot be reused. Bump "
                         "forward instead."}
    where = _sub(project, comp)
    rel = str((where / VERSION_FILE).relative_to(root(project).resolve()))
    staged = (_git(project, "diff", "--cached", "--name-only") or "").splitlines()
    if rel in staged:
        return {"error": f"{VERSION_FILE} is already staged for another "
                         "commit; commit or unstage that first"}
    if (_git(project, "diff", "--name-only", "--", rel) or "").strip():
        return {"error": f"{VERSION_FILE} has uncommitted changes: commit "
                         "or discard those first"}
    cl_rel = None
    if changelog is not None:
        cl_rel = str((where / changelog.FILE)
                     .relative_to(root(project).resolve()))
        if cl_rel in staged:
            return {"error": f"{cl_rel} is staged for another commit, and "
                             "dissolving the section would sweep that edit; "
                             "commit or unstage it first"}
    try:
        (where / VERSION_FILE).write_text(prev + "\n", encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {VERSION_FILE}: {e}"}
    paths = [rel]
    if changelog is not None and changelog.unroll(where, tgt):
        _git(project, "add", "--", cl_rel)
        paths.append(cl_rel)
    # The repo's own stamps come BACK with the number, or taking a bump back
    # leaves the compatibility window where the bump put it: a controller
    # returned to 0.5.0 still promising 0.6 to every node and every briefing.
    # The hook is given the version being returned TO, and its own rules
    # apply: BuilderBot's moves the window down and the agent's build up,
    # since a build that went backwards could not say which agent is newer.
    if not comp:
        extra, why = _stamp(project, prev, part, env=env)
        if why:
            try:
                (where / VERSION_FILE).write_text(tgt + "\n", encoding="utf-8")
            except OSError:
                pass
            return {"error": why}
        for x in extra:
            if _git(project, "add", "--", x) is not None:
                paths.append(x)
    _git(project, "add", "--", rel)
    msg = (f"Return the {comp + ' ' if comp else ''}version to {prev}"
           + ("" if by == "operator" else " (session)"))
    if _git(project, "commit", "-m", msg, "--", *paths, timeout=30, env=env) is None:
        return {"error": f"{rel} now reads {prev}, but committing failed; "
                         "commit by hand", "target": prev}
    return {"ok": True, "was": tgt, "target": prev, "component": comp,
            "commit": _git(project, "rev-parse", "--short=7", "HEAD") or ""}


def ask(project, sessions=(), comp=""):
    """Put the version question to the project's own Claude session.

    There used to be a `bb version suggest` beside this: commit count, does
    dist/ hold anything, how the roadmap's done-to-open ratio reads. It was
    removed rather than kept as an input, and the reason is worth recording:
    a mechanical number does not merely fail to help, it ANCHORS. Handing a
    session "0.2.0, from 21 commits" invites it to justify that number
    instead of reading the code and forming a view. The judgment is the whole
    product here, and half a judgment arriving first is worse than none.

    So the prompt asks the question and points at the protocol, and the
    session does the reading.

    Deliberately proposes rather than acts. The prompt says what the policy
    here allows, and tells the session to wait for a clear yes either way.
    Negotiating the number is the point of asking a session instead of a
    function, and a session that set it on arrival would have skipped the
    conversation the operator came for.
    """
    if tell is None or tmux_name is None:
        return {"error": "no way to reach a session from here"}
    where = _sub(project, comp)
    if where is None:
        return {"error": f"no such component here: {comp}"}
    tgt, _err = target(project, comp)
    what = f"the `{comp}` component of {project}" if comp else project
    # Short on purpose. This is TYPED into a terminal a character at a time,
    # and the echo has to be seen before Enter can follow: the first cut ran
    # to 704 characters, which a TUI does not finish rendering inside the
    # window notify.tell waits, so it was left sitting in the input box
    # unsent. It used to point at the version section of the project's
    # CLAUDE.md; that block went with R63 step 3, so it points at the verb
    # that answers the same question wherever it is run.
    line = (f"From the operator, on the Artifacts tab: what version should "
            f"{what} start at? Read the code and `bb version policy`, then "
            f"propose a number you derived here and ask; do not apply one.")
    if tgt:
        # A different question once a version exists: not "what should this
        # start at" but "is {tgt} still where this is", the judgment the
        # operator says is hard precisely because most of the work here
        # happened through prompts. The session can read what actually landed.
        line = (f"From the operator, on the Artifacts tab: {what} is at "
                f"{tgt}: is that still right? Read what has landed since, "
                f"then propose and ask; do not apply.")
    # No switch ahead of it: a project's model and effort are launch flags now,
    # so the session this reaches is already running on them.
    session = claude_session(project)
    r = tell(session, line, sessions)
    if r.get("error"):
        return r
    return {"ok": True, "sent": bool(r.get("sent")), "session": session,
            "text": line}


def since_bump(project, comp=""):
    """What has happened since the target last moved: the case for a bump.

    The git half only. The counts that make the decision easy, roadmap items
    done and bugs fixed, come from the notebook's own dated logs and are added
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
    # count the app's commits when the question is about the extension. The
    # RESOLVED spec, for the same reason parts() uses it: the raw spelling
    # can name a different pathspec than the file just read.
    spec = _relspec(project, where) if comp else None
    n = _git(project, "rev-list", "--count", f"{last}..HEAD",
             *(["--", spec] if spec else [])) if last else None
    return {"at": int(at), "commits": int(n) if (n or "").isdigit() else None}
