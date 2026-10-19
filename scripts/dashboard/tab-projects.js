// The Projects tab and the bin behind it: every project as a row with its
// controls, and what Unlink and Delete left to purge.
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand: pure
// declarations, nothing runs at load.

"use strict";

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
  el.innerHTML = `${skel("rows", 3)}`;
  let j;
  try{ j = await (await fetch("/api/trash")).json(); }
  catch(e){ el.innerHTML = `<div class="hint bad">${esc(String(e))}</div>`; return; }
  const items = j?.items || [];
  if (!items.length){
    el.innerHTML = `<div class="empty">nothing deleted</div>`;
    return;
  }
  el.innerHTML = items.map(t => `<div class="row trow" data-t="${esc(t.name)}">
      <div class="grow"><div class="name">${esc(t.was || t.name)}</div>
        <div class="sub">deleted ${esc(ago(t.at))}${t.was && t.was !== t.name
          ? ` · directory ${esc(t.name)}` : ""}${t.taken
          ? ` · <span class="warn">its directory is in use again</span>` : ""}</div></div>
      <span class="acts">
        <button type="button" data-trestore="${esc(t.name)}"${t.taken ? " disabled" : ""}
          title="${t.taken
            ? "a directory of that name is back under /workspace: move it first"
            : "move it back to /workspace, as " + esc(t.was || t.name)}">Put back</button>
        <button type="button" class="ic danger" data-tpurge="${esc(t.name)}" aria-label="delete for good"
          title="delete it and every file in it, for good">${BIN}</button>
      </span></div>`).join("");
  el.querySelectorAll("[data-trestore]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await postTrash("/api/trash-restore", {name: b.dataset.trestore});
    if (r?.error) notify(r.error, true);
    else notify(`${r.label || r.name} is back`);
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
  box.className = "dropbox ctlown";
  box.innerHTML = `<div class="hint bad">This deletes every file in
      <b>${esc(name)}</b>. It is not moved anywhere and there is nothing to
      undo it with. Type its directory's name, ${esc(name)}, to confirm.</div>
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

// What the search box narrows the grid to: a view, this browser's, never
// saved. Matched against the name, the label, the branch and the node.
let pjQuery = "";
function projectMatches(p, q){
  if (!q) return true;
  const hay = [p.name, p.label, p.git, p.node_name, p.session_at].filter(Boolean).join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(w => hay.includes(w));
}

// One project's card on the grid (R218 step 3): its color down the left
// edge, the name (a press opens its page), the branch and the node, the
// session's dot and word, the one notice, and the two actions with the
// rest behind the menu, the same parts the project page's header draws.
// A project's lock, said one way on its card, its page's header and Home
// (consistency batch J: the header said locked where the card said
// archived): archived when it is locked, read-only when it is another
// account's.
function lockMark(p){
  return p.locked || notMine(p) ? ` <span class="lockmark">${LOCK}${p.locked ? "archived" : "read-only"}</span>` : "";
}
// A project's facts line, the same parts wherever it is drawn: its branch,
// that it may push, and the node it runs on.
function projFacts(p){
  const node = p.node_name || p.session_at || "";
  return `${p.git ? `git: <span class="pbr">${esc(p.git)}</span>${p.push ? ` · <span class="ok">push</span>` : ""}` : ""}${p.git && node ? " · " : ""}${esc(node)}`;
}
function projectCard(p){
  const pc = colorAttrs(p.color), cls = {error:"bad", warning:"warn", locked:"locked"};
  return `<div class="pcard${pc.cls}" data-row="${esc(p.name)}"${pc.style}>
    <div class="pcname"><button type="button" class="name link" data-open="${esc(p.name)}" title="open ${esc(projLabel(p.name))}'s page">${esc(p.label || p.name)}</button>${lockMark(p)}${
      p.pinned && !p.locked ? ` <span class="pinmark" title="pinned: on Home's glance" aria-label="pinned">${PIN}</span>` : ""}</div>
    <div class="pcfacts">${projFacts(p)}</div>
    ${projectState(p)}
    ${p.issues.map(i => `<div class="pnote ${cls[i.level] || ""}">${esc(i.text)}</div>`).join("")}
    ${state?.mapping?.[p.name] ? (m => m.running
        ? `<div class="pnote dim">mapping the code<span class="dots"></span>${m.for > 4 ? ` · ${m.for}s` : ""}</div>`
        : m.error ? `<div class="pnote warn">the code map did not build: ${esc(m.error)}</div>`
        : `<div class="pnote dim">mapped ${m.files} file${m.files === 1 ? "" : "s"} in ${m.took}s</div>`)(state.mapping[p.name]) : ""}
    ${p.phone?.lease?.project === p.name ? `<div class="pnote dim">${esc(p.phone.model || "a phone")} lent here by ${
        esc(p.phone.lease.by_name || p.phone.owner)}${p.phone.lease.left != null ? `, ${Math.max(1, Math.round(p.phone.lease.left / 60))} min left` : ""}: each command asks ${
        p.phone.mine ? "you" : esc(p.phone.owner)}</div>` : ""}
    ${p.testing ? `<div class="pnote dim">tests running, started ${esc(ago(p.testing.since))}</div>` : ""}
    ${projectNote(p)}
    <div class="pcacts actbar">${projectActions(p, `<button type="button" class="danger" data-del="${esc(p.name)}">Delete</button>`)}</div>
  </div>`;
}

function renderProjectsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  const ps = state?.projects || [];
  // The surface once (docSurface: the bar band, the band list, the quiet
  // footer): its bar is the search, New project and the trash, and the grid
  // under it is what paints on every pass, so typing in the box is not
  // drawn over.
  if (!el.querySelector(".projtab")){
    const d = docSurface(i, "proj");
    d.setBar(`<input id="pjSearch" type="search" placeholder="name, branch or node" aria-label="narrow the projects" autocomplete="off" spellcheck="false">
        <span class="sp"></span>
        <span class="actbar"><button type="button" id="bTrashTab" aria-label="the trash" title="projects you deleted: still on disk under .trash, and still recoverable">${BIN}</button>
        <button type="button" class="primary" id="bNewProjTab" title="a fresh local repo, or a clone">New project</button></span>`);
    d.list.innerHTML = `<div class="field pjjob" id="pjJob" hidden></div><div class="field pgridband"><div id="pjGrid"></div></div>`;
    el.querySelector("#bNewProjTab").onclick = openNewProject;
    el.querySelector("#bTrashTab").onclick = openTrash;
    const box = el.querySelector("#pjSearch");
    box.value = pjQuery;
    box.oninput = () => { pjQuery = box.value; renderProjectsInto(i); };
  }
  const grid = el.querySelector("#pjGrid");
  // The project job (a clone, a first push) running or failed, its own
  // band above the grid, where its result will appear.
  const jb = el.querySelector("#pjJob"), jh = projectJobHtml();
  if (paint(jb, jh)) pJobWire();
  setHidden(jb, !jh);
  // The empty case says what to do: an empty workspace is exactly where
  // somebody is about to make their first project.
  if (!ps.length){
    paint(grid, `<div class="empty">${state.admin ? "nothing under /workspace yet: New project starts one"
                                       : "no projects are yours yet: an administrator grants them on the Users tab"}</div>`);
    return;
  }
  // The pinned first, each part by name (the operator, 18 Oct, where on 7
  // Oct it was by name alone): what is pinned is what is looked for. Sorted
  // here rather than by the server, which reports the directory order every
  // other reader wants; each group, and the ungrouped, keeps the order.
  const shown = ps.filter(p => projectMatches(p, pjQuery))
    .sort((a, b) => (b.pinned && !b.locked) - (a.pinned && !a.locked) || byProjectName(a, b));
  // The ones in no group first, then each of this account's groups under
  // its name, by name (the operator, 18 Oct); and the archived ones apart,
  // folded at the foot, their own fold whatever group they were in.
  const live = shown.filter(p => !p.locked), gone = shown.filter(p => p.locked);
  const named = [...new Set(live.map(p => p.group).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const grid_ = list => `<div class="pgrid">${list.map(projectCard).join("")}</div>`;
  const loose = live.filter(p => !p.group);
  const html = (loose.length ? grid_(loose) : "")
    + named.map(g => {
        const list = live.filter(p => p.group === g);
        return `<section class="pjgroup" data-group="${esc(g)}"><h3 class="pjgname">${esc(g)} <span class="dim">${list.length}</span></h3>${grid_(list)}</section>`;
      }).join("")
    + (gone.length ? docSection("projects", "archived", "Archived", `${gone.length} project${gone.length === 1 ? "" : "s"}`,
                                grid_(gone), {open: false, cls: "dim", fold: true}) : "");
  if (paint(grid, html || `<div class="empty">nothing matches ${esc(pjQuery)}</div>`)){
    wireSections(grid);
    wireProjectRows(grid);
    wireProjectHeader(grid);
    grid.querySelectorAll("[data-open]").forEach(b => b.onclick = () => openNotebook(b.dataset.open));
    grid.querySelectorAll(".pcard[data-row]").forEach(c => c.onclick = e => {
      if (!cardPress(e)) return;
      openNotebook(c.dataset.row);
    });
  }
  syncResumeMenu();
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

// ---- the new-project dialog ------------------------------------------------
// One dialog, three modes: a new local repo, a clone, and linking a project
// to a git host. The host catalog and the agent's keys arrive per open from
// /api/pubkeys. Moved here from index.html with bb map sections in hand: the
// dialog is the Projects feature's. Its fields, its submit and the name
// that follows the address are wired from index.html.

// No cursor is put in a field here, on open or on a tab switch. A dialog that
// focuses something raises the on-screen keyboard with it, which covers half
// of what it just opened, so the field is chosen by the person who wants to
// type in it. `focus` stays in PMODES because it is also the name of the
// field that mode leads with, which pDraw uses.
const PMODES = {
  init:  { title: () => "New project", btn: "Create", focus: "pName",
           fields: ["pSrcField", "pNameField", "pVersionField", "pNodeField", "pGateField", "pArchiveField", "pAboutField"] },
  clone: { title: () => "New project", btn: "Create", focus: "pUrl",
           fields: ["pSrcField", "pNameField", "pNodeField", "pGateField", "pUrlField", "pForgeField",
                    "pPushField", "pTokenField", "pKeyField"] },
  link:  { title: () => `Link ${projLabel(pLink)} to a git host`, btn: "Link", focus: "pUrl",
           fields: ["pUrlField", "pForgeField", "pLinkAuthField", "pKeyField",
                    "pTokenField"] },
};

let pMode = "init";

let pLinkAuth = "key";                   // how a link authenticates: key or token

let pLink = null;                        // the project being linked, if any

let pKeys = [];                          // the agent's public keys, per open

let pPat = false;                        // can https push authenticate (gh)?

// The host catalog, from the same fetch as the keys. Empty until it lands,
// which is why every reader goes through pForge() rather than indexing it.
let pForges = [];

let pForgeId = "git";

// What the operator has already said their own servers run, by host. Both
// forms ask which host only for an address on a server nobody has answered
// for yet: the second project from the same Gitea is not asked.
let pForgeHosts = {};

// The host the current pick was made for, so a fresh address gets a fresh
// question rather than the last one's answer.
let pAskedHost = "";

// An archive picked, or picked again: its name beside the button, and the
// brief put away, since the archive is where the project starts.
function pArchivePicked(){
  const f = $("pArchive").files[0];
  $("pArchiveName").textContent = f?.name || "none picked";
  if (f) $("pAbout").value = "";
  pDraw();
}

function pDraw(){
  const m = PMODES[pMode];
  $("pTitle").textContent = m.title();
  $("pCreate").textContent = $("pCreate").disabled ? $("pCreate").textContent : m.btn;
  $("pLocal").classList.toggle("on", pMode === "init");
  $("pClone").classList.toggle("on", pMode === "clone");
  for (const f of ["pSrcField", "pNameField", "pVersionField", "pArchiveField", "pForgeField",
                   "pUrlField", "pLinkAuthField", "pPushField",
                   "pTokenField", "pKeyField", "pAboutField", "pGateField"])
    $(f).hidden = !m.fields.includes(f);
  // A brief says what to build from nothing; an archive is the start, so the
  // field goes once one is picked (the server refuses the pair as well).
  if (pMode === "init" && $("pArchive").files[0]) $("pAboutField").hidden = true;
  pDrawForge();
  // The deploy-key picker only appears when the agent actually holds keys:
  // an empty dropdown would be a question with no answers.
  if (!pKeys.length) $("pKeyField").hidden = true;
  // Linking: the switch decides which of the two fields is asked.
  if (pMode === "link"){
    $("pLinkKey").classList.toggle("on", pLinkAuth === "key");
    $("pLinkToken").classList.toggle("on", pLinkAuth === "token");
    $("pKeyField").hidden = pLinkAuth !== "key" || !pKeys.length;
    $("pTokenField").hidden = pLinkAuth !== "token";
  }
  // What the token field is about: the address's own host, in both modes.
  const fg = pFg();
  $("pUrlHint").textContent = pMode === "link"
    ? `An empty repository to push ${pLink} to.`
      + ((fg.creates && pLinkAuth === "token") || (pPat && fg.id === "github" && pLinkAuth === "key")
         ? " One that does not exist yet is created, private." : "")
    : "A private repository needs a deploy key or token that already reaches it.";
  $("pNameHint").textContent = pMode === "clone"
    ? "The directory to clone into; change it to keep two checkouts of one repository."
    : "Anything a git host cannot use in a name becomes a dash.";
  $("pPushHint").textContent =
    "Off is read-only. It cannot be turned on later, and only one project may push to a repository.";
  $("pTokenHint").textContent = pMode === "link"
    ? `Used for ${projLabel(pLink)} only.` + (fg.creates ? ` Checked with ${fg.name} first.` : "")
    : "Leave empty for a public repository. Kept for this project alone.";
  $("pToken").placeholder = fg.hint;
  $("pKeyHint").textContent =
    "The key used to push. Add the public key below to the repository's deploy keys."
    + (pPat && (pMode !== "link" || fg.id === "github") ? " With an access token configured, none works too."
       : pMode === "link" ? " No access token is configured for this host, so a key is required." : "");
}

// The source picker moves like the Dashboard | Terminal switch: the incoming
// fields slide in from the chosen tab's side (local is the left tab, clone
// the right), same 220ms ease, same reduced-motion gate: one vocabulary for
// every two-tab switch on the page. Scaled to the dialog: a few pixels, not
// a viewport, because the fields swap inside a box that is not moving.
// The host in an address, as typed: enough to tell a server the catalog
// names from one nobody has answered for. Not a validator: the server parses
// it properly, and this only decides whether to ask a question.
function pUrlHost(url){
  const u = (url || "").trim();
  let m = /^[a-z]+:\/\/(?:[^@/]+@)?([A-Za-z0-9][A-Za-z0-9.:-]*)/i.exec(u);
  if (!m) m = /^(?:[^@:/]+@)?([A-Za-z0-9][A-Za-z0-9.-]*):/.exec(u);
  return m ? m[1].toLowerCase() : "";
}

// Which catalog entry a host names itself as, or null when nobody has said.
const pForgeOf = host => {
  if (!host) return null;
  const bare = host.split(":")[0];
  return pForges.find(f => f.host && f.host.toLowerCase() === bare)
      || pForges.find(f => f.id === pForgeHosts[host]) || null;
};

function pDrawForge(){
  if ($("pForgeField").hidden) return;
  const sel = $("pForge");
  if (sel.dataset.built !== String(pForges.length)){
    sel.innerHTML = `<option value="" hidden>from the address</option>` + pForges.map(f =>
      `<option value="${esc(f.id)}">${esc(f.name)}${f.dev ? " (dev)" : ""}</option>`).join("");
    sel.dataset.built = String(pForges.length);
  }
  // One row under the address in both modes, always there, so nothing pops
  // up as the address is typed (the operator, 13 Oct). The address is the
  // subject and the host is in it, so this is not a second place to type
  // one: the row reads the address back (GitHub names itself, a server
  // answered for once is remembered) and becomes a question only for a
  // server that does not name itself and nobody has answered for. The
  // hint says which it is, so a locked row says why it is locked.
  const host = pUrlHost($("pUrl").value), bare = host.split(":")[0];
  const named = pForgeOf(host);
  sel.disabled = !host || !!named;
  if (!host){
    sel.value = "";
    $("pForgeHint").textContent = "Read from the address above.";
  } else if (named){
    sel.value = named.id;
    $("pForgeHint").textContent = pForges.some(f => f.host && f.host.toLowerCase() === bare)
      ? `${host} names itself.`
      : `Answered before: ${host} runs ${named.name}.`;
  } else {
    // A server nobody has answered for starts on the entry that promises
    // nothing, not on GitHub: the question is what this one runs, and a
    // default that names a different server is an answer nobody gave.
    if (pAskedHost !== host){ pAskedHost = host; pForgeId = "git"; }
    sel.value = pForgeId;
    $("pForgeHint").textContent = `Which software ${host} runs. Asked once per server.`;
  }
  // The address box asks for the shape the push will use: linking by key
  // is ssh, by token https; a clone takes either and shows the ssh form.
  $("pUrl").placeholder = pMode === "link" && pLinkAuth === "token"
    ? "https://github.com/owner/repo.git" : "git@github.com:owner/repo.git";
}

function pSlide(){
  if (noMotion()) return;
  const dx = pMode === "clone" ? "18px" : "-18px";
  for (const f of PMODES[pMode].fields){
    const el = $(f);
    if (f !== "pSrcField" && !el.hidden)
      el.animate([{transform: `translateX(${dx})`, opacity: 0},
                  {transform: "none", opacity: 1}],
                 {duration: 220, easing: "ease"});
  }
}

// The picked entry, or a safe stand-in while the catalog is still in flight:
// the dialog draws before the fetch answers, and a placeholder that promises
// nothing is better than a draw that throws.
const PFORGE_NONE = {id: "", name: "the host", host: "", fixed: false,
                     hint: "an access token", about: "", creates: false};

const pForge = () => pForges.find(f => f.id === pForgeId) || pForges[0]
                     || PFORGE_NONE;

// The host the dialog is about: the address's own wherever it names itself
// or has been answered for, the picked entry for a server nobody has, and
// the entry that promises nothing while there is no address yet.
const pFg = () => {
  const host = pUrlHost($("pUrl").value);
  return pForgeOf(host) || (host ? pForge() : null)
      || pForges.find(f => f.id === "git") || PFORGE_NONE;
};

function pShowKey(){
  const k = pKeys.find(k => k.name === $("pKey").value);
  $("pPubWrap").hidden = !k;
  if (k) $("pPub").textContent = k.pub;
}

// Each open is a generation; closing bumps it too. Everything asynchronous:
// the pubkeys response, a slow clone's outcome: checks the generation before
// touching the dialog, so a request from a closed dialog can neither shut the
// one the operator just reopened nor write its error where the wrong flow
// will wear it. The outcome itself still surfaces, as a toast.
let pGen = 0;

let pFetch = null;                       // this open's /api/pubkeys, parsed

// The four gates on the dialog (roadmap #27), the same table the settings
// dialog draws from, and auto on every open: what a session may enter is
// asked once here so it is a choice made rather than a default found later.
const P_GATE_IDS = {roadmap: "pGateRoadmap", bugs: "pGateBugs", rules: "pGateRules", settings: "pGateSettings",
                    design: "pGateDesign", wiki: "pGateWiki"};
const pGateNow = () => Object.fromEntries(
  Object.entries(P_GATE_IDS).map(([k, id]) => [k, $(id).value || "auto"]));
// What a new project starts on (the operator, 1 Oct). Auto where what a
// session does lands in the notebook or the settings with its history and
// is undone in a press: the roadmap, bugs, rules, build and test, the
// design, the wiki (each page's history is kept), and a report to
// BuilderBot's own tracker. Ask where it reaches
// past that: its container, which runs the project's code on a shared
// machine and publishes ports (ask rather than the deny a project has
// without a choice, so a session can propose a rebuild at all, having no
// docker of its own), a signed build, which leaves, and a signing key,
// which is an app's identity for good.
const P_GATE_DEFAULT = {pGateDocker: "ask", pGateSign: "ask", pGateKeys: "ask", pGateRelease: "ask", pGateReport: "auto"};
function pFillGates(){
  for (const id of [...Object.values(P_GATE_IDS), "pGateDocker", "pGateSign", "pGateKeys", "pGateRelease", "pGateReport"]){
    const el = $(id);
    if (el.dataset.built !== "1"){
      // A report has nothing to hold for approval: auto or deny.
      el.innerHTML = (id === "pGateWiki" ? gateChoices("wiki") : GATE_MODES).filter(([v]) => id !== "pGateReport" || v !== "ask")
        .map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    el.value = P_GATE_DEFAULT[id] || "auto";
  }
}

function pOpen(mode){
  const gen = ++pGen;
  pMode = mode; pKeys = []; pPat = false; pFillGates(); pDraw();
  $("pName").value = $("pUrl").value = $("pAbout").value = "";
  $("pToken").value = "";
  pAskedHost = "";
  // Every open starts on the entry that promises nothing rather than on
  // whatever the last one picked: the pick is only ever an answer about a
  // server nobody has answered for, and a remembered one would be silent.
  pForgeId = "git";
  $("pPush").checked = false;
  pNameTyped = false;
  $("pNamePreview").hidden = true;
  $("pName").classList.remove("bad");
  $("pNamePreview").classList.remove("bad");
  // The select is emptied, not left as-is: a key picked during a previous
  // open must not ride along invisibly into this one's submit.
  $("pKey").innerHTML = "";
  $("pErrWrap").hidden = $("pPubWrap").hidden = true;
  $("pCreate").disabled = false; $("pCreate").textContent = PMODES[mode].btn;
  $("pmodal").hidden = false;
  pFillNode();
  // Fetched per open, not cached: keys change when the container restarts
  // with a new /secrets/ssh, and a stale list here would offer a key the
  // agent no longer holds. The submit handler awaits pFetch directly, so an
  // early Create still judges auth on the real answer, not the defaults.
  pFetch = fetch("/api/pubkeys").then(r => r.json()).catch(() => null);
  pFetch.then(j => {
    if (gen !== pGen || !j) return;
    pKeys = j.keys || []; pPat = !!j.pat;
    pForges = j.forges || [];
    pForgeHosts = j.hosts || {};
    if (!pForges.some(f => f.id === pForgeId)) pForgeId = (pForges[0] || {}).id || "";
    $("pKey").innerHTML = `<option value="">none: ${pPat
        ? "use the configured access token"
        : "public repository"}</option>`
      + pKeys.map(k => `<option value="${esc(k.name)}">${esc(k.name)}</option>`).join("");
    pShowKey(); pDraw();
  });
}

// The node picker on New project: the same list the settings dialog
// offers, fetched the first time it is needed. One node is picked for
// the person; several leave the choice open, with none as the last
// option rather than the first.
function pFillNode(){
  const sel = $("pNode"), wrap = $("pNodeField");
  if (!sel || !wrap) return;
  if (nodesList === null){
    const gen = pGen;
    loadNodes().then(() => { if (gen === pGen && !$("pmodal").hidden) pFillNode(); });
  }
  const pick = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired" && n.state !== "disabled");
  const shown = PMODES[pMode]?.fields.includes("pNodeField") && pick.length > 0;
  wrap.hidden = !shown;
  if (!shown){ sel.innerHTML = ""; return; }
  const was = sel.value;
  sel.innerHTML = pick.map(n => `<option value="${esc(n.id)}">${esc(n.name)}${
      n.live === false ? " (quiet)" : ""}</option>`).join("")
    + `<option value="">none: no builds, tests or Claude sessions until one is picked</option>`;
  // Several: the node most projects are bound to, not none. A project born
  // with no node had nowhere to send its container and used to land on the
  // newest enrolled node instead (the operator, 25 Sep).
  sel.value = pick.some(n => n.id === was) ? was
    : pick.length === 1 ? pick[0].id
    : pick.some(n => n.id === nodesDefault) ? nodesDefault : "";
}

function openNewProject(){ pLink = null; pOpen("init"); }

function openLinkProject(name){ pLink = name; pOpen("link"); }

function closeNewProject(){ pGen++; $("pmodal").hidden = true; $("pArchive").value = "";
  $("pArchiveName").textContent = "none picked"; $("pVersion").value = "0.1.0"; }

// A stale error must not survive a mode switch: "a name is required" makes
// no sense over a form that no longer asks for one.
const pSwitch = m => { if (pMode === m) return;
  pMode = m; $("pErrWrap").hidden = true; pDraw(); pSlide(); };

// What a typed name becomes. The server sanitizes for real; this is the same
// rule in the other language, so the operator can see the answer before
// pressing anything, and the two agreeing is checked by a test rather than
// hoped for. If they ever disagree the server wins, and the row that appears
// carries the name it actually made.
function pNameShow(){
  const raw = $("pName").value.trim();
  // Cloning with the field left empty takes the repository's name, so a
  // second copy is checked against THAT, not against an empty string. The
  // name shown follows GitHub's rule (ghName, registry.clean_name).
  const typed = raw || (pMode === "clone" ? repoOfUrl($("pUrl").value) : "");
  const eff = ghName(typed);
  // Since R154 a name in use is no refusal: the new project gets a
  // directory of its own and is shown as Name-2 beside the first.
  const shown = new Set((state?.projects || []).map(p => String(p.label || p.name).toLowerCase()));
  let as = eff, n = 2;
  while (as && shown.has(as.toLowerCase())) as = `${eff}-${n++}`;
  const empty = !!raw && !eff;
  $("pName").classList.toggle("bad", empty);
  $("pNamePreview").classList.toggle("bad", empty);
  $("pNamePreview").hidden = !empty && as === typed;
  $("pNamePreview").textContent = empty ? "A name needs at least one letter or digit in it"
    : as !== eff ? `${eff} is already a project's name, so this one is shown as ${as}`
    : `Shown as ${as}: names follow GitHub's rule, letters, digits, - _ and . only`;
}

