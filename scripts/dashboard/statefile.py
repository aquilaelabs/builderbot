#!/usr/bin/env python3
"""Writing a state file, and holding it while you read-modify-write one.

Two things that were each implemented several times, and one of them was
implemented wrong.

**The write.** Every state file goes to a temp file in the same directory and
is then renamed over the real one, so a reader (including bb-tty, which parses
the lock list on every session launch) never sees half a file. The temp name
is unique per call, from mkstemp. It used to be a fixed `<name>.json.tmp`, and
the dashboard is a threading server: two saves landing together each opened the
SAME temp file, the second truncating what the first was writing, and whichever
renamed first published a torn file. That was fixed in the server and NOT in
the five copies inside `bb`, which is the ordinary fate of a function that
exists six times.

**The lock.** roadmap.py and bugs.py already wrap every read-modify-write in
`with _lock:`, which was a threading.Lock. A threading lock guards the
threads of ONE process. The notebook has two writers: the dashboard, and a
`bb roadmap`/`bb bug` invocation, which is a separate short-lived process. Both
would load the file, both mutate their own copy, both write; os.replace makes
each write atomic and does nothing whatever about the second one landing on top
of the first. An item added from a terminal while the panel was saving simply
was not there afterwards, and nothing anywhere said so.

So the lock is on the FILE, taken with flock, and held across the load and the
save rather than around the save alone: locking the write is locking the wrong
half, because the read that produced the stale copy already happened.

Re-entrant on purpose. flock is per open file description, so a second
`open()` in the same process blocks against the first: a mutator that called
another through the front door would deadlock on itself. The depth count makes
the outermost `with` the one that takes and releases it.

One lock per path, and each module locks only its own file, so there is no
order in which two of them can be taken, and therefore no order to get wrong.
"""
import contextlib
import errno
import fcntl
import json
import os
import tempfile
import threading

# path -> [reentrant lock, depth, fd]. The RLock makes the depth and the fd
# safe to touch: only the thread holding it ever does.
_locks = {}
_guard = threading.Lock()


def write_json(path, obj, mode=0o644):
    """Atomically replace `path` with `obj` as JSON. `mode` is the file's
    from the moment it is in place: a file of password hashes was 0644
    for the instant between the rename and the chmod that followed it."""
    path = _p(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=os.path.basename(path) + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(obj, indent=2) + "\n")
        # mkstemp gives 600 and these were world-readable before.
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked(path):
    """Hold `path` exclusively, against this process's threads and every other
    process, for as long as the block runs.

    Never fatal. A state directory that cannot hold a lock file (read-only,
    full, a filesystem with no flock) degrades to the threading lock alone,
    which is what there was before this existed. Refusing to let somebody read
    their roadmap because a lock could not be taken would be a worse failure
    than the one being prevented.
    """
    key = _p(path)
    with _guard:
        ent = _locks.setdefault(key, [threading.RLock(), 0, None])
    ent[0].acquire()
    try:
        if ent[1] == 0:
            ent[2] = _flock(key)
        ent[1] += 1
        yield
    finally:
        ent[1] -= 1
        if ent[1] == 0 and ent[2] is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(ent[2], fcntl.LOCK_UN)
                os.close(ent[2])
            ent[2] = None
        ent[0].release()


class on:
    """A reusable `with` over whatever path a module has configured.

    Modules set their FILE in configure(), after import, so a lock built at
    import time would close over None. This reads the path when the block is
    entered, and it can be entered again, which a contextmanager object
    cannot: `with locked(p):` twice reuses a generator that is already
    finished. Its own stack is per-thread, so two threads entering the same
    handle do not pop each other's.
    """

    def __init__(self, get_path):
        self._get = get_path
        self._held = threading.local()

    def _stack(self):
        if not hasattr(self._held, "cms"):
            self._held.cms = []
        return self._held.cms

    def __enter__(self):
        cm = locked(self._get())
        cm.__enter__()
        self._stack().append(cm)
        return self

    def __exit__(self, *exc):
        return self._stack().pop().__exit__(*exc)


def _flock(key):
    """The open, locked fd for `key`, or None if this filesystem will not."""
    try:
        os.makedirs(os.path.dirname(key) or ".", exist_ok=True)
        fd = os.open(key + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd
    except OSError as e:
        # ENOLCK/EINVAL: a filesystem without locking. Anything else is worth
        # not swallowing silently, but not worth failing the operation over.
        if e.errno not in (errno.ENOLCK, errno.EINVAL, errno.ENOSYS):
            raise
        with contextlib.suppress(OSError):
            os.close(fd)
        return None


def _p(path):
    return os.fspath(path)
