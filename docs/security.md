# The threat model

What BuilderBot protects, from whom, and what it does not. Written before
BuilderBot ships as an operating system (R158), so that every hardening
step names the line here it closes, and so that whoever runs an install
can tell their own users what a copy of the disk, a person on the LAN or a
tampered page would and would not get. [privacy.md](privacy.md) says what
an install keeps; this page says who can reach it.

The short version: a secret lives in one place, sealed under a key that is
not beside it, and is handed to the one process that needs it for the one
moment it needs it. Root on the running controller reads everything the
controller can; nobody else reads anything whole.

## Who is trusted for what

| Who | Trusted to | Not trusted to |
|---|---|---|
| **The owner** | run the install: the controller's settings, every project, every account, the install key, maintenance mode | open another person's key store (their agent sign-ins, their git tokens): sealed under that person's key, which only the install key opens, which the owner holds, so this is a line of policy today and a line of cryptography once R157 lands |
| **An administrator** | projects, nodes, people, the Keys page's inventory, purging a store | read a store's contents; sign in as another person |
| **A person** | their own projects, their own key store, their own sign-ins | another person's sessions, store or sign-ins; the controller's settings |
| **A person's coding agent (a session)** | the project it runs in, the projects it reads, `bb` on its person's behalf under the project's dials | the controller's state, another project's tree, any token (it pushes and signs through BuilderBot, which holds the credential), another account's home or tmux (R125), the dashboard's shell history (R155) |
| **Root on a node** | the machine: every session there, every token file on it | the controller: a node has no credential to the controller beyond its own enrollment, which reaches its own project's work and nothing of another node's |
| **Root on the controller** | everything the controller can read, the install key included | nothing is kept from root on the running controller; this is the host's own trust (`docker exec`, the machine's console) |
| **A copy of a disk** (a backup, a stolen drive, a copy of `/config`) | nothing | the sealed stores open without the install key (kept outside `/config`), the node's sealed sign-ins open without the controller, the signing keys and git tokens are ciphertext |
| **Someone on the LAN** | nothing | reading or changing what the page, the agent channel and the terminal relay carry: the channel and the relay are signed by their own keys either way; the page's traffic is theirs to read where the dashboard is served over http (step 2 below) |
| **The page's own code** | drawing what the controller answers and asking it to act | holding a key: the page never holds a key (a key of a person's own is a passkey's or a companion's, R157), keeps no secret in local or session storage, and under the CSP of step 4 runs no script it did not ship |

## What each store protects, and what it does not

**The install key** (`BB_SECRETS_DIR/install-key`, or `/config/.install-key`
where there is no secrets folder; made at the first start, changed from the
Keys page). Everything the controller keeps sealed is sealed under a key
derived from it: the accounts' keys, the signing keys, two-factor secrets,
the deploy keys' passphrases, a project's own git line from before 0.8.0.

- Protects against: a copy of `/config` (ciphertext alone), a backup
  restored on another machine (refused until the key is given), an
  operator of the share the state lives on.
- Does not protect against: root on the running controller, who reads the
  key where the controller does; a secrets folder copied along with
  `/config`, which is why the key belongs in a folder the state is not in.

**An account's key** (`account-keys.json`, sealed under the install key).
Each person's own, made with their account, changed from Profile. Their
key store, their agent sign-ins on every node and the key pair each node
seals those under derive from it.

- Protects against: another person, an administrator and a copy of the
  disk reading the store; the install key changing (the account's key is
  sealed again, nothing on the nodes moves).
- Does not protect against: the owner, who holds the install key the
  account's key is sealed under. R157 closes this: a key of the person's
  own, held by a passkey or the companion, which the controller cannot
  open.

**A person's key store** (`account-secrets.json`: their git tokens, each
sealed under their account's key; the project's `gitcreds/NAME` names
entries and holds no token). A token is handed to git only for that
person's own work (their session's `bb git`, their presses, the release
they cut) and only while they hold a live sign-in (`logins.json`); work
that is nobody's (watching CI) takes any signed-in giver's.

- Protects against: a token outliving its person's sign-in; a session
  pushing as somebody who is not there; a project carrying a token nobody
  gave it; a session reading the token (it never sees it: the helper hands
  it to git on the controller).
- Does not protect against: the controller itself while a person's store
  is open, which opens the token to hand it over. Step 5 bounds that: a
  token is opened per use for the window the person picks, the opened line
  is what the controller keeps (in memory, and in a handout file for git
  under `/run` for the window), and each use is on their Profile. With a
  key of their own (R157) the store opens only while they have unlocked it.

**The agent sign-ins on a node** (sealed by the node under a public key
whose secret only the controller derives; `tokenseal.py`). The node seals
and never holds what opens a seal; the controller hands the seal's key into
a terminal a signed-in person opened, wrapped to the agent's own key for
this boot.

- Protects against: a copy of the node's disk or of the share; the traffic
  captured and the disk copied together; another account's shell on the
  node (R125: each account is a Unix user of its own).
