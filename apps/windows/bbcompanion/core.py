"""The companion app's sync (R270 step 3): a folder on this machine kept in
step with a BuilderBot project, both ways, by the node agent's own sync
(builderbot_agent.wssync), shared rather than copied, spoken through the
device door (/api/v1/device/) with the person's device token.

What the agent's sync expects of a node, this answers for a person:
- which projects to hold: the ones the person picked in the app, each in its
  own folder (WorkspaceSync.top), read-only where their access is read;
- a hint when a project moves: a long poll per project on the device door,
  which nudges the sync the way a node's held work request does;
- what comes down: only paths Windows can hold (names.held), the rest left
  out and said, from the state, the changes and the first copy's archive.
"""
import os
import sys
import tarfile
import threading

try:
    from builderbot_agent import controller as _controller, wssync as _wssync
except ImportError:                                   # a checkout: the agent beside this tree
    # From the checkout (apps/windows/bbcompanion): the agent's package three
    # levels up, under scripts/agent.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "agent"))
    from builderbot_agent import controller as _controller, wssync as _wssync

from . import names, pc, update

POLL_WAIT = 25          # seconds the device door holds a long poll
UPDATE_EVERY = 24 * 3600


class DeviceDoor:
    """The agent's Controller on the device door, with what comes down cut
    to what this machine can hold and the projects to hold the person's
    choice. `picked` is {project: folder}."""

    def __init__(self, url, token, pin="", picked=None):
        self.ctl = _controller.Controller(url, token, pin, door="device")
        self.ctl.headers.update(update.headers())
        self.picked = dict(picked or {})
        self.too_old = False      # the controller's door is past this app's (426)
        self.access = {}          # project -> "rw" | "r", from the door
        self.left_out = {}        # project -> {path: why}: what Windows cannot hold
        self.error = ""

    def call(self, verb, body=None, timeout=30, method="POST", raw=False):
        if verb == "sync" and (body or {}).get("action") == "projects":
            return self._projects()
        st, r = self.ctl.call(verb, body, timeout=timeout, method=method, raw=raw)
        if st == 426:
            self.too_old = True
            self.error = str((r or {}).get("error") or "update the app")
        if verb == "sync" and st == 200 and isinstance(r, dict):
            project = (body or {}).get("project", "")
            key = "files" if "files" in r else "changes" if "changes" in r else ""
            if key:
                kept, out = names.held([row[0] for row in r[key]])
                if key == "files":
                    self.left_out[project] = out
                else:
                    self.left_out.setdefault(project, {}).update(out)
                r[key] = [row for row in r[key] if row[0] in kept]
        return st, r

    def _projects(self):
        """The agent's question, which projects this machine holds: the
        ones picked here that the person may still read, each at its
        revision; one read-only for them is held read-only."""
        st, r = self.ctl.call("projects", {})
        if st == 426:
            self.too_old = True
        if st != 200:
            self.error = str((r or {}).get("error") or f"the controller answered {st}")
            return st, r
        # A controller older than this app: said plainly, and the sync told
        # nothing this time (a refusal, which it waits out), rather than a
        # sync that half works against answers it misreads.
        too_new = update.controller_too_old(r)
        if too_new:
            self.error = too_new
            return 409, {"error": too_new}
        self.error = ""
        mine = {p["project"]: p for p in r.get("projects") or []}
        self.access = {n: mine[n]["access"] for n in self.picked if n in mine}
        want = {n: mine[n]["rev"] for n in self.picked if n in mine and mine[n]["access"] == "rw"}
        reads = {n: mine[n]["rev"] for n in self.picked if n in mine and mine[n]["access"] == "r"}
        return 200, {"mode": "sync", "projects": want, "reads": reads}

    def fetch(self, path, dest, timeout=600):
        code, digest = self.ctl.fetch(path, dest, timeout=timeout)
        if code == 200 and path.startswith("sync-tar?"):
            _drop_unheld(dest)
        return code, digest

    def upload(self, path, src, timeout=600, offset=0, length=None):
        return self.ctl.upload(path, src, timeout=timeout, offset=offset, length=length)


def lock_word(row):
    """A project's lock as the list says it (R119), from its row on the
    device door: "" when it is not locked, ", locked" when the lock leaves
    this account in (its owner's own), ", locked against you" when it holds
    this account out, which the controller keeps read-only."""
    if not (row or {}).get("locked"):
        return ""
    return ", locked against you" if row.get("locked_why") else ", locked"


def _drop_unheld(tar_path):
    """The first copy's archive, rewritten without the members Windows
    cannot hold, so the agent's unpack meets none of them."""
    with tarfile.open(tar_path) as t:
        members = t.getmembers()
        kept, out = names.held([m.name for m in members if not m.isdir()])
        if not out:
            return
        tmp = tar_path + ".held"
        with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as w:
            for m in members:
                if m.isdir() or m.name in kept:
                    w.addfile(m, t.extractfile(m) if m.isfile() else None)
    os.replace(tmp, tar_path)


class DeviceAgent:
    """What the agent's sync reads off its agent, for a person's machine:
    the door as its controller, and a data folder for its records."""

    def __init__(self, door, data_dir):
        self.ctl = door
        self.state = {"stores": {"data": data_dir}}


class FolderSync(_wssync.WorkspaceSync):
    """The agent's sync with each project in the folder its person picked."""

    def __init__(self, agent, picked):
        super().__init__(agent, root=agent.state["stores"]["data"])
        self.picked = dict(picked)

    def top(self, name):
        return self.picked.get(name) or super().top(name)


