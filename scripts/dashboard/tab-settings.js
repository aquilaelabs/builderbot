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
    <div class="row stack2" data-group="Reset">
      <div class="grow">
        <div class="name">Reset BuilderBot</div>
        <div class="sub">Start over at Create the owner: accounts, node enrolments, project settings, git tokens, the notebook, memories and logs are moved aside; project files are not touched.</div>
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
  d.setFoot(`a change takes now, or at the next start: each section says which.`);
  wireLogSection(d.el);
  wireIdleSection(d.el);
  wireSettingsSections(d.el);
  const gr = d.el.querySelector("#setGlobalRules");
  if (gr) gr.onclick = openGlobalRules;
  // The count on the section's line, fetched once: it is the only thing here
  // that is not already in the poll.
  if (globalRules === null) loadGlobalRules().then(() => {
    const st = d.el.querySelector("#setGlobalRules")?.closest(".actbar")?.querySelector(".state");
    if (st && globalRules) st.textContent = `${globalRules.length} rule${globalRules.length === 1 ? "" : "s"}`;
  });
  settingsKeep(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = openNodesTab;
  const rs = d.el.querySelector("#setReset");
  if (rs) rs.onclick = () => askReset(d.el);
}

// The settings that used to be environment variables (roadmap R29): what is
// left of them after the operator asked which needed to exist at all. Each
// group is one section with one Apply, a field that has never been saved
// says so beside it, and the bar says whether a change takes now or at the
// next start. Drawn from the poll's copy, so a save shows on the next poll.
const SETTING_GROUPS = [
  // One tree behaves as two products (roadmap R54, step 6): production
  // leaves this off and sees only what has been proven (alpha); a dev
  // instance turns it on and sees everything, the unproven tagged dev.
  {title: "What is offered", fields: [
    {key: "offer_unvetted", label: "Offer dev features", type: "bool",
     hint: "Alpha is what has been run for real; dev is the rest: git hosts, hypervisors "
         + "and node OS families nobody has tried yet. Off, only alpha is offered; on, "
         + "dev appears in the pickers tagged dev, and the header says dev."}]},
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

// The reset's confirmation, the way a project's purge asks: the word typed
// in a box under the button, and the red verb asleep until it matches.
// What it moves aside is said once more here, since the thing a person
// regrets is the thing they did not read.
function askReset(el){
  const box = el.querySelector("#setResetBox");
  if (!box || box.querySelector(".dropbox")) return;
  box.innerHTML = `<div class="dropbox"><div class="hint bad">This moves every account, node
      enrolment, project setting, git token, the notebook, memories and logs into a dated
      directory under the controller's config and starts the dashboard over at Create the
      owner. Project files stay where they are. Type <b>reset</b> to confirm.</div>
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
            <span class="state">takes now</span>
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

// ---- global rules (R63) ------------------------------------------------
//
// The rules that apply to EVERY project, which is why they are here and not
// on a project's Briefing tab: one reaches projects the person setting it may
// not work on, so it is an administrator's. A session may not add one at all
// and is told to say what it would add instead, the way it is told about a
// package it cannot install.
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
        <div class="sub">House rules every project's sessions are handed, kept here rather than copied into each project.</div>
        <div class="actbar">
          <span class="state">${n === null ? "" : `${n} rule${n === 1 ? "" : "s"}`}</span>
          <button type="button" id="setGlobalRules">Global rules</button>
        </div>
      </div>
    </div>`;
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
    return `<div class="rulerow" data-builtin="${esc(r.name)}">
      <label class="lbl"><input type="checkbox" class="grOn"${r.disabled ? "" : " checked"}>
        <b>${esc(r.name)}</b> <span class="dim">ships with BuilderBot</span></label>
      <div class="sub">${esc(r.text)}</div>
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
  const shipped = rs.filter(r => r.builtin);
  const own = rs.filter(r => !r.builtin);
  body.innerHTML = `
    <div class="sub">Every session on every project is handed these. A session cannot add one.</div>
    ${shipped.length ? `<h4>Shipped with BuilderBot</h4>${shipped.map(globalRuleRow).join("")}` : ""}
    <h4>Yours</h4>
    <div id="grOwn">${own.length ? own.map(globalRuleRow).join("") : `<div class="sub">none yet</div>`}</div>
    <div class="actbar">
      <span class="state" id="grState"></span>
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
    const none = own.querySelector(".sub");
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
      const r = await postJSON("/api/global-rules", {action: "save", rules, disabled});
      if (r.error) return notify(r.error, true);
      globalRules = r.rules || [];
      notify("global rules saved: every project's next session is handed them");
      drawGlobalRules();
      refresh();
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
  if (body) body.innerHTML = `<div class="sub">loading…</div>`;
  await loadGlobalRules();
  drawGlobalRules();
}
