// The Keys page (R154), Controller's, an administrator's: the install key
// and everything the install keeps sealed under it. With INSTALL_KEY not
// set the install made its own key at its first start (lib/boot.sh), which
// this page shows to save and changes, live: what is kept under it is
// sealed again under the new one at once. A key set in the environment is
// shown and changed there. Each account's own key, for its sign-ins on the
// nodes, is on its Profile (keyMineSection).
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// POST /api/keys, read when the page opens and after each change.

"use strict";

let keysData = null;             // {install, kept}, or null before the first read
let keysErr = "";
let keysRev = 0;
let keysShown = "";              // the key, while an administrator has it shown

function openKeysTab(){
  openTab({kind: "keys", arg: "__keys", label: "Keys"});
}

async function postKeys(body){
  try{
    const j = await (await postJSON("/api/keys", body)).json();
    if (j.error) notify(j.error, true);
    return j;
  }catch(e){
    notify("keys: " + failWords(e), true);
    return {error: String(e)};
  }
}

async function loadKeys(){
  const j = await postKeys({action: "status"});
  keysErr = j.error || "";
  keysData = j.error ? keysData : j;
  keysRev++;
  if (tabs.some(t => t.kind === "keys")) drawPanes();
}

// Where the key is kept, in a person's words.
const KEYS_WHERE = {secrets: "the secrets folder", state: "beside the state, in /config", env: "the environment (INSTALL_KEY)"};
const KEYS_KIND = {git: "Git token", setting: "Controller setting", signing: "Signing key", "two-factor": "Two-factor",
                   account: "Account key", forge: "Linked forge", "sign-in": "Agent sign-in"};
const KEYS_WHEN = s => s ? new Date(s * 1000).toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"}) : "";

function keysNotices(k){
  const out = [];
  if (!k.where){
    out.push(`<div class="notice warn">This install has no key, so what it keeps is not sealed. One is made at the next start
      when INSTALL_KEY is not set and the secrets folder or the state can take it.</div>`);
    return out.join("");
  }
  if (k.where === "state")
    out.push(`<div class="notice warn">The key is kept beside the state, so a copy of /config carries it. Mount a secrets
      folder the controller may write to and restart, and it moves there.</div>`);
  if (k.changeable && !k.saved)
    out.push(`<div class="notice warn">Save a copy of this key somewhere apart from /config: restoring a backup on a new
      install opens nothing that was sealed without it.</div>`);
  if (k.previous)
    out.push(`<div class="notice">The key before this one is kept while ${k.previous_on_nodes} sign-in${
      k.previous_on_nodes === 1 ? "" : "s"} on the nodes ${k.previous_on_nodes === 1 ? "is" : "are"} still sealed
      under it; each moves to this key when its person next opens a terminal there.</div>`);
  return out.join("");
}

function keysInstallBody(k){
  if (!k.where) return keysNotices(k);
  const shown = keysShown ? `<div class="field keyshown"><code class="keyval">${esc(keysShown)}</code>
    <div class="actbar"><button type="button" id="bKeyCopy">Copy</button><button type="button" id="bKeyDown">Download</button>${
      k.saved ? "" : `<button type="button" class="primary" id="bKeySaved">I saved it</button>`}
      <button type="button" id="bKeyHide">Hide</button></div></div>` : "";
  const acts = k.changeable
    ? `<div class="actbar">${keysShown ? "" : `<button type="button" id="bKeyShow">Show</button>`}
        <button type="button" id="bKeyChange">Change</button></div>`
    : `<div class="hint">Set in the environment: change INSTALL_KEY in the secrets folder and restart.</div>`;
  return keysNotices(k) + shown + acts;
}

function keysKeptBody(rows){
  if (!rows.length) return `<div class="empty">nothing is kept under the key yet</div>`;
  const cols = [{label: "Name"}, {label: "Kind", w: "9rem"}, {label: "Used for"}, {label: "Kept", w: "6rem"}, {act: true, w: "5.5rem"}];
  return tblWrap(cols, rows.map((r, i) => `<div class="row">${tblLine(cols, [
    esc(r.name), esc(KEYS_KIND[r.kind] || r.kind), esc(r.uses),
    r.sealed ? "sealed" : `<span class="warn">not sealed</span>`,
    `<button type="button" data-keygo="${i}" title="where this is changed">Open</button>`])}</div>`).join(""), "keystbl");
}

