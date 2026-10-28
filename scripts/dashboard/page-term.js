// BuilderBot's own terminal (R133): a dock tab drawn by xterm.js in the page
// itself, joined to /termws. One classic script beside index.html
// (docs/nodes.md §13); terminal.html is the same terminal on a page of its
// own, for a tab popped out and for the Android app.
//
// The server decides everything a terminal is (whose, whether, where); this
// is the screen and the keyboard. The wire is binary frames: to the server
// a type byte (0 keys, 1 a resize as JSON cols/rows) and its body, from it
// the terminal's bytes. A close says why the terminal ended, shown in its
// tab with Reconnect. A socket that drops (a phone asleep, the network) is
// opened again when the page is back in view: tmux redraws the screen as it
// attaches, so nothing is lost.

"use strict";

// Each terminal on the page, by its slot's key: {t, el, term, fit, ws, ended}.
const TERMS = new Map();
let xtermLoading = null;

// Whether this tab is a terminal drawn here: not a VM's screen (noVNC's, in
// a frame) and not popped out into its own window.
function termOwn(t){
  if (t?.kind === "term" && termLog(t)) return true;
  return t?.kind === "term" && !t.popped && !/^screen:/.test(t.arg || "");
}

// A log tab's argument (log:job:ID, log:controller): read-only, followed.
function termLog(t){ return /^log:/.test(t?.arg || ""); }

