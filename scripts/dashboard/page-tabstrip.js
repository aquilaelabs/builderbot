// The tab strip, drawn and dragged: a press held on a tab picks it up, the
// strip scrolls at its edges while one is carried, and a drop reorders the
// tabs. paint() replaces a surface's markup only when it changed, which is
// what keeps a redraw from resetting what somebody is typing.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- drag to reorder -------------------------------------------------

// Pointer events rather than HTML5 drag-and-drop, which does not exist on
// touch. Move/up are bound to the window because drawTabs replaces the very
// element the gesture started on.
let drag = null, swallowClick = false;

// On touch a drag must be earned: hold still for half a second and the tab
// lifts (long-press is a pickup, so its release is not a click either).
// A finger that moves before then was swiping, and the drag is dropped
// rather than reordering tabs under it. Mouse drags arm immediately.
const HOLD_MS = 500;

function startDrag(ev, id){
  if (ev.pointerType === "mouse" && ev.button !== 0) return;
  drag = {id, x0: ev.clientX, y0: ev.clientY, x: ev.clientX, y: ev.clientY,
          moved: false, armed: ev.pointerType !== "touch"};
  if (!drag.armed)
    drag.timer = setTimeout(() => {
      if (!drag) return;
      drag.armed = drag.moved = true;
      document.body.classList.add("dragging");
      holdTab(id);
      edgeScroll();
    }, HOLD_MS);
  window.addEventListener("pointermove", onDrag);
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);
}

// While something is picked up and held near the edge of its scroller, the
// scroller creeps in that direction, so a drop can reach what is off screen
//: the sidebar on a phone once it has a few cards open, the one-row tab
// strip. A held pointer sends no more move events, so this is a frame loop,
// not a move handler; it re-runs the drop step with the last known position
// because the items have moved under a stationary pointer. Speed scales with
// how deep into the 48px margin the pointer sits.
let edgeRaf = 0;
function edgeScroll(){
  cancelAnimationFrame(edgeRaf);
  const tick = () => {
    edgeRaf = 0;
    if (drag?.armed && drag.moved){
      const bar = $("tabbar"), r = bar.getBoundingClientRect(), m = 48;
      const v = drag.x < r.left + m ? drag.x - (r.left + m)
              : drag.x > r.right - m ? drag.x - (r.right - m) : 0;
      if (v && bar.scrollWidth > bar.clientWidth){ bar.scrollLeft += v / 4; placeTab(); }
    } else if (cardDrag?.armed && cardDrag.moved){
      const side = document.querySelector(".col.side"), r = side.getBoundingClientRect(), m = 48;
      const v = cardDrag.y < r.top + m ? cardDrag.y - (r.top + m)
              : cardDrag.y > r.bottom - m ? cardDrag.y - (r.bottom - m) : 0;
      if (v && side.scrollHeight > side.clientHeight){ side.scrollTop += v / 4; placeCard(); }
    } else return;
    edgeRaf = requestAnimationFrame(tick);
  };
  edgeRaf = requestAnimationFrame(tick);
}

// Where the dragged tab belongs: the number of *other* tabs that come before
// the pointer in reading order. That is exactly the insertion index once the
// dragged tab is spliced out, and it handles a wrapped tab bar for free.
function dropIndex(x, y, from){
  let idx = 0;
  [...$("tabbar").querySelectorAll(".tab[data-id]")].forEach((el, i) => {
    if (i === from) return;
    const r = el.getBoundingClientRect();
    if (y > r.bottom || (y >= r.top && x > r.left + r.width / 2)) idx++;
  });
  return idx;
}

function onDrag(ev){
  if (!drag) return;
  drag.x = ev.clientX; drag.y = ev.clientY;
  const far = Math.hypot(ev.clientX - drag.x0, ev.clientY - drag.y0) >= 6;
  if (!drag.armed){
    // Moved before the hold elapsed: a swipe, not a pickup.
    if (far) endDrag();
    return;
  }
  if (!drag.moved){
    // A few pixels of slop, so an ordinary click is not read as a drag.
    if (!far) return;
    drag.moved = true; pinFor = null;
    document.body.classList.add("dragging");
    holdTab(drag.id);
    edgeScroll();
  }
  ev.preventDefault();
  placeTab();
}

