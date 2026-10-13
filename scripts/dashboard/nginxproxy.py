"""One reverse proxy per node, BuilderBot's own (R171, the operator, 10 Oct).

The nginx tab lists every node's nginx instance: one nginx container per
node, written here like a container from the Docker tab (containers.py), its
compose file generated from what this module keeps rather than typed. What
it keeps, per node: the routes (a hostname or path, to a port on that node,
with or without TLS) and the certificate (a Cloudflare origin certificate
for a site behind Cloudflare, or any other), as PEM files under the state
directory, 0600, never shown back whole. Deploy makes the container and
builds it; Save rewrites its compose file and rebuilds it so the change is
up; Remove takes it out of the manager like any written container.

The compose file carries everything inline (compose `configs` with
`content`, so the node's compose job needs nothing new): nginx on the host
network, proxying to 127.0.0.1 and the port a container on that node
publishes. Host networking because a hosting node's containers publish
their ports there already, and it is one rule a person can hold in their
head; the cost, said on the tab, is that nginx holds 80 and 443 on the
machine, so a container that publishes either itself is named as the clash.
"""
import contextlib
import http.client
import json
import os
import re
import ssl
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

STATE = None
write_json = None
_lock = threading.Lock()

# The image: the alpine build of a release line. A node's nginx is pinned
# to the newest line's digest when it is deployed or updated (R192), so what
# runs is what the record says; the line's tag here is only what a node
# deployed before any check had read the registry says of itself.
IMAGE = "nginx:1.27-alpine"
IMAGE_LINE = re.compile(r"^(\d+)\.(\d+)-alpine$")
# Docker Hub's tag list for the official image, read weekly like the
# toolchains' upstreams; a test points it at a file.
TAGS_URL = (os.environ.get("BB_NGINX_TAGS_URL")
            or "https://hub.docker.com/v2/repositories/library/nginx/tags?page_size=100&name=-alpine")
CHECK_EVERY = 7 * 86400
CHECK_DELAY = float(os.environ.get("BB_NGINX_CHECK_DELAY") or 240)
AUTOCHECK = os.environ.get("BB_NGINX_AUTOCHECK", "1") != "0"
_checking = False
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)*$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._~/-]*$")
MAX_ROUTES = 64
# What a node's view is read from: nodes.py's list and devapp's listing,
# handed in by the server (configure).
node_list = None
node_name = None
taken_ports = None


def configure(*, state, write_json, node_list, node_name, taken_ports):
    globals().update(STATE=Path(state), write_json=write_json, node_list=node_list,
                     node_name=node_name, taken_ports=taken_ports)


def _file():
    return STATE / "nginx.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(d):
    write_json(_file(), d)


def _cert_dir(nid, host=""):
    """Where a node's certificate lives: the default at the node's own
    directory, a hostname's own under certs/<host> (R175)."""
    d = STATE / "nginx" / re.sub(r"[^A-Za-z0-9_-]", "_", str(nid))
    return d / "certs" / re.sub(r"[^a-z0-9.-]", "_", host.lower()) if host else d


def _cert_slug(host):
    """A hostname as a compose config name: letters, digits and _."""
    return re.sub(r"[^a-z0-9]", "_", host.lower())


def cert_for(rec, host, pick=""):
    """The key of the pair a server's hostname uses, or "": the route's own
    pick where it names a pair the node holds (R188), else the hostname's
    own pair, else the nearest parent domain's (one wildcard pair under
    example.com covers a.example.com and b.example.com, another domain's
    pair its own). No default (the operator, 11 Oct): a hostname nothing
    covers answers on 80 alone."""
    certs = rec.get("certs") or {}
    if pick and (certs.get(pick) or {}).get("set"):
        return pick
    if not host or host == "*":
        return ""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if (certs.get(cand) or {}).get("set"):
            return cand
    return ""


def cert_paths(rec, host, pick=""):
    """(cert, key) paths inside the container for a server's hostname
    (cert_for), or none."""
    own = cert_for(rec, host, pick)
    if own:
        return f"/etc/nginx/certs/{own}/cert.pem", f"/etc/nginx/certs/{own}/key.pem"
    return "", ""


def container_name(nid):
    """The written container's name on a node: nginx-<node name>, kept to
    the characters a compose project name may have."""
    base = re.sub(r"[^a-z0-9-]", "-", str(node_name(nid) or nid).lower()).strip("-") or "node"
    return f"nginx-{base}"[:60]


