# The dashboard's design language

The page's visual rules, in one place. Read this before adding or restyling
any surface, and extend the group selectors named here rather than restyling
locally. `test/uniform.mjs` measures most of what follows on every tab and
fails by name; the house rule `design` points here and runs it.

## Colour

Colour comes only from the tokens in `:root`: surfaces `--bg` / `--panel` /
`--sunk` (page, raised box, set-into-the-panel), edge `--line`, text `--ink`
and `--dim`, status `--accent` / `--warn` / `--bad` / `--note`, buttons
`--btn` / `--btn-hi`. Twelve schemes repaint the page by swapping nine of
them, so a hardcoded hex is a spot the schemes cannot reach.

**A filled accent surface is `--accent-deep`, and what sits on it is `--ink`
— never `--dim`.** The active tab, a primary button, a button that is on, a
view bar's current tab, an open select's chosen row, the text selection: all
one token, so all one answer. `--accent-deep` carries a lightness cap for
exactly this reason — the accents range from `#2fb8c6` to `#ffb000`, and
forty percent of black is not enough darkening under the bright ones. Five
schemes had text on that fill under AA before the cap, nostromo worst at
3.56:1. `test/uniform.mjs` measures the rendered pixels on every scheme.

Watch the class the words wear. A tab's name is a `.lbl`, which is also the
field-label helper, so it arrived wearing the quiet colour meant for "Your
email" above a text box — on an accent fill, at 2.51:1.

## Shape

8px radius for boxes (cards, panes, modals), 6px for controls (buttons,
fields), 4px for tags, 99px for pills, 50% for dots. Hairlines are
`1px solid var(--line)`.

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

## Controls

The field skin (ground, edge, radius) is applied to the elements globally,
so a new surface's controls match by existing. What a surface adds is
sizing: full-width 13px mono controls mean joining the `.modal input, …`
sizing group, its 16px phone rule (iOS zooms into anything smaller) and its
`:focus` group. Tap targets are `min-height: var(--tap)`. A row of filters
is `<div class="field histbar">`.

**A field's label sits above it**, as `.lbl` (`lbl(id, text, help)`), two
or three words and no more: a field that is filled in still says what it
is, which a placeholder cannot. Where there is something the label cannot
say — a password's rules, what blank means, what a rename costs — it rides
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
carry a label above them with bare controls — a select, a button, a remove —
and a centred line floats the bare one between its neighbour's label and its
field. The bottom is the line the eye reads, whatever is stacked above it and
whatever each control's own height is, so a row of controls sets
`align-items: flex-end` and a row whose text column holds a field does the
same with its action cluster. `test/uniform.mjs` groups every visible control
into lines by vertical overlap and fails when one on a line ends at a
different height.

**A file field is a button of ours and the name of what was picked.** The
browser's own chooser stays hidden: its button wears the browser's skin,
not the page's, and there is no styling it. A `.filepick` — a button that
opens the chooser, and the picked name beside it — is the shape.

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
select as one line high at phone width.

**A button says what it does and stops.** No ellipsis on a label: "Enroll
node", not "Enroll node…" — whether a dialog follows is not the reader's
problem, and the dots are not a word.

**A value that is one line of PROSE is a `textarea.proseline`, never an
`<input>`.** An input shows about thirty characters at phone width, and a
roadmap item, a bug's title, a changelog entry or the reason something was
dropped runs to three hundred: on a phone every one of those was a field you
could not read what you were editing in. A proseline wraps, grows to its
content and never scrolls inside itself. It is still one line — Enter does
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
editor in the notebook — a memory's body, a rule, a bug's repro — is a page
rather than a control and keeps the reading width.

**Every group of settings ends with one action bar** — the state line and
its Apply or Save at the right — and nothing else in the group carries a
button. One place to look for the press, on every section of every tab.

**A control never spans its container.** A button, a select, a text field,
or a row of them side by side, is at most `var(--ctl-w)` wide and never the
full width of the tab, card or band it sits in: it stops short, with the
band's own inset and room beside it, at every width. Full-width controls
read as a form pretending to be a page. The one exception is a control
whose whole point is the width — a terminal, a log. `test/uniform.mjs`
measures every control and control row on every tab against the surface
holding it.

## Settings

Nothing on a tab takes effect until Save or Apply is pressed. A select that
saves the moment it is changed, a checkbox that writes on the click, is a
control that cannot be reconsidered, and the same section's Save then means
two different things. So every group of settings — on the Settings, Users,
Nodes and Artifacts tabs and in the project dialogs — has one Save or Apply
at its foot, and reads its fields when that is pressed. The one exception
is the colour scheme in the gear: a theme is looked at, not decided, and a
swatch that needed a second press to be seen would be answering a question
nobody asked. Buttons that *do* something — install, build, connect, end —
are actions, not settings, and act on the press.

