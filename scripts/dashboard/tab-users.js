// The Users tab: who may sign in, and which projects they see. Step 3 of
// roadmap #22; the design and the reasoning are docs/users.md and are not
// repeated here. A page of settings (the operator, 17 Oct): the accounts a
// list beside the picked one's settings, its name, roles and projects,
// profile and password saved together and Remove at their foot; Add user
// at the right of the page's bar, in a dialog. Its own classic script beside index.html, per the
// new-surface rule: same page, same global scope, one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file fills slots. Every rule about WHO may do WHAT lives on the server
// (users.py): a row that cannot be deleted is drawn without the control and
// says why, rather than being offered one that fails, but the store refuses
// it regardless, because `bb users` reaches the same rules from a shell.

"use strict";

let usersList = null;            // last answer, or null before the first
let usersRev = 0;                // bumped when it changes, so panes repaint
let usersErr = "";
let usersMeta = {owner: "", me: "", roles: [], role_names: [], projects: [], role_labels: {}};
// What is typed into Add somebody, kept across the repaints a reload brings:
// the form is drawn afresh each time, and a reload landing between typing
// and Add emptied it, so Add said only "a name and a password" and sent
// nothing (B422). Cleared once an add lands.
let usersAddDraft = {name: "", pw: "", role: "user"};

function openUsersTab(){
  // The kind's open hook loads; a second load here asked twice for one press.
  openTab({kind: "users", arg: "__users", label: "Users"});
}

async function loadUsers(){
  try{
    const j = await (await bootFetch("/api/users")).json();
    usersErr = j.error || "";
    usersList = j.users || [];
    usersMeta = {owner: j.owner || "", me: j.me || "",
                 roles: j.roles || [], role_names: j.role_names || [], projects: j.projects || [],
                 role_labels: j.role_labels || {}};
  }catch(e){
    usersErr = String(e);
    usersList = usersList || [];
  }
  usersRev++;
  drawPanes();
}