# ---- the routes ------------------------------------------------------------

def clean_routes(routes):
    """The routes as stored, or {"error"}: a hostname (or * for any), a
    path, a port on the node, and whether 443 serves it too."""
    out = []
    for r in (routes if isinstance(routes, list) else [])[:MAX_ROUTES]:
        if not isinstance(r, dict):
            continue
        host = str(r.get("host") or "").strip().lower()
        path = str(r.get("path") or "/").strip() or "/"
        port = str(r.get("port") or "").strip()
        if host != "*" and not HOST_RE.match(host):
            return {"error": f"a route's hostname is a name like www.example.com, or * for any: not {host or 'nothing'}"}
        if not PATH_RE.match(path) or ".." in path:
            return {"error": f"a route's path starts with / and names a place on the site: not {path}"}
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return {"error": f"a route goes to a port on the node (1 to 65535): not {port or 'nothing'}"}
        # The pair it serves 443 with (R188): a key the node holds, or ""
        # for the one its hostname resolves to (cert_for); checked for
        # shape here and against the node's list when the config is written.
        pick = str(r.get("cert") or "").strip().lower()
        if pick and not HOST_RE.match(pick):
            return {"error": f"a route's certificate is one the node holds, named by its domain: not {pick}"}
        out.append({"host": host, "path": path, "port": int(port), "tls": r.get("tls") is not False, "cert": pick})
    return out


def nginx_conf(routes, rec=None):
    """nginx's config from the routes: a server per hostname, each path to
    its port on this machine, 443 with the pair the route picked or its
    hostname resolves to (cert_for), and any name not routed answered by
    closing the connection, on 443 by refusing the handshake with no
    certificate at all (ssl_reject_handshake, nginx 1.19.4 and later; the
    image is 1.27), so the box serves nothing it was not told to and
    needs no default pair (R188). `rec` carries the node's pairs."""
    rec = rec if rec is not None else {}
    by_host = {}
    for r in routes:
        by_host.setdefault(r["host"], []).append(r)
    lines = ["# Written by BuilderBot from the nginx tab: edit it there, not here.",
             "worker_processes auto;",
             "events { worker_connections 1024; }",
             "http {",
             "  include /etc/nginx/mime.types;",
             "  server_tokens off;",
             "  client_max_body_size 512m;",
             "  proxy_http_version 1.1;",
             "  proxy_set_header Host $host;",
             "  proxy_set_header X-Real-IP $remote_addr;",
             "  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
             "  proxy_set_header X-Forwarded-Proto $scheme;",
             "  proxy_set_header Upgrade $http_upgrade;",
             "  proxy_set_header Connection $http_connection;",
             "  proxy_read_timeout 300s;"]
    # A name nothing routes: the connection closed, no page. Unless a * route
    # takes any name, which is then the default server itself (two default
    # servers on one port is nginx's "duplicate default server", seen on
    # bb-dev-sandbox, 10 Oct).
    any_host = "*" in by_host
    if not any_host:
        lines.append("  server { listen 80 default_server; server_name _; return 444; }")
    if not (any_host and any(r["tls"] for r in by_host["*"])):
        lines.append("  server { listen 443 ssl default_server; server_name _; "
                     "ssl_reject_handshake on; return 444; }")
    for host, rs in by_host.items():
        name = "_" if host == "*" else host
        # The pair for this hostname's server: its routes' pick (the first
        # that names one), else what the hostname resolves to.
        pick = next((r.get("cert") for r in rs if r.get("cert")), "")
        cert, key = cert_paths(rec, host, pick)
        for listen in ("80", "443 ssl"):
            if listen.startswith("443") and not (cert and any(r["tls"] for r in rs)):
                continue
            lines.append("  server {")
            lines.append(f"    listen {listen}{' default_server' if host == '*' else ''};")
            lines.append(f"    server_name {name};")
            if listen.startswith("443"):
                lines.append(f"    ssl_certificate {cert};")
                lines.append(f"    ssl_certificate_key {key};")
            # The longest path first, so /api wins over / for /api/x.
            for r in sorted(rs, key=lambda x: -len(x["path"])):
                if listen.startswith("443") and not r["tls"]:
                    continue
                loc = r["path"] if r["path"] == "/" else r["path"].rstrip("/") + "/"
                lines.append(f"    location {loc} {{ proxy_pass http://127.0.0.1:{r['port']}; }}")
                if r["path"] != "/":
                    lines.append(f"    location = {r['path'].rstrip('/')} {{ return 301 {loc}; }}")
            lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _indent(text, n):
    pad = " " * n
    return "\n".join(pad + ln if ln else "" for ln in text.rstrip("\n").split("\n"))


