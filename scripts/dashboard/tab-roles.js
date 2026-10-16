// The Roles tab (R152, the operator, 7 Oct): everything an account may do,
// set here and nowhere else, in two sections with a Save and a Revert each.
// Each a list beside the one picked (R255 step 9). People: the accounts,
// and for the one picked its Everywhere roles, the projects it is on with
// its roles there (holding one is being on the project, R155), Add to
// project, and what that adds up to. Roles: the roles with their kind and
// holders, and for the one picked or added its kind (Everywhere, or On a
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
let rolesDraft = null;           // {name, scope, perms, note, fresh, only} being edited
const rolesExp = new Set();      // the areas opened on their instances (R260)

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

// ---- a list beside the one picked ----------------------------------------
// Both sections are a list and the picked one's detail side by side at a
// desk (R255 step 9, the operator 16 Oct: every project listed for an
// account that is on none of them, and half the desk empty); on a phone the
// list, then the detail over it with a way back.
const rolesOpen = {people: false, roles: false};
function rolesSplit(which, list, detail){
  return `<div class="rsplit${rolesOpen[which] ? " open" : ""}" data-rsplit="${which}">
    <div class="rlist">${list}</div>
    <div class="rdetail"><button type="button" class="rback" data-rback="${which}">‹ ${which === "people" ? "Every account" : "Every role"}</button>${detail}</div>
  </div>`;
}
const rolesLabel = n => rolesData.roles?.[n]?.label || n;

// An account's row: its name, and what it holds as tags.
function rolesPersonRow(x){
  const on = Object.values(x.project_roles || {}).filter(v => (v || []).length).length;
  const tags = x.role === "owner" ? [`<span class="pill ok">BuilderBot's owner</span>`]
    : [...(x.roles || []).map(n => `<span class="pill">${esc(rolesLabel(n))}</span>`),
       on ? `<span class="dim">on ${on} project${on === 1 ? "" : "s"}</span>` : ""].filter(Boolean);
  return `<button type="button" class="rrow${x.name === rolesWho ? " on" : ""}" data-rwho="${esc(x.name)}"${x.name === rolesWho ? ' aria-current="true"' : ""}>
    <span class="name">${esc(x.name)}</span><span class="rtags">${tags.join("") || `<span class="dim">no role</span>`}</span></button>`;
}

// The roles a project offers: every role on a project, and its own owner
// role there and nowhere else (B726).
const rolesOnProject = pn => Object.values(rolesData.roles || {}).filter(r => r.scope === "projects" && (!r.project || r.project === pn));

