// The Settings tab: controller-scoped settings, graduated out of the gear
// popup the moment there was more than a flyout's worth (docs/nodes.md §13).
// The gear keeps the per-browser items (theme, layout) and one entry that
// opens this; everything the CONTROLLER owns and can apply live belongs here,
// where it has room to say what it does and what it costs.
//
// Its own classic script beside index.html, per the new-surface rule. Chrome
// from docSurface(); conformance held by uniform.mjs.

// The tab repaints when what it shows has moved on the poll: a value saved
// here, or by another window, and not otherwise, so typing is not swept
// away by a poll that changed nothing. A string, compared whole by drawPanes.
function settingsLive(){
  return JSON.stringify([state?.settings?.settings, state?.idle, state?.log_days]);
}

// Typed and not yet applied, by control id, across the tab's redraws: one
// section's Apply repaints the whole tab from the poll, and must not throw
// away what was typed into another (docs/design-language.md, Settings).
const settingsDraft = {};
const sdVal = (id, value) => settingsDraft[id] ?? value;
function settingsKeep(el){
  el.querySelectorAll("input[data-set], select[data-set], #idleMin, #logDays").forEach(i => {
    const on = () => { settingsDraft[i.id] = i.type === "checkbox" ? i.checked : i.value; };
    i.oninput = on; i.onchange = on;
  });
}

function openSettingsTab(){
  // The name the button that opens it uses, and the one the tab's own first
    // line uses. "Settings" alone competes with a project's settings dialog
    // and with the gear, which is this browser's appearance.
    openTab({kind: "settings", arg: "__settings", label: "Controller settings"});
}

