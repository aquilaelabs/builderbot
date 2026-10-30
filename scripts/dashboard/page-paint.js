// paint(): replace a surface's markup only when it changed, the one way
// every list on this page is redrawn on the poll; and newShell(), a terminal
// opened in the dock. What was the tab strip around them (its drag, its
// picker, its arrows and pin menu) went with R218 step 4: terminals are the
// dock's line (page-dock.js) and every other tab is a page on the rail.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

// Rebuild-if-changed, for every list this page redraws on the poll. The poll
// is every fifteen seconds and nearly always says the same thing; replacing
// identical markup anyway dropped :hover under a resting pointer, reset a
// link mid-"updating…", and made every card blink for nothing. Markup is
// compared as a string (cheap, since it was just built) and only a
// difference touches the DOM. Returns whether it did, for the callers that
// bind handlers or animate only on a real change.
const painted = new WeakMap();

// The same rule for the frame's small writes (R218 step 10): a text, an
// attribute, a whole class list or a hidden flag set only when it differs.
// Written unconditionally, each status poll rewrote the header's words, the
// doctor's dot, the dock's and the panes' classes and the phone bar's flags
// with what they already said, two hundred changes a poll that were none.
function setText(el, s){ if (el && el.textContent !== String(s)) el.textContent = String(s); }
function setAttr(el, name, v){
  if (!el) return;
  if (v === null || v === undefined || v === false){ if (el.hasAttribute(name)) el.removeAttribute(name); }
  else if (el.getAttribute(name) !== String(v)) el.setAttribute(name, String(v));
}
function setClass(el, cls){ if (el && el.className !== cls) el.className = cls; }
function setHidden(el, off){ if (el && el.hidden !== !!off) el.hidden = !!off; }
function setDisabled(el, off){ if (el && el.disabled !== !!off) el.disabled = !!off; }
// A title is taken off by untitle() and kept for a screen reader as the
// element's description or name, so it is compared against what was kept.
function setTitle(el, s){ if (el && saidOf(el) !== String(s)) el.title = String(s); }
// Every redraw on the page goes through here, which is what makes it the one
// place worth teaching about arriving. It already skips the write when
// nothing changed; that is what keeps :hover alive and stops a mid-edit
// field being wiped by a poll, and now the FIRST real content fades in.
//
// First only, deliberately. Fading on every change would flicker a list every
// time a poll moved one word in it, which is worse than not animating at all.
// "First" means: nothing has been painted here yet, or what was here was a
// placeholder saying it had not arrived.
const WAITING = /class="(loading|empty)[ "]|loading…/;
const paintedKids = el => { let n = el.childNodes.length;
  for (const c of el.children) if (c.classList.contains("slmark")) n--;
  return n; };
function paint(el, html, quiet = false){
  const rec = painted.get(el);
  // What it left there is what is there: a renderer that wrote the element
  // directly in between (a "loading…", an error) replaced its children, and
  // the same markup painted again is then a change (R218 step 10, now that a
  // page's list outlives its draws). A fold opened or a box ticked since
  // replaces nothing and still reads as unchanged.
  // ...counting the children it wrote: a slide marker (slideMark) put in
  // beside them is the motion's, not a write that makes the markup stale.
  const was = rec && rec.first === el.firstChild && rec.n === paintedKids(el) ? rec.html : undefined;
  // ...unless a button in it was marked busy since (busy(): "Asking..."):
  // the press rewrote it in place, and the same markup painted again is what
  // takes the mark off. Skipped, Measure now said Asking until a reload (the
  // operator, 23 Oct).
  // A mark the markup carries itself (Abort's Stopping) is not a press's.
  if (rec && was === html && (html.includes('aria-busy="true"') || !el.querySelector('[aria-busy="true"]'))) return false;
  // Not recorded, so the same markup is still a change on the next poll.
  if (menuHolds(el)) return false;
  const arriving = !rec || WAITING.test(rec.html);
  el.innerHTML = html;
  painted.set(el, {html, first: el.firstChild, n: paintedKids(el)});
  // ...but never while the card around it is folding. contentIn starts at
  // opacity 0 and takes 180ms, which is exactly the fold's duration, so a
  // repaint landing on a collapsing card blanks its body at full height and
  // fades it back in as the card shuts. That is the flicker on Runner and
  // Projects and not the other cards: those two are the ones whose bodies
  // redraw from the poll, so they are the ones a fold can collide with.
  //
  // Suppressed rather than delayed. The animation exists to make arriving
  // content feel like it arrived; content arriving into something on its way
  // shut has nowhere to arrive, and the fold is the motion that matters.
  const folding = el.closest(".card")?.getAnimations().length > 0;
  // `quiet` is the frame's own (the rail, a page's bar and foot): chrome is
  // there, it does not arrive.
  if (arriving && !quiet && !folding && !WAITING.test(html) && !noMotion()){
    // Restarted rather than added-once: an element can arrive more than once
    // in a session, and a class already on it would not replay.
    el.classList.remove("justpainted");
    void el.offsetWidth;
    el.classList.add("justpainted");
  }
  return true;
}

// A change a press already made in place (a card turned over: its class and
// its faces' inert) written into what paint() remembers, so the next paint
// of the same markup is no change and the element is left alone. Replacing
// it instead, as the turn ends, flashed the card in Firefox (the operator,
// 29 Oct). Only where the record still holds `from`, so a poll's change
// since is still drawn.
function paintAdopt(el, from, to){
  const rec = painted.get(el);
  if (!rec || rec.first !== el.firstChild || rec.n !== paintedKids(el) || from === to || !rec.html.includes(from)) return false;
  rec.html = rec.html.replace(from, to);
  return true;
}

// A terminal at some directory, always a new one. "" is the workspace root.
function newShell(proj){
  if (!mayShell()){ notify("a shell is an administrator's", true); return; }
  const arg = nextShell(proj);
  if (!arg){ notify("Too many terminals open for that directory.", true); return; }
  // A shell on a project whose node cannot take one opens on this container
  // and says so: a shell is where the node gets looked at, and a JSON error
  // in the frame was what the operator got instead of one. Only when a NODE
  // refused, which is what session_at names: a project with no node has
  // always had its shell here, and announcing that would be news about
  // nothing.
  const pr = (state?.projects || []).find(p => p.name === proj);
  const here = !!(pr?.session_why && pr?.session_at);
  if (here) notify(`${projLabel(proj)}'s node cannot take a session now; this shell is on the controller`);
  openTab({kind:"term", arg, label: `sh: ${proj ? projLabel(proj) : "workspace"}${here ? " (here)" : ""}`, here});
}
