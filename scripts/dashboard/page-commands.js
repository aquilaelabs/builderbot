// The command cards: every bb command with the pinned ones above the cut,
// the Linux and git cards, and the operator's own custom commands with the
// dialog that edits one. Each button types into the terminal; the list of
// what can be typed is the server's (MACROS), never a string from here.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

"use strict";

const COMMANDS_SHOWN = 8;

let showAllCommands = false;

// Side-view thumbtack: cap, body, needle. Filled when pinned, so the state
// reads at a glance without a second icon to learn.
const TACK = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M5 1.6h6"/>
  <path d="M6.4 1.6v4.1c0 .9-.5 1.4-1.3 1.9-.7.5-1.2 1-1.2 1.6h8.2c0-.6-.5-1.1-1.2-1.6
           -.8-.5-1.3-1-1.3-1.9V1.6"/>
  <path d="M8 9.2v5.2"/></svg>`;

// Pinned first, then the rest: both in the order `bb help` lists them, which
// is the order the server sends. Pinning moves a command up; it does not
// re-sort it into an order the CLI never uses.
function commandOrder(){
  const all = state?.macros || [];
  const pins = new Set(state?.pinned || []);
  return [...all.filter(m => pins.has(m.name)), ...all.filter(m => !pins.has(m.name))];
}

function drawCommands(){
  const el = $("commands");
  const order = commandOrder(), pins = new Set(state?.pinned || []);
  if (!order.length){ paint(el, `<div class="empty">no commands</div>`); return; }

  const shown = showAllCommands ? order : order.slice(0, COMMANDS_SHOWN);
  const fresh = paint(el, shown.map(m => {
    const on = pins.has(m.name);
    return `<span class="cmd">
      <button data-m="${esc(m.name)}" title="bb ${esc(m.label)}: runs in the terminal"
        >${esc(m.label)}</button>
      <button class="tack${on ? " on" : ""}" data-tack="${esc(m.name)}"
        data-on="${on ? "1" : "0"}" aria-label="${on ? "unpin" : "pin"}"${state?.can?.["command-pin"] === false ? " disabled" : ""}
        title="${on ? "unpin: let it fall back into the list"
                    : "pin: keep it at the top of this card"}">${TACK}</button>
    </span>`;
  }).join("")
  // The cut-off toggle sits with the list it cuts, since the header is
  // reserved for collapsing the whole card.
  + (order.length > COMMANDS_SHOWN
     ? `<button id="bCmds">${showAllCommands ? "Show fewer" : `Show all (${order.length})`}</button>`
     : ""));
  wireMacros(el);                       // live-or-grayed depends on the active
                                        // tab, not the markup: always re-done
  if (!fresh) return;
  if (order.length > COMMANDS_SHOWN)
    $("bCmds").onclick = () => { showAllCommands = !showAllCommands;
                                 slideBody(el, drawCommands); };
  el.querySelectorAll("[data-tack]").forEach(b => b.onclick = () =>
    setPinned(b.dataset.tack, b.dataset.on === "0"));
}

// The Linux and git/GitHub cards. Same idea as the bb card, minus pins and
// the cut-off: the lists are short and fixed. The label IS the command:
// these are buttons for things an operator would type, and hiding the text
// behind a friendly name would only add mystery. `need` rides along as
// data-need for wireMacros to ghost against the active shell's directory.
function drawShellCard(id, list){
  const el = $(id);
  if (!list.length){ paint(el, `<div class="loading">loading…</div>`); return; }
  paint(el, list.map(m => `<button data-m="${esc(m.name)}"${
      m.need ? ` data-need="${esc(m.need)}"` : ""
    } title="${esc(m.label)}: runs in the terminal">${esc(m.label)}</button>`).join(""));
  wireMacros(el);
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
    drawCommands();
  }catch(e){ notify("could not save the pin: " + e, true); }
}
