// The Roles tab (R152, the operator, 7 Oct): everything an account may do,
// set here and nowhere else, in two sections with a Save and a Revert each.
// People: an account picked, its Global roles, the projects it is on and
// the roles it holds on each. Roles: a role picked or added, its scope
// (Global, or the user's projects) and Read and Write per area, Write
// needing Read. Owner and admin are built in and read only. A project's
// owner who is not an administrator sees the people of the projects they
// own and gives those projects' roles; the server holds every rule
// (roles.py, users.assign) and this file draws and asks.
//
// Chrome comes from docSurface() and the hard rules are held by
// uniform.mjs; this file fills slots, one fold per section.
"use strict";
let rolesData = null;            // GET /api/roles, or null before the first load
let rolesRev = 0;
let rolesErr = "";
let rolesWho = "";               // the account the People section is on
let rolesPeopleDraft = null;     // {roles, projects, project_roles} being edited
let rolesPick = "";              // the role the Roles section is on
let rolesDraft = null;           // {name, scope, perms, note, fresh} being edited

function openRolesTab(){
  openTab({kind: "roles", arg: "__roles", label: "Roles"});
}

async function loadRoles(){
  try{
    const r = await fetch("/api/roles");
    const j = await r.json();
    rolesErr = j.error || "";
    rolesData = j.error ? {roles: {}, areas: [], people: [], projects: [], admin: false} : j;
  }catch(e){
    rolesErr = String(e);
    rolesData = rolesData || {roles: {}, areas: [], people: [], projects: [], admin: false};
  }
  rolesRev++;
  drawPanes();
}

async function rolesAct(body, said){
  try{
    const r = await fetch("/api/roles", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error){ notify(j.error || `failed (HTTP ${r.status})`, true); return false; }
    notify(said);
  }catch(e){ notify(String(e), true); return false; }
  await loadRoles();
  return true;
}

// ---- People ------------------------------------------------------------
function rolesPerson(){
  return (rolesData?.people || []).find(p => p.name === rolesWho) || null;
}

function rolesPeopleFrom(p){
  return p ? {roles: [...(p.roles || [])], projects: [...(p.projects || [])],
              project_roles: JSON.parse(JSON.stringify(p.project_roles || {}))} : null;
}

function rolesPeopleBody(){
  const d = rolesData, people = d.people || [];
  if (!rolesWho && people.length) rolesWho = people[0].name;
  const p = rolesPerson();
  if (p && !rolesPeopleDraft) rolesPeopleDraft = rolesPeopleFrom(p);
  const dr = rolesPeopleDraft;
  const all = Object.values(d.roles || {});
  const onProject = all.filter(r => r.scope === "projects");
  // The owner holds everything and is nobody's to change, its own too.
  const locked = p && p.role === "owner";
  const pick = `<div class="setrow col">${lbl("rolesWho", "Account")}
    <select id="rolesWho">${people.map(x => `<option value="${esc(x.name)}"${x.name === rolesWho ? " selected" : ""}>${
      esc(x.name)}${x.role === "owner" ? " (owner)" : ""}</option>`).join("")}</select></div>`;
  if (!p) return pick + `<div class="sub">nobody to show</div>`;
  if (locked) return pick + `<div class="sub">${esc(p.name)} is BuilderBot's owner: every area, everywhere, and not changed here.</div>`;
  const global = d.admin ? `<div class="setrow col">${lbl("", "Global roles", "hold on every project the account is on, or everywhere for a Global role")}
      <div class="upick" id="rolesGlobal">${all.filter(r => r.name !== "owner").map(r => `<label class="pick"><input type="checkbox" data-rglobal="${esc(r.name)}"${
        dr.roles.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)} <span class="dim">${r.scope === "global" ? "global" : "its projects"}</span></label>`).join("")}</div></div>` : "";
  const projects = (d.projects || []).map(pn => {
    const on = dr.projects.includes(pn);
    const have = dr.project_roles[pn] || [];
    return `<div class="rproj" data-rproject="${esc(pn)}">
      <label class="pick"><input type="checkbox" data-ron="${esc(pn)}"${on ? " checked" : ""}> <b>${esc(projLabel(pn))}</b></label>
      <div class="upick"${on ? "" : " hidden"}>${onProject.length ? onProject.map(r => `<label class="pick"><input type="checkbox" data-rprole="${esc(r.name)}"${
        have.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)}</label>`).join("") : `<span class="dim">no roles on a project yet: add one below</span>`}</div>
    </div>`;
  }).join("");
  return `${pick}${global}
    <div class="setrow col">${lbl("", d.admin ? "Projects" : "Your projects", "the projects the account is on, and the roles it holds on each")}
      <div class="rprojects">${projects || `<span class="dim">no projects</span>`}</div></div>
    <div class="actbar"><span class="state">${rolesPeopleDirty() ? "unsaved" : ""}</span>
      <button type="button" id="rolesPeopleRevert">Revert</button>
      <button type="button" class="primary" id="rolesPeopleSave">Save</button></div>`;
}

