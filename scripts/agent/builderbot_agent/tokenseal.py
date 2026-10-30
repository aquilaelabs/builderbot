"""The coding agents' sign-ins sealed on a node (R126): one implementation
the node's agent and the controller both load (the controller by path, as
termws.py loads term.py).

The node seals and never holds what opens a seal. Each account has a key
pair per node made on the controller from the account's key (R154) and never
kept: the secret is HMAC(key, "bb agent token v2" | node | account) as an
X25519 private key, the public its X25519 public, which the node is handed
as 64 hex characters. The node seals with the public alone: a fresh X25519
key r, its public R, the seal's key K = HKDF-SHA256(r·A, info = R | A), and
ChaCha20-Poly1305 under K with the seal's header as its associated data
(R158 step 3: a vetted library, `cryptography`, in the image and on the
nodes). Only the controller can make K again, from R and the secret, and it
hands K to the node only inside a terminal a signed-in person opened for
that account (the signed /term open of R133), wrapped to the agent's own
X25519 key for this boot so that neither a copy of /config nor a copy of the
node's disk, with the traffic captured, opens it.

The format before (BBTOK1: Diffie-Hellman in RFC 3526's 2048-bit group, a
HMAC-SHA256 counter-mode stream and a HMAC tag, built from the standard
library alone) is still opened here for one release, so a seal a node made
under 0.8.x opens in the terminal its person next opens there and is sealed
again the new way. A key is told apart by its width: 64 hex characters is
X25519, 512 the old group. A node without the library (a 0.8.x node not yet
provisioned with it) seals the old way, which the controller still opens.

A seal: MAGIC, one line of JSON (the agent, the account, R, and what the
login said of itself: email, plan), the nonce, the ciphertext with its tag.
Nothing in this file reads or writes a token file; it seals and opens bytes.
"""
import hashlib
import hmac
import json
import os

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    HAVE = True
except ImportError:                                         # a node provisioned before the library
    HAVE = False

MAGIC = b"BBTOK2\n"
WRAP = b"BBWRAP2\n"
MAGIC1 = b"BBTOK1\n"
WRAP1 = b"BBWRAP1\n"

# RFC 3526 group 14: the 2048-bit MODP group, g = 2, a safe prime (the
# format before; kept to open what 0.8.x nodes sealed).
P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
G = 2
Q = (P - 1) // 2
WIDTH = 256                      # bytes of a group element


class Refused(Exception):
    """A seal or a wrap this side cannot open: not one, damaged, or made for
    another key."""


def _b(n):
    return int(n).to_bytes(WIDTH, "big")


def is_v2(x):
    """Whether a public key, an R or a C is the new kind: 64 hex characters."""
    return isinstance(x, str) and len(x) == 64


def element(x):
    """A group element from hex or an int, held to the group: 1 < x < p-1
    and of order q, so a value chosen to leak the secret is refused (the
    format before)."""
    try:
        n = int(x, 16) if isinstance(x, str) else int(x)
    except (TypeError, ValueError):
        raise Refused("not a group element") from None
    if not 1 < n < P - 1 or pow(n, Q, P) != 1:
        raise Refused("not an element of the group")
    return n


def _pub2(x):
    """An X25519 public key from 64 hex characters, or Refused."""
    try:
        raw = bytes.fromhex(x) if isinstance(x, str) else bytes(x)
        if len(raw) != 32:
            raise ValueError
        return X25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError):
        raise Refused("not a public key") from None


def _need():
    if not HAVE:
        raise Refused("this node has no cryptography library: a seal of the new kind cannot be made or opened here")


# ---- the account's key pair on this node -----------------------------------

def secret(key, node, account):
    """The account's secret on this node, derived from its key and never
    kept: 32 bytes, an X25519 private key."""
    return hmac.new(bytes(key), b"bb agent token v2|" + str(node).encode() + b"|" + str(account).encode(),
                    hashlib.sha256).digest()


