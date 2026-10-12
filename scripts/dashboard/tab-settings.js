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

// Revert on a section puts its fields back to what is saved: the draft for
// them dropped and the tab repainted, which the live key has to notice.
let settingsRev = 0;
function settingsLive(){
  return JSON.stringify([state?.settings?.settings, state?.settings?.tunnel, state?.idle, state?.logs, state?.paths, settingsRev]);
}

// Typed and not yet applied, by control id, across the tab's redraws: one
// section's Apply repaints the whole tab from the poll, and must not throw
// away what was typed into another (docs/design-language.md, Settings).
const settingsDraft = {};
const sdVal = (id, value) => settingsDraft[id] ?? value;
function settingsKeep(el){
  el.querySelectorAll("input[data-set], select[data-set], #idleMin, #logDays, input[data-path]").forEach(i => {
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
  // Sections, like every other tab's (the operator, 11 Oct): one fold per
  // group, its status on the heading, a jump bar over them, and each with
  // its own Apply and Revert. The groups' own markup is kept inside (the
  // suites and the keepers address it), the heading taking the h4's place.
  const idle = state?.idle?.minutes;
  const paths = state?.paths?.paths || [];
  const t = state?.settings?.tunnel;
  const dbg = state?.settings?.settings?.debug_mode?.value;
  const sect = (key, title, status, html, opts = {}) =>
    docSection("settings", key, title, status, html.replace(/<h4>[^<]*<\/h4>\s*/, ""), opts);
  const groups = settingsSections();
  d.list.innerHTML = `<div class="sectjump" data-sects></div>
    ${sect("logs", "Logs", "", `<div class="row stack2" data-group="Logs"><div class="grow">${withRevert(logSection(), "logs")
        || `<div class="sub">log settings arrive with the first poll…</div>`}</div></div>`)}
    ${reportsSection() ? sect("reports", "BuilderBot bug reports", "", reportsSection()) : ""}
    ${sect("idle", "Claude sessions", idle === undefined ? "" : idle ? `${idle} min` : "never",
           `<div class="row stack2" data-group="Claude sessions"><div class="grow">${withRevert(idleSection(), "idle")}</div></div>`)}
    ${pathsSection() ? sect("paths", "Storage on this controller", `${paths.length} path${paths.length === 1 ? "" : "s"}`, withRevert(pathsSection(), "paths")) : ""}
    ${groups.map(g => sect(g.key, g.title, g.status, withRevert(g.html, g.key), {cls: g.cls})).join("")}
    ${sect("reset", "Reset BuilderBot", "", `<div class="row stack2" data-group="Reset">
      <div class="grow">
        <div class="sub">Start over at the setup page, un-enrolling the nodes first if you choose. Everything but project files is moved aside, not deleted.</div>
        <div class="actbar"><button type="button" class="danger" id="setReset">Reset BuilderBot</button></div>
      </div>
    </div>`)}
    ${sect("nodes", "Nodes", "", `<div class="row stack2">
      <div class="grow">
        <div class="sub">The machines work runs on, each set up on its own row.</div>
        <div class="actbar"><button type="button" id="setNodes">Open the Nodes tab</button></div>
      </div>
    </div>`)}`;
  d.setFoot(`a change applies at once or at the next start: each section says which. Revert puts a section's fields back to what is saved.`);
  sectJump(d.list.querySelector("[data-sects]"));
  wireSections(d.el);
  d.el.querySelectorAll("[data-srevert]").forEach(b => b.onclick = () => {
    const sec = b.closest("details.sect");
    sec?.querySelectorAll("input, select").forEach(i => { if (i.id) delete settingsDraft[i.id]; });
    settingsRev++;
    drawPanes();
  });
  wireLogSection(d.el);
  wireIdleSection(d.el);
  wirePathsSection(d.el);
  wireSettingsSections(d.el);
  settingsKeep(d.el);
  const nd = d.el.querySelector("#setNodes");
  if (nd) nd.onclick = () => openNodesTab();
  const rs = d.el.querySelector("#setReset");
  if (rs) rs.onclick = () => askReset();
  const rc = d.el.querySelector("#setReportsClear");
  if (rc) rc.onclick = () => clearReports(rc);
}

// What sessions on other projects reported about BuilderBot with bb report,
// which the Diagnostics download under Logs carries. Counted on the press
// rather than on the line: they arrive from sessions at any time, so a count
// fetched when the tab opened would be stale by the time it was read.
// A section's Revert beside its Apply: the first Apply button in the markup
// gets one after it, wearing the section's key.
function withRevert(html, key){
  if (!html) return html;
  const m = html.match(/<button[^>]*(id="(logApply|idleApply|pathsApply)"|class="setApply")[^>]*>Apply<\/button>/);
  if (!m) return html;
  return html.replace(m[0], `${m[0]}<button type="button" class="caution" data-srevert="${esc(key)}" title="put this section's fields back to what is saved">Revert</button>`);
}

function reportsSection(){
  // The debug grant's, and not drawn without it (the operator, 6 Oct).
  if (state?.can?.debug === false) return "";
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
  if (!confirm(`Delete all ${c.all} report${s} sessions made about BuilderBot?`)) return;
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
  // The home tunnel the controller runs itself (R176): the public hostname
  // a node off the LAN dials, the tunnel's token, and an API token that
  // writes the hostname's record and the tunnel's rules rather than having
  // them clicked. The two tokens are secrets: never shown back.
  {key: "tunnel", title: "Public hostname", status: tunnelStatus, intro: tunnelSteps,
   heading: s => !s?.tunnel ? "" : s.tunnel.connected ? "connected" : s.tunnel.configured ? (s.tunnel.running ? "starting" : "stopped") : "off",
   headingCls: s => s?.tunnel?.connected ? "ok" : "",
   fields: [
    {key: "tunnel_host", label: "Hostname", type: "text", placeholder: "bb.example.com",
     hint: "The name a node off your network dials the controller at, published by a tunnel from home. Enroll node fills it in."},
    {key: "tunnel_token", label: "Tunnel token", type: "secret",
     hint: "From Zero Trust: Networks, Tunnels, Create a tunnel (Cloudflared), the long eyJ… string in its install command. The controller runs the tunnel itself with it."},
    {key: "cf_api_token", label: "Cloudflare API token (optional)", type: "secret",
     hint: "With Zone DNS Edit and Account Cloudflare Tunnel Edit: the hostname's record and the tunnel's two rules (the agent's API to the controller, everything else 404) are written on Apply rather than clicked."}]},
  {key: "debug", title: "Debugging", heading: s => s?.settings?.debug_mode?.value ? "on" : "off", fields: [
    {key: "debug_mode", label: "Debug mode", type: "bool",
     hint: "Shows the Debug settings button here, and lets a project's settings grant its "
         + "sessions nodes' logs and the controller's diagnostics. Turning it on grants nothing by itself."}],
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
     hint: "Also offer untested git hosts, hypervisors and node systems, tagged dev in the pickers."}]},
];

