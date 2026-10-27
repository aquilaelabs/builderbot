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
  return JSON.stringify([state?.settings?.settings, state?.settings?.tunnel, state?.idle, state?.logs, state?.paths, settingsRev, devAppsRev]);
}

// Typed and not yet applied, by control id, across the tab's redraws: one
// section's Apply repaints the whole tab from the poll, and must not throw
// away what was typed into another (docs/design-language.md, Settings).
const settingsDraft = {};
const sdVal = (id, value) => settingsDraft[id] ?? value;
// Each field's saved value, read when it is drawn with no draft over it,
// so an edit back to it is no change and its section's Apply and Revert
// sleep again (R218 step 32, as Profile's do).
const settingsSaved = {};
const SETTINGS_FIELDS = "input[data-set], select[data-set], #idleMin, #logDays, input[data-path]";
function settingsKeep(el){
  const val = i => i.type === "checkbox" ? i.checked : i.value;
  el.querySelectorAll(SETTINGS_FIELDS).forEach(i => {
    if (!(i.id in settingsDraft)) settingsSaved[i.id] = val(i);
    const on = () => {
      const v = val(i);
      if (i.id in settingsSaved && v === settingsSaved[i.id]) delete settingsDraft[i.id];
      else settingsDraft[i.id] = v;
      settingsWake(el);
    };
    i.oninput = on; i.onchange = on;
  });
  el.querySelectorAll("[data-clear]").forEach(i => { i.addEventListener("change", () => settingsWake(el)); });
  settingsWake(el);
}
// A section's Apply and Revert awake only while one of its fields differs
// from what is saved, or a stored secret is ticked to go: the Logs section's
// too (the operator, 26 Oct: every save bar asleep with nothing to save).
function settingsWake(el){
  el.querySelectorAll("details.sect").forEach(sec => {
    const dirty = [...sec.querySelectorAll(SETTINGS_FIELDS)].some(i => i.id in settingsDraft)
      || !!sec.querySelector("[data-clear]:checked");
    sec.querySelectorAll(".setApply, #logApply, #idleApply, #pathsApply, [data-srevert]").forEach(b => {
      if (!b.dataset.busy && b.disabled !== !dirty) b.disabled = !dirty;
    });
  });
}

function openSettingsTab(){
  // The name the button that opens it uses, and the one the tab's own first
    // line uses. "Settings" alone competes with a project's settings dialog
    // and with the gear, which is this browser's appearance.
    openTab({kind: "settings", arg: "__settings", label: "Controller settings"});
}

// Each section's line on the list beside it: what is in it.
const SETTINGS_SAYS = {
  logs: "days kept, following, downloads", reports: "what was reported about BuilderBot, and the diagnostics",
  idle: "when an idle session is ended", paths: "the shares and disks this controller uses",
  tunnel: "a hostname that reaches it from outside",
  apps: "the apps your people install, kept current",
  reset: "start over at the setup page",
};

