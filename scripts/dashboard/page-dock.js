// The dock (R218 step 4, the design's the-dashboard/dock): the foot of every
// page, holding the terminals and the chat. Shut it is one line, the open
// terminals as tabs with their session dots, Chat, and + for a new shell;
// up it takes the height kept for it (half the screen to begin with) and
// the page scrolls above it; on a phone up is the whole height above the
// bottom bar. It is the second pane, moved from beside the page to its foot
// and holding terminals only: the strip and the split it replaces are what
// the dock was for.
//
// Which tabs are open is the account's (the saved layout, as the strip's
// was); which is in front and whether the dock is up are this browser's.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

// ---- where a tab goes -------------------------------------------------------

let dockUp = false, dockH = 0;
(() => {
  try{
    dockUp = localStorage.getItem("bb.dock") === "1";
    dockH = Number(localStorage.getItem("bb.dock.h")) || 0;
  }catch(e){ /* private mode: shut, at the default height */ }
})();
function dockKeep(){
  try{
    localStorage.setItem("bb.dock", dockUp ? "1" : "0");
    if (dockH) localStorage.setItem("bb.dock.h", String(Math.round(dockH)));
  }catch(e){ /* private mode */ }
}

// A terminal and the chat are the dock's (R250 step 2); every other tab is a
// page.
const slotFor = t => t?.kind === "term" || t?.kind === "chat" ? 1 : 0;

// Put a tab where it belongs and give it the keyboard: a terminal brings the
// dock up.
function dockPlace(t){
  const i = slotFor(t);
  panes[i] = t.id;
  active = i;
  if (i === 1 && !dockUp){ dockUp = true; dockKeep(); }
  // On a phone the dock up is a sheet over the whole page, so going to a
  // page puts it down; at a desk the page scrolls above it and it stays.
  if (i === 0 && dockUp && isPhone()){ dockUp = false; dockKeep(); }
}

// The layout made to hold: a page in pane 0 and a terminal, or nothing, in
// pane 1. A layout saved by the strip (a terminal on the left, a document on
// the right, or a terminal alone) is repaired here rather than refused, and a
// page is always on show: the first one open, else Home, the landing page.
function dockSettle(){
  const a = tabOf(panes[0]), b = tabOf(panes[1]);
  if (a && slotFor(a) === 1){
    if (!b || slotFor(b) === 0){ panes[1] = a.id; panes[0] = b ? b.id : null; }
    else panes[0] = null;
  } else if (b && slotFor(b) === 0){
    if (!a) panes[0] = b.id;
    panes[1] = null;
  }
  if (panes[1] && !tabOf(panes[1])) panes[1] = null;
  if (!panes[0] || !tabOf(panes[0])){
    const page = tabs.find(t => slotFor(t) === 0);
    if (page) panes[0] = page.id;
    else {
      const t = {id: "t" + (++seq), kind: "home", arg: "__home", label: "Home"};
      tabs.push(t);
      panes[0] = t.id;
    }
  }
  if (active === 1 && !(panes[1] && dockUp)) active = 0;
}

// ---- the dock's line ------------------------------------------------------

function dockShow(id){
  const t = tabOf(id);
  if (!t) return;
  if (panes[1] === id && dockUp && active === 1){ dockUp = false; active = 0; }
  else { dockPlace(t); }
  dockKeep();
  show(t);
}

function dockToggle(open){
  dockUp = typeof open === "boolean" ? open : !dockUp;
  if (dockUp && !panes[1]){
    const t = tabs.find(x => slotFor(x) === 1);
    if (t) panes[1] = t.id;
  }
  active = dockUp && panes[1] ? 1 : 0;
  dockKeep();
  render();
}

