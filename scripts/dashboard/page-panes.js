// The panes: the two viewports the tabs are shown in, each with its bar, a
// terminal's frame and the veil over it while it connects, the console
// under a Claude session, a notebook or a document drawn in, the frames
// kept warm per pane, and a terminal nudged when the page comes back.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- panes -----------------------------------------------------------

// The pane's title bar is redrawn on every pass; it is cheap, and its close
// button only exists while the layout is split. The pane *body* is left alone
// whenever the same tab is still in it, because rebuilding it would reload the
// iframe and drop a live terminal for no reason.
function paintBar(pane, t, i){
  const bar = pane.querySelector(".bar");
  // The dock's pane wears the dock's line (R218 step 4), with or without a
  // terminal in it.
  if (i === 1){
    setClass(bar, "bar dockbar");
    bar.style.removeProperty("--pc");
    // Painted only when it changed: a poll that moves nothing leaves the
    // line's buttons where they are, and a pointer over one keeps its hover.
    if (paint(bar, dockBar())){ wireDockBar(bar); dockReveal(bar); }
    return;
  }
  // Only the kinds that still declare it. Toolchains moved its own into the tab
  // beside the node picker, where a control belongs: this bar is the tab's
  // name and its close button everywhere else, and a third thing in it was a
  // shape one tab had and no other.
  const reload = TABKINDS[t.kind]?.reload
    ? `<button class="ic" data-reload="${esc(t.kind)}" style="margin-left:8px">reload</button>` : "";
  // A page (R218 step 2) wears its group's sub-nav, or its name, and no
  // close: the rail is how you leave it. A project (step 3) wears its
  // header: the name, the facts, the session's state and its actions.
  const proj = t.kind === "notebook";
  // Painted, and wired, only when it changed (R218 step 10): assigned on
  // every draw, the page's sub-nav and a project's header were rebuilt by
  // each poll under the pointer that was about to press them.
  const fresh = paint(bar, isToolKind(t.kind) ? shellBar(t, i) + reload
    : proj ? projectHeader(t)
    : `<span title="${esc(tabTitle(t))}">${esc(tabLabel(t))}</span>${reload}`, true);
  bar.classList.toggle("page", isToolKind(t.kind));
  bar.classList.toggle("proj", proj);
  if (fresh){
    wireShellBar(bar);
    if (proj) wireProjectHeader(bar);
    bar.querySelectorAll("[data-reload]").forEach(b =>
      b.onclick = e => { e.stopPropagation();
        loadFindings(true); });
  }
  if (proj) syncResumeMenu();
  // The project's color on the strip too, so a split pane says whose it is.
  const tone = colorTone(projectColor(tabProject(t)));
  bar.classList.toggle("pc", !!tone);
  if (bar.style.getPropertyValue("--pc") !== (tone || "")) bar.style.setProperty("--pc", tone || "");
}

// Uncover a terminal the moment there is nothing white left to see.
//
// The flash was never the terminal being slow. The frame's load event fires
// when its document exists, and ttyd's stylesheet dresses `.xterm-viewport`
// and nothing above it: `body,html{height:100%;margin:0}` and no color at
// all. A document with no background of its own is a transparent canvas, and
// a transparent canvas is what a browser paints white; Firefox on Android
// does it over whatever the iframe element underneath is set to.
//
// So rather than cover that window for a guessed number of milliseconds, this
// closes it: /term is proxied through this server, the frame is same-origin,
// and one inline style on its <html> gives it the pane's own color. There is
// then no white to hide, and the cover comes off on the next frame.
//
// The cover stays, for the two moments this cannot reach: before load, when
// there is no document to dress, and the case where the frame will not answer
// at all: a proxy error page on an opaque origin, or an engine that decides
// the origins differ. That is what the clock below is for. It is the
// backstop, not the mechanism.
const VEIL_MAX  = 400;                 // longest it will ever stay
const VEIL_FADE = 120;                 // matches the CSS transition
const PANE_BG   = "#2b2b2b";           // the same color as .pane iframe