function renderSettingsInto(i){
  const d = docSurface(i, "settings");
  if (!d) return;
  // The build and the uptime live here now (R218 step 2, the top-bar rule):
  // facts in the facts voice, where the header carried them before.
  // ...and no sentence about the page beside them (the operator, 18 Oct).
  // The controller's build and how long it has been up, as a node's head
  // says what a machine is (the operator, 25 Oct: no loose words at the top).
  d.setBar("");
  const img = state?.image || {};
  const head = pageHead({title: "This controller", facts: [
    ["Version", img.version || "unstamped"],
    ["Commit", (img.rev || "").slice(0, 7)],
    ["Up", shortUptime(state?.uptime || 0)]]});
  // Sections, like every other tab's (the operator, 11 Oct): one fold per
  // group, its status on the heading, a jump bar over them, and each with
  // its own Apply and Revert. The groups' own markup is kept inside (the
  // suites and the keepers address it), the heading taking the h4's place.
  const idle = state?.idle?.minutes;
  const paths = state?.paths?.paths || [];
  const t = state?.settings?.tunnel;
  const sect = (key, title, status, html, opts = {}) =>
    docSection("settings", key, title, status, html.replace(/<h4>[^<]*<\/h4>\s*/, ""), opts);
  const groups = settingsSections();
  // The logs are an administrator's: a poll that has landed without them
  // means this account has no Logs section, not one still on its way (B38).
  const logs = logSection();
  d.list.innerHTML = `${head}<div class="sectjump" data-sects></div>
    ${logs || !state ? sect("logs", "Logs", "", `<div class="row stack2" data-group="Logs"><div class="grow">${withRevert(logs, "logs")
        || `<div class="sub">log settings arrive with the first poll…</div>`}</div></div>`) : ""}
    ${sect("reports", "BuilderBot bug reports", reportsCount() === null ? "" : reportsCount() ? `${reportsCount()} report${reportsCount() === 1 ? "" : "s"}` : "none", reportsSection())}
    ${sect("idle", "Idle sessions", idle === undefined ? "" : idle ? `${idle} min` : "never",
           `<div class="row stack2" data-group="Idle sessions"><div class="grow">${withRevert(idleSection(), "idle")}</div></div>`)}
    ${pathsSection() ? sect("paths", "Storage on this controller", `${paths.length} path${paths.length === 1 ? "" : "s"}`, withRevert(pathsSection(), "paths")) : ""}
    ${groups.map(g => sect(g.key, g.title, g.status, withRevert(g.html, g.key), {cls: g.cls})).join("")}
    ${
    // Last, apart from the settings (R218 step 32); the Nodes section that
    // only linked to the Nodes page is gone with it, the rail being the way.
    sect("reset", "Reset BuilderBot", "", `<div class="field" data-group="Reset">
      <div class="hint">Start over at the setup page, un-enrolling the nodes first if you choose. Everything but project files is moved aside, not deleted.</div>
      <div class="actbar"><span class="sp"></span><button type="button" class="danger" id="setReset">Reset BuilderBot</button></div>
    </div>`)}`;
  sectJump(d.list.querySelector("[data-sects]"));
  wireSections(d.el);
  // A page of settings (page-docs.js splitSects): the sections a list beside
  // the one picked, as a project's Settings are.
  splitSects(d.list, "settings", {says: SETTINGS_SAYS, back: "Controller settings"});
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
  if (reportsList === null) loadReports();
  const ac = d.el.querySelector("#setAppsCheck");
  if (ac) ac.onclick = async () => {
    busy(ac, "Looking");
    try{
      const j = await (await postJSON("/api/apps", {action: "check"})).json();
      if (j.error) notify(j.error, true);
    }catch(e){ notify("could not reach the controller: " + failWords(e), true); }
    // The look runs in the background; read again once it has had a moment.
    setTimeout(loadApps, 4000);
    await loadApps();
  };
  const rs = d.el.querySelector("#setReset");
  if (rs) rs.onclick = () => askReset();
  d.el.querySelectorAll("[data-repdel]").forEach(b => b.onclick = () => deleteReport(b));
  const rc = d.el.querySelector("#setReportsClear");
  if (rc) rc.onclick = () => clearReports(rc);
}

// A section's Revert beside its Apply: the first Apply button in the markup
// gets one after it, wearing the section's key.
function withRevert(html, key){
  if (!html) return html;
  const m = html.match(/<button[^>]*(id="(logApply|idleApply|pathsApply)"|class="setApply")[^>]*>Apply<\/button>/);
  if (!m) return html;
  return html.replace(m[0], `${m[0]}<button type="button" class="caution" data-srevert="${esc(key)}" title="put this section's fields back to what is saved">Revert</button>`);
}

