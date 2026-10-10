"""Enroll node, as one file to download (R161).

The Nodes tab's Enroll dialog asks its questions (the name, the account jobs
run as, whether sessions run there, how the machine reaches the controller
and at what address), and the answer is a script: the provisioner this
controller ships, with those answers and the enroll token inside, and for a
node behind WireGuard the tunnel's config as well. Run once as root on the
machine, it brings the tunnel up, checks the controller answers through it,
provisions and enrolls. It is built on the press and kept nowhere: the
uploaded config holds the node's private key, and the token is good once,
so the file the browser saves is the only copy of either.

WireGuard from a config the person's router made: the router is the home
end, so the one-way rule (the node may open the controller's port and
nothing else; the controller and the LAN open the session ports back) is
the router's to enforce, and home_rules() says what to put there. What the
script installs on the node is narrowed so it routes nothing but the
controller into the tunnel (AllowedIPs), runs nothing of the config's own
(PostUp and the like), and keeps the tunnel open from behind a cloud
provider's NAT (PersistentKeepalive). The narrowing is hygiene, not the
security: the node is the end not trusted, and root there can undo it.

Through a public hostname (R170, the operator, 10 Oct): the controller is
published at a name by a tunnel something at home dials out (Cloudflare
Tunnel, Tailscale Funnel, ngrok, frp, a reverse SSH to a box with an
address: any of them), set to forward /api/v1/agent/ and answer everything
else 404, so the node dials a public name over HTTPS, nothing at home is
opened, and the node never learns the home address: it only ever talks to
the tunnel's edge. Such a node is hosting only: the controller cannot open
its session ports back through the tunnel. It verifies the hostname's
public certificate rather than pinning the controller's own, which it never
sees. Nothing here is the tunnel's own: the dialog prints the rule, with
cloudflared's config as one way to write it.

Stdlib only; nodes.py hands in the provisioner's bytes.
"""
import base64
import ipaddress
import re
import time
import urllib.parse

REACH = ("lan", "wireguard", "public")
# The doors in for SSH (R174): a tunnel client on the node, switched from
# its row. cloudflared publishes port 22 at a hostname of its own with a
# tunnel token; Tailscale joins the node to a tailnet with an auth key and
# answers ssh there (tailscale ssh), with no public name at all.
DOORS = ("cloudflared", "tailscale")
# Lines a router's config carries that the node's copy goes without: a
# resolver (only the controller is reached, by address, and wg-quick's DNS
# needs resolvconf), commands wg-quick would run as root, and settings that
# route more than the controller.
_DROP = re.compile(r"^\s*(DNS|PreUp|PostUp|PreDown|PostDown|SaveConfig|Table)\s*=", re.I)
_NAME = re.compile(r"[^A-Za-z0-9._-]")


def controller_host(url):
    """The host part of the controller's URL, '' when it is not a URL."""
    u = urllib.parse.urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return ""
    return u.hostname


