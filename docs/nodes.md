# Controller and nodes — a design

BuilderBot today is one container with one remote Docker daemon hard-coded into
an environment variable. This describes turning it into a **controller** that
schedules work onto **nodes**, where the controller is itself a node, and where
a node is any registered host — a VM on the same server, a spare desktop, a
cloud instance — that can execute something.

It is a design document, not a plan of record. Where it disagrees with the
brief that prompted it, the disagreement is stated with its reason; where a
piece is over-engineered for a one-operator homelab, it says so and says what
to build instead.

## What exists now, honestly

Worth writing down, because most of it survives and the parts that do not are
the parts that decide the phasing.

- `DOCKER_HOST` names one sandbox VM, addressed over ssh, verified by a
  `builderbot.sandbox` label the provisioner writes. Everything the Docker
  manager does is `docker compose --project-name …` plus three whitelisted
  one-shot `docker run` shapes, and a guard rebuilds each argv and compares it
  whole.
- Work is not scheduled. There is one job at a time in `devapp.py` (`_job`, a
  module global) and another in `packages.py`, each a dict with a step word and
  a log tail. Nothing queues, nothing is placed, nothing retries.
- `/workspace` is a mounted share holding every project. Sessions, builds, the
  Actions runner and the emulator all run in the controller container against
  that one tree.
- State is JSON files under `/config` with an flock around read-modify-write
  (`statefile.py`). That was chosen over SQLite deliberately, for data that is
  small, human-editable and read whole.
- The GitHub Actions runner runs **in this container**, registered at the org
  level with fixed labels.

So the machine already does five jobs: dashboard, session host, build box,
Actions runner, and Docker client. The node model is what lets four of those
five be somewhere else.

## 1. The data model

### Node

```jsonc
{
  "id": "n_7f3a91",            // generated at enrollment, never reused
  "name": "sandbox",           // display only, renameable
  "kind": "local | agent | ssh",
  "created": 1756700000,
  "agent": {                   // kind=agent
    "version": "0.4.0",
    "token_id": "t_12",        // which credential it authenticates with
    "last_seen": 1756700123,
    "addr": "10.0.0.9"         // as seen by the controller, informational
  },
  "ssh": { "addr": "ssh://bb@10.0.0.9" },   // kind=ssh, bootstrap or legacy
  "capabilities": ["docker-host", "package-build"],
  "labels": { "arch": "amd64", "os": "debian12", "gpu": "none",
              "disposable": "true" },
  "concurrency": 1,
  "state": "online | offline | draining",
  "reported": {                // the agent's own census, refreshed on connect
    "cpu": 8, "mem_mb": 16000, "disk_free_mb": 240000,
    "docker": "27.3.1", "java": "21", "android_sdk": true
  }
}
```

Four things are worth arguing about here.

**The id is the node's, not the address's.** Generated at enrollment, written
to `/etc/builderbot/node.json` on the node, and used as the key for
everything the controller remembers about it — caches, last-known container
lists, build records. An address is not an identity: two VMs can wear one IP,
and one VM changes address when it moves. This is the same lesson the Docker
manager already learned the hard way, where a build record keyed by address
survived onto a different machine.

**Capabilities are node-side facts, not controller-side claims.** The
controller stores what a node reported it can do, and the agent refuses a job
whose capability it does not hold. If those two disagree, the node wins —
otherwise the capability list is documentation rather than a control.

**`deploy-target` is not a peer of the others**, and the brief treats it as
one. A deploy target is a `docker-host` plus a way for traffic to reach it, and
"can traffic reach it" is a property of where the node sits, not a toggle
somebody sets. Model it as a capability that *implies* `docker-host`, with a
separate reported field for routing:

```jsonc
"routing": { "public_ip": true, "tailscale": "node.tail1234.ts.net",
             "wildcard": "*.preview.example.com" }
```

