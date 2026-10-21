"use strict";
// ---- the VMs page (R91) ----------------------------------------------------
// A project's VMs, on the nodes whose VM host feature is installed: the
// Containers page's pieces (a card per project with its heading in the
// project's color, a row per VM with its state as a pill, the action bar and
// ⋯), so the two read as one manager (the operator, 21 Oct). Everything it
// shows is /api/vms: the records, the node's census laid over them.

let vmsData = null;             // the last /api/vms answer, null before the first
let vmsErr = "";
let vmsRev = 0;
let vmsSearch = "";

function openVmsTab(){
  openTab({kind: "vms", arg: "__vms", label: "VMs"});
}

async function loadVms(){
  try{
    const j = await (await bootFetch("/api/vms")).json();
    vmsErr = j.error || "";
    vmsData = j;
  }catch(e){
    vmsErr = String(e);
    vmsData = vmsData || {vms: [], images: [], hosts: [], can: {}};
  }
  vmsRev++;
  if (tabs.some(t => t.kind === "vms")) drawPanes();
}

// What a VM's state says, in its level's tone.
function vmPill(v){
  const st = v.state || "unknown";
  const tone = {running: "ok", made: "ok", failed: "bad", crashed: "bad", missing: "warn",
                making: "note", removing: "note", stopping: "note"}[st] || "";
  const word = {made: "starting", making: "being made", removing: "being removed", missing: "not on its node"}[st] || st;
  return `<span class="pill stat dmpill${tone ? " " + tone : ""}${st === "running" ? " live" : ""}">${esc(word)}</span>`;
}

const vmMay = p => (vmsData?.can || {})[p] === "write";

function vmRow(v){
  const may = vmMay(v.project);
  const busy = ["making", "removing"].includes(v.state);
  const up = v.state === "running";
  const size = `${v.vcpus} vCPU · ${v.mem_mb >= 1024 ? `${+(v.mem_mb / 1024).toFixed(1)} GB` : `${v.mem_mb} MB`} · ${v.disk_gb} GB disk`;
  const origin = [esc(v.os_name || v.os || ""), esc(v.node_name || ""), esc(size)].filter(Boolean).join(`<span class="sep"></span>`);
  const reach = up && v.ip ? `ssh ${esc(v.user || "builder")}@${esc(v.ip)}` : up ? "taking its address" : "";
  // Made a node (step 14): its row on the Nodes page.
  const asNode = v.node_id ? `<div class="sub dmorigin">a node too: ${pageLink("nodes", "on the Nodes page", `#/machines/nodes/${encodeURIComponent(v.node_id)}`)}</div>` : "";
  const snaps = v.snapshots || [];
  const acts = !may ? "" : `
    ${!up && !busy && v.state !== "failed" ? `<button type="button" class="primary" data-vm="start">Start</button>` : ""}
    ${up ? `<button type="button" data-vmcon title="its serial console, in the dock">Console</button>` : ""}
    ${up ? `<button type="button" data-vm="stop" title="ask it to shut down, as its power button would">Stop</button>` : ""}
    ${actMore([
      up ? `<button type="button" data-vm="restart">Restart</button>` : "",
      up ? `<button type="button" data-vm="stop" data-force="1" title="pull the plug: it stops at once, unsaved work in it lost">Force stop</button>` : "",
      !busy && v.state !== "failed" ? `<button type="button" data-vm="snapshot" title="its state saved under a name; a running VM's memory too">Snapshot…</button>` : "",
      `<button type="button" class="danger" data-vm="remove"${v.state === "removing" ? " disabled" : ""}
        title="destroy it, with its disk and its snapshots">Remove</button>`])}`;
  return `<div class="row stack2" data-vm-key="${esc(v.key)}">
    <div class="grow">
      <div class="dmhead">
        <div class="dmid">
          <div class="name">${esc(v.name)}${vmPill(v)}</div>
          ${origin ? `<div class="sub dmorigin">${origin}</div>` : ""}
          ${reach ? `<div class="sub dmstate${v.ip ? " ok" : ""}">${reach}</div>` : ""}
          ${asNode}
          ${v.error ? `<div class="sub dmstate bad">${esc(v.error)}</div>` : ""}
        </div>
        <div class="actbar dmacts">${acts}</div>
      </div>
      ${snaps.length ? `<div class="vmsnaps"><span class="vmsnaplbl">Snapshots</span>${snaps.map(s => `<div class="vmsnap"><code>${esc(s)}</code>${may && !busy ? `
        <button type="button" data-vm="revert" data-snap="${esc(s)}" title="back to ${esc(s)}: what changed since is lost">Revert</button>
        <button type="button" data-vm="snapshot-rm" data-snap="${esc(s)}" title="delete this snapshot">Delete</button>` : ""}</div>`).join("")}</div>` : ""}
    </div>
  </div>`;
}

