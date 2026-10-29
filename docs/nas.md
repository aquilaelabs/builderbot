# BuilderBot as a NAS: the design

What the installed edition does with disks, and what it leaves to the
kernel and to the daemons that already do it well. The decisions are the
operator's (R56, R115 and R162, 18 to 27 Oct 2026) and [decisions.md](decisions.md)
carries them with their dates; this page is the design they add up to,
written down before the storage module lands (R162) so the module is built
to it rather than the other way round.

## Python is the management plane, never the data path

The dashboard and the root agent on the controller's own machine make
pools, datasets, shares and schedules, watch health and say what they see.
Not one byte of a person's data goes through them. Samba and NFS serve the
shares, the filesystems (ZFS, XFS, btrfs) and the kernel's block layer hold
the data, SnapRAID computes parity, and each runs as its own daemon under
systemd. The dashboard stopped or crashed changes nothing a share serves
(R56 step 6 is the test that proves it: the dashboard killed mid-copy, the
share read back whole). A change to storage is a job from the root agent's
fixed table with checked arguments, audited under the person's name, never
a command string (R56 step 4).

## Two storage profiles

Every NAS makes one choice its own, and the comparison behind these two is
in R56's notes: the per-disk design (a filesystem per disk behind real-time
parity, a union layer and a mover), TrueNAS (ZFS checksums and self-heal, rigid growth, L2ARC and SLOG
that are not a tier), Synology SHR (md slices under btrfs, an SSD cache),
OpenMediaVault (mergerfs with SnapRAID, periodic parity). BuilderBot offers
two, said plainly for what each gives up.

**ZFS pools, the default for matched disks.** Mirrors or RAIDZ2, a dataset
per project and per container's data with quotas, scrubs on a schedule,
snapshots and replication mapped onto BuilderBot's own snapshots and
backups. Checksums on every block and self-heal from redundancy are what a
build machine's data wants; the price is that a pool grows by whole vdevs,
and disks in a vdev are alike. Never a special vdev or a SLOG on a single
SSD: losing a special vdev loses the pool.

**An array of mixed disks, as an option.** Disks of mixed sizes, each XFS or
btrfs on its own, pooled by mergerfs with its create policy chosen as the
allocation method (fill-up, most-free, a high-water equivalent), and
SnapRAID on one or two parity disks. Parity is periodic, computed by a
scheduled sync, never real time: a disk lost between syncs loses what
landed since the last one, and the page says so where the option is picked.
A disk is added or replaced one at a time, and a single disk's files are
readable on any machine, which is the reason to want it.

**Pools by purpose, no cache tier.** No mover between a cache and the array (the
operator, 27 Oct): an SSD is a pool of its own holding BuilderBot's hot data
(/config, the project workspaces, toolchains, build caches, apps' data and
VM disks); the hard-disk array holds the shares, media and backups; each
share names the one pool it lives on when it is made, and nothing moves
behind a person's back. A pool of one SSD has no redundancy, so it is
backed up to the array nightly by the snapshots and backups, the result on
the bell, and a dead SSD is restored from last night's.

## What is built on top

- **Encrypted storage**: a ZFS pool or dataset with native encryption, and
  each array disk under LUKS, unlocked at boot by a passphrase typed on the
  page or a key file on the stick (the person's choice, said with what each
  protects against); Safe mode boots with them locked, and a share on a
  locked pool says so rather than vanishing.
- **Other disks and shares**: a USB or eSATA disk, or a remote SMB or NFS
  share, mounted from the Storage page as a backup target or a source to
  copy in, never pooled, unmounted cleanly before it is pulled.
- **Backups and snapshots**: scheduled snapshots per share or pool with
  their keeping, browsable and restorable a file at a time or whole;
  backups off the machine to another node, another BuilderBot or a cloud
  store, each with its last good run on Home and a restore that is walked,
  not assumed.
- **Health**: disks by model, size, serial, SMART health and temperature;
  SMART tests and their results on the bell; room checks over pools as over
  a node's stores.

## What BuilderBot does not build

- **A storage engine.** No filesystem, no block layer, no RAID of its own:
  ZFS, mergerfs and SnapRAID are what they are, packaged by Debian and built
  with the image's kernel so the two never part (the installed edition is
  Debian stable, built with mkosi; R56's decision of 22 Oct).
- **Real-time parity of its own.** A real-time parity driver is its maker's;
  nothing of it is copied, and the array option says periodic where it is periodic.
- **Tiering on an experimental filesystem.** bcachefs is left out while its
  standing in the kernel is unsettled; the cache tier is not built at all
  (pools by purpose, above).
- **A data path through Python.** See the first section: the moment a
  design puts the dashboard between a client and its bytes, it is the wrong
  design.

## Where the pieces are

The storage module is R162 (the Storage page: pools, the array, encryption,
other disks, backups); the machine's own page, network and VMs are R165;
the root agent's table and the installed edition's features are R56 steps
2 and 4; the images and the USB edition are R160 and R161. Each lands as a
feature of the controller's own node, reported in its census as VM host is
today, so the container edition, which has no own node, never offers them.