// How the public hostname is set up, in the section itself (the operator,
// 11 Oct): the steps in order, with the controller's own port in them.
function tunnelSteps(s){
  const port = s?.tunnel?.port || 7680;
  return `<div class="sub">A name a node off your network dials to reach this controller, carried by a tunnel the controller runs itself. Nothing on your router changes, and the node never learns your address.</div>
    <ol class="setsteps dim">
      <li>In Cloudflare Zero Trust: Networks, Tunnels, Create a tunnel (Cloudflared), named for this controller. Copy the long <code>eyJ…</code> token from its install command into Tunnel token below. Do not run that command: the controller runs the tunnel.</li>
      <li>Pick the hostname, on a domain in your Cloudflare account (<code>bb.example.com</code>), and type it in Hostname.</li>
      <li>Either paste an API token with Zone DNS Edit on that domain and Account Cloudflare Tunnel Edit, and Apply writes the hostname's record and the tunnel's rules; or set them yourself on the tunnel's Public Hostname page: path <code>api/v1/agent/.*</code> to HTTP <code>localhost:${esc(String(port))}</code> (the controller's own port, inside its container), and the bare hostname to HTTP status 404, so the name serves no page.</li>
      <li>Apply. The line below says connected once the tunnel is up; Enroll node then fills the hostname in for a node reaching the controller through it.</li>
    </ol>`;
}

// The tunnel's line on its group's action bar (R176): whether cloudflared
// is here, running, registered, and at which name, as the server reads it.
function tunnelStatus(s){
  const t = s?.tunnel;
  if (!t) return "applies at once";
  if (t.error) return t.error;
  if (!t.installed) return "cloudflared is not in this image: the tunnel cannot run from here";
  if (!t.configured) return "off: paste a tunnel token and Apply to run the home tunnel here";
  if (!t.running) return "starting";
  if (!t.connected) return "running, not registered yet";
  // Registered is not routed (the operator, 11 Oct): the server asks the
  // name itself, and says so when the answer is somebody else's.
  if (t.route?.ok === false) return `connected, but ${t.route.said}`;
  if (t.route?.ok === true) return `connected: ${t.host || "the tunnel"} reaches this controller`;
  return `connected; checking that ${t.host || "the name"} reaches this controller`;
}

