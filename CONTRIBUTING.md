# Contributing

BuilderBot is the source of the container it runs in: `scripts/` becomes
`/opt/builderbot/scripts`, `config/templates/` ships the briefing every
session is handed, and the Dockerfile is the whole product. That decides
the shape of a change: nothing you edit here is live until CI builds a new
image and the box updates to it, so the loop is edit, prove on the checkout,
open a pull request, and let the image follow.

## Getting a checkout

Clone the repository and open it as a project on a BuilderBot, which is what
its own sessions do: the tree lives on the projects share, the notebook
(roadmap, bugs, rules, tests) is the controller's, and `bb` is on the PATH.
Outside a BuilderBot the linters and the dashboard's suite still run; the
notebook verbs do not, since they relay to a controller.

## Seeing a change

- `bb dashboard dev` restarts the live dashboard from `./scripts/dashboard`
  (same port, same credential, until the container restarts; `--off` puts
  it back), so a dashboard change is looked at in a browser without an
  image build.
- `bash scripts/bb <verb>` runs the checkout's `bb` rather than the image's;
  the installed one on your PATH is `/opt/builderbot/scripts/bb`.
- `bb capture shot URL FILE` pictures a page at rest; `bb capture reel`
  shows what changed over time. Both are how a change is shown to somebody
  who was not watching.
- A change that touches how sessions start, what they are handed, or what a
  node does is rebuilt onto the project's dev instance and walked there
  before production is asked to build it (`bb devapp rebuild`; the house
  rule `prove-on-dev`).

## Proving it

- `bb lint` runs shellcheck, hadolint, ruff, actionlint, compose validation,
  XML well-formedness, and the checks that hold the docs to the tree (bb
  help against `docs/reference.md`, the settings across their five places,
  `docs/layout.md` against `git ls-files`, the agent's version against its
  file). CI runs the same set on a pull request.
- `bb tests run` runs the dashboard's Playwright suite, isolated: its own
  server on a spare port, a scratch state, fake projects, a private tmux
  server. `bb dashboard test FILE` runs one file; `bb tests keep` holds the
  fixture up so `bb tests probe FILE.mjs` can ask the page a question.
- `bb tests preflight` lists what the branch changed, asks the code map
  which suites reach it, and runs those with the lint, voice and design
  checks. Run it before a push.
- `bb map` answers "where would I look" from an index over the tree
  (`find`, `who-calls`, `draws`, `suites`, `sections`, `state`): where a
  name is defined or called is its question; grep is for text.

## The house rules

`bb rules` prints them; the Briefing tab carries them; every session started
here is held to them, and the ones with a check (`bb rules check NAME`) run
before a change is handed back. Two you meet first: no em dash on a line the
branch adds, and one file per feature, with `server.py` holding a route and
one call into the module beside it.

## Landing it

Work lands on a branch and merges through a pull request the operator opens
from their desktop: push the branch (`bb git push` on a node, since the
controller holds the keys), hand over the link, move on. A pull request runs
lint and, for a dashboard change, the browser suite, on the repository's own
runner; it does not build the image. The image is built on `main`, by a
hosted job, on a push that touches its inputs, and `:latest` does not move
until that build passes. What a change means for the person using the
product goes in `CHANGELOG.md` through `bb changelog add`, under Added,
Changed, Deprecated, Removed, Fixed or Security.

## Why the harness is shaped the way it is

The house rule `tests` says what to do; this is why each clause is there.
Every run is from a copy of the tree because the page loads its scripts
from disk on every reload while its server keeps the python it started
with, so a run in a tree edited meanwhile was a run of neither version
(B616, 10 Oct 2026; `BB_TEST_INPLACE=1` still runs in place). One run at a
time because three suites side by side was the reproducer of bug 13, which
is what the lock is for; a lock a canceled CI job left is taken over on the
next run, since the directory is world-writable and not sticky. A run is
ended by the pid in its lock because `pkill -f` and `pgrep -f` match your
own prompt's command line. A run is waited on with `run_in_background` and
its notification because a loop over a log that a dead command was supposed
to write never ends (eight such loops were found alive at once, the oldest
at 10h54m). A whole run doubles every wait, and a wait that runs out while
the page still has requests in flight or the box is saturated is given the
same time again, three times at most, because four workers on four cores
timed out a dozen checks a day that passed alone (27 Sep 2026). Inside tmux
the client ignores `TMUX_TMPDIR`, so an ad-hoc harness that makes a session
lands it on the real server. And `run.sh` called by hand once tested a
whole day's work on the node while the container it was meant to prove sat
untouched (R65), which is why `bb tests run` goes through `bb test`.

The `dashboard tests` workflow is separate from `lint` because the suite is
timing-sensitive and the runner shares its box with everything else: while
it was a step in the lint job it took the linters' verdict with it (bug 19).
The image is built on a hosted runner because building it on the box that
runs it is circular: a bad image would take down the runner that has to
build the fix (R116). `bb ci-log` exists because the runner keeps no
console output, and without it the only evidence of a red run was the
runner's `_diag` directory, which names the failing step and nothing it
said; that cost a round trip through the operator once. The preflight
exists because the one suite skipped by hand before a push was the one that
would have caught it. The map is rebuilt by its own fingerprint because a
scanner changed without a hand-bumped number once left every index
answering from the old reading (8 Oct 2026).

## Where things are explained

`README.md` is the front page; `docs/README.md` the index of the docs;
`docs/reference.md` the configuration and `bb` reference;
`docs/architecture.md` the map; `docs/how-it-works.md` the overview, and the
docs it names (one per part of the dashboard) the prose behind each part; `docs/decisions.md` the design decisions with their dates and reasons;
`docs/layout.md` the file-by-file list; `docs/nodes.md` the design record for
nodes.
