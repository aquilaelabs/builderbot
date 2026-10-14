// The Emulator tab: the Android system images on a node's toolchain store,
// and adding or removing one there. Its own classic script beside index.html,
// per the new-surface rule (docs/nodes.md §13).
//
// Not the Toolchains tab. A toolchain is one thing at one version; a system
// image exists at every API level at once, and which one to have is a
// question about what is being tested. The images live on the toolchain store
// all the same, so an image job and a toolchain job take turns on one
// (toolchains.store_busy). Chrome comes from docSurface(); data from
// /api/emulator (emulator.py). Loaded BEFORE the page's own script, so
// everything here is a declaration and nothing runs at load.

"use strict";

let emu = null, emuRev = 0, emuPoll = null, emuLoadSeq = 0;
// Which node the tab shows, remembered in this browser, and which flavor the
// picker is on: a question being asked, not a fact about the node.
let emuNode = "", emuFlavor = "";

function openEmulator(){
  openTab({kind: "emulator", arg: "__emulator", label: "Emulator"});
}

// The node the tab opens on: the one it showed last, else the first agent
// node that has what the tab needs, else the first agent node.
function emuPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  let want = emuNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.emunode") || ""; }catch(e){ want = ""; }
  }
  // The server names the node this tab is FOR: one that can hold an image,
  // and the one that already does when there is one. Which platforms the
  // Android recipes are packaged for is the catalog's answer, not a rule to
  // keep a second copy of here.
  if (!live.some(n => n.id === want)) want = state?.emulator?.node || "";
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  emuNode = want;
  return emuNode;
}

// The node registry moved (a heartbeat, every few seconds): the tab used to
// fetch its whole listing for each one, though what it draws from a node
// is the images the census reports. It reads the list the poll already
// refetched and asks for the listing only when that slice changed (B216).
let emuCensus = null;
async function emuOnNodes(){
  await loadNodes();
  const n = (nodesList || []).find(x => x.id === emuNode) || null;
  const key = JSON.stringify([(n?.reported || {}).images || [], !!n?.live, n?.state || ""]);
  if (key === emuCensus) return;
  emuCensus = key;
  loadEmulator();
}

async function loadEmulator(){
  const asked = ++emuLoadSeq;
  if (nodesList === null) await loadNodes();
  if (asked !== emuLoadSeq) return;
  if (!emuPick()){ emu = {nonode: true}; emuRev++; drawPanes(); return; }
  try{
    const r = await fetch("/api/emulator?node=" + encodeURIComponent(emuNode));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (asked !== emuLoadSeq) return;
    emu = got;
  }catch(e){ if (asked !== emuLoadSeq) return; emu = {error: String(e)}; }
  emuRev++;
  drawPanes();
}

// Adding images is Toolchains' gesture (R121, the operator 4 Oct): tick
// rows, press Install selected. Forty-odd images (every API level Google
// still ships, times four flavors) would bury the few installed, so the
// rows to add are one flavor's at a time, chosen above them, and the
// installed ones stay in a list of their own. The sizes come from
// sdkmanager's own index, the only place they exist before the download.
// A tick survives a change of flavor, and the button counts them all.
const emuTicked = new Set();

function emuFlavorNow(d){
  const flavors = d.flavors || [];
  return emuFlavor && flavors.some(f => f.kind === emuFlavor) ? emuFlavor : (flavors[0]?.kind || "");
}

