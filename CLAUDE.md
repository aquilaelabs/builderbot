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
tools are denied every sibling path and the runner's `_work` tree, via a
settings file passed on the command line. A `Read` or `Edit` that comes back
denied for a path outside this project is that rule, working as intended — not
a bug to route around with Bash.

## There is no display

Everything is headless. There is no X server, no window manager, nothing to
show a GUI on.

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
```

The emulator is **not** started automatically, holds a few GB of RAM, and runs
one at a time — so start it when you need it and stop it when you are done.

Which API levels exist is set by `ANDROID_SYSTEM_IMAGES` on the container. Run
`bb emu list` before assuming a version is available; if the one you need is
missing, say so rather than trying to install it — a runtime `sdkmanager`
install works but the user should decide to spend the disk.

Rendering is software by default (`swiftshader_indirect`), which has one
consequence worth internalizing:

> **`screenrecord` captures ~10fps under software rendering.** Do not use it to
> verify animation timing — a 300ms transition is 3 frames and you will draw
> the wrong conclusion. Use `dumpsys gfxinfo <pkg> framestats` for real
> per-frame timestamps. It works under any renderer.

Judging whether a duration *feels* right is a question for real hardware, and
you should say so rather than guessing from a headless emulator.

## The shared to-do list

This project has one, and it is the only thing here that both you and the
operator write.

```bash
bb todo                      # what is on it
bb todo add "..."            # put something on it
bb todo done N               # tick one off; undone N, rm N, clear
```

**The open items are already in your context.** They were appended to this
session's prompt when it started, so there is nothing to go and read at the
top of a conversation, and nothing to recite back — the operator can see the
list; they are looking at the same one.

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

**When a change needs several things done in a set order, add it as one item
with steps** — `bb todo add "rework the picker" --step "widen the select"
--step "then re-measure it"`. The operator can build and rearrange one from
the dashboard too, so write the steps in the order they have to happen and
leave the arranging to them. Steps are handed to a session one at a time, in
order, from the dashboard: the operator sends the first, and the second only
becomes sendable once the first has gone. Three separate items can be handed
over backwards, and the second one then lands on a tree the first was supposed
to have made.

A step that has been sent is struck through rather than removed, and can be
sent again — sent is not the same as done, and the difference is exactly the
case worth being able to see. So do not treat "you sent me this" as proof it
worked; if you cannot finish a step, say so plainly rather than quietly
leaving it struck through. A line can also be struck by hand, meaning the
operator dealt with it or dropped it; the list says which, so read the note
rather than assuming you were asked.

If the list or these notes change while you are working, you may be told in
one line, which names which of the two moved. Read them when it is relevant
and carry on — a change to the list is not a request to drop what you are
doing. That line costs the operator a
message, so it is sent only when they press **Save & tell the session** —
there is a plain Save beside it that changes things and says nothing. So do
not expect to hear about every change, and re-read with `bb todo` if what you
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

## Static analysis findings

If `/reports` exists, a scanner runs on the host and drops SARIF there.

```bash
bb findings        # this project's findings, repo-relative paths
bb findings --all  # every project the report covers
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
