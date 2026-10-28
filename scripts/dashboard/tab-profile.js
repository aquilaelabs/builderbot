// The Profile tab: the signed-in account's own settings, who they are,
// how their commits are signed, and their password. Its own classic script
// beside index.html, per the new-surface rule; chrome from docSurface(),
// conformance held by uniform.mjs.
//
// Per ACCOUNT, and only ever the account asking: the server answers
// /api/profile for whoever is signed in, so there is nothing here to pick
// and nothing an administrator does on somebody's behalf; that is the
// Users tab. The commit identity lives here rather than in a project's
// settings because two people on one project are two authors: it reaches
// every session this account starts as git's environment, which outranks
// whatever a repository has configured.

"use strict";

let profile = null, profileRev = 0;
// Typed and not yet saved, kept across the poll's redraws: a field that
// emptied itself mid-sentence would be unusable (docs/design-language.md,
// Settings; nothing takes effect until Save).
const profileDraft = {};
// This browser's zone and every zone it knows, alphabetically after it. UTC
// by that name, which some browsers leave out of their own list.
function tzOptions(cur){
  const own = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  let zones = [];
  try{ zones = Intl.supportedValuesOf("timeZone"); }catch(e){ zones = own ? [own] : []; }
  if (!zones.includes("UTC")) zones = [...zones, "UTC"];
  return optionList([["", `This device's own${own ? ` (${own})` : ""}`], ...[...zones].sort()], cur || "");
}

function openProfileTab(){
  openTab({kind: "profile", arg: "__profile", label: "Profile"});
}

async function loadProfile(){
  try{
    const r = await bootFetch("/api/profile");
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    profile = j;
  }catch(e){ notify("profile: " + failWords(e), true); return; }
  profileRev++;
  if (tabs.some(t => t.kind === "profile")) drawPanes();
}

// Key, label, what the ? beside it says, input type. The label sits above
// the field and the explanation rides the help icon (docs/design-language.md,
// Controls): a filled-in field still says what it is.
const PROFILE_FIELDS = [
  ["account", "Account name", "what you sign in with. Changing it signs your other browsers out", "text"],
  ["full_name", "Your name", "", "text"],
  ["email", "Your email", "", "email"],
  ["git_name", "Git name", "on your commits. Blank means your name", "text"],
  ["git_email", "Git email", "on your commits. Blank means your email; a GitHub noreply address keeps yours out of the log", "email"],
];

// Each section's line on the list beside it.
const PROFILE_SAYS = {
  you: "your name, email and commit author", may: "what your roles let you do",
  password: "change it, signing out everywhere",
  twofactor: "an authenticator app, passkeys and recovery codes",
  mykey: "your key, the tokens you gave repositories, and Purge",
  terminal: "the size, cursor and colors of your terminals",
  devices: "your browsers and apps, to sign out",
};
// The apps signed in as this account on its own machines (R272 step 1), the
// last of Profile's sections (the operator, 19 Oct): a table, a line a device (its name,
// what it is, when it last called) with Disconnect at its end, which signs
// that one out.
const PF_DEVICE_COLS = [{label: "Device"}, {label: "Kind", w: "6rem"}, {label: "Last call", w: "minmax(0,.6fr)"}, {act: true, w: "8rem"}];
// ...and the browsers signed in as the account (R158 step 8), each bound
// to the browser it was made in, this one first; Sign out ends one, and a
// cookie copied elsewhere already opens nothing.
const PF_SIGNIN_COLS = [{label: "Browser"}, {label: "From", w: "minmax(0,.7fr)"}, {label: "Last used", w: "minmax(0,.6fr)"}, {act: true, w: "8rem"}];

