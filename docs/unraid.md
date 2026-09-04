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

| I want to… | Host GHCR token | Shielded `GITHUB_PAT` | SSH key | Per-project token |
|---|:--:|:--:|:--:|:--:|
| Pull the image at all — *everyone needs this* | ● | | | |
| Run Claude against the mounted projects, no remote git | ● | | | |
| `git clone` / `pull` / `push` private repos from inside | ● | | ● | *or* ● |
| Run a self-hosted runner for **one repo** | ● | ● | | |
| Run a self-hosted runner for the **whole org** | ● | ● | | |

### What each one is, exactly

| Credential | Type | Permissions | Lives where |
|---|---|---|---|
| **Host GHCR token** | PAT **(classic)** | `read:packages` — nothing else | Unraid host, via `docker login` (step 2). Fine-grained tokens cannot pull from GHCR |
| **`GITHUB_PAT`** (shielded) | PAT (fine-grained), resource owner = **the org** | *One* permission — see the runner-scope table below | `/secrets/builderbot.env`, root-only. Never visible to sessions |
| **SSH key** | ed25519, **no passphrase** | n/a — access is whatever GitHub grants the key | `/secrets/ssh/`. Loaded into a root-owned agent: usable by git, unreadable by sessions |
| **Per-project token** | PAT (fine-grained) | *Contents*: R/W on the one repository | Typed into the dashboard's clone dialog, stored at `/config/gitcreds/<project>` and named by that repo's `.git/config`. There is no container-wide git token |

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
It does nothing for `gh pr create` or `gh release create` — those are REST
calls, and there is no container-wide token for them. Opening PRs from your
desktop is the intended arrangement and the tightest one available.

**A token is readable by Claude, and that's unavoidable.** Over HTTPS, "git can
authenticate with it" and "sessions can't read it" are contradictory — same
user, same file. Only the ssh-agent breaks that tie. What a per-project token
changes is the blast radius rather than the exposure: it is scoped to one
repository and named by that repository's `.git/config`, so a token that opens
one repo opens one repo.

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

# The SDK share: Android platforms/emulator/system images and any toolchain
# you install later. On a normal share rather than appdata — it is bulk data,
# it is not written constantly, and keeping it out of the image is the point.
mkdir -p /mnt/user/development/SDK
chown 99:100 /mnt/user/development/SDK
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

* the projects folder (`/mnt/user/development/projects`) mapped to `/workspace` — one
  mapping for all of them, so every folder in that share is a project and
  adding one never means editing the container again
* the appdata paths for home / config / runner work
* fields for `GITHUB_PAT`, `ANTHROPIC_API_KEY` (masked), git identity, TZ

Fill in `GITHUB_PAT` (and `GIT_USER_NAME`/`GIT_USER_EMAIL`), leave
`ANTHROPIC_API_KEY` empty if you're using a Claude subscription, hit
**Apply**. Unraid pulls the image and starts it.

**Unraid never applies new template values to a container that already
exists**, so changing a default here — a path, the dashboard port — does
nothing to a running container until you edit that setting on it yourself.

### Give the container time to stop

Stopping from the Docker page sends SIGTERM and then SIGKILL. BuilderBot uses
that window to deregister the Actions runner, power the emulator down instead
of yanking it, end Claude sessions cleanly and record which conversation each
project was in.

**Unraid gives it ten seconds by default, and that is often not enough.**
Unraid always passes the timeout explicitly when it stops a container —
`DockerClient.php` calls `/containers/<id>/stop?t=` with `DOCKER_TIMEOUT`,
default `10` — so the container's own `--stop-timeout` is ignored and nothing
in Extra Params can change it. The only lever is the Unraid setting:

**Settings → Docker → Docker Stop Timeout** — raise it to **60** or more.
(Docker only waits as long as it needs to; a container with nothing running
still stops instantly, so a larger number costs nothing on a quiet box.)

What the extra seconds buy, in the order the container spends them:

| | why it wants the time |
|---|---|
| Actions runner | deregisters, instead of leaving a session GitHub holds for a minute or two — which is what makes the next start log `A session for this runner already exists` and retry on Conflict |
| Emulator | `adb emu kill` powers the AVD down; a hard kill leaves it dirty and costs a cold boot next time |
| Claude sessions | exit having closed the turn rather than being cut off mid-write |

