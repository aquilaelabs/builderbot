"""Controller settings the operator changes on the Settings tab (roadmap R29).

The rule (env-only-what-must, on the Briefing tab): a setting is an
environment variable only when the container cannot start without it or the
host has to know it — paths, ids, ports, the role, shielded credentials.
Everything else lives here, in /config/settings.json, edited on the Settings
tab, and applied either at once or at the next boot. Each one used to be an
environment variable, which is five places to keep in step and a container
restart to change a number.

Every key still knows the variable it replaced, and reads it when the file
has no value — for one release, so an install that set the variable keeps
working through the update; the tab shows "from the environment" beside it
until it is saved here, which is the one act that makes this file the owner.
The boot scripts read the same three-way answer through bb_setting in
lib/common.sh: this file, then the variable, then the default.

What is NOT here, and why: GITHUB_URL stays beside the PAT it is used with,
in the root-only stash the entrypoint builds — a session can write this
file, and the org a runner token is minted for should not be a session's to
change. The two GPU switches are a node's, not the controller's, and belong
on the node's row once a container node reads its config from there.
"""
import os
import subprocess
import sys
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402

write_json = None
FILE = None
HOME = None

# key -> the variable it replaced, its default, its shape, and when a change
# takes: "live" (applied by set_many) or "boot" (read by a startup hook).
KEYS = {
    "max_tabs": {"env": "DASHBOARD_MAX_TABS", "default": 12, "kind": "int",
                 "min": 1, "max": 64, "applied": "live"},
    "claude_auto_update": {"env": "AUTO_UPDATE_CLAUDE", "default": True,
                           "kind": "bool", "applied": "boot"},
    "claude_version": {"env": "CLAUDE_CODE_VERSION", "default": "latest",
                       "kind": "text", "applied": "boot"},
    "git_name": {"env": "GIT_USER_NAME", "default": "", "kind": "text", "applied": "live"},
    "git_email": {"env": "GIT_USER_EMAIL", "default": "", "kind": "text", "applied": "live"},
    "packages_apt": {"env": "EXTRA_APT_PACKAGES", "default": "", "kind": "words", "applied": "boot"},
    "packages_npm": {"env": "EXTRA_NPM_PACKAGES", "default": "", "kind": "words", "applied": "boot"},
    "packages_pipx": {"env": "EXTRA_PIPX_PACKAGES", "default": "", "kind": "words", "applied": "boot"},
    "project_bootstrap": {"env": "PROJECT_BOOTSTRAP", "default": False,
                          "kind": "bool", "applied": "boot"},
    "unraid_icon_name": {"env": "UNRAID_ICON_NAME", "default": "BuilderBot",
                         "kind": "text", "applied": "boot"},
}
MAX_TEXT = 200
MAX_WORDS = 2000


def configure(*, write_json, state, home=None):
    globals().update(write_json=write_json,
                     HOME=Path(home) if home else Path.home())
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
    if kind == "words":
        return " ".join(str(raw or "").split())[:MAX_WORDS]
    return " ".join(str(raw or "").split())[:MAX_TEXT]


def effective():
    """{key: {"value", "source"}} — this file, else the variable, else the
    default. `source` is what the tab says beside the field."""
    d = load()
    out = {}
    for key, spec in KEYS.items():
        if key in d and _parse(key, d[key]) is not None:
            out[key] = {"value": _parse(key, d[key]), "source": "settings"}
            continue
        env = os.environ.get(spec["env"])
        if env is not None and env != "" and _parse(key, env) is not None:
            out[key] = {"value": _parse(key, env), "source": "env"}
            continue
        out[key] = {"value": spec["default"], "source": "default"}
    return out


def get(key):
    return effective()[key]["value"]


def _apply_git(vals):
    """The commit identity, written where a session's git reads it — the
    builder home's global config — the moment it is saved, and again by the
    boot hook. --file rather than --global so the test harness, whose server
    runs under somebody's real HOME, writes into its own scratch home."""
    cfg = HOME / ".gitconfig"
    for k, name in (("git_name", "user.name"), ("git_email", "user.email")):
        if k not in vals:
            continue
        argv = ["git", "config", "--file", str(cfg)]
        argv += ["--unset", name] if not vals[k] else [name, vals[k]]
        try:
            subprocess.run(argv, check=False, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


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
                    else "true or false" if spec["kind"] == "bool" else "text")
            return {"error": f"{key} takes {hint}"}
        parsed[key] = v
    with _lock:
        d = load()
        d.update(parsed)
        write_json(FILE, d)
    if any(k in parsed for k in ("git_name", "git_email")):
        _apply_git(parsed)
    return {"ok": True, "set": sorted(parsed)}


def payload():
    return {"settings": effective(),
            "meta": {k: {"applied": s["applied"], "env": s["env"]} for k, s in KEYS.items()}}
