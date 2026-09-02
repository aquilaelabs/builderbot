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
  │  /workspace  ◄─────────  /mnt/user/development/projects   │
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

The dashboard starts early in the boot, before the Claude Code update, any
project's own `setup.sh` and the SDK/Playwright/Android hooks — so the web UI
is reachable in seconds rather than after the whole start-up. For a few of
those seconds it knows less than it will: the SDK share is listed as a project
until the hook that marks it runs, git columns are blank, Claude's version is
unknown. All of that corrects itself on the next poll. `bb logs` now times each
hook and prints how far into the boot it started, so "what is the wait" is a
question the log answers.
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
| Projects folder | One mapping for all of them: `/mnt/user/development/projects` → `/workspace`. Every folder inside it is a project |
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
| Web dashboard | Set `ENABLE_DASHBOARD=true` **and** `DASHBOARD_AUTH=user:pass`, map port 7680 — see [Web dashboard](#web-dashboard) |
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
(agent key vs file key), the **Docker daemon** on the sandbox node — whether
it actually answers, and says it is a sandbox — and —
when a GPU is passed through — whether its **graphics stack** is usable or
only CUDA is.

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
and is always the big one. *Run workflow* takes a **Rebuild every layer** box
for the same effect on demand — leave it off and a manual run is a cheap retry,
tick it to force a fresh pull of everything. Rollback = point the Repository field at a
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
| `UNRAID_ICON_NAME` | `BuilderBot` | Only with the icon-cache mapping: Unraid names the cached icon after the container, and nothing inside one can see its own name — set this if you renamed it |
| `ENABLE_DASHBOARD` | `false` | Web dashboard + browser terminal |
| `DASHBOARD_AUTH` | *(empty)* | `user:password` — **required** when the dashboard is enabled; it will not start otherwise |
| `DASHBOARD_PORT` | `7680` | The one published port: page, API and terminals (proxied under `/term`) |
| `DASHBOARD_TTYD_PORT` | `7681` | ttyd's loopback bind inside the container; never published |
| `DASHBOARD_DOCTOR_INTERVAL` | `1800` | Seconds between the dashboard's background `bb doctor` runs (min 300) |
| `BB_LOG_KEEP` | `60` | A ceiling on kept generations, not the retention policy — how long logs are kept is a number of days, set in the dashboard's settings menu. This exists so a crash loop cannot fill the directory |
| `BB_SESSION_HISTORY` | `2000` | Lines of each terminal's screen saved at shutdown and printed back when it is restored |

Mounts: the projects folder, three state dirs (`home`, `config`, `work`), and
three optional ones — `/secrets` (ro, shielded credentials), `/logs`
(relocate logs).

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
bb version unbump      take an unreleased bump back; its changelog section
                   dissolves into Unreleased, the code stays
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
bb nodes           the node registry, read-only in a terminal — the Nodes
                   tab is where it is edited; `local` is this container
bb jobs [-n N]     the recent jobs: state, node, what ran, how it ended —
                   read-only; the Jobs tab is where one is stopped
bb run [opts] -- CMD   snapshot this tree, run CMD on the project's node and
                   stream the log back; `--out GLOB` brings what matches into
                   dist/ with its provenance; `--node` names another node
bb build           the project's build command on its node, with the outputs
                   it lists — all set in the project's settings dialog
bb test            the same for its test command
bb emu create API  build the AVD for an API level, installing its image if missing
bb emu install APK install an APK on the running emulator
bb emu shot [FILE] screenshot the emulator into dist/emu/
bb emu gfx PKG     a package's per-frame timings (gfxinfo framestats) into
                   dist/emu/ — and every emu verb runs on the project's node
                   when it has one, its output coming back into dist/
bb ci-labels       the runner labels the registry knows — this box's and every
                   node runner's; `--write` regenerates .github/actionlint.yaml
bb findings        this project's scanner findings (--all for every project)
                   narrow with --level error|warning|note, --rule ID, --find TEXT
bb findings history   what the scanner stopped and started saying here
                      (-n N, --since 7d, --find TEXT, as the other logs)
bb roadmap            this project's roadmap
bb roadmap show N     one item in full: its details, its steps and theirs
bb roadmap add "..."  put something on it; `done N` finished, `rm N [why]` not
bb roadmap shelve N   park one without dropping it; `mv N up|down` moves it
bb roadmap add "..." --step "..." --step "..."   an ordered group of steps
bb roadmap edit N "..."               reword one; `step add|edit|rm|done` for one step
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
bb catchup         what has happened here lately: commits with the first line
                   of their bodies, what moved in the notebook, the builds this
                   box archived, and which image it is actually running
                   (`--since 7d`, `-n COMMITS`)
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

The dashboard's Commands flyout carries this same list in this same order.

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

**That server is watched, three times over.** It has died hours into a boot
with nothing in its log — no error, no signal, a clean startup and then
silence — and what made that expensive was the silence rather than the death:
the emulator went on working, on software, and every timing conclusion drawn
afterwards was wrong. So the hook restarts it up to three times with a backoff
and then **stops and says so**. An unbounded respawn against a card the host
has taken back would be worse than the silence it replaces, so the card is
checked before each attempt: if `nvidia-smi` stops answering, the watch ends
there and records that instead. Either way `bb emu gpu` and `bb doctor` print
what happened, which is what turns a silent drop to software into a stated one.

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
bb findings --level error --rule DL3008 --find "quote"   # narrow it
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
The three filters are the Analysis tab's bar in flag form — `--level` takes
error, warning or note (note and info are one level everywhere here), `--rule`
matches a rule id exactly, `--find` searches rules, paths and messages — so a
question answered in the browser is askable from a session in one line.

**Review the diffs.** Findings need judgment about intent — whether a `|safe`
is deliberate, whether a SHA1 is for dedup rather than security. Asking Claude
to fix everything and re-scan unattended optimizes for a clean report, which is
not the same as better code, and suppressing a finding satisfies that goal too.

## Web dashboard

Off by default. When enabled it serves everything on `7680`: the page, the
API, and the browser terminals, which are proxied under `/term` so one
sign-in covers them all. Signing in is a login page that sets a 30-day
cookie — a real form, so password managers work — not the browser's own
credentials dialog, and there is no second prompt for the terminal port
because there is no second port. The sign-out button beside ↻ and ▤ in the header ends the session (`/logout` does the same).

**The bell** in the header is where messages go to stay. A toast says a thing
once, for four seconds, to whoever happened to be looking — the right deal for
*saved*, and the wrong one for anything that failed while you were in another
tab. So every message the page shows lands behind the bell as well and stays
until you clear it, errors marked as errors. It is bare rather than boxed
because it is a state light first and a control second: a red dot means
something unread, an **amber** one means a session is blocked on an answer.
That second case is the reason it exists — a request to reach the phone shows
up there with **Approve** and **Deny** on it, so answering does not depend on
which of the two views you happen to be looking at, or on the Phone card being
scrolled into sight. Clearing empties the page's own log and never an ask: a
question somebody is still waiting on is not this button's to dismiss. The log
is this tab's, so a reload draws a line under it; the asks are the server's and
are read live, which is why they leave the list the moment they are answered or
time out.

The **About** control beside it is the version, and where the header is too
narrow for a version string it becomes a **?** rather than a truncated number
that answers nothing — either way the popup behind it carries the whole stamp. Every sidebar card collapses to its header with a click
on that header, and dragging a header reorders the cards; both are remembered
in `/config/cards.json`, so the phone and the desktop agree about the
arrangement and it survives restarts and image updates. The **▤** button in
the top bar opens the appearance menu, whose first item puts it all back:
default order — Doctor on top — with every card expanded.

**Under it, twelve colour schemes**, all dark, because this page is read in a
dim room beside a terminal and a light one would be a different design rather
than a recolour of this one. A scheme is nine custom properties: every rule in
the stylesheet draws from them, and the button and accent families are mixed
from the scheme's own panel and accent (`color-mix`, with flat fallbacks), so
a recolour reaches the tabs, the primaries and the active states rather than
stopping at the background. Each swatch is defined for `.sw[data-theme=…]` as
well as for the page, which means the preview *is* the palette rather than a
second copy of it that can drift.

**Nostromo** is the one that is more than a recolour: amber phosphor on a
green-black hull, with a hazard decal along the header's bottom edge, a stencil
tick on each card title, faint scanlines on the panels and a vignette on the
page. All of it drawn — gradients and one pseudo-element, no image files. That
is the persistence rule rather than taste: an image would be a binary in the
repository, re-shipped in a weekly rebuild, for something two gradients say.
Nothing in it moves the layout, so switching schemes never nudges the page.

The choice is kept in the browser (`localStorage`, `bb.theme`) rather than on
the server beside the card order — that describes the work and should follow
you between machines; which colours are comfortable is about the room you are
sitting in, and a phone in the dark may reasonably differ from a desktop at
noon. It is also applied from a block in `<head>`, before the first paint,
which a value fetched from the server could not be without a flash. The sidebar is what the *box* is doing; the command lists and
the session list are about the shell in front of you, and hang off the
terminal instead — see below. On a touch screen, hold a header for half a second to pick
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
  the projects share (the SDK share, if you map it inside the projects
  folder rather than beside it), and you can create one by hand for anything else
  you would rather not see. It *hides*; the padlock **blocks**, which is a
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
  Picking one makes the server handle the container side: it writes the
  `.pub` selector and an `IdentitiesOnly` ssh alias
  (`bb-<key>`, in a namespace of its own so hand-maintained config is never
  touched) and clones through the alias — which the remote then keeps, so
  later pushes offer the right key too. Only the matched agent key's own
  public line is ever written; nothing from the request is. With a PAT
  configured (a per-project token, or `gh auth login`) the key is optional even for
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
  is a bin on the row. Beside it, **Docker manager…**, **Static analysis**
  and **Nodes**, each a tab of its own
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
- a **padlock** per project, which locks it: no Claude session starts there
  and its notebook goes read-only — see below. A locked row keeps every
  control, with its Claude button ghosted rather than removed and a closed
  padlock after the name; a row with a repo *error* carries no Claude button at
  all, because a session cannot start there. **Shell** stays either way, since
  that is often how you would fix it
- a **thumbtack** per project, which decides whether the sidebar shows it at
  all. Unpinning takes a project off this card and nothing else: it keeps every
  control on the **All projects** tab at the foot of the card, which lists
  everything under `/workspace` with the same buttons on each row. Pins live in
  `/config/pinned-projects.json`; no file at all means everything is pinned,
  which is what a fresh install sees
- a **bin**, on the **All projects** tab only, which moves a project to
  `/workspace/.trash/<name>` with every file kept — a second delete of the same
  name is numbered rather than overwriting the first, and `/config` is not
  touched, so putting one back is a `mv`. Deliberately not on the sidebar card
- a **pencil** per project, which renames it — the directory, and everything
  keyed to its old name: the roadmap and bugs, the versions, the dev instance's
  data and env, the archived CI logs, and Claude's own transcripts and
  memories. It refuses while a terminal is open on it or its dev instance still
  has containers, and it reports what moved rather than only that it worked
- a **padlock** per project, which locks it: the row stays whole and every
  control you use stays live — notebook, artifacts, dev instance, shell — and
  the only thing that goes is Claude starting a session there. For a project
  you keep in `/workspace` to deploy and run rather than to develop
The **Tools** card carries **Docker manager…**, which is where a project's
containers are built, started, stopped and given their env. A project can have
several — the Artifacts tab's dev row is one button now, **Send to Docker
manager…**, which names a container and takes you there; every container of a
project is built from that project's codebase, and rebuilding takes whatever
that codebase says at the time.

**The daemon is a node.** The sandbox VM is added on the Nodes tab — its
address, with `ssh://` and the `bb` account filled in — and what this
container's paths are called over there is set on the node's row, because
the daemon resolves a compose file's bind sources on its own filesystem. The
manager tab says which node it is on — *"on a sandbox VM at ssh://…"* — and
`bb doctor` prints the same line from the same function, so the two cannot
disagree about which daemon is live. (`DOCKER_HOST` and `DOCKER_HOST_PATHS`
from earlier releases seed that record once and are otherwise ignored.)

**A daemon has to say it is the sandbox before anything is driven on it.**
`vm/provision.sh` writes a `builderbot.sandbox` label into the VM's
`/etc/docker/daemon.json`; the dashboard reads it back with `docker info` over
the ssh connection it already has, and a daemon without it is refused exactly
like an unreachable one — named as the reason, with the command to fix it. An
ssh address only proves somebody typed one, and every one-shot container the
manager runs is root on the far side: what makes that reasonable is the far
side being a box built to be wrecked, which is a thing only the provisioner
can vouch for. A VM set up before this shipped has no stamp; re-running
`provision.sh` adds it and changes nothing else.

**Point it at a different sandbox and that one becomes the source of truth.**
A build records the daemon's own id as well as its address, because two VMs can
wear one address — a rebuilt sandbox, a second machine given the old one's IP.
When the id changes, records claiming a build on the machine no longer in play
are cleared rather than left quoting a version this daemon has never seen; the
instances stay, since their compose file and env are this side's.

**With no daemon reachable, the controls that would drive one are disabled**,
each carrying the reason as its tooltip, and the manager tab says the same
thing in words at the top — a tooltip is not reachable on a phone, and *"why is
everything greyed out"* should be answered by looking. That is the node
unset, or a sandbox VM this container
cannot reach; `available()` in `devapp.py` already distinguishes them, and the
answer rides the status poll memoised, because asking it properly is a
subprocess and the poll is the page's heartbeat.

Three things deliberately stay live. **Refresh** is the retry — it drops the
memo, so a daemon wired up a moment ago is noticed by pressing it rather than
by waiting. **Edit** and **Env** open a compose file, which is a file whatever
can run it. And the manager tab still opens, because disabling the way to
*read* a diagnosis is how a dashboard goes quiet for no visible cause.

**The rows are still there, and they stop claiming anything.** What an
instance *is* — its name, its project, what it was last built from, what its
env still wants — lives on this side of the wire and needs no daemon; only
whether it is *running* is the daemon's to know. So a manager opened against a
VM that is off lists everything on record, greyed, each row saying **state
unknown** rather than reporting one nobody asked for: an unreachable daemon is
not evidence that anything stopped. It is also fast, because a daemon known to
be off is asked nothing — `docker ps` over ssh to a machine that is not there
sits until its timeout, and that used to be the whole cost of finding out.

**With more than one docker host, the manager grows a node picker.** Nodes
with the `docker-host` capability are listed online or not; picking one
switches the whole view to that node's daemon — one tab, re-rendered, never a
tab per node. Each node's last-known container list is kept, so switching to
an offline node paints instantly in the greyed state above rather than
spinning at a machine that will not answer, and the reason is that node's
own. **New container…** and **Send to Docker manager…** gain the same select,
defaulting to the project's own node from its settings dialog (a per-project
binding, `auto` unless chosen); an instance stays bound to the node it was
created on, and everything that acts on it — Up, Down, Rebuild, the data
directory's one-shot containers — addresses that node's daemon.

