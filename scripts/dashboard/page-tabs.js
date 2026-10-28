// Tabs: what one is called and the address its terminal is reached at, the
// kinds of tab there are, the titles kept for a screen reader, a menu somebody has open, opening,
// focusing, hiding and pinning one, and a terminal in a window of its own
// (R8).
//
// One classic script beside index.html (docs/design-language.md, Files):
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
  const of = s => { const b = tmuxBase(s.name), ag = agentOfSession(b);
    return ag ? ag.agent.name + ": " + projLabel(projFor(ag.stem) ?? ag.stem)
           // A container's shell (R218 step 4) by the container, not by a
           // directory on the host it says nothing about.
           : b.startsWith("ctr-") ? "in " + b.slice(4)
           // A project's directory by the name it is shown under (B64):
           // one reused after a delete is numbered on disk, not on screen.
           : s.cwd ? "sh: " + projLabel(baseOf(s.cwd))
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

// A tab's full description, the full path a basename loses, plus, for a
// Claude tab, what the session says it is doing: kept for a screen reader
// (untitle), since the page draws no tooltips.
function tabTitle(t){
  // A notebook's title is computed like its label, so a rename shows at once.
  if (t.kind === "notebook") return tabLabel(t);
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

// A Claude terminal's words carry the boot it was opened in, so a tab left
// open across a container restart asks for a session under the *old* boot,
// which bb-tty refuses rather than starting a new one behind the person's
// back: a phone waking up reconnects its terminal, which spawns whatever the
// words name. A shell carries no marker, because a shell is safe to
// recreate in the same directory and always was.
// The boot is the machine the session runs ON: for a project bound to a node
// it is that node's (the row carries it), because bb-tty there compares
// against its own run, and a tab stamped with this container's boot was
// refused on the node on every reconnect, forever (roadmap #24).
const bootFor = arg => {
  const proj = agentOfArg(arg)?.project || "";
  const row = (state?.projects || []).find(p => p.name === proj);
  // The boot of the node the argument names (R82), else the primary's.
  const picked = (arg.match(/:n:([A-Za-z0-9_-]+)/) || [])[1];
  const onNode = picked ? (row?.session_nodes || []).find(x => x.id === picked)?.boot : "";
  return onNode || row?.session_boot || state?.boot || "";
};
// A tab's words as its terminal opens with them: the argument, and the boot
// stamped on a Claude session's.
const termArg = arg => agentOfArg(arg) && bootFor(arg) ? `${arg}:b:${bootFor(arg)}` : arg;
// A tab on a page of its own: a VM's screen (R99), noVNC's own page speaking
// to this controller's relay for that VM, scaled to the dock's size; any
// other, BuilderBot's terminal page (terminal.html), for a tab popped out.
const tabUrl = (arg, label) => arg.startsWith("screen:")
  ? `/novnc/vnc_lite.html?scale=true&path=${encodeURIComponent(`screen/ws?vm=${arg.split(":")[1]}/${arg.split(":")[2]}`)}`
  : `/terminal?arg=${encodeURIComponent(termArg(arg))}${label ? "&label=" + encodeURIComponent(label) : ""}`;

const isPhone = () => window.matchMedia("(max-width:900px)").matches;

const dur = s =>
  s < 60   ? `${s}s` :
  s < 3600 ? `${Math.floor(s/60)}m ${s%60}s` :
             `${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;

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
  // A prompt's chevron and cursor in a box: a coding agent at work (R95).
  agents: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2" y="2.5" width="12" height="11" rx="1.6"/><path d="M4.8 6.2l2.2 1.8-2.2 1.8"/><path d="M8.6 10.4h2.8"/></svg>`,
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
  // A play arrow in a box: CI, running workflows.
  runner: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2.5" y="2.5" width="11" height="11" rx="1.6"/><path d="M6.6 5.6v4.8l3.8-2.4z"/></svg>`,
  // A handset.
  phone: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="4.5" y="2" width="7" height="12" rx="1.4"/><path d="M7 11.8h2"/></svg>`,
  // Two arrows through a gate: traffic passed on, for the nginx tab.
  nginx: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 5.5h7.5"/><path d="M8 3.3l2.2 2.2L8 7.7"/>
    <path d="M13.5 10.5H6"/><path d="M8.2 8.3L6 10.5l2.2 2.2"/>
    <rect x="11" y="2.5" width="2.5" height="11" rx="0.6"/></svg>`,
  // A magnifier over lines of code, for the Scanners page (R145).
  scanners: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6.5" cy="6.5" r="3.8"/><path d="M9.3 9.3L13.5 13.5"/><path d="M4.8 5.8h3.4M4.8 7.6h2.2"/></svg>`,
  // A screen inside a screen: a machine run on a machine, for the VMs page.
  vms: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <rect x="1.5" y="2.5" width="13" height="9" rx="1.2"/><rect x="4.5" y="5" width="7" height="4" rx="0.6"/>
    <path d="M5.5 14h5"/><path d="M8 11.5V14"/></svg>`,
  // A ledger's lines, for the Audit page (R158 step 8).
  audit: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 2.5h10v11H3z"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"/></svg>`,
  // Two points joined, for the Network page (R165 step 4).
  network: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="4" cy="8" r="2"/><circle cx="12" cy="4" r="2"/><circle cx="12" cy="12" r="2"/><path d="M5.8 7.2 10.2 4.8M5.8 8.8l4.4 2.4"/></svg>`,
  // A box with its one light, for This machine (R90 step 8).
  machine: `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2.5" y="3.5" width="11" height="9" rx="1"/><path d="M5 12.5v1.5M11 12.5v1.5M5 6.5h3"/><circle cx="11" cy="6.5" r=".8"/></svg>`,
  // A clock, for the Schedules page (R117).
  keys: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="5" cy="8" r="2.5"/><path d="M7.5 8H14M11.5 8v2.5M13.5 8v2"/></svg>`,
  debug: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 5.5a2.5 2.5 0 0 1 5 0v4a2.5 2.5 0 0 1-5 0z"/><path d="M8 7v5M3 6.5h2.5M10.5 6.5H13M3 10h2.5M10.5 10H13M6 3.5 5 2M10 3.5 11 2"/></svg>`,
  schedules: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="8" cy="8" r="5.8"/><path d="M8 4.6V8l2.4 1.6"/></svg>`,
  // A drive: two platters, for the Storage tab.
  storage: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <ellipse cx="8" cy="4.2" rx="5.5" ry="2"/><path d="M2.5 4.2v7.6c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2V4.2"/>
    <path d="M2.5 8c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/></svg>`,
  // A magnifier, for the scanner's findings.
  findings: `<svg viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="6.8" cy="6.8" r="4"/><path d="M9.8 9.8 13.4 13.4"/></svg>`,
};

const TABKINDS = {
  term:     { multi: true },
  notebook:     { multi: true, label: t => "Notebook: " + projLabel(t.arg),
              icon: TOOL_ICONS.notebook,
              render: (i, t) => renderNotebookInto(i, t.arg), live: "always" },
  // The Library (R170): one list of everything a BuilderBot installs or
  // runs, for one node; its own read, the node list, and the sign-in,
  // which rides the status poll (an agent's row carries it).
  library:  { multi: false, label: () => "Library",
              icon: TOOL_ICONS.toolchains,
              render: (i) => renderLibraryInto(i), live: () => `${libRev}/${nodesRev}/${signinRev()}`,
              open: () => loadLibrary() },
  toolchains: { multi: false, label: () => "Toolchains",
              icon: TOOL_ICONS.toolchains,
              render: (i) => renderToolchainsInto(i), live: () => tcRev,
              open: () => loadToolchains() },
  // The coding agents on a node (R95 step 15): its own read, the node
  // list, and the sign-in, which rides the status poll.
  agents:   { multi: false, label: () => "Agents",
              icon: TOOL_ICONS.agents,
              render: (i) => renderAgentsInto(i), live: () => agentsLiveKey(),
              open: () => loadAgents() },
  // nodesRev and jobsRev as well as its own: a node's images arrive on its
  // census, and an image job moves the queue.
  emulator: { multi: false, label: () => "Emulator",
              icon: TOOL_ICONS.emulator,
              render: (i) => renderEmulatorInto(i), live: () => `${emuRev}/${nodesRev}`,
              open: () => loadEmulator() },
  // The Notifications page (R218 step 6): the account's record, read on
  // open, and the asks, which ride the phone payload, on every draw.
  // Help (R258): the docs' list on open, each doc read when it is opened.
  help:     { multi: false, label: () => "Help",
              render: (i) => renderHelpInto(i), live: () => helpRev,
              open: () => loadHelp() },
  notices:  { multi: false, label: () => "Notifications",
              render: (i) => renderNoticesInto(i), live: "always",
              open: () => loadNotices() },
  // Home (R218 step 5): its own read on open, and the poll's rows on every
  // draw, painted only when they changed.
  home:     { multi: false, label: () => "Home",
              render: (i) => renderHomeInto(i), live: "always",
              open: () => homeOpen() },
  // The chat (R250 step 2): the dock's Chat tab, the list and the open
  // conversation, read on open and on the chat revision.
  chat:     { multi: false, label: () => "Chat",
              render: (i) => renderChatInto(i), live: "always",
              open: () => loadChat() },
  // Sessions (R250 step 1): the status poll's sessions, painted only when
  // they changed.
  sessions: { multi: false, label: () => "Sessions",
              render: (i) => renderSessionsInto(i), live: "always" },
  projects: { multi: false, label: () => "Projects",
              render: (i) => renderProjectsInto(i), open: () => projectsShown(), live: "always" },
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
              render: (i) => renderNodesInto(i), live: () => `${nodesRev}/${signinRev()}/${phRev}`,
              open: () => loadNodes() },
  // nodesRev as well as its own: a node coming or going moves the sections.
  nginx:    { multi: false, label: () => "nginx",
              icon: TOOL_ICONS.nginx,
              render: (i) => renderNginxInto(i), live: () => `${nginxRev}/${nodesRev}`,
              open: () => loadNginx() },
  // The Scanners page (R145): BuilderBot's own scanners on each node.
  scanners: { multi: false, label: () => "Scanners",
              icon: TOOL_ICONS.scanners,
              render: (i) => renderScannersInto(i), live: () => `${scannersRev}/${nodesRev}/${jobsRev}`,
              open: () => loadScanners() },
  // The VMs page (R91): its records, and the census a node's hello carries.
  vms:      { multi: false, label: () => "VMs",
              icon: TOOL_ICONS.vms,
              render: (i) => renderVmsInto(i), live: () => `${vmsRev}|${vmView}|${vmsNode}|${vmsChip}|${vmsSearch}`,
              open: () => loadVms() },
  // nodesRev as well as its own: a hello carries a fresh walk.
  storage:  { multi: false, label: () => "Storage",
              icon: TOOL_ICONS.storage,
              render: (i) => renderStorageInto(i), live: () => `${storageRev}/${nodesRev}`,
              open: () => loadStorage() },
  // From the status read and the node list: drawn on every poll, painted
  // only when it changed.
  debug:    { multi: false, label: () => "Debug",
              icon: TOOL_ICONS.debug,
              render: (i) => renderDebugInto(i), live: "always" },
  // jobsRev as well as its own: a schedule's run is a job.
  schedules: { multi: false, label: () => "Schedules",
              icon: TOOL_ICONS.schedules,
              render: (i) => renderSchedulesInto(i), live: () => `${schedRev}/${jobsRev}`,
              open: () => loadSchedules() },
  jobs:     { multi: false, label: () => "Jobs",
              icon: TOOL_ICONS.jobs,
              render: (i) => renderJobsInto(i), live: () => jobsRev,
              open: () => loadJobs() },
  // A phone and a CI runner are tools of their own again, each with a node
  // picker (R121, the operator 4 Oct): inside a node's page they were hard
  // to find, and the Nodes tab is a machine's configuration.
  phone:    { multi: false, label: () => "Phone",
              icon: TOOL_ICONS.phone,
              render: (i) => renderPhoneInto(i), live: () => phRev,
              open: () => phFetch(null, true) },
  runner:   { multi: false, label: () => "CI runner",
              icon: TOOL_ICONS.runner,
              render: (i) => renderRunnerInto(i), live: () => `${nodesRev}/${(state?.node_runners || []).length}`,
              open: () => loadNodes() },
  // The install key and what is kept under it (R154).
  keys:     { multi: false, label: () => "Keys",
              icon: TOOL_ICONS.keys,
              render: (i) => renderKeysInto(i), live: () => keysRev,
              open: () => loadKeys() },
  // Who did what to this install (R158 step 8).
  audit:    { multi: false, label: () => "Audit",
              icon: TOOL_ICONS.audit,
              render: (i) => renderAuditInto(i), live: () => auditRev,
              open: () => loadAudit() },
  network:  { multi: false, label: () => "Network",
              icon: TOOL_ICONS.network,
              render: (i) => renderNetworkInto(i), live: () => settingsLive() + nodesRev,
              open: () => loadNodes() },
  machine:  { multi: false, label: () => "This machine",
              icon: TOOL_ICONS.machine,
              render: (i) => renderMachineInto(i), live: () => nodesRev,
              open: () => loadNodes() },
  settings: { multi: false, label: () => "Controller settings",
              render: (i) => renderSettingsInto(i), live: settingsLive,
              open: () => loadApps() },
  users:    { multi: false, label: () => "Users",
              render: (i) => renderUsersInto(i), live: () => usersRev,
              open: () => loadUsers() },
  roles:    { multi: false, label: () => "Roles",
              render: (i) => renderRolesInto(i), live: () => rolesRev,
              open: () => loadRoles() },
  profile:  { multi: false, label: () => "Profile",
              render: (i) => renderProfileInto(i), live: () => `${profileRev}/${keyMineRev}`,
              open: () => loadProfile() },
  apps:     { multi: false, label: () => "Apps",
              render: (i) => renderAppsInto(i), live: () => devAppsRev,
              open: () => loadApps() },
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

// No tooltips (the operator, 11 Oct: a hover box was clipped by the pane it
// sat in, and a phone has no hover). The words a `title` carries are kept for
// a screen reader and never drawn: an element with no text of its own (an
// icon button, a swatch, a field) is named by them, and one with text is
// described by them. One observer over the page does it to whatever any
// draw writes, so no surface needs to remember to.
function untitle(el){
  const s = el.getAttribute("title");
  el.removeAttribute("title");
  if (!s) return;
  const named = el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby") || el.labels?.length
    || (el.textContent || "").trim();
  setAttr(el, named ? "aria-description" : "aria-label", s);
}
function untitleIn(root){
  if (root.nodeType !== 1) return;
  if (root.hasAttribute("title") && !(root instanceof SVGElement)) untitle(root);
  root.querySelectorAll("[title]").forEach(el => { if (!(el instanceof SVGElement)) untitle(el); });
}
function untitleWatch(){
  untitleIn(document.body);
  new MutationObserver(ms => {
    for (const m of ms){
      if (m.type === "attributes"){ if (m.target.hasAttribute("title") && !(m.target instanceof SVGElement)) untitle(m.target); }
      else m.addedNodes.forEach(untitleIn);
    }
  }).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["title"]});
}

