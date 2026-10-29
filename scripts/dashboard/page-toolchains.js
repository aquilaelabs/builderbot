// The toolchain store's state and verbs, shared by the Library (what the
// catalog offers), the Installed page (what the node holds) and the pack
// dialogs: the read of a node's store (/api/toolchains), the one job at a
// time it runs (tcAct: install, remove, check, the system packages, abort),
// the lines a toolchain's row says (its terms, system packages, what it
// needs, how its download was checked), the machine's own rows (the NVIDIA
// driver and the container toolkit) and the tool pack dialog (R77). Not a
// page: the Toolchains page it was went with R170, the Library in its place.
//
// Loaded BEFORE the page's own script, so everything here is a declaration
// and nothing runs at load.

// ---- toolchains --------------------------------------------------------
// An install is a job on the node, read back here as it runs, so a page
// keeps saying what it is doing rather than waiting on a request that
// cannot return.

"use strict";

let toolchains = null, tcRev = 0;

// The sizes are measured by a worker on the server, so the first draw after
// an install (or after a restart) carries the catalog's estimates and the
// real numbers land a moment later. One follow-up ask while that is true,
// not a poll: the flag clears when the measurement finishes, and nothing else
// on this tab changes on its own.
let tcSizeTimer = null;
async function loadToolchains(){
  const asked = ++tcLoadSeq;
  if (nodesList === null || nodesStale) await loadNodes();
  if (asked !== tcLoadSeq) return;           // a later load asks instead
  if (!tcPick()){
    toolchains = {nonode: true};
    clearTimeout(tcSizeTimer); tcSizeTimer = null;
    tcRev++; drawPanes();
    return;
  }
  // A reply is kept when it is still about the node on show and nothing
  // asked after it has landed first. Dropping every reply a later ask had
  // overtaken was a livelock on a loaded box: the revision watch, the
  // sizing timer and the settling poll each ask again, and when they asked
  // faster than one read came back, every reply was overtaken, the page sat
  // on its template, and Forward to a node never said what it held (B154).
  const node = tcNode;
  const keep = () => tcNode === node && asked > tcLanded;
  try{
    const r = await fetch("/api/toolchains" + (node !== "local" ? `?node=${encodeURIComponent(node)}` : ""));
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (!keep()) return;
    toolchains = got;
  }catch(e){ if (!keep()) return; toolchains = {error: String(e)}; }
  tcLanded = asked;
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
// Every animated ellipsis on the page, not just the toolchain rows': the
// Projects card grew one when clones moved to a background job, and two
// tickers running at different phases would read as a fault.
// Which node's store is read: the Library's and the Installed page's node,
// which each set here before they read. Empty until tcPick() chooses one,
// and empty when there is none to choose: toolchains are installed on
// NODES (roadmap #26), and this container is never offered: what it keeps is
// the Playwright browsers its boot hook put on its store for bb capture shot.
// "local" is still what that installer is called (`bb toolchains install`
// from a shell and the suite address it) but no page sets it.
let tcNode = "";
let tcLoadSeq = 0;         // each load's number, in the order asked
let tcLanded = 0;          // the newest load drawn: an older reply landing after it is dropped

// The node the store is read for: the one a page showed last (remembered
// in this browser), else the first live agent node, else nothing. Re-asked
// on every load, so a node retired under a page is not read as if it were
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
  const fix = p.installed && miss.length && tcSandboxNow && mayToolchains(tcNode)
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
    mayToolchains(tcNode) ? gone.map(n => ` <button type="button" class="link" data-tcneed="${esc(n)}">Install ${esc(n)}</button>`).join("") : ""}</span>`;
}

// What installing a toolchain is under, on its own row (the operator, 7
// Oct): an agreement Install accepts said as one, then the licenses.
function tcTermsLine(p){
  const link = t => `<a href="${esc(t.url)}" target="_blank" rel="noreferrer">${esc(t.label)}</a>`;
  const acc = (p.terms || []).filter(t => t.accept), lic = (p.terms || []).filter(t => !t.accept);
  if (!acc.length && !lic.length) return "";
  return `<span class="sub tcterms">${acc.length ? `Installing it asks you to accept ${acc.map(link).join(" and ")}.` : ""}${
    acc.length && lic.length ? " " : ""}${lic.length ? `Licensed: ${lic.map(link).join(", ")}.` : ""}</span>`;
}

// How an installed toolchain's download was checked when it was installed
// (R137): against what its publisher states, or not, and why not. Nothing
// for one installed before BuilderBot checked.
function tcVerifiedLine(p){
  const v = p.installed ? p.verified : null;
  if (!v) return "";
  return v.algo === "none"
    ? `<span class="sub tcverified">Not checked when it was installed: ${esc(v.where)}</span>`
    : v.algo === "gpg" ? `<span class="sub tcverified">Checked when it was installed: ${esc(v.where)}</span>`
    : `<span class="sub tcverified">Checked when it was installed: its ${esc(v.algo)} matched ${esc(v.where)}</span>`;
}
// ---- tool packs (R77) -------------------------------------------------------
// The packs an administrator added, as a table, a row each with Edit at its
// end and Add tool pack over it, both opening one dialog (tpDraw). A pack is
// looked at before it is added: the dialog fetches its manifest at a commit
// and shows what it would download and run, and Add keeps exactly that commit.
const TP_COLS = [{label: "Pack"}, {label: "From"}, {label: "Commit", w: "6.5rem"},
  {label: "Added by", w: "minmax(0,.6fr)"}, {act: true, w: "5rem"}];
let tpEdit = null;             // the dialog's pack: "" for Add tool pack, else the name of the pack in Edit
// `from` is where Add takes the pack (a repository, a pasted bbtool.json or
// an uploaded archive of its files); a pack made here edits by the last two.
let tpForm = {url: "", seen: null, error: "", busy: "", from: "repo", text: "", file: null, catalog: null, what: "pack", app: null};
const TP_BLANK = () => ({url: "", seen: null, error: "", busy: "", from: "repo", text: "", file: null, catalog: null,
                         // What is being added (R170 step 3): a tool pack, or an app of the person's own (its compose file).
                         what: "pack", app: {id: "", name: "", what: "", port: "", compose: "", editing: ""}});
// The vetted catalog (R169 step 4): its index as /api/catalog answers it,
// read when the page opens and on Refresh, never polled.
let tpCatalog = null;
async function loadCatalog(fresh){
  try{ tpCatalog = await (await fetch("/api/catalog" + (fresh ? "?fresh=1" : ""))).json(); }
  catch(e){ tpCatalog = {error: "the catalog: " + failWords(e)}; }
  tcRev++; drawPanes();
}

// What a pack would install and give a session, from the manifest a look
// fetched: its downloads are its install steps, its verbs the words each
// runs, so the person adding it reads both before Add.
// `offer` is whether Add or Update stands beside it: the plain-http warning
// is about approving what is shown, so it is said only then.
// On an update, `was` is the installed pack's (its verbs' words and its
// install steps): what the new commit changes is said on its line, and a
// verb it drops is listed as gone, so the approval is of the difference.
function tpSeen(seen, was, offer = true){
  const m = seen.manifest, w = a => `<code>${esc(a.join(" "))}</code>`;
  const same = (a, b) => JSON.stringify(a || null) === JSON.stringify(b || null);
  const mark = (now, then) => !was ? "" : then === undefined ? ` <span class="pill warn">new</span>`
    : same(now, then) ? "" : ` <span class="pill warn">changed</span> <span class="sub">was ${w(then)}</span>`;
  const verbs = Object.entries(m.verbs || {}).map(([v, x]) =>
    `<div class="sub">bb tool ${esc(m.name)} ${esc(v)} ${esc(x.usage || "")} runs ${w(x.run)}${mark(x.run, was?.runs?.[v])}${
      x.about ? `: ${esc(x.about)}` : ""}</div>`).join("")
    + Object.keys(was?.runs || {}).filter(v => !(v in (m.verbs || {})))
      .map(v => `<div class="sub">bb tool ${esc(m.name)} ${esc(v)} <span class="pill warn">gone</span></div>`).join("");
  const steps = (m.steps || []).map(w).join(", ") + (was && !same(m.steps || [], was.steps || [])
    ? ` <span class="pill warn">changed</span>${(was.steps || []).length ? ` <span class="sub">was ${(was.steps || []).map(w).join(", ")}</span>` : ""}` : "");
  return `<div class="tpseen">
    <div class="name">${esc(m.label)} <span class="pill">${esc(m.name)}</span> <span class="sub">${seen.here
      ? `as given here, ${seen.nfiles} file${seen.nfiles === 1 ? "" : "s"}` : `at ${esc(seen.commit.slice(0, 12))}`}</span></div>
    ${m.about ? `<div class="sub">${esc(m.about)}</div>` : ""}
    <div class="sub">Installs ${seen.here ? "by copying these files to the node" : "by fetching the repository at that commit"}${steps ? `, then running ${steps}` : ""}${
      m.verify ? `, and checks it with ${w(m.verify)}` : ""}; on ${esc((m.platforms || []).join(", "))}.</div>
    ${verbs}
    ${(m.touches?.hosts || []).length ? `<div class="sub">Its install fetches from ${m.touches.hosts.map(h => `<code>${esc(h)}</code>`).join(", ")}.</div>` : ""}
    ${(m.works_with || []).length ? `<div class="sub">It works with BuilderBot ${esc(m.works_with.join(", "))}.</div>` : ""}
    ${m.touches?.root ? `<div class="hint warn">It needs root on the node to install: only an administrator adds it.</div>` : ""}
    ${(m.terms || []).length ? `<div class="sub">Under ${m.terms.map(t => t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.label)}</a>` : esc(t.label)).join(", ")}.</div>` : ""}
    ${seen.guidance ? `<div class="sub">Comes with guidance a session reads as <code>bb help tool-${esc(m.name)}</code>.</div>` : ""}
    ${seen.plain && offer ? `<div class="hint warn">Fetched over plain http: what Add keeps is this commit, checked by its hash, but read what it runs here before you add it.</div>` : ""}
  </div>`;
}

