// The shell (R218 step 2): a rail of groups down the left edge, each one a
// page with an address, the page on show in the pane; the tool tabs that
// filled the strip are these pages now, and the strip keeps the documents
// (terminals, notebooks, the profile is a page under Settings). On a phone
// the rail is a bar of five across the bottom, with More for the rest.
// The top bar carries a search that jumps to a page, a project, a container
// or a node.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the rail ----------------------------------------------------------------

// One stroke voice with TOOL_ICONS (page-tabs.js), 16px, for the groups
// that have no tool icon of their own.
const RAIL_ICONS = {
  home: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 8.2 8 3.2l5.5 5"/><path d="M4 7v6h8V7"/><path d="M6.6 13V9.6h2.8V13"/></svg>`,
  projects: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4.5h4l1.2 1.4h5.8v7.1H2.5z"/><path d="M2.5 7.4h11"/></svg>`,
  sessions: `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.4" y="3" width="11.2" height="8.6" rx="1.2"/><path d="M4.6 6.2l1.8 1.4-1.8 1.4"/><path d="M7.6 9h3"/><path d="M5.5 13.5h5"/></svg>`,
  people: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6.2" cy="5.6" r="2.3"/><path d="M2.4 13c.3-2.6 1.9-4 3.8-4s3.5 1.4 3.8 4"/><circle cx="11.2" cy="6.2" r="1.8"/><path d="M10.4 9.6c1.9 0 3 1.3 3.2 3.4"/></svg>`,
  settings: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.6 1.9h2.8l.35 1.72 1.2.7 1.66-.57 1.4 2.42-1.3 1.16v1.4l1.3 1.16-1.4 2.42-1.66-.57-1.2.7-.35 1.72H6.6l-.35-1.72-1.2-.7-1.66.57-1.4-2.42 1.3-1.16v-1.4L1.99 6.17l1.4-2.42 1.66.57 1.2-.7z"/><circle cx="8" cy="8" r="2.1"/></svg>`,
  more: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/></svg>`,
  // A server: two units in a rack, each with its light.
  controller: `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="2.8" width="11" height="4.4" rx="1"/><rect x="2.5" y="8.8" width="11" height="4.4" rx="1"/><circle cx="5" cy="5" r=".6"/><circle cx="5" cy="11" r=".6"/><path d="M8 5h3.5M8 11h3.5"/></svg>`,
  help: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.8"/><path d="M6.3 6.4a1.75 1.75 0 1 1 2.5 1.6c-.55.27-.8.66-.8 1.2v.3"/><path d="M8 11.3v.1"/></svg>`,
};

// The eleven groups, in the rail's order (the design's rail rule); Help, the
// docs, last (R258). A group's
// tools are the tab kinds it holds, the first the one its button opens; a
// group with several draws them as the page's sub-nav.
const RAIL = [
  {key: "home", label: "Home", icon: "home", tools: [["home", "Home"]]},
  {key: "projects", label: "Projects", icon: "projects", tools: [["projects", "Projects"], ["findings", "Analysis"]]},
  {key: "build", label: "Build", icon: "toolchains", tools: [["library", "Library"], ["emulator", "Emulator"], ["phone", "Phone"], ["runner", "CI runner"]]},
  {key: "containers", label: "Containers", icon: "docker", tools: [["docker", "Containers"], ["vms", "VMs"], ["nginx", "nginx"], ["scanners", "Scanners"]]},
  // The controller, a group of its own (the operator, 22 Oct): how this
  // BuilderBot behaves, with room for the pages a bare-metal install and
  // the USB edition add beside Settings (R90, R56). After Containers, so a
  // phone's bar keeps its four.
  {key: "controller", label: "Controller", icon: "controller", tools: [["machine", "This machine"], ["settings", "Settings"], ["network", "Network"], ["keys", "Keys"], ["audit", "Audit"], ["debug", "Debug"]]},
  {key: "machines", label: "Machines", icon: "nodes", tools: [["nodes", "Nodes"], ["storage", "Storage"], ["installed", "Installed"]]},
  {key: "sessions", label: "Sessions", icon: "sessions", tools: [["sessions", "Sessions"]]},
  {key: "jobs", label: "Jobs", icon: "jobs", tools: [["jobs", "Jobs"], ["schedules", "Schedules"]]},
  {key: "people", label: "People", icon: "people", tools: [["users", "Users"], ["roles", "Roles"]], admin: true},
  {key: "settings", label: "Settings", icon: "settings", tools: [["profile", "Profile"]]},
  {key: "help", label: "Help", icon: "help", tools: [["help", "Help"]]},
];
// The five on a phone's bar: the rail's first four, so a phone and a desk
// keep one order (the operator, 19 Oct), and More for the rest in it.
const RAIL_PHONE = RAIL.slice(0, 4).map(g => g.key);

