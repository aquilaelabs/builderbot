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
outside every session's view, and sealed there (R111 step 2) under the
install's signing secret, which is never in /config: a copied /config, or a
backup of it, holds ciphertext alone. Root on the running controller still
reads them, as it reads everything the dashboard can. A session never receives either: a signing is
a job on the project's node that fetches the key over the agent's own
channel for that one job (step 2), so what a session can read, print or
commit holds no key and no password.

Nothing here runs a jdk or build-tools (the operator, 22 Oct: the
controller runs nothing). What needs keytool or apksigner, an upload checked,
a key made, a backup wrapped, a rotation's proof and a release's APK signed,
is a sign-key job on the project's node (_on_node), as bb sign is a sign job
there: what it needs is handed over the agent's channel for that job alone
(hand_over), what it made comes back the same way (take_result), and this
waits for it. An upload is checked before it is kept: a wrong password or
an alias the store does not hold is refused rather than at the first
signing, and the certificate's SHA-256 fingerprint is read so the Artifacts
view can say which key signed a build.
"""
import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import threading
import time
import zipfile
from pathlib import Path

ROUTES = ("play", "sideload")
WORDS = {"play": "Play upload key", "sideload": "sideload signing key"}
# A keystore is a few kilobytes; a megabyte is a file that is not one.
MAX_BYTES = 1 << 20

STATE = None
PROJECT_NAME = None
# Set by the server for start(): the project's node, nodes.job_add and
# workspace.file_path (a dist/ file a node may fetch for a job).
node_of = None
# (node id) -> why that node will take no job now (its agent is behind the
# controller's), or "": asked before anybody is asked to allow a signing.
node_refuses = None
job_add = None
file_path = None
# Set by the server for the key work on the node: nodes.node, nodes.job,
# nodes.job_cancel, and (node) -> the toolchain names its store holds,
# empty when it has not said (toolchains.node_has).
node_get = None
job_get = None
job_cancel = None
node_tools = None


def configure(*, state, project_name, secret_file=None):
    globals().update(STATE=Path(state), PROJECT_NAME=project_name)
    load_master(secret_file)


# ---- sealed at rest (R111 step 2) ------------------------------------------
# The install's signing secret: SIGNING_SECRET in the container's environment,
# which the entrypoint shields like every secret and hands the dashboard as a
# file of its own in /run (never /config). Each keystore and each record's
# passwords are sealed under it. The standard library has no cipher, so the
# seal is built from what it has: HMAC-SHA256 as a pseudorandom function in
# counter mode for the keystream (a fresh 16-byte nonce per seal) and a
# second HMAC over the whole for its tag, checked before anything is opened
# (encrypt-then-MAC, two keys derived from the secret apart).
SECRET_FILE = "/run/builderbot-signing"
MAGIC = b"BBSEAL1\n"
MASTER = None


class Locked(Exception):
    """A sealed file this controller cannot open: no signing secret, or not
    the one it was sealed under."""


def load_master(path=None):
    """Read the signing secret, or none: a missing file is an install that
    has not set one, and keeps its keys unsealed as before."""
    f = Path(path or os.environ.get("BB_SIGNING_SECRET_FILE") or SECRET_FILE)
    try:
        raw = f.read_bytes().strip()
    except OSError:
        raw = b""
    globals()["MASTER"] = raw if len(raw) >= 16 else None
    return MASTER is not None


def _subkeys():
    root = hashlib.sha256(b"builderbot signing seal v1\0" + MASTER).digest()
    return (hmac.new(root, b"encrypt", hashlib.sha256).digest(),
            hmac.new(root, b"authenticate", hashlib.sha256).digest())


def _stream(key, nonce, n):
    out, i = bytearray(), 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def seal(data):
    """`data` sealed under the signing secret: MAGIC, nonce, ciphertext, tag."""
    enc, mac = _subkeys()
    nonce = secrets.token_bytes(16)
    ct = bytes(a ^ b for a, b in zip(data, _stream(enc, nonce, len(data)), strict=True))
    return MAGIC + nonce + ct + hmac.new(mac, MAGIC + nonce + ct, hashlib.sha256).digest()


def unseal(blob):
    """The data a seal holds, or Locked: checked whole before it is opened."""
    if MASTER is None:
        raise Locked("this controller has no signing secret: set SIGNING_SECRET as it was, or import the key's backup")
    enc, mac = _subkeys()
    body, tag = blob[:-32], blob[-32:]
    if len(blob) < len(MAGIC) + 48 or not hmac.compare_digest(tag, hmac.new(mac, body, hashlib.sha256).digest()):
        raise Locked("sealed under another signing secret: set SIGNING_SECRET as it was, or import the key's backup")
    nonce, ct = body[len(MAGIC):len(MAGIC) + 16], body[len(MAGIC) + 16:]
    return bytes(a ^ b for a, b in zip(ct, _stream(enc, nonce, len(ct)), strict=True))


def _read_secret(path):
    """A keystore's bytes from disk, opened if sealed (Locked if it cannot be)."""
    data = Path(path).read_bytes()
    return unseal(data) if data.startswith(MAGIC) else data