- Does not protect against: root on that node while the sign-in is open in
  a terminal there, which reads the process's memory; a controller that is
  itself compromised, which can derive any node's secret.

**The signing keys and the deploy keys** (`/config/signing`, `/config/deploy-keys`;
sealed, root-only). A signing is a job on the project's node handed the key
over the agent's channel for that job; a push with a deploy key goes
through the shielded ssh agent.

- Protects against: a session reading, printing or committing a key; a copy
  of `/config`.
- Does not protect against: root on the node during the job that holds the
  key.

**The cryptography itself.** Today every seal is HMAC-SHA256 in counter
mode with a second HMAC as its tag, and the node's key pair is
Diffie-Hellman in RFC 3526's 2048-bit group, built from the standard
library because the image carried nothing else. It is sound by
construction and reviewed by nobody outside. Step 3 moves every seal to
X25519 and ChaCha20-Poly1305 (or AES-GCM) with HKDF from a vetted library,
reseals what was sealed the old way, and reads the old format for one
release; step 7 is the outside review.

## What an unlock gives up

A store is opened to be used. Each opening is a moment the controller holds
the plain token, and R158 step 5 makes each one a choice the person made:

- A person's git token is opened the first time git asks for it in a
  window, for the window they picked on their Profile (a quarter of an
  hour, an hour, eight hours, or while they are signed in), and the opened
  line is what the controller keeps: in its memory, and in a handout file
  of one line under `/run/bb-git` that `git-credential-bb` reads for that
  window, shredded when the window ends, the store is locked or the person
  signs out everywhere. The seal is opened once per window, not per use,
  and every opening is a line on their Profile: when, which token, on which
  project, for what (a push, a pull, CI watching, a release) and by whom.
  Lock on the Profile lets go of all of it at once.
- An agent sign-in is opened into the terminal that starts the session, on
  the node, and lives in that process for the session's life.
- The install key is in the controller's memory for as long as it runs:
  what root on the controller reads.

**A key of the person's own (R157).** Under the install key, the unlock
bounds how long an opened token stays in memory; the controller could open
the store at any time, since it holds the key. *Hold the key yourself* on
the Profile moves the store under a key the controller never holds: a
passkey's PRF secret (the authenticator derives it and the page only relays
it to the controller, over https and under the page's policy, for the one
request that unlocks), or a key the person keeps (64 hex characters shown
once; the Windows companion or a password manager holds it, and a device
signed in as them may unlock with it through the device door). The
controller keeps the X25519 public half of what the person holds and the
account key sealed to it; the account key is in its memory only while the
person has unlocked, and `Lock`, a restart or the window's end forgets it.
While it is shut: their pushes and pulls wait and the Git view says so, a
terminal they open on a node asks for the unlock first (that terminal is
what opens their sealed sign-ins there), and a login made on a node is
still sealed, to the node public halves the controller remembered while
the store was open. What it costs: a forgotten passkey or key means signing
in to every agent again and giving each project a token again; Purge
still works without it, an administrator's too. The tokens a project runs
background work with (CI watching, releases) go to the project's own
keeping at the move, listed before the person chooses, unless they keep
them under their key and accept that this work waits for their unlock.

## Memory and process

The dashboard and the node agent each do three things about the keys they
hold (R158 step 6, `hardening.py` and `builderbot_agent.base.harden`): no
core dump (the core limit is zero and the process is not dumpable, which
also keeps another process of the same user from reading its memory
through ptrace or `/proc/PID/mem`), no swap (the process locks its pages
in memory where the memlock limit lets it; `docker-compose.yml` and the
Unraid template raise that limit, and the Doctor says when it was too low),
and zeroing (`wipe`) of a bytes value that held a key or an opened sign-in
once it is let go. Root on the machine still reads a running process; what
the step closes is a core file, a swap partition and a neighbor of the same
user.

What sessions ask for never runs in either process: the controller runs
nothing, and on a node the agent that opens a seal is apart from the
sessions, which run as their account's own user in a view of their own
(R125, `bb-session`), so a session reaches no key the agent holds.

## The lines the hardening closes

| Step of R158 | The line it closes |
|---|---|
| 2, TLS | someone on the LAN reading the page's traffic, a session cookie or a token typed into a form; http stays a choice for an install with no CA, said on the page with what then crosses in the clear |
| 3, vetted cryptography | the hand-built seal and key exchange, replaced with a library somebody else has reviewed |
| 4, the page hardened | a tampered or injected script on the page, a secret parked in the browser's storage, a cookie sent cross-site |
| 5, an unlock that gives up less | the controller holding a person's whole store open while they are signed in |
| 6, memory and process | a core dump, swap or a neighboring process reading a key the controller holds |
| 7, outside review | this page and the cryptography being right by their authors' word alone |
| 8, sign-in hardened | a stolen cookie used from another device; what was done to the host read back by person and machine |

What no step closes: root on the running controller, and a person's own
agent acting as them on their own projects, which is what it is for. The
dials (Agents may) bound what it may do; the record (the audit, the
notebook's history, the forge's log under their own token) says what it did.
