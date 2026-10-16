// The Roles tab (R152, the operator, 7 Oct): everything an account may do,
// set here and nowhere else, in two sections with a Save and a Revert each.
// People: an account picked, its Everywhere roles, the roles it holds on
// each project (holding one is being on the project, R155), and what that
// adds up to. Roles: a role picked or added, its kind (Everywhere, or On a
// project) and Read and Write per area, Write needing Read. Owner and admin are built in and read only. A project's
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
let rolesPeopleDraft = null;     // {roles, project_roles} being edited
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
  return p ? {roles: [...(p.roles || [])],
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
  const everywhere = all.filter(r => r.scope === "global" && r.name !== "owner");
  const global = d.admin ? `<div class="setrow col">${lbl("", "Everywhere roles", "hold on every project and on BuilderBot itself, as far as each one's areas say")}
      <div class="upick" id="rolesGlobal">${everywhere.map(r => `<label class="pick"><input type="checkbox" data-rglobal="${esc(r.name)}"${
        dr.roles.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)}</label>`).join("")}</div></div>` : "";
  // Holding a role on a project is being on it (R155): no separate box.
  const projects = (d.projects || []).map(pn => {
    const have = dr.project_roles[pn] || [];
    // A role that is one project's (its owner role, B726) is offered
    // under that project and no other.
    const here = onProject.filter(r => !r.project || r.project === pn);
    return `<div class="rproj" data-rproject="${esc(pn)}">
      <div class="rprojname"><b>${esc(projLabel(pn))}</b> <span class="dim">${have.length ? "" : "not on it"}</span></div>
      <div class="upick">${here.length ? here.map(r => `<label class="pick"><input type="checkbox" data-rprole="${esc(r.name)}"${
        have.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)}</label>`).join("") : `<span class="dim">no roles on a project yet: add one under Roles</span>`}</div>
    </div>`;
  }).join("");
  return `${pick}${global}
    <div class="setrow col">${lbl("", d.admin ? "Projects" : "Your projects", "a role ticked on a project puts the account on it; none ticked, it is not on it")}
      <div class="rprojects">${projects || `<span class="dim">no projects</span>`}</div></div>
    ${rolesCanDo(p.name, dr)}
    <div class="actbar"><span class="state">${rolesPeopleDirty() ? "unsaved" : ""}</span>
      <button type="button" id="rolesPeopleRevert">Revert</button>
      <button type="button" class="primary" id="rolesPeopleSave">Save</button></div>`;
}

// What an account's roles add up to, worked out from the draft so it moves
// as boxes are ticked (R155, the operator: "why can't they..." at a glance).
// Per project the areas it reads and writes, then the areas that are not
// about a project. An administrator's answer is "everything", said as such.
function rolesCanDo(name, dr){
  const d = rolesData, areas = d.areas || [];
  const per = names => {
    const got = {};
    for (const rn of names){
      const r = d.roles[rn];
      for (const [k, v] of Object.entries(r?.perms || {}))
        if (v === "write" || !got[k]) got[k] = v;
    }
    return got;
  };
  if (dr.roles.includes("admin"))
    return `<div class="setrow col">${lbl("", `What ${name} can do`)}<div class="sub">everything but change the owner: admin holds every area</div></div>`;
  const glob = per(dr.roles);
  const say = (got, keys) => {
    const w = keys.filter(k => got[k] === "write"), r = keys.filter(k => got[k] === "read");
    const nm = k => (areas.find(a => a[0] === k) || [])[1] || k;
    return [w.length ? `writes ${w.map(nm).join(", ")}` : "", r.length ? `reads ${r.map(nm).join(", ")}` : ""]
      .filter(Boolean).join("; ");
  };
  const projKeys = areas.filter(a => a[2] !== "global").map(a => a[0]);
  const globKeys = areas.filter(a => a[2] === "global").map(a => a[0]);
  const rows = (d.projects || []).map(pn => {
    const got = per([...dr.roles, ...(dr.project_roles[pn] || [])]);
    const line = say(got, projKeys);
    return line ? `<div class="sub"><b>${esc(projLabel(pn))}</b>: ${esc(line)}</div>` : "";
  }).filter(Boolean);
  const g = say(glob, globKeys);
  return `<div class="setrow col">${lbl("", `What ${name} can do`, "worked out from the boxes above, saved or not")}
    ${rows.join("") || `<div class="empty">nothing on any project</div>`}
    <div class="sub">${g ? `<b>Beyond projects</b>: ${esc(g)}` : `<span class="dim">nothing beyond projects</span>`}</div></div>`;
}

