// The Commands panel (the operator, 17 Oct): the pinned commands above the
// rest, the operator's own, and the Linux and git lists, each command with a
// tack that pins it. No bb commands: every one of them has its page now.
// Each button types into the terminal; the list of what can be typed is the
// server's (macros.py), never a string from here.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

"use strict";

// Side-view thumbtack: cap, body, needle. Filled when pinned, so the state
// reads at a glance without a second icon to learn.
const TACK = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M5 1.6h6"/>
  <path d="M6.4 1.6v4.1c0 .9-.5 1.4-1.3 1.9-.7.5-1.2 1-1.2 1.6h8.2c0-.6-.5-1.1-1.2-1.6
           -.8-.5-1.3-1-1.3-1.9V1.6"/>
  <path d="M8 9.2v5.2"/></svg>`;

// One command and its tack. The label IS the command: these are buttons
// for things an operator would type, and hiding the text behind a friendly
// name would only add mystery. `need` rides along as data-need for
// wireMacros to ghost against the active shell's directory.
function commandButton(m, pins){
  const on = pins.has(m.name);
  return `<span class="cmd">
    <button data-m="${esc(m.name)}"${m.need ? ` data-need="${esc(m.need)}"` : ""} title="${esc(m.label)}: runs in the terminal">${esc(m.label)}</button>
    <button class="tack${on ? " on" : ""}" data-tack="${esc(m.name)}" data-on="${on ? "1" : "0"}"
      aria-label="${on ? "unpin" : "pin"} ${esc(m.label)}"${state?.can?.["command-pin"] === false ? " disabled" : ""}
      title="${on ? "unpin: let it fall back into its list" : "pin: keep it at the top"}">${TACK}</button></span>`;
}

function wireTacks(el){
  el.querySelectorAll("[data-tack]").forEach(b => b.onclick = () =>
    setPinned(b.dataset.tack, b.dataset.on === "0"));
}

// The pinned ones, in their lists' order.
function drawCommands(){
  const el = $("commands"), pins = new Set(state?.pinned || []);
  const all = [...(state?.linux || []), ...(state?.gitcmds || [])].filter(m => pins.has(m.name));
  const fresh = paint(el, all.length ? all.map(m => commandButton(m, pins)).join("")
    : `<div class="empty">none yet: a command's tack keeps it here</div>`);
  wireMacros(el);
  if (fresh) wireTacks(el);
}

function drawShellCard(id, list){
  const el = $(id), pins = new Set(state?.pinned || []);
  if (!list.length){ paint(el, `${skel("chips")}`); return; }
  const fresh = paint(el, list.map(m => commandButton(m, pins)).join(""));
  wireMacros(el);
  if (fresh) wireTacks(el);
}

const drawLinux = () => drawShellCard("linux", state?.linux || []);

const drawGit   = () => drawShellCard("git", state?.gitcmds || []);

const PENCIL = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M11.3 2.2 13.8 4.7 5.6 12.9 2.4 13.6 3.1 10.4z"/>
  <path d="M9.9 3.6 12.4 6.1"/></svg>`;

function drawCustom(){
  const el = $("custom"), list = state?.custom || [];
  const fresh = paint(el, (list.length ? "" : `<div class="empty">none yet: add one with +</div>`)
    + list.map(m => {
    // The full title and what it will run, for the hover: a one-word title is
    // no help six months later when you have forgotten what it does.
    const tip = `${m.title}\n\n${m.lines.join("\n")}`;
    return `<span class="cmd">
      <button class="run" data-run="${esc(m.id)}" title="${esc(tip)}">${esc(m.title)}</button>
      <button class="tack" data-edit="${esc(m.id)}" aria-label="edit"
        title="edit or delete">${PENCIL}</button>
    </span>`;
  }).join("")
  // "+" is redrawn with the list it adds to: a static button would be wiped
  // by this very innerHTML, and lives here because the header holds nothing.
  + `<button id="bAdd" title="new custom command">+</button>`);
  wireMacros(el);
  if (!fresh) return;
  el.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => editCustom(b.dataset.edit));
  $("bAdd").onclick = () => editCustom(null);
}

let editing = null;

function editCustom(id){
  const m = (state?.custom || []).find(x => x.id === id) || null;
  editing = m?.id || null;
  $("mTitle").textContent = m ? "Edit custom command" : "New custom command";
  $("mName").value = m?.title || "";
  $("mBody").value = (m?.lines || []).join("\n");
  $("mDelete").hidden = !m;
  $("modal").hidden = false;
}

function closeEditor(){ $("modal").hidden = true; editing = null; }

// ---- saved and pinned commands ------------------------------------------

async function postCustom(body){
  try{
    const r = await postJSON("/api/custom", body);
    const j = await r.json();
    if (j.error){ notify(j.error, true); return false; }
    if (state) state.custom = j.custom;
    drawCustom();
    return true;
  }catch(e){ notify("could not save it: " + e, true); return false; }
}

async function setPinned(name, on){
  try{
    const r = await postJSON("/api/pin", {name, pinned:on});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The server's answer is the truth, so two browsers cannot disagree about
    // what is pinned until the next poll.
    if (state) state.pinned = j.pinned;
    drawCommands(); drawLinux(); drawGit();
  }catch(e){ notify("could not save the pin: " + e, true); }
}
