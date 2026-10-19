"""The home tunnel, run by the controller itself (R176, the operator, 11 Oct).

A node off the LAN reaches the controller at a public hostname a tunnel from
home publishes (R170). Rather than a cloudflared somebody sets up beside
BuilderBot, the controller carries cloudflared in its own image and runs it
from two settings: the tunnel's token, pasted once from Zero Trust, and the
hostname. The process is this module's child, started when the settings
say so, restarted when it dies, stopped when the token is taken away; its
last lines and whether it has registered a connection are what the
Settings page shows. With an API token as well (optional), the hostname's
DNS record and the tunnel's two rules (the agent's API to the controller,
everything else 404) are written through Cloudflare's API rather than
clicked, so the whole of the home side is one paste.

The token never reaches a command line: cloudflared reads TUNNEL_TOKEN from
its environment. Nothing of it is logged.
"""
import base64
import collections
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

# Which binary: the image's, or a stub the harness points at.
BIN = os.environ.get("BB_CLOUDFLARED", "cloudflared")
API = "https://api.cloudflare.com/client/v4"
# The dashboard's own port inside the container, which is where cloudflared
# forwards to: it runs beside the server in the same network.
port = 7680
settings = None            # the settings store, handed in by configure()
urlopen = urllib.request.urlopen     # the seam a test replaces

_lock = threading.Lock()
_proc = None
_token = ""                 # the token the running process was started with
_tail = collections.deque(maxlen=40)
_since = 0
_connected = False
_stopped = False
_error = ""
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?)+$")


def configure(*, settings_mod, dash_port):
    globals().update(settings=settings_mod, port=int(dash_port))


def installed():
    return bool(shutil.which(BIN) or os.access(BIN, os.X_OK))


def decode_token(token):
    """What a tunnel token says about itself: the account and the tunnel it
    is for ({account, tunnel}), or {} for anything that is not one. The
    token is base64 of a small JSON object; its secret stays in it."""
    try:
        raw = base64.b64decode(str(token or "").strip() + "==")
        d = json.loads(raw)
        a, t = str(d.get("a") or ""), str(d.get("t") or "")
        if re.fullmatch(r"[0-9a-f]{32}", a) and re.fullmatch(r"[0-9a-f-]{36}", t):
            return {"account": a, "tunnel": t}
    except (ValueError, TypeError):
        pass
    return {}


# ---- the process ---------------------------------------------------------------

def _wanted():
    """(token, host) as the settings say, "" for either not set."""
    if settings is None:
        return "", ""
    return settings.secret("tunnel_token"), str(settings.get("tunnel_host") or "")


def apply():
    """The process brought in step with the settings: started with the
    token, restarted with a new one, stopped with none. What the tab
    shows afterwards is status()."""
    global _proc, _token, _since, _connected, _stopped, _error
    token, host = _wanted()
    with _lock:
        if not token:
            _stopped = True
            _stop_locked()
            _error = ""
            return status()
        if not installed():
            _error = f"{BIN} is not in this image: the tunnel cannot run from here"
            return status()
        if _proc is not None and _proc.poll() is None and token == _token:
            return status()
        _stop_locked()
        _stopped = False
        _error = ""
        _start_locked(token)
    return status()


def _start_locked(token):
    global _proc, _token, _since, _connected
    env = {k: v for k, v in os.environ.items() if not k.startswith("TUNNEL_")}
    env["TUNNEL_TOKEN"] = token
    env["NO_AUTOUPDATE"] = "true"
    try:
        _proc = subprocess.Popen([BIN, "--no-autoupdate", "tunnel", "run"], env=env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, start_new_session=True)
    except OSError as e:
        _proc = None
        globals()["_error"] = f"could not start {BIN}: {e}"
        return
    _token, _since, _connected = token, int(time.time()), False
    _tail.clear()
    threading.Thread(target=_read, args=(_proc,), name="tunnel-log", daemon=True).start()


def _stop_locked():
    global _proc, _connected
    p = _proc
    _proc = None
    _connected = False
    if p is None or p.poll() is not None:
        return
    try:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    except OSError:
        pass


def _read(p):
    """The process's lines, kept for the tab, and its registering read off
    them; when it ends and is still wanted, started again after a pause."""
    global _connected
    for line in p.stdout:
        line = line.rstrip("\n")
        _tail.append(_redact(line)[:300])
        if "Registered tunnel connection" in line:
            _connected = True
        elif "Unregistered tunnel connection" in line or "connection lost" in line.lower():
            _connected = False
    p.wait()
    with _lock:
        if _proc is not p:
            return             # stopped or replaced on purpose
        _connected = False
        if _stopped:
            return
    time.sleep(5)
    with _lock:
        if _proc is p and not _stopped:
            token, _ = _wanted()
            if token:
                _start_locked(token)


# ---- does the name reach this controller? -------------------------------------
# Registered is cloudflared's word, not the route's: a tunnel whose rule for
# /api/v1/agent/ pointed at a fixed status answered 200 with nothing, the
# tab said "reaches this controller", and a node enrolled with an empty
# agent (the operator, 11 Oct). So the name is asked, off the request's
# thread and at most once a minute: an agent path that is not one answers
# 405 with this server's JSON, and anything else is somebody else.
ROUTE_EVERY = 60
# Where the name is asked: https://HOST, or the harness's own server, which
# stands in for a tunnel whose name nobody owns.
ROUTE_BASE = os.environ.get("BB_TUNNEL_ROUTE_BASE", "")
_route = {"at": 0, "ok": None, "said": "", "host": ""}


