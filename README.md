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
  │  /workspace/MediaReducer-Dev    ◄── /mnt/user/development │
  │  /workspace/MediaReducer-Stage  ◄── /mnt/user/development │
  │  /workspace/FreshBoot           ◄── /mnt/user/development │
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
| **Runner PAT** — fine-grained, owned by the org. Repo runner: *Administration R/W*. Org runner: *Self-hosted runners R/W*. Nothing else | In the **secrets folder** (recommended) or the `GITHUB_PAT` variable | Mints runner registration tokens — that is its only job. Skip if `ENABLE_RUNNER=false` |
| **Git SSH key(s)** | `secrets/ssh/` (shielded) or `home/.ssh/` (simple) | `git clone/pull/push` in your projects. Shielded keys are usable but unreadable |
| **`GIT_PAT`** — fine-grained, *Contents R/W* (+ *Pull requests R/W*) | `GIT_PAT` variable — session-readable by design | Only for **GitHub API** calls from inside (`gh pr create`, `gh release create`). Not needed if ssh covers your git usage |

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

**Docker template (recommended)** — get
[`unraid/builderbot.xml`](unraid/builderbot.xml) into
`/boot/config/plugins/dockerMan/templates-user/`, then **Docker → Add
Container →** pick *builderbot*. The repo is private, so the raw URL 404s
without auth — easiest is to save the file from your browser and drop it on
the `flash` SMB share; [docs/unraid.md](docs/unraid.md#install) also has an
API-based `curl` (which needs a *contents*-read token, not the
`read:packages` one).

**Compose Manager** — copy `docker-compose.yml` + `.env.example`→`.env` into
a compose stack. Same container either way; don't run both.

### 5. Fill in the fields

Required / usually touched:

| Field | Set it to |
|---|---|
| Project paths | Pre-wired: `MediaReducer-Dev`, `MediaReducer-Stage` and `FreshBoot` under `/mnt/user/development` → `/workspace/…` |
| State paths | Pre-wired to `/mnt/user/appdata/BuilderBot/{home,config,work}` |
| **Secrets directory** | The folder from step 3 (or leave empty if unshielded) |
| `TZ` | Your timezone |
| `GITHUB_URL` | Repo the runner serves (`https://github.com/OWNER/REPO`) or org (`https://github.com/ORG`) |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | Your commit identity |
| `ANTHROPIC_API_KEY` | Leave **empty** for Claude subscription login (step 7); set only for API-key billing |
| `ENABLE_RUNNER` | `true` unless you want a pure workstation |

**The template's Extra Params default to `--hostname=builderbot --device=/dev/kvm
--runtime=nvidia`**, matching the server it was written for. Both device flags
make Docker refuse to start the container on hardware that lacks them, with an
error that does not obviously point back here — so drop whichever does not apply
before your first Apply.

Everything else has sane defaults — full reference below.

### 6. Optional features

| Want | Do |
|---|---|
| Android emulator | On by default; needs `--device=/dev/kvm` (pre-set in the template). Then `bb emu start` |
| Web dashboard | Set `ENABLE_DASHBOARD=true` **and** `DASHBOARD_AUTH=user:pass`, map ports 8080/7681 — see [Web dashboard](#web-dashboard) |
| NVIDIA GPU | `--runtime=nvidia` is pre-set; add the Nvidia-Driver plugin and keep `NVIDIA_DRIVER_CAPABILITIES=all` — see [GPU](#nvidia-gpu) |
| Logs on the array | Set the **Logs directory** path field (template) / uncomment the `/logs` volume (compose) |
| Static analysis reports | Point the **Scanner reports** path at your scanner's output dir — read-only; see [Static analysis reports](#static-analysis-reports) |
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
credential mode** (shielded vs in-environment), **SSH auth against GitHub**
(agent key vs file key), and — when a GPU is passed through — whether its
**graphics stack** is usable or only CUDA is.

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

**Every label in `runs-on` must be one the runner carries.** A job asking for a
label BuilderBot does not have sits in *Waiting for a runner* forever while the
runner shows *Idle* — the job is simply not addressed to it, and neither screen
mentions the other. If a job queues and never starts, compare its
`Requested labels:` line against the labels beside the runner in
*Settings → Actions → Runners*, and either fix the workflow or add the label to
`RUNNER_LABELS`. Stale **Offline** runners carrying the label a job wants are
worth deleting for the same reason — they make a job look routable when nothing
is going to pick it up.

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
| `RUNNER_NAME` / `RUNNER_LABELS` / `RUNNER_GROUP` | `builderbot` / `builderbot,self-hosted,linux,x64,unraid` / — | Runner identity |
| `RUNNER_EPHEMERAL` | `true` | Fresh registration per job |
| `RUNNER_RESTART_DELAY` / `RUNNER_SHUTDOWN_TIMEOUT` | `5` / `120` | Seconds between re-registrations, and how long a stop waits for a job to finish |
| `SHIELD_SECRETS` | `true` | Scrub PAT from session env; `false` = legacy (PAT visible, `gh` auto-authenticated) |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | `BuilderBot` / `builderbot@localhost` | Commit identity |
| `GIT_PAT` | *(empty)* | GitHub **API** auth for `gh` from inside (`gh pr create`). Session-readable by design; not needed if ssh covers your git usage |
| `ENABLE_ANDROID_EMULATOR` | `false` | Create system images and AVDs at startup |
| `ANDROID_SYSTEM_IMAGES` | `35` | API levels to keep an image + AVD for, e.g. `34,35,36,37` |
| `ANDROID_SYSTEM_IMAGE_VARIANT` | `google_apis;x86_64` | Image flavour; `default;x86_64` is smaller AOSP, no Google APIs |
| `ANDROID_AVD_NAME` / `ANDROID_AVD_PREFIX` | *(derived)* / `builderbot` | Override the default AVD, or the `<prefix>-<api>` naming |
| `ANDROID_EMULATOR_GPU` | `swiftshader_indirect` | Emulator renderer — `swangle_indirect` (faster software) or `host` (needs a GPU) |
| `NVIDIA_VISIBLE_DEVICES` | `all` | Only with `--runtime=nvidia`; GPU UUID when you have more than one card |
| `NVIDIA_DRIVER_CAPABILITIES` | `all` | Only with `--runtime=nvidia`; `all` is what gets you GL/EGL/Vulkan, not just CUDA |
| `NPM_TOKEN` | — | `npm publish` auth (lands in `~/.npmrc`, session-visible by necessity) |
| `EXTRA_APT_PACKAGES` / `EXTRA_NPM_PACKAGES` / `EXTRA_PIPX_PACKAGES` | — | Space-separated extras installed each start |
| `PROJECT_BOOTSTRAP` | `false` | Run `<project>/.builderbot/setup.sh` each start |
| `CHOWN_PROJECTS` | `false` | Recursive chown of project mounts to `PUID:PGID` |
| `CHOWN_HOME` | `true` | Recursive chown of the home volume at startup. Set `false` if it is large and already correct |
| `BB_LOG_DIR` | *(auto)* | Log location override; normally use the `/logs` mount instead |
| `ENABLE_DASHBOARD` | `false` | Web dashboard + browser terminal |
| `DASHBOARD_AUTH` | *(empty)* | `user:password` — **required** when the dashboard is enabled; it will not start otherwise |
| `DASHBOARD_PORT` / `DASHBOARD_TTYD_PORT` | `8080` / `7681` | Page and terminal ports; both must be published |
| `BB_LOG_KEEP` | `5` | How many previous boots' logs to keep — the log rotates on every start |

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
bb emu start [api] | stop | status | list
bb claude-md       is this project's CLAUDE.md environment block current?
bb claude-md --update   refresh that block only
bb claude-md --init     create one here from the template
bb findings        this project's scanner findings (--all for every project)
bb logs [-f] [N]   this boot's log
bb logs -p [N]     a previous boot's log
bb logs --list     the kept boot logs, newest first
```

`claude` and `bb` re-exec as `builder` automatically — `docker exec` lands
as root, which would break your saved login and file ownership. A bare
`docker exec -it BuilderBot bash` is still root; use `bb shell` for the
normal user.

## NVIDIA GPU

Pass the card through with `--runtime=nvidia` (Extra Params) or the `deploy:`
block in the compose file. It needs the NVIDIA Container Toolkit on the host —
on Unraid that's the **Nvidia-Driver** plugin, which also lists your GPU UUIDs
for `NVIDIA_VISIBLE_DEVICES`. Step-by-step:
[docs/unraid.md](docs/unraid.md#nvidia-gpu-optional).

**Keep `NVIDIA_DRIVER_CAPABILITIES=all`.** The runtime defaults to
`compute,utility`, which injects CUDA but none of the GL/EGL/Vulkan drivers.
That failure mode is nasty because `nvidia-smi` reports a perfectly healthy GPU
while every attempt at hardware rendering falls back or fails outright.
`bb doctor` distinguishes the two: it checks for the EGL vendor ICD, not just
the device.

What actually gets faster, in rough order of payoff:

| Workload | Notes |
|---|---|
| `ffmpeg` transcodes | The big one. Check `ffmpeg -encoders \| grep nvenc`, then use `h264_nvenc`/`hevc_nvenc` |
| CUDA / ML | Works with capabilities left at the default |
| Android emulator | Set `ANDROID_EMULATOR_GPU=host`. Least reliable of the three — the emulator is picky about host rendering with no display attached, so verify rather than assume |
| Playwright | Headless runs are rarely GPU-bound; usually not worth it |

For the emulator specifically, `swangle_indirect` is worth trying before
`host` — it's still software, needs no GPU, and is usually faster than the
`swiftshader_indirect` default. And if the goal is verifying animation timing
rather than watching it, `dumpsys gfxinfo <pkg> framestats` gives real
per-frame timestamps under any renderer; `screenrecord` caps out around 10fps
in software and will mislead you.

## Multiple Android versions

The image ships one system image (API 35). To emulate more, list the API levels
you want:

```
ANDROID_SYSTEM_IMAGES=34,35,36,37
```

On the next start each missing level is downloaded and given an AVD named
`builderbot-<api>`:

```bash
bb emu list          # configured levels, and which AVDs exist
bb emu start 37      # boot Android 17
bb emu start         # the first configured level
bb emu stop
```

As of 2026 the supported range is **34–37** (Android 14 through 17). API 33 and
below stopped receiving security patches in March 2026.

**Where the space goes.** System images and platforms are symlinked onto the
home volume, so each level is downloaded **once** and survives image updates —
without that, a weekly `:latest` rebuild would re-fetch every one of them. The
cost lands on your appdata share instead of the image: budget roughly **2 GB per
API level**. If that is tight, `ANDROID_SYSTEM_IMAGE_VARIANT=default;x86_64`
gets you smaller AOSP images at the price of the Google APIs.

Two practical limits: an Android 17 phone AVD wants **4 GB of RAM minimum**, and
`bb emu` runs one emulator at a time — this is for testing across versions in
sequence, not a device farm.

## Static analysis reports

If you run a scanner on the host, mount only its **output** — read-only:

```
/mnt/user/appdata/scanners/reports:/reports:ro
```

That boundary is the point. The scanner binaries stay outside, so nothing in
this container can run a scan, change the rules, or edit what was reported. It
reads findings; it does not produce them. If a report looks stale, re-run the
scanner on the host — there is deliberately no way to do it from in here.

```bash
bb findings              # this project's findings
bb findings --all        # every project the report covers
bb findings x.sarif      # one file rather than all of /reports
```

A scanner pointed at a directory of repos writes one report covering all of
them, so `bb findings` filters to the project you run it from and says how many
it held back. Reports must be **SARIF** — several scanners default to their own
JSON and need asking (`--format sarif` for Trivy, `--sarif` for Semgrep);
anything that is not SARIF is skipped silently, which looks identical to a
scanner that found nothing.

For the same reason, a project missing from a report has not necessarily
passed: SARIF carries findings, not coverage. If you need to know a tree was
actually walked, keep the scanner's own stdout — `semgrep` and `trivy` both
print file counts that the report itself does not preserve.

Raw SARIF is mostly metadata — a few hundred KB of it fills a session's context
before it reaches the code the findings are about. `bb findings` groups by
severity and rule, prints each message once with the locations under it, and
rewrites the scanner's paths to be repo-relative so they can be opened
directly. Run it from the project directory; the current directory name is what
gets stripped from the recorded paths (override with `FINDINGS_PROJECT`).

**Review the diffs.** Findings need judgement about intent — whether a `|safe`
is deliberate, whether a SHA1 is for dedup rather than security. Asking Claude
to fix everything and re-scan unattended optimises for a clean report, which is
not the same as better code, and suppressing a finding satisfies that goal too.

## Web dashboard

Off by default. When enabled it serves a status page on `8080` and a browser
terminal on `7681`:

- container uptime, runner registration and listening state
- every project under `/workspace` with its branch, and one-click **Claude**,
  **Shell** and **Findings** per project
- `bb` macros as buttons — doctor, status, logs, emulator control, update
- live list of tmux sessions, with attach

Every terminal runs inside **tmux**, so closing the tab detaches instead of
killing the session — a Claude conversation survives a dropped connection or a
closed laptop, and clicking the same project again reattaches to it rather than
starting a second one.

```
ENABLE_DASHBOARD=true
DASHBOARD_AUTH=you:a-real-password
```

**`DASHBOARD_AUTH` is mandatory and the dashboard refuses to start without
it.** What it publishes is a writable shell inside a container holding a loaded
ssh-agent and read-write mounts of every project — so that credential is worth
as much as the ssh keys are. It is not a convenience toggle; treat it like the
Docker socket mount.

Both ports must be reachable from your browser. If you remap the **host** side
of the terminal port, set `DASHBOARD_TTYD_PUBLIC_PORT` to that host port —
the page has to tell the browser where to connect and cannot see Docker's port
mappings from inside. The failure is quiet: the page loads and only the
terminal fails. The terminal is a separate
service on its own port rather than proxied through the page, because relaying
a PTY websocket by hand is the kind of code that works until it deadlocks.

The dashboard's own API only runs commands from a fixed list — it takes a macro
name, never a command string. Anything not on that list belongs in the
terminal, which is one port away and honest about being a shell.

## Telling a project's sessions about this environment

A Claude session started in `/workspace/<project>` sees the project, not the
container around it — so it does not know that `apt-get install` will not
survive an update, that there is no display, or that ssh keys are deliberately
unreadable. The image ships a template that explains all of it:

```bash
bb claude-md --init      # from the project directory
```

Then fill in the project section at the bottom. Claude Code picks `CLAUDE.md`
up from the project root automatically.

**Keeping it current.** The environment half of that file goes stale every time
the container gains a feature, while the project half is the expensive part
nobody wants to risk. So the template wraps its own content in
`BUILDERBOT:ENV:BEGIN` / `END` markers, and refreshing is a substitution rather
than a merge:

```bash
bb claude-md             # does this copy differ from the image's template?
bb claude-md --update    # replace just that block
```

Everything below the end marker is never read, compared or written. A file
without markers is refused rather than guessed at — merge those once by hand,
and every refresh after that is mechanical.

The template also tells sessions to run the check at the start of a session and
refresh if it reports drift, so a project's environment notes keep up with the
container without you remembering to do it. It asks the session to say when it
updates rather than doing it silently, because a modified tracked file that
nobody mentioned is the kind of thing that gets swept into an unrelated commit.

## Playwright, Android, publishing

- **Playwright**: three browsers + deps pre-installed; `npx playwright test`
  works headless immediately. Shared writable `/opt/pw-browsers` lets
  projects pin their own versions.
- **Android**: `./gradlew assembleRelease` works out of the box; emulator
  headless via `bb emu start`. See [Multiple Android versions](#multiple-android-versions)
  to emulate more than one API level.
- **Publishing**: `npm publish` (`NPM_TOKEN`), `uv publish`
  (`UV_PUBLISH_TOKEN`), `gh release create`, Gradle publish tasks; `docker
  push` to GHCR needs the opt-in socket. Signing keys belong in the home
  volume or CI secrets, never the image.

## Logs

| Log | Where |
|---|---|
| Startup + runner supervisor | `config/logs/builderbot.log` — one file per container start, `.1` … `.5` are previous boots. Persists across updates, secret-redacted. Or the `/logs` mount |
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
config/templates/                project CLAUDE.md template (shipped in the image)
  scripts/dashboard/               web dashboard: server.py, index.html, bb-tty
docs/unraid.md                   step-by-step Unraid walkthrough
.github/workflows/               GHCR publish + shellcheck/hadolint/compose/xml lint
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
