"""Behind `bb vm` (cmd_vm in bb): a project's VMs (R91), made, listed, started,
stopped, snapshotted and removed through /api/vms. A session works on its own
project's under its Make VMs dial: deny refuses, ask waits for the
administrators on their bell, auto does it now. A new VM is made from an OS
in the catalog (bb vm os) and lets in the session's own ssh key, made here
when the session has none.

BB_VM_AUTH is the auth header and BB_VM_PROJECT the project; the rest is
argv: the verb, then its words.
"""
import os
import re
import subprocess
import sys
import time

import bbapi
import waits

AUTH = os.environ.get("BB_VM_AUTH", "")
PROJECT = os.environ.get("BB_VM_PROJECT", "")
USAGE = """usage: bb vm [list]
       bb vm os
       bb vm new NAME --os OS [--vcpus N] [--mem 4G] [--disk 20] [--node NODE] [--key FILE] [--node-agent] --why "what it is for"
       bb vm start|stop|restart|rm NAME [--force]
       bb vm snapshot NAME SNAP [--note "..."] | revert NAME SNAP | snapshot-rm NAME SNAP
       bb vm ip NAME | ssh NAME [COMMAND...]"""


def die(msg):
    print(f"[builderbot] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def read():
    d = bbapi.call("/api/vms", auth=AUTH)
    if d.get("error"):
        die(d["error"])
    return d


def mine(d, name):
    return next((v for v in d.get("vms") or [] if v.get("project") == PROJECT and v.get("name") == name), None)


def cmd_list(_args):
    d = read()
    rows = [v for v in d.get("vms") or [] if v.get("project") == PROJECT]
    if not rows:
        hosts = ", ".join(h["name"] for h in d.get("hosts") or []) or "none yet (a node's Features section installs VM host)"
        print(f"{PROJECT} has no VM. VM hosts: {hosts}")
        return
    for v in rows:
        snaps = v.get("snapshots") or []
        print(f"{v['name']:<20} {v.get('state', '?'):<9} {v.get('os', ''):<13} {v.get('node_name', ''):<16} "
              f"{v.get('ip') or '-':<15} {v.get('vcpus')} vCPU {v.get('mem_mb')} MB {v.get('disk_gb')} GB"
              + (f"  snapshots: {', '.join(snaps)}" if snaps else "")
              + (f"\n    {v['error']}" if v.get("error") else ""))


def cmd_os(_args):
    for i in read().get("images") or []:
        print(f"{i['id']:<14} {i['name']}" + (f"  (a person's: {i.get('why')})" if i.get("person") else ""))


def mem_mb(s):
    m = re.fullmatch(r"(\d+)\s*([GgMm]?)[Bb]?", str(s).strip())
    if not m:
        die(f"--mem is a size like 4G or 2048: not {s}")
    return int(m.group(1)) * (1024 if m.group(2).lower() == "g" else 1)


def own_key(path):
    """The session's public key: the one named, else ~/.ssh/id_ed25519.pub,
    made now when there is none, so the VM lets this session in."""
    if path:
        if not os.path.isfile(path):
            die(f"no such key file: {path}")
        return open(path, encoding="utf-8").read().strip()
    home = os.path.expanduser("~/.ssh")
    pub = os.path.join(home, "id_ed25519.pub")
    if not os.path.isfile(pub):
        os.makedirs(home, mode=0o700, exist_ok=True)
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"builderbot {PROJECT}",
                            "-f", pub[:-4]], capture_output=True, text=True, check=False)
        if r.returncode:
            die(f"could not make an ssh key for the VM: {r.stderr.strip()}")
        print(f"[builderbot] made {pub[:-4]} for the VM to let this session in", file=sys.stderr)
    return open(pub, encoding="utf-8").read().strip()


def post(body):
    return bbapi.call("/api/vms", {"project": PROJECT, **body}, auth=AUTH)


def answered(r, what):
    """An answer: an ask waits for its outcome; the rest is said."""
    if r.get("error"):
        die(r["error"])
    if r.get("id") and not r.get("job"):
        print(f"[builderbot] asked {r.get('to') or 'the administrators'} (#{r['id']}): {what} is on their bell, "
              "waiting up to 15 minutes for Allow (Make VMs is ask)", file=sys.stderr)
        o = waits.outcome(AUTH, r["id"], "denied on the dashboard; nothing ran")
        if o.get("code"):
            die(o.get("out") or "refused")
        print(f"[builderbot] allowed: {o.get('out')}")
        return o.get("out")
    return r.get("job")


