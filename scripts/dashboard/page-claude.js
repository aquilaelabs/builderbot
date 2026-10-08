// A Claude session, started: which of the project's nodes it runs on, what
// each node has, whether it resumes a conversation or starts a fresh one,
// and the way to a node's sign-in where this account has none there, all
// from the chooser the Claude button opens.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- a Claude session: which node, and resume or fresh ------------------

// Which project's chooser is open, if any.
let resumeFor = null;

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
  const asks = !!p?.session_why || ns.length > 1 || !!p?.last_claude
    || liveSessions().has(myClaude(name))
    || ns.some(n => n.where === "node" && !claudeSigned(n));
  if (!asks){
    resumeFor = null;
    return startClaude(name, null, "");
  }
  resumeFor = resumeFor === name ? null : name;
  drawProjects(state.projects);
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
    $(id).innerHTML = table.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
    $(id).value = cur;
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

function placeResumeMenu(){
  const p = (state?.projects || []).find(x => x.name === resumeFor);
  const anchor = $("projects").querySelector(`[data-c="${CSS.escape(resumeFor)}"]`);
  const ns = claudeNodes(p), several = ns.length > 1;
  if (!p || !anchor){ resumeFor = null; return; }
  const card = anchor.closest(".card");
  const m = document.createElement("div");
  m.className = "pinmenu resumemenu";
  m.id = "resumemenu";
  // What one node offers: Open tab and End session where this account's
  // session runs there; its sign-in where this account has none there;
  // else Resume and New conversation, or the one press when there is
  // nothing to resume; and only its reason where a session cannot start.
  const offer = n => {
    const node = several ? n.id : "";
    if (claudeLiveOn(p.name, n))
      return `<button data-open="1" data-node="${esc(node)}" class="primary">Open tab</button>`
        + `<button data-end="${esc(n.id)}" class="danger">End session</button>`;
    if (n.where !== "node") return `<div class="sub bad">${esc(shortWhy(n.why))}</div>`;
    if (!claudeSigned(n))
      return `<button data-signin-node="${esc(n.id)}" title="opens ${esc(n.name)} on the Nodes tab, at its Claude sign-in">Sign in on ${esc(n.name)}</button>`;
    return (p.last_claude ? `<button data-r="1" data-node="${esc(node)}">Resume: ${esc(ago(p.last_claude.when))}</button>` : "")
      + `<button data-n="1" data-node="${esc(node)}">New conversation</button>`;
  };
  m.innerHTML = !ns.length
    // No node, or one that refused, and there is nowhere else: a session
    // runs on a node and this container carries no Claude Code. The reason,
    // and no choice under it: a menu with nothing in it would be a button
    // that lies.
    ? `<div class="sub">${esc(p.session_why)}</div>`
    // Several nodes (R82): each under its name and what it has.
    : several ? ns.map(n => `<div class="sub">${esc(n.name)}${
        claudeNodeFacts(n) ? ` <span class="dim">${esc(claudeNodeFacts(n))}</span>` : ""}${
        claudeLiveOn(p.name, n) ? ` · your session is running here`
        : n.where === "node" && !claudeSigned(n) ? ` · you are not signed in there` : ""}</div>${offer(n)}`).join("")
    // One node: its name and what it has, as each of several gets.
    : (ns[0].name ? `<div class="sub">${esc(ns[0].name)}${
        claudeNodeFacts(ns[0]) ? ` <span class="dim">${esc(claudeNodeFacts(ns[0]))}</span>` : ""}</div>` : "")
      + (claudeLiveOn(p.name, ns[0]) ? `<div class="sub">Your session is running here.</div>`
       : claudeSigned(ns[0]) ? "" : `<div class="sub">You are not signed in to Claude here.</div>`) + offer(ns[0]);
  card.appendChild(m);
  m.querySelectorAll("[data-signin-node]").forEach(b => b.onclick = () => {
    resumeFor = null;
    drawProjects(state.projects);
    openNodeClaude(b.dataset.signinNode);
  });
  m.querySelectorAll("[data-r]").forEach(b => b.onclick = () => startClaude(p.name, p.last_claude.id, b.dataset.node));
  m.querySelectorAll("[data-n]").forEach(b => b.onclick = () => startClaude(p.name, null, b.dataset.node));
  m.querySelectorAll("[data-open]").forEach(b => b.onclick = () => launchClaude(p.name, null, b.dataset.node));
  m.querySelectorAll("[data-end]").forEach(b => b.onclick = () =>
    claudeEnd(p.name, ns.find(n => n.id === b.dataset.end) || {id: "", name: ""}, several));
  const a = anchor.getBoundingClientRect(), c = card.getBoundingClientRect();
  m.style.left = Math.max(4, Math.min(a.left - c.left, c.width - m.offsetWidth - 4)) + "px";
  m.style.top = (a.bottom - c.top + 4) + "px";
  // ...and brought into the sidebar, which scrolls. Pressing Claude on a
  // project whose session has ENDED opens this chooser instead of a tab;
  // that is the design, and it is the only thing the press does, so a
  // chooser placed below the fold is a press with no visible result. Reported
  // as "opened Claude again and it did not go to the new tab" (bug #65).
  // Same rule and the same fix as the notebook's view strip: arriving
  // somewhere you cannot see reads as nothing having happened.
  //
  // Measured at rest. scrollIntoView reads the box where it is, and where it
  // is right now is menuIn's first frame, 5px above where it will settle,
  // so aligning that box left the settled chooser 5px below the fold (B77).
  // Finish the entrance for the measurement and play it again from the start.
  const enter = m.getAnimations()[0];
  enter?.finish();
  m.scrollIntoView({block: "nearest", inline: "nearest"});
  enter?.play();
}
