# BuilderBot OS: the appliance image

The installed editions of BuilderBot (the installable OS, its VM disk, and
the USB edition) are made from one image: Debian stable, built by
[mkosi](https://mkosi.systemd.io/) from the definition in `image/`, sealed as
a read-only root and laid into a disk with two root slots. An update is a
whole new root written into the slot not in use, and a bad one falls back
to the one that was. This page says what the image is, what persists on it,
how it boots, and how it is built. The decisions behind it are in
[decisions.md](decisions.md), "The appliance image".

## What it is

- **Debian 13 (trixie), x86-64**, every package pinned to one dated
  [snapshot.debian.org](https://snapshot.debian.org) archive, named in
  `image/SNAPSHOT`, so a build from the same inputs is the same image.
- **The kernel Debian ships, with ZFS built against it** in the image
  (`zfs-dkms` at build time), so the two never part.
- **The controller staged in**, exactly as a bare-metal install lays it out
  (`nodes/install-controller.sh --stage`, run inside the tree by
  `image/mkosi.postinst`): the account, `/opt/builderbot`, the env file,
  `bb`, the sudo rule and the service, enabled for the first boot. Its
  packages come from the one list the container image and a bare-metal
  install read, `config/controller-packages.tsv`.
- **Everything the node half needs**: what `nodes/provision-linux.sh`
  installs on a Debian node (python, tmux, git, the reel's X tools,
  WireGuard, nftables), Debian's own docker, the VM host's qemu and
  libvirt, Samba and NFS, and the disk tools the Storage page will use
  (smartmontools, ZFS, mergerfs, SnapRAID).
- **No apt.** `apt` and `apt-get` are diverted to a stub that says why: the
  root forgets at the next boot, and a package installed into it would be
  gone without a word. A tool a project needs is a toolchain, from the
  Toolchains page; a package the node needs is added to
  `image/mkosi.conf` and comes with the next image.

## The disk

`image/build.sh` lays the image into one GPT disk, `builderbot-os-VERSION.raw`
(compressed with xz), and the same disk with the slot loaded into memory at boot as `builderbot-os-VERSION.stick.raw.xz`, the USB edition's. Every partition has a fixed UUID, the same on every
disk BuilderBot makes, held in `image/partitions.sh` and read by the build,
the initramfs, `fstab` and GRUB alike:

| Partition | Size | What |
|---|---|---|
| `bios` | 1 MiB | GRUB's core for a BIOS boot |
| `esp` | 512 MiB | the ESP: GRUB for UEFI and BIOS, one menu, its environment, each slot's kernel and initrd under `/builderbot/a` and `/builderbot/b` |
| `bbroot-a` | 4 GiB | root slot A: a squashfs, read-only |
| `bbroot-b` | 4 GiB | root slot B: empty until an update writes it |
| `bbdata` | 2 GiB in the image, the rest of the disk when installed | `/var`, and under it the changes to `/etc` |

Beside the disk, the build leaves the pieces an update and the stick maker
take: the slot's squashfs (`.root.squashfs`), its kernel and initrd, and the
release stamp, each with a `.sha256`.

## On a stick, run from memory

The same disk written to a USB stick is the USB edition's base (R161): with
`bb_toram=1` in GRUB's environment (`slot ram on`; the stick maker sets
it) the initramfs copies the slot's squashfs into memory, exactly its
bytes, and the root is that copy, so the stick is read once at boot and the
system runs from memory; `/var` and `/etc`'s changes stay
on the stick's data partition, apart from both slots, and an update writes
the other slot as on a disk. `slot status` says when the root is in memory.
A machine needs the slot's size in memory beside what it runs (about 2 GB).
The stick's own first run, its backup and the public stick maker are the
USB edition's later steps.

## The configuration backed up, and a new stick

With a backup password set under Controller settings, Backup, the
controller keeps a sealed copy of its configuration (the same bundle a move
carries: the state without its logs, the stores, the secrets; never the
repositories) after every change, once the state has been quiet for a
quarter of an hour: under the state, and on every pool of the machine at
`/mnt/POOL/.builderbot/backup`, the five newest in each; Back up now writes
one at once, and each copy under the state is downloadable. The key is the
password's (scrypt), so a copy carried off is a sealed file.

A stick that dies is replaced by one written from the release's image with
no configuration: its first page offers *Restoring a saved configuration*,
lists the copies found on the machine's pools (newest first, with the
machine and the version each came from) and takes the password, or takes a
copy you kept; held to the same gate as a move (never onto an older build),
restored and restarted, the machine is the controller as it was, its nodes
checking back in. Pushing a copy to another BuilderBot or a node is the
step's next piece.

