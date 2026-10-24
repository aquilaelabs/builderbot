# Containers and nginx

The Containers group on the rail: **Containers** is the Docker manager,
where a project's containers are built, started, stopped and given their env
on a node, and **nginx** is each node's reverse proxy. A project's own
containers are also its page's Docker view. This doc covers the manager, a
container's row, a dev instance built from a project and its mounts, how an
instance is reached, the containers' networks, nginx, and image updates.

## The Containers page

**Containers** on the rail is the **Docker manager**, which is where a project's
containers are built, started, stopped and given their env. A project can have
several: the Artifacts view's dev row is one button, **Send to Docker
manager**, which names a container and takes you there; every container of a
project is built from that project's codebase, and rebuilding takes whatever
that codebase says at the time. It opens on the project's own name while the
project has no container and on `<project>-2`, `-3` after, so another one is
the same press, and a session sends its project the same way with `bb
devapp new`, under the project's **Run its container** setting.

**The page at a glance.** Under the bar, a row of tiles says how many
containers run of how many are here, how many have an update due, how many
projects they belong to, and how many on the daemon nobody here started; a
row of chips narrows the list to one project (All puts it back, and nothing
is saved). A container's row is its name and a state pill with a dot of its
color, a facts grid (image, ports, containers, what it was built from, its
compose file), its notices, its settings with one Apply, then its action
bar. A published port is a link to where it answers, and a port nginx
routes to shows the address as a fact beside it. Docker's health is read
off the status and said on the pill: healthy, unhealthy or starting, not
just running. The bar holds a search box (a name, an image, a port or a
project, narrowing the rows as it is typed) and a Cards or List switch: in
the list each container is one line, its name, state and facts, that opens
into its card, which is the view for a node with thirty containers and
this browser's choice to keep.

**A shell inside a container.** A running instance's row carries **Shell**
for its first running container, and **Shell in** each other one under
More; it opens `docker exec` into that container as a terminal in the
dock, bash where the image has it and sh where it does not, on the machine
the container runs on. On a node that is the agent's third terminal server,
on port 7683 and open to the controller only, run as the docker account:
the session account stays out of docker, since docker is root on the
machine. It is for a person who may start and stop that
container (its project's account or an administrator) and has a shell, and
for an administrator alone when the project's **Run its container** is
Deny. A container on a hosting-only node runs no terminal, so its Shell is
dead with the reason under the row. The controller checks the account and
that the container is one of the instance's running ones before anything
opens, and on a node the node asks the controller again rather than taking
the address's word for which container it is.

**The daemon is a node.** The sandbox VM is enrolled on the Nodes page like
any other node, and what this container's paths are called over there is set
on the node's page (its path mapping, under Advanced), because the daemon resolves a compose file's bind sources
on its own filesystem. The Containers page names the node it is on and
`bb doctor` prints the same line from the same function, so the two cannot
disagree about which daemon is live.

**A daemon has to say it is the sandbox before anything is driven on it.**
`nodes/provision-linux.sh` writes a `builderbot.sandbox` label into the VM's
`/etc/docker/daemon.json`; the node's agent reports it in its census, and a
daemon without it is refused exactly
like an unreachable one: named as the reason, with the command to fix it. An
ssh address only proves somebody typed one, and every one-shot container the
manager runs is root on the far side: what makes that reasonable is the far
side being a box built to be wrecked, which is a thing only the provisioner
can vouch for. A VM without the stamp gets it by re-running
`provision-linux.sh`, which changes nothing else.

**Point it at a different sandbox and that one becomes the source of truth.**
A build records the daemon's own id as well as its address, because two VMs can
wear one address: a rebuilt sandbox, a second machine given the old one's IP.
When the id changes, records claiming a build on the machine no longer in play
are cleared rather than left quoting a version this daemon has never seen; the
instances stay, since their compose file and env are this side's.

**With no daemon reachable, the controls that would drive one are disabled**,
and the Containers page says why in words at the top: *"why is everything grayed
out"* should be answered by looking, on a phone as at a desk. That is the node
unset, or a sandbox VM this container
cannot reach; `available()` in `devapp.py` already distinguishes them, and the
answer rides the status poll memoised, because asking it properly is a
subprocess and the poll is the page's heartbeat.

Two things deliberately stay live. **Edit** and **Env** open a compose file,
which is a file whatever can run it. And the page still opens, because
disabling the way to *read* a diagnosis is how a dashboard goes quiet for no
visible cause. There is no Refresh to keep live: each node's heartbeat
carries a fingerprint of its containers (their names, states and health), and
the page reads the node again when it moves, so a daemon wired up a moment
ago, a container that crashed or one a shell started is on the page within a
heartbeat.

**The rows are still there, and they stop claiming anything.** What an
instance *is*: its name, its project, what it was last built from, what its
env still wants: lives on this side of the wire and needs no daemon; only
whether it is *running* is the daemon's to know. So a manager opened against a
VM that is off lists everything on record, grayed, each row saying **state
unknown** rather than reporting one nobody asked for: an unreachable daemon is
not evidence that anything stopped. It is also fast, because a daemon known to
be off is asked nothing, rather than waiting on a machine that is not there
until a timeout.

**With more than one docker host, the manager grows a node picker.** Nodes
with the `docker-host` capability are listed online or not; picking one
switches the whole view to that node's daemon: one page, redrawn, never a
page per node. Each node's last-known container list is kept, so switching to
an offline node paints instantly in the grayed state above rather than
spinning at a machine that will not answer, and the reason is that node's
own. **New container** and **Send to Docker manager** gain the same select,
defaulting to the project's own node from its settings (a per-project
binding, `auto` unless chosen); an instance stays bound to the node it was
created on, and everything that acts on it: Up, Down, Rebuild, the data
directory's one-shot containers: addresses that node's daemon.

