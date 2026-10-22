"use strict";
// ---- the tour (R94) --------------------------------------------------------
// The first time an account opens each page, a few steps about it, each a
// card beside the part of the page it is about, with Back, Next and Done;
// Skip tour ends it, and its box skips the tour on every page. Which pages
// an account has toured is the account's, kept on the server with its theme
// (users.own_prefs), so a phone does not start over; Show the tours again on
// Profile and in About clears it.

// Each page's steps: `at` the part of the page it is about (the first of
// the selectors on screen, under the page's own pane), none for a step about
// the page as a whole. A step whose part is not on screen is left out.
const TOUR_PANE = "#pane0";
const TOUR_BAR = `${TOUR_PANE} .docbarrow:not([hidden]), ${TOUR_PANE} .vbar`;
const TOUR_SUB = `${TOUR_PANE} .bar .pseg`;
const TOUR_FIRST = `${TOUR_PANE} .dmcard, ${TOUR_PANE} details.sect, ${TOUR_PANE} .doclist > .row, ${TOUR_PANE} .doclist .row`;
const TOUR_STEPS = {
  home: [
    {say: "Welcome to BuilderBot. Home is what the whole install is doing at a glance: what is running, what failed, and what wants your attention."},
    {at: "#rail, .railbar", say: "Every page is here, grouped. A group with several tools opens on the first and carries the rest along its top."},
    {at: "#jump", say: "Search jumps to a page, a project, a container or a node by name. Enter opens the first match."},
    {at: "#bBell", say: "The bell holds what needs a person: updates due, failures, and anything a Claude session is asking you to allow."},
    {at: `${TOUR_PANE} .tiles, ${TOUR_PANE} .hometiles, ${TOUR_PANE} .stattiles`, say: "Each number opens the page that holds it."},
    {at: "#pane1 .bar, .dockline", say: "The dock at the foot keeps the chat and your terminals and Claude sessions, whichever page you are on. Pull it up to work in one."},
  ],
  projects: [
    {say: "Every project you work on. A project is a git repository with its own notebook: a roadmap, bugs, tests, its containers and VMs."},
    {at: TOUR_BAR, say: "Search and the view switch are here, and New project at the right."},
    {at: `${TOUR_PANE} .pcard`, say: "A project's card: its branch, its sessions, and Start Claude. Its name opens the notebook."},
  ],
  notebook: [
    {say: "A project's notebook: everything about it in one place, shared by the people and the Claude sessions working on it."},
    {at: `${TOUR_PANE} .nbtabs .nbgroups`, say: "Five groups: Overview (with your sessions here, what a session may do, and the settings), Plan (the roadmap and bugs), Code, Ship (artifacts, containers and VMs) and Docs. Each opens its views in the row under it."},
    {at: `${TOUR_PANE} .phead, ${TOUR_PANE} .bar.proj`, say: "Start Claude opens a session on this project; Shell a terminal in it. The menu holds its settings, its link and more."},
  ],
  findings: [
    {say: "Analysis is what the linters and the code map found across your projects, worst first."},
    {at: TOUR_BAR, say: "Narrow it by project or by kind here."},
  ],
  toolchains: [
    {say: "Toolchains are the SDKs and tools a node has for builds, tests and sessions: Android, Flutter, Node and the rest, Claude Code among them."},
    {at: TOUR_BAR, say: "Pick the node here. Install and Remove act on what you tick; Check for updates reads what is newer."},
    {at: TOUR_FIRST, say: "Each toolchain says what is installed and whether a newer one is out. Some ask you to accept a license first, and that is always yours to accept."},
  ],
  emulator: [
    {say: "The Android emulator on a node: the system images it holds and the virtual devices made from them."},
    {at: TOUR_BAR, say: "Pick the node here. A device starts from its row, and a session drives it with bb emu."},
  ],
  phone: [
    {say: "A real Android phone, lent to a project by plugging it into a node: a session can install its app and look at the screen, and every command waits for the phone's owner to allow it unless they trust it."},
  ],
  runner: [
    {say: "CI runners: a node registered with GitHub or Gitea so your project's workflows run on it."},
    {at: TOUR_BAR, say: "Pick the node here, and add a runner with a token from the forge."},
  ],
  apps: [
    {say: "Apps are BuilderBot's own companions you install: the phone app, the editor extension and the Windows companion, each its newest release."},
  ],
  docker: [
    {say: "Containers: every project's containers on a node, grouped by project, with Up, Down, Rebuild and a Shell in the dock."},
    {at: TOUR_SUB, say: "Containers, VMs and nginx are the three tools of this group."},
    {at: TOUR_BAR, say: "Pick the node, search, and switch between cards and a list. New container and Check for updates sit at the right."},
    // Its rows by name: TOUR_FIRST matched an empty page's own notice, so
    // the example never came (the operator, 21 Oct, on a phone).
    {at: `${TOUR_PANE} .dmtab .dmcard, ${TOUR_PANE} .dmtab > .tbl`, sample: () => tourSampleCard(), say: "A project's card: each container with its state, where it answers, and its buttons. The menu holds the rest, Remove last."},
  ],
  vms: [
    {say: "VMs: a project's virtual machines on the nodes with VM host installed, made from the cloud images of a dozen Linux systems."},
    {at: TOUR_BAR, say: "New VM is here. A Claude session can make one too, with bb vm new, where the project's Make VMs setting allows it."},
    {at: `${TOUR_PANE} .vmtab [data-vm-key]`, sample: () => vmGroupsHtml([{key: "example/db", project: "example", name: "db", state: "running",
      os_name: "Debian 13", node_name: "your-node", vcpus: 2, mem_mb: 2048, disk_gb: 20, ip: "10.232.0.12", user: "builder",
      snapshots: ["clean"], screen: true}]),
     say: "Each VM says its state and how to ssh in. Snapshot keeps its state under a name, and Revert goes back to it."},
  ],
  nginx: [
    {say: "nginx: BuilderBot's own reverse proxy on a node, putting your containers behind hostnames and certificates."},
    {at: TOUR_FIRST, say: "Hostnames, routes, certificates and the image each have a section. A route sends a hostname to a port a container publishes."},
  ],
  settings: [
    {say: "The controller's settings: how this BuilderBot itself behaves, the room it keeps on the nodes among them. Each section says what it changes."},
    {at: TOUR_FIRST, say: "A section's changes are saved with its own Save, never another's."},
  ],
  nodes: [
    {say: "Nodes are the machines your builds, tests, containers, VMs and Claude sessions run on. The controller itself runs none of them."},
    {at: TOUR_BAR, say: "Pick a node here. Enroll node makes the script that adds a machine."},
    {at: TOUR_FIRST, say: "A node's sections: its health, the projects on it, its sessions, its features, and the advanced verbs at the end."},
  ],
  storage: [
    {say: "Storage: what every node's disks hold, by project and by kind, and where the room is going."},
  ],
  sessions: [
    {say: "Every Claude session and terminal open, on every node: who is working where, and whether each is busy, waiting or asking."},
  ],
  jobs: [
    {say: "Jobs: every build, test, install and system job sent to a node, with its log."},
    {at: TOUR_BAR, say: "Narrow it to what is running, failed or waiting here."},
  ],
  users: [
    {say: "Users: the accounts that sign in here, and the roles each holds."},
    {at: TOUR_BAR, say: "Add user is here. A new account holds no role until you give it one."},
  ],
  roles: [
    {say: "Roles: what an account may read and change, area by area, on its projects or everywhere."},
  ],
  profile: [
    {say: "Your profile: your name and email for commits, your password, your theme, and the devices signed in as you."},
  ],
  help: [
    {say: "BuilderBot's own documentation, with a search across it."},
  ],
};

