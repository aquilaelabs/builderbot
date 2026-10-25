// A Claude session, started: which of the project's nodes it runs on, what
// each node has, whether it resumes a conversation or starts a fresh one,
// and the way to a node's sign-in where this account has none there, all
// from the chooser the Claude button opens.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- a Claude session: which node, and resume or fresh ------------------

// Which project's chooser is open, if any.
let resumeFor = null;
// Where the chooser was asked for (R218 step 3): the pane of the project's
// page or of the Projects page; it is drawn in that one and positioned under
// the Claude button there.
let resumeHost = null;
function resumeHostNow(){
  if (resumeHost?.isConnected) return resumeHost;
  // Asked without a press (openClaude from code, a redraw): the pane where
  // that project's Claude button is on show, a page's header or its card.
  const b = resumeFor && [...document.querySelectorAll(`[data-c="${CSS.escape(resumeFor)}"]`)].find(x => x.offsetParent !== null);
  return b?.closest(".pane") || null;
}
// The chooser kept in step with a redraw of its host: the same menu stays
// where it is (drawn again on every poll, its buttons were replaced under
// the pointer), a stale one goes, and one asked for is placed.
function syncResumeMenu(){
  const host = resumeHostNow();
  if (!host){ document.querySelectorAll(".resumemenu").forEach(n => n.remove()); return; }
  const keep = resumePick && resumeFor === resumePick.project
    ? host.querySelector(`.resumemenu[data-pick="${CSS.escape(resumePick.project)}"]`) : null;
  const first = resumeFor && !keep
    ? host.querySelector(`.resumemenu[data-for="${CSS.escape(resumeFor)}"]:not([data-pick])`) : null;
  document.querySelectorAll(".resumemenu").forEach(n => { if (n !== keep && n !== first) n.remove(); });
  if (resumeFor && !keep) placeResumeMenu();
}
// The second step of the Claude button's menu (the operator, 12 Oct): which
// conversation on which node was picked, and the model and effort it is to
// start on, chosen there each time rather than kept in the project's
// settings. Kept here as they are picked, since the menu is drawn again on
// every poll. null while the menu offers its first step.
let resumePick = null;
// Which node the chooser's first step shows, of a project on several.
let rmNode = {project: "", node: ""};
// Your conversations on the project the chooser is open on, for its Resume
// band (R143): the Sessions view's list, read as it opens. rows null while
// it is on its way.
let rmConvs = {project: "", rows: null, error: ""};
async function loadRmConvs(name){
  rmConvs = {project: name, rows: null, error: ""};
  try{
    const j = await (await fetch("/api/transcripts?project=" + encodeURIComponent(name))).json();
    if (rmConvs.project !== name) return;
    rmConvs = j.error ? {project: name, rows: [], error: j.error} : {project: name, rows: j.rows || [], error: ""};
  }catch(e){ if (rmConvs.project === name) rmConvs = {project: name, rows: [], error: "could not read your conversations: " + failWords(e)}; }
  if (resumeFor === name && !resumePick) placeResumeMenu();
}

// `ps -o etime=` gives MM:SS under an hour, HH:MM:SS under a day, and
// D-HH:MM:SS beyond one. Rendered raw in a header with four buttons beside it
// that is exactly what ran out of room on a phone, and it did not wrap or
// shrink, it ELLIPSISED, so "09:52:31" became "09:52:…", which reads as a
// perfectly good and completely different number. Two units is all anybody
// reads off a header anyway; the About popup keeps the precise one.
function shortUptime(raw){
  const t = String(raw || "").trim();
  const m = t.match(/^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$/);
  if (!m) return t;                       // "?" from a ps that would not answer
  const [d, h, mi, sec] = [+(m[1] || 0), +(m[2] || 0), +m[3], +m[4]];
  // Only where the third field exists is the first hours; without it ps is
  // counting minutes and seconds, and calling those hours would be a lie in
  // the direction nobody checks.
  const parts = m[2] === undefined
    ? [[mi, "m"], [sec, "s"]]
    : [[d, "d"], [h, "h"], [mi, "m"], [sec, "s"]];
  const shown = parts.filter(([n]) => n > 0).slice(0, 2);
  return shown.length ? shown.map(([n, u]) => n + u).join(" ") : "0s";
}

const ago = s => {
  const d = Math.max(0, Math.floor(Date.now()/1000) - s);
  return d < 90 ? "just now"
       : d < 5400 ? `${Math.round(d/60)} min ago`
       : d < 172800 ? `${Math.round(d/3600)} h ago`
       : `${Math.round(d/86400)} days ago`;
};

// The places a Claude session of this project could run, as the chooser
// draws them: the project's several nodes (R82), its one, or this machine
// where a session runs here (id ""), which has no sign-in of a node's to ask
// about. None where there is nowhere, and session_why says so.
function claudeNodes(p){
  if ((p?.session_nodes || []).length > 1) return p.session_nodes;
  if (p?.session_node) return [(p.session_nodes || []).find(n => n.id === p.session_node)
    || {id: p.session_node, name: p.session_at, where: "node", why: ""}];
  return p && !p.session_why ? [{id: "", name: "", where: "node", why: ""}] : [];
}
// Whether this account can start one there without signing in first.
const claudeSigned = n => !n.id || !!claudeOn(n.id);
// Whether this account has a Claude session of this project running on one
// of the places claudeNodes lists: by node, since a project on several may
// have one on each; the place with no node is this account's one session.
const claudeLiveOn = (name, n, slot = 1) => (state?.sessions || []).some(s => s.name === myClaude(name, slot)
  && (!n.id || s.node_id === n.id));

