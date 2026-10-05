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
let usersMeta = {owner: "", me: "", roles: [], role_names: [], projects: []};
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
                 roles: j.roles || [], role_names: j.role_names || [], projects: j.projects || []};
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

// One row. The owner's is the one with rules attached, and it says them
// rather than showing controls that would be refused.
function userRow(u){
  const isOwner = u.role === "owner";
  const isMe = u.name === usersMeta.me;
  const seen = !u.seen ? "never signed in" : "last seen " + ago(u.seen);
  const scope = u.role === "user"
    ? (u.projects.length
        ? `<span class="sub">sees</span> ` + u.projects.map(
            p => `<span class="pill">${esc(p)}</span>`).join(" ")
        : `<span class="sub dim">sees no project yet</span>`)
    // An administrator and the owner alike (R135): every project listed,
    // the ones on their own list worked on.
    : `<span class="sub">sees every project${u.projects.length
        ? `, works on</span> ` + u.projects.map(p => `<span class="pill">${esc(p)}</span>`).join(" ")
        : `; works on none yet: Edit ticks the ones to take on</span>`}`;
  // The roles of your own it carries beside its built-in one (R137).
  const more = (u.roles || []).filter(r => r !== u.role);
  return `<div class="row stack2 urow" data-user="${esc(u.name)}">
    <div class="grow">
      <div class="name">${esc(u.name)}
        <span class="pill">${esc(u.role)}</span>${
        more.map(r => ` <span class="pill note" title="a role of your own, from the Roles tab">${esc(r)}</span>`).join("")}${
        isMe ? ` <span class="pill">you</span>` : ""}</div>
      <div class="uscope">${scope}</div>
      <div class="sub${u.claude_shared_with?.length ? " warn" : " dim"}">${u.claude
        ? `signed in to Claude as ${esc(u.claude)}${u.claude_shared_with?.length
            ? `: the same Claude account as ${u.claude_shared_with.map(esc).join(", ")}, allowed only while one person is behind both`
            : ""}`
        : "no Claude login yet: its sessions sign in on first use"}</div>
      ${isOwner ? `<div class="sub dim">The owner cannot be deleted or given another role.</div>` : ""}
    </div>
    <div class="actbar">
      <span class="state">${esc(seen)}</span>
      <button type="button" data-uedit="${esc(u.name)}"
        title="everything about this account in one dialog, saved together">Edit</button>
      ${isOwner
        ? `<button type="button" class="danger" disabled
             title="the owner cannot be deleted: rename it instead">Remove</button>`
        : `<button type="button" class="danger" data-uremove="${esc(u.name)}">Remove</button>`}
    </div>
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
    d.list.innerHTML = `<div class="row"><div class="sub">loading<span class="dots"></span></div></div>`;
    loadUsers();
    return;
  }
  d.list.innerHTML = `
    ${usersErr ? `<div class="row bad"><div class="grow">${esc(usersErr)}</div></div>` : ""}
    ${usersList.map(userRow).join("")}
    ${docSection("users", "roles", "What an account gets", "", `
        <div class="sub">Each account has its own home, Claude login and memories; two people on one project each work in a worktree of their own, sharing the notebook.</div>
        <div class="sub">A <b>user</b> has no shell and sees only the projects given to them.</div>
        <div class="sub warn">An <b>admin</b> has a shell that reaches every account's files: give that role to people you would give the server to.</div>
        <div class="sub">Anything between the two is a role of your own: the <b>Roles</b> tab under Administration makes one out of grants, and Edit gives it to an account, beside its role. Grants only add.</div>`)}
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
          <div class="setrow col">${lbl("uNewRole", "Role")}
          <select id="uNewRole">${
            usersMeta.roles.filter(r => r !== "owner").map(r =>
              // `user` selected, not merely first: the roles run owner, admin,
              // user, so the browser's own default would be the MOST privileged
              // of the two on offer. Adding somebody should start at the least.
              `<option value="${esc(r)}"${r === (usersAddDraft.role || "user") ? " selected" : ""}
                >${esc(r)}</option>`).join("")}</select></div>
        </div>
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
                           ["#uNewFull", "full"], ["#uNewEmail", "email"], ["#uNewRole", "role"]]){
    const f = el.querySelector(id);
    if (!f) continue;
    if (key !== "role") f.value = usersAddDraft[key] || "";
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
    usersAct({action: "add", name, password: pw,
              role: el.querySelector("#uNewRole").value,
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
    ${isOwner ? `<div class="field">${lbl("", "Role", "the owner's role cannot change; its name can")}<div class="hint">owner</div></div>`
      : `<div class="field">${lbl("ueRole", "Role")}<select id="ueRole">${
          usersMeta.roles.filter(r => r !== "owner").map(r =>
            `<option value="${esc(r)}"${r === u.role ? " selected" : ""}>${esc(r)}</option>`).join("")}
        </select></div>`}
    ${!isOwner && (usersMeta.role_names || []).length ? `<div class="field">
      ${lbl("", "Roles of your own", "beside the role above; their grants add up (the Roles tab makes them)")}
      <div class="upick">${usersMeta.role_names.map(r => `<label class="tc"><input type="checkbox"
          data-uerole="${esc(r)}"${(u.roles || []).includes(r) ? " checked" : ""}>
          <span class="grow"><span class="nm">${esc(r)}</span></span></label>`).join("")}</div>
    </div>` : ""}
    ${f("ueFull", "Their name", pf.full_name)}
    ${f("ueEmail", "Their email", pf.email, "email")}
    ${f("ueGitName", "Git name", pf.git_name, "text", "", "on their commits. Blank means their name")}
    ${f("ueGitEmail", "Git email", pf.git_email, "email", "", "on their commits. Blank means their email")}
    ${f("uePw", "New password", "", "password", 'autocomplete="new-password"', "blank keeps the current one. Set without the old one, which is the way back in for somebody locked out")}
    <div class="field" id="ueProjField"${u.role === "owner" ? " hidden" : ""}>
      ${u.role === "admin"
        ? lbl("", "Projects this account works on", "the rest are read-only for them")
        : lbl("", "Projects this account sees", "the rest do not appear for them")}
      <div class="upick">${usersMeta.projects.length
        ? usersMeta.projects.map(p => `<label class="tc"><input type="checkbox"
            data-ueproj="${esc(p)}"${(u.projects || []).includes(p) ? " checked" : ""}>
            <span class="grow"><span class="nm">${esc(p)}</span></span></label>`).join("")
        : `<div class="sub">no projects to give</div>`}</div>
    </div>
    <div class="field" id="ueErrWrap" hidden><div class="hint bad" id="ueErr"></div></div>
    <div class="foot">
      <button id="ueSave" class="primary">Save</button>
      <button id="ueCancel">Cancel</button>
    </div>
  </div>`;
  m.hidden = false;
  // Dismissed like every other dialog: the backdrop, or Escape.
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  if (!m.dataset.keys){
    m.dataset.keys = "1";
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !m.hidden){ e.preventDefault(); m.hidden = true; }
    });
  }
  const role = m.querySelector("#ueRole");
  // The list is every role's but the owner's, who has every project: an
  // admin works on the ones ticked (users.may_work), so hiding it for them
  // left no way to take a project on from the page (B142).
  if (role) role.onchange = () => { m.querySelector("#ueProjField").hidden = role.value === "owner"; };
  m.querySelector("#ueCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#ueSave").onclick = () => usersEditSave(u.name, m);
  m.querySelector("#ueName").focus();
}

async function usersEditSave(name, m){
  const v = id => m.querySelector("#" + id)?.value ?? "";
  const body = {action: "edit", name, to: m.querySelector("#ueName")?.disabled ? "" : v("ueName").trim(),
                role: m.querySelector("#ueRole")?.value || "",
                profile: {full_name: v("ueFull"), email: v("ueEmail"),
                          git_name: v("ueGitName"), git_email: v("ueGitEmail")},
                password: v("uePw")};
  if ((m.querySelector("#ueRole")?.value || "user") !== "owner" && !m.querySelector("#ueProjField").hidden)
    body.projects = [...m.querySelectorAll("[data-ueproj]")].filter(c => c.checked).map(c => c.dataset.ueproj);
  if (m.querySelector("[data-uerole]"))
    body.roles = [...m.querySelectorAll("[data-uerole]")].filter(c => c.checked).map(c => c.dataset.uerole);
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
