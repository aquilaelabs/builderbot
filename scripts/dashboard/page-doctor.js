// The doctor: bb doctor's verdict, run by the server on a slow loop and on
// the ↻ button, behind a dot in the top bar after the bell (R218 step 3).
// The dot wears the worst check's color; its panel lists failures and
// warnings as full lines (they are for reading) and passing checks as chips.
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. The dot and ↻ are wired from
// index.html, under the doctor header.

"use strict";

let docShown = false;

function drawDoctor(){
  const el = $("doctor"), d = state?.doctor;
  const dot = $("docDot");
  setText($("docWhen"), d?.running ? "running…" : d?.when ? ago(d.when) : "");
  if (!d || !d.when){
    setClass(dot, "st");
    setAttr($("bDocDot"), "aria-label", "bb doctor: no verdict yet");
    paint(el, `<div class="empty">${d?.running ? "running…" : "first run pending…"}</div>`);
    return;
  }
  const tip = c => c.text + (c.detail ? "\n\n" + c.detail : "");
  // A plain user sees the lines that are theirs to act on: whether a node
  // can run their session. Runner tokens, ssh keys and the docker daemon
  // are the controller's, and in their panel they read as things to fix.
  const checks = state?.admin === false
    ? d.checks.filter(c => /can run a session/.test(c.text)) : d.checks;
  const probs = checks.filter(c => c.level === "FAIL" || c.level === "warn");
  const fine = checks.filter(c => c.level === "ok");
  const skip = checks.filter(c => c.level === "skip");

  const level = probs.some(c => c.level === "FAIL") ? "bad"
              : probs.length ? "warn" : "ok";
  setClass(dot, "st " + level);
  setAttr($("bDocDot"), "aria-label", level === "ok" ? `bb doctor: all ${fine.length} ok`
    : `bb doctor: ${probs.length} to look at`);
  paint(el,
    `<div class="probs">${probs.map(c =>
       `<div class="sub ${c.level === "FAIL" ? "bad" : "warn"}" title="${esc(tip(c))}">${esc(c.text)}${
          c.detail ? `<span class="why">${esc(c.detail)}</span>` : ""}</div>`
     ).join("")}</div>` +
    `<div class="chips">${
       fine.map(c => `<span class="pill ok" title="${esc(tip(c))}">${esc(c.text)}</span>`).join("") +
       skip.map(c => `<span class="pill" title="${esc(tip(c))}">${esc(c.text)}</span>`).join("")
     }</div>`);
}

// Open or shut the panel, with the bell's manners: anything else closes it,
// Escape closes it (wired in index.html).
function toggleDoctor(open){
  docShown = open === undefined ? !docShown : open;
  $("bDocDot").setAttribute("aria-expanded", String(docShown));
  $("docPanel").hidden = !docShown;
  if (docShown) drawDoctor();
}
