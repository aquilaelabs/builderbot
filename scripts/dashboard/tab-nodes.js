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
let nodesRev = 0;                // bumped when it changes, so panes repaint
let nodesErr = "";
let nodesAgent = null;           // the agent this controller ships: {digest, version}
let nodesDefault = "";           // the node work nobody bound to one lands on
let nodesPick = "";              // which node the tab is showing, "" until the first draw
// The configuration plane's editor state, per node (docs/nodes.md §12): the
// fold's open flag and the DRAFT the operator is typing. Kept here and not in
// the DOM because the tab repaints on every heartbeat: a field that lived
// only in the row would lose its text every 25 seconds.
const nodesConf = {};
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

async function loadNodes(){
  try{
    const j = await (await fetch("/api/v1/nodes")).json();
    nodesErr = j.error || "";
    nodesList = j.nodes || [];
    nodesAgent = j.agent || null;
    nodesDefault = j.default || "";
  }catch(e){
    nodesErr = String(e);
    nodesList = nodesList || [];
  }
  nodesRev++;
  if (tabs.some(t => t.kind === "nodes")) drawPanes();
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
      title="the driver is installed from this node's Toolchains tab">Install the driver</button>` : ""}
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
  return docSection("nodes", "gpu", "GPU", status, body, {cls});
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
    return `<div class="sub ndtools dim">no toolchains yet: install them from the Toolchains tab</div>`;
  // Held recipes whose system libraries this machine lacks (roadmap R51),
  // said here rather than left for a build to fail on: the store is shared,
  // the libraries are each machine's own, and the Tools tab installs them.
  const unmet = Object.entries(n.reported?.sysdeps?.unmet || {});
  const sys = unmet.length
    ? `<div class="sub ndsys warn">System packages missing for ${unmet.map(([r, ps]) =>
        `${esc(r)} (${esc(ps.join(" "))})`).join(", ")}: install them from the Toolchains tab</div>` : "";
  return `<div class="sub ndtools">${names.slice(0, 8).map(k =>
    `<span class="pill" title="${esc(String(tc[k] || "present"))}">${
      esc(TOOL_LABELS[k] || k)}</span>`).join(" ")}</div>${sys}`;
}

function nodeStatePill(n){
  if (n.state === "pending")
    return `<span class="pill note">waiting for enrollment</span>`;
  const cls = {online: "ok", draining: "warn"}[n.state] || "";
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
function nodeRunnerSection(n, c){
  // One runner per git host on a node (R53): the record's asks and the
  // census's reports, joined by slot, each a row with its own state and
  // buttons; the addbar at the top takes a new one, host, address and
  // token, the way every view adds. A runner the census reports under no
  // slot (an agent from before the list) joins the record's only entry.
  const recs = n.services?.runners || {};
  const reps = (n.reported?.services?.runners || []).map(r =>
    r.slot || Object.keys(recs).length !== 1 ? r : {...r, slot: Object.keys(recs)[0]});
  const slots = [...new Set([...Object.keys(recs), ...reps.map(r => r.slot).filter(Boolean)])];
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
    // The verdict first: "installed" and "will actually pick up a job" are
    // different states, and a runner registered with no listener reads as
    // healthy right up until a workflow sits in "Waiting for a runner".
    const [verdict, vcls] = job
      ? [`${job} now: its job is on the Jobs tab, and the buttons come back when it ends`, "note"]
      : !rep.installed
      ? (failed ? [`install failed ${when(failed.ended)}: ${failed.why || "its job on the Jobs tab says why"}`, "bad"]
        : [want.want ? "install asked for; the node has not reported it yet" : "not installed", ""])
      : rep.busy ? ["running a job right now", "ok"]
      : rep.active ? ["listening: idle, waiting for a job", "ok"]
      : ["installed but NOT listening, so no workflow will reach it: Reinstall runner", "bad"];
    const rowCls = failed && rep.installed && vcls === "ok" ? "warn" : vcls;
    if (rowCls === "bad") worst = "bad"; else if (rowCls === "note" && worst !== "bad") worst = "note";
    const detail = rep.installed
      ? [rep.name ? `registered as ${rep.name}`
           : rep.active ? "" : "its registered name did not come back, so the registration may not have finished",
         rep.labels?.length ? "labels " + rep.labels.join(", ") : ""].filter(Boolean).join(" · ")
      : "";
    // A token is what a reinstall and a removal mint from, so a runner
    // without one (registered before tokens were per runner) says so once,
    // where the two buttons it disables are, rather than as a warning on a
    // runner that is working.
    const noToken = !stored ? (rep.installed ? "no token stored: add one above with this address to reinstall or remove" : "no token stored") : "";
    // A reinstall that failed left the runner standing: its state stays,
    // and what went wrong follows it.
    const late = failed && rep.installed ? ` · reinstall failed ${when(failed.ended)}: ${failed.why || "its job on the Jobs tab says why"}` : "";
    const state = verdict + (detail ? " · " + detail : "") + late + (noToken ? " · " + noToken : "");
    return `<div class="row stack2 ndrun" data-slot="${esc(slot)}"><div class="grow">
        <div class="name"><code>${esc(rep.url || want.url || slot)}</code>${hostOf(want, rep) ? ` <span class="pill">${hostOf(want, rep)}</span>` : ""}${
          rep.busy ? ` <span class="pill note ndrunbusy">running a job</span>` : ""}</div>
        <div class="actbar">
          <span class="state ndrunstate${rowCls ? " " + rowCls : ""}">${esc(state)}</span>
          <button type="button" data-nrunner="install" data-slot="${esc(slot)}" ${busyNow || !stored ? "disabled" : ""}
            title="${why || (stored ? "install the runner here and register it with the stored token"
                                    : "add a token first")}">${
            rep.installed ? "Reinstall runner" : "Install runner"}</button>
          ${stored ? `<button type="button" class="danger" data-nrunnerforget data-slot="${esc(slot)}" ${busyNow ? "disabled" : ""}
            title="drop the stored token and this row; a registered runner keeps running">Forget token</button>` : ""}
          ${rep.installed || want.want ? `<button type="button" class="danger" data-nrunner="remove" data-slot="${esc(slot)}" ${busyNow || !stored ? "disabled" : ""}
            title="${why || (stored ? "deregister it and remove it from this node" : "add a token first")}">Remove runner</button>` : ""}
        </div></div></div>`;
  }).join("");
  // Adding is a button that unrolls the form in its own band, the shape
  // every view adds with; the form is four fields that wrap to the width
  // they have, one per line on a phone, and its own action bar.
  const addbar = c.addRunner ? `<div class="addbar ndrunadd" data-add="runner"><div class="grow">
        <div class="uadd">
          <div class="setrow col">${lbl("", "Repository or organization", "a repository, or an organization for all of its repositories")}
          <input data-k="runner:url" value="${esc(d.runner.url)}" spellcheck="false" autocomplete="off"
            placeholder="https://github.com/your-org" aria-label="repository or organization URL"></div>
          <div class="setrow col">${lbl("", "Host", "GitHub, or act_runner for Gitea, Forgejo and Codeberg")}
          <select data-k="runner:forge" aria-label="host kind">${[["", "from the address"], ["github", "GitHub"], ["gitea", "Gitea or Forgejo"]].map(([v, t]) =>
            `<option value="${v}"${(d.runner.forge || "") === v ? " selected" : ""}>${t}</option>`).join("")}</select></div>
          <div class="setrow col">${lbl("", "Token", "a token that may register runners there. Stored on the controller only")}
          <input data-k="runner:token" type="password" value="${esc(d.runner.token || "")}" spellcheck="false" autocomplete="off"
            placeholder="paste a token" aria-label="runner token"></div>
          <div class="setrow col">${lbl("", "Extra labels", `comma-separated. builderbot, self-hosted, linux, the arch and ${n.name} are always on`)}
          <input data-k="runner:labels" value="${esc(d.runner.labels)}" spellcheck="false" autocomplete="off"
            placeholder="gpu, android" aria-label="labels"></div>
        </div>
        <div class="actbar"><span class="state">Install on the runner's row registers it</span>
          <button type="button" class="stop" data-nrunnercancel>Cancel</button>
          <button type="button" class="primary" data-nrunneradd ${busyNow ? "disabled" : ""}
            title="save the token and add the runner to this node">Add runner</button></div>
      </div></div>`
    : `<div class="addbar" data-add="runner"><button type="button" data-nrunnershow ${busyNow ? "disabled" : ""}
        title="a runner for another git host, or this one's under another address">Add runner</button></div>`;
  const status = !slots.length ? "none" : worst === "bad" ? "attention" : worst === "note" ? "working"
    : reps.some(r => r.busy) ? "busy" : reps.some(r => r.active) ? "listening" : "asked for";
  const pill = {attention: "bad", working: "note", busy: "ok", listening: "ok"}[status] || "";
  // The node-scoped tool's shape, the Phone tab's too (R121 step 5): the
  // state row first, the things below it, the add band, and at the foot
  // what a workflow (or a session) does to reach this node.
  return `<div class="row toolstate"><div class="grow">
        <div class="name">CI runners on ${esc(n.name)} <span class="pill ${pill}">${esc(status)}</span></div>
        <div class="sub">One runner per git host; its labels decide which workflows land here.</div></div></div>
      <div class="field">${addbar}</div>
      ${rows || `<div class="row"><div class="grow"><div class="sub dim ndrunnone">no runner on this node</div></div></div>`}
      <div class="field toolfoot ndrunpin"><div class="hint">${slots.length ? `This node's name pins a job here:
        <pre class="ndcmd">runs-on: [self-hosted, ${esc(n.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 40))}]</pre>`
        : "A workflow reaches this node through a runner added here."}</div></div>`;
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
function nodeDoorRow(n){
  if (n.kind !== "agent") return "";
  const d = n.reported?.door || n.config?.door;
  if (!d?.kind) return "";
  const known = !!n.reported?.door;
  const cmd = d.kind === "cloudflared"
    ? `ssh -o ProxyCommand="cloudflared access ssh --hostname ${esc(d.host || "HOST")}" ${esc(n.config?.user || "bb")}@${esc(d.host || "HOST")}`
    : `ssh ${esc(n.config?.user || "bb")}@${esc(d.host || n.name)}`;
  const state = !known ? "not reported yet" : !d.installed ? "not installed" : d.active ? "open" : "shut";
  return `<div class="field nddoor">
      <div class="actbar"><span class="state">SSH door: ${esc(d.kind)}, ${esc(state)}${
        d.kind === "cloudflared" ? " (Cloudflare Access decides who reaches it)" : " (the tailnet's ACLs decide who reaches it)"}</span><span class="sp"></span>
        ${known && d.installed ? `<button type="button" data-nd="door" data-on="${d.active ? "0" : "1"}" ${n.live ? "" : "disabled"}>${d.active ? "Shut it" : "Open it"}</button>` : ""}</div>
      ${known && d.installed && d.active ? `<pre class="ndcmd">${cmd}</pre>` : ""}
    </div>`;
}

function nodeHostRow(n){
  if (n.kind !== "agent") return "";
  return n.config?.host_only
    ? `<div class="sub">It hosts containers only: no project lists it, no session or synced copy runs here,
        and its agent may ask the controller for nothing but its own jobs, an image shipped to it
        and a container's data in a copy or a move.</div>
       <div><button type="button" data-nd="host-off">Let projects use it again</button></div>`
    : `<div class="sub dim">A node that only runs containers sent to it (a web-facing one) can be made
        hosting only: no code, no sessions, and nothing of it comes back but its own jobs.</div>
       <div><button type="button" data-nd="host-only" ${n.live ? "" : "disabled"}>Make it hosting only</button></div>`;
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
  return docSection("nodes", "projects", "Projects", list.length ? `${list.length}` : "none", body);
}

function nodeSessionsSection(n){
  const se = n.reported?.session;
  const list = n.reported?.sessions || [];
  let status, cls, body;
  if (n.config?.host_only){
    return docSection("nodes", "sessions", "Sessions", "hosting only", nodeHostRow(n) + nodeDoorRow(n) + nodeToolsLine(n), {cls: "ok"});
  }
  if (!se || typeof se !== "object"){
    [status, cls] = ["agent too old", "warn"];
    body = `<div class="sub">Update the agent: this one is too old to run sessions.</div>`;
  } else if (!se.up){
    [status, cls] = ["none", "warn"];
    body = `<div class="sub">${esc(se.why || "no session account: provision it with --session-user")}.
      No Claude session can start here until it is up.</div>`;
  } else {
    const gaps = [];
    if (!se.boot) gaps.push("the agent reports no boot id: Update agent");
    // Whether a session here is kept to its own project (R35): said on the
    // status itself when it is not, since a folded section shows nothing else.
    const iso = n.reported?.isolation;
    const shared = !!iso && !iso.sessions;
    [status, cls] = gaps.length ? ["blocked", "bad"]
      : [`${list.length ? `${list.length} open` : "ready"}${shared ? ", not isolated" : ""}`, shared ? "warn" : "ok"];
    body = `
      <div class="sub">Sessions run here as <code>${esc(se.user || "?")}</code> with ${
        se.claude ? esc(se.claude) : "no Claude Code installed yet"}.</div>
      ${gaps.map(g => `<div class="sub bad">${esc(g)}</div>`).join("")}
      ${!iso ? `<div class="sub dim">Update the agent to know whether sessions here see only their own project.</div>`
        : iso.sessions ? `<div class="sub">Each session sees only its own project.</div>`
        : `<div class="sub warn">Sessions here can read each other's projects: ${esc(iso.why || "this machine cannot build a session's view")}.</div>`}
      ${list.length ? `<div class="sub">open now: ${list.map(s => `<code>${esc(s.name)}</code>`).join(", ")}</div>` : ""}
      ${nodeSyncRow(n)}
      ${nodeSessNetRow(n)}
      ${nodeTurnsRow(n)}`;
  }
  // ...and the node's phone and CI runner, which are tabs of their own
  // (R121): a line at the foot of this section opens them. It was a band
  // between sections, which read as part of Sessions yet stayed when Sessions
  // folded, and sat without the section's inset (the operator, 7 Oct).
  return docSection("nodes", "sessions", "Sessions", status, body + nodeHostRow(n) + nodeDoorRow(n) + nodeToolsLine(n), {cls});
}

// Claude Code on this node: this account's sign-in here (a login is one
// account's on one node, page-signin.js), and where the copy the session
// account runs stands, with the way to the node's Toolchains tab, which
// installs, updates and removes it (R145).
function nodeClaudeSection(n){
  const cc = state?.claude_code || {};
  const me = cc.nodes?.[n.id] || {};
  const se = n.reported?.session;
  const inst = me.installed || "";
  const latest = cc.latest || "";
  let status, cls;
  if (!se || typeof se !== "object" || !se.up) [status, cls] = ["no session account", "warn"];
  else if (me.updating) [status, cls] = ["updating", "warn"];
  else if (!inst) [status, cls] = ["not installed", "bad"];
  else if (me.behind) [status, cls] = [`${inst}, ${latest} is out`, "warn"];
  else [status, cls] = [latest ? `${inst}, up to date` : inst, "ok"];
  // ...and whether the person looking is signed in here, which a folded
  // section would otherwise keep to itself.
  if (inst && se?.up && !me.updating && !claudeOn(n.id)) [status, cls] = [`${status}, not signed in`, "warn"];
  // Installed, updated and removed on the node's Toolchains tab like any
  // toolchain (R145); what stays here is the account's sign-in.
  const body = `
    ${signinBlock(n)}
    <div class="actbar">
      <span class="state">${!se?.up ? "No session account here, so nothing runs Claude Code."
        : inst ? `Claude Code ${esc(inst)}${me.behind ? `; ${esc(latest)} is out` : ""}: the Toolchains tab updates it.`
        : "Not installed: a Claude session cannot start here until the Toolchains tab installs it."}</span>
      ${se?.up && mayToolchains() ? `<button type="button" data-ndtc="${esc(n.id)}" title="install, update or remove it there">Toolchains</button>` : ""}
    </div>`;
  return docSection("nodes", "claude", "Claude Code", status, body, {cls});
}

// Whether each session here reaches only its own project's containers, the
// controller and the internet (R79): the node's setting, and what its agent
// says about it underneath, a reason in red when it is on and not in force.
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
      ? (on ? `<div class="sub warn">Update the agent: this one cannot keep a session to its own project's network.</div>` : "")
    : on && !sn.can ? `<div class="sub bad">Not in force: ${esc(sn.why || "this node cannot do it")}.</div>`
    : on && sn.error ? `<div class="sub bad">Not in force, so no session starts here until it is: ${esc(sn.error)}.</div>`
    : on && sn.active ? `<div class="sub">Sessions started here reach the internet, the controller and their own project's containers at this node's address, and nothing else.</div>`
    : on ? `<div class="sub dim">Setting it up.</div>`
    : sn.sessions ? `<div class="sub dim">${sn.sessions} session${sn.sessions === 1 ? "" : "s"} started while it was on keep their own network until they end.</div>`
    : "";
  return `<label class="ndcap"><input type="checkbox" data-k="sessnet" ${c.draft.sessnetOn ? "checked" : ""}>
      keep each session to its own project's network</label>
    ${line}
    <label class="ndcap"><input type="checkbox" data-k="rootasks" ${c.draft.rootAsks ? "checked" : ""}>
      let a session ask for a root command (bb root run), which a person then allows or denies</label>
    ${rootOn ? "" : `<div class="sub dim">A session that asks is refused and told this is off.</div>`}`;
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
  const now = `${t.working || 0} working now${t.limit ? ` of ${t.limit}` : ""}${
    t.waiting ? `, ${t.waiting} waiting for a turn` : ""}`;
  const inp = `ndTurns-${n.id}`;
  // ...and how many workers a test run here may use (R81): the node's
  // cores when 0, handed to every test job as BB_TEST_WORKERS.
  const tw = String(n.config?.test_workers || 0);
  if (c.draft.workersText === undefined || c.draft.workersFrom !== tw){
    c.draft.workersText = tw; c.draft.workersFrom = tw;
  }
  const winp = `ndWorkers-${n.id}`;
  // What 0 means is in each label, where a phone reads it (B459).
  return `<div class="logdays setrow col">
      ${lbl(inp, "Claude sessions working at once (0: no limit)", "a prompt past it waits for a turn instead of starting")}
      <input id="${esc(inp)}" data-k="turns" type="number" min="0" max="64" step="1" inputmode="numeric"
        value="${esc(c.draft.turnsText)}">
    </div>
    <div class="logdays setrow col">
      ${lbl(winp, `Test workers (0: every core${n.reported?.cpu ? `, ${n.reported.cpu} here` : ""})`,
        "how many workers a test run here may use, as BB_TEST_WORKERS in its environment")}
      <input id="${esc(winp)}" data-k="workers" type="number" min="0" max="256" step="1" inputmode="numeric"
        value="${esc(c.draft.workersText)}">
    </div>
    <div class="actbar">
      <span class="state${t.waiting ? " warn" : ""}">${esc(now)}</span>
      <button type="button" data-nd="turns" title="save the limit and the switch: the next prompt here is held to the one, the next session started here to the other">Save</button>
    </div>`;
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
  const body = `
    <div class="ndname actbar">
      <div class="setrow col grow">${lbl("", "Name", "its name in the pickers, on the project rows and as a runner label")}
      <input data-k="name" value="${esc(c.draft.nameText)}" spellcheck="false" autocomplete="off"
        maxlength="60" aria-label="node name"></div>
      <button type="button" data-nd="rename" title="a runner already installed keeps its old label until reinstalled">Rename</button>
    </div>
    <div class="sub">Only needed when a path a compose file names is somewhere else on the node.</div>
    <div class="ndpaths actbar">
      <div class="setrow col grow">${lbl("", "Path mapping", "here:there pairs, comma-separated")}
      <input data-k="paths" value="${esc(c.draft.pathsText)}" spellcheck="false" autocomplete="off"
        placeholder="/workspace:/workspace, /devdata:/mnt/user/appdata/bb-dev"
        aria-label="path mapping"></div>
      <button type="button" data-nd="paths" title="save the mapping onto the node's record">Save paths</button>
      <button type="button" data-nd="check-paths"
        title="check both machines see the same projects directory">Check</button>
    </div>
    <div class="sub ndcheck" hidden></div>
    ${!n.reported?.sandbox ? "" : `<div class="actbar">
      <span class="state">${n.config?.lock
        ? "Locked: storage, network and root changes are refused from here."
        : "Lock refuses storage, network and root changes from here."}</span>
      <button type="button" data-nd="${n.config?.lock ? "unlock" : "lock"}"
        title="${n.config?.lock ? "allow them from here again"
          : "keep them to the machine's own console"}">${
        n.config?.lock ? "Unlock" : "Lock system changes"}</button>
    </div>`}
    <div class="actbar">
      <span class="state">Drain finishes what is running and takes nothing new.</span>
      <button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
        title="${n.state === "draining" ? "take new work again"
          : "finish what is running and take nothing new, so the machine can reboot"}">${
        n.state === "draining" ? "Undrain" : "Drain"}</button>
      <button type="button" data-nd="cache-clear" ${stale || inflight("cache-clear") ? "disabled" : ""}
        title="${stale ? esc(staleWhy(n))
          : inflight("cache-clear") ? "already clearing"
          : "drop every project's build cache here; the next build refetches"}">${
        inflight("cache-clear") ? "Clearing…" : "Clear cache"}</button>
      <button type="button" class="danger" data-nd="retire"
        title="take it off every list; its history stays">Remove</button>
      ${n.reported?.sandbox ? `<button type="button" class="danger" data-nd="uninstall"
        ${inflight("uninstall") ? "disabled" : ""}
        title="remove BuilderBot from the machine: the agent, its accounts, mounts and files; docker and the shares stay">${
        inflight("uninstall") ? "Uninstalling…" : "Uninstall"}</button>` : ""}
    </div>
    ${n.kind === "agent" ? `<div class="actbar">
      <span class="state${n.live && !installing ? "" : " bad"}">${!n.live
        ? "Reboot and Shut down need the agent dialing in, and it is away: power the machine from its console or its hypervisor."
        : installing ? `Reboot and Shut down wait: ${installing} is running here. Stop it first, or wait for it to finish.`
        : "Reboot ends every session there and the machine comes back on its own; Shut down does not come back until somebody switches it on."}</span>
      ${["reboot", "poweroff"].map(w =>
        `<button type="button" class="danger" data-nd="${w}" ${!n.live || inflight(w) || installing ? "disabled" : ""}>${
          inflight(w) ? (w === "reboot" ? "Rebooting…" : "Shutting down…")
                      : (w === "reboot" ? "Reboot" : "Shut down")}</button>`).join("")}
    </div>` : ""}`;
  return docSection("nodes", "advanced", "Advanced",
                    n.state === "draining" ? "draining" : n.config?.lock ? "locked" : "",
                    body, {cls: n.state === "draining" ? "warn" : ""});
}
function nodeStale(n){
  return n.kind === "agent" && n.agent?.digest && nodesAgent?.digest
    && n.agent.digest !== nodesAgent.digest;
}

