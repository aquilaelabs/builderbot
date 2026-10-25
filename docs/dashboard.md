# The dashboard

The dashboard is the page the controller serves on port 7680: a rail of
pages down the left edge (a bar along the foot on a phone), a top bar, the
page on show, and the dock at the foot of every page, which holds the
terminals and the chat. This doc covers signing in, finding your way, what
the page tells you (toasts, the bell, notifications, the doctor), its color
schemes, the dock and its terminals, and the commands it types for you. Each
group on the rail has a doc of its own: [projects.md](projects.md) and
[notebook.md](notebook.md), [building.md](building.md) and
[toolchains.md](toolchains.md), [containers.md](containers.md),
[machines.md](machines.md), [sessions.md](sessions.md) and
[people.md](people.md).

## Signing in, on one port

It serves everything on `7680`: the page, the API, and the browser
terminals, which are websockets at `/termws` on the same port, so one
sign-in covers them all. Signing in is a login page that sets a 30-day
cookie (a real form, so password managers work) not the browser's own
credentials dialog, and there is no second prompt for the terminal port
because there is no second port. The sign-out button, last in the header, ends the session (`/logout` does the same).

Only the dashboard port is published. A terminal is xterm.js in the page on
a websocket at `/termws`: on the controller the dashboard runs bb-tty in a
pty of its own, and for a node it carries the socket, signed, to the node
agent's screen relay. So the browser asks for credentials once, the router
needs one port, and credentials are checked in one place: the cookie or basic
auth this server already verifies. curl and scripts can skip the
login page entirely: basic auth is honored preemptively on every request
(`curl -u user:pass ...`), there is just no `WWW-Authenticate` challenge, and
that header is exactly what made browsers pop their own dialog.

The dashboard's own API runs commands from a fixed list; it takes a macro name,
never a command string, and the list is `bb`'s own commands rather than anything
the page can compose. The one exception is a **custom command**: the operator's
own lines, stored by one authenticated request and typed by another into a tty
they are already sitting at with a full shell. Nothing runs in the dashboard's
process either way, and anything else belongs in the terminal, which is one port
away and honest about being a shell.

## The rail and the pages

**The page is a rail, a top bar, a page on show and the dock.** The rail
down the left edge is ten groups, each one press, in this order: **Home**;
**Projects** (Projects, Analysis); **Build** (Toolchains, Emulator, Phone, CI
runner, Apps); **Containers** (Containers, nginx); **Machines** (Controller
settings, Nodes, Storage); **Sessions**; **Jobs**; **People** (Users, Roles);
**Settings** (Profile); and **Help**. A group with several pages shows them
as a sub-nav at the top of its page. A page an account's grants forbid is not
drawn: People only for an account that may read accounts, Controller
settings only for one that may read the controller. Every page has an
address (`#/containers`, `#/machines/nodes`, `#/projects/NAME/roadmap`), so a
reload, a shared link and the back button land on it. Terminals and the chat
are the dock's, at the foot of every page. On a phone the rail is a bar of
five across the foot in the same order (Home, Projects, Build, Containers,
and More for the rest), and every page is the one page area above it, with
the dock at its foot. The search in the top bar jumps to a page, a project,
a container or a node as you type; it does not search inside notebooks.

**Help** is these docs, read in the wiki's reader: listed in the docs
folder's README groups beside the one open (a picker above it on a phone), a
long one opening on its contents, a link to another doc opening it in place
at its own address (`#/help/install`), and a search across all of them as it
is typed, each line found opening its doc at the section it is in.

## Home

**Home is the landing page**, and the one view that fits on
one screen. Across the top, six tiles count the whole install: the nodes
online of those enrolled, the containers running of all of them, the jobs
running (with how many failed today), the sessions open, the
updates due and the projects whose CI is red. Each is a link into the page
that holds the number. The machines and their containers are counted only
for an account that may read the Nodes page; a node that has not answered
within a few seconds counts as unknown and the tile says "as last seen".
Under the tiles, Attention is the bell's own rows (a node behind, a red CI
run, a file changed in two places), dismissed there as on the bell, and
Last jobs is the ten newest, each opening its row on the Jobs page with
the log open. Under those, the pinned projects at a glance, each with its
branch, its session state and the one notice it carries; Pin and Unpin
are in a project's menu on the Projects page. Home reads its numbers when
it opens, and the queue's again when a job moves; the containers are asked
only on opening, and nothing is read on a timer. A browser with nothing open lands on it.