function profileSignins(rows){
  if (!rows.length) return "";
  return tblWrap(PF_SIGNIN_COLS, rows.map(r => `<div class="row" data-signin="${esc(r.id)}">${tblLine(PF_SIGNIN_COLS, [
    esc(r.agent) + (r.mine ? ` <span class="dim">(this one)</span>` : ""), esc(r.ip || ""), esc(r.last ? ago(r.last) : "never"),
    `<button type="button"${r.mine ? "" : ' class="danger"'} data-pfsignout="${esc(r.id)}">Sign out</button>`])}</div>`).join(""), "pfsignins");
}
const PF_DEVICE_KIND = {pc: "PC", phone: "Phone", editor: "Editor"};
// `of` names the account when an administrator reads it on the Users page
// (R272 step 8), whose Disconnect asks for that account.
function profileDevices(rows, of = ""){
  if (!rows.length) return of ? `<div class="hint">No device is signed in as ${esc(of)}.</div>`
    : `<div class="empty">No device yet. The Windows companion signs in here with your name and password, and is listed for you to disconnect.</div>`;
  return tblWrap(PF_DEVICE_COLS, rows.map(d => `<div class="row" data-device="${esc(d.id)}">${tblLine(PF_DEVICE_COLS, [
    esc(d.name), esc(PF_DEVICE_KIND[d.kind] || d.kind), esc(d.seen ? ago(d.seen) : "never"),
    `<button type="button" class="danger" data-pfdevout="${esc(d.id)}"${of ? ` data-devof="${esc(of)}"` : ""}>Disconnect</button>`])}</div>`).join(""), "pfdevices");
}

function renderProfileInto(i){
  const d = docSurface(i, "profile");
  if (!d) return;
  if (!profile){
    // Its template (R218 step 16): every heading and field label here is the
    // page's own; what is yours to fill them is on its way.
    // A page of settings as it lands (skSplit): the sections listed, Who
    // you are picked beside them with its fields.
    const fld = label => skField(label, 18);
    d.setBar("");
    splitOff(d.list);                   // drawn before: its grid is the template's to bring
    d.list.innerHTML = skTpl(skSplit([["Who you are", PROFILE_SAYS.you], ["What you may do", PROFILE_SAYS.may],
      ["Password", PROFILE_SAYS.password]], "Who you are", PROFILE_FIELDS.map(([, label]) => fld(label)).join(""),
      pageHead({title: GHOST, facts: [["Roles", GHOST], ["Owner of", GHOST]]})));
    return;
  }
  const p = {...(profile.profile || {}), account: profile.name}, g = profile.git || {};
  const val = k => profileDraft[k] ?? p[k] ?? "";
  const dirty = PROFILE_FIELDS.some(([k]) => (profileDraft[k] ?? p[k] ?? "") !== (p[k] ?? ""));
  const wm = profile.what_may || {roles: [], may: []};
  // Who this is, as a node's head says what it is (the operator, 25 Oct:
  // a run-on mono line could not be read): the name, the roles as facts,
  // the projects owned on a line of their own, each agent's account its own.
  d.setBar("");
  const owns = wm.roles.filter(r => /^Owner of /.test(r)).map(r => r.slice(9));
  const held = wm.roles.filter(r => !/^Owner of /.test(r));
  const by = {...(profile.claude ? {claude: profile.claude} : {}), ...(profile.agents || {})};
  const head = pageHead({title: profile.name, facts: [
    ["Roles", held.length ? held.join(", ") : "no role"],
    ["Owner of", owns.join(", ")],
    ...AGENTS.filter(a => by[a.id]).map(a => [a.name, by[a.id]])]});
  // A page of settings (page-docs.js splitSects, the operator, 16 Oct):
  // each block a section, the sections a list beside the one picked; who
  // you are first, since that is what is changed here most.
  const sec = (id, title, inner) => docSection("profile", id, title, "",
    `<div class="row stack2"><div class="grow">${inner}</div></div>`);
  d.list.innerHTML = `${head}
    ${sec("you", "Who you are", `
        <div class="logset">
          ${PROFILE_FIELDS.map(([k, label, hint, type]) => `
            <div class="logdays setrow col ctlrow">
              ${lbl("pf_" + k, label, hint)}
              <input id="pf_${k}" type="${type}" data-pf="${k}" value="${esc(val(k))}"
                     spellcheck="false" autocomplete="off">
            </div>`).join("")}
          <div class="actbar">
            <span class="state${profile.git_ready === false ? " warn" : ""}">${
              profile.git_ready === false
                ? "no author for commits yet: a session waits for a name and an email here"
                : `commits are signed ${esc(g.name)} &lt;${esc(g.email)}&gt;`}</span>
            <button type="button" id="pfSave" class="primary"${dirty ? "" : " disabled"}>Save</button>
          </div>
        </div>`)}
    ${sec("may", "What you may do", `
        ${wm.may.length ? factGrid(wm.may) : `<div class="hint">nothing yet: an administrator gives you a role</div>`}`)}
    ${sec("password", "Password", `
        <div class="logset">
          <div class="logdays setrow col ctlrow">
            ${lbl("pfCur", "Current password")}
            <input id="pfCur" type="password" autocomplete="current-password">
            <div class="notice bad" id="pfCurWhy" hidden></div>
          </div>
          <div class="logdays setrow col ctlrow">
            ${lbl("pfNew", "New password", "at least 8 characters; every browser signed in as you signs out")}
            <input id="pfNew" type="password" autocomplete="new-password">
            <div class="notice bad" id="pfNewWhy" hidden></div>
          </div>
          <div class="logdays setrow col ctlrow">
            ${lbl("pfNew2", "New password again")}
            <input id="pfNew2" type="password" autocomplete="new-password">
            <div class="notice bad" id="pfNew2Why" hidden></div>
          </div>
          <div class="actbar">
            <span class="state"></span>
            <button type="button" id="pfPasswd" disabled>Change password</button>
          </div>
        </div>`)}
    ${sec("twofactor", "Two-factor sign-in", profileTwoFactor(profile.two_factor || {}, !!profile.two_factor_required))}
    ${keyMineSection()}
    ${sec("terminal", "Your terminal", profileTerminal())}
    ${docSection("profile", "devices", "Signed in as you", "", profileSignins(profile.signins || []) + profileDevices(profile.devices || []))}`;
  wireSections(d.list);
  splitSects(d.list, "profile", {says: PROFILE_SAYS, back: "Profile"});
  wireProfile(d.el);
  wireDeviceOut(d.el);
  wireTwoFactor(d.el);
  wireKeyMine(d.el);
  wireTerminalLook(d.el);
}

