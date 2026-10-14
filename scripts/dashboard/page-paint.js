// paint(): replace a surface's markup only when it changed, the one way
// every list on this page is redrawn on the poll; and newShell(), a terminal
// opened in the dock. What was the tab strip around them (its drag, its
// picker, its arrows and pin menu) went with R218 step 4: terminals are the
// dock's line (page-dock.js) and every other tab is a page on the rail.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

// The click that ends a card's drag is not a press on its header
// (page-cards.js): set by the drag, read by the header's handler.
let swallowClick = false;

// Rebuild-if-changed, for every list this page redraws on the poll. The poll
// is every fifteen seconds and nearly always says the same thing; replacing
// identical markup anyway dropped :hover under a resting pointer, reset a
// link mid-"updating…", and made every card blink for nothing. Markup is
// compared as a string (cheap, since it was just built) and only a
// difference touches the DOM. Returns whether it did, for the callers that
// bind handlers or animate only on a real change.
const painted = new WeakMap();
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
function paint(el, html){
  const was = painted.get(el);
  if (was === html) return false;
  // Not recorded, so the same markup is still a change on the next poll.
  if (menuHolds(el)) return false;
  const arriving = was === undefined || WAITING.test(was);
  painted.set(el, html);
  el.innerHTML = html;
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
  if (arriving && !folding && !WAITING.test(html) && !noMotion()){
    // Restarted rather than added-once: an element can arrive more than once
    // in a session, and a class already on it would not replay.
    el.classList.remove("justpainted");
    void el.offsetWidth;
    el.classList.add("justpainted");
  }
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
  openTab({kind:"term", arg, label: `sh: ${proj || "workspace"}${here ? " (here)" : ""}`, here});
}
