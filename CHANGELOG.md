# Changelog

## Unreleased

### Added

- bb version release --withdraw TAG deletes a published release and its tag together, and the tag in the project's copy, so the number can be cut again; it is always the project owner's answer on the bell, and a tag whose release is already gone goes alone (7a8e367)
- bb version rehearse runs every build a release's tag runs on the pushed branch, publishing nothing, with a summary of the files the release would carry, so a release is tagged once it is green (7a8e367)
- A project can list the files each release must carry in .release-files; the controller checks every release against it once CI has had three hours, and a release short of a file is a red row on the bell naming the file and why (7a8e367)

### Changed

- A session's bb version release from a branch other than main makes a dev pre-release unless --stable is said, and its first line names the channel the release lands on (7a8e367)
- bb sign release waits for its look and says what it found, run by run, or why it found nothing to sign (7a8e367)

## 0.9.0: 2026-10-30

### Added

- An agent works the project's git host through `bb forge`: pull requests (list, view, create, comment, review, close, merge), issues, CI runs with their logs, reruns and dispatches, and releases, one set of verbs on GitHub, GitLab, Gitea and Forgejo, each run on the controller with the project's access token, which never reaches a session. The token is measured on the host without changing anything; the project's Permissions view gains On the git host, each ability with what the token allows and an Allow or Deny over it (merging starts at Deny); every session is told at its start what it may do there and what to ask for; and *Which permissions?* beside the token field opens the new git hosts page, the table of what to enable on each host. (3113eeb)
- A machine that is its own controller sets up its disks in its first run: you say how many disks may fail, it picks a ZFS layout or an array with parity from the disks there and says how much you can use and how it grows, names every disk it erases before it writes, and makes the Media, Backups and Projects shares after. (386d43e)
- BuilderBot OS's console shows BuilderBot's logo above the login prompt at every boot, with the release it runs and the address to open the dashboard at; the installer opens on the same logo. (68ba427)
- A tool pack or a catalog app can carry its own icon: `icon` in `bbtool.json` or `bbapp.json` names a PNG, WebP or SVG file in it (64 KB at most), which its Library card shows in place of its kind's glyph. It is read at the commit the pack is pinned to and shown only as an image, so an SVG's scripts never run. (fe8d6df)
- Two release channels: the releases as published, and a dev channel of the pre-releases CI publishes from a dev build (a vX.Y.Z-dev.N tag, the same files, never the latest), picked under Controller settings, Updates, where an install offers it; bb version release --dev cuts and pushes such a tag (8228751)
- Moving a controller to another home without losing its nodes: Prepare to move under Controller settings arms the move and shows a move token once, with no life on it, so a controller is prepared days ahead; every node hears the new address and a challenge of its own on each hello from then on, and the section says how many have; the bundle (the state, the deploy key, each store, the repositories and the install key as ticked, each with its size) is packed fresh each time it is downloaded; the new install's first page (Moving a controller here?) takes the token with the old controller's address and pulls the bundle from it, or with a downloaded bundle, holds it to the version gate, restores it and restarts; the landing is told both ways under the move key, so the old controller marks itself moved whichever side was up; it is read-only after, saying where it went, and tells a node that comes late its own challenge, so it knocks and follows like the others; the new controller's Nodes page lists the nodes not yet here with one line each (builderbot-agent follow) for a node that outlived the old controller, never enrolled again (72d59c6)
- Power under Controller settings on a bare-metal install and BuilderBot OS: Restart and Shut down for the machine the controller runs on, the same verbs This machine has (72d59c6)
- A held start on a bare-metal install: after a shutdown that was not clean, or when hold the next start was ticked beside Restart and Shut down before a restart, the install comes up with the dashboard, its agent and the network and nothing else (no agent session starts; a shell still opens) until Start is pressed on This machine, a band on every page saying it is held and why (0a822e8)
- This machine: on a controller installed bare metal the computer it runs on has a page of its own, first in the rail's Controller group, with what the machine is, the Updates section and everything a node's page draws (health, projects, sessions, features, storage, network, reboot and power off); it is no longer a row on the Nodes page or in its picker, and a project's node picker names it This machine (ae919d3)
- A bare-metal install updates from the page: a newer release is a line on the bell and an Updates section under Controller settings, Update runs the installer through the machine's own node (its root agent, never the controller's account), the release's controller bundle is fetched from the release and checked against its sha256 and its build attestation, and a new release that does not answer is rolled back by itself; each release now publishes builderbot-controller-X.Y.Z.tar.gz with its sha256 and attestation (2df7ee8)
- Tests run on a node picked for them: a project's settings gain a Test node beside its nodes, and with one named bb tests run, bb dashboard test and the gate's suites run there as a job (this tree snapshotted, as a build travels), with as many workers as that node's cores and memory allow, the lines streamed back, the run recorded and a covered run's counters merged here as a local run's are; a run behind another there says how many jobs are ahead (725635f)
- USB devices to VMs: a VM host's node page gains a USB section listing each device the machine has (name, vendor and product, serial, port, speed, the driver holding it) with what holds it, Give to a VM attaches it live to a running VM and writes it into its definition (a stopped one has it from its next start), Take back detaches it, a device is found again by its serial after a replug or a reboot and by its port when two are alike, a device the host boots from, serves storage on or has in a pool stays the host's with why, the VM's row names what it holds, and bb vm devices and bb vm usb let a session list and ask, held for an administrator on the bell; the section's Controllers list each USB controller with what hangs off it and its IOMMU group, given whole through the VM's Hardware dialog unless something the host needs shares the group; the Features section's IOMMU puts intel_iommu=on or amd_iommu=on with iommu=pt on the kernel's command line and asks for a restart (afbb962)
- The roadmap's steps move between items without losing anything: bb roadmap step mv takes a step to another item whole, split makes new items from an item's steps, fold makes an item a step of another, and each step keeps the number it was first given, so bb roadmap show R56.9 finds it wherever it is now; on the page a step has Move to, an item Split and Fold into, and in reorder mode a step drags onto another item (3b4d293)
- Every notebook record prints whole as JSON, YAML or Markdown (--format, or --json) on bb roadmap, bug, rules, wiki, design and map, from one serializer with a format number in each document, and the same formats come back in: bb roadmap add --from FILE and bb bug add --from FILE add the records in a file, and bb roadmap apply FILE writes an edited show back, refused when the list moved since it was printed; the code map reads data files too, so bb map find DASHBOARD_PORT names every file a setting lands in and bb map who-calls DASHBOARD_PORT where the code reads it (3b4d293)
- A model router on a node: a node's page gains a Model router section that deploys LiteLLM there with the provider keys you give it (Anthropic, OpenAI, Google, OpenRouter, xAI, and any OpenAI-compatible endpoint under a name of its own), kept sealed on the controller and never in a session's view, Ollama beside it where you turn it on with its models pulled and removed from the section, and the projects allowed to use it, each handed the router's address and a key of its own at a session's start so its spend is its own; the models the router knows, with their context and price, and each project's spend are read from the section (a82d20e)
- Any model as a fifth coding agent: OpenCode, pointed at a node's model router rather than signed in to anybody, offered by Start as Any model with the router's models (their context and price where known) and started with a config of its own (the router as its provider, the briefing as its instructions), its guards a plugin of BuilderBot's calling the same hooks as the other agents', its conversations exported into the transcripts; the Library installs and updates it as the others; the picker marks the models walked with it and says when one's context cannot hold the briefing, and its tab on the dock says the project's spend through the router and a local model's tokens per second (a196894)
- The bell reaches you elsewhere: Profile's Where the bell reaches you takes email (through the SMTP server under Controller settings, Mail), a webhook, ntfy, Gotify, Pushover, Telegram, Discord or Slack, each with the kinds it takes (an ask waiting on you, what a node needs, a red CI run, an invitation, a file changed in two places) and a quiet window; a row goes once and not again while unchanged, Test checks the way, and a token or address is sealed under the install key (c41c804)
- A Scanners page in the Containers group beside nginx: BuilderBot's own static analysis scanners (Semgrep, Trivy, mobsfscan) deployed to each node that holds projects as a compose project with their versions pinned, run there on one schedule (daily, weekly, monthly or a timetable of your own, and Run now) over the projects whose node it is, each node sending its SARIF up to the controller so nothing is mounted for it; the page says each node's state, Update when newer versions are out (checked weekly), the last run with its log, and the projects nothing covers with why; a failed run and versions behind are on the bell (12af2fa)
- The threat model is written down in docs/security.md: who is trusted for what, what each store protects and does not, what an unlock gives up, and the line each hardening step closes (1493a5c)
- A person's key store opens less at a time: a token is opened per use for the window picked on Profile, Your key store (a quarter of an hour, an hour, eight hours, or while signed in), Lock lets go of everything opened, and Uses of your tokens lists each opening with what it was for; git is handed an opened token for that window and never opens the store itself (da2e647)
- A key of the person's own: Hold the key yourself on Profile moves the key store under a passkey (one that answers PRF; a new passkey asks for it) or a key the person keeps, which this BuilderBot never holds, so not even its owner opens what is in it; it opens only while they unlock it, their pushes and pulls say when it is locked, a terminal on a node asks for the unlock first, the tokens projects run CI watching and releases with go to each project's own keeping at the move unless kept, and Give the key back moves it under the install key again; a device signed in as the person may unlock with the key they keep (da2e647)
- A browser's sign-in is bound to the browser it was made in: its cookie presented from another browser is refused, Profile's Signed in as you lists each browser signed in as you (its system and the address it came from) with Sign out, and Controller, Audit is who did what to this install, newest first, narrowed to a person or a machine (75aaf5f)
- The nginx page gets certificates from Let's Encrypt: Get one from Let's Encrypt asks for a hostname's pair by an HTTP-01 challenge the node's nginx answers or a DNS-01 record written through the Cloudflare API token, keeps it like a pasted pair and renews it thirty days before it ends, with the result on the bell (ccb1e29)
- BuilderBot OS, the appliance image the installed editions are made from: Debian stable pinned to a dated snapshot with ZFS built against its kernel, the controller staged in as a bare-metal install lays it out, a read-only root in two slots so an update is a whole image and a bad one falls back, GRUB for UEFI and BIOS, /var and the changes to /etc the only things that persist, and the machine its controller's own node at its first boot; built by image/build.sh, in CI on every release tag (docs/image.md) (03d24cd)
- VMs on the controller's own machine: VM host installs on a bare-metal controller's machine too, its VMs run through the node's root agent with the jobs account kept out of libvirt's group there, and the VMs page lists for an administrator the domains a node's libvirt has that BuilderBot did not make, under Not BuilderBot's, read-only (c641b4b)
- BuilderBot OS in a VM: a VM installs from the ISO as a machine does, so a hypervisor is the easiest place to try it; a release carries the OS as two files, the ISO and the USB stick's image (14f007e)
- BuilderBot OS updates from the page: on a machine running the image, Update under Controller settings fetches the release's ISO, checks it against its sha256 and its build attestation, takes the root, kernel and initrd out of it, writes the slot not in use and names it for the next boot, the restart yours from This machine and the slot running now kept to fall back to; an offline machine takes the same files from a folder; an Update window under Controller settings applies a newer release by itself at an hour, daily or one weekday, off by default (b583bae)
- BuilderBot OS installs from an ISO: it boots the same root live with an installer on the console that asks for the disk (everything on it lost, said first) and the features to turn on at the first boot, lays the disk out with the very script that made the image, the data partition grown to the disk, and restarts into the machine as its own controller and node; the ISO's second entry boots the live system without installing (b2cab06)
- BuilderBot OS on a stick runs from memory: with the switch set in GRUB's environment the slot is copied into memory at boot, exactly its bytes, and the system runs from the copy while the stick keeps the configuration apart from both slots; the slot tool reads and sets the switch (e0d7654)
- A BuilderBot OS update boots on trial: the slot an update wrote boots as a trial, the health check marks it good once the dashboard answers and the agent runs, and a second boot without that word goes back to the slot before by itself, said on This machine; the boot menu names each slot's version and offers Safe mode, which brings up the dashboard and the shares and starts nothing else (the start is held); the controller's configuration is copied before an update, kept beside the old slot (668715b)
- This machine sets the machine's name and time zone: a Name and time section on the controller's own machine, each set on the machine by its root agent, the zones offered as a list to type into; the first-run page's This machine card says the name, the address and the clock's zone, and where to change them (b18d6fe)
- The Storage page lists the controller's own machine's disks: each by name, model, size, serial, spinning or solid state and what each partition holds, with SMART's health, temperature and hours where the machine has smartctl, the system disk marked; read before anything is written to one (c56141b)
- Storage and shares are features of the controller's own machine: its Features section installs ZFS, mergerfs, SnapRAID and SMART as Storage and Samba and NFS as Shares, each with exactly its packages, removed with them and refused while a pool or a share stands; the row says which tools answer (6c8a995)
- Shares on the Storage page: the controller's own machine's SMB and NFS shares, each a folder on a pool given to the machine's users or to everybody as a guest over SMB and to named clients over NFS, read-only or not, with Remove; every press a job the machine's root agent runs, which writes BuilderBot's own share files whole and tells Samba and NFS to read again (a041fd2)
- The configuration backed up onto the machine and found again: with a backup password set under Controller settings, a sealed copy of the state (the same bundle a move carries) is written onto every pool of the controller's own machine and under the state after every change, the five newest kept and each downloadable, and a fresh install's first page offers Restoring a saved configuration: a copy found on its disks or one you kept, and the password, and it becomes the controller as it was (c86dcfe)
- The USB stick maker: tools/builderbot-stick.py writes a release's stick image onto a USB stick on Windows, a Mac or Linux with nothing but Python's own library, lists the removable disks and never writes the system disk, fetches the image with its sha256 and checks it, says what is on the stick is lost, writes the disk whole and reads it back; the release carries the stick's disk beside the ISO, the slot loaded into memory at boot (6a559f9); it writes the newest release when none is named, and `--set KEY=VALUE` puts a line in the stick's builderbot.env as it writes: TZ, BB_RELEASE_LINE, and the network settings BB_HOSTNAME and a static address (BB_NET_ADDRESS, BB_NET_MASK, BB_NET_GATEWAY, BB_NET_DNS) the machine takes at each boot in place of DHCP; each boot grows the stick's data partition to the stick's size, `BB_DATA_MAX` capping it; on a stick boot the logs and the journal are kept in memory and docker, the VMs, the toolchains and the projects write to a system pool picked under This machine's The stick, which also says what the stick has written; `--config FILE` puts a prepared configuration on the stick (the machine's name and time zone, the owner, the people), which the first boot applies before anyone signs in and says on This machine (c014595)
- ZFS pools on the Storage page: the controller's own machine's pools as zpool says them (size and what is used, health, the members by layout, the last scrub), each with Scrub, Export and Destroy, and a new pool made from a name, a layout and the disks it takes, each named by model, size and serial and said again before anything is written; every press a job the machine's root agent runs, the system disk never offered (0cae2c5)
- Snapshots of the controller's own pools: the Storage page's Snapshots section counts each ZFS pool's snapshots by kind, takes one now, rolls a dataset back to one (its name typed again) or deletes one, and saves a schedule per pool (hourly, daily or weekly, with how many of that kind to keep; the oldest past that goes as the next is taken), each a row on the Schedules page that runs as one of the machine's own jobs rather than a script (b25236b)
- People on shares: a share on the controller's own machine is given to BuilderBot accounts and roles by name (a role names everybody holding it now), each person sets an SMB password of their own on Profile, where Your shares lists the shares named to them with the address to map each by on Windows and a Mac, and a share can be a Mac's Time Machine target (e9c5e12)
- An array of mixed disks on the controller's own machine: the Storage page's Array section makes one of data disks of any sizes (each its own xfs or btrfs filesystem, pooled into one tree by mergerfs with the policy picked for where new files land) and one or two parity disks kept by SnapRAID, adds a disk, replaces a slot's disk with its files rebuilt from parity, runs a sync, scrub or check now and schedules the sync and the scrub as rows on the Schedules page; parity is periodic, which the page says, and destroying the array leaves every disk's files readable on any Linux (14f007e)
- Disk health on the bell, and disks spun down: a disk SMART calls failing, a disk running hot, a pool not online or an array disk gone on the controller's own machine is a row on the bell (a kind of its own under Where the bell reaches you, so it can go out by email or a push) that leaves when it stops being true, and This machine's Name and time gains Spin down disks, which stops the spinning disks but the system's after the idle time picked and sets it again after every boot (5d14606)
- A UPS and the system's own updates on This machine: the UPS feature installs NUT for a USB UPS, the Power section shows its charge, the minutes left and the load, the bell says when the machine runs on battery or the battery is low (sendable by email or a push), and NUT shuts the machine down cleanly on a low battery; on a bare-metal install that is not BuilderBot OS, Updates under Controller settings also counts the system's own package updates once an hour, says which are security ones and whether a restart is needed, and applies them with apt from the page, restarting after when asked (7918b2d)
- Reporting on This machine: the controller's own machine's CPU, memory, network in and out, disk reads and writes and the CPU's and disks' temperatures are kept for weeks at falling resolution (five-minute means for two days, hourly for two months) and drawn in a Reporting section over six hours, a day, a week or a month, the hour's charts unchanged (0778cbf)
- Other disks and shares on the Storage page: a USB or eSATA disk plugged into the controller's own machine, or an SMB share or NFS export on another machine, is mounted at /mnt/other by name as a backup target or a source to copy in, never pooled, with Eject unmounting a disk so it is safe to pull; the record is the controller's, a share's password sealed under the install key, and the machine's agent follows it within a minute (8aa403b)
- Backups off the machine: the Storage page's Backups section copies a folder on the controller's own machine (a pool, the array, the controller's state) to another place (another pool, the array, a disk or a share under Other disks and shares) with rsync, each run a dated folder sharing what did not change with the run before and the oldest pruned past the runs kept, run now or on a daily or weekly schedule that is a row on the Schedules page; the last good run is a tile on Home, and a run that failed or a scheduled backup two days without one is a row on the bell (4df8513)
- Pools by purpose: a new share picks the pool or the array it lives on and names its folder there, and a pool of one disk (an SSD holding the hot data) gets a one-press nightly backup to the array under Backups, so a dead disk is restored from last night's run; no cache tier and no mover: writes go to the pool a share names (f8f7751)
- Encrypted pools: a new pool can be made with ZFS native encryption under a passphrase, its key either kept on the machine sealed under the install key (the pool unlocks at every boot, the disks unreadable pulled from it) or asked for on the Storage page after every boot (the whole machine taken is covered too), the choice said with what each protects against and changeable later; a locked pool is a row on the bell and its shares say so rather than vanishing, and Safe mode boots with every pool locked (3c6c521)
- Apps a NAS runs: New container on the Containers page offers a catalog of ready apps (Jellyfin, Plex, the arr stack, qBittorrent, Immich, Nextcloud, Home Assistant, Syncthing), each filled in from a few blanks (its data folder, its media or files folder, the user it runs as, the time zone, its port) into a compose file pinned to a tag and an environment the Create makes as any container, reached on its port on the node and put behind a hostname and a certificate on that node's nginx page (1fc3563)
- A VM may belong to the machine rather than a project: Belongs to on New VM offers This machine's own to an administrator, for the NAS's own apps and desktops (a Home Assistant VM, a Windows desktop), grouped as such on the VMs page, administrators' alone and never a session's (04c0799)
- One manifest for everything: every shipped toolchain and every coding agent is a pack in bbtool.json's format under packs/, tagged official and bundled with the release for an install with no network, a toolchain's recipe under shipped and an agent's adapter (how it installs, updates and signs in, how it takes the briefing and BuilderBot's guards, where its conversations are) under agent; an agent that cannot take the guards is not listed, and bb lint holds the packs to the tables they are written from (3aa2613)
- The vetted catalog's signed index: BuilderBot reads the catalog's index.json and index.sig from the address under Controller settings (the public builderbot-catalog by default), checks the signature against the maintainers' public key the install ships before reading an entry, refuses a tampered or re-signed index and keeps the one before, and puts a pack the catalog withdrew on the bell for every install that holds it; each entry pins a pack to an exact commit and its archive's sha256, never latest (c9eebb7)
- Install from the vetted catalog: the Library lists the index's packs with their tier, each Install opening the Add tool pack dialog on the commit the index pins with the archive's sha256 checked on the way in, Look before Add as always; every pack's row says its tier (vetted, or by URL), and a withdrawn pack is said and not offered (a196894)

