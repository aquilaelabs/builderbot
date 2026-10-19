"""What the page keeps on the server: each account's tab strip and panes.

The strip is kept per account and handed to every browser that account
opens, so a phone picks up the desktop's layout; a revision on it keeps two
browsers from fighting over it. The server holds the routes and reads these
into the status poll.
"""
import json
from pathlib import Path

# How many tabs the page will open. Each terminal tab is an iframe running a
# full xterm.js with its own websocket, so this is a real ceiling on browser
# memory rather than a tidiness rule, and a phone hits it far earlier than a
# desktop does: twelve is what a browser on this box takes without falling
# over. It counts TERMINAL tabs, per account (the layout is kept per
# account): a document tab is a draw from state and costs nothing to keep.
MAX_TABS = 12


def max_tabs():
    return MAX_TABS


# What this module needs from the server, set by configure(): how a state
# file is written, and the one lock every read-edit-write of the server's
# state files takes.
write_json = None
lock = None

# Each account's strip, and the boot it was pruned under (prune_claude_tabs).
TABS_FILE = None             # <state>/tabs.json, set by configure()

def configure(*, state, write_json, lock):
    globals().update(write_json=write_json, lock=lock, TABS_FILE=Path(state) / "tabs.json")


# What a stored tab may contain. Anything else is dropped rather than trusted:
# this file is written by one browser and handed to every other one, so it is
# the one place where a bad value could travel between devices.
# Every kind of tab the saved layout may carry. A kind missing from here is
# dropped on read without a word, which is how the notebook came back from a
# refresh as no tab at all: it was written to the file and filtered out of it.
# "findings" is the Analysis tab the Static analysis button opens, the
# report as a document tab beside the notebook's own view of it.
TAB_KINDS = {"term", "toolchains", "emulator", "notebook", "projects", "docker", "findings", "roles", "nginx", "storage",
             "nodes", "settings", "jobs", "users", "profile", "apps", "phone", "runner", "home", "notices", "help",
             "sessions", "chat"}


def _layouts():
    """The whole file: {"boot": ..., "users": {uid: layout}}.

    One strip per ACCOUNT, keyed by the minted id rather than the name so a
    rename keeps it (users.mint_uid says why): a layout written by whoever
    last saved and handed to everybody else is fine for one operator and
    wrong the moment there are two.
    """
    try:
        v = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        v = {}
    if not isinstance(v, dict):
        v = {}
    if not isinstance(v.get("users"), dict):
        v = {"boot": v.get("boot"), "users": {}}
    return v


def load_layout(uid):
    """One account's strip, shape-checked. `uid` is users.uid_of(who)."""
    v = (_layouts().get("users") or {}).get(str(uid or ""))
    # Shape-checked field by field, not trusted: this runs inside every status
    # poll and once at startup (prune_claude_tabs), so a file holding
    # `"tabs": 5` (a hand edit, or a client that posted junk before the
    # handler checked) must read as "no layout", not raise and take the
    # whole dashboard down with a 500 per poll and a crash at the next boot.
    if not isinstance(v, dict):
        v = {}
    tabs, ids, terms = [], set(), 0
    stored = v.get("tabs") if isinstance(v.get("tabs"), list) else []
    for t in stored[:64]:
        if not isinstance(t, dict) or t.get("kind") not in TAB_KINDS:
            continue
        if t.get("kind") == "term":
            if terms >= max_tabs():
                continue              # the cap, on terminals alone
            terms += 1
        tid, arg, label = t.get("id"), t.get("arg"), t.get("label")
        if not all(isinstance(x, str) for x in (tid, arg, label)):
            continue
        if len(tid) > 32 or len(arg) > 200 or len(label) > 80:
            continue
        # Ids address panes and are how a tab is closed; a duplicate would make
        # two tabs indistinguishable to everything downstream.
        if tid in ids:
            continue
        ids.add(tid)
        tabs.append({"id": tid, "kind": t["kind"], "arg": arg, "label": label,
                     # Popped out into its own window (R8): kept so the page
                     # that popped it reconciles; another page drops it.
                     "popped": bool(t.get("popped"))})
    stored = v.get("panes") if isinstance(v.get("panes"), list) else []
    panes = [p if isinstance(p, str) and p in ids else None for p in stored[:2]]
    while len(panes) < 2:
        panes.append(None)
    rev = v.get("rev")
    return {"rev": rev if isinstance(rev, int) and rev >= 0 else 0,
            "tabs": tabs, "panes": panes,
            "active": 1 if v.get("active") == 1 and panes[1] else 0}


