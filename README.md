# BuilderBot

One container that is a **Claude Code workstation**, a **self-hosted GitHub
Actions runner**, a **Playwright browser lab** and an **Android build/emulator
box** — built to live on an Unraid server with your projects mounted straight
in.

```
  ┌─────────────────────── BuilderBot ────────────────────────┐
  │  claude · node 22 · python 3 + uv · jdk 21 · gh · docker  │
  │  playwright (chromium/firefox/webkit)                     │
  │  android sdk + emulator · bundletool                      │
  │  git/git-lfs · ripgrep/fd/fzf/jq · build-essential · mise │
  │                                                           │
  │  actions-runner ──► listens for jobs from GitHub          │
  │                                                           │
  │  /workspace/mediareducer-dev  ◄── /mnt/user/appdata/…     │
  │  /workspace/FreshBoot         ◄── /mnt/user/development/… │
  └───────────────────────────────────────────────────────────┘
```

The container starts, runs its install/setup hooks, registers the runner, and
stays up. You `docker exec` into it to use Claude Code; GitHub sends CI jobs
to the same box. New images publish automatically to GHCR on every push to
`main`, so updating is Unraid's one-click **update ready** flow.

## What's in the image

| | |
|---|---|
| **Claude Code** | `@anthropic-ai/claude-code`, auto-updated on every start |
| **Node** | 22.x (NodeSource) + npm, corepack (yarn/pnpm shims) |
| **Python** | 3.12, `uv`, `pipx`, venv |
| **Java** | OpenJDK 21 |
| **Playwright** | CLI + chromium/firefox/webkit with system deps, shared at `/opt/pw-browsers` |
| **Android** | SDK cmdline-tools/platform-tools/build-tools + platform 35, emulator with Google-APIs x86_64 image, adb, `bundletool` |
| **Git** | git, git-lfs, `gh` CLI |
| **Docker** | CLI + compose/buildx plugins (needs the opt-in socket mount) |
| **Search** | ripgrep, fd, fzf, jq |
| **Build** | build-essential, cmake, pkg-config |
| **Media** | ffmpeg, imagemagick |
| **Runner** | latest `actions/runner`, ephemeral by default |
| **Versioning** | `mise` for per-project tool pinning (gradle, go, rust — on demand) |

Slimmer builds: `--build-arg INSTALL_PLAYWRIGHT=false`, `INSTALL_ANDROID=false`,
`INSTALL_ANDROID_EMULATOR=false`.

---

## Setup, start to finish

The Unraid-specific detail for every step lives in
**[docs/unraid.md](docs/unraid.md)**; this is the complete checklist with the
decisions you need to make.

### 0. Know the three credentials (they are NOT interchangeable)

| Credential | Lives where | Used for |
|---|---|---|
| **GHCR pull token** — classic PAT, `read:packages` scope only | On the Unraid **host** (`docker login`) | Lets the server pull the private image. Fine-grained PATs don't work for GHCR pulls |
| **Runner PAT** — fine-grained PAT, *Administration: R/W* (+ *Contents: R/W* optionally) on the target repos | In the **secrets folder** (recommended) or the `GITHUB_PAT` variable | Mints runner registration tokens. Only needed if `ENABLE_RUNNER=true` |
| **Git SSH key(s)** | `secrets/ssh/` (shielded) or `home/.ssh/` (simple) | `git pull`/`push` in your projects. Deploy keys (one per repo, write-enabled) are the tightest option |

### 1. Authorize the server to pull the image (one-time)

```bash
docker login ghcr.io -u <your-github-username>     # paste the read:packages PAT

# Unraid wipes root's filesystem every boot — persist the login:
cp /root/.docker/config.json /boot/config/ghcr-auth.json
echo 'install -D -m 600 /boot/config/ghcr-auth.json /root/.docker/config.json' >> /boot/config/go
```

The auth file stores the PAT base64-encoded (not encrypted) on flash — which
is why it must be a `read:packages`-only token.

