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
let storageDisk = "";            // the disk its chips picked, "" for all (R122)

function openStorageTab(node){
  if (node) storageNode = node;
  openTab({kind: "storage", arg: "__storage", label: "Storage"});
}

async function loadStorage(){
  try{
    const j = await (await bootFetch("/api/storage")).json();
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
                note: recl ? `${sgb(recl)} of it reclaimable` : "", prune: recl ? n.node : ""});
  }
  return items;
}

function storageRow(h){
  return `<div class="row"><div class="grow"><div class="name">${esc(h.name)} <span class="dim">· ${esc(h.path)}</span></div>
      <div class="sub">${h.mb === null ? "not measured in time" : sgb(h.mb)}${h.note ? `; ${esc(h.note)}` : ""}${
        // ...and the way to it: the Containers page on this node with its
        // Images and volumes open, where the prunes are.
        h.prune ? `: <a href="#" data-stprune="${esc(h.prune)}">prune on the Containers page</a>` : ""}</div></div></div>`;
}

// What BuilderBot could free on a filesystem (R123 step 4): its projects'
// phones, its build caches and Docker's reclaimable, where they sit on it.
function storageFreeable(n, fs){
  const on = path => fs.path === path || (path || "").startsWith(fs.path === "/" ? "/" : fs.path + "/");
  const phones = (n.phones || []).filter(p => !p.running).reduce((a, p) => a + (p.mb || 0), 0);
  const builds = (n.projects || []).reduce((a, r) => a + (r.builds || 0), 0);
  const cache = n.stores?.cache && n.stores.cache.fs === fs.path
    ? (n.projects || []).reduce((a, r) => a + (r.cache || 0), 0) : 0;
  const dk = n.docker || {};
  const docker = dk.fs === fs.path ? (dk.kinds || []).reduce((a, k) => a + (k.reclaimable_mb || 0), 0) : 0;
  const home = n.homes?.fs === fs.path || on(n.homes?.path || "");
  // Each named with the page that frees it: this page only measures (the
  // operator, 23 Oct).
  const parts = [[home ? phones : 0, "phones not running (the Emulator page)"],
                 [(home ? builds : 0) + cache, "build caches (Clear cache on the node's row on the Nodes page)"],
                 [docker, "Docker's reclaimable (the Containers page)"]].filter(([mb]) => mb > 0);
  return parts.length ? `${sgb(parts.reduce((a, [mb]) => a + mb, 0))} of it can be freed: ${
    andList(parts.map(([mb, what]) => `${what.replace(/ \(/, ` ${sgb(mb)} (`)}`))}` : "";
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
    // Each filesystem a card of its own (R218 step 47, the operator 18 Oct):
    // its mount the heading, used of its size the status, then its meter,
    // what of it is BuilderBot's and the rows of what that is.
    return docSection("storage", `fs:${fs.path}`, fs.path, `${sgb(fs.used_mb)} of ${sgb(fs.total_mb)}`,
      `<div class="field stdisk"><div class="ndmeters">${
        // "used": the card's heading already names the filesystem.
        meter("used", pct, `${sgb(fs.used_mb)} / ${sgb(fs.total_mb)}`,
              `${fs.source} (${fs.type}${fs.ro ? ", read-only" : ""})${also}`)}</div>${
        mine.length ? `<div class="sub">${ours ? `${sgb(ours)} of it is BuilderBot's` : "nothing of it is BuilderBot's yet"}</div>` : ""}${
        pct >= 90 && storageFreeable(n, fs) ? `<div class="sub warn">${esc(storageFreeable(n, fs))}.</div>` : ""}</div>${
      some.map(storageRow).join("")}${
      none.length ? `<div class="row stnone"><div class="grow"><div class="sub">${esc(andList(none.map(h => h.name)))} hold${none.length === 1 ? "s" : ""} nothing yet</div></div></div>` : ""}`,
      {cls: pct >= 92 ? "bad" : pct >= 80 ? "warn" : "", item: true});
  };
  // The disks are the node's, as many as it has: big chips pick one (R122),
  // where small pills listed them as if they were the page's sections.
  const off = held.filter(h => !fss.some(fs => fs.path === h.fs));
  const keys = [...fss.map(fs => fs.path), ...(off.length ? ["elsewhere"] : [])];
  if (storageDisk && !keys.includes(storageDisk)) storageDisk = "";
  const chips = chipBar([...fss.map(fs => ({key: fs.path, label: fs.path, count: null})),
                         ...(off.length ? [{key: "elsewhere", label: "Elsewhere", count: null}] : [])],
                        storageDisk, "data-stdisk");
  const out = fss.filter(fs => !storageDisk || storageDisk === fs.path).map(fs => block(fs, held.filter(h => h.fs === fs.path)));
  if (off.length && (!storageDisk || storageDisk === "elsewhere"))
    out.push(docSection("storage", "fs:elsewhere", "Elsewhere", "not measured", off.map(storageRow).join(""), {item: true}));
  return chips + out.join("");
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
  // A table (R218 step 27, the tables rule): a head naming the columns at a
  // desk, and on a phone each cell its column's word beside its number,
  // since a column of bare numbers under a name said nothing (B655). An
  // empty cell says so.
  const tcols = [{label: "Project"}, ...cols.map(w => ({label: w, num: true})), {label: "total", num: true}];
  const tail = empty.length ? `<div class="field stnone"><div class="sub">${esc(andList(empty.map(r => projLabel(r.name))))} hold${empty.length === 1 ? "s" : ""} nothing here</div></div>` : "";
  if (!shown.length) return tail;
  return tblWrap(tcols, shown.map(r => `<div class="row stack2 stproj${r.other ? " dim" : ""}">${tblLine(tcols, [
      `<span class="name">${r.other ? "other projects <span class=\"dim\">· ones you cannot see</span>" : esc(projLabel(r.name))}</span>`,
      ...cols.map(w => r[w] ? sgb(r[w]) : `<span class="dim">none</span>`), `<b>${sgb(r.total)}</b>`])}</div>`).join(""), "sttbl") + tail;
}