// The window a version promises: "0.4" of "0.4.27", empty for anything that
// is not WINDOW.BUILD. Empty means "cannot say" and is never read as a
// mismatch: an agent built before the window existed is behind for the
// ordinary reason and does not need a louder claim invented about it.
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
  // Static routes, in either mode, against the ones the node reports (an
  // agent from before 0.7.143 reports none, which reads as all to apply).
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
    <div class="ndmount" data-i="${i}">
      <select data-k="type" aria-label="type">
        <option value="nfs" ${m.type !== "virtiofs" ? "selected" : ""}>nfs</option>
        <option value="virtiofs" ${m.type === "virtiofs" ? "selected" : ""}>virtiofs</option>
      </select>
      <div class="setrow col">${lbl("", "Source", m.type === "virtiofs" ? "the share tag" : "host:/export")}
      <input data-k="source" value="${esc(m.source || "")}" spellcheck="false" autocomplete="off"
        placeholder="${m.type === "virtiofs" ? "appdata" : "nas:/mnt/user/appdata"}" aria-label="source"></div>
      <div class="setrow col">${lbl("", "Mountpoint", "blank means /mnt/ and the export's name")}
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
      r.free_mb >= 10240 ? Math.round(r.free_mb / 1024) + "GB" : r.free_mb + "MB"} free`) : "";
    return `
    <div class="ndstore">
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
  const pending = drift ? drift.storage.concat(drift.network === "unknown" ? [] : drift.network) : [];
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
          la.error ? ": " + la.error : ""}. Its log is on the Jobs tab; fix it and Apply again.`, "bad"]
      : null;
  // The state line answers one question: is there anything to press Apply
  // for, and names the changes when there is, so the button is not a leap.
  const [status, statusCls] = busyNow
    ? [`applying ${busyNow.what}${busyNow.what === "network" ? ": waiting for it to dial back in" : "…"}`, "note"]
    : stale ? [staleWhy(n), windowGap(n) ? "bad" : "warn"]
    : c.dirty ? ["Unsaved: press Save, then Apply.", "warn"]
    : !drift ? ["nothing configured yet: the node runs on whatever it was set up with", ""]
    : pending.length ? [`${pending.length} change${pending.length === 1 ? "" : "s"} to apply: ${
        pending.slice(0, 3).join("; ")}${pending.length > 3 ? "; …" : ""}`, "warn"]
    : drift.network === "unknown"
      ? ["the node matches what is saved here, except dhcp, which cannot be told from here", ""]
      : ["the node matches what is saved here", "ok"];
  // The dhcp caveat is Network's; under Storage it read as a storage fault.
  const [storStatus, storStatusCls] = drift?.network === "unknown" && status.startsWith("the node matches")
    ? ["the node matches what is saved here", "ok"] : [status, statusCls];
  const saveBtn = `<button type="button" data-nsave ${c.dirty ? "" : "disabled"}
      title="save these settings; Apply puts them on the node">Save</button>`;
  const storage = `
      <div class="sub">Mounts at boot.${
        d.fromNode ? ` <span class="dim">As the node reports them; save to manage them from here.</span>` : ""}</div>
      ${mounts}
      <div><button type="button" data-madd>+ mount</button></div>
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
      <div class="ndnet${isStatic ? "" : " dhcp"}">
        <select data-k="net:mode" aria-label="mode">
          <option value="dhcp" ${isStatic ? "" : "selected"}>dhcp</option>
          <option value="static" ${isStatic ? "selected" : ""}>static</option>
        </select>
        ${isStatic ? `
        <div class="setrow col">${lbl("", "Address", "with its prefix length")}
        <input data-k="net:address" value="${esc(d.network.address || "")}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.12/24" aria-label="address"></div>
        <div class="setrow col">${lbl("", "Gateway")}
        <input data-k="net:gateway" value="${esc(d.network.gateway || "")}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.1" aria-label="gateway"></div>
        <div class="setrow col">${lbl("", "DNS", "comma-separated")}
        <input data-k="net:dns" value="${esc((d.network.dns || []).join(", "))}"
          spellcheck="false" autocomplete="off" placeholder="10.0.0.1, 1.1.1.1" aria-label="dns"></div>
        <div class="setrow col">${lbl("", "Interface", "blank means the default route's")}
        <input data-k="net:interface" value="${esc(d.network.interface || "")}" spellcheck="false"
          autocomplete="off" placeholder="${esc(net.interface || "eth0")}" aria-label="interface"></div>` : ""}
        <div class="setrow col ndroutes">${lbl("", "Static routes", "one a line: a network with its prefix, via the router that reaches it")}
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
      ? docSection("nodes", "storage", "Storage", stStatus, storage, {cls: stCls})
        + docSection("nodes", "network", "Network", netStatus, network, {cls: netCls})
      : `<div class="sub dim ndguest">Storage and network are managed on the machine itself, not here.</div>`}
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

