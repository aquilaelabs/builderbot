// BuilderBot's own terminal (R133): a dock tab drawn by xterm.js in the page
// itself, joined to /termws, in place of ttyd's page in a frame. One classic
// script beside index.html (docs/nodes.md §13).
//
// The server decides everything a terminal is (whose, whether, where) as it
// does for ttyd's; this is the screen and the keyboard. The wire is binary
// frames: to the server a type byte (0 keys, 1 a resize as JSON cols/rows)
// and its body, from it the terminal's bytes. A close says why the terminal
// ended, shown in its tab with Reconnect; 4001 says the tab's node serves no
// terminal of its own yet, and that tab opens through ttyd instead. A socket
// that drops (a phone asleep, the network) is opened again when the page is
// back in view: tmux redraws the screen as it attaches, so nothing is lost.
// Behind the own_terminal switch (a dev feature until walked); off, every
// tab is ttyd's as before.

"use strict";

// Each terminal on the page, by its slot's key: {t, el, term, fit, ws, ended}.
const TERMS = new Map();
let xtermLoading = null;

// Whether this tab is drawn here rather than by ttyd: the switch on, a
// terminal (not a VM's screen, which is noVNC's), not popped out, and not a
// tab its node sent back to ttyd.
function termOwn(t){
  return !!state?.term_own && t?.kind === "term" && !t.popped && !t.ttyd && !/^screen:/.test(t.arg || "");
}

// xterm.js and its fit addon, fetched once, when the first such tab opens:
// a page that never opens one never loads them.
function xtermReady(){
  if (window.Terminal && window.FitAddon) return Promise.resolve();
  if (xtermLoading) return xtermLoading;
  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/vendor/xterm.css";
  document.head.append(css);
  const script = src => new Promise((ok, no) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = () => no(new Error(`${src} did not load`));
    document.head.append(s);
  });
  xtermLoading = script("/vendor/xterm.js").then(() => script("/vendor/addon-fit.js"))
    .catch(e => { xtermLoading = null; throw e; });
  return xtermLoading;
}

// The slot a tab of ours is drawn in: the terminal's box, the line that
// says why it ended, and the console bar a read-only tab carries.
function termSlot(t){
  return `<div class="slot ownterm"><div class="xhost" aria-label="${esc(tabLabel(t))}"></div>
    <div class="xend" hidden><span class="xwhy"></span><button type="button" class="xagain">Reconnect</button></div>${consoleBar(t)}</div>`;
}

