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
const claudeLiveOn = (name, n) => (state?.sessions || []).some(s => s.name === myClaude(name)
  && (!n.id || s.node_id === n.id));

// End this account's session of a project on one node, asked first, and
// drop its tab: the chooser's End session.
async function claudeEnd(name, n, several){
  const where = n.name ? ` on ${n.name}` : "";
  if (!confirm(`End your Claude session on ${projLabel(name)}${where}?\n\nThe transcript is kept and can be resumed later, but the conversation stops now.`)) return;
  resumeFor = null;
  if (state) drawProjects(state.projects);
  try{
    const j = await endSession(myClaude(name), n.id);
    if (j.error) return notify(j.error, true);
    const arg = `claude:${name}` + (several && n.id ? `:n:${n.id}` : "");
    const t = tabs.find(x => x.kind === "term" && String(x.arg).replace(/:r:[^:]*/, "") === arg);
    if (t) dropTab(t.id);
    notify(`ended your Claude session on ${projLabel(name)}${where}`);
  }catch(e){ notify("could not end it: " + e, true); }
  refresh();
}

// Restart (the operator, 12 Oct): end the session and pick its conversation
// up again, which is how a session sees what changed since it started (a
// toolchain on its node's PATH, BuilderBot's briefing; the project row says
// which). The menu turns to the model and effort first, the conversation it
// was in already chosen; its Restart asks, and only then is the session
// ended and started again (restartNow). Asked first and ended at once, it
// left a person picking a model with no session running.
function claudeRestart(name, n, several){
  const p = (state?.projects || []).find(x => x.name === name);
  resumeFor = name;
  resumePick = {project: name, sessionId: p?.last_claude?.id || null, node: several ? n.id : "",
                model: p?.yours?.model || "", effort: p?.yours?.effort || "",
                restart: {id: n.id || "", name: n.name || "", several: !!several}};
  if (state) drawProjects(state.projects);
}

// The restart itself, once the model and effort are picked and the person
// said yes: end the session, wait until the controller no longer lists it,
// then start the same conversation. Started while the old one was still
// going down, the new tab attached to the dying session and showed it end,
// and a second press was what got a session (the operator, 12 Oct).
async function restartNow(name, r){
  const n = r.restart;
  const where = n.name ? ` on ${n.name}` : "";
  const j = await endSession(myClaude(name), n.id).catch(e => ({error: String(e)}));
  if (j.error) return j.error;
  const arg = `claude:${name}` + (n.several && n.id ? `:n:${n.id}` : "");
  const t = tabs.find(x => x.kind === "term" && String(x.arg).replace(/:r:[^:]*/, "") === arg);
  if (t) dropTab(t.id);
  for (let i = 0; i < 40 && claudeLiveOn(name, {id: n.id}); i++){
    await new Promise(res => setTimeout(res, 500));
    await refresh();
  }
  if (claudeLiveOn(name, {id: n.id}))
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
  drawProjects(state.projects);
  syncResumeMenu();
}

// One conversation picked to go on with (the notebook's Sessions view, the
// operator, 22 Oct: the project's Claude button resumes only the last): the
// chooser opens on it at the model and effort step. With a session of yours
// running here it is a restart into that conversation, which ends the one
// running first and asks before it does.
function resumeConversation(name, id, when, ev){
  const p = (state?.projects || []).find(x => x.name === name);
  if (!p) return;
  const ns = claudeNodes(p), several = ns.length > 1;
  const live = ns.find(n => claudeLiveOn(name, {id: n.id}));
  resumeFor = name;
  // The press goes no further: the page's click-away closes the chooser,
  // as the Claude button's own press keeps it open (openClaude).
  ev?.stopPropagation();
  // Under the project's own Start Claude where it is on show (the notebook's
  // header), not the box the row's button sits in, which holds no Start.
  resumeHost = null;
  resumePick = {project: name, sessionId: id, when, node: live && several ? live.id : "",
                model: p.yours?.model || "", effort: p.yours?.effort || "",
                ...(live ? {restart: {id: live.id || "", name: live.name || "", several}} : {})};
  drawProjects(state.projects);
  syncResumeMenu();
  // Nowhere to start it (placeResumeMenu found no Start Claude to open under):
  // said, rather than a press that does nothing.
  if (resumeFor !== name)
    notify(claudeInstall(p) ? `Claude Code is not installed on ${p.node_name || "this project's node"}: install it from its Toolchains, then resume`
      : "a session cannot start on this project now: its Start Claude says why", true);
}

