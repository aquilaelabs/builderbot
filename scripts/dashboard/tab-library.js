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
const libSeen = {};            // what a pack's Look brought back, by row key ("looking" while it is asked)
let libWantAgent = "";         // the agent whose card a door asked to open, until the rows land
// The sections, in the page's order: what a session runs first, then what
// it builds with, then what a person adds, then what the box hosts, then
// what the person takes to their own machines.
const LIB_KINDS = [["agent", "Coding agents"], ["toolchain", "Toolchains"], ["pack", "Tool packs"], ["service", "Services"], ["app", "Apps"], ["companion", "For you"]];
const LIB_TIERS = [["official", "Official"], ["vetted", "Vetted"], ["sideloaded", "Sideloaded"]];

function openLibrary(){
  openTab({kind: "library", arg: "__library", label: "Library"});
}
// ...on a node somebody named (the bell's rows, a node's page): read for
// first when the page has not listed it yet (B754's lesson).
function openLibraryOn(id, agent = ""){
  if (id && id !== libNode){ libNode = id; lib = null; }
  // A door that names a coding agent (a project's Sign in on NODE, the
  // bell's row) opens that agent's card on its sign-in once the rows land.
  if (agent) libWantAgent = agent;
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
  if (want && want !== tcNode){ tcNode = want; toolchains = null; tcDriverPick = ""; }
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
  if (libWantAgent && !lib.error){
    const r = (lib.rows || []).find(x => x.kind === "agent" && x.agent === libWantAgent);
    if (r) libOpen.add(`agent:${r.name}`);
    libWantAgent = "";
  }
  // The lines the Toolchains and Agents pages draw read their own page's
  // state: the node's sandbox flag (Install them now on a system line) and
  // this person's plugins and MCP servers there (an agent's Yours).
  if (!lib.error){
    tcSandboxNow = !!lib.sandbox; agYours = lib.yours || {plugins: [], mcp: {}};
    // ...and tcAct refuses a second job by the Toolchains page's record of
    // the one running, which this read keeps current for it.
    if (toolchains && !toolchains.nonode && !toolchains.error) toolchains.job = lib.job; else toolchains = {name: lib.name, job: lib.job, items: []};
  }
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
  const w = (t, cls = "") => `<span class="state${cls ? " " + cls : ""}">${t}</span>`;
  if (r.running) return w(`${esc(r.doing === "remove" ? "removing" : r.doing === "check" ? "checking" : r.kind === "agent" && r.installed ? "updating" : "installing")}<span class="dots"></span>`);
  if (r.kind === "app") return w("");
  if (r.kind === "service") return r.installed ? w("deployed", "ok") : r.ready ? w(esc(r.ready), "warn") : w("");
  if (r.kind === "companion") return r.download ? w(esc(r.version ? `held, ${r.version}` : "held")) : w(esc(r.absent ? `not in ${r.absent}` : "not fetched yet"), "warn");
  if (r.wrong_platform) return w(esc(r.wrong_platform), "warn");
  if (r.machine){
    const m = r.machine, st = m.state;
    if (!m.managed) return w("installed by hand on this machine", "");
    // A newer version of what is here is the news, whatever runs the card now.
    if (m.here && m.newer && st !== "nocard" && st !== "leaving") return w("update available", "warn");
    if (r.name === "nvidia-driver") return st === "absent" ? w("") : st === "loaded" ? w("running the card", "ok")
      : w(st === "nocard" ? "installed, no card now" : st === "leaving" ? "removed, until a restart" : m.newer ? "update available" : "installed, takes the card at a restart", "warn");
    return st === "absent" ? w("") : st === "ready" ? w(m.driver_loaded ? "ready" : "installed, needs the driver running", m.driver_loaded ? "ok" : "warn")
      : w(st === "nocard" ? "installed, no card now" : "installed, Docker not configured", "warn");
  }
  if (r.installed) return w(r.update ? "update available" : "installed", r.update ? "warn" : "ok");
  if (r.unknown) return w("installed, version unknown");
  return w("");
}

