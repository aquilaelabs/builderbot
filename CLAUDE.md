# Working inside BuilderBot


---

## About this project

This repository **is** BuilderBot — the source of the container you are running
inside. `scripts/` becomes `/opt/builderbot/scripts`, `config/templates/` ships
the briefing every session on every project is handed, and the Dockerfile is
the whole product. There is no application here; the deliverable
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
  weekly cron rebuild, so the base image stays fresh. Claude Code is in
  neither the image nor the boot: a session runs on a node, which carries its
  own. It runs on `ubuntu-latest`, deliberately: hosted minutes cost more,
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
  bb lint                       # shellcheck / hadolint / ruff / actionlint / compose / XML, the same set as CI
  bb tests run                  # the Playwright suite, timed and recorded; bb dashboard test [cards] for one file
  bb tests lab                  # the lab suites, against the Gitea of BuilderBot's own dev stack (lab profile)
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

- **Lint:** CI runs shellcheck, hadolint, ruff (ruff.toml at the root; the
  agent's own pins it to the python a Rocky node carries), actionlint, compose validation and
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
  (`scripts/lib/embedded.py`), so a finding may name the extracted copy
  (`provision-linux.sh-BBSANDBOX`). The python a shell script feeds to
  `python3` from a quoted heredoc goes through ruff the same way, as
  `bb-PY-7.py`, with its line numbers those of the script it sits in.
- **Conventions** live in the house rules on the Briefing tab (`bb rules`);
  what follows is the layout they refer to.
  - The dashboard is deliberately dependency-free: `server.py` is stdlib-only,
    `index.html` is vanilla JS and CSS with one classic `tab-*.js` script per
    document tab and one `nb-*.js` per notebook view beside it. No framework,
    no build step.
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
  - What a session is briefed with comes from `config/templates/briefing.md`,
    assembled per session by `preamble.py` with the project's rules, roadmap
    and open bugs. Nothing is copied into a project, so editing that file is
    the whole of changing what every session reads.
  - The weekly Monday build is uncached by design and is always a full pull;
    a manual dispatch is cached unless its `no_cache` box is ticked.

`README.md` holds the full configuration reference and a file-by-file layout;
`docs/unraid.md` is the host-side walkthrough.