// An agent's session tab on a project, dropped as its session ends: matched
// with what it was opened on (a resumed conversation, a model, an effort)
// taken off, which only the node it runs on is left beside.
function dropAgentTab(id, name, node, slot = 1){
  const arg = agentArg(id, name) + slotArg(slot) + (node ? `:n:${node}` : "");
  const t = tabs.find(x => x.kind === "term" && String(x.arg).replace(/:[rme]:[^:]*/g, "") === arg);
  if (t) dropTab(t.id);
}

// End this account's session of a project on one node, asked first, and
// drop its tab: the chooser's End session.
async function claudeEnd(name, n, several, slot = 1){
  const where = n.name ? ` on ${n.name}` : "", said = agentSlotName(agentById("claude"), slot);
  if (!await askYes(`End your ${said} session on ${projLabel(name)}${where}?\n\nThe transcript is kept and can be resumed later, but the conversation stops now.`)) return;
  resumeFor = null;
  if (state) drawProjects(state.projects);
  try{
    const j = await endSession(myClaude(name, slot), n.id);
    if (j.error) return notify(j.error, true);
    dropAgentTab("claude", name, several && n.id ? n.id : "", slot);
    notify(`ended your ${said} session on ${projLabel(name)}${where}`);
  }catch(e){ notify("could not end it: " + failWords(e), true); }
  refresh();
}

// Restart (the operator, 12 Oct): end the session and pick its conversation
// up again, which is how a session sees what changed since it started (a
// toolchain on its node's PATH, BuilderBot's briefing; the project row says
// which). The menu turns to the model and effort first, the conversation it
// was in already chosen; its Restart asks, and only then is the session
// ended and started again (restartNow). Asked first and ended at once, it
// left a person picking a model with no session running.
function claudeRestart(name, n, several, agent = "claude", slot = 1){
  const p = (state?.projects || []).find(x => x.name === name);
  const claude = agent === "claude", last = claude ? p?.last_claude : p?.last_agents?.[agent];
  // The conversation that slot is in, where its hooks have said (R143);
  // else the project's last, as before slots.
  const conv = mySlots(name).find(x => x.agent.id === agent && x.slot === slot)?.row?.claude?.conv;
  resumeFor = name;
  resumePick = {project: name, sessionId: conv || last?.id || null, node: several ? n.id : "", slot,
                model: p?.yours?.[claude ? "model" : `${agent}_model`] || "",
                effort: p?.yours?.[claude ? "effort" : `${agent}_effort`] || "",
                ...(claude ? {} : {agent}),
                restart: {id: n.id || "", name: n.name || "", several: !!several}};
  if (state) drawProjects(state.projects);
}

// The restart itself, once the model and effort are picked and the person
// said yes: end the session, wait until the controller no longer lists it,
// then start the same conversation. Started while the old one was still
// going down, the new tab attached to the dying session and showed it end,
// and a second press was what got a session (the operator, 12 Oct).
async function restartNow(name, r){
  const n = r.restart, id = r.agent || "claude", slot = r.slot || 1;
  const where = n.name ? ` on ${n.name}` : "";
  const j = await endSession(myAgentSession(id, name, slot), n.id).catch(e => ({error: String(e)}));
  if (j.error) return j.error;
  dropAgentTab(id, name, n.several && n.id ? n.id : "", slot);
  const live = () => id === "claude" ? claudeLiveOn(name, {id: n.id}, slot) : agentLiveOn(id, name, {id: n.id}, slot);
  for (let i = 0; i < 40 && live(); i++){
    await new Promise(res => setTimeout(res, 500));
    await refresh();
  }
  if (live())
    return `your session${where} is still going down; press Restart again in a moment`;
  return "";
}

// Something started a session on a node this account has not signed in on
// (a step sent from the notebook, a brief): it goes to that node's sign-in
// instead of to a session that would start and say so. True when it did.
// The Claude button itself offers the sign-in in its chooser; this is the
// same answer for every other way in. A session of theirs already running
// is left alone, since the record is a report and the session is the fact.
function claudeSigninFirst(name, nodeId){
  if (!nodeId || claudeOn(nodeId) || claudeLiveOn(name, {id: nodeId})) return false;
  resumeFor = null;
  if (state) drawProjects(state.projects);
  const at = (nodesList || []).find(n => n.id === nodeId)?.name
    || claudeNodes((state?.projects || []).find(x => x.name === name)).find(n => n.id === nodeId)?.name || "its node";
  notify(`sign in to Claude on ${at} first: a sign-in is each node's own`);
  openNodeClaude(nodeId);
  return true;
}

// A choice arises whenever there is something to choose: a running session
// (open its tab, or end it, with the project's other nodes still offered
// beside it: the operator, 30 Sep), a transcript to resume (which is what a
// restart leaves behind), several nodes to run on, or a node this account
// has yet to sign in on, whose sign-in the chooser offers in place of a
// session there.
function openClaude(name, ev){
  ev?.stopPropagation();
  const p = (state?.projects || []).find(x => x.name === name);
  const ns = claudeNodes(p);
  // Nowhere for it to run opens the reason under the row rather than a
  // tab, which is the whole of what the press can do.
  // Always the menu now: a session starts on the model and effort picked in
  // it (the operator, 12 Oct), so even one node and nothing to resume asks.
  void ns;
  resumeFor = resumeFor === name ? null : name;
  resumePick = null;
  resumeHost = ev?.currentTarget?.closest?.(".pane, .card") || null;
  if (resumeFor) loadRmConvs(name);
  drawProjects(state.projects);
  syncResumeMenu();
}

