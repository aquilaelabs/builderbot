# Journeys

What a person does with BuilderBot, walked for real rather than reasoned
about, on the dev pair: builderbot-dev (BuilderBot's own dev instance, on its
own share) and the bb-dev-sandbox VM. Each section is one walk with its date,
what was pressed in what order, where it snagged, and what that moved from
dev to alpha (house rule `vetting`). A walk that snags is the point of
walking it; the snag is fixed or filed, then the walk continues.

## New deploy to first project to first build and test (15 September 2026)

The starting state was made by the two verbs built for it that day: **Reset
BuilderBot** on the controller (Settings tab, the word `reset` typed), which
moved every account, node, setting, token and notebook into a dated
directory and brought the dashboard back at *Create the owner*; and
**Uninstall** on the node, which took the agent, its accounts, its mounts,
its stores and `bb-sandbox` off the VM and left docker, a few packages and
three empty mountpoints. Project files on the share were not touched by
either, which is what a fresh dashboard then shows.

What was pressed, in order:

1. **Create the owner.** The setup form, one account. No snag.
2. **The first look.** The Projects card listed a project left over on the
   share from before the reset. Trashed from its row and purged from the
   Trash, both asking for the name. No snag; a fresh install on a share that
   held projects before will see the same, which is right.
3. **Enroll node.** The Nodes tab minted a token and showed the command:
   `sudo bash provision-linux.sh --controller URL --token bbe_…`. *Snag:* the
   dialog does not say where `provision-linux.sh` comes from, and the
   controller does not serve it although its image now carries it; a person
   has to know the repository. Filed. The command itself, run as shown on a
   machine that already had docker, enrolled the node in about a minute.
   *Snag, fixed on the spot:* the first run stopped on an unbound variable
   the previous day's `--remove` work had left after the argument loop.
4. **The row of a node with no shares.** It reported its four stores on its
   own disk and its session half up with no `/workspace`. The Storage section
   took the three NFS mounts and the three store paths, and **Apply** moved
   them as a job. *Snag, fixed on the spot:* moving the toolchain store onto
   the squashed share failed on `cp` preserving the destination root's
   timestamp, an empty store at that; the agent copies a store's entries now.
   Applied again, every store was on the share and the row said so.
5. **Tools.** Installing `node` was refused: the toolchain store is a share,
   and an earlier node had already put `node` and Playwright on it. The
   refusal names the path and the remove verb; the tab shows them installed.
   Not a snag, and a good property: a second node inherits the first one's
   toolchains.
6. **New project.** Clone of the lab forge's `lab/hello` with a token, push
   rights ticked. Bound to the node in its settings with a build command, a
   test command and an output glob. No snag.
7. **A session's verbs, without a session.** The dev pair has no Claude
   login, so the Claude button was not pressed; instead a session token was
   minted against the dev controller's own state and `bb` was run on the VM
   as the session account with the environment `bb-tty` gives a session.
   `bb status` named the node; `bb build` ran there and wrote the artifact
   onto the share, listed on the Artifacts tab; `bb test` ran there.
   *Snag, already filed (B128):* `bb git policy`, a read, refused until the
   owner had a commit identity on the Profile tab. With one set, the policy
   read, `ls-remote` answered, and a branch pushed through the controller's
   stored credential.
8. **A runner.** Its token stored on the node's row against the lab forge
   over plain http, Install pressed, registered in five seconds; the push
   from step 7 had already queued a workflow, and it ran green on the fresh
   node the moment the runner appeared.

What this walk moved or confirmed:

- Alpha, confirmed again: Gitea as a git host (link, push, runner
  registration, CI), Unraid as the VM's hypervisor, the Debian family for
  the provisioner, and the plain enroll command from the dialog.
- Alpha, new evidence: the Storage section's Apply moving three stores and
  three mounts onto a squashed NFS share; Uninstall and Reset as the way to a
  fresh start without a new VM.
- Still dev: nothing this walk touched is left in dev; the hosts and
  hypervisors nobody has run stay where they are.

What a new user would still stumble on, in order of when they meet it: where
to get the provisioner (filed), the `useradd` warning during provisioning
(B131), and a git read refusing for want of a commit identity (B128).