The operator toggles "may host deployments"; the agent reports which of the
three ways out it actually has, and the controller picks one. A toggle that
promises reachability the node does not have is a promise the GUI cannot keep.

**`actions-runner` is not a job type**, and lumping it with the others will
bend the scheduler. A GitHub Actions runner is a daemon that takes work from
GitHub, not work the controller places. Split the model in two:

- **capabilities** — what the scheduler may place jobs against
  (`docker-host`, `package-build`, `deploy-target`)
- **services** — what the controller installs and supervises on a node
  (`actions-runner`, and later anything else long-lived)

Same screen, same enrollment, different lifecycle. The runner's labels then
become a per-node field, which is worth having anyway: today they are one
environment variable for one machine.

### Job

```jsonc
{
  "id": "j_0192",
  "type": "compose | build | exec | deploy",
  "project": "MediaReducer",
  "placement": { "node": "n_7f3a91" },     // or { "select": {...} }
  "source": { "kind": "snapshot", "digest": "sha256:…", "ref": "main@e1615f5" },
  "spec": { "steps": [ … ], "env": {…}, "timeout": 3600 },
  "outputs": ["dist/**"],
  "state": "queued | assigned | running | succeeded | failed | canceled",
  "times": { "queued": …, "started": …, "ended": … },
  "node": "n_7f3a91",            // where it actually ran
  "exit": 0,
  "artifacts": [ { "path": "dist/app-0.4.0.apk", "size": 24000000,
                   "digest": "sha256:…" } ]
}
```

Placement is either an explicit node or a selector — `{"capability":
"package-build", "labels": {"arch": "arm64"}}` — resolved at assignment time
and then frozen, so a job's history says where it ran rather than where it
might have.

**Do not build a scheduler.** The queue is a list, one job at a time per node
up to that node's concurrency, first in first out, and that is the whole of it.
No priorities, no preemption, no bin-packing, no fair-share. A single operator
pressing buttons does not generate contention worth an algorithm, and every one
of those features is a thing to debug at 1am. If two jobs ever queue behind
each other and it matters, raise concurrency.

### Where this lives

Nodes, jobs, job logs and artifact records go in **SQLite**, not in the JSON
files the notebook uses.

That reverses an earlier decision, so here is why it does not contradict it.
The notebook is small, whole-file, human-edited and hand-inspectable, and the
flock fix made concurrent writers safe — JSON is right for it. Jobs are the
opposite shape: append-heavy, written from several threads, queried by state
and by node, with log chunks arriving continuously and a retention policy. That
is a database's job, and doing it in JSON means rewriting a growing file on
every log flush.

Keep the notebook where it is. One new file, `/config/builderbot.db`, holding
nodes, jobs, logs, artifacts and enrollment tokens. Python ships SQLite, so the
dependency-free rule is intact.

## 2. Transport and enrollment

### Agent, dialing out — with one honest catch

The brief's instinct is right, and for the stated reason: a node that dials out
works identically whether it is a VM on the same server, a laptop on the LAN or
an instance in a cloud, and none of them need an inbound port. Adding a cloud
node then costs no new code path, which is the actual goal.

Three further arguments for it that the brief does not make:

- **Liveness is free.** A held connection tells you the node is up. With ssh
  you learn a node is down by trying to use it, which is exactly when you
  cannot afford to find out.
- **The credential moves to the node.** Today the controller holds a private
  key that can run anything as `bb` on the VM. With enrollment, each node holds
  its own token and the controller holds nothing that lets it log in.
- **One channel carries everything** — job assignment, log lines, source
  snapshots, artifact uploads — so there is one thing to authenticate, one
  thing to reconnect, and one thing to instrument.

**The catch, which must be said plainly: dialing out solves NAT at the node and
moves it to the controller.** For a cloud node to reach BuilderBot, BuilderBot
must be reachable — a forwarded port, a tunnel, or Tailscale. For LAN nodes
nothing changes. This is the one place the architecture cannot be neutral about
where things are, and it is worth deciding early: either the controller gets a
public endpoint (with TLS in front of it), or cloud nodes join over Tailscale
and the "no VPN required" property applies only to LAN nodes.

