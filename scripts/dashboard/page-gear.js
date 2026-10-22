// The gear menu: what is this BROWSER's (the color scheme, the time zone)
// and the way to the account's Profile. Everything the controller owns
// lives on the Controller page instead (docs/nodes.md, section 13), the
// log settings drawn here (logSection) among them.
// One classic script beside index.html (docs/design-language.md, Files): pure
// declarations, nothing runs at load. The gear button and the listeners
// that close the menu are wired from index.html, under the logs header.

"use strict";

const THEMES = [
  ["default",  "Default"],
  ["abyss",    "Abyss"],    ["carbon",   "Carbon"],   ["ember", "Ember"],
  ["ice",      "Ice"],      ["moss",     "Moss"],     ["nocturne", "Nocturne"],
  ["nostromo", "Nostromo"], ["plum",     "Plum"],     ["rust",  "Rust"],
  ["sepia",    "Sepia"],    ["slate",    "Slate"],
];

const THEME_IDS = new Set(THEMES.map(t => t[0]));
// The time zone picked in the gear and not applied yet: this browser's (a
// cookie, userTZ), with its own Apply.
let tzDraft = null;

// The scheme's other half (R216): each has a dark and a light palette, and
// which is on is this switch: dark, light, or the device's own setting,
// followed as it changes. Kept exactly as the scheme is: in localStorage
// for the paint path and on the account for a browser that has none.
const MODES = [["dark", "Dark"], ["light", "Light"], ["system", "System"]];
const MODE_IDS = new Set(MODES.map(m => m[0]));
let modeSaved = null;
const modeMedia = window.matchMedia ? matchMedia("(prefers-color-scheme: light)") : null;

function currentMode(){
  let m = null;
  try{ m = localStorage.getItem("bb.mode"); }catch(e){ /* private mode */ }
  return MODE_IDS.has(m) ? m : "dark";
}

// What the page wears for a mode: "system" resolved against the device now.
const modeHalf = m => m === "light" || (m === "system" && modeMedia && modeMedia.matches) ? "light" : "dark";

function applyMode(id, {save = true} = {}){
  const use = MODE_IDS.has(id) ? id : "dark";
  const root = document.documentElement;
  const half = modeHalf(use);
  if (!noMotion() && (root.dataset.mode || "dark") !== half){
    root.classList.add("theming");
    clearTimeout(themingTimer);
    themingTimer = setTimeout(() => root.classList.remove("theming"), 320);
  }
  if (half === "light") root.dataset.mode = "light";
  else delete root.dataset.mode;
  if (!save) return;
  try{ localStorage.setItem("bb.mode", use); localStorage.setItem("bb.mode.who", state?.me || ""); }catch(e){ /* private mode */ }
  modeSaved = use;
  fetch("/api/users", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "prefs", prefs: { mode: use } }) })
    .catch(() => {});
  markUiMenu();
}

// The account's mode, taken up only by a browser that has none of its own:
// adoptTheme's rule, for the same reasons.
function adoptMode(m, who){
  let had, whose;
  try{
    had = localStorage.getItem("bb.mode"); whose = localStorage.getItem("bb.mode.who");
  }catch(e){ return; }
  const same = !who || !had || (whose || "") === who;
  if (had && same) return;
  const use = MODE_IDS.has(m) ? m : "dark";
  if (same && (!m || use === modeSaved)) return;
  modeSaved = use;
  applyMode(use);
}

// "System" follows the device as it changes, without a reload.
if (modeMedia) modeMedia.addEventListener("change", () => {
  if (currentMode() === "system") applyMode("system", {save: false});
});

// The browser holds it and the ACCOUNT remembers it, and the order matters
// (roadmap #25). localStorage is the only way to have no flash: applied from
// the inline block in <head>, before the first paint, where a value fetched
// from the server cannot be. So it stays the paint path and is written on
// every pick.
//
// The account record is what a browser that has never seen this account reads
// instead of starting on the default: the scheme follows the person rather
// than the machine. But only then: a value already in localStorage WINS,
// because which colors are comfortable is partly about the room you are
// sitting in, and a phone in the dark that picked Nocturne must not have it
// undone by the desktop at noon. adoptTheme is the whole of that rule.
let themingTimer = null;

