# Working inside BuilderBot

<!-- BUILDERBOT:ENV:BEGIN -->
<!-- BUILDERBOT:ENV:WINDOW 0.4 -->
<!-- Everything between these markers is generated from BuilderBot's shipped
     template and is safe to replace wholesale:
         bb claude-md            # is this copy current?
         bb claude-md --update   # refresh just this block
     Your project's own notes live BELOW the end marker and are never touched.
     Edits inside this block are lost on the next --update; put them below. -->

You are running inside **BuilderBot**, a long-lived container on an Unraid
server. It is a Claude Code workstation and the controller for one or more
nodes — the machines where builds, tests, CI and the Android emulator actually
run. This file describes the environment; it is not a description of the
project itself.

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
  container is right and the file is stale. Trust `bb doctor` and `bb status`
  over anything written here.

Do not create a `CLAUDE.md` anywhere one does not already exist — `--init` is
the user's decision, not a session's.

## What persists and what does not

This matters more than anything else here. The container is disposable and gets
recreated on every image update.

**Survives a container restart** — because it is on a mounted volume:

| Thing | Where |
|---|---|
| This project, including uncommitted work | `/workspace/<project>` — the projects share is mounted whole at `/workspace`, so every folder in it is here |
| Your session transcripts and memory files | `~/.claude/` |
| Claude Code login, shell history, AVDs | `~` (the home volume) |
| SDKs and toolchains — Android packages, Playwright browsers, Flutter/.NET/Swift | the package store at `/sdk`, symlinked into place. `bb sdk` lists and installs them |
| Gradle / npm / pip caches | `~/.gradle`, `~/.npm`, … |

**Does not survive** — anything written outside those paths:

- `/tmp`, `/var`, and the rest of the root filesystem
- `/opt` — but most of what looks like it lives there is a symlink onto the
  package store and *does* persist: the Android packages, the Playwright browsers,
  anything `bb sdk install` put there. What actually comes from the image is
  the bootstrap — `sdkmanager`, `adb`, the CLI tools
- System packages installed ad hoc with `apt-get install`
- Running processes, including the emulator and any dev server

So: **never `apt-get install` something and consider the problem solved.** It
will be gone after the next update. A tool a project needs is installed
through the package manager on its node (the Tools tab); the controller
carries what it needs in the image. Say what is missing rather than
installing it yourself.

Uncommitted work in this project is **not** at risk from a container restart.
It is still worth committing, but do not panic-commit on the theory that the
container is about to eat it.

## Stay in this directory

`/workspace` holds *other projects* as sibling directories — the whole projects
share is mounted there, so that is every folder in it, not a hand-picked few.
Your working directory is this project. Do not read from or write to sibling
projects, and do not go looking for context in them — if something seems to be
missing, ask.

A sibling directory holding a `.bbignore` file is not a project at all — it is
the container's own storage (the package store) or something the operator chose to
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

- **Playwright** — browsers live at `/opt/pw-browsers`, which is a symlink
  onto the package store (they are 1.3GB of download, so the image does not carry
  them); `PLAYWRIGHT_BROWSERS_PATH` still points there. Run headless. You do
  not need `playwright install` — the container installs them on the first
  boot of a fresh share, and `bb sdk install playwright` repairs them (if the
  operator removed them deliberately, boot leaves them out and says so) — and
  if a project pins a different version, launch with
  `executablePath: '/opt/pw-browsers/chromium'`
  (a stable symlink to the current Chromium). The image's Playwright is a global module: `require()`
  finds it from any directory via `NODE_PATH`; ESM `import` does not honor
  that, so use `createRequire(import.meta.url)('playwright')`.
- **`bb shot URL... [FILE|DIR]`** — headless screenshot(s) of any pages, for
  showing the user visual state. Takes `--full`, `--scale N`, `--wait MS`,
  `--resize W` for README-quality captures — a docs-screenshot script should
  boot the app and end with one `bb shot` line, not carry its own Playwright.
- **Screenshots** are the way to show the user visual state — save to a file
  and surface the path.

## Toolchains beyond the image

