"""The file-access servers a project's settings open (FTP)."""
import contextlib
import json
import os
import shutil
import subprocess
import threading
from .base import hello_again, log
from .toolchains import sdk_env


class FtpServers:
    """A project's file access over FTP (R151): one bb-ftpd per project the
    controller's hello names, from the ftp toolchain, as the session
    account, rooted at the project's tree. bb-ftpd knows nobody's password:
    each login comes up its stdout as a JSON line, is asked of the
    controller's ftp-auth, and the answer goes back down its stdin. Nothing
    is kept here, so an access taken away holds from the next login.

    What is up and why not is said to the controller with the ftp verb
    after every change, for the project settings to show."""

    def __init__(self, agent):
        self.agent = agent
        self.lock = threading.Lock()
        self.procs = {}       # project -> {"proc", "port", "root", "why"}
        self.wanted = []

    def want(self, rows):
        rows = [r for r in rows if isinstance(r, dict) and r.get("project") and r.get("port")]
        with self.lock:
            self.wanted = rows
        threading.Thread(target=self.apply, name="ftp", daemon=True).start()

    def apply(self):
        with self.lock:
            want = {r["project"]: r for r in self.wanted}
            for name in list(self.procs):
                p = self.procs[name]
                w = want.get(name)
                if not w or w["port"] != p["port"] or w["root"] != p["root"] or p["proc"] is None \
                        or p["proc"].poll() is not None:
                    self._stop(name)
            for name, w in want.items():
                if name not in self.procs:
                    self.procs[name] = self._start(name, int(w["port"]), str(w["root"]))
            rows = [{"project": n, "up": bool(p["proc"] and p["proc"].poll() is None), "why": p["why"],
                     "port": p["port"], "addr": p.get("addr", "")} for n, p in self.procs.items()]
        self.agent.ctl.call("ftp", {"servers": rows}, timeout=15)

    def _start(self, name, port, root):
        rec = {"proc": None, "port": port, "root": root, "why": ""}
        env = dict(sdk_env(self.agent.state))
        try:
            who = self.agent.as_user(env, self.agent.session_account())
        except RuntimeError as e:
            rec["why"] = str(e)
            return rec
        exe = shutil.which("bb-ftpd", path=env.get("PATH"))
        if not exe:
            rec["why"] = "the ftp toolchain is not installed on this node: install it on the Toolchains page"
            return rec
        if not os.path.isdir(root):
            rec["why"] = f"{root} is not on this node"
            return rec
        home = env.get("HOME") or os.path.expanduser("~")
        cert = os.path.join(home, ".builderbot", "ftp", "cert.pem")
        bind = self.agent.session_bind()
        rec["addr"] = bind
        try:
            proc = subprocess.Popen([exe, "--root", root, "--port", str(port), "--cert", cert,
                                     "--bind", bind, "--project", name],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, cwd="/", text=True, bufsize=1, **who)
        except OSError as e:
            rec["why"] = f"bb-ftpd could not start: {e}"[:200]
            return rec
        # Started is not up: a port already taken ends it at once, and its
        # last line says so. The first line is the listening one.
        first = proc.stderr.readline()
        if "listening" not in first:
            tail = (first + proc.stderr.read() if proc.poll() is not None else first).strip().splitlines()
            rec["why"] = (tail[-1] if tail else "bb-ftpd ended at once")[:200]
            with contextlib.suppress(OSError):
                proc.kill()
            return rec
        rec["proc"] = proc
        threading.Thread(target=self._relay, args=(name, proc), name=f"ftp-{name}", daemon=True).start()
        threading.Thread(target=self._drain, args=(name, proc), name=f"ftp-log-{name}", daemon=True).start()
        log(f"ftp: {name} on {bind}:{port}")
        return rec

    def _relay(self, name, proc):
        """Each login asked of the controller, its answer handed back."""
        for line in proc.stdout:
            try:
                q = json.loads(line)
            except ValueError:
                continue
            st, r = self.agent.ctl.call("ftp-auth", {"project": name, "user": str(q.get("user") or ""),
                                                     "password": str(q.get("password") or ""),
                                                     "addr": str(q.get("addr") or "")}, timeout=20)
            ans = {"id": q.get("id"), "access": r.get("access", "") if st == 200 else "",
                   "why": r.get("why", "") if st == 200 else "BuilderBot could not be asked; try again shortly."}
            try:
                proc.stdin.write(json.dumps(ans) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                return
        # Its pipe closed: it ended. Said, and started again on the next apply.
        with self.lock:
            p = self.procs.get(name)
            if p and p["proc"] is proc:
                p["why"] = "bb-ftpd ended; it is started again on the next hello"
        hello_again(self.agent, f"bb-ftpd for {name} ended")

    @staticmethod
    def _drain(name, proc):
        for line in proc.stderr:
            line = line.strip()
            if line and ("error" in line.lower() or "traceback" in line.lower()):
                log(f"ftp {name}: {line[:200]}")

    def _stop(self, name):
        p = self.procs.pop(name, None)
        if p and p["proc"] and p["proc"].poll() is None:
            p["proc"].terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                p["proc"].wait(5)
            if p["proc"].poll() is None:
                p["proc"].kill()
        if p and p["proc"]:
            for f in (p["proc"].stdin, p["proc"].stdout, p["proc"].stderr):
                with contextlib.suppress(OSError, ValueError):
                    f.close()

    def stop_all(self):
        with self.lock:
            for name in list(self.procs):
                self._stop(name)
