"""The dashboard's modules, for the bb verbs that read and write the notebook's
files directly rather than through the API (roadmap, bug, history, findings,
rules, tests, settings, users, nodes, jobs, work, version, changelog,
preamble, and the doctor's and the lint's probes): each loaded by path from
the dashboard directory beside the bb that is running, so a checkout's bb
works with the checkout's modules and the running image's bb with the
image's, and neither imports a dashboard.

bb hands each verb the module's path (or the dashboard directory) as its
first argument, and DASHBOARD_STATE in its environment says where the
notebook's files are.
"""
import importlib.util
import json
import os
import sys


def beside(path):
    """The directory a module's path names: where the rest of the dashboard's modules are."""
    return os.path.dirname(os.path.abspath(path))


def load(name, here):
    """The dashboard module NAME from the directory HERE, executed fresh.
    A notebook module puts its own directory on sys.path as it loads, so
    what it imports beside itself (ids, pending) is importable after this
    the way it is inside the server."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def statefile(here):
    """The atomic write the notebook's modules share (statefile.py), which
    carries the file lock that stops this process and the dashboard losing
    each other's writes. Registered under its name so a module that imports
    it gets this copy."""
    sf = load("statefile", here)
    sys.modules["statefile"] = sf
    return sf


# Which account this session belongs to, for the notebook's logs: "claude"
# says a session wrote it, and with two people each running one that does not
# say whose. Read from the users file the way `bb settings` reads the commit
# identity: no configure, two fields.
def account_name(state_dir):
    uid = os.environ.get("BB_ACCOUNT_UID", "")
    try:
        with open(os.path.join(state_dir, "users.json")) as f:
            store = json.load(f).get("users") or {}
    except (OSError, ValueError):
        return ""
    for name, u in store.items():
        if isinstance(u, dict) and ((uid and u.get("uid") == uid)
                                    or (not uid and u.get("role") == "owner")):
            return str(name)
    return ""


def wrote(e):
    """Who made a change, for a log line: the mark, and the person behind it
    where the entry carries one. "you" and "claude" say a person or a
    session; with two people on a project the name is the half that answers
    which. Entries written before this carry no name and read as they did."""
    by = str(e.get("by", "") or "")
    who = str(e.get("who", "") or "")
    return f"{by} {who}".strip() if who else by
