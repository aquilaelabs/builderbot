"""Two-factor sign-in (R127): an authenticator app's codes, passkeys and
recovery codes, per account.

The store is two-factor.json in the state directory, 0600, keyed by the
account's uid: {uid: {"totp": {...}, "passkeys": [...], "recovery": [...],
"trusted": [...]}}. The authenticator's secret is sealed under the install's
install key where it has one (signing.seal, as a keystore is), and kept
as it is otherwise, as signing keeps its keys then; recovery codes are kept
as their SHA-256, each good once. An account with nothing here signs in with
its password alone, as before.

Passkeys are WebAuthn with "none" attestation and ES256 (P-256) keys, the
one algorithm every platform authenticator offers. The standard library has
no CBOR and no elliptic curves, so both are here: a CBOR reader for the
shapes WebAuthn sends, and an ECDSA verify over P-256. Verifying a signature
handles no secret, so the arithmetic need not be constant-time.

A wrong code is counted per account and per address (`slowed`): after five
in a quarter of an hour each try waits, after ten the account or the address
is held for a quarter of an hour. What a factor does is audited by the
server, which holds the door; this module answers questions about factors.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time

import qr
import statefile

STATE = None              # pathlib.Path, set by configure()
seal = None               # signing.seal, or None: an install without an install key
unseal = None
sealing = None            # () -> whether an install key is loaded now

_lock = threading.Lock()
ISSUER = "BuilderBot"
STEP = 30                 # seconds per authenticator code
RECOVERY_N = 10
TRUST_DAYS = 30
CHALLENGE_S = 300


def configure(**deps):
    globals().update(deps)


def _file():
    return STATE / "two-factor.json"


def load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _save(d):
    statefile.write_json(_file(), d, mode=0o600)


def record(uid):
    return load().get(str(uid)) or {}


def _update(uid, fn):
    with _lock:
        d = load()
        r = d.get(str(uid)) or {}
        out = fn(r)
        r = {k: v for k, v in r.items() if v}
        if r:
            d[str(uid)] = r
        else:
            d.pop(str(uid), None)
        _save(d)
        return out


def enabled(uid):
    """Whether this account signs in with a second factor."""
    r = record(uid)
    return bool((r.get("totp") or {}).get("on") or r.get("passkeys"))


def summary(uid):
    """What Profile shows: never a secret, never a code."""
    r = record(uid)
    t = r.get("totp") or {}
    return {"on": enabled(uid),
            "totp": {"on": bool(t.get("on")), "added": t.get("added", 0)},
            "passkeys": [{"id": p["id"], "name": p.get("name", ""), "added": p.get("added", 0),
                          "used": p.get("used", 0)} for p in r.get("passkeys") or []],
            "recovery_left": len(r.get("recovery") or []),
            "trusted": [{"id": t2["id"], "name": t2.get("name", ""), "added": t2.get("added", 0),
                         "until": t2.get("until", 0)} for t2 in r.get("trusted") or []
                        if t2.get("until", 0) > time.time()]}


def b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s):
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---- the authenticator app (RFC 6238) ------------------------------------

def _hotp(key, counter, digits=6):
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    n = struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF
    return str(n % 10 ** digits).zfill(digits)


def totp_now(key, at=None):
    return _hotp(key, int((time.time() if at is None else at) // STEP))


def _keep_secret(key):
    if seal and sealing and sealing():
        return {"sealed": b64u(seal(key))}
    return {"plain": base64.b32encode(key).decode()}


def _secret_of(t):
    if t.get("sealed"):
        return unseal(unb64u(t["sealed"]))
    return base64.b32decode(t.get("plain", ""))


def totp_begin(uid, name):
    """A new secret, not yet on: the QR's otpauth URI and the secret in
    words, for the first code to confirm."""
    key = secrets.token_bytes(20)
    words = base64.b32encode(key).decode().rstrip("=")

    def put(r):
        r["totp_pending"] = {**_keep_secret(key), "at": int(time.time())}
    _update(uid, put)
    label = f"{ISSUER}:{name}"
    uri = f"otpauth://totp/{_q(label)}?secret={words}&issuer={_q(ISSUER)}&algorithm=SHA1&digits=6&period={STEP}"
    return {"uri": uri, "qr": qr.svg(uri), "secret": " ".join(words[i:i + 4] for i in range(0, len(words), 4))}


def _q(s):
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def _code_ok(key, code, last):
    """The counter a code matches within one step either way, or None; one
    already used (`last`) never again."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    now = int(time.time() // STEP)
    for c in (now - 1, now, now + 1):
        if c > (last or -1) and hmac.compare_digest(_hotp(key, c), code):
            return c
    return None


