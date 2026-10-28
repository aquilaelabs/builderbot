"""Moving a controller to another home without losing its nodes (R90 step
12): from a container to another container on another host, from a
container to bare metal, and back.

Prepare to move on the old controller arms the move: a move token shown
once, a key derived from it kept here, and from then on every node hears
on its hello where the controller is going and a challenge of its own that
only a holder of the key answers. The move stays armed until it is
forgotten or it lands (R175: no life on the token, so a controller is
prepared days ahead and a node off for a weekend still hears it). The
bundle is packed fresh under that key each time it is downloaded or pulled,
so what moves is the state at the moment of moving: the whole state (the
JSON records, the database, the stores paths.py may have moved: project
snapshots, the git relay, the Git view's area, images), the canonical
repositories under the workspace when asked (left out when both homes mount
the same share), the deploy key, and what is sealed under the install key,
with the install key itself carried only when the person ticks it. The new
install's first run takes the bundle and the token, or the old controller's
address and the token and pulls the bundle from it, holds it to the version
gate (never onto an older build), restores it and restarts; each node knocks
on the new address when the old goes quiet, checks the answer and re-adopts
the controller by itself. The landing is told both ways under the move key
(the new controller tells the old, the old asks the new), and the old one
marks itself moved on either: read-only, saying where it went, and handing
a node that never heard the move its challenge in the same breath, so a
late node knocks and follows too. A node that outlived the old controller
is followed by hand with one line the new controller's Nodes page gives
(the agent's follow verb), never enrolled again.

The bundle's shape: a header line BBMOVE1, a JSON manifest (version, state
version, made at, the old address, what it carries, the sha256 of the
token, nothing secret), a newline, then the sealed tar.gz (ChaCha20-Poly1305
under HKDF(token)).
"""
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import shutil
import ssl
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE = Path("/config")
WORKSPACE = Path("/workspace")
SECRETS = ""
HEADER = b"BBMOVE1\n"
# A stick's backup (R161 step 4, backup.py): the same bundle sealed under a
# password's key, with its own header, opened by restore with the key.
BACKUP_HEADER = b"BBBACKUP1\n"
# What the state carries that is nobody's to move: logs, CI logs, the job
# trees, the apps fetched from the releases, this module's own output.
LEAVE = {"logs", "ci-logs", "snapshots", "apps", "move", "csp-reports.json", "held.json", "clean-shutdown", "booted", "hold-next"}

_lock = threading.Lock()
write_json = None
seal = None
open_with = None
state_version = lambda: 0           # noqa: E731
build_version = lambda: ""          # noqa: E731
install_key = lambda: b""           # noqa: E731
store_paths = lambda: {}            # noqa: E731
page_url = lambda: ""               # noqa: E731
node_ids = lambda: []               # noqa: E731
bare_metal = lambda: False          # noqa: E731
# Each node's last hello, {nid: epoch}: how many have heard an armed move,
# and which have not knocked since a move landed here (R175).
node_seen = lambda: {}              # noqa: E731
node_name = lambda nid: nid         # noqa: E731
audit = lambda who, what, detail: None    # noqa: E731
# The other controller, asked over HTTP(S): a wait of this many seconds.
PEER_TIMEOUT = 15
# How often the loop asks or tells (server._move_loop), and how long a
# fetch's nonce is good: a replayed fetch repacks the state for nobody.
TICK_S = 60
NONCE_LIFE = 600


def configure(*, state, workspace, secrets_dir, write_json_fn, seal_fn, open_fn, state_version_fn, build_version_fn,
              install_key_fn, store_paths_fn, page_url_fn, node_ids_fn, bare_metal_fn, node_seen_fn=None, node_name_fn=None,
              audit_fn=None):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), SECRETS=secrets_dir or "", write_json=write_json_fn,
                     seal=seal_fn, open_with=open_fn, state_version=state_version_fn, build_version=build_version_fn,
                     install_key=install_key_fn, store_paths=store_paths_fn, page_url=page_url_fn, node_ids=node_ids_fn,
                     bare_metal=bare_metal_fn, node_seen=node_seen_fn or (lambda: {}), node_name=node_name_fn or (lambda nid: nid),
                     audit=audit_fn or (lambda who, what, detail: None))


