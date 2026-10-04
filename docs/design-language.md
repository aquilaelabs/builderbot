# The design language

What this project looks like, in one place. Written by BuilderBot's Design view from the notebook, so edit it there, or edit here and say so in the notebook. Every surface follows it; a change to the look is a change to this file first.

It governs the dashboard (scripts/dashboard: index.html and the scripts beside it), which the companion app mirrors.

## Color

Color comes only from these tokens, named once in the stylesheet. The app starts on Default; a theme picker, where the app has one, offers the themes by name, and every theme names the same tokens:

### Default (dark, the default)

| token | value | for |
|---|---|---|
| `--bg` | `#1a1f26` | the page |
| `--panel` | `#212730` | a raised box: a card, a pane, a modal |
| `--ink` | `#e6edf3` | the text, and text on a filled accent |
| `--dim` | `#9fa9b4` | secondary text and field labels |
| `--line` | `#4d5c6f` | hairlines and borders, 1px |
| `--accent` | `#3fb950` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d29922` | a warning, and the amber marks |
| `--bad` | `#f8524a` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#58a6ff` | an informational mark, the low level |

### Abyss (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#111d20` | the page |
| `--panel` | `#18262a` | a raised box: a card, a pane, a modal |
| `--ink` | `#dcecee` | the text, and text on a filled accent |
| `--dim` | `#93a9ac` | secondary text and field labels |
| `--line` | `#3e5e66` | hairlines and borders, 1px |
| `--accent` | `#2fb8c6` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d7ab4c` | a warning, and the amber marks |
| `--bad` | `#ef6a63` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#6fb3e0` | an informational mark, the low level |

### Ash (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#1b1b1b` | the page |
| `--panel` | `#222322` | a raised box: a card, a pane, a modal |
| `--ink` | `#e2e4e0` | the text, and text on a filled accent |
| `--dim` | `#a1a59f` | secondary text and field labels |
| `--line` | `#555955` | hairlines and borders, 1px |
| `--accent` | `#a3b18a` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#cfa94a` | a warning, and the amber marks |
| `--bad` | `#e26d60` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#82a7b8` | an informational mark, the low level |

### Carbon (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#141417` | the page |
| `--panel` | `#1c1c1f` | a raised box: a card, a pane, a modal |
| `--ink` | `#e8e8ea` | the text, and text on a filled accent |
| `--dim` | `#9d9da4` | secondary text and field labels |
| `--line` | `#53535b` | hairlines and borders, 1px |
| `--accent` | `#e64e53` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d9a441` | a warning, and the amber marks |
| `--bad` | `#ff6b6b` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#7aa2f7` | an informational mark, the low level |

### Ember (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#1f1814` | the page |
| `--panel` | `#271f1a` | a raised box: a card, a pane, a modal |
| `--ink` | `#f0e4d8` | the text, and text on a filled accent |
| `--dim` | `#af9f90` | secondary text and field labels |
| `--line` | `#67533e` | hairlines and borders, 1px |
| `--accent` | `#f0873f` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#e8bb50` | a warning, and the amber marks |
| `--bad` | `#ef5f52` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#8fb4d9` | an informational mark, the low level |

### Ice (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#151c21` | the page |
| `--panel` | `#1c252c` | a raised box: a card, a pane, a modal |
| `--ink` | `#e3edf5` | the text, and text on a filled accent |
| `--dim` | `#9aa8ae` | secondary text and field labels |
| `--line` | `#465b6c` | hairlines and borders, 1px |
| `--accent` | `#58c7e8` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d3ab52` | a warning, and the amber marks |
| `--bad` | `#ee6a68` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#7cc0ff` | an informational mark, the low level |

### Moss (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#161f1b` | the page |
| `--panel` | `#1d2920` | a raised box: a card, a pane, a modal |
| `--ink` | `#dfe9df` | the text, and text on a filled accent |
| `--dim` | `#9daba0` | secondary text and field labels |
| `--line` | `#48604f` | hairlines and borders, 1px |
| `--accent` | `#63c98a` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d6ad4e` | a warning, and the amber marks |
| `--bad` | `#e8695f` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#74b3d8` | an informational mark, the low level |

### Nocturne (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#181825` | the page |
| `--panel` | `#202031` | a raised box: a card, a pane, a modal |
| `--ink` | `#e4e2f5` | the text, and text on a filled accent |
| `--dim` | `#a2a0c1` | secondary text and field labels |
| `--line` | `#53537b` | hairlines and borders, 1px |
| `--accent` | `#9d7cff` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#e0b24d` | a warning, and the amber marks |
| `--bad` | `#f2637b` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#7cb0ff` | an informational mark, the low level |

### Nostromo (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#101712` | the page |
| `--panel` | `#162018` | a raised box: a card, a pane, a modal |
| `--ink` | `#d7e3c8` | the text, and text on a filled accent |
| `--dim` | `#95a488` | secondary text and field labels |
| `--line` | `#405b37` | hairlines and borders, 1px |
| `--accent` | `#ffb000` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#ffd166` | a warning, and the amber marks |
| `--bad` | `#ff5f45` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#9ad07a` | an informational mark, the low level |

Nostromo differs from the default in:

- Shape, as the rule corners says:
-   This scheme squares all three corner tokens; the pills and the dots stay round, as everywhere.
- Motion, as the rule fold says:
-   This scheme asks for the fade fold with `--fold: fade` on the card: its smoked glass sliding into the title bar read as a bug, so the body fades where it stands, then the gap closes, and the cards below still ride the height.

#### Rules of Nostromo's own

##### nostromo/textures

Applies to: scripts/dashboard/static/nostromo, scripts/dashboard/index.html; texture, hull, svg, decal