// One conversation picked to go on with (the notebook's Sessions view, the
// operator, 22 Oct: the project's Claude button resumes only the last): the
// chooser opens on it at the model and effort step, in the lowest slot of
// its agent free (R143). One running in a session of yours already is
// opened there rather than started twice, which would write over it; with
// every slot taken it is said, and nothing starts.
function resumeConversation(name, id, when, ev, agent = "claude"){
  const p = (state?.projects || []).find(x => x.name === name);
  if (!p) return;
  ev?.stopPropagation();
  agent = agent || "claude";
  const claude = agent === "claude";
  const live = mySlots(name).find(x => x.row.claude?.conv === id);
  if (live){
    notify(`that conversation is running in your ${agentSlotName(live.agent, live.slot)} session: its tab is open`);
    const nid = (claudeNodes(p).length > 1 && live.row.node_id) || "";
    return claude ? launchClaude(name, null, nid, live.slot) : launchAgent(agent, name, nid, "", "", "", live.slot);
  }
  const slot = freeSlot(name, agent);
  if (!slot)
    return notify(`every ${agentById(agent).name} session you may run on ${projLabel(name)} is running: end one to resume this`, true);
  // A conversation resumes in the agent it is with, and in no other (R95
  // step 8): the chooser turns to that agent's own step, its model and
  // effort, on the project's node.
  const ns = claudeNodes(p), several = ns.length > 1;
  resumeFor = name;
  // Under the project's own Start agent where it is on show (the notebook's
  // header), not the box the row's button sits in, which holds no Start.
  resumeHost = null;
  resumePick = {project: name, sessionId: id, when, node: several ? (ns[0]?.id || "") : "", slot,
                ...(claude ? {} : {agent}),
                model: p.yours?.[claude ? "model" : `${agent}_model`] || "", effort: p.yours?.[claude ? "effort" : `${agent}_effort`] || ""};
  drawProjects(state.projects);
  syncResumeMenu();
  // Nowhere to start it (placeResumeMenu found no Start agent to open under):
  // said, rather than a press that does nothing.
  if (resumeFor !== name)
    notify(claude && claudeInstall(p) ? `Claude Code is not installed on ${p.node_name || "this project's node"}: install it from its Agents page, then resume`
      : "a session cannot start on this project now: its Start agent says why", true);
}

// The agent a send on a project reaches: the running session the server
// types into, Claude's first as names.running_session picks, else the one
// Start agent opens. A send reached a ChatGPT or Copilot session too, under
// a button that said Claude.
function sendAgent(project){
  const live = liveSessions();
  return AGENTS.find(a => live.has(myAgentSession(a.id, project)))
    || agentById((state?.projects || []).find(x => x.name === project)?.prefs?.agent_default) || AGENTS[0];
}
// ...and its tab, opened after a send to watch the answer: the session the
// server says it typed into, else the one a send reaches. A ChatGPT or
// Copilot session opens as itself; opening Claude's started a Claude session
// beside it.
function openSentTo(project, session = ""){
  const ag = (session && agentOfSession(tmuxBase(session))?.agent) || sendAgent(project);
  if (ag.id !== "claude") return launchAgent(ag.id, project);
  startClaude(project, null);
}

// Which of your sessions on a project a send goes to, where several run
// (R143): asked, each by its agent and slot. "" with one or none, which the
// server answers as before; null when the asking was put away.
async function pickSend(project){
  const s = mySlots(project);
  if (s.length < 2) return "";
  const r = await ask({title: `Which of your sessions on ${projLabel(project)}?`,
                       text: "It arrives in that one as a prompt.",
                       choices: s.map(x => ({label: agentSlotName(x.agent, x.slot), value: x.name}))});
  return typeof r === "string" ? r : null;
}
// A button that sends something to a project's session asks first (the
// operator, 6 Oct): what it sends arrives as a prompt and the agent starts on
// it at once, so a stray tap is work begun. The bug and roadmap sends ask in
// their own send box; every other Send asks here.
async function sendSure(project, what){
  const a = sendAgent(project).name;
  return await askYes(`Send ${what} to ${projLabel(project)}'s ${a} session?\n\n`
                 + `It arrives as a prompt, and ${a} starts on it at once.`);
}

// A new project's first session goes through its brief's dialog: a new
// conversation (no transcript picked), nothing running, and a brief still
// waiting in the tree (brief.py). Everything else starts at once.
function startClaude(name, sessionId, node, slot = 1){
  const p = (state?.projects || []).find(x => x.name === name);
  if (claudeSigninFirst(name, node || p?.session_node || "")) return;
  if (!sessionId && p?.brief && slot === 1 && !claudeLiveOn(name, {id: node || ""}))
    return openBrief(name, node || "");
  launchClaude(name, sessionId, node, slot);
}

// Another coding agent's session (R95 step 4): Codex CLI or Copilot CLI on
// one of the project's nodes, a new conversation in a tab of its own, named
// for the agent. Its session is its own beside a Claude one, in a tree of
// its own (session_dir), so one person may run both on a project at once.
const agentLiveOn = (id, name, n, slot = 1) => (state?.sessions || []).some(s => s.name === myAgentSession(id, name, slot)
  && (!n.id || s.node_id === n.id));