function rolesPeopleBody(){
  const d = rolesData, people = d.people || [];
  if (!rolesWho && people.length) rolesWho = people[0].name;
  const p = rolesPerson();
  if (p && !rolesPeopleDraft) rolesPeopleDraft = rolesPeopleFrom(p);
  const dr = rolesPeopleDraft;
  const list = people.map(rolesPersonRow).join("") || `<div class="empty">nobody yet</div>`;
  if (!p) return rolesSplit("people", list, `<div class="empty">nobody to show</div>`);
  const head = `<div class="rhead"><b>${esc(p.name)}</b></div>`;
  // The owner holds everything and is nobody's to change, its own too.
  if (p.role === "owner")
    return rolesSplit("people", list, `${head}<div class="sub">${esc(p.name)} is BuilderBot's owner: every area, everywhere, and not changed here.</div>`);
  const everywhere = Object.values(d.roles || {}).filter(r => r.scope === "global" && r.name !== "owner");
  const global = d.admin ? `<div class="setrow col">${lbl("", "Everywhere roles", "hold on every project and on BuilderBot itself, as far as each one's areas say")}
      <div class="upick" id="rolesGlobal">${everywhere.map(r => `<label class="pick"><input type="checkbox" data-rglobal="${esc(r.name)}"${
        dr.roles.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)}</label>`).join("")}</div></div>` : "";
  // The projects it is on, and only those: holding a role on a project is
  // being on it (R155), and a row of every project it is not on said
  // nothing a picker does not.
  const all = d.projects || [];
  const on = all.filter(pn => (dr.project_roles[pn] || []).length);
  const rows = on.map(pn => {
    const have = dr.project_roles[pn] || [];
    return `<div class="rproj" data-rproject="${esc(pn)}">
      <b class="rprojname">${esc(projLabel(pn))}</b>
      <span class="upick">${rolesOnProject(pn).map(r => `<label class="pick"><input type="checkbox" data-rprole="${esc(r.name)}"${
        have.includes(r.name) ? " checked" : ""}> ${esc(r.label || r.name)}</label>`).join("")}</span>
      <button type="button" class="ic" data-rprojoff="${esc(pn)}" aria-label="take ${esc(p.name)} off ${esc(projLabel(pn))}" title="take off this project">×</button>
    </div>`;
  }).join("");
  const off = all.filter(pn => !on.includes(pn));
  const addPn = off.includes(rolesAddProj) ? rolesAddProj : off[0] || "";
  // No role on a project at all: there is nothing to put it on a project
  // with, and the place that makes one is named instead of an empty picker.
  const anyProjRole = Object.values(d.roles || {}).some(r => r.scope === "projects");
  const add = off.length && !anyProjRole ? `<div class="sub dim raddon">No role on a project yet: one made under Roles puts ${esc(p.name)} on a project.</div>`
    : off.length ? `<div class="raddon">
      <select id="rolesAddProj" aria-label="the project">${off.map(pn => `<option value="${esc(pn)}"${pn === addPn ? " selected" : ""}>${esc(projLabel(pn))}</option>`).join("")}</select>
      <select id="rolesAddRole" aria-label="the role there">${rolesOnProject(addPn).map(r => `<option value="${esc(r.name)}">${esc(r.label || r.name)}</option>`).join("")}</select>
      <button type="button" id="rolesAddOn"${rolesOnProject(addPn).length ? "" : " disabled"}>Add to project</button></div>` : "";
  const detail = `${head}${global}
    <div class="setrow col">${lbl("", d.admin ? "Projects" : "Your projects", "a role on a project puts the account on it; taken off, it is not on it")}
      <div class="rprojects">${rows || `<div class="empty">on no project yet</div>`}</div>${add}</div>
    ${rolesCanDo(p.name, dr)}
    <div class="actbar"><span class="state">${rolesPeopleDirty() ? "unsaved" : ""}</span>
      <button type="button" id="rolesPeopleRevert">Revert</button>
      <button type="button" class="primary" id="rolesPeopleSave">Save</button></div>`;
  return rolesSplit("people", list, detail);
}
let rolesAddProj = "";

// What an account's roles add up to, worked out from the draft so it moves
// as boxes are ticked (R155, the operator: "why can't they..." at a glance):
// a grid of the project areas it holds, a column for what its Everywhere
// roles give on every project and one per project it is on, then the areas
// that are not about a project in a line. An administrator's answer is
// "everything", said as such.
const ROLES_LVL = {write: "Write", read: "Read"};
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
  const nm = k => (areas.find(a => a[0] === k) || [])[1] || k;
  const projKeys = areas.filter(a => a[2] !== "global").map(a => a[0]);
  const globKeys = areas.filter(a => a[2] === "global").map(a => a[0]);
  const on = (d.projects || []).filter(pn => (dr.project_roles[pn] || []).length);
  const cols = [{label: "Every project", got: glob}, ...on.map(pn => ({label: projLabel(pn), pn, got: per([...dr.roles, ...dr.project_roles[pn]])}))];
  const keys = projKeys.filter(k => cols.some(c => c.got[k]));
  const tcols = [{label: "Area"}, ...cols.map(c => ({label: c.label, w: "minmax(5rem,.5fr)"}))];
  const grid = keys.length ? tblWrap(tcols, keys.map(k => `<div class="row" data-rcan="${esc(k)}">${tblLine(tcols, [esc(nm(k)),
      ...cols.map(c => c.got[k] ? `<span class="rlvl ${c.got[k]}"${c.pn ? ` data-rcanp="${esc(c.pn)}"` : ""}>${ROLES_LVL[c.got[k]]}</span>` : `<span class="dim">·</span>`)])}</div>`).join(""), "rcan")
    : `<div class="empty">nothing on any project</div>`;
  const w = globKeys.filter(k => glob[k] === "write"), r = globKeys.filter(k => glob[k] === "read");
  const beyond = [w.length ? `writes ${w.map(nm).join(", ")}` : "", r.length ? `reads ${r.map(nm).join(", ")}` : ""].filter(Boolean).join("; ");
  return `<div class="setrow col">${lbl("", `What ${name} can do`, "worked out from the boxes above, saved or not")}
    ${grid}
    <div class="sub">${beyond ? `<b>Beyond projects</b>: ${esc(beyond)}` : `<span class="dim">nothing beyond projects</span>`}</div></div>`;
}

