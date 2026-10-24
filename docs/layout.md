# Layout

```
README.md                        the front page: what it is, its features, screenshots, and the way into docs/
CLAUDE.md                        working inside this repository: what a session here is told
CONTRIBUTING.md                  a person's way in: a checkout, seeing a change, proving it, the house rules, landing it
CHANGELOG.md                     the user-facing record, by release and category; bb changelog writes it
VERSION                          this repository's own version, moved per commit by tools/version-stamp
LICENSE                          the Apache License 2.0
NOTICE                           the copyright line the license's notice section asks a redistribution to keep
.gitignore                       what the tree leaves out of git; .dockerignore what the image build leaves out of its context
.dockerignore                    (see .gitignore)
ruff.toml                        the python linter's settings for the controller; scripts/agent/ruff.toml pins the agent's to a Rocky node's python
Dockerfile                       image definition
docker-compose.yml               compose variant of the stack
.env.example                     annotated compose configuration
lab/compose.yml                  the lab's Gitea and Forgejo for bb tests lab, a stack of its own beside the dev instance
lab/.env.example                 the lab's one setting: the address other machines reach it at
unraid/builderbot.xml            Unraid Docker template (one-click updates)
scripts/
  entrypoint.sh                  the container's boot: uid remap, the timezone, then lib/boot.sh's steps and gosu
  host-boot.sh                   a bare-metal install's boot under systemd: lib/boot.sh's steps, then setpriv to its account (R90)
  supervisor.sh                  keeps the box alive; the graceful shutdown
  mint-runner-token              root-only token helper (one of the two sudo commands)
  deploy-key                     root-only deploy key helper: make, keep, forget, load (the other)
  healthcheck.sh                 docker healthcheck
  bb                             in-container helper CLI
  as-builder                     privilege-dropping wrapper for docker exec
  lib/common.sh                  shared shell helpers
  lib/host-env.sh                the image's ENV, the release's stamp and the env file, for a bare-metal install's service and its bb (R90)
  lib/boot.sh                    the boot's steps both installs take: secrets shield, ssh-agent, home seed, hooks, state gate (R90)
  lib/controller-packages.sh     the controller's package list read one way, for the Dockerfile and a bare-metal install (R90)
  lib/relay-verbs                the bb verbs a node relays to the controller (bb and bbrelay.py both read it)
  lib/sdk.sh                     the toolchain manager: `bb toolchains`, sourced by bb
  lib/preflight.sh               `bb tests preflight`, sourced by bb
  lib/bbapi.py                   the controller's API from bb: one client, the loopback or BB_CONTROLLER, pinned https
  lib/cmdmatch.py                which commands a shell line runs, read as a shell splits it, for a rule that refuses (R200)
  lib/rulehook.py                what a session's hooks keep about the house rules: what fired, the guard list, a refusal's words (R200)
  lib/syncwait.py                a session's bb on a synced node waits for its copy to be in step with the controller's (R163)
  lib/codemap.py                 the code map bb map answers from: an index over the tree, rebuilt when a source is newer (R75)
  lib/trace-verbs.py             bb dashboard trace: what the server was asked over a window, by endpoint and asker
  lib/sdkmeta.py                 reads config/toolchains.json for bb, with the tool packs beside it: fields, argv, versions
  lib/toolpack-run.py            `bb tool PACK VERB`: a tool pack's verb from its manifest, the caller's words in place of {args}
  lib/docker-probe.py            which daemon is live, for `bb doctor` and the boot log
  lib/log-split.sh               splits a long-running process's output: all of it to its own file, warnings to the boot log
  lib/embedded.py                pulls scripts and python out of quoted heredocs so `bb lint` sees them
  lib/waits.py                   the wait for a person's Allow and the job-log stream, shared by the verbs below
  lib/devapp-verbs.py            `bb devapp`: status, rebuild, test, new, env, remove, ls, log, start, stop, restart
  lib/capture.py                 `bb capture`: the sources anything that draws gives (a page, the emulator, an X display) and a shot at rest
  lib/reel.py                    `bb capture reel`: the frames of a recording that changed, stamped and tiled
  lib/touch.py                   `bb emu touch` and a drive script's $BB_TOUCH: a tap, hold or glide with its timing kept, through sendevent
  lib/hand.py                    a finger's path through points for a glide (curved, eased, overshooting, wobbling, by seed), played by `bb emu touch` and `bb phone touch`
  lib/sound.py                   `bb tool sound`: sound effects from sfxr's presets and plain tones, into dist/sound/ as OGG with a waveform and a spectrogram (ffmpeg)
  lib/cilog-hosted.py            `bb ci-log` for a project on GitHub's own runners: the runs and a run's failed jobs, from the controller
  lib/docs.py                    `bb tool docs`: a document as Markdown (markitdown) or its pages as pictures (PyMuPDF), run with the documents toolchain's Python
  lib/poppler.py                 the pdftoppm and pdfinfo Claude Code's PDF reader asks for, drawn with PyMuPDF; the documents toolchain installs them
  lib/bbftp.py                   bb-ftpd: one project's tree over FTPS, each login asked of the controller through the agent; the ftp toolchain installs it (R151)
  lib/gradle-local-build.gradle  the Gradle init script bb-tty puts in a project's Gradle home: its build folders on the node's disk, linked from app/build (B439)
  lib/tmux.conf                  BuilderBot's tmux settings: the controller copies them to ~/.tmux.builderbot.conf, bb-tty applies them to a node's tmux server
  lib/gpu.py                     `bb gpu`: the node's NVIDIA card from where a session stands, and a turn on it for a heavy job
  lib/tidy.py                    `bb tidy`: what a task left holding (its emulator, the card, build daemons, browsers, /tmp) given back
  lib/unitpar.py                 `bb tests unit` across the cores: the modules dealt by their last measured seconds, one unittest process per core (R130)
  lib/bottleneck.py              what bounded a run of the dashboard suites, from its own numbers: the floor, the machine, the reruns (R130)
  lib/browser.mjs                `bb browser`: Chrome or Firefox with an unpacked extension loaded, on its own port and profile, driven and stopped by one verb
  lib/proc-verbs.py              `bb proc`: this account's processes by a word of their command line, listed, ended or waited for, never the call's own shell
  lib/container-verbs.py         `bb container`: status and new
  lib/vm-verbs.py                `bb vm`: a project's VMs listed, made, started, stopped, snapshotted and removed (R91)
  lib/phone-verbs.py             `bb phone`: status and run
  lib/root-verbs.py              `bb root`: status and run
  lib/report.py                  `bb report`, and file/close from BuilderBot's side
  lib/pc.py                      `bb pc`: a person's Windows PC lent to the project, its verbs asked and their results read
  lib/diag.py                    `bb diag`
  lib/node-log.py                `bb logs --node`
  lib/login-check.py             `bb login --check`: who this account is signed in to each agent as on this machine, told to the controller
  lib/emu-job.py                 `bb emu` as a job on the project's node
  lib/run-job.py                 `bb run`: the snapshot, the job, the log back
  lib/build-or-test.py           the command, place and outputs `bb build` and `bb test` read from the settings
  lib/git-policy.py              `bb git policy`
  lib/relay.py                   a notebook verb relayed from a node to the controller
  lib/release-edit.py            `bb version release --edit`: the notes and files read where it is typed, the edit asked over the API
  lib/controller-stamp.py        the controller's build, for `bb status` and `bb catchup`
  lib/dash.py                    the dashboard's modules loaded by path for the notebook verbs, and the account name and "who wrote it" they share
  lib/roadmap-verbs.py           `bb roadmap`
  lib/bug-verbs.py               `bb bug`
  lib/brief-verbs.py             `bb brief`: a new project's brief, and bb-tty's take of it for a first session
  lib/design-verbs.py            `bb design`: a project's design language and pages, as the notebook's Design view keeps them
  lib/wiki-verbs.py              `bb wiki`: a project's wiki pages, listed, shown, saved and removed under Agents may: Write the wiki
  lib/transcripts-verbs.py       `bb transcripts`: the account's own conversations with each agent on a project, listed and printed
  lib/nb-history.py              `bb history`: the notebook's logs merged
  lib/rules-verbs.py             `bb rules`, except check
  lib/rules-check.py             `bb rules check`: a rule's check command, run in this tree
  lib/tests-verbs.py             `bb tests`: the registry verbs
  lib/tests-verdict.py           what went wrong, from a run's log (bb tests last, the end of a run)
  lib/preamble-verbs.py          `bb preamble`
  lib/findings-verbs.py          `bb findings history` and `bb findings sample`
  lib/settings-verbs.py          `bb settings`: show, set for build, test and outputs, and node from a controller shell
  lib/projects-adopt.py          `bb projects adopt`: a folder already under the share made a project
  lib/sign-verbs.py              `bb sign`: a build signed on the node with one of the project's keys, and its keys and mapping
  lib/busy-verbs.py              `bb node busy` and `bb node wait-quiet`: how busy this node is before a measurement
  lib/users-verbs.py             `bb users`: list, claim, passwd, add, token
  lib/nodes-verbs.py             `bb nodes` (and enroll-token) and `bb ci-labels`
  lib/jobs-verbs.py              `bb jobs`
  lib/work-verbs.py              `bb work`
  lib/version-verbs.py           `bb version`
  lib/changelog-verbs.py         `bb changelog`
  lib/token-verbs.py             `bb token keep`
  lib/login-list.py              `bb login --list`: every account this machine is signed in as
  lib/doctor-probes.py           egl, project node, commit identity, session-capable node, signed-in account
  lib/lint-checks.py             bb lint's own checks: runner label pinning, XML well-formedness, settings agreement
  startup.d/*.sh                 startup hooks
  dashboard/                     web dashboard: server.py (the routes, the transport and the gates, each handler one call
                                 into a module beside it); index.html (markup, stylesheet, the wiring that runs at load);
                                 one tab-*.js per document tab, one nb-*.js per notebook view (nb-core.js is the
                                 notebook itself), one page-*.js per part of the page that is neither, all strict,
                                 all pure declarations, served by name from the page's own script tags (R77)
    server.py                    the routes, the transport and the gates; each handler one call into a module beside it
    index.html                   the markup, the stylesheet and the wiring that runs at load
    tab-*.js                     one per document tab (Docker, Nodes, Jobs, nginx, Storage, Toolchains, Agents, Emulator, Phone, Apps, Settings, Users, Profile, Findings, Projects)
    nb-*.js                      one per notebook view; nb-core.js is the notebook itself
    page-*.js                    one per part of the page that is neither: the state, the tabs, the panes and the dock, a project's rows, the polls, the bell, the doctor and the rest
    static/                      the favicon set and the SVG marks the page draws
    bb-tty                       what ttyd runs: which tmux session a terminal is, and whose
    bb-agent-hook                Codex's and Copilot's own hooks holding Claude's guards: their payload in Claude's shape, the same hooks run (R95)
    bb-codex-trust               BuilderBot's own Codex hooks trusted for one launch, by the hashes that Codex reports for them (B284)
    bb-check-relay               the relay's own check, run by bb tests preflight
    bb-gate                      the hook every tool call asks before it runs, on a node
    bb-prompt-relay              a node session's prompts and answers, back to the controller
    bb-work-note                 what a session is changing, for the overlap warning, and the named rules its file raises
    bb-rule-hook                 refuses a shell call a rule refuses, hands a definition grep the map's answer, and says the named rules again after a summary (R200)
    users.py                     who may sign in, and what they are allowed to see (docs/users.md)
    roles.py                     roles and permissions (R137): a grant is a capability on a scope, a role a named set of them, in roles.json; the gate (users.may) reads them
    prefs.py                     which model and effort a project's sessions run on, per agent
    settings.py                  controller settings, the things that used to be environment variables; switches, a text and two secrets never shown back
    storage.py                   the Storage page's answer (R169): the nodes an account holds the area on, each project's folders where it may see the project, the rest as one line
    tunnel.py                    the home tunnel the controller runs itself (R176): cloudflared as its child from the settings, and the hostname's record and rules through Cloudflare's API
    statefile.py                 writing a state file, and holding it while you read-modify-write one
    stateversion.py              /config's state version: the start's refusal of a newer or too old one, the copy before a migration, the JSON stores' migrations run
    statemigrations/             numbered migrations for the JSON stores (NNNN_name.py, run(ctx)), each run once as the state moves, never edited once shipped
    toolchains.py                everything behind the Toolchains page: catalog, sizes, the job worker
    toolpacks.py                 the tool packs a person adds (docs/tool-packs.md): a repository's bbtool.json, pinned to a commit, as catalog rows
    emulator.py                  everything behind the Emulator page: a node's Android system images
    enrollscript.py              Enroll node as one script: the answers, the token and a WireGuard tunnel inside the provisioner
    memory.py                    everything behind the memory book: what Claude remembers per project
    rules.py                     house rules: what has been decided about working on a project
    preamble.py                  what every session on a project starts with, assembled once
    brief.py                     a new project's brief: kept out of CLAUDE.md, handed to its first session through a dialog
    design.py                    the notebook's Design view: a project's design language and pages, the prompts a session is pointed at, and docs/design-language.md written from them
    cilogs.py                    a project's CI on GitHub's own runners: its runs and the end of a failed job's log, read with the controller's token for `bb ci-log`
    BbGlide.java                 a lent phone's glide as one held stroke: built on the node with javac and d8, run with app_process (R126)
    forgerelease.py              Release's forge half: the GitHub, Gitea or GitLab release beside a pushed tag, its notes the changelog's section and its builds attached
    ciwatch.py                   a project's CI watched once a day and at link: a moving runner label, an action a major behind, a red main branch and GitHub's notices on it, for the Git view, bb catchup and the bell
    wiki.py                      the notebook's Wiki view: a project's wiki kept as a forge-shaped git repository of its own, exported as a zip and pushed to or pulled from the repository's wiki
    names.py                     what things are called: a project, a tmux session, a project's agent sessions
    agents.py                    the coding agents a session may run, one adapter each (R95): how each installs, signs in, is launched, briefed, guarded and read; page-agents.js is the page's copy
    projects.py                  new project / link and unlink a remote, the worker that clones and pushes, the locks and the pins Home shows
    forges.py                    which git host a remote is on, and the two things a host can be asked that git cannot
    systems.py                   the systems a node can be: what Enroll node's pulldown offers, each with its provisioner family and its vetting (R204)
    ftp.py                       a project's file access over FTP and in an editor: the switches, the port, each account's access, and access_for, the one answer both doors give (R151, R159)
    wssync.py                    a node's projects as a synced copy: the index, state, since, get and put for its agent, and conflicts (R162)
    devices.py                   a person's devices: the token an app signs in for, the Devices list and Disconnect, and the device door an app syncs a project through as a node does (R270, R272)
    pcwork.py                    a person's PC lent to a project (R270): what the companion lends, a session's asks under Use a lent PC, the PC's long poll and its results
    apps.py                      the apps a person installs (R272): fetched from the release matching this controller, checked against their sha256, kept under /config/apps and served at /apps; the seed file read once
    snapshots.py                 each project's tree as it was each day, stored once by content, pruned to the project's days, and restored whole or a file at a time (R165)
    paths.py                     where the controller keeps what grows (snapshots, the git relay, logs), as the Settings page's Storage section sets it, and the move between two
    claudesync.py                a synced node's agents' conversations: the listing, get and put (whole, a tail, gone) for its agent's mirror (B613)
    files.py                     a project's files for a person's editor (R159): stat, list, read, write, rename, delete, search and changes, inside the project and never .git
    git.py                       the notebook's Git view: the repository read out, and its writes
    codebase.py                  the code base counted, by language, for the Briefing tab
    logs.py                      what is kept, for how long, and the downloads behind the gear menu
    roadmap.py                   the roadmap; `bb roadmap` drives the same file
    bugs.py                      the bug tracker; `bb bug` drives the same file
    notebook.py                  one batch over both of those, so half of one cannot exist
    pending.py                   what a session wants to add to the notebook, held for the operator
    ids.py                       one letter per notebook tab, so a number says which list it came from
    presence.py                  who else has a notebook open, in memory only
    overlap.py                   what each session is changing, and where two of them collide
    chat.py                      messages between accounts, and what each project's people are doing
    version.py                   one version identity per project, rendered for whatever is asking
    changelog.py                 the user-facing record beside it: categories, and the editor's writes
    artifacts.py                 what a project built: dist/, and what a row may offer
    signing.py                   a project's Android signing keys, kept by the controller, never a session's, and the sign-key jobs that work on them on the project's node (R106)
    releasesign.py               a release's unsigned APK from CI, signed on the project's node with its sideload key and attached (R106)
    membership.py                a project's owner, whether it is invite only, and the invitations to it
    registry.py                  projects by id (R154): each directory's permanent number and the name it is shown under, in projects.json; a directory is never handed out twice
    busy.py                      whether a node is quiet enough to time anything on, and why not (R108)
    devapp.py                    a project's dev instance: built here, run here, driven from Artifacts
    devactions.py                the layer that runs and reports an instance: up, down, rebuild, test, remove, state and act, the compose plan and job runners, on the base devapp.py keeps
    relocate.py                  copying or moving a dev instance to another node, its volumes and data directory with it: three jobs, packed on the old node, unpacked on the new, then its rebuild
    containers.py                containers BuilderBot did not build: the daemon's list and controls, ones written from a compose file, and whose each is; the Docker manager's view and verbs
    imagecheck.py                every container's registry images against what their registries serve (R195): a weekly check, Check for updates on the Containers page, Update on a row
    vms.py                       the VM manager (R91): each project's VMs on the nodes with VM host, the OS catalog matched by name, the limits, and the vm jobs
    nginxproxy.py                one nginx per node, BuilderBot's own (R171): the routes and certificate kept here, the compose file generated from them, deployed and rebuilt through containers.py
    phone.py                     a paired handset on a node: install, push, and the asking
    phonelease.py                a phone lent to a project (R113): the lease, and what its sessions may do on the phone without asking
    db.py                        the controller's store: the SQLite connection, the migrations, ids and the audit trail
    nodes.py                     the node registry, the job queue and the agent's channel (docs/nodes.md); the Nodes page's verbs; a build job from the controller
    channel.py                   the node agent's verbs behind /api/v1/agent/: enroll, hello, work, a job's files, log and result
    claudecode.py                Claude Code on each node: which version, checking for and installing an update
    agentcode.py                 the other coding agents on each node (Codex CLI, Copilot CLI): which version, the registry's latest, installing, updating and removing each (R95)
    claudegrant.py               which nodes each account is signed in to each agent on, as each node reported it
    mapping.py                   a new project's code map built in the background as it is created
    plugins.py                   the Claude Code plugins a project carries, listed and installed
    turns.py                     how many prompts a node lets run at once, and the queue when more ask
    workspace.py                 snapshots, the node bundle, and the artifact store
    jobs.py                      the controller's own job runner (exec here or over ssh) plus /healthz and /metrics
    vmtemplate.py                what a new sandbox VM is made from, with this one's identity in it
    idle.py                      ending sessions nobody has used for a while
    home.py                      Home's numbers across the install: nodes online, containers running, jobs running, failed today and the last ten
    notices.py                   what the page said to each account, kept per account (<state>/notices/UID.json, the newest 300): the Notifications page's history
    helpdocs.py                  BuilderBot's own docs for the Help page: the docs README lists, one read by name, and a search across them
    projsessions.py              every account's sessions on a project, and an administrator ending one
    reports.py                   problems with BuilderBot reported by any project's session (bb report)
    diag.py                      the Diagnostics section of Controller settings: reports, images, errors, the audit trail, and the download
    featuresoff.py               the features an install switches off from its environment (FEATURES_OFF): the list, the sentence, and what the page and the routes read of it (R81)
    doctor.py                    `bb doctor` run on a timer and cached, for the Doctor card
    runners.py                   a node's CI runners: the root-only token helper, and the Runner card's list
    findings.py                  the scanner's reports read and attributed, and what they used to say
    gitrelay.py                  a node session's push, fetch and pull, done in a repository of the controller's own
    pushscan.py                  what a push would send, read for secrets and private things before it goes, and the lines a person okayed (R219)
    bbrelay.py                   a bb verb from a node's session, run here: which verbs travel, and what a session may push
    hooks.py                     what a node session's hooks post: overlap notes, the chat feed, the catch-up, the turn queue
    macros.py                    what the page may type into a terminal: the command and key tables, the pins, custom lists
    profiletab.py                an account's own settings, the Profile page
    mfa.py                       two-factor sign-in (R127): an authenticator app's codes, passkeys (WebAuthn, its CBOR and P-256 check), recovery codes, remembered browsers and wrong codes held, in two-factor.json
    qr.py                        a QR code as an SVG, for an authenticator app to scan (R127)
    transcripts.py               an account's conversations with each agent as a text to download, from a notebook's Sessions view
    fields.py                    one field out of a request body, read one way by the server and the modules it calls
    timing.py                    where a request's time went: named parts and its own CPU, for bb dashboard trace
    share.py                     a part's share of what a session is sent: the rules, the roadmap and the bugs say less per row before they leave one out
    layout.py                    what the page keeps here: each account's tabs and panes, the dock's terminals among them
    bellseen.py                  what each account has dismissed from its bell: an update to one version, until a newer one is out
    migrations/                  numbered schema files for /config/builderbot.db, applied at boot
    testreg.py                   the test registry: what each test protects, and
                                 what a run measured it costing
    notify.py                    getting a line into a running session, and knowing it landed
    signin.py                    each agent's sign-in and sign-out on one node, as jobs there
    test/                        its Playwright suite: `bb dashboard test`, isolated; device-api.json in it pins what the released companion and VS Code extension read from the controller, each field's type, and deviceapi.mjs drives it (R79)
    unit/                        its python unit tier: `bb tests unit`, the modules' rules without a server or a browser, run first by preflight (agentpkg.py loads the node agent for it)
  agent/builderbot-agent.py      the node agent's entry: runs the package beside it, and is the __main__.py of the zip a node runs
  agent/builderbot_agent/        the node agent, stdlib only, shipped to nodes by the dashboard as one zip
    __init__.py                  what the agent is and how it runs, and AGENT_VERSION
    base.py                      the constants naming the node's paths and tools, the log, own_path and own_digest
    bundle.py                    the zip a node runs, built the same on the controller and the node, so the digests agree
    controller.py                the connection to the controller, verified by pin
    stores.py                    the node's stores, a store's path rules, and node.json
    storage.py                   what the disks hold, by filesystem, store and project: an hourly walk on its own thread, for the Storage page (R169)
    backends.py                  the machine's package manager and network configuration backends
    vms.py                       the VMs a node runs (R91): the vm job's fixed table of virsh and qemu-img commands, cloud-init, the census of them, and their network's firewall
    vmhw.py                      a VM's hardware beyond size (R100): the host's CPUs and devices, pinning, the balloon, the network, a virtiofs folder, passthrough, the vBIOS dump
    screen.py                    a VM's screen for the dock (R99): a websocket relay on 7684 to the VM's VNC on the loopback, signed by the controller
    toolchains.py                the toolchain store (R19): what is installed, who uses it, a session's environment
    gpu.py                       the NVIDIA card: its sample, its memory's holders, the driver and container toolkit
    sessnet.py                   each session kept to its own project's network (R79)
    accounts.py                  each account a Unix user of its own on the node (R125): its user made, its home moved to it and back, the terminal's environment for bb-session tty
    tokenwatch.py                who opens an account's coding-agent token on the node (R125): the files held at 600, a reader that is neither the account nor the agent said on the next hello
    runners.py                   the CI runners: their slots and state, and Agent's runner verbs
    census.py                    the census and the sample every hello carries
    jobs.py                      Job: one piece of the controller's work, on its own thread
    ftp.py                       the file-access servers a project's settings open
    wssync.py                    keeps a node's synced copy of its projects in step with the controller's (R162)
    claudesync.py                keeps a synced node's agents' conversations and memories in step with the controller's (B613)
    sessions.py                  the session half (#24): ttyds, tokens, firewall and upkeep, as Agent's methods
    workspace.py                 a job's source on disk, its artifacts, and the bundle of bb
    work.py                      compose, toolchains, signing, images and system packages, as Agent's methods
    keyops.py                    the controller's signing key work on this node: a keystore checked, a key made or wrapped, a rotation's proof, a release's APK signed (R106)
    configplane.py               the configuration plane: the node's system, storage and network, as root
    agent.py                     Agent: hello, the loop and self-update, made of the parts above
    cli.py                       enroll, run, status, sample
    coverage.py                  function coverage under bb tests coverage only
  agent/ruff.toml                the linter's settings for the agent, pinned to the python a Rocky node carries
android/                         the companion app: api-surface.json is its contract with the dashboard, each field's type pinned, app/ the Kotlin
vscode/                          BuilderBot for VS Code (R159): plain JavaScript, no build step and no dependencies
  package.json                   the extension's manifest: its commands, its settings, and builderbotApi, the Files API it speaks
  extension.js                   the builderbot: file system, the sign-in, open project, search and the session's terminal
  lib/client.js                  the controller as the extension speaks to it: sign-in through /login, the Files API, /term
  lib/ws.js                      a websocket client in Node's own modules, for the terminal
  lib/ttyd.js                    ttyd's protocol over the /term relay: the dashboard's own terminal, from VS Code
  README.md                      what VS Code shows on the extension's page: setting it up, installing and using it
windows/                         the Windows companion app (R270): a person's machine keeping a project's folder in step through the device door
  README.md                      what it does, signing in, picking a project and a folder, building it
  bbcompanion/__init__.py        the package: what the app is
  bbcompanion/__main__.py        its command line (sign in, add, remove, run, sign out) and the packaged app's start
  bbcompanion/core.py            the node agent's own sync on the device door: the projects picked, a long poll per project, what Windows cannot hold left out
  bbcompanion/names.py           Windows' rules for a file's name: device names, a trailing dot or space, the refused characters, two names one by case
  bbcompanion/creds.py           the device token in Windows' credential store, or a file only its owner reads elsewhere
  bbcompanion/settings.py        the projects kept and their folders, the controller's address
  bbcompanion/pc.py              this PC lent to a project: the verbs its person set up, run on a session's ask, the folder written as the project's path
  bbcompanion/update.py          kept current by its controller: what it holds asked at start and daily, a newer copy checked and swapped in at the next start
  bbcompanion/app.py             the window: sign in, the projects and each one's state, Add, Remove, Open folder, Conflicts
nodes/bb-session                    the root helper that runs a session in a view of its own project; the agent installs it
nodes/provision-macos.sh            a provisioner for macOS, not offered by default takes it away
nodes/provision-linux.sh                  turns a Linux machine into a node (the Docker sandbox, the stores, the session half) and enrolls it; Debian, RHEL, Arch and SUSE families, Alpine, Void, Gentoo
nodes/families/                           the provisioner's family files, one per package family (deb, rhel, arch, suse, alpine, void, gentoo): package names and verbs, where docker comes from; the enroll script carries the picked system's beside the core
nodes/install-controller.sh               installs the controller bare metal on the provisioner's core, lays the release out by the Dockerfile's COPY lines, and makes the machine a node of itself; --check, --update, --rollback, --remove (R90)
nodes/unraid-vm.xml             the node as an Unraid VM: one file for every distribution; only the installer ISO line changes
nodes/vm/                        the same machine for the other six hypervisors: Proxmox, libvirt, QEMU, VMware, Hyper-V, VirtualBox
nodes/cloud-init/                the seed a cloud image boots from: meta-data and the user-data that runs the provisioner
config/skel/                     home directory skeleton
config/icon.png                  the icon the Unraid template shows
config/toolchains.json           the toolchains the Toolchains page offers, and how to install each
config/controller.env            a bare-metal install's env file as the installer first writes it: the paths compose mounts, the settings compose passes (R90)
config/controller-packages.tsv   what the controller needs installed, per provisioner family: the image and a bare-metal install read this one list (R90)
config/vm-images.json            the operating systems a VM is made from: each publisher's cloud image and its checksum file (R91)
config/templates/                briefing.md, assembled per session by preamble.py; nothing is copied into a project
tools/readme-shots.mjs           the README's pictures (dashboard, notebook, nodes, toolchains, the phone's dashboard and terminal) from a running dashboard, normally the dev instance: default scheme, addresses scrubbed, nothing saved
tools/bb-ref.sh                  writes the bb block of docs/reference.md from bb help; bb lint holds the two equal
tools/api-doc.py                 writes docs/api.md from server.py's route tables; bb lint holds the two equal
tools/check-sysdeps.py           checks every recipe's system packages, and with --controller the controller's own list, against each distribution's package index
tools/agent-version.sh           the lint check that the agent's version moved with its file
tools/no-em-dash.sh              the house rule voice's check: no em dash on a line this branch adds
test/nettest/compose.yml         the network probe (R178's proof): a container shipped to a node that tries what a project's container may and may not reach
test/nettest/Dockerfile          its image: alpine with curl, dig and nc, running probe.sh
test/nettest/probe.sh            the probe itself: DNS, the internet, the controller, the node's 80 and 443, and not its 22, the private ranges or IPv6; PASS/FAIL per line in the log
test/nettest/.env.example        the two addresses it needs: the controller's and the node's
tools/american-spelling.sh       the house rule spelling's check: no British spelling on a line this branch adds
tools/no-net-growth.sh           the everything-files against their ceilings in tools/ratchet.txt (R77)
tools/upgrade-snapshot.py        a lived-in /config made by this tree's controller through its API, written to scripts/dashboard/test/upgrade/VERSION/ for the upgrade suite; a release runs it
tools/vscode-vsix.py             packages vscode/ as a .vsix with python's zipfile, BuilderBot's version inside (R159)
tools/companion-build.py         builds the Windows companion as one .pyz with the four agent modules its sync is (R270)
tools/app-schemes.py             writes the Android app's twelve color schemes, both halves, from the design record (bb design json | tools/app-schemes.py)
tools/ratchet.txt                those ceilings, one per file
tools/scan.sh                    the static analysis stack, run once with plain docker run: Semgrep, Trivy and mobsfscan, versions pinned, SARIF into the reports folder (docs/scanners.md)
pyrightconfig.json               how pyright (the pyright-lsp plugin, or the CLI) reads this repo: each directory's imports and Python
                                 version, with the None checks off, since a module's configure() fills what it declares as None
tools/version-stamp              this repo's own stamp hook: a bump moves the compatibility
                                 window in the agent and the template with it, or refuses
docs/README.md                   the index of these docs, linked from the README
docs/reference.md                the configuration reference, every bb command (its bb block written by tools/bb-ref.sh) and signing Android releases
docs/unraid.md                   step-by-step Unraid walkthrough
docs/install.md                  setup, start to finish: the checklist with the decisions each step needs
docs/architecture.md             the map: the seven parts, how they reach each other, where each is explained
docs/api.md                      every /api/ route with its method, handler, first sentence and what it refuses on, written by tools/api-doc.py
docs/how-it-works.md             the overview: what the image carries, its security model and hooks, and which doc explains each part
docs/dashboard.md                the dashboard: signing in, the rail, Home, the bell, color schemes, the dock and its terminals
docs/projects.md                 the Projects page: making, linking, archiving and deleting a project, and its repository's access
docs/notebook.md                 a project's page: its header and its views, from the roadmap and bugs to the wiki and design
docs/sessions.md                 each agent's sessions: starting one, the Sessions page, a session's view and network, its briefing and rules
docs/building.md                 builds, tests, CI runners and logs, the scanner's findings, dist/, signing and releases
docs/toolchains.md               the toolchain store, the Toolchains and Emulator pages, the NVIDIA card, Android, the Phone page
docs/agents.md                   the coding agents: the agent table, the Agents page, installing and signing in to each on a node (R95)
docs/tool-packs.md               tool packs: adding one, a project's Toolchains setting, and writing a bbtool.json
docs/containers.md               the Containers page and nginx: dev instances, how one is reached, networks, image updates
docs/scanners.md                 setting up the static analysis stack and running it (tools/scan.sh)
docs/versions.md                 versions and release lines: bb version line, forward, backport, a patch line's rules
docs/vms.md                      the VMs page and bb vm: VM host, the OS catalog, the dial, the limits, the network, snapshots, a VM made a node
docs/machines.md                 Controller settings, Nodes, Storage, the logs, the Jobs page, a Mac as a node
docs/people.md                   the first account, Users and Roles, owners and invitations, the chat, your Profile
docs/bb-command.md               the bb verbs with more behind them: the test harness, the code map, capture, sound and documents
docs/privacy.md                  data and privacy: what an install keeps, what it contacts, how to remove it
docs/features.md                 everything BuilderBot does, by area, linked from each release's notes
docs/companion-app.md            the companion app for an Android phone: pairing, its lock, notifications, how it is built
docs/decisions.md                the design decisions, with their dates and reasons
docs/layout.md                   this list, held to the tree by bb lint
docs/screenshots/                the README's pictures, regenerated by tools/readme-shots.mjs
docs/start-here.md               the one page for somebody given an account on somebody else's BuilderBot
docs/journeys.md                 what a person does with BuilderBot, walked for real, dated
docs/sandbox-vm.md               the Docker sandbox VM: why, how, and pointing this at it
docs/nodes.md                    design: controller + nodes, homelab-default and enterprise-scalable
docs/users.md                    design: accounts, roles, and what each one may reach
docs/design-language.md          what the dashboard's surfaces owe each other: held by the
                                 house rule `design` and measured by test/uniform.mjs
.hadolint.yaml                   Dockerfile lint config, shared by CI and bb lint
.github/actionlint.yaml          this runner's labels, for workflow linting
.github/workflows/
  build-image.yml                GHCR publish: hosted, cached from :latest, on a push to main that touches the image's inputs
  lint.yml                       the linters, on a pull request, on this runner
  dashboard.yml                  the dashboard's browser suite, on a pull request that changes it, on this runner
  android-app.yml                the companion app's build
  companion-app.yml              the Windows companion's .exe: PyInstaller on a hosted Windows runner, on a published release or by hand, attached to the release
  runner-smoke-test.yml          proves this runner picks up jobs, carries its toolchain and cannot see the shielded PAT (manual)
```
