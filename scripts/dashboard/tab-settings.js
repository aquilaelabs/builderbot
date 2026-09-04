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
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
}
