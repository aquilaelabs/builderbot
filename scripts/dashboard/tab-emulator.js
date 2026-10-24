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
  if (nodesList === null || nodesStale) await loadNodes();
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
  return `<div class="imgadd emadd ctlrow"><label for="imgFlavor">Kind</label>
      <select id="imgFlavor">${
        flavors.map(f => `<option value="${esc(f.kind)}"${f.kind === chosen ? " selected" : ""}
          >${esc(f.label)}</option>`).join("")}</select>
      ${about ? `<span class="sub imgabout">${esc(about)}</span>` : ""}</div>
    <div class="tcs emaddrows">${mine.map(r => {
      const now = writing.has(r.id);
      return `<label class="tc emnew">
        <input type="checkbox" value="${esc(r.id)}"${why || job.running || !mayToolchains(emuNode) ? " disabled" : ""}${
          emuTicked.has(r.id) || now ? " checked" : ""}>
        <span class="grow">
          <span class="nm">API ${esc(r.api)}</span>
          ${now ? `<span class="sub prog plain">${job.current === r.id ? "adding" : "waiting its turn"}<span class="dots"></span></span>`
                : `<span class="sub where">${[r.size, r.id].filter(Boolean).map(esc).join(" · ")}</span>`}
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
      <span class="nm">${esc(im.api)} <span class="pill">${esc(im.kind)}</span></span>
      <span class="sub where on">${[im.size ? `<span${im.size_from ? ` title="${esc(im.size_from)}"` : ""}>${esc(im.size)}</span>` : "",
        esc(im.id)].filter(Boolean).join(" · ")}</span>
      ${avds}
    </span>
    ${mayToolchains(emuNode) ? rmIcon(`data-rmimg="${esc(im.id)}"`, `remove ${im.id}`, {title: "remove this system image", why}) : ""}
  </label>`;
}

// The page's two lists under their heads (the operator, 18 Oct: the
// Emulator had none): the system images the node holds, and the ones to add
// with their terms and Install selected. The page and its placeholder draw
// them the same.
function emuSections(images, count, add){
  return docSection("emulator", "images", "System images", count, images)
    + docSection("emulator", "add", "Images to add", "", add);
}
// Install selected, and Abort while a job runs, at the foot of Images to add.
// Each project's phones on the node (R123, the operator 23 Oct: removed on
// the page that manages them, not on Storage), largest first: when each last
// started, its quick-boot snapshot, and a Remove that is refused while it
// runs. Its next bb emu start makes it again, empty.
function emuPhonesSaid(phones){
  const mb = phones.reduce((a, p) => a + (p.mb || 0), 0);
  return `${phones.length}, ${mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"}`;
}
function emuPhones(d){
  const may = mayToolchains(emuNode);
  const size = mb => mb === null || mb === undefined ? "?" : mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.round(mb) + " MB";
  const cols = [{label: "Phone"}, {label: "Project"}, {label: "last started"}, {label: "snapshot", num: true},
                {label: "size", num: true}, ...(may ? [{act: true, w: "6.5rem"}] : [])];
  const rows = [...d.phones].sort((a, b) => (b.mb || 0) - (a.mb || 0));
  return `<div class="field"><div class="hint">A phone removed is made again by its project's next <code>bb emu start</code>, empty: what was installed and signed in on it goes.</div></div>`
    + tblWrap(cols, rows.map(p => `<div class="row stack2 emphone">${tblLine(cols, [
      `<span class="name">${esc(p.name)}</span>${p.running ? ` <span class="pill ok">running</span>` : ""}`,
      esc(projLabel(p.project)), p.running ? "now" : p.ran ? esc(ago(p.ran)) : `<span class="dim">never</span>`,
      p.snap_mb ? size(p.snap_mb) : `<span class="dim">none</span>`, size(p.mb),
      ...(may ? [p.running ? `<span class="sub dim">stop it first</span>`
        : `<button type="button" class="danger" data-emuphone="${esc(p.project)}" data-uid="${esc(p.uid)}" data-avd="${esc(p.name)}">Remove</button>`] : [])])}</div>`).join(""), "emphones");
}

