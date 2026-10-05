// The Roles tab (R137): what an account may read and change, as named
// roles made of grants, under the Administration card. A role is one job
// (deployer, tester); an account carries one or more and their grants add
// up. The built-in owner, admin and user are shown and not edited: Copy
// makes a role of your own from one. Every rule about WHAT a grant allows
// lives on the server (roles.py, users.may); this file draws and asks.
//
// Chrome comes from docSurface() and the hard rules are held by
// uniform.mjs; this file fills slots, one fold per role.
"use strict";
let rolesList = null;            // {name: role}, or null before the first load
let rolesRev = 0;
let rolesErr = "";
let rolesMeta = {caps: {}, groups: [], projects: []};
let rolesOpen = new Set();       // the roles whose fold is open
let rolesDraft = null;           // a new role being written: {name, note, grants}

function openRolesTab(){
  openTab({kind: "roles", arg: "__roles", label: "Roles"});
}

async function loadRoles(){
  try{
    const j = await (await fetch("/api/roles")).json();
    rolesErr = j.error || "";
    rolesList = j.roles || {};
    rolesMeta = {caps: j.caps || {}, groups: j.groups || [], projects: j.projects || []};
  }catch(e){
    rolesErr = String(e);
    rolesList = rolesList || {};
  }
  rolesRev++;
  drawPanes();
}

async function rolesAct(body){
  try{
    const r = await fetch("/api/roles", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) return notify(j.error || `failed (HTTP ${r.status})`, true);
    notify(body.action === "remove" ? `${body.name} removed` : `${body.name} saved`);
    if (body.action === "set") rolesDraft = null;
  }catch(e){ return notify(String(e), true); }
  await loadRoles();
}

// One grant as the editor shows it: the capability's sentence, and where it
// holds. A scope is "mine" (the projects the account is on), "all", or a
// list of named projects, which the picker under the row holds.
function roleGrantRow(role, cap, g, editable){
  const [, sentence] = rolesMeta.caps[cap] || ["", cap];
  const sc = g ? g.scope : null;
  const named = Array.isArray(sc) ? sc : [];
  const id = `rg-${role}-${cap}`.replace(/[^A-Za-z0-9_-]/g, "_");
  // A field in the fold, like Add somebody's (the design's bands): the
  // tick and the capability, its sentence under it where it wraps, and the
  // scope under that while the tick is on.
  return `<div class="setrow col rgrant" data-cap="${esc(cap)}">
    <label class="pick"><input type="checkbox" data-rcap="${esc(cap)}"${g ? " checked" : ""}${editable ? "" : " disabled"}> <b>${esc(cap)}</b></label>
    <div class="sub">${esc(sentence)}</div>
    <div class="rscope"${g ? "" : " hidden"}>
      <label class="pick">Where <select data-rscope="${esc(cap)}" aria-label="where ${esc(cap)} holds"${editable ? "" : " disabled"}>
        <option value="mine"${sc === "mine" ? " selected" : ""}>the projects the account is on</option>
        <option value="all"${sc === "all" ? " selected" : ""}>every project</option>
        <option value="named"${Array.isArray(sc) ? " selected" : ""}>these projects</option>
      </select></label>
      <div class="upick rnamed"${Array.isArray(sc) ? "" : " hidden"}>${rolesMeta.projects.length
        ? rolesMeta.projects.map(p => `<label class="pick"><input type="checkbox" data-rproj="${esc(p)}"${
            named.includes(p) ? " checked" : ""}${editable ? "" : " disabled"}> ${esc(p)}</label>`).join(" ")
        : `<div class="sub">no projects to name</div>`}</div>
    </div>
  </div>`;
}

// A role's fold: its note, its grants by group, and Save, Copy or Remove.
function roleSection(r){
  const editable = !r.builtin;
  const byCap = {};
  for (const g of r.grants || []){
    if (g.cap === "*") for (const c of Object.keys(rolesMeta.caps)) byCap[c] = {cap: c, scope: g.scope};
    else byCap[g.cap] = g;
  }
  const body = `
    ${editable ? `<div class="setrow col">${lbl(`rnote-${esc(r.name)}`, "What this role is for")}
        <input data-rnote value="${esc(r.note || "")}" autocomplete="off"></div>`
      : `<div class="sub">${esc(r.note || "")} · built in, and not edited: Copy makes one of your own from it</div>`}
    ${rolesMeta.groups.map(([key, title]) => `<div class="sub rgroup">${esc(title)}</div>${
      Object.keys(rolesMeta.caps).filter(c => rolesMeta.caps[c][0] === key)
        .map(c => roleGrantRow(r.name, c, byCap[c], editable)).join("")}`).join("")}
    <div class="actbar">${editable
      ? `<button type="button" class="primary" data-rsave="${esc(r.name)}">Save</button>
         <button type="button" class="danger" data-rremove="${esc(r.name)}">Remove</button>`
      : `<button type="button" data-rcopy="${esc(r.name)}">Copy</button>`}</div>`;
  const status = r.builtin ? "built in" : `${(r.grants || []).length} grant${(r.grants || []).length === 1 ? "" : "s"}`;
  return docSection("roles", `r-${r.name}`, r.name, status, body);
}