const gb = mb => mb === null || mb === undefined ? "?"
  : mb >= 10240 ? Math.round(mb / 1024) + "GB" : Math.round(mb) + "MB";

// Everything the census measured, as meters: what the machine is doing now,
// and how much room each store has left.
function nodeMeters(n){
  const rep = n.reported || {}, s = rep.sample || {};
  const out = [];
  if (n.live && typeof s.cpu_pct === "number")
    out.push(meter("cpu", s.cpu_pct, s.cpu_pct + "%",
                   `${rep.cpu || "?"} cores${s.load1 ? `, load ${s.load1}` : ""}`));
  const mem = s.mem_mb || rep.mem_mb;
  if (n.live && mem && s.mem_used_mb)
    out.push(meter("memory", s.mem_used_mb / mem * 100,
                   `${gb(s.mem_used_mb)} / ${gb(mem)}`));
  // The card, where the node has one whose driver answers: how busy it is
  // and how much of its own memory is taken, the two things a model or an
  // encode is waiting on.
  if (n.live && typeof s.gpu_pct === "number")
    out.push(meter("gpu", s.gpu_pct, s.gpu_pct + "%", rep.gpu || "the node's card"));
  if (n.live && s.gpu_mem_mb)
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


// The node's page: a header band: name, state, where it is, its agent and
// the one control that is about the agent, then the sections.
function renderNodesInto(i){
  const d = docSurface(i, "nodes");
  if (!d) return;
  if (nodesList === null){
    d.list.innerHTML = `<div class="loading">loading…</div>`;
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
  d.setBar(`${live.length ? `<label class="pick">Node <select id="ndPick" aria-label="node">${
      live.map(x => `<option value="${esc(x.id)}"${x.id === nodesPick ? " selected" : ""}>${
        esc(x.name)}: ${esc(x.kind)}${x.live === false ? ", quiet" : ""}</option>`).join("")}</select></label>` : ""}
    <span class="sp"></span>
    <span class="actbar">
      <button type="button" id="ndVm">Create sandbox VM</button>
      <button type="button" id="ndEnroll">Enroll node</button>
    </span>`);
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
        <div class="phcmd"># ${esc(a.cmd.join(" "))}</div>
        <div class="sub">${esc(a.asker ? a.asker + "'s session in " + (a.project ? projLabel(a.project) : "a project") : a.project ? projLabel(a.project) : "a session")} asks to run this as root on ${esc(a.node_name)} · ${a.left > 60
          ? `${Math.floor(a.left / 60)} min left to answer`
          : `${a.left}s left to answer`}</div></div>
      <span class="acts">
        <button type="button" data-rdeny="${a.id}">Deny</button>
        <button type="button" class="primary" data-rallow="${a.id}">Allow</button>
      </span></div>`).join("");
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
    const agentLine = n.kind === "agent" && n.agent?.version
      ? `agent ${n.agent.version}${n.agent.digest ? " " + n.agent.digest.slice(7, 15) : ""}${
          stale ? ` <span class="pill warn ndstale" title="this controller ships agent ${
            esc(nodesAgent.version)} ${esc(nodesAgent.digest.slice(7, 15))}">update available → ${
            esc(nodesAgent.version)}</span>` : ""}${
          n.config?.user ? ` · jobs run as ${esc(n.config.user)}` : ""}` : "";
    const pending = n.state === "pending";
    const agentBar = n.kind === "agent" && !pending ? `
        <div class="actbar ndagent">
          <span class="lead dim${updating ? " note"
                              : stale ? (windowGap(n) ? " bad" : " warn") : ""}">${
            updating ? (held ? `Update to agent ${esc(nodesAgent?.version || "")} waits for ${held} running job${
                held === 1 ? "" : "s"} to finish; the node takes no new work until then (10 minutes at most).`
              : `Updating to agent ${esc(nodesAgent?.version || "")}. This row refreshes when the node reports back.`)
            : stale ? `${windowGap(n) ? "out of window" : "behind"}: ${esc(staleWhy(n))}`
            : `Test checks that this node answers.`}</span>
          ${stale ? `<button type="button" data-nd="update-agent" ${updating ? "disabled" : ""}
            title="${updating ? "Update queued: this row refreshes when the node reports back"
              : `Update the agent to ${esc(nodesAgent.version)} once its running jobs finish`}">${
            updating ? "Updating…" : "Update agent"}</button>` : ""}
          <button type="button" data-nd="test" title="check that this node answers">Test</button>
          <button type="button" data-nd="reenroll" title="a new enroll script for this node, to run again on the same machine">Enroll script</button>
        </div>
        <div class="sub ndtest" hidden></div>` : "";
    const health = docSection("nodes", "health", "Health",
      n.kind === "agent" ? (n.live ? "live" : "quiet") : "", `
        ${nodeMeters(n) || `<div class="empty">nothing measured yet</div>`}
        ${nodeTools(n)}
        ${nodeGit(n)}
        ${nodeGpu(n)}
        ${nodeSound(n)}
        ${labels ? `<div class="sub ndlabels">${labels}</div>` : ""}`,
      {cls: n.kind === "agent" && n.live ? "ok" : "", open: true});
    // Every live agent node gets the plane: the runner needs no stamp. What
    // inside it needs one (Storage and Network) nodeConfSections decides.
    const plane = n.kind === "agent" && !pending;
    return askRows + `
    <div class="row stack2 ndrow" data-node="${esc(n.id)}">
      <div class="grow">
        <div class="name">${esc(n.name)} ${nodeStatePill(n)}
          <span class="dim">· ${esc(n.kind)}</span></div>
        <div class="sub">${[esc(where), census, esc(seen), agentLine].filter(Boolean).join(" · ")}</div>
        ${keepLine(n)}
        ${state?.can?.admin === false ? `<div class="sub warn ndreadonly">An administrator changes a node's settings. Your Claude sign-in here, under Claude Code, is yours.</div>` : ""}
        ${agentBar}
      </div>
      <div class="ndsections">
        ${health}
        ${n.kind === "agent" && !pending ? nodeProjectsSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeSessionsSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeGpuSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeClaudeSection(n) : ""}
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
  d.list.innerHTML = rows + none
    + (!nodesList.length ? `<div class="empty">The node list could not be read.</div>` : "");
  d.setFoot(`A node does the work of the projects bound to it: pick one in a project's
    settings. Jobs run as the enrolled account, never root.`);
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
function renderRunnerInto(i){
  const d = docSurface(i, "runner");
  if (!d) return;
  if (nodesList === null){ d.list.innerHTML = `<div class="loading">loading…</div>`; return; }
  const ns = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  const has = n => (n.reported?.services?.runners || []).length || Object.keys(n.services?.runners || {}).length;
  if (!ns.some(n => n.id === runnerNode)) runnerNode = (ns.find(has) || ns[0])?.id || "";
  const n = ns.find(x => x.id === runnerNode);
  d.setBar(`${nodePick("rnrPick", ns, runnerNode)}<span class="sp"></span>
    <button type="button" id="rnrRefresh" title="read the nodes again">Refresh</button>`);
  d.list.innerHTML = n
    ? `<div class="ndrow runnerpanel" data-node="${esc(n.id)}"><div class="ndconf">${nodeRunnerSection(n, nodeDraft(n))}</div></div>`
    : `<div class="hint">No node is enrolled yet: the Nodes tab enrolls one, and its runner is added here.</div>`;
  if (n) wireNodeConf(d.list.querySelector(".ndrow"), n.id);
  const pick = d.el.querySelector("#rnrPick");
  if (pick) pick.onchange = () => { runnerNode = pick.value; nodesRev++; drawPanes(); };
  const rf = d.el.querySelector("#rnrRefresh");
  if (rf) rf.onclick = () => { busy(rf, "Reading"); loadNodes(); };
}

// An account that does not administer sees a node's settings and changes
// none of them: every control on the tab is dead for it but the picker and
// its own Claude sign-in, and the row says why (the operator, 30 Sep). Once,
// after the draw and its wiring, rather than in each section: a control a
// later section adds is dead for that account without anybody remembering.
function nodesReadOnly(root){
  if (state?.can?.admin !== false) return;
  root.querySelectorAll("button, input, select, textarea").forEach(c => {
    // A phone is its owner's, any account's (tab-phone.js): its section
    // stays live, and the server holds who may press what there.
    if (c.id !== "ndPick" && !c.closest("[data-signin]") && !c.closest(".phonetab")) c.disabled = true;
  });
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
        + "Its containers there keep running, and the Docker tab still reaches them.")) return;
  busy(b, "Removing");
  const j = await (await postJSON("/api/prefs", {project: name, node, nodes: rest}))
    .json().catch(() => ({error: "no answer"}));
  if (j.error) notify(j.error, true);
  else notify(`${projLabel(name)} no longer uses ${nname}`);
  await refresh();
  nodesRev++; drawPanes();
}

