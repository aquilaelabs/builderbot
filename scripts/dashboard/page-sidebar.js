// The sidebar's content: the Runner card, and the Projects card with each
// project's row (its controls, why it is held, its lock and its pin, its
// one clone or first-push job), which the Projects tab draws from the same
// functions so a project offers the same controls wherever it is met. A
// row arrives and leaves with a tween.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- sidebar ---------------------------------------------------------

function drawRunner(){
  // The nodes' runners, and nothing else. This container ran a runner of its
  // own until phase 7 of the controller design moved CI onto nodes; the card
  // used to lead with that one's state and keep Start/Stop for it. A workflow
  // lands on whichever runner its runs-on matches, and the node's own name is
  // the label that pins a job to it, so that is what each row leads with. The
  // Nodes tab is where one is installed, started or removed.
  const el = $("runner");
  const rows = state?.node_runners || [];
  if (!rows.length){
    paint(el, `<div class="empty">no runner on any node: the Nodes tab installs one</div>`);
    return;
  }
  const when = t => fmtTime((t || 0) * 1000, {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"});
  paint(el, rows.map(n => {
    // A runner job in flight comes first: a remove of a listening runner is
    // "removing now", not "listening, idle" until the census catches up. And
    // a failure carries its time, because a new one reads exactly like the
    // old one otherwise, and the operator pressed Remove on that reading.
    const [word, cls] = !n.live ? ["quiet: the node has not dialed in lately", "warn"]
      : n.installing ? ["installing now", "warn"]
      : n.removing ? ["removing now", "warn"]
      : n.busy ? ["running a job", "ok"]
      : n.listening ? ["listening, idle", "ok"]
      : n.installed ? ["installed, not listening", "bad"]
      : n.failed ? [`install failed ${when(n.failed.ended)}: ${n.failed.why || "its job on the Jobs tab says why"}`, "bad"]
      : ["install asked for; not reported yet", "warn"];
    return `<div class="row"><span class="grow"><b>${esc(n.node)}</b>${n.url ? ` <span class="dim">${esc(n.url.replace(/^https?:\/\//, ""))}</span>` : ""}
      <span class="sub ${cls}">${esc(word)}</span>${n.labels.length
        ? `<div class="sub dim">runs-on: [self-hosted, ${esc(n.node)}]</div>` : ""}</span></div>`;
  }).join(""));
}

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

let showAllProjects = false;

// What the fold-away button says. It used to have to split its count two
// ways, because half of what it hid was excluded (a decision) and half was
// broken. Only the second kind exists now, so it says the one thing.
function hiddenLabel(flagged){
  return [flagged.length ? `Error (${flagged.length})` : ""]
         .filter(Boolean).join(" / ");
}

const nbOpen = name => tabs.some(t => t.kind === "notebook" && t.arg === name);

// The first clause of a refusal: what is wrong, without what to do about it.
// Every sentence session_target() writes is shaped "<this> is wrong; <do
// this>" or "<this> is wrong. <do this>", so the first sentence end or the
// first dash, whichever comes first, is the half a row can carry. The rest
// stays on the button's tooltip, where a paragraph costs nothing.
function shortWhy(why){
  const s = String(why || "").trim();
  const at = [s.indexOf(": "), s.indexOf(". ")].filter(i => i > 0);
  return (at.length ? s.slice(0, Math.min(...at)) : s).replace(/[.,:;]+$/, "");
}

// ...and its handlers, for the same reason. A row rendered into the tab has
// to DO the same things as one in the card, and a second copy of this list is
// how one of them quietly stops offering Notebook.
function wireProjectRows(root){
  tipify(root);
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
    renameProject(b.dataset.rn));
  root.querySelectorAll("[data-del]").forEach(b => b.onclick = () =>
    deleteProject(b.dataset.del));
}

// One project's row. Extracted so the sidebar card and the Projects tab
// render the SAME markup from the same place: two copies of this would
// have drifted within a week, and the whole point of the tab is that a
// project offers the same controls wherever you meet it.
//
// `live` and `cls` are passed rather than recomputed per row: liveSessions()
// walks the session list, and doing that once per project turned a redraw
// into O(projects x sessions) for no gain.
function projectRow(p, live, cls, inTab){
  const nb = nbOpen(p.name);
  const pc = colorAttrs(p.prefs?.color);
  return `
    <div class="row stack2${pc.cls}" data-row="${esc(p.name)}"${pc.style}>
      <div class="grow">
        <div class="namerow"><div class="name">${esc(p.name)}${p.locked
          // After the name, because it is a fact about the project rather
          // than a control: the row reads "StreamLift, locked" at a glance
          // without hunting for which of six icons is lit.
          ? ` <span class="lockmark" aria-label="locked" data-tip="locked; you run this one">${LOCK}</span>`
          : ""}${notMine(p)
          // The same shape as the padlock and for the same reason: a fact
          // about the row, said where the name is, rather than something to
          // work out from which controls are gray. A different word, because
          // it is a different thing: the padlock is the operator keeping a
          // project to themselves, this is a project you have not taken on.
          ? ` <span class="lockmark" aria-label="read-only" data-tip="${esc(NOT_MINE_WHY)}">${LOCK}</span>`
          : ""}</div></div>
        ${state?.mapping?.[p.name] ? (m => m.running
            ? `<div class="sub">mapping the code<span class="dots"></span>${m.for > 4 ? ` · ${m.for}s` : ""}</div>`
            : m.error ? `<div class="sub warn">the code map did not build: ${esc(m.error)}</div>`
            : `<div class="sub dim">mapped ${m.files} file${m.files === 1 ? "" : "s"} in ${m.took}s</div>`
          )(state.mapping[p.name]) : ""}
        ${p.git ? `<div class="sub">git: ${esc(p.git)}${
          p.push ? ` · <span class="ok">push</span>` : ""}</div>` : ""}

        ${p.issues.map(i =>
          // Every issue a project can carry now is something to go and look
          // at rather than a button to press: an unreadable directory, a
          // broken .git. There used to be a class with a one-press fix (the
          // CLAUDE.md block, and the link that wrote it), and the link went
          // with the block itself, R63 step 3.
          `<div class="sub ${cls[i.level] || ""}">${esc(i.text)}</div>`).join("")}
      </div>
      <span class="acts">
      ${isBroken(p) ? "" : `<button class="eye${live.has(myClaude(p.name)) ? " on acc" : ""}"
         data-c="${esc(p.name)}" aria-label="Claude session"${
         (p.locked || notMine(p)
          // No node, no session, and the button says so by being dead: a
          // Claude session runs on a node and this container carries no
          // Claude Code, so there is nothing for a press to do.
          || (!p.session_at && !!p.session_why && !live.has(myClaude(p.name)))
          // Not signed in on its node ghosts nothing: the press opens the
          // chooser, which offers that node's sign-in, the way in.
          || heldWhy(p))
           ? " disabled" : ""}
         title="${notMine(p) ? NOT_MINE_WHY
                 : p.locked
                   ? "locked; you run this one. The padlock lets Claude back in"
                 : heldWhy(p) ? heldWhy(p)
                 // The whole reason, including what to do about it. The row
                 // carries the first clause in red and stops there; this is
                 // where the rest belongs, and it is a tap rather than a
                 // hover on a phone because these rows are tipified.
                 : p.session_why ? p.session_why
                 : othersOn(p.name).length
                   ? `${othersOn(p.name).join(", ")} also working here, in a checkout of their own: start yours`
                 : p.session_node && !claudeOn(p.session_node) && !live.has(myClaude(p.name))
                   ? `Claude: you are not signed in on ${p.session_at}, this project's node. Press for its sign-in`
                 : p.session_at
                   ? `Claude: a session on ${p.session_at}, this project's node`
                 : live.has(myClaude(p.name)) ? "Claude: session running, go to its tab"
                 : p.last_claude ? "Claude: no session running; resume or start one"
                 : "Claude: start a session here"}">${SPARK}</button>`}
      ${mayShell() ? `<button class="eye" data-s="${esc(p.name)}" aria-label="shell"
        ${notMine(p) || !gitReadyFor(p) ? "disabled" : ""}
        title="${notMine(p) ? NOT_MINE_WHY
                : !gitReadyFor(p)
                  ? "set your commit name and email on your Profile (the gear) or in this project's settings first"
                : "shell: open another terminal here"}"
        >${TERM}</button>` : ""}
      ${p.git_ok && !isBroken(p)
        ? `<button class="eye" data-l="${esc(p.name)}"
             aria-label="${p.linked ? `${p.forge_name || "remote"} settings` : "link to a git host"}"
             title="${p.linked
               ? `${esc(p.forge_host || p.forge_name || "its remote")}: the credential this project pushes with, and Unlink`
               : "no remote: link this repo to an empty repository on GitHub, Gitea, GitLab or another git host"}">${LINK}</button>`
        : ""}
      ${isBroken(p) ? "" : `<button class="eye${nb ? " on acc" : ""}"
         data-m="${esc(p.name)}" aria-label="notebook"
         title="${p.locked
                   ? (nb ? "notebook: open, go to its tab. Read-only: this project is locked"
                         : "notebook: readable while this project is locked, not writable")
                 : nb ? "notebook: open, go to its tab"
                 : "notebook: roadmap, memory and bugs for this project"}">${BOOK}</button>`}
      <button class="eye" data-rn="${esc(p.name)}" aria-label="settings"
        title="settings: name, node, and what Claude runs on here">${GEAR}</button>
      <button class="eye${p.locked ? " on" : ""}" data-k="${esc(p.name)}"
        data-on="${p.locked ? "0" : "1"}"${state?.admin === false ? " disabled" : ""}
        aria-label="${p.locked ? "unlock" : "lock"}"
        title="${state?.admin === false ? "locking a project is an administrator's"
          : p.locked
          ? "unlock: let Claude start sessions here and write its notebook again"
          : "lock: run this project yourself. No Claude session starts here "
            + "and its notebook goes read-only"}"
        >${p.locked ? LOCK : LOCK_OPEN}</button>
      <button class="eye pin${p.pinned ? " on" : ""}" data-p="${esc(p.name)}"
        data-on="${p.pinned ? "0" : "1"}"
        aria-label="${p.pinned ? "unpin" : "pin"}"
        title="${state?.admin === false ? "the pins are one set for everybody, so moving them is an administrator's"
          : p.pinned
          ? "unpin: take it off the sidebar; it stays on the Projects tab"
          : "pin: show it on the sidebar's Projects card"}"
        >${TACK}</button>
      ${inTab ? `<button class="eye rm bare" data-del="${esc(p.name)}" aria-label="delete"
        title="delete: moves it to the trash with everything it has; Put back restores it">${BIN}</button>` : ""}
      <button class="eye rowmore" data-more="${esc(p.name)}" aria-label="more"
        aria-expanded="false" title="the rest of this row's controls">${DOTS}</button>
      </span>
      ${p.testing ? `<div class="sub sessline testing">tests running, started ${esc(ago(p.testing.since))}</div>` : ""}
      ${sessionRows(p.name) ? `<div class="sub sesslist">${sessionRows(p.name)}</div>`
        // WHO is here, or WHY nobody can be. Which machine they are on is
        // neither: it is on the project's settings, it is the same for every
        // session here, and a row that said it had a line spent on something
        // nobody was asking.
        //
        // A project whose NODE cannot start one says so in red whenever it
        // is not LOCKED, which is the one case where no session is the point
        // rather than a fault. Short: what is wrong and not what to do about
        // it, because the fix runs to a paragraph on some of these and the
        // ghosted button's tooltip is where a paragraph is free (the rows
        // are tipified, so that is a tap on a phone as well as a hover). A
        // project with no node said nothing here for a week ("(node: none)"
        // beside the name was called the whole fact, 15 Sep); it says so
        // now, because a dead button and a tooltip are not a reason on a
        // phone, and the operator stared at three such rows after an update
        // (23 Sep). The same line for a node whose agent is out of window
        // (held), unless the row is already saying the map is building.
        : (p.session_why || (p.held && !state?.mapping?.[p.name]?.running)) && !p.locked
          ? `<div class="sub sessline bad">${esc(shortWhy(p.session_why || p.held))}</div>` : ""}
    </div>
`;
}

function drawProjects(all){
  const el = $("projects");
  // The card is the pinned view; the Projects tab is the whole list. Filtered
  // here rather than by the server, which reports every project to everything
  // that asks: the findings card and the SARIF attribution both need the full
  // set, and a payload that quietly shrank would take them with it.
  const ps = all.filter(p => p.pinned);
  const flagged = ps.filter(isBroken);
  const hidden = hiddenLabel(flagged);
  // Excluded last: it is not a problem waiting to be fixed like the rest of
  // what is folded away here, it is a decision already made.
  const shown   = (showAllProjects ? ps : ps.filter(p => !isBroken(p)))
                  .slice();

  // Declared above the empty-list branch below, which READS it. It used to
  // sit past that branch's `return`, so a card with nothing pinned threw
  // "Cannot access 'jobHtml' before initialization" and drew nothing: the
  // one state where the empty message is the whole point of the card.
  // A clone or a first push, drawn where its result will appear. An ellipsis
  // rather than a percentage: git's progress is a carriage-return animation
  // on stderr, and parsing one to redraw it is the thing the toolchains tab
  // gave up on. What it *is* doing is a phrase from the server.
  // The job is the poll's (state.project_job), read here per draw and kept
  // nowhere else: the page-level copy it used to be drifted from the poll.
  const pJob = state?.project_job || null;
  const jobHtml = pJob?.running
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
    // Named, like the running row above it. A project row carries a red
    // `.sub` of its own now (why no session can start here), so "the red
    // line in the projects card" stopped being one thing, and the test that
    // waited for one to CLEAR waited forever on somebody else's.
    ? `<div class="row jobfail">
         <div class="grow">
           <div class="name">${esc(pJob.name)}</div>
           <div class="sub bad">${esc(pJob.error)}</div>
         </div>
         <span class="acts"><button id="bJobOk">Dismiss</button></span>
       </div>`
    : "";

  // At the foot of the card, not the header: headers hold nothing but the
  // title, because the whole header is the collapse control and drag handle.
  // New project lives here too: present even when the list is empty, since
  // an empty workspace is exactly where it is needed most.
  const togHtml = `<div class="macros"><button id="bNewProj"
       title="create a project: a new local repository, or a clone of one">New project</button><button id="bAllProj"
       title="every project under /workspace, pinned or not, with the same controls">All projects</button
       ><button id="bTrash" class="ic"
       title="projects you deleted: still on disk under .trash, and still recoverable">${BIN}</button>${
       flagged.length
       ? `<button id="bAll">${showAllProjects ? "Hide" : "Show"} ${hidden}</button>` : ""}</div>`;

  if (!shown.length){
    // state.projects at click time, not the `ps` this draw was given: the
    // handler outlives the draw now that unchanged markup is kept.
    if (paint(el, jobHtml + `<div class="empty">${
      !all.length ? (state.admin ? "no projects yet: New project starts one"
                     : "no projects are yours yet: an administrator grants them on the Users tab")
      : !ps.length ? "nothing pinned: open the Projects tab to pin what you want here"
                 : `nothing to show; everything here is folded away under Show ${hidden}`
    }</div>` + togHtml)){
      pJobWire();
      $("bNewProj").onclick = openNewProject;
      const tb = $("bTrash"); if (tb) tb.onclick = openTrash;
      $("bAllProj").onclick = openProjectsTab;
      if (flagged.length)
        $("bAll").onclick = () => { showAllProjects = !showAllProjects;
                                  slideBody(el, () => drawProjects(state?.projects || ps)); };
    }
    return;
  }

  const cls = {error:"bad", warning:"warn", locked:"locked"};
  const live = liveSessions();
  // Handlers bind on a real change only; an unchanged card keeps its
  // elements, and their handlers, from last time.
  if (paint(el, jobHtml + shown.map(p => projectRow(p, live, cls)).join("") + togHtml)){
    $("bNewProj").onclick = openNewProject;
    const tb = $("bTrash"); if (tb) tb.onclick = openTrash;
    $("bAllProj").onclick = openProjectsTab;
    if (flagged.length)
      $("bAll").onclick = () => { showAllProjects = !showAllProjects;
                                  slideBody(el, () => drawProjects(state?.projects || ps)); };
    wireProjectRows(el);
    pJobWire();
  }
  // The chooser is positioned against the card, so it is a sibling of the list
  // rather than part of it: replacing the list's innerHTML does not remove it,
  // and without this they stack up one per draw.
  el.closest(".card").querySelectorAll(".resumemenu").forEach(n => n.remove());
  if (resumeFor) placeResumeMenu();
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
  const nb = $("bNewProj"); if (nb) nb.disabled = busy;
  document.querySelectorAll("#projects [data-l]").forEach(b => b.disabled = busy);
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
  if (on && !confirm(`Lock ${name}?\n\n${running}\n\n`
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
    if (on && j.ended?.length) notify(`${name} locked: ${j.ended.length === 1 ? "its Claude session" : `${j.ended.length} Claude sessions`} ended`);
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
  // Nothing to watch: the card is collapsed, a phone is on the terminal view,
  // or the row drew straight into the fold behind Show broken. The draw stands.
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
