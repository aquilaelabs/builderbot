"""A project's Android signing keys, kept by the controller (R106).

Two routes, either or both per project:

    play       the UPLOAD key for Google Play. Play App Signing holds the key
               the app is really signed with, and Play Console resets a lost
               or leaked upload key, so this one is replaceable.
    sideload   the APP SIGNING key for a build handed out directly (or to
               another store). It is the app's identity for good: lost, no
               update can reach an existing install; leaked, anybody can
               ship one that installs over it.

The keystore and its passwords live under /config/signing/PROJECT/, the
directory 0700 and every file 0600, beside the git tokens and like them
outside every session's view. A session never receives either: a signing is
a job on the project's node that fetches the key over the agent's own
channel for that one job (step 2), so what a session can read, print or
commit holds no key and no password.

An upload is checked before it is kept, with the store's own keytool: a
wrong password or an alias the store does not hold is refused here rather
than at the first signing, and the certificate's SHA-256 fingerprint is
read so the Artifacts tab can say which key signed a build. The password
reaches keytool through its environment (-storepass:env), never argv.
"""
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROUTES = ("play", "sideload")
WORDS = {"play": "Play upload key", "sideload": "sideload signing key"}
# A keystore is a few kilobytes; a megabyte is a file that is not one.
MAX_BYTES = 1 << 20

STATE = None
PROJECT_NAME = None
keytool_path = None     # set by the server: the store's keytool, or None
# Set by the server for start(): the project's node, nodes.job_add and
# workspace.file_path (a dist/ file a node may fetch for a job).
node_of = None
job_add = None
file_path = None


def configure(*, state, project_name, keytool):
    globals().update(STATE=Path(state), PROJECT_NAME=project_name, keytool_path=keytool)


def _dir(project):
    return STATE / "signing" / project


def _ok_project(project):
    return bool(project) and bool(PROJECT_NAME.fullmatch(project)) and "/" not in project