## What the page says

**A toast** is one of a stack at the
bottom left of the page, beside the rail and above the dock's line (across
the screen on a phone), the corner that holds the fewest controls; while a dialog is
open it stands beside the dialog's box instead, or at the top of the
screen letting presses through where there is no room beside it. The
newest is at the foot and there are at most four, each with its kind's icon and its own ×. It goes after four seconds, seven for a warning or a failure, and stays
while the pointer is over the stack. A job started from the page (an agent
update, a toolchain install) gets a toast of its own that stays while the
job runs, says its state and its step as the queue reports them, and takes
the outcome's tone when it ends. Every toast is also kept for your account
on the server, newest first, the latest 300, so a failure you were not at
the screen for is still there to read.

**The bell** in the header is a short list: what waits on an answer, then
what needs attention, then the five latest of what was said, and See all.
It is bare rather than boxed because it is a state light first and a
control second: a red dot means something unread or something stopped, an
**amber** one means a session is blocked on an answer. That second case is
the reason it exists: a request to reach the phone, a container, a root
command or a release shows up there with **Approve** and **Deny** on it,
so answering does not depend on another page being open. Pinned in it, and
not Clear's to dismiss, is what is waiting on you or stopping work: a
notebook holding a session's changes, a node whose agent has an update, (in
red) a node from another compatibility window, a red CI run. Those come from
the state on every poll and leave the moment they stop being true.

**The Notifications page** (See all, at `#/notifications`) has the rest.
Waiting on you comes first, when anything is waiting: every ask, invitation and held change as a row
with its answer on the row, and the long part (a compose file, the lines a
push flagged, a release's notes) whole in a box that scrolls inside itself.
History follows: what the page has said to your account, each with its
kind, when, its own × and, for a job, a button to its row on the Jobs page;
chips narrow it to what was said, answers to asks, jobs or failures, and
Clear empties it or the chip in force, asked first. An answer to an ask is
kept there as an answer, from the bell or from the page.

**`bb doctor`'s verdict** is the dot right after the bell, green, amber or
red for the worst check. The server runs the checks in the background every
30 minutes. Pressing the dot opens a panel with the bell's manners (Escape
or a press elsewhere closes it): failures and warnings as full lines, each
with the fix hint from `bb doctor`'s own output beside it, passing checks as
green chips, when it last ran, and a ↻ that runs `bb doctor` now. A plain
user's panel carries only the lines that are theirs to act on (whether a
node can run their session); the runner tokens, ssh keys and the docker
daemon are an administrator's.

The **About** control beside it is the version, and where the header is too
narrow for a version string it becomes a **?** rather than a truncated number
that answers nothing: either way the popup behind it carries the whole stamp,
and behind one switch, a **getting-started guide** and BuilderBot's
**changelog**. The guide is [start-here.md](start-here.md) itself, read
through Help's docs, so the two never say different things; its last
section, for administrators, is left out for anybody else. The
panel opens itself twice in an account's life: on the guide the first time
the account signs in, and on the changelog once after every image update,
with a line under what is new since that account last looked. Closing it is
the acknowledgement.

The changelog there is **what is unreleased plus the current minor's own
releases**, each release under the categories it was filed into, and a line
saying how many earlier releases it is not showing. The question it answers is
"what changed in the build in front of me"; the file it reads keeps every
release forever and is where the rest of them are. Cutting a new minor takes
the previous one off that page in the same gesture, with nothing pruned.

## Color schemes