## A Docker project, an Android app, and three people on one project (16 September 2026)

The second walk, page-driven at desktop and phone widths, on the pair the
first walk left behind: the owner `stencil`, the node `bb-dev-sandbox`, the
project `hello`. Three things the mandate asked for, in the order they were
done, with what snagged and what was moved.

**A compose project through the Docker manager.** A one-file nginx project
(`web`) was made from the New project dialog, bound to the node in its
settings, and sent to Docker from its Artifacts view. The dialog asked for
the instance name and a confirm, the build ran as a job on the node, Up
brought it up, and the site answered on the node's address. *Snag, fixed
(B134):* the manager's rows said "the daemon did not answer: Connection
closed by ... port 22" and "state unknown" throughout, because the one read
the rows are drawn from, `docker ps`, still went over ssh from the
controller while every action ran through the agent. A bare docker read
addressed at an agent node now runs there as a probe job the Jobs tab never
keeps, and a node that is on a job is not probed (a probe queued behind a
build would wait the build out): the last answer stands until the job ends.

**An Android app, built on the node.** JDK, the Android command-line tools
and the platform tools were installed from the Toolchains tab with the node
picked (a job each; the tab shows the running one). A new empty project
(`droid`) took a one-screen Java app with Gradle 8.14 and AGP 8.10, its
settings took the node, `./gradlew assembleDebug` and the APK glob, and
`bb build` was run on the node under the exact environment a session gets
there (read off a live session's process). Gradle downloaded, AGP fetched
Build-Tools 35 and platform 35 into the store against the licences the
recipe had accepted, and the build succeeded in under two minutes with the
APK copied into `dist/`, where the Artifacts view listed it with Download
live and Install ghosted for want of a phone. Setting the first version from
that view wrote `VERSION` and the block read `0.1.0-dev.2+…` at once. No
snag in the product. *Two snags beside it:* a console login shell on the
node had no `bb` on PATH because the provisioner's profile line named the
store the node was born with, not the one Storage had moved it to (B135,
fixed: the agent rewrites the line after every apply); and the Toolchains tab
asked to install the emulator's libraries on a node that had never
installed the emulator, because every android recipe shares one directory
(B139, fixed: a recipe is held when its own tool exists).

**Three people on one project.** The owner added `dev2` (a user, granted
`hello` only) and `dev3` (an admin). As dev2: the Projects card listed
`hello` and nothing else; the API refused everything not hers (artifacts
"not a project", roadmap and settings "not found", users "that is an
administrator's"); the Claude button opened a session on the node in a
worktree of her own (`.worktrees/hello/<uid>`) on the read-only console
with the "message Claude, then Enter" bar, while the owner's session on the
same project ran beside it in the project directory: three tmux sessions on
the node at once, each named for its account. *Snag, fixed (B141):* with
both accounts carrying one Claude login, pressing Claude again to get back
to your own running session was refused with the one-account sentence
naming the other person, and the refusal arrived as the browser's JSON
viewer inside the tab. *Snag, fixed (B142):* dev3, an admin, was told to
take the project on from the Users tab, whose editor hid the project list
for anyone but a user. *Filed:* the sign-out button of a user whose login
is shared names a session that is not theirs (see the notes in B137's
area), and a plain user's Doctor card carried the controller's whole pill
list, now cut to the lines that are theirs.

**The Doctor, read as a new owner.** Five lines were stale since sessions
moved to nodes and are gone or reworded: a red "git identity configured" on
a box where nobody commits, "no Claude login here" beside the card naming
the login, "gh is not authenticated" for a thing nothing signs in, "no ssh
key (agent empty)" and "no node with a daemon" while the Docker tab was
building on one. The probe behind the last one now opens the node store and
answers for the node the manager would open on.

What this walk moved or confirmed:

- Alpha, new evidence: the Docker manager against an agent node end to end
  (Send, build, Up, the route); the Android toolchain from the Toolchains tab and
  a Gradle build on a node with the store's JDK and SDK; several accounts
  with sessions on one project at once, each in its own tree; the users
  editor and the API's per-account refusals.
- Still dev: nothing this walk touched; the unwalked hosts and hypervisors
  stay where they are.

What a new user would still stumble on, in order of when they meet it: the
New project dialog has no node picker, so every project is born with
"node: none" and needs its settings before Claude can start; a project's
settings dialog leads with rename; the Docker row stacks three settings
pickers above its buttons; and the notebook foot's Save and Revert sit
ghosted on views with nothing to save.

## Several people on one controller, and what a walk actually proves (17 September 2026)

Walked to answer one question before letting anybody else in: what does a
second person see, and can they reach past what they were given. The dev pair
already carried three accounts from the 16 September walk, so this needed no
setup: `stencil` (owner), `dev2` (user, granted `hello` alone), `dev3`
(admin).

What was pressed, in order:

1. **New project, from nothing.** `journey-scratch`, no git host, a sentence
   of notes. It came back as a repository on `main` with CLAUDE.md written
   from those notes, and its row said `no node: pick one in the project's
   settings, or enroll one on the Nodes tab`. No snag: the row names the one
   thing standing between it and a session, which is what the 16 September
   walk asked for.
2. **The same box as dev2.** The Projects card listed `hello` and nothing
   else. `journey-scratch`, made a minute earlier, was not there.
3. **Reaching past the grant, as a person does by pasting a link.** The Git
   view, the roadmap, the changelog and the settings write, all named
   `journey-scratch`, all answered 400 `not a project` rather than 403. That
   is the design and it is the right one: a project somebody cannot see does
   not exist for them, so the answer is the same one a typo gets and leaks
   nothing. Creating a project at all was 403, which a plain user may not do.
4. **...and doing the job they were given.** The other half, because a grant
   that is too tight fails a tester as surely as one that leaks: on `hello`,
   the Git view, the roadmap and the changelog all answered, the row said the
   project was theirs to work in, and a session could start on
   `bb-dev-sandbox`.
5. **As dev3, the admin.** Every project listed, and none of them marked
   theirs to work in. That is the seatbelt the code describes rather than a
   wall: hiding a project from somebody who administers the box would only
   send them looking for it.

No snag in any of it. The isolation a second person meets holds at both
edges, which is the half of "ready for testing" that cannot be argued from
the code.

**The snag was in the walk itself.** The dev instance's dashboard answers
from the image it was last built from, and only its TEST runs use the live
checkout. It was serving `f681c5d`, built twenty hours earlier and thirty
commits behind the branch, so everything hardened that day (a session's
findings scoped to its own project, the per-account model and commit author,
B165's atomic fix) was not in what was walked. The walk proved yesterday's
isolation.

So the routine gains a first step, and it is not optional: **rebuild the dev
instance before walking a journey on it, and record the build the walk was
against.** A walk whose build is not written down says less than it appears
to, which is the same fault as a green suite that ran somewhere else (R65).

### Walked again on the build it was meant to prove (against `e8a6f5a`)

`bb devapp rebuild` took 136 seconds and brought the dashboard up on the
branch head, so the same ground was covered again with that day's work
actually present. A session token was minted against the dev controller's own
state, which is what stands in for a Claude session there.

6. **A session sees its one project.** The token for `hello` listed `hello`
   and nothing else, and the poll's finding counts were empty rather than the
   box's.
7. **Parking, and not un-parking.** The session added a roadmap step, shelved
   it (`ok`), and was refused taking it back off: 403, *taking an item off the
   shelf is the operator's*. The owner then unshelved it in one call. That is
   the asymmetry the control was built for, proved from both sides rather than
   from the tests alone.
8. **Two people, one project, two models.** As the owner, `hello` was given a
   model, an effort and a commit author. The owner's row carried them under
   `yours`; `dev2`, who has the same project, carried none of them; and the
   project's own settings carried no model at all. Asked the way a session is
   asked (`bb settings --json` for each seat), the owner's session would
   launch on `opus` at `high` and commit as `Stencil Alt`, while `dev2`'s on
   the same project would launch on Claude's own default and commit as
   themselves. That is the whole of what "yours, not the project's" was meant
   to mean, seen from outside the code.

No snag. Everything set during the walk was put back, and the box was left
with the four projects it started with.

- Alpha, new evidence: several accounts on one controller, each seeing only
  what they were granted, proved from the outside rather than from the tests.
- Still dev: nothing this walk touched.

## Enrolling somebody's own machine as a guest node (18 September 2026)

Walked against `e4f4fc1`, the branch head, on the dev pair. The point of a
guest node is that the machine stays its owner's, so the walk is as much
about what is NOT on it afterwards as what is.

`labowner` on the bb-dev-sandbox VM stood in for somebody's laptop. That VM
is already a MANAGED node, provisioned as a sandbox with the agent running as
root, which made it a better test than a clean machine: a guest footprint is
one account's, so the two had to coexist without touching each other.

What was run, in order:

1. **`--guest --check`** as an ordinary user. It answers whether the machine
   can be one and changes nothing.
2. **`--guest --controller ... --token ...`**, no sudo. It laid down
   `~/.builderbot`, fetched the agent and checked it against the digest the
   controller sent, enrolled as `labowner`, and wrote one systemd user unit.
   *Snag:* the four store paths default to `/var/lib/builderbot` for the
   managed shape, and the guest path read those defaults rather than its own
   footprint, so the agent reported it could not create
   `/var/lib/builderbot/artifacts`. Fixed: a guest keeps its stores in the
   footprint unless a flag actually named one.
3. **The row.** Online, and `sandbox` false: the managed marker is the thing
   the per-verb gate reads, so its absence is what makes the class mean
   something rather than a label. Storage and Network were both refused on it
   with the reason, asked straight at the API rather than judged from the tab.
4. **`--guest --remove --yes`.** *Snag:* it hit the MANAGED remove first and
   demanded root, because that runs on the argument before the guest branch
   is reached. So the instruction the script itself prints was wrong. Fixed
   by skipping the managed remove for a guest.
5. **What was left.** `~/.builderbot` gone, the unit gone and inactive. The
   `builderbot-agent` still running on the box is the MANAGED node's own, at
   `/usr/local/sbin`, untouched. Two agents on one machine, and taking the
   guest away left the other one working.

Two snags, both found by running it rather than reading it, both fixed in the
same sitting. What this does not cover is a machine with no BuilderBot on it
at all, and macOS, which is R23 step 3 and wants a Mac.

- Alpha, new evidence: a guest node enrolled, refused the verbs its class
  does not have, and removed itself completely, on a machine that was already
  a managed node.
- Still dev: the macOS half, which has never been run on a Mac.

## 20 September: the Git view on a project linked over http, and two people

Walked on the dev pair after `bb devapp rebuild`, so the instance was serving
the branch tip (f9e021a) rather than whatever it was last built from, which is
the discipline the 17 September walk cost us.

**Why this one.** The operator pressed **Pull** on the production Git view and
got git's own words back: `fatal: could not read Username for
'https://github.com': terminal prompts disabled`. That is a dead end for
whoever reads it, and the two things behind it were not the same thing.

1. **As `dev2`, a user with one project.** Signed in, met the welcome panel,
   closed it. Sees `hello` and nothing else; no Administration card, and
   `state.can` agrees field by field (terminal, docker-write,
   toolchains-write, git-auth, admin all false). Nothing here needed a
   refusal, because nothing was offered.
2. **As the owner, Fetch and Pull on `hello`** (linked to the lab Gitea over
   plain http). They failed with git's prompt error, and the reason was NOT
   the one the production failure had: this project's stored token had been
   taken away by an earlier Reset, so `has_token` was false and there was
   nothing anywhere to authenticate with. The API says so on the projects
   payload, which is how it was told apart from the other cause in a minute
   rather than an afternoon.
3. **With a token stored** (minted on the lab Gitea, put in through the
   project's settings dialog), Fetch answered `fetched` and Pull `Already up
   to date`. That is B184 proven on an instance: the controller names its own
   credential record on the command line, and the mirror git dir that
   deliberately drops the tree's helper no longer costs the view its reach.
4. **With the token cleared again**, the refusal now reads: *this project has
   no access token stored, and 192.168.1.16:3000 asks for one: put it in the
   project's settings dialog under Access token, or point the remote at ssh.*
   A token that is present and rejected says the other thing instead. Both
   are sentences that name the control; git's line named only what happened.
5. **The Emulator tab** drew for the picked node, and its button on the Tools
   card was ghosted with its reason, since no node there has the Android
   tools. The tab also surfaced, unprompted, that the dev VM's agent is 0.5.80
   against a 0.6 controller: a different compatibility window, said on the tab
   rather than discovered by a job that fails.
6. **Debug settings** in the controller's settings opened as a dialog with its
   own Save and Cancel, and its switch is no longer in the group where the
   group's Apply would have saved it.

- Alpha, new evidence: the Git view authenticates on an http remote through
  the controller's own credential record; the two credential failures are told
  apart and both name the control; a user with one project sees one project.
- Still dev: a real Claude session on the dev pair, which has no Claude login,
  so the tester's first hour is still unwalked past the point where a session
  would start.

## 23 September: the tabs as a tester sees them, with the map and the trace in hand

Walked on the dev pair after `bb devapp rebuild`, so the instance served the
branch tip (8d15eca). This walk was as much about the method as the product:
a browser script signed in as each person, opened every tab, screenshotted
it, kept the console errors and counted what each open fetched, and the
controller's own request trace was read beside it.

1. **As `dev2` on a phone.** Signed in, met the welcome panel, closed it.
   One project, no Administration card, `state.can` all false. The Tests
   view's *Open the run's output* is hidden, since a user has no shell. The
   Roadmap view's hint says nothing can be sent because no session runs.
   No console error on any surface.
2. **As the owner on a desktop, every tab.** Docker, Toolchains, Nodes,
   Emulator, Phone, Settings, Jobs and a notebook with all its views. Each
   open asked its endpoint once, which is the invariant the design suite
   now holds on the fixture, seen true on an instance. The controller's
   trace, with no browser open, showed one request in fifteen seconds:
   the node's own poll. The three counts that first looked like storms
   (sixteen fetches of the jobs list) were the walker wrapping `fetch`
   again at every step and counting itself; the instance was quiet.
3. **Snag, and fixed (B221).** The Nodes, Toolchains and Docker tabs all
   said *bb-dev-sandbox runs agent 0.6.92 and this controller ships
   0.6.92: press Update agent first*, and refused work until it was
   pressed. Both numbers were right and the sentence was nonsense: the
   check compares the agent file's digest, the words compared version
   numbers, and the file had moved without its constant. The row and the
   refusal name the two files by digest now when the numbers match, and
   the Docker tab no longer joins its clause as *...does not know.: the
   rows cannot say*.
4. **Update agent**, pressed as a tester would. The self-update job named
   the shipped digest, ran in seconds, and the node came back online on
   the controller's own file. The Docker tab's banner left, the Toolchains
   tab's ticks came alive.
5. **Tools, for real on a RedHat node.** Graphics ticked, Install selected
   pressed: the recipe fixed on 22 Sep fetched ImageMagick by tag and
   landed with resvg, oxipng, pngquant and cwebp on `bb-dev-sandbox` in
   a job the row followed, and the row now reads *installed* and says it
   adds `bb tool graphics` to a session. `needs_missing` is empty there,
   which is the fonts package present on that machine.
6. **A step and its arrow.** With one item added to `hello`'s roadmap and
   no session running, the arrow is drawn dead, the hint under the list
   says why, and a press on the arrow itself now says *no Claude session
   is running here* in the band (B213 on an instance). The project row's
   Claude button is unlit, and the two agree (B214).
7. **The Phone tab** says in one sentence that no node carries adb and how
   to change that. **The Emulator tab** draws for the picked node and says
   where its images would live. **Settings** opens with its three groups
   and the Debugging dialog.

- Alpha, new evidence: every tab asks once on open, on an instance with a
  real node heartbeating; the Toolchains tab installs a script recipe onto a
  RedHat node and the row follows the job; Update agent is a one-press
  recovery and the tabs it unblocks say so; a dead arrow explains itself.
- Still dev: a real Claude session on the dev pair (no Claude login there),
  so build, artifact, send-a-step and the phone journeys are still walked
  only up to the point where a session would start. The one bug this walk
  found (B221) was in the words, not the check; it would have cost a tester
  their first hour on a node.


## 26 September: sending a project to Docker twice

On `builderbot-dev` built from `3c794fe`, as the owner, with the project
`web` (an nginx compose whose `.env.example` sets `WEB_PORT=8088`) already
holding one container, `web-dev`, on `bb-dev-sandbox`.

1. **Send, with a container already there.** The Artifacts tab's **Send to
   Docker manager** opened on the name `web`, the project's own, since
   `web-dev` is not it, and the hint under the name said the new one goes
   beside the one it already has and needs ports of its own. The env came
   seeded with `WEB_PORT=8088`; it was changed to `8089` and Create pressed.
2. **The build it hands over.** The Docker tab opened on the new row and
   asked the same question Build asks (*Build web/main? Builds the first
   image and brings it up.*); answered yes, it built on the node and the
   controller reported it running with `8089->80` published, beside
   `web-dev` on `8088`. The page itself was not loaded from here: the
   session the walk ran in reaches only its own project's containers, and
   the VM's address is not one of them.
3. **Send again.** The dialog opened on `web-2`, saying it goes beside the
   two it already has. With the Docker tab's branches loaded, Build from
   showed too, carrying the same ports sentence a second time; that one
   went (`5391ae1`). Cancelled there.
4. **What a session is handed.** `web`'s briefing (the Briefing tab's
   source, `/api/preamble`) carries the new paragraph: `bb devapp new
   [NAME] [--branch REF]` is Send done from a session, and it, not `bb
   container new`, is how the project's own code goes into Docker. The old
   *create it when it has none* is gone from it.

- Alpha, new evidence: Send makes a second container of a project, named
  and built in the one gesture, on a real node.
- Still dev: `bb devapp new` from a real session on the dev pair, which has
  no Claude login and so no session token. The verb is proven by the
  harness instead: run as a session against the fixture server on auto and
  on ask (made, pinned, built; the card naming the container and its
  branch) and driven in process on both dials.

## 26 September, later: the first real Claude session on the dev pair

The stub `claude` that had stood in on the VM was replaced by pressing
Update Claude Code on its row (the real 2.1.283, pinned root-owned), the
operator signed in, and a Haiku session opened on `web` from the dashboard's
Claude button, in manual mode, at 10.231.0.2 on its own network. It was
driven as a person would: prompts typed through the dashboard, each bash
command approved at its prompt, its outputs appended to a file in the
project and read off the dev share. On `builderbot-dev` at e559a4a, then
1e03bde; `web`'s compose given `cap_add: CHOWN, SETUID` for the walk.

1. **`bb devapp ls`** listed `web` and `web-dev` as the project's own.
   **`bb devapp log web-dev`** resolved to `web-dev-web-1` (B307's fix)
   and then failed: `docker logs` went out over `ssh://bb@192.168.1.18`,
   "Host key verification failed". Only the bare reads ran through the
   agent; the container verbs took the retired ssh path (B312, fixed in
   1e03bde). Walked again after the rebuild: nginx's log came back.
2. **Rebuild, then curl at once.** `bb devapp --instance web-dev rebuild`
   at e559a4a said "no build appeared within twenty seconds" over a build
   that succeeded: the same commit, finished between two looks at the row
   (B312's other half). At 1e03bde it said "rebuilt 58e7e92; web-dev is
   up", and `curl http://192.168.1.18:8088/` on the next line answered
   200: the port reachable the moment the verb returns, from inside the
   session's network, which is what the agent's refresh after a compose
   job is for. The compose carried capabilities and the setting was auto,
   so the build was not stopped at the confirmation.
3. **Send from a session.** `bb devapp new --env /tmp/e2` (WEB_PORT=8090)
   printed "created web-2", "built 58e7e92; web-2 is up", and `curl
   :8090` answered 200 straight after; `ls` then listed three.
4. **Ask.** With the setting at ask, `bb devapp --instance web-2 rebuild
   --why askwalk` printed "asked stencil (#1), waiting up to 15 minutes";
   Allow on the dev bell built it and the verb reported "rebuilt".
5. **Deny.** The same command was refused with the sentence naming
   Claude may: Run its container.

- Alpha, new evidence: a session sends its project to Docker, rebuilds
  it, reads its log and reaches its port, under each of the three
  settings, on a real node with a real session.
- Still dev: `bb container new` from a session was not walked; nor was a
  session's `start`, `stop` or `restart` by an instance's name.