Recording which conversation was open costs milliseconds and happens first, so
it survives even a ten-second stop. `SHUTDOWN_GRACE` (default 90) caps how long
the container will wait in total, if you would rather it gave up sooner.

### Stopping cleanly before an update

Nothing you care about lives in the container: projects are bind mounts to the
array, and sessions, memory files, logins and AVDs are all on the home volume.
Uncommitted work is not at risk from a restart.

**The container handles the rest itself** — see *Give the container time to
stop* above. Stopping it deregisters the runner, powers the emulator down,
ends Claude sessions cleanly and records which conversation each project was
in, all on SIGTERM. There is no checklist to run first.

The one thing worth a glance beforehand is whether CI is mid-job, because a
job killed by the shutdown shows up as a red run on GitHub:

```bash
docker exec -it BuilderBot bb runner status
```

From a terminal rather than the Unraid UI, pass a timeout — Docker's own
default is 10 seconds:

```bash
docker stop -t 120 BuilderBot
```

Unraid's Docker page and *Check for Updates* both use the host's configured
stop timeout (Settings → Docker → Docker Stop Timeout) instead, which is why
that setting is the one worth raising.

Getting this wrong is recoverable, not fatal: a phantom offline runner in the
repo's runner list, an AVD that cold-boots next time, and a conversation you
resume from the dashboard rather than one that closed itself.

### Updating — the whole point

CI publishes a fresh `:latest` for any push to `main` that changes what the
image is built from, and on a weekly schedule. On the **Docker** tab, Unraid's
*Check for Updates* compares your running image's digest against GHCR and flips
the container to **update ready** — click it and you're on the new build.
That's the entire update procedure. Ansible not required. Most updates pull
only the layers that changed; the Monday build is rebuilt from scratch on
purpose (that is the one that refreshes packages) and pulls everything.

Template edits (new paths, changed variables) are done from the container's
own settings page (click the icon → *Edit*), and survive image updates.

### The container icon (optional, cosmetic)

The template's `Icon` points at `config/icon.png` in this repo. While the repo is
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

### A second container as a build node (optional)

A node is a machine that runs the work — builds, tests, Android emulation —
while the management container keeps the dashboard and the record. It can be a
[VM](nodes.md), and it can just as well be another copy of this container.

The container version has one property the VM does not: it shares the server's
GPU the ordinary Docker way, so the Android emulator renders on the card
without passing it through to a VM and taking it away from everything else.

1. Dashboard → **Nodes** → **Enroll node**. Name it, tick **package-build**
   and leave **docker-host** off — a container cannot be a Docker host without
   `--privileged`, which is root on the server. Copy the `bbe_…` token; it is
   shown once and lasts 24 hours.
2. Add this template a second time, with a different container name, and set:
   - **BUILDERBOT_ROLE** → `node`
   - **CONTROLLER_URL** → the dashboard's address, e.g. `http://192.168.1.15:7680`
   - **NODE_TOKEN** → the token you just copied
3. Give it its own **/config** path — that is where it keeps its identity, so
   it must not share the management container's. Its data, cache and artifacts
   stores live under `/config/node`; map a volume onto any of them — an NFS
   one, made with `docker volume create -o type=nfs …` — if you want it
   elsewhere. Nothing about the dashboard or the runner needs turning off:
   in the node role neither one starts.
4. Point its **SDK share** at the same share the management container uses.
   One store under two names is recognized, and installs are arbitrated across
   it rather than colliding.
5. For the emulator, map `/dev/kvm` and the GPU exactly as you would for the
   management container.

It appears on the Nodes tab within a few seconds of starting. Point a project
at it in the project's settings dialog and `bb build`, `bb test` and `bb emu`
run there.

### Web dashboard (optional)

1. Container settings → **ENABLE_DASHBOARD** → `true`
2. **DASHBOARD_AUTH** → `you:a-real-password`. This is read once, to create
   the owner account; afterwards the accounts are the truth and this is
   ignored, so change a password with `bb users passwd <name>` rather than
   here. The dashboard will not start
   without this, and says so in the log