def _write_secret(path, data):
    """A keystore written sealed where there is a signing secret."""
    _write_private(path, seal(data) if MASTER is not None else data)


def _save_rec(project, key, route, rec):
    """A key's record written with its passwords sealed (in `sealed`) where
    there is a signing secret, and never the opened copy _record hands out."""
    out = {k: v for k, v in rec.items() if k not in ("store_pass", "key_pass", "sealed", "locked")}
    pw = {"store_pass": rec.get("store_pass"), "key_pass": rec.get("key_pass")}
    if rec.get("locked"):
        out["sealed"] = rec.get("sealed")          # kept as it was: it cannot be opened here
    elif MASTER is not None:
        out["sealed"] = base64.b64encode(seal(json.dumps(pw).encode())).decode()
    else:
        out.update(pw)
    _write_private(_dir(project, key) / f"{route}.json", json.dumps(out).encode())


def at_rest(project=None):
    """How the keys are kept: "sealed" (every one), "open" (none sealed, no
    secret set), "locked" (sealed keys this controller cannot open), or
    "mixed" (a secret set and keys still to seal, which seal_all does)."""
    seen = set()
    for proj in ([project] if project else _projects()):
        for k in key_names(proj):
            for r in ROUTES:
                rec = _record(proj, r, k)
                if rec:
                    seen.add("locked" if rec.get("locked") else "sealed" if rec.get("sealed") else "open")
    if "locked" in seen:
        return "locked"
    if not seen:
        return "sealed" if MASTER is not None else "open"
    if seen == {"sealed"}:
        return "sealed"
    return "mixed" if MASTER is not None else "open"


def _projects():
    top = STATE / "signing" if STATE else None
    try:
        return sorted(d.name for d in top.iterdir() if d.is_dir() and _ok_project(d.name))
    except (OSError, AttributeError):
        return []


def seal_all():
    """Seal every key kept open, at start and whenever a secret first
    arrives: its keystore and its record's passwords. Returns how many."""
    if MASTER is None:
        return 0
    n = 0
    for proj in _projects():
        for k in key_names(proj):
            for r in ROUTES:
                rec = _record(proj, r, k)
                if not rec or rec.get("sealed") or rec.get("locked"):
                    continue
                ks = _dir(proj, k) / f"{r}.ks"
                try:
                    data = ks.read_bytes()
                    if not data.startswith(MAGIC):
                        _write_private(ks, seal(data))
                except OSError:
                    continue
                _save_rec(proj, k, r, rec)
                n += 1
    return n


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
    """A key's record, its passwords opened where they were sealed; one this
    controller cannot open says why in `locked` and carries none."""
    try:
        with open(_dir(project, key) / f"{route}.json", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    if d.get("sealed"):
        try:
            d.update(json.loads(unseal(base64.b64decode(d["sealed"]))))
        except Locked as e:
            d["locked"] = str(e)
        except (ValueError, TypeError):
            d["locked"] = "its sealed passwords are damaged: import the key's backup"
    return d


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
    return {k: v for k, v in rec.items() if k not in ("store_pass", "key_pass", "sealed")}


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


def key_for(project, package, route=""):
    """The key a build of `package` is signed with: the one it is mapped to,
    else `default`, else, when no key is called that, the project's only key
    holding the route. A project whose one key had another name had every
    unmapped build approved and then failed for want of `default`
    (BuilderBot's own app, 5 Oct, B509)."""
    mapped = mapping(project).get(package or "")
    if mapped:
        return mapped
    if not route or _record(project, route, DEFAULT):
        return DEFAULT
    holders = [k for k in key_names(project) if _record(project, route, k)]
    return holders[0] if len(holders) == 1 else DEFAULT


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
            # The node a key is checked and made on, and what keeps that
            # from happening there now ("" when nothing does).
            "node": signer_name(project), "node_why": signer(project)[1],
            "backup_locked": bool(backup_locked(project)),
            # Sealed under the install's signing secret, kept open, or
            # locked (R111 step 2): the view says which.
            "at_rest": at_rest(project)}, 200


def routes_held(project):
    """The routes any of the project's keys can sign for."""
    return [r for r in ROUTES if any(_record(project, r, k) for k in key_names(project))]


def inspect(project, blob, store_pass, alias=""):
    """(alias, store type, sha256, error) for a keystore, asked of keytool on
    the project's node. An empty alias picks the store's only entry, and a
    store holding several asks for one by name rather than guessing which
    key to sign with."""
    r = _on_node(project, "inspect", {"keystore": base64.b64encode(blob).decode(),
                                      "store_pass": store_pass, "alias": alias})
    if r.get("error"):
        return "", "", "", r["error"]
    return r.get("alias") or "", r.get("type") or "", r.get("sha256") or "", ""


