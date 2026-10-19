# Working inside BuilderBot

What this tree is, how it is built and tested, and where its parts live.
How to work here is the house rules (`bb rules`); what this machine is and
does is the briefing every session gets; the reasons behind both are in
CONTRIBUTING.md and docs/decisions.md.

## About this project

This repository **is** BuilderBot: the source of the container the
controller runs in. `scripts/` becomes `/opt/builderbot/scripts`,
`config/templates/briefing.md` is the briefing every session on every
project is handed, and the Dockerfile is the whole product. There is no
application here; the deliverable is the environment.

**Editing a file here does not change the running controller.** `bb` on the
PATH is the installed copy, not `scripts/bb` in this tree; `bash scripts/bb
<verb>` runs the checkout's (it sources the library beside itself), and
`bb lint` prints `[skip]` for a tool the running image does not carry.
Nothing is live until the operator rebuilds the controller from the branch,
which `bb status` and the dashboard header say the short commit of; `bb
catchup` says what the box has run and what changed since.

## Build

The image, and nothing else: `.github/workflows/build-image.yml` builds and
pushes `ghcr.io/aquilaelabs/builderbot` on a push to `main` that touches the
image's inputs (Dockerfile, `scripts/`, `config/`), plus a weekly uncached
rebuild; a manual dispatch is cached unless its `no_cache` box is ticked. It
runs on a hosted, pinned `ubuntu-24.04`, and a pull request does not build
it. Claude Code is in neither the image nor the boot: a session runs on a
node, which carries its own.

## Test

```bash
bb lint                       # shellcheck, hadolint, ruff, actionlint, compose, XML, the doc checks: the set CI runs
bb tests unit                 # the python unit tier, scripts/dashboard/unit, under a minute
bb tests run                  # the dashboard's Playwright suite; bb dashboard test FILE for one file
bb tests preflight            # what the branch changed, the suites that reach it, lint, voice, design: before a push
bb tests lab                  # the lab suites, against the lab's own stack (lab/compose.yml)
```

The browser suite runs the checkout's `server.py` on a spare port with a
scratch state directory, fake projects and a private tmux server, from a
copy of the tree, one run at a time. Its discipline is the house rule
`tests`. `surface.mjs` holds the page's top-level names; a new one is
added there. `lib.mjs` is the pattern a suite follows (real touch over
CDP, dialogs recorded, console errors collected). `BB_TEST_TIMING=1`
prefixes each result with its seconds, which `bb tests ingest` keeps on
the Tests tab. The `dashboard tests` workflow is separate from `lint` so a
timing-bound red run does not take the linters' verdict with it; `bb
ci-log` reads either.

- **One suite or one question:** `bb tests keep` holds the fixture up;
  `bb dashboard test SUITE` and `bb tests probe FILE.mjs` then attach to it.
  A probe is a scratch Playwright script importing `./lib.mjs` that asks the
  page a question. The kept world's server is the kept copy's, so a change
  to the dashboard's python needs `bb tests keep stop` and a new keep.
- **What the page asks for:** `bb dashboard trace [SECONDS]` prints what the
  server was asked over that window, by endpoint and by who asked;
  `uniform.mjs` holds the invariant (an idle page issues only its polls).
- **What the suite covers:** `bb tests coverage [SUITE...]` counts every
  function the copy's page, server and agent reach and merges it into
  `.bb-map/coverage.json`; `bb map covered NAME`, `bb map uncovered [FILE]`
  and `bb map unused` read it. A whole run refreshes it, and preflight picks
  suites by it (`bb map affected`).
- **Before a push:** `bb tests preflight`; `--dry` prints the plan,
  `--files F...` names the files, `--base HEAD` measures the working tree.
- **What other projects' sessions report:** `bb diag reports` lists what
  sessions elsewhere said with `bb report`; one worth fixing is added here
  with `bb bug add`. Nothing goes back to the reporter.

## Finding your way

`bb map find NAME`, `bb map who-calls NAME`, `bb map draws ID` and `bb map
suites FILE` answer "where would I look" from `scripts/lib/codemap.py`'s
index, with the function's own comment; `bb map sections FILE` reads a file
by its `// ---- name ----` headers, `bb map state [FILE]` lists a page
script's page-level `let`s, `bb map addresses` says which `file ~line`
details on the roadmap have moved. A miss is a bug to file and fix in
codemap.py. `bb drift` lists what this checkout changed that the running
controller is not serving; `bb dashboard dev` serves the live dashboard
from `./scripts/dashboard` until the container restarts (`--off` reverts).
`tools/readme-shots.mjs` retakes the README's pictures from a running
dashboard.

