# Design decisions

Why it is this way: each paragraph here was lifted out of the section of [how-it-works.md](how-it-works.md) it is headed with, and keeps its dates, bug numbers and reasons.

## The toolchain store lives outside the image

The reason is arithmetic. `/opt` is discarded and rebuilt on every image
update, and the update is weekly, so a toolchain baked into the image is
re-downloaded forever: the Android emulator alone is 800MB, a system image
about 2GB. On the share they are downloaded once and the update walks past
them. Map no share and everything falls back to the home volume, which also
persists, but mixes 30GB of system images in with your shell history.

**A row says what it is doing, and not how far along it is.** `installing`
with a ticking ellipsis for the whole of an install, `removing` for a removal.
There was a percentage and a bar here, scraped from whatever each recipe
printed, and it was retired: every one of them meters differently and several
mislead by accident. sdkmanager counts a single fraction across a whole
operation, changes the label part way through, and parks it in the fifties for
the minutes it spends writing a system image. `playwright install` fetches five
bundles and meters each from zero. rustup prints no percentages at all down a
pipe. A row relaying any of that faithfully still read as a bar that had
broken, so the honest answer is the one that does not pretend to a
denominator. The full output of every job goes to the log under the buttons,
which is where to look when "it is working" is not enough.

Whether a newer one exists is a network round trip to a different upstream per
toolchain, so that one is a slow background errand rather than something the
poll does: **once a week**, counted from when a check last actually happened
rather than from when the container came up. A restart used to mean a full
round of upstream requests three minutes later, so an afternoon of image
updates was an afternoon of asking the internet for answers that had not
moved. **Check for updates** asks on demand, which is what somebody presses
when they want to know now, and editing the catalog forces one: the stored
answers describe recipes, and a changed recipe has no answer yet.

Either way the answers are what the rows show. A check answers for the rows
that are *not* installed too: the version there is what Install would fetch,
plainly rather than in amber, since nothing about it is news. What a check
found is kept on the state volume and dated on the page.

**Update checking is a question, not a background service.** Each answer costs
a network round trip to a different upstream: the Flutter branch head, the
.NET installer's own dry run, Swift's release redirect, the browser revisions
Playwright's module wants, sdkmanager's update table, so nothing is checked
until `bb toolchains check` or the tab's **Check for updates** asks. An unchecked
row says nothing rather than implying it is current. Updates then run through
each toolchain's own mechanism rather than a delete-and-reinstall: Flutter
moves to the branch head, .NET installs the current LTS beside what is there,
sdkmanager updates its packages, and Swift and the browsers fetch the version
they now want.

**Moving the share later is a host-side job.** The container knows one
location (whatever `/sdk` is mapped to), so relocating that directory on the
server and re-pointing the mapping is invisible from inside: stop the
container, move the folder, start it again. There is deliberately no command
for it. (Toolchains left on the home volume from an older image keep working
where they are: the startup wiring points at whichever location actually
holds them, and says so.)

**What stays in the image, and why.** Anything apt installs (the JDK,
ffmpeg, imagemagick, build-essential) integrates with the system and cannot
live on a share. So do the small CLI tools `bb lint` promises: shellcheck,
hadolint, actionlint, and the Android bootstrap, `sdkmanager` and `adb`,
which is what installs everything else. Playwright's *module* and its system
libraries stay; only the browser bundles move. The Actions runner is not in
the image at all any more: every runner lives on a node, installed from the
Nodes tab, so the controller carries neither the runner nor the toolchains a
job needs.

## Multiple Android versions

**That server is watched, three times over.** It has died hours into a boot
with nothing in its log: no error, no signal, a clean startup and then
silence, and what made that expensive was the silence rather than the death:
the emulator went on working, on software, and every timing conclusion drawn
afterwards was wrong. So it is restarted up to three times with a backoff
and then **stopped, and said**. An unbounded respawn against a card the host
has taken back would be worse than the silence it replaces, so the card is
checked before each attempt: if `nvidia-smi` stops answering, the watch ends
there and records that instead. Either way `bb emu gpu` and `bb doctor` print
what happened, which is what turns a silent drop to software into a stated one.

## The notebook

It exists because nothing else on this box can hold that. `gh` is
unauthenticated here on purpose, so GitHub Issues are unreachable from inside
the container, and until this, something noticed mid-task and left undone
lived in the conversation and died with it.