def secret1(key, node, account):
    """The format before's secret exponent, for the seals 0.8.x nodes made."""
    raw = hmac.new(bytes(key), b"bb agent token v1|" + str(node).encode() + b"|" + str(account).encode(),
                   hashlib.sha256).digest()
    return int.from_bytes(raw, "big") % (Q - 1) + 1


def public(a):
    """The public half, as hex: X25519's for a 32-byte secret, g^a for the
    format before's exponent."""
    if isinstance(a, bytes):
        _need()
        return X25519PrivateKey.from_private_bytes(a).public_key().public_bytes_raw().hex()
    return format(pow(G, a, P), "x")


def _kdf(shared, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"bb agent token v2|" + info).derive(shared)


def _subkeys(k):
    return (hmac.new(k, b"encrypt", hashlib.sha256).digest(),
            hmac.new(k, b"authenticate", hashlib.sha256).digest())


def _stream(key, nonce, n):
    out, i = bytearray(), 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def _close(k, magic, head, data):
    """`data` under K: ChaCha20-Poly1305 with the header as associated
    data for the new magics, the format before's stream and tag for the old."""
    if magic in (MAGIC, WRAP):
        _need()
        nonce = os.urandom(12)
        return magic + head + b"\n" + nonce + ChaCha20Poly1305(k).encrypt(nonce, data, magic + head)
    enc, mac = _subkeys(k)
    nonce = os.urandom(16)
    ct = _xor(data, _stream(enc, nonce, len(data)))
    body = magic + head + b"\n" + nonce + ct
    return body + hmac.new(mac, body, hashlib.sha256).digest()


def _open(k, blob):
    """The data a seal or a wrap holds under K, whichever kind it is."""
    magic = next((m for m in (MAGIC, WRAP, MAGIC1, WRAP1) if blob.startswith(m)), None)
    if magic is None:
        raise Refused("not a seal")
    nl = blob.find(b"\n", len(magic))
    if nl < 0:
        raise Refused("not a seal")
    head = blob[len(magic):nl]
    if magic in (MAGIC, WRAP):
        _need()
        nonce, ct = blob[nl + 1:nl + 13], blob[nl + 13:]
        try:
            return ChaCha20Poly1305(k).decrypt(nonce, ct, magic + head)
        except Exception:                                   # noqa: BLE001 (InvalidTag, or a short blob)
            raise Refused("made for another key, or damaged") from None
    if len(blob) < nl + 1 + 16 + 32:
        raise Refused("not a seal")
    enc, mac = _subkeys(k)
    body, tag = blob[:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(mac, body, hashlib.sha256).digest()):
        raise Refused("made for another key, or damaged")
    nonce, ct = body[nl + 1:nl + 17], body[nl + 17:]
    return _xor(ct, _stream(enc, nonce, len(ct)))


def header(blob):
    """What a seal says of itself, readable without opening it: the agent,
    the account, R, and what its login said (email, plan)."""
    magic = MAGIC if blob.startswith(MAGIC) else MAGIC1 if blob.startswith(MAGIC1) else None
    if magic is None:
        raise Refused("not a seal")
    try:
        return json.loads(blob[len(magic):blob.index(b"\n", len(magic))])
    except ValueError:
        raise Refused("not a seal") from None


def seal(pub, data, about=None):
    """`data` (bytes) sealed for the holder of pub's secret: the node's side,
    which needs nothing secret. `about`: what may be read without opening
    it (the agent, the account, the login's email). An X25519 public (64
    hex) seals the new way; the format before's public, or no library here,
    the old way."""
    if is_v2(pub) and HAVE:
        A = _pub2(pub)
        r = X25519PrivateKey.generate()
        R = r.public_key().public_bytes_raw()
        k = _kdf(r.exchange(A), R + A.public_bytes_raw())
        head = json.dumps(dict(about or {}, R=R.hex()), sort_keys=True).encode()
        return _close(k, MAGIC, head, data)
    if is_v2(pub):
        raise Refused("this node has no cryptography library: it seals the old way with the old public key")
    A = element(pub)
    r = int.from_bytes(os.urandom(32), "big") % (Q - 1) + 1
    R = pow(G, r, P)
    k = hashlib.sha256(_b(pow(A, r, P)) + _b(R) + _b(A)).digest()
    head = json.dumps(dict(about or {}, R=format(R, "x")), sort_keys=True).encode()
    return _close(k, MAGIC1, head, data)