def compose_text(nid, rec):
    """The container's compose file: nginx on the host network, its config
    and certificate inline as compose configs, so nothing but this file
    goes to the node."""
    routes = rec.get("routes") or []
    # The pairs a route uses, each once (R175, R188).
    own = sorted(h for h, c in (rec.get("certs") or {}).items()
                 if (c or {}).get("set") and any(cert_for(rec, r["host"], r.get("cert", "")) == h for r in routes))
    conf = nginx_conf(routes, rec)
    out = ["# Written by BuilderBot from the nginx tab (nginxproxy.py); Save there rewrites it.",
           "services:",
           "  nginx:",
           f"    image: {image_ref(rec)}",
           # Named for the node, as the Docker tab names it, so docker logs
           # finds it under that name (B653: compose's nginx-NODE-nginx-1 did not).
           f"    container_name: {container_name(nid)}",
           "    restart: unless-stopped",
           "    network_mode: host",
           "    configs:",
           "      - source: nginx_conf",
           "        target: /etc/nginx/nginx.conf"]
    for h in own:
        out += [f"      - source: tls_cert_{_cert_slug(h)}", f"        target: /etc/nginx/certs/{h}/cert.pem",
                f"      - source: tls_key_{_cert_slug(h)}", f"        target: /etc/nginx/certs/{h}/key.pem", "        mode: 0400"]
    # compose reads $name in a config's content as its own variable and
    # empties it (nginx's $host became nothing on bb-dev-sandbox, 10 Oct):
    # a literal dollar is written $$ there.
    out += ["configs:", "  nginx_conf:", "    content: |", _indent(conf.replace("$", "$$"), 6)]
    for h in own:
        cert, key = _read_cert(nid, h)
        out += [f"  tls_cert_{_cert_slug(h)}:", "    content: |", _indent(cert, 6),
                f"  tls_key_{_cert_slug(h)}:", "    content: |", _indent(key, 6)]
    return "\n".join(out) + "\n"


# ---- the certificate ---------------------------------------------------------

def _read_cert(nid, host=""):
    d = _cert_dir(nid, host)
    try:
        return (d / "cert.pem").read_text(), (d / "key.pem").read_text()
    except OSError:
        return "", ""


def check_cert(cert, key):
    """{subject, expires} when the PEM pair is a certificate and the key
    that goes with it, else {"error"}: checked by loading them the way
    nginx will, so a mismatch is said here and not by a container that
    will not start."""
    cert, key = str(cert or "").strip() + "\n", str(key or "").strip() + "\n"
    if "-----BEGIN CERTIFICATE-----" not in cert:
        return {"error": "the certificate is a PEM file: it starts -----BEGIN CERTIFICATE-----"}
    if "PRIVATE KEY-----" not in key:
        return {"error": "the key is a PEM file: it starts -----BEGIN PRIVATE KEY----- (or RSA/EC PRIVATE KEY)"}
    if len(cert) > 64000 or len(key) > 64000:
        return {"error": "that is too big to be a certificate or a key"}
    with tempfile.TemporaryDirectory() as t:
        cp, kp = Path(t) / "c.pem", Path(t) / "k.pem"
        cp.write_text(cert)
        kp.write_text(key)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        try:
            ctx.load_cert_chain(str(cp), str(kp))
        except ssl.SSLError as e:
            return {"error": f"the certificate and key do not load together: {e.reason or e}"}
        try:
            info = ssl._ssl._test_decode_cert(str(cp))  # noqa: SLF001 (the stdlib's own reader)
        except Exception:  # noqa: BLE001
            info = {}
    subject = ", ".join(v for rdn in info.get("subject", ()) for k, v in rdn if k == "commonName") or ""
    alt = ", ".join(v for k, v in info.get("subjectAltName", ()) if k == "DNS")
    expires = 0
    with contextlib.suppress(ValueError, TypeError):
        expires = int(ssl.cert_time_to_seconds(info["notAfter"]))
    return {"subject": subject or alt or "(no name)", "names": alt, "expires": expires}


