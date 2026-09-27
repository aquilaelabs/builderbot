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
    ${globalRulesSection()}
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
  const gr = d.el.querySelector("#setGlobalRules");
  if (gr) gr.onclick = openGlobalRules;
  // The count on the section's line, fetched once: it is the only thing here
  // that is not already in the poll.
  if (globalRules === null) loadGlobalRules().then(paintGlobalRulesCount);
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
    {key: "claude_shared_login", label: "Let two accounts share one Claude login", type: "bool",
     hint: "For one person testing two accounts. Anthropic's terms allow one person per Claude account."},
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

// ---- global rules (R63) ------------------------------------------------
//
// The rules that apply to EVERY project, which is why they are here and not
// on a project's Briefing tab: one reaches projects the person setting it may
// not work on, so it is an administrator's. A session may not add one at all
// and is told to say what it would add instead, the way it is told about a
// toolchain it cannot install.
//
// The shipped ones are read-only. An edit would be undone by the next image,
// and a change nobody can see reverted is worse than no change, so the only
// thing that can be done to one is turn it off. That rides the same Save as
// the rest: nothing here takes effect until it is pressed.
let globalRules = null;

function globalRulesSection(){
  const n = globalRules ? globalRules.length : null;
  return `<div class="row stack2">
      <div class="grow">
        <div class="name">Global rules</div>
        <div class="sub">House rules every project's sessions are handed.</div>
        <div class="actbar">
          <span class="state">${n === null ? "" : `${n} rule${n === 1 ? "" : "s"}`}</span>
          <button type="button" id="setGlobalRules">Global rules</button>
        </div>
      </div>
    </div>`;
}

// The count on the section's line. Painted rather than left to the next
// repaint: saving one rule and still reading "0 rules" is the sort of thing a
// person notices, and the tab does not re-render on its own for this.
function paintGlobalRulesCount(){
  const st = document.querySelector("#setGlobalRules")?.closest(".actbar")?.querySelector(".state");
  if (st && globalRules) st.textContent = `${globalRules.length} rule${globalRules.length === 1 ? "" : "s"}`;
}

async function loadGlobalRules(){
  try{
    const r = await (await fetch("/api/global-rules")).json();
    globalRules = Array.isArray(r.rules) ? r.rules : [];
  }catch{ globalRules = []; }
  return globalRules;
}

function globalRuleRow(r, i){
  const id = `gr${i}`;
  if (r.builtin) {
    // A switch in its label, the way every setting on the Settings tab is
    // (design language, Controls), with the rule's words under it.
    return `<div class="rulerow" data-builtin="${esc(r.name)}">
      <div class="logdays setrow"><label class="ndcap">
        <input type="checkbox" class="grOn"${r.disabled ? "" : " checked"}> <b>${esc(r.name)}</b></label></div>
      <div class="hint">${esc(r.text)}</div>
    </div>`;
  }
  return `<div class="rulerow" data-own="1">
      <label class="lbl">Name<input class="grName" value="${esc(r.name || "")}" placeholder="short-name"></label>
      <label class="lbl">The rule<textarea class="grText" rows="3">${esc(r.text || "")}</textarea></label>
      <label class="lbl">Files it covers<input class="grPaths" value="${esc((r.paths || []).join(", "))}" placeholder="scripts/agent, docs"></label>
      <label class="lbl">Words that raise it<input class="grWords" value="${esc((r.words || []).join(", "))}" placeholder="agent, protocol"></label>
      <div class="actbar"><button type="button" class="danger grDrop" data-i="${id}">Remove</button></div>
    </div>`;
}

function drawGlobalRules(){
  const body = document.getElementById("grBody");
  if (!body) return;
  const rs = globalRules || [];
  // A fixed shipped rule (rules.py BUILTIN) has no switch and is not listed:
  // there is nothing here to decide about it.
  const shipped = rs.filter(r => r.builtin && !r.fixed);
  const own = rs.filter(r => !r.builtin);
  // Each part in a .field, where every other dialog's inset lives, and the
  // buttons in the dialog's .foot: this one drew flush against the box.
  body.innerHTML = `
    <div class="field"><div class="hint">Every session on every project is handed these. A session cannot add one.</div></div>
    ${shipped.length ? `<div class="field"><label>Shipped with BuilderBot</label>${shipped.map(globalRuleRow).join("")}</div>` : ""}
    <div class="field"><label>Yours</label>
      <div id="grOwn">${own.length ? own.map(globalRuleRow).join("") : `<div class="hint">none yet</div>`}</div></div>
    <div class="foot">
      <span class="state" id="grState"></span><span class="sp"></span>
      <button type="button" id="grAdd">Add a rule</button>
      <button type="button" id="grSave">Save</button>
      <button type="button" id="grClose">Close</button>
    </div>`;
  wireGlobalRules();
}

function wireGlobalRules(){
  const body = document.getElementById("grBody");
  const modal = document.getElementById("grmodal");
  if (!body || !modal) return;
  body.querySelectorAll(".grDrop").forEach(b => {
    b.onclick = () => { b.closest(".rulerow").remove(); };
  });
  const add = body.querySelector("#grAdd");
  if (add) add.onclick = () => {
    const own = body.querySelector("#grOwn");
    const none = own.querySelector(".hint");
    if (none) none.remove();
    own.insertAdjacentHTML("beforeend", globalRuleRow({}, Date.now()));
    wireGlobalRules();
  };
  const close = body.querySelector("#grClose");
  if (close) close.onclick = () => { modal.hidden = true; };
  const save = body.querySelector("#grSave");
  if (save) save.onclick = async () => {
    const rules = [...body.querySelectorAll('.rulerow[data-own="1"]')].map(row => ({
      name: row.querySelector(".grName").value.trim(),
      text: row.querySelector(".grText").value.trim(),
      paths: row.querySelector(".grPaths").value,
      words: row.querySelector(".grWords").value,
    })).filter(r => r.text);
    const disabled = [...body.querySelectorAll(".rulerow[data-builtin]")]
      .filter(row => !row.querySelector(".grOn").checked)
      .map(row => row.dataset.builtin);
    busy(save, "Saving");
    try{
      // postJSON hands back the Response, not the body: read it, or an error
      // is never seen and the redraw below empties the list it just saved.
      const r = await (await postJSON("/api/global-rules", {action: "save", rules, disabled})).json();
      if (r.error) return notify(r.error, true);
      globalRules = r.rules || [];
      notify("global rules saved: every project's next session is handed them");
      drawGlobalRules();
      paintGlobalRulesCount();
    }catch(e){ notify("global rules: " + e, true); }
    finally{ if (save.isConnected) unbusy(save, "Save"); }
  };
}

async function openGlobalRules(){
  const modal = document.getElementById("grmodal");
  if (!modal) return;
  modal.hidden = false;
  // The backdrop closes it, like every other dialog on the page.
  modal.onclick = e => { if (e.target === modal) modal.hidden = true; };
  const body = document.getElementById("grBody");
  if (body) body.innerHTML = `<div class="loading">loading…</div>`;
  await loadGlobalRules();
  drawGlobalRules();
}
