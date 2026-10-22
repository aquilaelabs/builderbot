"""A release's Android APK signed by BuilderBot with the project's own
sideload key, not in CI (R106, the operator 22 Oct: four keystore secrets
set by hand on GitHub failed three ways, and one put a password in a public
log).

The project's workflow builds an UNSIGNED release APK and hands it over as a
workflow artifact named `bb-release-apk-TAG` (kept a few days, never on the
release). The controller, which made the release, watches for that artifact:
it fetches it with the project's GitHub token, signs each APK in it here as
`bb sign` does (signing.sign_here: zipalign, apksigner with the proof of a
rotation, verify, the certificate checked against the kept key), and
attaches it to the release under its name less `-unsigned`, with its sha256
file and a line in the notes giving the key and its certificate's SHA-256
fingerprint. No keystore, alias or password is ever a GitHub secret, and the
key never leaves the controller.

What would stop a release's signing is said on the bell before the release
(attention(): no sideload key, an app mapped to none of several, no
apksigner here), and a signing that failed after one is said there too, red,
until it succeeds or is put away. The Signing view names which key signs
the releases (status()).

    configure(state=, workspace=, write_json_fn=, projects=)
    wants(project)        whether its workflows hand over an unsigned APK
    readiness(project)    {wanted, packages, keys, why}
    status(project)       readiness and the newest results, for the view
    expect(project, tag)  a release just made: look for its APK soon
    check(project, force) look now; sign and attach what is waiting
    attention(projects)   the bell's rows
    start()               the loop

GitHub only: a Gitea or GitLab workflow's artifacts are asked for another
way, and nothing here asks them.
"""
import calendar
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import cilogs
import forgerelease
import signing

STATE = Path("/config")
WORKSPACE = Path("/workspace")
write_json = None
projects_fn = None

# The artifact's name, a tag after it: what a workflow writes to be signed.
MARK = "bb-release-apk-"
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}")
APK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,150}\.apk")
# How long an expected release is looked for every few minutes, and how
# often otherwise: the artifact is kept three days, so a run older than that
# has nothing left to fetch.
EXPECT_S = 12 * 3600
SCAN_S = 3600
TICK_S = int(os.environ.get("BB_RELEASESIGN_TICK", "120"))
RUN_AGE_S = 3 * 86400
MAX_ZIP = 400 << 20
NOTE = "Signed by BuilderBot:"
_lock = threading.Lock()
_busy = set()
_cache = {}
_bare = set()        # (project, run id): finished runs that handed over no APK


def configure(*, state, workspace, write_json_fn, projects=None):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), write_json=write_json_fn,
                     projects_fn=projects)
    _cache.clear()
    _bare.clear()


def _file():
    return STATE / "release-signing.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _mine(d, project):
    rec = d.setdefault(project, {})
    for k in ("expect", "signed", "failed", "runs"):
        if not isinstance(rec.get(k), dict):
            rec[k] = {}
    return rec


def _save(d):
    if write_json:
        write_json(_file(), d)
    _cache.clear()


# ---- what the project asks for ----------------------------------------------

def wants(project):
    """Whether any of the project's workflows hands over an unsigned APK for
    the controller to sign (writes an artifact named bb-release-apk-...)."""
    d = WORKSPACE / project / ".github" / "workflows"
    try:
        flows = [f for f in d.iterdir() if f.is_file() and f.suffix in (".yml", ".yaml")]
    except OSError:
        return False
    for f in flows:
        try:
            if MARK in f.read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


APP_ID = re.compile(r"""applicationId\s*(?:=\s*)?["']([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+)["']""")


def packages(project):
    """The applicationIds the tree's Gradle files declare, which is what a
    release's APK will say it is: [package]."""
    root = WORKSPACE / project
    found = []
    for pat in ("build.gradle*", "*/build.gradle*", "*/*/build.gradle*"):
        for f in sorted(root.glob(pat)):
            if ".git" in f.parts or "node_modules" in f.parts:
                continue
            try:
                found += APP_ID.findall(f.read_text(errors="replace")[:400_000])
            except OSError:
                continue
    return sorted(set(found))


def _stamp(project):
    """What a readiness depends on that changes by a file coming or going:
    the workflows directory and the project's signing directories."""
    out = []
    for d in [WORKSPACE / project / ".github" / "workflows", signing.STATE / "signing" / project]:
        try:
            out.append(d.stat().st_mtime_ns)
            if d.name == project:
                out += sorted(x.stat().st_mtime_ns for x in d.iterdir() if x.is_dir())
        except (OSError, TypeError):
            out.append(0)
    return tuple(out)