3. The port mapping (`7680`) is already in the template; change the host
   side if it collides with something else on the server. Terminals ride the
   same port, behind the same sign-in — a login page with a 30-day cookie,
   not the browser's credentials prompt, and only asked once
4. Apply, then click the container's **WebUI** link

You get container and runner status, a rendered report of whatever SARIF your
scanner drops in `/reports`, every `bb` command as a button that types into the
terminal you are looking at (thumbtack the ones you use to keep them on top),
and browser terminals backed by tmux.

The Projects card is the list of folders in the projects share, and it says
what is wrong with each one rather than hiding it. Errors fold away behind a
button — no git repository, or ownership the container cannot work with, in red.
Warnings stay in the list in amber, because they are asking for something: no
`CLAUDE.md`, or one whose environment block has fallen behind the image. Both
are underlined links that fix themselves in place. A row with an error carries
no Claude button, since a session cannot start there; a *locked* one keeps its
button, ghosted, and a closed padlock after the name.
A directory with a `.bbignore` file in it is not treated as a project — the
container marks its own paths that way (the SDK share, if you put it inside
the projects share, as the default does), and you can drop the same file into
anything you would rather the card ignored.

**New project…** at the foot of the card creates one — a fresh local repo built
from the name and description you give it, or a clone of a GitHub repository
the container's deploy key or PAT can already reach, which needs only the URL:
the name comes from the repository and the `CLAUDE.md` is drafted from its own
README and build files.

Selecting text in a shell terminal copies it to your clipboard as you release
the mouse. Claude tabs keep tmux's mouse mode instead, so they do not.
Right-click gives you the browser's menu only — tmux's would be drawn
underneath it — and Alt+right-click still opens tmux's if you want it.

The `bb` commands card sits between two more: **Linux commands** (disk,
memory, processes, ports — live on any shell) above it, and **Git & GitHub**
below, which grays out when the active shell's directory is not a git
repository — and grays just its `gh` half when the repo has no GitHub remote.
Last comes a card for your own: **+** takes a title and a list of command
lines, and the button it makes types them into the terminal in order. They
are kept in `/config`, so they survive updates.

The page starts with one workspace tab; every tab, that one included, can be
minimized. **Claude** opens one session per project — resumable if a previous
conversation exists — and **Shell** opens another terminal each time you click
it. Tabs are named for where they are (`sh: <directory>`, following a `cd`;
`Claude: <project>`), with the full path on hover. Tabs can be dragged to
reorder (on a phone, hold for half a second first) and pinned to a left or
right pane for a side-by-side view. A pane's ✕ only collapses the split.

A tab's **—** minimizes it: the terminal or Claude session keeps running and is
listed under Sessions, where clicking the name brings its tab back. Ending a
session for good is the ✕ in the Sessions card (or a middle-click on its tab),
and that is the only thing that asks. The sidebar cards collapse on a click of
their header and can be dragged into any order; the ▤ button in the top bar
resets them.

The tab strip is stored on the container rather than in the browser, so a phone
shows what the desktop has open. **Terminals survive a restart of the container**
— the shutdown saves each one's directory and the last screenful of its
scrollback under the Config path in `sessions/`, and startup puts them back.
What was *running* in them does not come back; that went down with the
container. Claude sessions are not restored either, because the conversation
ended with it — the transcript is kept, and the project's Claude button offers
to resume it.

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
`bb doctor` separates the questions:

```
  [ok]   nvidia gpu: NVIDIA GeForce RTX 3070 Ti
  [ok]   nvidia graphics stack usable (EGL vendor: NVIDIA)
```

If the second line is `[FAIL]`, capabilities are the cause. If it is `[warn]`,
the drivers are injected but nothing can render on them yet — see below.

**Rendering needs a display, not just a driver.** This is the part that looks
like it should already work and does not. NVIDIA's EGL refuses to hand out a
display unless an X server carrying its own GLX module is running; with none,
the Android emulator finds the card for Vulkan, fails at `Failed to get EGL
display`, and quietly renders in software. The container starts a headless
`Xorg` for the card at boot to close that gap (`ENABLE_GPU_DISPLAY`, on by
default, silent on a box with no GPU). Two things have to be true for it:

- **`NVIDIA_DRIVER_CAPABILITIES` must include `display`** — `all` does. It is
  what makes the runtime inject `libglxserver_nvidia.so`, the module the X
  server loads. `graphics` alone is not enough.
- **The card must not be in use by a VM**, for the same VFIO reason below.

`bb emu gpu` answers "hardware or software, and why" in one line, and
`/var/log/xorg-builderbot.log` has the detail when the answer is software.
After a driver update this is the first thing to check: NVIDIA's X module is
built against a specific X server ABI, and if the two disagree the server will
not start — the log says so, and the emulator carries on in software rather
than failing.

Xvfb is the obvious thing to reach for here and it does not work: it has no
NVIDIA GLX, so EGL falls through to Mesa, which has no driver for an NVIDIA
card and lands on llvmpipe. That is software rendering by a slower road, and
it looks like success from the outside.

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
| Per-project token, in the clone dialog | Session-readable by design, but scoped to the one repository that names it — a token that opens one repo opens one repo |
| `gh auth login` in a session | Same exposure, and a separate token you can revoke independently |

**How the SSH shielding works:** at startup a *root-owned* `ssh-agent` loads
every key from `secrets/ssh/`; sessions get only the agent's socket. When
Claude runs `git push`, the agent signs the authentication challenge on its
behalf — the key *works* everywhere, but the private key bytes are never
readable by any session, so it cannot be copied out of the container. (Keys
placed in `~/.ssh` instead keep working too — that's the simple, unshielded
option.)

With several deploy keys loaded, one per private repo, ssh needs telling
which key belongs to which repo. The dashboard's **New project…** clone
form does that for you: it lists the loaded keys (their public halves,
straight from the agent), and picking one writes the selector and alias
and clones through them — the
same picker also shows the public key to paste into the repo's
**Settings → Deploy keys** on GitHub. Adding a *new* key is still the
host-side flow above: drop the private key in `secrets/ssh/` and restart
the container so the agent picks it up.

The same picker appears when **linking** a local repo to GitHub (the chain
icon on a project row that has no remote): pick the key, or none if a PAT
is configured. Linking only ever targets an *empty* GitHub repository —
and with a PAT, one that does not exist yet is created for you, private.

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

## Dev instances: building a project's app

The dashboard's Artifacts tab can build a project's compose app and bring it up
and down — no GitHub minutes, no registry round trip. It builds on a **sandbox
VM**: a small machine whose only job is running Docker, reached over ssh, with
no real containers on it and no route to this server's daemon. Setting it up is
[sandbox-vm.md](sandbox-vm.md), and it is the only arrangement.

A separate machine needs no filtering, which is the point: there is nothing
over there to protect. Anything else — an address of another kind, or none —
turns every Docker control off with the reason on it.

One limit survives the move, because it is not the daemon's. A compose file can
ask for the machine directly — `privileged: true`, `network_mode: host`, a bind
mount of `/` — and the container it makes is a container like any other. So the
file is read before anything starts, what it reaches for is named on the row,
and a confirmation is asked once per set. That is a warning rather than a
refusal: a compose may want a host path for good reasons, and nothing here can
tell which. On a machine that exists to be wrecked it is information rather
than a gate.

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

The SDK (platform-tools, build-tools, platform 36), JDK 21 and `bundletool`
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

AVDs persist in the home volume; the images and platforms themselves live on
the SDK share, so an image update never re-downloads them. Need more
platforms? `bb sdk install android:"platforms;android-34"`, or tick it in the
dashboard's Tools tab.

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

**The container cannot touch the host's Docker.** There is no socket to mount
and no proxy to point at: docker work happens on the sandbox VM, over ssh, on a
machine that holds nothing. The repo mounts expose those directories and
nothing else, `/dev/kvm` only accelerates the emulator, and container-root is
not host-root.

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
project is owned differently, fix that project once
(`chown -R 99:100 /mnt/user/development/projects/FreshBoot`) or set
`CHOWN_PROJECTS=true` to do it for all of them at every start. The container
never chowns the projects share itself — that folder is yours, and a container
quietly changing the ownership of a share because it started is a surprise, not
a repair. It warns in the log if it cannot write there, and the dashboard names
any project it cannot read, write or enter.

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