def _file():
    return STATE / "move.json"


def _load():
    try:
        with open(_file()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _save(d):
    write_json(_file(), d)


def new_token():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def key_of(token):
    """The sealing key from the token: HKDF-SHA256 with a fixed info."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"builderbot move v1").derive(token.encode())


def token_hash(token):
    return hashlib.sha256(b"builderbot move token\0" + token.encode()).hexdigest()


def challenge(key, nid):
    """What the old controller tells a node to expect, and the answer only
    a holder of the key gives (the new controller, once restored)."""
    return hmac.new(key, b"challenge\0" + str(nid).encode(), hashlib.sha256).hexdigest()


# The proofs the two controllers show each other (R175), each an HMAC under
# the move key over what it is for, so one is never good for another, and
# none of them is the token or opens the bundle.
def landed_proof(key, at):
    """The new controller's word that the bundle landed, at `at`."""
    return hmac.new(key, b"landed\0" + str(int(at)).encode(), hashlib.sha256).hexdigest()


def asked_proof(key, nonce):
    """The old controller's question, did it land here: fresh each time."""
    return hmac.new(key, b"asked\0" + str(nonce).encode(), hashlib.sha256).hexdigest()


def fetch_proof(key, nonce):
    """The new controller's right to pull the bundle, once per nonce."""
    return hmac.new(key, b"fetch\0" + str(nonce).encode(), hashlib.sha256).hexdigest()


def _key():
    try:
        return base64.b64decode(_load()["key_b64"])
    except (KeyError, ValueError):
        return b""


def armed():
    """An armed move on this, the old, controller: prepared and not
    forgotten, whether or not it has landed; never on the controller the
    state landed on (its record came with the bundle)."""
    d = _load()
    return bool(d.get("made_at") and d.get("key_b64") and not d.get("restored_at"))


def status():
    """What Controller settings shows: a move armed (where to, when, how
    many nodes have heard it, when the bundle was last packed and its
    size), or this controller moved (where to, how it learned), or nothing."""
    d = _load()
    out = {"prepared": False, "moved": False}
    if d.get("moved_to"):
        out.update(moved=True, to=d["moved_to"], at=d.get("moved_at", 0), how=d.get("moved_how", "pressed"),
                   landed_at=int(d.get("landed_at") or 0))
    if d.get("made_at") and not d.get("used") and not d.get("restored_at"):
        seen = node_seen() or {}
        heard = [nid for nid in node_ids() if int(seen.get(nid) or 0) >= int(d["made_at"])]
        out.update(prepared=True, to=d.get("to", ""), made_at=d["made_at"], heard=len(heard), nodes=len(list(node_ids())),
                   bundle=d.get("bundle", ""), packed_at=int(d.get("packed_at") or 0), size=int(d.get("size") or 0),
                   repos=bool(d.get("repos")), carries_key=bool(d.get("carries_key")),
                   stores=d.get("stores") if isinstance(d.get("stores"), list) else sorted(k for k in (store_paths() or {}) if k not in STORES_OFF),
                   asked_at=int(d.get("asked_at") or 0), asked_error=d.get("asked_error", ""))
    return out


def bundle_path():
    d = _load()
    p = STATE / "move" / str(d.get("bundle") or "")
    return p if d.get("bundle") and p.is_file() else None


def _tar_tree(tar, src, arc, leave=()):
    src = Path(src)
    if not src.exists():
        return 0
    n = 0
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if rel.parts and rel.parts[0] in leave:
            continue
        if p.is_symlink() or not (p.is_file() or p.is_dir()):
            continue
        if p.is_file():
            tar.add(str(p), arcname=f"{arc}/{rel.as_posix()}", recursive=False)
            n += 1
    return n


# The stores a bundle leaves out unless ticked (R175 step 7): what LEAVE
# leaves out of the state when they live under it.
STORES_OFF = {"logs", "job-snapshots"}


def _size_of(src, leave=()):
    """Bytes under a tree, symlinks not followed; 0 for nothing there."""
    src = Path(src)
    if not src.exists():
        return 0
    n = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        if rel.parts and rel.parts[0] in leave:
            dirs[:] = []
            continue
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            if not os.path.islink(os.path.join(root, f)):
                n += st.st_size
    return n


def pieces():
    """What a bundle may carry, each with its size here, for the ticks on
    Controller settings (R175 step 7): the state always; each store kept
    outside it (on unless it is logs or the job trees); the repositories
    (off: both homes may mount the same share); the install key (off: the
    new home asks for it)."""
    out = [{"key": "state", "label": "The state", "about": "accounts, nodes, projects, settings, the notebooks, the database, what is sealed",
            "size": _size_of(STATE, LEAVE), "on": True, "fixed": True}]
    for kind, path in (store_paths() or {}).items():
        if path and not str(path).startswith(str(STATE)):
            out.append({"key": f"store:{kind}", "label": kind, "about": str(path), "size": _size_of(path), "on": kind not in STORES_OFF})
    if SECRETS and Path(SECRETS).is_dir():
        out.append({"key": "secrets", "label": "The deploy key and the secrets", "about": SECRETS, "size": _size_of(SECRETS), "on": True, "fixed": True})
    out.append({"key": "repos", "label": "The repositories", "about": f"{WORKSPACE}: leave off when both homes mount the same share",
                "size": _size_of(WORKSPACE), "on": False})
    out.append({"key": "install_key", "label": "The install key", "about": "else the new home asks for it", "size": len(install_key() or b""), "on": False})
    return out


def pack(repos=False, carry_key=False, stores=None):
    """The tree a move or a backup carries, as one gzipped tar in memory:
    the state without its logs and job trees, the stores kept outside it
    (`stores` names the kinds; None is every kind but STORES_OFF), the
    repositories when asked, the secrets, the install key when asked.
    Returns (bytes, counts)."""
    buf = io.BytesIO()
    counts = {}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        counts["state"] = _tar_tree(tar, STATE, "state", leave=LEAVE)
        for kind, path in (store_paths() or {}).items():
            if path and not str(path).startswith(str(STATE)) and (kind in stores if stores is not None else kind not in STORES_OFF):
                counts[kind] = _tar_tree(tar, path, f"stores/{kind}")
        if repos:
            counts["repos"] = _tar_tree(tar, WORKSPACE, "workspace")
        if SECRETS and Path(SECRETS).is_dir():
            counts["secrets"] = _tar_tree(tar, SECRETS, "secrets")
        if carry_key:
            k = install_key() or b""
            if k:
                info = tarfile.TarInfo("install-key")
                info.size = len(k)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(k))
                counts["install_key"] = 1
    return buf.getvalue(), counts