**Under the gear in the header, Dark, Light or System, and twelve color
schemes**, with Profile below them; each scheme has a dark half and a light
one. Nostromo is the ship in both: its dark half the metal hallways, cold
blue-black steel, deck grating, silver pipe under amber lamps, a bulkhead's
frame and square corners; its light half the white corridors, gray-white walls with large chamfered panels, an
octagon relief at the page's foot, the ceiling's vents and light panels
across the header and the hazard marking's red-orange, rounded like the
rest. Dark is the page read in a dim room beside a
terminal; Light is the same scheme with the page near white, the ink dark
and the accent pulled down to read on it; System follows the device as it
changes. The switch is applied on the press like a scheme, kept in the
browser so the first paint is right, and on the account so a browser that
has never seen it starts the same way. A scheme is nine custom properties:
every rule in the stylesheet draws from them, and the button and accent families are mixed
from the scheme's own panel and accent (`color-mix`, with flat fallbacks), so
a recolor reaches the sub-navs, the primaries and the active states rather than
stopping at the background. Each swatch is defined for `.sw[data-theme=…]` as
well as for the page, which means the preview *is* the palette rather than a
second copy of it that can drift.

**Nostromo** is the one that is more than a recolor: the ship's interiors,
the metal hallways in its dark half and the white corridors in its light
one, each with graphics of its own (the deck, the pipes and a bulkhead; the
wall panels, the vents and an octagon relief) drawn as hand-written SVG in
the tree under `static/nostromo`, served by the page's allow-list. No raster
image: that would be a binary in the repository, re-shipped in a weekly
rebuild, for something a few paths say.
Nothing in it moves the layout, so switching schemes never nudges the page.

The scheme is kept the same way: in the browser (`localStorage`, `bb.theme`,
with the account it was picked by) so the first paint is right, and on the
account so another browser starts with it. A browser whose stored choice was
another account's takes this account's own on the next poll. It is applied
from a block in `<head>`, before the first paint, which a value fetched from
the server could not be without a flash.

## Which build is serving it

The container's uptime **and which build of the image is serving it** are
both in the bar of the Controller settings page, and the build is again the
About control in the header, whose popup carries the whole commit and the time it was
built. The two are different questions: an Unraid container keeps running
whatever it last pulled, so "up two hours" says nothing about whether a fix
merged an hour ago is in there, and inferring one from the other is a good
way to spend an afternoon debugging a bug that was already fixed. `unstamped`
means the image was built outside CI. `bb status` prints the same line first,
and `bb drift` is the other half: what a checkout has changed that the
running container is not serving.

## The dock and its terminals

**The dock** is the foot of every page. Shut, it is one line: **Chat**
(with its unread count), then each open terminal as a tab (an agent's
session with its state dot, a project's in that project's color), then
**+** for a new shell and the chevron. A press on a terminal brings the dock
up with it, half the area to begin with, and dragging the line changes that
height, which this browser keeps. The chevron puts it down again and the
terminal keeps running behind its line. A tab held and dragged takes a new
place on the line, and **⧉** opens the terminal in front in its own window.
The page above stays whole: clicking into the terminal gives the dock the
keyboard, a press on the page gives it back.

**On a phone** the dock up is a sheet over the whole page, above the
bottom bar, and opening a page puts it down. Under the terminal sit
**Keys** and **Commands**. Keys is the
phone's alone: a desktop has a keyboard, so it carries no on-screen one at
all. One flyout at a time on a phone, because there is not the height for
two, and a flyout that has done its job gets out of the way: sending a
command closes it. The dock's line carries each session's dot, amber if it is waiting on you, blue while it works,
as each project's card does.

