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
        const was = this.hasAttribute("hidden") || this.classList.contains("leaving");
        this.getAnimations().forEach(a => a.cancel());
        this.querySelector(":scope > .box")?.getAnimations().forEach(a => a.cancel());
        this.classList.remove("leaving");
        this.removeAttribute("hidden");
        // A dialog opens at its top: the box kept where it was last scrolled
        // to, and a field focused on the way in scrolled it further, so one
        // opened on a phone could start halfway down (the operator, 30 Sep).
        // Again after the frame, for what the opener fills and focuses.
        if (was){ modalTop(this); modalOpened(this); requestAnimationFrame(() => { modalTop(this); scrollHints(this); }); }
        return;
      }
      if (this.hasAttribute("hidden") || this.classList.contains("leaving")) return;
      modalClosed(this);
      if (noMotion()){ this.setAttribute("hidden", ""); return; }
      this.classList.add("leaving");
      this.querySelector(":scope > .box")?.animate(
        [{opacity: 1, transform: "none"}, {opacity: 0, transform: "translateY(6px) scale(.985)"}],
        {duration: 150, easing: "ease"});
      this.animate([{opacity: 1}, {opacity: 0}], {duration: 150, easing: "ease"}).finished.then(
        () => { if (this.classList.contains("leaving")){ this.classList.remove("leaving"); this.setAttribute("hidden", ""); } },
        () => {});                        // canceled: it was shown again, and stays
    }});
}

// ---- a dialog and the keyboard ------------------------------------------
// One place for what every dialog does with the keyboard (R88), rather than
// an Escape listener per dialog, which seven of the sixteen had: it takes
// the focus as it opens, so a screen reader starts in it and Tab starts
// from it; Tab and Shift+Tab go round inside it rather than out to the page
// behind; Escape closes it, as the design says every dialog's foot does;
// and the focus goes back to what opened it. The stack is the order they
// opened in, so Escape closes the one on top.
const openModals = [];

function topModal(){
  for (let i = openModals.length - 1; i >= 0; i--){
    const m = openModals[i];
    if (!m.isConnected || m.hidden){ openModals.splice(i, 1); continue; }
    // A notebook's reading room in a tab that is not showing is open but
    // not on screen, and not the one a key is meant for.
    if (m.getClientRects().length) return m;
  }
  return null;
}

function modalOpened(el){
  const i = openModals.indexOf(el);
  if (i >= 0) openModals.splice(i, 1);
  openModals.push(el);
  const a = document.activeElement;
  el.__opener = a && a !== document.body && !el.contains(a) ? a : null;
  // A dialog is named by its title for a screen reader, which the markup
  // says by aria-labelledby; one made in a script gets its h3 named here.
  const h = el.querySelector(":scope > .box h3");
  if (h && !el.hasAttribute("aria-labelledby")){
    if (!h.id) h.id = (el.id || "dlg") + "Title";
    el.setAttribute("aria-labelledby", h.id);
  }
  // After the frame, as modalTop's second pass: the opener fills the
  // dialog then, and may focus a field of its own, which is left alone. The
  // box itself otherwise, not its first field: a phone would raise its
  // keyboard over a dialog the person came to read.
  requestAnimationFrame(() => {
    if (el.hidden || el.contains(document.activeElement)) return;
    const box = el.querySelector(":scope > .box") || el;
    if (!box.hasAttribute("tabindex")) box.setAttribute("tabindex", "-1");
    box.focus({preventScroll: true});
  });
}

function modalClosed(el){
  const i = openModals.indexOf(el);
  if (i >= 0) openModals.splice(i, 1);
  const back = el.__opener, a = document.activeElement;
  el.__opener = null;
  // Only when the focus was still in the dialog: a Save that opened a tab
  // or a dialog that opened another has put it somewhere on purpose.
  if (a && a !== document.body && !el.contains(a)) return;
  if (!back || !back.isConnected || back.disabled || !back.getClientRects().length){ a?.blur?.(); return; }
  // Never into a text field: on a phone that raises the keyboard for nothing.
  if (back.matches("textarea, [contenteditable], input:not([type=checkbox]):not([type=radio]):not([type=button])")){
    a?.blur?.(); return;
  }
  back.focus({preventScroll: true});
}

function modalFocusables(m){
  return [...m.querySelectorAll(`a[href], button, input, select, textarea, [contenteditable="true"],
                                 [tabindex]:not([tabindex="-1"])`)]
    .filter(x => !x.disabled && x.type !== "hidden" && x.getClientRects().length);
}

