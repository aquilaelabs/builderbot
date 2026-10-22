// The Nodes tab: the node registry, editable. Phases 2 and 3 of
// docs/nodes.md: CRUD over ssh docker hosts, capability toggles, labels,
// pool, concurrency, test, drain, retire; and now enrollment: minting the
// one-time token an agent dials in with, the live/quiet state of each agent
// node, the numbers its heartbeat carries, and revoking its credential. Its
// own classic script beside index.html, per the new-surface rule (§13): same
// page, same global scope, one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs;
// this file only fills slots. Data comes from /api/v1/nodes, fetched when the
// "nodes" revision token moves, never from the status poll.

"use strict";

let nodesList = null;            // last answer, or null before the first
// ...and stale when the nodes token moved while no page that draws the list
// was on show (index.html's watch): the next page to read it loads a fresh
// one, and meanwhile draws the last, so a picker drawn in the same tick as
// its dialog opened still has its nodes.
let nodesStale = false;
// The pages that draw the list: a node picker each, or the rows themselves.
const NODE_READERS = ["nodes", "toolchains", "agents", "emulator", "docker", "projects", "settings"];
let nodesRev = 0;                // bumped when it changes, so panes repaint
let nodesErr = "";
let nodesAgent = null;           // the agent this controller ships: {digest, version}
let nodesDefault = "";           // the node work nobody bound to one lands on
let nodesSystems = [];           // what Enroll node's System pulldown offers (R204)
let nodesPick = "";              // which node the tab is showing, "" until the first draw
// The configuration plane's editor state, per node (docs/nodes.md §12): the
// fold's open flag and the DRAFT the operator is typing. Kept here and not in
// the DOM because the tab repaints on every heartbeat: a field that lived
// only in the row would lose its text every 25 seconds.
const nodesConf = {};
let nodesCheck = {};             // node id -> {text, warn}: Check paths' last verdict (B850)
let nodesFocus = null;           // {id, key, i}: the field to refocus after a repaint
// When Update agent was pressed per node, so the button stays busy until the
// agent comes back with the new digest (see renderNodesInto).
const nodesUpdating = {};

// `nid`, when given, is the node to show, and `what` the part of it the
// caller is about: "agent" for the head bar where Update agent is, or a
// section's id ("claude"), opened. A bell row about a node goes straight
// to that node's control, not to whichever node the tab was on (the
// operator, 4 Oct).
let nodesReveal = null;
function openNodesTab(nid, what){
  if (nid){
    nodesPick = nid;
    nodesFocus = null;
    if (what && what !== "agent") sectOpen["nodes:" + what] = true;
    nodesReveal = what === "agent" ? '[data-nd="update-agent"], .ndagent'
                : what ? `[data-sect="nodes:${what}"]` : null;
    nodesRev++;
  }
  openTab({kind: "nodes", arg: "__nodes", label: "Nodes"});
  loadNodes();
  if (nid) drawPanes();
}

// Each read numbered, so an answer asked for before a later one (a poll's,
// in flight when a save asked again) cannot land after it and stay drawn
// until the nodes next move (B849), as the Toolchains page's tcLoadSeq does.
// A caller awaiting one that was overtaken waits for the newest instead, so
// what it reads after is the list.
let nodesLoadSeq = 0, nodesLoading = null;
function loadNodes(){
  const seq = ++nodesLoadSeq;
  return (nodesLoading = loadNodesOnce(seq));
}
async function loadNodesOnce(seq){
  try{
    const j = await (await bootFetch("/api/v1/nodes")).json();
    if (seq !== nodesLoadSeq) return nodesLoading;
    nodesErr = j.error || "";
    nodesList = j.nodes || [];
    nodesAgent = j.agent || null;
    nodesDefault = j.default || "";
    nodesSystems = Array.isArray(j.systems) ? j.systems : [];
  }catch(e){
    if (seq !== nodesLoadSeq) return nodesLoading;
    nodesErr = String(e);
    nodesList = nodesList || [];
  }
  nodesStale = false;
  nodesRev++;
  // Any page that draws the list is drawn again with it: the Toolchains
  // bar's picker appears when the first node enrolls, as it did when the
  // strip held the Nodes tab.
  if (NODE_READERS.some(shown)) drawPanes();
}

// A button that starts something goes dead the moment it is pressed.
//
// Every action here awaits a round trip: the POST, then loadNodes(), then
// the repaint, and for that second or two the control looked exactly as it
// did before the click. So there was no way to tell a press that had landed
// from one that had missed, and a second press queued a second job or
// collected a "one at a time" refusal for its trouble.
//
// Only the gap: the repaint that follows draws the real state (n.applying,
// the runner's census, a queued job) and replaces this element entirely, so
// the restore below fires only when nothing repainted: an error, or an
// action that changes no state. Put the confirm() BEFORE the call, so
// canceling leaves the button alive.
async function pressing(btn, fn){
  if (!btn || btn.disabled) return undefined;
  btn.disabled = true;
  try{
    return await fn();
  }finally{
    if (btn.isConnected) btn.disabled = false;
  }
}

async function nodeAct(body){
  const j = await (await fetch("/api/v1/nodes", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)})).json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  await loadNodes();
  return j;
}

// What a node can do, offered as toggles. The list is the server's
// (nodes.CAPABILITIES); repeated here only as labels, and an unknown one
// coming back in a record still renders: data wins over this table.
// What a node can do for a project is what is INSTALLED on it, not a set of
// toggles: a project names one node and that node does all of its work (the
// operator's decision, 2 Sep). So the row shows the toolchains the census
// found, and the Tools tab is where they are added. The capability field
// still exists underneath; it is the vocabulary of the node-side refusal,
// §15 door 7, and every node now carries the full set.
const TOOL_LABELS = {java: "java", "android-sdk": "android sdk", emulator: "emulator",
                     flutter: "flutter", dotnet: ".NET", node: "node", go: "go"};

// The git this machine carries, and whether it clears the floor the Git view
// needs (merge-tree --write-tree, 2.38). Shown because NOTHING keeps the
// nodes and the controller in step: git is installed once at enrollment from
// whatever the distribution packages, and on a guest node the machine is its
// owner's, so upgrading it is not the controller's to do. Being able to see
// it, and to be told when one is too old, is what is owed instead.
const GIT_FLOOR = [2, 38];
// The GPU (R20): the NVIDIA card the census names by its PCI id, what the
// display's unit last said, and the press that sets the display up on a
// sandbox node. The reason is on the line, in the state's own words.
function nodeGpu(n){
  const card = n.reported?.gpu_card;
  if (!card) return "";
  const st = n.reported?.gpu_display || "";
  const up = /^up/.test(st), reboot = /^reboot/.test(st);
  // The display runs on NVIDIA's driver and does not install it (R102): the
  // driver is a row on this node's Toolchains tab, and until it is on the
  // machine this line says so and opens that tab. What the card is used
  // for is the GPU section's two switches, below.
  const gd = n.reported?.gpu_driver;
  const nodriver = !!gd && !gd.installed;
  const word = up ? "display up: an emulator here renders on the card"
    : nodriver ? "no NVIDIA driver on it yet: an emulator here renders in software"
    : reboot ? "driver installed; Reboot under Advanced lets it take the card"
    : /^down/.test(st) ? st
    : "no display for it: an emulator here renders in software";
  const cls = up ? "ok" : reboot && !nodriver ? "note" : "warn";
  return `<div class="actbar ndgpu">
    <span class="state ${cls}">gpu: ${esc(card)} · ${esc(word)}</span>
    ${nodriver ? `<button type="button" data-ndtc="${esc(n.id)}"
      title="the driver is installed from this node's Toolchains page">Install the driver</button>` : ""}
  </div>`;
}
// The sound this node has (R107), in a line: the card ALSA sees, or a
// virtual one, and the sound server an emulator's audio would go through.
// Today an emulator here runs with -no-audio whatever this says; the line is
// what the steps after it need, said before anybody reaches for them.
function nodeSound(n){
  const s = n.reported?.sound;
  if (!s || n.kind !== "agent") return "";
  const card = s.cards?.[0] || (s.virtual?.[0] ? `${s.virtual[0]} (virtual)` : "");
  const word = card && s.server ? `${card} through ${s.server}`
    : card ? `${card}, with no sound server installed`
    : s.server ? `no sound card; ${s.server} is installed`
    : "none: no sound card and no sound server";
  return `<div class="actbar ndsound"><span class="state ${card && s.server ? "ok" : ""}">sound: ${esc(word)}</span></div>`;
}
// Whether this node reaches the internet (R82), said only when it does not:
// a toolchain, an image or a system image is a download, and each install
// here refuses with this before it starts.
function nodeInternet(n){
  if (n.kind !== "agent") return "";
  // A store mounted noexec: nothing in it runs, the bb bundle and every
  // terminal from it included, which closed at once with nothing saying why.
  const noexec = n.reported?.store_noexec === true
    ? `<div class="actbar ndnoexec"><span class="state bad">the toolchain store is mounted noexec: bb and every terminal here cannot run until it is remounted with exec</span></div>` : "";
  if (n.reported?.internet !== false) return noexec;
  return noexec + `<div class="actbar ndnet"><span class="state warn">no internet: toolchains, images and updates cannot download here</span></div>`;
}
// What this node's NVIDIA card is for (R102): two switches and one Apply.
// The emulator renders on it or does not, which is the headless X server
// the display needs; and sessions and jobs may compute on it or not, which
// decides whether a session started here finds CUDA a device. Neither is a
// way of moving work onto the card: a program uses it only if it was
// written to. Both wait for the driver, which is the Toolchains tab's row.
function nodeGpuSection(n){
  const card = n.reported?.gpu_card;
  if (!card || n.kind !== "agent") return "";
  const gd = n.reported?.gpu_driver;
  const st = n.reported?.gpu_display || "";
  const emuOn = /^(up|starting|reboot)/.test(st);
  const compOn = !n.config?.no_gpu_compute;
  const c = nodeDraft(n);
  if (c.draft.gpuEmu === undefined || c.draft.gpuEmuFrom !== emuOn){ c.draft.gpuEmu = emuOn; c.draft.gpuEmuFrom = emuOn; }
  if (c.draft.gpuComp === undefined || c.draft.gpuCompFrom !== compOn){ c.draft.gpuComp = compOn; c.draft.gpuCompFrom = compOn; }
  const nodriver = !!gd && !gd.installed;
  const pending = (n.jobs || []).find(j => j.apply === "gpu" || j.apply === "gpu-off");
  const busy = !!pending;
  // While the emulator's job runs the box shows where it is going, not
  // where the machine still is: it read as unticked under "Applying" until
  // the node's next report (the operator, 30 Sep).
  if (pending){ c.draft.gpuEmu = pending.apply === "gpu"; }
  const managed = !!n.reported?.sandbox;
  const name = n.reported?.gpu || (String(card).match(/\[([^\]]*(?:GeForce|RTX|Quadro|Tesla|TITAN)[^\]]*)\]/)?.[1]) || card;
  const [status, cls] = nodriver ? ["no driver", "warn"]
    : [[emuOn ? "emulator" : "", compOn ? "compute" : ""].filter(Boolean).join(" and ") || "not used", emuOn || compOn ? "ok" : ""];
  const emuLine = /^up/.test(st) ? `<div class="sub">An emulator started here renders on the card.</div>`
    : /^reboot/.test(st) ? `<div class="sub warn">It starts when the machine restarts: Reboot under Advanced.</div>`
    : /^down/.test(st) ? `<div class="sub bad">${esc(st.replace(/^down:\s*/, ""))}.</div>`
    : `<div class="sub dim">An emulator here renders in software.</div>`;
  const body = `
    <div class="sub">${esc(name)}${gd?.loaded ? ` on NVIDIA's driver ${esc(gd.loaded)}` : ""}.</div>
    ${nodriver ? `<div class="sub warn">No NVIDIA driver on this machine yet, so nothing can use the card.
        <button type="button" class="link" data-ndtc="${esc(n.id)}">Install the driver</button></div>` : ""}
    <label class="ndcap"><input type="checkbox" data-k="gpuemu" ${c.draft.gpuEmu ? "checked" : ""}${
      nodriver || !managed || busy ? " disabled" : ""}>
      render the Android emulator on the card</label>
    ${nodriver ? "" : emuLine}
    <label class="ndcap"><input type="checkbox" data-k="gpucomp" ${c.draft.gpuComp ? "checked" : ""}>
      let sessions and jobs compute on it (CUDA, the hardware video encoder)</label>
    ${compOn ? `<div class="sub dim">A project can turn this off for itself in its settings.</div>`
             : `<div class="sub dim">A session started here from now on finds no card to compute on.</div>`}
    <div class="actbar">
      <span class="state"></span>
      <button type="button" data-nd="gpu-apply"${busy ? " disabled" : ""}
        title="apply both: the emulator's switch is a job on the node, the other takes effect for sessions started from now on">${
        busy ? "Applying…" : "Apply"}</button>
    </div>`;
  return docSection("nodes", "gpu", ndTitle("gpu"), status, body, {cls});
}
function nodeGit(n){
  const v = String(n.reported?.git || "").trim();
  if (n.kind !== "agent" || !v) return "";
  const m = v.match(/(\d+)\.(\d+)/);
  const old = m && (+m[1] < GIT_FLOOR[0]
                    || (+m[1] === GIT_FLOOR[0] && +m[2] < GIT_FLOOR[1]));
  return old
    ? `<div class="sub ndgit warn">${esc(v)}: older than ${GIT_FLOOR.join(".")}, which merging needs; update it on the machine</div>`
    : `<div class="sub ndgit dim">${esc(v)}</div>`;
}

function nodeTools(n){
  const tc = n.reported?.toolchains || {};
  const names = Object.keys(tc);
  if (n.kind !== "agent") return "";
  if (!names.length)
    return `<div class="sub ndtools dim">no toolchains yet: install them from the ${pageLink("toolchains", "Toolchains page")}</div>`;
  // Held recipes whose system libraries this machine lacks (roadmap R51),
  // said here rather than left for a build to fail on: the store is shared,
  // the libraries are each machine's own, and the Tools tab installs them.
  const unmet = Object.entries(n.reported?.sysdeps?.unmet || {});
  const sys = unmet.length
    ? `<div class="sub ndsys warn">System packages missing for ${unmet.map(([r, ps]) =>
        `${esc(r)} (${esc(ps.join(" "))})`).join(", ")}: install them from the ${pageLink("toolchains", "Toolchains page")}</div>` : "";
  return `<div class="sub ndtools">${names.slice(0, 8).map(k =>
    `<span class="pill" title="${esc(String(tc[k] || "present"))}">${
      esc(TOOL_LABELS[k] || k)}</span>`).join(" ")}</div>${sys}`;
}

function nodeStatePill(n){
  if (n.state === "pending")
    return `<span class="pill note">waiting for enrollment</span>`;
  const cls = {online: "ok", draining: "warn", disabled: "warn"}[n.state] || "";
  const live = n.kind !== "agent" ? ""
    : n.live ? ` <span class="pill ok ndlive">live</span>`
    : ` <span class="pill ndlive">quiet</span>`;
  return `<span class="pill ${cls}">${esc(n.state)}</span>${live}`;
}
// The draft for a node: what is on the record, until the operator types.
function nodeDraft(n){
  const c = nodesConf[n.id] || (nodesConf[n.id] = {open: false, dirty: false, draft: null});
  if (!c.draft){
    const d = n.config?.desired || {};
    // A node set up at its own console has mounts and no desired config, and
    // drawing only the desired one showed an empty list for a machine with
    // three shares on it. So the editor opens on what the node REPORTS when
    // nothing has been recorded: the rows are the real ones, editable, and
    // Save is what puts this page in charge of them.
    const seed = (n.reported?.mounts || []).map(m => ({
      path: m.path, source: m.source, type: m.type || "nfs", ro: !!m.ro}));
    c.draft = {
      mounts: (d.mounts?.length ? d.mounts : seed).map(m => ({...m})),
      fromNode: !d.mounts?.length && seed.length > 0,
      stores: {...(d.stores || {})},
      network: {mode: "dhcp", address: "", gateway: "", dns: [], interface: "", routes: [], ...(d.network || {})},
    };
  }
  return c;
}

// What the row says beside a desired mount, from the agent's census: the
// reported half of desired-vs-reported, in words rather than a gray nothing.
function mountState(m, reported){
  const r = (reported || []).find(x => x.path === m.path);
  if (!r) return ["not applied yet", "warn"];
  const diff = r.source !== m.source || !!r.ro !== !!m.ro;
  if (!r.mounted) return [r.error
    ? `not mounted: ${r.error}${/access denied/i.test(r.error) ? ": the host's export rule names another address" : ""}`
    : `not mounted${r.source ? `: fstab has ${r.source}` : ""}`, "bad"];
  // Mounted and answering Stale file handle: the worst of the states, since
  // every list of mounts calls it fine and every read fails.
  if (r.stale) return [r.error || "mounted, but the handle is stale: re-export it on the host", "bad"];
  const from = r.real && r.real !== r.source ? `mounted from ${r.real} (fstab says ${r.source})`
                                             : `mounted${r.ro ? ", read-only" : ""}`;
  return [diff ? `${from}: applying will change it` : from, diff ? "warn" : ""];
}

// The Actions runner on this node (phase 7), as a section: what the census
// says is there, and the labels an install would register with: the node's
// own name among them, which is the label a workflow's runs-on uses to land
// here. Install and Remove are system jobs like the rest of the plane.
function nodeRunnerSection(n, c, between = ""){
  // One runner per git host on a node (R53): the record's asks and the
  // census's reports, joined by slot, each a row with its own state and
  // buttons; the addbar at the top takes a new one, host, address and
  // token, the way every view adds.
  const recs = n.services?.runners || {};
  const reps = n.reported?.services?.runners || [];
  // Runner by runner (R260): one this account may not read is left out, one
  // it may only read keeps its row with its buttons dead and why.
  const mayOn = slot => n.runner_may ? (n.runner_may[slot] ?? "write") : "write";
  const slots = [...new Set([...Object.keys(recs), ...reps.map(r => r.slot).filter(Boolean)])].filter(sl => mayOn(sl));
  const tokens = n.runner_tokens || [];
  const d = c.draft;
  if (d.runner === undefined) d.runner = {url: "", token: "", forge: "", labels: ""};
  const busyNow = n.applying || nodeStale(n);
  const why = nodeStale(n) ? esc(staleWhy(n)) : "";
  const when = t => fmtTime((t || 0) * 1000, {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  const hostOf = (want, rep) => (rep.forge || want.forge) === "gitea" ? "Gitea" : (rep.forge || want.forge) === "github" ? "GitHub" : "";
  let worst = "";
  const rows = slots.map(slot => {
    const want = recs[slot] || {}, rep = reps.find(r => r.slot === slot) || {};
    const stored = tokens.includes(slot);
    const ap = n.applying?.what === "runner" && (n.applying.slot || slot) === slot ? n.applying : null;
    const job = ap ? (want.want ? "installing" : "removing") : "";
    const failed = n.runner_failed && (n.runner_failed.slot || slot) === slot ? n.runner_failed : null;
    // Its state a pill on its name line, its facts one mono line, and what
    // is wrong or worth knowing a notice under it (R218 step 28, the voices
    // rule). "Installed" and "will actually pick up a job" are different
    // states: a runner registered with no listener reads as healthy right
    // up until a workflow sits in "Waiting for a runner".
    const [word, pcls, say, scls] = job
      ? [`${job} now`, "warn", "its job is on the Jobs page, and the buttons come back when it ends", "note"]
      : !rep.installed
      ? (failed ? ["install failed", "off", `install failed ${when(failed.ended)}: ${failed.why || "its job on the Jobs page says why"}`, "bad"]
        : want.want ? ["asked for", "warn", "install asked for; the node has not reported it yet", "note"] : ["not installed", "", "", ""])
      : rep.busy ? ["running a job", "ok", "", ""]
      : rep.active ? ["listening", "ok", "", ""]
      : ["not listening", "off", "installed but not listening, so no workflow will reach it: Reinstall runner", "bad"];
    const rowCls = failed && rep.installed && pcls === "ok" ? "warn" : scls === "bad" ? "bad" : scls;
    if (rowCls === "bad") worst = "bad"; else if (rowCls === "note" && worst !== "bad") worst = "note";
    const facts = rep.installed
      ? [rep.name ? `registered as ${rep.name}` : "", rep.labels?.length ? "labels " + rep.labels.join(", ") : ""].filter(Boolean).join(" · ") : "";
    // A token is what a reinstall and a removal mint from, so a runner
    // without one (registered before tokens were per runner) says so once,
    // with the way to add one, rather than as a warning on one that works.
    const notes = [
      say ? [say, scls] : null,
      rep.installed && !rep.name && !rep.active ? ["its registered name did not come back, so the registration may not have finished", "warn"] : null,
      // A reinstall that failed left the runner standing: its state stays,
      // and what went wrong follows it.
      failed && rep.installed ? [`reinstall failed ${when(failed.ended)}: ${failed.why || "its job on the Jobs page says why"}`, "bad"] : null,
      !stored ? [`no token stored: Add runner with this address stores one, to ${rep.installed ? "reinstall or remove it" : "install it"}`, "warn"] : null,
    ].filter(Boolean);
    const ro = mayOn(slot) !== "write";
    return `<div class="row stack2 ndrun${ro ? " ndrunro" : ""}" data-slot="${esc(slot)}"><div class="grow">
        <div class="name"><code>${esc(rep.url || want.url || slot)}</code>${hostOf(want, rep) ? ` <span class="pill">${hostOf(want, rep)}</span>` : ""}
          <span class="pill stat ndrunstate${pcls ? " " + pcls : ""}${rep.busy && !job ? " ndrunbusy" : ""}">${esc(word)}</span></div>
        ${facts ? `<div class="sub ndrunfacts">${esc(facts)}</div>` : ""}
        ${notes.map(([t, c]) => `<div class="sub ${c} ndrunnote">${esc(t)}</div>`).join("")}
        <div class="actbar">
          <span class="sp"></span>
          <button type="button" data-nrunner="install" data-slot="${esc(slot)}" ${busyNow || !stored ? "disabled" : ""}
            title="${why || (stored ? "install the runner here and register it with the stored token"
                                    : "add a token first")}">${
            rep.installed ? barSaid("Reinstall runner", "Reinstall") : barSaid("Install runner", "Install")}</button>
          ${stored ? `<button type="button" class="danger" data-nrunnerforget data-slot="${esc(slot)}" ${busyNow ? "disabled" : ""}
            title="drop the stored token and this row; a registered runner keeps running">${barSaid("Forget token", "Forget")}</button>` : ""}
          ${rep.installed || want.want ? `<button type="button" class="danger" data-nrunner="remove" data-slot="${esc(slot)}" ${busyNow || !stored ? "disabled" : ""}
            title="${why || (stored ? "deregister it and remove it from this node" : "add a token first")}">${barSaid("Remove runner", "Remove")}</button>` : ""}
        </div></div></div>`;
  }).join("");
  // Adding is a button that unrolls the form in its own band, the shape
  // every view adds with; the form is four fields that wrap to the width
  // they have, one per line on a phone, and its own action bar.
  const addbar = c.addRunner ? `<div class="addbar ndrunadd ctlrow" data-add="runner"><div class="grow">
        <div class="uadd ctlrow">
          <div class="setrow col ctlrow">${lbl("", "Repository or organization", "a repository, or an organization for all of its repositories")}
          <input data-k="runner:url" value="${esc(d.runner.url)}" spellcheck="false" autocomplete="off"
            placeholder="https://github.com/your-org" aria-label="repository or organization URL"></div>
          <div class="setrow col ctlrow">${lbl("", "Host", "GitHub, or act_runner for Gitea, Forgejo and Codeberg")}
          <select data-k="runner:forge" aria-label="host kind">${optionList([["", "from the address"], ["github", "GitHub"], ["gitea", "Gitea or Forgejo"]], d.runner.forge || "")}</select></div>
          <div class="setrow col ctlrow">${lbl("", "Token", "a token that may register runners there. Stored on the controller only")}
          <input data-k="runner:token" type="password" value="${esc(d.runner.token || "")}" spellcheck="false" autocomplete="off"
            placeholder="paste a token" aria-label="runner token"></div>
          <div class="setrow col ctlrow">${lbl("", "Extra labels", `comma-separated. builderbot, self-hosted, linux, the arch and ${n.name} are always on`)}
          <input data-k="runner:labels" value="${esc(d.runner.labels)}" spellcheck="false" autocomplete="off"
            placeholder="gpu, android" aria-label="labels"></div>
        </div>
        <div class="actbar"><span class="state">Install on the runner's row registers it</span>
          <button type="button" class="stop" data-nrunnercancel>Cancel</button>
          <button type="button" class="primary" data-nrunneradd ${busyNow ? "disabled" : ""}
            title="save the token and add the runner to this node">Add runner</button></div>
      </div></div>`
    : "";
  const status = !slots.length ? "none" : worst === "bad" ? "attention" : worst === "note" ? "working"
    : reps.some(r => r.busy) ? "busy" : reps.some(r => r.active) ? "listening" : "asked for";
  const pill = {attention: "bad", working: "note", busy: "ok", listening: "ok"}[status] || "";
  // The node-scoped tool's shape, the Phone tab's too (R121 step 5): the
  // state row first, the things below it, the add band, and at the foot
  // what a workflow (or a session) does to reach this node.
  // `between` is what the CI runner page puts under the state line: every
  // node's runner at a glance (runnerRows). This node's runners are a list
  // of their own, a card on that page (the operator, 18 Oct: it read as
  // loose rows under lines that ran to the edge).
  return `${headLine(`<span class="pill ${pill}">${esc(status)}</span> One runner per git host; its labels decide which workflows land here.`,
        "", "toolstate")}${between}
      ${addbar ? `<div class="field">${addbar}</div>` : ""}
      <div class="ndruns">${rows || `<div class="row"><div class="grow"><div class="sub dim ndrunnone">no runner on this node</div></div></div>`}</div>
      ${slots.length ? `<div class="field toolfoot ndrunpin"><div class="hint">This node's name pins a job here:
        <pre class="ndcmd">runs-on: [self-hosted, ${esc(n.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 40))}]</pre></div></div>` : ""}`;
}

// The node's sessions (roadmap #24): whether this machine runs them, what a
// session there gets, and which are open right now. The reasons a project
// cannot be sent here are the proxy's (server.session_target), repeated in
// the same words so the row and the refusal agree.
// A node holds its projects as a copy kept in step through the controller
// (R162), the one way it holds them (R163): each project's state, and the
// presses that take it off its copy and back (R164).
function nodeSyncRow(n){
  if (n.kind !== "agent") return "";
  const rows = Object.entries(n.reported?.sync || {});
  const one = ([p, v]) => `<code>${esc(p)}</code> ${v.error ? `<span class="bad">${esc(v.error)}</span>`
    : !v.ready ? `copying${v.copying ? ` (${v.copying} to go)` : ""}`
    : v.pending ? `${v.pending} change${v.pending === 1 ? "" : "s"} going up` : "in step"}`;
  const conf = n.config || {}, live = n.live ? "" : "disabled";
  // Off its synced copy (R164): no projects and no sessions here, the
  // copies removed or on their way out, and one press back.
  if ((conf.workspace || "sync") !== "sync"){
    const c = n.reported?.sync_clean || {};
    const done = conf.clean && c.token === conf.clean;
    return `<div class="sub">This node holds no projects, so no session starts here${
      !conf.clean ? "." : !done ? "; its copies are being removed." : c.error
        ? `; its copies could not all be removed: <span class="bad">${esc(c.error)}</span>`
        : `; its copies were removed, ${esc(gb(Math.round((c.freed || 0) / 1048576)))} freed.`}</div>
    <div><button type="button" data-nd="to-sync" ${live} ${conf.clean && !done ? "disabled" : ""}>Move to a synced copy</button></div>`;
  }
  // Leaving it: sessions held while what is left goes up, then Clean up.
  if (conf.leaving){
    const d = n.reported?.sync_drain;
    const left = d ? [d.files ? `${d.files} file change${d.files === 1 ? "" : "s"}` : "",
                      d.claude ? `${d.claude} conversation file${d.claude === 1 ? "" : "s"}` : ""].filter(Boolean) : [];
    const drained = d && d.walked && !left.length;
    return `<div class="sub">Leaving its synced copy: no session starts here, and ${
      !d ? "the node has not said yet what is left to send up"
      : left.length ? `${left.join(" and ")} still to go up to the controller`
      : !d.walked ? "the node is looking at every file once more" : "everything here has reached the controller"}.</div>
    <div><button type="button" data-nd="sync-clean" ${live} ${drained ? "" : "disabled"}>Clean up /workspace</button>
      <button type="button" data-nd="sync-resume" ${live}>Keep syncing</button></div>`;
  }
  return `<div class="sub">Projects here are a copy kept in step through the controller${
    rows.length ? `: ${rows.map(one).join(", ")}` : "; none is bound to this node yet"}.</div>
    <div><button type="button" data-nd="sync-stop" ${live}>Stop syncing</button></div>`;
}

// Hosting only (the operator, 10 Oct): a node that runs containers sent to
// it and nothing else, so nothing of it comes back to the controller. Said in
// the Sessions section, since what it takes away is sessions and code.
// The door in for SSH (R174): what the machine reports, or what the enroll
// script set up while it has not reported yet; the switch is a system job,
// and the line says the ssh command to use.
// What a PC needs to come in through a cloudflared door (R179, the
// operator's own way in to a hosting node, 11 Oct): an ~/.ssh/config block named
// for the node, so every server keeps its own name and its own saved
// password rather than all of them being localhost:22, and `ssh NAME`.
// MobaXterm's own SSH sessions read no ssh config, so it is said how it
// gets there: a session that runs `ssh NAME` in its local terminal.
function nodeDoorConfig(n, d){
  const host = d.host || "HOST", user = n.config?.user || "bb";
  const alias = String(n.name || "node").toLowerCase().replace(/[^a-z0-9._-]+/g, "-");
  return `<pre class="ndcmd"># in ~/.ssh/config on your PC, with cloudflared installed there
