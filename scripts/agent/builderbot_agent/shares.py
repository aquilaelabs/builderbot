"""SMB and NFS shares on the controller's own machine (R162 step 1): each
share as BuilderBot's own two files say it (/etc/samba/smb.conf.d/
builderbot.conf, included by smb.conf; /etc/exports.d/builderbot.exports),
read whole for the census and written whole by the storage-share job, which
checks the name, the path (a folder under /mnt or /srv that is there) and
the users and clients named before Samba and NFS are told to read again.
Who may reach a share is a Unix user the machine has (an account's own,
R125, or one named) or everybody as a guest. The SMB passwords the accounts
set on Profile (R164 step 1) come with the hello as Samba keeps them (the
NT hash per Unix user) and are imported into Samba's own database here,
the users made where they are missing and the ones gone removed; a share
may be a Mac's Time Machine target.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

from .base import log
from .stores import save_state

SMB_FILE = "/etc/samba/smb.conf.d/builderbot.conf"
NFS_FILE = "/etc/exports.d/builderbot.exports"
# The accounts' SMB passwords as handed over, written for pdbedit to import
# (smbpasswd's line format) and removed once read.
SMB_USERS_FILE = "/run/builderbot/smbusers"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}")
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
CLIENT_RE = re.compile(r"[A-Za-z0-9*][A-Za-z0-9*./:_-]{0,80}")
ROOTS = ("/mnt/", "/srv/")


def _env(name, default):
    return os.environ.get(name) or default


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def shares_now():
    """[{name, path, smb: {on, guest, ro, users}, nfs: {on, ro, clients}}]
    from BuilderBot's own two files; [] where neither is here."""
    smb, nfs = {}, {}
    cur = None
    for line in _read(_env("BB_SMB_FILE", SMB_FILE)).splitlines():
        line = line.strip()
        m = re.fullmatch(r"\[([^\]]+)\]", line)
        if m:
            cur = m.group(1).strip()
            smb[cur] = {"path": "", "guest": False, "ro": False, "tm": False, "users": []}
            continue
        if cur and "=" in line and not line.startswith((";", "#")):
            k, _, v = line.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "path":
                smb[cur]["path"] = v[:200]
            elif k == "guest ok":
                smb[cur]["guest"] = v.lower() == "yes"
            elif k == "read only":
                smb[cur]["ro"] = v.lower() == "yes"
            elif k == "valid users":
                smb[cur]["users"] = [u for u in v.split() if USER_RE.fullmatch(u)][:64]
            elif k == "fruit:time machine":
                smb[cur]["tm"] = v.lower() == "yes"
    for line in _read(_env("BB_NFS_FILE", NFS_FILE)).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^# share: (\S+)", line)
        parts = line.split()
        path = parts[0]
        clients = []
        ro = False
        for c in parts[1:]:
            host, _, opts = c.partition("(")
            if CLIENT_RE.fullmatch(host):
                clients.append(host)
                ro = ro or "ro" in opts.rstrip(")").split(",")
        nfs[path] = {"ro": ro, "clients": clients[:64]}
    names = list(smb)
    out = []
    for name in names:
        s = smb[name]
        n = nfs.get(s["path"]) or {}
        out.append({"name": name, "path": s["path"], "smb": {"on": True, "guest": s["guest"], "ro": s["ro"], "tm": s["tm"], "users": s["users"]},
                    "nfs": {"on": bool(n), "ro": bool(n.get("ro")), "clients": n.get("clients") or []}})
    for path, n in nfs.items():
        if not any(o["path"] == path for o in out):
            out.append({"name": os.path.basename(path.rstrip("/")) or path, "path": path, "smb": {"on": False, "guest": False, "ro": False, "tm": False, "users": []},
                        "nfs": {"on": True, "ro": n["ro"], "clients": n["clients"]}})
    return out[:64]