// The line: Chat with its unread count, each terminal (a Claude session
// wears its dot), + for a shell, the pop-out for the one in front on a desk,
// and the chevron.
function dockBar(){
  const cur = panes[1], names = tabLabels();
  const terms = tabs.filter(t => t.kind === "term");
  const waiting = Object.values(state?.chat?.unread || {}).reduce((a, b) => a + b, 0);
  // A project's terminal wears its color, as its tab on the strip did.
  const tabsHtml = terms.map(t => { const pc = colorAttrs(projectColor(tabProject(t)));
    return `<span class="dtab${t.id === cur ? " on" : ""}${pc.cls}"${pc.style} data-id="${esc(t.id)}">
      <button type="button" class="dlbl" data-dock="${esc(t.id)}" role="tab" aria-selected="${t.id === cur && dockUp}" title="${esc(tabTitle(t))}">${
        isClaude(t) ? stateDot(claudeOf(sessionOf(t.arg))) : ""}${esc(names.get(t.id) || tabLabel(t))}</button>
      <button type="button" class="ic dx" data-min="${esc(t.id)}" aria-label="minimize ${esc(names.get(t.id) || tabLabel(t))}"
        title="minimize: it keeps running, and Sessions reopens it">−</button></span>`; }).join("");
  const t = tabOf(cur), chatOn = t?.kind === "chat";
  // Chat first (the operator, 15 Oct): it is always there while terminals
  // come and go, so it never scrolls off the start of the line.
  return `<div class="dockline" role="tablist" aria-label="the chat and terminals">
      <span class="dtab dchat${chatOn ? " on" : ""}${waiting ? " unread" : ""}"><button type="button" class="dlbl" data-dchat
        role="tab" aria-selected="${chatOn && dockUp}" title="${waiting ? `${waiting} unread` : "people and the projects' channels"}">Chat${
        waiting ? ` <span class="pill">${waiting}</span>` : ""}</button></span>${tabsHtml}
      ${mayShell() ? `<button type="button" class="ic dnew" data-dnew aria-label="a new shell" title="a new terminal at /workspace">+</button>` : ""}
    </div>
    <span class="sp"></span>
    ${t?.kind === "term" && dockUp && !isPhone() ? `<button type="button" class="ic" data-pop="${esc(t.id)}" title="${t.popped
        ? "reattach: bring the terminal back into this page" : "open in its own window"}">${t.popped ? "⧈" : "⧉"}</button>` : ""}
    <button type="button" class="ic dtoggle" data-dtoggle aria-expanded="${dockUp && !!t}"
      aria-label="${dockUp ? "put the dock down" : "pull the dock up"}">${dockUp && t ? "▾" : "▴"}</button>`;
}

function wireDockBar(bar){
  bar.querySelectorAll("[data-dock]").forEach(b => b.onclick = e => { e.stopPropagation(); dockShow(b.dataset.dock); });
  bar.querySelectorAll("[data-min]").forEach(b => b.onclick = e => hideTab(b.dataset.min, e));
  // A middle click on a terminal's tab ends its session, asked first, as it
  // did on the strip; auxclick with the default suppressed, or the browser
  // arms its autoscroll cursor first.
  bar.querySelectorAll(".dtab[data-id]").forEach(el => {
    el.onpointerdown = e => { if (e.button === 1) e.preventDefault(); };
    el.onauxclick = e => {
      if (e.button !== 1) return;
      e.preventDefault();
      const t = tabOf(el.dataset.id);
      if (t) killSession(sessionOf(t.arg));
    };
  });
  bar.querySelectorAll("[data-pop]").forEach(b => b.onclick = e => {
    const t = tabOf(b.dataset.pop);
    if (t?.popped) reattachTab(t.id, e); else popOut(b.dataset.pop, e);
  });
  bar.querySelector("[data-dchat]")?.addEventListener("click", e => { e.stopPropagation(); openChatTab(); });
  bar.querySelector("[data-dnew]")?.addEventListener("click", e => { e.stopPropagation(); newShell(""); });
  bar.querySelector("[data-dtoggle]")?.addEventListener("click", e => { e.stopPropagation(); dockToggle(); });
  // The dock's top edge is its handle: dragged, the height follows the
  // finger and is kept for this browser.
  bar.onpointerdown = e => {
    if (!dockUp || isPhone() || e.target.closest("button")) return;
    const pane = bar.closest(".pane"), panesEl = $("panes");
    const startY = e.clientY, startH = pane.getBoundingClientRect().height;
    const max = panesEl.getBoundingClientRect().height - 80;
    bar.setPointerCapture(e.pointerId);
    const move = ev => {
      dockH = Math.max(120, Math.min(max, startH + (startY - ev.clientY)));
      panesEl.style.setProperty("--dock-h", dockH + "px");
    };
    const up = () => {
      bar.removeEventListener("pointermove", move);
      bar.removeEventListener("pointerup", up);
      dockKeep();
      nudgeTerminals();
    };
    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", up);
  };
}

// The terminal in front brought into view on the line, which scrolls inside
// itself: with more tabs than fit, the one in front sat past its end (B740).
function dockReveal(bar){
  const line = bar.querySelector(".dockline"), on = line?.querySelector(".dtab.on");
  if (!line) return;
  line.onscroll = () => dockEdges(line);
  // ...and when the line's own width changes, a window or the rail moving.
  if (!line.bbEdges && window.ResizeObserver){
    line.bbEdges = new ResizeObserver(() => dockEdges(line));
    line.bbEdges.observe(line);
  }
  if (on){
    const lr = line.getBoundingClientRect(), r = on.getBoundingClientRect();
    if (r.left < lr.left) line.scrollLeft -= lr.left - r.left;
    else if (r.right > lr.right) line.scrollLeft += r.right - lr.right;
  }
  dockEdges(line);
}

// The line fades at an edge with more tabs past it, one side at a time
// (the operator, 16 Oct, as the strip it replaced did): hard against an
// end, that edge shows a whole tab and is left sharp.
function dockEdges(line){
  const max = line.scrollWidth - line.clientWidth;
  line.classList.toggle("fadeL", line.scrollLeft > 1);
  line.classList.toggle("fadeR", line.scrollLeft < max - 1);
}

// The pane's classes and height for the dock's state, each draw.
function dockDress(){
  const el = $("panes");
  if (!el) return;
  const up = dockUp && !!panes[1];
  el.classList.toggle("docked", true);
  el.classList.toggle("dockup", up);
  if (dockH) el.style.setProperty("--dock-h", dockH + "px");
}
