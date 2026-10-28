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
    : k.adopted === "yes"
      ? `<div class="notice">INSTALL_KEY is copied into the secrets folder's key folder. Take it out of your secrets folder's
          .env file and restart: the install carries on with this same key, and it is changed here from then on.</div>`
    : k.adopted === "other"
      ? `<div class="notice warn">The key folder holds another key than INSTALL_KEY, which is the one in use. Keep INSTALL_KEY set,
          or move the key folder's key aside so the next start copies this one in.</div>`
    : `<div class="hint">Set in the environment. Mount the secrets folder read-write and restart, and it is copied into a key
        folder there, after which INSTALL_KEY can be taken out and the key changed here.</div>`;
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
// sealed with; and each token it gave a repository (a project's settings, a
// clone, a link to a host), kept here and not in the install's store, with
// the projects that use it (the operator, 27 Oct). Nothing is added here:
// a token arrives with the repository it was given for. Never shown and
// never downloaded: Change makes another key, Remove takes out a token no
// project uses, and Purge empties the store after a plain confirmation, no
// password or code asked, since a person who forgot theirs, or fears it
// stolen, must still be able to.
//
// An unlock that gives up less (R158 step 5): a token is opened per use for
// the window picked here (a quarter of an hour, an hour, eight hours, or
// while signed in), Lock lets go of everything opened, and the uses are
// listed under the store. A key of the person's own (R157): Hold the key
// yourself moves the store under a passkey's PRF secret or a key they keep,
// which the controller never holds, so it opens only while they unlock it.
let keyMine = null;
let keyMineRev = 0;
let keyMineAsked = false;
let keyMineUses = null;

async function loadKeyMine(){
  keyMineAsked = true;
  keyMine = await postKeys({action: "mine"});
  keyMineUses = (await postKeys({action: "uses"})).uses || [];
  keyMineRev++;
  drawPanes();
}

const KS_FORGE_COLS = [{label: "Token"}, {label: "Signed in as", w: "minmax(0,.7fr)"}, {label: "Used by"}, {act: true, w: "6.5rem"}];
const KS_USE_COLS = [{label: "When", w: "7rem"}, {label: "Token"}, {label: "For"}, {label: "By", w: "minmax(0,.6fr)"}];
const KS_FOR = [[900, "a quarter of an hour"], [3600, "an hour"], [28800, "eight hours"], [0, "while signed in"]];
const KS_WHY = {push: "a push", fetch: "a fetch", pull: "a pull", "ls-remote": "a look at the remote", read: "a read",
                git: "git", ci: "watching CI", release: "a release", wiki: "the wiki", unlocked: "unlocked", locked: "locked",
                "the window ended": "the window ended", "signed out everywhere": "signed out everywhere", purged: "purged",
                "moved to the project": "moved to the project's own keeping", "moved under your own key": "moved under your own key",
                "given back to this BuilderBot": "given back to this BuilderBot", "the controller restarted": "the controller restarted"};

function keyStoreHeld(m){
  return !m.own ? "this BuilderBot (the install key)" : m.how === "passkey" ? "your passkey" : "a key you keep";
}