def render(shares):
    """The two files from the record: Samba's sections and NFS's lines."""
    smb = ["# Written by BuilderBot (the Storage page): every share here is one it makes. Do not edit; the page writes it whole.\n"]
    nfs = ["# Written by BuilderBot (the Storage page): do not edit; the page writes it whole.\n"]
    for s in shares:
        if s["smb"]["on"]:
            smb.append(f"[{s['name']}]\n    path = {s['path']}\n    browseable = yes\n    read only = {'yes' if s['smb']['ro'] else 'no'}\n")
            if s["smb"]["guest"]:
                smb.append("    guest ok = yes\n    force user = nobody\n")
            else:
                smb.append(f"    guest ok = no\n    valid users = {' '.join(s['smb']['users'])}\n")
            # A Mac's Time Machine target (R164 step 1): fruit says so to the
            # Finder, catia keeps the names it writes; the Mac finds it by
            # mDNS, which Samba registers itself.
            smb.append("    vfs objects = catia fruit streams_xattr\n    fruit:metadata = stream\n"
                       + ("    fruit:time machine = yes\n" if s["smb"].get("tm") else "") + "\n")
        if s["nfs"]["on"]:
            opts = "ro" if s["nfs"]["ro"] else "rw"
            nfs.append(f"{s['path']} " + " ".join(f"{c}({opts},sync,no_subtree_check,root_squash)" for c in s["nfs"]["clients"]) + "\n")
    return "".join(smb), "".join(nfs)