def route_check(host):
    """(ok, said) for https://HOST/api/v1/agent/route-check: ok when the
    answer is this controller's (JSON with an error in it), with what was
    seen otherwise."""
    req = urllib.request.Request(f"{ROUTE_BASE or 'https://' + host}/api/v1/agent/route-check", method="GET",
                                 headers={"User-Agent": "builderbot-route-check"})
    try:
        with urlopen(req, timeout=15) as r:
            code, ctype, body = r.status, r.headers.get("Content-Type", ""), r.read(400)
    except urllib.error.HTTPError as e:
        code, ctype, body = e.code, e.headers.get("Content-Type", ""), e.read(400)
    except (OSError, ValueError) as e:
        return False, f"{host} did not answer from here: {e}"[:200]
    if "json" in ctype and b'"error"' in body:
        return True, ""
    return False, (f"{host} answers {code} on the agent's API with "
                   f"{'nothing' if not body else 'something else'}: the tunnel's rule for "
                   f"/api/v1/agent/ does not go to this controller (it should be HTTP localhost:{port})")


def _route_refresh(host):
    ok, said = route_check(host)
    _route.update(at=int(time.time()), ok=ok, said=said, host=host)


def route(host):
    """The last answer for the name, refreshed in the background when it
    is older than a minute or for another name."""
    now = int(time.time())
    if host and (_route["host"] != host or now - _route["at"] >= ROUTE_EVERY):
        _route["at"] = now          # one probe in flight, not one per poll
        threading.Thread(target=_route_refresh, args=(host,), name="tunnel-route", daemon=True).start()
    return {"ok": _route["ok"] if _route["host"] == host else None, "said": _route["said"] if _route["host"] == host else ""}


def _redact(line):
    return re.sub(r"eyJ[A-Za-z0-9_=-]{20,}", "eyJ…", line)


def status():
    """What the Settings page says: whether cloudflared is here, running,
    registered, at which hostname, since when, its last lines."""
    token, host = _wanted()
    running = _proc is not None and _proc.poll() is None
    reach = route(host) if running and _connected and host else {"ok": None, "said": ""}
    return {"route": reach,
            "installed": installed(), "configured": bool(token), "host": host, "port": port,
            "running": running, "connected": bool(running and _connected),
            "since": _since if running else 0,
            "tail": list(_tail)[-6:], "error": _error,
            "ids": decode_token(token) if token else {}}


# ---- the home side through Cloudflare's API (optional) ------------------------

def _api(method, path, api_token, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 headers={"Authorization": "Bearer " + api_token,
                                          "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode())
        except ValueError:
            d = {}
        msgs = "; ".join(str(x.get("message") or "") for x in (d.get("errors") or [])) or f"HTTP {e.code}"
        return None, f"{method} {path}: {msgs}"
    except (OSError, ValueError) as e:
        return None, f"{method} {path}: {e}"
    if not d.get("success", True):
        return None, f"{method} {path}: " + "; ".join(str(x.get("message") or "") for x in (d.get("errors") or []))
    return d.get("result"), ""


def ingress(host):
    """The tunnel's rules: the agent's API to the dashboard beside this
    process, everything else at the name 404, anything else 404."""
    return [{"hostname": host, "path": r"^/api/v1/agent/", "service": f"http://localhost:{port}"},
            {"hostname": host, "service": "http_status:404"},
            {"service": "http_status:404"}]


def publish(api_token):
    """The hostname's DNS record and the tunnel's rules, written through
    Cloudflare's API with `api_token` (Zone DNS Edit and Account Cloudflare
    Tunnel Edit): {ok, did: [...]} or {error}. Nothing is clicked."""
    token, host = _wanted()
    ids = decode_token(token)
    if not ids:
        return {"error": "the tunnel token does not read as one: it is the long eyJ… string from Zero Trust's install command"}
    if not host or not HOST_RE.match(host):
        return {"error": "the public hostname is a name like bb.example.com"}
    # The zone: the longest suffix of the hostname Cloudflare knows.
    parts = host.split(".")
    zone = None
    for i in range(1, len(parts) - 1):
        cand = ".".join(parts[i:])
        got, err = _api("GET", f"/zones?name={cand}", api_token)
        if err:
            return {"error": err}
        if got:
            zone = got[0]
            break
    if not zone:
        return {"error": f"no zone of yours holds {host}: is the domain on this Cloudflare account, and may the API token read zones?"}
    did = []
    target = f"{ids['tunnel']}.cfargotunnel.com"
    recs, err = _api("GET", f"/zones/{zone['id']}/dns_records?name={host}", api_token)
    if err:
        return {"error": err}
    rec = {"type": "CNAME", "name": host, "content": target, "proxied": True, "ttl": 1,
           "comment": "BuilderBot: the controller's public hostname (R176)"}
    have = next((r for r in recs or [] if r.get("type") == "CNAME"), None)
    if have and have.get("content") == target and have.get("proxied"):
        did.append(f"DNS: {host} already points at the tunnel")
    elif have:
        _, err = _api("PUT", f"/zones/{zone['id']}/dns_records/{have['id']}", api_token, rec)
        if err:
            return {"error": err}
        did.append(f"DNS: {host} now points at the tunnel")
    else:
        if any(r.get("type") in ("A", "AAAA") for r in recs or []):
            return {"error": f"{host} already has an address record: take it off, or pick another name"}
        _, err = _api("POST", f"/zones/{zone['id']}/dns_records", api_token, rec)
        if err:
            return {"error": err}
        did.append(f"DNS: {host} made, pointing at the tunnel")
    _, err = _api("PUT", f"/accounts/{ids['account']}/cfd_tunnel/{ids['tunnel']}/configurations", api_token,
                  {"config": {"ingress": ingress(host)}})
    if err:
        return {"error": err}
    did.append(f"rules: {host}/api/v1/agent/ to the controller, everything else 404")
    return {"ok": True, "did": did}
