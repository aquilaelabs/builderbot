# Controller and nodes — a design

BuilderBot today is one container with one remote Docker daemon hard-coded into
an environment variable. This describes turning it into a **controller** that
schedules work onto **nodes**, where the controller is itself a node, and where
a node is any registered host — a VM on the same server, a spare desktop, a
cloud instance — that can execute something.

Second pass. The first version of this document optimized for one operator and
cut everything an organization would need. The brief has since widened: **the
same system has to be usable in a homelab and scalable to enterprise use.**
That changes the design less than it changes the discipline — most of what it
adds is interfaces where the first pass had cuts — but it changes some real
decisions too, and those are marked.

It is a design document, not a plan of record. Where it disagrees with the
brief that prompted it, the disagreement is stated with its reason.

## 0. Two deployments, one system

The tension to design around, stated plainly: a homelab wants one container
that works with zero configuration, and an enterprise wants SSO, audit,
hundreds of nodes, Postgres and a security review. The classic failure is to
serve the second by drowning the first — a config surface so wide that the
single-operator install needs a consultant. The second classic failure is two
code paths, where "enterprise mode" is a fork wearing a flag.

Four rules prevent both, and every section below is written against them:

1. **One data model, one protocol, one API — at every scale.** A homelab node
   and a fleet node enroll the same way, run the same jobs, and speak the same
   wire format. Enterprise never gets a different *kind* of node; it gets more
   of them. (This is the brief's own rule for cloud vs. private nodes, applied
   to everything.)
2. **The homelab is the default, and the default is one decision.** One
   container, SQLite, one operator, and one node enrolled with one command —
   the sandbox VM the Docker manager already needs. Everything else is
   defaulted. Enterprise is *configuration*: Postgres instead of SQLite, OIDC
   instead of one password, approval instead of auto-approval. Config, never
   a fork. (This rule used to say "the local node — nothing to set"; §18 says
   why the local node stopped being a place work runs.)
3. **Enterprise features are additive planes, not modifications.** Audit is a
   table every mutation writes; RBAC is a check in front of the same handlers;
   metrics are a read-only endpoint. If a feature needs the core to behave
   differently per tier, the core is wrong.
4. **Build interfaces now, implementations when somebody needs them.** An
   unnamed enterprise customer is a speculation, and speculative code rots.
   What is cheap now and impossible to retrofit honestly — identity on every
   mutation, an audit row, IDs that never assume one tenant, SQL that runs on
   two databases — goes in from day one. What is expensive — SSO, quotas,
   HA — waits for a requirement with a name on it.

One honest caution before the details: "enterprise-ready" is a direction, not
a checkbox, and this document deliberately does not promise compliance
regimes, active/active HA, or a support organization. It promises a core that
does not have to be rewritten when those conversations start.

## 1. What exists now, honestly

Worth writing down, because most of it survives and the parts that do not are
the parts that decide the phasing.

- `DOCKER_HOST` names one sandbox VM, addressed over ssh, verified by a
  `builderbot.sandbox` label the provisioner writes. (This section is the
  *before*: the variable is gone and the VM is an enrolled node — §11.) Everything the Docker
  manager does is `docker compose --project-name …` plus three whitelisted
  one-shot `docker run` shapes, and a guard rebuilds each argv and compares it
  whole.
- Work is not scheduled. There is one job at a time in `devapp.py` (`_job`, a
  module global) and another in `packages.py`. Nothing queues, nothing is
  placed, nothing retries.
- `/workspace` is a mounted share holding every project. Sessions, builds, the
  Actions runner and the emulator all run in the controller container against
  that one tree.
- State is JSON files under `/config` with an flock around read-modify-write
  (`statefile.py`) — chosen over SQLite deliberately, for data that is small,
  human-edited and read whole.
- The GitHub Actions runner runs **in this container**, registered at the org
  level with fixed labels.
- The dashboard's server is stdlib-only Python on `ThreadingHTTPServer`, one
  thread per open request. It can *relay* a websocket (it does, to ttyd) but
  does not implement one.

So the machine already does five jobs: dashboard, session host, build box,
Actions runner, and Docker client. The node model is what lets four of those
five be somewhere else — and, at the other end of the scale, be a hundred
somewhere-elses.

## 2. The data model

### Node

```jsonc
{
  "id": "n_7f3a91",            // generated at enrollment, never reused
  "name": "sandbox",           // display only, renameable
  "kind": "local | agent | ssh",
  "created": 1756700000,
  "pool": "default",           // grouping; homelab never touches it
  "agent": {                   // kind=agent
    "version": "0.4.0",
    "token_id": "t_12",        // which credential it authenticates with
    "last_seen": 1756700123,
    "addr": "10.0.0.9"         // as seen by the controller, informational
  },
  "ssh": { "addr": "ssh://bb@10.0.0.9" },   // kind=ssh, bootstrap or legacy
  "capabilities": ["docker-host", "package-build"],
  "services": { "actions-runner": { "labels": "builderbot,linux,x64" } },
  "labels": { "arch": "amd64", "os": "debian12", "gpu": "none",
              "disposable": "true" },
  "concurrency": 1,
  "state": "pending | online | offline | draining | retired",
  "reported": {                // the agent's own census, refreshed on connect
    "cpu": 8, "mem_mb": 16000,
    "docker": "27.3.1", "gpu": "nvidia GeForce RTX 3070 Ti",
    "toolchains": { "java": "21", "android-sdk": "35.0.2", "flutter": null },
    "stores": {                // each ROLE's location and headroom, see §6
      "packages": { "path": "/var/lib/builderbot/toolchains", "free_mb": 118000 },
      "data":     { "path": "/appdata",                       "free_mb": 800000 },
      "cache":    { "path": "/var/lib/builderbot/cache",      "free_mb": 118000 }
    }
  },
  "routing": { "public_ip": false, "tailscale": "", "wildcard": "" }
}
```

Points worth arguing about:

**The id is the node's, not the address's.** Generated at enrollment, written
to `/etc/builderbot/node.json` on the node, and used as the key for everything
the controller remembers about it — caches, last-known container lists, build
records. An address is not an identity: two VMs can wear one IP, and one VM
changes address when it moves. The Docker manager already learned this the
hard way. A re-provisioned machine enrolls as a *new* node; the GUI offers
"adopt as `<old node>`" to keep history, rather than guessing.

**Capabilities are node-side facts, not controller-side claims.** The
controller stores what a node reported; the agent refuses a job whose
capability it does not hold. If the two disagree, the node wins — otherwise
the capability list is documentation rather than a control. This is also the
enterprise story in miniature: enforcement lives at the resource, so a
compromised or misconfigured controller cannot make a node into something it
was not enrolled to be.

*Amended 2 September, by the operator:* **capabilities stopped being a
setting.** A node is not "for" docker or for building; a project names ONE
node and that node does everything the project needs, so nobody is asked
which. Every node enrols with the full set, and what a project can actually
DO on its node is what is INSTALLED there — the census's `toolchains`, which
the node's row now shows in place of the toggles, and which the Tools tab
adds to. Three projects on three VMs keeps them apart; three projects on one
VM shares it; the choice is the project's node, and nothing else.

The paragraph above still stands as the *mechanism*: the field, the wire, and
the agent's refusal are untouched (§15 door 7 — retrofitting node-side
enforcement onto a deployed fleet means re-enrolling all of it, which is why
it was built before it was needed). A deliberately restricted node remains
expressible through the API; it is simply not something anyone has to
configure to get ordinary work done. Two things are unchanged and stay
gated on facts rather than toggles: `system` jobs are offered only to a node
whose census says it carries `bb-sandbox`, and `local` — the controller's
own record, which is registry plumbing rather than a row on the tab
itself — is never given `docker-host`, because containers there would run
beside `/config` and the dashboard credential (§12).

**`deploy-target` is not a peer of the others**, and the brief treats it as
one. A deploy target is a `docker-host` plus a way for traffic to reach it,
and "can traffic reach it" is a property of where the node sits, not a toggle
somebody sets. The operator toggles "may host deployments"; the agent reports
which ways out it actually has (`routing`), and the controller picks one. A
toggle that promises reachability the node does not have is a promise the GUI
cannot keep.

**`actions-runner` is not a job type**, and lumping it with the others will
bend the scheduler. A GitHub Actions runner is a daemon that takes work from
GitHub, not work the controller places. So the model splits in two:

- **capabilities** — what the scheduler may place jobs against
  (`docker-host`, `package-build`, `deploy-target`)
- **services** — long-lived things the controller installs and supervises on
  a node (`actions-runner` first; anything else later)

Same screen, same enrollment, different lifecycle. Runner labels become a
per-node field — which an org wants anyway, because "the arm64 runners" is a
sentence they will say.

**A GPU node hosting Android emulation lands on this split too, and mostly on
the job side.** The controller runs an emulator today because a session drives
it interactively; a *node* with a GPU is more useful the other way around: an
instrumented-test job ships to the node, the agent boots the emulator
job-scoped (the same lifecycle as a workspace — up for the job, down after),
runs the tests against it locally, and the results come back as artifacts.
That path needs no network adb, no port forwarding and no new transport — it
is an ordinary `package-build`-shaped job on a node whose census reports a
GPU and an android-sdk. The interactive case — a session on the controller
holding `adb` open to an emulator elsewhere — is a `device-host` **service**
(long-lived, like the runner), reached over network adb, and it is the fragile
half: worth designing the record for, not worth building first. The GPU
display arrangement the controller already carries (a headless Xorg so EGL
answers, with the bounded restart watch) becomes something the provisioner
can install on a GPU node, which is all "GPU acceleration on a node" turns
out to mean.

**`pool` exists from day one and the homelab never sees it.** A pool is a
named group of nodes ("default" unless set). It costs one column now. It is
the seam that later carries the enterprise asks — this team's nodes, quotas
per pool, RBAC per pool — none of which are built now, all of which are
retrofits onto *queries* rather than onto the model if the column exists, and
schema surgery if it does not.

### Job

