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
  │  /workspace  ◄────────────────── /mnt/user/development    │
  │    every folder in there is a project                     │
  └───────────────────────────────────────────────────────────┘
```

The container starts, runs its install/setup hooks, registers the runner, and
stays up. You `docker exec` into it to use Claude Code; GitHub sends CI jobs
to the same box. New images publish automatically to GHCR whenever a push to
`main` changes what the image is built from (plus a weekly refresh), so
updating is Unraid's one-click **update ready** flow.

## What it looks like

The [dashboard](#web-dashboard): projects, sessions, findings and the runner
on one side, real terminals on the other — the same page on a phone, where
the two sides become a switch.

![The dashboard on a desktop](docs/screenshots/dashboard.png)

<p>
  <img src="docs/screenshots/phone-dashboard.png" width="290"
       alt="The dashboard side on a phone">
  &nbsp;
  <img src="docs/screenshots/phone-terminal.png" width="290"
       alt="The terminal side on a phone, with the tab strip and bottom bar">
</p>

(Staged data. The pictures regenerate with `bash tools/readme-shots.sh`,
which boots the checkout's dashboard against an invented workspace on a
private tmux server and photographs it with `bb shot` — the pattern the
[`bb` helper section](#the-bb-helper) preaches, practiced.)

## What's in the image

| | |
|---|---|
| **Claude Code** | `@anthropic-ai/claude-code`, auto-updated on every start |
| **Node** | 22.x (NodeSource) + npm, corepack (yarn/pnpm shims) |
| **Python** | 3.12, `uv`, `pipx`, venv |
| **Java** | OpenJDK 21 |
| **Playwright** | CLI + the system deps; the browsers themselves install to the [SDK share](#sdks-live-outside-the-image) and appear at `/opt/pw-browsers` |
| **Android** | SDK cmdline-tools (`sdkmanager`), platform-tools (`adb`), `bundletool`. Platforms, build-tools, the emulator and system images install to the [SDK share](#sdks-live-outside-the-image), not the image |
| **Git** | git, git-lfs, `gh` CLI |
| **Docker** | CLI + compose/buildx plugins (needs the opt-in socket mount) |
| **Search** | ripgrep, fd, fzf, jq, yq |
| **Build** | build-essential, cmake, pkg-config |
| **Lint** | shellcheck, hadolint, actionlint, ruff — `bb lint` runs the right ones over a repo |
| **Media** | ffmpeg, imagemagick |
| **Runner** | latest `actions/runner`, ephemeral by default |
| **Versioning** | `mise` for per-project tool pinning (gradle, go, rust — on demand) |

Slimmer builds: `--build-arg INSTALL_PLAYWRIGHT=false`, `INSTALL_ANDROID=false`.
The heavyweight toolchains — Flutter, .NET, Swift, extra Android packages —
are never in the image at all; `bb sdk install` puts them on a share that an
update cannot touch. See [SDKs live outside the image](#sdks-live-outside-the-image).

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
| Projects folder | One mapping for all of them: `/mnt/user/development` → `/workspace`. Every folder inside it is a project |
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
| Web dashboard | Set `ENABLE_DASHBOARD=true` **and** `DASHBOARD_AUTH=user:pass`, map port 8080 — see [Web dashboard](#web-dashboard) |
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

**Adding a project**: make a folder in the projects share. That is the whole
step — the folder is mounted along with everything else beside it, and it
appears on the dashboard at the next poll. A directory that is not a working
project is not hidden but reported: no git repository or the wrong ownership in
red, no `CLAUDE.md` in amber, both behind **Show projects with errors**. Only
empty directories, hidden ones and the runner's `_work` are left out.

**Updating**: CI publishes `:latest` for any push to `main` that touches the
image's inputs (Dockerfile, `scripts/`, `config/`) + a weekly freshness
rebuild. Unraid's *Check for Updates* flips the container to **update ready**
— click it. Builds seed their layer cache from the previous `:latest`, so a
scripts-only change is a small pull; the Monday rebuild is uncached on purpose
and is always the big one. Rollback = point the Repository field at a
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
| `RUNNER_RESTART_DELAY` | `5` | Seconds between re-registrations |
| `SHUTDOWN_GRACE` | `90` | Seconds a stop may spend deregistering the runner, powering down the emulator and ending Claude sessions. Unraid caps this with its own Docker Stop Timeout (default **10**) — raise that if you want the full drain |
| `SHIELD_SECRETS` | `true` | Scrub PAT from session env; `false` = legacy (PAT visible, `gh` auto-authenticated) |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | `BuilderBot` / `builderbot@localhost` | Commit identity |
| `GIT_PAT` | *(empty)* | GitHub **API** auth for `gh` from inside (`gh pr create`). Session-readable by design; not needed if ssh covers your git usage |
| `SDK_ROOT` | `/sdk` | Where the SDKs *you* install are kept — see [SDKs live outside the image](#sdks-live-outside-the-image). Falls back to the home volume when no share is mapped. Not CI's: the runner keeps its own toolchains under `RUNNER_WORKDIR` |
| `RUNNER_WORKDIR` | `/workspace/_work` | Everything the runner owns: job checkouts, the `_tool` cache `actions/setup-*` fills, cached actions, and `_diag` logs. Mapped to `appdata/BuilderBot/work` by the template |
| `ENABLE_ANDROID_EMULATOR` | `false` | Create system images and AVDs at startup |
| `ANDROID_SYSTEM_IMAGES` | `36` | API levels to keep an image + AVD for, e.g. `34,35,36,37` |
| `ANDROID_SYSTEM_IMAGE_VARIANT` | `google_apis;x86_64` | Image flavor; `default;x86_64` is smaller AOSP, no Google APIs |
| `ANDROID_AVD_NAME` / `ANDROID_AVD_PREFIX` | *(derived)* / `builderbot` | Override the default AVD, or the `<prefix>-<api>` naming |
| `ENABLE_GPU_DISPLAY` | `true` | Start a headless X server for a passed-through NVIDIA GPU at boot, so the emulator can render on it. Does nothing without one |
| `ANDROID_EMULATOR_GPU` | *(empty — auto)* | Emulator renderer. Empty tests the GPU and falls back to software; `swiftshader_indirect`/`swangle_indirect` force software, `host` insists on the GPU |
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
| `DASHBOARD_PORT` | `8080` | The one published port: page, API and terminals (proxied under `/term`) |
| `DASHBOARD_TTYD_PORT` | `7681` | ttyd's loopback bind inside the container; never published |
| `DASHBOARD_DOCTOR_INTERVAL` | `1800` | Seconds between the dashboard's background `bb doctor` runs (min 300) |
| `BB_LOG_KEEP` | `5` | How many previous boots' logs to keep — the log rotates on every start |
| `BB_SESSION_HISTORY` | `2000` | Lines of each terminal's screen saved at shutdown and printed back when it is restored |

Mounts: the projects folder, three state dirs (`home`, `config`, `work`), and
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

Bare `bb` prints this list; `bb status` is the tool-version wall.

```
bb status          tool versions, runner registration, mounted projects
bb version         this project's version, and who is allowed to move it
bb version --code  one form only: --code (Android versionCode), --quad (= --win:
                   manifest.json and Windows VERSIONINFO), --msi, --pep440,
                   --file, --semver, --json
bb version bump major|minor|patch    move the target, if the policy allows it
bb version init X.Y.Z  give this project (or --for DIR) its first VERSION
bb version --list  every version this repo carries: its own, and any component
bb version --for DIR   ask about a component — a directory with its own VERSION
bb version policy  what a session may move here, and who decides
bb changelog       this project's user-facing changelog (--for DIR for a component)
bb changelog add "..."   log what a change means for the person using it; the
                   next version bump dates the accumulated lines
bb projects        mounted project dirs and their branches
bb shell           login shell as the builder user
bb update          update Claude Code in place
bb login           Claude Code subscription auth flow
bb runner status | stop | start | restart
bb emu start [api] | stop | status | list | log [-p]
bb claude-md       is this project's CLAUDE.md environment block current?
bb claude-md --update   refresh that block only
bb claude-md --init     create one here from the template
bb lint [path]     lint a repo's infrastructure files: shell scripts,
                   Dockerfiles, workflows, compose files, XML
bb findings        this project's scanner findings (--all for every project)
bb findings history   what the scanner stopped and started saying here
                      (-n N, --since 7d, --find TEXT, as the other logs)
bb roadmap            this project's roadmap
bb roadmap show N     one item in full: its details, its steps and theirs
bb roadmap add "..."  put something on it; `done N` finished, `rm N [why]` not
bb roadmap shelve N   park one without dropping it; `mv N up|down` moves it
bb roadmap add "..." --step "..." --step "..."   an ordered group of steps
bb roadmap edit N "..."               reword one; `step add|edit|rm` for one step
bb roadmap info N [M] "..."           attach the technical details to one, or step M
bb roadmap begin      work one out; `commit` records it as one change, `revert` undoes
bb bug             the bug tracker: open bugs; `all`, `show N` for one in full
bb bug find TEXT   search the reports themselves — area, repro and notes too
bb bug begin       the same notebook batch `bb roadmap begin` opens; `commit`, `revert`
bb bug add "..."   report one (--sev, --area, --repro, ...); `note N`, `fix N`,
                   `wontfix N`, `na N`, `reopen N`, `rm N`, `history`
bb history         one search over the notebook's logs — roadmap, bugs, memory
                   (`--find X`, `--since 7d`, `-n N`)
bb roadmap history [-n N] [--since 7d] [--find TEXT]   what changed, narrowed
bb phone           what phone is connected, and what is waiting on you
bb phone run --why "..." -- adb args...
                   ask to reach it — the operator allows it on the dashboard
                   and the dashboard runs it, so a session never touches the
                   handset itself
bb ci-log          what CI printed on its last run here (`--list` for the runs
                   kept, a run id for one, `--project NAME` from elsewhere)
bb logs [-f] [N]   this boot's log
bb logs -p [N]     a previous boot's log
bb logs --list     the kept boot logs, newest first
bb doctor          check everything that usually goes wrong