function emuAddRows(d, why){
  const rows = d.addable || [], flavors = d.flavors || [];
  // Google's index is read off the request, so the first draw does not wait
  // for it; saying so beats the rows appearing a second later unexplained.
  if (!rows.length) return d.loading
    ? `<div class="tchead emadd"><span class="sub">reading the list of available
         images<span class="dots"></span></span></div>`
    : "";
  const chosen = emuFlavorNow(d);
  const mine = rows.filter(r => r.kind === chosen);
  const about = flavors.find(f => f.kind === chosen)?.about || "";
  const job = d.job || {};
  const writing = job.running && job.action === "add" ? new Set(job.images || [job.image]) : new Set();
  // Adding images is an administrator's (the server's gate on /api/emulator):
  // not offered without the grant (R137 step 4), the list above is everybody's.
  if (state?.can?.admin === false) return "";
  return `<div class="imgadd emadd"><label for="imgFlavor">Images to add</label>
      <select id="imgFlavor">${
        flavors.map(f => `<option value="${esc(f.kind)}"${f.kind === chosen ? " selected" : ""}
          >${esc(f.label)}</option>`).join("")}</select>
      ${about ? `<span class="sub imgabout">${esc(about)}</span>` : ""}</div>
    <div class="tcs emaddrows">${mine.map(r => {
      const now = writing.has(r.id);
      return `<label class="tc emnew">
        <input type="checkbox" value="${esc(r.id)}"${why || job.running || !mayToolchains() ? " disabled" : ""}${
          emuTicked.has(r.id) || now ? " checked" : ""}>
        <span class="grow">
          <span class="nm">API ${esc(r.api)}${r.size ? ` <span class="pill">${esc(r.size)}</span>` : ""}</span>
          ${now ? `<span class="sub prog plain">${job.current === r.id ? "adding" : "waiting its turn"}<span class="dots"></span></span>`
                : `<span class="sub where">${esc(r.id)}</span>`}
        </span></label>`;
    }).join("") || `<div class="tchead">every ${esc(flavors.find(f => f.kind === chosen)?.label || "")} image is here already</div>`}</div>`;
}

// One installed image, drawn as an installed toolchain is: its tick set and
// dead, its bin at the right. Which AVDs are built on it, because that is
// the question anybody asking "can this go?" is really asking: an AVD names
// one image exactly, and two flavors at one API level are not interchangeable.
function emuRow(im, why){
  const avds = (im.avds || []).length
    ? `<span class="sub">${im.avds.length === 1 ? "AVD" : "AVDs"}: ${esc(im.avds.join(", "))}</span>`
    : `<span class="sub dim">no AVD uses it</span>`;
  return `<label class="tc done emimg">
    <input type="checkbox" checked disabled title="installed">
    <span class="grow">
      <span class="nm">${esc(im.api)} <span class="pill">${esc(im.kind)}</span>
        ${im.size ? `<span class="pill"${im.size_from
          ? ` title="${esc(im.size_from)}"` : ""}>${esc(im.size)}</span>` : ""}</span>
      <span class="sub where on">${esc(im.id)}</span>
      ${avds}
    </span>
    ${mayToolchains() ? `<button class="eye rm" data-rmimg="${esc(im.id)}" aria-label="remove ${esc(im.id)}"${
      why ? ` disabled title="${esc(why)}"`
           : ` title="remove this system image"`}>${BIN}</button>` : ""}
  </label>`;
}

function renderEmulatorInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  const surf = docSurface(i, "emu");
  if (!surf) return;
  const d = emu;
  if (!d){ surf.list.innerHTML = `<div class="loading">loading…</div>`; return; }
  if (d.error){ surf.list.innerHTML = `<div class="empty">${
    esc("could not read the images: " + d.error)}</div>`; return; }
  if (d.nonode){
    surf.setBar(`<span class="sp"></span><button type="button" id="emuRefresh">Refresh</button>`);
    surf.list.innerHTML = `<div class="empty">The emulator runs on a node, and none is
      enrolled: the Nodes tab's <b>Enroll node</b> makes one.</div>`;
    el.querySelector("#emuRefresh").onclick = e => { busy(e.currentTarget, "Refreshing"); nodesList = null; loadEmulator(); };
    return;
  }
  const pnodes = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  const pnode = pnodes.find(n => n.id === emuNode) || {};
  const stale = nodeStale(pnode);
  const job = d.job || {};
  // Why nothing can be added or removed right now, said on the ghosted control.
  const held = d.wrong_platform ? `${d.name} is ${d.platform}, and the Android tools are packaged for ${d.wrong_platform}`
    : job.running ? "another job is writing to this store"
    : stale ? staleWhy(pnode)
    : d.sdkmanager === false ? `${d.name} needs the Android command-line tools first` : "";
  // The one node switcher (page-docs.js nodePick, R121).
  surf.setBar(`${nodePick("emuNodeSel", pnodes, emuNode)}
    <span class="sp"></span>
    <button type="button" id="emuRefresh" title="read this node's images again">Refresh</button>`);
  const free = typeof d.free_mb === "number"
    ? `, ${d.free_mb >= 10240 ? Math.round(d.free_mb / 1024) + "GB" : d.free_mb + "MB"} free` : "";
  surf.list.innerHTML = `
    <div class="tchead">${d.wrong_platform
      ? `System images are what an emulator boots, and they live on the node that runs it.`
      : d.root
      ? `System images in <code>${esc(d.root)}</code> on ${esc(d.name)}${free}: what its emulator can boot.`
      : `${esc(d.name)} reports no toolchain store yet.`}</div>
    ${stale ? `<div class="tchead warn">${esc(staleWhy(pnode))}. Nothing changes here until it is.</div>` : ""}
    ${d.wrong_platform ? `<div class="tchead warn emneed">${esc(d.name)} is ${esc(d.platform)},
      and the Android command-line tools and the emulator are packaged for ${
      esc(d.wrong_platform)}: no system image can run there.</div>`
      : (d.missing || []).length ? `<div class="tchead warn emneed">${esc(d.name)} has no ${
      esc(d.missing.join(" or "))} yet: <a href="#" id="emuToTc">install ${
      d.missing.length === 1 ? "it" : "them"} from Toolchains</a>.</div>` : ""}
    ${
    // The node's images at a glance (R216): how many, the AVDs built on
    // them, the levels its projects need and have none of, the room left.
    !d.wrong_platform && d.known !== false ? statTiles([
      {label: "images", value: (d.images || []).length},
      {label: "AVDs", value: (d.images || []).reduce((n, im) => n + (im.avds || []).length, 0), sub: "built on them"},
      {label: "levels needed", value: (d.needed || []).length, tone: (d.needed || []).length ? "warn" : "", omit: !(d.needed || []).length},
      {label: "free", value: typeof d.free_mb === "number" ? (d.free_mb >= 10240 ? Math.round(d.free_mb / 1024) + "GB" : d.free_mb + "MB") : "",
       sub: "on the store", omit: typeof d.free_mb !== "number"},
    ]) : ""}
    ${(d.needed || []).map(nd => `<div class="tchead warn emlevel">${esc(nd.projects.join(", "))} compile${
      nd.projects.length === 1 ? "s" : ""} against ${esc(nd.level)} and no image of that level is here${
      nd.pick ? `: ${esc(nd.pick)} below is the plain one` : ""}.</div>`).join("")}
    ${job.state === "failed" && job.error ? `<div class="tchead bad">${
      job.action === "remove" ? "Removing" : "Adding"} ${esc(job.image)} failed: ${esc(job.error)}.
      The Jobs tab has its log.</div>` : ""}
    ${(d.images || []).length
      ? `<div class="tcs">${d.images.map(im => emuRow(im, held)).join("")}</div>`
      : d.wrong_platform ? ""
      : `<div class="tchead">${d.known === false
          ? `${esc(d.name)}'s agent is too old to report its system images: update it from the Nodes tab.`
          : `No image yet: ${esc(d.name)}'s emulator has nothing to boot.`}</div>`}
    ${d.wrong_platform ? "" : emuAddRows(d, held)}
    ${d.wrong_platform ? "" : `<div class="hint tcterms">Adding an image accepts
      <a href="https://developer.android.com/studio/terms" target="_blank" rel="noreferrer">Google's
      Android SDK terms</a>.</div>`}
    ${d.wrong_platform || !mayToolchains() ? "" : `<div class="actbar macros">
      ${job.running ? `<span class="state tcworking">${job.action === "remove" ? "Removing" : "Adding"} ${
        esc(job.current || job.image || "")}<span class="dots"></span></span>` : ""}
      ${held && !job.running ? `<span class="state bad">${esc(held)}</span>` : ""}
      <button class="primary" data-emu="install"${held || job.running ? " disabled" : ""}>Install selected${
        emuTickedHere(d).length > 1 ? ` (${emuTickedHere(d).length})` : ""}</button>
      ${job.running ? `<button data-emu="abort"${job.aborting ? " disabled" : ""}>${job.aborting ? "Stopping…" : "Abort"}</button>` : ""}
    </div>`}`;

  const sel = el.querySelector("#emuNodeSel");
  if (sel) sel.onchange = () => { emuNode = sel.value; emu = null; emuTicked.clear();
                                  try{ localStorage.setItem("bb.emunode", emuNode); }catch(e){ /* private */ }
                                  emuRev++; drawPanes(); loadEmulator(); };
  el.querySelector("#emuRefresh").onclick = e => { busy(e.currentTarget, "Refreshing"); loadEmulator(); };
  const toTc = el.querySelector("#emuToTc");
  if (toTc) toTc.onclick = e => { e.preventDefault(); tcNode = emuNode; openToolchains(); };
  const fl = el.querySelector("#imgFlavor");
  if (fl) fl.onchange = () => { emuFlavor = fl.value; emuRev++; drawPanes(); };
  el.querySelectorAll(".tc.emnew input").forEach(b => b.onchange = () => {
    b.checked ? emuTicked.add(b.value) : emuTicked.delete(b.value);
    emuRev++; drawPanes();          // the button counts them
  });
  const add = el.querySelector('[data-emu="install"]');
  // Straight in, no confirmation: a download into free space, and each
  // row says its size.
  if (add) add.onclick = () => {
    const ids = emuTickedHere(emu);
    if (!ids.length) return notify("tick something first", true);      // Toolchains' word for it
    emuAct("add", ids, add);
  };
  el.querySelectorAll("[data-rmimg]").forEach(b => b.onclick = () => {
    const id = b.dataset.rmimg;
    const users = (emu?.images || []).find(im => im.id === id)?.avds || [];
    if (confirm(`Remove ${id}?\n\n${users.length
      ? `${users.join(", ")} ${users.length === 1 ? "is" : "are"} built on it and will not boot without it.`
      : "No AVD is built on it."}`))
      emuAct("remove", id, b);
  });
  const ab = el.querySelector('[data-emu="abort"]');
  if (ab) ab.onclick = async () => {
    if (!confirm("Stop this image job? A half-fetched image is removed.")) return;
    busy(ab, "Stopping");
    await postJSON("/api/v1/jobs", {action: "cancel", id: job.id});
    loadEmulator();
  };
  // A timer only while a job is in flight (or the index is being read): an
  // image job can start and finish between two revision polls, and the tab
  // would go from idle to done without ever saying "adding".
  clearTimeout(emuPoll);
  const ticking = !!job.running || !!d.loading;
  if (ticking) emuPoll = setTimeout(loadEmulator, job.running ? 1000 : 1500);
  if (ticking && !tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
}

// The ticks that are still images this node could add: one added since,
// or offered no more, is not sent.
function emuTickedHere(d){
  const can = new Set((d?.addable || []).map(r => r.id));
  return [...emuTicked].filter(id => can.has(id));
}

async function emuAct(action, image, btn){
  if (btn) busy(btn, action === "add" ? "Adding" : "Removing");
  const many = Array.isArray(image);
  try{
    const r = await postJSON("/api/emulator", {action, node: emuNode, ...(many ? {images: image} : {image})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) notify(j.error || `could not start (HTTP ${r.status})`, true);
    else {
      if (many) image.forEach(id => emuTicked.delete(id));
      notify(`${action === "add" ? "adding" : "removing"} ${many && image.length > 1
        ? `${image.length} images` : (many ? image[0] : image)} on ${
        emu?.name || "the node"}; this can take minutes`);
    }
  }catch(e){ notify("could not start: " + e, true); }
  loadEmulator();
}
