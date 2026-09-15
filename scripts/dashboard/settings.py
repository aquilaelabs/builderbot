"""Controller settings the operator changes on the Settings tab (roadmap R29).

The rule (env-only-what-must, on the Briefing tab): a setting is an
environment variable only when the container cannot start without it or the
host has to know it. Everything else lives here, in /config/settings.json,
edited on the Settings tab and read by the boot hooks through bb_setting in
lib/common.sh: this file, else the default. Nothing reads an environment
variable for one of these any more (the rule `unreleased`).

Few keys, deliberately. The first pass moved fourteen variables here; the
operator then asked which of them needed to exist at all, and most did not:
the tab cap is a constant, the packages a node needs come from the package
manager and the controller carries what it needs in the image, the project
bootstrap and the icon name went with the features, and the commit identity
is a project's own (prefs.py, the settings dialog). Two more went with the
Claude Code install itself (R47): this container does not carry it, so
whether to update it here and on which channel were settings about nothing —
a node installs its own and `claude update` in a session there keeps it
current.

A node's runner token and the address it registers with are not here
either: they go through mint-runner-token into a root-only store keyed by
node, because a session can write this file, and the organization a runner
token is minted for should not be a session's to change.
"""
import os
import shutil
import sys
import time
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402

write_json = None
FILE = None

# key -> its default, its shape, and when a change takes: "live" (applied by
# set_many) or "boot" (read by a startup hook through bb_setting).
KEYS = {
    # Off, the server refuses a second Claude session on one project when
    # another account's session there is signed in to the same Claude
    # account — two people on one login is what Anthropic's terms forbid.
    # On, that refusal stands down: for one person testing two BuilderBot
    # accounts with the one Claude login they have. The refusal is kept,
    # not removed, because the setting is for that test and nothing else.
    "claude_shared_login": {"default": False, "kind": "bool", "applied": "now"},
    # Off, the pickers offer only what has been proven: the git hosts, the
    # hypervisors and the provisioner's OS families that carry a vetting
    # note (the date and what proved them) in their catalogue: the alpha
    # tier. On, every entry is offered, the unproven ones tagged dev, and
    # the header says dev. One tree behaves as two products: production
    # leaves this off, a dev instance turns it on, and an entry crosses
    # over when a lab suite or a real run proves it (roadmap R54, step 6).
    "offer_unvetted": {"default": False, "kind": "bool", "applied": "now"},
    # Off, a session on a node reads only logs belonging to the work it is
    # doing: the CI runs for its project, and what its own test runs left.
    # The machine's own logs — the agent's journal, the runner's, the
    # terminal server's — are root's on that box and are not offered at all.
    #
    # On, a node's row gains Debug settings, where each node is granted the
    # nodes whose machine logs its sessions may read. Nothing is granted by
    # this switch: it only puts the question on the screen. A node is not
    # implicitly granted ITSELF, because its own journal is as much system
    # level as any other machine's.
    "debug_mode": {"default": False, "kind": "bool", "applied": "now"},
}
MAX_TEXT = 200


def configure(*, write_json, state):
    globals().update(write_json=write_json)
    globals()["FILE"] = Path(state) / "settings.json"


_lock = statefile.on(lambda: FILE)


def load():
    try:
        with open(FILE) as f:
            d = __import__("json").load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse(key, raw):
    """A value of the key's kind out of a string or a JSON value, or None
    when it cannot be read as one — an unreadable value is treated as unset
    rather than as an error on every read."""
    spec = KEYS[key]
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        return None
    if kind == "int":
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return n if spec.get("min", n) <= n <= spec.get("max", n) else None
    if kind == "choice":
        v = str(raw or "").strip()
        return v if v in spec["choices"] else None
    return " ".join(str(raw or "").split())[:MAX_TEXT]


def effective():
    """{key: {"value", "source"}} — this file, else the default. `source` is
    what the tab says beside a field that has never been saved."""
    d = load()
    out = {}
    for key, spec in KEYS.items():
        if key in d and _parse(key, d[key]) is not None:
            out[key] = {"value": _parse(key, d[key]), "source": "settings"}
        else:
            out[key] = {"value": spec["default"], "source": "default"}
    return out


def get(key):
    return effective()[key]["value"]



def set_many(changes):
    """Save the given keys. Refuses an unknown key or a value not of its
    kind, and applies what applies live."""
    if not isinstance(changes, dict) or not changes:
        return {"error": "nothing to set"}
    parsed = {}
    for key, raw in changes.items():
        if key not in KEYS:
            return {"error": f"not a setting: {key}"}
        v = _parse(key, raw)
        if v is None:
            spec = KEYS[key]
            hint = (f"a whole number from {spec['min']} to {spec['max']}" if spec["kind"] == "int"
                    else "true or false" if spec["kind"] == "bool"
                    else "one of " + ", ".join(spec["choices"]) if spec["kind"] == "choice"
                    else "text")
            return {"error": f"{key} takes {hint}"}
        parsed[key] = v
    with _lock:
        d = load()
        d.update(parsed)
        write_json(FILE, d)
    return {"ok": True, "set": sorted(parsed)}


def payload():
    return {"settings": effective(),
            "meta": {k: {"applied": s["applied"], "choices": list(s.get("choices") or [])}
                     for k, s in KEYS.items()}}


def reset_state(state):
    """Start over: everything in the state directory moved into a dated
    directory beside it, never deleted. `.reset-<stamp>` holds what was
    there (accounts, nodes, project settings, git tokens, the notebook,
    memories, logs), so a reset pressed by mistake is a move back rather
    than a loss; earlier resets' directories are left where they are.
    Project files are not in here at all. Returns {dest, kept}: where it
    went, and the names that stayed because they could not be moved (the
    runner tokens' root-only store, a volume's mountpoint, anything the
    filesystem refused), which the caller says rather than hides. A refusal
    on one entry never stops the rest: a half-moved state that also stopped
    is the worst of both."""
    state = Path(state)
    dest = state / time.strftime(".reset-%Y%m%d-%H%M%S")
    dest.mkdir()
    kept = []
    for p in sorted(state.iterdir()):
        if p.name.startswith(".reset-"):
            continue
        if p.name in RESET_KEEPS:
            kept.append(p.name)
            continue
        try:
            shutil.move(str(p), str(dest / p.name))
        except OSError:
            kept.append(p.name)
    return {"dest": dest, "kept": kept}


# Left where they are by a reset: the runner tokens' store is root's and the
# mountpoint of a volume, and mint-runner-token --reset empties it instead.
RESET_KEEPS = ("runner-tokens",)
