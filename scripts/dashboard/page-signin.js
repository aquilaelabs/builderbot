// The Claude sign-in, which is one account's on one node: who this account
// is signed in as there, the flow that signs that node in, the code a
// person pastes back into it, and signing that node out. Drawn inside the
// Claude section of the Agents page on that node (R95 step 15), and reached
// from a project's Claude button when its node has no sign-in yet.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- the Claude sign-in -------------------------------------------------

// Who this account is signed in to Claude as on a node, {email, plan}, or
// null. A report, from that node (claudegrant.py): the login itself is the
// machine's, and no other node's counts for it.
const claudeOn = nid => state?.claude_auth?.nodes?.[nid] || null;
// ...and to any coding agent (R95 step 3): Claude's from the record above,
// another agent's from the same record kept per agent.
const agentOn = (id, nid) => id === "claude" ? claudeOn(nid) : state?.agent_auth?.[id]?.nodes?.[nid] || null;

// What the sign-in has to say that the node list does not carry, as one
// string: the Nodes tab repaints when this moves as well as on its own
// revision, so a link arriving or a code being taken shows at once.
function signinRev(){
  const lg = state?.signin || {};
  return JSON.stringify([state?.claude_auth?.nodes || {}, state?.agent_auth || {}, lg.node, lg.agent, lg.running, lg.url, lg.code,
                         lg.waiting, lg.sent, lg.done, lg.ok, lg.error,
                         state?.can?.admin, claudeSessions().length]);
}

// The code being typed, kept here and not in the field: the tab repaints on
// every heartbeat, and a field that emptied itself under a thumb mid-paste
// is how this looked broken. Whether the field had the focus is kept the
// same way, from its own focus and blur.
let signinCode = "";
let signinHadFocus = false;
// What the last press on a node answered, when it was a refusal: on the
// row, not only in a toast.
let signinSaid = {};

// Why a sign-in cannot be made on this node now, or "": the server's own
// test (signin.cannot), said before the press.
function signinCannot(n, id = "claude"){
  if (n.state !== "online") return `${n.name} is ${n.state || "not online"} and takes no new work: sign in or out there when it is back online`;
  if (n.live === false) return `${n.name} is not answering: sign in or out there when it is back`;
  if (!n.reported?.session?.up) return `${n.name} runs no sessions, so there is nowhere for a ${agentById(id)?.name || "Claude"} login to live`;
  return "";
}

// This account's Claude sessions open on a node, as project names: signing
// out there pulls the ground from under them.
function signinBusy(n, id = "claude"){
  const open = new Set((state?.sessions || []).filter(s => s.node_id === n.id).map(s => s.name));
  return (state?.projects || []).filter(p => open.has(myAgentSession(id, p.name))).map(p => p.name);
}