// A button that sends something to a project's Claude session asks first
// (the operator, 6 Oct): what it sends arrives as a prompt and Claude starts
// on it at once, so a stray tap is work begun. The bug and roadmap sends ask
// in their own send box; every other Send to Claude asks here.
function sendSure(project, what){
  return confirm(`Send ${what} to ${projLabel(project)}'s Claude session?\n\n`
                 + "It arrives as a prompt, and Claude starts on it at once.");
}

// A new project's first session goes through its brief's dialog: a new
// conversation (no transcript picked), nothing running, and a brief still
// waiting in the tree (brief.py). Everything else starts at once.
function startClaude(name, sessionId, node){
  const p = (state?.projects || []).find(x => x.name === name);
  if (claudeSigninFirst(name, node || p?.session_node || "")) return;
  if (!sessionId && p?.brief && !claudeLiveOn(name, {id: node || ""}))
    return openBrief(name, node || "");
  launchClaude(name, sessionId, node);
}

function launchClaude(name, sessionId, node){
  resumeFor = null;
  resumePick = null;
  // Redraw the card, not just the tabs: the chooser is a child of it and would
  // otherwise sit there until the next poll, over a choice already made.
  if (state) drawProjects(state.projects);
  const p = (state?.projects || []).find(x => x.name === name);
  const nn = node ? (p?.session_nodes || []).find(x => x.id === node)?.name || node : "";
  openTab({kind:"term",
           arg: `claude:${name}` + (sessionId ? `:r:${sessionId}` : "") + (node ? `:n:${node}` : ""),
           label: `Claude: ${projLabel(name)}` + (nn ? ` (${nn})` : "")});
}

// ---- a new project's first session ------------------------------------------
// The brief the project was made with, editable, and the model and effort the
// session starts on, since nothing has started yet. Build it stages the brief
// for this account and opens the session, which takes it as its first prompt
// as it starts; Start without it opens one that was not given it and puts the
// brief away. Either way the brief leaves the project's tree then, and its
// notebook keeps it.
let briefFor = null;