function applyTheme(id){
  const use = THEME_IDS.has(id) ? id : "default";
  // Default carries no attribute at all, so its palette is the :root one and
  // there is nothing to strip if every scheme is ever removed.
  const root = document.documentElement;
  // Crossfade, by giving the page a color transition for as long as the swap
  // takes and no longer. A standing transition on every element would be the
  // easy version and the wrong one: it would also slow every hover, every row
  // turning green and every state light on the page, all to make one rare
  // action look nicer. So it is switched on for the swap and off again.
  //
  // The custom properties themselves do not animate, since a var flips at once,
  // but the computed background, text and border colors that read them do,
  // which is the whole picture except the terminal, whose iframe is another
  // document with its own styling and cannot be reached from here.
  if (!noMotion() && root.dataset.theme !== (use === "default" ? undefined : use)){
    root.classList.add("theming");
    clearTimeout(themingTimer);
    themingTimer = setTimeout(() => root.classList.remove("theming"), 320);
  }
  if (use === "default") delete root.dataset.theme;
  else root.dataset.theme = use;
  applyMode(currentMode(), {save: false});
  // ...with whose it is (B491): a browser's choice wins for the account
  // that made it, and another account signing in here gets its own.
  try{ localStorage.setItem("bb.theme", use); localStorage.setItem("bb.theme.who", state?.me || ""); }catch(e){ /* private mode */ }
  themeSaved = use;
  // ...and onto the account, which is the truth behind it (roadmap #25).
  // localStorage stays the PAINT path: the scheme is applied at the top of
  // this file before the stylesheet parses, and a value fetched over the
  // network would be a flash of the default followed by a jump, so this is
  // not a replacement for it. What it buys is a browser that has never seen
  // this account: it adopts the scheme after first paint instead of never.
  // Fire and forget: a failed save is a scheme that did not follow you, not
  // something to interrupt the person picking colors about.
  fetch("/api/users", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "prefs", prefs: { theme: use } }) })
    .catch(() => {});
  markUiMenu();
}

// The account's scheme, taken up only by a browser that has none of its own.
// Runs on every poll and does nothing on almost all of them; the guard is the
// stored value, not a flag, so a second tab that picked a scheme is honored
// here too rather than being fought over.
let themeSaved = null;

function adoptTheme(t, who){
  let had, whose;
  try{
    had = localStorage.getItem("bb.theme"); whose = localStorage.getItem("bb.theme.who");
  }catch(e){ return; }              // no storage: leave the default alone
  // The browser's own choice stands for the account that made it. Another
  // account signing in here takes its own scheme, the default for one that
  // never picked (B491: a new account inherited the first one's colors).
  const same = !who || !had || (whose || "") === who;
  if (had && same) return;
  const use = t && /^[a-z]{2,12}$/.test(t) ? t : "default";
  if (same && (!t || use === themeSaved)) return;
  themeSaved = use;
  applyTheme(use);
}

// Only the marks, never a rebuild. Replacing the grid's innerHTML from inside
// a swatch's own click handler detaches the node the click is still traveling
// through, and the document listener that closes the menu on an outside click
// then sees a target #uiMenu no longer contains, and shuts it. Picking a scheme
// closed the menu, which is exactly wrong for a control somebody tries twice.
function markUiMenu(){
  const cur = currentTheme();
  document.querySelectorAll("#uiMenu .sw").forEach(b => {
    const on = b.dataset.theme === cur;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
  });
  const mode = currentMode();
  document.querySelectorAll("#uiMenu [data-mode]").forEach(b => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
  });
}

function currentTheme(){
  return document.documentElement.dataset.theme || "default";
}

