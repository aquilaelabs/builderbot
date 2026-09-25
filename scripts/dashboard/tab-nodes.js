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

function openNodesTab(){
  openTab({kind: "nodes", arg: "__nodes", label: "Nodes"});
  loadNodes();
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
// cancelling leaves the button alive.
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
    return `<div class="sub ndtools dim">no toolchains yet: install them from the Tools tab</div>`;
  // Held recipes whose system libraries this machine lacks (roadmap R51),
  // said here rather than left for a build to fail on: the store is shared,
  // the libraries are each machine's own, and the Tools tab installs them.
  const unmet = Object.entries(n.reported?.sysdeps?.unmet || {});
  const sys = unmet.length
    ? `<div class="sub ndsys warn">System packages missing for ${unmet.map(([r, ps]) =>
        `${esc(r)} (${esc(ps.join(" "))})`).join(", ")}: install them from the Tools tab</div>` : "";
  return `<div class="sub ndtools">${names.slice(0, 8).map(k =>
    `<span class="pill" title="${esc(String(tc[k] || "present"))}">${
      esc(TOOL_LABELS[k] || k)}</span>`).join(" ")}</div>${sys}`;
}

function nodeStatePill(n){
  if (n.state === "pending")
    return `<span class="pill note">waiting for enrollment</span>`;
  const cls = {online: "ok", draining: "warn"}[n.state] || "";
  const live = n.kind !== "agent" ? ""
    : n.agent?.revoked ? ` <span class="pill bad ndlive">revoked</span>`
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
      network: {mode: "dhcp", address: "", gateway: "", dns: [], interface: "", ...(d.network || {})},
    };
  }
  return c;
}

// What the row says beside a desired mount, from the agent's census: the
// reported half of desired-vs-reported, in words rather than a grey nothing.
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
  const body = `
      <div class="sub">One runner per git host; its labels decide which workflows land here.</div>
      ${addbar}
      ${rows || `<div class="sub dim ndrunnone">no runner on this node</div>`}
      ${slots.length ? `<div class="sub ndrunpin">This node's name pins a job here:
        <pre class="ndcmd">runs-on: [self-hosted, ${esc(n.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 40))}]</pre></div>` : ""}`;
  const status = !slots.length ? "none" : worst === "bad" ? "attention" : worst === "note" ? "working"
    : reps.some(r => r.busy) ? "busy" : reps.some(r => r.active) ? "listening" : "asked for";
  return docSection("nodes", "runner", "CI runners", status, body, {cls: worst});
}