def set_cert(nid, cert, key, host=""):
    """A pair the node holds (R188): checked, kept 0600, summarized in the
    record under the key it is known by: `host` when the person named one,
    else the domain its names say (domain_of), so a wildcard pair for
    *.example.com is example.com's. The same key again is a renewal and
    replaces that pair; another domain's pair stands beside it. There is
    no default (the operator, 11 Oct)."""
    host = str(host or "").strip().lower()
    if host and not HOST_RE.match(host):
        return {"error": f"a certificate is known by a name like example.com: not {host}"}
    got = check_cert(cert, key)
    if got.get("error"):
        return got
    host = host or domain_of(got.get("names") or got.get("subject") or "")
    if not host:
        return {"error": "that pair names no hostname: say which domain it is for under Filed under"}
    d = _cert_dir(nid, host)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, text in (("cert.pem", cert), ("key.pem", key)):
        p = d / name
        p.write_text(str(text).strip() + "\n")
        p.chmod(0o600)
    summary = {"set": True, "subject": got["subject"], "names": got["names"],
               "expires": got["expires"], "at": int(time.time())}
    with _lock:
        st = _load()
        rec = st.setdefault(str(nid), {})
        rec.setdefault("certs", {})[host] = summary
        _save(st)
    return {"ok": True, "cert": summary, "host": host}


def domain_of(names):
    """The domain a pair is for, from its names: the first, a wildcard's
    star taken off (*.example.com is example.com's), lowercased."""
    first = str(names or "").split(",")[0].strip().lower()
    if first.startswith("*."):
        first = first[2:]
    return first if HOST_RE.match(first) else ""


def drop_cert(nid, host=""):
    """A pair taken off the node, by the key it is known by; a route that
    picked it falls back to what its hostname resolves to, or 80 alone."""
    host = str(host or "").strip().lower()
    if not host:
        return {"error": "which certificate? name it by the key it is listed under"}
    d = _cert_dir(nid, host)
    for name in ("cert.pem", "key.pem"):
        with contextlib.suppress(OSError):
            (d / name).unlink()
    with _lock:
        st = _load()
        rec = st.get(str(nid)) or {}
        (rec.get("certs") or {}).pop(host, None)
        _save(st)
    return {"ok": True}


def _migrate(nid):
    """A node's default pair from before R188 becomes a listed pair under
    the domain its names say, its files moved under certs/<domain>: read on
    the way in, once, so nothing a person saved is lost."""
    with _lock:
        st = _load()
        rec = st.get(str(nid)) or {}
        cur = rec.get("cert")
        if not isinstance(cur, dict):
            return
        if cur.get("set"):
            key = domain_of(cur.get("names") or cur.get("subject") or "") or "default"
            src, dst = _cert_dir(nid), _cert_dir(nid, key)
            dst.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in ("cert.pem", "key.pem"):
                with contextlib.suppress(OSError):
                    (src / name).replace(dst / name)
            rec.setdefault("certs", {}).setdefault(key, cur)
        rec.pop("cert", None)
        _save(st)


# ---- the tab's verbs ----------------------------------------------------------

def record(nid):
    _migrate(nid)
    return dict(_load().get(str(nid)) or {})


# ---- the image: a weekly check, a pin per node, Update (R192) ----

def latest_image():
    """The newest line the registry listed: {tag, digest, at, error}, kept
    in the store beside the nodes' records so it outlives the container."""
    return dict(_load().get("_image") or {})


