# Working inside BuilderBot

<!-- BUILDERBOT:ENV:BEGIN -->
<!-- Everything between these markers is generated from BuilderBot's shipped
     template and is safe to replace wholesale:
         bb claude-md            # is this copy current?
         bb claude-md --update   # refresh just this block
     Your project's own notes live BELOW the end marker and are never touched.
     Edits inside this block are lost on the next --update; put them below. -->

You are running inside **BuilderBot**, a long-lived container on an Unraid
server. It is a Claude Code workstation, a self-hosted GitHub Actions runner, a
Playwright browser lab and an Android build box. This file describes the
environment; it is not a description of the project itself.

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
| SDKs and toolchains — Android packages, Playwright browsers, Flutter/.NET/Swift | the SDK share at `/sdk`, symlinked into place. `bb sdk` lists and installs them |
| Gradle / npm / pip caches | `~/.gradle`, `~/.npm`, … |

**Does not survive** — anything written outside those paths:

- `/tmp`, `/var`, and the rest of the root filesystem
- `/opt` — but most of what looks like it lives there is a symlink onto the
  SDK share and *does* persist: the Android packages, the Playwright browsers,
  anything `bb sdk install` put there. What actually comes from the image is
  the bootstrap — `sdkmanager`, `adb`, the CLI tools
- System packages installed ad hoc with `apt-get install`
- Running processes, including the emulator and any dev server

So: **never `apt-get install` something and consider the problem solved.** It
will be gone after the next update. Durable extras belong in the container's
`EXTRA_APT_PACKAGES` / `EXTRA_NPM_PACKAGES` / `EXTRA_PIPX_PACKAGES` variables,
or in a startup hook in `/config/startup.d/`. Mention it to the user rather
than trying to edit those yourself — they live in the Unraid template.

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
the container's own storage (the SDK share) or something the operator chose to
hide. Leave those alone too.

If this session was started from the dashboard, that is also enforced: the file
tools — `Read`, `Edit`, `Write` and `NotebookEdit` — are denied every sibling
path and the runner's `_work` tree, via a settings file passed on the command
line. One of them coming back denied for a path outside this project is that
rule, working as intended — not a bug to route around with Bash.

Bash is **not** covered by it, and that is worth knowing rather than
discovering: `cat ../other-project/src/main.kt` works. The settings file is a
guardrail against wandering into the wrong tree by mistake, not a sandbox. The
rule above is the actual boundary; the file tools just make it harder to cross
by accident.

## There is no display

Everything is headless: no window manager, no monitor, nothing to show a GUI
on. Run every tool in its headless mode and show the user pixels by saving a
screenshot to a file.

There may be an X server on `:0` all the same, and it is not an exception to
any of that. When a GPU is passed through, the container starts a headless
Xorg at boot for one reason: NVIDIA's EGL will not hand out a display without
one, and without EGL the Android emulator cannot use the card. It has no
window manager, no monitor and one intended client. Do not read `$DISPLAY`
being set as permission to open a window on it.

