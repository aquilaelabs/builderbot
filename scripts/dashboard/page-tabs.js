// Tabs: what one is called and the address its terminal is reached at, the
// kinds of tab there are, the tooltips, a menu somebody has open, opening,
// focusing, hiding and pinning one, and a terminal in a window of its own
// (R8).
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- what a tab is called --------------------------------------------

// Derived at draw time from where the terminal *is*, not from the argument it
// was opened with, so a `cd` shows up in the strip. The stored label is only
// the fallback for a session tmux does not know about yet.
const cwdOf = session => (state?.sessions || []).find(s => s.name === session)?.cwd || "";
const baseOf = path => path.replace(/\/+$/, "").split("/").pop() || "/";

// One naming rule, computed from the session list and read by both the tab
// strip and the Sessions card. A tab and its session are the same thing, so
// they must not be able to disagree about what that thing is called, including
// after the tab is closed, when the session is all that is left.
//
// Two terminals in one directory would be indistinguishable, so the duplicates
// (and only the duplicates) carry a number.
function sessionLabels(){
  const list = (state?.sessions || []);
  // Through tmuxBase: an account's own sessions carry its prefix, and a
  // prefixed Claude session is still a Claude session.
  const of = s => { const b = tmuxBase(s.name);
    return b.startsWith("claude-") ? "Claude: " + (projFor(b.slice(7)) ?? b.slice(7))
           : s.cwd ? "sh: " + baseOf(s.cwd)
           : "sh: " + s.name; };
  const total = {};
  list.forEach(s => { const l = of(s); total[l] = (total[l] || 0) + 1; });
  const nth = {}, out = new Map();
  for (const s of list){
    const l = of(s);
    nth[l] = (nth[l] || 0) + 1;
    out.set(s.name, total[l] > 1 ? `${l} ${nth[l]}` : l);
  }
  return out;
}

function tabLabel(t){
  // Computed for a notebook, not stored: a tab restored from a layout saved
  // before the rename would otherwise wear "To do:" forever.
  const spec = TABKINDS[t.kind];
  if (spec?.label) return spec.label(t);
  if (t.kind !== "term") return t.label;
  // Falls back to the stored label only while tmux has yet to register a
  // just-opened session.
  return sessionLabels().get(sessionOf(t.arg)) || t.label;
}

// The tooltip is the full path, which is the thing a basename loses, plus,
// for a Claude tab, what the session says it is doing.
function tabTitle(t){
  if (t.kind !== "term") return t.label;
  const base = cwdOf(sessionOf(t.arg)) || t.label;
  const c = isClaude(t) ? claudeOf(sessionOf(t.arg)) : null;
  return c?.task && c.state === "working" ? `${base}\nworking on: ${c.task}` : base;
}

function tabLabels(){
  return new Map(tabs.map(t => [t.id, tabLabel(t)]));
}

// The next free numbered terminal for a project ("" = the workspace root).
// Checked against live tmux sessions as well as open tabs, so a tab closed
// without killing its session does not hand the number back out.
function nextShell(proj){
  const taken = new Set([...liveSessions(),
                         ...tabs.filter(t => t.kind === "term").map(t => sessionOf(t.arg))]);
  const base = myTmux(tmuxName(proj ? `shell-${proj}` : "shell"));
  for (let n = 1; n <= 99; n++)
    if (!taken.has(`${base}-${n}`)) return `sh:${n}:${proj}`;
  return null;
}

// Same origin, not ttyd's own port: the server proxies /term to ttyd, so the
// one sign-in that opened this page covers every terminal too: no second
// credential prompt, and no second port for the router to publish.
// A Claude terminal's URL carries the boot it was opened in. It is fixed into
// the iframe's src at that moment and a reattach reuses the string, so a page
// left open across a container restart asks for a session under the *old*
// boot, which bb-tty refuses. That is the hole the boot-time tab prune could
// not close: pruning the stored layout does nothing about a browser already
// holding the tab, and a phone waking up reloads its terminal iframe, which
// spawns whatever the URL names. A shell carries no marker, because a shell
// is safe to recreate in the same directory and always was.
// The boot is the machine the session runs ON: for a project bound to a node
// it is that node's (the row carries it), because bb-tty there compares
// against its own run, and a tab stamped with this container's boot was
// refused on the node on every reconnect, forever (roadmap #24).
const bootFor = arg => {
  const proj = arg.startsWith("claude:") ? arg.slice(7).split(":")[0] : "";
  const row = (state?.projects || []).find(p => p.name === proj);
  // The boot of the node the argument names (R82), else the primary's.
  const picked = (arg.match(/:n:([A-Za-z0-9_-]+)/) || [])[1];
  const onNode = picked ? (row?.session_nodes || []).find(x => x.id === picked)?.boot : "";
  return onNode || row?.session_boot || state?.boot || "";
};
const ttydUrl = (arg) => `/term/?arg=${encodeURIComponent(
  arg.startsWith("claude:") && bootFor(arg) ? `${arg}:b:${bootFor(arg)}` : arg)}`;