def totp_confirm(uid, code):
    """Turn the pending secret on with its first code."""
    def put(r):
        p = r.get("totp_pending")
        if not p or time.time() - p.get("at", 0) > 900:
            return {"error": "start again: the authenticator's setup ran out"}
        c = _code_ok(_secret_of(p), code, None)
        if c is None:
            return {"error": "that code is not the one the app shows now"}
        r["totp"] = {**{k: p[k] for k in ("sealed", "plain") if k in p}, "on": True,
                     "added": int(time.time()), "last": c}
        r.pop("totp_pending", None)
        return {"ok": True}
    return _update(uid, put)


def totp_check(uid, code):
    def put(r):
        t = r.get("totp") or {}
        if not t.get("on"):
            return False
        c = _code_ok(_secret_of(t), code, t.get("last"))
        if c is None:
            return False
        t["last"] = c
        r["totp"] = t
        return True
    return _update(uid, put)


def totp_remove(uid):
    _update(uid, lambda r: (r.pop("totp", None), r.pop("totp_pending", None)))


# ---- recovery codes ------------------------------------------------------

def _rhash(code):
    norm = "".join(ch for ch in str(code or "").lower() if ch.isalnum())
    return hashlib.sha256(norm.encode()).hexdigest()


def recovery_make(uid):
    """Ten new codes, shown once; the old ones stop working."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = ["".join(secrets.choice(alphabet) for _ in range(5)) + "-"
             + "".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(RECOVERY_N)]
    _update(uid, lambda r: r.__setitem__("recovery", [_rhash(c) for c in codes]))
    return codes


def recovery_use(uid, code):
    h = _rhash(code)

    def put(r):
        left = r.get("recovery") or []
        hit = next((x for x in left if hmac.compare_digest(x, h)), None)
        if not hit:
            return False
        r["recovery"] = [x for x in left if x != hit]
        return True
    return _update(uid, put)


# ---- passkeys (WebAuthn, ES256) ------------------------------------------

_challenges = {}          # (uid, kind) -> (challenge bytes, expiry)


def challenge(uid, kind):
    c = secrets.token_bytes(32)
    with _lock:
        now = time.time()
        for k in [k for k, v in _challenges.items() if v[1] < now]:
            _challenges.pop(k, None)
        _challenges[(str(uid), kind)] = (c, now + CHALLENGE_S)
    return b64u(c)


def _take_challenge(uid, kind):
    with _lock:
        c = _challenges.pop((str(uid), kind), None)
    return c[0] if c and c[1] > time.time() else None


def cbor(data):
    """The one value `data` starts with, and where it ends: the CBOR
    WebAuthn sends (maps, arrays, byte and text strings, integers, simple
    values). Anything else is refused."""
    def item(i):
        ib = data[i]
        major, info = ib >> 5, ib & 0x1F
        i += 1
        if info < 24:
            n = info
        elif info in (24, 25, 26, 27):
            size = 1 << (info - 24)
            n = int.from_bytes(data[i:i + size], "big")
            i += size
        else:
            raise ValueError("indefinite or reserved CBOR")
        if major == 0:
            return n, i
        if major == 1:
            return -1 - n, i
        if major in (2, 3):
            b = data[i:i + n]
            if len(b) != n:
                raise ValueError("short CBOR string")
            return (bytes(b) if major == 2 else b.decode()), i + n
        if major == 4:
            out = []
            for _ in range(n):
                v, i = item(i)
                out.append(v)
            return out, i
        if major == 5:
            out = {}
            for _ in range(n):
                k, i = item(i)
                v, i = item(i)
                out[k] = v
            return out, i
        if major == 7 and info in (20, 21, 22):
            return {20: False, 21: True, 22: None}[info], i
        raise ValueError("unsupported CBOR")
    return item(0)


# P-256 (secp256r1)
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _on_curve(pt):
    x, y = pt
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        m = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        m = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (m * m - x1 - x2) % _P
    return x3, (m * (x1 - x3) - y1) % _P


def _mul(k, pt):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def _der_sig(sig):
    """(r, s) from an ASN.1 DER ECDSA signature."""
    if len(sig) < 8 or sig[0] != 0x30:
        raise ValueError("not a DER signature")
    i, out = 2, []
    for _ in range(2):
        if sig[i] != 0x02:
            raise ValueError("not a DER integer")
        n = sig[i + 1]
        out.append(int.from_bytes(sig[i + 2:i + 2 + n], "big"))
        i += 2 + n
    return out[0], out[1]


def ecdsa_p256_verify(x, y, msg, sig):
    """Whether `sig` (DER) is an ES256 signature over `msg` by (x, y)."""
    try:
        r, s = _der_sig(sig)
    except (ValueError, IndexError):
        return False
    q = (x, y)
    if not (1 <= r < _N and 1 <= s < _N) or not _on_curve(q):
        return False
    e = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    w = pow(s, -1, _N)
    pt = _add(_mul(e * w % _N, _G), _mul(r * w % _N, q))
    return pt is not None and pt[0] % _N == r


def _client(client_json, kind, chal, origin):
    try:
        c = json.loads(client_json)
    except ValueError:
        return "the browser's answer was not readable"
    if c.get("type") != kind:
        return "the browser answered another question"
    if not chal or not hmac.compare_digest(unb64u(c.get("challenge", "")), chal):
        return "that passkey answer is for another request: try again"
    if c.get("origin") != origin:
        return f"that passkey answer came from {c.get('origin')!r}, not this page"
    return ""


def _rp_hash(origin):
    import urllib.parse
    return hashlib.sha256((urllib.parse.urlsplit(origin).hostname or "").encode()).digest()


def passkey_add(uid, origin, name, client_b64, att_b64):
    """Register a passkey from navigator.credentials.create's answer."""
    chal = _take_challenge(uid, "create")
    try:
        client = unb64u(client_b64)
        why = _client(client, "webauthn.create", chal, origin)
        if why:
            return {"error": why}
        att, _ = cbor(unb64u(att_b64))
        auth = att["authData"]
        if auth[:32] != _rp_hash(origin):
            return {"error": "that passkey was made for another site"}
        flags = auth[32]
        if not flags & 0x01 or not flags & 0x40:
            return {"error": "the authenticator did not say the person was present"}
        cred_len = int.from_bytes(auth[53:55], "big")
        cred_id = auth[55:55 + cred_len]
        key, _ = cbor(auth[55 + cred_len:])
        if key.get(1) != 2 or key.get(3) != -7 or key.get(-1) != 1:
            return {"error": "BuilderBot takes a P-256 passkey (ES256), and this authenticator offered another"}
        x, y = int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big")
        if not _on_curve((x, y)):
            return {"error": "that passkey's key is not a point on its curve"}
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return {"error": f"the passkey could not be read: {e}"}
    pid = b64u(cred_id)
    nm = str(name or "").strip()[:60] or "a passkey"

    def put(r):
        keys = [p for p in r.get("passkeys") or [] if p["id"] != pid]
        keys.append({"id": pid, "x": format(x, "x"), "y": format(y, "x"), "name": nm, "rp": b64u(auth[:32]),
                     "count": int.from_bytes(auth[33:37], "big"), "added": int(time.time()), "used": 0})
        r["passkeys"] = keys[-20:]
        return {"ok": True, "id": pid, "name": nm}
    return _update(uid, put)


