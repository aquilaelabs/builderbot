// The Roles tab (R152, the operator, 7 Oct): a page of settings, the roles
// a list beside the one picked (R255 step 9; the operator, 17 Oct): one
// list, the projects' owner roles folded into one row at its end, New role
// at the right of the page's bar in a dialog, and Remove at the foot of the
// picked one's settings. Its kind (Everywhere, or On a project) and Read
// and Write per area, Write needing Read; owner and admin are built in and
// read only.
//
// What one account holds (its Everywhere roles, the projects it is on with
// its roles there, holding one being on the project, R155, and what that
// adds up to) is picked in its settings on the Users page, beside its name
// and password: rolesAccessFields below draws it there. The server holds every rule (roles.py, users.assign) and this
// file draws and asks.
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
    const r = await bootFetch("/api/roles");
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

// ---- an account's access, in the Users page's Edit dialog ---------------
function rolesPerson(){
  return (rolesData?.people || []).find(p => p.name === rolesWho) || null;
}

function rolesPeopleFrom(p){
  return p ? {roles: [...(p.roles || [])],
              project_roles: JSON.parse(JSON.stringify(p.project_roles || {}))} : null;
}

// ---- a list beside the one picked ----------------------------------------
// On a phone the list, then the detail sliding in over it with Back, and the
// list sliding back (the shape every page of settings has).
let rolesPhoneOpen = false;      // on a phone, the detail is over the list
let rolesMoveNext = "";          // the slide the next draw plays
let rolesOwnersOpen = false;     // the projects' owner roles shown on the list
function rolesSplit(which, list, detail){ return {which, list, detail}; }

// The roles a project offers: every role on a project, and its own owner
// role there and nowhere else (B726).
const rolesOnProject = pn => Object.values(rolesData.roles || {}).filter(r => r.scope === "projects" && (!r.project || r.project === pn));

// Its fields, for the account `name` (the Edit dialog's): the owner's say it
// holds everything and are not changed here.
function rolesAccessFields(name){
  const d = rolesData;
  if (rolesWho !== name){ rolesWho = name; rolesPeopleDraft = null; }
  const p = rolesPerson();
  if (!p) return `<div class="sub dim">${esc(name)}'s roles are not yours to give.</div>`;
  if (p.role === "owner")
    return `<div class="sub">BuilderBot's owner: every area, everywhere, and not changed here.</div>`;
  if (!rolesPeopleDraft) rolesPeopleDraft = rolesPeopleFrom(p);
  const dr = rolesPeopleDraft;
  // Accounts and roles Read alone: the same fields, to read (B34).
  const ro = !d.admin && !!d.readonly, dead = ro ? " disabled" : "";
  const everywhere = Object.values(d.roles || {}).filter(r => r.scope === "global" && r.name !== "owner");
  const global = d.admin || ro ? `<div class="setrow col ctlrow">${lbl("", "Everywhere roles", "hold on every project and on BuilderBot itself, as far as each one's areas say")}
      <div class="upick" id="rolesGlobal">${everywhere.map(r => `<label class="pick"><input type="checkbox" data-rglobal="${esc(r.name)}"${
        dr.roles.includes(r.name) ? " checked" : ""}${dead}> ${esc(r.label || r.name)}</label>`).join("")}</div></div>` : "";
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
        have.includes(r.name) ? " checked" : ""}${dead}> ${esc(r.label || r.name)}</label>`).join("")}</span>
      ${ro ? "" : rmIcon(`data-rprojoff="${esc(pn)}"`, `Take ${p.name} off ${projLabel(pn)}`, {title: "take off this project: every role there goes"})}
    </div>`;
  }).join("");
  // The projects it is not on that offer a role (another project's owner
  // role is not one this project offers, B35).
  const notOn = all.filter(pn => !on.includes(pn));
  const off = notOn.filter(pn => rolesOnProject(pn).length);
  const addPn = off.includes(rolesAddProj) ? rolesAddProj : off[0] || "";
  // No role on a project it could join: there is nothing to put it on a
  // project with, and the place that makes one is named instead of an
  // empty picker.
  const add = ro ? "" : notOn.length && !off.length ? `<div class="sub dim raddon">No role on a project yet: one made on the ${pageLink("roles", "Roles page")} puts ${esc(p.name)} on a project.</div>`
    : off.length ? `<div class="raddon">
      <select id="rolesAddProj" aria-label="the project">${optionList(off.map(pn => [pn, projLabel(pn)]), addPn)}</select>
      <select id="rolesAddRole" aria-label="the role there">${optionList(rolesOnProject(addPn).map(r => [r.name, r.label || r.name]))}</select>
      <button type="button" id="rolesAddOn"${rolesOnProject(addPn).length ? "" : " disabled"}>Add to project</button></div>` : "";
  return `${global}
    <div class="setrow col ctlrow">${lbl("", d.admin || ro ? "Projects" : "Your projects", "a role on a project puts the account on it; taken off, it is not on it")}
      <div class="rprojects">${rows || `<div class="empty">on no project yet</div>`}</div>${add}</div>
    ${rolesCanDo(p.name, dr)}`;
}