function launchAgent(id, name, node, model = "", effort = "", sessionId = "", slot = 1){
  const a = agentById(id);
  if (!a) return;
  resumeFor = null;
  resumePick = null;
  if (state) drawProjects(state.projects);
  const p = (state?.projects || []).find(x => x.name === name);
  const nn = node ? (p?.session_nodes || []).find(x => x.id === node)?.name || node : "";
  // Its model and effort ride the argument (R95 step 9), which bb-tty
  // holds to the agent's own lists.
  const me = (model ? `:m:${model}` : "") + (effort ? `:e:${effort}` : "");
  openTab({kind: "term", arg: agentArg(id, name) + (sessionId ? `:r:${sessionId}` : "") + me + slotArg(slot) + (node ? `:n:${node}` : ""),
           label: `${agentSlotName(a, slot)}: ${projLabel(name)}` + (nn ? ` (${nn})` : "")});
}
async function agentEnd(id, name, n, several, slot = 1){
  const a = agentById(id), said = agentSlotName(a, slot);
  const where = n.name ? ` on ${n.name}` : "";
  if (!await askYes(`End your ${said} session on ${projLabel(name)}${where}?\n\nThe transcript is kept and can be resumed later, but the conversation stops now.`)) return;
  resumeFor = null;
  if (state) drawProjects(state.projects);
  try{
    const j = await endSession(myAgentSession(id, name, slot), n.id);
    if (j.error) return notify(j.error, true);
    dropAgentTab(id, name, several && n.id ? n.id : "", slot);
    notify(`ended your ${said} session on ${projLabel(name)}${where}`);
  }catch(e){ notify("could not end it: " + failWords(e), true); }
  refresh();
}

function launchClaude(name, sessionId, node, slot = 1){
  resumeFor = null;
  resumePick = null;
  // Redraw the card, not just the tabs: the chooser is a child of it and would
  // otherwise sit there until the next poll, over a choice already made.
  if (state) drawProjects(state.projects);
  const p = (state?.projects || []).find(x => x.name === name);
  const nn = node ? (p?.session_nodes || []).find(x => x.id === node)?.name || node : "";
  openTab({kind:"term",
           arg: agentArg("claude", name) + (sessionId ? `:r:${sessionId}` : "") + slotArg(slot) + (node ? `:n:${node}` : ""),
           label: `${agentSlotName(agentById("claude"), slot)}: ${projLabel(name)}` + (nn ? ` (${nn})` : "")});
}

// ---- a new project's first session ------------------------------------------
// The brief the project was made with, editable, and the model and effort the
// session starts on, since nothing has started yet. Build it stages the brief
// for this account and opens the session, which takes it as its first prompt
// as it starts; Start without it opens one that was not given it and puts the
// brief away. Either way the brief leaves the project's tree then, and its
// notebook keeps it. Whichever agent the session is (R95): Codex's and
// Copilot's first prompt is the brief as Claude's is, with their own models.
let briefFor = null;

async function openBrief(name, node, agent = "claude"){
  resumeFor = null;
  resumePick = null;
  if (state) drawProjects(state.projects);
  briefFor = {name, node, agent};
  const p = (state?.projects || []).find(x => x.name === name);
  const a = agentById(agent);
  $("briefTitle").textContent = agent === "claude" ? `First session on ${projLabel(name)}`
    : `First ${a.name} session on ${projLabel(name)}`;
  $("briefErrWrap").hidden = true;
  $("briefText").value = "";
  if (agent === "claude"){
    for (const [id, table, cur] of [["briefModel", MODELS, p?.yours?.model || ""],
                                    ["briefEffort", EFFORTS, p?.yours?.effort || ""]]){
      $(id).innerHTML = optionList(table, cur);
    }
  } else {
    const t = AGENT_MODELS[agent] || {models: [], efforts: []};
    for (const [id, xs, cur] of [["briefModel", t.models, p?.yours?.[`${agent}_model`] || ""],
                                 ["briefEffort", t.efforts, p?.yours?.[`${agent}_effort`] || ""]]){
      $(id).innerHTML = optionList([["", `${a.name}'s default`], ...xs.map(v => [v, v])], cur);
    }
  }
  for (const b of ["briefGo", "briefSkip"]) $(b).disabled = true;
  $("briefModal").hidden = false;
  try{
    const j = await (await fetch("/api/brief?project=" + encodeURIComponent(name))).json();
    if (briefFor?.name !== name) return;
    if (j.error) throw new Error(j.error);
    $("briefText").value = j.text || "";
  }catch(e){
    $("briefErr").textContent = "could not read the brief: " + e.message;
    $("briefErrWrap").hidden = false;
  }
  for (const b of ["briefGo", "briefSkip"]) $(b).disabled = false;
}

function closeBrief(){ $("briefModal").hidden = true; briefFor = null; }

// Build it (skip false) or Start without it (skip true). The model and the
// effort are saved first, as the settings dialog saves them, so the session
// the press opens starts on them.
async function briefGo(skip){
  const f = briefFor;
  if (!f) return;
  const p = (state?.projects || []).find(x => x.name === f.name);
  const text = $("briefText").value.trim();
  const model = $("briefModel").value, effort = $("briefEffort").value;
  const fail = m => { $("briefErr").textContent = m; $("briefErrWrap").hidden = false; };
  if (!skip && !text) return fail("the brief is empty: Start without it starts a session with no brief");
  const b = $(skip ? "briefSkip" : "briefGo");
  const was = b.textContent;
  busy(b, "Starting");
  try{
    const mk = f.agent === "claude" ? "model" : `${f.agent}_model`, ek = f.agent === "claude" ? "effort" : `${f.agent}_effort`;
    if (model !== (p?.yours?.[mk] || "") || effort !== (p?.yours?.[ek] || "")){
      const j = await (await postJSON("/api/prefs", {project: f.name, [mk]: model, [ek]: effort})).json();
      if (j.error) throw new Error(j.error);
    }
    const j = await (await postJSON("/api/brief", skip ? {project: f.name, action: "aside"}
                                                       : {project: f.name, action: "stage", text})).json();
    if (j.error) throw new Error(j.error);
  }catch(e){
    unbusy(b, was);
    return fail(e.message);
  }
  unbusy(b, was);
  closeBrief();
  if (f.agent === "claude") launchClaude(f.name, null, f.node);
  else launchAgent(f.agent, f.name, f.node, model, effort);
  refreshSoon();
}

