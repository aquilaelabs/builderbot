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
   them as a job. *Snag, fixed on the spot:* moving the packages store onto
   the squashed share failed on `cp` preserving the destination root's
   timestamp, an empty store at that; the agent copies a store's entries now.
   Applied again, every store was on the share and the row said so.
5. **Tools.** Installing `node` was refused: the packages store is a share,
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
and the platform tools were installed from the Tools tab with the node
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
fixed: the agent rewrites the line after every apply); and the Tools tab
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
  (Send, build, Up, the route); the Android toolchain from the Tools tab and
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
