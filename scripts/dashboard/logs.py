#!/usr/bin/env python3
"""The container's logs: what is kept, for how long, and how to take a copy.

Four streams, one file each per container start, because one file per session
means "what happened on that boot" is answerable by opening a file rather than
by hunting for a boundary in an appended stream:

    builderbot.log   the boot, and every warning or error after it
    dashboard.log    the dashboard server's own output, in full
    docker.log       every compose call the Docker manager made
    ttyd.log         the terminal server

The boot log is the one to read first, and the reason is the third line above:
it used to end when the hooks finished, so anything that went wrong an hour
later was in a different file that nothing pointed at. It now carries the
warnings and errors from the other two as they happen, so the session's story
is in one place and the detail is next door.

Kept for a number of DAYS rather than a number of boots. A count is the wrong
unit for the question anybody actually has — "was that this week?" — and a
crash loop can burn five generations in a minute. The count survives as a
ceiling for exactly that case, not as the policy.
"""
import io
import json
import os
import re
import tarfile
import threading
import time
from pathlib import Path

STATE = None
write_json = None
_lock = threading.Lock()

# The streams this container writes. Anything else there is somebody else's and is
# listed but never pruned or cleared — /logs may be a share the operator put
# other things in.
STREAMS = ("builderbot.log", "dashboard.log", "docker.log", "ttyd.log")

DEFAULT_DAYS = 30
# A ceiling on generations, whatever the day count says. Rotation is per start,
# so a container in a crash loop makes a file per restart; without this, thirty
# days of that is a directory nobody can list.
MAX_GENERATIONS = 60


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


def log_dir():
    """Where the logs are — the same three-step answer bb_log_dir gives.

    Kept in step with lib/common.sh by having the same priority in the same
    order: an explicit BB_LOG_DIR, then a mounted /logs share, then inside
    /config. Two readers of one path have to agree, and the shell half is the
    one that creates it.
    """
    if os.environ.get("BB_LOG_DIR"):
        return Path(os.environ["BB_LOG_DIR"])
    if Path("/logs").is_dir():
        return Path("/logs")
    return STATE / "logs"


# --- the setting -----------------------------------------------------------

def _file():
    return STATE / "log-prefs.json"


def days():
    """How many days of logs to keep. The operator's, or the default."""
    try:
        d = json.loads(_file().read_text())
        n = int(d.get("days", DEFAULT_DAYS))
    except (OSError, ValueError, TypeError):
        return DEFAULT_DAYS
    # A floor of 1: zero would mean deleting the boot log of the session
    # reading it, which is not a retention policy, it is a bug with a setting
    # in front of it.
    return max(1, min(3650, n))


def set_days(n):
    try:
        n = max(1, min(3650, int(n)))
    except (TypeError, ValueError):
        return {"error": "days must be a number"}
    with _lock:
        write_json(_file(), {"days": n})
    return {"ok": True, "days": n, "removed": prune()}


# --- what is there ---------------------------------------------------------

# builderbot.log, and builderbot.log.3 — the generation is the boot count back.
_GEN = re.compile(r"^(?P<stem>[A-Za-z0-9._-]+?\.log)(?:\.(?P<gen>\d+))?$")


def _entries():
    d = log_dir()
    try:
        names = sorted(p.name for p in d.iterdir() if p.is_file())
    except OSError:
        return []
    out = []
    for name in names:
        m = _GEN.match(name)
        if not m:
            continue
        p = d / name
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "name": name,
            "stream": m.group("stem"),
            # 0 is the live one — this session's — and N is N boots back.
            "generation": int(m.group("gen") or 0),
            "bytes": st.st_size,
            "mtime": int(st.st_mtime),
            "ours": m.group("stem") in STREAMS,
        })
    out.sort(key=lambda e: (-e["mtime"], e["name"]))
    return out


def payload():
    """What the settings panel shows: the policy, and what it is holding."""
    es, ci = _entries(), _ci_entries()
    return {
        "dir": str(log_dir()),
        "days": days(),
        "files": len(es) + len(ci),
        "ci": len(ci),
        "bytes": sum(e["bytes"] for e in es) + sum(e["bytes"] for e in ci),
        # This session's own, which is what Download reaches for first.
        "session": [e["name"] for e in es if e["generation"] == 0 and e["ours"]],
        "oldest": min((e["mtime"] for e in es), default=0),
    }


