// Pull to refresh, on a touch screen (the operator, 2 Oct). The page scrolls
// inside its panes, never the document, so a phone browser's own pull to
// refresh never fires here; this is the same gesture, done by the page: a
// finger that lands on a pane scrolled to its top and drags down past the
// threshold re-reads the dashboard and the tab in front. It replaces the ↻
// that sat in the header. One classic script beside index.html; index.html
// wires it at load.

"use strict";

const PULL_AT = 72;          // px of drag that counts as a pull

// The nearest thing that scrolls, from where the finger landed.
function pullScroller(el){
  for (let n = el; n && n !== document.body; n = n.parentElement){
    const s = getComputedStyle(n);
    if (/(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight) return n;
  }
  return null;
}

// The dashboard read again, and the tab in front fetched again the way it
// is when it opens: what a person pulling down is asking for. Its promise
// settles when the dashboard's own read has, so the spinner spins for as
// long as the refresh takes.
function pullRefresh(){
  const t = tabOf(panes[active]);
  if (t) TABKINDS[t.kind]?.open?.(t);
  const done = Promise.resolve(refresh());
  drawPanes();
  return done;
}

// The browser's own pull to refresh, as near as a page can draw it: a round
// button with a circular arrow comes down from the top as the finger pulls,
// turning with the distance, and goes the accent once letting go would
// count; let go there and it spins until the refresh has landed, then rises
// back out of sight. Let go short and it rises at once.
function wirePull(){
  let y0 = null, last = 0, live = false, busy = false;
  const hint = document.createElement("div");
  hint.id = "pullHint";
  hint.setAttribute("aria-hidden", "true");
  hint.innerHTML = `<svg viewBox="0 0 24 24"><path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19 4.5V8h-3.5"/></svg>`;
  document.body.appendChild(hint);
  // How far the button has come down for a pull of `dy`: with the finger at
  // first, then slower, the way an elastic edge gives.
  const travel = dy => dy < PULL_AT ? dy * 0.9 : PULL_AT * 0.9 + (dy - PULL_AT) * 0.25;
  const show = dy => {
    hint.classList.remove("back", "spin");
    hint.classList.toggle("ready", dy >= PULL_AT);
    hint.style.opacity = String(Math.min(1, dy / (PULL_AT * 0.6)));
    hint.style.transform = `translate(-50%, ${Math.min(travel(dy), 110)}px) rotate(${dy * 3}deg)`;
  };
  const hide = () => {
    hint.classList.remove("ready", "spin");
    hint.classList.add("back");
    hint.style.opacity = "0";
    hint.style.transform = "translate(-50%, 0) rotate(0deg)";
  };
  // A row a poll redraws under the finger leaves the page, and a touch's
  // moves and lift go on to it alone, never reaching the document, so the
  // pull was lost (B854): while it is out of the page they are heard on it.
  let held = null;
  const unhold = () => {
    if (!held) return;
    held.t.removeEventListener("touchmove", held.mv);
    held.t.removeEventListener("touchend", held.en);
    held.t.removeEventListener("touchcancel", held.cn);
    held = null;
  };
  const reset = () => { unhold(); y0 = null; live = false; last = 0; if (!busy) hide(); };
  document.addEventListener("touchstart", e => {
    if (busy || e.touches.length !== 1) return reset();
    const t = e.target;
    // Not where a finger types, drags a block or works a terminal.
    if (t.closest("input, textarea, select, iframe, .dsboard, .modal:not([hidden]):not(.inline)")) return reset();
    const sc = pullScroller(t);
    if (sc && sc.scrollTop > 0) return reset();
    y0 = e.touches[0].clientY; live = false; last = 0;
    // It comes down from the header's lower edge, wherever that is, or the
    // install's banner's under it (R88).
    hint.style.top = `${Math.round((document.getElementById("banner") || document.querySelector("header"))?.getBoundingClientRect().bottom || 0)}px`;
    unhold();
    const away = f => ev => { if (!t.isConnected) f(ev); };
    held = {t, mv: away(onMove), en: away(onEnd), cn: away(reset)};
    t.addEventListener("touchmove", held.mv, {passive: true});
    t.addEventListener("touchend", held.en, {passive: true});
    t.addEventListener("touchcancel", held.cn, {passive: true});
  }, {passive: true});
  const onMove = e => {
    if (y0 === null) return;
    const dy = e.touches[0].clientY - y0;
    // Back above where it started: nothing pulled, for now. The finger may
    // still come down again, so the start is kept until it lifts.
    if (dy <= 0){ last = 0; hint.style.opacity = "0"; return; }
    live = true; last = dy;
    show(dy);
  };
  document.addEventListener("touchmove", onMove, {passive: true});
  const onEnd = () => {
    // The distance the last move reached: a lift's own position is not
    // always reported, and a lift is where the finger already was.
    if (y0 !== null && live && last >= PULL_AT){
      busy = true;
      hint.classList.remove("back", "ready");
      hint.classList.add("spin");
      hint.style.transform = `translate(-50%, ${PULL_AT * 0.9}px)`;
      const started = Date.now();
      pullRefresh().catch(() => {}).finally(() => {
        // Long enough to be seen turning, even when the answer is instant.
        setTimeout(() => { busy = false; hide(); }, Math.max(0, 450 - (Date.now() - started)));
      });
      unhold(); y0 = null; live = false; last = 0;
      return;
    }
    reset();
  };
  document.addEventListener("touchend", onEnd, {passive: true});
  document.addEventListener("touchcancel", reset, {passive: true});
}
