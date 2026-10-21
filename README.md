<p align="center">
  <img src="scripts/dashboard/static/favicon.svg" width="96" alt="BuilderBot's robot mark">
</p>

<h1 align="center">BuilderBot</h1>

<p align="center">
  A self-hosted workshop for Claude Code: your projects, the machines that
  build them, and the sessions working on them, in one dashboard.
</p>

<p align="center">
  <a href="https://github.com/aquilaelabs/builderbot/actions/workflows/build-image.yml"><img src="https://github.com/aquilaelabs/builderbot/actions/workflows/build-image.yml/badge.svg" alt="build image"></a>
  <a href="https://github.com/aquilaelabs/builderbot/actions/workflows/lint.yml"><img src="https://github.com/aquilaelabs/builderbot/actions/workflows/lint.yml/badge.svg" alt="lint"></a>
  <a href="https://github.com/aquilaelabs/builderbot/actions/workflows/dashboard.yml"><img src="https://github.com/aquilaelabs/builderbot/actions/workflows/dashboard.yml/badge.svg" alt="dashboard tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="Apache 2.0 license"></a>
  <a href="https://github.com/aquilaelabs/builderbot/pkgs/container/builderbot"><img src="https://img.shields.io/badge/image-ghcr.io-2496ed?logo=docker&logoColor=white" alt="container image on GHCR"></a>
</p>

> [!WARNING]
> **BuilderBot is early software.** It runs Claude Code sessions that edit,
> commit, run and push code on your machines, and it is still changing fast.
> Do not point it at production repositories or at anything you cannot afford
> to lose: try it on separate repositories made for testing, and keep backups
> of what it works on.
>
> **Check a project's rules before you use it there.** Some open source
> projects, employers and clients forbid AI coding tools, or contributions
> written with them. That is their call to make, and BuilderBot does not
> check it for you.

## Overview

BuilderBot is one container, the **controller**, and the machines you enroll
under it, the **nodes**. The controller keeps the dashboard and the record of
every project: its plan, its bugs, its rules. The nodes do the work: Claude
Code sessions, builds, tests, CI, Android emulators and Docker containers.

Each project is a git repository on a shared disk. Open it from the browser,
on a desktop or a phone, and a Claude session starts on its node already
briefed with the project's house rules, roadmap and open bugs. Close the tab
and the session keeps going.

It is built to live on a home server (an Unraid template ships with it) with
your projects mounted straight in, and to grow from one machine to several.

## Features

- **Claude sessions from the browser.** Real terminals in a dock at the foot
  of every page, at a desk or on a phone, each session in its own project's
  view of the disk. Resume,
  restart, pick the model and effort, and see at a glance which sessions need
  a restart to pick up a change.
- **A page per project.** Its overview and house rules, roadmap, bug
  tracker, git, tests, static analysis, artifacts, containers, VMs, wiki and
  design, shared between you and every session that works there.
- **Nodes that do the work.** Enroll a Linux machine or VM with one script:
  Ubuntu, Debian, Fedora, Rocky Linux, AlmaLinux, CentOS Stream, Arch Linux or
  openSUSE, each walked end to end on a real machine.
  Each node carries its own toolchains (JDK, Android SDK, Flutter, Node,
  Python, Playwright and more), installed and updated from the Toolchains page
  and kept on a store that survives the machine being rebuilt. A node's
  Features section says what the machine has and installs more of it, a VM
  host among them.
- **Builds, tests and CI.** `bb build` and `bb test` run on the project's
  node, a test run is timed and recorded, and a node can be a self-hosted
  GitHub Actions runner.
- **Android end to end.** An emulator per project, a real phone lent through
  the companion app, screenshots and frame-by-frame reels a session can read,
  and release signing with keys no session ever sees.
- **Containers and hosting.** A project's compose file becomes a dev
  instance with one click; hosting-only nodes run what a dev node built, and
  an nginx per node puts a hostname and a certificate in front of it. A
  public box can take in only 80 and 443, and Lock down stops it and revokes
  it in one press if it is ever taken over.
- **Virtual machines.** A project's VMs on any node with KVM, made from
  Ubuntu, Debian, Fedora, Rocky, Alma, CentOS, Arch, openSUSE, Gentoo or
  Alpine, or from an installer's ISO you install yourself (Windows
  included), each on its own network, with snapshots to go back to, more
  disks when it needs them, and its screen and console in the dock, shared
  with whoever else is on it. Ask a Claude session for "a Debian 12 VM with
  4 GB" and it makes one, where the project allows it; a VM can even enroll
  itself as another node.
- **People and permissions.** Accounts with roles, per-project access, and a
  dial for everything a session may do on its own (file bugs, add rules, run
  its container, sign a release): allowed, asked of a person, or refused.
- **A tour of each page** the first time you open it, which you can skip
  once for every page and bring back from About or your Profile. About's
  Credits name the open-source work BuilderBot is built on.
- **Logs you can read.** Every job's output, each node's own logs and the
  controller's diagnostics, kept for as long as the log policy says and
  readable by a session that has been granted them.

## Screenshots

