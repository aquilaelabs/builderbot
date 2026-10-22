# People and access

The People group on the rail holds **Users** and **Roles**, for an account
that may read accounts, and **Settings** holds each person's own
**Profile**. This doc covers the first account, accounts and roles, a
project's owner and its invitations, what each account keeps of its own,
several people on one project, the chat, and a user's console. The design
and its reasoning are in [users.md](users.md).

## The first account

**There is no password setting.** The first page the dashboard serves asks you
to make the **owner** account, and it is the only page it serves until you
have; nothing else is reachable, signed in or not. So open it as soon as the
container is up: until somebody claims it, whoever can reach the port can.
The setup page follows (R199, R267): four steps, each a card with its state
and its own button. A first node cannot wait: **Create sandbox VM** or
**Enroll node** in its card opens the Nodes page's own dialogs, the card says
when the machine dials in, and **Finish** stays shut, on the server too,
until a node is enrolled, answering and running sessions: a hosting-only node
holds no code, so a project would have nowhere to work or build. Then your
name and email (no session starts without an author for its commits),
Claude Code on that node, and a first project, which can wait: after Finish,
Home's Getting started card keeps what is left of them. Where what grows is
kept and when an idle session ends are not asked; their defaults are under
Controller settings. A public hostname and hosting-only nodes come later,
from Controller settings and Enroll node.

Afterwards, `bb users passwd <name>` changes a password and `bb users add`
makes the others. `bb users token <project> [<account>]` mints the scoped
session token a Claude session is given, for proving a node by hand, where
`bb` reaches the controller with `BB_TOKEN` and nothing else; with an
account named it is the token a node-bound terminal carries, which is also
what reports that account's Claude sign-in on the node.

## Accounts

The **Users** page (People > Users on the rail) lists the accounts beside the
one picked, whose settings (its name, roles and projects, profile, git
identity and a new password) are saved together, with **Remove** at their
foot; **Add user**, at the right of the page's bar, adds one. There is exactly one **owner**,
undeletable and renameable; an **admin** can do everything except act on the
owner; a **user** gets the projects you give them and the work inside them,
but not deleting one, renaming one, or changing which node it builds on: a
node is shared, and that setting reaches every project on it.

**The project list means the same thing for every role; what differs is the
remedy.** A project not on your list is read-only: no Claude session, no
notebook edits, no rebuild. An admin is shown *every* project: hiding one
from somebody who administers the box only sends them looking for it, with
the ones they have not taken on marked read-only, and they can add any of them
to their own list themselves. A user is shown only what you give them, and
cannot grant themselves anything. So for an admin the list is a seatbelt
against working on the wrong project; for a user it is the boundary. The
owner wears the same seatbelt (R135): they see every project by role and
work on the ones on their own list; the one difference from an
administrator is that the owner may add themselves to an invite-only
project without an invitation.

**Roles and permissions.** Everything an account may do comes from its
roles, made on the **Roles** page (R152, the operator, 7 Oct). A role is a
**kind** (**Everywhere**, which holds on every project and is the only kind
that reaches the machinery, or **On a project**, given per project and
holding there) and, per area, **Read** and **Write**: Projects, Project
settings, Releases and versions, Git authentication, File access, Containers
and Terminal on a project; Nodes, Toolchains, Jobs, CI runner, Accounts and
roles, New projects, Controller and Storage beside them. On an Everywhere
role the areas that reach a machine (Nodes, Toolchains, Jobs, New projects,
Storage) open on the nodes, and CI runner on each runner, with Read and Write
on each, every one ticked being every node, those added later included: a
role with New projects to write on bb-sandbox alone lets an
account make projects there and nowhere else, a project made elsewhere or on
no node being refused by name, and the account owns what it makes, so it
holds PROJECT_owner on it. Write needs Read, and an area without Read is not shown. Terminal's
Read is the shielded Claude console and its Write the full tmux shell, which
reaches every account's files on its node.

**owner** and **admin** are built in with everything; an admin may not change
the owner's account or roles. There is no built-in user role: an account
added holds none and may do nothing until it is given one. A project's owner holds
`PROJECT_owner` on it, every project area to write, made when the project is
and moved with it when it changes hands; it is an ordinary role, so cutting
it back (taking File access off it, say) holds for whoever owns the project.