// Your terminal (R133 step 10): its text size, cursor and colors, yours in
// every tab of BuilderBot's own terminal, applied as picked as the gear's
// appearance is. A project's own colors, in your settings for it, win there.
const PF_TERM = [
  ["size", "Text size", [9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 24].map(n => [String(n), `${n}px`]), "13"],
  ["cursor", "Cursor", [["bar", "bar"], ["block", "block"], ["underline", "underline"]], "block"],
  // Default first, as the page's own Default leads its schemes; the rest A to Z.
  ["scheme", "Colors", [["default", "default"], ["amber", "amber"], ["blue", "blue"], ["dashboard", "the dashboard's scheme"],
                        ["green", "green"], ["light", "light"], ["red", "red"]], "default"],
];
function profileTerminal(){
  const look = state?.term_look || {}, scheme = look.scheme || "default";
  const mine = (look.colors || {})[scheme] || {}, pal = termPalette(scheme, mine);
  // Under the preset, each of its colors with its own swatch (the operator,
  // 25 Oct): a change is this person's to that preset, Reset takes it away.
  const swatch = ([k, name]) => `<label class="tcolor${k in mine ? " mine" : ""}">
      <input type="color" data-pftcolor="${k}" value="${esc(pal[k] || "#000000")}" aria-label="${esc(name)}">
      <span>${esc(name)}</span></label>`;
  return `<div class="logset">${PF_TERM.map(([k, label, opts, dflt]) => `
      <div class="logdays setrow col ctlrow">
        ${lbl("pfTerm_" + k, label)}
        <select id="pfTerm_${k}" data-pfterm="${k}">${opts.map(([v, w]) =>
          `<option value="${v}"${String(look[k] ?? dflt) === v ? " selected" : ""}>${esc(w)}</option>`).join("")}</select>
      </div>`).join("")}
      <div class="logdays setrow ctlrow"><label class="ndcap"><input type="checkbox" data-pfterm="blink"${look.blink === false ? "" : " checked"}> The cursor blinks</label></div>
    </div>
    <div class="field">${lbl("pfTermColors", `The colors of ${PF_TERM[2][2].find(([v]) => v === scheme)?.[1] || scheme}`)}
      <div class="tcolors" id="pfTermColors">${TERM_COLOR_NAMES.map(swatch).join("")}</div>
      ${Object.keys(mine).length ? `<div class="actbar"><span class="state">${Object.keys(mine).length} of them yours</span>
        <button type="button" data-pftreset>Reset to the preset</button></div>` : ""}</div>
    <div class="field">${lbl("pfTermPreview", "How it looks")}<div id="pfTermPreview">${termPreview(pal, look)}</div></div>`;
}
// The look as the fields say it now, the colors changed of the scheme picked.
function termLookPicked(root){
  const term = {}, was = state?.term_look || {};
  root.querySelectorAll("[data-pfterm]").forEach(x => {
    const k = x.dataset.pfterm;
    term[k] = k === "blink" ? x.checked : k === "size" ? Number(x.value) : x.value;
  });
  const colors = {...(was.colors || {})}, base = termPalette(term.scheme, {});
  const mine = {};
  root.querySelectorAll("[data-pftcolor]").forEach(i => { if (i.value.toLowerCase() !== String(base[i.dataset.pftcolor]).toLowerCase()) mine[i.dataset.pftcolor] = i.value; });
  // The swatches are the scheme's that was showing: a new scheme brings its own.
  if (term.scheme === (was.scheme || "default")){
    if (Object.keys(mine).length) colors[term.scheme] = mine; else delete colors[term.scheme];
  }
  term.colors = colors;
  return term;
}
function wireTerminalLook(root){
  const save = async term => {
    try{
      const j = await (await postJSON("/api/users", {action: "prefs", prefs: {term}})).json();
      if (j.error) return notify(j.error, true);
    }catch(e){ return notify("could not reach the controller: " + failWords(e), true); }
    refresh();
  };
  const preview = () => {
    const t = termLookPicked(root), box = root.querySelector("#pfTermPreview");
    if (box) box.innerHTML = termPreview(termPalette(t.scheme, t.colors[t.scheme]), t);
  };
  root.querySelectorAll("[data-pfterm]").forEach(el => el.onchange = () => { preview(); save(termLookPicked(root)); });
  // A swatch redraws the preview as it is dragged and saves when it is let go.
  root.querySelectorAll("[data-pftcolor]").forEach(el => {
    el.oninput = preview;
    el.onchange = () => save(termLookPicked(root));
  });
  root.querySelectorAll("[data-pftreset]").forEach(b => b.onclick = () => {
    const t = termLookPicked(root);
    delete t.colors[t.scheme];
    save(t);
  });
}