// A tool kind is a page: it leaves the strip and lives on the rail.
function isToolKind(kind){ return kind !== "term" && kind !== "notebook"; }

// The group a tab kind is a page of: the first group that lists it.
function groupOf(kind){
  // The pages the Library replaced (R170) are off the rail but keep their
  // addresses under Build until step 5 retires them.
  return RAIL.find(g => (g.tools || []).some(([k]) => k === kind))
    || (["toolchains", "agents", "apps"].includes(kind) ? RAIL.find(g => g.key === "build") : null);
}

// Which tool kinds this account may open, from the areas its grants read
// (state.areas, "" for no Read; R152 step 3): a rail item for something a
// grant forbids is not drawn. CI runner is offered by grant too (R137 step
// 3). Before the first poll everything is drawn, as the page always was.
function railAllows(kind){
  const a = state?.areas;
  // The Debug page (R147) only where DEBUG_MODE=1 started the controller,
  // and for an account with the debug grant, whatever its areas say.
  if (kind === "debug") return !!state?.settings?.debug_available && state?.can?.debug !== false;
  if (!a) return true;
  switch (kind){
    case "settings": case "keys": case "audit": case "network": return !!a.controller;
    // This machine (R90 step 8): a bare-metal install's own, drawn only
    // where the install has one; the container edition shows Settings first.
    case "machine": return !!a.controller && !!state?.own_node;
    case "users": case "roles": return !!a.accounts;
    // The Emulator's images are the toolchain store's, so the same area.
    case "toolchains": case "emulator": return !!a.toolchains;
    // The coding agents on a node (R95): installed as a toolchain is, and
    // signed in to by whoever works there, so either area draws it.
    case "agents": return !!a.toolchains || !!a.nodes;
    // The Library (R170): the Toolchains and Agents pages as one, so either
    // area draws it; what each row offers is the server's to gate.
    case "library": return !!a.toolchains || !!a.nodes;
    // What is installed on a node (R172): the same areas as the Library.
    case "installed": return !!a.toolchains || !!a.nodes;
    case "jobs": return !!a.jobs;
    // An administrator's own cron (R117), its own area.
    case "schedules": return !!a.schedules;
    // The nginx tab is the Nodes tab's area (R171); Storage its own (R169).
    case "nodes": case "nginx": case "scanners": return !!a.nodes;
    case "storage": return !!a.storage;
    case "runner": return state?.can?.runner !== false && a.runner !== "";
    default: return true;
  }
}
function railGroups(){
  return RAIL.filter(g => (g.tools || []).some(([k]) => railAllows(k)));
}
// The page a group opens on: the one asked for when this account may open
// it, else the group's first that it may.
function railTool(g, want){
  const ok = (g.tools || []).filter(([k]) => railAllows(k)).map(([k]) => k);
  return want && ok.includes(want) ? want : ok[0] || "";
}

// What the rail lights: the group somebody pressed, while its page is the
// one on show; else the group of the page on show.
let railWant = "";
function railOn(){
  const t = tabOf(panes[0]);
  const kind = t?.kind || "";
  if (railWant){
    const g = RAIL.find(x => x.key === railWant);
    if (g && (g.tools || []).some(([k]) => k === kind)) return railWant;
    railWant = "";
  }
  // The pages the Library replaced (R170) are off the rail but keep their
  // addresses under Build until step 5 retires them.
  return groupOf(kind)?.key || (kind === "notebook" ? "projects" : "");
}

