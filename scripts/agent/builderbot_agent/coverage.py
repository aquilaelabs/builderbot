"""Function coverage (roadmap R76), under bb tests coverage only."""
import contextlib
import json
import os
import sys
import threading
import time


# ---- function coverage (roadmap R76) ----------------------------------------
# Under `bb tests coverage` the harness names a file (PID in the name is this
# process's, so an agent that re-execs itself on a self-update keeps its
# counts apart from its successor's), and every function of this package any
# thread enters is counted and written there, every few seconds and on the
# way out. A profile hook, call and return events only. Nothing here runs
# otherwise; the agent on a node never sees the variable.
# PID and the start time: an agent that re-executes itself keeps its PID, and
# its successor must not write over the counts of the process it replaced.
_COV_OUT = os.environ.get("BB_COVERAGE_OUT", "").replace("PID", f"{os.getpid()}-{int(time.time() * 1000)}")
_cov_counts = {}
_cov_lock = threading.Lock()
_COV_ME = os.path.dirname(os.path.realpath(__file__))   # the package: every module of it counts
_COV_AS = os.environ.get("BB_COVERAGE_AS", "")
_cov_mine = {}      # code object -> whether it is this file's, decided once


def _cov_profile(frame, event, arg):
    if event != "call":
        return
    co = frame.f_code
    mine = _cov_mine.get(co)
    if mine is None:
        # By real path, decided once per code object: the harness names this
        # file with a doubled slash, and a plain string compare counted nothing.
        mine = _cov_mine[co] = os.path.dirname(os.path.realpath(co.co_filename)) == _COV_ME
    if not mine:
        return
    # Named as the tree knows it (BB_COVERAGE_AS, the package's directory
    # there), since the suite may run a copy from elsewhere, as it does to
    # prove the self-update.
    where = f"{_COV_AS}/{os.path.basename(co.co_filename)}" if _COV_AS else co.co_filename
    key = f"{where}:{co.co_firstlineno}:{co.co_name}"
    with _cov_lock:
        _cov_counts[key] = _cov_counts.get(key, 0) + 1


def _cov_write():
    with _cov_lock:
        body = json.dumps({"suite": os.environ.get("BB_COVERAGE_SUITE") or "agent",
                           "counts": dict(_cov_counts)})
    with contextlib.suppress(OSError):
        tmp = _COV_OUT + ".tmp"
        with open(tmp, "w") as f:
            f.write(body)
        os.replace(tmp, _COV_OUT)


def _cov_start():
    import atexit
    sys.setprofile(_cov_profile)
    threading.setprofile(_cov_profile)

    def loop():
        while True:
            time.sleep(3)
            _cov_write()
    threading.Thread(target=loop, daemon=True, name="coverage").start()
    atexit.register(_cov_write)


if _COV_OUT:
    # At import, not in main(): the suite also drives this module in-process
    # (a backend's apply with hello stubbed), and those runs count too.
    _cov_start()
