// What a project offers wherever it is met (the Projects page's cards and a
// project's page): its controls, why it is held, its lock and its pin, its
// one clone or first-push job. Named for the sidebar the rows were first
// drawn in, which went with R218 step 3.
//
// One classic script beside index.html (docs/design-language.md, Files):
// pure declarations, nothing runs at load.

"use strict";

// Rendered, as opposed to merely present: a hidden element and one the
// stylesheet hides offer nothing to animate.
const rendered = el => el && !el.hidden && el.getClientRects().length > 0;

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
const heldWhy = p => p.held || (!gitReadyFor(p) && !liveSessions().has(myClaude(p.name))
  ? "set your commit name and email on your Profile (the gear) or in this project's settings first"
  : "");


const nbOpen = name => tabs.some(t => t.kind === "notebook" && t.arg === name);

// ...and its handlers, for the same reason. A row rendered into the tab has
// to DO the same things as one in the card, and a second copy of this list is
// how one of them quietly stops offering Notebook.
function wireProjectRows(root){
  // A phone shows the two controls a phone is for: the session and the
  // notebook, and folds the rest behind this. Six 38px buttons were a third
  // of a 140px row, on a screen that fits six rows; the row is the list, and
  // a list should be names. CSS decides which are hidden, so the desktop is
  // untouched and nothing here has to know the breakpoint.
  root.querySelectorAll("[data-more]").forEach(b => b.onclick = () => {
    const row = b.closest(".row");
    // The row's controls wrap under its name when folded out: the row (and
    // the card holding it) slides over the height that takes, rather than
    // snapping to it.
    slideBody(row, () => {
      const on = row.classList.toggle("moreon");
      b.setAttribute("aria-expanded", on ? "true" : "false");
    });
  });
  root.querySelectorAll("[data-c]").forEach(b => b.onclick = e => openClaude(b.dataset.c, e));
  root.querySelectorAll("[data-s]").forEach(b => b.onclick = () => newShell(b.dataset.s));
  // The chain is the remote, whichever state the project is in: linking one
  // that has no remote, and the credential half (and the way off it) for
  // one that has. It used to be the first only, and GitHub only, with the
  // credential buried in the settings dialog beside the name and the model.
  root.querySelectorAll("[data-l]").forEach(b => b.onclick = () => {
    const p = (state?.projects || []).find(x => x.name === b.dataset.l);
    if (p?.linked) renameProject(b.dataset.l, "git");
    else openLinkProject(b.dataset.l);
  });
  root.querySelectorAll("[data-m]").forEach(b => b.onclick = () => openNotebook(b.dataset.m));
  root.querySelectorAll("[data-k]").forEach(b => b.onclick = () =>
    setLocked(b.dataset.k, b.dataset.on === "1"));
  root.querySelectorAll("[data-p]").forEach(b => b.onclick = () =>
    setProjectPinned(b.dataset.p, b.dataset.on === "1"));
  root.querySelectorAll("[data-rn]").forEach(b => b.onclick = () =>
    openProjectSettings(b.dataset.rn));
  root.querySelectorAll("[data-bug]").forEach(b => b.onclick = () =>
    openReport(b.dataset.bug));
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
  if (!ph) return `no phone is connected on ${p.node_name}: connect yours in the Phone tab, on that node`;
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
    if (confirm(`Take your phone back from ${projLabel(p.name)}? Its session stops reaching it.`))
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
// The project job's row (a clone or a first push, running or failed), for
// the Projects page: the card that drew it went with R218 step 3. An
// ellipsis rather than a percentage: git's progress is a carriage-return
// animation on stderr, and parsing one to redraw it is the thing the
// toolchains tab gave up on. What it *is* doing is a phrase from the server.
// The job is the poll's (state.project_job), read here per draw and kept
// nowhere else: the page-level copy it used to be drifted from the poll.
function projectJobHtml(){
  const pJob = state?.project_job || null;
  return pJob?.running
    ? `<div class="row job">
         <div class="grow">
           <div class="name">${esc(pJob.name)}</div>
           <div class="sub">${esc(pJob.step || pJob.kind)}<span class="dots"></span>${
             pJob.for > 4 ? ` · ${pJob.for}s` : ""}</div>
         </div>
         <span class="acts"><button id="bJobStop"${pJob.aborting ? " disabled" : ""}
           title="stop it: a half-cloned directory is removed, a remote already set stays"
           >${pJob.aborting ? "Stopping…" : "Abort"}</button></span>
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

// What the sidebar's projects card did is the Projects page's (R218 step
// 3): a draw asked of the card draws the page where it is on show, and
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
  // The toolchains tab owns the timer; starting it here too means the Projects
  // card animates whether or not that tab has ever been opened.
  if (stop && !tcDotsTimer) tcDotsTimer = setInterval(tcTickDots, 400);
  // While a job runs the two things that would start another are dead, the
  // same rule the toolchain buttons follow: the server answers 409 anyway,
  // and a button that earns an error is worse than one that waits.
  const busy = !!state?.project_job?.running;
  const nb = $("bNewProjTab"); if (nb) nb.disabled = busy;
  // ...and never re-enabled past the grant (R137 step 4): the busy pass
  // undid the row's disabled for an account without git-auth.
  document.querySelectorAll(".pgrid [data-l]").forEach(b => b.disabled = busy || state?.can?.["git-auth"] === false);
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
  }catch(e){ notify("could not reach the server: " + e, true); }
  pJobPoll();
}

// ---- a project's lock ---------------------------------------------------

// Locking is the same write and the same session-ending as excluding, and the
// confirmation says the one thing that is different: the row survives whole.
// Somebody reaching for this wants to keep the project, so the dialog has to
// make clear it is not the other button.
// ...and names who is running a Claude session here, since the lock ends
// every one of them, whoever's and on whatever node (the operator, 29 Sep).
async function setLocked(name, on){
  const who = withMe(name);
  const running = !who.length ? "No Claude session is running here."
    : who.length === 1 ? `${who[0] === state?.me ? "Your" : who[0] + "'s"} Claude session here ends now.`
    : `${who.length} Claude sessions here end now: ${who.map(w => w === state?.me ? "yours" : w).join(", ")}.`;
  if (on && !confirm(`Lock ${projLabel(name)}?\n\n${running}\n\n`
        + `No Claude session starts here and its notebook goes read-only. Your `
        + `shells, findings, artifacts and dev instance keep working. Unlock `
        + `reverses it.`)) return;
  try{
    const r = await postJSON("/api/lock", {name, locked:on});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    for (const s of j.ended || (j.killed ? [j.killed] : [])){
      const t = tabs.find(x => x.kind === "term" && sessionOf(x.arg) === s);
      if (t) dropTab(t.id);
    }
    if (on && j.ended?.length) notify(`${projLabel(name)} locked: ${j.ended.length === 1 ? "its Claude session" : `${j.ended.length} Claude sessions`} ended`);
    applyNow(p => { p.locked = (j.locked || []).includes(p.name); });
  }catch(e){ notify("lock failed: " + e, true); }
  refresh();
}

// ---- a project's pin, and rows that come and go -------------------------

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
    const r = await postJSON("/api/project-pin", {name, pinned:on});
    const j = await r.json();
    if (j.error){ notify(j.error, true); return; }
    // The answer IS the new state: the server sends back the whole pinned
    // set, so the page adopts it and redraws now. Waiting for the next
    // /api/status put a poll's latency between the click and the button
    // moving, on a control whose whole job is instant.
    const apply = p => { p.pinned = (j.pinned || []).includes(p.name); };
    // Both directions are watched from the Projects tab, which sits beside the
    // sidebar on a desktop: the row grows into the card or folds out of it.
    if (on) arriveRow(name, apply); else leaveRow(name, apply);
  }catch(e){ notify("pin failed: " + e, true); }
  refresh();                       // ...and reconcile, in the background
}

// Adopt a server answer into the projects already on screen and redraw.
//
// The rule this follows: an action's response is authoritative for what it
// changed, so the page should not go and ask again before believing it. The
// poll still runs and still wins in the end; this only removes the wait
// between a click and the thing it clicked moving.
function applyNow(fn){
  adoptSeq++;                      // a poll already out is older than this
  (state?.projects || []).forEach(fn);
  drawProjects(state?.projects || []);
  drawPanes();                     // the Projects tab shows the same rows
}

// The sidebar row for one project. By the row's own name rather than through
// the thumbtack inside it: the card has no thumbtack now: pinning is the
// Projects tab's, where the whole list is, and a lookup that went through the
// control would have quietly stopped finding anything, taking both animations
// with it and saying nothing.
//
// Escaped for a QUOTED attribute value, which is a different job from
// CSS.escape: that one escapes identifiers, so a project with a dot in its
// name came out as [data-row="ep\.silon"]: a literal backslash inside the
// quotes, matching nothing.
const pinRow = (card, name) => card?.querySelector(
  `.row[data-row="${name.replace(/["\\]/g, "\\$&")}"]`);

