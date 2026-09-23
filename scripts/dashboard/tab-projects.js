// The Projects tab and the bin behind it: every project as a row with its
// controls, and what Unlink and Delete left to purge.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

async function postTrash(path, body){
  try{
    const r = await postJSON(path, body);
    return await r.json();
  }catch(e){ return {error: String(e)}; }
}

async function openTrash(){
  $("tmodal").hidden = false;
  await drawTrash();
}

async function drawTrash(){
  const el = $("tList");
  el.innerHTML = `<div class="loading">loading…</div>`;
  let j;
  try{ j = await (await fetch("/api/trash")).json(); }
  catch(e){ el.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; return; }
  const items = j?.items || [];
  if (!items.length){
    el.innerHTML = `<div class="empty">nothing deleted</div>`;
    return;
  }
  el.innerHTML = items.map(t => `<div class="row trow" data-t="${esc(t.name)}">
      <div class="grow"><div class="name">${esc(t.name)}</div>
        <div class="sub">deleted ${esc(ago(t.at))}${t.taken
          ? ` · <span class="warn">${esc(t.was)} exists again</span>` : ""}</div></div>
      <span class="acts">
        <button type="button" data-trestore="${esc(t.name)}"${t.taken ? " disabled" : ""}
          title="${t.taken
            ? "a project called " + esc(t.was) + " is back under /workspace: rename it first"
            : "move it back to /workspace/" + esc(t.was)}">Put back</button>
        <button type="button" class="danger" data-tpurge="${esc(t.name)}"
          title="delete it and every file in it, for good">${BIN}</button>
      </span></div>`).join("");
  el.querySelectorAll("[data-trestore]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await postTrash("/api/trash-restore", {name: b.dataset.trestore});
    if (r?.error) notify(r.error, true);
    else notify(`${r.name} is back under /workspace`);
    await drawTrash(); refresh();
  });
  el.querySelectorAll("[data-tpurge]").forEach(b => b.onclick = () => askPurge(b.dataset.tpurge));
}

// Typed, not clicked. There is nothing after this one: no .trash to fish it
// out of a second time, and the ceremony is the difference between a control
// somebody meant to press and one their thumb found.
function askPurge(name){
  const row = $("tList").querySelector(`.trow[data-t="${CSS.escape(name)}"]`);
  if (!row || row.querySelector(".dropbox")) return;
  const box = document.createElement("div");
  box.className = "dropbox";
  box.innerHTML = `<div class="hint bad">This deletes every file in
      <b>${esc(name)}</b>. It is not moved anywhere and there is nothing to
      undo it with. Type the name to confirm.</div>
    <input autocomplete="off" placeholder="${esc(name)}">
    <div class="foot"><span class="sp"></span>
      <button type="button" class="stop">Keep it</button>
      <button type="button" class="danger" disabled>Delete for good</button></div>`;
  row.appendChild(box);
  const input = box.querySelector("input"), go = box.querySelector(".danger");
  input.oninput = () => { go.disabled = input.value.trim() !== name; };
  input.focus();
  box.querySelector(".stop").onclick = () => box.remove();
  go.onclick = async () => {
    go.disabled = true;
    const r = await postTrash("/api/trash-purge", {name, confirm: input.value.trim()});
    if (r?.error){ notify(r.error, true); go.disabled = false; return; }
    notify(`${name} is gone`);
    await drawTrash();
  };
}

const BIN = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M2.8 4.3h10.4"/><path d="M6.4 4.3V2.9h3.2v1.4"/>
  <path d="M4.2 4.3l.7 8.3a1 1 0 0 0 1 .9h4.2a1 1 0 0 0 1-.9l.7-8.3"/>
  <path d="M6.8 6.8v4"/><path d="M9.2 6.8v4"/></svg>`;

// Every project, and the whole of each one. The card is a view of this filtered
// to what is pinned, so a project that is not on the sidebar has lost nothing
// but its place there, which is the only promise the thumbtack makes.
function openProjectsTab(){
  openTab({kind: "projects", arg: "__projects", label: "Projects"});
}

function renderProjectsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  const ps = state?.projects || [];
  // The empty case keeps the button, and needs it most: an empty workspace is
  // exactly where somebody is about to make their first project, and a page
  // that only says what is missing offers no way to fix it.
  if (!ps.length){
    el.innerHTML = `<div class="projtab"><div class="macros"><button
        id="bNewProjTab">New project</button></div>
      <div class="empty">${state.admin ? "nothing under /workspace yet: New project starts one"
                                       : "no projects are yours yet: an administrator grants them on the Users tab"}</div></div>`;
    el.querySelector("#bNewProjTab").onclick = openNewProject;
    return;
  }
  const live = liveSessions();
  const cls = {error:"bad", warning:"warn", locked:"locked"};
  // Pinned first, then by name: the sidebar's order, so moving between the two
  // does not mean finding everything again. Sorted here rather than by the
  // server, which reports the directory order every other reader wants.
  const ordered = ps.slice().sort((a, b) =>
    (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || a.name.localeCompare(b.name));
  // paint() rather than innerHTML, the same as the card: this runs on every
  // render pass, and rebuilding a list of rows nobody changed throws away the
  // handlers on it for no reason.
  // At the TOP here, unlike the sidebar card where it sits at the foot. That
  // card's header is its collapse control and drag handle, so nothing else can
  // live in it; this tab has no such header, and the list of every project is
  // exactly where somebody stands when they want another one: the bottom of a
  // long scroll is the worst place for it.
  if (paint(el, `<div class="projtab"><div class="actbar macros"><button
      id="bNewProjTab"
      title="create a project under /workspace: a fresh local repo, or a clone of a repo the container can reach"
      >New project</button></div>${
    ordered.map(p => projectRow(p, live, cls, true)).join("")}</div>`)){
    wireProjectRows(el);
    el.querySelector("#bNewProjTab").onclick = openNewProject;
  }
}

// Whether a session in this project may rebuild its dev instance: the
// project's own setting, off unless somebody turned it on, read from the
// poll rather than fetched so the checkbox is right on the first draw.
// The same three words the notebook's gates use (GATE_MODES), because it is
// the same question: how much of what a session wants to do happens without
// you. `deny` leads, as the default and as the safe end of the dial.
const DEVBUILD_MODES = [["deny", "deny"], ["ask", "ask me"], ["auto", "auto"]];

// What a project's dial says: one of the three words, deny unless a
// record says otherwise.
const devClaudeMode = name => {
  const v = (state?.projects || []).find(p => p.name === name)?.prefs?.devbuild;
  return DEVBUILD_MODES.some(([m]) => m === v) ? v : "deny";
};
