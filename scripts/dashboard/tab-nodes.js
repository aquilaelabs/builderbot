// The Nodes tab: the node registry, editable. Phases 2 and 3 of
// docs/nodes.md — CRUD over ssh docker hosts, capability toggles, labels,
// pool, concurrency, test, drain, retire; and now enrollment: minting the
// one-time token an agent dials in with, the live/quiet state of each agent
// node, the numbers its heartbeat carries, and revoking its credential. Its
// own classic script beside index.html, per the new-surface rule (§13): same
// page, same global scope, one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs —
// this file only fills slots. Data comes from /api/v1/nodes, fetched when the
// "nodes" revision token moves, never from the status poll.

let nodesList = null;            // last answer, or null before the first
let nodesRev = 0;                // bumped when it changes, so panes repaint
let nodesErr = "";
let nodesOpenForm = "";          // "" | "ssh" | "agent": which add form is up
let nodesMinted = null;          // the last enroll token, shown once, then gone
let nodesAgent = null;           // the agent this controller ships: {digest, version}
let nodesPick = "";              // which node the tab is showing, "" until the first draw
// The configuration plane's editor state, per node (docs/nodes.md §12): the
// fold's open flag and the DRAFT the operator is typing. Kept here and not in
// the DOM because the tab repaints on every heartbeat — a field that lived
// only in the row would lose its text every 25 seconds.
const nodesConf = {};
let nodesFocus = null;           // {id, key, i}: the field to refocus after a repaint

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
// coming back in a record still renders — data wins over this table.
// What a node can do for a project is what is INSTALLED on it, not a set of
// toggles: a project names one node and that node does all of its work (the
// operator's decision, 2 Sep). So the row shows the toolchains the census
// found, and the Tools tab is where they are added. The capability field
// still exists underneath — it is the vocabulary of the node-side refusal,
// §15 door 7 — and every node now carries the full set.
const TOOL_LABELS = {java: "java", "android-sdk": "android sdk", emulator: "emulator",
                     flutter: "flutter", dotnet: ".NET", node: "node", go: "go"};