function rolesPeopleDirty(){
  const p = rolesPerson();
  return !!p && !!rolesPeopleDraft && JSON.stringify(rolesPeopleFrom(p)) !== JSON.stringify(rolesPeopleDraft);
}

// ---- Roles -------------------------------------------------------------
function rolesFrom(r){
  return r ? {name: r.name, scope: r.scope, perms: {...(r.perms || {})}, note: r.note || "", fresh: false,
              builtin: !!r.builtin, nodes: [...(r.nodes || [])]} : null;
}

function rolesRoleBody(){
  const d = rolesData;
  const names = Object.keys(d.roles || {});
  if (!rolesPick && names.length) rolesPick = names[0];
  if (!rolesDraft || (!rolesDraft.fresh && rolesDraft.name !== rolesPick)) rolesDraft = rolesFrom(d.roles[rolesPick]);
  const r = rolesDraft;
  const pick = `<div class="setrow col">${lbl("rolesPick", "Role")}
    <div class="rpickrow"><select id="rolesPick">${names.map(n => `<option value="${esc(n)}"${n === rolesPick && !r?.fresh ? " selected" : ""}>${
      esc(d.roles[n].label || n)}${d.roles[n].builtin ? " (built in)" : ""}</option>`).join("")}${r?.fresh ? `<option selected>${esc(r.name)} (new)</option>` : ""}</select>
      ${d.admin ? `<input id="rolesNewName" placeholder="a new role's name" autocomplete="off" aria-label="a new role's name">
      <button type="button" id="rolesAdd">Add role</button>` : ""}</div></div>`;
  if (!r) return pick;
  const ro = r.builtin || !d.admin;
  const areas = (d.areas || []).map(([key, label, group, rd, wr]) => {
    const lvl = r.perms[key] || "";
    const off = ro || (group === "global" && r.scope !== "global");
    return `<div class="rarea${off && !ro ? " off" : ""}" data-rarea="${esc(key)}">
      <div class="grow"><b>${esc(label)}</b><div class="sub dim">Read: ${esc(rd)}. Write: ${esc(wr)}.</div></div>
      <label class="pick"><input type="checkbox" data-rread="${esc(key)}"${lvl ? " checked" : ""}${off ? " disabled" : ""}> Read</label>
      <label class="pick"><input type="checkbox" data-rwrite="${esc(key)}"${lvl === "write" ? " checked" : ""}${off || !lvl ? " disabled" : ""}> Write</label>
    </div>`;
  }).join("");
  return `${pick}
    <div class="setrow col">${lbl("rolesScope", "Scope", "Global holds everywhere and is the only one that reaches the machinery; the user's projects holds on each project the account is on, or the one it is given on")}
      <select id="rolesScope"${ro ? " disabled" : ""}>
        <option value="global"${r.scope === "global" ? " selected" : ""}>Global</option>
        <option value="projects"${r.scope !== "global" ? " selected" : ""}>The user's projects</option>
      </select></div>
    ${ro ? "" : `<div class="setrow col">${lbl("rolesNote", "What this role is for")}<input id="rolesNote" value="${esc(r.note)}" autocomplete="off"></div>`}
    ${r.scope === "global" && !r.builtin && (d.nodes || []).length ? `<div class="setrow col">${lbl("", "On these nodes",
        "Nodes, Toolchains, Jobs and New projects hold on the nodes ticked here; none ticked is every node")}
      <div class="upick" id="rolesNodes">${d.nodes.map(n => `<label class="pick"><input type="checkbox" data-rnode="${esc(n.id)}"${
        r.nodes.includes(n.id) ? " checked" : ""}${ro ? " disabled" : ""}> ${esc(n.name)}</label>`).join("")}</div>
      <div class="sub dim">${r.nodes.length ? "those areas on the ticked nodes only" : "those areas on every node"}</div></div>` : ""}
    <div class="rareas">${areas}</div>
    ${r.builtin ? `<div class="sub">${esc(r.note)}. Built in, every area to write, and not changed here.</div>` : ""}
    ${ro ? "" : `<div class="actbar"><span class="state">${rolesRoleDirty() ? "unsaved" : ""}</span>
      <button type="button" id="rolesRevert">Revert</button>
      <button type="button" class="primary" id="rolesSave">Save</button>
      ${r.fresh ? "" : `<button type="button" class="danger" id="rolesRemove">Remove</button>`}</div>`}`;
}

