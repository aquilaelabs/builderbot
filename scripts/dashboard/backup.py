"""The configuration backed up and found again (R161 step 4): the same
bundle a move carries (move.pack: the state without its logs, the stores,
the secrets), sealed under a key the backup password derives, written after
every change to the state (a quiet quarter of an hour after the last) onto
every pool of the controller's own machine (/mnt/POOL/.builderbot/backup)
and under the state, the five newest kept in each, and downloadable. A new
install finds the copies on its pools at first run, takes the password and
becomes the controller as it was (move.restore with the key). Pushing a
copy to another BuilderBot or a node is the next piece.
"""
import base64
import contextlib
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

STATE = Path("/config")
LEAVE = {"logs", "ci-logs", "snapshots", "apps", "move", "backup", "csp-reports.json", "held.json", "clean-shutdown", "booted", "hold-next", "backup.json"}
KEEP = 5
QUIET_S = 15 * 60
EVERY_S = 10 * 60
SUFFIX = ".bbbackup"
_lock = threading.Lock()
_pack = lambda: (b"", {})       # noqa: E731 (configured: move.pack)
_seal = lambda data, key: data  # noqa: E731
_restore = lambda *a, **k: {}   # noqa: E731 (move.restore)
_manifest = lambda p: (None, "")  # noqa: E731 (move.read_manifest)
_password = lambda: ""          # noqa: E731 (the setting, sealed)
_dirs = lambda: []              # noqa: E731 (the own machine's pools' mounts)
_version = lambda: ""           # noqa: E731
_state_version = lambda: 0      # noqa: E731
_write_json = None
_host = lambda: ""              # noqa: E731


def configure(*, state, pack_fn, seal_fn, restore_fn, manifest_fn, password_fn, dirs_fn, version_fn, state_version_fn, write_json_fn, host_fn=None):
    globals().update(STATE=Path(state), _pack=pack_fn, _seal=seal_fn, _restore=restore_fn, _manifest=manifest_fn, _password=password_fn,
                     _dirs=dirs_fn, _version=version_fn, _state_version=state_version_fn, _write_json=write_json_fn, _host=host_fn or _host)


def key_from(password, salt):
    """The sealing key from the backup password: scrypt, so a copy on a disk
    somebody carries off is not opened by a guess in an afternoon."""
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, dklen=32, maxmem=256 << 20)


def _file():
    return STATE / "backup.json"