### 2. Create the state directories

```bash
mkdir -p /mnt/user/appdata/BuilderBot/{home,config/startup.d,work}
chown -R 99:100 /mnt/user/appdata/BuilderBot
```

| Dir | Holds |
|---|---|
| `home/` | Claude Code login, npm globals, shell history, AVDs — survives image updates |
| `config/` | your custom startup hooks (`config/startup.d/*.sh`) + persistent logs (`config/logs/`) |
| `work/` | GitHub Actions job checkouts + runner diagnostics |

Keep these on a cache/SSD-backed share — `work/` and `home/` do heavy
small-file IO. (Logs can be relocated to the array; see step 6.)

### 3. Create the secrets folder (recommended)

Root-owned, so its contents are **never readable by Claude sessions**:

```bash
mkdir -p /mnt/user/appdata/BuilderBot/secrets/ssh

cat > /mnt/user/appdata/BuilderBot/secrets/builderbot.env <<'EOF'
GITHUB_PAT=github_pat_xxxxxxxxxxxxxxxx
EOF

cp /path/to/git-key /mnt/user/appdata/BuilderBot/secrets/ssh/id_ed25519

chown -R root:root /mnt/user/appdata/BuilderBot/secrets
chmod -R go-rwx    /mnt/user/appdata/BuilderBot/secrets
```

