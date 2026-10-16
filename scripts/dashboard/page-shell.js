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
  help: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.8"/><path d="M6.3 6.4a1.75 1.75 0 1 1 2.5 1.6c-.55.27-.8.66-.8 1.2v.3"/><path d="M8 11.3v.1"/></svg>`,
};

// The ten groups, in the rail's order (the design's rail rule); Help, the
// docs, last (R258). A group's
// tools are the tab kinds it holds, the first the one its button opens; a
// group with several draws them as the page's sub-nav.
const RAIL = [
  {key: "home", label: "Home", icon: "home", tools: [["home", "Home"]]},
  {key: "projects", label: "Projects", icon: "projects", tools: [["projects", "Projects"], ["findings", "Analysis"]]},
  {key: "containers", label: "Containers", icon: "docker", tools: [["docker", "Containers"]]},
  {key: "machines", label: "Machines", icon: "nodes", tools: [["nodes", "Nodes"], ["storage", "Storage"], ["nginx", "nginx"]]},
  {key: "build", label: "Build", icon: "toolchains", tools: [["toolchains", "Toolchains"], ["emulator", "Emulator"], ["phone", "Phone"], ["runner", "CI runner"]]},
  {key: "jobs", label: "Jobs", icon: "jobs", tools: [["jobs", "Jobs"]]},
  {key: "sessions", label: "Sessions", icon: "sessions", tools: [["sessions", "Sessions"]]},
  {key: "people", label: "People", icon: "people", tools: [["users", "Users"], ["roles", "Roles"]], admin: true},
  {key: "settings", label: "Settings", icon: "settings", tools: [["settings", "Controller"], ["profile", "Profile"]]},
  {key: "help", label: "Help", icon: "help", tools: [["help", "Help"]]},
];
// The five on a phone's bar; the rest are under More.
const RAIL_PHONE = ["home", "projects", "containers", "jobs"];

// A tool kind is a page: it leaves the strip and lives on the rail.
function isToolKind(kind){ return kind !== "term" && kind !== "notebook"; }

// The group a tab kind is a page of: the first group that lists it.
function groupOf(kind){
  return RAIL.find(g => (g.tools || []).some(([k]) => k === kind)) || null;
}

// Which tool kinds this account may open, from the areas its grants read
// (state.areas, "" for no Read; R152 step 3): a rail item for something a
// grant forbids is not drawn. CI runner is offered by grant too (R137 step
// 3). Before the first poll everything is drawn, as the page always was.
function railAllows(kind){
  const a = state?.areas;
  if (!a) return true;
  switch (kind){
    case "settings": return !!a.controller;
    case "users": case "roles": return !!a.accounts;
    // The Emulator's images are the toolchain store's, so the same area.
    case "toolchains": case "emulator": return !!a.toolchains;
    case "jobs": return !!a.jobs;
    // The nginx tab is the Nodes tab's area (R171); Storage its own (R169).
    case "nodes": case "nginx": return !!a.nodes;
    case "storage": return !!a.storage;
    case "runner": return state?.can?.runner !== false && a.runner !== "";
    default: return true;
  }
}
function railGroups(){
  return RAIL.filter(g => (g.tools || []).some(([k]) => railAllows(k)));
}
// The page a group opens on: the one asked for when this account may open
// it, else the group's first that it may. Settings opens Profile for an
// account the Controller page is not drawn for, where it opened nothing.
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
  return groupOf(kind)?.key || (kind === "notebook" ? "projects" : "");
}

// Open a group: its first tool as a page. A press is a navigation, so the
// address is pushed.
const OPENERS = {
  home: () => openHome(),
  projects: () => openProjectsTab(), findings: () => openFindingsTab(), docker: () => openDocker(),
  nodes: () => openNodesTab(), storage: () => openStorageTab(), nginx: () => openNginxTab(),
  toolchains: () => openToolchains(), emulator: () => openEmulator(), phone: () => openPhoneTab(),
  runner: () => openRunnerTab(), jobs: () => openJobsTab(), users: () => openUsersTab(),
  roles: () => openRolesTab(), settings: () => openSettingsTab(), profile: () => openProfileTab(),
  sessions: () => openSessionsTab(), help: () => openHelp(),
};
function railGo(key, tool){
  const g = RAIL.find(x => x.key === key);
  if (!g) return;
  railWant = key;
  const kind = railTool(g, tool);
  if (!kind) return;
  const was = location.hash;
  OPENERS[kind]?.();
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was) history.pushState(null, "", to);
}

// A node page's picked node, read and set by the address (R256 step 3): the
// node is the address's last part, so a reload, a link and Back land on it.
const NODE_PICKED = {nodes: () => nodesPick, storage: () => storageNode, nginx: () => nginxNode,
  toolchains: () => tcNode === "local" ? "" : tcNode, emulator: () => emuNode, phone: () => phNode,
  runner: () => runnerNode, docker: () => dockerNode};
const NODE_SET = {nodes: v => { nodesPick = v; }, storage: v => { storageNode = v; }, nginx: v => { nginxNode = v; },
  toolchains: v => { tcNode = v; }, emulator: v => { emuNode = v; }, phone: v => { phNode = v; },
  runner: v => { runnerNode = v; }, docker: v => { dockerNode = v; }};