// Escape closes the dialog the way it closes itself: its backdrop's "never
// mind" where it has one (which may tidy up, as closeEditor and closeRename
// do), else its foot's Cancel or Close, else simply hidden.
function dismissModal(m){
  m.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  if (m.hidden) return;
  const c = [...m.querySelectorAll(":scope > .box .foot button")]
    .find(b => !b.disabled && /^(cancel|close)$/i.test(b.textContent.trim()));
  if (c) c.click();
  if (!m.hidden) m.hidden = true;
}

// The page's one keydown listener for dialogs, wired at load in index.html
// ahead of the page's other Escape listeners: a dialog's Escape is its own,
// and the menus and armed arrows under it are not closed with it. A field
// that does something with Escape itself (a filter clearing its search)
// stops the event first and keeps the dialog open.
function modalKeys(e){
  if (e.key !== "Escape" && e.key !== "Tab") return;
  const m = topModal();
  if (!m) return;
  if (e.key === "Escape"){
    e.preventDefault(); e.stopImmediatePropagation();
    dismissModal(m);
    return;
  }
  const all = modalFocusables(m), a = document.activeElement;
  if (!all.length){ e.preventDefault(); return; }
  const first = all[0], last = all[all.length - 1];
  if (!m.contains(a)){ e.preventDefault(); (e.shiftKey ? last : first).focus(); }
  else if (e.shiftKey && (a === first || !all.includes(a))){ e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && a === last){ e.preventDefault(); first.focus(); }
}

// Every scroller in a dialog back at its top, the dialog's own included.
function modalTop(el){
  el.scrollTop = 0;
  el.querySelectorAll(".box, .box *").forEach(x => { if (x.scrollTop) x.scrollTop = 0; });
}

// ---- scroll hints -------------------------------------------------------
// A box that scrolls says so: a soft shadow on each edge with more past it,
// gone at the end (the operator, 30 Sep). A phone hides its scrollbars until
// a finger moves, and a dialog cut off at a field boundary read as the whole
// dialog. An inset shadow rather than a painted gradient, since several
// themes put their own texture on these grounds; the classes are set here,
// from the box's own numbers, on scroll and on a slow clock for content that
// grows while nobody scrolls.
// ...and the lists and logs that scroll inside a surface: a project's Reads
// and nodes in its settings, the notebook's lists, a job's log, the chat
// (the operator, 30 Sep).
const SCROLL_HINTED = ".modal:not([hidden]):not(.inline) > .box, .modal:not([hidden]):not(.inline) .sheetslot, .pane .doc.on, "
  + ".lbox, #roadmapList, #memList, #pendList, .dllog, .dmlog, .chatlog, .mpanel.show, .abpage, .dsboardwrap";