// A ? and its words in a tooltip beside it (the operator, 26 Oct, where on
// 11 Oct they were a line on the page: a tooltip then was clipped by the
// pane it sat in and a phone never showed one). Fixed to the window, so no
// pane clips it, under the ? or above it near the screen's foot, inside the
// screen's edges; a press on the ? (a tap on a phone) opens and shuts it,
// never a hover (the operator, 26 Oct: a press works on a phone too), and a
// press elsewhere, Escape or a scroll shuts it. One at a time.
let helpAt = null;
function helpShow(h){
  const words = h.dataset.help || h.getAttribute("aria-label") || "";
  if (!words) return;
  let tip = document.getElementById("helpPop");
  if (!tip){
    tip = document.createElement("div");
    tip.id = "helpPop"; tip.className = "helppop"; tip.setAttribute("role", "tooltip");
    document.body.appendChild(tip);
  }
  if (helpAt && helpAt !== h) helpHide();
  helpAt = h;
  tip.textContent = words;
  tip.hidden = false;
  h.classList.add("on");
  h.setAttribute("aria-expanded", "true");
  h.setAttribute("aria-describedby", "helpPop");
  const r = h.getBoundingClientRect(), t = tip.getBoundingClientRect(), gap = 6, edge = 8;
  const below = r.bottom + gap + t.height <= innerHeight - edge || r.top - gap - t.height < edge;
  tip.style.top = `${Math.round(below ? r.bottom + gap : r.top - gap - t.height)}px`;
  tip.style.left = `${Math.round(Math.max(edge, Math.min(r.left + r.width / 2 - t.width / 2, innerWidth - edge - t.width)))}px`;
}
function helpHide(){
  const tip = document.getElementById("helpPop");
  if (tip) tip.hidden = true;
  if (helpAt){ helpAt.classList.remove("on"); helpAt.setAttribute("aria-expanded", "false"); helpAt.removeAttribute("aria-describedby"); }
  helpAt = null;
}
function helpToggle(h){
  if (helpAt === h) return helpHide();
  helpShow(h);
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
// ...and an action bar's More menu (R210) holds a redraw the same way: a
// repaint while it is open drew the row again with the menu shut, under
// the finger that had just opened it.
function openPopup(){
  return openMenu() || document.querySelector(".actmenu:not([hidden])");
}
function menuHolds(root){
  const m = openPopup();
  if (!m || (root && !root.contains(m))) return false;
  if (!menuTimer) menuTimer = setInterval(() => {
    if (openPopup()) return;
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
  try{
    const f = typingIn(i);
    spec.render(i, t);
    typingBack(i, f);
    // ...and its jump bar, whatever it drew: a page waiting on its read
    // draws its sections' template, and waits as itself with the bar the
    // loaded page will have (sectJump; the templates rule).
    $("doc" + i)?.querySelectorAll(".doctab, .nbview:not([hidden])").forEach(v => sectJump(v));
  }
  catch(e){
    const el = $("doc" + i);
    if (el) el.innerHTML = `<div class="hint bad" data-style="padding:var(--row-y) var(--row-x)">
      this tab's renderer failed: the rest of the page is fine.
      ${esc(String(e && e.message || e))}</div>`;
    setTimeout(() => { throw e; });
  }
}

// A box being typed in keeps the caret across its page's redraw (B156,
// B158): the page writes the box again with what was typed (each page keeps
// its fields' values), but the focus stayed on the box the redraw threw
// away, so the next keys went nowhere, and a paste landing in that moment
// was lost. Found by id, so only a box the page names; given back only when
// the redraw left nothing else focused.
function typingIn(i){
  const a = document.activeElement, doc = $("doc" + i);
  if (!a?.id || !doc?.contains(a) || !/^(INPUT|TEXTAREA)$/.test(a.tagName)) return null;
  let s = null, e = null;
  try{ s = a.selectionStart; e = a.selectionEnd; }catch(x){ /* a box with no caret */ }
  return {id: a.id, s, e};
}
function typingBack(i, f){
  if (!f) return;
  const a = document.activeElement;
  if (a && a !== document.body && a.isConnected) return;
  const el = $("doc" + i)?.querySelector("#" + CSS.escape(f.id));
  if (!el || el.disabled) return;
  el.focus({preventScroll: true});
  try{ if (typeof f.s === "number") el.setSelectionRange(f.s, f.e ?? f.s); }catch(x){ /* a box with no caret */ }
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
  // A Claude tab whose frame was built before its machine restarted carries
  // that run's boot, and bb-tty refuses it, rightly for a frame reconnecting
  // on its own. A press is the decision the refusal asks for, so the frame
  // is built again with the machine's boot now: kept, every press after a
  // crash reopened the refusal that said to press it (19 Oct).
  if (isClaude(t) && t.frameBoot !== undefined && t.frameBoot !== bootFor(t.arg))
    t.gen = (t.gen || 0) + 1;
  // The boot it was opened under, for the restart check on the poll: a tab
  // opened AFTER the machine came back is not one from before it. Stamped
  // here rather than only where a tab is CREATED, because a second click on
  // Claude for something already open takes the other branch, and an
  // unstamped tab read as "from before", which dropped the tab the operator
  // had just opened.
  if (agentOfArg(t.arg) && t.boot === undefined)
    t.boot = bootFor(t.arg);
  // A terminal goes to the dock and anything else is the page on show
  // (R218 step 4): there is no strip and no second pane to choose.
  dockPlace(t);
  show(t);
}

// Each terminal tab is a full xterm.js over its own websocket. Past a point the page stops being usable and the container is
// carrying sessions nobody is reading, so refuse rather than degrade.
// Only terminals count (R78): a document tab is a draw from state and costs
// nothing to keep, so a Nodes tab beside twelve shells was never the load
// the cap is about. The count is this account's own strip, which is what
// `tabs` is: the layout is kept per account on the server.
function roomForTab(kind){
  if (kind !== "term") return true;
  const cap = state?.max_tabs || 12;
  if (tabs.filter(t => t.kind === "term").length < cap) return true;
  notify(`Terminal tab limit reached (${cap} shells and agents' sessions). Close or minimize `
       + `one first; a minimized tab keeps running.`, true);
  return false;
}

function focusTab(id){
  const t = tabOf(id);
  if (!t) return;
  dockPlace(t);
  show(t);
}

// Common tail of "make this tab the one being looked at".
function show(t){
  render();
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

// Put a tab away: a terminal off the dock's line, a page closed. Nothing is
// destroyed and nothing is asked: a terminal keeps running and is listed
// under Sessions, a document is a view of a file on disk. Ending a session for good is the ✕ in the Sessions card,
// which is where a question is worth asking because something is actually lost.
async function hideTab(id, ev){
  ev?.stopPropagation();
  const t = tabOf(id);
  if (!t) return;
  if (t.kind === "notebook"){
    // Closing a notebook's tab ends its instance: whatever was staged in it
    // was just answered for, and reopening reads fresh from disk.
    const nb = notebooks.get(t.arg);
    if (nb && !await nb.leaving()) return;
    nb?.destroy();
  }
  dropTab(id);
  refresh();
}

// Remove a tab and repair the layout: a pane it was in falls back to the other
// one, then to whatever tab is still open, then to nothing, which drawPanes
// renders as a placeholder rather than this function preventing.
function dropTab(id){
  tabs = tabs.filter(x => x.id !== id);
  for (let i = 0; i < 2; i++) if (panes[i] === id) panes[i] = null;
  // The dock keeps the next terminal, if there is one; the page falls back
  // to another (dockSettle, on the render).
  if (panes[1] === null){
    const next = tabs.find(t => slotFor(t) === 1);
    if (next) panes[1] = next.id;
    else active = 0;
  }
  render();
}

// ---- a terminal in its own window (R8) ------------------------------------

// tmux attaches many clients to one session by design; what it does not do
// is size a session for two of them, so the tab here must not stay a live
// terminal while the window has it: its socket is closed and the pane
// shows a placeholder with Reattach. The window is the terminal's own page,
// its own /termws connection, so closing this page leaves it working, and the
// session outlives both. Desktop only: a phone has nowhere to put a window.
function popOut(id, ev){
  ev?.stopPropagation();
  const t = tabOf(id);
  if (!t || t.kind !== "term" || isPhone()) return;
  const w = window.open(tabUrl(t.arg, tabLabel(t)), "bb-pop-" + id, "popup=yes,width=1000,height=640");
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
