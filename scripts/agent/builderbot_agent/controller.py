"""The connection to the controller."""
import hashlib
import http.client
import json
import os
import shutil
import ssl
import urllib.request
from . import AGENT_VERSION


# ---------------------------------------------------------------------------
# the connection

class Controller:
    """One controller, one credential, one way to talk to it.

    TLS is verified by PIN, not by CA: the controller's certificate digest is
    learned at enrollment (given with --pin, or trusted on first use and
    printed so it can be checked) and every later connection must present
    the same one. A LAN dashboard with a self-signed certificate is exactly
    the case, and a CA is a later layer (docs/nodes.md §4). Plain http is
    allowed and said plainly: the token then travels in the clear, which is
    no worse than the dashboard's own credential already does on that
    network, and no better.
    """

    def __init__(self, url, token, pin=""):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise SystemExit(f"controller URL is not http(s)://host[:port]: {url}")
        self.url, self.token, self.pin = url.rstrip("/"), token, pin
        self.scheme, self.host = u.scheme, u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base = u.path.rstrip("/")

    def _conn(self, timeout):
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE       # the pin below is the check
        # The certificate is pinned on first use and any other refused; a CA
        # check would refuse the self-signed one a home proxy serves.
        # nosemgrep: httpsconnection-detected
        c = http.client.HTTPSConnection(self.host, self.port, timeout=timeout,
                                        context=ctx)
        c.connect()
        seen = "sha256:" + hashlib.sha256(c.sock.getpeercert(True)).hexdigest()
        if self.pin and seen != self.pin:
            c.close()
            raise ssl.SSLError(f"controller certificate changed: pinned "
                               f"{self.pin[:19]}…, presented {seen[:19]}…")
        self.seen_pin = seen
        return c

    def call(self, verb, body=None, timeout=30, method="POST", raw=False):
        """(status, decoded body). Status 0 means no answer at all
        (the controller is down or unreachable), and is the case the loop
        backs off on rather than treating as a refusal."""
        try:
            c = self._conn(timeout)
            hdrs = {"Authorization": "Bearer " + self.token,
                    "User-Agent": f"builderbot-agent/{AGENT_VERSION}"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                hdrs["Content-Type"] = "application/json"
            c.request(method, f"{self.base}/api/v1/agent/{verb}", data, hdrs)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        if raw:
            return r.status, payload
        if r.status == 204 or not payload:
            return r.status, {}
        try:
            return r.status, json.loads(payload)
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}

    def fetch(self, path, dest, timeout=600):
        """GET a large body straight to a file. (status, digest-header).
        The snapshot and the bundle both arrive this way, and neither
        belongs in memory twice."""
        try:
            c = self._conn(timeout)
            c.request("GET", f"{self.base}/api/v1/agent/{path}", None,
                      {"Authorization": "Bearer " + self.token,
                       "User-Agent": f"builderbot-agent/{AGENT_VERSION}"})
            r = c.getresponse()
            if r.status != 200:
                r.read()
                c.close()
                return r.status, ""
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            c.close()
            os.replace(tmp, dest)
            return 200, (r.getheader("X-Snapshot-Digest") or r.getheader("X-Bundle-Digest") or "")
        except (OSError, http.client.HTTPException) as e:
            return 0, str(e)

    def upload(self, path, src, timeout=600):
        """POST a file as the raw body. (status, decoded answer)."""
        try:
            size = os.path.getsize(src)
            c = self._conn(timeout)
            c.putrequest("POST", f"{self.base}/api/v1/agent/{path}")
            c.putheader("Authorization", "Bearer " + self.token)
            c.putheader("User-Agent", f"builderbot-agent/{AGENT_VERSION}")
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(size))
            c.endheaders()
            with open(src, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    c.send(chunk)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        try:
            return r.status, json.loads(payload) if payload else {}
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}