Host ${esc(alias)}
  HostName ${esc(host)}
  User ${esc(user)}
  ProxyCommand cloudflared access ssh --hostname %h</pre>
      <div class="sub">Then <code>ssh ${esc(alias)}</code>. In MobaXterm, whose own SSH sessions read no ssh config, make a Shell session that runs <code>ssh ${esc(alias)}</code>, or type it in its local terminal.</div>`;
}

// What the node has beyond the base (R91): each feature bb-sandbox installs
// and removes, with Install or Uninstall on its row, the same install the
// enroll script's tick ran. A row that cannot be pressed says why under it,
// muted; the firewall is a hosting-only node's alone.
function nodeFeaturesSection(n){
  if (n.kind !== "agent") return "";
  const fe = n.reported?.features;
  const job = n.applying?.what === "feature" ? n.applying : null;
  const failed = n.last_apply?.what === "feature" && n.last_apply.state === "failed" ? n.last_apply : null;
  // A job that succeeded and a census that does not show it yet (B162): the
  // machine has changed and has not said so, so its row waits for the report
  // the agent sends after every feature job rather than offering the press
  // that was just made. Read off what the census says, not off the clock:
  // the two land in the same second often enough that time cannot tell.
  const la = n.last_apply;
  const ahead = la?.what === "feature" && la.state === "succeeded" && fe?.[la.feature]
    && !!fe[la.feature].installed !== (la.op !== "remove")
    // ...for a few minutes at most: past that the machine has been changed
    // since by something else, and the row says what it reports.
    && Date.now() / 1000 - (la.ended || 0) < 300 ? la.feature : "";
  const why = !n.reported ? ""
    : !n.reported.administers ? "This node's agent is not root on a managed machine, so its features are set on the machine itself."
    : !n.live ? "Its agent is not dialing in, so nothing from here reaches the machine." : "";
  const row = (fid, title, has, about, cant, more = "") => {
    const mine = job?.feature === fid;
    const btn = ahead === fid ? `<button type="button" disabled>Done, the node is reporting back…</button>`
      : why || cant || (job && !mine) ? ""
      : `<button type="button" data-nd="feature" data-feature="${fid}" data-op="${has ? "remove" : "install"}"${mine ? " disabled" : ""}>${
          mine ? (job.op === "remove" ? "Uninstalling…" : "Installing…") : has ? "Uninstall" : "Install"}</button>`;
    const fail = failed?.feature === fid ? `<div class="sub bad">The last try failed${failed.error ? `: ${esc(failed.error)}` : ""}; its job's log says more.</div>` : "";
    return `<div class="row ndfeat" data-feat="${fid}"><div class="grow">
        <div class="name">${esc(title)} <span class="pill${has ? " ok" : ""}">${has ? "installed" : "not installed"}</span></div>
        <div class="sub">${about}</div>${cant ? `<div class="sub dim">${cant}</div>` : ""}${fail}${more}</div>${btn}</div>`;
  };
  const vm = fe?.vmhost || {};
  const rows = [row("vmhost", "VM host", !!vm.installed,
      `Runs virtual machines here with KVM through libvirt${vm.libvirt ? ` (libvirt ${esc(vm.libvirt)})` : ""}, as the jobs account and never a session.`,
      fe && !vm.kvm && !vm.installed ? "No /dev/kvm here, so a VM would run in software. On a VM, its host passes virtualization through: CPU mode host-passthrough and nested KVM on." : "",
      // Where its VMs may go (R91 step 8): the internet, the controller and
      // their own project's network, and the LAN only when ticked, inside
      // the row it is about.
      (vm.installed ? `<label class="ndcap ndvmlan"><input type="checkbox" data-ndvmlan${n.config?.vm_lan ? " checked" : ""}${why ? " disabled" : ""}>
        its VMs may reach this machine's LAN too</label>` : "")
      // A shared folder needs virtiofsd, which an install from before it did
      // not bring; installing again adds what is missing and keeps the rest.
      + (vm.installed && vm.virtiofs === false ? `<div class="sub">A VM's shared folder needs virtiofsd and VM host's wrapper for it, which are not all here yet.
        ${why || job ? "" : `<button type="button" data-nd="feature" data-feature="vmhost" data-op="install">Bring in shared folders</button>`}</div>` : ""))];
  if (n.config?.host_only)
    rows.push(row("firewall", "Hosting firewall", !!fe?.firewall?.installed,
      "Takes in only 80 and 443, a port a container publishes included; port 22 as the SSH door leaves it.", ""));
  // The features installed elsewhere on the page (R91 step 1): each said as
  // the machine reports it, with the press that installs or removes it where
  // it already lives, since those take a license to accept (Google's, NVIDIA's)
  // or a secret (a door's token, a forge's) that is the person's to give.
  const r = n.reported || {};
  // Its presses only for an account that may change the node: one that may
  // read it sees what is installed and no way onto a page it is not given.
  const writes = nodeMay(n) === "write";
  const elsewhere = (fid, title, has, about, btn) => `<div class="row ndfeat" data-feat="${fid}"><div class="grow">
      <div class="name">${esc(title)} <span class="pill${has ? " ok" : ""}">${has ? "installed" : "not installed"}</span></div>
      <div class="sub">${about}</div></div>${writes ? btn : ""}</div>`;
  const others = [];
  if (!n.config?.host_only)
    others.push(elsewhere("sessions", "Claude sessions", !!r.session?.user,
      r.session?.user ? `Sessions run here as ${esc(r.session.user)}, kept off Docker and root.` : "No session account on this machine: enrolling it again with Claude sessions ticked makes one.",
      `<button type="button" data-nd="reenroll" title="a new script for this machine, with the ticks changed">Enroll again…</button>`));
  others.push(elsewhere("door", "SSH door", !!r.door?.installed,
    r.door?.installed ? `${esc(r.door.kind)}, opened and shut under Sessions.` : "A way in for ssh through a tunnel; its token is given in the enroll script.",
    `<button type="button" data-nd="reenroll" title="a new script for this machine, with the door's token in it">Enroll again…</button>`));
  if (r.gpu_card)
    others.push(elsewhere("gpu", "GPU driver", !!r.gpu_driver?.installed, "NVIDIA's driver, installed and removed from its row on the Toolchains page, where its license is accepted.",
      `<button type="button" data-ndtc="${esc(n.id)}">Toolchains</button>`));
  const emu = (r.store_dirs?.android || []).includes("emulator");
  others.push(elsewhere("emulator", "Android emulator", emu, "The emulator and its system images, from the Toolchains page, where Google's SDK license is accepted.",
    `<button type="button" data-ndtc="${esc(n.id)}">Toolchains</button>`));
  const runs = ((r.services || {}).runners || []).length;
  others.push(elsewhere("runner", "CI runner", runs > 0, runs ? `${runs} runner${runs === 1 ? "" : "s"} registered here.` : "A forge's runner, registered with a token from the forge on the CI runner page.",
    `<button type="button" data-ndrunner="${esc(n.id)}">CI runner</button>`));
  rows.push(...others);
  const have = fe ? [fe.vmhost?.installed, n.config?.host_only && fe.firewall?.installed].filter(Boolean).length
    + others.filter(h => / ok">installed/.test(h)).length : 0;
  return docSection("nodes", "features", ndTitle("features"), fe ? (have ? `${have} installed` : "none installed") : "",
    `${why ? `<div class="sub dim ndfeatwhy">${why}</div>` : ""}${rows.join("")}`);
}

// How the node reaches the controller, chosen in Enroll node and kept on
// its record (the operator, 13 Oct: what is the node's reads on its row;
// the controller's own tunnel stays in Settings). Read-only: changing it
// is enrolling again.
function nodeDoorRow(n){
  if (n.kind !== "agent") return "";
  const d = n.reported?.door || n.config?.door;
  if (!d?.kind) return "";
  const known = !!n.reported?.door;
  const cmd = d.kind === "cloudflared"
    ? `ssh -o ProxyCommand="cloudflared access ssh --hostname ${esc(d.host || "HOST")}" ${esc(n.config?.user || "bb")}@${esc(d.host || "HOST")}`
    : `ssh ${esc(n.config?.user || "bb")}@${esc(d.host || n.name)}`;
  // The machine's own way in, for a person with a shell on it, whatever
  // projects it hosts: one hostname, picked when it was enrolled, not a
  // project's (the operator, 18 Oct, asked whether each project needed one).
  return `<div class="field nddoor">
      <div class="sub">The SSH door lets you into this machine itself, as <code>${esc(n.config?.user || "bb")}</code>; ${
        d.kind === "cloudflared" ? "Cloudflare Access decides who reaches it" : "the tailnet's ACLs decide who reaches it"}. The projects it hosts need none of their own.</div>
      ${known && d.installed ? `<div class="actbar"><span class="sp"></span><button type="button" data-nd="door" data-on="${d.active ? "0" : "1"}" ${n.live ? "" : "disabled"}>${d.active ? "Shut the door" : "Open the door"}</button></div>` : ""}
      ${known && d.installed && d.active ? (d.kind === "cloudflared" ? nodeDoorConfig(n, d) : `<pre class="ndcmd">${cmd}</pre>`) : ""}
    </div>`;
}

function nodeHostRow(n){
  if (n.kind !== "agent") return "";
  return n.config?.host_only
    ? `<div class="sub">It hosts containers only: no project lists it, no session or synced copy runs here,
        and its agent may ask the controller for nothing but its own jobs, an image shipped to it
        and a container's data in a copy or a move.</div>
       ${n.config?.tunnel?.kind === "public"
         ? `<div class="sub dim ndhostfixed">It reaches the controller through a public hostname, so it stays hosting only.</div>`
         : `<div><button type="button" data-nd="host-off">Let projects use it again</button></div>`}`
    : `<div class="sub dim">A node that only runs containers sent to it (a web-facing one) can be made
        hosting only: no code, no sessions, and nothing of it comes back but its own jobs.</div>
       <div><button type="button" data-nd="host-only" ${n.live ? "" : "disabled"}>Make it hosting only</button></div>`;
}

// Un-enroll (the operator, 11 Oct): the one way off. Where the machine can
// be cleaned (its agent dialing in, provisioned by BuilderBot) the dialog
// says what always goes (the agent, the session isolation, the accounts)
// and offers three rings to tick: the stores on its disk, what was
// configured from the dashboard after enrolling, and a hosting node's
// doors and proxy, ticked for one. Anywhere else the node is removed here
// only, and the dialog says BuilderBot's pieces stay on the machine.
// What un-enrolling takes off a machine and what it leaves, said the same
// way in a node's Un-enroll and in Reset BuilderBot (the operator, 12 Oct).
// `all`: everything goes (Reset un-enrolls with every part); otherwise the
// parts the dialog's boxes choose are said as such.
function unenrollWhat(all){
  return `<div class="resetwhat">
      <b>What un-enrolling takes off a machine BuilderBot set up</b>
      <ul>
        <li>The agent and its service, and the tunnel to this controller.</li>
        <li>The sessions' firewall rules and networks, and the job and session accounts with their homes.</li>
        <li>${all ? "" : "If ticked below: "}what was set up from the dashboard after enrolling: the mounts and their fstab lines, the CI runners, the GPU display.</li>
        <li>${all ? "" : "If ticked below: "}what it was given as a host: the SSH door with its token, the port 22 rule, and the nginx container.</li>
      </ul>
      <b>What stays</b>
      <ul>
        <li>Docker, the system packages, and what is on the shares.</li>
        <li>Its stores on its own disk (toolchains, caches, artifacts), unless that box is ticked.</li>
        <li>Anything the provisioner installed for the machine itself.</li>
      </ul>
      The node leaves the Nodes page and its tokens stop working; to use the machine again, enroll it again.
      A machine that is only removed here keeps BuilderBot's pieces until <code>sudo bb-sandbox uninstall</code> is run on it.
    </div>`;
}

