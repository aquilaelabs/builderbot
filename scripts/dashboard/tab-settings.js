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

"use strict";

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
  d.setBar(`<span class="dim">what this controller does; appearance is in the gear</span>`);
  d.list.innerHTML = `
    <div class="row stack2">
      <div class="grow">${logSection()
        || `<div class="sub">log settings arrive with the first poll…</div>`}</div>
    </div>
    ${reportsSection()}
    <div class="row stack2">
      <div class="grow">${idleSection()}</div>
    </div>
    ${settingsSections()}
    <div class="row stack2" data-group="Reset">
      <div class="grow">
        <div class="name">Reset BuilderBot</div>
        <div class="sub">Start over at Create the owner. Everything but project files is moved aside, not deleted.</div>
        <div class="actbar"><button type="button" class="danger" id="setReset">Reset BuilderBot</button></div>
        <div id="setResetBox"></div>
      </div>
    </div>
    <div class="row stack2">
      <div class="grow">
        <div class="name">Nodes</div>
        <div class="sub">The machines work runs on, each set up on its own row.</div>
        <div class="actbar"><button type="button" id="setNodes">Open the Nodes tab</button></div>
      </div>
    </div>`;
  d.setFoot(`a change applies at once or at the next start: each section says which.`);
  wireLogSection(d.el);
  wireIdleSection(d.el);
  wireSettingsSections(d.el);
  settingsKeep(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
  const rs = d.el.querySelector("#setReset");
  if (rs) rs.onclick = () => askReset(d.el);
  const rc = d.el.querySelector("#setReportsClear");
  if (rc) rc.onclick = () => clearReports(rc);
}

// What sessions on other projects reported about BuilderBot with bb report,
// which the Diagnostics download under Logs carries. Counted on the press
// rather than on the line: they arrive from sessions at any time, so a count
// fetched when the tab opened would be stale by the time it was read.
function reportsSection(){
  return `<div class="row stack2">
      <div class="grow">
        <div class="name">BuilderBot bug reports</div>
        <div class="sub">What sessions reported about BuilderBot with bb report. The Diagnostics download under Logs carries them.</div>
        <div class="actbar"><button type="button" class="danger" id="setReportsClear">Clear reports</button></div>
      </div>
    </div>`;
}

async function clearReports(btn){
  let c;
  try{
    c = await (await postJSON("/api/reports", {action: "count"})).json();
  }catch{ return notify("could not count the reports", true); }
  if (c.error) return notify(c.error, true);
  if (!c.all) return notify("there are no reports to clear");
  const s = c.all === 1 ? "" : "s";
  if (!confirm(`Delete all ${c.all} report${s} sessions made about BuilderBot?`
               + (c.open ? `\n\n${c.open} still open: nobody has filed or closed ${c.open === 1 ? "it" : "them"}.` : "")))
    return;
  busy(btn, "Clearing");
  try{
    const j = await (await postJSON("/api/reports", {action: "clear"})).json();
    if (j.error) notify(j.error, true);
    else notify(`cleared ${j.cleared} report${j.cleared === 1 ? "" : "s"}`);
  }catch{ notify("could not clear the reports", true); }
  unbusy(btn, "Clear reports");
}

// The settings that used to be environment variables (roadmap R29): what is
// left of them after the operator asked which needed to exist at all. Each
// group is one section with one Apply, a field that has never been saved
// says so beside it, and the bar says whether a change applies at once or at the
// next start. Drawn from the poll's copy, so a save shows on the next poll.
const SETTING_GROUPS = [
  {title: "Debugging", fields: [
    {key: "debug_mode", label: "Debug mode", type: "bool",
     hint: "Shows the Debug settings buttons here and on each node. "
         + "Turning it on grants nothing by itself."}],
   // What a developer of BuilderBot reaches for and nobody else should
   // meet: behind a Debug settings button that opens a dialog while debug
   // mode is on, the same way the node row's Debug settings does.
   debug: [
    // One tree behaves as two products (roadmap R54, step 6): production
    // leaves this off and sees only what has been proven (alpha); a dev
    // instance turns it on and sees everything, the unproven tagged dev.
    // In the debug dialog rather than a group of its own: it is a switch a
    // developer of BuilderBot reaches for, and a group headed by one switch
    // read as a feature of the product rather than of its testing.
    {key: "offer_unvetted", label: "Offer dev features", type: "bool",
     hint: "Also offer untested git hosts, hypervisors and node systems, tagged dev in the pickers."},
    {key: "claude_autoupdate", label: "Update Claude Code before a session starts", type: "bool",
     hint: "Before a session starts on a node that is behind, Claude Code is updated there first. "
         + "An open conversation is never ended for it."}]},
];

