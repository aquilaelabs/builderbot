// The Tools tab: what is installed on a node, and installing or removing it
// there. Its own classic script beside index.html, per the new-surface rule
// (docs/nodes.md §13): same page, same global scope, one file per surface
// (roadmap R55 step 4).
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. The catalogue is config/toolchains.json, read
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

// The sizes are measured by a worker on the server, so the first draw after
// an install (or after a restart) carries the catalog's estimates and the
// real numbers land a moment later. One follow-up ask while that is true,
// not a poll: the flag clears when the measurement finishes, and nothing else
// on this tab changes on its own.
let tcSizeTimer = null;
async function loadToolchains(){
  const asked = ++tcLoadSeq;
  if (nodesList === null) await loadNodes();
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
  if (toolchains && toolchains.sizing) tcSizeTimer = setTimeout(loadToolchains, 1500);
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
// the Playwright browsers its boot hook put on its store for bb shot, and no
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

// What the one job is doing, said next to Install selected rather than
// written into it. A toolchain id is longer than any button should be, and
// using it as a label turned Install into a green banner across the tab.
const tcWorking = job => `<span class="tcworking">${
  {install: "Installing", remove: "Removing", update: "Updating",
   check: "Checking"}[job.action] || "Working on"} ${
  esc((job.current || "").replace(/^android:/, ""))}<span class="dots"></span></span>`;

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

// A toolchain this one needs that is not on this node: the store is shared,
// so a recipe can be here while what it runs on is not. Said on the row,
// with that row's own install one press away.
function tcNeedsLine(p){
  const gone = p.needs_missing || [];
  if (!gone.length) return "";
  return `<span class="sub warn tcneed">Needs ${esc(gone.join(", "))}, which ${gone.length === 1 ? "is" : "are"} not installed here.${
    mayToolchains() ? gone.map(n => ` <button type="button" class="link" data-tcneed="${esc(n)}">Install ${esc(n)}</button>`).join("") : ""}</span>`;
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
  const noUpgrade = !mine && p.installed && !p.updatable;
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
  const upd = p.state === "update"
    ? `<span class="sub upd">update available: tick it and press Install selected</span>`
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
  return `<label class="tc${upToDate ? " done" : ""}">
    <input type="checkbox" value="${esc(p.name)}"${
      busy || p.wrong_platform || noUpgrade ? " disabled" : ""}${
      p.wrong_platform ? ` title="this recipe is packaged for ${esc(p.wrong_platform)}: installing it here would fetch binaries that cannot run"`
      : noUpgrade ? ` checked disabled title="installed; no update in place: remove it first for a newer version"`
      : upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(p.name) ? " checked" : ""}>
    <span class="grow">
      <span class="nm">${esc(p.label)}${p.size
        ? ` <span class="pill" title="${esc(p.size_from)}">${esc(p.size)}</span>` : ""
      }${ver}${next}</span>
      <span class="sub">${esc(p.about)}${
        p.tool ? ` Adds <code>bb tool ${esc(p.tool)}</code> to a session.` : ""}${
        p.needs?.length ? ` Needs ${esc(p.needs.join(", "))}, installed with it.` : ""}${
        p.needed_by?.length ? ` Needed by ${esc(p.needed_by.join(", "))}.` : ""}</span>
      ${tcSystemLine(p, managed)}
      ${tcNeedsLine(p)}
      ${mine ? prog : `<span class="sub where${p.installed ? " on" : ""}">${
        // The path is the store's, and the head of the tab already says where
        // that is, so naming it per row was a repetition, and on a node,
        // where the census reports no per-toolchain path, it read "installed
        // at " with nothing after it.
        p.wrong_platform ? `packaged for ${esc(p.wrong_platform)}, and this node is not`
        : p.installed ? (p.path ? "installed at " + esc(p.path) : "installed")
                      : "not installed"}</span>`}
      ${upd}${err}${
        // Sessions that started before this landed still have the old PATH
        // (toolchains.py counts them); one line, and only while there are any.
        p.reopen && !mine ? `<span class="sub warn tcreopen">${p.reopen === 1 ? "1 session" : `${p.reopen} sessions`}
          open here started before this was installed: reopen ${p.reopen === 1 ? "it" : "them"} to use it</span>` : ""}
    </span>
    ${p.installed && !mine ? `<button class="eye rm" data-rm="${esc(p.name)}" aria-label="uninstall ${esc(p.label)}"${
      busy ? ` disabled title="another toolchain operation is running"`
           : ` title="uninstall ${esc(p.label)}"`}>${BIN}</button>` : ""}
  </label>`;
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
  if (!d){ surf.list.innerHTML = `<div class="loading">loading…</div>`; return; }
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
    if (pre) pre.onclick = () => { nodesList = null; toolchains = null; tcRev++; drawPanes(); loadToolchains(); };
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
  if (nodesList === null) loadNodes();
  const onNode = tcNode !== "local";
  // An install is a job on the node, so it waits for the same thing every
  // other agent job waits for: an agent this controller knows how to talk to.
  // The server refuses it either way (nodes.agent_stale); this is the reason,
  // said before the press rather than after it.
  const pstale = onNode && nodeStale(pnodes.find(n => n.id === tcNode) || {});
  surf.setBar(`${pnodes.length ? `<label class="pick">Toolchains on <select id="tcNodeSel" aria-label="node">
        ${pnodes.map(n => `<option value="${esc(n.id)}"${n.id === tcNode ? " selected" : ""}>${
          esc(n.name)}${n.live === false ? " (quiet)" : ""}</option>`).join("")}
      </select></label>` : ""}
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
    ${(() => {
      // Held recipes whose system libraries this machine lacks (roadmap
      // R51): the store is shared, so a toolchain installed from one node is
      // on every node, while the libraries it needs are each machine's own.
      // One press installs the libraries and leaves the recipes alone.
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
    <div class="tcs">${(d.items || []).filter(i => !i.wrong_platform)
      .map(i => tcRow(i, busy || pstale, job, !!d.administers && !d.locked)).join("")}</div>
    ${(() => {
      // Behind a fold rather than in the list. A recipe this node's platform
      // cannot have is a row that can never be pressed, and on a Mac that is
      // eleven of the sixteen: a tab of dead controls. Not hidden either:
      // somebody looking for xcodes should find out that it exists and what
      // it needs, which is a click rather than a search.
      const no = (d.items || []).filter(i => i.wrong_platform);
      if (!no.length) return "";
      return `<details class="sect tcno"${sectAttr("toolchains:no:" + tcNode)}><summary><span class="t">Not for this node</span>
          <span class="sst">${no.length}</span></summary>
        <div class="tcs">${no.map(i => tcRow(i, true, job)).join("")}</div></details>`;
    })()}
    <div class="hint tcterms">Installing an Android package accepts
      <a href="https://developer.android.com/studio/terms" target="_blank" rel="noreferrer">Google's
      Android SDK terms</a>.</div>
    <div class="actbar macros">
      ${d.checked ? `<span class="state">versions checked ${ago(d.checked)}</span>` : ""}
      ${!mayToolchains() ? "" : `<button class="primary" data-tc="install"${busy || pstale ? " disabled" : ""}
        ${pstale ? `title="${esc(staleWhy(pnodes.find(n => n.id === tcNode)))}"` : ""}
        >Install selected</button>`}
      ${busy && mayToolchains() ? `<button data-tc="abort"${job.aborting ? " disabled" : ""}>${
        job.aborting ? "Stopping…" : "Abort"}</button>` : ""}
      ${busy ? tcWorking(job) : ""}
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
  if (psel) psel.onchange = () => { tcNode = psel.value; toolchains = null; tcTicked.clear();
                                    try{ localStorage.setItem("bb.tcnode", tcNode); }catch(e){ /* private */ }
                                    tcRev++; drawPanes(); loadToolchains(); };
  const pre = el.querySelector("#tcRefresh");
  if (pre) pre.onclick = () => loadToolchains();
  const sd = el.querySelector("#tcSysdeps");
  if (sd) sd.onclick = () => tcAct("sysdeps");
  el.querySelectorAll("[data-tcsys]").forEach(b => b.onclick = () => tcAct("sysdeps", [b.dataset.tcsys]));
  el.querySelectorAll("[data-tcneed]").forEach(b => b.onclick = () => tcAct("install", [b.dataset.tcneed]));
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
  clearTimeout(tcPoll);
  if (busy)
    tcPoll = setTimeout(loadToolchains, 500);
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
  // The ticks stay: a toolchain being installed reads as chosen, and the boxes
  // are ghosted anyway. What happens to them afterwards is decided by how it
  // went: installed rows carry their own tick, failed ones let go of it.
  try{
    const r = await postJSON("/api/toolchains", {action, names, node: tcNode});
    const j = await r.json().catch(() => ({}));
    // A toolchain that needs another used to be installed without it and fail
    // inside it: android-tools with no jdk, from sdkmanager, naming
    // neither. The catalog says so now, and so does this, rather than an
    // extra name appearing in the queue unexplained.
    if (j?.added?.length)
      notify(`also installing ${j.added.join(", ")}: needed by what you picked`);
    if (!r.ok) return notify(j.error || `could not start (HTTP ${r.status})`, true);
    notify(action === "check"
      ? (tcNode === "local" ? "checking for updates"
         : "checking for updates on " + ((nodesList || []).find(n => n.id === tcNode)?.name
                                         || "the node"))
      : action === "sysdeps"
      ? "installing the system packages"
      : `${action === "remove" ? "removing" : "installing"} ${names.join(", ")}${
          tcNode !== "local" ? " on " + ((nodesList || []).find(n => n.id === tcNode)?.name || "the node") : ""
        }; this can take minutes`);
    loadToolchains();
  }catch(e){ notify("could not start: " + e, true); }
}