// The node's sessions (roadmap #24): whether this machine runs them, what a
// session there gets, and which are open right now. The reasons a project
// cannot be sent here are the proxy's (server.session_target), repeated in
// the same words so the row and the refusal agree.
function nodeSessionsSection(n){
  const se = n.reported?.session;
  const list = n.reported?.sessions || [];
  let status, cls, body;
  if (!se || typeof se !== "object"){
    [status, cls] = ["agent too old", "warn"];
    body = `<div class="sub">Update the agent: this one is too old to run sessions.</div>`;
  } else if (!se.up){
    [status, cls] = ["none", "warn"];
    body = `<div class="sub">${esc(se.why || "no session account: provision it with --session-user")}.
      No Claude session can start here until it is up.</div>`;
  } else {
    const gaps = [];
    const wsErr = (n.reported?.mounts || []).find(m => m.path === "/workspace")?.error || "";
    if (!se.workspace && wsErr) gaps.push(`the projects share is not mounted at /workspace: ${wsErr}${
      /access denied/i.test(wsErr) ? ": the host's NFS export names another address; change the rule there" : ""}`);
    else if (!se.workspace) gaps.push(se.up_s != null && se.up_s >= 0 && se.up_s < 600
      ? `the projects share is not mounted yet: the machine booted ${se.up_s} seconds ago. Check again in a minute`
      : "the projects share is not mounted at /workspace: add it under Storage");
    else if (se.writable === false) gaps.push("the projects share is read-only: untick read-only under Storage and press Apply storage");
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
      ${nodeSessNetRow(n)}
      ${nodeTurnsRow(n)}`;
  }
  return docSection("nodes", "sessions", "Sessions", status, body, {cls});
}

// Claude Code on this node (claudecode.py): what the session account runs
// against the latest the controller knows, a check on demand, and the one
// way it is updated. The update ends every Claude session here first and
// starts none again: the project rows do, when a person presses them.
// A session cannot ask for this and cannot change the copy it runs.
// What the last press here answered, when it was a refusal: on the row,
// not only in a toast, or a press that was refused for the agent being
// behind read as "it said updating and nothing happened" (23 Sep).
let nodesClaudeSaid = {};
function nodeClaudeSection(n){
  const cc = state?.claude_code || {};
  const me = cc.nodes?.[n.id] || {};
  const se = n.reported?.session;
  const inst = me.installed || "";
  const latest = cc.latest || "";
  const stale = nodeStale(n);
  let status, cls;
  if (!se || typeof se !== "object" || !se.up) [status, cls] = ["no session account", "warn"];
  else if (me.updating) [status, cls] = ["updating", "warn"];
  else if (!inst) [status, cls] = ["not installed", "bad"];
  else if (me.behind) [status, cls] = [`${inst}, ${latest} is out`, "warn"];
  else [status, cls] = [latest ? `${inst}, up to date` : inst, "ok"];
  const checked = cc.checked ? `checked ${ago(cc.checked)}` : "not checked yet";
  const known = latest ? `latest ${latest}, ${checked}`
    : cc.error ? `could not check: ${cc.error}` : checked;
  const open = (state?.sessions || []).filter(s => s.node_id === n.id && tmuxBase(s.name).startsWith("claude-")).length;
  const auto = !!state?.settings?.settings?.claude_autoupdate?.value;
  const dead = !se?.up || me.updating || (inst && !me.behind) || stale;
  const body = `
    <div class="sub">${!se?.up ? "No session account here, so nothing runs Claude Code."
      : inst ? `Claude Code ${esc(inst)}${me.behind ? `; ${esc(latest)} is out.` : "."}`
      : "No Claude Code yet: Update installs it."} Checked every six hours.</div>
    ${stale ? `<div class="sub bad">${esc(staleWhy(n))}</div>` : ""}
    ${nodesClaudeSaid[n.id] ? `<div class="sub bad">${esc(nodesClaudeSaid[n.id])}</div>` : ""}
    <div class="actbar">
      <span class="state">${esc(known)}</span>
      <button type="button" data-nd="claude-check" ${cc.checking ? "disabled" : ""}
        title="ask now what the latest Claude Code is">Check for updates</button>
      <button type="button" data-nd="claude-update" ${dead ? "disabled" : ""}
        title="${me.updating ? "an update is queued or running here"
               : stale ? "update the agent first"
               : !se?.up ? "no session account to update it for"
               : inst && !me.behind ? "already on the latest known"
               : `install ${latest || "the current Claude Code"} here: ends the ${open} Claude session${open === 1 ? "" : "s"} open on this node first`}">Update</button>
    </div>
    <div class="sub dim">Update ends the Claude sessions here; start them again from the project rows.${
      auto ? " Before a session starts on a node that is behind, Claude Code is updated there first (Controller settings)." : ""}</div>`;
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
  return `<div class="logdays setrow col">
      ${lbl(inp, "Claude sessions working at once", "a prompt past it waits for a turn instead of starting. 0 is no limit")}
      <input id="${esc(inp)}" data-k="turns" type="number" min="0" max="64" step="1" inputmode="numeric"
        value="${esc(c.draft.turnsText)}">
    </div>
    <div class="logdays setrow col">
      ${lbl(winp, "Test workers", `how many workers a test run here may use, as BB_TEST_WORKERS in its environment. 0 uses every core${
        n.reported?.cpu ? ` (${n.reported.cpu} here)` : ""}`)}
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
// bind sources over there. Nearly always the identity now that the projects
// share is mounted at /workspace on both sides: path parity is a rule, not
// a setting, so it lives under Advanced with the actions that are rarely
// pressed, and says why it is there. Still read by devapp.host_map for
// every node addressed, so it is not gone.
function nodeAdvancedSection(n, stale, inflight){
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
    <div class="sub">Only needed when the projects share is not at <code>/workspace</code> on the node.</div>
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
    ${state?.settings?.settings?.debug_mode?.value ? `
    <div class="actbar nddebug">
      <span class="state">Which machines' logs a session here may read.</span>
      <button type="button" data-nd="debug"
        title="which nodes' agent, runner and terminal logs a session on this node may read">Debug settings${
        (n.config?.log_from || []).length ? ` (${(n.config.log_from || []).length})` : ""}</button>
    </div>` : ""}
    <div class="actbar">
      <span class="state">Drain finishes what is running and takes nothing new.</span>
      <button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
        title="${n.state === "draining" ? "take new work again"
          : "finish what is running and take nothing new, so the machine can reboot"}">${
        n.state === "draining" ? "Undrain" : "Drain"}</button>
      ${!n.agent?.revoked ? `<button type="button" data-nd="cache-clear" ${stale || inflight("cache-clear") ? "disabled" : ""}
        title="${stale ? esc(staleWhy(n))
          : inflight("cache-clear") ? "already clearing"
          : "drop every project's build cache here; the next build refetches"}">${
        inflight("cache-clear") ? "Clearing…" : "Clear cache"}</button>` : ""}
      ${!n.agent?.revoked ? `<button type="button" class="danger" data-nd="revoke"
        title="cut its credential; it cannot dial in until enrolled again">Revoke</button>` : ""}
      <button type="button" class="danger" data-nd="retire"
        title="take it off every list; its history stays">Remove</button>
      ${n.reported?.sandbox && !n.agent?.revoked ? `<button type="button" class="danger" data-nd="uninstall"
        ${inflight("uninstall") ? "disabled" : ""}
        title="remove BuilderBot from the machine: the agent, its accounts, mounts and files; docker and the shares stay">${
        inflight("uninstall") ? "Uninstalling…" : "Uninstall"}</button>` : ""}
    </div>`;
  return docSection("nodes", "advanced", "Advanced",
                    n.state === "draining" ? "draining" : n.config?.lock ? "locked" : "",
                    body, {cls: n.state === "draining" ? "warn" : ""});
}
function nodeStale(n){
  return n.kind === "agent" && n.agent?.digest && nodesAgent?.digest
    && n.agent.digest !== nodesAgent.digest && !n.agent?.revoked;
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
    ${nodeRunnerSection(n, c)}
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
    // A job of this type queued or running on this node. pressing() greys a
    // button for the round trip; this is what keeps it grey afterwards,
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
        <div class="sub">${esc(a.asker ? a.asker + "'s session in " + (a.project || "a project") : a.project || "a session")} asks to run this as root on ${esc(a.node_name)} · ${a.left > 60
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
            updating ? `Updating to agent ${esc(nodesAgent?.version || "")}. This row refreshes when the node reports back.`
            : stale ? `${windowGap(n) ? "out of window" : "behind"}: ${esc(staleWhy(n))}`
            : `Test checks that this node answers.`}</span>
          ${stale ? `<button type="button" data-nd="update-agent" ${updating ? "disabled" : ""}
            title="${updating ? "Update queued: this row refreshes when the node reports back"
              : `Update the agent to ${esc(nodesAgent.version)} once its running jobs finish`}">${
            updating ? "Updating…" : "Update agent"}</button>` : ""}
          <button type="button" data-nd="test" title="check that this node answers">Test</button>
        </div>
        <div class="sub ndtest" hidden></div>` : "";
    const health = docSection("nodes", "health", "Health",
      n.kind === "agent" ? (n.live ? "live" : "quiet") : "", `
        ${nodeMeters(n) || `<div class="empty">nothing measured yet</div>`}
        ${nodeTools(n)}
        ${nodeGit(n)}
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
        ${agentBar}
      </div>
      <div class="ndsections">
        ${health}
        ${n.kind === "agent" && !pending ? nodeSessionsSection(n) : ""}
        ${n.kind === "agent" && !pending ? nodeClaudeSection(n) : ""}
        ${plane ? nodeConfSections(n) : ""}
        ${n.kind === "agent" && !pending ? nodeAdvancedSection(n, stale, inflight) : ""}
      </div>
    </div>`;
  }).join("");
  // Nothing enrolled. Said where the rows would be, rather than an empty
  // picker over an empty page: the Enroll button above is the whole of what
  // there is to do here.
  const none = live.length ? "" :
    `<div class="empty ndnone">No node yet. Press <b>Enroll node</b> to get the command
      that adds a machine for builds, tests and sessions.</div>`;
  // Enrolling is a dialog now (#ndmodal), not two panels appended here; see
  // the markup's comment. Which means a poll landing while it is open cannot
  // take the name being typed with it, because this list is not where it is.
  d.list.innerHTML = rows + none
    + (!nodesList.length ? `<div class="empty">The node list could not be read.</div>` : "");
  d.setFoot(`A node does the work of the projects bound to it: pick one in a project's
    settings. Jobs run as the enrolled account, never root.`);
  wireNodesTab(d.el);
}

