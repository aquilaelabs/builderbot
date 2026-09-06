// The Settings tab: controller-scoped settings, graduated out of the gear
// popup the moment there was more than a flyout's worth (docs/nodes.md §13).
// The gear keeps the per-browser items — theme, layout — and one entry that
// opens this; everything the CONTROLLER owns and can apply live belongs here,
// where it has room to say what it does and what it costs.
//
// Its own classic script beside index.html, per the new-surface rule. Chrome
// from docSurface(); conformance held by uniform.mjs.

let settingsRev = 0;

function openSettingsTab(){
  openTab({kind: "settings", arg: "__settings", label: "Settings"});
}

function renderSettingsInto(i){
  const d = docSurface(i, "settings");
  if (!d) return;
  d.setBar(`<span class="dim">controller settings — what this container does,
    changeable while it runs. Appearance stays in the gear: it is this
    browser's, not the controller's.</span>`);
  d.list.innerHTML = `
    <div class="row stack2">
      <div class="grow">${logSection()
        || `<div class="sub">log settings arrive with the first poll…</div>`}</div>
    </div>
    <div class="row stack2">
      <div class="grow">${idleSection()}</div>
    </div>
    <div class="row stack2">
      <div class="grow">
        <div class="name">Nodes</div>
        <div class="sub">The machines work runs on — enrollment defaults and
          per-node storage arrive with the agent (phase 3); until then the
          registry itself is the setting.</div>
        <div class="acts"><button type="button" id="setNodes">Open the Nodes tab</button></div>
      </div>
    </div>
    <div class="row stack2">
      <div class="grow">
        <div class="name">Still set in the environment</div>
        <div class="sub">Container-scoped settings stay in the template — ports,
          mounts, credentials are what env is for. Controller-scoped ones move
          here as the phases that own them land, each seeded from its env var
          once and owned by this page after (docs/nodes.md §11, the
          unhardwiring). <code>DOCKER_HOST</code> and
          <code>DOCKER_HOST_PATHS</code> were the first, and are now gone: the
          sandbox is a node record with its path mapping on its row, and
          neither variable is read anywhere.</div>
      </div>
    </div>`;
  d.setFoot(`one scope per setting: who has to change it, and what restarts
    for it to take, decide where it lives — the placement rule is
    docs/nodes.md §13.`);
  wireLogSection(d.el);
  wireIdleSection(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
}

// Ending Claude sessions nobody has used for a while. One rule for this
// container and every node, and a node enforces it itself — the value rides
// the agent's hello and lives in its node.json — so it holds while this
// controller is down. That is the point: a node's sessions outlive a
// controller restart on purpose, and the rule about when they end must not.
function idleSection(){
  const m = state?.idle?.minutes;
  if (m === undefined) return `<div class="sub">the idle rule arrives with the first poll…</div>`;
  return `<h4>Claude sessions</h4>
    <div class="logset">
      <div class="dim">A session with no activity — nothing typed, nothing
        written — for this long is ended, here and on every node. 0 never
        ends one. Shells are left alone.</div>
      <div class="logdays">
        <label for="idleMin">End after</label>
        <input id="idleMin" type="number" min="0" max="100000" step="1"
               value="${m}" inputmode="numeric">
        <span>minutes idle</span>
        <button type="button" id="idleApply" title="save it — a node hears on its next poll">Apply</button>
      </div>
    </div>`;
}

function wireIdleSection(el){
  const inp = el.querySelector("#idleMin");
  if (!inp) return;
  const apply = async () => {
    const minutes = parseInt(inp.value, 10);
    if (!(minutes >= 0)) return notify("minutes has to be 0 or more", true);
    const btn = el.querySelector("#idleApply");
    if (btn) busy(btn, "Applying");
    try{
      const r = await fetch("/api/idle", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({minutes})});
      const j = await r.json();
      if (j.error) return notify(j.error, true);
      notify(j.minutes ? `Claude sessions end after ${j.minutes} idle minute(s), here and on every node`
                       : "Claude sessions are never ended for being idle");
      refresh();
    }catch(e){ notify("idle: " + e, true); }
    finally{ if (btn && btn.isConnected){ btn.disabled = false; btn.textContent = "Apply"; } }
  };
  el.querySelector("#idleApply").onclick = apply;
  inp.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
}