// Give a terminal frame's document a background of its own. True if it took,
// null if the frame cannot be reached, which is the only case the clock is
// still needed for.
function dressFrame(frame){
  try {
    const d = frame.contentDocument;
    if (!d || !d.documentElement) return null;
    d.documentElement.style.background = PANE_BG;
    return true;
  } catch { return null; }
}

function unveil(frame){
  refreshSoon();                       // a new terminal appears under Sessions
  const veil = frame.parentElement?.querySelector(".veil");
  if (!veil) return;
  const lift = () => {
    if (!veil.isConnected) return;     // the pane was replaced under us
    veil.classList.add("gone");
    setTimeout(() => veil.remove(), VEIL_FADE + 60);
  };
  // One frame's grace either way: after dressing it, so the color is on the
  // screen before the cover over it goes.
  if (dressFrame(frame) === null) setTimeout(lift, VEIL_MAX);
  else requestAnimationFrame(lift);
}

// The console bar, for an account with no shell (roadmap #27).
//
// The terminal above it is the real one, relayed to a ttyd started WITHOUT
// --writable: it renders Claude's own full-screen interface correctly, which
// capturing the pane into a textarea could never do, and the browser cannot
// type into it at all. So the way in is this row: the send path, which is
// the same table lookup and literal text every other thing this page can make
// happen goes through, and the way out is Terminate.
//
// Drawn only when there is no shell to have. An administrator types into the
// terminal itself and would find a second input box confusing.
function consoleBar(t){
  if (mayShell() || !isClaude(t)) return "";
  const s = sessionOf(t.arg);
  return `<div class="consbar" data-sess="${esc(s)}">
    <input class="consin" placeholder="message Claude, then Enter"
      aria-label="message Claude" autocomplete="off" spellcheck="false">
    <button type="button" class="conssend primary">Send</button>
    <button type="button" class="consend" title="end this conversation: the
      transcript is kept and can be resumed">Terminate</button>
  </div>`;
}

// Wired after every repaint, because the bar is redrawn with its pane. The
// field keeps what was typed across a repaint the same way the node config
// drafts do: a fifteen-second poll must not eat a half-written message.
const consDraft = {};
function wireConsole(root){
  root.querySelectorAll(".consbar").forEach(bar => {
    const sess = bar.dataset.sess;
    const inp = bar.querySelector(".consin");
    if (consDraft[sess] !== undefined) inp.value = consDraft[sess];
    inp.oninput = () => { consDraft[sess] = inp.value; };
    const send = async () => {
      const text = inp.value;
      if (!text.trim()) return;
      inp.value = ""; consDraft[sess] = "";
      let r = {};
      try{
        r = await (await fetch("/api/say", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session: sess, text }) })).json();
      }catch(e){ r = { error: "could not reach the container" }; }
      // Put it back on failure rather than losing it: a message somebody
      // typed is worth more than a tidy field.
      if (r.error){ notify(r.error, true); inp.value = text; consDraft[sess] = text; }
    };
    inp.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); } };
    bar.querySelector(".conssend").onclick = send;
    bar.querySelector(".consend").onclick = () => killSession(sess);
  });
}

