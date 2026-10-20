# Installing BuilderBot

The Unraid-specific detail for every step lives in
**[unraid.md](unraid.md)**; this is the complete checklist with the
decisions you need to make.

### 0. Know the three credentials (they are NOT interchangeable)

Three credentials, three places, three jobs: a **GHCR pull token** on the
host so the server can pull a private image, a **runner token** for the
nodes' CI runners, and **git SSH keys** for your projects. Which of them
your setup needs, what each is exactly, and the three things that trip
people up are in [unraid.md, shared step 1](unraid.md#shared-step-1-credentials);
decide there before going on.

### 1. Authorize the server to pull the image (one-time)

A `docker login ghcr.io` on the host with the pull token, persisted across
Unraid's reboot of root's filesystem: the commands, and why the token must
be `read:packages` only, are in
[unraid.md, shared step 2](unraid.md#shared-step-2-log-the-unraid-host-into-ghcr).

### 2. Create the state directories

```bash
mkdir -p /mnt/user/appdata/BuilderBot/{home,config/startup.d}
chown -R 99:100 /mnt/user/appdata/BuilderBot
```

| Dir | Holds |
|---|---|
| `home/` | each account's home on the controller (shell history, npm globals, which Claude login it is bound to); survives image updates |
| `config/` | your custom startup hooks (`config/startup.d/*.sh`) + persistent logs (`config/logs/`) |

Keep `home/` on a cache/SSD-backed share: it does heavy small-file IO.
(Logs can be relocated to the array; see step 6.)

### 3. Create the secrets folder (recommended)

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

### 4. Install the container

**Docker template (recommended)**: get
[`unraid/builderbot.xml`](../unraid/builderbot.xml) into
`/boot/config/plugins/dockerMan/templates-user/`, then **Docker → Add
Container →** pick *builderbot*. The repo is private, so the raw URL 404s
without auth: easiest is to save the file from your browser and drop it on
the `flash` SMB share; [docs/unraid.md](unraid.md#install) also has an
API-based `curl` (which needs a *contents*-read token, not the
`read:packages` one).

**Compose Manager**: copy `docker-compose.yml` + `.env.example`→`.env` into
a compose stack. Same container either way; don't run both.

### 5. Fill in the fields

Required / usually touched:

| Field | Set it to |
|---|---|
| Projects folder | One mapping for all of them: `/mnt/user/projects` → `/workspace`. Every folder inside it is a project |
| State paths | Pre-wired to `/mnt/user/appdata/BuilderBot/{home,config}` |
| **Secrets directory** | The folder from step 3 (or leave empty if unshielded) |

Everything else has sane defaults: full reference in [reference.md](reference.md#configuration-reference).

### 6. Optional features

| Want | Do |
|---|---|
| Android emulator, builds, CI | Enroll a node from the dashboard's Nodes page. This container compiles nothing and renders nothing: the toolchains, the card and `/dev/kvm` are that machine's |
| Web dashboard | Always on (it is the controller). Map port 7680 and open it: the first page is the setup, see step 7 and [the dashboard](dashboard.md) |
| Logs on the array | Set the **Logs directory** path field (template) / uncomment the `/logs` volume (compose) |
| Static analysis reports | Point the **Scanner reports** path at your scanner's output dir: read-only; see [Static analysis reports](building.md#static-analysis-reports) |
| Docker builds (CI jobs, a project's containers) | On a node, never in this container: a node's own Docker, or the Docker sandbox VM ([sandbox-vm.md](sandbox-vm.md)). The template has no Docker socket field |
| Extra tools | the Toolchains page, per node; the controller carries what it needs in the image |

### 7. First boot

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
asked; their defaults are under Controller settings.

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

### 8. Daily use and updating

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

**The apps for your machines**: the Android app, the VS Code extension and
the Windows companion are on the **Apps** page, under Build, each with
Download and how to connect it, fetched by the controller from its own
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
tick it to force a fresh pull of everything. Rollback = point the Repository field at a
`sha-<commit>` tag; a build older than the `/config` it finds refuses to start, and
[machines.md](machines.md#upgrades-and-config) says what each start does with it.
Compose: `docker compose pull && docker compose up -d`.

## Building locally instead of pulling

```bash
git clone https://github.com/aquilaelabs/BuilderBot.git && cd BuilderBot
cp .env.example .env && nano .env
docker compose build && docker compose up -d
```
