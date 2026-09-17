#!/usr/bin/env python3
"""Which model and effort a project's Claude session runs on.

Per project, set at the bottom of that project's settings dialog. It began as
a pair of pickers inside every send box, became one standing preference on a
sidebar card, and is now per project — because the thing it governs is per
project. Each directory has one long-lived conversation, and which model suits
a Kotlin app is not which model suits a shell script.

**It is applied at launch, not typed into a running session.** bb-tty passes
`--model` and `--effort` when it starts claude. That matters for two reasons
the slash-command route could not manage:

  - `/model` now raises a confirmation, and there is no IPC into a session —
    only tmux send-keys — so the dashboard was typing the next line into a
    dialog. notify.py predicted exactly this: it refuses to recognise dialogs,
    because that means pattern-matching a TUI that changes every release.
  - a slash-command switch is saved as claude's default for NEW sessions too,
    so a per-send switch quietly changed global state. A launch flag is the
    process's own and leaks nowhere.

Empty means what "leave as is" meant: pass no flag, and claude uses its own
default. Changing it for a project with a session already running is the one
case that cannot wait for a launch, so the dialog says so and the session is
respawned onto the same transcript.
"""
import json
import threading
from pathlib import Path

write_json = None
FILE = None
# The canonical tables. todo.py and bugs.py carry copies for their own
# switching; a value stored here must satisfy theirs, so keep them equal.
MODELS = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# How much the operator wants to be in the loop on what a session ENTERS
# into each notebook tab (roadmap #27): auto lands it, ask holds it for
# approval, deny refuses it. Creation only — see pending.py. Kept here
# because it is a project setting, edited in the same dialog as the rest.
GATE_KINDS = ("roadmap", "bugs", "rules")
# The git policy's two questions, and what they read as when nothing is set:
# a session may push the branch it works on, and may not push to main.
GITPOL_KEYS = ("push", "main")
GITPOL_MODES = ("allow", "deny")
GITPOL_DEFAULT = {"push": "allow", "main": "deny"}
GATE_MODES = ("auto", "ask", "deny")
# ...and the same three words for whether a SESSION may rebuild this
# project's dev instance. One vocabulary: a person who has set a notebook
# tab to "ask me" knows what this one does without being told twice.
DEVBUILD_MODES = ("deny", "ask", "auto")
# A colour for the project, worn by its notebook tab and its row so that
# eight open notebooks can be told apart at a glance. Names, not hex: the
# page maps each to a tone that sits on its palette, and a name survives a
# theme change where a hex value picked against one background does not.
# "" is no colour, which is the default and leaves nothing on the file.
COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "violet", "pink")

_lock = threading.Lock()


def configure(*, write_json, state):
    globals().update(write_json=write_json)
    globals()["FILE"] = Path(state) / "claude-prefs.json"


# ---- what is the PERSON's rather than the project's ------------------------
#
# The operator's call (17 Sep): the model and the effort a session launches on
# are facts about whoever is at the keyboard, not about the directory. Two
# people on one project want different ones, and the old per-project pair made
# one of them change the other's sessions. The author a commit carries is the
# same kind of fact, and git_identity already says so for the account; this
# adds the per-project override, for somebody who commits to one repository
# under a different name or address.
#
# Kept here, keyed by uid, and NOT in users.json: that file holds password
# hashes and is not a session's to read, while this one is read by the
# launcher at exec time so a respawn picks up a change. Nothing here is a
# secret; a git author is on every commit by design.
USER_CHOICES = {"model": MODELS, "effort": EFFORTS}
USER_TEXT = {"git_name": 120, "git_email": 200}


def _clean_user(rec):
    """One person's settings on one project; unset and invalid read the same,
    for the reason _clean gives: a hand-edited typo means "leave as is"."""
    rec = rec if isinstance(rec, dict) else {}
    out = {k: (rec.get(k) if rec.get(k) in vals else "") for k, vals in USER_CHOICES.items()}
    out.update({k: str(rec.get(k) or "").strip()[:n] for k, n in USER_TEXT.items()})
    return out


