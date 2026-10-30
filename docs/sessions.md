# Sessions

A session is a coding agent running in a terminal on a project's node:
**Claude** (Anthropic's Claude Code), **ChatGPT** (OpenAI's Codex CLI) or
**Copilot** (GitHub's Copilot CLI), started from the project's card or page
with Start agent and kept in the dock at the foot of every page. This doc
covers starting one (the agent, the node, the model and effort, the
sign-in), the Sessions page, what a session sees and reaches, what it is
told and how it is held to its rules, and its token. The terminal itself is
in [dashboard.md](dashboard.md#the-dock-and-its-terminals).

## The three agents

Each agent is used the same way, and the same things hold for each: one
briefing, the house rules' guards, the project's view and walls, the dock's
working, waiting and asking states, the transcripts and Resume, and `bb`.
Where they differ is how each takes those, in its own form:

- **The briefing**: Claude reads it as a system prompt file; ChatGPT as
  developer instructions added to Codex's own; Copilot as an instructions
  folder it reads like a project's AGENTS.md. None of it is written into
  the project's tree.
- **The guards**: Claude's are the hooks in its generated settings file;
  ChatGPT's and Copilot's are each agent's own hooks, written into the
  account's hooks file for it, every one running the same list. Codex's
  are trusted for each launch by the hashes Codex reports for them.
- **The conversations**: each agent keeps its own transcripts, listed on a
  project's Sessions view with the agent named, and Start agent's menu
  offers each agent's last one to resume.
- **The sign-in**: each agent's, per account and per node, on the Agents
  page (see [below](#the-agents-on-a-node-and-their-sign-in)).

Which agent Start agent opens first is your pick for the project; the menu
lists every agent installed on its node.

## Starting a session

**The model and effort are picked when a session starts** (the operator, 12
Oct), not kept in the project's settings: pressing Start agent opens a menu
(the node, Resume or New conversation), and that choice turns the menu to
Model and Effort with Start, opening on the last ones picked here and naming
on *Claude's default* the model the last session answered on. Start keeps
the picks as yours for the project (`claude-prefs.json`, what the launcher
reads) and opens the session on them. A new project's first session picks
them beside its brief instead. While a session of yours is running, the menu
offers a red **Restart** beside Open tab and End session, which ends it and
turns to the same Model and Effort before resuming the conversation; and
the project's card says, under that session in the warning color, what has
changed since it started that it will not see until it is started again (a
toolchain installed on its node that puts something on `PATH`, or
BuilderBot updated, whose briefing a session reads once), and why.

**Changing it while a session is running asks about that session.** Some
settings a session takes only when it starts: the
author it commits as, the projects it reads and the places it sees, its
node, and what its briefing says (replies, questions, how a test run meets
a change, how long captures are kept). Save with one of those changed while
your session is running and the settings name the changes and put two
answers at their foot: *Save and end it*, which ends the session so the next
press of Start agent starts it on the new setting with the conversation resumed,
or *Save, keep it running*, which saves and leaves the session on what it
started with until you end it yourself. The setting lands either way;
only the interruption is asked about. Anything mid-turn is lost when it is
ended, which is the whole reason it asks. Everything else in the settings
(the build and test commands, the dials, where tests run) is read when it
is used, so those save without a question.

**A project's Start agent knows which node it is about.** Where this
account's session is already running, the press opens the chooser rather
than jumping to the tab: **Open tab**, a red **Restart** and **End session**
for the node it runs on (Restart ends the session, asks the model and effort
as Resume and New conversation do, and resumes the same conversation, so it
starts fresh on whatever changed since), and the project's other nodes
offered beside it, so a session on a
second node can be started from the same place. Where this account is
signed in on the project's node, the press starts the session or opens the
chooser with Resume and New conversation, as it always has. Where
it is not, the chooser offers **Sign in on** that node in their place, which
opens that agent's own page on that node, at its sign-in. A
project on several nodes lists each under its name: Resume and New
conversation for a node this account is signed in on, the sign-in for one it
is not, and the reason alone for one where a session cannot start.

**An agent's tab does not come back on its own after a restart.** The
conversation ended with the container; the transcript did not, so the
project's Start agent offers to resume it and that stays a decision you
make. Enforcing it takes two halves: the saved layout drops agents' tabs at
boot, and, because a browser left open still holds its own copy, and a phone
waking up reloads the terminal iframe, which spawns whatever its URL names:
each agent's terminal URL carries the run of the container it was opened in.
One from a previous run is refused where the session would have been created,
with a line saying to open it from its project's Start agent instead.
Shell tabs carry no such marker and never needed one: a shell is safe to
recreate in the same directory, which is why it survives a restart and a
conversation does not.

## The agents on a node, and their sign-in

**Claude Code is a toolchain of each node, installed on purpose, and by
nothing a session can do.** The provisioner does not install it: a node's
Library (under Build) installs it, and the Installed page (under Machines) has its row, with the version its session account
runs against the latest the controller knows, asked on the toolchains' own
clock (weekly, when a node starts, and on **Check for updates**). Until it
is installed no Claude session starts there: the project's Start agent
is ghosted with the reason, and the terminal refuses with the same
sentence. Press **Install** or **Update** there to install or update it:
that ends every Claude session on the node first, then the agent runs the
installer as the session account and, on a managed node, pins the binary
where the account cannot write it, so `claude update` typed in a session
changes nothing that runs (the auto-updater is off there too). **Remove**
takes it off. Nothing starts again on its own: a project's Start agent does,
when you press it, and until the job ends it is held with the reason. A
node behind is a row in the bell, and stays on what it has until you
install the update: nothing updates it before a session starts (a switch
that did went on 7 Oct). The same section keeps each account's sign-in;
the Nodes page keeps one line per node saying which agents are installed and
signed in there, with a button to the Installed page.

**ChatGPT's Codex CLI and Copilot CLI are installed the same way**, each
from its own card on the Library and its row on the Installed page: Install, Update and Remove run the
vendor's installer as the session account and pin the binary on a managed
node, and an agent's update holds its starts there until it ends. A project
whose agent is missing on its node offers Install for that agent in place
of Start agent.

**A Claude sign-in is one account's, on one node.** A person signs in on
each node they work on, and the login stays in that account's home on that
machine: nothing carries it to another node, and the controller holds no
credential, only what each node reported. A refresh rotates the refresh
token, so one login on two machines signs each of them out in turn; a login
per machine is the shape Claude supports. The sign-in is in the Claude
row of the node's Installed page, for whoever is looking: *You
are signed in here as* the Anthropic account that node reported, with **Sign
out**, or *You are not signed in to Claude on* that node, with **Sign in**.
**There is no terminal in it.** `claude auth login` is interactive, printing
a URL and waiting for the code the browser gives back, and a terminal is the
worst place for both on a phone: a wrapped URL cannot be selected out of a
canvas and a paste into one silently does not arrive. The flow runs on the
node under a pty, as a job; the section shows its link to tap and a field for
the code, which goes down to the node on the job's own channel, and what the
flow says when it refuses a code is said there in its own words. The
field passes the code through rather than judging it: the authorize URL the
code page glues to it is cut off, whitespace and control junk are stripped,
and the only pastes refused outright are one with no code left in it and
one far too long to be a code. A running flow, with its link, is shown to
the account it was started for and to nobody else. Sign out asks first and
runs `claude auth logout` on that node, in that account's home; it is dead
while that account has a Claude session open there, which the section
names, and a sign-in on any other node is untouched. A node that is not
answering offers neither, with the reason under it.

**ChatGPT and Copilot sign in with a device code**, each in its own section
of the node's Installed page and as the same per-account, per-node record:
the section shows the link to open and the code to enter at OpenAI or
GitHub, and says who the node reports signed in once the code is taken
(the ChatGPT account, or the GitHub login with a Copilot plan). Sign out
runs that agent's own sign-out on that node, in that account's home.

## The Sessions page

**Sessions**, on the rail, is every terminal and agent's session of your
account, here and on the nodes, one row each: its name, exactly as its tab
in the dock is named and with the same hover text, then its project, its
node and when it started. **Press the name** to go to its tab, reopening it
first if it was minimized. Beside it, **Open** puts back a tab that was
minimized, **Minimize** takes a shell's tab off the dock (it keeps running),
and **End** stops the session. An **on screen** pill marks the ones open in
the dock right now. Every agent's session (in this list and on its tab)
carries a **state dot**:
blue and pulsing while it works, amber when it is waiting on you (input, a
permission decision, or a finished turn), with the task it reported
alongside. That is the phone-glance question answered without opening the
terminal: is it still going, or does it need me? The state comes from the
terminal title Claude Code itself maintains, read through tmux, and for
ChatGPT and Copilot from their own hooks: no polling of the conversation,
no extra process.

**Ending a session for good is End on the Sessions page**, or × on its tab
in the dock. That one asks,
because that is where something is actually lost: the shell and everything
in it, or the agent's conversation (its transcript is kept and can be resumed).

## How many sessions work at once

**How many sessions work at once is a node's to limit**, not a project's:
what a working session costs is the machine's (Claude Code itself, and the
builds and tests it runs), several projects share a node, and each Anthropic
account's own limits are already its own. An administrator sets it in the node's
**Sessions** section on the Nodes page, where the line beside it says how many are
working and waiting now; 0, the default, is no limit. A prompt past the limit
is not thrown away: it waits for a turn ("Waiting for a turn on this node" under
the prompt), and the turns go in the order they were asked for. One that has
waited fourteen minutes is refused with a sentence naming the node and the
limit, since a UserPromptSubmit hook is cut off at fifteen. A session counts as
working from the moment its prompt is let through until it stops, and also
whenever its pane's title shows Claude working, so a session opened before the
limit existed, or one that was interrupted, is counted by what it is doing.

## Keeping a session in its own project

A Claude session started from the dashboard is launched with a generated
settings file that denies its file tools, `Read` and `Edit` (which covers
every tool that writes), access to every *other* project under `/workspace`.
A ChatGPT or Copilot session gets the same walls from its own hooks. Siblings are
enumerated by name rather than matched by
pattern, so a project called `app[1]` cannot quietly take its neighbors out of
the list. That file is passed with
`--settings`, which ranks as a command-line argument: above the project's own
`.claude/settings.json` and `.claude/settings.local.json`, so a session cannot
widen its own boundary by editing files in the repo it is working on. Only the
root-owned managed policy file outranks it.

**On its own this is a guardrail, not a sandbox.** It stops a session wandering
into the wrong tree by mistake, which is the common failure, and Bash is not
under it.

**The hard boundary is the session's view (roadmap R35).** Every session on a
node runs as one account and the node holds every project bound to it, so file
permissions cannot keep projects apart. On a Linux node provisioned as a
sandbox, a project's Claude session and its project shells start inside a
mount, PID and IPC namespace built by `nodes/bb-session`, a root helper that
is the session account's one sudo rule. Inside it `/workspace` holds only the
project, its worktrees and the account's Claude share (other projects'
transcripts are empty); the account's home is the only home and its
BuilderBot cache keeps only this project's folder; `/tmp`, `/var/tmp` and
`/dev/shm` are the session's own; the agent's stores keep only the
emulator's logs and the project's own CI logs and artifacts; the toolchain
store is read-only, so nothing a session writes can reach
a command another account or a job runs (Flutter's own tree is the one
exception, since it writes there on every run, with its `bin` still
read-only); and the process list and tmux server of other sessions are out of
reach.

The view is built from what a session is given, not from a list of what to
hide. At the top of the machine the system's own directories stay (`/usr`,
`/etc`, `/var`, `/opt`, `/home` and the rest), and everything else there is
out: a directory that holds one of the view's own places (the toolchain
store under `/mnt`, say) is covered and that place put back inside it, and
one that holds none is hidden whole, with the mounts inside either let go so
the mount table names no export. The agent's own directory
(`/var/lib/builderbot`) is covered the same way, so other projects' build
caches, their containers' data and the agent's tools are not there. The
base home, which belongs to the account every session runs as, is new in
the view and holds what a session runs from it, read-only: the launchers on
its `PATH` and Claude Code. Its keys, history and settings are not there. So
a share mounted on the node next month is out of every view without anybody
naming it. A share a project works with is named in the project's settings
(**Also sees**, a path on the node, set by whoever may set the project's
node); it is handed to the helper as `--sees` and put back as the node has
it. The helper refuses one that names the system's own, the projects share,
a home or the agent's stores, so the setting cannot bring back what the view
leaves out on purpose. Two things are known to show through: the names of
the account's own other projects, as empty folders under
`~/.claude/projects`, and a share mounted under one of the system's own
directories, which is left as the node has it.