// The sign-in's part of a node's Claude Code section. Every state is one
// action bar: what is so on its `.state` line, the press after it, and the
// reason a press is dead on a line of its own under it.
function signinBlock(n, id = "claude"){
  const me = agentOn(id, n.id), lg = state?.signin || {};
  const a = agentById(id) || AGENTS[0];
  const mine = lg.node === n.id && (lg.agent || "claude") === id;
  const cannot = signinCannot(n, id);
  const key = id === "claude" ? n.id : `${n.id}:${id}`;
  const said = signinSaid[key] ? `<div class="sub bad">${esc(signinSaid[key])}</div>` : "";
  let inner;
  if (mine && lg.running && !me && id !== "claude"){
    // A device flow (Codex, Copilot): its link and its one-time code, which
    // the person enters on the provider's page; nothing is pasted back.
    inner = `
      <div class="sub">${lg.url
        ? `<a href="${esc(lg.url)}" target="_blank" rel="noopener">Open the sign-in page ↗</a>, sign in to ${esc(a.provider)}, and enter this code there.`
        : `Starting the sign-in on ${esc(n.name)}<span class="dots"></span>`}</div>
      ${lg.code ? `<div class="field"><code class="sicode">${esc(lg.code)}</code></div>` : ""}
      <div class="actbar"><span class="state">${lg.code ? "waiting for you to enter the code" : "waiting for the link"}</span>
        <button type="button" class="stop" data-si="cancel">Cancel</button>
        <button type="button" data-si="in" title="start the sign-in again with a new code">Start over</button>
      </div>`;
  } else if (mine && lg.running && !me){
    inner = `
      <div class="sub">${lg.url
        ? `<a href="${esc(lg.url)}" target="_blank" rel="noopener">Open the sign-in page ↗</a>, approve, and paste the code it gives you.`
        : `Starting the sign-in on ${esc(n.name)}<span class="dots"></span>`}</div>
      <div class="setrow col ctlrow">${lbl("authCode", "Code", "the code the sign-in page shows once you approve")}
        <input id="authCode" autocomplete="off" spellcheck="false" autocapitalize="none"
          placeholder="paste the code here" aria-label="sign-in code"${lg.waiting ? "" : " disabled"}></div>
      <div class="actbar"><span class="state">${lg.sent ? "checking the code" : lg.waiting ? "waiting for the code" : "waiting for the link"}</span>
        <button type="button" class="stop" data-si="cancel">Cancel</button>
        <button type="button" data-si="in" title="start the sign-in again: the code from the one before it will not be accepted">Start over</button>
        <button type="button" class="primary" id="bAuthCode" data-si="code"${lg.waiting ? "" : " disabled"}>${lg.sent ? "Signing in" : "Send"}</button>
      </div>`;
  } else if (me){
    const busy = signinBusy(n, id);
    const dead = busy.length || cannot;
    inner = `
      <div class="actbar"><span class="state">You are signed in here as ${esc(me.email)}${me.plan ? ` · ${esc(me.plan)}` : ""}</span>
        <button type="button" data-si="out"${dead ? " disabled" : ""}>Sign out</button></div>
      ${busy.length ? `<div class="hint warn">End your ${esc(a.name)} session${busy.length === 1 ? "" : "s"} on ${esc(busy.join(", "))} before signing out here.</div>`
        : cannot ? `<div class="hint warn">${esc(cannot)}.</div>` : ""}`;
  } else {
    const failed = mine && lg.done && !lg.ok;
    inner = `
      <div class="actbar"><span class="state warn">You are not signed in to ${esc(a.name)} on ${esc(n.name)}: your ${esc(a.name)} sessions will not start here</span>
        <button type="button" class="primary" data-si="in"${cannot ? " disabled" : ""}>${failed ? "Try again" : "Sign in"}</button></div>
      ${cannot ? `<div class="hint warn">${esc(cannot)}.</div>`
        : failed ? `<div class="sub bad">${esc(lg.error || "the sign-in did not finish")}</div>` : ""}`;
  }
  return `<div class="ndsignin" data-signin="${esc(n.id)}" data-siagent="${esc(id)}">${inner}${said}
    <div class="hint">A sign-in is this node's alone: each node you work on is signed in from its own row.</div></div>`;
}

function wireSignin(root){
  root.querySelectorAll("[data-signin]").forEach(box => {
    const id = box.dataset.signin, ag = box.dataset.siagent || "claude";
    const f = box.querySelector("#authCode");
    if (f){
      f.value = signinCode;
      f.oninput = () => { signinCode = f.value; };
      f.onfocus = () => { signinHadFocus = true; };
      // Forgotten only when the person left the field, not when a repaint
      // took it away from under the caret: the browser fires blur for both,
      // and a moment later only the first is still in the page.
      f.onblur = () => setTimeout(() => { if (f.isConnected) signinHadFocus = false; }, 0);
      f.onkeydown = e => { if (e.key === "Enter"){ e.preventDefault(); sendCode(); } };
      // Restoring focus, not taking it: the row was rebuilt under someone
      // who was already typing in this field, and only they put it there.
      if (signinHadFocus && !f.disabled) f.focus();
    }
    box.querySelectorAll("[data-si]").forEach(b => b.onclick = () => ({
      in: () => signIn(id, b, ag), out: () => signOut(id, b, ag), code: () => sendCode(),
      cancel: () => signinCancel(b)})[b.dataset.si]());
  });
}