// An app of the person's own (R170 step 3, the Library's Add your own): a
// compose file with the blanks New container fills, its id, name, what it
// is and its port; Look checks it the way the shipped apps are held (every
// image pinned, no blank but the known ones) and says what it would run;
// Add keeps it at tier sideloaded, and it is offered as any app is.
function tpAppHtml(f){
  const a = f.app, ed = !!a.editing;
  return `<div class="field setrow col ctlrow">${lbl("tpAppName", "Name", "what the card says")}
      <input id="tpAppName" value="${esc(a.name)}" maxlength="60" autocomplete="off" placeholder="Notes"></div>
    <div class="field setrow col ctlrow">${lbl("tpAppId", "Id", "its name as a container and in the address: lower-case letters, digits and dashes")}
      <input id="tpAppId" value="${esc(a.id)}" maxlength="32" autocomplete="off" spellcheck="false" placeholder="notes"${ed ? " disabled" : ""}></div>
    <div class="field setrow col ctlrow">${lbl("tpAppWhat", "What it is", "one line, as the card says it")}
      <input id="tpAppWhat" value="${esc(a.what)}" maxlength="200" autocomplete="off" placeholder="a notebook with a web page"></div>
    <div class="field setrow col ctlrow">${lbl("tpAppPort", "Port", "the port it answers on; New container offers it, and a person can pick another")}
      <input id="tpAppPort" type="number" min="1" max="65535" value="${esc(String(a.port || ""))}" placeholder="8080"></div>
    <div class="field">${lbl("tpAppCompose", "Its compose file", "images pinned to a tag, never latest; ${PORT}, ${DATA}, ${MEDIA}, ${PUID}, ${PGID} and ${TZ} are the blanks New container fills")}
      <textarea id="tpAppCompose" class="mono" rows="12" spellcheck="false" autocomplete="off"
        placeholder='services:\n  notes:\n    image: ghcr.io/owner/notes:1.2.3\n    ports:\n      - "\${PORT}:8080"\n    volumes:\n      - \${DATA}/notes:/data'>${esc(a.compose)}</textarea></div>`;
}
function tpAppSeen(seen){
  return `<div class="tpseen">
    <div class="sub">Runs ${seen.services.length === 1 ? "one container" : `${seen.services.length} containers`}, each from a pinned image${seen.media ? ", with a media folder beside its data" : ""}:</div>
    ${seen.services.map(s => `<div class="sub"><b>${esc(s.name)}</b> from <code>${esc(s.image)}</code>${s.ports.length ? `, on ${s.ports.map(x => `<code>${esc(x)}</code>`).join(", ")}` : ""}${
      s.volumes.length ? `, keeping ${s.volumes.map(x => `<code>${esc(x)}</code>`).join(", ")}` : ""}</div>`).join("")}
    <div class="sub">Blanks New container fills: ${seen.blanks.map(b => `<code>${esc(b)}</code>`).join(", ")}.</div>
  </div>`;
}
async function tpAppLook(){
  const f = tpForm;
  f.busy = "look"; f.error = ""; tpDraw();
  const j = await (await postJSON("/api/nasapps", {action: "preview", compose: f.app.compose})).json().catch(() => ({error: "no answer"}));
  if (tpEdit === null) return;
  f.busy = ""; f.seen = j.error ? null : j; f.error = j.error || ""; tpDraw();
}
// Edit on a sideloaded app's card: its record as kept, to change in place.
async function tpOpenApp(id){
  tpEdit = ""; tpForm = TP_BLANK(); tpForm.what = "app"; tpForm.app.editing = id; tpForm.app.id = id;
  tpDraw(true);
  const j = await (await postJSON("/api/nasapps", {action: "source", app: id})).json().catch(() => ({error: "no answer"}));
  if (tpEdit === null || tpForm.app.editing !== id) return;
  if (j.error) tpForm.error = j.error;
  else Object.assign(tpForm.app, {name: j.name, what: j.what, port: j.port, compose: j.compose});
  tpDraw();
}

