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

## What persists and what does not

This matters more than anything else here. The container is disposable and gets
recreated on every image update.

**Survives a container restart** — because it is on a mounted volume:

| Thing | Where |
|---|---|
| This project, including uncommitted work | `/workspace/<project>` → a share on the array |
| Your session transcripts and memory files | `~/.claude/` |
| Claude Code login, shell history, AVDs | `~` (the home volume) |
| Android system images and platforms | `~/.android/sdk` (symlinked into the SDK) |
| Gradle / npm / pip caches | `~/.gradle`, `~/.npm`, … |

**Does not survive** — anything written outside those paths:

- `/tmp`, `/var`, and the rest of the root filesystem
- `/opt` — including the Android SDK's tools and build-tools. The two
  expensive subdirectories (`system-images/`, `platforms/`) are symlinked to
  the home volume and *do* persist; everything else there comes from the image
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

`/workspace` holds *other projects* as sibling directories. Your working
directory is this project. Do not read from or write to sibling projects, and
do not go looking for context in them — if something seems to be missing, ask.

## There is no display

Everything is headless. There is no X server, no window manager, nothing to
show a GUI on.

- **Playwright** — browsers are pre-installed at `/opt/pw-browsers` and
  configured via `PLAYWRIGHT_BROWSERS_PATH`. Run headless. Never run
  `playwright install`; if a project pins a different version, launch with
  `executablePath: '/opt/pw-browsers/chromium'`.
- **Screenshots** are the way to show the user visual state — save to a file
  and surface the path.

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
is deliberate or a SHA1 is for dedup rather than security is a judgement about
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
`/workspace/_work`. It is registered at the **organisation** level, so it serves
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
- A push to a *different* repo in the org can be building on this same box
  right now. If something is inexplicably slow, that is a candidate.

## Toolchain already present

Do not install these; they are in the image.

`node 22` · `npm`/`yarn`/`pnpm` · `python 3.12` + `uv`/`pipx` · `jdk 21` ·
`android sdk` (build-tools, platform-tools, `bundletool`; platforms and system
images per `ANDROID_SYSTEM_IMAGES`) ·
`playwright` (chromium/firefox/webkit) · `git`/`git-lfs`/`gh` ·
`ripgrep`/`fd`/`fzf`/`jq` · `build-essential`/`cmake` · `ffmpeg`/`imagemagick` ·
`mise` for per-project tool pinning

Check `bb status` for versions and `bb doctor` when something environmental
looks wrong — it diagnoses auth, connectivity and GPU state in one pass.

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

<!-- Replace this section. Build/test/lint commands, architecture notes,
     conventions, anything a new contributor would need. -->

- **Build:**
- **Test:**
- **Lint:**
- **Conventions:**
