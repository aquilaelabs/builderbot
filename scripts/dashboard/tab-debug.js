// The Debug page (R147): beside Controller settings, and drawn only on a
// controller started with DEBUG_MODE=1 for an account with the debug grant
// (railAllows). Not an advertised feature (the operator, 26 Oct): no tour,
// and nothing of it in the changelog. Its head says debug mode is on and
// why; Dev features holds Offer dev features; What sessions may read holds
// every project's grants, the controller's diagnostics and each node's
// machine logs, which a project's settings held before (prefs diag and
// log_from, the project's own).
//
// Chrome from docSurface(); drawn from the status read and the node list,
// so it follows the poll; what is ticked and not saved is held here.

"use strict";

let debugGrants = {};            // a project key -> {diag, log_from}, ticked and not saved
let debugDev = null;             // Offer dev features ticked and not saved, or null

function openDebugTab(){
  openTab({kind: "debug", arg: "__debug", label: "Debug"});
}

// A project's grants as saved, or as ticked since.
function debugGrant(c){
  return debugGrants[c.key] || {diag: !!c.first?.prefs?.diag, log_from: [...(c.first?.prefs?.log_from || [])]};
}

function renderDebugInto(i){
  const d = docSurface(i, "debug");
  if (!d) return;
  d.setBar("");
  if (nodesList === null) loadNodes();
  const nodes = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  const dev = debugDev ?? !!state?.settings?.settings?.offer_unvetted?.value;
  // A project with a repository: the grants are saved through it, as its
  // settings saved them.
  const rows = projectList().filter(c => c.first).sort(byProjectName);
  // Its rows wait for the node list, whose machine logs each row offers,
  // so they are drawn once and whole rather than again when it lands.
  const granted = rows.filter(c => { const g = debugGrant(c); return g.diag || g.log_from.length; }).length;
  const staged = Object.keys(debugGrants).length > 0;
  const row = c => {
    const g = debugGrant(c);
    return `<div class="row stack2 dbgrow" data-dbgproj="${esc(c.key)}"><div class="grow">
        <div class="name">${esc(c.name)}</div>
        <div class="lbox dbgbox">${lrow("@diag", "The controller's diagnostics", "bb diag", g.diag)}${
          nodes.map(n => lrow(n.id, n.name, "machine logs", g.log_from.includes(n.id))).join("")}</div></div></div>`;
  };
  const html = pageHead({title: "Debug mode", pills: `<span class="pill ok">on</span>`,
                         facts: [["Turned on by", "DEBUG_MODE=1 where this controller starts"]]})
    + docSection("debug", "dev", "Dev features", dev ? "offered" : "off",
        `<div class="field"><label class="ndcap"><input type="checkbox" id="dbgDev"${dev ? " checked" : ""}> Offer dev features${
          helpIcon("Also offer what has not been tested end to end yet, tagged dev: git hosts, node systems, hypervisors, WireGuard and Tailscale when enrolling, an account per user on a node, the VS Code extension and the Windows companion.")}</label></div>
        <div class="field"><div class="actbar"><span class="sp"></span>
          <button type="button" class="primary" id="dbgDevSave"${debugDev === null ? " disabled" : ""}>Save</button></div></div>`)
    + docSection("debug", "grants", "What sessions may read", nodesList === null ? "" : `${granted} granted`,
        `<div class="field"><div class="hint">A project's sessions read what is ticked for it, and only while their account holds the debug grant.</div></div>
        ${nodesList === null ? skRows(2)
          : rows.length ? rows.map(row).join("") : `<div class="empty">No project with a repository yet.</div>`}
        <div class="field"><div class="actbar"><span class="sp"></span>
          <button type="button" class="primary" id="dbgSave"${staged ? "" : " disabled"}>Save</button>
          <button type="button" class="caution" id="dbgRevert"${staged ? "" : " disabled"}>Revert</button></div></div>`);
  // In one wrapper, as the Agents page's: the jump bar wireSections puts
  // over the two sections goes inside it, so the list's own children are
  // what was painted and a read that brings nothing writes nothing.
  if (paint(d.list, `<div class="dbgpage">${html}</div>`)) wireDebug(d.el);
}

function wireDebug(el){
  wireSections(el);
  el.querySelectorAll("[data-dbgproj]").forEach(r => r.querySelectorAll("input").forEach(i => i.onchange = () => {
    const on = [...r.querySelectorAll("input:checked")].map(x => x.value);
    debugGrants[r.dataset.dbgproj] = {diag: on.includes("@diag"), log_from: on.filter(v => v !== "@diag")};
    drawPanes();
  }));
  const dev = el.querySelector("#dbgDev");
  if (dev) dev.onchange = () => { debugDev = dev.checked; drawPanes(); };
  const devSave = el.querySelector("#dbgDevSave");
  if (devSave) devSave.onclick = async () => {
    busy(devSave, "Saving");
    try{
      const j = await (await postJSON("/api/settings", {set: {offer_unvetted: debugDev}})).json();
      if (j.error){ notify(j.error, true); unbusy(devSave, "Save"); return; }
      debugDev = null;
      notify("saved");
    }catch(e){ notify("settings: " + failWords(e), true); unbusy(devSave, "Save"); return; }
    await refresh();
  };
  const revert = el.querySelector("#dbgRevert");
  if (revert) revert.onclick = () => { debugGrants = {}; drawPanes(); };
  const save = el.querySelector("#dbgSave");
  if (save) save.onclick = async () => {
    busy(save, "Saving");
    for (const [key, g] of Object.entries(debugGrants)){
      const c = projectList().find(x => x.key === key);
      if (!c?.first) continue;
      try{
        const j = await (await postJSON("/api/prefs", {project: c.first.name, diag: g.diag, log_from: g.log_from})).json();
        if (j.error){ notify(`${c.name}: ${j.error}`, true); unbusy(save, "Save"); return; }
      }catch(e){ notify(`${c.name}: ${failWords(e)}`, true); unbusy(save, "Save"); return; }
      delete debugGrants[key];
    }
    notify("saved");
    await refresh();
  };
}
