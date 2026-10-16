// The Tools tab: what is installed on a node, and installing or removing it
// there. Its own classic script beside index.html, per the new-surface rule
// (docs/nodes.md §13): same page, same global scope, one file per surface
// (roadmap R55 step 4).
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. The catalog is config/toolchains.json, read
// through /api/toolchains; an install is a JOB on the node, so the list keeps
// reporting progress rather than freezing on a request that cannot return.
//
// Moved out of index.html unchanged. Loaded BEFORE the page's own script, so
// everything here is a declaration and nothing runs at load.

// ---- toolchains --------------------------------------------------------
// The Tools card's other half, opened as a document tab beside the findings
// report rather than a dialog: installing an SDK is not a detour to dismiss,
// it is a thing to leave open for the several minutes it runs, and a tab can
// be pinned to a pane, minimized, or left on the strip while you work.
//
// Installs are queued by the server and polled from here, so the list keeps
// reporting progress instead of freezing on a request that cannot return.

"use strict";

let toolchains = null, tcRev = 0, tcPoll = null;
const tcTicked = new Set();     // survives a redraw; a poll must not untick

function openToolchains(){
  openTab({kind:"toolchains", arg:"__toolchains", label:"Toolchains"});
}
// ...on a node somebody named: the Nodes tab's GPU line sends its reader to
// the driver's row here.
function openToolchainsOn(id){
  tcNode = id; toolchains = null; tcTicked.clear(); tcDriverPick = "";
  // A node this page has not listed yet (enrolled a moment ago, named by the
  // bell before the poll said the nodes moved) is read for first, or tcPick
  // took it for a retired one and showed another node (B754).
  if (!(nodesList || []).some(n => n.id === id)) nodesStale = true;
  try{ localStorage.setItem("bb.tcnode", id); }catch(e){ /* private */ }
  openToolchains();
  loadToolchains();
}

// The sizes are measured by a worker on the server, so the first draw after
// an install (or after a restart) carries the catalog's estimates and the
// real numbers land a moment later. One follow-up ask while that is true,
// not a poll: the flag clears when the measurement finishes, and nothing else
// on this tab changes on its own.
let tcSizeTimer = null;
async function loadToolchains(){
  const asked = ++tcLoadSeq;
  if (nodesList === null || nodesStale) await loadNodes();
  if (asked !== tcLoadSeq) return;           // the node changed under this load
  if (!tcPick()){
    toolchains = {nonode: true};
    clearTimeout(tcSizeTimer); tcSizeTimer = null;
    tcRev++; drawPanes();
    return;
  }
  try{
    const r = await fetch("/api/toolchains" + (tcNode !== "local" ? `?node=${encodeURIComponent(tcNode)}` : ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (asked !== tcLoadSeq) return;
    toolchains = got;
  }catch(e){ if (asked !== tcLoadSeq) return; toolchains = {error: String(e)}; }
  clearTimeout(tcSizeTimer); tcSizeTimer = null;
  // ...and while Claude Code's own job runs (R145), which is not a toolchain
  // job and so moves nothing the tab waits on otherwise.
  if (toolchains && toolchains.sizing) tcSizeTimer = setTimeout(loadToolchains, 1500);
  else if ((toolchains?.machine || []).some(m => m.running)) tcSizeTimer = setTimeout(loadToolchains, 3000);
  tcRev++;
  drawPanes();
}

// The animated ellipsis. One counter for the tab, ticked on its own timer and
// written straight into the spans, so the once-a-second redraw neither
// restarts it nor resets it: a rebuild simply renders the count it is on.
let tcDots = 0, tcDotsTimer = null;
// Every animated ellipsis on the page, not just the toolchains tab's: the
// Projects card grew one when clones moved to a background job, and two
// tickers running at different phases would read as a fault.
// Which node the Tools tab is showing (docs/nodes.md §6): an agent node's
// toolchain store, where an install is a job. Empty until tcPick() chooses
// one, and empty when there is none to choose: toolchains are installed on
// NODES (roadmap #26), and this container is never offered: what it keeps is
// the Playwright browsers its boot hook put on its store for bb capture shot, and no
// button reaches its installer. "local" is still what that installer is
// called (`bb toolchains install` from a shell and the suite address it) but
// nothing on this page sets it.
let tcNode = "";
let tcLoadSeq = 0;         // a load that lands after the node changed is dropped

// The node the tab opens on: the one it showed last (remembered in this
// browser), else the first live agent node, else nothing. Re-asked on every
// load, so a node that was retired under the tab is not shown as if it were
// still there.
function tcPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  if (tcNode === "local") return tcNode;
  let want = tcNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.tcnode") || ""; }catch(e){ want = ""; }
  }
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  tcNode = want;
  return tcNode;
}

// What the one job is doing: the bar's own state, where "versions checked"
// sits when nothing runs, by the toolchain's name on its row and how far
// through the batch it is. It was a green line of its own between the
// buttons, naming the recipe's id (the operator, 6 Oct: "Installing ndk...").
const tcWorking = (job, items) => {
  const verb = {install: "Installing", remove: "Removing", update: "Updating",
                check: "Checking"}[job.action] || "Working on";
  const row = (items || []).find(i => i.name === job.current);
  const what = job.action === "check" ? "for updates"
    : row?.label || (job.current || "").replace(/^android:/, "");
  const done = (job.done || []).length + (job.failed || []).length + (job.passed || []).length,
        left = (job.queue || []).length;
  const of = job.action !== "check" && done + left > 0 ? `, ${done + 1} of ${done + left + 1}` : "";
  return `<span class="state tcworking">${esc(verb)} ${esc(what)}${of}<span class="dots"></span></span>`;
};

