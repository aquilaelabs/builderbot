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

function nodeTools(n){
  const tc = n.reported?.toolchains || {};
  const names = Object.keys(tc);
  if (n.kind !== "agent") return "";
  if (!names.length)
    return `<div class="sub ndtools dim">no toolchains yet: the Tools tab installs them
      onto this node, and what is here is what a project bound to it can build</div>`;
  return `<div class="sub ndtools">${names.slice(0, 8).map(k =>
    `<span class="pill" title="${esc(String(tc[k] || "present"))}">${
      esc(TOOL_LABELS[k] || k)}</span>`).join(" ")}</div>`;
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
  const from = r.real && r.real !== r.source ? `mounted from ${r.real} (fstab says ${r.source})`
                                             : `mounted${r.ro ? ", read-only" : ""}`;
  return [diff ? `${from}: applying will change it` : from, diff ? "warn" : ""];
}

// The Actions runner on this node (phase 7), as a section: what the census
// says is there, and the labels an install would register with: the node's
// own name among them, which is the label a workflow's runs-on uses to land
// here. Install and Remove are system jobs like the rest of the plane.
function nodeRunnerSection(n, c){
  const rep = n.reported?.services?.["actions-runner"] || {};
  const want = n.services?.["actions-runner"] || {};
  const d = c.draft;
  if (d.runner === undefined) d.runner = {labels: (want.labels || []).filter(x =>
      !["builderbot", "self-hosted", "linux", "x64", "arm64", n.name].includes(x)).join(", "),
    url: want.url || ""};
  // The verdict first, because "installed" and "will actually pick up a job"
  // are different states and the old line buried the difference in the
  // middle of a sentence: a runner registered with no listener reads as
  // healthy right up until a workflow sits in "Waiting for a runner".
  // A runner job in flight says so here, in the section's own line, beside
  // the buttons it takes away: the config section's "applying runner" is a
  // screen above on a phone, and two dead buttons said nothing.
  const job = n.applying?.what === "runner" ? (want.want ? "installing" : "removing") : "";
  const when = t => new Date((t || 0) * 1000).toLocaleString([], {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  const [verdict, vcls] = job
    ? [`${job} now: its job is on the Jobs tab, and the buttons come back when it ends`, "note"]
    : !rep.installed
    ? (n.runner_failed ? [`install failed ${when(n.runner_failed.ended)}: ${n.runner_failed.why || "its job on the Jobs tab says why"}`, "bad"]
      : [want.want ? "install asked for; the node has not reported it yet" : "no runner on this node", ""])
    : rep.busy ? ["running a job right now", "ok"]
    : rep.active ? ["listening: idle, waiting for a job", "ok"]
    : ["installed but NOT listening, so no workflow will reach it: Reinstall runner", "bad"];
  // A listening runner has demonstrably finished registering, whatever the
  // census could read off .runner, so only a runner that is NOT listening
  // gets the "may not have finished" reading. Saying it of a working one sent
  // the operator to reinstall a runner that was fine.
  const detail = rep.installed
    ? [rep.name ? `registered as ${rep.name}`
         : rep.active ? "" : "its registered name did not come back, so the registration may not have finished",
       rep.url || "", rep.labels?.length ? "labels " + rep.labels.join(", ") : ""].filter(Boolean).join(" · ")
    : "";
  const state = verdict + (detail ? " · " + detail : "");
  const busyNow = n.applying || nodeStale(n);
  const why = nodeStale(n) ? esc(staleWhy(n)) : "";
  const body = `
      <div class="sub">GitHub's Actions runner as a service here; its labels decide which workflows land.</div>
      <div class="ndrunner">
        <div class="setrow col">${lbl("", "GitHub URL", "the org or repo the runner registers with")}
        <input data-k="runner:url" value="${esc(d.runner.url)}" spellcheck="false" autocomplete="off"
          placeholder="${esc(want.url || "https://github.com/your-org")}" aria-label="GitHub URL"></div>
        <div class="setrow col">${lbl("", "Extra labels", `comma-separated. builderbot, self-hosted, linux, the arch and ${n.name} are always on`)}
        <input data-k="runner:labels" value="${esc(d.runner.labels)}" spellcheck="false" autocomplete="off"
          placeholder="gpu, android" aria-label="labels"></div>
      </div>
      ${rep.installed || want.want ? `<div class="sub ndrunpin">Any BuilderBot runner answers
        <code>self-hosted</code>; this node's name is the label that pins a job here:
        <pre class="ndcmd">runs-on: [self-hosted, ${esc(n.name.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 40))}]</pre></div>` : ""}
      <div class="actbar">
        <span class="state ndrunstate${vcls ? " " + vcls : ""}">${
          rep.busy ? `<span class="pill note ndrunbusy">running a job</span> ` : ""}${esc(state)}</span>
        <button type="button" data-nrunner="install" ${busyNow ? "disabled" : ""}
          title="${why || "download GitHub's runner onto the node, register it with a one-hour token the controller mints, and run it as a service"}">${
          rep.installed ? "Reinstall runner" : "Install runner"}</button>
        ${rep.installed || want.want ? `<button type="button" class="danger" data-nrunner="remove" ${busyNow ? "disabled" : ""}
          title="${why || "deregister it from GitHub and take the service off the node"}">Remove runner</button>` : ""}
      </div>`;
  const status = job ? job
    : !rep.installed ? (n.runner_failed ? "failed" : want.want ? "asked for" : "none")
    : rep.busy ? "busy" : rep.active ? "listening" : "not listening";
  return docSection("nodes", "runner", "CI runner", status, body, {cls: vcls});
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
    body = `<div class="sub">This node's agent predates sessions on a node: Update agent, and
      it reports the half that runs them.</div>`;
  } else if (!se.up){
    [status, cls] = ["none", "warn"];
    body = `<div class="sub">${esc(se.why || "no session account: provision it with --session-user")}.
      A project bound to this node keeps a dead Claude button until this half is up.</div>`;
  } else {
    const gaps = [];
    const wsErr = (n.reported?.mounts || []).find(m => m.path === "/workspace")?.error || "";
    if (!se.workspace && wsErr) gaps.push(`the projects share is not mounted at /workspace: ${wsErr}${
      /access denied/i.test(wsErr) ? ": the host's NFS export names another address; change the rule there" : ""}`);
    else if (!se.workspace) gaps.push(se.up_s != null && se.up_s >= 0 && se.up_s < 600
      ? `the projects share is not mounted at /workspace yet; this machine came up ${se.up_s} seconds ago, and a network mount lands a moment after boot`
      : "the projects share is not mounted at /workspace: add it under Storage");
    else if (se.writable === false) gaps.push("the projects share is mounted read-only: untick read-only under Storage and apply, or `bb-sandbox readonly /workspace off` on the machine");
    if (!se.boot) gaps.push("the agent reports no boot id: Update agent");
    [status, cls] = gaps.length ? ["blocked", "bad"]
      : [list.length ? `${list.length} open` : "ready", "ok"];
    body = `
      <div class="sub">Sessions run here as <code>${esc(se.user || "?")}</code>, on ports ${
        se.port || "?"} and ${se.ro_port || "?"} (read-only), with ${
        se.claude ? esc(se.claude) : "no Claude Code installed for that account yet"}.
        A project bound to this node opens its Claude sessions on this machine.</div>
      ${gaps.map(g => `<div class="sub bad">${esc(g)}</div>`).join("")}
      ${list.length ? `<div class="sub">open now: ${list.map(s => `<code>${esc(s.name)}</code>`).join(", ")}:
        listed on the Sessions card, and ended from there</div>` : ""}`;
  }
  return docSection("nodes", "sessions", "Sessions", status, body, {cls});
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
  const body = `
    <div class="sub">What this container's paths are called on the node, for its daemon's
      bind mounts. With the projects share at <code>/workspace</code> on both, leave it blank.</div>
    <div class="ndpaths actbar">
      <div class="setrow col grow">${lbl("", "Path mapping", "here:there pairs, comma-separated. Blank when the projects share is at /workspace on both")}
      <input data-k="paths" value="${esc(c.draft.pathsText)}" spellcheck="false" autocomplete="off"
        placeholder="/workspace:/workspace, /devdata:/mnt/user/appdata/bb-dev"
        aria-label="path mapping"></div>
      <button type="button" data-nd="paths" title="save the mapping onto the node's record">Save paths</button>
      <button type="button" data-nd="check-paths"
        title="check that both machines mean the same directory by the projects share">Check</button>
    </div>
    <div class="sub ndcheck" hidden></div>
    ${!n.reported?.sandbox ? "" : `<div class="actbar">
      <span class="state">${n.config?.lock
        ? "System changes are locked to this node's own console: Apply storage, Apply network and a root command are refused until Unlock."
        : "Lock keeps this node's mounts, address and root managed at the OS level: Apply storage, Apply network and a root command are refused while it is on."}</span>
      <button type="button" data-nd="${n.config?.lock ? "unlock" : "lock"}"
        title="${n.config?.lock ? "let the dashboard apply storage, network and root commands here again"
          : "refuse system changes from here: the machine's fstab, address and root stay its administrator's at the console"}">${
        n.config?.lock ? "Unlock" : "Lock system changes"}</button>
    </div>`}
    ${state?.settings?.settings?.debug_mode?.value ? `
    <div class="actbar nddebug">
      <span class="state">A session here reads its own project's CI and test logs. Machine logs are
        a grant, this node's alone, and its own counts.</span>
      <button type="button" data-nd="debug"
        title="which nodes' agent, runner and terminal logs a session on this node may read">Debug settings${
        (n.config?.log_from || []).length ? ` (${(n.config.log_from || []).length})` : ""}</button>
    </div>` : ""}
    <div class="actbar">
      <span class="state">Drain finishes what is running and takes nothing new: what makes the machine safe
        to reboot. Revoke and Remove are the way out; the row and its history stay either way.</span>
      <button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
        title="${n.state === "draining" ? "take new work again"
          : "finish what is running, accept nothing new: what makes a node safe to reboot"}">${
        n.state === "draining" ? "Undrain" : "Drain"}</button>
      ${!n.agent?.revoked ? `<button type="button" data-nd="cache-clear" ${stale || inflight("cache-clear") ? "disabled" : ""}
        title="${stale ? esc(staleWhy(n))
          : inflight("cache-clear") ? "already clearing"
          : "drop this node's build caches: every project's. A cold cache costs the next build time, never correctness"}">${
        inflight("cache-clear") ? "Clearing…" : "Clear cache"}</button>` : ""}
      ${!n.agent?.revoked ? `<button type="button" class="danger" data-nd="revoke"
        title="cut this node's credential. It stops being able to dial in; the row and its history stay. The way back is a new enrollment">Revoke</button>` : ""}
      <button type="button" class="danger" data-nd="retire"
        title="take it off every list. Its row and its history stay: an id is never reused">Remove</button>
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
    ? `${n.name} runs agent ${mine} and this controller ships ${ship}: a DIFFERENT `
      + `compatibility window (${agentWindow(mine)} against ${agentWindow(ship)}). `
      + `Inside one window any agent works with any controller; across one that was `
      + `never promised, so update it before relying on this node`
    : `${n.name} runs agent ${mine} and this controller ships ${ship}: press `
      + `Update agent first, so nothing is sent that the agent may not know`;
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
    data: "job workspaces and AVDs", packages: "toolchains installed here",
    cache: "build caches, per project", artifacts: "what projects built, per project",
  };
  const stores = ["data", "packages", "cache", "artifacts"].map(role => {
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
      ? [`the last ${kind} apply ${la.state === "canceled" ? "was canceled" : "failed"}${
          la.error ? ": " + la.error : ""}: its log is on the Jobs tab. Nothing on the `
         + "node changed for whatever did not apply; fix it and Apply again.", "bad"]
      : null;
  // The state line answers one question: is there anything to press Apply
  // for, and names the changes when there is, so the button is not a leap.
  const [status, statusCls] = busyNow
    ? [`applying ${busyNow.what}${busyNow.what === "network" ? ": waiting for it to dial back in" : "…"}`, "note"]
    : stale ? [staleWhy(n), windowGap(n) ? "bad" : "warn"]
    : c.dirty ? ["unsaved: Save keeps it on the record; Apply makes the node match", "warn"]
    : !drift ? ["nothing configured yet: the node runs on whatever it was set up with", ""]
    : pending.length ? [`${pending.length} change${pending.length === 1 ? "" : "s"} to apply: ${
        pending.slice(0, 3).join("; ")}${pending.length > 3 ? "; …" : ""}`, "warn"]
    : drift.network === "unknown"
      ? ["the node matches what is saved here, except dhcp, which cannot be told from here", ""]
      : ["the node matches what is saved here", "ok"];
  const saveBtn = `<button type="button" data-nsave ${c.dirty ? "" : "disabled"}
      title="keep this on the node's record: Apply is what makes the node match it">Save</button>`;
  const storage = `
      <div class="sub">Mounts: what this node mounts at boot, applied through bb-sandbox on it${
        d.fromNode ? `. <span class="dim">These are the ones the node reports; nothing has been
        saved here yet, so editing and saving is what puts this page in charge of them.</span>` : ""}</div>
      ${mounts}
      <div><button type="button" data-madd>+ mount</button></div>
      <div class="sub">Where the agent keeps job data, toolchains, caches and built artifacts.
        Each is its own directory; a system path is refused.</div>
      ${stores}
      <div class="actbar">
        <span class="state ndconfstate${(failedFor("storage") || [0, statusCls])[1] ? " " + (failedFor("storage") || [0, statusCls])[1] : ""}">${
          esc((failedFor("storage") || [status])[0])}</span>
        ${saveBtn}
        <button type="button" data-napply="storage" ${
          busyNow || c.dirty || stale || locked || !drift?.storage.length ? "disabled" : ""}
          title="${locked ? LOCKED_WHY : stale ? esc(staleWhy(n))
            : !drift ? "nothing is saved to apply"
            : !drift.storage.length ? "the node already has the mounts and stores saved here"
            : "mounts and stores: a system job on the node, through bb-sandbox"}">Apply storage</button>
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
      : `<div class="sub dim ndguest">Storage and Network are not offered: this node was not
         provisioned as a sandbox (${rep.system === "darwin" ? "a Mac, enrolled as a guest" : "a container, or somebody's own machine"}), so its mounts
         and its address are its own to change.${rep.system === "darwin"
           ? " Its packages land in its own darwin scope of the store; Xcode is installed on the Mac itself." : ""}</div>`}
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
  // #16), takes no packages (#26), and every section on this tab is about
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
    const inflight = t => (n.jobs || []).some(j => j.type === t);
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
            updating ? `updating to agent ${esc(nodesAgent?.version || "")}; it swaps itself in and dials back; the row follows its next hello`
            : stale ? `${windowGap(n) ? "out of window" : "behind"}: ${esc(staleWhy(n))}`
            : `Test runs uname through the agent: the channel, end to end`}</span>
          ${stale ? `<button type="button" data-nd="update-agent" ${updating ? "disabled" : ""}
            title="${updating ? "the update is queued: the row follows the agent's next hello"
              : `hand the node the agent this controller ships (${esc(nodesAgent.version)}); it swaps itself in place and re-execs; nothing else restarts, and it waits for its own jobs to finish first`}">${
            updating ? "Updating…" : "Update agent"}</button>` : ""}
          <button type="button" data-nd="test" title="run uname on it through the agent: the channel, end to end">Test</button>
        </div>
        <div class="sub ndtest" hidden></div>` : "";
    const health = docSection("nodes", "health", "Health",
      n.kind === "agent" ? (n.live ? "live" : "quiet") : "", `
        ${nodeMeters(n) || `<div class="sub dim">nothing measured yet</div>`}
        ${nodeTools(n)}
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
        ${plane ? nodeConfSections(n) : ""}
        ${n.kind === "agent" && !pending ? nodeAdvancedSection(n, stale, inflight) : ""}
      </div>
    </div>`;
  }).join("");
  // Nothing enrolled. Said where the rows would be, rather than an empty
  // picker over an empty page: the Enroll button above is the whole of what
  // there is to do here.
  const none = live.length ? "" :
    `<div class="empty ndnone">No node is enrolled. A node is the machine the
      work runs on (builds, tests, CI and the Android emulator) and this
      container runs none of it. <b>Enroll node…</b> above mints a token and
      shows the one command to run on that machine.</div>`;
  // Enrolling is a dialog now (#ndmodal), not two panels appended here; see
  // the markup's comment. Which means a poll landing while it is open cannot
  // take the name being typed with it, because this list is not where it is.
  d.list.innerHTML = rows + none
    + (!nodesList.length ? `<div class="empty">no nodes, which cannot happen:
        local is seeded at boot. If you can read this, the store broke.</div>` : "");
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
        <div class="hint">A session on ${esc(n.name)} always reads its own project's CI and
          test logs. These are the machines whose agent, runner and terminal logs it may
          read as well, each of which is root's on that box.</div>
        <div class="logset">${rows.map(x => `
          <div class="logdays setrow"><label class="ndcap">
            <input type="checkbox" data-grant="${esc(x.id)}"${have.has(x.id) ? " checked" : ""}>
            <span>${esc(x.name)}${x.id === n.id ? ": itself" : ""}</span></label></div>`).join("")}
        </div>
        ${rows.length ? "" : `<div class="hint">No other node is enrolled.</div>`}
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
      const j = await nodeAct({action: "log-grant", id: n.id, from});
      if (j.error){ notify(j.error, true); return; }
      shut();
      notify(from.length ? `${n.name} may read ${from.length} node's logs`
                         : `${n.name} reads no machine logs`);
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
        <div class="hint">The node dials in with this token, which is good once and
          for a day. What it can build is what the Tools tab installs on it afterwards.</div>
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
        <div class="hint">shown once; the controller keeps only a hash. On a
          fresh machine, the provisioner installs docker and the agent
          together:</div>
        <pre class="ndcmd">sudo bash provision-linux.sh --controller ${esc(m.url)} --token ${esc(m.token)}${
          m.user && m.user !== "bb" ? ` --user ${esc(m.user)}` : ""}</pre>
        <div class="hint">on a Mac, as yourself: one directory and a launchd agent, no root:</div>
        <pre class="ndcmd">bash provision-macos.sh --controller ${esc(m.url)} --token ${esc(m.token)}</pre>
        <div class="hint">or on a machine that already has python3, the agent alone:</div>
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
        <div class="hint">A node is a machine the controller sends work to. Pick what runs
          it and this writes the machine: sized the same everywhere, with an identity of
          its own.</div>
        <div class="setrow col">${lbl("vm_hv", "Runs on")}
          <select id="vm_hv" data-vk="hv">${kinds.map(k =>
            `<option value="${esc(k.id)}"${k.id === kind.id ? " selected" : ""}>${
              esc(k.label)}</option>`).join("")}</select></div>
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
              + `It restarts the agent, which ends the ${here.length} session`
              + `${here.length === 1 ? "" : "s"} open there`
              + `${mine.length ? ` (${mine.length} of them a Claude conversation)` : ""}`
              + `. Their transcripts are kept and the tabs reopen, but whatever `
              + `they were running stops.`)) return;
      }
      if (act === "cache-clear"
          && !confirm("Clear this node's build caches? Every project's Gradle, "
                      + "npm and snapshot cache there goes; the next build of "
                      + "each re-downloads what it needs.")) return;
      // The verb, said on the button for the round trip and, for the
      // actions whose effect the row cannot see at once: beyond it.
      busy(b, {"update-agent": "Updating", test: "Asking", drain: "Draining",
               online: "Undraining", "cache-clear": "Clearing", revoke: "Revoking",
               retire: "Removing", paths: "Saving", "check-paths": "Checking"}[act] || "Working");
      if (act === "update-agent"){
        nodesUpdating[id] = Date.now();
        const j = await nodeAct({action: "update-agent", id});
        if (j.current){ delete nodesUpdating[id]; notify(`already on ${j.version}`); }
        else if (j.ok) notify("update queued: the row follows the agent's next hello");
        else delete nodesUpdating[id];
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
          st.textContent = "unsaved: Save keeps it on the record; Apply makes the node match";
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
    const want = b.dataset.nrunner === "install";
    if (!want && !confirm(`Remove the runner from ${n?.name || "this node"}?\n\nIt is deregistered `
        + `from GitHub first; workflows that target its label will wait for a runner.`)) return;
    const labels = (c.draft.runner?.labels || "").split(",").map(x => x.trim()).filter(Boolean);
    await pressing(b, () => { busy(b, want ? "Installing" : "Removing");
      return nodeAct({action: "runner", id, want, labels, url: c.draft.runner?.url || ""}); });
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
          + `${moving.map(m => `${m.role} from ${m.from} to ${m.to}`).join(", and ")}. The `
          + `contents are copied across first and the job waits for that; nothing is deleted, `
          + `so the old cop${moving.length === 1 ? "y stays" : "ies stay"} where ${
              moving.length === 1 ? "it is" : "they are"} for you to remove.`)) return;
    }
    await pressing(b, () => { busy(b, "Applying"); return nodeAct({action: "apply", id, what}); });
  });
}