### Changed

- Every page's top reads in one order: a notice, the page's head, its number tiles, then the search with the page's buttons at its right, the filter chips under it and the small jump chips over the sections they lead to; a notebook view the same, its tiles first. A single action sits in its head's top-right corner or beside the words it belongs with, never on a line of its own, and on a phone the search keeps its buttons on its line while they fit. (61c8237)
- The Machines, Build and Containers headers keep one node for every one of their pages, and no page names that node again under the header. (61c8237)
- A page's state reads as a state pill, an update check is Check for updates everywhere, Users and Roles have a head with their counts, empty lists say so in one quiet line, and the Phone page is two plain steps, Connect and Pair a new phone. (61c8237)
- BuilderBot's mark is the robot head in isometric line work, in the mark's greens: the big mark at the top of the README and the About screen, the solid small one as the favicon, the top bar's mark (in the theme's color, red while the controller is away) and the phone app's launcher and status icons (a5fe690)
- The Machines, Build and Containers groups each wear one header over their pages, in a project's shape: the node picked once where a project's name is, with when it was seen, where it dials in from and its agent beside it, the group's sub-nav under it with the group's own actions at its right (Machines: Create sandbox VM and Enroll node); every page of the group follows that one pick and carries no picker of its own, the Containers page's search growing into the picker's room, and a sub-tab says not here when the picked node lacks what it needs (nginx not deployed, no Docker, no Android tools or adb, no CI runner yet); a notebook's restart note is a band between its header and its view strip, put away with its x for as long as it says the same (05dd7bb)
- A Network page in the Controller group says how the controller is reached (its address and port, what it is served over, which nodes dial in and from where), and Connection and Reach from outside live there now rather than under Controller settings (0602655)
- The repository is laid out by what each part is: the companions a person installs live under apps/ (apps/android the phone app, apps/vscode the editor extension, apps/windows the Windows companion) and each place the container edition installs under platforms/ (platforms/unraid/builderbot.xml, the Unraid template, which moved there with no copy at the old path: a template installed from the old raw URL is pointed at the new one by hand, once); the installed edition's own parts land beside them as they are built; release assets keep their names (e4bacde)
- Every git action is a person's, with their own token: each person gives a project their own token for their pushes, pulls and releases, used only while they are signed in on a browser or a device, and the project keeps none of its own; its settings list who has given one, the Git view says whose token a press would use, a session whose person is signed out everywhere is told that bb git waits for them, and watching CI pauses, said on the project, while nobody who gave a token is signed in (46493b1)
- The node agent's compatibility window moves to 0.9: a 0.8.x agent still seals sign-ins the way before, which the controller opens, but a controller from 0.8.x cannot open a seal a 0.9 node made nor read a node's config without the two network switches, so every node is updated with the controller, which it does by itself (1e534c6)
- Update checks under Controller settings: each check BuilderBot makes by itself (a newer BuilderBot, the container images, nginx, the scanners, the Library's versions and catalog) daily, weekly, monthly or off, with when it last ran and Check now; a node's own version check is its row's Version check. A newer BuilderBot is now looked for weekly rather than daily, like the rest (b0eb924)
- The Library: one page under Build for everything a BuilderBot installs or runs on a node (the coding agents, the toolchains, the tool packs, the apps a NAS runs and the companions for your own machines), each a card with its tier (official, vetted or sideloaded), what it is and one Install, Update, Remove or Download; a card opens on its whole description; a search box and chips by kind and tier; Add your own takes a tool pack or an app's compose file of yours, looked at before it is kept. The Toolchains, Agents and Apps pages are this page now, and are gone: the Library offers, the Installed page under Machines holds, a companion's download is a Library card, and an address naming one of the old pages opens the Build group. (2083e35)
- A tool pack may name the BuilderBot release lines it works with: one that does not name this install's is not added, and one held that stops fitting after an upgrade is said on the bell (a05dda7)
- A tool pack says what it touches (the hosts its install fetches from, and whether it needs root), shown on Look; one that needs root is added by an administrator alone (e3e4592)
- A session can look through the vetted catalog with bb tool search and ask for a tool pack with bb tool install, as a new Install a tool pack setting under Agents may says (ask by default: a person who may curate the catalog answers on the bell) (ef5b215)
- A tool pack names its system packages for each package manager (apt, dnf, pacman, zypper, apk), as the shipped toolchains do; a node whose manager it names none for is told so on the pack's card and its Install there is refused, and Look lists them (8aed56e)
- A mirror of the vetted catalog for a controller without the network: tools/catalog-mirror.py makes one on a machine that has it, and Controller settings' new Vetted catalog group imports it (refused unless the index is the maintainers' and complete), the Library then reading its index and installing its packs and apps with nothing fetched; the same group sets the catalog's address, and the stick maker's --mirror carries one on a USB stick, imported as the controller starts (30d91f3)
- Catalog update: a tool pack kept from the vetted catalog offers the newer commit a later index pins on its Library card, the dialog showing what it changes before Update keeps it, its tier kept (9e48fd2)
- Docker apps in the vetted catalog: an app entry is an Apps card on the Library, and Install fetches it at the commit the signed index pins, keeps it and opens New container with it picked on the Library's node (25ae3ea)
- A pack's setting may be each person's own: a config field with `"scope": "person"` is set under Yours on the Installed page's row by anyone who works on that node's projects, sealed under their own key and read by their own sessions' verbs (8f2fabf)
- Configure on the card: a tool pack says in its manifest what it asks for on a node (keys, choices, a list of endpoints, a switch, the projects allowed), a new Installed page under Machines, with the node picked, lists what the Library put there and draws that form on each row, keeps the answers sealed and hands them to that node for the pack's verbs; an agent's sign-in, a toolchain's system packages and Remove live there too, the Library's cards showing the catalog's entry alone; the Model router is installed from the Library and configured on Installed, and its section leaves the node's page (5155820)
- A person keeps one token for each git host and sign-in: a new one replaces the one before in place, every project using it moves to the new one, and the older tokens an install already kept for the same host are let go at the upgrade (fb7bd4d)