// The dialog Add tool pack and a row's Edit open (the operator, 19 Oct): the
// repository, Look, what it would install and run, then Add. A pack already
// here is looked at again as Edit opens, so its foot is Remove, Close and,
// when the repository has moved on, Update: three short words that sit on
// one row on a phone.
// Where a new pack comes from, and a pack made here's own two: its
// manifest as text, and an archive of its files.
// What is being added: a tool pack (a toolchain of the person's choosing,
// giving sessions bb tool verbs) or an app (a container the Containers page
// runs). An agent pack is a tool pack with an agent block, so it is the first.
function tpWhatHtml(f){
  return `<div class="field"><label id="tpWhatLabel">What</label>
    <div class="pseg" role="group" aria-labelledby="tpWhatLabel">${[["pack", "A tool pack"], ["app", "An app"]]
      .map(([k, t]) => `<button type="button" data-tpwhat="${k}" class="${f.what === k ? "on" : ""}" aria-pressed="${f.what === k}">${t}</button>`).join("")}</div>
    <div class="hint">${f.what === "app" ? "A compose file of your own, offered in New container and on the Library's Apps cards like the shipped ones, kept as sideloaded."
      : "A tool pack installs on a node like any toolchain and gives a session bb tool verbs; a pack with an agent block is a coding agent. Help's Tool packs says how to write one."}</div></div>`;
}
function tpFromHtml(f, here){
  const seg = here ? "" : `<div class="field"><label id="tpFromLabel">From</label>
    <div class="pseg" role="group" aria-labelledby="tpFromLabel">${[["repo", "A repository"], ["paste", "Paste bbtool.json"], ["upload", "Upload files"]]
      .map(([k, t]) => `<button type="button" data-tpfrom="${k}" class="${f.from === k ? "on" : ""}" aria-pressed="${f.from === k}">${t}</button>`).join("")}</div></div>`;
  if (f.catalog) return `<div class="field"><div class="sub">From the vetted catalog: <b>${esc(f.catalog.name)}</b> at <code>${esc(f.catalog.url)}</code>, commit ${esc(f.catalog.commit.slice(0, 12))}, its archive checked against the catalog's sha256 on the way in.</div></div>`;
  if (f.from === "repo") return seg + `<div class="field">${lbl("tpUrl", "Repository", "a git repository with a bbtool.json at its root: https, ssh, or http for a git host on your network")}
      <input id="tpUrl" value="${esc(f.url)}" placeholder="https://github.com/owner/repo" autocomplete="off" spellcheck="false"></div>`;
  const text = `<div class="field">${lbl("tpText", here ? "Its bbtool.json" : "bbtool.json",
      "the whole pack when its install steps fetch the tool itself; Help's Tool packs says what each field is")}
      <textarea id="tpText" class="mono" rows="12" spellcheck="false" autocomplete="off"
        placeholder='{"name": "mytool", "platforms": ["linux/amd64"], "install": {...}, "verbs": {...}}'>${esc(f.text)}</textarea></div>`;
  const file = `<div class="field">${lbl("tpFile", here ? "Or upload a new version" : "The pack's files",
      "a zip or tar with bbtool.json at its top and the scripts it runs; a single top-level folder is dropped; up to 8 MB")}
      <input id="tpFile" type="file" hidden accept=".zip,.tar,.tgz,.tar.gz,.tbz2,.tar.bz2,.txz,.tar.xz,application/zip,application/gzip,application/x-tar">
      <div class="filepick ctlline"><button type="button" data-tpfile>Choose an archive</button>
        <span class="dim">${f.file ? esc(f.file.name) : "none picked"}</span></div></div>`;
  return seg + (here ? text + file : f.from === "paste" ? text : file);
}