This scheme alone carries drawn textures (`static/nostromo/*.svg`, hand-written,
served by the page's allow-list): hull plating behind the page, ribbing in
the left gutter and a glyph strip in the header. Each bakes its own opacity, none sits under text above a third, and
none moves the layout: a texture lives in space the page already leaves
empty. The same suite measures the contrast with them in place. Its panels, the bar of a pane and the ground under a document are `--glass`: the panel color at 70% over the hull, so the plating shows through.

##### nostromo/fold

Applies to: scripts/dashboard/page-motion.js, scripts/dashboard/index.html; fold, fade, card

This scheme asks for the fade fold with `--fold: fade` on the card: its smoked glass sliding into the title bar read as a bug, so the body fades where it stands, then the gap closes, and the cards below still ride the height.

##### nostromo/corners

Applies to: scripts/dashboard/index.html; corner, radius, square

This scheme squares all three corner tokens; the pills and the dots stay round, as everywhere.

### Plum (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#1e1623` | the page |
| `--panel` | `#261d2d` | a raised box: a card, a pane, a modal |
| `--ink` | `#eddff2` | the text, and text on a filled accent |
| `--dim` | `#ae9cb7` | secondary text and field labels |
| `--line` | `#654d73` | hairlines and borders, 1px |
| `--accent` | `#c874d8` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#dfae52` | a warning, and the amber marks |
| `--bad` | `#ee6183` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#83aee8` | an informational mark, the low level |

### Rust (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#1e1614` | the page |
| `--panel` | `#261d1a` | a raised box: a card, a pane, a modal |
| `--ink` | `#ecdedb` | the text, and text on a filled accent |
| `--dim` | `#ae9d99` | secondary text and field labels |
| `--line` | `#6a4e4a` | hairlines and borders, 1px |
| `--accent` | `#cf6a4c` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d9a441` | a warning, and the amber marks |
| `--bad` | `#e8544a` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#7fa8c9` | an informational mark, the low level |

### Sepia (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#1f1b14` | the page |
| `--panel` | `#272219` | a raised box: a card, a pane, a modal |
| `--ink` | `#ece0cb` | the text, and text on a filled accent |
| `--dim` | `#b0a28c` | secondary text and field labels |
| `--line` | `#63563e` | hairlines and borders, 1px |
| `--accent` | `#d3a94f` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#e3c069` | a warning, and the amber marks |
| `--bad` | `#e0705f` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#9db98c` | an informational mark, the low level |

### Slate (dark)

| token | value | for |
|---|---|---|
| `--bg` | `#181c23` | the page |
| `--panel` | `#1f242d` | a raised box: a card, a pane, a modal |
| `--ink` | `#dfe5ec` | the text, and text on a filled accent |
| `--dim` | `#9fa6ae` | secondary text and field labels |
| `--line` | `#4f5a68` | hairlines and borders, 1px |
| `--accent` | `#6ea8fe` | the one color that means this is the one: the active tab, the primary button, a link |
| `--warn` | `#d9a441` | a warning, and the amber marks |
| `--bad` | `#ef6f6c` | an error, a destructive verb, the reason under a dead control |
| `--note` | `#7fb8ff` | an informational mark, the low level |

## Type

The platform's own sans-serif: system-ui on Web, Roboto on Android, SF Pro on iOS, the desktop's own on Linux, SF Pro on macOS, Segoe UI Variable on Windows, set as system-ui for the page; a monospace stack (--mono) for data: names, paths, versions, anything a terminal could print; --f-note, --f-ui and --f-tag for the three secondary voices.

## Shape

Small radii: 6px on controls, 8px on boxes, 4px on tags.

## Space

An ordinary rhythm: 11px by 14px bands, 10px between fields.

## Motion

Short eases on state changes, nothing decorative, and none under prefers-reduced-motion.

## Rules

Each is one rule of the design, by name; a session is handed one on the turn it edits a file or is asked about a word the rule names, and `bb design show NAME` reads one.

### design-language

The page's visual rules, in one place. Read this before adding or restyling
any surface, and extend the group selectors named here rather than restyling
locally. `test/uniform.mjs` measures most of what follows on every tab and
fails by name; the house rule `design` points here and runs it.

### color

Applies to: scripts/dashboard/index.html, scripts/dashboard/static; color, scheme, theme, palette, hex, contrast

Color comes only from the tokens in `:root`: surfaces `--bg` / `--panel` /
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
A scheme that carries drawn textures says so in its own rules (Nostromo does).

Watch the class the words wear. A tab's name is a `.lbl`, which is also the
field-label helper, so it arrived wearing the quiet color meant for "Your
email" above a text box, on an accent fill, at 2.51:1.

The edge of a filled accent surface, and the tick of a checkbox, is `--accent-mid`: the accent darkened by 14%, between the accent and `--accent-deep`.

### shape

Applies to: scripts/dashboard/index.html; corner, radius, rounded, hairline, border

Three corners, as tokens: `--r-surface` (8px) for boxes (cards, panes,
modals), `--r-control` (6px) for controls (buttons, fields, tabs), `--r-small`
(4px) for tags. Never the number: a scheme may square all three, and nostromo
does. 99px for pills and 50% for dots are not corners and stay round
everywhere. Hairlines are `1px solid var(--line)`.

A color is a token too, including the ones that look like a one-off: a
danger edge is `--red2-edge`, a warn edge `--gold-edge`, text on a filled
accent is `--bg`, and a hover shade is `color-mix()` of the scheme's own.
A hex outside the scheme blocks is the default scheme leaking into the
other eleven, and the check counts them.

### type

Applies to: scripts/dashboard/index.html; font, mono, typography, text, size

`--mono` for data: names, paths, versions, anything a terminal could print.
Three secondary voices: `--f-note` (a quiet explainer, in `var(--dim)`),
`--f-ui` (secondary UI), `--f-tag` (pills and badges). Severity and level
colors agree everywhere: error and high are red, warning and medium yellow,
note and low blue.

What a row says is `--f-row` (13px system sans), what is typed into is `--f-field` (mono, a step below the text beside it, because mono at the same size reads larger), and a pill is `--f-tag`.

### space

Applies to: scripts/dashboard/index.html; padding, spacing, gap, inset, margin

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

### controls

Applies to: scripts/dashboard/index.html, scripts/dashboard/tab-*.js, scripts/dashboard/nb-*.js, scripts/dashboard/page-*.js; control, field, input, select, button, listbox, label, placeholder, textarea, picker

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

**Every control on a row is one height, the finger's (`--ctl`, which is
`--tap`).** A field, a pulldown, a one-line prose box and a button beside
each other were 35, 35, 38 and 30px (the operator, 29 Sep): now every
input, select, proseline and button in a document, a notebook or a dialog
takes `min-height: var(--ctl)`, the color swatches alone keeping their
circle, and `test/uniform.mjs` fails a line of controls that are not one
height. The sidebar's cards and the header keep their own smaller buttons,
which sit beside no field.

**Controls on a row line up at their bottom edge.** A row mixes fields that
carry a label above them with bare controls (a select, a button, a remove)
and a centered line floats the bare one between its neighbor's label and its
field. The bottom is the line the eye reads, whatever is stacked above it and
whatever each control's own height is, so a row of controls sets
`align-items: flex-end` and a row whose text column holds a field does the
same with its action cluster. `test/uniform.mjs` groups every visible control
into lines by vertical overlap and fails when one on a line ends at a
different height.

**A set of things to pick from is a listbox.** Several nodes a project
works on, several projects it reads: a `.lbox`, a bordered box of checkbox
rows (`label.lrow`: the box, the name, a quiet note at the right), each a
thumb high, scrolling past four so it stays small, under a label like any
field. It is the one thing besides a text box that may scroll inside a
dialog: the dialog still scrolls in one place around it, since a box of
forty projects that did not scroll would be the dialog. Never a
`select multiple`, whose list is the platform's and whose picks are
invisible once it closes, and never a loose column of checkboxes, which has
no edge to say where the choice ends. The project settings dialog draws
both of its sets this way (`lrow` in `page-projsettings.js`).

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
otherwise, and what says otherwise says why in place.** The color schemes,
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

### settings

Applies to: scripts/dashboard/tab-settings.js, scripts/dashboard/page-projsettings.js; setting, apply, save, checkbox, switch, toggle

Nothing on a tab takes effect until Save or Apply is pressed. A select that
saves the moment it is changed, a checkbox that writes on the click, is a
control that cannot be reconsidered, and the same section's Save then means
two different things. So every group of settings, on the Settings, Users,
Nodes and Artifacts tabs and in the project dialogs: has one Save or Apply
at its foot, and reads its fields when that is pressed. The one exception
is the color scheme in the gear: a theme is looked at, not decided, and a
swatch that needed a second press to be seen would be answering a question
nobody asked. Buttons that *do* something (install, build, connect, end)
are actions, not settings, and act on the press.

### files

Applies to: scripts/dashboard/index.html; script, module, file, load

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

### sections-and-action-bars

Applies to: scripts/dashboard/tab-*.js, scripts/dashboard/nb-*.js; section, fold, action, bar, actbar, hidden

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

### rows-you-open

Applies to: scripts/dashboard/nb-*.js, scripts/dashboard/tab-profile.js, scripts/dashboard/nb-artifacts.js; row, fold, edit, cancel, download

A row with detail behind it is a fold, the shape a bug report has: the name
on the line with its pills, the fields under labels when opened, its action
bar at the foot, and a line divider between rows rather than a box. Rules
and memories on the Briefing tab and the tests on the Tests tab are this
shape too.

A row opens to be read, never as a form. Edit on its action bar swaps the
fields in; Cancel (`.stop`) puts them away and drops what was typed, and
Save puts them away having written it. A row Add made has nothing to go
back to, so canceling it removes it.

A list of things to download or open is the Artifacts tab's rows
(`.artrow`) wherever it appears: the name in bold with its facts in the
small mono beside it, a hairline between rows, and the download or the
action at the row's right, wrapping under it on a phone. The Profile's
conversation logs are those rows, not a list of their own.

### long-lists

Applies to: scripts/dashboard/nb-*.js, scripts/dashboard/tab-*.js; list, page, paginate, pagination

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

### motion

Applies to: scripts/dashboard/index.html, scripts/dashboard/page-motion.js; motion, animation, animate, fade, transition, tween

