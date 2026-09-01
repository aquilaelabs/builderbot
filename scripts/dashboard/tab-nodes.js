// The Nodes tab: the node registry, editable. Phase 2 of docs/nodes.md —
// CRUD over ssh docker hosts, capability toggles, labels, pool, concurrency,
// test, drain, retire. Its own classic script beside index.html, per the
// new-surface rule (§13): same page, same global scope, one file per surface.
//
// Chrome comes from docSurface() and the hard rules are held by uniform.mjs —
// this file only fills slots. Data comes from /api/v1/nodes, fetched when the
// "nodes" revision token moves, never from the status poll.

let nodesList = null;            // last answer, or null before the first
let nodesRev = 0;                // bumped when it changes, so panes repaint
let nodesErr = "";
let nodesOpenForm = false;       // the add-node form, staged across repaints

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
  const cls = {online: "ok", draining: "warn", pending: "note"}[n.state] || "";
  return `<span class="pill ${cls}">${esc(n.state)}</span>`;
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
    <button type="button" id="ndAdd">${nodesOpenForm ? "Cancel" : "Add node…"}</button>`);
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
    return `
    <div class="row stack2 ndrow" data-node="${esc(n.id)}">
      <div class="grow">
        <div class="name">${esc(n.name)} ${nodeStatePill(n)}
          <span class="dim">· ${esc(n.kind)}</span></div>
        <div class="sub">${esc(n.ssh_addr || (n.kind === "local"
          ? "this container" : ""))}${census ? ` · ${census}` : ""}${
          seen ? ` · ${esc(seen)}` : ""}</div>
        <div class="sub ndcaps">${caps}</div>
        ${labels ? `<div class="sub">${labels}</div>` : ""}
        <div class="sub ndtest" hidden></div>
      </div>
      <span class="acts">
        ${n.kind === "local" ? "" : `<button type="button" data-nd="test"
          title="probe this node's daemon now — docker answering, and the provisioner's sandbox stamp">Test</button>`}
        <button type="button" data-nd="${n.state === "draining" ? "online" : "drain"}"
          title="${n.state === "draining"
            ? "take new work again"
            : "finish what is running, accept nothing new — what makes a node safe to reboot"}">${
          n.state === "draining" ? "Undrain" : "Drain"}</button>
        ${n.kind === "local" ? "" : `<button type="button" class="rm" data-nd="retire"
          title="take it off every list. Its row and its history stay — an id is never reused">Remove</button>`}
      </span>
    </div>`;
  }).join("");
  const form = !nodesOpenForm ? "" : `
    <div class="row ndform">
      <div class="grow">
        <label for="ndName">Name</label>
        <input id="ndName" maxlength="60" autocomplete="off" placeholder="buildbox">
        <label for="ndAddr">Address — a machine vm/provision.sh set up</label>
        <input id="ndAddr" autocomplete="off" spellcheck="false"
          placeholder="10.0.0.12 — ssh:// and the bb account are filled in">
        <div class="hint">ssh nodes only for now: the agent, and enrolling
          anything that dials out, is the next phase. Test it after adding —
          a daemon without the provisioner's stamp is refused, on purpose.</div>
        <div class="acts"><span class="sp"></span>
          <button type="button" class="primary" id="ndGo">Add it</button></div>
      </div>
    </div>`;
  d.list.innerHTML = rows + form
    + (!nodesList.length ? `<div class="empty">no nodes — which cannot happen:
        local is seeded at boot. If you can read this, the store broke.</div>` : "");
  d.setFoot(`nodes run work; the controller schedules it. docs/nodes.md is the
    design, and phase 2 is what this tab can do so far.`);
  wireNodesTab(d.el);
}

function wireNodesTab(root){
  const add = root.querySelector("#ndAdd");
  if (add) add.onclick = () => { nodesOpenForm = !nodesOpenForm;
                                 nodesRev++; drawPanes(); };
  const go = root.querySelector("#ndGo");
  if (go) go.onclick = async () => {
    const r = await nodeAct({action: "add",
                             name: root.querySelector("#ndName").value,
                             addr: root.querySelector("#ndAddr").value});
    if (!r.error){ nodesOpenForm = false; nodesRev++; drawPanes(); }
  };
  root.querySelectorAll(".ndrow").forEach(row => {
    const id = row.dataset.node;
    row.querySelectorAll("[data-nd]").forEach(b => b.onclick = async () => {
      if (b.dataset.nd === "retire"
          && !confirm("Remove this node from every list? Its containers and "
                      + "its data stay on the machine; the row is kept as "
                      + "history.")) return;
      if (b.dataset.nd === "test"){
        const out = row.querySelector(".ndtest");
        out.hidden = false;
        out.textContent = "asking its daemon…";
        const j = await nodeAct({action: "test", id});
        out.textContent = j.on ? "answers, and says it is a sandbox"
                               : (j.why || "no answer");
        out.classList.toggle("warn", !j.on);
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
