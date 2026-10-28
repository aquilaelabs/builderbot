"""One reverse proxy per node, BuilderBot's own (R171, the operator, 10 Oct).

The nginx page lists every node's nginx instance: one nginx container per
node, written here like a container from the Containers page (containers.py), its
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
import concurrent.futures
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


# The token the nginx tab watches (/api/revs `nginx`, B714): moved by every
# write of the record and of the hostnames, so a route added from a Docker
# row, from bb or from another browser reaches an open tab within a poll
# rather than at its next Refresh. A counter, not an mtime: the tab stages
# a draft per node and redraws around it.
_rev = 0


def _bump():
    global _rev
    _rev += 1


def rev():
    return _rev


def _save(d):
    write_json(_file(), d)
    _bump()


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
    lines = ["# Written by BuilderBot from the nginx page: edit it there, not here.",
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
    # An ACME HTTP-01 challenge being answered (R150): the token's line on
    # every port-80 server, the default one included, since the name may
    # route nowhere yet.
    tokens = rec.get("acme_tokens") or {}
    chall = [f"    location = /.well-known/acme-challenge/{t} {{ default_type text/plain; return 200 \"{v}\"; }}"
             for t, v in sorted(tokens.items()) if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", str(t)) and re.fullmatch(r"[A-Za-z0-9_.-]{8,256}", str(v))]
    if not any_host:
        if chall:
            lines += ["  server {", "    listen 80 default_server;", "    server_name _;", *chall,
                      "    location / { return 444; }", "  }"]
        else:
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
            else:
                lines += chall
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
    out = ["# Written by BuilderBot from the nginx page (nginxproxy.py); Save there rewrites it.",
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


def wide_names(rec):
    """For each pair the node holds, the names it serves beyond the node's
    own routes (R93): a wildcard always, and any name no route on the node
    is for. On a hosting-only node the key sits on a public box in the
    compose file, and a box that was taken over could pass as every one
    of them; the page says so under the pair."""
    hosts = {str(r.get("host") or "").lower() for r in (rec.get("routes") or [])}
    out = {}
    for k, c in (rec.get("certs") or {}).items():
        if not (c or {}).get("set"):
            continue
        names = [x.strip().lower() for x in str(c.get("names") or c.get("subject") or "").split(",") if x.strip()]
        wide = [x for x in names if x.startswith("*.") or x not in hosts]
        if wide:
            out[k] = wide
    return out


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
        # Written without moving the tab's token: this runs on a READ (the
        # Docker list reads the record for its rows), and a token moved by
        # a read had the Docker tab re-reading itself (uniform.mjs, 13 Oct).
        write_json(_file(), st)


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
    """behind() for the Containers page's row of that name, or "" for a container
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
    says whether a node's nginx is on the Containers page."""
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
                    "to": f"nginx:{to} ({lt['digest'][7:19]})", "digest": lt["digest"],
                    # The tag it runs, rebuilt upstream: said as a newer build.
                    "rebuild": im["tag"] == to})
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
    """Whether the nginx page's container is on this node: written from here
    (a file source under its name) and bound to this node."""
    name = container_name(nid)
    return bool(devapp.is_file_source(name) and devapp._read_rec(name, devapp.MAIN).get("node") == nid)


# The daemon half of a row (the deployed container's state and the ports
# something else holds), kept per node for DAEMON_TTL seconds (B717). Both
# are reads of the node's docker, one probe job on an agent node each, up to
# 25 s on a quiet one: the tab's every poll paid them for every node, which
# held the view 40 s through production while the operator looked at the
# nginx tab, and a Docker tab beside it sat on 'reading its env' behind the
# same node's channel. A row read within the TTL is the last answer; a
# Deploy, Save or Remove bumps the record, a compose job's end moves the
# manager's job revision, and the next read after either is fresh.
DAEMON_TTL = 20.0
_daemon_memo = {}      # node id -> (expires, key, state or None, clash)
_memo_lock = threading.Lock()