// What a node has and how busy it is, on its button in the chooser: the
// pick is a read (a card for the emulator, a quiet box), not a name.
function claudeNodeFacts(n){
  const s = n.sample || {};
  const bits = [];
  if (s.cpu_pct !== undefined) bits.push(`cpu ${s.cpu_pct}%`);
  if (s.mem_mb) bits.push(`${Math.round((s.mem_used_mb || 0) / 1024 * 10) / 10}/${Math.round(s.mem_mb / 1024)}GB`);
  if (n.gpu) bits.push(n.gpu);
  if ((n.tools || []).length) bits.push(n.tools.join(", "));
  return bits.join(" · ");
}

// The menu's second step: the model and effort a session starts on, picked
// each time (the operator, 12 Oct), opening on the last ones picked here,
// and Start. Saved as this account's own for the project, which is what the
// launcher reads when the session starts, so nothing else changes.
let resumeModelNow = {project: "", model: ""};
function resumePicker(p, m, card, anchor, ns, several){
  const r = resumePick;
  const n = ns.find(x => x.id === r.node) || ns[0] || {};
  if (r.agent && r.agent !== "claude") return agentPicker(p, m, card, anchor, n, several);
  const opts = (table, cur) => table.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${
    esc(v === "" && table === MODELS && resumeModelNow.project === p.name && resumeModelNow.model
      ? `Claude's default (last session: ${(MODELS.find(([x]) => x === resumeModelNow.model) || [])[1] || resumeModelNow.model})` : l)}</option>`).join("");
  // What it will do as its head, the two picks labeled above their fields
  // side by side, and Back and the press at its foot (the design 2.0 pass).
  // The head names the agent and its product, as the other agents' does.
  // Which of your Claude sessions it is, past the first (R143).
  const as = (r.slot || 1) > 1 ? ` as ${agentSlotName(agentById("claude"), r.slot)}` : "";
  m.innerHTML = `<div class="rmhead"><b>${r.restart ? `Restart your ${esc(agentSlotName(agentById("claude"), r.slot || 1))} session`
      : r.sessionId ? "Resume the Claude conversation" : "A new Claude conversation"}</b><span class="rmfacts">${
      r.restart ? (r.when ? `ending the one running, resuming the one from ${esc(ago(r.when))} · ` : "ending the one running, resuming its conversation · ")
        : r.sessionId ? `from ${esc(ago(r.when ?? p.last_claude?.when))} · ` : ""}Claude Code${
      several || n.name ? ` on ${esc(n.name || "")}` : ""}${r.restart ? "" : esc(as)}</span></div>
    <div class="rmfields">
      <div class="setrow col ctlrow"><label class="lbl" for="rmModel">Model</label><select id="rmModel" aria-label="model this session starts on">${opts(MODELS, r.model)}</select></div>
      <div class="setrow col ctlrow"><label class="lbl" for="rmEffort">Effort</label><select id="rmEffort" aria-label="effort this session starts on">${opts(EFFORTS, r.effort)}</select></div>
    </div>
    <div class="actbar rmacts"><span class="state" id="rmSay"></span><span class="sp"></span>
      <button type="button" data-back>Back</button>
      <button type="button" class="${r.restart ? "danger" : "primary"}" data-start>${r.restart ? "Restart" : "Start"}</button></div>`;
  m.dataset.pick = p.name;
  card.appendChild(m);
  m.querySelector("#rmModel").onchange = e => { r.model = e.target.value; };
  m.querySelector("#rmEffort").onchange = e => { r.effort = e.target.value; };
  m.querySelector("[data-back]").onclick = () => { resumePick = null; drawProjects(state.projects); };
  m.querySelector("[data-start]").onclick = async e => {
    const label = r.restart ? "Restart" : "Start";
    if (r.restart && !await askYes(`Restart your ${agentSlotName(agentById("claude"), r.slot || 1)} session on ${projLabel(p.name)}${r.restart.name ? ` on ${r.restart.name}` : ""}?\n\n`
        + (r.when ? "It ends now, and the conversation you picked is resumed in its place."
                  : "It ends now and resumes the same conversation, starting fresh so it sees what changed since it started."))) return;
    busy(e.target, r.restart ? "Restarting" : "Starting");
    if (r.model !== (p.yours?.model || "") || r.effort !== (p.yours?.effort || "")){
      const j = await (await postJSON("/api/prefs", {project: p.name, model: r.model, effort: r.effort})).json()
        .catch(() => ({error: "no answer"}));
      if (j.error){ unbusy(e.target, label); m.querySelector("#rmSay").textContent = j.error; return; }
      if (p.yours) Object.assign(p.yours, {model: r.model, effort: r.effort});
    }
    if (r.restart){
      const why = await restartNow(p.name, r);
      if (why){ unbusy(e.target, label); m.querySelector("#rmSay").textContent = why; return; }
    }
    resumePick = null;
    startClaude(p.name, r.sessionId, r.node, r.slot || 1);
  };
  // What the last session here answered on, for Claude's default to name.
  if (resumeModelNow.project !== p.name){
    resumeModelNow = {project: p.name, model: ""};
    fetch(`/api/claude-now?project=${encodeURIComponent(p.name)}`).then(x => x.json())
      .then(j => {
        if (!j.model || resumeModelNow.project !== p.name) return;
        resumeModelNow.model = j.model;
        const o = document.querySelector('#rmModel option[value=""]');
        if (o) o.textContent = `Claude's default (last session: ${(MODELS.find(([x]) => x === j.model) || [])[1] || j.model})`;
      })
      .catch(() => {});
  }
  floatAt(m, anchor);
}