// Open a group: its first tool as a page. A press is a navigation, so the
// address is pushed.
const OPENERS = {
  home: () => openHome(),
  projects: () => openProjectsTab(), findings: () => openFindingsTab(), docker: () => openDocker(),
  nodes: () => openNodesTab(), storage: () => openStorageTab(), installed: () => openInstalledTab(), nginx: () => openNginxTab(), vms: () => openVmsTab(),
  // The Toolchains, Agents and Apps pages are the Library since R170: every
  // door a person presses lands there; their own addresses still open them
  // until step 5 retires them with their suites.
  library: () => openLibrary(), toolchains: () => openToolchains(), agents: () => openAgentsTab(), emulator: () => openEmulator(), phone: () => openPhoneTab(),
  runner: () => openRunnerTab(), jobs: () => openJobsTab(), debug: () => openDebugTab(), schedules: () => openSchedulesTab(), users: () => openUsersTab(),
  roles: () => openRolesTab(), settings: () => openSettingsTab(), keys: () => openKeysTab(), profile: () => openProfileTab(),
  apps: () => openAppsTab(),
  sessions: () => openSessionsTab(), help: () => openHelp(),
  // The pages of 0.9.0 (B410: an address with no opener landed on its
  // group's first page): Scanners, Audit, This machine and Network.
  scanners: () => openScannersTab(), audit: () => openAuditTab(), machine: () => openMachineTab(), network: () => openNetworkTab(),
};
function railGo(key, tool){
  const g = RAIL.find(x => x.key === key);
  if (!g) return;
  railWant = key;
  const kind = railTool(g, tool);
  if (!kind) return;
  // A page opened anew opens on its first section on a phone.
  sectNewVisit();
  const was = location.hash;
  OPENERS[kind]?.();
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was) shellPush(to);
}

// A history entry the page made itself, and shellSync told so: it leaves an
// address alone that differs from the one it last saw (a hand-typed one,
// B303), and an entry pushed here without saying so read as one, so the
// next page opened left the old page's address under it and Back went
// there (B313).
function shellPush(to){
  history.pushState(null, "", to);
  shellSeen = to;
}

// A node page's picked node, read and set by the address (R256 step 3): the
// node is the address's last part, so a reload, a link and Back land on it.
// The Jobs page has no node; its second segment is the chip it is narrowed
// to (#/jobs/failed-today, which Home's "failed today" opens, B74).
const NODE_PICKED = {jobs: () => jobsShow, nodes: () => nodesPick, storage: () => storageNode, nginx: () => nginxNode,
  toolchains: () => tcNode === "local" ? "" : tcNode, agents: () => agNode, library: () => libNode, installed: () => instNode, emulator: () => emuNode, phone: () => phNode,
  runner: () => runnerNode, docker: () => dockerNode};
// Toolchains' "local" (the controller's own store, for a shell and the
// suite) is no node, so an address naming it opens on the node tcPick picks.
// A page that keeps what it read for one node forgets it when Back names
// another, or the other node's list showed under this one until the read.
const NODE_SET = {jobs: v => jobsShowSet(v), nodes: v => { nodesPick = v; }, storage: v => { storageNode = v; }, nginx: v => { nginxNode = v; },
  toolchains: v => { const n = v === "local" ? "" : v;
                     if (n !== tcNode){ tcNode = n; toolchains = null; tcTicked.clear(); tcDriverPick = ""; } },
  agents: v => { if (v !== agNode){ agNode = v; agRows = null; } },
  library: v => { if (v !== libNode){ libNode = v; lib = null; } },
  installed: v => { if (v !== instNode){ instNode = v; inst = null; } },
  emulator: v => { if (v !== emuNode){ emuNode = v; emu = null; emuTicked.clear(); } },
  phone: v => { if (v !== phNode){ phNode = v; phIp = ""; } },
  runner: v => { runnerNode = v; },
  docker: v => { if (v !== dockerNode){ dockerNode = v; dockerList = dockerSeen[v] || null; } }};

// A move inside a page (a notebook view, a wiki page) is a history entry,
// so Back returns to where it was (R256 step 3): the draw replaces the
// address as it always does, and the one before is put back and the new
// one pushed after it.
function navPush(fn){
  const was = location.hash;
  fn();
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was){ history.replaceState(null, "", was || location.pathname + location.search); shellPush(to); }
}

