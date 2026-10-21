# A project's page

Every project has a page of its own, opened from its card on the Projects
page or at `#/projects/NAME`, and the page is the project's **notebook**: the
one surface here that both you and a session write. This doc covers the
page's header and its views, grouped on the view strip as **Overview**
(Overview, Settings), **Plan** (Roadmap, Bugs), **Code** (Git, Tests,
Analysis), **Ship** (Artifacts, Docker) and **Docs** (Wiki, Design), and what
each one keeps.

## The page and its views

**The page's header** wears the project's color and carries its name, the
branch and the node, the session's state as a dot and a word, and its
actions: **Start Claude** (**Open Claude**, in green, while your session
runs) with the chooser under it, **Shell**, and the rest behind one menu,
the same menu its card has ([projects.md](projects.md#a-projects-card-and-its-menu)).

**The view strip** under it is two rows: the five groups, and the views of
the group picked, each group coming back to the view last picked in it.
The address names the view (`#/projects/web/bugs`), so a link to a project's
bug list lands on it.

| Group | Views | What they keep |
|---|---|---|
| Overview | Overview, Settings | The code base, the brief, the rules, what Claude remembers and what a session is sent; the project's settings |
| Plan | Roadmap, Bugs | The shared list of work and the bug tracker |
| Code | Git, Tests, Analysis | The repository, the test registry, the scanner's findings |
| Ship | Artifacts, Docker | What the project built, and its containers |
| Docs | Wiki, Design | The project's wiki, and what it looks like |

## Overview: what Claude remembers here

**Overview** is the page's first view: the code base, the brief the project
started from, the rules, what a session is sent (described in
[sessions.md](sessions.md#telling-a-projects-sessions-about-this-environment)),
and the **Memories**, what Claude remembers here.

Claude Code keeps memories in `~/.claude/projects/<slug>/memory/`:
one markdown file per fact, plus a `MEMORY.md` index that is loaded into
every session started there. Everything else a session is told is
reviewable (`CLAUDE.md` through a pull request, the transcript on screen),
but a memory writes itself and is never read back, so a wrong one steers
every later session invisibly. The fold opens them: each memory folded to
the summary line Claude wrote for itself (name, type, when), unfolding to
the whole file in an editor, with **Forget this** to delete one, which
takes its line out of the index too, since a pointer to a file that is gone
is worse than no pointer. The index is not shown as a document of its own:
it is one line per memory, so it is edited as **title** and **hook** fields
on the memory that line names, and written back whole when you save. That
is also the difference worth knowing: the index is the only part always in
context, and the files themselves are read only when recall reaches for
one. Drift between the index and the files is called
out in amber both ways: a line naming a file that is not there, and a file
no line names; saving clears the first and fills in the second.
**+ write a memory** puts one there by hand: title, file name (slugged
from the title until you type in it), kind, the one-line hook, and the
memory itself: written with the frontmatter Claude uses and given its
index line in the same act, never one without the other. Mostly Claude
writes these itself; this is for the standing instruction you would
otherwise repeat once a session and hope stuck.
It sits on the project's page rather than beside a Claude terminal on
purpose, since *why did it do that?* is usually asked after the session has
ended, and it is folded shut, because a handful of files nobody edits does
not earn the top of a page. Editing one arms the Memories section's own
**Save**.
**Edits land for the next session**: the index is read at startup, and a
running session is holding what it read then, which is what Save tells it,
in the one line it spends.

**Settings**, beside Overview in its group, is the project's settings,
described in [projects.md](projects.md#a-projects-settings).

## Working in the notebook

**Unsaved work does not cross those views.** Leaving a view asks, and answering
yes throws the change away rather than carrying it to the next view.

**A History, and the changelog, open over the page rather than in place of
it**: a large box on a desktop, the whole screen on a phone. They are things
you *read*, so the list you are reading them against stays behind them, and
**Close**, Escape or a click outside puts the log back where it came from.
What goes into the sheet is the real element,
moved, so the filter bar keeps every handler it had and there is no second
copy of it to drift.

**It opens on Overview** the first time, and after that on the view you were
on: the view is kept per project, so going off to another page and coming
back finds it, and each group comes back to the view last picked in it.

**Each section saves its own.** A notebook section that stages anything (the
roadmap's list, the Memories, Your rules, each Version, the Design's Themes
and Pages) carries its own Save and Revert at its foot, which write or throw
away that section's changes and nothing else's; there is no notebook-wide
Save, since one at the bottom was a long scroll on a phone from the change it
saved. A view opens on its first section; on a phone one is open at a
time, opening one closing the others, and on a desktop several may stand
open (the operator, 7 Oct).

**And the page keeps up by itself.** Every view re-reads when somebody else
writes: each carries a revision from the status poll, and a change to the
list, the memories or the tracker is picked up without anything being touched.
It is guarded rather than unconditional: the roadmap on screen may be carrying staged changes the
server has never seen, and the memory editor may be holding an hour of typing,
so a re-read waits until there is nothing to lose.

**A write that would go over somebody else's is refused, not applied.** Each
one says what it believes it is replacing: a roadmap field says the words it
read, a bug form the revision it opened over, a memory the digest of the bytes
it loaded, and if that is no longer what is stored, nothing is written. A
band says who moved it and when, shows what is stored beside what was typed,
and offers the two answers: **Keep theirs**, which drops the staged change, or
**Use mine**, which writes over what is there now. A memory has no "keep
theirs" (the version in the editor may be an hour of typing), so what is on
disk is shown to read and copy from, and the choice is to write over it or to
reload deliberately, with the loss said out loud.

The unit is different in each view because what a write *replaces* is
different: one field of one roadmap item, a whole bug form, a whole memory
file. A roadmap item's check is per field on purpose: a session attaching
details while you reword the same line is two people doing two things, and
reporting that as a conflict would offer a choice between two things that do
not disagree.

`bb` is held to the same rule from the other side: a session that has not
re-read the roadmap since it moved is refused when it tries to reword, drop
or tick off an item, and told to run `bb roadmap` first. There is no
`--force`: re-reading is one command, and a flag would make the dishonest
path the shorter one.

**And a line says who else is in here**, under the view strip, so that most
collisions are seen rather than resolved: *Also open: your other window
(Roadmap)*, or somebody's name when the account is not yours. Both windows of
one account are the same account, so the account cannot be the answer: the
line is keyed on the browser tab, which is what lets it say *your other
window*. It rides on the same fifteen-second poll the page already makes,
lives in the server's memory and nowhere else (a seat that survived a restart
would be a claim about somebody who is not there), and closing the notebook
says so rather than leaving the seat to time out.

Beside it, **when a session here last read the roadmap**, which is a
different claim from having been told. Being told rides in on the session's
next prompt; going to look is `bb roadmap`, and after changing something that
is the question worth answering.

**Every view keeps its history.** The roadmap, the bug tracker and the
memories each have a **History** button with the same bar: search, a time
window, a cap, and the same rows: what happened, to which line, by whom,
when. **By whom is the account, not just "you" or "claude"**: those two say a
person or a session, and with several people on a project that does not say
which of them dropped an item. A session carries its account's name too, because a session
has an author: the person it was minted for. The memory log records what the *notebook* changed
(wrote, edited, forgot): Claude's own memory writes are files, not events,
so they have no entry to make. For a session, `bb history --find X` is one
search across all three logs, merged by time and tagged by source; `bb roadmap
history` and `bb bug history` scope to one.

## The roadmap

**The roadmap** is `bb roadmap` in a terminal. Saving does not leave it; the
Save button simply goes dead until there is something to save again, and the
button beside it is **Revert**, which throws away what has not been saved
and is dead whenever there is nothing to throw. Leaving the view asks first
if anything is unsaved. It is the one surface here that
**both sides write**:
you add "make the picker wrap properly", a session adds "a project can be
created in one click and only deleted from a shell", and either of you can tick
something off.

**Every change to a list is kept.** Both sides write these, and the list
itself only ever shows the present tense, so *was that step always worded
like that?* and *who dropped the third one?* need a record.
**History**, at the top of the view where the other views keep theirs, is
the answer: one line per change, newest
first, each with its date and time and whether you or a session made it. A
reword shows both wordings, the old one struck through. `bb roadmap history`
prints the same log in a terminal.

That log is also what makes deleting safe, because the list holds nothing
but outstanding work. **A ticked-off item comes off it**: a list is read to
find out what is left, and a thing that is finished is not left. `bb roadmap
done N` moves it into the log under *done*, where `rm N` would have put it
under *dropped*; both leave, and the log says which happened. Only a session
ticks things off, because only the session that did the work knows.

**The strike icon is only ever an undo.** It appears on a line that *has* been
sent, to put it back so it can go again; there is no crossing one off by
hand, because "I crossed that off" is not the same claim as "that is done". A
line you handled yourself gets dropped, and its words stay in the log to be
retyped if you were wrong.

**Nothing the view does reaches the list until you press Save.** Type three
steps, reword one, drop another, shuffle the order; it is all held on the
page until then, so a plan can be looked at whole before it is committed to.
Leaving the view asks, names how many changes would go, and puts the list back exactly as
it was. The one exception is the send arrow: it types into a live session,
which no Save button can take back, so it flushes whatever is staged first and
then goes.

While a session has a batch open, **the roadmap's Save is held**, and only
that Save. You can still type, edit, drop and revert; what waits is writing
back, because what is on your screen was read before the session started and
saving over a list that has moved underneath is how two writers lose each
other's work. The block is one-way: nothing on the page ever makes a session
wait. When the batch commits the notebook says so and offers to reload, since
what it is holding is now out of date.

**That hold is the page's own, and it is not a lock.** Nothing here
serializes writers: `bb` and a second session write straight through an open
batch, and two browsers can have the same notebook open. What stops the loss
is per write, below.

**One batch covers the whole notebook**, not just the roadmap. Bugs filed,
noted or closed while one is open are staged the same way, and `bb bug begin`,
`commit` and `revert` are the same three commands reached from the other view's
name: `notebook.py` sequences the two halves so that half a batch is a state
the front door cannot reach. A plan usually moves *because* of what the tracker
now says, and committing one while reverting the other would leave a roadmap
describing work against a tracker that never recorded why, with nothing
afterwards able to notice. The memories are outside it: a session writes those
as files with its own tools, so there is no write to intercept and `revert`
will not put one back.

A session gets the same idea in a different shape: `bb roadmap begin`, then work,
then `bb roadmap commit`: the changes land on the list as they are made, because
that is how you can see what a session is doing, but the *record* is written
once at commit. Rewording the same step four times is one history entry rather
than four. `bb roadmap revert` puts the list back and writes nothing, and refuses
if you have touched the list yourself since the batch opened.

**Dropping something asks why.** The bin opens a box under the row with an
optional reason field, and the reason is kept with the entry and is
searchable, because nothing here can be undone, and that note is the only
thing between a dropped line and somebody adding it straight back. The log
can be narrowed rather than read whole: search the lines, their previous
wordings and the reasons things went, over a window of time, capped to a
count. `bb roadmap history --find picker --since 7d` does the same in a
terminal, which is how a session reads it without spending its context on
the whole thing.

**Shelving** is the state between *do this* and *we are not doing this*: the
tray icon parks an item, sinks it to the bottom, dims it and kills its
arrows, and a session is told it is parked rather than left to wonder. It is
the only control here that undoes itself (the same tap brings it back) and
it applies to an item, never to one step of a plan, because the thing you
have decided not to do now is the whole plan. Shelved items do not count
towards the number on the project's card. A session can shelve (something turns
out to be blocked, and saying so on the item beats saying it in a reply nobody
re-reads), and can ask for one back with `bb roadmap unshelve N WHY`: taking
one off reverses a decision it was not told the reason for, so the request
is held on the notebook with its reason, whatever the roadmap gate says, and
a user or administrator on the project approves or denies it there.
**Finished** at the top of the view shows the items ticked off, with the
plans they had, below the shelved ones; they are hidden until asked for,
because a list is read to find out what is left.

**A session can correct a plan, not just follow it**: `bb roadmap edit N`,
`bb roadmap step add|edit|rm|mv|done`, `bb roadmap mv N up|down`, which matters when the design moves under a plan
written a week ago. Every one of those lands in the history under `claude`,
so nothing gets quietly rewritten.

**The list reads top down, and the top is what matters most**: new items go
on the end, and the arrows in Reorder are how something gets promoted. Each
item wears its number: `R4` is the item's own name, not its position, so it is
what `bb roadmap done R4` takes, what a session means when it says "R4", and what
survives the list being rearranged. The R is the roadmap's letter and B is the
bug tracker's, so a number in a reply or a commit says which list it is from;
every verb takes the bare number too, and refuses the other list's letter. The
prompt a session starts with carries the same names. Steps inside a group
number themselves 1, 2, 3 within it.
A gap in the numbers means something was removed; one out of sequence means
it was moved.

**Every line can carry details**, the technical half: which files, which
functions, the approach. They live under a "▸ details" fold on the row (the
words are the decision; this is the workings), travel with a step when it is
sent, and ride in the block a session starts with, so the session that works
the step does not start from a cold grep. Claude writes them with
`bb roadmap info N [M] "..."`, usually when it writes the plan; the pencil edits
them alongside the words.

**An item can name the release it is meant for**, its target: the
project's own version, as `0.6.0`. It shows as a tag above the item's words
and among its facts, and a line of chips under the list's own narrows it to
one release, or to the items meant for none yet; the Finished section
narrows with it, so what went into a release can be read back. The Reword
box sets it, and a session sets it with `bb roadmap target N 0.6.0` (or
`--target` on `bb roadmap add`), and lists one release's with
`bb roadmap --target 0.6.0`. It is a plan, not a gate: nothing holds a
release for it, and what shipped an item is still read off the changelog.

**A group is one goal with an order to it.** Its title is that goal in plain
words ("make the picker usable on a phone") and the steps under it carry the
detail; the group folds like a bug's row, its title the heading and a tap on
it opening every step under it. Steps only exist because of one physical constraint: each is a message
*you* send by hand, one at a time, waiting on each. So a step is not a task,
it is a point at which the previous work has to have finished before the next
can start, and a session that splits work into more steps than that costs you
round trips for nothing. A step can be several lines, blank lines and all, so
the cheap unit is the line and the expensive one is the step. The briefing
every session gets says this in as many words.

**Items are handed to the session one at a time, by the arrow beside them.**
Sending types the line into the running Claude session and submits it, but
only if it can see that it arrived. There is no IPC into a session; the only
door is its terminal, and a session "waiting for input" is either at its prompt
or holding a permission dialog, which the title cannot tell apart. Answering a
permission dialog on your behalf, blind, is the worst thing anything here could
do, so instead of trying to recognize a dialog, it uses the one property every
text box has and no dialog does: **it echoes what you type**. Type the line,
look at the terminal, and press Enter only if there is now one more of it on screen
than there was. If it did not appear, the line is left in the input box unsent
and the dashboard says so. With no session running, every arrow is dead.

A sent step is **struck through in place**, not removed, not reordered. Sent
is not done: a step can be handed over and quietly not carried out, and the
struck line is how you notice. It stays sendable, so "that did not take, do it
again" is one tap on the same arrow.

**Done is the session's mark, and it is a different one.** A session that
finishes a step says so with `bb roadmap step done N M`: the step it was
sent, or one it was told to go ahead with in chat. The line is struck the same way but wears a tick instead of its
number, the frontier moves past it, and the log says a session finished it
and when. Only a session sets it. A whole item is ticked off by a session
with `bb roadmap done` or by a person with Done on its row (the operator,
16 Oct), and goes under Finished, where Reopen puts it back until a release
ships it. Sending a done
step again is the override: the mark comes off, and the log shows the send
after the finish.

**The order that is protected is the order things are sent in**, and nothing
else. Only the frontier step of a group arms, and the group's own arrow stands
for that same step, so a plan cannot be handed over backwards, which is the
mistake that actually costs something: step three landing on a tree step two
was supposed to have made.

Editing is not constrained the same way, deliberately. The pencil rewords any
row, and the **bin is on every row**: item or step, anywhere in a plan, so a
stale step three does not cost you steps one and two to reach. A deletion
cannot send anything out of order. It can only make a plan shorter,
and it says why it did, in a note kept with the entry in the history.
**The bin always asks; shelving never does**, because one is recoverable by
pressing the same button again and the other is not.

Which is why **sending a step folds the two together**. Tapping an arrow
**arms** it: the arrow lights up and a **send box opens under that row**,
carrying a note field, Cancel and Send; tapping the arrow again puts it
down. Send then does three things: the line goes, the step is crossed off,
and you land in that session's terminal. One tap for all three would be a mis-tap you could not
take back, and the highlight is the confirmation: a sentence restating the
line the arrow is sitting next to was not.

The box sits **under the line it would send**, not at the foot of the view,
where on a phone it would be a screen away from the line it is asking about.

**A note can ride with it.** The box carries a field for anything to send
alongside ("the select is the one on the left") and it goes on the *same*
line as the step rather than as a second message, for the reason two messages
never work here: the second lands glued to the first. It is cleared once the
step has gone: a note belongs to the one thing it was
written for, and finding it still sitting there on the next step is how it
gets sent twice.

**Model and effort** are not questions in that box and are not applied by it.
They are picked when the session starts
([sessions.md](sessions.md#starting-a-session)), and `bb-tty` passes them as
`--model` and `--effort`, so a session that is up is already on them and a
send is only ever the send.

A group's own arrow **stands for its next step**: picking either lights both,
because they are one choice. A crossed-off line cannot be sent at all; put it
back first, so that struck-through means one thing rather than two.

The "I also changed the list" note rides on the *same message* as the step
rather than chasing it: two lines into one input box is how the second ends up
glued to the first. It rides on every send rather than being offered as a
choice: a session about to act on a step is exactly who wants to know the plan
around it moved, and by the time anything can be sent there is nothing unsaved
left to keep quiet about, which is the next rule.

The view opens the way the others do: its one-line summary on the left
and **History** on the right, with the field, **Add** and **Reorder** together
on the row under it. Those three are the things that change the list; History
only reads it.

**Nothing can be sent while the view is holding unsaved work.** The arrows go
down, and the line above the list says which change is not on disk and that
Save or Revert will clear it. The reason is what a step *is*: a line typed into
a session, which then goes and reads the list for itself. Send a step off a
list that exists only in this browser and the two are describing different
plans: the session is working from the file, and the file has never heard of
it.

**An item can be an ordered group of steps.** From a terminal that is
`bb roadmap add "rework the picker" --step "widen the select" --step "then
re-measure it"`; on the view it is **+ step** under any item, which turns a
plain one into a plan, and the field stays open, so three steps is three lines
of typing rather than three dialogs. A step is **sent with the plan around
it**: "this is step 2 of 3 in a plan", the plan's own line, then the step,
because "then re-measure it" arriving on its own says nothing about what it is
for. Only the next unsent step can be sent; the one after it is dead until the
one before has gone, because three separate items can be handed over backwards
and the second then lands on a tree the first was supposed to have made.

**Reorder** is a mode rather than two more icons on every row: five controls
and a number do not fit a phone, and nobody rearranges a list at the same
moment they are sending from it. The toggle beside the hint swaps each row's
send/strike/bin for up and down: items move among items, steps move within
their group. A step that has gone is pinned and nothing moves above it, so the
crossed ones stay the block every other rule reads them as. The order on
screen is the order in the file; nothing is sorted on the way out, so a list
you arranged stays arranged and a ticked item fades where it is rather than
jumping to the bottom.

**Reordering is staged like every other edit**: the moves live in the page
until you save them, leaving the mode puts the order back, and leaving the
view on a half-done shuffle leaves the list alone. Both are asked about
first, since an arrangement is work.

## What a session may add

**How much of what a session adds lands on its own** is the *Claude may*
section of the project's settings: add to the roadmap, file bugs, add rules
and fill in build and test, each **auto**, **ask** or **deny**. Auto: an item, report or
rule a session adds lands at once, marked as its own. Ask holds it instead: the
session is told "held for approval as R12", the page shows a band above
its views with how many changes are waiting (and a count on each view), the bell
carries a row per project that takes you there, and **Review** opens the
list: every held change with a checkbox and its full text under a fold, a
select-all box, and Approve and Deny at the foot. Approve replays the ticked
changes in the order they were made; Deny drops them and anything that rode
behind them (details or a step added to a held item, a note on a held
report). Deny refuses the add outright, with a sentence the session can quote
so it says the thing in its reply instead. It covers creation only: what is
already on a list a session may still tick, note and reword under every
setting, and the session is told on its next turn what you decided. The
settled ones are in `bb history` under *waiting*.

## Bugs

**The bug tracker** is the Bugs view, under Plan, and `bb bug` in a terminal.
The roadmap is for things somebody decided to build; a bug is a different
record; it has a severity, a place it lives, a way to make it happen, and a
gap between expected and actual, which are exactly its fields, plus a notes
field the analysis accumulates in (`bb bug note N "..."` appends, dated,
rather than replacing: the last analysis is how the next one starts). Either
side writes it: you report from the view, a session files what it trips over
with `bb bug add "..." --sev high --area "..." --repro "..."`. It is
write-through, not staged: a report is a form submitted once. Each report
is stamped with the project's version as `bb version` prints it, on filing
(*in 0.4.0-dev.390+045bb5a* on the row) and again on closing (*closed in*),
plus the image the container was running when it was filed; a report that
predates the stamp stays blank rather than being backfilled with a guess.
A line of chips under the Open and Closed ones narrows the list by the
release a report was seen in (the X.Y.Z of its stamp), with Unknown for one
that has none.
Closing a bug that is already closed is refused: reopen it first, so the
log says the earlier answer was withdrawn. A bug **closes**
three ways, and the difference is what the next reader is told: **fixed**
(somebody fixed it), **won't fix** (a decision to leave it), and **not
applicable** (it was real and stopped applying, because the feature it was
about went away: neither of the other two is true of that). Each asks for
the note that is the point of closing, and `bb bug all` still lists it,
because a closed bug is the record that stops the same report being chased
twice.

**Delete** is separate and narrower: for a report that should never have
existed: mis-filed, duplicated, aimed at the wrong project. It takes the row
and leaves the reason in the log. The briefing tells sessions that this is
the only case for it; anything that was a real bug gets closed.

**Send to Claude** hands one bug to the session running there, from the same
box the roadmap opens under a step: the same note field for anything to send
with it, opened under the report instead. Nothing is switched on the way in:
the session is already running on the model and effort it was started with.

**A closed bug cannot be sent**: reopen it first. A closed bug is a record
rather than work, and the three closes exist to say which kind of dealt-with
it was; handing one over asks a session to deal with something somebody has
already decided is done. If a fix did not take, `reopen` is the honest way
back, and it leaves a line in the log where sending it again would leave
none. The button goes dead on the row and says so, and the server refuses it
independently: a rule only the page honors is a suggestion, and this one is
reachable over the API.

Sending is **written into the tracker's log** as `sent`, because "was this
ever handed to a session, and when?" is a tracker question. It is not a status
change: sent is not fixed, and the bug stays open until somebody closes it.

The list **sorts** by severity, newest, oldest, recently changed or title,
from the same bar shape the log's filters use. Open before closed is not one
of the choices (a tracker is read to find what is outstanding), so every
order works within that. Open bugs ride into every session's starting prompt by number,
severity and title, with the fields on disk behind `bb bug show N`.

## Git

The Git view, under Code, reads the repository out: what is
changed and not committed, each file a fold with its diff; the last hundred
commits across every branch as a graph, a node per commit and a curve to
each parent, with the branch and tag names on their rows; one commit's
message, author, files and diff when you pick it; and the branches, marked
with the one the tree is on and whose session's worktree sits on which
(`claude/<account>`), with how far each stands from `main` and from its
upstream, in plain words: "3 commits not yet in main", "same as main",
"in step with GitHub" (the host by its name, from the remote's address). The
branches are grouped by what there is to do with them: the one the tree is
on and `main` first, then work not yet in `main`, then branches already in
`main` with one **Delete** for all of them, then, folded, branches only the
remote has; a remote row that mirrors a local branch is not repeated. A
branch with work not yet in `main` opens to its commits and the diff `main`
would take, which is what a pull request page shows, so that page is not
needed to read work before accepting it. It
reads on open and again when the tree's history moves, never on the poll,
and every question is git plumbing on the controller against the project on
the share: a sha or a path from the address is checked against what the
repository itself reports before it reaches a command.

The view acts too, each button one fixed git command with checked arguments,
run under your author and the project's own credentials: **Fetch**, **Pull**
(fast-forward only, refused with uncommitted changes) and **Push** (through
the same path `bb git push` takes, offered only to a project with push
rights) on the bar under the head row; **Commit all** with a message at the
top of Changes and **Discard** on each file; **New branch** at the top of
Branches, **Merge into main** on a branch (from any branch, the way a pull
request's button merges: it lands in a temporary worktree on `main`, so the
tree does not move and the owner's session need not end; a clash is
abandoned whole and Send to Claude is what finishes it; nothing touches the
remote), **Merge main into here** on the `main` row when the tree is
elsewhere (in place, so refused while the owner's Claude session stands in
the directory, and a conflict is left standing for the Changes section to
hand to Claude), **Switch** (refused under a session likewise, or with
uncommitted changes) and **Delete**, which refuses a branch holding commits
no other branch has until you say so twice, and says which of the two kinds
it is: a branch whose commits change nothing `main` lacks is history going,
not work. Merge into main waits while the copy of `main` here is behind the
host, and names the pull, because merging into it is how that copy ends up
both ahead and behind. **A push is read before it goes** (`pushscan.py`,
R219): the added lines of what it would send are looked at for a token, a
key, a password, a private key block, an address with a password in it, an
email address or an IP address, in the relay's own repository and never in
the tree. A session's `bb git push` with such lines is held: the bell shows
them whole, each with its file and line, Approve pushes and Deny drops it,
and `bb git push` waits on the answer the way `bb root run` does. The Git
view's Push shows the same lines in a confirm. An approved line in a file
is okayed for that project (`/config/pushok.json`) and passes from then on;
a line that changes is asked about again. The hold is the third answer of
the project's git policy, **Hold a push that looks sensitive**: off, a
session's push goes without being read, and the Git view's confirm still
shows what it saw. The **only on `<host>`** fold says of each branch
whether `main` already has every commit on it, and offers **Delete on
`<host>`** for the ones where it does, which is the only case where removing
a branch there can lose nothing. **Revert** and **Branch here**
on a picked commit. A session's token
has none of these (it has `bb git`) and an archived project takes no action.

## Tests

The Tests view is the project's test registry, described in [building.md](building.md#the-test-registry).

## Analysis

**Analysis**, under Code, is the scanner's findings for that
project alone, worst level first, read-only: the scan runs on the host, and
`bb findings` reads the same digest in a terminal, and **Analysis** under
Projects on the rail opens the whole report as a page, with a project
selector and the same filter bar. Findings whose paths
resolve into anything other than a **valid** project: one that is listed and
free of error-level issues; an archived one still counts: are set aside rather
than shown as "unattributed". The label is reserved for paths that genuinely
place nowhere, which is the case worth a look.

That rule is a subtraction, and deliberately so: rather than recognizing each
kind of thing that is not a project, findings attribute only to the projects
worth reading them for, and everything else in the share falls out together.
It matters because of how the toolchain store is mapped here, beside the projects
folder in the same development share, so the host's scanner walks it like
anything else and one report grew nine thousand findings for a pile of
downloaded toolchains.

**The row names what it could not place**, commonest first: `file:/src × 9`,
which is mobsfscan reporting its own container path. A bare count said
something was wrong and nothing about what, which is how it sat in the
hundreds through several passes when 267 of them were one share and 9 were a
scanner's configuration. A
marker file (`.bbignore`) handles the case where the container knows about the
directory, but a share mapped in with nothing to mark it is still listed as a
project (one with an error, because it is not a repository), so subtracting
only the *listed* names would have left it in play. Subtracting the valid ones
catches both, and needs no excludes configured on the scanner.

**Analysis** keeps a log too, and it is the odd one among the logs: nothing here
writes a finding. The scan runs on the host, the container reads a report, and
between two runs a finding can simply stop being in it: fixed, or the file
went, or a rule changed upstream. The report cannot tell those apart and
neither does the log; what it says is *it was here on the 3rd and it is not
here now*. So the entries are **derived**:
each read of the report is compared against the last, and the difference is
the entry: `found`, `gone`, or `changed` when the count or level moved.

Two things keep it honest. A finding is identified by **rule and path, not
line**, because line numbers move whenever anything is inserted above them and
a key including the line turns one edit into a gone-and-found pair for
everything below it. And **the first scan of a project seeds silently**: the
starting point rather than an entry, because stamping a discovery date on
findings older than the feature would be confidently wrong. A report that
fails to parse, or a reports directory that is not there this minute, is
skipped rather than read as "everything was fixed": that is the SARIF trap the
rest of this is careful about.

## Artifacts

**Artifacts**, under Ship, is what the project has built, listed from its
`dist/` directory, and the convention is the feature. Build systems scatter
their outputs (gradle five directories deep, cargo into `target/`), and a view
that went looking for all of those would be a catalog of build systems that
is wrong the week a new one arrives. So the deal is one word long: **what
ships goes in `dist/`**, a session that builds something copies it there, and
the view lists `dist/` and nothing else. An empty view on a project that builds
things means the copy step is missing, and it says so.

Each row is labeled by kind (apk, xpi, whatever the extension says) with
its size and age, newest first. Everything can be **downloaded**.

What a session looked with lands in `dist/` too: a reel's sheet under
`dist/reel/NAME`, a page's shot under `dist/shot` and an emulator's under
`dist/emu`, each with a record
of who asked and when (`bb capture`, R96). Those are not what ships, so the
list leaves them out and the view draws them as one **Captures** fold, shut,
saying how many and how long they are kept; open, each row says whose it is
and offers Download and Remove. The recording and the full-size frames never
reach the share at all: they are working files on the node's own disk, at
the paths the reel's `frames.json` names.

They go by age and never by need. Nothing can tell whether a capture is done
with: two sessions on one project may each be reading a reel the other made,
and a session ending is not evidence that its reel is. So the project's
settings carry **Captures kept for N days** (7; 0 keeps them), the server
sweeps what is older on the read that draws the view, a person removes one
from the fold, and a session lets one of its own go with `bb capture prune
NAME`, the same rule applied from the node.

A **script** is the one kind the extension cannot settle on its own: a shipped
shell installer is as often `dist/install` as `dist/install.sh`, so a file
whose extension the list does not know is asked for its first two bytes and a
shebang makes it a script. Those rows also offer **View**, which reads the
file over the page the way a History opens, because a script is a thing
people read before they run it and a download is the end of that on a phone.
Nothing runs from the view, and there is no control that would.

An `.apk` can be **installed** on the paired phone. `adb install -r` replaces
an existing copy in place and keeps its data, so install and update are one
verb and there is no second button. Two failures are common enough to be
turned into sentences rather than passed through: a **signature clash** (the
copy on the phone was signed with a different key: a release build, or one
from the Play Store, against a debug build from here) says to uninstall it on
the phone first, and notes that this takes the app's data with it, because
that is the operator's call to make on the handset rather than something to do
on their behalf. A **version downgrade** says so plainly; `-d` would allow it
but only for debuggable packages, and passing it always would quietly turn a
mistaken downgrade into a successful one. Neither `-g` nor `-t` is passed
either: granting every runtime permission, or allowing test-only packages,
makes the install behave unlike the one a real user would get, which is the
opposite of what testing on a real handset is for.

An `.xpi`
can instead be **pushed** to the paired phone, which unpacks it and hands the
directory to `web-ext` for a **temporary** install (gone when Firefox
restarts). Two rules keep the push honest. **Nothing auto-pushes**: web-ext's
file-watcher is disabled and what is pushed is a snapshot, so a push is a
decision made each time, and pushing the **identical build** into a live
session is said rather than done, since it would install nothing. Stop the
session and the same file becomes pushable again, because after a stop (or a
Firefox restart) that is a legitimate thing to want. No History button,
deliberately: the files' own timestamps are the history, and a log of "the
file changed" would restate the mtime column.

## Docker

The Docker view is every container that belongs to this project, with the
Containers page's rows and controls, so a dev radarr for a media project is
found beside that project rather than among every project's on the
Containers page. How those containers are built and run is
[containers.md](containers.md).

## Wiki

The **Wiki** is the project's wiki, for whoever uses or works on it: pages
of Markdown that a person writes on the view or a session writes with
`bb wiki save`, under the project's dial Claude may: Write the wiki (auto
lands a page, ask holds it on the notebook for approval with its text, deny
refuses it, and hidden keeps the wiki from sessions altogether, reading
included, for notes that are the people's alone). It reads like an encyclopedia: one article at a time, its title over a
rule, a Contents box for a page with three or more sections, the prose in a
serif at a reading width, and the pages listed beside it (the wiki's own
`_Sidebar` when it has one, a picker above the article on a phone), with
`[[Another page]]` opening that page in place. Read and Edit are tabs over
the article, Save writes it through, and a page somebody changed since it
was opened is refused rather than overwritten. The controller keeps it as a git
repository of its own (`/config/wiki/PROJECT`) in the shape a forge's wiki
has, one `Page-Name.md` per page with `Home`, `_Sidebar` and `_Footer` as
GitHub reads them, so every change has a history and the wiki is never in
the project's tree, where a session could rewrite what the controller then
pushes. **Export** is a zip of the pages, which works for any project, with
a remote or without. A project with push rights on GitHub, Gitea or GitLab
gets **Push**, which sends the wiki to the repository's own `.wiki.git`
with the project's credentials, and **Pull**, which takes in what was
changed there (a page changed on both sides is named and nothing is taken
until one side matches). A forge makes a wiki's repository only when its
first page is saved on the web, so a first push to a repository with no
wiki says to make one page there; that page (GitHub calls it Home) is then
the forge's own, and Push offers to replace the forge's wiki with this one,
which is what a first push wants, or Pull to merge the two. GitHub's fine-grained tokens cannot write
a wiki; a classic token with the repo scope can. Pushing and pulling are a
person's: they reach outside BuilderBot.

## Design

**Design**, under Docs, is what the project looks like, in two folds. The
pages are laid out as labeled blocks on a phone or desktop frame, each named
for what it is for and the platform it is built for, a web app or an Android,
iOS, Linux, macOS or Windows app, since one project can be several. The
themes are each a named set of colors, dark or light, that a preset fills and
you add to or cut, the app starting on the first, and each carrying the
design language of its own: type and the exact families, shape, space,
motion, and its rules.

The first theme is the default, and its choices and rules are the design's:
said bare, as the design's own, in the briefing and the file; another
theme's are said under it where they differ, and its rules reach a session
named under the theme, `nostromo/hull`. What the language governs sits at the
top of the themes. A page carries rules of its own as well, for what holds
for that page alone, named under the page. Every rules list reads as the
Overview's does, a folded row a rule, inside the entry it holds for: a
theme's under its choices, a page's under its board. A new theme starts
blank, from a preset or as a copy of a theme here, choices and rules
included, and a new page from a template or as a copy of a page here.

The pages and the themes show one at a time, chosen on a pulldown. A frame
is one screen and a page may be longer than one, up to 240 rows, which
scrolls, and a page keeps where its blocks sit on each frame it has been
laid out for, which `bb design show` and the file say after the frame it is
on. Blocks may overlap, and the blocks' order is the drawing order, a later
one over an earlier one, which a layers list beside the board shows top
first, a row selecting a block another covers and its arrows moving it up
or down the stack. A block may be set inside another (a card in a list, a
form in a card), which it then stays within as either is moved or sized, on
every frame. The board takes the width the page gives it, with Pages, Design
language and Themes folded the first time the view opens and Add page inside
Pages. A page may have a short key of its own, which its rules are addressed
under (`now/live`) in place of its whole name. Each of the language's four
choices may be left not chosen, or be custom, which hands it to the design's
rules and can name the one that says it, whose text a session then reads in
the choice's place; the words a session reads are the record's own and
nothing is added to them.

A new project's design is empty, no theme and no page, and a project built
that way is built as a session sees fit, the session then putting the look it
arrived at into the design so the next one finds it. A project designed
before it is built is built to the design: its briefing says the notebook
holds one, what is in it, that on a tree with no code yet the design, the
rules and the roadmap are the specification, and that what the design leaves
open goes back into it, under the project's dial. Every edit is staged behind
Save; nothing on the view is a prompt and nothing on it reaches into a
session. A session meets the design by itself and piece by piece, through
the rules its briefing names and `bb design show`, which prints the
language, one page, one theme or one rule. A session asked to put a design
into the notebook writes the same record with `bb design save`, which keeps a
record as it was sent or refuses it whole with everything wrong with it
listed, never moving a block to fit or dropping a layout. **Write the file**
puts `docs/design-language.md` into the tree for every session to read.
