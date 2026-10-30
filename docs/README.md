# BuilderBot documentation

BuilderBot is a self-hosted workshop for coding agents: Claude Code,
ChatGPT's Codex CLI and GitHub's Copilot CLI. One container, the
**controller**, serves this dashboard and keeps every project's plan, bugs
and rules; the machines it enrolls, the **nodes**, do the work: the agents'
sessions, builds, tests, CI, Android emulators and Docker containers. These
docs are also the dashboard's **Help**, where the search in the bar finds a
line in any of them.

**Where to start.** To set BuilderBot up, follow
[install.md](install.md) (on Unraid, [unraid.md](unraid.md)). Given an
account on somebody's BuilderBot, read [start-here.md](start-here.md). To
find your way around, read [how-it-works.md](how-it-works.md), the overview,
then the doc for the part you are on: the docs under *Work on a project*,
*Build, test and ship* and *Machines, people and devices* follow the
dashboard's rail.

## Start here

- [start-here.md](start-here.md): given an account on somebody else's BuilderBot: the first five minutes, what is shared, and what the refusals mean
- [how-it-works.md](how-it-works.md): the overview: the controller and its nodes, what the image carries, and which doc explains each part
- [features.md](features.md): everything BuilderBot does, one area at a time, with the doc for each
- [dashboard.md](dashboard.md): finding your way: the rail, Home, the bell and notifications, color schemes, and the dock with its terminals and chat

## Set it up

- [install.md](install.md): the complete checklist, with the decisions each step needs
- [unraid.md](unraid.md): the same on Unraid, step by step
- [sandbox-vm.md](sandbox-vm.md): the Docker sandbox VM a node usually is: why, how, and enrolling it

## Work on a project

- [projects.md](projects.md): the Projects page: making, cloning and linking a project, its menu and settings, archiving and deleting it
- [git-hosts.md](git-hosts.md): what an agent can do on your git host (GitHub, GitLab, Gitea): each ability, the token permission it needs, and the project's Allow or Deny over it
- [notebook.md](notebook.md): a project's page: Overview, Roadmap, Bugs, Git, Tests, Analysis, Artifacts, Docker, Wiki and Design
- [sessions.md](sessions.md): sessions of each agent, Claude, ChatGPT and Copilot: starting one, the Sessions page, what a session sees, what it is told and the rules it is held to

## Build, test and ship

- [building.md](building.md): builds and tests on a node, CI runners and their logs, the scanner's findings, signing and releases
- [scanners.md](scanners.md): setting up the static analysis stack (Semgrep, Trivy, mobsfscan) and the script that runs it
- [versions.md](versions.md): a project's version, release lines (two releases built at once), and moving fixes forward and back between them
- [toolchains.md](toolchains.md): the Build pages: Toolchains, the NVIDIA card, Android versions and the Emulator, and a Phone lent to a project
- [agents.md](agents.md): the coding agents a session runs (Claude Code, Codex CLI, Copilot CLI, Grok Build): installing each on a node from the Library and signing in to it there
- [tool-packs.md](tool-packs.md): toolchains you add yourself from a repository, the commands they give a session, and how to write one
- [containers.md](containers.md): the Containers page and nginx: dev instances, how one is reached, their networks and image updates
- [vms.md](vms.md): the VMs page and `bb vm`: VM host on a node, the OS catalog, Make VMs, the network, snapshots, a VM made a node
- [nas.md](nas.md): the installed edition as a NAS, its design: Python the management plane and never the data path, the two storage profiles, and what BuilderBot does not build
- [image.md](image.md): BuilderBot OS, the appliance image the installed editions are made from: Debian pinned to a snapshot, two root slots, what persists, how it boots and how it is built

## Machines, people and devices

- [machines.md](machines.md): This machine, Controller settings, Network, Nodes, Storage, Installed, the logs and the Jobs page
- [people.md](people.md): accounts and roles, a project's owner and invitations, the chat, and your Profile
- [companion-app.md](companion-app.md): the Android companion app: pairing, approvals and notifications from a phone

## Look things up

- [reference.md](reference.md): every setting in the environment, every `bb` command, the apps to install, and signing Android releases
- [bb-command.md](bb-command.md): the `bb` verbs with more behind them: the test harness, the code map, capture, sound and documents
- [privacy.md](privacy.md): what an install keeps about the people who use it, what it contacts, and how to remove it; nothing goes to BuilderBot's authors
- [security.md](security.md): the threat model: who is trusted for what, what each store protects and does not, what an unlock gives up, and the line each hardening step closes

## Working on BuilderBot

- [../CONTRIBUTING.md](../CONTRIBUTING.md): where to start
- [architecture.md](architecture.md): one page: what the parts are, how they reach each other, and where each is explained
- [layout.md](layout.md): the file-by-file layout
- [api.md](api.md): every dashboard endpoint and who may call it, generated from the server
- [design-language.md](design-language.md): what the dashboard's surfaces owe each other
- [decisions.md](decisions.md): the design decisions, with their dates and reasons
- [nodes.md](nodes.md): the design record for the controller and its nodes, from one machine at home to many
- [users.md](users.md): the design record for accounts, roles and what each one may reach
- [journeys.md](journeys.md): what a person does with BuilderBot, walked for real rather than reasoned about