class Companion:
    """One person's machine kept in step: the sync's loop, and a long poll
    per project that wakes it the moment the project moves."""

    def __init__(self, url, token, picked, data_dir, pin="", lend=None, asker=None):
        os.makedirs(data_dir, exist_ok=True)
        # What this PC lends each project (pc.py), and who answers an ask:
        # the window, or nobody from a command line, which refuses.
        self.lend = {p: c for p, c in (lend or {}).items() if p in picked}
        self.asker = asker
        self.lender = pc.Lender()
        self.lent_log = []        # the last uses, for the window
        self.door = DeviceDoor(url, token, pin, picked)
        self.sync = FolderSync(DeviceAgent(self.door, data_dir), picked)
        self.picked = dict(picked)
        self.stopped = threading.Event()
        self.polls = []
        self.update = {}          # the last look for a newer app (update.check)
        self.look = threading.Event()

    def start(self):
        self.sync.start()
        threading.Thread(target=self._updates, name="updates", daemon=True).start()
        if self.lend:
            threading.Thread(target=self._lending, name="lending", daemon=True).start()
        for name in self.picked:
            t = threading.Thread(target=self._poll, args=(name,), name=f"poll-{name}", daemon=True)
            t.start()
            self.polls.append(t)

    def _poll(self, name):
        """Hold a long poll on the project and nudge the sync when it moves.
        The revision is the sync's own, so a change this machine made and
        the sync has already taken in does not wake it again."""
        while not self.stopped.is_set():
            p = self.sync.projects.get(name)
            rev = p.rev if p and p.ready else 0
            st, r = self.door.ctl.call("sync", {"action": "since", "project": name, "rev": rev,
                                                "wait": POLL_WAIT}, timeout=POLL_WAIT + 15)
            if st == 200 and (r.get("changes") or r.get("reset")):
                self.sync.nudge({name: r.get("rev")})
            elif st != 200:
                self.stopped.wait(10)      # down or refused: try again, not in a spin

    def _lending(self):
        """Lend this PC's verbs to its projects while the app runs: a long
        poll on the door for what sessions ask, each run on its own thread
        (a build is long), its result posted back (R270 step 6)."""
        lent = {p: pc.lent_verbs(c) for p, c in self.lend.items()}
        lent = {p: v for p, v in lent.items() if v}
        while lent and not self.stopped.is_set():
            st, r = self.door.ctl.call("pc-work", {"projects": lent, "wait": POLL_WAIT}, timeout=POLL_WAIT + 15)
            if st != 200:
                self.stopped.wait(10)
                continue
            for req in r.get("work") or []:
                threading.Thread(target=self._lend_one, args=(req,), daemon=True).start()

    def _lend_one(self, req):
        if req.get("mode") == "ask" and not (self.asker and self.asker(req)):
            out = {"ok": False, "refused": True,
                   "text": "" if self.asker else "this PC runs the companion without a window, so nobody was there to say yes"}
        else:
            try:
                out = self.lender.run(req, self.lend.get(req["project"]) or {}, self.picked.get(req["project"], ""))
            except Exception as e:          # noqa: BLE001 (said to the session)
                out = {"ok": False, "text": f"{type(e).__name__}: {e}"}
        self.lent_log = ([f"{req['verb']} for {req['project']}: {'refused' if out.get('refused') else 'done' if out.get('ok') else 'failed'}"]
                         + self.lent_log)[:20]
        self.door.ctl.call("pc-result", {"id": req["id"], **out}, timeout=120)

    def _updates(self):
        """A look for a newer app at start and once a day, and at once when
        the door says this one is too old (R270 step 9)."""
        while not self.stopped.is_set():
            try:
                self.update = update.check(self.door.ctl)
            except Exception as e:          # noqa: BLE001 (said in the window)
                self.update = {"said": f"the update check failed: {type(e).__name__}: {e}"}
            self.look.wait(UPDATE_EVERY)
            self.look.clear()

    def status(self):
        """For the tray: each project's state, what Windows could not hold,
        the door's own trouble, and an update waiting for a restart."""
        st = self.sync.status() or {}
        if self.door.too_old and not self.update.get("pending"):
            self.door.too_old = False
            self.look.set()
        return {"error": self.door.error, "update": self.update, "lent": self.lent_log,
                "projects": {n: {**st.get(n, {"ready": False}), "access": self.door.access.get(n, ""),
                                 "left_out": self.door.left_out.get(n, {})} for n in self.picked}}

    def conflicts(self):
        """The conflict copies in the picked folders: what the controller
        kept beside a file when two changes met."""
        out = []
        for top in self.picked.values():
            for d, _, files in os.walk(top):
                out += [os.path.join(d, f) for f in files if ".conflict-" in f]
        return out

    def stop(self):
        self.stopped.set()


def sign_in(url, username, password, name, pin=""):
    """Trade the person's name and password, once, for a device token:
    ({token, device, account} | {error})."""
    ctl = _controller.Controller(url, "", pin, door="device")
    ctl.headers.update(update.headers())
    st, r = ctl.call("signin", {"username": username, "password": password, "name": name, "kind": "pc"})
    if st != 200:
        said = (r or {}).get("error") or f"the controller answered {st}"
        # A TLS hello to a plain HTTP server, which each OpenSSL names its own way.
        if url.lower().startswith("https://") and "SSL" in said and any(
                w in said for w in ("WRONG_VERSION_NUMBER", "RECORD_LAYER_FAILURE", "HTTP_REQUEST")):
            said = ("that address answers in plain HTTP, not HTTPS: use http:// in front of it "
                    "(https:// is for an address behind nginx with a certificate)")
        return {"error": said}
    return r