function drawUiMenu(){
  const el = $("uiMenu");
  if (!el || el.hidden) return;
  const cur = currentTheme();
  const mode = currentMode();
  el.innerHTML = `<div class="popbar"><b>Preferences</b></div>
    <h4>Appearance</h4><div class="popbody">
    <div class="pseg modeseg" role="group" aria-label="dark or light">${MODES.map(([id, label]) => `
      <button type="button" data-mode="${id}" class="${id === mode ? "on" : ""}"
        role="menuitemradio" aria-checked="${id === mode}">${esc(label)}</button>`).join("")}</div>
    <label class="uimotion"><input type="checkbox" id="uiMotion"${document.documentElement.dataset.motion === "reduce" ? " checked" : ""}> Reduce motion${
      helpIcon("pages switch, menus open and sections fold at once, in every browser you sign in to; off, the page follows what this device asks for")}</label></div>
    <h4>Color scheme</h4><div class="popbody">
    <div class="swgrid">${THEMES.map(([id, label]) => `
      <button type="button" class="sw${id === cur ? " on" : ""}" data-theme="${id}"
        role="menuitemradio" aria-checked="${id === cur}"
        aria-label="${esc(label)}" title="${esc(label)}">
        <span class="swa"></span><span class="swb"></span><span class="swi"></span>
        <span class="swp"></span><span class="swn">${esc(label)}</span>
      </button>`).join("")}</div></div>
    <h4>Time zone</h4><div class="popbody">
    <div class="tzrow">
      <select id="uiTZ" aria-label="this browser's time zone">${tzOptions(tzDraft ?? userTZ())}</select>
      <button type="button" id="uiTZApply"${tzDraft === null || tzDraft === userTZ() ? " disabled" : ""}>Apply</button>
    </div>
    <div class="tzsaid">times here read ${esc(fmtTime(Date.now(), {hour: "2-digit", minute: "2-digit", timeZoneName: "short"}))}</div></div>
    <h4>Account</h4><div class="popbody">
    <div class="acctrow">
      <button type="button" id="uiProfile">Profile</button>
      <button type="button" id="uiReport" class="narrowonly" aria-label="report a bug" title="report a bug in BuilderBot: it goes to the diagnostics">${$("bReport")?.querySelector("svg")?.outerHTML || "Report a bug"}</button>
      <button type="button" id="uiOut" class="narrowonly" aria-label="sign out" title="sign out: back to the login page">${$("bOut")?.querySelector("svg")?.outerHTML || "Sign out"}</button>
    </div></div>`;
  el.querySelectorAll(".sw").forEach(b =>
    b.onclick = () => applyTheme(b.dataset.theme));
  el.querySelectorAll("[data-mode]").forEach(b =>
    b.onclick = () => applyMode(b.dataset.mode));
  // Less motion beside the scheme's half (the operator, 19 Oct): the
  // account's own, kept as the scheme is (page-motion.js applyMotion).
  el.querySelector("#uiMotion").onchange = e => applyMotion(e.target.checked);
  // The graduation (docs/nodes.md §13): the gear keeps what is this
  // BROWSER's and everything the controller owns lives on the Controller
  // page, where it has room to say what it costs.
  // The time zone is this browser's, beside its scheme (R218 step 31): a
  // pick, then Apply, as any setting (the settings rule's one exception is
  // the scheme, which is looked at rather than decided).
  const tz = el.querySelector("#uiTZ"), tzApply = el.querySelector("#uiTZApply");
  tz.onchange = () => { tzDraft = tz.value; tzApply.disabled = tzDraft === userTZ(); };
  // Said in place, not by drawing the menu again: a redraw took the pressed
  // button out of the menu before the press reached the page's listener,
  // which read it as a press elsewhere and shut the menu.
  tzApply.onclick = () => {
    setUserTZ(tzDraft || "");
    tzDraft = null;
    tzApply.disabled = true;
    const said = el.querySelector(".tzsaid");
    if (said) said.textContent = `times here read ${fmtTime(Date.now(), {hour: "2-digit", minute: "2-digit", timeZoneName: "short"})}`;
    notify(userTZ() ? `times on this browser are in ${userTZ()} now` : "times on this browser follow this device again");
    drawPanes();
  };
  el.querySelector("#uiProfile").onclick = () => { toggleUiMenu(false);
    openProfileTab(); };
  // On a narrow phone the header's bug and sign-out live here, so the search
  // beside the logo keeps room to be typed into (B744).
  el.querySelector("#uiReport").onclick = () => { toggleUiMenu(false); openReport(""); };
  el.querySelector("#uiOut").onclick = () => askSignOut();
}

function logSection(){
  const L = state?.logs;
  if (!L) return "";
  // How far back the files actually reach, not the policy repeated back: on a
  // box that has been up a week the honest answer is a week, whatever the
  // setting says.
  const back = L.oldest
    ? Math.max(0, Math.round((Date.now() / 1000 - L.oldest) / 86400)) : 0;
  return `<h4>Logs</h4>
    <div class="logset">
      <div class="dim">${!L.files ? "no logs yet"
        : `${L.files} file${L.files === 1 ? "" : "s"}, ${humanBytes(L.bytes)}`}${
        L.ci ? ` · ${L.ci} CI run${L.ci === 1 ? "" : "s"}` : ""}${
        L.oldest ? ` · reaching back ${back} day${back === 1 ? "" : "s"}` : ""}</div>
      <div class="logdays setrow col ctlrow">
        ${lbl("logDays", "Days of logs kept", "older files are deleted when this is applied")}
        <input id="logDays" type="number" min="1" max="3650" step="1"
               value="${typeof sdVal === "function" ? sdVal("logDays", L.days) : L.days}" inputmode="numeric">
      </div>
      <div class="actbar">
        <span class="state">applies at once, and anything already past it is cropped</span>
        <button type="button" id="logApply"
          title="save it, and crop anything already past it">Apply</button>
      </div>
      <!-- An action bar like every other: what the links are on the left,
           the verbs at the right (R119 step 6). -->
      <div class="actbar logacts">
        <span class="state">download the logs, or clear the old ones</span>
        <a class="btnish" href="/logs/download?what=session" download
           title="this container start: the boot, the dashboard and docker"
           >This session</a>
        <a class="btnish" href="/logs/download?what=archive" download
           title="every log kept, plus the archived CI runs, as a .tar.gz"
           >All logs</a>
        ${state?.can?.debug === false ? "" : `<a class="btnish" href="/logs/download?what=diag" download
           title="the controller's diagnostics as one file, with what sessions reported about BuilderBot"
           >Diagnostics</a>`}
        <button type="button" id="logClear" class="danger"
           title="delete every kept log except this session's">Clear</button>
      </div>
    </div>`;
}

