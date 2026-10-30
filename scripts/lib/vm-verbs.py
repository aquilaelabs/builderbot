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
       bb vm new NAME --os OS [--vcpus N] [--mem 4G] [--disk 20] [--disks 100,500] [--node NODE] [--key FILE]
                 [--pin 2,3] [--mem-max 8G] [--share PATH [--ro]] [--autostart] [--node-agent] --why "what it is for"
       bb vm start|stop|restart|rm NAME [--force]
       bb vm snapshot NAME SNAP [--note "..."] | revert NAME SNAP | snapshot-rm NAME SNAP
       bb vm grow NAME [vda|vdb|vdc|vdd] GB | disk-add NAME GB | eject NAME
       bb vm hardware NAME [--pin 2,3|none] [--share-cpus] [--mem-max 8G|none] [--share PATH|none] [--ro]
       bb vm autostart NAME on|off
       bb vm devices [NODE]
       bb vm usb NAME give|take VENDOR:PRODUCT[:SERIAL] [--port 1-3]
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
              + (f"\n    {said}" if (said := hw_said(v)) else "")
              + (f"\n    {v['error']}" if v.get("error") else ""))


def hw_said(v):
    """What a VM was given beyond its size (R100), in the words its row uses."""
    hw, bits = v.get("hw") or {}, []
    if hw.get("cpuset"):
        bits.append(f"pinned to threads {', '.join(map(str, hw['cpuset']))}")
    if hw.get("mem_max_mb"):
        bits.append(f"memory up to {hw['mem_max_mb']} MB")
    if hw.get("net") == "lan":
        bits.append("on the LAN")
    if (hw.get("share") or {}).get("path"):
        sh = hw["share"]
        bits.append(f"sees {sh['path']}{' read-only' if sh.get('ro') else ''} as \"{sh.get('tag')}\" "
                    f"(mount -t virtiofs {sh.get('tag')} /mnt)")
    usb = v.get("usb") or []
    if usb:
        bits.append("USB: " + ", ".join(u.get("name") or f"{u['vendor'][2:]}:{u['product'][2:]}" for u in usb))
    rest = [d for d in hw.get("devices") or [] if d.get("type") != "usb"
            or not any(u.get("vendor") == d.get("vendor") and u.get("product") == d.get("product") for u in usb)]
    if rest:
        bits.append(f"{len(rest)} device(s) passed through")
    if v.get("autostart"):
        bits.append("starts with its host")
    return " · ".join(bits)


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


def hw_opts(rest, flags):
    """The hardware words of new and hardware: (the record to send, what is
    left). An option given is sent; one not given leaves the VM as it is."""
    hw, left = {}, []
    while rest:
        k = rest.pop(0)
        if k == "--ro":
            hw.setdefault("share", {})["ro"] = True
        elif k == "--share-cpus":
            hw["share_cpus"] = True
        elif k in ("--pin", "--mem-max", "--share", "--net") and rest:
            v = rest.pop(0)
            if k == "--pin":
                if v != "none" and not re.fullmatch(r"\d+(,\d+)*", v):
                    die(f"--pin is host threads like 2,3, or none: not {v}")
                hw["cpuset"] = [] if v == "none" else [int(c) for c in v.split(",")]
            elif k == "--mem-max":
                hw["mem_max_mb"] = 0 if v == "none" else mem_mb(v)
            elif k == "--share":
                hw["share"] = {} if v == "none" else {**hw.get("share", {}), "path": v.strip("/") or "."}
            else:
                hw["net"] = v
        elif k in flags:
            left.append(k)
        else:
            left += [k, rest.pop(0)] if rest and not rest[0].startswith("--") else [k]
    if "share" in hw and hw["share"] and "path" not in hw["share"]:
        die("--ro goes with --share PATH")
    return hw, left


def cmd_new(args):
    if not args or args[0].startswith("-"):
        die(USAGE)
    name, rest = args[0], args[1:]
    opts = {"os": "", "vcpus": "", "mem": "", "disk": "", "disks": "", "node": "", "key": "", "why": "", "user": ""}
    hw, rest = hw_opts(rest, ("--node-agent", "--autostart"))
    agent = "--node-agent" in rest
    autostart = "--autostart" in rest
    rest = [a for a in rest if a not in ("--node-agent", "--autostart")]
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
    if opts["disks"]:
        body["disks"] = [int(re.sub(r"[Gg][Bb]?$", "", d)) for d in opts["disks"].split(",") if d.strip()]
    if hw:
        body["hw"] = hw
    if autostart:
        body["autostart"] = True
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


def cmd_disk(verb, args):
    """grow NAME [DEV] GB, disk-add NAME GB, eject NAME: a stopped VM's
    disks and an installer's drive, as its row's More does."""
    if not args:
        die(USAGE)
    name, rest = args[0], args[1:]
    body = {"action": {"grow": "disk-grow"}.get(verb, verb), "name": name, "why": f"{verb} {name}"}
    if verb in ("grow", "disk-add"):
        if not rest or not re.fullmatch(r"\d+[Gg]?[Bb]?", rest[-1]):
            die(USAGE)
        body["gb"] = int(re.sub(r"[Gg]?[Bb]?$", "", rest[-1]))
        if verb == "grow":
            body["disk"] = rest[0] if len(rest) > 1 else "vda"
    job = answered(post(body), f"{verb} {name}")
    print(f"[builderbot] {verb} {name}: queued" + (f" as {job}" if job else ""))