### Upgrading

- The Toolchains role area is three (migration 0017): Install (what Toolchains Write did), Configure (a service's and a pack's settings on a node, which needed an administrator or writing containers) and Curate (adding a pack or an app of your own, an administrator's). A role that held Toolchains holds Install at the same level, and Configure where it also wrote containers everywhere; give Curate to a role of your own on the Roles page where someone besides an administrator adds to the catalog. (ea68356)
- 0.9 upgrades from any 0.6.x, 0.7.x or 0.8.x release in one step. A 0.5.x or older `/config` is refused with the way through: start the newest 0.6.x on it first. (a196894)
- A bare-metal install moves forward only: `install-controller.sh --rollback` is gone. An update whose new release does not answer still goes back to the one before by itself, its state copy put back. (a9f3e3f)
- The scanners move onto the nodes: open the Scanners page under Containers and press Deploy on each node that holds projects (one press for all of them), and the schedule carried over from the Schedules page runs them there; a host scanner writing into SCANNER_REPORTS_PATH is still read this release and not the next, so take it out of your cron or User Scripts once the page's first run has landed on the Analysis page (12af2fa)
- Accounts become users of their own on every node as this version's agent lands there: a home moves once the account's sessions started before have ended, and until then that account's terminals open the old way; nothing to do. A sign-in is sealed the next time its person opens a terminal on the node or signs in there, and a session can start for an account only while somebody has opened a terminal for it on that node in the last five minutes, so a scheduled start for an account nobody has opened waits for them (44cef34)
- Signing in again once after this upgrade: a browser's sign-in now has a record of its own, which says when a person's tokens may be used, and the cookies from before carry none. A project's token from 0.8.0 stays its owner's for that project; everyone else on it gives their own in the project's settings (Give it to this project) before their pushes go (46493b1)

### Fixed

- A container's Ports and mounts reads again when its compose file needs the node's docker group (`${BB_DOCKER_GID:?...}`): the read asked compose without it, so it said the file could not be read on every open. When compose does refuse a file, the row now says what compose said. (d23620a)
- Switching a phone's browser to its desktop site, or a browser updating itself, no longer signs you out: a sign-in is held to the browser it was made in (Safari, Chrome, Firefox) rather than to its whole identifying string, and a cookie taken to another browser is still refused. Sign-ins kept from before stay signed in through the upgrade. (2b91ef6)

### Removed

- The built-in static analysis scan on the Schedules page, and tools/scan.sh with it: the Scanners page runs the scanners now, and an install's scan schedule became the page's schedule (migration 0016); SCANNER_REPORTS_PATH is deprecated and removed in the release after (12af2fa)
- The two dev switches on a node's Sessions section are gone: every account runs as a Unix user of its own on every node that runs sessions (its home, its sign-ins and its terminals are its alone, and only root reaches them), and the coding agents' sign-ins are kept sealed there, Copilot CLI's with the others now, each opened only while its person has a terminal open on that node, so a copy of the node's disk signs in to nothing; the rows say whether each is in force (44cef34)
- The two node switches deprecated in 0.8.0 are gone: every session is kept to its own project's network and every project's containers to their own, on every node that runs them, with no checkbox; a key an older build left in a node's config is read as on (1e534c6)

### Security

- Every seal is on vetted cryptography: what the controller keeps sealed (the accounts' keys and key stores, the signing keys, the settings' secrets, two-factor secrets) is ChaCha20-Poly1305 under a key HKDF derives from the install key or the account's, and a node seals the coding agents' sign-ins with X25519 and ChaCha20-Poly1305, all from the cryptography library in the image and on every node; what was sealed the way before is sealed again at the next start, and on a node the next time its person opens a terminal there, and the old format is still read this release (1e534c6)
- The dashboard is served over https where it can be had: Controller settings' Connection section picks http, the install's own certificate (made at the switch, its fingerprint shown for the phone and the companion to pin, its private key sealed under the install key and listed on the Keys page) or a Let's Encrypt certificate for the controller's hostname by a DNS-01 record through the Cloudflare API token; one port serves both, so a node keeps dialing http while a browser gets https; a fresh install starts on http, and the Doctor and the section say so until https is on (e6d74b8)
- The page runs only what it ships: a Content-Security-Policy allows the page's own scripts and styles and nothing inline that is not in the file by its hash, each script tag names its file's integrity, cookies are SameSite=Strict, and what a browser refuses under the policy is kept and said by bb doctor (41d8fe9)
- The dashboard and the node agent keep the keys they hold out of core files and swap: neither writes a core dump or can be read by another process of its user, each locks its memory where the memlock limit allows (docker-compose.yml, the Unraid template and the agent's unit raise it, and bb doctor says when it could not), and a key or an opened sign-in is zeroed once let go (b2635de)

## 0.8.2: 2026-10-27

### Fixed

- A pick list under a field (moving a repository to another project, a project's group) takes an option on a click, so pressing on the list to hold and scroll it no longer takes the option under the pointer (6d22e0b)
- An empty project left beside a new repository's by the 0.8.0 bug fixed in 0.8.1 (its name the repository's with its id, such as NAME (P43)) is named on the bell, with Delete on the row; nothing is deleted without that press (cc6c3e7)

## 0.8.1: 2026-10-27

### Changed

- A session reaches a remote only through bb git: git's own push, fetch, pull, ls-remote and remote update are refused in a session, so the project's credential, git policy and scan for secrets cannot be gone round with a token of its own (5a34a53)

### Fixed

- A release whose tag could not be pushed says why, in git's own words, rather than only that the push failed (f36411f)
- A release whose tag was pushed by hand after its own push failed can be finished: releasing again makes its page on GitHub rather than refusing the tag that exists (256ad29)
- A project's push or fetch outside a session (a release's tag, a check of a repository's address) is handed BuilderBot's own credential wherever it is kept, and a checkout left pointing at git's own credential store from an earlier release is moved off it at start: those went with no credential once tokens were sealed (37fd44e)
- A repository made with Add repository on a project's card stays in that project: it could land in a new project of its own when the page refreshed while it was being made (0eaf6d2)
- bb git push of a tag says it is a release's, pushed by bb version release, rather than that the tree has no such name (0eaf6d2)

## 0.8.0: 2026-10-27

### Added

- Projects come first: a project is made with a name alone (spaces and punctuation kept) and repositories are added to it, each keeping its own notebook, git host link and releases; its card lists its repositories and who is working there, and Edit turns it over to rename, move a repository to another project, delete one to the trash, and set its color, group, pin, archive and lock. A project has one id and one coding-agent session that works in all its repositories, and a project that reads it reads every repository in it (9ccf960, 178952e)
- Terminal colors can be changed one by one under the preset you pick, with Reset to go back, and a preview on your Profile and in a project's own settings shows how your terminals will look (48dbbe9)
- You can run several sessions of one coding agent on a project at once, each in its own worktree and conversation (Claude 2 beside Claude). Start agent lists your running sessions with Open, Restart and End, starts a new one, or resumes any of your conversations there; one already running is not offered twice. A project's settings say how many each person may run (three unless changed), and a Send with several running asks which one (efdf884)
- A Schedules page beside Jobs runs an administrator's own scripts on a timetable: each on a node of yours, as its jobs account or as root on a sandbox node, every run a job with its log, a failed or skipped run on the bell. The static analysis scan is built in, off until you turn it on with its node and paths (380cc7a)
- Controller settings' BuilderBot bug reports section lists every report with its own delete, so one can be taken out before the diagnostics are downloaded. (c2ece51)
- A container that has to talk to a machine on your LAN, such as a device or another server, can be let through the network wall around each project's containers: an administrator turns on Reaches the LAN in its settings on the Containers page (881deec)
- An install makes its own install key at its first start, so nothing has to be set to keep its tokens, signing keys and sign-ins sealed: Controller, Keys shows where it is kept, shows it to save, changes it with everything kept under it sealed again at once, and lists what is kept under it. Each account has a key of its own for its agents' sign-ins on the nodes, changed from Profile, Your key (fd6c02f)
- Each person keeps a key store of their own: a token they give a repository (in its settings, or cloning or linking it) is kept under their own key and used for their own git work ahead of a project's, and another of their projects can use it from its settings; Profile lists what it holds, never showing it; Purge empties it, and deleting the account does too, unlinking the projects that used it (0f4af38)
- A session sees a release's Android signing: bb sign status says whether the APK can be signed and how the newest went, bb sign release asks for it again under Sign a build, and a release whose APK could not be signed is said before the tag, on Release's confirm and by bb version release, which goes on only with --without-apk (60d1d3e)
- A bug and a BuilderBot report say whether they reproduce: always, sometimes, once or not tried, asked under the steps on the Bugs form, shown on the opened row, and a chip and a sort on the list; bb bug add and bb report take --reproduces, and bb bug add --report N files a diagnostics report with its words, steps and answer (2517bcb)
- Grok (xAI's Grok Build) can run a project's session beside Claude, ChatGPT and Copilot: installed from its node's Agents page, signed in there with a device code, and held to the same briefing and guards through its own hooks (dc85506)

### Changed

- SIGNING_SECRET is INSTALL_KEY: the one key that seals at rest what BuilderBot keeps, the signing keys among it (7645fec)
- Terminals are BuilderBot's own, drawn in the page itself, and ttyd is gone from the controller and the nodes: a finger scrolls a terminal on a phone and a press held on a word selects it to copy, a job's, a container's and the controller's logs follow in a tab of the dock, a terminal that ends says why, and a tab popped out opens the same terminal in a window of its own. A node's terminals come in on the one port its VMs' screens use, so its firewall opens 7684 alone (052c096)
- Every page states what it knows in a head at its top (its name, its state and its facts in a grid) in place of loose lines of text (48dbbe9)
- Each session and each project's containers are kept to their own network on every node: a node that had either switched off has it on again after the upgrade, since which projects reach each other is set by their Reads. A hosting-only node's containers are kept apart the same way. (c2ece51)
- Download diagnostics moved from the Logs section to the BuilderBot bug reports section, beside the reports it carries, and anyone who can open Controller settings can read the reports and download the diagnostics there. (c2ece51)
- A shell keeps its history in memory for itself alone, never in a file in the home, where the account's own coding agents, which run as the same user, could read what was typed; the same for the Python, Node, psql, sqlite, mysql and less history files (ba0eeb8)
- Turning maintenance mode on ends every other account's coding-agent sessions and terminals, here and on the nodes, after asking: the question lists each with whose it is, its project, whether it is working or waiting, and its node (12966dc)

### Upgrading

- Rename SIGNING_SECRET to INSTALL_KEY in your secrets folder's env file: the old name is read for this release only. With an install key set, everybody is signed out once at the first start of 0.8.0 (7645fec)
- Update the Android app and the VS Code extension (0.2.0) with the controller: they open a session's terminal on BuilderBot's own terminal now, and an older copy of either cannot open one (052c096)
- Each project you had becomes a project holding its one repository, under the same name, with its settings, people, owner, pins, groups, colors, archive and lock; nothing on disk moves. New project now asks for a name alone, and Add repository on its card makes or clones the repository (178952e)
- The secrets folder is mounted read-write now, so the first start can make the install key in it: on a NAS host set the Secrets directory's access to Read/Write, and in compose drop :ro from the /secrets volume. An install with INSTALL_KEY set keeps it, and the Keys page says to change it there (fd6c02f)
- An install with INSTALL_KEY set and its secrets folder read-write copies that key into the folder at its first start, so INSTALL_KEY can then be taken out of the secrets folder: the install carries on with the same key, changed from Controller, Keys (8cc38de)
- The shell and REPL history files in each account's home on a node (.bash_history, .python_history and the like) are removed the first time a terminal opens after the update: copy out anything you want to keep first (ba0eeb8)
- A project's git token kept before is moved into the project owner's key store at the first start, BuilderBot's owner taking those of a project with none; a build from before refuses to start on that state (c5b9205)

### Deprecated

- The two node switches that turned those networks off (in a node's Sessions section) go in 0.9.0. Nothing to do unless a project's containers relied on reaching another project's: add that project to its Reads. (c2ece51)

### Fixed

- Pressing the filter chip or the settings section that is already selected no longer redraws the page with a fade (4a237e5)
- On a desk the dock's line of tabs, with more tabs than fit, has an arrow at each end with more past it and can be dragged with the mouse (8abd211)
- A VM made again under an earlier VM's name no longer shows that VM's address until its node next reports (3b9c386)
- Enrolling a node or installing on a machine just booted from a cloud image waits for the machine's own first apt run to let go of its lock, instead of failing at the first package step (3b9c386)
- A release's signing pressed again on the Signing view is followed to its end: the Releases section re-reads when the look finishes, rather than showing the old failure until the view is reopened (a1611e7)
- Saving a project's settings with End ends a ChatGPT or Copilot session there too, not only a Claude one, so the next start picks up what was saved (7c9b38a)
- The bell's CI failing row can be dismissed until another run fails, and a check that has passed since on a release no longer stays red (9cfe9f4)
- Signing a build or a release keeps the key in the node's memory while it works, never on its data store, which on a shared network folder sessions could read (5da1f79)

### Security

- With an install key, the key sign-in cookies are signed with is made from it and kept nowhere, so a copy of /config can forge no sign-in (7645fec)
- With an install key, the tunnel's and Cloudflare's tokens are kept sealed in the controller's settings, so a copy of /config holds neither (13812ea)
- With an install key, each project's git token is kept sealed and handed to git by BuilderBot's own credential helper, for the host it was written for alone, so a copy of /config pushes nowhere (b1c372e)
- A node's token is replaced at each of its check-ins, and one it has given up presented again revokes the node and says so on the bell, so a copy of a node's disk cannot pose as it for long (bd54513)
- A toolchain's download is checked against what its publisher says it is before it is unpacked or run, its checksum or its signature, and refused naming both digests when it does not match; the Toolchains page and bb toolchains say how each installed toolchain was checked, or that its publisher states nothing to check it against (690cd2e)
- A terminal or a VM's screen opens only from the dashboard's own page: a connection started by another site's page, such as an app on a sibling hostname, is refused (f96a91d)

## 0.7.0: 2026-10-24

### Added

- A roadmap step can be meant for a release of its own, set from its Reword box or with bb roadmap target N.M: it says so on the step, the release chips count it, and bb roadmap --target lists its item under that release. (61179cb)
- A day of a project's snapshots can be pinned from its row, and is then kept whatever the days kept say until it is unpinned; and daily snapshots have their own switch in Build and test, on as before, where 0 days used to be the only way to stop them. (e13dbfb)
- Controller settings has Room on the nodes: the disk a node keeps free, the memory level the bell warns at, and a memory limit for every container whose compose file sets none; a build also wants the room its last one took, and the hourly keeper clears build caches unused for two weeks (1cd0bc5)
- A node's setup fences BuilderBot's containers, sessions and jobs inside a share of its memory (builderbot.slice on systemd), so a runaway build or app is stopped before the system itself runs out; the Storage page says each node's fence (1cd0bc5)
- bb version forward and bb version backport move fixes between two release lines with the changelog kept right, and a project's patch rules hold what a patch release may change (1cd0bc5)
- tools/scan.sh runs the static analysis stack (Semgrep, Trivy, mobsfscan) with plain docker run, and docs/scanners.md says how to set it up (e7190d6)
- Codex CLI (ChatGPT) and Copilot CLI (GitHub) run beside Claude Code: the new Agents page installs, updates and signs in to each on a node, a project's Start offers each one signed in there, and its settings say which agents may run and which one Start opens. Every Agents may dial, house rule and guard holds for them as for Claude, and their conversations are kept, read, shared and resumed on the Sessions view. (90bec19)
- The Android app has the dashboard's light half of every color scheme, and Dark, Light or System beside the schemes under More; its colors are the dashboard's own, written from the design (acc4dfa)
- Lock keeps a project to its owner: the owner's Lock ends every other session there and holds everybody else out of starting one or changing it until they unlock it; an administrator's Admin: Lock holds the owner out too. A locked project stays on the Projects page with its padlock (24c9a24)
- A store move waits for its node to be quiet, holds the node's sessions without ending them (each is told what is moving and how far it has got, and may still keep its notes), and lets them go when it is done (f6572b0)
- A node's Storage and Network have Revert beside Save, and saving a store inside a mount that is not on the node yet, or adding a mount over a store, says what will happen first (c1da3b1)
- The Storage page lists each project's emulator phones with their size, last start and snapshot, and a disk past 90% says what of it can be freed and on which page; the Emulator page's new Phones section removes a phone (refused while it runs). (1e89170)
- Phones give back their room when idle: bb tidy removes the quick-boot snapshot of a project's phone not started for a week and names one that is not its default after two, the node's room keeper does the same for every project when the homes' disk is past 90%, and bb emu list and the Storage page say when each phone last started and what its snapshot holds. (c25685f)
- A node's agent says when it was built, beside its version: on the node's row, in bb status on that node and in a diagnostics report, so a problem with an agent can be dated (4647e68)
- Two-factor sign-in: an authenticator app, passkeys and recovery codes on Profile, asked after the password on every way in (the page, a companion app's sign-in, Basic auth refused); a browser can be remembered for 30 days; wrong codes are slowed and held; an administrator can require it per role on the Roles page; the bell recommends it until it is on; and bb users reset-2fa NAME on the controller is the way back for a lost factor (1ef3fb4)
- The Android app starts, opens, restarts and ends a ChatGPT or Copilot session as well as Claude's from a project's Agent view, the Manage agent chooser in a phone's shape, says how you are signed in to each agent on the project's node, archives and locks a project from its menu, and lists the coding agents under Tools (11b042d)
- The Windows companion's project list says each project's lock, whose it is when it holds you out, and puts an archived project you do not keep at its foot (a59c9ad)
- BuilderBot for VS Code opens a ChatGPT or Copilot session as well as Claude's: Open Agent Session asks the project, then the agent, and starts the session when it is not running; its project list says a lock and an archive (b7b6ea6)

### Changed

- Being on a project is enough for BuilderBot for VS Code and the Windows companion to open it, as far as your roles' File access goes: no grant of your own on the project's list is needed any more, and the companion lists every project you are on, each synced to a folder or not. A project's switch for them is on by default and closes them when turned off. (2c0e9f6)
- Android signing keys are now a project's own Signing view under Ship, out of its settings, and a key's downloaded backup can be imported there into the same project or another, its password and alias read from the backup (96c07c1)
- Every notebook view now opens the way the Containers page does: one row with its search, its toggles and its actions (the Add last, as the main button), its numbers as tiles under it (the Roadmap's to send, shelved and finished, Bugs' open by severity, Git's changes and branches, Tests' passing and failing), a status line under those that holds the Roadmap's Save and Revert while something is staged, and every row of filter chips in one band (a2887c7)
- A project's notebook has Sessions beside Overview: your own conversations there, any one to resume, read, download, make visible to every session on the project, or delete; they are no longer listed on your Profile (e7190d6)
- A project's notebook has Permissions beside Overview: everything a session may do on its own, asks first, or may not, with what it may push, in one place out of Settings and the Git view (e7190d6)
- Controller settings is a rail group of its own, Controller, after Containers; old links to it still land there (e7190d6)
- Signing keys are checked, generated, wrapped for a backup and rotated, and a release's APK is signed, on the project's node with its own jdk and Android SDK Build-Tools, never on the controller: install both on that node's Toolchains, and the Signing view and the bell say which node it is and what it lacks when it cannot (5d47be7)
- A project's Start Claude is Start agent, opening a chooser of one node at a time (picked by name) with a line per coding agent there; Open names the agent whose session is running (c95d14e)
- Archive puts a project out of sight and nothing else: its card folds under Archived and leaves Home, and it keeps working for everybody on it. Its owner or an administrator archives it (24c9a24)
- Pointing a node's store at a new folder asks first: a folder that already holds files gets one named for the node inside it, and bringing the old data across is a question of its own; a mount point on a folder with files asks too, and no store or mount may be a system folder (9970f34)
- Every question the dashboard asks is its own dialog with buttons that say what they do (Delete, Revert, Yes and No, Cancel), not the browser's OK and Cancel; Escape or a press outside is Cancel (c1da3b1)
- Every page and notebook view with more than one section has the row of section names at its top to jump to one; the Containers page's names its project groups too (c1da3b1)
- Creating a project no longer pins it on everyone's Home; it is on the Projects page, and each person pins what they want there. (3357c1f)
- A project's agent button reads Manage agent while your session runs, since it opens the chooser with Open, Restart and End. (0412bda)
- The Jobs page's When says the time a running or waiting job began, where it said "started just now" cut short. (24e747c)
- A terminal scrolled back hands your next key to the program: the key row's keys leave the scroll first, and a typed letter ends it, where an arrow used to move tmux's cursor over the history and a letter did nothing. (78ba3e1)
- Test runs are faster and say what held them up: the suites take turns from one queue, longest first, each started only while the machine has room and at the lowest priority, so the emulator and a docker build come first; the unit tier runs across the cores; and a run ends with what bounded it. (1e89170)

### Upgrading

- Claude Code is installed, updated and removed on a node's Agents page, beside Codex CLI and Copilot CLI, and no longer on the Toolchains page, which keeps build toolchains alone and one line pointing there. A script that posted names ["claude-code"] to /api/toolchains now posts {action, node, agent: "claude"} to /api/agents, which also answers check; /api/toolchains refuses a coding agent's name with the way there. A coding agent's update is its own bell row, opening the Agents page. (3cdd23b)
- Every project's switch for VS Code and the Windows companion (Settings, Files) is turned on by the upgrade, so everyone on a project with File access in their roles can open it from their own machine; turn it off on a project that should not be. (2c0e9f6)
- Set SIGNING_SECRET (16 characters or more) in an *.env file in the secrets folder to seal the signing keys, and keep a copy of it with your other secrets: without it the keys stay as they were; lost, each key comes back by Import a backup (e7190d6)
- Projects archived before this upgrade stay archived and are no longer locked: their sessions start and their notebooks take changes again. Lock one again from its menu if it should stay shut (24c9a24)

### Deprecated

- The Lock grant on a role no longer decides anything (a project's owner locks it, an administrator too) and goes in 0.8.0 (24c9a24)

### Removed

- Show the tours again is no longer on Profile: it is in About, under the version in the header (51f1a7a)

### Fixed

- A toolchain left half-installed reads as not installed, and Install clears what it left and installs it whole. (933a5aa)
- A button stays Asking no longer once its press is answered. (5ae753d)
- A Claude session no longer opens on two yellow warnings that a deny rule never matches (b510480)
- An address typed into the browser opens its page, where a draw landing first could take you back to the page you were leaving (b510480)
- A roadmap's Finished section lists what was finished on a project you may read and not change, where it showed an empty list (b510480)
- New VM says why it refused where you can read it, where the reason sat behind the dialog's footer and Make it seemed to do nothing (b510480)
- bb vm ssh lets a session into a VM it made, where it was refused for want of the key bb vm new had made (b510480)
- A request that never reached the controller is said as the controller not answering, not as the browser's error, and a controller restart no longer leaves a Phone page failure in Notifications (b510480)
- The top bar's search keeps at least 80px on the narrowest phones (b510480)
- The Git view says why Pull is off when the branch has no upstream (b510480)

### Security

- A signing key's backup downloaded from a project with a backup password is now wrapped under that password: the zip holds no password, and the key opens only with it. A backup downloaded before this holds its key's password in password.txt in plain text: keep those copies somewhere only you can reach, or delete them and download again. (44b453c)
- With SIGNING_SECRET in the secrets folder, every Android signing key and its passwords are sealed at rest, so a copy of /config opens no key; keys kept from before are sealed at the next start (e7190d6)

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