function vmGroupsHtml(rows){
  const byName = (a, b) => a.localeCompare(b, undefined, {sensitivity: "base"});
  const owners = [...new Set(rows.map(v => v.project))].sort((a, b) => byName(projLabel(a), projLabel(b)));
  return owners.map(o => `<section class="dmcard"><div class="field dmgroup" style="--gc:${colorTone(projectColor(o)) || "var(--accent)"}"><b>${
      esc(projLabel(o))}</b></div>${rows.filter(v => v.project === o).sort((a, b) => byName(a.name, b.name)).map(vmRow).join("")}</section>`).join("");
}

function vmBar(ghost){
  const dead = ghost ? " disabled" : "";
  const any = !ghost && Object.values(vmsData?.can || {}).includes("write");
  return `<div class="field docbarrow dmpick"><input${ghost ? "" : ` id="vmSearch"`} type="search"
      placeholder="${isPhone() ? "search" : "name, OS, node or project"}" autocomplete="off" aria-label="narrow the VMs: name, OS, node or project" value="${esc(vmsSearch)}"${dead}><span class="sp"></span>${
      any || ghost ? `<span class="actbar"><button type="button"${ghost ? "" : ` id="bVmNew"`} class="primary"${
        dead || !(vmsData?.hosts || []).length ? " disabled" : ""}>${barSaid("New VM", "New")}</button></span>` : ""}</div>`;
}

function renderVmsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  if (!vmsData){
    el.innerHTML = `<div class="doctab vmtab">${skTpl(`${vmBar(true)}
      <section class="dmcard"><div class="field dmgroup"><b>${skv(8)}</b></div>${skRows(2)}</section>`)}</div>`;
    loadVms();
    return;
  }
  const q = vmsSearch.trim().toLowerCase();
  const rows = (vmsData.vms || []).filter(v => !q || [v.name, v.os, v.os_name, v.node_name, projLabel(v.project), v.ip]
    .some(s => String(s || "").toLowerCase().includes(q)));
  const hosts = vmsData.hosts || [];
  const empty = vmsErr ? `<div class="hint bad">${esc(vmsErr)}</div>`
    : !hosts.length ? `<div class="empty vmnone">No node has VM host yet: its Features section on the ${pageLink("nodes", "Nodes page")} installs it, where the machine has /dev/kvm.</div>`
    : !(vmsData.vms || []).length ? `<div class="empty vmnone">No VM yet. ${Object.values(vmsData.can || {}).includes("write")
        ? "Press <b>New VM</b>, or ask Claude in a session for one: <code>bb vm new NAME --os debian</code>."
        : "A project's sessions make them with <code>bb vm new</code> where its settings allow it."}</div>`
    : !rows.length ? `<div class="empty">No VM matches “${esc(vmsSearch)}”.</div>` : "";
  el.innerHTML = `<div class="doctab vmtab">${vmBar(false)}${empty || vmGroupsHtml(rows)}</div>`;
  wireVms(el);
}

function wireVms(el){
  const s = el.querySelector("#vmSearch");
  if (s) s.oninput = () => { vmsSearch = s.value; const at = s.selectionStart; drawPanes();
    const n = document.querySelector("#vmSearch"); if (n){ n.focus(); n.setSelectionRange(at, at); } };
  const nb = el.querySelector("#bVmNew");
  if (nb) nb.onclick = () => openNewVm();
  el.querySelectorAll("[data-vm-key]").forEach(row => {
    const v = (vmsData?.vms || []).find(x => x.key === row.dataset.vmKey);
    if (!v) return;
    row.querySelectorAll("[data-vmcon]").forEach(b => b.onclick = () =>
      openTab({kind: "term", arg: `vm:${v.project}:${v.name}`, label: `console ${v.name}`}));
    row.querySelectorAll("[data-vm]").forEach(b => b.onclick = () => pressing(b, async () => {
      const action = b.dataset.vm;
      const body = {action, project: v.project, name: v.name};
      if (action === "remove" && !confirm(`Remove ${v.name}?\n\nThe VM is destroyed with its disk${
            (v.snapshots || []).length ? ` and its ${v.snapshots.length} snapshot${v.snapshots.length === 1 ? "" : "s"}` : ""}${
            v.node_id ? ", and its node is retired with its credential revoked" : ""}. It cannot be undone.`)) return;
      if (action === "stop" && b.dataset.force && !confirm(`Force ${v.name} to stop?\n\nIt stops at once, as if unplugged: what it had not saved is lost.`)) return;
      if (action === "revert" && !confirm(`Revert ${v.name} to ${b.dataset.snap}?\n\nWhat changed in it since that snapshot is lost.`)) return;
      if (action === "snapshot-rm" && !confirm(`Delete the snapshot ${b.dataset.snap} of ${v.name}?`)) return;
      if (action === "snapshot"){
        const name = prompt(`A name for this snapshot of ${v.name}: letters, digits, dots, dashes`, "before-" + new Date().toISOString().slice(0, 10));
        if (!name) return;
        body.snapshot = name.trim();
      }
      if (b.dataset.snap) body.snapshot = b.dataset.snap;
      if (b.dataset.force) body.force = true;
      busy(b, {start: "Starting", stop: "Stopping", restart: "Restarting", remove: "Removing", snapshot: "Saving",
               revert: "Reverting", "snapshot-rm": "Deleting"}[action] || "Working");
      const j = await (await postJSON("/api/vms", body)).json();
      if (j.error) notify(j.error, true);
      else notify(`${v.name}: ${action === "snapshot-rm" ? "snapshot delete" : action} queued`);
      await loadVms();
    }));
  });
}

