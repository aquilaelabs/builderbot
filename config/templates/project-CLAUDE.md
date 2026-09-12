# Working inside BuilderBot

<!-- BUILDERBOT:ENV:BEGIN -->
<!-- BUILDERBOT:ENV:WINDOW 0.5 -->
<!-- Everything between these markers is generated from BuilderBot's shipped
     template and is safe to replace wholesale:
         bb claude-md            # is this copy current?
         bb claude-md --update   # refresh just this block
     Your project's own notes live BELOW the end marker and are never touched.
     Edits inside this block are lost on the next --update; put them below. -->

You are running inside **BuilderBot**, on one of its **nodes** — the machines
where sessions, builds, tests, CI and the Android emulator run. The controller
is a long-lived container on an Unraid server: it keeps the dashboard, the
notebook and the record, carries no Claude Code, and starts no session, so
there is nowhere else for this conversation to be. `bb status` names the
machine you are on. This file describes the environment; it is not a
description of the project itself.

## Check this file is current, first

Before anything else in a session:

```bash
bb claude-md
```

That compares the environment block above against the template the container
ships, and changes nothing. If it reports the block differs, run
`bb claude-md --update` and mention that you did — the update rewrites only the
marked block and never touches the project notes below the end marker. (The
dashboard notices the same drift on its own and offers the update as a link on
the project's row, so it may already have been done for you.)

**Two of the cases are enforced, not advised.** A session outlives a container
update, so a hook on every tool call refuses to run anything while the
controller is not answering (restarting after an update) or while this block
is from another compatibility window, and says which: wait for the one, ask
the operator for the other. A block merely behind inside the window stops
nothing — you are told once, on a prompt, that an update is waiting.

The block carries the compatibility window it was written for — the
`BUILDERBOT:ENV:WINDOW` line under the begin marker, BuilderBot's minor
version. Drift inside a window is routine and stops nothing. A block from
another window does: the dashboard ends the sessions running on that project,
ghosts its Claude button and refuses a new one until the block is updated —
and, for a project on a node, until that node's agent is from the same
window too.

Two things about doing it:

- The refresh lands **for the next session**. Your context already holds the
  old text, so re-read this file if you need the new content now.
- If the environment turns out to disagree with what this file says, the
  machine is right and the file is stale. Trust `bb doctor` and `bb status`
  over anything written here.

Do not create a `CLAUDE.md` anywhere one does not already exist — `--init` is
the user's decision, not a session's.

## What persists and what does not

This matters more than anything else here. Three of the things you touch are
not this machine's own, and those three are the ones that survive it being
rebuilt:

| Thing | Where |
|---|---|
| This project, including uncommitted work | `/workspace/<project>` — the projects share, mounted whole at `/workspace`, so every folder in it is here and on every other node |
| SDKs and toolchains — Android packages, Playwright browsers, Flutter/.NET/Swift | the packages store this node mounts, symlinked into place. `bb packages` lists them and says where it is |
| The notebook — roadmap, bugs, rules, memories, transcripts | the controller's, reached through `bb`. Nothing of it is kept here |

Everything else is this machine's own disk: your shell history and caches
under `~`, the AVDs, `/tmp`, anything a package manager put on it. That
survives a reboot and is nobody's backup.

So: **never `apt-get install` something and consider the problem solved.** A
tool a project needs is installed through the package manager on its node
(the Tools tab), which puts it on the store — where it persists, where
`bb packages` can see it, and where the next node gets it too. Say what is
missing rather than installing it yourself.

Uncommitted work in this project is **not** at risk from a restart of
anything: it is on the share. It is still worth committing, but do not
panic-commit on the theory that something is about to eat it.

## Stay in this directory

`/workspace` holds *other projects* as sibling directories — the whole projects
share is mounted there, so that is every folder in it, not a hand-picked few.
Your working directory is this project. Do not read from or write to sibling
projects, and do not go looking for context in them — if something seems to be
missing, ask.

A sibling directory holding a `.bbignore` file is not a project at all — it is
BuilderBot's own storage (the package store) or something the operator chose to
hide. Leave those alone too.

If this session was started from the dashboard, that is also enforced: the file
tools — `Read`, `Edit`, `Write` and `NotebookEdit` — are denied every sibling
path, via a settings file passed on the command line. One of them coming back
denied for a path outside this project is that rule, working as intended — not
a bug to route around with Bash.

Bash is **not** covered by it, and that is worth knowing rather than
discovering: `cat ../other-project/src/main.kt` works. The settings file is a
guardrail against wandering into the wrong tree by mistake, not a sandbox. The
rule above is the actual boundary; the file tools just make it harder to cross
by accident.

## There is no display

Everything is headless: no window manager, no monitor, nothing to show a GUI
on. Run every tool in its headless mode and show the user pixels by saving a
screenshot to a file.

On a node with a GPU passed through there may be an X server on `:0` all
the same, and it is not an exception to any of that. It is started at boot
for one reason: NVIDIA's EGL will not hand out a display without one, and
without EGL the Android emulator cannot use the card. It has no window
manager, no monitor and one intended client. Do not read `$DISPLAY` being
set as permission to open a window on it.

- **Playwright** — the browsers live on the package store, which is a
  different path on the controller and on a node: `$PLAYWRIGHT_BROWSERS_PATH`
  is the one that is right wherever you are, and `bb packages` prints it. Run
  headless. You do not need `playwright install` — they arrive with the store,
  and `bb packages install playwright` repairs them. If a project pins its own
  version, point `executablePath` at `$PLAYWRIGHT_BROWSERS_PATH/chromium`. The
  module is global: `require()` finds it from any directory via `NODE_PATH`,
  ESM `import` does not honor that, so use
  `createRequire(import.meta.url)('playwright')`.
- **`bb shot URL... [FILE|DIR]`** — headless screenshot(s) of any pages, for
  showing the user visual state. Takes `--full`, `--scale N`, `--wait MS`,
  `--resize W` for README-quality captures — a docs-screenshot script should
  boot the app and end with one `bb shot` line, not carry its own Playwright.
- **Screenshots** are the way to show the user visual state — save to a file
  and surface the path.

## The toolchain is the store, not the machine

**What this node carries by itself is small**: `git`, `tmux`, `jq`,
`python3`, `curl`, and Docker where it runs containers. That is what its
provisioner installs and all it installs.

Everything else — `node`, the JDK, the Android SDK and its system images,
Playwright's browsers with their module, Flutter, the .NET SDK, Swift, the
lint tools — lives on the **packages store**, a share this node mounts. So
which of them exist here is a runtime fact, not something to infer from this
file:

```bash
bb packages            # what is installed, where each one lives, and what is not
```

**It answers for the store this project builds with**, which is this
machine's — the same one `bb build`, `bb test` and `bb emu` use — so what it
lists is what a build here can use. `bb nodes` names it.

`bb status` prints the same summary in two lines. Check before concluding a
tool is missing, and check before reaching for a system package manager —
the thing you want may be one `bb packages install` away, or already installed
somewhere PATH does not look until the next shell.

Never `apt-get` around a gap: what you install by hand is on this machine
only, invisible to `bb packages`, and gone when the node is rebuilt. One
`bb lint` check skipping, or `bb shot` failing to find its module, means a
recipe is not installed yet — say which.

If a project needs one that is not there, **say so and ask** — you cannot
install it yourself. `bb packages install` refuses to run from a session and tells
you to hand the decision back: these are gigabytes on someone else's disk.
The operator does it from the dashboard's Tools tab (Additional packages),
where the checkboxes and the uninstall controls live, or by running the
command you offer them.

Installing one is not a reason to edit this file: `bb packages` is the source of
truth, and it is accurate the moment something lands.

<!-- BUILDERBOT:IF android *.gradle *.gradle.kts settings.gradle settings.gradle.kts android AndroidManifest.xml app/src/main/AndroidManifest.xml -->
## Android

Only relevant if this is an Android project.

```bash
bb emu list       # which API levels are configured, and which AVDs exist
bb emu start      # boot the default AVD headless (takes ~50s cold)
bb emu start 37   # boot a specific API level, if it is configured
bb emu status     # adb devices -l
bb emu stop       # graceful shutdown — use this, do not kill the process
bb emu log [-p]   # this boot's emulator log; -p is the one before it
bb emu gpu        # hardware or software rendering, and why
```

The emulator is **not** started automatically, holds a few GB of RAM, and runs
one at a time — so start it when you need it and stop it when you are done.

**The emulator is this machine's**, and so are the system images, the GPU and
the adb it answers on — the verbs run right here and `adb` reaches it
directly. What a verb writes lands in `dist/`: `bb emu shot` for a
screenshot, `bb emu gfx PKG` for real per-frame timings. `bb emu install
FILE` installs from `dist/`. `bb emu create API` builds its AVD when the
node's store has none yet.

Which API levels exist is what the node's packages store holds a system
image for — the operator adds one from the Tools tab with that node picked,
or `bb emu create API` fetches it on demand. Run `bb emu list` before assuming a
version is available; if the one you need is missing, say so rather than
trying to install it — a runtime `sdkmanager` install works but the user
should decide to spend the disk.

### When the screen is blank but the app is fine

Three failure modes here are the emulator's, not Android's and not the app's.
All three look like a bug in what you just wrote, and none of them are — so
check these before you go looking:

- **Every frame blank, view hierarchy complete.** Under a software GPU the
  guest has no DRM render node, so HWUI's default Vulkan backend cannot
  start: the app draws, `uiautomator` sees every view, and the pixels come
  out empty. The one hint is `E/MESA: Failed to open rendernode` in logcat.
  `bb emu start` now sets `debug.hwui.renderer=skiagl` at boot, so this
  should be gone — if you meet it, check the property survived
  (`adb shell getprop debug.hwui.renderer`) and say so, because a shell
  `setprop` does not survive a reboot and was the old workaround.
- **A window stops updating part-way through a long session.** After many
  minutes of screenshots and input, a running app's surface silently freezes:
  the hierarchy is still complete, `screencap` returns flat white.
  `am force-stop` and relaunch paints fine. The host log shows
  `Failed to find EmulatedEglImage` when it happens. **If pixels go blank
  while the hierarchy is intact, restart the app before suspecting your
  code.**
- **The emulator dies silently.** `adb` calls start hanging, then
  `adb devices` is empty and `bb emu stop` says there is nothing to stop —
  the process simply exited. Recovery is `bb emu start`. The post-mortem is
  `bb emu log -p`: the log rotates on each start rather than being
  overwritten, precisely so the account of a death survives the restart that
  follows it.

**Which renderer you got is a question with a one-line answer**, and it is
worth asking before drawing conclusions about performance or about a blank
screen:

```bash
bb emu gpu        # hardware or software, and why
```

With a GPU passed through, this machine starts a headless X server for it at
boot and `bb emu start` uses `-gpu host` *if EGL actually answers there with a
vendor driver*. It tests rather than assumes, because the failure mode in
between is the expensive one: Mesa will happily answer on an X server it
cannot accelerate and hand back llvmpipe, which is software wearing hardware's
name. Anything short of a real answer falls back to `swiftshader_indirect`,
which is what this box did for months.

Under software rendering there is one more consequence worth internalizing:

> **`screenrecord` captures ~10fps under software rendering.** Do not use it to
> verify animation timing — a 300ms transition is 3 frames and you will draw
> the wrong conclusion. Use `dumpsys gfxinfo <pkg> framestats` for real
> per-frame timestamps. It works under any renderer.

Judging whether a duration *feels* right is a question for real hardware, and
you should say so rather than guessing from a headless emulator.

<!-- BUILDERBOT:END -->
## What you can build, and where

Compiling happens here, on the node this project is bound to, with the
toolchains this machine carries. Which node that is is a per-project setting
the operator owns.

```bash
bb build            # the project's build command, on its node
bb test             # its test command, on its node
bb run -- CMD       # anything else there, from a snapshot of this tree
```

**You are reading this ON a node, because there is nowhere else to read it
from.** A session runs on the machine its project is bound to: the controller
keeps the dashboard, the notebook and the record, carries no Claude Code, and
starts no session at all. A project with no node has no session — pressing
Claude on it says so and names what to do, rather than opening a conversation
that cannot build anything.

So the node you are on is the whole of what you have: its toolchains, its
`/dev/kvm`, its card, its share mounts. `bb nodes` names it and `bb packages`
says what it carries.

**When its toolchain is missing what a build needs, there are two honest
answers** and the refusal names whichever applies:

- **The project can push** — commit, push, and let CI build it. That is the
  fallback, and it is a real one: the workflow runs on a runner with the
  toolchain.
- **It cannot push** — then say plainly that the project cannot be built
  until the operator installs it from the Tools tab or grants push rights. Do
  not invent a local build, do not `apt-get` a compiler, and do not report
  success you did not observe.

**That is not hypothetical.** A node that carries no JDK cannot build an
Android app, and `bb build` refuses before queueing anything, naming the tool
and the Tools tab. Again: CI if the project can push, otherwise say so.

`bb nodes` names the project's node and what its census reports it carries.

## A phone, if one is connected

Only relevant when a phone is connected on this project's node.

A phone is paired and connected on a **node**, on the dashboard's Phone tab,
and a project's sessions reach the phone on the project's node and no other.
Pairing is once per node; if the phone is not showing as connected, the
answer is almost always Connect rather than Pair.

**You cannot reach it directly, and that is deliberate.** The handset is kept
on an adb server of its own, so `adb devices` here shows the emulator and
nothing else. Asking for the phone goes through the person who connected it:

```bash
bb phone                                    # which nodes hold one, whose, what is waiting
bb phone run --why "..." -- shell getprop ro.build.version.release
```

That puts your reason and the exact command in front of the account that
connected the phone — on their Phone tab and their bell, nobody else's — and
waits. On **Allow** the node runs it and hands you the output; on **Deny**
you are told no. There is no setting that skips the question. The reason is
required — they are being asked about a command they did not write, and
without a sentence saying what it is for, allowing it is a guess. Write the
sentence you would want to read.

It waits fifteen minutes and then gives up, so do not open one and wander
off. And do not go looking for the port the phone is on: reaching around
this is possible, in the way most things on a machine are possible, and it
is the one thing here that touches hardware somebody is holding.

## One command as root, if you truly need it

You have no sudo on a node and will not get one. Almost nothing needs it:
packages are the Tools tab's, mounts and addresses the Nodes tab's, and a
tool that clones, builds or syncs runs as you. When something genuinely
does — a kernel module, a device permission, a daemon setting — ask for that
one command the way you ask for the phone:

```bash
bb root                                     # what is waiting on an administrator
bb root run --why "..." -- modprobe binder_linux
```

That puts your reason and the exact command in front of a person and waits:
the account whose session this is, when it is an administrator's — on their
Nodes tab and bell — and otherwise every administrator, because a sandbox is
a shared machine and root on it is not a user's to allow (their own phone
is). On **Allow** the node runs that command as root and hands you the
output, on **Deny** you are told no. A second command is a second question.
It works only on a node provisioned as a sandbox — somebody's own machine is
not yours to run root on.
A node whose system changes are locked to its own console refuses the ask
outright and says so; that is the operator's decision, not a fault.
Write the reason you would want to read, and ask for the smallest command
that does the job, not a shell.

