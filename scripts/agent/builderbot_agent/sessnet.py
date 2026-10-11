"""Each session kept to its own project's network (R79): the tables, the firewall and the session account's sudoers."""
import contextlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from .base import (
    DOCKER_BIN,
    FIREWALL_CMD,
    IPTABLES_BIN,
    NFT_BIN,
    RESOLV_UPSTREAM,
    RUNNER_DIR,
    SESSION_BIN,
    SESSION_SUDOERS,
    SESSNET_CIDR,
    SESSNET_DIR,
    SESSNET_LOCAL,
    SESSNET_MARK,
    SESSNET_TABLE,
    _run,
    log,
)
from .stores import tc_root
from .backends import _have


def session_sudoers(user):
    """The sudo rule that lets the session account start a session inside its
    project's view, and nothing else. !use_pty keeps the session on the pane's
    own terminal rather than a pty sudo would relay."""
    return (f"# Written by the BuilderBot agent (R35): the one command {user} may run as root,\n"
            f"# which starts a session inside a view of this node that holds only its project.\n"
            f"Defaults!{SESSION_BIN} !use_pty, !lecture\n"
            f"{user} ALL=(root) NOPASSWD: {SESSION_BIN}\n")


def session_conf(state, user, net=False):
    """This machine's layout for bb-session: the session account and the
    stores whose other projects' parts a session's view leaves out, and,
    once the table is in place, that each session gets a network of its own
    (R79). Off, the lines are not written at all, so an older bb-session
    reads the file it always read."""
    stores = state.get("stores") or {}
    return (f"# Written by the BuilderBot agent (R35) for bb-session.\n"
            f"SESSION_USER={user}\n"
            f"WORKSPACE=/workspace\n"
            f"DATA_STORE={stores.get('data') or ''}\n"
            f"ARTIFACTS_STORE={stores.get('artifacts') or ''}\n"
            f"TOOLCHAINS_STORE={tc_root(state)}\n"
            f"RUNNER_DIR={RUNNER_DIR}\n"
            f"HIDE=/devdata\n"
            + (f"SESSION_NET=on\nSESSION_NET_CIDR={SESSNET_CIDR}\n" if net else ""))