// Its controls, wired in `el`; `redraw` draws the fields again from the draft.
function wireRolesAccess(el, redraw){
  // Off a project: every role it held there goes, which is being off it.
  el.querySelectorAll("[data-rprojoff]").forEach(b => b.onclick = () => {
    delete rolesPeopleDraft.project_roles[b.dataset.rprojoff];
    redraw();
  });
  // On a project: the one picked, with the role picked for it there.
  const ap = el.querySelector("#rolesAddProj"), ar = el.querySelector("#rolesAddRole"), ao = el.querySelector("#rolesAddOn");
  if (ap) ap.onchange = () => { rolesAddProj = ap.value; redraw(); };
  if (ao) ao.onclick = () => {
    if (!ap?.value || !ar?.value) return;
    rolesPeopleDraft.project_roles[ap.value] = [ar.value];
    rolesAddProj = "";
    redraw();
  };
  el.querySelectorAll("[data-rglobal]").forEach(cb => cb.onchange = () => {
    const dr = rolesPeopleDraft, n = cb.dataset.rglobal;
    dr.roles = cb.checked ? [...new Set([...dr.roles, n])] : dr.roles.filter(x => x !== n);
    redraw();
  });
  el.querySelectorAll("[data-rprole]").forEach(cb => cb.onchange = () => {
    const dr = rolesPeopleDraft, p = cb.closest("[data-rproject]").dataset.rproject, n = cb.dataset.rprole;
    const have = dr.project_roles[p] || [];
    dr.project_roles[p] = cb.checked ? [...new Set([...have, n])] : have.filter(x => x !== n);
    redraw();
  });
}

// Saved with the dialog: nothing sent when nothing changed. True when it
// landed or there was nothing to send.
async function rolesAccessSave(){
  if (!rolesPeopleDirty()) return true;
  const dr = rolesPeopleDraft;
  const body = {action: "assign", name: rolesWho, project_roles: {}};
  for (const p of rolesData.projects || []) body.project_roles[p] = dr.project_roles[p] || [];
  if (rolesData.admin) body.roles = dr.roles;
  const ok = await rolesAct(body, `${rolesWho}'s roles saved`);
  if (ok) rolesPeopleDraft = null;
  return ok;
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
    return `<div class="setrow col ctlrow">${lbl("", `What ${name} can do`)}<div class="sub">everything but change the owner: admin holds every area</div></div>`;
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
  return `<div class="setrow col ctlrow">${lbl("", `What ${name} can do`, "worked out from the boxes above, saved or not")}
    ${grid}
    <div class="sub">${beyond ? `<b>Beyond projects</b>: ${esc(beyond)}` : `<span class="dim">nothing beyond projects</span>`}</div></div>`;
}

function rolesPeopleDirty(){
  const p = rolesPerson();
  return !!p && !!rolesPeopleDraft && JSON.stringify(rolesPeopleFrom(p)) !== JSON.stringify(rolesPeopleDraft);
}

