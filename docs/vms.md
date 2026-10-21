# VMs

A project's virtual machines, made, started, stopped, snapshotted and removed
on the nodes whose VM host feature is installed, by a person on the VMs page
or by a project's Claude session with `bb vm`, under the project's own
setting. The VMs page sits in the Containers group beside Containers and
nginx, and is built from the Containers page's pieces.

## Where a VM runs

A VM runs on a node with **VM host** installed: KVM through libvirt, put
there by Enroll node's tick or by the node's Features section on the Nodes
page (`bb-sandbox feature install vmhost`, the same install either way). It
needs `/dev/kvm`. A node that is itself a VM has that only when its host
passes virtualization through: CPU mode host-passthrough (Unraid's CPU Mode:
Host Passthrough, Proxmox's CPU type host) and nested KVM on in the host's
`kvm_intel` or `kvm_amd`. Without it the Features row says so, and offers no
Install: a VM in software emulation would be tens of times slower.

The VMs' images and disks are in `/var/lib/builderbot/vms` on the node,
owned by the jobs account, which is in the libvirt group; no session can
reach libvirt. Removing VM host is refused while any VM is there, and takes
off exactly the packages its install added.

## What a VM is made from

An OS from `config/vm-images.json`, asked for by name in any of the ways a
person says it (`debian`, `Debian 12`, `ubuntu-24.04`, `noble`, `rocky`,
`leap 16`): Ubuntu 26.04 and 24.04, Debian 13 and 12, Fedora 44, Rocky Linux
10 and 9, AlmaLinux 9, CentOS Stream 9, Arch, openSUSE Leap 16 and
Tumbleweed, Gentoo, Alpine 3.24. Gentoo's image is a dated build, which the
catalog moves on by hand. Each is its publisher's cloud image, downloaded once per node
and checked against the checksum file the publisher posts beside it before
it is kept. cloud-init makes one account (`builder`, sudo without a password)
that lets in the ssh keys given and no password. `bb vm os` lists them.

Windows and macOS are in the catalog only to be refused by name: each has a
license to accept or a key to enter, which a session never does for a
person, and BuilderBot does not make them.

## The dial, the area and the limits

- **Make VMs**, under Claude may in the project's settings, reads as Run its
  container does: deny (the default) refuses a session's `bb vm`, ask holds
  each for the administrators' bell with Allow and Deny, auto does it. A
  person may always do from the page what the dial holds a session to
  asking for. Changing it is the VMs area's.
- **VMs**, a project area in the roles: Read sees its VMs, Write makes,
  starts, stops, snapshots and removes them. Every role that held Containers
  was given VMs at the same level when this arrived (state migration 0002).
- **What its VMs may hold** in the project's settings: how many, and their
  vCPUs, memory and disk added up (4, 8, 16 GB and 200 GB by default). Each
  node keeps 2 GB of memory and 10 GB of disk for itself besides. A VM that
  would pass either is refused with the limit named.

## The network

Each project has a network of its own on each node, a /24 out of
10.232.0.0/16 kept for it, NAT'd to the internet. A table of BuilderBot's
own (`builderbot_vmnet`) keeps a VM off other projects' VMs, off the LAN
(unless the node's Features row lets its VMs onto it), and off the node
itself but for the DHCP and DNS libvirt serves; the controller's address and
port it reaches. Its project's sessions reach it, by ssh and anything else,
through the sessions' own table; no other project's session does.

## Snapshots

A VM's state saved under a name and gone back to, as in VMware: libvirt's
own, inside its qcow2 disk. A running VM's memory is kept too, so a revert
lands where it was, mid-program. Listed under its row with Revert and
Delete; `bb vm snapshot NAME SNAP`, `bb vm revert NAME SNAP` and `bb vm
snapshot-rm NAME SNAP` from a session, under the same dial. A snapshot taken
before Claude changes a VM is the undo.

## Made a node

New VM's **Make it a node** and `bb vm new --node-agent` enroll the VM as a
node at its first boot: Enroll node's own script, for the OS's system, run by
cloud-init and removed once it has run. It appears on the Nodes page marked
as a VM on its host, and is retired with its credential revoked when the VM
is removed. A session's is always an administrator's to allow, whatever the
dial says: adding a node is theirs.

A VM made a node is not on its project's network. It joins the LAN through
the host's own interface (macvtap) and takes an address from the LAN's DHCP
like any other machine, because the controller reaches a node at its address
(its sessions' terminals, its Docker over SSH), which a project network
behind the host's NAT does not give it. Its firewall is the one the
provisioner makes on every node, and the VMs page shows the address its
agent dials in from. A macvtap guest cannot talk to its own host, so a
controller that runs on the VM host itself does not reach it: put node VMs on
another machine than the controller's.

## Console and Screen

**Console** on a running VM's row opens its serial console in the dock,
`virsh console` as the jobs account on the node's container terminal
server, for a person with a shell and VMs Write on its project. Ctrl+]
leaves it.

**Screen** opens the VM's display in the dock: keyboard, mouse and all,
drawn by noVNC, which the image carries. Every VM has one, on its host's
loopback alone; the node's agent relays it on port 7684, which it opens to
the controller alone beside the terminals' ports, and only for a request the
controller signed for that VM within the last two minutes. It takes VMs
Write on the VM's project, since seeing a screen is driving the machine.
A screen password set at New VM is asked for when it opens.

## From an installer

For a system the catalog does not carry (Windows, a BSD, an appliance, a
distribution of your own), New VM's **From** has **Add an ISO…**: an https
address and the SHA-256 its publisher gives, fetched onto the node and
kept only when it matches. The ISO is then offered under **From** on that
node. A VM made from it boots the installer with a blank disk of the size
given, UEFI or BIOS as picked, and nothing of BuilderBot's inside it (no
account, no key, no cloud-init): its **Screen** is where you install it.
Once the system is on its disk, **Eject ISO** under More empties the drive
so it boots from the disk. Making one is a person's: a session has no screen
to install from, and is refused.

**More** at New VM gives any VM up to three further disks (vdb to vdd), a
MAC address kept for good (so a DHCP reservation holds) and the screen's
password; every disk hands freed space back to the pool (discard). **Grow
disk** on a stopped VM makes one of its disks larger, never smaller; the
partition inside is the system's own to grow.

## From a session

```
bb vm                       this project's VMs: state, OS, node, address, size, snapshots
bb vm os                    the operating systems there are
bb vm new db --os debian --mem 4G --disk 30 --why "a database to test the migration on"
bb vm ssh db                in, as builder, with the session's own key (made when there is none)
bb vm snapshot db clean     before changing it
bb vm revert db clean       and back
bb vm rm db
```