## The stick maker

`tools/builderbot-stick.py` writes a release's stick image onto a USB
stick on Windows, a Mac or Linux with nothing but Python's own library: `list`
names the removable disks here (the system disk marked, and never written),
`write DISK --latest` (or `--release vX.Y.Z`, or `--image FILE`) fetches
`builderbot-os-VERSION.stick.raw.xz` with its sha256, checks it, says what
is on the stick is lost, writes the disk whole and reads it back; `verify`
reads a stick back against an image. It runs as root (sudo) on Linux and a
Mac and as an administrator on Windows, where it locks and dismounts the
stick's volumes first. A stick made this way boots the appliance with the
slot loaded into memory and keeps its configuration on the stick's data
partition. The stick's own network settings file (a plain file on the ESP,
read at boot and written by the Network page) is the Network page's
bare-metal half; until then the stick takes DHCP.

## Installing it on a machine

`builderbot-os-VERSION.iso` boots the same root live (UEFI or BIOS) with
the installer on the console: it lists the machine's disks (the medium it
booted from left out), asks which one to lay out and says that everything
on it is lost, asks which features to turn on at the first boot (VM host
and the hosting firewall on, the IOMMU off), then lays the disk out with
the very script that made the image (`image/lay-disk`, carried in the
image at `/usr/lib/builderbot-os/lay-disk`), the data partition grown to
the disk, and asks for a restart. Nothing else is asked: the first boot
makes the machine its own node with those features, and the dashboard's
first page, at `http://ITS-ADDRESS:7680` on the LAN, makes the owner and
names the machine. The ISO's second entry boots the live system without
installing, for a look or a rescue.

## The same disk for a hypervisor

The raw disk is converted, never laid out again, into `builderbot-os-VERSION.qcow2`
for Proxmox, libvirt and other QEMU hosts, and `builderbot-os-VERSION.ova` for VMware
and VirtualBox (a stream-optimized VMDK with its OVF descriptor,
`image/ovf.xml`, and a manifest): the easiest way to try BuilderBot, and to
keep it apart on a hypervisor, its snapshots the hypervisor's. The VM boots
into the bare-metal controller with the machine as its own node, as a stick
or an installed disk does. Give it two processors and 4 GB at least, and
turn nested virtualization on for it where VMs are to run inside it (the
Features row says when `/dev/kvm` is missing); the data partition is grown
to the disk the hypervisor gives it at the first boot once R160 step 2's
installer lands, and is 2 GB until then.

## What persists

The root is read-only, with a tmpfs over it (`overlayroot`): anything
written anywhere in it lives until the next boot. Two places are made to
last, both on the data partition and both mounted by the initramfs
(`image/mkosi.extra/etc/initramfs-tools/scripts/init-bottom/builderbot-os`)
before the system starts, so PID 1 sees them from its first read:

- **`/var`**, the data partition itself: the controller's state and
  secrets' home, the projects, docker, libvirt, the logs.
- **`/etc`**, as an overlay whose upper half is `/var/lib/builderbot-os/etc`:
  an account made, a hostname set, a unit enabled or a share written is kept
  across boots, and every file the next image brings still shows through
  unless a changed copy sits over it.

Nothing else persists, which is what makes an update a whole image.

## How it boots

GRUB on the ESP reads its environment (`grubenv`) for `bb_slot`, the slot to
boot, and shows both slots in its menu for three seconds. The slot's kernel
and initrd are on the ESP; the kernel's command line names the slot's root
partition by its UUID and the slot by name (`bbslot=a`). The initramfs mounts
the squashfs, puts the tmpfs over it, mounts `/var` and `/etc`'s overlay,
and the system starts.

