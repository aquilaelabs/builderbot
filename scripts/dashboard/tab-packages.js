// The Tools tab: what is installed on a node, and installing or removing it
// there. Its own classic script beside index.html, per the new-surface rule
// (docs/nodes.md §13): same page, same global scope, one file per surface
// (roadmap R55 step 4).
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. The catalogue is config/packages.json, read
// through /api/packages; an install is a JOB on the node, so the list keeps
// reporting progress rather than freezing on a request that cannot return.
//
// Moved out of index.html unchanged. Loaded BEFORE the page's own script, so
// everything here is a declaration and nothing runs at load.

// ---- additional packages -----------------------------------------------
// The Tools card's other half, opened as a document tab beside the findings
// report rather than a dialog: installing an SDK is not a detour to dismiss,
// it is a thing to leave open for the several minutes it runs, and a tab can
// be pinned to a pane, minimized, or left on the strip while you work.
//
// Installs are queued by the server and polled from here, so the list keeps
// reporting progress instead of freezing on a request that cannot return.
let packages = null, pkgRev = 0, pkgPoll = null;
const pkgTicked = new Set();     // survives a redraw; a poll must not untick

function openPackages(){
  openTab({kind:"packages", arg:"__packages", label:"packages"});
}

// The sizes are measured by a worker on the server, so the first draw after
// an install (or after a restart) carries the catalog's estimates and the
// real numbers land a moment later. One follow-up ask while that is true,
// not a poll: the flag clears when the measurement finishes, and nothing else
// on this tab changes on its own.
let pkgSizeTimer = null;
async function loadPackages(){
  const asked = ++pkgLoadSeq;
  if (nodesList === null) await loadNodes();
  if (asked !== pkgLoadSeq) return;           // the node changed under this load
  if (!pkgPick()){
    packages = {nonode: true};
    clearTimeout(pkgSizeTimer); pkgSizeTimer = null;
    pkgRev++; drawPanes();
    return;
  }
  try{
    const r = await fetch("/api/packages" + (pkgNode !== "local" ? `?node=${encodeURIComponent(pkgNode)}` : ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (asked !== pkgLoadSeq) return;
    packages = got;
  }catch(e){ if (asked !== pkgLoadSeq) return; packages = {error: String(e)}; }
  clearTimeout(pkgSizeTimer); pkgSizeTimer = null;
  if (packages && packages.sizing) pkgSizeTimer = setTimeout(loadPackages, 1500);
  pkgRev++;
  drawPanes();
}

// The animated ellipsis. One counter for the tab, ticked on its own timer and
// written straight into the spans, so the once-a-second redraw neither
// restarts it nor resets it: a rebuild simply renders the count it is on.
let pkgDots = 0, pkgDotsTimer = null;
// Every animated ellipsis on the page, not just the packages tab's: the
// Projects card grew one when clones moved to a background job, and two
// tickers running at different phases would read as a fault.
// Which flavor the picker is showing. Page state, not the server's: it is a
// question being asked, not a fact about the box.
let pkgFlavor = "";
// Which node the Tools tab is showing (docs/nodes.md §6): an agent node's
// packages store, where an install is a job. Empty until pkgPick() chooses
// one, and empty when there is none to choose: packages are installed on
// NODES (roadmap #26), and this container is never offered: what it keeps is
// the Playwright browsers its boot hook put on its store for bb shot, and no
// button reaches its installer. "local" is still what that installer is
// called (`bb packages install` from a shell and the suite address it) but
// nothing on this page sets it.
let pkgNode = "";
let pkgLoadSeq = 0;         // a load that lands after the node changed is dropped

// The node the tab opens on: the one it showed last (remembered in this
// browser), else the first live agent node, else nothing. Re-asked on every
// load, so a node that was retired under the tab is not shown as if it were
// still there.
function pkgPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  if (pkgNode === "local") return pkgNode;
  let want = pkgNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.pkgnode") || ""; }catch(e){ want = ""; }
  }
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  pkgNode = want;
  return pkgNode;
}

// What the one job is doing, said next to the control that started it: Add
// for a system image, Install selected for anything else, rather than
// written into that button. A package id is longer than any button should be,
// and using it as a label turned Install into a green banner across the tab.
const pkgWorkingIsImage = job =>
  (job?.current || "").includes("system-images;");
