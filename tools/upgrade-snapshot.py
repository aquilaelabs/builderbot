#!/usr/bin/env python3
"""A lived-in /config as this tree's controller writes it, kept as the
upgrade suite's fixture for this release (R79): every later build is started
on it by scripts/dashboard/test/upgrade.mjs, which checks the build migrates
it and keeps everything in it. A release runs this once, commits what it
writes, and `bb version release` refuses a version that has none.

    tools/upgrade-snapshot.py [--version V] [--force]

Nothing in it is anybody's: the controller of this tree is started on a
scratch /config and workspace, with stubs for every outside thing it would
reach (bb, docker, adb, the release and registry checks), and filled through
its own API, as a person at the dashboard fills it: the owner made on the
first-run form, accounts with roles everywhere and on projects, three
projects with a roadmap, bugs, house rules and a wiki each, settings, a
project's settings, a tool pack made here and a device signed in. The
passwords are this file's and the addresses example.com. Then it is
stopped, and its /config and workspace are packed as config.tar.gz beside
manifest.json, which lists what a later build must still hold and the
owner's password to sign in with.

Writes scripts/dashboard/test/upgrade/<V>/ (V from VERSION). A shipped
release's snapshot is never regenerated: --force is for one not yet
released.
"""
import argparse
import base64
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "scripts" / "dashboard"
OUT = DASH / "test" / "upgrade"