function emuAddBar(d, held, job){
  if (!mayToolchains(emuNode)) return "";
  return `<div class="actbar macros">
      ${job.running ? `<span class="state tcworking">${job.action === "remove" ? "Removing" : "Adding"} ${
        esc(job.current || job.image || "")}<span class="dots"></span></span>` : ""}
      ${held && !job.running ? `<span class="state bad">${esc(held)}</span>` : ""}
      <button class="primary" data-emu="install"${held || job.running || !emuTickedHere(d).length ? " disabled" : ""}>Install selected${
        emuTickedHere(d).length > 1 ? ` (${emuTickedHere(d).length})` : ""}</button>
      ${job.running ? abortBtn('data-emu="abort"', job.aborting) : ""}
    </div>`;
}

function renderEmulatorInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  const surf = docSurface(i, "emu");
  if (!surf) return;
  const d = emu;
  if (!d){
    // Its template (R218 step 16): the bar and the add list's label are the
    // page's own; the node's images are on their way.
    surf.setBar(skNodeBar([]));
    // In the page's order: its head line, its tiles, the images it holds,
    // then the ones to add.
    const tile = (l, sub) => `<div class="tile"><span class="tv">${skv(1.4)}</span><span class="tl">${l}</span>${sub ? `<span class="ts">${sub}</span>` : ""}</div>`;
    surf.list.innerHTML = skTpl(`<div class="tchead">System images in ${skv(18)}: what its emulator can boot.</div>
      <div class="field"><div class="tiles">${tile("images")}${tile("AVDs", "built on them")}${tile("free", "on the store")}</div></div>
      ${emuSections(`<div class="tcs">${skRows(2)}</div>`, "", `<div class="tcs">${skRows(2)}</div>`)}`);
    return;
  }
  if (d.error){ surf.list.innerHTML = `<div class="empty">${
    esc("could not read the images: " + d.error)}</div>`; return; }
  if (d.nonode){
    surf.setBar("");
    surf.list.innerHTML = noNodeYet("the emulator runs on a node");

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
  surf.setBar(nodeBar(nodePick("emuNodeSel", pnodes, emuNode)));
  surf.list.innerHTML = `
    <div class="tchead">${d.wrong_platform
      ? `System images are what an emulator boots, and they live on the node that runs it.`
      : d.root
      // Its free space is the tile's to say, once (R218 step 24).
      ? `System images in <code>${esc(d.root)}</code> on ${esc(d.name)}: what its emulator can boot.`
      : `${esc(d.name)} reports no toolchain store yet.`}</div>
    ${
    // Warnings in the notice voice, an action a button beside it rather than
    // a link in the prose (R218 step 24).
    stale ? `<div class="field"><div class="notice warn">${esc(staleWhy(pnode))}. Nothing changes here until it is.</div></div>` : ""}
    ${d.wrong_platform ? `<div class="field"><div class="notice warn emneed">${esc(d.name)} is ${esc(d.platform)},
      and the Android command-line tools and the emulator are packaged for ${
      esc(d.wrong_platform)}: no system image can run there.</div></div>`
      : (d.missing || []).length ? `<div class="field"><div class="notice warn emneed">${esc(d.name)} has no ${
      esc(d.missing.join(" or "))} yet. <button type="button" id="emuToTc">Install from Toolchains</button></div></div>` : ""}
    ${
    // The node's images at a glance (R216): how many, the AVDs built on
    // them, the levels its projects need and have none of, the room left.
    !d.wrong_platform && d.known !== false ? statTiles([
      {label: "images", value: (d.images || []).length},
      {label: "AVDs", value: (d.images || []).reduce((n, im) => n + (im.avds || []).length, 0), sub: "built on them"},
      {label: "levels needed", value: (d.needed || []).length, tone: (d.needed || []).length ? "warn" : "", omit: !(d.needed || []).length},
      // Storage's reading of a size (sgb), TB past ten of them (B842).
      {label: "free", value: typeof d.free_mb === "number" ? sgb(d.free_mb) : "",
       sub: "on the store", omit: typeof d.free_mb !== "number"},
    ]) : ""}
    ${(d.needed || []).map(nd => `<div class="field"><div class="notice warn emlevel">${esc(nd.projects.join(", "))} compile${
      nd.projects.length === 1 ? "s" : ""} against ${esc(nd.level)} and no image of that level is here${
      nd.pick ? `: ${esc(nd.pick)} below is the plain one` : ""}.</div></div>`).join("")}
    ${job.state === "failed" && job.error ? `<div class="tchead bad">${
      job.action === "remove" ? "Removing" : "Adding"} ${esc(job.image)} failed: ${esc(job.error)}.
      The Jobs page has its log.</div>` : ""}
    ${d.wrong_platform ? "" : emuSections((d.images || []).length
      ? `<div class="tcs">${d.images.map(im => emuRow(im, held)).join("")}</div>`
      : `<div class="tchead">${d.known === false
          ? `${esc(d.name)} has not reported its system images yet.`
          : `No image yet: ${esc(d.name)}'s emulator has nothing to boot.`}</div>`,
      (d.images || []).length ? `${d.images.length}` : "none",
      emuAddRows(d, held) + `<div class="hint tcterms">Adding an image accepts
      <a href="https://developer.android.com/studio/terms" target="_blank" rel="noreferrer">Google's
      Android SDK terms</a>.</div>` + emuAddBar(d, held, job))}
    ${(d.phones || []).length ? docSection("emulator", "phones", "Phones", emuPhonesSaid(d.phones), emuPhones(d)) : ""}`;

  // Its sections stand open at a desk and take turns on a phone.
  wireSections(el);
  const sel = el.querySelector("#emuNodeSel");
  // A pick is a history entry (B31), so Back returns to the node before.
  if (sel) sel.onchange = () => navPush(() => { emuNode = sel.value; emu = null; emuTicked.clear();
                                  try{ localStorage.setItem("bb.emunode", emuNode); }catch(e){ /* private */ }
                                  emuRev++; drawPanes(); loadEmulator(); });

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
  el.querySelectorAll("[data-emuphone]").forEach(b => b.onclick = async () => {
    const {emuphone: project, uid, avd} = b.dataset;
    if (!await askYes(`Remove ${avd}, ${projLabel(project)}'s phone on ${emu?.name || "this node"}?\n\nIts next bb emu start makes it again, empty: what was installed and signed in on it goes.`,
                      {verb: "Remove"})) return;
    busy(b, "Removing");
    const j = await (await postJSON("/api/emulator", {action: "phone-remove", node: emuNode, project, uid, name: avd})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify(`removing ${avd}: the list follows once the node has measured again`);
    loadEmulator();
  });
  el.querySelectorAll("[data-rmimg]").forEach(b => b.onclick = async () => {
    const id = b.dataset.rmimg;
    const users = (emu?.images || []).find(im => im.id === id)?.avds || [];
    if (await askYes(`Remove ${id}?\n\n${users.length
      ? `${users.join(", ")} ${users.length === 1 ? "is" : "are"} built on it and will not boot without it.`
      : "No AVD is built on it."}`))
      emuAct("remove", id, b);
  });
  const ab = el.querySelector('[data-emu="abort"]');
  if (ab) ab.onclick = async () => {
    if (!await askYes("Stop this image job? A half-fetched image is removed.")) return;
    busy(ab, "Stopping");
    await postJSON("/api/v1/jobs", {action: "cancel", id: job.id});
    loadEmulator();
  };
  // A timer only while a job is in flight: an image job can start and
  // finish between two revision polls, and the tab would go from idle to
  // done without ever saying "adding". The index being read is not one: its
  // landing moves the emulator revision, which reads the tab again, and a
  // timer beside it made an open ask twice (B757).
  clearTimeout(emuPoll);
  if (job.running) emuPoll = setTimeout(loadEmulator, 1000);
  if ((job.running || d.loading) && !tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
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
  }catch(e){ notify("could not start: " + failWords(e), true); }
  loadEmulator();
}
