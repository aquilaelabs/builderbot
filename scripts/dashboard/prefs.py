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
# How much a session may change in this project without asking first. The
# names are Claude Code's own permission modes, which is what the launcher
# puts in the settings file: `default` asks before every edit, `accept`
# lets the file tools write inside the project and still asks for
# everything else — a shell command, a push, anything outside the tree.
# The deny list is not affected either way: a sibling project, VERSION and
# the rules file stay refused whatever this says.
EDIT_MODES = ("ask", "accept")

_lock = threading.Lock()


def configure(*, write_json, state):
    globals().update(write_json=write_json)
    globals()["FILE"] = Path(state) / "claude-prefs.json"


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
        return {"projects": {}}
    if not isinstance(d, dict):
        return {"projects": {}}
    p = d.get("projects")
    return {"projects": p if isinstance(p, dict) else {}}


def _clean(rec):
    """One project's pair, with anything unrecognised read as "leave as is".

    Unset and invalid deliberately land in the same place: an entry
    hand-edited into nonsense should mean claude's own default, not an error
    every time a session starts.
    """
    rec = rec if isinstance(rec, dict) else {}
    return {"model": rec.get("model") if rec.get("model") in MODELS else "",
            "effort": rec.get("effort") if rec.get("effort") in EFFORTS else "",
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
            # Ask by default: a project nobody has decided about behaves the
            # way Claude Code does out of the box.
            "edits": (rec.get("edits") if rec.get("edits") in EDIT_MODES else "ask")}


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


def set_prefs(project, model=None, effort=None, node=None, build=None, test=None,
              outputs=None, gate=None, gitpol=None,
              edits=None, workspace=None):
    """Change any of one project's settings; None leaves it, "" clears it."""
    if not project:
        return {"error": "no project"}
    with _lock:
        d = _load()
        cur = _clean(d["projects"].get(project))
        if model is not None:
            if model not in MODELS and model != "":
                return {"error": f"not a model this can set: {model}"}
            cur["model"] = model
        if effort is not None:
            if effort not in EFFORTS and effort != "":
                return {"error": f"not an effort this can set: {effort}"}
            cur["effort"] = effort
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
        if edits is not None:
            if edits not in EDIT_MODES:
                return {"error": f"edits is one of {', '.join(EDIT_MODES)}, not {edits}"}
            cur["edits"] = edits
        # An empty pair is removed rather than stored: the file then says only
        # what somebody chose, and a project left alone leaves no trace to read
        # past when its directory is renamed or deleted.
        if (cur["model"] or cur["effort"] or cur["node"]
                or cur["build"] or cur["test"] or cur["outputs"]
                or any(v != "auto" for v in cur["gate"].values())
                or cur["edits"] != "ask"
                or cur["gitpol"] != GITPOL_DEFAULT):
            # Stored without the all-auto gate or the default policy, so the
            # file says only what somebody chose — _clean puts the defaults
            # back on the way out.
            rec = dict(cur)
            if all(v == "auto" for v in cur["gate"].values()):
                rec.pop("gate", None)
            if cur["gitpol"] == GITPOL_DEFAULT:
                rec.pop("gitpol", None)
            if cur["edits"] == "ask":
                rec.pop("edits", None)
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