// The tabs whose open hook the draw in progress ran: show() reads it so a
// tab is opened once, by whichever of the two ran first.
const openedNow = new Set();
function drawPanes(){
  openedNow.clear();
  if (!state) return;    // nothing to point a frame at until the first poll
  dockDress();
  // A frame kept alive behind the visible one belongs to a tab. When the tab
  // goes (closed, or replaced by a Resume that mints a new one) the frame
  // is nobody's, and a nobody's frame is still an attached tmux client.
  const liveTabs = new Set(tabs.map(t => t.id));
  for (let j = 0; j < 2; j++)
    [...($("pane" + j).querySelector(".stack")?.children || [])]
      .filter(c => c.dataset.key && !liveTabs.has(c.dataset.key.split("|")[0]))
      .forEach(c => c.remove());
  for (let i = 0; i < 2; i++){
    const pane = $("pane" + i);
    pane.classList.toggle("hidden", false);
    pane.classList.toggle("active", i === 1 && active === 1 && dockUp);
    pane.classList.toggle("dock", i === 1);
    if (i === 1 && !isSplit()){
      // No terminal in the dock: its line alone. Emptied, not just hidden:
      // a hidden frame is still a live tmux client, and one that
      // reattachTerminals would reload, recreating a session since ended.
      if (pane.dataset.tab || !pane.querySelector(".bar")){
        pane.innerHTML = `<div class="bar dockbar"></div>`;
        pane.dataset.tab = pane.dataset.kind = pane.dataset.arg = pane.dataset.popped = "";
      }
      paintBar(pane, null, 1);
      continue;
    }

    const t = tabOf(panes[i]);
    // Arg included: two browsers minting the same id for different things
    // inside one poll (their counters were equal), or a dead session's tab
    // taking a resume arg, must rebuild the frame: id and kind alone said
    // "same" and left the old terminal showing under the new name.
    const same = pane.dataset.tab === (t?.id || "") && pane.dataset.kind === (t?.kind || "")
              && pane.dataset.arg === (t?.arg || "")
              // ...and whether it is popped out (R8): the same tab with its
              // frame gone, or back, is a rebuild.
              && pane.dataset.popped === (t?.popped ? "1" : "");
    if (same && t){
      paintBar(pane, t, i);
      // Refill a document pane only when the report itself changed. Doing it
      // on every status poll would fight the reader for control of the page.
      // A pane still showing the same tab. Whether it redraws is the kind's
      // own business (see TABKINDS.live) and this is the case that used to
      // be forgotten, because a tab looks perfectly fine until its data moves.
      renderDoc(i, t, pane);
      continue;
    }
    if (same) continue;

    pane.dataset.tab = t?.id || ""; pane.dataset.kind = t?.kind || ""; pane.dataset.arg = t?.arg || "";
    pane.dataset.popped = t?.popped ? "1" : "";
    pane.onclick = () => { if (isSplit() && active !== i && (i === 0 || dockUp)){ active = i; render(); } };

    const st = paneStack(pane);
    if (!t){ showInStack(st, "", () =>
      `<div class="empty-pane">no tab here: “+” opens a terminal, Sessions reopens a running one</div>`);
      continue; }
    const key = `${t.id}|${t.kind}|${t.arg}${t.popped ? "|popped" : ""}`;
    // A terminal that was on screen a moment ago is kept alive behind the one
    // that replaced it, so coming back to it is instant. Two panes must never
    // hold the same one: a second live client on a session is the size fight one
    // client per terminal avoids.
    if (t.kind === "term" || t.kind === "notebook") dropElsewhere(i, key);
    // Same tab, different argument: a dead session's tab taking a Resume's
    // transcript id: is a different frame, and the old one is nobody's now.
    [...st.children].filter(c => c.dataset.key !== key
                            && c.dataset.key?.startsWith(t.id + "|"))
                    .forEach(c => c.remove());
    const { el, fresh } = showInStack(st, key, () => t.kind === "term" && t.popped
      // Popped out into its own window (R8): the tab stays, blank, with the
      // one control that makes sense. Not a hidden frame: that would be a
      // second client on the session, the size fight one client per terminal avoids.
      ? `<div class="slot popped"><div class="empty-pane">this terminal is open in its own window<br>
           <button type="button" class="reattach" data-reattach="${esc(t.id)}">Reattach</button></div></div>`
      : t.kind === "term"
      // Selecting in a shell copies: the terminal fires the copy itself, and
      // this is the permission that lets it, since the terminal is served from
      // its own port and so counts as a cross-origin frame. Claude tabs are
      // left without it; they keep tmux's mouse mode, where a drag never
      // becomes a browser selection in the first place.
      ? `<div class="slot"><iframe title="${esc(tabLabel(t))}"${isClaude(t) ? "" : ` allow="clipboard-write"`} src="${esc(ttydUrl(t.arg))}" onload="unveil(this)"></iframe><i class="veil"></i>${consoleBar(t)}</div>`
      // Documents are not kept: they redraw from state in a millisecond, and
      // one per pane means one #docN, which is what renders into them.
      : `<div class="doc fx" id="doc${i}"></div>`);
    // The id names "the document being shown in pane i", so it must name one
    // node. A hidden document left in the stack (the notebook parks there)
    // used to keep it, and getElementById returns the first in DOM order,
    // so toolchains and findings rendered into a node nobody could see and the
    // pane sat blank.
    if (t.kind !== "term"){
      [...st.children].forEach(c => { if (c !== el && c.id) c.removeAttribute("id"); });
      el.id = "doc" + i;
    }
    // The console bar rides with its pane, so it is wired with it: the row is
    // replaced whenever the slot is, and a handler bound once would be bound
    // to a node nothing is looking at any more.
    wireConsole(el);
    el.querySelector("[data-reattach]")?.addEventListener("click", e => reattachTab(t.id, e));
    // Shown again after being hidden: xterm sizes itself from a resize event,
    // and one that was laid out behind another frame may have missed one. One
    // marked stale slept through a disconnect instead, and needs the reload it
    // was spared while nobody was looking at it.
    if (!fresh && t.kind === "term"){
      const f = el.querySelector("iframe");
      if (f?.dataset.stale){ delete f.dataset.stale; f.src = f.src; }
      else nudgeTerminals();
    }
    paintBar(pane, t, i);
    // ...and a pane that has just changed tab. Same decision, same place,
    // plus the kind's own open hook, which is what a tab restored from a saved
    // layout needs to fetch what it draws.
    renderDoc(i, t, pane);
    openedNow.add(t.id);
    TABKINDS[t.kind]?.open?.();
  }
}

