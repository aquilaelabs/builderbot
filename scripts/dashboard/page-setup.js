"use strict";
// ---- first run: the setup page (R199, R267) ---------------------------------
//
// After the owner is made, the page is this until Finish: the four things a
// new owner has to do, each a card with its state and its own action, at the
// page's reading width with nothing beside it (the operator, 18 Oct: the
// panel over half a Nodes page, six storage paths and an idle timeout ahead
// of the one step that blocks, read as anything but a start). A node first,
// which cannot wait: nothing runs without one (the operator, 12 Oct), and
// Finish is refused by the server too until one is enrolled and answering.
// Then the owner's name and email, which every commit carries; Claude Code
// on that node; and a first project. Those three can wait: Home keeps them
// in its Getting started card until they are done. Where what grows is kept
// and when an idle session ends have working defaults, under Controller
// settings, and are not asked here.

let setupSig = "", setupNodesAt = 0;

function setupNeeded(){
  return state?.settings?.settings?.setup_done?.value === false;
}

// A node enrolled, answering and running sessions, from the Nodes tab's
// list. Not a hosting-only one: it holds no code and runs no sessions, so a
// project has nowhere to work or to build its container (the operator,
// 12 Oct). That is also why the first node reaches the controller over the
// LAN or WireGuard, never only through a public hostname.
function setupNode(){
  return (nodesList || []).find(n => n.kind === "agent" && n.state === "online" && n.live !== false
                                     && !n.config?.host_only) || null;
}

// Where each of the four stands, read from what the page already holds: the
// nodes list, the status read's git_ready and projects. Home's Getting
// started card reads the same, so the two never disagree.
function setupSteps(){
  const node = setupNode();
  const waiting = !node && (nodesList || []).find(n => n.kind === "agent" && n.state !== "retired" && !n.config?.host_only);
  const claude = node?.reported?.session?.claude || "";
  return {
    node, waiting,
    git: state?.git_ready !== false,
    claude,
    project: (state?.projects || []).length > 0,
  };
}