The image is a bootstrap, not a toolbox. The heavy toolchains — Flutter, the
.NET SDK, Swift, the Android emulator and its system images, the Playwright
browsers — live on a share outside it, so which of them exist on *this*
container is a runtime fact, not something to infer from this file:

```bash
bb sdk            # what is installed, where each one lives, and what is not
bb sdk --local    # ...on this container, when the answer above is a node's
```

**`bb sdk` answers for the store this project actually builds with.** With a
node, that is the node's — the same machine `bb build`, `bb test` and `bb emu`
go to — so what it lists is what a build here can use. Without one there is
nothing: packages are installed on nodes, never on the controller, and a
project with no node cannot compile. `bb nodes` says which node is this
project's. (`bb sdk --local` lists the controller's own store, which holds
only what its boot keeps for `bb shot`.)

`bb status` prints the same summary in two lines. Check before concluding a
tool is missing, and check before reaching for a system package manager —
the thing you want may be one `bb sdk install` away, or already installed
somewhere PATH does not look until the next shell.

If a project needs one that is not there, **say so and ask** — you cannot
install it yourself. `bb sdk install` refuses to run from a session and tells
you to hand the decision back: these are gigabytes on someone else's disk.
The operator does it from the dashboard's Tools tab (Additional packages),
where the checkboxes and the uninstall controls live, or by running the
command you offer them.

Installing one is not a reason to edit this file: `bb sdk` is the source of
truth, and it is accurate the moment something lands.

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

**When the project has a node, every `bb emu` verb runs there.** The node's
own emulator, images and GPU are used, the output streams back, and what a
verb writes — `bb emu shot` for a screenshot, `bb emu gfx PKG` for real
per-frame timings — comes back into `dist/`. `bb emu install FILE` sends an
APK from `dist/` along. From a session on the controller you cannot reach
that emulator with `adb`; the verbs are the way in. From a session **on the
node** — `bb status` says which this is — the verbs run right here and
`adb` reaches it directly. `bb emu create API` builds its AVD when the
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

With a GPU passed through, the container starts a headless X server for it at
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

## What you can build, and where

Compiling happens on the project's **node** — a machine the operator
enrolled, with its own toolchains — and never in this container. Which node
is a per-project setting, and a project may have none.

```bash
bb build            # the project's build command, on its node
bb test             # its test command, on its node
bb run -- CMD       # anything else there, from a snapshot of this tree
```

**A project with no node is a normal state, not a broken one.** You can read
every file, change any of them, run the linters and the project's own
non-compiling checks, commit and push. What you cannot do is produce a
binary: `bb build` refuses and says so rather than half-working.

When that happens there are exactly two honest answers, and the refusal
names whichever applies:

- **The project can push** — commit, push, and let CI build it. That is the
  fallback, and it is a real one: the workflow runs on a runner with the
  toolchain.
- **It cannot push** — then say plainly that the project cannot be built
  from here until the operator picks a node or grants push rights. Do not
  invent a local build, do not `apt-get` a compiler, and do not report
  success you did not observe.

**The same rule applies when the node is missing a toolchain.** A node that
carries no JDK cannot build an Android app, and `bb build` refuses before
queueing anything, naming the tool and the Tools tab. Again: CI if the
project can push, otherwise say so.

`bb nodes` names the project's node and what its census reports it carries.

## A phone, if one is connected

Only relevant when a phone is connected on this project's node.

A phone is driven from a **node**, not from this container: whichever node
has adb is where a handset is paired and connected, on the dashboard's Phone
tab, and a project's sessions reach the phone on the project's node and no
other. Pairing is once per node; if the phone is not showing as connected,
the answer is almost always Connect rather than Pair.

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
not yours to run root on — and a project with no node has nothing to ask.
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
and the short sha — rendered as `0.4.0-dev.390+e1615f5`, or as whatever
format the thing you are stamping demands. **Use `bb version --file` for the
artifact name** rather than inventing one; that is what makes two builds
tellable apart in the Artifacts tab.

A project with no `VERSION` file still answers, falling back to `git describe`.
Giving it one is `bb version init 0.1.0` — which the same policy governs, so
under the default `locked` it is the operator's, from the Artifacts tab. Do
not write the file by hand; that is the one path deliberately closed.

