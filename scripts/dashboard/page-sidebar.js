// What a project offers wherever it is met (the Projects page's cards and a
// project's page): its controls, why it is held, its lock and its pin, its
// one clone or first-push job. Named for the sidebar the rows were first
// drawn in.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

// What gets folded away is what the button says: projects with an *error*, and
// ones the operator has locked. A warning is not an error: a repo with no
// CLAUDE.md still works, and hiding it would bury the very thing the amber
// text is asking for. The only thing
// never listed at all is an empty directory, which the server drops: it is not
// a problem to fix but a mount point waiting for content.
const isBroken = p => p.issues.some(i => i.level === "error");

// Why no Claude session may run on this project right now, from the server:
// its own node's agent from another compatibility window than this
// BuilderBot (the briefing is assembled per session since R63 step 3, so
// nothing in the tree can be). Drift INSIDE the window (the agent behind
// on a build) is not here: the row offers the update and the button stays
// live. Across a window the promise was never
// made, so the button waits for the press, bb-tty refuses the URL, and the
// server ends what is running. Per project: another project's node being
// out of window is that row's hold, not this one's.
// ...and a session that is ALREADY RUNNING is reached, not started: the same
// button goes to its tab, and stranding somebody from a live conversation
// over a missing author would be a worse fault than the one this prevents.
// The ROW's answer, not the account's: somebody whose Profile carries no
// email can set one for this project alone, and then this project is ready
// while the others are not.
const gitReadyFor = p => (p.git_ready !== undefined ? p.git_ready : state?.git_ready) !== false;
const heldWhy = p => p.held || (!gitReadyFor(p) && !myLiveSession(p.name)
  ? "set your commit name and email on your Profile (the gear) or in this project's settings first"
  : "");

// The handlers for projectActions' buttons, one list for the Projects page's
// cards and a project's header: a second copy of it is how one of them
// quietly stops offering a control.
function wireProjectRows(root){
  root.querySelectorAll("[data-c]").forEach(b => b.onclick = e => openClaude(b.dataset.c, e));
  root.querySelectorAll("[data-s]").forEach(b => b.onclick = () => newShell(b.dataset.s));
  // Install opens the Library on the node at that agent's card, where it is installed (R95, R170).
  root.querySelectorAll("[data-tcinst]").forEach(b => b.onclick = () => openLibraryOn(b.dataset.tcinst, b.dataset.agent || "claude"));
  // The chain is the remote, whichever state the project is in: linking one
  // that has no remote, and the credential half (and the way off it) for
  // one that has.
  root.querySelectorAll("[data-l]").forEach(b => b.onclick = () => {
    const p = (state?.projects || []).find(x => x.name === b.dataset.l);
    if (p?.linked) renameProject(b.dataset.l, "git");
    else openLinkProject(b.dataset.l);
  });
  root.querySelectorAll("[data-m]").forEach(b => b.onclick = () => openNotebook(b.dataset.m));
  root.querySelectorAll("[data-k]").forEach(b => b.onclick = () =>
    setArchived(b.dataset.k, b.dataset.on === "1"));
  root.querySelectorAll("[data-lock]").forEach(b => b.onclick = () =>
    setLocked(b.dataset.lock, b.dataset.on === "1"));
  root.querySelectorAll("[data-p]").forEach(b => b.onclick = () =>
    setProjectPinned(b.dataset.p, b.dataset.on === "1"));
  root.querySelectorAll("[data-pgroup]").forEach(b => b.onclick = () => askProjectGroup(b));
  root.querySelectorAll("[data-pcolor]").forEach(b => b.onclick = () => pickProjectColor(b));
  root.querySelectorAll("[data-rn]").forEach(b => b.onclick = () =>
    openProjectSettings(b.dataset.rn));
  // From any of a project's repositories, with the others to pick from.
  root.querySelectorAll("[data-bug]").forEach(b => b.onclick = () =>
    openReport(b.dataset.bug, state?.repos?.[reposOf(b.dataset.bug)]?.members || []));
  root.querySelectorAll("[data-ph]").forEach(b => b.onclick = e => phoneRowPress(b, e));
  root.querySelectorAll("[data-del]").forEach(b => b.onclick = () =>
    deleteProject(b.dataset.del));
}