def for_user(uid, project):
    """What this account chose on this project. Empty for anybody with no uid,
    which is a terminal opened before accounts existed."""
    if not uid:
        return _clean_user(None)
    d = _load()
    return _clean_user(((d.get("users") or {}).get(str(uid)) or {}).get(str(project)))


def all_for_user(uid):
    """{project: settings} for one account, in ONE read. project_list resolves
    a row per project on the poll and cannot afford a file read per row."""
    if not uid:
        return {}
    users = _load().get("users") or {}
    mine = users.get(str(uid)) or {}
    return {k: _clean_user(v) for k, v in mine.items()} if isinstance(mine, dict) else {}


def set_for_user(uid, project, patch):
    """Write one person's settings on one project; the cleaned record back.

    A field left out of the patch is left alone, and one set to "" is cleared,
    so the dialog can unset a model without unsetting an email beside it.
    """
    if not uid or not project:
        return _clean_user(None)
    patch = patch if isinstance(patch, dict) else {}
    with _lock:
        d = _load()
        users = d.setdefault("users", {})
        mine = users.setdefault(str(uid), {})
        cur = _clean_user(mine.get(str(project)))
        for k in list(USER_CHOICES) + list(USER_TEXT):
            if k in patch:
                cur[k] = patch[k]
        cur = _clean_user(cur)
        if any(cur.values()):
            mine[str(project)] = cur
        else:
            # Nothing set is no record, so the file does not grow a row per
            # person per project that says "default, default".
            mine.pop(str(project), None)
        if not mine:
            users.pop(str(uid), None)
        write_json(FILE, d)
        return cur


def forget_user_project(project):
    """Drop everybody's settings for a project that is gone."""
    with _lock:
        d = _load()
        users = d.get("users") or {}
        for uid in list(users):
            users[uid].pop(str(project), None)
            if not users[uid]:
                users.pop(uid, None)
        write_json(FILE, d)


def _load():
    """The whole file, in the per-project shape, tolerating the old one.

    Was a single global pair. It moved onto each project because the sessions
    it governs are per project: one long-lived conversation per directory, and
    which model is right for a Kotlin app is not which model is right for a
    shell script. The old global value is not thrown away — `migrate` puts it
    on every project that exists at the time, so nothing changes underfoot for
    an install that had one.
    """
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"projects": {}, "users": {}}
    if not isinstance(d, dict):
        return {"projects": {}, "users": {}}
    p = d.get("projects")
    u = d.get("users")
    return {"projects": p if isinstance(p, dict) else {},
            "users": u if isinstance(u, dict) else {}}


def _clean(rec):
    """One project's pair, with anything unrecognised read as "leave as is".

    Unset and invalid deliberately land in the same place: an entry
    hand-edited into nonsense should mean claude's own default, not an error
    every time a session starts.
    """
    rec = rec if isinstance(rec, dict) else {}
    return {
            # Which docker-host node this project's containers default to.
            # A node id, opaque here: prefs stores the choice, the pickers
            # resolve it, and "" means auto — the default docker node.
            # The project's node (docs/nodes.md §6, §13): where EVERYTHING
            # this project does on a node goes — its containers, builds,
            # tests, CI and emulation. One setting, by the operator's
            # decision (1 Sep): per-role pickers were more control than
            # anybody wanted. A node id, "" meaning none.
            "node": str(rec.get("node") or "")[:40],
            # What `bb build` / `bb test` run there, and the globs whose
            # matches come back into dist/.
            "build": str(rec.get("build") or "")[:500],
            "test": str(rec.get("test") or "")[:500],
            "outputs": [str(g)[:200] for g in (rec.get("outputs") or [])
                        if str(g)][:16] if isinstance(rec.get("outputs"), list) else [],
            # Anything unrecognised reads as auto, for the same reason an
            # unknown model reads as "leave as is": a hand-edited file must
            # not lock a session out of the notebook by typo.
            # What a session may do with git's network half (roadmap R36):
            # push its own branch, and push to main. Enforced where the
            # controller runs git — the relay — and read by a session with
            # bb git policy; a local commit or merge cannot be forbidden.
            "gitpol": {k: ((rec.get("gitpol") or {}).get(k)
                           if isinstance(rec.get("gitpol"), dict)
                           and (rec.get("gitpol") or {}).get(k) in GITPOL_MODES else GITPOL_DEFAULT[k])
                       for k in GITPOL_KEYS},
            "gate": {k: ((rec.get("gate") or {}).get(k)
                         if isinstance(rec.get("gate"), dict)
                         and (rec.get("gate") or {}).get(k) in GATE_MODES else "auto")
                     for k in GATE_KINDS},
            "color": rec.get("color") if rec.get("color") in COLORS else "",
            # Whether a SESSION may rebuild this project's dev instance,
            # and it is a real grant rather than a nicety: a rebuild runs the
            # project's own Dockerfile and brings the container up, on the
            # node's daemon. `deny` by default; `auto` for a project whose
            # whole loop is "change it, rebuild it, look at it"; `ask` puts
            # the reason in front of a person, who allows one rebuild.
            # Creating, removing and Up/Down are not on this dial at all —
            # those are docker-write, which a session never has.
            "devbuild": _devbuild(rec.get("devbuild")),
            # Whether a session's tests run ONLY inside the project's dev
            # instance (roadmap R48, step 3). Off, `bb test` runs there when
            # the instance is up and on the node otherwise; on, a down
            # instance is a refusal that names it, and nothing runs on the
            # node. Per project because only a project with a compose file
            # has a container to run in; global would break every other one.
            "devtest": bool(rec.get("devtest"))}