def parse_wg(conf):
    """What a WireGuard config says, or why it cannot be used: the
    interface's IPv4 address (the node's address in the tunnel), and that
    there is a key and a peer with an endpoint to dial."""
    sect, iface, peers = "", {}, []
    for raw in (conf or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            sect = m.group(1).lower()
            if sect == "peer":
                peers.append({})
            continue
        if "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        if sect == "interface":
            iface[k.lower()] = v
        elif sect == "peer" and peers:
            peers[-1][k.lower()] = v
    if not iface.get("privatekey"):
        return {"error": "that is not a WireGuard config: it has no [Interface] with a PrivateKey"}
    if len(peers) != 1:
        return {"error": f"the config names {len(peers)} peers; a node's has one, the router"}
    if not peers[0].get("publickey") or not peers[0].get("endpoint"):
        return {"error": "the config's [Peer] has no PublicKey or no Endpoint, so the node would have nothing to dial"}
    addr = ""
    for a in (iface.get("address") or "").split(","):
        try:
            ip = ipaddress.ip_interface(a.strip())
        except ValueError:
            continue
        if ip.version == 4:
            addr = str(ip.ip)
            break
    if not addr:
        return {"error": "the config's [Interface] has no IPv4 Address, which is what the controller reaches the node at"}
    return {"addr": addr, "endpoint": peers[0]["endpoint"]}


def narrow_wg(conf, controller_ip):
    """The config the node runs: the router's, with AllowedIPs the
    controller alone, the dropped lines gone, and a keepalive."""
    out, sect, keep = [], "", False
    for raw in (conf or "").splitlines():
        line = raw.strip()
        m = re.fullmatch(r"\[(\w+)\]", line.split("#", 1)[0].strip())
        if m:
            if sect == "peer" and not keep:
                out.append("PersistentKeepalive = 25")
            sect = m.group(1).lower()
            out.append(line)
            continue
        if _DROP.match(line):
            continue
        if sect == "peer" and re.match(r"^\s*AllowedIPs\s*=", line, re.I):
            out.append(f"AllowedIPs = {controller_ip}/32")
            continue
        if sect == "peer" and re.match(r"^\s*PersistentKeepalive\s*=", line, re.I):
            keep = True
        out.append(line)
    if sect == "peer" and not keep:
        out.append("PersistentKeepalive = 25")
    if not any(re.match(r"^\s*AllowedIPs\s*=", x, re.I) for x in out):
        i = max(i for i, x in enumerate(out) if x.lower() == "[peer]")
        out.insert(i + 1, f"AllowedIPs = {controller_ip}/32")
    return "\n".join(out).strip() + "\n"


def check(answers):
    """The answers, cleaned, or {"error": why}. `answers` is the dialog's:
    name, user, sessions (bool), reach, controller (the URL as the node
    will reach it) and, for WireGuard, wg_conf (the router's file)."""
    reach = str(answers.get("reach") or "lan")
    if reach not in REACH:
        return {"error": f"no such way to reach the controller: {reach}"}
    url = str(answers.get("controller") or "").strip().rstrip("/")
    host = controller_host(url)
    if not host:
        return {"error": "the controller's address is a URL the node dials, like http://192.168.1.10:7680"}
    out = {"reach": reach, "controller": url, "sessions": answers.get("sessions") is not False}
    # A door in for SSH (R174): which recipe, its name, and its secret.
    door = str(answers.get("door") or "")
    if door:
        if door not in DOORS:
            return {"error": f"no such door: {door}; one of {', '.join(DOORS)}"}
        host = str(answers.get("door_host") or "").strip().lower()
        secret = str(answers.get("door_secret") or "").strip()
        if door == "cloudflared" and not re.fullmatch(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?", host):
            return {"error": "cloudflared's door is a hostname of its own, like ssh-vps.example.com (not the "
                             "controller's): the public hostname set on the tunnel in Zero Trust"}
        if not secret or len(secret) > 4000 or any(c.isspace() for c in secret):
            return {"error": "the door's secret is one line: cloudflared's tunnel token, or Tailscale's auth key"}
        out.update(door=door, door_host=host if door == "cloudflared" else "", door_secret=secret,
                   door_close22=answers.get("door_close22") is True)
    if reach == "public":
        # A public name over HTTPS, verified by the system's CAs: an address
        # or plain http here is a LAN enrollment wearing the wrong word.
        if urllib.parse.urlparse(url).scheme != "https":
            return {"error": f"through a public hostname the controller is reached over https at the "
                             f"tunnel's name, like https://bb.example.com, not {url}"}
        try:
            ipaddress.ip_address(host)
            return {"error": f"through a public hostname the controller is reached at the tunnel's "
                             f"name, not an address ({host}): the name is what the tunnel routes"}
        except ValueError:
            pass
        # Hosting only, whatever was ticked: the controller cannot reach
        # back through the tunnel to a session's ports.
        out.update(sessions=False, tunnel_host=host.lower())
    if reach == "wireguard":
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return {"error": f"through WireGuard the controller is reached by its address on your network, "
                             f"not a name ({host}): nothing resolves names through the tunnel"}
        conf = str(answers.get("wg_conf") or "")
        if len(conf) > 8000:
            return {"error": "that file is too big to be a WireGuard config"}
        wg = parse_wg(conf)
        if wg.get("error"):
            return wg
        out.update(wg_conf=narrow_wg(conf, str(ip)), tunnel_addr=wg["addr"],
                   endpoint=wg["endpoint"], controller_ip=str(ip))
    return out


WG_BEGIN = "base64 -d > \"$dir/bb.conf\" <<'WGCONF'"
# The door's secret, the same way (R174): in the script until it has run.
DOOR_BEGIN = "base64 -d > \"$dir/door-secret\" <<'DOORSECRET'"
DOOR_AFTER = ": # the door's secret left this file once the node enrolled; the node keeps it"
# What stands where the config was, once it has run: the tunnel's config as
# this node installed it.
WG_AFTER = ('[ -r /etc/wireguard/bb.conf ] || { echo "the WireGuard config left this file once the node '
            'enrolled, and /etc/wireguard/bb.conf is not here either: make a new script on the Nodes tab" >&2; '
            'exit 1; }; install -m 600 /etc/wireguard/bb.conf "$dir/bb.conf"')


def _b64(data):
    s = base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()
    return "\n".join(s[i:i + 76] for i in range(0, len(s), 76))


def filename(name):
    return f"enroll-{_NAME.sub('-', name or 'node').strip('-') or 'node'}.sh"


def build(ans, *, name, user, token, expires, provisioner):
    """The script, as text. `ans` is check()'s answer."""
    flags = [f"--controller {_q(ans['controller'])}", f"--token {_q(token)}"]
    if user and user != "bb":
        flags.append(f"--user {_q(user)}")
    if not ans["sessions"]:
        flags.append("--session-user none")
    if ans["reach"] == "public":
        flags.append("--reach public")
    if ans.get("door"):
        flags.append(f"--door {_q(ans['door'])}")
        if ans.get("door_host"):
            flags.append(f"--door-host {_q(ans['door_host'])}")
        if ans.get("door_close22"):
            flags.append("--door-close22")
    when = time.strftime("%d %b %Y %H:%M UTC", time.gmtime(expires))
    lines = [
        "#!/usr/bin/env bash",
        f"# BuilderBot: enroll {name} as a node of {ans['controller']}.",
        "# Made on the Nodes tab's Enroll node. Run it as root on the machine:",
        "# sudo bash THIS_FILE",
        "#",
        f"# It holds an enrollment token, good once, until {when}.",
        *(["# Until it has run it holds this node's WireGuard private key as well:",
           "# once the node has enrolled it takes the WireGuard config out of itself",
           "# (the node's copy is /etc/wireguard/bb.conf) and keeps the rest, which",
           "# can be changed and run again on this machine with a new token."]
          if ans["reach"] == "wireguard" else []),
        *(["# Until it has run it holds the door's secret as well (a tunnel token or",
           "# an auth key): once the node has enrolled it takes that out of itself."]
          if ans.get("door") else []),
        "set -euo pipefail",
        # One block, read whole before any of it runs: the end of it rewrites
        # this file, and bash otherwise reads a script as it goes.
        "{",
        '[ "$(id -u)" -eq 0 ] || { echo "run this as root: sudo bash $0" >&2; exit 1; }',
        'command -v base64 >/dev/null 2>&1 || { echo "this needs base64 (coreutils)" >&2; exit 1; }',
        'dir="$(mktemp -d)"',
        "trap 'rm -rf \"$dir\"' EXIT",
        "base64 -d > \"$dir/provision-linux.sh\" <<'PROVISIONER'",
        _b64(provisioner),
        "PROVISIONER",
    ]
    if ans["reach"] == "wireguard":
        lines += [WG_BEGIN, _b64(ans["wg_conf"]), "WGCONF",
                  'chmod 600 "$dir/bb.conf"']
        flags.append('--wg-conf "$dir/bb.conf"')
    if ans.get("door"):
        lines += [DOOR_BEGIN, _b64(ans["door_secret"]), "DOORSECRET",
                  'chmod 600 "$dir/door-secret"']
        flags.append('--door-secret "$dir/door-secret"')
    lines.append(f'bash "$dir/provision-linux.sh" {" ".join(flags)} "$@"')
    # Only after the provisioner succeeded (set -e ends a failed run above,
    # with the secrets still in here for another try): each secret block out
    # of this file, the rest kept to be changed and run again, which then
    # takes the tunnel's config as installed and the door's service as it
    # is. The old copy shredded where shred exists, since a rename leaves
    # its blocks.
    for begin, end, after, said in (
            (WG_BEGIN, "WGCONF", WG_AFTER, "the WireGuard config is out of %s now; this node keeps its own in /etc/wireguard/bb.conf"),
            (DOOR_BEGIN, "DOORSECRET", DOOR_AFTER, "the door secret is out of %s now; this node keeps it")):
        if (begin == WG_BEGIN and ans["reach"] != "wireguard") or (begin == DOOR_BEGIN and not ans.get("door")):
            continue
        lines += [
            "if [ -f \"$0\" ] && grep -qxF " + _q(begin) + " \"$0\"; then",
            '    new="$(mktemp "$0.XXXXXX")"',
            "    awk -v b=" + _q(begin) + " -v r=" + _q(after)
            + " '$0 == b { print r; skip = 1; next } skip && $0 == \"" + end + "\" { skip = 0; next } !skip' \"$0\" > \"$new\"",
            '    chmod --reference="$0" "$new" 2>/dev/null || chmod 600 "$new"',
            '    if command -v shred >/dev/null 2>&1; then shred -u "$0"; else rm -f "$0"; fi',
            '    mv "$new" "$0"',
            "    printf '\\n== " + said + "\\n' \"$0\"",
            "fi"]
    lines += ["exit 0", "}", ""]
    return "\n".join(lines)


def _q(s):
    """A word for the script's command line, single-quoted."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def home_rules(ans, port):
    """What the home end enforces so the tunnel is one-way, for the person
    to apply on their router: words first, then the rules in nftables'
    form, which an OpenWrt or any Linux router takes as they are."""
    if ans["reach"] == "public":
        return hostname_rules(ans, port)
    if ans["reach"] != "wireguard":
        return ""
    node, ctl = ans["tunnel_addr"], ans["controller_ip"]
    return (
        f"On the router, so this node can open the controller and nothing else: from {node} through the "
        f"tunnel, allow TCP to {ctl} port {port} and replies to connections the LAN opened; drop "
        f"everything else it starts. The controller opens the session ports (7681, 7682) to {node}, so "
        f"traffic from the LAN to it stays allowed, and the router routes the tunnel's addresses to the "
        f"LAN without masquerading them.\n\n"
        f"# nftables (OpenWrt, or any Linux router), in the forward chain:\n"
        f"ip saddr {node} ct state established,related accept\n"
        f"ip saddr {node} ip daddr {ctl} tcp dport {port} accept\n"
        f"ip saddr {node} drop\n"
        f"# ...and in the input chain, the router itself:\n"
        f"ip saddr {node} ct state established,related accept\n"
        f"ip saddr {node} drop\n")


def hostname_rules(ans, port):
    """What the home end does so the hostname reaches the agent's API and
    nothing else: the rule in words, for whatever tunnel publishes the name,
    then cloudflared's config as one way to write it. The tunnel is its
    own program's to keep up; the controller's own gate (nodes.
    tunnel_refuses) answers the hostname on the agent's API alone as well,
    so a wider rule still reaches no page."""
    host = ans.get("tunnel_host") or controller_host(ans["controller"])
    return (
        f"At home, the tunnel that publishes {host} (Cloudflare Tunnel, Tailscale Funnel, ngrok, frp, or "
        f"another) forwards only the path /api/v1/agent/ to the controller at CONTROLLER_LAN_ADDRESS:{port}, "
        f"and answers everything else at that name 404, so it serves no page. Nothing on your router "
        f"changes, and the node only ever talks to the tunnel's edge.\n\n"
        f"With cloudflared, in its config.yml (or the same two public hostname rules in Zero Trust):\n"
        f"ingress:\n"
        f"  - hostname: {host}\n"
        f"    path: ^/api/v1/agent/\n"
        f"    service: http://CONTROLLER_LAN_ADDRESS:{port}\n"
        f"  - hostname: {host}\n"
        f"    service: http_status:404\n"
        f"  - service: http_status:404\n")