function tpModalHtml(){
  const p = tpEdit ? (toolchains?.items || []).find(i => i.name === tpEdit && i.pack) : null;
  const f = tpForm, fresh = !p, seen = f.seen, here = !!p?.pack?.here && !f.catalog;
  // An app of the person's own: its own form, look and foot (R170 step 3).
  if (fresh && f.what === "app"){
    const ed = !!f.app.editing;
    const look = `<button type="button" data-tplook${f.busy ? " disabled" : ""}${seen ? "" : ` class="primary"`}>${f.busy === "look" ? "Looking…" : seen ? "Look again" : "Look"}</button>`;
    const add = seen ? `<button type="button" class="primary" data-tpadd${f.busy ? " disabled" : ""}>${f.busy === "add" ? (ed ? "Saving…" : "Adding…") : ed ? "Save" : "Add"}</button>` : "";
    const rm = ed ? `<button type="button" class="danger" data-tprmapp="${esc(f.app.editing)}">Remove</button>` : "";
    return `<div class="box wide"><h3>${ed ? `${esc(f.app.name || f.app.editing)}, an app you added` : "Add your own"}</h3>
      ${ed ? "" : tpWhatHtml(f)}
      ${tpAppHtml(f)}
      ${seen ? `<div class="field">${tpAppSeen(seen)}</div>` : ""}
      ${f.error ? `<div class="field"><div class="hint bad">${esc(f.error)}</div></div>` : ""}
      ${dlgFoot(`<button type="button" data-tpcancel>Cancel</button>`, `${look}${add}`, rm)}</div>`;
  }
  const newer = !!(seen && p && !here && seen.commit !== p.pack.commit);
  const offer = !!(seen && (fresh || newer || here));
  // Look is Add's first step, Edit's only after a look that failed, and a
  // pack made here's whenever its text or files are given again.
  const look = fresh || f.error || here ? `<button type="button" data-tplook${f.busy ? " disabled" : ""}${offer ? "" : ` class="primary"`}>${
    f.busy === "look" ? "Looking…" : fresh || here ? "Look" : "Look again"}</button>` : "";
  const add = offer ? `<button type="button" class="primary" data-tpadd${f.busy ? " disabled" : ""}>${
    f.busy === "add" ? (fresh ? "Adding…" : "Updating…") : fresh ? "Add" : "Update"}</button>` : "";
  const rm = p ? `<button type="button" class="danger" data-tprm="${esc(p.name)}">Remove</button>` : "";
  return `<div class="box wide"><h3>${fresh ? (f.catalog ? `Install ${esc(f.catalog.name)} from the catalog` : "Add your own") : `${esc(p.label)}, a tool pack`}</h3>
    ${p ? `<div class="field"><div class="sub">${here ? "Made here" : `From <code>${esc(p.pack.url)}</code>`} at ${esc(p.pack.commit.slice(0, 12))}, added by ${
          esc(p.pack.by || "an administrator")}${p.pack.at ? ` ${ago(p.pack.at)}` : ""}. Verbs: ${esc((p.pack.verbs || []).join(", "))}.</div></div>` : ""}
    ${fresh && !f.catalog ? tpWhatHtml(f) : ""}
    ${fresh || here ? tpFromHtml(f, here) : ""}
    ${seen ? `<div class="field">${tpSeen(seen, p ? p.pack : null, offer)}</div>` : ""}
    ${f.error ? `<div class="field"><div class="hint bad">${esc(f.error)}</div></div>` : ""}
    ${p && !here && f.busy === "look" ? `<div class="field"><div class="hint">Looking for a newer commit…</div></div>` : ""}
    ${p && !here && seen && !newer ? `<div class="field"><div class="hint">${f.catalog ? "No newer pin: the vetted catalog pins the commit added." : "No newer commit: the repository's head is the one added."}</div></div>` : ""}
    ${newer ? `<div class="field"><div class="hint">${esc(seen.commit.slice(0, 12))} is ${f.catalog ? "the vetted catalog's newer pin: Update keeps it, its archive checked against the catalog's sha256," : "newer: Update keeps it,"} with the changes marked above.</div></div>` : ""}
    ${dlgFoot(`<button type="button" data-tpcancel>${fresh || offer ? "Cancel" : "Close"}</button>`, `${look}${add}`, rm)}</div>`;
}