// The same, for a change that takes a row OUT of the sidebar: unpinning.
//
// Done as a fade and a collapse rather than a redraw, because a row vanishing
// between two frames leaves the eye hunting for what moved: everything below
// jumps up by exactly one row's height and nothing says which one went. The
// row fades where it stands, the list closes over it, and only then is the
// real draw allowed to happen.
//
// The card's height is animated too, not just the row's: the cards below ride
// on it, so animating only the row would collapse the gap and then snap the
// page. slideBody already does that pairing for the Show-broken toggle.
function leaveRow(name, fn){
  const card = $("projects");
  const row = pinRow(card, name);
  if (!row || noMotion()){ applyNow(fn); return; }
  const from = card.offsetHeight;
  row.style.overflow = "hidden";
  const h = row.offsetHeight;
  const anim = row.animate(
    [{opacity: 1, height: h + "px"}, {opacity: 0, height: "0px"}],
    {duration: 170, easing: "ease"});
  // The redraw waits for the tween. If it landed first the row would be gone
  // before it had faded, which is the jump this exists to remove.
  anim.onfinish = anim.oncancel = () => {
    (state?.projects || []).forEach(fn);
    slideBody(card, () => drawProjects(state?.projects || []));
    drawPanes();
    // Belt and braces: a row that survived the change must not keep the
    // tween's end state.
    row.style.overflow = ""; row.style.opacity = ""; row.style.height = "";
    void from;
  };
}