// The one verb a row takes, and Remove where it is installed (the
// Toolchains page's Remove and the Agents page's, moved here).
// Why the store's verbs are held on every card, or "": a job running on
// the node (one at a time), a node not reporting, a store it cannot write.
// Set by the draw; the notice over the cards says the last two in full.
let libHold = "";
function libActs(r, may){
  const n = libNode, a = (act, words, cls = "", held = "") =>
    `<button type="button"${cls ? ` class="${cls}"` : ""} data-libact="${act}" data-libkind="${esc(r.kind)}" data-libname="${esc(r.name)}"${
      held ? ` disabled title="${esc(held)}"` : ""}>${esc(words)}</button>`;
  if (r.running) return "";
  if (r.kind === "companion") return r.download
    ? `<a class="btn primary" href="${esc(r.download.url)}" download title="${esc(r.download.file)} · sha256 ${esc((r.download.sha256 || "").slice(0, 12))}…">Download</a>`
    : `<button type="button" class="primary" disabled>Download</button>`;
  // An app is not installed on the node from here (the operator, 28 Oct):
  // its press sends it to the Containers page's New container with the app
  // picked, and each press makes another container under its own name.
  if (r.kind === "app") return `${may.apps ? a("install", "New container", "primary") : ""}${r.tier === "sideloaded" && may.packs ? a("edit", "Edit") : ""}`;
  // A service deploys as a written container does (Configure on the node, R174), once
  // something is behind it, set on the Installed page.
  if (r.kind === "service") return !may.configure || r.installed ? "" : `<button type="button" class="primary" data-libact="install" data-libkind="service" data-libname="${esc(r.name)}"${r.ready ? " disabled" : ""}${r.ready ? ` title="${esc(r.ready)}: set on the Installed page"` : ""}>Install</button>`;
  if (!may.install || !n) return "";
  if (r.kind === "pack" && !r.installed && r.catalog) return a("add", "Install", "", libHold);
  if (r.machine && !r.machine.managed) return "";
  // The container toolkit installed but unknown to Docker is put right by
  // installing it again, which its line on the Installed page says.
  const again = r.machine?.state === "unconfigured";
  const verb = r.update ? a("install", "Update", "primary", libHold) : again ? a("install", "Install again", "", libHold)
    : r.installed ? "" : a("install", "Install", r.kind === "agent" && r.agent === "claude" ? "primary" : "", libHold);
  const edit = r.kind === "pack" && r.pack ? a("edit", "Edit") : "";
  return `${verb}${edit}`;
}

// The whole description, on the open row (rows-you-open): what it fetches
// and runs, its terms, its platforms, the verbs it gives a session, an
// agent's sign-in on this node, a pack's source, a companion's other files.
// How a companion is connected once it is installed (the Apps page's words
// until R170): the controller's address is the one thing each asks for,
// written where it is typed.
function devHow(name){
  const at = `<code>${esc(location.origin)}</code>`;
  return {
    android: `Install it, open it and sign in at ${at} with your name and password.`,
    vscode: `In VS Code: Extensions, the ⋯ menu, Install from VSIX; then BuilderBot: Connect, at ${at}.`,
    companion: `Run it, sign in at ${at} with your name and password, and pick a project and a folder.`,
  }[name] || "";
}

