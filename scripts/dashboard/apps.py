"""The apps a person installs, shipped with every controller and kept current
by it (R272 steps 3 and 4): the Android app, the VS Code extension and the
Windows companion, each built for every release and attached to it with its
sha256 (the android app and companion app workflows).

Which of them this controller offers is chosen on the Settings page (the
apps_* switches, settings.py), or by the seed file a generator writes beside
a compose file, read once on the first boot and then put aside. At boot and
once a day the controller fetches each offered app from the release that
matches its own version (the newest release when none does, and says so),
checks it against its sha256 file, keeps it under /config/apps, and serves
it at /apps/NAME/FILE to anybody signed in and to a device's app, which is
how the companion keeps itself current (R270 step 9). Nothing here runs a
file it fetched.

    configure(state=, version=, setting=, write_json=, audit=)
    view()                     the Settings and Apps pages' reading
    check_now()                look again, in the background
    path(name, file)           a held file's path, or None
    start()                    the boot look and the daily one
    seed()                     apply /config/seed.json once
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

# The releases are BuilderBot's own on GitHub; a test points this at a file.
RELEASES_URL = (os.environ.get("BB_APPS_RELEASES_URL")
                or "https://api.github.com/repos/aquilaelabs/builderbot/releases")
BOOT_DELAY = float(os.environ.get("BB_APPS_BOOT_DELAY") or 30)
EVERY = 24 * 3600
TIMEOUT = 60
MAX_BYTES = 200 << 20

# name -> what the pages say of it, and the files a release carries for it
# (a prefix and a suffix around the version). The first file is the one a
# person downloads; the rest go beside it.
APPS = {
    "android": {"title": "Android app", "setting": "apps_android",
                "does": "The notebook, the bell and your sessions on a phone, and the phone lent to a project.",
                "files": [("builderbot-app-", ".apk")]},
    "vscode": {"title": "VS Code extension", "setting": "apps_vscode",
               "does": "A project's files and its terminal in VS Code, opened from the controller.",
               "files": [("builderbot-vscode-", ".vsix")]},
    "companion": {"title": "Windows companion", "setting": "apps_companion",
                  "does": "A folder on a Windows PC kept in step with a project both ways, for a tool that only runs there.",
                  "files": [("builderbot-companion-", ".exe"), ("builderbot-companion-", ".pyz")]},
}
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,120}$")

# Each set by configure(); the defaults are the container's own paths.
DIR = Path("/config") / "apps"
SEED = Path("/config") / "seed.json"
INDEX = DIR / "index.json"


def _version():
    return ""


def _setting(key):
    return True


def write_json(path, data):
    raise RuntimeError("apps.configure() was not called")


audit = None
_lock = threading.Lock()
_state = {"checking": False}


def _token():
    return ""


def configure(*, state, version, setting, write_json, audit=None, token=None):
    globals().update(DIR=Path(state) / "apps", SEED=Path(state) / "seed.json", _version=version,
                     _setting=setting, write_json=write_json, audit=audit)
    if token:
        globals()["_token"] = token
    globals()["INDEX"] = DIR / "index.json"


def offered(name):
    return bool(_setting(APPS[name]["setting"]))


def _index():
    try:
        with open(INDEX) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def base_version(v):
    """The release a build belongs to: 0.7.0 of 0.7.0-dev.3160+a1269ff."""
    m = re.match(r"v?(\d+\.\d+\.\d+)", str(v or ""))
    return m.group(1) if m else ""


def view():
    """{apps: [...], checked, problem, release, matched, checking, version}:
    each app with whether it is offered, the files held of it and their
    sha256, for the Settings section and the Apps page."""
    idx = _index()
    held = idx.get("apps") or {}
    out = []
    for name, a in APPS.items():
        h = held.get(name) or {}
        out.append({"name": name, "title": a["title"], "does": a["does"], "offered": offered(name),
                    "version": h.get("version", ""),
                    "files": [{"file": f["file"], "sha256": f["sha256"], "size": f["size"],
                               "url": f"/apps/{name}/{f['file']}"}
                              for f in h.get("files") or []]})
    return {"apps": out, "checked": idx.get("checked", 0), "problem": idx.get("problem", ""),
            "release": idx.get("release", ""), "matched": bool(idx.get("matched")),
            "checking": _state["checking"], "version": _version()}


def path(name, file):
    """A held file's path, or None: only a name the index holds, so a
    request can never name anything else under /config."""
    if name not in APPS or not SAFE.match(str(file or "")):
        return None
    for f in ((_index().get("apps") or {}).get(name) or {}).get("files") or []:
        if f.get("file") == file:
            p = DIR / name / file
            return p if p.is_file() else None
    return None


def _get(url, limit=MAX_BYTES, accept="application/octet-stream, application/json"):
    headers = {"Accept": accept, "User-Agent": "builderbot-apps"}
    # The token only to GitHub's API, where a private repository's releases
    # and their files are read with it; never to wherever a file redirects.
    if _token() and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + _token()
    req = urllib.request.Request(url, headers=headers)
    with _OPENER.open(req, timeout=TIMEOUT) as r:                   # noqa: S310 (our releases, or a test's file)
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"more than {limit >> 20} MB")
    return body


class _NoTokenAway(urllib.request.HTTPRedirectHandler):
    """A redirect to another host goes without the token: GitHub sends a
    file to signed storage, which refuses a request carrying both."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_OPENER = urllib.request.build_opener(_NoTokenAway)


def _pick(releases, want):
    """The release for version `want`, else the newest that is published;
    (release, whether it matched)."""
    live = [r for r in releases if isinstance(r, dict) and not r.get("draft")]
    for r in live:
        if base_version(r.get("tag_name")) == want and want:
            return r, True
    return (live[0], False) if live else (None, False)