// A log opened in the dock, followed as it is written (R133 step 12).
function openLogTab(arg, label){
  openTab({kind: "term", arg, label});
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

// The URL the socket opens: the tab's words, boot stamp and all, and the
// size it starts at.
function termUrl(t, cols, rows){
  const q = new URLSearchParams();
  q.append("arg", termArg(t.arg));
  q.set("cols", cols); q.set("rows", rows);
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/termws?${q}`;
}

// A terminal's colors by name (R133 step 10), the choices prefs.py's
// TERM_SCHEMES names: Default the plain dark ground, Dashboard the page's
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

// What every scheme is laid over: xterm's own ground and the Tango ANSI
// colors it ships, so a scheme names only what it changes and every color
// has a value to show and to change (the operator, 25 Oct).
const TERM_BASE = {background: "#2b2b2b", foreground: "#e6e6e6", cursor: "#e6e6e6", selectionBackground: "#5a5a5a",
  black: "#2e3436", red: "#cc0000", green: "#4e9a06", yellow: "#c4a000", blue: "#3465a4", magenta: "#75507b",
  cyan: "#06989a", white: "#d3d7cf", brightBlack: "#555753", brightRed: "#ef2929", brightGreen: "#8ae234",
  brightYellow: "#fce94f", brightBlue: "#729fcf", brightMagenta: "#ad7fa8", brightCyan: "#34e2e2", brightWhite: "#eeeeec"};
// Each color as a person reads it, in the order the Profile lays them out:
// the four of the terminal itself, then the eight ANSI colors and their
// bright halves (users.py TERM_COLORS).
const TERM_COLOR_NAMES = [["background", "Ground"], ["foreground", "Text"], ["cursor", "Cursor"], ["selectionBackground", "Selection"],
  ["black", "Black"], ["red", "Red"], ["green", "Green"], ["yellow", "Yellow"], ["blue", "Blue"], ["magenta", "Magenta"], ["cyan", "Cyan"], ["white", "White"],
  ["brightBlack", "Bright black"], ["brightRed", "Bright red"], ["brightGreen", "Bright green"], ["brightYellow", "Bright yellow"],
  ["brightBlue", "Bright blue"], ["brightMagenta", "Bright magenta"], ["brightCyan", "Bright cyan"], ["brightWhite", "Bright white"]];

// A scheme's whole palette: the base, the preset over it, and this
// person's own changes to that preset over both.
function termPalette(scheme, mine){
  const css = getComputedStyle(document.documentElement);
  const preset = scheme === "dashboard"
    ? {background: css.getPropertyValue("--bg").trim(), foreground: css.getPropertyValue("--ink").trim(),
       cursor: css.getPropertyValue("--accent").trim()}
    : TERM_SCHEMES[scheme] || TERM_SCHEMES.default;
  return {...TERM_BASE, ...preset, ...(mine || {})};
}

// A terminal drawn small in a palette, for a person to see before one opens
// (the operator, 25 Oct): a prompt, a listing in the ANSI colors, every
// color as a block, a selection and the cursor in its shape.
function termPreview(theme, look = {}){
  const c = k => esc(theme[k] || "");
  const sp = (k, t) => `<span data-style="color:${c(k)}">${esc(t)}</span>`;
  const blocks = keys => keys.map(k => `<span class="tpblock" data-style="background:${c(k)}" title="${esc(k)}"></span>`).join("");
  const cur = look.cursor || "block";
  const cursor = cur === "bar" ? `<span class="tpcur bar" data-style="border-color:${c("cursor")}"></span>`
    : cur === "underline" ? `<span class="tpcur under" data-style="border-color:${c("cursor")}">&nbsp;</span>`
    : `<span class="tpcur" data-style="background:${c("cursor")}">&nbsp;</span>`;
  return `<div class="termprev" role="img" aria-label="how a terminal looks in these colors"
      data-style="background:${c("background")};color:${c("foreground")};font-size:${Number(look.size) || 13}px">
    <div>${sp("green", "you@node")}:${sp("blue", "~/alpha")}$ ls</div>
    <div>${sp("blue", "src")}  ${sp("green", "build.sh")}  ${sp("cyan", "docs")}  ${sp("red", "core")}  ${sp("yellow", "notes.md")}  ${sp("magenta", "logo.png")}</div>
    <div>${blocks(["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"])}</div>
    <div>${blocks(["brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite"])}</div>
    <div><span data-style="background:${c("selectionBackground")}">a selection</span> and the cursor ${cursor}</div>
  </div>`;
}

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
  const theme = termPalette(scheme, (look.colors || {})[scheme]);
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
    // A log takes no keys: there is no program behind it to read them.
    if (termLog(t)) term.options.disableStdin = true;
    else {
      term.onData(d => termType(rec, new TextEncoder().encode(d)));
      term.onBinary(d => termType(rec, Uint8Array.from(d, c => c.charCodeAt(0))));
    }
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
// PgUp moves it by the page.
function termScroll(rec, n, at){
  if (rec.term.modes.mouseTrackingMode !== "none"){
    const scr = rec.el.querySelector(".xterm-screen");
    for (let i = 0; i < Math.abs(n); i++)
      scr.dispatchEvent(new WheelEvent("wheel", {deltaY: Math.sign(n), deltaMode: 1, clientX: at.clientX,
        clientY: at.clientY, bubbles: true, cancelable: true}));
    return;
  }
  // A key a line (TERM_LINE_UP and TERM_LINE_DOWN, tmux's own keys from
  // lib/tmux-keys.conf), down the socket: copy mode entered going up and
  // ended by itself at the bottom.
  if (!n) return;
  termSend(rec, 0, new TextEncoder().encode((n < 0 ? TERM_LINE_UP : TERM_LINE_DOWN).repeat(Math.min(Math.abs(n), 200))));
  if (n < 0) termScrolled.add(rec.t.id);
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

// What is typed, from the keyboard or the keys bar, for the program: a
// pane this page scrolled back into tmux's copy mode leaves it first, where
// an arrow moved tmux's cursor over the history and a letter did nothing,
// and the program heard neither (B254). The leaving is tmux's own key for
// it (TERM_LEAVE, lib/tmux.conf), sent down the same socket ahead of what
// is typed, so it lands first. Marked on the tab, so a pane the server
// scrolled before the socket opened counts too: by its id, since the
// layout's tab and the terminal's may be two objects for one tab.
const termScrolled = new Set();
const TERM_LEAVE = "\x1b[9001~", TERM_LINE_UP = "\x1b[9002~", TERM_LINE_DOWN = "\x1b[9003~";
function termType(rec, bytes){
  if (termScrolled.delete(rec.t.id)){
    termSend(rec, 0, new TextEncoder().encode(TERM_LEAVE));
  }
  termSend(rec, 0, bytes);
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

// The keys bar's keys as a keyboard sends them (R133 step 5): a table, as
// everything the page can make happen is, never text from elsewhere.
const TERM_KEYS = {escape: "\x1b", tab: "\t", left: "\x1b[D", down: "\x1b[B", up: "\x1b[A", right: "\x1b[C",
  home: "\x1b[H", end: "\x1b[F", enter: "\r", bspace: "\x7f", pipe: "|", tilde: "~", slash: "/", backslash: "\\",
  dash: "-", under: "_", dollar: "$", star: "*", lt: "<", gt: ">", amp: "&", caret: "^", "brace-l": "{", "brace-r": "}"};

// A key pressed on the bar, for this tab's terminal: true when it went,
// false for one it does not take (no socket). PgUp and PgDn scroll a page,
// as a finger's drag does; the rest are typed.
function termKey(t, key){
  const rec = [...TERMS.values()].find(r => r.t.id === t.id && r.el.isConnected);
  if (!rec || rec.ws?.readyState !== WebSocket.OPEN) return false;
  if (key === "pgup" || key === "pgdn"){
    const b = rec.el.querySelector(".xterm-screen")?.getBoundingClientRect();
    termScroll(rec, (key === "pgup" ? -1 : 1) * Math.max(1, rec.term.rows - 1),
               {clientX: b ? b.left + b.width / 2 : 0, clientY: b ? b.top + b.height / 2 : 0});
    return true;
  }
  const m = /^ctrl-([a-z])$/.exec(key);
  const s = m ? String.fromCharCode(m[1].charCodeAt(0) - 96) : TERM_KEYS[key];
  if (s === undefined) return false;
  termType(rec, new TextEncoder().encode(s));
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