def prepare(principal, to, repos=False, carry_key=False, stores=None):
    """The move armed: a new token, returned once and never kept, its key
    kept here, the nodes told from the next hello, and a first bundle
    packed under it (repacked fresh by each download or pull). `stores`
    names the store kinds it carries (None: every kind but STORES_OFF)."""
    to = str(to or "").strip().rstrip("/")
    if to and not to.startswith(("http://", "https://")):
        return {"error": "the new home's address is where its page will be reached, as http:// or https://"}
    if _load().get("moved_to"):
        return {"error": "this controller has moved already; nothing more leaves here"}
    token = new_token()
    key = key_of(token)
    made_at = int(time.time())
    # The record first, so the bundle carries it: the new home answers the
    # nodes' knocks from the key kept here, under the state that moved.
    with _lock:
        d = _load()
        for old in (STATE / "move").glob("*.bbmove"):
            old.unlink(missing_ok=True)
        d = {k: v for k, v in d.items() if k in ("moved_to", "moved_at")}
        d.update(made_at=made_at, to=to, bundle="", size=0, used=False, repos=bool(repos), carries_key=bool(carry_key),
                 stores=sorted(str(k) for k in stores) if stores is not None else None,
                 token_hash=token_hash(token), key_b64=base64.b64encode(key).decode(), by=str(principal)[:80])
        _save(d)
    r = pack_bundle()
    if r.get("error"):
        return r
    return {"ok": True, "token": token, "bundle": r["bundle"], "size": r["size"], "counts": r["counts"], "to": to, "made_at": made_at}