function openUnenroll(n){
  const modal = document.getElementById("ndmodal"), body = document.getElementById("ndBody");
  if (!modal || !body) return;
  const clean = !!(n.live && n.reported?.sandbox);
  const host = !!n.config?.host_only;
  document.getElementById("ndTitle").textContent = `Un-enroll ${n.name}?`;
  body.innerHTML = clean ? `<div class="field">
      <div class="hint">Are you sure? BuilderBot is uninstalled from ${esc(n.name)}, then the node is removed here. Its job account is <code>${esc(n.config?.user || "bb")}</code>.</div>
      ${unenrollWhat(false)}
      <label class="ndcap"><input type="checkbox" id="ndUnStores"> Also delete the stores on its disk: the toolchains, the caches, the artifacts, dev instance data, and the synced project copies</label>
      <label class="ndcap"><input type="checkbox" id="ndUnConf"> Also undo what was set up from the dashboard after enrolling: the mounts and their fstab lines, the runners, the GPU display</label>
      <label class="ndcap"><input type="checkbox" id="ndUnDoors"${host ? " checked" : ""}> Also shut what it was given as a host: the SSH door with its token, the port 22 rule, and the nginx container</label>
    </div>
    ${dlgFoot(`<button type="button" id="ndUnCancel">Cancel</button>`, `<button type="button" class="danger" id="ndUnGo">Un-enroll</button>`)}`
  : `<div class="field">
      <div class="hint bad">Are you sure? The machine cannot be cleaned from here: ${n.live ? "it was not provisioned by BuilderBot" : "its agent is not dialing in"}. The node is removed here and its tokens revoked; BuilderBot's pieces stay on the machine until <code>sudo bb-sandbox uninstall</code> is run there.</div>
    </div>
    ${dlgFoot(`<button type="button" id="ndUnCancel">Cancel</button>`, `<button type="button" class="danger" id="ndUnGo">Remove it here</button>`)}`;
  modal.hidden = false;
  const shut = () => { modal.hidden = true; };
  body.querySelector("#ndUnCancel").onclick = shut;
  const go = body.querySelector("#ndUnGo");
  go.onclick = async () => {
    busy(go, "Un-enrolling");
    const j = await nodeAct(clean
      ? {action: "uninstall", id: n.id, stores: !!body.querySelector("#ndUnStores")?.checked,
         configured: !!body.querySelector("#ndUnConf")?.checked, doors: !!body.querySelector("#ndUnDoors")?.checked}
      : {action: "retire", id: n.id});
    if (j.error){ notify(j.error, true); unbusy(go, clean ? "Un-enroll" : "Remove it here"); return; }
    shut();
    notify(clean ? `${n.name}: uninstalling; the row goes when the machine reports it done` : `${n.name} removed here`);
    await loadNodes();
  };
}

// The projects that have this node among theirs (the operator, 10 Oct): read
// off the projects this account is shown, primary first in each, with Remove
// on the ones the account is on. Remove is the project's settings saved
// without the node, so the same gates hold (the node grant, a read-only
// project) and the server names the refusal; a project the account is not on
// says so rather than offering it, the accident guard the pickers keep too.
function nodeProjects(id){
  return (state?.projects || []).filter(p => (p.prefs?.nodes || []).includes(id) || p.prefs?.node === id)
    .sort((a, b) => projLabel(a.name).localeCompare(projLabel(b.name), undefined, {sensitivity: "base"}));
}
function nodeProjectsSection(n){
  const list = nodeProjects(n.id);
  const rows = list.map(p => {
    const set = p.prefs?.nodes || [];
    const primary = p.prefs?.node === n.id;
    const rest = set.filter(x => x !== n.id);
    const then = !rest.length ? "it is then on no node, so nothing builds or runs a session until one is picked"
      : primary ? `${esc((nodesList || []).find(x => x.id === rest[0])?.name || rest[0])} becomes its primary` : "";
    return `<div class="row ndproj">
      <div class="grow"><div class="name">${esc(projLabel(p.name))}${primary ? ` <span class="dim">· primary</span>` : ""}</div>
        ${p.mine ? (then ? `<div class="sub dim">Removing it: ${then}.</div>` : "")
          : `<div class="sub dim">Not one of your projects: add yourself to it to change its nodes.</div>`}</div>
      ${p.mine ? `<button type="button" data-ndproj="${esc(p.name)}">Remove</button>` : ""}
    </div>`;
  }).join("");
  const body = rows || `<div class="empty">No project you can see has this node. A project's settings add one.</div>`;
  return docSection("nodes", "projects", ndTitle("projects"), list.length ? `${list.length}` : "none", body);
}

function nodeSessionsSection(n){
  const se = n.reported?.session;
  const list = n.reported?.sessions || [];
  const host = !!n.config?.host_only;
  const iso = n.reported?.isolation;
  // What this node is, said as facts (the operator, 18 Oct: the section was
  // a heap of lines from one install, a Save under every switch): who runs
  // the sessions, with what, how far each sees, how the node reaches the
  // controller, and its SSH door, the machine's own way in.
  const t = n.config?.tunnel;
  const reach = n.kind !== "agent" ? "" : !t ? "over the LAN" : t.kind === "wireguard" ? `over WireGuard, as ${t.addr || "its tunnel address"}`
    : `through ${t.host || "the public hostname"}, the controller's tunnel`;
  const d = n.kind === "agent" ? (n.reported?.door || n.config?.door) : null;
  const door = !d?.kind ? "none" : `${d.kind}${d.host ? ` at ${d.host}` : ""}, ${!n.reported?.door ? "not reported yet" : !d.installed ? "not installed" : d.active ? "open" : "shut"}`;
  const ready = !host && se && typeof se === "object" && se.up;
  const facts = factGrid([
    ["Sessions", host ? "none: it hosts containers only" : ready ? `run as ${se.user || "?"}` : ""],
    ["Claude Code", ready ? (se.claude || "not installed yet") : ""],
    ["Each session", ready && iso ? (iso.sessions ? "sees only its own project" : "can read other projects") : ""],
    ["Open now", ready && list.length ? list.map(x => x.name).join(", ") : ""],
    ["Reaches the controller", reach],
    ["SSH door", door],
  ], "ndsessfacts");
  let status, cls;
  const notes = [];
  if (host){
    [status, cls] = ["hosting only", "ok"];
  } else if (!se || typeof se !== "object"){
    [status, cls] = ["not reported", "warn"];
    notes.push(["The node has not said yet whether it runs sessions.", "warn"]);
  } else if (!se.up){
    [status, cls] = ["none", "warn"];
    notes.push([`${se.why || "no session account: provision it with --session-user"}. No Claude session can start here until it is up.`, "warn"]);
  } else {
    const shared = !!iso && !iso.sessions;
    if (!se.boot) notes.push(["the agent could not read this machine's boot id, which a terminal here is checked against", "bad"]);
    if (shared) notes.push([`Sessions here can read each other's projects: ${iso.why || "this machine cannot build a session's view"}.`, "warn"]);
    [status, cls] = !se.boot ? ["blocked", "bad"]
      : [`${list.length ? `${list.length} open` : "ready"}${shared ? ", not isolated" : ""}`, shared ? "warn" : "ok"];
  }
  const body = `<div class="field">${facts}${notes.map(([x, c]) => `<div class="sub ${c}">${esc(x)}</div>`).join("")}</div>
    ${nodeSessSettings(n)}
    <div class="ndactions">
      ${nodeDoorRow(n)}
      ${nodeHostRow(n)}
      ${host ? "" : nodeSyncRow(n)}
      ${nodeToolsLine(n)}
    </div>`;
  return docSection("nodes", "sessions", ndTitle("sessions"), status, body, {cls});
}

// The section's settings, one group with one Save and Revert at its foot
// (the operator, 18 Oct): every switch and number here is a draft until
// Save, which sends what changed and nothing else.
function nodeSessSettings(n){
  const host = !!n.config?.host_only;
  const rows = host ? nodeHostRootRow(n) + nodeContainerNetRow(n) + nodePortsLocalRow(n)
    : nodeSessNetRow(n) + nodeContainerNetRow(n) + nodePortsLocalRow(n) + nodeTurnsRow(n);
  const t = n.turns || {};
  const now = host ? "" : `${t.working || 0} working now${t.limit ? ` of ${t.limit}` : ""}${t.waiting ? `, ${t.waiting} waiting for a turn` : ""}`;
  const dirty = nodeSessDirty(n);
  return `<div class="ndsettings">${rows}
    <div class="actbar sectbar"><span class="state${t.waiting ? " warn" : ""}">${esc(now)}</span><span class="sp"></span>
      <button type="button" data-nd="sess-save"${dirty ? "" : " disabled"}>Save</button>
      <button type="button" data-nd="sess-revert"${dirty ? "" : " disabled"}>Revert</button></div>
  </div>`;
}
// Whether a draft in the section differs from what the node has.
function nodeSessDirty(n){
  const c = nodeDraft(n).draft || {};
  const conf = n.config || {};
  const ctrOn = "container_net" in conf ? !!conf.container_net : !!conf.host_only;
  const portsOn = "ports_local" in conf ? !!conf.ports_local : !!conf.host_only;
  return (c.sessnetOn !== undefined && c.sessnetOn !== !!conf.session_net)
    || (c.rootAsks !== undefined && c.rootAsks !== !conf.no_root)
    || (c.ctrNet !== undefined && c.ctrNet !== ctrOn)
    || (c.portsLocal !== undefined && c.portsLocal !== portsOn)
    || (c.turnsText !== undefined && String(Number(c.turnsText) || 0) !== String((n.turns || {}).limit || 0))
    || (c.workersText !== undefined && String(Number(c.workersText) || 0) !== String(conf.test_workers || 0));
}

// The coding agents on this node, in one line (R95 step 15): which are
// installed, and which of them this account is signed in to here, with the
// way to the Agents page, where each is installed, updated and signed in to.
function nodeAgentsSection(n){
  const cc = state?.claude_code || {};
  const me = cc.nodes?.[n.id] || {};
  const se = n.reported?.session;
  const up = !!(se && typeof se === "object" && se.up);
  // What the census says each agent's version is here, by the table's key.
  const have = AGENTS.filter(a => a.id === "claude" ? !!me.installed : !!se?.[a.id]);
  const signed = have.filter(a => a.id === "claude" && claudeOn(n.id));
  let status, cls;
  if (!up) [status, cls] = ["no session account", "warn"];
  else if (me.updating) [status, cls] = ["updating", "warn"];
  else if (!have.length) [status, cls] = ["none installed", "bad"];
  else if (!signed.length) [status, cls] = ["not signed in", "warn"];
  else [status, cls] = [`signed in to ${signed.map(a => a.name).join(", ")}`, "ok"];
  const said = !up ? "No session account here, so no coding agent runs."
    : !have.length ? "No coding agent is installed here: a session cannot start until one is."
    : `${have.map(a => a.name).join(", ")} installed; ${signed.length ? `you are signed in to ${signed.map(a => a.name).join(", ")}` : "you are signed in to none of them"} here.`;
  const body = `
    <div class="actbar">
      <span class="state">${esc(said)}</span>
      ${up && railAllows("agents") ? `<button type="button" data-ndag="${esc(n.id)}" title="install, update and sign in to each on the Agents page">Agents</button>` : ""}
    </div>`;
  return docSection("nodes", "agents", ndTitle("agents"), status, body, {cls});
}

// Whether each session here reaches only its own project's containers, the
// controller and the internet (R79): the node's setting, and what its agent
// says about it underneath, a reason in red when it is on and not in force.
// Root asks on a hosting-only node (the operator, 11 Oct): no session runs
// here, but a session of a project that hosts its containers here may ask
// for a root command by name (bb root run --node NAME), and this switch
// decides, as the Sessions section's does on a node that runs them. A
// draft until its Save, like that one.
function nodeHostRootRow(n){
  const c = nodeDraft(n);
  const rootOn = !n.config?.no_root;
  if (c.draft.rootAsks === undefined || c.draft.rootFrom !== rootOn){
    c.draft.rootAsks = rootOn; c.draft.rootFrom = rootOn;
  }
  return `<div class="field">
    <label class="ndcap"><input type="checkbox" data-k="rootasks" ${c.draft.rootAsks ? "checked" : ""}>
      let a session of a project that hosts containers here ask for a root command (bb root run --node ${esc(n.name)}), which a person then allows or denies</label>
    ${rootOn ? "" : `<div class="sub dim">A session that asks is refused and told this is off.</div>`}
  </div>`;
}

// Each project's containers kept to their own network on this node (R178,
// the operator, 11 Oct): a container reaches its own project's containers,
// those of the projects it reads, the controller, DNS, the node's 80 and
// 443 and the internet, and nothing else on the node. On by default for a
// hosting-only node, which is the one two web-facing projects share. A
// draft until its Save, like the switches beside it.
function nodeContainerNetRow(n){
  const c = nodeDraft(n);
  const on = "container_net" in (n.config || {}) ? !!n.config.container_net : !!n.config?.host_only;
  if (c.draft.ctrNet === undefined || c.draft.ctrFrom !== on){
    c.draft.ctrNet = on; c.draft.ctrFrom = on;
  }
  const ct = n.reported?.session_net?.ctr;
  const line = !on ? ""
    : !ct ? `<div class="sub dim">The node has not reported it yet.</div>`
    : !ct.can ? `<div class="sub bad">Not in force: ${esc(ct.why || "this node cannot do it")}.</div>`
    : ct.error ? `<div class="sub bad">Not in force: ${esc(ct.error)}.</div>`
    : ct.active ? `<div class="sub">In force on ${ct.bridges} compose network${ct.bridges === 1 ? "" : "s"}: a container reaches its own project's containers, the ones its project reads, and the internet; not another project's by this node's address.</div>`
    : `<div class="sub dim">Setting it up.</div>`;
  return `<div class="field">
    <label class="ndcap"><input type="checkbox" data-k="ctrnet" ${c.draft.ctrNet ? "checked" : ""}>
      keep each project's containers to their own network (a container reaches another project's only where its project reads it)</label>
    ${line}
  </div>`;
}

// Published ports bound to 127.0.0.1 by default (R190): on for a hosting-only
// node unless switched off, since there a port on every address is open to
// the world and not only to its nginx. The census says what docker binds to.
function nodePortsLocalRow(n){
  const c = nodeDraft(n);
  const on = "ports_local" in (n.config || {}) ? !!n.config.ports_local : !!n.config?.host_only;
  if (c.draft.portsLocal === undefined || c.draft.portsFrom !== on){
    c.draft.portsLocal = on; c.draft.portsFrom = on;
  }
  const ip = n.reported?.docker_ip;
  const line = ip === undefined ? `<div class="sub dim">The node has not reported what docker binds published ports to yet.</div>`
    : on && ip === "127.0.0.1" ? `<div class="sub">In force: a published port binds to 127.0.0.1 unless its compose names an address, so only this node's nginx and its tunnel reach it.</div>`
    : on ? `<div class="sub dim">Setting it up: the agent writes docker's daemon.json and restarts docker once.</div>`
    : ip === "127.0.0.1" ? `<div class="sub dim">Off, and docker still binds to 127.0.0.1 until the agent puts it back.</div>`
    : `<div class="sub">Off: a published port binds to every address of this node, the internet's included where the node is on it.</div>`;
  return `<div class="field">
    <label class="ndcap"><input type="checkbox" data-k="portslocal" ${c.draft.portsLocal ? "checked" : ""}>
      published ports stay on this node (bound to 127.0.0.1; a compose naming 0.0.0.0:PORT publishes it anyway)</label>
    ${line}
  </div>`;
}

function nodeSessNetRow(n){
  const on = !!n.config?.session_net;
  // A draft until the section's Save is pressed (the rule apply-not-onchange,
  // the operator, 24 Sep): the tick is kept across the repaints a heartbeat
  // brings, and the press is where it is made.
  const c = nodeDraft(n);
  if (c.draft.sessnetOn === undefined || c.draft.sessnetFrom !== on){
    c.draft.sessnetOn = on; c.draft.sessnetFrom = on;
  }
  // ...and whether a session here may ask for a root command at all (the
  // operator, 24 Sep): the same draft, the same Save.
  const rootOn = !n.config?.no_root;
  if (c.draft.rootAsks === undefined || c.draft.rootFrom !== rootOn){
    c.draft.rootAsks = rootOn; c.draft.rootFrom = rootOn;
  }
  const sn = n.reported?.session_net || {};
  const told = Object.keys(sn).length > 0;
  const line = !told
      ? (on ? `<div class="sub dim">The node has not reported it yet.</div>` : "")
    : on && !sn.can ? `<div class="sub bad">Not in force: ${esc(sn.why || "this node cannot do it")}.</div>`
    : on && sn.error ? `<div class="sub bad">Not in force, so no session starts here until it is: ${esc(sn.error)}.</div>`
    : on && sn.active ? `<div class="sub">Sessions started here reach the internet, the controller and their own project's containers at this node's address, and nothing else.</div>`
    : on ? `<div class="sub dim">Setting it up.</div>`
    : sn.sessions ? `<div class="sub dim">${sn.sessions} session${sn.sessions === 1 ? "" : "s"} started while it was on keep their own network until they end.</div>`
    : "";
  return `<div class="field"><label class="ndcap"><input type="checkbox" data-k="sessnet" ${c.draft.sessnetOn ? "checked" : ""}>
      keep each session to its own project's network</label>
    ${line}</div>
    <div class="field"><label class="ndcap"><input type="checkbox" data-k="rootasks" ${c.draft.rootAsks ? "checked" : ""}>
      let a session ask for a root command (bb root run), which a person then allows or denies</label>
    ${rootOn ? "" : `<div class="sub dim">A session that asks is refused and told this is off.</div>`}</div>`;
}

// How many Claude sessions here may work on a prompt at once (turns.py on
// the controller). What is working and waiting now is on the status line,
// so the number is set against what the machine is actually doing. The
// typed value is a draft, kept across the repaints a poll brings. Its Save
// is the Sessions section's one, and saves the switch above it too.
function nodeTurnsRow(n){
  const t = n.turns || {};
  const have = String(t.limit || 0);
  const c = nodeDraft(n);
  if (c.draft.turnsText === undefined || c.draft.turnsFrom !== have){
    c.draft.turnsText = have; c.draft.turnsFrom = have;
  }
  const inp = `ndTurns-${n.id}`;
  // ...and how many workers a test run here may use (R81): the node's
  // cores when 0, handed to every test job as BB_TEST_WORKERS.
  const tw = String(n.config?.test_workers || 0);
  if (c.draft.workersText === undefined || c.draft.workersFrom !== tw){
    c.draft.workersText = tw; c.draft.workersFrom = tw;
  }
  const winp = `ndWorkers-${n.id}`;
  // What 0 means is in each label, where a phone reads it (B459).
  return `<div class="ndnums"><div class="logdays setrow col ctlrow">
      ${lbl(inp, "Claude sessions working at once (0: no limit)", "a prompt past it waits for a turn instead of starting")}
      <input id="${esc(inp)}" data-k="turns" type="number" min="0" max="64" step="1" inputmode="numeric"
        value="${esc(c.draft.turnsText)}">
    </div>
    <div class="logdays setrow col ctlrow">
      ${lbl(winp, `Test workers (0: every core${n.reported?.cpu ? `, ${n.reported.cpu} here` : ""})`,
        "how many workers a test run here may use, as BB_TEST_WORKERS in its environment")}
      <input id="${esc(winp)}" data-k="workers" type="number" min="0" max="256" step="1" inputmode="numeric"
        value="${esc(c.draft.workersText)}">
    </div></div>
`;
}

