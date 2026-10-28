"""Other disks and shares on the controller's own machine (R162 step 4):
the hello hands the record (a USB or eSATA disk by its by-id link, an SMB
share, an NFS export, each with a name and whether it is on), and this
mounts each at /mnt/other/NAME when it is on and its source is here, and
unmounts what is off or gone from the record, every hello; a disk turned
off is unmounted so it is safe to pull. An SMB share's password goes in a
root-only credentials file and nowhere else. The census says what is
mounted, present and how full.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

from .base import log
from .stores import save_state

ROOT = "/mnt/other"
CREDS = "/etc/builderbot/creds"
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")


def _env(k, d):
    return os.environ.get(k) or d


def _mounted(path):
    return os.path.ismount(path)


def _df(path):
    try:
        st = os.statvfs(path)
        return st.f_frsize * st.f_blocks // 1048576, st.f_frsize * (st.f_blocks - st.f_bavail) // 1048576
    except OSError:
        return 0, 0


def disk_dev(source):
    """The device for a disk's by-id link: its first partition's link
    where one exists (a disk with a table), else the disk's own."""
    root = _env("BB_BY_ID", "/dev/disk/by-id")
    for cand in (f"{root}/{source}-part1", f"{root}/{source}"):
        if os.path.exists(cand):
            return cand
    return ""


def extmounts_now(state):
    """[{id, name, kind, mounted, present, size_mb, used_mb, error}] for the
    census, from the record the hello left in node.json."""
    out = []
    for m in state.get("ext_mounts") or []:
        if not isinstance(m, dict) or not NAME_RE.fullmatch(str(m.get("name") or "")):
            continue
        path = f"{_env('BB_OTHER_ROOT', ROOT)}/{m['name']}"
        mounted = _mounted(path)
        present = bool(disk_dev(str(m.get("source") or ""))) if m.get("kind") == "disk" else True
        size, used = _df(path) if mounted else (0, 0)
        out.append({"id": str(m.get("id") or "")[:16], "name": m["name"], "kind": str(m.get("kind") or "")[:4], "mounted": mounted, "present": present,
                    "size_mb": size, "used_mb": used, "error": str((state.get("ext_errors") or {}).get(m.get("id"), ""))[:200]})
    return out


class ExtMountsMixin:
    """Agent's other mounts: one of the parts class Agent (agent.py) is made of."""

    def ext_mounts_want(self, rows):
        """The record as the hello hands it, reconciled: each on and here
        mounted, each off or gone unmounted; once per change of the record
        and once a minute for a disk that arrives or leaves (ext_mounts_pass)."""
        want = [r for r in rows if isinstance(r, dict) and NAME_RE.fullmatch(str(r.get("name") or "")) and r.get("kind") in ("disk", "smb", "nfs")]
        sig = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()
        changed = sig != self.state.get("ext_mounts_sig")
        if changed:
            self.state["ext_mounts"] = [{k: r.get(k) for k in ("id", "kind", "name", "source", "host", "path", "user", "ro", "on")} for r in want]
            self.state["ext_mounts_sig"] = sig
            self._ext_creds(want)
            save_state(self.state)
        self.ext_mounts_pass(force=changed)

    def _ext_creds(self, want):
        """An SMB share's credentials file, root's alone; the files of shares
        gone removed."""
        root = _env("BB_CREDS", CREDS)
        os.makedirs(root, mode=0o700, exist_ok=True)
        keep = set()
        for r in want:
            if r.get("kind") != "smb":
                continue
            path = os.path.join(root, r["name"])
            keep.add(r["name"])
            text = f"username={r.get('user') or 'guest'}\npassword={r.get('password') or ''}\n"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
        for f in os.listdir(root):
            if f not in keep:
                try:
                    os.unlink(os.path.join(root, f))
                except OSError:
                    pass

    def ext_mounts_pass(self, force=False):
        """Once a minute: a disk that arrived mounted, one that left said
        gone; with `force`, every mount brought to the record."""
        if os.geteuid() != 0:
            return
        rows = self.state.get("ext_mounts") or []
        root = _env("BB_OTHER_ROOT", ROOT)
        errors = dict(self.state.get("ext_errors") or {})
        wanted_names = set()
        for m in rows:
            name, path = m.get("name"), f"{root}/{m.get('name')}"
            wanted_names.add(name)
            if not m.get("on"):
                if _mounted(path):
                    self._ext_umount(path, m, errors)
                continue
            if _mounted(path):
                continue
            argv = self._ext_argv(m, path)
            if not argv:
                continue
            os.makedirs(path, exist_ok=True)
            p = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            if p.returncode == 0:
                errors.pop(m.get("id"), None)
                log(f"other mounts: {name} mounted ({m.get('kind')})")
            else:
                why = (p.stderr or p.stdout or f"exit {p.returncode}").strip()[:200]
                if errors.get(m.get("id")) != why:
                    log(f"other mounts: {name} did not mount: {why}")
                errors[m.get("id")] = why
        # What the record no longer names, unmounted and its folder gone.
        try:
            for name in os.listdir(root):
                if name not in wanted_names and NAME_RE.fullmatch(name):
                    path = f"{root}/{name}"
                    if _mounted(path):
                        self._ext_umount(path, {"name": name, "id": ""}, errors)
                    if not _mounted(path):
                        with __import__("contextlib").suppress(OSError):
                            os.rmdir(path)
        except OSError:
            pass
        if errors != (self.state.get("ext_errors") or {}):
            self.state["ext_errors"] = errors
            save_state(self.state)

    def _ext_argv(self, m, path):
        kind = m.get("kind")
        ro = ["-o", "ro"] if m.get("ro") else []
        if kind == "disk":
            dev = disk_dev(str(m.get("source") or ""))
            return [shutil.which("mount") or "mount", *ro, dev, path] if dev else None
        if kind == "smb":
            creds = os.path.join(_env("BB_CREDS", CREDS), m["name"])
            opts = f"credentials={creds},uid=0,gid=0,file_mode=0664,dir_mode=0775,vers=3.0,soft" + (",ro" if m.get("ro") else "")
            return [shutil.which("mount") or "mount", "-t", "cifs", f"//{m.get('host')}/{m.get('path')}", path, "-o", opts]
        if kind == "nfs":
            opts = "nfsvers=4,soft,timeo=100" + (",ro" if m.get("ro") else "")
            return [shutil.which("mount") or "mount", "-t", "nfs", f"{m.get('host')}:{m.get('path')}", path, "-o", opts]
        return None

    def _ext_umount(self, path, m, errors):
        p = subprocess.run([shutil.which("umount") or "umount", path], capture_output=True, text=True, timeout=120, check=False)
        if p.returncode != 0:
            # Busy: lazily, so the record's word holds and the files close by themselves.
            subprocess.run([shutil.which("umount") or "umount", "-l", path], capture_output=True, timeout=60, check=False)
        errors.pop(m.get("id"), None)
        log(f"other mounts: {m.get('name')} unmounted")
