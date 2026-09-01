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
  `builderbot.sandbox` label the provisioner writes. Everything the Docker
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
  install or remove there. The controller is just the `local` row.
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
replaced it (§6), and only legacy `ssh` nodes still mount source.

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

**Project-scoped** — which node (or selector: capability/labels/pool) runs
this project's Actions, compiles its packages, hosts its dev instance. These
join the project row's existing settings dialog as a "Nodes" group beside
model and effort — the dialog and its poll plumbing already exist
(`claude-prefs.json`), and a second surface for per-project settings would be
a second place to look. Each binding defaults to **auto by capability**, so a
project that never opens the dialog behaves exactly as before. Storage:
node *bindings* go in the database (they reference node ids, must survive a
node's rename, and want auditing); the existing model/effort prefs stay where
they are — no churn for its own sake.

**Node-scoped** — capabilities, services, labels, pool, concurrency: the
**Nodes tab**, a document tab opened from the Tools card beside Docker manager
and Static analysis. Row anatomy in the house language: name, state as a pill
(online / offline / draining / pending — the severity-pill palette already
says how), capability toggles, labels, last-seen, and per-row Test / Drain /
Remove; Enroll at the top; the pending-approval strip above the list when a
bulk token is in play, in the same held-above-the-fold shape the phone card's
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
- **New container…** and **Send to Docker manager…** gain a node select,
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

**Phase 6 — workspace, caches, artifacts, and the package store.**
Dirty-tree snapshots, per-node caches with size/clear, artifact upload +
provenance chain, the read-only workspace browser. The Tools installer gains
its node picker; toolchain installs become jobs against each node's packages
store, gated on reported headroom. `package-build` becomes real: an APK
compiles elsewhere and lands in the Artifacts tab.

**Phase 7 — services.**
The Actions runner as a per-node managed service with per-node labels,
installed/removed from the Nodes screen.

**Phase 8 — deploy targets.**
Modes `lan` and `funnel`; the `route` record shaped for `public`.

**Phase 9 — device hosts.** Required, not optional, since §18.
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

