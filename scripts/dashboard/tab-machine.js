"use strict";
// This machine (R90 step 8, R56 step 8): the controller's own machine on a
// bare-metal install, a page of its own in the Controller rail group and
// not a row among Machines' nodes. Its head says what the machine is (its
// name, system, cores and memory, the release this install runs and how
// long it has been up, its agent, the wall); under it the Updates section
// (Controller settings' own, R90 step 5) and the own node's row as the
// Nodes page draws any node's (tab-nodes.js ndRowHtml): its health, the
// projects on it, its sessions, GPU, USB, router, features, storage,
// network and the advanced verbs (reboot and power off among them). The
// container edition has no own machine and says so if the page is opened.
// Chrome from docSurface(); the hard rules are uniform.mjs's.

function openMachineTab(what){
  if (what) sectOpen["nodes:" + what] = true;
  openTab({kind: "machine", arg: "__machine", label: "This machine"});
  loadNodes();
}

// The own machine's row, or null before the node list lands.
function ownMachine(){
  return (nodesList || []).find(n => n.config?.own && n.state !== "retired") || null;
}

function machineHead(n){
  const r = n.reported || {};
  const img = state?.image || {};
  const mem = r.mem_mb ? `${Math.round(r.mem_mb / 1024)} GB` : "";
  const wall = r.session?.up ? "in force" : r.session?.why ? `down: ${r.session.why}` : n.live ? "not reported yet" : "";
  // A held start (R56 step 9): Start lifts it. Holding the next one is the
  // checkbox beside Reboot and Shut down (R161 step 11).
  const h = state?.held || {};
  const actions = h.held ? `<button type="button" class="primary" data-heldstart title="${esc((h.why || []).join("; "))}">Start</button>` : "";
  return pageHead({title: n.name, pills: `<span class="tag ndown">this machine</span> ${nodeStatePill(n)}${h.held ? ` <span class="pill bad">held</span>` : ""}`, actions, facts: [
    ["System", [r.os, r.hostname && r.hostname !== n.name ? r.hostname : ""].filter(Boolean).join(" · ")],
    ["Cores and memory", [r.cpu ? `${r.cpu} cpu` : "", mem].filter(Boolean).join(" · ")],
    ["Release", `${img.version || "unstamped"}${img.rev ? ` (${img.rev.slice(0, 7)})` : ""}`],
    // BuilderBot OS (R160 step 4): the image, the slot this boot came from
    // and the one that boots next when an update has been written.
    ...(r.os_image?.version ? [["Image", `BuilderBot OS ${r.os_image.version}, slot ${r.os_image.slot || "?"}${r.os_image.next && r.os_image.next !== r.os_image.slot ? `; slot ${r.os_image.next} boots next: restart to finish the update` : r.os_image.trial ? "; on trial until the health check marks it good" : ""}${r.os_image.fell_back ? `; ${r.os_image.fell_back}` : ""}`]] : []),
    ["Up", shortUptime(state?.uptime || 0)],
    ...(r.timezone ? [["Time zone", r.timezone]] : []),
    ["Agent", n.agent?.version || ""],
    ["Wall", wall]]});
}

function renderMachineInto(i){
  const d = docSurface(i, "machine");
  if (!d) return;
  d.setBar("");
  if (!state?.bare_metal){
    d.list.innerHTML = `<div class="empty">This machine is a bare-metal install's page: the machine the controller runs on, its system, its updates and what it runs as a node. This BuilderBot runs in a container, which has no machine of its own here; its nodes are on the Nodes page.</div>`;
    return;
  }
  if (nodesList === null){
    d.list.innerHTML = skTpl(`<div class="row stack2 ndrow"><div class="grow"><div class="name">${skv(7)}</div>${ndFacts(null)}</div>
      <div class="ndsections">${ND_SECTS.filter(([k]) => k !== "gpu" && k !== "usb").map(([k, t], j) => docSection("nodes", k, t, "", skRows(j ? 1 : 3))).join("")}</div></div>`);
    loadNodes();
    return;
  }
  const n = ownMachine();
  if (!n){
    d.list.innerHTML = `<div class="empty">This install's own machine is not enrolled as a node yet: the setup page shows it being set up, and the installer's --install does it (install-controller.sh --no-node leaves it out, and then there is nothing here).</div>`;
    return;
  }
  const inflight = t => (n.jobs || []).some(j => j.type === t || j.apply === t);
  d.list.innerHTML = machineHead(n)
    + (state?.release?.running !== undefined ? docSection("nodes", "updates", "Updates", state.release.newer ? `${state.release.newer} is out` : state.release.latest ? "up to date" : "", updatesSection()) : "")
    + firstbootSection()
    + ndRowHtml(n);
  wireNodesTab(d.el);
  nodesReadOnly(d.el);
  wireUpdates(d.el);
  wireHeld(d.el);
  void inflight;
}

// Hold the next start (R56 step 9, R161 step 11): a checkbox beside Restart
// and Shut down, ticked for the one restart that follows and shown ticked
// while it is armed; a bare-metal install's alone.
function holdNextBox(){
  if (!state?.bare_metal) return "";
  const armed = !!state?.held?.armed;
  return `<label class="ndcap holdnext" title="the restart after this one comes back with nothing running, for a look first"><input type="checkbox" data-holdnextbox${armed ? " checked" : ""}> hold the next start</label>`;
}
function wireHoldNext(root){
  root.querySelectorAll("[data-holdnextbox]").forEach(c => c.onchange = async () => {
    const on = c.checked;
    c.disabled = true;
    const j = await (await postJSON("/api/v1/nodes", {action: "hold-next", on})).json().catch(() => ({error: "no answer"}));
    notify(j.error || (on ? "the next start is held: nothing runs after the restart until Start is pressed on This machine" : "the next start runs as usual"), !!j.error);
    await refresh();
  });
}

// What a stick's prepared configuration did at the first boot (R161 step 8,
// firstboot.py): each piece applied, waiting for disks to be adopted, or not
// applied with why, in the facts voice. Nothing on an install that had none.
function firstbootSection(){
  const f = state?.firstboot;
  if (!f) return "";
  const line = (x, cls) => [x.what, `${x.said}${x.count ? ` (${x.count})` : ""}`, {cls}];
  const rows = [...(f.done || []).map(x => line(x, "ok")), ...(f.waiting || []).map(x => line(x, "")), ...(f.failed || []).map(x => line(x, "warn"))];
  const status = (f.failed || []).length ? `${f.failed.length} not applied` : (f.waiting || []).length ? `${f.waiting.length} waiting` : "applied";
  return docSection("nodes", "firstboot", "From the stick", status,
    `<div class="field">${factGrid(rows, "fbfacts")}<div class="hint">Taken off the stick at the first boot ${esc(ago(f.at))} and blanked there; what waits is applied once its disks are adopted.</div></div>`);
}

function wireHeld(root){
  root.querySelectorAll("[data-heldstart]").forEach(b => b.onclick = () => pressing(b, async () => {
    busy(b, "Starting");
    const j = await (await postJSON("/api/v1/nodes", {action: "start-held"})).json().catch(() => ({error: "no answer"}));
    notify(j.error || "started: sessions run again", !!j.error);
    await refresh();
  }));
  wireHoldNext(root);
}