Everything that appears, leaves, opens or changes state moves: a panel or
menu arrives (`menuIn`), a document brought to the front fades in over its
own ground (`docIn`, contentIn's frames under a name of its own, so a
document that already wears contentIn from its first paint still fades when
it comes forward), a section or card folds over its height
(`slideBody`, the section tween), a button or tab eases its color, a
tooltip fades, a toast
slides, a modal leaves the way it arrived (caught off the `hidden` attribute
by one observer, so no close site has to remember), and a row folding its
controls out on a phone slides over the height that takes. A change that
snaps is a change the eye has to find. Every one of them is off under
`prefers-reduced-motion`. A scheme may ask for a different fold with
`--fold: fade` on the card; a scheme that does says why in its own rules (Nostromo does).

**What fades is what is drawn, never the ground under it.** A document's
ground (the page color, the panel color, nostromo's glass and scanlines)
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

### progress

Applies to: scripts/dashboard/page-docs.js; progress, busy, spinner, percentage

Something that is running says so with a word and an animated ellipsis,
`busy(btn, verb)`, never a bar or a percentage: nothing here can honestly
measure how far along a build or a pull is, and a bar that guesses is a lie
with a scale on it.

### meters

Applies to: scripts/dashboard/tab-nodes.js; meter, gauge, bar, track

A bar that measures something real (a disk, memory, a load) is a meter:
a label, a track, a value. Meters come in stacks, and a stack is read as
one set of gauges, so every track in it is the same width and the values
sit in one right-aligned column. The value column has a fixed width sized
to the widest value the stack can show; it is never `auto`, because then
each row sizes its bar to whatever its own number leaves it, the long
values shorten their bars, and the stack reads as a ragged edge instead of
a comparison. `uniform.mjs` measures every stack on every tab for this.

### when-a-view-re-reads

Applies to: scripts/dashboard/page-poll.js, scripts/dashboard/nb-*.js, scripts/dashboard/tab-*.js; poll, refresh, revision, redraw, re-read, timer

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

### words-on-the-screen

Applies to: scripts/dashboard; hint, wording, text, copy, sentence, empty, state, line

One sentence that tells the person what they need to know to act, in their
words: what the control does, and the one consequence they could not guess.
Not what they can intuit, not how it came to be, not the reasoning; a
paragraph on a control is one nobody reads, and a page of them turns the
reader off (the operator, 23 Sep, after R28 swept them). A hint, a state
line or an empty state is a line, about 25 words. The why goes in a code
comment, the README or Help, never inline. A stacked row
is `flex-wrap: nowrap`; a long token in it wraps or scrolls inside its own
box, and nothing scrolls the page or the pane sideways on a phone.

### badges

Applies to: scripts/dashboard/index.html, scripts/dashboard/nb-*.js; badge, pill, tag, severity, sev

A tag that says who or what (a memory's type, a bug's severity and state, who wrote a history line) wears one of five badge colors, the same on every scheme, named once on `:root`, each with an edge for the pill's border: `--purple` `#b79ae0` (edge `--purple-edge` `#38294a`) for who did it, a reference and a state that does not apply; `--green2` `#7fc08a` (`--green2-edge` `#1f3f28`) for what is new, a project's own and fixed; `--blue2` `#77b7e8` (`--blue2-edge` `#1e3a4a`) for the user's, low and open; `--gold` `#d8b25c` (`--gold-edge` `#4a3c1e`) for a note, feedback, medium and a toggle that is on; `--red2` `#e0796f` (`--red2-edge` `#94423d`) for what is gone and high. Never a hex at the site: the day one shade drifts is the day two tags of one family stop looking like it. The pill's text is `--f-tag`.

### project-color

Applies to: scripts/dashboard/index.html, scripts/dashboard/page-panes.js, scripts/dashboard/page-projsettings.js, scripts/dashboard/tab-docker.js; project color, stripe, swatch, tone

A project may carry a color, one of the nine swatches in its settings, and the page says whose a thing is with it in four places and no others: its tab in the strip (a 3px stripe on the left, a tint of 10% at rest and 28% when it is the one in front), its row in the sidebar (the stripe and a 6% tint, on the card), the bar of the pane showing it (the stripe only), and the heading of its group in the Docker manager (a 4px stripe and a 16% tint, as `--gc`, the line color for containers that belong to no project). The bar keeps the ground every bar has: a tint there sat over the pane's black and made a notebook's bar the one bar that looked like no other (the operator, 29 Sep). The color arrives as `--pc` on the element; the swatches are circles of their own size, never the control height.

## Pages

Each page is a layout of labeled blocks on a frame, named for what it is for, on the platform it is built for.

### the dashboard (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the dashboard on a desktop frame (12 columns by 8 rows), from the App shell template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the brand, the build stamp and uptime, the bell, the gear and sign out, across the top, row 1 of 8
  2. Sidebar (a side column): the cards, folding; the one arrangement stored per device, on the left, columns 1 to 3 of 12, rows 2 to 8 of 8
  3. Card (a box holding one thing): Doctor, Tools, Administration, Runner: each a fold with its state on the title bar, on the left, columns 1 to 3 of 12, rows 7 to 8 of 8, inside block 2 (Sidebar: the cards)
  4. Card (a box holding one thing): Projects, first: the pinned projects, and a session's state as a dot on each, on the left, columns 1 to 3 of 12, rows 2 to 6 of 8, inside block 2 (Sidebar: the cards)
  5. List (rows of like things): a project row: name, dot, Claude, notebook, and … for shell, link, phone, report, lock, pin, on the left, columns 1 to 3 of 12, row 3 of 8, inside block 4 (Card: Projects)
  6. Tabs (a strip of tabs switching one area): the tab strip: terminals and document tabs, a + to open one, on the right, columns 4 to 12 of 12, row 2 of 8
  7. Content (the main reading or working area): the pane: a terminal or a document tab, one on show, two panes side by side on a wide desk, on the right, columns 4 to 12 of 12, rows 3 to 7 of 8
  8. Footer (the band at the foot): the bottom bar: Commands, Sessions, Chat, on the right, columns 4 to 12 of 12, row 8 of 8
Notes:
  A document tab is a reading surface built by docSurface: a bar band, the band list, a quiet footer. Everything that appears or changes state moves, and nothing fades its own ground. The bell fills amber and pulses while something waits on you. A project row's dot is the session's state in the one palette every dot here wears: working pulses, waiting is amber (30 Sep). The pin on the card's rows takes a project off the card; the Projects tab puts it back. A project's Claude button opens a small chooser under it when there is something to choose: Open tab and End session where your session is running, Resume and New conversation where you are signed in to Claude on its node, Sign in on that node where you are not, and for a project on several nodes each node under its name with its own. The bug on a project's row (report a bug) opens a small dialog: Category (a pulldown of what it is about), What happened, How to make it happen (optional) and Send, which puts it in the diagnostics under that project, the node and the build attached, as a session's bb report does; a person's is heard whatever the project's Claude dial for reports says. Projects is the first card and a new layout opens on the Projects tab with the controller's shell beside it (R119, 4 Oct): the projects are what a person comes for. The sidebar card's rows fold at every width (R119): Claude, the notebook and … for the rest, as a phone's; the Projects tab shows every icon on a desktop. A project's settings are its notebook's Settings view (R119 step 3): the row has no settings button.
This page's own rules:
  the-dashboard/document-tabs: scripts/dashboard/tab-*.js; tab, document, docsurface, bar (`bb design show the-dashboard/document-tabs` reads it)

#### Rules of the dashboard's own

##### the-dashboard/document-tabs

Applies to: scripts/dashboard/tab-*.js; tab, document, docsurface, bar

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

### a notebook (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Content (the main reading or working area): the view, across the middle, rows 2 to 7 of 8
  3. Header (the band at the top): the head row: its one-line summary on the left, its controls and History on the right, at one height on every view, across the middle, row 2 of 8, inside block 2 (Content: the view)
  4. Form (fields a person fills in): the add bar: the first band under the head row, a button named for what it adds, its form unrolling in its place, across the middle, row 3 of 8, inside block 2 (Content: the view)
  5. List (rows of like things): the sections: folds with their count on the title, each remembered open or shut; rows that open on a slide, across the middle, rows 4 to 7 of 8, inside block 2 (Content: the view)
  6. Footer (the band at the foot): Save and Revert, only on the views that stage something, across the bottom, row 8 of 8
Notes:
  One notebook per project, a clone of one template. Every view opens with the same head row at one height. A row with detail behind it is a fold that opens to be read, never as a form.
This page's own rules:
  a-notebook/views: scripts/dashboard/nb-*.js; notebook, view, head, row, strip (`bb design show a-notebook/views` reads it)

#### Rules of a notebook's own

##### a-notebook/views

Applies to: scripts/dashboard/nb-*.js; notebook, view, head, row, strip

Every view opens with the same head row: its one-line summary on the left
and its controls, History where it has one, on the right. That row is the
first band of the view and sits at one height on all ten views.

The view strip is one row on a desktop. On a phone it wraps into rows of
equal-width tabs rather than scrolling sideways: ten labels do not fit
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
Artifacts). A view that writes through or only reads (Bugs, Wiki, Tests,
Analysis, Git) has no foot.

