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

Download an Ubuntu 26.04 **cloud** image (or a Debian **genericcloud** qcow2),
resize it, and boot it with the seed in `vm/cloud-init/` attached as a second
drive labelled `cidata`. Fill in
the ssh key and the share tags first. `growpart` sizes the root filesystem,
cloud-init installs Docker and mounts the shares, and the machine is ready on
first boot.

### From an ordinary install (reliable)

Install **Ubuntu Server 26.04 LTS** (`ubuntu-26.04-live-server-amd64.iso`) —
headless, no desktop. It is what most Docker instructions assume, it turns on
unattended security updates by default, which is worth having on a box nobody
logs into, and Docker's repository already publishes for it (`resolute`).
Debian 13 works identically if you would rather have the leaner machine;
`provision.sh` accepts either. Then run one script inside it:

```bash
curl -fsSLO https://raw.githubusercontent.com/<org>/BuilderBot/main/vm/provision.sh
sudo bash provision.sh \
    --user bb \
    --key "ssh-ed25519 AAAA…"          # BuilderBot's public key
    --share workspace:/workspace \
    --share devdata:/devdata
```

It is safe to run again; every step checks before it acts.

One thing it does that is worth knowing about, because it is the failure a
fresh release usually hands you: Docker's apt repository can lag a new Ubuntu
or Debian by weeks, and the symptom is an `apt` 404 naming a URL and not a
reason. The script asks the repository which suites exist before committing to
one, and falls back to the newest that does — the packages are the same build,
only the suite name differs — saying so when it does.

## The domain XML

`vm/unraid-domain.xml` is the whole machine. Create the VM in **Form view**
first so Unraid makes the domain folder and the vdisk, then switch to **XML
view** and paste it over what is there — keeping the `<uuid>` Unraid gave you,
because the OVMF nvram file is named after it and a new one orphans it.

Five things in it differ from Unraid's placeholder, each for a reason:

| | placeholder | this | why |
|---|---|---|---|
| machine | `pc-i440fx` | `q35` | UEFI firmware paired with a 1996 chipset; q35 is what OVMF is for |
| clock | `localtime` | `utc` | localtime is a Windows guest's convention |
| memory backing | `nosharepages` | `memfd` + `shared` | virtiofs cannot work without it, and fails *silently* — the mounts simply never appear |
| cputune | vCPU 0 pinned to cpuset 0 | none | that is the host's busiest core |
| disk | *(absent)* | qcow2, `discard=unmap` | so the image shrinks again when Docker prunes, instead of only ever growing |

## Unraid settings that matter

- **Network: bridged (`br0`).** The VM gets its own address on your LAN, which
  is what makes a container's web UI reachable at `http://<vm-ip>:<port>` from
  your browser with no forwarding and no proxy — *and* lets BuilderBot reach
  the daemon.

  **`br0` exists only if bridging is on**: Settings → Network Settings →
  *Enable bridging* → Yes, which needs the array stopped. If the VM dialog
  offers you `virbr0` and `bond0` but no `br0`, that is what is missing.
  `virbr0` is libvirt's NAT network — BuilderBot can still reach the VM, but
  your browser needs a port forward for every web UI. Avoid `bond0` unless you
  can confirm it gives a real bridge rather than **macvtap**, which blocks
  host-to-guest traffic by design and would leave BuilderBot unable to reach
  the daemon at all. That failure is quiet: everything looks up.

- **Network model: `virtio-net`.** The others are emulated legacy NICs, for
  guests without virtio drivers. Ubuntu and Debian both have them.
- **Shares: NFS first, virtiofs once it is up.** virtiofs is the faster
  answer — same host, no network stack — and it is what you want in the end.
  It is not what you want on the first boot: `virtiofsd` is a host-side
  daemon, and when it refuses to start the VM will not start either, with

  ```
  internal error: virtiofsd died unexpectedly
  ```

  which says nothing about which of its several reasons applied. The two
  usual ones are a source directory that does not exist yet, and `/mnt/user`
  being shfs, whose FUSE layer does not give `passthrough` mode the `openat2`
  and xattr behaviour it expects — pointing it at `/mnt/cache/...` or a disk
  path instead often settles it. `virtiofsd`'s own complaint is in
  `/var/log/libvirt/qemu/<vm-name>.log`, and is worth reading before changing
  anything.

  So bring the machine up with NFS, which needs no host-side daemon:

  ```bash
  sudo bash provision.sh --user bb --key "ssh-ed25519 …" \
      --nfs 192.168.1.15:/mnt/user/development:/workspace \
      --nfs 192.168.1.15:/mnt/cache/appdata/builderbot-dev:/devdata
  ```

  (Export both from Unraid: *Shares → share → NFS Security Settings*.)

  To move to virtiofs later, add a `<filesystem>` block per share — the
  `<memoryBacking>` it needs is already in the XML for exactly this — and
  drop the matching `fstab` lines:

  ```xml
  <filesystem type="mount" accessmode="passthrough">
    <driver type="virtiofs"/>
    <source dir="/mnt/user/development"/>
    <target dir="workspace"/>
  </filesystem>
  ```

  The `target dir` is the *tag*, not a path; `provision.sh --share
  workspace:/workspace` is what mounts it.
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
