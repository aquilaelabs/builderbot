// The Library (R170, the operator, 28 Oct: one place for everything a
// BuilderBot installs or runs, not a page each for toolchains, agents and
// apps): one list, read whole from /api/library for one node, of the
// toolchains the catalog offers and what the node's store holds, the coding
// agents with their versions, the tool packs a person added, the apps a NAS
// runs as containers, the vetted catalog's offers and the companions a
// person downloads; each a row of one shape (its kind, its tier, what it is,
// where it stands on the node) with one verb, and opening on its whole
// description. The node picker in the bar, a search box and chips by kind
// and tier under the head; the rows under a section per kind.
//
// Nothing here installs a second way: a toolchain's Install is the
// Toolchains job (tcAct), an agent's the /api/agents verb, a pack's the Add
// tool pack dialog (tpOpen, tpOpenCatalog) and an app's the New container
// dialog with the app picked, so what each did yesterday it does today.
// Chrome from docSurface(); the hard rules are uniform.mjs's. Loaded before
// the page's own script, so everything here is a declaration.

"use strict";

let lib = null, libNode = "", libRev = 0, libSeq = 0, libLanded = 0, libFollow = null;
let libQ = "", libKind = "", libTier = "";
const libOpen = new Set();     // the rows opened on their descriptions (rows-you-open)
// The sections, in the page's order: what a session runs first, then what
// it builds with, then what a person adds, then what the box hosts, then
// what the person takes to their own machines.
const LIB_KINDS = [["agent", "Coding agents"], ["toolchain", "Toolchains"], ["pack", "Tool packs"], ["app", "Apps"], ["companion", "For you"]];
const LIB_TIERS = [["official", "Official"], ["vetted", "Vetted"], ["sideloaded", "Sideloaded"]];

function openLibrary(){
  openTab({kind: "library", arg: "__library", label: "Library"});
}
// ...on a node somebody named (the bell's rows, a node's page): read for
// first when the page has not listed it yet (B754's lesson).
function openLibraryOn(id){
  if (id && id !== libNode){ libNode = id; lib = null; }
  if (!(nodesList || []).some(n => n.id === id)) nodesStale = true;
  try{ localStorage.setItem("bb.libnode", id); }catch(e){ /* private */ }
  const was = location.hash;
  openLibrary();
  libRev++;
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was) shellPush(to);
  loadLibrary();
}

// The node the page opens on: the one it showed last, else the first agent
// node, as the Toolchains page picked. The toolchain and pack verbs act on
// tcNode, so the pick is theirs too.
function libPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  let want = libNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.libnode") || localStorage.getItem("bb.tcnode") || ""; }catch(e){ want = ""; }
  }
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  libNode = want;
  if (want && want !== tcNode){ tcNode = want; toolchains = null; tcTicked.clear(); }
  return live.find(n => n.id === want) || null;
}

async function loadLibrary(){
  const asked = ++libSeq;
  if (nodesList === null || nodesStale) await loadNodes();
  if (asked !== libSeq) return;
  if (!libPick()){
    lib = {nonode: true};
    libRev++; drawPanes();
    return;
  }
  // A reply is kept when it is still about the node on show and nothing
  // asked after it has landed first (B154: dropping every overtaken reply
  // was a livelock on a loaded box).
  const node = libNode;
  const keep = () => libNode === node && asked > libLanded;
  try{
    const r = await fetch("/api/library?node=" + encodeURIComponent(node));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (!keep()) return;
    lib = got;
  }catch(e){ if (!keep()) return; lib = {error: failWords(e)}; }
  libLanded = asked;
  // One follow-up while a job writes a row, not a poll: the toolchains
  // revision moves when the job ends, and the row's "installing" until then.
  clearTimeout(libFollow); libFollow = null;
  if ((lib.rows || []).some(r => r.running)) libFollow = setTimeout(loadLibrary, 3000);
  libRev++;
  drawPanes();
}