def _devbuild(v):
    """One of DEVBUILD_MODES; anything else reads as `deny`."""
    return v if v in DEVBUILD_MODES else "deny"


def get(project):
    return _clean(_load()["projects"].get(project))


# How a project of each shape runs its tests, in the order a tree is asked.
# The command is never WRITTEN anywhere: the record stays exactly what the
# operator typed, and this answers when that is empty — so `bb test` on a
# project nobody has configured runs the thing that project obviously runs,
# and the settings field shows it as the placeholder it would use.
#
# Tests only. "Run the tests" has one conventional answer per ecosystem;
# "build" does not — which target, which flavour, which of an Android
# project's four — so `bb build` still refuses and says so rather than
# guessing at somebody's release variant.
TEST_DEFAULTS = (
    # This repository's own harness, which is a shell script rather than a
    # runner anyone would guess at.
    ("scripts/dashboard/test/run.sh", "bash scripts/dashboard/test/run.sh"),
    ("gradlew", "./gradlew test"),
    ("Cargo.toml", "cargo test"),
    ("go.mod", "go test ./..."),
    ("pytest.ini", "pytest"),
    ("tox.ini", "pytest"),
)


def test_default(project, workspace=None):
    """The test command this project would obviously use, or ""."""
    return test_default_at(Path(workspace or "/workspace") / str(project or ""))


def test_default_at(root):
    """...for a directory, which is what a caller standing IN the tree has.

    Read from the tree each time rather than remembered: a repo that grows a
    test runner should start answering, and one that loses it should stop.
    Two entry points because the two callers know different things — the
    server knows the workspace and the project name, and bb knows the
    directory it is being run in and often not the workspace at all.
    """
    root = Path(root)
    try:
        if not root.is_dir():
            return ""
    except OSError:
        return ""
    for name, cmd in TEST_DEFAULTS:
        if (root / name).exists():
            return cmd
    # package.json, only when it actually declares a test script: the field
    # is optional and npm answers "no test specified" with an exit 1 for the
    # rest, which is a failing suite that never existed.
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        if isinstance(pkg, dict) and (pkg.get("scripts") or {}).get("test"):
            return "npm test"
    except (OSError, ValueError, AttributeError):
        pass
    # ...and a python project with tests but no runner config of its own.
    if (root / "pyproject.toml").is_file() and (root / "tests").is_dir():
        return "pytest"
    return ""


