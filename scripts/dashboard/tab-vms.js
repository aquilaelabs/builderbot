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
let vmsNode = "";               // the node picked in the bar, "" for every one
let vmsChip = "";               // the project chip pressed, "" for All (a view, never saved)
// Cards or a list, as Containers has them: the same card either way, whole
// as a row or behind one line that opens into it. This browser's choice.
let vmView = (() => { try{ return localStorage.getItem("bb.vmview") === "list" ? "list" : "cards"; }catch(e){ return "cards"; } })();
const VM_COLS = [{label: "VM"}, {label: "State", w: "8.5rem"}, {label: "Node", w: "minmax(0,.7fr)"},
                 {label: "System", w: "minmax(0,.8fr)"}, {label: "Address", w: "minmax(0,.9fr)"}];
// When this page asked each VM (PROJECT/NAME) to shut down: a system that
// ignores the request stays up with its job a success, and the row says so
// rather than leaving Stop looking broken (B308).
const vmStopAsked = {};

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
    : up && v.ip ? `at ${esc(v.ip)}`
    // On the LAN (R100) its address is the LAN's DHCP's, which only QEMU's
    // guest agent inside it tells the node.
    : up && v.hw?.net === "lan" && !v.node_id ? "on the LAN: its address shows once QEMU's guest agent runs inside it"
    : up ? "taking its address" : "";
  // What its guest agent says of it (R110 step 8, the operator, 22 Oct:
  // like VMware Tools): its own name, system and kernel, who is signed in,
  // and its addresses when it has more than the one the reach line says.
  const g = up ? v.guest || {} : {};
  const more = (g.ips || []).filter(ip => ip !== v.ip);
  const inside = [g.hostname, g.os, g.kernel && `kernel ${g.kernel}`, g.users ? `${g.users} signed in` : "",
                  more.length ? `also at ${more.join(", ")}` : ""].filter(Boolean).map(esc).join(`<span class="sep"></span>`);
  // Made a node (step 14): its row on the Nodes page.
  const asNode = v.node_id ? `<div class="sub dmorigin">a node too: ${pageLink("nodes", "on the Nodes page", `#/machines/nodes/${encodeURIComponent(v.node_id)}`)}</div>` : "";
  const snaps = v.snapshots || [];
  // Who else is on it now (the operator, 21 Oct): a Screen is shared, one
  // keyboard among them; a Console is one person's at a time.
  const me = vmsData?.me || "";
  const who = list => list.map(w => w.uid && w.uid === me ? "you" : w.name);
  const onScreen = who(v.on?.screen || []), onConsole = who(v.on?.console || []);
  const others = [...onScreen, ...onConsole].some(w => w !== "you");
  const onLine = onScreen.length || onConsole.length ? `<div class="sub dmstate${others ? " warn" : ""}">${[
      onScreen.length ? `${esc(andList(onScreen))} ${onScreen.length > 1 || onScreen[0] === "you" ? "are" : "is"} on its Screen, sharing one keyboard` : "",
      onConsole.length ? `${esc(andList(onConsole))} ${onConsole[0] === "you" ? "have" : "has"} its Console` : ""].filter(Boolean).join("; ")}</div>` : "";
  // Asked to shut down here a while ago and still up: its system did not take
  // the power button, which Force stop pulls the plug on.
  const asked = vmStopAsked[`${v.project}/${v.name}`];
  if (asked && !up) delete vmStopAsked[`${v.project}/${v.name}`];
  const ignored = asked && up && Date.now() - asked > 45000
    ? `<div class="sub dmstate warn">asked to shut down ${Math.max(1, Math.round((Date.now() - asked) / 60000))} min ago and still running: its system may not answer the power button, and Force stop under More ends it at once</div>` : "";
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
      v.state === "stopped" ? `<button type="button" data-vmhw title="CPU threads, memory ceiling, network, a shared folder, devices">Hardware…</button>` : "",
      `<button type="button" class="danger" data-vm="remove"${v.state === "removing" ? " disabled" : ""}
        title="destroy it, with its disk and its snapshots">Remove</button>`])}`;
  const inner = `
    <div class="grow">
      <div class="dmhead">
        <div class="dmid">
          <div class="name">${esc(v.name)}${vmPill(v)}</div>
          ${origin ? `<div class="sub dmorigin">${origin}</div>` : ""}
          ${reach ? `<div class="sub dmstate${v.ip ? " ok" : ""}">${reach}</div>` : ""}
          ${inside ? `<div class="sub dmorigin vmguest">${inside}</div>` : ""}
          ${asNode}
          ${vmHwLine(v)}
          ${onLine}${ignored}
          ${may && v.state !== "making" ? `<label class="ndcap vmauto"><input type="checkbox" data-vmauto${v.autostart ? " checked" : ""}> starts with its host</label>` : ""}
          ${v.error ? `<div class="sub dmstate bad">${esc(v.error)}</div>` : ""}
        </div>
        <div class="actbar dmacts">${acts}</div>
      </div>
      ${snaps.length ? `<div class="vmsnaps"><span class="vmsnaplbl">Snapshots</span>${snaps.map(s => `<div class="vmsnap"><code>${esc(s)}</code>${may && !busy ? `
        <button type="button" data-vm="revert" data-snap="${esc(s)}" title="back to ${esc(s)}: what changed since is lost">Revert</button>
        <button type="button" data-vm="snapshot-rm" data-snap="${esc(s)}" title="delete this snapshot">Delete</button>` : ""}</div>`).join("")}</div>` : ""}
    </div>`;
  if (vmView !== "list") return `<div class="row stack2" data-vm-key="${esc(v.key)}">${inner}</div>`;
  return `<details class="row stack2 dmline" data-vm-key="${esc(v.key)}"${sectAttr(`vms:line:${v.key}`)}>
    ${tblLine(VM_COLS, [`<span class="name">${esc(v.name)}</span>`, vmPill(v), esc(v.node_name || ""),
                        esc(v.os_name || v.os || ""), up && v.ip ? esc(v.ip) : ""], "summary", "dmsum")}
    <div class="dmbody">${inner}</div></details>`;
}

// Domains on a node's libvirt that BuilderBot did not make (R165 step 1):
// an administrator reads them by name, state and size, and nothing on the
// page acts on one; libvirt's own tools do, on the machine.
function vmOthersHtml(rows){
  const size = v => [v.vcpus ? `${v.vcpus} vCPU` : "", v.mem_mb ? (v.mem_mb >= 1024 ? `${+(v.mem_mb / 1024).toFixed(1)} GB` : `${v.mem_mb} MB`) : ""].filter(Boolean).join(" · ");
  return `<section class="dmcard vmothers"><div class="field dmgroup"><b>Not BuilderBot's</b><span class="sub"> · on a node's libvirt, made outside BuilderBot: read here, never changed from here</span></div>
    <div class="rows">${rows.map(v => `<div class="row stack2 vmother" data-vmother="${esc(v.node)}/${esc(v.name)}"><div class="grow"><div class="dmhead"><div class="dmid">
      <div class="name">${esc(v.name)}<span class="pill${v.state === "running" ? " ok" : ""}">${esc(v.state || "unknown")}</span></div>
      <div class="sub dmorigin">${[esc(v.node_name || ""), esc(size(v))].filter(Boolean).join(`<span class="sep"></span>`)}</div>
    </div></div></div></div>`).join("")}</div></section>`;
}

// A VM whose repository is gone is in no project (the operator, 26 Oct),
// grouped and chipped as No project.
// ...and the machine's own (R165 step 3): the NAS's apps and desktops, no
// project's, grouped and chipped as such.
const vmOwner = p => p === "machine" ? "This machine's own" : (vmsData?.unowned || []).includes(p) ? "No project" : projLabel(p);
function vmGroupsHtml(rows){
  const byName = (a, b) => a.localeCompare(b, undefined, {sensitivity: "base"});
  const owners = [...new Set(rows.map(v => v.project))].sort((a, b) => byName(vmOwner(a), vmOwner(b)));
  const group = o => {
    const html = rows.filter(v => v.project === o).sort((a, b) => byName(a.name, b.name)).map(vmRow).join("");
    return vmView === "list" ? tblWrap(VM_COLS, html, "dmtbl") : html;
  };
  return owners.map(o => `<section class="dmcard"><div class="field dmgroup" data-style="--gc:${colorTone(projectColor(o)) || "var(--accent)"}"><b>${
      esc(vmOwner(o))}</b></div>${group(o)}</section>`).join("");
}

// The bar, as Containers' is (the operator, 26 Oct): the node switcher, every
// VM host and Every node first, the search, Cards and List, and New VM.
function vmBar(ghost){
  const dead = ghost ? " disabled" : "";
  const any = !ghost && Object.values(vmsData?.can || {}).includes("write");
  const hosts = ghost ? null : vmsData?.hosts || [];
  return `<div class="field docbarrow dmpick">${
      hosts && hosts.length < 2 ? "" : nodePick("vmPickNode", hosts && [{id: "", name: "Every node"}, ...hosts], vmsNode)}<input${ghost ? "" : ` id="vmSearch"`} type="search"
      placeholder="${isPhone() ? "search" : "name, OS or project"}" autocomplete="off" aria-label="narrow the VMs: name, OS or project" value="${esc(vmsSearch)}"${dead}><span class="sp"></span>
      ${viewSeg("vmview", vmView, "each VM as a card", "one line per VM, opening into its card", dead)}${
      (any || ghost) && !featureOff("vms") ? `<span class="actbar"><button type="button"${ghost ? "" : ` id="bVmNew"`} class="primary"${
        dead || !(vmsData?.hosts || []).length ? " disabled" : ""}>${barSaid("New VM", "New")}</button></span>` : ""}</div>`;
}

// The tiles, as Containers has them: how many run of how many, the projects
// they are under, and any that failed or are not on their node, in their tone.
function vmTiles(vms, projects){
  const running = vms.filter(v => v.state === "running").length;
  const broke = vms.filter(v => ["failed", "crashed", "missing"].includes(v.state)).length;
  return statTiles([
    {label: "running", value: running, sub: `of ${vms.length}${matchMedia("(max-width:440px)").matches ? "" : ` VM${vms.length === 1 ? "" : "s"}`}`,
     tone: vms.length && !running ? "warn" : ""},
    {label: "projects", value: projects},
    {label: "snapshots", value: vms.reduce((n, v) => n + (v.snapshots || []).length, 0)},
    {label: broke === 1 ? "needs a look" : "need a look", value: broke, tone: "bad", omit: !broke,
     title: "failed, crashed, or not on its node"},
  ]);
}
// A chip per project with a VM here (the chips rule), by name.
function vmChipGroups(vms){
  const owners = [...new Set(vms.map(v => v.project))];
  return owners.map(o => ({key: o, label: vmOwner(o), count: vms.filter(v => v.project === o).length}))
    .sort((a, b) => a.label.localeCompare(b.label, undefined, {sensitivity: "base"}));
}

function renderVmsInto(i){
  const el = $("doc" + i);
  if (!el) return;
  el.classList.add("flush");
  if (!vmsData){
    el.__vmHtml = "";
    el.innerHTML = `<div class="doctab vmtab">${skTpl(`${vmBar(true)}${statTiles([{label: "running", value: GHOST, sub: GHOST},
        {label: "projects", value: GHOST}, {label: "snapshots", value: GHOST}])}
      <section class="dmcard"><div class="field dmgroup"><b>${skv(8)}</b></div>${skRows(2)}</section>`)}</div>`;
    loadVms();
    return;
  }
  const q = vmsSearch.trim().toLowerCase();
  if (vmsNode && !(vmsData.hosts || []).some(h => h.id === vmsNode)) vmsNode = "";
  // The node picked narrows everything under the bar, the tiles and the
  // chips counting what it hosts; a chip and the search narrow the rows.
  const onNode = (vmsData.vms || []).filter(v => !vmsNode || v.node === vmsNode);
  const chips = vmChipGroups(onNode);
  if (vmsChip && !chips.some(c => c.key === vmsChip)) vmsChip = "";
  const rows = onNode.filter(v => !vmsChip || v.project === vmsChip).filter(v => !q || [v.name, v.os, v.os_name, v.node_name, projLabel(v.project), v.ip]
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
  const head = off || vmsErr || !onNode.length ? "" : vmTiles(onNode, chips.length) + chipBar(chips, vmsChip, "data-vmchip");
  // A reload that lands while the search is being typed in keeps the box's
  // focus and its caret, as Containers' does: the box is drawn anew.
  // Written only when it says something new, as the Containers page is
  // (the operator, 26 Oct): a read bringing the same VMs leaves the page,
  // its menus and its focus alone.
  // The domains a node's libvirt has that BuilderBot did not make (R165
  // step 1): read here by an administrator, under the node picked, with no
  // button on them; not counted in the tiles or the chips, which are
  // BuilderBot's own VMs.
  const others = off ? [] : (vmsData.others || []).filter(v => !vmsNode || v.node === vmsNode)
    .filter(v => !q || [v.name, v.node_name].some(x => String(x || "").toLowerCase().includes(q)));
  const html = `<div class="doctab vmtab">${vmBar(false)}${head}${empty || vmGroupsHtml(rows)}${others.length ? vmOthersHtml(others) : ""}</div>`;
  if (el.__vmHtml === html && el.querySelector(":scope > .vmtab")) return;
  const typing = document.activeElement?.id === "vmSearch" && el.contains(document.activeElement) ? document.activeElement.selectionStart : null;
  el.innerHTML = html;
  el.__vmHtml = html;
  wireVms(el);
  const sb = typing === null ? null : el.querySelector("#vmSearch");
  if (sb){ sb.focus(); try{ sb.setSelectionRange(typing, typing); }catch(e){ /* a type that cannot */ } }
}

function wireVms(el){
  const s = el.querySelector("#vmSearch");
  if (s) s.oninput = () => { vmsSearch = s.value; const at = s.selectionStart; drawPanes();
    const n = document.querySelector("#vmSearch"); if (n){ n.focus(); n.setSelectionRange(at, at); } };
  el.querySelectorAll("[data-vmchip]").forEach(c => c.onclick = () => { vmsChip = c.dataset.vmchip; drawPanes(); });
  const np = el.querySelector("#vmPickNode");
  if (np) np.onchange = () => { vmsNode = np.value; drawPanes(); };
  el.querySelectorAll("[data-vmview]").forEach(b => b.onclick = () => {
    vmView = b.dataset.vmview === "list" ? "list" : "cards";
    try{ localStorage.setItem("bb.vmview", vmView); }catch(e){ /* private mode */ }
    drawPanes();
  });
  const nb = el.querySelector("#bVmNew");
  if (nb) nb.onclick = () => openNewVm();
  el.querySelectorAll("[data-vm-key]").forEach(row => {
    const v = (vmsData?.vms || []).find(x => x.key === row.dataset.vmKey);
    if (!v) return;
    row.querySelectorAll("[data-vmcon]").forEach(b => b.onclick = async () => {
      // One person's at a time (the operator, 21 Oct): somebody else's is
      // refused, but for the project's owner and the administrators, who
      // may take it over, asked first, and the person is told.
      const held = (v.on?.console || []).filter(w => !w.uid || w.uid !== vmsData?.me).map(w => w.name);
      if (held.length){
        if (!vmsData?.take?.[v.project])
          return notify(`${andList(held)} ${held.length > 1 ? "have" : "has"} ${v.name}'s Console open: it is one person's at a time. Its Screen can be shared, or ask them.`, true);
        if (!await askYes(`Take ${v.name}'s Console from ${andList(held)}?\n\nA console is one person's at a time: theirs ends, and they are told you took it. Its Screen can be shared instead.`)) return;
        const j = await (await postJSON("/api/vms", {action: "console-take", project: v.project, name: v.name})).json();
        if (j.error) return notify(j.error, true);
      }
      openTab({kind: "term", arg: `vm:${v.project}:${v.name}`, label: `console ${v.name}`});
    });
    row.querySelectorAll("[data-vmhw]").forEach(b => b.onclick = () => openVmHardware(v));
    row.querySelectorAll("[data-vmauto]").forEach(c => c.onchange = () => pressing(c, async () => {
      const j = await (await postJSON("/api/vms", {action: "autostart", project: v.project, name: v.name, on: c.checked})).json();
      if (j.error){ notify(j.error, true); c.checked = !c.checked; }
      else notify(`${v.name} ${c.checked ? "starts" : "no longer starts"} with its host`);
    }));
    row.querySelectorAll("[data-vmscreen]").forEach(b => b.onclick = () =>
      openTab({kind: "term", arg: `screen:${v.project}:${v.name}`, label: `screen ${v.name}`}));
    row.querySelectorAll("[data-vm]").forEach(b => b.onclick = () => pressing(b, async () => {
      const action = b.dataset.vm;
      const body = {action, project: v.project, name: v.name};
      if (action === "remove" && !await askYes(`Remove ${v.name}?\n\nThe VM is destroyed with its disk${
            (v.snapshots || []).length ? ` and its ${v.snapshots.length} snapshot${v.snapshots.length === 1 ? "" : "s"}` : ""}${
            v.node_id ? ", and its node is retired with its credential revoked" : ""}. It cannot be undone.`)) return;
      if (action === "stop" && b.dataset.force && !await askYes(`Force ${v.name} to stop?\n\nIt stops at once, as if unplugged: what it had not saved is lost.`)) return;
      if (action === "revert" && !await askYes(`Revert ${v.name} to ${b.dataset.snap}?\n\nWhat changed in it since that snapshot is lost.`)) return;
      if (action === "snapshot-rm" && !await askYes(`Delete the snapshot ${b.dataset.snap} of ${v.name}?`)) return;
      if (action === "snapshot"){
        const name = await askText(`A snapshot of ${v.name}\n\nIts name: letters, digits, dots and dashes.`,
          {value: "before-" + new Date().toISOString().slice(0, 10), verb: "Take snapshot", label: "Name"});
        if (!name) return;
        body.snapshot = name.trim();
      }
      if (action === "disk-grow"){
        const devs = ["vda", "vdb", "vdc", "vdd"].slice(0, 1 + (v.disks || []).length);
        const sizes = [v.disk_gb, ...(v.disks || [])];
        const dev = devs.length > 1 ? await ask({text: `Which disk of ${v.name} grows?`,
          choices: devs.map((d, i) => ({label: `${d}, ${sizes[i]} GB`, value: d}))}) : "vda";
        if (!dev || !devs.includes(dev.trim())) return;
        const gb = await askText(`Grow ${dev.trim()} of ${v.name}\n\nIt is ${sizes[devs.indexOf(dev.trim())]} GB now.`,
          {value: String(sizes[devs.indexOf(dev.trim())] * 2), verb: "Grow", label: "New size, GB"});
        if (!gb) return;
        body.disk = dev.trim(); body.gb = +gb;
      }
      if (action === "disk-add"){
        const gb = await askText(`Add a disk to ${v.name}`, {value: "20", verb: "Add disk", label: "Size, GB"});
        if (!gb) return;
        body.gb = +gb;
      }
      if (action === "eject" && !await askYes(`Eject ${v.iso} from ${v.name}?\n\nIts next boot is from its disk, where the installer put the system.`)) return;
      if (b.dataset.snap) body.snapshot = b.dataset.snap;
      if (b.dataset.force) body.force = true;
      busy(b, {start: "Starting", stop: "Stopping", restart: "Restarting", remove: "Removing", snapshot: "Saving",
               revert: "Reverting", "snapshot-rm": "Deleting", eject: "Ejecting", "disk-grow": "Growing", "disk-add": "Adding"}[action] || "Working");
      const j = await (await postJSON("/api/vms", body)).json();
      if (!j.error && action === "stop" && !body.force) vmStopAsked[`${v.project}/${v.name}`] = Date.now();
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
      <div class="setrow col ctlrow">${lbl("vmProject", "Belongs to", "a project, whose sessions reach it; or this machine's own, an administrator's alone")}<select id="vmProject">${optionList(projects.map(p => [p, vmOwner(p)]), forProject)}</select></div>
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
      <div class="field">${lbl("vmIsoFile", "Or upload one", "an .iso from this computer, sent through the controller to the node and checked there")}
        <input id="vmIsoFile" type="file" accept=".iso"></div>
      <div class="field"><div class="actbar"><button type="button" id="vmIsoUp" disabled>Upload it to the node</button></div></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmCpu", "vCPUs")}<input id="vmCpu" type="number" min="1" max="64" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmMem", "Memory, GB")}<input id="vmMem" type="number" min="1" max="256" value="2"></div>
      <div class="setrow col ctlrow">${lbl("vmDisk", "Disk, GB")}<input id="vmDisk" type="number" min="2" max="4096" value="20"></div>
    </div>
    <div id="vmCloud">
      <div class="field">${lbl("vmKey", "SSH public key", "who may log in: yours, as in ~/.ssh/id_ed25519.pub. The account is builder (admin on a VM made a node), with sudo")}
        <textarea id="vmKey" rows="3" spellcheck="false" autocomplete="off" placeholder="ssh-ed25519 AAAA… you@laptop"></textarea></div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="vmAgent"> Make it a node: enroll it with an agent at its first boot</label>
      <div class="hint" id="vmAgentHint" hidden>It joins your LAN as its own machine and appears on the Nodes page once it has booted, a node like any other, marked as a VM on its host; removing the VM retires the node and revokes its credential.</div></div>
    </div>
    <div class="prefrow ctlrow" id="vmFwRow" hidden>
      <div class="setrow col ctlrow">${lbl("vmFw", "Firmware", "UEFI for most current installers (and Windows 11); BIOS for an older one")}
        <select id="vmFw">${optionList([["uefi", "UEFI"], ["bios", "BIOS"]], "uefi")}</select></div>
    </div>
    <details class="vmmore"><summary>More: disks, network, screen password, hardware</summary>
      <div class="field">${lbl("vmDisks", "Further disks, GB", "up to three more, each its own virtio disk (vdb, vdc, vdd), comma-separated: 100, 500")}
        <input id="vmDisks" spellcheck="false" autocomplete="off" placeholder="none"></div>
      <div class="prefrow ctlrow">
        <div class="setrow col ctlrow">${lbl("vmMac", "MAC address", "kept for good, so a DHCP reservation holds; libvirt picks one when empty")}
          <input id="vmMac" spellcheck="false" autocomplete="off" placeholder="52:54:00:…"></div>
        <div class="setrow col ctlrow">${lbl("vmPw", "Screen password", "asked when its Screen opens; one to eight characters, VNC's limit")}
          <input id="vmPw" type="password" maxlength="8" autocomplete="new-password"></div>
      </div>
      <div class="field"><label class="ndcap"><input type="checkbox" id="vmAuto"> Starts with its host</label></div>
      <div id="vmHwBox"></div>
    </details>
    <div class="field" id="vmWhyF" hidden><div class="hint bad" id="vmWhy"></div></div>
    ${dlgFoot(`<button type="button" id="vmCancel">Cancel</button>`, `<button type="button" id="vmGo" class="primary">Make it</button>`)}</div>`;
  m.hidden = false;
  const $m = s => m.querySelector(s);
  // More opens as every fold here does, slid rather than snapped.
  $m(".vmmore > summary").onclick = e => { e.preventDefault(); const d = e.currentTarget.parentElement; slideDetails(d, !d.open); };
  // Brought into view when said: at the dialog's foot, under More, it sat
  // behind the footer and a refused press looked like nothing (B304).
  const say = t => { $m("#vmWhy").textContent = t; $m("#vmWhyF").hidden = !t;
    if (t) $m("#vmWhyF").scrollIntoView({block: "nearest"}); };
  const from = () => {
    const v = $m("#vmOs").value;
    $m("#vmIsoAdd").hidden = v !== "iso-add";
    $m("#vmCloud").hidden = v.startsWith("iso");
    $m("#vmFwRow").hidden = !v.startsWith("iso:");
    $m("#vmGo").disabled = v === "iso-add";
  };
  const hwBox = () => {
    const nid = $m("#vmNode").value;
    document.getElementById("vmhwmodal")?.replaceChildren();   // one set of the fields' ids on the page
    $m("#vmHwBox").innerHTML = vmHwFields((vmsData?.hosts || []).find(h => h.id === nid), {}, !!state?.can?.admin);
    vmHwWire($m("#vmHwBox"), nid, $m("#vmProject").value);
  };
  hwBox();
  $m("#vmNode").onchange = () => { $m("#vmOs").innerHTML = fromOptions($m("#vmNode").value); from(); hwBox(); };
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
  $m("#vmIsoFile").onchange = () => { $m("#vmIsoUp").disabled = !$m("#vmIsoFile").files.length; };
  $m("#vmIsoUp").onclick = () => pressing($m("#vmIsoUp"), async () => {
    const f = $m("#vmIsoFile").files[0];
    if (!f) return;
    busy($m("#vmIsoUp"), "Uploading");
    const q = new URLSearchParams({project: $m("#vmProject").value, node: $m("#vmNode").value, name: f.name});
    let j;
    try{ j = await (await fetch("/api/vms-iso-upload?" + q, {method: "POST", body: f,
                                 headers: {"Content-Type": "application/octet-stream"}})).json(); }
    catch(e){ j = {error: String(e)}; }
    $m("#vmIsoUp").disabled = false; $m("#vmIsoUp").textContent = "Upload it to the node";
    if (j.error) return say(j.error);
    say("");
    notify(`${j.iso}: uploaded; ${j.node} takes it from the controller and checks it, then it is offered under From`);
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
      ...($m("#vmPw").value ? {console_password: $m("#vmPw").value} : {}),
      hw: vmHwRead($m("#vmHwBox")), autostart: $m("#vmAuto").checked})).json();
    if (j.error){ say(j.error); $m("#vmGo").disabled = false; $m("#vmGo").textContent = "Make it"; return; }
    m.hidden = true;
    notify(iso ? `${j.key}: starting from ${iso} on ${j.node}; open its Screen to install`
               : `${j.key}: being made on ${j.node}; the image downloads once per node`);
    await loadVms();
  });
  from();
}