```jsonc
{
  "id": "j_0192",
  "type": "compose | build | exec | deploy | service",
  "project": "MediaReducer",
  "requested_by": "operator",              // a principal, see §8
  "placement": { "node": "n_7f3a91" },     // or { "select": { "capability": "…",
                                           //      "labels": {…}, "pool": "…" } }
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

Placement is an explicit node or a selector, resolved at assignment time and
then frozen, so a job's history says where it ran rather than where it might
have.

**The queue is a list; placement is a function.** One job at a time per node up
to that node's concurrency, first in first out. No priorities, no preemption,
no bin-packing — a single operator does not generate contention worth an
algorithm. The enterprise concession is *shape*, not features: placement is one
pure function `pick(job, nodes) -> node`, called in one place, so
fair-share-per-pool or quota checks are one function swapped later rather than
logic scraped out of four call sites. Until someone needs that, the function is
ten lines.

**This is not a CI engine, and enterprise pressure will try to make it one.**
No workflow DSL, no step graph, no matrix builds, no plugin marketplace. The
Actions runner *service* exists precisely so that pipeline-shaped work goes to
a pipeline product; this system runs jobs a person (or a session) asked for.
The moment a job spec grows `needs:` it has gone wrong.

## 3. API first

New in this pass, and load-bearing for both tiers: **everything is a versioned
HTTP API (`/api/v1/…`), and the GUI is a client of it.** The homelab reason is
`bb` — the CLI should hit the same endpoints the page does, which is already
half true today and should become a rule. The enterprise reason is that
integration *is* the product there: Terraform enrolling nodes, a bot draining
one before patch night, dashboards reading `/metrics`. An API that is "whatever
the GUI happens to POST" cannot be documented, versioned or secured.

Practically: the endpoints the dashboard already has migrate under `/api/v1`
with their shapes written down; new node/job endpoints start there. Version
bumps are additive; `v1` never changes meaning under a client.

## 4. Transport and enrollment

### Agent, dialing out — with one honest catch

The brief's instinct is right, and for the stated reason: a node that dials out
works identically whether it is a VM on the same server, a laptop on the LAN or
an instance in a cloud, and none of them need an inbound port. Adding a cloud
node then costs no new code path, which is the actual goal.

Three further arguments the brief does not make:

- **Liveness is free.** A held connection tells you the node is up. With ssh
  you learn a node is down by trying to use it, which is exactly when you
  cannot afford to find out.
- **The credential moves to the node.** Today the controller holds a private
  key that can run anything as `bb` on the VM. With enrollment, each node holds
  its own token and the controller holds nothing that logs in anywhere.
- **One channel carries everything** — job assignment, log lines, source
  snapshots, artifact uploads — so there is one thing to authenticate, one
  thing to reconnect, and one thing to instrument.

**The catch, which must be said plainly: dialing out solves NAT at the node
and moves it to the controller.** For a cloud node to reach BuilderBot,
BuilderBot must be reachable — a forwarded port with TLS in front of it, a
tunnel, or Tailscale. For LAN nodes nothing changes. In the enterprise
deployment this is a non-issue (the controller lives on a network the fleet
can reach, behind a normal load balancer); in the homelab it is the first
question to answer before enrolling anything off-LAN.

**Why not ssh-first:** every remote operation becomes "shell out and parse",
which is where most of the Docker manager's sharp edges came from; streaming
logs, artifact upload and liveness are three more invocations with three
failure modes; and the controller holds a key that is root-equivalent on every
node — a model that fails every enterprise review on arrival. ssh remains for
bootstrap only, and `kind: ssh` nodes keep the current arrangement working
through the migration.

### The protocol: semantics first, transport negotiated

The agent needs six verbs, and they are the protocol; how bytes move is an
implementation detail that *will* change with scale, so it is designed to:

```
POST /api/v1/agent/hello               census + capabilities, on connect
POST /api/v1/agent/work                long-poll, 25s, returns a job or 204
POST /api/v1/agent/log                 chunked appends while it runs, by sequence
POST /api/v1/agent/result              terminal state + exit code
POST /api/v1/agent/artifact            the file, content-addressed        (phase 6)
GET  /api/v1/agent/source?digest=…     the workspace snapshot              (phase 6)
```

Plus two the list above does not count: `POST /api/v1/agent/enroll`, spoken
once, and `GET /api/v1/agent/download`, which serves the agent file itself.
The node is named by its bearer token, never by a query parameter, so `work`
takes no `?node=`. It is a POST because the heartbeat rides it: every poll
carries a sample (CPU, memory, load, per-store free space, jobs running), so
liveness and the numbers cost no verb of their own and a node is "live" when
a poll has arrived within three poll lengths. The four the agent speaks
today, and the two it does not yet, are marked; the agent takes `exec` jobs
and `self-update`, nothing else, until phase 6 gives it a workspace to build
in.

*Driving the self-update (after phase 9):* nothing does it unasked. The node
list carries the digest and version this controller ships, the row compares
its node's against them and says *update available*, and the **Update
agent** button queues the `self-update` job with that digest in its spec —
so a node is never handed a file other than the one this controller serves.
`provision.sh` re-run on an enrolled node is the console path to the same
swap, with the node's own token. The agent's `hello` after re-exec is what
moves the row.

*And an agent that is behind takes nothing but its own update.* A controller
is always newer than or equal to its nodes — it is where the agent file comes
from — so a digest mismatch means the node may not understand a job this
version would send it. Job types and spec fields have been added on nearly
every phase (`system`, `package`, `cache-clear`, compose plans, `bb` verbs,
store listings), and an older agent meets an unknown one with a shrug rather
than an error, which is the worst of the three possible answers. So
`job_add` refuses and `fits` declines every job whose runner is the node,
`self-update` excepted; the Nodes tab and the Tools tab ghost the buttons and
say why before the press. It is one rule in `nodes.agent_stale` and the UI
only mirrors it.

*Compose moved to the agent (2 Sep, roadmap #18):* a node enrolled with a
token needed an ssh key on top of it, because `runner_of` kept compose on the
controller and it reached the node's daemon over ssh. It does not any more.
The controller still decides WHAT — the env gate, the risk gate, the records,
what `built_rev` becomes — and sends the agent an ordered PLAN for one action
(`up`, `down`, `rebuild`, `remove`) with the compose file and the instance's
env beside it; the agent writes those into a directory of its own under the
data store, makes the bind directories itself rather than through a throwaway
container, runs each step with the node's own docker, and reports how far it
got. `devapp.compose_done` applies the records from that result, and only for
a plan the agent ran — the controller's runner does its bookkeeping inline,
and running both undid the env gate. A node with no agent (the legacy `ssh`
kind) still takes the old path, until that kind goes. The wire gained one
thing for it: a log post may carry `step`, so the row still shows the word.

*What phase 4 added to the wire (protocol 2):* `hello` carries `running`,
the job ids the agent still has in flight, so the controller can reconcile
its rows against the node's truth after either side restarts. `work` may
answer `{"cancel": [ids]}` instead of a job, and the reply to a `log` post
carries `cancel: true` — the two ways a cancel reaches a busy agent, neither
of which names a signal (door 9). `result` carries `error`, one line on how
it ended, and the state may be `canceled`. The 3-second busy poll the phase 3
agent used as a stopgap is gone: a poll is held for its full length, and the
queue wakes it when a job ends on the node, so the next one starts at once.

**What a job runs as.** The unit runs the agent as root — that is what lets
phase 5's system jobs (mounts, network) exist — but an `exec` job drops to
the account the provisioner enrolled, the same `bb` that docker runs as,
before it runs anything. A session reaching a node through a job has the
reach it already had over ssh, and no more.

**Ship long-poll first.** It gives sub-second job pickup, crosses every proxy
and NAT, and needs no new protocol machinery in a stdlib-only server. Each
held poll is one thread on `ThreadingHTTPServer`, and that is the honest
ceiling: **on the order of 50–100 connected agents** before thread count and
the GIL make it silly. That covers every homelab and a pilot deployment.

**The enterprise path is a transport swap, not a redesign.** The `hello`
response carries `"transports": ["longpoll", "websocket"]`; an agent uses the
best both sides speak. When a deployment outgrows the thread-per-poll model,
the controller grows an async front end (or a small separate gateway process
that terminates agent connections and forwards to the same handlers) speaking
websocket to the same six verbs as message types. Agents do not change first;
protocol version and transport are negotiated independently. This is the
concrete meaning of rule 1: the wire format scales by swapping the listener,
never by forking the agent.

**Not gRPC**, at either tier. It brings protobuf and a code generator to a
stdlib-only project, and its benefit — typed streaming — is not the missing
piece at 100 nodes; the listener model is.

### Enrollment, at both scales

1. **Add node** mints an enrollment token. Two kinds, one mechanism:
*Token lifetimes, stated because the two get confused:* the **enrollment**
token (`bbe_…`) is one use and one day — it exists to be pasted into a
terminal, and one minted and forgotten is a standing way in, so it is
revoked the moment enrollment succeeds. The **node** token (`bbn_…`) it
trades for has no expiry at all: it is `0600` on the node and works until
the operator revokes it or retires the node, so a node enrolled today is
still working a year from now with nothing to renew. (The runner
registration token is GitHub's and lives an hour; after registering, the
runner holds credentials GitHub issued to it and refreshes them itself.)
The row `expires` column and `revoke_tokens` are what a rotation policy
would use if a deployment ever wants one — the shape is there, unbuilt.

   - **single-use** (homelab default): scoped to intended capabilities,
     short-lived; enrolling with it *is* the approval.
   - **bulk** (enterprise, cloud-init/ASG): multi-use, longer-lived; nodes
     enrolling with it land in **`pending`** and appear in an approval queue.
     Auto-approval per token is a setting, so an org that trusts its image
     pipeline can have it.
2. The provisioner (or cloud-init) runs with the token; the agent posts it once
   and receives its **node id** and a **node token** (32 random bytes), both
   written to `/etc/builderbot/node.json`, mode 0600.
3. Every later request carries the node token as a bearer credential over TLS.
   TLS is not optional — the token is a bearer credential. On a LAN that can be
   a self-signed certificate pinned by the agent at enrollment.
4. Rotation and revocation are rows: revoke a token and the node's next call
   fails closed, showing offline with "credential revoked".

**mTLS is a later layer, not a redesign** — the pinned-cert enrollment above is
where a private CA slots in when a security review asks for it: same
enrollment flow, the token exchange returns a client cert instead of (or
beside) a bearer token. Design the seam; do not run a CA for three machines.

**Agents update themselves, because a fleet is unpatchable by hand.** The
agent reports its version in `hello`; the controller may answer any poll with
a `self-update` job (a capability-independent type), which downloads the
pinned new agent by digest, swaps the file and re-execs. In the homelab this
is a convenience; at fleet scale it is the difference between a protocol that
can evolve and one frozen by its oldest node.

**That version is `WINDOW.BUILD`, and only the first half is a promise.** The
window is BuilderBot's own semver minor: while the project is `0.4.x`, any
`0.4` agent works with any `0.4` controller, in both directions. `0.5.0` is
where that ends, and it is therefore where a breaking change to this protocol
and the removal of the compatibility paths carrying old ones belong. Inside a
window: add, do not change — a field gains a default rather than a new
meaning, a verb gains a sibling rather than a signature.

The build is the agent file's own counter and moves only when that file
moves, which is why it is not the project's patch number; most patches ship
no new agent. It does not reset at a boundary — `0.5.28` follows `0.4.27` —
so "which of these is newer" always has an answer.

A node whose agent is from another window is reported as such and not
refused: the Nodes tab separates *behind* (a newer build in the same window,
routine) from *out of window* (the promise was never made, update before
relying on it). Refusing would strand a node on a guess. The one thing an
out-of-window agent does stop is Claude sessions on the projects bound to
that node: the controller ends the running ones and ghosts each such
project's Claude button until the node is updated — per project, so a
project on a current node is untouched.

The CLAUDE.md environment block is in the same window. The template carries
a `BUILDERBOT:ENV:WINDOW` line under its begin marker, held to the project's
minor by the same test that holds the agent's, and a project's copy from
another window is treated the way an agent from one is: the block described
a different BuilderBot, so sessions on that project are ended and refused
until `bb claude-md --update` restamps it. A block merely behind inside the
window is drift — the row offers the update and nothing stops. The older `protocol`
integer, which both sides declared and neither ever compared, is superseded
by this and is removed at `0.5.0` — removing a field the other side may still
read being exactly the kind of break the window exists to schedule.

### Tailscale

Optional at every tier, exactly as the brief says: a way for the controller to
be reachable without a public port, and a way for the operator to reach a
node's own services. Nothing in the model may require it. Where it earns its
place is **Funnel for preview URLs** (§7) and controller reachability for a
homelab with off-LAN nodes.

## 5. Storage

**SQLite by default, Postgres by configuration.** Nodes, jobs, job logs,
artifacts, tokens, audit — all in one database, which is `/config/builderbot.db`
until somebody sets `DATABASE_URL`.

This reverses an earlier decision (the notebook chose flock'd JSON over
SQLite), and the reversal does not contradict it: the notebook is small,
whole-file, human-edited — JSON is right for it and it stays. Jobs are the
opposite shape: append-heavy, multi-writer, queried by state and node, with
log chunks arriving continuously and a retention policy. That is a database's
job.

The dual-database rule is the discipline, and it is cheap only if applied from
the first migration:

- SQL through one thin storage module; parameter style abstracted.
- No engine-specific features: JSON stored as TEXT and parsed app-side,
  integer epochs for time, no partial indexes the other engine lacks.
- Migrations as numbered files applied at boot, same files for both engines.
- Log chunks batched on write (the one place SQLite's write rate is a real
  limit) and pruned by the retention job.

This is the Gitea/Grafana pattern and it is well-trodden: the homelab never
learns Postgres exists; the enterprise gets real concurrency and a backup
story their DBAs already own — and it is the prerequisite for controller HA
(§10) rather than an optimization.

## 6. Workspace and artifacts

**The brief's instinct is right: network-mounting `/workspace` onto nodes is
the wrong design.** Four reasons, in order of cost: build tools do
pathological small-file IO and network filesystems turn minutes into hours; a
dropped mount mid-build corrupts state *in the source tree on the
controller*; two nodes building one project would share one `build/`
directory; and a container on a remote node would hold a writable path into
every project on the box — the thing the sandbox VM exists to prevent. At
enterprise scale every one of these gets worse, and the fourth becomes a
finding in somebody's report.

### What `/workspace` means in the new model

- **On the controller: unchanged, and canonical.** The projects share, mounted
  whole, holding every project including uncommitted work. Sessions run here;
  the notebook is about these directories; `bb` works exactly as today. It is
  the source of truth and the only writable copy.
- **On a node: nothing permanent.** A job gets
  `/var/lib/builderbot/jobs/<job-id>/workspace`, materialized before the first
  step and deleted after, with a retention window (keep the last failed job
  per project) so failures can be inspected.
- **The GUI's node browser reads that path**, read-only, for debugging — a
  viewing mechanism, never the execution mechanism. The agent exposes
  "list/read under this job's directory", not a filesystem.

### Materializing a job's source

1. **Dirty-tree snapshot (the default).** Most work here is uncommitted — the
   box exists for sessions editing trees — so "clone the commit" is wrong in
   the common case. The controller tars the working tree minus `.gitignore`d
   paths and `.git`, hashes it, serves it by digest; nodes cache by digest, so
   an unchanged tree transfers nothing.
2. **Git ref**, for commit-shaped work (release builds, anything that must be
   reproducible): the node fetches from the project's remote or from the
   controller acting as a dumb git server.
3. **Delta sync**, later, keyed on the previous snapshot's digest — the
   optimization that makes a 2GB tree tolerable over a WAN, not needed on day
   one.

### Caches are the whole cost of this approach

Per node, persistent, never job-scoped: `/var/lib/builderbot/cache/<project>/…`
mounted into the job for Gradle, npm and friends; the Android SDK once per
node; Docker layer cache is the node's own daemon. Cross-node image builds use
buildx `--cache-to/--cache-from` against a registry — the first genuinely
enterprise-flavored piece, and worth deferring until there is a second
builder.

Two rules keep caches honest at any scale: a cache is never an input to
correctness (a cold node must produce the same result), and the GUI shows
cache size per node with a button to drop it — because the first thing that
goes wrong with caches is a full disk, and at fleet scale the second thing is
"which of forty nodes has the poisoned one".

### Toolchains and the package store

Caches answered "how does a node avoid re-downloading what a build pulls";
this answers the question above it, which the plan had not: **how do the
toolchains themselves — a JDK, the Android SDK, Flutter — get onto a node at
all, and where do they live?** Today the answer is the controller's SDK share
and `bb sdk`, operator-gated; that has to generalize without forking.

- **One catalog, per-node state.** `config/packages.json` stays the single
  description of what is installable and how. What becomes per-node is the
  *state*: the census reports which toolchains a node has and at what version
  (`reported.toolchains`), probed by the agent the same way `bb sdk` probes
  locally. The controller never guesses from what it asked for; it reads what
  the node says it has.
- **Installing is a job.** A package install on a node is an ordinary job
  (`type: exec`, spec from the catalog) placed on that node, with the same
  logs, audit and one-at-a-time-per-node rule as everything else — which also
  keeps the existing gate: sessions cannot trigger it, operators can, and now
  the audit row says who did. The Tools tab's installer gains the same node
  picker the Docker manager gets: pick a node, see what is installed *there*,
  install or remove there. The controller is not offered at all (roadmap
  #26): it takes no packages, and its own record is registry plumbing.
*Amended 2 September:* there are **four** stores, not three — `artifacts`
joins data, packages and cache: this node's copy of what a project built,
per project underneath, so a VM that is several projects' node keeps two
`app-release.apk` apart. It exists for the node that is not on the LAN: an
emulator or a container on a cloud node should start from a copy beside it
rather than pulling one across the link on every run, and the second run of
an unchanged build copies nothing. And **a store path is now refused if it
is a system directory** — exactly or inside one, and a bare top-level
directory like `/mnt` with it. A store is a directory this system creates,
fills and (for the cache) empties on request, so `--cache /etc` would have
made *Clear cache* delete every directory under `/etc`. Checked on the
controller so the tab says no before anybody presses Apply, and again on the
node whatever it is told — the same reasoning as the capability refusal,
applied to disk.

*Amended 3 September:* **system images are per-node state too, and are the
one thing in this section the catalog cannot list.** Which images exist is
not a fixed list — it depends on what has been installed — so the node walks
its own store for the ids and the AVDs built on each, and reports them in the
census (`reported.images`). What *could* be added is not a per-node question
at all: an image is a GUEST artifact, identical on every host, so the picker
is drawn from Google's index read on the controller, minus what that node
already has. A node therefore needs no network of its own to be offered one,
and the size on the row is the download size from that index rather than a
`du` — measuring tens of gigabytes over an NFS-mounted store every ten
minutes would be minutes of stat traffic for a number already known. Adding
one is the ordinary package job with `android-tools` (and its JDK) put in
front of it, since the install is sdkmanager's.

- **The store is a role with a location, not a mount.** Each node has a
  `packages` store — default an internal path
  (`/var/lib/builderbot/toolchains`), because a node with its own disk should
  not need NFS to hold a JDK. A share is allowed as the location where that
  is what the operator wants (the controller's own SDK share is exactly this
  case, so the local node needs nothing migrated). **Sharing one store
  between several nodes is the trap to name**: two agents installing into one
  NFS directory at once, or one upgrading under another mid-build, is version
  skew nobody can debug — the default is one store per node, and a shared
  store is a deliberate arrangement for co-located nodes with the
  one-install-at-a-time rule enforced across them or not at all.

  *Where it landed (2 Sep):* enforced. Reading is automatic and always was —
  a node's `toolchains` are a live probe of its packages store at every
  census, so a node whose neighbour installed something on the shared export
  reports it at its next `hello` (ten minutes, or at once after any job that
  ends in one). Writing is what needed the rule: `packages.store_sharers`
  identifies the nodes that share a store — by the census's mount SOURCE
  under the store path, never by the path string, since
  `/var/lib/builderbot/packages` is every node's default and a different disk
  on each — and a package job is refused while one is running on any of them,
  naming the node that holds it. The Tools tab says a store is shared, and
  with whom, before anybody presses Install.
- **Disk is checked before, not discovered after.** The catalog already knows
  each package's size; the census reports each store's headroom. A
  package-install job is refused at placement when the store cannot hold it —
  named, with numbers — rather than failing at 91% of a 12GB download. The
  same check gates a job's workspace materialization against the node's cache
  store. This is most of what "any size of VM" means in practice: nothing in
  the system assumes a size, everything that consumes disk asks first.

`package-build` placement then follows from the census: a job that needs
android tooling selects on `toolchains["android-sdk"]`, not on a label
somebody remembered to set.

*Where phase 6 landed it:* `workspace.py` on the controller makes the
dirty-tree snapshot — git's view of the tree (tracked plus untracked, minus
ignored and minus `.git`), never `dist/`, as one uncompressed tar named by
its sha256 under `/config/snapshots`, the last five per project kept — and
serves it to the agent's `source?digest=` verb. A run (`bb run`, `bb build`,
`bb test`, or the same `run` action on `/api/v1/jobs`) snapshots, then
queues an exec carrying the digest on the node the project assigns to the
role in its settings dialog (build, test, ci, emulator — the last two are
settings for phases 7 and 9). The agent fetches by digest into its cache
store once, checks it, unpacks it under `<data>/jobs/<id>/workspace`, runs
there with `BUILDERBOT_WORKSPACE` and a per-project `BUILDERBOT_CACHE`
under the cache store, uploads what the outputs globs match through the
`artifact` verb — into the project's `dist/` by basename, with
`dist/.provenance/<name>.json` beside it (job, node, snapshot digest,
command, sha256) — and deletes the workspace; a failed job keeps it and
replaces the previous kept failure of that project. The census reports the
cache store's size and *Clear cache* on the row is a `cache-clear` job. A
toolchain install on a node is a `package` job: the agent fetches the
bundle (bb, its library, the catalog) by digest into the packages store
and runs `bb sdk install` from it with `SDK_ROOT` at the store, gated on the
store's headroom when this controller has measured the package before; the
Tools tab's node picker shows what the node's census says it has. Not
landed: the node browser is the kept-workspace path in the job's log and
`bb run`'s last line, not a file view; and an APK has not yet compiled on a
real node — the mechanism is complete, the proof needs a node with a JDK.

### Artifacts

The job declares outputs as globs; the agent uploads on success,
content-addressed; the controller stores them and the Artifacts tab lists them
under the version stamp that is already the convention. Retention by count and
age per project, with pool-level quotas as the later enterprise knob.

Provenance rides along nearly free and matters to both tiers: every artifact
row already knows its job, its source digest/ref and its node. Keep that chain
queryable ("what built this, from what, where") — it is the skeleton that
signing and SLSA-shaped attestation attach to *if* an org ever asks, and it is
useful on day one when an APK misbehaves.

## 7. Deploy targets and preview environments

A deployment is a long-lived job on a node with `deploy-target`: compose up,
plus a route. What must be uniform is the *record*, not the implementation:

```jsonc
{ "id": "d_04", "project": "…", "node": "n_…", "compose": "…",
  "route": { "mode": "lan | funnel | public", "url": "https://…", "port": 8080 },
  "state": "up | down | failed" }