# --- keeping the directory honest ------------------------------------------

def prune():
    """Drop what is past the policy. Returns how many files went.

    Only the streams this container writes — a /logs share may hold somebody
    else's files, and a retention setting on this page is not a licence to
    delete them.

    The live generation is never touched, whatever its age: a container that
    has been up for six months is still writing to it, and the file somebody
    is reading is the last one to remove on the grounds that it is old.
    """
    cutoff = time.time() - days() * 86400
    gone = 0
    for e in _entries():
        if not e["ours"] or e["generation"] == 0:
            continue
        if e["mtime"] < cutoff or e["generation"] > MAX_GENERATIONS:
            try:
                (log_dir() / e["name"]).unlink()
                gone += 1
            except OSError:
                pass
    for e in _ci_entries():
        if e["mtime"] < cutoff:
            try:
                e["path"].unlink()
                gone += 1
            except OSError:
                pass
    return gone


def clear():
    """Everything but this session. The live files are left in place.

    Truncating them instead was the other option and is worse: the boot log is
    an open file descriptor in the entrypoint, and cutting it out from under a
    running `tee` gets you a sparse file that reads as leading nulls.
    """
    gone = 0
    for e in _entries():
        if not e["ours"] or e["generation"] == 0:
            continue
        try:
            (log_dir() / e["name"]).unlink()
            gone += 1
        except OSError:
            pass
    return {"ok": True, "removed": gone}


# --- taking a copy ---------------------------------------------------------

# In the archive but not in the session bundle. ttyd.log is the terminal
# server's connection churn — 22,000 lines and 1.5MB on this box against 4KB
# of boot log — so bundling it means the thing somebody opens to read what
# happened is 99% libwebsockets tagging its own sockets.
SESSION_STREAMS = tuple(n for n in STREAMS if n != "ttyd.log")


def session_bytes():
    """This session's logs as one text file, in stream order.

    One file rather than several downloads, because the question being asked
    is "what happened in this session" and the answer is spread across them.
    """
    out = []
    for name in SESSION_STREAMS:
        p = log_dir() / name
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        out.append(f"===== {name} =====\n{body}")
    if not out:
        return b"(no logs yet)\n"
    return "\n".join(out).encode("utf-8", "replace")


def archive_bytes():
    """Every log in the directory, as a .tar.gz, built in memory.

    In memory because these are text files that compress to very little and
    writing a temp file into /config to serve it back is a way to leave one
    behind. Capped, so a log directory that has grown beyond reason fails as a
    refusal rather than as the container running out of memory.
    """
    d = log_dir()
    es = [e for e in _entries()]
    ci = _ci_entries()
    total = sum(e["bytes"] for e in es) + sum(e["bytes"] for e in ci)
    if total > 256 * 1024 * 1024:
        return None, f"the log directory is {total // (1024*1024)}MB — too big to send"
    buf = io.BytesIO()
    try:
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for e in es:
                with open(d / e["name"], "rb") as f:
                    info = tarfile.TarInfo(f"builderbot-logs/{e['name']}")
                    info.size = e["bytes"]
                    info.mtime = e["mtime"]
                    tar.addfile(info, f)
            for e in ci:
                with open(e["path"], "rb") as f:
                    info = tarfile.TarInfo(f"builderbot-logs/{e['arc']}")
                    info.size = e["bytes"]
                    info.mtime = e["mtime"]
                    tar.addfile(info, f)
    except OSError as err:
        return None, str(err)
    return buf.getvalue(), ""


# --- CI, which is already per project and per run ---------------------------
#
# Deliberately NOT moved in here. A CI run is not a container session — it
# belongs to a workflow run, spans whatever session happened to be up, and is
# already one file per run under a directory per repository, which is the
# grouping somebody actually wants. `bb ci-log` reads them by run id.
#
# What was missing was only that the settings menu did not know they existed:
# they were not in the archive and no retention reached them. Both now do.

def ci_dir():
    return Path(os.environ.get("BB_CI_LOG_DIR", "/config/ci-logs"))


def _ci_entries():
    out = []
    root = ci_dir()
    try:
        repos = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for repo in repos:
        try:
            files = sorted(p for p in repo.iterdir() if p.is_file())
        except OSError:
            continue
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"path": f, "arc": f"ci/{repo.name}/{f.name}",
                        "bytes": st.st_size, "mtime": int(st.st_mtime)})
    return out