// ---- a phone, from a project's row (R120) -----------------------------------
// A phone is the person's who connected it, and only they lend it to a
// project: the row's Phone button is live for exactly them, on a project
// whose node their phone is on. Lent here, it takes it back. Everybody else
// sees why it is not theirs on its tip, and the lease on the row's line.
function phoneWhy(p){
  const ph = p.phone;
  if (!p.node_name) return "no node: a phone is connected on a project's node, and this one has none";
  if (!ph) return `no phone is connected on ${p.node_name}: connect yours in the Phone page, on that node`;
  if (!ph.mine) return `the phone on ${p.node_name} is ${ph.owner}'s: only they lend it`;
  if (ph.lease && ph.lease.project !== p.name) return `your phone is lent to ${projLabel(ph.lease.project)}: take it back there first`;
  return "";
}
async function phoneRowPress(b, e){
  e.stopPropagation();
  const p = (state?.projects || []).find(x => x.name === b.dataset.ph);
  if (!p?.phone?.mine) return;
  const nid = p.phone.node || "";
  const post = async body => {
    busy(b, "");
    try{
      const j = await (await postJSON("/api/phone", body)).json();
      if (j.error) notify(j.error, true);
      else notify(body.action === "lend" ? `your phone is lent to ${projLabel(p.name)}: each command asks you` : `your phone is back from ${projLabel(p.name)}`);
    }catch(err){ notify("could not reach the controller: " + err, true); }
    unbusy(b);
    refresh();
  };
  if (p.phone.lease?.project === p.name){
    if (await askYes(`Take your phone back from ${projLabel(p.name)}? Its session stops reaching it.`))
      post({action: "take-back", node: p.phone.node || nid});
    return;
  }
  openPhoneLend(p.name, hours => post({action: "lend", node: nid, project: p.name, hours}));
}
// The lend dialog: how long, and Lend. #phoneLendModal is index.html's.
function openPhoneLend(name, lend){
  const p = (state?.projects || []).find(x => x.name === name) || {name};
  const m = $("phoneLendModal");
  armModal(m);
  $("phoneLendTitle").textContent = `Lend your phone to ${projLabel(p.name)}`;
  $("phoneLendHint").textContent = `${p.phone?.model || "Your phone"} on ${p.node_name || "its node"}. Each command ${projLabel(p.name)}'s `
    + "session runs on it asks you in your bell first, and only its own app is reachable.";
  m.hidden = false;
  m.onclick = ev => { if (ev.target === m) m.hidden = true; };
  $("phoneLendCancel").onclick = () => { m.hidden = true; };
  $("phoneLendGo").onclick = () => {
    m.hidden = true;
    lend?.(Number($("phoneLendFor").value));
  };
}

