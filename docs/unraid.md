# Running BuilderBot on Unraid

Two ways to run it:

* **Option A — Docker template** *(recommended)*: a native Unraid container
  with a form-based settings page and **one-click updates** from the Docker
  tab whenever a new image is published.
* **Option B — Compose Manager plugin**: the `docker-compose.yml` from this
  repo, if you prefer compose stacks.

Pick one — both create a container named the same thing, so don't run both.

Either way, start with the two shared steps below.

---

## Shared step 1: credentials

BuilderBot deliberately uses **separate credentials for separate jobs**, so a
leak of one doesn't hand over the others. Work out which you actually need
before creating anything.

### Which credentials does my setup need?

Find the rows that describe what you want; you need every credential marked in
those rows. Nothing else.

| I want to… | Host GHCR token | Shielded `GITHUB_PAT` | SSH key | `GIT_PAT` |
|---|:--:|:--:|:--:|:--:|
| Pull the image at all — *everyone needs this* | ● | | | |
| Run Claude against the mounted projects, no remote git | ● | | | |
| `git clone` / `pull` / `push` private repos from inside | ● | | ● | *or* ● |
| `gh pr create`, `gh release create` from inside | ● | | ● | ● |
| Run a self-hosted runner for **one repo** | ● | ● | | |
| Run a self-hosted runner for the **whole org** | ● | ● | | |
| `docker build` / push images from inside | ● | | | see note |

### What each one is, exactly

| Credential | Type | Permissions | Lives where |
|---|---|---|---|
| **Host GHCR token** | PAT **(classic)** | `read:packages` — nothing else | Unraid host, via `docker login` (step 2). Fine-grained tokens cannot pull from GHCR |
| **`GITHUB_PAT`** (shielded) | PAT (fine-grained), resource owner = **the org** | *One* permission — see the runner-scope table below | `/secrets/builderbot.env`, root-only. Never visible to sessions |
| **SSH key** | ed25519, **no passphrase** | n/a — access is whatever GitHub grants the key | `/secrets/ssh/`. Loaded into a root-owned agent: usable by git, unreadable by sessions |
| **`GIT_PAT`** | PAT (fine-grained) | *Contents*: R/W, plus *Pull requests*: R/W for PRs | `GIT_PAT` variable. Readable by sessions **by design** — see below |

**Runner scope decides the `GITHUB_PAT` permission**, and it is the only one
that token needs:

| `GITHUB_URL` | Permission to grant |
|---|---|
| `https://github.com/OWNER/REPO` | Repository permissions → **Administration**: Read and write |
| `https://github.com/ORG` | Organization permissions → **Self-hosted runners**: Read and write |

*Metadata: Read-only* is added automatically and can't be removed. Do **not**
add Contents or Pull requests here — nothing in the shielded path uses them,
and workflow jobs check code out with the per-run `GITHUB_TOKEN` GitHub
injects, never with this PAT.

### Three things that trip people up

**SSH authenticates git, not the API.** A key covers `clone`/`pull`/`push`.
It does nothing for `gh pr create`, `gh release create`, or `gh issue` — those
are REST calls and need `GIT_PAT`. If you'd rather open PRs from your desktop,
skip `GIT_PAT` entirely and the ssh key is your only in-container credential,
which is the tightest arrangement available.

**`GIT_PAT` is readable by Claude, and that's unavoidable.** Over HTTPS, "git
can authenticate with it" and "sessions can't read it" are contradictory —
same user, same environment. Only the ssh-agent breaks that tie. Scope
`GIT_PAT` to Contents (+ Pull requests) and it grants no reach Claude lacks
anyway, since it already has read/write on the mounted working trees. Keep
Administration out of it.

**Pushing images from inside** needs the (off-by-default) Docker socket *and*
a classic token with `write:packages`; fine-grained tokens don't cover GitHub
Packages. Enabling the socket is root-equivalent on the host — see the notes
at the end before doing it.

## Shared step 2: log the Unraid host into GHCR

The image auto-publishes to `ghcr.io/stencil-projects/builderbot` on every
push to `main` (plus a weekly freshness rebuild). The repo is private, so the
package is private, so the Unraid host must authenticate to pull it.

In the Unraid terminal:

```bash
docker login ghcr.io -u <your-github-username>
# paste the classic PAT with read:packages when prompted
```

Unraid's root filesystem is rebuilt from flash on every boot, so that login
would vanish on reboot. Persist it:

```bash
cp /root/.docker/config.json /boot/config/ghcr-auth.json
echo 'install -D -m 600 /boot/config/ghcr-auth.json /root/.docker/config.json' >> /boot/config/go
```

> The auth file on flash contains your PAT base64-encoded (not encrypted).
> Scope that token to `read:packages` only, so it can't do anything else.

Create the appdata directories:

```bash
mkdir -p /mnt/user/appdata/BuilderBot/{home,config/startup.d,work}
chown -R 99:100 /mnt/user/appdata/BuilderBot
```

---

## Option A: the Docker template

### Install

Get the template onto the flash drive. The repo is private, so a plain
`wget` of the raw URL returns 404 — pick one of these:

**Copy it over (simplest, no token).** The flash drive is an SMB share. On a
desktop logged into GitHub, open `unraid/builderbot.xml` → **Raw** → save,
then drop it into `\\<TOWER>\flash\config\plugins\dockerMan\templates-user\`
as `my-builderbot.xml`.

**Fetch via the API.** Note this needs a token with *repository contents*
read — the `read:packages` token from step 2 will **not** work (it returns
404, because GitHub answers 404 rather than 403 for things your token can't
see). Use a fine-grained token with Contents: read, or a classic one with
`repo`. Also note `raw.githubusercontent.com` does not reliably accept
`Authorization` headers for private repos; the API endpoint does:

```bash
curl -fsSL \
  -H "Authorization: Bearer <TOKEN_WITH_CONTENTS_READ>" \
  -H "Accept: application/vnd.github.raw" \
  -o /boot/config/plugins/dockerMan/templates-user/my-builderbot.xml \
  https://api.github.com/repos/Stencil-Projects/BuilderBot/contents/unraid/builderbot.xml
```

**Or copy it out of a clone**, if you already cloned the repo for Option B.

Then in the WebUI: **Docker** tab → **Add Container** → in the *Template*
dropdown pick **builderbot**. You get a form with everything already wired:

* the project paths (`MediaReducer-Dev`, `MediaReducer-Stage`, `FreshBoot`
  under `/mnt/user/development`) mapped into `/workspace/…`
* the appdata paths for home / config / runner work
* fields for `GITHUB_PAT`, `ANTHROPIC_API_KEY` (masked), git identity, TZ

Fill in `GITHUB_PAT` (and `GIT_USER_NAME`/`GIT_USER_EMAIL`), leave
`ANTHROPIC_API_KEY` empty if you're using a Claude subscription, hit
**Apply**. Unraid pulls the image and starts it.

### Stopping cleanly before an update

Nothing you care about lives in the container: projects are bind mounts to the
array, and sessions, memory files, logins and AVDs are all on the home volume.
Uncommitted work is not at risk from a restart. Still, a tidy shutdown avoids
two annoyances:

```bash
# 1. Exit any Claude session (in the app, or Ctrl-C twice in a terminal).
#    Transcripts and memory are appended as you go, so at most you lose an
#    in-flight turn — but a clean exit loses nothing.

# 2. Stop the emulator gracefully if it is running. A hard kill can leave the
#    AVD in a dirty state that costs you a cold boot later.
docker exec -it BuilderBot bb emu stop

# 3. Check the runner is not mid-job — a killed job shows up as a CI failure.
docker exec -it BuilderBot bb runner status

