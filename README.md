<p align="center">
  <img src="scripts/dashboard/static/favicon.svg" width="96" alt="BuilderBot's robot mark">
</p>

<h1 align="center">BuilderBot</h1>

<p align="center">
  A self-hosted workshop for Claude Code: your projects, the machines that
  build them, and the sessions working on them, in one dashboard.
</p>

<p align="center">
  <a href="https://github.com/aquilaelabs/BuilderBot/actions/workflows/build-image.yml"><img src="https://github.com/aquilaelabs/BuilderBot/actions/workflows/build-image.yml/badge.svg" alt="build image"></a>
  <a href="https://github.com/aquilaelabs/BuilderBot/actions/workflows/lint.yml"><img src="https://github.com/aquilaelabs/BuilderBot/actions/workflows/lint.yml/badge.svg" alt="lint"></a>
  <a href="https://github.com/aquilaelabs/BuilderBot/actions/workflows/dashboard.yml"><img src="https://github.com/aquilaelabs/BuilderBot/actions/workflows/dashboard.yml/badge.svg" alt="dashboard tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="Apache 2.0 license"></a>
  <a href="https://github.com/aquilaelabs/BuilderBot/pkgs/container/builderbot"><img src="https://img.shields.io/badge/image-ghcr.io-2496ed?logo=docker&logoColor=white" alt="container image on GHCR"></a>
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
  tracker, git, tests, static analysis, artifacts, containers, wiki and
  design, shared between you and every session that works there.
- **Nodes that do the work.** Enroll a Linux machine or VM with one script.
  Each node carries its own toolchains (JDK, Android SDK, Flutter, Node,
  Python, Playwright and more), installed and updated from the Toolchains page
  and kept on a store that survives the machine being rebuilt.
- **Builds, tests and CI.** `bb build` and `bb test` run on the project's
  node, a test run is timed and recorded, and a node can be a self-hosted
  GitHub Actions runner.
- **Android end to end.** An emulator per project, a real phone lent through
  the companion app, screenshots and frame-by-frame reels a session can read,
  and release signing with keys no session ever sees.
- **Containers and hosting.** A project's compose file becomes a dev
  instance with one click; hosting-only nodes run what a dev node built, and
  an nginx per node puts a hostname and a certificate in front of it.
- **People and permissions.** Accounts with roles, per-project access, and a
  dial for everything a session may do on its own (file bugs, add rules, run
  its container, sign a release): allowed, asked of a person, or refused.
- **Logs you can read.** Every job's output, each node's own logs and the
  controller's diagnostics, kept for as long as the log policy says and
  readable by a session that has been granted them.

## Screenshots

<table>
  <tr>
    <td colspan="2"><img src="docs/screenshots/dashboard.png" alt="The dashboard at a desk"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="docs/screenshots/phone-dashboard.png" width="80%" alt="The dashboard on a phone"></td>
    <td width="50%" align="center"><img src="docs/screenshots/phone-terminal.png" width="80%" alt="A terminal on a phone"></td>
  </tr>
</table>

## Documentation

Everything else, from installing to the full command reference, is in
**[docs/](docs/README.md)**, which is also the dashboard's Help:

- [Install](docs/install.md), with the [Unraid walkthrough](docs/unraid.md)
- [Start here](docs/start-here.md), for an account on somebody else's BuilderBot
- [How it works](docs/how-it-works.md), the overview, with a doc for each part
  of the dashboard: [projects](docs/projects.md), [a project's page](docs/notebook.md),
  [sessions](docs/sessions.md), [building](docs/building.md),
  [toolchains](docs/toolchains.md), [containers](docs/containers.md),
  [machines](docs/machines.md) and [people](docs/people.md)
- [Reference](docs/reference.md): settings, every `bb` command, Android signing
- [Architecture](docs/architecture.md) and [Contributing](CONTRIBUTING.md)

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
