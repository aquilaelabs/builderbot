// The Storage tab (R169): what a node's disks hold, and whose. One node at
// a time, picked in the bar like Toolchains (the node-switcher rule; the
// operator, 11 Oct): a state row saying when it was measured, its
// filesystems as a meter stack, its stores and Docker's share, then each
// project's folders on it (the synced copy, the build cache, artifacts, a
// dev instance's data, emulators, the accounts' build caches), largest
// first, with every project this account may not see folded into one
// line. The numbers are the agent's hourly walk, said with their age;
// Measure now asks for a fresh one, which the next hello brings.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/storage, read when the tab opens and after Measure now; redrawn on
// the nodes revision, since a hello carries a new walk.

"use strict";

let storageList = null;          // last answer, or null before the first
let storageErr = "";
let storageRev = 0;
let storageMay = false;          // whether this account may measure now
let storageNode = "";            // the node the tab shows

function openStorageTab(node){
  if (node) storageNode = node;
  openTab({kind: "storage", arg: "__storage", label: "Storage"});
}

async function loadStorage(){
  try{
    const j = await (await fetch("/api/storage")).json();
    storageErr = j.error || "";
    storageList = j.nodes || [];
    storageMay = !!j.may_measure;
  }catch(e){
    storageErr = String(e);
    storageList = storageList || [];
  }
  storageRev++;
  if (tabs.some(t => t.kind === "storage")) drawPanes();
}

// The node the tab opens on: the one it showed last (remembered in this
// browser), else the first in the answer, else nothing.
function storagePick(){
  const have = storageList || [];
  let want = storageNode;
  if (!have.some(n => n.node === want)){
    try{ want = localStorage.getItem("bb.stnode") || ""; }catch(e){ want = ""; }
  }
  if (!have.some(n => n.node === want)) want = have[0]?.node || "";
  storageNode = want;
  return have.find(n => n.node === want) || null;
}

// MB as a person reads it: TB above ten million, GB above ten thousand,
// MB below, "?" for unmeasured.
const sgb = mb => mb === null || mb === undefined ? "?"
  : mb >= 10485760 ? (mb / 1048576).toFixed(1) + " TB"
  : mb >= 10240 ? (mb / 1024).toFixed(mb >= 102400 ? 0 : 1) + " GB" : Math.round(mb) + " MB";

function storageFilesystems(n){
  const fss = n.filesystems || [];
  if (!fss.length) return `<div class="empty">no filesystem measured yet</div>`;
  return `<div class="ndmeters">${fss.map(f => {
    const pct = f.total_mb ? (f.used_mb || 0) / f.total_mb * 100 : 0;
    const also = f.also?.length ? `, also at ${f.also.join(", ")}` : "";
    return meter(f.path, pct, `${sgb(f.used_mb)} / ${sgb(f.total_mb)}`,
                 `${f.source} (${f.type}${f.ro ? ", read-only" : ""})${also}`);
  }).join("")}</div>`;
}

function storageStores(n){
  const rows = Object.entries(n.stores || {}).map(([role, s]) =>
    `<div class="row"><div class="grow"><div class="name">${esc(role)} store <span class="dim">· ${esc(s.path)}</span></div>
      <div class="sub">${s.slow ? "not measured in time" : sgb(s.used_mb)}${s.fs ? ` on ${esc(s.fs)}` : ""}</div></div></div>`);
  if (n.workspace?.path) rows.push(`<div class="row"><div class="grow"><div class="name">synced copies <span class="dim">· ${esc(n.workspace.path)}</span></div>
      <div class="sub">on ${esc(n.workspace.fs || "?")}; per project below</div></div></div>`);
  if (n.homes?.path) rows.push(`<div class="row"><div class="grow"><div class="name">the accounts' homes <span class="dim">· ${esc(n.homes.path)}</span></div>
      <div class="sub">${sgb(n.homes.mb)}${n.homes.fs ? ` on ${esc(n.homes.fs)}` : ""}; their build caches per project below</div></div></div>`);
  const dk = n.docker || {};
  if (dk.kinds?.length){
    const total = dk.kinds.reduce((a, k) => a + (k.mb || 0), 0);
    const recl = dk.kinds.reduce((a, k) => a + (k.reclaimable_mb || 0), 0);
    rows.push(`<div class="row"><div class="grow"><div class="name">Docker <span class="dim">· ${esc(dk.root || "its data root")}</span></div>
      <div class="sub">${sgb(total)}${dk.fs ? ` on ${esc(dk.fs)}` : ""}: ${dk.kinds.map(k => `${esc(k.kind.toLowerCase())} ${sgb(k.mb)} (${k.count})`).join(", ")}${
        recl ? `; ${sgb(recl)} of it reclaimable` : ""}</div></div></div>`);
  }
  return rows.join("") || `<div class="empty">no store measured yet</div>`;
}