```

The modes are tiers of the same thing, built in this order:

1. **`lan`** — publish a port, show `http://<node-ip>:<port>`. What the Docker
   manager does today; most of the homelab value.
2. **`funnel`** — Tailscale Funnel on the node: a public HTTPS URL with no
   DNS, no certificate, no firewall change. For "show someone a build", this
   is the answer, and it is a small agent feature.
3. **`public`** — a reverse proxy (Caddy, for zero-config ACME) on nodes with
   a public IP and a wildcard record: `<project>-<id>.preview.example.com`.
   **This is the enterprise mode, not an over-engineered homelab mode** — the
   first pass cut it; this pass sequences it last instead. The traffic never
   transits the controller, which is what keeps every mode cheap.

*Where phase 8 landed it:* the route lives on the dev-instance record
(`route: {mode, port}` in `/config/devapps.json`) and is drawn on the
manager's row as the URL plus a picker. `lan` is the published port at the
instance's node's address (`nodes.route_host`: an ssh node's address, an
agent node's the one it last dialed in from) — what the manager always
linked, now a record. `funnel` is a `system` job with `apply: funnel` on the
instance's node: the agent runs `tailscale funnel --bg --https=443
http://127.0.0.1:<port>`, and the census reports tailscale — installed, the
MagicDNS name, and which https ports forward where, read from `tailscale
serve status` so a funnel set by hand reports the same — which is what
makes the row's `https://<name>/` say *ready* rather than *asked for*. One
funnel per node on 443; switching the route back to lan turns it off. The
picker greys funnel on a node without tailscale and names `public` as
unbuilt rather than hiding it; the Artifacts row's Open uses the route's
URL when it is ready. No deployment record of its own: an instance up on a
node with a route IS the deployment, and the compose job is its long-lived
job. The unhardwiring this phase owes: deploy targets touch no environment
variable of their own — `DOCKER_HOST` became a node in phase 2, and both it
and `DOCKER_HOST_PATHS` have since left the five places entirely (§11).

## 8. Security model

New as a section, because "usable in an enterprise" is mostly this.

**Identity.** Every API caller is a *principal*: the operator (dashboard
credential today), a node (its token), or a service token (for automation).
Every mutating handler receives one. In the homelab there is exactly one human
principal and nothing changes visibly. The seam this buys: OIDC/SSO later is a
new way to *establish* a principal, not a new kind of request — same handlers,
same audit, same API.

**Authorization.** Day one: admin-or-node, which is what exists today. The
design constraint is only that checks happen in one middleware, keyed on
(principal, action, target), so roles (admin / operator / viewer, then
per-pool) are a table and a lookup later — not a hunt through handlers.

**Audit.** Every mutation writes a row: when, principal, action, target,
parameter digest. Built in phase 1, because it is one middleware and one table
now and an archaeology project later. The homelab gets "what did the session
change while I slept" — genuinely useful here, where an agentic session is a
second pair of hands — and the enterprise gets the first thing their review
asks for.

**Secrets.** Job env vars that are secret (registry credentials, deploy keys)
live in the controller's store, encrypted at rest with a key from the
environment, injected into jobs at assignment and redacted from logs by the
same mechanism the entrypoint already uses. The interface is `secrets.get(name)`
— which is the seam where Vault or a cloud secret manager plugs in for an org
that has one. Do not build the Vault client until then.

**What a compromise means, stated honestly.** A controller compromise owns the
fleet — it hands out jobs; that is inherent to every CI/CD system and no
protocol choice removes it. What the design *does* bound: nodes enforce their
own capabilities (a controller cannot make a `docker-host` out of a node not
enrolled as one); node tokens are per-node and revocable, so one stolen agent
credential is one node; the controller holds no credential that logs into
anything; and `disposable: true` nodes (the sandbox pattern) are where
untrusted work belongs. The `local` node is the deliberate exception — see
§12's caution.

## 9. Observability

Minimal and in the core, because both tiers debug the same way:

- **`/api/v1/healthz`** — liveness, DB reachable, queue depth.
- **`/metrics`** — Prometheus text format: nodes by state, jobs by state,
  queue depth, job duration, artifact bytes. A homelab points Netdata or
  nothing at it; an org points their existing stack. Read-only, cheap,
  and retrofitting it later means re-instrumenting every path.
- **Structured job logs** are already in the model (chunks, per job, retained
  by policy); controller logs stay logs.
- **Per-node performance metrics, from the agent.** CPU, memory, load and
  per-store disk headroom, sampled every ~30s and shipped with the heartbeat —
  the channel is already there, so this is a payload, not a feature. The
  controller keeps the current sample per node (in the DB, so the row can
  show it) and a short in-memory ring for a sparkline; long history is what
  `/metrics` plus the operator's own stack is for, and the controller does
  not become a time-series database. The Nodes row shows the numbers; the
  Docker manager shows them beside the node picker, because "is this box
  struggling" is a question you ask while staring at a build.

## 10. Scale and availability, honestly

Design targets, so "scales" means something: **homelab: 1–5 nodes, one
operator.** **Enterprise: ~500 nodes, ~50 concurrent jobs, tens of humans.**
Numbers chosen to be defensible with this architecture, not aspirational.

What gets each tier there:

- 1–5 nodes: everything in this document as first built. Long-poll, SQLite,
  one process.
- ~50–100 nodes: still one process; batch log writes; Postgres recommended.
- Beyond: the websocket/async listener (§4) for connections; Postgres
  required; artifact store on real disk or S3-compatible (an interface with
  two implementations, local-dir first).
- **Controller HA: active/passive only.** State lives in the database;
  the controller is restartable without losing jobs (agents outlive it —
  running jobs keep running, reconnect, report late). Two controllers behind a
  load balancer with Postgres and a leader lock is the ceiling this design
  promises. Active/active job scheduling is explicitly out: it buys nothing at
  500 nodes and costs a distributed-systems paper.
- **Failure semantics** (same at every scale): agents are the durable side of
  a job — a controller restart must never kill running work; a node that
  vanishes mid-job fails the job with "node lost" after a grace window; a job
  is retried only if its spec says it is idempotent, never by default.

## 11. Configuration and migration

`DOCKER_HOST` and `DOCKER_HOST_PATHS` leave `.env` and become node fields:

1. On first boot after the upgrade, if `DOCKER_HOST` is set and no node has
   that address, create one — `kind: ssh`, name `sandbox`, capabilities
   `[docker-host]` — and log that it happened.
2. The env var keeps working for one release; the Nodes screen shows the node
   as "from DOCKER_HOST — this setting is going away" with an adopt button.
3. Then it leaves the five places (`.env.example`, `docker-compose.yml`,
   `unraid/builderbot.xml`, README reference, `docs/unraid.md`) in one change.

*Where it landed (roadmap #24, complete):* both variables are out of the five
places, out of every doc that named them as settings, and read by nothing.
The one-release deprecation path is gone with them — `nodes._adopt_docker_host`
and `_seed_paths` are deleted, and so is the env branch of `devapp._pairs`.
The path mapping lives on the node record (`config.paths`, edited on an agent
node's row, read by `devapp.host_map` through the node being addressed).

**Check, beside it (roadmap #13).** Under the identity mapping — the shipped
default and the rule — nothing verified that the two machines actually mean
the same directory by `/workspace`: this container's mount table says nothing
about the other machine's, and docker answers a missing bind source by
creating an empty directory, so the failure was silent twice over (it cost
three rounds on 27 Aug, when the share was repointed on one side only). Check
makes a marker directory under the share here and asks the node's daemon
whether it can see it, through the same guarded one-shot container the
dev-data directory is made with (`devapp.check_paths`, a `test -d` on the
share root). Three answers and never a guess: the same directory, NOT the
same directory with what that would cost, or "could not ask" with the
daemon's own words. Off the poll — it is for when something changed.

The `ssh` kind went in the same change, because the seed was the only thing
that made one: `node_add` is a refusal naming enrollment, `_addr` and
`runner_of` know two kinds, and the `ssh` branch of `jobs.run_exec` — the
controller running a job on another machine over a key — is gone. The
`ssh_addr` column stays, written empty and read by nothing: migrations are
numbered and append-only, and dropping a column across two engines is a
one-way door for a cosmetic gain.

**Tools → Nodes** is the screen: a row per node with state, capability
toggles, services, labels, pool, concurrency, last seen — and Enroll, Test,
Drain, Remove, plus the approval queue when a bulk token is in play. Drain
means "finish what you are running, accept nothing new", and it is what makes
a node safe to patch — at home and in a fleet alike.

Profiles rather than knobs: the config surface stays one file/env-set, and the
**defaults are the homelab** (SQLite, single-use tokens auto-approved, local
node enabled, no OIDC). An enterprise install sets `DATABASE_URL`, an OIDC
block, and approval mode — and nothing else changes meaning.

### The unhardwiring

`DOCKER_HOST` is the first of a class, and the class should be named: this
project has grown up hard-wiring runtime behavior into the container's
environment, where changing anything means editing a template and recreating
the container. That was fine while everything was one box; it is the wrong
home for anything the node work touches, and the operator has asked for the
shift to be explicit. So it is a standing rule with a precedence contract,
not a one-off migration:

- **Every env var gets a scope from §13.** Container-scoped ones (ports,
  mounts, credentials, `DATABASE_URL`) stay env forever — that is what env is
  for. Everything controller-scoped moves to the DB-backed settings the
  Settings tab edits.
- **Precedence: env seeds, the database owns.** On first boot a set env var
  seeds the setting; from then on the DB value is the truth and the env var
  is ignored — never a silent override, because two live sources for one
  value is how a box disagrees with its own screen. The Settings tab marks
  any setting that came from a seed, so where a value originated is never a
  mystery.
- **Each phase unhardwires the vars it touches**, and the five-places list
  shrinks in the same commit — a moved setting leaves `.env.example`, the
  compose file, the Unraid template and both docs together, with one
  deprecation release where the seed still works and says so.

The end state: `.env` is bootstrap — where the container runs and how it
authenticates — and everything about *what the system does* lives in config
the GUI can change and the audit log can attribute. That is most of what
"easier to deploy" turns out to mean: a new install answers three questions
in a template and does the rest from the dashboard.

## 12. Provisioning and the agent

One script, `vm/provision.sh` grown up: detect with `/etc/os-release`;
abstract the package manager over `apt|dnf|pacman|zypper|apk`; install Docker
only if the docker capability was requested; install the agent and its systemd
unit; enroll with the token; idempotent throughout; end by printing the node
id. Cloud-init is the same script with the bulk token baked in — which is the
entire cloud story, deliberately: **instance *creation* stays outside.** An
autoscaler that talks to EC2/Azure/GCP is an external program using the same
enrollment API; building three cloud SDKs into the controller is how the core
stops being maintainable. The API is the extension point (§3).

**Storage as roles, with transport separated out.** The current script
conflates two questions the node model needs kept apart: *how a location is
provided* (a virtiofs share, an NFS mount, a plain directory on the node's own
disk) and *what it is for*. `bb-sandbox` already has the seed of the second —
its `appdata` flag marks one mount as where containers keep data — but it
requires the answer to be a mount, so a node with a big internal disk cannot
say "just use /var/lib". The provisioner grows the roles as first-class flags,
each taking either an internal path or a mount the script sets up:

```
--data      PATH | nfs:HOST:EXPORT[:opts]     where containers keep state
--packages  PATH | nfs:HOST:EXPORT[:opts]     the toolchain store (§6)
--cache     PATH                              build caches; internal by default
```

`--share`/`--nfs` remain the *transport* half for anything else the operator
mounts; a role flag pointing at a mount implies it. Roles land in
`/etc/builderbot/node.json`, the agent reports them (with headroom) in its
census, and nothing on the controller ever hard-codes a path on a node again.
*Where phase 3 landed it:* the three role flags take a path (the `nfs:` form
waits for phase 5, where mounts become jobs), default under
`/var/lib/builderbot/`, and `--controller URL --token bbe_…` is what turns a
provisioning run into an enrollment — the script fetches the agent from the
controller, checks it against the digest header, enrolls as the docker
account and enables the unit. Package-manager abstraction and
docker-on-request are still the shape written above, not the shape shipped.
Notably absent: a `--workspace` role for agent nodes — job-scoped snapshots
replaced it (§6) for JOBS. A node that runs sessions (§19, phase 10a) mounts
the projects share at `/workspace` all the same, through the phase-5 config
plane like any other mount; that is the session's tree, not a job's.

**Any size of VM, by construction.** The script assumes no disk layout and no
sizes: every role defaults to the node's own filesystem, a role can be pointed
anywhere, and the script's only size opinion is a *warning* when a requested
role's filesystem is visibly too small for what was asked (a `package-build`
node whose packages store has 8GB free will not fit an Android SDK, and
hearing that at provision time beats hearing it from a dying download). The
running system's size decisions all live controller-side against the census
(§6) — so a small VM is a valid node that simply qualifies for less, not a
special case.

**The agent: Python file first, static binary when nodes stop being pets.**
The first pass recommended a single-file stdlib Python agent and deferred Go.
With enterprise in scope the endgame is clearly a **static binary** —
signed releases, no runtime dependency, no distro Python drift across a fleet,
trivial cloud-init. The resolution is sequencing, not a change of endgame:
the protocol is six HTTP verbs precisely so an agent is trivial to write in
either language; ship the Python one through the pilot phases (it matches the
house, and one file is reviewable); commit to the Go build the moment nodes
are machines nobody set up by hand (bulk enrollment appearing is the trigger).
The self-update mechanism (§4) is what makes swapping agents in place a
non-event.

### After provisioning: reconfiguring a node from the GUI

Provisioning is once; a node's storage and network change over its life, and
the operator has named the goal plainly: **never having to ssh in for it.**
So the provisioner's decisions become a *configuration plane* the Nodes tab
edits — declarative, applied by the agent, with the same desired-vs-reported
split capabilities use:

- A mount whose mountpoint is left blank lands at `/mnt/<the export's own
  name>` — where a Linux box puts a mount, and the agent's `bb-sandbox`
  creates the directory itself, so naming one that does not exist yet is
  not a problem. Only a default: `/workspace` has to stay `/workspace` for
  path parity with the controller, so anything that matters is typed.
- The controller stores a node's **desired config**: mount entries (NFS or
  virtiofs, with options and read-only flags), the role assignments from §6
  (which path is `data`, `packages`, `cache`), and network settings (static
  address, gateway, DNS, static routes).
- A change is a **`system` job** — audited like any mutation, run by the
  agent as the one root-privileged thing it does, applied idempotently
  through the same logic `bb-sandbox` uses today. `bb-sandbox` itself
  survives as the console fallback, reading and writing the same on-node
  state, so the GUI and a rescue shell can never disagree about what the
  node is configured to be.
- The agent then **reports applied config** in its census, and the row shows
  desired vs. actual — a mount that failed shows the mount error verbatim on
  the row, not a greyed nothing.

**A store's path and the mount it sits on must agree, and both ends enforce
it.** The failure it exists to stop is silent in the worst way: a share that
is in fstab but not mounted leaves its mountpoint an ordinary empty
directory, `mkdir` makes the store inside it, and everything then lands on
the node's own disk while the census reports a healthy store with the root
filesystem's free space. So the agent refuses to *point* a store at a
configured mount that is not mounted, naming the share and saying what would
otherwise have happened; and `bb-sandbox remove` refuses to *unmount* a
share a store is inside, unless it is given `--force`. `bb-sandbox list`
marks a mount that holds stores, and a share that fails to mount says which
store is stranded in it.

The two are kept in step structurally rather than by matching rules:
**`bb-sandbox` reads the store paths out of the agent's own `node.json`**
instead of keeping a list of its own, so a store repointed from the Nodes
tab is visible at the console on the next command with nothing to
synchronise. `test/agent.mjs` runs the real `bb-sandbox` — pulled out of the
provisioner the way `bb lint` pulls it out for shellcheck — against the
agent's `mount_covering` on the same cases, including the string-prefix
traps (`/mnt/tan` is not a parent of `/mnt/tank/cache`), so drift between
them fails a test rather than surfacing on someone's node.

**Repointing a store brings its contents with it.** It used to just repoint,
which meant the node started using an empty directory while the toolchains,
AVDs or built artifacts stayed where they were and nothing said so. The
agent now copies the old store into the new one before the switch, refuses
the move if the destination has not got room, and **never deletes the
source** — the same rule the node-change migration keeps: a half-finished
move must leave the old store able to serve. `cache` is the exception and
says so in the log; it is rebuildable by definition, and copying tens of
gigabytes of it across a link would be work for nothing. Because that copy
can legitimately run for hours, a storage apply that moves a store gets a
six-hour clock instead of the usual fifteen minutes, and the Nodes tab asks
before starting one.

**Network changes get commit/confirm safety, because they are the one change
that can cut the cord it arrives on.** The agent applies the new network
config, cycles the stack, and must re-establish its connection to the
controller within a window (default three minutes); if it cannot, it rolls
back to the previous config automatically and reports the failure on
reconnect. This is the dial-out architecture paying rent: the node finds the
controller from *whatever* address it lands on, so the row simply says
"applying network change — waiting for it to dial back in", and a bad
gateway is a three-minute delay instead of a bricked VM and a console
session. (The same pattern RouterOS and Proxmox users know as safe mode —
familiar for a reason.)

**Validity holds through all of it, because enrollment is the recognition.**
For an agent node, "this is a real BuilderBot sandbox" is no longer inferred
per-connection from a daemon label — it is the enrollment itself: the node
token, the stamp written at provision time, and the `disposable` marking.
Reconfiguring storage or network changes none of those, so nothing the GUI
does here can un-recognize the node it is doing it to. Root-level system
jobs are *offered only* to nodes that carry the stamp — a machine enrolled
as a plain builder never shows the mounts-and-network panel at all, which is
the capability rule (§2) applied to the most privileged thing the agent
does. Legacy `ssh` nodes keep the daemon-label check they have today and do
not get the configuration plane; absorbing bb-sandbox's menu is the agent's
job, not ssh's.

*Where phase 5 landed it:* the desired config lives on the node record
(`config.desired`: mounts, stores, network), validated to its shape when it
is saved; the agent's census carries the reported half (`mounts` as
`bb-sandbox list --json` reads them, `stores` with headroom, the address the
default route leaves by, and `sandbox` — whether bb-sandbox is there, which
is the stamp). A `system` job with `apply: storage` diffs desired mounts
against reported and runs `bb-sandbox remove` / `add-nfs` / `add-share` for
the difference, then moves the stores in node.json and makes them; it ends
with a hello, so the row shows the applied state at once. `apply: network`
carries the address, gateway and resolvers and never a tool: the agent
detects which service owns the machine's network and renders the same spec
through it — a file of its own under `/etc/netplan` and `netplan apply`;
the ipv4 keys of the interface's NetworkManager connection through
`nmcli`, then `con up`; a `.network` file and `networkctl reload` under
systemd-networkd; wicked's `ifcfg`/`ifroute` files on SUSE Leap; the
interface's stanza in `/etc/network/interfaces` and an `ifdown`/`ifup`; a
marked block in `dhcpcd.conf`. Either way it
keeps what was there, dials the controller from wherever it landed for up
to three minutes, and with no answer puts the previous config back and
applies it again, reporting the revert on reconnect. A node with neither
backend refuses the job and says so. The same detection picks the package
manager — apt, dnf, zypper, pacman, apk, xbps or emerge — for a recipe's
system packages (named per family under `system` in the catalog), and the
census reports both with the init system (`distro`), so the row says what
a change would go through.
Another distribution is another backend in the agent, not another job
spec. A fourth system job, `apply: root` (roadmap R38), runs ONE command as
root that an administrator allowed: a session asks with `bb root run --why
"..." -- CMD`, and the request is routed by the SESSION that asked: to
that session's own account when it is an administrator's, and to every
administrator when it is a user's, because a sandbox is shared and root on
it is not a user's to allow — the way a phone request waits on the phone's
owner, which is the asker when the phone is theirs (same list, `kind:
root`, on the Nodes tab and the bell; a per-user grant for root on a
sandbox is a permissions design of its own, not written). Allow queues the job with the reason and the approver in
its spec so its log is the record, and only a sandbox node takes it — the
agent refuses it without the stamp like storage and network. It is not
sudo: there is no second command without a second question, and nothing
pretends. The controller offers system jobs only to an
online agent node whose census says sandbox, one at a time per node; the
agent refuses them without bb-sandbox whatever the row says. On the Nodes
tab the row grows a *storage & network* fold: the editor is a draft that
survives the heartbeat repaint, Save keeps the record, Apply queues the job
(asking first when it would unmount something, and always for network), and
each desired mount says what the node reports for it. bb-sandbox at the
console is unchanged and remains the fallback.

And the caution that survives from the first pass, now with a sharper edge:
**the `local` node is not a sandbox.** Jobs placed on it run inside the
controller container, beside `/config`, the dashboard credential and every
project's source. That is already true of builds today, so it is not a
regression — but `docker-host` on `local` stays off unless a socket is
deliberately mounted, the Nodes screen says what `local` means, and an
enterprise deployment should be able to disable the local node entirely
(one setting; the controller then schedules nothing onto itself).

## 13. Settings and surfaces

The node work multiplies settings, and settings sprawl is how a dashboard
stops being one. So before the screens: **every setting has exactly one scope,
and the scope decides its surface and its storage.** Five scopes cover
everything this design adds, and the rule for placing a future setting is at
the end.

**Browser-scoped** — theme, sidebar layout. Per viewer, cosmetic, instant.
Stays where it is: the gear's popup. Nothing here changes.

**Container-scoped** — what the process needs before it can think: ports,
mounts, credentials, PUID/PGID, `DATABASE_URL` itself. Stays in the
environment and the five documented places. The test for this scope: *if
changing it means recreating the container, it is env.* This list should only
ever shrink — `DOCKER_HOST` leaving it (§11) is the pattern.

**Controller-scoped** — what the controller owns and can apply live:
enrollment defaults (auto-approve, token TTL), retention (job logs, artifacts,
failed workspaces), the local node's enablement, later the OIDC block. Stored
in the database, audited like any mutation. Today this scope holds one
setting (session-log retention, living in the gear popup); the node work
gives it a dozen, and **a dozen settings do not fit in a flyout — the gear
graduates.** The popup keeps the per-browser items plus one entry,
**"All settings…"**, opening a **Settings document tab**: a `TABKINDS` entry
rendering banded groups in the house pattern, same as every other document
surface. The graduation lands with the first batch of controller settings
(phase 2), not before — converting the popup while it holds one setting would
be ceremony.

**Project-scoped** — which node runs this project's work. One node, named in
the project row's existing settings dialog beside model and effort (the
dialog and its poll plumbing already exist in `claude-prefs.json`, and a
second surface for per-project settings would be a second place to look).
Not a selector and not per-role: the operator dropped both, on 1 and 2
September respectively — a project picks a machine, and that machine does its
containers, builds, tests, CI and emulation. A project that never opens the
dialog has no node, and is told so where it matters. Storage:
node *bindings* go in the database (they reference node ids, must survive a
node's rename, and want auditing); the existing model/effort prefs stay where
they are — no churn for its own sake.

**Node-scoped** — services, labels, pool, concurrency (capabilities left this
list on 2 Sep — see §2): the
**Nodes tab**, a document tab opened from the Tools card beside Docker manager
and Static analysis. Row anatomy in the house language: name, state as a pill
(online / offline / draining / pending — the severity-pill palette already
says how), the toolchains its census reports, labels, last-seen, and per-row Test / Drain /
Remove; Enroll at the top; the pending-approval strip above the list when a
bulk token is in play, in the same held-above-the-fold shape the Phone tab's
asks use.

**The rule for anything new:** *who has to be able to change it, and what has
to restart for it to take?* Answer those two and the scope — and therefore
the storage and the screen — is decided. A setting that shows up in two
scopes is two settings wearing one name, and should be split before it ships.

### The Docker manager, concretely

- The "on ssh at …" source line becomes the **node picker**: a select over
  every `docker-host` node, online or not, in the standard field skin. One
  Docker tab, re-rendered per selection — not a tab per node.
- The container cache (`dockerList`) becomes per-node, keyed by node id, so
  switching nodes shows each one's last-known list instantly. An offline
  node's view is the ghosted rows and "state unknown" language already built —
  that work was this design's down payment.
- Gating goes per-node: controls grey with *this node's* reason, not a global
  one. Refresh retries the selected node only.
- **New container** and **Send to Docker manager** gain a node select,
  defaulting to the project's configured node, else the only node, else ask.
- The row's build/log tail is the job view scoped to that instance, and each
  row names the node it ran on (phase 4).

### The rest

- **Jobs** (phase 4): a document tab — queue, running, recent; per-job log
  tail (the dev-instance row's rendering, generalized), Cancel on a row, and
  a filter for what is not over. `bb jobs` is the read-only form.
- Later, enterprise-flavored and additive: the audit view (a read of the
  table phase 1 starts writing), pool filters wherever a node list appears.

### The page itself — one page, still

The dashboard is one page: a tab strip over panes, every view a document tab
or a terminal, no router, no framework, ~11k lines of classic-script JS in
one file. The node work is the right moment to ask whether that survives, so
here is the answer argued rather than assumed: **it survives, because the
constraint that shaped it has not moved.** The page's first job is holding
live terminals — tmux-backed iframes that must not be torn down by
navigation. Any many-pages design either kills terminals on every click or
duplicates the terminal host per page; the tab model exists because of that,
not out of habit. Everything multi-node adds (Nodes, Jobs, Settings) is
document-shaped, and document tabs are the cheap case now: a `TABKINDS`
entry, a renderer, and the shared machinery — the field skin, the band
tokens, the doc-tab pattern, the surface inventory, the TABKINDS/TAB_KINDS
pairing test — carries the rest. The week the Analysis tab shipped proved the
marginal cost, and the guardrails that made it cheap were the point of
building them.

Three things do change inside the one page, and one is the actual scaling
risk:

- **The status poll must not grow; new data rides the revisions registry.**
  The real thing that breaks with many nodes is not the tab model, it is
  "one `/api/status` ships everything to everyone every fifteen seconds".
  Node lists, job queues and logs get their own endpoints and revision
  tokens, fetched by the views that show them when their token moves — the
  pattern findings and the docker tab already use. Rule, stated once: **node
  and job data never joins the status payload.**
- **A new surface is a new file, same page.** One page has never had to mean
  one file. Nodes, Jobs and Settings each land as their own classic script
  (`nodes.js`, `jobs.js`, …) served beside `index.html` — classic scripts,
  deliberately not ES modules, because the shared global scope is what lets
  the suite drive internals and the surface inventory audit the namespace,
  and modules would end both. No big-bang split of the existing file; the
  rule applies to new surfaces, the way the server side already keeps a
  feature's code in one module.
- **A tab renderer gets an error boundary.** One page is one failure domain:
  a throwing renderer used to take the whole dashboard down, terminals
  included. Renderers run inside a guard that draws the failure as that tab's
  error band and rethrows to the console — "the new Jobs tab has a bug" is a
  bug again, not an outage. *(Built, with the scaffold below, ahead of phase
  2 — the foundation was worth having before anything lands on it.)*

- **The chrome is built once, and conformance is enforced, not requested.**
  Every new tab used to hand-write its own skeleton, and every one drifted —
  browser-default controls, a bar with no inset, rows on the sidebar's
  tighter padding — each caught by a person noticing, three tabs in a row.
  Two mechanisms end that. `docSurface(i, kind)` builds the standard skeleton
  (doc-width box, filter-bar slot, band list, quiet footer) and a renderer
  fills slots instead of writing chrome. And `test/uniform.mjs` holds **every
  kind TABKINDS registers** to the hard rules by computed style and geometry
  — one content-x for every band, the field skin on every control, the
  document width cap, no sideways scroll and 16px controls at phone width —
  with the enforcement hook that makes it stick: a new kind with no
  conformance driver fails the suite by name. The price of a new tab includes
  conforming, not just existing; Nodes, Jobs and Settings inherit the rules
  on the day they are written, not after their third redesign.

And the one honest limit, filed on the enterprise track where it belongs:
the tab layout is server-side state for **one operator** — several humans
sharing a controller would fight over one strip. Per-principal layouts are an
E3-shaped change (they hang off the principal seam) and nothing before that
needs them.

## 14. Phased roadmap

Each phase leaves a working system, and each is independently useful. The
core track is unchanged from the first pass; the enterprise track is new and
explicitly gated.

**Phase 1 — the seam, with nothing visibly changing.**
A `nodes` module, the SQLite store and migration files, a node record for the
controller (`local`), principals + the audit table on existing mutating
endpoints. Everything that runs work asks for a node and always gets `local`.
`DOCKER_HOST` migrates into an `ssh` node. Read-only node list. The operator
notices nothing.

**Phase 2 — Tools → Nodes, and multiple Docker hosts over ssh.**
CRUD, capability toggles, labels, test, drain, remove. The sandbox VM becomes
an ordinary node. The Docker manager gains its node picker and per-node
caches; the project dialog gains its Nodes group; the gear graduates to the
Settings tab as the first controller-scoped settings arrive (§13). Delivers
"more than one Docker host" with no agent written — worth doing even if
nothing later happens.

**Phase 3 — the agent, enrollment, and the numbers.**
Single-file Python agent, systemd unit, one-time tokens, `hello`/long-poll,
heartbeat and census — **metrics included** (§9): CPU, memory and per-store
headroom ride the heartbeat from day one, because they prove the channel with
something the operator actually wants to see. Job type `exec` only. Nodes may
be `agent` or `ssh`; both work. **Stop and reassess here**: this is the phase
that changes the project's shape.

**Phase 4 — jobs and the queue.**
The job model, placement function, streaming logs, concurrency, cancel,
drain-aware assignment. Move the Docker manager's compose actions onto it, so
"rebuild" is a job with a log rather than a module global. The Jobs tab.
`/healthz` and `/metrics` land here, with something to measure.

*Where phase 4 landed it:* the rows are the queue — there is no in-memory
list to lose. A job is placed by an explicit node or by a selector over
capability, labels, pool, `os` and `arch` (the node record carries the last
two as columns now, from the census), checked against the live registry when
it is queued so an impossible selector is refused with the selector in the
message, and frozen onto the row when it is taken. Two runners serve one
table: the agent takes `exec` and `self-update` on its own node; the
controller's runner (`jobs.py`) takes everything else — every `compose`
action, and `exec` on a node with no agent, run over ssh from here — through
the same `job_next`/`job_log`/`job_result` the agent uses, so the rows cannot
tell which served them. Concurrency is counted from the rows per node.
Cancel is a flag on the row: the agent hears it on the wire, the controller's
watcher turns it into a kill of the held process group, and the row moves
when the runner reports it stopped, not when the button was pressed. Logs
fold (a progress frame supersedes the last of its kind) and are held back at
most two seconds, so a pull is a log that moves rather than a transcript. A
job this process was running when it died is failed as lost at the next
start. The Docker manager's Up, Down, Rebuild and Remove are compose jobs,
busy per instance rather than per dashboard. The Jobs tab and `bb jobs` read
it; `/api/v1/healthz` answers without a credential, `/metrics` with one.

**Phase 5 — the node configuration plane.**
Storage roles, mounts and network editable from the Nodes tab (§12), applied
by the agent as `system` jobs — which is why this sits after phase 4 — with
the commit/confirm rollback for network changes. Deliberately **before** the
package store and caches: they consume the roles this phase makes editable,
and building them against provision-time-only roles would bake the ssh-to-fix
workflow in for another year.

*Where phase 5 landed it:* §12's closing paragraph. Agent 3 adds the
`system` job type and three census fields (`sandbox`, `mounts`, `network`);
the protocol's verbs are unchanged.

**Phase 6 — workspace, caches, artifacts, and the package store.**
Dirty-tree snapshots, per-node caches with size/clear, artifact upload +
provenance chain, the read-only workspace browser. The Tools installer gains
its node picker; toolchain installs become jobs against each node's packages
store, gated on reported headroom. `package-build` becomes real: an APK
compiles elsewhere and lands in the Artifacts tab.

*Where phase 6 landed it:* §6's closing paragraph. Agent 4 adds the
`package` and `cache-clear` job types, workspaces for jobs with a source,
`used_mb` on the stores and toolchains found in the packages store.

**Phase 7 — services.**
The Actions runner as a per-node managed service with per-node labels,
installed/removed from the Nodes screen.

*Where phase 7 landed it:* the fold on a sandbox node's row grows a *CI
runner* section. Install is a `system` job with `apply: runner`: the agent
fetches GitHub's latest runner release for the node's architecture into
`/var/lib/builderbot/runner`, asks the controller for a registration token
through the new `runner-token` agent verb — minted on request from the
root-only stash by the same helper the container's runner uses, audited,
never stored; the PAT stays here — registers as the enrolled account with
labels `builderbot, self-hosted, linux, <arch>, <node name>` plus any typed,
and installs and starts it with the runner's own `svc.sh`. Remove
deregisters with a removal token first. The census reports the service
(`services.actions-runner`: registered as what, with which labels,
listening or busy), the node record keeps what was asked for, and `bb
ci-labels` lists every label the registry knows — this box's and every
node runner's — with `--write` regenerating `.github/actionlint.yaml` from
it; `bb lint` notes a declared label no runner carries. **A project's CI
node setting decides where its jobs land by label**: the workflow's
`runs-on` names the node, and nothing else can, because GitHub places the
job, not this controller. The controller's own runner was retired on 5 Sep,
by the phase's own rule: only after a node runner had taken a real job (3 Sep,
the smoke test on bb-sandbox) and every workflow in this repo had moved there.
`runner.sh`, its supervision, `bb runner`, the image's install step and the
five `RUNNER_*` settings all went in one change; the Runner card is a view of
the nodes' runners now, and `github_url()` reads only the environment.

**Phase 8 — deploy targets.**
Modes `lan` and `funnel`; the `route` record shaped for `public`.

*Where phase 8 landed it:* §7's closing paragraph. Agent 6 adds
`apply: funnel` and tailscale to the census.

**Phase 9 — device hosts.** Required, not optional, since §18.

*Where phase 9 landed it:* `bb emu` goes to the project's node when it has
one (`BB_EMU_LOCAL=1` keeps a verb on a box that still carries its own
emulator): the verb is an exec job whose spec carries `bb` argv instead of
a command, and the agent runs this very `bb` from the bundle in
`<data>/emu/<project>` with the node's store as its SDK — `sdk_env()`:
`SDK_ROOT`, `ANDROID_HOME` at the store's `android/`, `JAVA_HOME` at its
`jdk/`, the tools on `PATH`, AVDs under the data store. Inputs come from the
project's `dist/` by name through the new `file` agent verb (an APK for
`bb emu install`); what the verb writes comes back through the outputs
globs like a build's. Two catalog rows bootstrap a node for Android —
`jdk` (Temurin 21) and `android-tools` (sdkmanager, linked in as
`android/cmdline-tools/latest`) — after which `android:emulator` and the
system images install through them; `bb emu create <api>` makes the AVD.
New verbs on both sides: `create`, `install`, `shot` (a screenshot into
`dist/emu/`), `gfx` (gfxinfo framestats into `dist/emu/`). The census
reports `emulator` among the toolchains. Not proven: an emulator booting on
a real node — the tests run `bb emu list` from the bundle against an empty
store; the first `bb emu create` on the VM downloads a system image and is
worth watching. Interactive network adb was not needed for the verbs that
exist, and is left unbuilt. Bug #17 (the headless Xorg dying) stays this
container's until the local emulator goes with phase 10.
Job-scoped emulation first: instrumented-test jobs that boot an emulator on a
GPU node for the life of the job and return results as artifacts — no network
adb involved. The provisioner learns to install the GPU display arrangement
on a node that has the card. The interactive `device-host` service (a
long-lived emulator a session reaches over network adb) is designed in §2 and
built only if the job-scoped path proves insufficient.