def pack_bundle():
    """The bundle packed fresh under the armed move's key, written under
    STATE/move in place of the one before (R175: what moves is the state
    at the moment of moving, not at Prepare). {ok, bundle, size, counts}
    or {error}."""
    d = _load()
    key = _key()
    if not d.get("made_at") or not key or d.get("restored_at"):
        return {"error": "no move is prepared"}
    out_dir = STATE / "move"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"builderbot-move-{stamp}.bbmove"
    raw, counts = pack(repos=bool(d.get("repos")), carry_key=bool(d.get("carries_key")),
                       stores=set(d["stores"]) if isinstance(d.get("stores"), list) else None)
    sealed = seal(raw, key)
    manifest = {"format": 1, "version": build_version(), "state_version": int(state_version() or 0), "made_at": int(d["made_at"]),
                "packed_at": int(time.time()), "from": page_url(), "to": d.get("to", ""), "repos": bool(d.get("repos")),
                "carries_key": bool(d.get("carries_key") and counts.get("install_key")),
                "nodes": list(node_ids()), "bare_metal": bool(bare_metal()), "counts": counts, "token_hash": d.get("token_hash", "")}
    tmp = out_dir / (name + ".partial")
    with open(tmp, "wb") as f:
        f.write(HEADER)
        f.write(json.dumps(manifest).encode() + b"\n")
        f.write(sealed)
    os.replace(tmp, out_dir / name)
    with _lock:
        d = _load()
        for old in out_dir.glob("*.bbmove"):
            if old.name != name:
                old.unlink(missing_ok=True)
        d.update(bundle=name, size=(out_dir / name).stat().st_size, packed_at=manifest["packed_at"], carries_key=manifest["carries_key"])
        _save(d)
    return {"ok": True, "bundle": name, "size": d["size"], "counts": counts}


def forget(principal):
    """The armed move withdrawn: the bundle gone, the nodes told nothing more."""
    with _lock:
        d = _load()
        if not d.get("made_at") or d.get("restored_at"):
            return {"error": "no move is prepared"}
        if d.get("moved_to"):
            return {"error": "this controller has moved; the move is not withdrawn after it landed"}
        for old in (STATE / "move").glob("*.bbmove"):
            old.unlink(missing_ok=True)
        d = {k: v for k, v in d.items() if k in ("moved_to", "moved_at")}
        _save(d)
    return {"ok": True}


def for_node(nid):
    """What a node's hello carries while a move is armed, and what the old
    controller's "moved" answer carries after (R175: a node that never
    heard the move hears it then and knocks): the new address and that
    node's challenge; {} with no move armed, and {} on the controller the
    move landed on, whose record came with the bundle."""
    d = _load()
    if not d.get("made_at") or not d.get("to") or d.get("restored_at"):
        return {}
    key = _key()
    if not key:
        return {}
    return {"url": d.get("moved_to") or d["to"], "expect": challenge(key, nid)}