function libDetail(r){
  // The entry's metadata alone (the operator, 28 Oct: the Library is the
  // catalog; what is installed is managed on the Installed page under
  // Machines): what it is in full, its platforms, terms, size and source, a
  // pack's Look, an app's compose with its blanks, a companion's files.
  const key = `${r.kind}:${r.name}`;
  const lines = [];
  if (r.platforms?.length) lines.push(`<span class="sub">Platforms: ${esc(r.platforms.join(", "))}</span>`);
  if (r.kind === "toolchain" || r.kind === "pack"){
    if (r.tool) lines.push(`<span class="sub">Adds <code>bb tool ${esc(r.tool)}</code> to a session.</span>`);
    if (r.needs?.length) lines.push(`<span class="sub">Needs ${esc(r.needs.join(", "))}, installed with it.</span>`);
    lines.push(tcTermsLine(r));
    if (r.size) lines.push(`<span class="sub">About ${esc(r.size)} on the store.</span>`);
    if (r.machine) lines.push(`<span class="sub">${r.name === TC_DRIVER ? "Built for the machine's kernel, installed as root, taking the card at the next restart." : "From NVIDIA's own package source, which installing adds and removing takes away."} Its state and Remove are on the Installed page.</span>`);
    if (r.pack) lines.push(`<span class="sub">${r.pack.here ? "Made here" : `From <code>${esc(r.pack.url)}</code>${r.pack.path ? ` (${esc(r.pack.path)})` : ""} at ${esc((r.pack.commit || "").slice(0, 12))}`}${r.pack.by ? `, added by ${esc(r.pack.by)}` : ""}. A session has <code>bb tool ${esc(r.name)}</code>.</span>`);
    if (r.catalog) lines.push(`<span class="sub">From <code>${esc(r.catalog.url)}</code>${r.catalog.path ? ` (${esc(r.catalog.path)})` : ""} at ${esc((r.catalog.commit || "").slice(0, 12))}, its archive's sha256 checked on the way in. Install opens the Add tool pack dialog on that commit, and Add keeps exactly that.</span>`);
    if (r.config?.length) lines.push(`<span class="sub">Asks for ${esc(r.config.map(f => f.label).join(", "))} on each node, set on the Installed page once it is there.</span>`);
    if (r.wrong_platform) lines.push(`<span class="sub warn">${esc(r.wrong_platform)}</span>`);
    if (r.pack && !r.pack.here || r.catalog){
      const seen = libSeen[key];
      lines.push(seen === "looking" ? `<span class="sub">Looking at the repository<span class="dots"></span></span>`
        : seen?.error ? `<span class="sub bad">${esc(seen.error)}</span>`
        : seen ? tpSeen(seen, null, false)
        : `<span class="sub"><button type="button" class="link" data-liblook="${esc(key)}">Look</button> at what it fetches and runs, before anything is installed.</span>`);
    }
  }
  if (r.kind === "service"){
    lines.push(`<span class="sub">Deployed on the node as a written container; configured, read and removed on the Installed page under Machines.</span>`);
    if (r.config?.length) lines.push(`<span class="sub">Asks for ${esc(r.config.map(f => f.label).join(", "))}.</span>`);
  }
  if (r.kind === "agent"){
    const a = agentById(r.agent);
    lines.push(`<span class="sub">${a?.product ? `${esc(a.product)}, installed` : "Installed"} once per node for its session account${a?.provider ? `; each person signs in with ${/^(?:[AEIOU]|x(?=[A-Z]))/.test(a.provider) ? "an" : "a"} ${esc(a.provider)} account on the Installed page` : ""}.${r.latest ? ` The latest is ${esc(r.latest)}.` : ""}</span>`);
  }
  if (r.kind === "app"){
    if (r.tier === "sideloaded") lines.push(`<span class="sub">Added${r.by ? ` by ${esc(r.by)}` : ""}${r.at ? ` ${ago(r.at)}` : ""}, kept as sideloaded: Edit changes it, and Remove in there takes it off the catalog.</span>`);
    lines.push(`<span class="sub">New container opens the Containers page's dialog with ${esc(r.label)} picked: its folders, the user, the time zone and the port are filled in, and Create makes it a container there${r.port ? `, on port ${esc(String(r.port))}` : ""}. Each press makes another, under its own name.</span>`);
    if (r.secrets?.length) lines.push(`<span class="sub">Made for it when it is created: ${esc(r.secrets.join(", "))}.</span>`);
    if (r.blanks?.length) lines.push(`<span class="sub">Its blanks, filled from what you type: ${r.blanks.map(b => `<code>${esc(b)}</code>`).join(", ")}.</span>`);
    if (r.compose) lines.push(`<pre class="libcompose mono">${esc(r.compose.trim())}</pre>`);
  }
  if (r.kind === "companion"){
    lines.push(`<span class="sub">${devHow(r.name)}</span>`);
    if ((r.files || []).length > 1) lines.push(`<span class="sub">Also: ${r.files.slice(1).map(f => `<a href="${esc(f.url)}" download>${esc(f.file)}</a>`).join(", ")}</span>`);
  }
  return lines.filter(Boolean).join("");
}