// The address a tab is reached at: #/group, #/group/tool, #/projects/NAME,
// with a node page's node and the open wiki page on the end. A terminal has
// none.
function routeOf(t){
  if (!t) return "";
  if (t.kind === "notebook"){
    // ...and the view it is on (R218 step 3): Overview is the Briefing
    // view's name on the page, so the address says overview.
    const n = notebooks.get(t.arg), v = n?.where?.() || "";
    // ...and a branch's comparison, its own page (R269 step 2).
    const page = v === "wiki" ? n?.wikiPage?.() || "" : v === "git" && n?.gitPage?.() ? "compare/" + encodeURIComponent(n.gitPage()) : "";
    return "#/projects/" + encodeURIComponent(t.arg) + (v ? "/" + (v === "briefing" ? "overview" : v) : "")
      + (page ? "/" + (v === "git" ? page : encodeURIComponent(page)) : "");
  }
  if (!isToolKind(t.kind)) return "";
  // The Notifications page is on no group: the bell's See all opens it.
  if (t.kind === "notices") return "#/notifications";
  // Help names the doc on show (R258), so a link to one lands on it.
  if (t.kind === "help") return "#/help" + (helpCur && helpCur !== helpIndex?.home ? "/" + encodeURIComponent(helpCur) : "");
  const g = groupOf(t.kind);
  if (!g) return "";
  // Home is #/home, the address everything links to, though its group
  // holds Controller settings too.
  if (t.kind === "home") return "#/home";
  const node = NODE_PICKED[t.kind]?.() || "";
  // A page named as its group is (Jobs, beside Schedules since R117) keeps
  // the group's own address, #/jobs/failed as Home links it, never
  // #/jobs/jobs; the reader takes a segment that is no page's for its node.
  return ((g.tools || []).length > 1 && t.kind !== g.key ? `#/${g.key}/${t.kind}` : `#/${g.key}`) + (node ? "/" + encodeURIComponent(node) : "");
}

// Open what an address names; nothing happens for one that names nothing.
function openRoute(hash){
  const m = /^#\/([a-z]+)(?:\/([^/]+))?(?:\/([^/]+))?(?:\/([^/]+))?(?:\/([^/]+))?/.exec(hash || "");
  if (!m) return false;
  const [, key, a, b, c, d] = m;
  if (key === "projects" && a && !RAIL[1].tools.some(([k]) => k === a)){
    const name = decodeURIComponent(a);
    if (!(state?.projects || []).some(p => p.name === name)) return false;
    railWant = "projects";
    const v = b ? decodeURIComponent(b) : "";
    // A comparison is set before the open as well as after it: the open
    // writes the address, and written without the comparison the entry for
    // it read /git, so Back from it went nowhere.
    const cmp = v === "git" ? (c === "compare" && d ? decodeURIComponent(d) : "") : null;
    if (cmp !== null) notebooks.get(name)?.gitAt?.(cmp);
    openNotebook(name, v ? (v === "overview" ? "briefing" : v) : undefined);
    if (v === "wiki" && c) notebooks.get(name)?.wikiAt?.(decodeURIComponent(c));
    if (cmp !== null) notebooks.get(name)?.gitAt?.(cmp);
    return true;
  }
  if (key === "notifications"){ openNotices(); return true; }
  if (key === "help"){
    railWant = "help";
    const doc = a ? decodeURIComponent(a) : helpIndex?.home || "";
    if (doc && doc !== helpCur){ helpCur = doc; helpQ = ""; helpHits = null; helpRev++; }
    // ...at a section of it when the address names one (#/help/reference/
    // the-install-key): the doctor's links land on the fix itself.
    if (b){ helpAnchor = decodeURIComponent(b); helpRev++; }
    openHelp();
    if (helpIndex && helpCur) helpRead(helpCur);
    return true;
  }
  let g = RAIL.find(x => x.key === key);
  if (!g) return false;
  // A page that moved group keeps its old address: #/machines/settings and
  // #/home/settings, bookmarks from before Controller settings had a group
  // of its own, open it there.
  if (a && !(g.tools || []).some(([k]) => k === a) && groupOf(a)) g = groupOf(a);
  const multi = (g.tools || []).length > 1;
  // A group of one tool names its node second (#/group/NODE), as routeOf
  // writes it.
  // ...and a page the Library replaced (R170) keeps its address under Build
  // until step 5 retires it, though the rail no longer lists it.
  const retired = !!a && ["toolchains", "agents", "apps"].includes(a) && groupOf(a) === g && !!OPENERS[a] && railAllows(a);
  const named = (g.tools || []).some(([k]) => k === a) || retired;
  const kind = retired ? a : railTool(g, named ? a : "");
  if (!kind) return false;
  railWant = g.key;
  // The node the address names, set before the page draws (R256 step 3).
  const node = multi && named ? b : a;
  if (node && NODE_SET[kind]) NODE_SET[kind](decodeURIComponent(node));
  OPENERS[kind]?.();
  return true;
}