function rolesPeopleDirty(){
  const p = rolesPerson();
  return !!p && !!rolesPeopleDraft && JSON.stringify(rolesPeopleFrom(p)) !== JSON.stringify(rolesPeopleDraft);
}

// ---- Roles -------------------------------------------------------------
const ROLE_AREA_COLS = [{label: "Area"}, {label: "Read", w: "4.5rem"}, {label: "Write", w: "4.5rem"}];
function rolesFrom(r){
  return r ? {name: r.name, scope: r.scope, perms: {...(r.perms || {})}, note: r.note || "", fresh: false,
              builtin: !!r.builtin, only: JSON.parse(JSON.stringify(r.only || {}))} : null;
}

// ---- an area instance by instance (R260) ----
// An Everywhere role's node areas open on the nodes, the CI runner's on each
// runner, Read and Write on each (the operator, 16 Oct). The draft keeps an
// area held on every instance as its level alone, and one held on some as
// `only[area]`, {instance: level}: every instance at one level folds back to
// the level alone, which holds on instances added later too.
function rolesInsts(key){
  const d = rolesData;
  if (!(d.instance_areas || []).includes(key)) return [];
  return key === "runner" ? (d.runners || []).map(r => ({id: r.id, name: `${r.name} on ${r.node}`}))
                          : (d.nodes || []);
}
function rolesLvlAt(key, id){
  const m = rolesDraft.only?.[key];
  return m ? (m[id] || "") : (rolesDraft.perms[key] || "");
}
// Every instance's level at once, folded as above.
function rolesSetAll(key, levelOf){
  const r = rolesDraft, insts = rolesInsts(key);
  const map = Object.fromEntries(insts.map(i => [i.id, levelOf(i.id, rolesLvlAt(key, i.id))]));
  const vals = new Set(Object.values(map));
  r.only = r.only || {};
  if (vals.size === 1){
    const v = [...vals][0];
    delete r.only[key];
    if (v) r.perms[key] = v; else delete r.perms[key];
    return;
  }
  r.only[key] = Object.fromEntries(Object.entries(map).filter(([, v]) => v));
  r.perms[key] = vals.has("write") ? "write" : "read";
}