// `say`, when given, is where a refusal is written (a dialog's own line);
// without it a refusal is a toast. True when it landed.
async function usersAct(body, say = null){
  const refuse = t => { if (say) say(t); else notify(t, true); return false; };
  try{
    const r = await fetch("/api/users", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return refuse(j.error || `failed (HTTP ${r.status})`);
    if (body.action === "add"){ usersAddDraft = {name: "", pw: "", role: "user"}; usersPick = body.name; usersPhoneOpen = true; }
    if (body.action === "remove"){ usersPick = ""; usersPhoneOpen = false; }
    notify(body.action === "remove" ? `${body.name} removed`
         : body.action === "add" ? `${body.name} added`
         : `${body.name} updated`);
  }catch(e){ return refuse(String(e)); }
  // The roles data names the accounts whose roles this one may give, so an
  // account added or removed is read there too (B32).
  if (body.action === "add" || body.action === "remove") await loadRoles();
  await loadUsers();
  return true;
}

// ---- a list beside the one picked ----------------------------------------
// On a phone the list, then the account's settings sliding in over it with
// Back, and the list sliding back (the shape every page of settings has).
let usersPick = "";              // the account on show
let usersPhoneOpen = false;      // on a phone, the settings are over the list
let usersMoveNext = "";          // the slide the next draw plays
let usersEdit = null;            // what is typed into the picked account's fields
let usersRolesAsked = false;     // /api/roles read once for the roles fields
const USER_KEYS = ["name", "full", "email", "git_name", "git_email", "pw"];

function usersEditFrom(u){
  const pf = u.profile || {};
  return {for: u.name, name: u.name, full: pf.full_name || "", email: pf.email || "",
          git_name: pf.git_name || "", git_email: pf.git_email || "", pw: ""};
}
function usersPicked(){ return (usersList || []).find(x => x.name === usersPick) || null; }
function usersDirty(){
  const u = usersPicked();
  if (!u || !usersEdit) return false;
  const was = usersEditFrom(u);
  return USER_KEYS.some(k => was[k] !== usersEdit[k]) || (typeof rolesPeopleDirty === "function" && rolesPeopleDirty());
}
function usersRedraw(){ usersRev++; drawPanes(); }
// Accounts and roles Read without its Write: the page is there to read, its
// fields dead and the reason said over them (B34).
function usersReadOnly(){ return state?.can?.admin === false; }

// An account's row: its name with what it holds as pills on one line, and
// when it was last seen a fact under it (the operator, 18 Oct: the pills
// and the seen ran together under the name).
function userRow(u){
  const on = u.name === usersPick;
  const more = (u.roles || []).filter(r => r !== u.role && r !== "user");
  const roles = [...(u.role === "owner" || u.role === "admin" ? [u.role] : []), ...more];
  return `<button type="button" class="rrow${on ? " on" : ""}" data-upick="${esc(u.name)}"${on ? ' aria-current="true"' : ""}>
    <span class="rline"><span class="name">${esc(u.name)}</span>${u.name === usersMeta.me ? `<span class="pill">you</span>` : ""}${
      roles.map(r => `<span class="pill${r === "owner" ? " ok" : ""}">${esc(usersMeta.role_labels?.[r] || r)}</span>`).join("")}</span>
    <span class="rfacts">${[roles.length ? "" : (u.projects || []).length
      ? `a role on ${u.projects.length} project${u.projects.length === 1 ? "" : "s"}` : "no role", u.seen ? `seen ${ago(u.seen)}` : "never seen"].filter(Boolean).map(esc).join(" · ")}</span></button>`;
}

// The picked account's settings, saved together: its name, its roles and
// projects (tab-roles.js draws those), the Profile fields an administrator
// may fill in for somebody, and a new password, which an administrator sets
// without the current one, that being the way back in for somebody locked
// out. Remove at the foot, away from Save.
function usersDetail(u){
  if (!usersEdit || usersEdit.for !== u.name) usersEdit = usersEditFrom(u);
  const e = usersEdit, isMe = u.name === usersMeta.me, isOwner = u.role === "owner", ro = usersReadOnly();
  const f = (id, key, label, type = "text", extra = "", help = "") =>
    `<div class="setcell">${lbl(id, label, help)}<input id="${id}" data-ufield="${key}" type="${type}" value="${esc(e[key] || "")}"
       autocomplete="off" spellcheck="false" ${extra}${ro ? " disabled" : ""}></div>`;
  const facts = [agentLogins(u) || "signed in to no agent yet", u.seen ? `seen ${esc(ago(u.seen))}` : "never seen",
                 u.projects?.length ? `on ${u.projects.length} project${u.projects.length === 1 ? "" : "s"}` : "on no project yet"];
  const access = rolesData === null ? `<div class="sub dim">reading its roles…</div>` : rolesAccessFields(u.name);
  return `<div class="rhead" data-uback><span class="shback" role="img" aria-label="Back to People">\u2039</span><b>${esc(u.name)}</b> <span class="dim">${facts.join(" · ")}</span></div>
    ${u.claude_shared_with?.length ? `<div class="sub warn">the same Claude account as ${u.claude_shared_with.map(esc).join(", ")
      }, allowed only while one person is behind both</div>` : ""}
    <div class="setgrid">
      ${isMe ? f("ueName", "name", "Account name", "text", "disabled", "your own account name changes on your Profile, which keeps this browser signed in")
             : f("ueName", "name", "Account name", "text", "", "what they sign in with. Changing it signs their browsers out")}
      ${f("ueFull", "full", "Their name")}
      ${f("ueEmail", "email", "Their email", "email")}
      ${f("ueGitName", "git_name", "Git name", "text", "", "on their commits. Blank means their name")}
      ${f("ueGitEmail", "git_email", "Git email", "email", "", "on their commits. Blank means their email")}
      ${f("uePw", "pw", "New password", "password", 'autocomplete="new-password"', "blank keeps the current one. Set without the old one, which is the way back in for somebody locked out")}
    </div>
    <div class="setrow col ueaccess ctlrow">${lbl("", "Roles and projects", "what this account may do; what each role holds is on the Roles page")}<div id="ueAccess">${access}</div></div>
    <div class="sub bad" id="ueErr" hidden></div>
    ${ro ? "" : saveBar({save: 'id="ueSave"', revert: 'id="ueRevert"', state: usersDirty() ? "unsaved" : ""})}
    ${u.devices ? `<div class="uedevices"><span class="lbl">Devices${helpIcon("the apps signed in as this account on its machines; Disconnect cuts one off for them, as a lost laptop needs")}</span>${
      profileDevices(u.devices, u.name)}</div>` : ""}
    ${ro ? "" : `<div class="rfoot">${isOwner ? `<span class="sub dim">The owner cannot be deleted: rename it instead.</span>`
      : `<button type="button" class="danger" id="ueRemove">Remove ${esc(u.name)}</button>`}</div>`}`;
}

function renderUsersInto(i){
  const d = docSurface(i, "users");
  if (!d) return;
  // A count where Jobs and Sessions keep theirs, not a sentence about the
  // page (the operator, 18 Oct: a bar holds what the page acts on).
  // Refused outright (a plain account by link), there is nothing to count
  // or add, and the refusal is the page (B38).
  const refused = usersErr && !(usersList || []).length;
  // No count beside the button (the operator, 25 Oct: no loose words at a
  // page's top): the list says how many.
  d.setBar(`<span class="sp"></span>
    ${refused || usersReadOnly() ? "" : `<span class="actbar"><button type="button" class="primary" id="uAddOpen">Add user</button></span>`}`);
  if (usersList === null){
    // Its template (R218 step 16): the list beside the settings, whose
    // labels are the page's own; the accounts are on their way.
    const field = label => skField(label, 16);
    d.list.innerHTML = skTpl(`<div class="rsplit"><div class="rlist">${skRows(3)}</div><div class="rdetail">${
      field("Account name") + field("Their name") + field("Roles and projects")}</div></div>`);
    loadUsers();
    wireUsersBar(d.el);
    return;
  }
  if (refused){
    d.list.innerHTML = `<div class="row bad"><div class="grow">${esc(usersErr)}</div></div>`;
    return;
  }
  if (rolesData === null && !usersRolesAsked){ usersRolesAsked = true; loadRoles().then(usersRedraw); }
  if (!usersPicked()) usersPick = usersList[0]?.name || "";
  const u = usersPicked();
  d.list.innerHTML = `
    ${usersErr ? `<div class="row bad"><div class="grow">${esc(usersErr)}</div></div>` : ""}
    <div class="rsplit${usersPhoneOpen ? " open" : ""}">
      <div class="rlist">${usersList.map(userRow).join("") || `<div class="empty">nobody yet</div>`}</div>
      <div class="rdetail">${u ? usersDetail(u) : `<div class="empty">nobody to show</div>`}</div>
    </div>`;
  wireUsersBar(d.el);
  wireUsers(d.el);
  if (usersMoveNext){ splitMove(d.list.querySelector(".rsplit"), usersMoveNext); usersMoveNext = ""; }
}

function wireUsersBar(el){
  const a = el.querySelector("#uAddOpen");
  if (a) a.onclick = () => usersAddOpen();
}

function wireUsers(el){
  wireDeviceOut(el);
  el.querySelectorAll("[data-upick]").forEach(b => b.onclick = async () => {
    if (b.dataset.upick !== usersPick && usersDirty() && !await askYes(`Leave ${usersPick}'s changes unsaved?`)) return;
    splitAway(() => document.querySelectorAll(".pane .doc.on .rsplit > .rdetail"), () => {
      usersPick = b.dataset.upick; usersEdit = null; usersPhoneOpen = true; usersMoveNext = "in"; usersRedraw(); });
  });
  // The picked account's head is the way back on a phone (splitSects).
  el.querySelectorAll("[data-uback]").forEach(b => b.onclick = () => { if (!matchMedia("(max-width: 900px)").matches) return; usersPhoneOpen = false; usersMoveNext = "back"; usersRedraw(); });
  // What is typed is kept across the repaints a poll brings (B422's lesson).
  el.querySelectorAll("[data-ufield]").forEach(f => f.oninput = f.onchange = () => {
    usersEdit[f.dataset.ufield] = f.value;
    const st = el.querySelector(".rdetail .actbar .state");
    if (st) st.textContent = usersDirty() ? "unsaved" : "";
  });
  const box = el.querySelector("#ueAccess");
  if (box && rolesData !== null) wireRolesAccess(box, usersRedraw);
  const rv = el.querySelector("#ueRevert");
  if (rv) rv.onclick = () => { usersEdit = null; rolesPeopleDraft = null; usersRedraw(); };
  const sv = el.querySelector("#ueSave");
  if (sv) sv.onclick = () => usersSave(el, sv);
  const rm = el.querySelector("#ueRemove");
  if (rm) rm.onclick = async () => {
    if (await askYes(`Remove ${usersPick}? They lose access immediately.`)) usersAct({action: "remove", name: usersPick});
  };
}

async function usersSave(el, btn){
  const u = usersPicked(), e = usersEdit;
  if (!u || !e) return;
  const err = el.querySelector("#ueErr");
  const say = t => { err.textContent = t; err.hidden = !t; };
  // An email that is not one is caught here, before a request: the field
  // knows (type=email), and the server checks the same shape again.
  for (const id of ["ueEmail", "ueGitEmail"]){
    const f = el.querySelector("#" + id);
    if (f && f.value && !f.checkValidity()) return say(`${f.value} is not an email address`);
  }
  say("");
  busy(btn, "Saving");
  try{
    // Its roles first, under the name they are held by, before a rename.
    if (!(await rolesAccessSave())) return;
    const was = usersEditFrom(u);
    // Only its roles changed: the list and the header are read again all
    // the same, since they show what it holds (B33).
    if (!USER_KEYS.some(k => was[k] !== e[k])){ usersEdit = null; await loadUsers(); return; }
    const body = {action: "edit", name: u.name, to: u.name === usersMeta.me ? "" : e.name.trim(),
                  profile: {full_name: e.full, email: e.email, git_name: e.git_name, git_email: e.git_email},
                  password: e.pw};
    const r = await fetch("/api/users", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return say(j.error || `failed (HTTP ${r.status})`);
    notify(`${body.to || u.name} saved`);
    usersPick = body.to || u.name; usersEdit = null;
    await loadUsers();
  }catch(x){ notify(String(x), true); }
  finally{ if (btn.isConnected) unbusy(btn, "Save"); }
}

// ---- Add user, a dialog ---------------------------------------------------
// What an account gets is the docs' to say (the operator, 16 Oct), not a
// block of prose here; a new one holds no role, given beside its account.
function usersAddOpen(){
  let m = document.getElementById("uaddmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "uaddmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  m.innerHTML = `<div class="box"><h3>Add user</h3>
    <div class="field">${lbl("uNewName", "Account name")}<input id="uNewName" autocomplete="off"></div>
    <div class="field">${lbl("uNewPw", "Password", "at least 8 characters. They can change it on their Profile")}
      <input id="uNewPw" type="password" autocomplete="new-password"></div>
    <div class="field">${lbl("uNewPw2", "The password again")}<input id="uNewPw2" type="password" autocomplete="new-password"></div>
    <div class="field">${lbl("uNewFull", "Name", "optional: how they are addressed. Their git name and email are set on their Profile, or here once the account exists")}
      <input id="uNewFull" autocomplete="off"></div>
    <div class="field">${lbl("uNewEmail", "Email", "optional")}<input id="uNewEmail" type="email" autocomplete="off"></div>
    <div class="field"><div class="hint">A new account holds no role: give it one beside its account once it is added.</div></div>
    <div class="field" id="uAddWhyF" hidden><div class="hint bad" id="uAddWhy"></div></div>
    ${dlgFoot(`<button type="button" id="uAddCancel">Cancel</button>`, `<button type="button" id="uAdd" class="primary" disabled>Add</button>`)}</div>`;
  // Add wakes once there is a name and a password of 8 or more typed the
  // same twice (the operator, 18 Oct); why it sleeps is said in the dialog
  // once something is typed, and a refusal from the server lands there too.
  const say = t => { m.querySelector("#uAddWhy").textContent = t; m.querySelector("#uAddWhyF").hidden = !t; };
  const why = () => {
    const pw = m.querySelector("#uNewPw").value, pw2 = m.querySelector("#uNewPw2").value;
    if (pw && pw.length < 8) return "The password is shorter than 8 characters.";
    if (pw && pw2 && pw !== pw2) return "The two passwords differ.";
    if (pw && !m.querySelector("#uNewName").value.trim()) return "It needs an account name.";
    return "";
  };
  const ready = () => {
    const pw = m.querySelector("#uNewPw").value;
    say(why());
    m.querySelector("#uAdd").disabled = !(m.querySelector("#uNewName").value.trim()
      && pw.length >= 8 && pw === m.querySelector("#uNewPw2").value);
  };
  for (const [id, key] of [["#uNewName", "name"], ["#uNewPw", "pw"], ["#uNewPw2", "pw2"],
                           ["#uNewFull", "full"], ["#uNewEmail", "email"]]){
    const f = m.querySelector(id);
    f.value = usersAddDraft[key] || "";
    f.oninput = f.onchange = () => { usersAddDraft[key] = f.value; ready(); };
  }
  ready();
  m.hidden = false;
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  m.querySelector("#uAddCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#uAdd").onclick = async () => {
    const name = m.querySelector("#uNewName").value.trim();
    const pw = m.querySelector("#uNewPw").value;
    // Typed twice (R134): a password nobody can read back is one a slip
    // locks somebody out with.
    if (!name || pw.length < 8 || pw !== m.querySelector("#uNewPw2").value) return ready();
    const full = m.querySelector("#uNewFull").value.trim(), email = m.querySelector("#uNewEmail").value.trim();
    if (await usersAct({action: "add", name, password: pw, role: "user",
                        profile: {...(full ? {full_name: full} : {}), ...(email ? {email} : {})}}, say)) m.hidden = true;
  };
  m.querySelector("#uNewName").focus();
}