The dock starts with one terminal (**workspace**, a shell at `/workspace`),
and every shell or agent's session you open is another tab on its line.
Every one, the workspace one included, can be minimized; a dock with none
is its line alone, and **+** starts over. On a desktop the terminal in front
can also be popped out into its own window (the ⧉ on the dock's line): its
tab stays, its pane blank with **Reattach**, and closing the window brings
it back on its own. The window is the terminal on a page of its own
(`/terminal` on the dashboard's port), so closing the dashboard leaves it
working.

- **Start agent** on a project opens a chooser of the coding agents, one
  session of each per project. While yours runs the button reads **Manage
  agent**, in green, and the chooser offers **Open** (its tab), **Restart**
  and **End**. If none runs but the project has a previous conversation, you
  are offered to **resume** it or start a **new** one: the tmux session dies
  with a container restart, the transcript does not.
- **Shell** opens *another* terminal at the project path every time you
  press it, so you can have several side by side. **+** on the dock's line
  does the same for `/workspace`.
- **−** on a terminal's tab minimizes it, and asks nothing. The terminal
  keeps running and is listed on the Sessions page, where **Open** brings it
  back; an agent's session is the same, the conversation carries on without a
  tab. Nothing is lost, so nothing is asked.
- **×** on a terminal's tab is the stronger thing: it ends the session,
  after the same question the Sessions page's End asks, and closes the tab
  with it. **Middle-clicking** the tab does the same, the way it does in a
  browser.

**A terminal tab closes itself when its session ends.** `bb-tty` execs the
agent, so the terminal's process *is* the conversation. Exit it with Ctrl+C twice, `/exit`,
Ctrl+D, or a crash, and the tmux session goes with it, and the tab closes rather
than holding a dead terminal until somebody closes it. Shells too: one you
typed `exit` in is just as dead.

Nothing is lost by closing it. The transcript is on disk and the project's
Start agent offers to resume it, which is a better way back than a corpse in
a tab: the project knows the transcript id and the dead tab does not.

The rule is *seen alive, then gone*, and the transition is load-bearing: "has
no session" is also true of every tab restored from a saved layout before
anything has started, and of all of them for a moment if a poll ever comes back
empty. Reaping on absence would empty the dock at every boot.

**Switching between terminals is instant**, because the dock keeps the last
three of them loaded behind the one on screen. Rebuilding the terminal instead
would throw the frame away, and the terminal is 700KB of JavaScript that
then has to parse, open a websocket, attach to tmux and draw: a second and
a half of blank pane on a phone, every switch. The frames sit exactly on top
of one another at the same size, which is not just tidiness: a hidden frame
is still an attached tmux client, and tmux sizes a window to its smallest
one, so different geometry would mean the terminals fighting over the width.
The fourth reloads: the ceiling is there because each
one is a live xterm and its own socket, the same reasoning as the cap on
open terminals below. Killing a session also closes its tab, whichever tab
that is: a tab left pointing at a dead session would only offer to recreate
it.

**Tabs are named for where they are.** A terminal reads `sh: <directory>`,
following the shell as it `cd`s; hover for the full path. An agent's tab
reads `<agent>: <project>` (`Claude: alpha`, `ChatGPT: alpha`, `Copilot: alpha`). Two terminals in the same directory carry their number
so they stay distinguishable.

Every terminal runs inside **tmux**, so a dropped connection, a closed laptop
or a reloaded page detaches instead of killing the session. Coming back to a
backgrounded page reconnects **the terminal you are looking at**: the three
kept alive behind it reconnect when you switch to them, because reloading all
of them at once is several hundred kilobytes of terminal emulator apiece and a
phone spent its first seconds back doing exactly that. The **Sessions**
list (Sessions on the rail) is the full list: every terminal and every
agent's session, named the way the tabs are (`sh: <directory>`, `<agent>: <project>`), including the ones you
minimized; the tmux name and full path are on hover.

**Selecting in a shell copies it.** Release the mouse and the selection is on
your system clipboard. That is why tmux's mouse mode is off in shell sessions:
with it on, tmux takes the drag and the text only ever reaches a tmux paste
buffer. The trade is that the wheel no longer scrolls tmux's scrollback there;
at a prompt it walks shell history instead. **Agents' tabs keep mouse mode** and
so do not copy on select; its interface wants the mouse more than the
clipboard, and the wheel scrolls its output.

**Scrolling back is PgUp.** At a prompt, PgUp enters tmux copy mode a page up
and PgDn pages forward; copy mode ends by itself the moment you are back at
the bottom, so there is nothing to remember (`Ctrl-b [` still works, and `q`
still leaves). Inside a full-screen program the key is the program's. That is
also what the PgUp/PgDn keys in the ⌨ Keys row do on a **phone**, where a
finger dragged up or down scrolls the terminal too: back through a shell's
history by the line (copy mode, left by itself at the bottom), and as the
wheel would in an agent's tab. A press held on a word selects it, with a
grip at each end to widen it and **Copy** beside it; a tap still brings up
the keyboard.

The launcher sets this on the session as it starts one, not only in the config
file, because `~/.tmux.conf` lives on the persistent home and is yours.
Because the setting is applied per session, a `set -g mouse on` in your own
config does not override it: turn it back on where you want it with
`Ctrl-b : set mouse on`.

**Right-click gives you one menu, the browser's.** tmux draws its own context
menu inside the terminal, and the browser's lands on top of it: two menus for
one click, only one of them dismissable. The browser's is the one kept, so
tmux's is unbound. **Alt+right-click** still opens it if you want *Copy Line* and the
pane commands.

**Which terminals are open is your account's, not one browser's.** It lives
on the container, so opening the dashboard on a phone shows the terminals
the desktop has open, and a change on either reaches the other within a
poll. At most twelve terminals are open at once: each is a full terminal
emulator over its own websocket, so the limit is about browser
memory, not tidiness.

**Terminals survive a container restart, scrollback and all.** tmux dies with
the container, so on the way down the supervisor writes each terminal's
directory and the last 2000 lines of its screen to
`/config/sessions/`, and a startup hook recreates them there and prints that
scrollback back in before the shell starts. Minimized terminals come back the
same way, since they are sessions like any other.

What comes back is the terminal, not what was running in it. A build that was
halfway through went down with the container: restarting it here would be a
promise this cannot keep, and the shutdown kills whatever was running before it
takes the sessions' picture. Sessions are single-pane by construction; if you
split one inside tmux, only the active pane's contents are kept.

**Agents' sessions do not come back.** The conversation ended with the container,
and a session wearing its old name would be a new one pretending otherwise. Its
tab is dropped at boot too, and the project's **Start agent** offers to resume
the transcript, which is still on disk.

## Commands run in the terminal

They live under the terminal, at every width: **Commands** (and, on a
phone, **Keys**) in the bar under it, opening a flyout over the terminal they
act on. On a desktop it really is *over*: the flyout is
an overlay and the terminal keeps its height, because a resize costs a terminal
a refit and a reflow of everything on screen, which is a lot to charge for
looking at a list. A phone pushes the terminal up for it instead, there being
no screen to spare for covering one thing with another. Both slide. That is where they belong: a command list is
about the shell in front of you, not about the box, which is what the pages
are for. On
a wide screen the buttons sit at the bar's left edge and the flyout is capped
rather than stretched: a short list read across two thousand pixels is worse
than one read in a column.

Nothing about the graying-out below depends on where they live. It is computed
from the *terminal in front*, which is why one markup serves a phone and a
desktop alike.

A command's button clears whatever is half-typed at the prompt, types the
command into the terminal you are looking at and presses Enter, rather than
reporting into a box of its own. The output is then somewhere you can scroll
it, and one that follows behaves exactly as if you had typed it. A command
only ever goes to the tab you are looking at, and only if that is a plain
shell: with an agent's session in front (it would submit the command as a
prompt), or no terminal at all, every command button is grayed out and
its hover text says where to go: never quietly typed into some other terminal.

The line is cleared with end-of-line then kill-line, which is readline editing
rather than a signal: `Ctrl-C` would also interrupt whatever is running in that
terminal, which is not something a button should be able to do.

The flyout holds no `bb` commands: each has a page that does it better
(status on Home, the emulator on its page, the logs in Controller settings,
an agent's sign-in on its node's Agents page). The Tests view sends `bb tests log -f`
into the project's shell from its own button.

What is there, top to bottom: **pinned**, the commands whose **thumbtack**
is pressed, in their lists' order; **your commands** (below); **Linux**, the
general toolkit: `clear`, `cd ..`, `ls -lah`, disk usage here and per
directory, memory, the biggest processes, listening ports, live on any shell
tab; and **git**, its commands verbatim (`git status`, log, diff, branches,
stashes, fetch, pull), ghosting against the directory the active shell is
*in*: outside a git repository the whole list grays out, and the verdict
follows a `cd` on the next status poll. There is no `gh`: a node carries
none, and a push is `bb git push`'s, under the project's policy. Pins live in
`/config/pinned-commands.json`: one machine, one set, so a pin made at the
desk is there on the phone.

## Your own commands

**Your commands**, the second section of the same flyout, starts empty with a **+**. It takes a title and a
box of command lines, and the button it makes types those lines into the
terminal you are looking at, in order, exactly as if you had typed them: one
line or twenty. The pencil beside each one edits or deletes it.

Long titles are cut with an ellipsis so the list keeps its shape; hovering shows
the full title *and* the commands it will run, which is the thing you will want
six months later. They live in `/config/custom-commands.json`, so they survive
restarts and image updates and are the same on every device.

This is the one place the dashboard sends text you wrote rather than a name from
a fixed list, and it is still not a remote-execution API. The lines are stored
by one authenticated request and typed by another into a tty that the same
operator is already sitting at with a full shell. Nothing is executed in the
dashboard's own process.

## How a view knows to re-read

Every view shows facts it does not own. The roadmap's arrows depend on a
session existing; the Artifacts view's Install depends on a phone being
connected on a node; the Phone page's questions arrive from a terminal. A
view that made up its own rule for when to re-read would go stale, so none
does: `/api/revs` returns one token per thing that can change, a view
registers what it depends on, and it is told:

```js
onRev("phone.asks", () => phFetch());
onRev(() => `dist:${project}`, () => loadArtifacts());
```

**The notebook is on the same clock.** Its halves: the roadmap, the memories,
the rules, the approval queue, the test registry, and the controller's own
settings: each carry a revision here too, so a change made in another window
or by a session shows up on the page you are looking at within a second or two
rather than at the fifteen-second status poll. A view re-reads only when it is
not in the middle of something: a half with an unsaved edit, a staged change
or a write in flight is left alone until it settles, because a poll that
overwrites what somebody is typing is worse than a stale line.

The endpoint is **deliberately tiny**: file mtimes and in-memory counters, no
git, no tmux, no adb, which is what makes it affordable at a second and a
half, where `/api/status` runs git for every project and is affordable at
fifteen. The one thing that is not free, the set of attached devices, is
cached with a floor of a few seconds and refreshed at once when the dashboard
itself connects or disconnects, so pressing Connect is instant rather than up
to that floor late.

**A hidden tab slows down; it does not stop.** That distinction is the point:
a request lands while you are looking at something else, which is the ordinary
case rather than the exception. The poll drops to thirty seconds when the tab
is hidden (browsers throttle background timers hard anyway) and the tab
re-reads *immediately* on becoming visible, so coming back to it is never
looking at a stale page. A pending request also puts a count in the **tab
title** and a dot on the **favicon**, which is as far as a page can go without
asking for notification permission; that is a decision about your browser
rather than about the dashboard, so it is not taken on your behalf.

## Reporting a problem with BuilderBot

A problem with BuilderBot itself goes to the **diagnostics**, where whoever
looks after this BuilderBot reads it (`bb diag reports`). It is a log, not a
conversation: nothing goes back to whoever sent it, and **Clear reports**
empties it. A session sends one with `bb report "what happened"`, under the
project's **Agents may: Report BuilderBot bugs**. A person sends one from a
project's menu: **Report a BuilderBot bug** opens **Report a bug**, with a category to
pick, what happened and how to make it happen, and **Send** puts it in the
diagnostics under that project with its node and the build it was seen on,
marked as from the dashboard. A person's report is heard whatever that
project's Agents may dial says, from a project they are on: an administrator
shown every project but not on this one cannot start a session there, so
its menu has no such entry for them and the server refuses one. A
project's report can carry the reporter's latest conversation on it,
ticked in the dialog: its last 400 KB, redacted, kept as a file of its own
beside the report. The diagnostics name that file, the download beside the
logs is a zip of `diagnostics.json` with a `conversations/` folder holding
each one, and `bb report conversation N` prints it for a session. The bug in
the header is the same dialog about no project in particular, for anybody
signed in, and the diagnostics list it as general.
