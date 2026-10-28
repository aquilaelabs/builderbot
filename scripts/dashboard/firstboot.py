"""A prepared configuration's first boot on the controller (R161 step 8).

The stick's root step (image/mkosi.extra/usr/lib/builderbot-os/firstboot-take)
takes builderbot/firstboot.json off the ESP before the controller starts and
hands it over at /run/builderbot-os/firstboot/firstboot.json with what it did
to the machine itself (the hostname, the time zone). At start this applies
the rest it can: the owner (a name and a password hash; none leaves the
first-run page to ask), the people (by name and role, their SMB password's
NT hash with them), and first_run: skip marks the setup page finished. What
needs disks adopted first (the shares, the pools, the array) and the apps
are kept for the piece that adopts them, said as waiting. The handed file is
removed; what is kept in /config/firstboot.json never holds the password
hash nor an SMB hash. This machine draws the report (view()).

Format 1:
    {"format": 1, "first_run": "skip" | "ask",
     "machine": {"hostname", "timezone", "network": {...}},
     "owner": {"name", "password_hash"},
     "people": [{"name", "role", "smb_nt"}],
     "shares": [...], "pools": [...], "array": {...}, "apps": [...]}
"""
import json
import os
import time
from pathlib import Path

RUN = Path(os.environ.get("BB_FIRSTBOOT_RUN", "/run/builderbot-os/firstboot/firstboot.json"))
STATE = None
write_json = users = settings = None
WAITS = {"shares": "a share is served from a pool or the array, adopted first",
         "pools": "the pools are adopted from This machine's Storage, a later piece",
         "array": "the array is adopted by its disks' serials, a later piece",
         "apps": "an app is a container made from New container once its folders' disks are here"}


def configure(*, state, write_json_fn, users_mod, settings_mod):
    globals().update(STATE=Path(state), write_json=write_json_fn, users=users_mod, settings=settings_mod)


def _file():
    return STATE / "firstboot.json"


def apply(path=None):
    """Apply what the stick's first boot handed over, once. The report, or
    None when nothing was handed over."""
    path = Path(path or RUN)
    try:
        handed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cfg = handed.get("config") if isinstance(handed, dict) else None
    done, waiting, failed = [], [], []
    for k, v in ((handed or {}).get("machine") or {}).items():
        (done if v == "applied" else failed).append({"what": k, "said": v})
    if isinstance(cfg, dict):
        owner = cfg.get("owner") or {}
        if owner.get("password_hash"):
            r = users.adopt(owner, cfg.get("people") or [])
            if r.get("error"):
                failed.append({"what": "accounts", "said": r["error"]})
            else:
                done.append({"what": "accounts", "said": ", ".join(r["made"])})
                failed += [{"what": f"account {n or '(no name)'}", "said": why} for n, why in r["skipped"]]
                if cfg.get("first_run") == "skip":
                    settings.set_many({"setup_done": True})
                    done.append({"what": "first run", "said": "skipped: the owner signs in"})
        else:
            waiting.append({"what": "accounts", "said": "no owner's password came with it: the first-run page makes the owner"})
        for k, why in WAITS.items():
            if cfg.get(k):
                waiting.append({"what": k, "said": why, "count": len(cfg[k]) if isinstance(cfg[k], list) else 1})
        net = (cfg.get("machine") or {}).get("network")
        if net and net != "dhcp":
            waiting.append({"what": "network", "said": "the stick's network settings are written by the Network page; it takes DHCP until then"})
        # Kept for the pieces that adopt the rest, the password hash and the
        # SMB hashes taken out: those are on the accounts, and nowhere else.
        kept = {k: v for k, v in cfg.items() if k not in ("owner", "people")}
        kept["owner"] = {"name": owner.get("name", "")} if owner else {}
        kept["people"] = [{"name": p.get("name", ""), "role": p.get("role", "user")} for p in cfg.get("people") or [] if isinstance(p, dict)]
    else:
        kept = None
        failed.append({"what": "file", "said": "the prepared configuration could not be read"})
    report = {"at": int(time.time()), "done": done, "waiting": waiting, "failed": failed, "config": kept}
    write_json(_file(), report)
    try:
        path.unlink()
    except OSError:
        pass
    return report


def view():
    """This machine's section: what the stick's prepared configuration did,
    or None when this install had none."""
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: d.get(k) for k in ("at", "done", "waiting", "failed")}