// ---- a VM's hardware beyond size (R100) -----------------------------------
// One set of fields for New VM's More and the Hardware dialog of a stopped VM:
// CPU threads in their core pairs (as Unraid draws them), a memory ceiling it
// may balloon to, its network, a folder of the project shared in, and the
// host's devices passed through, which only an administrator is shown.
function vmHwLine(v){
  const hw = v.hw || {}, bits = [];
  if ((hw.cpuset || []).length) bits.push(`pinned to threads ${hw.cpuset.join(", ")}`);
  if (hw.mem_max_mb) bits.push(`memory up to ${+(hw.mem_max_mb / 1024).toFixed(1)} GB`);
  if (hw.net === "lan" && !v.node_id) bits.push("on the LAN");
  if (hw.share?.path) bits.push(`sees ${hw.share.path.replace(/^\/workspace\//, "")}${hw.share.ro ? " read-only" : ""} as "${hw.share.tag}"`);
  // The USB devices it was given from its node's page, by name (R116);
  // the rest of what is passed through, counted.
  const usb = v.usb || [];
  if (usb.length) bits.push(`USB: ${usb.map(u => u.name || `${u.vendor.slice(2)}:${u.product.slice(2)}`).join(", ")}`);
  const rest = (hw.devices || []).filter(d => d.type !== "usb" || !usb.some(u => u.vendor === d.vendor && u.product === d.product));
  if (rest.length) bits.push(`${rest.length} device${rest.length > 1 ? "s" : ""} passed through`);
  return bits.length ? `<div class="sub dmorigin">${esc(bits.join(" · "))}</div>` : "";
}
function vmHwFields(host, hw, admin){
  const pin = new Set(hw?.cpuset || []);
  const cpus = (host?.hw?.cpus || []).map(pair => `<label class="ndcap vmcpu"><input type="checkbox" data-cpus="${pair.join(",")}"${
    pair.every(c => pin.has(c)) ? " checked" : ""}> ${pair.map(c => `cpu ${c}`).join(" / ")}</label>`).join("");
  const sh = hw?.share || {};
  const devs = admin ? [
    ...(host?.hw?.usb || []).map(u => `<label class="ndcap"><input type="checkbox" data-usb="${esc(u.vendor)}:${esc(u.product)}"${
      (hw?.devices || []).some(d => d.type === "usb" && d.vendor === u.vendor && d.product === u.product) ? " checked" : ""}> USB: ${esc(u.name)}</label>`),
    ...(host?.hw?.pci || []).map(p => `<label class="ndcap"><input type="checkbox" data-pci="${esc(p.addr)}"${
      (hw?.devices || []).some(d => d.type === "pci" && d.addr === p.addr) ? " checked" : ""}${host?.hw?.iommu ? "" : " disabled"}> PCI ${esc(p.addr)} (${
      esc(p.class.startsWith("0x03") ? "display" : p.class.startsWith("0x04") ? "sound" : p.class.startsWith("0x0c03") ? "USB controller" : p.class.startsWith("0x02") ? "network" : "storage")}, ${esc(p.driver || "no driver")}${p.group ? `, group ${esc(p.group)}` : ""})${
      p.class.startsWith("0x0300") ? ` <button type="button" data-vbios="${esc(p.addr)}" title="read this card's vBIOS, which passing a GPU through may need">Dump vBIOS</button>
        <button type="button" data-vbiosgive="${esc(p.addr)}" title="the card maker's .rom, or one from a collection, used instead of a dump">Give a .rom…</button>` : ""}</label>`)] : [];
  return `<div class="field">${lbl("vmHwCpus", "CPU threads", "pin its vCPUs to these host threads, each core's pair together; none ticked leaves the host to schedule it")}
      <div class="vmcpus" id="vmHwCpus">${cpus || `<span class="sub">the node has not said its CPUs yet</span>`}</div>
      <label class="ndcap"><input type="checkbox" id="vmHwShareCpus"> Share them with another VM pinned there</label></div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmHwMemMax", "Memory ceiling, GB", "it starts with its memory and may balloon up to this; empty for none")}
        <input id="vmHwMemMax" type="number" min="1" max="256" step="0.5" value="${hw?.mem_max_mb ? +(hw.mem_max_mb / 1024).toFixed(1) : ""}"></div>
      <div class="setrow col ctlrow">${lbl("vmHwNet", "Network", "its project's own network, or your LAN as a machine of its own")}
        <select id="vmHwNet">${optionList([["project", "Its project's network"], ["lan", "The LAN"]], hw?.net || "project")}</select></div>
    </div>
    <div class="prefrow ctlrow">
      <div class="setrow col ctlrow">${lbl("vmHwShare", "Shared folder", "a folder of the project, seen inside the VM by: mount -t virtiofs project /mnt; empty for none, a dot for the whole project")}
        <input id="vmHwShare" spellcheck="false" autocomplete="off" placeholder="none" value="${esc(sh.path ? sh.path.replace(/^\/workspace\/[^/]+\/?/, "") || "." : "")}"></div>
      <label class="ndcap"><input type="checkbox" id="vmHwShareRo"${sh.ro ? " checked" : ""}> read-only</label>
    </div>
    ${admin ? `<div class="field">${lbl("vmHwDevs", "Devices passed through", "the host's own, given to this VM alone while it runs; a PCI device needs the IOMMU on")}
      <div id="vmHwDevs">${devs.join("") || `<span class="sub">none on this node</span>`}${host?.hw?.iommu ? "" : `<div class="sub warn">The IOMMU is off on this node, so no PCI device can be passed through.</div>`}</div></div>` : ""}`;
}
function vmHwRead(root){
  const cpus = [...root.querySelectorAll("[data-cpus]:checked")].flatMap(c => c.dataset.cpus.split(",").map(Number));
  const mx = +root.querySelector("#vmHwMemMax")?.value || 0;
  const share = root.querySelector("#vmHwShare")?.value.trim() || "";
  const devices = [...root.querySelectorAll("[data-usb]:checked")].map(c => { const [vendor, product] = c.dataset.usb.split(":"); return {type: "usb", vendor, product}; })
    .concat([...root.querySelectorAll("[data-pci]:checked")].map(c => ({type: "pci", addr: c.dataset.pci})));
  return {cpuset: cpus, share_cpus: !!root.querySelector("#vmHwShareCpus")?.checked, mem_max_mb: Math.round(mx * 1024),
          net: root.querySelector("#vmHwNet")?.value || "project",
          share: share ? {path: share === "." ? "" : share, ro: !!root.querySelector("#vmHwShareRo")?.checked} : {},
          ...(root.querySelector("#vmHwDevs") ? {devices} : {})};
}
function vmHwWire(root, nodeId, project){
  root.querySelectorAll("[data-vbios]").forEach(b => b.onclick = e => { e.preventDefault(); pressing(b, async () => {
    busy(b, "Asking");
    const j = await (await postJSON("/api/vms", {action: "vbios", project, node: nodeId, addr: b.dataset.vbios})).json();
    b.disabled = false; b.textContent = "Dump vBIOS";
    notify(j.error || `reading ${b.dataset.vbios}'s vBIOS on the node; the job says how it went`, !!j.error);
  }); });
  root.querySelectorAll("[data-vbiosgive]").forEach(b => b.onclick = e => {
    e.preventDefault();
    const pick = document.createElement("input");
    pick.type = "file"; pick.accept = ".rom,.bin";
    pick.onchange = () => pressing(b, async () => {
      const f = pick.files[0];
      if (!f) return;
      if (f.size > 2 * 1024 * 1024) return notify("a vBIOS is 2 MB at most", true);
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 32768) bin += String.fromCharCode(...bytes.subarray(i, i + 32768));
      const j = await (await postJSON("/api/vms", {action: "vbios", project, node: nodeId, addr: b.dataset.vbiosgive, rom: btoa(bin)})).json();
      notify(j.error || `${f.name}: kept on the node for ${b.dataset.vbiosgive}`, !!j.error);
    });
    pick.click();
  });
}
function openVmHardware(v){
  let m = document.getElementById("vmhwmodal");
  if (!m){
    m = document.createElement("div");
    m.id = "vmhwmodal"; m.className = "modal"; m.hidden = true;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    document.body.appendChild(m);
    armModal(m);
  }
  const host = (vmsData?.hosts || []).find(h => h.id === v.node);
  document.getElementById("vmHwBox")?.replaceChildren();   // New VM's, so the fields' ids are this dialog's alone
  m.innerHTML = `<div class="box"><h3>${esc(v.name)}'s hardware</h3>
    ${vmHwFields(host, v.hw || {}, !!state?.can?.admin)}
    <div class="field" id="vmHwWhyF" hidden><div class="hint bad" id="vmHwWhy"></div></div>
    ${dlgFoot(`<button type="button" id="vmHwCancel">Cancel</button>`, `<button type="button" id="vmHwGo" class="primary">Save</button>`)}</div>`;
  m.hidden = false;
  vmHwWire(m, v.node, v.project);
  m.querySelector("#vmHwCancel").onclick = () => { m.hidden = true; };
  m.querySelector("#vmHwGo").onclick = () => pressing(m.querySelector("#vmHwGo"), async () => {
    busy(m.querySelector("#vmHwGo"), "Saving");
    const j = await (await postJSON("/api/vms", {action: "hardware", project: v.project, name: v.name, hw: vmHwRead(m)})).json();
    if (j.error){ m.querySelector("#vmHwWhy").textContent = j.error; m.querySelector("#vmHwWhyF").hidden = false;
                  m.querySelector("#vmHwGo").disabled = false; m.querySelector("#vmHwGo").textContent = "Save"; return; }
    m.hidden = true;
    notify(`${v.name}: its hardware changes on the node; it takes effect at its next start`);
    await loadVms();
  });
}