## What version this is

Every project here uses the same scheme, and `bb version` is what makes it the
same one — it is on your PATH in any project, so there is nothing to set up
and nothing to agree about.

```bash
bb version              # the identity, and who is allowed to move it
bb version --file       # the form to put in a dist/ filename
bb version --code       # Android versionCode; also --quad/--win, --msi,
                        #   --pep440, --semver, --json
bb version policy       # what a session may move here, and who decides
```

It is built from three parts: a `VERSION` file at the repo root holding one
line of `MAJOR.MINOR.PATCH`, the commit count (`git rev-list --count HEAD`),
and the short sha — rendered as `MAJOR.MINOR.PATCH-dev.<count>+<sha>`, or as
whatever format the thing you are stamping demands. **Use `bb version --file` for the
artifact name** rather than inventing one; that is what makes two builds
tellable apart in the Artifacts tab.

**Bumping is not releasing, and the `-dev` is how you tell.** Two gestures,
and both are the operator's to press: a **bump** decides the number and
closes the changelog under it, in one commit; a **release** says it happened
— an annotated tag `vX.Y.Z` (or `DIR-vX.Y.Z` for a component) on that
commit, pushed. Until the tag exists every build reads `X.Y.Z-dev.<n>+<sha>`,
which sorts BEFORE `X.Y.Z`: heading for it rather than at it. From the tag
on, a build of that commit is the bare number. `bb version` says which of the
two has happened — *building towards* or *released as* — so when somebody
asks whether something shipped, that line is the answer rather than a guess.

