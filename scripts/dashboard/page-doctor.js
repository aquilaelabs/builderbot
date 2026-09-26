// The doctor card: bb doctor's verdict, run by the server on a slow loop and
// on the refresh button. Failures and warnings are full lines (they are for
// reading) while passing checks collapse into chips.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load. Its two buttons are wired from
// index.html, under the doctor header.

"use strict";

let docOpen  = null;   // the operator's toggle; null = follow the verdict

let docLevel = null;   // last verdict, so a change can override that toggle

function drawDoctor(){
  const el = $("doctor"), d = state?.doctor;
  const dot = $("docDot"), tog = $("bDocTog");
  $("docWhen").textContent = d?.running ? "running…" : d?.when ? ago(d.when) : "";
  if (!d || !d.when){
    dot.hidden = tog.hidden = true;             // no verdict yet, nothing to fold
    el.hidden = false;
    paint(el, `<div class="empty">${d?.running ? "running…" : "first run pending…"}</div>`);
    return;
  }
  const tip = c => c.text + (c.detail ? "\n\n" + c.detail : "");
  // A plain user sees the lines that are theirs to act on: whether a node
  // can run their session. Runner tokens, ssh keys and the docker daemon
  // are the controller's, and on their card they read as things to fix.
  const checks = state?.admin === false
    ? d.checks.filter(c => /can run a session/.test(c.text)) : d.checks;
  const probs = checks.filter(c => c.level === "FAIL" || c.level === "warn");
  const fine = checks.filter(c => c.level === "ok");
  const skip = checks.filter(c => c.level === "skip");

  // A changed verdict beats the operator's inner toggle: detail that turns
  // red must open even if it was folded away green an hour ago, and detail
  // that heals folds itself back up rather than squatting on space it no
  // longer earns. Only the detail: a collapsed *card* stays collapsed.
  const level = probs.some(c => c.level === "FAIL") ? "bad"
              : probs.length ? "warn" : "ok";
  if (level !== docLevel){ docLevel = level; docOpen = null; }
  const open = docOpen ?? (level !== "ok");
  dot.hidden = false;
  dot.className = "st " + level;
  tog.hidden = false;
  tog.textContent = open ? "Hide"
                  : level === "ok" ? `all ${fine.length} ok`
                  : `Show (${probs.length})`;
  el.hidden = !open;
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
