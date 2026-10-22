// The Agents page (R95 step 15): the coding agents on one node, each a
// section of its own, in the agent table's order (page-agents.js): its
// version and the way to update it, and this account's sign-in on that
// node. What used to be spread over the Nodes page's Claude Code section and
// the Toolchains page's Claude Code row is here; the Nodes page keeps one
// line per node saying which agents are signed in there, with the way here.
//
// One node at a time, picked in the bar like every node's page (the
// node-switcher rule). Chrome from docSurface(); the hard rules are
// uniform.mjs's. Data: the node list (its census says what each agent's
// version is), the node's toolchain rows from /api/toolchains (the latest
// of each and whether a job runs), read when the page opens and on the
// toolchains and nodes revisions; the sign-in rides the status poll.

"use strict";

let agNode = "";              // the node the page shows
let agRows = null;            // that node's coding agent rows, or null before the read
let agErr = "";
let agRev = 0;
let agSeq = 0;
let agFollow = null;          // the one follow-up read while a job runs
let agYours = {plugins: [], mcp: {}};   // this account's plugins and MCP servers on the node

function openAgentsTab(node){
  if (node && node !== agNode){ agNode = node; agRows = null; }
  openTab({kind: "agents", arg: "__agents", label: "Agents"});
}
// ...on a node somebody named (the Nodes page's line, a Start with no
// sign-in there): remembered as the page's node, and a history entry.
function openAgentsOn(id){
  try{ localStorage.setItem("bb.agnode", id); }catch(e){ /* private */ }
  if (!(nodesList || []).some(n => n.id === id)) nodesStale = true;
  const was = location.hash;
  openAgentsTab(id);
  agRev++;
  const to = routeOf(tabOf(panes[0]));
  if (to && to !== was) history.pushState(null, "", to);
}

// The node the page opens on: the one it showed last, else the first agent
// node, as the Toolchains page picks.
function agPick(){
  const live = (nodesList || []).filter(n => n.kind === "agent" && n.state !== "retired");
  let want = agNode;
  if (!live.some(n => n.id === want)){
    try{ want = localStorage.getItem("bb.agnode") || ""; }catch(e){ want = ""; }
  }
  if (!live.some(n => n.id === want)) want = live[0]?.id || "";
  agNode = want;
  return live.find(n => n.id === want) || null;
}

async function loadAgents(){
  const asked = ++agSeq;
  if (nodesList === null || nodesStale) await loadNodes();
  if (asked !== agSeq) return;
  const n = agPick();
  if (!n){
    agRows = [];
    agRev++; drawPanes();
    return;
  }
  try{
    const r = await fetch(`/api/toolchains?node=${encodeURIComponent(n.id)}`);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const got = await r.json();
    if (asked !== agSeq) return;
    agErr = got.error || "";
    agRows = (got.machine || []).filter(m => TC_AGENT_TOOLS.has(m.name));
    agYours = got.yours || {plugins: [], mcp: {}};
  }catch(e){
    if (asked !== agSeq) return;
    agErr = String(e);
    agRows = agRows || [];
  }
  // A job running on one of them is followed until it ends, as the
  // Toolchains page follows one: its end moves no revision of its own.
  clearTimeout(agFollow); agFollow = null;
  if ((agRows || []).some(m => m.running)) agFollow = setTimeout(loadAgents, 3000);
  agRev++;
  drawPanes();
}

// What the page draws again on: its own reads, the node list, and the
// sign-in, which rides the status poll.
function agentsLiveKey(){ return `${agRev}/${nodesRev}/${signinRev()}`; }

// One agent's section: its version, its update, and the sign-in.
function agSection(a, n, m){
  const tool = m?.name || "";
  const may = mayToolchains(n.id);
  const up = !!n.reported?.session?.up;
  const running = !!m?.running;
  const doing = m?.action === "remove" ? "removing" : m?.here ? "updating" : "installing";
  let status, cls;
  if (!up) [status, cls] = ["no session account", "warn"];
  else if (running) [status, cls] = [doing, "warn"];
  else if (!m.installed) [status, cls] = ["not installed", a.id === "claude" ? "bad" : ""];
  else if (m.state === "update") [status, cls] = [`${m.installed}, ${m.latest} is out`, "warn"];
  else [status, cls] = [m.latest ? `${m.installed}, up to date` : m.installed, "ok"];
  if (a.provider && m?.installed && up && !running && !agentOn(a.id, n.id)) [status, cls] = [`${status}, not signed in`, "warn"];
  const facts = factGrid([
    ["program", a.product],
    ["installed", m?.installed || (up ? "none" : "")],
    ["latest", m?.latest || ""],
    ["signs in with", a.provider ? `${/^[AEIOU]/.test(a.provider) ? "an" : "a"} ${a.provider} account` : ""],
  ], "agfacts");
  const verb = m?.installed ? (m.state === "update" ? "Update" : "") : "Install";
  const acts = !up || !m || !may || running ? ""
    : `${verb ? `<button type="button" class="${a.id === "claude" && !m.installed ? "primary" : ""}" data-agact="install" data-agtool="${esc(tool)}">${esc(verb)}</button>` : ""}${
       m.installed ? `<button type="button" class="danger" data-agact="remove" data-agtool="${esc(tool)}">Remove</button>` : ""}`;
  const line = !up ? `${esc(n.name)} runs no session account, so nothing runs ${esc(a.product)} here.`
    : running ? `${esc(doing.charAt(0).toUpperCase() + doing.slice(1))} ${esc(a.product)}<span class="dots"></span>`
    : m?.installed ? `${esc(a.product)} ${esc(m.installed)} is what a ${esc(a.name)} session here runs.`
    : `Not installed: a ${esc(a.name)} session cannot start on ${esc(n.name)} until it is.`;
  const body = `<div class="field">${facts}</div>
    <div class="field"><div class="actbar"><span class="state">${line}</span>${acts}</div>
      ${m?.error && !running ? `<div class="sub bad">${esc(m.error)}</div>` : ""}</div>
    ${a.provider && up && (a.id === "claude" || m?.installed) ? `<div class="field">${signinBlock(n, a.id)}</div>` : ""}
    ${up && m?.installed ? agExtras(a) : ""}`;
  return docSection("agents", a.id, a.name, status, body, {cls});
}

