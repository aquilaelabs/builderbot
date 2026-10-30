"""Accounts as their own users on a node (R125).

Every account's sessions ran as one Unix user, the session account, so its
homes were one uid's: a shell as that user read every account's coding-agent
tokens and attached to every account's tmux. With the node's setting on, the
agent gives each account that has a home here a user of its own, bbu- and
its eight hex digits, which owns that home (700) and runs its terminals, its
tmux and its sessions; bb-session's tty verb is how a terminal becomes it.

A home moves to its user only while nothing of the account runs on the
session account's tmux, so a session that was running when the setting came
on is never ended: it keeps going as before, and the move waits for it.
Root, and the agent's loop, once a minute.
"""
import contextlib
import grp
import json
import os
import pwd
import re
import subprocess
import time

from .base import ROOT_BUNDLE_DIR, SESSION, SESSION_BIN, SHARE, log
from .tokenwatch import TokenWatch

GROUP = "bbu"
PREFIX = "bbu-"
UID_RE = re.compile(r"^u_[0-9a-f]{8}$")
# Where bb-session tty reads the terminal's environment: sudo resets it, so
# the agent leaves it here, root's alone.
TTY_ENV = "/run/bb-session/tty-env.json"
# The session account's groups an account's user is NOT given: the ones that
# are root by another name, or none of a session's business.
NOT_GROUPS = frozenset(("docker", "sudo", "wheel", "adm", "systemd-journal", "root", "lxd", "libvirt"))
EVERY_S = 60


def user_of(account):
    return PREFIX + account[2:] if UID_RE.match(account or "") else ""