def _record(project, route):
    try:
        with open(_dir(project) / f"{route}.json", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_private(path, data):
    """Write a file only its owner may read, through a temporary name, so a
    reader never meets half a keystore."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    os.chmod(path.parent.parent, 0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _public(rec):
    """What may be shown: everything but the passwords."""
    return {k: v for k, v in rec.items() if k not in ("store_pass", "key_pass")}


def listing(project):
    """{route: public record or None} for a project. No secret in it, so any
    account that sees the project may read it: knowing that a key exists and
    its fingerprint is what lets a person check a signed build."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    out = {}
    for r in ROUTES:
        rec = _record(project, r)
        out[r] = _public(rec) if rec else None
    return {"project": project, "keys": out, "keytool": bool(keytool_path and keytool_path())}, 200


def inspect(blob, store_pass, alias=""):
    """(alias, store type, sha256, error) for a keystore, asked of keytool.

    An empty alias picks the store's only entry, and a store holding several
    asks for one by name rather than guessing which key to sign with."""
    kt = keytool_path() if keytool_path else None
    if not kt:
        return "", "", "", ("there is no keytool to check it with: install the jdk toolchain "
                            "(Toolchains tab), which this controller reads from the shared store")
    d = tempfile.mkdtemp(prefix="bb-sign-")
    try:
        os.chmod(d, 0o700)
        ks = os.path.join(d, "ks")
        fd = os.open(ks, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        env = dict(os.environ, BB_SIGN_PASS=store_pass)
        argv = [kt, "-list", "-v", "-keystore", ks, "-storepass:env", "BB_SIGN_PASS"]
        if alias:
            argv += ["-alias", alias]
        try:
            p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            return "", "", "", f"keytool did not run: {e}"
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            if re.search(r"password was incorrect|Keystore was tampered|integrity", out, re.I):
                return "", "", "", "the keystore's password is not that"
            if alias and re.search(r"does not exist", out, re.I):
                return "", "", "", f"the keystore holds no key named {alias}"
            said = [ln for ln in out.splitlines() if ln.strip()]
            return "", "", "", "keytool could not read it: " + (said[-1][:200] if said else f"exit {p.returncode}")
        names = re.findall(r"^Alias name:\s*(.+)$", out, re.M)
        if not alias:
            if len(names) != 1:
                return "", "", "", (f"the keystore holds {len(names)} keys ({', '.join(names[:6])}): "
                                    "name the one to sign with")
            alias = names[0].strip()
        kind = (re.search(r"^Keystore type:\s*(\S+)", out, re.M) or [None, ""])[1]
        sha = (re.search(r"SHA256:\s*([0-9A-F:]{95})", out) or [None, ""])[1]
        if "PrivateKeyEntry" not in out:
            return "", "", "", f"{alias} is a certificate, not a key: it cannot sign anything"
        return alias, kind, sha, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def put(project, route, blob_b64, store_pass, alias="", key_pass="", by=""):
    """Keep a keystore for one route, once keytool has read it with the
    password given. (payload, status)."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if route not in ROUTES:
        return {"error": f"a key is for {' or '.join(ROUTES)}, not {route!r}"}, 400
    try:
        blob = base64.b64decode(blob_b64 or "", validate=True)
    except ValueError:
        return {"error": "the keystore did not arrive whole"}, 400
    if not blob:
        return {"error": "no keystore was given"}, 400
    if len(blob) > MAX_BYTES:
        return {"error": "that is too large to be a keystore"}, 400
    if not store_pass:
        return {"error": "the keystore's password is needed to sign with it"}, 400
    alias, kind, sha, why = inspect(blob, store_pass, alias.strip())
    if why:
        return {"error": why}, 400
    _write_private(_dir(project) / f"{route}.ks", blob)
    was = _record(project, route) or {}
    rec = {"route": route, "alias": alias, "type": kind, "sha256": sha,
           "by": by, "at": int(time.time()),
           # A replaced key has not been backed up, whatever the last one was.
           "backed_up": 0 if was.get("sha256") != sha else int(was.get("backed_up") or 0),
           "store_pass": store_pass, "key_pass": key_pass or store_pass}
    _write_private(_dir(project) / f"{route}.json", json.dumps(rec).encode())
    return {"ok": True, "project": project, "key": _public(rec)}, 200


def remove(project, route):
    if not _ok_project(project) or route not in ROUTES:
        return {"error": "unknown project or route"}, 400
    gone = False
    for ext in ("ks", "json"):
        p = _dir(project) / f"{route}.{ext}"
        if p.exists():
            p.unlink()
            gone = True
    if not gone:
        return {"error": f"{project} has no {WORDS[route]}"}, 404
    return {"ok": True, "project": project, "route": route}, 200


def backup(project, route):
    """(filename, bytes) of the keystore for an administrator's own copy, and
    the record marks it backed up; (error payload, status) otherwise."""
    if not _ok_project(project) or route not in ROUTES:
        return {"error": "unknown project or route"}, 400
    rec = _record(project, route)
    try:
        blob = (_dir(project) / f"{route}.ks").read_bytes()
    except OSError:
        blob = b""
    if not rec or not blob:
        return {"error": f"{project} has no {WORDS[route]}"}, 404
    rec["backed_up"] = int(time.time())
    _write_private(_dir(project) / f"{route}.json", json.dumps(rec).encode())
    ext = "jks" if str(rec.get("type") or "").upper() == "JKS" else "p12"
    return (f"{project}-{route}.{ext}", blob), 200


def secret(project, route):
    """(keystore bytes, record with its passwords) for the node signing a
    job, or None. The one caller is the agent's job channel (step 2)."""
    rec = _record(project, route)
    try:
        blob = (_dir(project) / f"{route}.ks").read_bytes()
    except OSError:
        return None
    return (blob, rec) if rec else None


def refusal(project, rel, route):
    """(error payload, status) when this signing cannot happen, else None:
    asked before a person is asked to allow one (step 3) as well as before
    one is queued."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if route not in ROUTES:
        return {"error": f"a build is signed for {' or '.join(ROUTES)}, not {route!r}"}, 400
    if not _record(project, route):
        return {"error": f"{project} has no {WORDS[route]}: an administrator adds one under "
                         "Signing keys in its settings"}, 404
    rel = str(rel or "").replace("\\", "/").strip()
    rel = rel[len("dist/"):] if rel.startswith("dist/") else rel
    if not rel.lower().endswith((".apk", ".aab")):
        return {"error": "an Android build is an .apk or an .aab"}, 400
    if file_path(project, rel) is None:
        return {"error": f"no {rel} in {project}'s dist/: bb build puts a build there"}, 404
    if not (node_of(project) or ""):
        return {"error": f"{project} has no node to sign on: its settings choose one"}, 400
    return None


def start(principal, project, rel, route):
    """Queue the signing of one build in dist/ with one of the project's
    keys, on the project's node (step 2). Refused before anything is queued
    when there is no such key, no such build, or nowhere to sign it.
    (payload, status)."""
    no = refusal(project, rel, route)
    if no:
        return no
    rel = str(rel or "").replace("\\", "/").strip()
    rel = rel[len("dist/"):] if rel.startswith("dist/") else rel
    r = job_add(principal, {"node": node_of(project)}, "sign", {"route": route, "file": rel, "timeout": 900},
                project=project)
    return r, (400 if r.get("error") else 200)


def verb(req, by=""):
    """POST /api/signing's actions, once the server has decided the caller
    may: list for anybody who sees the project, the rest an administrator's."""
    act = str(req.get("action") or "list")
    project = str(req.get("project") or "")
    route = str(req.get("route") or "")
    if act == "list":
        return listing(project)
    if act == "put":
        return put(project, route, str(req.get("keystore") or ""), str(req.get("password") or ""),
                   str(req.get("alias") or ""), str(req.get("key_password") or ""), by=by)
    if act == "remove":
        return remove(project, route)
    return {"error": f"unknown action {act!r}"}, 400
