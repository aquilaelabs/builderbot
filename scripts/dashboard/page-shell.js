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
};

// The nine groups, in the rail's order (the design's rail rule). A group's
// tools are the tab kinds it holds, the first the one its button opens; a
// group with several draws them as the page's sub-nav. Home opens the
// Projects page until Home is built (R218 step 5). Sessions is the panel
// the pane's Sessions button opens until the dock (step 4).
const RAIL = [
  {key: "home", label: "Home", icon: "home", tools: [["projects", "Projects"]]},
  {key: "projects", label: "Projects", icon: "projects", tools: [["projects", "Projects"], ["findings", "Analysis"]]},
  {key: "containers", label: "Containers", icon: "docker", tools: [["docker", "Containers"]]},
  {key: "machines", label: "Machines", icon: "nodes", tools: [["nodes", "Nodes"], ["storage", "Storage"], ["nginx", "nginx"]]},
  {key: "build", label: "Build", icon: "toolchains", tools: [["toolchains", "Toolchains"], ["emulator", "Emulator"], ["phone", "Phone"], ["runner", "CI runner"]]},
  {key: "jobs", label: "Jobs", icon: "jobs", tools: [["jobs", "Jobs"]]},
  {key: "sessions", label: "Sessions", icon: "sessions", panel: "sessions"},
  {key: "people", label: "People", icon: "people", tools: [["users", "Users"], ["roles", "Roles"]], admin: true},
  {key: "settings", label: "Settings", icon: "settings", tools: [["settings", "Controller"], ["profile", "Profile"]]},
];
// The five on a phone's bar; the rest are under More.
const RAIL_PHONE = ["home", "projects", "containers", "jobs"];

// A tool kind is a page: it leaves the strip and lives on the rail.
function isToolKind(kind){ return kind !== "term" && kind !== "notebook"; }

// The group a tab kind is a page of: the first group that lists it, Home
// aside (Home shares the Projects page).
function groupOf(kind){
  return RAIL.find(g => g.key !== "home" && (g.tools || []).some(([k]) => k === kind)) || null;
}

// Which tool kinds this account may open, read off the buttons the page
// already ghosts or hides by grant (the Tools and Administration cards): a
// rail item for something a grant forbids is not drawn.
function railAllows(kind){
  const btn = {projects: null, profile: null, settings: "bSettings", users: "bUsers", roles: "bRoles",
               docker: "bDocker", nodes: "bNodes", storage: "bStorage", nginx: "bNginx", toolchains: "bToolchains",
               emulator: "bEmulator", phone: "bPhone", runner: "bRunner", jobs: "bJobs", findings: "bFindings"}[kind];
  if (btn === null) return true;
  const b = $(btn);
  if (!b) return false;
  if (b.closest("#cardAdmin")?.hidden) return false;
  // Hidden is not offered; disabled is offered dead, with the card's reason.
  return !b.hidden && b.style.display !== "none";
}
function railGroups(){
  return RAIL.filter(g => g.panel || (g.tools || []).some(([k]) => railAllows(k)));
}

// What the rail lights: the group somebody pressed, while its page is the
// one on show; else the group of the page on show.
let railWant = "";
function railOn(){
  const t = tabOf(panes[active]);
  const kind = t?.kind || "";
  if (railWant){
    const g = RAIL.find(x => x.key === railWant);
    if (g && (g.panel || (g.tools || []).some(([k]) => k === kind))) return railWant;
    railWant = "";
  }
  return groupOf(kind)?.key || (kind === "notebook" ? "projects" : "");
}

// Open a group: its first tool as a page (or, for Home, the Projects page),
// or its panel. A press is a navigation, so the address is pushed.
const OPENERS = {
  projects: () => openProjectsTab(), findings: () => openFindingsTab(), docker: () => openDocker(),
  nodes: () => openNodesTab(), storage: () => openStorageTab(), nginx: () => openNginxTab(),
  toolchains: () => openToolchains(), emulator: () => openEmulator(), phone: () => openPhoneTab(),
  runner: () => openRunnerTab(), jobs: () => openJobsTab(), users: () => openUsersTab(),
  roles: () => openRolesTab(), settings: () => openSettingsTab(), profile: () => openProfileTab(),
};
function railGo(key, tool){
  const g = RAIL.find(x => x.key === key);
  if (!g) return;
  railWant = key;
  if (g.panel){ mobPanel(g.panel); drawRail(); return; }
  const kind = tool && (g.tools || []).some(([k]) => k === tool) ? tool : g.tools[0][0];
  if (!railAllows(kind)) return;
  const was = location.hash;
  OPENERS[kind]?.();
  const to = routeOf(tabOf(panes[active]));
  if (to && to !== was) history.pushState(null, "", to);
}

// The address a tab is reached at: #/group, #/group/tool, #/projects/NAME.
// A terminal has none.
function routeOf(t){
  if (!t) return "";
  if (t.kind === "notebook") return "#/projects/" + encodeURIComponent(t.arg);
  if (!isToolKind(t.kind)) return "";
  const g = railWant === "home" && t.kind === "projects" ? RAIL[0] : groupOf(t.kind);
  if (!g) return "";
  return (g.tools || []).length > 1 ? `#/${g.key}/${t.kind}` : `#/${g.key}`;
}

