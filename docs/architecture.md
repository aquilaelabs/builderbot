# Architecture

One page: what the parts are, how they reach each other, and where each is
explained. Everything below is one of seven things.

```
                      the projects share (/workspace: every project's tree)
                                   |
   +------------- controller -------------+        +----------- node ----------+
   |  the dashboard (server.py + the page) |  <---  |  the agent (dials in)     |
   |  the notebook: roadmap, bugs, rules,  |  --->  |  jobs: build, test, emu,  |
   |    tests, memory, changelog           |  hello |    compose, tell, update  |
   |  the store: /config (SQLite + JSON)   |  work  |  sessions: bb-session,    |
   |  the relay: a session's bb verbs      |  result|    bb-tty, tmux, Claude   |
   |  the asks: root, phone, container,    |        |  the toolchain store      |
   |    rebuild, on the bell               |        |  docker, the emulator,    |
   +---------------------------------------+        |    a phone, an X display  |
                                                    +---------------------------+
```

## The controller

One container (the Dockerfile, `docker-compose.yml`, the Unraid template).
It holds the record and answers the dashboard; it runs nothing of a
project's itself. `scripts/entrypoint.sh` starts it, `scripts/supervisor.sh`
keeps it alive, and `scripts/startup.d/` are its hooks. Explained in
how-it-works.md under *What's in the image*, *Startup hooks* and *Security
model*.

## The dashboard

`scripts/dashboard/server.py` is the routes, the transport and the gates;
each handler checks who may ask and makes one call into the module beside
it. `index.html` is the markup, the stylesheet and the wiring that runs at
load; one `tab-*.js` per document tab, one `nb-*.js` per notebook view,
one `page-*.js` per part of the page that is neither. No framework, no
build step. The page's design language is `docs/design-language.md`; its
suite is `scripts/dashboard/test/` (CONTRIBUTING.md says how to run it).
Explained in how-it-works.md under *Web dashboard*, with a section per tab.

## The notebook

What a project's people and its sessions share: the roadmap, the bugs, the
house rules, the test registry, the memories, the changelog. One module per
view beside server.py (`roadmap.py`, `bugs.py`, `rules.py`, `testreg.py`,
`memory.py`, `changelog.py`), one store each under /config, and `bb roadmap`,
`bb bug`, `bb rules`, `bb tests`, `bb changelog` driving the same files; a
session's writes that the project holds for approval go through
`pending.py`. Explained in how-it-works.md under *The notebook*; the reasons
in decisions.md under *The notebook*.

## Nodes and the agent

A node is a machine enrolled to run work: builds, tests, the emulator, a
project's containers, and the Claude sessions themselves. It runs the
agent, `scripts/agent/` (the `builderbot_agent` package and its entry,
shipped as one zip that python runs as it would a script), which dials into the controller
(`channel.py` on that side: enroll, hello, work, result) and needs no port
of its own; the controller keeps the registry and the job queue in
`nodes.py`. `nodes/provision-linux.sh` makes a Linux machine a node,
`nodes/provision-macos.sh` a Mac, `nodes/bb-session` is the root helper
that gives a session its own view of its project. The design record is
`docs/nodes.md`; the walkthroughs `docs/sandbox-vm.md` and `docs/unraid.md`.

## Sessions

A Claude session runs on its project's node, in tmux, started by `bb-tty`
from a dashboard terminal, inside its own view of the project
(`bb-session`) and its own network (R79). It is briefed from
`config/templates/briefing.md`, assembled per session by `preamble.py`
with the project's rules, roadmap and bugs. Its `bb` verbs reach the
controller through the relay (`bbrelay.py`, `scripts/lib/relay-verbs`),
its hooks post through `hooks.py`, and its git pushes go through
`gitrelay.py`, since the controller holds the keys. Explained in
how-it-works.md under *Keeping a session in its own project* and *Telling
a project's sessions about this environment*.

## The store and the toolchain store

The controller's state is `/config`: SQLite (`db.py`, with
`scripts/dashboard/migrations/`) for the registry and the queue, and one
JSON file per feature beside it, written through `statefile.py`. A node's
big downloads live on the toolchain store, outside the image, managed by
`scripts/lib/sdk.sh` from `config/toolchains.json`. Explained in
how-it-works.md under *The toolchain store lives outside the image*.

## The asks

Some things wait on a person: root on a node, a phone, a container from a
compose file, a session's rebuild under a project's setting. Each is a
request on the bell and the tab it belongs to, answered with Allow or
Deny, and the session waits on the answer through the same verb
(`phone.py` holds the queue; `bb root`, `bb phone`, `bb container`,
`bb devapp`). Explained in how-it-works.md under *A phone, and asking
before touching it* and *The dev instance and the Docker manager*.

## Where the rest is

- `README.md`: the front page, the configuration reference, the bb
  reference (written from `bb help`).
- `docs/decisions.md`: the design decisions with their dates and reasons.
- `docs/layout.md`: every file, held to the tree by `bb lint`.
- `docs/users.md`: accounts, roles, what each may reach.
- `docs/journeys.md`: what a person does with it, walked for real, dated.
- `CONTRIBUTING.md`: a person's way in; `CLAUDE.md`: a session's.
