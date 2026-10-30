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
  libvirt, Samba and NFS, NUT for a UPS, and the disk tools the Storage
  page uses (smartmontools, ZFS, mergerfs, SnapRAID).
- **No apt.** `apt` and `apt-get` are diverted to a stub that says why: the
  root forgets at the next boot, and a package installed into it would be
  gone without a word. A tool a project needs is a toolchain, from the
  Library; a package the node needs is added to
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

Beside the disk, the build leaves the slot's squashfs (`.root.squashfs`),
its kernel and initrd, and the release stamp, each with a `.sha256`; the ISO
carries the same four under `live/`, which is where an update takes them
from.

## On a stick, run from memory

The same disk written to a USB stick is the USB edition's base (R161): with
`bb_toram=1` in GRUB's environment (`slot ram on`; the stick maker sets
it) the initramfs copies the slot's squashfs into memory, exactly its
bytes, and the root is that copy, so the stick is read once at boot and the
system runs from memory; `/var` and `/etc`'s changes stay
on the stick's data partition, apart from both slots, and an update writes
the other slot as on a disk. `slot status` says when the root is in memory.
A machine needs the slot's size in memory beside what it runs (about 2 GB).

**The stick is written rarely.** Flash wears with every write, and many
small synced writes are what make a stick slow, so on a stick boot it keeps
the configuration and little else. Its data partition is flushed once a
minute rather than every five seconds. The system's logs (`/var/log`), the
controller's own logs and the journal are kept in memory, so they start
again at each boot; the controller's logs go to a pool when Controller
settings' paths put them there. What writes all day, docker's images and
containers, the VMs, the toolchains and the projects, lives on a **system
pool**: picked under This machine's **The stick** from the pools and the
array the machine has, it is where those folders are bound at every boot,
and picking it moves what the stick held of them there. Until one is
picked, docker and the VMs wait, and sessions still run, their projects on the stick. **The stick**
also says what still lives on the stick and how much has been written to it,
in its life and since this boot. An installed disk has none of this: its
data partition is the machine's disk.

**The data partition takes the stick's room.** The image's data partition
is 2 GB; at each boot it is grown to the end of the stick (the filesystem
with it, while mounted) and never shrunk. `BB_DATA_MAX` in `builderbot.env`
caps it (`64G`, `512M`, `2T`; a bare number is GiB), to leave the rest of a
big stick unused.

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
checking back in. Pushing a copy to another BuilderBot or a node is not
here yet.

## The stick maker

