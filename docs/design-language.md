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

**A file field is a button of ours and the name of what was picked.** The
browser's own chooser stays hidden: its button wears the browser's skin,
not the page's, and there is no styling it. A `.filepick` — a button that
opens the chooser, and the picked name beside it — is the shape.

**A button says what it does and stops.** No ellipsis on a label: "Enroll
node", not "Enroll node…" — whether a dialog follows is not the reader's
problem, and the dots are not a word.

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

A new tab lands as: its own classic script file beside `index.html`, an entry
in `TABKINDS` there and `TAB_KINDS` in `server.py`, its top-level names in
`test/surface.mjs`, a driver in `test/uniform.mjs`, and a content test beside
its siblings. Renderers run inside `renderGuarded`, so a throwing renderer is
an error band in its own tab, never a dead dashboard.

## Sections and action bars

A long surface is sections: `docSection(kind, id, title, status, body)`, one
fold per concern with its status on the heading, open on a desktop and
closed on a phone. A status is a word or a number, never a sentence.

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

## The notebook

Every view opens with the same head row: its one-line summary on the left
and its controls, History where it has one, on the right. That row is the
first band of the view and sits at one height on all seven views.

The view strip is one row on a desktop. On a phone it wraps into rows of
equal-width tabs rather than scrolling sideways: seven labels do not fit
393px, and a strip that hides its last two behind an edge is a strip whose
last two views nobody opens. Every tab stays visible at every width.

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

## Words on the screen

One sentence that tells the person what they need to know to act, in their
words. A hint, a state line or an empty state is a line, about 25 words. The
why goes in a code comment, the README or Help, never inline. A stacked row
is `flex-wrap: nowrap`; a long token in it wraps or scrolls inside its own
box, and nothing scrolls the page or the pane sideways on a phone.