// Disconnect: asked, then that device signed out; the app finds its token
// refused on its next call and says to sign in again. One of another
// account's, on the Users page, is an administrator's to cut off for them.
function wireDeviceOut(root){
  root.querySelectorAll("[data-pfsignout]").forEach(b => b.onclick = async () => {
    const r = (profile?.signins || []).find(x => x.id === b.dataset.pfsignout);
    if (!await askYes(r?.mine ? "Sign out this browser?" : `Sign out ${r ? r.agent : "that browser"}? Its next request finds it signed out.`)) return;
    busy(b, "Signing out");
    try{
      const j = await (await postJSON("/api/profile", {action: "signin-out", id: b.dataset.pfsignout})).json();
      if (j.error) notify(j.error, true);
      else if (j.this){ location.href = "/login"; return; }
    }catch(e){ notify("could not reach the controller: " + failWords(e), true); }
    await loadProfile();
  });
  root.querySelectorAll("[data-pfdevout]").forEach(b => b.onclick = async () => {
    const of = b.dataset.devof || "";
    const d = [...(profile?.devices || []), ...(usersList || []).flatMap(u => u.devices || [])].find(x => x.id === b.dataset.pfdevout);
    if (!await askYes(`Disconnect ${d ? d.name : "this device"}${of ? ` of ${of}` : ""}? It stops syncing at once and signs in again to come back.`)) return;
    busy(b, "Disconnecting");
    try{
      const j = await (await postJSON(of ? "/api/users" : "/api/profile",
        of ? {action: "device-signout", name: of, device: b.dataset.pfdevout} : {action: "device-signout", device: b.dataset.pfdevout})).json();
      if (j.error) notify(j.error, true);
    }catch(e){ notify("could not reach the controller: " + failWords(e), true); }
    await (of ? loadUsers() : loadProfile());
  });
}