def passkey_ids(uid):
    return [p["id"] for p in record(uid).get("passkeys") or []]


def passkey_check(uid, origin, pid, client_b64, auth_b64, sig_b64):
    """Whether a navigator.credentials.get answer proves one of this
    account's passkeys."""
    chal = _take_challenge(uid, "get")
    try:
        client, auth, sig = unb64u(client_b64), unb64u(auth_b64), unb64u(sig_b64)
    except (ValueError, TypeError):
        return False
    if _client(client, "webauthn.get", chal, origin) or len(auth) < 37:
        return False
    if auth[:32] != _rp_hash(origin) or not auth[32] & 0x01:
        return False

    def put(r):
        for p in r.get("passkeys") or []:
            if p["id"] != pid:
                continue
            # The site it was made for, and only that one.
            if p.get("rp") and p["rp"] != b64u(auth[:32]):
                return False
            if not ecdsa_p256_verify(int(p["x"], 16), int(p["y"], 16),
                                     auth + hashlib.sha256(client).digest(), sig):
                return False
            count = int.from_bytes(auth[33:37], "big")
            # A counter that went backwards is a copied authenticator; one
            # that stays at zero is a platform that does not count.
            if count and count <= p.get("count", 0):
                return False
            p["count"], p["used"] = count, int(time.time())
            return True
        return False
    return _update(uid, put)