// The address follows the page on show (render calls this): replaced, not
// pushed, so a poll's redraw is not a history entry; a rail press pushes.
// The address it last left, or null before the first: one that has changed
// since, and is not the page on show, is a navigation whose hashchange has
// not run yet, and is left for it. Replacing it took the address back to the
// page being left, which the handler then opened (B303).
let shellSeen = null;
function shellSync(){
  const to = routeOf(tabOf(panes[0]));
  if (shellSeen !== null && location.hash && location.hash !== shellSeen && location.hash !== to) return;
  shellSeen = to || "";
  if (to && to !== location.hash) history.replaceState(null, "", to);
  // A document in front has no address: the page's goes, so a reload lands
  // on the document this browser had in front (R131), not on the last page.
  else if (!to && location.hash) history.replaceState(null, "", location.pathname + location.search);
}
// Once, on the first draw that had state: an address the page was opened on
// wins over the strip's remembered front tab, unless it names that very tab.
let shellBooted = false;
function shellBoot(){
  if (shellBooted || !state) return;
  shellBooted = true;
  const h = location.hash;
  if (h && h !== "#/" && h !== routeOf(tabOf(panes[0]))) openRoute(h);
}

// A page on show in a visible pane: what a watch asks before fetching for it
// (the design's pages rule: nothing for the pages not on show).
function shown(kind){
  return panes.some((id, i) => (i === 0 || isSplit()) && tabOf(id)?.kind === kind);
}

// The rail, and on a phone the bar and its More sheet.
function drawRail(){
  const rail = $("rail"), bar = $("railbar");
  if (!rail || !bar || !state) return;
  const on = railOn(), groups = railGroups();
  const item = g => `<button type="button" class="ritem${g.key === on ? " on" : ""}" data-rail="${esc(g.key)}" aria-label="${esc(g.label)}"${
      g.key === on ? ' aria-current="page"' : ""}>${RAIL_ICONS[g.icon] || TOOL_ICONS[g.icon] || ""}<span class="rlbl">${esc(g.label)}</span></button>`;
  const html = groups.map(item).join("");
  // Through paint(), which remembers what it wrote: compared against
  // innerHTML, which the browser writes back its own way (an SVG's
  // attributes, an entity), it never matched, and the rail was rebuilt on
  // every draw with the pointer on it (R218 step 10).
  if (paint(rail, html, true)){
    rail.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => railGo(b.dataset.rail));
  }
  // ...and the bar beside the group on show slides to the one pressed.
  slideMark(rail, "rail", true);
  const five = groups.filter(g => RAIL_PHONE.includes(g.key));
  const rest = groups.filter(g => !RAIL_PHONE.includes(g.key));
  const moreOn = rest.some(g => g.key === on);
  const bhtml = five.map(item).join("") + (rest.length
    ? `<button type="button" class="ritem${moreOn ? " on" : ""}" data-railmore aria-haspopup="menu" aria-expanded="${railMoreOpen}" aria-label="More">${RAIL_ICONS.more}<span class="rlbl">More</span></button>` : "");
  if (paint(bar, bhtml, true)){
    bar.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => { railMoreShow(false); railGo(b.dataset.rail); });
    bar.querySelector("[data-railmore]")?.addEventListener("click", () => railMoreShow(!railMoreOpen));
  }
  const more = $("railmore");
  if (more){
    const mhtml = rest.map(g => `<button type="button" class="ritem${g.key === on ? " on" : ""}" data-rail="${esc(g.key)}">${
        RAIL_ICONS[g.icon] || TOOL_ICONS[g.icon] || ""}<span class="rlbl">${esc(g.label)}</span></button>`).join("");
    if (paint(more, mhtml, true)){
      more.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => { railMoreShow(false); railGo(b.dataset.rail); });
    }
  }
}
let railMoreOpen = false;
function railMoreShow(on){
  railMoreOpen = !!on;
  const m = $("railmore"), b = $("railbar")?.querySelector("[data-railmore]");
  if (m) m.hidden = !railMoreOpen;
  if (b) b.setAttribute("aria-expanded", String(railMoreOpen));
}