def save_layout(uid, v):
    """Write one account's strip, leaving every other account's alone."""
    uid = str(uid or "")
    if not uid:
        return                            # not a person: nothing to remember
    all_of = _layouts()
    all_of["users"][uid] = v
    write_json(TABS_FILE, all_of | {"boot": boot_id()})


def boot_id():
    """An identifier for this run of the container.

    PID 1 is the container's init, so when it changes the container was
    restarted. Pairing its start time with the host's boot time keeps the value
    from repeating across a host reboot. Restarting only the dashboard leaves
    both untouched, which is the distinction this is for.

    An unreadable /proc gives "", which compares equal to nothing and so is
    treated as "cannot tell" by the one caller that acts on a difference.
    """
    try:
        start = Path("/proc/1/stat").read_text().rsplit(")", 1)[1].split()[19]
        btime = next(l for l in Path("/proc/stat").read_text().splitlines()
                     if l.startswith("btime "))
        return f"{btime.split()[1]}.{start}"
    except (OSError, IndexError, StopIteration):
        return ""


def prune_claude_tabs():
    """Drop Claude tabs left over from a previous run of the container.

    A shell tab survives a restart because it can: bb-tty recreates the session
    in the same directory and the operator carries on. A Claude tab cannot: the
    conversation ended with the container, and restoring the tab would start a
    brand new session wearing the old one's name. The transcript is still on
    disk, so the project's Claude button offers to resume it; that is a decision
    to make, not one to make silently at boot.

    Called once at startup, and once for EVERY account: the strip is per
    person (roadmap #25), and a boot that pruned only one of them would
    leave everyone else's dead Claude tabs on their strip.

    The revision is bumped so a browser left open across the restart adopts
    the pruned strip instead of saving its stale tabs back.
    """
    try:
        stored = json.loads(TABS_FILE.read_text())
    except (OSError, ValueError):
        return
    here = boot_id()
    if not here or stored.get("boot") == here:
        return
    for uid in list((_layouts().get("users") or {})):
        v = load_layout(uid)
        kept = [t for t in v["tabs"] if not t["arg"].startswith("claude:")]
        if len(kept) == len(v["tabs"]):
            continue                    # nothing to drop for this one
        ids = {t["id"] for t in kept}
        panes = [p if p in ids else None for p in v["panes"]]
        if panes[0] is None:
            panes = [panes[1], None]
        try:
            save_layout(uid, {"rev": v["rev"] + 1, "tabs": kept, "panes": panes,
                              "active": 1 if panes[1] else 0})
        except OSError:
            return                      # a read-only /config is not fatal here
    # The boot stamp regardless, so a run that dropped nothing is not asked
    # again on every restart afterwards.
    try:
        write_json(TABS_FILE, _layouts() | {"boot": here})
    except OSError:
        pass


# ---- the verbs, one call each from the dashboard ------------------------------

def save_tabs(uid, req):
    """Store one account's open tabs, bumping a revision so its other
    browsers notice. The revision is what keeps two browsers from fighting:
    each polls, sees a number it did not write, and adopts. Without it they
    would take turns overwriting each other every fifteen seconds.
    (payload, status)."""
    # The lists are validated entry by entry when read back, but they have
    # to BE lists: a stored non-list is what load_layout would otherwise
    # have to survive on every poll from then on.
    if not isinstance(req.get("tabs", []), list) or not isinstance(req.get("panes", []), list):
        return {"error": "bad request"}, 400
    with lock:
        cur = load_layout(uid)
        v = {"rev": cur["rev"] + 1,
             "tabs": req.get("tabs") or [],
             "panes": req.get("panes") or [None, None],
             "active": 1 if req.get("active") == 1 else 0}
        try:
            save_layout(uid, v)
        except OSError as e:
            return {"error": f"could not save: {e}"}, 500
        # Re-read so the caller gets exactly what every other client will
        # see, including anything the validator dropped.
        return load_layout(uid), 200