// The reset's confirmation, the way a project's purge asks: the word typed
// in a box under the button, and the red verb asleep until it matches.
// What it moves aside is said once more here, since the thing a person
// regrets is the thing they did not read.
function askReset(el){
  const box = el.querySelector("#setResetBox");
  if (!box || box.querySelector(".dropbox")) return;
  box.innerHTML = `<div class="dropbox"><div class="hint bad">Accounts, nodes, project settings, tokens, the notebook, memories and logs move into a dated
      directory under the controller's config. Project files stay. Type <b>reset</b> to confirm.</div>
    <input autocomplete="off" placeholder="reset" aria-label="type reset to confirm">
    <div class="foot"><span class="sp"></span>
      <button type="button" class="stop">Keep it</button>
      <button type="button" class="danger" disabled>Reset for real</button></div></div>`;
  const input = box.querySelector("input"), go = box.querySelector(".danger");
  input.oninput = () => { go.disabled = input.value.trim() !== "reset"; };
  box.querySelector(".stop").onclick = () => { box.innerHTML = ""; };
  go.onclick = async () => {
    busy(go, "Resetting");
    try{
      const r = await fetch("/api/reset", {method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({confirm: input.value.trim()})});
      const j = await r.json();
      if (j.error){ notify(j.error, true); unbusy(go, "Reset for real"); return; }
      notify("reset: the dashboard is starting over; the old state is in " + j.moved_to);
      setTimeout(() => { location.href = "/login"; }, 2500);
    }catch(e){ notify("the reset: " + e, true); unbusy(go, "Reset for real"); }
  };
  input.focus();
}

// The Debugging group's other half, in a dialog rather than a fold in the
// group. Two reasons, and the first is the one that was wrong rather than
// merely inconsistent: the fold's fields sat inside the group, so the
// group's Apply saved them, and a person who ticked one and pressed the
// Apply they could see had saved a debug setting without meeting a word
// about it. The second is that the node row's Debug settings is a dialog,
// and these are one idea in two places.
function openDebugSettings(){
  const modal = $("setdbgmodal"), body = $("setdbgBody");
  const g = SETTING_GROUPS.find(x => x.debug);
  if (!modal || !body || !g) return;
  const s = state?.settings;
  const shut = () => { modal.hidden = true; };
  body.innerHTML = `<div class="field">
      <div class="hint">For developing BuilderBot itself. Nothing here is on until saved.</div>
      <div class="logset">${g.debug.map(f => `
        <div class="logdays setrow"><label class="ndcap">
          <input type="checkbox" data-dbgset="${esc(f.key)}"${
            s?.settings?.[f.key]?.value ? " checked" : ""}> ${esc(f.label)}${
            helpIcon(f.hint)}</label></div>`).join("")}
      </div>
    </div>
    <div class="foot"><span class="sp"></span>
      <button type="button" class="primary" id="setdbgSave">Save</button>
      <button type="button" id="setdbgCancel">Cancel</button>
    </div>`;
  modal.hidden = false;
  body.querySelector("#setdbgCancel").onclick = shut;
  const go = body.querySelector("#setdbgSave");
  go.onclick = async () => {
    const set = {};
    body.querySelectorAll("[data-dbgset]").forEach(i => { set[i.dataset.dbgset] = i.checked; });
    busy(go, "Saving");
    try{
      const r = await fetch("/api/settings", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({set})});
      const j = await r.json();
      if (j.error){ notify(j.error, true); unbusy(go, "Save"); return; }
      shut();
      notify("saved");
      refresh();
    }catch(e){ notify("settings: " + e, true); unbusy(go, "Save"); }
  };
}

function settingsSections(){
  const s = state?.settings;
  if (!s) return `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`;
  const src = k => s.settings[k]?.source === "default" ? `<span class="pill">default</span>` : "";
  return SETTING_GROUPS.map(g => {
    const field = f => {
            const v = s.settings[f.key]?.value;
            const id = "set_" + f.key;
            // Every setting is a switch: a checkbox inside its label, the
            // way the Tests bar's are, with what the label cannot say on
            // the ? (docs/design-language.md, Controls).
            return `<div class="logdays setrow"><label class="ndcap">
                <input id="${id}" type="checkbox" data-set="${f.key}"${sdVal(id, !!v) ? " checked" : ""}> ${esc(f.label)}${helpIcon(f.hint)}</label>${src(f.key)}
              </div>`;
    };
    // The button is a real control only while debug mode is SAVED on: what
    // is behind it is debug's, and a draft tick that has not been applied
    // yet is not debug mode.
    const debugOn = !!s.settings.debug_mode?.value;
    const fold = !g.debug ? "" : `
          <div class="addbar" data-add="debug"><button type="button" data-debugshow
            ${debugOn ? "" : " disabled"}
            title="${debugOn ? "the settings kept behind debug mode"
                             : "turn Debug mode on and Apply first: these are its settings"}"
            >Debug settings</button></div>`;
    return `<div class="row stack2" data-group="${esc(g.title)}">
      <div class="grow">
        <h4>${esc(g.title)}</h4>
        <div class="logset">
          ${g.fields.map(field).join("")}${fold}
          <div class="actbar">
            <span class="state">applies at once</span>
            <button type="button" class="setApply" title="save">Apply</button>
          </div>
        </div>
      </div>
    </div>`;
  }).join("");
}

function wireSettingsSections(el){
  el.querySelectorAll('[data-group]').forEach(box => {
    const show = box.querySelector("[data-debugshow]");
    if (show) show.onclick = () => openDebugSettings();
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
        notify("saved");
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
      <div class="dim">A session idle this long is ended, on every node.</div>
      <div class="logdays setrow col">
        ${lbl("idleMin", "Minutes idle before a session ends", "0 never ends one. Shells are left alone")}
        <input id="idleMin" type="number" min="0" max="100000" step="1"
               value="${sdVal("idleMin", m)}" inputmode="numeric">
      </div>
      <div class="actbar">
        <span class="state">applies at once; a node hears on its next poll</span>
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

// The global rules (R63) are not on this tab: every project's notebook lists
// them under its own rules on the Briefing, with a switch for that project,
// and an administrator changes them there for every project (nb-rules.js).