// A conversation read here (R83): its turns as the reader route gives them,
// the newest part of a long one, with the commands folded under Claude's.
async function openConversation(project, id){
  const m = $("cvModal"), body = $("cvBody");
  $("cvTitle").textContent = `Conversation on ${projLabel(project)}`;
  $("cvNote").textContent = "";
  body.innerHTML = skel("lines", 8, "reading…");
  m.hidden = false;
  $("cvClose").onclick = () => { m.hidden = true; };
  const tz = userTZ() || Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  let j;
  try{
    j = await (await fetch(`/api/transcript?project=${encodeURIComponent(project)}&id=${encodeURIComponent(id)}&as=turns&tz=${encodeURIComponent(tz)}`)).json();
  }catch(e){ j = {error: "could not reach the controller: " + e}; }
  if (j.error){ body.innerHTML = `<div class="notice bad">${esc(j.error)}</div>`; return; }
  // The agent the conversation is with (R95): Claude, or the one it names.
  const WHO = {you: "You", claude: j.agent_name || "Claude", system: "System"};
  body.innerHTML = (j.turns || []).map(t => `<div class="cvturn ${esc(t.who)}">
      <div class="cvwho">${esc(WHO[t.who] || t.who)}${t.at ? ` · ${esc(t.at)}` : ""}</div>
      ${t.text ? `<div class="cvtext">${esc(t.text)}</div>` : ""}
      ${(t.tools || []).map(c => `<details class="cvtool${c.error ? " err" : ""}"><summary>${esc(c.call.split("\n")[0])}</summary>
        <pre>${esc(c.result || "(nothing)")}${c.cut ? "\n[cut here: the download has the rest]" : ""}</pre></details>`).join("")}
    </div>`).join("") || `<div class="empty">Nothing said in it yet.</div>`;
  $("cvNote").textContent = j.partial ? "The newest part of a long conversation: the download has all of it." : "";
  body.scrollTop = body.scrollHeight;
}
function wireProfile(root){
  const p = {...(profile?.profile || {}), account: profile?.name};
  root.querySelectorAll("[data-pf]").forEach(inp => inp.oninput = () => {
    const k = inp.dataset.pf;
    if (inp.value === (p[k] ?? "")) delete profileDraft[k];
    else profileDraft[k] = inp.value;
    const b = root.querySelector("#pfSave");
    if (b) b.disabled = !Object.keys(profileDraft).length;
  });
  const save = root.querySelector("#pfSave");
  if (save) save.onclick = async () => {
    const body = {};
    root.querySelectorAll("[data-pf]").forEach(i => { if (i.dataset.pf !== "account") body[i.dataset.pf] = i.value; });
    const account = root.querySelector("#pf_account")?.value.trim() || "";
    for (const id of ["pf_email", "pf_git_email"]){
      const el = root.querySelector("#" + id);
      if (el && el.value && !el.checkValidity()) return notify(`${el.value} is not an email address`, true);
    }
    busy(save, "Saving");
    try{
      const r = await fetch("/api/profile", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "save", profile: body, account})});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      for (const k of Object.keys(profileDraft)) delete profileDraft[k];
      notify(j.name !== profile?.name
        ? `saved; you are ${j.name} now; other browsers signed in as you sign out`
        : "saved: your next session and shell carry it");
      await loadProfile();
      refresh();                      // the Claude buttons follow git_ready
    }catch(e){ notify("profile: " + failWords(e), true); }
    finally{ if (save.isConnected) unbusy(save, "Save"); }
  };
  // Change password wakes once the current one is typed and the new one is
  // 8 or more, typed the same twice; what is wrong is said under the field
  // it is about as it is typed, and the server's refusal lands there too,
  // never only in a toast (B90, Add user's B37).
  const pw = root.querySelector("#pfPasswd");
  const fld = id => root.querySelector("#" + id);
  const sayAt = (id, t) => { setText(fld(id + "Why"), t); setHidden(fld(id + "Why"), !t); };
  const pwReady = () => {
    const cur = fld("pfCur").value, a = fld("pfNew").value, b2 = fld("pfNew2").value;
    sayAt("pfNew", a && a.length < 8 ? "The new password is shorter than 8 characters." : "");
    sayAt("pfNew2", a && b2 && a !== b2 ? "The two new passwords differ." : "");
    if (pw && !pw.getAttribute("aria-busy")) pw.disabled = !(cur && a.length >= 8 && a === b2);
  };
  if (pw){
    fld("pfCur").oninput = () => { sayAt("pfCur", ""); pwReady(); };
    fld("pfNew").oninput = fld("pfNew2").oninput = pwReady;
    pwReady();
  }
  if (pw) pw.onclick = async () => {
    const cur = fld("pfCur").value, a = fld("pfNew").value, b2 = fld("pfNew2").value;
    if (!cur || a.length < 8 || a !== b2) return pwReady();
    busy(pw, "Changing");
    try{
      const r = await fetch("/api/profile", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "password", current: cur, password: a})});
      const j = await r.json();
      if (j.error){ sayAt(/current/.test(j.error) ? "pfCur" : "pfNew", j.error); return; }
      notify("password changed: sign in again where you are asked to");
      ["pfCur", "pfNew", "pfNew2"].forEach(id => { const el = fld(id); if (el) el.value = ""; });
    }catch(e){ sayAt("pfCur", "could not reach the controller: " + e); }
    finally{ if (pw.isConnected){ unbusy(pw, "Change password"); pwReady(); } }
  };
}