// The reset's confirmation, the way a project's purge asks: the word typed
// in a box under the button, and the red verb asleep until it matches.
// What it moves aside is said once more here, since the thing a person
// regrets is the thing they did not read.
// Reset BuilderBot (the operator, 12 Oct): a dialog that offers to
// un-enroll every node first, so each machine is clean to enroll again
// afterwards, then the typed word. The controller uninstalls each and waits
// for every one to report before anything is moved (server._reset_after),
// and this follows it to the end. A node with sessions or containers
// running cannot be ticked: un-enrolling would end them, and that is the
// person's to do first, as on the node's own Un-enroll.
function resetBusy(n){
  const rep = n.reported || {};
  const s = (rep.sessions || []).filter(x => /^u_[0-9a-f]{8}~/.test(String(x?.name || ""))).length;
  const c = Object.keys(rep.published || {}).length;
  return [s ? `${s} session${s === 1 ? "" : "s"} running` : "", c ? `${c} container${c === 1 ? "" : "s"} running` : ""]
    .filter(Boolean).join(" and ");
}

async function askReset(){
  const modal = $("resetmodal"), body = $("resetBody");
  if (!modal || !body) return;
  try { await loadNodes(); } catch {}
  const list = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  const shut = () => { modal.hidden = true; body.innerHTML = ""; };
  body.innerHTML = `<div class="field">
      <div class="hint bad">Accounts, nodes, project settings, tokens, the notebook, memories and logs move into a dated
        directory under the controller's config. Project files stay. The next page is the setup page.</div>
    </div>
    ${list.length ? `<div class="field">
      <label class="lbl">Un-enroll first</label>
      <div class="hint">So each machine can be enrolled again afterwards. One BuilderBot set up is uninstalled from; any other is removed here only.</div>
      ${unenrollWhat(true)}
      ${list.map(n => { const busy = resetBusy(n), clean = !!(n.live && n.reported?.sandbox); return `
        <label class="ndcap"><input type="checkbox" data-rsnode="${esc(n.id)}"${busy ? " disabled" : " checked"}> ${esc(n.name)}: ${
          clean ? "uninstall BuilderBot from it" : "remove it here; the machine keeps BuilderBot until <code>sudo bb-sandbox uninstall</code> there"}${
          busy ? `<div class="hint bad">${esc(busy)}: end and bring them down first, or it stays enrolled</div>` : ""}</label>`; }).join("")}
      <label class="ndcap"><input type="checkbox" id="resetStores"> Also delete the stores on their disks: the toolchains, the caches, the artifacts</label>
    </div>` : ""}
    <div class="field">
      <label class="lbl" for="resetWord">Type reset to confirm</label>
      <input id="resetWord" autocomplete="off" placeholder="reset">
      <div class="hint bad" id="resetWhy" hidden></div>
    </div>
    <div class="foot"><span class="sp"></span>
      <button type="button" id="resetKeep">Keep it</button>
      <button type="button" class="danger" id="resetGo" disabled>Reset</button></div>`;
  modal.hidden = false;
  const word = $("resetWord"), go = $("resetGo"), why = $("resetWhy");
  word.oninput = () => { go.disabled = word.value.trim() !== "reset"; };
  $("resetKeep").onclick = shut;
  const send = async (ids) => {
    busy(go, ids.length ? "Un-enrolling" : "Resetting");
    why.hidden = true;
    let j;
    try{
      j = await (await postJSON("/api/reset", {confirm: word.value.trim(), unenroll: ids,
        stores: !!$("resetStores")?.checked})).json();
    }catch(e){ j = {error: "no answer from the dashboard: " + e}; }
    if (j.error){ unbusy(go, "Reset"); why.textContent = j.error; why.hidden = false; return; }
    if (j.unenrolling) return resetFollow(body, ids, send);
    resetGone(body, j.moved_to);
  };
  go.onclick = () => send([...body.querySelectorAll("[data-rsnode]:checked")].map(i => i.dataset.rsnode));
  word.focus();
}