// What this account added to an agent on the node (R95 step 15, moved here
// from Profile): Claude Code's plugins, and each agent's MCP servers, by
// name, as the node last said. Read here; changed in a session.
function agExtras(a){
  const pl = a.id === "claude" ? (agYours.plugins || []) : [];
  const mcp = (agYours.mcp || {})[a.id] || [];
  const one = p => `<code>${esc(p.id.replace(/@claude-plugins-official$/, ""))}</code>${p.version ? ` ${esc(p.version)}` : ""}${
    p.scope === "project" ? ` (${esc(p.project ? projLabel(p.project) : "a project")})` : ""}${p.enabled === false ? ` <span class="dim">off</span>` : ""}`;
  const rows = [
    a.id === "claude" ? ["your plugins", pl.length ? pl.map(one).join(", ") : "none", {html: true}] : null,
    ["your MCP servers", mcp.length ? mcp.map(x => `<code>${esc(x)}</code>`).join(", ") : "none", {html: true}],
  ].filter(Boolean);
  return `<div class="field">${factGrid(rows, "agextras")}<div class="hint">${
    a.id === "claude" ? "Changed with <code>/plugin</code> and <code>/mcp</code> in a Claude session, for you alone."
      : `Set up in ${esc(a.product)}'s own configuration, for you alone.`}</div></div>`;
}

function renderAgentsInto(i){
  const d = docSurface(i, "agents");
  if (!d) return;
  if (agRows === null){
    d.setBar(nodeBar(nodePick("", null)));
    d.list.innerHTML = skTpl(`${skRows(2)}${skRows(2)}`);
    loadAgents();
    return;
  }
  const n = agPick();
  const pnodes = (nodesList || []).filter(x => x.kind === "agent" && x.state !== "retired")
    .map(x => ({id: x.id, name: x.name, live: x.live}));
  d.setBar(nodeBar(nodePick("agNodeSel", pnodes, agNode)));
  if (!n){
    d.list.innerHTML = noNodeYet("a coding agent runs on a node");
    return;
  }
  if (agErr){
    d.list.innerHTML = `<div class="field"><div class="hint bad">${esc(agErr)}</div></div>`;
    return;
  }
  const shown = AGENTS.filter(a => agRows.some(m => m.agent === a.id));
  if (!shown.length){
    // A hosting-only node, or one with no session account: nothing there
    // runs a session, so no agent has anything to install or sign in to.
    paint(d.list, `<div data-agnode="${esc(n.id)}"><div class="empty">${esc(n.name)} runs no sessions${
      n.config?.host_only ? ": it only hosts containers" : ""}, so no coding agent runs there.</div></div>`);
    wireAgentsTab(d.el);
    return;
  }
  const hint = `<div class="field"><div class="hint">The coding agents a session on ${esc(n.name)} can run, each installed for its session account and signed in to by each person who works there.</div></div>`;
  paint(d.list, `<div data-agnode="${esc(n.id)}">${hint}${
    shown.map(a => agSection(a, n, agRows.find(m => m.agent === a.id))).join("")}</div>`);
  wireAgentsTab(d.el);
}

function wireAgentsTab(root){
  wireSections(root);
  wireSignin(root);
  const psel = root.querySelector("#agNodeSel");
  if (psel) psel.onchange = () => navPush(() => {
    agNode = psel.value; agRows = null;
    try{ localStorage.setItem("bb.agnode", agNode); }catch(e){ /* private */ }
    agRev++; drawPanes();
  });
  root.querySelectorAll("[data-agact]").forEach(b => b.onclick = async () => {
    const act = b.dataset.agact, tool = b.dataset.agtool;
    const m = (agRows || []).find(x => x.name === tool);
    const who = m?.for || "Claude";
    if (act === "remove" && !confirm(`Remove ${m?.label || tool} from ${agPick()?.name || "this node"}? Its ${who} sessions end, and none starts there until it is installed again.`)) return;
    if (act === "install" && m?.installed && !confirm(`Update ${m.label} on ${agPick()?.name || "this node"}? Its ${who} sessions there end first; they start again from the project rows.`)) return;
    busy(b, act === "remove" ? "Removing" : "Asking");
    const j = await (await postJSON("/api/toolchains", {action: act, node: agNode, names: [tool]})).json().catch(() => ({error: "no answer"}));
    if (j.error) notify(j.error, true);
    await loadAgents();
  });
}