def _asset(rel, prefix, suffix):
    for a in rel.get("assets") or []:
        n = str(a.get("name") or "")
        if n.startswith(prefix) and n.endswith(suffix) and SAFE.match(n):
            return a
    return None


def check():
    """Fetch each offered app from the matching release, check it, keep it,
    and drop what is no longer offered. Writes the index; returns view()."""
    idx = _index()
    held = idx.get("apps") or {}
    err, rel, matched = "", None, False
    try:
        releases = json.loads(_get(RELEASES_URL, 8 << 20))
        rel, matched = _pick(releases if isinstance(releases, list) else [], base_version(_version()))
        if not rel:
            err = "no published release to take the apps from"
    except (OSError, ValueError) as e:
        err = f"the releases did not answer: {e}"
        if "404" in str(e) and not _token():
            err += (" (a private repository answers 404 to anybody without a token: an administrator adds one "
                    "under Apps on the Controller page)")
    DIR.mkdir(parents=True, exist_ok=True)
    for name, a in APPS.items():
        if not offered(name):
            shutil.rmtree(DIR / name, ignore_errors=True)
            held.pop(name, None)
            continue
        if not rel:
            continue
        files, missing = [], []
        for prefix, suffix in a["files"]:
            asset = _asset(rel, prefix, suffix)
            if not asset:
                missing.append(f"{prefix}*{suffix}")
                continue
            sums = {str(x.get("name")): x for x in rel.get("assets") or []}
            sha_asset = sums.get(asset["name"] + ".sha256")
            if not sha_asset:
                missing.append(f"{asset['name']}.sha256")
                continue
            got = _keep(name, asset, sha_asset, held.get(name) or {})
            if isinstance(got, str):
                missing.append(got)
            else:
                files.append(got)
        if files:
            keep = {f["file"] for f in files}
            for old in (DIR / name).iterdir() if (DIR / name).is_dir() else []:
                if old.name not in keep:
                    old.unlink(missing_ok=True)
            held[name] = {"version": base_version(rel.get("tag_name")) or str(rel.get("tag_name") or ""),
                          "files": files, "at": int(time.time())}
        if missing and not err:
            err = f"{a['title']}: {', '.join(missing)} not in {rel.get('tag_name')}"
    idx = {"apps": held, "checked": int(time.time()), "problem": err,
           "release": str((rel or {}).get("tag_name") or idx.get("release") or ""), "matched": matched}
    write_json(INDEX, idx)
    return view()


def _keep(name, asset, sha_asset, was):
    """One file of an app: kept as it is when the sha256 has not moved,
    else downloaded and checked. Its index entry, or a sentence."""
    try:
        want = _get(_where(sha_asset), 4096).decode("ascii", "replace").split()[0].lower()
    except (OSError, ValueError, IndexError, KeyError) as e:
        return f"{sha_asset.get('name')} ({e})"
    if not re.fullmatch(r"[0-9a-f]{64}", want):
        return f"{sha_asset.get('name')} is not a sha256"
    dest = DIR / name / asset["name"]
    for f in was.get("files") or []:
        if f.get("file") == asset["name"] and f.get("sha256") == want and dest.is_file():
            return f
    try:
        body = _get(_where(asset))
    except (OSError, ValueError, KeyError) as e:
        return f"{asset['name']} ({e})"
    if hashlib.sha256(body).hexdigest() != want:
        return f"{asset['name']} does not match its sha256"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, dest)
    return {"file": asset["name"], "sha256": want, "size": len(body)}


def _where(asset):
    """Where a release's file is read from: its API address with the token
    (the one way into a private repository's files), else its download
    link."""
    return asset["url"] if _token() and asset.get("url") else asset["browser_download_url"]


def check_now():
    """Look again in the background; False when a look is already going."""
    with _lock:
        if _state["checking"]:
            return False
        _state["checking"] = True

    def run():
        try:
            check()
        except Exception as e:              # noqa: BLE001 (said on the section)
            write_json(INDEX, {**_index(), "checked": int(time.time()), "problem": f"{type(e).__name__}: {e}"})
        finally:
            _state["checking"] = False
    threading.Thread(target=run, daemon=True, name="apps-check").start()
    return True


def start():
    """The look at boot, a while after it, and then once a day."""
    def loop():
        time.sleep(BOOT_DELAY)
        while True:
            check_now()
            time.sleep(EVERY)
    threading.Thread(target=loop, daemon=True, name="apps-loop").start()


# ---- the seed file (R272 step 4) -------------------------------------------
#
# /config/seed.json, written by a compose generator beside the compose file:
#
#     {"version": 1, "apps": ["android", "companion"]}
#
# Read once, on the first boot that finds it: each app named is offered and
# each one left out is not. It is then renamed seed.json.applied, so Settings
# owns the choice from there and a later edit of the file changes nothing.

def seed(set_many):
    """Apply the seed file once; what it set, or {} when there was none."""
    try:
        d = json.loads(SEED.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        return {"error": f"seed.json not read: {e}"}
    if not isinstance(d, dict):
        return {"error": "seed.json is not an object"}
    changes = {}
    if isinstance(d.get("apps"), list):
        names = {str(x) for x in d["apps"]}
        changes = {a["setting"]: name in names for name, a in APPS.items()}
        set_many(changes)
    try:
        os.replace(SEED, SEED.with_name("seed.json.applied"))
    except OSError:
        pass
    if audit:
        audit("controller", "seed", "seed.json", changes)
    return changes
