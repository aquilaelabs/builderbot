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
      title="a fresh local repo, or a clone"
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

// ---- the new-project dialog ------------------------------------------------
// One dialog, three modes: a new local repo, a clone, and linking a project
// to a git host. The host catalog and the agent's keys arrive per open from
// /api/pubkeys. Moved here from index.html with bb map sections in hand: the
// dialog is the Projects feature's. Its fields, its submit and the name
// that follows the address are wired from index.html.

const PMODES = {
  init:  { title: () => "New project", btn: "Create", focus: "pName",
           fields: ["pSrcField", "pNameField", "pVersionField", "pNodeField", "pGateField", "pArchiveField", "pAboutField"] },
  clone: { title: () => "New project", btn: "Create", focus: "pUrl",
           fields: ["pSrcField", "pNameField", "pNodeField", "pGateField", "pUrlField", "pForgeField",
                    "pPushField", "pTokenField", "pKeyField"] },
  link:  { title: () => `Link ${pLink} to a git host`, btn: "Link", focus: "pUrl",
           fields: ["pForgeField", "pUrlField", "pLinkAuthField", "pKeyField",
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

let pForgeId = "github";

// What the operator has already said their own servers run, by host. The
// clone form asks which host only for an address on a server nobody has
// answered for yet: the second project from the same Gitea is not asked.
let pForgeHosts = {};

// The host the current pick was made for, so a fresh address gets a fresh
// question rather than the last one's answer.
let pAskedHost = "";

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
  // What the token field is about: the picked entry when linking, and the
  // address's own host when cloning, which is where the host comes from there.
  const fg = pMode === "clone"
    ? (pForgeOf(pUrlHost($("pUrl").value)) || pForge()) : pForge();
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
    ? `Used for ${pLink} only.` + (fg.creates ? ` Checked with ${fg.name} first.` : "")
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
// The host row: the catalog as a select, and a box for the address when the
// picked one is somebody's own server rather than a single public site.
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
    sel.innerHTML = pForges.map(f =>
      `<option value="${esc(f.id)}">${esc(f.name)}${f.dev ? " (dev)" : ""}</option>`).join("");
    sel.dataset.built = String(pForges.length);
  }
  // Cloning: the URL is the subject and the host is in it, so this is not a
  // second place to type one. It is one question: what is running on that
  // server, and it is asked only when the address is on a server that does
  // not name itself and nobody has answered for. Which means a paste of a
  // GitHub URL never sees it, and a Gitea is asked about once ever.
  if (pMode === "clone"){
    const host = pUrlHost($("pUrl").value);
    const named = pForgeOf(host);
    $("pForgeField").hidden = !host || !!named;
    $("pForgeHost").hidden = true;
    if (!$("pForgeField").hidden){
      // A server nobody has answered for starts on the entry that promises
      // nothing, not on GitHub: the question is what this one runs, and a
      // default that names a different server is an answer nobody gave.
      if (pAskedHost !== host){ pAskedHost = host; pForgeId = "git"; }
      sel.value = pForgeId;
      $("pForgeHint").textContent =
        `Which software ${host} runs. Asked once per server.`;
    }
    return;
  }
  sel.value = pForgeId;
  const f = pForge();
  $("pForgeHost").hidden = !!f.fixed;
  if (f.fixed) $("pForgeHost").value = "";
  $("pForgeHint").textContent = f.about;
  // The address box follows the host, so the shape being asked for is the
  // shape of the thing they are about to paste.
  const h = pHost() || "your-host";
  $("pUrl").placeholder = pLinkAuth === "key"
    ? `git@${h}:owner/repo.git` : `https://${h}/owner/repo.git`;
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

// What the operator typed for a self-hosted one, or the entry's own fixed
// host. Trimmed of a pasted scheme and trailing slash, because people paste
// the address bar.
const pHost = () => {
  const f = pForge();
  if (f.fixed && f.host) return f.host;
  return $("pForgeHost").value.trim()
    .replace(/^[a-z]+:\/\//i, "").replace(/\/.*$/, "");
};

function pShowKey(){
  const k = pKeys.find(k => k.name === $("pKey").value);
  $("pPubWrap").hidden = !k;
  if (k) $("pPub").value = k.pub;
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
const P_GATE_IDS = {roadmap: "pGateRoadmap", bugs: "pGateBugs", rules: "pGateRules", settings: "pGateSettings"};
const pGateNow = () => Object.fromEntries(
  Object.entries(P_GATE_IDS).map(([k, id]) => [k, $(id).value || "auto"]));
function pFillGates(){
  for (const id of [...Object.values(P_GATE_IDS), "pGateDocker"]){
    const el = $(id);
    if (el.dataset.built !== "1"){
      el.innerHTML = GATE_MODES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
      el.dataset.built = "1";
    }
    // Running its container starts at deny, the setting's own default: it
    // runs the project's code on a shared machine, which the notebook's
    // four do not.
    el.value = id === "pGateDocker" ? "deny" : "auto";
  }
}

function pOpen(mode){
  const gen = ++pGen;
  pMode = mode; pKeys = []; pPat = false; pFillGates(); pDraw();
  $("pName").value = $("pUrl").value = $("pAbout").value = "";
  $("pToken").value = "";
  pAskedHost = "";
  // Every open starts on GitHub rather than on whatever the last one picked:
  // the host is the first thing decided and a remembered pick would be a
  // silent one.
  pForgeId = "github";
  $("pForgeHost").value = "";
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
  const pick = (nodesList || []).filter(n => n.kind !== "local" && n.state !== "retired");
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