function renderKeysInto(i){
  const d = docSurface(i, "keys");
  if (!d) return;
  if (keysData === null){
    d.setBar("");
    d.list.innerHTML = keysErr ? `<div class="field"><div class="notice bad">${esc(keysErr)}</div></div>`
      : skTpl(pageHead({facts: [["Install key", GHOST], ["Kept in", GHOST], ["Saved", GHOST]]})
        + docSection("keys", "install", "Install key", "", skRows(1)) + docSection("keys", "kept", "Kept under it", "", skRows(3)));
    if (!keysErr) loadKeys();
    return;
  }
  const k = keysData.install || {}, rows = keysData.kept || [];
  d.setBar("");
  d.list.innerHTML = pageHead({facts: k.where ? [
      ["Install key", k.fingerprint, {cls: "keyfp"}], ["Kept in", KEYS_WHERE[k.where]],
      ["Made", KEYS_WHEN(k.made)], ["Changed", k.changed && k.changed !== k.made ? KEYS_WHEN(k.changed) : ""],
      ["Saved", k.changeable ? (k.saved ? "yes" : "not yet") : ""]] : [["Install key", "none"]]})
    + docSection("keys", "install", "Install key", k.where ? k.fingerprint : "none", keysInstallBody(k),
                 {cls: k.where && (k.where === "state" || (k.changeable && !k.saved)) ? "warn" : ""})
    + docSection("keys", "kept", "Kept under it", String(rows.length), keysKeptBody(rows));
  wireKeys(d.el);
}

function keysGo(r){
  const [where, arg] = r.go || [];
  if (where === "project") return openProjectSettings(arg);
  if (where === "controller") return openSettingsTab();
  if (where === "profile") return openProfileTab();
  if (where === "user") return openUsersTab();
  if (where === "agents") return openAgentsTab(arg);
}

async function keysChange(btn){
  const how = await ask({title: "Change the install key?",
    text: "Everything kept under it is sealed again under the new key at once, and the one before is kept while the "
      + "nodes still need it. People stay signed in until the next restart, when each signs in once more.\n\n"
      + "Save the new key afterwards: a backup made before the change needs the key it was made under.",
    choices: [{label: "Make a new key", value: "make"}, {label: "Paste one", value: "paste"}]});
  if (!how) return;
  let key = "";
  if (how === "paste"){
    key = await askText("The new install key", {verb: "Change", label: "32 to 256 letters, digits or + / = _ . -"});
    if (!key) return;
  }
  busy(btn, "Changing");
  const j = await postKeys({action: "change", key});
  if (!j.error){
    notify(`install key changed; ${j.resealed} sealed again under it`);
    keysShown = "";
  }
  loadKeys();
}

function wireKeys(root){
  wireSections(root);
  const on = (id, fn) => { const b = root.querySelector("#" + id); if (b) b.onclick = () => fn(b); };
  on("bKeyShow", async b => {
    busy(b, "Showing");
    const j = await postKeys({action: "show"});
    keysShown = j.key || "";
    keysRev++;
    drawPanes();
  });
  on("bKeyHide", () => { keysShown = ""; keysRev++; drawPanes(); });
  on("bKeyCopy", async () => {
    try{ await navigator.clipboard.writeText(keysShown); notify("install key copied"); }
    catch(e){ notify("copy: " + failWords(e), true); }
  });
  on("bKeyDown", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([`INSTALL_KEY=${keysShown}\n`], {type: "text/plain"}));
    a.download = "builderbot-install-key.env";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  on("bKeySaved", async b => {
    busy(b, "Saving");
    await postKeys({action: "saved", fingerprint: keysData?.install?.fingerprint || ""});
    keysShown = "";
    loadKeys();
  });
  on("bKeyChange", keysChange);
  root.querySelectorAll("[data-keygo]").forEach(b => b.onclick = () => keysGo((keysData?.kept || [])[+b.dataset.keygo]));
}

// ---- an account's own key store, on its Profile ---------------------------
// What is kept under the account's own key (R154): the key, made for it and
// kept by the controller, which its coding agents' sign-ins on the nodes are
// sealed with; each forge token it linked, which its own git work uses
// before a project's and which a project may be linked to; and the projects
// linked to it. Never shown and never downloaded (the operator, 27 Oct):
// Change makes another key, Remove takes one forge out, and Purge empties
// the store after a plain confirmation, no password or code asked, since a
// person who forgot theirs, or fears it stolen, must still be able to.
let keyMine = null;
let keyMineRev = 0;
let keyMineAsked = false;

async function loadKeyMine(){
  keyMineAsked = true;
  keyMine = await postKeys({action: "mine"});
  keyMineRev++;
  drawPanes();
}

const KS_FORGE_COLS = [{label: "Forge"}, {label: "Signed in as", w: "minmax(0,.8fr)"}, {label: "Linked", w: "7rem"}, {act: true, w: "6.5rem"}];

