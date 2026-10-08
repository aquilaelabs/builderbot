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
not a file here: it is typed on the Nodes tab and kept root-only by the
controller. Details and threat model: [docs/unraid.md, Shielding
secrets](unraid.md#shielding-secrets-pat--ssh-keys-from-claude-sessions).

Skippable if you don't care about shielding: put keys in `home/.ssh/`
instead; everything works, Claude can just see them.

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

Everything else has sane defaults: full reference in [the README](../README.md#configuration-reference).

### 6. Optional features

| Want | Do |
|---|---|
| Android emulator, builds, CI | Enroll a node from the dashboard's Nodes tab. This container compiles nothing and renders nothing: the toolchains, the card and `/dev/kvm` are that machine's |
| Web dashboard | Always on (it is the controller. Map port 7680 and open it: the first page asks you to make the owner account) see [Web dashboard](how-it-works.md#web-dashboard) |
| Logs on the array | Set the **Logs directory** path field (template) / uncomment the `/logs` volume (compose) |
| Static analysis reports | Point the **Scanner reports** path at your scanner's output dir: read-only; see [Static analysis reports](how-it-works.md#static-analysis-reports) |
| Docker builds inside (CI jobs, Claude) | Fill the **Docker socket** path field: **off by default; this is root-equivalent on the host**, read the warning in the docs first |
| Extra tools | the Toolchains tab, per node; the controller carries what it needs in the image |

### 7. First boot

```bash
docker logs -f BuilderBot          # banner → hooks → runner registered → ready
docker exec -it BuilderBot bb doctor
```

Every `bb doctor` line should be `[ok]` or an expected `[skip]`. It verifies:
Claude on PATH, connectivity to Anthropic/GitHub, git identity, **runner
credential mode** (shielded vs in-environment), **SSH auth against GitHub**
(agent key vs file key), the **Docker daemon** on the sandbox node: whether
it actually answers, and says it is a sandbox; and, when a GPU is passed through,: whether its **graphics stack** is usable or
only CUDA is.

Each person signs in to Claude on each node they work on, from that node's
row on the Nodes tab: **Sign in** under Claude Code, which a project's
Claude button offers the first time. The flow runs on that node, the
machine Claude Code is installed on, and the code is pasted back on the
row. Each node keeps the login it alone refreshes; the controller holds no
credential, only which Anthropic account each node reported for you.

**CI runs on a node, not in this container.** Enroll one (a token from
the Nodes tab, then `provision-linux.sh` on the machine; `docs/nodes.md`
walks it), open its row on the Nodes tab, add a runner for your git host
and press **Install runner** on it. It registers under the node's own name,
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

A Claude session is opened from the dashboard, on the project's row, and runs
on that project's node. There is no `claude` in this container to exec into.

```bash
docker exec -it BuilderBot bb shell                        # shell as builder
docker exec -it BuilderBot bb status                       # what this box is
```

**Adding a project**: make a folder in the projects share. That is the whole
step: the folder is mounted along with everything else beside it, and it
appears on the dashboard at the next poll. A directory that is not a working
project is not hidden but reported: no git repository or the wrong ownership in
red, no `CLAUDE.md` in amber, both behind **Show projects with errors**. Only
empty directories and hidden ones are left out.

**Updating**: CI publishes `:latest` for any push to `main` that touches the
image's inputs (Dockerfile, `scripts/`, `config/`) + a weekly freshness
rebuild. Unraid's *Check for Updates* flips the container to **update ready**,
so click it. Builds seed their layer cache from the previous `:latest`, so a
scripts-only change is a small pull; the Monday rebuild is uncached on purpose
and is always the big one. *Run workflow* takes a **Rebuild every layer** box
for the same effect on demand: leave it off and a manual run is a cheap retry,
tick it to force a fresh pull of everything. Rollback = point the Repository field at a
`sha-<commit>` tag. Compose: `docker compose pull && docker compose up -d`.

## Building locally instead of pulling

```bash
git clone https://github.com/aquilaelabs/BuilderBot.git && cd BuilderBot
cp .env.example .env && nano .env
docker compose build && docker compose up -d
```