A project with no `VERSION` file still answers, falling back to `git describe`.
Giving it one is `bb version init 0.1.0` — which the same policy governs, so
under the default `locked` it is the operator's, from the Artifacts tab. There
is a setting for exactly this case: *may start one, not move it* lets you
write the first version and leaves every move after it theirs. Do not write
the file by hand; that is the one path deliberately closed.

**The operator may ask you what it should start at.** Pressing *Ask Claude*
on that tab sends the question here, the way a roadmap step arrives. The
judgment is the whole of what they are asking for: read the code, the
roadmap and the changelog, decide how finished this actually is and what has
shipped, and say what you concluded and why. Then **propose, and ask** —
they came to negotiate, and a number applied on arrival skips the
conversation they wanted. Do not propose `1.0.0` unless they raise it.

**The number is this project's own, and nothing here suggests one** — not an
example in this file, not BuilderBot's own version, not a sibling
project's. A number you did not derive from this code base is
the wrong number, however plausible it looks.

**A repo that ships two products has two versions.** An APK and a browser
extension do not share a maturity, so a directory with its own `VERSION` file
is a *component* and answers for itself: `bb version --for extension`, and
`bb version --list` for everything this repo carries. Its ordinal counts only
the commits that touched that directory, so a shipped extension stops
appearing to change every time the app beside it is edited. **Stamp each
artifact from its own component** — using the project's number for all of them
tells whoever installed the extension that it moved when it did not. A
component's release tag is `<dir>-vX.Y.Z`; the repo's own `vX.Y.Z` says
nothing about a component, even when the numbers coincide.

