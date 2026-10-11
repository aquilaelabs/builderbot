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
import json
import re
import ssl
import tempfile
import threading
import time
from pathlib import Path

STATE = None
write_json = None
_lock = threading.Lock()

# The image: a pinned tag, moved by hand like every other version here.
IMAGE = "nginx:1.27-alpine"
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


def cert_paths(rec, host):
    """(cert, key) paths inside the container for a server's hostname:
    its own certificate where it has one (R175), else the node's default,
    else none."""
    if host and host != "*" and ((rec.get("certs") or {}).get(host) or {}).get("set"):
        return f"/etc/nginx/certs/{host}/cert.pem", f"/etc/nginx/certs/{host}/key.pem"
    if (rec.get("cert") or {}).get("set"):
        return "/etc/nginx/certs/cert.pem", "/etc/nginx/certs/key.pem"
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
        out.append({"host": host, "path": path, "port": int(port), "tls": r.get("tls") is not False})
    return out


def nginx_conf(routes, has_cert, rec=None):
    """nginx's config from the routes: a server per hostname, each path to
    its port on this machine, 443 with the certificate where there is one
    (the hostname's own, else the node's default: R175), and any name not
    routed answered by closing the connection, so the box serves nothing it
    was not told to. `has_cert` is the default's; `rec` carries the rest."""
    rec = rec if rec is not None else ({"cert": {"set": True}} if has_cert else {})
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
    dflt = cert_paths(rec, "*")
    if dflt[0] and not (any_host and any(r["tls"] for r in by_host["*"])):
        lines.append("  server { listen 443 ssl default_server; server_name _; "
                     f"ssl_certificate {dflt[0]}; ssl_certificate_key {dflt[1]}; return 444; }}")
    for host, rs in by_host.items():
        name = "_" if host == "*" else host
        cert, key = cert_paths(rec, host)
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
    has_cert = bool((rec.get("cert") or {}).get("set"))
    # The hostnames' own certificates that a route uses (R175).
    own = sorted(h for h, c in (rec.get("certs") or {}).items()
                 if (c or {}).get("set") and any(r["host"] == h for r in routes))
    conf = nginx_conf(routes, has_cert, rec)
    out = ["# Written by BuilderBot from the nginx tab (nginxproxy.py); Save there rewrites it.",
           "services:",
           "  nginx:",
           f"    image: {IMAGE}",
           "    restart: unless-stopped",
           "    network_mode: host",
           "    configs:",
           "      - source: nginx_conf",
           "        target: /etc/nginx/nginx.conf"]
    if has_cert:
        out += ["      - source: tls_cert", "        target: /etc/nginx/certs/cert.pem",
                "      - source: tls_key", "        target: /etc/nginx/certs/key.pem", "        mode: 0400"]
    for h in own:
        out += [f"      - source: tls_cert_{_cert_slug(h)}", f"        target: /etc/nginx/certs/{h}/cert.pem",
                f"      - source: tls_key_{_cert_slug(h)}", f"        target: /etc/nginx/certs/{h}/key.pem", "        mode: 0400"]
    # compose reads $name in a config's content as its own variable and
    # empties it (nginx's $host became nothing on bb-dev-sandbox, 10 Oct):
    # a literal dollar is written $$ there.
    out += ["configs:", "  nginx_conf:", "    content: |", _indent(conf.replace("$", "$$"), 6)]
    if has_cert:
        cert, key = _read_cert(nid)
        out += ["  tls_cert:", "    content: |", _indent(cert, 6),
                "  tls_key:", "    content: |", _indent(key, 6)]
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
    """The node's default certificate, or with `host` that hostname's own
    (R175): checked, kept 0600, summarized in the record."""
    host = str(host or "").strip().lower()
    if host and not HOST_RE.match(host):
        return {"error": f"a certificate is for a hostname like www.example.com, or the node's default: not {host}"}
    got = check_cert(cert, key)
    if got.get("error"):
        return got
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
        if host:
            rec.setdefault("certs", {})[host] = summary
        else:
            rec["cert"] = summary
        _save(st)
    return {"ok": True, "cert": summary, "host": host}


def drop_cert(nid, host=""):
    host = str(host or "").strip().lower()
    d = _cert_dir(nid, host)
    for name in ("cert.pem", "key.pem"):
        with contextlib.suppress(OSError):
            (d / name).unlink()
    with _lock:
        st = _load()
        rec = st.get(str(nid)) or {}
        if host:
            (rec.get("certs") or {}).pop(host, None)
        else:
            rec.pop("cert", None)
        _save(st)
    return {"ok": True}


# ---- the tab's verbs ----------------------------------------------------------

def record(nid):
    return dict(_load().get(str(nid)) or {})


def deployed(devapp, nid):
    """Whether the nginx tab's container is on this node: written from here
    (a file source under its name) and bound to this node."""
    name = container_name(nid)
    return bool(devapp.is_file_source(name) and devapp._read_rec(name, devapp.MAIN).get("node") == nid)


def view(devapp, instance_state):
    """Every agent node with what its nginx is: deployed or not, its routes,
    its certificate (never the key), and the containers on it holding 80 or
    443 themselves. `instance_state` is devactions.state, for a deployed one."""
    st = _load()
    out = []
    for n in node_list():
        if n.get("kind") != "agent" or n.get("state") in ("retired", "pending"):
            continue
        nid, rec = n["id"], st.get(n["id"]) or {}
        name = container_name(nid)
        is_up = deployed(devapp, nid)
        row = {"node": nid, "name": n.get("name") or nid, "host_only": bool((n.get("config") or {}).get("host_only")),
               "container": name, "deployed": is_up,
               "routes": rec.get("routes") or [], "cert": rec.get("cert") or {},
               "certs": rec.get("certs") or {},
               "live": n.get("live"), "clash": []}
        if is_up:
            with contextlib.suppress(Exception):  # noqa: BLE001 (a row still draws without its state)
                row["state"] = instance_state(name, devapp.MAIN)
        with contextlib.suppress(Exception):  # noqa: BLE001 (a node that does not answer has no clash to show)
            with devapp.on_node(nid):
                row["clash"] = taken_ports(name, devapp.MAIN, [{"published": "80"}, {"published": "443"}])
        out.append(row)
    return {"nodes": out, "image": IMAGE}


def save_routes(nid, routes):
    got = clean_routes(routes)
    if isinstance(got, dict):
        return got
    with _lock:
        st = _load()
        st.setdefault(str(nid), {})["routes"] = got
        _save(st)
    return {"ok": True, "routes": got}


def deploy(nid, containers, devactions, devapp):
    """The container made on the node from the generated compose file, then
    built: Deploy on a node without one, and the enroll dialog's tick once
    the node has enrolled."""
    name = container_name(nid)
    if devapp.is_file_source(name):
        return {"error": f"{name} is already on the Docker tab"}
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


def remove(nid, devactions, devapp):
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"error": f"{name} is not on the Docker tab"}
    return devactions.remove_instance(name, devapp.MAIN)