**Compose runs on the node, not from here.** A dev instance's Up, Down,
Rebuild and Remove are executed by the agent with the node's own docker: the
dashboard sends the plan and the compose file, the node runs it. So an
enrolled node needs nothing but the token it enrolled with: no ssh key, no
open daemon port, nothing dialing in.

## A container's row

Each row folds open to show what that container publishes and what it mounts,
read only when you open it: parsing a compose file is the one thing the page
deliberately does not do for every row at once. Lines wrap rather than scroll:
a host path is long, and a row that scrolls sideways on a phone hides the half
you were reading.

**A long build says what it is doing, and can be stopped.** The command's
output is streamed into the row as it arrives rather than handed over when it
exits, so a `compose build` spending four minutes pulling layers is not four
minutes of a spinner. The phase word above it still says *building* or
*starting*; the tail below says what the phase is spending its time on. It is
raw and deliberately not parsed into a bar: docker rewrites a line per layer
per tick, and turning that into a percentage is the thing the Toolchains page
already gave up on.

**Abort** sits beside it while a job runs, and asks nothing first. Stopping a
build is not destructive: what is already built is kept, exactly as a failed
build's work is, and the signal goes to the process *group*, because a compose
CLI waiting on a pull leaves the download running if only the CLI is asked to
stop. The row then says how the job ended rather than silently reverting to
whatever state it was in.

**New container** on that page runs something with no project behind it, and
takes the **project** it belongs to (Send to Docker manager takes the same,
with the project it is built from picked by default): a
name, a compose file and an environment, which is the shape Portainer's stacks
and Dockge use. Labels are not a fourth box, in compose they belong in the
YAML. The compose file is checked by compose itself before it is saved, and
kept in `/config/containers/<name>/` where no project scan can see it; its
relative bind sources resolve against its own data directory under `/devdata`,
which is a path the daemon has; this container too where the share is
mounted here, and only the sandbox where it is not. Removing one takes its files
with it, because its compose file *is* the thing.

It lists what has been sent to it, not every project that could be sent: a
project with a compose file does not appear there until you send one, and
**Remove** takes a container down and drops it from the list again. Removing
keeps its env file and its data directory, so sending it again under the same
name finds them, and the project's Artifacts view is untouched either way,
which is where it comes back from.

The same page lists every container on the picked node's daemon, not only the ones this
dashboard started. A port taken by something else is exactly what you open a
list like this to find out about, so the others are shown and marked *not ours*
rather than hidden, and an administrator can start, stop and restart one by
name and read its log.