The Design view is two folds under its head row: Pages and Themes, in
that order, both closed on a new tab so the view opens short, and each
showing one entry at a time, chosen on a pulldown at the fold's top: every
page and every theme at once was the whole view scrolled past (the
operator, 28 Sep). The one shown is fields like any tab's, never a box of
its own. Adding is inside the fold it adds to (the operator, 30 Sep): Add
page, with its platform, its template and a page here to copy, is the first
band inside Pages; Add theme, from blank, a preset or a copy of a theme, the
first inside Themes; blank is the default of both, and what is added is
what is shown. The design language is each theme's (the operator, 30 Sep):
the first theme is the default, and its type, corners, space, motion,
families and rules are the design's; another theme's are its own. Rules
live inside the entry they hold for and nowhere else (the operator, 29
Sep): a Rules section inside each theme above its colors and one inside
each page under its board, each following the pulldown; a rules fold below
everything read as the rules. Every rules list here is the Briefing's
(nb-rules.js): Add a rule first, a folded row a rule with its name and when
it reaches a session, Edit turning the row into its form. A new project's
design is empty, no theme and no page: the session that builds it chooses
the look and puts it here after. The view is passive: nothing on it reaches
into a session and nothing on it is a prompt; a session reads the design
piece by piece, through its rules and `bb design show`, never as one dump.
A session meets a theme's or a page's own rule as HOLDER/RULE, and the
default theme's bare.

**The Design view's board is the one surface here whose colors are data.**
A page's blocks are painted in the project's own language (`nb-design.js`,
`blockStyle`), inline from the saved hex, because the board is a picture of
that project and not chrome of this page; everything around the board (the
frame's edge, the selection outline, the sizing corner) is the page's
tokens, and the corner shows on the selected block only, since a tap
selects a block before anything drags it. Its controls are the framework's:
choices in labeled selects on a `.dsrow` that lines up at the bottom, the
row's prose field growing only to the width the other tabs give a field so
what follows it stays beside it, colors as a chip beside a seven-character
field, prose in a proseline.

The Wiki view reads like an encyclopedia (the operator, 2 Oct), not as rows: the pages listed in a
narrow column (the wiki's own _Sidebar when it has one) beside one article at a time, its title large in
the serif over a hairline, its sections headed the same way, a Contents box for three or more, and the
prose in --serif at a reading width, the one place the dashboard sets text to be read at length. Read and
Edit are tabs over the article, with Rename and Remove at their right. Its head row carries History alone;
under it an action bar says where the wiki goes and holds Export, with Pull and Push when the project has
a remote, so the head row fits a phone, where the column gives way to a picker above the article. Why
Push is dead (no push rights) is said in red under that bar, never only in a tooltip. New page is the
band under the head row, the first page offered as Home. Under Claude may: Write the wiki hidden the view is unchanged for a person; only a session is kept out.

The Briefing's rules section lists the global rules under the project's own, each a row that
opens to read with an On for this project switch, staged behind the notebook's Save like the
rules above it. An administrator's rows also carry Edit and Remove, or Off everywhere for a
shipped one, each written at once for every project, and Add a global rule is the band over
them; nowhere else on the dashboard edits a global rule.

### the dashboard on a phone (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the dashboard on a phone on a phone frame (6 columns by 12 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the brand, the uptime, the bell, the gear and sign out, across the top, row 1 of 12
  2. Tabs (a strip of tabs switching one area): Dashboard or Terminal: the two panels take turns, across the middle, row 2 of 12
  3. Content (the main reading or working area): the panel on show, across the middle, rows 3 to 11 of 12
  4. Card (a box holding one thing): Dashboard: the sidebar's cards, Projects open and the rest folded, as the device last left them, across the middle, rows 3 to 7 of 12, inside block 3 (Content: the panel on show)
  5. List (rows of like things): a project row: name, dot, Claude, notebook, and … for shell, link, phone, report, lock, pin, across the middle, row 4 of 12, inside block 4 (Card: Dashboard)
  6. Content (the main reading or working area): Terminal: the tab strip wrapping into rows, and the pane, across the middle, rows 8 to 11 of 12, inside block 3 (Content: the panel on show)
  7. Footer (the band at the foot): Keys, Commands, Sessions, Chat, sharing the width, across the bottom, row 12 of 12
Notes:
  Sections open on a desktop and shut on a phone, and a card opened here stays open after a reload. The notebook's strip wraps into rows of equal tabs. A bar of buttons shares the width so the last is never cut off, down to a 344px fold cover. A row's more button slides the row over the height its controls take, whether or not the card grows (30 Sep).
This page's own rules:
  the-dashboard-on-a-phone/both-sizes: scripts/dashboard/index.html; phone, mobile, touch, tap, width, responsive, fold, cover (`bb design show the-dashboard-on-a-phone/both-sizes` reads it)

#### Rules of the dashboard on a phone's own

##### the-dashboard-on-a-phone/both-sizes

Applies to: scripts/dashboard/index.html; phone, mobile, touch, tap, width, responsive, fold, cover

The phone and the desktop are both first-class. A surface is not done until
it has been looked at at both widths: sections open on a desktop and shut on
a phone, no control spans the screen at either, and a typed field is 16px
on iOS alone, so Safari does not zoom.

A finger is not a pointer. On a coarse pointer (`@media(pointer:coarse)`)
every button in a dialog and in the notebook is `--tap` high, and the small
controls a thumb meets (a tab's close and minimize, the new-tab button, the
color swatches) are at least 30px; a desktop keeps its tighter strip. A bar
of buttons that spans a phone shares its width (`flex: 1 1 0; min-width: 0`)
rather than each taking its text's, so the last one is never cut off: at
344px, a folding phone's cover screen, four did not fit. "Both widths" means
a small phone (360 to 375), the fold cover (344), an unfolded fold (690 to
840, still the phone layout) and a desktop.

### a dialog (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a dialog on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): a modal over the page, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
  2. Header (the band at the top): its h3: what the dialog is, in a few words, in the middle, columns 4 to 9 of 12, row 2 of 8, inside block 1 (Overlay: a modal over the page)
  3. Form (fields a person fills in): every line a field band; groups headed by a label; the two gaps and no others, in the middle, columns 4 to 9 of 12, rows 3 to 6 of 8, inside block 1 (Overlay: a modal over the page)
  4. Footer (the band at the foot): the foot: the state on the left, Cancel and the one filled button on the right; Escape closes it, in the middle, columns 4 to 9 of 12, row 7 of 8, inside block 1 (Overlay: a modal over the page)
Notes:
  Two gaps down a dialog and no others: the field gap between the things in a band, the label gap between a label and its control. It scrolls in one place; a text box and a listbox are the only things that scroll inside it. A dialog opens at its top every time, whatever was scrolled or focused last. One taller than the screen scrolls inside its box and says so: the edge darkens, a soft shadow on each edge with more past it, gone at the end; a document pane does the same, and so does a list or a log that scrolls inside a surface (a project's Reads, the notebook's lists, a job's log, the chat), with a shallower shadow.
This page's own rules:
  a-dialog/layout: scripts/dashboard/index.html, scripts/dashboard/page-*.js; dialog, modal, popup, pop-up, foot (`bb design show a-dialog/layout` reads it)

#### Rules of a dialog's own

##### a-dialog/layout

Applies to: scripts/dashboard/index.html, scripts/dashboard/page-*.js; dialog, modal, popup, pop-up, foot

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

### signing in (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of signing in on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Card (a box holding one thing): one panel in the middle of the page: the mark and the name, then the form, in the middle, columns 5 to 8 of 12, rows 3 to 6 of 8
  2. Form (fields a person fills in): Username, Password and Sign in, the one filled button; a refusal is said under it, in the middle, columns 5 to 8 of 12, rows 4 to 6 of 8, inside block 1 (Card: one panel in the middle of the page)
Notes:
  The only page with nothing around it: the page's ground and one panel, 340px wide, centered both ways. The mark is the scheme's accent and the button is the deep accent with ink on it, as every filled surface is. Nothing else is reachable before it.

### a terminal tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a terminal tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the pane bar: which session this is, by its kind and its project, across the top, row 1 of 8
  2. Content (the main reading or working area): the terminal itself, the session as tmux has it: Claude or a shell, across the middle, rows 2 to 7 of 8
  3. Footer (the band at the foot): Commands, Sessions and Chat; on a phone Keys joins them for what a touch keyboard lacks, across the bottom, row 8 of 8
Notes:
  A terminal is the one surface here that is not the dashboard's to draw: the frame shows the session and the chrome stays out of it. The bar wears the project's color as a stripe. Commands types a line from the fixed tables or the operator's own list into a shell, never into a Claude session; Sessions lists what is running; Chat is between accounts.

### the Toolchains tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Toolchains tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: which node's store this is, and Refresh, across the top, row 1 of 8
  2. Text (a block of prose): the store's path on that node, across the middle, row 2 of 8
  3. Card (a box holding one thing): this machine's own: the NVIDIA driver and, under it, the container toolkit, each a row to tick like the rest, across the middle, row 3 of 8
  4. List (rows of like things): the toolchains by group, across the middle, rows 4 to 6 of 8
  5. Card (a box holding one thing): a row to tick: what it is, its size, what it needs, its version; installed as a pill, across the middle, row 5 of 8, inside block 4 (List: the toolchains by group)
  6. List (rows of like things): Not for this node: a fold of the ones its platform cannot run, with why, across the middle, row 7 of 8
  7. Button (an action to press): Install selected and Check for updates; what the one job is doing is said beside them, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). Toolchains are installed on nodes and never on the controller, so the picker lists agent nodes only. An install is a job on the node: the rows are read again as it runs, and the line beside the buttons says what it is doing rather than the button changing its words. The NVIDIA driver is the machine's and not the store's (R102): its row sits above the store's list and behaves as they do, a tick into the same Install selected (last, since it ends at a restart), a bin, and the same Check for updates. Its pulldown lists the branches apt offers there, the recommended one first, and is ghosted while a driver is installed: another version means removing this one first. One line says where the driver stands (not installed, waiting for a restart, running the card, removed but still loaded), and on a guest machine the row says whose it is instead of offering a press. The NVIDIA container toolkit is a second row of the same kind under it, where the node has Docker: no pulldown, one line for where it stands (not installed, installed, installed but unknown to Docker), and its description says where it comes from, since installing it adds NVIDIA's own package source to the machine.

### the Emulator tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Emulator tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: which node, and Refresh, across the top, row 1 of 8
  2. Text (a block of prose): the store the images live in, across the middle, row 2 of 8
  3. Form (fields a person fills in): add an image: the API level, the flavor, and Add, across the middle, row 3 of 8
  4. List (rows of like things): the images held, across the middle, rows 4 to 7 of 8
  5. Card (a box holding one thing): an image: what it is and can do in a sentence, its size, its package and the AVD made from it, across the middle, row 5 of 8, inside block 4 (List: the images held)
  6. Footer (the band at the foot): the terms the images come under, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). The flavors say what they are for in a sentence (Play services or not, rootable or not), since the package name says it to nobody.

### the Docker tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Docker tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: which node's daemon, and how it is reached, across the top, row 1 of 8
  2. List (rows of like things): containers grouped by the project that owns them, the group headed in the project's color; no project last, across the middle, rows 2 to 7 of 8
  3. Card (a box holding one thing): one container: running as a pill, where it came from, Details, Ports and mounts; why a control is dead, in red under it, in the middle, columns 2 to 11 of 12, rows 3 to 6 of 8, inside block 2 (List: containers grouped by the project that o)
  4. Button (an action to press): the container's own action bar: Up, Down, Env or Edit, Rebuild (no cache, pull), Remove, in the middle, columns 2 to 11 of 12, row 6 of 8, inside block 3 (Card: one container)
  5. Footer (the band at the foot): New container and Refresh, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). A group is headed by its project in the project's color. A container's row says whether it runs as a pill, never as colored words alone. Why a control is dead is written under the row in red, since a tooltip is nothing on a phone. A session's request to rebuild is answered here.