// The pane's bar for a page: the group's tools as a sub-nav, one button
// in the accent when the page stands alone (the operator, 16 Oct: a bare
// name beside the other pages' segments read as a different kind of page);
// a page has no close, the rail is how you leave it (a split pane keeps its
// own close).
function shellBar(t, i){
  const g = groupOf(t.kind);
  const tools = g ? g.tools.filter(([k]) => railAllows(k) || k === t.kind) : [[t.kind, tabLabel(t)]];
  return `<span class="subnav pseg" role="tablist" aria-label="${esc(g ? g.label : tabLabel(t))}">${tools.map(([k, label]) =>
      `<button type="button" role="tab" aria-selected="${k === t.kind}" class="${k === t.kind ? "on" : ""}"${g ? ` data-subnav="${esc(k)}"` : ""}>${esc(label)}</button>`).join("")}</span>`;
}
function wireShellBar(bar){
  // The line under the tab on show slides to the one pressed (slideMark),
  // kept per group so another group's sub-nav never slides from this one.
  const sub = bar.querySelector(".subnav");
  if (sub) slideMark(sub, "subnav:" + (groupOf(sub.querySelector(".on")?.dataset.subnav || "")?.key || sub.getAttribute("aria-label") || ""));
  bar.querySelectorAll("[data-subnav]").forEach(b => b.onclick = () => {
    const g = groupOf(b.dataset.subnav);
    if (g) railGo(g.key, b.dataset.subnav);
  });
}

// ---- maintenance mode's band ---------------------------------------------------
// Drawn under the header for the owner while maintenance mode is on: the
// server sends it hidden on every page, and the poll shows it, so switching
// it on or off shows without a reload.
function drawMaintBand(){
  const b = document.getElementById("maintband");
  const off = !(state?.can?.maintenance && state?.settings?.settings?.maintenance_mode?.value);
  // Written only when it changes: a poll that brings nothing new writes nothing.
  if (b && b.hidden !== off) b.hidden = off;
  // Its link opens Controller settings at Maintenance, where it is switched
  // off (the operator, 26 Oct).
  const go = b?.querySelector("[data-maintgo]");
  if (go && !go.onclick) go.onclick = e => { e.preventDefault(); SPLIT.settings = {pick: "maint", open: true}; openSettingsTab(); };
}

// ---- a held start's band (R56 step 9) ------------------------------------------
// Drawn under the header on a bare-metal install while its start is held:
// the server sends it hidden on every page, and the poll shows it with why.
function drawHeldBand(){
  const b = document.getElementById("heldband");
  if (!b) return;
  const h = state?.held || {};
  const off = !h.held;
  if (b.hidden !== off) b.hidden = off;
  const why = b.querySelector("[data-heldwhy]");
  const said = (h.why || []).length ? `Held because ${h.why.join("; ")}.` : "";
  if (why && why.textContent !== said) why.textContent = said;
  const go = b.querySelector("[data-heldgo]");
  if (go && !go.onclick) go.onclick = e => { e.preventDefault(); openMachineTab(); };
}

// ---- a moved controller's band (R90 step 12) ---------------------------------
function drawMovedBand(){
  const b = document.getElementById("movedband");
  if (!b) return;
  const to = state?.moved_to || "";
  const off = !to;
  if (b.hidden !== off) b.hidden = off;
  const a = b.querySelector("[data-movedto]");
  if (a && to && a.textContent !== to){ a.textContent = to; a.href = to; }
}

// ---- search: jump to a page, a project, a container or a node ---------------