# developing BuilderBot itself, from inside it
bb dashboard test  browser-test the dashboard from this checkout, isolated
bb dashboard dev   serve the live dashboard from ./scripts/dashboard (--off reverts)
bb dashboard status  which copy of the dashboard is serving
bb drift           what this checkout changed that the container is not serving
bb shot URL... [FILE|DIR]  headless screenshot(s) of pages
bb favicon SVG [DIR]  favicon set (ico + touch icon) from one mark
bb sdk             SDKs kept outside the image: status, check, install X, update X, remove X
```

The dashboard's Commands card is this same list in this same order.

`bb shot` is the container's camera: one URL with an optional output file
keeps the simple shape, several URLs share one browser and land in a
directory named from their paths (`/` → `index.png`). For README-quality
captures it takes `--full` (whole page, not just the viewport), `--scale 2`
(2x pixels, crisp in GitHub's column), `--wait MS` (pages whose async
fetches settle after networkidle), and `--resize W` (imagemagick downscale,
in place, so full-size originals never land in a repo). `--auth user:pass`
defaults to `DASHBOARD_AUTH`. The intended split for a project's docs
screenshots: the project keeps a script that boots its app into a
photogenic state — staged data, ready-wait — and ends with one `bb shot`
line; the Playwright plumbing lives here, once.

`bb favicon LOGO.svg [DIR]` is the same idea for a web app's icon: the
project supplies its mark as one SVG, and out come `favicon.ico` holding
every small size in one file (the bare `/favicon.ico` request browsers make
cannot ask for a particular one), `apple-touch-icon.png` at 180 for iOS
(`--bg COLOR` flattens it — iOS composites transparency onto black), and
the SVG copied alongside for browsers that prefer vector. Chromium
rasterizes (the image's ImageMagick has no SVG delegate; a browser engine
renders exactly what a tab will show) and ImageMagick packs the `.ico`.
The dashboard's own tab icon is this command's output, from
`scripts/dashboard/static/favicon.svg`.

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

## SDKs live outside the image

The image carries what it takes to *bootstrap* a toolchain, not the toolchain
itself: `sdkmanager`, `adb`, `bundletool` — about 170MB. Everything large and
merely downloadable is installed at runtime into the **SDK share**, mapped at
`/sdk` (Unraid default `/mnt/user/development/SDK`).

The reason is arithmetic. `/opt` is discarded and rebuilt on every image
update, and the update is weekly, so a package baked into the image is
re-downloaded forever: the Android emulator alone is 800MB, a system image
about 2GB. On the share they are downloaded once and the update walks past
them. Map no share and everything falls back to the home volume — which also
persists, but mixes 30GB of system images in with your shell history.

```bash
bb sdk                     # what is installed, where, and how much room is left
bb sdk install flutter     # or: playwright · dotnet · swift · go · rust · zig · android:<pkg>
bb sdk install android:tv         # or wear · playstore · ndk · cmake · emulator
bb sdk install android:"system-images;android-35;google_apis;x86_64"
bb sdk list                # every package the catalog offers
bb sdk images              # the android system images on disk, with sizes
bb sdk images --available  # ...and every one that could be installed
bb sdk flavors             # google_apis · +playstore · tv · wear, and which to pick
bb sdk plan swift          # what installing it would fetch and run, exactly
bb sdk versions            # what is installed, asking nobody
bb sdk check               # ...and whether anything newer exists
bb sdk update flutter      # each the way its own tooling expects
bb sdk remove flutter
bb sdk env                 # the PATH lines; new shells get them automatically
```

**The recipes are a file, not code.**
[`config/packages.json`](config/packages.json) holds everything the container
needs in order to offer, fetch and install a package: the URL, the branch, the
installer's arguments, the environment it wants, how many directory levels to
strip out of the archive, what to run afterwards to prove it worked. Both the
dashboard and `bb sdk` read it, so adding a package is one edit — as long as
it fits one of five shapes:

| kind | what it does |
|---|---|
| `tarball` | resolve a version, fetch the archive, unpack it |
| `script` | fetch a vendor installer and run it with the given arguments |
| `git` | shallow-clone a branch, for a tool that then updates itself |
| `command` | run something already in the image, pointed at the directory |
| `sdkmanager` | an Android package, or an image flavor by kind |

The shapes stay in `bb` because they are genuinely different jobs, and a
table that could express all five would be a programming language. **`bb sdk
plan <package>`** prints what a recipe resolves to — version, URL, the exact
commands — without downloading anything, which is how a catalog edit gets
checked before it is trusted.

**No size is written down anywhere.** A size typed into a file is wrong the
next time upstream ships. A row shows the footprint once the package is
installed — measured, and remembered after it is removed — and before that
what an install would *download*, which is a different number and is labelled
as one: Swift arrives as a gigabyte and unpacks to three.

Upstream is asked for that download figure rather than guessed at, three ways,
all of them catalog entries. Where the catalog's URL is the payload, its
`Content-Length` is the answer. Where it is not, a `download` block names a
dry run to execute and a pattern to match URLs out of — that is how
Playwright's five bundles and the .NET archive get counted. And the Android
packages come from `sdkmanager`'s own repository index, looked up by the exact
package id an install would resolve to: the index's newest Play Store image is
an `android-CANARY` build nobody installs, and the emulator appears twice,
once stable and once on the dev channel.

None of this is a scrape. Every document these resolvers read is one the
vendor's own installer reads — `sdkmanager`'s package index, `rustup`'s
channel manifest, Zig's release index, Go's version file — and the two GitHub
lookups deliberately use the `releases/latest` redirect rather than the API,
which is what rate-limits anonymous callers by IP. Requests carry a
`builderbot-sdk` User-Agent, there are no retries and no parallel fetching,
and a check runs at most a few times a day. What it costs is about 1.8MB,
cached for fifteen minutes in `/tmp` so that the thirteen separate processes
of one check share the four hundred kilobytes of package index that three of
them need.

Rust answers a fourth way: its channel manifest names an archive per
component, and the three a minimal profile installs add up to what `rustup` is
about to fetch. Only Flutter cannot be asked at all — a git clone has no
content length — so it carries the one approximation in the catalog, marked
with a `~` everywhere it appears and replaced by a measurement the moment the
package has been installed here once.

**Nothing installs, updates or removes itself, and no session can do it for
you.** `bb sdk install|update|remove` refuses to run when `CLAUDECODE` is in
the environment — that variable is in everything a Claude session runs, and
the dashboard drops it at startup precisely so that this page is never
mistaken for one — and tells the session to ask instead. It is a guardrail
rather than a boundary (a session has a shell, and could call `sdkmanager`
directly), and it says how the human at the keyboard overrides it:
`env -u CLAUDECODE bb sdk install …`.

**A removal sticks.** Two things are fetched on the first boot of a fresh
share — the Playwright browsers and, with `ENABLE_ANDROID_EMULATOR`, the
emulator — because a container that comes up "ready" with `bb shot` broken is
worse than a slow first start. A share somebody has just cleared looks
identical to a fresh one from a startup hook, so `bb sdk remove` leaves a
marker under `.removed/` on the share and the hooks respect it; installing
the package again clears it. Without that, an uninstall lasted until the next
restart, which is not an uninstall.

In the tab, one button does it: **Install selected** installs what is not
there and updates what is, so there is no second verb to choose between. A
package that is installed and current has a **dead checkbox** — there is
nothing to do to it — and gets its tick back the moment a check finds an
update, with the version it would move to in amber beside the installed one.
Uninstalling is a **bin icon on the row itself**, with a confirmation,
because it is about one package and a bulk Remove button beside a bulk
Install was one mis-click from being expensive.

**A job can be stopped.** **Abort** empties the queue and interrupts the
package being worked on — the whole process group, so the download it is
waiting on goes too — and `bb` removes the half-installed directory on its way
out, the same cleanup a failed install gets. Everything already installed
stays; the abort is for the rest of the queue, not for undoing what worked.

**A row says what it is doing, and not how far along it is.** `installing`
with a ticking ellipsis for the whole of an install, `removing` for a removal.
There was a percentage and a bar here, scraped from whatever each recipe
printed, and it was retired: every one of them meters differently and several
mislead by accident. sdkmanager counts a single fraction across a whole
operation, changes the label part way through, and parks it in the fifties for
the minutes it spends writing a system image. `playwright install` fetches five
bundles and meters each from zero. rustup prints no percentages at all down a
pipe. A row relaying any of that faithfully still read as a bar that had
broken, so the honest answer is the one that does not pretend to a
denominator. The full output of every job goes to the log under the buttons,
which is where to look when "it is working" is not enough.

**Two different questions, two different costs.** What version is installed
is local knowledge — a directory name, or `flutter --version` — so it is on
every row from the moment the tab opens, cached until something is installed.
Whether a newer one exists is a network round trip to a different upstream
per toolchain, so that one is a slow background errand rather than something
the poll does: once a minute or so after the container comes up, and once a
day after that. **Check for updates** asks again on demand, and either way the
answers are what the rows show. A check answers for the rows
that are *not* installed too: the version there is what Install would fetch,
plainly rather than in amber, since nothing about it is news. What a check
found is kept on the state volume and dated on the page — those answers cost
a round trip each and do not go stale quickly, and holding them only in
memory meant a restart wiped every version the tab had been told.

**The size is an estimate until it is a measurement.** Every row carries one:
the catalog's `~3 GB` before installation, which is what the download costs,
and the real `du` figure afterwards, which is not the same number and grows
(a pub cache, a .NET workload, an NDK that unpacks bigger than it ships).
Hover a size to see which one you are reading. Measuring walks the tree, so
it happens on a worker rather than in the request — the first draw after an
install carries the estimate and the real number arrives a moment later.

**Update checking is a question, not a background service.** Each answer costs
a network round trip to a different upstream — the Flutter branch head, the
.NET installer's own dry run, Swift's release redirect, the browser revisions
Playwright's module wants, sdkmanager's update table — so nothing is checked
until `bb sdk check` or the tab's **Check for updates** asks. An unchecked
row says nothing rather than implying it is current. Updates then run through
each toolchain's own mechanism rather than a delete-and-reinstall: Flutter
moves to the branch head, .NET installs the current LTS beside what is there,
sdkmanager updates its packages, and Swift and the browsers fetch the version
they now want.

**Moving the share later is a host-side job.** The container knows one
location — whatever `/sdk` is mapped to — so relocating that directory on the
server and re-pointing the mapping is invisible from inside: stop the
container, move the folder, start it again. There is deliberately no command
for it. (Packages left on the home volume from an older image keep working
where they are: the startup wiring points at whichever location actually
holds them, and says so.)

Android needs no PATH help — `ANDROID_HOME` still points at
`/opt/android-sdk`, whose package directories are symlinks into the share, so
Gradle, Android Studio and `sdkmanager` install and find things exactly where
they always did. The other toolchains land in their own directory under the
share and are put on `PATH` by a generated `env.sh` that every shell sources;
`bb sdk remove` is `rm -rf` of one directory, because nothing was installed
anywhere else.

| Toolchain | Size | What it gets you |
|---|---|---|
| `go` | ~250MB | Windows, macOS, Linux and ARM binaries from here — `GOOS=windows go build`, no target to install |
| `rust` | ~700MB | rustup, cargo and the stable toolchain in one directory |
| `zig` | ~300MB | A C/C++ cross-compiler: `zig cc -target x86_64-windows-gnu` makes this box a Windows toolchain |
| Android packages | 800MB emulator, 3GB NDK | Platforms, build-tools, emulator, NDK, CMake |
| Android system images | 1–2GB each | One per API level per flavor — see [below](#sdks-live-outside-the-image) |
| `playwright` | ~1.3GB | Chromium, Firefox and WebKit — fetched on a fresh share, since `bb shot` and the dashboard's tests need them; removing it stays removed |
| `flutter` | ~1.3GB | Flutter + the bundled Dart SDK; builds Android APKs here |
| `dotnet` | ~4GB | .NET SDK plus the `maui-android` workload |
| `swift` | ~3GB | The Swift toolchain, for shared logic and server-side code |
| `tizen` | manual | Samsung TVs, signage and appliances. No headless installer exists, so `bb sdk install tizen` prints the steps and is not in the dashboard's list — everything there installs |

**From the dashboard.** The sidebar's **Tools** card holds **Additional
packages…**, which opens as a **tab** the way the findings report does: a list of
everything above with a checkbox each, the size it will take, and, once
installed, the path it actually landed on. Tick several and install or remove
them in one go. If one fails, its row says why — the sentence, not the
several hundred lines of progress frames that came with it.

System images sit below in a section of their own, because they are not
packages: a picker for the API level and flavor with the download size on
each option, and the ones already on disk listed under it with what they take
and a bin each. Each one also says **which AVDs are built on it**, which is
what "can this go?" actually means — an AVD names one image exactly and will
not boot without it, and two flavors at the same API level are not
interchangeable. An image no AVD names says so, and is the one that is spare. A tab rather than a dialog because an install runs for
minutes — it can sit on the strip, be pinned to a pane, or be minimized while
you work, and the work itself is a background job on the container, so the
list keeps reporting progress instead of hanging on a request that would take
four minutes to answer. The page only ever posts names the server offered it
— the same rule the command buttons follow.

**Building for Windows, from here.** Three of those cross-compile without a
Windows machine anywhere: Go does it with `GOOS=windows GOARCH=amd64 go
build`, Zig with `zig cc -target x86_64-windows-gnu` (a C and C++
cross-compiler that happens to ship with a language), and .NET with `dotnet
publish -r win-x64 --self-contained`. All three were verified on this box —
`file` says *PE32+ executable, for MS Windows*. Rust needs one more piece: a
linker, either `EXTRA_APT_PACKAGES=gcc-mingw-w64` or `cargo-zigbuild` on top
of Zig. What none of them give you is a Windows *GUI* toolchain — WPF, WinUI
and MSIX packaging need Windows itself.

**Tizen is Samsung's, and where it runs decides whether you care.** TVs,
signage and appliances still run it and Samsung still ships it — that is the
reason to install it. Watches are not: Galaxy Watch moved to Wear OS with the
Watch 4 in 2021, so a watch app is `bb sdk install android:wear`. Phones ended
in 2017. There is no headless installer, so it is a CLI pointer rather than a
row in the dashboard's list, where everything installs.

**Android, and which vendor you are targeting.** One SDK covers all of them:
Samsung, Pixel, Oppo, OnePlus, Xiaomi. There is no per-vendor SDK to install
and no vendor emulator image to download — Samsung's Galaxy skins are
cosmetic, and the vendor libraries (Samsung IAP or Health, Oppo/Xiaomi push)
are Gradle dependencies a project declares, not toolchains a container holds.
What genuinely differs is the *system image* you emulate against — which is
why those are not packages. A package is one thing at one version; a system
image exists at **every API level at once**, so the question is which level
and which flavor, never whether. The four flavors, and why you would pick one:

| Flavor | What it is |
|---|---|
| **Google APIs** | Play *services* — Maps, sign-in, push — but no Play Store app. Rootable: `adb root` works. The default, and what `ANDROID_SYSTEM_IMAGES` installs |
| **Google APIs + Play Store** | The same plus the Play Store app itself, for anything that signs in to Play, checks a license or takes an in-app payment. A Play-certified build, so **not** rootable |
| **Android TV** | Leanback layout, remote-control navigation |
| **Wear OS** | What modern Galaxy and Pixel watches run |

The first two are separate downloads from Google, not one image with a switch
— which is why the Play Store one has to be fetched on its own even when a
plain image for the same API level is already here. The trade is deliberate on
Google's side: an image that ships the Play Store is certified, and a
certified build does not give you root.

Which means the two at one API level are **not** redundant with each other,
even though they cost 2GB each and look almost identical. Take the Play Store
one if something has to talk to Play; take the plain one if you want
`adb root`, a writable system, or the level your existing AVDs were made
against. Rarely both — and the image list says which AVDs are built on each,
so the one that is actually spare is visible rather than guessed at.

The Tools tab offers a level and a flavor and installs it; `bb sdk images
--available` is the same list on the command line, sizes and all. Real Samsung
or Oppo hardware is an `adb connect` away over the network, and Samsung's
Remote Test Lab rents you real devices, but neither is something to install
here.

**iOS is not on this list and cannot be.** Xcode and the iOS SDK are macOS-only
and licensed to Apple hardware; no Linux container can host them. For web and
PWA work the answer is already installed — Playwright's WebKit is Safari's
engine, with iPhone device profiles. For a native iOS build you need a Mac.

**CI's toolchains are not these.** A workflow that runs `actions/setup-node`
downloads its own copy into the runner's tool cache under `RUNNER_WORKDIR`
(`_work/_tool`), versioned by whatever that workflow asked for. The SDK share
is the other thing entirely: what you installed, versioned by when you
installed it. They are kept apart on purpose — a workflow bumping a version
must not move the ground under a Claude session — and `_work` can be emptied
whenever no job is running, at the cost of re-downloading on the next run.

**What stays in the image, and why.** Anything apt installs (the JDK,
ffmpeg, imagemagick, build-essential) integrates with the system and cannot
live on a share. So do the small CLI tools `bb lint` promises — shellcheck,
hadolint, actionlint — and the Android bootstrap, `sdkmanager` and `adb`,
which is what installs everything else. Playwright's *module* and its system
libraries stay; only the browser bundles move. The Actions runner stays too:
it is what this container is for, its version is part of what an image
pins, and CI that had to wait for a 666MB download before its first job
would be a worse trade than the megabytes are worth.

**The first boot after an update is not free.** A container whose share is
empty installs the Android baseline (platform + build-tools, a few hundred MB)
and the Playwright browsers (~1.3GB) on first start, and the emulator the
first time `ENABLE_ANDROID_EMULATOR=true` asks for it. That happens once per
share; from then on updates cost nothing.

## Multiple Android versions

No system image is in the image — the first boot installs the baseline onto
the SDK share. To emulate more levels, list the ones you want:

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
bb emu log -p        # the previous boot's log — the post-mortem after a death
```

