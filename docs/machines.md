# Machines: the controller, nodes and storage

The Machines group on the rail: **Controller settings**, what the controller
owns and applies live; **Nodes**, every machine work runs on; and
**Storage**, what a node's disks hold. **Jobs**, the queue of work placed on
the nodes, is a page of its own on the rail. This doc covers enrolling and
running nodes, their stores and their network, the controller's settings and
logs, the jobs, and a Mac as a node. The design behind nodes is
[nodes.md](nodes.md); the sandbox VM a node usually is,
[sandbox-vm.md](sandbox-vm.md).

## The Nodes page

**Nodes**, under Machines, is the registry ([nodes.md](nodes.md)): every
machine work can run on. This container is not among them; it runs no work,
takes no toolchains, and has nothing any section here configures, so with
nothing enrolled the page says so and offers the one thing there is to do.
(It does keep a node record of its own, which is how a share it mounts is
recognized as the same store a node mounts; that is plumbing, not a node on
the page.) The page shows one node, picked in its bar beside **Create
sandbox VM** and **Enroll node**: a header with its state, and where it dials in from, which is the address of its
last hello, so a node whose address moves is followed within a minute, its
terminals rebound onto the new address by its agent and the session-ports
rule on the node rewritten if the controller's own address is what moved,
and its agent (with
**Update agent** when this container ships a newer one, busy until the node
comes back on it), then **sections**, each a fold with its status on the
heading so a phone reads the headings and opens one: Health (the meters:
cpu, memory, the card's load and its own memory where an NVIDIA driver
answers, and each store's room; the toolchains its census found, which is what a project bound to it can
build), Projects (the projects bound to it), Sessions (whether it runs them,
and which are open), GPU (where it has a card), Claude Code (each account's
sign-in there), Storage (mounts and stores), Network, and Advanced, which
holds the node's **name** (Rename changes what it is called everywhere here:
the pickers, the project cards and the label a runner installed from then on registers
with; a runner already installed keeps the label it registered with until
it is reinstalled), the path
mapping and the rarely pressed verbs: **Drain** (finish what is running,
accept nothing new: what makes a node safe to reboot), **Clear cache**,
**Revoke**, **Disable** (the operator, 11 Oct: kept and configured, its agent
dialing in, but off every picker, refused to a project's set and handed no
work or session until **Enable**), and **Un-enroll**, which on a node
provisioned as a sandbox that is dialing in uninstalls BuilderBot from the
machine and then removes the node here (retire: off every list, its record kept as
history, and an id is never reused), and on any other removes the node here
only, saying BuilderBot's pieces stay on the machine. Neither Disable nor
Un-enroll goes through while a Claude session or a container is running on
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
as a host (cloudflared with its token, Tailscale's login, the port 22 rule,
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
projects on one VM share it. **Its Claude sessions too** (roadmap #24,
docs/nodes.md §19): a node provisioned with a session account keeps two
ttyds up beside the agent, running bb-tty from the bb the controller ships,
so a session on a project bound to it works *on* that machine, with its
toolchains, in the copy of the project its agent keeps at `/workspace` in
step with this container's (a synced copy, the one way a node holds its
projects: nothing mounts the projects share on a node). The node's census
says whether that half is up (`session`: ports, account, which Claude the
account has) and how far each copy is; `bb roadmap`, `bb bug`, `bb version` and the other verbs
whose state is this container's are relayed back here over the API with the
session's own token. The terminal proxy sends a bound project's session to
that node when its census says the half is up and the project's copy is there, and
refuses with the reason (on the project's Start Claude and in the terminal) when
the node cannot take one, rather than starting it on the wrong machine. A
project with **no** node has no Claude session at all: this container carries
no Claude Code, so the button says so and names what to do. Its shell still
opens here, on the same share (a tree to read, the linters, git) because
what moved to a node is Claude and not the terminal. A node's sessions ride its
heartbeat onto the Sessions page, with the node named, and ending one
there reaches the node's agent within a poll. What a project can actually do on its node is
what is **installed** there: its Health section lists the toolchains its census found,
and the Toolchains page's node picker is where more are added. (Underneath, the
node still refuses a job asking for something it did not enroll with: the
enforcement of docs/nodes.md §15 door 7, but every node enrolls with the
full set, so it is a mechanism rather than a setting.)

**An account that does not administer sees the Nodes page and changes
nothing on it but its own sign-in.** Its picker lists the nodes its own
projects work on and no others; every control on the node's page is
ghosted for it, updating Claude Code and enrolling included, and a line on
the page says so; the verbs behind those controls are an administrator's on
the server as well.

**Create sandbox VM** is the step before all of this when there is no
machine yet. **Pick what runs it**: Unraid, Proxmox VE, libvirt/KVM, QEMU on
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

Two of Enroll node's options are dev features too, offered tagged *(dev)*
only while *Offer dev features* is on, since neither has been proven end to
end yet: reaching the controller **through WireGuard**, and a **Tailscale**
SSH door. A public hostname and the cloudflared door are offered to everyone.

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
one node at a time, picked in its bar: a line saying when it was measured,
its filesystems as a stack of meters, its stores and Docker's share, then
each project's folders on it (the synced copy, the build cache, artifacts, a
dev instance's data, emulators, the accounts' build caches), largest first,
with every project this account may not see folded into one line. The
numbers are the agent's hourly walk, said with their age; **Measure now**
asks for a fresh one, which the node's next report brings.

## Controller settings