// What sessions and people reported about BuilderBot (bb report, the
// header's Report a bug), every one listed with its delete, and the
// diagnostics download under them, which carries what is left (the
// operator, 26 Oct): a report taken out before the download is not in it.
// Whoever reads Controller settings reads them; only a session reading them
// is debug's. Read when the page draws it and after a delete, not on the poll.
let reportsList = null;
async function loadReports(){
  try{
    const j = await (await postJSON("/api/reports", {action: "list"})).json();
    if (j.error) return;
    reportsList = j.reports || [];
  }catch{ return; }
  settingsRev++;
  drawPanes();
}
const reportsCount = () => reportsList === null ? null : reportsList.length;
function reportsSection(){
  const rows = reportsList || [];
  const mayDelete = state?.can?.controller !== false;
  const list = reportsList === null ? `<div class="row stack2"><div class="grow"><div class="sub dim">reading the reports…</div></div></div>`
    : !rows.length ? `<div class="empty">No reports. A session's <code>bb report</code> and Report a bug in the header land here.</div>`
    : rows.map(r => `<div class="row repline" data-report="${r.id}"><div class="grow">
        <div class="name">#${r.id} ${esc(r.project || "no project")}<span class="dim"> · ${esc(ago(r.at))} · ${esc(r.by || "")}${r.area ? ` · ${esc(r.area)}` : ""}</span></div>
        <div class="sub reptext">${esc(r.text || "")}</div></div>
        ${mayDelete ? rmIcon(`data-repdel="${r.id}"`, `Delete report ${r.id}`, {title: "take it out: it is not in the diagnostics downloaded after"}) : ""}
      </div>`).join("");
  return `<div class="field"><div class="hint">What sessions and people reported about BuilderBot. Delete any you do not want in the diagnostics before downloading them.</div></div>
    <div class="replist">${list}</div>
    <div class="field"><div class="actbar"><span class="sp"></span>
      <a class="btnish" href="/logs/download?what=diag" download title="the controller's diagnostics as one file, with the reports listed here">Download diagnostics</a>
      ${mayDelete && rows.length ? `<button type="button" class="danger" id="setReportsClear">Clear reports</button>` : ""}</div></div>`;
}

async function deleteReport(btn){
  const id = Number(btn.dataset.repdel);
  busy(btn, "");
  try{
    const j = await (await postJSON("/api/reports", {action: "delete", id})).json();
    if (j.error){ notify(j.error, true); unbusy(btn, ""); return; }
    notify(`report #${id} deleted`);
  }catch{ notify("could not delete the report", true); unbusy(btn, ""); return; }
  await loadReports();
}

async function clearReports(btn){
  // Read again first: a report may have come in, or gone, since the draw.
  await loadReports();
  const n = reportsList?.length || 0;
  if (!n) return notify("there are no reports to clear");
  const s = n === 1 ? "" : "s";
  if (!await askYes(`Delete all ${n} report${s} about BuilderBot?`)) return;
  busy(btn, "Clearing");
  try{
    const j = await (await postJSON("/api/reports", {action: "clear"})).json();
    if (j.error) notify(j.error, true);
    else notify(`cleared ${j.cleared} report${j.cleared === 1 ? "" : "s"}`);
  }catch{ notify("could not clear the reports", true); }
  unbusy(btn, "Clear reports");
  loadReports();
}