// The notebook is *moved* into the pane rather than rendered into it. One
// instance, so every id inside stays unique and the staging model does not
// have to become per-pane, and moving it keeps whatever is half-typed in it,
// which re-rendering would not.
function renderNotebookInto(i, project){
  const host = $("doc" + i), nb = getNotebook(project);
  if (!host) return;
  host.classList.toggle("nbhost", true);
  if (nb.root.parentElement !== host) host.appendChild(nb.root);
  nbReadOnly(nb.root, project);
  nb.shown();
}

// A locked project's notebook opens and does not change. Applied on every draw
// rather than at open, because the lock can be turned while the tab is sitting
// there, and this kind renders from `state`, so every draw already happens.
//
// The class is the visible half; the refusal is server-side, in locked_out().
// A read-only state enforced by a dimmed button is a suggestion, and this page
// is not the only way to reach the endpoint behind it.
function nbReadOnly(root, project){
  const locked = !!(state?.projects || []).find(p => p.name === project)?.locked;
  root.classList.toggle("ro", locked);
  let note = root.querySelector(":scope > .rolock");
  if (!locked){ if (note) note.remove(); return; }
  if (!note){
    note = document.createElement("div");
    note.className = "rolock";
    root.prepend(note);
  }
  // Says what still works, not only what does not: the point of locking a
  // project is that everything you do yourself carries on.
  note.textContent = "Locked: roadmap, bugs and memories are read-only. Findings, "
    + "artifacts and the dev instance still work; the padlock on its row unlocks it.";
}

// Back to its holder when no tab is showing it, so a stale copy is never left
// inside a pane's stack for the next document to be drawn over.
// Every terminal tab on the strip stays attached, behind the one on screen,
// for as long as it is on the strip; Minimize (into the Sessions menu) or
// closing it is what detaches it, since a frame whose tab is gone is removed
// at the top of drawPanes (the operator, 6 Oct). It used to keep the three
// last seen, and picking a fourth reloaded it from nothing: its page, its
// socket, its attach. The strip's own cap (MAX_TABS, twelve terminal tabs an
// account) is the ceiling on browser memory now.
let stackClock = 0;