function rolesRoleBody(){
  const d = rolesData;
  const names = Object.keys(d.roles || {});
  if (!rolesPick && names.length) rolesPick = names[0];
  if (!rolesDraft || (!rolesDraft.fresh && rolesDraft.name !== rolesPick)) rolesDraft = rolesFrom(d.roles[rolesPick]);
  const r = rolesDraft;
  // Who holds each role, for its row and its detail.
  const holders = n => (d.people || []).filter(x => (x.roles || []).includes(n)
    || Object.values(x.project_roles || {}).some(v => (v || []).includes(n))).map(x => x.name);
  const kind = x => x.builtin ? "built in" : x.scope === "global" ? "Everywhere" : x.project ? `on ${projLabel(x.project)}` : "on a project";
  const list = (d.admin ? `<div class="raddrole"><input id="rolesNewName" placeholder="a new role's name" autocomplete="off" aria-label="a new role's name">
      <button type="button" id="rolesAdd">Add role</button></div>` : "")
    + (r?.fresh ? `<button type="button" class="rrow on" aria-current="true"><span class="name">${esc(r.name)}</span><span class="rtags"><span class="dim">new, not saved</span></span></button>` : "")
    + names.map(n => { const x = d.roles[n], h = holders(n).length, on = n === rolesPick && !r?.fresh;
        return `<button type="button" class="rrow${on ? " on" : ""}" data-rpick="${esc(n)}"${on ? ' aria-current="true"' : ""}>
          <span class="name">${esc(x.label || n)}</span><span class="rtags"><span class="pill">${esc(kind(x))}</span><span class="dim">${
            h ? `${h} ${h === 1 ? "person" : "people"}` : "nobody"}</span></span></button>`; }).join("");
  if (!r) return rolesSplit("roles", list, `<div class="empty">no role picked</div>`);
  const who = r.fresh ? [] : holders(r.name);
  const pick = `<div class="rhead"><b>${esc(r.fresh ? r.name : (d.roles[r.name]?.label || r.name))}</b>${
    r.fresh ? "" : ` <span class="dim">${who.length ? `held by ${esc(who.join(", "))}` : "held by nobody yet"}</span>`}</div>`;
  const ro = r.builtin || !d.admin;
  // A table (R218 step 8): the area, with what Read and Write let one do
  // under its name, then its two boxes in their columns.
  const offOf = group => ro || (group === "global" && r.scope !== "global");
  const box = (attr, key, label, on, part, dead) => `<input type="checkbox" ${attr}="${esc(key)}" aria-label="${esc(label)}"${
    on ? " checked" : ""}${part ? " data-part" : ""}${dead ? " disabled" : ""}>`;
  const rows = (d.areas || []).map(([key, label, group, rd, wr]) => {
    const off = offOf(group);
    // Opened on its instances only where it can be changed: an Everywhere
    // role this account may edit, with instances to name.
    const insts = !off && r.scope === "global" ? rolesInsts(key) : [];
    const lv = insts.length ? insts.map(i => rolesLvlAt(key, i.id)) : [r.perms[key] || ""];
    const rAll = lv.every(Boolean), rSome = lv.some(Boolean);
    const wAll = lv.every(x => x === "write"), wSome = lv.some(x => x === "write");
    const open = insts.length && rolesExp.has(key);
    const what = key === "runner" ? "runner" : "node";
    const exp = insts.length ? `<button type="button" class="rexp" data-rexp="${esc(key)}" aria-expanded="${open ? "true" : "false"}"
      aria-label="${esc(label)} on each ${what}">${rSome && !rAll ? `${lv.filter(Boolean).length} of ${insts.length} ${what}s` : `each ${what}`}</button>` : "";
    const head = tblLine(ROLE_AREA_COLS, [
      `<span class="rareahead">${esc(label)}${exp}</span><div class="sub dim">Read: ${esc(rd)}. Write: ${esc(wr)}.</div>`,
      box("data-rread", key, `Read ${label}`, rAll, rSome && !rAll, off),
      box("data-rwrite", key, `Write ${label}`, wAll, wSome && !wAll, off || !rSome)],
      "div", `rarea${off && !ro ? " off" : ""}`, `data-rarea="${esc(key)}"`);
    return head + (open ? insts.map(i => { const at = rolesLvlAt(key, i.id), k = `${key}|${i.id}`;
      return tblLine(ROLE_AREA_COLS, [`<span class="rinstname">${esc(i.name)}</span>`,
        box("data-riread", k, `Read ${label} on ${i.name}`, !!at, false, false),
        box("data-riwrite", k, `Write ${label} on ${i.name}`, at === "write", false, !at)],
        "div", "rarea rinst", `data-rinst="${esc(k)}"`); }).join("") : "");
  }).join("");
  // Why some rows are gray, said once above the table, in the reason's
  // color (the design: the reason under a dead control).
  const why = !ro && (d.areas || []).some(([, , group]) => offOf(group))
    ? `<div class="sub bad" id="rolesWhyOff">The gray areas are not about one project: only an Everywhere role holds them.</div>` : "";
  const areas = why + tblWrap(ROLE_AREA_COLS, rows, "rareas");
  return rolesSplit("roles", list, `${pick}
    <div class="setrow col">${lbl("rolesScope", "Kind", "On a project: given per project under People, and holds there. Everywhere: given to the account, holds on every project and is the only kind that reaches the nodes, toolchains and the controller")}
      <select id="rolesScope"${ro ? " disabled" : ""}>
        <option value="projects"${r.scope !== "global" ? " selected" : ""}>On a project</option>
        <option value="global"${r.scope === "global" ? " selected" : ""}>Everywhere</option>
      </select></div>
    ${ro ? "" : `<div class="setrow col">${lbl("rolesNote", "What this role is for")}<input id="rolesNote" value="${esc(r.note)}" autocomplete="off"></div>`}
    ${areas}
    ${r.builtin ? `<div class="sub">${esc(r.note)}. Built in, every area to write, and not changed here.</div>` : ""}
    ${ro ? "" : `<div class="actbar"><span class="state">${rolesRoleDirty() ? "unsaved" : ""}</span>
      <button type="button" id="rolesRevert">Revert</button>
      <button type="button" class="primary" id="rolesSave">Save</button>
      ${r.fresh ? "" : `<button type="button" class="danger" id="rolesRemove">Remove</button>`}</div>`}`);
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
    const split = detail => `<div class="rsplit"><div class="rlist">${skRows(4)}</div><div class="rdetail">${detail}</div></div>`;
    const field = (label, em) => `<div class="setrow col"><span class="lbl">${esc(label)}</span>${skv(em, "ctl")}</div>`;
    d.list.innerHTML = skTpl(docSection("roles", "people", "People", "", split(field("Everywhere roles", 18) + field("Projects", 22)))
      + docSection("roles", "roles", "Roles", "", split(field("Kind", 16) + skRows(5))));
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
  // An account or a role picked from its list (on a phone, the detail
  // comes over the list), and Back to the list.
  el.querySelectorAll("[data-rwho]").forEach(b => b.onclick = () => {
    if (b.dataset.rwho !== rolesWho && rolesPeopleDirty() && !confirm(`Leave ${rolesWho}'s changes unsaved?`)) return;
    rolesWho = b.dataset.rwho; rolesPeopleDraft = null; rolesOpen.people = true; rolesRedraw();
  });
  el.querySelectorAll("[data-rpick]").forEach(b => b.onclick = () => {
    if (b.dataset.rpick !== rolesPick && rolesRoleDirty() && !confirm(`Leave the changes to ${rolesDraft.name} unsaved?`)) return;
    rolesPick = b.dataset.rpick; rolesDraft = null; rolesOpen.roles = true; rolesRedraw();
  });
  el.querySelectorAll("[data-rback]").forEach(b => b.onclick = () => { rolesOpen[b.dataset.rback] = false; rolesRedraw(); });
  // Off a project: every role it held there goes, which is being off it.
  el.querySelectorAll("[data-rprojoff]").forEach(b => b.onclick = () => {
    delete rolesPeopleDraft.project_roles[b.dataset.rprojoff];
    rolesRedraw();
  });
  // On a project: the one picked, with the role picked for it there.
  const ap = el.querySelector("#rolesAddProj"), ar = el.querySelector("#rolesAddRole"), ao = el.querySelector("#rolesAddOn");
  if (ap) ap.onchange = () => { rolesAddProj = ap.value; rolesRedraw(); };
  if (ao) ao.onclick = () => {
    if (!ap?.value || !ar?.value) return;
    rolesPeopleDraft.project_roles[ap.value] = [ar.value];
    rolesAddProj = "";
    rolesRedraw();
  };
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

  const add = el.querySelector("#rolesAdd"), nm = el.querySelector("#rolesNewName");
  if (add) add.onclick = () => {
    const name = (nm?.value || "").trim();
    if (!name) return notify("a name for the role", true);
    if (rolesData.roles[name]) return notify(`${name} is a role already`, true);
    rolesDraft = {name, scope: "projects", perms: {}, note: "", fresh: true, builtin: false, only: {}};
    rolesOpen.roles = true;
    rolesRedraw();
  };
  const sc = el.querySelector("#rolesScope");
  if (sc) sc.onchange = () => {
    rolesDraft.scope = sc.value;
    if (sc.value !== "global") rolesDraft.only = {};
    // A role on the user's projects holds project areas only.
    if (sc.value !== "global")
      for (const [key, , group] of rolesData.areas) if (group === "global") delete rolesDraft.perms[key];
    rolesRedraw();
  };
  // A box ticked on one row in three, partly (R260).
  el.querySelectorAll("input[data-part]").forEach(cb => { cb.indeterminate = true; });
  el.querySelectorAll("[data-rexp]").forEach(b => b.onclick = () => {
    const k = b.dataset.rexp;
    if (rolesExp.has(k)) rolesExp.delete(k); else rolesExp.add(k);
    rolesRedraw();
  });
  const note = el.querySelector("#rolesNote");
  if (note) note.oninput = () => { rolesDraft.note = note.value; };
  // The area's own boxes say it for every instance: Read ticked reads on
  // every one (keeping Write where it was), cleared reads on none; Write
  // ticked writes on every one, cleared leaves each reading.
  el.querySelectorAll("[data-rread]").forEach(cb => cb.onchange = () => {
    const k = cb.dataset.rread;
    if (rolesInsts(k).length && rolesDraft.scope === "global")
      rolesSetAll(k, (id, at) => cb.checked ? (at || "read") : "");
    else if (cb.checked) rolesDraft.perms[k] = rolesDraft.perms[k] || "read";
    else { delete rolesDraft.perms[k]; if (rolesDraft.only) delete rolesDraft.only[k]; }   // no Read, no Write
    rolesRedraw();
  });
  el.querySelectorAll("[data-rwrite]").forEach(cb => cb.onchange = () => {
    const k = cb.dataset.rwrite;
    if (rolesInsts(k).length && rolesDraft.scope === "global")
      rolesSetAll(k, (id, at) => cb.checked ? "write" : (at ? "read" : ""));
    else rolesDraft.perms[k] = cb.checked ? "write" : "read";
    rolesRedraw();
  });
  // ...and an instance's say it for that one.
  el.querySelectorAll("[data-riread],[data-riwrite]").forEach(cb => cb.onchange = () => {
    const [k, one] = (cb.dataset.riread || cb.dataset.riwrite).split(/\|(.*)/s);
    const read = "riread" in cb.dataset;
    rolesSetAll(k, (id, at) => id !== one ? at
      : read ? (cb.checked ? (at || "read") : "") : (cb.checked ? "write" : (at ? "read" : "")));
    rolesRedraw();
  });
  const rr = el.querySelector("#rolesRevert");
  if (rr) rr.onclick = () => { rolesDraft = null; rolesRedraw(); };
  const rs = el.querySelector("#rolesSave");
  if (rs) rs.onclick = async () => {
    busy(rs, "Saving");
    const r = rolesDraft;
    if (await rolesAct({action: "set", name: r.name, scope: r.scope, perms: r.perms, note: r.note,
                        only: r.scope === "global" ? r.only : {}}, `${r.name} saved`)){
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