def wait_state(name, until, minutes=30):
    """Wait for the VM's record to leave `until`, saying where it is."""
    end = time.time() + minutes * 60
    said = ""
    while time.time() < end:
        v = mine(read(), name)
        if v is None:
            return None
        st = v.get("state") or ""
        if st != said:
            print(f"[builderbot] {name}: {st}", file=sys.stderr)
            said = st
        if st not in until:
            return v
        time.sleep(5)
    die(f"{name} is still {said} after {minutes} minutes: the job on the Jobs page says where it is")


def cmd_new(args):
    if not args or args[0].startswith("-"):
        die(USAGE)
    name, rest = args[0], args[1:]
    opts = {"os": "", "vcpus": "", "mem": "", "disk": "", "node": "", "key": "", "why": "", "user": ""}
    agent = "--node-agent" in rest
    rest = [a for a in rest if a != "--node-agent"]
    while rest:
        k = rest.pop(0)
        if k.lstrip("-") not in opts or not rest:
            die(USAGE)
        opts[k.lstrip("-")] = rest.pop(0)
    if not opts["os"]:
        die("bb vm new needs --os: bb vm os lists what there is")
    if not opts["why"]:
        die('bb vm new needs --why "what it is for": a person may read it before allowing')
    body = {"action": "new", "name": name, "os": opts["os"], "node": opts["node"], "why": opts["why"],
            "keys": [own_key(opts["key"])], "user": opts["user"] or "builder", "node_agent": agent}
    if opts["vcpus"]:
        body["vcpus"] = int(opts["vcpus"])
    if opts["mem"]:
        body["mem_mb"] = mem_mb(opts["mem"])
    if opts["disk"]:
        body["disk_gb"] = int(re.sub(r"[Gg][Bb]?$", "", opts["disk"]))
    answered(post(body), f"a new VM, {name}")
    v = wait_state(name, ("making",))
    if not v or v.get("state") == "failed":
        die(f"{name} was not made: {(v or {}).get('error') or 'its job on the Jobs page says why'}")
    print(f"[builderbot] {name} is made on {v.get('node_name')}: bb vm ssh {name} once it has its address (bb vm list)")


def cmd_action(verb, args):
    if not args:
        die(USAGE)
    name = args[0]
    body = {"action": {"rm": "remove"}.get(verb, verb), "name": name, "why": f"{verb} {name}"}
    if verb in ("snapshot", "revert", "snapshot-rm"):
        if len(args) < 2:
            die(USAGE)
        body["snapshot"] = args[1]
        if "--note" in args[2:]:
            body["note"] = args[args.index("--note") + 1] if args.index("--note") + 1 < len(args) else ""
    if "--force" in args:
        body["force"] = True
    job = answered(post(body), f"{verb} {name}")
    print(f"[builderbot] {verb} {name}: queued" + (f" as {job}" if job else ""))


def cmd_ip(args):
    v = mine(read(), args[0] if args else "")
    if not v:
        die(f"{PROJECT} has no VM called {args[0] if args else '?'}")
    if not v.get("ip"):
        die(f"{v['name']} has no address yet ({v.get('state')}): it takes one once it has booted")
    print(v["ip"])
    return v


def cmd_ssh(args):
    v = cmd_ip(args[:1]) if args else die(USAGE)
    os.execvp("ssh", ["ssh", "-o", "StrictHostKeyChecking=accept-new", f"{v.get('user') or 'builder'}@{v['ip']}", *args[1:]])


def main():
    argv = sys.argv[1:]
    verb = argv[0] if argv else "list"
    args = argv[1:]
    if verb in ("list", "ls"):
        return cmd_list(args)
    if verb == "os":
        return cmd_os(args)
    if verb == "new":
        return cmd_new(args)
    if verb in ("start", "stop", "restart", "rm", "remove", "snapshot", "revert", "snapshot-rm"):
        return cmd_action("rm" if verb == "remove" else verb, args)
    if verb == "ip":
        return cmd_ip(args)
    if verb == "ssh":
        return cmd_ssh(args)
    die(USAGE)


if __name__ == "__main__":
    main()
