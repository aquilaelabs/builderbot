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
    termTouch(rec);
    termConnect(rec);
  }, e => termEnded(rec, String(e.message || e)));
}

// A finger on the terminal (R133 step 11): a drag up and down scrolls it
// and a press held selects the word under it, with handles and Copy; a tap
// is left to xterm.js, which focuses it for the keyboard.
function termTouch(rec){
  const host = rec.el.querySelector(".xhost");
  let g = null;
  // A touch's moves and lift go to the element it began on, and xterm.js
  // redraws its rows under the finger: off the page, that element passes
  // nothing up to the host. So a gesture, once begun here, is followed on
  // the window until it lifts.
  const move = e => {
    if (!g) return;
    const p = e.touches[0];
    if (g.held){ e.preventDefault(); e.stopPropagation(); return; }
    if (!g.moved && Math.hypot(p.clientX - g.x, p.clientY - g.y) < 8) return;
    g.moved = true;
    clearTimeout(g.hold);
    e.preventDefault(); e.stopPropagation();
    // A finger going up brings the newer lines, as a page under it would.
    g.acc += g.last - p.clientY; g.last = p.clientY;
    const h = termCell(rec).h, n = Math.trunc(g.acc / h);
    if (n){ g.acc -= n * h; termScroll(rec, n, p); }
  };
  const end = e => {
    window.removeEventListener("touchmove", move, {capture: true});
    window.removeEventListener("touchend", end, {capture: true});
    window.removeEventListener("touchcancel", end, {capture: true});
    if (!g) return;
    clearTimeout(g.hold);
    // Neither a drag nor a hold ends as a tap on what was under it, and the
    // mouse events the browser makes of a held press as it lifts would
    // start xterm.js's own selection over ours: held off for a moment.
    if (g.moved || g.held){ e.preventDefault(); e.stopPropagation(); }
    if (g.held) rec.quietUntil = performance.now() + 700;
    g = null;
  };
  host.addEventListener("touchstart", e => {
    if (e.touches.length !== 1 || e.target.closest(".xsel")) return;
    const p = e.touches[0];
    if (rec.sel) termSelectEnd(rec);
    g = {x: p.clientX, y: p.clientY, last: p.clientY, acc: 0, moved: false, held: false};
    g.hold = setTimeout(() => { if (!g || g.moved) return; g.held = true; termSelectAt(rec, g.x, g.y); }, 500);
    window.addEventListener("touchmove", move, {capture: true, passive: false});
    window.addEventListener("touchend", end, {capture: true, passive: false});
    window.addEventListener("touchcancel", end, {capture: true, passive: false});
  }, {capture: true, passive: true});
  // ...and, where the browser says so, any mouse event made of a touch while
  // our selection is up: the lift can come late, or not reach us at all.
  host.addEventListener("mousedown", e => {
    if (performance.now() < (rec.quietUntil || 0) || (rec.sel && e.sourceCapabilities?.firesTouchEvents)){
      e.preventDefault(); e.stopPropagation();
    }
  }, {capture: true});
  // The phone's own menu on a held press is ours to replace.
  host.addEventListener("contextmenu", e => { if (matchMedia("(pointer: coarse)").matches) e.preventDefault(); });
}

// One cell's size and the screen's box, from what xterm.js drew.
function termCell(rec){
  const scr = rec.el.querySelector(".xterm-screen"), b = scr.getBoundingClientRect();
  return {w: b.width / rec.term.cols, h: b.height / rec.term.rows, b};
}

// Lines scrolled (more than nought: toward the newest). Where the pane takes
// the mouse (a coding agent's, tmux's mouse on) a drag is the wheel it would
// be at a desk; otherwise (a shell) tmux's history moves by the line, as
// PgUp moves it by the page, asked of the server in batches.
function termScroll(rec, n, at){
  if (rec.term.modes.mouseTrackingMode !== "none"){
    const scr = rec.el.querySelector(".xterm-screen");
    for (let i = 0; i < Math.abs(n); i++)
      scr.dispatchEvent(new WheelEvent("wheel", {deltaY: Math.sign(n), deltaMode: 1, clientX: at.clientX,
        clientY: at.clientY, bubbles: true, cancelable: true}));
    return;
  }
  rec.scrollBy = (rec.scrollBy || 0) + n;
  if (rec.scrollSend) return;
  rec.scrollSend = setTimeout(async () => {
    const by = rec.scrollBy;
    rec.scrollBy = 0; rec.scrollSend = null;
    if (!by) return;
    try{
      await postJSON("/api/keys", {session: sessionOf(rec.t.arg), key: by < 0 ? "lineup" : "linedown", lines: Math.abs(by)});
    }catch(e){ /* the next drag asks again */ }
  }, 80);
}

