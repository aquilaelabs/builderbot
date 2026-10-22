# Changelog

## Unreleased

### Added

- A roadmap step can be meant for a release of its own, set from its Reword box or with bb roadmap target N.M: it says so on the step, the release chips count it, and bb roadmap --target lists its item under that release. (ab9d0d2)
- A day of a project's snapshots can be pinned from its row, and is then kept whatever the days kept say until it is unpinned; and daily snapshots have their own switch in Build and test, on as before, where 0 days used to be the only way to stop them. (77189ff)
- Controller settings has Room on the nodes: the disk a node keeps free, the memory level the bell warns at, and a memory limit for every container whose compose file sets none; a build also wants the room its last one took, and the hourly keeper clears build caches unused for two weeks (640b6ab)
- A node's setup fences BuilderBot's containers, sessions and jobs inside a share of its memory (builderbot.slice on systemd), so a runaway build or app is stopped before the system itself runs out; the Storage page says each node's fence (640b6ab)
- bb version forward and bb version backport move fixes between two release lines with the changelog kept right, and a project's patch rules hold what a patch release may change (640b6ab)
- tools/scan.sh runs the static analysis stack (Semgrep, Trivy, mobsfscan) with plain docker run, and docs/scanners.md says how to set it up (4ec0aa7)

### Changed

- Being on a project is enough for BuilderBot for VS Code and the Windows companion to open it, as far as your roles' File access goes: no grant of your own on the project's list is needed any more, and the companion lists every project you are on, each synced to a folder or not. A project's switch for them is on by default and closes them when turned off. (a0f86af)
- Android signing keys are now a project's own Signing view under Ship, out of its settings, and a key's downloaded backup can be imported there into the same project or another, its password and alias read from the backup
- Every notebook view now opens the way the Containers page does: one row with its search, its toggles and its actions (the Add last, as the main button), its numbers as tiles under it (the Roadmap's to send, shelved and finished, Bugs' open by severity, Git's changes and branches, Tests' passing and failing), a status line under those that holds the Roadmap's Save and Revert while something is staged, and every row of filter chips in one band
- A project's notebook has Sessions beside Overview: your own conversations there, any one to resume, read, download, make visible to every session on the project, or delete; they are no longer listed on your Profile (4ec0aa7)
- A project's notebook has Permissions beside Overview: everything a session may do on its own, asks first, or may not, with what it may push, in one place out of Settings and the Git view (4ec0aa7)
- Controller settings is a rail group of its own, Controller, after Containers; old links to it still land there (4ec0aa7)
- Signing keys are checked, generated, wrapped for a backup and rotated, and a release's APK is signed, on the project's node with its own jdk and Android SDK Build-Tools, never on the controller: install both on that node's Toolchains, and the Signing view and the bell say which node it is and what it lacks when it cannot

### Upgrading

- Every project's switch for VS Code and the Windows companion (Settings, Files) is turned on by the upgrade, so everyone on a project with File access in their roles can open it from their own machine; turn it off on a project that should not be. (a0f86af)
- Set SIGNING_SECRET (16 characters or more) in an *.env file in the secrets folder to seal the signing keys, and keep a copy of it with your other secrets: without it the keys stay as they were; lost, each key comes back by Import a backup (4ec0aa7)

### Security

- A signing key's backup downloaded from a project with a backup password is now wrapped under that password: the zip holds no password, and the key opens only with it. A backup downloaded before this holds its key's password in password.txt in plain text: keep those copies somewhere only you can reach, or delete them and download again. (3fe7f38)
- With SIGNING_SECRET in the secrets folder, every Android signing key and its passwords are sealed at rest, so a copy of /config opens no key; keys kept from before are sealed at the next start (4ec0aa7)

## 0.6.1: 2026-10-22

### Added

