// The Storage tab (R169): what every node's disks hold, and whose. A
// section per node: its filesystems as a meter stack, its stores and
// Docker's share, then each project's folders on it (the synced copy, the
// build cache, artifacts, a dev instance's data, emulators, the accounts'
// build caches), largest first, with every project this account may not
// see folded into one line. The numbers are the agent's hourly walk, said
// with their age; Measure now asks for a fresh one, which the next hello
// brings.
//
// Chrome from docSurface(); the hard rules are uniform.mjs's. Data from
// /api/storage, read when the tab opens and after Measure now; redrawn on
// the nodes revision, since a hello carries a new walk.

"use strict";

let storageList = null;          // last answer, or null before the first
let storageErr = "";
let storageRev = 0;
let storageMay = false;          // whether this account may measure now

function openStorageTab(){
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

// MB as a person reads it: GB above ten, MB below, "?" for unmeasured.
const sgb = mb => mb === null || mb === undefined ? "?"
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
  const head = `<div class="row stack2 stproj sthead"><div class="grow"><div class="dim">project</div></div>${
    cols.map(w => `<div class="dim stcol">${esc(w)}</div>`).join("")}<div class="dim stcol">total</div></div>`;
  return head + rows.map(r => `<div class="row stack2 stproj${r.other ? " dim" : ""}">
      <div class="grow"><div class="name">${r.other ? "other projects <span class=\"dim\">· ones you cannot see</span>" : esc(projLabel(r.name))}</div></div>
      ${cols.map(w => `<div class="stcol">${r[w] ? sgb(r[w]) : ""}</div>`).join("")}
      <div class="stcol"><b>${sgb(r.total)}</b></div>
    </div>`).join("");
}

function storageSection(n, where){
  const status = !n.measured ? "not measured yet"
    : n.age_s < 3600 ? `measured ${Math.round(n.age_s / 60)} min ago` : `measured ${Math.round(n.age_s / 3600)} h ago`;
  const body = `
    <div class="field"><label>Filesystems</label>${storageFilesystems(n)}</div>
    <div class="field"><label>Stores</label></div>${storageStores(n)}
    <div class="field"><label>By project</label>
      <div class="hint">What each project's folders hold on ${esc(n.name)}: its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.</div></div>
    ${storageProjects(n, where)}
    ${n.slow?.length ? `<div class="field"><div class="hint warn">Not measured in time: ${esc(n.slow.join(", "))}. A slow share; the next walk tries again.</div></div>` : ""}
    <div class="field"><div class="actbar">
      <span class="state">${n.measured ? `${status}${n.took_s ? `, the walk took ${n.took_s}s` : ""}; walked again every hour` : "the agent walks its disks an hour after it starts, then every hour"}</span><span class="sp"></span>
      ${storageMay ? `<button type="button" data-stmeasure="${esc(n.node)}" ${n.live ? "" : "disabled"} title="${n.live ? "walk the disks now; the next report brings the numbers" : "the node is not dialing in"}">Measure now</button>` : ""}
    </div></div>`;
  return docSection("storage", n.node, n.name, status, body, {cls: n.measured ? "" : "warn"});
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
  d.setBar(`<span class="dim">${storageList.length} node${storageList.length === 1 ? "" : "s"}</span>
    <span class="sp"></span><button type="button" id="stReload" title="read the nodes again">Reload</button>`);
  d.list.innerHTML = storageList.length
    ? `<div class="sectjump" data-sects></div>` + storageList.map(n => storageSection(n, where)).join("")
    : `<div class="empty">no node to measure yet: enroll one on the Nodes tab</div>`;
  d.setFoot(`The agent walks each node's disks once an hour at the lowest priority. A project you cannot see is counted under other projects.`);
  wireStorageTab(d.el);
}

function wireStorageTab(root){
  const rl = root.querySelector("#stReload");
  if (rl) rl.onclick = () => { busy(rl, "Reading"); loadStorage(); };
  if (root.querySelector("[data-sects]")) sectJump(root.querySelector("[data-sects]"));
  wireSections(root);
  root.querySelectorAll("[data-stmeasure]").forEach(b => b.onclick = async () => {
    busy(b, "Asking");
    const j = await (await postJSON("/api/storage", {action: "measure", node: b.dataset.stmeasure})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify("measuring: the numbers arrive with the node's next report, in a minute or so");
    await loadStorage();
  });
}