### The Nodes tab

**Tools → Nodes** is the registry (docs/nodes.md): every machine work can run
on, `local` — this container — first. A row carries the node's state,
the toolchains its census found — what a project bound to it can build — labels
and census, with **Test** (probe its daemon now, sandbox stamp included),
**Drain** (finish what is running, accept nothing new — what makes a node
safe to reboot) and **Remove** (retire: off every list, row kept as history —
an id is never reused). **Enroll node** mints a one-time token; the machine
runs `vm/provision.sh --controller URL --token bbe_…` and dials in. That is
the only way in — there is no second enrollment, this container holds no key
that logs in anywhere, and a node reached by token alone takes every kind of
job, docker included. The **ssh node kind is retired** (roadmap #18): it
existed because compose used to run from this container over ssh, which meant
a node needed a key on top of its token and a token-only node — the cloud
case — could do everything except docker. A row left over from before says so
and asks to be enrolled again. Its **path mapping** — what this container's
paths are called on that machine — is still on its row, which is where the old
`DOCKER_HOST_PATHS` setting lives now. The
local node refuses `docker-host` on purpose — it is not a sandbox. Every
change writes an audit row.

**A node does everything for the projects bound to it.** There is nothing to
pick per node — no "this one builds, that one deploys". A project names one
node in its settings dialog and its containers, builds, tests, CI and
emulation all go there, so three projects on three VMs stay apart and three
projects on one VM share it. What a project can actually do on its node is
what is **installed** there: the row lists the toolchains its census found,
and the Tools tab's node picker is where more are added. (Underneath, the
node still refuses a job asking for something it did not enrol with — the
enforcement of docs/nodes.md §15 door 7 — but every node now enrols with the
full set, so it is a mechanism rather than a setting.)

