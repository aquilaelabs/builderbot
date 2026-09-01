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

function openNodesTab(){
  openTab({kind: "nodes", arg: "__nodes", label: "Nodes"});
  loadNodes();
}

async function loadNodes(){
  try{
    const j = await (await fetch("/api/v1/nodes")).json();
    nodesErr = j.error || "";
    nodesList = j.nodes || [];
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
const NODE_CAPS = [
  ["docker-host", "docker host"],
  ["package-build", "package build"],
  ["deploy-target", "deploy target"],
];

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

// The heartbeat's numbers, as the row shows them: what the machine is doing
// now, and how much room each store has. Only an agent node has them — an
// ssh node reports nothing between commands, and the local node's numbers
// are the container's own, already on the header.
function nodeNumbers(n){
  const s = n.reported?.sample;
  if (!s || !n.live) return "";
  const mem = s.mem_mb ? `${Math.round(s.mem_used_mb / 1024 * 10) / 10}/${
      Math.round(s.mem_mb / 1024)}GB` : "";
  const stores = Object.entries(s.stores || {}).map(([r, free]) => free === null
    ? `${esc(r)} missing`
    : `${esc(r)} ${free >= 10240 ? Math.round(free / 1024) + "GB" : free + "MB"} free`);
  return [`cpu ${s.cpu_pct}%`, mem, s.running ? `${s.running} running` : "",
          ...stores].filter(Boolean).join(" · ");
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
  d.setBar(`<span class="dim">${nodesList.length} node${
      nodesList.length === 1 ? "" : "s"} — the machines work can run on</span>
    <span class="sp"></span>
    <button type="button" id="ndEnroll">${nodesOpenForm === "agent" ? "Cancel" : "Enroll node…"}</button>
    <button type="button" id="ndAdd">${nodesOpenForm === "ssh" ? "Cancel" : "Add ssh node…"}</button>`);
  const rows = nodesList.map(n => {
    const caps = NODE_CAPS.map(([c, label]) => `
      <label class="ndcap"><input type="checkbox" data-cap="${esc(c)}"
        ${n.capabilities.includes(c) ? "checked" : ""}
        ${n.kind === "local" && c === "docker-host" ? "disabled" : ""}>
        ${esc(label)}</label>`).join("");
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
    const numbers = nodeNumbers(n);
    const agentVer = n.kind === "agent" && n.agent?.version
      ? `agent ${n.agent.version}${n.agent.digest ? " " + n.agent.digest.slice(7, 15) : ""}${
          n.config?.user ? ` · jobs run as ${esc(n.config.user)}` : ""}` : "";
    return `
    <div class="row stack2 ndrow" data-node="${esc(n.id)}">
      <div class="grow">
        <div class="name">${esc(n.name)} ${nodeStatePill(n)}
          <span class="dim">· ${esc(n.kind)}</span></div>
        <div class="sub">${[esc(where), census, esc(seen), agentVer].filter(Boolean).join(" · ")}</div>
        ${numbers ? `<div class="sub ndnums">${numbers}</div>` : ""}
        <div class="sub ndcaps">${caps}</div>
        ${labels ? `<div class="sub">${labels}</div>` : ""}
        <div class="sub ndtest" hidden></div>
      </div>
      <span class="acts">
        ${n.kind === "local" || n.state === "pending" ? "" : `<button type="button" data-nd="test"
          title="${n.kind === "agent"
            ? "run uname on it through the agent — the channel, end to end"
            : "probe this node's daemon now — docker answering, and the provisioner's sandbox stamp"}">Test</button>`}
        ${n.state === "pending" ? "" : `<button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
          title="${n.state === "draining"
            ? "take new work again"
            : "finish what is running, accept nothing new — what makes a node safe to reboot"}">${
          n.state === "draining" ? "Undrain" : "Drain"}</button>`}
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
        <div class="sub ndcaps">${NODE_CAPS.map(([c, label]) => `
          <label class="ndcap"><input type="checkbox" data-encap="${esc(c)}"
            ${c === "docker-host" ? "checked" : ""}> ${esc(label)}</label>`).join("")}</div>
        <div class="hint">the node dials in; nothing here connects to it. The
          token below is good once and for a day, and the machine keeps the
          capabilities it enrolled with — a job needing one it did not is
          refused there, whatever this row says.</div>
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
  d.setFoot(`nodes run work; the controller schedules it. docs/nodes.md is the
    design; an agent node runs jobs as the account it enrolled, never root.`);
  wireNodesTab(d.el);
}

function wireNodesTab(root){
  const add = root.querySelector("#ndAdd");
  if (add) add.onclick = () => { nodesOpenForm = nodesOpenForm === "ssh" ? "" : "ssh";
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
    const caps = [...root.querySelectorAll("[data-encap]")]
      .filter(x => x.checked).map(x => x.dataset.encap);
    const name = root.querySelector("#ndEnName").value;
    const r = await nodeAct({action: "enroll", name, capabilities: caps});
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
    row.querySelectorAll("[data-cap]").forEach(c => c.onchange = () => {
      const caps = [...row.querySelectorAll("[data-cap]")]
        .filter(x => x.checked).map(x => x.dataset.cap);
      nodeAct({action: "update", id, fields: {capabilities: caps}});
    });
  });
}
