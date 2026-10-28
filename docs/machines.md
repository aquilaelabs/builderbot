# Machines: the controller, nodes and storage

The Machines group on the rail: **Nodes**, every machine work runs on, and
**Storage**, what a node's disks hold; with them here, **Controller
settings**, in the Home group, what the controller owns and applies live. **Jobs**, the queue of work placed on
the nodes, is a page of its own on the rail. This doc covers enrolling and
running nodes, their stores and their network, the controller's settings and
logs, and the jobs. The design behind nodes is
[nodes.md](nodes.md); the sandbox VM a node usually is,
[sandbox-vm.md](sandbox-vm.md).

## The Nodes page

**Nodes**, under Machines, is the registry ([nodes.md](nodes.md)): every
machine work can run on. This container is not among them; it runs no work,
takes no toolchains, and has nothing any section here configures, so with
nothing enrolled the page says so and offers the one thing there is to do.
(It does keep a node record of its own, which is how a share it mounts is
recognized as the same store a node mounts; that is plumbing, not a node on
the page.) A controller installed bare metal can be a node of itself
([install.md](install.md#bare-metal)): its machine is then an ordinary row
here, marked **this machine**, offered in a project's node pickers as such
and in no container picker, its session network always on, and the Doctor
says whether the wall between its sessions and the controller holds. The
page shows one node, picked in the Machines header over it (R177: one band
for Nodes, Storage and Installed, the node pulldown where a project's name
is, when it was seen, where it dials in from and its agent beside it, and
**Create sandbox VM** and **Enroll node** at the right of the sub-nav's line;
the pick holds across the three pages, and the Build and Containers groups
wear the same header, R178, a sub-tab reading *not here* when the node
lacks its feature): a header with its state, and where it dials in from, which is the address of its
last hello, so a node whose address moves is followed within a minute, its
screen relay rebound onto the new address by its agent and the session-port
rule on the node rewritten if the controller's own address is what moved,
and its agent (with
**Update agent** when this container ships a newer one, busy until the node
comes back on it), then **sections**, each a fold with its status on the
heading so a phone reads the headings and opens one: Health (the meters:
cpu, memory, the card's load and its own memory where an NVIDIA driver
answers, and each store's room; the toolchains its census found, which is what a project bound to it can
build), Projects (the projects bound to it), Sessions (whether it runs them,
and which are open), GPU (where it has a card), USB (on a VM host: each USB
device with what holds it, **Give to a VM** and **Take back**, and its
controllers; [vms.md](vms.md#usb-devices)), Model router (R144, R172: a card of the Library's with this node picked, under Services, where it is configured, deployed and removed; the row here says so), Features (what the machine has
beyond the base, each with **Install** or **Uninstall**: VM host, the IOMMU
on a VM host's kernel command line, and the
hosting firewall on a hosting-only node), Coding agents (one line saying
which are installed there, with the way to the node's **Agents** page, where
each is installed, updated, removed and signed in to), Storage (mounts and stores), Network, and Advanced, which
holds the node's **name** (Rename changes what it is called everywhere here:
the pickers, the project cards and the label a runner installed from then on registers
with; a runner already installed keeps the label it registered with until
it is reinstalled), the path
mapping and the rarely pressed verbs: **Lock down** (a hosting-only node's: every container
there stopped, its door shut and its credential revoked, docs/nodes.md), **Drain** (finish what is running,
accept nothing new: what makes a node safe to reboot), **Clear cache**,
**Revoke**, **Disable** (the operator, 11 Oct: kept and configured, its agent
dialing in, but off every picker, refused to a project's set and handed no
work or session until **Enable**), and **Un-enroll**, which on a node
provisioned as a sandbox that is dialing in uninstalls BuilderBot from the
machine and then removes the node here (retire: off every list, its record kept as
history, and an id is never reused), and on any other removes the node here
only, saying BuilderBot's pieces stay on the machine. Neither Disable nor
Un-enroll goes through while a session or a container is running on
the node: the refusal counts them and says where to end them (the Sessions
page, Down on the Containers page). Un-enroll opens a dialog, since what goes is
in rings (the operator, 11 Oct), with a box saying what un-enrolling takes
off a machine and what it leaves, the same one Reset BuilderBot shows. Always: the runners deregistered on their
forges, then the agent and its unit, the sessions' firewall rules and their
own networks (nothing of the isolation outlives the agent), the `bb` and
`builder` accounts with their homes, `/etc/builderbot` with the tunnel to
the controller, and bb-sandbox itself. Three boxes to tick: the stores on
the machine's own disk (toolchains, caches, artifacts, dev instance data, the
synced project copies, `/var/lib/builderbot`); what was configured from the
dashboard after enrolling (the mounts and their fstab lines, the runners'
units, the GPU display); and, ticked for a hosting node, what it was given
as a host (cloudflared with its token, the port 22 rule,
the nginx container). Unticked, those stay, so the machine can be enrolled
again, here or on another controller, with its stores and mounts as they
were. What the provisioner installed for the machine itself (docker, the
packages, the empty mountpoints, everything on the shares) is never touched.
The node is retired when the job is done. The same removal is `sudo
bb-sandbox uninstall [--stores] [--configured] [--doors]` on the machine, or
`provision-linux.sh --remove`; both say what will go and ask, and neither
deregisters a runner, which only the dashboard can do while the agent can still
ask for the tokens. **Test** probes the channel end to end. **Enroll node** mints a one-time token; the machine
runs `nodes/provision-linux.sh --controller URL --token bbe_…` and dials in. That is
the only way in; there is no second enrollment, this container holds no key
that logs in anywhere, and a node reached by token alone takes every kind of
job, docker included. A node's **path mapping**: what this container's paths
are called on that machine, which its daemon needs to resolve a compose
file's bind sources: is under Advanced. Every change writes an audit row. **Check**, beside the mapping,
proves the two machines mean the same directory by the projects share: a
marker is made under it here and looked for through the node's daemon, and
the page says plainly whether it was found: the one pair nothing else
verifies, and one that fails silently when it is wrong.

**A node does everything for the projects bound to it.** There is nothing to
pick per node: no "this one builds, that one deploys". A project names one
node in its settings and its containers, builds, tests, CI and
emulation all go there, so three projects on three VMs stay apart and three
projects on one VM share it. **Its sessions too** (roadmap #24,
docs/nodes.md §19): a node provisioned with a session account runs its
terminals in the agent's screen relay, each a pty running bb-tty from the bb
the controller ships, so a session on a project bound to it works *on* that machine, with its
toolchains, in the copy of the project its agent keeps at `/workspace` in
step with this container's (a synced copy, the one way a node holds its
projects: nothing mounts the projects share on a node). The node's census
says whether that half is up (`session`: the screen relay's port, account,
which agents the account has) and how far each copy is; `bb roadmap`, `bb bug`, `bb version` and the other verbs
whose state is this container's are relayed back here over the API with the
session's own token. The controller carries a bound project's session to
that node's screen relay when its census says the half is up and the project's copy is there, and
refuses with the reason (on the project's Start agent and in the terminal) when
the node cannot take one, rather than starting it on the wrong machine. A
project with **no** node has no session at all: this container carries no
coding agent, so the button says so and names what to do. Its shell still
opens here, on the same share (a tree to read, the linters, git) because
what moved to a node is the agents and not the terminal. A node's sessions ride its
heartbeat onto the Sessions page, with the node named, and ending one
there reaches the node's agent within a poll. What a project can actually do on its node is
what is **installed** there: its Health section lists the toolchains its census found,
and the Library, with the node picked, is where more are added. (Underneath, the
node still refuses a job asking for something it did not enroll with: the
enforcement of docs/nodes.md §15 door 7, but every node enrolls with the
full set, so it is a mechanism rather than a setting.)

**An account that does not administer sees the Nodes page and changes
nothing on it but its own sign-in.** Its picker lists the nodes its own
projects work on and no others; every control on the node's page is
ghosted for it, enrolling included, and a line on
the page says so; the verbs behind those controls are an administrator's on
the server as well.

**Create sandbox VM** is the step before all of this when there is no
machine yet. **Pick what runs it**: the VM manager whose XML the form writes (nodes/unraid-vm.xml), Proxmox VE, libvirt/KVM, QEMU on
its own, VMware, Hyper-V or VirtualBox, and it writes that machine: the same
cores, memory, disk and installer everywhere, in whatever that manager reads
(a domain XML, a `qm create`, a `virt-install`, a `.vmx`, a PowerShell
script), with an identity of its own and the steps from that manager's own
"new VM" to an enrolled node. The identity is the part worth having written
for you: a uuid, the firmware variables named after it where the manager
keeps them that way, and **a MAC in the range that manager accepts**:
VMware refuses a static address outside `00:50:56:00-3F`, Hyper-V uses
`00:15:5D`, VirtualBox `08:00:27`, and QEMU and everything on top of it
`52:54:00`, so a hand-copied address is how two machines end up on one.
Paste the manager's own uuid and MAC into the two fields when the VM already
exists. `docs/sandbox-vm.md` is the long version.

**Enroll node** is the other way in, and the one the design is built around:
it makes a pending node and mints a one-time token (`bbe_…`, good for a day),
shown once inside the command to run on the machine,
`sudo bash provision-linux.sh --controller URL --token bbe_…`, or the two-line
version that fetches `builderbot-agent` by hand. The provisioner downloads
the agent from the controller itself (checking it against the digest the
controller sends), enrolls, and leaves it running under systemd. From then
on the node **dials out**: no port is opened on it, the controller holds no
key that logs in anywhere, and the credential the node keeps
(`/etc/builderbot/node.json`, 0600) opens its own record and nothing else.
**Revoke**, under Advanced, ends it; the agent says so in its journal and the node goes
quiet, keeping its history. The one-day life belongs to the *enrollment*
token only: the credential the node keeps afterwards does not expire, so an
enrolled node needs nothing renewed.

**Updating the agent.** The node's page says *update available* when its
agent is not the file this controller ships, and **Update agent** hands it
over as a job: the agent checks the download
against the digest, swaps itself in place and re-execs, so nothing on the
node restarts and no running job is interrupted. The agent will not swap
itself in under a running job, so while the update is queued the controller
hands that node nothing new and hands it the update once what was running
has finished, the page saying how many it waits for; a node that does not go
quiet within ten minutes fails the update with what kept it busy, and works
on. Re-running `provision-linux.sh` on an enrolled node does the same thing
from the console, with the node's own token. Inside a compatibility window
the controller does it unasked as soon as the node is idle, since the swap
keeps the node's terminals and sessions; across a window it stays the
operator's press, because that update ends the sessions on the node
([sessions.md](sessions.md#holding-a-session-to-its-rules)).

**Until it is updated, that node takes nothing else.** The controller is
where the agent file comes from, so it is always the newer of the two, and a
job it queues may name something the older agent does not know: a job type,
a field in the spec, which an older agent meets with a shrug rather than an
error. So while *update available* is showing, Apply storage, Apply network,
Install runner, Clear cache and installing a toolchain onto that node are all
refused, with the reason on the button; the self-update itself is the one
thing that still goes through. Nodes running the shipped agent are unaffected.

**A store cannot be pointed at a share that is not mounted.** This is the
one storage mistake that looks like success: a share in fstab but not
mounted leaves its mountpoint an ordinary empty directory, the store gets
made inside it, and everything lands on the node's own disk while the page
reports a healthy store with plenty of room. Apply refuses it instead,
naming the share and what would have happened: fix the mount, or take it
out of the node's mounts if that path is meant to be local. At the console
`bb-sandbox` holds the same line from the other end: `remove` will not
unmount a share a store is inside without `--force`, `list` marks a mount
that holds stores, and a share that fails to mount says which store is
stranded in it.

**Repointing a store moves what is in it.** The contents are copied to the
new path before the switch, and the page asks first, because a toolchain store
is tens of gigabytes and the job waits for the copy. Nothing is deleted: the
old copy stays where it was for you to remove once you are satisfied, so a
move that fails half way leaves the node still able to work. `cache` is the
exception; it is rebuildable, so it is left behind and the log says so.

**Saved is not applied.** The settings on a node's page are a record of what
it *should* be; **Apply** is what makes the machine match. The state line
under them says which of the two you are looking at: how many changes are
waiting and what they are, or that the node already matches, and Apply is
off when there is nothing to do. `dhcp` is the one thing it cannot answer:
the census reports the addresses a node has, not how it got them, so a node
set to `dhcp` keeps Apply network live and says so.

An agent node is *live* when a poll has arrived within the last 75
seconds, and the poll carries the numbers: CPU, memory, jobs running and
free space per store (`data`, `toolchains`, `cache`), so its page shows them
and `bb nodes` marks liveness (`●` live, `○` quiet). Test runs
`uname` there through the channel and shows the answer. Jobs run as the
account the node enrolled (`bb`, the docker account), never as root, and a
job needing a capability the node was not enrolled with is refused **on the
node** (exit 77), whatever the page says. Over plain http the node token
travels in the clear, as the dashboard's own credential does; enrollment says
so, and with TLS in front of the dashboard the agent pins the certificate on
first use and refuses a different one after.

Two nodes may point `toolchains` at the same NFS export deliberately. Each
still installs into its own directory there, named by its node id, so what is
installed on one is not installed for the other; the Android system images
under `<store>/shared` are the one thing they have in common, and a system
image job waits while one is running on any node sharing that store, naming
which. Sharing is recognized by the mount's source, not by the path, since
every node's default path is the same string.

**Four stores per node**, each a directory of its own: `data` (job
workspaces and AVDs), `toolchains` (the toolchains installed there: what a
project bound to that node can build), `cache` (build caches, per project)
and `artifacts` (that node's copy of what its projects built, per project).
The artifacts store is what makes a node off the LAN reasonable: an emulator
or a container there starts from a copy beside it, and a second run of an
unchanged build copies nothing. A store path may not be a system directory:
`/etc`, anything under `/usr`, or a bare `/mnt`, because the agent creates,
fills and empties these; the refusal is made on the dashboard and again on
the node.

**Storage and network, from the page.** A node that enrolled as a sandbox (it
carries `bb-sandbox`) folds open an editor for what it should mount (NFS or
virtiofs, read-only or not), where the agent keeps its data, toolchain and
cache stores, and how it is addressed (DHCP, or a static address with gateway
and resolvers). **Save** keeps that on the node's record; **Apply storage**
and **Apply network** each queue a `system` job the agent runs as root
through the same `bb-sandbox` verbs the console uses, so the two can never
disagree about what the machine is configured to be. Every desired mount says
what the node reports for it: mounted, not mounted, not applied yet, or
mounted from somewhere else. A network change is the one that can cut the
cord it arrives on, so it is applied with a three-minute dial-back: the node
re-addresses itself and must reach the controller from the new address, or it
puts the previous config back on its own and says so when it reconnects.
The job names the address and never the tool: the agent detects what owns
the node's network: netplan, NetworkManager, systemd-networkd, wicked,
`/etc/network/interfaces` or dhcpcd, and writes it through that one, and
refuses, saying so, on a node with none of them. **Static routes** ride the
same apply, in dhcp mode or static, one a line as `10.20.0.0/24 via
192.168.1.1` (the operator, 7 Oct): each backend writes them its own way
(netplan's routes, NetworkManager's ipv4.routes, a `[Route]` section,
`up ip route add` lines, wicked's ifroute), dhcpcd, which has no setting
for one, refuses them by name, and the node reports the routes it has so
the Network section says which are still to apply. A network with no prefix, the
default route (the gateway is that) and a router that is not an address are
refused at Save. **Lock system changes**,
under the node's Advanced section, keeps all of that at the machine's own
console: while it is on, Apply storage, Apply network and a root command
are refused here with the reason, the desired configuration stays on the
record beside what the node reports, and the runner and a funnel, which
are BuilderBot's own footprint: are unaffected. For a node whose fstab and
address are managed by hand, or by something else. Nothing here is
offered to a node that did not enroll as a sandbox.

## Storage

**Storage**, under Machines, is what a node's disks hold, and whose. It shows
one node at a time, picked in the Machines header: a line saying when it was measured,
its filesystems as a stack of meters, its stores and Docker's share, then
each project's folders on it (the synced copy, the build cache, artifacts, a
dev instance's data, emulators, the accounts' build caches), largest first,
with every project this account may not see folded into one line. The
numbers are the agent's hourly walk, said with their age; **Measure now**
asks for a fresh one, which the node's next report brings.

**Storage and shares as features.** On the controller's own machine its
Features section offers two more: *Storage* (ZFS, mergerfs, SnapRAID and
SMART, for the pools, the array and the disks' health) and *Shares*
(Samba and NFS, serving what the Storage page makes), each installed with
exactly its packages and removed with them, refused while a pool or a
share still stands; on BuilderBot OS the packages are the image's. The
row says which of each one's tools answer.

**Shares** (R162): the own machine's SMB and NFS shares as BuilderBot's own
two files say them (an include of `smb.conf`, and `exports.d`): each a
folder on a pool, served over SMB to named users of the machine or to
everybody as a guest, over NFS to named clients (an address, a network, a
name, `*`), read-only or not, with the address to map it by and Remove;
and a form for a new one. Every press is a job the machine's root agent
runs: it writes the two files whole, checks Samba accepts them, and tells
Samba and NFS to read again. The SMB password an account sets for itself is
R164's.
**Pools** (R162): under the disks, the own machine's ZFS pools as `zpool`
says them (size and what is used, health, the members by layout, the last
scrub, errors), each with Scrub, Export and Destroy (which takes the pool's
name again); and a form for a new pool: a name, a layout (a mirror, raidz2,
raidz1 or a single disk) and the disks it takes, each named by model, size
and serial, those that hold something taken only with wipe ticked, and the
whole said again before anything is written. Every press is a system job
the machine's root agent runs from its table (`zpool` on the disks'
`/dev/disk/by-id` links), never the controller's account; the system disk
is never offered. Nothing here is on another node: pools are the controller's
own machine's.

**On the bell** (R164): a disk SMART calls failing, a disk at 55 °C or
over, a pool not online and an array slot whose disk is gone are each a
row on the bell (kind disk, which Where the bell reaches you can send by
email or a push), read off the census on every poll so a row leaves the
moment it stops being true, and keyed on what is wrong so a dismissal
holds until that changes. Each links to the Storage page, where Replace
and the rest are.

**Array** (R162): an array of mixed disks beside the pools, for disks of
mixed sizes: each data disk its own xfs or btrfs filesystem mounted at
`/mnt/disks/dN`, pooled into one tree at `/mnt/array` by mergerfs (the
policy picked says where a new file lands: the emptiest disk, the disk its
folder is on, fill up, or the first with room), with parity on one or two
disks at `/mnt/parity/pN` kept by SnapRAID. Parity is periodic, not real
time: a file written since the last sync is unprotected until the next,
which the section says; the usual pair is a sync daily and a scrub weekly,
saved from the section as rows on the Schedules page (one of the machine's
own jobs, its log on the Jobs page), with Sync now, Scrub and Check on the
section. A parity disk is at least as large as the largest data disk,
which both the page and the agent hold to. Add a disk formats it and
takes the next slot; Replace on a slot formats the new disk and rebuilds
that slot from parity (a data disk) or the parity on it (a parity disk),
hours during which the array is readable, or unprotected, as the job says.
The record is BuilderBot's own (`/etc/builderbot/array.json`), from which
`snapraid.conf` and the array's fstab lines (by filesystem UUID, `nofail`)
are written whole. Destroying the array unmounts it and forgets it: every
data disk keeps its files, readable on any Linux. The cache tier and the
mover the step's details describe wait on pools by purpose (R162 step 6),
where write landing is a share's opt-in.

**Other disks and shares** (R162): under the shares, a disk plugged into
the machine (USB, eSATA) or a remote SMB share or NFS export, mounted at
`/mnt/other/NAME` by itself as a backup target or a source to copy in,
never pooled and never written to by anything but what a person does with
it. The record is the controller's (`extmounts.json`, an SMB share's
password sealed under the install key as every secret is) and goes to the
own machine's agent in its hello, which mounts what the record says and
unmounts what it no longer says, within a minute; a disk's row says when
it is not plugged in. Eject (Unmount, for a share) turns the row off: the
agent unmounts it and the row says the disk is safe to pull; Remove
forgets it, nothing on it touched.

**Backups** (R162): under the other disks and shares, what the machine
copies where: a folder on it (a pool's mount, the array, a disk or share
under `/mnt/other`, or the controller's state) to another of those, by
rsync, each run its own dated folder under `DEST/NAME` hard-linked to the
run before so a run costs only what changed, `latest` the newest whole
run, the oldest pruned past the runs kept, and a run that fails leaving no
half folder. Run now is a system job; a daily or weekly schedule from the
row is a row on the Schedules page like the snapshots' and the array's.
The last run of each (when, whether it succeeded, the size of all its runs)
comes with the census: the row says it, Home's backups tile says the last
good run, and a run that failed or a scheduled backup with no good run in
two days is a row on the bell (kind backup). A destination under `/mnt`
that is not mounted is refused, so a copy never lands on the system disk.
A cloud store (restic or rclone to S3 or B2) is not here yet: a share on
another machine mounted under Other disks and shares is the way off the
box today.

**Pools by purpose** (R162): there is no cache tier and no mover. A
pool of solid-state disks holds the hot data and the array the shares,
media and backups, and a share names the one place it lives on when it is
made (the pool or the array, picked on the form, its folder under it),
nothing moved behind a person's back; writes go to that place at its
speed, the array's parity being periodic. A pool of one disk has no
redundancy, so where the array stands the Backups section offers one press
that backs it up to the array nightly (seven runs kept), and a dead disk is
restored from last night's run. A special vdev or a SLOG on a single disk
is never offered: losing one loses the pool.

**People on shares** (R164): an SMB share's users are BuilderBot's own
accounts, named on the share by account name (each becomes its own Unix
user on the machine, `bbu-` and the account's id, made when first named)
or by role (`role:NAME` on the API; the form offers each role, and it
names everybody holding the role at that moment, not later joiners), with
the machine's own Unix users still accepted by name. A person reaches a
share with their account's name and an SMB password of their own, set on
Profile under Your shares, which also lists the shares named to them and
the address to map each by; the password is kept only as the NT hash
Samba keeps, handed to the own machine's agent in its hello and imported
into Samba's database there, never written in a job or shown again. A
share ticked as a Mac's Time Machine target is offered to the Finder as
one (`fruit:time machine`), found by mDNS as Samba registers it.

**Encryption** (R162): a new pool can be made with ZFS native encryption
(`aes-256-gcm`, a passphrase). Where its key lives is the person's choice,
said on the form with what each protects against: kept on the machine,
sealed under the install key as every secret is, so the pool unlocks at
every boot and the disks are unreadable pulled from the machine; or asked
for on the Storage page after every boot, which also covers the whole
machine being taken, at the cost of a person at the page after each boot
while the pool and its shares wait. The choice is changed later from the
pool's row (Keep its key here, Stop keeping its key here). The passphrase
never rides a job: the controller hands it to the own machine's agent in
its hello (a kept key every time, an offered one until the pool reports
open), the agent keeps it in memory only and gives it to `zpool` and
`zfs load-key` on their stdin. A locked pool is a row on the bell, a share
on it says its pool is locked rather than vanishing, and Safe mode boots
with every pool locked. Nothing recovers a pool without its passphrase.
Each array disk under LUKS is not here yet.

**Snapshots** (R162): under the pools, each pool's snapshots as `zfs`
lists them, counted by kind (hourly, daily, weekly, manual) with the
newest ten named, and Snapshot now, which takes one of every dataset at
once. Each named one has Roll back (the pool as it was then; the name is
typed again, since everything written since is gone, and every later
snapshot with it) and Delete. A schedule per pool and kind, saved from the
form (the pool, how often, how many of that kind to keep), is a row on the
Schedules page like any other, its timetable in words and its last run's
log on the Jobs page, except that it runs one of the machine's own jobs
from the root agent's table rather than a script: when it runs, the
oldest of its kind past what is kept goes. Snapshots are named
`bb-KIND-DATE-TIME`; ones made by hand with other names are left alone and
not counted.

**Disks** (R162): on the controller's own machine the page opens with the
machine's disks as its agent lists them (`lsblk`, and `smartctl` where it
is installed): each by name, model, size, serial, spinning or solid state,
what each partition holds (a filesystem and where it is mounted, a ZFS
pool's member, swap, nothing), the system disk marked, and SMART's health,
temperature and hours. A failing disk is said in the bad tone. Nothing
here writes to a disk: the pools and the shares made from them are the
storage module's next pieces.

## Installed

**Installed**, under Machines beside Nodes and Storage (R172), is what the
Library put on one node, picked in the Machines header, and how each is set there: a
section per kind with anything on the node (coding agents, toolchains,
tool packs, services), each a row that opens on what the Library's card
does not show, since the Library is the catalog. An agent's row holds your
sign-in on that node and what you added to the agent there, and Remove. A
toolchain's row says where it is on the store, which system packages it
uses and which this machine lacks (Install them now where the agent
administers the machine), what it needs that is not there, how its
download was checked, and Remove; the machine's own NVIDIA driver and
container toolkit are rows here too, with their state in the census's
words. A pack that asks for anything per node (its manifest's `config`
block, [tool-packs.md](tool-packs.md#writing-one)) has **Configure** on its
row: the fields drawn from the block, a secret shown only as set (typed to
replace, `clear` to take it out), Save keeping the answers sealed on the
controller and handing them to the node for the pack's verbs. A service,
the **Model router**, is configured the same way (the provider keys, other
OpenAI-compatible endpoints, Ollama beside it, the projects allowed) and
holds its models and spend, Ollama's pulled models, Install once
something is behind it, and Remove; the Library's card for it only
installs. Over the rows, the system packages the node lacks for what its
store holds, with the one press that installs them.

## This machine

On a controller installed bare metal ([install.md](install.md#bare-metal)),
**This machine**, first in the rail's Controller group (`#/controller/machine`),
is the computer the controller runs on: its head says what it is (its name,
system, cores and memory, the release this install runs and how long it
has been up, its agent and whether the wall between its sessions and the
controller is in force), then the **Updates** section (the release running
against the newest, **Check now**, **Update**: [Controller settings](#controller-settings)),
then the machine as a node, drawn exactly as a node's page draws any node:
its health, the projects on it, its sessions, GPU, USB, model router,
features, storage, network and the advanced verbs, reboot and power off
among them. The machine is not a row on the Nodes page and not in its
picker; a project still picks it as its node, shown as **This machine** in
every project's node picker, so its sessions, builds and containers run
there as on any node. The container edition has no machine of its own and
does not draw the page (R90 step 8, R56 step 8).

**A held start** (R56 step 9). Not by default: after a shutdown that was
not clean (the service writes a marker on a clean stop and the next start
misses it), or when **Hold the next start** on this page was pressed
before a restart (that one boot), the install comes up with the dashboard,
its agent and the network and nothing else: no agent session starts (a
shell still opens), and the pools, shares, apps, VMs and containers the
installed OS adds are held by their own modules until **Start** is pressed
here. A band on every page says it is held and why. Safe mode at the boot
menu and a disk the array names gone missing are the installed OS's own
reasons to hold (R161, R162).

Under Name and time, **Spin down disks** (R164) stops the spinning
disks but the system's after the idle time picked (`hdparm -S`, five
minutes to two hours, or never); a solid-state disk is left alone, and the
agent sets it again after every boot, since the timer is the drive's own.

**Reporting** (R164): a Reporting section on the controller's own
machine's row keeps what every heartbeat samples (CPU, memory, the
network's bytes in and out, the disks' bytes read and written, the CPU's
temperature and the hottest disk's) for weeks at falling resolution:
five-minute means for two days and hourly means for two months, one small
file per node under the state (`history.py`), drawn over six hours, a day,
a week or a month as the hour's charts are drawn, one measure each. The
rates come from the agent's cumulative counters, so an agent restart is one
skipped point, never a spike. The hour's charts above it are the samples
themselves and are unchanged.

**Power** (R164): with the UPS feature installed (NUT, for a USB UPS;
the Features section installs it on the controller's own machine), a
Power section shows the UPS as NUT reads it: on line or on battery, the
charge as a meter, the minutes left and the load. The machine on its
battery, a low battery, a battery to replace and a UPS that does not
answer are rows on the bell (kind power), and NUT's monitor shuts the
machine down cleanly when the UPS says the battery is low, which is the
feature's own configuration (`/etc/nut`, written once and left alone where
a person changed it).

**The system's own updates** (R164): on a bare-metal install that is not
BuilderBot OS, Updates under Controller settings also counts the system's
own package updates (apt, once an hour as root), says how many are
security ones and whether the last update asked for a restart, and Apply
updates runs apt on the machine by its root agent with the configuration
files kept as they are, restarting after when the box was ticked and the
update asked for it; Restart now is there when one is needed. Security
updates waiting and a restart needed are rows on the bell (kind host).
BuilderBot OS has none of this: its updates are whole images.

## Network

**Network**, in the rail's Controller group (`#/controller/network`), is how
this controller is reached, in every edition (R165 step 4): the address the
page is at and its port, what it is served over, and which nodes dial in,
each with where it dials in from, when it was last seen and how it reaches
the controller (this network, the public hostname, WireGuard). Under them,
two groups moved here out of Controller settings: **Connection** (http, or
https with the install's own certificate or a Let's Encrypt one for the
hostname; the certificate's fingerprint a phone or the companion pins, and
its download) and **Reach from outside** (the home tunnel the controller
runs itself, with its setup steps). On a bare-metal install the machine's
own ports, addresses and bridge are This machine's Network section.

## Controller settings

**Controller settings**, beside Home in the rail's Home group (`#/home/settings`),
drawn only for an account that may read the controller, is what the
**controller** owns and can apply live. Its bar carries the container's uptime
and the build it is serving. Its sections, each with its own Apply and Revert:

- **Logs**: how long logs are kept, and the downloads (see [Logs](#logs)).
- **BuilderBot bug reports**: what sessions and people reported about
  BuilderBot itself, each with its delete, **Download diagnostics** and
  **Clear reports**.
- **Updates** (a controller installed bare metal, R90): the release this
  install runs and the newest published, checked daily and on **Check
  now**; **Update** runs the installer's update through this machine's
  own node, the bundle verified and the state copied aside, and the install
  comes back by itself if the new release does not answer. On BuilderBot OS
  the same press writes the release's image into the slot not in use and
  names it for the next boot, the restart yours ([image.md](image.md)), and
  **Update from the folder** takes the files from a folder on the machine.
  The container edition has no such section: its image is pulled by the
  host. On a controller in debug mode with the dev switch on the section
  carries a **Channel** pulldown, Releases or Dev builds
  ([versions.md](versions.md#two-channels)); everywhere else the releases
  are the only channel and no pulldown is drawn.
- **Power** (a controller installed bare metal, the OS and the USB edition
  among them, R175): Restart and Shut down for the machine the controller
  runs on, through its own node's reboot and power-off verbs with This
  machine's words and ask, dead with why while its agent is away or a
  system job runs there. The container edition has neither this nor
  Updates: its image and its container are its Docker manager's.
- **Backup** and **Backup copies** (R161): the backup password, under which
  a sealed copy of the configuration is written after every change onto the
  machine's pools and under the state (the five newest kept), Back up now,
  the copies listed with Download for those under the state; a fresh
  install's first page restores one ([image.md](image.md)).
- **Update window**: a newer release applied by itself at an hour, daily or
  one weekday, the way Update does it; off by default.
- **Idle sessions**: the idle rule, which ends any agent's session after N minutes
  with nothing typed or written, here and on every node, where the node
  itself enforces it so the rule holds while this container is down.
- **Storage on this controller**: where each kind of thing that grows
  (project snapshots, job snapshots, the git relay's repositories, the Git
  view's working area, the logs) is kept, moved to a new empty path on Apply
  and switched once all of it is there, while the records, the database,
  the signing keys and the git credentials stay in the state directory
  (`paths.py`).
- **Room on the nodes**: the disk a node keeps free (a build, a test or a
  container rebuild is refused under it, and the bell says so), the memory
  level past which the bell warns, and a memory limit for every container
  whose compose file sets none ([nodes.md](nodes.md#room-a-node-keeps-for-itself)).
- **Apps**: which of the apps a person installs this controller offers as
  Library cards ([reference.md](reference.md#the-apps-a-person-installs)).
- **Mail**: the SMTP server BuilderBot sends through (its port, security,
  sign-in and the From address, the password sealed under the install key),
  for a person who asked on their Profile for the bell by email (R149,
  `reach.py`); nothing is sent until a server is set.
- **Maintenance**: the owner's alone. While *Maintenance mode* is on, only
  the owner signs in and is answered, from the page, the phone app or a
  session of theirs. Everybody else is told BuilderBot is down for
  maintenance, by the sign-in page, the API (503) and the app, and stays
  signed in for when it ends. Turning it on ends everybody else's coding
  agent sessions and terminals, here and on the nodes; it asks first, listing
  each with whose it is, its project, whether it is working or waiting, and
  its node. Nodes are not accounts and keep running, and a band under the
  header reminds the owner it is on.
- **Move this controller** (R90 step 12, R175): the move armed (the token
  shown once, every node told from its next hello, however long it takes),
  what the bundle carries ticked with each piece's size, Download the
  bundle packed fresh each press, Ask the new home, Forget it, Mark as
  moved; and, on a controller a move landed on, where it came from and
  whether the old one has been told ([install.md](install.md#moving-a-controller)).
- **Reset BuilderBot**, last.

The page says plainly what still comes from the environment and why (the
placement rule and the unhardwiring are docs/nodes.md §13 and §11).


**Reset BuilderBot** starts the controller over at the setup page: accounts,
node enrollments, project settings, git tokens, the notebook, memories and
logs are moved into a dated `.reset-…` directory under `/config`, never
deleted, and project files are not touched. Its dialog first offers to
un-enroll every node, so each machine can be enrolled again afterwards, with
the same box the Nodes page's Un-enroll shows saying what un-enrolling takes
off a machine and what it leaves; a node with a session or a container
running cannot be ticked until they are ended. It asks for the word `reset`
typed, waits for each node it un-enrolls to report, and the dashboard
re-executes itself. Projects are deleted from the Projects page, one at a
time.

## Upgrades and /config

`/config` carries one number, its state, in `/config/state.json`: the newest
of the controller's numbered migrations that has run on it, and the build
that ran it. Every start reads it before anything is written, first in the
entrypoint and again in the dashboard:

- **The same state**: the controller starts, and nothing is copied.
- **An older state this build migrates from**: `/config` is copied to
  `/config/backups/before-VERSION` (VERSION being the build about to
  migrate it), then each migration past the stamp runs once, in order, and
  the stamp moves with each. The newest three copies are kept. A copy leaves
  out what grows and is rebuilt (the logs, the job and project snapshots,
  images in transit, the relay and Git view repositories, the apps fetched
  from a release, earlier copies and a Reset's moved-aside state) and keeps
  every record, the database, the signing keys, the git credentials and the
  wikis. A migration that fails is said in the log and runs again at the
  next start; the controller starts either way.
- **An older state than this build migrates from**: the container stops,
  saying which release to start on it first.
- **A newer state** (a rollback past an upgrade): the container stops, saying
  that downgrades are not supported. Start the newer build again, or stop
  the container and put the copy back: the contents of
  `/config/backups/before-VERSION` in place of the rest of `/config`.

A fresh `/config` is stamped with this build's state at the first start.
Which upgrades are supported, and how to roll one back, is
[install.md](install.md#upgrading).

## Logs

**One file per container start, per stream.** All three rotate together on
boot, so a generation number means the same boot in every one of them, and
`.1` is the previous run of the container.

| Log | Where |
|---|---|
| Startup, the runner supervisor, and every later warning | `config/logs/builderbot.log` |
| The dashboard server, in full | `config/logs/dashboard.log` |
| Every compose call the Docker manager made | `config/logs/docker.log` |
| Runner diagnostics | `_diag/` under the runner's directory on its node (`/var/lib/builderbot/runner/<slot>/_work/`) |
| CI job output | GitHub → Actions → the run |
| Emulator | `home/.android/emulator.log` |

All of them persist across updates, are secret-redacted, and move together to
the `/logs` mount if you map one.

**Kept for a number of days, not a number of boots.** Thirty by default, set
as **Days of logs kept** in the Logs section of Controller settings, and one
policy for everything the controller keeps: these generations, the archived
CI runs and the jobs' logs. It runs every hour as well as on Apply, and a
live file past 64 MB is moved to its next generation then. A
count was the wrong unit for the question anybody has (*was that this week?*)
and a container in a crash loop can burn five generations in a minute;
a ceiling of sixty generations survives for exactly that case. A running
job's log keeps its first megabyte and its newest, 16 MB in all, with one
line where the middle went.

**Apply crops.** Lowering the number deletes what it already excludes, then
and there, rather than waiting for the next sweep, which is why it is a button
and not a field that saves itself: a number input fires `change` on its way
through every value the keyboard passes, so typing `30` over `300` would have
pruned at `3` in passing. Pressing it without changing anything is a
crop-now, which is the other thing you sometimes want. The same section
downloads this session's logs as one file, or everything kept as a `.tar.gz`,
and **Clear** deletes the kept generations, the archived CI runs and every
finished job's log without touching the ones being written. The BuilderBot bug
reports section lists every report made about BuilderBot, each with its own
delete, and under them **Download diagnostics**, the controller's
diagnostics as one file (what `bb diag` prints, with the reports left in the
list, redacted and on the audit trail), so a report can be taken out before
the diagnostics go to somebody. **Clear reports** deletes every one after a
confirmation that says how many; the numbers carry on, so a bug that names
report #3 never meets a second one. Whoever reads Controller settings reads
the reports there; a session reads them only where its project is granted
the diagnostics, and never deletes one.

One deliberate omission from *this session*: the **CI logs stay where they are**, under `config/ci-logs/<repo>/`, one
file per run: a CI run is not a container session, it belongs to a workflow
run and spans whatever session was up. They are already grouped the way you
would want and `bb ci-log` reads them by run id; they are in the archive and
under the same retention.

## Jobs

**Jobs**, on the rail, is the queue (docs/nodes.md §2, phase 4): everything the
controller has taken: a compose action on a dev instance, an exec on a node,
an agent self-update, with where it was placed, what it is doing now, how it
ended and its log. A job is placed on a node named outright or on whichever
node fits a selector (capability, labels, pool, OS, architecture), and the
choice is frozen on the row when the job is taken; a selector nothing fits is
refused when it is queued, naming the selector. Each node runs as many jobs at
once as its row allows; the rest wait in order. **Cancel** on a row stops one
where it is: a queued job never starts, a running one is killed and the row
moves when the runner reports that it did, and nothing edits a job after the
fact. The checkbox in the bar narrows the list to what is running or waiting.
`bb jobs [--node NAME] [--type T]` prints the same list read-only, so a
session can see what became of the work it asked for, and `bb jobs ID
[--all]` prints one job's log. Both ask the controller as the caller, so
they are narrowed the way the page is: a session sees its own project's jobs
and its reads', and the nodes' own jobs (a toolchain install, a system
change) only where the project's settings grant it the diagnostics, which is
also what `bb diag` needs; a node's machine logs (`bb logs --node NAME`) are
a grant of their own. The log is the only copy:
a node buffers it and posts it here, and keeps nothing. `/api/v1/healthz` answers without a credential with
the queue's counts, and `/metrics` answers with one in Prometheus text.

## Schedules

**Schedules**, beside Jobs in its group, is an administrator's own cron:
each schedule a name, when it runs (hourly, daily,
weekly, monthly, or cron's five fields under Custom, said in words: `0 4 * * 0`
is Sundays at 4:00), where it runs, and a script. It runs on the controller,
as the controller's account with everything that account can read, or on a
node as the node's jobs account; on a node provisioned as a sandbox it may
run as root instead, as `bb root run` does. A run is stopped after a day.
New schedule and a row's Edit open the same dialog. Every run is a job, its
log on the Jobs page and linked from the schedule's row with how it ended;
**Run now** runs one once, whatever its timetable says. One run of a schedule
goes at a time: one still going when the next falls due is said on the bell
and that run skipped, and a run the controller was down for is run once when
it is back, said as late, never once per run it missed. A failed run is on the
bell too, with its log.

The scripts are kept in the controller's state and never on the share, and
are a person's alone: the page is its own area of a role (Schedules), which
administrators hold and no other role is given unless somebody says so, and
a session's token is refused at it whatever it asks; bb has no verb for
schedules, and a schedule's runs are not among the jobs a session reads.

The static analysis scan is not a schedule here since 0.9.0: it is the
Scanners page's own ([scanners.md](scanners.md)), which deploys BuilderBot's
scanners to each node and runs them on one timetable.