function keyMineSection(){
  if (keyMine === null){ if (!keyMineAsked) loadKeyMine(); return ""; }
  const m = keyMine;
  if (m.error || !m.sealing) return "";
  const forgesHtml = (m.forges || []).length
    ? tblWrap(KS_FORGE_COLS, m.forges.map(f => `<div class="row">${tblLine(KS_FORGE_COLS, [
        esc(f.scheme === "http" ? "http://" + f.host : f.host), esc(f.login || "not said"), esc(KEYS_WHEN(f.at)),
        `<button type="button" data-ksunlink="${esc(f.host)}">Remove</button>`])}</div>`).join(""), "ksforges")
    : `<div class="hint">Nothing linked yet. A token linked here is used for your own git work ahead of a project's, and a project can be linked to it from its settings.</div>`;
  const projects = (m.projects || []).length
    ? `<div class="sub">Linked to it: ${(m.projects || []).map(p => esc(projLabel(p))).join(", ")}</div>` : "";
  const body = `${m.has ? factGrid([["Key", m.fingerprint, {cls: "keyfp"}], ["Made", KEYS_WHEN(m.made)],
      ["Changed", m.changed && m.changed !== m.made ? KEYS_WHEN(m.changed) : ""]]) : ""}${m.previous
      ? `<div class="notice">The key before this one is kept while ${m.previous_on_nodes} of your sign-in${
        m.previous_on_nodes === 1 ? "" : "s"} on the nodes ${m.previous_on_nodes === 1 ? "is" : "are"} still sealed under it.</div>` : ""}
    ${forgesHtml}${projects}
    <div class="setrow col ctlrow ksadd">
      ${lbl("ksToken", "Link a forge", "its host (http://host for a forge on plain http) and a personal access token; checked with the forge, then kept under your key")}
      <div class="ksaddrow"><input id="ksHost" value="github.com" spellcheck="false" autocomplete="off" aria-label="forge host">
        <input id="ksToken" type="password" autocomplete="off" spellcheck="false" placeholder="token" aria-label="token"></div>
    </div>
    <div class="actbar"><button type="button" id="bKsLink">Link</button>${m.has ? `<button type="button" id="bKeyMine">Change key</button>` : ""}
      <button type="button" class="danger" id="bKsPurge">Purge</button></div>`;
  return docSection("profile", "mykey", "Your key store", m.has ? m.fingerprint : "", body);
}

async function keyStorePurge(account = ""){
  const whose = account ? `${account}'s` : "your";
  const ok = await askYes(`Purge ${whose} key store?`, {verb: "Purge", danger: true,
    title: `Purge ${whose} key store?`});
  if (!ok) return null;
  const j = await postKeys(account ? {action: "purge-for", account} : {action: "purge"});
  if (!j.error) notify(`${account ? account + "'s" : "your"} key store purged${(j.unlinked || []).length
    ? `; ${j.unlinked.length} project${j.unlinked.length === 1 ? "" : "s"} unlinked` : ""}`);
  return j;
}

function wireKeyMine(root){
  const on = (id, fn) => { const b = root.querySelector("#" + id); if (b) b.onclick = () => fn(b); };
  on("bKeyMine", async b => {
    const how = await ask({title: "Change your key?",
      text: "What your key store keeps is sealed again under the new key at once. Your sign-ins on the nodes move to it the next time you open a terminal there.",
      choices: [{label: "Make a new key", value: "make"}, {label: "Paste one", value: "paste"}]});
    if (!how) return;
    let key = "";
    if (how === "paste"){
      key = await askText("Your new key", {verb: "Change", label: "64 hex characters"});
      if (!key) return;
    }
    busy(b, "Changing");
    const j = await postKeys({action: "change-mine", key});
    if (!j.error) notify("your key changed");
    loadKeyMine();
  });
  on("bKsLink", async b => {
    const host = root.querySelector("#ksHost")?.value.trim() || "", token = root.querySelector("#ksToken")?.value.trim() || "";
    if (!token) return notify("paste a token to link", true);
    busy(b, "Linking");
    const j = await postKeys({action: "link-forge", host, token});
    if (!j.error) notify(`${j.host} linked${j.login ? " as " + j.login : ""}`);
    loadKeyMine();
  });
  on("bKsPurge", async b => {
    busy(b, "Purging");
    await keyStorePurge();
    loadKeyMine();
  });
  root.querySelectorAll("[data-ksunlink]").forEach(b => b.onclick = async () => {
    if (!await askYes(`Remove your ${b.dataset.ksunlink} token from your key store?`, {verb: "Remove", danger: true})) return;
    busy(b, "Removing");
    await postKeys({action: "unlink-forge", host: b.dataset.ksunlink});
    loadKeyMine();
  });
}