def _keep(project, route, key, blob, alias, kind, sha, store_pass, key_pass, by, generated=False, imported=False):
    _write_secret(_dir(project, key) / f"{route}.ks", blob)
    was = _record(project, route, key) or {}
    rec = {"route": route, "key": key, "alias": alias, "type": kind, "sha256": sha,
           "by": by, "at": int(time.time()), "generated": bool(generated),
           # A replaced key has not been backed up, whatever the last one was;
           # one brought back from a backup is one somebody already holds.
           "backed_up": int(time.time()) if imported
           else 0 if was.get("sha256") != sha else int(was.get("backed_up") or 0),
           "store_pass": store_pass, "key_pass": key_pass or store_pass}
    if imported:
        # Its password came in a backup's password.txt and is in no head
        # either, so its own backup carries the two together again.
        rec["imported"] = True
    _save_rec(project, key, route, rec)
    return {"ok": True, "project": project, "key": _public(rec)}, 200


def needs_lock(project):
    """(error, 409) while a project has no backup password, else None: a key
    is only kept once its backups have one (the operator, 2 Oct), so no key
    can leave the dashboard without it from the first one on."""
    if backup_locked(project):
        return None
    return {"error": f"{project} has no backup password yet: its owner sets one in its Signing view first, "
                     "and every key's backup asks for it from then on"}, 409


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
    if (no := _check(project, route, key)) or (no := needs_lock(project)):
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
    alias, kind, sha, why = inspect(project, blob, store_pass, alias.strip())
    if why:
        return {"error": why}, 400
    return _keep(project, route, key, blob, alias, kind, sha, store_pass, key_pass, by)


def generate(project, route, key=DEFAULT, by="", name=""):
    """Make a new key on the project's node with its keytool: RSA 4096,
    good for ten thousand days, behind a random password kept in its record,
    so nobody types or sees one. Refused where the slot holds a key already:
    replacing a key is an upload, said on purpose. (payload, status)."""
    if (no := _check(project, route, key)) or (no := needs_lock(project)):
        return no
    if _record(project, route, key):
        return {"error": f"{key} has a {WORDS[route]} already: replacing one is an upload, "
                         "and a sideload key once used is the app's for good"}, 409
    pw = secrets.token_urlsafe(24)
    who = re.sub(r"[^A-Za-z0-9 ._-]", "", name or project)[:60] or project
    r = _on_node(project, "generate", {"alias": key, "cn": who, "password": pw}, by=by)
    if r.get("error"):
        return {"error": r["error"]}, 409 if r.get("state") else 500
    try:
        blob = base64.b64decode(r.get("keystore") or "", validate=True)
    except ValueError:
        blob = b""
    alias, kind, sha = r.get("alias") or "", r.get("type") or "", r.get("sha256") or ""
    if not blob or not sha:
        return {"error": "the node made no key it could read back"}, 500
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


def successor(project, key):
    """The key a sideload key was rotated to, followed to the newest: a
    retired key signs nothing itself, its builds go out with what replaced
    it and the proof that it did."""
    seen = set()
    while key not in seen:
        seen.add(key)
        rec = _record(project, "sideload", key) or {}
        nxt = rec.get("retired_for") or ""
        if not nxt or not _record(project, "sideload", nxt):
            return key
        key = nxt
    return key


def lineage(project, key):
    """The proof of rotation a key's sideload slot carries, or b""."""
    try:
        return (_dir(project, key) / "sideload.lineage").read_bytes()
    except OSError:
        return b""


def rotate(project, old, new, by=""):
    """Move an app from one sideload key to another (step 7): the proof of
    rotation made on the project's node with apksigner from both keys, kept
    with the new one; the old one retired, never signing alone again and
    kept, since the proof and every device before Android 9 still need it;
    and the apps mapped to the old key mapped to the new. (payload, status)."""
    if not _ok_project(project) or not _ok_key(old) or not _ok_key(new):
        return {"error": "unknown project or key"}, 400
    if old == new:
        return {"error": "a key is rotated to another key"}, 400
    a, b = _record(project, "sideload", old), _record(project, "sideload", new)
    if not a or not b:
        return {"error": f"both keys need a sideload signing key: {old if not a else new} has none"}, 404
    if a.get("retired_for"):
        return {"error": f"{old} was rotated to {a['retired_for']} already"}, 409
    if b.get("rotated_from") or b.get("retired_for"):
        return {"error": f"{new} is part of a rotation already, so it cannot start another"}, 409
    if a.get("locked") or b.get("locked"):
        return {"error": a.get("locked") or b.get("locked")}, 409
    got_a, got_b = secret(project, "sideload", old), secret(project, "sideload", new)
    if not got_a or not got_b:
        return {"error": locked(project, "sideload", old) or locked(project, "sideload", new)
                or "a key's keystore could not be read"}, 409

    def signer_of(got):
        blob, rec = got
        return {"keystore": base64.b64encode(blob).decode(), "alias": rec.get("alias") or "",
                "store_pass": rec.get("store_pass") or "", "key_pass": rec.get("key_pass") or ""}
    r = _on_node(project, "rotate", {"old": signer_of(got_a), "new": signer_of(got_b)}, build_tools=True, by=by)
    if r.get("error"):
        return {"error": r["error"]}, 409 if r.get("state") else 500
    try:
        proof = base64.b64decode(r.get("lineage") or "", validate=True)
    except ValueError:
        proof = b""
    if not proof:
        return {"error": "the node made no proof of rotation"}, 500
    _write_private(_dir(project, new) / "sideload.lineage", proof)
    b.update(rotated_from=old, rotated_at=int(time.time()), rotated_by=by)
    _save_rec(project, new, "sideload", b)
    a.update(retired_for=new, retired_at=int(time.time()))
    _save_rec(project, old, "sideload", a)
    m = {pkg: (new if k == old else k) for pkg, k in mapping(project).items()}
    _write_private(_root(project) / "map.json", json.dumps(m).encode())
    return listing(project)