// The settings that used to be environment variables (roadmap R29): what is
// left of them after the operator asked which needed to exist at all. Each
// group is one section with one Apply, a field that has never been saved
// says so beside it, and the bar says whether a change applies at once or at the
// next start. Drawn from the poll's copy, so a save shows on the next poll.
const SETTING_GROUPS = [
  // The apps this controller offers its people (R272 step 3, apps.py): each
  // one on is fetched from the release matching this controller, checked
  // against its sha256 and offered on the Apps page (under Build); Look now asks the
  // release again rather than waiting for the daily look.
  {key: "apps", title: "Apps", off: "apps", intro: appsIntro, status: appsStatus,
   heading: s => `${["apps_android", ...(s?.settings?.offer_unvetted?.value ? ["apps_vscode", "apps_companion"] : [])]
     .filter(k => s?.settings?.[k]?.value).length} offered`,
   fields: [
    {key: "apps_android", label: "Android app", type: "bool",
     hint: "The notebook, the bell and your sessions on a phone, and the phone lent to a project."},
    {key: "apps_vscode", label: "VS Code extension", type: "bool", dev: true,
     hint: "A project's files and terminal in VS Code."},
    {key: "apps_companion", label: "Windows companion", type: "bool", dev: true,
     hint: "A folder on a Windows PC kept in step with a project, for a tool that only runs there."}]},
  // The home tunnel the controller runs itself (R176): the public hostname
  // a node off the LAN dials, the tunnel's token, and an API token that
  // writes the hostname's record and the tunnel's rules rather than having
  // them clicked. The two tokens are secrets: never shown back.
  // Named for what it is for, not for its field (the operator, 13 Oct):
  // "Public hostname" read as a node's or a route's, and those are on the
  // node's row and the nginx tab.
  {key: "tunnel", title: "Reach from outside", off: "tunnel", status: tunnelStatus, intro: tunnelSteps,
   heading: s => !s?.tunnel ? "" : s.tunnel.connected ? "connected" : s.tunnel.configured ? (s.tunnel.running ? "starting" : "stopped") : "off",
   headingCls: s => s?.tunnel?.connected ? "ok" : "",
   fields: [
    {key: "tunnel_host", label: "Hostname", type: "text", placeholder: "bb.example.com",
     hint: "The name a node off your network dials the controller at, published by a tunnel from home. Enroll node offers it as the controller's address."},
    {key: "tunnel_token", label: "Tunnel token", type: "secret",
     hint: "From Zero Trust: Networks, Tunnels, Create a tunnel (Cloudflared), the long eyJ… string in its install command. The controller runs the tunnel itself with it."},
    {key: "cf_api_token", label: "Cloudflare API token (optional)", type: "secret",
     hint: "With Zone DNS Edit and Account Cloudflare Tunnel Edit: the hostname's record and the tunnel's two rules (the agent's API to the controller, everything else 404) are written on Apply rather than clicked."}]},
  // The room a node keeps for itself (R110): the numbers the bell, the
  // build gate, a rebuild's check and the hourly prune go by, and a memory
  // limit for a container whose compose file sets none.
  {key: "room", title: "Room on the nodes", status: () => "applies at once; a container's limit at its next start",
   heading: s => `${s?.settings?.room_floor_gb?.value ?? 10} GB kept`,
   fields: [
    {key: "room_floor_gb", label: "Disk kept free (GB)", type: "number",
     hint: "A node under this much free on a disk or a store is on the bell, and a build, a test or a container rebuild there is refused until room is made. A disk smaller than ten times this keeps a tenth of itself instead."},
    {key: "room_mem_pct", label: "Memory warning (% in use)", type: "number",
     hint: "A node or a VM using more than this share of its memory over ten minutes is on the bell, before the system starts killing processes."},
    {key: "container_mem_gb", label: "Default container memory (GB, 0 for none)", type: "number",
     hint: "A container whose compose file sets no memory limit gets this one when it starts, so one runaway app cannot take the node's memory. A limit the compose file sets is kept."}]},
  // Maintenance mode, the owner's alone (state.can.maintenance): every
  // other account is told why and kept out until it is off, and a band on
  // every page reminds the owner it is on.
  {key: "maint", title: "Maintenance", can: "maintenance",
   heading: s => s?.settings?.maintenance_mode?.value ? "on" : "off",
   headingCls: s => s?.settings?.maintenance_mode?.value ? "warn" : "",
   fields: [
    {key: "maintenance_mode", label: "Maintenance mode", type: "bool",
     hint: "Only you can sign in and use BuilderBot, from the page, a phone or a session. Everybody else is told it is down for maintenance and stays signed in for after; their sessions and terminals are ended when it goes on, which it asks about first. Nodes keep running."}]},
];

// Turning maintenance mode on: who is kept out, and the sessions and
// terminals of theirs it ends, each with what it is doing (the operator, 27
// Oct), so a working session is not ended unseen.
const MAINT_STATE = {working: "working", waiting: "waiting for its person", asking: "asking for permission", open: "open"};
async function maintAsk(rows){
  const line = r => `${r.who}: ${r.what}${r.project ? ` on ${r.project}` : ""}, ${MAINT_STATE[r.state] || "idle"}, on ${r.node}`;
  const busyN = rows.filter(r => r.state === "working").length;
  const text = rows.length
    ? `Everybody else is kept out until it is off, and these ${rows.length} session${rows.length === 1 ? "" : "s"} and terminal${
        rows.length === 1 ? "" : "s"} of theirs end now${busyN ? `, ${busyN} of them in the middle of work` : ""}:\n\n${rows.map(line).join("\n")}`
    : "Everybody else is kept out until it is off. Nobody else has a session or a terminal open.";
  return askYes(text, {title: "Turn maintenance mode on?", verb: rows.length ? "End them and turn it on" : "Turn it on", danger: rows.length > 0});
}