### Should it be ssh-first instead?

For this deployment, ssh-first is a defensible answer, and it is worth stating
the case rather than dismissing it:

- Nothing to install on the node beyond a shell and Docker.
- Cloud instances almost always have public IPs, so the NAT problem the agent
  solves does not arise for them; the ones behind NAT are home machines, which
  are on the same LAN as the controller anyway.
- No new protocol, no reconnection logic, no version skew between controller
  and agent.

And the case against, which is why the recommendation is the agent:

- Every remote operation becomes "shell out to ssh and parse", which is the
  thing that has already produced most of the Docker manager's sharp edges.
- Streaming a build's output, uploading artifacts and reporting liveness are
  three more ssh invocations, each with its own timeout and failure mode.
- The controller holds a key that is root-equivalent on every node.
- Version skew still exists; it is just implicit in "which coreutils does this
  distro have".

**Recommendation: agent for the runtime channel, ssh for bootstrap only** —
exactly as the brief proposes. Keep the existing ssh path alive as `kind: ssh`
during migration so the sandbox VM keeps working before it has an agent.

### The protocol, and where the brief over-specifies

**Not gRPC.** It brings protobuf, a code generator and a runtime dependency to
a project whose dashboard is deliberately stdlib-only. The benefit — typed
streaming — is not worth that here.

**Not WebSocket first, either, and this is the recommendation I expect
disagreement on.** `server.py` can *relay* a websocket (it does, to ttyd) but
does not *implement* one; adding it means hand-writing RFC 6455 framing,
masking, ping/pong and close semantics, and then living with it. What the agent
actually needs is: get work, stream logs, upload files, say I am alive. Plain
HTTP does all four:

```
GET  /api/agent/work?node=n_…      long-poll, 30s, returns a job or 204
POST /api/agent/log?job=j_…        chunked appends while it runs
POST /api/agent/result?job=j_…     terminal state + exit code
POST /api/agent/artifact?job=j_…   the file, content-addressed
GET  /api/agent/source?digest=…    the workspace snapshot
POST /api/agent/hello              census + capabilities, on connect
```

Long-poll gives sub-second job pickup, works through every proxy, needs no new
protocol, and each held request is one thread on a `ThreadingHTTPServer` —
fine for the number of nodes a homelab has, and a real ceiling worth knowing
(a hundred nodes would want the websocket). Start here; the endpoints above are
the same ones a websocket would carry as message types, so moving later is a
transport change and not a redesign.

**Not mTLS at first.** A CA, certificate issuance, rotation and revocation is a
lot of machinery for a network where the operator can re-enroll a node in
thirty seconds. Use:

1. Operator presses **Add node**; the controller mints a one-time enrollment
   token (short-lived, single-use, scoped to intended capabilities).
2. The provisioner runs on the node with that token; the agent posts it once
   and receives a **node token** (32 random bytes) plus its node id, both
   written to `/etc/builderbot/node.json`, mode 0600.
3. Every later request carries the node token as a bearer credential over TLS.
4. Rotation and revocation are rows in a table: revoke a token, the node fails
   its next call and shows as offline with "credential revoked".

TLS is not optional in this scheme, since the token is a bearer credential — on
a LAN that can be a self-signed certificate pinned by the agent at enrollment,
which is where the design leaves room for mTLS later without needing it now.

### Tailscale

Optional, exactly as the brief says: a way for the controller to be reachable
by a cloud node without a public port, and a way for the operator to reach a
node's own services. Nothing in the model may require it — a node on the LAN
must enroll with an IP and no overlay at all. Where it earns its place is
**Funnel for preview environments** (below), which is genuinely the cheapest
way to show somebody a running app.

## 3. Workspace and artifacts