def remove(project, route, key=DEFAULT):
    if not _ok_project(project) or route not in ROUTES or not _ok_key(key):
        return {"error": "unknown project, key or route"}, 400
    if route == "sideload" and (_record(project, "sideload", key) or {}).get("retired_for"):
        return {"error": f"{key}'s sideload key was rotated to {(_record(project, 'sideload', key) or {})['retired_for']}, "
                         "and the proof, and every device before Android 9, still need it: it is kept"}, 409
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


def _rewrap(project, blob, store_pass, key_pass, alias, new_pass):
    """(PKCS12 bytes, error, whether the error is the node's state): the
    keystore's key under `new_pass`, as its store and key password both, by
    keytool -importkeystore on the project's node, the keystore's own
    encryption (R111)."""
    r = _on_node(project, "wrap", {"keystore": base64.b64encode(blob).decode(), "store_pass": store_pass,
                                   "key_pass": key_pass or store_pass, "alias": alias, "new_pass": new_pass})
    if r.get("error"):
        return b"", r["error"], bool(r.get("state"))
    try:
        out = base64.b64decode(r.get("keystore") or "", validate=True)
    except ValueError:
        out = b""
    return (out, "", False) if out else (b"", "the node wrapped nothing", False)


def backup(project, route, key=DEFAULT, password=""):
    """(filename, bytes) of the keystore for an administrator's own copy, and
    the record marks it backed up; (error payload, status) otherwise. With
    the project's backup password (checked by the caller), the keystore in
    the zip is wrapped under it and password.txt never holds a password, so
    a copy of the file is no key without it (R111)."""
    if not _ok_project(project) or route not in ROUTES or not _ok_key(key):
        return {"error": "unknown project, key or route"}, 400
    rec = _record(project, route, key)
    if rec and rec.get("locked"):
        return {"error": rec["locked"]}, 409
    try:
        blob = _read_secret(_dir(project, key) / f"{route}.ks")
    except (OSError, Locked):
        blob = b""
    if not rec or not blob:
        return {"error": f"{project}'s {key} has no {WORDS[route]}"}, 404
    ext = "jks" if str(rec.get("type") or "").upper() == "JKS" else "p12"
    base = f"{project}-{key}-{route}"
    if password:
        wrapped, why, state = _rewrap(project, blob, rec.get("store_pass") or "", rec.get("key_pass") or "",
                                      rec.get("alias") or "", password)
        if why:
            # Never the bare key in its place: a backup password promises
            # the copy is wrapped. A node that cannot wrap it now says why.
            return {"error": why}, 409 if state else 500
        rec["backed_up"] = int(time.time())
        _save_rec(project, key, route, rec)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{base}.p12", wrapped)
            z.writestr("password.txt", "keystore and key password: this project's backup password\n"
                                       f"alias: {rec.get('alias')}\nSHA-256: {rec.get('sha256')}\n")
        return (f"{base}.zip", buf.getvalue()), 200
    rec["backed_up"] = int(time.time())
    _save_rec(project, key, route, rec)
    if rec.get("generated") or rec.get("imported"):
        # Its password was made here and is in no head, so a keystore alone
        # would be a backup nobody could open: the two travel together.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{base}.{ext}", blob)
            z.writestr("password.txt", f"keystore and key password: {rec.get('store_pass')}\n"
                                       f"alias: {rec.get('alias')}\nSHA-256: {rec.get('sha256')}\n")
        return (f"{base}.zip", buf.getvalue()), 200
    return (f"{base}.{ext}", blob), 200


# ---- a backup brought back (R103, the operator 22 Oct) ----------------------
# What Download backup hands over goes back in, to this project or another:
# the zip a generated key's backup is (the keystore and password.txt, which
# says its password and alias, so nothing is retyped), or a bare keystore
# with the password its owner types. Checked as an upload is, and against the
# fingerprint password.txt names.
BACKUP_KS = re.compile(r"[A-Za-z0-9._-]{1,200}\.(p12|jks|pfx|keystore)")
BACKUP_ROUTE = re.compile(r"-(play|sideload)\.(p12|jks|pfx|keystore|zip)$")