const isPhone = () => window.matchMedia("(max-width:900px)").matches;

const dur = s =>
  s < 60   ? `${s}s` :
  s < 3600 ? `${Math.floor(s/60)}m ${s%60}s` :
             `${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;

function setView(v){
  const prev = document.body.dataset.view;
  document.body.dataset.view = v;
  $("vDash").classList.toggle("on", v === "dash");
  $("vTerm").classList.toggle("on", v === "terminal");
  // Per device, not on the server: which side of the switch a phone was
  // looking at is about that phone, and a reload (or a tab the browser
  // evicted overnight) should come back to the same side.
  // Stamped with the run of the container it was chosen under. A reload comes
  // back to the same side (that is the point of remembering it), but a
  // container that has been REPLACED is a different situation: whatever was
  // on the terminal side ended with it, so coming back there lands on tabs
  // for sessions that are gone.
  try{
    localStorage.setItem("bb.view", v);
    if (state?.boot) localStorage.setItem("bb.view.boot", state.boot);
  }catch(e){ /* private mode */ }
  // The switch reads left-to-right (Dashboard | Terminal), so the incoming
  // view slides in from its own side. The outgoing one is display:none the
  // moment the attribute flips (only the entrance can be animated) and
  // main clips the overshoot so the page never grows a horizontal scrollbar.
  if (prev && prev !== v && isPhone() && !noMotion()){
    const col = document.querySelector(v === "dash" ? ".col.side" : ".col.term");
    const main = document.querySelector("main");
    main.style.overflowX = "hidden";
    col.animate([{transform: `translateX(${v === "terminal" ? "" : "-"}100%)`},
                 {transform: "none"}],
                {duration: 220, easing: "ease"})
       .onfinish = () => main.style.overflowX = "";
  }
  // The strip was display:none while the dashboard was in front, so nothing
  // drawn then could scroll it: bring the tab just opened into view now,
  // and re-judge the arrows, which measured a zero-width strip until now.
  if (v === "terminal"){ revealActiveTab(); updateArrows(); }
}

// Back to the Dashboard when the container this page remembers a side from is
// not the one answering any more. Checked on the first status as well as on a
// live restart: a page opened fresh after the container came back has no
// memory of the previous boot to compare against, only what it stored.
function viewAfterRestart(){
  if (!isPhone() || !state?.boot) return;
  let was = null;
  try{ was = localStorage.getItem("bb.view.boot"); }catch(e){ return; }
  if (was === state.boot) return;
  // No stamp at all is not a restart; it is a browser that has never been
  // here, or one upgrading from before this existed. Adopt the boot and leave
  // the side alone: yanking somebody to the Dashboard once, on the strength
  // of a value that was simply absent, is a worse bug than the one this fixes.
  if (!was){
    try{ localStorage.setItem("bb.view.boot", state.boot); }catch(e){ /* private */ }
    return;
  }
  try{ localStorage.setItem("bb.view.boot", state.boot); }catch(e){ /* private */ }
  // A view asked for in the URL outranks this, the same as it outranks the
  // remembered side: something that can only speak URLs is making a request.
  const qv = new URLSearchParams(location.search).get("view");
  if (qv === "terminal" || qv === "dash") return;
  if (document.body.dataset.view !== "dash") setView("dash");
}

// ---- tabs ------------------------------------------------------------

// What makes two tabs the same tab. For a terminal it is the tmux session,
// NOT the argument that produced it: "claude:FreshBoot" from the project list
// and "claude-FreshBoot" from the session list are different strings naming
// one session, and letting both exist puts two ✕ buttons on it.
// Everything a tab kind needs, in one place, because it used to be seven and
// three of them failed SILENTLY: a kind missing from the server's TAB_KINDS
// vanished on the next reload, a kind missing from the render dispatch showed
// nothing, and a kind missing from the repaint hatch drew once and then held
// that drawing forever, which shipped twice, as an empty Docker tab and as a
// Projects tab whose thumbtacks lied about what was pinned.
//
//   multi   several may be open at once. A notebook is per project; the rest
//           are one window onto one thing and a second is only ever confusing.
//   label   what the tab strip says. Computed, never stored: a tab restored
//           from an older layout must not wear a name that has since changed.
//   render  draw this kind into pane i.
//   live    when to redraw. "always" for a kind that renders from `state`,
//           which moves under it constantly; a function returning a revision
//           for one whose data arrives on its own schedule, so a pane already
//           showing it is left alone until that data actually changes.
//   open    run when the tab is brought up: the fetch its first draw needs.
//   reload  give its pane bar a reload button.
// The Tools card's icons, one per tab kind a button there opens: drawn in
// the same 16px stroke voice as the row icons further down. Declared ahead
// of TABKINDS, which reads them at its own initialization, rather than
// beside the row icons, which come ten thousand lines later (bug #27).
const TOOL_ICONS = {
  // A book, open at the spine: the row's notebook button and the notebook
  // tab wear the same one (the operator, 25 Sep: the ticked list did not
  // read as a book, and the tab looked to have no icon at all).
  notebook: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 4.2C6.8 3.1 5 2.8 2.6 3v9.4c2.4-.2 4.2.1 5.4 1.2 1.2-1.1 3-1.4 5.4-1.2V3C11 2.8 9.2 3.1 8 4.2z"/>
    <path d="M8 4.2v9.4"/></svg>`,
  // A box, for what gets installed.
  toolchains: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 5.2 8 2.6l5.5 2.6v5.6L8 13.4l-5.5-2.6z"/>
    <path d="M2.5 5.2 8 7.8l5.5-2.6"/><path d="M8 7.8v5.6"/></svg>`,
  // A handset with a play mark on its screen: a phone that is software.
  emulator: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="4.5" y="2" width="7" height="12" rx="1.4"/><path d="M7 6.2v3.6l2.8-1.8z"/></svg>`,
  // Stacked containers.
  docker: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2.4" y="8.4" width="3.4" height="3.4"/><rect x="6.3" y="8.4" width="3.4" height="3.4"/>
    <rect x="10.2" y="8.4" width="3.4" height="3.4"/><rect x="6.3" y="4.6" width="3.4" height="3.4"/></svg>`,
  // A list with a clock beside it: what is queued and what is running.
  jobs: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.8 4.4h5"/><path d="M2.8 8h4"/><path d="M2.8 11.6h5"/>
    <circle cx="11.6" cy="10" r="2.8"/><path d="M11.6 8.6v1.5l1 .7"/></svg>`,
  // Two machines in a rack.
  nodes: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2.5" y="2.8" width="11" height="4.2" rx="1"/><rect x="2.5" y="9" width="11" height="4.2" rx="1"/>
    <path d="M5 4.9h.01"/><path d="M5 11.1h.01"/></svg>`,
  // A handset.
  phone: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="4.5" y="2" width="7" height="12" rx="1.4"/><path d="M7 11.8h2"/></svg>`,
  // A magnifier, for the scanner's findings.
  findings: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="6.8" cy="6.8" r="4"/><path d="M9.8 9.8 13.4 13.4"/></svg>`,
};
// Which button on the Tools card opens which kind, so the card can be
// stamped with the icons once at load and the tab strip can look them up.
const TOOL_BUTTONS = {bToolchains: "toolchains", bDocker: "docker", bEmulator: "emulator", bJobs: "jobs",
                      bNodes: "nodes", bPhone: "phone", bFindings: "findings"};

const TABKINDS = {
  term:     { multi: true },
  notebook:     { multi: true, label: t => "Notebook: " + t.arg,
              icon: TOOL_ICONS.notebook,
              render: (i, t) => renderNotebookInto(i, t.arg), live: "always" },
  toolchains: { multi: false, label: () => "Toolchains",
              icon: TOOL_ICONS.toolchains,
              render: (i) => renderToolchainsInto(i), live: () => tcRev,
              open: () => loadToolchains() },
  // nodesRev and jobsRev as well as its own: a node's images arrive on its
  // census, and an image job moves the queue.
  emulator: { multi: false, label: () => "Emulator",
              icon: TOOL_ICONS.emulator,
              render: (i) => renderEmulatorInto(i), live: () => `${emuRev}/${nodesRev}`,
              open: () => loadEmulator() },
  projects: { multi: false, label: () => "Projects",
              render: (i) => renderProjectsInto(i), live: "always" },
  // nodesRev as well as dockerRev: the node PICKER on this tab is drawn from
  // the node list, and that list arrives on its own schedule. Watching only
  // dockerRev meant a fresh page whose first tab was this one drew before
  // the list landed and never drew again, so a box with two nodes showed no
  // picker at all until something else happened to repaint it. And the list
  // is asked for on open for the same reason, rather than only by the Nodes
  // tab happening to have been visited.
  docker:   { multi: false, label: () => "Docker",
              icon: TOOL_ICONS.docker,
              render: (i) => renderDockerInto(i),
              // ...and phRev, because a session's rebuild request is answered
              // on this tab and arrives on the phone payload's ask list.
              live: () => `${dockerRev}/${dmNodesKey()}/${phRev}`,
              open: () => { const t = dockerTab();
                            if (!dockerNode && t?.arg && t.arg !== "__docker")
                              dockerNode = t.arg;
                            if (!dockerList && !dockerFetching) loadDocker();
                            if (nodesList === null) loadNodes(); } },
  nodes:    { multi: false, label: () => "Nodes",
              icon: TOOL_ICONS.nodes,
              render: (i) => renderNodesInto(i), live: () => `${nodesRev}/${signinRev()}`,
              open: () => loadNodes() },
  jobs:     { multi: false, label: () => "Jobs",
              icon: TOOL_ICONS.jobs,
              render: (i) => renderJobsInto(i), live: () => jobsRev,
              open: () => loadJobs() },
  phone:    { multi: false, label: () => "Phone",
              icon: TOOL_ICONS.phone,
              render: (i) => renderPhoneInto(i), live: () => phRev,
              open: () => phFetch(null, true) },
  settings: { multi: false, label: () => "Controller settings",
              render: (i) => renderSettingsInto(i), live: settingsLive },
  users:    { multi: false, label: () => "Users",
              render: (i) => renderUsersInto(i), live: () => usersRev,
              open: () => loadUsers() },
  profile:  { multi: false, label: () => "Profile",
              render: (i) => renderProfileInto(i), live: () => profileRev,
              open: () => loadProfile() },
  findings: { multi: false, label: () => "Analysis",
              icon: TOOL_ICONS.findings,
              render: (i) => renderFindingsInto(i),
              // The ages list as well as the mtime: the mtime is a MAX, so a
              // report appearing with an OLD stamp: the exact shape of a
              // stale copy: moves it nowhere, and the tab never heard.
              live: () => `${state?.reports_mtime ?? ""}:${
                (state?.reports_ages || []).map(r => r.name + (r.stale ? "!" : ""))
                  .join(",")}:${fxRev}`,
              open: () => loadFindings() },
};

// A terminal is identified by the tmux session behind it, not by the argument
// that opened it. A kind that may not have two open is identified by the kind
// alone, so a second open focuses the first whatever argument it carries,
// which is the rule, rather than a convention of passing the same magic arg.
const identity = t => t.kind === "term" ? "tmux:" + sessionOf(t.arg)
                    : TABKINDS[t.kind] && !TABKINDS[t.kind].multi ? t.kind
                    : t.kind + ":" + t.arg;

// Move `title` to `data-tip` inside a container, so markup that already
// carries the words gets the faster tooltip without being rewritten. The
// title is removed rather than left in place: keeping both shows the native
// one a second later, on top of ours.
function tipify(root){
  root.querySelectorAll("[title]:not([data-tip])").forEach(el => {
    const s = el.getAttribute("title");
    if (!s) return;
    el.setAttribute("data-tip", s);
    el.removeAttribute("title");
  });
}

// A tooltip stops being wanted the moment its button is clicked: you have read
// it, you have acted on it, and it is now a box sitting over the next thing you
// want to press. CSS alone cannot say "since the last click": `:active` ends
// with the release and `:hover` is still true, so the state lives here.
//
// Held as the tip's TEXT rather than the element, because a row repaints on the
// poll and the button under a motionless pointer is a different node a second
// later. The replacement fires `pointerover` (the hit-test target changed) with
// the same words on it, which is how the flag survives the repaint and clears
// the moment the pointer genuinely reaches a different control.
let tipHushed = null;
function tipOff(){
  const html = document.documentElement;
  addEventListener("pointerdown", e => {
    // A tap is not a hover and never raised a tip in the first place: the
    // whole rule is inside @media(hover:hover). Left unguarded, tapping on the
    // phone half of a hybrid would set a flag that then suppressed the mouse's
    // tips until something else cleared it.
    if (e.pointerType === "touch") return;
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (!el) return;
    tipHushed = el.getAttribute("data-tip");
    html.setAttribute("data-tipoff", "");
  }, true);
  addEventListener("pointerover", e => {
    if (tipHushed === null) return;
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el && el.getAttribute("data-tip") === tipHushed) return;
    tipHushed = null;
    html.removeAttribute("data-tipoff");
  }, true);
}

// ---- a menu somebody has open ---------------------------------------------

// A browser without :open: the last <select> pressed, until it changes,
// loses focus or Escape, and never for longer than half a minute.
let selPressed = null, selPressedAt = 0;
function openMenu(){
  // closest(), because focus is not always on the <select> itself: Chromium
  // moves it onto the <option> under the pointer while the list is showing.
  const a = document.activeElement?.closest?.("select");
  if (!a || !a.isConnected) return null;
  if (OPEN_KNOWN) return a.matches(":open") ? a : null;
  return selPressed === a && Date.now() - selPressedAt < 30000 ? a : null;
}
let menuTimer = null;
// Whether `root` must be left alone for now; with no root, whether anything
// must. Saying yes is also a promise to come back, which is the timer.
function menuHolds(root){
  const m = openMenu();
  if (!m || (root && !root.contains(m))) return false;
  if (!menuTimer) menuTimer = setInterval(() => {
    if (openMenu()) return;
    clearInterval(menuTimer); menuTimer = null;
    // Everything that was skipped, from its own source: the status poll
    // repaints the cards and the panes, the revisions poll fires the watches.
    refresh(); drawPanes(); pollRevs();
  }, 250);
  return true;
}

// Draw one document tab into its pane, if it is due a redraw. The one place
// that decides, so the two call sites: a pane that just changed tab and a
// pane that did not: cannot disagree about it.
function renderDoc(i, t, pane){
  const spec = TABKINDS[t.kind];
  if (!spec || !spec.render) return;
  // Before the stamp, so the draw is still owed when the menu shuts.
  if (menuHolds(pane)) return;
  if (spec.live === "always"){ renderGuarded(spec, i, t); return; }
  // Stamped with the kind as well as the number: one pane holds one tab, but
  // it can be handed a different KIND of tab, and two counters that happened
  // to agree would then read as "already drawn".
  const rev = t.kind + ":" + (typeof spec.live === "function" ? spec.live() : "");
  if (pane.dataset.rev !== rev){ pane.dataset.rev = rev; renderGuarded(spec, i, t); }
}

// One page is one failure domain, and this is the fence inside it: a renderer
// that throws breaks its own tab, not the dashboard. Without it, one bug in
// one kind's render took down drawPanes, and with it the poll loop, the tab
// strip and every terminal on screen, which is an outage wearing a typo.
// The error is still thrown at the console (rethrown async, so nothing that
// reads console errors (the suite included) mistakes a caught bug for
// none), and the tab itself says what happened instead of holding whatever
// half-drawn state the throw left.
function renderGuarded(spec, i, t){
  try{ spec.render(i, t); }
  catch(e){
    const el = $("doc" + i);
    if (el) el.innerHTML = `<div class="hint bad" style="padding:var(--row-y) var(--row-x)">
      this tab's renderer failed: the rest of the page is fine.
      ${esc(String(e && e.message || e))}</div>`;
    setTimeout(() => { throw e; });
  }
}

// The same guard for a card on the Dashboard side. A card's draw that throws
// paints the failure into that card and lets the poll carry on to the next
// one; the error still reaches the console with its stack. id is the card's
// body element, or null for a step that has no card to write into.
function drawCard(id, fn){
  try{ fn(); }
  catch(e){
    const el = id && $(id);
    if (el) paint(el, `<div class="empty warn">not drawn; this card's draw failed
      on the container's answer; the rest of the page is fine.
      ${esc(String(e && e.message || e))}</div>`);
    setTimeout(() => { throw e; });
  }
}

// One tab per thing. A second click on Claude or Findings for something already
// open is a request to go to it, not to open a duplicate. Shell tabs are the
// exception and are always new: each carries its own session name, so they
// never collide here.
function openTab(spec){

  let t = tabs.find(x => identity(x) === identity(spec));
  if (!t){
    if (!roomForTab(spec.kind)) return;
    t = Object.assign({id:"t" + (++seq)}, spec);
    tabs.push(t);
  } else if (t.kind === "term" && t.arg !== spec.arg
             && !liveSessions().has(sessionOf(t.arg))){
    // Same session, different argument, and the session is gone: the new
    // argument is the one that decides what starts: Resume on a tab whose
    // claude has exited must carry the transcript id, not the old fresh-
    // conversation arg the tab was opened with. A live session keeps its
    // tab's arg: reloading the frame would only re-attach to it anyway.
    t.arg = spec.arg;
  }
  // The boot it was opened under, for the restart check on the poll: a tab
  // opened AFTER the machine came back is not one from before it. Stamped
  // here rather than only where a tab is CREATED, because a second click on
  // Claude for something already open takes the other branch, and an
  // unstamped tab read as "from before", which dropped the tab the operator
  // had just opened.
  if (String(t.arg).startsWith("claude:") && t.boot === undefined)
    t.boot = bootFor(t.arg);
  const shown = panes.indexOf(t.id);
  if (shown === -1) panes[active] = t.id;    // not on screen; put it here
  else active = shown;                       // already on screen: focus it
  show(t);
}

// Each terminal tab is an iframe running a full xterm.js over its own
// websocket. Past a point the page stops being usable and the container is
// carrying sessions nobody is reading, so refuse rather than degrade.
// Only terminals count (R78): a document tab is a draw from state and costs
// nothing to keep, so a Nodes tab beside twelve shells was never the load
// the cap is about. The count is this account's own strip, which is what
// `tabs` is: the layout is kept per account on the server.
function roomForTab(kind){
  if (kind !== "term") return true;
  const cap = state?.max_tabs || 12;
  if (tabs.filter(t => t.kind === "term").length < cap) return true;
  notify(`Terminal tab limit reached (${cap} shells and Claude sessions). Close or minimize `
       + `one first; a minimized tab keeps running.`, true);
  return false;
}

function focusTab(id){
  const t = tabOf(id);
  if (!t) return;
  const shown = panes.indexOf(id);
  if (shown === -1) panes[active] = id; else active = shown;
  show(t);
}

// Common tail of "make this tab the one being looked at".
function show(t){
  pinFor = null;
  render();
  if (isPhone()) setView("terminal");
  // Once. The render above ran the kind's open hook already when this tab
  // was not the one its pane showed, and running it here as well opened
  // every tab twice: two node listings, two phone probes, and with the
  // Docker manager's own load behind them, three listings of one daemon
  // for one press, each one a set of reads on the node (B210).
  if (!openedNow.has(t.id)) TABKINDS[t.kind]?.open?.();
  // Only when it is a different project's: switching back to a notebook must
  // not reload it, or whatever is staged in it goes.
  refreshSoon();      // a just-opened terminal's session appears in Sessions
}

// The status poll is every fifteen seconds, which is the right cadence for
// watching and the wrong one for feedback: a terminal opened here should show
// up under Sessions when it exists, not up to a quarter-minute later. Actions
// that change something the poll reports call this: one refresh now, and two
// more shortly after, because a session takes a moment to exist after its
// iframe is created (bb-tty makes it on the terminal's connection). Timers
// are collapsed so a burst of clicks is one burst of polls.
let soonTimers = [];
function refreshSoon(){
  soonTimers.forEach(clearTimeout);
  refresh();
  soonTimers = [1500, 4000].map(ms => setTimeout(() => refresh(), ms));
}

// Take a tab off the strip. Nothing is destroyed and nothing is asked: a
// terminal keeps running and is listed under Sessions, a document is a view of
// a file on disk. Ending a session for good is the ✕ in the Sessions card,
// which is where a question is worth asking because something is actually lost.
function hideTab(id, ev){
  ev?.stopPropagation();
  const t = tabOf(id);
  if (!t) return;
  if (t.kind === "notebook"){
    // Closing a notebook's tab ends its instance: whatever was staged in it
    // was just answered for, and reopening reads fresh from disk.
    const nb = notebooks.get(t.arg);
    if (nb && !nb.leaving()) return;
    nb?.destroy();
  }
  dropTab(id);
  refresh();
}

// Remove a tab and repair the layout: a pane it was in falls back to the other
// one, then to whatever tab is still open, then to nothing, which drawPanes
// renders as a placeholder rather than this function preventing.
function dropTab(id){
  if (pinFor === id) pinFor = null;    // its menu would otherwise outlive it
  tabs = tabs.filter(x => x.id !== id);
  for (let i = 0; i < 2; i++) if (panes[i] === id) panes[i] = null;
  if (panes[0] === null && panes[1] !== null){ panes[0] = panes[1]; panes[1] = null; }
  if (panes[0] === null) panes[0] = tabs[0]?.id ?? null;
  if (panes[1] === null) active = 0;
  render();
}

function pinTo(id, idx, ev){
  ev?.stopPropagation();
  pinFor = null;
  if (!tabOf(id)){ render(); return; }   // the tab went while its menu was open
  const other = 1 - idx;
  if (panes[other] === id){
    // It is already in the other pane. That pane needs something else or the
    // tab renders twice: two iframes attaching to one tmux session.
    const fill = tabs.find(t => t.id !== id)?.id ?? null;
    if (idx === 1 && fill === null){ render(); return; }  // nothing to sit beside it
    panes[other] = idx === 1 ? fill : null;
  }
  panes[idx] = id;
  active = idx;
  render();
}

// Closing a pane collapses the layout. It must not close the tab: the tab is
// the thing that owns a session, the pane is only where it was being shown.
function closePane(idx, ev){
  ev?.stopPropagation();
  if (idx === 1){ panes[1] = null; active = 0; }
  else { panes[0] = panes[1] ?? tabs[0]?.id ?? null; panes[1] = null; active = 0; }
  render();
}

// ---- a terminal in its own window (R8) ------------------------------------

// tmux attaches many clients to one session by design; what it does not do
// is size a session for two of them, so the tab here must not stay a live
// terminal while the window has it: its frames are torn down and the pane
// shows a placeholder with Reattach. The window is the terminal's own URL,
// its own /term connection, so closing this page leaves it working, and the
// session outlives both. Desktop only: a phone has nowhere to put a window.
function popOut(id, ev){
  ev?.stopPropagation();
  const t = tabOf(id);
  if (!t || t.kind !== "term" || isPhone()) return;
  const w = window.open(ttydUrl(t.arg), "bb-pop-" + id, "popup=yes,width=1000,height=640");
  if (!w){ notify("the browser blocked the window: allow pop-ups for this page and try again", true); return; }
  popWins.set(id, w);
  t.popped = true;
  for (let j = 0; j < 2; j++)
    [...($("pane" + j).querySelector(".stack")?.children || [])]
      .filter(c => c.dataset.key?.startsWith(id + "|")).forEach(c => c.remove());
  render();
}

function reattachTab(id, ev){
  ev?.stopPropagation();
  const t = tabOf(id);
  if (!t) return;
  const w = popWins.get(id);
  popWins.delete(id);
  try{ if (w && !w.closed) w.close(); }catch(e){ /* another origin by now: it stays */ }
  t.popped = false;
  render();
}

function togglePin(id, ev){
  ev.stopPropagation();
  pinFor = pinFor === id ? null : id;
  drawTabs();
}

// Positioning happens in drawTabs, not here, because the tab bar is rebuilt on
// every status poll: anything measured at click time is gone 15 seconds later.
function placePinMenu(){
  const menu = $("pinmenu"), anchor = $("tabbar").querySelector(`.tab[data-id="${pinFor}"]`);
  if (!menu || !anchor) return;
  const a = anchor.getBoundingClientRect(), bar = $("tabbar").getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(a.left - bar.left,
                                         bar.width - menu.offsetWidth - 4)) + "px";
  menu.style.top = (a.bottom - bar.top + 4) + "px";
}