class SharesMixin:
    """Agent's share jobs: one of the parts class Agent (agent.py) is made of."""

    def smb_users_want(self, rows):
        """The accounts' SMB passwords as the hello hands them (R164 step 1):
        [{user, nt}], applied once per change (its digest kept in node.json):
        each user made where it is missing (a system user, no login shell,
        the bbu group), the set imported into Samba's database whole, and
        every bbu- user Samba knows that is not in the set removed. Root,
        with Samba installed; nothing otherwise."""
        want = sorted(({"user": str(r.get("user") or ""), "nt": str(r.get("nt") or "").upper()} for r in rows if isinstance(r, dict)),
                      key=lambda r: r["user"])
        want = [r for r in want if re.fullmatch(r"bbu-[0-9a-f]{8}", r["user"]) and re.fullmatch(r"[0-9A-F]{32}", r["nt"])]
        sig = hashlib.sha256(json.dumps(want).encode()).hexdigest()
        pdbedit = shutil.which("pdbedit")
        if sig == self.state.get("smb_users_sig") or not pdbedit or os.geteuid() != 0:
            return
        group = getattr(self, "_account_group", None)
        if group:
            group()
        import pwd
        for r in want:
            try:
                pwd.getpwnam(r["user"])
            except KeyError:
                p = subprocess.run(["useradd", "-r", "-M", "-U", "-d", "/nonexistent", "-s", "/usr/sbin/nologin", "-G", "bbu", r["user"]],
                                   capture_output=True, text=True, timeout=30, check=False)
                if p.returncode != 0:
                    log(f"shares: could not make {r['user']}: {(p.stderr or '').strip()[:160]}")
        have = set()
        for line in (self._out([pdbedit, "-L"]) or "").splitlines():
            u = line.split(":", 1)[0]
            if re.fullmatch(r"bbu-[0-9a-f]{8}", u):
                have.add(u)
        for u in sorted(have - {r["user"] for r in want}):
            subprocess.run([pdbedit, "-x", "-u", u], capture_output=True, timeout=30, check=False)
        lines = []
        for r in want:
            try:
                uid = pwd.getpwnam(r["user"]).pw_uid
            except KeyError:
                continue
            lines.append(f"{r['user']}:{uid}:{'X' * 32}:{r['nt']}:[U          ]:LCT-00000000:\n")
        path = _env("BB_SMB_USERS_FILE", SMB_USERS_FILE)
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write("".join(lines))
            if lines:
                p = subprocess.run([pdbedit, "-i", f"smbpasswd:{path}", "-e", "tdbsam"], capture_output=True, text=True, timeout=60, check=False)
                if p.returncode != 0:
                    log(f"shares: pdbedit did not take the passwords: {(p.stderr or p.stdout or '').strip()[:200]}")
                    return
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        self.state["smb_users_sig"] = sig
        save_state(self.state)
        log(f"shares: {len(lines)} SMB password(s) in Samba, {len(have - {r['user'] for r in want})} removed")

    def _out(self, argv, timeout=30):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def _apply_storage_share(self, job, cfg):
        say = job.say
        if os.geteuid() != 0:
            say("refused: shares are written as root, and this agent is not root\n")
            return "failed", 77
        action = str(cfg.get("share") or "")
        name = str(cfg.get("name") or "").strip()
        if action not in ("set", "remove"):
            say(f"refused: {action or 'no action'} is not a share action (set, remove)\n")
            return "failed", 64
        if not NAME_RE.fullmatch(name):
            say(f"refused: {name or 'no name'} is not a share name (letters, digits, dots, hyphens and underscores, 63 at most)\n")
            return "failed", 64
        have = shares_now()
        rest = [s for s in have if s["name"] != name]
        if action == "set":
            path = str(cfg.get("path") or "").strip()
            smb = cfg.get("smb") if isinstance(cfg.get("smb"), dict) else {}
            nfs = cfg.get("nfs") if isinstance(cfg.get("nfs"), dict) else {}
            if not (path.startswith(ROOTS) and os.path.isabs(path) and ".." not in path.split("/") and os.path.isdir(path)):
                say(f"refused: {path or 'no path'} is not a folder under /mnt or /srv that is here\n")
                return "failed", 65
            if not smb.get("on") and not nfs.get("on"):
                say("refused: a share is served over SMB, NFS or both\n")
                return "failed", 64
            users = [str(u) for u in (smb.get("users") or []) if isinstance(u, str)]
            if smb.get("on") and not smb.get("guest"):
                if not users:
                    say("refused: an SMB share takes the users who may reach it, or everybody as a guest\n")
                    return "failed", 64
                for u in users:
                    if not USER_RE.fullmatch(u):
                        say(f"refused: {u!r} is not a user name\n")
                        return "failed", 64
                    try:
                        import pwd
                        pwd.getpwnam(u)
                    except KeyError:
                        say(f"refused: {u} is not a user this machine has (an account's own user is made when it first signs in here)\n")
                        return "failed", 66
            clients = [str(c) for c in (nfs.get("clients") or []) if isinstance(c, str)]
            if nfs.get("on"):
                if not clients:
                    say("refused: an NFS share takes the clients it is exported to (an address, a network, a name, or * for any)\n")
                    return "failed", 64
                for c in clients:
                    if not CLIENT_RE.fullmatch(c):
                        say(f"refused: {c!r} is not a client (an address, a network like 192.168.1.0/24, a name, or *)\n")
                        return "failed", 64
            if any(s["path"] == path and s["name"] != name for s in rest):
                say(f"refused: {path} is shared already under another name\n")
                return "failed", 66
            rest.append({"name": name, "path": path,
                         "smb": {"on": bool(smb.get("on")), "guest": bool(smb.get("guest")), "ro": bool(smb.get("ro")), "tm": smb.get("tm") is True, "users": users[:64]},
                         "nfs": {"on": bool(nfs.get("on")), "ro": bool(nfs.get("ro")), "clients": clients[:64]}})
            say(f"share {name}: {path}, {'SMB' if smb.get('on') else ''}{' and ' if smb.get('on') and nfs.get('on') else ''}{'NFS' if nfs.get('on') else ''}\n")
        else:
            if len(rest) == len(have):
                say(f"refused: no share called {name}\n")
                return "failed", 66
            say(f"share {name}: removed\n")
        smb_text, nfs_text = render(rest)
        smb_file, nfs_file = _env("BB_SMB_FILE", SMB_FILE), _env("BB_NFS_FILE", NFS_FILE)
        try:
            for f, text in ((smb_file, smb_text), (nfs_file, nfs_text)):
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f + ".new", "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.chmod(f + ".new", 0o644)
        except OSError as e:
            say(f"the share files did not write: {e}\n")
            return "failed", 67
        testparm = shutil.which("testparm")
        if testparm and subprocess.run([testparm, "-s", "--suppress-prompt", smb_file + ".new"], capture_output=True, text=True, check=False).returncode != 0:
            say("refused: Samba does not accept the share file as written (testparm); nothing changed\n")
            os.unlink(smb_file + ".new")
            os.unlink(nfs_file + ".new")
            return "failed", 68
        os.replace(smb_file + ".new", smb_file)
        os.replace(nfs_file + ".new", nfs_file)
        bad = 0
        if shutil.which("smbcontrol"):
            bad += self._sh(job, [shutil.which("smbcontrol"), "all", "reload-config"], timeout=30) != 0
        if shutil.which("exportfs"):
            bad += self._sh(job, [shutil.which("exportfs"), "-ra"], timeout=30) != 0
        self.hello_again(f"the share {name}: {action}")
        return ("succeeded", 0) if not bad else ("failed", 1)
