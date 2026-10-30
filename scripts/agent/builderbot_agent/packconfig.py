"""What each added pack is configured with on this node (R172): the hello
hands the rows (pack, the store root, values, env), and the agent writes
each pack's env into STORE/.bb/config/PACK.env, owned by the session
account and readable by it alone, which bb tool reads into a verb's
environment before it runs; a pack no row names any more loses its file.
Written only when something changed, by the rows' digest kept in memory.

Each account's own answers (R172 step 5, the fields a pack scopes to a
person) go into that account's home: ~/.bb/config/PACK.env, owned by the
account's user and readable by it alone, which bb tool reads after the
store's, so a person's own value is the one their session's verb sees.
"""
import hashlib
import json
import os
import pwd
import re

from .accounts import user_of
from .base import log

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,40}$")
PACK_NAME = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


UID = re.compile(r"^u_[0-9a-f]{8}$")


class PackConfigMixin:
    _pack_config_sig = ""
    _pack_people_sig = ""

    def pack_people_want(self, rows):
        """Each account's own pack answers written into its home on this
        node, the files no row names any more taken away; once per change,
        and as root alone (an account's home is its own user's)."""
        want = [r for r in rows if isinstance(r, dict) and UID.fullmatch(str(r.get("uid") or ""))
                and PACK_NAME.fullmatch(str(r.get("pack") or ""))]
        sig = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()
        if sig == self._pack_people_sig or os.geteuid() != 0:
            return
        by_uid = {}
        for r in want:
            by_uid.setdefault(r["uid"], {})[r["pack"]] = {k: str(v) for k, v in (r.get("env") or {}).items() if ENV_NAME.fullmatch(str(k))}
        users_dir = ""
        try:
            users_dir = os.path.join(pwd.getpwnam(self.session_account()).pw_dir, "users")
        except (KeyError, AttributeError, TypeError):
            pass
        uids = set(by_uid)
        if users_dir and os.path.isdir(users_dir):
            uids |= {n for n in os.listdir(users_dir) if UID.fullmatch(n)}
        for uid in sorted(uids):
            try:
                pw = pwd.getpwnam(user_of(uid))
            except KeyError:
                continue
            d = os.path.join(pw.pw_dir, ".bb", "config")
            packs = by_uid.get(uid, {})
            try:
                if not packs and not os.path.isdir(d):
                    continue
                os.makedirs(d, mode=0o700, exist_ok=True)
                for p in (os.path.join(pw.pw_dir, ".bb"), d):
                    os.chown(p, pw.pw_uid, pw.pw_gid)
                for name in os.listdir(d):
                    if name.endswith(".env") and name[:-4] not in packs:
                        os.unlink(os.path.join(d, name))
                for pack, env in packs.items():
                    path = os.path.join(d, pack + ".env")
                    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write("".join(f"{k}={v}\n" for k, v in sorted(env.items()) if "\n" not in v))
                    os.chown(path + ".tmp", pw.pw_uid, pw.pw_gid)
                    os.replace(path + ".tmp", path)
            except OSError as e:
                log(f"pack config: could not write {uid}'s own: {e}")
                return
        self._pack_people_sig = sig

    def pack_config_want(self, rows):
        """The hello's rows applied: each pack's env file written, the rest
        removed; once per change."""
        want = [r for r in rows if isinstance(r, dict) and PACK_NAME.fullmatch(str(r.get("pack") or "")) and str(r.get("store") or "").startswith("/")]
        sig = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()
        if sig == self._pack_config_sig:
            return
        stores = {}
        for r in want:
            stores.setdefault(r["store"], {})[r["pack"]] = {k: str(v) for k, v in (r.get("env") or {}).items() if ENV_NAME.fullmatch(str(k))}
        uid = gid = None
        if os.geteuid() == 0:
            try:
                pw = pwd.getpwnam(self.session_account())
                uid, gid = pw.pw_uid, pw.pw_gid
            except (KeyError, AttributeError, TypeError):
                uid = gid = None
        for store, packs in stores.items():
            d = os.path.join(store, ".bb", "config")
            try:
                os.makedirs(d, mode=0o700, exist_ok=True)
                if uid is not None:
                    os.chown(os.path.join(store, ".bb"), uid, gid)
                    os.chown(d, uid, gid)
                for name in os.listdir(d):
                    if name.endswith(".env") and name[:-4] not in packs:
                        os.unlink(os.path.join(d, name))
                for pack, env in packs.items():
                    path = os.path.join(d, pack + ".env")
                    tmp = path + ".tmp"
                    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write("".join(f"{k}={v}\n" for k, v in sorted(env.items()) if "\n" not in v))
                    if uid is not None:
                        os.chown(tmp, uid, gid)
                    os.replace(tmp, path)
            except OSError as e:
                log(f"pack config: could not write {d}: {e}")
                return
        self._pack_config_sig = sig