**Phase 10 — the lockdown.** After phases 6, 7 and 9 and never before them:
the image drops the compile and emulation toolchains, the local node loses
`package-build`, the session's settings file closes Bash to an allow-list,
and every `bb` verb that ran something here submits a job or refuses with
the reason. §18 has the argument and the honest limit.

**Running through every phase: the unhardwiring (§11).** Each phase moves the
env vars it touches into the DB-backed settings, seeds-then-owns, and shrinks
the five-places list in the same commit. Phase 2 starts it with the settings
the new tab exists to hold; nothing waits for a dedicated migration phase,
because there is not one.

**Enterprise track** — not planned. There is no enterprise deployment today
and pretending otherwise would put speculative code in the core; this list
exists only to show that each item lands on a seam above without touching
anything, and the order is a sketch of how it would go if the fantasy ever
grew a name. The binding part of this document for enterprise purposes is not
this list — it is §15, the doors.

- **E1 — Postgres** via `DATABASE_URL` (the storage rule from phase 1 is what
  makes this a config change).
- **E2 — bulk enrollment + approval queue + agent self-update + the Go
  agent.** The fleet phase.
- **E3 — OIDC/SSO + roles** (admin/operator/viewer, then per-pool) on the
  principal/authz seams; the audit view.
- **E4 — scale-out listener** (websocket/async or gateway) when connected
  agents approach the long-poll ceiling; S3-compatible artifact backend;
  active/passive HA runbook.
