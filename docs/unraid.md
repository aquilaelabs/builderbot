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
mkdir -p /mnt/user/development/BuilderBot/{home,config/startup.d,work}
chown -R 99:100 /mnt/user/development/BuilderBot
```

---

## Option A: the Docker template

### Install

Get the template onto the flash drive (the repo is private, so fetch with a
token or copy it over from a clone):

```bash
curl -fsSL -H "Authorization: Bearer <YOUR_PAT>" \
  -o /boot/config/plugins/dockerMan/templates-user/my-builderbot.xml \
  https://raw.githubusercontent.com/Stencil-Projects/BuilderBot/main/unraid/builderbot.xml
```

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
| GHCR (docker) | automatic `docker login ghcr.io` from `GITHUB_PAT` at startup; `docker push ghcr.io/stencil-projects/<image>` |
| Play Store / Maven | Gradle handles it (`./gradlew publish`); signing keys belong in the home volume or CI secrets, not the image |
| GitHub Releases | `gh release create` — `gh` is already authenticated |

---

## Notes and gotchas

**The Docker socket.** Mapping `/var/run/docker.sock` gives the container
control of the host Docker daemon — effectively root on the host. Appropriate
for a private toolchain box; remove the mapping if you'd rather not.

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