// ---- two-factor sign-in (R127) ----
// Profile's section: the authenticator app (added by its QR and a first
// code), passkeys by name, the recovery codes left and new ones, and the
// browsers remembered for 30 days. What is set up here is asked at every
// sign-in after the password; removing a factor asks for one first.
let pfTotp = null;          // {qr, secret} while an authenticator is being added
let pfCodes = null;         // recovery codes just made, shown once

function profileTwoFactor(tf, required){
  const t = tf.totp || {}, keys = tf.passkeys || [], trust = tf.trusted || [];
  const line = (name, sub, act) => `<div class="tfrow"><div class="grow"><b>${name}</b>${sub ? `<div class="hint">${sub}</div>` : ""}</div>${act}</div>`;
  return `<div class="logset tfset">
    <div class="state${tf.on ? "" : required ? " warn" : ""}">${tf.on
      ? "on: a password alone does not sign in as you"
      : required ? "a role of yours requires it: add an authenticator or a passkey" : "off: a password alone signs in as you"}</div>
    ${pfCodes ? `<div class="notice tfcodes"><div>Your recovery codes, shown this once: each signs you in once if your app or passkey is lost.</div>
      <pre>${pfCodes.map(esc).join("\n")}</pre><button type="button" data-tf="codes-done">I have kept them</button></div>` : ""}
    ${line("Authenticator app", t.on ? `added ${esc(ago(t.added))}` : "a six-digit code from an app on your phone",
      t.on ? `<button type="button" data-tf="totp-remove">Remove</button>` : pfTotp ? "" : `<button type="button" data-tf="totp-add">Add</button>`)}
    ${pfTotp ? `<div class="tfadd"><div class="tfqr">${pfTotp.qr}</div>
      <div class="hint">Scan it with the app, or type the secret: <code>${esc(pfTotp.secret)}</code></div>
      <div class="logdays setrow col ctlrow">${lbl("pfTfCode", "The code the app shows")}
        <input id="pfTfCode" autocomplete="one-time-code" inputmode="numeric" spellcheck="false"></div>
      <div class="actbar"><span class="state" id="pfTfSaid"></span>
        <button type="button" data-tf="totp-cancel">Cancel</button><button type="button" class="primary" data-tf="totp-confirm">Turn it on</button></div></div>` : ""}
    ${keys.map(k => line(`Passkey: ${esc(k.name || "a passkey")}`, `added ${esc(ago(k.added))}${k.used ? `, last used ${esc(ago(k.used))}` : ""}`,
      `<button type="button" data-tf="passkey-remove" data-id="${esc(k.id)}">Remove</button>`)).join("")}
    ${window.PublicKeyCredential ? line("Add a passkey", "this device's own, or a security key", `<button type="button" data-tf="passkey-add">Add a passkey</button>`) : ""}
    ${tf.on ? line("Recovery codes", `${tf.recovery_left} of 10 left`, `<button type="button" data-tf="recovery">Make new ones</button>`) : ""}
    ${trust.map(b => line(`Remembered: ${esc(b.name || "a browser")}`, `asks no second factor until ${esc(fmtTime(b.until * 1000, {day: "numeric", month: "short"}))}`,
      `<button type="button" data-tf="trust-remove" data-id="${esc(b.id)}">Forget</button>`)).join("")}
  </div>`;
}