// Projects by name, as a person reads a list: case aside and numbers as
// numbers (the operator, 7 Oct). The server's order is the directory's, in
// which every capitalised name came before every lower-case one.
function byProjectName(a, b){ return String(a.label || a.name).localeCompare(String(b.label || b.name), undefined, {sensitivity: "base", numeric: true}); }
// The projects in this account's groups, in the one order every page that
// shows them keeps (the Projects page and Home, R273): the ones in no group
// first, then each group by name, each list in the order it was handed.
function byProjectGroup(list){
  const named = [...new Set(list.map(p => p.group).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const loose = list.filter(p => !p.group);
  return [...(loose.length ? [{group: "", list: loose}] : []),
          ...named.map(g => ({group: g, list: list.filter(p => p.group === g)}))];
}
// The project job's row (a clone or a first push, running or failed), for
// the Projects page. An ellipsis rather than a percentage: git's progress is a carriage-return
// animation on stderr, and parsing one to redraw it is the thing the
// toolchains tab gave up on. What it *is* doing is a phrase from the server.
// The job is the poll's (state.project_job), read here per draw and kept
// nowhere else, so it cannot drift from the poll.
function projectJobHtml(){
  const pJob = state?.project_job || null;
  return pJob?.running
    ? `<div class="row job">
         <div class="grow">
           <div class="name">${esc(pJob.name)}</div>
           <div class="sub">${esc(pJob.step || pJob.kind)}<span class="dots"></span>${
             pJob.for > 4 ? ` · ${pJob.for}s` : ""}</div>
         </div>
         <span class="acts">${abortBtn('id="bJobStop"', pJob.aborting,
             "stop it: a half-cloned directory is removed, a remote already set stays")}</span>
       </div>`
    // The last outcome, if it went wrong. Kept until it is dismissed rather
    // than shown in a toast that is gone in seven seconds: the page may not
    // even have been open when it failed.
    : pJob?.error
    ? `<div class="row jobfail">
         <div class="grow">
           <div class="name">${esc(pJob.name)}</div>
           <div class="sub bad">${esc(pJob.error)}</div>
         </div>
         <span class="acts"><button id="bJobOk">Dismiss</button></span>
       </div>`
    : "";
}

// A draw of the projects draws the Projects page where it is on show, and
// keeps the Claude chooser in step wherever it was asked for.
function drawProjects(all){
  void all;
  panes.forEach((id, i) => { if ((i === 0 || isSplit()) && tabOf(id)?.kind === "projects") renderProjectsInto(i); });
  syncResumeMenu();
}

// Handlers for the job row, and the ellipsis it needs running. Called from
// both draw paths, because an empty workspace mid-clone shows only this row.
function pJobWire(){
  const stop = $("bJobStop"), okd = $("bJobOk");
  if (stop) stop.onclick = () => pJobAct("abort");
  if (okd)  okd.onclick  = () => pJobAct("dismiss");
  // page-toolchains.js owns the timer; starting it here too means the Projects
  // card animates whether or not a page of toolchains has ever been opened.
  if (stop && !tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
  // While a job runs the two things that would start another are dead, the
  // same rule the toolchain buttons follow: the server answers 409 anyway,
  // and a button that earns an error is worse than one that waits.
  const busy = !!state?.project_job?.running;
  const nb = $("bNewProjTab"); if (nb) nb.disabled = busy;
  // ...and never re-enabled past the grant (R137 step 4): the busy pass
  // undid the row's disabled for an account without git-auth.
  document.querySelectorAll(".pgrid [data-l]").forEach(b => setDisabled(b, busy || state?.can?.["git-auth"] === false));
}

// ---- a project's job: the clone or the first push -----------------------

// The one project job (a clone or a first push) and the poll that watches
// it. It lives on the server, so a page opened halfway through picks it up
// from /api/status and a page closed halfway through changes nothing. On the
// page it lives in state.project_job and nowhere else: this poll writes the
// same slot the status poll fills, and the card reads it from there.
let pJobTimer = null;

function pJobSeen(j){
  const was = state?.project_job?.running;
  if (state) state.project_job = j;
  if (j?.running){
    if (!pJobTimer) pJobTimer = setTimeout(pJobPoll, 1000);
  } else {
    clearTimeout(pJobTimer); pJobTimer = null;
    // Finished while we were watching: the note is the good news, and the
    // list needs re-reading because a project just appeared in it.
    if (was){ if (j.note) notify(`${j.name}: ${j.note}`); refresh(); }
  }
  if (state) drawProjects(state.projects);
}

async function pJobPoll(){
  pJobTimer = null;
  try{ pJobSeen(await (await fetch("/api/project-job")).json()); }
  catch{ pJobTimer = setTimeout(pJobPoll, 3000); }   // a blip, not a finish
}

async function pJobAct(action){
  try{
    const j = await (await postJSON("/api/project-job", {action})).json();
    if (j.error) notify(j.error, true);
  }catch(e){ notify("could not reach the server: " + failWords(e), true); }
  pJobPoll();
}

// ---- a project's archive and lock ----------------------------------------
// Two presses since the operator split them (R119, 23 Oct). Archive is out of
// sight and nothing else: no question asked, since nothing stops. Lock holds
// people out, so its question says whom, and names the sessions it ends.

async function setArchived(name, on){
  const key = reposOf(name) || name;
  try{
    const j = await (await postJSON("/api/archive", {name, archived: on})).json();
    if (j.error){ notify(j.error, true); return; }
    applyNow((p, k) => { if (k === key) p.archived = !!j.archived; });
    notify(on ? `${projectName(key)} archived: in Archived at the foot of the Projects page, and working as before`
              : `${projectName(key)} unarchived`);
  }catch(e){ notify("archive failed: " + failWords(e), true); }
  refresh();
}

async function setLocked(name, on){
  const key = reposOf(name) || name, p = state?.repos?.[key] || {};
  // An administrator who is not its owner locks its owner out too.
  const held = on ? !p.owner_mine : !!p.locked_admin;
  // The project's sessions run on its first repository (R136).
  const who = withMe(p.members?.[0] || name);
  name = projectName(key);
  const running = !who.length ? "No session is running here."
    : who.length === 1 ? `${who[0] === state?.me ? "Your" : who[0] + "'s"} session here ends now.`
    : `${who.length} sessions here end now: ${who.map(w => w === state?.me ? "yours" : w).join(", ")}.`;
  if (on && !await askYes(held
      ? `Lock ${name} as an administrator?\n\n${running}\n\nNobody starts a session in it or `
        + `changes it, ${p.owner_name || "its owner"} included, until an administrator unlocks it. `
        + `It stays on the Projects page with its lock mark.`
      : `Lock ${name}?\n\nEvery session here but yours ends now. Nobody but you starts a session `
        + `in it or changes it until you unlock it. It stays on the Projects page with its lock mark.`)) return;
  try{
    const j = await (await postJSON("/api/lock", {name: key, locked: on})).json();
    if (j.error){ notify(j.error, true); return; }
    for (const s of j.ended || []){
      const t = tabs.find(x => x.kind === "term" && sessionOf(x.arg) === s);
      if (t) dropTab(t.id);
    }
    notify(on ? `${name} locked${j.ended?.length ? `: ${j.ended.length === 1 ? "a session" : `${j.ended.length} sessions`} ended` : ""}`
              : `${name} unlocked`);
    applyNow((x, k) => { if (k === key){ x.locked = !!j.locked; x.locked_admin = !!j.admin; } });
  }catch(e){ notify("lock failed: " + failWords(e), true); }
  refresh();
}

// ---- a project's group ----------------------------------------------------

// Which of this account's groups a project is kept in (the operator, 18
// Oct): asked in a box under the card's name, the groups already made
// offered, an empty answer taking it out of its group.
async function askProjectGroup(btn){
  const name = btn.dataset.pgroup, key = reposOf(name) || name, p = state?.repos?.[key];
  btn.closest(".actmenu")?.setAttribute("hidden", "");
  const card = btn.closest(".pcard, .phead") || btn.closest("[data-row]");
  const at = card?.querySelector(".pcface:not([inert]) .pcname, .pname") || card;
  if (!at) return;
  const groups = [...new Set(Object.values(state?.repos || {}).map(x => x.group).filter(Boolean))].sort();
  const got = await askInline(at, {label: `Group ${projectName(key)} with`, value: p?.group || "", ok: "Save",
                                   options: groups, allowEmpty: true});
  if (got === null || got === (p?.group || "")) return;
  try{
    const j = await (await postJSON("/api/project-group", {name: key, group: got})).json();
    if (j.error){ notify(j.error, true); return; }
    applyNow((x, k) => { x.group = (j.groups || {})[k] || ""; });
    notify(got ? `${projectName(key)} is in ${got}` : `${projectName(key)} is in no group`);
  }catch(e){ notify("group: " + failWords(e), true); }
  refresh();
}

// ---- a project's color ----------------------------------------------------

// The color this account gives a project (the operator, 18 Oct: a person's
// own, not the project's), picked from the dot beside its name on its card:
// the swatches unroll under the name, and a press on one wears it at once,
// as a scheme is (it is looked at, not decided). Escape, a press
// elsewhere or the Color button again rolls them back up.
function pickProjectColor(btn){
  const name = btn.dataset.pcolor, key = reposOf(name) || name, cur = projectColor(name);
  btn.closest(".actmenu")?.setAttribute("hidden", "");
  const card = btn.closest(".pcard, .phead") || btn.closest("[data-row]");
  // The face on show, on a card that turns over (R138).
  const line = card?.querySelector(".pcface:not([inert]) .pcname, .pname");
  const open = line?.nextElementSibling?.classList.contains("pcpop");
  document.querySelectorAll(".pcpop").forEach(x => x.__done?.());
  if (open || !line) return;
  const pop = document.createElement("div");
  pop.className = "pcpop pcpick";
  pop.setAttribute("role", "radiogroup");
  pop.setAttribute("aria-label", `your color for ${projectName(key)}`);
  pop.innerHTML = PROJECT_COLORS.map(([n, tone]) => `<button type="button" role="radio" data-color="${n}" aria-checked="${n === cur}"
      aria-label="${esc(n || "none")}" title="${esc(n || "none")}"${n ? ` data-style="--pc:${tone}"` : ""}></button>`).join("");
  // On a card's back the swatches take the repositories' place, its height
  // held while they are open (askInline's way).
  const back = line.closest(".pcback");
  if (back) back.style.minHeight = back.getBoundingClientRect().height + "px";
  faceFade(line, () => line.insertAdjacentElement("afterend", pop));
  btn.setAttribute("aria-expanded", "true");
  // A press on a Color button is left to its click, which shuts these
  // swatches when it is theirs and opens another card's when not.
  const away = e => { if (!pop.contains(e.target) && !e.target.closest?.("[data-pcolor]")) done(); };
  const esc_ = e => { if (e.key === "Escape") done(); };
  const done = () => { faceFade(pop, () => { pop.remove(); if (back && !back.querySelector(".askline, .pcpop")) back.style.minHeight = ""; });
                       btn.setAttribute("aria-expanded", "false");
                       document.removeEventListener("pointerdown", away, true); document.removeEventListener("keydown", esc_, true); };
  pop.__done = done;
  setTimeout(() => { document.addEventListener("pointerdown", away, true); document.addEventListener("keydown", esc_, true); });
  pop.querySelector(`[data-color="${cur}"]`)?.focus();
  pop.onclick = async e => {
    const b = e.target.closest("[data-color]");
    if (!b) return;
    const color = b.dataset.color;
    done();
    if (color === cur) return;
    try{
      const j = await (await postJSON("/api/project-color", {name: key, color})).json();
      if (j.error){ notify(j.error, true); return; }
      applyNow((x, k) => { x.color = (j.colors || {})[k] || ""; });
    }catch(err){ notify("color: " + err, true); }
  };
}

// ---- a project's pin ------------------------------------------------------

// Pinning asks nothing and ends nothing: no session is touched, no control is
// taken away, and the project is still whole on the Projects tab. It is the
// one of the three that only moves where a row is seen, so no confirmation,
// which would teach somebody to click through the two that do matter.
//
// setProjectPinned, not setPinned: that name, and /api/pin, and the server's
// _pin: were the COMMAND pin's already, and taking them shadowed it in all
// three places at once. Nothing failed loudly; the commands card simply began
// asking the projects endpoint about a command.
async function setProjectPinned(name, on){
  try{
    const r = await postJSON("/api/project-pin", {name: reposOf(name) || name, pinned:on});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The answer IS the new state: the server sends back the whole pinned
    // set, so the page adopts it and redraws now. Waiting for the next
    // /api/status put a poll's latency between the click and the button
    // moving, on a control whose whole job is instant.
    applyNow((p, k) => { p.pinned = (j.pinned || []).includes(k); });
  }catch(e){ notify("pin failed: " + failWords(e), true); }
  refresh();                       // ...and reconcile, in the background
}

// Adopt a server answer into the projects already on screen and redraw.
//
// The rule this follows: an action's response is authoritative for what it
// changed, so the page should not go and ask again before believing it. The
// poll still runs and still wins in the end; this only removes the wait
// between a click and the thing it clicked moving.
// Each repository's row and each project's card, by the project's key: the
// marks are the project's (R138).
function applyNow(fn){
  adoptSeq++;                      // a poll already out is older than this
  (state?.projects || []).forEach(p => fn(p, p.project || p.name));
  Object.entries(state?.repos || {}).forEach(([k, r]) => fn(r, k));
  drawProjects(state?.projects || []);
  drawPanes();                     // the Projects page shows the same rows
}