let tourKind = "", tourI = 0, tourSteps = [];
const tourAsked = new Set();

function tourSeen(){ return new Set(state?.tour?.seen || []); }

// Called after the panes are drawn: the page in front, toured once.
function tourSoon(kind){
  // A step's example, put back after a draw of the page wiped it.
  if (tourKind && tourSteps[tourI]?.sample && !$("tourSample") && tourKind === kind) return tourDraw();
  // BB_NO_TOUR: a page the test harness or the README's pictures opened.
  if (!kind || !TOUR_STEPS[kind] || !state?.me || state?.tour?.off || tourKind || window.BB_NO_TOUR) return;
  if (tourSeen().has(kind) || tourAsked.has(kind)) return;
  // The welcome panel first, and no tour over another dialog: the next draw
  // asks again once it is closed.
  if (document.querySelector(".modal:not([hidden])")) return;
  // ...nor over a placeholder: the page's own draw, once its data has
  // landed, asks again (the operator, 21 Oct: the tour pointed at shimmer).
  if (tourLoading()) return;
  // ...nor over the setup page, which is the whole page until Finish: a new
  // owner's first look was Home's tour over its four steps.
  if (setupNeeded()) return;
  tourAsked.add(kind);
  setTimeout(() => tourStart(kind), 700);
}

