"""The files a release must carry, checked on the forge once CI has had its
time (R190 step 4): a project lists them in `.release-files` at its root,
one name a line with @VER@ for the release's version, and a release whose
page is short of one is a red row on the bell naming the file and why. The
0.9.0 dev release went out with no APK and nothing said so until somebody
looked (the operator, 30 Oct).

The list is read at the release's own tag, so a later commit changing it
does not change what an older release is held to. `*` matches as a shell
pattern does. A release is checked once WAIT_S has passed since its tag was
pushed (CI's builds: the OS image alone is over an hour), then every
TICK_S until it is whole or GIVE_UP_S has passed; a row stays until it is
whole or put away.

    configure(state=, workspace=, write_json_fn=)
    wanted(project, tag)   the names the release must carry, or []
    expect(project, tag)   a release's tag just pushed: check it later
    check(project)         check the expected releases that are due
    attention(projects)    the bell's rows
    start()                the loop
"""
import fnmatch
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import forgerelease
import releasesign

STATE = Path("/config")
WORKSPACE = Path("/workspace")
write_json = None

MANIFEST = ".release-files"
WAIT_S = int(os.environ.get("BB_RELEASEFILES_WAIT", str(3 * 3600)))
GIVE_UP_S = 3 * 86400
TICK_S = int(os.environ.get("BB_RELEASEFILES_TICK", "600"))
_lock = threading.Lock()


def configure(*, state, workspace, write_json_fn):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), write_json=write_json_fn)


def _file():
    return STATE / "release-files.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    if write_json:
        write_json(_file(), d)


def wanted(project, tag):
    """The names `tag`'s release must carry, from the list at that tag (at
    HEAD when the tag is not here yet), @VER@ filled in; [] with no list."""
    root = WORKSPACE / project
    text = ""
    for ref in (tag, "HEAD"):
        try:
            r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{MANIFEST}"],
                               capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode == 0:
            text = r.stdout
            break
    ver = tag.rsplit("-v", 1)[-1] if "-v" in tag and not tag.startswith("v") else tag.removeprefix("v")
    return [ln.strip().replace("@VER@", ver) for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")][:100]


def expect(project, tag):
    """A release's tag was pushed: its files are checked once CI has had
    WAIT_S to build and attach them."""
    if not wanted(project, tag):
        return
    with _lock:
        d = _load()
        d.setdefault(project, {})[tag] = {"at": int(time.time())}
        _save(d)


def _why(project, tag, name):
    """Why one file is not there, as far as the controller can tell."""
    if name.endswith(".apk"):
        f = ((releasesign._load().get(project) or {}).get("failed") or {}).get(tag)
        if isinstance(f, dict) and f.get("why"):
            return f"the controller could not sign it: {f['why']}"
        return f"the controller has not signed it: bb sign status {tag} says why, bb sign release looks again"
    return "CI did not attach it: bb ci-log reads the release's run"


def missing(project, tag):
    """(names missing, release url) of `tag` on the forge, or raises
    forgerelease.Refused."""
    kind, name, ctx = forgerelease._handle(project)
    url, have = forgerelease._files_on(kind, name, ctx, tag)
    return [w for w in wanted(project, tag) if not fnmatch.filter(have, w)], url


def check(project, now=None):
    """Check each expected release of the project that is due."""
    now = int(now or time.time())
    with _lock:
        recs = dict(_load().get(project) or {})
    for tag, rec in recs.items():
        if not isinstance(rec, dict) or now - int(rec.get("at") or 0) < WAIT_S:
            continue
        if rec.get("done") or now - int(rec.get("at") or 0) > GIVE_UP_S:
            continue
        try:
            gone, url = missing(project, tag)
            rec.update(checked=now, url=url, gone=[{"name": n, "why": _why(project, tag, n)} for n in gone],
                       error="")
        except forgerelease.Refused as e:
            rec.update(checked=now, error=str(e))
        if not rec.get("gone") and not rec.get("error"):
            rec["done"] = now
        with _lock:
            d = _load()
            if tag in (d.get(project) or {}):
                d[project][tag] = rec
                _save(d)


def attention(projects):
    """The bell's rows, kind release-files: a release short of a file it
    must carry, red, each keyed on what is missing so a row put away comes
    back only when that changes."""
    out, whole = [], _load()
    for p in projects:
        for tag, rec in (whole.get(p) or {}).items():
            if not isinstance(rec, dict) or rec.get("done") or not (rec.get("gone") or rec.get("error")):
                continue
            gone = rec.get("gone") or []
            why = "; ".join(f"{g['name']}: {g['why']}" for g in gone) or f"it could not be read: {rec['error']}"
            h = hashlib.sha256(why.encode()).hexdigest()[:10]
            out.append({"kind": "release-files", "id": f"{p}|{tag}", "project": p, "tag": tag, "bad": True,
                        "files": [g["name"] for g in gone], "why": why, "url": rec.get("url") or "",
                        "at": int(rec.get("checked") or 0), "key": f"rfiles:{p}|{tag}@{h}"})
    return out


def start():
    """Every TICK_S, each project with a release expected. A daemon thread."""
    def loop():
        while True:
            time.sleep(TICK_S)
            for p in list(_load()):
                try:
                    check(p)
                except Exception as e:                              # noqa: BLE001 (a loop must not die)
                    print(f"dashboard: release files {p}: {e}", flush=True)
    threading.Thread(target=loop, name="releasefiles", daemon=True).start()
