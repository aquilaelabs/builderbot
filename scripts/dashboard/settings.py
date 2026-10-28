"""Controller settings the operator changes on the Settings page (roadmap R29).

The rule (env-only-what-must, on the Briefing tab): a setting is an
environment variable only when the container cannot start without it or the
host has to know it. Everything else lives here, in /config/settings.json,
edited on the Settings page and read by the boot hooks through bb_setting in
lib/common.sh: this file, else the default. Nothing reads an environment
variable for one of these any more (the rule `unreleased`).

Few keys, deliberately. The first pass moved fourteen variables here; the
operator then asked which of them needed to exist at all, and most did not:
the tab cap is a constant, the packages a node needs come from the package
manager and the controller carries what it needs in the image, the project
bootstrap and the icon name went with the features, and the commit identity
is a project's own (prefs.py, the settings dialog). Two more went with the
Claude Code install itself (R47): this container does not carry it, so
whether to update it here and on which channel were settings about nothing:
a node installs its own and `claude update` in a session there keeps it
current.

A node's runner token and the address it registers with are not here
either: they go through mint-runner-token into a root-only store keyed by
node, because a session can write this file, and the organization a runner
token is minted for should not be a session's to change.
"""
import base64
import os
import re
import shutil
import sys
import time
from pathlib import Path

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
import statefile  # noqa: E402

write_json = None
# A secret's value sealed under the install key where there is one (R135),
# as signing keys and two-factor secrets are: set by the server.
seal = None               # bytes -> bytes, signing.seal
unseal = None             # bytes -> bytes, or raises signing.Locked
sealing = None            # () -> whether an install key is loaded now
SEALED = "bbseal:"        # a sealed value's prefix, its blob after it in base64
# What reset() forgets beside the state it moves aside: the runner tokens,
# which are root's, behind the helper (runners.reset), set by server.py.
forget_runners = None
FILE = None