function nodeTools(n){
  const tc = n.reported?.toolchains || {};
  const names = Object.keys(tc);
  if (n.kind !== "agent") return "";
  if (!names.length)
    return `<div class="sub ndtools dim">no toolchains yet — the Tools tab installs them
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
  if (!r.mounted) return [`not mounted${r.source ? ` — fstab has ${r.source}` : ""}`, "bad"];
  const from = r.real && r.real !== r.source ? `mounted from ${r.real} (fstab says ${r.source})`
                                             : `mounted${r.ro ? ", read-only" : ""}`;
  return [diff ? `${from} — applying will change it` : from, diff ? "warn" : ""];
}

// The Actions runner on this node (phase 7): what the census says is
// there, and the labels an install would register with — the node's own
// name among them, which is the label a workflow's runs-on uses to land
// here. Install and Remove are system jobs like the rest of the fold.
function nodeRunnerSection(n, c){
  const rep = n.reported?.services?.["actions-runner"] || {};
  const want = n.services?.["actions-runner"] || {};
  const d = c.draft;
  if (d.runner === undefined) d.runner = {labels: (want.labels || []).filter(x =>
      !["builderbot", "self-hosted", "linux", "x64", "arm64", n.name].includes(x)).join(", "),
    url: want.url || ""};
  const state = rep.installed
    ? `registered as ${rep.name || "?"}${rep.url ? " with " + rep.url : ""} — ${
        rep.busy ? "running a job" : rep.active ? "listening" : "installed, not listening"}${
        rep.labels?.length ? " · labels " + rep.labels.join(", ") : ""}`
    : want.want ? "install asked for; the node has not reported it yet" : "no runner on this node";
  const busy = n.applying || nodeStale(n);
  const why = nodeStale(n) ? esc(staleWhy(n)) : "";
  return `
      <div class="ndsec">CI runner — GitHub's Actions runner as a service here; its labels decide which workflows land</div>
      <div class="ndrunner">
        <input data-k="runner:url" value="${esc(d.runner.url)}" spellcheck="false" autocomplete="off"
          placeholder="${esc(want.url || "https://github.com/your-org — the org or repo it registers with")}" aria-label="GitHub URL">
        <input data-k="runner:labels" value="${esc(d.runner.labels)}" spellcheck="false" autocomplete="off"
          placeholder="extra labels, comma-separated — builderbot, self-hosted, linux, the arch and ${esc(n.name)} are always on" aria-label="labels">
      </div>
      <div class="sub ndrunstate${rep.installed && !rep.active ? " warn" : ""}">${esc(state)}</div>
      <div class="acts">
        <span class="sp"></span>
        <button type="button" data-nrunner="install" ${busy ? "disabled" : ""}
          title="${why || "download GitHub's runner onto the node, register it with a one-hour token the controller mints, and run it as a service"}">${
          rep.installed ? "Reinstall runner" : "Install runner"}</button>
        ${rep.installed || want.want ? `<button type="button" class="rm" data-nrunner="remove" ${busy ? "disabled" : ""}
          title="${why || "deregister it from GitHub and take the service off the node"}">Remove runner</button>` : ""}
      </div>`;
}

// An ssh node's path mapping (docs/nodes.md §11): what this container's
// paths are called on that machine, because its daemon resolves a compose
// file's bind sources over there. Was DOCKER_HOST_PATHS; the record owns it
// now, and the env var only seeds it once.
function nodePathsLine(n){
  const paths = n.config?.paths || {};
  const text = Object.entries(paths).map(([k, v]) => `${k}:${v}`).join(", ");
  const c = nodeDraft(n);
  // The draft follows the record when the record moves (a save, another
  // browser); it keeps the operator's typing otherwise.
  if (c.draft.pathsText === undefined || c.draft.pathsFrom !== text){
    c.draft.pathsText = text; c.draft.pathsFrom = text;
  }
  return `
    <div class="sub ndpaths">
      <input data-k="paths" value="${esc(c.draft.pathsText)}" spellcheck="false" autocomplete="off"
        placeholder="path mapping: /workspace:/workspace, /devdata:/mnt/user/appdata/bb-dev"
        aria-label="path mapping" title="what this container's paths are called on the node — its daemon resolves bind mounts over there">
      <button type="button" data-nd="paths" title="save the mapping onto the node's record">Save paths</button>
    </div>`;
}

// Is this node's agent the one this controller ships? Everything the AGENT
// runs is held until it is: job types and spec fields have been added on
// nearly every phase, and an older agent meets an unknown one with a shrug
// rather than an error, so a newer controller must not drive it. Its own
// update is the way out and is never held. The server refuses the same jobs
// (nodes.agent_stale) — this only saves the operator the round trip.
function nodeStale(n){
  return n.kind === "agent" && n.agent?.digest && nodesAgent?.digest
    && n.agent.digest !== nodesAgent.digest && !n.agent?.revoked;
}

function staleWhy(n){
  return `${n.name} runs agent ${n.agent?.version || "?"} and this controller ships ${
    nodesAgent?.version} — press Update agent first, so nothing is sent that the agent may not know`;
}

// Which stores a storage apply would move: saved somewhere other than where
// the node reports them. `cache` is left out — the agent does not copy it
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

function nodeConfFold(n){
  const c = nodeDraft(n);
  const d = c.draft;
  const rep = n.reported || {};
  const busy = n.applying;
  const mounts = d.mounts.map((m, i) => {
    const [st, cls] = mountState(m, rep.mounts);
    return `
    <div class="ndmount" data-i="${i}">
      <select data-k="type" aria-label="type">
        <option value="nfs" ${m.type !== "virtiofs" ? "selected" : ""}>nfs</option>
        <option value="virtiofs" ${m.type === "virtiofs" ? "selected" : ""}>virtiofs</option>
      </select>
      <input data-k="source" value="${esc(m.source || "")}" spellcheck="false" autocomplete="off"
        placeholder="${m.type === "virtiofs" ? "share tag" : "nas:/mnt/user/appdata"}" aria-label="source">
      <input data-k="path" value="${esc(m.path || "")}" spellcheck="false" autocomplete="off"
        placeholder="mountpoint — blank means /mnt/<the export's name>" aria-label="mountpoint">
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
    const now = r ? (r.free_mb === null ? `${r.path} — missing` : `${r.path}, ${
      r.free_mb >= 10240 ? Math.round(r.free_mb / 1024) + "GB" : r.free_mb + "MB"} free`) : "";
    return `
    <div class="ndstore">
      <label title="${esc(STORE_ABOUT[role] || "")}">${esc(role)}</label>
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
  // The state line answers one question — is there anything to press Apply
  // for — and names the changes when there is, so the button is not a leap.
  const [status, statusCls] = busy
    ? [`applying ${busy.what}${busy.what === "network" ? " — waiting for it to dial back in" : "…"}`, "note"]
    : stale ? [staleWhy(n), "warn"]
    : c.dirty ? ["unsaved — Save keeps it on the record; Apply makes the node match", "warn"]
    : !drift ? ["nothing configured yet — the node runs on whatever it was set up with", ""]
    : pending.length ? [`${pending.length} change${pending.length === 1 ? "" : "s"} to apply: ${
        pending.slice(0, 3).join("; ")}${pending.length > 3 ? "; …" : ""}`, "warn"]
    : drift.network === "unknown"
      ? ["the node matches what is saved here, except dhcp, which cannot be told from here", ""]
      : ["the node matches what is saved here", "ok"];
  return `
  <div class="ndconf">
    <div class="ndconfbody">
      <div class="ndsec">Mounts — what this node mounts at boot, applied through bb-sandbox on it${
        d.fromNode ? `. <span class="dim">These are the ones the node reports; nothing has been
        saved here yet, so editing and saving is what puts this page in charge of them.</span>` : ""}</div>
      ${mounts}
      <button type="button" data-madd>+ mount</button>
      <div class="ndsec">Stores — where the agent keeps job data, toolchains, build caches and
        this node's copy of what projects built. Each is a directory of its own: a system
        path is refused, here and on the node.</div>
      ${stores}
      <div class="ndsec">Network — applied with a three-minute dial-back, or reverted</div>
      <div class="ndnet">
        <select data-k="net:mode" aria-label="mode">
          <option value="dhcp" ${isStatic ? "" : "selected"}>dhcp</option>
          <option value="static" ${isStatic ? "selected" : ""}>static</option>
        </select>
        <input data-k="net:address" value="${esc(d.network.address || "")}" ${isStatic ? "" : "disabled"}
          spellcheck="false" autocomplete="off" placeholder="10.0.0.12/24" aria-label="address">
        <input data-k="net:gateway" value="${esc(d.network.gateway || "")}" ${isStatic ? "" : "disabled"}
          spellcheck="false" autocomplete="off" placeholder="gateway 10.0.0.1" aria-label="gateway">
        <input data-k="net:dns" value="${esc((d.network.dns || []).join(", "))}" ${isStatic ? "" : "disabled"}
          spellcheck="false" autocomplete="off" placeholder="dns 10.0.0.1, 1.1.1.1" aria-label="dns">
        <input data-k="net:interface" value="${esc(d.network.interface || "")}" spellcheck="false"
          autocomplete="off" placeholder="${esc(net.interface || "interface (default route's)")}" aria-label="interface">
      </div>
      <div class="sub">${esc(now)}</div>
      ${nodeRunnerSection(n, c)}
      <div class="acts ndconfacts">
        <span class="sub ndconfstate${statusCls ? " " + statusCls : ""}">${esc(status)}</span>
        <span class="sp"></span>
        <button type="button" data-nsave ${c.dirty ? "" : "disabled"}>Save</button>
        <button type="button" data-napply="storage" ${
          busy || c.dirty || stale || !drift?.storage.length ? "disabled" : ""}
          title="${stale ? esc(staleWhy(n))
            : !drift ? "nothing is saved to apply"
            : !drift.storage.length ? "the node already has the mounts and stores saved here"
            : "mounts and stores: a system job on the node, through bb-sandbox"}">Apply storage</button>
        <button type="button" data-napply="network" ${busy || c.dirty || stale || !netPend ? "disabled" : ""}
          title="${stale ? esc(staleWhy(n))
            : !drift ? "nothing is saved to apply"
            : !netPend ? "the node is already on the address saved here"
            : "re-address the node; it must dial back in within three minutes or it reverts"}">Apply network</button>
      </div>
    </div>
  </div>`;
}

// A resource as a bar rather than a sentence. The row said "cpu 0.5% ·
// 0.7/7GB · data 48GB free · packages 48GB free · cache 48GB free, 1MB used
// · artifacts 48GB free" in one grey line, which is a paragraph pretending
// to be a readout — nothing in it can be taken in at a glance, and the one
// number that matters (a store filling up) reads the same as the five that
// do not. Pressure picks the colour, so a full disk is the thing your eye
// lands on. Tokens only; the schemes repaint these with everything else.
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
  // the freshness — never the sample alone, which has no total to take a
  // percentage of and no path to name.
  for (const [role, st] of Object.entries(rep.stores || {})){
    const live = s.stores?.[role];
    const free = typeof live === "number" ? live : st?.free_mb;
    if (free === null || free === undefined){
      out.push(meter(role, 0, "missing", `${st?.path || role} — the node cannot see it`));
      continue;
    }
    const total = st?.total_mb || 0;
    const used = total ? Math.max(0, total - free) : 0;
    out.push(meter(role, total ? used / total * 100 : 0, `${gb(free)} free`,
                   `${st?.path || ""}${total ? ` — ${gb(used)} of ${gb(total)} used` : ""}`));
  }
  return out.length ? `<div class="ndmeters">${out.join("")}</div>` : "";
}

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
  // on one page was a wall — mounts, four stores, network, the runner, the
  // actions, per row, for every machine — and the fold that hid it only
  // moved the problem: the settings you came for were two taps down and the
  // ones you did not care about were still in the way. So the tab is a
  // picker and one machine, expanded, like the Docker manager and the Tools
  // tab already are (docs/nodes.md §13: one tab, re-rendered per pick).
  const live = nodesList.filter(n => n.state !== "retired");
  if (!live.some(n => n.id === nodesPick)) nodesPick = live[0]?.id || "";
  const n = live.find(x => x.id === nodesPick);
  d.setBar(`<label class="pick">Node <select id="ndPick" aria-label="node">${
      live.map(x => `<option value="${esc(x.id)}"${x.id === nodesPick ? " selected" : ""}>${
        esc(x.name)} — ${esc(x.kind)}${x.live === false ? ", quiet" : ""}</option>`).join("")}</select></label>
    <span class="sp"></span>
    <button type="button" id="ndEnroll">${nodesOpenForm === "agent" ? "Cancel" : "Enroll node…"}</button>
    <button type="button" id="ndAdd">${nodesOpenForm === "ssh" ? "Cancel" : "Add ssh node…"}</button>`);
  const rows = (n ? [n] : []).map(n => {
    const labels = Object.entries(n.labels || {})
      .map(([k, v]) => `<span class="pill">${esc(k)}=${esc(v)}</span>`).join(" ");
    const seen = n.agent?.last_seen
      ? `seen ${ago(n.agent.last_seen)}` : (n.kind === "agent" ? "never seen" : "");
    const census = n.reported?.cpu
      ? `${n.reported.cpu} cpu · ${Math.round((n.reported.mem_mb || 0) / 1024)}GB`
      : "";
    const where = n.kind === "local" ? "this container"
      : n.kind === "agent" ? (n.agent?.addr ? `dials in from ${n.agent.addr}` : "")
      : (n.ssh_addr || "");
    // Behind when the node's agent is not the file this controller ships.
    // Said on the row before anybody presses anything: a five-version-old
    // agent otherwise looks exactly like a current one.
    const stale = nodeStale(n);
    const agentVer = n.kind === "agent" && n.agent?.version
      ? `agent ${n.agent.version}${n.agent.digest ? " " + n.agent.digest.slice(7, 15) : ""}${
          stale ? ` <span class="pill warn ndstale" title="this controller ships agent ${
            esc(nodesAgent.version)} ${esc(nodesAgent.digest.slice(7, 15))}">update available → ${
            esc(nodesAgent.version)}</span>` : ""}${
          n.config?.user ? ` · jobs run as ${esc(n.config.user)}` : ""}` : "";
    return `
    <div class="row stack2 ndrow" data-node="${esc(n.id)}">
      <div class="grow">
        <div class="name">${esc(n.name)} ${nodeStatePill(n)}
          <span class="dim">· ${esc(n.kind)}</span></div>
        <div class="sub">${[esc(where), census, esc(seen), agentVer].filter(Boolean).join(" · ")}</div>
        ${nodeMeters(n)}
        ${nodeTools(n)}
        ${labels ? `<div class="sub ndlabels">${labels}</div>` : ""}
        <div class="sub ndtest" hidden></div>
        ${n.kind === "agent" && n.reported?.sandbox && n.state !== "pending" ? nodeConfFold(n) : ""}
        ${n.kind === "ssh" && n.state !== "retired" ? nodePathsLine(n) : ""}
      </div>
      <span class="acts">
        ${n.kind === "local" || n.state === "pending" ? "" : `<button type="button" data-nd="test"
          title="${n.kind === "agent"
            ? "run uname on it through the agent — the channel, end to end"
            : "probe this node's daemon now — docker answering, and the provisioner's sandbox stamp"}">Test</button>`}
        ${stale && n.state !== "pending" ? `<button type="button" data-nd="update-agent"
          title="hand the node the agent this controller ships (${esc(nodesAgent.version)}) — it swaps itself in place and re-execs; nothing else restarts, and it waits for its own jobs to finish first">Update agent</button>` : ""}
        ${n.state === "pending" ? "" : `<button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
          title="${n.state === "draining"
            ? "take new work again"
            : "finish what is running, accept nothing new — what makes a node safe to reboot"}">${
          n.state === "draining" ? "Undrain" : "Drain"}</button>`}
        ${n.kind === "agent" && n.state !== "pending" && !n.agent?.revoked
          ? `<button type="button" data-nd="cache-clear" ${stale ? "disabled" : ""}
          title="${stale ? esc(staleWhy(n)) : "drop this node's build caches — every project's. A cold cache costs the next build time, never correctness"}">Clear cache</button>` : ""}
        ${n.kind === "agent" && n.state !== "pending" && !n.agent?.revoked
          ? `<button type="button" class="rm" data-nd="revoke"
          title="cut this node's credential. It stops being able to dial in; the row and its history stay. The way back is a new enrollment">Revoke</button>` : ""}
        ${n.kind === "local" ? "" : `<button type="button" class="rm" data-nd="retire"
          title="take it off every list. Its row and its history stay — an id is never reused">Remove</button>`}
      </span>
    </div>`;
  }).join("");
  const form = nodesOpenForm === "ssh" ? `
    <div class="row ndform">
      <div class="grow">
        <label for="ndName">Name</label>
        <input id="ndName" maxlength="60" autocomplete="off" placeholder="buildbox">
        <label for="ndAddr">Address — a machine vm/provision.sh set up</label>
        <input id="ndAddr" autocomplete="off" spellcheck="false"
          placeholder="10.0.0.12 — ssh:// and the bb account are filled in">
        <div class="hint">an ssh node is driven from here over ssh and runs no
          agent: docker only, no jobs. Test it after adding — a daemon without
          the provisioner's stamp is refused, on purpose.</div>
        <div class="acts"><span class="sp"></span>
          <button type="button" class="primary" id="ndGo">Add it</button></div>
      </div>
    </div>` : nodesOpenForm === "agent" ? `
    <div class="row ndform">
      <div class="grow">
        <label for="ndEnName">Name</label>
        <input id="ndEnName" maxlength="60" autocomplete="off" placeholder="buildbox">
        <div class="hint">the node dials in; nothing here connects to it. The
          token below is good once and for a day. A node does everything for
          the projects bound to it — what it can actually build is what gets
          installed on it afterwards, from the Tools tab.</div>
        <div class="acts"><span class="sp"></span>
          <button type="button" class="primary" id="ndEnGo">Mint a token</button></div>
      </div>
    </div>` : "";
  const minted = !nodesMinted ? "" : `
    <div class="row ndform ndtoken">
      <div class="grow">
        <div class="name">${esc(nodesMinted.name)} — enroll it with one of these</div>
        <div class="hint">shown once; the controller keeps only a hash. On a
          fresh machine, the provisioner installs docker and the agent
          together:</div>
        <pre class="ndcmd">sudo bash provision.sh --controller ${esc(nodesMinted.url)} --token ${esc(nodesMinted.token)}</pre>
        <div class="hint">or on a machine that already has python3, the agent alone:</div>
        <pre class="ndcmd">curl -fsSL -H 'Authorization: Bearer ${esc(nodesMinted.token)}' ${esc(nodesMinted.url)}/api/v1/agent/download -o /usr/local/sbin/builderbot-agent