def cmd_hardware(args):
    """A stopped VM's hardware beyond its size (R100), what is named and no
    more: --pin, --mem-max, --share, each none to take it off."""
    if not args or args[0].startswith("-"):
        die(USAGE)
    name = args[0]
    hw, left = hw_opts(list(args[1:]), ())
    if left or not hw:
        die(USAGE)
    job = answered(post({"action": "hardware", "name": name, "hw": hw, "why": f"hardware of {name}"}), f"{name}'s hardware")
    print(f"[builderbot] {name}'s hardware: queued" + (f" as {job}" if job else "") + "; it takes effect at its next start")


def cmd_devices(args):
    """The USB devices on this project's VM hosts (R116), each with what
    holds it, for a session to name one in bb vm usb."""
    d = read()
    hosts = [h for h in d.get("hosts") or [] if not args or h.get("name") == args[0] or h.get("id") == args[0]]
    if not hosts:
        die(f"no VM host called {args[0]}" if args else "no VM host yet")
    for h in hosts:
        usb = (h.get("hw") or {}).get("usb") or []
        print(f"{h['name']}: {len(usb)} USB device(s)" if usb else f"{h['name']}: no USB device reported")
        for u in usb:
            holder = next((v for v in d.get("vms") or [] if v.get("node") == h["id"]
                           and any(k.get("vendor") == u.get("vendor") and k.get("product") == u.get("product")
                                   and (not k.get("serial") or k.get("serial") == u.get("serial")) for k in v.get("usb") or [])), None)
            held = f"in {holder['project']}/{holder['name']}" if holder else ("the host's: " + "; ".join(u["use"])) if u.get("use") else "free"
            print(f"  {u['vendor'][2:]}:{u['product'][2:]}{':' + u['serial'] if u.get('serial') else ''}  {u.get('name') or '?':<40} "
                  f"port {u.get('port') or '?':<8} {held}")


def cmd_usb(args):
    """A USB device to a VM, or back (R116 step 6): always held for a person
    on the bell, since a device can be a disk or a key."""
    if len(args) < 3 or args[1] not in ("give", "take"):
        die(USAGE)
    name, verb, dev = args[0], args[1], args[2]
    m = re.fullmatch(r"([0-9a-f]{4}):([0-9a-f]{4})(?::([\w.:+/-]{1,64}))?", dev)
    if not m:
        die(f"a device is VENDOR:PRODUCT[:SERIAL] in hex, as bb vm devices lists it: not {dev}")
    usb = {"vendor": "0x" + m.group(1), "product": "0x" + m.group(2), "serial": m.group(3) or ""}
    rest = list(args[3:])
    if rest[:1] == ["--port"] and len(rest) > 1:
        usb["port"] = rest[1]
    elif rest:
        die(USAGE)
    r = post({"action": f"usb-{verb}", "name": name, "usb": usb, "why": f"{verb} {dev} {'to' if verb == 'give' else 'from'} {name}"})
    job = answered(r, f"{dev} {'to' if verb == 'give' else 'back from'} {name}")
    print(f"[builderbot] {dev} {'to' if verb == 'give' else 'back from'} {name}: queued" + (f" as {job}" if job else "")
          + "; a running VM has it now, a stopped one from its next start")


def cmd_autostart(args):
    if len(args) != 2 or args[1] not in ("on", "off"):
        die(USAGE)
    on = args[1] == "on"
    answered(post({"action": "autostart", "name": args[0], "on": on, "why": f"autostart {args[1]} for {args[0]}"}),
             f"{args[0]} starting with its host")
    print(f"[builderbot] {args[0]} {'starts' if on else 'no longer starts'} with its host")


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
    # The key own_key made and the hosts it met, named from $HOME as it made
    # them: ssh reads the Unix account's home from the password file, which
    # for an account's session is the shared session account's, where there
    # is no key and .ssh cannot be written (B307).
    home = os.path.expanduser("~/.ssh")
    key = os.path.join(home, "id_ed25519")
    pick = (["-i", key, "-o", "IdentitiesOnly=yes"] if os.path.isfile(key) else []) \
        + ["-o", f"UserKnownHostsFile={os.path.join(home, 'known_hosts')}"]
    os.execvp("ssh", ["ssh", *pick, "-o", "StrictHostKeyChecking=accept-new",
                      f"{v.get('user') or 'builder'}@{v['ip']}", *args[1:]])


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
    if verb in ("grow", "disk-add", "eject"):
        return cmd_disk(verb, args)
    if verb == "hardware":
        return cmd_hardware(args)
    if verb == "autostart":
        return cmd_autostart(args)
    if verb == "devices":
        return cmd_devices(args)
    if verb == "usb":
        return cmd_usb(args)
    if verb == "ip":
        return cmd_ip(args)
    if verb == "ssh":
        return cmd_ssh(args)
    die(USAGE)


if __name__ == "__main__":
    main()