// The drop step: put the held tab where the pointer says, and slide the
// others out of its way. Called per move, and per frame while the strip is
// creeping under a held pointer.
function placeTab(){
  const from = tabs.findIndex(t => t.id === drag.id);
  if (from < 0) return;
  const to = dropIndex(drag.x, drag.y, from);
  if (to !== from){
    tabs.splice(to, 0, tabs.splice(from, 1)[0]);
    reorderTabEls();
  }
}

// Mid-drag the strip is re-sorted in place: the same elements moved, never
// rebuilt. A touch is implicitly captured by the node it began on: rebuild
// the strip and that node is detached, its events stop reaching the window
// listeners that run the drag, and the browser scrolls instead. Moving a
// node keeps it in the document. The full redraw waits for pointerup.
const holdTab = id => $("tabbar").querySelector(`.tab[data-id="${id}"]`)?.classList.add("held");

function reorderTabEls(){
  const bar = $("tabbar");
  const els = new Map([...bar.querySelectorAll(".tab[data-id]")].map(el => [el.dataset.id, el]));
  const play = flip(() => bar.querySelectorAll(".tab[data-id]"), el => el.dataset.id);
  const anchor = bar.querySelector(".sep");
  for (const t of tabs){ const el = els.get(t.id); if (el) bar.insertBefore(el, anchor); }
  play();
}

function endDrag(){
  clearTimeout(drag?.timer);
  window.removeEventListener("pointermove", onDrag);
  window.removeEventListener("pointerup", endDrag);
  window.removeEventListener("pointercancel", endDrag);
  document.body.classList.remove("dragging");
  const moved = drag?.moved;
  drag = null;
  // Redraw ONLY after a real drag. `click` is dispatched after `pointerup`, so
  // rebuilding the tab bar here would replace the button mid-gesture and the
  // click would never reach a handler: every tab click silently doing nothing.
  if (!moved) return;
  swallowClick = true;                  // ...and the click ending a drag is not
  setTimeout(() => swallowClick = false, 0);   //    a request to switch tabs
  drawTabs();
  // Saved now, not on the next poll: the other browser's next write would
  // otherwise arrive first and put the strip back the way it was.
  saveLayout();
}

// Whether drawTabs has painted once: the very first draw is a page opening,
// not tabs arriving, so it plays no entrances.
let tabsDrawn = false, lastCur = null;

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