function renderSettingsInto(i){
  const d = docSurface(i, "settings");
  if (!d) return;
  d.setBar(`<span class="dim">controller settings: what this container does,
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
        <div class="sub">The machines work runs on, each set up on its own row.</div>
        <div class="actbar"><button type="button" id="setNodes">Open the Nodes tab</button></div>
      </div>
    </div>`;
  d.setFoot(`a change takes now, or at the next start: each section says which.`);
  wireLogSection(d.el);
  wireIdleSection(d.el);
  wireSettingsSections(d.el);
  settingsKeep(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
}

// The settings that used to be environment variables (roadmap R29): what is
// left of them after the operator asked which needed to exist at all. Each
// group is one section with one Apply, a field that has never been saved
// says so beside it, and the bar says whether a change takes now or at the
// next start. Drawn from the poll's copy, so a save shows on the next poll.
const SETTING_GROUPS = [
  {title: "Debugging", fields: [
    {key: "debug_mode", label: "Debug mode", type: "bool",
     hint: "Shows the controls kept out of the way otherwise: Debug settings "
         + "here, and Debug settings on a node's row, where you grant it the "
         + "nodes whose agent, runner and terminal logs its sessions may read. "
         + "It grants nothing by itself."}],
   // What a developer of BuilderBot reaches for and nobody else should
   // meet: folded behind a Debug settings button that opens only while
   // debug mode is on, the same way the node row's is.
   debug: [
    {key: "claude_shared_login", label: "Let two accounts share one Claude login", type: "bool",
     hint: "For one person testing two accounts. Anthropic's terms allow one person per Claude account."}]},
];
// Whether the Debugging group's fold is open: kept across repaints, since
// the tab redraws on every poll that moves a setting.
let debugSettingsOpen = false;

function settingsSections(){
  const s = state?.settings;
  if (!s) return `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`;
  const src = k => s.settings[k]?.source === "default" ? `<span class="pill">default</span>` : "";
  return SETTING_GROUPS.map(g => {
    const boot = [...g.fields, ...(g.debug || [])].some(f => s.meta[f.key]?.applied === "boot");
    const field = f => {
            const v = s.settings[f.key]?.value;
            const id = "set_" + f.key;
            // A checkbox sits inside its label, the way the Tests bar's do;
            // a choice is a select over the store's own list.
            // A checkbox keeps its sentence beside it; a field or a select
            // has its label above, and what the label cannot say rides the ?
            // (docs/design-language.md, Controls).
            if (f.type === "bool")
              return `<div class="logdays setrow"><label class="ndcap">
                <input id="${id}" type="checkbox" data-set="${f.key}"${sdVal(id, !!v) ? " checked" : ""}> ${esc(f.label)}${helpIcon(f.hint)}</label>${src(f.key)}
              </div>`;
            const choices = s.meta[f.key]?.choices || [];
            const ctl = f.type === "choice"
              ? `<select id="${id}" data-set="${f.key}">${choices.map(c =>
                  `<option value="${esc(c)}"${c === sdVal(id, v) ? " selected" : ""}>${esc(c)}</option>`).join("")}</select>`
              : `<input id="${id}" type="text" data-set="${f.key}" value="${esc(String(sdVal(id, v) ?? ""))}" spellcheck="false" autocomplete="off">`;
            return `<div class="logdays setrow col">
              ${lbl(id, f.label, f.hint)}${ctl}${src(f.key)}
            </div>`;
    };
    // The fold's button is a real control only while debug mode is SAVED
    // on: what is behind it is debug's, and a draft tick that has not been
    // applied yet is not debug mode.
    const debugOn = !!s.settings.debug_mode?.value;
    const fold = !g.debug ? "" : `
          <div class="addbar" data-add="debug"><button type="button" data-debugshow
            aria-expanded="${debugOn && debugSettingsOpen}"${debugOn ? "" : " disabled"}
            title="${debugOn ? "the settings kept behind debug mode"
                             : "turn Debug mode on and Apply first: these are its settings"}"
            >Debug settings</button></div>
          <div class="uadd" data-debugfold${debugOn && debugSettingsOpen ? "" : " hidden"}>
            ${g.debug.map(field).join("")}
          </div>`;
    return `<div class="row stack2" data-group="${esc(g.title)}">
      <div class="grow">
        <h4>${esc(g.title)}</h4>
        <div class="logset">
          ${g.fields.map(field).join("")}${fold}
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
    const show = box.querySelector("[data-debugshow]"), fold = box.querySelector("[data-debugfold]");
    if (show && fold) show.onclick = () => {
      debugSettingsOpen = !debugSettingsOpen;
      show.setAttribute("aria-expanded", String(debugSettingsOpen));
      slideBody(box, () => { fold.hidden = !debugSettingsOpen; });
    };
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
        box.querySelectorAll("[data-set]").forEach(i => { delete settingsDraft[i.id]; });
        const boot = Object.keys(set).some(k => j.meta?.[k]?.applied === "boot");
        notify(boot ? "saved; it takes at the next start" : "saved");
        refresh();
      }catch(e){ notify("settings: " + e, true); }
      finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
    };
    btn.onclick = apply;
    box.querySelectorAll("input[type=text]").forEach(i => {
      i.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
    });
  });
}

// Ending Claude sessions nobody has used for a while. One rule for this
// container and every node, and a node enforces it itself: the value rides
// the agent's hello and lives in its node.json, so it holds while this
// controller is down. That is the point: a node's sessions outlive a
// controller restart on purpose, and the rule about when they end must not.
function idleSection(){
  const m = state?.idle?.minutes;
  if (m === undefined) return `<div class="sub">the idle rule arrives with the first poll…</div>`;
  return `<h4>Claude sessions</h4>
    <div class="logset">
      <div class="dim">A session with nothing typed and nothing written for
        this long is ended, here and on every node.</div>
      <div class="logdays setrow col">
        ${lbl("idleMin", "Minutes idle before a session ends", "0 never ends one. Shells are left alone")}
        <input id="idleMin" type="number" min="0" max="100000" step="1"
               value="${sdVal("idleMin", m)}" inputmode="numeric">
      </div>
      <div class="actbar">
        <span class="state">takes now, and a node hears on its next poll</span>
        <button type="button" id="idleApply" title="save it: a node hears on its next poll">Apply</button>
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
      delete settingsDraft.idleMin;
      notify(j.minutes ? `Claude sessions end after ${j.minutes} idle minute(s), here and on every node`
                       : "Claude sessions are never ended for being idle");
      refresh();
    }catch(e){ notify("idle: " + e, true); }
    finally{ if (btn && btn.isConnected){ btn.disabled = false; btn.textContent = "Apply"; } }
  };
  el.querySelector("#idleApply").onclick = apply;
  inp.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
}
