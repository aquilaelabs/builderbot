# Changelog

## 0.6.0: 2026-10-21

### Added

- A short tour of each page the first time you open it, pointing at its parts one step at a time, with Skip tour and a box to skip it on every page; Show the tours again, in About and on Profile, brings them back. (310b392)
- Lock down on a hosting-only node's page, for a box that may have been taken over: one press stops every container there and its nginx, keeps them from starting at a boot, shuts its SSH door, and removes the node with its credential revoked, within five minutes even if the box never answers (edb13701)
- A VMs page in the Containers group: make, start, stop, snapshot, revert and remove a project's virtual machines on any node with VM host installed, from Ubuntu, Debian, Fedora, Rocky or Alpine images, each with its own network that reaches the internet and the controller but not your LAN. A project's Claude sessions can do the same with bb vm under a new Make VMs setting (deny by default), ask for an OS in words, and make a VM a node of its own. (8ba0d8e)
- A node's page has a Features section listing what the machine has (VM host, the hosting firewall, Claude sessions, the SSH door, the GPU driver, the Android emulator, a CI runner), with Install and Uninstall for VM host and the firewall and a way to each of the others; Enroll node can tick VM host. (c849623)

### Removed

- An agent from 0.5 no longer works with this controller: after updating, press Update agent on each node's row, which ends the sessions on that node; until then its projects' sessions are held. A session started under 0.5 is not carried over. (dfdf573)

### Fixed

- A node whose NVIDIA card has gone keeps its driver and container toolkit rows on the Toolchains page, saying so with Remove, and no longer tries to load the driver at every boot, which filled its console with No NVIDIA GPU found (57ef607)
- Enrolling a new Linux node works again: since the provisioner was split into one file per system, it stopped right after installing Docker with 'svc_enable: command not found', and a VM's guest agent was never installed. (2a64240)
- On a phone, a node that is not a sandbox says where its storage and network are managed with room around it, no longer pressed against the next section's heading (18b971e1)
- Opening the nginx page from a link for a node that enrolled since the page last loaded shows that node, not the first one. (66bbe80)
- A system job right after a controller update runs the node's newest root helper, not whichever one another job last fetched. (11e99d0)

### Security

- A hosting-only node that was taken over can no longer reach past its own containers: bringing its containers home writes only their own volumes, it cannot lock the controller's own address out by what it reports, jobs placed by selector never land on it, a forged address no longer lets a project's sessions reach a LAN machine, it cannot fill the controller's disk or audit log, and a node enrolled through a public hostname stays hosting only. Update the controller, and its nodes' agents follow (edb13701)
- Enroll node offers a hosting-only box a firewall of its own, ticked: it takes in only 80 and 443 (and port 22 as its SSH door leaves it), so a container that publishes another port is not reached from the internet. A box enrolled before keeps its ports; enroll it again from its row to add it (85d3b6e8)
- On the nginx page, a certificate pair on a hosting-only node says which names it also answers for beyond that node's routes, such as a wildcard for your home domain, since its key sits on that box (85d3b6e8)

## 0.5.4: 2026-10-21

### Added

- Maintenance mode, under Controller settings and the owner's alone: while it is on, only the owner can sign in and use BuilderBot, from the page, a phone or a Claude session; everybody else is told it is down for maintenance and stays signed in for after, and nodes keep running (a533093)
- A project whose node has no Claude Code offers Install Claude, which opens that node's Toolchains, in place of a dead Start Claude (444b8fc)
- A roadmap item can name the release it is meant for: set it in the item's Reword box or with bb roadmap target, and a line of chips narrows the Roadmap by release; the Bugs view narrows the same way by the release a bug was seen in (7887ca9)

### Changed

- A button an account's roles do not give is left off the page, where it was drawn dead with a red line naming the role it lacks; a reason a control is off is no longer red: a feature the install switched off says so in yellow, and why a project cannot start a session is muted (a644363)

### Fixed

- A toolchain install on a machine with no internet says so in one sentence, on a node too, where the job ended with only a count of what did not install (3cd49c2)
- The header's search field is as tall as the buttons beside it, and the dock's + and pull as tall as its tabs (34c12da)
- A job on a node whose agent runs as an account with no home (a container started as a bare user id) gets one, so tools like npm run (407fc51)
- With no node running Docker, the Containers page names the nodes that need it, instead of asking for a sandbox VM to be enrolled (68ff224)
- On a phone, a tile's number with a unit wraps rather than being cut, where the Emulator page read "11.1…" for 11.1 TB (2b714d0)
- The Sessions page says when a session on the controller started (8e7754e)
- The Apps page no longer says the controller's look at its release failed when that release simply carries no Android app: the app's row says the release does not carry it (c62fb88)