// What the search box matches: the name, what it is, its kind and its tier.
function libMatch(r, q){
  if (!q) return true;
  const hay = `${r.label} ${r.name} ${r.about} ${r.kind} ${r.tier} ${(r.platforms || []).join(" ")}`.toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(w => hay.includes(w));
}

// The pills a row wears: its tier (the three read on every row), what is
// installed, and what an update would move it to, which alone is news.
function libPills(r){
  const tier = `<span class="pill${r.tier === "vetted" ? " ok" : ""}">${esc(r.tier)}</span>`;
  const ver = r.version && r.version !== "-" && r.version !== "present" ? ` <span class="pill" title="installed">${esc(r.version)}</span>` : "";
  const upd = r.update && r.latest ? ` <span class="pill warn" title="update available">${esc(r.latest)} is out</span>` : "";
  const dev = r.dev ? devMark() : "";
  return `${tier}${ver}${upd}${dev}`;
}

// Where the row stands on the node, in a few words at its right.
function libState(r){
  if (r.running) return `<span class="sub prog plain">${esc(r.doing === "remove" ? "removing" : r.doing === "check" ? "checking" : r.kind === "agent" && r.installed ? "updating" : "installing")}<span class="dots"></span></span>`;
  if (r.kind === "app") return `<span class="sub">runs as a container</span>`;
  if (r.kind === "companion") return r.download ? `<span class="sub">${esc(r.version ? "held, " + r.version : "held")}</span>` : `<span class="sub warn">${esc(r.absent ? "not in " + r.absent : "not fetched yet")}</span>`;
  if (r.wrong_platform) return `<span class="sub">${esc(r.wrong_platform)}</span>`;
  if (r.installed) return `<span class="sub ok">${r.update ? "update available" : "installed"}</span>`;
  if (r.unknown) return `<span class="sub">present, version unknown</span>`;
  return `<span class="sub">not installed</span>`;
}

// The one verb a row takes, and Remove where it is installed (the
// Toolchains page's Remove and the Agents page's, moved here).
function libActs(r, may){
  const n = libNode, a = (act, words, cls = "") =>
    `<button type="button"${cls ? ` class="${cls}"` : ""} data-libact="${act}" data-libkind="${esc(r.kind)}" data-libname="${esc(r.name)}">${esc(words)}</button>`;
  if (r.running) return "";
  if (r.kind === "companion") return r.download
    ? `<a class="btn primary" href="${esc(r.download.url)}" download title="${esc(r.download.file)} · sha256 ${esc((r.download.sha256 || "").slice(0, 12))}…">Download</a>`
    : `<button type="button" class="primary" disabled>Download</button>`;
  if (r.kind === "app") return may.apps ? a("install", "Install", "primary") : "";
  if (!may.install || !n) return "";
  if (r.kind === "pack" && !r.installed && r.catalog) return a("add", "Install");
  const verb = r.update ? a("install", "Update", "primary") : r.installed ? "" : a("install", "Install", r.kind === "agent" && r.agent === "claude" ? "primary" : "");
  const edit = r.kind === "pack" && r.pack ? a("edit", "Edit") : "";
  const rm = r.installed && r.kind !== "pack" ? a("remove", "Remove", "danger") : r.kind === "pack" && r.pack ? a("remove", "Remove", "danger") : "";
  return `${verb}${edit}${rm}`;
}