**Enroll node** is the other way in, and the one the design is built around:
it makes a pending row and mints a one-time token (`bbe_…`, good for a day),
shown once inside the command to run on the machine —
`sudo bash provision.sh --controller URL --token bbe_…`, or the two-line
version that fetches `builderbot-agent` by hand. The provisioner downloads
the agent from the controller itself (checking it against the digest the
controller sends), enrolls, and leaves it running under systemd. From then
on the node **dials out**: no port is opened on it, the controller holds no
key that logs in anywhere, and the credential the node keeps
(`/etc/builderbot/node.json`, 0600) opens its own row and nothing else.
Revoke on the row ends it; the agent says so in its journal and the row goes
quiet, keeping its history. The one-day life belongs to the *enrollment*
token only — the credential the node keeps afterwards does not expire, so an
enrolled node needs nothing renewed.

**Updating the agent is a button, never automatic.** The row says *update
available* when the node's agent is not the file this controller ships, and
**Update agent** hands it over as a job: the agent checks the download
against the digest, swaps itself in place and re-execs, so nothing on the
node restarts and no running job is interrupted (it waits for its own to
finish). Re-running `provision.sh` on an enrolled node does the same thing
from the console, with the node's own token. Nothing updates an agent
unasked.

**Until it is updated, that node takes nothing else.** The controller is
where the agent file comes from, so it is always the newer of the two, and a
job it queues may name something the older agent does not know — a job type,
a field in the spec — which an older agent meets with a shrug rather than an
error. So while *update available* is showing, Apply storage, Apply network,
Install runner, Clear cache and installing a package onto that node are all
refused, with the reason on the button; the self-update itself is the one
thing that still goes through. Nodes running the shipped agent are unaffected.

**A store cannot be pointed at a share that is not mounted.** This is the
one storage mistake that looks like success: a share in fstab but not
mounted leaves its mountpoint an ordinary empty directory, the store gets
made inside it, and everything lands on the node's own disk while the row
reports a healthy store with plenty of room. Apply refuses it instead,
naming the share and what would have happened — fix the mount, or take it
out of the node's mounts if that path is meant to be local. At the console
`bb-sandbox` holds the same line from the other end: `remove` will not
unmount a share a store is inside without `--force`, `list` marks a mount
that holds stores, and a share that fails to mount says which store is
stranded in it.

**Repointing a store moves what is in it.** The contents are copied to the
new path before the switch, and the tab asks first, because a packages store
is tens of gigabytes and the job waits for the copy. Nothing is deleted: the
old copy stays where it was for you to remove once you are satisfied, so a
move that fails half way leaves the node still able to work. `cache` is the
exception — it is rebuildable, so it is left behind and the log says so.

**Saved is not applied.** The settings on a node's page are a record of what
it *should* be; **Apply** is what makes the machine match. The state line
under them says which of the two you are looking at — how many changes are
waiting and what they are, or that the node already matches — and Apply is
off when there is nothing to do. `dhcp` is the one thing it cannot answer:
the census reports the addresses a node has, not how it got them, so a node
set to `dhcp` keeps Apply network live and says so.

An agent node's row is *live* when a poll has arrived within the last 75
seconds, and the poll carries the numbers — CPU, memory, jobs running and
free space per store (`data`, `packages`, `cache`) — so the row shows them
and `bb nodes` marks liveness (`●` live, `○` quiet, `✗` revoked). Test runs
`uname` there through the channel and shows the answer. Jobs run as the
account the node enrolled (`bb`, the docker account), never as root, and a
job needing a capability the node was not enrolled with is refused **on the
node** (exit 77), whatever the row says. Over plain http the node token
travels in the clear, as the dashboard's own credential does; enrollment says
so, and with TLS in front of the dashboard the agent pins the certificate on
first use and refuses a different one after.

Two nodes may point `packages` at the same NFS export deliberately, and then
they are one store: what is installed on either is installed for both — a
node's toolchains are read from the store at every census, so its neighbour's
install shows up within the census interval. What that arrangement needs is a
lock, and it has one: an install is refused while a package job is running on
any node sharing that store, naming which, and the Tools tab says the store
is shared before you press. Sharing is recognised by the mount's source, not
by the path, since every node's default path is the same string.