The first boot of a disk runs `builderbot-os-firstboot.service` once: it
waits for the controller, which the image's own service started, puts up
the wall between the controller and the sessions, and enrolls the machine as
its controller's own node, as a bare-metal install's last step does. From
there the machine is what [install.md](install.md)'s bare-metal section
describes, and its page is This machine.

`/usr/lib/builderbot-os/slot` is the slot tool: `current` (the slot this
boot came from), `other`, `next [a|b]` (the one GRUB boots next time, which
is what an update sets once it has written the other slot) and `status`.
Counting a new slot's tries, marking it good, and Safe mode are the USB
edition's boot work (R161 step 2), on top of this.

## Building it

CI builds the image on a hosted runner (`appliance` in
`.github/workflows/build-image.yml`): on every release tag, from the
Actions page's *Run workflow* with its *appliance* box ticked, and weekly.
Before anything of it is published, `appliance-boot` boots the VM disk
under QEMU and waits for the dashboard to answer; a release's files land
only after that (`appliance-publish`), beside the controller bundle, each
of the disk, the ISO, the VM disks and the slot with a build attestation.
The weekly run takes the day before's snapshot, builds, and says in its
summary which system packages moved since the last release (each image
carries its package list, `.packages`); a patch release from it is a press
on a tag, never the run's own doing.

By hand, on a Debian or Ubuntu machine with root (mkosi installs packages,
and the disk is assembled on a loop device):

```bash
pip install mkosi==25.3          # the version build.sh pins
sudo apt install squashfs-tools dosfstools e2fsprogs fdisk grub-efi-amd64-bin grub-pc-bin grub-common xz-utils xorriso mtools qemu-utils
sudo image/build.sh --out image/out
```

`--tree-only` stops after mkosi, with the tree under `image/out/mkosi/tree`
to look at; `--from-tree DIR` assembles a disk from a tree built before.
Moving the pin is editing `image/SNAPSHOT` to a newer timestamp; the weekly
security rebuild (R160 step 6) will do that on its own.

## Updating

A newer release is found the way a bare-metal install's is (checked daily
and on **Check now** under Controller settings, Updates, and said on the
bell). On BuilderBot OS **Update** does not run the installer: the own
node's root agent fetches the release's image files (the root, the kernel,
the initrd, the stamp), checks each against the sha256 the release carries
and the root against its build attestation (where `gh` is on the machine),
writes the slot not in use, puts the kernel beside it on the ESP, and names
that slot for the next boot. Nothing running changes until you restart
from This machine, and the slot running now stays to fall back to: at the
GRUB menu, or with `slot next a`. The Updates section says which slot runs
and which boots next.

An offline machine takes the same files from a folder on it (a stick, a
share): **Update from the folder** under Updates, the folder holding the
release's four files with their `.sha256` beside them.

**On trial.** The slot an update wrote boots on trial: GRUB counts each
boot of it in its environment, and the health check
(`builderbot-os-health.service`) marks it good once the dashboard answers
and the node's agent runs; a second boot without that word goes back to
the slot before by itself, and This machine says so until the next update.
Before an update the controller's configuration is copied to
`/var/lib/builderbot-os/before/` (the two newest kept), so the slot before
boots the configuration it had; a patch carries no configuration change,
so falling back on one boots the same configuration as it is.

**The boot menu.** Each slot is named with its version, the slot that
boots is the default after four seconds, and **Safe mode** boots the slot
that runs now with the start held: the dashboard and the shares come up
and nothing else starts (no container, VM or session) until Start is
pressed on This machine.

**Update window.** By default nothing is applied by itself. Under
Controller settings, *Update window* names a day (daily, or one weekday)
and an hour; in that hour a newer release is applied the way Update does
it, once per release, and the restart still waits for you.

## What is not here yet

What the boot in CI does not yet try (a ZFS pool and an array on virtual
disks, a share over SMB, a node enrolled and a container started, the
browser suites against the booted system) lands with the storage work
(R162), the canary on the dev pair with it; the USB edition with its boot
counting, Safe mode and the slot kept only once it says it is healthy
(R161) builds on this image.