function tcTickDots(){
  const spans = document.querySelectorAll(".dots");
  if (!spans.length){ clearInterval(tcDotsTimer); tcDotsTimer = null; return; }
  tcDots = (tcDots + 1) % 4;
  spans.forEach(e => e.textContent = ".".repeat(tcDots));
}

// What a row pulls onto the picked machine from its own package manager,
// named, so which tool needed which library is on the row before Install
// rather than in a job log after it. Held ones say which are missing here.
// Whether the picked node was provisioned as a sandbox, which is the one
// condition the server takes a sysdeps action under (toolchains.py); read
// off the payload each draw so the row's repair and the tab's banner agree.
let tcSandboxNow = false;
function tcSystemLine(p, managed){
  const sys = p.system;
  if (!sys?.names?.length) return "";
  const n = sys.names.length, plural = n === 1 ? "" : "s";
  const miss = sys.missing || [];
  // An entry naming alternatives ("libasound2t64|libasound2") is whichever
  // this machine's release carries; a missing one is already the one it takes.
  const show = (miss.length ? miss : sys.names).map(x => x.split("|").join(" or "));
  const list = show.length <= 6 ? esc(show.join(", "))
    : `${esc(show.slice(0, 4).join(", "))}<details class="tcsysl"${sectAttr(`toolchains:sysl:${tcNode}|${p.name}`)}><summary> and ${show.length - 4} more</summary>, ${
        esc(show.slice(4).join(", "))}</details>`;
  const head = !p.installed ? `Installs ${n} system package${plural} with it here (${esc(sys.manager)})`
    : miss.length ? `${miss.length} of its ${n} system package${plural} missing here (${esc(sys.manager)})${
        managed ? ", installed by itself" : ", for this machine's owner to install"}`
    : `Uses ${n} system package${plural} here (${esc(sys.manager)}), all installed`;
  // The repair, on the row that needs it: one press puts this row's missing
  // packages on the node and leaves the toolchain alone. Only where the
  // agent administers the machine; a guest node's owner installs them.
  const fix = p.installed && miss.length && tcSandboxNow && mayToolchains()
    ? ` <button type="button" class="link" data-tcsys="${esc(p.name)}">Install them now</button>` : "";
  return `<span class="sub tcsysd${miss.length ? " warn" : ""}">${head}: ${list}.${fix}</span>`;
}

// A toolchain this one needs that is not on this node: what it runs on was
// removed since, or never arrived. Said on the row, with that row's own
// install one press away.
function tcNeedsLine(p){
  const gone = p.needs_missing || [];
  if (!gone.length) return "";
  return `<span class="sub warn tcneed">Needs ${esc(gone.join(", "))}, which ${gone.length === 1 ? "is" : "are"} not installed here.${
    mayToolchains() ? gone.map(n => ` <button type="button" class="link" data-tcneed="${esc(n)}">Install ${esc(n)}</button>`).join("") : ""}</span>`;
}

// What installing a toolchain is under, on its own row (the operator, 7
// Oct): an agreement Install accepts said as one, then the licenses.
function tcTermsLine(p){
  const link = t => `<a href="${esc(t.url)}" target="_blank" rel="noreferrer">${esc(t.label)}</a>`;
  const acc = (p.terms || []).filter(t => t.accept), lic = (p.terms || []).filter(t => !t.accept);
  if (!acc.length && !lic.length) return "";
  return `<span class="sub tcterms">${acc.length ? `Installing it accepts ${acc.map(link).join(" and ")}.` : ""}${
    acc.length && lic.length ? " " : ""}${lic.length ? `Licensed: ${lic.map(link).join(", ")}.` : ""}</span>`;
}

