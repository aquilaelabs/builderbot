"""The dashboard served over TLS where it can be had, http where it cannot
(R158 step 2; the operator, 27 Oct).

One port, both ways: the listening socket peeks at a connection's first
byte and wraps the ones that open a TLS handshake (0x16) in the certificate
loaded here, and serves the rest as plain http, so a node whose agent dials
http://controller:7680 keeps dialing while a browser at https://... is
answered over TLS, and nothing of it is in the setup steps or the five
places a setting lands. The mode is a setting (Controller settings,
Connection): `http`, `self` (the install's own certificate, made here and
remade a month before it ends) or `acme` (a Let's Encrypt certificate for
a hostname of the controller's own, by a DNS-01 record through the
Cloudflare API token, since port 80 is not the dashboard's), with `""`
reading as `self` where a hostname is set and `http` otherwise. The
certificate is kept plain under /config/tls, its private key sealed under
the install key (listed on Controller, Keys) and opened into a 0600 file
under /run only while it is loaded. The agent channel and the terminal
relay keep their own signatures either way.
"""
import base64
import contextlib
import datetime
import hashlib
import json
import os
import socket
import ssl
import threading
import time
from pathlib import Path

STATE = None
seal = None
unseal = None
sealing = None
RUN_DIR = os.environ.get("BB_RUN_DIR") or "/run"
SELF_DAYS = 825                # Apple's limit for a certificate a browser will take
RENEW_BEFORE = 30 * 86400
SEALED = "bbseal:"
_lock = threading.Lock()
_ctx = None                    # the ssl.SSLContext in force, None while http
_loaded = ""                   # the fingerprint _ctx was loaded from
_pending = {}                  # an ACME request going: {state, error, at}


def configure(*, state, seal_fn=None, unseal_fn=None, sealing_fn=None):
    globals().update(STATE=Path(state), seal=seal_fn, unseal=unseal_fn, sealing=sealing_fn)


