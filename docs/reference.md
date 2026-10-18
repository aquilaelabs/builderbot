# Reference

The settings the container is given, every `bb` command a session has, and
how Android releases are signed. What each part is for is
[how-it-works.md](how-it-works.md); setting one up is [install.md](install.md).

## Configuration reference

Only what the container or the host has to know before BuilderBot runs is a
variable; everything else is set in the dashboard: Settings for the
controller, a project's settings for the project, the Nodes tab for each
machine. Tokens are never variables: git keys and publishing tokens go in the
root-only secrets folder ([unraid.md](unraid.md#shielding-secrets-pat--ssh-keys-from-claude-sessions)),
a project's settings make its deploy key or hold its access token, and a
runner's token is typed on the Nodes tab.

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | File ownership (Unraid `nobody:users`) |
| `TZ` | `Etc/UTC` | The container's clock, for its log lines. Optional: the dashboard shows times in each browser's own zone, or the one picked on the Profile tab |
| `DASHBOARD_PORT` | `7680` | The one published port: page, API and terminals (proxied under `/term`) |
| `SCANNER_REPORTS_PATH` | `/mnt/user/appdata/scanners/reports` | the directory a scanner on the host writes SARIF into, mounted read-only at `/reports` and read by `bb findings` and the Analysis view; empty where no scanner runs |
| `BUILDERBOT_PULL` | `missing` | BuilderBot's own dev instance only: compose's pull policy, `build` to build this checkout (with `BUILDERBOT_TAG=dev`) |

Mounts: the projects folder, the state directories (`home`, `config`), the
`/sdk` (the browsers `bb capture shot` uses; a node keeps its own
toolchains), and three optional ones: `/secrets` (ro,
shielded credentials), `/reports` (ro, a scanner's output) and `/logs`
(the logs on a share of their own).

## The `bb` helper

Bare `bb` prints this list; `bb status` is the tool-version wall.

```
bb -p NAME VERB    any verb, about another project this one reads (its
                   settings name them): bb -p NAME roadmap, bb -p NAME map find X
bb status          tool versions, runner registration, the projects here
bb version         this project's version, and who is allowed to move it
bb version --code  one form only: --code (Android versionCode), --quad (= --win:
                   manifest.json and Windows VERSIONINFO), --msi, --pep440,
                   --file, --semver, --json
bb version bump major|minor|patch    move the target, if the policy allows it.
                   A bump decides the number and closes the changelog under
                   it; it does not release anything. It commits on the branch
                   the checkout is on and pushes nothing, and says so when
                   that is not the branch builds come from. **Release** on the
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
bb version set X.Y.Z   straight to a later version in one commit, allowed
                   when the policy allows the largest part it moves; from a
                   number never released (no tag), its changelog section is
                   dated as the new one
bb version unbump      take the last unreleased bump or set back; its
                   changelog section dissolves into Unreleased, the code
                   stays. Once: the bump before it is not taken back too.
                   A section dated under the wrong number is fixed with
                   unbump, then set to the number meant
bb version release --why "..."
                   tag this commit and publish the release, as Release on the
                   Artifacts tab does, on the controller with the project's own
                   credentials. The project's settings say whether Claude may
                   (Tag and publish a release): auto releases, ask waits for
                   the project's owner, with --why as the reason
bb version release --edit --why "..." [--tag TAG] [--notes FILE] [--attach FILE]...
                   change the published release under the same setting, each
                   edit its own ask: the notes replaced whole (- reads stdin),
                   a build in dist/ or a committed file attached (one of the
                   same name replaced), (asset:NAME) in the notes the address
                   of that file on the release, for a screenshot
bb version release --remove NAME [--remove NAME]... --why "..." [--tag TAG]
                   take files off the published release, named as the forge
                   lists them: its own ask under the same setting, never part
                   of an edit, the names checked against the release first
bb version --list  every version this repo carries: its own, and any component
bb version --for DIR   ask about a component: a directory with its own VERSION
bb version policy  what a session may move here, and who decides. A
                   person picks it in the project's settings (Claude may:
                   Move the version) or on the Artifacts tab, before or after
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
bb projects        the project dirs here and their branches
bb shell           login shell as the builder user
bb login           Claude Code subscription auth flow, on the machine it is
                   run on. Nothing is copied anywhere: each node is signed in
                   for itself, from its row on the Nodes tab or with this
bb login --check   what THIS machine is signed in as, told to the controller.
                   The login itself never travels
bb git push|fetch|pull|ls-remote [ARGS]
bb git policy      what a session may push here (its own branches, main) from
                   the project's Git view; the controller enforces it on the
                   relay, against the refs the push would write: a name that is
                   only on the remote, a tag, --all and deleting a branch there
                   are the operator's whatever the two settings say
                   git's network half, run where the credential is: from a
                   session on a node it goes through the controller
bb emu start [api] | stop | status | list | log [-p] | adopt
                   the project's own emulator: its phones are this project's
                   alone, made on the first start; adopt moves the account's
                   phones from before that into this project, once
bb emu touch tap X Y | hold X Y --ms N | glide X Y X Y... [--hand NAME] [--seed N] [--pre MS] [--hold MS] [--mark FILE]
                   a timed touch on the running emulator, in screen pixels;
                   a glide moves like a hand (steady, normal, shaky, or
                   ruler for the straight even stroke), repeatable by seed,
                   at the pace asked whatever a move costs the device;
                   --mark FILE is made when the finger arrives to be held
bb gpu             this node's NVIDIA card: how much of its memory is free, who is
                   computing on it, and whether this session may
bb gpu run [--mem MB] -- CMD
                   CMD with a turn on the card: one heavy job at a time per node, waiting
                   for its turn and for MB of free memory rather than failing on a full card
bb browser open --ext DIR [--firefox] [--url URL] [--headed]
                   Chrome (or Firefox) with an unpacked extension loaded, headless,
                   detached on a debugging port and a profile of its own: its id,
                   its port and the extension's id
bb browser go|eval|shot ID ...
                   go ID URL (ext:PAGE for the extension's own), eval ID JS (the
                   value as JSON), shot ID FILE (a PNG of the page on show)
bb browser list | stop ID|--all
                   the ones open; stop ends one by its process group and removes
                   its profile
bb proc [PATTERN]  this account's processes with PATTERN in their command line, never
                   the call's own shell (which pgrep -f matches): pid, age, command
bb proc stop PATTERN [--grace S]
                   end them: SIGTERM, then SIGKILL after S seconds (3)
bb proc wait PATTERN [--timeout S]
                   wait until none is left (600s), saying what is left if some is
bb tidy [--keep emulator|gpu|gradle|browser|server|tmp]... [--dry]
                   after a task or a batch of them, give back what it left holding:
                   this session's emulator (through bb emu stop), anything else of
                   its own on the NVIDIA card, its Gradle and Kotlin daemons, the
                   headless browsers a test left behind, a server it put in the
                   background and left listening (a dev server, a preview), and its
                   own files in /tmp, which in a session is memory; --keep one, with
                   the reason in your reply
bb lint [path]     lint a repo's infrastructure files: shell scripts,
                   Dockerfiles, workflows, compose files, XML
bb node busy [--json]
                   whether this node is quiet enough to time anything on: its load,
                   memory and card (what holds the card's memory, by kind), what
                   runs there by kind (emulators, Gradle, compilers, browsers,
                   other Claude sessions working, other projects' jobs, counted
                   and never named) and a verdict: quiet, busy, saturated
bb node wait-quiet [--level quiet|busy] [--timeout SECONDS]
                   wait until it is (quiet twice, ten seconds apart), before a
                   measurement; exits 1, saying how busy, if it never was
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
bb devapp probe [--port N] [--path /x]
                   whether it answers on its node's loopback: each published port
                   open or refused, and the HTTP status of a GET of the path; a read,
                   so no root ask; --container NAME for another of the project's
bb devapp rebuild [--why "..."]
                   build it and bring it up. Only where the project has handed that
                   over: Claude may: Run its container, in its settings dialog and
                   the new-project dialog, reads deny (the default, refused with the
                   sentence that names it), ask (the reason goes to a person and the
                   command waits for Allow) or auto. Up, Down and a container of
                   any other shape stay the operator's. The build sees BB_BUILD_REV,
                   BB_BUILD_AT and BB_BUILD_VERSION, for a compose whose build.args
                   interpolate them; its other options are the compose file's own
bb devapp new [NAME] [--branch REF] [--compose FILE] [--override FILE] [--node NODE] [--env FILE] [--why "..."]
                   send the project to Docker, as the Artifacts tab's Send to Docker
                   manager does, under the same setting: a container made from its
                   own compose file on its node, then built and started, and this
                   waits for the verdict. Unnamed, it is the project's own container
                   while it has none, then another beside it named for the project
                   with -2, -3 and on; a second needs ports of its own, so give it
                   an env that sets them with --env. --branch builds it
                   from that branch; --compose names another of its compose
                   files (site/compose.yml), the root's own by default; --override
                   lays another compose file from the tree over it, for this one
                   container (its own ports, env or an extra service). --node
                   puts it on a hosting node ticked under the project's Also
                   works on (marked Hosting only): built on the project's own
                   node and shipped there. On ask, one request carries all of it and
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
bb devapp override FILE|none
                   lay another compose file from the tree over the container's own
                   (compose's -f after -f), or none; the next rebuild takes it, and a
                   service it adds is asked about as any new one is. On ask it is a
                   person's, in the container's settings
bb devapp ls       every container that belongs to this project on its node
bb devapp log NAME one of those containers' log
bb devapp start|stop|restart NAME [--why "..."]
                   one of those, under the same setting; --container NAME on the
                   other verbs reaches one written for this project
bb sign FILE [--for play|sideload] [--why "..."]
                   sign a build in dist/ with one of the project's keys, on its
                   node, as a job this session cannot look inside: the key and
                   its password never reach the session. --for play is the Play
                   upload key (the default for an .aab), sideload the app signing
                   key (the default for an .apk). The project's settings say
                   whether Claude may (Sign a build): auto signs, ask waits for
                   the project's owner to allow it, with --why as the reason.
                   Arrives in dist/ as NAME-signed.apk or .aab. --key NAME signs
                   with that key; without it, the key the build's package is
                   mapped to, else the project's default
bb sign keys       the project's keys by name, their fingerprints and which
                   package each signs (never a key or a password)
bb sign key new NAME --for play|sideload --why "..."
bb sign map PACKAGE KEY --why "..."
bb sign rotate OLD NEW --why "..."
                   a new key made on the controller, or an app's package mapped
                   to a key (KEY "" unmaps it), under Claude may: Manage signing
                   keys: auto does it, ask waits for the project's owner. rotate
                   moves the apps OLD's sideload key signs to NEW's: builds go out
                   signed with both and a proof, Android 9 and newer take NEW,
                   older devices keep checking OLD, which is kept for good
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
bb roadmap reopen N   put back one finished since the last release, for the same goal
bb roadmap shelve N   park one without dropping it; `mv N up|down` moves it
bb roadmap unshelve N [WHY]   ask for one back: held for a person on the project to approve
bb roadmap add "..." --step "..." --step "..."   an ordered group of steps
bb roadmap edit N "..."               reword one; `step add|edit|rm|done` for one step
bb roadmap info N [M] "..."           add the technical details to one, or step M,
                                      under what is there (--replace sets them)
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
bb tests unit      the python unit tier (scripts/dashboard/unit): the modules' rules without a server
                   or a browser, in under a second; preflight runs it before any suite
bb tests lab       the lab suites (test/lab-*.mjs) against real services rather than stand-ins.
                   Each names what it needs and skips in one line without it, so a missing service
                   is never a failure, and nothing records them: a lab run is a proof, not a timing.
                   Two services are known. A Gitea: the `gitea` service of BuilderBot's own dev
                   stack, under its compose file's `lab` profile, brought up from the Docker tab
                   like any project's stack (`BB_LAB_GITEA`, the local one by default), and
                   a Forgejo beside it (`BB_LAB_FORGEJO`, port 3001), which the forge suite
                   runs against a second time under its own catalog entry. A real node,
                   through the controller it is enrolled on: `BB_LAB_CONTROLLER` (that dashboard's
                   address), `BB_LAB_TOKEN` (`user:password` for an administrator there, the lab's
                   own) and `BB_LAB_NODE` (the node by name or id). A job runs on that node, so name
                   one you are willing to have that happen to
bb tests projection  when a run should finish, from what the last one took (--secs for the number)
bb tests accept KEY "why"   the wait is the work: stop flagging it, saying why (--no undoes)
bb rules           the house rules for this project: the operator's and yours
bb rules show NAME one of them in full: what a conditional rule says
bb rules add NAME "..." [--files ...] [--words ...] [--doc PATH] [--check CMD]   leave one of your own
                   [--refuse "CMD, CMD"]: commands it refuses outright when a session runs one
                   [--replaces RULE]: the global rule it takes the place of in this project
                   [--why "..."]: the reason behind it, kept for show and the tab, never sent
bb rules edit NAME "..." | rm NAME ["why"]            change or drop yours
bb rules check [NAME|--all]   run the checks of the rules whose files you changed
bb rules history   what has changed them, by either of you
bb rules pending   rules a session added that are waiting for your approval
bb rules audit [DAYS]   your conversations here over DAYS (7): the commands a rule
                   refuses, run or tried, and the code map asked against grep
bb preamble        what a session started here is handed: rules, roadmap, bugs (--json for its size)
bb help TOPIC      one topic of the session briefing in full (start, where, map, build, tidy,
                   speed, capture, asks, notebook, versions, git, android, gpu, containers);
                   bb help topics lists them, bb help VERB one verb's lines
bb brief           the brief this project was started from: waiting for its first
                   Claude session, or kept after that session started
bb design          what this project looks like, from the notebook's Design view:
                   its design language in a line, and its pages
bb design show [ID|NAME]   the prompt for one page, or for the language alone:
                   the colors as tokens, the type, the shape, the layout
bb design file     docs/design-language.md as the notebook writes it
bb design json     the record: the language, the pages, and the presets by key
bb design schema   the record's shape with every limit, for a save that lands first time
bb design save FILE   write a record of that shape back, whole: how a session
                   puts a design language it was given into the notebook
bb wiki            the project's wiki, from the notebook's Wiki view: its pages,
                   who changed each last, and where it is pushed
bb wiki show NAME [--rev]   one page's Markdown (--rev: the revision a save checks)
bb wiki save NAME FILE|- [--why "..."]   write a page whole, new or rewritten,
                   under Claude may: Write the wiki: auto lands it, ask holds it
                   for the operator, deny refuses it, hidden keeps the whole
                   wiki from a session, reading included. A page changed since the
                   save began is refused rather than overwritten
bb wiki rm NAME [--why "..."]   take a page out, under the same setting
bb wiki mv OLD NEW   rename one; bb wiki history: the last changes
bb transcripts     your own conversations with Claude on this project, newest
                   first, as the Profile tab lists them (bb -p NAME for one it reads)
bb transcripts show ID [--tz ZONE]   one of them as text: what was said, every
                   command Claude ran and what it answered
bb transcripts fetch ID [--into DIR]   the file itself into this machine's folder
                   for it: how a node holding its projects as a synced copy
                   resumes a conversation it does not have (bb-tty runs it)
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
bb phone lease     whether the phone is lent to this project, for how long, and
                   which of its apps the lease covers. While lent, each of
                   these asks the phone's owner and runs on their Allow
                   (--why "..." is the sentence they read), or at once
                   once they allowed this session's commands:
bb phone install dist/APP.apk   install one of this project's builds; its
                   package joins the lease
bb phone start|stop|ime|log PKG   run, stop, pick as keyboard, or read the
                   logcat of a lease app
bb phone shot      the screen, into dist/phone/
bb phone record [SECONDS] | record start [SECONDS] | record stop
                   a video into dist/phone/, with its reel beside it (the
                   frames that changed, with their times, in one picture);
                   start leaves it running while touches work the phone,
                   stop collects it
bb phone touch tap X Y | hold X Y [--ms N] | glide X Y X Y... [--hand NAME] [--seed N] |
                   text "..." | key back|enter|del|tab|space|up|down|left|right
                   only while a lease app is in front or is the keyboard;
                   --any-app asks the owner for that one touch on whatever is
                   in front (another project's keyboard), and Allow for this
                   session does not cover it; bb phone ui prints the screen's
                   layout under the same rule
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
bb root run --why "..." [--node NAME] -- CMD...
                   ask for ONE command as root on this project's node (or, with --node
                   NAME, on a node it hosts containers on; the row's root-asks switch
                   decides): an
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
                   kept, a run id for one, `--project NAME` from elsewhere);
                   for a project on GitHub's own runners, its runs and the end
                   of each failed job's log, read by the controller from GitHub
bb logs [-f] [N]   this boot's log
bb logs -p [N]     a previous boot's log
bb logs --list     the kept boot logs, newest first
bb logs --node NAME [--agent|--runner|--terminal|--nginx|--system|--kernel|--crash] [N]
                   a machine's own log: the agent's journal, the CI runner's,
                   the terminal server's, its nginx's where the nginx tab put
                   one, this boot's system journal, its kernel ring, and the
                   previous boot's last lines (--crash: what the box said
                   before it went). Root's on that box: the enrolled
                   account is in neither `adm` nor `systemd-journal`, so a
                   session cannot read them at all. Offered only while **debug
                   mode** is on in Controller settings, the session's project
                   has been granted that node's logs under **Debug** in its
                   settings, its own node included, and the session's account
                   has the **debug** grant, which is the owner's unless a role
                   names it. The project is the session's own, proved by its
                   token. What can be read is a table of three streams;
                   anything else is refused, not run
bb diag [--json] [SECTION...]
                   the controller's diagnostics, read-only: its build and the
                   images it ran, its switches, the doctor's every check, each
                   node's agent and session half, the Claude plugins each
                   account installed on each node, the last day's jobs and the
                   failures, error lines from its own logs and the audit
                   trail, with anything shaped like a credential redacted. The
                   **debug** grant's: the owner's, or a role's that names it.
                   A session reads it only while **debug mode** is on, its
                   project is granted **the controller's diagnostics** under
                   Debug in its settings, and its account has the grant.
                   Its `reports` section is what sessions on any project
                   reported about BuilderBot, kept until a person clears them
bb report "..." [--area A] [--repro "..."]
                   a problem with BuilderBot itself, from a session on any
                   project: it goes into the controller's diagnostics rather
                   than the project's tracker (the briefing's notebook section
                   says so), redacted like the diagnostics, and nothing comes
                   back to follow up. A `bb bug add` whose words name
                   BuilderBot or a `bb` command is not filed but sent here,
                   unless `--here` says it is the project's own. *Claude may: Report
                   BuilderBot bugs* in a project's settings turns all of it off
                   for that project, rule and nudge included: BuilderBot's own
                   project, whose tracker those bugs belong in, has it off
bb report conversation N   the conversation a person sent with a report (the
                   end of it, redacted), behind the same gate
bb doctor          check everything that usually goes wrong

# developing BuilderBot itself, from inside it
bb dashboard test  browser-test the dashboard from this checkout, isolated
bb dashboard dev   serve the live dashboard from ./scripts/dashboard (--off reverts)
bb dashboard status  which copy of the dashboard is serving
bb dashboard trace [SECONDS]  what the dashboard was asked over the last SECONDS, by endpoint and who asked, with how long each took
bb drift           what this checkout changed that the container is not serving
bb map VERB ...    the code map, which a session asks before grepping: find NAME,
                   who-calls NAME, calls NAME, defs FILE, draws ID|.class,
                   suites FILE..., state [FILE], sections FILE, unused [FILE],
                   addresses [FILE...], coverage, covered NAME, uncovered [FILE],
                   affected --base REF FILES..., languages (which files it
                   reads), build; bb map help says what each does
bb capture shot URL... [FILE|DIR] | --emu [PKG] [FILE] | --display :N [FILE]
                   one picture at rest: a page, the running emulator's screen,
                   or an X display (--drive F works the surface first). At rest
                   means shots a quarter second apart until a second of them
                   match, so a modal still arriving or a list still loading is
                   not the picture: the dashboard's own pages and the two other
                   sources settle by default, --settle asks it of any page, --now
                   takes the one shot at once. Into dist/emu/ for the emulator.
                   A page that does not answer is no picture and exit 3; one
                   that answers 4xx or 5xx is shot, and the status said
bb capture reel --video FILE|--url URL|--emu [PKG]|--display :N [--seconds N] [--drive F]
                   eyes on change over time: the frames of a recording that changed,
                   each stamped with its time, tiled into dist/reel/NAME/sheet.png
                   beside frames.json (when, and how much moved). From a video, a
                   page Playwright records while --drive FILE.mjs works it, the
                   running emulator's screenrecord (with gfxinfo framestats beside
                   it), or an X display grabbed while a shell script drives it with
                   xdotool; the provisioner installs Xvfb and xdotool for that.
                   Only the sheet and frames.json land in dist/: the recording
                   and the full-size frames are on this machine's disk, where
                   frames.json says
bb capture ls      the captures in this project's dist/ (reels and emulator
                   shots), each with who asked and when: the Artifacts tab's
                   Captures fold, in the terminal
bb capture prune [--days N] [NAME...]
                   remove those named now, or every capture older than N days.
                   A capture is somebody's until the project's "captures kept"
                   days are up (7 unless its settings say otherwise), and the
                   controller sweeps them when the Artifacts tab draws: name
                   yours here to let them go sooner
bb tool            the tools toolchains add to a session, each under its own name
bb tool graphics CMD  pictures a session can make and then read back, with the
                   graphics toolchain on its node: info, resize, crop, compose,
                   annotate, diff, svg2png and optimize, into dist/img/, and
                   favicon SVG [DIR], a favicon set (ico + touch icon) from one mark
bb tool diagrams render FILE...  PlantUML (.puml) and Mermaid (.mmd) rendered to
                   PNG and SVG in dist/diagrams/, with the diagrams toolchain
bb tool docs read FILE...  a PDF, Word document, slide deck or spreadsheet as
                   Markdown on stdout, with the documents toolchain
bb tool docs pages FILE [--pages N-M] [--dpi N]  its pages as pictures in
                   dist/docs/NAME/, for layout, charts and scans; a file that
                   is not a PDF is made one by the office toolchain first
bb tool office convert FILE... [--to FORMAT]  LibreOffice with no window: a
                   document into pdf (the default), docx, xlsx, pptx or odt
bb tool sound make PRESET [--seed N] [--name N] [--wav]  a sound effect for an
                   app from sfxr's presets (blip, pickup, jump, laser, hit,
                   powerup, explosion, bloop), into dist/sound/ as OGG, with a
                   waveform and a spectrogram beside it to check it by; tone
                   HZ [--ms N] [--to HZ] makes a beep or a sweep, look FILE
                   draws any sound, presets lists them; say "TEXT" speaks it
                   into a WAV (piper) and hear FILE writes down what a
                   recording says with its times (whisper), which need the
                   audio toolchain
bb toolchains             SDKs kept outside the image: status, check, install X, update X, remove X
```

The dashboard's Commands flyout carries this same list in this same order.

## Signing Android releases

A project keeps its Android keys on the controller, under **Signing keys** in
its settings, and a build is signed on its node as a job no session can look
inside: from the Artifacts tab, or by a session with `bb sign`, under the
project's **Claude may: Sign a build**. No key is made or added until the
project's owner has set its **backup password**, which every download of a
key's backup asks for, BuilderBot's owner included; a backup goes only to an
administrator who works on the project.

| Key | For | If it is lost or leaks |
|---|---|---|
| Play upload key | Google Play with Play App Signing: you sign the `.aab` with it, Google re-signs what users download with the key it holds | Play Console resets it |
| Sideload signing key | an APK you hand out yourself, or that F-Droid publishes from a reproducible build | gone for good: no update reaches an existing install, or anybody can ship one over it |

So a sideload key is downloaded once with **Download backup** and kept
offline, with its password somewhere apart from it; its row says so in red
until it has been. A lost backup password is not reset from the dashboard:
signing goes on, and only somebody with a shell on the controller can clear
it, so keep it as carefully as the key. A signed build's Artifacts
row gives the certificate's whole fingerprint, with **Copy for F-Droid** for
its metadata. Using one key on Play, F-Droid and your own downloads (so users
can move between them) means giving Play that key when the app is first set
up there. A project can keep several named keys (one per app, or one shared),
generated on the controller or uploaded, with each app's package mapped to its
key, and a sideload key can be **rotated** to another: builds then carry both
and a proof, Android 9 and newer move to the new key, and the old one is kept
for the devices before that. [how-it-works.md](how-it-works.md#android-signing-keys)
has the rest.