function tcRow(p, busy, job, managed){
  // The row the job is *writing*. Mid-install its directory exists and every
  // probe here calls a non-empty directory installed, so it wears none of the
  // furniture that means "this is here": no ticked box, no uninstall control,
  // no path; it says what it is doing instead.
  //
  // A check is not writing. It reads thirteen upstreams and changes nothing on
  // disk, so stripping each row in turn as it passed made the whole tab churn
  // for the eight seconds of a check, including the one that now runs by
  // itself once a day, where nobody asked for anything at all.
  const mine = !!(job && job.running && job.action !== "check"
                  && job.current === p.name);
  // A tick means "do something to this". Something installed and current has
  // nothing to do, so its box is dead until a check finds an update, which
  // is also why Install is the only verb here: on a row with an update it
  // updates, and the operator never has to know which button to reach for.
  const upToDate = !mine && p.installed && p.state !== "update";
  // An installed toolchain whose recipe cannot update in place. The check can
  // still say a newer version exists (it asks upstream, not the recipe) and
  // before this the row let you tick it and then died on `bb toolchains update`'s
  // usage line, naming five toolchains you had not asked about (bug #43).
  // ...unless a check found a newer version: then the box is live, and the
  // job removes the old one and installs the new (R193, the operator, 11 Oct).
  const noUpgrade = !mine && p.installed && !p.updatable && p.state !== "update";
  // Three versions can be on a row and only ever two at once: what is
  // installed, what an update would move it to, and, on a row that has never
  // been installed: what Install would fetch. Only the middle one is yellow,
  // because only it is news; a version on an absent row is just a fact about
  // the shelf, and coloring six of them amber would be crying wolf.
  const ver = p.version && p.version !== "-"
    ? ` <span class="pill" title="installed">${esc(p.version)}</span>` : "";
  // Only on a row that has nothing installed, where it is the one version
  // worth showing: what Install would fetch. An installed row that is behind
  // says so in words underneath: an amber arrow pointing at a number was one
  // more thing to decode on a line that already has two.
  const next = !p.installed && p.latest && p.latest !== "-"
    ? ` <span class="pill" title="what Install selected would fetch">${esc(p.latest)}</span>`
    : "";
  // A recipe that cannot update in place says what does, on the row: its box
  // is locked as installed, and "tick it" was an instruction it could not
  // follow (the operator, 6 Oct, on JDK 21).
  const upd = p.state === "update"
    ? `<span class="sub upd">update available: tick it and press Install selected${
        p.updatable ? "" : "; it is removed and installed again"}</span>`
    : "";
  // What went wrong, on the row it went wrong on. This is what the scrolling
  // log at the foot of the tab was for, minus the ninety-nine lines of
  // progress frames it took to say it. Cleared when this toolchain is tried
  // again, because by then it describes a state that no longer holds.
  const err = job?.errors?.[p.name] && !mine
    ? `<span class="sub bad">${esc(job.errors[p.name])}</span>` : "";
  // One word and an ellipsis, for as long as it takes. No percentage is read
  // out of a job at all: every recipe meters differently and several mislead
  // by accident: sdkmanager counts one fraction across a whole operation and
  // parks it for minutes, playwright meters five files from zero apiece,
  // rustup reports nothing at all down a pipe, and a row relaying any of
  // that faithfully still read as a bar that had broken. If it fails, the row
  // says so underneath; that is the only time the output was ever wanted.
  const doing = job && job.action === "remove" ? "removing"
              : job && job.action === "check" ? "checking" : "installing";
  const prog = `<span class="sub prog plain">${esc(doing)}<span class="dots">${
    ".".repeat(tcDots)}</span></span>`;
  // A line of the table (R218 step 8): the tick and the name with what it
  // is under it, then what is installed (or what the job is doing), what
  // Install would fetch, its size, the projects that pin it, and its
  // uninstall at the end. What is news about it is under the line.
  const pins = (p.pinned_by || []).map(projLabel);
  return `<label class="tc${upToDate ? " done" : ""}">${tblLine(TC_COLS, [
    `<input type="checkbox" value="${esc(p.name)}"${
      busy || noUpgrade ? " disabled" : ""}${
      noUpgrade ? ` checked disabled title="installed; no update in place: a newer version, once a check finds one, is installed in its place"`
      : upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(p.name) ? " checked" : ""}>
    <span class="grow">
      <span class="nm">${esc(p.label)}</span>
      <span class="sub">${esc(p.about)}${
        p.tool ? ` Adds <code>bb tool ${esc(p.tool)}</code> to a session.` : ""}${
        p.needs?.length ? ` Needs ${esc(p.needs.join(", "))}, installed with it.` : ""}${
        p.needed_by?.length ? ` Needed by ${esc(p.needed_by.join(", "))}.` : ""}</span>
      ${tcTermsLine(p)}
      ${tcSystemLine(p, managed)}
      ${tcNeedsLine(p)}
      ${p.installed && p.path && !mine ? `<span class="sub tcpath">at ${esc(p.path)}</span>` : ""}
    </span>`,
    // Whatever version is known, installed or reported: a node's own
    // versions can name one its census summary does not.
    mine ? prog : `<span class="where${p.installed ? " on" : ""}">${ver || (p.installed ? "installed" : "not installed")}</span>`,
    next, p.size ? `<span class="pill" title="${esc(p.size_from)}">${esc(p.size)}</span>` : "",
    pins.length ? `<span title="${esc(pins.join(", "))}">${esc(pins.join(", "))}</span>` : "",
    p.installed && !mine ? `<button class="eye rm" data-rm="${esc(p.name)}" aria-label="uninstall ${esc(p.label)}"${
      busy ? ` disabled title="another toolchain operation is running"`
           : ` title="uninstall ${esc(p.label)}"`}>${BIN}</button>` : ""], "span", "tcline")}
    ${upd}${err}${
      // Sessions that started before this landed still have the old PATH
      // (toolchains.py counts them); one line, and only while there are any.
      p.reopen && !mine ? `<span class="sub warn tcreopen">${p.reopen === 1 ? "1 session" : `${p.reopen} sessions`}
        open here started before this was installed: reopen ${p.reopen === 1 ? "it" : "them"} to use it</span>` : ""}
  </label>`;
}
const TC_COLS = [{label: "Toolchain", w: "minmax(0,2fr)"}, {label: "Installed", w: "minmax(0,.6fr)"}, {label: "Latest", w: "6.5rem"},
                 {label: "Size", w: "5.5rem", num: true}, {label: "Pinned by", w: "minmax(0,.5fr)"}, {act: true, w: "2.75rem"}];