**Log what a change means for the person using the product.** Beside the
version sits its changelog, and you write it:

```bash
bb changelog add "Pairing no longer fails when you switch screens"
bb changelog add "…" --cat Fixed   # file it under a category
bb changelog            # read it; --for DIR for a component's own
bb changelog unreleased # what is waiting for a bump, numbered, by category
bb changelog edit 3 "…" # reword entry 3 rather than logging it twice
bb changelog edit 3 --cat Fixed    # move it, leaving the words alone
bb changelog merge 2 5 "…"   # one line for several, carrying their commits
bb changelog split 2    # back into one line per commit it carries
bb changelog rm 2       # drop one that stopped being true
```

**The arrangement is the operator's, and the numbers are positional.** A
category is a `### Name` subsection — the Keep a Changelog shape — and which
categories exist, what order they sit in and what order the lines run inside
them are all decided by hand, on the Changelog editor beside the version.
`--cat` files an entry at the end of a category, making the category at the
end of the section if it is new — on `add` and on `edit` alike, so re-filing
a line into its own category sends it to the bottom of that category. That is
the only ordering you have; where a CATEGORY sits is not a session's call.
Entry numbers count straight through the whole section, categories and all,
and they move whenever it is rearranged, so read `bb changelog unreleased`
before naming one.

A changelog line is not a commit message. The commit says what happened to
the code; this line says what changed for the person holding the app, in
their words — if it only makes sense to someone reading the source, reword it
or leave it out. Log after committing (the entry is stamped with the commit
it describes), once per user-visible change rather than once per commit, and
into the component the change belongs to. Entries accumulate under
Unreleased; when the operator bumps the version they become that release's
dated section, so nothing is lost while the number waits.

**When a change tweaks something already logged this cycle, correct that
line instead of adding one.** Read `bb changelog unreleased` before you log:
if an entry there already describes the thing you just changed — a fix on a
fix, a second pass over one feature — `bb changelog edit N "…"` rewords it.
The line keeps every commit it already carried and gains yours, oldest
first, so the entry names all the commits that made it. A correction with no
commit behind it — a pass over the wording, a move between categories — takes
`--no-stamp`, or names no new words at all, and then claims nothing. Use your judgment: two lines about
one change tell the reader about it twice, but a genuinely separate change
is a new line. Only Unreleased is editable; a dated section is a release
somebody may have read.

**You very likely cannot move it, and that is the point.** Which parts a
session may bump is a per-project setting the operator owns: the default is
`locked`, meaning none. `bb version bump minor` refuses and says so, and in a
dashboard-started session the file tools are denied on `VERSION` — the same
guardrail, and the same honest limit, as the sibling-project rule above. So
propose a bump in your reply, with what shipped since the last one, and let
the operator move it; do not route around the refusal. `bb version policy`
prints the limit you are under.

## What you build goes in dist/

When a build produces something shippable — an APK, a browser extension's
.xpi, an installer — **copy it into the project's `dist/` directory**, named
with its version. The dashboard's Artifacts tab lists `dist/` and nothing
else: build systems scatter their outputs, so the deal is one word long, and
an artifact left in `app/build/outputs/...` simply does not exist as far as
the operator's tab is concerned. Subdirectories one level down are fine
(`dist/android/app-1.2.apk`).

