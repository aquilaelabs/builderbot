# What BuilderBot does

Everything BuilderBot 0.5.0 offers, one area at a time, with the doc that
explains each in full.

## The dashboard

One page in the browser, at a desk or on a phone ([dashboard.md](dashboard.md)).

- **The rail** down the left edge: Home, Projects, Build, Containers,
  Machines, Sessions, Jobs, People, Settings and Help. On a phone it is a bar
  at the foot.
- **Home**: tiles for what is running and what needs you (nodes online,
  containers running, jobs and failures, sessions open, updates due, CI in
  the red), your attention list, the last jobs and your pinned projects.
- **Search** at the top jumps to any page, project, container or node.
- **The bell** holds what waits on your answer and what was said; **the
  doctor's dot** beside it is the controller's health at a glance.
- **The dock** at the foot of every page holds the chat and your terminals.
- **Help** is these docs, with a search across them, inside the dashboard.
- Color schemes, light and dark, chosen per person.

## Projects

Each project is a git repository ([projects.md](projects.md)).

- **New project**: clone one from GitHub, Gitea, Forgejo or any git remote,
  start an empty one, or upload a zip or tarball of code you already have.
  Link an existing local repository to an empty one on a host.
- Groups, pins, a color of your own, rename, archive, and a trash that
  keeps a deleted project until it is purged.
- A per-project **Settings** page: its node, build and test commands, what
  an agent may do, the toolchains its sessions may use, signing keys, file
  access and who is on it.

## A project's page

Everything about a project, shared between you and every session that
works there ([notebook.md](notebook.md)).

- **Overview**: house rules, memories, the code base at a glance.
- **Roadmap** of items and steps, sent to a session from the page,
  with a history of who did what.
- **Bugs**: a tracker sessions file into and read from.
- **Git**: status, commit, branches with a history graph, fetch, pull and
  push, and the CI runs of the repository's workflows.
- **Tests**: every run recorded and timed, per suite.
- **Analysis**: static-analysis findings from a scanner you run.
- **Artifacts**: the project's builds in `dist/`, with releases.
- **Docker**: the project's containers.
- **Wiki** and **Design**: a wiki read like an encyclopedia, and the
  project's design language and pages, which sessions follow.

## Sessions

([sessions.md](sessions.md), [agents.md](agents.md))

- **Start agent** opens a session of Claude (Claude Code), ChatGPT (Codex
  CLI) or Copilot (Copilot CLI) on the project's node, in a real terminal in
  the dock. Resume it later, restart it, and pick the model and effort.
- Each session starts **briefed**: the project's house rules, roadmap and
  open bugs, so you ask for the thing rather than explain the place.
- **What an agent may do is a dial per project**: add to the roadmap, file
  bugs, add rules, write the wiki, run its container, sign a build, publish
  a release. Each is allowed, asked of a person, or refused.
- **A session sees only its own project** on disk, with your git identity on
  its commits. Credentials stay out of its reach: it pushes and signs
  through BuilderBot without ever holding the keys.
- **Asking**: a session waiting on a permission prompt shows amber in the
  dock, on its project and in the bell.
- A session may **read other projects** you allow, without changing them.
- Each person signs in to each agent with their own account, on each node,
  from the Agents page.

## The `bb` command

What a session (or you, in a terminal) uses to work with BuilderBot
([bb-command.md](bb-command.md), [reference.md](reference.md)).

- The notebook from the terminal: `bb roadmap`, `bb bug`, `bb rules`,
  `bb design`, `bb changelog`.
- `bb build`, `bb test` and `bb run` on the project's node.
- `bb map`: where a name is defined and who calls it, across the code.
- `bb capture`: screenshots and frame-by-frame reels of a page or the
  emulator that a session can look at.
- `bb tool`: the commands toolchains and tool packs give a session:
  documents to Markdown, graphics, diagrams, sound, and your own.

## Nodes

The machines that do the work ([machines.md](machines.md), [nodes.md](nodes.md)).

- **Enroll node** gives you one command to run on a machine: it sets the
  machine up and connects it. Nodes run Ubuntu 24.04 or later or Rocky
  Linux 9.
- A node **dials out** to the controller: on your network, or from
  elsewhere through a public hostname.
- **Hosting-only nodes** for a public box such as a cloud VPS: they run the
  containers sent to them and nothing of them reaches back home.
- An **SSH door** through cloudflared, switched on and off from the node's row.
- Each node's **storage**, **network**, sessions and logs on its page, and
  its agent updated from the dashboard.
- **Jobs**: every build, install and container action as a job, with its
  log, on the Jobs page.

## Toolchains

([toolchains.md](toolchains.md))

- A catalog of toolchains installed per node from the Toolchains page: JDK,
  the Android SDK, Flutter, Go, .NET, Node.js, Python, Rust, Swift, Zig,
  Playwright, ffmpeg, language servers, lint tools, document, graphics,
  diagram and speech tools, LibreOffice, and PyTorch with CUDA.
- Kept on a store outside the node's system, so a rebuilt machine keeps them.
- Updates checked and offered; anything under an agreement (Google's Android
  SDK terms, NVIDIA's CUDA license) asks you to accept it first.
- **Tool packs** ([tool-packs.md](tool-packs.md)): add a toolchain of your
  own for any tool, from a git repository, a pasted `bbtool.json` or an
  upload, with the commands it gives Claude. Kept at the version you
  approved.
- Per project, which toolchains and packs its sessions may use.
- **The NVIDIA card**: its driver and container toolkit installed on a node.

## Android

([toolchains.md](toolchains.md), [companion-app.md](companion-app.md))

- Android SDK versions, system images and an **emulator** per project.
- A **real phone** lent to a project through the Android app.
- **Release signing** with keys a session never sees.
- **The Android app**: your projects, the bell and your sessions on a phone.

## Containers

([containers.md](containers.md))

- A project's compose file becomes a **dev instance** with one press, built
  and run on its node.
- **Copy or move** a container and its data to another node.
- **nginx** per node puts a hostname and a certificate in front of what runs
  there.
- Image updates checked and applied from the Containers page.

## Builds, CI and releases

([building.md](building.md))

- Builds and tests run on the project's node; their output lands in `dist/`.
- A node can be a **self-hosted GitHub Actions runner**, with its CI logs
  readable from the project.
- Versions and a changelog per project, and releases tagged and published
  from the Artifacts view.

## People

([people.md](people.md), [users.md](users.md))

- Accounts with **roles**: built-in or your own, giving each area Read or
  Write, everywhere or per project.
- A project's **owner** and **invitations**.
- A **chat** between the people on a controller.
- **Your profile**: name, email and git identity, your time zone, and the
  devices signed in as you.
- **File access**: a project's files over FTPS, signing in with your own
  account.

## Running it

- One container, the controller; your projects, its state and its
  toolchains in folders you choose ([install.md](install.md)).
- **Upgrades** between releases carried forward automatically, with a backup
  first and a clear refusal on an unsupported jump ([install.md](install.md#upgrading)).
- **Settings**, logs and diagnostics on the Controller settings page.
- **Nothing is sent to us**: no telemetry ([privacy.md](privacy.md)).