def readiness(project, fresh=False):
    """{wanted, packages, keys: [{package, key, sha256}], why}: which key
    signs each app's release, or what keeps one from being signed. Kept for
    the bell's poll half a minute, or until a workflow or a key comes or
    goes; `fresh` asks again."""
    stamp = _stamp(project)
    hit = _cache.get(("ready", project))
    if not fresh and hit and hit[2] == stamp and time.time() - hit[0] < 30:
        return hit[1]
    out = {"wanted": wants(project), "packages": [], "keys": [], "why": ""}
    if out["wanted"]:
        out["packages"] = packages(project)
        for pkg in out["packages"] or [""]:
            key, rec, why = signing.release_key(project, pkg)
            if why:
                out["why"] = why
                break
            out["keys"].append({"package": pkg, "key": key, "sha256": rec.get("sha256") or "",
                                "rotated_from": rec.get("rotated_from") or ""})
        if not out["why"] and not signing.build_tools():
            out["why"] = ("this controller has no apksigner to sign its releases with: install "
                          "android-tools and the jdk (Toolchains page)")
        if not out["why"] and not cilogs.repo_of(project):
            out["why"] = (f"{project} is not on GitHub, which is the one forge whose workflow "
                          "artifacts the controller fetches to sign")
    _cache[("ready", project)] = (time.time(), out, stamp)
    return out


def status(project):
    """What the Signing view says of releases: readiness, and the newest
    signed and failed, newest first."""
    rec = _load().get(project) or {}
    newest = lambda d: sorted(({"tag": t, **v} for t, v in (d or {}).items() if isinstance(v, dict)),
                              key=lambda x: -int(x.get("at") or 0))[:5]
    return readiness(project, fresh=True) | {"signed": newest(rec.get("signed")), "failed": newest(rec.get("failed"))}


# ---- GitHub -----------------------------------------------------------------

def _download(repo, aid, token, into):
    """An artifact's zip into the file `into`. GitHub answers with a redirect
    to its storage host, which is never handed the token."""
    path = f"/repos/{repo}/actions/artifacts/{int(aid)}/zip"
    if not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/artifacts/\d+/zip", path):
        raise cilogs.Refused("not a path this asks GitHub for")
    req = urllib.request.Request(cilogs.API + path, headers={"User-Agent": "BuilderBot",
                                                             "Accept": "application/vnd.github+json"})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        # The host is cilogs' literal API and the path is checked above.
        with urllib.request.urlopen(req, timeout=600) as r, open(into, "wb") as f:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            n = 0
            while chunk := r.read(1 << 20):
                n += len(chunk)
                if n > MAX_ZIP:
                    raise cilogs.Refused("the artifact is larger than an APK's zip should be")
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise cilogs.Refused("GitHub refused the token for the run's artifact: it needs Actions: read") from e
        if e.code == 410:
            raise cilogs.Refused("GitHub no longer keeps the run's artifact: run the workflow again") from e
        raise cilogs.Refused(f"GitHub answered {e.code} for the run's artifact") from e
    except (urllib.error.URLError, OSError) as e:
        raise cilogs.Refused(f"could not fetch the run's artifact: {e}") from e