function wireNodesTab(root){
  wireSignin(root);
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
    document.getElementById("ndTitle").textContent = again ? `Enroll ${again.name} again` : "Enroll a node";
    boxWidth(false);
    body.innerHTML = `<div class="field">
        <div class="prefrow">
          <div class="setrow col">${lbl("ndEnName", "Name")}
            <input id="ndEnName" maxlength="60" autocomplete="off" placeholder="buildbox"></div>
          <div class="setrow col">${lbl("ndEnUser", "Jobs run as",
            "the account the provisioner makes and every job runs as. bb unless that name is taken on the machine")}
            <input id="ndEnUser" maxlength="32" autocomplete="off" spellcheck="false"
              value="bb"></div>
        </div>
        <label class="ndcap"><input type="checkbox" id="ndEnSess" checked> Claude sessions run on it</label>
        <label class="ndcap"><input type="checkbox" id="ndEnHost"> Hosting only: it runs containers sent to it, and nothing of it comes back</label>
        <div class="hint" id="ndEnHostHint" hidden>No project's code, no sessions and no bb go to it; its agent may ask the controller for its own jobs and nothing else. For a public box such as a cloud VPS.</div>
        <div class="setrow col">${lbl("ndEnDoor", "SSH door",
          "a way in for ssh, switched on and off from the node's row. cloudflared publishes the machine's port 22 at a hostname of its own, with a tunnel token from Zero Trust; Tailscale joins the machine to your tailnet with an auth key and answers ssh there, with no public name")}
          <select id="ndEnDoor">
            <option value="">none</option>
            <option value="cloudflared">cloudflared: port 22 at a hostname</option>
            <option value="tailscale">Tailscale: ssh on the tailnet</option>
          </select></div>
        <div class="setrow col" id="ndEnDoorHostRow" hidden>${lbl("ndEnDoorHost", "The door's hostname",
          "a public hostname of its own on the tunnel (not the controller's), set in Zero Trust to go to ssh://localhost:22")}
          <input id="ndEnDoorHost" autocomplete="off" spellcheck="false" placeholder="ssh-vps.example.com"></div>
        <div class="setrow col" id="ndEnDoorSecretRow" hidden>${lbl("ndEnDoorSecret", "The door's secret",
          "cloudflared's tunnel token, or a Tailscale auth key. It rides in the script until the script has run, then leaves it; the node keeps it")}
          <input id="ndEnDoorSecret" type="password" autocomplete="off" spellcheck="false"></div>
        <label class="ndcap" id="ndEnDoorCloseRow" hidden><input type="checkbox" id="ndEnDoorClose"> Close port 22 to the internet once the door is up</label>
        <div class="hint" id="ndEnDoorHint" hidden>Who gets to the door is the tunnel's own say (Cloudflare Access, or the tailnet's ACLs); the machine's keys decide after that. Leave port 22 open until you have come in through the door once.</div>
        <label class="ndcap"><input type="checkbox" id="ndEnNginx"> Put nginx on it once it is enrolled</label>
        <div class="hint" id="ndEnNginxHint" hidden>BuilderBot's own reverse proxy, deployed the moment the node enrolls, with the routes and certificate the nginx tab holds for it (set them there first or after).</div>
      </div>
      <div class="field">
        <div class="setrow col">${lbl("ndEnReach", "Reaches the controller",
          "how the machine dials in. Through WireGuard, the config your router made for it goes inside the script, and only the controller is routed through the tunnel. Through a public hostname, a tunnel at home (Cloudflare Tunnel, Tailscale Funnel, ngrok, frp) publishes the controller at a name and the machine dials that: nothing on your router changes and it never learns your address")}
          <select id="ndEnReach">
            <option value="lan">on this network</option>
            <option value="wireguard">WireGuard</option>
            <option value="public">a public hostname (a tunnel from home)</option>
          </select></div>
        <div class="setrow col">${lbl("ndEnCtl", "Controller's address",
          "the URL the machine dials. Behind WireGuard, the controller's address on your network, which the tunnel routes to. Through a public hostname, the name the tunnel publishes, as https://bb.example.com")}
          <input id="ndEnCtl" autocomplete="off" spellcheck="false" value="${esc(location.origin)}"></div>
        <div class="hint" id="ndEnCfHint" hidden>Hosting only, and no sessions: the controller cannot reach back through the tunnel. The machine verifies the hostname's public certificate and never sees your home address.</div>
        <div class="setrow col" id="ndEnWgRow" hidden>${lbl("ndEnWgText", "WireGuard config",
            "the .conf your router made for this machine: choose the file, or paste what is in it. Only the controller's address is routed through it on the machine")}
          <input type="file" id="ndEnWg" accept=".conf,text/plain" aria-label="choose the WireGuard config file">
          <textarea id="ndEnWgText" rows="7" spellcheck="false" autocomplete="off"
            placeholder="[Interface]&#10;PrivateKey = …&#10;Address = 10.6.0.5/32&#10;&#10;[Peer]&#10;PublicKey = …&#10;Endpoint = home.example.net:51820"></textarea></div>
      </div>
      <div class="field"><div class="hint">${again
        ? "A new script for this node: run it again on the same machine, as root, to set it up afresh or change what it reaches the controller through. It carries no secret (the node keeps its WireGuard config and its door's); a secret pasted here replaces the node's. It refuses to run on another machine, and so does the controller."
        : "The script carries a token good once, for a day, and runs as root on a Linux machine."}</div></div>
      <div class="foot">
        <button type="button" class="primary" id="ndEnGo">Make the script</button>
        <button type="button" id="ndEnTok">Just a token</button>
        <button type="button" id="ndEnCancel">Cancel</button>
      </div>`;
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
    const host = $b("#ndEnHost"), sess = $b("#ndEnSess");
    const showHost = () => {
      const cf = reach.value === "public";
      if (cf) host.checked = true;
      host.disabled = cf;
      $b("#ndEnHostHint").hidden = !host.checked;
      $b("#ndEnCfHint").hidden = !cf;
      sess.disabled = host.checked;
      if (host.checked) sess.checked = false;
    };
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
    reach.onchange = showWg;
    host.onchange = showHost;
    showWg();
    // A file chosen lands in the box, which is what is sent: one place to
    // read it, change it, or paste it instead.
    $b("#ndEnWg").onchange = async e => {
      const f = e.target.files?.[0];
      if (f) $b("#ndEnWgText").value = await f.text();
    };
    // No focus, like every other dialog here: on a phone it would raise the
    // keyboard over the box it just opened.
    $b("#ndEnCancel").onclick = shut;
    const answers = () => ({name: $b("#ndEnName").value,
      // The account rides along, so the row says the right one before the
      // machine exists and the command below carries it. The record follows
      // whatever the agent reports at enrollment either way.
      user: $b("#ndEnUser").value.trim() || "bb"});
    // What was typed comes back after a refusal: a redraw to its defaults
    // lost the name and the account on every one (B331's shape).
    const keep = () => ({"#ndEnName": $b("#ndEnName").value, "#ndEnUser": $b("#ndEnUser").value,
      "#ndEnSess": $b("#ndEnSess").checked, "#ndEnHost": $b("#ndEnHost").checked, "#ndEnNginx": ngx.checked,
      "#ndEnDoor": door.value, "#ndEnDoorHost": $b("#ndEnDoorHost").value, "#ndEnDoorClose": $b("#ndEnDoorClose").checked,
      "#ndEnReach": reach.value, "#ndEnCtl": $b("#ndEnCtl").value,
      "#ndEnWgText": $b("#ndEnWgText").value});
    const go = $b("#ndEnGo");
    go.onclick = () => pressing(go, async () => {
      const kept = keep();
      const conf = $b("#ndEnWgText").value;
      if (reach.value === "wireguard" && !conf.trim() && !again){
        notify("choose the WireGuard config your router made for this machine, or paste it in", true); return;
      }
      busy(go, "Making");
      const r = await nodeAct({action: "enroll", script: true, ...answers(), ...(again ? {node: again.id} : {}),
        sessions: $b("#ndEnSess").checked && !$b("#ndEnHost").checked, reach: reach.value,
        host_only: $b("#ndEnHost").checked, nginx: ngx.checked,
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
      <div class="foot"><span class="sp"></span>
        <button type="button" class="primary" id="ndScriptGet">Download ${esc(r.filename)}</button>
        <button type="button" id="ndTokDone">Done</button></div>`;
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
        <div class="hint">On a Mac, as yourself:</div>
        <pre class="ndcmd">curl -fsSL -H 'Authorization: Bearer ${esc(m.token)}' '${esc(m.url)}/api/v1/agent/download?what=provisioner-macos' -o provision-macos.sh
bash provision-macos.sh --controller ${esc(m.url)} --token ${esc(m.token)}</pre>
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
      `<div class="setrow col">${lbl("vm_" + k, label, help)}
        <input id="vm_${k}" data-vk="${k}" autocomplete="off" spellcheck="false"
          value="${esc(String(vmDraft[k]))}"${extra}></div>`;
    const kinds = vmKinds || [{id: "unraid", label: "Unraid", wants: ["uuid", "mac"],
                              mac_prefix: "52:54:00", artifact: "domain XML"}];
    const kind = kinds.find(k => k.id === vmDraft.hv) || kinds[0];
    const takes = k => (kind.wants || []).includes(k);
    body.innerHTML = `<div class="field vmform">
        <div class="hint">Pick where it runs; the machine is written the same everywhere.</div>
        <div class="setrow col">${lbl("vm_hv", "Runs on")}
          <select id="vm_hv" data-vk="hv">${kinds.map(k =>
            `<option value="${esc(k.id)}"${k.id === kind.id ? " selected" : ""}>${
              esc(k.label)}${k.dev ? " (dev)" : ""}</option>`).join("")}</select></div>
        <div class="prefrow">
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
        <div class="prefrow">
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
      <div class="foot">
        ${made ? `<button type="button" id="vmCopy">Copy</button>` : ""}
        <span class="sp"></span>
        <button type="button" class="primary" id="vmGo">${made ? "Generate another" : "Generate"}</button>
        <button type="button" id="vmCancel">${made ? "Done" : "Cancel"}</button>
      </div>`;
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
  const vm = root.querySelector("#ndVm");
  if (vm) vm.onclick = async () => {
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
  const en = root.querySelector("#ndEnroll");
  if (en) en.onclick = () => { modal.hidden = false; mintForm(); };
  // The backdrop closes it, like every other dialog on the page. Not while
  // the token is up: that is the one thing here shown once, and closing it by
  // a stray click on the room around it would lose the command.
  modal.onclick = e => {
    if (e.target === modal && !body.querySelector(".ndtoken")) shut();
  };
  wireSections(root);
  root.querySelectorAll(".ndrow").forEach(box => {
    const id = box.dataset.node;
    // The driver is the Toolchains tab's row (R102): this opens it on the node.
    box.querySelectorAll("[data-ndtc]").forEach(b => b.onclick = () => openToolchainsOn(b.dataset.ndtc));
    box.querySelectorAll("[data-nd]").forEach(b => b.onclick = () => pressing(b, async () => {
      const act = b.dataset.nd;
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
      if (act === "reboot" || act === "poweroff"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        const here = (state?.sessions || []).filter(x => x.node_id === id);
        const mine = here.filter(x => tmuxBase(x.name).startsWith("claude-"));
        const open = here.length
          ? `It ends the ${here.length} session${here.length === 1 ? "" : "s"} open there`
            + `${mine.length ? ` (${mine.length} of them a Claude conversation)` : ""}; transcripts are kept. `
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
        const mine = here.filter(x => tmuxBase(x.name).startsWith("claude-"));
        if (here.length && !confirm(
              `Update the agent on ${
                (nodesList || []).find(n => n.id === id)?.name || "this node"}?\n\n`
              + `This ends the ${here.length} session`
              + `${here.length === 1 ? "" : "s"} open there`
              + `${mine.length ? ` (${mine.length} of them a Claude conversation)` : ""}`
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
      if (act === "reenroll"){
        const n = (nodesList || []).find(x => x.id === id);
        if (n){ modal.hidden = false; mintForm({}, n); }
        return;
      }
      if (act === "door" && b.dataset.on === "0"){
        const name = (nodesList || []).find(n => n.id === id)?.name || "this node";
        if (!confirm(`Shut the SSH door on ${name}?\n\nNothing reaches its port 22 through the tunnel until it is opened again from here.`)) return;
      }
      if (act === "cache-clear"
          && !confirm("Clear this node's build caches? Every project's Gradle, "
                      + "npm and snapshot cache there goes; the next build of "
                      + "each re-downloads what it needs.")) return;
      // The verb, said on the button for the round trip and, for the
      // actions whose effect the row cannot see at once: beyond it.
      busy(b, {"update-agent": "Updating", test: "Asking", drain: "Draining",
               online: "Undraining", "cache-clear": "Clearing",
               retire: "Removing", uninstall: "Uninstalling", reboot: "Rebooting", poweroff: "Shutting down", "gpu-apply": "Applying",
               paths: "Saving", "check-paths": "Checking", "to-sync": "Moving",
               "sync-stop": "Stopping", "sync-resume": "Resuming", "sync-clean": "Cleaning",
               rename: "Renaming", turns: "Saving"}[act] || "Working");
      if (act === "update-agent"){
        nodesUpdating[id] = Date.now();
        const j = await nodeAct({action: "update-agent", id});
        if (j.current){ delete nodesUpdating[id]; notify(`already on ${j.version}`); }
        else if (j.ok) notify("Update queued: the row refreshes when the node reports back");
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
      if (act === "turns"){
        // The Sessions section's Save: the limit, and the session network
        // switch when its tick differs from what the node has.
        const inp = box.querySelector('[data-k="turns"]');
        const sw = box.querySelector('[data-k="sessnet"]');
        const was = !!nodesList.find(x => x.id === id)?.config?.session_net;
        const j = await nodeAct({action: "turns", id, limit: Number(inp ? inp.value : 0)});
        if (j.error) return;
        const c = nodesConf[id]; if (c && c.draft) c.draft.turnsText = undefined;
        let said = j.limit ? `at most ${j.limit} Claude session${j.limit === 1 ? "" : "s"} work here at once`
                           : "no limit on Claude sessions working here at once";
        if (sw && sw.checked !== was){
          const k = await nodeAct({action: "session-net", id, on: sw.checked});
          if (k.error) return;
          if (c && c.draft) c.draft.sessnetOn = undefined;
          said += sw.checked ? "; sessions started here from now on reach only their own project's containers"
                             : "; sessions started here from now on share its network";
        }
        const wi = box.querySelector('[data-k="workers"]');
        const wWas = String(nodesList.find(x => x.id === id)?.config?.test_workers || 0);
        if (wi && String(Number(wi.value) || 0) !== wWas){
          const k = await nodeAct({action: "test-workers", id, workers: Number(wi.value) || 0});
          if (k.error) return;
          if (c && c.draft) c.draft.workersText = undefined;
          said += k.workers ? `; test runs here may use ${k.workers} worker${k.workers === 1 ? "" : "s"}`
                            : "; test runs here may use every core";
        }
        const ra = box.querySelector('[data-k="rootasks"]');
        const raWas = !nodesList.find(x => x.id === id)?.config?.no_root;
        if (ra && ra.checked !== raWas){
          const k = await nodeAct({action: "root-asks", id, on: ra.checked});
          if (k.error) return;
          if (c && c.draft) c.draft.rootAsks = undefined;
          said += ra.checked ? "; a session here may ask for a root command again"
                             : "; a session here asking for a root command is refused";
        }
        notify(said);
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
        await nodeAct({action: "paths", id, paths: inp ? inp.value : ""});
        const c = nodesConf[id]; if (c && c.draft) c.draft.pathsText = undefined;
        return;
      }
      if (act === "check-paths"){
        // Roadmap #13. Like Test: the verdict goes on the row's own line,
        // found again after nodeAct's repaint replaced the one clicked.
        const out = root.querySelector(`.ndrow[data-node="${CSS.escape(id)}"] .ndcheck`);
        if (out){ out.hidden = false; out.textContent = "checking…"; }
        const j = await nodeAct({action: "check-paths", id});
        const now = root.querySelector(`.ndrow[data-node="${CSS.escape(id)}"] .ndcheck`) || out;
        if (!now) return;
        now.hidden = false;
        now.textContent = j.error || j.why || (j.same ? "the same directory" : "not the same directory");
        now.classList.toggle("warn", !j.same);
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
      await nodeAct({action: act, id, ...(act === "door" ? {on: b.dataset.on === "1"} : {})});
    }));
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
                           nodesFocus = {id, key: "name", pos: ni.selectionStart ?? undefined}; };
    }
    // The same for the limit on sessions working at once, in the Sessions
    // section: a number is typed across a heartbeat as easily as a path.
    // The update-before-a-session switch is Controller settings' alone:
    // one setting for every node, behind an Apply there. It used to be a
    // checkbox on this section too, written on the click (B257).
    // Each session kept to its own project's network (R79): a draft until
    // the section's Save, like the limit beside it.
    const sw = box.querySelector('[data-k="sessnet"]');
    if (sw) sw.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.sessnetOn = sw.checked; };
    const ra = box.querySelector('[data-k="rootasks"]');
    if (ra) ra.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.rootAsks = ra.checked; };
    // The GPU section's two switches (R102): drafts until its Apply.
    const ge = box.querySelector('[data-k="gpuemu"]');
    if (ge) ge.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.gpuEmu = ge.checked; };
    const gc = box.querySelector('[data-k="gpucomp"]');
    if (gc) gc.onchange = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.gpuComp = gc.checked; };
    const ti = box.querySelector('[data-k="turns"]');
    if (ti){
      ti.onfocus = () => { nodesFocus = {id, key: "turns"}; };
      ti.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.turnsText = ti.value;
                           nodesFocus = {id, key: "turns"}; };
    }
    const wi = box.querySelector('[data-k="workers"]');
    if (wi){
      wi.onfocus = () => { nodesFocus = {id, key: "workers"}; };
      wi.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.workersText = wi.value;
                           nodesFocus = {id, key: "workers"}; };
    }
  });
  // The field that had the caret before this repaint gets it back: the
  // tab redraws on every heartbeat, and a form that drops the caret every
  // 25 seconds is not a form anybody can type into.
  if (nodesFocus && nodesFocus.id){
    const f = nodesFocus;
    const el = root.querySelector(`.ndrow[data-node="${CSS.escape(f.id)}"] ${
      f.i === undefined ? "" : `.ndmount[data-i="${f.i}"] `}[data-k="${CSS.escape(f.key)}"]`);
    if (el && document.activeElement !== el){
      el.focus();
      if (el.setSelectionRange && typeof f.pos === "number")
        try{ el.setSelectionRange(f.pos, f.pos); }catch(e){ /* a select has no caret */ }
    }
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
