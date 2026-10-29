"""Registry images kept up to date (R195, the operator, 11 Oct).

A container's services that run an image from a registry (`image:` and no
`build:`) have no other way to move: Rebuild builds what the project's code
makes, and pulls nothing that is already there. So once a week, and on Check
for updates on the Containers page, each instance's registry images are compared
on its node: the digest the node pulled (`docker inspect`'s
RepoDigests) against the one the registry serves for that tag now. One that
differs is behind: its row says so with Update (pull, then up), and the bell
carries a note per node.

What is not asked: a service whose image is pinned by digest (nginx's,
which its own tab moves, nginxproxy.py), a service built from code, and an
image the node has never pulled (Up pulls it; there is nothing to compare).

The registry is asked over its v2 API with an anonymous token, which is
what a public image on Docker Hub, ghcr.io or quay.io answers; a private
one says it could not be read, on the row, rather than guessing. The
harness points BB_IMAGE_DIGESTS_FILE at {ref: digest} instead.
"""
import contextlib
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE = None
write_json = None
devapp = None
_lock = threading.Lock()
_checking = {"on": False}

CHECK_EVERY = 7 * 86400
CHECK_DELAY = float(os.environ.get("BB_IMAGE_CHECK_DELAY") or 300)
AUTOCHECK = os.environ.get("BB_IMAGE_AUTOCHECK", "1") != "0"
DIGESTS_FILE = os.environ.get("BB_IMAGE_DIGESTS_FILE") or ""
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                    "application/vnd.oci.image.manifest.v1+json"])
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def configure(*, state, write_json, devapp_module):
    globals().update(STATE=Path(state), write_json=write_json, devapp=devapp_module)


def _file():
    return STATE / "imagecheck.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def parse_ref(ref):
    """(registry, repository, tag) of an image reference, or None for one
    pinned by digest. `mariadb:11` is Docker Hub's library/mariadb."""
    ref = str(ref or "").strip()
    if not ref or "@" in ref:
        return None
    first, _, rest = ref.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry, path = "registry-1.docker.io", ref
    name, _, tag = path.rpartition(":") if ":" in path.rsplit("/", 1)[-1] else (path, "", "latest")
    if registry == "registry-1.docker.io" and "/" not in name:
        name = "library/" + name
    return registry, name, tag or "latest"


def _stub(ref):
    try:
        return str(json.loads(Path(DIGESTS_FILE).read_text()).get(ref) or "")
    except (OSError, ValueError, AttributeError):
        return ""


def remote_digest(ref):
    """(digest, error): what the registry serves for this tag now."""
    if DIGESTS_FILE:
        got = _stub(ref)
        return (got, "") if got else ("", f"the registry has no {ref}")
    parts = parse_ref(ref)
    if not parts:
        return "", ""
    registry, name, tag = parts
    url = f"https://{registry}/v2/{name}/manifests/{tag}"

    def head(token=""):
        req = urllib.request.Request(url, method="HEAD", headers={"Accept": ACCEPT}
                                     | ({"Authorization": f"Bearer {token}"} if token else {}))
        with urllib.request.urlopen(req, timeout=20) as r:   # noqa: S310 (https to the registry the image names)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            return r.headers.get("Docker-Content-Digest") or ""
    try:
        try:
            got = head()
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            # The anonymous token the challenge names: realm, service, scope.
            ch = dict(re.findall(r'(\w+)="([^"]*)"', e.headers.get("WWW-Authenticate") or ""))
            if not ch.get("realm", "").startswith("https://"):
                return "", f"{registry} asks for a sign-in this check does not have"
            q = urllib.parse.urlencode({k: v for k, v in (("service", ch.get("service")),
                                        ("scope", ch.get("scope") or f"repository:{name}:pull")) if v})
            with urllib.request.urlopen(f"{ch['realm']}?{q}", timeout=20) as r:   # noqa: S310 (the realm the registry named, https)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                tok = json.loads(r.read(200_000).decode("utf-8", "replace"))
            got = head(tok.get("token") or tok.get("access_token") or "")
    except urllib.error.HTTPError as e:
        return "", (f"{registry} has no {name}:{tag}" if e.code == 404
                    else f"{registry} would not say ({e.code}): a private image needs a sign-in this check does not have")
    except (OSError, http.client.HTTPException, ValueError) as e:
        return "", f"could not reach {registry}: {e}"[:200]
    return (got, "") if _DIGEST.fullmatch(got or "") else ("", f"{registry} gave no digest for {name}:{tag}")