<table>
  <tr>
    <td colspan="2"><img src="docs/screenshots/dashboard.png" alt="Home at a desk: what runs, what needs you, the last jobs and your projects"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/notebook.png" alt="A project's page, on its roadmap"></td>
    <td width="50%"><img src="docs/screenshots/nodes.png" alt="A node's page: how it is reached, its health and its stores"></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/toolchains.png" alt="The Toolchains page for a node"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/containers.png" alt="The Containers page: each project's containers on a node"></td>
    <td width="50%"><img src="docs/screenshots/vms.png" alt="The VMs page: a project's virtual machines with their state, address and snapshots"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/features.png" alt="A node's Features section: VM host, Claude sessions, the SSH door and the rest, each with how it installs"></td>
    <td width="50%"><img src="docs/screenshots/tour.png" alt="The first-use tour on Home, its card beside the rail it is about"></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/vm-screen.png" alt="A VM's screen in the dock: its installer, keyboard and mouse, beside its row on the VMs page"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="docs/screenshots/phone-dashboard.png" width="80%" alt="Home on a phone"></td>
    <td width="50%" align="center"><img src="docs/screenshots/phone-terminal.png" width="80%" alt="A terminal in the dock on a phone"></td>
  </tr>
</table>

## Quick start

### What you need

- **A server for the controller**: any machine that runs Docker, with
  Docker Compose. The controller is one container: it runs the dashboard and
  keeps the record, needs little CPU, and wants a disk for your projects.
- **At least one node**: a Linux machine or VM where sessions, builds and
  tests actually run, on **Ubuntu 24.04 or later** or **Rocky Linux 9**,
  the systems nodes are tested on. A separate VM keeps what Claude runs
  away from your server.
- **Your repositories** on GitHub, Gitea or Forgejo, or any git remote over
  plain git.
- **A Claude account** for each person who will run Claude sessions. Each
  signs in to Claude Code themselves, on the node.
- **Repositories made for trying it** (see the warning above).

### Install the controller

Make the folders it keeps its state in, owned by the user the container
should run as (`id -u` and `id -g` give yours):

```bash
mkdir -p /srv/projects /srv/builderbot/{home,config,sdk}
chown -R 1000:1000 /srv/projects /srv/builderbot
```

Then save this as `docker-compose.yml`, changing the paths and the IDs to
match:

```yaml
services:
  builderbot:
    image: ghcr.io/aquilaelabs/builderbot:0.6   # a release line; see Upgrading in docs/install.md
    container_name: BuilderBot
    hostname: builderbot
    restart: unless-stopped
    stdin_open: true
    tty: true
    environment:
      PUID: 1000          # the owner of the folders above
      PGID: 1000
      TZ: Etc/UTC         # your time zone, e.g. America/Chicago
      DASHBOARD_PORT: 7680
    volumes:
      - /srv/projects:/workspace           # your projects: one folder each
      - /srv/builderbot/sdk:/sdk           # the controller's own toolchains
      - /srv/builderbot/home:/home/builder # each account's home
      - /srv/builderbot/config:/config     # accounts, settings, notebooks, logs
      - runner-tokens:/config/runner-tokens
    ports:
      - "7680:7680"
    logging:
      driver: json-file
      options: {max-size: "20m", max-file: "3"}

volumes:
  runner-tokens:
```

Start it, and open the dashboard straight away:

```bash
docker compose up -d
```

Go to `http://YOUR-SERVER:7680`. The first page asks you to make the owner
account, so do this before anyone else can reach it. Then:

1. **Your profile** (the gear, then Profile): your name, email and git
   identity, which your commits carry.
2. **Enroll a node**: Machines, then Nodes, then **Enroll node**. It gives
   you one command to run on the node machine, which sets it up and connects
   it.
3. **Install Claude Code on the node**: Build, then Toolchains, with that
   node picked.
4. **Add a project** on the Projects page (clone one, start an empty one,
   or upload an archive), and press **Start Claude**. The first time, it walks you
   through signing in to Claude on that node.

The full checklist, with every option and the Unraid way, is
**[docs/install.md](docs/install.md)**. Once it is running, the people you
give accounts to start with **[Start here](docs/start-here.md)**, the
getting started guide, which is also the About screen's guide in the
dashboard.

## Documentation

Everything else, from installing to the full command reference, is in
**[docs/](docs/README.md)**, which is also the dashboard's Help:

- [Everything it does](docs/features.md), one area at a time
- [Install](docs/install.md), with the [Unraid walkthrough](docs/unraid.md)
- [Start here](docs/start-here.md), for an account on somebody else's BuilderBot
- [How it works](docs/how-it-works.md), the overview, with a doc for each part
  of the dashboard: [projects](docs/projects.md), [a project's page](docs/notebook.md),
  [sessions](docs/sessions.md), [building](docs/building.md),
  [toolchains](docs/toolchains.md), [containers](docs/containers.md), [VMs](docs/vms.md),
  [machines](docs/machines.md) and [people](docs/people.md)
- [Reference](docs/reference.md): settings, every `bb` command, Android signing
- [Data and privacy](docs/privacy.md): what an install keeps and contacts; nothing is sent to us
- [Architecture](docs/architecture.md) and [Contributing](CONTRIBUTING.md)

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