That is deliberately the opposite of the panel's rule, where unsaved work is
per-tab and cannot cross. The two models are answering different questions. In
the panel the thing being edited is on screen and Save is the commit, so each
tab holds its own; for a session the file is the only way anyone can see what
it is doing, so the work lands as it happens and only the *record* waits.

**Edits are written immediately, and a running session is told by itself.** A
phone that dies half way through tidying a list must not lose it, so the write
does not wait for anything. The telling used to: every telling types a line
into the session's input box, which spends a turn and lands mid-task, so it
had to be a button somebody remembered to press.

It is not a button any more. The `UserPromptSubmit` hook every session runs
under carries the news back for free: a hook's stdout is added to the turn as
context, so the next prompt the session is given arrives with one line saying
what moved. Nothing is spent and nothing is interrupted. The watermark is **per
session**, so two people sharing a project each hear once, and neither clears
it for the other; a session's first prompt is silent, because it was handed the
whole list in its system prompt a moment earlier.

Which leaves **one Save**, where there were two. The second typed the line
into a running session's input box, and it existed because that was the only
way anything reached one; with the session told by itself, what it bought was
the difference between telling somebody now and telling them when they next
look up, not a difference worth a permanent control, when the session's own
tab is one tap away. Save writes any memory edits, replays whatever the list
has staged, settles the panel, and says nothing. It is dead until something
has moved.

The line **names which half moved** (the roadmap, the memories, or both),
because "something changed" sends somebody to look at both, and one of the two
is a directory of files. The same line still rides on a **sent step**, which
is a message going to that session anyway: there it costs nothing extra, which
is the one place it never did.

A launch flag rather than a `/model` typed ahead of each message, for two
reasons: claude puts a confirmation behind that command, and a dialog is
exactly what "the pane has stopped changing" looks like, and it saves the
switch as the default for *new* sessions, so a per-project pick would leak to
every project.

**Unsaved work does not follow you between the four tabs.** Leaving one asks,
and answering yes throws the change away rather than carrying it along. It used
to carry: an edit left on Memory sat in a variable no tab switch touched, so
you could meet it again much later with no memory of making it, and Save from
another tab would write it. The tab close asks the same question for the same
reason.

What goes over is **a number and an instruction, never a copy of the report**.
The line asks the session to run `bb bug show N` for the area, the repro,
expected against actual and the notes so far, and tells it to close the bug
with `bb bug fix N "what fixed it"` when it is done. That is deliberate: the
tracker is the copy that stays current, and a report pasted into a
conversation starts going stale the moment anybody adds a note to it: the
session would then be working from the paste while everything else here reads
the file. One number cannot drift. It also means a bug that has grown a long
analysis costs the same to hand over as a one-line report.

The list lives in `/config/roadmap.json`, beside the tab strip and the locked
projects: deliberately **not** in the repository. A list like this churns far
faster than commits, and a checkbox tapped on a phone should not turn into an
uncommitted change. Anything that deserves to be permanent graduates out of it:
into `CLAUDE.md`, a commit message, or a test that fails when it regresses.
Thirty open items is the ceiling, because the list is read at the start of
every conversation and one nobody can take in at a glance is one nobody reads.
Ticked items stay a week, then go.

## The dev instance and the Docker manager

The boundary is the machine: a VM holding nothing anybody minds losing. What
the code adds bounds the **shape** of what gets sent rather than what it may
reach: every docker call goes through one function, which refuses any argv
that is not a `compose` call carrying a `--project-name`, two reads (`version`
and `ps`), or one of the three one-shot commands that tend the dev-data
directory, recognized by rebuilding the exact argv rather than by allowing the
verb. So a bug in a caller cannot become a freeform docker call. The **compose file** is the other half, and the one no
check on a NAME can bound: a file that says `privileged: true` and mounts `/`
produces a container named as innocently as any other. So it is read before anything
starts, and `privileged`, host `pid`/`network_mode`, and bind mounts landing
outside the project and `${BB_DEV_DATA}` are named on the row and put in a
confirmation. Confirmed once per set rather than per press: an
acknowledgement given every time is one nobody reads, and asked again the
moment the file reaches for something new. It warns rather than refuses: a
legitimate compose may genuinely want a host path, and nothing here can tell
which. That confirmation is a person's own press of Build. A session's build
is not asked it (26 Sep): the project's **Run its container** setting answers
for a session there as it does for every other container, so `auto` builds,
`ask` puts the build in front of a person, whose Allow is the confirmation,
and `deny` refuses. A session on `auto` that stopped here anyway was a
setting saying yes and a gate saying no to the same build.