- **E5 — `public` preview routing** (Caddy + wildcard DNS) where an org wants
  review environments.

## 15. The one-way doors

The stated constraint is not "build for enterprise" — it is **"do not get
backed into a wall that cannot be resolved later."** Those are different
requirements, and the second is much cheaper. Almost everything on the
enterprise track is a two-way door: OIDC, RBAC, Postgres, mTLS, a websocket
listener, S3 artifacts, the Go agent — each can be added years later at the
cost of building it then, and *nothing* built now makes any of them harder.
They need no insurance and get none.

What follows is the complete list of one-way doors — the places where the
cheap version becomes load-bearing and the expensive version cannot be
retrofitted honestly. Each is already in a core phase; this section exists so
that if any of them gets cut in the name of shipping, the cut is made knowing
what it costs.

1. **Identity that is not an address** (phase 1). Node ids minted at
   enrollment; `requested_by` on every job; ids never reused. Retrofitting
   identity means guessing what old records meant, which is not retrofitting,
   it is fiction.
2. **Attribution and audit at the mutation sites** (phase 1). One middleware,
   one table. History that was never written cannot be backfilled — this is
   the single enterprise-flavored feature built early *because* it is a
   one-way door, and it pays homelab rent ("what did the session change while
   I slept").
3. **A versioned API before any client exists** (phases 1–2). `/api/v1` is
   nearly free on day one; imposing versioning on clients already in the
   field is the wall.
4. **Protocol semantics split from transport, with the agent's version in
   `hello` and self-update in the verb set** (phase 3). The wall is a fleet
   of agents in the field speaking a protocol that cannot evolve; version
   negotiation plus self-update is the escape hatch, and it must exist before
   the second agent is installed, not after.
5. **Agents as the durable side of a job** (phases 3–4). A controller restart
   must never kill running work: the agent owns the process, buffers what it
   could not report, reconnects, reports late. Bolting this on later rewrites
   the agent's state machine — it is the difference between HA being a
   runbook and HA being a rewrite.
6. **SQL that runs on two engines, behind numbered migrations, from migration
   0001** (phase 1). A year of accreted SQLite-isms is a port; the discipline
   from day one is a config change.
7. **Node-side capability enforcement** (phase 3). Agents refuse jobs outside
   their enrollment. As a later patch it means re-enrolling a deployed fleet
   to establish what each node should have been refusing all along.
8. **No "one operator" baked into data shapes** (phase 1). The `pool` column,
   token records carrying a `kind`, principals as strings rather than a
   boolean. Columns are cheap; schema surgery under live data is not.
9. **OS and architecture are placement dimensions, and the wire carries
   nothing POSIX** (phase 4). The operator's stated direction, 1 Sep: macOS
   and Windows nodes for building and testing Apple and Windows apps, set up
   and linked the way the Linux VM is. Not on this roadmap, and the protocol
   already allows it — HTTP, JSON, argv as a list, an integer exit code, a
   `cancel` verb rather than a signal name. What would close it is phase 4
   assigning jobs by capability alone: a `package-build` job landing on the
   wrong OS. So the node record carries `os` and `arch` as first-class
   fields (today a census string and a label), a job's placement selects on
   them and freezes them at assignment, and no job spec, log or result ever
   names a signal, a shell, a path separator or a uid. Everything else is a
   two-way door: a per-OS provisioner (zsh, PowerShell) speaking the same
   `enroll`; the agent's census, sampler, privilege drop and process kill
   behind one platform seam so a darwin or windows agent is another
   implementation of that seam, not a fork; "jobs never run as root"
   becoming "the service runs as the enrolled account, never an
   administrator" where there is no setuid; a per-OS key in the package
   catalog; simulators and Windows apps as device-host capabilities of their
   own OS. Enrollment being the sandbox recognition already means a Mac
   needs no daemon stamp.

That is the whole list. It is deliberately short, because over-insuring is
its own wall: every speculative abstraction is complexity the homelab pays
for daily against a customer who may never exist. If a ninth door turns up,
it gets argued into this section first and built second.

## 16. Still not worth building — for either tier

- **A workflow engine.** Pipelines belong to the Actions integration; this
  schedules jobs people ask for. (`needs:` is the tripwire.)
- **Active/active controllers.** Active/passive on Postgres is the ceiling.
- **gRPC.** The listener model, not serialization, is what scale pressures.
- **An in-controller autoscaler / cloud SDKs.** External, over the API.
- **A plugin system.** The API is the extension point; in-process plugins are
  a compatibility treadmill.
- **Node auto-discovery.** Enrollment is deliberate at both tiers; a bulk
  token in cloud-init is discovery enough.
- **Per-job micro-VMs / Firecracker.** The isolation story is disposable
  nodes; when someone needs more, that is a different product tier.

## 17. Open questions

1. **Controller reachability** for off-LAN nodes: public endpoint or
   Tailscale? (Homelab decision; enterprises have load balancers.)
2. ~~Who is the enterprise user?~~ **Answered: nobody yet, and that is fine.**
   The operator's constraint is "do not get backed into a wall", which §15
   satisfies without building the track. E1–E5 stay unbuilt until a
   deployment with a name exists; nothing in the core phases waits on one.
3. **Windows/macOS nodes?** The agent model extends (a service instead of
   systemd), the provisioner does not. Decide before the Go agent, not after.
4. **Session `docker`:** with several nodes, does a session's environment get
   the project's default node, or nothing, with everything through `bb`?
   *Answered by §18: nothing, with everything through `bb`.*
5. **Retention defaults** for logs, artifacts and failed workspaces — the one
   part of the design that grows without bound, at both tiers.

## 18. The controller runs nothing

Decided 1 September, after phase 3, and it changes the destination rather
than the route: **the container is the controller and nothing else.** No
build runs here, no test, no CI job, no emulator. A project names the nodes
its builds, tests, CI and emulation run on; a session on this container
reaches them only through `bb` verbs that submit jobs; the artifacts come
back into `dist/`. A VM is therefore required for full function, and the
sandbox VM the Docker manager already needs is the first node — `provision.sh
--controller URL --token bbe_…` enrolls it in the same run.

Three things follow, in the order they have to happen.

**Every toolchain leaves first.** Phases 6, 7 and 9 put compilation, the
Actions runner and emulation on nodes. Only then does the image drop the
JDK, the Android SDK and emulator, .NET, Flutter and Swift, and only then
does the local node lose `package-build`. The other order strands every
project between a container that cannot build and a node that cannot yet.
`bb sdk` shrinks to what a session and the dashboard actually use here —
node, Python, and the Playwright browsers for `bb shot` against a URL.

**Then the session's tools close.** The settings file `claude_scope()`
already passes (`scripts/dashboard/bb-tty`) denies the file tools every
sibling project and `VERSION`. It grows a Bash rule: denied except an
allow-list — `bb`, `git`, and read-only inspection. Every `bb` verb that used
to run something locally (`bb emu`, a build, a test) submits a job to the
project's node for that role, streams the log back, and refuses with the
reason when the project has no node for it. So the job channel — audited,
node-scoped, capability-checked on the node itself — is the one execution
path a session has.

**The honest limit, written into the UI and into CLAUDE.md.** Claude Code's
permission rules are prefix matches enforced by the client; the sibling-path
deny list already carries the caveat that it is a guardrail and not a
sandbox, and the Bash rule is the same kind of thing. What actually holds is
that there is *nothing here to run against*: no toolchain, no daemon a
session can reach, no runner, no emulator. The rule makes the boundary
visible and the missing toolchains make it real, and neither should be
described as the other.

What this does to the rest of the document: rule 2 no longer promises a
working system with zero configuration — it promises one with one decision;
phase 9 is required; a phase 10 exists; and open question 4 ("does a
session's environment get the project's default node?") is answered —
nothing, with everything through `bb`. The self-hosted runner on this
container, and everything CLAUDE.md says about CI sharing the box, goes with
phase 7.

## 19. The session runs on the node

Decided 4 September, and it moves the destination again — further, and in a
direction that makes §18 the halfway house rather than the end: **Claude works
*on* the sandbox.** Not a session here reaching a node through `bb` verbs, but
the session itself living there, editing that machine's files with that
machine's toolchain. The container keeps the dashboard, the notebook, the
queue and the record; it stops being where work happens at all.

Why it beats §18, in one line: §18 spends a lot of machinery teaching a
session on the wrong machine to act on the right one — a job per build, a job
per emulator verb, snapshots in both directions, a lockdown to stop it doing
otherwise. Put the session on the node and most of that is simply not needed.
`bb sdk` on the node already answers for the node. `bb build` is a build.

It also settles a question §18 could not. The operator hit it on 4 September:
this box's SDK share and bb-sandbox's packages store are **one store under two
names** — `/sdk` here through Unraid's FUSE layer, `/mnt/SDK` there over NFS,
store id identical — so "the container has Flutter" and "the node has Flutter"
were one fact, and nothing could be taken off the container without taking it
off the node. §18's answer was to split the share, which is a share per
controller and does not survive more than one node. §19's answer is that the
question stops mattering: whoever is on the node reads the node's store.

**Nothing here is designed yet.** These are the decisions it turns on, and
each is a real fork rather than a detail:

1. **The project tree.** The biggest one, and it argues with a rule this
   document already made: job workspaces are dirty-tree snapshots, *never* a
   network mount (§6). A snapshot is right for a job that runs for a minute.
   An interactive session edits one tree for hours and expects its edits to
   still be there tomorrow. So either the node mounts the projects share and
   that rule is narrowed to *jobs*, or `/workspace` moves to the node and this
   container's copy becomes the view rather than the original. Pick one
   deliberately; they are not compatible half-way.
2. **A project with no node then has no session.** On 2 September the operator
   settled the opposite: a project may have no node, and a session there still
   reads, edits, commits and pushes — it simply cannot compile. If sessions
   live on nodes that policy has to change, or this container keeps running
   sessions for the nodeless, which means both paths exist forever.
3. **The login and the transcripts.** `~/.claude` — the Claude Code login,
   every session transcript, the memory files — is on this container's home
   volume. Per node, or mounted, or synced; and the login is one credential
   being placed on more machines.
4. **The terminal.** `bb-tty` makes a tmux session locally and the dashboard
   frames ttyd at it. A session on the VM means the tmux is there, so the
   dashboard has to reach across — ssh, or the agent proxying a PTY over the
   job channel. Roadmap #8 (pop-out windows) is in the same code and should
   land after this, not before.
5. **The notebook, and `bb` itself.** `bb roadmap`, `bb bug`, `bb version`
   and the rest read `/config` directly. From the node they are API calls to
   the controller, with a credential the session holds — which is bug #16's
   problem arriving somewhere new.
6. **The shielding.** The sibling-project deny list, the shielded ssh keys and
   the PAT stash are all mechanisms of this image. They have to exist on the
   node or the bargain quietly changes. And measured on bb-sandbox on 4 Sep:
   a job runs as `bb`, which has no sudo and cannot read `/etc/builderbot`
   (0700 root, so the node token is out of reach) — but it IS in the `docker`
   group, which is root-equivalent on any machine running a daemon. That is
   acceptable while the sandbox is the blast radius and a session is only
   visiting through jobs. With the session LIVING there it is the thing to
   design against: root on the node reads the node token, and a node token
   fetches bundles and job snapshots from this controller.

What survives from §18 either way: every toolchain on nodes (phases 6, 7, 9),
the job channel for anything a session should not do by hand, and the honest
limit — a permission rule is a guardrail, and what makes a boundary real is
that the machine on the other side of it has nothing to run.

### How the forks went (roadmap #24)

Decided 5 September, and phase 10a — the node's half — is built. Each fork
above, in order:

1. **The projects share is mounted on the node**, at `/workspace`, through the
   phase-5 config plane (one more row in the node's mounts). §6's rule is
   narrowed to *jobs*: a job's workspace is still a snapshot and never a
   mount; a session's tree is the mount, because it edits one tree for
   hours. Path parity does the rest — `/workspace/<project>` means the same
   directory on both sides, which is what lets bb's relayed verbs run on the
   controller in the tree the session is in.
2. **A project with no node keeps its session here.** Both paths exist, and
   the proxy decides per project: bound to a node whose census reports the
   session half up, the session is relayed there; otherwise it is this
   container's, as it always was.
3. **The login is per node**, in the session account's home — and it gets
   there from the controller: a node-bound terminal's token is minted for
   the account, `bb login` on the node fetches that account's credentials
   file with it (`GET /api/v1/claude-login`), into that home, 0600, only
   when the node's copy is not signed in. Not a share — one file, one
   machine, one account. The interactive flow in the session's own terminal
   is the fallback. **Transcripts and memories are one place**: every
   account's `~/.claude/projects`, on every machine, is a link to
   `/workspace/.claude/<uid>/projects` on the projects share
   (`claude_projects_link` in lib/common.sh, made when the home is), and
   the tree rule is the same on both machines — the owner in the project
   directory, everybody else in a worktree — so the transcript slug is the
   same string wherever the session ran, and the controller's Memory tab and
   resume chooser read a node's conversations without knowing where they
   happened. A home that already held transcripts has them copied across
   and the original kept beside the link, renamed, for the operator to
   delete. The share carries a `.bbignore`; bb-tty walls every other
   account's directory in it as it walls a sibling project.
4. **The terminal is the same ttyd, on the node.** The agent keeps two of
   them up — writable, and the read-only twin — running bb-tty from the bb
   bundle the controller ships (refetched when the bundle's digest moves in
   hello), bound on the node's LAN address; the controller's `/term` proxy
   dials that instead of the loopback (phase 10b), stamping the account, its
   name and a session token into the URL exactly as it stamps the account
   locally. The tmux server is the node's; a dropped browser detaches.
5. **bb's notebook verbs are relayed**: `POST /api/v1/bb` with the session's
   token carries the words (`roadmap add …`, `bug show 3`, `version --file`),
   the controller runs its own bb in that project's tree and returns what it
   printed. One implementation of every verb, kept where the state is;
   `RELAY_VERBS` (server.py) and `BB_RELAY_VERBS` (bb) are the one list, and
   a test holds them equal. `sdk`, `emu`, `run`, `build`, `test` are NOT
   relayed — they answer for the machine the session is on, which is the
   point. The token's scope is the project; a session's credential is the
   same scoped token it has always had (bug #16), now with a hop.
6. **A third account.** Sessions run as `builder` (provision.sh
   `--session-user`), made with the controller's PUID:PGID so files it saves
   on the share are owned as the controller's are; in `kvm` for the
   emulator, in **no docker group**, no sudo. Jobs stay `bb`; the agent stays
   root and drops to each. The node token lives in `/etc/builderbot`
   (0700 root) and never enters a session's environment — the sessions get
   the controller's URL and certificate pin, and nothing else of the agent's.

Phase 10b is built too: `server.session_target` decides per project —
local, the node (`reported.session.up` and `/workspace` mounted), or
refused with the reason (offline, no session half, no mount) rather than
quietly started on the wrong machine — and `_term_proxy` dials the node's
ttyd on the address it enrolled from, stamping `tok:` and `name:` after the
account. The project row carries the same decision (`session_at`,
`session_why`), so the Claude button is dead with the sentence before
anything is asked. provision.sh filters 7681/7682 to the controller's
address with an nftables table of its own, re-applied at boot by a unit.
The node's sessions are on the Sessions card too: the agent's heartbeat
carries the session account's tmux sessions (name, attached, directory,
pane title), the controller lists them beside its own under its own naming
rule — the owner's bare, everybody else's prefixed, `node_name` keeping the
node's — each with an "on <node>" pill, claude_with and the project rows
count them, and ending one queues a kill the agent's held poll takes at
once (`nodes.session_kill`, `{"kill_sessions": [...]}` in the work reply).
The two hooks a session runs post from a node too: `POST /api/v1/hook`
with the session's token takes a `note` (the file an edit is about to
touch, answered with who else has it open — `bb work` reads the same
record), an `asked` line for the project's feed, and `started`, which
bb-tty sends when it is about to make the session, since the proxy cannot
see one start on a node. The account is the token's, never the request's.
Keys reach a node's session the same way — the key row, the read-only
console's line, a macro — as tmux commands queued for the agent
(`nodes.session_tmux`, `{"tmux": [...]}` in the work reply), which types
them into the pane as the dashboard types into its own; the paging
decision (copy mode at a prompt, the program's key in a full-screen one)
is made on the node, where the pane is. What the controller still cannot
do for a node's session is keep the one-Anthropic-account rule, which is
the node's own. 10c landed 6 September: the image carries no JDK and no
Android SDK; a container in the node role keeps the emulator's runtime
libraries and the X server for the GPU path, and the startup hook that
builds AVDs from `ANDROID_SYSTEM_IMAGES` is gone — an API level is what a
store holds an image for, and `bb emu create` fetches one. `bb emu` on a
controller with no node for the project refuses and says where it runs.
A node's sessions outlive a controller restart on purpose (the tmux is the
node's); what must not is the idle rule — the Settings tab's "end a Claude
session after N idle minutes" rides the hello reply into node.json and the
agent enforces it on its own tmux, controller up or down (idle.py).
The account's CLAUDE LOGIN is kept in step rather than copied once: the
grant is an OAuth pair and a refresh rotates the refresh token, so two
machines each holding a copy sign each other out — which is exactly what
happened after a day of node sessions (bug #64). `bb login --sync` runs on
every connection and moves whichever grant has the later `expiresAt`, up or
down; an older one is refused rather than stored, and the copy it replaces
is kept beside it for one round. The controller stays the one place that
holds the account's current grant, and a machine that has been away cannot
undo a sign-in that happened while it was gone.
A CONTAINER node — this image in the node role — is a guest in §20's terms
before the class exists on the record: no systemd, so its runner is run.sh
in the foreground under the agent (supervised, taken down with it, reported
by the same pgrep as a service); no bb-sandbox, so no system jobs; no root,
so a recipe's system packages are the image's to carry. The doctor's GPU
check runs only in that role, since a controller renders nothing.

## 20. Three rules from 6 September

Set by the operator after a session ran on bb-sandbox for the first time and
the bill for it came in (roadmap #24, step 4). They bound §19 rather than
replace it.

**A node may carry the whole workstation.** That was never the objection.
Nodes exist for resource management — a sandbox on this server or another,
a cloud box, a Mac, a Windows machine — and the controller exists so all of
that is configured, enrolled and updated from one place. So the toolchain,
the lint tools, the browser module, the session half: fine on a node, *as
long as they arrive from the controller* — the Tools tab, the catalog, the
bundle, the agent's self-update — and never by somebody logging in and
setting them up. A new node is a provisioner run and a few clicks, not a
checklist.

**Credentials are set up on the controller and nowhere else.** PATs, deploy
keys, the Claude login, the runner registration: one place. A node never
holds a git credential. Git's network operations from a node session go
through the controller (`bb git push|fetch|pull`, relayed, run in the
shared tree with the keys the controller already shields — the shape
shelved #15 wanted, arrived at from the other side). The Claude login is
handed to a node's account by `bb login` with the session's token, which
is the one exception and is deliberate: it is the account's own credential,
placed in that account's home, 0600, and nowhere a job can read.

**A node keeps one footprint, and the machine stays its owner's.** The
sandbox VM is *managed*: the controller may edit its fstab, netplan, docker
and accounts through the config plane, because the VM is for nothing else.
Everything else is a *guest*: the agent, the stores and the session half
live in one directory with one service unit, and the controller changes
nothing outside it. A MacBook enrolled as a node is still a MacBook; a
`--remove` leaves no trace. The class is declared at enrollment and gates
the system verbs per what each actually touches (roadmap #23). provision.sh
today is the managed shape; the guest shape is the work.