// The glyph a card wears for its kind: the rail's and the tabs' own where
// one exists, a box with a tag for a pack and a screen for a companion.
const LIB_ICONS = {
  agent: () => TOOL_ICONS.agents, toolchain: () => TOOL_ICONS.toolchains, app: () => TOOL_ICONS.docker,
  pack: () => `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 5.2 8 2.6l5.5 2.6v5.6L8 13.4l-5.5-2.6z"/><path d="M2.5 5.2 8 7.8l5.5-2.6"/><path d="M8 7.8v5.6"/><path d="M5.2 3.9l5.6 2.7"/></svg>`,
  companion: () => `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.2" y="3" width="11.6" height="7.6" rx="1.2"/><path d="M6 13.4h4M8 10.6v2.8"/></svg>`,
  // A service (R172): what a node runs for the others, as a box with a plug.
  service: () => `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.4" y="4.2" width="11.2" height="7.6" rx="1.2"/><path d="M5.2 8h5.6M5.2 4.2V2.6M10.8 4.2V2.6"/></svg>`,
};

// One card (the Projects page's shape, R170: a store browses as cards):
// its kind's glyph, its name with the tier and the versions as quiet pills,
// what it is in two lines, and at its foot where it stands, Details, and
// the verb. Open, it runs the grid's width with the whole description.
// A pack's Look on its row: the manifest fetched at the commit it is pinned
// to (an added pack at its own, a catalog offer at the catalog's, its archive
// checked against the catalog's sha256), drawn as the dialog draws it.
async function libLook(key){
  const r = (lib?.rows || []).find(x => `${x.kind}:${x.name}` === key);
  if (!r || libSeen[key] === "looking") return;
  libSeen[key] = "looking"; libRev++; drawPanes();
  const body = r.catalog ? {action: "preview", url: r.catalog.url, commit: r.catalog.commit, sha256: r.catalog.sha256, path: r.catalog.path || ""}
    : {action: "preview", url: r.pack.url, commit: r.pack.commit, path: r.pack.path || ""};
  const j = await (await postJSON("/api/toolpacks", body)).json().catch(() => ({error: "no answer"}));
  libSeen[key] = j;
  libRev++; drawPanes();
}

// The driver's version on its card (R102, the operator 6 Oct: the branch
// is picked before Install), as the Toolchains page's row had it: the
// recommended one first, the rest by version, dead once one is installed.
function libDriverPick(m){
  const opts = m.options || [];
  if (!opts.length || m.state === "nocard" || !m.managed) return "";
  const picked = m.here ? m.package : (opts.some(o => o.pkg === tcDriverPick) ? tcDriverPick : "");
  return `<label class="pick libdrvpick">Version <select id="libDrvSel" aria-label="driver version"${m.here || !lib?.may?.install ? " disabled" : ""}${
      m.here ? ` title="installed: remove it first to install another version"` : ""}>
      ${m.here ? "" : `<option value=""${picked ? "" : " selected"}>${esc(m.recommended
          ? tcDriverOption(opts.find(o => o.pkg === m.recommended) || {pkg: m.recommended, version: "recommended"}, m)
          : "the one recommended for this card")}</option>`}
      ${opts.filter(o => m.here || o.pkg !== m.recommended).map(o => `<option value="${esc(o.pkg)}"${o.pkg === picked ? " selected" : ""}>${esc(tcDriverOption(o, m))}</option>`).join("")}
    </select></label>`;
}