function wireLogSection(el){
  const inp = el.querySelector("#logDays");
  if (!inp) return;
  // Applied on a press, not on change. Lowering the number CROPS: the files
  // past it are deleted then and there, and a number field fires `change` on
  // its way through every value the arrows and the keyboard pass, so typing 30
  // over 300 would have pruned at 3 before reaching 30. A button is also the
  // only way to say "crop now" without changing the number at all.
  const apply = async () => {
    const days = parseInt(inp.value, 10);
    if (!(days >= 1)) return notify("days has to be 1 or more", true);
    const btn = el.querySelector("#logApply");
    busy(btn, "Applying");
    try{
      const r = await postJSON("/api/logs", {action: "days", days});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      if (typeof settingsDraft === "object") delete settingsDraft.logDays;
      notify(j.removed
        ? `keeping ${j.days} days: ${j.removed} file${j.removed === 1 ? "" : "s"} removed`
        : `keeping ${j.days} days; nothing was past it`);
      refresh(); drawUiMenu();
    }catch(e){ notify("logs: " + e, true); }
    finally{ if (btn?.isConnected) unbusy(btn, "Apply"); }
  };
  el.querySelector("#logApply").onclick = apply;
  // Enter in the field does what the button does, because a number typed into
  // a box and then pressed at is what everybody tries first.
  inp.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
  el.querySelector("#logClear").onclick = async () => {
    if (!confirm("Delete every kept log except this session's?\n\n"
                 + "This session keeps writing to its own.")) return;
    try{
      const r = await postJSON("/api/logs", {action: "clear"});
      const j = await r.json();
      notify(j.error || `${j.removed} file${j.removed === 1 ? "" : "s"} removed`, !!j.error);
      refresh(); drawUiMenu();
    }catch(e){ notify("logs: " + e, true); }
  };
}

let uiMenuOpen = false;

function toggleUiMenu(open){
  const el = $("uiMenu"), btn = $("bCards");
  uiMenuOpen = open === undefined ? !uiMenuOpen : open;
  btn.setAttribute("aria-expanded", uiMenuOpen ? "true" : "false");
  if (uiMenuOpen){
    // A close still playing is stopped, and its end hides only a menu still
    // meant to be shut: pressed again inside its 120ms, the menu opened and
    // was then hidden by the close's own finish (B855).
    el.getAnimations().forEach(a => a.cancel());
    el.hidden = false;
    drawUiMenu();
    if (!noMotion())
      el.animate([{opacity: 0, transform: "translateY(-10px)"},
                  {opacity: 1, transform: "none"}], {duration: 160, easing: "ease"});
  } else if (!el.hidden){
    const hide = () => { if (!uiMenuOpen) el.hidden = true; };
    if (noMotion()) hide();
    else el.animate([{opacity: 1, transform: "none"},
                     {opacity: 0, transform: "translateY(-10px)"}],
                    {duration: 120, easing: "ease"}).onfinish = hide;
  }
}

// ---- sign out, asked --------------------------------------------------------
// The header's Sign out and the gear's open this first (the operator, 16
// Oct): Sign out leaves for /logout, and with the box ticked ends the
// account's sessions on the way, here and on the nodes, the same End the
// Sessions page presses. With none running the box is not offered.
function askSignOut(){
  const m = $("outModal");
  if (!m) { location.href = "/logout"; return; }
  const ss = state?.sessions || [];
  const agentSs = ss.filter(s => agentOfSession(tmuxBase(s.name))), claude = agentSs.length;
  $("outEndRow").hidden = !ss.length;
  $("outEnd").checked = false;
  $("outEndSaid").textContent = `Also end my sessions (${ss.length} running${claude ? `, ${claude} of them ${agentsWord(agentSs.map(s => s.name))}` : ""})`;
  const go = $("outGo");
  unbusy(go, "Sign out");
  go.onclick = async () => {
    busy(go, "Signing out");
    if ($("outEnd").checked)
      await Promise.all(ss.map(s => endSession(s.name, s.node_id || "").catch(() => {})));
    location.href = "/logout";
  };
  $("outCancel").onclick = () => { m.hidden = true; };
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  m.hidden = false;
}