function rolesRoleDirty(){
  const r = rolesDraft;
  if (!r) return false;
  if (r.fresh) return true;
  return JSON.stringify(rolesFrom(rolesData.roles[r.name])) !== JSON.stringify(r);
}

function renderRolesInto(i){
  const d = docSurface(i, "roles");
  if (!d) return;
  d.setBar(`<span class="dim">what each account may do: roles given to people, and what each role reads and writes</span>`);
  if (rolesData === null){
    d.list.innerHTML = `<div class="row"><div class="sub">loading<span class="dots"></span></div></div>`;
    loadRoles();
    return;
  }
  d.list.innerHTML = `
    ${rolesErr ? `<div class="row bad"><div class="grow">${esc(rolesErr)}</div></div>` : ""}
    ${docSection("roles", "people", "People", String((rolesData.people || []).length), rolesPeopleBody())}
    ${docSection("roles", "roles", "Roles", String(Object.keys(rolesData.roles || {}).length), rolesRoleBody())}`;
  wireSections(d.list);
  d.setFoot(`Roles add up: an account may do what any of its roles allows, on the projects each holds on.
    Write needs Read, and an area without Read is not shown at all.`);
  wireRoles(d.el);
}

// Repaint the tab, keeping the drafts: the sections read them.
function rolesRedraw(){ rolesRev++; drawPanes(); }