// The un-enrolling, node by node, until the reset happens or something
// stops it; then Reset anyway, which leaves the rest enrolled.
function resetFollow(body, ids, send){
  const draw = j => {
    body.innerHTML = `<div class="field">
        <div class="hint">Un-enrolling, then the reset. A machine reports its uninstall when it is done; this can take a few minutes.</div>
        ${(j.nodes || []).map(x => `<div class="ndcap">${esc(x.name)}: ${
          x.error ? `<span class="bad">${esc(x.error)}</span>` : x.done ? "done" : x.how === "uninstall" ? "uninstalling…" : "removing…"}</div>`).join("")}
        <div class="hint bad" id="resetWhy"${j.error ? "" : " hidden"}>${esc(j.error || "")}</div>
      </div>
      <div class="foot"><span class="sp"></span>${j.error ? `
        <button type="button" id="resetShut">Close</button>
        <button type="button" class="danger" id="resetAnyway">Reset anyway</button>` : ""}</div>`;
    if (j.error){
      $("resetShut").onclick = () => { $("resetmodal").hidden = true; body.innerHTML = ""; };
      $("resetAnyway").onclick = async () => {
        let r;
        try{ r = await (await postJSON("/api/reset", {confirm: "reset"})).json(); }
        catch(e){ r = {error: "no answer from the dashboard: " + e}; }
        if (r.error){ $("resetWhy").textContent = r.error; $("resetWhy").hidden = false; return; }
        resetGone(body, r.moved_to);
      };
    }
  };
  const tick = async () => {
    let j;
    try{ j = await (await fetch("/api/reset")).json(); }
    catch{ return resetGone(body, ""); }       // the controller is starting over
    draw(j);
    if (j.moved_to) return resetGone(body, j.moved_to);
    if (j.running) setTimeout(tick, 3000);
  };
  tick();
}