// A move inside a page (a notebook view, a wiki page) is a history entry,
// so Back returns to where it was (R256 step 3): the draw replaces the
// address as it always does, and the one before is put back and the new
// one pushed after it.
function navPush(fn){
  const was = location.hash;
  fn();
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was){ history.replaceState(null, "", was || location.pathname + location.search); history.pushState(null, "", to); }
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
    const page = v === "wiki" ? n?.wikiPage?.() || "" : "";
    return "#/projects/" + encodeURIComponent(t.arg) + (v ? "/" + (v === "briefing" ? "overview" : v) : "")
      + (page ? "/" + encodeURIComponent(page) : "");
  }
  if (!isToolKind(t.kind)) return "";
  // The Notifications page is on no group: the bell's See all opens it.
  if (t.kind === "notices") return "#/notifications";
  // Help names the doc on show (R258), so a link to one lands on it.
  if (t.kind === "help") return "#/help" + (helpCur && helpCur !== helpIndex?.home ? "/" + encodeURIComponent(helpCur) : "");
  const g = groupOf(t.kind);
  if (!g) return "";
  const node = NODE_PICKED[t.kind]?.() || "";
  return ((g.tools || []).length > 1 ? `#/${g.key}/${t.kind}` : `#/${g.key}`) + (node ? "/" + encodeURIComponent(node) : "");
}

// Open what an address names; nothing happens for one that names nothing.
function openRoute(hash){
  const m = /^#\/([a-z]+)(?:\/([^/]+))?(?:\/([^/]+))?(?:\/([^/]+))?/.exec(hash || "");
  if (!m) return false;
  const [, key, a, b, c] = m;
  if (key === "projects" && a && !RAIL[1].tools.some(([k]) => k === a)){
    const name = decodeURIComponent(a);
    if (!(state?.projects || []).some(p => p.name === name)) return false;
    railWant = "projects";
    const v = b ? decodeURIComponent(b) : "";
    openNotebook(name, v ? (v === "overview" ? "briefing" : v) : undefined);
    if (v === "wiki" && c) notebooks.get(name)?.wikiAt?.(decodeURIComponent(c));
    return true;
  }
  if (key === "notifications"){ openNotices(); return true; }
  if (key === "help"){
    railWant = "help";
    const doc = a ? decodeURIComponent(a) : helpIndex?.home || "";
    if (doc && doc !== helpCur){ helpCur = doc; helpQ = ""; helpHits = null; helpRev++; }
    openHelp();
    if (helpIndex && helpCur) helpRead(helpCur);
    return true;
  }
  const g = RAIL.find(x => x.key === key);
  if (!g) return false;
  const multi = (g.tools || []).length > 1;
  const kind = railTool(g, a);
  if (!kind) return false;
  railWant = key;
  // The node the address names, set before the page draws (R256 step 3).
  const node = multi ? b : a;
  if (node && NODE_SET[kind]) NODE_SET[kind](decodeURIComponent(node));
  OPENERS[kind]?.();
  return true;
}

// The address follows the page on show (render calls this): replaced, not
// pushed, so a poll's redraw is not a history entry; a rail press pushes.
function shellSync(){
  const to = routeOf(tabOf(panes[0]));
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
  bar.querySelectorAll("[data-subnav]").forEach(b => b.onclick = () => {
    const g = groupOf(b.dataset.subnav);
    if (g) railGo(g.key, b.dataset.subnav);
  });
}

// ---- search: jump to a page, a project, a container or a node ---------------

// Rows: [label, where, go]. Pages by name, projects by the name they are
// shown under, nodes from the list once it has landed, containers from the
// Docker tab's last answer.
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
  for (const d of dockerList?.instances || [])
    rows.push([d.name || d.instance, `container on ${dockerList?.node_name || "its node"}`, () => { railGo("containers"); }]);
  const hit = rows.filter(([label]) => label.toLowerCase().includes(needle));
  hit.sort((a, b) => a[0].toLowerCase().indexOf(needle) - b[0].toLowerCase().indexOf(needle));
  return hit.slice(0, 8);
}
let jumpRows = [];
function drawJump(){
  const inp = $("jump"), list = $("jumpList");
  if (!inp || !list) return;
  jumpRows = jumpItems(inp.value);
  list.hidden = !jumpRows.length;
  list.innerHTML = jumpRows.map(([label, where], i) =>
    `<button type="button" class="jrow${i === 0 ? " on" : ""}" data-jump="${i}" role="option"><span class="jl">${esc(label)}</span><span class="jw">${esc(where)}</span></button>`).join("");
  list.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => jumpGo(Number(b.dataset.jump)));
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
  inp.oninput = drawJump;
  inp.onfocus = () => { if (nodesList === null) loadNodes().then(drawJump); drawJump(); };
  inp.onkeydown = e => {
    if (e.key === "Enter"){ e.preventDefault(); jumpGo(0); }
    else if (e.key === "Escape"){ inp.value = ""; list.hidden = true; inp.blur(); }
  };
  document.addEventListener("click", e => { if (!e.target.closest(".jump")) list.hidden = true; });
}