**The operator may ask you what it should start at.** Pressing *Ask Claude*
on that tab sends the question here, the way a roadmap step arrives. The
judgment is the whole of what they are asking for: read the code, the
roadmap and the changelog, decide how finished this actually is and what has
shipped, and say what you concluded and why. Then **propose, and ask** —
they came to negotiate, and a number applied on arrival skips the
conversation they wanted. Do not propose `1.0.0` unless they raise it.

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
bb changelog            # read it; --for DIR for a component's own
bb changelog unreleased # what is waiting for a bump, numbered
bb changelog edit 3 "…" # reword entry 3 rather than logging it twice
```

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
first, so the entry names all the commits that made it. Use your judgment: two lines about
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
paired phone (which replaces an existing copy in place, keeping its data), and
pushes an `.xpi` to it. Nothing auto-pushes: a push is a decision the operator
makes each time, so do not design around the extension on the handset staying
current — say when a rebuild is worth pushing instead.

## The dev instance, if this project has a compose file

The Artifacts tab may carry a **dev instance** row: the operator builds this
project's compose app and brings it up and down from there. **Those controls
are the operator's.** If a build or the instance's env needs changing, say so
and let them press the buttons; the env file lives outside the repo on
purpose.

The daemon those buttons drive is a **sandbox VM** — `DOCKER_HOST` names a
machine whose only job is running Docker, with no real containers on it and no
route to the server's. That daemon **is yours**: build, run and destroy
containers there as freely as you like. Being wrecked and reset is what it is
for. The one courtesy is to leave alone the compose projects the dashboard has
up, which are somebody else's instance while they are running.

It is a sandbox VM or it is nothing: `DOCKER_HOST` unset, or naming any other
kind of daemon, turns every dev-instance control off. Say so rather than
driving `docker` at whatever answers.

What is yours either way: keeping `docker-compose.yml` and `.env.example`
true. The rebuild flow reads `.env.example` to know when new settings need
filling in, so a new variable your code reads belongs there in the same
commit.

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

**Both of you write them, and each is marked with who did.** Yours are marked
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
one tab each. The roadmap is the shared list of design work, and both
you and the operator write it. (`bb todo` still works as an alias for `bb roadmap`, so a
conversation that started before the rename does not break mid-task; use
`bb roadmap`.)

```bash
bb roadmap                      # what is on it
bb roadmap add "..."            # put something on it
bb roadmap done N               # finished it — off the list, into the log
bb roadmap rm N ["why"]         # not doing it — same, and say why it went
bb roadmap shelve N             # parked: keep it, not now — the operator unshelves
bb roadmap mv N up|down         # move one up or down the list
bb roadmap edit N "..."         # reword one
bb roadmap info N [M] "..."     # attach the technical details to one, or step M
bb roadmap step add N "..."     # give one a step; step edit N M "...", step rm N M
bb roadmap step done N M        # you finished step M of N — ticked, and no longer offered
bb roadmap begin                # working one out: commit writes one record of it
bb roadmap commit               # ...or revert, which puts the notebook back
bb roadmap history [-n N] [--since 7d] [--find TEXT]   # what changed, narrowed
```

**The open items are already in your context.** They were appended to this
session's prompt when it started, so there is nothing to go and read at the
top of a conversation, and nothing to recite back — the operator can see the
list; they are looking at the same one.

Each carries a number — `R4` — and that number is the item's own, not its
position: it is what the operator sees on the row in the dashboard and what
`bb roadmap done R4` takes, and it survives the list being rearranged. Refer to
one by it rather than by counting down the list. New items go on the end, so
the numbers normally run down the page; a gap means something was removed and
an item out of sequence was moved by hand.

**The letter says which list.** A roadmap item is `R4`; a bug is `B4`; a
rule is named, not numbered. Write the letter whenever you name one — in a
reply, a commit message, a note — because `#4` on its own could be either
tab, or a pull request. Every verb takes the bare number too, so `bb roadmap
done 4` still works; `bb bug fix R4` is refused, and the refusal says which
tab R4 belongs to.

The half that needs saying is the writing.