What this buys you: the PAT is scrubbed from every session's environment
(the runner mints tokens through a root-only sudo helper instead), SSH keys
are served by a root-owned `ssh-agent` (sessions can push with them, never
read them), and all logs are redacted of token patterns *and* the literal
secret values. Details and threat model: [docs/unraid.md — Shielding
secrets](docs/unraid.md#shielding-secrets-pat--ssh-keys-from-claude-sessions).

Skippable if you don't care about shielding: put the PAT in the `GITHUB_PAT`
variable and keys in `home/.ssh/` instead — everything works, Claude can
just see them.

### 4. Install the container

**Docker template (recommended)** — fetch
[`unraid/builderbot.xml`](unraid/builderbot.xml) into
`/boot/config/plugins/dockerMan/templates-user/` (the repo is private, so
fetch with a token), then **Docker → Add Container →** pick *builderbot*.

**Compose Manager** — copy `docker-compose.yml` + `.env.example`→`.env` into
a compose stack. Same container either way; don't run both.

### 5. Fill in the fields

Required / usually touched:

| Field | Set it to |
|---|---|
| Project paths | Pre-wired: `/mnt/user/appdata/mediareducer-dev` and `/mnt/user/development/FreshBoot` → `/workspace/…` |
| State paths | Pre-wired to `/mnt/user/appdata/BuilderBot/{home,config,work}` |
| **Secrets directory** | The folder from step 3 (or leave empty if unshielded) |
| `TZ` | Your timezone |
| `GITHUB_URL` | Repo the runner serves (`https://github.com/OWNER/REPO`) or org (`https://github.com/ORG`) |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | Your commit identity |
| `ANTHROPIC_API_KEY` | Leave **empty** for Claude subscription login (step 7); set only for API-key billing |
| `ENABLE_RUNNER` | `true` unless you want a pure workstation |

Everything else has sane defaults — full reference below.

### 6. Optional features

| Want | Do |
|---|---|
| Android emulator | Extra Params: `--device=/dev/kvm`, set `ENABLE_ANDROID_EMULATOR=true`; then `bb emu start` |
| Logs on the array | Set the **Logs directory** path field (template) / uncomment the `/logs` volume (compose) |
| Docker builds inside (CI jobs, Claude) | Fill the **Docker socket** path field — **off by default; this is root-equivalent on the host**, read the warning in the docs first |
| Emulator adb from your desktop | Map port 5555 |
| Extra tools at startup | `EXTRA_APT_PACKAGES` / `EXTRA_NPM_PACKAGES` / `EXTRA_PIPX_PACKAGES`, or drop hooks in `config/startup.d/` |

### 7. First boot

```bash
docker logs -f BuilderBot          # banner → hooks → runner registered → ready
docker exec -it BuilderBot bb doctor
```

Every `bb doctor` line should be `[ok]` or an expected `[skip]`. It verifies:
Claude on PATH, connectivity to Anthropic/GitHub, git identity, **runner
credential mode** (shielded vs in-environment), and **SSH auth against
GitHub** (agent key vs file key).

If you're on a Claude subscription (no API key):

```bash
docker exec -it BuilderBot bb login    # one time; survives updates
```

Confirm the runner: GitHub → repo → *Settings → Actions → Runners* →
**builderbot** *Idle*. Then use it from a workflow:

```yaml
jobs:
  build:
    runs-on: [self-hosted, builderbot]
```

### 8. Daily use and updating

```bash
docker exec -it BuilderBot claude                          # Claude Code
docker exec -it -w /workspace/FreshBoot BuilderBot claude  # in a project
docker exec -it BuilderBot bb shell                        # shell as builder
```

**Updating**: CI publishes `:latest` on every push to `main` + a weekly
freshness rebuild. Unraid's *Check for Updates* flips the container to
**update ready** — click it. Rollback = point the Repository field at a
`sha-<commit>` tag. Compose: `docker compose pull && docker compose up -d`.

---

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | File ownership (Unraid `nobody:users`) |
| `TZ` | `America/New_York` | Container timezone |
| `ANTHROPIC_API_KEY` | *(empty)* | API-key billing; empty = subscription login via `bb login` |
| `AUTO_UPDATE_CLAUDE` | `true` | Update Claude Code on every start |
| `CLAUDE_CODE_VERSION` | `latest` | Pin the auto-update |
| `ENABLE_RUNNER` | `true` | `false` = pure workstation |
| `GITHUB_URL` | — | Repo or org URL the runner registers with |
| `GITHUB_PAT` | *(empty)* | Runner PAT — prefer the secrets folder; values here are session-visible |
| `RUNNER_NAME` / `RUNNER_LABELS` / `RUNNER_GROUP` | `builderbot` / `builderbot,self-hosted,linux,x64` / — | Runner identity |
| `RUNNER_EPHEMERAL` | `true` | Fresh registration per job |
| `SHIELD_SECRETS` | `true` | Scrub PAT from session env; `false` = legacy (PAT visible, `gh` auto-authenticated) |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | `BuilderBot` / `builderbot@localhost` | Commit identity |
| `ENABLE_ANDROID_EMULATOR` | `false` | Create the default AVD at startup |
| `NPM_TOKEN` | — | `npm publish` auth (lands in `~/.npmrc`, session-visible by necessity) |
| `EXTRA_APT_PACKAGES` / `EXTRA_NPM_PACKAGES` / `EXTRA_PIPX_PACKAGES` | — | Space-separated extras installed each start |
| `PROJECT_BOOTSTRAP` | `false` | Run `<project>/.builderbot/setup.sh` each start |
| `CHOWN_PROJECTS` | `false` | Recursive chown of project mounts to `PUID:PGID` |
| `BB_LOG_DIR` | *(auto)* | Log location override; normally use the `/logs` mount instead |

Mounts: two project dirs, three state dirs (`home`, `config`, `work`), and
three optional ones — `/secrets` (ro, shielded credentials), `/logs`
(relocate logs), `/var/run/docker.sock` (host Docker, off by default).

## Security model, in short

- **Repo mounts** expose only those trees; writes land as `nobody:users`.
- **No Docker socket by default** — with it absent, reaching the host
  requires a kernel exploit.
- **Secrets shielding** — PAT scrubbed from session env + root-only sudo
  helper for runner tokens; SSH keys usable via root-owned agent but not
  readable; logs redacted (patterns + literal values).
- **No passwords, no general sudo** — `root` and `builder` are locked
  accounts; brute-forcing has no target. Builder may sudo exactly one
  command (`mint-runner-token`), which only emits 1-hour tokens.
- **Your root door** is host-side: `docker exec -it -u 0 BuilderBot bash`.
- Don't attach the runner to public repos; treat container-produced commits
  and packages with normal review.

Full discussion: [docs/unraid.md](docs/unraid.md#notes-and-gotchas).

## Startup hooks

The entrypoint runs as root — stash/scrub secrets, remap `builder` to
`PUID:PGID`, seed the home volume (never overwriting), start the ssh-agent —
then executes hooks and drops privileges:

| Hook | Does |
|---|---|
| `10-system-packages.root.sh` | `EXTRA_APT_PACKAGES` |
| `20-claude-code.sh` | Claude Code update, npm/pipx extras |
| `30-git-and-auth.sh` | git identity, GitHub host keys, `gh` auth (unshielded mode only) |
| `35-publishing.sh` | npm publish auth, ghcr docker login (socket + PAT present) |
| `40-projects.sh` | project report, optional per-project bootstrap |
| `50-android.sh` | default AVD when the emulator is enabled |

Your own hooks go in `config/startup.d/` on the share — `*.root.sh` runs as
root, `*.disabled.sh` is skipped, filename order. All hooks are idempotent:
they check state before installing.

## The `bb` helper

```
bb status          tool versions, runner registration, mounted projects
bb doctor          check everything that usually goes wrong
bb projects        mounted project dirs and their branches
bb shell           login shell as the builder user
bb update          update Claude Code in place
bb login           Claude Code subscription auth flow
bb runner status | restart
bb emu start | stop | status
bb logs [-f] [N]   the persistent startup log
```

`claude` and `bb` re-exec as `builder` automatically — `docker exec` lands
as root, which would break your saved login and file ownership. A bare
`docker exec -it BuilderBot bash` is still root; use `bb shell` for the
normal user.

## Playwright, Android, publishing

- **Playwright**: three browsers + deps pre-installed; `npx playwright test`
  works headless immediately. Shared writable `/opt/pw-browsers` lets
  projects pin their own versions.
- **Android**: `./gradlew assembleRelease` works out of the box; emulator
  headless via `bb emu start`; AVDs persist; more platforms via
  `sdkmanager --install`.
- **Publishing**: `npm publish` (`NPM_TOKEN`), `uv publish`
  (`UV_PUBLISH_TOKEN`), `gh release create`, Gradle publish tasks; `docker
  push` to GHCR needs the opt-in socket. Signing keys belong in the home
  volume or CI secrets, never the image.

## Logs

| Log | Where |
|---|---|
| Startup + runner supervisor | `config/logs/builderbot.log` (persists across updates, size-rotated, secret-redacted) — or the `/logs` mount |
| Runner diagnostics | `work/_diag/` |
| CI job output | GitHub → Actions → the run |
| Emulator | `home/.android/emulator.log` |

## Building locally instead of pulling

```bash
git clone https://github.com/Stencil-Projects/BuilderBot.git && cd BuilderBot
cp .env.example .env && nano .env
docker compose build && docker compose up -d
```

## Layout

```
Dockerfile                       image definition
docker-compose.yml               compose variant of the stack
.env.example                     annotated compose configuration
unraid/builderbot.xml            Unraid Docker template (one-click updates)
scripts/
  entrypoint.sh                  secrets shield, uid remap, hooks, ssh-agent
  supervisor.sh                  keeps the box alive; supervises the runner
  runner.sh                      register / run / deregister the runner
  mint-runner-token              root-only token helper (the one sudo command)
  healthcheck.sh                 docker healthcheck
  bb                             in-container helper CLI
  as-builder                     privilege-dropping wrapper for docker exec
  lib/common.sh                  shared shell helpers
  startup.d/*.sh                 startup hooks
config/skel/                     home directory skeleton
docs/unraid.md                   step-by-step Unraid walkthrough
.github/workflows/               GHCR publish + shellcheck/hadolint/compose/xml lint
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
