// The on-screen keys, and the phone's panels: the key bar a touch device
// types with, and the panels (keys, macros, sessions, chat) that slide up
// from the phone's own bar.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- keys ------------------------------------------------------------

const KEYS = [
  [["escape","Esc"],["tab","Tab"],["left","←"],["down","↓"],["up","↑"],["right","→"],
   ["home","Home"],["end","End"],["pgup","PgUp"],["pgdn","PgDn"]],
  [["ctrl-c","^C"],["ctrl-d","^D"],["ctrl-z","^Z"],["ctrl-l","^L"],["ctrl-r","^R"],
   ["ctrl-a","^A"],["ctrl-e","^E"],["ctrl-u","^U"],["ctrl-w","^W"],["enter","⏎"]],
  [["pipe","|"],["tilde","~"],["slash","/"],["backslash","\\"],["dash","-"],
   ["under","_"],["dollar","$"],["star","*"],["lt","<"],["gt",">"]],
];

// The phone's second panel. Keys and macros are exclusive there; see the
// toggles below, and the macro lists are the dashboard's own #commands and
// The lists used to be moved between their sidebar cards and this panel every
// time the viewport crossed the phone breakpoint. They just live here now, at
// every width: one DOM, one set of handlers, and no breakpoint to be on the
// wrong side of.
let showMacros = false, showSessions = false, showChat = false;

// One panel at a time on the phone: opening any of the three closes the others.
function mobPanel(which){
  const on = {keys: showKeys, macros: showMacros, sessions: showSessions,
              chat: showChat}[which];
  // The two panels always take turns: they are the same strip of space. The
  // keys row only joins that trade on a phone, where the three of them plus
  // a terminal do not fit, on a desktop it stays where it was put.
  if (which === "keys") showKeys = !on;
  else if (isPhone()) showKeys = false;
  showMacros = which === "macros" ? !on : false;
  showSessions = which === "sessions" ? !on : false;
  showChat = which === "chat" ? !on : false;
  if (showChat) loadChat();               // open on something, not on "loading…"
  render();
}

// Slide a bottom flyout open or shut on a phone instead of popping it.
//
// The slide happens as an OVERLAY: for its duration the panel is taken out
// of the flow and pinned above the bottom bar, growing (or shrinking) over
// the terminal, and only when it lands is it put back into the flow, so the
// terminal resizes once, in a single step, instead of the iframe reflowing
// and refitting on every frame of the tween underneath it. Opening: overlay,
// slide up, then snap the terminal shorter. Closing: overlay (the terminal
// snaps taller at once), slide down, then hide. State is tracked on the
// element, not read from the class: the class stays on while a close is
// still tweening, and every render passes through here.
//
// Returns a promise for the moment the slide lands (null when there was no
// slide). `swap` is that promise from another panel opening in the same
// render: a panel closing to make way for it does not slide down at all;
// it stays put, in the flow, under the new one growing over it, and is
// simply gone when the new one lands. Two slides at once looked like a
// collision, and closing first would have resized the terminal twice.
function slidePanel(el, show, swap){
  const was = el.dataset.shown === "1";
  el.dataset.shown = show ? "1" : "0";
  if (was === show) return null;
  // Interrupted mid-slide, the next slide starts from the height the panel
  // is at, not from one end: the second tap on a flyout reverses it.
  const running = el.getAnimations();
  const mid = running.length ? el.getBoundingClientRect().height : null;
  running.forEach(a => a.cancel());
  // Where it ends up is the difference between the two screens. On a phone it
  // lands IN the flow and the terminal gives up the height, because there is
  // not enough screen to cover one thing with another. On a desktop it never
  // lands: it stays an overlay, and the terminal keeps its size, which is
  // what a terminal wants, since a resize costs it a refit and a reflow of
  // everything on screen. The TWEEN is an overlay either way, or the iframe
  // would reflow on every frame of it.
  const overlay = !isPhone();
  if (show && overlay) el.classList.add("over");
  const pin = () => { el.style.bottom = $("mobar").offsetHeight + "px"; };
  const settle = () => {
    el.style.overflow = "";
    el.classList.remove("sliding");
    if (!overlay) el.style.bottom = "";        // an overlay stays pinned
  };
  const done = () => { if (!show) el.classList.remove("show", "over"); };
  if (noMotion()){
    if (overlay) pin();
    settle(); el.classList.toggle("show", show); done();
    return null;
  }
  // The one being replaced holds still at full height and is dropped when the
  // opener lands over it: cheaper than two tweens, and nothing shows through
  // between them. Only in the flow: two overlays would have to agree about
  // which is on top, which the z-index above already settles.
  if (!show && swap && !overlay){
    settle();                                   // full height, in the flow
    swap.then(() => { if (el.dataset.shown === "0") el.classList.remove("show"); });
    return null;
  }
  el.classList.add("show", "sliding");
  pin();                                        // pinned just above the bar
  const h = el.offsetHeight;
  el.style.overflow = "hidden";
  const anim = el.animate(show ? [{height: (mid ?? 0) + "px"}, {height: h + "px"}]
                               : [{height: (mid ?? h) + "px"}, {height: "0px"}],
                          {duration: 200, easing: "ease"});
  return new Promise(res => {
    anim.onfinish = () => {
      settle();                                 // into the flow, or staying put
      done();
      res();
    };
    // Canceled by a newer slide: whoever is waiting must not wait forever,
    // and must not act either: the newer slide owns the panel now.
    anim.oncancel = () => res();
  });
}

