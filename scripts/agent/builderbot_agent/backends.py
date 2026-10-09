"""The machine's own tools: its package manager and the network configuration backends."""
import contextlib
import os
import shutil
import subprocess
from .base import (
    APK_BIN,
    APT_BIN,
    BREW_BIN,
    DHCPCD_CONF,
    DNF_BIN,
    DPKG_BIN,
    EMERGE_BIN,
    IFDOWN_BIN,
    IFUP_BIN,
    INTERFACES_FILE,
    NETPLAN_BIN,
    NETPLAN_DIR,
    NETPLAN_FILE,
    NETWORKCTL_BIN,
    NETWORKD_DIR,
    NMCLI_BIN,
    PACMAN_BIN,
    RPM_BIN,
    SYSCONFIG_NET_DIR,
    WICKED_BIN,
    XBPS_INSTALL_BIN,
    XBPS_QUERY_BIN,
    ZYPPER_BIN,
    _run,
)


# ---------------------------------------------------------------------------
# the machine's own tools
#
# A system job from the controller says WHAT (an address and a gateway, a
# mount, the packages a recipe needs) and never how: the spec is the same
# for every node. The how is this machine's, and it is detected here rather
# than assumed: which package manager is installed, and which service owns
# the network. Each backend renders the same desired state into its own
# commands, and the census reports which one a node has, so the row can say
# what a change would go through before it is sent. Debian/Ubuntu (apt,
# netplan) and the RHEL family (dnf, NetworkManager) are the two so far;
# another distribution is another backend here, not another job spec.

def _have(binary):
    """A binary on PATH, or an absolute path that is executable. The suite
    points the *_BIN settings at stubs by path."""
    return bool(shutil.which(binary)) or os.access(binary, os.X_OK)


def pkg_backend():
    """(name, query argv, install argv) for the package manager this machine
    has, keyed by the tool that answers whether a package is installed
    (since that is the half every check needs), and, where two families
    share one (rpm: dnf and zypper), by the installer beside it. The name
    is the key a recipe lists its system packages under (`system.apt`,
    `system.dnf`, ...). Empty when it is none of them, which is a machine
    this agent cannot install packages on: a recipe's packages are named
    for the owner there."""
    if _have(DPKG_BIN):
        return "apt", [DPKG_BIN, "-s"], [APT_BIN, "install", "-y", "-qq"]
    if _have(RPM_BIN) and _have(ZYPPER_BIN) and not _have(DNF_BIN):
        return "zypper", [RPM_BIN, "-q"], [ZYPPER_BIN, "-n", "-q", "install", "-y"]
    if _have(RPM_BIN) and _have(DNF_BIN):
        # Both, not rpm alone: rpm is an ordinary package on Arch and Alpine
        # (rpm-tools), and a node with it and no dnf is not a dnf machine.
        return "dnf", [RPM_BIN, "-q"], [DNF_BIN, "-y", "-q", "install"]
    if _have(PACMAN_BIN):
        return "pacman", [PACMAN_BIN, "-Q"], [PACMAN_BIN, "-S", "--noconfirm", "--needed"]
    if _have(APK_BIN):
        return "apk", [APK_BIN, "info", "-e"], [APK_BIN, "add", "-q"]
    if _have(XBPS_QUERY_BIN):
        return "xbps", [XBPS_QUERY_BIN], [XBPS_INSTALL_BIN, "-y"]
    if _have(EMERGE_BIN):
        # No query short of portage-utils: everything asked for is emerged
        # with --noreplace, which is portage's own "if missing".
        return "emerge", [], [EMERGE_BIN, "--quiet", "--noreplace"]
    if _have(BREW_BIN) or os.path.exists("/opt/homebrew/bin/brew"):
        # macOS: Homebrew, as the account that owns it. The agent runs as
        # that account on a guest node, which is what brew wants.
        brew = BREW_BIN if _have(BREW_BIN) else "/opt/homebrew/bin/brew"
        return "brew", [brew, "list", "--versions"], [brew, "install", "--quiet"]
    return "", [], []