def answer_for(nid):
    """The new controller's answer to a node's knock, once the bundle is
    restored here (the record came with it): the challenge the old
    controller told that node to expect, which only a holder of the move
    key can say back; "" when no move landed here."""
    d = _load()
    if not d.get("key_b64") or not d.get("restored_at"):
        return ""
    try:
        key = base64.b64decode(d["key_b64"])
    except ValueError:
        return ""
    return challenge(key, nid)


def mark_moved(to, how="pressed", landed_at=0):
    """The old controller, once the new one is up: read-only, saying where,
    and how it learned (pressed, told by the new controller, or asked)."""
    with _lock:
        d = _load()
        d.update(moved_to=str(to or "")[:200], moved_at=int(time.time()), used=True, moved_how=how,
                 landed_at=int(landed_at or d.get("landed_at") or 0))
        _save(d)
    return {"ok": True, "to": d["moved_to"], "how": how}


def moved_to():
    return str(_load().get("moved_to") or "")


# ---- the landing, told both ways (R175 step 4) --------------------------------

def take_landing(req):
    """POST /api/v1/move/landed on the old controller: the new controller's
    word that the bundle landed, {hash, at, proof, here}. The hash names
    the armed move, the proof is HMAC(key, landed\0at); right, this
    controller marks itself moved to the address it was prepared for (or
    the one the new controller says it is at, when none was named).
    (payload, status)."""
    d = _load()
    if not armed():
        return {"error": "no move is prepared here"}, 404
    if d.get("moved_to"):
        return {"ok": True, "moved": True, "to": d["moved_to"]}, 200
    if str(req.get("hash") or "") != str(d.get("token_hash") or ""):
        return {"error": "not this controller's move"}, 403
    try:
        at = int(req.get("at") or 0)
    except (TypeError, ValueError):
        at = 0
    want = landed_proof(_key(), at)
    if not at or not hmac.compare_digest(str(req.get("proof") or ""), want):
        return {"error": "the proof does not verify"}, 403
    to = d.get("to") or str(req.get("here") or "").strip().rstrip("/")[:200]
    r = mark_moved(to, how="told", landed_at=at)
    audit("controller", "moved-by-landing", {"to": to, "landed_at": at})
    return {"ok": True, "moved": True, "to": r["to"]}, 200


def answer_asked(q):
    """GET /api/v1/move/landed?hash=..&nonce=..&proof=.. on the new
    controller: the old controller asking whether its bundle landed here.
    The proof is HMAC(key, asked\0nonce) under the key that came with the
    bundle. (payload, status)."""
    d = _load()
    if not d.get("restored_at") or not d.get("key_b64"):
        return {"error": "no move landed here"}, 404
    if str(q.get("hash") or "") != str(d.get("token_hash") or ""):
        return {"error": "not this controller's move"}, 403
    nonce = str(q.get("nonce") or "")[:64]
    if not nonce or not hmac.compare_digest(str(q.get("proof") or ""), asked_proof(_key(), nonce)):
        return {"error": "the proof does not verify"}, 403
    return {"ok": True, "landed_at": int(d["restored_at"]), "here": page_url() or d.get("to", "")}, 200


def _peer_ctx():
    """TLS to the other controller: not verified, since neither knows the
    other's certificate; what is said either way is an HMAC under the move
    key, which a listener can neither forge nor use, and the bundle is
    sealed. Said in docs/install.md."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _peer_json(url, body=None, timeout=None):
    """One call to the other controller: (status, dict)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"User-Agent": "BuilderBot", **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout or PEER_TIMEOUT, context=_peer_ctx()) as r:
            raw = r.read()
            st = r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read(), e.code
    except (OSError, ValueError) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}
    try:
        j = json.loads(raw) if raw else {}
    except ValueError:
        j = {"error": raw[:200].decode("utf-8", "replace")}
    return st, j if isinstance(j, dict) else {}


