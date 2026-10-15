// The layout: the tabs, shared between browsers, saved on the server so a
// phone and a desk have the same strip open and adopted when another
// browser changes it; the panes and the tab in front, each browser's own
// (R131: switching tabs on the phone switched the desk too, the operator,
// 5 Oct); and render(), the one draw of the page every change ends in.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- one draw of the page -----------------------------------------------

// The Sessions card redraws with the layout, not just on the status poll: its
// pills mirror the tab strip, and a minimize would otherwise read as "on the
// tab bar" for up to a poll interval.
// Each card under its own guard here too: refresh() ends in render(), so a
// draw that threw here would still take the poll down after the guarded
// pass above it had kept the page up.
function render(){ shellBoot(); if (state) dockSettle(); drawPanes(); drawKeys(); drawRail(); shellSync(); saveLayout();
                   // The first draw that had something to draw ends the boot
                   // ground: from here a pane is a terminal's black or a
                   // tab's panel, and the loading line has been replaced.
                   if (state) document.body.classList.toggle("booting", false);
                   if (state){ drawCard("sessions", () => drawSessions(state.sessions));
                               drawCard("linux", drawLinux);
                               drawCard("commands", drawCommands); drawCard("git", drawGit);
                               drawCard("custom", drawCustom); } }

// ---- layout, shared between browsers ---------------------------------

// The tab strip lives on the server so a phone picks up what the desktop has
// open. `myRev` is the revision this client last wrote or adopted; a status
// poll carrying a different one means another browser changed something.
// Which tab is in front, and which tab each pane holds, are this browser's
// own, kept in localStorage: the server's copy is taken only by a browser that has
// none yet, and a switch writes nothing to the server (R131).
let myRev = -1, savePending = false, saveTimer = null, adopting = false;
const PANES_KEY = "bb.panes";
let lastLocal = null;
function readLocalPanes(){
  try{
    const v = JSON.parse(localStorage.getItem(PANES_KEY) || "null");
    return v && Array.isArray(v.panes) ? v : null;
  }catch(e){ return null; }                   // private mode, or junk
}
function keepLocalPanes(){
  const loc = JSON.stringify({panes, active});
  if (loc === lastLocal) return;
  lastLocal = loc;
  try{ localStorage.setItem(PANES_KEY, loc); }catch(e){ /* private mode */ }
}

function layoutNow(){
  return {tabs: tabs.map(t => ({id:t.id, kind:t.kind, arg:t.arg,
                                label:t.label, popped: !!t.popped})),
          panes, active};
}

function saveLayout(){
  if (adopting) return;                 // echoing back what we were just given
  // Nor before the first status has arrived: this page has not yet been told
  // what the strip is, and saving its built-in default now (a bottom-bar tap
  // on a phone that came back on the terminal view is enough to render)
  // would overwrite the real one, and then, holding that revision, ignore
  // the server's copy of what it just destroyed.
  if (!state) return;
  keepLocalPanes();
  // Pushed only when the TABS changed: the panes and the tab in front ride
  // along as the server's first-time default, and a switch alone is not a
  // write, so the other browser's strip is left where it was.
  const key = JSON.stringify(layoutNow().tabs);
  if (key === lastKey) return;          // render() runs on every poll
  lastKey = key;
  lastSaved = JSON.stringify(layoutNow());
  savePending = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(pushLayout, 400);
}
let lastSaved = null, lastKey = null, pushing = false;

// One save on the wire at a time. Two in flight could land in either order,
// and the older strip arriving second would be stored under the newer
// revision, which this page would then hold, and so never take the fix
// back from the server. A change made while one is out is sent when it
// lands, newest state only; savePending stays up throughout so a poll in
// between does not adopt what is about to be overwritten.
async function pushLayout(){
  if (pushing) return;
  pushing = true;
  const body = lastSaved;
  let ok = false;
  try{
    const r = await fetch("/api/layout", {method:"POST",
      headers:{"Content-Type":"application/json"}, body});
    const j = await r.json();
    if (typeof j.rev === "number"){ myRev = j.rev; ok = true; }
  }catch(e){ /* below */ }
  pushing = false;
  if (lastSaved !== body) pushLayout();
  else if (ok) savePending = false;
  else {
    // Not saved. Forget that it was, so the next render (the poll, within
    // fifteen seconds) tries again: a change silently kept local would be
    // overwritten by the other browser's next write. Not retried right here:
    // a server that is down would be hammered.
    lastSaved = null; savePending = false;
  }
}

// Take on a layout another browser wrote. Terminal tabs restore themselves:
// bb-tty attaches to the session if it is still there and recreates it in the
// same directory if it is not.
function adoptLayout(v){

  // Only a revision NEWER than the one this page holds. A poll the server
  // answered just before our push landed arrives carrying the strip as it
  // was before the change: one revision behind, and by then savePending is
  // already false. Under a plain "different revision" test that stale copy
  // was adopted: the tab just minimized came back, and a killed session's
  // tab was rebuilt, which recreated the session. Revisions only go up.
  if (!v || v.rev <= myRev || savePending) return;
  // Revision 0 with nothing in it is a server that has never been written to,
  // not an operator who closed every tab: keep the default strip rather than
  // adopting the void. A strip the operator deliberately emptied was saved,
  // which bumped the revision, so it still propagates.
  if (v.rev === 0 && !v.tabs.length){ myRev = v.rev; return; }
  myRev = v.rev;
  adopting = true;
  // Taken whole, workspace tab included; it is an ordinary tab now, so a
  // browser that closed it must not have it resurrected by this one. The map
  // also quietly drops the `fixed` flag a layout saved by the older page has.
  // `popped` (R8) survives only where this window holds the popped window's
  // handle: another browser's pop-out is not one this page can see or close,
  // and a placeholder nobody can reattach would be a dead pane.
  // A tab of a kind this page no longer has (the Phone tab became a section
  // of the Nodes tab, 2 Oct) is left out rather than drawn as nothing.
  tabs = v.tabs.filter(t => t.kind === "term" || TABKINDS[t.kind])
    .map(t => ({id:t.id, kind:t.kind, arg:t.arg, label:t.label,
                popped: !!t.popped && popWins.has(t.id)}));
  // Ids come back from another browser's counter; keep ours ahead of them so a
  // tab opened here cannot collide with one opened there.
  for (const t of tabs){
    const n = parseInt(String(t.id).replace(/^t/, ""), 10);
    if (Number.isFinite(n) && n > seq) seq = n;
  }
  const ids = new Set(tabs.map(t => t.id));
  // The panes and the tab in front: this browser's own where it has them,
  // reconciled against the strip just adopted. A pane whose tab is not in
  // the strip (closed elsewhere, or reopened under an id the server has not
  // been told yet) takes the server's pane for that slot, then the first tab.
  const mine = readLocalPanes() || v;
  const slot = i => ids.has(mine.panes[i]) ? mine.panes[i]
                  : ids.has(v.panes[i]) ? v.panes[i]
                  : (i === 0 ? (tabs[0]?.id ?? null) : null);
  panes = [slot(0), slot(1)];
  if (panes[1] === panes[0]) panes[1] = null;
  active = panes[1] && (ids.has(mine.panes[1]) ? mine.active : v.active) === 1 ? 1 : 0;
  lastSaved = JSON.stringify(layoutNow());
  lastKey = JSON.stringify(layoutNow().tabs);
  try{ render(); } finally{ adopting = false; }   // a draw error must not
                                                  // leave saves suppressed
}
