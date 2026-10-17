"""Where a request's time went (the operator, 17 Oct: pages took seconds to
load, and the trace could say which request but not why). A part of the
work wraps itself in `timed("name")`; the request's parts, its own thread's
CPU time beside its wall time, ride its line in the trace (server.py
trace_note), and `bb dashboard trace` sums them. Thread-local, so two
requests at once never mix their parts; free when nothing reads it.
"""
import contextlib
import threading
import time

_here = threading.local()


def start():
    """A request begins: its parts are empty and its CPU clock starts."""
    _here.parts = {}
    _here.cpu0 = time.thread_time()


def finish():
    """(cpu ms, {part: ms}) for the request now ending on this thread."""
    parts = getattr(_here, "parts", None) or {}
    cpu = (time.thread_time() - getattr(_here, "cpu0", time.thread_time())) * 1000
    _here.parts = {}
    return int(cpu), {k: int(v) for k, v in parts.items()}


@contextlib.contextmanager
def timed(name):
    """Add this block's wall time to the request's part called `name`."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        parts = getattr(_here, "parts", None)
        if parts is not None:
            parts[name] = parts.get(name, 0) + (time.monotonic() - t0) * 1000


def add(name, ms):
    """Add `ms` to the request's part called `name`, for work timed by hand."""
    parts = getattr(_here, "parts", None)
    if parts is not None:
        parts[name] = parts.get(name, 0) + ms
