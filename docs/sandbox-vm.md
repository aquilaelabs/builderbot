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
3. **The daemon itself.** Whatever address the manager can reach, a session
   on this box can reach too — the container has one network view, not two.
   A far bigger lever than any HTTP port, and the reason the daemon must not
   be this box's own. (It arrived as `DOCKER_HOST` once; the node record
   carries it now, but the reasoning is unchanged — what the controller can
   address is not a secret from a session.)
4. **The dashboard's own API**, which holds the same credential a session
   does.

**A separate physical machine does just as well, and `provision.sh` runs on
one.** Nothing in the argument below is about virtualization: what closes
these four paths is that the daemon belongs to a machine whose whole job is
being wrecked and reset, with no route to the server's containers. A VM is
simply the cheapest way to get one out of hardware you already own. On bare
metal the only differences are that `--share` has no hypervisor to pass a
share in — use `--nfs` — and that an emulator is *happier*, with `/dev/kvm`
native rather than nested. The provisioner skips the guest agent when it
finds no host to talk to, and is otherwise the same script.

A VM answers all four at once — and the point worth holding on to is that it
does not *add* a layer. It takes one away: dev instances run in the VM, so
**BuilderBot has no reason to reach the host's daemon at all** — and it no
longer can, because the socket mount and the proxy it used to accept are both
gone from the code.

Two things also get better on the way:

- **The layer cache comes back.** BuilderBot forces the classic builder
  (`DOCKER_BUILDKIT=0`), because buildx boots a helper container and *attaches*
  to it — which a filtered socket refuses. Nothing is in the way of the VM's
  own daemon, so buildx and its inline cache work; see the roadmap item on
  turning it back on.
- **The host-path problem disappears** rather than being mapped around. See
  *path parity* below.

## Path parity, which is the whole design

Mount the projects share into the VM **at the same path BuilderBot uses**:
`/workspace`.

This is not tidiness. A compose file's bind-mount *source* is resolved by
whatever runs the container, so if both machines call the share `/workspace`,
a relative bind like `./data:/data` means the same directory whichever side
asks. Mount it anywhere else and every project's compose file is wrong in the
worst way available: Docker does not fail on a missing bind source, it creates
an empty directory and mounts that, and the app comes up with no data.

the path mapping exists precisely because today's daemon is the host's and
its paths are not BuilderBot's. Give the sandbox parity and that setting
becomes an identity mapping you can leave empty.

**The dev-data path is the sandbox's alone.** `/devdata` — where a compose
that opts in with `${BB_DEV_DATA}/...` puts its volumes — needs mounting on
the VM and **not** in BuilderBot. Leave the container's **Dev instance data**
path empty — a mount there is not merely spare. It makes BuilderBot use its
own copy of `/devdata` instead of the sandbox's, which then needs a
`/devdata:/devdata` pair in the host path mapping as well; without one,
`BB_DEV_DATA` is left unset and a compose that wants it refuses to start.

The per-instance directory has to exist before a bind can use it, and docker's
own attempt fails on a share that squashes root — so BuilderBot asks the
sandbox to make it, in a one-shot `alpine` container owned by BuilderBot's own
uid. It never needs to read the directory, only to name it, so the share is
configured once on the machine that uses it and `/workspace` is the only path
the two sides have to agree about.

That also answers the question the arrangement invites: no, BuilderBot does
not ssh into the VM to do this, and it has no ssh dependency at all. Every
call it makes goes through the docker CLI, which carries the ssh transport
itself — so the one credential involved is the shielded key that already
reaches the daemon, and `_guard()` still allows only compose, `version`, and
the three fixed commands that tend this directory.

That is a `docker run`, which is root on whichever daemon answers — allowed
because a sandbox VM's whole job is being wrecked, and refused outright if
the node's address names anything that is not one.

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

## Configuring it afterwards

`provision.sh` installs **`bb-sandbox`**, and that is how the machine is
changed after the day it was built:

```bash
sudo bb-sandbox                      # a menu, whiptail where the distro has it
sudo bb-sandbox add-nfs 192.168.1.15:/mnt/user/media:/auxiliary
sudo bb-sandbox add-share workspace:/workspace:ro
sudo bb-sandbox appdata /devdata     # which mount holds container appdata
sudo bb-sandbox readonly /workspace  # ...and back with: readonly /workspace off
sudo bb-sandbox check                # is every mount really there
sudo bb-sandbox settings             # the lines to paste into BuilderBot
```

