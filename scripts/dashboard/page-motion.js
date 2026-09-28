// Motion: the one reduced-motion gate, the FLIP for both reorder surfaces,
// and every height tween on the page (a card, a <details>, a box under a
// row, a block that is shown and hidden). Height is real layout, so what is
// below rides along frame by frame instead of jumping, which is the whole
// vocabulary; docs/design-language.md, Motion.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load. The modals are armed and the Tools
// icons put on from index.html, under the motion header.

"use strict";

const noMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Every modal leaves the way it arrived. Closing one is `hidden = true` at a
// dozen sites, and any dialog added later closes the same way, so the leaving
// lives on the property itself: `hidden` on a modal is its own accessor, and
// setting it plays the tween first and puts the attribute on when the tween
// ends. Nothing at a call site to remember, and nothing for a watcher to
// misread: a hide of a modal already hidden is a hide, a show mid-leave
// drops the tween and shows. (An observer on the attribute did this first,
// and re-showing the element to play the tween was what every other test
// on the page tripped over.)
function armModal(el){
  if (!el || el.__modalArmed) return;
  el.__modalArmed = true;
  Object.defineProperty(el, "hidden", {
    configurable: true,
    // Hidden the moment it is told to, to everything that asks: the poll
    // and the cards read a dialog's state to decide what to repaint, and a
    // dialog that read as open for the length of its tween had them draw
    // the page as if it were. Only the pixels linger.
    get(){ return this.hasAttribute("hidden") || this.classList.contains("leaving"); },
    set(v){
      if (!v){
        this.getAnimations().forEach(a => a.cancel());
        this.querySelector(":scope > .box")?.getAnimations().forEach(a => a.cancel());
        this.classList.remove("leaving");
        this.removeAttribute("hidden");
        return;
      }
      if (this.hasAttribute("hidden") || this.classList.contains("leaving")) return;
      if (noMotion()){ this.setAttribute("hidden", ""); return; }
      this.classList.add("leaving");
      this.querySelector(":scope > .box")?.animate(
        [{opacity: 1, transform: "none"}, {opacity: 0, transform: "translateY(6px) scale(.985)"}],
        {duration: 150, easing: "ease"});
      this.animate([{opacity: 1}, {opacity: 0}], {duration: 150, easing: "ease"}).finished.then(
        () => { if (this.classList.contains("leaving")){ this.classList.remove("leaving"); this.setAttribute("hidden", ""); } },
        () => {});                        // cancelled: it was shown again, and stays
    }});
}

function flip(els, key){
  if (noMotion()) return () => {};
  const before = new Map([...els()].map(el => [key(el), el.getBoundingClientRect()]));
  return () => [...els()].forEach(el => {
    const a = before.get(key(el));
    if (!a) return;
    const b = el.getBoundingClientRect();
    const dx = a.left - b.left, dy = a.top - b.top;
    if (dx || dy)
      el.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: "none"}],
                 {duration: 140, easing: "ease"});
  });
}

// The same fold, on a <details> and on a plain hidden block: the memories,
// the bug reports, and a roadmap row's details. A <details> snaps open by
// construction and a [hidden] block appears with no in-between, so both are
// driven here instead: measure, flip the state, measure again, and tween
// between the two real heights. Height is real layout, so everything below
// rides along frame by frame rather than jumping, which is the whole reason
// the cards do it this way.
function foldHeight(el, from, to, done){
  // Only its own kind, so a fold inside a card cannot swallow the class write
  // the card-level fold's finish handler is going to make.
  el.getAnimations().forEach(a => { if (a.id === "fold") a.cancel(); });
  el.style.overflow = "hidden";
  const anim = el.animate([{height: from + "px"}, {height: to + "px"}],
                          {duration: 180, easing: "ease"});
  anim.id = "fold";
  const settle = () => { el.style.overflow = ""; el.style.height = ""; };
  anim.onfinish = () => { done(); settle(); };
  // Canceled by a newer fold: that one owns the element now, and it measured
  // its own starting height from wherever this one had got to.
  anim.oncancel = settle;
}

// The fold is a height tween between the card's two real sizes, with the
// class flipped at whichever end keeps the body visible while it moves,
// on open before the tween, on close after it. Height is real layout, so
// the cards below ride along frame by frame instead of jumping.
function slideCard(el, closing){
  if (noMotion()){ el.classList.toggle("closed", closing); return; }
  if (getComputedStyle(el).getPropertyValue("--fold").trim() === "fade"){
    fadeFoldCard(el, closing); return;
  }
  // Any entrance animation inside this card ends here. contentIn starts at
  // opacity 0 and runs 180ms (the same as the fold), so a body repainted in
  // the moment before a click spent the whole collapse invisible, and the card
  // looked like it blanked before it shut. Runner and Projects are the two
  // whose bodies redraw from the poll, which is why they were the two that
  // flickered. Removing the class ends the animation outright; the content is
  // already there and the fold is the motion that matters now.
  el.querySelectorAll(".justpainted").forEach(n => n.classList.remove("justpainted"));
  const from = el.offsetHeight;         // current frame, if one is mid-tween
  // A second click mid-tween reverses from wherever the card is now; the old
  // animation is canceled un-finished so its class write never lands.
  el.getAnimations().forEach(a => a.cancel());
  el.classList.toggle("closed", closing);
  const to = el.offsetHeight;
  if (closing) el.classList.remove("closed");
  el.style.overflow = "hidden";
  const anim = el.animate([{height: from + "px"}, {height: to + "px"}],
                          {duration: 180, easing: "ease"});
  anim.onfinish = () => {
    if (closing) el.classList.add("closed");
    el.style.overflow = "";
  };
}

