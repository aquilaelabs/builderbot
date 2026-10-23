"""State 5 to 6: two-factor sign-in (R127).

  * two-factor.json is new: each account's authenticator secret (sealed
    under the install's signing secret where it has one), its passkeys'
    public keys and its recovery codes as hashes. It starts empty, 0600,
    and an account with nothing in it signs in with its password as before.
  * the number is what moves: a build before this one would sign in an
    account that has a second factor with its password alone, so it refuses
    to start on this /config instead.

Idempotent: a file already there is left as it is.
Never edited once shipped (stateversion.py).
"""
import os
from pathlib import Path


def run(ctx):
    f = Path(ctx["state"]) / "two-factor.json"
    if f.exists():
        return
    fd = os.open(str(f), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("{}\n")
