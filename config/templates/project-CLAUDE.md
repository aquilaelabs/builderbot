# Working inside BuilderBot

> Template. Copy to the root of a project mounted in BuilderBot as `CLAUDE.md`
> (or append to an existing one), then delete the sections that do not apply
> and fill in the project-specific part at the bottom.
>
> ```bash
> cp /opt/builderbot/templates/project-CLAUDE.md /workspace/<project>/CLAUDE.md
> ```

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
| Gradle / npm / pip caches | `~/.gradle`, `~/.npm`, … |

**Does not survive** — anything written outside those paths:

- `/tmp`, `/var`, `/opt`, and the rest of the root filesystem
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
bb emu start      # boot the AVD headless (takes ~50s cold)
bb emu status     # adb devices -l
bb emu stop       # graceful shutdown — use this, do not kill the process
```

The emulator is **not** started automatically and holds a few GB of RAM, so
start it when you need it and stop it when you are done.

Rendering is software by default (`swiftshader_indirect`), which has one
consequence worth internalizing:

> **`screenrecord` captures ~10fps under software rendering.** Do not use it to
> verify animation timing — a 300ms transition is 3 frames and you will draw
> the wrong conclusion. Use `dumpsys gfxinfo <pkg> framestats` for real
> per-frame timestamps. It works under any renderer.

Judging whether a duration *feels* right is a question for real hardware, and
you should say so rather than guessing from a headless emulator.

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

The self-hosted runner (`runs-on: [self-hosted, builderbot]`) executes jobs in
this container, under `/workspace/_work`. Two implications:

- The toolchain CI sees is the toolchain you see. If a build works here it
  should work in CI, and if you needed an undocumented step, CI needs it too.
- CI jobs and your session share CPU, RAM and disk. A heavy build while the
  emulator is running can starve both.

## Toolchain already present

Do not install these; they are in the image.

`node 22` · `npm`/`yarn`/`pnpm` · `python 3.12` + `uv`/`pipx` · `jdk 21` ·
`android sdk` (platform 35, build-tools, platform-tools, `bundletool`) ·
`playwright` (chromium/firefox/webkit) · `git`/`git-lfs`/`gh` ·
`ripgrep`/`fd`/`fzf`/`jq` · `build-essential`/`cmake` · `ffmpeg`/`imagemagick` ·
`mise` for per-project tool pinning

Check `bb status` for versions and `bb doctor` when something environmental
looks wrong — it diagnoses auth, connectivity and GPU state in one pass.

---

## About this project

<!-- Replace this section. Build/test/lint commands, architecture notes,
     conventions, anything a new contributor would need. -->

- **Build:**
- **Test:**
- **Lint:**
- **Conventions:**