// What the Apps section holds, over its switches, and Look now.
function appsIntro(){
  return `<div class="sub">Each one on is fetched from the release that matches this controller, checked, and offered on the ${
    pageLink("apps", "Apps page")} for your people to download and keep current.</div>
    <div class="addbar ctlrow"><button type="button" id="setAppsCheck"${devApps?.checking ? " disabled" : ""}>${devApps?.checking ? "Looking…" : "Look now"}</button></div>`;
}
// ...and its line: what it holds, from which release, when it looked.
function appsStatus(){
  if (!devApps) return "applies at once";
  const held = (devApps.apps || []).filter(a => a.files.length);
  const when = devApps.checked ? `looked ${ago(devApps.checked)}` : "not looked yet";
  if (devApps.problem) return `${devApps.problem} · ${when}`;
  return held.length ? `holds ${held.map(a => a.title).join(", ")} from ${devApps.release}${devApps.matched ? "" : " (no release matches this controller: the newest)"} · ${when}` : when;
}

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
  if (t.route?.ok === true) return `connected: ${t.host || "the tunnel"} reaches this controller${tunnelNodes()}`;
  return `connected; checking that ${t.host || "the name"} reaches this controller`;
}

// Which nodes come in through the tunnel, on the same line: the route is
// each node's (chosen in Enroll node, kept on its record), and this is the
// one place the controller's side of it is set.
function tunnelNodes(){
  if (nodesList === null){ loadNodes(); return ""; }
  const via = (nodesList || []).filter(n => n.config?.tunnel?.kind === "public").map(n => n.name);
  return via.length ? `; ${via.join(", ")} come${via.length === 1 ? "s" : ""} in through it` : "; no node comes in through it yet";
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

function settingsSections(){
  const s = state?.settings;
  if (!s) return [{key: "wait", title: "Settings", status: "", html: `<div class="row stack2"><div class="grow"><div class="sub">the settings arrive with the first poll…</div></div></div>`}];
  const src = k => s.settings[k]?.source === "default" ? `<span class="pill">default</span>` : "";
  // What this install switched off from its environment (R81), listed first
  // when there is any: set where the container starts, so nothing here
  // turns it back on.
  const offs = Object.values(state?.off || {});
  const offSect = offs.length ? [{key: "off", title: "Switched off", status: String(offs.length), cls: "",
    html: `<div class="row stack2"><div class="grow"><div class="sub">Set where this container starts (FEATURES_OFF), so nothing here turns them back on.</div>${
      offs.map(w => `<div class="setrow">${esc(w)}</div>`).join("")}</div></div>`}] : [];
  return offSect.concat(SETTING_GROUPS.filter(g => !g.can || state?.can?.[g.can]).map(g => {
    const field = f => {
            const v = s.settings[f.key]?.value;
            const id = "set_" + f.key;
            // A text is a field with its label over it; a secret the same,
            // typed blind, with "set" said beside it and never its value:
            // left empty it is left alone, and its own tick takes it off.
            if (f.type === "text" || f.type === "secret"){
              const isSet = f.type === "secret" ? !!s.settings[f.key]?.set : !!v;
              return `<div class="setrow col ctlrow"><label for="${id}">${esc(f.label)}${f.dev ? devMark() : ""}${helpIcon(f.hint)}${
                  f.type === "secret" ? (isSet ? ` <span class="pill ok">set</span>` : ` <span class="pill">not set</span>`) : src(f.key)}</label>
                <input id="${id}" type="${f.type === "secret" ? "password" : "text"}" data-set="${f.key}"${
                  f.type === "secret" ? ' data-secret="1"' : ""} value="${esc(f.type === "secret" ? "" : sdVal(id, v || ""))}"
                  placeholder="${esc(f.type === "secret" ? (isSet ? "set: paste a new one to replace it" : "paste it") : (f.placeholder || ""))}"
                  autocomplete="off" spellcheck="false">${
                  f.type === "secret" && isSet ? `<label class="ndcap"><input type="checkbox" data-clear="${f.key}"> take it off</label>` : ""}
              </div>`;
            }
            // A number is a short field beside its label, held to the
            // range the server keeps (settings.KEYS) by the browser too.
            if (f.type === "number"){
              const m = s.meta?.[f.key] || {};
              return `<div class="setrow col ctlrow"><label for="${id}">${esc(f.label)}${helpIcon(f.hint)}${src(f.key)}</label>
                <input id="${id}" type="number" inputmode="numeric" data-set="${f.key}" data-num="1"
                  min="${esc(String(m.min ?? 0))}" max="${esc(String(m.max ?? ""))}" step="1"
                  value="${esc(String(sdVal(id, v ?? "")))}">
              </div>`;
            }
            // Every other setting is a switch: a checkbox inside its label,
            // the way the Tests bar's are, with what the label cannot say on
            // the ? (docs/design-language.md, Controls).
            return `<div class="logdays setrow ctlrow"><label class="ndcap">
                <input id="${id}" type="checkbox" data-set="${f.key}"${sdVal(id, !!v) ? " checked" : ""}> ${esc(f.label)}${f.dev ? devMark() : ""}${helpIcon(f.hint)}</label>${src(f.key)}
              </div>`;
    };
    // A group whose feature this install switched off (R81): its sentence
    // in place of its fields, which nothing could apply.
    if (g.off && featureOff(g.off)) return {key: g.key, title: g.title, status: "off", cls: "",
      html: `<div class="row stack2" data-group="${esc(g.title)}"><div class="grow">${deadWhy(featureOff(g.off))}</div></div>`};
    return {key: g.key, title: g.title, status: g.heading ? g.heading(s) : "", cls: g.headingCls ? g.headingCls(s) : "",
      html: `<div class="row stack2" data-group="${esc(g.title)}">
      <div class="grow">
        <div class="logset">
          ${g.intro ? g.intro(s) : ""}
          ${g.fields.filter(f => !f.dev || s.settings.offer_unvetted?.value).map(field).join("")}
          <div class="actbar">
            <span class="state">${g.status ? g.status(s) : "applies at once"}</span>
            <button type="button" class="setApply" title="save">Apply</button>
          </div>
        </div>
      </div>
    </div>`};
  }));
}

function wireSettingsSections(el){
  el.querySelectorAll('[data-group]').forEach(box => {
    const btn = box.querySelector(".setApply");
    if (!btn) return;
    const apply = async () => {
      const set = {};
      box.querySelectorAll("[data-set]").forEach(i => {
        // A secret left empty is left as it is; its tick takes it off.
        if (i.dataset.secret && !i.value.trim()) return;
        set[i.dataset.set] = i.type === "checkbox" ? i.checked : i.dataset.num ? Number(i.value) : i.value.trim();
      });
      box.querySelectorAll("[data-clear]:checked").forEach(i => { set[i.dataset.clear] = ""; });
      busy(btn, "Applying");
      try{
        const post = extra => fetch("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"}, body: JSON.stringify({set, ...extra})});
        let j = await (await post({})).json();
        // Maintenance mode asks first, with every other account's sessions
        // and what each is doing, since turning it on ends them.
        if (j.confirm === "maintenance"){
          if (!await maintAsk(j.sessions || [])) return;
          j = await (await post({confirmed: true})).json();
        }
        if (j.error) return notify(j.error, true);
        box.querySelectorAll("[data-set]").forEach(i => { delete settingsDraft[i.id]; });
        // What the tunnel did with it (R176): the record and rules written,
        // or why not, said here rather than only on the next poll's line.
        if (j.published?.error) notify(`saved; Cloudflare: ${j.published.error}`, true);
        else if (j.published?.did) notify(`saved; Cloudflare: ${j.published.did.join("; ")}`);
        else if (j.tunnel?.error) notify(`saved; the tunnel: ${j.tunnel.error}`, true);
        else notify("saved");
        refresh();
      }catch(e){ notify("settings: " + failWords(e), true); }
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
      <div class="logdays setrow col ctlrow">
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
      notify(j.minutes ? `every agent's session ends after ${j.minutes} idle minute(s), here and on every node`
                       : "no session is ended for being idle");
      refresh();
    }catch(e){ notify("idle: " + failWords(e), true); }
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
    return `<div class="logdays setrow col ctlrow">
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
    }catch(e){ notify("storage: " + failWords(e), true); }
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