function wireNodesTab(root){
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
  // Which nodes' MACHINE logs a session on this one may read. A tick per
  // node, this one first and named as itself, because its own journal is as
  // much root's as anybody else's; "it is only looking at itself" is the
  // reasoning that makes a boundary stop meaning anything. Only reachable
  // while the controller's debug switch is on; the switch grants nothing.
  const debugForm = (n) => {
    document.getElementById("ndTitle").textContent = `Debug settings: ${n.name}`;
    boxWidth(false);
    const rows = (nodesList || []).filter(x => x.kind === "agent" && x.state !== "retired");
    const have = new Set(n.config?.log_from || []);
    body.innerHTML = `<div class="field">
        <div class="hint">Machine logs a session on ${esc(n.name)} may read, besides its own project's.</div>
        <div class="logset">${rows.map(x => `
          <div class="logdays setrow"><label class="ndcap">
            <input type="checkbox" data-grant="${esc(x.id)}"${have.has(x.id) ? " checked" : ""}>
            <span>${esc(x.name)}${x.id === n.id ? ": itself" : ""}</span></label></div>`).join("")}
        </div>
        ${rows.length ? "" : `<div class="hint">No other node is enrolled.</div>`}
      </div>
      <div class="field">
        <div class="logdays setrow"><label class="ndcap">
          <input type="checkbox" id="ndDiag"${n.config?.diag ? " checked" : ""}>
          <span>The controller's diagnostics</span></label></div>
        <div class="hint">Lets an administrator's session here run bb diag.</div>
      </div>
      <div class="foot">
        <button type="button" class="primary" id="ndDbgSave">Save</button>
        <button type="button" id="ndDbgCancel">Cancel</button>
      </div>`;
    body.querySelector("#ndDbgCancel").onclick = shut;
    const go = body.querySelector("#ndDbgSave");
    go.onclick = () => pressing(go, async () => {
      const from = [...body.querySelectorAll("[data-grant]")]
        .filter(c => c.checked).map(c => c.dataset.grant);
      const diag = body.querySelector("#ndDiag").checked;
      const j = await nodeAct({action: "log-grant", id: n.id, from, diag});
      if (j.error){ notify(j.error, true); return; }
      shut();
      notify((from.length ? `${n.name} may read ${from.length} node's logs`
                          : `${n.name} reads no machine logs`)
             + (diag ? ", and the controller's diagnostics" : ""));
      loadNodes();
    });
  };

  const mintForm = () => {
    document.getElementById("ndTitle").textContent = "Enroll a node";
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
        <div class="hint">The token is good once, for a day.</div>
      </div>
      <div class="foot">
        <button type="button" class="primary" id="ndEnGo">Mint a token</button>
        <button type="button" id="ndEnCancel">Cancel</button>
      </div>`;
    // No focus, like every other dialog here: on a phone it would raise the
    // keyboard over the box it just opened.
    body.querySelector("#ndEnCancel").onclick = shut;
    const go = body.querySelector("#ndEnGo");
    go.onclick = () => pressing(go, async () => {
      busy(go, "Minting");
      const name = body.querySelector("#ndEnName").value;
      // The account rides along, so the row says the right one before the
      // machine exists and the command below carries it. The record follows
      // whatever the agent reports at enrollment either way; this is what
      // stops the two disagreeing in between, and what stops somebody
      // having to remember the flag.
      const user = body.querySelector("#ndEnUser").value.trim() || "bb";
      const r = await nodeAct({action: "enroll", name, user});
      if (r.error){ mintForm(); return; }   // nodeAct has said why
      // The URL the node should dial: this page's origin, which is the only
      // address the browser knows the controller by. A proxy in front is the
      // operator's to substitute.
      mintToken({name: name || "node", token: r.token, url: location.origin, user});
      nodesRev++; drawPanes();              // the pending row joins the picker
    });
    body.querySelector("#ndEnName").onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); go.click(); }
    };
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
      if (r.catalog){ vmKinds = r.catalog; if (!body.querySelector(".vmmade")) vmForm(null); }
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
    box.querySelectorAll("[data-nd]").forEach(b => b.onclick = () => pressing(b, async () => {
      const act = b.dataset.nd;
      if (act === "debug"){
        const n = (nodesList || []).find(x => x.id === id);
        if (n){ modal.hidden = false; debugForm(n); }
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
      if (act === "revoke"
          && !confirm("Revoke this node's credential? It will stop being able "
                      + "to dial in, and the only way back is enrolling it "
                      + "again with a new token.")) return;
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
      if (act === "claude-update"){
        const here = (state?.sessions || []).filter(x => x.node_id === id && tmuxBase(x.name).startsWith("claude-"));
        if (!confirm(`Update Claude Code on ${(nodesList || []).find(n => n.id === id)?.name || "this node"}?\n\n`
              + (here.length ? `It ends the ${here.length} Claude session${here.length === 1 ? "" : "s"} open there first; `
                             : "No Claude session is open there; ")
              + "nothing starts again on its own: press Claude on a project's row afterwards.")) return;
      }
      if (act === "cache-clear"
          && !confirm("Clear this node's build caches? Every project's Gradle, "
                      + "npm and snapshot cache there goes; the next build of "
                      + "each re-downloads what it needs.")) return;
      // The verb, said on the button for the round trip and, for the
      // actions whose effect the row cannot see at once: beyond it.
      busy(b, {"update-agent": "Updating", "claude-check": "Checking", "claude-update": "Updating", test: "Asking", drain: "Draining",
               online: "Undraining", "cache-clear": "Clearing", revoke: "Revoking",
               retire: "Removing", uninstall: "Uninstalling", paths: "Saving", "check-paths": "Checking",
               rename: "Renaming", turns: "Saving"}[act] || "Working");
      if (act === "claude-check"){
        const j = await nodeAct({action: "claude-check", id});
        nodesClaudeSaid[id] = j.error || (j.version ? "" : `checked; the download service gave no version${j.error ? ": " + j.error : ""}`);
        if (j.error) notify(j.error, true);
        else notify(j.version ? `the latest Claude Code is ${j.version}` : "checked; the download service gave no version");
        refresh();
        return;
      }
      if (act === "claude-update"){
        const j = await nodeAct({action: "claude-update", id});
        nodesClaudeSaid[id] = j.error || "";
        if (j.error) notify(j.error, true);
        else notify(`Claude Code update queued${j.ended?.length ? `; ${j.ended.length} session${j.ended.length === 1 ? "" : "s"} ended` : ""}: the row follows the job`);
        loadNodes(); refresh();
        return;
      }
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
      await nodeAct({action: act, id});
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
        d.network[f] = f === "dns" ? el.value.split(",").map(x => x.trim()).filter(Boolean) : el.value;
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