def _read_backup(blob):
    """(keystore bytes, password, alias, sha256, keystore's name, error) from
    a backup zip: exactly a keystore and password.txt, each under the cap."""
    def no(why):
        return b"", "", "", "", "", why
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        infos = z.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return no("that is not a key's backup: the zip did not open")
    names = sorted(i.filename for i in infos)
    stores = [n for n in names if BACKUP_KS.fullmatch(n)]
    if len(infos) != 2 or "password.txt" not in names or len(stores) != 1:
        return no("a key's backup is a keystore and password.txt, nothing else: "
                  f"this one holds {', '.join(names[:6]) or 'nothing'}")
    if any(i.file_size > MAX_BYTES for i in infos):
        return no("that is too large to be a key's backup")
    try:
        ks = z.read(stores[0])
        said = z.read("password.txt").decode("utf-8")
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        return no("the backup's files did not read whole")

    def line(k):
        m = re.search(rf"^{k}:[ \t]*(.*?)[ \t]*$", said, re.M)
        return m[1] if m else ""
    pw = line("keystore and key password")
    if not pw:
        return no("the backup's password.txt names no password")
    # Wrapped under its project's backup password (R111): the one typed in.
    if pw == "this project's backup password":
        pw = ""
    return ks, pw, line("alias"), line("SHA-256"), stores[0], ""


def import_backup(project, route, blob_b64, key="", password="", alias="", filename="", by=""):
    """Keep a key from a backup: a backup zip, or a bare keystore with its
    password. An empty route is read off the backup's name, an empty key off
    a zip's alias (a generated key is aliased by its name), else `default`.
    Refused over a slot that holds a different key. The password goes into
    the key's record and nowhere else. (payload, status)."""
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    if (no := needs_lock(project)):
        return no
    try:
        blob = base64.b64decode(blob_b64 or "", validate=True)
    except ValueError:
        return {"error": "the backup did not arrive whole"}, 400
    if not blob:
        return {"error": "no backup was given"}, 400
    if len(blob) > MAX_BYTES:
        return {"error": "that is too large to be a key's backup"}, 400
    zipped = blob[:4] == b"PK\x03\x04"
    want = inner = ""
    if zipped:
        typed = password
        blob, password, alias, want, inner, why = _read_backup(blob)
        if why:
            return {"error": why}, 400
        if not password:
            if not typed:
                return {"error": "this backup is wrapped under its project's backup password: type that password to import it"}, 400
            password = typed
        if not key and _ok_key(alias):
            key = alias
    elif not password:
        return {"error": "a keystore on its own needs its password: a generated key's backup is the zip, which carries it"}, 400
    key = key or DEFAULT
    if not route:
        m = BACKUP_ROUTE.search(filename or "") or BACKUP_ROUTE.search(inner)
        route = m[1] if m else ""
    if not route:
        return {"error": "say which slot it goes in, Play upload or sideload: the backup's name does not"}, 400
    if (no := _check(project, route, key)):
        return no
    alias, kind, sha, why = inspect(project, blob, password, alias.strip())
    if why:
        return {"error": why}, 400
    if want and want != sha:
        return {"error": "the keystore is not the key its password.txt names: the fingerprints differ"}, 400
    was = _record(project, route, key)
    if was and was.get("sha256") != sha:
        return {"error": f"{key} has a {WORDS[route]} already: remove it first, or import it under another name"}, 409
    return _keep(project, route, key, blob, alias, kind, sha, password, "", by, imported=zipped)


# ---- the backup password (the operator, 1 Oct) ----------------------------
# A project's owner may put a password on its keys' backups, which every
# download then needs, BuilderBot's owner's included: the dashboard's own
# accounts stop being enough to walk off with a key. Kept as a PBKDF2 hash
# (users.hash_password), never readable back; changed or removed only with
# the current one; five wrong in a row hold the downloads for fifteen
# minutes. It guards the dashboard's door, not the disk: somebody with a
# shell on the controller reads /config either way, which the docs say.
LOCK_TRIES, LOCK_HOLD = 5, 900
_tries = {}


def _lock_path(project):
    return _root(project) / "backup-lock.json"