# 4. Stop with a timeout that lets the runner deregister.
docker stop -t 150 BuilderBot
```

**That `-t 150` matters.** The supervisor gives the runner up to
`RUNNER_SHUTDOWN_TIMEOUT` (120s default) to finish its job and deregister, but
Docker's own default stop timeout is **10 seconds** — after which it sends
SIGKILL regardless. A plain `docker stop` therefore cuts the graceful shutdown
short, leaving a stale registration on GitHub until it times out server-side.
Unraid's *Check for Updates* button uses the host's configured stop timeout
(Settings → Docker), not this one, so if you update from the UI and care about
clean deregistration, stop the container by hand first.

The consequence of getting this wrong is cosmetic — a phantom offline runner
in the repo's runner list — so it is not worth losing sleep over.

### Updating — the whole point

CI publishes a fresh `:latest` on every push to `main` and on a weekly
schedule. On the **Docker** tab, Unraid's *Check for Updates* compares your
running image's digest against GHCR and flips the container to
**update ready** — click it and you're on the new build. That's the entire
update procedure. Ansible not required.

Template edits (new paths, changed variables) are done from the container's
own settings page (click the icon → *Edit*), and survive image updates.

### The container icon (optional, cosmetic)

The template's `Icon` points at `docs/icon.png` in this repo. While the repo is
private that URL answers **404** to Unraid's unauthenticated fetch, and you get
a placeholder.

You do not have to host the icon anywhere. Unraid keeps two copies of every
container icon and only downloads when **both** are missing
(`DockerClient.php`, `getIcon`):

| copy | path | survives a reboot |
|---|---|---|
| RAM | `/usr/local/emhttp/state/plugins/dynamix.docker.manager/images/<Name>-icon.png` | no — tmpfs |
| disk | `/var/lib/docker/unraid/images/<Name>-icon.png` | yes |

So keep the disk copy warm and the download never happens. Container settings →
**Unraid icon cache** → `/var/lib/docker/unraid/images`, apply, and the
container writes `BuilderBot-icon.png` there on every start — including right
after an image update, which is when Unraid clears the cache and re-downloads.

Two things that will silently defeat it:

- **`Icon` must not be empty.** `getIcon()` returns early on an empty URL and
  never looks at the cache, so a blank field gets the question mark no matter
  what is on disk. The template ships a URL for exactly this reason; it does
  not need to resolve.
- **The filename comes from the container name**, and nothing inside a
  container can see its own container name. If you renamed this container from
  `BuilderBot`, set `UNRAID_ICON_NAME` to match.

The one-time equivalent, if you would rather not add a mapping — just redo it
if you ever recreate `docker.img`:

```bash
docker cp BuilderBot:/opt/builderbot/icon.png \
  /var/lib/docker/unraid/images/BuilderBot-icon.png
```

### Android emulator (optional)

1. Container settings → **Extra Params**: append ` --device=/dev/kvm`
2. Set `ENABLE_ANDROID_EMULATOR` to `true`
3. Apply, then: `docker exec -it BuilderBot bb emu start`

### Web dashboard (optional)

1. Container settings → **ENABLE_DASHBOARD** → `true`
2. **DASHBOARD_AUTH** → `you:a-real-password` — the dashboard will not start
   without this, and says so in the log
3. The two port mappings (`8080` and `7681`) are already in the template; change
   the host side if either collides with something else on the server
4. Apply, then click the container's **WebUI** link

You get container and runner status, `bb` macros as buttons, a rendered report
of whatever SARIF your scanner drops in `/reports`, and a browser terminal with
a persistent tmux session per project. A permanent **workspace** tab sits at
the left; Claude, Shell and the findings report open as closable tabs beside
it, and any tab can be pinned to a left or right pane for a side-by-side view.
A tab's ✕ ends its tmux session; a pane's ✕ only collapses the split.

**Both ports have to be reachable from your browser.** The page is served by
one and the terminal websocket by the other; the terminal is a separate service
rather than something the page proxies.

**On the credential.** This is the same class of decision as the Docker socket.
The terminal is a writable shell inside a container that holds your loaded
ssh-agent and read-write mounts of every project, so anyone reaching it can
push to your repos. On a trusted LAN with a real password that is a reasonable
trade; exposed to the internet it is not, and no password makes it one.

### Static analysis reports (optional)

Running a scanner on the host? Give the container its **output** and nothing
else:

1. Container settings → **Scanner reports (read-only)** → your scanner's output
   directory, e.g. `/mnt/user/appdata/scanners/reports`
2. Apply, then from a project directory: `bb findings`

The read-only mount is the whole design. The scanner binaries stay on the host,
so a session can read what was found but cannot run a scan, change the rules,
or rewrite the report — the container consumes the output and has no path back
to the tool that produced it.

`bb findings` reduces SARIF to grouped markdown with repo-relative paths.
Handing a session the raw file instead would spend most of a context window on
metadata before it reached any code.

### NVIDIA GPU (optional)

1. **Apps** tab → install the **Nvidia-Driver** plugin. This is what puts the
   driver and the `nvidia` container runtime on the host; without it none of
   the rest applies. It needs Unraid 6.9 or newer.
   ([unraid/unraid-nvidia-driver](https://github.com/unraid/unraid-nvidia-driver)
   — originally *ich777*'s, since adopted by Unraid, so you may see either name
   attached to it.)
2. Container settings → **Extra Params**: append ` --runtime=nvidia`
3. Set `NVIDIA_VISIBLE_DEVICES`. `all` is fine for a single card. With more
   than one, use the GPU UUID — **Settings → Nvidia-Driver** lists them, in the
   form `GPU-7f326d12-d4c8-4011-9db1-36c47710daf6`.
4. Leave `NVIDIA_DRIVER_CAPABILITIES` at `all` (see below).
5. Apply, then: `docker exec -it BuilderBot bb doctor`

`--gpus all` works too and is equivalent for a single-GPU host, but
`--runtime=nvidia` plus the variable is the form the Unraid template and the
plugin are built around, so prefer it here.

**Why capabilities matter.** The NVIDIA runtime defaults to
`compute,utility`, which injects CUDA but no GL/EGL/Vulkan drivers. `nvidia-smi`
then reports a completely healthy GPU while anything that tries to *render*
fails or silently falls back — which is a genuinely annoying thing to chase.
`bb doctor` separates the two questions:

```
  [ok]   nvidia gpu: NVIDIA GeForce RTX 3070 Ti
  [ok]   nvidia graphics stack injected (EGL available)