### the Nodes tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Nodes tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: which node, Create sandbox VM and Enroll node, across the top, row 1 of 8
  2. Card (a box holding one thing): the node: online and live as pills, where it dials in from, its agent and its Claude Code, Update, and Test, across the middle, rows 2 to 3 of 8
  3. List (rows of like things): its sections, across the middle, rows 4 to 7 of 8
  4. Card (a box holding one thing): a section, a fold with its own Apply: Health, Sessions, GPU, Claude Code, Storage, Network, Runner, or why not, across the middle, rows 5 to 6 of 8, inside block 3 (List: its sections)
  5. Footer (the band at the foot): what a node is for, in a sentence, across the bottom, row 8 of 8
  6. Form (fields a person fills in): Claude Code opens on your own sign-in on this node: who you are signed in as and Sign out, or Sign in, in the middle, columns 2 to 11 of 12, row 6 of 8, inside block 4 (Card: a section)
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). Health draws meters: a track with a fill, the number beside it; a node whose NVIDIA driver answers adds two, gpu (how busy the card is) and vram (its own memory), under cpu and memory. A section the node cannot offer says why in its place rather than being missing. A node with an NVIDIA card has a GPU section among its folds: two switches, render the Android emulator on the card and let sessions and jobs compute on it, and one Apply, as every section here. The GPU line under Health is a status: it names the card, and with no NVIDIA driver on the machine it offers Install the driver, which opens that node's Toolchains tab. A Claude sign-in is one account's on one node, so it is drawn for whoever is looking at the top of that node's Claude Code section, each state one action bar: what is so on the state line, the press after it, and the reason a press is dead on a line under it. While a sign-in runs the bar gives way to its link, a labeled field for the code, and Cancel, Start over and Send. An account that does not administer sees the tab for the nodes its own projects are on: every control on it is ghosted but the picker and its own sign-in, and one line on the node's row says why.

### the Jobs tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Jobs tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: a filter for the ones still running, across the top, row 1 of 8
  2. List (rows of like things): jobs, newest first; a long list pages rather than scrolling forever, across the bottom, rows 2 to 8 of 8
  3. Card (a box holding one thing): a job: state as a pill, its kind, where, when, how long, who asked, and Log, across the middle, row 3 of 8, inside block 2 (List: jobs)
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). A long list pages rather than scrolling forever. Log opens the job's output in a dialog.