// The same fields in a dialog of their own, for a project's owner who gives
// its roles from the project's People section and has no Users page.
async function rolesAccessOpen(name, saved = () => {}){
  if (rolesData === null) await loadRoles();
  let m = document.getElementById("ramodal");
  if (!m){
    m = document.createElement("div");
    m.id = "ramodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  rolesWho = ""; rolesPeopleDraft = null;
  m.innerHTML = `<div class="box"><h3>${esc(name)}'s roles</h3><div id="raFields"></div>
    ${dlgFoot(`<button type="button" id="raCancel">Cancel</button>`, `<button type="button" id="raSave" class="primary">Save</button>`)}</div>`;
  const draw = () => { const box = m.querySelector("#raFields");
    box.innerHTML = rolesAccessFields(name); wireRolesAccess(box, draw); };
  draw();
  m.hidden = false;
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  m.querySelector("#raCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#raSave").onclick = async () => {
    const btn = m.querySelector("#raSave");
    busy(btn, "Saving");
    if (await rolesAccessSave()) m.hidden = true;
    if (btn.isConnected) unbusy(btn, "Save");
    saved();
  };
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
  const people = n => { const h = holders(n).length; return h ? `${h} ${h === 1 ? "person" : "people"}` : "nobody"; };
  const row = (n, name, tag, cls = "") => { const on = n === rolesPick && !r?.fresh;
    return `<button type="button" class="rrow${cls}${on ? " on" : ""}" data-rpick="${esc(n)}"${on ? ' aria-current="true"' : ""}>
      <span class="rline"><span class="name">${esc(name)}</span>${tag ? `<span class="pill">${esc(tag)}</span>` : ""}</span>
      <span class="rfacts">${esc(people(n))}</span></button>`; };
  // One list (the operator, 17 Oct: no heading or field halfway down it):
  // built in first, then the ones made here, each with its kind, and the
  // projects' owner roles, one per project and each the same shape, folded
  // into one row at the end that opens on them.
  const kind = x => x.builtin ? "built in" : x.scope === "global" ? "everywhere" : "on a project";
  const owners = names.filter(n => !d.roles[n].builtin && d.roles[n].project);
  const plain = names.filter(n => !owners.includes(n));
  const ownersOpen = rolesOwnersOpen || owners.includes(rolesPick) && !r?.fresh;
  const list = plain.map(n => row(n, d.roles[n].label || n, kind(d.roles[n]))).join("")
    + (r?.fresh ? `<button type="button" class="rrow on" aria-current="true"><span class="rline"><span class="name">${esc(r.name)}</span></span><span class="rfacts">new, not saved</span></button>` : "")
    + (owners.length ? `<button type="button" class="rrow rfold" data-rowners aria-expanded="${ownersOpen ? "true" : "false"}">
        <span class="rline"><span class="name">Project owners <span class="rchev" aria-hidden="true">${ownersOpen ? "▾" : "▸"}</span></span></span>
        <span class="rfacts">one per project, ${owners.length} project${owners.length === 1 ? "" : "s"}</span></button>`
       + (ownersOpen ? owners.map(n => row(n, projLabel(d.roles[n].project), "", " rsub")).join("") : "") : "");
  if (!r) return rolesSplit("roles", list, `<div class="empty">no role picked</div>`);
  const who = r.fresh ? [] : holders(r.name);
  const pick = `<div class="rhead" data-rback><span class="shback" role="img" aria-label="Back to Roles">\u2039</span><b>${esc(r.fresh ? r.name : (d.roles[r.name]?.label || r.name))}</b>${
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
  // Why some rows are gray, said once above the table: how the form works,
  // not a fault, so in the hint's voice (the operator, 21 Oct).
  const why = !ro && (d.areas || []).some(([, , group]) => offOf(group))
    ? `<div class="sub" id="rolesWhyOff">The gray areas are not about one project: only an Everywhere role holds them.</div>` : "";
  const areas = why + tblWrap(ROLE_AREA_COLS, rows, "rareas");
  return rolesSplit("roles", list, `${pick}
    <div class="setrow col ctlrow">${lbl("rolesScope", "Kind", "On a project: given per project under People, and holds there. Everywhere: given to the account, holds on every project and is the only kind that reaches the nodes, toolchains and the controller")}
      <select id="rolesScope"${ro ? " disabled" : ""}>
        <option value="projects"${r.scope !== "global" ? " selected" : ""}>On a project</option>
        <option value="global"${r.scope === "global" ? " selected" : ""}>Everywhere</option>
      </select></div>
    ${ro ? "" : `<div class="setrow col ctlrow">${lbl("rolesNote", "What this role is for")}<input id="rolesNote" value="${esc(r.note)}" autocomplete="off"></div>`}
    ${areas}
    ${r.builtin ? `<div class="sub">${esc(r.note)}. Built in, every area to write, and not changed here.</div>`
      : ""}
    ${r.fresh ? "" : `<label class="ndcap rtwofactor"><input type="checkbox" id="rolesTf"${
      d.roles[r.name]?.two_factor ? " checked" : ""}${d.admin ? "" : " disabled"}> Require two-factor sign-in of everybody holding it${
      helpIcon("each holder without an authenticator app or a passkey is sent to set one up at their next sign-in, and reaches nothing else until they have")}</label>`}
    ${ro ? "" : `${saveBar({save: 'id="rolesSave"', revert: 'id="rolesRevert"', state: rolesRoleDirty() ? "unsaved" : "", dead: !rolesRoleDirty()})}
      ${r.fresh ? "" : `<div class="rfoot"><button type="button" class="danger" id="rolesRemove">Remove ${esc(d.roles[r.name]?.label || r.name)}</button></div>`}`}`);
}

function rolesRoleDirty(){
  const r = rolesDraft;
  if (!r) return false;
  if (r.fresh) return true;
  return JSON.stringify(rolesFrom(rolesData.roles[r.name])) !== JSON.stringify(r);
}

// New role, a dialog from the page's bar: its name and kind, then its areas
// beside the list as any role's, saved there.
function rolesNewOpen(){
  let m = document.getElementById("rnewmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "rnewmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  m.innerHTML = `<div class="box"><h3>New role</h3>
    <div class="field">${lbl("rolesNewName", "Its name")}<input id="rolesNewName" autocomplete="off"></div>
    <div class="field">${lbl("rolesNewScope", "Kind", "On a project: given per project, and holds there. Everywhere: holds on every project and is the only kind that reaches the nodes, toolchains and the controller")}
      <select id="rolesNewScope"><option value="projects">On a project</option><option value="global">Everywhere</option></select></div>
    ${dlgFoot(`<button type="button" id="rolesNewCancel">Cancel</button>`, `<button type="button" id="rolesAdd" class="primary" disabled>Make it</button>`)}</div>`;
  // Make it wakes once a name is typed that no role has (the operator, 18
  // Oct).
  const nm = m.querySelector("#rolesNewName");
  nm.oninput = () => { const v = nm.value.trim(); m.querySelector("#rolesAdd").disabled = !v || !!rolesData.roles[v]; };
  m.hidden = false;
  m.onclick = e => { if (e.target === m) m.hidden = true; };
  m.querySelector("#rolesNewCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#rolesAdd").onclick = () => {
    const name = m.querySelector("#rolesNewName").value.trim();
    if (!name) return notify("a name for the role", true);
    if (rolesData.roles[name]) return notify(`${name} is a role already`, true);
    rolesDraft = {name, scope: m.querySelector("#rolesNewScope").value, perms: {}, note: "", fresh: true, builtin: false, only: {}};
    m.hidden = true;
    rolesPhoneOpen = true; rolesMoveNext = "in";
    rolesRedraw();
  };
  m.querySelector("#rolesNewName").focus();
}

function renderRolesInto(i){
  const d = docSurface(i, "roles");
  if (!d) return;
  // A count, as Users and Jobs keep (the operator, 18 Oct), not a sentence.
  const nRoles = Object.keys(rolesData?.roles || {}).length;
  // Refused outright (a plain account by link): the refusal is the page (B38).
  const refused = rolesErr && !nRoles;
  // No count beside the button (the operator, 25 Oct): the list says it.
  // New role on the head (the operator, 29 Oct: not a row of its own).
  // Waiting, who may add a role is the status read's to say, and the
  // button is there and dead, as it will land.
  d.setBar("");
  const newRole = (rolesData ? rolesData.admin : state?.can?.admin) ? `<button type="button" class="primary"${
      rolesData ? ` id="rolesNewOpen"` : " disabled"}>New role</button>` : "";
  if (rolesData === null){
    // Its template (R218 step 16): the two sections and their fields' labels
    // are the page's own; who holds what is on its way.
    const split = detail => `<div class="rsplit"><div class="rlist">${skRows(4)}</div><div class="rdetail">${detail}</div></div>`;
    const field = skField;
    d.list.innerHTML = skTpl(pageHead({facts: [["Roles", GHOST], ["For projects", GHOST]], actions: newRole}) + split(field("Kind", 12) + skTable(ROLE_AREA_COLS, 4, "rareas")));
    loadRoles();
    return;
  }
  if (refused){
    d.list.innerHTML = `<div class="row bad"><div class="grow">${esc(rolesErr)}</div></div>`;
    return;
  }
  const ro = rolesRoleBody();
  // The page's head (the operator, 29 Oct): how many roles, and how many
  // of them are a project's.
  const all = Object.values(rolesData.roles || {});
  d.list.innerHTML = `
    ${rolesErr ? `<div class="row bad"><div class="grow">${esc(rolesErr)}</div></div>` : ""}
    ${pageHead({facts: [["Roles", String(all.length)], ["For projects", String(all.filter(r => r.scope === "projects").length)]], actions: newRole})}
    <div class="rsplit${rolesPhoneOpen ? " open" : ""}">
      <div class="rlist">${ro.list}</div>
      <div class="rdetail">${ro.detail}</div>
    </div>`;
  wireRoles(d.el);
  if (rolesMoveNext){ splitMove(d.list.querySelector(".rsplit"), rolesMoveNext); rolesMoveNext = ""; }
}

// Repaint the tab, keeping the drafts: the sections read them.
function rolesRedraw(){ rolesRev++; drawPanes(); }

function wireRoles(el){
  // A role picked from its list (on a phone, the detail comes over the
  // list), the owners' row opened or shut, and Back to the list.
  el.querySelectorAll("[data-rpick]").forEach(b => b.onclick = async () => {
    if (b.dataset.rpick !== rolesPick && rolesRoleDirty() && !await askYes(`Leave the changes to ${rolesDraft.name} unsaved?`)) return;
    splitAway(() => document.querySelectorAll(".pane .doc.on .rsplit > .rdetail"), () => {
      rolesPick = b.dataset.rpick; rolesDraft = null; rolesPhoneOpen = true; rolesMoveNext = "in"; rolesRedraw(); });
  });
  el.querySelectorAll("[data-rowners]").forEach(b => b.onclick = () => {
    rolesOwnersOpen = b.getAttribute("aria-expanded") !== "true";
    rolesRedraw();
  });
  // The picked role's head is the way back on a phone, as a page of
  // settings' section head is (splitSects).
  el.querySelectorAll("[data-rback]").forEach(b => b.onclick = () => { if (!matchMedia("(max-width: 900px)").matches) return; rolesPhoneOpen = false; rolesMoveNext = "back"; rolesRedraw(); });

  const nw = el.querySelector("#rolesNewOpen");
  if (nw) nw.onclick = () => rolesNewOpen();
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
  const tf = el.querySelector("#rolesTf");
  if (tf) tf.onchange = () => rolesAct({action: "two-factor", name: rolesDraft.name, on: tf.checked},
    tf.checked ? `${rolesDraft.name}: two-factor sign-in required` : `${rolesDraft.name}: two-factor sign-in no longer required`);
  const note = el.querySelector("#rolesNote");
  if (note) note.oninput = () => {
    rolesDraft.note = note.value;
    // Save and Revert awake only while the role is unsaved (the operator, 26 Oct).
    const dirty = rolesRoleDirty(), st = el.querySelector("#rolesSave")?.closest(".actbar")?.querySelector(".state");
    if (st) st.textContent = dirty ? "unsaved" : "";
    for (const b of el.querySelectorAll("#rolesSave, #rolesRevert")) if (!b.dataset.busy) b.disabled = !dirty;
  };
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
    if (!await askYes(`Remove the role ${rolesDraft.name}? Accounts that hold it lose what it gave.`)) return;
    if (await rolesAct({action: "remove", name: rolesDraft.name}, `${rolesDraft.name} removed`)){
      rolesPick = ""; rolesDraft = null;
    }
    rolesRedraw();
  };
}
