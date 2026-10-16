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

// MB as a person reads it: TB above ten million, GB from one (a decimal
// under a hundred), MB below, "?" for unmeasured. One unit per view where
// it can be: the meters said GB while the rows under them said 7737 MB.
const sgb = mb => mb === null || mb === undefined ? "?"
  : mb >= 10485760 ? (mb / 1048576).toFixed(1) + " TB"
  : mb >= 1024 ? (mb / 1024).toFixed(mb >= 102400 ? 0 : 1) + " GB" : Math.round(mb) + " MB";

// Everything BuilderBot holds on the node, one item each: the stores, the
// synced copies (their size is the projects' workspace column, summed),
// the accounts' homes and Docker's data root. Each names the filesystem it
// sits on, which is what groups it under a meter below.
function storageHeld(n){
  const items = Object.entries(n.stores || {}).map(([role, st]) => ({
    name: `${role} store`, path: st.path, fs: st.fs || "", slow: !!st.slow, mb: st.slow ? null : (st.used_mb || 0)}));
  if (n.workspace?.path){
    const ws = [...(n.projects || []), n.other || {}].reduce((a, p) => a + (p.workspace || 0), 0);
    items.push({name: "synced copies", path: n.workspace.path, fs: n.workspace.fs || "", mb: ws, note: "per project below"});
  }
  if (n.homes?.path) items.push({name: "the accounts' homes", path: n.homes.path, fs: n.homes.fs || "", mb: n.homes.mb || 0,
                                 note: "their build caches per project below"});
  const dk = n.docker || {};
  if (dk.kinds?.length){
    const total = dk.kinds.reduce((a, k) => a + (k.mb || 0), 0);
    const recl = dk.kinds.reduce((a, k) => a + (k.reclaimable_mb || 0), 0);
    // The one number in Docker's share a person acts on is what a prune
    // would free; the kind-by-kind list (images 3095 MB (7), ...) is the
    // Docker tab's to tell.
    items.push({name: "Docker", path: dk.root || "its data root", fs: dk.fs || "", mb: total,
                note: recl ? `${sgb(recl)} of it reclaimable: prune on the Docker tab` : ""});
  }
  return items;
}

function storageRow(h){
  return `<div class="row"><div class="grow"><div class="name">${esc(h.name)} <span class="dim">· ${esc(h.path)}</span></div>
      <div class="sub">${h.mb === null ? "not measured in time" : sgb(h.mb)}${h.note ? `; ${esc(h.note)}` : ""}</div></div></div>`;
}