def check_image():
    """Read the registry's tag list now and keep the newest release line's
    alpine tag with its digest (the manifest list's, which is what a pull
    by digest takes). An answer that could not be read keeps the last one
    and says why; the record is what came back."""
    global _checking
    with _lock:
        if _checking:
            return latest_image()
        _checking = True
    tag, digest, error = "", "", ""
    try:
        with urllib.request.urlopen(TAGS_URL, timeout=20) as r:   # noqa: S310 (a fixed https URL, or a test's file://)  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            d = json.loads(r.read(4_000_000).decode("utf-8", "replace"))
        best = None
        for t in (d.get("results") or []) if isinstance(d, dict) else []:
            m = IMAGE_LINE.match(str((t or {}).get("name") or ""))
            if not m:
                continue
            key = (int(m.group(1)), int(m.group(2)))
            if best is None or key > best[0]:
                best = (key, t)
        if best:
            t = best[1]
            tag = str(t["name"])
            digest = str(t.get("digest") or next((i.get("digest") for i in (t.get("images") or [])
                                                  if (i or {}).get("digest")), "") or "")
            if not digest.startswith("sha256:"):
                tag, digest, error = "", "", f"the registry gave no digest for nginx:{t['name']}"
        else:
            error = "the registry listed no release line's alpine tag"
    except (OSError, http.client.HTTPException, ValueError, TypeError, KeyError) as e:   # URLError and a timeout are OSErrors
        error = f"could not reach the registry: {e}"[:200]
    with _lock:
        st = _load()
        rec = dict(st.get("_image") or {})
        rec.update(at=int(time.time()), error=error)
        if tag:
            rec.update(tag=tag, digest=digest)
        st["_image"] = rec
        _save(st)
        _checking = False
    return dict(rec)


def image_of(rec):
    """What a node's nginx is pinned to: its tag and digest, or the line's
    tag alone for one deployed before a check had read the registry."""
    im = rec.get("image") or {}
    return {"tag": str(im.get("tag") or IMAGE.partition(":")[2]), "digest": str(im.get("digest") or "")}


def image_ref(rec):
    """The compose file's image line: nginx:TAG@sha256:... once pinned, so
    a rebuild pulls exactly that and nothing moves under a Save."""
    im = image_of(rec)
    return f"nginx:{im['tag']}" + (f"@{im['digest']}" if im["digest"] else "")


def behind(rec):
    """The tag a node's nginx would move to, or "": the newest line's digest
    is not the one it is pinned to, and one not pinned at all is behind
    whatever the registry says is newest."""
    lt = latest_image()
    if not lt.get("digest"):
        return ""
    return str(lt["tag"]) if image_of(rec)["digest"] != lt["digest"] else ""


def behind_named(name):
    """behind() for the Docker tab's row of that name, or "" for a container
    that is not a node's nginx."""
    for n in node_list():
        if container_name(n["id"]) == name:
            return behind(record(n["id"]))
    return ""


def pin_latest(nid):
    """A node's nginx pinned to the newest line the registry listed; nothing
    changes when no check has read one yet."""
    lt = latest_image()
    if not lt.get("digest"):
        return {}
    with _lock:
        st = _load()
        st.setdefault(str(nid), {})["image"] = {"tag": lt["tag"], "digest": lt["digest"]}
        _save(st)
    return dict(st[str(nid)]["image"])


def attention(deployed):
    """The bell's rows (R192): each node whose deployed nginx is behind the
    newest line, kind nginx, keyed by bellseen on the digest it would move
    to, so a dismissal holds until the registry moves again. `deployed`
    says whether a node's nginx is on the Docker tab."""
    lt = latest_image()
    if not lt.get("digest"):
        return []
    out = []
    for n in node_list():
        if n.get("kind") != "agent" or n.get("state") in ("retired", "pending"):
            continue
        nid = n["id"]
        if not deployed(nid):
            continue
        rec = record(nid)
        to = behind(rec)
        if not to:
            continue
        im = image_of(rec)
        out.append({"kind": "nginx", "node": n.get("name") or nid, "id": nid,
                    "from": f"nginx:{im['tag']}" + (f" ({im['digest'][7:19]})" if im["digest"] else ", not pinned"),
                    "to": f"nginx:{to} ({lt['digest'][7:19]})", "digest": lt["digest"]})
    return out


def check_loop():
    """The weekly check, from when the last one happened rather than from
    the start: a container restart is not a reason to ask the registry
    again. Started by the server beside the toolchains' loop."""
    time.sleep(CHECK_DELAY)
    while True:
        if time.time() >= int(latest_image().get("at") or 0) + CHECK_EVERY:
            with contextlib.suppress(Exception):   # noqa: BLE001 (the loop outlives one bad answer)
                check_image()
        time.sleep(300)