**What a container is called** is what you called it: `radarr`, not
`bbdev-myproject-radarr`. The daemon is a machine with nothing else on it, so
there is nothing to keep a container out of the way of, and a name that is
three words of ceremony in front of the one you typed is only harder to find in
`docker ps`.

It was a button for one release, and that was a mistake worth naming: a
control you have to press before another control is not a step, it is a trap.
Nothing about it was ever a decision.

**There is no primary docker manager** (25 Sep). For a while the newest
enrolled node that ran docker was "the default node": the Docker tab opened
on it, the doctor called its daemon "the docker daemon", and a project with
no node sent its container there. With two nodes that meant every new
project landed on the machine enrolled last, which was never the one the
operator meant. Now a project's containers go to the project's node and
nowhere else: a project with no node has no daemon, Send to Docker and New
container make the person pick one and say why, `bb devapp` says the project
has no node, and New project offers a node rather than none. The one place a
pick still has to come from nowhere is the Docker tab's first open, and that
is derived from where the projects are bound (the node most of them use)
rather than from enrolment order. Doctor reports each node's daemon on its
own line.

## A new project's brief is the first session's, not CLAUDE.md

What New project was told to build used to become the project's CLAUDE.md,
and Claude Code reads CLAUDE.md at the start of every session as standing
instructions that override its defaults. So a request written on the first
day (a stack, a layout, three tabs) went on asserting itself after the
project had moved past it, and nothing kept it current (the operator, 28
Sep). A request is a task for one session. It is kept as
BUILDERBOT-BRIEF.md, a name Claude Code does not load, out of git; the first
Claude press shows it in a dialog to change, with the model and effort, since
nothing has started; the session takes it as its first prompt, and it leaves
the tree then, kept outside the codebase rather than deleted. CLAUDE.md is
left for the project to write about what it is.

## Captures go by age, never by need

A reel's sheet and an emulator shot land in the project's `dist/`, because
the Artifacts tab is where a person looks for what a session produced, and
nothing can tell when one is done with: two sessions on one project may each
be reading a reel the other made, and a session ending is not evidence that
its reel is. So they are removed by age (the project's "captures kept" days,
7 by default, swept on the read that draws the tab) or by somebody's hand
(Remove on the fold, `bb capture prune NAME` from a session), never by a
guess about need, and only the sheet and the record go to the share: the
recording and the full-size frames stay on the node's own disk (27 Sep, R96).

## Analysis

**The subtraction alone stopped being enough when `/workspace` stopped being
the whole share.** Pointing it at the projects folder: a better arrangement,
and the one that cut most of this noise; put the toolchain store *outside* the
directory being subtracted from, and 267 trivy findings about vendored
Flutter, Go and Android toolchains went straight to "unattributed": improving
the layout regressed the classifier. So the wider question is asked as well.
`/proc/self/mountinfo` says what this container mounts from beside its own
projects folder,

```
/development/projects -> /workspace
/development/SDK      -> /sdk
```

so `SDK` is known to be a share rather than a project, wherever the shares
are moved to next, and still without a list of what to skip. A name that is a
valid project is never taken this way, whatever it is mounted from: an
appdata directory called `BuilderBot` would otherwise teach it to ignore the
BuilderBot project's own findings, which is the one mistake here that hides
real work instead of noise.

**A report a whole cycle behind its siblings is not counted**, and the
Analysis tab's footer says which and by how much. A scanner that dies leaves its *previous* report in
place: a host script worth having does not overwrite a good report with
nothing, so a dead scanner and a live one are the same file to everything
downstream. On 28 Aug a trivy that had been crashing for four days was still
supplying most of this box's findings, against a directory layout that had been
changed in between: the scanner's volume was fixed, the numbers did not move,
and the fix looked broken. `bb findings` leaves the same file out and says so,
and reads it anyway if you name it on the command line.