class AccountsMixin:
    accounts_at = 0.0

    def account_users_on(self):
        """The node's setting (R125), and only where the agent is root."""
        return bool(self.state.get("account_users")) and os.geteuid() == 0

    def account_users_pass(self):
        """Once a minute: a user for every account home, and each home moved
        to it once nothing of the account runs as the session account."""
        if os.geteuid() != 0 or time.time() - self.accounts_at < EVERY_S:
            return
        self.accounts_at = time.time()
        sa = self.session_account()
        try:
            sa_pw = pwd.getpwnam(sa)
        except KeyError:
            return
        users_dir = os.path.join(sa_pw.pw_dir, "users")
        if not os.path.isdir(users_dir):
            return
        if not self.account_users_on():
            left = self._homes_back(users_dir, sa_pw)
            SESSION["accounts"] = {"users": left} if left else {}
            return
        had = self.account_users_ready()
        self._account_group()
        if not had and self.account_users_ready():
            # The group is what lets the layout say so: written now, and
            # the terminals started again on bb-session tty.
            self.refresh_session_tool()
            self.session_renew()
        if not self.account_users_ready():
            SESSION["accounts"] = {"error": "the agent could not make the bbu group, or bb-session is not installed"}
            return
        # Each account's user has to pass through the session account's home
        # and users/ to reach its own: search alone (o+x), never a listing,
        # so the names of the other homes stay unread (B270).
        for d in (sa_pw.pw_dir, users_dir):
            with contextlib.suppress(OSError):
                st = os.lstat(d)
                if not st.st_mode & 0o001:
                    os.chmod(d, (st.st_mode & 0o7777) | 0o001)
        legacy = self._legacy_accounts()
        users = moved = waiting = 0
        for name in sorted(os.listdir(users_dir))[:500]:
            home = os.path.join(users_dir, name)
            if not UID_RE.match(name) or not os.path.isdir(home) or os.path.islink(home):
                continue
            pw = self._account_user(name, home, sa)
            if not pw:
                continue
            users += 1
            with contextlib.suppress(OSError):
                if os.lstat(home).st_uid == sa_pw.pw_uid:
                    if name in legacy:
                        waiting += 1
                        continue
                    self._move_home(home, pw)
                if os.lstat(home).st_uid == pw.pw_uid:
                    moved += 1
                    self._own_share(name, pw)
                    # Its token files held at 600, and who else opens one
                    # said (R125 step 6).
                    self.token_watch().watch(home, pw)
        SESSION["accounts"] = {"users": users, "moved": moved, "waiting": waiting}
        self.tty_env_write()

    def _homes_back(self, users_dir, sa_pw):
        """The setting off again: each home its account's user owns goes
        back to the session account, once nothing runs on that user's tmux.
        The users themselves stay, holding nothing, for the next time."""
        left = 0
        for name in sorted(os.listdir(users_dir))[:500]:
            home = os.path.join(users_dir, name)
            user = user_of(name)
            if not user or not os.path.isdir(home) or os.path.islink(home):
                continue
            try:
                pw = pwd.getpwnam(user)
                if os.lstat(home).st_uid != pw.pw_uid:
                    continue
            except (KeyError, OSError):
                continue
            if (self._tmux_as(user, ["list-sessions", "-F", "#{session_name}"], quiet=True) or "").strip():
                left += 1
                continue
            self._move_home(home, sa_pw)
            self._own_share(name, sa_pw)
        return left

    def _account_group(self):
        try:
            grp.getgrnam(GROUP)
        except KeyError:
            subprocess.run(["groupadd", "-r", GROUP], capture_output=True, timeout=30, check=False)

    def _account_user(self, account, home, sa):
        """The account's user, made if it is missing: a system user with no
        password and no login shell, its own group, the bbu group the sudo
        rule names, and the session account's groups but the root-like
        ones (kvm for the emulator, render and video for the card)."""
        name = user_of(account)
        extra = sorted({GROUP} | {g.gr_name for g in grp.getgrall()
                                  if sa in g.gr_mem and g.gr_name not in NOT_GROUPS})
        with contextlib.suppress(KeyError):
            have = pwd.getpwnam(name)
            # One made for its SMB password first (shares.py, R164 step 1)
            # has the bbu group alone: the session's groups are added.
            missing = [g for g in extra if name not in (grp.getgrnam(g).gr_mem if g in {x.gr_name for x in grp.getgrall()} else [name])]
            if missing:
                subprocess.run(["usermod", "-aG", ",".join(missing), name], capture_output=True, timeout=30, check=False)
            return have
        p = subprocess.run(["useradd", "-r", "-M", "-U", "-d", home, "-s", "/usr/sbin/nologin",
                            "-G", ",".join(extra), name], capture_output=True, text=True, timeout=30, check=False)
        if p.returncode != 0:
            log(f"accounts: could not make {name}: {(p.stderr or '').strip()[:160]}")
            return None
        log(f"accounts: made {name} for {account}")
        try:
            return pwd.getpwnam(name)
        except KeyError:
            return None

    def _legacy_accounts(self):
        """The accounts with a session still on the session account's tmux,
        whose homes wait: moving one under it would stop its next write."""
        out = self._tmux_as(self.session_account(), ["list-sessions", "-F", "#{session_name}"]) or ""
        return {m.group(1) for m in (re.match(r"^(u_[0-9a-f]{8})~", n) for n in out.split()) if m}

    def _own_share(self, account, pw):
        """The account's folder of conversations in the share (the link its
        ~/.claude/projects is, lib/common.sh's claude_projects_link) its
        user's too, made where it is missing: on a node's own disk (a synced
        copy) the session account's 0700 folder was one the account's user
        could not write, so its conversations stayed in its home and the
        controller listed none (R125, the dev pair's walk of 24 Oct). On a
        share squashed to one owner the change is refused and not needed:
        the server takes the write as that owner."""
        root = os.path.join(SHARE, ".claude")
        if not os.path.isdir(root):
            return
        d = os.path.join(root, account)
        with contextlib.suppress(OSError):
            if not os.path.isdir(d):
                os.makedirs(os.path.join(d, "projects"), mode=0o700)
            if os.lstat(d).st_uid != pw.pw_uid:
                self._move_home(d, pw)

    def _move_home(self, home, pw):
        """The home and everything in it to the account's user, 700 at the
        top; a link is changed itself, never what it points at."""
        n = 0
        for d, dirs, files in os.walk(home):
            for x in [d] + [os.path.join(d, f) for f in dirs + files]:
                with contextlib.suppress(OSError):
                    os.lchown(x, pw.pw_uid, pw.pw_gid)
                    n += 1
        os.chmod(home, 0o700)
        log(f"accounts: {os.path.basename(home)}'s home is {pw.pw_name}'s now ({n} entries)")

    def tty_env_write(self):
        """The environment a terminal starts with, for bb-session tty: what
        a terminal gets (session_env), less what is the account's own."""
        if not self.account_users_on():
            return
        env = {}
        with contextlib.suppress(OSError, RuntimeError):
            env, _who = self.session_env(os.path.join(ROOT_BUNDLE_DIR, "current"))
        env = {k: v for k, v in env.items() if k not in ("HOME", "USER", "LOGNAME")}
        os.makedirs(os.path.dirname(TTY_ENV), mode=0o700, exist_ok=True)
        tmp = TTY_ENV + ".new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(env, f)
        os.replace(tmp, TTY_ENV)

    def drop_for(self, env, account):
        """How to run something for one account here: (who, the base home,
        the bundle to run bb from). The account's own user, from the
        root-owned bundle, once its home is that user's (R125); the session
        account and its bundle on the store otherwise, as before."""
        sa = self.session_account()
        base = ""
        with contextlib.suppress(KeyError):
            base = pwd.getpwnam(sa).pw_dir
        user = user_of(account)
        if user and os.geteuid() == 0:
            try:
                pw = pwd.getpwnam(user)
                mine = os.lstat(os.path.join(base, "users", account)).st_uid == pw.pw_uid
            except (KeyError, OSError):
                mine = False
            if mine and os.path.isdir(os.path.join(ROOT_BUNDLE_DIR, "current")):
                return self.as_user(env, user), base, os.path.realpath(os.path.join(ROOT_BUNDLE_DIR, "current"))
        return self.as_user(env, sa), base, ""

    def token_watch(self):
        tw = self.__dict__.get("_tokenwatch")
        if tw is None:
            tw = self.__dict__["_tokenwatch"] = TokenWatch()
            tw.start()
        return tw

    def account_users_ready(self):
        """Whether the sudo rule and bb-session's layout may say accounts
        are their own users: the setting, the group, and bb-session there."""
        if not self.account_users_on() or not os.access(SESSION_BIN, os.X_OK):
            return False
        try:
            grp.getgrnam(GROUP)
        except KeyError:
            return False
        return True