def _daemon_half(devapp, instance_state, nid, name, is_up):
    key = (_rev, getattr(devapp, "job_rev", lambda: "")())
    now = time.monotonic()
    with _memo_lock:
        got = _daemon_memo.get(nid)
    if got and got[0] > now and got[1] == key:
        return got[2], got[3]
    state, clash = None, []
    if is_up:
        with contextlib.suppress(Exception):  # noqa: BLE001 (a row still draws without its state)
            state = instance_state(name, devapp.MAIN)
    with contextlib.suppress(Exception):  # noqa: BLE001 (a node that does not answer has no clash to show)
        with devapp.on_node(nid):
            clash = taken_ports(name, devapp.MAIN, [{"published": "80"}, {"published": "443"}])
    with _memo_lock:
        _daemon_memo[nid] = (time.monotonic() + DAEMON_TTL, key, state, clash)
    return state, clash


def view(devapp, instance_state):
    """Every agent node with what its nginx is: deployed or not, its routes,
    its certificate (never the key), and the containers on it holding 80 or
    443 themselves. `instance_state` is devactions.state, for a deployed one.
    The two daemon reads per node come from a short memo (_daemon_half)."""
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
               "wide": wide_names(rec) if (n.get("config") or {}).get("host_only") else {},
               "live": n.get("live"), "clash": [],
               # What it is pinned to and the line it would move to (R192).
               "image": image_of(rec) | {"ref": image_ref(rec)}, "behind": behind(rec),
               # Certificates from Let's Encrypt (R150): what is being asked
               # for, the email the account was made with, and whether a
               # DNS-01 challenge has a Cloudflare token to write with.
               "acme": {"pending": rec.get("acme_pending") or {}, "email": (rec.get("acme") or {}).get("email", ""),
                        "cf": bool(cf_token and cf_token()), "directory": ACME_DIRECTORY}}
        out.append((row, is_up))
    # Each node's daemon half at once (the operator, 18 Oct: the tab took
    # five seconds, the nodes' reads one after another): the view waits for
    # the slowest node rather than for all of them added up.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(out)))) as ex:
        halves = list(ex.map(lambda ri: _daemon_half(devapp, instance_state, ri[0]["node"], ri[0]["container"], ri[1]), out))
    for (row, _), (state, clash) in zip(out, halves, strict=True):
        row["clash"] = clash
        if state is not None:
            row["state"] = state
    return {"nodes": [row for row, _ in out], "image": IMAGE, "latest": latest_image(), "hostnames": hostnames()}


# ---- certificates from an ACME directory (R150) -----------------------------
# Let's Encrypt, or any ACME directory (BB_ACME_DIRECTORY for a test or a
# private CA): a pair asked for on the nginx page by hostname, by an HTTP-01
# challenge the node's nginx answers on port 80 (the token's line written
# into its config for the minutes it takes) or a DNS-01 record written
# through the Cloudflare API token Settings holds; kept on the node as any
# pasted pair is (set_cert) and renewed by renew_loop thirty days before it
# ends, the result on the bell either way.

ACME_DIRECTORY = os.environ.get("BB_ACME_DIRECTORY") or "https://acme-v02.api.letsencrypt.org/directory"
RENEW_BEFORE = 30 * 86400
RENEW_EVERY = 6 * 3600
cf_token = None          # () -> the Cloudflare API token, set by the server (settings.secret)
_acme_busy = set()
_acme_lock = threading.Lock()


def _acme_account_pem():
    """The ACME account key, made once and kept 0600 beside the nodes'
    pairs: one account for the install, whatever node asks."""
    d = STATE / "nginx"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = d / "acme-account.pem"
    try:
        return f.read_text()
    except OSError:
        import acme                                         # noqa: PLC0415
        pem = acme.account_key_new()
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(pem)
        return pem


def _acme_note(nid, host, **fields):
    """The state of a hostname's request on the record, for the page."""
    with _lock:
        st = _load()
        rec = st.setdefault(str(nid), {})
        pend = rec.setdefault("acme_pending", {})
        if fields.get("gone"):
            pend.pop(host, None)
        else:
            pend[host] = {**(pend.get(host) or {}), **fields, "at": int(time.time())}
        _save(st)