// The whole description, on the open row (rows-you-open): what it fetches
// and runs, its terms, its platforms, the verbs it gives a session, an
// agent's sign-in on this node, a pack's source, a companion's other files.
function libDetail(r){
  const n = (nodesList || []).find(x => x.id === libNode);
  const lines = [];
  if (r.platforms?.length) lines.push(`<span class="sub">Platforms: ${esc(r.platforms.join(", "))}</span>`);
  if (r.kind === "toolchain" || r.kind === "pack"){
    lines.push(tcTermsLine(r));
    if (r.size) lines.push(`<span class="sub">About ${esc(r.size)} on the store.</span>`);
    if (r.pack) lines.push(`<span class="sub">${r.pack.here ? "Made here" : `From <code>${esc(r.pack.url)}</code> at ${esc((r.pack.commit || "").slice(0, 12))}`}${r.pack.by ? `, added by ${esc(r.pack.by)}` : ""}. A session has <code>bb tool ${esc(r.name)}</code>.</span>`);
    if (r.catalog) lines.push(`<span class="sub">From <code>${esc(r.catalog.url)}</code> at ${esc((r.catalog.commit || "").slice(0, 12))}, its archive's sha256 checked on the way in. Install opens the Add tool pack dialog on that commit: Look shows what it fetches and runs, and Add keeps exactly that.</span>`);
    if (r.wrong_platform) lines.push(`<span class="sub warn">${esc(r.wrong_platform)}</span>`);
    if (r.pinned?.length) lines.push(`<span class="sub">Pinned by ${esc(r.pinned.map(projLabel).join(", "))}.</span>`);
  }
  if (r.kind === "agent"){
    lines.push(`<span class="sub">Installed for the node's session account; ${r.latest ? `the latest is ${esc(r.latest)}` : "its latest is not known yet"}.</span>`);
    if (r.error) lines.push(`<span class="sub bad">${esc(r.error)}</span>`);
    if (n && r.installed && typeof signinBlock === "function" && (agentById(r.agent) || {}).provider)
      lines.push(`<div class="field agpart"><div class="fsub">Your sign-in</div>${signinBlock(n, r.agent)}</div>`);
  }
  if (r.kind === "app"){
    lines.push(`<span class="sub">Install opens New container with ${esc(r.label)} picked: its folders, the user, the time zone and the port are filled in, and Create makes it a container on the Containers page${r.port ? `, on port ${esc(String(r.port))}` : ""}.</span>`);
    if (r.secrets?.length) lines.push(`<span class="sub">Made for it when it is created: ${esc(r.secrets.join(", "))}.</span>`);
  }
  if (r.kind === "companion"){
    lines.push(`<span class="sub">${typeof devHow === "function" ? devHow(r.name) : ""}</span>`);
    if ((r.files || []).length > 1) lines.push(`<span class="sub">Also: ${r.files.slice(1).map(f => `<a href="${esc(f.url)}" download>${esc(f.file)}</a>`).join(", ")}</span>`);
  }
  return lines.filter(Boolean).join("");
}

function libRow(r, may){
  const key = `${r.kind}:${r.name}`, open = libOpen.has(key);
  return `<div class="row lrow${open ? " open" : ""}" data-lrow="${esc(key)}">
    <div class="grow">
      <div class="name">${esc(r.label)} ${libPills(r)} <button type="button" class="link lmore" data-libmore="${esc(key)}" aria-expanded="${open}">${open ? "Less" : "Details"}</button></div>
      <div class="sub labout">${esc(r.about)}</div>
      <div class="ldetail">${open ? libDetail(r) : ""}</div>
      ${!r.running && (r.kind === "toolchain" || r.kind === "pack") && lib?.job?.errors?.[r.name] ? `<div class="sub bad">${esc(lib.job.errors[r.name])}</div>` : ""}
    </div>
    <div class="acts">${libState(r)}${libActs(r, may)}</div>
  </div>`;
}

// The band under the head: the search, then the kind chips and the tier
// chips side by side (the chips rule: one band where a list is narrowed
// more than one way).
function libFilterBand(rows){
  const count = (key, f) => rows.filter(f).length;
  const kinds = LIB_KINDS.map(([k, l]) => ({key: k, label: l, count: count(k, r => r.kind === k)}));
  const tiers = LIB_TIERS.map(([k, l]) => ({key: k, label: l, count: count(k, r => r.tier === k)}));
  return `<div class="field lfilter libfilter">
    <input id="libFind" type="search" maxlength="80" autocomplete="off" spellcheck="false" aria-label="search the library"
      placeholder="search by name or what it does" value="${esc(libQ)}">
    <div class="chips" data-chips="libkind">${chipButtons(kinds, libKind, "data-libkind")}</div>
    <div class="chips" data-chips="libtier">${chipButtons(tiers, libTier, "data-libtier")}</div>
  </div>`;
}