**When you notice something worth doing and it is out of scope for what you
are on, put it on the list.** Not only in your reply. A reply is read once,
in a scroll of other text, at the end of a task the operator is already
finished thinking about; the list is read at the start of every conversation
after it. "I flagged that last week" is worth nothing if it went past in a
paragraph. This is the operator's own reason for the list existing:

> sometimes you mention things and I forget that you did

So: say it in the reply *and* add it. Items you add are marked as yours, so
the operator can see what you raised and sweep it if they disagree.

**The operator decides how much of what you add lands on its own.** Per
project and per tab — roadmap, bugs, rules — the setting is auto, ask or
deny, and it covers *creating* an entry only: what is already on a list you
may still tick, note and reword under any of them. Under **auto** an add
lands as it always has. Under **ask** it is held: `bb roadmap add` answers
"held for approval as R12", the item is not on the list yet, and the
operator approves or denies it on the notebook. Details or steps you add to
R12 meanwhile ride behind it and land after it; anything else on a held
item is refused, and `bb roadmap pending` lists what is waiting. You are
told on a later turn what they decided. Under **deny** the add is refused
with a sentence you can quote — put the item in your reply instead, and the
operator adds it if they agree. The same three words apply to `bb bug add`
and `bb rules add`.

**Tick things off as you finish them**, including items you did not add.
A list that only grows is one that stops being read.

Ticking one off **takes it off the list** — this list is read to find out what
is left, and something finished is not left. It goes into the history under
"done", where dropping it would have gone under "dropped", and there is no
undoing either: if it turns out not to have been finished, add it again and
say so. Only you tick things off. Nothing in the dashboard does it, because
only the session that did the work knows whether it is done.

**A group is one goal with an order to it, and its title is that goal.**
Group steps only when every one of them serves a single outcome — "the picker
works on a phone", not "four things I noticed". If the steps do not share a
goal they are separate items, and separate items can be sent in any order,
which is the whole reason to have both shapes.

Write the title as the goal in plain words, not as a summary of the work:
somebody reading only that line should know what is being aimed at and what
finishing it would look like. `bb roadmap add "make the picker usable on a
phone" --step "..." --step "..."`, not `bb roadmap add "picker: select width +
re-measure + regression pass"`. The steps carry the technical detail; the
title is the reason they exist. If you cannot write the title without listing
the steps, it is not one goal and should not be one group.

**Write the details when you write the plan.** `bb roadmap info N "..."` on an
item, `bb roadmap info N M "..."` on step M: which files, which functions, the
approach — the technical half the title should not carry. They show under a
fold on the row, travel with a step when the operator sends it, and appear in
this block for the next session, which is the point: the session that works
the step should not start from a cold grep because you already knew where the
work was.

**Steps are expensive — use as few as you can.** Each one is a message the
operator sends by hand from the dashboard, one at a time, waiting on each. So
a step is not a task, it is *a point at which the previous work must have
finished before the next can start*. Put everything that can be done in one
go into one step, using line breaks inside it to keep it readable, and only
start a new step when you genuinely need the last prompt to have run first —
a file that has to exist, a build that has to be green, an answer you need
before you can write the next instruction. Two steps that could have been one
cost somebody a round trip for nothing.

There are limits, and they are the design rather than an obstacle: a title or
a step is 500 characters over at most 12 lines, an item takes 12 steps, the
list holds 30 open items, and `info` takes 2000 characters over 40 lines. So
when a step will not fit, the answer is almost never to compress the wording —
it is that the technical half belongs in `bb roadmap info` and the step should
say what has to be true before the next one can start.

**Those are per-item caps, and the total is what actually costs.** The whole
list — every open item, its details, every step and every step's details — is
read into the prompt of every session that starts on this project, so a
paragraph written once is paid for again on every conversation afterwards. It
is easy to stay inside all of the limits above and still write a list nobody
can afford: one project's notebook reached 16KB and made its sessions
unstartable, because that is all `tmux new-session` accepts, and every session
before that had simply been paying for it quietly. The launcher no longer has
that ceiling, so the cost is the reason to be brief now, not the crash.

So write `info` as the technical half a session would otherwise have to grep
for — which files, which functions, what was decided and why — and not as a
record of the thinking that got there. **When the work lands, trim the item
back to what is left**: reasoning that is now a comment in the code, a section
in this file or a line in the README is being stored twice, and the copy in
the roadmap is the one nobody maintains.