// The same step for another agent's new conversation (R95 step 9): which
// agent, on which node, and that agent's own models and efforts, its
// default first; Start opens it. Nothing is saved: the pick rides the
// terminal's argument.
function agentPicker(p, m, card, anchor, n, several){
  const r = resumePick, a = agentById(r.agent), t = AGENT_MODELS[r.agent] || {models: [], efforts: []};
  const said = agentSlotName(a, r.slot || 1), as = (r.slot || 1) > 1 ? ` as ${said}` : "";
  const opts = (xs, cur) => [`<option value="">${esc(a.name)}'s default</option>`]
    .concat(xs.map(v => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(v)}</option>`)).join("");
  m.innerHTML = `<div class="rmhead"><b>${r.restart ? `Restart your ${esc(said)} session`
      : r.sessionId ? `Resume the ${esc(a.name)} conversation` : `A new ${esc(a.name)} conversation`}</b><span class="rmfacts">${
      r.restart ? (r.sessionId ? "ending the one running, resuming its conversation · " : "ending the one running · ")
        : r.sessionId && r.when ? `from ${esc(ago(r.when))} · ` : ""}${esc(a.product)}${
      several || n.name ? ` on ${esc(n.name || "")}` : ""}${r.restart ? "" : esc(as)}</span></div>
    <div class="rmfields">
      <div class="setrow col ctlrow"><label class="lbl" for="rmModel">Model</label><select id="rmModel" aria-label="model this session starts on">${opts(t.models, r.model)}</select></div>
      <div class="setrow col ctlrow"><label class="lbl" for="rmEffort">Effort</label><select id="rmEffort" aria-label="effort this session starts on">${opts(t.efforts, r.effort)}</select></div>
    </div>
    <div class="actbar rmacts"><span class="state" id="rmSay"></span><span class="sp"></span>
      <button type="button" data-back>Back</button>
      <button type="button" class="${r.restart ? "danger" : "primary"}" data-start>${r.restart ? "Restart" : "Start"}</button></div>`;
  m.dataset.pick = p.name;
  card.appendChild(m);
  m.querySelector("#rmModel").onchange = e => { r.model = e.target.value; };
  m.querySelector("#rmEffort").onchange = e => { r.effort = e.target.value; };
  m.querySelector("[data-back]").onclick = () => { resumePick = null; drawProjects(state.projects); };
  m.querySelector("[data-start]").onclick = async e => {
    const label = r.restart ? "Restart" : "Start";
    if (r.restart && !await askYes(`Restart your ${said} session on ${projLabel(p.name)}${r.restart.name ? ` on ${r.restart.name}` : ""}?\n\n`
        + "It ends now and resumes the same conversation, starting fresh so it sees what changed since it started.")) return;
    // Kept as this person's for the project, per agent (R95 step 9), so the
    // step opens on it next time; the session starts on it either way.
    const mk = `${r.agent}_model`, ek = `${r.agent}_effort`;
    busy(e.target, r.restart ? "Restarting" : "Starting");
    if (r.model !== (p.yours?.[mk] || "") || r.effort !== (p.yours?.[ek] || "")){
      const j = await (await postJSON("/api/prefs", {project: p.name, [mk]: r.model, [ek]: r.effort})).json().catch(() => ({error: "no answer"}));
      if (j.error){ unbusy(e.target, label); m.querySelector("#rmSay").textContent = j.error; return; }
      if (p.yours) Object.assign(p.yours, {[mk]: r.model, [ek]: r.effort});
    }
    if (r.restart){
      const why = await restartNow(p.name, r);
      if (why){ unbusy(e.target, label); m.querySelector("#rmSay").textContent = why; return; }
    }
    launchAgent(r.agent, p.name, r.node, r.model, r.effort, r.sessionId || "", r.slot || 1);
  };
  floatAt(m, anchor);
}

function placeResumeMenu(){
  const p = (state?.projects || []).find(x => x.name === resumeFor);
  const card = resumeHostNow();
  const anchor = card?.querySelector(`[data-c="${CSS.escape(resumeFor)}"]`);
  const ns = claudeNodes(p), several = ns.length > 1;
  if (!p || !anchor){ resumeFor = null; return; }
  const m = document.createElement("div");
  m.className = "pinmenu resumemenu";
  m.id = "resumemenu";
  if (resumePick?.project === p.name){
    // The first step leaves as the second comes up.
    card.querySelector(`.resumemenu[data-for="${CSS.escape(p.name)}"]:not([data-pick])`)?.remove();
    resumePicker(p, m, card, anchor, ns, several);
    return;
  }
  // Three bands (R143, the operator, 25 Oct): every session of yours on the
  // project, each agent's each slot on whichever node, with its state and
  // its Open, Restart and End; then Start, one line per agent installed on
  // the node picked, its New taking the lowest slot free; then Resume, your
  // conversations here to go on with, one running in a session of yours
  // shown and not offered, since two would write over each other. With
  // several nodes the node picker on top and its facts under it; the
  // project's default agent first.
  const at = several ? n => n.id : () => "";
  const mine = mySlots(p.name);
  const nodeOf = x => ns.find(y => y.id === x.row.node_id) || {id: x.row.node_id || "", name: x.row.node || ""};
  const runsOn = n => mine.some(x => !n.id || x.row.node_id === n.id);
  if (rmNode.project !== p.name || !ns.some(n => n.id === rmNode.node))
    rmNode = {project: p.name, node: (ns.find(runsOn) || ns.find(n => n.id === p.session_node) || ns[0] || {}).id || ""};
  const n = ns.find(x => x.id === rmNode.node) || ns[0];
  const line = (who, state, presses, cls = "") => `<div class="rmline${cls}"><span class="rmwho"><b>${esc(who)}</b>${
      state ? `<span class="rmsays">${esc(state)}</span>` : ""}</span><div class="actbar rmacts">${presses}</div></div>`;
  const STATE_WORDS = {working: "working", waiting: "waiting for you", asking: "asking you"};
  // Yours running: Claude's presses as they always were, another agent's
  // its own, each naming its slot (data-slot) and its node.
  const runningLine = x => {
    const nd = nodeOf(x), id = x.agent.id, claude = id === "claude";
    const words = [STATE_WORDS[x.row.claude?.state] || "running", several && nd.name ? `on ${nd.name}` : ""].filter(Boolean).join(" · ");
    const sl = ` data-slot="${x.slot}"`;
    return line(agentSlotName(x.agent, x.slot), words, claude
      ? `<button data-open="1" data-node="${esc(at(nd))}"${sl} class="primary" title="open your session's tab">Open</button>`
        + `<button data-restart="${esc(nd.id)}"${sl} title="end it and resume the same conversation">Restart</button>`
        + `<button data-end="${esc(nd.id)}"${sl} class="danger" title="end your session here">End</button>`
      : `<button data-aopen="${esc(id)}" data-node="${esc(at(nd))}"${sl} class="primary" title="open your session's tab">Open</button>`
        + `<button data-arestart="${esc(id)}" data-nid="${esc(nd.id)}"${sl} title="end it and resume the same conversation">Restart</button>`
        + `<button data-aend="${esc(id)}" data-nid="${esc(nd.id)}"${sl} class="danger" title="end your session here">End</button>`, " live");
  };
  // Start: a new conversation of each agent on the node picked, in the
  // lowest slot free, or why there is none.
  const startLine = a => {
    const node = at(n), claude = a.id === "claude";
    if (claude ? !claudeSigned(n) : n.id && !agentOn(a.id, n.id))
      return line(a.name, "not signed in here", claude
        ? `<button data-signin-node="${esc(n.id)}" title="opens ${esc(n.name)} on the Agents page, at its Claude sign-in">Sign in</button>`
        : `<button data-asignin="${esc(a.id)}" data-nid="${esc(n.id)}" title="opens ${esc(n.name)} on the Agents page, at its ${esc(a.name)} sign-in">Sign in</button>`);
    const slot = freeSlot(p.name, a.id);
    const cap = Math.min(AGENT_MAX_SLOTS, p.prefs?.agent_slots || 3);
    if (!slot) return line(a.name, `${cap} running, the most here: end one to start another`, "");
    const as = slot > 1 ? `, as ${agentSlotName(a, slot)}` : "";
    return line(a.name, slot > 1 ? `as ${agentSlotName(a, slot)}` : "", claude
      ? `<button data-n="1" data-node="${esc(node)}" data-slot="${slot}" title="a new conversation${esc(as)}">New</button>`
      : `<button data-anew="${esc(a.id)}" data-node="${esc(node)}" data-slot="${slot}" title="a new conversation${esc(as)}">New</button>`);
  };
  const here = () => {
    const first = p.prefs?.agent_default || "claude";
    return agentsLive().filter(a => (a.id === "claude" || (n.agents || []).includes(a.id))
        && !(p.prefs?.agents_off || []).includes(a.id))
      .sort((x, y) => (y.id === first) - (x.id === first));
  };
  // Resume: your conversations here, newest first (the Sessions view's
  // list), each its agent, when and its first words.
  const convs = () => {
    if (rmConvs.project !== p.name || rmConvs.rows === null)
      return `<div class="rmstate">${rmConvs.error ? esc(rmConvs.error) : "Reading your conversations here…"}</div>`;
    const ok = new Set(here().map(a => a.id));
    const rows = rmConvs.rows.filter(r => ok.has(r.agent || "claude")).slice(0, 8);
    if (!rows.length) return `<div class="rmstate">None yet: a conversation started here is kept to go on with.</div>`;
    return `<div class="rmconvs">${rows.map(r => {
      const a = agentById(r.agent || "claude"), live = mine.find(x => x.row.claude?.conv === r.id);
      return `<div class="rmline rmconv"><span class="rmwho"><b>${esc(a.name)}</b><span class="rmsays">${esc(ago(r.at))}</span></span>${
        live ? `<span class="rmsays rmin">running in ${esc(agentSlotName(live.agent, live.slot))}</span>`
             : `<div class="actbar rmacts"><button data-cv="${esc(r.id)}" data-cvagent="${esc(a.id)}" data-cvat="${esc(String(r.at))}" data-node="${esc(at(n))}" title="go on with this conversation">Resume</button></div>`}${
        r.first ? `<div class="rmfirst">${esc(r.first)}</div>` : ""}</div>`; }).join("")}</div>`;
  };
  const facts = n && claudeNodeFacts(n);
  const html = !ns.length
    // No node, or one that refused, and there is nowhere else: a session
    // runs on a node and this container carries no Claude Code. The reason,
    // and no choice under it: a menu with nothing in it would be a button
    // that lies.
    ? `<div class="rmstate bad">${esc(p.session_why)}</div>`
    // Several nodes are the house's node picker (nodePick, the node-switcher
    // rule), which holds any number of them; one where a session of yours
    // runs says so after its name.
    : `<div class="rmnode">${several ? `<div class="rmnodes">${nodePick("rmNodeSel",
          ns.map(x => ({id: x.id, name: runsOn(x) && mine.length ? `${x.name} · yours running` : x.name})), n.id)}</div>`
        + (facts ? `<div class="rmfacts">${esc(facts)}</div>` : "")
        : n.name ? `<div class="rmhead"><b>${esc(n.name)}</b>${facts ? `<span class="rmfacts">${esc(facts)}</span>` : ""}</div>` : ""}${
        mine.length ? `<div class="rmgroup"><div class="rmtitle">Yours here</div>${mine.map(runningLine).join("")}</div>` : ""}${
        n.where !== "node" ? `<div class="rmstate bad">${esc(n.why)}</div>`
          : `<div class="rmgroup"><div class="rmtitle">Start</div>${here().map(startLine).join("")}</div>
             <div class="rmgroup"><div class="rmtitle">Resume</div>${convs()}</div>`}</div>`;
  // The same menu as the one up already is left where it is (the operator,
  // 12 Oct): drawn again on every poll, its buttons were replaced under the
  // pointer and its entrance played again, so a press that began on one
  // button ended on another and did nothing, and it blinked.
  const was = card.querySelector(`.resumemenu[data-for="${CSS.escape(p.name)}"]:not([data-pick])`);
  if (was && was.dataset.sig === html) return;
  was?.remove();
  m.dataset.for = p.name;
  m.dataset.sig = html;
  m.innerHTML = html;
  card.appendChild(m);
  const nsel = m.querySelector("#rmNodeSel");
  if (nsel) nsel.onchange = () => { rmNode = {project: p.name, node: nsel.value}; placeResumeMenu(); };
  m.querySelectorAll("[data-signin-node]").forEach(b => b.onclick = () => {
    resumeFor = null;
    drawProjects(state.projects);
    openNodeClaude(b.dataset.signinNode);
  });
  const slotOf = b => +(b.dataset.slot || 1);
  const nodeBy = id => ns.find(x => x.id === id) || {id: "", name: ""};
  // New picked: the menu turns to the model and effort to start on, with
  // Start. A new project's first session goes to its brief instead, which
  // asks the same two beside the brief.
  m.querySelectorAll("[data-n]").forEach(b => b.onclick = () => {
    const node = b.dataset.node, slot = slotOf(b);
    if (p.brief && slot === 1 && !claudeLiveOn(p.name, {id: node || ""})) return startClaude(p.name, null, node);
    resumePick = {project: p.name, sessionId: null, node, slot, model: p.yours?.model || "", effort: p.yours?.effort || ""};
    drawProjects(state.projects);
  });
  m.querySelectorAll("[data-anew]").forEach(b => b.onclick = () => {
    const ag = b.dataset.anew, slot = slotOf(b);
    // A brief still waiting is the first prompt whichever agent starts.
    if (p.brief && slot === 1) return openBrief(p.name, b.dataset.node, ag);
    resumePick = {project: p.name, sessionId: null, node: b.dataset.node, agent: ag, slot,
                  model: p.yours?.[`${ag}_model`] || "", effort: p.yours?.[`${ag}_effort`] || ""};
    drawProjects(state.projects);
  });
  // A conversation picked to go on with: in the lowest slot of its agent
  // free, at the model and effort step.
  m.querySelectorAll("[data-cv]").forEach(b => b.onclick = () => {
    const ag = b.dataset.cvagent || "claude", slot = freeSlot(p.name, ag);
    if (!slot) return notify(`every ${agentById(ag).name} session you may run here is running: end one to resume this`, true);
    const claude = ag === "claude";
    resumePick = {project: p.name, sessionId: b.dataset.cv, when: +b.dataset.cvat, node: b.dataset.node, slot,
                  ...(claude ? {} : {agent: ag}),
                  model: p.yours?.[claude ? "model" : `${ag}_model`] || "", effort: p.yours?.[claude ? "effort" : `${ag}_effort`] || ""};
    drawProjects(state.projects);
  });
  m.querySelectorAll("[data-open]").forEach(b => b.onclick = () => launchClaude(p.name, null, b.dataset.node, slotOf(b)));
  m.querySelectorAll("[data-end]").forEach(b => b.onclick = () => claudeEnd(p.name, nodeBy(b.dataset.end), several, slotOf(b)));
  m.querySelectorAll("[data-restart]").forEach(b => b.onclick = () =>
    claudeRestart(p.name, nodeBy(b.dataset.restart), several, "claude", slotOf(b)));
  m.querySelectorAll("[data-aopen]").forEach(b => b.onclick = () =>
    launchAgent(b.dataset.aopen, p.name, b.dataset.node, "", "", "", slotOf(b)));
  m.querySelectorAll("[data-arestart]").forEach(b => b.onclick = () =>
    claudeRestart(p.name, nodeBy(b.dataset.nid), several, b.dataset.arestart, slotOf(b)));
  m.querySelectorAll("[data-aend]").forEach(b => b.onclick = () =>
    agentEnd(b.dataset.aend, p.name, nodeBy(b.dataset.nid), several, slotOf(b)));
  m.querySelectorAll("[data-asignin]").forEach(b => b.onclick = () => {
    resumeFor = null;
    drawProjects(state.projects);
    openNodeClaude(b.dataset.nid, b.dataset.asignin);
  });
  // Over the page under its button, above it near the screen's foot, a
  // sheet on a phone (floatAt), so it is never placed where it cannot be
  // seen: a chooser out of sight read as a press that did nothing (bug #65).
  floatAt(m, anchor);
}