// A shell tab, and not a Claude one. Both are terminals, but the keys and the
// macros are for driving a shell: over Claude they type into a conversation
// that has its own idea of what a keystroke means, and over a document there
// is nothing to type into at all.
const isShellTab = t => t?.kind === "term" && !t.arg.startsWith("claude:");

function drawKeys(){
  const el = $("keys");
  const t = tabOf(panes[active]);
  const term = isShellTab(t);
  const on = showKeys && term;                   // pointless anywhere else
  // Content first, then the slide: the slide measures the panel, and the
  // first open used to measure it empty and land twelve pixels tall.
  if (on && paint(el, KEYS.map(r =>
      r.map(([k,l]) => `<button data-k="${esc(k)}">${esc(l)}</button>`).join("")
    ).join('<span class="gap"></span>')))
    el.querySelectorAll("[data-k]").forEach(b => b.onclick = () => sendKey(b.dataset.k));
  // Content is otherwise kept while a close tweens shut: emptying it
  // mid-slide would collapse an already-shrinking box to nothing.
  // Not there at all where there is no shell to type into (B460): ghosted,
  // Keys took a quarter of a phone's bar on every document tab and cut
  // Sessions and Commands short beside it, to say a thing nobody needed.
  const mk = $("mKeys");
  mk.classList.toggle("on", on);
  mk.hidden = !term;
  const mm = $("mMacros");
  mm.classList.toggle("on", showMacros);
  mm.hidden = !term;
  $("mSessions").classList.toggle("on", showSessions);
  const mc = $("mChat");
  mc.classList.toggle("on", showChat);
  // The dot is the whole reason the counts ride the status poll: a chat you
  // have to open to discover is one nobody opens.
  const waiting = Object.values(state?.chat?.unread || {}).reduce((a, b) => a + b, 0);
  mc.classList.toggle("unread", waiting > 0);
  mc.title = waiting ? `${waiting} unread` : "";
  drawChat();
  // One panel at a time: whichever is opening slides, and any that is
  // closing in the same breath swaps out under it (see slidePanel).
  // Commands closes with the keys when the tab underneath is not a shell: a
  // flyout of things to type, over something that cannot be typed into.
  const want = [[el, on], [$("macpanel"), showMacros && term],
                [$("sespanel"), showSessions], [$("chatpanel"), showChat]];
  const opener = want.find(([p, s]) => s && p.dataset.shown !== "1");
  const landed = opener ? slidePanel(opener[0], true) : null;
  for (const [p, s] of want) if (p !== opener?.[0]) slidePanel(p, s, landed);
}
