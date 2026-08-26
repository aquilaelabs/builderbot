#!/usr/bin/env python3
"""Which model and effort a Claude send should switch the session to.

One setting for the whole dashboard, set on its own sidebar card. It used to
be a pair of pickers inside the send box, asked again for every step and
every bug — but which model to work on is not a per-step question, it is the
operator's standing preference, and a question asked at every send is either
answered identically every time or left on the default out of fatigue.

So every path that puts something in front of a session — a roadmap step, a
bug, the version question — reads this and switches the session first, with
the same /model and /effort slash commands the send box used to type. Empty
means what "leave as is" meant: no switch, the session keeps what it has.

Worth restating here because claude says it too: those slash commands save
the pick as the default for NEW sessions as well — a switch is never scoped
to the conversation it is typed into. That note lives on the card now, once,
instead of appearing in every send box.
"""
import json
import os
import threading
from pathlib import Path

write_json = None
FILE = None
# Claude Code's own settings, where a /model or /effort switch is saved as the
# default for new sessions. Read-only here, and never written: it is claude's
# file, and the switch that changes it is claude's own command.
CLAUDE_SETTINGS = None

# The canonical tables. todo.py and bugs.py carry copies for their own
# switching; a value stored here must satisfy theirs, so keep them equal.
MODELS = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")

_lock = threading.Lock()


def configure(*, write_json, state, home=None):
    globals().update(write_json=write_json)
    globals()["FILE"] = Path(state) / "claude-prefs.json"
    h = Path(home or os.environ.get("BUILDER_HOME") or Path.home())
    globals()["CLAUDE_SETTINGS"] = h / ".claude" / "settings.json"


def current():
    """What claude itself is defaulting to right now — the answer to "so what
    IS it?", which the preference alone cannot give.

    A preference of "" means "send no switch", and a card showing only that
    says nothing about what a session will actually run on. This reads the
    default claude saves when /model or /effort is used, so the card can state
    the fact beside the choice. Best-effort: an unreadable or unfamiliar file
    means the card simply does not claim to know.
    """
    try:
        with open(CLAUDE_SETTINGS) as f:
            d = json.load(f)
    except (OSError, ValueError, TypeError):
        return {"model": "", "effort": ""}
    model = d.get("model")
    model = model if isinstance(model, str) else ""
    # The effort is filed under the resolved model id, not the short name.
    effort = ""
    ms = d.get("modelSettings")
    if isinstance(ms, dict):
        for key, val in ms.items():
            if isinstance(val, dict) and (model in key or not model):
                got = val.get("effortLevel")
                if isinstance(got, str):
                    effort = got
                    break
    return {"model": model, "effort": effort}


def get():
    """The current preference. Unset and invalid both read as "" — an entry
    hand-edited into nonsense should mean "leave as is", not an error on
    every send."""
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    model = d.get("model") if d.get("model") in MODELS else ""
    effort = d.get("effort") if d.get("effort") in EFFORTS else ""
    return {"model": model, "effort": effort}


def set_prefs(model=None, effort=None):
    """Change either half; None leaves that half alone, "" clears it."""
    with _lock:
        cur = get()
        if model is not None:
            if model not in MODELS and model != "":
                return {"error": f"not a model this can set: {model}"}
            cur["model"] = model
        if effort is not None:
            if effort not in EFFORTS and effort != "":
                return {"error": f"not an effort this can set: {effort}"}
            cur["effort"] = effort
        write_json(FILE, cur)
    return {"ok": True} | cur