As of 2026 the supported range is **34–37** (Android 14 through 17). API 33 and
below stopped receiving security patches in March 2026.

**Where the space goes.** Nothing downloadable lives in the image: platforms,
build-tools, the emulator and the system images are all installed into the
[SDK share](#sdks-live-outside-the-image) and symlinked back into
`/opt/android-sdk`, so each is downloaded **once** and a weekly `:latest`
rebuild re-fetches none of them. Budget roughly **2 GB per API level**. If that
is tight, `ANDROID_SYSTEM_IMAGE_VARIANT=default;x86_64` gets you smaller AOSP
images at the price of the Google APIs.

Two practical limits: an Android 17 phone AVD wants **4 GB of RAM minimum**, and
`bb emu` runs one emulator at a time — this is for testing across versions in
sequence, not a device farm.

**Rendering is software, and it fails in ways that look like your bug.** Under
`swiftshader_indirect` the guest has no DRM render node, so HWUI's default
Vulkan backend cannot start and every frame comes out blank while the app draws
perfectly — the view hierarchy is complete and the pixels are empty, with one
`E/MESA: Failed to open rendernode` in logcat as the only hint. `bb emu start`
sets `debug.hwui.renderer=skiagl` at boot to head that off; a shell `setprop`
does the same but does not survive a reboot, which is what made it look
intermittent. Two related failures are worth knowing: a window can stop
updating part-way through a long session (restart the app — the host log says
`Failed to find EmulatedEglImage`), and the emulator can exit silently under
load, after which `bb emu log -p` is the account of why. The log rotates on
each start rather than being overwritten, so a death survives the restart that
follows it.

**Using the GPU takes an X server, and not just any X server.** `-gpu host`
needs GLES from the host driver, and NVIDIA's EGL will not hand out a display
without an X server carrying its own GLX module — with none, the emulator
finds the card for Vulkan and then fails at `Failed to get EGL display` and
falls back. Xvfb does not fix it and is the obvious wrong turn: it has no
NVIDIA GLX, so EGL falls through to Mesa, which has no driver for an NVIDIA
card and lands on llvmpipe — software by a slower road than the emulator's own
SwiftShader.

So the container starts a real `Xorg` on the injected `nvidia_drv.so` at boot
(`ENABLE_GPU_DISPLAY`, on by default, silent without a GPU). It has to happen
at boot because a session runs unprivileged with no capabilities and cannot
become DRM master. `bb emu start` then **tests** the result rather than
trusting it — EGL has to answer with a vendor driver, and Mesa answering counts
as failure for exactly the reason above — and falls back to software if it does
not. `bb emu gpu` says which you have and why, in one line.

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

**Review the diffs.** Findings need judgment about intent — whether a `|safe`
is deliberate, whether a SHA1 is for dedup rather than security. Asking Claude
to fix everything and re-scan unattended optimizes for a clean report, which is
not the same as better code, and suppressing a finding satisfies that goal too.

## Web dashboard

Off by default. When enabled it serves everything on `8080`: the page, the
API, and the browser terminals, which are proxied under `/term` so one
sign-in covers them all. Signing in is a login page that sets a 30-day
cookie — a real form, so password managers work — not the browser's own
credentials dialog, and there is no second prompt for the terminal port
because there is no second port. The sign-out button beside ↻ and ▤ in the header ends the session (`/logout` does the same). Every sidebar card collapses to its header with a click
on that header, and dragging a header reorders the cards; both are remembered
in `/config/cards.json`, so the phone and the desktop agree about the
arrangement and it survives restarts and image updates. The **▤** button in
the top bar puts it all back: default order — Doctor on top — with every
card expanded. On a touch screen, hold a header for half a second to pick
the card up; a finger that moves sooner is scrolling, and the sidebar scrolls
under it as if the header were not there — a fast flick that happens to land
on a header is never a misfire. The
headers hold nothing but the title and a chevron — every control a card has
lives in its body. The cards:

- **who this container is signed in to Claude as**, under the doctor verdict,
  with the action attached: **Sign out** when it is signed in, **Sign in** when
  it is not. **There is no terminal in it.** `claude auth login` is
  interactive — it prints a URL and waits for the code the browser gives back —
  which looked like a job for a terminal, and got one: a tmux session behind
  ttyd behind a tab. Every part of that was somewhere for it to go wrong. ttyd
  reconnects a dropped socket, so closing the flow started another; a phone
  cannot select a wrapped URL out of a canvas, and a paste into one silently
  does not arrive, so the code reaching the prompt empty read as a *rejected*
  code; and the tab zooms and reflows under a thumb while you are working in
  it. None of that was the sign-in. The sign-in is two lines of text going in
  opposite directions, and a program that wants a terminal only wants a pty —
  so the server holds one. What you see is a link and a text field, and what
  the flow says when it refuses a code is said on the card, in its own words.
  The field passes the code through rather than judging it: the authorize URL
  the code page glues to it is cut off, whitespace and control junk are
  stripped, and whatever remains goes to the flow — whose verdict is the only
  one that counts. The only pastes refused outright are the two that cannot
  be wrong to refuse: one with no code left in it (the link alone), and one
  far too long to be a code.
  Signing out is one command with no conversation in it, so it is a button,
  and it asks first because every session here stops working. **It is dead
  while any Claude session is running** and names the ones in the way; the
  server refuses it too, since a page can be fifteen seconds behind the
  answer. And with the container signed out, **every project's Claude button
  goes dead with it** — as does the terminal URL behind them, which refuses
  with the way in rather than letting a session start and die on Claude's own
  error. On a claude too old to have `auth status` the row simply is not
  there: not knowing is not the same as being signed out, and offering to sign
  somebody out of nothing is worse than offering nothing
- container uptime, **and which build of the image is serving it** — the short
  commit beside the uptime, with the whole one and the time it was built on
  hover. The two are different questions: an Unraid container keeps running
  whatever it last pulled, so "up two hours" says nothing about whether a fix
  merged an hour ago is in there, and inferring one from the other is a good
  way to spend an afternoon debugging a bug that was already fixed. `unstamped`
  means the image was built outside CI. `bb status` prints the same line first,
  and `bb drift` is the other half — what a checkout has changed that the
  running container is not serving. Also runner state — registered, listening, **running a job**
  (with the job's name and how long it has been going), **waiting for GitHub
  to release the last session**, or **failing to connect**. The middle one is
  amber rather than red on purpose: GitHub holds a runner's session for a
  minute or two after the process that had it goes away, so every container
  restart and every finished job on an ephemeral runner spends a moment being
  refused its own name. It clears itself, and a self-clearing state wearing
  the same red as an outage sends you hunting for a fault that is the design
  working. That last one matters: a runner retries a rejected connection
  forever without exiting, so the process being up is not evidence that it is
  reachable. (Progress within a job is as far as it goes: a runner long-polls
  for one job at a time and is never told what else is queued, and how far
  through its own work a job is — tests passed, steps left — is known only to
  the tool inside the step.)
- every project under `/workspace` with its branch, and one-click **Claude**
  and **Shell** per project. Anything with a problem is folded away behind
  **Show projects with errors** — in red, a directory the container user
  cannot read/write/enter (with the `chown` that fixes it) or one holding no
  valid git repository. Only errors are folded away — a **warning stays in the
  list**, in amber, because it is asking for something: a repo with no
  `CLAUDE.md` yet, or one whose environment block has drifted from the image's.
  Both are underlined links that fix themselves — `bb claude-md --init` and
  `bb claude-md --update` on that project. This is what
  makes one mapping for the whole folder workable: a directory that is not a
  project says so instead of quietly not appearing. Hidden directories and the
  runner's `_work` are skipped outright, and empty
  directories are never listed either: a mount point waiting for
  content is not a fault to report.
  A directory holding a **`.bbignore`** file is not a project and is not
  listed — the container writes one into any path of its own that lands in
  the projects share (the SDK share, if you map it under
  `/mnt/user/development`), and you can create one by hand for anything else
  you would rather not see. It *hides*; the eye below **blocks**, which is a
  different promise.
  At the foot of the card, **New project…** creates one. A fresh local repo
  (`git init`) asks for a name and a free-text *About this project*, which
  becomes the project section of a freshly built `CLAUDE.md` (environment
  block from the image's template, your notes below the end marker). A clone
  of a GitHub repository asks for nothing but the URL: it is fetched with the
  container's own access — a deploy key or PAT that can already reach it —
  the directory takes the repository's name, and the `CLAUDE.md` project
  section is drafted from the repo itself (the README's opening paragraph,
  plus build/test commands read off marker files like `package.json`,
  `gradlew`, `Cargo.toml`), marked as a draft for a session to verify. A
  repo that already carries a `CLAUDE.md` keeps its own.
  For a private repo with its own deploy key, a **Deploy key** picker lists
  what the shielded agent holds (public halves only, via `ssh-add -L`) and
  shows the selected key for copying into the repo's GitHub deploy-key page.
  Picking one makes the server handle the container side that used to be
  manual: it writes the `.pub` selector and an `IdentitiesOnly` ssh alias
  (`bb-<key>`, in a namespace of its own so hand-maintained config is never
  touched) and clones through the alias — which the remote then keeps, so
  later pushes offer the right key too. Only the matched agent key's own
  public line is ever written; nothing from the request is. With a PAT
  configured (`GIT_PAT`, or `gh auth login`) the key is optional even for
  private repos — gh answers for plain https remotes.
  A local repo with **no remote at all** wears a chain icon beside its eye:
  **link to GitHub**. It asks the same two questions as a clone — URL and
  deploy key — sets `origin`, and pushes the current branch, but **only into
  an empty repository**: `git ls-remote` must come back with no refs first,
  so linking can never write over existing work. Without a PAT a deploy key
  is required (a push has to authenticate somehow); with one, the key is
  optional and a URL that does not exist yet is created for you via
  `gh repo create` — always private, and only after GitHub itself has
  answered "not found"
  The name is one path segment and the URL must be one of GitHub's two
  address shapes — `git clone` accepts transports a web form should never
  reach, so anything else is refused server-side rather than passed along.
  **A clone and a first push run in the background**, like an SDK install
  does: everything checkable is checked while the dialog is still up (the
  name, the URL, the key, whether the directory is free, whether the repo
  already has a remote), and then the dialog closes and the work carries on
  server-side. The job appears as its own row in this card, saying what it is
  doing — an ellipsis, not a percentage; git's progress is a
  carriage-return animation on stderr and parsing it back into a bar is a
  fight not worth having — with an **Abort** that stops it and removes a
  half-cloned directory. Close the page, sleep the phone, come back later:
  the job belongs to the server, and a reload picks it up mid-flight. If it
  fails, the message stays on the card until you dismiss it rather than
  passing through a toast you may not have been there to see. `git init` is
  the exception and stays synchronous — it is done before a spinner would
  render, and a row that flashes up for one frame is worse than none
- **Tools**: **Additional packages…**, which opens the installer as a tab —
  every toolchain on the [SDK share](#sdks-live-outside-the-image) with its
  size, its installed version, its path, and an amber line when a check finds
  a newer one. Ticks are for things there is something to do to; uninstalling
  is a bin on the row
- a **checklist** per project, carrying how much is still to hand over here —
  the same number the panel shows, refreshed with every poll and again the
  moment you open it. It opens
  the [notebook](#the-notebook) — the one surface here that
  both you and a session write — with what Claude remembers folded away
  beneath it.
  Claude Code keeps memories in `~/.claude/projects/<slug>/memory/`:
  one markdown file per fact, plus a `MEMORY.md` index that is loaded into
  every session started there. Everything else a session is told is
  reviewable — `CLAUDE.md` through a pull request, the transcript on screen —
  but a memory writes itself and is never read back, so a wrong one steers
  every later session invisibly. The fold opens them: each memory folded to
  the summary line Claude wrote for itself (name, type, when), unfolding to
  the whole file in an editor, with **Forget this** to delete one — which
  takes its line out of the index too, since a pointer to a file that is gone
  is worse than no pointer. The index is not shown as a document of its own:
  it is one line per memory, so it is edited as **title** and **hook** fields
  on the memory that line names, and written back whole when you save. That
  is also the difference worth knowing — the index is the only part always in
  context, and the files themselves are read only when recall reaches for
  one. Drift between the index and the files is called
  out in amber both ways: a line naming a file that is not there, and a file
  no line names; saving clears the first and fills in the second.
  **+ write a memory** puts one there by hand — title, file name (slugged
  from the title until you type in it), kind, the one-line hook, and the
  memory itself — written with the frontmatter Claude uses and given its
  index line in the same act, never one without the other. Mostly Claude
  writes these itself; this is for the standing instruction you would
  otherwise repeat once a session and hope stuck.
  It sits on the project row rather than in a Claude tab on
  purpose — *why did it do that?* is usually asked after the tab is closed —
  and it is folded shut, because a handful of files nobody edits does not
  earn the top of a panel. Editing one arms the panel's single **Save**, the
  same button the roadmap uses.
  **Edits land for the next session**, the same rule `bb claude-md` follows:
  the index is read at startup, and a running session is holding what it read
  then — which is what Save tells it, in the one line it spends
- an **eye** per project, which excludes it: persists across restarts and
  blocks Claude sessions for that directory — see below. A row that is excluded
  or has an error carries **no Claude button at all**, because a session cannot
  start there; **Shell** stays, since that is often how you would fix it
- a rendered **findings report** — the SARIF your scanner drops in `/reports`,
  grouped by project and rule, with severity counts and CVEs linked to NVD.
  Project groups start collapsed — the severity pills on each are the overview,
  and what you open stays open across reloads. If the scanner re-runs while
  the report is open, the view reloads itself — the page watches the report
  files' mtime, so you never triage stale findings. The sidebar card carries
  the headline: one row per project with its counts by severity, so "whose
  code, how bad" is answered without opening the report. Both leave out
  projects that are excluded or have repo errors — those get fixed in the
  Projects card first — and the report says how many findings that held back
  rather than quietly shrinking
- a **Stop / Start** toggle for the runner, showing whichever one applies.
  Stopping waits for GitHub to release the runner's session rather than
  reporting success and leaving a listener behind
- every `bb` command as a button, pinnable, typed into the terminal you are
  looking at — and a second card for **your own** command lists. Every such
  button grays out while the tab on screen is a Claude session or a document:
  commands only ever go to a plain shell, never quietly to some other tab
- live list of tmux sessions, named exactly as their tabs are, with the same
  hover text the tabs carry. **Click the name** to go to its tab, reopening
  it first if it was minimized. The button beside it does the other thing:
  **Open** when the tab is minimized; when the tab is on the bar it turns
  green and reads **Minimize** for a shell, or **Close** for a Claude session
  — which asks first, because that ends the conversation. An **attached** pill
  marks the sessions on screen right now, with ◧/◨ saying which pane when
  the view is split.
  Every Claude session — in this list and on its tab — carries a **state dot**:
  blue and pulsing while it works, amber when it is waiting on you (input, a
  permission decision, or a finished turn), with the task it reported
  alongside. That is the phone-glance question answered without opening the
  terminal: is it still going, or does it need me? The state comes from the
  terminal title Claude Code itself maintains, read through tmux — no polling
  of the conversation, no extra process
- a **Doctor** card: `bb doctor`'s checks, run by the server in the background
  every 30 minutes (`DASHBOARD_DOCTOR_INTERVAL` seconds to change that) and
  re-run on demand with its ↻. Its status row wears the verdict as a dot —
  green, amber or red — beside an "all n ok" button that unfolds the detail:
  failures and warnings as full lines, with the fix hint from `bb doctor`'s
  own output in the tooltip, and passing checks collapsed into green chips.
  A verdict getting worse unfolds that detail by itself; healing folds it
  back. Only the detail — collapsing the whole card is your setting, and the
  verdict never overrides it

### Tabs and panes

The page starts with one tab — **workspace**, a shell at `/workspace` — and
everything you open gets its own tab above the terminal. Every tab, the
workspace one included, can be minimized or closed; an empty strip just shows
a placeholder, and **+** starts over.

- **Claude** on a project opens *one* session per project. If it is already
  running the button is green and takes you to its tab. If it is not but the
  project has a previous conversation, you are asked whether to **resume** it
  or start a **new** one — the tmux session dies with a container restart, the
  transcript does not.
- **Shell** opens *another* terminal at the project path every time you click
  it, so you can have several side by side. **+**, at the left of the tab
  strip, does the same for `/workspace`.
- **A Static analysis row** opens that project's notebook on its **Analysis**
  view — a *document* tab, not a terminal. It is a report to read; putting it
  through a PTY would only make it harder to. The whole-report findings tab it
  replaced is gone.
- **— on a tab minimizes it**, and asks nothing. The terminal keeps running
  and is listed under Sessions, where **Open** brings it back; a **Claude** tab
  is the same, the conversation carries on without a tab. Nothing is lost, so
  nothing is asked. **Middle-clicking** a terminal tab is the stronger thing,
  the way it is in a browser: it ends the session — after the same question
  the Sessions ✕ asks — and closes the tab with it.
- **✕ appears on document tabs**, the notebook and Analysis, because a document
  has no session to keep. The notebook asks first if anything in it is unsaved;
  nothing else does.
### The notebook

Every project has one, reachable from the **Notebook** button on its row: a tab
of its own, one per project, and as many open at once as you have projects —
each is its own instance, so what is half-typed in one survives working in
another, and the button lights green while that project's is open. Four views
under its tab strip: **Memory** (what Claude remembers here, moved up from the
fold it used to live in), the **Roadmap** (the shared list, renamed for what it
is — design work and ordered plans), **Bugs**, and **Analysis** (the scanner's
findings for this project alone).

**Unsaved work does not cross those four.** Leaving a view asks, and answering
yes throws the change away rather than carrying it to the next tab.

**The roadmap** is `bb roadmap` in a terminal. Saving does not close it; the
Save buttons simply go dead until there is something to save again, and the
button beside them is **Revert**, which throws away what has not been saved
and is dead whenever there is nothing to throw. It fills the pane rather than
sitting in it, and the pane is the only thing that scrolls. Closing the tab
asks first if anything is unsaved. It is the one surface here that
**both sides write**:
you add "make the picker wrap properly", a session adds "a project can be
created in one click and only deleted from a shell", and either of you can tick
something off.

It exists because nothing else on this box can hold that. `gh` is
unauthenticated here on purpose, so GitHub Issues are unreachable from inside
the container — and until this, something noticed mid-task and left undone
lived in the conversation and died with it.

**Every change to a list is kept.** Both sides write these, and the list
itself only ever shows the present tense — so *was that step always worded
like that?* and *who dropped the third one?* had no answer at all.
**History**, at the top of the view where the other three tabs keep theirs, is
the answer: one line per change, newest
first, each with its date and time and whether you or a session made it. A
reword shows both wordings, the old one struck through. `bb roadmap history`
prints the same log in a terminal.

That log is also what makes deleting safe, because the list now holds nothing
but outstanding work. **A ticked-off item comes off it.** It used to sit
there faded for a week, which is the same mistake crossing a line out was: a
list is read to find out what is left, and a thing that is finished is not
left. `bb roadmap done N` moves it into the log under *done*, where `rm N` would
have put it under *dropped* — both leave, and the log is what says which
happened. Only a session ticks things off; nothing in the dashboard can,
because only the session that did the work knows. **Crossing a line off by hand is gone.** It used to sit
beside the bin and leave exactly the mark that sending leaves, so a list
filled up with things that looked dealt with and were not — and "I crossed
that off" is not the same claim as "that is done". The strike icon is now
only ever an undo: it appears on a line that *has* been sent, to put it back
so it can go again. A line you handled yourself gets dropped, and its words
stay in the log to be retyped if you were wrong.

**Nothing the panel does reaches the list until you press Save.** Type three
steps, reword one, drop another, shuffle the order — it is all held on the
page until then, so a plan can be looked at whole before it is committed to.
Close asks, names how many changes would go, and puts the list back exactly as
it was. The one exception is the send arrow: it types into a live session,
which no Save button can take back, so it flushes whatever is staged first and
then goes.

While a session has a batch open, **the panel's Saves are held** — and only
the Saves. You can still type, edit, drop and revert; what waits is writing
back, because what is on your screen was read before the session started and
saving over a list that has moved underneath is how two writers lose each
other's work. The block is one-way: nothing in the panel ever makes a session
wait. When the batch commits the notebook says so and offers to reload, since
what it is holding is now out of date.

**One batch covers the whole notebook**, not just the roadmap. Bugs filed,
noted or closed while one is open are staged the same way, and `bb bug begin`,
`commit` and `revert` are the same three commands reached from the other tab's
name — `notebook.py` sequences the two halves so that half a batch is a state
the front door cannot reach. A plan usually moves *because* of what the tracker
now says, and committing one while reverting the other would leave a roadmap
describing work against a tracker that never recorded why, with nothing
afterwards able to notice. The memories are outside it: a session writes those
as files with its own tools, so there is no write to intercept and `revert`
will not put one back.

That is deliberately the opposite of the panel's rule, where unsaved work is
per-tab and cannot cross. The two models are answering different questions. In
the panel the thing being edited is on screen and Save is the commit, so each
tab holds its own; for a session the file is the only way anyone can see what
it is doing, so the work lands as it happens and only the *record* waits.

A session gets the same idea in a different shape: `bb roadmap begin`, then work,
then `bb roadmap commit` — the changes land on the list as they are made, because
that is how you can see what a session is doing, but the *record* is written
once at commit. Rewording the same step four times is one history entry rather
than four. `bb roadmap revert` puts the list back and writes nothing, and refuses
if you have touched the list yourself since the batch opened.

**Dropping something asks why.** The bin opens a box under the row with an
optional reason field, and the reason is kept with the entry and is
searchable — because nothing here can be undone, and that note is the only
thing between a dropped line and somebody adding it straight back. The log
can be narrowed rather than read whole: search the lines, their previous
wordings and the reasons things went, over a window of time, capped to a
count. `bb roadmap history --find picker --since 7d` does the same in a
terminal, which is how a session reads it without spending its context on
the whole thing.

**Shelving** is the state between *do this* and *we are not doing this*: the
tray icon parks an item, sinks it to the bottom, dims it and kills its
arrows, and a session is told it is parked rather than left to wonder. It is
the only control here that undoes itself — the same tap brings it back — and
it applies to an item, never to one step of a plan, because the thing you
have decided not to do now is the whole plan. Shelved items do not count
towards the number on the project row. A session can shelve (something turns
out to be blocked, and saying so on the row beats saying it in a reply nobody
re-reads) but cannot unshelve — taking one off reverses a decision it was not
told the reason for.

**A Claude tab does not come back on its own after a restart.** The
conversation ended with the container; the transcript did not, so the
project's Claude button offers to resume it and that stays a decision you
make. Enforcing it takes two halves: the saved layout drops Claude tabs at
boot, and — because a browser left open still holds its own copy, and a phone
waking up reloads the terminal iframe, which spawns whatever its URL names —
each Claude terminal's URL carries the run of the container it was opened in.
One from a previous run is refused where the session would have been created,
with a line saying to open it from the card instead. Shell tabs carry no such
marker and never needed one: a shell is safe to recreate in the same
directory, which is why it survives a restart and a conversation does not.

**A session can correct a plan, not just follow it** — `bb roadmap edit N`,
`bb roadmap step add|edit|rm|mv`, `bb roadmap mv N up|down` — which matters when the design moves under a plan
written a week ago. Every one of those lands in the history under `claude`,
so nothing gets quietly rewritten.

**The list reads top down, and the top is what matters most** — new items go
on the end, and the arrows in Reorder are how something gets promoted. Each
item wears its number: `#4` is the item's own name, not its position, so it is
what `bb roadmap done 4` takes, what a session means when it says "#4", and what
survives the list being rearranged. The prompt a session starts with carries
the same numbers. Steps inside a group number themselves 1, 2, 3 within it.
A gap in the numbers means something was removed; one out of sequence means
it was moved.

**Every line can carry details** — the technical half: which files, which
functions, the approach. They live under a "▸ details" fold on the row (the
words are the decision; this is the workings), travel with a step when it is
sent, and ride in the block a session starts with, so the session that works
the step does not start from a cold grep. Claude writes them with
`bb roadmap info N [M] "..."`, usually when it writes the plan; the pencil edits
them alongside the words.

**A group is one goal with an order to it.** Its title is that goal in plain
words — "make the picker usable on a phone" — and the steps under it carry the
detail. Steps only exist because of one physical constraint: each is a message
*you* send by hand, one at a time, waiting on each. So a step is not a task,
it is a point at which the previous work has to have finished before the next
can start, and a session that splits work into more steps than that costs you
round trips for nothing. A step can be several lines, blank lines and all, so
the cheap unit is the line and the expensive one is the step. The template
CLAUDE.md every project gets says this to sessions in as many words.

**Items are handed to the session one at a time, by the arrow beside them.**
Sending types the line into the running Claude session and submits it — but
only if it can see that it arrived. There is no IPC into a session; the only
door is its terminal, and a session "waiting for input" is either at its prompt
or holding a permission dialog, which the title cannot tell apart. Answering a
permission dialog on your behalf, blind, is the worst thing anything here could
do — so instead of trying to recognise a dialog, it uses the one property every
text box has and no dialog does: **it echoes what you type**. Type the line,
look at the pane, and press Enter only if there is now one more of it on screen
than there was. If it did not appear, the line is left in the input box unsent
and the dashboard says so. With no session running, every arrow is dead.

A sent step is **struck through in place** — not removed, not reordered. Sent
is not done: a step can be handed over and quietly not carried out, and the
struck line is how you notice. It stays sendable, so "that did not take, do it
again" is one tap on the same arrow.

**The order that is protected is the order things are sent in**, and nothing
else. Only the frontier step of a group arms, and the group's own arrow stands
for that same step — so a plan cannot be handed over backwards, which is the
mistake that actually costs something: step three landing on a tree step two
was supposed to have made.

Editing is not constrained the same way, deliberately. The pencil rewords any
row, and the **bin is on every row** — item or step, anywhere in a plan. It
used to be the first step only, on the theory that things come off a plan from
the front; in practice that meant a stale step three cost you steps one and
two to reach, and left the list describing work nobody was going to do. A
deletion cannot send anything out of order. It can only make a plan shorter —
and it now says why it did, in a note kept with the entry in the history.
**The bin always asks; shelving never does**, because one is recoverable by
pressing the same button again and the other is not.

**Edits are written immediately; telling the session is separate.** A phone
that dies half way through tidying a list must not lose it, but every telling
costs a line of somebody's conversation — so the two are apart, and there are
two Save buttons for the difference. **Save** writes any memory edits and
settles the panel without saying anything, which is what you want while a
session is mid-task or when there is none. **Save & tell the session** does
the same and spends the line. Both are dead until something has moved; the
second is also dead with nothing running to tell.

The line **names which half moved** — the roadmap, the memories, or both —
because "something changed" sends somebody to look at both, and one of the two
is a directory of files. There is no way to make a session read something
without sending it a message: no IPC into a running Claude, so the only door
is its input box.

Which is why **sending a step folds the two together**. Tapping an arrow
**arms** it — the arrow lights up and a **send box opens under that row**,
carrying the Send button and the two pickers below; tapping the arrow again
puts it down. Send then does four
things: the line goes, the step is crossed off, the panel closes and you land
in that session's tab. One tap for all four would be a mis-tap you could not
take back, and the highlight is the confirmation — a sentence restating the
line the arrow is sitting next to was not.

The box sits **under the line it would send**, not at the foot of the panel.
It used to be a strip down beside Save, which on a phone put the confirmation
for handing a line over a screen away from the line, with nothing on it saying
which one.

**A note can ride with it.** The box carries a field for anything to send
alongside — "the select is the one on the left" — and it goes on the *same*
line as the step rather than as a second message, for the reason two messages
never work here: the second lands glued to the first. It is cleared once the
step has gone, where the pickers stay: a note belongs to the one thing it was
written for, and finding it still sitting there on the next step is how it
gets sent twice.

**Model and effort** are pickers in that box, both starting at *leave as is*.
A running session's model cannot be changed by a flag it was not started with —
`--model` and `--effort` only apply at startup — so a pick is typed into the
session as its own slash command, `/model sonnet` then `/effort xhigh`, each on
its own line and both ahead of the step, which is what makes the step run on
what was picked. If either line does not submit (something else has the
keyboard in that tab) the step is **not** sent after it, because a step typed
onto the end of an unsent `/model` line is one line that is neither. Worth
knowing before picking: claude saves both as the default for new sessions, so
this is not scoped to the conversation it is typed into — the box says so.

A group's own arrow **stands for its next step**: picking either lights both,
because they are one choice. A crossed-off line cannot be sent at all — put it
back first, so that struck-through means one thing rather than two.

The "I also changed the list" note rides on the *same message* as the step
rather than chasing it — two lines into one input box is how the second ends up
glued to the first. It rides on every send rather than being offered as a
choice: a session about to act on a step is exactly who wants to know the plan
around it moved, and by the time anything can be sent there is nothing unsaved
left to keep quiet about — which is the next rule.

The view opens the way the other three do — its one-line summary on the left
and **History** on the right — with the field, **Add** and **Reorder** together
on the row under it. Those three are the things that change the list; History
only reads it.

**Nothing can be sent while the panel is holding unsaved work.** The arrows go
down, and the line above the list says which change is not on disk and that
Save or Revert will clear it. The reason is what a step *is*: a line typed into
a session, which then goes and reads the list for itself. Send a step off a
list that exists only in this browser and the two are describing different
plans — the session is working from the file, and the file has never heard of
it.

**Unsaved work does not follow you between the four tabs.** Leaving one asks,
and answering yes throws the change away rather than carrying it along. It used
to carry: an edit left on Memory sat in a variable no tab switch touched, so
you could meet it again much later with no memory of making it, and Save from
another tab would write it. The tab close asks the same question for the same
reason.

**An item can be an ordered group of steps.** From a terminal that is
`bb roadmap add "rework the picker" --step "widen the select" --step "then
re-measure it"`; in the panel it is **+ step** under any item, which turns a
plain one into a plan — and the field stays open, so three steps is three lines
of typing rather than three dialogs. A step is **sent with the plan around
it** — "this is step 2 of 3 in a plan", the plan's own line, then the step —
because "then re-measure it" arriving on its own says nothing about what it is
for. Only the next unsent step can be sent; the one after it is dead until the
one before has gone, because three separate items can be handed over backwards
and the second then lands on a tree the first was supposed to have made.

**Reorder** is a mode rather than two more icons on every row — five controls
and a number do not fit a phone, and nobody rearranges a list at the same
moment they are sending from it. The toggle beside the hint swaps each row's
send/strike/bin for up and down: items move among items, steps move within
their group. A step that has gone is pinned and nothing moves above it, so the
crossed ones stay the block every other rule reads them as. The order on
screen is the order in the file — nothing is sorted on the way out, so a list
you arranged stays arranged and a ticked item fades where it is rather than
jumping to the bottom.

**Reordering is the one edit held back until Save.** Everything else here is a
decision — ticked, crossed, dropped — and is written the moment it is made, so
that a phone dying half way through tidying a list loses nothing. Arranging is
not a decision; it is something you are in the middle of. So the moves live in
the page until you save them, leaving the mode puts the order back, and closing
the panel on a half-done shuffle leaves the list alone. Both are asked about
first, since an arrangement is work.

**Every view keeps its history.** The roadmap's log came first; the bug
tracker and the memory view have the same button now, with the same bar —
search, a time window, a cap — and the same rows: what happened, to which
line, by whom, when. The memory log records what the *notebook* changed
(wrote, edited, forgot) — Claude's own memory writes are files, not events,
so they have no entry to make. For a session, `bb history --find X` is one
search across all three logs, merged by time and tagged by source; `bb roadmap
history` and `bb bug history` scope to one.

**Analysis** keeps a log too, and it is the odd one of the four: nothing here
writes a finding. The scan runs on the host, the container reads a report, and
between two runs a finding can simply stop being in it — fixed, or the file
went, or a rule changed upstream. The report cannot tell those apart and
neither does the log; what it says is *it was here on the 3rd and it is not
here now*, which had no answer at all before. So the entries are **derived**:
each read of the report is compared against the last, and the difference is
the entry — `found`, `gone`, or `changed` when the count or level moved.

Two things keep it honest. A finding is identified by **rule and path, not
line**, because line numbers move whenever anything is inserted above them and
a key including the line turns one edit into a gone-and-found pair for
everything below it. And **the first scan of a project seeds silently** — the
starting point rather than an entry — because stamping a discovery date on
findings older than the feature would be confidently wrong. A report that
fails to parse, or a reports directory that is not there this minute, is
skipped rather than read as "everything was fixed": that is the SARIF trap the
rest of this is careful about.

**Artifacts** is the fifth view: what the project has built, listed from its
`dist/` directory — and the convention is the feature. Build systems scatter
their outputs (gradle five directories deep, cargo into `target/`), and a tab
that went looking for all of those would be a catalogue of build systems that
is wrong the week a new one arrives. So the deal is one word long: **what
ships goes in `dist/`**, a session that builds something copies it there, and
the tab lists `dist/` and nothing else. An empty tab on a project that builds
things means the copy step is missing, and it says so.

Each row is labeled by kind — apk, xpi, whatever the extension says — with
its size and age, newest first. Everything can be **downloaded**.

An `.apk` can be **installed** on the paired phone. `adb install -r` replaces
an existing copy in place and keeps its data, so install and update are one
verb and there is no second button. Two failures are common enough to be
turned into sentences rather than passed through: a **signature clash** (the
copy on the phone was signed with a different key — a release build, or one
from the Play Store, against a debug build from here) says to uninstall it on
the phone first, and notes that this takes the app's data with it, because
that is the operator's call to make on the handset rather than something to do
on their behalf. A **version downgrade** says so plainly; `-d` would allow it
but only for debuggable packages, and passing it always would quietly turn a
mistaken downgrade into a successful one. Neither `-g` nor `-t` is passed
either: granting every runtime permission, or allowing test-only packages,
makes the install behave unlike the one a real user would get, which is the
opposite of what testing on a real handset is for.

An `.xpi`
can instead be **pushed** to the paired phone, which unpacks it and hands the
directory to `web-ext` for a **temporary** install (gone when Firefox
restarts). Two rules keep the push honest: **nothing auto-pushes** — web-ext's
file-watcher is disabled and what is pushed is a snapshot, so a push is a
decision made each time — and pushing the **identical build** into a live
session is said rather than done, since it would install nothing. Stop the
session and the same file becomes pushable again, because after a stop (or a
Firefox restart) that is a legitimate thing to want. No History button,
deliberately: the files' own timestamps are the history, and a log of "the
file changed" would restate the mtime column.

**Analysis** is the notebook's fourth view: the scanner's findings for that
project alone, worst level first, read-only — the scan runs on the host, and
`bb findings` reads the same digest in a terminal. The whole-report findings
tab is gone; the Static analysis card's per-project rows are the way in now,
each opening its project's notebook on this view. Findings whose paths
resolve into anything other than a **valid** project — one that is listed, not
excluded, and free of error-level issues — are counted and set aside rather
than shown as "unattributed". The label is reserved for paths that genuinely
place nowhere, which is the case worth a look.

That rule is a subtraction, and deliberately so: rather than recognising each
kind of thing that is not a project, findings attribute only to the projects
worth reading them for, and everything else in the share falls out together.
It matters because of how the SDK share is mapped here — inside the
development folder, so the host's scanner walks it like anything else and one
report grew nine thousand findings for a pile of downloaded toolchains. A
marker file (`.bbignore`) handles the case where the container knows about the
directory, but a share mapped in with nothing to mark it is still listed as a
project — one with an error, because it is not a repository — so subtracting
only the *listed* names would have left it in play. Subtracting the valid ones
catches both, and needs no excludes configured on the scanner.

**The bug tracker** is the notebook's third view, and `bb bug` in a terminal.
The roadmap is for things somebody decided to build; a bug is a different
record — it has a severity, a place it lives, a way to make it happen, and a
gap between expected and actual, which are exactly its fields, plus a notes
field the analysis accumulates in (`bb bug note N "..."` appends, dated,
rather than replacing — the last analysis is how the next one starts). Either
side writes it: you report from the tab, a session files what it trips over
with `bb bug add "..." --sev high --area "..." --repro "..."`. It is
write-through, not staged — a report is a form submitted once. A bug **closes**
three ways, and the difference is what the next reader is told: **fixed**
(somebody fixed it), **won't fix** (a decision to leave it), and **not
applicable** (it was real and stopped applying, because the feature it was
about went away — neither of the other two is true of that). Each asks for
the note that is the point of closing, and `bb bug all` still lists it,
because a closed bug is the record that stops the same report being chased
twice.

**Delete** is separate and narrower: for a report that should never have
existed — mis-filed, duplicated, aimed at the wrong project. It takes the row
and leaves the reason in the log. The template CLAUDE.md tells sessions that
this is the only case for it; anything that was a real bug gets closed.

**Send to Claude** hands one bug to the session running there, from the same
box the roadmap opens under a step — the same Model and Effort pickers, the
same field for anything to send with it — opened under the report instead.

What goes over is **a number and an instruction, never a copy of the report**.
The line asks the session to run `bb bug show N` for the area, the repro,
expected against actual and the notes so far, and tells it to close the bug
with `bb bug fix N "what fixed it"` when it is done. That is deliberate: the
tracker is the copy that stays current, and a report pasted into a
conversation starts going stale the moment anybody adds a note to it — the
session would then be working from the paste while everything else here reads
the file. One number cannot drift. It also means a bug that has grown a long
analysis costs the same to hand over as a one-line report.

**A closed bug cannot be sent** — reopen it first. A closed bug is a record
rather than work, and the three closes exist to say which kind of dealt-with
it was; handing one over asks a session to deal with something somebody has
already decided is done. If a fix did not take, `reopen` is the honest way
back, and it leaves a line in the log where sending it again would leave
none. The button goes dead on the row and says so, and the server refuses it
independently — a rule only the panel honors is a suggestion, and this one is
reachable over the API.

Sending is **written into the tracker's log** as `sent`, because "was this
ever handed to a session, and when?" is a tracker question. It is not a status
change: sent is not fixed, and the bug stays open until somebody closes it.

The list **sorts** by severity, newest, oldest, recently changed or title,
from the same bar shape the log's filters use. Open before closed is not one
of the choices — a tracker is read to find what is outstanding — so every
order works within that. Open bugs ride into every session's starting prompt by number,
severity and title, with the fields on disk behind `bb bug show N`.

**Editing the list or the memories tells the running session**, in one line, to
go and read them and carry on — not to drop what it is doing. A list edited
under a conversation is a list that conversation is holding a stale copy of.

**The open items go in front of every Claude session the dashboard starts.**
`bb-tty` appends them to the session's system prompt, so a note left on Tuesday
is read on Thursday without anybody remembering to mention it. Items a session
added are marked, so you can see what it put there. It is given as context
rather than instructions: a session works an item when you ask, or when it is
plainly part of what you asked, and adds one when it notices something out of
scope for what it is on. The block travels to the session in a file rather than
on tmux's command line, which takes at most 16KB and answers a longer one with
`command too long` and nothing else — a full notebook made every Claude session
on that project unstartable, and the pane filled with that line as the terminal
reconnected into it. Past 100KB the block is cut at an item boundary and says
so, in the prompt and in the pane: one argument cannot exceed the kernel's
131072 bytes, and a list that big has outgrown being read at the start of every
conversation anyway.

The list lives in `/config/todos.json`, beside the tab strip and the excluded
projects — deliberately **not** in the repository. A list like this churns far
faster than commits, and a checkbox tapped on a phone should not turn into an
uncommitted change. Anything that deserves to be permanent graduates out of it:
into `CLAUDE.md`, a commit message, or a test that fails when it regresses.
Thirty open items is the ceiling, because the list is read at the start of
every conversation and one nobody can take in at a glance is one nobody reads.
Ticked items stay a week, then go.

- **Ending a session for good is the ✕ in the Sessions card.** That one asks,
  because that is where something is actually lost: the shell and everything
  in it, or the Claude conversation (its transcript is kept and can be resumed).
- **Switching between terminals is instant**, because a pane keeps the last
  three of them loaded behind the one on screen. It used to rebuild the pane
  to change tabs, which threw the frame away — and the terminal is 700KB of
  JavaScript that then had to parse, open a websocket, attach to tmux and
  draw. On a phone that was a second and a half of blank pane, every switch;
  it is now single-digit milliseconds. The frames sit exactly on top of one
  another at the same size, which is not just tidiness: a hidden frame is
  still an attached tmux client, and tmux sizes a window to its smallest one,
  so different geometry would mean the terminals fighting over the width. The
  fourth reloads, as all of them used to — the ceiling is there because each
  one is a live xterm and its own socket, the same reasoning as `DASHBOARD_MAX_TABS`.
  Killing a session also closes its tab, whichever tab that is — a tab left
  pointing at a dead session would only offer to recreate it.
- **Tabs are named for where they are.** A terminal reads `sh: <directory>`,
  following the shell as it `cd`s; hover for the full path. A Claude tab reads
  `Claude: <project>`. Two terminals in the same directory carry their number
  so they stay distinguishable.
- **Drag a tab** by its label to reorder the strip. With a finger, hold for
  half a second first — the tab dims to say it is picked up; a finger that
  moves sooner is swiping, and on a phone that swipe scrolls the strip.
- **⇱ on a tab** pins it to the **left** or **right** pane, which splits the
  view. Once split, each tab on screen carries ◧ or ◨ for the pane it is in,
  and clicking into either terminal makes its pane the active one — the one
  the keys and the commands go to.
- **✕ on a pane** collapses back to a single pane. It does **not** close the
  tab or touch its session — the tab owns the session, the pane is only where
  it was being shown.
- **On a phone** there is no split: the pin buttons are hidden and only the
  active pane is shown — a split made at the desk is still there when you get
  back to it. The strip stays one row — swipe it, or page it with the **‹ ›**
  arrows (grayed at the end you cannot page past) — instead of wrapping, so
  the terminal keeps its screen space; a tab you open is scrolled into view.
  Under the terminal sit three buttons, **Keys**, **Commands** and
  **Sessions**: the on-screen keys, the `bb` and custom command macros, and
  the session list — which on a phone live here rather than in dashboard
  cards (those three cards are hidden there). One flyout at a time — there is
  not the height for two — and a flyout that has done its job gets out of the
  way: picking a session or sending a command closes it. Which of the two
  views, Dashboard or Terminal, a phone was on is remembered across a reload,
  and while the dashboard is in front the **Terminal** switch carries the
  worst Claude state — amber if a session is waiting on you, blue if they are
  all working — as does each project's Claude button.

Every terminal runs inside **tmux**, so a dropped connection, a closed laptop
or a reloaded page detaches instead of killing the session. Coming back to a
backgrounded page reconnects **the terminal you are looking at** — the three
kept alive behind it reconnect when you switch to them, because reloading all
of them at once is several hundred kilobytes of terminal emulator apiece and a
phone spent its first seconds back doing exactly that. The **Sessions
card** is the full list — every terminal and every Claude session, named the way
the tabs are (`sh: <directory>`, `Claude: <project>`), including the ones you
minimized; the tmux name and full path are on hover. Document tabs are not
there, having nothing to keep.

**Selecting in a shell copies it.** Release the mouse and the selection is on
your system clipboard. That is why tmux's mouse mode is off in shell sessions:
with it on, tmux takes the drag and the text only ever reaches a tmux paste
buffer. The trade is that the wheel no longer scrolls tmux's scrollback there —
at a prompt it walks shell history instead. **Claude tabs keep mouse mode** and
so do not copy on select; its interface wants the mouse more than the
clipboard, and the wheel scrolls its output.

**Scrolling back is PgUp.** At a prompt, PgUp enters tmux copy mode a page up
and PgDn pages forward; copy mode ends by itself the moment you are back at
the bottom, so there is nothing to remember (`Ctrl-b [` still works, and `q`
still leaves). Inside a full-screen program the key is the program's. That is
also how a **phone** scrolls, with the PgUp/PgDn keys in the ⌨ Keys row: a
finger drag in the terminal reaches nothing, because tmux holds the alternate
screen and the browser terminal only turns wheel events into something tmux
can see — in either kind of tab.

The launcher sets this on the session as it starts one, not only in the config
file, because `~/.tmux.conf` lives on the persistent home: an install upgraded
from an image that wrote its settings straight into that file would otherwise
keep `mouse on` forever and nothing would explain why. That old copy is
recognized and replaced on the next start, with the original kept as
`~/.tmux.conf.builderbot-old`. Because the setting is applied per session, a
`set -g mouse on` in your own config no longer overrides it — turn it back on
where you want it with `Ctrl-b : set mouse on`.

**Right-click gives you one menu, the browser's.** tmux draws its own context
menu inside the terminal, and the browser's lands on top of it — two menus for
one click, only one of them dismissable. The browser's cannot be suppressed
from outside the frame (the terminal is served from its own port), so tmux's is
unbound. **Alt+right-click** still opens it if you want *Copy Line* and the
pane commands.

**The tab strip is shared, not per-browser.** It lives on the container, so
opening the dashboard on a phone shows what the desktop has open, and a change
on either reaches the other within a poll. `DASHBOARD_MAX_TABS` (default 12)
caps how many can be open at once: each terminal tab is an iframe running a
full terminal emulator over its own websocket, so the limit is about browser
memory, not tidiness.

**Terminals survive a container restart, scrollback and all.** tmux dies with
the container, so on the way down the supervisor writes each terminal's
directory and the last 2000 lines of its screen (`BB_SESSION_HISTORY`) to
`/config/sessions/`, and a startup hook recreates them there and prints that
scrollback back in before the shell starts. Minimized terminals come back the
same way, since they are sessions like any other.

What comes back is the terminal, not what was running in it. A build that was
halfway through went down with the container — restarting it here would be a
promise this cannot keep — and the shutdown kills whatever was running before it
takes the sessions' picture. Sessions are single-pane by construction; if you
split one inside tmux, only the active pane's contents are kept.

**Claude sessions do not come back.** The conversation ended with the container,
and a session wearing its old name would be a new one pretending otherwise. Its
tab is dropped at boot too, and the project's **Claude** button offers to resume
the transcript, which is still on disk.

### Commands run in the terminal

The `bb` commands worth a button are buttons. Clicking one clears whatever is half-typed at
the prompt, types the command into the terminal you are looking at and presses
Enter, rather than reporting into a box of its own. The
output is then somewhere you can scroll it, a slow one like `bb runner stop` is
watchable while it runs, and one that asks a question (`bb login`) or follows
(`bb logs -f`) behaves exactly as if you had typed it. A command only ever goes
to the tab you are looking at, and only if that is a plain shell: with a
**Claude** tab in front (it would submit the command as a prompt), a document,
or no tab at all, every command button is grayed out and its hover text says
where to go — never quietly typed into some other terminal.

The line is cleared with end-of-line then kill-line, which is readline editing
rather than a signal: `Ctrl-C` would also interrupt whatever is running in that
terminal, which is not something a button labeled `bb status` should be able to
do.

They are listed in `bb help`'s own order, so the card and the CLI read the
same. If the list outgrows the card it is cut off at eight with a **Show all**
button after the cut. The **thumbtack** on each command keeps it above that
cut — pinning moves a command up, it does not re-sort it into an order the CLI
never uses. Pins live in `/config/pinned-commands.json` — one machine, one
operator, so a pin made at the desk is there on the phone.

What is *not* there is most of `bb`, on purpose. Nothing that needs an argument
(`bb shot URL`) — a button is never a half-written command line. Nothing a card
already does better: the Projects card lists projects and offers the CLAUDE.md
fixes on each row, the Doctor card runs doctor, the findings report beats
`bb findings`, and the Runner card has the runner's own controls. And nothing
that only means anything from a checkout of the BuilderBot repo (`bb drift`,
`bb dashboard dev`) — those are for sessions developing the container. What is
left is what an operator actually reaches for from a terminal: status, update,
login, the emulator, lint, and the logs.

Two more command cards flank the `bb` one, following the same rules. **Linux
commands** is the general toolkit — `ls -lah`, disk usage here and per mount,
memory, the biggest processes, listening ports — live on any shell tab. **Git
& GitHub** shows its commands verbatim (`git status`, log, diff, branches,
fetch, pull; `gh pr list`, `gh run list`, …) and ghosts against the directory
the active shell is *in*, not just whether it is a shell: outside a git
repository the whole card grays out, and in a repository whose remotes do not
include GitHub, just the `gh` half does — the hover text says which it is.
The verdict follows a `cd` on the next status poll, and the ghosting only
reflects the repo; `gh` itself still needs its own auth (`GIT_PAT` or
`gh auth login`) to answer.

### Your own commands

The **Custom commands** card starts empty with a **+**. It takes a title and a
box of command lines, and the button it makes types those lines into the
terminal you are looking at, in order, exactly as if you had typed them — one
line or twenty. The pencil beside each one edits or deletes it.

Long titles are cut with an ellipsis so the card keeps its shape; hovering shows
the full title *and* the commands it will run, which is the thing you will want
six months later. They live in `/config/custom-commands.json`, so they survive
restarts and image updates and are the same on every device.

This is the one place the dashboard sends text you wrote rather than a name from
a fixed list — and it is still not a remote-execution API. The lines are stored
by one authenticated request and typed by another into a tty that the same
operator is already sitting at with a full shell. Nothing is executed in the
dashboard's own process.

### A phone, and asking before touching it

USB is not an option here — there is no `/dev/bus/usb` in the container, and
passed through it would mean plugging the handset into the server rather than
leaving it on the desk. So the **Phone** card speaks Android's wireless
debugging: pair once with the six-digit code, then Connect by IP.

**Open the dashboard on the phone and the IP is already there.** The address
the field exists to capture is the client address of that very request, and
Docker's bridge does not masquerade it — so browsing from the handset fills it
in and says "this device". Only for an Android browser: from a desktop the
client address is the desktop's, which is not the phone, and filling it in
would be a confident wrong answer. The port and the six-digit code still come
off the phone's own screen; nothing but the phone knows those.

**Pairing is once, and it outlives a restart** — the key the phone trusts is
in `~/.android` on the home volume, so after a container update the phone is
still paired and Connect is all it needs. Which matters because pairing has a
trap in it: **Android cancels the pairing dialog the moment you navigate away
from it**, taking its port with it. Pairing from the browser *on the phone you
are pairing* therefore cannot work — by the time you paste the code, the port
it belonged to is gone. The card notices that case (it knows it is being read
on the phone whose IP is in the field) and says so, and says the thing worth
saying first: try Connect, you are probably already paired.

**You give it an IP, not a port.** Android hands out a new one every time
wireless debugging is toggled, so a remembered port goes stale, and the port on
the pairing screen is a different number from the one on the main screen
anyway. The server scans for it. mDNS would answer for free and cannot — the
container is NAT'd on Docker's bridge and multicast does not cross it.

**Pushing lives in the notebook now**, on the Artifacts view — the card is
the connection, and what there is to push is a fact about a project rather
than about the phone.

**A session never touches the phone itself.** It is kept on an adb server of
its own, so a plain `adb devices` in a session shows the emulator and nothing
else. To reach the handset a session runs `bb phone run --why "..." -- …`,
which puts the reason and the exact command on the card and waits; on **Allow**
the dashboard runs it and hands back the output. The reason is required, not
optional — approving a command you did not write, with no sentence saying what
it is for, is a guess.

That is a door that is shut by default rather than a wall. A session could set
`ANDROID_ADB_SERVER_PORT` itself and go straight there; inside one container,
with Bash, nothing can be a wall. What it buys is that reaching the phone is a
deliberate act rather than an incidental one, and that every deliberate one
leaves a question on your screen.

### How a view knows to re-read

Every view shows facts it does not own. The roadmap's arrows depend on a Claude
session existing; the Artifacts tab's Push depends on a phone being connected
somewhere else entirely; the Phone card's questions arrive from a terminal. In
one week, four of them went stale in exactly the same way — each had invented
its own rule for when to re-read, out of knowledge it did not have. The worst
was self-defeating: the Phone card polled only while it already knew of a
pending request, so it could never discover the first one.

So no view decides that any more. `/api/revs` returns one token per thing that
can change, a view registers what it depends on, and it is told:

```js
onRev("phone.asks", () => phFetch());
onRev(() => `dist:${project}`, () => loadArtifacts());
```

The endpoint is **deliberately tiny** — file mtimes and in-memory counters, no
git, no tmux, no adb — which is what makes it affordable at a second and a
half, where `/api/status` runs git for every project and is affordable at
fifteen. The one thing that is not free, the set of attached devices, is
cached with a floor of a few seconds and refreshed at once when the dashboard
itself connects or disconnects, so pressing Connect is instant rather than up
to that floor late.

**A hidden tab slows down; it does not stop.** That distinction is the point:
a request lands while you are looking at something else, which is the ordinary
case rather than the exception. The poll drops to thirty seconds when the tab
is hidden — browsers throttle background timers hard anyway — and the tab
re-reads *immediately* on becoming visible, so coming back to it is never
looking at a stale page. A pending request also puts a count in the **tab
title** and a dot on the **favicon**, which is as far as a page can go without
asking for notification permission; that is a decision about your browser
rather than about the dashboard, so it is not taken on your behalf.

Requests wait **fifteen minutes**, not five, and the card counts down. Five
assumed somebody was already watching the dashboard; a request that expires
before it is ever seen is worse than one that waits, because the session is
idle either way and only one of the two ends in an answer.

### Reading CI from inside the container

The self-hosted runner streams a job's console output to GitHub and keeps none
of it. `/workspace/_work/_diag` holds the runner's own diagnostics — which step
failed and its exit code — and not one line of what that step printed. With
`GIT_PAT` unset there is no API to ask either, so *"CI is red, why?"* had no
answer in here for a job that ran in this very container.

So the lint workflow archives its own output: each check is teed into
`/config/ci-logs/<repo>/<run-id>-<attempt>.log`, with a header naming the
commit, ref and event, and a `result:` line written by an `if: always()` step
so a job that died still says so. `bb ci-log` prints the newest, `--list` shows
the twenty kept with their results, and a run id picks one.

Two details that are load-bearing. The job sets `shell: bash` rather than
taking the default `bash -e`, because the difference is `pipefail` — without it
the tee's exit status becomes the step's and a failing linter reports success.
And the logs live in `/config` rather than `/tmp`, because a log that vanishes
with the container is no use for the question *"what broke while I was away?"*.

This only covers jobs that run on this box. A workflow on a hosted runner is
out of reach, which is one more reason to keep the checks self-hosted where the
minutes are free anyway.

### Keeping a session in its own project

A Claude session started from the dashboard is launched with a generated
settings file that denies its file tools — `Read`, `Edit`, `Write` and
`NotebookEdit`, since a deny rule names one tool and Read does not imply the
rest — access to every *other* project under `/workspace`, plus the runner's
`_work` checkouts. Siblings are enumerated by name rather than matched by
pattern, so a project called `app[1]` cannot quietly take its neighbours out of
the list. That file is passed with
`--settings`, which ranks as a command-line argument — above the project's own
`.claude/settings.json` and `.claude/settings.local.json` — so a session cannot
widen its own boundary by editing files in the repo it is working on. Only the
root-owned managed policy file outranks it.

**This is a guardrail, not a sandbox.** It stops a session wandering into the
wrong tree by mistake, which is the common failure. Note also that it only
applies to sessions the dashboard starts: run `claude` yourself in a shell tab
and there is no settings file, leaving the instruction in the project's
CLAUDE.md as the only thing asking it to stay put. It does not contain one
that goes looking: Bash still reaches the whole filesystem, and no in-process
permission system changes that. If you need a hard boundary, do not mount the
other projects into the same container.

### Excluding a project

The **eye** on a project row blocks Claude sessions for that directory — a
struck-through eye excludes it, a plain eye lets it back in. The
list lives in `/config/excluded-projects.json`, so it survives restarts and
image updates, and it is enforced by the terminal launcher rather than the
page — the ttyd URL is reachable on its own, so a rule only the UI honored
would be advice. Specifically, excluding a project:

- refuses `claude:<project>` at launch, with a message saying why
- ends any Claude session already running there, rather than taking effect
  "next time"
- folds the row away behind **Show projects with errors**, and puts it at the
  *bottom* of that list — an exclusion is a decision already made, not a problem
  waiting for someone
- grays the row out and takes the click off anything in it. A `no CLAUDE.md —
  create one` line stays as text, because nothing acts on an excluded project
  until it is let back in. **Shell** and the **eye** keep their weight: those
  are how you look at it and how you reverse it

Other projects' sessions were already denied read access to it, the same as to
any sibling — that comes from the scoping above, not from excluding it.

A shell there is still offered, so you can go and look at what you excluded.

```
ENABLE_DASHBOARD=true
DASHBOARD_AUTH=you:a-real-password
```

**`DASHBOARD_AUTH` is mandatory and the dashboard refuses to start without
it.** What it publishes is a writable shell inside a container holding a loaded
ssh-agent and read-write mounts of every project — so that credential is worth
as much as the ssh keys are. It is not a convenience toggle; treat it like the
Docker socket mount.

Only the dashboard port is published. ttyd binds the loopback and the
dashboard relays `/term` to it — an earlier revision kept the terminal on its
own published port to avoid hand-relaying a PTY websocket, but the price was
the browser asking for credentials twice and a second port on the router, and
the relay that buys that back is deliberately dumb: after checking the
session it splices the two sockets byte for byte and never parses a frame.
Credentials are checked in one place either way — the cookie or basic auth
this server already verifies; the old `DASHBOARD_TTYD_PUBLIC_PORT` knob is
gone with the second port that needed it. curl and scripts can skip the
login page entirely: basic auth is honored preemptively on every request
(`curl -u user:pass ...`), there is just no `WWW-Authenticate` challenge —
that header is exactly what made browsers pop their own dialog.

The dashboard's own API runs commands from a fixed list — it takes a macro name,
never a command string, and the list is `bb`'s own commands rather than anything
the page can compose. The one exception is a **custom command**: the operator's
own lines, stored by one authenticated request and typed by another into a tty
they are already sitting at with a full shell. Nothing runs in the dashboard's
process either way, and anything else belongs in the terminal, which is one port
away and honest about being a shell.

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

**The dashboard checks too.** A project whose block has drifted is flagged in
amber on the Projects card, and that line is a link: clicking it runs the same
`bb claude-md --update` against that project and the warning clears. It is the
same comparison `bb claude-md` makes — the marked block against the image's
template, and nothing below the end marker — done in-process rather than by
shelling out once per project on every poll. A `CLAUDE.md` with no markers is
named but *not* offered the link, because `--update` refuses that file too.

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
  lib/sdk.sh                     the package manager: `bb sdk`, sourced by bb
  lib/sdkmeta.py                 reads config/packages.json for bb: fields, argv, versions
  startup.d/*.sh                 startup hooks
  dashboard/                     web dashboard: server.py, index.html, bb-tty
    packages.py                  everything behind the Tools tab: catalog, sizes, the job worker
    memory.py                    everything behind the memory book: what Claude remembers per project
    projects.py                  new project / link to GitHub, and the worker that clones and pushes
    todo.py                      the roadmap; `bb roadmap` drives the same file
    bugs.py                      the bug tracker; `bb bug` drives the same file
    notebook.py                  one batch over both of those, so half of one cannot exist
    notify.py                    getting a line into a running Claude session, and knowing it landed
    signin.py                    the Claude sign-in, under a pty rather than in a terminal
    test/                        its Playwright suite — `bb dashboard test`, isolated
config/skel/                     home directory skeleton
config/packages.json             the packages the Tools tab offers, and how to install each
config/templates/                project CLAUDE.md template (shipped in the image)
docs/unraid.md                   step-by-step Unraid walkthrough
.hadolint.yaml                   Dockerfile lint config, shared by CI and bb lint
.github/actionlint.yaml          this runner's labels, for workflow linting
.github/workflows/               GHCR publish (hosted, cached from :latest); lint + dashboard
                                 browser tests (on this runner); runner smoke test (manual)
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
