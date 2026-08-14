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

## Shared step 1: GitHub PAT

The container needs a token to register itself as an Actions runner and to
work with your private repos.

**Fine-grained token** (preferred):

1. GitHub → *Settings* → *Developer settings* → *Personal access tokens* →
   *Fine-grained tokens* → **Generate new token**.
2. Resource owner: **Stencil-Projects**.
3. Repository access: the repo(s) you want the runner attached to.
4. Repository permissions:
   * **Administration**: *Read and write* — mints runner registration tokens.
   * **Contents**: *Read and write* — so `gh`/`git` can push from inside.
   * **Pull requests**: *Read and write* — optional, lets Claude open PRs.

You'll also need a **classic PAT with `read:packages`** for pulling the
private image from GHCR (fine-grained tokens still don't cover GHCR pulls; a
classic token with `read:packages` + `repo` can double for everything if you
prefer one token).

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

* both project paths (`/mnt/user/appdata/mediareducer-dev`,
  `/mnt/user/development/FreshBoot`) mapped into `/workspace/…`
* the appdata paths for home / config / runner work
* fields for `GITHUB_PAT`, `ANTHROPIC_API_KEY` (masked), git identity, TZ

Fill in `GITHUB_PAT` (and `GIT_USER_NAME`/`GIT_USER_EMAIL`), leave
`ANTHROPIC_API_KEY` empty if you're using a Claude subscription, hit
**Apply**. Unraid pulls the image and starts it.

### Updating — the whole point

CI publishes a fresh `:latest` on every push to `main` and on a weekly
schedule. On the **Docker** tab, Unraid's *Check for Updates* compares your
running image's digest against GHCR and flips the container to
**update ready** — click it and you're on the new build. That's the entire
update procedure. Ansible not required.

Template edits (new paths, changed variables) are done from the container's
own settings page (click the icon → *Edit*), and survive image updates.

### Android emulator (optional)

1. Container settings → **Extra Params**: append ` --device=/dev/kvm`
2. Set `ENABLE_ANDROID_EMULATOR` to `true`
3. Apply, then: `docker exec -it BuilderBot bb emu start`

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
to follow, `bb logs 500` for more lines), and `bb doctor` is the first thing
to run when something misbehaves. The file rotates at ~5 MB keeping one
previous generation, so it can't grow unbounded.

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