- A VM's hardware beyond its size, at New VM and in a stopped VM's new Hardware… dialog: its vCPUs pinned to host threads, a memory ceiling it balloons up to, the project's network or the LAN, a folder of the project shared in by virtiofs, and USB and PCI devices passed through by an administrator, with Dump vBIOS beside a GPU. A VM can start with its host, switched on its row. (fc44e419)
- A release's notes can show a committed picture from the repository with (file:PATH) in bb version release --edit, so a screenshot no longer has to be attached and listed among the release's downloads. (b28801de)
- A Claude session's bb vm does what a VM's row does: grow a disk, add one, eject an installer's ISO, pin its CPUs, give it a memory ceiling and a shared folder, and switch whether it starts with its host, each under the project's Make VMs setting; putting a VM on the LAN and passing a device through stay a person's. (c441b4f6)
- Alpine Linux can be picked in Enroll node without Offer dev features, walked on a real machine: a node there runs containers, CI runners and synced projects, and a toolchain that publishes a musl build, as Node does. Gentoo stays a dev system, and Enroll node says why when it is picked. (ff27d93a)

### Fixed

- A snapshot of a VM that boots by UEFI (Debian 13, an installer VM set to UEFI) works, where it failed; one made in 0.6.0 takes its first snapshot once it has been stopped (e4897281)
- An empty Containers or VMs page's tour shows an example row on a phone as well, where its step ringed the empty notice (04a802bb)
- Reopening the dashboard on a phone no longer asks whether to leave the page over unsaved data: a terminal's own leave warning is off, since nothing in a terminal is lost by leaving. (9c5be842)
- A VM whose job its node refused says why on its row, as the node said it, instead of an exit code. (ac9e0d8b)
- New VM's rows of fields are inset like the rest of the dialog instead of sitting against its edge. (1d903832)
- A VM made from an image bigger than the disk asked for boots, its disk made the image's size, where it stopped at an emergency shell; a Gentoo VM boots under UEFI, where it stopped at Booting from Hard Disk (ff27d93a)
- nginx deploys on a machine enrolled again under its old name, where Deploy said it was already on the Containers page (ff27d93a)

## 0.6.0: 2026-10-21

### Added

- FEATURES_OFF takes vms, for an install that should make no virtual machines: the VMs page says so, and making one or installing VM host is refused (296df6e0)
- Enroll node offers Debian, Fedora, AlmaLinux, CentOS Stream, Arch Linux and openSUSE beside Ubuntu and Rocky Linux, each walked end to end on a real machine (075ec223)
- About has Credits: the open-source work BuilderBot carries and runs, each with what it does here and its license (115a5fa)
- A short tour of each page the first time you open it, pointing at its parts one step at a time, with Skip tour and a box to skip it on every page; Show the tours again, in About and on Profile, brings them back. (310b392)
- Lock down on a hosting-only node's page, for a box that may have been taken over: one press stops every container there and its nginx, keeps them from starting at a boot, shuts its SSH door, and removes the node with its credential revoked, within five minutes even if the box never answers (edb13701)
- A VMs page in the Containers group: make, start, stop, snapshot, revert and remove a project's virtual machines on any node with VM host installed, from the cloud images of Ubuntu, Debian, Fedora, Rocky, AlmaLinux, CentOS Stream, Arch, openSUSE, Gentoo or Alpine, or from an installer's ISO you install yourself (Windows included), each with its own network that reaches the internet and the controller but not your LAN, a Screen in the dock, further disks and Grow disk. A project's Claude sessions can do the same with bb vm under a new Make VMs setting (deny by default), ask for an OS in words, and make a VM a node of its own. (8ba0d8e)
- A node's page has a Features section listing what the machine has (VM host, the hosting firewall, Claude sessions, the SSH door, the GPU driver, the Android emulator, a CI runner), with Install and Uninstall for VM host and the firewall and a way to each of the others; Enroll node can tick VM host. (c849623)

### Removed

- An agent from 0.5 no longer works with this controller: after updating, press Update agent on each node's row, which ends the sessions on that node; until then its projects' sessions are held. A session started under 0.5 is not carried over. (dfdf573)

### Fixed

- Enrolling a node never takes over an account that is already on the machine (a builder or bb of somebody's own): it stops and asks for another name, where it adopted the account and Uninstall then deleted it with its home (b17916df)
- A Rocky Linux node gets the tools bb capture reel --display needs, which never installed there (7041619)
- On a phone the Storage and nginx pages open one section at a time, sliding, as every other page does, where every section stood open at once (a18ac8e7)
- A session's pgrep -f or pkill -f inside a for loop over a command substitution is refused like any other, where it used to slip past and match its own shell (fea13264)
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