**The instinct in the brief is right, and network-mounting `/workspace` onto
nodes is the wrong design.** Four reasons, in order of how much they cost:

1. **Build tools do pathological IO.** Gradle, npm and cargo do tens of
   thousands of small stats and opens. Over NFS or SMB that is not "a bit
   slower", it is minutes-to-hours slower, and it is the single most common
   reason people abandon network-mounted build trees.
2. **It couples build correctness to node liveness.** A dropped mount
   mid-build gives half-written outputs in the *source* tree, on the
   controller, where the operator's uncommitted work lives.
3. **Concurrency has no answer.** Two nodes building one project write the
   same `build/` directory. Every build system assumes it owns its output
   directory.
4. **Blast radius.** A container on a cloud node would have a writable path
   into every project on the server. The sandbox VM exists precisely to keep
   that from being true.

### What `/workspace` means in the new model

- **On the controller: unchanged, and canonical.** The projects share, mounted
  whole, holding every project including uncommitted work. Sessions run here,
  the notebook is about these directories, `bb` works exactly as it does today.
  It is the source of truth and the only writable copy.
- **On a node: nothing permanent.** A job gets
  `/var/lib/builderbot/jobs/<job-id>/workspace`, materialized before the first
  step and deleted after — with a retention window (say, keep the last failed
  job per project) so a failure can be looked at.
- **The GUI's node browser reads that path**, read-only, for debugging. A
  viewing mechanism, as the brief says. It must never be the execution
  mechanism, and the agent should expose it as "list/read under this job's
  directory" rather than as a filesystem.

### Materializing a job's source

Three strategies, and the order matters for this operator specifically:

1. **Dirty-tree snapshot (the default).** Most work here is uncommitted — the
   whole point of the box is a session editing a tree — so "clone the commit"
   would be wrong most of the time. The controller tars the working tree minus
   `.gitignore`d paths and `.git`, hashes it, and serves it by digest; the node
   caches by digest, so re-running a job with unchanged source transfers
   nothing.
2. **Git ref**, when the job is against a commit (a CI-shaped build, a
   reproducible release): the node clones or fetches from the project's remote,
   or from the controller acting as a dumb git server. Cheapest for large
   histories, and reproducible by construction.
3. **Delta sync**, later: rsync-style over the agent channel, keyed on the
   previous snapshot's digest. This is the optimization that makes a 2GB tree
   tolerable, and it is not needed on day one.

### Caches are the whole cost of this approach, so treat them as first class

Per node, persistent, never job-scoped:

```
/var/lib/builderbot/cache/<project>/gradle      → mounted at ~/.gradle
/var/lib/builderbot/cache/<project>/npm         → ~/.npm
/var/lib/builderbot/cache/shared/android-sdk    → the SDK, once per node
```

Docker layer cache is the node's own daemon and needs nothing. For cross-node
image builds, buildx `--cache-to/--cache-from` against a registry is the
answer, and it is worth deferring until there is a second builder.

Two rules that keep this honest: a cache is **never** an input to correctness
(a job must produce the same result on a cold node), and the GUI shows cache
size per node with a button to drop it, because the first thing that goes wrong
with caches is that they fill a disk.

### Artifacts

The job declares outputs as globs; the agent uploads them on success,
content-addressed; the controller stores them and the Artifacts tab lists them
with the version stamp that is already the convention. This is a real
improvement over today, where `dist/` is whatever happens to be on the one box.

## 4. Deploy targets and preview environments

A deployment is a long-lived job on a node with `deploy-target`: compose up,
plus a route. The mechanism that must be uniform is the *record*, not the
implementation:

```jsonc
{ "id": "d_04", "project": "…", "node": "n_…", "compose": "…",
  "route": { "mode": "public | funnel | lan", "url": "https://…", "port": 8080 },
  "state": "up | down | failed" }
```

Three modes, in the order they are worth building:

