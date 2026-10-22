# How BuilderBot works

BuilderBot is one container, the **controller**, and the machines it enrolls,
the **nodes**. The controller serves the dashboard and keeps every project's
notebook and record; the nodes run the work: Claude sessions, builds, tests,
CI, the emulator and containers. This page is the overview: what the image
carries, how it is kept safe and how it starts, and which doc explains each
part. The design decisions behind it, with their dates and reasons, are in
[decisions.md](decisions.md); the setup steps are in [install.md](install.md).

## Where each part is explained

The docs follow the rail, the column of pages down the dashboard's left
edge:

| On the rail | What it is | Explained in |
|---|---|---|
| Home, the top bar, the dock | The landing page, the bell, the search, the terminals and the chat | [dashboard.md](dashboard.md) |
| Projects | Every project as a card; making, linking, archiving and deleting one | [projects.md](projects.md) |
| A project's page | Its notebook: Overview, Roadmap, Bugs, Git, Tests, Analysis, Artifacts, Docker, Wiki, Design | [notebook.md](notebook.md) |
| Build | Toolchains, Emulator and Phone | [toolchains.md](toolchains.md) |
| Build | Agents: the coding agents on each node, their versions and your sign-in there | [agents.md](agents.md) |
| Build | CI runner, builds, tests, the scanner's findings, signing and releases | [building.md](building.md) |
| Containers | The Docker manager and nginx | [containers.md](containers.md) |
| Machines, Jobs | Controller settings, Nodes, Storage and the job queue | [machines.md](machines.md) |
| Sessions | Claude sessions: starting one, what it sees, what it is told | [sessions.md](sessions.md) |
| People, Settings | Users, Roles, and your Profile | [people.md](people.md) |
| Build > Apps | The companion app for an Android phone | [companion-app.md](companion-app.md) |
| (a terminal) | The `bb` command | [bb-command.md](bb-command.md) and [reference.md](reference.md) |

## What's in the image

| | |
|---|---|
| **Claude Code** | Not in the image: a session runs on a node, and the node installs it |
| **Node** | 22.x (NodeSource) + npm, corepack (yarn/pnpm shims) |
| **Python** | 3.12, `uv`, `pipx`, venv |
| **Playwright** | CLI + the system deps; the browsers themselves install to the [toolchain store](toolchains.md#the-toolchain-store-lives-outside-the-image) and appear at `/opt/pw-browsers` |
| **Android, Java, Flutter, .NET…** | Not in the image. A node's, from its toolchain store: the JDK, the SDK and the emulator are recipes on the Toolchains page, installed with the node picked, and the system images the emulator boots are on the Emulator page |
| **Git** | git, git-lfs, `gh` CLI |
| **Docker** | CLI + compose/buildx plugins; no daemon and no host socket here, so containers run on a node |
| **Search** | ripgrep, fd, fzf, jq, yq |
| **Build** | build-essential, cmake, pkg-config |
| **Lint** | shellcheck, hadolint, actionlint, ruff, node --check: `bb lint` runs the right ones over a repo |
| **Media** | ffmpeg, imagemagick |
| **Runner** | Not in the image: CI runners are a node's, added on the CI runner page under Build |
| **Versioning** | `mise` for per-project tool pinning (gradle, go, rust, on demand) |

Slimmer builds: `--build-arg INSTALL_PLAYWRIGHT=false`, `INSTALL_ANDROID=false`.
The heavyweight toolchains (Flutter, .NET, Swift, extra Android packages)
are never in the image at all; `bb toolchains install` puts them on a share that an
update cannot touch. See [the toolchain store lives outside the image](toolchains.md#the-toolchain-store-lives-outside-the-image).

## Security model, in short

- **Repo mounts** expose only those trees; writes land as `nobody:users`.
- **No Docker socket**: nothing mounts the host's, so reaching the host
  requires a kernel exploit.
- **Secrets shielding**: publishing tokens always scrubbed from session env +
  root-only sudo helper for runner tokens, whose store is a named volume of the daemon's
  rather than a directory under `/config`, so it stays root-owned even
  when appdata is a squashed NFS share; SSH keys usable via root-owned
  agent but not readable; logs redacted (patterns + literal values).
- **No passwords, no general sudo**: `root` and `builder` are locked
  accounts; brute-forcing has no target. Builder may sudo exactly two
  commands: `mint-runner-token`, which only emits 1-hour tokens, and
  `deploy-key`, which keeps a project's deploy key root-only and loads it
  into the agent.
- **Your root door** is host-side: `docker exec -it -u 0 BuilderBot bash`.
- Don't attach the runner to public repos; treat container-produced commits
  and packages with normal review.

Full discussion: [unraid.md](unraid.md#notes-and-gotchas).

## Startup hooks

The entrypoint runs as root: stash/scrub secrets, remap `builder` to
`PUID:PGID`, seed the home volume (never overwriting), start the ssh-agent,
then executes hooks and drops privileges:

| Hook | Does |
|---|---|
| `30-git-and-auth.sh` | git defaults and GitHub's host keys; no commit identity and no container-wide token |
| `35-publishing.sh` | npm publish auth, when an `NPM_TOKEN` is in the secrets folder |
| `40-projects.sh` | project report, optional per-project bootstrap |

Your own hooks go in `config/startup.d/` on the share: `*.root.sh` runs as
root, `*.disabled.sh` is skipped, filename order. All hooks are idempotent:
they check state before installing.

The dashboard starts early in the boot, before any project's own `setup.sh`
and the SDK/Playwright hooks, so the web UI is reachable in seconds rather
than after the whole start-up. For a few of those seconds it knows less than
it will: the toolchain store is listed as a project until the hook that marks
it runs, and the git facts on the cards are blank. All of that corrects itself on the next
poll. `bb logs` times each
hook and prints how far into the boot it started, so "what is the wait" is a
question the log answers.