Once the machine is enrolled as a node, the same mounts (and the agent's
stores, and the address) are editable from the Nodes tab too: the agent
applies them through these very verbs as audited `system` jobs, and
`bb-sandbox list --json` is what its census reports. The menu stays as the
console fallback, reading and writing the same fstab — see docs/nodes.md §12.

**The admin account is optional.** Nothing in BuilderBot uses it: the agent
runs as root under systemd and drops to the docker account for every job,
`bb-sandbox` refuses to run as anyone but root whoever invokes it, and the
controller never names it. It is a convenience — a sudo login that is not
the account a session reaches — so a machine you already administer from
your own account, a cloud image's `ubuntu`, or root, needs no second one:
`--admin none` skips it. What the split actually protects is the other half,
and that half is not optional: the DOCKER account has no sudo.

**Two accounts, and the split is the point.** `bb` runs Docker and answers
ssh — the one BuilderBot uses, and so the one a Claude session reaches. It has
no sudo and cannot run `bb-sandbox`. `admin` has sudo and is the only account
`bb-sandbox` runs for, so what this machine mounts is a decision made by a
person at a console rather than something available to whatever is building a
container this afternoon.

`provision.sh` makes both. `--admin NAME` renames the second; `--admin-key`
gives it a key so it can be reached over ssh. No password is set for it — a
provisioner that invents one has to print it, and a password in a terminal
scrollback is not a secret — so set one from the console or pass a key.

**And a third, for sessions** (roadmap #24, docs/nodes.md §19). A Claude
session on a project bound to this node runs *here*, and it runs as
`builder` — `--session-user NAME`, `none` to run no sessions — which is in
`kvm` for the emulator and in **no docker group**: the account that edits
your source is the one thing on this machine to keep away from a group that
is root. It is made with `--session-uid`/`--session-gid` **99:100**, the
controller's PUID:PGID, so a file it saves on the projects share is owned
exactly as one saved from the controller is; a different uid would leave the
share with files the rest of the array does not expect. `provision.sh`
installs tmux, ttyd, jq and git for it, Claude Code into its home by the
native installer, and a `/etc/profile.d` entry so a login shell as that
account has the role, the controller's address and `bb` (from the bundle the
agent keeps under the packages store at `.bb/current`) — the same
environment a dashboard session gets, which is what makes proving the node
by hand the same path: `sudo -iu builder`, then
`bb-tty u:<uid>:claude:<project>` with `BB_TOKEN` from `bb users token
<project> <account>` on the controller. The projects share has to be mounted
at `/workspace` for any of it to have a tree to work in — one more row in
the node's mounts on the Nodes tab.

**The Claude login follows the account.** A node-bound terminal's token is
minted for the account as well as the project, and the first session there
runs `bb login`, which fetches that account's credentials file from its
home on the controller into its home on the node — 0600, that account's
only, and only when the node's copy is not signed in already. So signing in
once on the Doctor card signs every node in, per person: two accounts on
one node are two homes and two logins. The one thing to know: the file is
an OAuth grant with a refresh token, and whether Claude Code rotates it on
use is not documented; if a node and the controller ever sign each other
out on refresh, `bb login` from a shell on the node is the fallback.

Be clear about what this does *not* do: `bb` is in the `docker` group, and that
group is root on this machine to anyone who wants it. One
`docker run -v /:/host --privileged` and the separation is over. That is not a
hole to plug — the VM exists to be wrecked, and BuilderBot needs the daemon to
do its job. What the split buys is that the machine's own configuration, the
fstab deciding whether `/workspace` is the projects share and read-only, is not
one command away from a session that wandered.

**Mount the projects share read-only — unless this node runs sessions.** For
a Docker-only sandbox nothing on the machine writes source code (the daemon
only ever *resolves* bind sources there), so read-only costs nothing and
means a container that binds its project tree cannot scribble on your
source. A node with a session account is the other case: Claude works on
that share from here, so it has to be read-write — the dashboard refuses to
send a session to a node whose `/workspace` is read-only and says so on the
project's button, because a session that cannot save a file is worse than
none. `:ro` on `add-share`/`add-nfs` decides it when the mount is made;
`bb-sandbox readonly /workspace` decides it afterwards, and
`readonly /workspace off` puts it back (or untick read-only on the mount's
row on the Nodes tab and apply). `list` shows which mounts are read-only.

Leave the shares containers keep their data on — appdata, media — writable,
being what they are for.

