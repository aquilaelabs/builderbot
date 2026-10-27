"""The coding agents' sign-ins sealed on a node (R126): one implementation
the node's agent and the controller both load (the controller by path, as
termws.py loads term.py).

The node seals and never holds what opens a seal. Each account has a key
pair per node made on the controller from the install key (R135) and never
kept: the secret a = HMAC(install key, "bb agent token v1" | node | account),
the public A = g^a in RFC 3526's 2048-bit group, which the node is handed.
The node seals with A alone: a fresh r, R = g^r, the seal's key K =
SHA256(A^r | R | A). Only the controller can make K again, from R and a,
and it hands K to the node only inside a terminal a signed-in person opened
for that account (the signed /term open of R133), wrapped to the agent's
own key for this boot so that neither a copy of /config nor a copy of the
node's disk, with the traffic captured, opens it.

The cipher is the one signing.py builds from what the standard library has:
HMAC-SHA256 as a pseudorandom function in counter mode for the keystream (a
fresh 16-byte nonce per seal) and a second HMAC over the whole for the tag,
checked before anything is opened.

A seal: MAGIC, one line of JSON (the agent, the account, R, and what the
login said of itself: email, plan), the nonce, the ciphertext, the tag.
Nothing in this file reads or writes a token file; it seals and opens bytes.
"""
import hashlib
import hmac
import json
import os

MAGIC = b"BBTOK1\n"
WRAP = b"BBWRAP1\n"
# RFC 3526 group 14: the 2048-bit MODP group, g = 2, a safe prime.
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


def element(x):
    """A group element from hex or an int, held to the group: 1 < x < p-1
    and of order q, so a value chosen to leak the secret is refused."""
    try:
        n = int(x, 16) if isinstance(x, str) else int(x)
    except (TypeError, ValueError):
        raise Refused("not a group element") from None
    if not 1 < n < P - 1 or pow(n, Q, P) != 1:
        raise Refused("not an element of the group")
    return n


def secret(install_key, node, account):
    """The account's secret exponent on this node: derived, never kept."""
    raw = hmac.new(bytes(install_key), b"bb agent token v1|" + str(node).encode() + b"|" + str(account).encode(),
                   hashlib.sha256).digest()
    return int.from_bytes(raw, "big") % (Q - 1) + 1


def public(a):
    """g^a, as hex."""
    return format(pow(G, a, P), "x")


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
    return bytes(x ^ y for x, y in zip(a, b))


def _close(k, magic, head, data):
    enc, mac = _subkeys(k)
    nonce = os.urandom(16)
    ct = _xor(data, _stream(enc, nonce, len(data)))
    body = magic + head + b"\n" + nonce + ct
    return body + hmac.new(mac, body, hashlib.sha256).digest()


def _open(k, magic, blob):
    if not blob.startswith(magic) or len(blob) < len(magic) + 1 + 16 + 32:
        raise Refused("not a seal")
    enc, mac = _subkeys(k)
    body, tag = blob[:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(mac, body, hashlib.sha256).digest()):
        raise Refused("made for another key, or damaged")
    nl = body.index(b"\n", len(magic))
    nonce, ct = body[nl + 1:nl + 17], body[nl + 17:]
    return _xor(ct, _stream(enc, nonce, len(ct)))


def header(blob):
    """What a seal says of itself, readable without opening it: the agent,
    the account, R, and what its login said (email, plan)."""
    if not blob.startswith(MAGIC):
        raise Refused("not a seal")
    try:
        return json.loads(blob[len(MAGIC):blob.index(b"\n", len(MAGIC))])
    except ValueError:
        raise Refused("not a seal") from None


def seal(pub, data, about=None):
    """`data` (bytes) sealed for the holder of pub's secret: the node's side,
    which needs nothing secret. `about`: what may be read without opening
    it (the agent, the account, the login's email)."""
    A = element(pub)
    r = int.from_bytes(os.urandom(32), "big") % (Q - 1) + 1
    R = pow(G, r, P)
    k = hashlib.sha256(_b(pow(A, r, P)) + _b(R) + _b(A)).digest()
    head = json.dumps(dict(about or {}, R=format(R, "x")), sort_keys=True).encode()
    return _close(k, MAGIC, head, data)


def key_for(a, R):
    """The key that opens a seal whose R is R, for the secret a: the
    controller's side, which alone can make it."""
    Rn = element(R)
    return hashlib.sha256(_b(pow(Rn, a, P)) + _b(Rn) + _b(pow(G, a, P))).digest()


def rid(R):
    """A seal's short name in a wrap: its R is a group element as wide as
    the group, and a terminal's signed open has to fit in a request line."""
    return hashlib.sha256(str(R).encode()).hexdigest()[:24]


def open_with(k, blob):
    """The data a seal holds, opened with the key key_for made for it."""
    return _open(k, MAGIC, blob)


# ---- the agent's own key for this boot: what a seal's key travels under ----

def boot_secret():
    """A fresh secret for this run of the agent, kept in its memory alone."""
    return int.from_bytes(os.urandom(32), "big") % (Q - 1) + 1


def wrap(agent_pub, keys):
    """`keys` ({name: key bytes}, each seal named by rid) wrapped for the agent whose boot public is
    agent_pub: (C, blob), C the wrap's own public half."""
    E = element(agent_pub)
    c = boot_secret()
    C = pow(G, c, P)
    w = hashlib.sha256(_b(pow(E, c, P)) + _b(C) + _b(E)).digest()
    data = json.dumps({R: k.hex() for R, k in keys.items()}, sort_keys=True).encode()
    return format(C, "x"), _close(w, WRAP, b"{}", data)


def unwrap(e, C, blob):
    """The {name: key bytes} a wrap holds, opened with the agent's boot secret."""
    Cn = element(C)
    w = hashlib.sha256(_b(pow(Cn, e, P)) + _b(Cn) + _b(pow(G, e, P))).digest()
    try:
        return {R: bytes.fromhex(k) for R, k in json.loads(_open(w, WRAP, blob)).items()}
    except ValueError:
        raise Refused("not a wrap") from None