function resetGone(body, moved){
  body.innerHTML = `<div class="field"><div class="hint">Reset: the dashboard is starting over${
    moved ? `; the old state is in ${esc(moved)}` : ""}. The setup page follows.</div></div>`;
  setTimeout(() => { location.href = "/login"; }, 2500);
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
  if (!s) return [{key: "wait", title: "Settings", status: "", html: `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`}];
  const src = k => s.settings[k]?.source === "default" ? `<span class="pill">default</span>` : "";
  // The Debugging group is the debug grant's (roles.NAMED_ONLY): without it
  // the page does not show it at all (the operator, 6 Oct).
  return SETTING_GROUPS.filter(g => !g.debug || state?.can?.debug !== false).map(g => {
    const field = f => {
            const v = s.settings[f.key]?.value;
            const id = "set_" + f.key;
            // A text is a field with its label over it; a secret the same,
            // typed blind, with "set" said beside it and never its value:
            // left empty it is left alone, and its own tick takes it off.
            if (f.type === "text" || f.type === "secret"){
              const isSet = f.type === "secret" ? !!s.settings[f.key]?.set : !!v;
              return `<div class="setrow col"><label for="${id}">${esc(f.label)}${helpIcon(f.hint)}${
                  f.type === "secret" ? (isSet ? ` <span class="pill ok">set</span>` : ` <span class="pill">not set</span>`) : src(f.key)}</label>
                <input id="${id}" type="${f.type === "secret" ? "password" : "text"}" data-set="${f.key}"${
                  f.type === "secret" ? ' data-secret="1"' : ""} value="${esc(f.type === "secret" ? "" : sdVal(id, v || ""))}"
                  placeholder="${esc(f.type === "secret" ? (isSet ? "set: paste a new one to replace it" : "paste it") : (f.placeholder || ""))}"
                  autocomplete="off" spellcheck="false">${
                  f.type === "secret" && isSet ? `<label class="ndcap"><input type="checkbox" data-clear="${f.key}"> take it off</label>` : ""}
              </div>`;
            }
            // Every other setting is a switch: a checkbox inside its label,
            // the way the Tests bar's are, with what the label cannot say on
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
    return {key: g.key, title: g.title, status: g.heading ? g.heading(s) : "", cls: g.headingCls ? g.headingCls(s) : "",
      html: `<div class="row stack2" data-group="${esc(g.title)}">
      <div class="grow">
        <div class="logset">
          ${g.intro ? g.intro(s) : ""}
          ${g.fields.map(field).join("")}${fold}
          <div class="actbar">
            <span class="state">${g.status ? g.status(s) : "applies at once"}</span>
            <button type="button" class="setApply" title="save">Apply</button>
          </div>
        </div>
      </div>
    </div>`};
  });
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
        // A secret left empty is left as it is; its tick takes it off.
        if (i.dataset.secret && !i.value.trim()) return;
        set[i.dataset.set] = i.type === "checkbox" ? i.checked : i.value.trim();
      });
      box.querySelectorAll("[data-clear]:checked").forEach(i => { set[i.dataset.clear] = ""; });
      busy(btn, "Applying");
      try{
        const r = await fetch("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: JSON.stringify({set})});
        const j = await r.json();
        if (j.error) return notify(j.error, true);
        box.querySelectorAll("[data-set]").forEach(i => { delete settingsDraft[i.id]; });
        // What the tunnel did with it (R176): the record and rules written,
        // or why not, said here rather than only on the next poll's line.
        if (j.published?.error) notify(`saved; Cloudflare: ${j.published.error}`, true);
        else if (j.published?.did) notify(`saved; Cloudflare: ${j.published.did.join("; ")}`);
        else if (j.tunnel?.error) notify(`saved; the tunnel: ${j.tunnel.error}`, true);
        else notify("saved");
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
  // What 0 means is in the label, where a phone reads it (B459).
  return `<h4>Claude sessions</h4>
    <div class="logset">
      <div class="dim">A session idle this long is ended, on every node.</div>
      <div class="logdays setrow col">
        ${lbl("idleMin", "Minutes idle before a session ends (0: never)", "shells are left alone")}
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

// Where the controller keeps what grows (paths.py): each kind on its own line,
// the path in use, and a move in flight or the last one's error. Applying a
// path moves what is there and switches once it has all arrived. The JSON
// records, the database, the signing keys and the git credentials stay in
// /config whatever is set here, and the section says so. An administrator's:
// the poll carries nothing for anybody else, and the section is absent.
function pathsSection(){
  const list = state?.paths?.paths;
  if (!list) return "";
  const line = p => {
    const id = "path_" + p.name;
    const note = p.pinned ? `<div class="dim">${esc(p.pinned)}</div>`
      : p.moving?.error ? `<div class="sub bad">moving to ${esc(p.moving.to)} stopped: ${esc(p.moving.error)}</div>`
      : p.moving ? `<div class="dim">moving to ${esc(p.moving.to)}; ${esc(p.path)} is in use until it is done</div>`
      : !p.set ? "" : `<div class="dim">default: ${esc(p.default)}</div>`;
    return `<div class="logdays setrow col">
        ${lbl(id, p.name, p.what)}
        <input id="${id}" type="text" data-path="${esc(p.name)}" spellcheck="false" autocomplete="off"
               value="${esc(sdVal(id, p.path))}"${p.pinned || (p.moving && !p.moving.error) ? " disabled" : ""}>
        ${note}
      </div>`;
  };
  return `<div class="row stack2" data-group="Storage">
      <div class="grow">
        <h4>Storage on this controller</h4>
        <div class="logset">
          <div class="dim">Where what grows is kept. A new path must be empty or new; what is there is moved across.
            The records, the database, the signing keys and the git credentials stay in the state directory.</div>
          ${list.map(line).join("")}
          <div class="actbar">
            <span class="state">applies once what is there has moved</span>
            <button type="button" id="pathsApply" title="move each changed one to its new path">Apply</button>
          </div>
        </div>
      </div>
    </div>`;
}

function wirePathsSection(el){
  const btn = el.querySelector("#pathsApply");
  if (!btn) return;
  const apply = async () => {
    const list = state?.paths?.paths || [];
    const changed = [...el.querySelectorAll("input[data-path]")]
      .filter(i => !i.disabled && i.value.trim() !== (list.find(p => p.name === i.dataset.path)?.path || ""));
    if (!changed.length) return notify("nothing changed");
    busy(btn, "Applying");
    try{
      for (const i of changed){
        const r = await fetch("/api/paths", {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name: i.dataset.path, path: i.value.trim()})});
        const j = await r.json();
        if (j.error) return notify(`${i.dataset.path}: ${j.error}`, true);
        delete settingsDraft[i.id];
        notify(j.moving ? `${i.dataset.path}: moving what is there; it switches once it has arrived`
                        : `${i.dataset.path} is kept at ${i.value.trim() || "its default"}`);
      }
      refresh();
    }catch(e){ notify("storage: " + e, true); }
    finally{ if (btn.isConnected) unbusy(btn, "Apply"); }
  };
  btn.onclick = apply;
  el.querySelectorAll("input[data-path]").forEach(i => {
    i.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); apply(); } };
  });
}

// The global rules (R63) are not on this tab: every project's notebook lists
// them under its own rules on the Briefing, with a switch for that project,
// and an administrator changes them there for every project (nb-rules.js).
