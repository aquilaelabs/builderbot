// Icons drawn inline as SVG: a row's gear and its folded controls, the
// lock, the link, the spark, the terminal and the book. Stroked at one
// weight, so the controls on a row read as one set.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- icons: the row's gear, and its folded controls ---------------------

// The project row's own button. It stopped being a pencil when the dialog
// stopped being only a rename: it holds the credential switch and what Claude
// runs on, and a pencil promises editing one thing. Drawn stroked at the same
// 1.4 weight as its neighbours: an eight-toothed ring and a hub, which is the
// only gear shape that stays legible at 16px.
// The rest of a row's controls, folded on a phone. An icon rather than a
// typed ellipsis: every other control in that cluster is one, and a cluster
// with text in it stops being an icon cluster, which is a real rule here,
// not a nicety (uniform.mjs reads a set of TEXT buttons as an action bar and
// holds it to a bar's shape).
const DOTS = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <circle cx="3.2" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/>
  <circle cx="12.8" cy="8" r="1.3"/></svg>`;

const GEAR = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M6.6 1.9h2.8l.35 1.72 1.2.7 1.66-.57 1.4 2.42-1.3 1.16v1.4l1.3 1.16-1.4 2.42-1.66-.57-1.2.7-.35 1.72H6.6l-.35-1.72-1.2-.7-1.66.57-1.4-2.42 1.3-1.16v-1.4L1.99 6.17l1.4-2.42 1.66.57 1.2-.7z"/>
  <circle cx="8" cy="8" r="2.1"/></svg>`;

// ---- icons: lock, link, spark, terminal and book ------------------------

// A padlock, for a project the operator keeps and runs themselves. Only the
// shackle differs between the two states (the body stays put), so which one
// a row is wearing reads at a glance without comparing it to its neighbours.
// A padlock with a wide shackle and a keyhole: at 16px the old narrow
// shackle over a low body read as another list icon beside the notebook's
// ticks (R58), and the keyhole is the one mark no list has.
const LOCK_BODY = `<rect x="2.9" y="7.2" width="10.2" height="6.4" rx="1.4"/>
  <path d="M8 9.6v1.9"/>`;
const LOCK = `<svg viewBox="0 0 16 16" aria-hidden="true">${LOCK_BODY}
  <path d="M5 7.2V4.9a3 3 0 0 1 6 0v2.3"/></svg>`;
const LOCK_OPEN = `<svg viewBox="0 0 16 16" aria-hidden="true">${LOCK_BODY}
  <path d="M5 7.2V4.9a3 3 0 0 1 6 0"/></svg>`;

// A chain link: the remote, on every repository: the link form for one that
// has none, and the credential and Unlink for one that has.
const LINK = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M6.7 9.3 9.3 6.7"/>
  <path d="M7.5 4.9 9.2 3.2a2.6 2.6 0 0 1 3.6 3.6L11.1 8.5"/>
  <path d="M8.5 11.1 6.8 12.8a2.6 2.6 0 0 1-3.6-3.6L4.9 7.5"/></svg>`;

// Claude's asterisk, for starting or returning to a session. Eight strokes
// rather than the filled four-pointed spark: at 16px a fill reads as a blob,
// and every other icon on this row is a stroke.
const SPARK = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M8 2.3v11.4"/><path d="M2.3 8h11.4"/>
  <path d="M4 4l8 8"/><path d="M12 4l-8 8"/></svg>`;

// A prompt, for a plain terminal: the chevron and the line you type on.
const TERM = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M3.2 4.6 6.6 8l-3.4 3.4"/><path d="M8.4 11.8h4.4"/></svg>`;

// A ticked list, for the project's to-do. The panel behind it also holds what
// Claude remembers here, folded away, but the number worth putting on a row
// is how much is still to do, not how many memories exist.
// The notebook's book, the same on the row's button and its tab.
const BOOK = TOOL_ICONS.notebook;