A step may be several lines, and blank lines between them are kept. The
operator can build and rearrange a group from the dashboard too, so write the
steps in the order they have to happen and leave the arranging to them. The
order is enforced on sending: the first has to go before the second becomes
sendable, which is what separate items cannot promise — hand three of those
over backwards and the second lands on a tree the first was supposed to have
made.

A step that has been sent is struck through rather than removed, and can be
sent again — sent is not the same as done, and the difference is exactly the
case worth being able to see. So do not treat "you sent me this" as proof it
worked; if you cannot finish a step, say so plainly rather than quietly
leaving it struck through.

**When you finish a step, mark it.** `bb roadmap step done R4 2` is your mark
on step 2 of R4, distinct from sent: the panel draws it with a tick instead
of a number and stops offering it as the next thing to send, and the log says
a session finished it. Do this whether or not the step was sent to you — a
phase you were told to start in chat is the case it exists for — and do it
for the step you were sent as well, or the operator has only your reply to
go on. There is no undo: if it turns out not to have been finished, the
operator sends it again, which clears the mark and says so in the log. When
the last step is done, the item is done: `bb roadmap done R4` takes it off.
A line the operator dealt with themselves is dropped rather than marked,
because there is still no way to cross one off by hand.

**A plan can be corrected as well as followed.** If the design moves under
one — a step describes a file that no longer exists, or an approach that was
abandoned — reword or drop that step rather than working around it:

```bash
bb roadmap edit 4 "the new wording"
bb roadmap step edit 4 2 "...what step 2 should say now"
bb roadmap step rm 4 2          # and step add 4 "..." to put one on the end
```

Reordering too, when two steps turn out to be the wrong way round:
`bb roadmap step mv 4 3 up`, and `bb roadmap mv 4 up` for the item's own place in
the list. Both are covered by a batch, so `revert` puts them back.

Say in your reply that you did it, and why. Every change either of you makes
is written to a log with its time and the name of who made it — so a step you
dropped is recoverable from its own words, and there is no version of this
where quietly rewriting somebody's plan goes unnoticed. That is the point:
correct the list openly rather than leaving it describing work nobody is
going to do.

**You can be refused for writing over words you have not read.** `bb roadmap
edit`, `info`, `rm`, `done` and the step verbs check whether the list has
moved since you last read it, and stop rather than rewriting an item from the
copy in your context — which may be hours old, because it arrived when this
conversation started. There is no `--force`: run `bb roadmap`, which clears
it, and make the change against what it says now. Your own writes never count
against you, so a run of edits is not interrupted by itself.

**When you drop something, say why in the command**: `bb roadmap rm R4 "the
picker this described no longer exists"`. Nothing here can be undone, so that
note is the only thing between a dropped line and somebody adding it straight
back. It is kept with the entry and is searchable.

**When you are working a plan out, open a batch first.** `bb roadmap begin`,
then edit as much as you like, then `bb roadmap commit`. The changes land on the
list as you make them — the operator can watch, which is better than hiding
your work until you are happy — but the *record* is written once, at commit,
saying what changed rather than every step of getting there. Rewording the
same step four times before you are satisfied is one entry, not four, and a
log nobody can skim is a log nobody reads. `bb roadmap revert` puts the list back
as it was and writes nothing; it refuses if the operator has changed the list
since you opened the batch, because putting your copy back would undo their
work too.

**A batch covers the whole notebook, not just the roadmap.** Bugs you file,
note or close while one is open are staged the same way, and `bb bug begin`,
`commit` and `revert` are the same three commands reached from the other tab's
name. That is deliberate: a plan usually moves because of what the tracker now
says, and committing one while reverting the other would leave a roadmap
describing work against a tracker that never recorded why. Your memories are
not in it — those are files you write directly, so there is no write to
intercept and `revert` will not put one back.

**Read the logs before you open one.** While a batch is open your own changes
are not in `bb roadmap history` or `bb bug history` yet — that is the whole
point of it — so a session that opens a batch and then asks the log what it
just did gets a confusing answer. Do the reading first, then start editing.