def _acme_said(nid, host, ok, why=""):
    """A result for the bell: the last few per node, newest first."""
    with _lock:
        st = _load()
        rec = st.setdefault(str(nid), {})
        said = [x for x in (rec.get("acme_said") or []) if x.get("host") != host]
        said.insert(0, {"host": host, "ok": bool(ok), "why": str(why or "")[:300], "at": int(time.time())})
        rec["acme_said"] = said[:12]
        _save(st)


def _node_addr(nid):
    for n in node_list():
        if n.get("id") == nid:
            return str(n.get("addr") or (n.get("agent") or {}).get("addr") or "")
    return ""


def _cf_zone(token, host):
    import tunnel                                           # noqa: PLC0415
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        got, err = tunnel._api("GET", f"/zones?name={cand}", token)
        if err:
            return None, err
        if got:
            return got[0], ""
    return None, f"no zone of yours holds {host}: is the domain on this Cloudflare account, and may the API token read zones?"


def _cf_txt(token, name, value, delete=False):
    """The _acme-challenge TXT record written, or taken off, through
    Cloudflare's API. "" or the error."""
    import tunnel                                           # noqa: PLC0415
    zone, err = _cf_zone(token, name)
    if err:
        return err
    recs, err = tunnel._api("GET", f"/zones/{zone['id']}/dns_records?type=TXT&name={name}", token)
    if err:
        return err
    have = next((r for r in recs or [] if str(r.get("content") or "").strip('"') == value), None)
    if delete:
        if have:
            _, err = tunnel._api("DELETE", f"/zones/{zone['id']}/dns_records/{have['id']}", token)
        return err
    if have:
        return ""
    _, err = tunnel._api("POST", f"/zones/{zone['id']}/dns_records", token,
                         {"type": "TXT", "name": name, "content": value, "ttl": 60,
                          "comment": "BuilderBot: an ACME challenge (R150), taken off when it is answered"})
    return err


def _challenge_served(addr, host, token, value, wait=120):
    """Whether the node's nginx answers the HTTP-01 token at its address,
    polled while the rebuild lands; a node whose address is unknown or
    unreachable from here is given the wait and then trusted."""
    if not addr:
        time.sleep(min(wait, 30))
        return True
    end = time.time() + wait
    while time.time() < end:
        try:
            req = urllib.request.Request(f"http://{addr}/.well-known/acme-challenge/{token}", headers={"Host": host})
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.read().decode(errors="replace").strip() == value:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(3)
    return False


def acme_request(nid, host, method, email, containers, devactions, devapp):
    """A pair for `host` from the ACME directory, asked for now in the
    background: {ok, started} or {error}. method is http-01 (port 80 of
    this node reachable at the name) or dns-01 (Cloudflare, with the API
    token Settings holds)."""
    host = str(host or "").strip().lower()
    method = str(method or "http-01").strip().lower()
    email = str(email or "").strip()
    if not HOST_RE.match(host) or "." not in host:
        return {"error": "a certificate is asked for by a public name like www.example.com"}
    if method not in ("http-01", "dns-01"):
        return {"error": "the challenge is http-01 or dns-01"}
    if method == "dns-01" and not (cf_token and cf_token()):
        return {"error": "a DNS-01 challenge writes the record through Cloudflare's API: set the Cloudflare API token under Controller settings first"}
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return {"error": "the email Let's Encrypt writes to about this certificate is not an address"}
    if not deployed(devapp, nid) and method == "http-01":
        return {"error": "an HTTP-01 challenge is answered by this node's nginx: Deploy it first"}
    with _acme_lock:
        if (nid, host) in _acme_busy:
            return {"error": f"a certificate for {host} is being asked for already"}
        _acme_busy.add((nid, host))
    with _lock:
        st = _load()
        rec = st.setdefault(str(nid), {})
        if email:
            rec.setdefault("acme", {})["email"] = email
        _save(st)
    _acme_note(nid, host, method=method, state="asking", error="")
    threading.Thread(target=_acme_run, args=(nid, host, method, email, containers, devactions, devapp),
                     name=f"acme-{host}", daemon=True).start()
    return {"ok": True, "started": True, "host": host}