**Gitignore it.** The tab reads the filesystem, not git, so nothing is gained
by committing a build — and a 24MB APK per build is history nobody wants.
Document the rebuild command in the README instead, so the artifact is
reproducible rather than stored.

`bb version --file` already carries something that moves between builds, so a
name built from it is never ambiguous. If you name an artifact some other way,
make sure something in it changes per build — the short commit, usually — or
every build is named identically and the tab cannot tell this one from the
last.

From that tab the operator downloads any of them, installs an `.apk` on their
paired phone (which replaces an existing copy in place, keeping its data),
pushes an `.xpi` to it, and reads a shell script without downloading it — a
file is a script by its extension or by its shebang, so a shipped installer
does not have to be called `.sh` to be treated as one. Nothing auto-pushes: a push is a decision the operator
makes each time, so do not design around the extension on the handset staying
current — say when a rebuild is worth pushing instead.

<!-- BUILDERBOT:IF compose docker-compose.yml docker-compose.yaml compose.yml compose.yaml -->
## The dev instance, if this project has a compose file

The **Docker** tab may carry a row for this project: the operator builds its
compose app and brings it up and down from there, and the Artifacts tab is
where it is sent there from. **Making a container, removing one, Up, Down and
Env are the operator's** and no setting hands any of them over. If the
instance's env needs filling in, say so and let them press the buttons; the
env file lives outside the repo on purpose.

**Rebuild is the one that can be handed to you**, per project, with the dial
on that project's row in the **Docker** tab, beside the Rebuild it hands
over. It reads `deny`, `ask` or `auto` and starts at deny:

```bash
bb devapp              what it was built from, whether it is running, and
                       whether its daemon answers
bb devapp rebuild      build it and bring it up
bb devapp rebuild --why "..."     ...on `ask`: the sentence goes to a person
```

That is the loop for a project whose work IS the container: change it,
rebuild it, look at what it did. On **deny** the verb is refused with a
sentence naming the dial, and that sentence is the thing to quote rather
than a thing to route around. On **ask** the reason and what it would
rebuild go in front of a person, the command waits up to fifteen minutes,
and their Allow is what starts the build — so write the sentence you would
want to read, the same as for the phone and for root.

**You have no Docker socket of your own, and that is deliberate.** The daemon
belongs to the node, and membership of its docker group is root on that
machine, so the account your session runs as is not in it: a bare `docker
build` here fails with a permission error. The rebuild above works because it
goes through the controller, which holds the connection. Anything else that
genuinely needs docker is one command asked for the way root is asked for:

```bash
bb root run --why "..." -- docker build -t thing:latest /workspace/thing
```

What is yours either way: keeping `docker-compose.yml` and `.env.example`
true. The rebuild flow reads `.env.example` to know when new settings need
filling in, so a new variable your code reads belongs there in the same
commit.

<!-- BUILDERBOT:END -->
## House rules

How the operator wants this project worked on, and what a session has learned
about working on it. If this project has any, they are already in your prompt
— you will have met them before this line. They live in `/config`, never in
the repository, and are read at the start of every session started here.

```bash
bb rules                # what is in effect here
bb rules show NAME      # one of them in full
bb rules add NAME "..." [--files scripts/agent] [--words agent,protocol]
bb rules edit NAME "..." | bb rules rm NAME ["why"]
bb rules history        # what has changed them, by either of you
```

