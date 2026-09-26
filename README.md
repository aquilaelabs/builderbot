# BuilderBot

One container that is the **controller for your build nodes**: the machines
where Claude sessions, builds, tests, CI and the Android emulator run: built
to live on an Unraid server with your projects mounted straight in.

```
  ┌─────────────────────── BuilderBot ────────────────────────┐
  │  the dashboard · the notebook · the record                │
  │  node 22 · python 3 + uv · gh · docker · playwright       │
  │                                                           │
  │  nodes ──► sessions, builds, tests, CI and the emulator:  │
  │            claude · jdk · android sdk · … from a store    │
  │                                                           │
  │  /workspace  ◄─────────  /mnt/user/projects               │
  │    every folder in there is a project                     │
  └───────────────────────────────────────────────────────────┘
```

**Given an account on somebody else's BuilderBot rather than setting one up?**
[docs/start-here.md](docs/start-here.md) is the one page for that: the first
five minutes, what is shared, and what the refusals mean. Everything below is
for whoever runs the box.

The container starts, runs its install/setup hooks, and stays up. It carries
**no Claude Code**: a session runs on the node its project is bound to, opened
from the dashboard, and the controller keeps the dashboard, the notebook and
the record. New images publish automatically to GHCR whenever a push to
`main` changes what the image is built from (plus a weekly refresh), so
updating is Unraid's one-click **update ready** flow.

## What it looks like

