"""Moving a controller to another home without losing its nodes (R90 step
12): from a container to another container on another host, from a
container to bare metal, and back.

Prepare to move on the old controller writes a move bundle: one file,
sealed under a key derived from a move token shown once (good for one move
and 72 hours), holding the whole state (the JSON records, the database, the
stores paths.py may have moved: project snapshots, the git relay, the Git
view's area, images), the canonical repositories under the workspace when
asked (left out when both homes mount the same share), the deploy key, and
what is sealed under the install key, with the install key itself carried
only when the person ticks it. The nodes are told the move is coming on
their next hello: the new address and a challenge only a holder of the
token answers. The new install's first run takes the bundle and the token,
holds it to the version gate (never onto an older build), restores it and
restarts; each node knocks on the new address when the old goes quiet,
checks the answer and re-adopts the controller by itself. The old one is
marked moved and stays read-only, saying where it went.

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
import tarfile
import tempfile
import threading
import time
from pathlib import Path

STATE = Path("/config")
WORKSPACE = Path("/workspace")
SECRETS = ""
TOKEN_LIFE = 72 * 3600
HEADER = b"BBMOVE1\n"
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


def configure(*, state, workspace, secrets_dir, write_json_fn, seal_fn, open_fn, state_version_fn, build_version_fn,
              install_key_fn, store_paths_fn, page_url_fn, node_ids_fn, bare_metal_fn):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), SECRETS=secrets_dir or "", write_json=write_json_fn,
                     seal=seal_fn, open_with=open_fn, state_version=state_version_fn, build_version=build_version_fn,
                     install_key=install_key_fn, store_paths=store_paths_fn, page_url=page_url_fn, node_ids=node_ids_fn,
                     bare_metal=bare_metal_fn)


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


def status():
    """What Controller settings shows: a move prepared (where to, when, how
    long the token is good, the bundle's size), or this controller moved
    (where to), or nothing."""
    d = _load()
    out = {"prepared": False, "moved": False}
    if d.get("moved_to"):
        out.update(moved=True, to=d["moved_to"], at=d.get("moved_at", 0))
    if d.get("made_at") and not d.get("used"):
        left = max(0, int(d["made_at"]) + TOKEN_LIFE - int(time.time()))
        out.update(prepared=left > 0, to=d.get("to", ""), made_at=d["made_at"], left=left,
                   bundle=d.get("bundle", ""), size=int(d.get("size") or 0), repos=bool(d.get("repos")), carries_key=bool(d.get("carries_key")))
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


def prepare(principal, to, repos=False, carry_key=False):
    """The bundle written under STATE/move, sealed under a new token, which
    is returned once and never kept; the nodes told from the next hello."""
    to = str(to or "").strip().rstrip("/")
    if to and not to.startswith(("http://", "https://")):
        return {"error": "the new home's address is where its page will be reached, as http:// or https://"}
    if _load().get("moved_to"):
        return {"error": "this controller has moved already; nothing more leaves here"}
    token = new_token()
    key = key_of(token)
    out_dir = STATE / "move"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"builderbot-move-{stamp}.bbmove"
    made_at = int(time.time())
    # The record first, so the bundle carries it: the new home answers the
    # nodes' knocks from the key kept here, under the state that moved.
    with _lock:
        d = _load()
        for old in out_dir.glob("*.bbmove"):
            old.unlink(missing_ok=True)
        d.update(made_at=made_at, to=to, bundle=name, size=0, used=False, repos=bool(repos), carries_key=bool(carry_key),
                 token_hash=token_hash(token), key_b64=base64.b64encode(key).decode(), by=str(principal)[:80])
        _save(d)
    buf = io.BytesIO()
    counts = {}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        counts["state"] = _tar_tree(tar, STATE, "state", leave=LEAVE)
        for kind, path in (store_paths() or {}).items():
            if path and not str(path).startswith(str(STATE)):
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
    sealed = seal(buf.getvalue(), key)
    manifest = {"format": 1, "version": build_version(), "state_version": int(state_version() or 0), "made_at": made_at,
                "from": page_url(), "to": to, "repos": bool(repos), "carries_key": bool(carry_key and counts.get("install_key")),
                "nodes": list(node_ids()), "bare_metal": bool(bare_metal()), "counts": counts, "token_hash": token_hash(token)}
    tmp = out_dir / (name + ".partial")
    with open(tmp, "wb") as f:
        f.write(HEADER)
        f.write(json.dumps(manifest).encode() + b"\n")
        f.write(sealed)
    os.replace(tmp, out_dir / name)
    with _lock:
        d = _load()
        d.update(size=(out_dir / name).stat().st_size, carries_key=manifest["carries_key"])
        _save(d)
    return {"ok": True, "token": token, "bundle": name, "size": d["size"], "counts": counts, "to": to, "made_at": made_at}


def forget(principal):
    """The prepared move withdrawn: the bundle gone, the nodes told nothing more."""
    with _lock:
        d = _load()
        if not d.get("made_at"):
            return {"error": "no move is prepared"}
        for old in (STATE / "move").glob("*.bbmove"):
            old.unlink(missing_ok=True)
        d = {k: v for k, v in d.items() if k in ("moved_to", "moved_at")}
        _save(d)
    return {"ok": True}


def for_node(nid):
    """What a node's hello carries while a move is prepared: the new address
    and its challenge; {} otherwise."""
    d = _load()
    if not d.get("made_at") or d.get("used") or not d.get("to") or int(d["made_at"]) + TOKEN_LIFE < time.time():
        return {}
    try:
        key = base64.b64decode(d["key_b64"])
    except (KeyError, ValueError):
        return {}
    return {"url": d["to"], "expect": challenge(key, nid)}


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


def mark_moved(to):
    """The old controller, once the new one is up: read-only, saying where."""
    with _lock:
        d = _load()
        d.update(moved_to=str(to or "")[:200], moved_at=int(time.time()), used=True)
        _save(d)
    return {"ok": True, "to": d["moved_to"]}


def moved_to():
    return str(_load().get("moved_to") or "")


def read_manifest(path):
    """The bundle's manifest, or (None, why)."""
    try:
        with open(path, "rb") as f:
            head = f.readline()
            if head != HEADER:
                return None, "not a BuilderBot move bundle"
            line = f.readline()
        m = json.loads(line)
        return (m, "") if isinstance(m, dict) and m.get("format") == 1 else (None, "a move bundle of a format this build does not read")
    except (OSError, ValueError) as e:
        return None, f"could not read the bundle: {e}"


def restore(path, token, state_dir=None, workspace_dir=None, secrets_dir=None, build_state_version=None, here_bare_metal=None):
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
    if token_hash(token) != m.get("token_hash"):
        return {"error": "that is not this bundle's move token"}
    key = key_of(token)
    with open(path, "rb") as f:
        f.readline(); f.readline()
        sealed = f.read()
    try:
        raw = open_with(key, sealed)
    except Exception:                                              # noqa: BLE001 (any failure to open is one answer)
        return {"error": "the bundle did not open under that token"}
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
        rec.update(restored_at=int(time.time()), used=True, came_from=m.get("from", ""), source_bare_metal=bool(m.get("bare_metal")),
                   here_bare_metal=bool(here_bare_metal if here_bare_metal is not None else bare_metal()))
        rec.pop("moved_to", None)
        rec.pop("moved_at", None)
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
    return {"restored_at": int(d.get("restored_at") or 0), "from": d.get("came_from", ""),
            "source_bare_metal": bool(d.get("source_bare_metal"))} if d.get("restored_at") else {}