// The NVIDIA driver (R102): a row like the store's, ticked into the same
// Install selected and asked by the same Check for updates, but this
// machine's own: its kernel module is built for this machine's kernel and
// its libraries must match that module, so it is installed here as root and
// takes the card only when the machine restarts, since nouveau holds it
// until then. Its pulldown is the branches apt offers there, live only
// while no driver is installed: one branch at a time, so another version
// means removing this one first (the operator, 30 Sep), the rule a recipe
// that cannot update in place already keeps.
const TC_DRIVER = "nvidia-driver";
let tcDriverPick = "";       // the package picked on the row; "" is the recommended one
function tcDriverLine(m){
  const nodesBtn = ` <button type="button" class="link" data-tcnodes>Open the Nodes tab</button>`;
  switch (m.state){
    case "absent": return `<span class="sub where">not installed: nouveau has the card, so nothing here can compute on it</span>`;
    case "waiting": return `<span class="sub warn">installed; it takes the card when the machine restarts, which Reboot on the node's row does and which ends every session there.${nodesBtn}</span>`;
    case "update": return `<span class="sub warn">${esc(m.installed)} is installed and takes over from ${esc(m.loaded)} when the machine restarts.${nodesBtn}</span>`;
    case "leaving": return `<span class="sub warn">removed; it keeps the card until the machine restarts, when nouveau takes it back.${nodesBtn}</span>`;
    case "loaded": return `<span class="sub where on">installed, and running the card</span>`;
    default: return `<span class="sub warn">this node's agent does not report the driver yet: update it on the Nodes tab.${nodesBtn}</span>`;
  }
}
// One option's words: the version first, since that is what is being
// chosen, then what kind of branch it is.
function tcDriverOption(o, m){
  const branch = (o.pkg.match(/-(\d{3})/) || [])[1] || "";
  const rec = (m.recommended.match(/-(\d{3})/) || [])[1] || "";
  const tags = [o.open ? "open kernel modules" : "",
    o.pkg === m.recommended ? "recommended for this card" : "",
    rec && branch && +branch > +rec ? "newer than recommended" : ""].filter(Boolean);
  return `${o.version}${tags.length ? " · " + tags.join(", ") : ""}`;
}
function tcDriverRow(m, busy, job){
  const card = m.gpu || (String(m.card).match(/\[([^\]]*(?:GeForce|RTX|Quadro|Tesla|TITAN)[^\]]*)\]/)?.[1]) || m.card;
  const ver = m.installed || m.loaded;
  const mine = !!(job && job.running && job.action !== "check" && job.current === TC_DRIVER);
  const doing = job && job.action === "remove" ? "removing" : "installing";
  const may = m.managed && mayToolchains() && m.state !== "unknown";
  // A tick means "do something to this": install it where there is none,
  // update it where apt has a newer one. Installed and current, its box is
  // dead and ticked, as a toolchain's is.
  const upToDate = !mine && m.here && !m.newer;
  const opts = m.options || [];
  const picked = m.here ? m.package : (opts.some(o => o.pkg === tcDriverPick) ? tcDriverPick : "");
  const sel = opts.length ? `<label class="pick tcdrvpick">Version <select id="tcDrvSel" aria-label="driver version"${
      m.here || busy || !may ? " disabled" : ""}${
      m.here ? ` title="installed: remove it first to install another version"` : ""}>
      ${m.here ? "" : `<option value=""${picked ? "" : " selected"}>${esc(m.recommended
          ? tcDriverOption(opts.find(o => o.pkg === m.recommended) || {pkg: m.recommended, version: "recommended"}, m)
          : "the one recommended for this card")}</option>`}
      ${opts.filter(o => m.here || o.pkg !== m.recommended).map(o => `<option value="${esc(o.pkg)}"${
          o.pkg === picked ? " selected" : ""}>${esc(tcDriverOption(o, m))}</option>`).join("")}
    </select></label>` : "";
  return `<div class="tc tcdrv${upToDate ? " done" : ""}">
    <input type="checkbox" id="tcDrvTick" value="${TC_DRIVER}" aria-label="NVIDIA driver"${
      busy || !may ? " disabled" : ""}${
      upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(TC_DRIVER) ? " checked" : ""}>
    <span class="grow">
      <label class="nm" for="tcDrvTick">${esc(m.label)}${ver ? ` <span class="pill" title="${m.installed ? "installed" : "loaded"}">${esc(ver)}</span>` : ""}</label>
      <span class="sub">For this machine's ${esc(card)}: CUDA, the hardware video encoder and the emulator's GPU rendering need it. It is this machine's own, not a copy on the store.</span>
      ${sel}
      ${mine ? `<span class="sub prog plain">${esc(doing)}<span class="dots">${".".repeat(tcDots)}</span></span>` : tcDriverLine(m)}
      ${m.newer && !mine ? `<span class="sub upd">update available: ${esc(m.newer)}. Tick it and press Install selected</span>` : ""}
      ${job?.errors?.[TC_DRIVER] && !mine ? `<span class="sub bad">${esc(job.errors[TC_DRIVER])}</span>` : ""}
      ${!m.managed ? `<span class="sub warn">This machine is its owner's, not a BuilderBot sandbox: its driver is installed there by hand.</span>` : ""}
    </span>
    ${m.here && !mine && may ? `<button class="eye rm" data-tcdrvrm aria-label="uninstall the NVIDIA driver"${
      busy ? ` disabled title="another toolchain operation is running"`
           : ` title="remove NVIDIA's driver from this machine"`}>${BIN}</button>` : ""}
  </div>`;
}

// The NVIDIA container toolkit (R102): the second of the machine's own
// rows, under the driver it needs. It is what lets a container on this
// machine reserve the card, and comes from NVIDIA's package source rather
// than the distribution's, which is said before it is added. Docker
// reloads its configuration for it; no container stops.
const TC_TOOLKIT = "nvidia-container-toolkit";
function tcToolkitLine(m){
  const nodesBtn = ` <button type="button" class="link" data-tcnodes>Open the Nodes tab</button>`;
  switch (m.state){
    case "absent": return `<span class="sub where">not installed: a container here cannot reserve the card${
      m.driver ? "" : ". It needs the driver above: tick both, and the driver goes on first"}</span>`;
    case "unconfigured": return `<span class="sub warn">installed, but Docker here does not list the nvidia runtime: tick it and press Install selected, which configures Docker again</span>`;
    case "ready": return m.driver_loaded
      ? `<span class="sub where on">installed: a compose file reserves the card with deploy.resources.reservations.devices (driver: nvidia)</span>`
      : `<span class="sub warn">installed; a container sees the card once the driver above is running it</span>`;
    default: return `<span class="sub warn">this node's agent does not report the container toolkit yet: update it on the Nodes tab.${nodesBtn}</span>`;
  }
}
function tcToolkitRow(m, busy, job){
  const mine = !!(job && job.running && job.action !== "check" && job.current === TC_TOOLKIT);
  const doing = job && job.action === "remove" ? "removing" : "installing";
  const may = m.managed && mayToolchains() && m.state !== "unknown";
  // Ticked and dead where it is installed, current and known to Docker;
  // live where a tick has something to do (install, update, configure).
  const upToDate = !mine && m.state === "ready" && !m.newer;
  return `<div class="tc tcdrv${upToDate ? " done" : ""}">
    <input type="checkbox" id="tcCtkTick" value="${TC_TOOLKIT}" aria-label="NVIDIA container toolkit"${
      busy || !may ? " disabled" : ""}${
      upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(TC_TOOLKIT) ? " checked" : ""}>
    <span class="grow">
      <label class="nm" for="tcCtkTick">${esc(m.label)}${m.installed ? ` <span class="pill" title="installed">${esc(m.installed.split("-")[0])}</span>` : ""}</label>
      <span class="sub">Lets a container on this machine use the card. From NVIDIA's own package source, which installing adds and removing takes away. Running containers keep running.</span>
      ${mine ? `<span class="sub prog plain">${esc(doing)}<span class="dots">${".".repeat(tcDots)}</span></span>` : tcToolkitLine(m)}
      ${m.newer && !mine ? `<span class="sub upd">update available: ${esc(m.newer.split("-")[0])}. Tick it and press Install selected</span>` : ""}
      ${job?.errors?.[TC_TOOLKIT] && !mine ? `<span class="sub bad">${esc(job.errors[TC_TOOLKIT])}</span>` : ""}
      ${!m.managed ? `<span class="sub warn">This machine is its owner's, not a BuilderBot sandbox: the toolkit is installed there by hand.</span>` : ""}
    </span>
    ${m.here && !mine && may ? `<button class="eye rm" data-tcctkrm aria-label="uninstall the NVIDIA container toolkit"${
      busy ? ` disabled title="another toolchain operation is running"`
           : ` title="remove the container toolkit from this machine"`}>${BIN}</button>` : ""}
  </div>`;
}

// Claude Code, the session account's (R145): a row like the store's, with
// its own job behind it, which ends the node's Claude sessions before it
// swaps the binary. A session cannot start on a node without it, so the
// row says so where it is missing.
const TC_CLAUDE = "claude-code";
function tcClaudeRow(m, busy){
  const mine = !!m.running;
  const doing = m.action === "remove" ? "removing" : m.here ? "updating" : "installing";
  const may = mayToolchains();
  const upToDate = !mine && m.state === "current";
  const line = mine ? `<span class="sub prog plain">${esc(doing)}<span class="dots">${".".repeat(tcDots)}</span></span>`
    : m.here ? `<span class="sub where on">installed</span>`
    : `<span class="sub where warn">not installed: a Claude session cannot start on this node until it is</span>`;
  return `<div class="tc tcdrv${upToDate ? " done" : ""}">
    <input type="checkbox" id="tcClaudeTick" value="${TC_CLAUDE}" aria-label="Claude Code"${
      busy || mine || !may ? " disabled" : ""}${
      upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(TC_CLAUDE) ? " checked" : ""}>
    <span class="grow">
      <label class="nm" for="tcClaudeTick">${esc(m.label)}${m.installed ? ` <span class="pill" title="installed">${esc(m.installed)}</span>` : ""}${
        !m.installed && m.latest ? ` <span class="pill" title="what Install selected would fetch">${esc(m.latest)}</span>` : ""}</label>
      <span class="sub">What a Claude session on this node runs, for the node's session account. Installing or updating it ends the Claude sessions here first; they start again from the project rows.</span>
      ${line}
      ${m.state === "update" && !mine ? `<span class="sub upd">update available: ${esc(m.latest)}. Tick it and press Install selected</span>` : ""}
      ${m.error && !mine ? `<span class="sub bad">${esc(m.error)}</span>` : ""}
    </span>
    ${m.here && !mine && may ? `<button class="eye rm" data-tcclrm aria-label="uninstall Claude Code"${
      busy ? ` disabled title="another toolchain operation is running"`
           : ` title="remove Claude Code from this node"`}>${BIN}</button>` : ""}
  </div>`;
}

function renderToolchainsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  // The pane is redrawn whole on every change, and a redraw put the
  // reader at the foot the moment Install was pressed,
  // with the row that was installing off screen. Where they were, kept.
  const keepScroll = el.scrollTop;
  queueMicrotask(() => { if (el.isConnected) el.scrollTop = keepScroll; });
  // Fills its pane like the notebook and the other document tabs, rather than
  // sitting on the darker ground with an inset, which is what made this one
  // look like a different kind of screen.
  el.classList.add("flush");
  const d = toolchains;
  // The shared scaffold, like every other document kind: the bar slot holds
  // the picker and the Refresh that re-reads it, so the action sits where a
  // tab's action sits rather than in a band this tab invented. `tc` makes the
  // tctab class the suite finds it by.
  const surf = docSurface(i, "tc");
  if (!surf) return;
  if (!d){ surf.list.innerHTML = `${skel("rows", 6)}`; return; }
  if (d.error){ surf.list.innerHTML = `<div class="empty">${
    esc("could not read the toolchain list: " + d.error)}</div>`; return; }
  // No node to install on. Not this container: it builds nothing and keeps
  // nothing but the browsers its boot put there, so there is no list to show
  // and no button that would be honest to offer.
  if (d.nonode){
    surf.setBar(`<span class="sp"></span>
      <button type="button" id="tcRefresh" title="look again for a node">Refresh</button>`);
    surf.list.innerHTML = `<div class="empty tcnone">No node yet. Toolchains install on a node:
        enroll one from the Nodes tab.</div>`;
    const pre = el.querySelector("#tcRefresh");
    if (pre) pre.onclick = () => { busy(pre, "Refreshing"); nodesList = null; toolchains = null; loadToolchains(); };
    return;
  }

  const job = d.job || {}, busy = !!job.running;
  // A finished toolchain loses its tick: whether it worked or not. One that
  // worked wears the permanent tick of a toolchain that is installed; one that
  // failed should not still be selected, because the next click might be
  // Remove and it was never there. Until then the tick stays put: through a
  // job, a ticked box says which toolchains this job is for.
  //
  // Except a check, which spends nothing: it asks about every row whether or
  // not anything is ticked, so treating its results as consumed selection
  // cleared a tick the operator had just placed: press check, and the thing
  // you were about to install quietly unticked itself.
  if (!busy && job.action !== "check")
    for (const n of [...(job.done || []), ...(job.failed || [])]) tcTicked.delete(n);
  // The picker: an agent node. Never this container (roadmap #26). Drawn
  // whenever there is a node, one included, so the tab always says whose
  // store it is showing.
  const pnodes = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  if (nodesList === null || nodesStale) loadNodes();
  const onNode = tcNode !== "local";
  // An install is a job on the node, so it waits for the same thing every
  // other agent job waits for: an agent this controller knows how to talk to.
  // The server refuses it either way (nodes.agent_stale); this is the reason,
  // said before the press rather than after it.
  const pstale = onNode && nodeStale(pnodes.find(n => n.id === tcNode) || {});
  // The one node switcher (page-docs.js nodePick, R121).
  surf.setBar(`${nodePick("tcNodeSel", pnodes, tcNode)}
    <span class="sp"></span>
    <button type="button" id="tcRefresh"
      title="read this store again: what is installed, and how big it is">Refresh</button>`);
  surf.list.innerHTML = `
    <div class="tchead">${onNode
      ? (d.root
          // Nothing here about a shared store. Several nodes pointing at one
          // share is an ordinary arrangement: three Linux sandboxes on one
          // NFS export is the obvious way to run this, and it works without
          // anybody being told. The one moment it matters is when a second
          // install is refused because one is already running across the
          // share, and that refusal says so at the press; a standing banner
          // on every draw was explaining a thing that needs no explaining.
          ? `Installed into <code>${esc(d.root)}</code> on ${esc(d.name)}${
              typeof d.free_mb === "number" ? `, ${d.free_mb >= 10240
                ? Math.round(d.free_mb / 1024) + "GB" : d.free_mb + "MB"} free` : ""}. An install
            is a job there.`
          : `${esc(d.name || "the node")} reports no toolchain store yet.`)
      : d.root
      ? (d.shared
          ? `Installed into <code>${esc(d.root)}</code>: a mapped share, so an image update never re-downloads them.`
          : `Installed into <code>${esc(d.root)}</code>: the home volume. Map a toolchain store to keep them out of it.`)
      : "No toolchain store found."}</div>
    ${pstale ? `<div class="tchead warn tcstale">${esc(staleWhy(
      pnodes.find(n => n.id === tcNode)))}. Nothing installs here until it is.</div>` : ""}
    ${
    // The store at a glance (R216): what is installed, what has an update
    // due, what a project needs that the store lacks, and the room left.
    (() => {
      const items = (d.items || []).filter(x => !x.wrong_platform);
      if (!items.length) return "";
      const due = items.filter(x => x.state === "update").length;
      const need = items.filter(x => (x.pinned_by || []).length && !x.installed).length;
      return statTiles([
        {label: "installed", value: items.filter(x => x.installed).length, sub: `of ${items.length} offered`},
        {label: "updates due", value: due, tone: due ? "warn" : "", omit: !due && !d.checked},
        {label: "needed by a project", value: need, tone: need ? "warn" : "", omit: !need},
        {label: "free", value: typeof d.free_mb === "number" ? (d.free_mb >= 10240 ? Math.round(d.free_mb / 1024) + "GB" : d.free_mb + "MB") : "",
         sub: "on the store", omit: typeof d.free_mb !== "number"},
      ]);
    })()}
    ${onNode && (d.cleanable || []).length && mayToolchains() ? `<div class="field"><div class="actbar tcclean"><span class="state">On this store and used by no node: ${
      d.cleanable.map(c => `<code>${esc(c.dir)}</code> (${esc(c.what)})`).join(", ")}</span><span class="sp"></span>
      <button type="button" class="danger" data-tcclean${busy ? " disabled" : ""}>Remove</button></div></div>` : ""}
    ${(() => {
      // Held recipes whose system libraries this machine lacks (roadmap
      // R51): the libraries are the machine's own, outside the store, and
      // can go missing while the toolchain stays. One press installs the
      // libraries and leaves the recipes alone.
      tcSandboxNow = !!(onNode && d.sandbox);
      const unmet = Object.entries((onNode && d.sysdeps?.unmet) || {});
      if (!unmet.length) return "";
      const what = unmet.map(([r, ps]) => `${esc(r)}: ${esc(ps.join(" "))}`).join("; ");
      return `<div class="tchead warn tcsys">System packages ${esc(d.name || "this node")} lacks
          for what its store holds (${esc(d.sysdeps.family || "")}): ${what}.
          ${d.sandbox
            ? `<button type="button" id="tcSysdeps"${busy || pstale ? " disabled" : ""}
                 title="install these on ${esc(d.name || "the node")} without reinstalling the toolchains">Install system packages</button>`
            : `This node's owner installs them: the agent does not administer the machine.`}</div>`;
    })()}
    ${onNode && (d.machine || []).length ? `<div class="tcs tcmachine">${
      d.machine.map(m => (m.name === TC_CLAUDE ? tcClaudeRow : m.name === TC_TOOLKIT ? tcToolkitRow : tcDriverRow)(m, busy || pstale || d.live === false, job)).join("")}</div>` : ""}
    ${tblWrap(TC_COLS, (d.items || []).filter(i => !i.wrong_platform)
      .map(i => tcRow(i, busy || pstale, job, !!d.administers && !d.locked)).join(""), "tcs")}
    <div class="actbar macros">
      ${busy ? tcWorking(job, d.items) : d.checked ? `<span class="state">versions checked ${ago(d.checked)}</span>` : ""}
      ${!mayToolchains() ? "" : `<button class="primary" data-tc="install"${busy || pstale ? " disabled" : ""}
        ${pstale ? `title="${esc(staleWhy(pnodes.find(n => n.id === tcNode)))}"` : ""}
        >Install selected</button>`}
      ${busy && mayToolchains() ? `<button data-tc="abort"${job.aborting ? " disabled" : ""}>${
        job.aborting ? "Stopping…" : "Abort"}</button>` : ""}
      <button data-tc="check"${busy || pstale || !mayToolchains() ? " disabled" : ""}
        title="ask each upstream what it has now">${
        busy && job.action === "check"
          ? `Checking for updates<span class="dots">${".".repeat(tcDots)}</span>`
        : (d.items || []).some(i => i.state) ? "Re-check for updates" : "Check for updates"}</button>
    </div>`;

  el.querySelectorAll(".tc input").forEach(b => b.onchange = () => {
    b.checked ? tcTicked.add(b.value) : tcTicked.delete(b.value);
  });
  el.querySelectorAll("[data-tc]").forEach(b => b.onclick = () => tcAct(b.dataset.tc));
  const psel = el.querySelector("#tcNodeSel");
  if (psel) psel.onchange = () => { tcNode = psel.value; toolchains = null; tcTicked.clear(); tcDriverPick = "";
                                    try{ localStorage.setItem("bb.tcnode", tcNode); }catch(e){ /* private */ }
                                    tcRev++; drawPanes(); loadToolchains(); };
  const pre = el.querySelector("#tcRefresh");
  if (pre) pre.onclick = () => { busy(pre, "Refreshing"); loadToolchains(); };
  const sd = el.querySelector("#tcSysdeps");
  if (sd) sd.onclick = () => tcAct("sysdeps");
  el.querySelectorAll("[data-tcsys]").forEach(b => b.onclick = () => tcAct("sysdeps", [b.dataset.tcsys]));
  // What no node runs from any more, taken off the store (R196).
  el.querySelectorAll("[data-tcclean]").forEach(b => b.onclick = async () => {
    const dirs = (toolchains?.cleanable || []).map(c => c.dir);
    if (!dirs.length || !confirm(`Take ${dirs.join(", ")} off the store?\n\nNo node runs from ${dirs.length === 1 ? "it" : "them"}; what is in ${dirs.length === 1 ? "it" : "them"} is gone for good.`)) return;
    busy(b, "Removing");
    const j = await (await postJSON("/api/toolchains", {action: "clean", node: tcNode, names: dirs})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify(`taking ${j.queued.join(", ")} off the store: a job on ${toolchains?.name || "the node"}`);
    loadToolchains();
  });
  el.querySelectorAll("[data-tcneed]").forEach(b => b.onclick = () => tcAct("install", [b.dataset.tcneed]));
  el.querySelectorAll("[data-tcnodes]").forEach(b => b.onclick = () => openNodesTab());
  const dsel = el.querySelector("#tcDrvSel");
  if (dsel) dsel.onchange = () => {
    // Picking a version is choosing to install it: the tick follows.
    tcDriverPick = dsel.value; tcTicked.add(TC_DRIVER);
    const t = el.querySelector("#tcDrvTick"); if (t && !t.disabled) t.checked = true;
  };
  el.querySelectorAll("[data-tcdrvrm]").forEach(b => b.onclick = () => {
    if (confirm(`Remove NVIDIA's driver from ${toolchains?.name || "this node"}? The emulator's GPU display goes with it, and nouveau takes the card back when the machine restarts.`))
      tcAct("remove", [TC_DRIVER]);
  });
  el.querySelectorAll("[data-tcclrm]").forEach(b => b.onclick = () => {
    if (confirm(`Remove Claude Code from ${toolchains?.name || "this node"}? Its Claude sessions end, and none starts there until it is installed again.`))
      tcAct("remove", [TC_CLAUDE]);
  });
  el.querySelectorAll("[data-tcctkrm]").forEach(b => b.onclick = () => {
    if (confirm(`Remove the NVIDIA container toolkit from ${toolchains?.name || "this node"}? A container that reserves the card no longer starts; NVIDIA's package source goes with it.`))
      tcAct("remove", [TC_TOOLKIT]);
  });
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = e => {
    // Inside a <label>, so the click would otherwise toggle the checkbox on
    // its way past.
    e.preventDefault(); e.stopPropagation();
    const name = b.dataset.rm;
    if (confirm(`Uninstall ${name}? The files are deleted; installing it again re-downloads them.`))
      tcAct("remove", [name]);
  });

  // No idle clock. Everything this tab draws that can move while nothing is
  // happening: the daily version check, or a toolchain installed from a
  // terminal: is in the `toolchains` token now, and
  // the revisions poll asks for that every second and a half along with the
  // rest of the page. The eight-second timer that used to cover it was one
  // tab noticing things sooner than the tab beside it for no reason anybody
  // chose.
  //
  // What survives is the SAMPLE, and it is a different thing from noticing a
  // change: while a job is actually running this tab is watching an operation
  // in flight, and a job on a small toolchain starts and finishes inside one
  // revision poll: the tab would go from idle to done having never said
  // "installing". Half a second is how often that is worth looking at, and it
  // stops the moment the job does.
  // After a job that touched the driver, or a check, the census that
  // follows is what says where the driver stands: asked again until it has
  // landed (settling).
  const drvSettling = (d.machine || []).some(m => m.settling) || !!d.store_settling;
  clearTimeout(tcPoll);
  if (busy)
    tcPoll = setTimeout(loadToolchains, 500);
  else if (drvSettling)
    tcPoll = setTimeout(loadToolchains, 2000);
  const ticking = busy;
  if (ticking && !tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
  if (!ticking && tcDotsTimer){ clearInterval(tcDotsTimer); tcDotsTimer = null; }
  else if (!busy && (job.done || []).length) refresh();
}

