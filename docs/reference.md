# Reference

The settings the container is given, every `bb` command a session has, the
apps a controller offers, and how Android releases are signed. What each part is for is
[how-it-works.md](how-it-works.md) and the docs it names; setting one up is [install.md](install.md).

## Configuration reference

Only what the container or the host has to know before BuilderBot runs is a
variable; everything else is set in the dashboard: Controller settings (under
Machines) for the controller, a project's settings for the project, the
Nodes page for each machine. Tokens are never variables: git keys and publishing tokens go in the
root-only secrets folder ([unraid.md](unraid.md#shielding-secrets-pat--ssh-keys-from-sessions)),
a project's settings make its deploy key or hold its access token, and a
runner's token is typed on the CI runner page.

| Variable | Default | Purpose |
|---|---|---|
| `PUID` / `PGID` | `99` / `100` | File ownership (Unraid `nobody:users`) |
| `TZ` | `Etc/UTC` | The container's clock, for its log lines. Optional: the dashboard shows times in each browser's own zone, or the one picked under the gear in the header |
| `DASHBOARD_PORT` | `7680` | The one published port: page, API and terminals (websockets at `/termws`) |
| `FEATURES_OFF` | *(empty)* | Features switched off for the whole install, comma-separated: `tunnel`, `ftp`, `phone`, `devices`, `apps`, `image-updates`, `runner`, `enroll`, `shell` (a terminal on the controller itself; a node's stay), `vms` (virtual machines on nodes: the VMs page, `bb vm` and installing VM host), `internet` (an install meant to run offline: apps, image updates, the tunnel and runners with it, and the Doctor skips asking the outside). Each one's controls are drawn dead with the sentence below under them, its requests are refused, and Settings lists them |
| `BANNER_TEXT` | *(empty)* | One line every visitor sees under the header, on every page and the sign-in page: a shared install's word to whoever is on it |
| `BANNER_LINK` | *(empty)* | A link at the banner's end, http(s) or a path on this site; anything else is dropped |
| `BANNER_LINK_LABEL` | *(empty)* | The link's words; "more" when empty |
| `FEATURES_OFF_WHY` | *(empty)* | The sentence a switched-off feature shows; "switched off on this install" when empty |
| `SCANNER_REPORTS_PATH` | `/mnt/user/appdata/scanners/reports` | the directory a scanner on the host writes SARIF into, mounted read-only at `/reports` and read by `bb findings` and the Analysis view; empty where no scanner runs |
| `BUILDERBOT_PULL` | `missing` | BuilderBot's own dev instance only: compose's pull policy, `build` to build this checkout (with `BUILDERBOT_TAG=dev`) |

Mounts: the projects folder, the state directories (`home`, `config`), the
`/sdk` (the browsers `bb capture shot` uses; a node keeps its own
toolchains), and three optional ones: `/secrets` (ro,
shielded credentials), `/reports` (ro, a scanner's output) and `/logs`
(the logs on a share of their own).

### A controller installed bare metal: its env file

A controller installed with `nodes/install-controller.sh` ([install.md](install.md#bare-metal))
reads `/etc/builderbot-controller/controller.env` at every start, in place of
compose's `.env`. It carries the same settings as the table above, under the
same names and with the same defaults (`TZ`, `DASHBOARD_PORT`,
`FEATURES_OFF`, `FEATURES_OFF_WHY`, `BANNER_TEXT`, `BANNER_LINK`,
`BANNER_LINK_LABEL`), but `PUID` and `PGID`, which are the container's alone:
the installer makes an account with ids of its own. In place of compose's
mounts it names the folders:

| Variable | Default | Purpose |
|---|---|---|
| `DASHBOARD_STATE` | `/var/lib/builderbot-controller/config` | The state, compose's `/config`: accounts, settings, notebooks, logs |
| `BUILDER_HOME` | `/var/lib/builderbot-controller/home` | The controller's own home, compose's `/home/builder` |
| `WORKSPACE` | `/srv/builderbot/projects` | The projects, compose's `/workspace` (the installer's `--workspace`); never `/workspace`, which is the machine's own node's synced copy |
| `SDK_ROOT` | `/var/lib/builderbot-controller/sdk` | The toolchain store, compose's `/sdk` |
| `BB_SECRETS_DIR` | `/etc/builderbot-controller/secrets` | The root-only secrets folder, compose's `/secrets`: `*.env` files and `ssh/` |
| `SSH_AUTH_SOCK` | `/run/builderbot-controller/ssh-agent.sock` | The deploy-key agent's socket, in a folder only the controller's account enters |
| `BB_ACCOUNT` | `builderbot` | The account the controller runs as, written by the installer (`--account`); change it by running the installer again |
| `BB_INSTALL` | `bare-metal` | What the install is, written by the installer and read by the controller, never guessed: on a bare-metal install the first run's node is the machine's own, set up by the installer, and Finish waits for it |

A value with spaces in it goes in double quotes. After an edit, `sudo
systemctl restart builderbot-controller`. The file is root's and readable by
the controller's account alone; a session on the machine's own node is kept
out of it, with the rest of the controller (the wall,
[decisions.md](decisions.md#a-controller-installed-bare-metal-and-its-own-node)).

### The install key

The install key seals at rest what BuilderBot keeps that would let somebody
in: the settings' tokens, each project's signing keys, the git credentials a
project holds, the two-factor secrets, and each account's own key; the
sign-in cookies' key is made from it too.

An install makes its own at its first start, so there is nothing to set:
32 random bytes in an `install-key` folder only the controller's account
reads, inside the secrets folder (compose's `/secrets`, the template's
**Secrets directory**, a bare-metal install's `BB_SECRETS_DIR`) when that is
mounted read-write, and beside the state in `/config/.install-key` when
there is none. Kept beside the state, a copy of `/config` carries the key,
so the Keys page and `bb doctor` say so; mount a secrets folder the
controller may write to and the next start moves the key into it. On
Unraid that is the container's **Edit**, **Secrets directory** set to a
folder such as `/mnt/user/appdata/BuilderBot/secrets` with access
**Read/Write**, then **Apply**: an install from a template before 0.8.0
keeps the read-only mount it was made with until it is changed there.

**Controller, Keys** (an administrator's) shows where the key is kept and
its fingerprint, which names it and opens nothing. **Show** puts the key on
the page to copy or download, and **I saved it** marks it saved: keep that
copy apart from `/config`, since a backup restored on a new install opens
nothing that was sealed without it. **Change** makes a new key, or takes one
pasted, and seals everything kept under the one before again under it at
once; people stay signed in until the next restart. The page also lists
everything kept under the key, each with what uses it and where it is
changed.

Each account has a key of its own, kept by the controller under the install
key, for its coding agents' sign-ins sealed on the nodes; changing the
install key leaves those as they are. A person changes their own on
**Profile, Your key**. A sign-in sealed under a key before one that changed
opens with the old key the next time its person opens a terminal on that
node, and is sealed again under the new one; the old key is kept until then.

That key also seals the account's own **key store**, on **Profile, Your key
store**: a token the person gives a repository (an access token in its
settings, or one given when cloning it or linking it to a host) is kept
under their key, not the install's, and the project is linked to it; the
store holds any number for one host, each listed with the projects that use
it, never shown again and never downloaded. Their own git work uses it
ahead of a project's: a `bb git` push or pull from their session, and their
presses in the Git view (one the view hands to a background job uses the
project's). A project's settings list the person's tokens for its remote's
host, with **Use for this project**; CI watching, releases and anybody
without a token of their own then use the one the project is linked to. A
token a project kept before goes into the project owner's store at the
first start that can seal it, BuilderBot's owner taking those of a project
with none. **Purge**
empties the store after a plain confirmation: the key, every forge linked,
and the link of every project that used it, each of which then says on the
bell that its git access went with that account. Deleting the account does
the same, and an administrator can purge an account's store from the Users
page. Purging asks for no password or code, so a person who forgot theirs,
or fears it stolen, can still do it.

`INSTALL_KEY=` in a `*.env` file in the secrets folder (16 characters or
more; never in `.env` or the template's plain fields) sets the key instead,
and the install then makes none. With the secrets folder read-write, the
first start copies that key into its key folder (never beside the state),
and the Keys page says so: take `INSTALL_KEY` out and restart, and the
install carries on with the same key, changed on the page from then on.
Until it is copied, the Keys page says to change it there, with the old one as `INSTALL_KEY_PREVIOUS=` beside it until each
sign-in has moved. `SIGNING_SECRET=`, its name before 0.8.0, is read for one
release.

## The `bb` helper

Bare `bb` prints this list; `bb status` is the tool-version wall.

```
bb -p NAME VERB    any verb, about another project this one reads (its
                   settings name them): bb -p NAME roadmap, bb -p NAME map find X;
                   NAME is its shown name, its folder or its id (P3)
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
                   Artifacts view is the second gesture: an annotated tag
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
bb version release --why "..." [--without-apk]
                   tag this commit and publish the release, as Release on the
                   Artifacts view does, on the controller with the project's own
                   credentials. The project's settings say whether an agent may
                   (Tag and publish a release): auto releases, ask waits for
                   the project's owner, with --why as the reason. A release
                   whose Android APK could not be signed is refused before the
                   tag, saying why; --without-apk goes on, and bb sign release
                   signs it once that is put right
bb version release --edit --why "..." [--tag TAG] [--notes FILE] [--attach FILE]...
                   change the published release under the same setting, each
                   edit its own ask: the notes replaced whole (- reads stdin),
                   a build in dist/ or a committed file attached (one of the
                   same name replaced), (asset:NAME) in the notes the address
                   of that file on the release, (file:PATH) a committed
                   picture shown from the repository at its pushed commit,
                   never a download: the way for a screenshot
bb version release --remove NAME [--remove NAME]... --why "..." [--tag TAG]
                   take files off the published release, named as the forge
                   lists them: its own ask under the same setting, never part
                   of an edit, the names checked against the release first
bb version --list  every version this repo carries: its own, and any component
bb version --for DIR   ask about a component: a directory with its own VERSION
bb version line [X.Y.Z|none]   the release this branch works toward: a branch
                   named for one (claude/0.7.0) works toward it, or set it here;
                   a dev build heads for it (0.7.0-dev.N), a bump moves only
                   to it, and on a patch line bb lint refuses a new migration
bb version policy  what a session may move here, and who decides. A
                   person picks it in the project's settings (Agents may:
                   Move the version) or on the Artifacts view, before or after
                   there is a version: locked (theirs entirely), may start
                   one (a session writes the FIRST version and moves nothing
                   after), patch, patch and minor, or anything
bb changelog       this project's user-facing changelog (--for DIR for a component)
bb changelog add "..." --cat NAME   log what a change means for the person using
                   it; the next version bump dates the accumulated lines. A
                   category is required, and the tool is where the rule lives:
                   Added (somebody can do something they could not), Changed
                   (already here, now different), Deprecated (going away),
                   Removed (gone), Fixed (was wrong in a released version,
                   now right), Security (act on it because of what it
                   exposed). When two fit, the one a reader would look under;
                   something nobody using the product would notice gets no
                   entry, and neither does a fix to something no release has
                   carried yet: the changelog is read by somebody upgrading
                   from a release, who never met that bug. Run without a category
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
                   for itself, from its row on the Nodes page or with this
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
                   own files in /tmp, which in a session is memory; and the quick-boot
                   snapshot of each of this project's phones not started for a week,
                   naming a phone that is not its default and has not run for two
                   (--keep emulator keeps them); --keep one, with the reason in your reply
bb lint [path]     lint a repo's infrastructure files: shell scripts,
                   Dockerfiles, workflows, compose files, XML
bb node busy [--json]
                   whether this node is quiet enough to time anything on: its load,
                   memory and card (what holds the card's memory, by kind), what
                   runs there by kind (emulators, Gradle, compilers, browsers,
                   other agents' sessions working, other projects' jobs, counted
                   and never named) and a verdict: quiet, busy, saturated
bb node wait-quiet [--level quiet|busy] [--timeout SECONDS]
                   wait until it is (quiet twice, ten seconds apart), before a
                   measurement; exits 1, saying how busy, if it never was
bb nodes           the machines enrolled as nodes, each with the agent it runs,
                   read-only in a terminal; the Nodes page is where they are edited
bb nodes show NAME one of them in full, by name or id: its agent against the one
                   this controller ships, and what Update agent would fix
bb nodes enroll-token NAME [--user U] [--own]
                   a new node's enrollment token, printed once, from a shell on
                   the controller: Enroll node's Just a token, for a scripted setup;
                   --own is the controller's own machine, on a bare-metal install
bb projects adopt FOLDER [--name NAME]
                   a folder already under the projects share made a project, as
                   if BuilderBot had made it, from a shell on the controller: a
                   folder made by hand is not one until this says so
bb settings        this project's settings as the dashboard has them: node,
                   model, effort, build and test commands, lock. On a node
                   it is relayed from the controller, and it is what bb-tty
                   and bb build read there. `set build|test|outputs VALUE`
                   is the one write: a session fills a field in for the
                   operator, under the project's gate (below). `node NODE`,
                   from a shell on the controller, sets the project's node as
                   its Settings page does, for a scripted setup.
bb users           the dashboard's accounts. `passwd NAME` resets one from a
                   shell, which is the way back when the owner is locked out;
                   `claim NAME` makes the owner of a new install, as its first
                   page does, for a setup scripted from a shell
bb work            who else is working this project, and which files two of
                   you have uncommitted at once: read-only
bb jobs [-n N | ID]    the recent jobs: state, node, what ran, how it ended,
                   read-only; the Jobs page is where one is stopped. An id
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
                   over: Agents may: Run its container, in its settings dialog and
                   the new-project dialog, reads deny (the default, refused with the
                   sentence that names it), ask (the reason goes to a person and the
                   command waits for Approve) or auto. Up, Down and a container of
                   any other shape stay the operator's. The build sees BB_BUILD_REV,
                   BB_BUILD_AT and BB_BUILD_VERSION, for a compose whose build.args
                   interpolate them, BB_BUILD_TAG, the version as an image tag
                   can carry it, and BB_DOCKER_GID, the node's docker group; its
                   other options are the compose file's own
bb devapp new [NAME] [--branch REF] [--compose FILE] [--override FILE] [--node NODE] [--env FILE] [--why "..."]
                   send the project to Docker, as the Artifacts view's Send to Docker
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
                   Approve makes and builds it
bb devapp remove [--why "..."]
                   take the container out of the manager, under the same setting;
                   its env and data stay for a remake, as the row's Remove leaves them
bb devapp env [set FILE|-] [--why "..."]
                   print the container's env, or replace it, under the same setting;
                   on ask, Approve writes it and builds nothing, since the card said
                   env set, and the rebuild is the next ask.
                   BuilderBot keeps it per container, never as a file in the project,
                   and points a compose line `env_file: .env` at it when it runs
bb devapp override FILE|none
                   lay another compose file from the tree over the container's own
                   (compose's -f after -f), or none; the next rebuild takes it, and a
                   service it adds is asked about as any new one is. On ask it is a
                   person's, in the container's settings
bb devapp ls       every container that belongs to this project, on every node it has one
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
                   whether an agent may (Sign a build): auto signs, ask waits for
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
                   to a key (KEY "" unmaps it), under Agents may: Manage signing
                   keys: auto does it, ask waits for the project's owner. rotate
                   moves the apps OLD's sideload key signs to NEW's: builds go out
                   signed with both and a proof, Android 9 and newer take NEW,
                   older devices keep checking OLD, which is kept for good
bb sign status [TAG]
                   whether a release's APK can be signed (the sideload key, the
                   node with its tools) and how the newest went: handed over,
                   signed and attached with the key's fingerprint, or what
                   stopped it, in the bell's words
bb sign release --why "..."
                   look for unsigned release APKs now and sign a failed one
                   again, as the Signing view's Look for unsigned APKs now,
                   under Sign a build: auto starts it, ask waits for the owner
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
bb roadmap target N X.Y.Z             the release one is meant for (`none` clears); --target
                                      on add sets it, `bb roadmap --target X.Y.Z` lists those;
                                      `target N.M X.Y.Z` (or N M) is step M's own, `none`
                                      sends it back to its item's, and --target lists an item
                                      for any step meant for that release
bb roadmap begin      work one out; `commit` records it as one change, `revert` undoes
bb roadmap pending    what a session added that is waiting for your approval
bb bug             the bug tracker: open bugs; `all`, `show N` for one in full
bb bug find TEXT   search the reports themselves: area, repro and notes too
bb bug begin       the same notebook batch `bb roadmap begin` opens; `commit`, `revert`
bb bug pending     reports a session filed that are waiting for your approval
bb bug add "..."   report one (--sev, --area, --repro, ...); `note N`, `fix N`,
                   `wontfix N`, `na N`, `reopen N`, `rm N`, `history`. With
                   --repro, --reproduces always|sometimes|once|untried says how
                   often those steps showed it; --report N files diagnostics
                   report N with its words, area, repro and that answer
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
                   nothing and passes. Agents may: Run its container is not asked: a test runs in a
                   container that is already up
bb tests unit      the python unit tier (scripts/dashboard/unit): the modules' rules without a server
                   or a browser, in under a second; preflight runs it before any suite
bb tests lab       the lab suites (test/lab-*.mjs) against real services rather than stand-ins.
                   Each names what it needs and skips in one line without it, so a missing service
                   is never a failure, and nothing records them: a lab run is a proof, not a timing.
                   Two services are known. A Gitea: the `gitea` service of BuilderBot's own dev
                   stack, under its compose file's `lab` profile, brought up from the Containers page
                   like any project's stack (`BB_LAB_GITEA`, the local one by default), and
                   a Forgejo beside it (`BB_LAB_FORGEJO`, port 3001), which the forge suite
                   runs against a second time under its own catalog entry. A real node,
                   through the controller it is enrolled on: `BB_LAB_CONTROLLER` (that dashboard's
                   address), `BB_LAB_TOKEN` (`user:password` for an administrator there, the lab's
                   own) and `BB_LAB_NODE` (the node by name or id). A job runs on that node, so name
                   one you are willing to have that happen to. A VM host there as well
                   (`BB_LAB_VMHOST`, with `BB_LAB_KEY` an ssh public key) walks every Linux
                   system Enroll node offers as a VM made a node, enrolled to Uninstall
                   (lab-systems, slow: each system takes its ten to twenty minutes);
                   with `BB_LAB_SSH` (that key's private half, a path on the VM host) and
                   `BB_LAB_REF` (a pushed ref) it installs a controller bare metal in a VM
                   and tries the wall around its own node (lab-baremetal)
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
                   session, whichever agent runs it, or kept after that session started
bb design          what this project looks like, from the notebook's Design view:
                   its design language in a line, and its pages
bb design show [ID|NAME]   the prompt for one page, or for the language alone:
                   the colors as tokens, the type, the shape, the layout
bb design file [--from FILE]   docs/design-language.md as the notebook writes it;
                   --from renders it from a record (bb design json, edited) instead
                   of the saved design, so a branch writes the file from its own
bb design json     the record: the language, the pages, and the presets by key
bb design schema   the record's shape with every limit, for a save that lands first time
bb design save FILE   write a record of that shape back, whole: how a session
                   puts a design language it was given into the notebook
bb wiki            the project's wiki, from the notebook's Wiki view: its pages,
                   who changed each last, and where it is pushed
bb wiki show NAME [--rev]   one page's Markdown (--rev: the revision a save checks)
bb wiki save NAME FILE|- [--why "..."]   write a page whole, new or rewritten,
                   under Agents may: Write the wiki: auto lands it, ask holds it
                   for the operator, deny refuses it, hidden keeps the whole
                   wiki from a session, reading included. A page changed since the
                   save began is refused rather than overwritten
bb wiki rm NAME [--why "..."]   take a page out, under the same setting
bb wiki mv OLD NEW   rename one; bb wiki history: the last changes
bb transcripts     your own conversations on this project, from every coding agent
                   you use, each marked with its agent, newest first, as the
                   Profile page lists them (bb -p NAME for one it reads)
bb transcripts show ID [--tz ZONE] [--all]   one of them as text: what was said,
                   every command it ran and what it answered; the newest
                   16 MB of a longer one, the whole of it with --all
bb transcripts fetch ID [--into DIR]   the file itself into this machine's folder
                   for it: how a node holding its projects as a synced copy
                   resumes a conversation it does not have (bb-tty runs it)
bb memory          your memories on this repository, kept for every coding agent:
                   the index, newest first (bb -p REPO for another repository
                   of the project, which keeps them when it moves)
bb memory show NAME   one of them whole
bb memory add NAME --type user|feedback|project|reference --about "one line" "what to remember"
                   save one, with its line in the index: a fact about one
                   repository on that repository
bb memory forget NAME   take one out
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
                   these asks the phone's owner and runs on their Approve
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
                   in front (another project's keyboard), and Approve for this
                   session does not cover it; bb phone ui prints the screen's
                   layout under the same rule
bb vm [list]       this project's VMs (R91): state, OS, node, address, size, snapshots
bb vm os           the operating systems a VM is made from
bb vm new NAME --os OS [--vcpus N] [--mem 4G] [--disk 20] [--disks 100,500] [--node NODE] [--key FILE] [--pin 2,3] [--mem-max 8G] [--share PATH [--ro]] [--autostart] [--node-agent] --why "..."
                   a VM on one of the project's nodes with VM host installed,
                   letting in this session's ssh key (made when there is none);
                   the project's Make VMs setting decides: deny refuses, ask
                   waits for an administrator's Allow, auto makes it now.
                   --node-agent enrolls it as a node at its first boot, which
                   an administrator always allows; --disks gives it up to
                   three more, --pin, --mem-max and --share are as bb vm
                   hardware says, --autostart starts it when its node boots
bb vm start|stop|restart|rm NAME [--force]
                   one VM, under the same setting; stop asks it to shut down,
                   --force pulls the plug
bb vm snapshot NAME SNAP [--note "..."] | revert NAME SNAP | snapshot-rm NAME SNAP
                   its state saved under a name and gone back to; a running
                   VM's memory is kept too, so a revert lands mid-program
bb vm grow NAME [vda|vdb|vdc|vdd] GB | disk-add NAME GB | eject NAME
                   a stopped VM's disk made larger or another added, and an
                   installer's ISO taken out of its drive
bb vm hardware NAME [--pin 2,3|none] [--share-cpus] [--mem-max 8G|none] [--share PATH|none] [--ro]
                   a stopped VM's hardware beyond its size (R100), what is
                   named and no more: its vCPUs pinned to host threads, the
                   memory it may balloon up to, a folder of the project seen
                   inside it by mount -t virtiofs project /mnt; the LAN and a
                   device passed through are a person's, on the VMs page
bb vm autostart NAME on|off
                   whether it starts when its node boots
bb vm ip NAME | ssh NAME [COMMAND...]
                   its address, and ssh in as its account
bb container       what container asks are waiting on an administrator
bb container new --why "..." --name NAME --compose FILE [--env FILE] [--node NODE] [--for PROJECT]
                   a container built from a compose file the session wrote,
                   under the project's *Agents may: Run its container*: refused
                   at deny, asked at ask (an administrator reads the file on
                   the bell, and Approve registers it through the Containers page's own
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
                   administrator allows or denies it on the Nodes page or the
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
bb logs --node NAME [--agent|--runner|--nginx|--system|--kernel|--crash] [N]
                   a machine's own log: the agent's journal (its terminals'
                   among it), the CI runner's, its nginx's where the nginx
                   page put one, this boot's system journal, its kernel ring, and the
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
                   project is granted **the controller's diagnostics** on
                   the Debug page, and its account has the grant.
                   Its `reports` section is what sessions on any project
                   reported about BuilderBot, kept until a person clears them
bb report "..." [--area A] [--repro "..." --reproduces always|sometimes|once|untried]
                   a problem with BuilderBot itself, from a session on any
                   project: it goes into the controller's diagnostics rather
                   than the project's tracker (the briefing's notebook section
                   says so), redacted like the diagnostics, and nothing comes
                   back to follow up. A `bb bug add` whose words name
                   BuilderBot or a `bb` command is not filed but sent here,
                   unless `--here` says it is the project's own. *Agents may: Report
                   BuilderBot bugs* in a project's settings turns all of it off
                   for that project, rule and nudge included: BuilderBot's own
                   project, whose tracker those bugs belong in, has it off
bb report conversation N   the conversation a person sent with a report (the
                   end of it, redacted), behind the same gate
bb pc [VERB] [--why "..."]
                   a person's Windows PC lent to this project by the Windows
                   companion: bare, which PCs lend which verbs; a verb
                   (editor-start, editor-stop, game-start, game-stop, build,
                   shot, log, editor-call METHOD PATH) runs on the PC as its
                   person set it up there and waits for what it did, a
                   picture landing in dist/pc/. Under *Agents may: Use a lent
                   PC* (Deny by default; Ask puts each use in front of the
                   person at the PC); never a command string
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
                   takes the one shot at once. Into dist/shot/ for a page and
                   dist/emu/ for the emulator when no FILE is named.
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
                   shots), each with who asked and when: the Artifacts view's
                   Captures fold, in the terminal
bb capture prune [--days N] [NAME...]
                   remove those named now, or every capture older than N days.
                   A capture is somebody's until the project's "captures kept"
                   days are up (7 unless its settings say otherwise), and the
                   controller sweeps them when the Artifacts view draws: name
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

## The apps a person installs

The apps are built for every release and attached to it, each with a
`.sha256` file beside it. A controller offers the ones ticked
under **Apps** on its Controller settings page: a while after it starts and once a day it fetches each from
the release matching its own version (the newest release when none does,
and the section says so), keeps it only if it matches its sha256, and
serves it from `/config/apps`. A switch moved, or **Look now**, looks at
once.

| Where | What |
|---|---|
| Build, Apps | each offered app with its version, **Download**, and how to connect it |
| Settings, Profile | the devices signed in as you, with **Disconnect** |
| `GET /apps/NAME/FILE` | one file the controller holds (`android`), for anybody signed in |
| `GET /api/apps` | what is offered and held: each app's files, their sha256 and size, the release, when it last looked |
| `POST /api/v1/device/apps` | the same for a device's app (its own token), to update itself from; `GET /api/v1/device/app-file?app=NAME&file=FILE` fetches one |

A device's app sends the door it speaks as `X-BB-Door` (none means 1) and
which app and release it is as `X-BB-App`; one from
before the controller's window is answered 426 with the way to update, by
name. The device door's `projects` and `apps` answers say the controller's
`door` and `door_min`, so an app newer than its controller says so plainly.
What each released app reads is pinned with its types (the Android app's
in `android/api-surface.json`): a field may be added at any time, and removed
only in the release after the apps that read it stopped, with the pin moved
in the same change and a changelog line.

### The seed file

A compose generator (the website's) writes `/config/seed.json` beside the
compose file to choose what a new controller offers before anybody signs in:

```json
{"version": 1, "apps": ["android", "companion"]}
```

Read once, on the first start that finds it: each app named is offered and
each one left out is not. It is then renamed `seed.json.applied`, and
Controller settings owns the choice from there. Nothing about it is in the
environment.

## Signing Android releases

A project keeps its Android keys on the controller, in the **Signing** view of
its page (under Ship), and a build is signed on its node as a job no session can look
inside: from the Artifacts view, or by a session with `bb sign`, under the
project's **Agents may: Sign a build**. Everything that needs a jdk or the
build-tools happens on the project's node too, never on the controller:
checking an uploaded keystore, Generate, a wrapped backup, a rotation's proof
and a release's APK are each a job there, handed the key for that job alone.
So the node the project's settings choose needs the **jdk** and **Android SDK
Build-Tools** (with android-tools, which installs them) from its Toolchains,
and the Signing view says which node it is and what it lacks when it cannot.
No key is made or added until the
project's owner has set its **backup password**, which every download of a
key's backup asks for, BuilderBot's owner included; a backup goes only to an
administrator who works on the project.

| Key | For | If it is lost or leaks |
|---|---|---|
| Play upload key | Google Play with Play App Signing: you sign the `.aab` with it, Google re-signs what users download with the key it holds | Play Console resets it |
| Sideload signing key | an APK you hand out yourself, or that F-Droid publishes from a reproducible build | gone for good: no update reaches an existing install, or anybody can ship one over it |

On the controller every key is sealed at rest under the **install key**
([The install key](#the-install-key)), which the install makes itself
unless `INSTALL_KEY=` sets one. Each keystore and its passwords under
`/config/signing` are ciphertext, so a copy of `/config`, or a backup of it,
opens no key; keys kept from before are sealed at the next start. Changing
the key on the Keys page seals them again under the new one. A key lost, or
replaced outside the page, leaves the sealed keys shut: the Signing view
says so, and each key comes back by **Import a backup**. Root on the running
controller can still read them.

So a sideload key is downloaded once with **Download backup** and kept
offline, with its password somewhere apart from it; its row says so in red
until it has been. A lost backup password is not reset from the dashboard:
signing goes on, and only somebody with a shell on the controller can clear
it, so keep it as carefully as the key. A signed build's Artifacts
row gives the certificate's whole fingerprint, with **Copy for F-Droid** for
its metadata. Using one key on Play, F-Droid and your own downloads (so users
can move between them) means giving Play that key when the app is first set
up there. A project can keep several named keys (one per app, or one shared),
generated on the project's node or uploaded, with each app's package mapped to its
key, and a sideload key can be **rotated** to another: builds then carry both
and a proof, Android 9 and newer move to the new key, and the old one is kept
for the devices before that. **Import a backup** takes what Download backup
gave, in this project or another, as the same key. [building.md](building.md#android-signing-keys)
has the rest.