// The repository's own name out of a clone URL: the same rule the server
// falls back to when the name field is empty.
function repoOfUrl(url){
  const last = (url || "").trim().replace(/\/+$/, "").split(/[/:]/).pop() || "";
  return last.endsWith(".git") ? last.slice(0, -4) : last;
}

// The name follows the address until somebody types one. Tracked rather than
// guessed from emptiness: clearing the field is itself a choice, and refilling
// it on the next keystroke of the URL would fight whoever did it.
let pNameTyped = false;

// Create, clone or link: the dialog's one submit, wired to #pCreate in index.html.
async function createProject() {
  // Captured at the click: the dialog can be closed, reopened and switched
  // to another mode while this request runs, and everything below must keep
  // talking about the flow the operator actually submitted.
  const mode = pMode, linkName = pLink, gen = pGen;
  const name = $("pName").value.trim();
  let url = $("pUrl").value.trim();
  const key = $("pKey").value;          // "" until this open's fetch offered any
  const file = mode === "init" ? $("pArchive").files[0] : null;
  const fail = m => gen === pGen
    ? ($("pErr").textContent = m, $("pErrWrap").hidden = false)
    : notify(`${mode === "link" ? projLabel(linkName) : name || mode}: ${m}`, true);
  if (mode === "init"){ if (!name) return fail("a name is required"); }
  else if (!url) return fail("a repository address is required");
  $("pErrWrap").hidden = true;
  const b = $("pCreate");
  b.disabled = true;
  b.textContent = { init: "Creating…", clone: "Starting…", link: "Starting…" }[mode];
  try{
    // A push has to authenticate somehow; catching this before the round-trip
    // spares typing a URL into a flow that cannot finish. Judged on the
    // pubkeys answer itself: awaited, so an early Create is not judged on
    // the pre-fetch defaults. (The server refuses it too; this is just the
    // earlier of the two answers.)
    const linkToken = mode === "link" && pLinkAuth === "token" ? $("pToken").value.trim() : "";
    const fg = pFg();
    // The pick is sent only when it was asked: for a server the address
    // names or one answered for before, the server reads the address.
    const forge = pForgeOf(pUrlHost(url)) ? "" : pForgeId;
    if (mode === "link" && pLinkAuth === "token" && !linkToken)
      return fail("an access token for this project: a push has to authenticate somehow");
    if (mode === "link" && pLinkAuth === "key" && !key){
      const auth = await pFetch;
      // The container's PAT is GitHub's and covers nothing else, so it is not
      // an answer for a host it was never minted for.
      if (!(auth && auth.pat && fg.id === "github"))
        return fail((auth && auth.keys || []).length
          ? `no credential is configured for ${fg.name}: pick a deploy key, or switch to an access token`
          : `no deploy key is available for ${fg.name}: switch to an access token, or add a deploy key and try again`);
    }
    // The archive goes first, on its own: the create request is a small
    // JSON body and the upload is not, so the server spools the bytes and
    // hands back an id the create quotes.
    let archive = "";
    if (file){
      b.textContent = "Uploading…";
      const u = await fetch("/api/upload-archive?name=" + encodeURIComponent(file.name),
                            {method: "POST", body: file});
      const uj = await u.json().catch(() => ({}));
      if (!u.ok) return fail(uj.error || `upload failed (HTTP ${u.status})`);
      archive = uj.id;
      b.textContent = "Creating…";
    }
    const r = mode === "link"
      ? await fetch("/api/link", {method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name: linkName, url, forge,
                                key: pLinkAuth === "key" ? key : "",
                                token: linkToken})})
      : await fetch("/api/create", {method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name, mode, url, about: $("pAboutField").hidden ? "" : $("pAbout").value, archive,
                                node: $("pNodeField").hidden ? "" : $("pNode").value,
                                // A starting version, for a fresh tree only: a
                                // clone keeps the history it came with.
                                version: mode === "init" ? $("pVersion").value.trim() : "",
                                gate: $("pGateField").hidden ? null : pGateNow(),
                                devbuild: $("pGateField").hidden ? null : ($("pGateDocker").value || "deny"),
                                sign: $("pGateField").hidden ? null : ($("pGateSign").value || "ask"),
                                keys: $("pGateField").hidden ? null : ($("pGateKeys").value || "ask"),
                                release: $("pGateField").hidden ? null : ($("pGateRelease").value || "ask"),
                                report: $("pGateField").hidden ? null : ($("pGateReport").value || "auto"),
                                key: mode === "clone" ? key : "",
                                forge: mode === "clone" ? forge : "",
                                token: mode === "clone" ? $("pToken").value.trim() : "",
                                push: mode === "clone" && $("pPush").checked})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return fail(j.error || `${mode} failed (HTTP ${r.status})`);
    if (gen === pGen) closeNewProject();
    // Everything that touches the network is a background job now, and it is
    // accepted, not finished. The dialog gets out of the way and the Projects
    // card carries it from here, which is also what happens if this page is
    // closed a second later.
    if (j.started){
      pJobSeen({running: true, kind: mode === "link" ? "link" : "clone",
                name: j.name || linkName, step: "starting", for: 0});
      pJobPoll();
    } else {
      notify(`${mode === "link" ? projLabel(linkName) : j.label || name || j.name} ${mode === "link" ? "linked" : "created"}: ${j.note || "ready"}`);
      refresh();                        // the new state, without waiting a poll
    }
  }catch(e){
    // The request may still be running server-side (a big clone or push
    // outlives a dropped connection), so say to look rather than blindly retry.
    fail("lost the connection; check the Projects card before trying again");
  }finally{
    if (gen === pGen){ b.disabled = false; b.textContent = PMODES[pMode].btn; }
  }
}
