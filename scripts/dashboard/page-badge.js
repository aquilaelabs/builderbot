// Saying so when nobody is looking at the page: the browser tab's title
// and icon carry a count of what waits, and the ages on the page are
// written coarsely enough that they need no redraw every second.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- saying so when nobody is looking at the page --------------------------

// A request waits five minutes and then gives up, which is no use at all if
// it arrives while the tab is in the background, and that is the normal
// case, not the exception. So the tab itself carries the count: the title,
// which a browser shows in the tab strip, and the favicon, which is what is
// left when the strip is too crowded for text.
//
// This is as far as a page can go without asking for notification permission,
// which is a decision about the operator's browser rather than about this
// dashboard, and not one to take on their behalf.
const BASE_TITLE = document.title;
let badgeOn = null;

function setBadge(n){
  if (badgeOn === n) return;                    // no needless DOM churn
  badgeOn = n;
  document.title = n ? `(${n}) ${BASE_TITLE}` : BASE_TITLE;
  if (!ICON) return;
  // The same robot with a dot in the corner, drawn into the icon that is
  // already there rather than swapped for a second asset: one icon to keep
  // in step instead of two that can drift.
  ICON.setAttribute("href", n
    ? ICON_BASE.replace("%3C/svg%3E",
        "%3Ccircle cx='25.5' cy='6.5' r='6' fill='%23f0883e'"
        + " stroke='%231b2027' stroke-width='2'/%3E%3C/svg%3E")
    : ICON_BASE);
}

// Findings opens as a document tab, not a terminal; it is a report to read,
// and piping it through a PTY would only make it harder to.
// The card's per-project headline: which project, how many, how bad, so
// "is anything on fire, and whose" is answered without opening the report.
// Same level pills the report itself leads with; "" is the scanner seeing a
// directory this workspace does not mount, shown rather than hidden because
// a finding with a bad path is still a finding.
// Coarser than dur(), which is the uptime clock: a report's age wants one
// unit. "17m 25s ago" reads as a stopwatch and "94h 54m behind" reads as
// arithmetic homework, where what is being said is "this morning" and "four
// days". Mirrors ago() in bb's cmd_findings, which says the same words in the
// other language: the tmuxName situation, and the same answer: state the rule
// twice and keep them together in the mind.
const coarse = s =>
  s < 90     ? `${Math.round(s)}s` :
  s < 5400   ? `${Math.round(s / 60)}m` :
  s < 172800 ? `${Math.round(s / 3600)}h`
             : `${Math.round(s / 86400)}d`;

// When the reports were written, and which of them are not being counted.
// A scanner that dies leaves its PREVIOUS report in place: a host script
// worth having does not overwrite a good report with nothing, so one a whole
// cycle behind is left out of the counts and this line says so: a number that
// dropped with nothing to explain it is the same problem wearing the other
// face.
function reportAges(){
  const rs = state?.reports_ages || [];
  if (!rs.length) return "";
  const newest = rs[0].when, now = Date.now() / 1000;
  const out = rs.filter(r => r.stale);
  // Content only: the caller's footer slot owns the .fnote band, and a band
  // inside a band would inset twice, which is the exact drift §the scaffold
  // exists to end.
  return `scanned ${
    esc(coarse(Math.max(0, now - newest)))} ago${
    out.map(r => `<br><span class="warn">${esc(r.name)} left out: ${
      esc(coarse(r.behind))} behind, its scanner may have failed</span>`).join("")}`;
}