// The node's path mapping (docs/nodes.md §11): what this container's paths
// are called on that machine, because its daemon resolves a compose file's
// bind sources over there. Nearly always the identity, since a node holds
// its projects at /workspace as the controller does: path parity is a rule,
// not a setting, so it lives under Advanced with the actions that are rarely
// pressed, and says why it is there. Still read by devapp.host_map for
// every node addressed, so it is not gone.
function nodeAdvancedSection(n, stale, inflight){
  // An install or a change being applied on the machine holds Reboot and
  // Shut down: a restart in the middle of apt, or of a storage or network
  // apply, leaves it half done (the operator, 30 Sep). A reboot or shut
  // down of its own is the one system job that does not.
  const applying = (n.jobs || []).find(j => j.type === "system" && !["reboot", "poweroff"].includes(j.apply));
  const installing = inflight("toolchain") ? "a toolchain install or removal"
    : inflight("image") ? "a system image install" : inflight("claude-update") ? "a Claude Code update"
    : applying ? `a change to this node (${applying.apply || "a system job"})` : "";
  const paths = n.config?.paths || {};
  const text = Object.entries(paths).map(([k, v]) => `${k}:${v}`).join(", ");
  const c = nodeDraft(n);
  if (c.draft.pathsText === undefined || c.draft.pathsFrom !== text){
    c.draft.pathsText = text; c.draft.pathsFrom = text;
  }
  if (c.draft.nameText === undefined || c.draft.nameFrom !== n.name){
    c.draft.nameText = n.name; c.draft.nameFrom = n.name;
  }
  // Each action a row of its own (the operator, 18 Oct: the section was big
  // gaps, a sentence across the width and its buttons on the next line): its
  // name and what it does at the left, its button at the right.
  const act = (title, say, btn, cls = "") => `<div class="ndact${cls ? " " + cls : ""}"><div class="grow"><div class="name">${esc(title)}</div>
      <div class="sub">${say}</div></div><div class="acts actbar">${btn}</div></div>`;
  const body = `
    <div class="ndname actbar ctlrow">
      <div class="setrow col grow ctlrow">${lbl("", "Name", "its name in the pickers, on the project rows and as a runner label")}
      <input data-k="name" value="${esc(c.draft.nameText)}" spellcheck="false" autocomplete="off"
        maxlength="60" aria-label="node name"></div>
      <button type="button" data-nd="rename"${!String(c.draft.nameText || "").trim() || String(c.draft.nameText).trim() === n.name ? " disabled" : ""}
        title="a runner already installed keeps its old label until reinstalled">Rename</button>
    </div>
    <div class="ndpaths actbar ctlrow">
      <div class="setrow col grow ctlrow">${lbl("", "Path mapping", "here:there pairs, comma-separated; only needed when a path a compose file names is somewhere else on the node")}
      <input data-k="paths" value="${esc(c.draft.pathsText)}" spellcheck="false" autocomplete="off"
        placeholder="/workspace:/workspace, /devdata:/mnt/user/appdata/bb-dev"
        aria-label="path mapping"></div>
      <button type="button" data-nd="paths" title="save the mapping onto the node's record">Save paths</button>
      <button type="button" data-nd="check-paths"
        title="check both machines see the same projects directory">Check</button>
    </div>
    <div class="sub ndcheck${nodesCheck[n.id]?.warn ? " warn" : ""}"${nodesCheck[n.id] ? "" : " hidden"}>${esc(nodesCheck[n.id]?.text || "")}</div>
    <div class="ndacts">
    ${n.kind !== "agent" || !n.config?.host_only ? "" : act("Lock down",
        n.config?.lockdown ? "Locking down: it may take nothing but the job that stops its containers and shuts its door, and its credential is revoked when that ends, or within five minutes if it never answers."
        : "For a box that may have been taken over: stops every container here and its nginx, keeps them from starting at a boot, shuts its SSH door, and revokes its credential. The box's own console stops it without the agent.",
        `<button type="button" class="danger" data-nd="lockdown" ${n.config?.lockdown ? "disabled" : ""}>${n.config?.lockdown ? "Locking down…" : "Lock down"}</button>`)}
    ${!n.reported?.sandbox ? "" : act(n.config?.lock ? "Unlock system changes" : "Lock system changes",
        n.config?.lock ? "Locked: storage, network and root changes are refused from here." : "Refuses storage, network and root changes from here, keeping them to the machine's own console.",
        `<button type="button" data-nd="${n.config?.lock ? "unlock" : "lock"}">${n.config?.lock ? "Unlock" : "Lock"}</button>`)}
    ${act(n.state === "draining" ? "Undrain" : "Drain",
        n.state === "draining" ? "Draining: it finishes what is running and takes nothing new. Undrain takes new work again." : "Finishes what is running and takes nothing new, so the machine can reboot.",
        `<button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}">${n.state === "draining" ? "Undrain" : "Drain"}</button>`)}
    ${act("Clear cache", stale ? esc(staleWhy(n)) : "Drops every project's build cache here; the next build fetches again.",
        `<button type="button" data-nd="cache-clear" ${stale || inflight("cache-clear") ? "disabled" : ""}>${inflight("cache-clear") ? "Clearing…" : "Clear cache"}</button>`)}
    ${act(n.state === "disabled" ? "Enable" : "Disable",
        n.state === "disabled" ? "Disabled: off every picker and handed no work or session. Enable offers it again." : "Keeps it enrolled and configured, but off every picker and handed no work or session until Enable.",
        `<button type="button" data-nd="${n.state === "disabled" ? "enable" : "disable"}">${n.state === "disabled" ? "Enable" : "Disable"}</button>`)}
    ${act("Un-enroll", n.live && n.reported?.sandbox
        ? "Takes BuilderBot off the machine (its agent, accounts, mounts, runners and files; Docker and the shares stay) and removes the node here."
        : `Removes the node here; BuilderBot's pieces stay on the machine, since ${n.live ? "BuilderBot did not provision it" : "its agent is not dialing in"}.`,
        `<button type="button" class="danger" data-nd="unenroll" ${inflight("uninstall") ? "disabled" : ""}>${inflight("uninstall") ? "Un-enrolling…" : "Un-enroll"}</button>`)}
    ${n.kind !== "agent" ? "" : act("Reboot or shut down",
        !n.live ? `<span class="bad">They need the agent dialing in, and it is away: power the machine from its console or its hypervisor.</span>`
        : installing ? `<span class="bad">They wait: ${esc(installing)} is running here. Stop it first, or wait for it to finish.</span>`
        : "Reboot ends every session there and the machine comes back on its own; Shut down does not come back until somebody switches it on.",
        ["reboot", "poweroff"].map(w =>
          `<button type="button" class="danger" data-nd="${w}" ${!n.live || inflight(w) || installing ? "disabled" : ""}>${
            inflight(w) ? (w === "reboot" ? "Rebooting…" : "Shutting down…")
                        : (w === "reboot" ? "Reboot" : "Shut down")}</button>`).join(""))}
    </div>`;
  return docSection("nodes", "advanced", ndTitle("advanced"),
                    n.state === "draining" ? "draining" : n.config?.lock ? "locked" : "",
                    body, {cls: n.state === "draining" ? "warn" : ""});
}
function nodeStale(n){
  return n.kind === "agent" && n.agent?.digest && nodesAgent?.digest
    && n.agent.digest !== nodesAgent.digest;
}

// The window a version promises: "0.4" of "0.4.27", empty for anything that
// is not WINDOW.BUILD (a node that has not said hello yet). Empty means
// "cannot say" and is never read as a mismatch.
const agentWindow = v => (/^(\d+\.\d+)\./.exec(String(v || "")) || [])[1] || "";
const short = d => String(d || "").split(":").pop().slice(0, 8) || "?";

// A node whose agent is from ANOTHER window. Inside one, any agent works with
// any controller and being behind is routine; across one, that promise was
// never made, which is the difference this exists to draw.
function windowGap(n){
  const a = agentWindow(n.agent?.version), b = agentWindow(nodesAgent?.version);
  return !!(a && b && a !== b);
}

function staleWhy(n){
  const mine = n.agent?.version || "?", ship = nodesAgent?.version;
  return windowGap(n)
    ? `${n.name} runs agent ${mine} and this controller needs ${ship}: press Update agent before using this node`
    : mine === ship
    // The same number and a different file: the agent moved without its
    // version constant, and "runs 0.6.92 and ships 0.6.92" read as nonsense.
    ? `${n.name} has an older build of agent ${mine} (${short(n.agent?.digest)}, this controller ships ${short(nodesAgent?.digest)}): press Update agent first`
    : `${n.name} runs agent ${mine} and this controller ships ${ship}: press Update agent first`;
}

// Which stores a storage apply would move: saved somewhere other than where
// the node reports them. `cache` is left out: the agent does not copy it
// (rebuildable, and a cold cache costs time and never correctness), so
// promising a move here would be a lie.
function storeMoves(n){
  const want = n?.config?.desired?.stores || {}, rep = n?.reported?.stores || {};
  return Object.entries(want).filter(([role, p]) => role !== "cache" && p
      && rep[role]?.path && rep[role].path.replace(/\/+$/, "") !== String(p).replace(/\/+$/, ""))
    .map(([role, p]) => ({role, from: rep[role].path, to: p}));
}

// Saved is not applied: the record says what the node SHOULD be, the census
// says what it is, and the gap between them is the only thing Apply is for.
// Without this the buttons were live whenever anything had been saved, so
// there was no way to tell a node that matches its record from one that has
// never been applied. Returns null when nothing is saved at all.
//
// dhcp is the one case that cannot be answered: the census reports addresses,
// not how they were obtained, so a dhcp lease and a static address of the
// same value look identical. That returns "unknown" rather than a guess.
function nodeDrift(n){
  const d = n.config?.desired;
  if (!d) return null;
  const rep = n.reported || {};
  const storage = [];
  for (const m of d.mounts || []){
    const [st, cls] = mountState(m, rep.mounts);
    if (cls) storage.push(`${m.path || m.source || "a mount"}: ${st}`);
  }
  // A stale mount is drift whether or not the desired list names it: it
  // reads as mounted to every list and fails every read (roadmap R41).
  for (const r of rep.mounts || []){
    if (r.stale && !(d.mounts || []).some(m => m.path === r.path))
      storage.push(`${r.path}: ${r.error || "mounted, but the handle is stale: re-export it on the host"}`);
  }
  for (const [role, path] of Object.entries(d.stores || {})){
    if (!path) continue;
    const r = rep.stores?.[role];
    if (!r) storage.push(`${role} store not reported yet`);
    else if (r.path !== path)
      storage.push(`${role} store ${role === "cache" ? "→" : "moves to"} ${path}`);
    else if (r.free_mb === null) storage.push(`${role} store is missing on the node`);
  }
  const net = d.network || {}, rn = rep.network || {};
  let network = [];
  if (net.mode === "static"){
    const addr = (net.address || "").trim();
    if (addr && !(rn.addresses || []).includes(addr)) network.push(`address → ${addr}`);
    if (net.gateway && rn.gateway !== net.gateway) network.push(`gateway → ${net.gateway}`);
    const dns = (net.dns || []).filter(Boolean);
    if (dns.length && dns.join(",") !== (rn.dns || []).join(",")) network.push(`dns → ${dns.join(", ")}`);
    if (net.interface && rn.interface && net.interface !== rn.interface)
      network.push(`interface → ${net.interface}`);
  }else if (rn.addresses?.length){
    network = "unknown";      // dhcp: the census cannot say how it was addressed
  }
  // Static routes, in either mode, against the ones the node reports.
  const have = new Set((rn.routes || []).map(r => `${r.to} ${r.via}`));
  const routes = (net.routes || []).filter(r => !have.has(`${r.to} ${r.via}`)).map(r => `route → ${r.to} via ${r.via}`);
  if (routes.length) network = [...(Array.isArray(network) ? network : []), ...routes];
  return {storage, network};
}


// The configuration plane (docs/nodes.md §12) as three sections: the
// runner, storage (mounts and stores), network. One record underneath:
// Save keeps the whole draft, so the status line reads the same in both
// editors: is there anything to press Apply for, and what.
// System changes locked to the node's own console (the Lock under
// Advanced): the sections still show desired beside reported, and Apply
// says why it will not go. The rule is the server's; this is the courtesy.
const LOCKED_WHY = "system changes on this node are locked to its own console: Unlock under Advanced";
function nodeConfSections(n){
  const c = nodeDraft(n);
  const d = c.draft;
  const rep = n.reported || {};
  const busyNow = n.applying;
  const locked = !!n.config?.lock;
  const mounts = d.mounts.map((m, i) => {
    const [st, cls] = mountState(m, rep.mounts);
    return `
    <div class="ndmount ctlline" data-i="${i}">
      <select data-k="type" aria-label="type">
        <option value="nfs" ${m.type !== "virtiofs" ? "selected" : ""}>nfs</option>
        <option value="virtiofs" ${m.type === "virtiofs" ? "selected" : ""}>virtiofs</option>
      </select>
      <div class="setrow col ctlrow">${lbl("", "Source", m.type === "virtiofs" ? "the share tag" : "host:/export")}
      <input data-k="source" value="${esc(m.source || "")}" spellcheck="false" autocomplete="off"
        placeholder="${m.type === "virtiofs" ? "appdata" : "nas:/mnt/user/appdata"}" aria-label="source"></div>
      <div class="setrow col ctlrow">${lbl("", "Mountpoint", "blank means /mnt/ and the export's name")}
      <input data-k="path" value="${esc(m.path || "")}" spellcheck="false" autocomplete="off"
        placeholder="/mnt/appdata" aria-label="mountpoint"></div>
      <label class="ndcap"><input type="checkbox" data-k="ro" ${m.ro ? "checked" : ""}> read-only</label>
      <button type="button" class="eye" data-mrm title="take this mount out">×</button>
      <div class="sub ndmstate ${cls}">${esc(st)}</div>
    </div>`;
  }).join("");
  const STORE_ABOUT = {
    data: "job workspaces and AVDs", toolchains: "toolchains installed here",
    cache: "build caches, per project", artifacts: "what projects built, per project",
  };
  const stores = ["data", "toolchains", "cache", "artifacts"].map(role => {
    const r = rep.stores?.[role];
    const now = r ? (r.free_mb === null ? `${r.path}: missing` : `${r.path}, ${
      sgb(r.free_mb)} free`) : "";
    return `
    <div class="ndstore ctlline">
      ${lbl("", role, STORE_ABOUT[role] || "")}
      <input data-k="store:${esc(role)}" value="${esc(d.stores[role] || "")}" spellcheck="false"
        autocomplete="off" placeholder="${esc(r?.path || "/var/lib/builderbot/" + role)}">
      <div class="sub">${now ? "now " + esc(now) : "not reported"}</div>
    </div>`;
  }).join("");
  const net = rep.network || {};
  const now = net.addresses?.length
    ? `now ${net.addresses.join(", ")} on ${net.interface || "?"}${net.gateway ? " via " + net.gateway : ""}${
        net.dns?.length ? " · dns " + net.dns.join(", ") : ""}` : "address not reported";
  const isStatic = d.network.mode === "static";
  const stale = nodeStale(n);
  const drift = nodeDrift(n);
  const netPend = drift && (drift.network === "unknown" || drift.network.length);
  // An apply that ran and did not work, said where the button is. A failed
  // apply leaves the drift exactly as it was, so the section went back to
  // "4 changes to apply" and mentioned the attempt nowhere, which is
  // indistinguishable from a button that does nothing, and is what the
  // operator saw.
  //
  // ONLY WHILE IT IS STILL THE ANSWER. A failure that has been overtaken:
  // the node matches now, the operator is typing, the agent is behind, one
  // is running: is history, and the current state is the more useful
  // sentence. So it is reported only when this kind still has something to
  // apply and nothing more immediate is true.
  const stillPending = {storage: !!drift?.storage.length,
                        network: !!netPend && drift?.network !== "unknown"};
  // ...and only while it is about the record as it stands. `current` is the
  // server comparing the config the job carried with the one saved now: a
  // failure the operator has since saved past is about a record that no
  // longer exists, and the changes waiting are the thing to say.
  const la = n.last_apply?.current ? n.last_apply : null;
  const failedFor = kind =>
    la && la.state !== "succeeded" && la.what === kind && stillPending[kind]
    && !busyNow && !stale && !c.dirty
      ? [`The last ${kind} apply ${la.state === "canceled" ? "was canceled" : "failed"}${
          la.error ? ": " + la.error : ""}. Its log is on the Jobs page; fix it and Apply again.`, "bad"]
      : null;
  // Each section's state line answers one question: is there anything in
  // it to press its Apply for, and names those changes when there is, so
  // the button is not a leap. Storage's changes are never said under
  // Network, nor Network's under Storage.
  const lineFor = kind => {
    const pending = !drift ? [] : kind === "storage" ? drift.storage
      : drift.network === "unknown" ? [] : drift.network;
    return busyNow
      ? [`applying ${busyNow.what}${busyNow.what === "network" ? ": waiting for it to dial back in" : "…"}`, "note"]
      : stale ? [staleWhy(n), windowGap(n) ? "bad" : "warn"]
      : c.dirty ? ["Unsaved: press Save, then Apply.", "warn"]
      : !drift ? ["nothing configured yet: the node runs on whatever it was set up with", ""]
      : pending.length ? [`${pending.length} change${pending.length === 1 ? "" : "s"} to apply: ${
          pending.slice(0, 3).join("; ")}${pending.length > 3 ? "; …" : ""}`, "warn"]
      // The dhcp caveat is Network's; under Storage it read as a storage fault.
      : kind === "network" && drift.network === "unknown"
        ? ["the node matches what is saved here, except dhcp, which cannot be told from here", ""]
        : ["the node matches what is saved here", "ok"];
  };
  const [storStatus, storStatusCls] = lineFor("storage");
  const [status, statusCls] = lineFor("network");
  const saveBtn = `<button type="button" data-nsave ${c.dirty ? "" : "disabled"}
      title="save these settings; Apply puts them on the node">Save</button>`;
  const storage = `
      <div class="sub">Mounts at boot.${
        d.fromNode ? ` <span class="dim">As the node reports them; save to manage them from here.</span>` : ""}</div>
      ${mounts}
      <div class="addbar ctlrow"><button type="button" data-madd>Add a mount</button></div>
      <div class="sub">Where job data, toolchains, caches and artifacts live.</div>
      ${stores}
      <div class="actbar">
        <span class="state ndconfstate${(failedFor("storage") || [0, storStatusCls])[1] ? " " + (failedFor("storage") || [0, storStatusCls])[1] : ""}">${
          esc((failedFor("storage") || [storStatus])[0])}</span>
        ${saveBtn}
        <button type="button" data-napply="storage" ${
          busyNow || c.dirty || stale || locked || !drift?.storage.length ? "disabled" : ""}
          title="${locked ? LOCKED_WHY : stale ? esc(staleWhy(n))
            : !drift ? "nothing is saved to apply"
            : !drift.storage.length ? "the node already has the mounts and stores saved here"
            : "apply the mounts and stores to the node"}">Apply storage</button>
      </div>`;
  // The four static fields only when static: five boxes of placeholders
  // under a dhcp node were the wall this section used to be on a phone.
  // Which service on the machine the agent would write this into. The
  // spec it is sent is the same everywhere; the agent detects the backend
  // (netplan, NetworkManager, systemd-networkd, wicked, ifupdown, dhcpcd)
  // and reports it in the census, so the row can say so before the job goes
  //, or say that a change would be refused, on a machine with none.
  const dist = rep.distro;
  const NET_BACKENDS = {netplan: "netplan", networkmanager: "NetworkManager",
    "systemd-networkd": "systemd-networkd", wicked: "wicked", ifupdown: "/etc/network/interfaces",
    dhcpcd: "dhcpcd"};
  const via = !dist ? ""
    : NET_BACKENDS[dist.network] ? ` Through ${NET_BACKENDS[dist.network]} on this node.`
    : ` <b class="warn">This node reports no network backend the agent drives${
        dist.pretty ? " (" + esc(dist.pretty) + ")" : ""}; a change would be refused.</b>`;
  const network = `
      <div class="sub">Applied with a three-minute dial-back, or reverted.${via}</div>
      <div class="ndnet ctlline${isStatic ? "" : " dhcp"}">
        <select data-k="net:mode" aria-label="mode">
          <option value="dhcp" ${isStatic ? "" : "selected"}>dhcp</option>
          <option value="static" ${isStatic ? "selected" : ""}>static</option>
        </select>
        ${isStatic ? `
        <div class="setrow col ctlrow">${lbl("", "Address", "with its prefix length")}
        <input data-k="net:address" value="${esc(d.network.address || "")}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.12/24" aria-label="address"></div>
        <div class="setrow col ctlrow">${lbl("", "Gateway")}
        <input data-k="net:gateway" value="${esc(d.network.gateway || "")}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.1" aria-label="gateway"></div>
        <div class="setrow col ctlrow">${lbl("", "DNS", "comma-separated")}
        <input data-k="net:dns" value="${esc((d.network.dns || []).join(", "))}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.1, 1.1.1.1" aria-label="dns"></div>
        <div class="setrow col ctlrow">${lbl("", "Interface", "blank means the default route's")}
        <input data-k="net:interface" value="${esc(d.network.interface || "")}" spellcheck="false"
          autocomplete="off" placeholder="${esc(net.interface || "eth0")}" aria-label="interface"></div>` : ""}
        <div class="setrow col ndroutes ctlrow">${lbl("", "Static routes", "one a line: a network with its prefix, via the router that reaches it")}
        <textarea data-k="net:routes" rows="${Math.max(2, (d.network.routes || []).length + 1)}" spellcheck="false"
          autocomplete="off" placeholder="10.20.0.0/24 via 192.168.1.1" aria-label="static routes">${
          esc((d.network.routes || []).map(r => `${r.to} via ${r.via}`).join("\n"))}</textarea></div>
      </div>
      <div class="sub">${esc(now)}</div>
      <div class="actbar">
        <span class="state ndconfstate${(failedFor("network") || [0, statusCls])[1] ? " " + (failedFor("network") || [0, statusCls])[1] : ""}">${
          esc((failedFor("network") || [status])[0])}</span>
        ${saveBtn}
        <button type="button" data-napply="network" ${busyNow || c.dirty || stale || locked || !netPend ? "disabled" : ""}
          title="${locked ? LOCKED_WHY : stale ? esc(staleWhy(n))
            : !drift ? "nothing is saved to apply"
            : !netPend ? "the node is already on the address saved here"
            : "re-address the node; it must dial back in within three minutes or it reverts"}">Apply network</button>
      </div>`;
  const stStatus = locked ? "locked" : busyNow?.what === "storage" ? "applying"
    : failedFor("storage") ? "apply failed"
    : c.dirty ? "unsaved" : drift?.storage.length ? `${drift.storage.length} to apply`
    : `${(rep.mounts || []).length} mount${(rep.mounts || []).length === 1 ? "" : "s"}`;
  const stCls = busyNow?.what === "storage" ? "note"
    : failedFor("storage") ? "bad" : c.dirty || drift?.storage.length ? "warn" : "";
  const netStatus = locked ? "locked" : busyNow?.what === "network" ? "applying"
    : failedFor("network") ? "apply failed"
    : c.dirty ? "unsaved" : netPend && drift.network !== "unknown" ? "to apply"
    : net.addresses?.length ? net.addresses[0] : "";
  const netCls = busyNow?.what === "network" ? "note"
    : failedFor("network") ? "bad" : c.dirty || (netPend && drift.network !== "unknown") ? "warn" : "";
  // .ndconf and .ndconfbody: the names the suite finds the plane by; the
  // sections are its children, so a test can read them in order.
  // Storage and Network edit the machine's own configuration: fstab, and
  // whatever owns its network, which only a node provisioned as a sandbox (a MANAGED node,
  // roadmap #23) hands over. A container node or a guest machine keeps its
  // mounts and its address its own, and the tab says so rather than
  // offering buttons the agent refuses.
  const managed = !!rep.sandbox;
  return `<div class="ndconf"><div class="ndconfbody">
    ${managed
      ? docSection("nodes", "storage", ndTitle("storage"), stStatus, storage, {cls: stCls})
        + docSection("nodes", "network", ndTitle("network"), netStatus, network, {cls: netCls})
      : `<div class="hint ndguest">Storage and network are managed on the machine itself, not here.</div>`}
  </div></div>`;
}
function meter(label, pct, right, title){
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  const cls = p >= 92 ? "bad" : p >= 80 ? "warn" : "";
  return `<div class="ndmeter${cls ? " " + cls : ""}"${title ? ` title="${esc(title)}"` : ""}>
    <span class="lbl">${esc(label)}</span>
    <span class="track"><span class="fill" style="width:${p}%"></span></span>
    <span class="val">${esc(right)}</span></div>`;
}

// Storage's reading of a size (sgb): TB past ten of them (B834: 11425GB).
const gb = mb => sgb(mb);

// Everything the census measured, as meters: what the machine is doing now,
// and how much room each store has left.
function nodeMeters(n){
  const rep = n.reported || {}, s = rep.sample || {};
  const out = [];
  // What the charts below draw is not drawn again as a bar (the operator,
  // 17 Oct): CPU and memory where the node has its hour charted, the card's
  // two where its hour holds the card.
  const {cpu: charted, gpu: gpuCharted} = nodeCharted(n);
  if (n.live && typeof s.cpu_pct === "number" && !charted)
    out.push(meter("cpu", s.cpu_pct, s.cpu_pct + "%",
                   `${rep.cpu || "?"} cores${s.load1 ? `, load ${s.load1}` : ""}`));
  const mem = s.mem_mb || rep.mem_mb;
  if (n.live && mem && s.mem_used_mb && !charted)
    out.push(meter("memory", s.mem_used_mb / mem * 100,
                   `${gb(s.mem_used_mb)} / ${gb(mem)}`));
  // The card, where the node has one whose driver answers: how busy it is
  // and how much of its own memory is taken, the two things a model or an
  // encode is waiting on.
  if (n.live && typeof s.gpu_pct === "number" && !gpuCharted)
    out.push(meter("gpu", s.gpu_pct, s.gpu_pct + "%", rep.gpu || "the node's card"));
  if (n.live && s.gpu_mem_mb && !gpuCharted)
    out.push(meter("vram", (s.gpu_mem_used_mb || 0) / s.gpu_mem_mb * 100,
                   `${gb(s.gpu_mem_used_mb || 0)} / ${gb(s.gpu_mem_mb)}`, "the card's own memory"));
  // Two shapes for the same fact, and mixing them said "missing" about
  // four healthy stores. The CENSUS carries the whole story per store
  // ({path, free_mb, total_mb}) and moves every ten minutes; the heartbeat
  // flattens each one to a bare free-space number and arrives every poll
  // (nodes.heartbeat). So the census gives the shape and the sample gives
  // the freshness: never the sample alone, which has no total to take a
  // percentage of and no path to name.
  for (const [role, st] of Object.entries(rep.stores || {})){
    const live = s.stores?.[role];
    const free = typeof live === "number" ? live : st?.free_mb;
    if (free === null || free === undefined){
      out.push(meter(role, 0, "missing", `${st?.path || role}: the node cannot see it`));
      continue;
    }
    const total = st?.total_mb || 0;
    const used = total ? Math.max(0, total - free) : 0;
    out.push(meter(role, total ? used / total * 100 : 0, `${gb(free)} free`,
                   `${st?.path || ""}${total ? `: ${gb(used)} of ${gb(total)} used` : ""}`));
  }
  return out.length ? `<div class="ndmeters">${out.join("")}</div>` : "";
}


// Which of its hour the node's charts draw: CPU and memory for an agent
// with samples, and its card's where any sample has one.
function nodeCharted(n){
  const sp = n.kind === "agent" ? (n.spark || []) : [];
  return {cpu: sp.length > 0, gpu: sp.some(x => typeof x[3] === "number"), vram: sp.some(x => typeof x[4] === "number")};
}

// Its last hour, CPU and memory, side by side at a desk (R218 step 9): the
// controller's ring of its samples, one each poll. Small multiples rather
// than two lines on one chart, so neither needs a legend or a second hue.
// The card's busyness and its own memory beside them where it has one (the
// operator, 17 Oct).
function nodeCharts(n){
  const c = nodeCharted(n);
  if (!c.cpu) return "";
  return `<div class="charts ndcharts">${hourChart(`cpu:${n.id}`, "CPU", n.spark.map(x => [x[0], x[1]]))}${
    hourChart(`mem:${n.id}`, "Memory", n.spark.map(x => [x[0], x[2]]))}${
    c.gpu ? hourChart(`gpu:${n.id}`, "GPU", n.spark.map(x => [x[0], x[3]])) : ""}${
    c.vram ? hourChart(`vram:${n.id}`, "GPU RAM", n.spark.map(x => [x[0], x[4]])) : ""}</div>`;
}

// The page's parts its placeholder draws too (R218, the operator 18 Oct: a
// template written beside the page fell behind it), so a change to either
// is a change to both; given null, each draws the placeholder's.
// A node's sections, in their order, by the titles they are drawn under.
const ND_SECTS = [["health", "Health"], ["projects", "Projects"], ["sessions", "Sessions"], ["gpu", "GPU"],
                  ["features", "Features"], ["agents", "Coding agents"], ["storage", "Storage"], ["network", "Network"], ["advanced", "Advanced"]];
function ndTitle(k){ return (ND_SECTS.find(s => s[0] === k) || [k, k])[1]; }
// Why Create sandbox VM and Enroll node are dead, when this install switched
// enrolling off (R81): under the bar, since a reason in a tooltip is nothing
// on a phone.
function ndOffLine(){
  const why = featureOff("enroll");
  return why ? `<div class="field">${deadWhy(why)}</div>` : "";
}
// The bar: the node switcher, Create sandbox VM, and Enroll node.
function ndBar(live){
  // Enrolling switched off on this install (R81): both dead, the reason on
  // the page under the bar (ndOffLine).
  const g = !live, dead = g || featureOff("enroll") ? " disabled" : "";
  return nodeBar(nodePick("ndPick", g ? null : live.map(x => ({id: x.id, name: x.name, live: x.live})), nodesPick),
    `<button type="button"${g ? "" : ` id="ndVm"`}${dead}>${barSaid("Create sandbox VM", "New VM")}</button>
      <button type="button" class="primary"${g ? "" : ` id="ndEnroll"`}${dead}>${barSaid("Enroll node", "Enroll")}</button>`);
}
// Its facts in the facts voice, its id among them (R218 step 26): the id is
// the one in its enroll script's name.
const ND_FACTS = ["Reached", "Has", "Seen", "Agent", "Jobs run as", "Runs on", "Id"];
function ndFacts(vals){
  return factGrid(ND_FACTS.map((k, i) => [k, vals ? vals[i] : GHOST, k === "Id" ? {cls: "ndid"} : undefined]), "ndfacts");
}
// Test and Enroll script, the head's two buttons about the machine itself.
function ndAgentButtons(dead){
  const off = dead ? " disabled" : "";
  return `<button type="button"${dead ? "" : ` data-nd="test"`} title="check that this node answers"${off}>Test</button>
          <button type="button"${dead ? "" : ` data-nd="reenroll"`} title="a new enroll script for this node, to run again on the same machine"${off}>Enroll script</button>`;
}

// The node's page: a header band: name, state, where it is, its agent and
// the one control that is about the agent, then the sections.
function renderNodesInto(i){
  const d = docSurface(i, "nodes");
  if (!d) return;
  if (nodesList === null){
    // Its template (R218 step 16): the bar, the sections' names and the jump
    // bar over them are the page's own; the node and what it says are on
    // their way. A section somebody shut is drawn shut, as it will land.
    // Drawn by the page's own builders given nothing (the operator, 18
    // Oct: a template written beside the page fell behind it): the bar, the
    // head card with its facts' labels and its two buttons, the sections a
    // node usually has under their own titles, and the jump bar sectJump
    // puts over them, as the page does.
    d.setBar(ndBar(null));
    d.list.innerHTML = skTpl(`<div class="row stack2 ndrow"><div class="grow">
        <div class="name">${skv(7)}</div>${ndFacts(null)}
        <div class="actbar ndagent"><span class="lead dim"></span>${ndAgentButtons(true)}</div></div>
      <div class="ndsections">${ND_SECTS.filter(([k]) => k !== "gpu").map(([k, t], j) =>
        docSection("nodes", k, t, "", skRows(j ? 1 : 3))).join("")}</div></div>`);
    sectJump(d.list.closest(".doctab") || d.el);
    loadNodes();
    return;
  }
  if (nodesErr){
    d.list.innerHTML = `<div class="hint bad">${esc(nodesErr)}</div>`;
    return;
  }
  // One node at a time, picked at the top. Every node's whole configuration
  // on one page was a wall: mounts, four stores, network, the runner, the
  // actions, per row, for every machine, and the fold that hid it only
  // moved the problem: the settings you came for were two taps down and the
  // ones you did not care about were still in the way. So the tab is a
  // picker and one machine, in sections, like the Docker manager and the
  // Tools tab already are (docs/nodes.md §13: one tab, re-rendered per pick).
  // Enrolled machines only. The controller has a node record of its own;
  // that is how a share it mounts is recognized as the same store a node
  // mounts, and how install arbitration works across the pair, but it is
  // not a machine anybody configures from here: it runs no work (roadmap
  // #16), takes no toolchains (#26), and every section on this tab is about
  // something it does not have. So it is registry plumbing, not a row.
  const live = nodesList.filter(n => n.state !== "retired" && n.kind !== "local");
  if (!live.some(n => n.id === nodesPick)) nodesPick = live[0]?.id || "";
  const n = live.find(x => x.id === nodesPick);
  // Picked as every node-scoped page picks one (nodePick, R218 step 26).
  d.setBar(ndBar(live));
  const rows = (n ? [n] : []).map(n => {
    const labels = Object.entries(n.labels || {})
      .map(([k, v]) => `<span class="pill">${esc(k)}=${esc(v)}</span>`).join(" ");
    const seen = n.agent?.last_seen
      ? `seen ${ago(n.agent.last_seen)}` : (n.kind === "agent" ? "never seen" : "");
    const census = n.reported?.cpu
      ? `${n.reported.cpu} cpu · ${Math.round((n.reported.mem_mb || 0) / 1024)}GB`
      : "";
    const where = n.kind === "local" ? "this container"
      : n.agent?.addr ? `dials in from ${n.agent.addr}` : "";
    // Behind when the node's agent is not the file this controller ships.
    // Said on the row before anybody presses anything: a five-version-old
    // agent otherwise looks exactly like a current one.
    const stale = nodeStale(n);
    // A job of this type queued or running on this node. pressing() grays a
    // button for the round trip; this is what keeps it gray afterwards,
    // through the repaint that replaces the element.
    const inflight = t => (n.jobs || []).some(j => j.type === t || j.apply === t);
    // What a session is waiting on, as root, on THIS machine (roadmap R38):
    // above everything else on the row, because somebody is blocked on it
    // and it is the one thing here that runs as root. From the phone's
    // answer, which carries every ask for this account; the server sends a
    // root ask to administrators only, so a user sees none.
    // Every node's, not only the picked one's: the tab shows one machine at
    // a time and a request on another would otherwise wait unseen here
    // (the row names its node). The bell carries them too.
    const rootAsks = (typeof ph !== "undefined" && ph?.asks || []).filter(a => a.kind === "root");
    const askRows = rootAsks.map(a => `<div class="row ndask">
      <div class="grow"><div class="name">root: ${esc(a.why)}</div>
        <div class="phcmd">${askCmd(a)}</div>
        <div class="sub">${esc(askWho(a))} asks to run this as root on ${esc(a.node_name)} · ${askLeft(a)}</div></div>
      <span class="acts">${askActs(a, {deny: "data-rdeny", allow: "data-rallow"})}</span></div>`).join("");
    // An update was pressed less than three minutes ago and the agent has
    // not come back with the new digest: the job row is gone the moment the
    // agent swaps itself in, but the row only learns that from its next
    // hello, so for that gap the button stays busy and the line says what
    // is being waited for, rather than offering the same press again.
    const updating = stale && (inflight("self-update")
      || Date.now() - (nodesUpdating[n.id] || 0) < 180000);
    // ...and while it is queued the controller hands the node nothing new
    // until what runs there has finished (B516), so the line says what it
    // is waiting for rather than "Updating" for minutes.
    const held = (n.jobs || []).some(j => j.type === "self-update" && j.state === "queued")
      ? (n.jobs || []).filter(j => j.type !== "self-update" && j.state !== "queued").length : 0;
    // The agent a fact; an update for it a pill beside the node's state.
    const agentVer = n.kind === "agent" && n.agent?.version
      ? `${n.agent.version}${n.agent.digest ? " " + n.agent.digest.slice(7, 15) : ""}` : "";
    const stalePill = n.kind === "agent" && n.agent?.version && stale
      ? ` <span class="pill warn ndstale" title="this controller ships agent ${
          esc(nodesAgent.version)} ${esc(nodesAgent.digest.slice(7, 15))}">update available → ${esc(nodesAgent.version)}</span>` : "";
    const pending = n.state === "pending";
    // A waiting row says what its script was made with (the operator, 11
    // Oct), and offers the script again: a new one, since a token is good
    // once and never kept, so the old script stops working.
    const picks = c => [`jobs run as ${esc(c.user || "bb")}`,
      c.host_only ? "hosting only" : "runs sessions",
      c.tunnel?.kind === "public" ? `reaches the controller at https://${esc(c.tunnel.host || "?")}`
        : c.tunnel?.kind === "wireguard" ? `reaches the controller through WireGuard as ${esc(c.tunnel.addr || "?")}`
        : "reaches the controller on this network",
      c.door?.kind ? `SSH door: ${esc(c.door.kind)}${c.door.host ? ` at ${esc(c.door.host)}` : ""}` : "",
      c.nginx ? "nginx once enrolled" : ""].filter(Boolean).join(" · ");
    const pendingBar = n.kind === "agent" && pending ? `
        <div class="sub ndpicks">Made with: ${picks(n.config || {})}.</div>
        <div class="actbar ndpending">
          <span class="lead dim">Waiting for enroll-${esc(n.name)}-${esc(n.id)}.sh to run on the machine. Download it again makes a new one with a new token (the old script stops working); Discard takes the row off.</span>
          <button type="button" data-nd="reenroll" title="a new enroll script for this row, with a new token">Download it again</button>
          <button type="button" class="danger" data-nd="discard" title="take this waiting row off: nothing has enrolled with it">Discard</button>
        </div>` : "";
    const agentBar = n.kind === "agent" && !pending ? `
        <div class="actbar ndagent">
          <span class="lead dim${updating ? " note"
                              : stale ? (windowGap(n) ? " bad" : " warn") : ""}">${
            updating ? (held ? `Update to agent ${esc(nodesAgent?.version || "")} waits for ${held} running job${
                held === 1 ? "" : "s"} to finish; the node takes no new work until then (10 minutes at most).`
              : `Updating to agent ${esc(nodesAgent?.version || "")}. This row refreshes when the node reports back.`)
            : stale ? `${windowGap(n) ? "out of window" : "behind"}: ${esc(staleWhy(n))}`
            : ""}</span>
          ${stale ? `<button type="button" data-nd="update-agent" ${updating ? "disabled" : ""}
            title="${updating ? "Update queued: this row refreshes when the node reports back"
              : `Update the agent to ${esc(nodesAgent.version)} once its running jobs finish`}">${
            updating ? "Updating…" : "Update agent"}</button>` : ""}
          ${ndAgentButtons(false)}
        </div>
        <div class="sub ndtest" hidden></div>` : "";
    const health = docSection("nodes", "health", ndTitle("health"),
      n.kind === "agent" ? (n.live ? "live" : "quiet") : "", `
        ${nodeMeters(n) || `<div class="empty">nothing measured yet</div>`}
        ${nodeCharts(n)}
        <div class="ndhmore">
        ${nodeTools(n)}
        ${nodeGit(n)}
        ${nodeGpu(n)}
        ${nodeSound(n)}
        ${nodeInternet(n)}
        ${labels ? `<div class="sub ndlabels">${labels}</div>` : ""}</div>`,
      {cls: n.kind === "agent" && n.live ? "ok" : "", open: true});
    // Every live agent node gets the plane: the runner needs no stamp. What
    // inside it needs one (Storage and Network) nodeConfSections decides.
    const plane = n.kind === "agent" && !pending;
    return askRows + `
    <div class="row stack2 ndrow" data-node="${esc(n.id)}">
      <div class="grow">
        <div class="name">${esc(n.name)} ${nodeStatePill(n)}${stalePill}</div>
        ${
        // Its facts in the facts voice, its id among them (R218 step 26):
        // the id is the one in its enroll script's name.
        ndFacts([where, census, seen, agentVer, n.kind === "agent" ? n.config?.user || "" : "",
                 // A VM BuilderBot made on another node (R91 step 14).
                 n.config?.vm_of ? `${(nodesList || []).find(x => x.id === n.config.vm_of)?.name || n.config.vm_of}, as a VM` : "", n.id])}
        ${keepLine(n)}
        ${agentBar}${pendingBar}
      </div>
      <div class="ndsections">
        ${health}
        ${n.kind === "agent" && !pending ? nodeProjectsSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeSessionsSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeGpuSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeFeaturesSection(n) : ""}
        ${n.kind === "agent" && !pending && !n.config?.host_only ? nodeAgentsSection(n) : ""}
        ${plane ? nodeConfSections(n) : ""}
        ${n.kind === "agent" && !pending ? nodeAdvancedSection(n, stale, inflight) : ""}
      </div>
    </div>`;
  }).join("");
  // Nothing enrolled. Said where the rows would be, rather than an empty
  // picker over an empty page: the Enroll button above is the whole of what
  // there is to do here.
  const none = live.length ? "" : state?.can?.admin === false
    ? `<div class="empty ndnone">None of your projects is on a node yet. An administrator sets a project's node.</div>`
    : `<div class="empty ndnone">No node yet. Press <b>Enroll node</b> to get the command
      that adds a machine for builds, tests and sessions.</div>`;
  // Enrolling is a dialog now (#ndmodal), not two panels appended here; see
  // the markup's comment. Which means a poll landing while it is open cannot
  // take the name being typed with it, because this list is not where it is.
  d.list.innerHTML = ndOffLine() + rows + none
    + (!nodesList.length ? `<div class="empty">The node list could not be read.</div>` : "");
  wireNodesTab(d.el);
  nodesReadOnly(d.el);
  // What openNodesTab was asked to show, once it is drawn.
  const want = nodesReveal && d.el.querySelector(nodesReveal);
  if (want){
    nodesReveal = null;
    requestAnimationFrame(() => want.scrollIntoView({block: "center", behavior: noMotion() ? "instant" : "smooth"}));
  }
}