function storageProjects(n, where){
  const rows = [...(n.projects || [])];
  if (n.other) rows.push({name: "other projects", other: true, ...n.other});
  if (!rows.length) return `<div class="empty">no project's folders here yet</div>`;
  const cols = where.filter(w => rows.some(r => r[w]));
  // Each cell says which column it is (data-k): a desk shows the head row
  // and hides the words, a phone stacks the cells and shows each one's word
  // beside its number, since a column of bare numbers under a name said
  // nothing (the operator's screenshot, B655). An empty cell says so.
  const head = `<div class="row stack2 stproj sthead"><div class="grow"><div class="dim">project</div></div>${
    cols.map(w => `<div class="dim stcol">${esc(w)}</div>`).join("")}<div class="dim stcol">total</div></div>`;
  return head + rows.map(r => `<div class="row stack2 stproj${r.other ? " dim" : ""}">
      <div class="grow"><div class="name">${r.other ? "other projects <span class=\"dim\">· ones you cannot see</span>" : esc(projLabel(r.name))}</div></div>
      ${cols.map(w => `<div class="stcol" data-k="${esc(w)}">${r[w] ? sgb(r[w]) : `<span class="dim">none</span>`}</div>`).join("")}
      <div class="stcol" data-k="total"><b>${sgb(r.total)}</b></div>
    </div>`).join("");
}

// What the tab says about one node: the state row, then its disks.
function storageBody(n, where){
  const age = !n.measured ? "not measured yet"
    : n.age_s < 3600 ? `measured ${Math.round(n.age_s / 60)} min ago` : `measured ${Math.round(n.age_s / 3600)} h ago`;
  const pill = `<span class="pill${n.measured ? "" : " warn"}">${esc(age)}</span>`;
  return `<div data-stnode="${esc(n.node)}">
    <div class="row toolstate">
      <div class="grow"><div class="name">Storage on ${esc(n.name)} ${pill}</div>
        <div class="sub">${n.measured ? `${n.took_s ? `the walk took ${n.took_s}s; ` : ""}walked again every hour` : "the agent walks its disks an hour after it starts, then every hour"}</div></div>
    </div>
    <div class="field">${lbl("", "Filesystems")}${storageFilesystems(n)}</div>
    <div class="field">${lbl("", "Stores")}</div>${storageStores(n)}
    <div class="field">${lbl("", "By project")}
      <div class="hint">What each project's folders hold on ${esc(n.name)}: its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.</div></div>
    ${storageProjects(n, where)}
    ${n.slow?.length ? `<div class="field"><div class="hint warn">Not measured in time: ${esc(n.slow.join(", "))}. A slow share; the next walk tries again.</div></div>` : ""}
    <div class="field"><div class="actbar">
      <span class="state"></span><span class="sp"></span>
      ${storageMay ? `<button type="button" data-stmeasure="${esc(n.node)}" ${n.live ? "" : "disabled"} title="${n.live ? "walk the disks now; the next report brings the numbers" : "the node is not dialing in"}">Measure now</button>` : ""}
    </div></div>
  </div>`;
}

function renderStorageInto(i){
  const d = docSurface(i, "storage");
  if (!d) return;
  if (storageList === null){
    d.list.innerHTML = `<div class="loading">loading…</div>`;
    loadStorage();
    return;
  }
  if (storageErr){
    d.list.innerHTML = `<div class="hint bad">${esc(storageErr)}</div>`;
    return;
  }
  const where = ["workspace", "cache", "artifacts", "appdata", "emulator", "builds"];
  const n = storagePick();
  const pnodes = storageList.map(x => ({id: x.node, name: x.name, live: x.live}));
  d.setBar(`${nodePick("stNodeSel", pnodes, storageNode)}
    <span class="sp"></span><button type="button" id="stReload" title="read the nodes again">Refresh</button>`);
  d.list.innerHTML = n ? storageBody(n, where)
    : `<div class="empty">no node to measure yet: enroll one on the Nodes tab</div>`;
  d.setFoot(`The agent walks each node's disks once an hour at the lowest priority. A project you cannot see is counted under other projects.`);
  wireStorageTab(d.el);
}

function wireStorageTab(root){
  const rl = root.querySelector("#stReload");
  if (rl) rl.onclick = () => { busy(rl, "Refreshing"); loadStorage(); };
  const psel = root.querySelector("#stNodeSel");
  if (psel) psel.onchange = () => { storageNode = psel.value;
                                    try{ localStorage.setItem("bb.stnode", storageNode); }catch(e){ /* private */ }
                                    storageRev++; drawPanes(); };
  root.querySelectorAll("[data-stmeasure]").forEach(b => b.onclick = async () => {
    busy(b, "Asking");
    const j = await (await postJSON("/api/storage", {action: "measure", node: b.dataset.stmeasure})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify("measuring: the numbers arrive with the node's next report, in a minute or so");
    await loadStorage();
  });
}