// The part a step is about: its selectors tried in the order written (the
// page's own order would pick a node's whole row over its first section),
// the first that is on screen.
function tourTarget(sel){
  if (!sel) return null;
  const shown = e => { const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
  for (const one of sel.split(",")){
    const hit = [...document.querySelectorAll(one.trim())].find(shown);
    if (hit) return hit;
  }
  return null;
}

// Whether the page in front is still its placeholder, or the page is still
// booting: a boot draws the saved front tab before it lands on Home, and a
// tour asked for in between toured Projects instead.
// Only a placeholder that shows counts: the Containers page keeps one in
// each section it reads when opened, and a tour that waited for those never
// came (B216).
function tourLoading(){
  return document.body.classList.contains("booting")
    || [...document.querySelectorAll(".doc.on .skel, .doc.on .loading, .doc.on .sk-b")].some(e => e.checkVisibility());
}
function tourStart(kind){
  // Still the page in front, and nothing over it: a tour asked for a page
  // left meanwhile waits for that page's next visit.
  if (tourKind || document.querySelector(".modal:not([hidden])") || setupNeeded() || tourLoading() || tabOf(panes[0])?.kind !== kind){
    tourAsked.delete(kind);
    return;
  }
  // A step about a row the page has none of yet keeps its place with an
  // example of one (the operator, 21 Oct): an empty Containers or VMs page.
  tourSteps = TOUR_STEPS[kind].filter(s => !s.at || s.sample || tourTarget(s.at));
  if (!tourSteps.length) return;
  tourKind = kind;
  tourI = 0;
  let ring = $("tourRing"), card = $("tourCard");
  if (!ring){
    ring = document.createElement("div");
    ring.id = "tourRing"; ring.className = "tourring";
    document.body.appendChild(ring);
    card = document.createElement("div");
    card.id = "tourCard"; card.className = "tourcard";
    card.setAttribute("role", "dialog"); card.setAttribute("aria-live", "polite");
    document.body.appendChild(card);
    window.addEventListener("resize", () => { if (tourKind) tourDraw(); });
    document.addEventListener("keydown", e => {
      if (!tourKind) return;
      if (e.key === "Escape") tourEnd(false);
      else if (e.key === "ArrowRight") tourGo(1);
      else if (e.key === "ArrowLeft") tourGo(-1);
    });
  }
  tourDraw();
}

// An example of what a step is about, put on the page while the step shows
// and taken away after: drawn by the page's own renderer where it has one,
// inert, and marked as an example.
function tourSample(s){
  $("tourSample")?.remove();
  if (!s?.sample || (s.at && tourTarget(s.at))) return null;
  // The page on show's, not the first the pane keeps: after Home, the
  // example went into Home's hidden page and the ring wrapped an empty box
  // over the VMs page (B223).
  const doc = document.querySelector(`${TOUR_PANE} .doc.on .doctab`) || document.querySelector(`${TOUR_PANE} .doctab`);
  if (!doc) return null;
  const box = document.createElement("div");
  box.id = "tourSample"; box.className = "toursample"; box.inert = true;
  box.innerHTML = `<div class="field"><span class="pill note">example</span> <span class="sub">what one looks like once there is one</span></div>${s.sample()}`;
  const bar = doc.querySelector(":scope > .docbarrow, :scope > .vbar");
  if (bar) bar.after(box); else doc.prepend(box);
  return box;
}
function tourSampleCard(){
  return `<section class="dmcard"><div class="field dmgroup" style="--gc:var(--accent)"><b>example</b></div>
    <div class="row stack2"><div class="grow"><div class="dmhead"><div class="dmid">
      <div class="name">web<span class="pill stat dmpill ok live">running</span></div>
      <div class="sub dmorigin">nginx:1.31-alpine<span class="sep"></span>your-node</div>
      <div class="sub dmstate ok">answers at http://your-node:8080/</div></div>
      <div class="actbar dmacts"><button type="button">Shell</button><button type="button">Rebuild</button>
        <span class="more"><button type="button" class="moreb" aria-label="More">⋯</button></span></div></div></div></div></section>`;
}

// A page that redraws itself on its own poll, not through the panes' draw
// (VMs), wiped a step's example and left the ring around where it had been
// (B215): while a step with one shows, a redraw that takes it away puts it
// back and the ring with it.
let tourWatch = null;
function tourKeepSample(on){
  tourWatch?.disconnect();
  tourWatch = null;
  const pane = document.querySelector(TOUR_PANE);
  if (!on || !pane) return;
  let queued = false;
  tourWatch = new MutationObserver(() => {
    if (queued || !tourKind || $("tourSample") || tourTarget(tourSteps[tourI]?.at)) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; if (tourKind && !$("tourSample")) tourDraw(); });
  });
  tourWatch.observe(pane, {childList: true, subtree: true});
}