## Lint

`bb lint` runs the set CI runs on a pull request: shellcheck (file list
from shebangs, a heredoc inside a script included), hadolint
(`.hadolint.yaml`), ruff (`ruff.toml`; the agent's own pins to a Rocky
node's python), actionlint (`.github/actionlint.yaml`, generated by `bb
ci-labels --write`), compose validation, XML, and the doc checks: `bb help`
against `docs/reference.md` (written by `tools/bb-ref.sh`), the settings
across compose, `.env.example`, the Unraid template and the reference,
`docs/api.md` against the routes, `docs/layout.md` against `git ls-files`,
the agent's version against its file, and the instruction channels (this
file, the briefing, the shipped rules). CI runs on the pull request's merge
ref and nowhere else; `bb ci-log` reads a run's output.

## Layout and conventions

- **The agent's compatibility window.** `AGENT_VERSION` in
  `scripts/agent/builderbot_agent/__init__.py` is `WINDOW.BUILD`: inside a
  window nothing is held; across one the controller ends the sessions on a
  project whose node's agent is from the old window until it is updated
  (`server.compat_holds`). BUILD never resets; the minor moves only for a
  break, in the same change as the removal of what it supersedes.
  `test/version.mjs` holds both WINDOWs to the VERSION file.
- **Three numbers.** `bb version` moves per commit; a file two builds may
  read carries a format it checks (`.bb-map/map3.json`,
  `.bb-map/coverage.json`); `AGENT_VERSION` moves by hand with any change to
  the agent, and `bb lint` fails when it did not.
- **The dashboard is dependency-free.** `server.py` is stdlib-only and holds
  the routes, the transport and the gates; each handler checks who may ask
  and makes one call into the feature's module beside it, which answers
  `(payload, status)` and is handed what it needs by `configure()`.
  `index.html` is the markup, the stylesheet and the wiring that runs at
  load; `tab-*.js` one per document tab, `nb-*.js` one per notebook view
  (`nb-core.js` the notebook), `page-*.js` one per part of the page that is
  neither; all pure declarations, all `"use strict"`, served only by name
  from the page's own script tags (`server.page_scripts`). A tab kind
  declares `multi`, `live` and `open`.
- **The design language** is `docs/design-language.md`, written by this
  project's own Design view (`bb design file > docs/design-language.md`,
  committed with the change) and measured by `test/uniform.mjs`; the house
  rule `design` holds it.
- **Anything the page can execute is a table lookup** (`MACROS`,
  `TMUX_KEYS`, `TMUX_LITERALS`, `TOOLCHAINS`), never a command string, and
  `bb-tty` validates its one URL argument against directories that exist.
  The terminal, under `/term`, is there for anything else.
- **A setting that has to be in the environment lands in five places:**
  `.env.example`, `docker-compose.yml`, `unraid/builderbot.xml`,
  `docs/reference.md`, and `docs/unraid.md` when it needs host-side setup.
- **The briefing** is `config/templates/briefing.md`, assembled per session
  by `preamble.py` with the project's rules, roadmap and bugs: the core
  before `BUILDERBOT:CORE-END` and the project's own lines are in every
  session's block, and each `## Heading` with a `BUILDERBOT:TOPIC slug:
  gist` marker is a topic, named in the block's index and read with `bb
  help TOPIC`. Nothing is copied into a project.

`README.md` is the front page and `docs/README.md` the index of the docs;
`docs/reference.md` holds the configuration and `bb` references;
`docs/install.md` is the setup checklist, `docs/unraid.md` the host-side
walkthrough, `docs/how-it-works.md` the overview and the docs it names the
explanatory prose,
`docs/decisions.md` the design decisions with their dates and reasons, and
`docs/layout.md` the file-by-file layout.