function renderRolesInto(i){
  const d = docSurface(i, "roles");
  if (!d) return;
  d.setBar(`<span class="dim">named roles made of grants; an account carries one or more, and they add up</span>`);
  if (rolesList === null){
    d.list.innerHTML = `<div class="row"><div class="sub">loading<span class="dots"></span></div></div>`;
    loadRoles();
    return;
  }
  const names = Object.keys(rolesList);
  d.list.innerHTML = `
    ${rolesErr ? `<div class="row bad"><div class="grow">${esc(rolesErr)}</div></div>` : ""}
    ${names.map(n => roleSection(rolesList[n])).join("")}
    ${docSection("roles", "new", "New role", "", `
      <div class="setrow col">${lbl("rNewName", "Name", "one job: deployer, tester, reviewer")}
        <input id="rNewName" autocomplete="off" value="${esc(rolesDraft?.name || "")}"></div>
      <div class="sub">A new role starts with no grants: it is made here, then its grants are ticked in its own fold above and saved there.</div>
      <div class="actbar"><button type="button" class="primary" id="rNew">Make it</button></div>`)}`;
  wireSections(d.list);
  d.setFoot(`A grant adds and never takes away: an account with two roles may do what either allows.
    The built-in roles reproduce what owner, admin and user could do before roles existed.`);
  wireRoles(d.el);
}

// What the editor holds for one role, read back from its rows.
function roleGrantsFrom(sec){
  const out = [];
  for (const row of sec.querySelectorAll(".rgrant")){
    const cb = row.querySelector("[data-rcap]");
    if (!cb || !cb.checked) continue;
    const sel = row.querySelector("[data-rscope]");
    let scope = sel ? sel.value : "mine";
    if (scope === "named") scope = [...row.querySelectorAll("[data-rproj]")].filter(c => c.checked).map(c => c.dataset.rproj);
    out.push({cap: cb.dataset.rcap, scope});
  }
  return out;
}

function wireRoles(el){
  // A grant's scope row shows with its tick, and its names with "these
  // projects": drawn once, toggled in place, saved on Save.
  el.querySelectorAll("[data-rcap]").forEach(cb => cb.onchange = () => {
    const row = cb.closest(".rgrant");
    row.querySelector(".rscope").hidden = !cb.checked;
  });
  el.querySelectorAll("[data-rscope]").forEach(sel => sel.onchange = () => {
    sel.closest(".rscope").querySelector(".rnamed").hidden = sel.value !== "named";
  });
  el.querySelectorAll("[data-rsave]").forEach(b => b.onclick = () => {
    const sec = b.closest(".sect") || el;
    const grants = roleGrantsFrom(sec);
    if (grants.some(g => Array.isArray(g.scope) && !g.scope.length))
      return notify("a grant on these projects needs at least one named", true);
    rolesAct({action: "set", name: b.dataset.rsave, grants,
              note: sec.querySelector("[data-rnote]")?.value || ""});
  });
  el.querySelectorAll("[data-rremove]").forEach(b => b.onclick = () => {
    if (confirm(`Remove the role ${b.dataset.rremove}? Accounts that carry it lose its grants.`))
      rolesAct({action: "remove", name: b.dataset.rremove});
  });
  el.querySelectorAll("[data-rcopy]").forEach(b => b.onclick = () => {
    const src = rolesList[b.dataset.rcopy];
    const name = prompt(`A role of your own, copied from ${src.name}. Its name:`, `${src.name} copy`);
    if (!name) return;
    rolesAct({action: "set", name: name.trim(), grants: src.grants, note: `copied from ${src.name}`});
  });
  const nw = el.querySelector("#rNew");
  const nameIn = el.querySelector("#rNewName");
  if (nameIn) nameIn.oninput = () => { rolesDraft = {name: nameIn.value}; };
  if (nw) nw.onclick = () => {
    const name = (nameIn?.value || "").trim();
    if (!name) return notify("a name", true);
    // Made with the one grant everybody has, so it exists to be edited; the
    // server refuses an empty role.
    rolesAct({action: "set", name, grants: [{cap: "read", scope: "mine"}], note: ""});
  };
}
