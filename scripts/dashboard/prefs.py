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
            "dockernode": str(rec.get("dockernode") or "")}


def get(project):
    return _clean(_load()["projects"].get(project))


def all_projects():
    """Every project's pair, for the status payload. Cheap — one small file,
    no subprocess — which is what lets this ride the poll at all."""
    d = _load()["projects"]
    return {k: _clean(v) for k, v in d.items() if isinstance(k, str)}


def set_prefs(project, model=None, effort=None, dockernode=None):
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
        if dockernode is not None:
            cur["dockernode"] = str(dockernode)[:40]
        # An empty pair is removed rather than stored: the file then says only
        # what somebody chose, and a project left alone leaves no trace to read
        # past when its directory is renamed or deleted.
        if cur["model"] or cur["effort"] or cur.get("dockernode"):
            d["projects"][project] = cur
        else:
            d["projects"].pop(project, None)
        write_json(FILE, d)
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