## Document tabs

Reading surfaces, not terminals. A new kind does not write its own chrome: it
calls `docSurface(i, kind)`, which builds the standard skeleton (a
`.doctab.<kind>tab` box capped at `var(--doc-w)`: a filter/actions bar slot,
the band list, a quiet `.fnote` footer) and returns the slots to fill. States
are `.loading` / `.empty` / `.hint.bad` inside the list.

**The bar is a band, not a row of controls.** What the tab is about goes at
its left — a node picker, the filters, a one-line count — and the action on
it at the right, where a row's buttons and a section's status already sit, so
every tab's Refresh is in one place and lines up with the column of actions
under it. The band spans the tab; the controls in it are capped one by one
like any other. A tab that builds its own chrome instead misses all of this:
the Packages tab kept its picker in a band of its own and its Refresh landed
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
the sidebar's cards are the one arrangement that is stored.

Every set of two or more text buttons is an action bar (`.actbar`): the
status on its own `.state` line, the buttons after it at the right, their
own size at every width — a phone gives them the finger height, never the
row. The destructive verb wears `.danger` and comes last, so nothing safe
sits after something that cannot be undone. A button that started something
wears `busy(btn, verb)` until the repaint replaces it. Icon clusters with no
text are exempt.

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
and nothing else — one helper applied to the DOM after a list draws, rather
than each renderer growing its own. It draws a `.pagemore` footer: what is
shown of the total, then Show N more, Show all and Fewer as each becomes
worth offering. It is a bar the framework owns, so it is exempt from the
action-bar rule and its shape is the same on every list.

Deliberately not numbered pages: these lists are read in an order that means
something — bugs by severity, jobs newest first, the roadmap by the order
the work has to happen in — so "page 4" names nothing.

Two judgements are yours. A list that only just crosses the line is left
whole, which `paginate` does for you. And a list somebody SCANS for a name
rather than reads in order — the package catalog — is not paged at all,
because hiding half of it behind a button is worse than a long page.

The state is per list and per notebook. A notebook is a clone of one
template, so its ids belong to every open notebook at once; a key that
forgets which notebook it is in is one bucket shared by all of them, which
is how Show more came to undo itself.

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
something behind them (Roadmap, Briefing, the version on Artifacts). A view
that writes through or only reads — Bugs, Tests, Analysis, Git — has no foot.

## Both sizes

The phone and the desktop are both first-class. A surface is not done until
it has been looked at at both widths: sections open on a desktop and shut on
a phone, no control spans the screen at either, and controls are 16px on a
phone so iOS does not zoom.

## Motion

Everything that appears, leaves, opens or changes state moves: a panel or
menu arrives (`menuIn`), a document brought to the front fades in
(`contentIn`), a section or card folds over its height (`slideBody`, the
section tween), a button or tab eases its colour, a tooltip fades, a toast
slides. A change that snaps is a change the eye has to find. Every one of
them is off under `prefers-reduced-motion`.

**The page waits on its own ground.** Nothing can be drawn in a pane until
the first snapshot lands, and an empty one used to be black and wearing the
active pane's outline — the loudest element on the page, showing nothing, for
as long as that took. Until then `body.booting` gives the pane the page's
ground and the same quiet `loading…` line every other surface waits with, and
the first draw that had state to draw takes the class off.

## Progress

Something that is running says so with a word and an animated ellipsis,
`busy(btn, verb)`, never a bar or a percentage: nothing here can honestly
measure how far along a build or a pull is, and a bar that guesses is a lie
with a scale on it.

## Meters

A bar that measures something real — a disk, memory, a load — is a meter:
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
Packages tab is the one that keeps a timer, and only while a job is running:
an install of a small package starts and finishes inside one revision poll,
so the tab would go from idle to done having never said "installing". It
stops when the job does. Anything else with a clock of its own is a tab that
notices things sooner than the tab beside it for no reason anybody chose,
which is what this whole section is against.

## Words on the screen

One sentence that tells the person what they need to know to act, in their
words. A hint, a state line or an empty state is a line, about 25 words. The
why goes in a code comment, the README or Help, never inline. A stacked row
is `flex-wrap: nowrap`; a long token in it wraps or scrolls inside its own
box, and nothing scrolls the page or the pane sideways on a phone.
