# BuilderBot

One container that is a **Claude Code workstation**, a **self-hosted GitHub
Actions runner**, a **Playwright browser lab** and an **Android build/emulator
box** — built to live on an Unraid server with your projects mounted straight
in.

```
  ┌─────────────────────── builderbot ────────────────────────┐
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

The container starts, runs its install/setup scripts, registers the runner, and
then stays up. You `docker exec` into it to use Claude Code; GitHub sends CI
jobs to the same box.

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
| **Docker** | CLI + compose/buildx plugins (talks to the host daemon via the mounted socket) |
| **Search** | ripgrep, fd, fzf, jq |
| **Build** | build-essential, cmake, pkg-config |
| **Media** | ffmpeg, imagemagick (MediaReducer needs these) |
| **Runner** | latest `actions/runner`, ephemeral by default |
| **Versioning** | `mise` for per-project tool pinning (gradle, go, rust, any node/python — on demand) |

Trim it down with build args if you don't want the heavy toolchains:
`--build-arg INSTALL_PLAYWRIGHT=false`, `INSTALL_ANDROID=false`,
`INSTALL_ANDROID_EMULATOR=false`.

## Quick start on Unraid

Full walkthrough: **[docs/unraid.md](docs/unraid.md)**. Two install options:

**Docker template (recommended)** — [`unraid/builderbot.xml`](unraid/builderbot.xml)
drops into `/boot/config/plugins/dockerMan/templates-user/`, giving you a
native Unraid container with a form-based settings page. CI auto-publishes
`ghcr.io/stencil-projects/builderbot:latest` on every push to `main`, so the
Docker tab's *Check for Updates* lights up **update ready** and updating is
one click. (One-time: `docker login ghcr.io` on the host, persisted via the
`go` file — the package is private.)

**Compose Manager** — the `docker-compose.yml` in this repo, updated with
`docker compose pull && docker compose up -d`.

Then start working:

```bash
docker exec -it BuilderBot claude       # opens in /workspace
```

## Configuration

Everything is environment variables — see [`.env.example`](.env.example) for the
annotated list. The ones that matter:

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | Unraid's `nobody:users`, so files you create land with the right ownership |
| `TZ` | `America/New_York` | Container timezone |
| `ANTHROPIC_API_KEY` | *(empty)* | API-key billing. Leave blank to log in with a Claude subscription instead |
| `ENABLE_RUNNER` | `true` | Set `false` to run as a pure Claude workstation |
| `GITHUB_URL` | — | `https://github.com/OWNER/REPO` (repo runner) or `https://github.com/ORG` (org runner) |
| `GITHUB_PAT` | — | Mints runner registration tokens and authenticates `gh` |
| `RUNNER_LABELS` | `builderbot,self-hosted,linux,x64` | What `runs-on:` targets |
| `RUNNER_EPHEMERAL` | `true` | Re-register after every job — no state leaks between runs |
| `ENABLE_ANDROID_EMULATOR` | `false` | Create the default AVD at startup (start it with `bb emu start`; needs `--device=/dev/kvm`) |
| `NPM_TOKEN` | — | Auth for `npm publish` |
| `EXTRA_APT_PACKAGES` | — | Space-separated apt packages installed at startup |
| `EXTRA_NPM_PACKAGES` | — | Space-separated global npm packages |
| `EXTRA_PIPX_PACKAGES` | — | Space-separated pipx tools |
| `PROJECT_BOOTSTRAP` | `false` | Run `<project>/.builderbot/setup.sh` on start |
| `CHOWN_PROJECTS` | `false` | Recursively chown mounted projects to `PUID:PGID` |

### Claude Code authentication

Two options, pick one:

* **API key** — set `ANTHROPIC_API_KEY` in `.env`. Nothing else to do.
* **Claude subscription** — leave it blank, then run `docker exec -it builderbot bb login`
  once. Follow the URL it prints, paste the code back. The credentials land in
  `/home/builder`, which is a persistent volume, so this survives restarts and
  image upgrades.

## Startup scripts

The entrypoint runs, in order:

1. **user remap** — `builder` is remapped to `PUID:PGID` before anything writes
   to disk, and added to the group owning `/var/run/docker.sock` if it's mounted.
2. **home seeding** — copies shell config into `/home/builder` without
   clobbering anything already there.