def ask_new(force=False):
    """The old controller, armed and not yet marked moved, asking the new
    address whether the bundle landed there; marked moved on a verified
    yes. Once per TICK_S unless forced. True when it learned so."""
    d = _load()
    if not armed() or d.get("moved_to") or not d.get("to"):
        return False
    now = int(time.time())
    if not force and now - int(d.get("asked_at") or 0) < TICK_S:
        return False
    nonce = secrets.token_hex(16)
    q = urllib.parse.urlencode({"hash": d.get("token_hash", ""), "nonce": nonce, "proof": asked_proof(_key(), nonce)})
    st, r = _peer_json(f"{d['to'].rstrip('/')}/api/v1/move/landed?{q}")
    with _lock:
        d = _load()
        d.update(asked_at=now, asked_error="" if st == 200 or st == 404 else (r.get("error") or f"answered {st}"))
        _save(d)
    if st == 200 and r.get("ok") and r.get("landed_at"):
        mark_moved(d.get("to") or r.get("here", ""), how="asked", landed_at=r["landed_at"])
        audit("controller", "moved-by-asking", {"to": d.get("to", ""), "landed_at": r["landed_at"]})
        return True
    return False


def tell_old(force=False):
    """The new controller, once the bundle landed here, telling the old
    address so until it answers (200: taken; 404: no move armed there any
    more, which is an answer too). Once per TICK_S unless forced. True
    once it has been told."""
    d = _load()
    if not d.get("restored_at") or d.get("told_at") or not d.get("came_from"):
        return bool(d.get("told_at"))
    now = int(time.time())
    if not force and now - int(d.get("tell_tried_at") or 0) < TICK_S:
        return False
    body = {"hash": d.get("token_hash", ""), "at": int(d["restored_at"]), "proof": landed_proof(_key(), int(d["restored_at"])),
            "here": page_url() or d.get("to", "")}
    st, r = _peer_json(f"{str(d['came_from']).rstrip('/')}/api/v1/move/landed", body)
    with _lock:
        d = _load()
        d["tell_tried_at"] = now
        if st in (200, 404):
            d["told_at"] = now
            d["told_how"] = "taken" if st == 200 else "no move armed there"
        else:
            d["tell_error"] = r.get("error") or (f"answered {st}" if st else "no answer")
        _save(d)
    return st in (200, 404)


def tick():
    """The loop's pass (server._move_loop): the old side asks, the new side
    tells, whichever this controller is."""
    ask_new()
    tell_old()


# ---- the pull (R175 step 5) ------------------------------------------------------

def serve_fetch(q):
    """GET /api/v1/move/bundle?hash=..&nonce=..&proof=.. on the old
    controller: the new install pulling the bundle with a proof derived
    from the token (HMAC(key, fetch\0nonce)), the bundle packed fresh for
    it; a nonce is good once and for NONCE_LIFE. (path, "") or ("", why,
    status)."""
    d = _load()
    if not armed():
        return "", "no move is prepared here", 404
    if d.get("moved_to"):
        return "", "this controller has moved already", 410
    if str(q.get("hash") or "") != str(d.get("token_hash") or ""):
        return "", "not this controller's move", 403
    nonce = str(q.get("nonce") or "")[:64]
    if not nonce or not hmac.compare_digest(str(q.get("proof") or ""), fetch_proof(_key(), nonce)):
        return "", "the proof does not verify", 403
    now = int(time.time())
    with _lock:
        d = _load()
        used = {k: v for k, v in (d.get("fetch_nonces") or {}).items() if now - int(v) < NONCE_LIFE}
        if nonce in used:
            return "", "that proof was used already", 403
        used[nonce] = now
        d["fetch_nonces"] = used
        _save(d)
    r = pack_bundle()
    if r.get("error"):
        return "", r["error"], 500
    audit("controller", "move-bundle-pulled", {"bundle": r["bundle"], "size": r["size"]})
    return str(STATE / "move" / r["bundle"]), "", 200