function scrollHint(el){
  const more = el.scrollHeight - el.clientHeight > 2;
  el.classList.toggle("scrollup", more && el.scrollTop > 2);
  el.classList.toggle("scrolldown", more && el.scrollTop + el.clientHeight < el.scrollHeight - 2);
}
function scrollHints(root){
  (root || document).querySelectorAll(SCROLL_HINTED).forEach(scrollHint);
  if (root?.matches?.(SCROLL_HINTED)) scrollHint(root);
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
// rides along frame by frame rather than jumping.
function foldHeight(el, from, to, done){
  // Only its own kind: another animation on the element is not this fold's.
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

// What a press just redrew in place (a chip narrowing a list, Cards or a
// List, a group picked) fades in as a rail page does: the in-half of the
// fade through, on the parts that changed (the operator, 17 Oct). Only for
// a press: a redraw the poll makes is not a change of page and never fades.
function fadeIn(els){
  if (noMotion()) return;
  for (const el of (els instanceof Element ? [els] : [...(els || [])])){
    el.getAnimations().forEach(a => { if (a.id === "fadein") a.cancel(); });
    // docIn's frames and timing, so a part arrives as a rail page does.
    el.animate([{opacity: 0}, {opacity: 1}], {duration: 220, delay: 60, fill: "backwards",
                                                easing: "cubic-bezier(.33,1,.68,1)", id: "fadein"});
  }
}

// ...and the out-half (the operator, 18 Oct: a section, a person, a chip
// and a view switched with a cut where the rail fades through). What is on
// show is copied before the press redraws it; the copy goes back where it
// stood, in the parent the redraw left (or drew again) there, so the page's
// rules still dress it, and fades out on docOut's .09s while the new part
// fades in. The copy is inert, has no ids and wears .fghost, which every
// reader of the parts skips.
function ghostOf(el){
  if (!el || !el.offsetParent) return null;
  return { g: el.cloneNode(true), r: el.getBoundingClientRect(), home: el.parentNode };
}
function ghostOut(w, home){
  if (!w) return;
  const at = home?.isConnected ? home : w.home?.isConnected ? w.home : null;
  if (!at) return;
  const g = w.g;
  g.classList.add("fghost");
  g.removeAttribute("id");
  g.querySelectorAll("[id]").forEach(e => e.removeAttribute("id"));
  g.inert = true;
  g.setAttribute("aria-hidden", "true");
  Object.assign(g.style, { position: "absolute", left: "0", top: "0", margin: "0", boxSizing: "border-box",
                           width: `${w.r.width}px`, height: `${w.r.height}px`, pointerEvents: "none", zIndex: "1" });
  at.appendChild(g);
  const r = g.getBoundingClientRect();
  g.style.left = `${(w.r.left - r.left).toFixed(1)}px`;
  g.style.top = `${(w.r.top - r.top).toFixed(1)}px`;
  const gone = () => g.remove();
  g.animate([{opacity: 1}, {opacity: 0}], {duration: 90, easing: "ease-in", fill: "forwards"}).finished.then(gone, gone);
  setTimeout(gone, 400);
}
// A press's redraw as a fade through: `pick` names the parts that change
// (a selector, or a function giving them), `swap` redraws them.
function fadeThrough(pick, swap){
  const parts = () => [...(typeof pick === "function" ? pick() : document.querySelectorAll(pick))]
    .filter(e => !e.classList.contains("fghost") && e.offsetParent);
  if (noMotion()) return swap();
  const was = parts().map(ghostOf);
  swap();
  const now = parts();
  was.forEach((w, i) => ghostOut(w, (now[i] || now[0])?.parentNode));
  fadeIn(now);
}

// The marker on the item on show slides to the one pressed (the operator,
// 17 Oct): the line under a sub-nav's tab and a notebook strip's, the bar
// beside the rail's group. One element per strip, put back when a draw
// replaced the strip's contents, moved from where it last stood (kept by
// `key`, so a group's sub-nav never slides from another group's) to the
// item now on. The strip wears .slides, which puts its own static line away.
const SLIDE_MARKS = {};
function slideMark(box, key, vertical = false){
  if (!box) return;
  const on = [...box.children].find(e => e.classList.contains("on") && !e.hidden && e.offsetWidth);
  // The same element back when a repaint took it (the rail is painted two
  // or three times on one press), so a slide already under way goes on.
  let m = box.querySelector(":scope > .slmark") || SLIDE_MARKS[key]?.el;
  if (!on){ m?.remove(); if (box.classList.contains("slides")) box.classList.remove("slides"); return; }
  if (!m){ m = document.createElement("span"); m.className = "slmark"; m.setAttribute("aria-hidden", "true"); }
  if (m.parentNode !== box) box.append(m);
  // Written only when it changes: a draw that moves nothing writes nothing.
  if (!box.classList.contains("slides")) box.classList.add("slides");
  const at = vertical ? on.offsetTop + 8 : on.offsetLeft;
  const size = vertical ? Math.max(0, on.offsetHeight - 16) : on.offsetWidth;
  const dim = vertical ? "height" : "width";
  const move = n => vertical ? `translateY(${n}px)` : `translateX(${n}px)`;
  if (m.style.transform !== move(at)) m.style.transform = move(at);
  if (m.style[dim] !== `${size}px`) m.style[dim] = `${size}px`;
  const was = SLIDE_MARKS[key];
  SLIDE_MARKS[key] = {at, size, el: m};
  // Transform alone, so the compositor runs it (the operator, 18 Oct: the
  // notebook's line stuttered): the marker takes its new size at once and
  // its old size is a scale that eases to 1, rather than a width animated
  // on the main thread, which the view drawn on the same press held up.
  const scale = n => vertical ? `scaleY(${n})` : `scaleX(${n})`;
  if (was && (was.at !== at || was.size !== size) && size > 0 && !noMotion())
    m.animate([{transform: `${move(was.at)} ${scale(was.size / size)}`}, {transform: `${move(at)} ${scale(1)}`}],
              {duration: 260, easing: "cubic-bezier(.33,1,.68,1)"});
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
  const from = card.offsetHeight, own = el.offsetHeight;
  // Only its own kind: canceling a card-level fold here would swallow the
  // class write that fold's finish handler was going to make.
  card.getAnimations().forEach(a => { if (a.id === "body") a.cancel(); });
  mutate();
  const to = card.offsetHeight;
  // A row inside a card's scroll box (the Projects card's list) grows
  // without the card growing, so the card had nothing to tween and the
  // row snapped, where the same row on the Projects tab slid (the
  // operator, 30 Sep): then the row moves over its own height.
  const host = from === to && el !== card && el.offsetHeight !== own ? el : card;
  const [h0, h1] = host === card ? [from, to] : [own, el.offsetHeight];
  if (h0 === h1) return;
  host.style.overflow = "hidden";
  const anim = host.animate([{height: h0 + "px"}, {height: h1 + "px"}],
                            {duration: 180, easing: "ease"});
  anim.id = "body";
  anim.onfinish = () => host.style.overflow = "";
}