// The fold a scheme asks for with `--fold: fade` on the card (nostromo):
// the body fades out where it stands and THEN the gap closes, and on open the
// gap opens first and the body fades in. Two phases because the body never
// slides: the smoked glass sliding up into the title bar read as a glitch
// (first seen with the decal the card's corner used to carry), and a fade
// leaves the card where it is until it is gone.
// The cards below still ride on the height tween, the same as the plain fold.
// A second click mid-way cancels whatever phase is running, in the subtree
// too. A cancelled fold's clean-up runs a microtask AFTER the newer fold has
// set its own state, so it clears only while it still owns the card (the
// token), or a re-open would run its gap phase with the body showing.
// `fading` on the card is for the stylesheet: it clears the card's own fill
// and frame on the class while the body is out.
function fadeFoldCard(el, closing){
  el.querySelectorAll(".justpainted").forEach(n => n.classList.remove("justpainted"));
  const body = [...el.children].filter(n => n.tagName !== "H2");
  const from = el.offsetHeight;
  el.getAnimations({subtree: true}).forEach(a => a.cancel());
  const token = el.fold = {};
  // Before the measuring flip: the mark's fade is a transition, and a class
  // that lands after a style flush is a second transition, back the way
  // it came.
  el.classList.add("fading");
  el.classList.toggle("closed", closing);
  const to = el.offsetHeight;
  if (closing) el.classList.remove("closed");
  const dim = v => body.forEach(n => { n.style.opacity = v; });
  const clear = () => {
    if (el.fold !== token) return;
    el.style.overflow = ""; dim(""); el.classList.remove("fading");
  };
  const fade = (a, b) => {
    const runs = body.map(n => n.animate([{opacity: a}, {opacity: b}], {duration: 120, easing: "ease"}));
    return Promise.all(runs.map(r => r.finished));
  };
  const gap = () => {
    el.style.overflow = "hidden";
    const anim = el.animate([{height: from + "px"}, {height: to + "px"}], {duration: 180, easing: "ease"});
    return anim.finished;
  };
  const run = closing
    ? fade(1, 0).then(() => { dim(0); return gap(); }).then(() => { el.classList.add("closed"); clear(); })
    : (dim(0), gap()).then(() => { dim(""); el.classList.remove("fading"); return fade(0, 1); }).then(clear);
  // A cancel rejects `finished`: the newer fold owns the card now, and only
  // the inline styles this one wrote are put back.
  run.catch(clear);
}

// A <details>, which has to be open while it shrinks or there is nothing to
// see moving, so the flag is set true for the tween and written for real at
// the end, whichever direction it went.
function slideDetails(el, willOpen){
  const sum = el.querySelector("summary");
  if (!sum || noMotion()){ el.open = willOpen; return; }
  const from = el.offsetHeight;
  el.open = true;
  const to = willOpen ? el.offsetHeight : sum.offsetHeight;
  if (from === to){ el.open = willOpen; return; }
  foldHeight(el, from, to, () => { el.open = willOpen; });
}

// A plain block that is shown and hidden. Same tween, collapsed height zero.
// One arrival for every box that opens under a row: the send box, a reword,
// a delete confirm, the bug tracker's two. They unroll from nothing on the
// same height tween the folds use, so the lines below ride down instead of
// jumping out of the way. Height rather than opacity, because those lines
// have to move either way and moving them smoothly is the whole point.
function arriveBox(el){
  proselines(el);
  if (noMotion() || !el) return;
  foldHeight(el, 0, el.offsetHeight, () => {});
}

// A box whose CONTENTS are replaced: the memory writer and the bug reporter,
// each a one-line link that becomes a form and goes back to a link. Not
// arriveBox: that unrolls from nothing, and these start at the height of the
// link they are replacing, so the tween runs between the two real sizes the
// same way every other fold here does. Paint first, measure after: the form
// has no height until it is in the document.
function swapBox(el, paint){
  if (!el){ paint(); return; }
  if (noMotion()){ paint(); return; }
  // Where it is NOW, which mid-tween is a pinned px height rather than the
  // natural one: measured before the cancel below, exactly as the card fold
  // does it. Reopening a box while it was still rolling up otherwise measured
  // that pinned height twice, read from === to, and swapped with no motion at
  // all: the second click in a row was the one that looked broken.
  const from = el.offsetHeight;
  el.getAnimations().forEach(a => { if (a.id === "fold") a.cancel(); });
  paint();
  const to = el.offsetHeight;
  if (from === to) return;
  foldHeight(el, from, to, () => {});
}

function slideHidden(el, willShow, after){
  const done = () => { el.hidden = !willShow; after?.(); };
  if (noMotion()){ done(); return; }
  el.hidden = false;
  const full = el.offsetHeight;
  foldHeight(el, willShow ? 0 : full, willShow ? full : 0,
             () => { el.hidden = !willShow; after?.(); });
}

// Grow or shrink a card around what a control just changed inside it: the
// projects error toggle, the commands cut-off, doctor's detail, with the
// same height tween as the card-level fold. `mutate` does the actual redraw.
function slideBody(el, mutate){
  // The card or panel hosting it, whose height is what moves; a row in a
  // tab has no card and slides over its own height.
  const card = el.closest(".card, .mpanel") || el;
  if (noMotion()){ mutate(); return; }
  const from = card.offsetHeight;
  // Only its own kind: canceling a card-level fold here would swallow the
  // class write that fold's finish handler was going to make.
  card.getAnimations().forEach(a => { if (a.id === "body") a.cancel(); });
  mutate();
  const to = card.offsetHeight;
  if (from === to) return;
  card.style.overflow = "hidden";
  const anim = card.animate([{height: from + "px"}, {height: to + "px"}],
                            {duration: 180, easing: "ease"});
  anim.id = "body";
  anim.onfinish = () => card.style.overflow = "";
}