// Rows: [label, where, go]. Pages by name, projects by the name they are
// shown under, nodes from the list once it has landed, containers from what
// every node last answered (dmJumpRows).
function jumpItems(q){
  const needle = (q || "").trim().toLowerCase();
  if (!needle) return [];
  const rows = [];
  for (const g of railGroups()){
    for (const [k, label] of g.tools) if (railAllows(k))
      rows.push([label, g.tools.length > 1 ? `${g.label} page` : "page", () => railGo(g.key, k)]);
  }
  for (const p of state?.projects || [])
    rows.push([projLabel(p.name), "project", () => { railWant = "projects"; openNotebook(p.name); }]);
  for (const n of nodesList || [])
    rows.push([n.name || n.id, "node", () => { railGo("machines", "nodes"); openNodesTab(n.id); }]);
  for (const c of dmJumpRows())
    rows.push([c.name, `container on ${c.where}`, () => dmJumpTo(c.node, c.name)]);
  const hit = rows.filter(([label]) => label.toLowerCase().includes(needle));
  hit.sort((a, b) => a[0].toLowerCase().indexOf(needle) - b[0].toLowerCase().indexOf(needle));
  return hit.slice(0, 8);
}
let jumpRows = [];
let jumpAt = 0;                  // the row the arrow keys have marked, Enter's
function drawJump(){
  const inp = $("jump"), list = $("jumpList");
  if (!inp || !list) return;
  jumpRows = jumpItems(inp.value);
  jumpAt = 0;
  // Something typed that matches nothing says so, rather than the list
  // staying shut as if the field had not heard (B72).
  const none = !jumpRows.length && !!inp.value.trim();
  list.hidden = !jumpRows.length && !none;
  list.innerHTML = none ? `<div class="jnone" role="option" aria-disabled="true">nothing matches “${esc(inp.value.trim())}”</div>`
    : jumpRows.map(([label, where], i) =>
    `<button type="button" class="jrow${i === 0 ? " on" : ""}" id="jumpRow${i}" data-jump="${i}" role="option" aria-selected="${i === 0}"><span class="jl">${esc(label)}</span><span class="jw">${esc(where)}</span></button>`).join("");
  list.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jumpGo(Number(b.dataset.jump)));
  if (jumpRows.length) inp.setAttribute("aria-activedescendant", "jumpRow0");
  else inp.removeAttribute("aria-activedescendant");
}
// ArrowDown and ArrowUp move the mark through the rows, round at the ends,
// so the second hit is a key away and not only the mouse's (B72).
function jumpMove(by){
  const list = $("jumpList");
  if (!jumpRows.length || !list) return;
  jumpAt = (jumpAt + by + jumpRows.length) % jumpRows.length;
  list.querySelectorAll("[data-jump]").forEach(b => {
    const on = Number(b.dataset.jump) === jumpAt;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
    if (on) b.scrollIntoView({block: "nearest"});
  });
  $("jump")?.setAttribute("aria-activedescendant", "jumpRow" + jumpAt);
}
function jumpGo(i){
  const row = jumpRows[i] || jumpRows[0];
  const inp = $("jump"), list = $("jumpList");
  if (inp){ inp.value = ""; inp.blur(); }
  if (list){ list.hidden = true; list.innerHTML = ""; }
  jumpRows = [];
  if (!row) return;
  row[2]();
}
function wireJump(){
  const inp = $("jump"), list = $("jumpList");
  if (!inp || !list) return;
  // The whole hint where it fits, else a shorter one, else two words (the
  // operator, 18 Oct: cut off mid-word), measured against the field as it is
  // laid out, since at a desk it was still cut at 1280 (B72). The aria-label
  // keeps the whole of it either way.
  const said = () => {
    const cs = getComputedStyle(inp);
    const room = inp.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 4;
    const ctx = (said.ctx ||= document.createElement("canvas").getContext("2d"));
    ctx.font = cs.font;
    const hint = ["jump to a page, project, container or node", "jump to a page, project or node", "jump to…"]
      .find(t => ctx.measureText(t).width <= room) || "jump to…";
    if (inp.placeholder !== hint) inp.placeholder = hint;
  };
  said();
  if (window.ResizeObserver) new ResizeObserver(said).observe(inp);
  inp.oninput = drawJump;
  inp.onfocus = () => { (nodesList === null ? loadNodes() : Promise.resolve()).then(dmJumpLoad).then(drawJump); drawJump(); };
  inp.onkeydown = e => {
    if (e.key === "Enter"){ e.preventDefault(); jumpGo(jumpAt); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp"){ e.preventDefault(); jumpMove(e.key === "ArrowDown" ? 1 : -1); }
    else if (e.key === "Escape"){ inp.value = ""; list.hidden = true; inp.blur(); }
  };
  document.addEventListener("click", e => { if (!e.target.closest(".jump")) list.hidden = true; });
}
