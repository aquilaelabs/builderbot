// The Users tab: who may sign in, and which projects they see. Step 3 of
// roadmap #22; the design and the reasoning are docs/users.md and are not
// repeated here. Its own classic script beside index.html, per the
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
    const j = await (await fetch("/api/users")).json();
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

async function usersAct(body){
  try{
    const r = await fetch("/api/users", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return notify(j.error || `failed (HTTP ${r.status})`, true);
    if (body.action === "add") usersAddDraft = {name: "", pw: "", role: "user"};
    notify(body.action === "remove" ? `${body.name} removed`
         : body.action === "add" ? `${body.name} added`
         : `${body.name} updated`);
  }catch(e){ return notify(String(e), true); }
  await loadUsers();
}

// One row of the table (R218 step 8): the account, its roles, its projects,
// its Claude login and when it was last seen, Edit and Remove at the end.
// The owner's is the one with rules attached, and it says them rather than
// showing controls that would be refused.
const USER_COLS = [{label: "Account", w: "minmax(0,.8fr)"}, {label: "Role", w: "minmax(0,.7fr)"},
                   {label: "Projects", w: "minmax(0,1.1fr)"}, {label: "Claude", w: "minmax(0,1fr)"},
                   {label: "Last seen", w: "8rem"}, {act: true, w: "10.5rem"}];
function userRow(u){
  const isOwner = u.role === "owner";
  const isMe = u.name === usersMeta.me;
  const seen = !u.seen ? "never" : ago(u.seen);
  // Its projects and roles are the Roles tab's to set (R152); shown here.
  const projs = u.projects.map(projLabel);
  const more = (u.roles || []).filter(r => r !== u.role && r !== "user");
  const roles = [...(u.role === "owner" || u.role === "admin" ? [u.role] : []), ...more];
  return `<div class="row stack2 urow" data-user="${esc(u.name)}">
    ${tblLine(USER_COLS, [
      `${esc(u.name)}${isMe ? ` <span class="pill">you</span>` : ""}`,
      roles.length ? esc(roles.map(r => usersMeta.role_labels?.[r] || r).join(", ")) : `<span class="dim">no role</span>`,
      projs.length ? `<span title="${esc(projs.join(", "))}">${esc(projs.join(", "))}</span>` : "on no project yet",
      u.claude ? `<span title="signed in to Claude as ${esc(u.claude)}">${esc(u.claude)}</span>` : "no Claude login yet",
      esc(seen),
      `<div class="actbar">
        <button type="button" data-uedit="${esc(u.name)}"
          title="everything about this account in one dialog, saved together">Edit</button>
        ${isOwner
          ? `<button type="button" class="danger" disabled
               title="the owner cannot be deleted: rename it instead">Remove</button>`
          : `<button type="button" class="danger" data-uremove="${esc(u.name)}">Remove</button>`}
      </div>`])}
    ${u.claude_shared_with?.length ? `<div class="sub warn">the same Claude account as ${u.claude_shared_with.map(esc).join(", ")
      }, allowed only while one person is behind both</div>` : ""}
    ${isOwner ? `<div class="sub dim">The owner cannot be deleted.</div>` : ""}
  </div>`;
}

// Which projects a `user` account may see. Only the ones the admin doing the
// giving can see themselves: the server filters again, so this is the honest
// list rather than the enforcing one.
function renderUsersInto(i){
  const d = docSurface(i, "users");
  if (!d) return;
  d.setBar(`<span class="dim">who may sign in here, and which projects they see</span>`);
  if (usersList === null){
    d.list.innerHTML = skel("rows", 4);
    loadUsers();
    return;
  }
  d.list.innerHTML = `
    ${usersErr ? `<div class="row bad"><div class="grow">${esc(usersErr)}</div></div>` : ""}
    ${usersList.length ? tblWrap(USER_COLS, usersList.map(userRow).join(""), "utbl") : ""}
    ${docSection("users", "roles", "What an account gets", "", `
        <div class="sub">Each account has its own home, Claude login and memories; two people on one project each work in a worktree of their own, sharing the notebook.</div>
        <div class="sub">A new account holds no role, so it may do nothing until the <b>Roles</b> tab gives it one, Everywhere or on a project, and puts it on projects.</div>
        <div class="sub warn">An <b>admin</b> has a shell that reaches every account's files: give that role to people you would give the server to.</div>
        <div class="sub">A project's owner holds PROJECT_owner on it, which the Roles tab can cut back like any other role.</div>`)}
    ${docSection("users", "add", "Add somebody", "", `

        <div class="uadd">
          <div class="setrow col">${lbl("uNewName", "Account name")}
            <input id="uNewName" autocomplete="off"></div>
          <div class="setrow col">${lbl("uNewPw", "Password", "at least 8 characters. They can change it on their Profile")}
            <input id="uNewPw" type="password" autocomplete="new-password"></div>
          <div class="setrow col">${lbl("uNewPw2", "The password again")}
            <input id="uNewPw2" type="password" autocomplete="new-password"></div>
          <div class="setrow col">${lbl("uNewFull", "Name", "optional: how they are addressed; their git identity is theirs to set on their Profile")}
            <input id="uNewFull" autocomplete="off"></div>
          <div class="setrow col">${lbl("uNewEmail", "Email", "optional")}
            <input id="uNewEmail" type="email" autocomplete="off"></div>
        </div>
        <div class="sub">A new account holds no role: give it one on the Roles tab.</div>
        <div class="actbar"><button type="button" class="primary" id="uAdd">Add</button></div>`)}`;
  wireSections(d.list);
  d.setFoot(`Locked out? Run <code>bb users passwd &lt;name&gt;</code> in the
    container to reset a password.`);
  wireUsers(d.el);
}

function wireUsers(el){
  el.querySelectorAll("[data-uremove]").forEach(b => b.onclick = () => {
    const n = b.dataset.uremove;
    if (confirm(`Remove ${n}? They lose access immediately.`))
      usersAct({action: "remove", name: n});
  });
  // A role is saved on Save, not on the change: the select is a question
  // and the button is the answer (docs/design-language.md, Settings).
  el.querySelectorAll("[data-uedit]").forEach(b => b.onclick = () => usersEditOpen(b.dataset.uedit));
  const add = el.querySelector("#uAdd");
  for (const [id, key] of [["#uNewName", "name"], ["#uNewPw", "pw"], ["#uNewPw2", "pw2"],
                           ["#uNewFull", "full"], ["#uNewEmail", "email"]]){
    const f = el.querySelector(id);
    if (!f) continue;
    f.value = usersAddDraft[key] || "";
    f.oninput = f.onchange = () => { usersAddDraft[key] = f.value; };
  }
  if (add) add.onclick = () => {
    const name = el.querySelector("#uNewName").value.trim();
    const pw = el.querySelector("#uNewPw").value;
    if (!name || !pw) return notify("a name and a password", true);
    // Typed twice (R134): a password nobody can read back is one a slip
    // locks somebody out with.
    if (pw !== el.querySelector("#uNewPw2").value) return notify("the two passwords differ", true);
    const full = el.querySelector("#uNewFull").value.trim(), email = el.querySelector("#uNewEmail").value.trim();
    usersAct({action: "add", name, password: pw, role: "user",
              profile: {...(full ? {full_name: full} : {}), ...(email ? {email} : {})}});
  };
}

// ---- the edit dialog ------------------------------------------------------
// Everything about one account in one place, saved together (docs/
// design-language.md, Settings): its name, role, projects, the Profile
// fields an administrator may fill in for somebody, and a new password,
// which an administrator sets without the current one, that being the way
// back in for somebody locked out. The owner's role is not on offer; the
// store refuses it anyway. Built once, on first use, and filled per open.
function usersEditOpen(name){
  const u = usersList.find(x => x.name === name);
  if (!u) return;
  let m = document.getElementById("umodal");
  if (!m){
    m = document.createElement("div");
    m.id = "umodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);                          // made after the page-load pass

  }
  const isOwner = u.role === "owner";
  const pf = u.profile || {};
  const f = (id, label, val, type = "text", extra = "", help = "") =>
    `<div class="field">${lbl(id, label, help)}<input id="${id}" type="${type}" value="${esc(val || "")}"
       autocomplete="off" spellcheck="false" ${extra}></div>`;
  m.innerHTML = `<div class="box">
    <h3>Edit ${esc(u.name)}</h3>
    ${u.name === usersMeta.me
      ? f("ueName", "Account name", u.name, "text", "disabled", "your own account name changes on your Profile, which keeps this browser signed in")
      : f("ueName", "Account name", u.name, "text", "", "what they sign in with. Changing it signs their browsers out")}
    <div class="field">${lbl("", "Roles and projects", "what this account may do, set on the Roles tab (R152)")}
      <div class="setrow"><span class="hint grow">${isOwner ? "BuilderBot's owner: every area, everywhere"
        : esc((u.what_may?.roles || []).join(", ") || "no role yet")}</span>
        <button type="button" id="ueRolesGo">Roles</button></div>
      ${!isOwner && (u.what_may?.may || []).length ? factGrid(u.what_may.may) : ""}</div>
    ${f("ueFull", "Their name", pf.full_name)}
    ${f("ueEmail", "Their email", pf.email, "email")}
    ${f("ueGitName", "Git name", pf.git_name, "text", "", "on their commits. Blank means their name")}
    ${f("ueGitEmail", "Git email", pf.git_email, "email", "", "on their commits. Blank means their email")}
    ${f("uePw", "New password", "", "password", 'autocomplete="new-password"', "blank keeps the current one. Set without the old one, which is the way back in for somebody locked out")}
    <div class="field" id="ueErrWrap" hidden><div class="hint bad" id="ueErr"></div></div>
    <div class="foot">
      <button id="ueSave" class="primary">Save</button>
      <button id="ueCancel">Cancel</button>
    </div>
  </div>`;
  m.hidden = false;
  // Dismissed like every other dialog: the backdrop, or Escape (modalKeys).
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  m.querySelector("#ueRolesGo").onclick = () => {
    m.hidden = true;
    rolesWho = u.name; rolesPeopleDraft = null;
    openRolesTab();
  };
  m.querySelector("#ueCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#ueSave").onclick = () => usersEditSave(u.name, m);
  m.querySelector("#ueName").focus();
}

async function usersEditSave(name, m){
  const v = id => m.querySelector("#" + id)?.value ?? "";
  const body = {action: "edit", name, to: m.querySelector("#ueName")?.disabled ? "" : v("ueName").trim(),
                profile: {full_name: v("ueFull"), email: v("ueEmail"),
                          git_name: v("ueGitName"), git_email: v("ueGitEmail")},
                password: v("uePw")};
  // An email that is not one is caught here, before a request: the field
  // knows (type=email), and the server checks the same shape again.
  for (const id of ["ueEmail", "ueGitEmail"]){
    const el = m.querySelector("#" + id);
    if (el && el.value && !el.checkValidity()){
      m.querySelector("#ueErr").textContent = `${el.value} is not an email address`;
      m.querySelector("#ueErrWrap").hidden = false;
      return;
    }
  }
  m.querySelector("#ueErrWrap").hidden = true;
  const btn = m.querySelector("#ueSave");
  busy(btn, "Saving");
  try{
    const r = await fetch("/api/users", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error){
      m.querySelector("#ueErr").textContent = j.error || `failed (HTTP ${r.status})`;
      m.querySelector("#ueErrWrap").hidden = false;
      return;
    }
    m.hidden = true;
    notify(`${body.to || name} saved`);
    await loadUsers();
  }catch(e){ notify(String(e), true); }
  finally{ if (btn.isConnected) unbusy(btn, "Save"); }
}