// A pane is a bar and a stack. The stack's children all sit on top of one
// another at the same size, and exactly one of them is visible, which is the
// whole trick: rebuilding a pane's innerHTML to change tabs threw the frame
// away, and ttyd is 700KB of javascript that then had to load, connect and
// draw again. A second and a half of blank pane, every switch.
//
// Same size, not merely present: a hidden frame is still an attached tmux
// client, and tmux sizes a window to its smallest one. Overlapping them keeps
// every client on the same geometry, so there is nothing to fight about.
function paneStack(pane){
  let st = pane.querySelector(".stack");
  if (!st){
    pane.innerHTML = `<div class="bar"></div><div class="stack"></div>`;
    st = pane.querySelector(".stack");
  }
  return st;
}

function showInStack(st, key, html){
  let el = [...st.children].find(c => c.dataset.key === key);
  const fresh = !el;
  if (fresh){
    st.insertAdjacentHTML("beforeend", html());
    el = st.lastElementChild;
    el.dataset.key = key;
  }
  el.dataset.seen = String(++stackClock);
  for (const c of st.children) c.classList.toggle("on", c === el);
  return { el, fresh };
}

// Terminals only, oldest gone first: a document is one per pane already, and
// costs nothing to rebuild. The visible one is counted rather than exempted:
// when the pane is showing a document, all three terminals behind it are
// hidden, and exempting "the visible slot" then kept one fewer than it says.
function dropElsewhere(keep, key){
  for (let j = 0; j < 2; j++){
    if (j === keep) continue;
    [...($("pane" + j).querySelector(".stack")?.children || [])]
      .filter(c => c.dataset.key === key)
      .forEach(c => c.remove());
  }
}

// Two browsers attached to one tmux session fight over its size: tmux sizes a
// window to whichever client used it last, and paints the spare rows of the
// bigger client with dots until that client does something. The terminal is
// served from its own port, so we cannot ask it to refit, but resizing its
// frame makes it refit itself, and the size comes back here.
//
// Done when this page returns to the front, which is exactly when the other
// device has been the one using it.
let nudgeTimer = null, nudgedAt = 0;
function nudgeTerminals(){
  // The visible ones only. A pane keeps three more frames alive behind the one
  // on screen, and they are all the same size already: thrashing their layout
  // costs a reflow each and fixes nothing anybody is looking at.
  const frames = [...document.querySelectorAll(".pane .slot.on iframe")];
  if (!frames.length) return;
  // Focus comes back to this page every time a click leaves a terminal, and
  // this is a layout thrash: often enough to matter on a phone, and pointless
  // more than once in a moment.
  if (Date.now() - nudgedAt < 1500) return;
  nudgedAt = Date.now();
  clearTimeout(nudgeTimer);
  frames.forEach(f => f.style.width = "calc(100% - 1px)");
  // A frame has to be laid out at the new width for the resize to reach the
  // document inside it, so this cannot be folded into an animation frame.
  nudgeTimer = setTimeout(() => frames.forEach(f => f.style.width = ""), 60);
}

// Reconnecting a dropped terminal. ttyd auto-reconnects on its own, except
// on a phone, which freezes the whole page while it is backgrounded (so
// ttyd's timer never fires) and often restores it from the back/forward cache
// with the socket already dead, showing ttyd's "reconnect" prompt. The
// terminal is a cross-origin iframe we cannot reach into, but reloading it is
// lossless: tmux holds the session and its scrollback on the server, so the
// reload reattaches exactly where it was.
let hiddenAt = 0;
function reattachTerminals(){
  // What is on screen reloads now; what is behind it is marked and reloads
  // when it is next shown. Reloading all of them together was up to six ttyd
  // instances (700KB of javascript, a websocket and a full repaint each)
  // starting at the same moment on the device least able to afford it, which
  // is what a phone spent its first seconds back doing.
  document.querySelectorAll(".pane .slot:not(.on) iframe")
          .forEach(f => f.dataset.stale = "1");
  document.querySelectorAll(".pane .slot.on iframe").forEach(f => { f.src = f.src; });
}
