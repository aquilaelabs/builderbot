"""A scan job (R145): the node's own scanners over the projects whose node
this is, each SARIF sent up to the controller.

The controller's Scanners page deployed a compose project of the three
scanners here (a compose job: the file written, the images pulled); a run
is this job: the compose file written again beside the plan so what runs
is what the page says, each scanner run once as `compose run --rm` with
the node's copy of every listed project mounted read-only at /src/NAME,
and each report uploaded as `scan-put`, tagged with the projects it covers.
Nothing of the controller's is mounted here (R163): the report goes up
the agent's own API as a synced file does.
"""
import contextlib
import os
import re
import shutil
import time
import urllib.parse

from .base import log

SERVICES = ("semgrep", "trivy", "mobsfscan")


class ScanMixin:
    def scan(self, job, spec):
        if not shutil.which("docker"):
            job.say("refused: this node has no docker\n")
            return "failed", 78
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(spec.get("name") or "scanners"))
        cdir = os.path.join((self.state.get("stores") or {}).get("data") or "/tmp", "compose", name)
        who = self.drop_privileges({})
        self.own_dir(cdir, who)
        for fname, body in (spec.get("files") or {}).items():
            base = os.path.basename(str(fname)) or "file"
            with open(os.path.join(cdir, base), "w") as f:
                f.write(str(body))
        reports = os.path.join(cdir, "reports")
        os.makedirs(reports, exist_ok=True)
        # The projects whose node this is, as this node holds them: a copy
        # that is not here (not synced yet, or gone) is said and skipped.
        mounts, held, missing = [], [], []
        for p in (spec.get("projects") or [])[:200]:
            p = str(p)
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", p):
                continue
            top = self.wssync.top(p) if getattr(self, "wssync", None) else ""
            if top and os.path.isdir(top):
                mounts += ["-v", f"{top}:/src/{p}:ro"]
                held.append(p)
            else:
                missing.append(p)
        if missing:
            job.say(f"not here, so not scanned: {', '.join(missing)}\n")
        if not held:
            job.say("nothing to scan: none of the projects has a copy on this node\n")
            return "failed", 75
        job.say(f"scanning {', '.join(held)} with {', '.join(spec.get('scanners') or SERVICES)}\n")
        env = {k: v for k, v in os.environ.items() if k not in ("HOME", "USER", "LOGNAME")}
        failed = []
        sent = []
        for svc in (spec.get("scanners") or SERVICES):
            if svc not in SERVICES:
                continue
            if job.canceled:
                job.say("stopped\n")
                return "canceled", 130
            job.step(svc)
            out = os.path.join(reports, f"{svc}.sarif")
            with contextlib.suppress(OSError):
                os.unlink(out)
            argv = ["docker", "compose", "-f", os.path.join(cdir, "compose.yml"), "--profile", "scan", "run", "--rm",
                    *mounts, svc]
            job.say("$ " + " ".join(argv) + "\n")
            started = time.time()
            st, code = job.exec({"argv": argv, "cwd": cdir, "env": env, "timeout": int(spec.get("timeout") or 4 * 3600)})
            if st != "succeeded" or not os.path.isfile(out):
                job.say(f"   {svc} failed ({st}, exit {code}): its report, if any, is not sent\n")
                failed.append(svc)
                continue
            size = os.path.getsize(out)
            job.say(f"   {svc} wrote {size} bytes in {int(time.time() - started)}s; sending it up\n")
            q = urllib.parse.urlencode({"scanner": svc, "projects": ",".join(held)})
            try:
                rc, r = self.ctl.upload(f"scan-put?{q}", out, timeout=600)
            except Exception as e:                          # noqa: BLE001 (said on the job, not raised)
                rc, r = 0, {"error": str(e)}
            if rc != 200:
                job.say(f"   the controller did not take {svc}'s report: {r.get('error') or rc}\n")
                failed.append(svc)
                continue
            sent.append(svc)
            with contextlib.suppress(OSError):
                os.unlink(out)
        job.outputs.append({"kind": "scan", "projects": held, "sent": sent, "failed": failed})
        if failed:
            log(f"scan: {', '.join(failed)} failed on this node")
            return "failed", 1
        return "succeeded", 0
