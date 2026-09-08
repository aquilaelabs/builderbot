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
import subprocess
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
GATE_MODES = ("auto", "ask", "deny")

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
            # anybody wanted. A node id, "" meaning none; older records
            # spelled it dockernode or nodes.build, and both still read.
            "node": str(rec.get("node") or rec.get("dockernode")
                        or (rec.get("nodes") or {}).get("build") or "")[:40]
                    if isinstance(rec.get("nodes", {}), dict) else str(rec.get("node") or "")[:40],
            # What `bb build` / `bb test` run there, and the globs whose
            # matches come back into dist/.
            "build": str(rec.get("build") or "")[:500],
            "test": str(rec.get("test") or "")[:500],
            "outputs": [str(g)[:200] for g in (rec.get("outputs") or [])
                        if str(g)][:16] if isinstance(rec.get("outputs"), list) else [],
            # Anything unrecognised reads as auto, for the same reason an
            # unknown model reads as "leave as is": a hand-edited file must
            # not lock a session out of the notebook by typo.
            # The commit identity, per project: applied to the repo's own config
            # by set_prefs and by 40-projects.sh at boot, and carried to a node's
            # session by bb settings.
            "git_name": str(rec.get("git_name") or "")[:120],
            "git_email": str(rec.get("git_email") or "")[:200],
            "gate": {k: ((rec.get("gate") or {}).get(k)
                         if isinstance(rec.get("gate"), dict)
                         and (rec.get("gate") or {}).get(k) in GATE_MODES else "auto")
                     for k in GATE_KINDS}}


def get(project):
    return _clean(_load()["projects"].get(project))


def all_projects():
    """Every project's pair, for the status payload. Cheap — one small file,
    no subprocess — which is what lets this ride the poll at all."""
    d = _load()["projects"]
    return {k: _clean(v) for k, v in d.items() if isinstance(k, str)}


def set_prefs(project, model=None, effort=None, node=None, build=None, test=None,
              outputs=None, dockernode=None, gate=None, git_name=None, git_email=None,
              workspace=None):
    """Change any of one project's settings; None leaves it, "" clears it.
    `dockernode` is the old name for `node`, kept for a caller that still
    says it."""
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
        if node is None and dockernode is not None:
            node = dockernode
        if node is not None:
            cur["node"] = str(node)[:40]
        if build is not None:
            cur["build"] = str(build)[:500].strip()
        if test is not None:
            cur["test"] = str(test)[:500].strip()
        if outputs is not None:
            got = outputs if isinstance(outputs, list) else str(outputs).split(",")
            cur["outputs"] = [str(g).strip()[:200] for g in got if str(g).strip()][:16]
        if git_name is not None:
            cur["git_name"] = " ".join(str(git_name).split())[:120]
        if git_email is not None:
            cur["git_email"] = str(git_email).strip()[:200]
        if gate is not None:
            if not isinstance(gate, dict):
                return {"error": "gate is {roadmap|bugs|rules: auto|ask|deny}"}
            for k, v in gate.items():
                if k not in GATE_KINDS:
                    return {"error": f"not a gate: {k} — one of {', '.join(GATE_KINDS)}"}
                if v not in GATE_MODES:
                    return {"error": f"{k}: one of {', '.join(GATE_MODES)}, not {v}"}
                cur["gate"][k] = v
        # An empty pair is removed rather than stored: the file then says only
        # what somebody chose, and a project left alone leaves no trace to read
        # past when its directory is renamed or deleted.
        if (cur["model"] or cur["effort"] or cur["node"]
                or cur["build"] or cur["test"] or cur["outputs"]
                or cur["git_name"] or cur["git_email"]
                or any(v != "auto" for v in cur["gate"].values())):
            # Stored without the all-auto gate, so the file says only what
            # somebody chose — _clean puts the defaults back on the way out.
            rec = dict(cur)
            if all(v == "auto" for v in cur["gate"].values()):
                rec.pop("gate", None)
            d["projects"][project] = rec
        else:
            d["projects"].pop(project, None)
        write_json(FILE, d)
    # Into the repo's own config at once, so the next commit from any session
    # in it wears the name. Repo-local rather than global: two projects may be
    # two people's, and the tree is what a session's git reads.
    if (git_name is not None or git_email is not None) and workspace:
        repo = Path(workspace) / project
        if (repo / ".git").exists():
            for k, v in (("user.name", cur["git_name"]), ("user.email", cur["git_email"])):
                argv = ["git", "-C", str(repo), "config"] + (["--unset", k] if not v else [k, v])
                try:
                    subprocess.run(argv, check=False, capture_output=True, timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
    return {"ok": True, "project": project} | cur


def forget(project):
    """Drop a project's pair — for a project being deleted."""
    with _lock:
        d = _load()
        if d["projects"].pop(project, None) is not None:
            write_json(FILE, d)


def migrate(projects):
    """One-time move of the old global pair onto every project that exists.

    Called at startup with the current project list. Behaviour-preserving on
    purpose: an install that had "opus, max" standing for everything keeps
    exactly that, per project, and can then diverge. A file already in the new
    shape is left alone, so this is a no-op on every boot after the first.
    """
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(d, dict) or "projects" in d:
        return
    old = {"model": d.get("model") if d.get("model") in MODELS else "",
           "effort": d.get("effort") if d.get("effort") in EFFORTS else ""}
    new = {"projects": {}}
    if old["model"] or old["effort"]:
        for name in projects:
            new["projects"][name] = dict(old)
    with _lock:
        write_json(FILE, new)
