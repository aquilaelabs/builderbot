# Projects

Every project is a git repository under `/workspace`, shown as a card on
the **Projects** page (Projects on the rail) and opened as a page of its own,
described in [notebook.md](notebook.md). This doc covers the Projects page,
making a project (new, cloned or from an archive), linking it to a git host,
its menu and its settings, archiving and deleting it, and how its repository
is reached: push rights, tokens, deploy keys and FTP.

## The Projects page

The **Projects** page shows every project under `/workspace` as a card with
its branch and node, and **Start agent** (**Open** and the agent's name, in green, while
your session runs), **Shell** and a menu on each. The bar holds a search,
**New project** and the bin; the cards can be kept together in groups of your
own (**Group**, in a card's menu), and archived projects are folded under
**Archived** at the page's foot. A problem is
said on the card rather than hidden: an **error** in red, a directory the
container user cannot read/write/enter (with the `chown` that fixes it) or
one holding no valid git repository, and a **warning** in amber, because
it is asking for something. This is what
makes one mapping for the whole folder workable: a directory that is not a
project says so instead of quietly not appearing. Hidden directories are
skipped outright, and empty directories are never listed either: a mount point waiting for
content is not a fault to report.
A directory holding a **`.bbignore`** file is not a project and is not
listed: the container writes one into any path of its own that lands in
the projects share (the toolchain store, if you map it inside the projects
folder rather than beside it), and you can create one by hand for anything else
you would rather not see. It *hides*; archiving **blocks** a session, which is a
different promise.

## Making a project

In the page's bar, **New project** creates one. A fresh local repo
(`git init`) asks for a name and a free-text *Brief*: what you want
built. The brief is not the project's `CLAUDE.md`, which every session
reads as standing instructions and which would go on asserting the first
day's decisions after the project moved past them. It is kept in the tree
as `BUILDERBOT-BRIEF.md`, out of git through the repository's own exclude
file, for the first session: pressing Start agent on the project opens
it in a dialog, editable, beside the model and effort that session starts
on. **Build it** starts the session with the brief as its first prompt;
**Start without it** starts one that was not given it. Either way the
brief leaves the tree then, and the project page's Overview keeps it,
as `bb brief` prints it. When nodes are
enrolled it also asks which node the project runs on (the only one is
picked for you; *none* is an option), the same setting the project's
settings change later, so a new project can build and start a
session without a second dialog. It asks the same way what a session
may enter into the notebook (add to the roadmap, file bugs, add rules,
fill in build and test), auto unless you say otherwise, so that is a
choice made rather than a default found later. It can
also start from an archive you already have: zip, or tar with gzip, bzip2
or xz, unpacked into the new directory before `git init`. However it
arrived, the code map a session asks before grepping (`bb map`) is built
for it in the background the moment the tree is there: the dialog closes
as usual, the card says *mapping the code* for the seconds it takes, and
a session on that project waits for it, so its first question
about the tree is answered from an index rather than by building one. A single
top-level folder inside is dropped (the project directory *is* that
folder), desktop junk like `__MACOSX` is skipped, and no brief is asked
for: an archive is where that project starts, so the field goes when one
is picked, and a request carrying both is refused.
Nothing is committed; the first session, or you, decides what the first
commit is. Paths that would land outside the directory are refused whole. A clone
of a GitHub repository asks for nothing but the URL: it is fetched with the
container's own access (a deploy key or PAT that can already reach it).
The directory takes the repository's name. A repo that carries a
`CLAUDE.md` keeps its own, untouched, and one that does not gets none:
the briefing a session reads is assembled by the controller, and an
untracked draft in somebody's checkout was not worth the mystery.
For a private repo with its own deploy key, a **Deploy key** picker lists
what the shielded agent holds (public halves only, via `ssh-add -L`) and
shows the selected key for copying into the repo's GitHub deploy-key page.
Picking one makes the server handle the container side: it writes the
`.pub` selector and an `IdentitiesOnly` ssh alias
(`bb-<key>`, in a namespace of its own so hand-maintained config is never
touched) and clones through the alias, which the remote then keeps, so
later pushes offer the right key too. Only the matched agent key's own
public line is ever written; nothing from the request is. With a PAT
configured (a per-project token, or `gh auth login`) the key is optional even for
private repos: gh answers for plain https remotes.

## Linking a project to a git host

Every repo's menu carries its **remote** whichever state the project is
in: for one with **no remote at all** it is **Link to a git host**, and
for one that already has a remote it is the host's settings (**GitHub
settings**, say): the access token, which credential git reaches for, the
repository's address, and **Unlink**, all described under
[An access token for one project](#an-access-token-for-one-project),
[A new address for the same repository](#a-new-address-for-the-same-repository) and
[Unlinking](#unlinking).
Linking looks like the bottom of the clone form: the repository's address
first, and under it a **Host** row that reads the address back: GitHub,
Gitea, Forgejo, Codeberg, GitLab, Bitbucket, or another git host. A public
host names itself and the row says so, locked. A server nobody has
answered for is the one case where the row is a question, because a
hostname does not say what is running on it and only the person who set
the server up knows; the answer is remembered against that host, so the
second project on the same server is read back rather than asked again.
Then it asks how the push authenticates: a **deploy key**
the agent holds, or an **access token** for this project alone, checked
with the host where the host has an API to ask, stored under `/config` and
read by git's helper. It sets `origin`, records the project as able to
push, and pushes the current branch, but **only into an empty repository**:
`git ls-remote` must come back with no refs first, so linking can never
write over existing work. A repository that does not exist at all is
created for you, always private, and only after the host itself has
answered "not found": through the host's own API on GitHub, Gitea,
Forgejo, Codeberg and GitLab, and through `gh repo create` on the GitHub
path that uses the container's PAT. On a host with no API (Bitbucket,
anything else) the repository has to exist already, and the refusal says so.
The name is one path segment and the URL must be an https or ssh address
with an owner and a repository in it: `git clone` accepts transports a web
form should never reach, so anything else is refused server-side rather than
passed along. A path deeper than `owner/repo` is refused too, except on
GitLab, where subgroups make it a real part of an address.
**A clone and a first push run in the background**, like an SDK install
does: everything checkable is checked while the dialog is still up (the
name, the URL, the key, whether the directory is free, whether the repo
already has a remote), and then the dialog closes and the work carries on
server-side. The job appears as its own band above the Projects page's
grid, saying what it is
doing: an ellipsis, not a percentage; git's progress is a
carriage-return animation on stderr and parsing it back into a bar is a
fight not worth having, with an **Abort** that stops it and removes a
half-cloned directory. Close the page, sleep the phone, come back later:
the job belongs to the server, and a reload picks it up mid-flight. If it
fails, the message stays on the page until you dismiss it rather than
passing through a toast you may not have been there to see. `git init` is
the exception and stays synchronous; it is done before a spinner would
render, and a row that flashes up for one frame is worse than none.

## A project's card and its menu

A card, and the header of the project's own page, carry two actions,
**Start agent** and **Shell**, and a menu for the rest: **Link to a git
host** (or the host's settings, once linked), **Lend your phone** when your
phone is connected on its node, **Report a BuilderBot bug**, **Archive**,
**Pin**, **Group**, **Color**, **Settings**, and, on the card, **Delete**.
**Color** is your own color for the project, a stripe down its card, its
page's header and its terminals' tabs, so several projects tell apart
without reading each name; **Group** is a label of yours that keeps
projects together on the Projects page, and nothing else follows from it.

**The node** beside the branch on every project's card and in its page's
header is the node its work runs on. A project with none says nothing more;
its Start agent is ghosted with where to pick one.

**A pin** per project, **Pin** or **Unpin** in its menu, decides whether
Home's glance shows it.
The pins are each person's own: unpinning takes a project off your glance
and nobody else's, and nothing else: the Projects page lists everything
under `/workspace`, pinned or not, with the same controls on each card and
*unpinned* after the name of one that is not. Pins live per account in
`/config/pinned-projects.json`. An account made since 7 Oct starts with
nothing pinned and pins what it wants from the Projects page; one made
before that with no set yet still sees everything pinned. The page lists
projects by name, case aside.

**Delete** moves a project to `/workspace/.trash/<name>` with every
file kept: a second delete of the same name is numbered rather than
overwriting the first, and `/config` is not touched, so putting one back is
a `mv`. It is **Delete** in each card's menu on the Projects page and
**Delete project…** at the foot of every project's settings, and the bin in
the page's bar lists what was deleted, to put back. It is deliberately not a
bare button on the card.

## A project's settings

**Settings** in each project's menu opens that project's own settings, which
are also the Settings view of its page, in sections: General (its name),
People, Agents may (what a session may enter into the notebook, and how much
of the tree it may change without asking), Just for you (how a session replies
to you there, and the name and email your commits carry), Repository, Nodes,
Build and test, What sessions reach, File access, Snapshots and Running
sessions; its Android signing keys are a view of their own, Signing, in Ship.
The git credential is not in it; that is the remote, in the
same menu, so a credential has one home whether or not the project has a remote
yet. Renaming changes the name it is shown under and nothing else (R154):
a project has a permanent id and a directory that is never handed out again,
and everything (the notebook, the containers, the sessions, the agents' own
transcripts and memories) is keyed by the directory, so a rename moves
nothing and needs nothing closed first. A name follows GitHub's rules for a
repository's: letters, digits, `-`, `_` and `.` only, each run of anything
else one `-`, so "Turing Lens" is shown as Turing-Lens, and the field says
so as it is typed. Two live projects are never shown under one name: a
second gets Name-2, whether it was created, cloned or put back from the
trash. A name ever used gives a new project the next free
directory (Name-2), deleted for good included, while it is still shown as
Name, and the New project dialog says so as the name is typed; so it never
inherits an old project's notebook or containers, and a project put back from the trash always fits where it was.
Each project also has an id, P and a number (P3), shown first on its card's
and its page's facts line: it never changes and is never given to another
project, so it names the project for good. A Claude session is named after
the project with its id, "builderbot (P3)", which is how the Claude app lists
it, and `bb -p P3` names it as `bb -p builderbot` does.
Only BuilderBot makes a project (create, clone, or start from an imported
archive): a folder made by hand on the share is not listed, and the folders
already there when this arrived were recorded once, as they were.

## Archiving and locking a project

**Archive**, in a project's menu, puts a project out of sight and changes
nothing else: its card folds under **Archived** at the foot of the Projects
page and leaves Home's pinned projects, and the project keeps working for
everybody on it, sessions included. **Unarchive**, in the same menu, brings
it back. The project's owner or an administrator archives one.

**Lock** keeps people out of a project, and it comes in two kinds. The
project's owner locks it with **Lock**: every other account's session on it
ends, and until the owner presses **Unlock** nobody else starts a session in
it or changes it, administrators included. An administrator who is not its
owner locks it with **Admin: Lock**: every session on it ends, the owner's
too, and nobody at all starts one or changes it until an administrator
presses **Admin: Unlock**. A locked project stays on the Projects page with a
padlock after its name that says whose lock it is. Locked against you:

- a session of yours is refused at launch, with a message saying whose lock
  it is, on whatever node
- its notebook is **read-only**, and so are its settings, its git actions and
  its containers' settings: the server refuses each write
- reading it (its notebook, its findings, its artifacts, its dev instance)
  works as before

Both lists live under `/config` (`archived-projects.json` and
`locked-projects.json`), so they survive restarts and image updates. The lock
is enforced by the server on every write and by the terminal launcher on
every session, which on a node asks the controller with the session's own
token, because the ttyd URL and the API paths are reachable on their own and
a rule only the page honored would be advice. It is not a sandbox: the file
tools are denied on every project but a session's own, and a session in
another project can still reach this directory through Bash.

## A project of several repositories

A project can hold more than one repository. **Add a repository**, in a
project's menu, picks another project to join it; where the project is one
repository today, it also asks what the project over both is called (its
own name unless you give another). Each repository stays what it was: its
folder, its notebook, its git host link (remote, token or deploy key, push
rights, forge, CI and releases), its version and changelog, its signing
keys and its dev instance. Nothing on disk moves.

What one session needs is the project's: its node, its coding agents, its
people and its Agents may dials. A project of several repositories has one
card on the Projects page and one on Home, under the project's own name and
id, its repositories listed in it, and one **Start agent**. The session it
starts runs on the first repository and works in all of them: each one's
tree is in its view to write, on the same branch name, and `bb` answers for
the repository whose tree it is run in. A session asked for on another of
its repositories is refused and pointed at the first. Each repository's own
page names the project, with its repositories as a switch beside the name,
and its Roadmap and Bugs carry the other repositories' open items under
**Also in** the project's name.

What a project grants others goes by the project: one that reads it reads
every repository in it, including one added later, with no setting changed.
Merging rewrites a read of one of its repositories into a read of the
project, and says which projects now read more.

Merging is refused, saying which repository and why, when one is locked or
archived, when somebody is on one of them and not on another (the session
works in all of them, so everybody on it is on all of them), or when they
work on different nodes. The owner of every project merged, or an
administrator, merges them; never a session.

**Take out**, beside a repository on the project's card, makes it a project
of its own again, with the settings it had before it joined. A project left
with one repository is no longer one of several. Taking one out ends the
project's sessions, since each was started with the grants it had, and a
project that read the project keeps reading every repository that was in it.
The record is `project-repos.json` under `/config`.

## Push rights

A clone is read-only unless you tick **I want to push to this repository**, and
that decision is made once. Three rules, all deliberate:

- **It cannot be turned off.** A working copy that could push yesterday and
  cannot today explains nothing to whoever is standing in it. Deleting the
  project is the way out, which never touches GitHub.
- **One project per repository.** Two working copies pushing to one remote is
  how a branch ends up racing itself, and here both may be the same session on
  different days. Deleting the holder frees it.
- **The token is checked first.** Before the clone starts, GitHub is asked
  whether that token can actually push to that repository: a missing scope
  otherwise surfaces days later as a failure with nothing connecting it to the
  box you ticked. A deploy key cannot be checked this way short of pushing, so
  it is taken at its word.

Enforcement is a `pre-push` hook, which is transport-agnostic; it catches an
ssh push through a deploy key exactly as it catches an https one, and refuses
with a sentence rather than an auth error. Like the sibling-project rule it is
a guardrail, not a sandbox: a shell in the container can delete it.

A grant names the **host as well as the path**, because `sean/app` on GitHub
and `sean/app` on a Gitea in the cupboard are two repositories: mirroring one
to the other is a reason to link a second project, not a collision to refuse.
Grants written before there was more than one host are stamped as GitHub's
once, at startup, since nothing else could be linked when they were made.

## An access token for one project

Cloning a private repository asks for an optional **access token**. It is
written in git's own credential-store format to `/config/gitcreds/<project>`,
mode `0600`, and named from that repository's `.git/config` and nowhere else,
with git's empty-value reset ahead of it, so the globally configured helper is
never asked and no container-wide token authenticates the fetch.

That last part is the point. A token minted to reach one private repo usually
reaches every repo it was scoped to; in the environment it also reaches them
from every project and every session. Here it opens the one project you gave it
to, and stays with that project whatever it is renamed to.

A project that already has push rights can be given a token from its host's
settings, in its menu, including one that pushes with a **deploy key**. Setting one there
does not switch anything by itself: git never asks a credential helper about an
ssh remote, so a project with an `ssh://` or `git@` origin goes on using its
key however many tokens are stored for it.

The same section holds the project's **deploy key**, beside the token:
**Make a key** makes one and **Paste a key** keeps one you already have. The
private half goes on stdin to a root-only helper (`deploy-key`, the builder
account's second sudo rule), which keeps it under `/config/deploy-keys` and
loads it into the shielded agent, so a session pushes with it and never
reads it. The public half is shown with **Copy public key** and a link to
the host's deploy-keys page, the key becomes the ssh remote to switch to,
and a key in use is not forgotten out from under the push. A key dropped
into the secrets folder's `ssh/` by hand works as before.

None of this is GitHub's alone. The same dialog, the same file and the same
switch serve a Gitea, a Forgejo, a GitLab or anything else git can reach; only
two things differ by host, and both live in `forges.py`: whether a token can
be checked before it is stored, and whether a missing repository can be
created. Where the host has no API for either, the first fetch is the check
and the repository has to exist already, which the dialog says in a line.

The **Authentication** segment beside that field is what changes it. Three
answers, not two: *Disabled*, *Deploy key* and *Access token*. It shows which
one the remote actually reaches for and lets you move between them; the change
is applied when you press Save, which is also how a token typed in the same
dialog gets written before the switch that needs it. Under the hood it is one
`git remote set-url`, between `git@…:owner/repo.git` and
`https://host/owner/repo.git`, plus the credential helper.

*Disabled* is a real answer rather than the absence of one: the remote keeps
its https form and the helper comes off it, so a push is refused instead of
quietly falling back on whatever else git can find. It is also what makes the
dangerous case sayable: **clearing a token while the switch still says
*Access token* is refused at Save**, in those words. The pick is left exactly
where you put it and the reason is stated, rather than sliding to another mode
on your behalf: being corrected without being asked is how you end up on a
credential you did not choose.

**Test**, under the segment, says whether it works before a session finds
out (the operator, 7 Oct). It runs `git ls-remote` for the read and `git push
--dry-run` of HEAD to a branch nobody has for the write, which the host refuses
at the handshake when a deploy key is read-only or a token cannot push, and
which sends nothing; the project's own pre-push hook is skipped, so a clone
without push rights is still asked about its credential. For a token it also
asks the host's API what git cannot see: on GitHub a classic token's scopes
(without `workflow` a push touching `.github/workflows` is refused) and the
repository's push permission, on GitLab the role and the token's scopes, on
Gitea the push permission. What is missing is listed in red under the button
in the host's own words with what to change; a token typed and not saved yet
is what is tested, from a credential file of its own that is gone after.

The https address it writes is the **host the remote is actually on**, not a
constant: a deploy-key remote names a `bb-<key>-<host>` alias, and the server
it stands for is resolved out of `~/.ssh/config` with `ssh -G`, which reads
the file and touches no network.

**A stored token is closed, not shown.** Only its file has the value, so the
field cannot be pre-filled and typing over an invisible one is how a working
credential gets replaced by accident. It is disabled, with **Clear the stored
token** under it: pressing that opens the field for a new one, ghosts the
*Access token* side and puts the choice back on *Deploy key*. Like everything
else in this dialog it is staged: the project changes when you press Save,
and the link offers the way back until you do.

Clear the only credential a project has and both sides go quiet, with a line
saying it cannot push to GitHub and that everything else, commit, branch and
build, still works locally. The field stays typeable there deliberately:
ghosting it would be tidier and would leave no way back to pushing.

**Switching removes neither credential.** The token file stays in `/config`,
the deploy key and its `~/.ssh/config` alias stay where they are, and the
repository keeps its credential helper: an ssh remote simply never consults
one. So going back costs nothing, and the exact alias is restored rather than
guessed, because the alias is named after the *key* and there would be nothing
in the project to guess it from. A side you cannot take is shown disabled with
the reason: a project with no token stored, or one that has only ever been
https and so has no key remote to return to.

**It is not shielded the way a deploy key is.** Those are served by a root-owned
agent and cannot be read at all. This is a file owned by the same user your
shells run as, so a session with Bash can read it. Better than an environment
variable every process inherits, and not a secret store, for a repository
where that matters, use a deploy key.

The credential is filed under the **scheme, host and port** the remote uses,
because that is what git matches a stored line on. A token written against
the wrong one is a file git reads and then ignores: a credential that looks
stored and authenticates nothing, so the host is never defaulted. The
username beside it is a formality every host here accepts; where the host has
an API it is the account the token actually belongs to, asked for at the same
time the token is checked.

## Unlinking

**Unlink** sits at the far end of that dialog's foot, in red, with the verbs
that cannot be undone. It takes four things off, and the answer names each:
the `origin` remote, the stored access token, the credential helper pointing
at it, and the push grant, which is what frees the repository for another
project to be linked to it.

**It touches nothing in the tree.** No commit, no branch, no file, no reflog:
the history that was pushed is still here and can be pushed again the moment
something is linked. It is local and instant: the host is not contacted at
all, which is one of the reasons to reach for it, since the server may be the
thing that has gone. Any remote other than `origin` is left alone and named
back to you.

The deploy-key alias in `~/.ssh/config` stays as well. It is named after the
*key* and the host, not the project, and another project may be using it.

Unlinking is also **how a project moves from one host to another**: linking
refuses a repository that already has a remote, so this is the first half of
the move and pointing it at the new host is the second. The same repository
at a new address on the same host is not a move, and needs no unlinking:

## A new address for the same repository

Renaming your account or an organization on the host changes every
repository's address under it. The host redirects the old one only until
somebody claims the old name, so the remote should follow. **Repository
address**, in the same dialog, is where: type the new address and Save.

Only the path changes. The remote keeps its form (https, ssh, or a deploy
key's alias, which is named after the key and reaches the same host), the
access token stays filed under the host it always was, and the push grant
moves to the new path, so pushing carries on with nothing typed again.

Saving asks the new address for its branches and needs one of them to be a
commit this project already has: a renamed owner keeps every commit, while a
typo or another repository has none. Refused, with the remote left where it
was: an address on another host, a repository another project may push to,
and one that shares no history. A fork shares history too, so this checks
that it is the same history, not the same repository on the host's books;
that difference is why it is the administrator's control.

Changing it does not wait for the project's terminals to close: the address,
like the token and the authentication switch, is `.git/config` and the
store, which a running session reads on its next push. Only a new name, which
moves the directory, still asks for them to be closed first.

## File access over FTP

A project's tree can be reached from outside BuilderBot with an FTP client
(R151, the operator, 7 Oct): the **File access** section of its settings
turns it on, picks the port, and gives each account that sees the project
**Read** or **Read and write**. Setting it up is the project owner's or an
administrator's; signing in also needs File access on the account's roles
on that project (R152), and gets the lesser of the two, so a role without it
refuses even the project's owner. A session never may set it. Anybody else on the project
is shown only that it is on, and where.

The server is the project's primary node's: the **ftp** toolchain's
`bb-ftpd` (pyftpdlib), one per project, which the agent starts from what
hello hands it, as the session account, rooted at `/workspace/NAME`, so a
file written over FTP is owned as a session's would be. It listens on the
port and uses the nine after it for passive data, which is why two projects
on one node are kept ten ports apart; the first free block from 2121 is
offered. TLS is required on the control and the data connection (FTPS,
explicit), because the password is the account's own BuilderBot password and
plain FTP would carry it as written. The certificate is made on the node the
first time and kept in the session account's home, so a client asks to trust
it once.

`bb-ftpd` knows nobody's password. Each login goes up its stdout to the
agent, which asks the controller's `ftp-auth`, and the answer goes back down
its stdin: the name and password checked as the dashboard's sign-in checks
them, then the access the project's settings give that account, and none for
an account since taken off the project. Nothing is cached, so an access taken
away holds from the next login. Ten failed logins from one address in five
minutes refuse that address for the rest of the window, and every login,
failed or not, is in the audit log. The project's `.git` is read-only over
FTP whatever the access, and nothing outside the tree is reachable, a
symlink pointing out of it included. A node whose store has no ftp
toolchain is said in red under the section as soon as it is ticked, from
the node's last report, before anything is tried; the tick stays usable,
so the port and the access can be set before the install. Save, when it
turns the server on or moves its port, asks the node's address from the
controller whether anything answers on the port or the nine after it and
refuses, naming the ports, when something does; the project's own running
server is not asked about.