def _dir():
    d = STATE / "tls"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _meta():
    try:
        d = json.loads((_dir() / "meta.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _meta_save(d):
    tmp = _dir() / "meta.json.tmp"
    tmp.write_text(json.dumps(d))
    os.replace(tmp, _dir() / "meta.json")


def _key_text():
    """The private key, plain: opened where it was sealed."""
    try:
        raw = (_dir() / "key.pem").read_text().strip()
    except OSError:
        return ""
    if raw.startswith(SEALED):
        try:
            return unseal(base64.b64decode(raw[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked: another key)
            return ""
    return raw


def _keep(cert_pem, key_pem, kind, names):
    """The pair kept: the certificate plain, the key sealed where there is
    an install key."""
    d = _dir()
    (d / "cert.pem").write_text(cert_pem.strip() + "\n")
    text = (SEALED + base64.b64encode(seal(key_pem.encode())).decode()) if (seal and sealing and sealing()) else key_pem
    fd = os.open(d / "key.pem", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text + "\n")
    m = _meta()
    m.update({"kind": kind, "names": list(names), "made": int(time.time())})
    _meta_save(m)


def _cert_text():
    try:
        return (_dir() / "cert.pem").read_text()
    except OSError:
        return ""


def fingerprint(cert_pem=""):
    """The certificate's SHA-256 fingerprint, as the phone and the
    companion pin it (colon-separated hex), or ""."""
    pem = cert_pem or _cert_text()
    if "-----BEGIN CERTIFICATE-----" not in pem:
        return ""
    from cryptography import x509                           # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes      # noqa: PLC0415
    first = pem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    digest = x509.load_pem_x509_certificate(first.encode()).fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)


def _cert_facts(pem):
    from cryptography import x509                           # noqa: PLC0415
    first = pem.split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    c = x509.load_pem_x509_certificate(first.encode())
    try:
        alt = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = list(alt.get_values_for_type(x509.DNSName)) + [str(a) for a in alt.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        names = []
    return {"expires": int(c.not_valid_after_utc.timestamp()), "names": names,
            "issuer": ", ".join(a.value for a in c.issuer), "self": c.issuer == c.subject}


def self_signed(names):
    """A self-signed pair for these names and the addresses among them,
    SELF_DAYS long: (cert PEM, key PEM)."""
    import ipaddress                                        # noqa: PLC0415
    from cryptography import x509                           # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    from cryptography.x509.oid import NameOID               # noqa: PLC0415
    names = [n.strip().lower() for n in names if n and n.strip()] or ["builderbot"]
    key = ec.generate_private_key(ec.SECP256R1())
    alts = []
    for n in names:
        try:
            alts.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            alts.append(x509.DNSName(n))
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0][:64]),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BuilderBot")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=SELF_DAYS))
            .add_extension(x509.SubjectAlternativeName(alts), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode())


def mode_of(settings_get):
    """The mode in force from the settings: `""` reads as self where a
    hostname is set and http otherwise."""
    m = str(settings_get("tls_mode") or "").strip().lower()
    if m in ("http", "self", "acme"):
        return m
    return "self" if str(settings_get("tls_host") or "").strip() else "http"


def status(settings_get):
    """What the Connection section and the Doctor show: the mode, whether
    TLS is on now, the certificate's kind, names, fingerprint and expiry,
    and an ACME request going."""
    mode = mode_of(settings_get)
    pem = _cert_text()
    facts = {}
    if pem:
        with contextlib.suppress(Exception):                # noqa: BLE001 (a damaged file: no facts)
            facts = _cert_facts(pem)
    return {"mode": mode, "on": _ctx is not None, "host": str(settings_get("tls_host") or "").strip(),
            "fingerprint": fingerprint(pem) if pem else "", "expires": facts.get("expires", 0),
            "names": facts.get("names", []), "issuer": facts.get("issuer", ""), "kind": _meta().get("kind", ""),
            "pending": dict(_pending), "key_sealed": _key_sealed()}


def _key_sealed():
    try:
        return (_dir() / "key.pem").read_text().startswith(SEALED)
    except OSError:
        return False


def certificate_pem():
    """The certificate alone, for Download: what a phone or the companion pins."""
    return _cert_text()


def _load_context():
    """An SSLContext from the pair kept, the key opened into RUN_DIR only
    for the load; None when there is no pair or it will not load."""
    global _loaded
    pem, key = _cert_text(), _key_text()
    if not pem or not key:
        return None
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    kf = Path(RUN_DIR) / f"builderbot-tls-{os.getpid()}.pem"
    try:
        fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key)
        ctx.load_cert_chain(str(_dir() / "cert.pem"), str(kf))
    except (OSError, ssl.SSLError) as e:
        print(f"dashboard: tls: the certificate did not load: {e}", flush=True)
        return None
    finally:
        with contextlib.suppress(OSError):
            kf.unlink()
    _loaded = fingerprint(pem)
    return ctx


def apply(settings_get, names=()):
    """The mode as the settings say, made so: a self-signed pair made or
    remade for `names` (the hostname and the addresses the page is reached
    at) where there is none or it is another kind's or near its end, the
    context loaded, or TLS turned off. Returns status()."""
    global _ctx
    mode = mode_of(settings_get)
    with _lock:
        if mode == "http":
            _ctx = None
            return status(settings_get)
        host = str(settings_get("tls_host") or "").strip()
        want = [n for n in [host, *names] if n]
        if mode == "self":
            pem = _cert_text()
            facts = {}
            if pem:
                with contextlib.suppress(Exception):        # noqa: BLE001
                    facts = _cert_facts(pem)
            m = _meta()
            if (not pem or m.get("kind") != "self" or not facts.get("self")
                    or facts.get("expires", 0) - time.time() < RENEW_BEFORE
                    or (want and set(want) - set(facts.get("names", [])))):
                cert, key = self_signed(want or ["builderbot"])
                _keep(cert, key, "self", want or ["builderbot"])
        elif mode == "acme" and _meta().get("kind") != "acme":
            # Until the ACME pair comes (issue_acme), the install's own
            # answers, so the page is on https from the switch.
            if not _cert_text():
                cert, key = self_signed(want or ["builderbot"])
                _keep(cert, key, "self", want or ["builderbot"])
        _ctx = _load_context()
    return status(settings_get)


def issue_acme(settings_get, directory, account_pem, present, cleanup, on_done=None):
    """A Let's Encrypt pair for the hostname, by DNS-01 (present and cleanup
    are nginxproxy's Cloudflare hooks), in the background; loaded when it
    comes, said in status().pending meanwhile."""
    host = str(settings_get("tls_host") or "").strip().lower()
    email = str(settings_get("tls_email") or "").strip()
    if not host:
        return {"error": "an ACME certificate is for a hostname: set the Connection section's hostname first"}
    if _pending.get("state") not in (None, "failed", "done"):
        return {"error": f"a certificate for {host} is being asked for already"}
    _pending.update({"state": "asking", "error": "", "at": int(time.time()), "host": host})

    def go():
        global _ctx
        import acme                                         # noqa: PLC0415
        try:
            client = acme.Client(directory, account_pem, contact=f"mailto:{email}" if email else "")
            _pending.update({"state": "ordering"})
            chain, key = client.issue([host], "dns-01", present, cleanup)
            with _lock:
                _keep(chain, key, "acme", [host])
                _ctx = _load_context()
            _pending.update({"state": "done", "error": ""})
        except Exception as e:                              # noqa: BLE001 (said, never silent)
            _pending.update({"state": "failed", "error": str(e)[:300]})
            print(f"dashboard: tls: acme for {host}: {e}", flush=True)
        if on_done:
            with contextlib.suppress(Exception):            # noqa: BLE001
                on_done(_pending.get("state") == "done", _pending.get("error", ""))
    threading.Thread(target=go, name="tls-acme", daemon=True).start()
    return {"ok": True, "started": True, "host": host}


def renew_due():
    """Whether the pair in force ends within RENEW_BEFORE."""
    pem = _cert_text()
    if not pem:
        return False
    try:
        return _cert_facts(pem)["expires"] - time.time() < RENEW_BEFORE
    except Exception:                                       # noqa: BLE001
        return False


def wrap(sock, peek_timeout=5.0):
    """A just-accepted socket, wrapped in TLS when its first byte opens a
    handshake and a context is loaded, else as it came. A connection that
    sends nothing within peek_timeout is served plain, which a client that
    waits for a banner would have been anyway."""
    ctx = _ctx
    if ctx is None:
        return sock
    was = sock.gettimeout()
    try:
        sock.settimeout(peek_timeout)
        try:
            head = sock.recv(1, socket.MSG_PEEK)
        except (TimeoutError, OSError):
            head = b""
    finally:
        sock.settimeout(was)
    if head != b"\x16":
        return sock
    try:
        return ctx.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
    except (ssl.SSLError, OSError):
        return sock


def over_tls(connection):
    return isinstance(connection, ssl.SSLSocket)


def key_digest():
    """A short digest of the sealed key file, for the Keys page's row."""
    try:
        return hashlib.sha256((_dir() / "key.pem").read_bytes()).hexdigest()[:12]
    except OSError:
        return ""