function libSections(rows, may){
  return LIB_KINDS.map(([k, title]) => {
    const all = (lib.rows || []).filter(r => r.kind === k);
    const here = rows.filter(r => r.kind === k);
    if (libKind && libKind !== k) return "";
    if (k === "companion" && featureOff("apps"))
      return docSection("library", k, title, "", `<div class="field">${deadWhy(featureOff("apps"))}</div>`);
    const inst = all.filter(r => r.installed).length;
    const status = !all.length ? "" : k === "app" || k === "companion" ? `${all.length}` : `${inst} of ${all.length} installed`;
    const body = here.length ? `<div class="rows">${here.map(r => libRow(r, may)).join("")}</div>`
      : `<div class="empty">${all.length ? "Nothing here matches." : k === "companion" ? "This controller offers no apps for your own machines: an administrator picks them on the Controller page, under Apps." : "Nothing here yet."}</div>`;
    // Picked by the kind chips, so no jump bar over them (sectJump's rule:
    // a page's chips pick its groups, the jump bar is for its sections).
    return docSection("library", k, title, status, body, {item: true});
  }).join("");
}

function renderLibraryInto(i){
  const d = docSurface(i, "library");
  if (!d) return;
  if (lib === null){
    d.setBar(skNodeBar([["Check for updates", "", "Check"], ["Add your own", "primary", "Add"]]));
    d.list.innerHTML = skTpl(pageHead({title: GHOST, facts: [["Installed", GHOST], ["Updates due", GHOST], ["Store", GHOST]]})
      + `<div class="field lfilter libfilter"><input type="search" disabled placeholder="search by name or what it does">${skel("chips")}</div>`
      + LIB_KINDS.map(([k, title]) => docSection("library", k, title, "", skRows(2), {item: true})).join(""));
    if (!libSeq) loadLibrary();
    return;
  }
  const pnodes = (nodesList || []).filter(x => x.kind === "agent" && x.state !== "retired").map(x => ({id: x.id, name: x.name, live: x.live}));
  if (lib.nonode){
    d.setBar("");
    d.list.innerHTML = noNodeYet("toolchains and coding agents install on a node", "libnone");
    return;
  }
  const may = lib.may || {};
  const job = lib.job || {}, busy = !!job.running;
  d.setBar(nodeBar(nodePick("libNodeSel", pnodes, libNode), may.install
    ? `<button type="button" data-libcheck${busy ? " disabled" : ""}>${barSaid("Check for updates", "Check")}</button>${
        may.packs ? `<button type="button" class="primary" data-libadd>${barSaid("Add your own", "Add")}</button>` : ""}` : ""));
  if (lib.error){
    paint(d.list, `<div class="field"><div class="notice bad">${esc("could not read the library: " + lib.error)}</div></div>`);
    return;
  }
  const rows = (lib.rows || []).filter(r => libMatch(r, libQ) && (!libKind || r.kind === libKind) && (!libTier || r.tier === libTier));
  const all = lib.rows || [];
  const inst = all.filter(r => r.installed).length, due = all.filter(r => r.update).length;
  const free = lib.store?.free_mb ? `${(lib.store.free_mb / 1024).toFixed(1)} GB free` : "";
  const head = pageHead({title: lib.name || "", facts: [
    ["Installed", `${inst} of ${all.filter(r => r.kind !== "app" && r.kind !== "companion").length}`],
    ["Updates due", due ? String(due) : ""],
    ["Store", lib.store?.root ? `${lib.store.root}${free ? ", " + free : ""}` : ""],
    ["Catalog", lib.catalog_error ? lib.catalog_error : ""],
  ]});
  paint(d.list, `<div data-libnode="${esc(libNode)}">${head}${libFilterBand(all)}${libSections(rows, may)}</div>`);
  wireLibrary(d.el);
}