**Do not leave one open.** While a batch is open the panel holds its own
Save — what is on the operator's screen was read before you started, and
replaying it over a list that has moved is how two writers lose each other's
work. Their typing is not blocked and yours is not either; only the
writing-back waits. That hold is the panel's own courtesy and not a lock:
nothing here serializes writers, and `bb` and a second session write straight
through it. So commit or revert before you finish the reply, and if
you are not about to make several related changes, do not open one at all.

**Read the log narrowed, never whole.** `bb roadmap history` gives the last 20;
`-n N` for more, `--all` for everything, `--since 7d` or `--since 2026-08-01`
for a window, `--find TEXT` to search the lines, their previous wordings and
the reasons things went. Reach for `--find` before `--all` — the whole log
costs more context than the one line you wanted from it.

**A shelved item is parked, not yours to pick up.** The operator shelves
something they mean to keep and do not want done now; it goes dark at the
bottom of the list and its steps go with it. It stays in your context so you
know it exists — do not work on one unless they ask, and do not tidy it away
either.

`bb roadmap shelve N` is there when something turns out to be blocked or waiting
on somebody: park it and say why in your reply. There is no unshelve for you.
Taking one off the shelf reverses a decision made for reasons you were not
told, so it is the operator's, and it is one tap in the panel.

If the list or these notes change while you are working, **you are told** —
one line, naming which of the two moved, arriving with the next prompt you
are given. It costs the operator nothing and interrupts nothing, so it is not
something they have to remember to do. Read it when it is relevant and carry
on: a change to the list is not a request to drop what you are doing.

Two things follow from *when* it arrives. It rides on your next turn, so a
change made while you are mid-task reaches you at the end of it rather than
during — and if you are about to act on the list, re-read it with `bb roadmap`
rather than trusting the copy in your context, which was true when the
conversation started. And a change you make yourself is never announced back
to you.

There is one Save in the panel and it says nothing to you directly — the line
above is the whole of how a change reaches you. The other way anything lands
is a step being **sent**, which is a message the operator wrote deliberately;
what moved in the notebook rides along on that rather than costing a second
one.

A step arriving as a message *is* a request: the operator sent it deliberately,
and the panel closed and put them in this tab to read the answer. Sometimes it
carries a note that the list changed as well — that half is context, the step
is the ask.

Keep it short and keep it real. Thirty open items is the hard ceiling, and it
is a working list rather than an issue tracker: one line, plainly worded, no
duplicates of something already there. Anything that turns out to be a durable
rule rather than a task belongs somewhere stronger — a note in this file, a
comment where the code is, or a test that fails when it regresses — and should
come off the list once it lands there.

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
- `gh` is authenticated only if a session-visible `GITHUB_PAT` is set. If it is
  not, say so rather than inventing another auth path. There is no
  container-wide git token: a project that needs one carries its own, set in
  the dashboard's clone dialog.
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
node's own name as a label, which is how a workflow chooses it. A session on
the node is on the same machine as its runner; one on the controller is not.
`bb status` says which this is.

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
- A CI job's console output is archived on the node, under its data store.
  `bb ci-log` reads the newest run — right there from a session on the node,
  fetched across from one on the controller; `--list` shows what is kept.

## Toolchain already present

Do not install these. On the controller they are in the image:

`node 22` · `npm`/`yarn`/`pnpm` · `python 3.12` + `uv`/`pipx` ·
`playwright` (chromium/firefox/webkit) · `git`/`git-lfs`/`gh` ·
`ripgrep`/`fd`/`fzf`/`jq`/`yq` · `build-essential`/`cmake` · `ffmpeg`/`imagemagick` ·
`shellcheck`/`hadolint`/`actionlint`/`ruff` · `lsof`/`strace`/`tree` ·
`mise` for per-project tool pinning

No JDK and no Android SDK on the controller: compiling happens on a node.
There the toolchain is the packages store, and `bb sdk` is the list: the
JDK, the Android SDK, Playwright's browsers with their module, and the lint
tools are all recipes there, installed from the dashboard's Tools tab with
that node picked. One `bb lint` check skipping, or `bb shot` failing to
find its module, means a recipe is not installed yet — say which, and let
the operator install it; never `apt-get` around it.

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