**Controller settings**, the first page under Machines (`#/machines/settings`),
drawn only for an account that may read the controller, is what the
**controller** owns and can apply live. Its bar carries the container's uptime
and the build it is serving. Its sections, each with its own Apply and Revert:

- **Logs**: how long logs are kept, and the downloads (see [Logs](#logs)).
- **BuilderBot bug reports**: what sessions and people reported about
  BuilderBot itself, and **Clear reports**.
- **Claude sessions**: the idle rule, which ends a session after N minutes
  with nothing typed or written, here and on every node, where the node
  itself enforces it so the rule holds while this container is down.
- **Storage on this controller**: where each kind of thing that grows
  (project snapshots, job snapshots, the git relay's repositories, the Git
  view's working area, the logs) is kept, moved to a new empty path on Apply
  and switched once all of it is there, while the records, the database,
  the signing keys and the git credentials stay in the state directory
  (`paths.py`).
- **Apps**: which of the apps a person installs this controller offers on
  the Apps page ([reference.md](reference.md#the-apps-a-person-installs)).
- **Reach from outside**: the home tunnel the controller runs itself (R176,
  `tunnel.py`): the hostname a node off the LAN dials, the tunnel's token from
  Zero Trust (a secret, said to be set and never shown back), and an optional
  Cloudflare API token with which the hostname's record and the tunnel's two
  rules (the agent's API to the controller, everything else 404) are written
  on Apply rather than clicked; the section's line says whether cloudflared
  is in the image, running and registered.
- **Debugging**: one switch, *Debug mode*, and a *Debug settings* button
  beside it that is live only while the switch is saved on: behind the button
  are the settings a developer of BuilderBot reaches for and nobody else
  should meet.
- **Reset BuilderBot**, last.

The page says plainly what still comes from the environment and why (the
placement rule and the unhardwiring are docs/nodes.md §13 and §11).

One switch in Debug settings, *Offer dev features*, decides which product
this dashboard is: alpha is what has been run for real (GitHub and Gitea
among git hosts, Unraid among the VM sandbox methods, Debian's and RHEL's
families for the provisioner), dev is the rest, written to each product's
documented shape and never run. Off, only alpha is in the pickers and a dev
entry asked for by name is refused with the sentence that names the switch;
on, dev appears tagged *(dev)* and the header says *dev*, so the two
dashboards are never confused. Each catalog entry carries the evidence that
vetted it (`forges.py`, `vmtemplate.py`, the provisioner's family list), and
an entry crosses over when a lab suite or a real run proves it.

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

**One file per container start, per stream.** All four rotate together on
boot, so a generation number means the same boot in every one of them, and
`.1` is the previous run of the container.

| Log | Where |
|---|---|
| Startup, the runner supervisor, and every later warning | `config/logs/builderbot.log` |
| The dashboard server, in full | `config/logs/dashboard.log` |
| Every compose call the Docker manager made | `config/logs/docker.log` |
| The terminal server | `config/logs/ttyd.log` |
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
or the controller's **diagnostics** as one JSON file (what `bb diag` prints,
the reports sessions made about BuilderBot among it, redacted and on the audit
trail), and **Clear** deletes the kept generations, the archived CI runs and
every finished job's log without touching the ones being written. **Clear
reports**, in the BuilderBot bug reports section, deletes every report sessions made about
BuilderBot, after a confirmation that says how many; the numbers carry on, so a bug that names report #3 never meets a
second one, and a session cannot clear them.

Two deliberate omissions from *this session*. `ttyd.log` is the terminal
server's connection churn (22,000 lines against 4KB of boot log on this box),
so it is in the archive and not in the thing you open to read what happened.
And the **CI logs stay where they are**, under `config/ci-logs/<repo>/`, one
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

## A Mac as a node

Enrolling a Mac is a dev feature: Enroll node offers it, tagged *(dev)*, and
the controller serves `provision-macos.sh`, only while *Offer dev features*
is on, since the Mac path has not been proven end to end; a node that is
already a Mac keeps working either way.

`nodes/provision-macos.sh` enrolls a Mac as a **guest** node (bare, it prints
its help; the command to run is the one **Enroll node** gives you): one
directory
(`~/.builderbot`) and one launchd agent that runs as you at login, no root,
nothing in `/etc`, and `--remove` takes exactly that away. It is written for
the bash macOS ships, so it is its own file rather than a branch of the
Linux provisioner. `--check` runs only the pre-flight: the command line
tools, python3, Homebrew, Xcode, room, and whether the controller answers.

What a Mac node is for is what only a Mac builds: iOS, macOS, the Apple
half of a Flutter app. `--toolchains /Volumes/SDK` points its toolchain store at
the same share the Linux nodes use, mounted over SMB; its toolchains land under
its own directory in it, named by its node id, and nobody else's are touched. The
Toolchains page shows the node as a Mac and offers what the catalog packages for
`darwin`: the JDK, Node, Go and Flutter resolve their macOS downloads
through the same recipes, and `xcodes` installs and switches Xcode versions
from Apple's own downloads (Xcode itself is Apple's to serve and needs an
Apple ID once). The agent's package manager there is Homebrew, its service
launchd; the Nodes page offers no Storage or Network, because a Mac's mounts
and address are its owner's, and asks for no root. Sessions on the Mac
itself need a `/workspace` the agent can keep a synced copy in, which on
macOS is one line in `/etc/synthetic.conf`, and are not set up by the
script.

Untested on a real Mac yet: the script and the agent's macOS path are
written against Apple's documentation and the agent's own tests, and the
first enrollment is the proof.
