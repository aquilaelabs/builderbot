# Layout

```
README.md                        the front page: what it is, the configuration reference, the bb command reference
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
unraid/builderbot.xml            Unraid Docker template (one-click updates)
scripts/
  entrypoint.sh                  secrets shield, uid remap, hooks, ssh-agent
  supervisor.sh                  keeps the box alive; the graceful shutdown
  mint-runner-token              root-only token helper (the one sudo command)
  healthcheck.sh                 docker healthcheck
  bb                             in-container helper CLI
  as-builder                     privilege-dropping wrapper for docker exec
  lib/common.sh                  shared shell helpers
  lib/relay-verbs                the bb verbs a node relays to the controller (bb and bbrelay.py both read it)
  lib/sdk.sh                     the toolchain manager: `bb toolchains`, sourced by bb
  lib/preflight.sh               `bb tests preflight`, sourced by bb
  lib/bbapi.py                   the controller's API from bb: one client, the loopback or BB_CONTROLLER, pinned https
  lib/codemap.py                 the code map bb map answers from: an index over the tree, rebuilt when a source is newer (R75)
  lib/trace-verbs.py             bb dashboard trace: what the server was asked over a window, by endpoint and asker
  lib/sdkmeta.py                 reads config/toolchains.json for bb: fields, argv, versions
  lib/docker-probe.py            which daemon is live, for `bb doctor` and the boot log
  lib/log-split.sh               splits a long-running process's output: all of it to its own file, warnings to the boot log
  lib/embedded.py                pulls scripts and python out of quoted heredocs so `bb lint` sees them
  lib/waits.py                   the wait for a person's Allow and the job-log stream, shared by the verbs below
  lib/devapp-verbs.py            `bb devapp`: status, rebuild, test, new, env, remove, ls, log, start, stop, restart
  lib/capture.py                 `bb capture`: the sources anything that draws gives (a page, the emulator, an X display) and a shot at rest
  lib/reel.py                    `bb capture reel`: the frames of a recording that changed, stamped and tiled
  lib/touch.py                   `bb emu touch` and a drive script's $BB_TOUCH: a tap, hold or glide with its timing kept, through sendevent
  lib/sound.py                   `bb tool sound`: sound effects from sfxr's presets and plain tones, into dist/sound/ as OGG with a waveform and a spectrogram (ffmpeg)
  lib/cilog-hosted.py            `bb ci-log` for a project on GitHub's own runners: the runs and a run's failed jobs, from the controller
  lib/docs.py                    `bb tool docs`: a document as Markdown (markitdown) or its pages as pictures (PyMuPDF), run with the documents toolchain's Python
  lib/poppler.py                 the pdftoppm and pdfinfo Claude Code's PDF reader asks for, drawn with PyMuPDF; the documents toolchain installs them
  lib/gpu.py                     `bb gpu`: the node's NVIDIA card from where a session stands, and a turn on it for a heavy job
  lib/container-verbs.py         `bb container`: status and new
  lib/phone-verbs.py             `bb phone`: status and run
  lib/root-verbs.py              `bb root`: status and run
  lib/report.py                  `bb report`, and file/close from BuilderBot's side
  lib/diag.py                    `bb diag`
  lib/node-log.py                `bb logs --node`
  lib/login-check.py             `bb login --check`: who this account is signed in to Claude as on this machine, told to the controller
  lib/emu-job.py                 `bb emu` as a job on the project's node
  lib/run-job.py                 `bb run`: the snapshot, the job, the log back
  lib/build-or-test.py           the command, place and outputs `bb build` and `bb test` read from the settings
  lib/git-policy.py              `bb git policy`
  lib/relay.py                   a notebook verb relayed from a node to the controller
  lib/controller-stamp.py        the controller's build, for `bb status` and `bb catchup`
  lib/dash.py                    the dashboard's modules loaded by path for the notebook verbs, and the account name and "who wrote it" they share
  lib/roadmap-verbs.py           `bb roadmap`
  lib/bug-verbs.py               `bb bug`
  lib/brief-verbs.py             `bb brief`: a new project's brief, and bb-tty's take of it for a first session
  lib/design-verbs.py            `bb design`: a project's design language and pages, as the notebook's Design view keeps them
  lib/wiki-verbs.py              `bb wiki`: a project's wiki pages, listed, shown, saved and removed under Claude may: Write the wiki
  lib/transcripts-verbs.py       `bb transcripts`: the account's own conversations with Claude on a project, listed and printed
  lib/nb-history.py              `bb history`: the notebook's logs merged
  lib/rules-verbs.py             `bb rules`, except check
  lib/rules-check.py             `bb rules check`: a rule's check command, run in this tree
  lib/tests-verbs.py             `bb tests`: the registry verbs
  lib/tests-verdict.py           what went wrong, from a run's log (bb tests last, the end of a run)
  lib/preamble-verbs.py          `bb preamble`
  lib/findings-verbs.py          `bb findings history` and `bb findings sample`
  lib/settings-verbs.py          `bb settings`: show, and set for build, test and outputs
  lib/sign-verbs.py              `bb sign`: a build signed on the node with one of the project's keys, and its keys and mapping
  lib/busy-verbs.py              `bb node busy` and `bb node wait-quiet`: how busy this node is before a measurement
  lib/users-verbs.py             `bb users`: list, passwd, add, token
  lib/nodes-verbs.py             `bb nodes` and `bb ci-labels`
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
    tab-*.js                     one per document tab (Docker, Nodes, Jobs, Toolchains, Emulator, Phone, Settings, Users, Profile, Findings, Projects)
    nb-*.js                      one per notebook view; nb-core.js is the notebook itself
    page-*.js                    one per part of the page that is neither: the state, the tabs and the strip, the panes, the sidebar, the polls, the bell and the rest
    static/                      the favicon set and the SVG marks the page draws
    bb-tty                       what ttyd runs: which tmux session a terminal is, and whose
    bb-check-relay               the relay's own check, run by bb tests preflight
    bb-gate                      the hook every tool call asks before it runs, on a node
    bb-prompt-relay              a node session's prompts and answers, back to the controller
    bb-work-note                 what a session is changing, for the overlap warning
    bb-keep-login                a hook that does nothing, for sessions an earlier build of this window started with it
    users.py                     who may sign in, and what they are allowed to see (docs/users.md)
    prefs.py                     which model and effort a project's Claude session runs on
    settings.py                  controller settings, the things that used to be environment variables
    statefile.py                 writing a state file, and holding it while you read-modify-write one
    toolchains.py                everything behind the Toolchains tab: catalog, sizes, the job worker
    emulator.py                  everything behind the Emulator tab: a node's Android system images
    memory.py                    everything behind the memory book: what Claude remembers per project
    rules.py                     house rules: what has been decided about working on a project
    preamble.py                  what every session on a project starts with, assembled once
    brief.py                     a new project's brief: kept out of CLAUDE.md, handed to its first session through a dialog
    design.py                    the notebook's Design view: a project's design language and pages, the prompts a session is pointed at, and docs/design-language.md written from them
    cilogs.py                    a project's CI on GitHub's own runners: its runs and the end of a failed job's log, read with the controller's token for `bb ci-log`
    ciwatch.py                   a project's CI watched once a day and at link: a moving runner label, an action a major behind, a red main branch and GitHub's notices on it, for the Git view, bb catchup and the bell
    wiki.py                      the notebook's Wiki view: a project's wiki kept as a forge-shaped git repository of its own, exported as a zip and pushed to or pulled from the repository's wiki
    names.py                     what things are called: a project, a tmux session, a project's Claude session
    projects.py                  new project / link and unlink a remote, the worker that clones and pushes, the locks and the sidebar's pins
    forges.py                    which git host a remote is on, and the two things a host can be asked that git cannot
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
    signing.py                   a project's Android signing keys, kept by the controller, never a session's (R106)
    membership.py                a project's owner, whether it is invite only, and the invitations to it
    busy.py                      whether a node is quiet enough to time anything on, and why not (R108)
    devapp.py                    a project's dev instance: built here, run here, driven from Artifacts
    devactions.py                the layer that runs and reports an instance: up, down, rebuild, test, remove, state and act, the compose plan and job runners, on the base devapp.py keeps
    containers.py                containers BuilderBot did not build: the daemon's list and controls, ones written from a compose file, and whose each is; the Docker manager's view and verbs
    phone.py                     a paired handset on a node: install, push, and the asking
    phonelease.py                a phone lent to a project (R113): the lease, and what its sessions may do on the phone without asking
    db.py                        the controller's store: the SQLite connection, the migrations, ids and the audit trail
    nodes.py                     the node registry, the job queue and the agent's channel (docs/nodes.md); the Nodes tab's verbs; a build job from the controller
    channel.py                   the node agent's verbs behind /api/v1/agent/: enroll, hello, work, a job's files, log and result
    claudecode.py                Claude Code on each node: which version, checking for and installing an update
    claudegrant.py               which nodes each account is signed in to Claude on, as each node reported it
    mapping.py                   a new project's code map built in the background as it is created
    plugins.py                   the Claude Code plugins a project carries, listed and installed
    turns.py                     how many prompts a node lets run at once, and the queue when more ask
    workspace.py                 snapshots, the node bundle, and the artifact store
    jobs.py                      the controller's own job runner (exec here or over ssh) plus /healthz and /metrics
    vmtemplate.py                what a new sandbox VM is made from, with this one's identity in it
    idle.py                      ending Claude sessions nobody has used for a while
    projsessions.py              every account's sessions on a project, and an administrator ending one
    reports.py                   problems with BuilderBot reported by any project's session (bb report)
    diag.py                      the Diagnostics section of Controller settings: reports, images, errors, the audit trail, and the download
    doctor.py                    `bb doctor` run on a timer and cached, for the Doctor card
    runners.py                   a node's CI runners: the root-only token helper, and the Runner card's list
    findings.py                  the scanner's reports read and attributed, and what they used to say
    gitrelay.py                  a node session's push, fetch and pull, done in a repository of the controller's own
    bbrelay.py                   a bb verb from a node's session, run here: which verbs travel, and what a session may push
    hooks.py                     what a node session's hooks post: overlap notes, the chat feed, the catch-up, the turn queue
    macros.py                    what the page may type into a terminal: the command and key tables, the pins, custom lists
    profiletab.py                an account's own settings, the Profile tab
    transcripts.py               an account's conversations with Claude as a text to download, from the Profile tab
    fields.py                    one field out of a request body, read one way by the server and the modules it calls
    share.py                     a part's share of what a session is sent: the rules, the roadmap and the bugs say less per row before they leave one out
    layout.py                    what the page keeps here: each account's tab strip and panes, and the sidebar's cards
    migrations/                  numbered schema files for /config/builderbot.db, applied at boot
    testreg.py                   the test registry: what each test protects, and
                                 what a run measured it costing
    notify.py                    getting a line into a running Claude session, and knowing it landed
    signin.py                    the Claude sign-in and sign-out on one node, as jobs there
    test/                        its Playwright suite: `bb dashboard test`, isolated
    unit/                        its python unit tier: `bb tests unit`, the modules' rules without a server or a browser, run first by preflight
  agent/builderbot-agent.py      the node agent: one stdlib file, served to nodes by the dashboard
  agent/ruff.toml                the linter's settings for it, pinned to the python a Rocky node carries
android/                         the companion app: api-surface.json is its contract with the dashboard, app/ the Kotlin
nodes/bb-session                    the root helper that runs a session in a view of its own project; the agent installs it
nodes/provision-macos.sh            enrolls a Mac as a guest node: one directory, one launchd agent, no root; --remove takes it away
nodes/provision-linux.sh                  turns a Linux machine into a node (the Docker sandbox, the stores, the session half) and enrolls it; Debian, RHEL, Arch and SUSE families, Alpine, Void, Gentoo
nodes/unraid-vm.xml             the node as an Unraid VM: one file for every distribution; only the installer ISO line changes
nodes/vm/                        the same machine for the other six hypervisors: Proxmox, libvirt, QEMU, VMware, Hyper-V, VirtualBox
nodes/cloud-init/                the seed a cloud image boots from: meta-data and the user-data that runs the provisioner
config/skel/                     home directory skeleton
config/icon.png                  the icon the Unraid template shows
config/toolchains.json           the toolchains the Toolchains tab offers, and how to install each
config/templates/                briefing.md, assembled per session by preamble.py; nothing is copied into a project
tools/readme-shots.sh            regenerates the pictures above from a staged dashboard
tools/readme-shots-live.mjs      the same three pictures from a running dashboard: default scheme, addresses scrubbed, nothing saved
tools/readme-bb-ref.sh           writes the README's bb reference from bb help; bb lint holds the two equal
tools/api-doc.py                 writes docs/api.md from server.py's route tables; bb lint holds the two equal
tools/check-sysdeps.py           checks every recipe's system packages against each distribution's package index
tools/agent-version.sh           the lint check that the agent's version moved with its file
tools/no-em-dash.sh              the house rule voice's check: no em dash on a line this branch adds
tools/american-spelling.sh       the house rule spelling's check: no British spelling on a line this branch adds
tools/no-net-growth.sh           the everything-files against their ceilings in tools/ratchet.txt (R77)
tools/ratchet.txt                those ceilings, one per file
pyrightconfig.json               how pyright (the pyright-lsp plugin, or the CLI) reads this repo: each directory's imports and Python
                                 version, with the None checks off, since a module's configure() fills what it declares as None
tools/version-stamp              this repo's own stamp hook: a bump moves the compatibility
                                 window in the agent and the template with it, or refuses
docs/unraid.md                   step-by-step Unraid walkthrough
docs/install.md                  setup, start to finish: the checklist with the decisions each step needs
docs/architecture.md             the map: the seven parts, how they reach each other, where each is explained
docs/api.md                      every /api/ route with its method, handler, first sentence and what it refuses on, written by tools/api-doc.py
docs/how-it-works.md             the controller, the nodes, the sessions, the dashboard, the notebook: how each works
docs/decisions.md                the design decisions, with their dates and reasons
docs/layout.md                   this list, held to the tree by bb lint
docs/changelog-0.5.md            the releases before 0.6, moved out of CHANGELOG.md so the file the dashboard reads stays the current series
docs/screenshots/                the README's pictures, regenerated by tools/readme-shots.sh or tools/readme-shots-live.mjs
docs/start-here.md               the one page for somebody given an account on somebody else's BuilderBot
docs/journeys.md                 what a person does with BuilderBot, walked for real, dated
docs/sandbox-vm.md               the Docker sandbox VM: why, how, and pointing this at it
docs/nodes.md                    design: controller + nodes, homelab-default and enterprise-scalable
docs/users.md                    accounts, roles, and what each one may reach
docs/design-language.md          what the dashboard's surfaces owe each other: held by the
                                 house rule `design` and measured by test/uniform.mjs
.hadolint.yaml                   Dockerfile lint config, shared by CI and bb lint
.github/actionlint.yaml          this runner's labels, for workflow linting
.github/workflows/
  build-image.yml                GHCR publish: hosted, cached from :latest, on a push to main that touches the image's inputs
  lint.yml                       the linters, on a pull request, on this runner
  dashboard.yml                  the dashboard's browser suite, on a pull request that changes it, on this runner
  android-app.yml                the companion app's build
  runner-smoke-test.yml          proves this runner picks up jobs, carries its toolchain and cannot see the shielded PAT (manual)
```