// Open what an address names; nothing happens for one that names nothing.
function openRoute(hash){
  const m = /^#\/([a-z]+)(?:\/([^/]+))?(?:\/([^/]+))?/.exec(hash || "");
  if (!m) return false;
  const [, key, a, b] = m;
  if (key === "projects" && a && !RAIL[1].tools.some(([k]) => k === a)){
    const name = decodeURIComponent(a);
    if (!(state?.projects || []).some(p => p.name === name)) return false;
    railWant = "projects";
    openNotebook(name, b ? decodeURIComponent(b) : undefined);
    return true;
  }
  const g = RAIL.find(x => x.key === key);
  if (!g || g.panel) return false;
  const kind = a && (g.tools || []).some(([k]) => k === a) ? a : g.tools[0][0];
  if (!railAllows(kind)) return false;
  railWant = key;
  OPENERS[kind]?.();
  return true;
}

// The address follows the page on show (render calls this): replaced, not
// pushed, so a poll's redraw is not a history entry; a rail press pushes.
function shellSync(){
  const to = routeOf(tabOf(panes[active]));
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
  if (h && h !== "#/" && h !== routeOf(tabOf(panes[active]))) openRoute(h);
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
  if (rail.innerHTML !== html){
    rail.innerHTML = html;
    rail.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => { railGo(b.dataset.rail); if (isPhone()) setView(phoneViewFor(b.dataset.rail)); });
  }
  const five = groups.filter(g => RAIL_PHONE.includes(g.key));
  const rest = groups.filter(g => !RAIL_PHONE.includes(g.key));
  const moreOn = rest.some(g => g.key === on);
  const bhtml = five.map(item).join("") + (rest.length
    ? `<button type="button" class="ritem${moreOn ? " on" : ""}" data-railmore aria-haspopup="menu" aria-expanded="${railMoreOpen}" aria-label="More">${RAIL_ICONS.more}<span class="rlbl">More</span></button>` : "");
  if (bar.innerHTML !== bhtml){
    bar.innerHTML = bhtml;
    bar.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => { railMoreShow(false); railGo(b.dataset.rail); setView(phoneViewFor(b.dataset.rail)); });
    bar.querySelector("[data-railmore]")?.addEventListener("click", () => railMoreShow(!railMoreOpen));
  }
  const more = $("railmore");
  if (more){
    const mhtml = rest.map(g => `<button type="button" class="ritem${g.key === on ? " on" : ""}" data-rail="${esc(g.key)}">${
        RAIL_ICONS[g.icon] || TOOL_ICONS[g.icon] || ""}<span class="rlbl">${esc(g.label)}</span></button>`).join("")
      + `<button type="button" class="ritem" data-railtabs>${TOOL_ICONS.notebook}<span class="rlbl">Open tabs</span></button>`;
    if (more.innerHTML !== mhtml){
      more.innerHTML = mhtml;
      more.querySelectorAll("[data-rail]").forEach(b => b.onclick = () => { railMoreShow(false); railGo(b.dataset.rail); setView(phoneViewFor(b.dataset.rail)); });
      more.querySelector("[data-railtabs]").onclick = () => { railMoreShow(false); setView("terminal"); };
    }
  }
}
// On a phone Home and Projects are the dashboard panel (the project cards,
// until step 3 makes the Projects page); every other page is the pane.
function phoneViewFor(key){ return key === "home" || key === "projects" ? "dash" : "terminal"; }
let railMoreOpen = false;
function railMoreShow(on){
  railMoreOpen = !!on;
  const m = $("railmore"), b = $("railbar")?.querySelector("[data-railmore]");
  if (m) m.hidden = !railMoreOpen;
  if (b) b.setAttribute("aria-expanded", String(railMoreOpen));
}

// The pane's bar for a page: the group's tools as a sub-nav when it has
// several, else the page's name; a page has no close, the rail is how you
// leave it (a split pane keeps its own close).
function shellBar(t, i){
  const g = groupOf(t.kind);
  const closeBtn = isSplit() ? `<span class="x" data-cp="${i}" title="close this pane">✕</span>` : "";
  if (!g || (g.tools || []).length < 2)
    return `<span class="pgname">${esc(g ? g.tools[0][1] : tabLabel(t))}</span>${closeBtn}`;
  return `<span class="subnav pseg" role="tablist" aria-label="${esc(g.label)}">${g.tools.filter(([k]) => railAllows(k)).map(([k, label]) =>
      `<button type="button" role="tab" aria-selected="${k === t.kind}" class="${k === t.kind ? "on" : ""}" data-subnav="${esc(k)}">${esc(label)}</button>`).join("")}</span>${closeBtn}`;
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
    if (g.panel){ rows.push([g.label, "page", () => railGo(g.key)]); continue; }
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
  if (isPhone()) setView(phoneViewFor(railOn()));
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