**Every row belongs to a project or to none**, and the page is grouped that way:
each project's containers together under its name, the projects in
alphabetical order, and what belongs to none last. A container built from a
project belongs to it until its row says otherwise, one written here belongs
to the project picked when it was made, and one somebody else started belongs
to none until an administrator picks a project on its row; that choice is kept
by name on its node, so the same container recreated keeps it. The project it
belongs to lists it in its notebook's Docker view, and that project's
sessions are the only ones that can see it: `bb devapp ls` lists them and `bb
devapp log NAME` reads one, while rebuilding, changing the env, starting and
stopping follow that project's *Agents may: Run its container*. An account
that is not an administrator sees what belongs to its projects.

## A dev instance built from a project

**The dev instance** heads the list, shaped like every other row in it: the
kind on a pill (`docker`, where a file says `apk` or `xpi`), the compose
project's own name in bold, and whether it is `(running)`, `(stopped)` or
`(down)` in parentheses after it, where a file carries its size and age. The
name is the compose project's rather than a container's: a compose file may
set `container_name` to anything it likes and may declare several, and this is
the one name that is always true of all of them.

Under it, and not behind a fold, are **what it publishes and what it mounts,
written the way Unraid's own Containers page writes them**: container side
on the left, host side on the right, and the arrow saying which way it goes:
`/library ← /mnt/user/plex-media` for a read-only mount, `↔` for a writable
one, `7474:TCP ← 192.0.2.10:7475` for a published port. That is deliberately
not a second notation to learn; it is the one already used for every other
container on the box. All of it is read from the *resolved* compose config, so
a path or a port assembled out of variables shows as the value compose arrived
at rather than as the spelling, which is also how the checks below can judge
a mount without knowing anything about the variables that built it.

A running service gets **Open** beside its buttons. One published TCP port
links straight there, pointed at this page's own host; several open a chooser
listing every `host:port` for you to pick from. Unraid does not discover this
either: its tab reads a `WebUI` line somebody wrote into a template, or the
`net.unraid.docker.webui` label, so one port is the only case where it can be
known rather than asked, and asking beats guessing for the rest.

The mounts are not repeated in the warnings below. They are all on the row
already, with the path each one lands on, so naming the ones that reach past
the project would restate what is two lines above in worse words. What the
warnings keep is the set that is invisible otherwise: `privileged`, added
capabilities, host devices, and the host's process or network namespace:
the flags that make a container more than a container. It appears when the project
carries a compose file
and the project's node is the [sandbox VM](sandbox-vm.md): a machine
whose only job is running Docker, which is what keeps all of this away from
the server's real containers: the project's compose app, built over there and
controlled in the file rows' own language. **Up** and **Down** are compose
against the project's own file, under a compose project named for the
instance. **Env** edits the
instance's env file: kept in `/config/devenv/`, never in the repo, handed to
compose as `--env-file`; Up stays dead while the repo's `.env.example`
declares keys the env does not answer, because starting a service against an
env known to be missing is a crash with extra steps. **Rebuild** un-ghosts
when the code has moved since the last build (a new commit, or a dirty tree)
and runs build → down → up, unless the rebuild finds new settings in
`.env.example`, where it stops after down, rewrites the env as the new
example with the old values preserved in comments, and leaves Up for the
operator. Before the first build the button reads
**Build**, and nothing is built until it is pressed.
**Build from** picks the branch it is built from. A project's tree is shared, one checkout for every session and person on it, so this does not switch it:
the build comes from a git worktree of that branch beside the project, marked
with a `.bbignore` so the projects list knows what it is, and the project's own
checkout is left where it is. The row then says which branch it was built from,
and "the code has moved" means that branch has, not the working copy. **Send to
Docker manager** offers the same picker, because a second instance is usually a
second branch: a pull request running beside the one that is up.