// Each project's virtual phones on the node (R123 step 1), largest first,
// whoever's they are among the projects this account sees: measured here,
// removed on the Emulator page, the page that manages them (the operator,
// 23 Oct).
function storagePhones(n){
  const rows = [...(n.phones || [])].sort((a, b) => (b.mb || 0) - (a.mb || 0));
  const cols = [{label: "Phone"}, {label: "Project"}, {label: "Account"}, {label: "last started"},
                {label: "snapshot", num: true}, {label: "size", num: true}];
  return `<div class="field"><div class="hint">Each is removed on the ${pageLink("emulator", "Emulator page")}, with this node picked.</div></div>`
    + tblWrap(cols, rows.map(p => `<div class="row stack2 stphone">${tblLine(cols, [
      `<span class="name">${esc(p.name)}</span>${p.running ? ` <span class="pill ok">running</span>` : ""}`,
      esc(projLabel(p.project)), `<span class="dim">${esc(p.uid === state?.uid ? "yours" : p.uid || "the session account")}</span>`,
      p.running ? "now" : p.ran ? esc(ago(p.ran)) : `<span class="dim">never</span>`,
      p.snap_mb ? sgb(p.snap_mb) : `<span class="dim">none</span>`,
      p.mb === null || p.mb === undefined ? `<span class="dim">?</span>` : sgb(p.mb)])}</div>`).join(""), "sttbl");
}

// Measure now, the page's upkeep, in its bar with every header button (the
// operator, 17 Oct): the walk's numbers arrive with the node's census, which
// the page follows, so it has no Refresh.
// Given GHOST, the placeholder's: there and dead until the node is known.
function storageMeasureBtn(n){
  if (n === GHOST) return storageMay ? `<button type="button" disabled>Measure now</button>` : "";
  if (!n || !storageMay || n.may_measure === false) return "";
  return `<button type="button" data-stmeasure="${esc(n.node)}" ${n.live ? "" : "disabled"} title="${
    n.live ? "walk the disks now; the next report brings the numbers" : "the node is not dialing in"}">Measure now</button>`;
}
// The bar: the node and Measure now; given nothing, the placeholder's.
function storageBar(pnodes, n){
  return nodeBar(nodePick("stNodeSel", pnodes, storageNode), storageMeasureBtn(pnodes ? n : GHOST));
}