// The cell under a point, as a place in the buffer counted in cells.
function termPos(rec, x, y){
  const c = termCell(rec), buf = rec.term.buffer.active;
  const col = Math.max(0, Math.min(rec.term.cols - 1, Math.floor((x - c.b.left) / c.w)));
  const row = Math.max(0, Math.min(rec.term.rows - 1, Math.floor((y - c.b.top) / c.h)));
  return (buf.viewportY + row) * rec.term.cols + col;
}

// A held press: the word under it selected, its ends' handles and Copy drawn.
function termSelectAt(rec, x, y){
  const cols = rec.term.cols, at = termPos(rec, x, y), row = Math.floor(at / cols);
  const text = rec.term.buffer.active.getLine(row)?.translateToString(false) || "";
  let a = at % cols, b = a;
  if (/\S/.test(text[a] || "")){
    while (a > 0 && /\S/.test(text[a - 1])) a--;
    while (b < cols - 1 && /\S/.test(text[b + 1] || "")) b++;
  }
  rec.sel = {a: row * cols + a, b: row * cols + b};
  if (navigator.vibrate) navigator.vibrate(10);
  termSelectDraw(rec);
}

function termSelectDraw(rec){
  const s = rec.sel, cols = rec.term.cols;
  const lo = Math.min(s.a, s.b), hi = Math.max(s.a, s.b);
  rec.term.select(lo % cols, Math.floor(lo / cols), hi - lo + 1);
  const host = rec.el.querySelector(".xhost");
  let layer = host.querySelector(".xsel");
  if (!layer){
    layer = document.createElement("div");
    layer.className = "xsel";
    layer.innerHTML = `<span class="xgrip" data-end="a"></span><span class="xgrip" data-end="b"></span>
      <span class="xselbar"><button type="button" class="xcopy">Copy</button><button type="button" class="xdone">Done</button></span>`;
    host.append(layer);
    layer.querySelector(".xcopy").onclick = () => termCopy(rec);
    layer.querySelector(".xdone").onclick = () => termSelectEnd(rec);
    for (const grip of layer.querySelectorAll(".xgrip")){
      grip.addEventListener("touchmove", e => {
        e.preventDefault(); e.stopPropagation();
        const p = e.touches[0];
        rec.sel[grip.dataset.end] = termPos(rec, p.clientX, p.clientY - termCell(rec).h);
        termSelectDraw(rec);
      }, {passive: false});
    }
  }
  // Each grip under its end's cell: a at the start's left, b at the end's right.
  const c = termCell(rec), hb = host.getBoundingClientRect(), top = rec.term.buffer.active.viewportY;
  const place = (pos, right) => {
    const row = Math.floor(pos / cols) - top, col = pos % cols + (right ? 1 : 0);
    return {x: c.b.left - hb.left + col * c.w, y: c.b.top - hb.top + (row + 1) * c.h};
  };
  const pa = place(s.a <= s.b ? s.a : s.b, false), pb = place(s.a <= s.b ? s.b : s.a, true);
  const [ga, gb] = layer.querySelectorAll(".xgrip");
  const [first, last] = s.a <= s.b ? [ga, gb] : [gb, ga];
  first.style.left = `${pa.x}px`; first.style.top = `${pa.y}px`;
  last.style.left = `${pb.x}px`; last.style.top = `${pb.y}px`;
  // Copy above the selection, or under it where the top has no room.
  const bar = layer.querySelector(".xselbar"), above = pa.y - c.h - bar.offsetHeight - 4;
  bar.style.top = `${above >= 0 ? above : pb.y + 18}px`;
  bar.style.left = `${Math.max(0, Math.min(hb.width - bar.offsetWidth, pa.x))}px`;
}

// The selected text, read off the buffer between the record's ends: a
// wrapped line runs on, any other ends with a newline.
function termSelText(rec){
  const cols = rec.term.cols, buf = rec.term.buffer.active;
  const lo = Math.min(rec.sel.a, rec.sel.b), hi = Math.max(rec.sel.a, rec.sel.b);
  let out = "";
  for (let row = Math.floor(lo / cols); row <= Math.floor(hi / cols); row++){
    const line = buf.getLine(row);
    if (!line) continue;
    const from = row === Math.floor(lo / cols) ? lo % cols : 0;
    const to = row === Math.floor(hi / cols) ? hi % cols + 1 : cols;
    if (out && !line.isWrapped) out += "\n";
    out += line.translateToString(row !== Math.floor(hi / cols), from, to);
  }
  return out.replace(/[ \t]+$/gm, "");
}

async function termCopy(rec){
  if (!rec.sel) return;
  const text = termSelText(rec);
  try{
    await navigator.clipboard.writeText(text);
  }catch(e){
    // Not a secure page, or no permission: the old way, through a field.
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.append(ta); ta.select();
    try{ document.execCommand("copy"); }catch(e2){ /* nothing more to try */ }
    ta.remove();
  }
  notify("Copied");
  termSelectEnd(rec);
}

function termSelectEnd(rec){
  rec.sel = null;
  rec.term?.clearSelection();
  rec.el.querySelector(".xsel")?.remove();
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