Two instances of one project are the same compose file, so they publish the
same host ports and the second cannot start as written. That is said **before**
the press: the row names the port and what already has it, read off the
container list the page already has, and the answer is the per-instance env
file, which is where a compose written with `${PORT}` takes its ports from. A
compose that hard-codes them has no answer but a sentence. A compose that
references `${BB_DEV_DATA}/...` gets its volumes on the cache drive by
convention, in a per-instance directory the VM makes itself, so that share is
mounted over there and needs no mount here at all. By the same convention a
build sees `BB_BUILD_REV`, `BB_BUILD_AT` and `BB_BUILD_VERSION`: the commit
it is from, when, and the project's version, for a compose whose build args
want a stamp (BuilderBot's own passes them to its Dockerfile). An image tag
takes `BB_BUILD_TAG`, the same version with no `+`, which a tag cannot carry.
`BB_DOCKER_GID` is the docker group's id on the instance's node, for a
service that reaches the daemon's socket as a member of that group.
Every step of a rebuild (the pull, the stop, the start) reads the compose
file with the same variables, so an image named by `${BB_BUILD_REV}` is the
one pulled and started. BuilderBot itself gets the
row too, as a second container on another machine, never the one you are
using; expect
`up` to refuse while the real one holds the same host ports, which is the env
file's job to change.

**The daemon's filesystem is not this container's**, and that is the one thing
about a remote daemon easy to forget and impossible to see: a bind mount's
*source* is resolved by whoever runs the container, which is the host.
`/workspace/alpha` and `/devdata/alpha` mean something here and nothing
over there, and docker answers a missing bind source by creating an empty
directory and mounting that, so on Unraid, whose root filesystem is RAM, the
result is an app that starts with no data and loses it again at reboot. It
reads as a bug in the app. The node's path mapping states it once: the
same one you made when you mounted the volumes, and BuilderBot both hands
over host paths (that is what `BB_DEV_DATA` carries) and names any of a
compose file's *own* paths the host will not find, on the row, before you
press Up. Absolute host paths, which is what a working compose here already
writes, are unaffected. Build contexts are unaffected too: the classic builder
streams those from this side.

**Bind directories are made before anything starts**, as a step of Up and
Rebuild rather than a button somebody has to remember. A compose file names
directories that have to exist, and docker creates a missing bind source
itself (as root, then chowning it) which on a share that squashes root fails
and takes the whole run down with *operation not permitted*, leaving the
directory behind so the second press works: an intermittent-looking failure
with a fixed cause. So they are made first, owned by whoever BuilderBot runs
as, which is the ownership Unraid expects.

Made on whichever side can reach them, which is not something to think about:
a share this container mounts is a local `mkdir`, and anything else is a
one-shot container on the VM: the same mechanism that makes the per-instance
dev-data directory, running as BuilderBot's uid, which is the whole point
since docker's own attempt is as root. Which shares the VM has is the VM's
business: nothing is declared on this side, so a share added over there next
month needs no BuilderBot setting touched.

The one thing it will not create is a bind at a share root itself; there is
nothing below it to make, and docker creating the root is the as-root failure
this exists to avoid. The guard still holds the shape: the argv is rebuilt and
compared whole, the mount must be a single plain-named share root, and every
path in it is plain names only, so the reach stays a `mkdir -p` as an ordinary
user on a machine built to be wrecked.

`mkdir -p` throughout, so one that already exists is left alone and starting
twice does the same thing once. A directory made over there cannot be seen
from here afterwards, so what was made is recorded against the instance. What
could not be made is written into the job log and the compose runs anyway;
letting compose say what actually went wrong beats refusing on this side's
reading of a file compose is about to read for itself.

**A path this container also mounts needs a pair, even on a sandbox VM.**
`/workspace:/workspace` covers the projects share and nothing else. If you also
map the dev-data share here, so you can create a compose file's bind
directories from a shell, which is the usual reason to, then a compose
mounting `/devdata/...` is naming a path BuilderBot has, and it will say so
until the mapping answers for it. `/devdata:/devdata` is that answer when both
machines mount the same share at the same path, which is the arrangement the
sandbox is for. The alternative is to not map it here at all: what BuilderBot
cannot see, it does not check.

**Container names and project names are separate groups.** A project existing
reserves nothing: a container may be called `mediareducer-dev` while a project
is too, because they are not the same kind of thing. The one name that cannot
be reused is another *container's*: two instances resolving to one compose
project name would be one set of containers, one env file and one data
directory with two rows driving them, so the second is refused and told which
instance has it. A project's *default* instance is named for the project,
since nobody typed a name for it.

**Which project a container belongs to is tracked separately**, and is never
read out of its name; it is the key it is stored under. That is what decides
whose sessions may touch it, so a project can stand up several
containers, name them anything, and still own all of them.

Which compose projects on the daemon are **this dashboard's** is answered the
same way, from what it has stored, not from what things are called. So the
manager can list every container on the VM, including ones you started by
hand, and still be right about which of them it is driving.

## How an instance is reached

**How an instance is reached.** Each running instance on the Containers page
carries its route: the URL, a picker for the mode, and Apply, which is what
writes the pick: a pick alone changes nothing. **lan** is the
published port at the node's own address.
**funnel** is Tailscale Funnel on the node: a public https URL at the node's
MagicDNS name with no DNS, certificate or firewall change: applied by the
agent, so it is offered only on an agent node that has tailscale logged in;
the row says *asked for* until the node reports the funnel is up, and
switching back to lan closes it. **public**, a reverse proxy with a wildcard
record, is named in the picker as not built so the third mode is visible for
what it is (docs/nodes.md §7).

## nginx

The nginx page keeps one list of public **Hostnames**, shared by every node's
nginx (the operator, 12 Oct): a name is added once and shows where it is
routed, and is deleted only when nothing routes it, the refusal saying
where it is. A route's hostname is picked from that list, so several routes,
nodes and projects' containers use one name without typing it again.

nginx keeps up to date like the toolchains and the agent (R192, the
operator, 11 Oct). The controller reads the registry's tag list once a week
(Check now on the nginx page reads it at once) and keeps the newest release
line's alpine tag with its digest; a node's nginx is pinned to a digest when
it is deployed or updated, written into its compose file as
`nginx:TAG@sha256:...`, so a Save rebuilds with exactly what it had and
nothing moves under it. A deployed nginx behind the newest line says so on
the nginx page's node and on its Containers page row, each with Update, which pins
the new digest and rebuilds; the bell carries a note of its own kind, to the
digest, so Dismiss holds until the registry moves the line again. One
deployed before any check had read the registry is unpinned, and behind
whatever is newest until its first Update.

## Each project's containers on their own network

**Each project's containers on their own network (R178, the operator, 11
Oct)** is the same idea for the containers themselves, for a node two
web-facing projects share. Docker already keeps compose networks apart,
but a container reached another project's container by the node's address
(its published port, after Docker's DNAT) and the node's own ports, measured
on the dev pair. The agent's keeper runs a second table,
`builderbot_ctrnet`: forward from a compose bridge passes to its own
bridge, the bridges of the projects its owner reads, the controller, DNS
and the internet, and is dropped to any other bridge and rejected to the
private ranges; into the node it passes to the controller, DNS, 80 and 443
(nginx, the way in) and the published ports of its own project and the ones
it reads. The hello carries the map (`devapp.container_net_own`, compose
project to the compose projects it may reach) and the switch (config
`container_net`, on by default for a hosting-only node, on the row beside
the session switch elsewhere); a prefs change or the switch asks for a
hello, so a container reaches a newly read project within a poll. Nothing
is marked: a missing table leaves Docker's own rules, and the row says not
in force rather than a container being cut off. A container BuilderBot
deploys itself is **System**'s (R180, the operator, 11 Oct): the nginx
page's container today, set by that deployment and by no picker, a person's
or a session's, and given every bridge and every published port on its node
by the map (`all`), since a proxy or a monitor that is nobody's has to see
everybody's. nginx needs none of it yet, being on the host network; the
owner is for the day a deployment of BuilderBot's sits on a bridge.

## Image updates

Every other container's registry images keep up to date the same way (R195,
the operator, 11 Oct). A service that runs an image by tag, with no `build:`
(mariadb, a linuxserver image, ghcr.io/aquilaelabs/builderbot:latest), is
compared once a week, and on Check for updates on the Containers page: the digest
its node pulled (`docker inspect`'s RepoDigests) against what the
registry serves for that tag now, over the registry's v2 API with an
anonymous token (imagecheck.py). One that differs says so on its row with
Update, which pulls (`compose pull --ignore-buildable`) and starts it again;
the bell carries one note per node. What is built from code is not asked:
Rebuild is what moves that, and it is ghosted until the code has moved. An
image pinned by digest (nginx's) is its own page's, an image never pulled is
pulled by Up, and a private one says the registry would not answer. A
project's container is named whatever its owner wants: Send to Docker
offers the project's name and the compose file's folder or variant, and the
Edit dialog renames it while it is down, its record carrying the name while
the instance keeps its key.