function libRow(r, may){
  const key = `${r.kind}:${r.name}`, open = libOpen.has(key);
  const err = !r.running && (r.kind === "toolchain" || r.kind === "pack") && lib?.job?.errors?.[r.name] ? `<div class="sub bad">${esc(lib.job.errors[r.name])}</div>` : "";
  return `<div class="lcard${open ? " open" : ""}${r.running ? " busy" : ""}" data-lrow="${esc(key)}">
    <div class="lchead"><span class="lcicon">${(LIB_ICONS[r.kind] || LIB_ICONS.toolchain)()}</span>
      <div class="lctitle"><div class="name">${esc(r.label)} <button type="button" class="link lmore" data-libmore="${esc(key)}" aria-expanded="${open}">${open ? "Less" : "Details"}</button></div><div class="lcmeta">${libPills(r)}</div></div></div>
    <div class="lcabout">${esc(r.about)}</div>
    ${r.machine && r.name === TC_DRIVER ? libDriverPick(r.machine) : ""}
    <div class="ldetail">${open ? libDetail(r) : ""}</div>${err}
    <div class="pcacts actbar">${libState(r)}${libActs(r, may)}</div>
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
    const inst = all.filter(r => r.installed).length;
    const count = !all.length ? "" : k === "app" || k === "companion" ? `${all.length}` : `${inst} of ${all.length} installed`;
    // The catalog's trouble is the packs' alone, said over them, never in the node's head.
    // Over the packs: the catalog's trouble, and the way to offer one of
    // yours to everybody (R169 step 3's vetting: a pull request there).
    const submit = k === "pack" && lib.catalog_repo && may.packs
      ? `<div class="hint">Made a pack worth sharing? <a href="${esc(lib.catalog_repo)}" target="_blank" rel="noopener">Submit it to the vetted catalog ↗</a>: a pull request there, reviewed and signed by the maintainers.</div>` : "";
    const note = (k === "pack" && lib.catalog_error ? `<div class="hint warn">${esc(lib.catalog_error)}</div>` : "") + submit
      || (k === "companion" && featureOff("apps") ? deadWhy(featureOff("apps")) : "");
    const body = k === "companion" && featureOff("apps") ? ""
      : here.length ? `<div class="lgrid">${here.map(r => libRow(r, may)).join("")}</div>`
      : `<div class="empty">${all.length ? "Nothing here matches." : k === "companion" ? "This controller offers no apps for your own machines: an administrator picks them on the Controller page, under Apps."
        : k === "pack" ? "Nothing added yet: Add your own brings in a tool pack of yours, and the vetted catalog's offers land here." : "Nothing here yet."}</div>`;
    return `<div class="libgroup" data-libgroup="${esc(k)}"><h3 class="libgname">${esc(title)}${count ? ` <span class="dim">${esc(count)}</span>` : ""}</h3>${note}${body}</div>`;
  }).join("");
}

function renderLibraryInto(i){
  const d = docSurface(i, "library");
  if (!d) return;
  if (lib === null){
    d.setBar(skActBar([["Check for updates", "", "Check"], ["Add your own", "primary", "Add"]]));
    const skcard = () => `<div class="lcard skcard"><div class="lchead"><span class="lcicon"></span><div class="lctitle">${skv(7, "name")}${skv(4)}</div></div>${skRows(1)}</div>`;
    d.list.innerHTML = skTpl(pageHead({title: GHOST, facts: [["Installed", GHOST], ["Updates due", GHOST], ["Store", GHOST]]})
      + `<div class="field lfilter libfilter"><input type="search" disabled placeholder="search by name or what it does">${skel("chips")}</div>`
      + `<div class="field libgroups">${LIB_KINDS.map(([k, title]) => `<div class="libgroup"><h3 class="libgname">${esc(title)}</h3><div class="lgrid">${skcard()}${skcard()}${skcard()}</div></div>`).join("")}</div>`);
    if (!libSeq) loadLibrary();
    return;
  }
  if (lib.nonode){
    d.setBar("");
    d.list.innerHTML = noNodeYet("toolchains and coding agents install on a node", "libnone");
    return;
  }
  const may = lib.may || {};
  const job = lib.job || {}, busy = !!job.running;
  // The node's whole record: whether its agent is behind and its store
  // read-only are read off it.
  const node = (nodesList || []).find(x => x.id === libNode) || {};
  const stale = nodeStale(node), pro = node.reported?.store_ro === true;
  const clean = may.install && !pro ? (lib.cleanable || []) : [];
  // The node is the Build group's header's (R178).
  d.setBar(nodeBar("", may.install
    ? `${busy ? abortBtn('data-libabort', job.aborting) : ""}
       <button type="button" data-libcheck${busy || stale ? " disabled" : ""} title="ask each upstream what it has now">${
         busy && job.action === "check" ? `${barSaid("Checking for updates", "Checking")}<span class="dots"></span>`
         : (lib.rows || []).some(r => r.latest) ? barSaid("Re-check for updates", "Re-check") : barSaid("Check for updates", "Check")}</button>${
        may.packs ? `<button type="button" class="primary" data-libadd>${barSaid("Add your own", "Add")}</button>` : ""}${
        clean.length ? `<button type="button" class="danger" data-libclean${busy ? " disabled" : ""}>Remove</button>` : ""}` : ""));
  if (lib.error){
    paint(d.list, `<div class="field"><div class="notice bad">${esc("could not read the library: " + lib.error)}</div></div>`);
    return;
  }
  // A card not for this node is not drawn (R170 step 9): counted in the head.
  const all = (lib.rows || []).filter(r => !r.wrong_platform);
  const notHere = (lib.rows || []).length - all.length;
  const rows = all.filter(r => libMatch(r, libQ) && (!libKind || r.kind === libKind) && (!libTier || r.tier === libTier));
  const inst = all.filter(r => r.installed).length, due = all.filter(r => r.update).length;
  const free = lib.store?.free_mb ? `${(lib.store.free_mb / 1024).toFixed(1)} GB free` : "";
  const head = pageHead({title: lib.name || "", facts: [
    ["Installed", `${inst} of ${all.filter(r => r.kind !== "app" && r.kind !== "companion").length}`],
    ["Updates due", due ? String(due) : ""],
    ["Store", lib.store?.root ? `${lib.store.root}${free ? ", " + free : ""}` : ""],
    ["Versions checked", lib.store?.checked ? ago(lib.store.checked) : ""],
    ["Not for this node", notHere ? String(notHere) : ""],
    ["Remove takes", clean.length ? clean.map(c => `<code>${esc(c.dir)}</code> (${esc(c.what)})`).join(", ") : "", {html: true}],
  ]});
  // What the Toolchains page said over its rows (step 5): a node that has
  // not reported, a store it cannot write, and the system packages its
  // held recipes lack, with the one press that installs them.
  const unmet = Object.entries(lib.sysdeps?.unmet || {});
  const notes = `${stale ? `<div class="field"><div class="notice warn libstale">${esc(staleWhy(node))}. Nothing installs here until it is.</div></div>` : ""}${
    pro ? `<div class="field"><div class="notice warn libro">${esc(lib.name || "This node")}'s toolchain store is read-only to it, so nothing installs here: what is in it is what it has. Make it writable on the machine to install.</div></div>` : ""}${
    unmet.length ? `<div class="field"><div class="notice warn libsys">System packages ${esc(lib.name || "this node")} lacks for what its store holds (${esc(lib.sysdeps.family || "")}): ${
      unmet.map(([r, ps]) => `${esc(r)}: ${esc(ps.join(" "))}`).join("; ")}. ${lib.sandbox && may.install
        ? `<button type="button" data-libsysdeps${busy || stale ? " disabled" : ""} title="install these on ${esc(lib.name || "the node")} without reinstalling the toolchains">Install system packages</button>`
        : "This node's owner installs them: the agent does not administer the machine."}</div></div>` : ""}`;
  libHold = busy ? "another toolchain job is running on this node" : stale ? "this node is not reporting" : pro ? "this node's store is read-only to it" : "";
  paint(d.list, `<div data-libnode="${esc(libNode)}">${notes}${head}${libFilterBand(all)}<div class="field libgroups">${libSections(rows, may)}</div></div>`);
  // The ellipsis on a card whose job runs is ticked by the one timer every
  // page shares (tcTickDots), so a redraw does not restart it.
  if (!tcDotsTimer && d.list.querySelector(".dots")) tcDotsTimer = setInterval(tcTickDots, 400);
  wireLibrary(d.el);
}

function wireLibrary(root){
  wireSections(root);
  if (typeof wireSignin === "function") wireSignin(root);
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
  const ab = root.querySelector("[data-libabort]");
  if (ab) ab.onclick = async () => { await tcAct("abort"); loadLibrary(); };
  const sd = root.querySelector("[data-libsysdeps]");
  if (sd) sd.onclick = () => pressing(sd, async () => { busy(sd, "Installing"); await tcAct("sysdeps"); await loadLibrary(); });
  const cl = root.querySelector("[data-libclean]");
  if (cl) cl.onclick = async () => {
    const dirs = (lib?.cleanable || []).map(c => c.dir);
    if (!dirs.length || !await askYes(`Take ${dirs.join(", ")} off the store?\n\nNo node runs from ${dirs.length === 1 ? "it" : "them"}; what is in ${dirs.length === 1 ? "it" : "them"} is gone for good.`, {verb: "Remove", danger: true})) return;
    busy(cl, "Removing");
    const j = await (await postJSON("/api/toolchains", {action: "clean", node: libNode, names: dirs})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    loadLibrary();
  };
  const dsel = root.querySelector("#libDrvSel");
  if (dsel) dsel.onchange = () => { tcDriverPick = dsel.value; };
  const add = root.querySelector("[data-libadd]");
  if (add) add.onclick = () => libWithToolchains(() => tpOpen(""));
  root.querySelectorAll("[data-libact]").forEach(b => b.onclick = () => libAct(b, b.dataset.libact, b.dataset.libkind, b.dataset.libname));
  root.querySelectorAll("[data-liblook]").forEach(b => b.onclick = () => libLook(b.dataset.liblook));
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
  if (kind === "app"){
    if (act === "edit") tpOpenApp(name); else openNewContainerApp(name);
    return;
  }
  if (kind === "service"){
    busy(b, "Deploying");
    const j = await (await postJSON("/api/library", {action: "install", node: libNode, pack: r.name})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else if (j.job) notify(`deploying ${r.label}: its row on the Containers page has the build`);
    await loadLibrary();
    return;
  }
  if (kind === "agent"){
    if (r.installed && !await askYes(`Update ${r.label} on ${where}? Its sessions there end first; they start again from the project rows.`)) return;
    busy(b, "Asking");
    const j = await (await postJSON("/api/agents", {action: act, node: libNode, agent: r.agent || ""})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    await loadLibrary();
    return;
  }
  if (act === "add"){ libWithToolchains(() => tpOpenCatalog({...r.catalog, name: r.name, tier: r.tier, about: r.about, platforms: r.platforms})); return; }
  if (act === "edit"){ libWithToolchains(() => tpOpen(r.name)); return; }
  // Install or update a toolchain or an added pack: the Toolchains job,
  // with its agreements asked the way that page asks them.
  busy(b, r.installed ? "Updating" : "Installing");
  await tcAct("install", [r.name]);
  await loadLibrary();
}