// A list of names as a sentence: "cache, artifacts and appdata".
function andList(xs){
  return xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

// One picture per filesystem (R203): its meter, then what BuilderBot holds
// on it, largest first, with the stores holding nothing folded into one
// line. A flat list of nine stores under a separate meter stack said 37.8
// TB used above rows adding up to 10 GB, and left the reader to join them.
function storageDisks(n){
  const fss = n.filesystems || [];
  const held = storageHeld(n);
  if (!fss.length) return `<div class="empty">no filesystem measured yet</div>`;
  const block = (fs, mine) => {
    const some = mine.filter(h => h.mb === null || h.mb > 0).sort((a, b) => (b.mb || 0) - (a.mb || 0));
    const none = mine.filter(h => h.mb === 0);
    const ours = some.reduce((a, h) => a + (h.mb || 0), 0);
    const pct = fs.total_mb ? (fs.used_mb || 0) / fs.total_mb * 100 : 0;
    const also = fs.also?.length ? `, also at ${fs.also.join(", ")}` : "";
    return `<div class="field stdisk"><div class="ndmeters">${
        meter(fs.path, pct, `${sgb(fs.used_mb)} / ${sgb(fs.total_mb)}`,
              `${fs.source} (${fs.type}${fs.ro ? ", read-only" : ""})${also}`)}</div>${
        mine.length ? `<div class="sub">${ours ? `${sgb(ours)} of it is BuilderBot's` : "nothing of it is BuilderBot's yet"}</div>` : ""}</div>${
      some.map(storageRow).join("")}${
      none.length ? `<div class="row stnone"><div class="grow"><div class="sub">${esc(andList(none.map(h => h.name)))} hold${none.length === 1 ? "s" : ""} nothing yet</div></div></div>` : ""}`;
  };
  const out = fss.map(fs => block(fs, held.filter(h => h.fs === fs.path)));
  const off = held.filter(h => !fss.some(fs => fs.path === h.fs));
  if (off.length) out.push(`<div class="field"><div class="sub">on a filesystem the walk did not measure</div></div>${off.map(storageRow).join("")}`);
  return out.join("");
}

function storageProjects(n, where){
  const rows = [...(n.projects || [])];
  if (n.other) rows.push({name: "other projects", other: true, ...n.other});
  if (!rows.length) return `<div class="empty">no project's folders here yet</div>`;
  // The ones holding nothing here are one line, not a row of "none" each
  // (R203): four of five read none / 0 MB on a node that held one project.
  const empty = rows.filter(r => !r.other && !r.total);
  const shown = rows.filter(r => r.other || r.total);
  const cols = where.filter(w => shown.some(r => r[w]));
  // Each cell says which column it is (data-k): a desk shows the head row
  // and hides the words, a phone stacks the cells and shows each one's word
  // beside its number, since a column of bare numbers under a name said
  // nothing (the operator's screenshot, B655). An empty cell says so.
  const head = `<div class="row stack2 stproj sthead"><div class="grow"><div class="dim">project</div></div>${
    cols.map(w => `<div class="dim stcol">${esc(w)}</div>`).join("")}<div class="dim stcol">total</div></div>`;
  const tail = empty.length ? `<div class="row stnone"><div class="grow"><div class="sub">${esc(andList(empty.map(r => projLabel(r.name))))} hold${empty.length === 1 ? "s" : ""} nothing here</div></div></div>` : "";
  if (!shown.length) return tail;
  return head + shown.map(r => `<div class="row stack2 stproj${r.other ? " dim" : ""}">
      <div class="grow"><div class="name">${r.other ? "other projects <span class=\"dim\">· ones you cannot see</span>" : esc(projLabel(r.name))}</div></div>
      ${cols.map(w => `<div class="stcol" data-k="${esc(w)}">${r[w] ? sgb(r[w]) : `<span class="dim">none</span>`}</div>`).join("")}
      <div class="stcol" data-k="total"><b>${sgb(r.total)}</b></div>
    </div>`).join("") + tail;
}

// What the tab says about one node: the state row, then its disks.
function storageBody(n, where){
  const age = !n.measured ? "not measured yet"
    : n.age_s < 3600 ? `measured ${Math.round(n.age_s / 60)} min ago` : `measured ${Math.round(n.age_s / 3600)} h ago`;
  const pill = `<span class="pill${n.measured ? "" : " warn"}">${esc(age)}</span>`;
  return `<div data-stnode="${esc(n.node)}">
    <div class="row toolstate">
      <div class="grow"><div class="name">Storage on ${esc(n.name)} ${pill}</div>
        <div class="sub">${n.measured ? `${n.took_s ? `the walk took ${n.took_s}s; ` : ""}walked again every hour` : "the agent walks its disks an hour after it starts, then every hour"}; where its stores live is set on its row on the Nodes tab</div></div>
    </div>
    <div class="field">${lbl("", "Filesystems")}<div class="hint">Each disk, and what BuilderBot holds on it, largest first.</div></div>
    ${storageDisks(n)}
    <div class="field">${lbl("", "By project")}
      <div class="hint">What each project's folders hold on ${esc(n.name)}: its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.</div></div>
    ${storageProjects(n, where)}
    ${n.slow?.length ? `<div class="field"><div class="hint warn">Not measured in time: ${esc(n.slow.join(", "))}. A slow share; the next walk tries again.</div></div>` : ""}
  </div>`;
}

function renderStorageInto(i){
  const d = docSurface(i, "storage");
  if (!d) return;
  if (storageList === null){
    // Its template (R218 step 16): the bar, the state row's words and the
    // two headings with their hints are the page's own; the node and what
    // its disks hold are on their way.
    d.setBar(skNodeBar(storageMay ? ["Measure now", "Refresh"] : ["Refresh"]));
    d.list.innerHTML = skTpl(`<div class="row toolstate"><div class="grow"><div class="name">Storage on ${skv(6)}</div>
        <div class="sub">${skv(28)}</div></div></div>
      <div class="field">${lbl("", "Filesystems")}<div class="hint">Each disk, and what BuilderBot holds on it, largest first.</div></div>
      ${skRows(2)}
      <div class="field">${lbl("", "By project")}<div class="hint">What each project's folders hold: its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.</div></div>
      ${skRows(3)}`);
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
  // The tab's two actions side by side at the right of the bar (R203):
  // Measure now asks the node for a fresh walk, Refresh re-reads the record.
  d.setBar(`${nodePick("stNodeSel", pnodes, storageNode)}
    <span class="sp"></span><span class="actbar">${storageMay && n ? `<button type="button" data-stmeasure="${esc(n.node)}" ${n.live ? "" : "disabled"} title="${
      n.live ? "walk the disks now; the next report brings the numbers" : "the node is not dialing in"}">Measure now</button>` : ""}
    <button type="button" id="stReload" title="read the nodes again">Refresh</button></span>`);
  d.list.innerHTML = n ? storageBody(n, where)
    : `<div class="empty">no node to measure yet: enroll one on the ${pageLink("nodes", "Nodes page")}</div>`;
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
