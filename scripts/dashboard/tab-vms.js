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
  vmReapConsoles();
  if (tabs.some(t => t.kind === "vms")) drawPanes();
}
// A console tab is the account's and outlives the page, so one whose VM was
// removed while no page watched it stayed in the dock onto nothing (B172):
// dropped once the records are read and the VM is not among them.
const vmConsoleTab = t => t.kind === "term" && /^(vm|screen):/.test(String(t.arg));
// ...and read once for a page that opens with one, since the first poll's
// tokens fire nothing.
let vmsAskedForConsoles = false;
function vmConsolesChecked(){
  if (vmsData || vmsAskedForConsoles || !tabs.some(vmConsoleTab)) return;
  vmsAskedForConsoles = true;
  loadVms();
}
function vmReapConsoles(){
  if (!vmsData || vmsErr) return;
  const have = new Set((vmsData.vms || []).map(v => `${v.project}:${v.name}`));
  tabs.filter(t => vmConsoleTab(t) && !have.has(String(t.arg).replace(/^(vm|screen):/, ""))).map(t => t.id).forEach(dropTab);
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
  const disks = [v.disk_gb, ...(v.disks || [])];
  const size = `${v.vcpus} vCPU · ${v.mem_mb >= 1024 ? `${+(v.mem_mb / 1024).toFixed(1)} GB` : `${v.mem_mb} MB`} · ${
    disks.length > 1 ? `disks of ${disks.join(", ")} GB` : `${v.disk_gb} GB disk`}`;
  const origin = [esc(v.os_name || v.os || ""), esc(v.node_name || ""), esc(size)].filter(Boolean).join(`<span class="sep"></span>`);
  // From an installer (R99): its ISO in the drive until ejected, and no
  // account of BuilderBot's to ssh in as.
  const reach = up && v.iso ? `installing from ${esc(v.iso)}: its Screen shows the installer`
    : up && v.ip && v.os !== "installer" ? `ssh ${esc(v.user || "builder")}@${esc(v.ip)}`
    : up && v.ip ? `at ${esc(v.ip)}` : up ? "taking its address" : "";
  // Made a node (step 14): its row on the Nodes page.
  const asNode = v.node_id ? `<div class="sub dmorigin">a node too: ${pageLink("nodes", "on the Nodes page", `#/machines/nodes/${encodeURIComponent(v.node_id)}`)}</div>` : "";
  const snaps = v.snapshots || [];
  const acts = !may ? "" : `
    ${!up && !busy && v.state !== "failed" ? `<button type="button" class="primary" data-vm="start">Start</button>` : ""}
    ${up && v.screen ? `<button type="button" data-vmscreen title="its screen, keyboard and mouse, in the dock">Screen</button>` : ""}
    ${up && v.os !== "installer" ? `<button type="button" data-vmcon title="its serial console, in the dock">Console</button>` : ""}
    ${up ? `<button type="button" data-vm="stop" title="ask it to shut down, as its power button would">Stop</button>` : ""}
    ${actMore([
      up ? `<button type="button" data-vm="restart">Restart</button>` : "",
      up ? `<button type="button" data-vm="stop" data-force="1" title="pull the plug: it stops at once, unsaved work in it lost">Force stop</button>` : "",
      !busy && v.state !== "failed" ? `<button type="button" data-vm="snapshot" title="its state saved under a name; a running VM's memory too">Snapshot…</button>` : "",
      v.iso && !busy ? `<button type="button" data-vm="eject" title="take ${esc(v.iso)} out of its drive, so it boots from its disk">Eject ISO</button>` : "",
      v.state === "stopped" ? `<button type="button" data-vm="disk-grow" title="make one of its disks larger; it never shrinks">Grow disk…</button>` : "",
      v.state === "stopped" && (v.disks || []).length < 3 ? `<button type="button" data-vm="disk-add" title="another disk, there at its next start">Add disk…</button>` : "",
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
      (any || ghost) && !featureOff("vms") ? `<span class="actbar"><button type="button"${ghost ? "" : ` id="bVmNew"`} class="primary"${
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
  // Switched off on this install (FEATURES_OFF=vms): said where the list
  // would be, and New VM goes with it.
  const off = featureOff("vms");
  const empty = off ? `<div class="field">${deadWhy(off)}</div>`
    : vmsErr ? `<div class="hint bad">${esc(vmsErr)}</div>`
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
    row.querySelectorAll("[data-vmscreen]").forEach(b => b.onclick = () =>
      openTab({kind: "term", arg: `screen:${v.project}:${v.name}`, label: `screen ${v.name}`}));
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
      if (action === "disk-grow"){
        const devs = ["vda", "vdb", "vdc", "vdd"].slice(0, 1 + (v.disks || []).length);
        const sizes = [v.disk_gb, ...(v.disks || [])];
        const dev = devs.length > 1 ? prompt(`Which disk of ${v.name}? ${devs.map((d, i) => `${d} (${sizes[i]} GB)`).join(", ")}`, "vda") : "vda";
        if (!dev || !devs.includes(dev.trim())) return;
        const gb = prompt(`${dev.trim()} of ${v.name} is ${sizes[devs.indexOf(dev.trim())]} GB. Its new size in GB:`, String(sizes[devs.indexOf(dev.trim())] * 2));
        if (!gb) return;
        body.disk = dev.trim(); body.gb = +gb;
      }
      if (action === "disk-add"){
        const gb = prompt(`A further disk for ${v.name}, in GB:`, "20");
        if (!gb) return;
        body.gb = +gb;
      }
      if (action === "eject" && !confirm(`Eject ${v.iso} from ${v.name}?\n\nIts next boot is from its disk, where the installer put the system.`)) return;
      if (b.dataset.snap) body.snapshot = b.dataset.snap;
      if (b.dataset.force) body.force = true;
      busy(b, {start: "Starting", stop: "Stopping", restart: "Restarting", remove: "Removing", snapshot: "Saving",
               revert: "Reverting", "snapshot-rm": "Deleting", eject: "Ejecting", "disk-grow": "Growing", "disk-add": "Adding"}[action] || "Working");
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
  // What a VM is made from (R99): a catalog image, or an installer's ISO
  // already on the picked node, or one to fetch there first.
  const fromOptions = nid => {
    const isos = (hosts.find(h => h.id === nid)?.isos || []);
    return `<optgroup label="Cloud images">${optionList(imgs.map(i => [i.id, i.name]))}</optgroup>
      <optgroup label="Installers on this node">${optionList(isos.map(i => ["iso:" + i.name, `${i.name} (${i.mb} MB)`]))}
        <option value="iso-add">Add an ISO…</option></optgroup>`;
  };
  m.innerHTML = `<div class="box"><h3>New VM</h3>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmName", "Name")}<input id="vmName" maxlength="31" autocomplete="off" spellcheck="false" placeholder="db"></div>
      <div class="setrow col ctlrow">${lbl("vmProject", "Project")}<select id="vmProject">${optionList(projects.map(p => [p, projLabel(p)]), forProject)}</select></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmNode", "Node", "a node with VM host installed")}<select id="vmNode">${optionList(hosts.map(h => [h.id, h.name]))}</select></div>
      <div class="setrow col ctlrow">${lbl("vmOs", "From", "a publisher's cloud image, checked against its checksums and set up by cloud-init; or an installer's ISO on the node, which you install on the VM's Screen yourself, the way Windows or your own system goes on")}
        <select id="vmOs">${fromOptions(hosts[0]?.id || "")}</select></div>
    </div>
    <div id="vmIsoAdd" hidden>
      <div class="field">${lbl("vmIsoUrl", "The ISO's address", "an https link to the installer's .iso")}
        <input id="vmIsoUrl" type="url" spellcheck="false" autocomplete="off" placeholder="https://releases.ubuntu.com/…/ubuntu-26.04-live-server-amd64.iso"></div>
      <div class="field">${lbl("vmIsoSum", "Its SHA-256", "from the publisher's SHA256SUMS: the ISO is kept only when it matches")}
        <input id="vmIsoSum" spellcheck="false" autocomplete="off" maxlength="64" placeholder="64 hex digits"></div>
      <div class="field"><div class="actbar"><button type="button" id="vmIsoGo">Fetch it onto the node</button></div></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmCpu", "vCPUs")}<input id="vmCpu" type="number" min="1" max="64" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmMem", "Memory, GB")}<input id="vmMem" type="number" min="1" max="256" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmDisk", "Disk, GB")}<input id="vmDisk" type="number" min="2" max="4096" value="20"></div>
    </div>
    <div id="vmCloud">
      <div class="field">${lbl("vmKey", "SSH public key", "who may log in: yours, as in ~/.ssh/id_ed25519.pub. The account is builder, with sudo")}
        <textarea id="vmKey" rows="3" spellcheck="false" autocomplete="off" placeholder="ssh-ed25519 AAAA… you@laptop"></textarea></div>
      <label class="ndcap"><input type="checkbox" id="vmAgent"> Make it a node: enroll it with an agent at its first boot</label>
      <div class="hint" id="vmAgentHint" hidden>It joins your LAN as its own machine and appears on the Nodes page once it has booted, a node like any other, marked as a VM on its host; removing the VM retires the node and revokes its credential.</div>
    </div>
    <div class="prefrow ctlrow" id="vmFwRow" hidden>
      <div class="setrow col ctlrow">${lbl("vmFw", "Firmware", "UEFI for most current installers (and Windows 11); BIOS for an older one")}
        <select id="vmFw">${optionList([["uefi", "UEFI"], ["bios", "BIOS"]], "uefi")}</select></div>
    </div>
    <details class="vmmore"><summary>More: disks, network address, screen password</summary>
      <div class="field">${lbl("vmDisks", "Further disks, GB", "up to three more, each its own virtio disk (vdb, vdc, vdd), comma-separated: 100, 500")}
        <input id="vmDisks" spellcheck="false" autocomplete="off" placeholder="none"></div>
      <div class="prefrow ctlrow">
        <div class="setrow col ctlrow">${lbl("vmMac", "MAC address", "kept for good, so a DHCP reservation holds; libvirt picks one when empty")}
          <input id="vmMac" spellcheck="false" autocomplete="off" placeholder="52:54:00:…"></div>
        <div class="setrow col ctlrow">${lbl("vmPw", "Screen password", "asked when its Screen opens; one to eight characters, VNC's limit")}
          <input id="vmPw" type="password" maxlength="8" autocomplete="new-password"></div>
      </div>
    </details>
    <div class="field" id="vmWhyF" hidden><div class="hint bad" id="vmWhy"></div></div>
    ${dlgFoot(`<button type="button" id="vmCancel">Cancel</button>`, `<button type="button" id="vmGo" class="primary">Make it</button>`)}</div>`;
  m.hidden = false;
  const $m = s => m.querySelector(s);
  const say = t => { $m("#vmWhy").textContent = t; $m("#vmWhyF").hidden = !t; };
  const from = () => {
    const v = $m("#vmOs").value;
    $m("#vmIsoAdd").hidden = v !== "iso-add";
    $m("#vmCloud").hidden = v.startsWith("iso");
    $m("#vmFwRow").hidden = !v.startsWith("iso:");
    $m("#vmGo").disabled = v === "iso-add";
  };
  $m("#vmNode").onchange = () => { $m("#vmOs").innerHTML = fromOptions($m("#vmNode").value); from(); };
  $m("#vmOs").onchange = from;
  $m("#vmCancel").onclick = () => { m.hidden = true; };
  $m("#vmAgent").onchange = () => { $m("#vmAgentHint").hidden = !$m("#vmAgent").checked; };
  $m("#vmIsoGo").onclick = () => pressing($m("#vmIsoGo"), async () => {
    busy($m("#vmIsoGo"), "Asking");
    const j = await (await postJSON("/api/vms", {action: "iso-add", project: $m("#vmProject").value, node: $m("#vmNode").value,
      url: $m("#vmIsoUrl").value.trim(), sha256: $m("#vmIsoSum").value.trim()})).json();
    $m("#vmIsoGo").disabled = false; $m("#vmIsoGo").textContent = "Fetch it onto the node";
    if (j.error) return say(j.error);
    say("");
    notify(`${j.iso}: downloading onto ${j.node}, then checked; it is offered under From once it is there`);
  });
  $m("#vmGo").onclick = () => pressing($m("#vmGo"), async () => {
    busy($m("#vmGo"), "Making");
    const v = $m("#vmOs").value, iso = v.startsWith("iso:") ? v.slice(4) : "";
    const disks = $m("#vmDisks").value.split(",").map(x => x.trim()).filter(Boolean).map(Number);
    const j = await (await postJSON("/api/vms", {action: "new", project: $m("#vmProject").value,
      name: $m("#vmName").value.trim(), node: $m("#vmNode").value,
      ...(iso ? {iso, boot: $m("#vmFw").value} : {os: v, keys: $m("#vmKey").value.split("\n").map(s => s.trim()).filter(Boolean),
                                                  node_agent: $m("#vmAgent").checked}),
      vcpus: +$m("#vmCpu").value, mem_mb: Math.round(+$m("#vmMem").value * 1024), disk_gb: +$m("#vmDisk").value,
      ...(disks.length ? {disks} : {}), ...($m("#vmMac").value.trim() ? {mac: $m("#vmMac").value.trim()} : {}),
      ...($m("#vmPw").value ? {console_password: $m("#vmPw").value} : {})})).json();
    if (j.error){ say(j.error); $m("#vmGo").disabled = false; $m("#vmGo").textContent = "Make it"; return; }
    m.hidden = true;
    notify(iso ? `${j.key}: starting from ${iso} on ${j.node}; open its Screen to install`
               : `${j.key}: being made on ${j.node}; the image downloads once per node`);
    await loadVms();
  });
  from();
}