- **Playwright** — browsers live at `/opt/pw-browsers`, which is a symlink
  onto the SDK share (they are 1.3GB of download, so the image does not carry
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
```

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

Which API levels exist is set by `ANDROID_SYSTEM_IMAGES` on the container. Run
`bb emu list` before assuming a version is available; if the one you need is
missing, say so rather than trying to install it — a runtime `sdkmanager`
install works but the user should decide to spend the disk.

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

## A phone, if one is connected

Only relevant when the operator has one paired to the dashboard's Phone card.

**You cannot reach it directly, and that is deliberate.** The handset is kept
on an adb server of its own, so `adb devices` here shows the emulator and
nothing else. Asking for the phone goes through the operator:

```bash
bb phone                                    # what is connected, what is waiting
bb phone run --why "..." -- shell getprop ro.build.version.release
```

That puts your reason and the exact command on the card and waits. On **Allow**
the dashboard runs it and hands you the output; on **Deny** you are told no.
The reason is required — the operator is being asked about a command they did
not write, and without a sentence saying what it is for, allowing it is a
guess. Write the sentence you would want to read.

It waits five minutes and then gives up, so do not open one and wander off.
And do not go looking for the port the phone is on: reaching around this is
possible, in the way most things in a container are possible, and it is the
one thing here that touches hardware the operator is holding.

## The roadmap

Every project has a notebook in the dashboard — memory, roadmap, bugs, one
tab each. The roadmap is the shared list of design work, and both you and the
operator write it. (`bb todo` still works as an alias for `bb roadmap`, so a
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
bb roadmap begin                # working one out: commit writes one record of it
bb roadmap commit               # ...or revert, which puts the notebook back
bb roadmap history [-n N] [--since 7d] [--find TEXT]   # what changed, narrowed
```

**The open items are already in your context.** They were appended to this
session's prompt when it started, so there is nothing to go and read at the
top of a conversation, and nothing to recite back — the operator can see the
list; they are looking at the same one.

Each carries a number — `#4` — and that number is the item's own, not its
position: it is what the operator sees on the row in the dashboard and what
`bb roadmap done 4` takes, and it survives the list being rearranged. Refer to
one by it rather than by counting down the list. New items go on the end, so
the numbers normally run down the page; a gap means something was removed and
an item out of sequence was moved by hand.

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
leaving it struck through. Struck means sent and nothing else: there is no
way to cross a line off by hand, so a line the operator dealt with themselves
is dropped rather than marked.

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

**When you drop something, say why in the command**: `bb roadmap rm 4 "the
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

**Do not leave one open.** While a batch is open the operator's Save in the
panel is held — what is on their screen was read before you started, and
saving over a list that has moved underneath is how two writers lose each
other's work. Their typing is not blocked and yours is not either; only the
writing-back waits. So commit or revert before you finish the reply, and if
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

If the list or these notes change while you are working, you may be told in
one line, which names which of the two moved. Read them when it is relevant
and carry on — a change to the list is not a request to drop what you are
doing. That line costs the operator a
message, so it is sent only when they press **Save & tell the session** —
there is a plain Save beside it that changes things and says nothing. So do
not expect to hear about every change, and re-read with `bb roadmap` if what you
are about to do depends on it.

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
severity; `bb bug show <n>` gives one in full.

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
session looks first.

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

- Commit identity is already configured from the container's environment. Do
  not set `user.name` / `user.email` per-repo.
- SSH keys may be **shielded**: served by a root-owned agent so that pushes
  work but the key files are unreadable to you. `ssh-add -l` listing a key with
  no readable file in `~/.ssh` is the expected, healthy state — not a problem
  to fix. Do not try to read, copy, or regenerate keys.
- `gh` may be authenticated via `GIT_PAT` for API calls. If it is not, say so
  rather than inventing another auth path.
- Never write credentials into this repository, including into test fixtures,
  `.env` files that are not gitignored, or CI config.

## CI runs on this same box

The self-hosted runner executes jobs in this container, under
`/workspace/_work`. It is registered at the **organization** level, so it serves
every repo in the org, not just this one. It carries the labels
`builderbot,self-hosted,linux,x64,unraid`, and a workflow matches only if every
label in its `runs-on` is one the runner has. Four implications:

- The toolchain CI sees is the toolchain you see. If a build works here it
  should work in CI, and if you needed an undocumented step, CI needs it too.
- CI jobs and your session share CPU, RAM and disk. A heavy build while the
  emulator is running can starve both — stop the emulator before pushing.
- A job stuck in *Waiting for a runner* while the runner shows *Idle* is a
  label mismatch, not a broken runner. Compare the job's `Requested labels:`
  against the list above.
- `Runner connect error: Error: Conflict` with *A session for this runner
  already exists* means something else is holding this runner's name — usually
  a listener left behind by a half-finished restart. It clears when GitHub
  expires the old session. `bb runner status` says so explicitly; do not
  re-register to "fix" it, that is what caused it.
- A push to a *different* repo in the org can be building on this same box
  right now. If something is inexplicably slow, that is a candidate.

## Toolchain already present

Do not install these; they are in the image.

`node 22` · `npm`/`yarn`/`pnpm` · `python 3.12` + `uv`/`pipx` · `jdk 21` ·
`android sdk` (build-tools, platform-tools, `bundletool`; platforms and system
images per `ANDROID_SYSTEM_IMAGES`) ·
`playwright` (chromium/firefox/webkit) · `git`/`git-lfs`/`gh` ·
`ripgrep`/`fd`/`fzf`/`jq`/`yq` · `build-essential`/`cmake` · `ffmpeg`/`imagemagick` ·
`shellcheck`/`hadolint`/`actionlint`/`ruff` · `lsof`/`strace`/`tree` ·
`mise` for per-project tool pinning

Before pushing anything that touches shell scripts, Dockerfiles, workflows,
compose files or XML, run:

```bash
bb lint            # lints those files in the current repo, same tools as CI
```

It checks `runs-on` labels against the labels this runner actually carries, so
the "Waiting for a runner" label mismatch is caught here instead of on GitHub.
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

The corollary is a trap worth naming, because a session has already fallen into
it: when a fix is merged and the operator says the thing is still broken, the
first question is **which build their container is on**, not whether the fix was
wrong. An Unraid container keeps serving whatever it last pulled — an image
published twenty minutes ago is not on the box until somebody presses update —
so a screenshot taken after a merge is not evidence about the merge. Three
speculative fixes went out one afternoon on exactly that mistake, each shipped
against a screenshot of the build before it. The dashboard header now carries
the short commit beside the uptime (`bb status` prints the same line first), so
the question is a glance rather than an inference: check it before concluding
anything from a report of behavior you thought you had already changed.

- **Build:** the image, and nothing else. `.github/workflows/build-image.yml`
  builds and pushes `ghcr.io/stencil-projects/builderbot` on pushes to `main`
  that touch the image's inputs (Dockerfile, `scripts/`, `config/`) — plus a
  weekly cron rebuild, so the base image, Claude Code and the runner stay
  fresh. It runs on `ubuntu-latest`, deliberately: hosted minutes cost more,
  but building the image on the box that runs the image is circular — a bad
  image would take down the runner that has to build the fix. Locally,
  `docker compose build` needs the host Docker socket, which is not mounted by
  default; `bb doctor` says whether it is.
- **Test:** the dashboard has a browser suite; the rest is verified by the lint
  workflow plus the manual **runner smoke test** (Actions → Run workflow) that
  proves this runner picks up jobs, carries the toolchain it advertises, and
  cannot see the shielded PAT. What you *can* run here, with no daemon:

  ```bash
  bb lint                       # shellcheck / hadolint / actionlint / compose / XML — same as CI
  bb dashboard test [cards]     # Playwright suite in scripts/dashboard/test/, isolated (see below)
  python3 -m py_compile scripts/dashboard/server.py
  ```

  The dashboard suite runs the checkout's `server.py` on a spare port with a
  scratch state dir, fake projects and a **private tmux server** — it cannot
  touch the live dashboard, and CI runs it on this runner for any push that
  changes `scripts/dashboard/`. **Add to it when you change the dashboard**;
  the pattern in `lib.mjs` (real touch via CDP, dialogs recorded, console
  errors collected) is the one to follow. Never write ad-hoc harnesses that
  create tmux sessions: inside a tmux session the client ignores
  `TMUX_TMPDIR`, and a throwaway session lands on — or a cleanup kills — the
  real server. The harness unsets `TMUX` and verifies its socket first.

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

- **Lint:** CI runs shellcheck, hadolint and actionlint — on *this* runner,
  where minutes are free and the image already carries the tools (the job
  fetches any that are missing, so it stays green on a container whose image
  predates a newly added tool); `bb lint` runs the same three (plus compose
  validation and XML well-formedness) in-container.
  **When it fails, `bb ci-log` is the first place to look** — the runner keeps
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
  The shared configs are the contract: `.hadolint.yaml` holds the Dockerfile
  ignores (DL3008/DL3013/DL3016 — a rolling dev image deliberately tracks the
  newest packages — and SC1091), `.github/actionlint.yaml` declares the labels
  this runner carries so a bad `runs-on` fails the lint instead of stranding a
  job in *Waiting for a runner*. Keep both files in step with runner.sh's
  `RUNNER_LABELS` and the CI jobs; a rule suppressed in only one place means
  CI and `bb lint` disagree, which is worse than either answer. The shellcheck
  file list is derived from shebangs, not filenames, so a new script is covered
  the moment it exists — do not replace that with a name list.
- **Credentials here are what they are.** The operator uses SSH deploy keys
  and opens PRs from their own desktop; `GIT_PAT` is unset on purpose, not by
  oversight, so `gh` API calls will not work and a session should not keep
  suggesting a token to fix that. Push the branch, print the PR link, move on.
  If reading a CI run's log would help, say what you would look for and let
  the operator fetch it.
- **Conventions:**
  - Bash: `#!/usr/bin/env bash`, `set -euo pipefail`, helpers and `log`/`warn`/
    `die` from `lib/common.sh` rather than bare `echo`.
  - Every script opens with a header comment saying what it is for, and inline
    comments carry the *why* — usually the failure that motivated the code.
    That density is the house style, not decoration; match it.
  - The dashboard is deliberately dependency-free: `server.py` is stdlib-only,
    `index.html` is one file of vanilla JS and CSS. No framework, no build step.
  - Anything the web UI can execute is a table lookup (`MACROS`, `TMUX_KEYS`,
    `TMUX_LITERALS`, `PACKAGES`) rather than a command string, and `bb-tty` validates its one
    URL argument against directories that actually exist. New surface keeps that
    shape — the terminal is one port over for anything else.
  - A new setting lands in five places: `.env.example`, `docker-compose.yml`,
    `unraid/builderbot.xml`, the configuration reference in `README.md`, and
    `docs/unraid.md` when it needs host-side setup. A setting that stops being
    read gets removed from all five in the same change — `DASHBOARD_TTYD_PUBLIC_PORT`
    outlived its code in three files. The README is the
    documentation surface and is expected to move with behavior.
  - The environment block every *other* project gets comes from
    `config/templates/project-CLAUDE.md`. That file is the source of truth;
    this repo's own copy above the end marker is just its output, so edit the
    template and let `bb claude-md --update` propagate it.
  - Persistence is the recurring design constraint: `/opt` is discarded on every
    image update, the home, `/config` and SDK volumes are not. New state has to
    pick a side, and the comment should say which and why. Anything large and
    merely *downloadable* belongs on the SDK share via `bb sdk`, never in the
    image — that is what keeps a weekly rebuild from re-shipping gigabytes.
  - Layer order is a cost. Builds seed from the previous `:latest`, so a
    Dockerfile change invalidates every layer *below* it — and the host then
    re-downloads all of them. A runtime-only `ENV`/`ARG` belongs at the **end**
    of the Dockerfile, not in the top block, unless a build step needs it;
    two env vars added to the top block once turned a two-line change into a
    full multi-gigabyte pull. The weekly Monday build is uncached by design and
    is always a full pull.
  - Secrets never reach a log unredacted — the entrypoint builds
    `/run/builderbot/redact.sed` from both token shapes and literal values, and
    everything the container prints goes through it.
  - Commits are sentence-case, American-spelled, and describe the change rather
    than label it ("Minimize a tab, and let the terminals outlive the
    container"). No conventional-commit prefixes. Work lands on a branch and
    merges through a PR.

`README.md` holds the full configuration reference and a file-by-file layout;
`docs/unraid.md` is the host-side walkthrough.
