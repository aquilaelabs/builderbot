"""This PC lent to a project (R270 steps 6 and 7): the verbs its person set
up here, run when a session on the project asks with `bb pc VERB`, under the
project's Claude may: Use a lent PC.

What each verb runs is this machine's own, set by its person (settings.py
"lend", `python -m bbcompanion lend`): an editor's or a game's command line,
a build's, the editor's log file, the port of the editor's local interface.
A session names a verb from the table and nothing else; {folder} in a
command line is the project's folder here.

What comes back speaks the project's paths, not this PC's: the folder is
written /workspace/PROJECT in a log or a build's output (step 7), so a
session reads it as it reads its own tree.
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

# verb -> what its setting is: a command line, a file, a port, or nothing.
VERBS = {"editor-start": "argv", "editor-stop": "", "game-start": "argv", "game-stop": "",
         "build": "argv", "shot": "", "log": "file", "editor-call": "port"}
TEXT_MAX = 256 << 10
BUILD_TIMEOUT = 1800


def lent_verbs(conf):
    """The verbs a project's settings here lend: the ones set up, and the
    stops beside the starts, and a picture always once anything is."""
    out = [v for v, kind in VERBS.items() if kind and conf.get(v)]
    out += [v.replace("-start", "-stop") for v in out if v.endswith("-start")]
    return sorted(set(out + (["shot"] if out else [])))


def to_project(text, folder, project):
    """The folder written as the project's own path, in either slash and
    any case Windows would accept."""
    if not folder:
        return text
    want = f"/workspace/{project}"
    for f in {folder, folder.replace("\\", "/"), folder.replace("/", "\\")}:
        text = re.sub(re.escape(f.rstrip("\\/")) + r"([\\/][^\s\"']*)?",
                      lambda m: want + (m.group(1) or "").replace("\\", "/"), text,
                      flags=re.IGNORECASE if os.name == "nt" else 0)
    return text


def _argv(conf, verb, folder):
    argv = conf.get(verb) or []
    return [str(a).replace("{folder}", folder) for a in argv]


def _tail(text):
    return text[-TEXT_MAX:]


class Lender:
    """The running processes this PC started for each project, so a stop
    stops what a start began and nothing else."""

    def __init__(self):
        self.procs = {}           # (project, "editor" | "game") -> Popen

    def run(self, req, conf, folder):
        """One request: {ok, text?, picture?}."""
        verb, project = req["verb"], req["project"]
        if verb not in lent_verbs(conf):
            return {"ok": False, "text": f"{verb} is not set up for {project} on this PC"}
        if verb in ("editor-start", "game-start"):
            key = (project, verb.split("-")[0])
            if key in self.procs and self.procs[key].poll() is None:
                return {"ok": True, "text": f"the {key[1]} is running already"}
            self.procs[key] = subprocess.Popen(_argv(conf, verb, folder), cwd=folder or None)  # noqa: S603 (its person's)
            return {"ok": True, "text": f"started the {key[1]} (pid {self.procs[key].pid})"}
        if verb in ("editor-stop", "game-stop"):
            p = self.procs.pop((project, verb.split("-")[0]), None)
            if not p or p.poll() is not None:
                return {"ok": True, "text": "it was not running from here"}
            p.terminate()
            try:
                p.wait(20)
            except subprocess.TimeoutExpired:
                p.kill()
            return {"ok": True, "text": "stopped"}
        if verb == "build":
            try:
                r = subprocess.run(_argv(conf, verb, folder), cwd=folder or None, capture_output=True,  # noqa: S603
                                   text=True, errors="replace", timeout=BUILD_TIMEOUT)
            except subprocess.TimeoutExpired:
                return {"ok": False, "text": f"the build ran past {BUILD_TIMEOUT // 60} minutes and was stopped"}
            except OSError as e:
                return {"ok": False, "text": f"the build did not start: {e}"}
            out = to_project(_tail((r.stdout or "") + (r.stderr or "")), folder, project)
            return {"ok": r.returncode == 0, "text": out + f"\n(exit {r.returncode})"}
        if verb == "log":
            path = str(conf.get("log") or "").replace("{folder}", folder)
            try:
                with open(path, "rb") as f:
                    f.seek(max(0, os.path.getsize(path) - TEXT_MAX))
                    text = f.read().decode("utf-8", "replace")
            except OSError as e:
                return {"ok": False, "text": f"the log could not be read: {e}"}
            return {"ok": True, "text": to_project(text, folder, project)}
        if verb == "editor-call":
            a = req.get("args") or {}
            url = f"http://127.0.0.1:{int(conf.get('editor-call'))}{a.get('path') or '/'}"
            data = a.get("body", "").encode() if a.get("body") else None
            rq = urllib.request.Request(url, data=data, method=a.get("method") or "GET",
                                        headers={"Content-Type": "application/json"} if data else {})
            try:
                with urllib.request.urlopen(rq, timeout=60) as r:          # noqa: S310 (this PC's own port)
                    return {"ok": True, "text": to_project(_tail(r.read().decode("utf-8", "replace")), folder, project)}
            except urllib.error.HTTPError as e:
                return {"ok": False, "text": f"{e.code}: {_tail(e.read().decode('utf-8', 'replace'))}"}
            except OSError as e:
                return {"ok": False, "text": f"the editor's interface did not answer: {e}"}
        if verb == "shot":
            return shot()
        return {"ok": False, "text": f"no such verb: {verb}"}


def shot():
    """A picture of the screen as a PNG: PowerShell's own on Windows,
    ImageMagick's import elsewhere where there is one."""
    tmp = os.path.join(tempfile.gettempdir(), f"bbshot-{int(time.time() * 1000)}.png")
    try:
        if os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                  "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
                  "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                  "$g=[System.Drawing.Graphics]::FromImage($i);"
                  "$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
                  f"$i.Save('{tmp}',[System.Drawing.Imaging.ImageFormat]::Png)")
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],  # noqa: S603, S607
                           capture_output=True, timeout=60)
        elif shutil.which("import"):
            subprocess.run(["import", "-window", "root", tmp], capture_output=True, timeout=60)  # noqa: S603, S607
        else:
            return {"ok": False, "text": "no way to picture the screen on this system"}
        with open(tmp, "rb") as f:
            data = f.read()
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "text": f"the picture was not taken: {e}"}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return {"ok": True, "text": "a picture of the screen", "picture": base64.b64encode(data).decode()}