def registry_images(project, instance):
    """[(service, image)] of an instance's services that run a registry
    image by tag: not built, not pinned by digest."""
    cfg = devapp._config(project, instance)
    if cfg is None:
        return []
    return sorted((name, str(sv["image"])) for name, sv in devapp._services(cfg).items()
                  if sv.get("image") and not sv.get("build") and parse_ref(sv["image"]))


def local_digests(image):
    """The digests the node has for an image it pulled, or None for one it
    has not (nothing to compare: Up pulls it)."""
    # `docker inspect --type image`, not `docker image inspect`: the bare
    # inspect is the read _run sends to an agent node as it is.
    r = devapp._run([devapp.DOCKER, "inspect", "--type", "image", "--format", "{{json .RepoDigests}}", image], timeout=30)
    if r.get("code") != 0:
        return None
    try:
        got = json.loads((r.get("out") or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return {d.partition("@")[2] for d in got or [] if "@" in d}


def check_instance(project, instance):
    """{"at", "behind": [{service, image, to}], "error"} for one instance,
    asked on its node."""
    behind, errors = [], []
    with devapp.on_node(devapp._instance_node(project, instance)):
        for service, image in registry_images(project, instance):
            have = local_digests(image)
            if not have:
                continue
            want, err = remote_digest(image)
            if err:
                errors.append(f"{image}: {err}")
            elif want and want not in have:
                behind.append({"service": service, "image": image, "to": want})
    return {"at": int(time.time()), "behind": behind, "error": "; ".join(errors)[:400]}


def check(node=None):
    """Every instance's registry images (on one node, or all), now. The
    answers, keyed by container name."""
    with _lock:
        if _checking["on"]:
            return {"error": "a check is already running"}
        _checking["on"] = True
    out = {}
    try:
        for project, insts in devapp._load().items():
            for inst in insts:
                if devapp.owner_of(project, inst) == devapp.SYSTEM:
                    continue
                if node and (devapp._instance_node(project, inst) or "") != node:
                    continue
                try:
                    out[devapp._pname(project, inst)] = check_instance(project, inst) | {
                        "node": devapp._instance_node(project, inst) or "",
                        "project": devapp.owner_of(project, inst) or project}
                except Exception as e:   # noqa: BLE001 (one container's trouble is not the check's)
                    print(f"[imagecheck] {project}/{inst}: {type(e).__name__}: {e}", flush=True)
        with _lock:
            d = _load()
            if not node:
                d = {k: v for k, v in d.items() if k.startswith("_")}
            d.update(out)
            d["_at"] = int(time.time())
            write_json(_file(), d)
    finally:
        with _lock:
            _checking["on"] = False
    return {"ok": True, "checked": len(out), "behind": sum(1 for v in out.values() if v["behind"])}


def of(name):
    """What the last check said of the container called `name`, or {}."""
    return dict(_load().get(name) or {})


def last_at():
    return int(_load().get("_at") or 0)


def forget(name):
    """An update that pulled what was behind: nothing is behind until the
    next check says so."""
    with _lock:
        d = _load()
        if name in d:
            d[name] = dict(d[name], behind=[])
            write_json(_file(), d)


def _project_of(name, v):
    """The project a checked container is one of: as the check recorded it,
    or, for an answer from before it did, found by the container's name."""
    if (v or {}).get("project"):
        return v["project"]
    for project, insts in devapp._load().items():
        for inst in insts:
            if devapp._pname(project, inst) == name:
                return devapp.owner_of(project, inst) or project
    return ""


def attention(node_name, allowed=None):
    """The bell's rows: one per node with a container behind, kind image,
    keyed by bellseen on the digests it would move to. `allowed(project)`
    keeps the containers of the projects this account may act on: a row of
    another project's updates is news about containers it cannot touch, and
    names what it may not see (the operator, 16 Oct)."""
    by = {}
    for name, v in _load().items():
        if name.startswith("_") or not (v or {}).get("behind"):
            continue
        if allowed is not None and not allowed(_project_of(name, v)):
            continue
        by.setdefault(v.get("node") or "", []).append((name, v["behind"]))
    out = []
    for nid, rows in sorted(by.items()):
        rows.sort()
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
        out.append({"kind": "image", "id": nid, "node": node_name(nid) if nid else "the default node",
                    "containers": [{"name": n, "images": [b["image"] for b in bs]} for n, bs in rows],
                    "digest": digest})
    return out


import checks  # noqa: E402 (the cadence, R176)


def check_loop():
    """The weekly check, from when the last one ran rather than from the
    start, beside the toolchains' and nginx's."""
    time.sleep(CHECK_DELAY)
    while True:
        if checks.due("images", last_at()):
            with contextlib.suppress(Exception):   # noqa: BLE001 (the loop outlives one bad pass)
                check()
        time.sleep(600)
