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
(compressed with zstd). Every partition has a fixed UUID, the same on every
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
for Proxmox, Unraid and libvirt, and `builderbot-os-VERSION.ova` for VMware
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
`.github/workflows/build-image.yml`): on every release tag, and from the
Actions page's *Run workflow* with its *appliance* box ticked. The files land
on the release beside the controller bundle, the disk and the slot with a
build attestation.

By hand, on a Debian or Ubuntu machine with root (mkosi installs packages,
and the disk is assembled on a loop device):

```bash
pip install mkosi==25.3          # the version build.sh pins
sudo apt install squashfs-tools dosfstools e2fsprogs fdisk grub-efi-amd64-bin grub-pc-bin grub-common zstd
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

**Update window.** By default nothing is applied by itself. Under
Controller settings, *Update window* names a day (daily, or one weekday)
and an hour; in that hour a newer release is applied the way Update does
it, once per release, and the restart still waits for you.

## What is not here yet

The boot of each image in CI before it ships (R160 step 5), the weekly
rebuild (step 6), and the USB edition with its boot counting, Safe mode and
the slot kept only once it says it is healthy (R161) each build on this
image.