The [dashboard](docs/how-it-works.md#web-dashboard): projects, sessions, findings and the runner
on one side, real terminals on the other: the same page on a phone, where
the two sides become a switch.

![The dashboard on a desktop](docs/screenshots/dashboard.png)

<p>
  <img src="docs/screenshots/phone-dashboard.png" width="290"
       alt="The dashboard side on a phone">
  &nbsp;
  <img src="docs/screenshots/phone-terminal.png" width="290"
       alt="The terminal side on a phone, with the tab strip and bottom bar">
</p>

(Staged data. The pictures regenerate with `bash tools/readme-shots.sh`,
which boots the checkout's dashboard against an invented workspace on a
private tmux server and photographs it with `bb shot`: the pattern the
[`bb` helper section](#the-bb-helper) preaches, practiced.)
## Install

The complete checklist, with the decisions each step needs, is
[docs/install.md](docs/install.md); the Unraid-specific detail for every step
is [docs/unraid.md](docs/unraid.md).

0. [Know the three credentials (they are NOT interchangeable)](docs/install.md#0-know-the-three-credentials-they-are-not-interchangeable)
1. [Authorize the server to pull the image (one-time)](docs/install.md#1-authorize-the-server-to-pull-the-image-one-time)
2. [Create the state directories](docs/install.md#2-create-the-state-directories)
3. [Create the secrets folder (recommended)](docs/install.md#3-create-the-secrets-folder-recommended)
4. [Install the container](docs/install.md#4-install-the-container)
5. [Fill in the fields](docs/install.md#5-fill-in-the-fields)
6. [Optional features](docs/install.md#6-optional-features)
7. [First boot](docs/install.md#7-first-boot)
8. [Daily use and updating](docs/install.md#8-daily-use-and-updating)

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | File ownership (Unraid `nobody:users`) |
| `TZ` | `Etc/UTC` | The container's clock, for its logs and file names. Optional: the dashboard shows times in each browser's own zone, or the one picked on the Profile tab's On this browser, kept in a cookie there |
| `SDK_ROOT` | `/sdk` | Where the toolchains *you* install are kept; see [the toolchain store lives outside the image](docs/how-it-works.md#the-toolchain-store-lives-outside-the-image). Falls back to the home volume when no share is mapped. Not CI's: a node runner keeps its own toolchains in its tool cache |
| `NPM_TOKEN` | *(none)* | `npm publish` auth for a shell on the controller (lands in its `~/.npmrc`). A Claude session runs on a node, with that node's home, and does not get it |
| `CHOWN_PROJECTS` | `false` | Recursive chown of project mounts to `PUID:PGID` |
| `BUILDERBOT_PULL` | `missing` | compose's pull policy for the image: `missing` pulls (an install); `build` builds this checkout, which is what BuilderBot's own dev instance sets, with `BUILDERBOT_TAG=dev` |
| `COMPOSE_PROFILES` | empty | compose's own switch: `lab` in a dev instance's env file starts the lab's Gitea beside it (the `gitea` service), for `bb tests lab` |
| `BB_LAB_HOST` | `127.0.0.1` | the address other machines reach that Gitea on |
| `CHOWN_HOME` | `true` | Recursive chown of the home volume at startup. Set `false` if it is large and already correct |
| `DASHBOARD_PORT` | `7680` | The one published port: page, API and terminals (proxied under `/term`) |
| `DASHBOARD_TTYD_PORT` | `7681` | ttyd's loopback bind inside the container; never published |

Mounts: the projects folder, three state dirs (`home`, `config`, `work`), and
two optional ones: `/secrets` (ro, shielded credentials) and `/logs`
(relocate logs).

## The `bb` helper

Bare `bb` prints this list; `bb status` is the tool-version wall.

```
bb status          tool versions, runner registration, mounted projects
bb version         this project's version, and who is allowed to move it
bb version --code  one form only: --code (Android versionCode), --quad (= --win:
                   manifest.json and Windows VERSIONINFO), --msi, --pep440,
                   --file, --semver, --json
bb version bump major|minor|patch    move the target, if the policy allows it.
                   A bump decides the number and closes the changelog under
                   it; it does not release anything. **Release** on the
                   Artifacts tab is the second gesture: an annotated tag
                   (vX.Y.Z, or DIR-vX.Y.Z for a component) on the commit you
                   are on, pushed to the remote. Until that tag exists every
                   build reads X.Y.Z-dev.N+sha, which sorts BEFORE X.Y.Z,
                   heading for it rather than at it; from the tag on, a build
                   of that commit is the bare number. Releasing is the
                   operator's whatever the policy says, and a pushed tag is
                   never moved or deleted from the dashboard.
                   A repo that carries its number somewhere else as well
                   (an agent's protocol number, a template's stamp) declares
                   that by carrying an executable `tools/version-stamp`, run
                   from the repo root with the new version and the part that
                   moved. Whatever it changes is committed with VERSION, so
                   the bump is one commit or none: a hook that fails refuses
                   the bump rather than leaving the number moved and its twin
                   behind. A repo without one is unaffected
bb version init X.Y.Z  give this project (or --for DIR) its first VERSION
bb version unbump      take an unreleased bump back; its changelog section
                   dissolves into Unreleased, the code stays
bb version --list  every version this repo carries: its own, and any component
bb version --for DIR   ask about a component: a directory with its own VERSION
bb version policy  what a session may move here, and who decides. The
                   operator picks it on the Artifacts tab, before or after
                   there is a version: locked (theirs entirely), may start
                   one (a session writes the FIRST version and moves nothing
                   after), patch, patch and minor, or anything
bb changelog       this project's user-facing changelog (--for DIR for a component)
bb changelog add "..." --cat NAME   log what a change means for the person using
                   it; the next version bump dates the accumulated lines. A
                   category is required, and the tool is where the rule lives:
                   Added (somebody can do something they could not), Changed
                   (already here, now different), Deprecated (going away),
                   Removed (gone), Fixed (was wrong, now right), Security
                   (act on it because of what it exposed). When two fit, the
                   one a reader would look under; something nobody using the
                   product would notice gets no entry. Run without a category
                   and it prints this. A name that means one of the six is
                   spelled the one way (`fix` files under Fixed), the six keep
                   their usual order among themselves, and a project that
                   files its own way names its own category, kept as typed and
                   placed at the end: a default, which a house rule overrides.
                   What order the categories and their lines sit in is still
                   the operator's, on the Changelog editor beside the version
bb changelog unreleased  the entries waiting for a bump, numbered straight
                   through the section by category, in the arranged order
bb changelog edit N "..."  reword one of them: a change that tweaks something
                   already logged this cycle corrects its line rather than adding one,
                   and the line gains that commit. --cat NAME on its own moves it
                   and leaves the words, filing it at the end of that category the
                   way add --cat does, so re-filing a line into its own category
                   sends it to the bottom, which is the ordering a session has.
                   --no-stamp corrects a line without claiming a commit made it,
                   which is what a pass over the wording is
bb changelog merge N M "..."   one line for several, carrying all their commits
bb changelog split N     back into one line per commit it carries
bb changelog rm N        drop one that stopped being true
bb projects        mounted project dirs and their branches
bb shell           login shell as the builder user
bb login           Claude Code subscription auth flow, on the machine it is
                   run on. Nothing is copied anywhere
bb login --check   what THIS machine is signed in as, told to the controller,
                   and a sign-out taken here. The grant never travels: every
                   failure this had came from one OAuth pair living on several
                   machines: a refresh rotates the refresh token, so two
                   copies sign each other out, and a machine that was away
                   holds one the server has retired. Each machine signs in for
                   itself and keeps the grant it alone refreshes. What crosses
                   the wire is "I am signed in as X" going up and a generation
                   coming back; behind means the account was signed out while
                   this machine was not listening, and the answer is
                   `claude auth logout` here. Run on every connection and
                   every prompt
bb git push|fetch|pull|ls-remote [ARGS]
bb git policy      what a session may push here (its own branches, main) from
                   the project's Git view; the controller enforces it on the
                   relay, against the refs the push would write: a name that is
                   only on the remote, a tag, --all and deleting a branch there
                   are the operator's whatever the two settings say
                   git's network half, run where the credential is: from a
                   session on a node it goes through the controller
bb emu start [api] | stop | status | list | log [-p]
bb lint [path]     lint a repo's infrastructure files: shell scripts,
                   Dockerfiles, workflows, compose files, XML
bb nodes           the machines enrolled as nodes, read-only in a terminal;
                   the Nodes tab is where they are edited
bb settings        this project's settings as the dashboard has them: node,
                   model, effort, build and test commands, lock. On a node
                   it is relayed from the controller, and it is what bb-tty
                   and bb build read there. `set build|test|outputs VALUE`
                   is the one write: a session fills a field in for the
                   operator, under the project's gate (below).
bb users           the dashboard's accounts. `passwd NAME` resets one from a
                   shell, which is the way back when the owner is locked out
bb work            who else is working this project, and which files two of
                   you have uncommitted at once: read-only
bb jobs [-n N | ID]    the recent jobs: state, node, what ran, how it ended,
                   read-only; the Jobs tab is where one is stopped. An id
                   prints that job's log, which is where a failed job says
                   what happened rather than only that it failed
bb run [opts] -- CMD   snapshot this tree, run CMD on the project's node and
                   stream the log back; `--out GLOB` brings what matches into
                   dist/ with its provenance; `--node` names another node
bb build           the project's build command on its node, with the outputs
                   it lists: all set in the project's settings dialog
bb test [ARGS]     the same for its test command; ARGS are appended to it, so a
                   suite that takes file names runs only those. Where it runs is
                   "Tests run" in the project's settings: on the node, which is the
                   default; inside its dev instance when that is up, else on the
                   node; or only inside it, where a container that is down is a
                   refusal naming it and nothing runs on the node
bb devapp          this project's dev instance: what it was built from, whether it is
                   running, and whether its daemon answers
bb devapp rebuild [--why "..."]
                   build it and bring it up. Only where the project has handed that
                   over: Claude may: Run its container, in its settings dialog and
                   the new-project dialog, reads deny (the default, refused with the
                   sentence that names it), ask (the reason goes to a person and the
                   command waits for Allow) or auto. Up, Down and a container of
                   any other shape stay the operator's
bb devapp new [NAME] [--branch REF] [--env FILE] [--why "..."]
                   send the project to Docker, as the Artifacts tab's Send to Docker
                   manager does, under the same setting: a container made from its
                   own compose file on its node, then built and started, and this
                   waits for the verdict. Unnamed, it is the project's own container
                   while it has none, then another beside it named for the project
                   with -2, -3 and on; a second needs ports of its own, so give it
                   an env that sets them with --env. --branch builds it
                   from that branch. On ask, one request carries all of it and
                   Allow makes and builds it
bb devapp remove [--why "..."]
                   take the container out of the manager, under the same setting;
                   its env and data stay for a remake, as the row's Remove leaves them
bb devapp env [set FILE|-] [--why "..."]
                   print the container's env, or replace it, under the same setting;
                   on ask, Allow writes it and builds nothing, since the card said
                   env set, and the rebuild is the next ask.
                   BuilderBot keeps it per container, never as a file in the project,
                   and points a compose line `env_file: .env` at it when it runs
bb devapp ls       every container that belongs to this project on its node
bb devapp log NAME one of those containers' log
bb devapp start|stop|restart NAME [--why "..."]
                   one of those, under the same setting; --container NAME on the
                   other verbs reaches one written for this project
bb emu create API  build the AVD for an API level, installing its image if missing
bb emu install APK install an APK on the running emulator
bb emu shot [FILE] screenshot the emulator into dist/emu/
bb emu gfx PKG     a package's per-frame timings (gfxinfo framestats) into
                   dist/emu/, and every emu verb runs on the project's node
                   when it has one, its output coming back into dist/
bb emu images [--available]
                   the system images on this machine's toolchain store, or
                   every one there is; `bb emu flavors` says what each is for
bb emu image add|remove ID
                   put a system image on this machine's store, or take one
                   off: a full id or a flavor's short name (tv, wear,
                   playstore). The operator's, like bb toolchains install
bb ci-labels       the runner labels the registry knows; this box's and every
                   node runner's; `--write` regenerates .github/actionlint.yaml
bb findings        this project's scanner findings (--all for every project)
                   narrow with --level error|warning|note, --rule ID, --find TEXT
bb findings history   what the scanner stopped and started saying here
                      (-n N, --since 7d, --find TEXT, as the other logs)
bb findings sample [--remove]   write a clearly-fake report, so the Analysis
                      surfaces can be worked on where no scanner runs
bb token keep      store BB_TOKEN where this account's sessions on this
                   machine read it; the agent runs it for an idle session
bb roadmap            this project's roadmap: items are R1, R2, ...; bugs are B1, B2
bb roadmap show N     one item in full: its details, its steps and theirs (N is R12 or 12)
bb roadmap add "..."  put something on it; `done N` finished, `rm N [why]` abandoned
bb roadmap restore N  put a dropped one back from the history, as it was
bb roadmap shelve N   park one without dropping it; `mv N up|down` moves it
bb roadmap unshelve N [WHY]   ask for one back: held for a person on the project to approve
bb roadmap add "..." --step "..." --step "..."   an ordered group of steps
bb roadmap edit N "..."               reword one; `step add|edit|rm|done` for one step
bb roadmap info N [M] "..."           attach the technical details to one, or step M
bb roadmap begin      work one out; `commit` records it as one change, `revert` undoes
bb roadmap pending    what a session added that is waiting for your approval
bb bug             the bug tracker: open bugs; `all`, `show N` for one in full
bb bug find TEXT   search the reports themselves: area, repro and notes too
bb bug begin       the same notebook batch `bb roadmap begin` opens; `commit`, `revert`
bb bug pending     reports a session filed that are waiting for your approval
bb bug add "..."   report one (--sev, --area, --repro, ...); `note N`, `fix N`,
                   `wontfix N`, `na N`, `reopen N`, `rm N`, `history`
bb tests run [ARGS]  run the project's test command, time it, and record the run: says first when it should
                   finish, and ends by NAMING what went wrong: the failed assertions per file, and for a file
                   that CRASHED the line it died on, the assertions that had already failed before it did,
                   and the fact that nothing after it ran. A crash prints no `FAIL` line and no totals, so a
                   run that only said "failures above" cost four whole runs to read once. ARGS go to the
                   command, so `bb tests run auth cards` times and records those two files and nothing else
bb tests last      that verdict again off the last run's log, running nothing
bb tests log [-f]  the last run's output, whole; -f follows a run still going. The
                   Tests view's Open the run's output sends this into the project's shell
bb devapp test [ARGS]  the project's test command inside its running dev instance, as a compose job on
                   its node: the whole log, and the job's exit code. `bb test` takes this path on its own
                   where "Tests run" in the project's settings says the dev instance, so a suite that
                   tests BuilderBot cannot disturb the BuilderBot it runs on (roadmap R48). Only for an
                   image that carries its tests: one built to ship has none, and a run inside it finds
                   nothing and passes. Claude may: Run its container is not asked: a test runs in a
                   container that is already up
bb tests lab       the lab suites (test/lab-*.mjs) against real services rather than stand-ins.
                   Each names what it needs and skips in one line without it, so a missing service
                   is never a failure, and nothing records them: a lab run is a proof, not a timing.
                   Two services are known. A Gitea: the `gitea` service of BuilderBot's own dev
                   stack, under its compose file's `lab` profile, brought up from the Docker tab
                   like any project's stack (`BB_LAB_GITEA`, the local one by default). A real node,
                   through the controller it is enrolled on: `BB_LAB_CONTROLLER` (that dashboard's
                   address), `BB_LAB_TOKEN` (`user:password` for an administrator there, the lab's
                   own) and `BB_LAB_NODE` (the node by name or id). A job runs on that node, so name
                   one you are willing to have that happen to
bb tests projection  when a run should finish, from what the last one took (--secs for the number)
bb tests accept KEY "why"   the wait is the work: stop flagging it, saying why (--no undoes)
bb rules           the house rules for this project: the operator's and yours
bb rules show NAME one of them in full: what a conditional rule says
bb rules add NAME "..." [--files ...] [--words ...] [--doc PATH] [--check CMD]   leave one of your own
bb rules edit NAME "..." | rm NAME ["why"]            change or drop yours
bb rules check [NAME|--all]   run the checks of the rules whose files you changed
bb rules history   what has changed them, by either of you
bb rules pending   rules a session added that are waiting for your approval
bb preamble        what a session started here is handed: rules, roadmap, bugs (--json for its size)
bb tests           the test registry: where the suite's time goes, slowest first
bb tests show KEY  one test: what it protects, what it exercises, its history
bb tests note KEY "..." [--how "..."]   what it protects, and what it really runs
bb tests describe --from FILE.json      fill many at once, in one write
bb tests ingest [LOG]  record a run's real durations (BB_TEST_TIMING=1 output)
bb tests drift     what the runner reported that this list does not, and back
bb tests flagged   the ones sitting on a round timeout rather than working
bb history         one search over the notebook's logs: roadmap, bugs, memory
                   (`--find X`, `--since 7d`, `-n N`)
bb roadmap history [-n N] [--since 7d] [--find TEXT]   what changed, narrowed
bb phone           what phone is connected, and what is waiting on you
bb phone run --why "..." -- adb args...
                   ask to reach it: the operator allows it on the dashboard
                   and the dashboard runs it, so a session never touches the
                   handset itself
bb container       what container asks are waiting on an administrator
bb container new --why "..." --name NAME --compose FILE [--env FILE] [--node NODE] [--for PROJECT]
                   a container built from a compose file the session wrote,
                   under the project's *Claude may: Run its container*: refused
                   at deny, asked at ask (an administrator reads the file on
                   the bell, and Allow registers it through the Docker tab's own
                   New container path and starts its build), and at auto made
                   at once when it is this project's own on its own node; one
                   for another project or another node is always asked. A
                   published image is a compose naming it; a repository with a
                   Dockerfile is a compose with a build context on the projects
                   share. Never a user's to approve
bb root            what root commands are waiting on an administrator
bb root run --why "..." -- CMD...
                   ask for ONE command as root on this project's node: an
                   administrator allows or denies it on the Nodes tab or the
                   bell, and the node runs that command and nothing else. Not
                   sudo: a second command is a second question. A node's
                   Sessions section can turn root asks off altogether, and
                   the ask is then refused with that said
bb catchup         what has happened here lately: commits with the first line
                   of their bodies, what moved in the notebook, the builds this
                   box archived, and which image it is actually running
                   (`--since 7d`, `-n COMMITS`)
bb ci-log          what CI printed on its last run here (`--list` for the runs
                   kept, a run id for one, `--project NAME` from elsewhere)
bb logs [-f] [N]   this boot's log
bb logs -p [N]     a previous boot's log
bb logs --list     the kept boot logs, newest first
bb logs --node NAME [--agent|--runner|--terminal] [N]
                   a machine's own log: the agent's journal, the CI runner's,
                   the terminal server's. Root's on that box: the enrolled
                   account is in neither `adm` nor `systemd-journal`, so a
                   session cannot read them at all. Offered only while **debug
                   mode** is on in Controller settings AND the asking node has
                   been granted that node on its **Debug settings**, its own
                   journal included; "it is only looking at itself" is the
                   reasoning that makes a boundary stop meaning anything.
                   Which node is asking is the node of the session's own
                   project, proved by its token, never the `BB_NODE` in its
                   environment. What can be read is a table of three streams;
                   anything else is refused, not run
bb diag [--json] [SECTION...]
                   the controller's diagnostics, read-only: its build and the
                   images it ran, its switches, the doctor's every check, each
                   node's agent and session half, the Claude plugins each
                   account installed on each node, the last day's jobs and the
                   failures, error lines from its own logs and the audit
                   trail, with anything shaped like a credential redacted. An
                   administrator's. A session reads it only while **debug
                   mode** is on, its node is ticked for **the controller's
                   diagnostics** on its Debug settings, and its account is an
                   administrator's, so a tester on the same node never gets it.
                   Its `reports` section is what sessions on other projects
                   reported about BuilderBot and nobody has answered yet
bb report "..." [--area A] [--repro "..."]
                   a problem with BuilderBot itself, from a session on any
                   project: it waits on the controller for BuilderBot's own
                   sessions rather than going into the project's tracker (the
                   briefing's notebook section says so), redacted like the
                   diagnostics. `bb report` alone lists the project's reports
                   and what became of each. A `bb bug add` whose words name
                   BuilderBot or a `bb` command is not filed but sent here,
                   unless `--here` says it is the project's own. *Claude may: Report
                   BuilderBot bugs* in a project's settings turns all of it off
                   for that project, rule and nudge included: BuilderBot's own
                   project, whose tracker those bugs belong in, has it off
bb report file N [--sev S] [--as BUG] | close N "why"
                   answer a report, behind the diagnostics' gate: file it as a
                   bug in this project's tracker through `bb bug add` (or mark
                   it as one already there), or close it with the reason its
                   session will read
bb doctor          check everything that usually goes wrong

# developing BuilderBot itself, from inside it
bb dashboard test  browser-test the dashboard from this checkout, isolated
bb dashboard dev   serve the live dashboard from ./scripts/dashboard (--off reverts)
bb dashboard status  which copy of the dashboard is serving
bb dashboard trace [SECONDS]  what the dashboard was asked over the last SECONDS, by endpoint and who asked, with how long each took
bb drift           what this checkout changed that the container is not serving
bb map VERB ...    the code map: find NAME, who-calls NAME, calls NAME, defs FILE,
                   draws ID|.class, suites FILE...; a session asks it before grepping
bb shot URL... [FILE|DIR]  headless screenshot(s) of pages
bb tool            the tools toolchains add to a session, each under its own name
bb tool graphics CMD  pictures a session can make and then read back, with the
                   graphics toolchain on its node: info, resize, crop, compose,
                   annotate, diff, svg2png and optimize, into dist/img/, and
                   favicon SVG [DIR], a favicon set (ico + touch icon) from one mark
bb tool diagrams render FILE...  PlantUML (.puml) and Mermaid (.mmd) rendered to
                   PNG and SVG in dist/diagrams/, with the diagrams toolchain
bb toolchains             SDKs kept outside the image: status, check, install X, update X, remove X
```

The dashboard's Commands flyout carries this same list in this same order.

## Documentation

- [docs/start-here.md](docs/start-here.md): given an account on somebody else's BuilderBot rather than setting one up: the first five minutes, what is shared, and what the refusals mean
- [docs/install.md](docs/install.md): setup, start to finish: the complete checklist with the decisions you need to make
- [docs/unraid.md](docs/unraid.md): step-by-step Unraid walkthrough
- [docs/how-it-works.md](docs/how-it-works.md): the controller, the nodes, the sessions, the dashboard, the notebook, builds, tests, CI, containers and the phone
- [docs/decisions.md](docs/decisions.md): the design decisions, with their dates and reasons
- [docs/layout.md](docs/layout.md): the file-by-file layout
- [docs/nodes.md](docs/nodes.md): design: controller + nodes, homelab-default and enterprise-scalable
- [docs/sandbox-vm.md](docs/sandbox-vm.md): the Docker sandbox VM: why, how, and pointing this at it
- [docs/users.md](docs/users.md): accounts, roles, and what each one may reach
- [docs/design-language.md](docs/design-language.md): what the dashboard's surfaces owe each other
- [docs/journeys.md](docs/journeys.md): what a person does with BuilderBot, walked for real rather than reasoned about

## License

[Apache License 2.0](LICENSE). Copyright 2026 aquilaeLabs; see [NOTICE](NOTICE).