**Both of you write them, and each is marked with who did** — the mark
(yours or a session's) and the account behind it, so two people on one
project are told apart. Yours are marked
`*` wherever they appear; you may reword or drop those. The operator's you may not touch — say in your reply if one looks
wrong, and they change it on the Briefing tab. Every change either of you
makes is in `bb rules history` with a name against it, which is what makes
this shared rather than locked.

A rule with a trigger — files it covers, words that raise it — is named in
your prompt with its triggers and not quoted: a paragraph about the agent is
not worth paying for on a CSS change. Its text arrives whole on the turn it
becomes relevant, because you were asked about a word it names or are about
to edit a file it covers. `bb rules show NAME` reads one before either of
those happens. Only a rule with no trigger at all is quoted to you in full.

**A rule can carry a whole framework.** `--doc PATH` names the document in
the repo that defines it in full, and `--check CMD` the command that verifies
it. Under a rule with a doc, read the doc before the work; under one with a
check, run `bb rules check` before calling the work done — it runs the checks
of the rules whose files you changed, and fails by name.

**What belongs here rather than in a memory.** A memory is something you
noticed; a rule is something that should hold for whoever works here next,
including a person. "The suite takes ten minutes" is a memory. "A new
top-level name in index.html goes in test/surface.mjs, or the suite cannot
see it" is a rule — it is about this project and it applies to anybody.
When you learn one of those, `bb rules add` it and say so in your reply. The
operator may have set this project to hold or refuse a session's new rules,
the same way as roadmap items; `bb rules pending` lists what is waiting.

## The roadmap

Every project has a notebook in the dashboard — the briefing, the roadmap,
bugs, and the repository's own history, branches and diffs on its Git view,
one tab each. The roadmap is the shared list of design work, and both you and
the operator write it.

```bash
bb roadmap                      # what is on it
bb roadmap add "..."            # put something on it
bb roadmap done N               # finished it — off the list, into the log
bb roadmap rm N ["why"]         # not doing it — same, and say why it went
bb roadmap shelve N             # parked: keep it, not now
bb roadmap mv N up|down         # move one up or down the list
bb roadmap edit N "..."         # reword one
bb roadmap info N [M] "..."     # the technical details, on an item or step M
bb roadmap step add N "..."     # give one a step; step edit N M "...", step rm N M
bb roadmap step done N M        # you finished step M — ticked, and no longer offered
bb roadmap begin | commit | revert    # work a plan out, recorded once
bb roadmap history [-n N] [--since 7d] [--find TEXT]   # what changed, narrowed
```

**The open items are already in your context**, appended when this session
started. There is nothing to go and read at the top of a conversation and
nothing to recite back: the operator is looking at the same list.

**The letter says which list.** A roadmap item is `R4`, a bug is `B4`, a rule
is named. Write the letter whenever you name one, because `#4` alone could be
either tab, or a pull request. The number is the item's own and survives the
list being rearranged.

**When you notice something worth doing and it is out of scope for what you
are on, put it on the list — not only in your reply.** A reply is read once,
at the end of a task the operator has already finished thinking about; the
list is read at the start of every conversation after it. This is their own
reason for it existing:

> sometimes you mention things and I forget that you did

So say it in the reply *and* add it. What you add is marked as yours, so they
can see what you raised and sweep it if they disagree.

**Tick things off as you finish them**, including items you did not add: a
list that only grows is one that stops being read. Done takes it off the list
and has no undo — if it turns out not to have been finished, add it again and
say so. Dropping is for work that is abandoned, and a dropped item can be put
back from the history; done is not how a finished plan leaves. Only you tick
things off, because only the session that did the work knows whether it is
done.

**A group is one goal with an order to it, and its title is that goal.** Group
steps only when every one of them serves a single outcome — "the picker works
on a phone", not "four things I noticed". Somebody reading only the title
should know what finishing it would look like. If you cannot write the title
without listing the steps, it is not one goal and should not be one group.

**Steps are expensive.** Each is a message the operator sends by hand, one at
a time, waiting on each. A step is not a task, it is *a point at which the
previous work must have finished before the next can start*. Put everything
that can be done in one go into one step, and only start a new one when you
genuinely need the last prompt to have run. Mark one done when you finish it,
whether or not it was sent to you; marking the last one finishes the plan. A
step that was **sent** is struck through rather than ticked, and sent is not
done — if you could not finish one, say so plainly.

A step arriving as a message *is* a request: the operator sent it
deliberately and is in this tab to read the answer.

**Write the details when you write the plan.** `bb roadmap info N "..."`:
which files, which functions, the approach. They travel with a step when it is
sent and appear in this block for the next session, which is the whole point —
that session should not start from a cold grep. When the work lands, trim the
item back to what is left: reasoning that is now a comment in the code or a
line in the README is stored twice, and this copy is the one nobody maintains.

The limits — a title, a step, how many steps, how many open items, how long
the details run — are enforced, and each refusal says what to do instead of
compressing the wording. You do not need them memorised.

**A plan can be corrected as well as followed.** If a step describes a file
that no longer exists or an approach that was abandoned, reword or drop it
rather than working around it, and say in your reply that you did. Say why in
the command when you drop something: nothing here can be undone, and that note
is all that survives it.

**When you are working a plan out, open a batch.** `bb roadmap begin`, edit as
much as you like, then `bb roadmap commit`. The changes land as you make them,
so the operator can watch, but the record is written once. It covers the whole
notebook, so bugs you file or close meanwhile are staged the same way. Read
the logs before you open one — your own changes are not in the history until
you commit. And do not leave one open: the panel holds its own Save while it
is, so commit or revert before you finish the reply, and if you are not about
to make several related changes, do not open one at all.

**A shelved item is parked, not yours to pick up.** It stays in your context so
you know it exists. Do not work on one unless they ask, and do not tidy it
away either.

**The operator decides how much of what you add lands on its own** — auto, ask
or deny, per tab. Under ask, `bb roadmap add` answers "held for approval as
R12" and the item is not on the list yet; you are told on a later turn what
they decided. Under deny it is refused with a sentence you can quote, so put
the item in your reply instead. The same three words apply to `bb bug add` and
`bb rules add`.

**If the list changes while you are working, you are told** — one line, with
your next prompt. It is not a request to drop what you are doing. If you are
about to act on the list, run `bb roadmap` first rather than trusting the copy
in your context, which was true when the conversation started; the same
command clears the refusal you get for editing an item you have not re-read.

Read the log narrowed, never whole: reach for `--find TEXT` before `--all`.


## The bug tracker

The notebook's third tab, and yours through `bb bug`. The roadmap is for
design work; a bug is a different record — severity, where it lives, how to
reproduce it, expected against actual, and a notes field the analysis
accumulates in. The open ones are appended to your prompt by number and
severity; `bb bug show B7` gives one in full. The B is the tracker's letter,
the way R is the roadmap's; the bare number works too. A report carries the
version it was filed in and, once closed, the version it was closed in —
the identity `bb version` prints, stamped for you — so "was this before or
after the fix" is a comparison rather than a guess.

```bash
bb bug                       # the open ones; `all` includes closed, `show N` one in full
bb bug add "..." --sev high --area "..." --repro "..."   # file what you find
bb bug note N "..."          # append what you learned — dated, never replacing
bb bug fix N "what fixed it" # close it, with the note that is the point
bb bug wontfix N "why"       # decided not to; `reopen N` if a fix did not take
bb bug na N "why"            # it was real and stopped applying — the feature went
bb bug rm N "why"            # only for a report that should never have existed
bb bug begin                 # the same notebook batch `bb roadmap begin` opens
bb bug history [-n N] [--since 7d] [--find TEXT]   # what changed, narrowed
```

`bb history [--find X] [--since 7d]` is one search across the notebook's
three logs — roadmap, bugs, and what the dashboard changed in the memories —
merged by time and tagged by source. Reach for it when the question is "when
did anything here mention X", which no single tab can answer.

**When you find a bug and it is out of scope for what you are on, file it** —
the same rule as the roadmap, applied to defects: a reply is read once, the
tracker is read at the start of every session after it. Fill in the fields
you would want on arrival: area and repro above all. When you learn something
about one you did not fix, `bb bug note` it — the tracker is where the next
session looks first. Filing is subject to the same setting as the roadmap:
under ask a report is held as B7 until the operator approves it, a note on
it meanwhile rides behind it, and `bb bug pending` lists what is waiting.

**Close bugs; do not delete them.** There are three ways to close one, and
the difference between them is what the next reader is told:

- `fix N "what fixed it"` — you fixed it. The note is the point.
- `wontfix N "why"` — it is real and a decision was made to leave it.
- `na N "why"` — it was real and stopped applying, because the feature it was
  about went away. Neither of the other two is true of it: nobody fixed it,
  and nobody decided to leave it.

A closed bug stays in the tracker, which is what stops the same report being
investigated twice.

**`rm` is only for a report that should never have existed** — you mis-filed
one, filed it twice, or filed it against the wrong project. That is the whole
list. Reaching for it because a bug is dealt with destroys the record that
makes the tracker worth keeping; if you are not correcting your own mistake,
one of the three closes above is the honest answer. Deleting says why in the
log, and that note is all that survives it.

## The test registry

The notebook's Tests view, and yours through `bb tests`. Two records that only
mean something together.

**What each test protects, written by hand.** A line saying what breaks if it
goes red, and a second saying what it actually exercises — which fixtures,
which stubs, what is real and what is faked. That second half is the one
nobody can recover from the code in a hurry, and it is what decides whether a
red run is a bug or a fixture.

**When you write or change a test, record it in the same change.** Same deal
as the roadmap: a description written later is a description nobody writes.
The order is run, ingest, describe — a test gets its key from the runner, so
there is nothing to describe until a run has reported it once. The run you
were going to do anyway is the one that mints it, and the new test shows up
on the drift report as the thing to write a line about.

```bash
bb tests run             run the project's tests, time them, record the run — the way to run them
bb tests                 where the suite's time goes, slowest first
bb tests show KEY        one test: what it protects, what it runs, its history
bb tests note KEY "what it protects" --how "fixtures, stubs, what is faked"
bb tests drift           what the runner reported that this list does not, and back
bb tests flagged         the ones sitting on a round timeout rather than working
bb tests projection      when a run should finish, from what the last one took
```

**`bb tests run` is how a session runs the tests.** It runs the project's
own test command, the one in its settings, with timing on, records the
durations, and says before it starts when it should finish, from what the
last run took. Wait for that, not for a guess: a run well past it is stuck,
not slow, and the process is the thing to look at. `bb tests ingest LOG`
records a run made some other way.

**Do not edit the tree while its tests are running.** A runner reads files
as it goes — a dev server serves them from disk per request, a test file is
loaded when its turn comes — so an edit mid-run makes the run test a mix of
before and after, and its verdict is about nothing. Stage the change, let
the run finish, then apply it and run again. One run at a time, for the
same reason.

**The timings are measured, never estimated.** Do not put a duration in by hand. A number somebody guessed is worse than no
number, because it reads exactly like one that was measured.

**A test is keyed on where the runner puts it**, `<file>#<ordinal>`, not on
its name — the names here are prose and they get reworded, and an entry that
died on a rename would be an entry nobody trusted. Ingest reconciles: a
reworded test keeps its description, a test inserted above one does not shift
anybody's, and what genuinely arrived or went is the drift report. **Read that
report** — a registry that has quietly stopped describing the code is worse
than no registry, and it is the failure this whole thing is built to catch.

**A flagged test is the cheapest thing in a suite to fix.** Anything landing
just above a round boundary — 30.0s, 10.0s, 5.0s — is waiting rather than
working: a fixed sleep, a polling interval, or a selector that matches nothing
and times out. The work is already done; only the waiting has to go. When the
wait IS the work — a real boot, a timeout being proved — say so once with
`bb tests accept KEY "why"` (or the checkbox on its row), and it stops being
flagged, with the reason kept beside it.

**When you add a test, time it before you hand it back.** A test does not
run alone — the runner runs a file, and the tests in it share one page and
one server — so run the file it is in with timing on (`bb dashboard test
FILE` in BuilderBot; the project's own runner pointed at the file
elsewhere), `bb tests ingest` the output, and read `bb tests flagged`. Your
new test on that list is waiting on a fixed sleep, a poll interval or a
selector that never matches: take the wait out and run the file again. Leave
it only when the time is the work — a real build, a real boot — and say so
with `bb tests accept KEY "why"`, so it stops being flagged and the next
reader does not chase it.

## Static analysis findings

If `/reports` exists, a scanner runs on the host and drops SARIF there.

```bash
bb findings        # this project's findings, repo-relative paths
bb findings --all  # every project the report covers
bb findings history   # what the scanner stopped and started saying here
```

The scanner may cover several repos in one report; `bb findings` shows only
this project's and tells you how many it held back. If a count looks wrong,
check that line before assuming findings are missing.

**An empty result is not a clean bill of health.** SARIF records findings, not
coverage, so "scanned and found nothing" and "never scanned" are byte-identical
in the report. If this project is absent, say that it does not appear in the
report — not that it passed.

Read it with `bb findings`, not by opening the SARIF — the raw file is mostly
metadata and will eat the context you need for the code.

**You cannot run a scan from here.** `/reports` is read-only and no scanner is
installed, deliberately. If findings look stale, say so and let the user re-run
it on the host; do not try to install a scanner to work around it.

Treat findings as claims to evaluate, not a queue to clear. Whether a `|safe`
is deliberate or a SHA1 is for dedup rather than security is a judgment about
intent — check the surrounding code and say what you concluded. Suppressing a
rule makes the report clean without making the code better, so propose that
only when the finding is genuinely a false positive, and say why.

## Git and credentials

- Commit identity is the account's own, set on their Profile tab, and it
  reaches this session as git's environment (`GIT_AUTHOR_*`,
  `GIT_COMMITTER_*`) — so two people on one project are two authors. No
  session, shell or `bb git` runs for an account that has none set, so a
  commit failing to find an author here is a fault to report, not one to
  fix with `user.name` / `user.email` yourself.
