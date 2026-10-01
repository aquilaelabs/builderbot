# Working inside BuilderBot

What a session started in this repository is told, over the briefing every
session gets: what this tree is, how it is built and tested, and the
conventions the house rules refer to. A person's way in is CONTRIBUTING.md.

## About this project

This repository **is** BuilderBot: the source of the container you are running
inside. `scripts/` becomes `/opt/builderbot/scripts`, `config/templates/` ships
the briefing every session on every project is handed, and the Dockerfile is
the whole product. There is no application here; the deliverable
is the environment.

The consequence you hit first: **editing a file here does not change the
running container.** `bb` on your PATH is `/opt/builderbot/scripts/bb` from the
image, not `scripts/bb` in this tree. `bash scripts/bb <cmd>` dry-runs the
checkout properly (it sources the library next to itself, so a new helper in
`lib/common.sh` is there), but the startup hooks and the dashboard still source
`/opt` by absolute path, and nothing is really live until CI builds a new image
and Unraid updates the container.

The dashboard header carries the short commit of the image the box is
running, beside the uptime, and `bb status` prints the same line first.

The version of that question which spans days, *what was the box on when I
saw that?*, is `bb catchup`. The entrypoint appends a line to
`/config/image-log.tsv` every time the stamp changes, so the images this
container has actually run are a list rather than a guess, and the same
command prints recent commits with the first line of their bodies, what moved
in the notebook, and the builds this box archived. Reach for it when the
operator opens with *"it finally built"*; it exists because reconstructing that
by hand cost four commands and still could not see the failed builds.

- **Build:** the image, and nothing else. `.github/workflows/build-image.yml`
  builds and pushes `ghcr.io/aquilaelabs/builderbot` on pushes to `main`
  that touch the image's inputs (Dockerfile, `scripts/`, `config/`), plus a
  weekly cron rebuild, so the base image stays fresh. Claude Code is in
  neither the image nor the boot: a session runs on a node, which carries its
  own. It runs on `ubuntu-latest`, deliberately: hosted minutes cost more,
  but building the image on the box that runs the image is circular: a bad
  image would take down the runner that has to build the fix. **A pull request
  does not build it.** That used to be two hosted builds for one answer, the
  second of which is the only one that ships, so a change that breaks the
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
  scratch state dir, fake projects and a **private tmux server**, so it cannot
  touch the live dashboard, and its own `dashboard tests` workflow runs it on
  this runner for a PR that changes `scripts/dashboard/`. That is a separate
  workflow from `lint` on purpose: the suite is timing-sensitive and this
  runner shares its box with everything else, so it goes red for reasons that
  are not the code's, and while it was a step in the lint job it took the
  linters' verdict with it. Do not read a red `dashboard tests` as a
  regression without checking `bb ci-log`; see bug #19.
  `surface.mjs` holds the page's top-level names and compares both ways:
  MISSING means one fell into a nested scope, NEW means a global appeared.
  The pattern in `lib.mjs` (real touch via CDP, dialogs recorded, console
  errors collected) is the one to follow. `BB_TEST_TIMING=1` prefixes every
  result with the seconds since the last one; feed that output to `bb tests
  ingest` and the notebook's Tests tab keeps the numbers. The house rule
  `tests` carries the discipline: one run at a time, no edits under the
  dashboard during one, kill by pid. Why each clause is there: three suites
  side by side is bug 13's reproducer, which is what the lock is for; a
  lock a canceled CI job left is taken over on the next run, since the
  directory is world-writable and not sticky; `pkill -f` and `pgrep -f`
  match your own prompt's command line, so a run is ended by the pid in
  its lock; a loop over a log that a dead command was supposed to write
  never ends (eight such loops were found alive here at once, the oldest at
  10h54m), so a run is waited on with `run_in_background` and its
  notification; a whole run doubles every wait, and a wait that runs out
  while the page still has requests in flight or the box is saturated is
  given the same time again, three times at most, because four workers on
  four cores timed out a dozen checks a day that passed alone (27 Sep);
  inside tmux the client ignores `TMUX_TMPDIR`, so a
  throwaway session made by an ad-hoc harness lands on the real server;
  and `run.sh` called by hand tested a whole day's work on the node while
  the container it was meant to prove sat untouched (R65), which is why
  `bb tests run` goes through `bb test`.
  If the *installed* `bb` predates a subcommand, `bash scripts/bb <cmd>` runs
  the repo copy, and `bb lint` prints `[skip]` for any tool the running image
  does not carry yet, rather than passing by omission. The dashboard's server
  resolves `bb` as the copy beside it, so `bb dashboard dev` exercises the
  checkout's subcommands too.

