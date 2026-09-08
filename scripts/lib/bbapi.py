"""The controller's API, from `bb` — one client for the verbs that reach it.

bb used to carry four copies of the same twelve lines: build a Request to
http://127.0.0.1:<port>, send the auth header, decode the answer or the
error. Each assumed the dashboard was on the loopback, which was true for as
long as bb only ran on the controller. Since roadmap #24 a session runs ON A
NODE, where the controller is at BB_CONTROLLER over the LAN and possibly
https with a self-signed certificate — and then the four copies would each
have needed the same three changes.

So this is where those changes live:

  * the URL is BB_CONTROLLER when set (the agent exports it into every
    session it starts), the loopback otherwise;
  * https is verified by PIN, not by CA, exactly as the node agent verifies
    it: BB_CONTROLLER_PIN is the certificate digest the node learned at
    enrollment, and a different one is refused. No pin and https is allowed
    and unverified — the node's own choice at enrollment, repeated here;
  * the auth header is whatever bb_auth_or_die produced: a session token
    (Bearer) or a name:password for the command (Basic).

Standard library only, like everything else bb runs, and loaded by path from
the lib directory beside bb (BB_LIB) so the checkout's copy runs with the
checkout's bb.
"""
import base64
import hashlib
import http.client
import json
import os
import ssl
import urllib.parse


def keep_token(tok):
    """A renewed session token, written where bb_token_now reads: the same
    per-project file bb-tty writes when a tab is opened, so a session in use
    never runs out (users.renewal). The project comes from the token itself
    rather than the environment, because bb runs with BB_PROJECT set and a
    hook may not. Best effort: a token that could not be kept is a token
    that expires on schedule, which is what happened before."""
    try:
        raw = tok[len("bbs_"):]
        project = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode().split("|")[0]
        if not project or "/" in project:
            return
        home = os.environ.get("HOME", "")
        d = os.environ.get("XDG_CACHE_HOME") or (home and os.path.join(home, ".cache")) \
            or f"/tmp/bb-scope-{os.getuid()}"
        d = os.path.join(d, "builderbot")
        os.makedirs(d, mode=0o700, exist_ok=True)
        tmp = os.path.join(d, f"token-{project}.new")
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(tok + "\n")
        os.replace(tmp, os.path.join(d, f"token-{project}"))
    except (OSError, ValueError, UnicodeDecodeError):
        pass


def url():
    return (os.environ.get("BB_CONTROLLER")
            or f"http://127.0.0.1:{os.environ.get('DASHBOARD_PORT', '7680')}").rstrip("/")


def _conn(timeout):
    u = urllib.parse.urlsplit(url())
    port = u.port or (443 if u.scheme == "https" else 80)
    if u.scheme != "https":
        return http.client.HTTPConnection(u.hostname, port, timeout=timeout), u.path.rstrip("/")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                 # the pin below is the check
    c = http.client.HTTPSConnection(u.hostname, port, timeout=timeout, context=ctx)
    c.connect()
    pin = os.environ.get("BB_CONTROLLER_PIN", "")
    seen = "sha256:" + hashlib.sha256(c.sock.getpeercert(True)).hexdigest()
    if pin and seen != pin:
        c.close()
        raise OSError(f"controller certificate changed: pinned {pin[:19]}…, "
                      f"presented {seen[:19]}…")
    return c, u.path.rstrip("/")


def call(path, body=None, auth="", method="", timeout=30):
    """One request; the decoded JSON answer, or {"error": ...}.

    The shape every caller in bb already handled: an HTTP error whose body
    is JSON comes back as that JSON (the server's own sentence), any other
    failure as an error string. POST when a body is given, GET otherwise."""
    hdrs = {"Authorization": auth or os.environ.get("BB_AUTH_HEADER", "")}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    try:
        c, base = _conn(timeout)
        c.request(method or ("POST" if body is not None else "GET"), base + path, data, hdrs)
        r = c.getresponse()
        payload = r.read()
        fresh = r.getheader("X-BB-Session", "")
        c.close()
    except (OSError, http.client.HTTPException) as e:
        return {"error": str(e)}
    if fresh and fresh.startswith("bbs_"):
        keep_token(fresh)
    if r.status == 204 or not payload:
        return {} if r.status < 400 else {"error": f"HTTP {r.status}"}
    try:
        got = json.loads(payload)
    except ValueError:
        return {"error": f"HTTP {r.status}"}
    if r.status >= 400 and isinstance(got, dict) and not got.get("error"):
        got["error"] = f"HTTP {r.status}"
    return got
