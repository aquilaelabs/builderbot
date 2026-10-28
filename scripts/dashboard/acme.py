"""An ACME client (RFC 8555) for Let's Encrypt and any ACME directory (R150):
an account key and its JWS, an order for one or more names, the HTTP-01 or
DNS-01 challenge presented by a caller's hook, the finalize with a fresh key
and CSR, and the chain fetched. Built on the cryptography library the image
carries (R158 step 3) and the standard library's HTTP; nothing here touches
nginx or DNS: nginxproxy.py presents an HTTP-01 token on a node's nginx and
tunnel.py writes a DNS-01 record through Cloudflare's API, each handed in
as `present` and `cleanup`.

A certificate is asked for as

    client = Client(DIRECTORY, account_pem, contact="mailto:you@example.com")
    cert_pem, key_pem = client.issue(["www.example.com"], "http-01", present, cleanup)

where present(kind, name, token, value) makes the challenge answerable
(for http-01 `value` is the key authorization to serve at
/.well-known/acme-challenge/TOKEN, for dns-01 the TXT value for
_acme-challenge.NAME) and cleanup takes it down again. Errors are
AcmeError, whose text is the server's own problem detail where it gave one.
"""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

LETS_ENCRYPT = "https://acme-v02.api.letsencrypt.org/directory"
LETS_ENCRYPT_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
AGENT = "BuilderBot (+https://github.com/aquilaelabs/builderbot)"
TIMEOUT = 30
POLL_S = 2.0
POLL_FOR = 180


class AcmeError(Exception):
    """What the ACME server, or the challenge, said went wrong."""


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def account_key_new():
    """A new account key (EC P-256), as PEM, for the caller to keep sealed."""
    k = ec.generate_private_key(ec.SECP256R1())
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption()).decode()


def _load_key(pem):
    k = serialization.load_pem_private_key(pem.encode() if isinstance(pem, str) else pem, password=None)
    if not isinstance(k, ec.EllipticCurvePrivateKey):
        raise AcmeError("the account key is not an EC key")
    return k


def _jwk(key):
    n = key.public_key().public_numbers()
    return {"crv": "P-256", "kty": "EC", "x": b64(n.x.to_bytes(32, "big")), "y": b64(n.y.to_bytes(32, "big"))}


def thumbprint(key):
    """The account key's JWK thumbprint (RFC 7638), the half of every key
    authorization that is the account's."""
    j = json.dumps(_jwk(key), sort_keys=True, separators=(",", ":")).encode()
    return b64(hashlib.sha256(j).digest())


def dns01_value(keyauth):
    """The TXT record a dns-01 challenge wants, from the key authorization."""
    return b64(hashlib.sha256(keyauth.encode()).digest())