- SSH keys may be **shielded**: served by a root-owned agent so that pushes
  work but the key files are unreadable to you. `ssh-add -l` listing a key with
  no readable file in `~/.ssh` is the expected, healthy state — not a problem
  to fix. Do not try to read, copy, or regenerate keys.
- `gh` is authenticated only if a session-visible `GITHUB_PAT` is set, and it
  answers for GitHub and nothing else. If it is not set, say so rather than
  inventing another auth path. There is no container-wide git token: a
  project that needs one carries its own, set when it is cloned or from the
  chain on its row. A remote may be on any git host — GitHub, a self-hosted
  Gitea or Forgejo, Codeberg, GitLab, Bitbucket — so do not assume `gh`
  reaches this project's.
- **A session's token lasts twelve hours and renews itself while you work.**
  Every `bb` call and every prompt past its halfway mark brings back a fresh
  one, kept where `bb` looks, so a session in use never runs out. One idle
  for twelve hours does: if `bb` starts refusing with "this session's token
  expired", the fix is not a sign-in — ask the operator to open this
  session's tab in the dashboard, which mints a fresh one. Everything else
  keeps working meanwhile; the token is only how `bb` reaches the
  controller.
- **On a node, pushing is `bb git push`** (and `fetch`, `pull`, `ls-remote`).
  The tree is the shared projects share, so the controller runs git in it
  with the keys it holds, and no credential ever lives on a node. Plain
  `git push` there fails asking for a username: that is the rule, not a
  fault to work around. `bb status` says which machine this is.