const pfU8 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
const pfB64 = a => btoa(String.fromCharCode(...new Uint8Array(a))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function pfTf(body){
  const r = await fetch("/api/profile", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  return r.json().catch(() => ({error: "HTTP " + r.status}));
}

// A fresh second factor for a change that wants one: a passkey where the
// account has one and this browser can, else a code typed.
async function pfFresh(){
  const keys = profile?.two_factor?.passkeys || [];
  if (keys.length && window.PublicKeyCredential && await askYes("Confirm it is you with your passkey? Cancel types a code instead.", {verb: "Use my passkey"})){
    try{
      const o = await pfTf({action: "2fa-fresh"});
      const c = await navigator.credentials.get({publicKey: {challenge: pfU8(o.challenge), rpId: location.hostname,
        allowCredentials: o.ids.map(id => ({type: "public-key", id: pfU8(id)})), userVerification: "preferred", timeout: 60000}});
      return {passkey: {id: pfB64(c.rawId), client: pfB64(c.response.clientDataJSON),
        auth: pfB64(c.response.authenticatorData), sig: pfB64(c.response.signature)}};
    }catch{ return null; }
  }
  const code = await askText("The code your authenticator app shows now, or a recovery code.", {verb: "Confirm", label: "Code"});
  return code ? {code} : null;
}

function wireTwoFactor(root){
  const redraw = async () => { await loadProfile(); profileRev++; drawPanes(); };
  root.querySelectorAll("[data-tf]").forEach(b => b.onclick = async () => {
    const what = b.dataset.tf;
    if (what === "totp-add"){ pfTotp = await pfTf({action: "2fa-totp-begin"}); profileRev++; drawPanes(); return; }
    if (what === "totp-cancel"){ pfTotp = null; profileRev++; drawPanes(); return; }
    if (what === "codes-done"){ pfCodes = null; profileRev++; drawPanes(); return; }
    if (what === "totp-confirm"){
      const r = await pfTf({action: "2fa-totp-confirm", code: root.querySelector("#pfTfCode")?.value || ""});
      if (r.error){ const s = root.querySelector("#pfTfSaid"); if (s){ s.textContent = r.error; s.classList.add("bad"); } return; }
      pfTotp = null; if (r.recovery?.length) pfCodes = r.recovery;
      notify("Two-factor sign-in: the authenticator app is on");
      return redraw();
    }
    if (what === "passkey-add"){
      try{
        const o = await pfTf({action: "2fa-passkey-begin"});
        const c = await navigator.credentials.create({publicKey: {challenge: pfU8(o.challenge), rp: {name: "BuilderBot", id: location.hostname},
          user: {id: pfU8(o.user), name: o.name, displayName: o.name}, pubKeyCredParams: [{type: "public-key", alg: -7}],
          authenticatorSelection: {residentKey: "preferred", userVerification: "preferred"}, attestation: "none", timeout: 60000,
          excludeCredentials: (o.exclude || []).map(id => ({type: "public-key", id: pfU8(id)}))}});
        const name = await askText("A name for this passkey, so you know it in the list.", {verb: "Save", label: "Name", value: "this device"});
        const r = await pfTf({action: "2fa-passkey-add", name: name || "a passkey", client: pfB64(c.response.clientDataJSON), att: pfB64(c.response.attestationObject)});
        if (r.error){ notify(r.error, true); return; }
        if (r.recovery?.length) pfCodes = r.recovery;
        notify(`Passkey added: ${r.name}`);
        return redraw();
      }catch(e){ if (e.name !== "NotAllowedError") notify("the passkey was not made: " + (e.message || e), true); return; }
    }
    if (what === "trust-remove"){
      await pfTf({action: "2fa-trust-remove", id: b.dataset.id});
      return redraw();
    }
    // A removal or new recovery codes: a fresh second factor first.
    if (what === "totp-remove" || what === "passkey-remove" || what === "recovery"){
      if (what !== "recovery" && !await askYes(what === "totp-remove" ? "Remove the authenticator app from your sign-in?" : "Remove this passkey from your sign-in?", {verb: "Remove", danger: true})) return;
      const fresh = await pfFresh();
      if (!fresh) return;
      const r = what === "recovery" ? await pfTf({action: "2fa-recovery", ...fresh})
        : await pfTf({action: "2fa-remove", what: what === "totp-remove" ? "totp" : "passkey:" + b.dataset.id, ...fresh});
      if (r.error){ notify(r.error, true); return; }
      if (r.recovery?.length) pfCodes = r.recovery;
      return redraw();
    }
  });
}

// Profile opened at its Two-factor section: the bell's Set up.
function openProfileTwoFactor(){
  SPLIT.profile = {pick: "twofactor", open: true};
  openProfileTab();
}