// What the tab says about one node: the state row, then its disks. Given
// null, the placeholder (R218, the operator 18 Oct: drawn by the page's own
// code so it cannot drift): the same bands and By project, shimmering where
// the node's numbers go.
function storageBody(n, where){
  const hint = `<div class="field"><div class="hint">Each disk and what BuilderBot holds on it, largest first; where its stores live is set on its row on the ${pageLink("nodes", "Nodes page")}.</div></div>`;
  const byProject = (count, body) => docSection("storage", "projects", "By project", count,
    `<div class="field"><div class="hint">What each project's folders hold${n ? ` on ${esc(n.name)}` : ""}.${helpIcon("Its synced copy, build cache, artifacts, dev instance data, emulators and the accounts' build caches.")}</div></div>
      ${body}`);
  if (!n) return `${headLine(skv(28), "", "toolstate")}${hint}${skRows(2)}${byProject("", skRows(3))}`;
  const age = !n.measured ? "not measured yet"
    : n.age_s < 3600 ? `measured ${Math.round(n.age_s / 60)} min ago` : `measured ${Math.round(n.age_s / 3600)} h ago`;
  const pill = `<span class="pill${n.measured ? "" : " warn"}">${esc(age)}</span>`;
  // The walk as facts beside its pill (R218 step 27), and the one hint.
  // ...and the memory BuilderBot's work is kept to there (R110 step 4).
  const fence = !("fence" in n) ? "" : n.fence ? `its work kept to ${humanBytes(n.fence[0] * 1048576)} of memory, ${humanBytes(n.fence[1] * 1048576)} in use`
    : "its work is not fenced from the system's memory: run its setup again";
  const facts = [...(n.measured ? [n.took_s ? `the walk took ${n.took_s}s` : "", "walked every hour"]
    : ["walked an hour after the agent starts, then every hour"]), fence].filter(Boolean).join(" · ");
  return `<div data-stnode="${esc(n.node)}">
    ${headLine(`${pill} <span class="sub">${esc(facts)}</span>`, "", "toolstate")}
    ${hint}
    ${storageDisks(n)}
    ${byProject(`${(n.projects || []).length} project${(n.projects || []).length === 1 ? "" : "s"}`, storageProjects(n, where))}
    ${(n.phones || []).length ? docSection("storage", "phones", "Phones", `${n.phones.length}, ${sgb(n.phones.reduce((a, p) => a + (p.mb || 0), 0))}`, storagePhones(n)) : ""}
    ${n.slow?.length ? `<div class="field"><div class="hint warn">Not measured in time: ${esc(n.slow.join(", "))}. A slow share; the next walk tries again.</div></div>` : ""}
  </div>`;
}

function renderStorageInto(i){
  const d = docSurface(i, "storage");
  if (!d) return;
  if (storageList === null){
    // The page's own bar and body, given nothing.
    d.setBar(storageBar(null));
    d.list.innerHTML = skTpl(storageBody(null));
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
  // One order for every page's top (the operator, 17 Oct): the node and
  // Measure now in the bar; when it was measured on the status line under it.
  d.setBar(storageBar(pnodes, n));
  d.list.innerHTML = n ? storageBody(n, where)
    : noNodeYet("the disks measured here are a node's");
  wireStorageTab(d.el);
}

function wireStorageTab(root){
  // Its sections fold as every page's do: one open at a time on a phone,
  // sliding, where they snapped and stood open together (B171).
  wireSections(root);
  const psel = root.querySelector("#stNodeSel");
  // A pick is a history entry (B31), so Back returns to the node before.
  if (psel) psel.onchange = () => navPush(() => { storageNode = psel.value;
                                    try{ localStorage.setItem("bb.stnode", storageNode); }catch(e){ /* private */ }
                                    storageRev++; drawPanes(); });
  root.querySelectorAll("[data-stdisk]").forEach(c => c.onclick = () => {
    storageDisk = c.dataset.stdisk; storageRev++; drawPanes();
  });
  root.querySelectorAll("[data-stprune]").forEach(a => a.onclick = e => {
    e.preventDefault();
    sectOpen["docker:images"] = true;
    openDockerOn(a.dataset.stprune);
  });
  root.querySelectorAll("[data-stmeasure]").forEach(b => b.onclick = async () => {
    busy(b, "Asking");
    const j = await (await postJSON("/api/storage", {action: "measure", node: b.dataset.stmeasure})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify("measuring: the numbers arrive with the node's next report, in a minute or so");
    await loadStorage();
  });
}