# key -> its default, its shape, and when a change takes: "now", applied by
# set_many. A switch, a text, a secret, or a whole number between its min
# and max.
KEYS = {
    # Off, the pickers offer only what has been proven: the git hosts, the
    # hypervisors and the provisioner's OS families that carry a vetting
    # note (the date and what proved them) in their catalog: the alpha
    # tier. On, every entry is offered, the unproven ones tagged dev, and
    # the header says dev. One tree behaves as two products: production
    # leaves this off, a dev instance turns it on, and an entry crosses
    # over when a lab suite or a real run proves it (roadmap R54, step 6).
    "offer_unvetted": {"default": False, "kind": "bool", "applied": "now"},
    # Off, a session on a node reads only logs belonging to the work it is
    # doing: the CI runs for its project, and what its own test runs left.
    # The machine's own logs (the agent's journal, the runner's, the
    # terminal server's) are root's on that box and are not offered at all.
    #
    # On, a node's row gains Debug settings, where each node is granted the
    # nodes whose machine logs its sessions may read. Nothing is granted by
    # this switch: it only puts the question on the screen. A node is not
    # implicitly granted ITSELF, because its own journal is as much system
    # level as any other machine's.
    "debug_mode": {"default": False, "kind": "bool", "applied": "now"},
    # First run (R199, the operator, 12 Oct): False from the moment the
    # owner is made until Finish on the setup page, which needs a node
    # enrolled and answering. While False the page shows only the setup
    # panel and the Nodes tab. True by default: a controller that never
    # went through the setup page is one already set up.
    "setup_done": {"default": True, "kind": "bool", "applied": "now"},
    # The home tunnel the controller runs itself (R176, tunnel.py): the
    # public hostname a node off the LAN dials, the tunnel's token from
    # Zero Trust, and an API token with which the hostname's record and the
    # tunnel's rules are written rather than clicked. The two tokens are
    # secrets: kept here, never shown back, only said to be set.
    "tunnel_host": {"default": "", "kind": "text", "applied": "now"},
    # The vetted catalog's address (R169 step 2): where index.json and index.sig are read from.
    "catalog_url": {"default": "https://raw.githubusercontent.com/aquilaelabs/builderbot-catalog/main/", "kind": "text", "applied": "now"},
    "tunnel_token": {"default": "", "kind": "secret", "applied": "now"},
    "cf_api_token": {"default": "", "kind": "secret", "applied": "now"},
    # The dashboard's own connection (R158 step 2, tls.py): http, self (the
    # install's own certificate) or acme (Let's Encrypt for the hostname,
    # by DNS-01 through the Cloudflare API token); "" is self where a
    # hostname is set and http otherwise. The hostname is the controller's
    # own public name; the email is the ACME account's.
    # The mail server the bell's rows go out through (R149, reach.py):
    # Controller settings, Mail; the password sealed like the tokens.
    "smtp_host": {"default": "", "kind": "text", "applied": "now"},
    "smtp_port": {"default": "", "kind": "text", "applied": "now"},
    "smtp_security": {"default": "starttls", "kind": "text", "applied": "now"},
    "smtp_user": {"default": "", "kind": "text", "applied": "now"},
    "smtp_password": {"default": "", "kind": "secret", "applied": "now"},
    "smtp_from": {"default": "", "kind": "text", "applied": "now"},
    "tls_mode": {"default": "", "kind": "text", "applied": "now"},
    "tls_host": {"default": "", "kind": "text", "applied": "now"},
    "tls_email": {"default": "", "kind": "text", "applied": "now"},
    # The apps this controller offers its people (R272 step 3, apps.py):
    # each one on fetches that app from the release matching this
    # controller's version, checks it and serves it from /apps; off, it is
    # neither fetched nor offered. Set first by the seed file a compose
    # generator writes (apps.seed), then here.
    "apps_android": {"default": True, "kind": "bool", "applied": "now"},
    "apps_vscode": {"default": True, "kind": "bool", "applied": "now"},
    "apps_companion": {"default": True, "kind": "bool", "applied": "now"},
    # Maintenance mode: while on, the owner alone signs in and is answered,
    # from the page, a phone or a session; every other account is told why
    # and stays signed in for after. Nodes are not accounts and keep running.
    "maintenance_mode": {"default": False, "kind": "bool", "applied": "now"},
    # The update window (R160 step 4): when a newer release is applied by
    # itself, never by default; the day (daily, or one weekday) and the hour.
    # The backup password (R161 step 4): the copies of the state on the
    # machine's pools are sealed under a key it derives; eight characters
    # at least, sealed here like every secret.
    "backup_password": {"default": "", "kind": "secret", "applied": "now"},
    "update_window": {"default": "", "kind": "choice", "applied": "now",
                      "choices": ["", "daily", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
    # The release channel (R179): normal is the releases as published; dev
    # takes the pre-releases CI publishes from a dev build too, and may be
    # picked only on a controller started in debug mode with the dev switch
    # on. Reset to normal at a start without debug mode, as the switches are.
    "release_channel": {"default": "normal", "kind": "choice", "applied": "now", "choices": ["normal", "dev"]},
    "update_hour": {"default": 4, "kind": "number", "min": 0, "max": 23, "applied": "now"},
    # The room a node keeps for itself (R110): the disk left free under
    # which the bell warns and a build, a test or a container's rebuild is
    # refused (a tenth of a disk smaller than ten times this), the memory
    # in use over ten minutes past which the bell warns, and a memory limit
    # every container gets when its compose file sets none (0: none).
    "room_floor_gb": {"default": 10, "kind": "number", "min": 1, "max": 1000, "applied": "now"},
    "room_mem_pct": {"default": 92, "kind": "number", "min": 50, "max": 99, "applied": "now"},
    "container_mem_gb": {"default": 0, "kind": "number", "min": 0, "max": 1024, "applied": "now"},
}


# The debug and dev options exist only on a controller started with
# DEBUG_MODE=1 (the operator, 12 Oct): a switch for those who know, kept out
# of the env example, the template and the README on purpose. Without it the
# two switches read off and cannot be turned on, the Settings tab offers
# neither, and at start every option they opened (these two, and each
# project's Debug grants) is put back off, so setting it to 1 again starts
# from nothing granted.
DEBUG_KEYS = ("debug_mode", "offer_unvetted")
# ...and what only those allow, put back at a start without them.
DEBUG_ONLY = ("release_channel",)


def debug_available():
    return os.environ.get("DEBUG_MODE", "").strip() == "1"


def dev_channel_ok():
    """Whether the dev release channel may be picked here (R179): debug mode
    on and the dev switch on."""
    return debug_available() and _parse("offer_unvetted", load().get("offer_unvetted")) is True


def reset_debug():
    """Every debug and dev switch off, on a controller started without
    DEBUG_MODE=1. Whether anything was on."""
    with _lock:
        d = load()
        on = [k for k in DEBUG_KEYS if d.get(k) is True] + [k for k in DEBUG_ONLY if d.get(k) not in (None, KEYS[k]["default"])]
        for k in DEBUG_KEYS + DEBUG_ONLY:
            d.pop(k, None)
        if on:
            write_json(FILE, d)
    return bool(on)


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


HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)+$")
SECRET_MAX = 8000


def _parse(key, raw):
    """A setting's value out of a string or a JSON value, by its kind, or
    None when it cannot be read as one: an unreadable value is treated as
    unset rather than as an error on every read. A switch is true or false;
    a text is one line with the shape its key asks for (a hostname); a
    secret is one line, empty meaning none."""
    spec = KEYS.get(key, {})
    kind = spec.get("kind", "bool")
    if kind == "number":
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            v = int(str(raw).strip())
        except ValueError:
            return None
        return v if spec["min"] <= v <= spec["max"] else None
    if kind == "text":
        if isinstance(raw, bool) or raw is None:
            return None
        v = str(raw).strip().lower()[:253]
        return v if v == "" or HOST_RE.match(v) else None
    if kind == "choice":
        if isinstance(raw, bool) or raw is None:
            return None
        v = str(raw).strip().lower()[:40]
        return v if v in spec["choices"] else None
    if kind == "secret":
        if isinstance(raw, bool) or raw is None:
            return None
        v = str(raw).strip()
        return v if len(v) <= SECRET_MAX and "\n" not in v else None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return None


def secret(key):
    """A secret's value, for the code that uses it; effective() never
    carries it. Sealed, it is opened here; one this install cannot open
    (another install key, or none) reads as unset."""
    d = load()
    raw = d.get(key, "")
    if isinstance(raw, str) and raw.startswith(SEALED):
        try:
            raw = unseal(base64.b64decode(raw[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked, or a damaged value: unset)
            return ""
    v = _parse(key, raw) if key in d else None
    return v if isinstance(v, str) else ""


def _sealed(v):
    """A secret's value as it is kept: sealed where there is an install key."""
    if v and seal and sealing and sealing():
        return SEALED + base64.b64encode(seal(v.encode())).decode()
    return v


def seal_all(again=False):
    """Every secret kept open sealed, once the install has a key: at start.
    `again`, after the install key changed (R154): every sealed one sealed
    once more, under today's key. Returns how many."""
    if not (seal and sealing and sealing()):
        return 0
    with _lock:
        d = load()
        n = 0
        for key, spec in KEYS.items():
            v = d.get(key)
            if spec["kind"] != "secret" or not isinstance(v, str) or not v:
                continue
            if not v.startswith(SEALED):
                d[key] = _sealed(v)
                n += 1
            elif again:
                try:
                    d[key] = _sealed(unseal(base64.b64decode(v[len(SEALED):])).decode())
                    n += 1
                except Exception:                           # noqa: BLE001 (one that cannot be opened stays as it is)
                    continue
        if n:
            write_json(FILE, d)
    return n


def effective():
    """{key: {"value", "source"}} from this file, else the default. `source` is
    what the tab says beside a field that has never been saved."""
    d = load()
    out = {}
    off = not debug_available()
    for key, spec in KEYS.items():
        if off and key in DEBUG_KEYS:
            out[key] = {"value": False, "source": "locked"}
        # Debug mode is the environment's (the operator, 26 Oct): on exactly
        # when the controller was started with DEBUG_MODE=1, with nothing to
        # switch on in the page as well.
        elif key == "debug_mode":
            out[key] = {"value": True, "source": "env"}
        elif key in d and _parse(key, d[key]) is not None:
            out[key] = {"value": _parse(key, d[key]), "source": "settings"}
        else:
            out[key] = {"value": spec["default"], "source": "default"}
        # A secret is never shown back: the tab learns that one is set,
        # sealed (R135) or not.
        if spec["kind"] == "secret":
            sealed = isinstance(d.get(key), str) and d[key].startswith(SEALED)
            out[key] = {"value": "", "set": sealed or bool(out[key]["value"]),
                        "source": "settings" if sealed else out[key]["source"]}
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
        if key in DEBUG_KEYS and not debug_available() and _parse(key, raw) is True:
            return {"error": "the debug and dev options are not available on this controller"}
        if key == "debug_mode":
            return {"error": "debug mode is on while the controller is started with DEBUG_MODE=1, and off otherwise"}
        if key == "release_channel" and _parse(key, raw) == "dev" and not dev_channel_ok():
            return {"error": "the dev channel is offered only on a controller in debug mode with the dev switch on"}
        v = _parse(key, raw)
        if v is None:
            kind = KEYS[key]["kind"]
            return {"error": f"{key} takes true or false" if kind == "bool"
                    else f"{key} is a hostname like bb.example.com" if kind == "text"
                    else f"{key} is a whole number from {KEYS[key]['min']} to {KEYS[key]['max']}" if kind == "number"
                    else f"{key} is one of {', '.join(x or 'off' for x in KEYS[key]['choices'])}" if kind == "choice"
                    else f"{key} is one line"}
        parsed[key] = _sealed(v) if KEYS[key]["kind"] == "secret" else v
    with _lock:
        d = load()
        d.update(parsed)
        write_json(FILE, d)
    return {"ok": True, "set": sorted(parsed)}


def payload():
    return {"settings": effective(), "debug_available": debug_available(),
            "meta": {k: {"applied": s["applied"]} | ({"min": s["min"], "max": s["max"]} if s["kind"] == "number" else {})
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


def reset(state):
    """Start over at onboarding: the controller's own state moved aside
    (accounts, nodes, project settings, git tokens, the notebook, memories,
    logs), project files untouched. The runner tokens are root's, behind the
    helper: forgotten there, since the nodes they were for are being
    forgotten here. (payload, status); the server re-executes itself after
    a 200, so the next page is Create the owner."""
    try:
        moved = reset_state(state)
    except OSError as e:
        return {"error": f"could not move the state aside: {e}"}, 500
    forgot = forget_runners()
    kept = [k for k in moved["kept"] if not (k == "runner-tokens" and forgot)]
    return {"ok": True, "moved_to": str(moved["dest"]), "kept": kept}, 200
