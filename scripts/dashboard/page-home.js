// Home (R218 step 5, the design's the-dashboard/home rule): the landing page
// and the one single-screen view. A row of tiles, each a number across the
// whole install and a link into the page that holds it; under them
// Attention (the bell's rows, put away there as on the bell) and the last
// ten jobs, side by side at a desk and stacked on a phone; under those, the
// pinned projects at a glance. A glance, not a place to act: a tile opens
// its page, a row opens what it is about, and nothing here is a setting.
//
// What the status poll carries (sessions, updates, CI) is counted here;
// the rest is /api/home (home.py), read whole on open, and light (the
// queue and the node counts, the containers kept) when the jobs token
// moves; never on a timer of its own, and not on the nodes token, which
// moves with every node's check-in and would make Home a poll.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

let homeData = null;             // /api/home's last answer, or null before the first
let homeRev = 0;                 // bumped when it lands, so the page repaints
let homeFetching = false;
let homeAgain = null;            // a read asked while one was out: null, "light" or "whole"

function openHome(){
  openTab({kind: "home", arg: "__home", label: "Home"});
}
// Opening: the light read first, so the page draws at once from the queue
// and the node counts, and the whole one behind it for the containers,
// which waits on every docker node (up to home.CONTAINER_WAIT_S).
function homeOpen(){
  loadHome(true);
  loadHome(false);
}

// One out at a time, and never dropped (as refresh() is): a read asked
// while one is out is remembered, the whole one outranking a light one,
// and asked when that one lands, or the queue's last move went unread.
async function loadHome(light = false){
  if (homeFetching){ homeAgain = homeAgain === "whole" || !light ? "whole" : "light"; return; }
  homeFetching = true;
  try{
    const j = await (await bootFetch("/api/home" + (light ? "?light=1" : ""))).json();
    homeData = j.error ? {error: j.error}
      : light && homeData && !j.containers ? {...j, containers: homeData.containers} : j;
  }catch(e){
    homeData = {error: "could not read Home: " + e};
  }finally{
    homeFetching = false;
  }
  homeRev++;
  drawPanes();
  if (homeAgain){ const whole = homeAgain === "whole"; homeAgain = null; loadHome(!whole); }
}

// The updates due across the install, each thing behind counted once: each
// toolchain behind on a node, each container with a newer image, nginx
// behind, an agent behind. A move (relocate) is not an update, and a CI run
// has its own tile.
function homeUpdates(){
  return (state?.attention || []).reduce((n, a) =>
    a.kind === "relocate" ? n : n + (a.kind === "toolchain" ? (a.tools || []).length || 1
      : a.kind === "image" ? (a.containers || []).length || 1 : 1), 0);
}

// The tiles, each one a press into its page (the home rule: unlike a tab's
// tiles, these are links). One with nothing behind it for this account (a
// machine it may not read) is not drawn.
function homeTiles(){
  const h = homeData || {};
  const sessions = Object.values(state?.claude_where || {}).reduce((n, rows) => n + rows.length, 0);
  const updates = homeUpdates(), red = (state?.ci_red || []).length;
  const jobs = h.jobs || {};
  const c = h.containers;
  return [
    h.nodes ? {key: "nodes", label: "nodes online", value: h.nodes.online, sub: `of ${h.nodes.enrolled} enrolled`,
               tone: h.nodes.online < h.nodes.enrolled ? "warn" : ""} : null,
    c ? {key: "containers", label: "containers running", value: c.unknown === c.nodes && c.nodes ? "–" : c.running,
         sub: `of ${c.all}${c.stale || c.unknown ? ", as last seen" : ""}`}
      // Asked of every docker node, after the rest has drawn.
      : h.nodes ? {key: "containers", label: "containers running", value: "–", sub: "asking the nodes…"} : null,
    // The news here is a failure, not the count running, so the bad tone is
    // on the line that says it rather than on a red zero.
    {key: "jobs", label: "jobs running", value: jobs.running ?? "–",
     sub: jobs.failed_today ? `${jobs.failed_today} failed today` : jobs.waiting ? `${jobs.waiting} waiting` : "none failed today",
     subTone: jobs.failed_today ? "bad" : ""},
    {key: "sessions", label: "sessions open", value: sessions},
    {key: "updates", label: "updates due", value: updates, tone: updates ? "warn" : ""},
    {key: "ci", label: "CI red", value: red, tone: red ? "bad" : "", sub: red === 1 ? projLabel(state.ci_red[0].project) : ""},
  ].filter(Boolean);
}