class NetplanNet:
    """Debian and Ubuntu: one YAML file of our own under /etc/netplan, and
    `netplan apply`. The snapshot is the file's previous text (None when
    there was none), which is exactly what restore puts back."""
    name = "netplan"

    @staticmethod
    def available():
        return _have(NETPLAN_BIN)

    @staticmethod
    def ready(iface):
        return ""

    @staticmethod
    def render(iface, mode, addr, gw, dns, routes=()):
        lines = ["network:", "  version: 2", "  ethernets:", f"    {iface}:"]
        rs = []
        if mode == "dhcp":
            lines.append("      dhcp4: true")
        else:
            lines += ["      dhcp4: false", f"      addresses: [{addr}]"]
            if gw:
                rs.append(("default", gw))
        rs += [(r["to"], r["via"]) for r in routes]
        if rs:
            lines.append("      routes:")
            for to, via in rs:
                lines += [f"        - to: {to}", f"          via: {via}"]
        if mode != "dhcp" and dns:
            lines += ["      nameservers:", f"        addresses: [{', '.join(dns)}]"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def snapshot(iface):
        try:
            with open(os.path.join(NETPLAN_DIR, NETPLAN_FILE)) as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def same(desired, before):
        return desired == before

    @staticmethod
    def _write(text):
        path = os.path.join(NETPLAN_DIR, NETPLAN_FILE)
        if text is None:
            with contextlib.suppress(OSError):
                os.remove(path)
            return path
        os.makedirs(NETPLAN_DIR, exist_ok=True)
        with open(path, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(text)
        return path

    def apply(self, agent, job, iface, desired, before):
        path = self._write(desired)
        job.say(f"wrote {path}:\n{desired}")
        job.flush()                      # the last words before the cord is cut
        return agent._sh(job, [NETPLAN_BIN, "apply"])

    def restore(self, agent, job, iface, before):
        self._write(before)
        agent._sh(job, [NETPLAN_BIN, "apply"])


class NetworkManagerNet:
    """The RHEL family (and any machine NetworkManager runs): the ipv4 keys
    of the connection on the interface, through nmcli, then `con up` to
    make it live. The snapshot is those keys as they were, and restore is
    the same modify with the old values."""
    name = "networkmanager"
    FIELDS = ("ipv4.method", "ipv4.addresses", "ipv4.gateway", "ipv4.dns",
              "ipv4.ignore-auto-dns", "ipv4.routes")

    @staticmethod
    def available():
        return _have(NMCLI_BIN) and _run([NMCLI_BIN, "-t", "-g", "RUNNING", "general"]) == "running"

    @staticmethod
    def conn(iface):
        # By exit code, not by output: for a device that does not exist
        # nmcli prints "Error: Device 'x' not found." and exits 10, and
        # _run would hand that sentence back as the connection's name.
        try:
            p = subprocess.run([NMCLI_BIN, "-t", "-g", "GENERAL.CONNECTION", "device", "show", iface],
                               capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return ""
        return p.stdout.strip() if p.returncode == 0 else ""

    def ready(self, iface):
        if not self.conn(iface):
            return (f"NetworkManager has no connection on {iface}. Once, at the console: "
                    f"nmcli con add type ethernet ifname {iface} con-name {iface}")
        return ""

    @staticmethod
    def render(iface, mode, addr, gw, dns, routes=()):
        rs = ", ".join(f"{r['to']} {r['via']}" for r in routes)
        if mode == "dhcp":
            return {"ipv4.method": "auto", "ipv4.addresses": "", "ipv4.gateway": "",
                    "ipv4.dns": "", "ipv4.ignore-auto-dns": "no", "ipv4.routes": rs}
        return {"ipv4.method": "manual", "ipv4.addresses": addr, "ipv4.gateway": gw,
                "ipv4.dns": ",".join(dns), "ipv4.ignore-auto-dns": "yes" if dns else "no",
                "ipv4.routes": rs}

    def snapshot(self, iface):
        con = self.conn(iface)
        return {"_con": con, **{f: _run([NMCLI_BIN, "-t", "-g", f, "con", "show", con])
                                for f in self.FIELDS}}

    @staticmethod
    def same(desired, before):
        return all((before or {}).get(k, "").strip() == v for k, v in desired.items())

    def apply(self, agent, job, iface, desired, before):
        con = before["_con"]
        argv = [NMCLI_BIN, "con", "mod", con]
        for k in self.FIELDS:
            argv += [k, desired[k]]
        job.say(f"NetworkManager connection {con!r} on {iface}: "
                + " ".join(f"{k}={desired[k] or '-'}" for k in self.FIELDS) + "\n")
        job.flush()
        rc = agent._sh(job, argv)
        return rc or agent._sh(job, [NMCLI_BIN, "con", "up", con])

    def restore(self, agent, job, iface, before):
        con = before["_con"]
        argv = [NMCLI_BIN, "con", "mod", con]
        for k in self.FIELDS:
            argv += [k, before.get(k, "")]
        agent._sh(job, argv)
        agent._sh(job, [NMCLI_BIN, "con", "up", con])


class FilesNet:
    """The shape shared by the backends that are files plus a reload: render
    the desired state as {path: text-or-None}, snapshot the same paths as
    they are, write, run the reload, and restore by writing the snapshot
    back and reloading again. None for a path means "not there", both in
    what is wanted and in what was found, so a file this created is removed
    again on revert."""
    name = ""

    def ready(self, iface):
        return ""

    @staticmethod
    def same(desired, before):
        return desired == before

    def snapshot(self, iface):
        out = {}
        for path in self.paths(iface):
            try:
                with open(path) as f:
                    out[path] = f.read()
            except OSError:
                out[path] = None
        return out

    @staticmethod
    def _write(files):
        for path, text in files.items():
            if text is None:
                with contextlib.suppress(OSError):
                    os.remove(path)
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                os.fchmod(f.fileno(), 0o644)
                f.write(text)

    def apply(self, agent, job, iface, desired, before):
        self._write(desired)
        for path, text in desired.items():
            job.say(f"wrote {path}:\n{text}" if text is not None else f"removed {path}\n")
        job.flush()                      # the last words before the cord is cut
        return self.reload(agent, job, iface)

    def restore(self, agent, job, iface, before):
        self._write(before)
        self.reload(agent, job, iface)


class NetworkdNet(FilesNet):
    """systemd-networkd (Arch and its derivatives on a server install, and
    anything else that chose it): one .network file of our own for the
    interface, and `networkctl reload`."""
    name = "systemd-networkd"

    @staticmethod
    def available():
        return _have(NETWORKCTL_BIN) and os.path.isdir(NETWORKD_DIR) \
            and _run(["systemctl", "is-active", "systemd-networkd"]) == "active"

    @staticmethod
    def paths(iface):
        # networkd applies the FIRST .network file, in lexical order, that
        # matches a device and ignores the rest; the distribution's own sit
        # at 10- and 20-, so ours sorts ahead of them or it is never read,
        # and the job would then report success with the old address.
        return [os.path.join(NETWORKD_DIR, f"00-builderbot-{iface}.network")]

    def render(self, iface, mode, addr, gw, dns, routes=()):
        lines = ["[Match]", f"Name={iface}", "", "[Network]"]
        if mode == "dhcp":
            lines.append("DHCP=yes")
        else:
            lines.append(f"Address={addr}")
            if gw:
                lines.append(f"Gateway={gw}")
            lines += [f"DNS={d}" for d in dns]
        for r in routes:
            lines += ["", "[Route]", f"Destination={r['to']}", f"Gateway={r['via']}"]
        return {self.paths(iface)[0]: "\n".join(lines) + "\n"}

    def reload(self, agent, job, iface):
        rc = agent._sh(job, [NETWORKCTL_BIN, "reload"])
        return rc or agent._sh(job, [NETWORKCTL_BIN, "reconfigure", iface])


class IfupdownNet(FilesNet):
    """/etc/network/interfaces: Debian without netplan, Raspberry Pi OS
    before NetworkManager, Alpine's ifupdown-ng. The interface's own stanza
    in that file is replaced with ours (the rest of the file is kept as it
    is), then the interface is cycled with ifdown/ifup."""
    name = "ifupdown"
    MARK = "# BuilderBot: this interface, as the controller set it"

    @staticmethod
    def available():
        return _have(IFUP_BIN) and os.path.isfile(INTERFACES_FILE)

    @staticmethod
    def paths(iface):
        return [INTERFACES_FILE]

    @staticmethod
    def _without(text, iface):
        """The file minus the interface's stanza: its `auto`/`allow-*`
        line and its `iface` block up to the next top-level keyword."""
        out, skipping = [], False
        for line in text.splitlines():
            if line.strip() == IfupdownNet.MARK:
                continue                  # ours from last time: rendered again below
            w = line.split()
            top = bool(w) and not line[0].isspace()
            if top and w[0] in ("iface",) and len(w) > 1 and w[1] == iface:
                skipping = True
                continue
            if top and w[0] in ("auto", "allow-hotplug") and iface in w[1:]:
                rest = [x for x in w[1:] if x != iface]
                if rest:
                    out.append(w[0] + " " + " ".join(rest))
                continue
            if top and w[0] in ("iface", "auto", "allow-hotplug", "mapping", "source", "source-directory"):
                skipping = False
            if not skipping:
                out.append(line)
        return "\n".join(out).rstrip("\n") + ("\n" if out else "")

    def render(self, iface, mode, addr, gw, dns, routes=()):
        try:
            with open(INTERFACES_FILE) as f:
                base = self._without(f.read(), iface)
        except OSError:
            base = ""
        lines = [self.MARK, f"auto {iface}"]
        if mode == "dhcp":
            lines.append(f"iface {iface} inet dhcp")
        else:
            lines.append(f"iface {iface} inet static")
            lines.append(f"    address {addr}")
            if gw:
                lines.append(f"    gateway {gw}")
            if dns:
                lines.append(f"    dns-nameservers {' '.join(dns)}")
        for r in routes:
            lines += [f"    up ip route add {r['to']} via {r['via']} dev {iface}",
                      f"    down ip route del {r['to']} via {r['via']} dev {iface}"]
        return {INTERFACES_FILE: base + ("\n" if base and not base.endswith("\n\n") else "")
                + "\n".join(lines) + "\n"}

    def reload(self, agent, job, iface):
        agent._sh(job, [IFDOWN_BIN, iface])
        return agent._sh(job, [IFUP_BIN, iface])


class WickedNet(FilesNet):
    """SUSE Leap's wicked: ifcfg-IFACE for the address, ifroute-IFACE for
    the default route, and the static resolvers in netconfig's config, then
    `wicked ifreload` and `netconfig update`."""
    name = "wicked"

    @staticmethod
    def available():
        return _have(WICKED_BIN) and os.path.isdir(SYSCONFIG_NET_DIR) \
            and _run(["systemctl", "is-active", "wicked"]) == "active"

    @staticmethod
    def paths(iface):
        return [os.path.join(SYSCONFIG_NET_DIR, f"ifcfg-{iface}"),
                os.path.join(SYSCONFIG_NET_DIR, f"ifroute-{iface}"),
                os.path.join(SYSCONFIG_NET_DIR, "config")]

    def render(self, iface, mode, addr, gw, dns, routes=()):
        ifcfg, ifroute, config = self.paths(iface)
        out = {}
        lines = [f"{r['to']} {r['via']} - {iface}" for r in routes]
        if mode == "dhcp":
            out[ifcfg] = "STARTMODE='auto'\nBOOTPROTO='dhcp'\n"
        else:
            out[ifcfg] = f"STARTMODE='auto'\nBOOTPROTO='static'\nIPADDR='{addr}'\n"
            if gw:
                lines.insert(0, f"default {gw} - {iface}")
        out[ifroute] = "\n".join(lines) + "\n" if lines else None
        # netconfig's config is a shared file: only its static-DNS line moves.
        try:
            with open(config) as f:
                text = f.read()
        except OSError:
            text = ""
        kept = [l for l in text.splitlines() if not l.startswith("NETCONFIG_DNS_STATIC_SERVERS=")]
        kept.append(f'NETCONFIG_DNS_STATIC_SERVERS="{" ".join(dns) if mode == "static" else ""}"')
        out[config] = "\n".join(kept) + "\n"
        return out

    def reload(self, agent, job, iface):
        rc = agent._sh(job, [WICKED_BIN, "ifreload", iface])
        agent._sh(job, ["netconfig", "update", "-f"])
        return rc


class DhcpcdNet(FilesNet):
    """dhcpcd on its own (Void's default): a static address is a marked
    block in dhcpcd.conf for the interface, and the daemon is restarted."""
    name = "dhcpcd"
    MARK = "# BuilderBot: "

    @staticmethod
    def available():
        return _have("dhcpcd") and os.path.isfile(DHCPCD_CONF) and bool(_run(["pgrep", "-x", "dhcpcd"]))

    @staticmethod
    def paths(iface):
        return [DHCPCD_CONF]

    # dhcpcd.conf has no static route of its own (only a hook script could
    # add one), so routes are refused here by name rather than dropped.
    no_routes = "dhcpcd has no setting for a static route; add it with a dhcpcd hook by hand"

    def render(self, iface, mode, addr, gw, dns, routes=()):
        try:
            with open(DHCPCD_CONF) as f:
                text = f.read()
        except OSError:
            text = ""
        out, skipping = [], False
        for line in text.splitlines():
            if line.rstrip() == self.MARK + iface:
                skipping = True
                continue
            if skipping and line.startswith(self.MARK + "end"):
                skipping = False
                continue
            if not skipping:
                out.append(line)
        base = "\n".join(out).rstrip("\n")
        if mode == "static":
            block = [self.MARK + iface, f"interface {iface}", f"static ip_address={addr}"]
            if gw:
                block.append(f"static routers={gw}")
            if dns:
                block.append(f"static domain_name_servers={' '.join(dns)}")
            block.append(self.MARK + "end")
            base = (base + "\n\n" if base else "") + "\n".join(block)
        return {DHCPCD_CONF: base + "\n"}

    def reload(self, agent, job, iface):
        for argv in (["sv", "restart", "dhcpcd"], ["rc-service", "dhcpcd", "restart"],
                     ["systemctl", "restart", "dhcpcd"]):
            if _have(argv[0]):
                return agent._sh(job, argv)
        return agent._sh(job, ["dhcpcd", "-n", iface])


def net_backend():
    """The service that owns this machine's network, or None. In the order
    that resolves a machine with two of them: netplan renders to whichever
    of NetworkManager and networkd is under it, so a file of ours beside
    its files is the change it expects; NetworkManager over networkd where
    both run; the file-based ones only when nothing above them is running."""
    for b in (NetplanNet(), NetworkManagerNet(), NetworkdNet(), WickedNet(),
              IfupdownNet(), DhcpcdNet()):
        if b.available():
            return b
    return None
