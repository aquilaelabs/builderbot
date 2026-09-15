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