def backup_locked(project):
    try:
        with open(_lock_path(project), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("hash") else None
    except (OSError, ValueError):
        return None


def set_backup_password(project, current, new, by=""):
    """Set, change or (new "") remove the backup password; the current one is
    asked for whenever there is one. (payload, status)."""
    import users
    if not _ok_project(project):
        return {"error": "unknown project"}, 400
    was = backup_locked(project)
    if was and not users.check_password(was["hash"], current or ""):
        return {"error": "that is not the backup password now"}, 403
    if not new:
        if was:
            _lock_path(project).unlink()
        return {"ok": True, "backup_locked": False}, 200
    if len(new) < 10:
        return {"error": "a backup password is at least ten characters"}, 400
    _write_private(_lock_path(project), json.dumps({"hash": users.hash_password(new), "by": by,
                                                    "at": int(time.time())}).encode())
    _tries.pop(project, None)
    return {"ok": True, "backup_locked": True}, 200


def backup_refusal(project, password):
    """(error payload, status) when a backup may not be handed over for this
    password, else None. Counts the misses."""
    import users
    lock = backup_locked(project)
    if not lock:
        return None
    n, since = _tries.get(project, (0, 0.0))
    if n >= LOCK_TRIES and time.time() - since < LOCK_HOLD:
        return {"error": f"{LOCK_TRIES} wrong backup passwords in a row: downloads of {project}'s keys "
                         f"wait {int((LOCK_HOLD - (time.time() - since)) // 60) + 1} more minutes"}, 429
    if not password:
        return {"error": f"{project}'s key backups need their password"}, 403
    if not users.check_password(lock["hash"], password):
        _tries[project] = (n + 1 if time.time() - since < LOCK_HOLD else 1, time.time())
        return {"error": "that is not the backup password"}, 403
    _tries.pop(project, None)
    return None


def secret(project, route, key=DEFAULT):
    """(keystore bytes, record with its passwords) for the node signing a
    job, or None. The one caller is the agent's job channel (step 2)."""
    rec = _record(project, route, key)
    if not rec or rec.get("locked"):
        return None
    try:
        blob = _read_secret(_dir(project, key) / f"{route}.ks")
    except (OSError, Locked):
        return None
    return blob, rec


def locked(project, route, key=DEFAULT):
    """Why a key cannot be opened here (its seal), or "": said by whatever
    asked for it rather than "no such key"."""
    return str((_record(project, route, key) or {}).get("locked") or "")


# ---- a release's APK, signed on the project's node (R106: the operator, 22 Oct)
# Four keystore secrets set by hand on GitHub failed three ways and one put a
# password in a public log. A release's APK is built unsigned in CI, fetched
# by the controller, which holds the key, and signed on the project's node by
# a sign-key job: the same steps the node's sign job takes (zipalign,
# apksigner with the proof of a rotation, verify, the certificate checked
# against the kept key), with the node's own tools, the key handed over for
# that job alone and the signed APK handed back.

def release_key(project, package=""):
    """(key name, its sideload record, "") for the key a release of
    `package` signs with: the one it is mapped to, else default, else the
    only sideload key, followed through a rotation to the newest; or
    ("", None, why) said in words when there is none to use."""
    if not _ok_project(project):
        return "", None, "unknown project"
    held = [k for k in key_names(project) if _record(project, "sideload", k)]
    if not held:
        return "", None, (f"{project} has no sideload signing key, which signs its releases: an "
                          "administrator adds or makes one in its Signing view (Ship)")
    mapped = mapping(project).get(package or "")
    key = key_for(project, package, "sideload")
    if mapped and not _record(project, "sideload", mapped):
        return "", None, f"{package} is mapped to {mapped}, which holds no sideload signing key"
    if not mapped and not _record(project, "sideload", key):
        return "", None, (f"{package or 'the app'} is mapped to no key, and {project} has {len(held)} sideload "
                          f"keys ({', '.join(held)}) and none named default: map it in the Signing view's Apps")
    key = successor(project, key)
    return key, _record(project, "sideload", key), ""


def sign_release(project, src, out):
    """Sign the unsigned APK at `src` into `out` with the project's sideload
    key for its package, on the project's node: the node reads the package
    and is handed the key that package signs with. {key, cert, schemes,
    package, rotated_from} or {error}."""
    chosen = {}

    def give(package):
        key, rec, why = release_key(project, package)
        if why:
            return None, why
        got = secret(project, "sideload", key)
        if not got:
            return None, locked(project, "sideload", key) or f"{project} has no sideload signing key named {key}"
        blob, rec = got
        chosen.update(key=key, sha256=str(rec.get("sha256") or ""))
        payload = {"keystore": base64.b64encode(blob).decode(), "alias": rec.get("alias") or "",
                   "store_pass": rec.get("store_pass") or "", "key_pass": rec.get("key_pass") or "",
                   "sha256": rec.get("sha256") or "", "key": key}
        if rec.get("rotated_from"):
            prev, proof = secret(project, "sideload", rec["rotated_from"]), lineage(project, key)
            if prev and proof:
                payload["previous"] = {"keystore": base64.b64encode(prev[0]).decode(),
                                       "alias": prev[1].get("alias") or "",
                                       "store_pass": prev[1].get("store_pass") or "",
                                       "key_pass": prev[1].get("key_pass") or "", "key": rec["rotated_from"]}
                payload["lineage"] = base64.b64encode(proof).decode()
                chosen["rotated_from"] = rec["rotated_from"]
        return payload, ""
    r = _on_node(project, "release", give, build_tools=True, file=str(src), out=str(out), timeout=900)
    if r.get("error"):
        return {"error": r["error"]}
    if not chosen.get("key") or r.get("key") != chosen["key"] or not os.path.isfile(out):
        return {"error": "the signed APK did not come back from the node"}
    return {"key": chosen["key"], "cert": chosen["sha256"], "package": str(r.get("package") or ""),
            "schemes": [x for x in r.get("schemes") or [] if re.fullmatch(r"v\d(\.\d)?", x)],
            **({"rotated_from": chosen["rotated_from"]} if chosen.get("rotated_from") else {})}


# ---- the key work on the project's node (R106, the operator 22 Oct) --------
# One sign-key job per piece of work, on the node the project's signing runs
# on. Its spec carries the op and a handover token and never a secret: what
# the job needs waits here under the token, handed to that job's own node
# once (hand_over, the agent channel's signing-key), and what it made comes
# back under it (take_result, signing-result; put_signed for an APK). The
# caller waits for it, as other waited jobs do.
TOOL_WORDS = {"jdk": ("jdk", "it"), "android:build-tools": ("Android SDK Build-Tools (apksigner)", "them")}
TITLES = {"inspect": "check a signing key", "generate": "make a signing key", "wrap": "wrap a key's backup",
          "rotate": "make a rotation's proof", "release": "sign a release's APK"}
MAX_APK = 400 << 20
_lock = threading.Lock()
_handover = {}


def _node(project):
    nid = (node_of(project) or "") if node_of else ""
    return nid, (node_get(nid) if node_get and nid else None)


def signer_name(project):
    """The name of the node the project's keys are worked on, or ""."""
    nid, n = _node(project)
    return str((n or {}).get("name") or nid)


def signer(project, build_tools=False):
    """(node id, why): the node the project's key work runs on, and what
    keeps it from running there now in words that name the node and what
    is missing, "" when nothing does."""
    nid, n = _node(project)
    if not nid:
        return "", f"{project} has no node to sign on: its settings choose one"
    if node_get and not n:
        return nid, f"{project}'s node {nid} is not enrolled any more: its settings choose another"
    if n:
        name = n.get("name") or nid
        if n.get("state") != "online":
            return nid, (f"{project}'s node {name} is {n.get('state') or 'not online'} and takes no new work, "
                         "and its keys are worked on there: its settings choose another")
        if n.get("kind") != "agent":
            return nid, f"{project}'s node {name} runs no agent to sign with"
        if not n.get("live"):
            return nid, (f"{project}'s node {name} is offline (its agent is not dialing in), and its keys "
                         "are worked on there: start it again, or choose another node in its settings")
        why = node_refuses(nid) if node_refuses else ""
        if why:
            return nid, why
        have = node_tools(n) if node_tools else set()
        # A node that has not said what its store holds is not one that
        # holds nothing: the job itself says so if it does not.
        for need in ("jdk", *(["android:build-tools"] if build_tools else [])):
            if have and need not in have:
                word, pron = TOOL_WORDS[need]
                return nid, f"{project}'s node {name} has no {word}: install {pron} on its Toolchains"
    return nid, ""


def _on_node(project, op, give, *, build_tools=False, file=None, out=None, timeout=120, by=""):
    """Run one piece of key work on the project's node and wait for it: the
    result the node sent back, or {error} (with `state` when what stopped it
    is the node's state rather than the key)."""
    nid, why = signer(project, build_tools)
    if why:
        return {"error": why, "state": True}
    name = signer_name(project)
    tok = secrets.token_hex(16)
    with _lock:
        _handover[tok] = {"project": project, "op": op, "give": give, "given": False, "file": file,
                          "out": out, "result": None, "job": ""}
    try:
        r = job_add(f"user:{by}" if by else "dashboard", {"node": nid}, "sign-key",
                    {"op": op, "handover": tok, "timeout": timeout, "title": TITLES[op]}, project=project)
        if r.get("error"):
            return {"error": f"{project}'s node {name} took no signing job: {r['error']}", "state": True}
        jid = r["job"]
        with _lock:
            _handover[tok]["job"] = jid
        deadline = time.time() + timeout + 30
        got = None
        while got is None:
            got = _handover[tok]["result"]
            if got is not None:
                break
            j = job_get(jid, with_log=False) if job_get else None
            if j and j.get("state") in ("succeeded", "failed", "canceled"):
                got = _handover[tok]["result"]
                if got is None:
                    return {"error": f"the signing job on {name} {j['state']}"
                                     + (f": {j['error']}" if j.get("error") else "")}
                break
            if time.time() > deadline:
                if job_cancel:
                    job_cancel("dashboard", jid)
                return {"error": f"{name} did not finish the signing job within {timeout} seconds"}
            time.sleep(0.2)
        if got.get("missing") in TOOL_WORDS:
            word, pron = TOOL_WORDS[got["missing"]]
            return {"error": f"{project}'s node {name} has no {word}: install {pron} on its Toolchains",
                    "state": True}
        return got
    finally:
        with _lock:
            _handover.pop(tok, None)


def _waiting(tok, jid):
    h = _handover.get(str(tok or ""))
    return h if h and h["job"] in ("", jid) else None


def hand_over(tok, jid, package=""):
    """(what the sign-key job `jid` needs, status, what to audit): once, to
    the job the token was made for. The channel has checked it is that
    job's own node and that the job runs."""
    with _lock:
        h = _waiting(tok, jid)
        if not h:
            return {"error": "no key work waits for this job"}, 404, {}
        if h["given"]:
            return {"error": "what this job needs was handed over already"}, 409, {}
        h["given"], h["job"] = True, jid
    give = h["give"]
    if callable(give):
        payload, why = give(package if PACKAGE.fullmatch(package or "") else "")
        if why:
            return {"error": why}, 404, {}
    else:
        payload = give
    return payload, 200, {"project": h["project"], "op": h["op"], "package": package,
                          "key": payload.get("key") or ""}


def handover_file(tok, jid):
    """The file the sign-key job `jid` was handed (a release's unsigned
    APK), or None."""
    with _lock:
        h = _waiting(tok, jid)
    return Path(h["file"]) if h and h.get("file") and os.path.isfile(h["file"]) else None


def put_signed(tok, jid, stream, length):
    """The signed APK the sign-key job `jid` sends back, into the path its
    caller named. (payload, status)."""
    with _lock:
        h = _waiting(tok, jid)
    if not h or not h.get("out") or h["op"] != "release":
        return {"error": "no signed APK is waited for from this job"}, 404
    if not 0 < length <= MAX_APK:
        return {"error": "that is not the size of an APK"}, 400
    out = Path(h["out"])
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    left = length
    with os.fdopen(fd, "wb") as f:
        while left > 0:
            chunk = stream.read(min(left, 1 << 20))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    if left:
        out.unlink(missing_ok=True)
        return {"error": "the APK did not arrive whole"}, 400
    return {"ok": True, "size": length}, 200


# What a sign-key job may answer, each field a string of at most this size.
RESULT = {"error": 400, "missing": 40, "alias": 200, "type": 20, "sha256": 95, "keystore": MAX_BYTES * 2,
          "lineage": MAX_BYTES * 2, "key": 32, "package": 200, "rotated_from": 32, "cert": 64}


def take_result(tok, jid, req):
    """What the sign-key job `jid` made, or why it could not: kept for the
    caller waiting on it, and nothing else. (payload, status)."""
    with _lock:
        h = _waiting(tok, jid)
        if not h:
            return {"error": "no key work waits for this job"}, 404
        if h["result"] is not None:
            return {"error": "this job answered already"}, 409
        got = {k: str(req.get(k) or "")[:n] for k, n in RESULT.items() if req.get(k)}
        if isinstance(req.get("schemes"), list):
            got["schemes"] = [str(x)[:8] for x in req["schemes"][:6]]
        h["result"] = got
    return {"ok": True}, 200


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
        return {"error": f"{project} has no {WORDS[route]}: an administrator adds one in "
                         "its Signing view (Ship)"}, 404
    # With no key named, the build's package decides on the node; when no
    # key is called default, several hold the route and none is mapped, no
    # package can find one, so it is refused here rather than after a
    # person allowed it (B509).
    if not key and not _record(project, route, DEFAULT):
        holders = [k for k in key_names(project) if _record(project, route, k)]
        if len(holders) > 1 and not set(mapping(project).values()) & set(holders):
            return {"error": f"{project} has no {WORDS[route]} named default and {len(holders)} others "
                             f"({', '.join(holders)}): name one with --key"}, 400
    rel = str(rel or "").replace("\\", "/").strip()
    rel = rel[len("dist/"):] if rel.startswith("dist/") else rel
    if not rel.lower().endswith((".apk", ".aab")):
        return {"error": "an Android build is an .apk or an .aab"}, 400
    if file_path(project, rel) is None:
        return {"error": f"no {rel} in {project}'s dist/: bb build puts a build there"}, 404
    if not (node_of(project) or ""):
        return {"error": f"{project} has no node to sign on: its settings choose one"}, 400
    # A node whose agent is behind takes nothing but its own update, so the
    # signing would be allowed and then refused (B515): said before the ask.
    why = node_refuses(node_of(project)) if node_refuses else ""
    if why:
        return {"error": why}, 409
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
    if act == "rotate":
        return rotate(project, str(req.get("from") or ""), str(req.get("to") or ""), by=by)
    if act == "remove":
        return remove(project, route, key)
    if act == "import":
        return import_backup(project, route, str(req.get("backup") or ""), str(req.get("key") or ""),
                             str(req.get("password") or ""), str(req.get("alias") or ""),
                             str(req.get("filename") or ""), by=by)
    return {"error": f"unknown action {act!r}"}, 400