def _waiting(project, repo, token):
    """[(run, artifact id, tag)] of the recent runs that passed and handed
    over an unsigned APK."""
    j = cilogs._get(f"/repos/{repo}/actions/runs?per_page=30&status=success", token)
    out = []
    for r in (j.get("workflow_runs") or [])[:30]:
        rid = int(r.get("id") or 0)
        at = str(r.get("created_at") or "")
        try:
            t = calendar.timegm(time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            t = 0
        if not rid or (t and time.time() - t > RUN_AGE_S) or (project, rid) in _bare:
            continue
        arts = cilogs._get(f"/repos/{repo}/actions/runs/{rid}/artifacts?per_page=50", token)
        found = False
        for a in (arts.get("artifacts") or [])[:50]:
            name = str(a.get("name") or "")
            tag = name[len(MARK):]
            if name.startswith(MARK) and TAG.fullmatch(tag) and not a.get("expired"):
                out.append((rid, int(a.get("id") or 0), tag))
                found = True
        # A finished run's artifacts do not change: one that handed over
        # nothing is not asked about again (a look every few minutes for a
        # release's twelve hours would otherwise ask about thirty runs each).
        if not found:
            _bare.add((project, rid))
    return out


def _attach(project, repo, token, tag, files, lines):
    """Each (name, path) onto the release for `tag` with its sha256 file, one
    of the same name replaced, and the notes' signing lines put in place of
    any earlier ones. The release's address."""
    base = f"{forgerelease.API}/repos/{repo}/releases"
    rel = forgerelease._req("GET", f"{base}/tags/{urllib.parse.quote(tag)}", token)
    if not rel:
        raise forgerelease.Refused(f"there is no release for {tag} on GitHub to attach the APK to")
    have = {a.get("name"): a for a in rel.get("assets") or []}
    for name, path in files:
        data = Path(path).read_bytes()
        sums = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
        for n, body, ctype in ((name, data, "application/vnd.android.package-archive"),
                               (f"{name}.sha256", sums, "text/plain")):
            if n in have:
                forgerelease._req("DELETE", f"{base}/assets/{int(have[n]['id'])}", token)
            forgerelease._req("POST", f"{forgerelease.UPLOADS}/repos/{repo}/releases/{int(rel['id'])}/assets"
                                      f"?name={urllib.parse.quote(n)}", token, data=body, ctype=ctype)
    kept = [ln for ln in str(rel.get("body") or "").rstrip().splitlines() if not ln.startswith(NOTE)]
    while kept and not kept[-1].strip():
        kept.pop()
    body = "\n".join([*kept, *([""] if kept else []), *lines])
    forgerelease._req("PATCH", f"{base}/{int(rel['id'])}", token, {"body": body})
    return rel.get("html_url") or ""


def _sign_run(project, repo, token, rid, aid, tag):
    """Fetch one run's artifact, sign what it holds, attach it. {url, files,
    key, cert} or {error}."""
    d = tempfile.mkdtemp(prefix="bb-relsign-")
    try:
        os.chmod(d, 0o700)
        z = os.path.join(d, "artifact.zip")
        _download(repo, aid, token, z)
        try:
            with zipfile.ZipFile(z) as zf:
                names = [n for n in zf.namelist() if APK.fullmatch(os.path.basename(n)) and not n.endswith("/")]
                apks = []
                for n in names[:8]:
                    p = os.path.join(d, "in-" + os.path.basename(n))
                    with zf.open(n) as src, open(p, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    apks.append((os.path.basename(n), p))
        except zipfile.BadZipFile:
            return {"error": "the run's artifact is not a zip"}
        if not apks:
            return {"error": f"the run's {MARK}{tag} artifact holds no .apk"}
        out, said, first = [], [], {}
        for name, path in apks:
            final = name.replace("-unsigned", "")
            dst = os.path.join(d, "out-" + final)
            r = signing.sign_here(project, path, dst)
            if r.get("error"):
                return {"error": f"{name}: {r['error']}"}
            first = first or r
            out.append((final, dst))
            said.append(f"{NOTE} {final} with the sideload key {r['key']}, certificate SHA-256 {r['cert']}"
                        + (f" (rotated from {r['rotated_from']}, with the proof)" if r.get("rotated_from") else ""))
        url = _attach(project, repo, token, tag, out, said)
        return {"url": url, "files": [n for n, _ in out], "key": first.get("key"), "cert": first.get("cert")}
    except (cilogs.Refused, forgerelease.Refused, OSError) as e:
        return {"error": str(e)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def expect(project, tag):
    """A release was just made for `tag`: its APK is looked for every few
    minutes for a while, and a release whose APK never comes is said."""
    if not TAG.fullmatch(tag or "") or not wants(project):
        return
    with _lock:
        d = _load()
        _mine(d, project)["expect"][tag] = int(time.time())
        _save(d)
    check_soon(project)


def check(project, force=False):
    """Look at the project's recent runs now; sign and attach each unsigned
    APK not yet attached (a failed one again when `force` or an hour on).
    {signed: [tag], failed: [tag], error}."""
    now = int(time.time())
    done = {"signed": [], "failed": [], "error": ""}
    repo = cilogs.repo_of(project)
    token = cilogs._token(project) if repo else ""
    if not repo or not token:
        done["error"] = ("not on GitHub" if not repo else
                         "the controller has no GitHub token for this project, so it cannot fetch the APK to sign")
        return done
    try:
        waiting = _waiting(project, repo, token)
    except cilogs.Refused as e:
        done["error"] = str(e)
        waiting = []
    d = _load()
    rec = _mine(d, project)
    rec["scanned"] = now
    for rid, aid, tag in waiting:
        ran = rec["runs"].get(str(rid)) or {}
        if ran.get("state") == "signed":
            continue
        if ran.get("state") == "failed" and not force and now - int(ran.get("at") or 0) < SCAN_S:
            continue
        r = _sign_run(project, repo, token, rid, aid, tag)
        if r.get("error"):
            rec["runs"][str(rid)] = {"state": "failed", "at": now, "tag": tag}
            rec["failed"][tag] = {"why": r["error"], "at": now, "run": rid}
            done["failed"].append(tag)
        else:
            rec["runs"][str(rid)] = {"state": "signed", "at": now, "tag": tag}
            rec["signed"][tag] = {"at": now, "run": rid, "url": r["url"], "files": r["files"],
                                  "key": r["key"], "cert": r["cert"]}
            rec["failed"].pop(tag, None)
            rec["expect"].pop(tag, None)
            done["signed"].append(tag)
    # A release made here whose APK never came: said once it is overdue.
    for tag, at in list(rec["expect"].items()):
        if now - int(at or 0) > EXPECT_S:
            rec["expect"].pop(tag)
            if tag not in rec["signed"]:
                rec["failed"][tag] = {"why": f"no run handed over an unsigned APK for {tag} within "
                                             f"{EXPECT_S // 3600} hours: did the Android workflow run for it?",
                                      "at": now, "run": 0}
                done["failed"].append(tag)
    # Old runs forgotten: their artifacts are gone by now.
    rec["runs"] = {k: v for k, v in rec["runs"].items() if now - int((v or {}).get("at") or 0) < 2 * RUN_AGE_S}
    with _lock:
        whole = _load()
        # A release expected while this look ran is kept for the next.
        was = (whole.get(project) or {}).get("expect") or {}
        rec["expect"].update({t: a for t, a in was.items() if int(a or 0) >= now and t not in rec["signed"]})
        whole[project] = rec
        _save(whole)
    return done


def due(project, now=None):
    """Whether a project wants a look: a release expected, or the hourly one."""
    now = now or time.time()
    rec = _load().get(project) or {}
    if any(now - int(at or 0) <= EXPECT_S for at in (rec.get("expect") or {}).values()):
        return True
    return now - int(rec.get("scanned") or 0) >= SCAN_S and wants(project)


def _claim(project):
    with _lock:
        if project in _busy:
            return False
        _busy.add(project)
        return True


def _release(project):
    with _lock:
        _busy.discard(project)


def check_soon(project, force=False):
    """check() on its own thread, one per project at a time."""
    if not _claim(project):
        return False

    def go():
        try:
            check(project, force)
        except Exception as e:                                      # noqa: BLE001 (a look must not take the server)
            print(f"dashboard: release signing {project}: {e}", flush=True)
        finally:
            _release(project)
    threading.Thread(target=go, name=f"releasesign-{project}", daemon=True).start()
    return True


def start():
    """Every TICK_S, each project that is due. A daemon thread."""
    def loop():
        while True:
            time.sleep(TICK_S)
            for p in (projects_fn() if projects_fn else []):
                try:
                    if not due(p) or not _claim(p):
                        continue
                except Exception:                                   # noqa: BLE001 (a loop must not die)
                    continue
                try:
                    check(p)
                except Exception as e:                              # noqa: BLE001
                    print(f"dashboard: release signing {p}: {e}", flush=True)
                finally:
                    _release(p)
    threading.Thread(target=loop, name="releasesign", daemon=True).start()


# ---- the bell ---------------------------------------------------------------

def attention(projects):
    """The bell's rows, kind release-sign: what would keep a release's APK
    from being signed, said before the release (amber), and a signing that
    failed after one (red, `bad`), each keyed for bellseen on what it says."""
    out, whole = [], _load()
    for p in projects:
        r = readiness(p)
        if r["wanted"] and r["why"]:
            h = hashlib.sha256(r["why"].encode()).hexdigest()[:10]
            out.append({"kind": "release-sign", "id": p, "project": p, "why": r["why"], "bad": False,
                        "key": f"rsign:{p}@{h}"})
        for tag, f in ((whole.get(p) or {}).get("failed") or {}).items():
            if isinstance(f, dict):
                out.append({"kind": "release-sign", "id": f"{p}|{tag}", "project": p, "tag": tag,
                            "why": str(f.get("why") or ""), "at": int(f.get("at") or 0), "bad": True,
                            "key": f"rsign:{p}|{tag}@{int(f.get('at') or 0)}"})
    return out