`tools/builderbot-stick.py` writes a release's stick image onto a USB
stick on Windows, a Mac or Linux with nothing but Python's own library: `list`
names the removable disks here (the system disk marked, and never written),
`write DISK` fetches the newest release's `builderbot-os-VERSION.stick.raw.xz`
(or `--release vX.Y.Z`'s, or writes `--image FILE`) with its sha256, checks
it, says what is on the stick is lost, writes the disk whole and reads it
back; `verify` reads a stick back against an image. `--set KEY=VALUE`, as
often as needed, writes a line into the stick's `builderbot.env`, the file on
the ESP each boot reads: `TZ` (`Europe/Berlin`) and `BB_RELEASE_LINE` (the
release line updates follow, `0.9`) for the controller, and the stick's
network settings. `BB_HOSTNAME` names the machine; `BB_NET_ADDRESS`
(`192.0.2.20`) gives the wired interfaces a static address instead of
DHCP, with `BB_NET_MASK` (`24` or `255.255.255.0`, `24` when left out),
`BB_NET_GATEWAY` and `BB_NET_DNS` (`1.1.1.1,9.9.9.9`). `BB_DATA_MAX` caps the
stick's data partition (below). A value that is not
an address is said in the boot's log and DHCP stands, so a mistyped stick
still comes up on the network. The file is 4 KiB laid by the image itself, and
the maker writes the lines into those same bytes as the image streams, so
nothing writes a FAT partition by hand on any system; with the stick in
another machine it is a plain file to edit, and `verify` takes the same
`--set` to read such a stick back.

`--mirror FILE` writes a mirror of the vetted catalog (the archive
`tools/catalog-mirror.py` makes, up to 64 MiB) into the stick's
`builderbot/catalog-mirror.bin`, laid and filled the same way. Each boot
hands it to the controller, which imports it as it starts, once per mirror,
so a machine with no network installs tool packs from the Library (Tool
packs' Without the network says how the mirror is used). The stick keeps
it; it holds nothing secret.

`--config FILE` writes a prepared configuration into the stick's
`builderbot/firstboot.json` (64 KiB, laid and filled the same way), which the
first boot applies before anyone signs in. It is a JSON object:

```json
{"format": 1, "first_run": "skip",
 "machine": {"hostname": "tower", "timezone": "Europe/Berlin",
             "network": {"address": "192.0.2.20", "netmask": "255.255.255.0",
                         "gateway": "192.0.2.1", "dns": ["1.1.1.1"]}},
 "owner": {"name": "ada", "password_hash": "pbkdf2_sha256$600000$SALT$HASH"},
 "people": [{"name": "sam", "role": "user", "smb_nt": "NTHASH"}],
 "shares": [], "pools": [], "array": {}, "apps": []}
```

Before the controller starts, the boot sets the hostname and the time zone,
writes a static address (`"network": "dhcp"` or leaving it out keeps DHCP)
into the stick's `builderbot.env` as the `BB_NET_` lines above, unless the
stick already names one, hands the rest to the controller and blanks the file on the stick, so the
password hash is never left there. The controller makes the owner from the
hash (the dashboard's own scheme, so a tool that writes the file hashes what
was typed) and each person by name and role, with their SMB password where
it came with them and no dashboard password until the owner sets one on the
Users page. `"first_run": "skip"` marks the setup page done, and `"hold_first_start": true`
holds that first start, so the disks are on This machine before anything
mounts; without an
owner's hash the first-run page makes the owner as on any stick. The shares,
pools, array and apps wait until their disks are adopted. This machine's
**From the stick** section says what was applied, what waits and what could
not be, and nothing of a hash is kept on the controller beyond the accounts
themselves. It runs as root (sudo) on Linux and a
Mac and as an administrator on Windows, where it locks and dismounts the
stick's volumes first. A stick made this way boots the appliance with the
slot loaded into memory and keeps its configuration on the stick's data
partition. Its network settings are the `BB_NET_` lines in `builderbot.env`;
without them the stick takes DHCP.

## Its disks at the first run

A machine that is its own controller has a disks step in its first run,
after This machine. It lists every disk but the one it runs from, by model,
size, kind and serial; a disk that holds something is kept unless you tick
it. You say how safe the storage should be (no copy, one disk may fail, two
disks may fail) rather than pick a RAID level, and it picks the layout from
the disks and says why: disks of one size become a ZFS mirror, raidz1 or
raidz2, which checks every block and repairs one that rots; disks of mixed
sizes become an array with its largest disk as parity, which uses every
disk and grows one at a time; an SSD beside hard disks becomes a fast pool
of its own for apps, VMs and projects, never a cache. As you choose it says
how much you can use, how many disks may fail and how it grows, and
Advanced picks another layout. **Make it** names every disk it erases by
serial before anything is written, and then one press makes the Media,
Backups and Projects shares on it. The Storage page does all of this too,
later, the same way.

## At the console

A machine running BuilderBot OS welcomes whoever is at its screen with
BuilderBot's logo above the login prompt, the release and slot it runs, and
the address to open the dashboard at (this machine's address and the
dashboard's port), which the console fills in and redraws as the network
comes up. The installer opens on the same logo. Both are plain characters,
so a serial console or a server's remote screen draws them too.

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

## In a VM

A VM installs from the ISO as a machine does: give it a disk of 16 GB or
more, boot the ISO and pick that disk. It boots into the bare-metal
controller with the machine as its own node, as a stick or an installed
disk does. The build also converts the raw disk, never laid out again, into
`builderbot-os-VERSION.qcow2` and `builderbot-os-VERSION.ova` (a
stream-optimized VMDK with its OVF descriptor, `image/ovf.xml`, and a
manifest), which the boot test runs and the CI run keeps as its artifact;
a release does not carry them. Give the VM two processors and 4 GB at least, and
turn nested virtualization on for it where VMs are to run inside it (the
Features row says when `/dev/kvm` is missing); the data partition is grown
to the disk the hypervisor gives it at boot, so a disk made bigger later is
taken up at the next one.

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
An updated slot's trial and Safe mode are under [Updating](#updating).

## Building it

CI builds the image on a hosted runner with a workflow of its own,
`.github/workflows/os-image.yml`, which builds it and then boots the VM
disk under QEMU until the dashboard answers (`appliance-boot`). The image
build calls it on every release tag, from the Actions page's *Run
workflow* with its *appliance* box ticked, and weekly; a branch push that
touches the image runs it alone and publishes nothing, so a fix to the
image is proved on a push. A release carries two of its files, the ISO and
the stick's image, each with its sha256 and a build attestation, and only
after the boot (`appliance-publish`); the raw disk, the qcow2 and the OVA
stay the run's artifact.
The weekly run takes the day before's snapshot, builds, and says in its
summary which system packages moved since the last release (each image
carries its package list, `.packages`); a patch release from it is a press
on a tag, never the run's own doing.

By hand, on a Debian or Ubuntu machine with root (mkosi installs packages,
and the disk is assembled on a loop device):

```bash
pip install 'mkosi @ https://github.com/systemd/mkosi/archive/refs/tags/v25.3.tar.gz'   # the version build.sh pins; mkosi is not on PyPI
sudo apt install squashfs-tools dosfstools e2fsprogs fdisk grub-efi-amd64-bin grub-pc-bin grub-common xz-utils xorriso mtools qemu-utils
sudo image/build.sh --out image/out
```

`--tree-only` stops after mkosi, with the tree under `image/out/mkosi/tree`
to look at; `--from-tree DIR` assembles a disk from a tree built before.
Moving the pin is editing `image/SNAPSHOT` to a newer timestamp; the weekly
rebuild takes the day before's snapshot on its own.

## Updating

A newer release is found the way a bare-metal install's is (checked weekly
unless Controller settings' Update checks says otherwise, and on **Check
now** under Controller settings, Updates, and said on the bell). It follows
the release line the install is on (`BB_RELEASE_LINE`, which the stick
maker's `--set` writes) and the releases as published; the dev builds'
channel is in [versions.md](versions.md#two-channels). On BuilderBot OS **Update** does not run the installer: the own
node's root agent fetches the release's ISO, checks it against the sha256
the release carries and against its build attestation (`gh attestation
verify`; an image that does not verify, or a machine without `gh`, writes
nothing), opens it read-only and takes the root, the kernel, the initrd and
the stamp out of its `live/` folder as plain files, points the next boot
back at the slot running now, writes the slot not in use, puts the kernel
beside it on the ESP, and only then names that slot for the next boot, on
trial, in one write. An update is refused while the slot running now is
itself on trial, since the other slot is then the only good one, and when
a second BuilderBot disk or stick in the machine carries the same slot.
Nothing running changes until you restart
from This machine, and the slot running now stays to fall back to: at the
GRUB menu, or with `slot next a`. The Updates section says which slot runs
and which boots next.

An offline machine takes the same files from a folder on it (a stick, a
share): **Update from the folder** under Updates, the folder holding the
release's ISO with its `.sha256` and its `.attestation.jsonl` beside it,
all three from the release. The ISO is checked against both with no
network: the attestation against the trusted root the running image was
built with, so a folder on a share others can write cannot hand over an
image BuilderBot's release workflow did not build. A release's attestation
is read from GitHub's public API, and neither way asks for a sign-in.

**On trial.** The slot an update wrote boots on trial: GRUB counts each
boot of it in its environment, and the health check
(`builderbot-os-health.service`) marks it good once the controller's health
answer (`/api/v1/healthz`) says it is up, three times running, and the
node's agent runs. A trial boot that is not healthy
within ten minutes restarts, a kernel or initramfs that panics restarts
after fifteen seconds, and a kernel that will not load falls to the slot
before at once; a second boot without the health check's word goes back to
the slot before by itself, and This machine says so until the next update.
Picking the slot before from the menu during a trial ends the trial there.
Before an update the controller's configuration is copied to
`/var/lib/builderbot-os/before/` (the two newest kept). A boot that fell
back puts that copy back before the controller starts, when the newer slot
moved the configuration on further than the slot before reads; what it held
is kept in `/var/lib/builderbot-os/rolled-back-TIME/`. A patch carries no
configuration change, so falling back on one boots the same configuration
as it is.

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

The boot in CI does not yet try a ZFS pool and an array on virtual disks, a
share over SMB, a node enrolled and a container started, or the browser
suites against the booted system; those are proved by hand on a machine
for now.
