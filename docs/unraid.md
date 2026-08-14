# Running BuilderBot on Unraid

Step-by-step, from a stock Unraid box to `docker exec -it builderbot claude`.

---

## 1. Install the Docker Compose plugin

1. Make sure **Community Applications** is installed
   (Unraid → *Apps* tab; if it's missing, install it from
   <https://forums.unraid.net/topic/38582-plug-in-community-applications/>).
2. Go to the **Apps** tab and search for **Compose Manager**
   (by *dcflachs*). Install it.
3. A **Compose** section now appears at the bottom of the **Docker** tab.

The plugin is a thin wrapper: it stores each stack under
`/boot/config/plugins/compose.manager/projects/<name>/` and shells out to the
real `docker compose`. Anything you can do in the WebUI you can also do from
the terminal, which is usually easier for the first setup.

---

## 2. Get a GitHub PAT

The container needs a token to register itself as a runner.

**Fine-grained token** (preferred):

1. GitHub → *Settings* → *Developer settings* → *Personal access tokens* →
   *Fine-grained tokens* → **Generate new token**.
2. Resource owner: **Stencil-Projects**.
3. Repository access: the repo(s) you want the runner attached to.
4. Repository permissions:
   * **Administration**: *Read and write* — required to mint runner
     registration tokens.
   * **Contents**: *Read and write* — so `gh` and `git` can push from inside
     the container.
   * **Pull requests**: *Read and write* — optional, lets Claude open PRs.
5. Copy the token; you'll paste it into `.env` in a moment.

For an **org-level** runner (one runner serving every repo in
Stencil-Projects) use a classic token with the `admin:org` scope and set
`GITHUB_URL=https://github.com/Stencil-Projects`.

---

## 3. Create the stack

Open the Unraid terminal (the `>_` icon in the top-right) and run:

```bash
STACK=/boot/config/plugins/compose.manager/projects/builderbot
mkdir -p "$STACK"
cd "$STACK"

wget -O docker-compose.yml \
  https://raw.githubusercontent.com/Stencil-Projects/BuilderBot/main/docker-compose.yml
wget -O .env \
  https://raw.githubusercontent.com/Stencil-Projects/BuilderBot/main/.env.example
```

> The repo is private, so `wget` on the raw URLs will 404 until you either make
> it public or fetch with a token. The easy alternative is to clone with the PAT
> you just made:
>
> ```bash
> cd /mnt/user/appdata
> git clone https://<YOUR_PAT>@github.com/Stencil-Projects/BuilderBot.git
> cp BuilderBot/docker-compose.yml BuilderBot/.env.example "$STACK"/
> mv "$STACK"/.env.example "$STACK"/.env
> ```
>
> Cloning also gives you the Dockerfile, so you can build locally instead of
> pulling from GHCR (see step 5b).

Create the appdata directories the stack expects:

```bash
mkdir -p /mnt/user/appdata/builderbot/{home,config/startup.d,work}
chown -R 99:100 /mnt/user/appdata/builderbot
```

---

## 4. Edit `.env`

```bash
nano /boot/config/plugins/compose.manager/projects/builderbot/.env
```

The lines to actually change:

```ini
TZ=America/New_York

# blank = log in with your Claude subscription after first start
ANTHROPIC_API_KEY=

GITHUB_URL=https://github.com/Stencil-Projects/BuilderBot
GITHUB_PAT=github_pat_xxxxxxxxxxxxxxxxxxxx

GIT_USER_NAME=Sean Bowman
GIT_USER_EMAIL=you@example.com
```

Leave `PUID=99` / `PGID=100` alone unless you know your shares want something
else — that pair is Unraid's `nobody:users`, which is what
`/mnt/user/...` expects.

The project mount paths are already set to yours:

```ini
MEDIAREDUCER_PATH=/mnt/user/appdata/mediareducer-dev
FRESHBOOT_PATH=/mnt/user/development/FreshBoot
```

They land in the container as `/workspace/mediareducer-dev` and
`/workspace/FreshBoot`.

Lock the file down — it holds a token:

```bash
chmod 600 "$STACK"/.env
```

---

## 5a. Pull the prebuilt image from GHCR

The image is published to `ghcr.io/stencil-projects/builderbot`. Because the
repo is private, the package is private too, so Unraid has to log in once:

```bash
# a classic PAT with read:packages scope (can be the same token if it's classic)
echo "<YOUR_PAT>" | docker login ghcr.io -u <your-github-username> --password-stdin
```

Then:

```bash
cd /boot/config/plugins/compose.manager/projects/builderbot
docker compose pull
docker compose up -d
```

## 5b. …or build it on the server

No registry login needed:

```bash
cd /mnt/user/appdata/BuilderBot          # the clone from step 3
cp /boot/config/plugins/compose.manager/projects/builderbot/.env .
docker compose build          # ~5-10 minutes on first build
docker compose up -d
```

If you build here, edit `docker-compose.yml` to comment out the `image:` line
and uncomment the `build:` block.

---

## 6. First-run checks

```bash
docker logs -f builderbot
```

You want to see the banner, the hooks running, `registering runner
'builderbot'`, and finally `[builderbot] ready.`

Then:

```bash
docker exec -it builderbot bb doctor
```

Every line should read `[ok]`. If `no ANTHROPIC_API_KEY and no saved login`
shows up, do the login now:

```bash
docker exec -it builderbot bb login
```

Confirm the runner arrived: GitHub → repo → *Settings* → *Actions* →
*Runners*. You should see **builderbot** as *Idle*.

---

## 7. Daily use

```bash
# Claude Code, with both projects visible
docker exec -it builderbot claude

# start it already inside a project
docker exec -it -w /workspace/FreshBoot builderbot claude

# shell as the builder user
docker exec -it builderbot bb shell

# what's going on
docker exec -it builderbot bb status
```

`claude` and `bb` re-exec themselves as the `builder` user, because
`docker exec` bypasses the entrypoint and would otherwise drop you in as root
— which loses your saved Claude login and writes root-owned files into your
shares. A bare `docker exec -it builderbot bash` *is* root; use `bb shell` (or
`docker exec -it -u builder builderbot bash -l`) instead.

The Unraid WebUI's container → **Console** button opens as root for the same
reason. Type `bb shell` once you're in.

### Updating

```bash
cd /boot/config/plugins/compose.manager/projects/builderbot
docker compose pull && docker compose up -d
```

Claude Code itself updates on every container start (`AUTO_UPDATE_CLAUDE=true`),
so you don't need to pull the image just for that. `docker exec -it builderbot
bb update` does it without a restart.

---

## Notes and gotchas

**The Docker socket mount.** `- /var/run/docker.sock:/var/run/docker.sock` in
the compose file lets workflow jobs and Claude run `docker build` /
`docker compose` against the Unraid daemon. That is effectively root on the
host — appropriate for a private toolchain box you control, but delete the line
if you'd rather not.

**File ownership.** The container writes as `99:100`. If a project directory is
owned by something else you'll get permission errors; either fix the share's
ownership (`chown -R 99:100 /mnt/user/development/FreshBoot`) or set
`CHOWN_PROJECTS=true` in `.env` to have the container do it on every start.

**`/mnt/user` vs `/mnt/cache`.** Mounting through `/mnt/user` (the FUSE layer)
is correct and safest. It's slower than `/mnt/cache/...` direct paths, but
mixing the two for the same share can corrupt files — don't.

**Public repos.** Don't point the runner at a public repository. Anyone who can
open a pull request could run arbitrary code on your server.

**Ephemeral runners.** With `RUNNER_EPHEMERAL=true` the runner deregisters
after each job and re-registers immediately. Seeing the runner briefly vanish
from the GitHub UI between jobs is expected.

**Stopping cleanly.** `docker compose down` sends SIGTERM; the container drains
the in-flight job (up to `RUNNER_SHUTDOWN_TIMEOUT`, default 120s) and
deregisters itself. If you hard-kill it instead, delete the stale runner in
GitHub's Runners settings.

**Adding a third project.** Add the mount to `docker-compose.yml`:

```yaml
      - /mnt/user/development/SomethingElse:/workspace/SomethingElse
```

then `docker compose up -d`. It shows up under `/workspace` automatically.
