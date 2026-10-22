"""Behind every relayed verb on a node (bb_relay in bb, roadmap #24): the same
words sent to the controller's /api/v1/bb with the session's token, the
controller's own bb run in this project's tree, and what it printed printed
here, with its exit code. A git verb's network half ran there, in a
repository of its own (B148), and what this tree needs from it is applied
here, as this session.

Arguments: the auth header, then the bb words. BB_RELAY_PROJECT is the
project they are about.
"""
import os
import sys

import bbapi


auth, *argv = sys.argv[1:]
auth = auth or os.environ.get("BB_AUTH_HEADER", "")
project = os.environ.get("BB_RELAY_PROJECT", "")
# A verb that reads or changes the project's tree, which on the controller is
# its own copy: on a node holding a synced copy (R163), what was saved here
# goes up first, and what the verb changed comes back down before it is used.
TREE = {"git", "version", "changelog"}
tree = bool(argv) and argv[0] in TREE and bool(project)
if tree:
    import syncwait
    if not syncwait.up(project) and argv[0] == "git":
        sys.exit("[builderbot] ERROR: not sent: the controller's copy of this project is behind this one, "
                 "and git there would act on the older tree. Try again once the node is in step "
                 "(the Nodes page's Sessions section says each project's state)")
r = bbapi.call("/api/v1/bb", {"argv": argv, "project": project,
                              "cwd": os.getcwd(),
                              # A session of any coding agent (R95): Claude
                              # Code sets CLAUDECODE, bb-tty's launcher sets
                              # BB_AGENT for every agent, and which one rides
                              # along for the record to name.
                              "from": "session" if os.environ.get("CLAUDECODE") or os.environ.get("BB_AGENT") else "operator",
                              "agent": os.environ.get("BB_AGENT", "")},
               auth=auth, timeout=200)
if r.get("error") and "code" not in r:
    # The controller's own sentence, and nothing of how it traveled (B58).
    sys.exit(f"[builderbot] ERROR: {r['error']}")
if r.get("held"):
    # A push held for a person (R219): the flagged lines wait on the bell,
    # and this waits on the answer the way bb root run does; an approval
    # ran the push on the controller, and its outcome is what to print and
    # apply here.
    import waits
    sys.stderr.write(r.get("err") or "")
    sys.stderr.flush()
    o = waits.outcome(auth, r["held"], "the push was denied: the flagged lines were read and not approved")
    r = {"code": o.get("code") or 0, "out": o.get("out") or "", "err": "", "apply": o.get("apply")}
if tree and r.get("sync_rev"):
    syncwait.down(project, r["sync_rev"])
sys.stdout.write(r.get("out") or "")
sys.stderr.write(r.get("err") or "")
sys.stdout.flush()
sys.stderr.flush()
code = int(r.get("code") or 0)
ap = r.get("apply") if code == 0 else None
if isinstance(ap, dict):
    # git's network half ran on the controller, in a repository of its own
    # (B148); what this tree needs from it happens here, as this session:
    # the objects a fetch brought, the refs that moved, an upstream a push -u
    # set, and the merge or rebase that finishes a pull.
    import contextlib, subprocess                               # noqa: E401
    def git(*args, text=None):
        return subprocess.run(["git", *args], input=text, capture_output=text is not None,
                              text=True, check=False)
    bundle = ap.get("bundle") or ""
    if bundle:
        u = subprocess.run(["git", "bundle", "unbundle", bundle], capture_output=True, text=True, check=False)
        with contextlib.suppress(OSError):
            os.remove(bundle)
        if u.returncode:
            sys.exit(f"{u.stderr}[builderbot] ERROR: the objects the controller fetched did not go into this tree")
    lines = "".join(f"update {n} {v}\n" if v else f"delete {n}\n" for n, v in ap.get("refs") or [])
    if lines:
        u = git("update-ref", "--stdin", text=lines)
        if u.returncode:
            sys.exit(f"{u.stderr}[builderbot] ERROR: the refs the controller moved did not move here")
    for branch, remote, merge in ap.get("upstream") or []:
        git("config", f"branch.{branch}.remote", remote)
        git("config", f"branch.{branch}.merge", merge)
    m = ap.get("merge")
    if isinstance(m, dict) and m.get("ref"):
        mode = m.get("mode") or ""
        if not mode:
            ask = lambda k: git("config", "--type=bool", "--get", k, text="").stdout.strip()  # noqa: E731
            mode = "rebase" if "true" in (ask(f"branch.{m.get('branch')}.rebase"), ask("pull.rebase")) else "merge"
        step = (["rebase", m["ref"]] if mode == "rebase"
                else ["merge", "--no-edit", *(["--ff-only"] if mode == "ff-only" else []), m["ref"]])
        code = subprocess.run(["git", *step], check=False).returncode
sys.exit(code)