OWNER = ("owner", "owner-pass-0.5")
PEOPLE = {
    "ada": {"password": "ada-pass-0.5", "role": "admin", "full_name": "Ada Example"},
    "bea": {"password": "bea-pass-0.5", "role": "user", "full_name": "Bea Example"},
    "cy": {"password": "cy-pass-0.5", "role": "user", "full_name": "Cy Example"},
}
PROJECTS = ("alpha", "beta", "gamma")
PACK = {"name": "wordy", "label": "Wordy", "about": "Counts words.",
        "platforms": ["linux/amd64", "linux/arm64"],
        "install": {"steps": [["sh", "-c", 'mkdir -p "$1/bin"', "x", "{dir}"]]},
        "verbs": {"count": {"about": "Words in a file.", "usage": "FILE",
                            "run": ["{dir}/bin/wordy", "{args}"]}}}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Controller:
    """This tree's server.py on a scratch world, and its API."""

    def __init__(self, world, version):
        self.world, self.port = world, free_port()
        stub = world / "stub"
        stub.mkdir()
        for name in ("bb", "docker", "adb", "web-ext"):
            (stub / name).write_text("#!/bin/sh\nexit 0\n")
            (stub / name).chmod(0o755)
        (world / "doctor.txt").write_text("")
        (world / "home").mkdir()
        # Nothing of whoever runs this: no git identity, token or session
        # variable reaches what is committed to a public repository.
        env = {k: v for k, v in os.environ.items() if k in ("LANG", "LC_ALL", "TZ", "TMPDIR")}
        env.update(
            WORKSPACE=str(world / "workspace"), DASHBOARD_STATE=str(world / "config"),
            DASHBOARD_PORT=str(self.port), DASHBOARD_TTYD_PORT=str(free_port()),
            BUILDER_HOME=str(world / "home"), HOME=str(world / "home"),
            TMUX_TMPDIR=str(world / "tmux"), GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(world / "gitconfig"), PATH=f"{stub}:{os.environ.get('PATH', '')}",
            BB_BIN=str(stub / "bb"), BB_DOCKER_BIN=str(stub / "docker"), BB_ADB_BIN=str(stub / "adb"),
            BB_WEBEXT_BIN=str(stub / "web-ext"), BB_DOCTOR_FIXTURE=str(world / "doctor.txt"),
            BB_DEV_DATA_DIR=str(world / "devdata"), BB_ARCHIVE_SPOOL=str(world / "spool"),
            BB_AGENT_DIR=str(DASH.parent / "agent"), BB_VERSION=version,
            TC_AUTOCHECK="0", BB_NODE_POLL="3",
            BB_CLAUDE_LATEST_URL="file:///nonexistent", BB_CLAUDE_CHECK_DELAY="3600",
            BB_NGINX_TAGS_URL="file:///nonexistent", BB_NGINX_CHECK_DELAY="3600",
            BB_APPS_RELEASES_URL="file:///nonexistent", BB_APPS_BOOT_DELAY="3600",
            BB_IMAGE_DIGESTS_FILE=str(world / "image-digests.json"), BB_IMAGE_CHECK_DELAY="3600",
            BUILDERBOT_ROLE="controller", BB_TOKEN="")
        (world / "workspace").mkdir()
        self.log = open(world / "server.log", "w")
        self.proc = subprocess.Popen([sys.executable, "-u", str(DASH / "server.py")], env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.auth = None
        for _ in range(120):
            if self.proc.poll() is not None:
                raise SystemExit(f"the controller exited:\n{(world / 'server.log').read_text()}")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/login", timeout=2)
                return
            except urllib.error.HTTPError:
                return
            except OSError:
                time.sleep(0.25)
        raise SystemExit("the controller did not answer")

    def stop(self):
        with_pg = os.getpgid(self.proc.pid)
        os.killpg(with_pg, signal.SIGTERM)
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            os.killpg(with_pg, signal.SIGKILL)
            self.proc.wait()
        self.log.close()

    def form(self, path, fields):
        body = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        opener = urllib.request.build_opener(NoRedirect)
        try:
            return opener.open(req, timeout=30).status
        except urllib.error.HTTPError as e:
            return e.code

    def call(self, path, body=None, auth=None, ok=True):
        auth = auth or self.auth
        headers = {"Authorization": "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            out = {"error": f"{e.code}: {e.read()[:300].decode(errors='replace')}"}
        if ok and isinstance(out, dict) and out.get("error"):
            raise SystemExit(f"{path} {json.dumps(body)[:200] if body else ''}: {out['error']}")
        return out


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def wait_for(what, check, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return
        time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {what}")


def fill(c):
    """Everything a lived-in /config holds, made through the API."""
    st = c.form("/setup", {"username": OWNER[0], "password": OWNER[1], "password2": OWNER[1]})
    if st not in (200, 303):
        raise SystemExit(f"the first-run form answered {st}")
    c.auth = OWNER
    c.call("/api/users", {"action": "edit", "name": OWNER[0],
                          "profile": {"full_name": "Owner Example", "email": "owner@example.com"}})
    c.call("/api/settings", {"set": {"apps_vscode": False, "apps_companion": False}})
    # A node, enrolled as an operator does: a token minted, then presented
    # on the agent's door with what the machine is.
    tok = c.call("/api/v1/nodes", {"action": "enroll", "name": "box", "user": "bb"})["token"]
    req = urllib.request.Request(f"http://127.0.0.1:{c.port}/api/v1/agent/enroll", method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                                 data=json.dumps({"user": "bb", "version": "snapshot", "census": {
                                     "cpu": 4, "mem_mb": 8192, "arch": "x86_64", "system": "linux"}}).encode())
    urllib.request.urlopen(req, timeout=30).read()
    for name, p in PEOPLE.items():
        c.call("/api/users", {"action": "add", "name": name, "password": p["password"], "role": p["role"],
                              "profile": {"full_name": p["full_name"], "email": f"{name}@example.com"}})
    for name in PROJECTS:
        c.call("/api/create", {"name": name, "mode": "init", "about": "", "version": "0.1.0"})
        wait_for(f"{name} to be made", lambda n=name: (Path(c.world) / "workspace" / n / ".git").is_dir()
                 and not c.call("/api/project-job", ok=False).get("running"))
    # Roles: one of this install's own on projects, and the people on them.
    c.call("/api/roles", {"action": "set", "name": "reviewer", "scope": "projects",
                          "perms": {"projects": "read", "files": "read"}, "note": "reads, never writes"})
    c.call("/api/roles", {"action": "set", "name": "builder", "scope": "projects",
                          "perms": {"projects": "write", "files": "write"}})
    c.call("/api/users", {"action": "projects", "name": "ada", "projects": ["gamma"]})
    c.call("/api/roles", {"action": "assign", "name": "bea", "project_roles": {"alpha": ["reviewer"],
                                                                              "beta": ["builder"]}})
    c.call("/api/roles", {"action": "assign", "name": "cy", "project_roles": {"beta": ["reviewer"]}})
    c.call("/api/members", {"action": "set", "project": "gamma", "owner": "ada"})
    # The notebook.
    for p in PROJECTS:
        c.call("/api/roadmap", {"project": p, "action": "add", "text": f"{p}: the first plan"})
        c.call("/api/roadmap", {"project": p, "action": "add", "text": f"{p}: a second plan, with steps"})
        c.call("/api/bugs", {"project": p, "action": "add", "title": f"{p}: the button does nothing",
                             "severity": "high"})
        c.call("/api/bugs", {"project": p, "action": "add", "title": f"{p}: a typo on the page"})
        got = c.call(f"/api/rules?project={p}")
        c.call("/api/rules", {"project": p, "action": "save", "force": True,
                              "rules": (got.get("rules") or []) + [
                                  {"name": "tests-first", "text": f"Every change to {p} comes with its test."},
                                  {"name": "plain-words", "text": "Say it plainly."}]})
        c.call("/api/wiki", {"project": p, "action": "save", "name": "Home", "text": f"# {p}\n\nSee [[Build]].\n"})
        c.call("/api/wiki", {"project": p, "action": "save", "name": "Build", "text": "Run make.\n"})
    # A project's settings.
    c.call("/api/prefs", {"project": "alpha", "color": "teal", "build": "make"})
    c.call("/api/prefs", {"project": "beta", "gate": {"roadmap": "auto"}})
    # A tool pack made here, from a pasted bbtool.json.
    staged = c.call("/api/toolpacks", {"action": "preview", "text": json.dumps(PACK)})
    c.call("/api/toolpacks", {"action": "add", "staged": staged.get("staged") or staged.get("id")})
    # A device signed in on the device door.
    dev = c.call("/api/v1/device/signin", {"username": "bea", "password": PEOPLE["bea"]["password"],
                                           "name": "BEA-LAPTOP", "kind": "pc"})
    if not dev.get("token"):
        raise SystemExit(f"the device did not sign in: {dev}")


def manifest(c, version):
    """What a later build must still hold, read back through the API."""
    import stateversion
    users = c.call("/api/users")["users"]
    roles = c.call("/api/roles")
    m = {"version": version, "state": stateversion.current(),
         "owner": {"name": OWNER[0], "password": OWNER[1]},
         "passwords": {n: p["password"] for n, p in PEOPLE.items()},
         "accounts": sorted(u["name"] for u in users),
         "roles": sorted(n for n in roles.get("roles") or {} if n in ("builder", "reviewer")),
         "project_roles": {p["name"]: p.get("project_roles") or {} for p in roles.get("people") or []
                           if p.get("project_roles")},
         "projects": list(PROJECTS), "roadmap": {}, "bugs": {}, "rules": {}, "wiki": {},
         "toolpacks": [], "devices": {}}
    for p in PROJECTS:
        m["roadmap"][p] = sorted(i["id"] for i in c.call(f"/api/roadmap?project={p}").get("items") or [])
        m["bugs"][p] = sorted(b["id"] for b in c.call(f"/api/bugs?project={p}").get("bugs") or [])
        m["rules"][p] = sorted(r["name"] for r in c.call(f"/api/rules?project={p}").get("rules") or [])
        m["wiki"][p] = sorted(pg["name"] for pg in c.call(f"/api/wiki?project={p}").get("pages") or [])
    m["toolpacks"] = sorted(i["name"] for i in c.call("/api/toolchains").get("items") or [] if i.get("pack"))
    for u in users:
        if u.get("devices"):
            m["devices"][u["name"]] = sorted(d["name"] for d in u["devices"])
    return m


def pack(world, dest):
    """config/ and workspace/ as one tarball, owned by nobody in particular,
    with what a running controller leaves that is not state left out."""
    db = world / "config" / "builderbot.db"
    if db.exists():
        con = sqlite3.connect(db)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
    drop = {"logs", "apps", "ci-logs", "spool"}

    def keep(ti):
        name = Path(ti.name).name
        parts = Path(ti.name).parts
        if len(parts) > 1 and parts[0] == "config" and parts[1] in drop:
            return None
        if name == ".bb-map":
            return None           # the code map's index, rebuilt, and full of this run's paths
        if name.endswith((".lock", ".tmp", ".db-wal", ".db-shm")):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti
    with tarfile.open(dest, "w:gz") as t:
        for top in ("config", "workspace"):
            t.add(world / top, arcname=top, filter=keep)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", default=(ROOT / "VERSION").read_text().strip())
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = OUT / a.version
    if (out / "manifest.json").exists() and not a.force:
        raise SystemExit(f"{out} exists: a shipped release's snapshot is never regenerated "
                         "(--force for one not yet released)")
    sys.path.insert(0, str(DASH))
    world = Path(tempfile.mkdtemp(prefix="bb-upgrade-snapshot."))
    c = None
    try:
        c = Controller(world, a.version)
        fill(c)
        m = manifest(c, a.version)
        c.stop()
        c = None
        out.mkdir(parents=True, exist_ok=True)
        pack(world, out / "config.tar.gz")
        (out / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        print(f"wrote {out.relative_to(ROOT)}: {len(m['accounts'])} accounts, {len(m['projects'])} projects, "
              f"{sum(map(len, m['roadmap'].values()))} roadmap items, {sum(map(len, m['bugs'].values()))} bugs, "
              f"{len(m['toolpacks'])} tool pack(s), {sum(map(len, m['devices'].values()))} device(s)")
    finally:
        if c:
            c.stop()
            print((world / "server.log").read_text()[-4000:], file=sys.stderr)
        shutil.rmtree(world, ignore_errors=True)


if __name__ == "__main__":
    main()