- **Iterating on one suite or one question:** `bb tests keep` runs the
  harness's whole set-up once and holds the fixture up; after that
  `bb dashboard test SUITE` and `bb tests probe FILE.mjs` attach to it:
  half the time of a fresh run (4s against 8s for a small suite here, the
  set-up being a copy of the tree and the fixtures), and, what matters
  more, the world a suite just left is still there for a probe to look
  at. A probe is a scratch Playwright script that imports `./lib.mjs` and
  asks the page a question (count fetches, read a variable, screenshot):
  the fastest route to the truth about the dashboard, and the front door
  for what used to need a path hack. The kept world is not put back
  between runs, and its server is the kept copy's, so a change to the
  dashboard's python needs `bb tests keep stop` and a new keep; its `.js`
  and `.html` are copied over before every attached run.
- **What other projects' sessions say about BuilderBot:** a session on any
  other project reports a problem with BuilderBot itself with `bb report`,
  never its own tracker (the briefing says so), and the
  reports wait on the controller. This project turns it off in its settings
  (Claude may: Report BuilderBot bugs), so its own problems go into its own
  tracker as ever. `bb diag reports` lists the open ones;
  `bb report file N` files one into this tracker as a bug (`--as B123` for
  one this tracker already has) and `bb report close N "why"` answers one
  that needs nothing. The session that reported it reads the outcome with
  `bb report`, so the close's words are addressed to it.
- **What the page is asking for:** `bb dashboard trace [SECONDS]` prints
  what the server was asked over that window, by endpoint and by who
  asked (browser, session, agent, the companion app), from a ring the
  server keeps in memory. It is the one command that shows a poll that
  should not be there or a tab that asks twice; `uniform.mjs` holds the
  invariant (an idle page issues only its polls; opening a tab asks each
  endpoint once).
- **What the suite covers:** `bb tests coverage [SUITE...]` runs the
  harness with a counter in every function of the copy it runs from (the
  page's, the server's and the node agent's under a profile hook, the
  agent counted whether run as a process or driven in process) and merges what they
  reached into `.bb-map/coverage.json`; then `bb map covered NAME` says
  which suites ran a function and how often, which is the regression net
  for touching it, and `bb map uncovered [FILE]` lists what no suite
  reaches, which is where a probe is written before a refactor. `bb map
  unused` is dead code by measurement: no call and nothing passing the
  name anywhere. R76.
- **Before a push:** `bb tests preflight` lists the files the branch
  changed (against `origin/main`, plus the working tree), asks the map
  which suites reach them, and runs the python unit tier (`bb tests unit`,
  under a second) first, then those suites with the lint and voice checks,
  and the design check when a file carrying style changed (index.html,
  static/, the design language, uniform.mjs); for script and python the map
  already puts uniform in the suites when it reaches the change. The worker
  plan balances suites by the seconds each took on this node
  (`.bb-map/suite-times.tsv`), and `BB_TEST_PHASES=1` times a suite's set-up.
  `--dry` prints the plan, `--files F...`
  names the files instead, and `--base HEAD` measures the working tree
  alone when the branch is long and the default would be everything.
  With a covered run on record (`.bb-map/coverage.json`) the suites are
  picked by the functions the changed lines fall in and the suites that
  reached them (`bb map affected`), so a change to one handler in
  `server.py` is that handler's suites rather than all 49; a changed
  function no covered run has seen falls back to the file's answer, and
  in `server.py` to every suite, said as such. A whole run is made with
  the counters in and refreshes the covered run, so the next preflight
  measures by the last whole gate. This exists because the one suite
  skipped by hand before a push was the one that would have caught it.
- **Finding your way:** `bb map who-calls NAME`, `bb map find NAME`,
  `bb map draws ID` and `bb map suites FILE` answer "where would I look"
  from an index over this tree (`scripts/lib/codemap.py`, roadmap R75).
  Ask it before grepping; `test/codemap.mjs` holds it to the tree. `find`
  and `who-calls` also hand over what a function says about itself, the
  comment directly above it or its docstring's first sentence: the notes
  live in the code, never in the map, and the map reads them out.
  A new project is mapped in the background as it is created
  (`mapping.py`), and its first Claude session waits for that, so the
  index is there before the first question.
  `bb map sections FILE` reads a file by its `// ---- name ----` headers:
  each section's functions, how many callers reach in from outside, what
  runs at load, what the suite covers. A section with few outside
  callers and nothing at load moves to its own file whole, which is how
  the inline script leaves `index.html`. `bb map state [FILE]` lists a
  page script's page-level `let`s with where each is assigned and from
  what: one fed from `state` is a copy of the poll kept by hand (B213,
  B215), and the sweep for those starts there. `who-calls` lists where a
  function is passed by name as well as where it is called, so a handler
  handed to a draw never reads as dead. Every fix here carries its reason
  in a comment beside it, and what moves keeps the words and changes the
  addresses: `bb map addresses` reads the roadmap's `file ~line` details
  (or any file) and says which addresses moved away from the name beside
  them and which names are gone, which is how a plan written last month
  is still a plan.
- **Seeing a change without a rebuild:** `bb drift` lists what this checkout
  has changed that the running container is not serving. For the dashboard
  specifically, `bb dashboard dev` restarts the live dashboard from
  `./scripts/dashboard` (same port and credential; lasts until the container
  restarts; `--off` reverts), so a dashboard change can be looked at in the
  browser without a 40-minute image build. `bb capture shot URL... [FILE|DIR]` takes
  headless screenshots to show the operator; it reads `DASHBOARD_AUTH` from
  the environment for the dashboard's own pages. `tools/readme-shots.sh`
  regenerates the README's screenshots from a staged instance.