def passkey_remove(uid, pid):
    _update(uid, lambda r: r.__setitem__("passkeys", [p for p in r.get("passkeys") or [] if p["id"] != pid]))


# ---- a browser remembered for 30 days ------------------------------------

def trust_add(uid, name):
    tid = secrets.token_hex(8)
    until = int(time.time()) + TRUST_DAYS * 86400

    def put(r):
        keep = [t for t in r.get("trusted") or [] if t.get("until", 0) > time.time()]
        keep.append({"id": tid, "name": str(name or "")[:80], "added": int(time.time()), "until": until})
        r["trusted"] = keep[-20:]
    _update(uid, put)
    return tid, until


def trusted(uid, tid):
    return any(t["id"] == tid and t.get("until", 0) > time.time() for t in record(uid).get("trusted") or [])


def trust_remove(uid, tid=""):
    _update(uid, lambda r: r.__setitem__("trusted", [t for t in r.get("trusted") or [] if tid and t["id"] != tid]))


def remove_all(uid):
    """Every factor gone: `bb users reset-2fa` on the controller's console."""
    _update(uid, lambda r: r.clear())


# ---- wrong codes, counted ------------------------------------------------

_misses = {}              # key -> [times]
WINDOW = 900
SLOW_AFTER = 5
HOLD_AFTER = 10


def held(*keys):
    """Seconds left on a hold for any of these keys (an account, an
    address), or 0."""
    now = time.time()
    worst = 0
    with _lock:
        for k in keys:
            ts = [t for t in _misses.get(k, []) if now - t < WINDOW]
            _misses[k] = ts
            if len(ts) >= HOLD_AFTER:
                worst = max(worst, int(WINDOW - (now - ts[-HOLD_AFTER])))
    return worst


def missed(*keys):
    """Count a wrong code against each key; the seconds to wait before
    answering, once there have been enough to slow."""
    now = time.time()
    n = 0
    with _lock:
        for k in keys:
            ts = [t for t in _misses.get(k, []) if now - t < WINDOW] + [now]
            _misses[k] = ts[-50:]
            n = max(n, len(ts))
    return min(5, n - SLOW_AFTER + 1) if n >= SLOW_AFTER else 0


def cleared(*keys):
    with _lock:
        for k in keys:
            _misses.pop(k, None)


def misses_of(key):
    now = time.time()
    with _lock:
        return len([t for t in _misses.get(key, []) if now - t < WINDOW])