A day is the line, and the size is the argument. One scan run writes every
report within minutes of itself, so anything measured in hours is the same run.
Re-running *one* scanner by hand, the obvious thing to do after fixing
one, must not blank its siblings. A report left behind by a failed scanner is
behind by a whole cycle, which for any cadence anybody runs is more than a day.

## A phone, and asking before touching it

That is a door that is shut by default rather than a wall. A session on the
node could set `ANDROID_ADB_SERVER_PORT` itself and go straight there;
nothing on one machine can be a wall. What it buys is that reaching the phone
is a deliberate act rather than an incidental one, and that every deliberate
one leaves a question on the owner's screen.

## How a view knows to re-read

Requests wait **fifteen minutes**, not five, and the card counts down. Five
assumed somebody was already watching the dashboard; a request that expires
before it is ever seen is worse than one that waits, because the session is
idle either way and only one of the two ends in an answer.

## Reading CI from inside the container

Two details that are load-bearing. The job sets `shell: bash` rather than
taking the default `bash -e`, because the difference is `pipefail`, without it
the tee's exit status becomes the step's and a failing linter reports success.
And the logs live on the node's disk rather than in a job's temp directory,
because a log that vanishes with the job is no use for *"what broke while I
was away?"*.

## Catching up after time away

It is deliberately a pull and not a ritual. A session's prompt already carries
the roadmap and the open bugs, paid for on every conversation in the project;
most conversations never ask about last week. Reach for it when the first
message refers to history (*"it finally built"*, *"is that still broken?"*),
which is exactly when the alternative is four or five commands.

## Push rights

**What decides which branches can be written is GitHub's, not this box's.** A
credential that can push can push to any branch, `main` included: no GitHub
credential has a per-branch scope: fine-grained PATs and classic PATs are
repository-level, and a deploy key is read or write on the whole repo. So
there is nothing to grant here that pushes to a branch and not to the default
one. If a merge should be somebody's decision rather than a push, the control
is a **ruleset on the default branch requiring a pull request**, set once per
repository on GitHub. Nothing in this container can do that for you, and a
local refusal would only be one more guardrail a shell can step around.

Projects that already existed when this arrived are granted retroactively if
their GitHub remote is an ssh one, recorded as `key`. Those are the repos that
were already being pushed to with deploy keys, and a new rule is not a reason
to take away something that worked. https remotes are not seeded: those
authenticated with a container-wide token, and one of their own is
the way back.

## The owner account

That is deliberate rather than a convenience. The alternative was a password in
the container's environment, where it is readable by anything that can read the
template, stays readable forever, and is the one credential that opens a shell
on this box. What the dashboard publishes is a writable shell inside a
container holding a loaded ssh-agent and read-write mounts of every project,
worth as much as the ssh keys are, so it is worth typing once into a form
instead.

## Accounts

**An `admin` has a shell, and a shell is everything.** Every session runs as
the same user inside the container: deliberately, so everything written to
your array keeps the ownership `PUID`/`PGID` give it, which means an
administrator can reach any account's files if they go looking. Give that role
to people you would give the server to.

## Telling a project's sessions about this environment

This used to be a 53KB block rendered into every project's `CLAUDE.local.md`
and pushed again whenever the template moved, with a window gate that ended
sessions when a copy fell behind. The copy was the problem: nothing kept it
current, and the machinery that policed it was larger than the thing it
policed.

A project set up before that may still carry one. Earlier still the block was
written into `CLAUDE.md` itself, between `<!-- BUILDERBOT:ENV:BEGIN -->` and
`<!-- BUILDERBOT:ENV:END -->`, and a project that committed it then has it in
its history and its working copy now: prose about machinery that is gone,
which nothing here reads and nothing here will ever update. It does no harm
beyond being wrong. Removing it is an ordinary edit to the project's own
`CLAUDE.md`, made and committed by whoever owns the project; BuilderBot does
not offer to do it, because that was always a commit to somebody else's
repository. A leftover `CLAUDE.local.md` is the same text outside git and can
simply be deleted.

## Logs

**Start with `builderbot.log`.** It used to end when the startup hooks
finished, so anything that broke an hour later was in a different file that
nothing pointed at. The dashboard's output is now split as it is written: all
of it into `dashboard.log`, and the warnings and errors copied into the boot
log as they happen. So the session's story is in one file and the detail is
next door, including a failed compose call, which the Docker manager reports
in both places.