The container clock is set from the host's `TZ`, so timestamps you print are
local time, not UTC. Worth stating explicitly when you quote one.

The container's own log rotates on every start, which is worth knowing when
something broke across a restart:

```bash
bb logs            # this boot
bb logs -p         # the previous boot
bb logs --list     # what is kept
```

<!-- BUILDERBOT:ENV:END -->

---

## About this project

This repository **is** BuilderBot — the source of the container you are running
inside. `scripts/` becomes `/opt/builderbot/scripts`, `config/templates/` ships
the CLAUDE.md template `bb claude-md` compares projects against, and the
Dockerfile is the whole product. There is no application here; the deliverable
is the environment.

The consequence you hit first: **editing a file here does not change the
running container.** `bb` on your PATH is `/opt/builderbot/scripts/bb` from the
image, not `scripts/bb` in this tree. `bash scripts/bb <cmd>` dry-runs the
checkout properly — it sources the library next to itself, so a new helper in
`lib/common.sh` is there — but the startup hooks and the dashboard still source
`/opt` by absolute path, and nothing is really live until CI builds a new image
and Unraid updates the container.

The dashboard header carries the short commit of the image the box is
running, beside the uptime, and `bb status` prints the same line first.

The version of that question which spans days — *what was the box on when I
saw that?* — is `bb catchup`. The entrypoint appends a line to
`/config/image-log.tsv` every time the stamp changes, so the images this
container has actually run are a list rather than a guess, and the same
command prints recent commits with the first line of their bodies, what moved
in the notebook, and the builds this box archived. Reach for it when the
operator opens with *"it finally built"*; it exists because reconstructing that
by hand cost four commands and still could not see the failed builds.

- **Build:** the image, and nothing else. `.github/workflows/build-image.yml`
  builds and pushes `ghcr.io/stencil-projects/builderbot` on pushes to `main`
  that touch the image's inputs (Dockerfile, `scripts/`, `config/`) — plus a
  weekly cron rebuild, so the base image stays fresh. Claude Code is not in
  the image — it is installed into the home volume at first boot. It runs on `ubuntu-latest`, deliberately: hosted minutes cost more,
  but building the image on the box that runs the image is circular — a bad
  image would take down the runner that has to build the fix. **A pull request
  does not build it** — that used to be two hosted builds for one answer, the
  second of which is the only one that ships — so a change that breaks the
  Dockerfile fails on `main` rather than before the merge. Nothing broken is
  served when it does: `:latest` simply does not move. Locally,
  `docker compose build` needs the host Docker socket, which is not mounted by
  default; `bb doctor` says whether it is.
- **Test:** the dashboard has a browser suite; the rest is verified by the lint
  workflow plus the manual **runner smoke test** (Actions → Run workflow) that
  proves this runner picks up jobs, carries the toolchain it advertises, and
  cannot see the shielded PAT. What you *can* run here, with no daemon:

  ```bash
  bb lint                       # shellcheck / hadolint / actionlint / compose / XML — same as CI
  bb tests run                  # the Playwright suite, timed and recorded; bb dashboard test [cards] for one file
  python3 -m py_compile scripts/dashboard/server.py
  ```

  The dashboard suite runs the checkout's `server.py` on a spare port with a
  scratch state dir, fake projects and a **private tmux server** — it cannot
  touch the live dashboard, and its own `dashboard tests` workflow runs it on
  this runner for a PR that changes `scripts/dashboard/`. That is a separate
  workflow from `lint` on purpose: the suite is timing-sensitive and this
  runner shares its box with everything else, so it goes red for reasons that
  are not the code's — and while it was a step in the lint job it took the
  linters' verdict with it. Do not read a red `dashboard tests` as a
  regression without checking `bb ci-log`; see bug #19.
  `surface.mjs` holds the page's top-level names and compares both ways:
  MISSING means one fell into a nested scope, NEW means a global appeared.
  The pattern in `lib.mjs` (real touch via CDP, dialogs recorded, console
  errors collected) is the one to follow. `BB_TEST_TIMING=1` prefixes every
  result with the seconds since the last one; feed that output to `bb tests
  ingest` and the notebook's Tests tab keeps the numbers. The house rule
  `tests` carries the discipline: one run at a time, no edits under the
  dashboard during one, kill by pid.
  If the *installed* `bb` predates a subcommand, `bash scripts/bb <cmd>` runs
  the repo copy — and `bb lint` prints `[skip]` for any tool the running image
  does not carry yet, rather than passing by omission. The dashboard's server
  resolves `bb` as the copy beside it, so `bb dashboard dev` exercises the
  checkout's subcommands too.