1. **`lan`** — publish a port, show `http://<node-ip>:<port>`. This is what the
   Docker manager already does, and for a homelab it is most of the value.
2. **`funnel`** — Tailscale Funnel on the node gives a public HTTPS URL with no
   DNS, no certificate and no inbound firewall change. For *"spin up an
   instance to show someone"*, this is the answer, and it is a two-line agent
   implementation.
3. **`public`** — a reverse proxy (Caddy, for ACME with no configuration) on a
   node with a public IP and a wildcard DNS record, giving
   `<project>-<deploy>.preview.example.com`. This is the one that needs a
   domain, a DNS provider and a certificate story.

**Flag: mode 3 is the most over-engineered item in the brief** relative to what
it buys a single operator. Build 1 and 2; leave 3 as a record shape that a
later phase can fill in, and do not build a proxy layer in the controller —
the traffic never goes through the controller, which is the property that makes
this cheap.

## 5. Configuration and migration

`DOCKER_HOST` and `DOCKER_HOST_PATHS` leave `.env` and become node fields. The
migration must be automatic and reversible-in-effect:

1. On first boot after the upgrade, if `DOCKER_HOST` is set and no node exists
   with that address, create one: `kind: ssh`, name `sandbox`, capabilities
   `[docker-host]`, labels from what the daemon reports. Log a line saying it
   happened.
2. The env var keeps working for one release, and the Nodes screen shows the
   node as **"from DOCKER_HOST — this setting is going away"** with a button to
   adopt it permanently.
3. After that release, the variable is read once at boot for migration and
   otherwise ignored; then it goes from `.env.example`,
   `docker-compose.yml`, `unraid/builderbot.xml`, the README reference and
   `docs/unraid.md` — the five-places rule, all in one change.

**Tools → Nodes** is the screen: a row per node with state, capabilities as
toggles, labels, concurrency, last seen, and the buttons — Enroll, Test, Drain,
Remove. Drain means "finish what you are running, accept nothing new", and it
is the button that makes a node safe to reboot.

## 6. Provisioning

One script, `vm/provision.sh` grown up:

- Detect with `/etc/os-release`; abstract the package manager over
  `apt|dnf|pacman|zypper|apk` behind `pkg_install()`. Everything else in the
  script is already distro-neutral.
- Install Docker **only** if the docker capability was requested. A
  package-build node needs a JDK and the Android SDK, not a daemon.
- Install the agent, enable it as a systemd unit, enroll with the one-time
  token, and print the node id.
- Idempotent: every step checks before acting, which the current script already
  does and is the reason it can be re-run.

**On the "static agent binary".** A Go binary is genuinely the right answer for
"as many distros as reasonable" — one file, no runtime, cross-compiled in CI.
But it puts a second language and a second build pipeline into a project that
is Python and bash, and the agent's whole job is HTTP plus subprocess plus
tar. Every distro in that list ships Python 3.9+ in its base repos.

**Recommendation: a single-file Python agent using only the standard library**,
installed as `/usr/local/lib/builderbot/agent.py` with a systemd unit. It
matches the house style, it is readable by the person maintaining it, and it
can be replaced by a Go binary later without changing the protocol — which is
the property that makes deferring safe. Revisit if a target host turns up
without python3.

## 7. UI changes

- **Docker manager**: a node selector listing every `docker-host` node, online
  or not, with the per-node last-known container list already built for the
  offline case. Selecting a node switches the view; the row's greyed-out state
  and "state unknown" language is exactly what an offline node's cached view
  should say.
- **Project settings**: which node runs Actions, which compiles packages —
  each either a node or a selector ("any node with `package-build`").
- **Send artifact to Docker**: node picker, defaulting to the project's
  configured node.
- **Jobs**: a new tab. There is no view of "what is running" today because
  there was only ever one thing; with nodes there needs to be one, with the log
  tail that the dev-instance row already renders.

## 8. Phased roadmap

Each phase leaves a working system, and each is independently useful.