function keyMineSection(){
  if (keyMine === null){ if (!keyMineAsked) loadKeyMine(); return ""; }
  const m = keyMine;
  if (m.error || !m.sealing) return "";
  const forgesHtml = (m.forges || []).length
    ? tblWrap(KS_FORGE_COLS, m.forges.map(f => `<div class="row">${tblLine(KS_FORGE_COLS, [
        esc(f.scheme === "http" ? "http://" + f.host : f.host), esc(f.login || "not said"),
        esc((f.projects || []).join(", ") || "nothing now"),
        (f.projects || []).length ? "" : `<button type="button" data-ksunlink="${esc(f.id)}">Remove</button>`])}</div>`).join(""), "ksforges")
    : `<div class="hint">No token yet. One you give a project's repository, in its settings or when you clone or link it, is kept here under your key.</div>`;
  const until = m.locked ? "locked" : m.until ? `until ${fmtTime(m.until * 1000, {hour: "numeric", minute: "2-digit"})}` : m.own ? "while signed in" : "";
  const locked = m.own && m.locked;
  const body = `${m.has || m.own ? factGrid([["Key", m.fingerprint, {cls: "keyfp"}], ["Held by", keyStoreHeld(m)],
      ["Open", locked ? "no" : until || "yes"], ["Made", KEYS_WHEN(m.made)],
      ["Changed", m.changed && m.changed !== m.made ? KEYS_WHEN(m.changed) : ""]]) : ""}${m.previous
      ? `<div class="notice">The key before this one is kept while ${m.previous_on_nodes} of your sign-in${
        m.previous_on_nodes === 1 ? "" : "s"} on the nodes ${m.previous_on_nodes === 1 ? "is" : "are"} still sealed under it.</div>` : ""}${locked
      ? `<div class="notice">Locked: nothing of yours opens until you unlock it, your pushes and pulls wait, and a terminal you open on a node asks for it first.</div>`
      : m.own ? `<div class="hint">Not even this BuilderBot's owner opens what is here without ${m.how === "passkey" ? "your passkey" : "the key you keep"}. Forgetting it means signing in to every agent again and giving each project a token again; Purge still works without it.</div>` : ""}
    ${forgesHtml}
    <div class="actbar"><label class="pick"><span class="pickw">Unlock for</span>
        <select id="ksFor">${KS_FOR.map(([v, l]) => `<option value="${v}"${v === m.for ? " selected" : ""}>${l}</option>`).join("")}</select></label>
      ${locked ? `<button type="button" class="primary" id="bKsUnlock">Unlock</button>` : `<button type="button" id="bKsLock">Lock</button>`}
      ${m.own ? `<button type="button" id="bKsOwnBack"${locked ? " disabled" : ""}>Give the key back</button>`
              : `${m.has ? `<button type="button" id="bKeyMine">Change key</button>` : ""}<button type="button" id="bKsOwn">Hold the key yourself</button>`}
      <button type="button" class="danger" id="bKsPurge">Purge</button></div>`;
  const uses = (keyMineUses || []).slice(0, 20);
  const usesHtml = uses.length
    ? tblWrap(KS_USE_COLS, uses.map(u => `<div class="row">${tblLine(KS_USE_COLS, [
        esc(ago(u.at)), esc(u.host ? `${u.host}${u.login ? ", as " + u.login : ""}` : "the store"),
        esc((KS_WHY[u.why] || u.why) + (u.project ? ` on ${u.project}` : "")),
        esc(u.by ? u.by : u.host ? "work that is nobody's" : "you")])}</div>`).join(""), "ksuses")
    : `<div class="hint">Nothing opened yet. Each time a token of yours is opened, for a push, a pull, CI or a release, it is listed here.</div>`;
  return docSection("profile", "mykey", "Your key store", m.own && m.locked ? "locked" : m.has || m.own ? m.fingerprint : "", body)
    + docSection("profile", "uses", "Uses of your tokens", String((keyMineUses || []).length || ""), usesHtml);
}

// The person's secret for their own key: their passkey's PRF answer, with
// the passkey's own proof, or the key they keep, typed. `said` is the
// question; null when they cancel.
async function keyStoreSecret(said, how = ""){
  const m = keyMine || {};
  const use = how || (m.how === "passkey" ? "passkey" : "key");
  if (use === "passkey"){
    if (!window.PublicKeyCredential) { notify("this browser has no passkeys: type the key you keep instead", true); return null; }
    try{
      const o = await postKeys({action: "prf-begin"});
      if (o.error) return null;
      const c = await navigator.credentials.get({publicKey: {challenge: pfU8(o.challenge), rpId: location.hostname,
        allowCredentials: o.ids.map(id => ({type: "public-key", id: pfU8(id)})), userVerification: "required", timeout: 60000,
        extensions: {prf: {eval: {first: pfU8(o.salt)}}}}});
      let first = null;
      try{ first = c.getClientExtensionResults().prf?.results?.first || null; }catch(e){ first = null; }
      return {passkey: {id: pfB64(c.rawId), client: pfB64(c.response.clientDataJSON), auth: pfB64(c.response.authenticatorData),
                        sig: pfB64(c.response.signature), prf: first ? pfB64(first) : ""}};
    }catch(e){ if (e.name !== "NotAllowedError") notify("the passkey did not answer: " + (e.message || e), true); return null; }
  }
  const key = await askText(said, {verb: "Unlock", label: "The key you keep (64 hex characters)"});
  return key ? {key: key.trim()} : null;
}

// Unlock, asked for by the Profile's button or by a terminal about to open:
// resolves once the store is open or the person declined.
async function keyStoreUnlock(said = "Unlock your key store?"){
  if (keyMine === null) keyMine = await postKeys({action: "mine"});
  const m = keyMine || {};
  if (!m.own || !m.locked) return true;
  const got = await keyStoreSecret(said);
  if (!got) return false;
  const j = await postKeys({action: "unlock", ...got, for: Number(document.getElementById("ksFor")?.value ?? m.for)});
  if (j.error) return false;
  notify("your key store is unlocked");
  if (state?.store) state.store.locked = false;
  await loadKeyMine();
  return true;
}

// The move under a key of the person's own (R157 step 1): how it is held,
// the projects whose background work runs with a token of theirs, said
// before they choose, and what it costs.
async function keyStoreOwn(b){
  const pre = await postKeys({action: "own-preview"});
  if (pre.error) return;
  const prfKeys = (pre.passkeys || []).filter(k => k.prf);
  const bg = pre.projects || [];
  const costs = "Not even this BuilderBot's owner opens your store without it. Forgetting it means signing in to every agent "
    + "again and giving each project a token again; Purge still works without it, an administrator's too.";
  const how = await ask({title: "Hold the key yourself?",
    text: costs + (window.PublicKeyCredential ? (prfKeys.length ? "\n\nYour passkey can hold it: the authenticator gives a secret the page only relays."
                                                 : "\n\nNone of your passkeys answers PRF, which holding a key needs: add one that does under Two-factor sign-in, or keep a key yourself.")
                                               : "\n\nThis browser has no passkeys, so the key is one you keep."),
    choices: [...(prfKeys.length ? [{label: "With my passkey", value: "passkey"}] : []), {label: "A key I keep", value: "key"}]});
  if (!how) return;
  let keep = [];
  if (bg.length){
    const list = bg.map(p => `${p.label} (${p.host}${p.login ? ", as " + p.login : ""})`).join(", ");
    const pick = await ask({title: "The tokens projects run with in the background?",
      text: `${bg.length === 1 ? "One project runs" : bg.length + " projects run"} CI watching and releases with a token of yours: ${list}.\n\n`
        + "Moved to each project's own keeping, that work goes on while your store is locked; kept under your key, it waits for you to unlock.",
      choices: [{label: "Move them to the projects", value: "move"}, {label: "Keep them under my key", value: "keep"}]});
    if (!pick) return;
    keep = pick === "keep" ? bg.map(p => p.project) : [];
  }
  let got;
  if (how === "passkey"){
    got = await keyStoreSecret("", "passkey");
  }else{
    const key = keyStoreNewKey();
    const saved = await ask({title: "Your key", text: "Save this key where you keep secrets (a password manager, the Windows companion); it is shown once and never again:\n\n" + key,
      choices: [{label: "I saved it", value: true}]});
    if (!saved) return;
    got = {key};
  }
  if (!got) return;
  busy(b, "Moving");
  const j = await postKeys({action: "own-key", ...got, keep});
  if (!j.error) notify(`your key store is under ${how === "passkey" ? "your passkey" : "the key you keep"}${(j.moved || []).length ? `; ${j.moved.length} project${j.moved.length === 1 ? "" : "s"} keep their own token now` : ""}`);
  loadKeyMine();
}

function keyStoreNewKey(){
  const a = new Uint8Array(32);
  crypto.getRandomValues(a);
  return [...a].map(x => x.toString(16).padStart(2, "0")).join("");
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
  on("bKsUnlock", async b => { busy(b, "Unlocking"); await keyStoreUnlock(); loadKeyMine(); });
  on("bKsLock", async b => { busy(b, "Locking"); await postKeys({action: "lock"}); if (state?.store) state.store.locked = !!keyMine?.own; loadKeyMine(); });
  on("bKsOwn", keyStoreOwn);
  on("bKsOwnBack", async b => {
    if (!await askYes("Give the key back to this BuilderBot? Its install key then opens your store again, and no passkey or key of yours is asked for.", {verb: "Give it back"})) return;
    busy(b, "Giving back");
    const j = await postKeys({action: "own-back"});
    if (!j.error) notify("your key store is under this BuilderBot's key again");
    loadKeyMine();
  });
  const sel = root.querySelector("#ksFor");
  if (sel) sel.onchange = async () => { await postKeys({action: "unlock-for", for: Number(sel.value)}); };
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
  on("bKsPurge", async b => {
    busy(b, "Purging");
    await keyStorePurge();
    loadKeyMine();
  });
  root.querySelectorAll("[data-ksunlink]").forEach(b => b.onclick = async () => {
    if (!await askYes("Remove this token from your key store?", {verb: "Remove", danger: true})) return;
    busy(b, "Removing");
    await postKeys({action: "unlink-forge", id: b.dataset.ksunlink});
    loadKeyMine();
  });
}