Each account on a node keeps its own tool caches and dotfiles
(`.gradle`, `.m2`, `.npm`, `.cache`, the Rust crate cache and the rest)
rather than sharing the base home's, so a person's first build on a node
downloads its own dependencies. Java tools take their home from the session
user rather than `$HOME`, so a session points Gradle, the Android tools and
the Kotlin compile daemon at the account's home by the variables they read
(`GRADLE_USER_HOME`, `ANDROID_USER_HOME`, `XDG_DATA_HOME`). Updating Claude Code on a node is the
provisioner's; a session's own updater is off. The helper
then drops to the session account with `no_new_privs`, so nothing inside
can gain privilege again. The agent installs the helper, its layout file and
the sudo rule from the bundle, and reports on the node's Sessions section
whether a view can be built and why not. A guest machine or a container
node, whose agent is not root, cannot, and says so there. The
view is not a VM: the kernel is shared, and so is the network unless the
node keeps each session to its own project's network (below).
A workspace-root shell, which needs the `terminal` right, is not confined.

**Each session on its own project's network (roadmap R79)** is a switch in a
node's Sessions section, off by default. On, a session started there gets a
network namespace of its own from `bb-session`: a veth pair to the node, an
address from `10.231.0.0/16`, and a resolver file naming the node's upstream
DNS servers. The agent keeps an nftables table (`builderbot_sessnet`) that
judges everything leaving a session's link: the internet, the controller and
the DNS servers pass, and so do the containers the session's project owns on
that node (the project a container belongs to on the Containers page, the same
setting that says whose sessions may work on it); everything else that is not
the internet (every other container, the node's own services, the LAN) is
refused, and nothing, on the network or on the node itself, can open a
connection into a session. Only those sessions are touched: every rule matches
their links (`bbsN`) or their range, and everybody else's programs on the
machine keep its network as it was. What passes is
marked, and Docker's `DOCKER-USER` chain lets through only marked traffic
from a session, so if the table ever disappears a session loses its network
rather than gaining the node's. A session reaches its own containers at the
node's address and published port, not at `localhost`, which is its own; the
emulator it starts itself runs inside with it. Turning the switch on or off
applies to sessions started afterwards; one started while it was on keeps
its network until it ends. The section says, in red, when the switch is on and
it is not in force: an agent that is not root, a firewalld or ufw firewall,
no upstream DNS server, an older `bb-session`, or a node whose own network
already uses `10.231.x.x` (a LAN, a VPN or a VM bridge), which a session's
address would hide from everything on the machine. When setting it up fails,
no session starts on that node until it works or the switch is turned off.
A container in Docker's host network mode is not reachable from an isolated
session, since it has no address of its own to allow.

## What a session reaches

**Reads.** In What sessions reach, a project's settings name the other projects a
session on it may read: their trees, bound read-only at `/workspace/NAME`
into the session's view on a node, and their notebooks, which `bb roadmap`,
`bb bug`, `bb rules`, `bb design` and the rest answer for with `bb -p NAME`
in front. Their running containers answer the session too, on its own
project's nodes, so a page of theirs can be opened and photographed with
`bb capture`; a read project's node the reading project is not on stays
out until the operator adds it. Every write is refused by name, on the API
and on the relayed verbs alike, and a session's Claude gets the same wall:
Read allowed, Edit denied. The briefing names the projects a session reads,
and the shipped "stay in project" rule carries the exception. Set by the
operator in the project's settings, never by a session.

**Also sees.** Beside them, a project's settings name the places on its
node a session is shown: a share or a disk mounted there that the project
works with, by its path (`/mnt/media`). A session's view holds no other
(see the session's view, above), so this is how a project is given one. Set
by whoever may set the project's node, never by a session; a path that is
the system's own, the projects share, a home or the agent's is refused, and
a session started after the save sees the place. A path one of the
project's nodes does not have is passed over there.

**Also reaches**, under What sessions reach in a project's settings, opens
the rest by hand (the operator, 7 Oct): a machine its sessions may still
reach, by its address, or one service on it, as `address:port`, without
making the project read another. Each address applies on the project's
nodes ticked beside it when the project is on more than one, on all of them
when every one is ticked, which also covers a node added later. It is
handed to the node with what the project owns there and lands in the same
sets, so sessions already running reach it within a poll, without a
restart. Setting it is an administrator's, since it is a hole in a shared
node's firewall that reaches past the project; a session cannot. An IPv4 address only:
a name or a range is refused by name, as are this machine, multicast, the
sessions' own range and a project's own node, which a session reaches only
through its containers. On a node whose switch is off it does nothing yet,
and the field says so.

## Telling a project's sessions about this environment

Every session is handed one block of text before it types anything, assembled
by the controller at the moment the session starts: a short core of what
holds every time, then the house rules in effect, then the project's own
lines (what it reads, what a new ask does during a test run, its design) and
an index of the rest of how this machine works, then the open roadmap and
the open bugs. The rest is **topics**: each section of the briefing after the
core (start, where, map, build, tidy, speed, capture, asks, notebook,
versions, git, android, gpu, containers) is named in the index with a gist
and read whole with `bb help TOPIC` when the work reaches it, so a session
pays for the manual only where it needs it, and what it is held to comes
first and short, because a rule read after five thousand words of how-to is
read at the same weight as the how-to. A topic the tree gates out (Android on
a project with none) is not in the index and still answers when asked for. The
Overview's *What a session is sent* fold shows a person exactly that string, byte for byte, because it is the same assembly
rather than another rendering of it.

**Editing the list or the memories tells the running session**, in one line, to
go and read them and carry on, not to drop what it is doing. A list edited
under a conversation is a list that conversation is holding a stale copy of.

**The open items go in front of every session the dashboard starts.**
`bb-tty` appends them to the session's system prompt, so a note left on Tuesday
is read on Thursday without anybody remembering to mention it. Items a session
added are marked, so you can see what it put there. It is given as context
rather than instructions: a session works an item when you ask, or when it is
plainly part of what you asked, and adds one when it notices something out of
scope for what it is on. A step that is done is counted and not printed: the
plan's past is a `bb roadmap show` away. The block travels to the session in a
file rather than on tmux's command line, which takes at most 16KB and answers a
longer one with `command too long` and nothing else.

**What is kept and what a session is sent are two things.** A project only
grows, and every conversation pays for the block. So the notebook keeps what
there is (two hundred open roadmap items, the parked ones not counted; two
hundred open bugs; forty standing rules and two hundred named ones), and the
block is an index into it. The rules have a share of a session's prompt,
16 KB: every standing rule whole, since that is what a session is held to,
and over the share the named ones without what calls for each. The roadmap
and the bugs are a count and the verbs: `bb roadmap` and `bb bug` list them,
`show` prints one whole, and the items and bugs a prompt names, by their
number or by words shared with the title, arrive on that prompt through the
same hook that brings a named rule, once a conversation. What a part left out
is said in the part, where the session reading it sees it; and every part is
always there, whatever the others hold.

**And you can read the whole of it.** The Overview's last fold, *What a
session is sent*, holds the exact string a session started here is handed: the
briefing's core, the house rules, the project's lines and the index of
topics, then the roadmap and the tracker as counts, with its size on the
heading and each part's size under it, the rules against their share, so a
part that has started saying less is seen there before a session meets it. It is the same string, not a rendering
of the same idea: the page and `bb-tty` both ask `bb preamble` for it, so the
fold cannot quietly stop describing what sessions get. Shut by default, since
it is a thing to check rather than to read every time.

Two settings shape that string without touching what you read in the
notebook. Each person's **Replies** pick in a project's settings says how
wordy Claude's replies to them are there, and their
**Questions** pick how often Claude asks them, more, fewer or rarely; both
ride the block as its own part and
govern the replies and the asks only, so the notebook, commits and files are
written as ever.

A running session keeps the block it started with. What it hears live: a
named rule on the turn it applies, whatever a `bb` verb answers, and, on
its next prompt after the controller was rebuilt to another build, one line
saying so and pointing at `bb catchup` and `bb preamble`, once per build.

## Holding a session to its rules

Text in a prompt is a request a model can fumble, so the rules that can be
checked are checked as well as said:

- **A named rule arrives when it applies.** A rule with files or words is
  named in the block and its text arrives on the turn a session edits one of
  its files or is asked about one of its words, on a node as on the
  controller: the hooks ask the controller on the trip each edit and each
  prompt already makes.
- **And again after a summary.** When Claude Code summarizes a long
  conversation, the briefing and the standing rules stay in the system
  prompt but a named rule told earlier would be lost; a hook remembers which
  ones a conversation was told and says them again in full.
- **A rule can refuse.** A rule's *Commands it refuses* (`bb rules add
  --refuse`) are the starts of commands a session's shell call may not run:
  the call is refused with the rule's text as the reason. The shipped
  ask-do-not-install refuses the system package managers, and three of the
  briefing's never-do lines are refused in every project (`pkill -f`, the
  emulator binary, setting the account's commit identity). A pattern that
  starts with `!` is an exception, such as a package manager's dry run.
- **A project rule replaces a global one by name.** *In place of* (`bb rules
  add --replaces NAME`) takes a global rule out of that project's block, so
  a session reads one rule rather than two and an instruction to prefer one.
- **The map first.** A search for where a name is defined or called (a grep
  for `def NAME`, `function NAME` or `NAME(`, or the Grep tool's) is handed
  `bb map find NAME`'s answer beside it, a few lines, so the reads the map
  saves are not spent; the search still runs, and a name the map does not
  know adds nothing.
- **Test runs in the background.** A suite started in the foreground is
  refused, since it holds every reply until it ends and a new ask could
  never cut into it the way the project's *While a test runs* setting
  says; the unit tier runs either way.
- **And it can be counted.** `bb rules audit [DAYS]` reads the account's
  own conversations on the project and counts the commands a rule refuses,
  run or tried, and how often the code map was asked against a grep of the
  code, so whether sessions keep to a rule is a number rather than a feeling.

What a session is told is split by one question: is there value in turning
it off? An obligation somebody might reasonably not want (sessions filing
what they notice, chasing a bug they meet, installing nothing, walking a
change in the app before calling it done) is a **global rule**, and what
nobody would switch off (no credential in a repository, a true report,
another person's branch left alone, the project's own files) is a line of
the briefing. The global rules are listed in every project's notebook,
under the project's own rules on the Overview: anybody who works on
the project can switch one off for that project alone, staged behind the
rules section's own Save, and an administrator also adds, edits and removes them,
or turns a shipped one off, for every project from the same place.

None of it is copied into the project. There is no file to render, push, or
keep in step, and nothing to go stale: the briefing is one file in the image
(`config/templates/briefing.md`), the rules live in `/config`, and a project
that has never heard of BuilderBot gets the same briefing as one that has.
The parts that only apply to some projects are marked in that file with the
evidence that decides them, matched as globs against the project's tree, so a
project with no Android in it is not told how to drive an emulator.

`CLAUDE.md` in a project is the project's own notes, committed, and nobody's
to generate. **A session is still held to the current environment**: a hook on
every tool call (`bb-gate`) refuses to run anything while the controller is
not answering, which is what a restart after an update looks like. That is
waited out (R251): a `bb` command that meets a refused connection asks again
for up to ninety seconds (`BB_CONTROLLER_WAIT`; a hook asks once), saying it
is waiting, since a refused connection never reached a server and asking
again cannot do anything twice; the first refusal tells the gate at once, so
the next tool call is held rather than let through by a check from twenty
seconds before; and a held session may still write its own memory, its
scratchpad and its to-do list, so the gate's sentence can tell it, when the
hold lasts, to write where it is and what is next, then end the turn. The
gate leaves a `held` mark beside its stamp while it refuses and takes it off
with the first call it lets through; the node's agent reports the marks with
its heartbeat, so once the controller answers again the bell lists each
session an update stopped, for its own account or an administrator, with a
Resume that types into it (the roadmap's send, which presses Enter only if
the line echoed) that BuilderBot is back and to pick up from its note.

The compatibility window still holds a project whose *node* runs an agent
from another window, and the Nodes page's Update is what clears it. Inside a
window an agent behind the controller is updated by the controller itself
once its node is idle (R253): until then it takes no job but its own update,
so a session's job refused for that alone has `bb` wait for the update (up
to two and a half minutes, saying so) and send it again, and the bell's
agent row says the update is automatic, and why when its last try failed.

## A session's token

**A token lasts twelve hours, and a conversation can last longer.** One is
minted per connection, so opening the session's tab refreshes it, but the
`claude` already running keeps the environment it started in, and nothing
outside a process can change that. So `bb-tty` also writes the fresh token
beside the launcher in the account's own cache (0600), and `bb` reads it the
moment the one in its environment has expired. A long session therefore
recovers by having its tab opened, and until it is, `bb` says the token
expired and when, rather than "not signed in", which sent somebody looking
for a sign-in that was never the problem.

**And it renews itself while the session works.** Past half its life, every
authenticated answer from the controller: a `bb` verb, the hook that runs
on each prompt: carries a fresh token in an `X-BB-Session` header, and the
client writes it into that same cache file; `bb` then sends whichever of
its two tokens expires later. A session in use therefore never runs out; only
one idle for twelve hours does, and that one is told to have its tab opened.
An expired token is never renewed, which is what keeps twelve hours meaning
something for one that leaked. `bb status` says which copy is in use and
when it runs out (the environment's, or the kept one once that has been
renewed past it), so renewal is something to see.

## Catching up after time away

Two things are recorded for no other reason than that a later session will
want them, and neither can be reconstructed afterwards.

The first is which images this container has actually run. It is recreated on
every update, so its own stamp answers only *what is running now*, the boot log
rotates away after a few starts, and with no PAT there is no registry to ask,
which leaves *"which build was the box on when I saw that?"* unanswerable, and
that is the first question whenever a fix appears not to have landed. So the
entrypoint appends a line to `/config/image-log.tsv` whenever the stamp differs
from the last one: first-seen, commit, version, build time. A restart writes
nothing; a rollback writes a line, which is the point.

The second is `bb catchup`, which reads both of those plus git and the
notebook's own logs and prints one screen: the image this box is running and
how far behind `origin/main` it is, recent commits **with the first line of
each body** (the line that says *why*, which `--oneline` throws away) what
moved in the roadmap and the tracker, and the image builds CI archived
([building.md](building.md#reading-ci-from-inside-the-container)).