// ---- New VM, a dialog ----------------------------------------------------
// The Containers page's New's shape: what it is, where, and the one filled
// button; the OS from the catalog, a person's OS (Windows) said as theirs.
function openNewVm(forProject = ""){
  let m = document.getElementById("vmnewmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "vmnewmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  const projects = Object.entries(vmsData?.can || {}).filter(([, l]) => l === "write").map(([p]) => p).sort();
  const imgs = (vmsData?.images || []).filter(i => !i.person);
  const hosts = vmsData?.hosts || [];
  m.innerHTML = `<div class="box"><h3>New VM</h3>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmName", "Name")}<input id="vmName" maxlength="31" autocomplete="off" spellcheck="false" placeholder="db"></div>
      <div class="setrow col ctlrow">${lbl("vmProject", "Project")}<select id="vmProject">${optionList(projects.map(p => [p, projLabel(p)]), forProject)}</select></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmOs", "OS", "a publisher's cloud image, checked against its checksums; Windows and macOS have a license to accept, so BuilderBot does not make them")}
        <select id="vmOs">${optionList(imgs.map(i => [i.id, i.name]))}</select></div>
      <div class="setrow col ctlrow">${lbl("vmNode", "Node", "a node with VM host installed")}<select id="vmNode">${optionList(hosts.map(h => [h.id, h.name]))}</select></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmCpu", "vCPUs")}<input id="vmCpu" type="number" min="1" max="64" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmMem", "Memory, GB")}<input id="vmMem" type="number" min="1" max="256" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmDisk", "Disk, GB")}<input id="vmDisk" type="number" min="2" max="4096" value="20"></div>
    </div>
    <div class="field">${lbl("vmKey", "SSH public key", "who may log in: yours, as in ~/.ssh/id_ed25519.pub. The account is builder, with sudo")}
      <textarea id="vmKey" rows="3" spellcheck="false" autocomplete="off" placeholder="ssh-ed25519 AAAA… you@laptop"></textarea></div>
    <label class="ndcap"><input type="checkbox" id="vmAgent"> Make it a node: enroll it with an agent at its first boot</label>
    <div class="hint" id="vmAgentHint" hidden>It appears on the Nodes page once it has booted, a node like any other, marked as a VM on its host; removing the VM retires the node and revokes its credential.</div>
    <div class="field" id="vmWhyF" hidden><div class="hint bad" id="vmWhy"></div></div>
    ${dlgFoot(`<button type="button" id="vmCancel">Cancel</button>`, `<button type="button" id="vmGo" class="primary">Make it</button>`)}</div>`;
  m.hidden = false;
  const $m = s => m.querySelector(s);
  const say = t => { $m("#vmWhy").textContent = t; $m("#vmWhyF").hidden = !t; };
  $m("#vmCancel").onclick = () => { m.hidden = true; };
  $m("#vmAgent").onchange = () => { $m("#vmAgentHint").hidden = !$m("#vmAgent").checked; };
  $m("#vmGo").onclick = () => pressing($m("#vmGo"), async () => {
    busy($m("#vmGo"), "Making");
    const j = await (await postJSON("/api/vms", {action: "new", project: $m("#vmProject").value,
      name: $m("#vmName").value.trim(), os: $m("#vmOs").value, node: $m("#vmNode").value,
      vcpus: +$m("#vmCpu").value, mem_mb: Math.round(+$m("#vmMem").value * 1024), disk_gb: +$m("#vmDisk").value,
      keys: $m("#vmKey").value.split("\n").map(s => s.trim()).filter(Boolean), node_agent: $m("#vmAgent").checked})).json();
    if (j.error){ say(j.error); $m("#vmGo").disabled = false; $m("#vmGo").textContent = "Make it"; return; }
    m.hidden = true;
    notify(`${j.key}: being made on ${j.node}; the image downloads once per node`);
    await loadVms();
  });
}