def deployed(devapp, nid):
    """Whether the nginx tab's container is on this node: written from here
    (a file source under its name) and bound to this node."""
    name = container_name(nid)
    return bool(devapp.is_file_source(name) and devapp._read_rec(name, devapp.MAIN).get("node") == nid)


def view(devapp, instance_state):
    """Every agent node with what its nginx is: deployed or not, its routes,
    its certificate (never the key), and the containers on it holding 80 or
    443 themselves. `instance_state` is devactions.state, for a deployed one."""
    out = []
    for n in node_list():
        if n.get("kind") != "agent" or n.get("state") in ("retired", "pending"):
            continue
        nid = n["id"]
        rec = record(nid)
        name = container_name(nid)
        is_up = deployed(devapp, nid)
        row = {"node": nid, "name": n.get("name") or nid, "host_only": bool((n.get("config") or {}).get("host_only")),
               "container": name, "deployed": is_up,
               "routes": rec.get("routes") or [],
               # The pairs it holds (R188), and for each route the key its
               # hostname resolves to with no pick of its own, for the row.
               "certs": rec.get("certs") or {},
               "resolved": {r["host"]: cert_for(rec, r["host"]) for r in (rec.get("routes") or [])},
               "live": n.get("live"), "clash": [],
               # What it is pinned to and the line it would move to (R192).
               "image": image_of(rec) | {"ref": image_ref(rec)}, "behind": behind(rec)}
        if is_up:
            with contextlib.suppress(Exception):  # noqa: BLE001 (a row still draws without its state)
                row["state"] = instance_state(name, devapp.MAIN)
        with contextlib.suppress(Exception):  # noqa: BLE001 (a node that does not answer has no clash to show)
            with devapp.on_node(nid):
                row["clash"] = taken_ports(name, devapp.MAIN, [{"published": "80"}, {"published": "443"}])
        out.append(row)
    return {"nodes": out, "image": IMAGE, "latest": latest_image(), "hostnames": hostnames()}


# ---- the public hostnames (the operator, 12 Oct) ----------------------------
#
# One list for every node's nginx, so a name made once is picked from a
# pull-down on any route, by any project's container, rather than typed again
# on each: what a route can name. Kept beside the nodes' records; a name a
# route uses is on the list whether or not it was added there, and one in use
# cannot be deleted.

def _hosts_file():
    return STATE / "nginx-hostnames.json"


def _hosts_saved():
    try:
        d = json.loads(_hosts_file().read_text())
        return [str(h) for h in d if isinstance(h, str)] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def hostnames():
    """[{name, used: [{node, path, port}]}]: every hostname on the list and
    every one a route uses, in name order, with where each is used."""
    used = {}
    names = {n["id"]: n.get("name") or n["id"] for n in node_list()}
    for nid, rec in _load().items():
        for r in (rec.get("routes") or []) if isinstance(rec, dict) else []:
            if r.get("host") and r["host"] != "*":
                used.setdefault(r["host"], []).append({"node": names.get(nid, nid), "path": r.get("path") or "/",
                                                       "port": r.get("port")})
    return [{"name": h, "used": used.get(h, [])} for h in sorted(set(_hosts_saved()) | set(used))]


def add_hostname(name):
    h = str(name or "").strip().lower()
    if not HOST_RE.match(h):
        return {"error": f"a hostname is a name like www.example.com: not {h or 'nothing'}"}
    with _lock:
        have = _hosts_saved()
        if h not in have:
            write_json(_hosts_file(), sorted(have + [h]))
    return {"ok": True, "hostnames": hostnames()}


def remove_hostname(name):
    h = str(name or "").strip().lower()
    row = next((x for x in hostnames() if x["name"] == h), None)
    if not row:
        return {"error": f"{h} is not on the list"}
    if row["used"]:
        return {"error": f"{h} is routed on {', '.join(sorted({u['node'] for u in row['used']}))}: "
                         "take those routes off first"}
    with _lock:
        write_json(_hosts_file(), [x for x in _hosts_saved() if x != h])
    return {"ok": True, "hostnames": hostnames()}


def save_routes(nid, routes):
    got = clean_routes(routes)
    if isinstance(got, dict):
        return got
    with _lock:
        st = _load()
        st.setdefault(str(nid), {})["routes"] = got
        _save(st)
    return {"ok": True, "routes": got}


