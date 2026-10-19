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

    # The pin that means "no pin: the hostname's public certificate, by the
    # system's CAs" (R170): a controller behind Cloudflare presents the
    # edge's certificate, which changes under it and is not the controller's.
    CA = "ca"

    def __init__(self, url, token, pin="", door="agent"):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise SystemExit(f"controller URL is not http(s)://host[:port]: {url}")
        self.url, self.token, self.pin = url.rstrip("/"), token, pin
        self.scheme, self.host = u.scheme, u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.base = u.path.rstrip("/")
        # Which door it speaks to: the agent's, or a person's device's
        # (/api/v1/device/, R270), whose app reuses this connection whole.
        self.door = door

    def _conn(self, timeout):
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        ctx = ssl.create_default_context()
        if self.pin == self.CA:
            # A public hostname (R170): the system's CAs and the name, as a
            # browser would; nothing is pinned, since the certificate the
            # node sees is Cloudflare's edge's and not the controller's.
            c = http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=ctx)
            c.connect()
            self.seen_pin = self.CA
            return c
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
            c.request(method, f"{self.base}/api/v1/{self.door}/{verb}", data, hdrs)
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
            c.request("GET", f"{self.base}/api/v1/{self.door}/{path}", None,
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

    def upload_pieces(self, path, src, piece, timeout=600, say=None):
        """upload() in pieces of `piece` bytes, each its own request with
        offset and total in the query (relocate.data_put takes them): what
        a body limit on the way (Cloudflare's 100 MB, R170) asks for. The
        last piece's answer is the whole upload's; a piece the controller
        says it has already is not sent again."""
        size = os.path.getsize(src)
        sep = "&" if "?" in path else "?"
        off = 0
        while True:
            n = min(piece, size - off)
            code, r = self.upload(f"{path}{sep}offset={off}&total={size}", src, timeout=timeout,
                                  offset=off, length=n)
            if code != 200:
                return code, r
            off = int((r or {}).get("bytes") or off + n)
            if say and off < size:
                say(off)
            if off >= size or not (r or {}).get("more"):
                return code, r

    def upload(self, path, src, timeout=600, offset=0, length=None):
        """POST a file as the raw body, or `length` bytes of it from
        `offset` (a transcript's new tail: the file may grow while it is
        sent, and only what was asked for goes). (status, decoded answer)."""
        try:
            size = os.path.getsize(src) - offset if length is None else length
            c = self._conn(timeout)
            c.putrequest("POST", f"{self.base}/api/v1/{self.door}/{path}")
            c.putheader("Authorization", "Bearer " + self.token)
            c.putheader("User-Agent", f"builderbot-agent/{AGENT_VERSION}")
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(size))
            c.endheaders()
            with open(src, "rb") as f:
                f.seek(offset)
                left = size
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        raise OSError(f"{src} is shorter than when it was measured")
                    c.send(chunk)
                    left -= len(chunk)
            r = c.getresponse()
            payload = r.read()
            c.close()
        except (OSError, http.client.HTTPException) as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}
        try:
            return r.status, json.loads(payload) if payload else {}
        except ValueError:
            return r.status, {"error": payload[:200].decode("utf-8", "replace")}
