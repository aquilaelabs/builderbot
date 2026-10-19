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
  return `<option value=""${cur ? "" : " selected"}>This device's own${own ? ` (${esc(own)})` : ""}</option>`
    + [...zones].sort().map(z => `<option value="${esc(z)}"${z === cur ? " selected" : ""}>${esc(z)}</option>`).join("");
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
  }catch(e){ notify("profile: " + e, true); return; }
  profileRev++;
  if (tabs.some(t => t.kind === "profile" || t.kind === "devices")) drawPanes();
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
  plugins: "what you added with /plugin", logs: "your conversations with Claude, to download",
};
// The apps signed in as this account on its own machines (R272 step 1), on
// the Devices page (tab-devices.js): a table, a line a device (its name,
// what it is, when it last called) with Disconnect at its end, which signs
// that one out.
const PF_DEVICE_COLS = [{label: "Device"}, {label: "Kind", w: "6rem"}, {label: "Last call", w: "minmax(0,.6fr)"}, {act: true, w: "8rem"}];
const PF_DEVICE_KIND = {pc: "a PC", phone: "a phone", editor: "an editor"};
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
    const fld = label => `<div class="setrow col ctlrow"><span class="lbl">${esc(label)}</span>${skv(18, "ctl")}</div>`;
    d.setBar(`<span class="barfacts">${skv(16)}</span>`);
    splitOff(d.list);                   // drawn before: its grid is the template's to bring
    d.list.innerHTML = skTpl(skSplit([["Who you are", PROFILE_SAYS.you], ["What you may do", PROFILE_SAYS.may],
      ["Password", PROFILE_SAYS.password], ["Claude plugins", PROFILE_SAYS.plugins],
      ["Conversation logs", PROFILE_SAYS.logs]], "Who you are", PROFILE_FIELDS.map(([, label]) => fld(label)).join("")));
    return;
  }
  const p = {...(profile.profile || {}), account: profile.name}, g = profile.git || {};
  const val = k => profileDraft[k] ?? p[k] ?? "";
  const dirty = PROFILE_FIELDS.some(([k]) => (profileDraft[k] ?? p[k] ?? "") !== (p[k] ?? ""));
  const wm = profile.what_may || {roles: [], may: []};
  // Who this is, in the facts voice (R218 step 31): the name, the roles and
  // the Claude account, one mono line.
  d.setBar(`<span class="barfacts">${esc(profile.name)} · ${esc(wm.roles.length ? wm.roles.join(", ") : "no role")}${
    profile.claude ? ` · Claude: ${esc(profile.claude)}` : ""}</span>`);
  // A page of settings (page-docs.js splitSects, the operator, 16 Oct):
  // each block a section, the sections a list beside the one picked; who
  // you are first, since that is what is changed here most.
  const sec = (id, title, inner) => docSection("profile", id, title, "",
    `<div class="row stack2"><div class="grow">${inner}</div></div>`);
  d.list.innerHTML = `
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
                ? "no author for commits yet: a Claude session waits for a name and an email here"
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
          </div>
          <div class="logdays setrow col ctlrow">
            ${lbl("pfNew", "New password", "at least 8 characters; every browser signed in as you signs out")}
            <input id="pfNew" type="password" autocomplete="new-password">
          </div>
          <div class="logdays setrow col ctlrow">
            ${lbl("pfNew2", "New password again")}
            <input id="pfNew2" type="password" autocomplete="new-password">
          </div>
          <div class="actbar">
            <span class="state"></span>
            <button type="button" id="pfPasswd">Change password</button>
          </div>
        </div>`)}
    ${sec("plugins", "Claude plugins", `
        <div class="logset">${profilePlugins(profile.plugins || [])}</div>`)}
    ${sec("logs", "Conversation logs", `
        <div class="logset">${profileLogs(profile.logs || [])}</div>`)}`;
  wireSections(d.list);
  splitSects(d.list, "profile", {says: PROFILE_SAYS, back: "Profile"});
  // Paged like every long list here (R218 step 31): one log per
  // conversation, so the list only grows.
  paginate(d.list.querySelector(".cvlogs"), ":scope > .artrow", {key: "pfLogs", noun: "conversations"});
  wireProfile(d.el);
}

// What you installed with /plugin in your own sessions, per node, as each
// node last said (plugins.py): read here, changed only in a session, where
// a plugin takes effect.
function profilePlugins(rows){
  if (!rows.length) return `<div class="dim">None installed. <code>/plugin</code> in a Claude session adds one, for you alone.</div>`;
  const one = p => `<code>${esc(p.id.replace(/@claude-plugins-official$/, ""))}</code>${
    p.version ? ` ${esc(p.version)}` : ""}${p.scope === "project" ? ` (${esc(p.project ? projLabel(p.project) : "a project")})` : ""}${
    p.enabled === false ? ` <span class="dim">off</span>` : ""}`;
  return rows.map(n => `<div class="sub">On ${esc(n.name)}: ${n.plugins.map(one).join(", ")}</div>`).join("")
    + `<div class="dim">Change them with <code>/plugin</code> in a Claude session.</div>`;
}

// Your conversations with Claude, newest first, each as a text file to
// keep: what you said, what Claude said, every command it ran and what came
// back (transcripts.py renders the transcript Claude Code wrote). An anchor
// rather than a button, because a download is a link and the browser knows
// how to save one; the rows are the Artifacts tab's, divided by hairlines.
function profileLogs(rows){
  if (!rows.length) return `<div class="dim">None yet. A Claude session on a project writes one as you talk, and it is listed here for you alone.</div>`;
  const size = b => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
  // The stamps in the text are written in this browser's zone, the one the
  // times on this page are in, so the log and the page agree.
  const tz = userTZ() || Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  // The Artifacts tab's rows, so the two lists read the same.
  return `<div class="cvlogs">${rows.map(r => `
    <div class="artrow">
      <div class="grow">
        <div class="top"><b>${esc(projLabel(r.project))}</b> <span class="dim">${esc(fmtTime(r.at * 1000))} · ${esc(size(r.bytes))}</span></div>
        ${r.first ? `<div class="dim first">${esc(r.first)}</div>` : ""}</div>
      <div class="acts"><a class="btn" href="/api/transcript?project=${encodeURIComponent(r.project)}&id=${encodeURIComponent(r.id)}&tz=${encodeURIComponent(tz)}" download>Download</a></div>
    </div>`).join("")}</div>
    <div class="dim">The text is the whole exchange: your words, Claude's, each command it ran and what the command answered. Claude's private reasoning is not in it.</div>`;
}

// Disconnect: asked, then that device signed out; the app finds its token
// refused on its next call and says to sign in again. One of another
// account's, on the Users page, is an administrator's to cut off for them.
function wireDeviceOut(root){
  root.querySelectorAll("[data-pfdevout]").forEach(b => b.onclick = async () => {
    const of = b.dataset.devof || "";
    const d = [...(profile?.devices || []), ...(usersList || []).flatMap(u => u.devices || [])].find(x => x.id === b.dataset.pfdevout);
    if (!confirm(`Disconnect ${d ? d.name : "this device"}${of ? ` of ${of}` : ""}? It stops syncing at once and signs in again to come back.`)) return;
    busy(b, "Disconnecting");
    try{
      const j = await (await postJSON(of ? "/api/users" : "/api/profile",
        of ? {action: "device-signout", name: of, device: b.dataset.pfdevout} : {action: "device-signout", device: b.dataset.pfdevout})).json();
      if (j.error) notify(j.error, true);
    }catch(e){ notify("could not reach the controller: " + e, true); }
    await (of ? loadUsers() : loadProfile());
  });
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
    }catch(e){ notify("profile: " + e, true); }
    finally{ if (save.isConnected) unbusy(save, "Save"); }
  };
  const pw = root.querySelector("#pfPasswd");
  if (pw) pw.onclick = async () => {
    const cur = root.querySelector("#pfCur").value, a = root.querySelector("#pfNew").value,
          b2 = root.querySelector("#pfNew2").value;
    if (a.length < 8) return notify("a password is at least 8 characters", true);
    if (a !== b2) return notify("the two new passwords differ", true);
    busy(pw, "Changing");
    try{
      const r = await fetch("/api/profile", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "password", current: cur, password: a})});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      notify("password changed: sign in again where you are asked to");
      ["pfCur", "pfNew", "pfNew2"].forEach(id => { const el = root.querySelector("#" + id); if (el) el.value = ""; });
    }catch(e){ notify("profile: " + e, true); }
    finally{ if (pw.isConnected) unbusy(pw, "Change password"); }
  };
}