async function tcAct(action, only){
  // One at a time, and the server enforces it with a 409, so the buttons go
  // dead rather than letting a click earn an error message. Installs are
  // minutes long and share one sdkmanager lock; a queue that outlived them
  // would have to survive a page reload to mean anything, and this does not.
  // Abort is the one thing that may be asked of a running job; everything
  // else has to wait for it.
  if (action !== "abort" && toolchains?.job?.running)
    return notify("a toolchain operation is already running", true);
  if (action === "abort"){
    if (!confirm("Stop after the toolchain it is on? What has already installed stays."))
      return;
    // On a node the install is a job, and stopping it is the queue's Cancel.
    if (tcNode !== "local" && toolchains?.job?.id)
      await postJSON("/api/v1/jobs", {action: "cancel", id: toolchains.job.id});
    else
      await postJSON("/api/toolchains", {action});
    return loadToolchains();
  }

  // "Check for updates" asks about every row, ticked or not: the question is
  // whether anything is out of date and what the rest would install, not
  // whether one ticked thing is. Sending the selection made it answer for
  // that one toolchain and leave the others showing yesterday's answer.
  const names = only || (action === "check" || action === "sysdeps" ? [] : [...tcTicked]);
  if (!names.length && action !== "check" && action !== "sysdeps")
    return notify("tick something first", true);
  // The driver is the one row whose install ends at a restart: said once,
  // before anything is queued.
  const drv = names.includes(TC_DRIVER) && action === "install";
  if (drv && !confirm(`Install NVIDIA's driver on ${toolchains?.name || "this node"}? It takes the card only when the machine restarts, which ends every session on it.`))
    return;
  // ...and the toolkit is the one that adds a package source of somebody
  // else's to the machine.
  if (names.includes(TC_TOOLKIT) && action === "install"
      && !confirm(`Install the NVIDIA container toolkit on ${toolchains?.name || "this node"}? It adds NVIDIA's own package source to the machine. Running containers keep running.`))
    return;
  // The ticks stay: a toolchain being installed reads as chosen, and the boxes
  // are ghosted anyway. What happens to them afterwards is decided by how it
  // went: installed rows carry their own tick, failed ones let go of it.
  try{
    const r = await postJSON("/api/toolchains", {action, names, node: tcNode,
                                                 ...(drv && tcDriverPick ? {driver: tcDriverPick} : {})});
    const j = await r.json().catch(() => ({}));
    // A toolchain that needs another used to be installed without it and fail
    // inside it: android-tools with no jdk, from sdkmanager, naming
    // neither. The catalog says so now, and so does this, rather than an
    // extra name appearing in the queue unexplained.
    if (j?.added?.length)
      notify(`also installing ${j.added.join(", ")}: needed by what you picked`);
    if (!r.ok) return notify(j.error || `could not start (HTTP ${r.status})`, true);
    // The job's own toast where there is one (R218 step 6): it follows the
    // job to its end, which is kept on the record.
    const on = tcNode !== "local" ? " on " + ((nodesList || []).find(n => n.id === tcNode)?.name || "the node") : "";
    notifyJob(j.job, action === "check" ? "checking for updates" + on
      : action === "sysdeps" ? "installing the system packages" + on
      : `${action === "remove" ? "removing" : "installing"} ${names.join(", ")}${on}`);
    loadToolchains();
  }catch(e){ notify("could not start: " + e, true); }
}