### a node's Phone section (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a node's Phone section on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: which node the phone is plugged into or paired with, and Refresh, across the top, row 1 of 8
  2. Card (a box holding one thing): whether a phone is connected, as a pill, and Connect, the filled button, across the middle, rows 2 to 3 of 8
  3. Form (fields a person fills in): pairing: the code from the phone, and Pair, with the steps to get one, across the middle, rows 4 to 6 of 8
  4. List (rows of like things): what sessions have asked of the phone, across the middle, row 7 of 8
  5. Card (a box holding one thing): an ask: its reason, its command, Allow and Deny, across the middle, row 7 of 8, inside block 4 (List: what sessions have asked of the phone)
  6. Footer (the band at the foot): a session reaches the phone only by asking, across the bottom, row 8 of 8
Notes:
  A fold of a node's page on the Nodes tab (the operator, 2 Oct: each node with adb holds its own phone), shown on a node whose census carries adb, shut until opened: the phone and who connected it, Connect by IP, Pair, the phones the node remembers, and the asks waiting on its owner. Live for any account whatever the node's other settings allow, since a phone is its owner's. Under the connected phone, its owner's Lend to a project row: a project picker (only projects on the phone's node), For (1 hour, 4 hours, until taken back) and Lend, with why it cannot be lent in red under it when no project fits. Once lent, a row says Lent to PROJECT with the time left as a pill, which apps its sessions drive, and the newest screenshot a session took at a phone's proportions (updated on the next poll), with Look now and Take back on the owner's action bar; the section's last band says the lease's terms beside Refresh.

### Controller settings (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of Controller settings on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: what this tab is, and where appearance lives instead, across the top, row 1 of 8
  2. List (rows of like things): seven sections, across the middle, rows 2 to 7 of 8
  3. Form (fields a person fills in): a section: a group of fields, a draft until its own Apply at its foot, across the middle, rows 3 to 4 of 8, inside block 2 (List: seven sections)
  4. Footer (the band at the foot): when a change takes effect: at once, or at the next start, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). Nothing here takes effect on the change: each section is a draft until its Apply. The color scheme is not here; it is in the gear, since a theme is looked at and not decided.

### the Users tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Users tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: who may sign in here, and which projects they see, across the top, row 1 of 8
  2. List (rows of like things): accounts, across the middle, rows 2 to 4 of 8
  3. Card (a box holding one thing): an account: role as a pill, what it sees, its Claude sign-in, Edit and Remove; the owner's row says why it has neither, across the middle, row 3 of 8, inside block 2 (List: accounts)
  4. Text (a block of prose): What an account gets: a fold saying what a user and an admin each are, across the middle, row 5 of 8
  5. Form (fields a person fills in): Add somebody: a name, a role, and Add, across the middle, rows 6 to 7 of 8
  6. Footer (the band at the foot): how a password is set from a shell, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). The owner's row says it cannot be deleted or given another role, under the row, where a dead button would otherwise be the first you heard of it.

### the Profile tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Profile tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: who you are here, your role, and your Claude sign-in, across the top, row 1 of 8
  2. List (rows of like things): five sections: Who you are, Password, Claude, Plugins and Conversations, each with its own Save, across the middle, rows 2 to 7 of 8
  3. List (rows of like things): Conversations: your sessions with Claude here, newest first, divided by hairlines, each a download, across the middle, rows 6 to 7 of 8, inside block 2 (List: five sections)
  4. Footer (the band at the foot): your commits carry the git name and email above, across the bottom, row 8 of 8
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). Conversations lists the account's own sessions with Claude, newest first, divided by hairlines as the Artifacts list is, each a download.

### the Analysis tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Analysis tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar: the scanners' reports, by project, across the top, row 1 of 8
  2. List (rows of like things): findings grouped by project and scanner, across the bottom, rows 2 to 8 of 8
  3. Card (a box holding one thing): a finding: severity as a badge, its title; opens to its detail, across the middle, row 3 of 8, inside block 2 (List: findings grouped by project and scanner)
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). With no reports folder connected the tab says so in one line and where to read how.

### the Projects tab (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the Projects tab on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the bar, and New project, across the top, row 1 of 8
  2. List (rows of like things): every project the account may see, across the bottom, rows 2 to 8 of 8
  3. Card (a box holding one thing): a project: its color, branch, the session's dot, Claude, shell, lock, pin, delete; what is wrong in red under it, across the middle, row 3 of 8, inside block 2 (List: every project the account may see)
Notes:
  A document tab: the bar band, the list of bands, a quiet footer (docSurface). The pin on a row puts the project on the sidebar's card or takes it off, and the card's rows carry it too, so a project is unpinned from either (30 Sep): the sidebar shows the ones you work on, this tab all of them. Lock warns which sessions are running and ends them all; a user's account cannot lock or unlock.

### a notebook: Briefing (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Briefing on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: what every session here starts with, and History, across the middle, row 2 of 8
  3. Chart (a chart or a meter): Code base: open by default; the languages as one bar, counted from what git tracks, across the middle, row 3 of 8
  4. List (rows of like things): Your rules: standing ones in full, named ones with what calls for each, across the middle, rows 4 to 5 of 8
  5. Text (a block of prose): What a session is sent: the exact text, its size, and each part against its share, across the middle, row 6 of 8
  6. List (rows of like things): Memories: a fold, shut by default, its count on the title; Write a memory inside, across the middle, row 7 of 8
  7. Footer (the band at the foot): Save and Revert: what was changed is a draft until Save, across the bottom, row 8 of 8
Notes:
  What a session is sent is shut by default: a thing to check, not to read every time. It turns amber when a part is over its share of a session's prompt, and says what that part left out. Memories fold shut by default and Code base stays open (30 Sep): the languages are one glance, the memories a list to open when wanted.

### a notebook: Design (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Design on a desktop frame (12 columns by 14 rows: the frame shows 8 of them, and the page scrolls), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 14
  2. Header (the band at the top): the head row: how many pages, whether docs/design-language.md is written and current, and Write the file, across the middle, row 2 of 14
  3. Content (the main reading or working area): Pages: a fold, closed on a new tab, its count on the fold; one page shown at a time, across the middle, rows 3 to 9 of 14
  4. Form (fields a person fills in): Add page: the platform, the template it starts from, or a copy of a page here (blank by default), across the middle, row 3 of 14, inside block 3 (Content: Pages)
  5. Form (fields a person fills in): the page pulldown, then the page's For, Key, Platform, Frame and Rows, across the middle, row 4 of 14, inside block 3 (Content: Pages)
  6. Content (the main reading or working area): the board: the blocks on the frame in the project's colors; drag to move, a corner to size; a child stays in its parent, on the left, columns 1 to 8 of 12, rows 5 to 7 of 14, inside block 3 (Content: Pages)
  7. List (rows of like things): the layers, top first: each block's name; tap to select, up and down to reorder, on the right, columns 9 to 12 of 12, rows 5 to 7 of 14, inside block 3 (Content: Pages)
  8. Form (fields a person fills in): the selected block: Kind, what it's for, Inside (the block it is part of), Remove block; Add block above it, across the middle, row 8 of 14, inside block 3 (Content: Pages)
  9. Card (a box holding one thing): Rules: what holds for this page alone, as PAGE/RULE, the Briefing's list; then Notes and Remove page, across the middle, row 9 of 14, inside block 3 (Content: Pages)
  10. List (rows of like things): Themes: a fold, closed on a new tab; the count and the default's type and corners on the fold; one shown at a time, across the middle, rows 10 to 13 of 14
  11. Form (fields a person fills in): Add theme from blank, a preset's ten colors or a copy of a theme here; Governs; Theme pulldown, the first the default, across the middle, row 10 of 14, inside block 10 (List: Themes)
  12. Form (fields a person fills in): the theme: Name, Mode, Fill from; its Type, Corners, Space and Motion, custom naming a rule of its own; Families, across the middle, row 11 of 14, inside block 10 (List: Themes)
  13. Card (a box holding one thing): Rules: the default theme's are the design's, another's hold for it alone as THEME/RULE; the Briefing's list, across the middle, row 12 of 14, inside block 10 (List: Themes)
  14. List (rows of like things): Colors: each a name, a hex chip and what it is for, added and cut one by one, across the middle, row 13 of 14, inside block 10 (List: Themes)
  15. Footer (the band at the foot): Save and Revert: what was changed is a draft until Save, across the bottom, row 14 of 14