function rolesPeopleDirty(){
  const p = rolesPerson();
  return !!p && !!rolesPeopleDraft && JSON.stringify(rolesPeopleFrom(p)) !== JSON.stringify(rolesPeopleDraft);
}

// ---- Roles -------------------------------------------------------------
const ROLE_AREA_COLS = [{label: "Area"}, {label: "Read", w: "4.5rem"}, {label: "Write", w: "4.5rem"}];
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
  // A table (R218 step 8): the area, with what Read and Write let one do
  // under its name, then its two boxes in their columns.
  const offOf = group => ro || (group === "global" && r.scope !== "global");
  const rows = (d.areas || []).map(([key, label, group, rd, wr]) => {
    const lvl = r.perms[key] || "", off = offOf(group);
    return tblLine(ROLE_AREA_COLS, [
      `${esc(label)}<div class="sub dim">Read: ${esc(rd)}. Write: ${esc(wr)}.</div>`,
      `<input type="checkbox" data-rread="${esc(key)}" aria-label="Read ${esc(label)}"${lvl ? " checked" : ""}${off ? " disabled" : ""}>`,
      `<input type="checkbox" data-rwrite="${esc(key)}" aria-label="Write ${esc(label)}"${lvl === "write" ? " checked" : ""}${
        off || !lvl ? " disabled" : ""}>`], "div", `rarea${off && !ro ? " off" : ""}`, `data-rarea="${esc(key)}"`);
  }).join("");
  // Why some rows are gray, said once above the table, in the reason's
  // color (the design: the reason under a dead control).
  const why = !ro && (d.areas || []).some(([, , group]) => offOf(group))
    ? `<div class="sub bad" id="rolesWhyOff">The gray areas are not about one project: only an Everywhere role holds them.</div>` : "";
  const areas = why + tblWrap(ROLE_AREA_COLS, rows, "rareas");
  return `${pick}
    <div class="setrow col">${lbl("rolesScope", "Kind", "On a project: given per project under People, and holds there. Everywhere: given to the account, holds on every project and is the only kind that reaches the nodes, toolchains and the controller")}
      <select id="rolesScope"${ro ? " disabled" : ""}>
        <option value="projects"${r.scope !== "global" ? " selected" : ""}>On a project</option>
        <option value="global"${r.scope === "global" ? " selected" : ""}>Everywhere</option>
      </select></div>
    ${ro ? "" : `<div class="setrow col">${lbl("rolesNote", "What this role is for")}<input id="rolesNote" value="${esc(r.note)}" autocomplete="off"></div>`}
    ${r.scope === "global" && !r.builtin && (d.nodes || []).length ? `<div class="setrow col">${lbl("", "On these nodes",
        "Nodes, Toolchains, Jobs and New projects hold on the nodes ticked here; none ticked is every node")}
      <div class="upick" id="rolesNodes">${d.nodes.map(n => `<label class="pick"><input type="checkbox" data-rnode="${esc(n.id)}"${
        r.nodes.includes(n.id) ? " checked" : ""}${ro ? " disabled" : ""}> ${esc(n.name)}</label>`).join("")}</div>
      <div class="sub dim">${r.nodes.length ? "those areas on the ticked nodes only" : "those areas on every node"}</div></div>` : ""}
    ${areas}
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
    // Its template (R218 step 16): the two sections and their fields' labels
    // are the page's own; who holds what is on its way.
    const field = (label, em) => `<div class="setrow col"><span class="lbl">${esc(label)}</span>${skv(em, "ctl")}</div>`;
    d.list.innerHTML = skTpl(docSection("roles", "people", "People", "", field("Account", 16))
      + docSection("roles", "roles", "Roles", "", field("Role", 12) + field("Kind", 16) + skRows(6)));
    loadRoles();
    return;
  }
  d.list.innerHTML = `
    ${rolesErr ? `<div class="row bad"><div class="grow">${esc(rolesErr)}</div></div>` : ""}
    ${docSection("roles", "people", "People", String((rolesData.people || []).length), rolesPeopleBody())}
    ${docSection("roles", "roles", "Roles", String(Object.keys(rolesData.roles || {}).length), rolesRoleBody())}`;
  wireSections(d.list);
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
    const body = {action: "assign", name: rolesWho, project_roles: {}};
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