It is the same code provisioning uses for its own `--share` and `--nfs` — one
implementation of the fstab writing, not a copy per entry point, because the
comments in it were paid for one silent failure at a time: a mountpoint left
`ESTALE` by a share that moved, a re-provision whose source had changed being a
silent no-op, `mount -a` skipping a busy mountpoint so a rewritten entry stayed
on the old export and looked perfectly mounted.

**It is root on this machine, run by a person, and BuilderBot cannot reach it.**
That is the point rather than an omission. This VM exists so a session can
build and destroy containers without touching anything that matters; a path
from the container into the VM's own configuration would hand back exactly what
the arrangement buys. The dashboard can *see* what is mounted — it asks the
daemon — and changing it is a decision made here.

`settings` is the seam between the two machines. This VM cannot reach into
BuilderBot, so it prints what to enter on the dashboard's Nodes tab: the
address to add this machine as a node, and the path mapping to set on its
row, built from the mounts that actually exist here. Only the paths
BuilderBot *also* mounts at the same place belong in it — a share this
machine alone has belongs in neither list, and BuilderBot will say so on the
Docker manager tab rather than leaving the line looking like it does something.

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
`provision.sh` accepts either.

Take the installer's defaults except for four screens, where the default is
wrong for this particular machine:

- **Storage — use an entire disk, but untick *Set up this disk as an LVM
  group*.** Guided LVM has a long habit of leaving much of the volume group
  unallocated, so a 64G disk becomes a ~32G root and you find out when Docker
  fills it. Check the root filesystem's size on the summary screen before
  confirming. Plain ext4 is also simpler to grow later — `qemu-img resize`,
  `growpart`, `resize2fs`, with no `lvextend` in the middle — and the
  snapshots LVM would give you are already available a layer down, in qcow2.
  No encryption: it would want a passphrase at every boot on a headless box.
- **Install OpenSSH server — tick it.** It is off by default and it is how
  BuilderBot reaches the daemon; skip it and you are fixing that through the
  VNC console. Import or paste the key here.
- **Featured snaps — do not tick Docker.** The snap is not what
  `provision.sh` installs, and two Dockers will argue.
- **Network — DHCP is fine, but pin the address.** The node record and every
  web UI you open point at it, so a lease that moves breaks both. Set it
  static, or reserve it on the router against the MAC in the domain XML.

Use `bb` as the username so it matches `--user bb` below, and take the normal
Ubuntu Server rather than *minimized* — minimized strips editors and man
pages, and this is a box you will eventually log into to work something out.

Then run one script inside it:

The repository is private, so the VM cannot fetch the script itself — copy it
over. **From the Unraid terminal**, where that path is the host's own; inside
BuilderBot the same file is `/workspace/BuilderBot/vm/provision.sh`.

```bash
scp /mnt/user/development/projects/BuilderBot/vm/provision.sh bb@<vm-ip>:
ssh bb@<vm-ip>
```

then, in that session:

```bash
sudo bash provision.sh --user bb \
    --key "ssh-ed25519 AAAA… bb-sandbox" \
    --nfs 192.168.1.15:/mnt/user/development/projects:/workspace \
    --nfs 192.168.1.15:/mnt/user/bb-sandbox/devdata:/devdata
```

Both steps ask for the password you set in the installer, because the VM has
no `authorized_keys` yet — `--key` is what puts one there, so the first
connection is necessarily password-based. After this, BuilderBot gets in
without one.

Do not try to save the copy by piping the script into `ssh`: `sudo` wants a
tty to prompt on, a non-interactive `ssh` gives it none, and stdin is already
carrying the script.

To make the VM a **node** as well — dialing in to the dashboard, taking jobs,
reporting its numbers on the Nodes tab — add `--controller URL --token bbe_…`
to that command, with the token **Enroll node** minted. It is single-use and
lasts a day; the README's Nodes tab section says what the agent then is and
what it may do. A run without the two flags leaves an existing enrollment
alone, so re-running the provisioner for a mount does not re-enroll.

**`--key` is a PUBLIC key** — the `.pub` half, appended to the VM's
`authorized_keys`. Nothing private is ever put on this machine. The private
key stays on BuilderBot in `/secrets/ssh`, loaded into the root-owned agent,
where sessions can use it to connect but cannot read it; the VM holds only the
line that authorises the connection and never dials out itself.

Give the sandbox its **own** key rather than reusing a GitHub deploy key. Both
are safe — the private half of a deploy key never leaves the agent either —
but one key authorising two unrelated things means rotating it for a GitHub
reason silently breaks the sandbox. On the host:

```bash
ssh-keygen -t ed25519 -N "" -C bb-sandbox \
    -f /mnt/user/appdata/BuilderBot/secrets/ssh/bb_sandbox
```

The private half lands where the entrypoint loads it into the agent at boot;
the contents of `bb_sandbox.pub` are what you pass as `--key`.

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

  which says nothing about which of its several reasons applied. Read
  `/var/log/libvirt/qemu/<vm-name>.log` before changing anything — where the
  failure lands in that log tells you which kind you have.

  Observed once, on libvirt 12.2.0 with QEMU 10.2.3:

  ```
  Starting external device: virtiofsd
  /usr/libexec/virtiofsd --fd=40 --shared-dir /mnt/user/development/projects
  ...
  libvirt:  error : libvirtd quit during handshake: Input/output error
  ```

  Both directories were accepted and it died at the *handshake*, before
  touching a file — so that one is not about the paths, and not about shfs.
  It is virtiofsd and libvirt failing to talk. The thing to try there is
  telling virtiofsd not to sandbox itself with user namespaces, which is what
  it does by default and what a host can refuse:

  ```xml
  <binary path="/usr/libexec/virtiofsd">
    <sandbox mode="chroot"/>
  </binary>
  ```

  inside the `<filesystem>` element. If that does not settle it, suspect the
  virtiofsd shipped against a very new libvirt rather than anything in this
  XML, and stay on NFS — it costs a little throughput and nothing else.

  So bring the machine up with NFS, which needs no host-side daemon:

  ```bash
  sudo bash provision.sh --user bb --key "ssh-ed25519 …" \
      --nfs 192.168.1.15:/mnt/user/development/projects:/workspace \
      --nfs 192.168.1.15:/mnt/user/bb-sandbox/devdata:/devdata
  ```

  Export them from Unraid first: *Shares → share → NFS Security Settings*,
  **Security: Private**, with a rule naming only the VM:

  ```
  192.168.1.151(sec=sys,rw,all_squash,anonuid=99,anongid=100)
  ```

  `all_squash` with `anonuid=99,anongid=100` is the part that matters beyond
  access control. BuilderBot runs as uid 99 / gid 100, which is what the array
  files already are; the VM's own user is uid 1000 and containers inside it
  often write as root. Without squashing, anything the sandbox creates lands
  owned by 1000 or 0 and **BuilderBot cannot modify it** — a permission error
  in a session, on a file it made a minute earlier. Most Unraid examples show
  `no_root_squash`, which produces exactly that.

  **An NFS source is the exported SHARE path, not a pool path.** Unraid
  exports `/mnt/user/<share>`, so a directory on the cache pool is reached as
  `/mnt/user/appdata/thing`, never as `/mnt/cache/appdata/thing` — the latter
  is right for a bind mount and simply is not exported. The mount fails, and
  with `nofail` it fails quietly.

  **Never export `appdata` to reach the dev-data share.** Unraid exports
  *shares*, not folders, so exporting a directory inside appdata means
  exporting all of it — every other container's configuration, handed to the
  machine the VM exists to keep away from them. Give the dev data a share of
  its own, which is what the template now defaults to
  (`/mnt/user/bb-sandbox/devdata`), or skip `/devdata` entirely until
  something needs it: a compose that never mentions `${BB_DEV_DATA}` does not
  care.

  `ro` instead of `rw` on the projects share is worth knowing about: the
  sandbox could build from your source and never alter it. It breaks any
  compose that writes to a bind mount inside the project, which is common
  enough that it is not where I would start.

  To move to virtiofs later, add a `<filesystem>` block per share — the
  `<memoryBacking>` it needs is already in the XML for exactly this — and
  drop the matching `fstab` lines:

  ```xml
  <filesystem type="mount" accessmode="passthrough">
    <driver type="virtiofs"/>
    <binary path="/usr/libexec/virtiofsd">
      <sandbox mode="chroot"/>
    </binary>
    <source dir="/mnt/user/development/projects"/>
    <target dir="workspace"/>
  </filesystem>
  ```

  The `target dir` is the *tag*, not a path; `provision.sh --share
  workspace:/workspace` is what mounts it.
- **Guest agent.** `qemu-guest-agent` is installed by both paths so Unraid can
  shut the VM down cleanly instead of pulling the plug.

## Pointing BuilderBot at it

Three settings on the container's template, then the proxy comes off.

