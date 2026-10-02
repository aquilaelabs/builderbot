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
// is when it opens: what a person pulling down is asking for.
function pullRefresh(){
  refresh();
  const t = tabOf(panes[active]);
  if (t) TABKINDS[t.kind]?.open?.(t);
  drawPanes();
}

function wirePull(){
  let y0 = null, last = 0, live = false;
  const hint = document.createElement("div");
  hint.id = "pullHint";
  hint.setAttribute("aria-hidden", "true");
  document.body.appendChild(hint);
  const show = (dy) => {
    const p = Math.min(1, dy / PULL_AT);
    hint.style.opacity = String(p);
    hint.style.transform = `translate(-50%, ${Math.min(dy, PULL_AT) / 2}px)`;
    hint.textContent = p >= 1 ? "release to refresh" : "pull to refresh";
  };
  const reset = () => { y0 = null; live = false; hint.style.opacity = "0"; hint.style.transform = "translate(-50%, 0)"; };
  document.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) return reset();
    const t = e.target;
    // Not where a finger types, drags a block or works a terminal.
    if (t.closest("input, textarea, select, iframe, .dsboard, .modal:not([hidden])")) return reset();
    const sc = pullScroller(t);
    if (sc && sc.scrollTop > 0) return reset();
    y0 = e.touches[0].clientY; live = false;
  }, {passive: true});
  document.addEventListener("touchmove", e => {
    if (y0 === null) return;
    const dy = e.touches[0].clientY - y0;
    // Back above where it started: nothing pulled, for now. The finger may
    // still come down again, so the start is kept until it lifts.
    if (dy <= 0){ last = 0; hint.style.opacity = "0"; return; }
    live = true; last = dy;
    show(dy);
  }, {passive: true});
  document.addEventListener("touchend", () => {
    // The distance the last move reached: a lift's own position is not
    // always reported, and a lift is where the finger already was.
    if (y0 !== null && live && last >= PULL_AT) pullRefresh();
    reset();
  }, {passive: true});
  document.addEventListener("touchcancel", reset, {passive: true});
}