class Client:
    def __init__(self, directory, account_pem, contact="", opener=None):
        self.directory_url = directory
        self.key = _load_key(account_pem)
        self.contact = [contact] if contact and not isinstance(contact, list) else (contact or [])
        self.kid = ""
        self._dir = None
        self._nonce = ""
        self._open = opener or urllib.request.urlopen

    # ---- the wire ----------------------------------------------------------

    def _fetch(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                     headers={"User-Agent": AGENT, **(headers or {})})
        try:
            with self._open(req, timeout=TIMEOUT) as r:
                body = r.read()
                return r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
        except (urllib.error.URLError, OSError) as e:
            raise AcmeError(f"could not reach {url.split('/')[2]}: {e.reason if hasattr(e, 'reason') else e}") from None

    def directory(self):
        if self._dir is None:
            st, _, body = self._fetch(self.directory_url)
            if st != 200:
                raise AcmeError(f"the ACME directory answered {st}")
            self._dir = json.loads(body)
        return self._dir

    def _nonce_get(self):
        if self._nonce:
            n, self._nonce = self._nonce, ""
            return n
        _, h, _ = self._fetch(self.directory()["newNonce"], headers={"Accept": "*/*"})
        n = h.get("Replay-Nonce") or h.get("replay-nonce")
        if not n:
            raise AcmeError("the ACME server gave no nonce")
        return n

    def _sign(self, url, payload):
        protected = {"alg": "ES256", "nonce": self._nonce_get(), "url": url}
        if self.kid:
            protected["kid"] = self.kid
        else:
            protected["jwk"] = _jwk(self.key)
        p64 = b64(json.dumps(protected).encode())
        body64 = "" if payload is None else b64(json.dumps(payload).encode())
        der = self.key.sign(f"{p64}.{body64}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        sig = b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return json.dumps({"protected": p64, "payload": body64, "signature": sig}).encode()

    def post(self, url, payload=None, accept="application/json"):
        """A signed POST (None is POST-as-GET): (status, headers, body),
        the body parsed where it is JSON; a bad nonce is tried once more."""
        for attempt in (1, 2):
            st, h, body = self._fetch(url, self._sign(url, payload),
                                      {"Content-Type": "application/jose+json", "Accept": accept})
            self._nonce = h.get("Replay-Nonce") or h.get("replay-nonce") or ""
            ctype = (h.get("Content-Type") or h.get("content-type") or "")
            parsed = body
            if "json" in ctype:
                try:
                    parsed = json.loads(body or b"{}")
                except ValueError:
                    parsed = {}
            if st == 400 and isinstance(parsed, dict) and "badNonce" in str(parsed.get("type", "")) and attempt == 1:
                continue
            if st >= 400:
                detail = parsed.get("detail") if isinstance(parsed, dict) else ""
                raise AcmeError(f"the ACME server refused: {detail or st}")
            return st, h, parsed
        raise AcmeError("the ACME server kept refusing the nonce")

    # ---- the flow ----------------------------------------------------------

    def register(self):
        """The account for this key, made or found; its URL is the kid every
        later request is signed with."""
        if self.kid:
            return self.kid
        payload = {"termsOfServiceAgreed": True}
        if self.contact:
            payload["contact"] = self.contact
        _, h, _ = self.post(self.directory()["newAccount"], payload)
        self.kid = h.get("Location") or h.get("location") or ""
        if not self.kid:
            raise AcmeError("the ACME server made no account")
        return self.kid

    def _poll(self, url, want, what):
        """The object at `url` until its status is one of `want`, or invalid."""
        end = time.time() + POLL_FOR
        while True:
            _, _, obj = self.post(url, None)
            st = (obj or {}).get("status")
            if st in want:
                return obj
            if st in ("invalid", "revoked", "deactivated", "expired"):
                err = ((obj.get("error") or {}).get("detail")
                       or next(((c.get("error") or {}).get("detail") for c in obj.get("challenges", []) if c.get("error")), "")
                       or st)
                raise AcmeError(f"{what} is {st}: {err}")
            if time.time() > end:
                raise AcmeError(f"{what} did not become {' or '.join(want)} in time")
            time.sleep(POLL_S)

    def issue(self, names, kind, present, cleanup=None):
        """A certificate for `names`, the first its subject, by the `kind`
        of challenge (http-01 or dns-01): (chain PEM, key PEM)."""
        names = [str(n).strip().lower() for n in names if str(n).strip()]
        if not names:
            raise AcmeError("a certificate needs at least one name")
        if kind not in ("http-01", "dns-01"):
            raise AcmeError(f"not a challenge this client makes: {kind}")
        self.register()
        _, h, order = self.post(self.directory()["newOrder"],
                                {"identifiers": [{"type": "dns", "value": n} for n in names]})
        order_url = h.get("Location") or h.get("location") or ""
        done = []
        try:
            for auth_url in order.get("authorizations") or []:
                _, _, authz = self.post(auth_url, None)
                if authz.get("status") == "valid":
                    continue
                name = (authz.get("identifier") or {}).get("value", "")
                ch = next((c for c in authz.get("challenges") or [] if c.get("type") == kind), None)
                if not ch:
                    raise AcmeError(f"the ACME server offers no {kind} challenge for {name}")
                keyauth = f"{ch['token']}.{thumbprint(self.key)}"
                value = keyauth if kind == "http-01" else dns01_value(keyauth)
                present(kind, name, ch["token"], value)
                done.append((kind, name, ch["token"], value))
                self.post(ch["url"], {})
                self._poll(auth_url, ("valid",), f"the {kind} challenge for {name}")
            key = ec.generate_private_key(ec.SECP256R1())
            csr = (x509.CertificateSigningRequestBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
                   .sign(key, hashes.SHA256()))
            self.post(order["finalize"], {"csr": b64(csr.public_bytes(serialization.Encoding.DER))})
            order = self._poll(order_url, ("valid",), "the order")
            _, _, chain = self.post(order["certificate"], None, accept="application/pem-certificate-chain")
            chain = chain.decode() if isinstance(chain, bytes) else str(chain)
            if "-----BEGIN CERTIFICATE-----" not in chain:
                raise AcmeError("the ACME server sent no certificate")
            key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
            return chain, key_pem
        finally:
            for kind_, name, token, value in done:
                if cleanup:
                    try:
                        cleanup(kind_, name, token, value)
                    except Exception as e:                  # noqa: BLE001 (a cleanup must not hide the result)
                        print(f"dashboard: acme: the {kind_} challenge for {name} was not taken down: {e}", flush=True)


def expires(cert_pem):
    """When a PEM certificate (the chain's first) ends, as a unix time."""
    first = cert_pem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    c = x509.load_pem_x509_certificate(first.encode())
    return int(c.not_valid_after_utc.timestamp())