def _acme_run(nid, host, method, email, containers, devactions, devapp):
    import acme                                             # noqa: PLC0415
    addr = _node_addr(nid)
    token = cf_token() if cf_token else ""

    def present(kind, name, tok, value):
        if kind == "http-01":
            with _lock:
                st = _load()
                st.setdefault(str(nid), {}).setdefault("acme_tokens", {})[tok] = value
                _save(st)
            _acme_note(nid, host, state="answering the challenge on port 80")
            r = apply(nid, containers, devactions, devapp)
            if r.get("error"):
                raise acme.AcmeError(f"nginx could not be rebuilt with the challenge: {r['error']}")
            if not _challenge_served(addr, name, tok, value):
                raise acme.AcmeError(f"this node's nginx did not answer the challenge at {addr or 'its address'}: "
                                     "is port 80 open there, and does the name reach this node?")
        else:
            _acme_note(nid, host, state="writing the DNS record")
            err = _cf_txt(token, f"_acme-challenge.{name}", value)
            if err:
                raise acme.AcmeError(f"Cloudflare refused the record: {err}")
            time.sleep(15)

    def cleanup(kind, name, tok, value):
        if kind == "http-01":
            with _lock:
                st = _load()
                (st.get(str(nid)) or {}).get("acme_tokens", {}).pop(tok, None)
                _save(st)
        else:
            _cf_txt(token, f"_acme-challenge.{name}", value, delete=True)

    try:
        client = acme.Client(ACME_DIRECTORY, _acme_account_pem(), contact=f"mailto:{email}" if email else "")
        _acme_note(nid, host, state="ordering")
        chain, key = client.issue([host], method, present, cleanup)
        got = set_cert(nid, chain, key, host)
        if got.get("error"):
            raise acme.AcmeError(f"the certificate came, and could not be kept: {got['error']}")
        with _lock:
            st = _load()
            c = st.setdefault(str(nid), {}).setdefault("certs", {}).get(host) or {}
            c["acme"] = {"method": method, "email": email, "at": int(time.time())}
            st[str(nid)]["certs"][host] = c
            _save(st)
        _acme_note(nid, host, gone=True)
        _acme_said(nid, host, True, f"a certificate for {host} from {ACME_DIRECTORY.split('/')[2]}, until "
                                    + time.strftime("%d %b %Y", time.localtime(got["cert"]["expires"])))
        r = apply(nid, containers, devactions, devapp)
        if r.get("error"):
            _acme_said(nid, host, False, f"the certificate is kept, and nginx was not rebuilt with it: {r['error']}")
    except Exception as e:                                  # noqa: BLE001 (the thread must say, never die silent)
        why = str(e)
        _acme_note(nid, host, state="failed", error=why[:300])
        _acme_said(nid, host, False, why)
        print(f"dashboard: acme {host} on {nid}: {why}", flush=True)
        # A token left in the config comes out.
        with _lock:
            st = _load()
            if (st.get(str(nid)) or {}).get("acme_tokens"):
                st[str(nid)]["acme_tokens"] = {}
                _save(st)
                dirty = True
            else:
                dirty = False
        if dirty:
            with contextlib.suppress(Exception):            # noqa: BLE001
                apply(nid, containers, devactions, devapp)
    finally:
        with _acme_lock:
            _acme_busy.discard((nid, host))


def acme_due(now=None):
    """[(nid, host, meta)] for every ACME pair ending within RENEW_BEFORE."""
    now = now or time.time()
    out = []
    for nid, rec in _load().items():
        if nid.startswith("_") or not isinstance(rec, dict):
            continue
        for host, c in (rec.get("certs") or {}).items():
            if (c or {}).get("set") and (c.get("acme") or {}).get("method") and int(c.get("expires") or 0) - now < RENEW_BEFORE:
                out.append((nid, host, c["acme"]))
    return out


