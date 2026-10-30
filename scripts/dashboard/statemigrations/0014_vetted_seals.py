"""State 13 to 14: every seal on the vetted cryptography (R158 step 3; the
operator, 27 Oct).

  * nothing is rewritten here: what the controller keeps sealed (the
    accounts' keys and key stores, the signing keys and their passwords,
    the settings' secrets, two-factor secrets, a project's git line from
    before 0.8.0) is sealed again as ChaCha20-Poly1305 under a key HKDF
    derives from the install key or the account's, by the seal_all passes
    the dashboard runs at its start, which read the format before (BBSEAL1,
    a HMAC-SHA256 stream and tag) for this release and write only the new;
    the nodes' sealed sign-ins move the same way, each the next time its
    person opens a terminal there, to X25519 and ChaCha20-Poly1305 from the
    same library (python3-cryptography, in the image and on every node);
  * the number moves because a seal of the new format (BBSEAL2) is bytes
    an older build cannot open, so an older build refuses to start on this
    /config rather than reading every secret as locked.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