def fetch_bundle(old_url, token, dest):
    """The new install pulling the bundle from the old controller into
    `dest`, under the proof the token derives. "" or why."""
    old_url = str(old_url or "").strip().rstrip("/")
    if not old_url.startswith(("http://", "https://")):
        return "the old controller's address is where its page is reached, as http:// or https://"
    key = key_of(token)
    nonce = secrets.token_hex(16)
    q = urllib.parse.urlencode({"hash": token_hash(token), "nonce": nonce, "proof": fetch_proof(key, nonce)})
    req = urllib.request.Request(f"{old_url}/api/v1/move/bundle?{q}", headers={"User-Agent": "BuilderBot"})
    try:
        with urllib.request.urlopen(req, timeout=3600, context=_peer_ctx()) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read()).get("error") or f"answered {e.code}"
        except (ValueError, AttributeError):
            why = f"answered {e.code}"
        return f"the old controller did not hand the bundle over: {why}"
    except (OSError, ValueError) as e:
        return f"the old controller at {old_url} did not answer: {type(e).__name__}: {e}"
    return ""


# ---- the nodes not yet here (R175 step 3) ------------------------------------------

def follow_line(nid):
    """The one line to run on a node that outlived the old controller: the
    agent's follow verb with this address and the challenge this
    controller holds the key for."""
    d = _load()
    key = _key()
    if not d.get("restored_at") or not key:
        return ""
    return f"builderbot-agent follow {page_url() or d.get('to', '')} {challenge(key, nid)}"


def not_yet_here():
    """On the controller a move landed on: the nodes the bundle named that
    have not said hello since, each with its follow line; [] elsewhere."""
    d = _load()
    if not d.get("restored_at"):
        return []
    seen = node_seen() or {}
    out = []
    for nid in d.get("nodes") or []:
        if int(seen.get(nid) or 0) < int(d["restored_at"]):
            out.append({"id": nid, "name": node_name(nid), "line": follow_line(nid)})
    return out


def read_manifest(path):
    """The bundle's manifest, or (None, why)."""
    try:
        with open(path, "rb") as f:
            head = f.readline()
            if head not in (HEADER, BACKUP_HEADER):
                return None, "not a BuilderBot move bundle or backup"
            line = f.readline()
        m = json.loads(line)
        if isinstance(m, dict) and head == BACKUP_HEADER:
            m["kind"] = "backup"
        return (m, "") if isinstance(m, dict) and m.get("format") == 1 else (None, "a bundle of a format this build does not read")
    except (OSError, ValueError) as e:
        return None, f"could not read the bundle: {e}"