// Each tile is a link to the address of the page that holds its number,
// opened the way any address is (openRoute, on the hash changing); Sessions
// is a panel, with no address, and opens it on the press.
function homeHref(key){
  const c = (state?.ci_red || [])[0];
  return {nodes: "#/machines/nodes", containers: "#/containers", jobs: "#/jobs", updates: "#/build/toolchains",
          ci: c ? `#/projects/${encodeURIComponent(c.project)}/git` : "#/projects", sessions: "#"}[key] || "#";
}
function homeTilesHtml(tiles){
  return `<div class="field"><div class="tiles hometiles">${tiles.map(t => `
    <a class="tile link${t.tone ? " " + esc(t.tone) : ""}" href="${esc(homeHref(t.key))}" data-htile="${esc(t.key)}">
      <span class="tv">${t.wait ? skv(1.4) : esc(String(t.value ?? "–"))}</span>
      <span class="tl">${esc(t.label)}</span>
      ${t.sub ? `<span class="ts${t.subTone ? " " + esc(t.subTone) : ""}">${esc(t.sub)}</span>` : ""}
    </a>`).join("")}</div></div>`;
}

function homeJobsHtml(){
  const last = homeData?.jobs?.last || [];
  if (!last.length) return `<div class="empty">no jobs yet</div>`;
  const names = homeData.jobs.nodes || {};
  return last.map(j => `<button type="button" class="row hjob" data-hjob="${esc(j.id)}">
      <span class="grow"><span class="name">${jobTitle(j)} ${jobStatePill(j)}</span>
        <span class="sub">${esc(names[j.node] || j.node || "")}${j.node ? " · " : ""}${esc(ago(j.ended || j.started || j.queued))}</span></span>
    </button>`).join("");
}

function homeGlanceHtml(){
  // Not an archived one (the operator, 18 Oct), pinned or not.
  const pinned = (state?.projects || []).filter(p => p.pinned && !p.locked);
  if (!pinned.length) return `<div class="empty">no project is pinned: a project's menu on the Projects page pins it here</div>`;
  // In groups, in the Projects page's order, each group's name over its
  // cards (R273): the page this glances at is sorted so.
  const card = p => {
    const pc = colorAttrs(p.color);
    return `<div class="hproj${pc.cls}"${pc.style}>
      <button type="button" class="name link" data-hproj="${esc(p.name)}">${esc(p.label || p.name)}</button>
      <div class="pcfacts">${projFacts(p)}</div>
      ${projectState(p)}
      ${projectNote(p)}
    </div>`;
  };
  return byProjectGroup([...pinned].sort(byProjectName)).map(({group, list}) =>
    `${group ? `<div class="hgroup">${esc(group)} <span class="dim">${list.length}</span></div>` : ""}<div class="hglance">${list.map(card).join("")}</div>`).join("");
}

// Getting started (R267): what is left of first run's four once Finish is
// pressed, each with its own way there, until all are done or it is put
// away; read from setupSteps, the setup page's own reading, so the two
// never disagree. Put away is this browser's, which is all it needs.
let homeStartHidden = (() => { try{ return localStorage.getItem("bb.gsHidden") === "1"; }catch(e){ return false; } })();
// Whether the card is up and its node steps read the nodes list: read once,
// a list from before the nodes dialed in again after a restart said there
// was no node and no Claude Code until a reload (19 Oct).
function homeStartReadsNodes(){
  return !homeStartHidden && !setupNeeded() && !!state?.can?.admin && railAllows("nodes")
    && !(nodesList && setupSteps().claude);
}
function homeStartHtml(){
  // First run's continuation, so the owner's and an administrator's: a
  // person without the role may have no New project to press.
  if (homeStartHidden || setupNeeded() || !state?.can?.admin) return "";
  const s = setupSteps(), canNodes = railAllows("nodes");
  // What the card cannot read yet it does not claim: the nodes list comes
  // once, with the Claude step's state.
  if (canNodes && nodesList === null) return "";
  const steps = [
    canNodes ? ["Your first node", !!s.node, `<button type="button" data-hstart="node">Nodes page</button>`] : null,
    ["Your name and email", s.git, `<button type="button" data-hstart="git">Profile</button>`],
    canNodes ? ["Claude Code on your node", !!s.claude, `<button type="button" data-hstart="claude"${s.node ? "" : " disabled"}>Toolchains</button>`] : null,
    ["A first project", s.project, `<button type="button" data-hstart="project">New project</button>`],
  ].filter(Boolean);
  const left = steps.filter(x => !x[1]).length;
  if (!left) return "";
  return `<div class="field"><section class="hcard hstart"><h3>Getting started<span class="sst">${steps.length - left} of ${steps.length}</span></h3>
    ${steps.map(([t, done, act]) => `<div class="hsrow${done ? " done" : ""}"><span class="setnum">${done ? "✓" : ""}</span><span class="grow">${esc(t)}</span>${done ? "" : act}</div>`).join("")}
    <div class="bfootbar"><span class="sp"></span><button type="button" data-hstart="hide">Put away</button></div></section></div>`;
}