function drawSetup(){
  const on = setupNeeded();
  document.body.classList.toggle("firstrun", on);
  const el = $("setupPanel");
  if (!on){
    if (!el.hidden){ el.hidden = true; el.innerHTML = ""; setupSig = ""; }
    return;
  }
  el.hidden = false;
  // The nodes list is the node step's whole state, and no page that reads it
  // is open while this is: asked again every few seconds, so a machine that
  // dials in turns its card to done without a reload.
  if (Date.now() - setupNodesAt > 5000){
    setupNodesAt = Date.now();
    loadNodes().then(() => drawSetup());
  }
  const s = setupSteps();
  // Drawn again only when what it shows has moved: a poll landing mid-type
  // would otherwise take what was typed with it.
  const sig = JSON.stringify([s.node?.name || "", s.waiting?.name || "", s.git, s.claude, s.project]);
  if (sig === setupSig) return;
  setupSig = sig;
  const pill = (done, wait) => done ? `<span class="pill ok">done</span>`
    : wait ? `<span class="pill note">waiting</span>` : `<span class="pill">to do</span>`;
  const card = (n, title, done, wait, body, acts = "") => `<section class="setstep${done ? " done" : ""}">
      <div class="setstephead"><span class="setnum">${n}</span><h3>${esc(title)}</h3>${pill(done, wait)}</div>
      <div class="setstepbody">${body}</div>${acts ? `<div class="actbar">${acts}</div>` : ""}</section>`;
  const nodeName = s.node ? esc(s.node.name) : "";
  el.innerHTML = `<div class="setuppage">
    <div class="setuphead">
      <h2>Set up BuilderBot</h2>
      <p>BuilderBot works on nodes: machines you enroll, where projects are kept, built and worked on. One is all it needs to start.</p>
    </div>
    ${card(1, "Your first node", !!s.node, !!s.waiting, s.node
      ? `<p><b>${nodeName}</b> is enrolled and answering.</p>`
      : s.waiting
      ? `<p>Waiting for <b>${esc(s.waiting.name)}</b> to dial in: run its enroll script on the machine. This turns to done by itself.</p>`
      : `<p>A sandbox VM made for it, or a machine you already have, on this network or reached over the internet.</p>${deadWhy(featureOff("enroll"))}`,
      s.node ? "" : `<button type="button" data-setvm${featureOff("enroll") ? " disabled" : ""}>Create sandbox VM</button><button type="button" class="primary" data-setenroll${featureOff("enroll") ? " disabled" : ""}>Enroll node</button>`)}
    ${card(2, "Your name and email", s.git, false, s.git
      ? `<p>Your commits carry them. Your profile, in the gear, changes them.</p>`
      : `<p>Every commit carries an author, and no Claude session starts without one.</p>
         <div class="setfields"><div class="setrow col ctlrow">${lbl("setName", "Your name")}<input id="setName" type="text" autocomplete="name" placeholder="Ada Lovelace"></div>
           <div class="setrow col ctlrow">${lbl("setEmail", "Your email")}<input id="setEmail" type="email" autocomplete="email" placeholder="ada@example.com"></div></div>`,
      s.git ? "" : `<button type="button" class="primary" data-setgit disabled>Save</button>`)}
    ${card(3, "Claude Code on your node", !!s.claude, false, s.claude
      ? `<p>${esc(s.claude)} on ${nodeName}. A project's Start agent signs you in there the first time.</p>`
      : s.node
      ? `<p>What a Claude session on ${nodeName} runs. It installs as a job on the node, a minute or two.</p>`
      : `<p>What a Claude session runs, installed on the node.</p><div class="sub bad setwhy">Once your node answers.</div>`,
      s.claude ? "" : `<button type="button" class="primary" data-setclaude${s.node ? "" : " disabled"}>Install</button>`)}
    ${card(4, "A first project", s.project, false, s.project
      ? `<p>The Projects page holds it, and every one after it.</p>`
      : `<p>A repository to work on: a new one, or one cloned from GitHub or Gitea.</p>`,
      s.project ? "" : `<button type="button" data-setproject>New project</button>`)}
    <div class="setfinish">
      <p class="dim">${s.node ? "Steps 2 to 4 can wait: Home keeps them until they are done." : "Finish opens once your node answers."}
        Storage and the idle timeout have working defaults, under Controller settings.</p>
      <div class="actbar"><button type="button" class="primary" id="setupFinish"${s.node ? "" : " disabled"}>Finish</button></div>
      <div class="hint bad" id="setupWhy" hidden></div>
    </div>
  </div>`;
  wireSetup(el, s);
}

function wireSetup(el, s){
  const vm = el.querySelector("[data-setvm]"), en = el.querySelector("[data-setenroll]");
  if (vm) vm.onclick = () => ndDialogs().openVm();
  if (en) en.onclick = () => ndDialogs().openEnroll();
  const name = el.querySelector("#setName"), email = el.querySelector("#setEmail"), git = el.querySelector("[data-setgit]");
  // Save wakes once there is a name and an email that reads as one.
  const ready = () => { if (git) git.disabled = !(name.value.trim() && email.value.trim() && email.checkValidity()); };
  if (name && email){ name.oninput = ready; email.oninput = ready; }
  if (git) git.onclick = async () => {
    busy(git, "Saving");
    const j = await (await postJSON("/api/profile", {action: "save", profile: {full_name: name.value.trim(), email: email.value.trim()}}))
      .json().catch(() => ({error: "no answer from the dashboard"}));
    if (j.error){ unbusy(git, "Save"); return notify(j.error, true); }
    refresh();
  };
  const cl = el.querySelector("[data-setclaude]");
  if (cl) cl.onclick = async () => {
    busy(cl, "Starting");
    const r = await postJSON("/api/agents", {action: "install", agent: "claude", node: s.node.id});
    const j = await r.json().catch(() => ({}));
    if (!r.ok){ unbusy(cl, "Install"); return notify(j.error || `could not start (HTTP ${r.status})`, true); }
    notifyJob(j.job, `installing Claude Code on ${s.node.name}`);
    // It turns to done when the node's census reports the version.
    busy(cl, "Installing");
  };
  const np = el.querySelector("[data-setproject]");
  if (np) np.onclick = () => openNewProject();
  $("setupFinish").onclick = setupFinish;
}

async function setupFinish(){
  const btn = $("setupFinish"), why = $("setupWhy");
  busy(btn, "Finishing");
  let j;
  try{
    j = await (await postJSON("/api/settings", {set: {setup_done: true}})).json();
  }catch{ j = {error: "no answer from the dashboard"}; }
  if (j.error){
    unbusy(btn, "Finish");
    why.textContent = j.error;
    why.hidden = false;
    return;
  }
  setupSig = "";
  // Home, where what is left of the four waits in its Getting started card.
  location.hash = "#/home";
  refresh();
}