function tpSection(items){
  const packs = (items || []).filter(i => i.pack);
  const tier = p => p.pack.tier === "vetted" ? ` <span class="pill ok">vetted</span>` : p.pack.here ? "" : ` <span class="pill">by URL</span>`;
  const rec = p => `<div class="row ngrec">${tblLine(TP_COLS, [
      `${esc(p.label)} <span class="sub">${esc(p.name)}</span>${tier(p)}`, p.pack.here ? `<span class="sub">made here</span>` : `<code>${esc(p.pack.url)}</code>`,
      esc(p.pack.commit.slice(0, 12)),
      esc(p.pack.by || ""), `<button type="button" data-tpedit="${esc(p.name)}">Edit</button>`])}</div>`;
  const body = packs.length ? tblWrap(TP_COLS, packs.map(rec).join(""), "tprecords")
    : `<div class="hint">none yet: Add tool pack brings in a toolchain you choose</div>`;
  return docSection("toolchains", "packs", "Tool packs", packs.length ? `${packs.length} added` : "none added",
    `<div class="field"><div class="hint">Toolchains you add yourself, for any tool: from a git repository, a pasted bbtool.json or an upload of the pack's files.${helpIcon(
      "A pack installs like any toolchain and gives a session bb tool verbs. It is kept as the version you looked at, and a project's sessions use it only once its settings switch it on. Help's Tool packs says how to write one for somebody else's tool.")}</div></div>
    <div class="field"><div class="addbar ctlrow" data-add="pack"><button type="button" data-tpnew>Add tool pack</button></div></div>
    <div class="field">${body}</div>`);
}

// The vetted catalog (R169 step 4): the packs the maintainers reviewed,
// each pinned to a commit, with Install opening the same dialog as Add
// tool pack on that commit (Look first, as always); a withdrawn one is
// said and not offered; the three tiers read on every row.
function tpCatalogSection(items){
  const c = tpCatalog, idx = c?.index, have = new Set((items || []).filter(i => i.pack).map(i => i.name));
  const rows = (idx?.packs || []).filter(e => e.kind !== "app").map(e => `<div class="row${e.withdrawn ? " bad" : ""}"><div class="grow">
      <div class="name">${esc(e.name)} <span class="pill${e.withdrawn ? " bad" : " ok"}">${e.withdrawn ? "withdrawn" : e.tier}</span>${have.has(e.name) ? ` <span class="pill">added</span>` : ""}</div>
      <div class="sub">${esc(e.about || "")}${e.platforms?.length ? ` · ${esc(e.platforms.join(", "))}` : ""} · <code>${esc(e.url)}</code> at ${esc(e.commit.slice(0, 12))}</div>
      </div>${e.withdrawn ? `<span class="acts"><span class="sub bad">${have.has(e.name) ? "remove it from Tool packs" : "not offered"}</span></span>`
        : `<span class="acts"><button type="button" data-tpinstall="${esc(e.name)}"${have.has(e.name) ? " disabled" : ""}>${have.has(e.name) ? "Added" : "Install"}</button></span>`}</div>`).join("");
  const when = idx?.fetched_at ? `read ${ago(idx.fetched_at)}` : "";
  const body = c === null ? skRows(2)
    : `${c.error ? `<div class="hint${idx ? " warn" : " bad"}">${esc(c.error)}${idx ? "; the index read before stands" : ""}</div>` : ""}
       ${rows ? `<div class="rows">${rows}</div>` : idx ? `<div class="empty">Nothing vetted yet: the catalog is open for submissions, and a pack by URL is Add tool pack above.</div>` : ""}`;
  return docSection("toolchains", "catalog", "Vetted catalog", when,
    `<div class="field"><div class="hint">Packs BuilderBot's maintainers reviewed, each pinned to a commit and the sha256 of its archive there, the index signed by them and checked here before it is read.${helpIcon(
      "Install opens the same dialog as Add tool pack on that commit: Look shows what it fetches and runs, and Add keeps exactly that. The catalog's address is under Controller settings.")}</div></div>
    <div class="field"><div class="addbar ctlrow" data-add="catalog"><button type="button" data-tprefresh>Refresh</button></div></div>
    <div class="field">${body}</div>`);
}
function tpOpenCatalog(entry){
  tpEdit = "";
  tpForm = {...TP_BLANK(), url: entry.url, catalog: entry};
  tpDraw(true);
  tpLook();
}

// The section's two doors into the dialog.
function tpWire(el){
  el.querySelectorAll("[data-tpnew]").forEach(b => b.onclick = () => tpOpen(""));
  el.querySelectorAll("[data-tpedit]").forEach(b => b.onclick = () => tpOpen(b.dataset.tpedit));
  el.querySelectorAll("[data-tprefresh]").forEach(b => b.onclick = () => pressing(b, async () => { busy(b, "Reading"); await loadCatalog(true); }));
  el.querySelectorAll("[data-tpinstall]").forEach(b => b.onclick = () => {
    const e = (tpCatalog?.index?.packs || []).find(x => x.name === b.dataset.tpinstall);
    if (e) tpOpenCatalog(e);
  });
  if (tpCatalog === null) loadCatalog(false);
}