Notes:
  Two folds, Pages and Themes, both closed on a new tab, each showing one entry on its pulldown. The design language is each theme's: the first theme is the default and its type, corners, space, motion, families and rules are the design's; another theme's hold for it alone. A page keeps rules of its own under its board. Adding is inside the fold it adds to: a new page from a platform and a template (Blank, App shell, Dashboard, Landing page, List and detail, Settings for a desktop frame; Mobile app and Mobile feed for a phone's), or a copy of a page here (blocks, layouts, rules and notes), and a new theme blank, from a preset or as a copy of a theme (colors, choices and rules); blank is the default. The board is the width of the view with the layers list beside it, top layer first; a later layer draws over an earlier one, and a block can be inside another, drawn over it and kept within it however either moves, so a card sits in a list and a pill in a bar. The view is passive: no prompt, no Copy, nothing sent to a session; a session reads the design through bb design show and the rules that reach it.

### a notebook: Roadmap (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Roadmap on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: what is on the list, and History, across the middle, row 2 of 8
  3. Form (fields a person fills in): Add an item, and Reorder, across the middle, row 3 of 8
  4. List (rows of like things): the items, each a fold like a bug's row, across the middle, rows 4 to 7 of 8
  5. Card (a box holding one thing): an item's row: the caret level with the words, its number, the words, which open it on a slide; the pencil edits, across the middle, row 4 of 8, inside block 4 (List: the items)
  6. Button (an action to press): the right button group: edit, shelve, done, and Send to Claude with the Claude mark, last, on the right, columns 10 to 12 of 12, row 4 of 8, inside block 5 (Card: an item's row)
  7. List (rows of like things): behind the fold: its steps, a done one struck with a tick where its number was; the next step sends, across the middle, rows 5 to 7 of 8, inside block 4 (List: the items)
  8. Footer (the band at the foot): Save and Revert: what was changed is a draft until Save, across the bottom, row 8 of 8
Notes:
  An item folds like a bug's row (30 Sep): its words open it on the same slide, its buttons act on it, the send button wears the Claude mark and sits last in the right group. A parked item is dim and carries no steps. Finished items are behind their own view, not at the foot of this one.

### a notebook: Bugs (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Bugs on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: how many are open, and History, across the middle, row 2 of 8
  3. Form (fields a person fills in): Report a bug: the title, where it lives, how to reproduce it, the severity, across the middle, row 3 of 8
  4. Search (a search box): the sort bar: by severity, newest, oldest, recently changed or title, across the middle, row 4 of 8
  5. List (rows of like things): the bugs, open first, across the bottom, rows 5 to 8 of 8
  6. Card (a box holding one thing): a bug's row: number, severity as a badge, title; opens on a slide to its fields, notes and what fixed it, across the middle, row 5 of 8, inside block 5 (List: the bugs)
Notes:
  Severity wears the badge palette: the same colors on every scheme.

### a notebook: Git (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Git on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: the branch and how it stands with its host, and Refresh, across the middle, row 2 of 8
  3. Button (an action to press): the network bar: Fetch, Pull and Push, as the project's push rights allow, across the middle, row 3 of 8
  4. List (rows of like things): Changes: what is not committed, each file opening to its diff, and Commit all, across the middle, rows 4 to 5 of 8
  5. List (rows of like things): Branches, and Commits drawn as a graph in lanes, across the bottom, rows 6 to 8 of 8
Notes:
  Reads to a beginner and stays exact for a developer: the host is named (GitHub, Gitea), never 'origin'. Whose working tree it is is said to anybody else, who is offered nothing that changes it.

### a notebook: Artifacts (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Artifacts on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: what the project ships, and Download source, across the middle, row 2 of 8
  3. Card (a box holding one thing): Build: the node it builds on. Version: where the tree is, and the buttons that move it, across the middle, rows 3 to 4 of 8
  4. Text (a block of prose): the dev instance: what it was built from, and whether the tree has moved past it, across the middle, row 5 of 8
  5. List (rows of like things): what is in dist/, divided by hairlines, each a download, across the bottom, rows 6 to 8 of 8
  6. List (rows of like things): Captures apart: each with whose it is and its age, and how long they are kept, across the bottom, row 8 of 8, inside block 5 (List: what is in dist/)
Notes:
  Captures are not what the project ships, so they are listed apart, each saying whose it is, and go by age. Each artifact row ends with a pin, the project row's own tack: lit when pinned, with a pinned tag beside the name and who pinned it on the line under. Dev builds past the newest few of each (the project's Dev builds kept, 3 unless changed, 0 for all) go when the tab draws, and a line over the list says so; a pinned one stays. An .apk or .aab row offers Sign for each key its project has. A signed build wears a signed tag beside its name and, under its provenance, which key signed it, from which build and what verified, then the whole certificate fingerprint, wrapping on a phone, with Copy for F-Droid as a link beside it.

### a notebook: Docker (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Docker on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: this project's containers, and a way to the Docker tab, across the middle, row 2 of 8
  3. List (rows of like things): the project's own containers, each as the Docker tab draws one, across the bottom, rows 3 to 8 of 8
Notes:
  The same rows as the Docker tab, for one project: a second drawing of them would be a second place to be wrong.

### a notebook: Tests (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Tests on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: the last run, and Open the run's output, across the middle, row 2 of 8
  3. Search (a search box): sort and filter: by suite, by what is slow, by what is flagged, across the middle, row 3 of 8
  4. Table (columns of data): the tests, across the bottom, rows 4 to 8 of 8
  5. Card (a box holding one thing): a test's row: suite, name, what it protects, how long it took, whether it is suspect; opens to describe it, across the middle, row 5 of 8, inside block 4 (Table: the tests)
Notes:
  With no run on record the view says how one is made, in one line.

### a notebook: Analysis (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a notebook: Analysis on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Tabs (a strip of tabs switching one area): the views: Briefing, Design, Roadmap, Bugs, Git, Artifacts, Docker, Tests, Analysis, across the top, row 1 of 8
  2. Header (the band at the top): the head row: the scanners' findings for this project, and History, across the middle, row 2 of 8
  3. List (rows of like things): findings by scanner, severity as a badge; one can be sent to the session or dismissed with a reason, across the bottom, rows 3 to 8 of 8
Notes:
  The project's share of the Analysis tab.

### a project's settings (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a project's settings on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): Project settings, the longest dialog, so the one that proves the layout, down the middle, full height, columns 4 to 9 of 12
  2. Header (the band at the top): Project settings: the project's name, in the middle, columns 4 to 9 of 12, row 1 of 8, inside block 1 (Overlay: Project settings)
  3. Form (fields a person fills in): groups headed by a label: name and color, the remote, the node and Also sees, build and test, Claude may, yours here, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8, inside block 1 (Overlay: Project settings)
  4. Footer (the band at the foot): the foot: Unlink and Delete apart from Save; Save lists what takes a restart and asks: end the session now, or keep it, in the middle, columns 4 to 9 of 12, row 8 of 8, inside block 1 (Overlay: Project settings)