const pkgWorking = job => `<span class="pkgworking">${
  {install: "Installing", remove: "Removing", update: "Updating",
   check: "Checking"}[job.action] || "Working on"} ${
  esc((job.current || "").replace(/^android:/, ""))}<span class="dots"></span></span>`;

function pkgTickDots(){
  const spans = document.querySelectorAll(".dots");
  if (!spans.length){ clearInterval(pkgDotsTimer); pkgDotsTimer = null; return; }
  pkgDots = (pkgDots + 1) % 4;
  spans.forEach(e => e.textContent = ".".repeat(pkgDots));
}

function pkgRow(p, busy, job){
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
  // An installed package whose recipe cannot update in place. The check can
  // still say a newer version exists (it asks upstream, not the recipe) and
  // before this the row let you tick it and then died on `bb packages update`'s
  // usage line, naming five packages you had not asked about (bug #43).
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
  // progress frames it took to say it. Cleared when this package is tried
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
    ".".repeat(pkgDots)}</span></span>`;
  return `<label class="pkg${upToDate ? " done" : ""}">
    <input type="checkbox" value="${esc(p.name)}"${
      busy || p.wrong_platform || noUpgrade ? " disabled" : ""}${
      p.wrong_platform ? ` title="this recipe is packaged for ${esc(p.wrong_platform)}: installing it here would fetch binaries that cannot run"`
      : noUpgrade ? ` checked disabled title="installed. This one is fetched and unpacked whole, so there is no update in place: remove it first to get a newer version"`
      : upToDate ? ` checked disabled title="installed and up to date; nothing to do until a check finds an update"`
               : pkgTicked.has(p.name) ? " checked" : ""}>
    <span class="grow">
      <span class="nm">${esc(p.label)}${p.size
        ? ` <span class="pill" title="${esc(p.size_from)}">${esc(p.size)}</span>` : ""
      }${ver}${next}</span>
      <span class="sub">${esc(p.about)}${
        p.needs?.length ? ` Needs ${esc(p.needs.join(", "))}, installed with it.` : ""}${
        p.needed_by?.length ? ` Needed by ${esc(p.needed_by.join(", "))}.` : ""}</span>
      ${mine ? prog : `<span class="sub where${p.installed ? " on" : ""}">${
        // The path is the store's, and the head of the tab already says where
        // that is, so naming it per row was a repetition, and on a node,
        // where the census reports no per-package path, it read "installed
        // at " with nothing after it.
        p.wrong_platform ? `packaged for ${esc(p.wrong_platform)}, and this node is not`
        : p.installed ? (p.path ? "installed at " + esc(p.path) : "installed")
                      : "not installed"}</span>`}
      ${upd}${err}
    </span>
    ${p.installed && !mine ? `<button class="eye rm" data-rm="${esc(p.name)}" aria-label="uninstall ${esc(p.label)}"${
      busy ? ` disabled title="another package operation is running"`
           : ` title="uninstall ${esc(p.label)}"`}>${BIN}</button>` : ""}
  </label>`;
}

// One installed android image. No checkbox: there is nothing to select it
// for; it is here, and the only thing to decide is whether it stays.
// Adding an image is a pick, not a tick. There are forty-odd of them: every
// API level Google still ships, times four flavors, and a checkbox list that
// long would bury the ten that are actually installed. The sizes come from
// sdkmanager's own index, which is the only place they exist before the
// download.
function imgAdder(d, busy){
  const rows = d.addable || [], flavors = d.flavors || [];
  // Google's index is read off the request, so the first draw of the tab does
  // not wait for it. Saying so beats the picker popping into existence a
  // second later with no explanation.
  if (!rows.length) return d.images_loading
    ? `<div class="imgadd"><span class="sub">reading the list of available
         images<span class="dots"></span></span></div>`
    : "";
  const chosen = pkgFlavor && flavors.some(f => f.kind === pkgFlavor)
    ? pkgFlavor : (flavors[0]?.kind || "");
  const mine = rows.filter(r => r.kind === chosen);
  const about = flavors.find(f => f.kind === chosen)?.about || "";
  return `<div class="imgadd">
    <select id="imgFlavor"${busy ? " disabled" : ""} aria-label="image flavor">${
      flavors.map(f => `<option value="${esc(f.kind)}"${f.kind === chosen ? " selected" : ""}
        >${esc(f.label)}</option>`).join("")}</select>
    <select id="imgApi"${busy ? " disabled" : ""} aria-label="API level">${
      mine.map(r => `<option value="${esc(r.id)}">API ${esc(r.api)} · ${esc(r.size)}</option>`)
          .join("") || `<option value="">none left to add</option>`}</select>
    <button id="imgAdd"${busy || !mine.length ? " disabled" : ""}>Add</button>
    ${busy && pkgWorkingIsImage(d.job) ? pkgWorking(d.job) : ""}
    ${about ? `<div class="sub imgabout">${esc(about)}</div>` : ""}
  </div>`;
}

function imgRow(im, busy){
  // Which AVDs are built on it, because that is the question anybody asking
  // "can this go?" is really asking. An AVD names one image exactly, and two
  // flavors at the same API level are not interchangeable: one asking for
  // google_apis will not boot on google_apis_playstore, alike as they look.
  const avds = (im.avds || []).length
    ? `<span class="sub">${im.avds.length === 1 ? "AVD" : "AVDs"}: ${
        esc(im.avds.join(", "))}</span>`
    : `<span class="sub dim">no AVD uses it</span>`;
  return `<label class="pkg img">
    <span class="grow">
      <span class="nm">${esc(im.api)} <span class="pill">${esc(im.kind)}</span>
        ${im.size ? `<span class="pill"${im.size_from
          ? ` title="${esc(im.size_from)}"` : ""}>${esc(im.size)}</span>` : ""}</span>
      <span class="sub where on">installed at ${esc(im.id)}</span>
      ${avds}
    </span>
    <button class="eye rm" data-rmimg="${esc(im.id)}" aria-label="remove ${esc(im.id)}"${
      busy ? ` disabled title="another package operation is running"`
           : ` title="remove this system image"`}>${BIN}</button>
  </label>`;
}

function renderPackagesInto(i){
  const el = $("doc" + i);
  if (!el) return;
  // The pane is redrawn whole on every change, and a redraw put the
  // reader at the foot (the images block) the moment Install was pressed,
  // with the row that was installing off screen. Where they were, kept.
  const keepScroll = el.scrollTop;
  queueMicrotask(() => { if (el.isConnected) el.scrollTop = keepScroll; });
  // Fills its pane like the notebook and the other document tabs, rather than
  // sitting on the darker ground with an inset, which is what made this one
  // look like a different kind of screen.
  el.classList.add("flush");
  const d = packages;
  // The shared scaffold, like every other document kind: the bar slot holds
  // the picker and the Refresh that re-reads it, so the action sits where a
  // tab's action sits rather than in a band this tab invented. `pkg` is the
  // class name the sheet and the suite already use for it.
  const surf = docSurface(i, "pkg");
  if (!surf) return;
  if (!d){ surf.list.innerHTML = `<div class="loading">loading…</div>`; return; }
  if (d.error){ surf.list.innerHTML = `<div class="empty">${
    esc("could not read the package list: " + d.error)}</div>`; return; }
  // No node to install on. Not this container: it builds nothing and keeps
  // nothing but the browsers its boot put there, so there is no list to show
  // and no button that would be honest to offer.
  if (d.nonode){
    surf.setBar(`<span class="sp"></span>
      <button type="button" id="pkgRefresh" title="look again for a node">Refresh</button>`);
    surf.list.innerHTML = `<div class="empty pkgnone">Packages are installed on a node, and
        none is enrolled. The Nodes tab's <b>Enroll node</b> makes one; its packages store is
        what shows here. Nothing installs on this container.</div>`;
    const pre = el.querySelector("#pkgRefresh");
    if (pre) pre.onclick = () => { nodesList = null; packages = null; pkgRev++; drawPanes(); loadPackages(); };
    return;
  }

  const job = d.job || {}, busy = !!job.running;
  // A finished package loses its tick: whether it worked or not. One that
  // worked wears the permanent tick of a package that is installed; one that
  // failed should not still be selected, because the next click might be
  // Remove and it was never there. Until then the tick stays put: through a
  // job, a ticked box says which packages this job is for.
  //
  // Except a check, which spends nothing: it asks about every row whether or
  // not anything is ticked, so treating its results as consumed selection
  // cleared a tick the operator had just placed: press check, and the thing
  // you were about to install quietly unticked itself.
  if (!busy && job.action !== "check")
    for (const n of [...(job.done || []), ...(job.failed || [])]) pkgTicked.delete(n);
  // The picker: an agent node. Never this container (roadmap #26). Drawn
  // whenever there is a node, one included, so the tab always says whose
  // store it is showing.
  const pnodes = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  if (nodesList === null) loadNodes();
  const onNode = pkgNode !== "local";
  // An install is a job on the node, so it waits for the same thing every
  // other agent job waits for: an agent this controller knows how to talk to.
  // The server refuses it either way (nodes.agent_stale); this is the reason,
  // said before the press rather than after it.
  const pstale = onNode && nodeStale(pnodes.find(n => n.id === pkgNode) || {});
  surf.setBar(`${pnodes.length ? `<label class="pick">Packages on <select id="pkgNodeSel" aria-label="node">
        ${pnodes.map(n => `<option value="${esc(n.id)}"${n.id === pkgNode ? " selected" : ""}>${
          esc(n.name)}${n.live === false ? " (quiet)" : ""}</option>`).join("")}
      </select></label>` : ""}
    <span class="sp"></span>
    <button type="button" id="pkgRefresh"
      title="read this store again: what is installed, and how big it is">Refresh</button>`);
  surf.list.innerHTML = `
    <div class="pkghead">${onNode
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
          : `${esc(d.name || "the node")} reports no packages store yet.`)
      : d.root
      ? (d.shared
          ? `Installed into <code>${esc(d.root)}</code>: a mapped share, so an image update never re-downloads them.`
          : `Installed into <code>${esc(d.root)}</code>: the home volume. Map an package store to keep them out of it.`)
      : "The package store root could not be determined; this image may predate <code>bb packages</code>."}</div>
    ${pstale ? `<div class="pkghead warn pkgstale">${esc(staleWhy(
      pnodes.find(n => n.id === pkgNode)))}. Nothing installs here until it is.</div>` : ""}
    ${(() => {
      // Held recipes whose system libraries this machine lacks (roadmap
      // R51): the store is shared, so a package installed from one node is
      // on every node, while the libraries it needs are each machine's own.
      // One press installs the libraries and leaves the recipes alone.
      const unmet = Object.entries((onNode && d.sysdeps?.unmet) || {});
      if (!unmet.length) return "";
      const what = unmet.map(([r, ps]) => `${esc(r)}: ${esc(ps.join(" "))}`).join("; ");
      return `<div class="pkghead warn pkgsys">System packages ${esc(d.name || "this node")} lacks
          for what its store holds (${esc(d.sysdeps.family || "")}): ${what}.
          ${d.sandbox
            ? `<button type="button" id="pkgSysdeps"${busy || pstale ? " disabled" : ""}
                 title="install these on ${esc(d.name || "the node")} without reinstalling the packages">Install system packages</button>`
            : `This node's owner installs them: the agent does not administer the machine.`}</div>`;
    })()}
    <div class="pkgs">${(d.items || []).filter(i => !i.wrong_platform)
      .map(i => pkgRow(i, busy || pstale, job)).join("")}</div>
    ${(() => {
      // Behind a fold rather than in the list. A recipe this node's platform
      // cannot have is a row that can never be pressed, and on a Mac that is
      // eleven of the sixteen: a tab of dead controls. Not hidden either:
      // somebody looking for xcodes should find out that it exists and what
      // it needs, which is a click rather than a search.
      const no = (d.items || []).filter(i => i.wrong_platform);
      if (!no.length) return "";
      return `<details class="sect pkgno"><summary><span class="t">Not for this node</span>
          <span class="sst">${no.length}</span></summary>
        <div class="pkgs">${no.map(i => pkgRow(i, true, job)).join("")}</div></details>`;
    })()}
    <div class="pkghead imghead">Android system images. Not packages: one exists at
      every API level at once, so the question is which level and which flavor
      rather than whether. ${onNode
      ? `These are the ones in ${esc(d.name || "the node")}'s packages store: what its
         emulator can boot. The list of what exists is read here, from Google's index; an
         image is the same bytes on every host, so the node needs no network of its own to
         be offered one.`
      : `This container boots no emulator (the image carries no SDK): an image installed
         here sits in the store for a node that shares it.`}
      Nothing is removed except by asking.</div>
    ${onNode && d.images_need ? `<div class="pkghead sub">Images are installed by
      sdkmanager, which is part of <code>${esc(d.images_need)}</code>, not on this node
      yet, so it will be installed first.</div>` : ""}
    ${imgAdder(d, busy || pstale)}
    ${(d.images || []).length
      ? `<div class="pkgs">${d.images.map(im => imgRow(im, busy || pstale)).join("")}</div>`
      : `<div class="pkghead">${onNode && d.images_known === false
          ? `${esc(d.name || "This node")}'s agent is too old to report its system images:
             update it from the Nodes tab. Its emulator may well have one.`
          : `Nothing installed: ${onNode
             ? esc(d.name || "the node") + "'s emulator has no image to boot."
             : "the emulator has no image to boot."}`}</div>`}
    <div class="hint pkgterms">Installing an android package, image or tool accepts
      <a href="https://developer.android.com/studio/terms" target="_blank" rel="noreferrer">Google's
      Android SDK terms</a> for this store: pressing Install is that acceptance, made by you.</div>
    <div class="actbar macros">
      ${d.checked ? `<span class="state">versions checked ${ago(d.checked)}</span>` : ""}
      ${!mayPackages() ? "" : `<button class="primary" data-pkg="install"${busy || pstale ? " disabled" : ""}
        ${pstale ? `title="${esc(staleWhy(pnodes.find(n => n.id === pkgNode)))}"` : ""}
        >Install selected</button>`}
      ${busy && mayPackages() ? `<button data-pkg="abort"${job.aborting ? " disabled" : ""}>${
        job.aborting ? "Stopping…" : "Abort"}</button>` : ""}
      ${busy && !pkgWorkingIsImage(job) ? pkgWorking(job) : ""}
      <button data-pkg="check"${busy || onNode || !mayPackages() ? " disabled" : ""}
        ${onNode ? `title="a node says what it has installed; asking upstream what is newer
          is a round trip per toolchain and is not something a node does yet"` : ""}>${
        busy && job.action === "check"
          ? `Checking for updates<span class="dots">${".".repeat(pkgDots)}</span>`
        : (d.items || []).some(i => i.state) ? "Re-check for updates" : "Check for updates"}</button>
    </div>`;

  el.querySelectorAll(".pkg input").forEach(b => b.onchange = () => {
    b.checked ? pkgTicked.add(b.value) : pkgTicked.delete(b.value);
  });
  el.querySelectorAll("[data-pkg]").forEach(b => b.onclick = () => pkgAct(b.dataset.pkg));
  const psel = el.querySelector("#pkgNodeSel");
  if (psel) psel.onchange = () => { pkgNode = psel.value; packages = null; pkgTicked.clear();
                                    try{ localStorage.setItem("bb.pkgnode", pkgNode); }catch(e){ /* private */ }
                                    pkgRev++; drawPanes(); loadPackages(); };
  const pre = el.querySelector("#pkgRefresh");
  if (pre) pre.onclick = () => loadPackages();
  const sd = el.querySelector("#pkgSysdeps");
  if (sd) sd.onclick = () => pkgAct("sysdeps");
  const fl = el.querySelector("#imgFlavor"), api = el.querySelector("#imgApi");
  if (fl) fl.onchange = () => { pkgFlavor = fl.value; pkgRev++; drawPanes(); };
  if (el.querySelector("#imgAdd")) el.querySelector("#imgAdd").onclick = () => {
    if (!api?.value) return;
    // Straight in, no confirmation: it is a download into free space, and the
    // size is on the option that was just picked.
    pkgAct("install", ["android:" + api.value]);
  };
  el.querySelectorAll("[data-rmimg]").forEach(b => b.onclick = e => {
    e.preventDefault(); e.stopPropagation();
    const id = b.dataset.rmimg;
    const users = (packages?.images || []).find(im => im.id === id)?.avds || [];
    if (confirm(`Remove ${id}?\n\n${users.length
      ? `${users.join(", ")} ${users.length === 1 ? "is" : "are"} built on it and will not boot until it is installed again.`
      : "No AVD is built on it."}`))
      pkgAct("remove", ["android:" + id]);
  });
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = e => {
    // Inside a <label>, so the click would otherwise toggle the checkbox on
    // its way past.
    e.preventDefault(); e.stopPropagation();
    const name = b.dataset.rm;
    if (confirm(`Uninstall ${name}? The files are deleted; installing it again re-downloads them.`))
      pkgAct("remove", [name]);
  });

  // No idle clock. Everything this tab draws that can move while nothing is
  // happening: the daily version check, a package installed from a
  // terminal, the image index landing: is in the `packages` token now, and
  // the revisions poll asks for that every second and a half along with the
  // rest of the page. The eight-second timer that used to cover it was one
  // tab noticing things sooner than the tab beside it for no reason anybody
  // chose.
  //
  // What survives is the SAMPLE, and it is a different thing from noticing a
  // change: while a job is actually running this tab is watching an operation
  // in flight, and a job on a small package starts and finishes inside one
  // revision poll: the tab would go from idle to done having never said
  // "installing". Half a second is how often that is worth looking at, and it
  // stops the moment the job does.
  clearTimeout(pkgPoll);
  if (busy || d.images_loading)
    pkgPoll = setTimeout(loadPackages, busy ? 500 : 1000);
  // The ellipsis animates for the index read too, not only for a job.
  const ticking = busy || d.images_loading;
  if (ticking && !pkgDotsTimer) pkgDotsTimer = setInterval(pkgTickDots, 400);
  if (!ticking && pkgDotsTimer){ clearInterval(pkgDotsTimer); pkgDotsTimer = null; }
  else if (!busy && (job.done || []).length) refresh();
}

async function pkgAct(action, only){
  // One at a time, and the server enforces it with a 409, so the buttons go
  // dead rather than letting a click earn an error message. Installs are
  // minutes long and share one sdkmanager lock; a queue that outlived them
  // would have to survive a page reload to mean anything, and this does not.
  // Abort is the one thing that may be asked of a running job; everything
  // else has to wait for it.
  if (action !== "abort" && packages?.job?.running)
    return notify("a package operation is already running", true);
  if (action === "abort"){
    if (!confirm("Stop after the package it is on? What has already installed stays."))
      return;
    // On a node the install is a job, and stopping it is the queue's Cancel.
    if (pkgNode !== "local" && packages?.job?.id)
      await postJSON("/api/v1/jobs", {action: "cancel", id: packages.job.id});
    else
      await postJSON("/api/packages", {action});
    return loadPackages();
  }
  if (pkgNode !== "local" && !["install", "remove", "sysdeps"].includes(action))
    return notify("a node reports what it has installed, but checking upstream for newer "
                  + "versions is not something it does yet; that is a network round trip "
                  + "per toolchain and would have to be a job", true);
  // "Check for updates" asks about every row, ticked or not: the question is
  // whether anything is out of date and what the rest would install, not
  // whether one ticked thing is. Sending the selection made it answer for
  // that one package and leave the others showing yesterday's answer.
  const names = only || (action === "check" || action === "sysdeps" ? [] : [...pkgTicked]);
  if (!names.length && action !== "check" && action !== "sysdeps")
    return notify("tick something first", true);
  // The ticks stay: a package being installed reads as chosen, and the boxes
  // are ghosted anyway. What happens to them afterwards is decided by how it
  // went: installed rows carry their own tick, failed ones let go of it.
  try{
    const r = await postJSON("/api/packages", {action, names, node: pkgNode});
    const j = await r.json().catch(() => ({}));
    // A package that needs another used to be installed without it and fail
    // inside it: android-tools with no jdk, from sdkmanager, naming
    // neither. The catalog says so now, and so does this, rather than an
    // extra name appearing in the queue unexplained.
    if (j?.added?.length)
      notify(`also installing ${j.added.join(", ")}: needed by what you picked`);
    if (!r.ok) return notify(j.error || `could not start (HTTP ${r.status})`, true);
    notify(action === "check"
      ? "checking versions: each one asks its own upstream"
      : action === "sysdeps"
      ? "installing the system packages the held recipes need; the packages themselves are left alone"
      : `${action === "remove" ? "removing" : "installing"} ${names.join(", ")}${
          pkgNode !== "local" ? " on " + ((nodesList || []).find(n => n.id === pkgNode)?.name || "the node") : ""
        }; this can take minutes`);
    loadPackages();
  }catch(e){ notify("could not start: " + e, true); }
}