def _load():
    try:
        with open(_file(), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    if _write_json:
        _write_json(_file(), d)
    else:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump(d, f)


def where():
    """The folders a copy goes to: under the state, and on each pool."""
    out = [STATE / "backup"]
    for d in _dirs() or []:
        if d and str(d).startswith(("/mnt/", "/srv/")):
            out.append(Path(d) / ".builderbot" / "backup")
    return out


def _changed_since(at):
    """Whether anything under the state (its records, not its logs) was
    written after `at`, and when the newest was."""
    newest = 0
    for root, dirs, files in os.walk(STATE):
        rel = Path(root).relative_to(STATE)
        if rel.parts and rel.parts[0] in LEAVE:
            dirs[:] = []
            continue
        for f in files:
            if rel.parts == () and f in LEAVE:
                continue
            with contextlib.suppress(OSError):
                newest = max(newest, int(os.stat(os.path.join(root, f)).st_mtime))
    return newest > at, newest


def make(principal, why="asked"):
    """One copy, now, to every folder where(): {ok, name, size, where, made_at} or {error}."""
    pw = _password() or ""
    if len(pw) < 8:
        return {"error": "no backup password set (eight characters at least): Controller settings, Backup"}
    raw, counts = _pack()
    salt = secrets.token_bytes(16)
    sealed = _seal(raw, key_from(pw, salt))
    made_at = int(time.time())
    base = f"builderbot-backup-{_version() or 'unstamped'}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(made_at))}"
    name = base + SUFFIX
    n = 1
    while any((d / name).exists() for d in where()):
        n += 1
        name = f"{base}-{n}{SUFFIX}"
    manifest = {"format": 1, "kind": "backup", "version": _version(), "state_version": int(_state_version() or 0), "made_at": made_at,
                "salt": base64.b64encode(salt).decode(), "host": _host(), "counts": counts, "why": why, "by": str(principal)[:80]}
    body = move_header() + json.dumps(manifest).encode() + b"\n" + sealed
    written, failed = [], []
    for d in where():
        try:
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = d / (name + ".partial")
            with open(tmp, "wb") as f:
                f.write(body)
            os.chmod(tmp, 0o600)
            os.replace(tmp, d / name)
            olds = sorted(d.glob("*" + SUFFIX), key=lambda p: p.stat().st_mtime)
            for old in olds[:-KEEP]:
                old.unlink(missing_ok=True)
            written.append(str(d))
        except OSError as e:
            failed.append(f"{d}: {e.strerror or e}")
    if not written:
        return {"error": "the copy was written nowhere: " + "; ".join(failed)}
    with _lock:
        d = _load()
        d.update(made_at=made_at, name=name, size=len(body), where=written, failed=failed, why=why, by=str(principal)[:80])
        _save(d)
    return {"ok": True, "name": name, "size": len(body), "where": written, "failed": failed, "made_at": made_at}


def move_header():
    from move import BACKUP_HEADER
    return BACKUP_HEADER


def copies():
    """Every copy in every folder where(), newest first."""
    out = []
    for d in where():
        try:
            for p in d.glob("*" + SUFFIX):
                m, _ = _manifest(str(p))
                if m:
                    out.append({"where": str(d), "name": p.name, "size": p.stat().st_size, "made_at": int(m.get("made_at") or 0),
                                "version": str(m.get("version") or ""), "state_version": int(m.get("state_version") or 0)})
        except OSError:
            continue
    out.sort(key=lambda c: -c["made_at"])
    return out[:64]


def status():
    d = _load()
    return {"on": len(_password() or "") >= 8, "made_at": int(d.get("made_at") or 0), "name": d.get("name") or "", "size": int(d.get("size") or 0),
            "where": [str(w) for w in where()], "failed": d.get("failed") or [], "copies": copies()}


def found(dirs):
    """What a fresh install finds on its disks (R161 step 4): the copies
    under each pool's .builderbot/backup, newest first, with their versions,
    before anybody owns it."""
    out = []
    for d in dirs or []:
        base = Path(d) / ".builderbot" / "backup"
        try:
            for p in base.glob("*" + SUFFIX):
                m, _ = _manifest(str(p))
                if m:
                    out.append({"path": str(p), "name": p.name, "made_at": int(m.get("made_at") or 0), "version": str(m.get("version") or ""),
                                "state_version": int(m.get("state_version") or 0), "host": str(m.get("host") or "")})
        except OSError:
            continue
    out.sort(key=lambda c: -c["made_at"])
    return out[:32]


def restore(path, password, **kw):
    """The copy opened under the password and put in place of the state here,
    through move.restore's gate (never onto an older build)."""
    m, why = _manifest(path)
    if not m:
        return {"error": why}
    if m.get("kind") != "backup":
        return {"error": "that is a move bundle, which takes its token on the move page"}
    try:
        salt = base64.b64decode(str(m.get("salt") or ""))
    except ValueError:
        salt = b""
    if len(salt) != 16:
        return {"error": "the copy's manifest carries no salt"}
    return _restore(path, key=key_from(password or "", salt), **kw)


def start():
    """A copy after every change to the state, once it has been quiet for a
    quarter of an hour, looked at every ten minutes; nothing without the
    password set."""
    def loop():
        while True:
            time.sleep(EVERY_S)
            try:
                if len(_password() or "") < 8:
                    continue
                last = int(_load().get("made_at") or 0)
                changed, newest = _changed_since(last)
                if changed and time.time() - newest >= QUIET_S:
                    r = make("system:backup", "the state changed")
                    print(f"[dashboard] backup: {r.get('name') or r.get('error')}", flush=True)
            except Exception as e:                                  # noqa: BLE001 (the loop outlives one bad pass)
                print(f"[dashboard] backup: {type(e).__name__}: {e}", flush=True)
    threading.Thread(target=loop, name="backup", daemon=True).start()