def all_projects(workspace=None):
    """Every project's pair, for the status payload. Cheap — one small file,
    no subprocess — which is what lets this ride the poll at all.

    With a workspace, each record also carries `test_default`: what `bb test`
    would run there with nothing set, so the settings field can offer it as
    what leaving the box empty means. A handful of `exists()` calls beside a
    snapshot that already runs git per project.
    """
    d = _load()["projects"]
    out = {}
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        rec = _clean(v)
        if workspace is not None:
            rec["test_default"] = test_default(k, workspace)
        out[k] = rec
    return out


def set_prefs(project, node=None, build=None, test=None,
              outputs=None, gate=None, gitpol=None,
              devbuild=None, devtest=None, color=None, workspace=None):
    """Change any of one project's settings; None leaves it, "" clears it."""
    if not project:
        return {"error": "no project"}
    with _lock:
        d = _load()
        cur = _clean(d["projects"].get(project))
        if color is not None:
            if color not in COLORS and color != "":
                return {"error": f"color is one of {', '.join(COLORS)}, or none: not {color}"}
            cur["color"] = color
        if node is not None:
            cur["node"] = str(node)[:40]
        if build is not None:
            cur["build"] = str(build)[:500].strip()
        if test is not None:
            cur["test"] = str(test)[:500].strip()
        if outputs is not None:
            got = outputs if isinstance(outputs, list) else str(outputs).split(",")
            cur["outputs"] = [str(g).strip()[:200] for g in got if str(g).strip()][:16]
        if gitpol is not None:
            if not isinstance(gitpol, dict):
                return {"error": "gitpol is {push|main: allow|deny}"}
            for k, v in gitpol.items():
                if k not in GITPOL_KEYS:
                    return {"error": f"not a git policy: {k} — one of {', '.join(GITPOL_KEYS)}"}
                if v not in GITPOL_MODES:
                    return {"error": f"{k}: allow or deny, not {v}"}
                cur["gitpol"][k] = v
        if gate is not None:
            if not isinstance(gate, dict):
                return {"error": "gate is {roadmap|bugs|rules: auto|ask|deny}"}
            for k, v in gate.items():
                if k not in GATE_KINDS:
                    return {"error": f"not a gate: {k} — one of {', '.join(GATE_KINDS)}"}
                if v not in GATE_MODES:
                    return {"error": f"{k}: one of {', '.join(GATE_MODES)}, not {v}"}
                cur["gate"][k] = v
        if devbuild is not None:
            mode = devbuild
            if mode not in DEVBUILD_MODES:
                return {"error": f"devbuild is one of {', '.join(DEVBUILD_MODES)}, "
                                 f"not {devbuild}"}
            cur["devbuild"] = mode
        if devtest is not None:
            cur["devtest"] = devtest in (True, 1, "1", "true", "on", "yes")
        # An empty pair is removed rather than stored: the file then says only
        # what somebody chose, and a project left alone leaves no trace to read
        # past when its directory is renamed or deleted.
        if (cur["node"] or cur["color"]
                or cur["build"] or cur["test"] or cur["outputs"]
                or any(v != "auto" for v in cur["gate"].values())
                or cur["devbuild"] != "deny" or cur["devtest"]
                or cur["gitpol"] != GITPOL_DEFAULT):
            # Stored without the all-auto gate or the default policy, so the
            # file says only what somebody chose — _clean puts the defaults
            # back on the way out.
            rec = dict(cur)
            if all(v == "auto" for v in cur["gate"].values()):
                rec.pop("gate", None)
            if cur["gitpol"] == GITPOL_DEFAULT:
                rec.pop("gitpol", None)
            if cur["devbuild"] == "deny":
                rec.pop("devbuild", None)
            if not cur["devtest"]:
                rec.pop("devtest", None)
            d["projects"][project] = rec
        else:
            d["projects"].pop(project, None)
        write_json(FILE, d)
    # Into the repo's own config at once, so the next commit from any session
    # in it wears the name. Repo-local rather than global: two projects may be
    # two people's, and the tree is what a session's git reads.
    return {"ok": True, "project": project} | cur


def forget(project):
    """Drop a project's pair — for a project being deleted."""
    with _lock:
        d = _load()
        if d["projects"].pop(project, None) is not None:
            write_json(FILE, d)