**Four stores per node**, each a directory of its own: `data` (job
workspaces and AVDs), `packages` (the toolchains installed there — what a
project bound to that node can build), `cache` (build caches, per project)
and `artifacts` (that node's copy of what its projects built, per project).
The artifacts store is what makes a node off the LAN reasonable: an emulator
or a container there starts from a copy beside it, and a second run of an
unchanged build copies nothing. A store path may not be a system directory —
`/etc`, anything under `/usr`, or a bare `/mnt` — because the agent creates,
fills and empties these; the refusal is made on the dashboard and again on
the node.

**Storage & network, from the row.** A node that enrolled as a sandbox (it
carries `bb-sandbox`) folds open an editor for what it should mount (NFS or
virtiofs, read-only or not), where the agent keeps its data, packages and
cache stores, and how it is addressed (DHCP, or a static address with gateway
and resolvers). **Save** keeps that on the node's record; **Apply storage**
and **Apply network** each queue a `system` job the agent runs as root
through the same `bb-sandbox` verbs the console uses, so the two can never
disagree about what the machine is configured to be. Every desired mount says
what the node reports for it — mounted, not mounted, not applied yet, or
mounted from somewhere else. A network change is the one that can cut the
cord it arrives on, so it is applied with a three-minute dial-back: the node
re-addresses itself and must reach the controller from the new address, or it
puts the previous config back on its own and says so when it reconnects.
Network changes need netplan on the node, and the job says so where there is
none. Nothing here is offered to an ssh node or to local.

**Building there.** A project names its node in its settings dialog — one
node for everything it does off this box: containers, builds, tests, CI and
emulation — and gives its build and test commands and the output globs. `bb build`, `bb test` and `bb run -- CMD` snapshot the working
tree here, dirty edits included, run on that node in a workspace of the job's
own, and stream the log back; what the outputs match comes back into `dist/`
by name with a provenance record beside it, which the Artifacts tab shows on
the row (which job, which node, which snapshot). A failed build keeps its
workspace on the node for a look, and says where. The census reports each
node's cache size beside **Clear cache**, and the Tools tab gains a node
picker: installing a toolchain there is a job that carries `bb` and the
catalog to the node's own packages store.

**Compose runs on the node, not from here.** A dev instance's Up, Down,
Rebuild and Remove are executed by the agent with the node's own docker: the
dashboard sends the plan and the compose file, the node runs it. So an
enrolled node needs nothing but the token it enrolled with — no ssh key, no
open daemon port, nothing dialling in. (A node added as a plain `ssh` docker
host, the arrangement from before the agent, still runs compose from here
over ssh.)

**A CI runner per node.** The same fold installs GitHub's Actions runner
on the node as a service: it registers with the org or repo URL from the
controller's environment (or one typed there), a token the controller mints
for the hour, and labels `builderbot, self-hosted, linux, <arch>, <node
name>` plus any extra — so a workflow's `runs-on` names the node it should
land on. The row says whether the runner is listening or busy; Remove
deregisters it first. `bb ci-labels` lists every label the registry knows
and `--write` regenerates `.github/actionlint.yaml` from them, so the lint
checks `runs-on` against runners that exist. The container's own runner
stays until a node runner has taken a real job.

**How an instance is reached.** Each running instance on the Docker manager
carries its route: the URL, and a picker for the mode. **lan** is the
published port at the node's own address, what the manager always linked.
**funnel** is Tailscale Funnel on the node — a public https URL at the node's
MagicDNS name with no DNS, certificate or firewall change — applied by the
agent, so it is offered only on an agent node that has tailscale logged in;
the row says *asked for* until the node reports the funnel is up, and
switching back to lan closes it. **public**, a reverse proxy with a wildcard
record, is named in the picker as not built so the third mode is visible for
what it is (docs/nodes.md §7).

### The Jobs tab

**Tools → Jobs** is the queue (docs/nodes.md §2, phase 4): everything the
controller has taken — a compose action on a dev instance, an exec on a node,
an agent self-update — with where it was placed, what it is doing now, how it
ended and its log. A job is placed on a node named outright or on whichever
node fits a selector (capability, labels, pool, OS, architecture), and the
choice is frozen on the row when the job is taken; a selector nothing fits is
refused when it is queued, naming the selector. Each node runs as many jobs at
once as its row allows; the rest wait in order. **Cancel** on a row stops one
where it is — a queued job never starts, a running one is killed and the row
moves when the runner reports that it did — and nothing edits a job after the
fact. The checkbox in the bar narrows the list to what is running or waiting.
`bb jobs` prints the same list read-only, so a session can see what became of
the work it asked for. `/api/v1/healthz` answers without a credential with
the queue's counts, and `/metrics` answers with one in Prometheus text.

### The Settings tab

The gear in the header keeps what belongs to this **browser** — theme and
layout — and one entry, **All settings…**, opening the Settings tab: what the
**controller** owns and can apply live. The session-log policy lives there
now, the node-flavored settings land as their phases do, and the tab says
plainly what still comes from the environment and why (the placement rule and
the unhardwiring are docs/nodes.md §13 and §11).

Each row folds open to show what that container publishes and what it mounts,
read only when you open it — parsing a compose file is the one thing the page
deliberately does not do for every row at once. Lines wrap rather than scroll:
a host path is long, and a row that scrolls sideways on a phone hides the half
you were reading.

**A long build says what it is doing, and can be stopped.** The command's
output is streamed into the row as it arrives rather than handed over when it
exits, so a `compose build` spending four minutes pulling layers is not four
minutes of a spinner. The phase word above it still says *building* or
*starting*; the tail below says what the phase is spending its time on. It is
raw and deliberately not parsed into a bar: docker rewrites a line per layer
per tick, and turning that into a percentage is the thing the packages tab
already gave up on.

**Abort** sits beside it while a job runs, and asks nothing first. Stopping a
build is not destructive — what is already built is kept, exactly as a failed
build's work is — and the signal goes to the process *group*, because a compose
CLI waiting on a pull leaves the download running if only the CLI is asked to
stop. The row then says how the job ended rather than silently reverting to
whatever state it was in.

**New container…** on that tab runs something with no project behind it: a
name, a compose file and an environment, which is the shape Portainer's stacks
and Dockge use. Labels are not a fourth box — in compose they belong in the
YAML. The compose file is checked by compose itself before it is saved, and
kept in `/config/containers/<name>/` where no project scan can see it; its
relative bind sources resolve against its own data directory under `/devdata`,
which is a path the daemon has — this container too where the share is
mounted here, and only the sandbox where it is not. Removing one takes its files
with it, because its compose file *is* the thing.

It lists what has been sent to it, not every project that could be sent: a
project with a compose file does not appear there until you send one, and
**Remove** takes a container down and drops it from the list again. Removing
keeps its env file and its data directory, so sending it again under the same
name finds them — and the project's Artifacts tab is untouched either way,
which is where it comes back from.

The same tab lists every container on the picked node's daemon — not only the ones this
dashboard started. A port taken by something else is exactly what you open a
list like this to find out about, so the others are shown and marked *not ours*
rather than hidden. It is a read: `docker ps` is one of two verbs the dev
instance's guard allows outside compose, and nothing on the tab acts on a
container.

- a rendered **findings report** — the SARIF your scanner drops in `/reports`,
  grouped by project and rule, with severity counts and CVEs linked to NVD.
  Project groups start collapsed — the severity pills on each are the overview,
  and what you open stays open across reloads. If the scanner re-runs while
  the report is open, the view reloads itself — the page watches the report
  files' mtime, so you never triage stale findings. The sidebar card carries
  the headline: one row per project with its counts by severity, so "whose
  code, how bad" is answered without opening the report. Both leave out
  projects with repo errors — those get fixed in the Projects card first, and
  a *locked* one is not in that category — and the report says how many
  findings that held back
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

**A terminal tab closes itself when its session ends.** `bb-tty` execs claude,
so the pane's process *is* the conversation: exit it — Ctrl+C twice, `/exit`,
Ctrl+D, or a crash — the tmux session goes with it, and the tab closes rather
than holding a dead terminal until somebody presses ✕. Shells too: one you
typed `exit` in is just as dead.

Nothing is lost by closing it. The transcript is on disk and the project's
Claude button offers to resume it, which is a better way back than a corpse in
a tab — the row knows the transcript id and the dead tab does not.

The rule is *seen alive, then gone*, and the transition is load-bearing: "has
no session" is also true of every tab restored from a saved layout before
anything has started, and of all of them for a moment if a poll ever comes back
empty. Reaping on absence would wipe the strip at every boot.

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
- **Static analysis** on the Tools card opens the **Analysis** tab — the
  whole report, a project selector, and a filter bar (level, free text) — a
  *document* tab, not a terminal. It is a report to read; putting it through a
  PTY would only make it harder to. The notebook's own Analysis view is the
  same report already narrowed to that project. With nothing readable in
  `/reports` the button is **ghosted** and says which of the three reasons it
  is — no mount, nothing in it, or nothing in it that parses — and a tab
  restored from a saved layout is closed once, on the load that finds out,
  rather than left open to say "nothing here"
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
under its tab strip: **Memory** (what Claude remembers here), the **Roadmap**
(the shared list of design work and ordered plans), **Bugs**, and **Analysis**
(the scanner's findings for this project alone).

**Unsaved work does not cross those four.** Leaving a view asks, and answering
yes throws the change away rather than carrying it to the next tab.

**A History, and the changelog, open over the panel rather than in place of
it** — a large box on a desktop, the whole screen on a phone. They are things
you *read*, so the list you are reading them against stays behind them, and
**Close**, Escape or a click outside puts the log back where it came from.
What goes into the sheet is the real element,
moved — so the filter bar keeps every handler it had and there is no second
copy of it to drift.

**It opens on the first tab of the strip** — Memory today, and whatever is
first if the strip is ever reordered, since the default is read off the strip
rather than marked on one of the buttons. After that it stays where you left
it: the notebook is one instance per project, parked and reused, so going off
to a terminal and coming back finds the view you were on. Closing the tab ends
that instance, so the next open starts at the first tab again — which is the
same rule that makes closing it drop whatever was staged in it.

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
but outstanding work. **A ticked-off item comes off it** — a list is read to
find out what is left, and a thing that is finished is not left. `bb roadmap
done N` moves it into the log under *done*, where `rm N` would have put it
under *dropped*; both leave, and the log says which happened. Only a session
ticks things off, because only the session that did the work knows.

**The strike icon is only ever an undo.** It appears on a line that *has* been
sent, to put it back so it can go again — there is no crossing one off by
hand, because "I crossed that off" is not the same claim as "that is done". A
line you handled yourself gets dropped, and its words stay in the log to be
retyped if you were wrong.

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
`bb roadmap step add|edit|rm|mv|done`, `bb roadmap mv N up|down` — which matters when the design moves under a plan
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

**Done is the session's mark, and it is a different one.** A session that
finishes a step says so with `bb roadmap step done N M` — the step it was
sent, or one it was told to go ahead with in chat, which used to have no mark
at all. The line is struck the same way but wears a tick instead of its
number, the frontier moves past it, and the log says a session finished it
and when. Only a session sets it, as with ticking off an item. Sending a done
step again is the override: the mark comes off, and the log shows the send
after the finish.

**The order that is protected is the order things are sent in**, and nothing
else. Only the frontier step of a group arms, and the group's own arrow stands
for that same step — so a plan cannot be handed over backwards, which is the
mistake that actually costs something: step three landing on a tree step two
was supposed to have made.

Editing is not constrained the same way, deliberately. The pencil rewords any
row, and the **bin is on every row** — item or step, anywhere in a plan, so a
stale step three does not cost you steps one and two to reach. A deletion
cannot send anything out of order. It can only make a plan shorter —
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

The box sits **under the line it would send**, not at the foot of the panel,
where on a phone it would be a screen away from the line it is asking about.

**A note can ride with it.** The box carries a field for anything to send
alongside — "the select is the one on the left" — and it goes on the *same*
line as the step rather than as a second message, for the reason two messages
never work here: the second lands glued to the first. It is cleared once the
step has gone, where the pickers stay: a note belongs to the one thing it was
written for, and finding it still sitting there on the next step is how it
gets sent twice.

**Model and effort** are not questions in that box and are not applied by it.
They are the project's own setting, at the bottom of its **settings dialog**
(the gear on its row), and `bb-tty` passes them as `--model` and `--effort`
when it starts a session there — so a session that is up is already on them
and a send is only ever the send.

A launch flag rather than a `/model` typed ahead of each message, for two
reasons: claude puts a confirmation behind that command, and a dialog is
exactly what "the pane has stopped changing" looks like — and it saves the
switch as the default for *new* sessions, so a per-project pick would leak to
every project.

**Changing it while a session is running restarts that session**, and the
dialog says so before you save. The restart is `tmux respawn-pane`, so the
browser stays attached and the pane simply comes back: the launcher re-reads
the setting and resumes the newest transcript, which continues the
conversation on the new model rather than replacing it. Anything mid-turn is
lost, which is the whole reason it asks. *Leave as is* passes no flag, and
claude uses its own default.

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

**The dev instance** heads the list, shaped like every other row in it — the
kind on a pill (`docker`, where a file says `apk` or `xpi`), the compose
project's own name in bold, and whether it is `(running)`, `(stopped)` or
`(down)` in parentheses after it, where a file carries its size and age. The
name is the compose project's rather than a container's: a compose file may
set `container_name` to anything it likes and may declare several, and this is
the one name that is always true of all of them.

Under it, and not behind a fold, are **what it publishes and what it mounts,
written the way Unraid's own Docker tab writes them** — container side
on the left, host side on the right, and the arrow saying which way it goes:
`/library ← /mnt/user/plex-media` for a read-only mount, `↔` for a writable
one, `7474:TCP ← 192.168.1.15:7475` for a published port. That is deliberately
not a second notation to learn; it is the one already used for every other
container on the box. All of it is read from the *resolved* compose config, so
a path or a port assembled out of variables shows as the value compose arrived
at rather than as the spelling — which is also how the checks below can judge
a mount without knowing anything about the variables that built it.

A running service gets **Open** beside its buttons. One published TCP port
links straight there, pointed at this page's own host; several open a chooser
listing every `host:port` for you to pick from. Unraid does not discover this
either — its tab reads a `WebUI` line somebody wrote into a template, or the
`net.unraid.docker.webui` label — so one port is the only case where it can be
known rather than asked, and asking beats guessing for the rest.

The mounts are not repeated in the warnings below. They are all on the row
already, with the path each one lands on, so naming the ones that reach past
the project restated what was two lines above in worse words. What the
warnings keep is the set that is invisible otherwise: `privileged`, added
capabilities, host devices, and the host's process or network namespace —
the flags that make a container more than a container. It appears when the project
carries a compose file
and the project's node is the [sandbox VM](docs/sandbox-vm.md) — a machine
whose only job is running Docker, which is what keeps all of this away from
the server's real containers: the project's compose app, built over there and
controlled in the file rows' own language. **Up** and **Down** are compose
against the project's own file, under a compose project named for the
instance. **Env** edits the
instance's env file — kept in `/config/devenv/`, never in the repo, handed to
compose as `--env-file`; Up stays dead while the repo's `.env.example`
declares keys the env does not answer, because starting a service against an
env known to be missing is a crash with extra steps. **Rebuild** un-ghosts
when the code has moved since the last build (a new commit, or a dirty tree)
and runs build → down → up — unless the rebuild finds new settings in
`.env.example`, where it stops after down, rewrites the env as the new
example with the old values preserved in comments, and leaves Up for the
operator. Before the first build the button reads
**Build**, and nothing is built until it is pressed. A compose that
references `${BB_DEV_DATA}/...` gets its volumes on the cache drive by
convention — in a per-instance directory the VM makes itself, so that share is
mounted over there and needs no mount here at all. BuilderBot itself gets the
row too, as a second container on another machine, never the one you are
using; expect
`up` to refuse while the real one holds the same host ports, which is the env
file's job to change.

**The daemon's filesystem is not this container's**, and that is the one thing
about a remote daemon easy to forget and impossible to see: a bind mount's
*source* is resolved by whoever runs the container, which is the host.
`/workspace/alpha` and `/devdata/alpha` mean something here and nothing
over there — and docker answers a missing bind source by creating an empty
directory and mounting that, so on Unraid, whose root filesystem is RAM, the
result is an app that starts with no data and loses it again at reboot. It
reads as a bug in the app. The node's path mapping states it once — the
same one you made when you mounted the volumes — and BuilderBot both hands
over host paths (that is what `BB_DEV_DATA` now carries) and names any of a
compose file's *own* paths the host will not find, on the row, before you
press Up. Absolute host paths, which is what a working compose here already
writes, are unaffected. Build contexts are unaffected too: the classic builder
streams those from this side.

The boundary is the machine: a VM holding nothing anybody minds losing. What
the code adds bounds the **shape** of what gets sent rather than what it may
reach — every docker call goes through one function, which refuses any argv
that is not a `compose` call carrying a `--project-name`, two reads (`version`
and `ps`), or one of the three one-shot commands that tend the dev-data
directory, recognised by rebuilding the exact argv rather than by allowing the
verb. So a bug in a caller cannot become a freeform docker call. The **compose file** is the other half, and the one no
check on a NAME can bound: a file that says `privileged: true` and mounts `/`
produces a container named as innocently as any other. So it is read before anything
starts, and `privileged`, host `pid`/`network_mode`, and bind mounts landing
outside the project and `${BB_DEV_DATA}` are named on the row and put in a
confirmation. Confirmed once per set rather than per press — an
acknowledgement given every time is one nobody reads — and asked again the
moment the file reaches for something new. It warns rather than refuses: a
legitimate compose may genuinely want a host path, and nothing here can tell
which.

**What a container is called** is what you called it — `radarr`, not
`bbdev-myproject-radarr`. The daemon is a machine with nothing else on it, so
there is nothing to keep a container out of the way of, and a name that is
three words of ceremony in front of the one you typed is only harder to find in
`docker ps`.

**Migrate** appears on a row whose things are still under a name it used to
have — an instance made when names carried a `bbdev-` prefix, which they no
longer do. The containers, the env file and the data directory are all keyed by
that name, so the row says which old name is still holding everything and
offers to move it.

Never automatically, and never while anything is up: renaming a directory out
from under a running container leaves it writing to a path nothing will look at
again, so the button is dead until you take it down. Nothing is copied and
nothing is deleted — the env file and the data directory are renamed, and the
old names are what to rename back to if it goes wrong. The old name is found by
its tail rather than by remembering, so nothing has to have been recorded for
an old instance to be found.

**Bind directories are made before anything starts**, as a step of Up and
Rebuild rather than a button somebody has to remember. A compose file names
directories that have to exist, and docker creates a missing bind source
itself — as root, then chowning it — which on a share that squashes root fails
and takes the whole run down with *operation not permitted*, leaving the
directory behind so the second press works: an intermittent-looking failure
with a fixed cause. So they are made first, owned by whoever BuilderBot runs
as, which is the ownership Unraid expects.

It was a button for one release, and that was a mistake worth naming: a
control you have to press before another control is not a step, it is a trap.
Nothing about it was ever a decision.

Made on whichever side can reach them, which is not something to think about:
a share this container mounts is a local `mkdir`, and anything else is a
one-shot container on the VM — the same mechanism that makes the per-instance
dev-data directory, running as BuilderBot's uid, which is the whole point
since docker's own attempt is as root. Which shares the VM has is the VM's
business: nothing is declared on this side, so a share added over there next
month needs no BuilderBot setting touched.

The one thing it will not create is a bind at a share root itself — there is
nothing below it to make, and docker creating the root is the as-root failure
this exists to avoid. The guard still holds the shape: the argv is rebuilt and
compared whole, the mount must be a single plain-named share root, and every
path in it is plain names only, so the reach stays a `mkdir -p` as an ordinary
user on a machine built to be wrecked.

`mkdir -p` throughout, so one that already exists is left alone and starting
twice does the same thing once. A directory made over there cannot be seen
from here afterwards, so what was made is recorded against the instance. What
could not be made is written into the job log and the compose runs anyway —
letting compose say what actually went wrong beats refusing on this side's
reading of a file compose is about to read for itself.

**A path this container also mounts needs a pair, even on a sandbox VM.**
`/workspace:/workspace` covers the projects share and nothing else. If you also
map the dev-data share here — so you can create a compose file's bind
directories from a shell, which is the usual reason to — then a compose
mounting `/devdata/...` is naming a path BuilderBot has, and it will say so
until the mapping answers for it. `/devdata:/devdata` is that answer when both
machines mount the same share at the same path, which is the arrangement the
sandbox is for. The alternative is to not map it here at all: what BuilderBot
cannot see, it does not check.

**Container names and project names are separate groups.** A project existing
reserves nothing: a container may be called `mediareducer-dev` while a project
is too, because they are not the same kind of thing. The one name that cannot
be reused is another *container's* — two instances resolving to one compose
project name would be one set of containers, one env file and one data
directory with two rows driving them, so the second is refused and told which
instance has it. A project's *default* instance is named for the project,
since nobody typed a name for it.

**Which project a container belongs to is tracked separately**, and is never
read out of its name — it is the key it is stored under. That is what decides
whose Claude session may touch it, so a project can stand up several
containers, name them anything, and still own all of them.

Which compose projects on the daemon are **this dashboard's** is answered the
same way — from what it has stored, not from what things are called. So the
manager can list every container on the VM, including ones you started by
hand, and still be right about which of them it is driving.

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
`bb findings` reads the same digest in a terminal, and the Tools card's
**Static analysis** button opens the whole report as the Analysis tab, with a
project selector and the same filter bar. Findings whose paths
resolve into anything other than a **valid** project — one that is listed and
free of error-level issues; a locked one still counts — are set aside rather
than shown as "unattributed". The label is reserved for paths that genuinely
place nowhere, which is the case worth a look.

That rule is a subtraction, and deliberately so: rather than recognising each
kind of thing that is not a project, findings attribute only to the projects
worth reading them for, and everything else in the share falls out together.
It matters because of how the SDK share is mapped here — beside the projects
folder in the same development share, so the host's scanner walks it like
anything else and one report grew nine thousand findings for a pile of
downloaded toolchains.

**The subtraction alone stopped being enough when `/workspace` stopped being
the whole share.** Pointing it at the projects folder — a better arrangement,
and the one that cut most of this noise — put the SDK share *outside* the
directory being subtracted from, and 267 trivy findings about vendored
Flutter, Go and Android toolchains went straight to "unattributed": improving
the layout regressed the classifier. So the wider question is asked as well.
`/proc/self/mountinfo` says what this container mounts from beside its own
projects folder —

```
/development/projects -> /workspace
/development/SDK      -> /sdk
```

— so `SDK` is known to be a share rather than a project, wherever the shares
are moved to next, and still without a list of what to skip. A name that is a
valid project is never taken this way, whatever it is mounted from: an
appdata directory called `BuilderBot` would otherwise teach it to ignore the
BuilderBot project's own findings, which is the one mistake here that hides
real work instead of noise.

**A report a whole cycle behind its siblings is not counted**, and the
Analysis tab's footer says which and by how much. A scanner that dies leaves its *previous* report in
place — a host script worth having does not overwrite a good report with
nothing — so a dead scanner and a live one are the same file to everything
downstream. On 28 Aug a trivy that had been crashing for four days was still
supplying most of this box's findings, against a directory layout that had been
changed in between: the scanner's volume was fixed, the numbers did not move,
and the fix looked broken. `bb findings` leaves the same file out and says so,
and reads it anyway if you name it on the command line.

A day is the line, and the size is the argument. One scan run writes every
report within minutes of itself, so anything measured in hours is the same run
— and re-running *one* scanner by hand, the obvious thing to do after fixing
one, must not blank its siblings. A report left behind by a failed scanner is
behind by a whole cycle, which for any cadence anybody runs is more than a day.

**The row names what it could not place**, commonest first — `file:/src × 9`,
which is mobsfscan reporting its own container path. A bare count said
something was wrong and nothing about what, which is how it sat in the
hundreds through several passes when 267 of them were one share and 9 were a
scanner's configuration. A
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
box the roadmap opens under a step — the same note field for anything to send
with it — opened under the report instead. Nothing is switched on the way in:
the session is already running on the project's own model and effort.

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

The list lives in `/config/todos.json`, beside the tab strip and the locked
projects — deliberately **not** in the repository. A list like this churns far
faster than commits, and a checkbox tapped on a phone should not turn into an
uncommitted change. Anything that deserves to be permanent graduates out of it:
into `CLAUDE.md`, a commit message, or a test that fails when it regresses.
Thirty open items is the ceiling, because the list is read at the start of
every conversation and one nobody can take in at a glance is one nobody reads.
Ticked items stay a week, then go.

- **Ending a session for good is the ✕ in the Sessions list**, under the
  terminal. That one asks,
  because that is where something is actually lost: the shell and everything
  in it, or the Claude conversation (its transcript is kept and can be resumed).
- **Switching between terminals is instant**, because a pane keeps the last
  three of them loaded behind the one on screen. Rebuilding the pane instead
  would throw the frame away, and the terminal is 700KB of JavaScript that
  then has to parse, open a websocket, attach to tmux and draw — a second and
  a half of blank pane on a phone, every switch. The frames sit exactly on top
  of one another at the same size, which is not just tidiness: a hidden frame
  is still an attached tmux client, and tmux sizes a window to its smallest
  one, so different geometry would mean the terminals fighting over the width.
  The fourth reloads — the ceiling is there because each
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
  Under the terminal sit **Keys**, **Commands** and **Sessions**. Keys is the
  phone's alone — a desktop has a keyboard, so it carries no on-screen one at
  all. One flyout at a time on a phone, because there is not the height for
  two, and a flyout that has done its job gets out of the way: picking a
  session or sending a command closes it. Which of the two
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

They live under the terminal rather than in the sidebar, at every width:
**Commands** and **Sessions** in the bar below the panes, opening a flyout
over the terminal they act on. On a desktop it really is *over* — the panel is
an overlay and the terminal keeps its height, because a resize costs a terminal
a refit and a reflow of everything on screen, which is a lot to charge for
looking at a list. A phone pushes the terminal up for it instead, there being
no screen to spare for covering one thing with another. Both slide. That is where they belong — a command list is
about the shell in front of you, not about the box — and it is also what keeps
the sidebar to seven cards you can read instead of twelve you scroll past. On
a wide screen the buttons sit at the bar's left edge and the flyout is capped
rather than stretched: a short list read across two thousand pixels is worse
than one read in a column.

Nothing about the graying-out below depends on where they live. It is computed
from the *active pane* — which is why the same markup served the phone's bar
and the desktop's cards for as long as it did.

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
same. If the list outgrows its space it is cut off at eight with a **Show all**
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

Two more lists flank the `bb` one in the same flyout, following the same
rules. **Linux commands** is the general toolkit — `ls -lah`, disk usage here and per mount,
memory, the biggest processes, listening ports — live on any shell tab. **Git
& GitHub** shows its commands verbatim (`git status`, log, diff, branches,
fetch, pull; `gh pr list`, `gh run list`, …) and ghosts against the directory
the active shell is *in*, not just whether it is a shell: outside a git
repository the whole list grays out, and in a repository whose remotes do not
include GitHub, just the `gh` half does — the hover text says which it is.
The verdict follows a `cd` on the next status poll, and the ghosting only
reflects the repo; `gh` itself still needs its own auth (a session-visible
`GITHUB_PAT` or
`gh auth login`) to answer.

### Your own commands

**Custom commands**, the last section of the same flyout, starts empty with a **+**. It takes a title and a
box of command lines, and the button it makes types those lines into the
terminal you are looking at, in order, exactly as if you had typed them — one
line or twenty. The pencil beside each one edits or deletes it.

Long titles are cut with an ellipsis so the list keeps its shape; hovering shows
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
no git token here there is no API to ask either, so *"CI is red, why?"* had no
answer in here for a job that ran in this very container.

So the lint workflow archives its own output — and so does the `dashboard
tests` workflow beside it, which carries the browser suite: each check is
teed into
`/config/ci-logs/<repo>/<run-id>-<attempt>.log`, with a header naming the
commit, ref and event, and a `result:` line written by an `if: always()` step
so a job that died still says so. `bb ci-log` prints the newest, `--list` shows
the twenty kept with their results, and a run id picks one.

Two details that are load-bearing. The job sets `shell: bash` rather than
taking the default `bash -e`, because the difference is `pipefail` — without it
the tee's exit status becomes the step's and a failing linter reports success.
And the logs live in `/config` rather than `/tmp`, because a log that vanishes
with the container is no use for the question *"what broke while I was away?"*.

The image build is the exception that proves it: it runs on a hosted runner, so
nothing it prints is reachable from in here. Its last job comes back to this
box — `runs-on: [self-hosted, builderbot]` — and archives the *outcome* into the
same directory: result, trigger, version, digest, how long it took, and whether
the layer cache was used. Not the console output, which is gone; enough to
answer "did that build land, and why did the host re-pull a gigabyte?".

### Catching up after time away

Two things are recorded for no other reason than that a later session will
want them, and neither can be reconstructed afterwards.

The first is which images this container has actually run. It is recreated on
every update, so its own stamp answers only *what is running now*, the boot log
rotates away after a few starts, and with no PAT there is no registry to ask —
which leaves *"which build was the box on when I saw that?"* unanswerable, and
that is the first question whenever a fix appears not to have landed. So the
entrypoint appends a line to `/config/image-log.tsv` whenever the stamp differs
from the last one: first-seen, commit, version, build time. A restart writes
nothing; a rollback writes a line, which is the point.

The second is `bb catchup`, which reads both of those plus git and the
notebook's own logs and prints one screen: the image this box is running and
how far behind `origin/main` it is, recent commits **with the first line of
each body** — the line that says *why*, which `--oneline` throws away — what
moved in the roadmap and the tracker, and the builds archived above.

It is deliberately a pull and not a ritual. A session's prompt already carries
the roadmap and the open bugs, paid for on every conversation in the project;
most conversations never ask about last week. Reach for it when the first
message refers to history — *"it finally built"*, *"is that still broken?"* —
which is exactly when the alternative is four or five commands.

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

### Push rights

A clone is read-only unless you tick **I want to push to this repository**, and
that decision is made once. Three rules, all deliberate:

- **It cannot be turned off.** A working copy that could push yesterday and
  cannot today explains nothing to whoever is standing in it. Deleting the
  project is the way out — which never touches GitHub.
- **One project per repository.** Two working copies pushing to one remote is
  how a branch ends up racing itself, and here both may be the same session on
  different days. Deleting the holder frees it.
- **The token is checked first.** Before the clone starts, GitHub is asked
  whether that token can actually push to that repository — a missing scope
  otherwise surfaces days later as a failure with nothing connecting it to the
  box you ticked. A deploy key cannot be checked this way short of pushing, so
  it is taken at its word.

Enforcement is a `pre-push` hook, which is transport-agnostic — it catches an
ssh push through a deploy key exactly as it catches an https one — and refuses
with a sentence rather than an auth error. Like the sibling-project rule it is
a guardrail, not a sandbox: a shell in the container can delete it.

Projects that already existed when this arrived are granted retroactively if
their GitHub remote is an ssh one, recorded as `key`. Those are the repos that
were already being pushed to with deploy keys, and a new rule is not a reason
to take away something that worked. https remotes are not seeded: those
authenticated with a container-wide token, and one of their own is
the way back.

### An access token for one project

Cloning a private repository asks for an optional **access token**. It is
written in git's own credential-store format to `/config/gitcreds/<project>`,
mode `0600`, and named from that repository's `.git/config` and nowhere else —
with git's empty-value reset ahead of it, so the globally configured helper is
never asked and no container-wide token authenticates the fetch.

That last part is the point. A token minted to reach one private repo usually
reaches every repo it was scoped to; in the environment it also reaches them
from every project and every session. Here it opens the one project you gave it
to, and renaming that project takes it along.

A project that already has push rights can be given a token from the **rename**
dialog — including one that pushes with a **deploy key**. Setting one there
does not switch anything by itself: git never asks a credential helper about an
ssh remote, so a project with an `ssh://` or `git@` origin goes on using its
key however many tokens are stored for it.

The **Authentication** segment beside that field is what changes it. Three
answers, not two: *Disabled*, *Deploy key* and *Access token*. It shows which
one the remote actually reaches for and lets you move between them; the change
is applied when you press Save, which is also how a token typed in the same
dialog gets written before the switch that needs it. Under the hood it is one
`git remote set-url`, between `git@…:owner/repo.git` and
`https://github.com/owner/repo.git`, plus the credential helper.

*Disabled* is a real answer rather than the absence of one — the remote keeps
its https form and the helper comes off it, so a push is refused instead of
quietly falling back on whatever else git can find. It is also what makes the
dangerous case sayable: **clearing a token while the switch still says
*Access token* is refused at Save**, in those words. The pick is left exactly
where you put it and the reason is stated, rather than sliding to another mode
on your behalf — being corrected without being asked is how you end up on a
credential you did not choose.

**A stored token is closed, not shown.** Only its file has the value, so the
field cannot be pre-filled and typing over an invisible one is how a working
credential gets replaced by accident. It is disabled, with **Clear the stored
token** under it: pressing that opens the field for a new one, ghosts the
*Access token* side and puts the choice back on *Deploy key*. Like everything
else in this dialog it is staged — the project changes when you press Rename,
and the link offers the way back until you do.

Clear the only credential a project has and both sides go quiet, with a line
saying it cannot push to GitHub and that everything else — commit, branch,
build — still works locally. The field stays typeable there deliberately:
ghosting it would be tidier and would leave no way back to pushing.

**Switching removes neither credential.** The token file stays in `/config`,
the deploy key and its `~/.ssh/config` alias stay where they are, and the
repository keeps its credential helper — an ssh remote simply never consults
one. So going back costs nothing, and the exact alias is restored rather than
guessed, because the alias is named after the *key* and there would be nothing
in the project to guess it from. A side you cannot take is shown disabled with
the reason: a project with no token stored, or one that has only ever been
https and so has no key remote to return to.

**It is not shielded the way a deploy key is.** Those are served by a root-owned
agent and cannot be read at all. This is a file owned by the same user your
shells run as, so a session with Bash can read it. Better than an environment
variable every process inherits, and not a secret store — for a repository
where that matters, use a deploy key.

### Locking a project

The **padlock** on a project row is the one gate there is, and it carries the
whole meaning: no session, a read-only notebook, no CLAUDE.md.

The list lives in `/config/locked-projects.json`, so it survives restarts and
image updates, and it is enforced by the terminal launcher and the server
rather than the page — the ttyd URL is reachable on its own, and so are the
API paths, so a rule only the UI honored would be advice. Locking a project:

- refuses `claude:<project>` at launch, with a message saying why
- ends any Claude session already running there, rather than taking effect
  "next time"
- makes its notebook **read-only** — the roadmap, the bugs and the memories
  open and cannot be changed, by you or by anything else
- refuses to write a `CLAUDE.md` into it, so the `no CLAUDE.md — create one`
  line stays as plain text rather than being an offer

**What it deliberately does not touch is everything you do yourself.** A locked
row is not folded away and not grayed out — it is a project you are actively
running, and dimming it would say the opposite. A closed padlock sits after the
name so the row reads *"StreamLift, locked"* without hunting for which of six
icons is lit, and:

- the **shell** still opens, which is how you go and look at it
- its **static analysis** is still counted and still opens on the Analysis
  view, with its history: locking says who runs a project, not whether its code
  is worth knowing about
- its **artifacts** are still listed, and a **dev instance** still builds and
  runs — that is usually the reason a project is locked in the first place
- the **version** block, the settings dialog and the rename all still work

One limit worth stating, because it is the same one the sibling-project rule
carries: this stops a session **starting here**, and the file tools are already
denied on every project but a session's own. It is not a sandbox — a session in
another project can still reach this directory through Bash.

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
dashboard relays `/term` to it, so the browser asks for credentials once and
the router needs one port. The relay is deliberately dumb: after checking the
session it splices the two sockets byte for byte and never parses a frame, and
credentials are checked in one place — the cookie or basic auth this server
already verifies. curl and scripts can skip the
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

**One file per container start, per stream.** All four rotate together on
boot, so a generation number means the same boot in every one of them, and
`.1` is the previous run of the container.

| Log | Where |
|---|---|
| Startup, the runner supervisor, and every later warning | `config/logs/builderbot.log` |
| The dashboard server, in full | `config/logs/dashboard.log` |
| Every compose call the Docker manager made | `config/logs/docker.log` |
| The terminal server | `config/logs/ttyd.log` |
| Runner diagnostics | `work/_diag/` |
| CI job output | GitHub → Actions → the run |
| Emulator | `home/.android/emulator.log` |

All of them persist across updates, are secret-redacted, and move together to
the `/logs` mount if you map one.

**Start with `builderbot.log`.** It used to end when the startup hooks
finished, so anything that broke an hour later was in a different file that
nothing pointed at. The dashboard's output is now split as it is written: all
of it into `dashboard.log`, and the warnings and errors copied into the boot
log as they happen. So the session's story is in one file and the detail is
next door — including a failed compose call, which the Docker manager reports
in both places.

**Kept for a number of days, not a number of boots.** Thirty by default, set
in the dashboard's settings menu — the gear, beside the colour schemes. A
count was the wrong unit for the question anybody has (*was that this week?*)
and a container in a crash loop can burn five generations in a minute;
`BB_LOG_KEEP` survives as the ceiling for exactly that case.

**Apply crops.** Lowering the number deletes what it already excludes, then
and there, rather than waiting for the next boot — which is why it is a button
and not a field that saves itself: a number input fires `change` on its way
through every value the keyboard passes, so typing `30` over `300` would have
pruned at `3` in passing. Pressing it without changing anything is a
crop-now, which is the other thing you sometimes want. The same menu
downloads this session's logs as one file, or everything kept as a `.tar.gz`,
and clears the kept generations without touching the ones being written.

Two deliberate omissions from *this session*. `ttyd.log` is the terminal
server's connection churn — 22,000 lines against 4KB of boot log on this box —
so it is in the archive and not in the thing you open to read what happened.
And the **CI logs stay where they are**, under `config/ci-logs/<repo>/`, one
file per run: a CI run is not a container session, it belongs to a workflow
run and spans whatever session was up. They are already grouped the way you
would want and `bb ci-log` reads them by run id — what was missing is that the
settings menu did not know they existed, so they are in the archive and under
the same retention now.

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
  lib/docker-probe.py            which daemon is live, for `bb doctor` and the boot log
  lib/log-split.sh               splits a long-running process's output: all of it to its own file, warnings to the boot log
  lib/embedded-shell.py          pulls scripts out of quoted heredocs so `bb lint` sees them
  startup.d/*.sh                 startup hooks
  dashboard/                     web dashboard: server.py, index.html, bb-tty
    packages.py                  everything behind the Tools tab: catalog, sizes, the job worker
    memory.py                    everything behind the memory book: what Claude remembers per project
    projects.py                  new project / link to GitHub, and the worker that clones and pushes
    logs.py                      what is kept, for how long, and the downloads behind the gear menu
    todo.py                      the roadmap; `bb roadmap` drives the same file
    nodes.py                     the node registry, audit trail, SQLite store, the job queue and the agent's channel (docs/nodes.md)
    jobs.py                      the controller's own job runner — exec here or over ssh — plus /healthz and /metrics
    migrations/                  numbered schema files for /config/builderbot.db, applied at boot
    bugs.py                      the bug tracker; `bb bug` drives the same file
    notebook.py                  one batch over both of those, so half of one cannot exist
    notify.py                    getting a line into a running Claude session, and knowing it landed
    signin.py                    the Claude sign-in, under a pty rather than in a terminal
    test/                        its Playwright suite — `bb dashboard test`, isolated
  agent/builderbot-agent.py      the node agent: one stdlib file, served to nodes by the dashboard
vm/provision.sh                  turns a Debian/Ubuntu VM into the Docker sandbox, and enrolls it as a node
config/skel/                     home directory skeleton
config/packages.json             the packages the Tools tab offers, and how to install each
config/templates/                project CLAUDE.md template (shipped in the image)
docs/unraid.md                   step-by-step Unraid walkthrough
docs/sandbox-vm.md               the Docker sandbox VM: why, how, and pointing this at it
docs/nodes.md                    design: controller + nodes, homelab-default and enterprise-scalable
.hadolint.yaml                   Dockerfile lint config, shared by CI and bb lint
.github/actionlint.yaml          this runner's labels, for workflow linting
.github/workflows/               GHCR publish (hosted, cached from :latest); lint + dashboard
                                 browser tests (on this runner); runner smoke test (manual)
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