- **Seeing a change without a rebuild:** `bb drift` lists what this checkout
  has changed that the running container is not serving. For the dashboard
  specifically, `bb dashboard dev` restarts the live dashboard from
  `./scripts/dashboard` (same port and credential; lasts until the container
  restarts; `--off` reverts) — so a dashboard change can be looked at in the
  browser without a 40-minute image build. `bb shot URL... [FILE|DIR]` takes
  headless screenshots to show the operator; it reads `DASHBOARD_AUTH` from
  the environment for the dashboard's own pages. `tools/readme-shots.sh`
  regenerates the README's screenshots from a staged instance.

- **Lint:** CI runs shellcheck, hadolint, actionlint, compose validation and
  XML well-formedness on a node's runner; `bb lint` runs the same set here,
  and the house rule `lint` runs it as its check before a session hands
  back. **When it fails, `bb ci-log` is the first place to look** — the runner keeps
  no console output, so the workflow tees each check into
  `/config/ci-logs/<repo>/` and that command reads it. `--list` shows the runs
  kept with their results. Without it the only local evidence is
  `/workspace/_work/_diag`, which names the failing step and nothing it said;
  that cost a round trip through the operator once already.
  It runs **on the pull request and nowhere else**. A `pull_request` build
  checks out `refs/pull/N/merge` — this branch already merged into main — so
  it is testing the tree the merge button is about to produce, and re-running
  on the push that merging creates would say the same thing twice, after the
  decision instead of before it. A push straight to main is therefore
  unlinted, which is fine because work lands through a PR.
  `.hadolint.yaml` holds the Dockerfile ignores; `.github/actionlint.yaml` is
  generated by `bb ci-labels --write`. The shellcheck file list is derived
  from shebangs, including a shell heredoc inside another script
  (`scripts/lib/embedded-shell.py`), so a finding may name the extracted copy
  (`provision-linux.sh-BBSANDBOX`).
- **Conventions** live in the house rules on the Briefing tab (`bb rules`);
  what follows is the layout they refer to.
  - The dashboard is deliberately dependency-free: `server.py` is stdlib-only,
    `index.html` is vanilla JS and CSS with one classic `tab-*.js` script per
    document tab beside it. No framework, no build step.
  - **The dashboard's design language is `docs/design-language.md`**, held
    by the house rule `design`, which names it and runs `test/uniform.mjs`
    as its check. A new tab kind declares `multi` (a notebook is per
    project; everything else is one window onto one thing), `live`
    ("always" for a kind rendering from `state`, a revision function for one
    whose data arrives on its own schedule), and `open` for whatever its
    first draw has to fetch.
  - Anything the web UI can execute is a table lookup (`MACROS`, `TMUX_KEYS`,
    `TMUX_LITERALS`, `PACKAGES`) rather than a command string, and `bb-tty` validates its one
    URL argument against directories that actually exist. New surface keeps that
    shape — the terminal is one port over for anything else.
  - A setting that has to be in the environment lands in five places:
    `.env.example`, `docker-compose.yml`, `unraid/builderbot.xml`, the
    configuration reference in `README.md`, and `docs/unraid.md` when it
    needs host-side setup. The README is the documentation surface and is
    expected to move with behavior.
  - The environment block every *other* project gets comes from
    `config/templates/project-CLAUDE.md`. That file is the source of truth;
    this repo's own copy above the end marker is just its output, so edit the
    template and let `bb claude-md --update` propagate it.
  - The weekly Monday build is uncached by design and is always a full pull;
    a manual dispatch is cached unless its `no_cache` box is ticked.

`README.md` holds the full configuration reference and a file-by-file layout;
`docs/unraid.md` is the host-side walkthrough.
