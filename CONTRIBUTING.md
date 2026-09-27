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
  help against the README, the settings across their five places,
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
  (`who-calls`, `find`, `draws`, `suites`, `sections`, `state`); ask it
  before grepping.

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

## Where things are explained

`README.md` is the front page and the reference; `docs/architecture.md` the
map; `docs/how-it-works.md` the prose behind each part; `docs/decisions.md`
the design decisions with their dates and reasons; `docs/layout.md` the
file-by-file list; `docs/nodes.md` the design record for nodes.