- **Lint:** CI runs shellcheck, hadolint, ruff (ruff.toml at the root; the
  agent's own pins it to the python a Rocky node carries), actionlint, compose validation and
  XML well-formedness on a node's runner; `bb lint` runs the same set here,
  and the house rule `lint` runs it as its check before a session hands
  back. **When it fails, `bb ci-log` is the first place to look:** the runner keeps
  no console output, so the workflow tees each check into
  `/config/ci-logs/<repo>/` and that command reads it. `--list` shows the runs
  kept with their results. Without it the only local evidence is the
  runner's own `_diag` directory on its node, which names the failing step and
  nothing it said;
  that cost a round trip through the operator once already.
  It runs **on the pull request and nowhere else**. A `pull_request` build
  checks out `refs/pull/N/merge`, this branch already merged into main, so
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
  - The agent's compatibility window, behind the house rule `agent-compat`:
    inside a window nothing is held (a briefing block behind on a feature
    gets the row's update link and its Claude button stays live; an agent
    behind gets Update on the Nodes tab and its sessions keep running).
    Across a window the controller ends the Claude sessions on a project
    whose own node's agent is from the old window, ghosts that project's
    button and `bb-tty` refuses, per project, until that node's agent is
    updated (`server.compat_holds`, `compat_reap_once`). The briefing is
    assembled per session (R63 step 3), so nothing in a project's tree can
    be from another window any more. BUILD is the
    agent's own counter and never resets: 0.5.28 follows 0.4.27. Moving
    the minor is the one moment superseded paths (an old verb, a fallback
    for a pre-window agent) are removed, and `test/version.mjs` holds both
    WINDOWs to the VERSION file.
  - Two numbers move by machine and one by hand. `bb version` moves per
    commit; a file two builds may read carries a format it checks
    (`.bb-map/map3.json`, `.bb-map/coverage.json`) and a reader that meets
    another rebuilds; and `AGENT_VERSION` in `scripts/agent/builderbot-agent.py`
    moves by hand, so `bb lint` fails when that file changes against the
    branch's base without its patch moving. A node compares the file and
    the row names the number, and when they disagreed three tabs said
    "runs 0.6.92 and ships 0.6.92" (B221).
  - The dashboard is deliberately dependency-free: `server.py` is stdlib-only,
    `index.html` is the markup, the stylesheet and the wiring that runs at
    load, with one classic `tab-*.js` script per document tab, one
    `nb-*.js` per notebook view (`nb-core.js` is the notebook itself), and
    one `page-*.js` per part of the page that is neither (the state and its
    helpers, the tabs and the strip, the panes, the sidebar, a project's
    settings, the polls, the bell and the rest), all loaded before the
    page's own script, all pure declarations and all `"use strict"`:
    wiring that must run at load stays in `index.html` under the section's
    header, and the server serves a script only by name, from the list the
    page's own script tags make (`server.page_scripts`). No framework, no
    build step. `bb map sections FILE` reads any of them by its headers.
    On the server the same split: `server.py` holds the routes, the
    transport and the gates, and each handler checks who may ask, then
    makes one call into the feature's module beside it (a project's
    verbs in `projects.py`, the Nodes tab's in `nodes.py`, what the page
    may type into a terminal in `macros.py`), which answers with the
    payload and its status and is handed what it needs by `configure()`
    or by an attribute the server sets (R77).
  - **The dashboard's design language is `docs/design-language.md`**, held
    by the house rule `design`, which names it and runs `test/uniform.mjs`
    as its check. Since 28 Sep the file is written by this project's own
    Design view in the notebook: its themes are the dashboard's schemes,
    its notes are the prose, and its pages are the dashboard's surfaces.
    Change the design there, or as a session with `bb design json`, an
    edit, and `bb design save`, then `bb design file > docs/design-language.md`
    and commit the file with the change; a hand edit to the file alone is
    overwritten by the next write. A new tab kind declares `multi` (a notebook is per
    project; everything else is one window onto one thing), `live`
    ("always" for a kind rendering from `state`, a revision function for one
    whose data arrives on its own schedule), and `open` for whatever its
    first draw has to fetch.
  - Anything the web UI can execute is a table lookup (`MACROS`, `TMUX_KEYS`,
    `TMUX_LITERALS`, `TOOLCHAINS`) rather than a command string, and `bb-tty` validates its one
    URL argument against directories that actually exist. New surface keeps that
    shape: the terminal is one port over for anything else.
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

`README.md` holds the configuration reference and the `bb` command reference;
`docs/install.md` is the setup checklist, `docs/unraid.md` the host-side
walkthrough, `docs/how-it-works.md` the explanatory prose, `docs/decisions.md`
the design decisions with their dates and reasons, and `docs/layout.md` the
file-by-file layout.