// Attention, Last jobs and the pinned projects: the cards under the tiles,
// with Last jobs' rows handed in (its own, or the shapes of them on the way).
function homeCards(jobs){
  const needs = needsRows(), hidden = state?.bell_hidden || 0;
  return `${homeStartHtml()}<div class="field"><div class="homegrid">
        <section class="hcard"><h3>Attention</h3>${needs.length ? needs.join("")
          : `<div class="empty">nothing needs attention</div>`}${hidden
          ? `<div class="bfootbar"><span>${hidden} update${hidden === 1 ? "" : "s"} dismissed</span>
              <button type="button" data-brestore>Show again</button></div>` : ""}</section>
        <section class="hcard"><h3>Last jobs</h3>${jobs}</section>
      </div></div>
      <div class="field"><section class="hsect"><h3>Projects at a glance</h3>${homeGlanceHtml()}</section></div>`;
}

function renderHomeInto(i){
  const d = docSurface(i, "home");
  if (!d) return;
  if (homeData === null){
    // Its template while /api/home is on its way (R218 step 16): the poll
    // already holds Attention, the pinned projects and three of the tiles,
    // so only the node, container and job numbers and Last jobs wait.
    const tiles = homeTiles().map(t => t.key === "jobs" ? {...t, wait: true, sub: ""} : t);
    if (railAllows("nodes")) tiles.unshift({key: "nodes", label: "nodes online", wait: true},
                                           {key: "containers", label: "containers running", wait: true});
    d.list.innerHTML = skTpl(homeTilesHtml(tiles) + homeCards(skRows(3)), {live: true});
    wireNeeds(d.list);
    if (!homeFetching) homeOpen();
    return;
  }
  // Painted only when it changed: Home redraws on every poll (its rows are
  // the poll's), and an unchanged draw keeps a pointer's hover and a fold.
  if (!paint(d.list, (homeData.error ? `<div class="hint bad">${esc(homeData.error)}</div>` : "")
    + homeTilesHtml(homeTiles()) + homeCards(homeJobsHtml()))) return;
  const root = d.list;
  root.querySelectorAll('[data-htile="sessions"]').forEach(a => a.onclick = e => { e.preventDefault(); railGo("sessions"); });
  // The CI tile's address opens the Git view; its CI section opens with it.
  root.querySelectorAll('[data-htile="ci"]').forEach(a => a.onclick = () => { sectOpen["git:ci"] = true; });
  root.querySelectorAll("[data-hjob]").forEach(b => b.onclick = () => openJob(b.dataset.hjob));
  root.querySelectorAll("[data-hproj]").forEach(b => b.onclick = () => openNotebook(b.dataset.hproj));
  root.querySelectorAll(".hproj").forEach(c => c.onclick = e => {
    const name = c.querySelector("[data-hproj]")?.dataset.hproj;
    if (name && cardPress(e)) openNotebook(name);
  });
  root.querySelectorAll("[data-hstart]").forEach(b => b.onclick = () => {
    const k = b.dataset.hstart, s = setupSteps();
    if (k === "node") railGo("machines");
    else if (k === "git") openProfileTab();
    else if (k === "claude" && s.node) openToolchainsOn(s.node.id);
    else if (k === "project") openNewProject();
    else if (k === "hide"){ homeStartHidden = true; try{ localStorage.setItem("bb.gsHidden", "1"); }catch(e){ /* private */ } drawPanes(); }
  });
  // The Claude step's state is the nodes list's, read on open and again
  // when the nodes move (index.html's watch).
  if (homeStartReadsNodes() && (nodesList === null || nodesStale)) loadNodes().then(() => drawPanes());
  wireNeeds(root);
}
