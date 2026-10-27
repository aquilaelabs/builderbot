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
// Loaded BEFORE the page's own script, so
// everything here is a declaration and nothing runs at load.

// ---- toolchains --------------------------------------------------------
// A page rather than a dialog: installing an SDK is not a detour to
// dismiss, it is a thing to leave running for the several minutes it takes
// while you work elsewhere.
//
// Installs are queued by the server and polled from here, so the list keeps
// reporting progress instead of freezing on a request that cannot return.

"use strict";

let toolchains = null, tcRev = 0, tcPoll = null;
// The bar's main action as a row's hint names it: the words the button
// wears at the width the page is at.
const tcInstallSaid = () => barSaid("Install selected", "Install");
const tcTicked = new Set();     // survives a redraw; a poll must not untick
const tcOpen = new Set();       // the rows opened on their details (R218 step 22)

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
  const verb = {install: "Installing", remove: "Removing", update: "Updating"}[job.action] || "Working on";
  const row = (items || []).find(i => i.name === job.current);
  const what = row?.label || (job.current || "").replace(/^android:/, "");
  const done = (job.done || []).length + (job.failed || []).length + (job.passed || []).length,
        left = (job.queue || []).length;
  const of = done + left > 0 ? `, ${done + 1} of ${done + left + 1}` : "";
  return `${esc(verb)} ${esc(what)}${of}<span class="dots"></span>`;
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
  // "present" is a census's word for a tool that answered without a
  // version (the emulator): the cell says "installed" for it instead.
  const ver = p.version && p.version !== "-" && p.version !== "present"
    ?` <span class="pill" title="installed">${esc(p.version)}</span>` : "";
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
    ? `<span class="sub upd">update available: tick it and press ${tcInstallSaid()}${
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
  // Closed, the row is its name and what it is for on one line; its terms,
  // system packages, what it needs and where it lives are on the open row
  // (R218 step 22, rows-you-open), opened by Details beside its name.
  const open = tcOpen.has(p.name);
  return `<label class="tc${upToDate ? " done" : ""}${open ? " open" : ""}">${tblLine(TC_COLS, [
    `<input type="checkbox" value="${esc(p.name)}"${
      busy || noUpgrade ? " disabled" : ""}${
      noUpgrade ? ` checked disabled title="installed; no update in place: a newer version, once a check finds one, is installed in its place"`
      : upToDate ? ` checked disabled title="installed and up to date"`
               : tcTicked.has(p.name) ? " checked" : ""}>
    <span class="grow">
      <span class="nm">${esc(p.label)}</span> <button type="button" class="link tcmore" data-tcmore="${esc(p.name)}"
        aria-expanded="${open}">${open ? "Less" : "Details"}</button>
      <span class="sub tcabout">${esc(p.about)}${
        p.tool ? ` Adds <code>bb tool ${esc(p.tool)}</code> to a session.` : ""}${
        p.pack ? ` A tool pack ${esc(p.pack.by || "an administrator")} added, not shipped with BuilderBot: <code>bb tool ${esc(p.name)}</code>.` : ""}${
        p.needs?.length ? ` Needs ${esc(p.needs.join(", "))}, installed with it.` : ""}${
        p.needed_by?.length ? ` Needed by ${esc(p.needed_by.join(", "))}.` : ""}</span>
      <span class="tcdetail">
      ${tcTermsLine(p)}
      ${tcSystemLine(p, managed)}
      ${tcNeedsLine(p)}
      ${p.installed && p.path && !mine ? `<span class="sub tcpath">at ${esc(p.path)}</span>` : ""}
      ${tcVerifiedLine(p)}
      </span>
    </span>`,
    // Whatever version is known, installed or reported: a node's own
    // versions can name one its census summary does not.
    mine ? prog : `<span class="where${p.installed ? " on" : ""}">${ver || (p.installed ? "installed" : "not installed")}</span>`,
    next, p.size ? `<span class="pill" title="${esc(p.size_from)}">${esc(p.size)}</span>` : "",
    pins.length ? `<span title="${esc(pins.join(", "))}">${esc(pins.join(", "))}</span>` : "",
    p.installed && !mine ? rmIcon(`data-rm="${esc(p.name)}" data-rmlabel="${esc(p.label || p.name)}"`, `uninstall ${p.label}`, {title: `uninstall ${p.label}`, why: busy ? "another toolchain operation is running" : ""}) : ""], "span", "tcline")}
    ${upd}${err}${
      // Sessions that started before this landed still have the old PATH
      // (toolchains.py counts them); one line, and only while there are any.
      p.reopen && !mine ? `<span class="sub warn tcreopen">${p.reopen === 1 ? "1 session" : `${p.reopen} sessions`}
        open here started before this was installed: reopen ${p.reopen === 1 ? "it" : "them"} to use it</span>` : ""}
  </label>`;
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
let tpForm = {url: "", seen: null, error: "", busy: "", from: "repo", text: "", file: null};
const TP_BLANK = () => ({url: "", seen: null, error: "", busy: "", from: "repo", text: "", file: null});

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
    ${(m.terms || []).length ? `<div class="sub">Under ${m.terms.map(t => t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.label)}</a>` : esc(t.label)).join(", ")}.</div>` : ""}
    ${seen.guidance ? `<div class="sub">Comes with guidance a session reads as <code>bb help tool-${esc(m.name)}</code>.</div>` : ""}
    ${seen.plain && offer ? `<div class="hint warn">Fetched over plain http: what Add keeps is this commit, checked by its hash, but read what it runs here before you add it.</div>` : ""}
  </div>`;
}

// The dialog Add tool pack and a row's Edit open (the operator, 19 Oct): the
// repository, Look, what it would install and run, then Add. A pack already
// here is looked at again as Edit opens, so its foot is Remove, Close and,
// when the repository has moved on, Update: three short words that sit on
// one row on a phone.
// Where a new pack comes from, and a pack made here's own two: its
// manifest as text, and an archive of its files.
function tpFromHtml(f, here){
  const seg = here ? "" : `<div class="field"><label id="tpFromLabel">From</label>
    <div class="pseg" role="group" aria-labelledby="tpFromLabel">${[["repo", "A repository"], ["paste", "Paste bbtool.json"], ["upload", "Upload files"]]
      .map(([k, t]) => `<button type="button" data-tpfrom="${k}" class="${f.from === k ? "on" : ""}" aria-pressed="${f.from === k}">${t}</button>`).join("")}</div></div>`;
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
  const f = tpForm, fresh = !p, seen = f.seen, here = !!p?.pack?.here;
  const newer = !!(seen && p && !here && seen.commit !== p.pack.commit);
  const offer = !!(seen && (fresh || newer || here));
  // Look is Add's first step, Edit's only after a look that failed, and a
  // pack made here's whenever its text or files are given again.
  const look = fresh || f.error || here ? `<button type="button" data-tplook${f.busy ? " disabled" : ""}${offer ? "" : ` class="primary"`}>${
    f.busy === "look" ? "Looking…" : fresh || here ? "Look" : "Look again"}</button>` : "";
  const add = offer ? `<button type="button" class="primary" data-tpadd${f.busy ? " disabled" : ""}>${
    f.busy === "add" ? (fresh ? "Adding…" : "Updating…") : fresh ? "Add" : "Update"}</button>` : "";
  const rm = p ? `<button type="button" class="danger" data-tprm="${esc(p.name)}">Remove</button>` : "";
  return `<div class="box wide"><h3>${fresh ? "Add tool pack" : `${esc(p.label)}, a tool pack`}</h3>
    ${p ? `<div class="field"><div class="sub">${here ? "Made here" : `From <code>${esc(p.pack.url)}</code>`} at ${esc(p.pack.commit.slice(0, 12))}, added by ${
          esc(p.pack.by || "an administrator")}${p.pack.at ? ` ${ago(p.pack.at)}` : ""}. Verbs: ${esc((p.pack.verbs || []).join(", "))}.</div></div>` : ""}
    ${fresh || here ? tpFromHtml(f, here) : ""}
    ${seen ? `<div class="field">${tpSeen(seen, p ? p.pack : null, offer)}</div>` : ""}
    ${f.error ? `<div class="field"><div class="hint bad">${esc(f.error)}</div></div>` : ""}
    ${p && !here && f.busy === "look" ? `<div class="field"><div class="hint">Looking for a newer commit…</div></div>` : ""}
    ${p && !here && seen && !newer ? `<div class="field"><div class="hint">No newer commit: the repository's head is the one added.</div></div>` : ""}
    ${newer ? `<div class="field"><div class="hint">${esc(seen.commit.slice(0, 12))} is newer: Update keeps it, with the changes marked above.</div></div>` : ""}
    ${dlgFoot(`<button type="button" data-tpcancel>${fresh || offer ? "Cancel" : "Close"}</button>`, `${look}${add}`, rm)}</div>`;
}

function tpSection(items){
  const packs = (items || []).filter(i => i.pack);
  const rec = p => `<div class="row ngrec">${tblLine(TP_COLS, [
      `${esc(p.label)} <span class="sub">${esc(p.name)}</span>`, p.pack.here ? `<span class="sub">made here</span>` : `<code>${esc(p.pack.url)}</code>`,
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

// The section's two doors into the dialog.
function tpWire(el){
  el.querySelectorAll("[data-tpnew]").forEach(b => b.onclick = () => tpOpen(""));
  el.querySelectorAll("[data-tpedit]").forEach(b => b.onclick = () => tpOpen(b.dataset.tpedit));
}

function tpOpen(name){
  tpEdit = name || "";
  tpForm = TP_BLANK();
  const here = !!(toolchains?.items || []).find(i => i.name === tpEdit)?.pack?.here;
  if (here) tpForm.from = "paste";
  tpDraw(true);
  if (here) tpSource();
  else if (tpEdit) tpLook();
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
  if (pack && !pack.here) body = {action: "preview", url: pack.url};
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
  if (look) look.onclick = tpLook;
  const add = m.querySelector("[data-tpadd]");
  if (add) add.onclick = async () => {
    tpForm.busy = "add"; tpDraw();
    const j = await post(tpForm.seen?.staged ? {action: "add", staged: tpForm.seen.staged}
                                             : {action: "add", url: packUrl(), commit: tpForm.seen?.commit || ""});
    if (j.error){ tpForm.busy = ""; tpForm.error = j.error; tpDraw(); return; }
    notify(j.unchanged ? `${j.pack.name}: nothing changed, so it is kept as it was`
         : j.replaced ? `${j.pack.name} updated: where it is installed, uninstall it and install it again to take the new version`
         : `${j.pack.name} added: install it below like any toolchain`);
    tpClose(); loadToolchains();
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
function tcDriverRow(m, busy, job){
  const card = m.gpu || (String(m.card).match(/\[([^\]]*(?:GeForce|RTX|Quadro|Tesla|TITAN)[^\]]*)\]/)?.[1]) || m.card;
  const ver = m.installed || m.loaded;
  const mine = !!(job && job.running && job.action !== "check" && job.current === TC_DRIVER);
  const doing = job && job.action === "remove" ? "removing" : "installing";
  const may = m.managed && mayToolchains(tcNode);
  // A tick means "do something to this": install it where there is none,
  // update it where apt has a newer one. Installed and current, its box is
  // dead and ticked, as a toolchain's is.
  const upToDate = !mine && m.here && !m.newer;
  const opts = m.options || [];
  const picked = m.here ? m.package : (opts.some(o => o.pkg === tcDriverPick) ? tcDriverPick : "");
  // No card, nothing to pick a version for: the row is there to remove it (B168).
  const sel = opts.length && m.state !== "nocard" ? `<label class="pick tcdrvpick">Version <select id="tcDrvSel" aria-label="driver version"${
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
      <span class="sub">For ${m.card ? `this machine's ${esc(card)}` : "an NVIDIA card"}: CUDA, the hardware video encoder and the emulator's GPU rendering need it. It is this machine's own, not a copy on the store.</span>
      ${sel}
      ${mine ? `<span class="sub prog plain">${esc(doing)}<span class="dots">${".".repeat(tcDots)}</span></span>` : tcDriverLine(m)}
      ${m.newer && !mine ? `<span class="sub upd">update available: ${esc(m.newer)}. Tick it and press ${tcInstallSaid()}</span>` : ""}
      ${job?.errors?.[TC_DRIVER] && !mine ? `<span class="sub bad">${esc(job.errors[TC_DRIVER])}</span>` : ""}
      ${!m.managed ? `<span class="sub warn">This machine is its owner's, not a BuilderBot sandbox: its driver is installed there by hand.</span>` : ""}
    </span>
    ${m.here && !mine && may ? rmIcon("data-tcdrvrm", "uninstall the NVIDIA driver", {title: "remove NVIDIA's driver from this machine", why: busy ? "another toolchain operation is running" : ""}) : ""}
  </div>`;
}

// The NVIDIA container toolkit (R102): the second of the machine's own
// rows, under the driver it needs. It is what lets a container on this
// machine reserve the card, and comes from NVIDIA's package source rather
// than the distribution's, which is said before it is added. Docker
// reloads its configuration for it; no container stops.
const TC_TOOLKIT = "nvidia-container-toolkit";
function tcToolkitLine(m){
  switch (m.state){
    case "absent": return `<span class="sub where">not installed: a container here cannot reserve the card${
      m.driver ? "" : ". It needs the driver above: tick both, and the driver goes on first"}</span>`;
    case "nocard": return `<span class="sub warn">installed, but this machine has no NVIDIA card now, and its refresh service restarts every second looking for one. Remove it unless the card is coming back.</span>`;
    case "unconfigured": return `<span class="sub warn">installed, but Docker here does not list the nvidia runtime: tick it and press ${tcInstallSaid()}, which configures Docker again</span>`;
    default: return m.driver_loaded
      ? `<span class="sub where on">installed: a compose file reserves the card with deploy.resources.reservations.devices (driver: nvidia)</span>`
      : `<span class="sub warn">installed; a container sees the card once the driver above is running it</span>`;
  }
}
function tcToolkitRow(m, busy, job){
  const mine = !!(job && job.running && job.action !== "check" && job.current === TC_TOOLKIT);
  const doing = job && job.action === "remove" ? "removing" : "installing";
  const may = m.managed && mayToolchains(tcNode);
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
      ${m.newer && !mine ? `<span class="sub upd">update available: ${esc(m.newer.split("-")[0])}. Tick it and press ${tcInstallSaid()}</span>` : ""}
      ${job?.errors?.[TC_TOOLKIT] && !mine ? `<span class="sub bad">${esc(job.errors[TC_TOOLKIT])}</span>` : ""}
      ${!m.managed ? `<span class="sub warn">This machine is its owner's, not a BuilderBot sandbox: the toolkit is installed there by hand.</span>` : ""}
    </span>
    ${m.here && !mine && may ? rmIcon("data-tcctkrm", "uninstall the NVIDIA container toolkit", {title: "remove the container toolkit from this machine", why: busy ? "another toolchain operation is running" : ""}) : ""}
  </div>`;
}

// The coding agents (Claude Code, Codex CLI, Copilot CLI) are not here: the
// Agents page (tab-agents.js) installs, updates and removes them (R95, the
// operator 22 Oct), and this page keeps one line saying so.

// The page's two lists under their heads (the operator, 18 Oct: Toolchains
// had none): what belongs to the machine itself (its NVIDIA driver and
// toolkit, Claude Code), when the node has any, and the catalog. The page
// and its placeholder draw them the same.
function tcSections(machine, catalog, status){
  return (machine ? docSection("toolchains", "machine", "This machine", "", machine) : "")
    + docSection("toolchains", "catalog", "Toolchains", status, catalog);
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
  // the picker (no Refresh: the page follows the toolchains and nodes
  // revisions, R256 step 1), so the action sits where a
  // tab's action sits rather than in a band this tab invented. `tc` makes the
  // tctab class the suite finds it by.
  const surf = docSurface(i, "tc");
  if (!surf) return;
  if (!d){
    // Its template (R218 step 16): the bar, the tile's words and the table's
    // head are the page's own; the store and its rows are on their way.
    surf.setBar(skNodeBar([["Check for updates", "", "Check"], ["Install selected", "primary", "Install"]]));
    // In the page's own order: its bar with its two buttons, its head, its
    // tiles, then the catalog's table.
    const tile = (l, sub) => `<div class="tile"><span class="tv">${skv(1.4)}</span><span class="tl">${l}</span>${sub ? `<span class="ts">${sub}</span>` : ""}</div>`;
    surf.list.innerHTML = skTpl(`${pageHead({title: GHOST, cls: "tcact", facts: [["Store", GHOST], ["Versions checked", GHOST]]})}
      <div class="field"><div class="tiles">${tile("installed", `of ${skv(2)} offered`)}${tile("updates due")}${tile("free", "on the store")}</div></div>
      ${tcSections("", skTable(TC_COLS, 6, "tcs"), "")}
      ${state?.can?.admin ? docSection("toolchains", "packs", "Tool packs", "", skTable(TP_COLS, 2, "tprecords")) : ""}`);
    return;
  }
  if (d.error){ surf.list.innerHTML = `<div class="empty">${
    esc("could not read the toolchain list: " + d.error)}</div>`; return; }
  // No node to install on. Not this container: it builds nothing and keeps
  // nothing but the browsers its boot put there, so there is no list to show
  // and no button that would be honest to offer.
  if (d.nonode){
    surf.setBar("");
    surf.list.innerHTML = noNodeYet("toolchains install on a node", "tcnone");
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
  // A store the node reports it cannot write (R85): read-only to it, so
  // nothing installs, said here rather than as a failed job.
  const pro = onNode && (pnodes.find(n => n.id === tcNode) || {}).reported?.store_ro === true;
  // The page's buttons, in its bar with the one node switcher (page-docs.js
  // nodePick, R121), every header button on one row (the operator, 17 Oct):
  // Check for updates, Abort while a job runs, Install selected, and Remove
  // for what no node uses any more (R196), last as a destructive verb is.
  const may = mayToolchains(tcNode);
  const clean = onNode && (d.cleanable || []).length && may ? d.cleanable : [];
  surf.setBar(nodeBar(nodePick("tcNodeSel", pnodes, tcNode), `
      ${busy && may ? abortBtn('data-tc="abort"', job.aborting) : ""}
      <button data-tc="check"${busy ? ` class="tcidle"` : ""}${busy || pstale || !may ? " disabled" : ""}
        title="ask each upstream what it has now">${
        busy && job.action === "check"
          ? `${barSaid("Checking for updates", "Checking")}<span class="dots">${".".repeat(tcDots)}</span>`
        : (d.items || []).some(i => i.state) ? barSaid("Re-check for updates", "Re-check") : barSaid("Check for updates", "Check")}</button>
      ${!may ? "" : `<button class="primary${busy ? " tcidle" : ""}" data-tc="install"${busy || pstale || pro || !tcTicked.size ? " disabled" : ""}
        ${pstale ? `title="${esc(staleWhy(pnodes.find(n => n.id === tcNode)))}"` : ""}
        >${barSaid("Install selected", "Install")}</button>`}
      ${clean.length ? `<button type="button" class="danger${busy ? " tcidle" : ""}" data-tcclean${busy ? " disabled" : ""}>Remove</button>` : ""}`));
  // What the store is and where, said on the page's status line under the
  // tiles (the operator, 17 Oct: one order for every page's top).
  const working = busy && job.action !== "check";
  surf.list.innerHTML = `
    ${pstale ? `<div class="field"><div class="notice warn tcstale">${esc(staleWhy(
      pnodes.find(n => n.id === tcNode)))}. Nothing installs here until it is.</div></div>` : ""}
    ${pro ? `<div class="field"><div class="notice warn tcro">${esc(d.name || "This node")}'s toolchain store is read-only to it, so nothing installs here: what is in it is what it has. Make it writable on the machine to install.</div></div>` : ""}
    ${
    // The page's status line under its tiles (the operator, 16 and 17 Oct):
    // the store and when its versions were checked, or what is running; and
    // what the bar's Remove would take, when it is there. A check is said
    // on its own button, so the line keeps to the store while one runs.
    // ...as a head (the operator, 25 Oct: what a page knows is said the way
    // a node's head says it): the machine, the store's state or the job
    // running as a pill, and the store, its check and what Remove takes as
    // facts.
    pageHead({title: onNode ? d.name || "" : "This controller", cls: "tcact",
      pills: working ? `<span class="pill live state tcworking">${tcWorking(job, d.items)}</span>`
        : d.root ? `<span class="pill ok">store found</span>` : `<span class="pill warn">no store yet</span>`,
      facts: [["Store", d.root || ""],
               ["Kind", !onNode && d.root ? (d.shared ? "a mapped share: an image update never downloads them again"
                                                      : "the home volume: map a store to keep them out of it") : ""],
               ["Versions checked", d.checked ? ago(d.checked) : "not yet"],
               ["Remove takes", clean.length ? clean.map(c => `<code>${esc(c.dir)}</code> (${esc(c.what)})`).join(", ") : "",
                {html: true, cls: "tcclean"}]]})}
    ${
    // The store at a glance (R216): what is installed, what has an update
    // due, what a project needs that the store lacks, and the room left.
    (() => {
      const items = (d.items || []).filter(x => !x.wrong_platform);
      if (!items.length) return "";
      // This machine's rows count too (the driver, the toolkit). The
      // coding agents are the Agents page's to count (R95 step 15).
      const due = items.filter(x => x.state === "update").length
        + (onNode ? (d.machine || []).filter(m => !!m.newer).length : 0);
      const need = items.filter(x => (x.pinned_by || []).length && !x.installed).length;
      return statTiles([
        {label: "installed", value: items.filter(x => x.installed).length, sub: `of ${items.length} offered`},
        {label: due === 1 ? "update due" : "updates due", value: due, tone: due ? "warn" : "", omit: !due && !d.checked},
        {label: "needed by a project", value: need, tone: need ? "warn" : "", omit: !need},
        // Storage's reading of a size (sgb), TB past ten of them (B834).
        {label: "free", value: typeof d.free_mb === "number" ? sgb(d.free_mb) : "",
         sub: "on the store", omit: typeof d.free_mb !== "number"},
      ]);
    })()}
    ${(() => {
      // Held recipes whose system libraries this machine lacks (roadmap
      // R51): the libraries are the machine's own, outside the store, and
      // can go missing while the toolchain stays. One press installs the
      // libraries and leaves the recipes alone.
      tcSandboxNow = !!(onNode && d.sandbox);
      const unmet = Object.entries((onNode && d.sysdeps?.unmet) || {});
      if (!unmet.length) return "";
      const what = unmet.map(([r, ps]) => `${esc(r)}: ${esc(ps.join(" "))}`).join("; ");
      // A warning in the notice voice, its action beside it (R218 step 24).
      return `<div class="field"><div class="notice warn tcsys">System packages ${esc(d.name || "this node")} lacks
          for what its store holds (${esc(d.sysdeps.family || "")}): ${what}.
          ${d.sandbox
            ? `<button type="button" id="tcSysdeps"${busy || pstale ? " disabled" : ""}
                 title="install these on ${esc(d.name || "the node")} without reinstalling the toolchains">Install system packages</button>`
            : `This node's owner installs them: the agent does not administer the machine.`}</div></div>`;
    })()}
    ${tcSections(onNode && (d.machine || []).length ? `<div class="tcs tcmachine">${
      d.machine.map(m => (m.name === TC_TOOLKIT ? tcToolkitRow : tcDriverRow)(m, busy || pstale || d.live === false, job)).join("")}</div>` : "",
      // The coding agents are the Agents page's (R95 step 15): said first
      // inside the Toolchains section, never between sections (the
      // operator, 25 Oct: nothing outside a section).
      (onNode ? `<div class="field tcagents"><div class="hint">The coding agents (${
        esc(AGENTS.filter(a => a.live).map(a => a.product).join(", "))}) are installed and updated on the ${pageLink("agents", "Agents page", `#/build/agents/${encodeURIComponent(d.node || tcNode)}`)}.</div></div>` : "")
      + tblWrap(TC_COLS, (d.items || []).filter(i => !i.wrong_platform)
      .map(i => tcRow(i, busy || pstale, job, !!d.administers && !d.locked)).join(""), "tcs"),
      `${(d.items || []).filter(i => i.installed).length} installed`)}
    ${state?.can?.admin ? tpSection(d.items) : ""}
`;

  // Its sections stand open at a desk and take turns on a phone.
  wireSections(el);
  tpWire(el);
  // Install selected sleeps until something is ticked (the operator, 18
  // Oct: a press that only said "tick something first" was asleep in all
  // but look).
  const inst = el.querySelector('[data-tc="install"]');
  el.querySelectorAll(".tc input").forEach(b => b.onchange = () => {
    b.checked ? tcTicked.add(b.value) : tcTicked.delete(b.value);
    if (inst) inst.disabled = busy || pstale || !tcTicked.size;
  });
  el.querySelectorAll("[data-tc]").forEach(b => b.onclick = () => tcAct(b.dataset.tc));
  const psel = el.querySelector("#tcNodeSel");
  // A pick is a history entry (B31), so Back returns to the node before.
  if (psel) psel.onchange = () => navPush(() => { tcNode = psel.value; toolchains = null; tcTicked.clear(); tcDriverPick = "";
                                    try{ localStorage.setItem("bb.tcnode", tcNode); }catch(e){ /* private */ }
                                    tcRev++; drawPanes(); loadToolchains(); });
  const sd = el.querySelector("#tcSysdeps");
  if (sd) sd.onclick = () => tcAct("sysdeps");
  el.querySelectorAll("[data-tcsys]").forEach(b => b.onclick = () => tcAct("sysdeps", [b.dataset.tcsys]));
  // What no node runs from any more, taken off the store (R196).
  el.querySelectorAll("[data-tcclean]").forEach(b => b.onclick = async () => {
    const dirs = (toolchains?.cleanable || []).map(c => c.dir);
    if (!dirs.length || !await askYes(`Take ${dirs.join(", ")} off the store?\n\nNo node runs from ${dirs.length === 1 ? "it" : "them"}; what is in ${dirs.length === 1 ? "it" : "them"} is gone for good.`, {verb: "Remove", danger: true})) return;
    busy(b, "Removing");
    const j = await (await postJSON("/api/toolchains", {action: "clean", node: tcNode, names: dirs})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    else notify(`taking ${j.queued.join(", ")} off the store: a job on ${toolchains?.name || "the node"}`);
    loadToolchains();
  });
  el.querySelectorAll("[data-tcneed]").forEach(b => b.onclick = () => tcAct("install", [b.dataset.tcneed]));
  const dsel = el.querySelector("#tcDrvSel");
  if (dsel) dsel.onchange = () => {
    // Picking a version is choosing to install it: the tick follows.
    tcDriverPick = dsel.value; tcTicked.add(TC_DRIVER);
    const t = el.querySelector("#tcDrvTick"); if (t && !t.disabled) t.checked = true;
    if (inst) inst.disabled = busy || pstale || !tcTicked.size;
  };
  el.querySelectorAll("[data-tcdrvrm]").forEach(b => b.onclick = async () => {
    // With no card there is nothing for nouveau to take back (B168).
    const gone = (toolchains?.machine || []).some(m => m.name === TC_DRIVER && m.state === "nocard");
    if (await askYes(gone ? `Remove NVIDIA's driver from ${toolchains?.name || "this node"}? It has no card to drive here, and its tries for one stop.`
                     : `Remove NVIDIA's driver from ${toolchains?.name || "this node"}? The emulator's GPU display goes with it, and nouveau takes the card back when the machine restarts.`))
      tcAct("remove", [TC_DRIVER]);
  });
  el.querySelectorAll("[data-tcctkrm]").forEach(b => b.onclick = async () => {
    if (await askYes(`Remove the NVIDIA container toolkit from ${toolchains?.name || "this node"}? A container that reserves the card no longer starts; NVIDIA's package source goes with it.`))
      tcAct("remove", [TC_TOOLKIT]);
  });
  el.querySelectorAll("[data-tcmore]").forEach(b => b.onclick = e => {
    e.preventDefault();                 // inside the row's label: not its tick
    const k = b.dataset.tcmore;
    if (tcOpen.has(k)) tcOpen.delete(k); else tcOpen.add(k);
    tcRev++; drawPanes();
  });
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = async e => {
    // Inside a <label>, so the click would otherwise toggle the checkbox on
    // its way past.
    e.preventDefault(); e.stopPropagation();
    // Asked by the name its row shows: a pack's toolchain's name is the
    // pack's id (B65).
    const name = b.dataset.rm;
    if (await askYes(`Uninstall ${b.dataset.rmlabel || name}? The files are deleted; installing it again re-downloads them.`))
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
    if (!await askYes("Stop after the toolchain it is on? What has already installed stays."))
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
  if (drv && !await askYes(`Install NVIDIA's driver on ${toolchains?.name || "this node"}? It takes the card only when the machine restarts, which ends every session on it.`))
    return;
  // ...and the toolkit is the one that adds a package source of somebody
  // else's to the machine.
  if (names.includes(TC_TOOLKIT) && action === "install"
      && !await askYes(`Install the NVIDIA container toolkit on ${toolchains?.name || "this node"}? It adds NVIDIA's own package source to the machine. Running containers keep running.`))
    return;
  // The ticks stay: a toolchain being installed reads as chosen, and the boxes
  // are ghosted anyway. What happens to them afterwards is decided by how it
  // went: installed rows carry their own tick, failed ones let go of it.
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