```

If the second line is `[FAIL]`, capabilities are the cause.

**Two gotchas worth knowing:**

- A GPU bound to **VFIO** for VM passthrough is not available to Docker. It is
  one or the other; check *Settings → VFIO-PCI Config* if the card does not
  appear.
- The plugin fetches a driver build matched to your Unraid kernel, so a
  **version upgrade needs the plugin to update too**. If the GPU vanishes after
  an Unraid update, that is the first thing to check.

---

## Option B: Compose Manager

1. **Apps** tab → install **Compose Manager** (by *dcflachs*).
2. ```bash
   STACK=/boot/config/plugins/compose.manager/projects/builderbot
   mkdir -p "$STACK"
   cd /mnt/user/appdata
   git clone https://<YOUR_PAT>@github.com/Stencil-Projects/BuilderBot.git
   cp BuilderBot/docker-compose.yml "$STACK"/
   cp BuilderBot/.env.example "$STACK"/.env
   nano "$STACK"/.env && chmod 600 "$STACK"/.env
   ```
3. ```bash
   cd "$STACK" && docker compose pull && docker compose up -d
   ```
4. Update later with `docker compose pull && docker compose up -d`.

To build on the server instead of pulling, use the clone directory and swap
the `image:`/`build:` lines in the compose file as commented.

---

## Shielding secrets (PAT + SSH keys) from Claude sessions

Anything set as a container *variable* (template field / compose `environment:`)
is visible to every process inside — including Claude, and so is anything in
`/home/builder`. The shielded path for both kinds of credential is one
root-only folder:

1. Create it on the host and drop your secrets in:
   ```bash
   mkdir -p /mnt/user/appdata/BuilderBot/secrets/ssh

   # the runner PAT
   cat > /mnt/user/appdata/BuilderBot/secrets/builderbot.env <<'EOF'
   GITHUB_PAT=github_pat_xxxxxxxxxxxxxxxx
   EOF

   # any git ssh keys (no passphrase; filename doesn't matter)
   cp /path/to/id_ed25519 /mnt/user/appdata/BuilderBot/secrets/ssh/

   chown -R root:root /mnt/user/appdata/BuilderBot/secrets
   chmod -R go-rwx   /mnt/user/appdata/BuilderBot/secrets
   ```
2. Set the template's **Secrets directory** field (or uncomment the
   `/secrets` volume in compose) to that folder, and leave the `GITHUB_PAT`
   *variable* empty.

**Git access is a separate question from the runner PAT.** Over HTTPS,
"git can use it" and "Claude can't read it" are mutually exclusive — a
credential the session's git authenticates with is one the session can read.
Pick per your taste:

| Approach | Result |
|---|---|
| SSH key in `secrets/ssh/` | Usable *and* unreadable — the only option that gives both |
| `GIT_PAT` variable | Simple; session-readable by design. Scope it to **Contents** only. Claude already has read/write on the mounted trees, so this adds no reach — keep Administration in the shielded `GITHUB_PAT` |
| `gh auth login` in a session | Same exposure as GIT_PAT, but a separate token you can revoke independently |

**How the SSH shielding works:** at startup a *root-owned* `ssh-agent` loads
every key from `secrets/ssh/`; sessions get only the agent's socket. When
Claude runs `git push`, the agent signs the authentication challenge on its
behalf — the key *works* everywhere, but the private key bytes are never
readable by any session, so it cannot be copied out of the container. (Keys
placed in `~/.ssh` instead keep working too — that's the simple, unshielded
option.)

**You never need a sudo password to manage any of this** — and a password
field would actually punch a hole in the model (it would have to live
somewhere Claude could read). Administration happens from the Unraid side,
where you're already root: edit the secrets folder on the host and restart
the container, or hop in as root with
`docker exec -it -u 0 BuilderBot bash` — a door only someone with host
access can use. Inside the container, the `builder` user (Claude) has no
password to find and no sudo to escalate with.

What happens then:

* At startup (as root, before anything else runs) the entrypoint stashes the
  values into a root-only file in `/run` and **scrubs them from the
  environment** every builder-user process inherits.
* The runner never holds the PAT: a `sudo`-whitelisted root helper
  (`mint-runner-token`) reads the stash and hands back only short-lived
  (1-hour) registration tokens.
* The `builder` user has **no general sudo** — exactly one command is
  whitelisted, and it only ever outputs registration tokens, never the PAT.
* **All log output is redacted** — both the persistent file and
  `docker logs` pass through filters that strip known token shapes
  (`github_pat_…`, `ghp_…`, `sk-ant-…`, `npm_…`, JWTs) *and* the literal
  values of every configured secret. So logs stay safe for Claude to read
  even if some tool echoes a token.
* Trade-off: `gh` is not auto-authenticated in sessions anymore (the PAT
  isn't there to do it). Git works through the shielded agent keys; run
  `gh auth login` manually if you also want the API CLI.

`bb doctor` shows which mode you're in — `runner credential: shielded` vs
`in environment`, and `github ssh auth works (shielded agent key)` vs
`(~/.ssh key file)`.

Honest limits: container-root can always read the stash (that's what makes
the runner and the agent work); a session can still *use* the agent to push
while it's running (usage is the point — extraction is what's blocked);
`ANTHROPIC_API_KEY` can't be hidden from Claude Code since Claude Code
itself must send it; and `NPM_TOKEN` lands in `~/.npmrc` if you use it.
Shielding covers the credentials with real blast radius: the PAT and the
SSH private keys.

## First-run checks

```bash
docker logs -f BuilderBot        # banner → hooks → "registering runner" → ready
docker exec -it BuilderBot bb doctor
```

Every line should read `[ok]`. If it warns about no saved login:

```bash
docker exec -it BuilderBot bb login
```

Confirm the runner arrived: GitHub → repo → *Settings* → *Actions* →
*Runners* → **builderbot** shows *Idle*.

## Daily use

```bash
docker exec -it BuilderBot claude                          # Claude Code
docker exec -it -w /workspace/FreshBoot BuilderBot claude  # in a project
docker exec -it BuilderBot bb shell                        # shell as builder
docker exec -it BuilderBot bb status                       # overview
```

`claude` and `bb` re-exec themselves as the `builder` user, because
`docker exec` (and the WebUI **Console** button) land you in as root — which
would lose your saved Claude login and write root-owned files into your
shares. A bare `docker exec -it BuilderBot bash` *is* root; use `bb shell`.

### Playwright

Chromium, Firefox and WebKit are pre-installed with all system deps, shared
at `/opt/pw-browsers`:

```bash
docker exec -it -w /workspace/FreshBoot BuilderBot bb shell
npx playwright test                 # a project pinning another version can
npx playwright install chromium     # add its own browsers to the shared dir
```

Headless works out of the box; there is no display server in the container.

### Android

The SDK (platform-tools, build-tools, platform 35), JDK 21 and `bundletool`
are baked in — Gradle projects build with their own wrapper immediately:

```bash
cd /workspace/YourApp && ./gradlew assembleRelease
```

Emulator workflow (after enabling KVM per your install option above):

```bash
bb emu start        # boots the 'builderbot' AVD headless
adb devices
./gradlew connectedAndroidTest
bb emu stop
```

AVDs persist in the home volume. Need more platforms?
`sdkmanager --install "platforms;android-34"` just works.

### Publishing packages

| Target | How |
|---|---|
| npm | set `NPM_TOKEN`, then `npm publish` |
| PyPI | set `UV_PUBLISH_TOKEN`, then `uv publish` |
| GHCR (docker) | requires the (off-by-default) Docker socket mount; then `docker login` happens automatically from `GITHUB_PAT` and `docker push ghcr.io/stencil-projects/<image>` works |
| Play Store / Maven | Gradle handles it (`./gradlew publish`); signing keys belong in the home volume or CI secrets, not the image |
| GitHub Releases | `gh release create` — `gh` is already authenticated |

---

## Notes and gotchas

**The Docker socket is OFF by default.** Mapping `/var/run/docker.sock` gives
the container control of the host Docker daemon — anything inside could start
a privileged container and execute code on the host as root. It ships
disabled (empty template field / commented compose line). Without it, the
container cannot touch the host: repo mounts only expose those directories,
`/dev/kvm` only accelerates the emulator, and container-root is not host-root.
Enable the socket only if you want `docker build`/`docker compose`/GHCR
pushes available inside, and accept the trade. The startup scripts detect its
absence and skip Docker-related setup cleanly.

**Where the logs are.** Four places, by purpose:

| Log | Where | Survives image updates? |
|---|---|---|
| Startup + runner supervisor | `/mnt/user/appdata/BuilderBot/config/logs/builderbot.log` (also `docker logs BuilderBot` / WebUI **Log** button) | ✅ file yes; `docker logs` no |
| — or your own location | Map the optional **Logs directory** path (template, advanced view) / the `/logs` volume (compose) to any share — e.g. on the array — and the log moves there automatically | ✅ |
| Runner diagnostics (`_diag`) | `/mnt/user/appdata/BuilderBot/work/_diag/` | ✅ |
| CI job output | GitHub → repo → *Actions* → the run | ✅ (kept by GitHub) |
| Android emulator | `/mnt/user/appdata/BuilderBot/home/.android/emulator.log` | ✅ |

Inside the container, `bb logs` tails the persistent startup log (`bb logs -f`
to follow, `bb logs 500` for more lines), and `bb doctor` is the first thing to
run when something misbehaves.

The log **rotates on every container start**, so one file is one container
lifetime — which is what you want when diagnosing an update that went wrong,
since the boot before it is still intact rather than blended into the same
stream:

```bash
bb logs --list     # kept boots, newest first
bb logs -p         # the previous boot
bb logs -p 3       # three boots back
```

Five generations are kept (`BB_LOG_KEEP`). A container stuck in a restart loop
burns through them quickly — if that happens, raise it or grab the files off
the share before restarting again.

**File ownership.** The container writes as `99:100` (`nobody:users`). If a
project share is owned differently, fix it once
(`chown -R 99:100 /mnt/user/development/FreshBoot`) or set
`CHOWN_PROJECTS=true`.

**`/mnt/user` vs `/mnt/cache`.** Mount through `/mnt/user` (the FUSE layer).
Mixing direct-disk and user-share paths for the same data corrupts files.

**Public repos.** Don't attach the runner to a public repository — anyone who
can open a PR could run code on your server.

**Stopping cleanly.** Stop from the Docker tab (or `docker stop`) sends
SIGTERM; the runner drains its in-flight job (default 120s) and deregisters.
Hard kills leave a stale runner entry in GitHub to delete by hand.

**Image size.** With Playwright's three browsers plus the Android SDK and
emulator image baked in, expect a pull of several GB. Updates are
layer-diffed, so routine updates move far less data.