**1. Teach BuilderBot the VM's host key first.** This is the step that will
otherwise stop you with nothing useful in the log: `docker -H ssh://…` shells
out to `ssh`, the dashboard runs it non-interactively, and an unknown host key
makes ssh refuse rather than ask. From a session:

```bash
ssh-keyscan -H <vm-ip> >> ~/.ssh/known_hosts
```

`~` is the home volume, so this survives a container restart.

`bb-sandbox sdk` is the one verb that reads rather than configures, and the
one that needs no root: it hands you the controller's own `bb` — the copy
the agent unpacks into the packages store to run jobs with — so `bb-sandbox
sdk versions` at this console answers with exactly what the Tools tab shows
for this node, from the same generator. Read-only verbs only; installing
from here would go around the one-install-at-a-time rule the controller
keeps across every machine sharing a store, so it says so and points at the
tab. Nothing to run until a package job has put a `bb` there.

**2. Enroll it as a node.** On the dashboard's Nodes tab, **Enroll node**
mints a one-time token; run `provision.sh --controller URL --token bbe_…` on
the VM and it dials in and stays. The node opens no port and this container
holds no key that logs into it — the credential the node keeps opens its own
row and nothing else. Adding a machine by ssh address is gone (roadmap #18):
it existed only because compose used to run from this container over ssh, so
a node needed a key as well as a token. It does not any more. `DOCKER_HOST`
and `DOCKER_HOST_PATHS`, which named that machine before there were nodes,
are gone with that kind and are read nowhere.

Nothing but a sandbox VM is accepted, and the address is only half of what
decides that. An address of any other kind greys every Docker control out with
a sentence saying why, rather than half-working — and so does an ssh address
whose daemon does not **say it is the sandbox**. `provision.sh` writes a
`builderbot.sandbox` label into `/etc/docker/daemon.json` and restarts the
daemon; BuilderBot reads it back with `docker info` over the connection it
already has and refuses to drive anything without it.

The reason is the reason for the VM itself: the manager makes directories and
moves them with one-shot containers running as **root on the far side**, which
is only reasonable against a machine whose job is being wrecked. An ssh address
proves somebody typed one; the label is the only thing that says what is on the
end of it. A VM provisioned before this existed has no stamp — re-run
`provision.sh` on it, which adds what is missing and changes nothing else.

**Point it at a different sandbox and that one becomes the source of truth.**
Two VMs can wear one address — a rebuilt sandbox, a second machine given the
old one's IP — so a build records the daemon's own id as well as its address.
When the id changes, every record claiming a build on the machine no longer in
play is cleared, and the rows read as never built here rather than quoting a
version of something this daemon has never seen. The instances themselves stay:
their compose files and env are this side's and have nothing to do with which
daemon is plugged in.

**3. The path mapping, on the node's row: `/workspace:/workspace`** — and a
pair for any other share you mounted on *both* sides. `/devdata` is not one of them: it belongs
to the VM alone, BuilderBot never touches it, and naming it here would be a
line of configuration nothing acts on (the manager says so on the row when
you leave one in). An identity mapping, because the VM has the shares at
the same paths this container does. It is accepted without being checked
against this container's mount table, which describes its own mounts and says
nothing about the VM's, and it makes the path checks fall silent: a bind the
daemon resolves to the same directory is not a problem, and is no longer
reported as one.

Then delete the socket proxy container, if you had one. BuilderBot has no
reason to reach the host's daemon and no way to — the actual prize, and not
another layer of filtering but one fewer thing holding the keys to the real
containers.

**What this changes for a session.** The rule in every project's `CLAUDE.md`
says the daemon is a sandbox VM and is a session's to build on, run on and
wreck. So this hands Claude a Docker host it can actually use, which is the
half that is easy to miss while thinking about what it takes away. The
dev-instance *controls* stay the operator's, and the dashboard's own compose
project names stay the dashboard's.

**What does not change:** the classic builder stays on. BuilderBot forces
`DOCKER_BUILDKIT=0` because buildx attaches to a helper container and a socket
proxy refuses that; against the VM's own daemon buildx would work, and with it
the inline layer cache. That is worth doing and is not part of this switch —
it needs its own verification, and the classic builder is correct against a
real daemon, only slower to rebuild.

## What is deliberately not in it

No GPU, no Android SDK, no Playwright, no Actions runner. They stay in
BuilderBot, where the hardware and the shares already are. The sandbox is a
Docker host and nothing else, and keeping it that way is what makes throwing
it away cheap.