def isolation_now():
    """Whether a session here runs inside a view of its own project (R35), and
    why not when it does not: asked of the helper itself, which makes the
    namespaces a view needs and lets them go."""
    if os.geteuid() != 0:
        return {"sessions": False, "why": "the agent does not run as root here, so it cannot set up a view"}
    if not os.access(SESSION_BIN, os.X_OK):
        return {"sessions": False, "why": "bb-session is not installed on this machine"}
    if not os.path.isfile(SESSION_SUDOERS):
        return {"sessions": False, "why": "the session account has no sudo rule for bb-session"}
    if not shutil.which("sudo"):
        return {"sessions": False, "why": "sudo is not installed on this machine"}
    try:
        r = subprocess.run([SESSION_BIN, "check"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"sessions": False, "why": f"bb-session did not run: {e}"[:200]}
    if r.returncode:
        return {"sessions": False, "why": ((r.stderr or r.stdout).strip() or "bb-session check failed")[:200]}
    return {"sessions": True, "why": ""}


# ---------------------------------------------------------------------------
# each session kept to its own project's network (R79)
#
# bb-session gives the session a network namespace and a veth to the node,
# addressed from SESSNET_CIDR, and writes which project the address is; this
# agent keeps the table that judges what leaves by it. Allowed: the internet,
# the controller, the resolvers, and the containers the controller says the
# project owns here. Refused: everything else that is not the internet,
# which is every other container, the node itself, and the LAN.

SESSNET_STATUS = {}          # what the census says about it, kept by SessionNet


def sessnet_resolvers(paths=RESOLV_UPSTREAM):
    """The nameservers a session's own network can reach, and the search line:
    the node's upstream ones (the list systemd-resolved asks, where it runs),
    IPv4 and not the node's loopback, which a namespace of its own does not
    share."""
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        ns, search = [], ""
        for line in text.splitlines():
            bits = line.split()
            if len(bits) >= 2 and bits[0] == "nameserver":
                try:
                    a = ipaddress.ip_address(bits[1])
                except ValueError:
                    continue
                if a.version == 4 and not a.is_loopback and not a.is_unspecified:
                    ns.append(str(a))
            elif len(bits) >= 2 and bits[0] in ("search", "domain") and not search:
                search = " ".join(b for b in bits[1:] if re.fullmatch(r"[A-Za-z0-9.-]+", b))
        if ns:
            return ns[:3], search
    return [], ""


def sessnet_resolv_text(ns, search):
    return ("# Written by the BuilderBot agent (R79): the resolvers a session's own network reaches.\n"
            + "".join(f"nameserver {n}\n" for n in ns)
            + (f"search {search}\n" if search and search != "." else ""))


def sessnet_clash(addrs, routes, cidr=SESSNET_CIDR):
    """What on this node already uses the range sessions are addressed from,
    or "": an address or a route (from `ip -j -4 addr` and `ip -j -4 route
    show table all`) other than a session's own link. A session's /30 would
    hide its addresses from everything on the machine, and the masquerade
    would rewrite its traffic, which on a machine used for other things is
    somebody else's network (the operator, 24 Sep)."""
    net = ipaddress.ip_network(cidr)
    for a in addrs if isinstance(addrs, list) else []:
        if not isinstance(a, dict) or str(a.get("ifname") or "").startswith("bbs"):
            continue
        for i in a.get("addr_info") or []:
            if not isinstance(i, dict) or i.get("family") != "inet" or not i.get("local"):
                continue
            try:
                n = ipaddress.ip_network(f"{i['local']}/{i.get('prefixlen', 32)}", strict=False)
            except ValueError:
                continue
            if n.overlaps(net):
                return f"{i['local']}/{i.get('prefixlen', 32)} on {a.get('ifname')}"
    for r in routes if isinstance(routes, list) else []:
        if not isinstance(r, dict) or str(r.get("dev") or "").startswith("bbs"):
            continue
        dst = str(r.get("dst") or "")
        if dst in ("", "default"):
            continue
        try:
            n = ipaddress.ip_network(dst if "/" in dst else dst + "/32", strict=False)
        except ValueError:
            continue
        if n.version == 4 and n.overlaps(net):
            return f"a route to {dst}" + (f" on {r['dev']}" if r.get("dev") else "")
    return ""


def sessnet_can():
    """Whether this node can keep each session to its own project's network,
    and why not: asked in the order a person would put it right."""
    if os.geteuid() != 0:
        return False, "the agent does not run as root here"
    if not (os.access(SESSION_BIN, os.X_OK) and os.path.isfile(SESSION_SUDOERS)):
        return False, "sessions here do not start through bb-session, so there is no namespace to give them"
    try:
        r = subprocess.run([SESSION_BIN, "check-net"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"bb-session did not run: {e}"[:200]
    if r.returncode:
        said = (r.stderr or r.stdout).strip()
        if "takes check" in said and "check-net" not in said:
            return False, "the bb-session here is older than this setting; the next bundle brings it"
        return False, (said or "bb-session check-net failed")[:200]
    if not _have(NFT_BIN):
        return False, "nftables (nft) is not installed here"
    if _have(FIREWALL_CMD) and _run([FIREWALL_CMD, "--state"]) == "running":
        return False, "firewalld owns this node's firewall, which this setting does not go through yet"
    if _have("ufw") and _run(["ufw", "status"]).startswith("Status: active"):
        return False, "ufw owns this node's firewall, which this setting does not go through yet"
    try:
        with open("/proc/sys/net/ipv4/ip_forward", encoding="ascii") as f:
            if f.read().strip() != "1":
                return False, "IPv4 forwarding is off on this node (net.ipv4.ip_forward)"
    except OSError:
        return False, "this node's IPv4 forwarding setting could not be read"
    if shutil.which(DOCKER_BIN) and not _have(IPTABLES_BIN):
        return False, "iptables is not here to let a session's traffic past Docker's forwarding"
    if not sessnet_resolvers()[0]:
        return False, "the node names no DNS server a session's own network could reach, only its loopback"
    try:
        addrs = json.loads(_run(["ip", "-j", "-4", "addr"], timeout=10) or "[]")
        routes = json.loads(_run(["ip", "-j", "-4", "route", "show", "table", "all"], timeout=10) or "[]")
    except ValueError:
        addrs, routes = [], []
    clash = sessnet_clash(addrs, routes)
    if clash:
        return False, f"this node's own network already uses {SESSNET_CIDR}, which sessions are addressed from ({clash})"
    return True, ""


def sessnet_table(cidr=SESSNET_CIDR, mark=SESSNET_MARK):
    """The table, whole. Judged at the node, on the way out of a session's
    link, before Docker's own forwarding (priority -10 against its 0); the
    sets are filled by sessnet_fill. What passes is marked, and Docker's
    DOCKER-USER lets through marked traffic from a session and drops the
    rest, so without this table a session reaches nothing. Nothing starts a
    connection into a session: not from the network (forward) and not from
    the node itself (output), where every other account's programs are.
    The controller and the resolvers are let through on the way INTO the
    node as well, for a node that is the controller's own machine or runs
    the resolver, and by the destination a DNAT started from, for a
    controller Docker publishes on this node."""
    return f"""table inet {SESSNET_TABLE} {{
	set ctl {{ type ipv4_addr . inet_service; }}
	set dns {{ type ipv4_addr; }}
	set own {{ type ipv4_addr . ipv4_addr; }}
	set peers {{ type ipv4_addr . ipv4_addr . inet_service; }}
	set hosts {{ type ipv4_addr . ipv4_addr; }}
	set local {{ type ipv4_addr; flags interval; elements = {{ {", ".join(SESSNET_LOCAL)} }}; }}
	chain forward {{
		type filter hook forward priority -10; policy accept;
		iifname "bbs*" jump outbound
		oifname "bbs*" ct state established,related accept
		oifname "bbs*" drop
	}}
	chain outbound {{
		ip saddr != {cidr} drop
		meta nfproto ipv6 drop
		ct state established,related goto pass
		ip daddr . tcp dport @ctl goto pass
		ct original ip daddr . ct original proto-dst @ctl goto pass
		ip daddr @dns udp dport 53 goto pass
		ip daddr @dns tcp dport 53 goto pass
		ip saddr . ip daddr @own goto pass
		ip saddr . ip daddr . tcp dport @peers goto pass
		ip saddr . ip daddr . udp dport @peers goto pass
		ip saddr . ip daddr @hosts goto pass
		ip daddr @local reject with icmpx type admin-prohibited
		goto pass
	}}
	chain pass {{
		meta mark set meta mark or {mark:#x} accept
	}}
	chain input {{
		type filter hook input priority -10; policy accept;
		iifname "bbs*" ct state established,related accept
		iifname "bbs*" ip daddr . tcp dport @ctl accept
		iifname "bbs*" ip daddr @dns udp dport 53 accept
		iifname "bbs*" ip daddr @dns tcp dport 53 accept
		iifname "bbs*" reject with icmpx type admin-prohibited
	}}
	chain output {{
		type filter hook output priority -10; policy accept;
		oifname "bbs*" meta l4proto {{ tcp, udp }} ct state new reject with icmpx type admin-prohibited
	}}
	chain postrouting {{
		type nat hook postrouting priority 100; policy accept;
		ip saddr {cidr} oifname != "bbs*" masquerade
	}}
}}
"""


def sessnet_fill(ctl, dns, own, peers=(), hosts=()):
    """The sets, replaced in one transaction: the controller's address and
    port, the resolvers, (session address, container address) for every
    container each session's project owns here, and (R82) what its project
    has on its other nodes: (session, node address, published port) for a
    container there, (session, node address) for a Mac or Windows node,
    which has no containers to narrow to and is reached whole."""
    t = f"inet {SESSNET_TABLE}"
    out = [f"flush set {t} ctl", f"flush set {t} dns", f"flush set {t} own",
           f"flush set {t} peers", f"flush set {t} hosts"]
    if ctl:
        out.append(f"add element {t} ctl {{ {', '.join(f'{a} . {p}' for a, p in ctl)} }}")
    if dns:
        out.append(f"add element {t} dns {{ {', '.join(dns)} }}")
    if own:
        out.append(f"add element {t} own {{ {', '.join(f'{a} . {b}' for a, b in own)} }}")
    if peers:
        out.append(f"add element {t} peers {{ {', '.join(f'{a} . {b} . {p}' for a, b, p in peers)} }}")
    if hosts:
        out.append(f"add element {t} hosts {{ {', '.join(f'{a} . {b}' for a, b in hosts)} }}")
    return "\n".join(out) + "\n"


def sessnet_sessions(d=SESSNET_DIR):
    """The sessions bb-session gave a network to, from their files: which
    project each address is. One whose link has gone is over, whatever its
    file says, and is left out."""
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    net = ipaddress.ip_network(SESSNET_CIDR)
    for name in sorted(names):
        if not re.fullmatch(r"s\d+\.json", name):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                r = json.load(f)
            addr = ipaddress.ip_address(str(r.get("addr") or ""))
        except (OSError, ValueError):
            continue
        link, project = str(r.get("if") or ""), str(r.get("project") or "")
        if (addr in net and re.fullmatch(r"bbs\d{1,5}", link) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", project)
                and os.path.exists(f"/sys/class/net/{link}")):
            out.append({"addr": str(addr), "if": link, "project": project})
    return out


def sessnet_containers():
    """Every running container here: its name, its compose project and its
    addresses on Docker's networks. One ps and one inspect."""
    ids = _run([DOCKER_BIN, "ps", "-q"], timeout=15).split()
    if not ids or not all(re.fullmatch(r"[0-9a-f]{6,64}", i) for i in ids):
        return []
    try:
        p = subprocess.run([DOCKER_BIN, "inspect", *ids[:500]], capture_output=True, text=True,
                           timeout=30, check=False)
        rows = json.loads(p.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    out = []
    for c in rows if isinstance(rows, list) else []:
        labels = (c.get("Config") or {}).get("Labels") or {}
        nets = (c.get("NetworkSettings") or {}).get("Networks") or {}
        ips = set()
        for n in nets.values():
            with contextlib.suppress(ValueError):
                if isinstance(n, dict) and n.get("IPAddress"):
                    ips.add(str(ipaddress.IPv4Address(str(n["IPAddress"]))))
        # The bridges it is on (R178): a compose network is a user-defined
        # bridge whose interface is br- and the first twelve of its id; the
        # default network's is docker0.
        bridges = set()
        for name, n in nets.items():
            nid = str((n or {}).get("NetworkID") or "") if isinstance(n, dict) else ""
            if name == "bridge":
                bridges.add("docker0")
            elif re.fullmatch(r"[0-9a-f]{12,64}", nid):
                bridges.add("br-" + nid[:12])
        # ...and the host ports it publishes, for the node's own ports a
        # container may reach by the node's address (R178).
        ports = set()
        for binds in ((c.get("NetworkSettings") or {}).get("Ports") or {}).values():
            for b in binds or []:
                with contextlib.suppress(ValueError, TypeError):
                    hp = int((b or {}).get("HostPort") or 0)
                    if 0 < hp < 65536:
                        ports.add(hp)
        out.append({"name": str(c.get("Name") or "").lstrip("/"),
                    "compose": str(labels.get("com.docker.compose.project") or ""),
                    "ips": sorted(ips), "bridges": sorted(bridges), "ports": sorted(ports)})
    return out


def sessnet_pairs(sessions, own, containers):
    """(session address, container address) for every session and every
    container its project owns here: by compose project for an instance
    BuilderBot runs, by name for one the operator gave the project."""
    addrs = {}
    for project, o in (own or {}).items():
        if not isinstance(o, dict):
            continue
        comp = {str(x) for x in o.get("compose") or [] if x}
        names = {str(x) for x in o.get("names") or [] if x}
        addrs[project] = {ip for c in containers if c["compose"] in comp or c["name"] in names
                          for ip in c["ips"]}
    return sorted({(s["addr"], ip) for s in sessions for ip in addrs.get(s["project"], ())})


def sessnet_peers(sessions, own):
    """(session address, node address, port) for every session and every
    published port its project's containers hold on the project's other
    nodes (R82): the controller names them per project as `peers`."""
    out = set()
    for s in sessions:
        o = (own or {}).get(s["project"])
        for pair in (o.get("peers") or []) if isinstance(o, dict) else []:
            try:
                addr, port = str(ipaddress.IPv4Address(str(pair[0]))), int(pair[1])
            except (ValueError, TypeError, IndexError):
                continue
            if 0 < port < 65536:
                out.add((s["addr"], addr, port))
    return sorted(out)


def sessnet_hosts(sessions, own):
    """(session address, node address) for every session and every node of
    its project that is reached whole (R82): a Mac or Windows node, or a
    guest, which has no containers to narrow to."""
    out = set()
    for s in sessions:
        o = (own or {}).get(s["project"])
        for a in (o.get("hosts") or []) if isinstance(o, dict) else []:
            with contextlib.suppress(ValueError, TypeError):
                out.add((s["addr"], str(ipaddress.IPv4Address(str(a)))))
    return sorted(out)


def sessnet_ctl(url):
    """The controller's IPv4 addresses and port, which every session reaches."""
    u = urllib.parse.urlsplit(url or "")
    if not u.hostname:
        return []
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(u.hostname, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    return sorted({(i[4][0], port) for i in infos})


# ---- each project's containers kept to their own network (R178) ------------
#
# Measured on the dev pair (11 Oct): a container reaches another project's
# container through the node's address (its published port, after Docker's
# DNAT: forward from one bridge to the other), and the node's own ports
# (sshd); its bridge address is already dropped by Docker's isolation. So a
# second table judges those two paths for every compose bridge: forward from
# a bridge passes to its own bridge, to the bridges of the projects its
# owner reads, the controller, DNS and the internet, and is dropped to any
# other bridge and rejected to the private ranges; into the node it passes
# to the controller, DNS, 80 and 443 (nginx, the way in) and the node's
# published ports of its own project and the projects it reads, and is
# rejected otherwise. Nothing is marked: nothing of Docker's reads a mark on
# this path, and a missing table leaves Docker's own rules, which is what
# the row says (not in force), never a container cut off.

CTRNET_TABLE = "builderbot_ctrnet"


def ctrnet_table():
    """The table, whole; the sets are filled by ctrnet_fill."""
    return f"""table inet {CTRNET_TABLE} {{
	set bridges {{ typeof iifname; }}
	set pairs {{ typeof iifname . oifname; }}
	set ownports {{ typeof iifname . tcp dport; }}
	set ctl {{ type ipv4_addr . inet_service; }}
	set dns {{ type ipv4_addr; }}
	set local {{ type ipv4_addr; flags interval; elements = {{ {", ".join(SESSNET_LOCAL)} }}; }}
	chain forward {{
		type filter hook forward priority -10; policy accept;
		iifname @bridges jump outbound
	}}
	chain outbound {{
		ct state established,related accept
		meta nfproto ipv6 drop
		iifname . oifname @pairs accept
		oifname @bridges drop
		ip daddr . tcp dport @ctl accept
		ct original ip daddr . ct original proto-dst @ctl accept
		ip daddr @dns udp dport 53 accept
		ip daddr @dns tcp dport 53 accept
		ip daddr @local reject with icmpx type admin-prohibited
		accept
	}}
	chain input {{
		type filter hook input priority -10; policy accept;
		iifname @bridges ct state established,related accept
		iifname @bridges ip daddr . tcp dport @ctl accept
		iifname @bridges ip daddr @dns udp dport 53 accept
		iifname @bridges ip daddr @dns tcp dport 53 accept
		iifname @bridges tcp dport {{ 80, 443 }} accept
		iifname @bridges iifname . tcp dport @ownports accept
		iifname @bridges meta l4proto {{ tcp, udp }} reject with icmpx type admin-prohibited
	}}
}}
"""


def ctrnet_reach(containers, ctr):
    """What the table's sets hold, from the containers here and the
    controller's map {compose project: {owner, to: [compose projects]}}:
    every compose bridge, the (from, to) bridge pairs a container may
    cross (its own bridge among them), and the (bridge, host port) pairs
    of the published ports it may reach by the node's address. A compose
    project the controller does not name reaches its own bridge and ports
    and nothing of the others'."""
    by = {}
    for c in containers:
        if c.get("compose"):
            e = by.setdefault(c["compose"], {"bridges": set(), "ports": set()})
            e["bridges"].update(c.get("bridges") or [])
            e["ports"].update(c.get("ports") or [])
    bridges = sorted({b for e in by.values() for b in e["bridges"]})
    pairs, ports = set(), set()
    for comp, e in by.items():
        to = {comp} | {str(x) for x in ((ctr or {}).get(comp) or {}).get("to") or []}
        # BuilderBot's own (R180, the controller's `all`): every compose
        # project here, the ones the controller never heard of included.
        if ((ctr or {}).get(comp) or {}).get("all"):
            to |= set(by)
        for b in e["bridges"]:
            for other in to:
                for b2 in by.get(other, {}).get("bridges", ()):
                    pairs.add((b, b2))
                for hp in by.get(other, {}).get("ports", ()):
                    ports.add((b, hp))
    return bridges, sorted(pairs), sorted(ports)


def ctrnet_fill(bridges, pairs, ports, ctl, dns):
    """The sets, replaced in one transaction."""
    t = f"inet {CTRNET_TABLE}"
    out = [f"flush set {t} bridges", f"flush set {t} pairs", f"flush set {t} ownports",
           f"flush set {t} ctl", f"flush set {t} dns"]
    q = '"%s"'.__mod__
    if bridges:
        out.append(f"add element {t} bridges {{ {', '.join(q(b) for b in bridges)} }}")
    if pairs:
        out.append(f"add element {t} pairs {{ {', '.join(q(a) + ' . ' + q(b) for a, b in pairs)} }}")
    if ports:
        out.append(f"add element {t} ownports {{ {', '.join(q(b) + ' . ' + str(p) for b, p in ports)} }}")
    if ctl:
        out.append(f"add element {t} ctl {{ {', '.join(f'{a} . {p}' for a, p in ctl)} }}")
    if dns:
        out.append(f"add element {t} dns {{ {', '.join(dns)} }}")
    return "\n".join(out) + "\n"


def ctrnet_can():
    """Whether this node can keep its containers apart: nft and Docker here."""
    if not _have(NFT_BIN):
        return False, "nftables is not installed on this node"
    if not shutil.which(DOCKER_BIN):
        return False, "Docker is not on this node"
    return True, ""


# The three rules in Docker's DOCKER-USER that let a session's traffic past
# Docker's forwarding, in this order: replies back in, what the table marked
# on its way out, and nothing else from a session.
DOCKER_USER_RULES = (
    ["-o", "bbs+", "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
    ["-i", "bbs+", "-m", "mark", "--mark", f"{SESSNET_MARK:#x}/{SESSNET_MARK:#x}", "-j", "ACCEPT"],
    ["-i", "bbs+", "-j", "DROP"],
)


def docker_user(on):
    """Put the three rules in DOCKER-USER, or take them out. Where Docker is
    not running there is no such chain and nothing to do. Any of ours out of
    place and they all go and come back in order, since a drop that lands
    first would cut every session off."""
    if not _have(IPTABLES_BIN):
        return ""
    ipt = [IPTABLES_BIN, "-w", "5"]
    listing = subprocess.run(ipt + ["-S", "DOCKER-USER"], capture_output=True, text=True, timeout=15, check=False)
    if listing.returncode:
        return ""
    ours = [ln for ln in listing.stdout.splitlines() if "bbs+" in ln]

    def kind(ln):
        if "-o bbs+" in ln and "conntrack" in ln and "ACCEPT" in ln:
            return 1
        if "-i bbs+" in ln and "--mark" in ln and "ACCEPT" in ln:
            return 2
        return 3 if "-i bbs+" in ln and "DROP" in ln else 0
    if on and [kind(ln) for ln in ours] == [1, 2, 3]:
        return ""
    if not on and not ours:
        return ""
    for rule in DOCKER_USER_RULES:
        while subprocess.run(ipt + ["-C", "DOCKER-USER", *rule], capture_output=True, timeout=15,
                             check=False).returncode == 0:
            subprocess.run(ipt + ["-D", "DOCKER-USER", *rule], capture_output=True, timeout=15, check=False)
    if on:
        for rule in reversed(DOCKER_USER_RULES):
            r = subprocess.run(ipt + ["-I", "DOCKER-USER", "1", *rule], capture_output=True, text=True,
                               timeout=15, check=False)
            if r.returncode:
                return (r.stderr or r.stdout).strip()[:200] or "iptables refused a rule"
    return ""


class SessionNet:
    """Each session kept to its own project's network, where the controller
    asks for it and this node can (R79). A thread of its own: a session that
    has just started should reach its own containers within seconds, and the
    main loop turns over once a long-poll.

    The order is what keeps it closed. On: the table, then Docker's rules,
    the resolver file and the sets, and last the ready mark. The layout file
    says on as soon as it is wanted and this node can; bb-session then starts
    a session only while the mark is there, so one started before the rules
    are is refused and pointed at the row, never given the node's network.
    Off: the layout file first, so no new session gets a namespace; the rules
    stay while a session that has one is alive, since without them it has no
    network at all, and go with the last."""

    def __init__(self, agent):
        self.agent = agent
        self.can = (False, "")
        self.can_at = 0.0
        self.containers = []
        self.containers_at = 0.0
        self.seen = None              # the sessions as last read, to notice a new one
        self.filled = None            # the sets as last written
        self.docker_at = 0.0          # when Docker's rules were last checked
        self.ctl = []                 # the controller's addresses as last resolved
        self.ctl_at = 0.0
        self.empty_since = None       # when the last session with a network ended
        self.up = False               # the table and Docker's rules are in place
        # The layout file says on. Started from what was wanted before this
        # process, so a restart does not write it off for the seconds before
        # the first look, when a session starting would get the node's
        # network; the ready mark decides whether that session starts.
        self.conf_on = self.wanted()
        self.said = ""
        # The containers' table (R178): up, what its sets last held, and
        # what was last said about it.
        self.ctr_up = False
        self.ctr_filled = None
        self.ctr_said = ""

    def start(self):
        threading.Thread(target=self.run, name="sessnet", daemon=True).start()

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:                                # noqa: BLE001 (the loop must outlive one bad step; said once per message)
                self.say(f"session network: {e}")
            time.sleep(2)

    def say(self, text):
        if text != self.said:
            self.said = text
            if text:
                log(text)

    def wanted(self):
        return bool((self.agent.state.get("session_net") or {}).get("on"))

    def step(self):
        now = time.time()
        if now - self.can_at > 60:
            self.can, self.can_at = sessnet_can(), now
        want, (can, why) = self.wanted(), self.can
        sessions = sessnet_sessions()
        self.empty_since = None if sessions else (self.empty_since or now)
        error = ""
        if (want and can) or (sessions and self.up):
            error = self.keep(sessions, now)
        elif self.up and not want and now - self.empty_since > 30:
            # Off, and no session has had a network for half a minute: one
            # that has passed bb-session's check is still making its link,
            # and its file is not there to be counted yet.
            error = self.down()
        elif want and not can:
            # Wanted and not possible: closed, not open. The layout file
            # stays on, so bb-session refuses to start a session rather than
            # giving it the node's network, and the row says why.
            error = why
        if error:
            # Without the mark bb-session starts no session here while the
            # layout file says on, and says to look at the row.
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(SESSNET_DIR, "ready"))
        self.say(f"session network: {error}" if error and error != why else "")
        if want != self.conf_on:
            self.conf_on = want
            self.agent.refresh_session_tool()
            log(f"session network: {'on: each session started here gets a network of its own' if want else 'off for sessions started from now'}")
        now_is = {"can": can, "why": why, "wanted": want, "active": want and can and self.up and not error,
                  "sessions": len(sessions), "error": error if error != why else ""}
        # The census rides hello, every ten minutes: a change here is said
        # at the main loop's next turn instead, or the row would show the
        # answer from before the switch for ten minutes. The count of
        # sessions is not a change worth a hello.
        if {k: v for k, v in now_is.items() if k != "sessions"} != \
                {k: v for k, v in SESSNET_STATUS.items() if k != "sessions"}:
            self.agent.hello_at = 0
        # Updated, never cleared: the census copies it from another thread,
        # and every key is written every time, so a copy is always whole.
        SESSNET_STATUS.update(now_is)
        self.step_ctr(now)

    # -- each project's containers kept to their own network (R178) ----------
    def ctr_wanted(self):
        return bool((self.agent.state.get("session_net") or {}).get("ctr_on"))

    def step_ctr(self, now):
        """The containers' table: up and filled while the controller wants
        it and this node can, down otherwise; what the census says of it."""
        want = self.ctr_wanted()
        can, why = ctrnet_can() if want else (False, "")
        error = ""
        if want and can:
            error = self.keep_ctr(now)
        elif self.ctr_up:
            self.down_ctr()
        elif want:
            error = why
        if error != self.ctr_said:
            self.ctr_said = error
            log(f"container network: {error}" if error else "container network: each project's containers reach their own and the projects it reads, and nothing else on this node")
        was = SESSNET_STATUS.get("ctr") or {}
        now_is = {"wanted": want, "can": can if want else True, "why": why, "active": want and can and self.ctr_up and not error,
                  "error": error if error != why else "", "bridges": len(self.ctr_bridges) if hasattr(self, "ctr_bridges") else 0}
        if {k: v for k, v in now_is.items() if k != "bridges"} != {k: v for k, v in was.items() if k != "bridges"}:
            self.agent.hello_at = 0
        SESSNET_STATUS["ctr"] = now_is

    def keep_ctr(self, now):
        if not self.ctr_up:
            p = subprocess.run([NFT_BIN, "-f", "-"], input=f"table inet {CTRNET_TABLE}\n"
                               f"delete table inet {CTRNET_TABLE}\n" + ctrnet_table(),
                               capture_output=True, text=True, timeout=30, check=False)
            if p.returncode:
                return f"nft refused the containers' table: {(p.stderr or p.stdout).strip()[:200]}"
            self.ctr_up, self.ctr_filled = True, None
        elif subprocess.run([NFT_BIN, "list", "table", "inet", CTRNET_TABLE], capture_output=True,
                            timeout=15, check=False).returncode:
            self.ctr_up = False
            return "the containers' table was gone and is being put back"
        if now - self.containers_at > 10:
            self.containers, self.containers_at = sessnet_containers(), now
        if now - self.ctl_at > 60:
            self.ctl_at = now
            self.ctl = sessnet_ctl(self.agent.state.get("controller") or "") or self.ctl
        ns, _ = sessnet_resolvers()
        ctr = (self.agent.state.get("session_net") or {}).get("ctr") or {}
        bridges, pairs, ports = ctrnet_reach(self.containers, ctr)
        self.ctr_bridges = bridges
        fill = ctrnet_fill(bridges, pairs, ports, self.ctl, ns)
        if fill != self.ctr_filled:
            p = subprocess.run([NFT_BIN, "-f", "-"], input=fill, capture_output=True, text=True,
                               timeout=30, check=False)
            if p.returncode:
                return f"nft refused the containers' sets: {(p.stderr or p.stdout).strip()[:200]}"
            self.ctr_filled = fill
        return ""

    def down_ctr(self):
        subprocess.run([NFT_BIN, "delete", "table", "inet", CTRNET_TABLE], capture_output=True,
                       timeout=30, check=False)
        self.ctr_up, self.ctr_filled, self.ctr_bridges = False, None, []

    def keep(self, sessions, now):
        """The table and what it needs, then the sets as they are now."""
        if not self.up:
            os.makedirs(SESSNET_DIR, mode=0o755, exist_ok=True)
            os.chmod(SESSNET_DIR, 0o755)
            p = subprocess.run([NFT_BIN, "-f", "-"], input=f"table inet {SESSNET_TABLE}\n"
                               f"delete table inet {SESSNET_TABLE}\n" + sessnet_table(),
                               capture_output=True, text=True, timeout=30, check=False)
            if p.returncode:
                return f"nft refused the table: {(p.stderr or p.stdout).strip()[:200]}"
            bad = docker_user(True)
            if bad:
                return f"Docker's forwarding would not take the rules: {bad}"
            self.up, self.filled, self.docker_at = True, None, now
        elif subprocess.run([NFT_BIN, "list", "table", "inet", SESSNET_TABLE], capture_output=True,
                            timeout=15, check=False).returncode:
            # Gone from under us (a flush, a firewall reload): put back next turn.
            self.up = False
            return "the table was gone and is being put back"
        elif now - self.docker_at > 30:
            # Docker's rules likewise: a Docker restart or a flush takes them,
            # and without them a session reaches no container (closed, not
            # open). Looked at every half minute; put back when out of place.
            self.docker_at = now
            bad = docker_user(True)
            if bad:
                return f"Docker's forwarding would not take the rules back: {bad}"
        ns, search = sessnet_resolvers()
        _write_root(os.path.join(SESSNET_DIR, "resolv.conf"), sessnet_resolv_text(ns, search))
        if sessions != self.seen or now - self.containers_at > 10:
            self.containers, self.containers_at, self.seen = sessnet_containers(), now, sessions
        own = (self.agent.state.get("session_net") or {}).get("own") or {}
        # The controller's address, resolved once a minute and kept when a
        # resolver fails to answer: an empty set would cut every session off
        # from it until the next answer.
        if now - self.ctl_at > 60:
            self.ctl_at = now
            self.ctl = sessnet_ctl(self.agent.state.get("controller") or "") or self.ctl
        fill = sessnet_fill(self.ctl, ns, sessnet_pairs(sessions, own, self.containers),
                            sessnet_peers(sessions, own), sessnet_hosts(sessions, own))
        if fill != self.filled:
            p = subprocess.run([NFT_BIN, "-f", "-"], input=fill, capture_output=True, text=True,
                               timeout=30, check=False)
            if p.returncode:
                return f"nft refused the sets: {(p.stderr or p.stdout).strip()[:200]}"
            self.filled = fill
        _write_root(os.path.join(SESSNET_DIR, "ready"), f"{SESSNET_TABLE}\n")
        return ""

    def down(self):
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(SESSNET_DIR, "ready"))
        bad = docker_user(False)
        subprocess.run([NFT_BIN, "delete", "table", "inet", SESSNET_TABLE], capture_output=True,
                       timeout=30, check=False)
        self.up, self.filled = False, None
        return f"Docker's forwarding kept a rule: {bad}" if bad else ""


def _write_root(path, text):
    """A small file of ours, root's and readable by all, written when it differs."""
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