async function openBrief(name, node){
  resumeFor = null;
  if (state) drawProjects(state.projects);
  briefFor = {name, node};
  const p = (state?.projects || []).find(x => x.name === name);
  $("briefTitle").textContent = `First session on ${projLabel(name)}`;
  $("briefErrWrap").hidden = true;
  $("briefText").value = "";
  for (const [id, table, cur] of [["briefModel", MODELS, p?.yours?.model || ""],
                                  ["briefEffort", EFFORTS, p?.yours?.effort || ""]]){
    $(id).innerHTML = optionList(table, cur);
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
    if (model !== (p?.yours?.model || "") || effort !== (p?.yours?.effort || "")){
      const j = await (await postJSON("/api/prefs", {project: f.name, model, effort})).json();
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
  launchClaude(f.name, null, f.node);
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
  const opts = (table, cur) => table.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${
    esc(v === "" && table === MODELS && resumeModelNow.project === p.name && resumeModelNow.model
      ? `Claude's default (last session: ${(MODELS.find(([x]) => x === resumeModelNow.model) || [])[1] || resumeModelNow.model})` : l)}</option>`).join("");
  // What it will do as its head, the two picks labeled above their fields
  // side by side, and Back and the press at its foot (the design 2.0 pass).
  m.innerHTML = `<div class="rmhead"><b>${r.restart ? "Restart your session"
      : r.sessionId ? "Resume the conversation" : "A new conversation"}</b><span class="rmfacts">${
      r.restart ? (r.when ? `ending the one running, resuming the one from ${esc(ago(r.when))}` : "resuming its conversation")
        : r.sessionId ? `from ${esc(ago(r.when ?? p.last_claude?.when))}` : "a fresh start"}${
      several || n.name ? ` on ${esc(n.name || "")}` : ""}</span></div>
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
    if (r.restart && !confirm(`Restart your Claude session on ${projLabel(p.name)}${r.restart.name ? ` on ${r.restart.name}` : ""}?\n\n`
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
    startClaude(p.name, r.sessionId, r.node);
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
  // What one node offers: Open tab and End session where this account's
  // session runs there; its sign-in where this account has none there;
  // else Resume and New conversation, or the one press when there is
  // nothing to resume; and only its reason where a session cannot start.
  const offer = n => {
    const node = several ? n.id : "";
    // In one action bar (the design 2.0 pass, the operator, 17 Oct): Open
    // tab the filled press, Restart plain since it resumes, End session the
    // one destructive verb and last.
    const bar = html => `<div class="actbar rmacts">${html}</div>`;
    if (claudeLiveOn(p.name, n))
      return bar(`<button data-open="1" data-node="${esc(node)}" class="primary">Open tab</button>`
        + `<button data-restart="${esc(n.id)}">Restart</button>`
        + `<button data-end="${esc(n.id)}" class="danger">End session</button>`);
    if (n.where !== "node") return `<div class="rmstate bad">${esc(n.why)}</div>`;
    if (!claudeSigned(n))
      return bar(`<button data-signin-node="${esc(n.id)}" title="opens ${esc(n.name)} on the Nodes page, at its Claude sign-in">Sign in on ${esc(n.name)}</button>`);
    return bar((p.last_claude ? `<button data-r="1" data-node="${esc(node)}">Resume: ${esc(ago(p.last_claude.when))}</button>` : "")
      + `<button data-n="1" data-node="${esc(node)}"${p.last_claude ? "" : ' class="primary"'}>New conversation</button>`);
  };
  // A node's head: its name, and what it has on a quiet line under it.
  const head = n => `<div class="rmhead"><b>${esc(n.name || "")}</b>${
      claudeNodeFacts(n) ? `<span class="rmfacts">${esc(claudeNodeFacts(n))}</span>` : ""}</div>`;
  const html = !ns.length
    // No node, or one that refused, and there is nowhere else: a session
    // runs on a node and this container carries no Claude Code. The reason,
    // and no choice under it: a menu with nothing in it would be a button
    // that lies.
    ? `<div class="rmstate bad">${esc(p.session_why)}</div>`
    // Each node (several under R82, or the one): its head, how this account
    // stands there, and what it offers.
    : ns.map(n => `<div class="rmnode">${n.name ? head(n) : ""}${
        claudeLiveOn(p.name, n) ? `<div class="rmstate ok">Your session is running here</div>`
        : n.where === "node" && !claudeSigned(n) ? `<div class="rmstate">You are not signed in to Claude here</div>` : ""}${
        offer(n)}</div>`).join("");
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
  m.querySelectorAll("[data-signin-node]").forEach(b => b.onclick = () => {
    resumeFor = null;
    drawProjects(state.projects);
    openNodeClaude(b.dataset.signinNode);
  });
  // Resume or New conversation picked: the menu turns to the model and
  // effort to start on, with Start. A new project's first session goes to
  // its brief instead, which asks the same two beside the brief.
  const pick = (sessionId, node) => {
    if (!sessionId && p.brief && !claudeLiveOn(p.name, {id: node || ""})) return startClaude(p.name, null, node);
    resumePick = {project: p.name, sessionId, node, model: p.yours?.model || "", effort: p.yours?.effort || ""};
    drawProjects(state.projects);
  };
  m.querySelectorAll("[data-r]").forEach(b => b.onclick = () => pick(p.last_claude.id, b.dataset.node));
  m.querySelectorAll("[data-n]").forEach(b => b.onclick = () => pick(null, b.dataset.node));
  m.querySelectorAll("[data-open]").forEach(b => b.onclick = () => launchClaude(p.name, null, b.dataset.node));
  m.querySelectorAll("[data-end]").forEach(b => b.onclick = () =>
    claudeEnd(p.name, ns.find(n => n.id === b.dataset.end) || {id: "", name: ""}, several));
  m.querySelectorAll("[data-restart]").forEach(b => b.onclick = () =>
    claudeRestart(p.name, ns.find(n => n.id === b.dataset.restart) || {id: "", name: ""}, several));
  // Over the page under its button, above it near the screen's foot, a
  // sheet on a phone (floatAt), so it is never placed where it cannot be
  // seen: a chooser out of sight read as a press that did nothing (bug #65).
  floatAt(m, anchor);
}
