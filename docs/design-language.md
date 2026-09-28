# The dashboard's design language

The page's visual rules, in one place. Read this before adding or restyling
any surface, and extend the group selectors named here rather than restyling
locally. `test/uniform.mjs` measures most of what follows on every tab and
fails by name; the house rule `design` points here and runs it.

## Colour

Colour comes only from the tokens in `:root`: surfaces `--bg` / `--panel` /
`--sunk` / `--flyout` (page, raised box, set-into-the-panel, and what the
terminal's bottom bar opens: tinted towards the accent, with an accent edge
and a shadow, so it never reads as part of the bar or the page), edge `--line`, text `--ink`
and `--dim`, status `--accent` / `--warn` / `--bad` / `--note`, buttons
`--btn` / `--btn-hi`. Twelve schemes repaint the page by swapping nine of
them, so a hardcoded hex is a spot the schemes cannot reach.

**A filled accent surface is `--accent-deep`, and what sits on it is `--ink`,
never `--dim`.** The active tab, a primary button, a button that is on, a
view bar's current tab, an open select's chosen row, the text selection: all
one token, so all one answer. `--accent-deep` carries a lightness cap for
exactly this reason: the accents range from `#2fb8c6` to `#ffb000`, and
forty percent of black is not enough darkening under the bright ones. Five
schemes had text on that fill under AA before the cap, nostromo worst at
3.56:1. `test/uniform.mjs` measures the rendered pixels on every scheme.
Nostromo alone carries drawn textures (`static/nostromo/*.svg`, hand-written,
served by the page's allow-list): hull plating behind the page, ribbing in
the left gutter, a plate mark in a card's corner and a glyph strip in the
header. Each bakes its own opacity, none sits under text above a third, and
none moves the layout: a texture lives in space the page already leaves
empty. The same suite measures the contrast with them in place.

Watch the class the words wear. A tab's name is a `.lbl`, which is also the
field-label helper, so it arrived wearing the quiet colour meant for "Your
email" above a text box, on an accent fill, at 2.51:1.

## Shape

Three corners, as tokens: `--r-surface` (8px) for boxes (cards, panes,
modals), `--r-control` (6px) for controls (buttons, fields, tabs), `--r-small`
(4px) for tags. Never the number: a scheme may square all three, and nostromo
does. 99px for pills and 50% for dots are not corners and stay round
everywhere. Hairlines are `1px solid var(--line)`.

A colour is a token too, including the ones that look like a one-off: a
danger edge is `--red2-edge`, a warn edge `--gold-edge`, text on a filled
accent is `--bg`, and a hover shade is `color-mix()` of the scheme's own.
A hex outside the scheme blocks is the default scheme leaking into the
other eleven, and the check counts them.

## Type

`--mono` for data: names, paths, versions, anything a terminal could print.
Three secondary voices: `--f-note` (a quiet explainer, in `var(--dim)`),
`--f-ui` (secondary UI), `--f-tag` (pills and badges). Severity and level
colours agree everywhere: error and high are red, warning and medium yellow,
note and low blue.

## Space

A band of a document surface is inset `var(--row-y) var(--row-x)`, 11px 14px,
and `.field` applies it, so a band is a `.field` rather than a local padding.
A field inside a field does not inset again. The sidebar is denser on
purpose (rows 7px 10px, quiet states 9px 11px); nothing else is. Four
different left edges in one tab is what retyped padding produces.

**Down a dialog there are two gaps and no others**: `var(--field-gap)` (10px)
between the things in a band, and `var(--label-gap)` (5px) between a label
and the control it heads, because those two are one thing. The band owns
both: it is a flex column, and its children carry no margins of their own.
This is not a style preference. It was margin arithmetic between bare
siblings, which collapses between two blocks and adds around an input, so one
form measured 0, 10, 15, 16 and 22 down its length and read as several forms
stacked together. `uniform.mjs` measures every gap in every dialog against
the two tokens, so a dialog that invents a third fails rather than shipping.

## Controls

The field skin (ground, edge, radius) is applied to the elements globally,
so a new surface's controls match by existing. What a surface adds is
sizing: full-width mono controls at `--f-field` (11px, a step below the
text beside them, because mono at the same size reads larger) mean joining
the `.modal input, …` sizing group, its iOS rule and its `:focus` group. **The 16px is iOS's
alone**: Safari there zooms the page into a typed field smaller than that
and this layout cannot zoom back, so fields you type into are 16px under
`@supports (-webkit-touch-callout: none)`, a property only iOS has, and the
field size everywhere else. A `<select>` never zooms, so it keeps the field
size at every width: a 16px mono picker beside an 11px label is the loudest
thing on the tab, and it was on every tab. Tap targets are `min-height: var(--tap)`. A row of filters
is `<div class="field histbar">`.

**A field's label sits above it**, as `.lbl` (`lbl(id, text, help)`), two
or three words and no more: a field that is filled in still says what it
is, which a placeholder cannot. Where there is something the label cannot
say (a password's rules, what blank means, what a rename costs) it rides
the `?` beside it: `helpIcon(text)`, a circle with a tooltip that opens on
hover and on a tap, so a phone reads it too. Most fields need none: "Your
email" explains itself, and a `?` saying so is noise. Never a dash and a
clause on the label, never a line of small print under the field. A
checkbox keeps its sentence beside it. A placeholder, where there is one,
is an example, not a name. The two exceptions are a search box in a bar and
a one-line add box that is empty until it is sent: those carry their prompt
inside, because there is nothing to mistake them for once typed in. A text
field is wide enough for what goes in it: a name, an email, a password take
the row up to the cap, and only a number field is a few characters wide.

**Controls on a row line up at their bottom edge.** A row mixes fields that
carry a label above them with bare controls (a select, a button, a remove)
and a centred line floats the bare one between its neighbour's label and its
field. The bottom is the line the eye reads, whatever is stacked above it and
whatever each control's own height is, so a row of controls sets
`align-items: flex-end` and a row whose text column holds a field does the
same with its action cluster. `test/uniform.mjs` groups every visible control
into lines by vertical overlap and fails when one on a line ends at a
different height.

**A file field is a button of ours and the name of what was picked.** The
browser's own chooser stays hidden: its button wears the browser's skin,
not the page's, and there is no styling it. A `.filepick`: a button that
opens the chooser, and the picked name beside it: is the shape.

**An open `<select>` is the page's own menu, not the platform's.** The list
a select opens is drawn by the browser, so page CSS cannot reach it: on
Android it comes back as a system dialog with the OS accent on its radio
buttons, on iOS as a wheel, on each desktop as that platform's menu. Twelve
schemes and none of them apply. `appearance: base-select` moves the list into
the page, where the tokens do: the picker is `.pinmenu`'s box and `menuIn`,
its rows are `--tap` high and take `--accent-deep` when chosen, and the
element stays a `<select>` so its keyboard handling, its typeahead and its
screen-reader semantics are still the browser's. It is all inside `@supports`,
so a browser without it renders the native picker rather than nothing. The one
thing to know when placing one: a base select wraps a label that will not fit
where a native select truncated it, and `test/uniform.mjs` measures every
select as one line high at phone width. The arrow owns the end padding of
every base select (`padding-inline-end: 0` on the select, the padding on
`::picker-icon`), or a long choice slides under the arrow and shows again in
the strip beyond it.

**A button says what it does and stops.** No ellipsis on a label: "Enroll
node", not "Enroll node…": whether a dialog follows is not the reader's
problem, and the dots are not a word.

**A list of choices is in ALPHABETICAL order unless something says
otherwise, and what says otherwise says why in place.** The colour schemes,
the git hosts, the hypervisors and the toolchain catalog were each in the order
somebody happened to write them in; this box's own hypervisor first, then
whatever was added next, which is an order only that person can predict, and
a reader ends up scanning the whole list twice. Alphabetical is the default
because it needs no explanation and a new entry has one place to go. Three
exceptions exist and each is a sentence in the code: `Default` leads the
schemes because it is what you get having made no choice, *Another git host*
trails the hosts because it is not a host, and the toolchain list puts what is
installed first because that is the half you came to act on.

**A value that is one line of PROSE is a `textarea.proseline`, never an
`<input>`.** An input shows about thirty characters at phone width, and a
roadmap item, a bug's title, a changelog entry or the reason something was
dropped runs to three hundred: on a phone every one of those was a field you
could not read what you were editing in. A proseline wraps, grows to its
content and never scrolls inside itself. It is still one line: Enter does
not make a newline in one, and the surface's own Enter handler still runs.
`proseline()` does the growing and a MutationObserver wires every one that
appears, so there is nothing for a new surface to remember; `arriveBox` is
the one caller that asks by hand, because it measures a box's height in the
same tick. The rule the suite enforces: no `<input>` on a document tab
carries a `maxlength` over 120, because that is a sentence and a sentence is
a proseline.

**What the width test measures:** on every document tab, at desktop and at
phone width, the union of each control row's controls and each lone control
against the smaller of `--ctl-w` and nine tenths of the tab's box. A prose
editor in the notebook (a memory's body, a rule, a bug's repro) is a page
rather than a control and keeps the reading width.

**Every group of settings ends with one action bar**: the state line and
its Apply or Save at the right, and nothing else in the group carries a
button. One place to look for the press, on every section of every tab.

**A control never spans its container.** A button, a select, a text field,
or a row of them side by side, is at most `var(--ctl-w)` wide and never the
full width of the tab, card or band it sits in: it stops short, with the
band's own inset and room beside it, at every width. Full-width controls
read as a form pretending to be a page. The one exception is a control
whose whole point is the width: a terminal, a log. `test/uniform.mjs`
measures every control and control row on every tab against the surface
holding it.

**A dead control says why on its row, not only in its tooltip.** A ghosted
button carries the whole reason with the fix as its tip, which is a tap on
a phone as well as a hover; the first clause of that reason is also
written in red under the row, where the row's other facts sit (who has a
session here), because a phone shows nothing until it is tapped and a
dead button with no visible reason is what somebody stares at. Three
projects with no node read as broken after an update (23 Sep) with the
reason sitting in a tooltip the whole time. `shortWhy()` cuts the clause;
`cards.mjs` holds the no-node and out-of-window rows to it.

## Settings

Nothing on a tab takes effect until Save or Apply is pressed. A select that
saves the moment it is changed, a checkbox that writes on the click, is a
control that cannot be reconsidered, and the same section's Save then means
two different things. So every group of settings, on the Settings, Users,
Nodes and Artifacts tabs and in the project dialogs: has one Save or Apply
at its foot, and reads its fields when that is pressed. The one exception
is the colour scheme in the gear: a theme is looked at, not decided, and a
swatch that needed a second press to be seen would be answering a question
nobody asked. Buttons that *do* something (install, build, connect, end)
are actions, not settings, and act on the press.

## Files

The page is `index.html` (the markup, the stylesheet, and the wiring that
runs at load) and classic scripts beside it, loaded before its own
script: `tab-*.js` for a document tab, `nb-*.js` for a notebook view
(`nb-core.js` is the notebook itself, the frame the views draw into), and
`page-*.js` for a part of the page that is neither: the state and the
helpers everything reaches for, the tabs and their strip, the panes, the
sidebar, a project's settings, the polls, the bell, and so on.
Each is pure declarations and starts with `"use strict"`, as the page's
own script does, since it runs before the page and its helpers exist;
wiring that must run at load stays in `index.html` under the section's
`// ---- name ----` header, with a line saying which file holds its
declarations. A declaration whose initializer reads the page at load
(the favicon's element, a set kept in localStorage) stays there too. The
server serves a script only by name: the list is the page's own script
tags (`page_scripts` in `server.py`), so a new file is added once, as a
tag in `index.html`. `bb map sections FILE` reads a file by its
headers, with each section's outside callers, what runs at load and what
the suite covers.

## Document tabs

Reading surfaces, not terminals. A new kind does not write its own chrome: it
calls `docSurface(i, kind)`, which builds the standard skeleton (a
`.doctab.<kind>tab` box capped at `var(--doc-w)`: a filter/actions bar slot,
the band list, a quiet `.fnote` footer) and returns the slots to fill. States
are `.loading` / `.empty` / `.hint.bad` inside the list.

**The bar is a band, not a row of controls.** What the tab is about goes at
its left (a node picker, the filters, a one-line count) and the action on
it at the right, where a row's buttons and a section's status already sit, so
every tab's Refresh is in one place and lines up with the column of actions
under it. The band spans the tab; the controls in it are capped one by one
like any other. A tab that builds its own chrome instead misses all of this:
the Toolchains tab kept its picker in a band of its own and its Refresh landed
somewhere no other tab's does.

A new tab lands as: its own classic script file beside `index.html`, an entry
in `TABKINDS` there and `TAB_KINDS` in `server.py`, its top-level names in
`test/surface.mjs`, a driver in `test/uniform.mjs`, and a content test beside
its siblings. Renderers run inside `renderGuarded`, so a throwing renderer is
an error band in its own tab, never a dead dashboard.

## Sections and action bars

A long surface is sections: `docSection(kind, id, title, status, body)`, one
fold per concern with its status on the heading, open on a desktop and
closed on a phone. A status is a word or a number, never a sentence. A fold
keeps its state for the page's life and a reload starts it from the default:
the sidebar's cards are the one arrangement that is stored, at a desk in the
arrangement the server holds, and on a phone on the device itself, so a
card opened there stays open across a reload without reaching the desk.
Reset opens every card on both.

`hidden` means hidden. `[hidden]{display:none !important}` is global,
because any class that sets `display` otherwise beats the attribute: a fold
that never closed and a Select all with nothing to select were both that. To
show something, take the attribute off; never give a hidden thing a display.

Every set of two or more text buttons is an action bar (`.actbar`): the
status on its own `.state` line, the buttons after it at the right, their
own size at every width: a phone gives them the finger height, never the
row. The destructive verb wears `.danger` and comes last, so nothing safe
sits after something that cannot be undone. A button that started something
wears `busy(btn, verb)` until the repaint replaces it. Icon clusters with no
text are exempt.

## Dialogs

A dialog is `.modal > .box` (`.wide` for a list or an editor), titled by its
`h3`. Every line of its body is a `.field` band, which is where the inset
lives: a hint, a control, a list, never text at box level, which draws flush
against the edge. A group of fields inside it is headed by a `label`, the dim
small heading every dialog uses, never an `h4`; a dialog that is prose to
read rather than fields to fill (About) says so with `.box.prose` and may use
headings. The buttons are the `.foot`: a
`.state` first when there is one, then `.sp`, then the verbs, the primary
first and anything destructive last. A switch is a checkbox inside its label,
beside the thing it names, the way the Settings tab draws them
(`.logdays.setrow` holding a `label.ndcap`). What has nothing to act on is
hidden rather than disabled: a dialog with an empty list says so in one
sentence and offers Close.

## Rows you open

A row with detail behind it is a fold, the shape a bug report has: the name
on the line with its pills, the fields under labels when opened, its action
bar at the foot, and a line divider between rows rather than a box. Rules
and memories on the Briefing tab and the tests on the Tests tab are this
shape too.

A row opens to be read, never as a form. Edit on its action bar swaps the
fields in; Cancel (`.stop`) puts them away and drops what was typed, and
Save puts them away having written it. A row Add made has nothing to go
back to, so cancelling it removes it.

## Long lists

A list that can outgrow a screen shows a page at a time, through `paginate`
and nothing else: one helper applied to the DOM after a list draws, rather
than each renderer growing its own. It draws a `.pagemore` footer: which
rows are on screen of the total ("26 to 50 of 80 bugs"), then Previous and
Next, each only when there is a page for it to go to. It is a bar the
framework owns, so it is exempt from the action-bar rule and its shape is
the same on every list.

Pages, not a list that grows. The footer used to add a page below the last
one, and after two presses it was a screen away from the head: the same
number of rows is on screen whichever page is open, and turning a page
brings its top into view. The order still means something (bugs by
severity, the roadmap in the order the work has to happen in), so a page
is named by the rows it holds and never by a number.

Two judgements are yours. A list that only just crosses the line is left
whole, which `paginate` does for you. And a list somebody SCANS for a name
rather than reads in order (the toolchain catalog) is not paged at all,
because hiding half of it behind a control is worse than a long page.

The state is per list and per notebook. A notebook is a clone of one
template, so its ids belong to every open notebook at once; a key that
forgets which notebook it is in is one bucket shared by all of them, which
is how a page came to turn itself back.

## The notebook

Every view opens with the same head row: its one-line summary on the left
and its controls, History where it has one, on the right. That row is the
first band of the view and sits at one height on all seven views.

The view strip is one row on a desktop. On a phone it wraps into rows of
equal-width tabs rather than scrolling sideways: seven labels do not fit
393px, and a strip that hides its last two behind an edge is a strip whose
last two views nobody opens. Every tab stays visible at every width. The
view a notebook is on comes back with a reload, the way the tab strip and
the active pane do; closing the notebook's tab forgets it.

Adding goes at the top. The control that adds to a view is the first band
under its head row, above the list, one shape on every view (`.addbar`, a
button named for what it adds, `data-add`), and the form it opens unrolls
in that band's place. Never at the foot: a phone should not scroll past the
list to add to it.

Save and Revert at the notebook's foot show only on the views that stage
something behind them (Roadmap, Briefing, Design, the version on
Artifacts). A view that writes through or only reads (Bugs, Tests,
Analysis, Git) has no foot.

**The Design view's board is the one surface here whose colours are data.**
A page's blocks are painted in the project's own language (`nb-design.js`,
`blockStyle`), inline from the saved hex, because the board is a picture of
that project and not chrome of this page; everything around the board (the
frame's edge, the selection outline, the grip) is the page's tokens. Its
controls are the framework's: choices in labelled selects on a `.dsrow`
that lines up at the bottom, colours as a chip beside a seven-character
field, prose in a proseline, and the prompt in a read-only textarea, which
is a page of text and not a control.

## Both sizes

The phone and the desktop are both first-class. A surface is not done until
it has been looked at at both widths: sections open on a desktop and shut on
a phone, no control spans the screen at either, and a typed field is 16px
on iOS alone, so Safari does not zoom.

A finger is not a pointer. On a coarse pointer (`@media(pointer:coarse)`)
every button in a dialog and in the notebook is `--tap` high, and the small
controls a thumb meets (a tab's close and minimize, the new-tab button, the
colour swatches) are at least 30px; a desktop keeps its tighter strip. A bar
of buttons that spans a phone shares its width (`flex: 1 1 0; min-width: 0`)
rather than each taking its text's, so the last one is never cut off: at
344px, a folding phone's cover screen, four did not fit. "Both widths" means
a small phone (360 to 375), the fold cover (344), an unfolded fold (690 to
840, still the phone layout) and a desktop.

## Motion

Everything that appears, leaves, opens or changes state moves: a panel or
menu arrives (`menuIn`), a document brought to the front fades in over its
own ground (`docIn`, contentIn's frames under a name of its own, so a
document that already wears contentIn from its first paint still fades when
it comes forward), a section or card folds over its height
(`slideBody`, the section tween), a button or tab eases its colour, a
tooltip fades, a toast
slides, a modal leaves the way it arrived (caught off the `hidden` attribute
by one observer, so no close site has to remember), and a row folding its
controls out on a phone slides over the height that takes. A change that
snaps is a change the eye has to find. Every one of them is off under
`prefers-reduced-motion`. A scheme may ask for a different fold with
`--fold: fade` on the card (nostromo does: its plate mark is a decal, and a
decal sliding into the title bar reads as a bug): the body fades where it
stands, then the gap closes, and the cards below still ride the height.

**What fades is what is drawn, never the ground under it.** A document's
ground (the page colour, the panel colour, nostromo's glass and scanlines)
is painted by the pane's stack while that document is the one on show, and
the document box itself paints none, so the fade on it carries only its
content. When the box painted its own ground, the ground faded in with the
rest over the pane's black, and every switch to a notebook opened on a black
pane (27 Sep). `uniform.mjs` photographs the first frame of a switch, every
kind and every scheme, and holds it to the settled tab's own ground.

**The page waits on its own ground.** Nothing can be drawn in a pane until
the first snapshot lands, and an empty one used to be black and wearing the
active pane's outline: the loudest element on the page, showing nothing, for
as long as that took. Until then `body.booting` gives the pane the page's
ground and the same quiet `loading…` line every other surface waits with, and
the first draw that had state to draw takes the class off.

## Progress

Something that is running says so with a word and an animated ellipsis,
`busy(btn, verb)`, never a bar or a percentage: nothing here can honestly
measure how far along a build or a pull is, and a bar that guesses is a lie
with a scale on it.

## Meters

A bar that measures something real (a disk, memory, a load) is a meter:
a label, a track, a value. Meters come in stacks, and a stack is read as
one set of gauges, so every track in it is the same width and the values
sit in one right-aligned column. The value column has a fixed width sized
to the widest value the stack can show; it is never `auto`, because then
each row sizes its bar to whatever its own number leaves it, the long
values shorten their bars, and the stack reads as a ragged edge instead of
a comparison. `uniform.mjs` measures every stack on every tab for this.

## When a view re-reads

Three ways a view changes, and each has one answer.

**Something the person just pressed** is redrawn by the handler that sent it,
from the answer it got back. Nobody waits on a clock for a button they are
looking at.

**Something that arrived from elsewhere** is the revisions poll:
`/api/revs` every second and a half, which is stats and in-memory counters
and nothing that shells out. A view says what it depends on with
`onRev(key, fn)` and never decides when to re-read; the server publishes a
token for everything a view watches, and every token it publishes is
watched. `test/revs.mjs` holds those two sets equal, in both directions,
because the failure is silent: a page that waits is not wrong, only late,
so nothing else goes red. The keys a notebook watches are per project and
the page asks for its open ones by name, so a project nobody has open costs
nothing.

**A token is a counter where a panel can lose work, and an mtime otherwise.**
A panel that stages (the roadmap, the memory editor, a test's description)
holds the number it last read and compares, so it can tell somebody else's
write from the echo of its own; an mtime cannot make that distinction, and a
redraw a panel did not need detaches the send box or the half-typed row under
the finger that opened it. The same panel ignores the poll while a write of
its own is out, and asks again when it lands: the token moves when the server
takes the write and the panel's number moves when the answer gets back, so a
poll arriving in between would read the panel's own words as somebody
else's.

**Everything else is `/api/status`, every fifteen seconds**, and it carries
only what nothing cheaper can answer: the branch, the sessions, the image,
the doctor. A revision does not belong on it.

**A timer of a view's own is for watching something in flight, never for
noticing a change.** Noticing is the revisions poll's job, always. The
Toolchains and Emulator tabs are the ones that keep a timer, and only while a job is running:
an install of a small toolchain starts and finishes inside one revision poll,
so the tab would go from idle to done having never said "installing". It
stops when the job does. Anything else with a clock of its own is a tab that
notices things sooner than the tab beside it for no reason anybody chose,
which is what this whole section is against.

**A redraw nobody asked for never takes what a person has open.** Two things
on a surface are open rather than typed: a menu and a fold. Neither is a
tab's to look after, because a rule one tab keeps is a rule the next forgets.

A `<select>` whose list is showing holds the redraw. `menuHolds(root)` is
asked at the three places a redraw that did not come from a press starts: the
revisions poll, which is skipped whole so the news is still news on the next
tick; `renderDoc`, which draws every document tab; and `paint()`, which draws
every card. The draw that was skipped happens when the list shuts. A draw
that came from a press is not held, since the press is what shut the list.

A fold stays the way it was left. One with a `data-sect` key is recorded by
the page's one `toggle` listener, and only when somebody pressed it, so a
default never turns into a choice. `docSection` writes the key for a
section; `sectAttr(key, dflt)` writes it for a fold that is not one, such as
a row's Details or one file of a diff. A list row that carries its own
identity (a memory, a bug, a test, a rule) keeps its open set in its view
instead. `uniform.mjs` fails any `<details>` on any tab or notebook view that
has neither.

## Words on the screen

One sentence that tells the person what they need to know to act, in their
words: what the control does, and the one consequence they could not guess.
Not what they can intuit, not how it came to be, not the reasoning; a
paragraph on a control is one nobody reads, and a page of them turns the
reader off (the operator, 23 Sep, after R28 swept them). A hint, a state
line or an empty state is a line, about 25 words. The why goes in a code
comment, the README or Help, never inline. A stacked row
is `flex-wrap: nowrap`; a long token in it wraps or scrolls inside its own
box, and nothing scrolls the page or the pane sideways on a phone.