def key_for(a, R):
    """The key that opens a seal whose R is R, for the secret a: the
    controller's side, which alone can make it. A 32-byte secret and a
    64-hex R are the new kind; an exponent and a group element the old."""
    if is_v2(R):
        _need()
        if not isinstance(a, bytes):
            raise Refused("a seal of the new kind, and the secret of the old")
        Rk = _pub2(R)
        me = X25519PrivateKey.from_private_bytes(a)
        return _kdf(me.exchange(Rk), Rk.public_bytes_raw() + me.public_key().public_bytes_raw())
    if isinstance(a, bytes):
        raise Refused("a seal of the old kind, and the secret of the new")
    Rn = element(R)
    return hashlib.sha256(_b(pow(Rn, a, P)) + _b(Rn) + _b(pow(G, a, P))).digest()


def rid(R):
    """A seal's short name in a wrap: its R is as wide as a key, and a
    terminal's signed open has to fit in a request line."""
    return hashlib.sha256(str(R).encode()).hexdigest()[:24]


def open_with(k, blob):
    """The data a seal holds, opened with the key key_for made for it."""
    return _open(k, blob)


# ---- the agent's own key for this boot: what a seal's key travels under ----

def boot_secret():
    """A fresh secret for this run of the agent, kept in its memory alone:
    32 bytes for X25519 where the library is here, the exponent before
    where it is not."""
    if HAVE:
        return os.urandom(32)
    return int.from_bytes(os.urandom(32), "big") % (Q - 1) + 1


def wrap(agent_pub, keys):
    """`keys` ({name: key bytes}, each seal named by rid) wrapped for the agent whose boot public is
    agent_pub: (C, blob), C the wrap's own public half, of the agent's kind."""
    data = json.dumps({R: k.hex() for R, k in keys.items()}, sort_keys=True).encode()
    if is_v2(agent_pub):
        _need()
        E = _pub2(agent_pub)
        c = X25519PrivateKey.generate()
        C = c.public_key().public_bytes_raw()
        w = _kdf(c.exchange(E), C + E.public_bytes_raw())
        return C.hex(), _close(w, WRAP, b"{}", data)
    E = element(agent_pub)
    c = int.from_bytes(os.urandom(32), "big") % (Q - 1) + 1
    C = pow(G, c, P)
    w = hashlib.sha256(_b(pow(E, c, P)) + _b(C) + _b(E)).digest()
    return format(C, "x"), _close(w, WRAP1, b"{}", data)


def unwrap(e, C, blob):
    """The {name: key bytes} a wrap holds, opened with the agent's boot secret."""
    if is_v2(C):
        _need()
        if not isinstance(e, bytes):
            raise Refused("a wrap of the new kind for a boot key of the old")
        Ck = _pub2(C)
        me = X25519PrivateKey.from_private_bytes(e)
        w = _kdf(me.exchange(Ck), Ck.public_bytes_raw() + me.public_key().public_bytes_raw())
    else:
        if isinstance(e, bytes):
            raise Refused("a wrap of the old kind for a boot key of the new")
        Cn = element(C)
        w = hashlib.sha256(_b(pow(Cn, e, P)) + _b(Cn) + _b(pow(G, e, P))).digest()
    try:
        return {R: bytes.fromhex(k) for R, k in json.loads(_open(w, blob)).items()}
    except ValueError:
        raise Refused("not a wrap") from None