function drawTabs(){
  // Mid-drag, only re-sort: the status poll renders every fifteen seconds,
  // and a rebuild here would detach the node a finger is holding (see
  // reorderTabEls). Labels catch up on the redraw that follows the drop.
  if (drag){ reorderTabEls(); return; }
  if (pinFor && !tabOf(pinFor)) pinFor = null;   // its tab went (another browser's layout, a kill)
  const cur = panes[active], names = tabLabels();
  // Documents only (R218 step 2): a tool is a page on the rail now, and its
  // tab, still in `tabs` so the panes and the saved layout work as before,
  // is not drawn here.
  const html = tabs.filter(t => !isToolKind(t.kind)).map(t => {
    // Only a split has sides worth marking; a lone pane is just "the screen".
    const where = !isSplit() ? "" : panes[0] === t.id ? "◧" : panes[1] === t.id ? "◨" : "";
    const held = drag?.moved && drag.id === t.id ? " held" : "";
    // A notebook wears its project's color; a tool tab wears the icon its
    // button on the Tools card carries.
    const pc = colorAttrs(projectColor(tabProject(t)));
    const icon = TABKINDS[t.kind]?.icon || "";
    // A tab to a screen reader, and which one is showing (R88); the pin
    // and the close beside it stay buttons.
    return `<span class="tab ${t.id===cur?"on":""}${held}${pc.cls}" data-id="${esc(t.id)}"${pc.style} role="presentation">
      <button class="lbl" data-show="${esc(t.id)}" role="tab" aria-selected="${t.id === cur}" title="${esc(tabTitle(t))}">${isClaude(t) ? stateDot(claudeOf(sessionOf(t.arg))) : ""}${icon}${esc(names.get(t.id))}${where?` <span style="opacity:.7">${where}</span>`:""}</button>
      <button class="ic" data-pin="${esc(t.id)}" title="pin to a pane">⇱</button>
      ${t.kind === "term"
        // Its own window on a desktop (R8): the tab stays here, blank, with
        // Reattach. Hidden at phone width by the same rule as the pin.
        ? `<button class="ic" data-pop="${esc(t.id)}" title="${t.popped
             ? "reattach: bring the terminal back into this page"
             : "open in its own window: the tab stays here, blank, with Reattach"}">${t.popped ? "⧈" : "⧉"}</button>`
        : ""}
      ${
        // A terminal is minimized, not closed: it keeps running and is listed
        // under Sessions: the workspace tab the same as any other. A document
        // has nothing to keep, so its ✕ means what it says. Neither asks;
        // nothing is lost either way.
        t.kind === "term"
          ? `<button class="ic" data-min="${esc(t.id)}"
               title="minimize: the terminal keeps running, reopen it from Sessions">−</button>`
          : `<button class="ic" data-close="${esc(t.id)}" title="close">✕</button>`}
    </span>`;
  }).join("");

  const bar = $("tabbar");
  const full =
    (mayShell()
      ? `<button id="bNew" class="ic newtab" title="new terminal at /workspace">+</button>`
      : "") +
    html +
    // The spacer stays: reorderTabEls inserts before it, and it is what
    // keeps the tabs left-packed. What was after it (the ⌨ toggle) is
    // gone, because a desktop has a keyboard. The on-screen keys are the
    // phone's, and live on the phone's own bar.
    `<span class="sep"></span>` +
    (pinFor ? `<span class="pinmenu" id="pinmenu">
        <button data-l="${esc(pinFor)}">◧ Left</button>
        <button data-r="${esc(pinFor)}">◨ Right</button>
      </span>` : "");
  // Same strip as last time: the poll, mostly. Nothing to rebuild or slide;
  // ghosts already fading finish on their own.
  if (painted.get(bar) === full){ finishTabs(cur); return; }
  painted.set(bar, full);

  // Slide, don't teleport, and across the innerHTML rebuild, which is why
  // everything is keyed by tab id rather than element. Old positions (plus a
  // clone, for a tab about to vanish) are captured before the rebuild; after
  // it, survivors slide to their new spot, newcomers pop in, and the departed
  // fades out as an inert ghost pinned where it was. Not while the strip is
  // display:none (a phone showing the dashboard): every rect is zero there,
  // and a ghost pinned at zero would surface at the strip's left edge if the
  // terminal view came forward inside the fade.
  const prev = tabsDrawn && !noMotion() && rendered(bar)
    ? new Map([...bar.querySelectorAll(".tab")]
        .filter(el => el.dataset.id)
        .map(el => [el.dataset.id,
                    {r: el.getBoundingClientRect(), ghost: el.cloneNode(true)}]))
    : null;

  // Ghosts mid-fade ride across the rebuild: they are inert clones, and a
  // status poll landing during the 140ms would otherwise cut the fade short.
  const ghosts = [...bar.querySelectorAll(".tab:not([data-id])")];
  bar.innerHTML = full;
  ghosts.forEach(g => bar.appendChild(g));
  bar.querySelectorAll("[data-show]").forEach(b => {
    b.onpointerdown = e => startDrag(e, b.dataset.show);
    b.onclick = () => { if (!swallowClick) focusTab(b.dataset.show); };
  });
  // Middle-click closes for good, the way a browser tab does: a terminal's
  // session ends with it (after the same confirmation the Sessions ✕ asks),
  // a document just goes. `click` never fires for button 1 and pointerdown
  // would arm the autoscroll cursor first, so this is auxclick with the
  // default suppressed.
  bar.querySelectorAll(".tab[data-id]").forEach(el => {
    el.onpointerdown = e => { if (e.button === 1) e.preventDefault(); };
    el.onauxclick = e => {
      if (e.button !== 1) return;
      e.preventDefault();
      const t = tabOf(el.dataset.id);
      if (t?.kind === "term") killSession(sessionOf(t.arg)); else hideTab(el.dataset.id, e);
    };
  });
  bar.querySelectorAll("[data-pin]").forEach(b => b.onclick = e => togglePin(b.dataset.pin, e));
  bar.querySelectorAll("[data-min]").forEach(b => b.onclick = e => hideTab(b.dataset.min, e));
  bar.querySelectorAll("[data-pop]").forEach(b => b.onclick = e =>
    (tabOf(b.dataset.pop)?.popped ? reattachTab : popOut)(b.dataset.pop, e));
  bar.querySelectorAll("[data-close]").forEach(b => b.onclick = e => hideTab(b.dataset.close, e));
  bar.querySelectorAll("[data-l]").forEach(b => b.onclick = e => pinTo(b.dataset.l, 0, e));
  bar.querySelectorAll("[data-r]").forEach(b => b.onclick = e => pinTo(b.dataset.r, 1, e));
  if ($("bNew")) $("bNew").onclick = () => newShell("");
  if (pinFor) placePinMenu();

  if (prev){
    const seen = new Set();
    bar.querySelectorAll(".tab").forEach(el => {
      seen.add(el.dataset.id);
      const was = prev.get(el.dataset.id);
      if (!was){
        el.animate([{opacity: 0, transform: "scale(.8)"}, {opacity: 1, transform: "none"}],
                   {duration: 140, easing: "ease"});
        return;
      }
      const now = el.getBoundingClientRect();
      const dx = was.r.left - now.left, dy = was.r.top - now.top;
      if (dx || dy)
        el.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: "none"}],
                   {duration: 140, easing: "ease"});
    });
    const barR = bar.getBoundingClientRect();
    for (const [id, was] of prev){
      if (seen.has(id)) continue;
      const g = was.ghost;
      // Inert: no id to collide with the live strip, no events, pinned where
      // the tab was (scroll included) while it fades.
      g.removeAttribute("data-id");
      g.style.cssText = `position:absolute;margin:0;pointer-events:none;`
        + `left:${was.r.left - barR.left + bar.scrollLeft}px;`
        + `top:${was.r.top - barR.top + bar.scrollTop}px;width:${was.r.width}px`;
      bar.appendChild(g);
      g.animate([{opacity: 1, transform: "none"}, {opacity: 0, transform: "scale(.8)"}],
                {duration: 140, easing: "ease"}).onfinish = () => g.remove();
    }
  }
  tabsDrawn = true;
  // The strip just changed width. Scroll and resize both call this and adding a
  // tab is neither; it happened to work because a new tab scrolls itself into
  // view, which is luck rather than a rule, and closing one scrolls nothing.
  updateArrows();
  finishTabs(cur);
}

// The tail every drawTabs shares, rebuilt or not: on a phone the strip is
// one scrolling row, and a tab that just became active is brought into view
//: once, when it changes, so a strip the operator swiped away to look at
// something else is not snapped back by the next poll.
// ---- the phone's tab picker (R119 step 5) ----------------------------------
// One button naming the tab on show and how many are open, and a list of
// every tab under it, each with its close (or a terminal's minimize) and,
// for an account with a shell, a new terminal. The rows act through the
// strip's own functions, so a tab picked here is the same as one tapped there.
let tabPickOpen = false;
function tabPickShow(on){
  tabPickOpen = !!on;
  const list = $("tabPickList"), b = $("tabPick");
  if (!list || !b) return;
  b.setAttribute("aria-expanded", String(tabPickOpen));
  if (tabPickOpen){
    const strip = b.closest(".tabstrip");
    list.style.top = (strip.offsetTop + strip.offsetHeight) + "px";
    drawTabPick();
  }
  list.hidden = !tabPickOpen;
}
function drawTabPick(){
  const b = $("tabPick"), list = $("tabPickList");
  if (!b || !list) return;
  const cur = panes[active], names = tabLabels();
  const t = tabOf(cur);
  // The documents (R218 step 2): a page on show is named, and the list
  // under it is the strip's, the pages being the phone's bar.
  const docs = tabs.filter(x => !isToolKind(x.kind));
  const say = `${t ? TABKINDS[t.kind]?.icon || "" : ""}<span class="nm">${esc(t ? names.get(t.id) : "no tab open")}</span>${
    docs.length > 1 ? `<span class="pill">${docs.length}</span>` : ""}<span class="chev">▾</span>`;
  if (b.innerHTML !== say) b.innerHTML = say;
  b.setAttribute("aria-label", `tab: ${t ? names.get(t.id) : "none"}, ${docs.length} open; list them`);
  if (!tabPickOpen) return;
  list.innerHTML = docs.map(x => `<div class="tprow${x.id === cur ? " on" : ""}" role="none">
      <button type="button" class="lbl" role="menuitem" data-pshow="${esc(x.id)}">${
        isClaude(x) ? stateDot(claudeOf(sessionOf(x.arg))) : ""}${TABKINDS[x.kind]?.icon || ""}${esc(names.get(x.id))}</button>
      ${x.kind === "term"
        ? `<button type="button" class="ic" data-pmin="${esc(x.id)}" aria-label="minimize ${esc(names.get(x.id))}">−</button>`
        : `<button type="button" class="ic" data-pclose="${esc(x.id)}" aria-label="close ${esc(names.get(x.id))}">✕</button>`}
    </div>`).join("")
    + (mayShell() ? `<div class="tprow" role="none"><button type="button" class="lbl" role="menuitem" data-pnew>+ New terminal</button></div>` : "");
  list.querySelectorAll("[data-pshow]").forEach(e => e.onclick = () => { tabPickShow(false); focusTab(e.dataset.pshow); });
  list.querySelectorAll("[data-pclose]").forEach(e => e.onclick = ev => { ev.stopPropagation(); hideTab(e.dataset.pclose, ev); drawTabPick(); });
  list.querySelectorAll("[data-pmin]").forEach(e => e.onclick = ev => { ev.stopPropagation(); hideTab(e.dataset.pmin, ev); drawTabPick(); });
  list.querySelectorAll("[data-pnew]").forEach(e => e.onclick = () => { tabPickShow(false); $("bNew")?.click(); });
}

function finishTabs(cur){
  // A drag dropped where it started rebuilds nothing, so the pickup dim is
  // taken off here rather than by the rebuild that no longer happens.
  if (!drag) $("tabbar").querySelectorAll(".tab.held").forEach(el => el.classList.remove("held"));
  if (cur !== lastCur){ lastCur = cur; revealActiveTab(); }
  updateArrows();
  drawTabPick();
}

// By offsets, not scrollIntoView: that would also scroll every ancestor it
// could, and mid view-switch the column is translated off screen: the
// browser would drag `main` sideways to chase it and wreck the slide.
function revealActiveTab(){
  const bar = $("tabbar"), on = bar.querySelector(".tab.on");
  if (!on || bar.scrollWidth <= bar.clientWidth + 1) return;
  const l = on.offsetLeft, r = l + on.offsetWidth, w = bar.clientWidth;
  const to = l < bar.scrollLeft + 8 ? l - 8
           : r > bar.scrollLeft + w - 8 ? r - w + 8 : null;
  if (to !== null) bar.scrollTo({left: to, behavior: noMotion() ? "instant" : "smooth"});
}
function updateArrows(){
  const bar = $("tabbar");
  const atL = bar.scrollLeft <= 1;
  const atR = bar.scrollLeft + bar.clientWidth >= bar.scrollWidth - 1;
  $("tabL").disabled = atL;
  $("tabR").disabled = atR;
  // The same two facts as classes, so the strip fades the edge it is actually
  // cutting a tab off at, and only that edge. Hard against one end, that side
  // is showing a whole tab and a fade there would be dimming something
  // complete, which is the half of this worth getting right.
  bar.classList.toggle("fadeL", !atL);
  bar.classList.toggle("fadeR", !atR);
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