chmod 755 /usr/local/sbin/builderbot-agent
builderbot-agent enroll --controller ${esc(nodesMinted.url)} --token ${esc(nodesMinted.token)}</pre>
        <div class="acts"><span class="sp"></span>
          <button type="button" id="ndTokDone">Done</button></div>
      </div>
    </div>`;
  d.list.innerHTML = rows + form + minted
    + (!nodesList.length ? `<div class="empty">no nodes — which cannot happen:
        local is seeded at boot. If you can read this, the store broke.</div>` : "");
  d.setFoot(`a node does everything for the projects bound to it — pick one in a
    project's settings dialog. What it can build is what is installed on it;
    jobs run as the account it enrolled, never root.`);
  wireNodesTab(d.el);
}

function wireNodesTab(root){
  const add = root.querySelector("#ndAdd");
  if (add) add.onclick = () => { nodesOpenForm = nodesOpenForm === "ssh" ? "" : "ssh";
                                 nodesRev++; drawPanes(); };
  const pick = root.querySelector("#ndPick");
  if (pick) pick.onchange = () => { nodesPick = pick.value; nodesFocus = null;
                                    nodesRev++; drawPanes(); };
  const en = root.querySelector("#ndEnroll");
  if (en) en.onclick = () => { nodesOpenForm = nodesOpenForm === "agent" ? "" : "agent";
                               nodesRev++; drawPanes(); };
  const go = root.querySelector("#ndGo");
  if (go) go.onclick = async () => {
    const r = await nodeAct({action: "add",
                             name: root.querySelector("#ndName").value,
                             addr: root.querySelector("#ndAddr").value});
    if (!r.error){ nodesOpenForm = ""; nodesRev++; drawPanes(); }
  };
  const engo = root.querySelector("#ndEnGo");
  if (engo) engo.onclick = async () => {
    const name = root.querySelector("#ndEnName").value;
    const r = await nodeAct({action: "enroll", name});
    if (!r.error){
      // The URL the node should dial: this page's origin, which is the
      // only address the browser knows the controller by. A proxy in
      // front is the operator's to substitute.
      nodesMinted = {name: name || "node", token: r.token, url: location.origin};
      nodesOpenForm = ""; nodesRev++; drawPanes();
    }
  };
  const tok = root.querySelector("#ndTokDone");
  if (tok) tok.onclick = () => { nodesMinted = null; nodesRev++; drawPanes(); };
  root.querySelectorAll(".ndrow").forEach(row => {
    const id = row.dataset.node;
    row.querySelectorAll("[data-nd]").forEach(b => b.onclick = async () => {
      if (b.dataset.nd === "retire"
          && !confirm("Remove this node from every list? Its containers and "
                      + "its data stay on the machine; the row is kept as "
                      + "history.")) return;
      if (b.dataset.nd === "revoke"
          && !confirm("Revoke this node's credential? It will stop being able "
                      + "to dial in, and the only way back is enrolling it "
                      + "again with a new token.")) return;
      if (b.dataset.nd === "cache-clear"
          && !confirm("Clear this node's build caches? Every project's Gradle, "
                      + "npm and snapshot cache there goes; the next build of "
                      + "each re-downloads what it needs.")) return;
      if (b.dataset.nd === "update-agent"){
        const j = await nodeAct({action: "update-agent", id});
        if (j.current) notify(`already on ${j.version}`);
        else if (j.ok) notify("update queued — the row follows the agent's next hello");
        return;
      }
      if (b.dataset.nd === "paths"){
        const inp = row.querySelector('[data-k="paths"]');
        await nodeAct({action: "paths", id, paths: inp ? inp.value : ""});
        const c = nodesConf[id]; if (c && c.draft) c.draft.pathsText = undefined;
        return;
      }
      if (b.dataset.nd === "test"){
        const out = row.querySelector(".ndtest");
        out.hidden = false;
        out.textContent = "asking…";
        const j = await nodeAct({action: "test", id});
        // Repainted underneath by the loadNodes() in nodeAct — find the
        // row again rather than writing to the one that was replaced.
        const now = root.querySelector(`.ndrow[data-node="${CSS.escape(id)}"] .ndtest`)
                    || out;
        now.hidden = false;
        now.textContent = j.on ? (j.why || "answers, and says it is a sandbox")
                               : (j.why || "no answer");
        now.classList.toggle("warn", !j.on);
        return;
      }
      await nodeAct({action: b.dataset.nd, id});
    });
    wireNodeConf(row, id);
    const pi = row.querySelector('.ndpaths [data-k="paths"]');
    if (pi){
      pi.onfocus = () => { nodesFocus = {id, key: "paths", pos: pi.selectionStart ?? undefined}; };
      pi.oninput = () => { const c = nodeDraft(nodesList.find(x => x.id === id)); c.draft.pathsText = pi.value;
                           nodesFocus = {id, key: "paths", pos: pi.selectionStart ?? undefined}; };
    }
  });
  // The field that had the caret before this repaint gets it back — the
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
        const b = fold.querySelector("[data-nsave]");
        if (b) b.disabled = false;
        fold.querySelectorAll("[data-napply]").forEach(x => { x.disabled = true; });
        const st = fold.querySelector(".ndconfstate");
        if (st) st.textContent = "unsaved — Save keeps it on the record; Apply makes the node match";
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
    await nodeAct({action: "runner", id, want, labels, url: c.draft.runner?.url || ""});
  });
  const save = fold.querySelector("[data-nsave]");
  if (save) save.onclick = async () => {
    const r = await nodeAct({action: "config", id, config: c.draft});
    if (!r.error){ c.dirty = false; c.draft = null; nodesRev++; drawPanes(); }
  };
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
      // and take a while — so it is asked about rather than started by a
      // text field losing focus.
      const moving = storeMoves(n);
      if (moving.length && !confirm(`Apply storage to ${n?.name || "this node"}?\n\nThis moves `
          + `${moving.map(m => `${m.role} from ${m.from} to ${m.to}`).join(", and ")}. The `
          + `contents are copied across first and the job waits for that; nothing is deleted, `
          + `so the old cop${moving.length === 1 ? "y stays" : "ies stay"} where ${
              moving.length === 1 ? "it is" : "they are"} for you to remove.`)) return;
    }
    await nodeAct({action: "apply", id, what});
  });
}