// Open the Agents page on one node with its Claude section unfolded and in
// view: where a Claude button sends its press when that node has no sign-in
// of this account's yet.
function openNodeClaude(nodeId){
  // The Agents page on that node (R95 step 15), its Claude section open.
  sectOpen["agents:claude"] = true;
  openAgentsOn(nodeId);
  const show = (tries) => {
    const s = document.querySelector(`.agentstab [data-agnode="${CSS.escape(nodeId)}"] [data-sect="agents:claude"]`);
    if (s) return s.scrollIntoView({block: "start", behavior: "smooth"});
    if (tries > 0) setTimeout(() => show(tries - 1), 150);
  };
  show(40);
}

// Sign in on one node, however many times it takes. No terminal: the flow
// runs under a pty on the NODE (which is where Claude Code is installed)
// and its row does the rest, so this is one request from here. The answer
// is read: a refusal is said on the row, since a press that changes nothing
// repaints nothing.
async function signIn(nodeId, btn, id = "claude"){
  busy(btn, "Starting");
  signinCode = "";
  let j = {};
  try{
    const r = await postJSON("/api/signin", {node: nodeId, agent: id});
    j = await r.json();
  }catch(e){ j = {error: "could not reach the server: " + e}; }
  signinSaid[id === "claude" ? nodeId : `${nodeId}:${id}`] = j.error || "";
  if (j.error) notify(j.error, true);
  await refresh();
  nodesRev++; drawPanes();
}

async function signinCancel(btn){
  busy(btn, "Stopping");
  try{ await postJSON("/api/signin", {action: "cancel"}); }
  catch(e){ notify("could not reach the server: " + e, true); }
  signinCode = "";
  await refresh();
  nodesRev++; drawPanes();
}

// While a sign-in is going, its row is worth more than one look every
// fifteen seconds: the URL arrives a second in, and the answer to the code
// lands a second after it is sent. Stops the moment there is nothing running.
let signinTimer = null;
function watchSignin(){
  const lg = state?.signin;
  const live = !!lg?.running;
  if (live && !signinTimer) signinTimer = setInterval(() => refresh(), 1200);
  if (!live && signinTimer){ clearInterval(signinTimer); signinTimer = null; }
}

// The code from the browser, handed to the flow on the node: the two steps
// a phone is worst at are the two this takes off it.
async function sendCode(){
  const f = document.getElementById("authCode"), b = document.getElementById("bAuthCode");
  const code = (f?.value || "").trim();
  if (!code) return f?.focus();   // pressed Send with nothing in it
  busy(b, "Sending");
  try{
    const r = await postJSON("/api/login-code", {code});
    const j = await r.json();
    if (j.error) notify(j.error, true);
    else { signinCode = ""; notify("sent: the row says what the sign-in makes of it"); }
  }catch(e){ notify("could not reach the server: " + e, true); }
  await refresh();
  nodesRev++; drawPanes();
}

// Sign this account out on one node. The login is that machine's, so the
// machine is asked to let go of it; another node's is untouched.
async function signOut(nodeId, btn, id = "claude"){
  const n = (nodesList || []).find(x => x.id === nodeId);
  const a = agentById(id) || AGENTS[0];
  if (!confirm(`Sign out of ${a.name} on ${n?.name || "this node"}?\n\nYour ${a.name} sessions stop working there until you sign in again. Your sign-in on any other node stays.`)) return;
  busy(btn, "Signing out");
  let j = {};
  try{
    const r = await postJSON("/api/signout", {node: nodeId, agent: id});
    j = await r.json();
  }catch(e){ j = {error: "could not reach the server: " + e}; }
  signinSaid[id === "claude" ? nodeId : `${nodeId}:${id}`] = j.error || "";
  if (j.error) notify(j.error, true);
  else notify(`signed out on ${j.on || "the node"}`);
  await refresh();
  nodesRev++; drawPanes();
}