// The node's phone (tab-phone.js), where the phone is: a node with adb is a
// place a phone is paired, connected and lent, each node its own (the
// operator, 2 Oct). Only on a node the phone answer lists, which is a node
// carrying adb; the answer is fetched the first time the section is drawn.
// The node's phone and CI runner are tools of their own now (R121): a line
// here says so and opens them on this node, so somebody who looks for them
// where they were is sent where they are.
function nodeToolsLine(n){
  return `<div class="actbar ndtoolsline"><span class="state">This node's phone and CI runner are on their own tabs.</span>
    <button type="button" data-ndphone="${esc(n.id)}">Phone</button>
    <button type="button" data-ndrunner="${esc(n.id)}">CI runner</button></div>`;
}

// The CI runner tab (R121): a node picked in its bar, and that node's runners
// below, drawn and wired exactly as the Nodes tab drew them (nodeRunnerSection
// and wireNodeConf, one draft per node), so the two cannot disagree.
let runnerNode = "";
function openRunnerTab(nid){
  // The CI runner tab is a grant (R137 step 3, the operator's R136 line):
  // the card's status stays for everybody; the tab does not open for an
  // account without it, and the server refuses its writes regardless.
  if (state?.can?.runner === false) return notify("the CI runner is an administrator's: its status is on the card", true);
  if (nid) runnerNode = nid;
  openTab({kind: "runner", arg: "__runner", label: "CI runner"});
}
// Every node's runner, one row each, above the chosen node's section: which
// is busy, idle or quiet across the install, a question the per-node section
// cannot answer (the sidebar's Runner card's, until R218 step 3). A runner
// job in flight comes first, a failure carries its time, and a row picks
// its node.
function runnerRows(){
  const rows = state?.node_runners || [];
  if (!rows.length) return "";
  const when = t => fmtTime((t || 0) * 1000, {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  return `<div class="runnersall">${rows.map(n => {
    const [word, cls] = !n.live ? ["quiet: the node has not dialed in lately", "warn"]
      : n.installing ? ["installing now", "warn"]
      : n.removing ? ["removing now", "warn"]
      : n.busy ? ["running a job", "ok"]
      : n.listening ? ["listening, idle", "ok"]
      : n.installed ? ["installed, not listening", "bad"]
      : n.failed ? [`install failed ${when(n.failed.ended)}: ${n.failed.why || "its job on the Jobs page says why"}`, "bad"]
      : ["install asked for; not reported yet", "warn"];
    return `<button type="button" class="row${n.id === runnerNode ? " on" : ""}" data-runnode="${esc(n.id || "")}"><span class="grow"><b>${esc(n.node)}</b>${
      n.url ? ` <span class="dim">${esc(n.url.replace(/^https?:\/\//, ""))}</span>` : ""}
      <span class="sub ${cls}">${esc(word)}</span></span></button>`;
  }).join("")}</div>`;
}

function renderRunnerInto(i){
  const d = docSurface(i, "runner");
  if (!d) return;
  if (nodesList === null){
    // Its template (R218 step 16): the bar and the state row's words are the
    // page's own; the node and its runners are on their way.
    // In the node's panel, as it lands: its rows are bands there, not a card.
    d.setBar(skNodeBar([["Add runner", "primary"]]));
    d.list.innerHTML = skTpl(`<div class="ndrow runnerpanel">${headLine(`${skv(5)} One runner per git host; its labels decide which workflows land here.`,
      "", "toolstate")}<div class="ndruns">${skRows(1)}</div></div>`);
    return;
  }
  const ns = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  const has = n => (n.reported?.services?.runners || []).length || Object.keys(n.services?.runners || {}).length;
  if (!ns.some(n => n.id === runnerNode)) runnerNode = (ns.find(has) || ns[0])?.id || "";
  const n = ns.find(x => x.id === runnerNode);
  d.setBar(nodeBar(nodePick("rnrPick", ns, runnerNode), runnerAddBtn(n, n ? nodeDraft(n) : {})));
  const show = d.el.querySelector("[data-nrunnershow]");
  if (show) show.onclick = () => { nodeDraft(n).addRunner = true; nodesRev++; drawPanes(); };
  d.list.innerHTML = n
    ? `<div class="ndrow runnerpanel" data-node="${esc(n.id)}"><div class="ndconf">${nodeRunnerSection(n, nodeDraft(n),
        // Several to compare; one is what the section under it says already.
        (state?.node_runners || []).length > 1 ? runnerRows() : "")}</div></div>`
    : noNodeYet("a runner is added to a node");
  if (n) wireNodeConf(d.list.querySelector(".ndrow"), n.id);
  d.list.querySelectorAll(".ndrunro button").forEach(b => { b.disabled = true; });
  // CI runners switched off on this install (R81): every control here dead,
  // the sentence above them.
  if (featureOff("runner")){
    d.list.querySelectorAll("button, input, select").forEach(b => { b.disabled = true; });
    d.list.insertAdjacentHTML("afterbegin", `<div class="field">${deadWhy(featureOff("runner"))}</div>`);
  }
  d.list.querySelectorAll("[data-runnode]").forEach(r => r.onclick = () => { runnerNode = r.dataset.runnode; nodesRev++; drawPanes(); });
  const pick = d.el.querySelector("#rnrPick");
  // A pick is a history entry (B31), so Back returns to the node before.
  if (pick) pick.onchange = () => navPush(() => { runnerNode = pick.value; nodesRev++; drawPanes(); });
}

// Add runner, the page's main action, in its bar with every other header
// button (the operator, 17 Oct: all of a page's header buttons on one row);
// while the add band is open it is the band's to finish or cancel.
function runnerAddBtn(n, c){
  // Not drawn where this account's roles do not give it (the operator, 21 Oct).
  if (!n || c.addRunner || n.runner_new === false || nodeMay(n) !== "write") return "";
  return `<button type="button" class="primary" data-nrunnershow ${n.applying || nodeStale(n) || featureOff("runner") ? "disabled" : ""}
    title="a runner for another git host, or this one's under another address">Add runner</button>`;
}

// An account that does not administer sees a node's settings and changes
// none of them: every control on the tab is dead for it but the picker and
// its own Claude sign-in (the operator, 30 Sep), with nothing saying why
// (the operator, 21 Oct: a role somebody lacks is not advertised). Once,
// after the draw and its wiring, rather than in each section: a control a
// later section adds is dead for that account without anybody remembering.
// Node by node since R260: a role may write one node and read another, so
// a row is dead where the server says its account may only read it (the
// row's `may`), and the page's own controls only when it may write none.
const nodeMay = n => n?.may || (state?.can?.admin === false ? "read" : "write");
function nodesReadOnly(root){
  const dead = el => el.querySelectorAll("button, input, select, textarea").forEach(c => {
    // A phone is its owner's, any account's (tab-phone.js): its section
    // stays live, and the server holds who may press what there.
    if (c.id !== "ndPick" && !c.closest("[data-signin]") && !c.closest(".phonetab")) c.disabled = true;
  });
  root.querySelectorAll(".ndrow[data-node]").forEach(r => {
    if (nodeMay((nodesList || []).find(x => x.id === r.dataset.node)) !== "write") dead(r);
  });
  if (!(nodesList || []).some(n => nodeMay(n) === "write")) dead(root);
}

// Remove a project from this node: its settings saved with the node out of
// its set, the primary moving to the next of the set as the dialog's own
// save does. What ends with it is said before the press.
async function nodeProjectRemove(b, name, id){
  const p = (state?.projects || []).find(x => x.name === name);
  if (!p || !id) return;
  const nname = (nodesList || []).find(x => x.id === id)?.name || "this node";
  const rest = (p.prefs?.nodes || []).filter(x => x !== id);
  const node = p.prefs?.node === id ? (rest[0] || "") : (p.prefs?.node || "");
  const inIt = c => { const m = /^\/workspace\/(?:\.worktrees\/)?([^/]+)/.exec(c || ""); return m && m[1] === name; };
  const here = (state?.sessions || []).filter(x => x.node_id === id && inIt(x.cwd));
  if (!confirm(`Remove ${projLabel(name)} from ${nname}?\n\n`
        + (rest.length ? "" : "It is then on no node: nothing builds, tests or opens a session for it until one is picked. ")
        + (here.length ? `Its ${here.length} session${here.length === 1 ? "" : "s"} open there keep running until closed. ` : "")
        + "Its containers there keep running, and the Containers page still reaches them.")) return;
  busy(b, "Removing");
  const j = await (await postJSON("/api/prefs", {project: name, node, nodes: rest}))
    .json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  else notify(`${projLabel(name)} no longer uses ${nname}`);
  await refresh();
  nodesRev++; drawPanes();
}

// The enroll and sandbox VM dialogs, drawn into #ndmodal (outside every
// page's DOM, so a poll landing mid-type cannot take what was typed): the
// Nodes page's two buttons open them, and so does first run's node step
// (page-setup.js), so there is one way to enroll (R267). Built on each
// call, as they were on each wiring of the Nodes page.
function ndDialogs(){
  // ---- enrolling, in a dialog -------------------------------------------
  // Written here rather than into the tab, so a poll landing mid-type cannot
  // take the name with it: the box is outside this tab's DOM and survives
  // every repaint. Painted only when it opens, for the same reason.
  const modal = document.getElementById("ndmodal");
  const body = document.getElementById("ndBody");
  const shut = () => { modal.hidden = true; body.innerHTML = ""; };
  // The box narrows for the question and widens for the answer: one field
  // does not want 760px, and a shell line that wraps lies about what runs.
  const boxWidth = wide => modal.querySelector(".box").classList.toggle("wide", wide);
  // The questions, and one script as the answer (R161): the provisioner
  // with the answers, the token and (behind WireGuard) the tunnel inside,
  // built on the press and kept nowhere but the file the browser saves.
  // "Just a token" is the old way: the commands to paste, a Mac's included.
  // `again` is a node already here (R177): the form opens on its answers,
  // its name fixed, its secrets left out (the node keeps them), and the
  // script it makes carries that node's id and runs on its machine alone.
  const mintForm = (was = {}, again = null) => {
    // A node that has a machine (B637): a pending one never ran its script,
    // so its new one is a first enrollment, worded and checked as one.
    const enrolled = !!again && again.state !== "pending";
    // WireGuard reach and the Tailscale door have no walk on record (R48):
    // offered with Offer dev features on, marked so.
    const dev = !!state?.settings?.settings?.offer_unvetted?.value;
    document.getElementById("ndTitle").textContent = again ? `Enroll ${again.name} again` : "Enroll a node";
    boxWidth(false);
    body.innerHTML = `<div class="field">
        <div class="prefrow ctlrow">
          <div class="setrow col ctlrow">${lbl("ndEnName", "Name")}
            <input id="ndEnName" maxlength="60" autocomplete="off" placeholder="buildbox"></div>
          <div class="setrow col ctlrow">${lbl("ndEnUser", "Jobs run as",
            "the account the provisioner makes and every job runs as. bb unless that name is taken on the machine")}
            <input id="ndEnUser" maxlength="32" autocomplete="off" spellcheck="false"
              value="bb"></div>
          <div class="setrow col ctlrow">${lbl("ndEnSystem", "System",
            "what the machine runs. The script is built for it and refuses another machine by name; a system marked dev has not been walked on a node yet, and is offered with Offer dev features on")}
            <select id="ndEnSystem">${optionList((nodesSystems.length ? nodesSystems : [{id: "ubuntu", name: "Ubuntu 24.04 or later", vetted: true}])
              .map(s => [s.id, s.vetted ? s.name : devOpt(s.name)]))}</select></div>
        </div>
        <div class="hint" id="ndEnSysWhy" hidden></div>
        <label class="ndcap"><input type="checkbox" id="ndEnSess" checked> Claude sessions run on it</label>
        <label class="ndcap"><input type="checkbox" id="ndEnHost"> Hosting only: it runs containers sent to it, and nothing of it comes back</label>
        <div class="hint" id="ndEnHostHint" hidden>No project's code, no sessions and no bb go to it; its agent may ask the controller for its own jobs and nothing else. For a public box such as a cloud VPS.</div>
        <label class="ndcap" id="ndEnFwRow" hidden><input type="checkbox" id="ndEnFw" checked> Take in only 80 and 443</label>
        <div class="hint" id="ndEnFwHint" hidden>A firewall on the machine drops everything else coming in, a port a container publishes included, so nginx is the way to a container. Port 22 stays open unless the SSH door closes it. Going out is left alone.</div>
        <div class="setrow col ctlrow">${lbl("ndEnDoor", "SSH door",
          "a way in for ssh, switched on and off from the node's row. cloudflared publishes the machine's port 22 at a hostname of its own, with a tunnel token from Zero Trust" + (dev ? "; Tailscale joins the machine to your tailnet with an auth key and answers ssh there, with no public name" : ""))}
          <select id="ndEnDoor">
            <option value="">none</option>
            <option value="cloudflared">cloudflared: port 22 at a hostname</option>${dev ? `
            <option value="tailscale">${devOpt("Tailscale: ssh on the tailnet")}</option>` : ""}
          </select></div>
        <div class="setrow col ctlrow" id="ndEnDoorHostRow" hidden>${lbl("ndEnDoorHost", "The door's hostname",
          "a public hostname of its own on the tunnel (not the controller's), set in Zero Trust to go to ssh://localhost:22")}
          <input id="ndEnDoorHost" autocomplete="off" spellcheck="false" placeholder="ssh-vps.example.com"></div>
        <div class="setrow col ctlrow" id="ndEnDoorSecretRow" hidden>${lbl("ndEnDoorSecret", "The door's secret",
          (dev ? "cloudflared's tunnel token, or a Tailscale auth key." : "cloudflared's tunnel token.") + " It rides in the script until the script has run, then leaves it; the node keeps it")}
          <input id="ndEnDoorSecret" type="password" autocomplete="off" spellcheck="false"></div>
        <label class="ndcap" id="ndEnDoorCloseRow" hidden><input type="checkbox" id="ndEnDoorClose"> Close port 22 to the internet once the door is up</label>
        <div class="hint" id="ndEnDoorHint" hidden>Who gets to the door is the tunnel's own say (Cloudflare Access${dev ? ", or the tailnet's ACLs" : ""}); the machine's keys decide after that. Leave port 22 open until you have come in through the door once.</div>
        <label class="ndcap"><input type="checkbox" id="ndEnVm"> VM host: run virtual machines on it</label>
        <div class="hint" id="ndEnVmHint" hidden>KVM through libvirt, installed once it has enrolled. It needs /dev/kvm: on a VM, its host passes virtualization through (CPU mode host-passthrough). Its Features section on this page installs and removes it later too.</div>
        <label class="ndcap"><input type="checkbox" id="ndEnNginx"> Put nginx on it once it is enrolled</label>
        <div class="hint" id="ndEnNginxHint" hidden>BuilderBot's own reverse proxy, deployed the moment the node enrolls, with the routes and certificate the nginx page holds for it (set them there first or after).</div>
      </div>
      <div class="field">
        <div class="setrow col ctlrow">${lbl("ndEnReach", "Reaches the controller",
          "how the machine dials in. " + (dev ? "Through WireGuard, the config your router made for it goes inside the script, and only the controller is routed through the tunnel. " : "") + "Through a public hostname, a tunnel at home (Cloudflare Tunnel, Tailscale Funnel, ngrok, frp) publishes the controller at a name and the machine dials that: nothing on your router changes and it never learns your address")}
          <select id="ndEnReach">
            <option value="lan">on this network</option>${dev ? `
            <option value="wireguard">${devOpt("WireGuard")}</option>` : ""}
            <option value="public">a public hostname (a tunnel from home)</option>
          </select></div>
        <div class="setrow col ctlrow">${lbl("ndEnCtl", "Controller's address",
          "the URL the machine dials. " + (dev ? "Behind WireGuard, the controller's address on your network, which the tunnel routes to. " : "") + "Through a public hostname, the name the tunnel publishes, as https://bb.example.com")}
          <input id="ndEnCtl" autocomplete="off" spellcheck="false" value="${esc(location.origin)}"></div>
        <div class="hint" id="ndEnCfHint" hidden>Hosting only, and no sessions: the controller cannot reach back through the tunnel. The machine verifies the hostname's public certificate and never sees your home address.</div>
        <div class="setrow col ctlrow" id="ndEnWgRow" hidden>${lbl("ndEnWgText", "WireGuard config",
            "the .conf your router made for this machine: choose the file, or paste what is in it. Only the controller's address is routed through it on the machine")}
          <input type="file" id="ndEnWg" accept=".conf,text/plain" aria-label="choose the WireGuard config file">
          <textarea id="ndEnWgText" rows="7" spellcheck="false" autocomplete="off"
            placeholder="[Interface]&#10;PrivateKey = …&#10;Address = 10.6.0.5/32&#10;&#10;[Peer]&#10;PublicKey = …&#10;Endpoint = home.example.net:51820"></textarea></div>
      </div>
      <div class="field"><div class="hint">${enrolled
        ? "A new script for this node: run it again on the same machine, as root, to set it up afresh or change what it reaches the controller through. It carries no secret (the node keeps its WireGuard config and its door's); a secret pasted here replaces the node's. It refuses to run on another machine, and so does the controller."
        : "The script carries a token good once, for a day, and runs as root on a Linux machine."}</div></div>
      ${dlgFoot(`<button type="button" id="ndEnCancel">Cancel</button>`,
        `<button type="button" id="ndEnTok">Just a token</button><button type="button" class="primary" id="ndEnGo">Make the script</button>`)}`;
    const $b = sel => body.querySelector(sel);
    if (again){
      const c = again.config || {};
      was = {"#ndEnName": again.name, "#ndEnUser": c.user || "bb",
             "#ndEnSess": !c.host_only, "#ndEnHost": !!c.host_only, "#ndEnNginx": !!c.nginx,
             "#ndEnReach": c.tunnel?.kind === "public" ? "public" : c.tunnel?.kind === "wireguard" ? "wireguard" : "lan",
             "#ndEnCtl": c.tunnel?.kind === "public" && c.tunnel.host ? `https://${c.tunnel.host}` : location.origin,
             "#ndEnDoor": c.door?.kind || "", "#ndEnDoorHost": c.door?.host || "", ...was};
    }
    for (const [k, v] of Object.entries(was)) if ($b(k) && v !== undefined)
      $b(k)[typeof v === "boolean" ? "checked" : "value"] = v;
    if (again) $b("#ndEnName").disabled = true;
    const reach = $b("#ndEnReach");
    // Hosting only takes sessions with it: the box is to run containers.
    // Through a public hostname it is so by construction (R170): the
    // switch is ticked and held, and the address field asks for the name.
    // A system marked dev says so under the pulldown, with why it is not
    // walked where it cannot be here (R97, R102).
    const sysWhy = () => {
      const s = nodesSystems.find(x => x.id === $b("#ndEnSystem")?.value);
      const dev = s && !s.vetted;
      $b("#ndEnSysWhy").innerHTML = dev ? `${devMark().trim()} ${esc(s.why || "not walked on a real machine yet: it may need a hand")}` : "";
      $b("#ndEnSysWhy").hidden = !dev;
    };
    if ($b("#ndEnSystem")){ $b("#ndEnSystem").addEventListener("change", sysWhy); sysWhy(); }
    const host = $b("#ndEnHost"), sess = $b("#ndEnSess");
    const showHost = () => {
      const cf = reach.value === "public";
      if (cf) host.checked = true;
      host.disabled = cf;
      $b("#ndEnHostHint").hidden = $b("#ndEnFwRow").hidden = !host.checked;
      $b("#ndEnFwHint").hidden = !host.checked || !$b("#ndEnFw").checked;
      $b("#ndEnCfHint").hidden = !cf;
      sess.disabled = host.checked;
      if (host.checked) sess.checked = false;
    };
    $b("#ndEnFw").onchange = showHost;
    $b("#ndEnVm").onchange = () => { $b("#ndEnVmHint").hidden = !$b("#ndEnVm").checked; };
    const ngx = $b("#ndEnNginx");
    ngx.onchange = () => { $b("#ndEnNginxHint").hidden = !ngx.checked; };
    const door = $b("#ndEnDoor");
    const showDoor = () => {
      $b("#ndEnDoorHostRow").hidden = door.value !== "cloudflared";
      $b("#ndEnDoorSecretRow").hidden = $b("#ndEnDoorCloseRow").hidden = $b("#ndEnDoorHint").hidden = !door.value;
    };
    door.onchange = showDoor;
    showDoor();
    const showWg = () => {
      $b("#ndEnWgRow").hidden = reach.value !== "wireguard";
      const ctl = $b("#ndEnCtl");
      if (reach.value === "public" && /^https?:\/\/(\d+\.|localhost|\[)/.test(ctl.value)) ctl.value = "https://";
      else if (reach.value !== "public" && ctl.value === "https://") ctl.value = location.origin;
      // The hostname the controller's own tunnel publishes (R176), filled
      // in where the settings have one and nothing has been typed yet.
      const own = state?.settings?.settings?.tunnel_host?.value;
      if (reach.value === "public" && own && ctl.value === "https://") ctl.value = `https://${own}`;
      showHost();
    };
    // Make the script wakes once a WireGuard way in has its config (the
    // operator, 18 Oct): chosen or pasted.
    const goReady = () => { const g = $b("#ndEnGo");
      if (g && !g.dataset.busy) g.disabled = reach.value === "wireguard" && !$b("#ndEnWgText").value.trim() && !enrolled; };
    reach.onchange = () => { showWg(); goReady(); };
    host.onchange = showHost;
    $b("#ndEnWgText").addEventListener("input", goReady);
    showWg();
    goReady();
    // A file chosen lands in the box, which is what is sent: one place to
    // read it, change it, or paste it instead.
    $b("#ndEnWg").onchange = async e => {
      const f = e.target.files?.[0];
      if (f) $b("#ndEnWgText").value = await f.text();
      goReady();
    };
    // No focus, like every other dialog here: on a phone it would raise the
    // keyboard over the box it just opened.
    $b("#ndEnCancel").onclick = shut;
    const answers = () => ({name: $b("#ndEnName").value,
      // The account rides along, so the row says the right one before the
      // machine exists and the command below carries it. The record follows
      // whatever the agent reports at enrollment either way.
      user: $b("#ndEnUser").value.trim() || "bb",
      system: $b("#ndEnSystem")?.value || "ubuntu"});
    // What was typed comes back after a refusal: a redraw to its defaults
    // lost the name and the account on every one (B331's shape).
    const keep = () => ({"#ndEnName": $b("#ndEnName").value, "#ndEnUser": $b("#ndEnUser").value, "#ndEnSystem": $b("#ndEnSystem")?.value,
      "#ndEnSess": $b("#ndEnSess").checked, "#ndEnHost": $b("#ndEnHost").checked, "#ndEnFw": $b("#ndEnFw").checked, "#ndEnVm": $b("#ndEnVm").checked, "#ndEnNginx": ngx.checked,
      "#ndEnDoor": door.value, "#ndEnDoorHost": $b("#ndEnDoorHost").value, "#ndEnDoorClose": $b("#ndEnDoorClose").checked,
      "#ndEnReach": reach.value, "#ndEnCtl": $b("#ndEnCtl").value,
      "#ndEnWgText": $b("#ndEnWgText").value});
    const go = $b("#ndEnGo");
    go.onclick = () => pressing(go, async () => {
      const kept = keep();
      const conf = $b("#ndEnWgText").value;
      if (reach.value === "wireguard" && !conf.trim() && !enrolled){
        notify("choose the WireGuard config your router made for this machine, or paste it in", true); return;
      }
      busy(go, "Making");
      const r = await nodeAct({action: "enroll", script: true, ...answers(), ...(again ? {node: again.id} : {}),
        sessions: $b("#ndEnSess").checked && !$b("#ndEnHost").checked, reach: reach.value,
        host_only: $b("#ndEnHost").checked, nginx: ngx.checked,
        firewall: $b("#ndEnHost").checked && $b("#ndEnFw").checked,
        features: $b("#ndEnVm").checked ? ["vmhost"] : [],
        door: door.value, door_host: $b("#ndEnDoorHost").value.trim(),
        door_secret: $b("#ndEnDoorSecret").value.trim(), door_close22: $b("#ndEnDoorClose").checked,
        controller: $b("#ndEnCtl").value.trim(),
        wg_conf: reach.value === "wireguard" ? conf : ""});
      if (r.error){ mintForm(kept, again); return; }
      mintScript(r);
      nodesRev++; drawPanes();              // the pending row joins the picker
    });
    const tok = $b("#ndEnTok");
    tok.onclick = () => pressing(tok, async () => {
      const kept = keep(), a = answers();
      busy(tok, "Minting");
      const r = await nodeAct({action: "enroll", ...a, host_only: $b("#ndEnHost").checked, nginx: ngx.checked,
                               ...(again ? {node: again.id} : {})});
      if (r.error){ mintForm(kept, again); return; }
      // The URL the node should dial: this page's origin, which is the only
      // address the browser knows the controller by. A proxy in front is the
      // operator's to substitute.
      mintToken({name: a.name || "node", token: r.token, url: location.origin, user: a.user});
      nodesRev++; drawPanes();
    });
    $b("#ndEnName").onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); go.click(); }
    };
  };
  // The script, saved the moment it arrives and again from the button: it
  // lives in this dialog and nowhere else, so closing it is the end of it.
  const mintScript = (r) => {
    document.getElementById("ndTitle").textContent = `${r.filename}: run it on the machine`;
    boxWidth(true);
    const url = URL.createObjectURL(new Blob([r.script], {type: "text/x-shellscript"}));
    body.innerHTML = `<div class="field ndtoken">
        <div class="hint">Copy it to the machine and run it once, as root. It ${
          r.reach === "wireguard" ? `brings the tunnel up as ${esc(r.tunnel_addr)}, checks the controller answers through it, `
          : r.reach === "public" ? "checks the controller answers at its hostname, " : ""}provisions the machine and enrolls it; the row goes live when it is done.</div>
        <pre class="ndcmd">sudo bash ${esc(r.filename)}</pre>
        <div class="hint">It holds a token good once, until ${esc(new Date(r.expires * 1000).toLocaleString())}${
          r.reach === "wireguard" ? ", and the machine's WireGuard private key until it has run: once the node has enrolled it takes the WireGuard config out of itself and keeps the rest, to change and run again" : ""}.</div>
      </div>${r.home ? `
      <div class="field ndtoken">
        <label class="lbl">${r.reach === "public" ? "At home, on the tunnel" : "On your router"}</label>
        <pre class="ndcmd" id="ndHome">${esc(r.home)}</pre>
      </div>` : ""}
      ${dlgFoot(`<button type="button" id="ndTokDone">Done</button>`, `<button type="button" class="primary" id="ndScriptGet">Download ${esc(r.filename)}</button>`)}`;
    const save = () => Object.assign(document.createElement("a"), {href: url, download: r.filename}).click();
    body.querySelector("#ndScriptGet").onclick = save;
    save();
    body.querySelector("#ndTokDone").onclick = () => { URL.revokeObjectURL(url); shut(); };
  };
  const mintToken = (m) => {
    document.getElementById("ndTitle").textContent = `${m.name}: enroll it with one of these`;
    boxWidth(true);
    body.innerHTML = `<div class="field ndtoken">
        <div class="hint">Shown once. On a fresh Linux machine, as root:</div>
        <pre class="ndcmd">curl -fsSL -H 'Authorization: Bearer ${esc(m.token)}' '${esc(m.url)}/api/v1/agent/download?what=provisioner' -o provision-linux.sh
sudo bash provision-linux.sh --controller ${esc(m.url)} --token ${esc(m.token)}${
          m.user && m.user !== "bb" ? ` --user ${esc(m.user)}` : ""}</pre>
${state?.settings?.settings?.offer_unvetted?.value ? `
        <div class="hint">On a Mac, as yourself <span class="pill">dev</span>:</div>
        <pre class="ndcmd">curl -fsSL -H 'Authorization: Bearer ${esc(m.token)}' '${esc(m.url)}/api/v1/agent/download?what=provisioner-macos' -o provision-macos.sh
bash provision-macos.sh --controller ${esc(m.url)} --token ${esc(m.token)}</pre>` : ""}
        <div class="hint">Or the agent alone, where python3 exists:</div>
        <pre class="ndcmd">curl -fsSL -H 'Authorization: Bearer ${esc(m.token)}' ${esc(m.url)}/api/v1/agent/download -o /usr/local/sbin/builderbot-agent
chmod 755 /usr/local/sbin/builderbot-agent
builderbot-agent enroll --controller ${esc(m.url)} --token ${esc(m.token)}${
          m.user && m.user !== "bb" ? ` --user ${esc(m.user)}` : ""}</pre>
      </div>
      <div class="foot"><span class="sp"></span>
        <button type="button" id="ndTokDone">Done</button></div>`;
    body.querySelector("#ndTokDone").onclick = shut;
  };
  // ---- a machine to enroll, before there is one -------------------------
  // The XML Unraid needs for a sandbox VM, rendered per VM rather than
  // copied: the uuid, the nvram file named after it and the MAC belong to
  // one machine, and a second VM wearing them answers to the first one's
  // address and writes over its firmware variables. The generator is
  // vmtemplate.py, over the same nodes/unraid-vm.xml the repository keeps.
  //
  // The two identities are fields rather than surprises. Unraid mints its own
  // pair when the VM is made in Form view: the nvram file on disk is named
  // after its uuid, and any DHCP reservation was made against its MAC, so a
  // minted pair is right for a machine that does not exist yet and Unraid's
  // is right the moment it does. Blank mints one.
  const vmDraft = {hv: "unraid", name: "bb-sandbox", cores: 6, memory_gb: 16,
                   disk_gb: 200, iso: "ubuntu-26.04-live-server-amd64.iso",
                   vmid: 9000, uuid: "", mac: ""};
  // The picker's own list, from the server: which hypervisors have a
  // template here, what each hands back, and which identity fields it takes.
  let vmKinds = null;
  const vmForm = (made) => {
    document.getElementById("ndTitle").textContent = "Create a sandbox VM";
    boxWidth(!!made);
    const f = (k, label, help, extra = "") =>
      `<div class="setrow col ctlrow">${lbl("vm_" + k, label, help)}
        <input id="vm_${k}" data-vk="${k}" autocomplete="off" spellcheck="false"
          value="${esc(String(vmDraft[k]))}"${extra}></div>`;
    const kinds = vmKinds || [{id: "unraid", label: "Unraid", wants: ["uuid", "mac"],
                              mac_prefix: "52:54:00", artifact: "domain XML"}];
    const kind = kinds.find(k => k.id === vmDraft.hv) || kinds[0];
    const takes = k => (kind.wants || []).includes(k);
    body.innerHTML = `<div class="field vmform">
        <div class="hint">Pick where it runs; the machine is written the same everywhere.</div>
        <div class="setrow col ctlrow">${lbl("vm_hv", "Runs on")}
          <select id="vm_hv" data-vk="hv">${kinds.map(k =>
            `<option value="${esc(k.id)}"${k.id === kind.id ? " selected" : ""}>${
              k.dev ? devOpt(esc(k.label)) : esc(k.label)}</option>`).join("")}</select></div>
        <div class="prefrow ctlrow">
          ${f("name", "Name", "the machine's name, and the folder its disk goes in")}
          ${f("cores", "Cores", "", ' type="number" min="1" max="64"')}
          ${f("memory_gb", "Memory GiB", "", ' type="number" min="1" max="512"')}
          ${f("disk_gb", "Disk GiB", kind.id === "unraid"
              ? "set in Unraid's own form: the XML only names the file" : "",
              ' type="number" min="8" max="8192"')}
          ${takes("vmid") ? f("vmid", "VM id", "Proxmox numbers its machines, 100 and up",
              ' type="number" min="100"') : ""}
        </div>
        ${f("iso", "Installer ISO", "a file you have already put where that manager keeps them. Ubuntu Server is the tested one")}
        <div class="prefrow ctlrow">
          ${takes("uuid") ? f("uuid", "UUID",
              "blank mints one. Made the VM already? Paste the manager's, or its firmware settings are left behind") : ""}
          ${f("mac", "MAC", `blank mints one in ${kind.mac_prefix}, which is the range this one accepts`)}
        </div>
      </div>
      ${made ? `<div class="field vmmade">
        <div class="hint">${esc(made.label)}: its own${made.uuid && takes("uuid")
          ? ` uuid <code>${esc(made.uuid)}</code> and` : ""} MAC
          <code>${esc(made.mac)}</code>: never a second machine's.</div>
        <pre class="ndcmd vmxml" id="vmXml">${esc(made.text)}</pre>
        <ol class="vmsteps">${(made.steps || []).map(x =>
          `<li>${esc(x)}</li>`).join("")}</ol>
      </div>` : ""}
      ${dlgFoot(`<button type="button" id="vmCancel">${made ? "Done" : "Cancel"}</button>`,
        `<button type="button" class="primary" id="vmGo">${made ? "Generate another" : "Generate"}</button>`,
        made ? `<button type="button" id="vmCopy">Copy</button>` : "")}`;
    body.querySelectorAll("[data-vk]").forEach(el => {
      el.oninput = () => { vmDraft[el.dataset.vk] = el.value; };
    });
    // Switching manager redraws the form: which fields it takes differ, and
    // so does the range a MAC has to be in: one typed for the old one would
    // be refused, so it goes back to being minted.
    const hvSel = body.querySelector("#vm_hv");
    if (hvSel) hvSel.onchange = () => {
      vmDraft.hv = hvSel.value;
      const k = (vmKinds || []).find(x => x.id === vmDraft.hv);
      if (k && vmDraft.mac && !vmDraft.mac.toLowerCase().startsWith(k.mac_prefix.toLowerCase()))
        vmDraft.mac = "";
      vmForm(null);
    };
    body.querySelector("#vmCancel").onclick = shut;
    const copy = body.querySelector("#vmCopy");
    if (copy) copy.onclick = async () => {
      // The clipboard API wants a secure context; over plain http the
      // selection route is what works, the same as the deploy key's Copy.
      const pre = body.querySelector("#vmXml");
      try{ await navigator.clipboard.writeText(pre.textContent); }
      catch(e){
        const r = document.createRange(); r.selectNodeContents(pre);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        document.execCommand("copy");
      }
      notify(`the ${made.artifact} is on the clipboard`);
    };
    const go = body.querySelector("#vmGo");
    go.onclick = () => pressing(go, async () => {
      busy(go, "Generating");
      const r = await nodeAct({action: "vm-xml", hv: vmDraft.hv, name: vmDraft.name,
                              cores: Number(vmDraft.cores) || 0,
                              memory_gb: Number(vmDraft.memory_gb) || 0,
                              disk_gb: Number(vmDraft.disk_gb) || 0,
                              vmid: Number(vmDraft.vmid) || 0,
                              iso: vmDraft.iso, uuid: vmDraft.uuid, mac: vmDraft.mac});
      if (r.catalog) vmKinds = r.catalog;     // the picker's list, on any answer
      if (r.error){ vmForm(null); return; }   // nodeAct has said why
      vmForm(r);
    });
  };
  const openVm = async () => {
    modal.hidden = false;
    vmForm(null);
    // The list of managers comes from the server; it is the templates that
    // are actually shipped, not a copy of them here. Asked once per dialog,
    // and the form redraws with the real picker when it lands.
    if (!vmKinds){
      const r = await nodeAct({action: "vm-xml", hv: vmDraft.hv});
      // Only onto the VM form it was asked for: closed by then and another
      // form opened in the same box (Enroll), a late catalog painted over
      // it and took what was typed (B424).
      if (r.catalog){ vmKinds = r.catalog;
        if (!modal.hidden && body.querySelector("#vmGo") && !body.querySelector(".vmmade")) vmForm(null); }
    }
  };
  const openEnroll = () => { modal.hidden = false; mintForm(); };
  // The backdrop closes it, like every other dialog on the page. Not while
  // the token is up: that is the one thing here shown once, and closing it by
  // a stray click on the room around it would lose the command.
  modal.onclick = e => {
    if (e.target === modal && !body.querySelector(".ndtoken")) shut();
  };
  return {modal, body, shut, mintForm, vmForm, openVm, openEnroll};
}