3. **hooks** — every `*.sh` in `scripts/startup.d/`, then every `*.sh` in
   `/config/startup.d/` (your own, from the appdata mount), in filename order:

   | Hook | Does |
   |---|---|
   | `10-system-packages.root.sh` | `EXTRA_APT_PACKAGES` |
   | `20-claude-code.sh` | update Claude Code, `EXTRA_NPM_PACKAGES`, `EXTRA_PIPX_PACKAGES` |
   | `30-git-and-auth.sh` | git identity, `gh auth`, GitHub SSH host keys |
   | `35-publishing.sh` | npm publish auth, `docker login ghcr.io` |
   | `40-projects.sh` | report mounted projects, optional per-project bootstrap |
   | `50-android.sh` | create the default AVD when the emulator is enabled |

4. **supervisor** — starts the Actions runner in the background and keeps the
   container alive as a workstation.

Naming rules for hooks: `*.root.sh` runs as root, anything else runs as
`builder`; `*.disabled.sh` is skipped. To add your own without rebuilding the
image, drop a script into `/mnt/user/appdata/builderbot/config/startup.d/`.

Per-project setup belongs in the project itself — create
`.builderbot/setup.sh` in the repo and set `PROJECT_BOOTSTRAP=true`.

## The `bb` helper

Inside the container:

```
bb status          tool versions, runner registration, mounted projects
bb doctor          check the things that usually go wrong
bb projects        list mounted project dirs and their branches
bb shell           login shell as the builder user
bb update          update Claude Code in place
bb login           run the Claude Code auth flow
bb runner status   show the current runner registration
bb runner restart  re-register the runner
bb emu start       boot the Android emulator, headless
bb emu stop        shut it down
bb emu status      adb devices
```

## Playwright, Android, publishing

* **Playwright**: chromium/firefox/webkit + system deps are pre-installed;
  `npx playwright test` works headless immediately. Browsers live in a shared,
  writable `/opt/pw-browsers`, so projects pinning other Playwright versions
  can `npx playwright install` their own revisions.
* **Android**: JDK 21 + SDK are baked in — `./gradlew assembleRelease` works
  out of the box. The emulator boots headless via `bb emu start`
  (`ENABLE_ANDROID_EMULATOR=true` + `--device=/dev/kvm`); AVDs persist in the
  home volume, and `sdkmanager --install` adds anything else.
* **Publishing**: `npm publish` (via `NPM_TOKEN`), `uv publish` (via
  `UV_PUBLISH_TOKEN`), `docker push` to GHCR (auto-login from `GITHUB_PAT`),
  `gh release create`, and Gradle's `publish`/Play-Store tasks. Details in
  [docs/unraid.md](docs/unraid.md#publishing-packages).

### A note on `docker exec` and users

`docker exec` skips the entrypoint, so it drops you in as **root** — which
would give Claude Code the wrong `HOME` (no saved login) and leave root-owned
files in your shares. `claude` and `bb` are therefore wrappers that re-exec
themselves as `builder`, so these all do the right thing:

```bash
docker exec -it builderbot claude      # runs as builder
docker exec -it builderbot bb shell    # builder login shell
```

A bare `docker exec -it builderbot bash` is still root. Use `bb shell`, or
`docker exec -it -u builder builderbot bash -l`, when you want the normal
user.

## Using it as a GitHub runner

Once registered, target it from a workflow:

```yaml
jobs:
  build:
    runs-on: [self-hosted, builderbot]
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm test
```

The runner is **ephemeral** by default: it takes one job, then deregisters and
re-registers fresh. That means no leftover state between runs, at the cost of a
few seconds of re-registration.

The PAT needs **Administration: read & write** on the repo (fine-grained token),
or `admin:org` for an org-level runner. It is only used to mint short-lived
registration tokens — the runner itself authenticates with those.

> Self-hosted runners should not be used with public repositories: anyone who
> can open a PR could run code on your server. Both of these repos are private,
> which is the supported case.

## Building locally instead of pulling

```bash
git clone https://github.com/Stencil-Projects/BuilderBot.git
cd BuilderBot
cp .env.example .env && nano .env
docker compose build && docker compose up -d
```

Pin the runner version if you need reproducibility:
`docker compose build --build-arg RUNNER_VERSION=2.320.0`.

## Layout

```
Dockerfile                       image definition
docker-compose.yml               the stack you run on Unraid
.env.example                     annotated configuration template
scripts/
  entrypoint.sh                  uid remap, home seeding, hook runner
  supervisor.sh                  PID 1 payload; keeps the box alive
  runner.sh                      register / run / deregister the Actions runner
  healthcheck.sh                 docker healthcheck
  bb                             in-container helper CLI
  as-builder                     privilege-dropping wrapper for docker exec
  lib/common.sh                  shared shell helpers
  startup.d/*.sh                 startup hooks
config/skel/                     home directory skeleton (bashrc etc.)
unraid/builderbot.xml            Unraid Docker template (one-click updates)
docs/unraid.md                   step-by-step Unraid setup
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