def restore(path, token="", state_dir=None, workspace_dir=None, secrets_dir=None, build_state_version=None, here_bare_metal=None, key=None):
    """The bundle unsealed under the token and put in place of the state here
    (the state as it is moved aside, as a reset does), its stores where the
    records name them, the repositories into the workspace, the secrets into
    theirs, the install key where it is read; held to the version gate first:
    never onto a build whose state version is older than the bundle's.
    Returns {ok, moved_aside, counts} or {error}."""
    state_dir = Path(state_dir or STATE)
    workspace_dir = Path(workspace_dir or WORKSPACE)
    secrets_dir = Path(secrets_dir) if secrets_dir else (Path(SECRETS) if SECRETS else None)
    here_ver = int(build_state_version if build_state_version is not None else state_version() or 0)
    m, why = read_manifest(path)
    if not m:
        return {"error": why}
    if int(m.get("state_version") or 0) > here_ver:
        return {"error": f"the bundle's state is at version {m.get('state_version')} and this build reads up to {here_ver}: "
                         "a move never lands on an older build; update this install first"}
    # A backup opens under the key its password derives (backup.py); a
    # move under its token's.
    if key is None:
        if m.get("kind") == "backup":
            return {"error": "a backup opens under its password, not a move token"}
        if token_hash(token) != m.get("token_hash"):
            return {"error": "that is not this bundle's move token"}
        key = key_of(token)
    with open(path, "rb") as f:
        f.readline(); f.readline()
        sealed = f.read()
    try:
        raw = open_with(key, sealed)
    except Exception:                                              # noqa: BLE001 (any failure to open is one answer)
        return {"error": "the bundle did not open under that " + ("password" if m.get("kind") == "backup" else "token")}
    work = Path(tempfile.mkdtemp(prefix=".move-", dir=str(state_dir.parent)))
    counts = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            for info in tar.getmembers():
                if not info.isfile() or info.name.startswith("/") or ".." in Path(info.name).parts:
                    continue
                tar.extract(info, path=str(work), filter="data") if hasattr(tarfile, "data_filter") else tar.extract(info, path=str(work))
                top = Path(info.name).parts[0]
                counts[top] = counts.get(top, 0) + 1
        stamp = time.strftime("%Y%m%d-%H%M%S")
        aside = state_dir.parent / f"{state_dir.name}.moved-{stamp}"
        # The state: what is here moved aside whole, the bundle's put in place.
        if state_dir.exists():
            os.rename(state_dir, aside)
        shutil.move(str(work / "state"), str(state_dir))
        # The stores, where the restored records name them (their paths may
        # not exist on this machine: then under the state, and paths.py says
        # so on the Storage page).
        for kind_dir in (work / "stores").iterdir() if (work / "stores").is_dir() else []:
            dest = (store_paths() or {}).get(kind_dir.name) or (state_dir / kind_dir.name)
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.copytree(str(kind_dir), str(dest), dirs_exist_ok=True)
            else:
                shutil.move(str(kind_dir), str(dest))
        if (work / "workspace").is_dir():
            workspace_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(work / "workspace"), str(workspace_dir), dirs_exist_ok=True)
        if (work / "secrets").is_dir() and secrets_dir:
            secrets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copytree(str(work / "secrets"), str(secrets_dir), dirs_exist_ok=True)
        if (work / "install-key").is_file():
            k = (work / "install-key").read_bytes()
            keydir = state_dir / ".install-key"
            keydir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with open(keydir / "key", "wb") as f:
                f.write(k)
            os.chmod(keydir / "key", 0o600)
        # The move's own record, carried with the state: now the new home's,
        # which answers the nodes' knocks and knows where it came from.
        rec_path = state_dir / "move.json"
        try:
            with open(rec_path) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            rec = {}
        rec.update(restored_at=int(time.time()), used=True, came_from=m.get("from", "") if m.get("kind") != "backup" else "",
                   source_bare_metal=bool(m.get("bare_metal")),
                   here_bare_metal=bool(here_bare_metal if here_bare_metal is not None else bare_metal()),
                   nodes=list(m.get("nodes") or []))
        if m.get("kind") == "backup":
            rec["came_from_backup"] = True
        for k in ("moved_to", "moved_at", "moved_how", "landed_at", "asked_at", "asked_error", "fetch_nonces", "told_at", "tell_tried_at",
                  "tell_error", "told_how"):
            rec.pop(k, None)
        with open(rec_path, "w") as f:
            json.dump(rec, f)
        return {"ok": True, "moved_aside": str(aside) if state_dir != aside else "", "counts": counts, "from": m.get("from", ""),
                "nodes": list(m.get("nodes") or [])}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restored():
    """Whether this state arrived by a move, and from where: for the first
    run's page and the Nodes page's "checking back in"."""
    d = _load()
    return {"restored_at": int(d.get("restored_at") or 0), "from": d.get("came_from", "") or ("a backup" if d.get("came_from_backup") else ""),
            "source_bare_metal": bool(d.get("source_bare_metal")), "told_at": int(d.get("told_at") or 0),
            "told_how": d.get("told_how", ""), "tell_error": d.get("tell_error", "")} if d.get("restored_at") else {}
