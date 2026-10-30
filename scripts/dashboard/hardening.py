"""What the dashboard's process does about the keys it holds (R158 step 6).

The install key, the accounts' keys while unlocked, a terminal's wrapped
seal keys and the TLS private key all live in this process's memory for a
while. Three things keep them there and nowhere else:

  * no core dump: RLIMIT_CORE is zero and the process is not dumpable
    (PR_SET_DUMPABLE 0), which also keeps a process of the same user from
    reading its memory through ptrace or /proc/PID/mem; root still can,
    which docs/security.md says;
  * no swap: every page is locked in memory (mlockall, MCL_FUTURE with
    MCL_ONFAULT so only what is touched is locked) where the memlock limit
    lets it, which docker-compose.yml raises; refused, the Doctor says so;
  * zeroed where the language lets it: wipe() overwrites a bytes or
    bytearray value in place once the key it held is let go, since Python
    cannot promise when the object is freed.

What sessions ask for runs on the nodes, never in this process (the
controller runs nothing), and on a node the agent that opens a seal is a
process apart from the sessions, which run as their account's own user in
a view of their own (R125, bb-session): the one separation step 6 asks for
that the code already had. The agent does the same three things in its own
process (builderbot_agent.base.harden).
"""
import ctypes
import ctypes.util
import json
import os
import resource
import sys

STATUS_FILE = "/run/builderbot-hardening.json"
PR_SET_DUMPABLE = 4
MCL_CURRENT, MCL_FUTURE, MCL_ONFAULT = 1, 2, 4


def _libc():
    try:
        return ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    except OSError:
        return None


def apply(mlock=True, status_file=STATUS_FILE):
    """Core dumps off, the process not dumpable, its memory kept from swap
    where it may be. The result, kept for the Doctor: {core, dumpable,
    mlock, why}."""
    out = {"core": False, "dumpable": False, "mlock": False, "why": ""}
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        out["core"] = True
    except (ValueError, OSError) as e:
        out["why"] = f"core limit: {e}"
    libc = _libc()
    if libc is not None and sys.platform.startswith("linux"):
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0:
            out["dumpable"] = True
        else:
            out["why"] = (out["why"] + "; " if out["why"] else "") + f"prctl: errno {ctypes.get_errno()}"
        if mlock:
            # Only with no memlock limit: under one, MCL_FUTURE makes every
            # allocation past the limit fail, and the process would die of
            # the hardening rather than be kept from swap.
            soft, _hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
            if soft != resource.RLIM_INFINITY:
                out["why"] = (out["why"] + "; " if out["why"] else "") + (
                    "memory not locked: the memlock limit is set, and locking under one would stop the process growing "
                    "(docker-compose.yml lifts it with ulimits memlock -1; an Unraid template with --ulimit memlock=-1:-1)")
            elif libc.mlockall(MCL_FUTURE | MCL_ONFAULT) == 0 or libc.mlockall(MCL_FUTURE) == 0:
                out["mlock"] = True
            else:
                out["why"] = (out["why"] + "; " if out["why"] else "") + f"mlockall: errno {ctypes.get_errno()}"
    else:
        out["why"] = (out["why"] + "; " if out["why"] else "") + "not linux, or no libc"
    if status_file:
        try:
            tmp = status_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f)
            os.replace(tmp, status_file)
        except OSError:
            pass
    return out


def status(status_file=STATUS_FILE):
    try:
        with open(status_file, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def wipe(b):
    """A bytes or bytearray value overwritten with zeros in place, for a key
    that is let go: the object may live on until Python frees it, and this
    makes what it then holds nothing. Only CPython's layout is known here;
    anything else is left alone."""
    if isinstance(b, bytearray):
        for i in range(len(b)):
            b[i] = 0
        return True
    if isinstance(b, bytes) and b and sys.implementation.name == "cpython":
        try:
            # A bytes object is its header then its characters, in place.
            off = bytes.__basicsize__ - 1
            ctypes.memset(id(b) + off, 0, len(b))
            return True
        except (ValueError, OSError):
            return False
    return False