### Security

- bb capture sends a session's credential to the controller alone: a page on another host that shared the dashboard's port, or any page a reel recorded, was sent it too (07147ec)

## 0.5.3: 2026-10-20

### Added

- An install can carry a banner: BANNER_TEXT, with an optional BANNER_LINK and BANNER_LINK_LABEL, is shown as a band under the header on every page and on the sign-in page (60ee682)
- FEATURES_OFF takes internet, for an install meant to run offline: it turns off apps, image updates, the tunnel and the CI runner together (60ee682)
- bb users add and bb users claim take --seen, so an account a script makes does not open on the guide and the what's-new window (60ee682)

### Fixed

- Updating a node's agent no longer cuts short a job running on it: the agent restarts only after installing a newer version, and only once its jobs end (aac08b2)
- A dev instance pinned to a branch builds on a node (1cf91cd)
- A container's Start on boot is applied on a hosting-only node (c56e2c0)
- The Doctor reports a switched-off feature's checks as skipped, not failed (60ee682)

## 0.5.2: 2026-10-20

### Added

- A conversation with Claude can be read on the Profile page: Read beside Download opens its turns, with Claude's commands folded under each and what they answered (40a86bf)
- Features can be switched off for a whole install with FEATURES_OFF (tunnel, ftp, phone, devices, apps, image-updates, runner, enroll, shell): their controls show the sentence in FEATURES_OFF_WHY, their requests are refused, and Settings lists them (94d96d3)
- A new install can be set up from a shell on the controller: bb users claim, bb nodes enroll-token, bb projects adopt and bb settings node (e3b0850)
- A compose file on a node can use BB_DOCKER_GID, the node's docker group (2953234)

### Fixed

- A node run in a container as a user with no account entry, or with its /workspace in memory, keeps dialing in and syncs its projects (92a2c3f)
- A node says when it has no internet, when its toolchain store is read-only, and when the store is mounted noexec (which stops its terminals); a toolchain install on a machine with no internet stops in one sentence before it starts (38efead)
- A dashboard put behind Cloudflare under its own hostname loads: it is no longer taken for the controller's own tunnel, and Rocket Loader leaves its scripts alone (63d5b9e)

## 0.5.1: 2026-10-20

### Added

- A project has an id, P and a number, shown first on its card and its page; a Claude session is named after the project with its id, as "builderbot (P3)", rather than after its folder, and bb -p takes the id too (d2ff341)

### Fixed

- A release cut without a bump carries the changelog's Unreleased changes as its notes, and is named by the project's name rather than its folder (3bbf872)
- A first start on new folders works: the container makes its home folders and /config its own account's, so the first account can be created and sign-ins are kept (abbdd4b)
- A container whose folders the host will not let it re-own (NFS that squashes root, some NAS shares) starts and says so in its log, rather than restarting forever; the first-account page says when /config cannot be written and what to do on the host (3cb1ed1)
- The install guide and the Unraid template no longer ask for a GitHub token or a docker login: the image is public (b3153f0)
- A container whose compose mounts the Docker socket starts on a node (2a605ef)
- A dev instance's rebuild pulls, stops and starts with the same build variables it builds with, and a build gets BB_BUILD_TAG, its version in a form an image tag accepts (ead0fa9)
- bb lint passes a compose file whose required variables are left empty in .env.example (a5dc372)

## 0.5.0: 2026-10-20

### Added

- The first public release of BuilderBot: a self-hosted workshop for Claude Code, a controller with a dashboard and the machines it enrolls to do the work. Everything it does is in [docs/features.md](https://github.com/aquilaelabs/builderbot/blob/main/docs/features.md); installing it is the [Quick start](https://github.com/aquilaelabs/builderbot#quick-start) and [docs/install.md](https://github.com/aquilaelabs/builderbot/blob/main/docs/install.md).
- The Android app is attached to this release, with its sha256.
- Upgrades from here on are carried forward by the controller, with a backup first: what is supported is under Upgrading in [docs/install.md](https://github.com/aquilaelabs/builderbot/blob/main/docs/install.md#upgrading).