**Phase 1 — the node abstraction, with `local` as the only node.**
A `nodes` module, the SQLite store, and a node record for the controller
itself. Everything that runs work asks for a node and always gets `local`.
`DOCKER_HOST`, if set, migrates into an `ssh` node. No UI yet beyond a
read-only list. Nothing changes for the operator; the seam exists.

**Phase 2 — Tools → Nodes, and multiple Docker nodes over ssh.**
CRUD, capability toggles, labels, test-connection, drain, remove. The Docker
manager gains its node selector and per-node caches. The sandbox VM becomes an
ordinary node. This phase alone delivers "more than one Docker host", which is
most of the immediate value, with no agent written.

**Phase 3 — the agent and enrollment.**
One-time tokens, `POST /api/agent/hello`, long-poll for work, heartbeat, node
census. The provisioner installs it. Job type `exec` only — enough to prove the
channel end to end. Nodes may be `agent` or `ssh`; both work.

**Phase 4 — jobs and the queue.**
The job model, placement by node or selector, streaming logs, concurrency,
cancel and drain. Move the Docker manager's compose actions onto it, so
"rebuild" is a job with a log rather than a module global. The Jobs tab.

**Phase 5 — workspace materialization, caches and artifacts.**
Dirty-tree snapshots, per-node caches, artifact upload, the read-only node
browser. `package-build` becomes real: an APK compiles on another machine and
lands in the Artifacts tab.

**Phase 6 — services: the Actions runner as a per-node managed service**,
with per-node labels, install/remove from the Nodes screen.

**Phase 7 — deploy targets**, modes `lan` and `funnel`, with `public` left as
a record shape.

Phases 1 and 2 are worth doing even if the rest never happens. Phase 3 is the
one that changes the shape of the project, and is where to stop and reassess.

## 9. What is over-engineered for this box

Said plainly, because a homelab tool that grows a distributed systems paper is
a tool nobody maintains:

- **mTLS with a CA.** Bearer tokens over TLS, revocable in a table. Revisit if
  a node ever lives somewhere untrusted.
- **gRPC.** Protobuf and a code generator for six endpoints.
- **A real scheduler.** Priorities, preemption, fair share, bin-packing: none
  of it. FIFO per node with a concurrency limit.
- **Wildcard DNS + ACME preview URLs.** Tailscale Funnel does the job for one
  person showing another person a demo.
- **A global content-addressed cache service.** Per-node directories keyed by
  project, with a size readout and a clear button.
- **Cloud provider integration.** Creating instances via AWS/Azure/GCP APIs is
  a different product. Enroll an instance you made; the enrollment path does
  not care who made it.
- **RBAC, multi-tenancy, audit logs.** One operator.
- **Node auto-discovery.** Typing an address once is not the bottleneck.

And one caution rather than a cut: **the `local` node is not a sandbox.** Jobs
placed on it run inside the controller container, which holds `/config`, the
dashboard credential and every project's source. That is already true of builds
today, so it is not a regression — but `docker-host` on `local` should stay off
unless a socket is deliberately mounted, and the Nodes screen should say what
`local` means rather than presenting it as one node among equals.

## 10. Open questions

1. **Controller reachability.** Public endpoint, or Tailscale for off-LAN
   nodes? This decides whether "cloud node" means "any cloud node" or "one that
   can reach my house".
2. **Is `package-build` worth a node at all?** The controller already has the
   Android SDK and the toolchains. A second build machine earns its place when
   it is faster than this box or when builds must stop competing with sessions
   — otherwise phase 5 is a lot of machinery for a slower build.
3. **What happens to a session's `docker`?** Today `DOCKER_HOST` is in every
   session's environment, so `docker ps` in a terminal reaches the VM. With
   several nodes, does a session get the project's default node, or nothing at
   all and everything through `bb`?
4. **Retention.** How long do job logs, artifacts and failed workspaces live?
   This is the only part of the design that grows without bound.
