# Installing BuilderBot

The Unraid-specific detail for every step lives in
**[unraid.md](unraid.md)**; this is the complete checklist with the
decisions you need to make.

The image, `ghcr.io/aquilaelabs/builderbot`, is public: pulling it needs no
login.

### 0. Know the credentials (they are NOT interchangeable)

Separate credentials for separate jobs: a **runner token** for the nodes' CI
runners, and **git SSH keys** or a per-project token for your projects.
Which of them your setup needs, what each is exactly, and the three things
that trip people up are in
[unraid.md, shared step 1](unraid.md#shared-step-1-credentials); decide
there before going on.

### 1. Create the state directories

```bash
mkdir -p /mnt/user/appdata/BuilderBot/{home,config/startup.d}
chown -R 99:100 /mnt/user/appdata/BuilderBot
```

| Dir | Holds |
|---|---|
| `home/` | each account's home on the controller (shell history, npm globals, which Claude login it is bound to); survives image updates |
| `config/` | your custom startup hooks (`config/startup.d/*.sh`) + persistent logs (`config/logs/`) |

Keep `home/` on a cache/SSD-backed share: it does heavy small-file IO.
(Logs can be relocated to the array; see step 5.)

### 2. Create the secrets folder (recommended)

Root-owned, so its contents are **never readable by Claude sessions**:

```bash
mkdir -p /mnt/user/appdata/BuilderBot/secrets/ssh

cp /path/to/git-key /mnt/user/appdata/BuilderBot/secrets/ssh/id_ed25519

# only if you publish to npm from a controller shell: any *.env file here is loaded the same way
cat > /mnt/user/appdata/BuilderBot/secrets/builderbot.env <<'EOF'
NPM_TOKEN=npm_xxxxxxxxxxxxxxxx
EOF

chown -R root:root /mnt/user/appdata/BuilderBot/secrets
chmod -R go-rwx    /mnt/user/appdata/BuilderBot/secrets
```

What this buys you: SSH keys are served by a root-owned `ssh-agent`
(sessions can push with them, never read them), a token in a `*.env` file
here never enters a session's environment, and all logs are redacted of
token patterns *and* the literal secret values. A node's runner token is
not a file here: it is typed on the CI runner page (under Build) and kept
root-only by the controller. Details and threat model: [docs/unraid.md, Shielding
secrets](unraid.md#shielding-secrets-pat--ssh-keys-from-claude-sessions).

Skippable: a project's settings can make an SSH deploy key for it or hold
its git access token instead, one project at a time. Or, if you don't care
about shielding, put keys in `home/.ssh/`; everything works, Claude can just
see them.

### 3. Install the container

**Docker template (recommended)**: get
[`unraid/builderbot.xml`](../unraid/builderbot.xml) into
`/boot/config/plugins/dockerMan/templates-user/`, then **Docker → Add
Container →** pick *builderbot*. From the Unraid terminal that is one
`curl` of the raw file, in [docs/unraid.md](unraid.md#install).

**Compose Manager**: copy `docker-compose.yml` + `.env.example`→`.env` into
a compose stack. Same container either way; don't run both.

### 4. Fill in the fields

Required / usually touched:

| Field | Set it to |
|---|---|
| Projects folder | One mapping for all of them: `/mnt/user/projects` → `/workspace`. Every folder inside it is a project |
| State paths | Pre-wired to `/mnt/user/appdata/BuilderBot/{home,config}` |
| **Secrets directory** | The folder from step 2 (or leave empty if unshielded) |

Everything else has sane defaults: full reference in [reference.md](reference.md#configuration-reference).

### 5. Optional features

| Want | Do |
|---|---|
| Android emulator, builds, CI | Enroll a node from the dashboard's Nodes page. This container compiles nothing and renders nothing: the toolchains, the card and `/dev/kvm` are that machine's |
| Web dashboard | Always on (it is the controller). Map port 7680 and open it: the first page is the setup, see step 6 and [the dashboard](dashboard.md) |
| Logs on the array | Set the **Logs directory** path field (template) / uncomment the `/logs` volume (compose) |
| Static analysis reports | Point the **Scanner reports** path at your scanner's output dir: read-only; see [Static analysis reports](building.md#static-analysis-reports) |
| Docker builds (CI jobs, a project's containers) | On a node, never in this container: a node's own Docker, or the Docker sandbox VM ([sandbox-vm.md](sandbox-vm.md)). The template has no Docker socket field |
| Extra tools | the Toolchains page, per node; the controller carries what it needs in the image |
| Virtual machines | **VM host** in a node's Features section on the Nodes page (or ticked on Enroll node), on a machine with `/dev/kvm`; then the VMs page, see [vms.md](vms.md) |
| A box on the internet that only serves | Enroll it hosting-only and tick the hosting firewall: it takes in 80 and 443 alone, and its page's **Lock down** stops and revokes it in one press |

### 6. First boot

```bash
docker logs -f BuilderBot          # banner → hooks → ready
docker exec -it BuilderBot bb doctor
```

Then open the dashboard. The first page makes the owner account; the setup
page after it is four steps, each a card with its own button: your first
node (**Enroll node** for a machine you already have, **Create sandbox VM**
for a new VM), your name and email, Claude Code on that node, and a first
project. The node cannot be skipped: nothing runs without one, so **Finish**
opens only once one is enrolled and answering, and it has to be one that
runs sessions, not a hosting-only one. The other three can wait: Home keeps
them in its Getting started card. Storage and the idle timeout are not
asked; their defaults are under Controller settings. After Finish, each page
gives a short tour the first time an account opens it; **Skip tour** with its
box skips them all, and About or your Profile brings them back.

Every `bb doctor` line should be `[ok]` or an expected `[skip]`. On the
controller it verifies: the workspace and home are writable, git is new
enough, each account has a commit identity, GitHub is reachable, a node can
take a Claude session, the **Docker daemon** on each node that has one
actually answers, a passed-through GPU's **graphics stack** is usable (not
only CUDA), each stored **runner token** is still accepted by its host, and
**SSH auth against GitHub** works (agent key or file key). Claude Code and
the Anthropic API are checked on a node, where sessions run.

Each person signs in to Claude on each node they work on, from that node's
Claude Code section on the Nodes page: **Sign in**, which a project's
**Start Claude** offers the first time. The flow runs on that node, the
machine Claude Code is installed on, and the code is pasted back in the
section. Each node keeps the login it alone refreshes; the controller holds no
credential, only which Anthropic account each node reported for you.

**CI runs on a node, not in this container.** Take the node the setup
enrolled, or enroll another (**Enroll node** on the Nodes page gives the
command to run on the machine; [nodes.md](nodes.md) walks it), open the CI runner page (under Build) with that node picked, add a runner
for your git host and press **Install runner** on it. It registers under the node's own name,
which is the label a workflow uses:

```yaml
jobs:
  build:
    runs-on: [self-hosted, bb-sandbox]
```

**Every label in `runs-on` must be one some runner carries.** A job asking for
a label nothing has sits in *Waiting for a runner* forever while the runners
show *Idle*: the job is simply not addressed to any of them, and neither
screen mentions the other. `bb ci-labels` lists every label the registry
knows, `bb lint` refuses a `runs-on` naming one that nothing carries, and
stale **Offline** runners carrying a label a job wants are worth deleting for
the same reason; they make a job look routable when nothing will pick it up.

### 7. Daily use and updating

A Claude session is opened from the dashboard, with **Start Claude** on the
project's card or page, and runs on that project's node. There is no `claude` in this container to exec into.

```bash
docker exec -it BuilderBot bb shell                        # shell as builder
docker exec -it BuilderBot bb status                       # what this box is
```

**Adding a project**: **New project** on the Projects page makes one, as a
fresh repository, a clone of one on a git host, or from an archive you already
have. Only BuilderBot makes a project: a folder made by hand on the projects
share is not listed. A project with a problem says so on its card: no git
repository or the wrong ownership in red.

**The apps for your machines**: the Android app is on the **Apps** page,
under Build, with Download and how to connect it, fetched by the controller from its own
release and kept current there. The devices signed in as you are the last
section of your **Profile**, under Settings, each with Disconnect. Which are offered is the **Apps** section of
the Controller settings page, or `/config/seed.json` before the first start
([reference.md](reference.md#the-seed-file)).

**Updating**: CI publishes `:latest` for any push to `main` that touches the
image's inputs (Dockerfile, `scripts/`, `config/`) + a weekly freshness
rebuild. Unraid's *Check for Updates* flips the container to **update ready**,
so click it. Builds seed their layer cache from the previous `:latest`, so a
scripts-only change is a small pull; the Monday rebuild is uncached on purpose
and is always the big one. *Run workflow* takes a **Rebuild every layer** box
for the same effect on demand: leave it off and a manual run is a cheap retry,
tick it to force a fresh pull of everything. To upgrade between releases, and roll
back, see [Upgrading](#upgrading). Compose: `docker compose pull && docker compose up -d`.

## Upgrading

**Pin a release, not `:latest`.** `:latest` follows the main branch between
releases. Each release publishes its own image, `ghcr.io/aquilaelabs/builderbot:0.6.0`,
and `:0.6` for the newest release of that line; pin one of those in your
compose file or template, and move it on when you choose to upgrade.

**What is supported:**

- From any release to any later release **in the same line** (0.5.0 to
  0.5.3, say), in one step.
- To a **new line** (0.6.0) **from the last release of the line before**
  (the newest 0.5.x). An older install goes there first, then on.
- **No downgrades.** Going back is restoring the backup the upgrade made,
  below, with the older image.

**What the controller does for you.** `/config` carries the version of its
state. On start, a controller moves older state forward, one numbered step
at a time, after copying `/config` to `/config/backups/before-VERSION` (the
last three are kept). It refuses to start, saying which release to go
through, on state older than it can move forward, and it refuses state from
a newer release rather than reading what it does not understand.

**Nodes and apps follow.** After the controller, update each node's agent
from its page when the dashboard asks; a node on an agent from before a
breaking change is held until it is updated, and says so. The Android app
tells you when it and the controller are too far apart.

**Read the release notes first.** A release that needs anything from you
(a setting that moved, a node to update) says so under **Upgrading** in its
notes, and anything removed was marked deprecated a release before.

**Rolling back.** Stop the container, put the image back to the release you
came from, replace `/config` with `/config/backups/before-VERSION`, and start
it.

## Bare metal

The same controller can be installed on a Linux machine of its own, without
the container: the same dashboard, state, `bb` and updates, laid out under
`/opt/builderbot` the way the image lays it out, run by the machine's own
service manager (systemd, OpenRC or runit) with an env file in place of
compose's. It is for a machine that is only BuilderBot, a small server or
a NAS, and it can use that machine as one of its own nodes, so one box runs
the dashboard and the builds and sessions with it.

**What it runs on.** Every system Enroll node offers for a node is one a
controller installs on, with the same `dev` tag for the ones not walked yet
(the installer is built on the node provisioner, and runs its pre-flight).
It needs Python 3.12 or newer; on a RHEL 9 rebuild it installs `python3.12`
beside the system's 3.9.

**Install**, from a checkout or an unpacked release, as root:

```bash
git clone https://github.com/aquilaelabs/builderbot.git && cd builderbot
sudo bash nodes/install-controller.sh --check        # changes nothing
sudo bash nodes/install-controller.sh --install
```

It installs the packages the image carries (`config/controller-packages.tsv`,
one list for both), makes an account for the controller (`builderbot`, no
password, no sudo but the image's two root helpers), lays the release out,
writes `/etc/builderbot-controller/controller.env` (yours to edit; every
setting is in [reference.md](reference.md#a-controller-installed-bare-metal-its-env-file)),
starts `builderbot-controller`, and then makes this machine a node of
itself. Open `http://ADDRESS:7680` and make the owner account, as on a
container install. The setup page's first step is then **This machine**,
the node the installer set up, with where it stands, and Finish waits for
it to answer rather than for a node you enroll; Enroll another machine is
there for more, and none is needed. `sudo bb ...` is the container's `docker exec -it
BuilderBot bb ...`.

Options worth knowing: `--workspace PATH` (the projects folder, by default
`/srv/builderbot/projects`), `--port N`, `--no-node` (the controller alone),
`--docker` (the controller's account in the docker group, the bare-metal
form of mounting the docker socket into the container: containers can then
run on this machine's daemon from the controller; docker is root here).
Give the machine a fixed address: its own node reaches the controller at
it.

**Its own node, and the wall.** The node half is `provision-linux.sh` run
as it is, with `--beside-controller`: a job account (`bb`) and a session
account (`builder`), neither of which can read the controller's state, env
file or secrets, reach its loopback ports or use docker. A session there is
covered from all of it and runs in a network of its own, and none starts
when any of that does not hold: the Doctor and the node's row say why. The
node builds and runs sessions, and runs no containers (its job account is
out of the docker group, since docker is root on the machine that holds the
controller). The reasons and the threat model are in
[decisions.md](decisions.md#a-controller-installed-bare-metal-and-its-own-node).

**Updating** is the image pull's equivalent:

```bash
sudo bash /opt/builderbot/nodes/install-controller.sh --update                 # the newest release
sudo bash /opt/builderbot/nodes/install-controller.sh --update --release v0.7.0
sudo bash /opt/builderbot/nodes/install-controller.sh --rollback               # the release before
```

An update fetches the release, asks its own state check whether it would
start on this install's state (and changes nothing when it would not),
lays it out beside the one in use, switches to it and restarts; the
release before is kept. The controller moves the state forward as it does
in the container, with the same copy first, and `--rollback` puts that
copy back when the newer release had moved the state on (what the state
held then is kept under its `backups/`). The [Upgrading](#upgrading) policy
is the same.

**Taking it away.** `--remove` stops the controller and takes away its
release, service, `bb` and wall, and this machine's node; the state, the
env file, the secrets, the account and the projects stay, and `--install`
puts it back on them. `--remove --purge` takes all but the projects.

## Building locally instead of pulling

```bash
git clone https://github.com/aquilaelabs/builderbot.git && cd builderbot
cp .env.example .env && nano .env
docker compose build && docker compose up -d
```