// The URL the socket opens: the tab's argument as ttyd's page was given it,
// boot stamp and all, and the size it starts at.
function termUrl(t, cols, rows){
  const u = new URL(ttydUrl(t.arg), location.href);
  const q = new URLSearchParams();
  for (const a of u.searchParams.getAll("arg")) q.append("arg", a);
  q.set("cols", cols); q.set("rows", rows);
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/termws?${q}`;
}

// A terminal's colors by name (R133 step 10), the choices prefs.py's
// TERM_SCHEMES names: Default the ground ttyd's page had, Dashboard the page's
// own scheme, and the tints a person gives a project to know it by. Literal
// here as a terminal's palette is: these are what the program's own
// colors are drawn on, not the page's surfaces.
const TERM_SCHEMES = {
  default: {background: "#2b2b2b"},
  amber: {background: "#2a2110", foreground: "#f3e6c8", cursor: "#f0b44c"},
  blue: {background: "#121c2c", foreground: "#dbe6f5", cursor: "#6ea8fe"},
  green: {background: "#122417", foreground: "#d8f0dc", cursor: "#5fd27a"},
  light: {background: "#fafafa", foreground: "#24292f", cursor: "#24292f", selectionBackground: "#c8d7f0",
          black: "#24292f", white: "#6e7781", brightWhite: "#8c959f"},
  red: {background: "#2c1416", foreground: "#f5dcdc", cursor: "#ff6b6b"},
};

// The project a terminal's argument is about, for its person's colors there.
function termProject(arg){
  const a = String(arg || "");
  const ag = agentOfArg(a);
  if (ag) return ag.project;
  const m = /^(?:sh:\d+:|shell:|vm:)([^:]+)/.exec(a);
  return m ? m[1] : "";
}

// This person's look for this tab: their Profile's, and the colors they
// gave its project over the Profile's (prefs' term_scheme).
function termLook(t){
  const look = state?.term_look || {}, row = (state?.projects || []).find(p => p.name === termProject(t.arg));
  const scheme = row?.yours?.term_scheme || look.scheme || "default";
  const css = getComputedStyle(document.documentElement);
  const theme = scheme === "dashboard"
    ? {background: css.getPropertyValue("--bg").trim(), foreground: css.getPropertyValue("--ink").trim(),
       cursor: css.getPropertyValue("--accent").trim()}
    : TERM_SCHEMES[scheme] || TERM_SCHEMES.default;
  return {fontSize: look.size || 13, cursorStyle: look.cursor || "block", cursorBlink: look.blink !== false, theme};
}

// The look applied to a terminal when it changed: a Profile saved, a
// project's colors picked, the page's scheme switched.
function termRestyle(rec){
  if (!rec?.term) return;
  const look = termLook(rec.t), was = JSON.stringify(look);
  if (rec.look === was) return;
  rec.look = was;
  Object.assign(rec.term.options, look);
  rec.el.style.background = look.theme.background || "";
  termFit(rec);
}

// A slot just drawn (or drawn again): its terminal made once, and kept
// while the slot is kept, as the frames were.
function termMount(el, t, key){
  let rec = TERMS.get(key);
  if (rec && rec.el === el){ rec.t = t; termRestyle(rec); return termFit(rec); }
  if (rec) termDrop(key);
  rec = {t, el, key, term: null, fit: null, ws: null, ended: ""};
  TERMS.set(key, rec);
  el.querySelector(".xagain").onclick = () => termConnect(rec);
  xtermReady().then(() => {
    if (TERMS.get(key) !== rec) return;
    const term = new window.Terminal({
      scrollback: 5000, fontFamily: getComputedStyle(document.body).getPropertyValue("--mono") || "monospace",
      allowProposedApi: false, ...termLook(t)});
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(el.querySelector(".xhost"));
    rec.term = term; rec.fit = fit; rec.look = "";
    termRestyle(rec);
    term.onData(d => termSend(rec, 0, new TextEncoder().encode(d)));
    term.onBinary(d => termSend(rec, 0, Uint8Array.from(d, c => c.charCodeAt(0))));
    term.onResize(({cols, rows}) => termSend(rec, 1, new TextEncoder().encode(JSON.stringify({cols, rows}))));
    // Its box changes size with the pane, the dock and the keyboard.
    rec.ro = new ResizeObserver(() => termFit(rec));
    rec.ro.observe(el.querySelector(".xhost"));
    termFit(rec);
    termConnect(rec);
  }, e => termEnded(rec, String(e.message || e)));
}

function termSend(rec, kind, body){
  if (rec.ws?.readyState !== WebSocket.OPEN) return;
  const b = new Uint8Array(body.length + 1);
  b[0] = kind; b.set(body, 1);
  rec.ws.send(b);
}

function termFit(rec){
  if (!rec?.fit || !rec.el.isConnected || !rec.el.offsetParent) return;
  try{ rec.fit.fit(); }catch(e){ /* a box with no size yet */ }
}

// Open (or open again) the tab's socket. A reconnect re-attaches the tmux
// session, which redraws its screen.
function termConnect(rec){
  if (!rec.term) return;
  try{ rec.ws?.close(); }catch(e){ /* already gone */ }
  rec.ended = "";
  rec.el.querySelector(".xend").hidden = true;
  rec.term.reset();
  const ws = new WebSocket(termUrl(rec.t, rec.term.cols, rec.term.rows));
  ws.binaryType = "arraybuffer";
  rec.ws = ws;
  ws.onmessage = e => { if (rec.ws === ws) rec.term.write(new Uint8Array(e.data)); };
  ws.onclose = e => {
    if (rec.ws !== ws) return;
    // A node not yet updated: this tab is ttyd's, drawn again as a frame.
    if (e.code === 4001){
      rec.t.ttyd = true;
      termDrop(rec.key);
      drawPanes();
      return;
    }
    termEnded(rec, e.reason || (e.code === 1006 ? "the connection dropped" : "the terminal ended"));
  };
}

// Why it ended, under the screen, with Reconnect. A drop rather than an
// end is opened again by termRevive when the page is back in view.
function termEnded(rec, why){
  rec.ended = why;
  const end = rec.el.querySelector(".xend");
  end.querySelector(".xwhy").textContent = why;
  end.hidden = false;
}

function termDrop(key){
  const rec = TERMS.get(key);
  if (!rec) return;
  TERMS.delete(key);
  try{ rec.ws?.close(); }catch(e){ /* gone */ }
  rec.ro?.disconnect();
  try{ rec.term?.dispose(); }catch(e){ /* gone */ }
}

// The keys bar's keys as a keyboard sends them (R133 step 5).
const TERM_KEYS = {escape: "\x1b", tab: "\t", left: "\x1b[D", down: "\x1b[B", up: "\x1b[A", right: "\x1b[C",
  home: "\x1b[H", end: "\x1b[F", enter: "\r", pipe: "|", tilde: "~", slash: "/", backslash: "\\", dash: "-",
  under: "_", dollar: "$", star: "*", lt: "<", gt: ">"};

// A key pressed on the bar, typed into this tab's terminal: true when it
// went, false for one it does not type (the server's, or no socket).
function termKey(t, key){
  const rec = [...TERMS.values()].find(r => r.t.id === t.id && r.el.isConnected);
  const m = /^ctrl-([a-z])$/.exec(key);
  const s = m ? String.fromCharCode(m[1].charCodeAt(0) - 96) : TERM_KEYS[key];
  if (!rec || s === undefined || rec.ws?.readyState !== WebSocket.OPEN) return false;
  termSend(rec, 0, new TextEncoder().encode(s));
  rec.term?.focus();
  return true;
}

// After each draw: a terminal whose slot left the page is closed, as a
// frame removed from it was, and the rest take a look that changed (a
// Profile saved, a project's colors picked), which a pane the draw left as
// it was would not otherwise be given.
function termSweep(){
  for (const [key, rec] of TERMS){
    if (!rec.el.isConnected) termDrop(key);
    else termRestyle(rec);
  }
}

// The page back in view, or its panes resized: every terminal sized to its
// box, and one whose socket dropped meanwhile opened again.
function termRevive(){
  for (const rec of TERMS.values()){
    termFit(rec);
    if (rec.term && rec.ended === "the connection dropped") termConnect(rec);
  }
}