// A pack kept from the vetted catalog (R169 step 4) looks at the index's
// pin, never at its repository's head: the newer pin `pin` when the Library
// offers one, else the index's own pin for it, read first if not yet read.
// Update then keeps it at that pin with the index's sha256, its tier kept.
async function tpOpen(name, pin){
  const pack = name ? (toolchains?.items || []).find(i => i.name === name)?.pack : null;
  const vetted = pack && (pack.tier === "vetted" || pack.tier === "official");
  if (vetted && !pin && !tpCatalog?.index) await loadCatalog(false);
  pin = pin || (vetted ? tpPinOf(name, pack) : null);
  tpEdit = name || "";
  tpForm = TP_BLANK();
  if (pin) tpForm.catalog = {...pin, name};
  const here = !!pack?.here && !pin;
  if (here) tpForm.from = "paste";
  tpDraw(true);
  if (here) tpSource();
  else if (tpEdit) tpLook();
}
function tpPinOf(name, pack){
  const e = (tpCatalog?.index?.packs || []).find(x => x.name === name && x.url === pack.url && (x.path || "") === (pack.path || "") && !x.withdrawn);
  return e ? {url: e.url, commit: e.commit, sha256: e.sha256, path: e.path || ""} : null;
}

// A pack made here opens on its bbtool.json as kept, to change in place.
async function tpSource(){
  const name = tpEdit;
  const j = await (await postJSON("/api/toolpacks", {action: "source", name})).json().catch(() => ({error: "no answer"}));
  if (tpEdit !== name) return;
  if (j.error) tpForm.error = j.error; else tpForm.text = j.text;
  tpDraw();
}

// Show what the pack holds: a repository fetched at its head (Add's Look,
// and what Edit does as it opens), or a pack made here from the text or the
// archive given, checked and held on the controller until Add.
async function tpLook(){
  const name = tpEdit, f = tpForm;
  const pack = name ? (toolchains?.items || []).find(i => i.name === name)?.pack : null;
  f.busy = "look"; f.error = ""; tpDraw();
  let body;
  if (pack && f.catalog) body = {action: "preview", url: f.catalog.url, commit: f.catalog.commit, sha256: f.catalog.sha256, path: f.catalog.path || ""};
  else if (pack && !pack.here) body = {action: "preview", url: pack.url};
  else if (!pack && f.catalog) body = {action: "preview", url: f.catalog.url, commit: f.catalog.commit, sha256: f.catalog.sha256, path: f.catalog.path || ""};
  else if (!pack && f.from === "repo") body = {action: "preview", url: f.url.trim()};
  else if (f.file){
    // The archive goes up on its own first, as New project's does, and the
    // look quotes the id the spool hands back.
    const u = await fetch("/api/upload-archive?name=" + encodeURIComponent(f.file.name), {method: "POST", body: f.file});
    const uj = await u.json().catch(() => ({}));
    if (!u.ok || uj.error){
      if (tpEdit !== name) return;
      f.busy = ""; f.error = uj.error || `the upload failed (HTTP ${u.status})`; tpDraw(); return;
    }
    body = {action: "preview", archive: uj.id};
  } else body = {action: "preview", text: f.text};
  const j = await (await postJSON("/api/toolpacks", body)).json().catch(() => ({error: "no answer"}));
  if (tpEdit !== name) return;                 // closed, or another opened, meanwhile
  f.busy = ""; f.seen = j.error ? null : j; f.error = j.error || ""; tpDraw();
}

function tpClose(){
  const m = document.getElementById("tpmodal");
  if (m) m.hidden = true;
  tpEdit = null;
}

