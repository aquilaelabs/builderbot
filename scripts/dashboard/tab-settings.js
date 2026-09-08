// The Settings tab: controller-scoped settings, graduated out of the gear
// popup the moment there was more than a flyout's worth (docs/nodes.md §13).
// The gear keeps the per-browser items — theme, layout — and one entry that
// opens this; everything the CONTROLLER owns and can apply live belongs here,
// where it has room to say what it does and what it costs.
//
// Its own classic script beside index.html, per the new-surface rule. Chrome
// from docSurface(); conformance held by uniform.mjs.

// The tab repaints when what it shows has moved on the poll — a value saved
// here, or by another window — and not otherwise, so typing is not swept
// away by a poll that changed nothing. A string, compared whole by drawPanes.
function settingsLive(){
  return JSON.stringify([state?.settings?.settings, state?.idle, state?.log_days]);
}

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
    ${settingsSections()}
    <div class="row stack2">
      <div class="grow">
        <div class="name">Nodes</div>
        <div class="sub">The machines work runs on — enrollment defaults and
          per-node storage arrive with the agent (phase 3); until then the
          registry itself is the setting.</div>
        <div class="actbar"><button type="button" id="setNodes">Open the Nodes tab</button></div>
      </div>
    </div>
    <div class="row stack2">
      <div class="grow">
        <div class="name">Still in the template</div>
        <div class="sub">Paths, ports, ids and credentials: what the container
          needs before it starts stays in the Unraid template.</div>
      </div>
    </div>`;
  d.setFoot(`one scope per setting: who has to change it, and what restarts
    for it to take, decide where it lives — the placement rule is
    docs/nodes.md §13.`);
  wireLogSection(d.el);
  wireIdleSection(d.el);
  wireSettingsSections(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
}

// The settings that used to be environment variables (roadmap R29): each
// group is one section with one Apply, the field's source said beside it
// until it is saved here, and whether a change takes now or at the next
// start. Drawn from the poll's copy, so a save shows on the next poll.
const SETTING_GROUPS = [
  {title: "Dashboard", fields: [
    {key: "max_tabs", label: "Tabs open at once", type: "number", min: 1, max: 64,
     hint: "Each terminal tab is a live terminal over its own socket."}]},
  {title: "Claude Code", fields: [
    {key: "claude_auto_update", label: "Update at every start", type: "bool"},
    {key: "claude_version", label: "Version", type: "text",
     hint: "latest, or a version to pin."}]},
  {title: "Commit identity", fields: [
    {key: "git_name", label: "Name", type: "text"},
    {key: "git_email", label: "Email", type: "text",
     hint: "A GitHub noreply address keeps your email out of commits."}]},
  {title: "Packages installed at boot", fields: [
    {key: "packages_apt", label: "apt", type: "text"},
    {key: "packages_npm", label: "npm", type: "text"},
    {key: "packages_pipx", label: "pipx", type: "text",
     hint: "Space-separated. Reinstalled at every start, since an image update discards what was installed by hand."}]},
  {title: "Projects", fields: [
    {key: "project_bootstrap", label: "Run each project's .builderbot/setup.sh at start", type: "bool"}]},
  {title: "Unraid", fields: [
    {key: "unraid_icon_name", label: "Container name, for the icon", type: "text",
     hint: "Only matters if you renamed the container."}]},
];

function settingsSections(){
  const s = state?.settings;
  if (!s) return `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`;
  const src = k => s.settings[k]?.source === "env" ? `<span class="pill">from the environment</span>`
                 : s.settings[k]?.source === "default" ? `<span class="pill">default</span>` : "";
  return SETTING_GROUPS.map(g => {
    const boot = g.fields.some(f => s.meta[f.key]?.applied === "boot");
    return `<div class="row stack2" data-group="${esc(g.title)}">
      <div class="grow">
        <h4>${esc(g.title)}</h4>
        <div class="logset">
          ${g.fields.map(f => {
            const v = s.settings[f.key]?.value;
            const id = "set_" + f.key;
            const ctl = f.type === "bool"
              ? `<input id="${id}" type="checkbox" data-set="${f.key}"${v ? " checked" : ""}>`
              : f.type === "number"
                ? `<input id="${id}" type="number" data-set="${f.key}" min="${f.min}" max="${f.max}" step="1" value="${esc(String(v ?? ""))}" inputmode="numeric">`
                : `<input id="${id}" type="text" data-set="${f.key}" value="${esc(String(v ?? ""))}" spellcheck="false" autocomplete="off">`;
            return `<div class="logdays setrow">
              <label for="${id}">${esc(f.label)}</label>${ctl}${src(f.key)}
            </div>${f.hint ? `<div class="dim">${esc(f.hint)}</div>` : ""}`;
          }).join("")}
          <div class="actbar">
            <span class="state">${boot ? "takes at the next start" : "takes now"}</span>
            <button type="button" class="setApply" title="save">Apply</button>
          </div>
        </div>
      </div>
    </div>`;
  }).join("");
}

function wireSettingsSections(el){
  el.querySelectorAll('[data-group]').forEach(box => {
    const btn = box.querySelector(".setApply");
    if (!btn) return;
    const apply = async () => {
      const set = {};
      box.querySelectorAll("[data-set]").forEach(i => {
        set[i.dataset.set] = i.type === "checkbox" ? i.checked : i.value.trim();
      });
      busy(btn, "Applying");
      try{
        const r = await fetch("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: JSON.stringify({set})});
        const j = await r.json();
        if (j.error) return notify(j.error, true);
        const boot = Object.keys(set).some(k => j.meta?.[k]?.applied === "boot");
        notify(boot ? "saved — it takes at the next start" : "saved");
        refresh();
      }catch(e){ notify("settings: " + e, true); }
      finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
    };
    btn.onclick = apply;
    box.querySelectorAll("input[type=text],input[type=number]").forEach(i => {
      i.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
    });
  });
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