A person may do what their roles give and nothing else: an account on a
project's list with no role there works on nothing. A Claude session does no
more than the person behind it: what its own rules (its project's Agents may
dials, a session's limits) allow and what its account's roles give on the
project, whichever is less, the projects it reads included, so a session of
somebody who may only read a project can only read it.

An area without Read is not offered (the status carries each area's level,
and the rail does not draw its page), and the server holds the same line: the
Users and Roles reads, a Claude console without Terminal Read (no terminal
at all), the Jobs listing (a person's own projects' jobs alone) and the
Docker listing (the projects whose Containers they may read). Without Nodes
or Toolchains Read those reads answer only for the nodes of the person's own
projects, which a Claude sign-in there needs, and never for another machine.

The **Roles** page lists the roles beside the one picked (the projects'
owner roles folded into one row at the list's end): its kind, what it is
for, and a Read and a Write per area, with **New role** at the right of the
bar and **Remove** at the foot; owner and admin are built in and read only.
What one account holds (its Everywhere roles, the projects it is on and its
roles there, and what that adds up to) is picked in its settings on the
Users page. A project's owner who is not an administrator gives people roles
on the projects they own from a name in that project's People section, and
nothing Everywhere. Every gate on the server reads the same roles
(`users.may` through `roles.CAP_AREA`), which keeps the pages and the
refusals consistent.

**Every project has an owner, and an owner can close it to administrators.**
Whoever made a project owns it; one from before there were owners belongs to
BuilderBot's owner. Under **People** in the project's settings
BuilderBot's owner hands it to another account at once, and the project's own
owner offers it: the offer waits in the other person's bell like an
invitation, and the project changes hands when they accept (and only if the
one who offered still owns it then). Either can make it
**invite only**: then nobody else changes who is on it, so an administrator
can still see it but cannot add themselves, or anybody, on the Users page or
anywhere, and people join by invitation. BuilderBot's owner is never kept
out. **Invite** there picks an existing account, user or admin; the
invitation waits in that person's bell with **Accept** and **Decline**, and
accepting puts the project on their list. Whoever invited, the owner, or
BuilderBot's owner can **Withdraw** one still waiting. On a project that is
not invite only any administrator may invite too, as they could always add
people. A session has no say in any of it.

Each account works as itself:

- **its own home**: own shell history, own Claude login, own memories. The
  box's own dotfiles are shared into it rather than copied, so the Android
  pairing key, the AVDs and the build caches are not duplicated per person
- **its transcripts and memories in one place whichever machine ran the
  session**: the home's `~/.claude/projects` is a link to the account's own
  directory at `/workspace/.claude/<uid>/projects`, made on this container
  and on every node alike (a node keeps that directory itself and its agent
  mirrors it here), so a
  conversation held on a node is offered here to resume and its memories
  show in the Memories on the project's Overview. A home that already held transcripts has them copied across
  once, the original kept beside the link as `projects.moved-<date>` for
  you to delete. The login itself stays in the home, per machine
- **its own terminals.** A shell session is named for the account, so two
  people opening a terminal on one project do not land in the same one
- **its own open terminals and color scheme**, which follow the account to any
  browser it signs in on rather than living in one browser
- **the owner keeps this container's original home and session names**, so an
  install with one operator is unchanged by any of it

**More than one person can work a project at once, in a working tree each.**
The owner works in the project directory as always; anybody else gets a **git
worktree**: a checkout of their own, on a branch of their own, sharing the
project's one `.git`. That is what makes it safe, and coordination inside one
tree could not have been: `/workspace/<project>` is a single working tree, so
two sessions in it commit each other's half-finished work and delete it with a
`checkout`. Separate trees make that impossible and put the conflicts at the
merge, where git is good at them. A worktree session builds into its own
`dist/`, which the Artifacts view lists apart from the project's, under whose
worktree and branch it is, with Download and View; Install and Push stay with
the project's `dist/`. The dev instance belongs to the project rather than to
the session.

## Chat

**Chat** is the first tab on the dock's line, at the foot of every page, with
its unread count beside it. It lists the
other accounts (a green dot for whoever is here right now) and, under them,
the **project channels**, which are group chats for everybody on a project. A
channel carries what people type into it *and* what the box notices: a Claude
session started, a rebuild, and what each person asked Claude. Three people on
one project not doing the same work twice is the whole point of it.

An admin is shown every project's channel, since they are shown every project,
with the ones they have taken on marked and sorted first. A `user` has the
channels for the projects they were given. Reading and answering a channel is
not a change to the project, so it follows what you can *see* rather than what
you have taken on.

**Prompts on a shared project are not private**, and the chat says so where
the channel is drawn rather than leaving it to be discovered: what you ask
Claude on a project you share goes to the people you share it with.

`bb work` says who else is in the project and which files two of you have
uncommitted at once. Two answers, and the cheap one is the truthful one: **git**
is exact: a file changed in two trees at once is a collision whatever anybody
intended, and it needs nothing recorded, while a **PreToolUse hook** adds the
finer grain, naming the definition an edit lands in, which is a guess and is
labeled as one. The hook also tells the second session, before its edit, that
somebody else has that file open. It does not refuse it: each session is in its
own worktree, so two people editing one function are making two commits rather
than corrupting one tree, and that is what a merge is for.

Each account signs in to Claude for itself, on each node it works on, from
that node's Agents page (Build, then Agents, with that node picked). Which Anthropic account that is is the person's own choice:
the Users page says when two BuilderBot accounts are on one, since Anthropic's
terms allow one person per Claude account, and nothing is refused for it.

The notebook (roadmap, bugs, analysis) stays shared, because it is about the
project; memories do not, because they are about the person.

## A user's console

**A `user` has no shell and no command line at all**, and that is what makes
the rest of the role mean something: everything else is enforced by the
dashboard, in Python, and a terminal is the way around all of it. So a `user`
gets no shell, and their Claude session opens as a **console** instead:
the real interface, rendered by a `ttyd` started without `--writable`, with
a box to type a message and a button to end the conversation. The proxy
refuses anything else they ask a terminal for, so a read-only window cannot be
pointed at somebody else's session. They see the Containers and Toolchains pages
for their own projects' nodes: the scoping is on the answer, not just the
picker, so a node none of their projects builds on is refused rather than
listed, and change neither, with one exception: **Rebuild**, and Abort with
it. Building what you committed and looking at it is the point of having the
project, and Rebuild is also how a stopped instance comes back; the page
already ghosts it until the code has actually moved. They cannot create or
rename a project, change how one authenticates, or touch a stored token. What
they can write is the notebook, a rebuild, and a Claude session on a project
they were given.

## Your profile

The gear in the header keeps what belongs to this **browser**: the color
scheme (Dark, Light or System, and the schemes) and the time zone, and one
entry, **Profile**, which is also **Settings** on the rail: the signed-in
account's own page, in sections. **Who you are** holds the account name,
their name and email, and the name and email their commits carry (blank means
the ones above); **What you may do** is what their roles add up to;
**Password** is a change that asks for the current one first; **Claude
plugins** lists the plugins they installed; and **Signed in as you**, last, is the devices signed in as this account (a
line a device, with when it last called and **Disconnect**, which signs that
one out).

Neither a Claude session nor a shell starts for an account with no
name and email for commits, and `bb git` refuses for it: every project is a
repository, and a shell is where git is typed, and the project's Start Claude
and Shell say so until the Profile has them. Blank git fields fall back to the name and email
above and to nothing else; no address is ever made up. A project's
notebook has **Sessions** beside Overview: the account's own conversations
with Claude on that project, newest first with the first thing typed, each
with **Resume**, which opens the Start chooser on that conversation (the
project's Claude button resumes only the last), **Read**, **Download**, and
behind its ⋯ **Make visible**, which lets every session on the project read
it with `bb transcripts` until **Make private**, and **Delete**, for good (one
still being written by a running session is refused). A session never
deletes or shares one. The download is a text file: what
was said on both sides, every command Claude ran and what the command
answered, `bb roadmap` and its reply included, from the transcript Claude
Code writes as the session goes (transcripts.py reads the account's
`~/.claude/projects` directory, the one on the share). Each line is
stamped in the browser's own zone, the one the page shows times in, so the
log and the page agree; a line headed System is what BuilderBot or Claude
Code put in front of Claude. Claude's private reasoning is not conversation
and is left out, and another account's file is simply not found. A session
reads the same: `bb transcripts` lists the account's own conversations on
its project and `bb transcripts show ID` prints one, and with `bb -p NAME`
the same on a project its own reads, whose transcript files of the account's
are in the session's view read-only as well; nobody else's are anywhere. The commit identity is per account rather than per project, and
reaches every session and shell that account opens as git's environment,
which outranks whatever a repository has configured, so two people on one
project are two authors.
