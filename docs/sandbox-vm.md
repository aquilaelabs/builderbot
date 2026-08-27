# The Docker sandbox VM

A small virtual machine whose only job is to run Docker, so that a Claude
session can build, run and destroy containers without any of it reaching the
server's real ones.

BuilderBot stays exactly what it is — the container, on the projects share,
with the GPU and the emulator and the runner. Only the *daemon* moves. It is
one environment variable on BuilderBot's side.

## Why a VM rather than a network

Four separate paths reach the box's real containers from inside BuilderBot,
and a shared Docker network closes only the first:

1. **Container to container.** BuilderBot sits on the default bridge, flat
   with every other bridge-mode container on the box.
2. **Host-published ports, through the default gateway.** Measured: a `curl`
   to `172.17.0.1:<published>` answers. Network membership does not close
   this; only host firewall rules would.
3. **The socket proxy.** `DOCKER_HOST` is in every session's environment and
   resolving `auto` is a scan, so a session finds the proxy the same way the
   dashboard does. A far bigger lever than any HTTP port.
4. **The dashboard's own API**, which holds the same credential a session
   does.

A VM answers all four at once — and the point worth holding on to is that it
does not *add* a layer. It lets you take one away: once dev instances run in
the VM, **BuilderBot has no reason to reach the host's daemon at all**, so the
socket proxy comes off the board entirely.

Two things also get better on the way:

- **The layer cache comes back.** BuilderBot forces the classic builder today
  (`DOCKER_BUILDKIT=0`) because buildx boots a helper container and *attaches*
  to it, which a socket proxy worth having refuses. Against the VM's own
  daemon there is no proxy in the way, so buildx and its inline cache work.
- **The host-path problem disappears** rather than being mapped around. See
  *path parity* below.

## Path parity, which is the whole design

Mount the projects share into the VM **at the same path BuilderBot uses**:
`/workspace`. Do the same for the dev-data path: `/devdata`.

This is not tidiness. A compose file's bind-mount *source* is resolved by
whatever runs the container, so if both machines call the share `/workspace`,
a relative bind like `./data:/data` means the same directory whichever side
asks. Mount it anywhere else and every project's compose file is wrong in the
worst way available: Docker does not fail on a missing bind source, it creates
an empty directory and mounts that, and the app comes up with no data.

`DOCKER_HOST_PATHS` exists precisely because today's daemon is the host's and
its paths are not BuilderBot's. Give the sandbox parity and that setting
becomes an identity mapping you can leave empty.

## The disk

**qcow2**, and let it grow.

Unraid's VM manager is libvirt and QEMU, so qcow2 is native; it is sparse, so
a 64G disk costs what is written to it and not 64G; and it takes snapshots,
which is worth a great deal on a machine whose whole purpose is being wrecked
and reset. Raw is marginally faster and gives up both. VHD is Hyper-V's format
and there is no reason to reach for it here.

Start at **64G virtual**. Actual use begins around 2–3GB and grows with the
image store. To expand later:

```bash
qemu-img resize /mnt/user/domains/bb-sandbox/vdisk1.qcow2 +32G
```

then grow the partition inside the guest — or nothing at all, if you built it
from a cloud image: `growpart` runs at every boot and takes the new space on
its own.

## Building it

Two paths. The second needs no tooling on your side at all.

### From a cloud image (automatic)

Download a Debian 12 **genericcloud** qcow2, resize it, and boot it with the
seed in `vm/cloud-init/` attached as a second drive labelled `cidata`. Fill in
the ssh key and the share tags first. `growpart` sizes the root filesystem,
cloud-init installs Docker and mounts the shares, and the machine is ready on
first boot.

### From an ordinary install (reliable)

Install Debian 12 or Ubuntu in an Unraid VM the way you would any other, then
run one script inside it:

```bash
curl -fsSLO https://raw.githubusercontent.com/<org>/BuilderBot/main/vm/provision.sh
sudo bash provision.sh \
    --user bb \
    --key "ssh-ed25519 AAAA…"          # BuilderBot's public key
    --share workspace:/workspace \
    --share devdata:/devdata
```

It is safe to run again; every step checks before it acts.

## Unraid settings that matter

- **Network: bridged (`br0`).** The VM gets its own address on your LAN, which
  is what makes a container's web UI reachable at `http://<vm-ip>:<port>` from
  your browser with no forwarding and no proxy.
- **Shares: pass them to the VM** rather than exporting NFS, where your Unraid
  version offers it — that is virtiofs on recent releases and 9p on older
  ones, and either beats a network filesystem on the same host. NFS is the
  fallback, and `provision.sh --nfs` writes those entries instead.
- **Guest agent.** `qemu-guest-agent` is installed by both paths so Unraid can
  shut the VM down cleanly instead of pulling the plug.

## Pointing BuilderBot at it

One variable in the container's template:

```
DOCKER_HOST=ssh://bb@<vm-ip>
```

ssh rather than an open Docker port: authentication is the key you installed,
and nothing has to listen. `provision.sh --tcp` will expose `2375`
unauthenticated if ssh proves awkward — that is root on the sandbox to anyone
who can reach it, which is tolerable only because the sandbox holds nothing.
Keep it off the LAN either way.

Then remove the socket proxy's address, and the proxy itself. BuilderBot no
longer needs the host's daemon.

## What is deliberately not in it

No GPU, no Android SDK, no Playwright, no Actions runner. They stay in
BuilderBot, where the hardware and the shares already are. The sandbox is a
Docker host and nothing else, and keeping it that way is what makes throwing
it away cheap.