function wireNodesTab(root){
  wireSignin(root);
  wireCharts(root);
  root.querySelectorAll("[data-ndphone]").forEach(b => b.onclick = () => { phNode = b.dataset.ndphone; openPhoneTab(); });
  root.querySelectorAll("[data-ndrunner]").forEach(b => b.onclick = () => openRunnerTab(b.dataset.ndrunner));
  root.querySelectorAll("[data-ndproj]").forEach(b => b.onclick = () =>
    nodeProjectRemove(b, b.dataset.ndproj, b.closest("[data-node]")?.dataset.node || ""));
  const pick = root.querySelector("#ndPick");
  if (pick) pick.onchange = () => { nodesPick = pick.value; nodesFocus = null;
                                    nodesRev++; drawPanes(); };
  // The root asks answer through the phone's endpoint, which holds the one
  // list of asks; phFetch redraws this tab when the answer comes back.
  root.querySelectorAll("[data-rallow]").forEach(b => b.onclick = () => {
    b.disabled = true; b.textContent = "running";
    phFetch({action: "allow", id: Number(b.dataset.rallow)});
  });
  root.querySelectorAll("[data-rdeny]").forEach(b => b.onclick = () =>
    phFetch({action: "deny", id: Number(b.dataset.rdeny)}));
  const {modal, body, shut, mintForm, vmForm, openVm, openEnroll} = ndDialogs();
  const vm = root.querySelector("#ndVm");
  if (vm) vm.onclick = openVm;
  const en = root.querySelector("#ndEnroll");
  if (en) en.onclick = openEnroll;
  wireSections(root);
  root.querySelectorAll(".ndrow").forEach(box => {
    const id = box.dataset.node;
    // The driver is the Toolchains tab's row (R102): this opens it on the node.
    box.querySelectorAll("[data-ndtc]").forEach(b => b.onclick = () => openToolchainsOn(b.dataset.ndtc));
    box.querySelectorAll("[data-ndag]").forEach(b => b.onclick = () => openAgentsOn(b.dataset.ndag));
    box.querySelectorAll("[data-nd]").forEach(b => b.onclick = () => pressing(b, async () => {
      const act = b.dataset.nd;
      if (act === "disable" || act === "enable"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (act === "disable" && !confirm(`Disable ${name}?\n\nIt stays enrolled and keeps its configuration, but no project can add it, `
              + "no picker offers it, and it is handed no work or session until you press Enable.")) return;
        busy(b, act === "disable" ? "Disabling" : "Enabling");
        const j = await nodeAct({action: act, id});
        if (j.error) notify(j.error, true);
        await loadNodes();
        return;
      }
      if (act === "unenroll"){
        const n = (nodesList || []).find(x => x.id === id);
        if (n) openUnenroll(n);
        return;
      }
      if (act === "retire"
          && !confirm("Remove this node from every list? Its containers and "
                      + "its data stay on the machine; the row is kept as "
                      + "history.")) return;
      if (act === "uninstall"
          && !confirm("Uninstall BuilderBot from this machine?\n\nThe agent, its accounts, "
                      + "mounts and runners are removed. Docker and the shares stay. "
                      + "Enrolling it again starts from scratch.")) return;
      // A reboot ends every session on the node, so the press names them,
      // as Update agent's does; a shutdown also does not come back by itself.
      if (act === "lockdown"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(`Lock down ${name}?\n\nFrom now it may ask this controller for nothing but the job that stops `
              + "every container there, its nginx with them, keeps them from starting at a boot and shuts its SSH door. "
              + "Its credential is revoked when that job ends, or in five minutes if the box never answers, and the node is removed.\n\n"
              + "If the box itself may be taken over, also power it off from its provider's console: that stop does not need the agent.")) return;
      }
      if (act === "reboot" || act === "poweroff"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        const here = (state?.sessions || []).filter(x => x.node_id === id);
        const mine = here.filter(x => agentOfSession(tmuxBase(x.name)));
        const open = here.length
          ? `It ends the ${here.length} session${here.length === 1 ? "" : "s"} open there`
            + `${mine.length ? ` (${mine.length} of them a ${agentsWord(mine.map(x => x.name))} conversation)` : ""}; transcripts are kept. `
          : "";
        if (!confirm(act === "reboot"
              ? `Reboot ${name}?\n\n${open}Whatever is running there stops; the agent dials in again when the machine is back up.`
              : `Shut down ${name}?\n\n${open}It does not come back on its own: switch it on from its console or its hypervisor.`)) return;
      }
      // An agent update RESTARTS the agent, and until B107 is fixed that
      // takes every session on the node with it: the ttyds, their tmux
      // servers and the Claude processes inside them are all in the agent's
      // systemd cgroup, so systemd's default kill reaches the lot. Said
      // before the press, naming what is open there, because the operator
      // who pressed this lost two conversations mid-work with no warning.
      if (act === "update-agent"){
        const here = (state?.sessions || []).filter(x => x.node_id === id);
        const mine = here.filter(x => agentOfSession(tmuxBase(x.name)));
        if (here.length && !confirm(
              `Update the agent on ${
                (nodesList || []).find(n => n.id === id)?.name || "this node"}?\n\n`
              + `This ends the ${here.length} session`
              + `${here.length === 1 ? "" : "s"} open there`
              + `${mine.length ? ` (${mine.length} of them a ${agentsWord(mine.map(x => x.name))} conversation)` : ""}`
              + `. Transcripts are kept; whatever they were running stops.`)) return;
      }
      if (act === "gpu-display"
          && !confirm(`Set up the GPU display on ${(nodesList || []).find(n => n.id === id)?.name || "this node"}?\n\n`
                      + "This installs the NVIDIA driver and a headless X server on the card, which "
                      + "takes minutes, and the driver takes the card only after a reboot: the row "
                      + "says when to press Reboot.")) return;
      // Leaving the synced copy (R164) ends the sessions, as a reboot does;
      // cleaning up removes the copies, which only the drain allows.
      if (act === "sync-stop"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        const here = (state?.sessions || []).filter(x => x.node_id === id);
        if (!confirm(`Stop syncing ${name}?\n\n`
              + (here.length ? `This ends the ${here.length} session${here.length === 1 ? "" : "s"} open there; transcripts are kept. ` : "")
              + "No session starts there while it sends up what is left; then Clean up /workspace removes its copies.")) return;
      }
      if (act === "sync-clean"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(`Remove the project copies on ${name}?\n\n`
              + "Everything there has reached the controller. The node then holds no projects until it moves to a synced copy again.")) return;
      }
      if (act === "host-only"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(`Make ${name} hosting only?\n\nIt keeps running the containers sent to it. `
              + "No project may list it, no session or synced copy runs there, and its agent may ask "
              + "the controller for nothing but its own jobs. A project that lists it now has to be "
              + "moved off it first.")) return;
      }
      if (act === "discard"){
        const n = (nodesList || []).find(x => x.id === id);
        if (!confirm(`Discard ${n?.name || "this row"}?\n\nNothing has enrolled with its script, so the row goes outright and the script it was made for stops working.`)) return;
      }
      if (act === "reenroll"){
        const n = (nodesList || []).find(x => x.id === id);
        if (n){ modal.hidden = false; mintForm({}, n); }
        return;
      }
      if (act === "door" && b.dataset.on === "0"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(`Shut the SSH door on ${name}?\n\nNothing reaches its port 22 through the tunnel until it is opened again from here.`)) return;
      }
      if (act === "feature" && b.dataset.op === "remove"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(b.dataset.feature === "vmhost"
              ? `Uninstall VM host from ${name}?\n\nThe packages BuilderBot added for it come off; what the machine had before stays. It is refused while any VM is still there.`
              : `Turn the hosting firewall off on ${name}?\n\nEvery port this box and its containers publish is reachable from the internet again.`)) return;
      }
      if (act === "cache-clear"
          && !confirm("Clear this node's build caches? Every project's Gradle, "
                      + "npm and snapshot cache there goes; the next build of "
                      + "each re-downloads what it needs.")) return;
      // The verb, said on the button for the round trip and, for the
      // actions whose effect the row cannot see at once: beyond it.
      busy(b, {"update-agent": "Updating", test: "Asking", drain: "Draining",
               online: "Undraining", "cache-clear": "Clearing",
               retire: "Removing", discard: "Discarding", uninstall: "Uninstalling", lockdown: "Locking down", reboot: "Rebooting", poweroff: "Shutting down", "gpu-apply": "Applying",
               paths: "Saving", "check-paths": "Checking", "to-sync": "Moving",
               "sync-stop": "Stopping", "sync-resume": "Resuming", "sync-clean": "Cleaning",
               rename: "Renaming", turns: "Saving",
               feature: b.dataset.op === "remove" ? "Uninstalling" : "Installing"}[act] || "Working");
      if (act === "update-agent"){
        nodesUpdating[id] = Date.now();
        const j = await nodeAct({action: "update-agent", id});
        if (j.current){ delete nodesUpdating[id]; notify(`already on ${j.version}`); }
        // A failed update frees the button at once, never retried: the
        // person reads why on the toast and presses again (B862). A good one
        // keeps it busy until the agent's hello brings the new digest.
        else if (j.ok) notifyJob(j.job, `agent update on ${(nodesList || []).find(n => n.id === id)?.name || "the node"}`,
          r => { if (r.state !== "succeeded"){ delete nodesUpdating[id]; nodesRev++; drawPanes(); } });
        else delete nodesUpdating[id];
        return;
      }
      if (act === "rename"){
        const inp = box.querySelector('.ndname [data-k="name"]');
        const name = (inp ? inp.value : "").trim();
        const was = (nodesList || []).find(x => x.id === id)?.name || "";
        if (!name || name === was) return notify("type the new name first", true);
        const j = await nodeAct({action: "update", id, fields: {name}});
        if (j.error) return notify(j.error, true);
        const c = nodesConf[id]; if (c && c.draft) c.draft.nameText = undefined;
        notify(`${was} is now ${name}. A runner already installed there keeps the label ${was} until it is reinstalled.`);
        return;
      }
      if (act === "sess-revert"){
        const c = nodesConf[id];
        if (c && c.draft) for (const k of ["sessnetOn", "rootAsks", "ctrNet", "portsLocal", "turnsText", "workersText"]) c.draft[k] = undefined;
        nodesRev++; drawPanes();
        return;
      }
      if (act === "sess-save"){
        // The Sessions section's one Save (the operator, 18 Oct): what
        // changed of its switches and numbers, each by its own action, said
        // in one line.
        const n0 = nodesList.find(x => x.id === id) || {}, conf = n0.config || {};
        const val = k => box.querySelector(`[data-k="${k}"]`);
        const said = [];
        busy(b, "Saving");
        const step = async (el, was, body, line) => {
          if (!el) return true;
          const now = el.type === "checkbox" ? el.checked : String(Number(el.value) || 0);
          if (now === was) return true;
          const k = await nodeAct({...body(now), id});
          if (k.error) return false;
          said.push(line(now, k));
          return true;
        };
        const ok = await step(val("turns"), String((n0.turns || {}).limit || 0), v => ({action: "turns", limit: Number(v)}),
                              v => Number(v) ? `at most ${v} Claude session${Number(v) === 1 ? "" : "s"} work here at once` : "no limit on Claude sessions working here at once")
          && await step(val("sessnet"), !!conf.session_net, v => ({action: "session-net", on: v}),
                        v => v ? "sessions started here from now on reach only their own project's containers" : "sessions started here from now on share its network")
          && await step(val("workers"), String(conf.test_workers || 0), v => ({action: "test-workers", workers: Number(v)}),
                        v => Number(v) ? `test runs here may use ${v} worker${Number(v) === 1 ? "" : "s"}` : "test runs here may use every core")
          && await step(val("rootasks"), !conf.no_root, v => ({action: "root-asks", on: v}),
                        v => v ? "a session here may ask for a root command" : "a session here asking for a root command is refused")
          && await step(val("ctrnet"), "container_net" in conf ? !!conf.container_net : !!conf.host_only, v => ({action: "container-net", on: v}),
                        v => v ? "each project's containers here are kept to their own network from the next hello" : "containers here reach each other again from the next hello")
          && await step(val("portslocal"), "ports_local" in conf ? !!conf.ports_local : !!conf.host_only, v => ({action: "ports-local", on: v}),
                        v => v ? "published ports here bind to 127.0.0.1 from the next hello; docker restarts once" : "published ports here bind to every address from the next hello; docker restarts once");
        const c = nodesConf[id];
        if (ok && c && c.draft) for (const k of ["sessnetOn", "rootAsks", "ctrNet", "portsLocal", "turnsText", "workersText"]) c.draft[k] = undefined;
        if (said.length) notify(said.join("; "));
        await loadNodes();
        return;
      }
      if (act === "gpu-apply"){
        // The GPU section's Apply: each switch only where its tick differs
        // from what the node has. The emulator's is a job on the node.
        const n = nodesList.find(x => x.id === id) || {};
        const ge = box.querySelector('[data-k="gpuemu"]'), gc = box.querySelector('[data-k="gpucomp"]');
        const emuWas = /^(up|starting|reboot)/.test(n.reported?.gpu_display || "");
        const compWas = !n.config?.no_gpu_compute;
        const c = nodesConf[id];
        const said = [];
        if (gc && gc.checked !== compWas){
          const k = await nodeAct({action: "gpu-compute", id, on: gc.checked});
          if (k.error) return;
          if (c && c.draft) c.draft.gpuComp = undefined;
          said.push(gc.checked ? "sessions started here from now on may compute on the card"
                               : "sessions started here from now on find no card to compute on");
        }
        if (ge && !ge.disabled && ge.checked !== emuWas){
          const want = ge.checked;
          const k = await nodeAct({action: "gpu-display", id, on: want});
          if (k.error) return;
          // Kept as asked until the node reports the new state, which moves
          // gpuEmuFrom and puts the box on the machine's word again.
          if (c && c.draft){ c.draft.gpuEmu = want; c.draft.gpuEmuFrom = emuWas; }
          said.push(ge.checked ? "setting the emulator up on the card" : "taking the emulator off the card");
        }
        notify(said.length ? said.join("; ") : "nothing changed");
        return;
      }
      if (act === "paths"){
        const inp = box.querySelector('[data-k="paths"]');
        delete nodesCheck[id];             // a new mapping wants a new check
        await nodeAct({action: "paths", id, paths: inp ? inp.value : ""});
        const c = nodesConf[id]; if (c && c.draft) c.draft.pathsText = undefined;
        return;
      }
      if (act === "check-paths"){
        // Roadmap #13. The verdict is kept, not only written on the line:
        // the next heartbeat's repaint drew the row without it (B850).
        nodesCheck[id] = {text: "checking…", warn: false};
        nodesRev++; drawPanes();
        const j = await nodeAct({action: "check-paths", id});
        nodesCheck[id] = {text: j.error || j.why || (j.same ? "the same directory" : "not the same directory"),
                          warn: !j.same};
        nodesRev++; drawPanes();
        return;
      }
      if (act === "test"){
        const out = root.querySelector(`.ndrow[data-node="${CSS.escape(id)}"] .ndtest`);
        if (out){ out.hidden = false; out.textContent = "asking…"; }
        const j = await nodeAct({action: "test", id});
        // Repainted underneath by the loadNodes() in nodeAct: find the
        // row again rather than writing to the one that was replaced.
        const now = root.querySelector(`.ndrow[data-node="${CSS.escape(id)}"] .ndtest`) || out;
        if (!now) return;
        now.hidden = false;
        now.textContent = j.on ? (j.why || "answers, and says it is a sandbox")
                               : (j.why || "no answer");
        now.classList.toggle("warn", !j.on);
        return;
      }
      if (act === "to-sync"){
        const j = await nodeAct({action: "to-sync", id});
        if (j.ok && !j.error) notify("Moved: each project is copied down now");
        return;
      }
      // The door's press says which way (R174); every other verb is its name.
      await nodeAct({action: act, id, ...(act === "door" ? {on: b.dataset.on === "1"} : {}),
                     ...(act === "feature" ? {feature: b.dataset.feature, op: b.dataset.op} : {})});
    }));
    box.querySelectorAll("[data-ndrunner]").forEach(b => b.onclick = () => openRunnerTab(b.dataset.ndrunner));
    box.querySelectorAll("[data-ndvmlan]").forEach(c => c.onchange = async () => {
      const j = await nodeAct({action: "vm-lan", id, on: c.checked});
      if (j.error){ c.checked = !c.checked; notify(j.error, true); }
    });
    wireNodeConf(box, id);
    const pi = box.querySelector('.ndpaths [data-k="paths"]');
    if (pi){
      pi.onfocus = () => { nodesFocus = {id, key: "paths", pos: pi.selectionStart ?? undefined}; };
      pi.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.pathsText = pi.value;
                           nodesFocus = {id, key: "paths", pos: pi.selectionStart ?? undefined}; };
    }
    // ...and the name under Advanced: without it a heartbeat's repaint
    // between typing a new name and pressing Rename put the old one back,
    // and Rename said to type one (B176: nodes.mjs's rename wait timed out
    // on exactly that, now and then).
    const ni = box.querySelector('.ndname [data-k="name"]');
    if (ni){
      ni.onfocus = () => { nodesFocus = {id, key: "name", pos: ni.selectionStart ?? undefined}; };
      ni.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.nameText = ni.value;
                           nodesFocus = {id, key: "name", pos: ni.selectionStart ?? undefined};
                           // Rename wakes on a new name (the operator, 18 Oct).
                           const rn = box.querySelector('[data-nd="rename"]'), v = ni.value.trim();
                           if (rn) rn.disabled = !v || v === (nodesList.find(x => x.id === id)?.name || ""); };
    }
    // The same for the limit on sessions working at once, in the Sessions
    // section: a number is typed across a heartbeat as easily as a path.
    // The update-before-a-session switch is Controller settings' alone:
    // one setting for every node, behind an Apply there. It used to be a
    // checkbox on this section too, written on the click (B257).
    // Each session kept to its own project's network (R79): a draft until
    // the section's Save, like the limit beside it.
    // The Sessions section's drafts: each change wakes its one Save and
    // Revert, which sleep again when every field is back where it was.
    const sessWake = () => { const dirty = nodeSessDirty(nodesList.find(x => x.id === id) || {});
      box.querySelectorAll('[data-nd="sess-save"], [data-nd="sess-revert"]').forEach(x => { x.disabled = !dirty; }); };
    for (const [k, key] of [["sessnet", "sessnetOn"], ["rootasks", "rootAsks"], ["ctrnet", "ctrNet"], ["portslocal", "portsLocal"]]){
      const el = box.querySelector(`[data-k="${k}"]`);
      if (el) el.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft[key] = el.checked; sessWake(); };
    }
    // The GPU section's two switches (R102): drafts until its Apply.
    const ge = box.querySelector('[data-k="gpuemu"]');
    if (ge) ge.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.gpuEmu = ge.checked; };
    const gc = box.querySelector('[data-k="gpucomp"]');
    if (gc) gc.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.gpuComp = gc.checked; };
    const ti = box.querySelector('[data-k="turns"]');
    if (ti){
      ti.onfocus = () => { nodesFocus = {id, key: "turns"}; };
      ti.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.turnsText = ti.value;
                           nodesFocus = {id, key: "turns"}; sessWake(); };
    }
    const wi = box.querySelector('[data-k="workers"]');
    if (wi){
      wi.onfocus = () => { nodesFocus = {id, key: "workers"}; };
      wi.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.workersText = wi.value;
                           nodesFocus = {id, key: "workers"}; sessWake(); };
    }
  });
  // The field that had the caret before this repaint gets it back: the
  // tab redraws on every heartbeat, and a form that drops the caret every
  // 25 seconds is not a form anybody can type into.
  if (nodesFocus && nodesFocus.id){
    const f = nodesFocus;
    const el = root.querySelector(`.ndrow[data-node="${CSS.escape(f.id)}"] ${
      f.i === undefined ? "" : `.ndmount[data-i="${f.i}"] `}[data-k="${CSS.escape(f.key)}"]`);
    // ...only when the repaint took it, which leaves the caret on nothing:
    // one the person moved on (the enroll or VM dialog, another field) stays
    // where they put it, and the memory goes (B848: the rename box, which
    // never forgot, took every keystroke typed in the enroll dialog).
    const at = document.activeElement;
    const lost = !at || at === document.body || !at.isConnected;
    if (el && at !== el && lost){
      el.focus();
      if (el.setSelectionRange && typeof f.pos === "number")
        try{ el.setSelectionRange(f.pos, f.pos); }catch(e){ /* a select has no caret */ }
    }else if (at !== el && !lost) nodesFocus = null;
  }
}
function wireNodeConf(row, id){
  const fold = row.querySelector(".ndconf");
  if (!fold) return;
  const c = nodesConf[id];
  const touch = () => { c.dirty = true; };
  const remember = (el) => {
    const m = el.closest(".ndmount");
    nodesFocus = {id, key: el.dataset.k, i: m ? Number(m.dataset.i) : undefined,
                  pos: el.selectionStart ?? undefined};
  };
  fold.querySelectorAll("[data-k]").forEach(el => {
    el.onfocus = () => remember(el);
    // Forgotten only when the operator left the field, not when a repaint
    // took the field away from under the caret: the browser fires blur for
    // both, and the second is the case this memory exists for.
    el.onblur = () => setTimeout(() => {
      if (el.isConnected && nodesFocus && nodesFocus.id === id && nodesFocus.key === el.dataset.k)
        nodesFocus = null;
    }, 0);
    const on = () => {
      remember(el);
      const k = el.dataset.k;
      const m = el.closest(".ndmount");
      const d = c.draft;
      if (m){
        const mt = d.mounts[Number(m.dataset.i)];
        if (!mt) return;
        if (k === "ro") mt.ro = el.checked;
        else mt[k] = el.value;
      } else if (k.startsWith("store:")){
        d.stores[k.slice(6)] = el.value;
      } else if (k.startsWith("net:")){
        const f = k.slice(4);
        d.network[f] = f === "dns" ? el.value.split(",").map(x => x.trim()).filter(Boolean)
          // A route a line, "TO via VIA" (or "TO VIA"); what does not read as
          // one is kept as typed for the server to refuse by name at Save.
          : f === "routes" ? el.value.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
              const [to, via] = l.replace(/\s+via\s+/, " ").split(/\s+/);
              return {to: to || "", via: via || ""};
            })
          : el.value;
      } else if (k.startsWith("runner:")){
        // The runner's fields are sent with Install, not with Save: they
        // are not part of the storage-and-network record.
        d.runner[k.slice(7)] = el.value;
        return;
      }
      touch();
      // Only the two that change what else is enabled repaint now; a
      // keystroke in a path field does not need the whole tab redrawn.
      if (k === "net:mode" || k === "type"){ nodesRev++; drawPanes(); }
      else {
        // Both editors carry a Save and the status line: one record, two
        // sections, so every copy moves.
        fold.querySelectorAll("[data-nsave]").forEach(b => { b.disabled = false; });
        fold.querySelectorAll("[data-napply]").forEach(x => { x.disabled = true; });
        fold.querySelectorAll(".ndconfstate").forEach(st => {
          st.textContent = "Unsaved: press Save, then Apply.";
          st.className = "state ndconfstate warn";
        });
      }
    };
    el.oninput = on;
    el.onchange = on;
  });
  const add = fold.querySelector("[data-madd]");
  if (add) add.onclick = () => {
    c.draft.mounts.push({type: "nfs", source: "", path: "", ro: false});
    touch(); nodesFocus = {id, key: "source", i: c.draft.mounts.length - 1};
    nodesRev++; drawPanes();
  };
  fold.querySelectorAll("[data-mrm]").forEach(b => b.onclick = () => {
    const i = Number(b.closest(".ndmount").dataset.i);
    c.draft.mounts.splice(i, 1);
    touch(); nodesFocus = null; nodesRev++; drawPanes();
  });
  fold.querySelectorAll("[data-nrunner]").forEach(b => b.onclick = async () => {
    const n = nodesList.find(x => x.id === id);
    const want = b.dataset.nrunner === "install", slot = b.dataset.slot;
    if (!want && !confirm(`Remove the runner ${slot} from ${n?.name || "this node"}?\n\nIt is deregistered `
        + `from its host first; workflows that target its label will wait for a runner.`)) return;
    // The runner's own labels, kept on its record since it was added; new
    // ones typed in an open form apply to the install pressed next.
    const typed = (c.draft.runner?.labels || "").split(",").map(x => x.trim()).filter(Boolean);
    await pressing(b, () => { busy(b, want ? "Installing" : "Removing");
      return nodeAct({action: "runner", id, slot, want, ...(c.addRunner && typed.length ? {labels: typed} : {})}); });
  });
  const showBtn = fold.querySelector("[data-nrunnershow]");
  if (showBtn) showBtn.onclick = () => { c.addRunner = true; nodesRev++; drawPanes(); };
  const cancelBtn = fold.querySelector("[data-nrunnercancel]");
  if (cancelBtn) cancelBtn.onclick = () => { c.addRunner = false; c.draft.runner = undefined; nodesRev++; drawPanes(); };
  const addBtn = fold.querySelector("[data-nrunneradd]");
  if (addBtn) addBtn.onclick = () => pressing(addBtn, async () => {
    busy(addBtn, "Adding");
    const r = await nodeAct({action: "runner-token", id, url: c.draft.runner?.url || "",
                             forge: c.draft.runner?.forge || "", token: c.draft.runner?.token || "",
                             labels: (c.draft.runner?.labels || "").split(",").map(x => x.trim()).filter(Boolean)});
    // The token leaves the page the moment it is handed over, either way;
    // the form rolls up once the runner is on the list.
    if (c.draft.runner) c.draft.runner.token = "";
    if (!r.error){ c.addRunner = false; c.draft.runner = undefined; nodesRev++; drawPanes(); }
  });
  fold.querySelectorAll("[data-nrunnerforget]").forEach(b => b.onclick = () => {
    const slot = b.dataset.slot;
    if (!confirm(`Forget the token for ${slot}?\n\nA runner already registered keeps running; installing or removing one later needs a token again.`)) return;
    pressing(b, async () => { busy(b, "Forgetting");
      const r = await nodeAct({action: "runner-forget", id, slot});
      if (!r.error){ nodesRev++; drawPanes(); } });
  });
  fold.querySelectorAll("[data-nsave]").forEach(save => { save.onclick = () => pressing(save, async () => {
    busy(save, "Saving");
    const r = await nodeAct({action: "config", id, config: c.draft});
    if (!r.error){ c.dirty = false; c.draft = null; nodesRev++; drawPanes(); }
  }); });
  fold.querySelectorAll("[data-napply]").forEach(b => b.onclick = async () => {
    const what = b.dataset.napply;
    const n = nodesList.find(x => x.id === id);
    const desired = n?.config?.desired || {};
    if (what === "network" && !confirm(
        `Apply the network change to ${n?.name || "this node"}?\n\nThe node re-addresses `
        + `itself and must dial back in within three minutes, or it puts the old `
        + `config back on its own. ${desired.network?.mode === "static"
            ? `Static ${desired.network.address}` : "DHCP"}.`)) return;
    if (what === "storage"){
      const gone = (n?.reported?.mounts || []).filter(m => !(desired.mounts || []).some(x => x.path === m.path));
      if (gone.length && !confirm(`Apply storage to ${n?.name || "this node"}?\n\nThis unmounts `
          + `${gone.map(m => m.path).join(", ")} and takes ${gone.length === 1 ? "it" : "them"} `
          + `out of fstab. Directories and data stay.`)) return;
      // Moving a store copies what is in it, which can be tens of gigabytes
      // and take a while, so it is asked about rather than started by a
      // text field losing focus.
      const moving = storeMoves(n);
      if (moving.length && !confirm(`Apply storage to ${n?.name || "this node"}?\n\nThis moves `
          + `${moving.map(m => `${m.role} from ${m.from} to ${m.to}`).join(", and ")}. `
          + `The contents are copied first; the old cop${moving.length === 1 ? "y stays" : "ies stay"} `
          + `for you to remove.`)) return;
    }
    await pressing(b, () => { busy(b, "Applying"); return nodeAct({action: "apply", id, what}); });
  });
}

// Why an idle session's token was not refreshed on this node, as its agent
// said it on its last hello (B419): its complaints went only to the node's
// own journal, which nothing here reads. The newest of the last day, in the
// warning color, with when a token was last kept beside it.
function keepLine(n){
  const k = n.agent?.keep;
  if (!k) return "";
  const day = Date.now() / 1000 - 86400;
  const said = (k.said || []).filter(x => x.at > day);
  if (!said.length) return "";
  const last = said[said.length - 1];
  return `<div class="sub warn ndkeep">session tokens: ${esc(last.msg)}, ${esc(ago(last.at))}${
    said.length > 1 ? ` (and ${said.length - 1} more today)` : ""}${
    k.ok ? `; one was last kept ${esc(ago(k.ok))}` : "; none kept since the agent started"}</div>`;
}