def renew_loop(containers, devactions, devapp):
    """Every few hours: each ACME pair ending within thirty days asked for
    again, the way it was first; a failure is said on the bell and tried
    again next round. Started by the server beside check_loop."""
    time.sleep(CHECK_DELAY)
    while True:
        with contextlib.suppress(Exception):               # noqa: BLE001 (the loop outlives one bad answer)
            for nid, host, meta in acme_due():
                acme_request(nid, host, meta.get("method"), meta.get("email"), containers, devactions, devapp)
        time.sleep(RENEW_EVERY)


def acme_rows():
    """The bell's rows (kind acme): a certificate that came or a request
    that failed, per node and hostname, the newest of each."""
    out = []
    for nid, rec in _load().items():
        if nid.startswith("_") or not isinstance(rec, dict):
            continue
        for x in rec.get("acme_said") or []:
            out.append({"kind": "acme", "id": f"{nid}:{x['host']}", "node": node_name(nid) if node_name else nid,
                        "nid": nid, "host": x["host"], "bad": not x.get("ok"), "why": x.get("why", ""),
                        "at": x.get("at", 0), "key": f"acme:{nid}:{x['host']}@{x.get('at', 0)}"})
    return out


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
            _bump()
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
        _bump()
    return {"ok": True, "hostnames": hostnames()}


def save_routes(nid, routes):
    got = clean_routes(routes)
    if isinstance(got, dict):
        return got
    # A hostname typed into a route row (the operator, 13 Oct: the pulldown
    # offered no subdomain) joins the shared list, so every node's rows
    # offer it from now on.
    for r in got:
        if r["host"] != "*" and r["host"] not in _hosts_saved():
            add_hostname(r["host"])
    with _lock:
        st = _load()
        st.setdefault(str(nid), {})["routes"] = got
        _save(st)
    return {"ok": True, "routes": got}


def add_route(nid, port, cert, containers, devactions, devapp, host=""):
    """A route written from a container's row on the Containers page (R209): to
    `port` on the node, at `host` (a subdomain, the operator, 13 Oct) or
    else at the hostname the certificate is filed under (its domain), with
    that pair, or at any hostname on 80 alone with no certificate; applied
    at once. A hostname the chosen pair does not cover is refused by name
    (cert_for's rule: a pair covers its domain and the names under it). The
    same hostname and port again is refused by name; a port already routed
    at one hostname takes another (the operator, 14 Oct: a site at its
    domain and at www), and the rest is the nginx page's."""
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
        return {"error": f"this node holds no certificate filed under {cert}: paste it on the nginx page first"}
    host = str(host or "").strip().lower()
    if host and host != "*" and not HOST_RE.match(host):
        return {"error": f"a hostname is a name like app.example.com: not {host}"}
    if host and cert and cert_for(rec, host) != cert:
        return {"error": f"the pair filed under {cert} does not cover {host}: pick a pair filed under its domain, "
                         "or paste one on the nginx page"}
    host = host or cert or "*"
    if host != "*" and host not in _hosts_saved():
        add_hostname(host)
    routes = list(rec.get("routes") or [])
    for r in routes:
        if int(r.get("port") or 0) == port and (r.get("host") or "*") == host:
            where = f"{r.get('host') or '*'}{r.get('path') or '/'}"
            return {"error": f"port {port} already has a route: {where} on this node's nginx; change it on the nginx page"}
    routes.append({"host": host, "path": "/", "port": port, "tls": bool(cert), "cert": cert})
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
        # The name is the node's name: one left by an uninstalled node of the
        # same name, whose machine is gone, is this node's to take.
        was = devapp._read_rec(name, devapp.MAIN).get("node")
        live = {n["id"] for n in node_list() if n.get("state") != "retired"}
        if was == nid or was in live:
            return {"error": f"{name} is already on the Containers page"}
        devapp.forget_container(name)
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
    """Update on the nginx page's node or its Docker row (R192): the newest
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
        return {"error": f"{name} is not on the Containers page"}
    return devactions.remove_instance(name, devapp.MAIN)