- **What you may push is the project's git policy**, set on its Git view:
  `bb git policy` prints it. By default you may push the branch you work
  on and may not push to `main`; the controller refuses a push the policy
  denies, so read it before pushing rather than discovering it. Committing
  and merging locally are yours either way — the policy governs what
  reaches the remote.
- Never write credentials into this repository, including into test fixtures,
  `.env` files that are not gitignored, or CI config.

## CI runs on a node

The controller runs no Actions runner. Every runner lives on a node the
operator enrolled — the dashboard's Nodes tab installs one — and carries that
node's own name as a label, which is how a workflow chooses it. A workflow
labelled with this machine's name runs right here, beside you.

```yaml
runs-on: [self-hosted, bb-sandbox]
```

Four implications:

- The toolchain CI sees is the **node's**, the same one `bb build` and
  `bb test` use for this project. If a build works through `bb build` it
  should work in CI; if it needed a toolchain the node lacks, CI needs it too.
- A job stuck in *Waiting for a runner* while the runners show *Idle* is a
  label mismatch, not a broken runner. `bb ci-labels` lists every label the
  registry knows; compare the job's `Requested labels:` against it.
- `bb lint` refuses a `runs-on` naming a label no runner carries, so that
  mismatch is caught here instead of on GitHub.
- A CI job's console output is archived on the node that ran it, under its
  data store. `bb ci-log` reads the newest run — this machine's directly, and
  another node's fetched across; `--list` shows what is kept.

## Linting, versions and logs

Before pushing anything that touches shell scripts, Dockerfiles, workflows,
compose files or XML, run:

```bash
bb lint            # lints those files in the current repo, same tools as CI
```

It checks `runs-on` labels against the labels the nodes' runners actually
carry, so the "Waiting for a runner" mismatch is caught here instead of on
GitHub.
It does not run the project's own linters (eslint, ruff configs, gradle
checks) — those have their own configuration; use the project's documented
commands for them.

Check `bb status` for versions and `bb doctor` when something environmental
looks wrong — it diagnoses auth, connectivity and GPU state in one pass. Bare
`bb` lists everything it can do.

Timestamps you print are this machine's local time, not UTC. Worth stating
explicitly when you quote one.

`bb logs` reads the controller's own log — this boot, `-p` the one before it,
`--list` what is kept. Worth knowing when something broke across a restart of
the dashboard rather than of anything here.

<!-- BUILDERBOT:ENV:END -->

---

## About this project

<!-- Replace this section. Build/test/lint commands, architecture notes,
     conventions, anything a new contributor would need. -->

- **Build:**
- **Test:**
- **Lint:**
- **Conventions:**