Notes:
  In sections, each headed by a label band drawn as a divide (small, dim, uppercase, a rule under it), and a section with no field showing hidden with its heading: The project (name, color, People), the remote (its own door, no heading), Where it runs (node, other nodes, the node's GPU, where tests run), What a session sees (Reads, Also sees), Build and test (commands, outputs, captures kept, dev builds kept), Android signing, Claude may (a change asked for while a test runs, then the permissions: the notebook's four and the wiki, build and test and the container, the two signing ones, reports), Yours on this project, Sessions on this project. Groups headed by a label, every line a field band, one foot. Claude may is ten dials (Write the wiki the newest), each auto, ask or deny, and Write the wiki may also be hidden, which keeps the wiki from a session, reading included. Also sees names the shares on the node a session may see, an allow-list since 29 Sep. During a test run says what a new ask does to a run going: wait for it, or interrupt it. Yours on this project is the person's own: model, effort, replies, questions. A saved change that takes a session restart (the model, the node, what it sees, the test setting) is listed at Save, which asks whether to end the running session now or keep it going (30 Sep). Unlink and Delete project are apart from Save, and each asks once, saying what goes and what stays. The node's GPU, with the Claude settings, says whether the project may compute on its node's NVIDIA card; off runs it as if the machine had none. People names the owner (a picker for the owner and BuilderBot's owner; the owner's pick is an offer, said under the picker, that waits for acceptance and shows with Withdraw) and Invite only, both staged until Save, who is on it, each invitation waiting with Withdraw, and Invite with its account picker, which acts on the press. Signing keys is a block per named key, Default key first, each a row per route (Play upload key, sideload signing key): the alias and fingerprint (made here for a generated key), Upload one or Replace opening its file and password fields, Generate on an empty slot (asking first for a sideload key), Download backup and Remove, and on a sideload row a key picker with Rotate to it; a retired sideload row says it is kept and why and has no Remove, a rotated-to row says who still sees the old key; a name field with New key under them, and Apps, each package with the key it signs with and Remove, then a package field, a key picker and Map it; a sideload key never backed up says so in red under its row.

### a new project (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a new project on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): New project, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
  2. Button (an action to press): the source as one row of buttons: a new repository, a clone, an archive, in the middle, columns 4 to 9 of 12, row 3 of 8, inside block 1 (Overlay: New project)
  3. Form (fields a person fills in): the fields under them, changing with the pick: its name, its node, what Claude may do, in the middle, columns 4 to 9 of 12, rows 4 to 6 of 8, inside block 1 (Overlay: New project)
  4. Footer (the band at the foot): Cancel and Create, the filled button, in the middle, columns 4 to 9 of 12, row 7 of 8, inside block 1 (Overlay: New project)
Notes:
  The three sources are one row of buttons and the fields under them change with the pick. A clone or a link runs as a job the Projects card reports; the dialog does not wait on the network.

### a first session (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a first session on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): First session: the brief typed when the project was made, the model and effort, Build it or Start without it, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
Notes:
  Shown the first time Claude is started on a project that has a brief. Either button takes the brief out of the tree.

### a new container (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of a new container on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): New container: its name, its node and project, and its definition from an image or a compose file, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
Notes:
  The env file's values are never shown back, only its keys.

### waiting for your approval (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of waiting for your approval on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): What a session added under an ask dial: each with Approve and Deny, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
Notes:
  Reached from the bell. A thing approved lands as if the session had been allowed it; a thing denied is said to the session.

### the gear (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of the gear on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): Layout (reset the sidebar's cards), Color scheme (thirteen swatches), Account (Profile), in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
Notes:
  A menu under the gear, not a modal. A swatch applies on the press, the one setting that does: a theme is looked at, not decided. Each swatch is drawn in its own scheme.

### about (Web app)

Platform: a responsive web app: the layout holds at phone and desktop widths, and every tap target is at least 44px on a coarse pointer.
Layout of about on a desktop frame (12 columns by 8 rows), from the Blank template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Overlay (a dialog, sheet, drawer, popover or toast over the page): About: the build, the license, Getting started and Changelog, in the middle, columns 4 to 9 of 12, rows 2 to 7 of 8
Notes:
  The changelog is the same text the welcome panel shows after an update.

### the app: signing in (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: signing in on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): BuilderBot, and what to sign in with, across the middle, rows 4 to 5 of 12
  2. Form (fields a person fills in): the dashboard's address, the account, the password, and Sign in, across the middle, rows 6 to 9 of 12
  3. Text (a block of prose): over http, said before the sign-in: it travels in the clear, across the middle, row 10 of 12
Notes:
  The app wears the dashboard's schemes by the same names and hexes, chosen under More and kept on the device. Text buttons are the accent; a filled button is the deep accent with ink.

### the app: projects (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: projects on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the mark, the account, the build and the host, and Refresh, across the top, row 1 of 12
  2. Card (a box holding one thing): the bell's row: questions waiting and nodes that need attention, a bar down its side, across the middle, rows 2 to 3 of 12
  3. Card (a box holding one thing): the doctor's problems, for an administrator, only when there are any, across the middle, row 4 of 12
  4. Search (a search box): a box to find a project in, once the list is longer than a screen, across the middle, row 5 of 12
  5. List (rows of like things): projects, across the middle, rows 6 to 11 of 12
  6. Card (a box holding one thing): a project: the color down the side, the session as working or waiting on you, what is waiting, across the middle, row 7 of 12, inside block 5 (List: projects)
  7. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  The question a phone is picked up to ask is whether it is done, so the list answers it before anything is opened. Pull down to read again, on every list.

### the app: a project (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: a project on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): the project, its color, and its session as a pill: working, or waiting on you, across the top, row 1 of 12
  2. Tabs (a strip of tabs switching one area): the view strip, scrolling sideways: Claude first, then the notebook's views, Git, Settings, across the middle, row 2 of 12
  3. Form (fields a person fills in): Claude: what the session is doing, and a box to say a line to it, across the middle, rows 3 to 5 of 12
  4. List (rows of like things): your conversations here, each with Read the end and Share, across the middle, rows 6 to 11 of 12
  5. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  A project opens on Claude. The terminals stay the browser's; a line said here goes into the account's own session and nowhere else. Design is read here, not edited. Docker's Start, Stop and Rebuild each ask before they act. Settings are a draft until Save.

### the app: approvals (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: approvals on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): Approvals, and Refresh, across the top, row 1 of 12
  2. List (rows of like things): what waits on your answer: the ask, its reason, its command, Deny and Allow, across the middle, rows 2 to 6 of 12
  3. List (rows of like things): changes a session has waiting, by project, each with Deny and Approve, across the middle, rows 7 to 11 of 12
  4. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  Root on a node wears red down its side and everything else amber. The same asks arrive as notifications with Approve and Deny on them, which need the phone unlocked.

### the app: nodes (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: nodes on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): Nodes, and Refresh, across the top, row 1 of 12
  2. List (rows of like things): nodes: live or not down the side, what the machine is, Lock system changes and Drain, across the middle, rows 2 to 11 of 12
  3. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  An administrator's. Enrolling and the node's sections stay the dashboard's.

### the app: more (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: more on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): More, across the top, row 1 of 12
  2. Card (a box holding one thing): whether the app and the dashboard are on the same API, and Install it when the app is behind, across the middle, rows 2 to 3 of 12
  3. List (rows of like things): the other pages as rows: Profile, Tools, Jobs, Users, What's new, across the middle, rows 4 to 6 of 12
  4. Form (fields a person fills in): The watch: questions, Tell me when Claude can take a message, how often to ask; one Save, across the middle, rows 7 to 9 of 12
  5. List (rows of like things): Colors: the thirteen schemes, each drawn in its own; About; Sign out, across the middle, rows 10 to 11 of 12
  6. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  The watch's settings are a draft until Save. The note that Claude is waiting on you names the project first and follows the project's During a test run setting: at once where a new ask interrupts a run, and when the tests finish where it waits for them (30 Sep). The scheme applies on the press, as it does on the dashboard.

### the app: tools (Android app)

Platform: an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections as a bottom bar, and the system's back gesture respected.
Layout of the app: tools on a phone frame (6 columns by 12 rows), from the Mobile app template, numbered in drawing order (a later block draws over an earlier one where they overlap):
  1. Header (the band at the top): Tools, and Refresh, across the top, row 1 of 12
  2. Tabs (a strip of tabs switching one area): the nodes, as chips; never the controller, across the middle, row 2 of 12
  3. Text (a block of prose): the store's path on that node, across the middle, row 3 of 12
  4. List (rows of like things): toolchains: what each is, its version or not installed, Install or Remove for an administrator, across the middle, rows 4 to 11 of 12
  5. Navigation (the way around: tabs or a menu): the bottom bar: Projects, Approvals, Nodes (an administrator), More, across the bottom, row 12 of 12
Notes:
  Install and Remove ask first, saying the size. Android system images are not here: choosing one wants the room the dashboard's tab has.
