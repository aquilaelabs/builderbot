"""Backups off the machine (R162 step 5): a folder on the controller's own
machine (a pool's mount, the array, the controller's state) copied to
another place (the array, a disk or a share mounted under /mnt/other) by
rsync, each run its own dated folder hard-linked to the one before so a
run costs only what changed, the oldest pruned past what is kept, and
`latest` always the newest whole run; a run that fails leaves no half
folder behind. The record comes with the hello (the controller's
backups.py), the storage-backup job names one of its rows, and the state
file beside it says each row's last run for the census.
"""
import json
import os
import re
import shutil
import subprocess
import time

from .base import log
from .stores import save_state

STATE_FILE = "/var/lib/builderbot/backups-state.json"
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")
ROOTS = ("/mnt/", "/var/lib/builderbot-controller", "/srv/")


def _env(k, d):
    return os.environ.get(k) or d


def _state():
    try:
        with open(_env("BB_BACKUPS_STATE", STATE_FILE), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _state_set(name, **kw):
    s = _state()
    s[name] = {**(s.get(name) or {}), **kw}
    path = _env("BB_BACKUPS_STATE", STATE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(s, f)
    os.replace(path + ".new", path)


def backups_now(state):
    """[{id, name, last_at, ok, error, size_mb, runs, took_s}] for the
    census: the record the hello left, each with its last run."""
    out = []
    st = _state()
    for r in state.get("store_backups") or []:
        if not isinstance(r, dict) or not NAME_RE.fullmatch(str(r.get("name") or "")):
            continue
        s = st.get(r["name"]) or {}
        out.append({"id": str(r.get("id") or "")[:16], "name": r["name"], "last_at": int(s.get("last_at") or 0), "ok": s.get("ok") is True,
                    "error": str(s.get("error") or "")[:200], "size_mb": int(s.get("size_mb") or 0), "runs": int(s.get("runs") or 0),
                    "took_s": int(s.get("took_s") or 0)})
    return out


def _du_mb(path):
    out = subprocess.run(["du", "-sm", path], capture_output=True, text=True, timeout=600, check=False).stdout
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return 0


class BackupsMixin:
    """Agent's backup jobs: one of the parts class Agent (agent.py) is made of."""

    def backups_want(self, rows):
        """The record as the hello hands it, kept in node.json for the job
        to look a name up in."""
        want = [{k: r.get(k) for k in ("id", "name", "source", "dest", "keep")} for r in rows
                if isinstance(r, dict) and NAME_RE.fullmatch(str(r.get("name") or ""))]
        if want != (self.state.get("store_backups") or []):
            self.state["store_backups"] = want
            save_state(self.state)

    def _apply_storage_backup(self, job, cfg):
        say = job.say
        rsync = shutil.which("rsync")
        if os.geteuid() != 0 or not rsync:
            say("refused: a backup is copied by rsync as root, and this agent is not root or has no rsync\n")
            return "failed", 77
        name = str(cfg.get("name") or "")
        rec = next((r for r in self.state.get("store_backups") or [] if r.get("name") == name), None)
        if not rec:
            say(f"refused: no backup called {name or 'nothing'} in the record this machine holds; the next hello brings it\n")
            return "failed", 66
        src, dest = str(rec.get("source") or ""), str(rec.get("dest") or "")
        keep = rec.get("keep") if isinstance(rec.get("keep"), int) and 1 <= rec.get("keep") <= 365 else 7
        for p in (src, dest):
            if not (os.path.isabs(p) and p.startswith(ROOTS) and ".." not in p.split("/")):
                say(f"refused: {p or 'nothing'} is not a folder under /mnt, /srv or the controller's state\n")
                return "failed", 64
        if not os.path.isdir(src):
            say(f"refused: the source {src} is not here (a disk not plugged in, a pool not imported)\n")
            _state_set(name, ok=False, error="the source is not here", last_at=int(time.time()))
            return "failed", 65
        if dest.startswith(src.rstrip("/") + "/") or src.startswith(dest.rstrip("/") + "/") or src.rstrip("/") == dest.rstrip("/"):
            say("refused: a backup goes somewhere other than inside its source\n")
            return "failed", 64
        top = os.path.dirname(dest.rstrip("/")) if dest.count("/") > 2 else dest
        if dest.startswith("/mnt/") and not any(os.path.ismount(m) for m in (dest, top, "/".join(dest.split("/")[:3]))):
            say(f"refused: nothing is mounted at {dest}: the disk is not plugged in or the share is not mounted, and a copy would land on the system disk\n")
            _state_set(name, ok=False, error="the destination is not mounted", last_at=int(time.time()))
            return "failed", 65
        runs_dir = os.path.join(dest, name)
        os.makedirs(runs_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        new, partial = os.path.join(runs_dir, stamp), os.path.join(runs_dir, stamp + ".partial")
        latest = os.path.join(runs_dir, "latest")
        argv = [rsync, "-aHAX", "--numeric-ids", "--delete", "--delete-excluded", "--exclude", ".snapraid.content", "--exclude", "lost+found",
                "--exclude", ".zfs", "--info=stats1,progress0"]
        if os.path.isdir(latest):
            argv += ["--link-dest", os.path.realpath(latest)]
        argv += [src.rstrip("/") + "/", partial + "/"]
        say(f"backup {name}: {src} to {new}{' (hard-linked to the run before)' if os.path.isdir(latest) else ''}\n")
        t0 = time.time()
        _state_set(name, running=True)
        try:
            rc = self._sh(job, argv, timeout=86400)
        finally:
            _state_set(name, running=False)
        if rc not in (0, 24):                              # 24: a file vanished while it was read, the copy whole otherwise
            shutil.rmtree(partial, ignore_errors=True)
            _state_set(name, ok=False, error=f"rsync exit {rc}", last_at=int(time.time()), took_s=int(time.time() - t0))
            return "failed", rc
        os.rename(partial, new)
        tmp = latest + ".new"
        try:
            os.unlink(tmp)
        except OSError:
            pass
        os.symlink(stamp, tmp)
        os.replace(tmp, latest)
        runs = sorted(d for d in os.listdir(runs_dir) if re.fullmatch(r"\d{8}-\d{6}", d))
        for old in runs[:max(0, len(runs) - keep)]:
            say(f"pruned {old}: past the {keep} kept\n")
            shutil.rmtree(os.path.join(runs_dir, old), ignore_errors=True)
        size = _du_mb(runs_dir)
        _state_set(name, ok=True, error="", last_at=int(time.time()), took_s=int(time.time() - t0), size_mb=size, runs=min(len(runs), keep))
        say(f"done: {name} at {new}, {len(runs[-keep:])} run(s) kept, {size} MB in all\n")
        log(f"backups: {name} done in {int(time.time() - t0)} s")
        self.hello_again(f"the backup {name} ran")
        return "succeeded", 0