function wireLibrary(root){
  wireSections(root);
  if (typeof wireSignin === "function") wireSignin(root);
  const psel = root.querySelector("#libNodeSel");
  if (psel) psel.onchange = () => navPush(() => {
    libNode = psel.value; lib = null;
    try{ localStorage.setItem("bb.libnode", libNode); }catch(e){ /* private */ }
    libRev++; drawPanes(); loadLibrary();
  });
  const q = root.querySelector("#libFind");
  if (q){
    q.oninput = () => { libQ = q.value; libRev++; drawPanes(); keepFocus(q); };
  }
  root.querySelectorAll("[data-libkind]").forEach(b => b.onclick = () => { libKind = b.dataset.libkind; libRev++; drawPanes(); });
  root.querySelectorAll("[data-libtier]").forEach(b => b.onclick = () => { libTier = b.dataset.libtier; libRev++; drawPanes(); });
  root.querySelectorAll("[data-libmore]").forEach(b => b.onclick = () => {
    const k = b.dataset.libmore;
    if (libOpen.has(k)) libOpen.delete(k); else libOpen.add(k);
    libRev++; drawPanes();
  });
  const chk = root.querySelector("[data-libcheck]");
  if (chk) chk.onclick = () => pressing(chk, async () => { busy(chk, "Checking"); await tcAct("check"); await loadLibrary(); });
  const add = root.querySelector("[data-libadd]");
  if (add) add.onclick = () => libWithToolchains(() => tpOpen(""));
  root.querySelectorAll("[data-libact]").forEach(b => b.onclick = () => libAct(b, b.dataset.libact, b.dataset.libkind, b.dataset.libname));
}

// The search keeps its caret through the redraw its own keystroke brings.
function keepFocus(q){
  const at = q.selectionStart;
  queueMicrotask(() => {
    const again = document.getElementById("libFind");
    if (again && document.activeElement !== again){ again.focus(); try{ again.setSelectionRange(at, at); }catch(e){ /* a type without a caret */ } }
  });
}

// The pack dialogs read the Toolchains page's rows (tpOpen's Edit finds the
// pack there), so they are read for this node first where they are not yet.
async function libWithToolchains(f){
  if (!toolchains || toolchains.nonode || toolchains.error || tcNode !== libNode) await loadToolchains();
  f();
}

async function libAct(b, act, kind, name){
  const r = (lib?.rows || []).find(x => x.kind === kind && x.name === name);
  if (!r) return;
  const n = (nodesList || []).find(x => x.id === libNode), where = n?.name || "this node";
  if (kind === "app"){ openNewContainerApp(name); return; }
  if (kind === "agent"){
    if (act === "remove" && !await askYes(`Remove ${r.label} from ${where}? Its sessions end, and none starts there until it is installed again.`)) return;
    if (act === "install" && r.installed && !await askYes(`Update ${r.label} on ${where}? Its sessions there end first; they start again from the project rows.`)) return;
    busy(b, act === "remove" ? "Removing" : "Asking");
    const j = await (await postJSON("/api/agents", {action: act, node: libNode, agent: r.agent || ""})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    await loadLibrary();
    return;
  }
  if (act === "add"){ libWithToolchains(() => tpOpenCatalog({...r.catalog, name: r.name, tier: r.tier, about: r.about, platforms: r.platforms})); return; }
  if (act === "edit"){ libWithToolchains(() => tpOpen(r.name)); return; }
  if (act === "remove"){
    if (!await askYes(`Uninstall ${r.label} from ${where}? The files are deleted; installing it again re-downloads them.`)) return;
    busy(b, "Removing");
    await tcAct("remove", [r.name]);
    await loadLibrary();
    return;
  }
  // Install or update a toolchain or an added pack: the Toolchains job,
  // with its agreements asked the way that page asks them.
  busy(b, r.installed ? "Updating" : "Installing");
  await tcAct("install", [r.name]);
  await loadLibrary();
}