function tourDraw(){
  const ring = $("tourRing"), card = $("tourCard");
  const s = tourSteps[tourI], last = tourI === tourSteps.length - 1;
  const el = tourSample(s) || tourTarget(s.at);
  tourKeepSample(!!s.sample);
  card.innerHTML = `<div class="tourstep">${tourI + 1} of ${tourSteps.length}</div>
    <div class="toursay">${esc(s.say)}</div>
    <label class="ndcap tourall"><input type="checkbox" id="tourAll"> Skip the tour on every page</label>
    <div class="actbar"><button type="button" id="tourSkip">Skip tour</button><span class="sp"></span>
      ${tourI ? `<button type="button" id="tourBack">Back</button>` : ""}
      <button type="button" class="primary" id="tourNext">${last ? "Done" : "Next"}</button></div>`;
  card.hidden = ring.hidden = false;
  $("tourNext").onclick = () => tourGo(1);
  if ($("tourBack")) $("tourBack").onclick = () => tourGo(-1);
  $("tourSkip").onclick = () => tourEnd($("tourAll").checked);
  ring.hidden = !el;
  if (el){
    el.scrollIntoView({block: "nearest", inline: "nearest"});
    const r = el.getBoundingClientRect(), pad = 4;
    Object.assign(ring.style, {left: `${r.left - pad}px`, top: `${r.top - pad}px`,
                               width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`});
  }
  // A phone's is a sheet from the bottom; a desk's sits beside its part,
  // under it where there is room, over it where there is not, centered
  // when the step is about the whole page.
  card.classList.toggle("sheet", isPhone());
  if (isPhone()) { card.style.left = card.style.top = ""; card.removeAttribute("data-at"); }
  else if (!el) {
    card.style.left = `${Math.max(16, (innerWidth - card.offsetWidth) / 2)}px`;
    card.style.top = `${Math.max(16, (innerHeight - card.offsetHeight) / 3)}px`;
  } else {
    const r = el.getBoundingClientRect(), h = card.offsetHeight, w = card.offsetWidth;
    if (r.bottom + 12 + h < innerHeight){             // under it
      card.style.top = `${r.bottom + 12}px`;
      card.style.left = `${Math.min(Math.max(16, r.left), innerWidth - w - 16)}px`;
    } else if (r.top - h - 12 > 0){                     // over it
      card.style.top = `${r.top - h - 12}px`;
      card.style.left = `${Math.min(Math.max(16, r.left), innerWidth - w - 16)}px`;
    } else {                                            // a tall part (the rail): beside it
      const right = r.right + 12 + w < innerWidth;
      card.style.left = `${right ? r.right + 12 : Math.max(16, r.left - w - 12)}px`;
      card.style.top = `${Math.min(Math.max(16, r.top + 40), innerHeight - h - 16)}px`;
    }
  }
  $("tourNext").focus({preventScroll: true});
}

function tourGo(d){
  const next = tourI + d;
  if (next >= tourSteps.length) return tourEnd(false);
  if (next < 0) return;
  tourI = next;
  tourDraw();
}

// Ended: this page toured, and with the box ticked every page.
function tourEnd(all){
  const kind = tourKind;
  tourKind = "";
  tourKeepSample(false);
  $("tourCard").hidden = $("tourRing").hidden = true;
  $("tourSample")?.remove();
  if (!state?.me) return;
  const seen = [...new Set([...tourSeen(), kind])].slice(-64);
  state.tour = {seen, off: !!state?.tour?.off || all};
  // A poll already out answers with the list from before this: dropped, as
  // an action's own answer drops it (B217).
  adoptSeq++;
  fetch("/api/users", {method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify({action: "prefs", prefs: {tour_seen: seen, tour_off: state.tour.off}})}).catch(() => {});
}

// Show the tours again: every page's, from the next one opened.
async function tourReset(){
  tourAsked.clear();
  state.tour = {seen: [], off: false};
  // ...and a reset the same way: a poll in flight put the old list back,
  // and the tours waited for a reload (B217).
  adoptSeq++;
  const r = await fetch("/api/users", {method: "POST", headers: {"Content-Type": "application/json"},
                                       body: JSON.stringify({action: "prefs", prefs: {tour_seen: [], tour_off: false}})});
  const j = await r.json().catch(() => ({}));
  if (j.error) notify(j.error, true);
  else {
    notify("The tours show again, on each page the next time you open it");
    // ...starting with the page in front, without waiting for a draw.
    tourSoon(tabOf(panes[0])?.kind);
  }
}
