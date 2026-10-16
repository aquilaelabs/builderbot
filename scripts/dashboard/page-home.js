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
    const j = await (await fetch("/api/home" + (light ? "?light=1" : ""))).json();
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

// The updates due across the install: each toolchain behind on a node, an
// image or nginx behind, an agent behind. A move (relocate) is not an
// update, and a CI run has its own tile.
function homeUpdates(){
  return (state?.attention || []).reduce((n, a) =>
    a.kind === "relocate" ? n : n + (a.kind === "toolchain" ? (a.tools || []).length || 1 : 1), 0);
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
      <span class="tv">${esc(String(t.value ?? "–"))}</span>
      <span class="tl">${esc(t.label)}</span>
      ${t.sub ? `<span class="ts${t.subTone ? " " + esc(t.subTone) : ""}">${esc(t.sub)}</span>` : ""}
    </a>`).join("")}</div></div>`;
}

function homeJobsHtml(){
  const last = homeData?.jobs?.last || [];
  if (!last.length) return `<div class="hnone">no jobs yet</div>`;
  const names = homeData.jobs.nodes || {};
  return last.map(j => `<button type="button" class="row hjob" data-hjob="${esc(j.id)}">
      <span class="grow"><span class="name">${jobTitle(j)} ${jobStatePill(j)}</span>
        <span class="sub">${esc(names[j.node] || j.node || "")}${j.node ? " · " : ""}${esc(ago(j.ended || j.started || j.queued))}</span></span>
    </button>`).join("");
}

function homeGlanceHtml(){
  const pinned = (state?.projects || []).filter(p => p.pinned);
  if (!pinned.length) return `<div class="hnone">no project is pinned: a project's menu on the Projects page pins it here</div>`;
  return `<div class="hglance">${pinned.map(p => {
    const pc = colorAttrs(p.prefs?.color);
    return `<div class="hproj${pc.cls}"${pc.style}>
      <button type="button" class="name link" data-hproj="${esc(p.name)}">${esc(p.label || p.name)}</button>
      <div class="pcfacts">${p.git ? `git: ${esc(p.git)}` : ""}</div>
      ${projectState(p)}
      ${projectNote(p)}
    </div>`;
  }).join("")}</div>`;
}

function renderHomeInto(i){
  const d = docSurface(i, "home");
  if (!d) return;
  if (homeData === null){
    d.list.innerHTML = `${skel("home")}`;
    if (!homeFetching) homeOpen();
    return;
  }
  const needs = needsRows(), hidden = state?.bell_hidden || 0;
  d.setFoot(`A tile opens its page; a row opens what it is about.`);
  // Painted only when it changed: Home redraws on every poll (its rows are
  // the poll's), and an unchanged draw keeps a pointer's hover and a fold.
  if (!paint(d.list, (homeData.error ? `<div class="hint bad">${esc(homeData.error)}</div>` : "")
    + homeTilesHtml(homeTiles())
    + `<div class="field"><div class="homegrid">
        <section class="hcard"><h3>Attention</h3>${needs.length ? needs.join("")
          : `<div class="hnone">nothing needs attention</div>`}${hidden
          ? `<div class="bfootbar"><span>${hidden} update${hidden === 1 ? "" : "s"} dismissed</span>
              <button type="button" data-brestore>Show again</button></div>` : ""}</section>
        <section class="hcard"><h3>Last jobs</h3>${homeJobsHtml()}</section>
      </div></div>
      <div class="field"><section class="hsect"><h3>Projects at a glance</h3>${homeGlanceHtml()}</section></div>`)) return;
  const root = d.list;
  root.querySelectorAll('[data-htile="sessions"]').forEach(a => a.onclick = e => { e.preventDefault(); railGo("sessions"); });
  // The CI tile's address opens the Git view; its CI section opens with it.
  root.querySelectorAll('[data-htile="ci"]').forEach(a => a.onclick = () => { sectOpen["git:ci"] = true; });
  root.querySelectorAll("[data-hjob]").forEach(b => b.onclick = () => openJob(b.dataset.hjob));
  root.querySelectorAll("[data-hproj]").forEach(b => b.onclick = () => openNotebook(b.dataset.hproj));
  wireNeeds(root);
}
