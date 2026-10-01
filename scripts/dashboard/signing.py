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
import contextlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import zipfile
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


# A project keeps several named keys (step 6), each with its two slots. The
# name is what a package is mapped to and what a row says signed it.
DEFAULT = "default"
KEY_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# A package name as Android writes one: dotted segments of letters, digits
# and underscores, each starting with a letter.
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")


def _root(project):
    return STATE / "signing" / project


def _dir(project, key=DEFAULT):
    _settle(project)
    return _root(project) / key


def _settle(project):
    """Move a project's keys from before there were names (the slots at the
    project's own directory) into `default`, once."""
    root = _root(project)
    for r in ROUTES:
        for ext in ("ks", "json"):
            old = root / f"{r}.{ext}"
            if old.is_file():
                (root / DEFAULT).mkdir(parents=True, exist_ok=True)
                os.chmod(root / DEFAULT, 0o700)
                os.replace(old, root / DEFAULT / f"{r}.{ext}")


def _ok_project(project):
    return bool(project) and bool(PROJECT_NAME.fullmatch(project)) and "/" not in project


def _ok_key(key):
    return bool(KEY_NAME.fullmatch(key or ""))


def _record(project, route, key=DEFAULT):
    try:
        with open(_dir(project, key) / f"{route}.json", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write_private(path, data):
    """Write a file only its owner may read, through a temporary name, so a
    reader never meets half a keystore."""
    path.parent.mkdir(parents=True, exist_ok=True)
    top = STATE / "signing"
    for d in [top, *[q for q in path.parents if top in q.parents]]:
        os.chmod(d, 0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _public(rec):
    """What may be shown: everything but the passwords."""
    return {k: v for k, v in rec.items() if k not in ("store_pass", "key_pass")}


def key_names(project):
    """The project's keys by name, `default` first when it has one."""
    _settle(project)
    root = _root(project)
    try:
        names = sorted(d.name for d in root.iterdir() if d.is_dir() and _ok_key(d.name))
    except OSError:
        names = []
    return sorted(names, key=lambda n: (n != DEFAULT, n))


def mapping(project):
    """{package: key}: which of the project's apps signs with which key; a
    package with no line signs with `default`."""
    try:
        with open(_root(project) / "map.json", encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if PACKAGE.fullmatch(k) and _ok_key(v)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def key_for(project, package):
    return mapping(project).get(package or "", DEFAULT)


def listing(project):
    """Every key's two slots (public records, or None) and the mapping. No
    secret in it, so any account that sees the project may read it: knowing
    which keys exist and their fingerprints is what lets a person check a
    signed build."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    keys = {}
    for k in key_names(project):
        keys[k] = {r: (_public(rec) if (rec := _record(project, r, k)) else None) for r in ROUTES}
    return {"project": project, "keys": keys, "map": mapping(project),
            "keytool": bool(keytool_path and keytool_path())}, 200


def routes_held(project):
    """The routes any of the project's keys can sign for."""
    return [r for r in ROUTES if any(_record(project, r, k) for k in key_names(project))]


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


def _keep(project, route, key, blob, alias, kind, sha, store_pass, key_pass, by, generated=False):
    _write_private(_dir(project, key) / f"{route}.ks", blob)
    was = _record(project, route, key) or {}
    rec = {"route": route, "key": key, "alias": alias, "type": kind, "sha256": sha,
           "by": by, "at": int(time.time()), "generated": bool(generated),
           # A replaced key has not been backed up, whatever the last one was.
           "backed_up": 0 if was.get("sha256") != sha else int(was.get("backed_up") or 0),
           "store_pass": store_pass, "key_pass": key_pass or store_pass}
    _write_private(_dir(project, key) / f"{route}.json", json.dumps(rec).encode())
    return {"ok": True, "project": project, "key": _public(rec)}, 200


def _check(project, route, key):
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if route not in ROUTES:
        return {"error": f"a key is for {' or '.join(ROUTES)}, not {route!r}"}, 400
    if not _ok_key(key):
        return {"error": "a key's name is lowercase letters, digits and dashes, up to 32"}, 400
    return None


def put(project, route, blob_b64, store_pass, alias="", key_pass="", by="", key=DEFAULT):
    """Keep a keystore for one key's route, once keytool has read it with the
    password given. (payload, status)."""
    if (no := _check(project, route, key)):
        return no
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
    return _keep(project, route, key, blob, alias, kind, sha, store_pass, key_pass, by)


def generate(project, route, key=DEFAULT, by="", name=""):
    """Make a new key on the controller with the store's keytool: RSA 4096,
    good for ten thousand days, behind a random password kept in its record,
    so nobody types or sees one. Refused where the slot holds a key already:
    replacing a key is an upload, said on purpose. (payload, status)."""
    if (no := _check(project, route, key)):
        return no
    if _record(project, route, key):
        return {"error": f"{key} has a {WORDS[route]} already: replacing one is an upload, "
                         "and a sideload key once used is the app's for good"}, 409
    kt = keytool_path() if keytool_path else None
    if not kt:
        return {"error": "there is no keytool to make one with: install the jdk toolchain "
                         "(Toolchains tab), which this controller reads from the shared store"}, 400
    pw = secrets.token_urlsafe(24)
    who = re.sub(r"[^A-Za-z0-9 ._-]", "", name or project)[:60] or project
    d = tempfile.mkdtemp(prefix="bb-sign-")
    try:
        os.chmod(d, 0o700)
        ks = os.path.join(d, "ks.p12")
        try:
            p = subprocess.run([kt, "-genkeypair", "-keystore", ks, "-storetype", "PKCS12",
                                "-storepass:env", "BB_SIGN_PASS", "-alias", key, "-keyalg", "RSA",
                                "-keysize", "4096", "-validity", "10000", "-dname", f"CN={who}"],
                               env=dict(os.environ, BB_SIGN_PASS=pw), capture_output=True, text=True,
                               timeout=120, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            return {"error": f"keytool did not run: {e}"}, 500
        if p.returncode != 0:
            return {"error": "keytool could not make it: " + ((p.stderr or p.stdout).strip()[-200:])}, 500
        blob = Path(ks).read_bytes()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    alias, kind, sha, why = inspect(blob, pw, key)
    if why:
        return {"error": why}, 500
    return _keep(project, route, key, blob, alias, kind, sha, pw, pw, by, generated=True)


def set_map(project, package, key):
    """Map an app's package to one of the project's keys, or unmap it with
    an empty key, which signs it with `default` again. (payload, status)."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if not PACKAGE.fullmatch(package or ""):
        return {"error": f"{package!r} is not an Android package name (com.example.app)"}, 400
    m = mapping(project)
    if key:
        if key not in key_names(project):
            return {"error": f"{project} has no key named {key}"}, 404
        m[package] = key
    else:
        m.pop(package, None)
    _write_private(_root(project) / "map.json", json.dumps(m).encode())
    return listing(project)


def remove(project, route, key=DEFAULT):
    if not _ok_project(project) or route not in ROUTES or not _ok_key(key):
        return {"error": "unknown project, key or route"}, 400
    gone = False
    for ext in ("ks", "json"):
        p = _dir(project, key) / f"{route}.{ext}"
        if p.exists():
            p.unlink()
            gone = True
    if not gone:
        return {"error": f"{project}'s {key} has no {WORDS[route]}"}, 404
    # A key left with neither slot goes, and so do the packages mapped to it,
    # which sign with `default` again.
    with contextlib.suppress(OSError):
        _dir(project, key).rmdir()
        m = {p: k for p, k in mapping(project).items() if k != key}
        _write_private(_root(project) / "map.json", json.dumps(m).encode())
    return {"ok": True, "project": project, "key": key, "route": route}, 200


def backup(project, route, key=DEFAULT):
    """(filename, bytes) of the keystore for an administrator's own copy, and
    the record marks it backed up; (error payload, status) otherwise."""
    if not _ok_project(project) or route not in ROUTES or not _ok_key(key):
        return {"error": "unknown project, key or route"}, 400
    rec = _record(project, route, key)
    try:
        blob = (_dir(project, key) / f"{route}.ks").read_bytes()
    except OSError:
        blob = b""
    if not rec or not blob:
        return {"error": f"{project}'s {key} has no {WORDS[route]}"}, 404
    rec["backed_up"] = int(time.time())
    _write_private(_dir(project, key) / f"{route}.json", json.dumps(rec).encode())
    ext = "jks" if str(rec.get("type") or "").upper() == "JKS" else "p12"
    base = f"{project}-{key}-{route}"
    if rec.get("generated"):
        # Its password was made here and is in no head, so a keystore alone
        # would be a backup nobody could open: the two travel together.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{base}.{ext}", blob)
            z.writestr("password.txt", f"keystore and key password: {rec.get('store_pass')}\n"
                                       f"alias: {rec.get('alias')}\nSHA-256: {rec.get('sha256')}\n")
        return (f"{base}.zip", buf.getvalue()), 200
    return (f"{base}.{ext}", blob), 200


def secret(project, route, key=DEFAULT):
    """(keystore bytes, record with its passwords) for the node signing a
    job, or None. The one caller is the agent's job channel (step 2)."""
    rec = _record(project, route, key)
    try:
        blob = (_dir(project, key) / f"{route}.ks").read_bytes()
    except OSError:
        return None
    return (blob, rec) if rec else None


def refusal(project, rel, route, key=""):
    """(error payload, status) when this signing cannot happen, else None:
    asked before a person is asked to allow one (step 3) as well as before
    one is queued. With no key named, any key holding the route will do
    here: which one is decided on the node, by the build's package."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if route not in ROUTES:
        return {"error": f"a build is signed for {' or '.join(ROUTES)}, not {route!r}"}, 400
    if key and not _record(project, route, key):
        return {"error": f"{project} has no {WORDS[route]} named {key}"}, 404
    if not key and route not in routes_held(project):
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


def start(principal, project, rel, route, key=""):
    """Queue the signing of one build in dist/ with one of the project's
    keys, on the project's node (step 2): the key named, or the one its
    package is mapped to, read on the node (step 6). Refused before anything
    is queued when it cannot happen. (payload, status)."""
    no = refusal(project, rel, route, key)
    if no:
        return no
    rel = str(rel or "").replace("\\", "/").strip()
    rel = rel[len("dist/"):] if rel.startswith("dist/") else rel
    spec = {"route": route, "file": rel, "timeout": 900}
    if key:
        spec["key"] = key
    r = job_add(principal, {"node": node_of(project)}, "sign", spec, project=project)
    return r, (400 if r.get("error") else 200)


def verb(req, by=""):
    """POST /api/signing's actions, once the server has decided the caller
    may: list for anybody who sees the project, the rest an administrator's."""
    act = str(req.get("action") or "list")
    project = str(req.get("project") or "")
    route = str(req.get("route") or "")
    key = str(req.get("key") or DEFAULT)
    if act == "list":
        return listing(project)
    if act == "put":
        return put(project, route, str(req.get("keystore") or ""), str(req.get("password") or ""),
                   str(req.get("alias") or ""), str(req.get("key_password") or ""), by=by, key=key)
    if act == "generate":
        return generate(project, route, key, by=by, name=str(req.get("name") or ""))
    if act == "map":
        return set_map(project, str(req.get("package") or ""), str(req.get("key") or ""))
    if act == "remove":
        return remove(project, route, key)
    return {"error": f"unknown action {act!r}"}, 400