function wireRoles(el){
  const who = el.querySelector("#rolesWho");
  if (who) who.onchange = () => { rolesWho = who.value; rolesPeopleDraft = null; rolesRedraw(); };
  el.querySelectorAll("[data-rglobal]").forEach(cb => cb.onchange = () => {
    const dr = rolesPeopleDraft, n = cb.dataset.rglobal;
    dr.roles = cb.checked ? [...new Set([...dr.roles, n])] : dr.roles.filter(x => x !== n);
    rolesRedraw();
  });
  el.querySelectorAll("[data-ron]").forEach(cb => cb.onchange = () => {
    const dr = rolesPeopleDraft, p = cb.dataset.ron;
    dr.projects = cb.checked ? [...new Set([...dr.projects, p])] : dr.projects.filter(x => x !== p);
    if (!cb.checked) delete dr.project_roles[p];
    rolesRedraw();
  });
  el.querySelectorAll("[data-rprole]").forEach(cb => cb.onchange = () => {
    const dr = rolesPeopleDraft, p = cb.closest("[data-rproject]").dataset.rproject, n = cb.dataset.rprole;
    const have = dr.project_roles[p] || [];
    dr.project_roles[p] = cb.checked ? [...new Set([...have, n])] : have.filter(x => x !== n);
    rolesRedraw();
  });
  const pr = el.querySelector("#rolesPeopleRevert");
  if (pr) pr.onclick = () => { rolesPeopleDraft = null; rolesRedraw(); };
  const ps = el.querySelector("#rolesPeopleSave");
  if (ps) ps.onclick = async () => {
    busy(ps, "Saving");
    const dr = rolesPeopleDraft;
    const body = {action: "assign", name: rolesWho, projects: dr.projects, project_roles: {}};
    for (const p of rolesData.projects || []) body.project_roles[p] = dr.project_roles[p] || [];
    if (rolesData.admin) body.roles = dr.roles;
    if (await rolesAct(body, `${rolesWho} saved`)) rolesPeopleDraft = null;
    rolesRedraw();
  };

  const rp = el.querySelector("#rolesPick");
  if (rp) rp.onchange = () => { rolesPick = rp.value; rolesDraft = null; rolesRedraw(); };
  const add = el.querySelector("#rolesAdd"), nm = el.querySelector("#rolesNewName");
  if (add) add.onclick = () => {
    const name = (nm?.value || "").trim();
    if (!name) return notify("a name for the role", true);
    if (rolesData.roles[name]) return notify(`${name} is a role already`, true);
    rolesDraft = {name, scope: "projects", perms: {}, note: "", fresh: true, builtin: false, nodes: []};
    rolesRedraw();
  };
  const sc = el.querySelector("#rolesScope");
  if (sc) sc.onchange = () => {
    rolesDraft.scope = sc.value;
    if (sc.value !== "global") rolesDraft.nodes = [];
    // A role on the user's projects holds project areas only.
    if (sc.value !== "global")
      for (const [key, , group] of rolesData.areas) if (group === "global") delete rolesDraft.perms[key];
    rolesRedraw();
  };
  el.querySelectorAll("[data-rnode]").forEach(cb => cb.onchange = () => {
    const n = cb.dataset.rnode;
    rolesDraft.nodes = cb.checked ? [...new Set([...rolesDraft.nodes, n])] : rolesDraft.nodes.filter(x => x !== n);
    rolesRedraw();
  });
  const note = el.querySelector("#rolesNote");
  if (note) note.oninput = () => { rolesDraft.note = note.value; };
  el.querySelectorAll("[data-rread]").forEach(cb => cb.onchange = () => {
    const k = cb.dataset.rread;
    if (cb.checked) rolesDraft.perms[k] = rolesDraft.perms[k] || "read";
    else delete rolesDraft.perms[k];      // no Read, no Write
    rolesRedraw();
  });
  el.querySelectorAll("[data-rwrite]").forEach(cb => cb.onchange = () => {
    const k = cb.dataset.rwrite;
    rolesDraft.perms[k] = cb.checked ? "write" : "read";
    rolesRedraw();
  });
  const rr = el.querySelector("#rolesRevert");
  if (rr) rr.onclick = () => { rolesDraft = null; rolesRedraw(); };
  const rs = el.querySelector("#rolesSave");
  if (rs) rs.onclick = async () => {
    busy(rs, "Saving");
    const r = rolesDraft;
    if (await rolesAct({action: "set", name: r.name, scope: r.scope, perms: r.perms, note: r.note,
                        nodes: r.scope === "global" ? r.nodes : []}, `${r.name} saved`)){
      rolesPick = r.name; rolesDraft = null;
    }
    rolesRedraw();
  };
  const rm = el.querySelector("#rolesRemove");
  if (rm) rm.onclick = async () => {
    if (!confirm(`Remove the role ${rolesDraft.name}? Accounts that hold it lose what it gave.`)) return;
    if (await rolesAct({action: "remove", name: rolesDraft.name}, `${rolesDraft.name} removed`)){
      rolesPick = ""; rolesDraft = null;
    }
    rolesRedraw();
  };
}