def add_route(nid, port, cert, containers, devactions, devapp):
    """A route written from a container's row on the Docker tab (R209): to
    `port` on the node, at the hostname the certificate is filed under
    (its domain), with that pair, or at any hostname on 80 alone with no
    certificate; applied at once. A port that already has a route is
    refused by name: one route per port, the rest is the nginx tab's."""
    try:
        port = int(str(port).strip())
    except (TypeError, ValueError):
        return {"error": "which port? one the container publishes on this node"}
    if not 1 <= port <= 65535:
        return {"error": f"not a port: {port}"}
    rec = record(nid)
    certs = rec.get("certs") or {}
    cert = str(cert or "").strip().lower()
    if cert and not (certs.get(cert) or {}).get("set"):
        return {"error": f"this node holds no certificate filed under {cert}: paste it on the nginx tab first"}
    routes = list(rec.get("routes") or [])
    for r in routes:
        if int(r.get("port") or 0) == port:
            where = f"{r.get('host') or '*'}{r.get('path') or '/'}"
            return {"error": f"port {port} already has a route: {where} on this node's nginx; change it on the nginx tab"}
    routes.append({"host": cert or "*", "path": "/", "port": port, "tls": bool(cert), "cert": cert})
    saved = save_routes(nid, routes)
    if saved.get("error"):
        return saved
    r = apply(nid, containers, devactions, devapp)
    if r.get("error"):
        return r
    return r | {"route": routes[-1]}


def deploy(nid, containers, devactions, devapp):
    """The container made on the node from the generated compose file, then
    built: Deploy on a node without one, and the enroll dialog's tick once
    the node has enrolled."""
    name = container_name(nid)
    if devapp.is_file_source(name):
        return {"error": f"{name} is already on the Docker tab"}
    # A new one is the newest line the registry listed, pinned (R192).
    pin_latest(nid)
    rec = record(nid)
    # BuilderBot's own (R180): System's, which no picker sets.
    r = containers.create_container(name, compose_text(nid, rec), "", node=nid, for_project=devapp.SYSTEM)
    if r.get("error"):
        return r
    b = devactions.rebuild(name, devapp.MAIN, gate=False)
    if b.get("error"):
        return {"ok": True, "name": name, "note": f"made, but not built: {b['error']}"}
    return {"ok": True, "name": name, "job": b.get("job")}


def claim(devapp, name):
    """One deployed before System existed (R180) is System's from its next
    Save: it was no project's, which is what the deployment used to write."""
    with devapp._lock:
        d = devapp._load()
        rec = (d.get(name) or {}).get(devapp.MAIN)
        if rec is not None and rec.get("source") == "file" and not rec.get("for"):
            rec["for"] = devapp.SYSTEM
            devapp.write_json(devapp.FILE, d)


def apply(nid, containers, devactions, devapp):
    """A deployed nginx given its new compose file and rebuilt, so what was
    saved is what runs; nothing to do where it is not deployed yet."""
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"ok": True, "deployed": False}
    claim(devapp, name)
    r = containers.update_container(name, compose_text(nid, record(nid)), "")
    if r.get("error"):
        return r
    b = devactions.rebuild(name, devapp.MAIN, gate=False)
    if b.get("error"):
        return {"ok": True, "deployed": True, "note": f"saved, but not rebuilt: {b['error']}"}
    return {"ok": True, "deployed": True, "job": b.get("job")}


def update(nid, containers, devactions, devapp):
    """Update on the nginx tab's node or its Docker row (R192): the newest
    line's digest pinned on the record and the container rebuilt with it,
    so the pull is the whole of what changes. The registry is read now
    when no check has, so the first press needs no Check first."""
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"error": f"{name} is not deployed: Deploy puts the newest nginx on the node"}
    lt = latest_image()
    if not lt.get("digest"):
        lt = check_image()
    if not lt.get("digest"):
        return {"error": lt.get("error") or "no check has read the registry yet"}
    if image_of(record(nid))["digest"] == lt["digest"]:
        return {"ok": True, "same": True, "note": f"{name} already runs nginx:{lt['tag']} at that digest"}
    pin_latest(nid)
    r = apply(nid, containers, devactions, devapp)
    return r if r.get("error") else r | {"to": lt["tag"]}


def remove(nid, devactions, devapp):
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"error": f"{name} is not on the Docker tab"}
    return devactions.remove_instance(name, devapp.MAIN)