// Drawn again on each step (looking, what came back, adding), the URL as
// typed kept in tpForm across the redraws. The height its From panes share,
// measured as it opens (holdPanes' way, the operator, 26 Oct), held on every
// redraw since each draws the box anew.
let tpHeld = 0;
function tpDraw(first){
  let m = document.getElementById("tpmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "tpmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  m.innerHTML = tpModalHtml();
  m.hidden = false;
  if (first){
    tpHeld = 0;
    if (m.querySelector("[data-tpfrom]")){
      const was = tpForm.from;
      let h = 0;
      for (const k of [...m.querySelectorAll("[data-tpfrom]")].map(x => x.dataset.tpfrom)){
        tpForm.from = k;
        m.innerHTML = tpModalHtml();
        h = Math.max(h, m.querySelector(".box").getBoundingClientRect().height);
      }
      tpForm.from = was;
      m.innerHTML = tpModalHtml();
      tpHeld = Math.ceil(h);
    }
  }
  // Held while From is chosen; what a look brings back is a step of its own.
  if (tpHeld && !tpForm.seen) Object.assign(m.querySelector(".box").style, {boxSizing: "border-box", height: tpHeld + "px"});
  m.onclick = e => { if (e.target === m) tpClose(); };
  const url = m.querySelector("#tpUrl");
  if (url){
    url.oninput = () => { tpForm.url = url.value; if (tpForm.seen || tpForm.error){ tpForm.seen = null; tpForm.error = ""; tpDraw(); url.focus(); } };
    url.onkeydown = e => { if (e.key === "Enter") m.querySelector("[data-tplook]")?.click(); };
    if (first) url.focus();
  }
  m.querySelectorAll("[data-tpwhat]").forEach(b => b.onclick = () => {
    if (tpForm.what === b.dataset.tpwhat) return;
    Object.assign(tpForm, {what: b.dataset.tpwhat, seen: null, error: ""});
    tpDraw();
    m.querySelector("#tpAppName, #tpUrl, #tpText")?.focus();
  });
  for (const [id, key] of [["tpAppName", "name"], ["tpAppId", "id"], ["tpAppWhat", "what"], ["tpAppPort", "port"], ["tpAppCompose", "compose"]]){
    const el = m.querySelector("#" + id);
    if (!el) continue;
    el.oninput = () => { tpForm.app[key] = el.value; if (key === "compose" && (tpForm.seen || tpForm.error)){ tpForm.seen = null; tpForm.error = ""; tpDraw(); m.querySelector("#tpAppCompose")?.focus(); } };
    if (first && id === "tpAppName" && tpForm.what === "app" && !tpForm.app.editing) el.focus();
  }
  const rmApp = m.querySelector("[data-tprmapp]");
  if (rmApp) rmApp.onclick = async () => {
    const id = rmApp.dataset.tprmapp;
    if (!await askYes(`Remove the app ${tpForm.app.name || id}? It leaves the catalog; a container made from it keeps its own compose file.`)) return;
    const j = await (await postJSON("/api/nasapps", {action: "remove", app: id})).json().catch(() => ({error: "no answer"}));
    if (j.error){ tpForm.error = j.error; tpDraw(); return; }
    notify(`${tpForm.app.name || id} removed from the catalog`);
    tpClose(); if (typeof loadLibrary === "function") loadLibrary();
  };
  m.querySelectorAll("[data-tpfrom]").forEach(b => b.onclick = () => {
    if (tpForm.from === b.dataset.tpfrom) return;
    Object.assign(tpForm, {from: b.dataset.tpfrom, seen: null, error: ""});
    tpDraw();
    m.querySelector("#tpUrl, #tpText")?.focus();
  });
  const text = m.querySelector("#tpText");
  if (text){
    text.oninput = () => { tpForm.text = text.value; tpForm.file = null;
      if (tpForm.seen || tpForm.error){ tpForm.seen = null; tpForm.error = ""; tpDraw(); m.querySelector("#tpText")?.focus(); } };
    if (first && tpForm.from === "paste" && !tpEdit) text.focus();
  }
  const file = m.querySelector("#tpFile");
  m.querySelector("[data-tpfile]")?.addEventListener("click", () => file?.click());
  if (file) file.onchange = () => { tpForm.file = file.files[0] || null; tpForm.seen = null; tpForm.error = ""; tpDraw(); };
  m.querySelector("[data-tpcancel]").onclick = tpClose;
  const post = async body => (await postJSON("/api/toolpacks", body)).json().catch(() => ({error: "no answer"}));
  const packUrl = () => tpEdit ? (toolchains?.items || []).find(i => i.name === tpEdit)?.pack?.url || "" : tpForm.url.trim();
  const look = m.querySelector("[data-tplook]");
  if (look) look.onclick = tpForm.what === "app" && !tpEdit ? tpAppLook : tpLook;
  const add = m.querySelector("[data-tpadd]");
  if (add) add.onclick = async () => {
    tpForm.busy = "add"; tpDraw();
    if (tpForm.what === "app" && !tpEdit){
      const a = tpForm.app;
      const j = await (await postJSON("/api/nasapps", {action: "add", app: a.id, name: a.name, what: a.what, port: a.port, compose: a.compose, replace: !!a.editing})).json().catch(() => ({error: "no answer"}));
      if (j.error){ tpForm.busy = ""; tpForm.error = j.error; tpDraw(); return; }
      notify(a.editing ? `${a.name} saved` : `${a.name} added: Install on its card opens New container with it picked`);
      tpClose(); if (typeof loadLibrary === "function") loadLibrary();
      return;
    }
    const j = await post(tpForm.seen?.staged ? {action: "add", staged: tpForm.seen.staged}
                                             : {action: "add", url: packUrl(), commit: tpForm.seen?.commit || "",
                                                ...(tpForm.catalog ? {sha256: tpForm.catalog.sha256, path: tpForm.catalog.path || ""} : {})});
    if (j.error){ tpForm.busy = ""; tpForm.error = j.error; tpDraw(); return; }
    notify(j.unchanged ? `${j.pack.name}: nothing changed, so it is kept as it was`
         : j.replaced ? `${j.pack.name} updated: where it is installed, uninstall it and install it again to take the new version`
         : `${j.pack.name} added: install it below like any toolchain`);
    tpClose(); loadToolchains(); if (typeof loadLibrary === "function" && shown("library")) loadLibrary();
  };
  const rm = m.querySelector("[data-tprm]");
  if (rm) rm.onclick = async () => {
    const n = rm.dataset.tprm;
    // Refused while a node's store holds it (B84), said on the form with
    // where, before anything is asked: its files would stay there with no
    // row left to uninstall them from.
    const at = await post({action: "where", name: n});
    if (at.error){ tpForm.error = at.error; tpDraw(); return; }
    if (!await askYes(`Remove the tool pack ${n}? It leaves the catalog, and projects that use it lose it.`)) return;
    const j = await post({action: "remove", name: n});
    if (j.error){ tpForm.error = j.error; tpDraw(); return; }
    tpClose(); loadToolchains();
  };
}

// The NVIDIA driver (R102): installed by the same job as the store's
// toolchains and asked by the same Check for updates, but this machine's own: its kernel module is built for this machine's kernel and
// its libraries must match that module, so it is installed here as root and
// takes the card only when the machine restarts, since nouveau holds it
// until then. Its pulldown (on the Library's card) is the branches apt
// offers there, live only while no driver is installed: one branch at a
// time, so another version means removing this one first (the operator, 30
// Sep), the rule a recipe that cannot update in place already keeps.
const TC_DRIVER = "nvidia-driver";
let tcDriverPick = "";       // the package picked on the row; "" is the recommended one
function tcDriverLine(m){
  const nodesBtn = ` ${pageLink("nodes", "Open the Nodes page")}`;
  switch (m.state){
    case "absent": return `<span class="sub where">not installed: nouveau has the card, so nothing here can compute on it</span>`;
    case "waiting": return `<span class="sub warn">installed; it takes the card when the machine restarts, which Reboot on the node's row does and which ends every session there.${nodesBtn}</span>`;
    case "update": return `<span class="sub warn">${esc(m.installed)} is installed and takes over from ${esc(m.loaded)} when the machine restarts.${nodesBtn}</span>`;
    case "leaving": return `<span class="sub warn">removed; it keeps the card until the machine restarts, when nouveau takes it back.${nodesBtn}</span>`;
    case "nocard": return `<span class="sub warn">installed, but this machine has no NVIDIA card now: it tries for one at every boot and fills the console with "No NVIDIA GPU found". Remove it unless the card is coming back.</span>`;
    default: return `<span class="sub where on">installed, and running the card</span>`;
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
// The NVIDIA container toolkit (R102): the second of the machine's own
// rows, after the driver it needs. It is what lets a container on this
// machine reserve the card, and comes from NVIDIA's package source rather
// than the distribution's, which is said before it is added. Docker
// reloads its configuration for it; no container stops.
const TC_TOOLKIT = "nvidia-container-toolkit";
function tcToolkitLine(m){
  switch (m.state){
    case "absent": return `<span class="sub where">not installed: a container here cannot reserve the card${
      m.driver ? "" : ". It needs the driver: installed together, the driver goes on first"}</span>`;
    case "nocard": return `<span class="sub warn">installed, but this machine has no NVIDIA card now, and its refresh service restarts every second looking for one. Remove it unless the card is coming back.</span>`;
    case "unconfigured": return `<span class="sub warn">installed, but Docker here does not list the nvidia runtime: Install it again from the Library, which configures Docker again</span>`;
    default: return m.driver_loaded
      ? `<span class="sub where on">installed: a compose file reserves the card with deploy.resources.reservations.devices (driver: nvidia)</span>`
      : `<span class="sub warn">installed; a container sees the card once the driver above is running it</span>`;
  }
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
    if (!await askYes("Stop after the toolchain it is on? What has already installed stays."))
      return;
    // On a node the install is a job, and stopping it is the queue's Cancel.
    if (tcNode !== "local" && toolchains?.job?.id)
      await postJSON("/api/v1/jobs", {action: "cancel", id: toolchains.job.id});
    else
      await postJSON("/api/toolchains", {action});
    return loadToolchains();
  }

  // "Check for updates" asks about every row: the question is whether
  // anything is out of date and what the rest would install, not whether
  // one row is. Sending a selection made it answer for that one toolchain
  // and leave the others showing yesterday's answer.
  const names = only || [];
  if (!names.length && action !== "check" && action !== "sysdeps")
    return notify("nothing selected", true);
  // The driver is the one row whose install ends at a restart: said once,
  // before anything is queued.
  const drv = names.includes(TC_DRIVER) && action === "install";
  if (drv && !await askYes(`Install NVIDIA's driver on ${toolchains?.name || "this node"}? It takes the card only when the machine restarts, which ends every session on it.`))
    return;
  // ...and the toolkit is the one that adds a package source of somebody
  // else's to the machine.
  if (names.includes(TC_TOOLKIT) && action === "install"
      && !await askYes(`Install the NVIDIA container toolkit on ${toolchains?.name || "this node"}? It adds NVIDIA's own package source to the machine. Running containers keep running.`))
    return;
  try{
    const body = {action, names, node: tcNode, ...(drv && tcDriverPick ? {driver: tcDriverPick} : {})};
    let r = await postJSON("/api/toolchains", body);
    let j = await r.json().catch(() => ({}));
    // An agreement a toolchain installs under (Google's Android SDK terms,
    // NVIDIA's CUDA license) is the person's to accept, named, before
    // anything is fetched: the server says which, and keeps who accepted.
    if (r.status === 409 && Array.isArray(j.accept) && j.accept.length){
      if (!await askYes(`Installing ${names.join(", ")} accepts ${j.accept.map(t => t.label).join(" and ")}.\n\n${
            j.accept.map(t => `${t.label}: ${t.url}`).join("\n")}\n\nAccept and install?`)) return;
      r = await postJSON("/api/toolchains", {...body, accept: j.accept.map(t => t.label)});
      j = await r.json().catch(() => ({}));
    }
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
  }catch(e){ notify("could not start: " + failWords(e), true); }
}