// And the mirror of it, for a change that brings a row IN: pinning.
//
// This used to be a plain redraw, on the theory that an arriving row was not
// there to be watched. That is only true if the sidebar is the thing you are
// looking at: you pin from the Projects tab, which on a desktop sits in the
// column beside the card, so the row lands in one frame and shoves every
// project under it down with no warning. It unrolls from nothing instead, on
// the same tween leaveRow uses backwards, and the rows below ride down.
//
// The redraw goes first here, which is the one real difference: a row cannot
// grow before it exists, so the tween starts from the collapsed state in the
// same frame rather than after it.
function arriveRow(name, fn){
  const card = $("projects");
  if (!card || noMotion()){ applyNow(fn); return; }
  const from = card.offsetHeight;
  applyNow(fn);
  const row = pinRow(card, name);
  // Nothing to watch: the row is not on screen. The draw stands.
  if (!rendered(row)) return;
  const to = card.offsetHeight, h = row.offsetHeight;
  row.style.overflow = "hidden";
  const anim = row.animate(
    [{opacity: 0, height: "0px"}, {opacity: 1, height: h + "px"}],
    {duration: 170, easing: "ease"});
  anim.onfinish = anim.oncancel = () => {
    row.style.overflow = ""; row.style.opacity = ""; row.style.height = "";
  };
  // The card is tweened alongside it for the same reason leaveRow does it: the
  // cards below ride on this one's height. Measured across the redraw rather
  // than derived from the row, because the first pin also drops the "nothing
  // pinned" line, and a card sized to the row alone would jump by that much.
  if (to === from) return;
  card.getAnimations().forEach(a => { if (a.id === "body") a.cancel(); });
  card.style.overflow = "hidden";
  const grow = card.animate([{height: from + "px"}, {height: to + "px"}],
                            {duration: 170, easing: "ease"});
  grow.id = "body";
  grow.onfinish = grow.oncancel = () => card.style.overflow = "";
}
