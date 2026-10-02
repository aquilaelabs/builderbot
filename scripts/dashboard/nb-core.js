// The notebook itself: one per project, each a clone of #nbTpl with its
// state in one closure (makeNotebook), so two open in a split share
// nothing. The views are the nb-*.js files beside this one; this is the
// frame they draw into, with its own strip, its presence line and its
// save.
//
// One classic script beside index.html (docs/design-language.md, Files),
// moved out of the page's own script with bb map sections in hand (R77):
// pure declarations, nothing runs at load. What runs at load stays in
// index.html under the section's header.

"use strict";

// ---- notebooks -----------------------------------------------------------

// One notebook per project, and as many open as there are projects: each is a
// clone of #nbTpl with its state held in this closure, so two of them in a
// split do not share so much as a variable. The local `$` shadows the global
// one on purpose: every lookup inside the notebook's code resolves within
// its own clone, which is what makes the ids in the template safe to repeat.
const notebooks = new Map();
// For the tests: the held state of one project's notebook, from outside.
const nbHeldFor = name => !!notebooks.get(name)?.held();

// Which view a project's notebook is on, kept per browser so a reload comes
// back to it: the strip and the active pane come back from the saved layout,
// and this is the one "where was I" that lives inside a tab rather than on
// the strip. Closing the notebook forgets it (destroy), so a tab opened
// fresh starts on the strip's first view as it always has.
const nbViewMemo = {
  read(){ try{ return JSON.parse(localStorage.getItem("bb.nbview") || "{}"); }catch(e){ return {}; } },
  keep(project, v){
    try{
      const m = this.read();
      if (v) m[project] = v; else delete m[project];
      localStorage.setItem("bb.nbview", JSON.stringify(m));
    }catch(e){ /* no storage */ }
  },
};

function getNotebook(project){
  let nb = notebooks.get(project);
  if (!nb){ nb = makeNotebook(project); notebooks.set(project, nb); }
  return nb;
}

function openNotebook(name, view){
  openTab({kind: "notebook", arg: name, label: "Notebook: " + name});
  if (view) getNotebook(name).view(view);
}

// ---- a project's notebook: one closure each -----------------------------

function makeNotebook(project){
  const root = document.getElementById("nbTpl").content.firstElementChild.cloneNode(true);
  // Whose notebook this clone is, on the element. Every id inside it is the
  // template's, so two open notebooks carry two of each; anything keyed on an
  // id alone is therefore keyed on BOTH of them, which is what paginate was.
  root.dataset.project = project;
  document.getElementById("nbPark").appendChild(root);
  const $ = id => root.querySelector('[id="' + CSS.escape(id) + '"]');
  // The notebook's state, one object rather than sixty closure variables,
  // so a view can live in its own file and reach it by name (R60).
  const nb = {};
  // The closure's own functions a view reaches through the state object,
  // late-bound: a view file calls nb.syncSave(), and which function that is
  // does not depend on the order the files loaded in.
  Object.assign(nb, {openSheet, closeSheet, setNbView, drawBatchNote, nbHeld,
                     nbUnsaved, noteBatch, syncSave});
  nb.loaded = false;
  nb.ruleData = null; nb.rulePending = null; nb.rulesRev = null;
  // Global rules switched off for this project, staged (nb-rules.js), and
  // the one an administrator is editing.
  nb.globalOffPending = null; nb.globalEditing = null;
  // Which rules are open for editing, by row. A rule is READ by default:
  // its name, its text, its triggers, and shows its fields only after Edit,
  // the way a bug report does; every row opening as a form read as a tab
  // full of half-finished edits. A row just added starts open, since it is
  // nothing but a form until it has words.
  nb.ruleEditing = new Set();
  // ...and which are unfolded. A rule is a fold like a bug report: its name
  // on the line, the words behind a click: a tab that showed every rule in
  // full was a wall. Kept across redraws so a reword does not shut the fold.
  nb.ruleOpen = new Set();
  // What each row read when its Edit was pressed, so Cancel has somewhere
  // to go back to. A row with no entry here is one Add made: canceling
  // that is removing it.
  nb.ruleWas = new Map();
  // How many memories the tab found (null until read), for the head row that
  // sums both halves of the briefing: set by drawMemory, read by both draws.
  nb.memN = null;
  // The approval queue (roadmap #27): what the band and the tab counts draw
  // from, and the revision the poll compares to know when to re-read it.
  nb.pendData = null; nb.pendRev = null;

  // ---- the reading room --------------------------------------------------
  // What goes in is the real element, MOVED: every handler bound to a filter
  // bar keeps working and there is no second copy to drift out of step with
  // the first. They go home on close, to the exact place they left: parent
  // AND next sibling, because "append it back" is how an element ends up
  // under the wrong heading.
  const sheet = root.querySelector(".nbsheet");
  armModal(sheet);                        // a clone: the page-load pass did not see it
  nb.sheetHome = []; nb.sheetClosed = null;

  // ---- the views, one file each (nb-*.js) --------------------------------
  // Made here, before anything below runs: a view is a factory that only
  // defines functions, and the names it hands back are what the rest of
  // this closure calls by name.
  const {loadGit} = nbGitView({$, nb, project});
  const {loadArtifacts, loadVersion, drawVersion, postArtifacts, postVersion} = Object.assign(nb, nbArtifactsView({$, nb, project, root, sheet}));
  const {loadAnalysis, loadCodebase, codebaseSection, loadPreamble, preambleSection, loadBrief, briefSection} = Object.assign(nb, nbAnalysisView({$, nb, project}));
  const {loadDesign} = Object.assign(nb, nbDesignView({$, nb, project, root}));
  const {loadWiki, wikiDirty, wikiNews} = Object.assign(nb, nbWikiView({$, nb, project}));
  const {loadRules, drawRules, saveRules, ruleDirty} = Object.assign(nb, nbRulesView({$, nb, project}));
  const {loadTests} = Object.assign(nb, nbTestsView({$, nb, project}));
  const {loadBugs, drawBugs, postBug} = Object.assign(nb, nbBugsView({$, nb, project}));
  const {loadPending, drawPending} = Object.assign(nb, nbPendingView({$, nb, project, root}));
  const {cancelSend, flushPending, loadRoadmap, postRoadmap, redrawRoadmap, revertPending} = Object.assign(nb, nbRoadmapView({$, nb}));
  const {briefingHead, loadMemory, memDirty, saveMemory} = Object.assign(nb, nbMemoryView({$, nb}));
  Object.assign(nb, nbHistoryView({$, nb, project}));

  function openSheet(title, els, onClose){
    closeSheet();                    // one at a time, like the env editor
    $("sheetTitle").textContent = title;
    const slot = $("sheetSlot");
    nb.sheetHome = els.map(el => [el, el.parentElement, el.nextSibling, el.hidden]);
    els.forEach(el => { el.hidden = false; slot.appendChild(el); });
    nb.sheetClosed = onClose || null;
    sheet.hidden = false;   // the fade is the stylesheet's, for every modal
  }

  function closeSheet(){
    if (sheet.hidden) return;
    sheet.hidden = true;
    for (const [el, parent, next, wasHidden] of nb.sheetHome){
      el.hidden = wasHidden;
      // No parent means it was built for the sheet and has nowhere to go back
      // to. next is null for "it was last".
      if (!parent){ el.remove(); continue; }
      // The reference node is only good while its parent still holds it, and
      // one of these parents does not: the changelog pane lives in #verBox,
      // whose children drawVersion() replaces wholesale, which happens on a
      // commit, a version poll or a dist change while the sheet is still open
      // over the top. insertBefore then throws on a node that is no longer a
      // child, mid-loop, so nb.sheetHome was never cleared and nb.sheetClosed never
      // ran: the button stayed lit and the pane sat orphaned in the slot,
      // reappearing inside the next sheet opened.
      try{
        parent.insertBefore(el, next && next.parentNode === parent ? next : null);
      }catch(e){
        // Parent gone from the document entirely; put it back where it can
        // do no harm rather than leaving it in the sheet.
        el.remove();
      }
    }
    nb.sheetHome = [];
    const done = nb.sheetClosed; nb.sheetClosed = null;
    done?.();
  }

  $("sheetClose").onclick = closeSheet;
  // The backdrop, and not the box on it: a click landing inside is aimed at
  // something in there.
  sheet.onclick = e => { if (e.target === sheet) closeSheet(); };
  root.addEventListener("keydown", e => {
    // A filter field holding a search clears the field on Escape and stops
    // the event, so this never sees that one.
    if (e.key === "Escape" && !sheet.hidden){ e.preventDefault(); closeSheet(); }
  });

  nb.memProj = null;  // set by openMemory; always this project
  nb.memGen  = 0;  // bumped on close, so a slow load cannot repaint it
  // What each half of the notebook was on at the last read, so the poll can see
  // somebody else writing (roadmap #26). Until this, the Bugs tab was the only
  // one of the four that noticed: the Roadmap and Memory views loaded once when
  // the tab opened and then held that drawing until it was closed and reopened,
  // which is a long time to be looking at a list a session has moved on from.
  nb.roadmapRev = null; nb.memRev = null;
  nb.movedUnder = false;        // another writer moved a half this panel is holding edits to (B199)

  async function openMemory(name){
    nb.memProj = name;
    const gen = ++nb.memGen;
    $("memTitle").textContent = "Notebook: " + name;
    nb.memN = null; briefingHead();
    $("memDrift").innerHTML = $("memList").innerHTML = $("memAdd").innerHTML = "";
    $("roadmapSaveQuiet").disabled = true;
    nb.roadmapSel = null;                 // the send box lives on the row, and the
    nb.roadmapOrdering = false;           // rows are about to be replaced wholesale
    nb.roadmapPending = []; nb.roadmapWas = null;
    nb.roadmapBatch = null; nb.roadmapStale = false;
    nb.roadmapRev = nb.memRev = null;
    nb.clash = nb.memClash = null; nb.clashResume = null;
    nb.nbHere = []; nb.nbRead = 0; nb.nbWhere = "briefing"; drawHere();
    nb.tests = null; nb.testsRev = null;
    nb.tstSuite = ""; nb.tstFlagged = nb.tstUndoc = false;
    nb.roadmapLogOn = false;
    nb.roadmapLog = null;
    nb.roadmapDoneOn = false; nb.roadmapDone = null;
    $("histFind").value = "";
    cancelSend();
    $("roadmapText").value = "";
    $("roadmapList").innerHTML = `<div class="loading">loading…</div>`;
    // Opening it is a re-read: both halves come off disk again, and the card
    // gets the same treatment so the number on the row you just pressed is not
    // the one from the last poll.
    await Promise.all([loadRoadmap(gen), loadMemory(gen), refresh()]);
  }

  // A batch opening is news; a batch closing is news of a different kind: the
  // list on screen is now a copy of something that has changed, so it is marked
  // stale and stays that way until it is re-read.
  function noteBatch(b){
    if (nb.roadmapBatch && !b){
      nb.roadmapStale = true;
      // Nothing staged and nothing half-typed: the fresh list can simply be
      // taken, and the banner never has to ask for a click it does not need.
      if (!nb.roadmapPending.length && !memDirty()){
        nb.roadmapStale = false;
        nb.roadmapBatch = null;
        reloadViews();
        return;
      }
    }
    nb.roadmapBatch = b || null;
  }

  // Is the notebook held against operator writes? While a session's batch is
  // open, and again until the roadmap is re-read after one closes. It holds
  // everything: the Saves, and the write-through controls on the memory and
  // bug views, because "a session is mid-change here" is a fact about the
  // notebook, not about one of its tabs.
  // A batch open past BATCH_STALE holds nothing (B198): its session is gone,
  // and a hold nobody can lift is a notebook nobody can save.
  function nbHeld(){ return (!!nb.roadmapBatch && !nb.roadmapBatch.stale) || nb.roadmapStale; }

  function drawBatchNote(){
    const el = $("roadmapBatch");
    if (!el) return;
    root.classList.toggle("held", nbHeld());
    el.hidden = !nb.roadmapBatch && !nb.roadmapStale;
    if (el.hidden){ el.innerHTML = ""; return; }
    const n = nb.roadmapBatch?.changes || 0;
    const mins = nb.roadmapBatch?.at ? Math.max(1, Math.round((Date.now() / 1000 - nb.roadmapBatch.at) / 60)) : 0;
    el.innerHTML = nb.roadmapBatch?.stale
      ? `<div>A session started changing this notebook ${mins} min ago and never closed it.
         Nothing is held: your saves go through.${
         state?.can?.admin ? ` <button type="button" id="roadmapBatchClose">Close it</button>` : ""}</div>`
      : nb.roadmapBatch
      ? `<div>${esc(nb.roadmapBatch.by || "a session")} is changing this
         notebook${n ? `: ${n} change${n === 1 ? "" : "s"} so far` : ""}. Saving
         waits until it finishes; your edits stay where they are.
         <button type="button" id="roadmapRecheck">Check now</button></div>`
      : `<div>A session finished changing this notebook. What is on screen was
         read before that, so saving over it would undo the change.
         <button type="button" id="roadmapReread">Reload the list</button></div>`;
    const bc = $("roadmapBatchClose");
    if (bc) bc.onclick = async () => {
      busy(bc, "Closing");
      try{
        const j = await (await postJSON("/api/roadmap", {project, action: "batch-close"})).json();
        if (j.error) notify(j.error, true);
      }catch(e){ notify("could not reach the server: " + e, true); }
      await refresh();
    };
    const rr = $("roadmapReread");
    if (rr) rr.onclick = rereadRoadmap;
    const rc = $("roadmapRecheck");
    // The link is the answer to "is it done yet?" without waiting for the next
    // poll. If it is, and nothing local is at stake, the reload happens by
    // itself: the guard should only demand a click when a click would cost.
    if (rc) rc.onclick = async () => {
      rc.disabled = true; rc.textContent = "Checking…";
      // The batch state, which is the question the button asks, not a reload
      // of one view, which is what it used to do and why the roadmap refreshed
      // while the other three tabs did not. If the batch has closed and nothing
      // local is staged, noteBatch re-reads the whole notebook by itself.
      await refresh();
      if (nbHeld()) notify("still at it: the guard stays until it commits");
    };
  }

  // Re-read, which is the only way out of stale. It costs whatever is staged,
  // so it says so first.
  // Every view, not just the roadmap. The banner says a session changed *this
  // notebook*, and it holds all four tabs, so the re-read that lifts it has to
  // cover what it held. Reloading only the list is how the Bugs tab could sit
  // there showing what a session had already changed.
  async function reloadViews(){
    await loadRoadmap(nb.memGen);
    if (nb.bugs) await loadBugs();
    await loadMemory(nb.memGen);
    if (!root.querySelector('[data-view="analysis"]').hidden) await loadAnalysis();
  }

  async function rereadRoadmap(){
    if (nb.roadmapPending.length
        && !confirm(`Reload? ${nb.roadmapPending.length} unsaved change`
                    + `${nb.roadmapPending.length === 1 ? "" : "s"} of yours would go: `
                    + "the notebook is being replaced with what is on disk."))
      return;
    revertPending();
    nb.roadmapOrdering = false;
    nb.roadmapStale = false;
    await reloadViews();
  }

  // One button for the panel: the list's changes are already on disk, the
  // memory editor's are not, and either way this is what tells a session. Dead
  // rather than absent, so the footer does not move about under a thumb.
  function syncSave(){
    const q = $("roadmapSaveQuiet");
    if (!q) return;
    const dirty = nb.roadmapUnsaved.roadmap || nb.roadmapUnsaved.memory || memDirty()
                  || nb.roadmapPending.length > 0 || nb.verStagedCount() > 0
                  || nb.ruleStagedCount() > 0 || nb.designStagedCount() > 0;
    // Held while a session is mid-batch, and again until the list is re-read
    // after one finishes. Reverting is still allowed either way: throwing away
    // your own unsaved work never depends on what anybody else is doing.
    const held = nbHeld();
    q.disabled = !dirty || held;
    // A panel holding unsaved work stops re-reading, which is right, since a
    // redraw would eat the typing, and it used to say nothing while it did
    // (B199): stage one line, go to lunch, and the list on screen was the
    // pre-lunch one until Save was refused an op at a time. Said once, where
    // the Save is, and true of all three halves now that the rules check
    // their revision too.
    if (!dirty) nb.movedUnder = false;
    const mv = $("roadmapMoved");
    if (mv){
      mv.hidden = !(dirty && nb.movedUnder);
      mv.textContent = mv.hidden ? "" : "this has changed since you loaded it: Save will ask which version wins";
    }
    // Revert answers the same question the Saves do, from the other side.
    const rv = $("roadmapRevert");
    if (rv){
      rv.disabled = !(nb.roadmapPending.length || memDirty() || nb.verStagedCount()
                      || nb.ruleStagedCount() || nb.designStagedCount());
      rv.title = rv.disabled ? "nothing unsaved to throw away"
        : "throw away what has not been saved: the list and the memory editors "
          + "go back to what is on disk";
    }
    q.title = held
      ? (nb.roadmapBatch ? "a session is part-way through changing this list"
                   : "a session changed this list: reload it before saving over it")
      : "save every change here; a session running here hears about it on its "
        + "next prompt";
  }

  // ---- who else is in here ---------------------------------------------------
  // Roadmap #26's other half. A refusal makes a collision safe; this is what
  // stops most of them happening: the line says who else has this notebook
  // open before the typing starts, rather than after it.
  //
  // Ridden on the poll rather than on a timer of its own: the panel is already
  // asking the server something every fifteen seconds, and a second clock would
  // be a second thing to get wrong. The request is not awaited: presence is
  // the least important thing on this page, and nothing else waits for it.
  nb.nbWhere = "briefing"; nb.nbHere = []; nb.nbRead = 0;

  async function beat(leave, keepalive){
    if (!nb.memProj) return;
    try{
      const r = await fetch("/api/presence", {method: "POST",
        headers: {"Content-Type": "application/json"},
        // A leave sent as the page goes away (pagehide) has to outlive the
        // page: keepalive is what lets it arrive after the page has gone.
        keepalive: !!keepalive,
        body: JSON.stringify({project: nb.memProj, client: nbClient,
                              where: nb.nbWhere, ...(leave ? {leave: 1} : {})})});
      const j = await r.json();
      if (leave || !j.ok) return;
      nb.nbHere = j.here || []; nb.nbRead = j.read || 0;
      drawHere();
    }catch(e){ /* the least important thing on the page */ }
  }

  // Named, not counted. "2 others" is a number somebody then has to go and
  // identify; the whole value of this line is knowing WHO, and on a phone the
  // names are shorter than the sentence explaining there are two of them.
  const WHERE_IS = {memory: "Memory", roadmap: "Roadmap", bugs: "Bugs",
                    analysis: "Analysis", artifacts: "Artifacts", design: "Design", wiki: "Wiki"};

  function drawHere(){
    const el = $("nbHere");
    if (!el) return;
    const bits = nb.nbHere.map(o =>
      `${o.mine ? "your other window" : esc(o.who)}${
        WHERE_IS[o.where] ? ` (${WHERE_IS[o.where]})` : ""}`);
    // A session that has gone and read the list, which is a different claim
    // from having been told: being told rides in on its next prompt (#27), and
    // what the operator wants to know after changing something is whether it
    // has actually looked.
    const read = nb.nbRead ? `a session here last read the roadmap ${ago(nb.nbRead)}` : "";
    const line = [bits.length ? "Also open: " + bits.join(", ") : "", read]
      .filter(Boolean).join(" · ");
    el.hidden = !line;
    el.innerHTML = line ? `<span class="hint">${line}</span>` : "";
  }

  // What is unsaved here, in the words the buttons use. Both halves, because
  // both Saves write both and a Revert that left one behind would be a trap.
  function nbUnsaved(){
    const n = nb.roadmapPending.length;
    const v = nb.verStagedCount();
    return [n ? `${n} change${n === 1 ? "" : "s"} to the list` : "",
            memDirty() ? "an edited memory" : "",
            nb.ruleStagedCount() ? "an edited rule" : "",
            nb.designStagedCount() ? "an unsaved design" : "",
            wikiDirty() ? "a wiki page being edited" : "",
            v ? `${v} staged version bump${v === 1 ? "" : "s"}` : ""]
      .filter(Boolean).join(" and ");
  }
  // Set by the notebook's version block and its rules; the panel-level Save and
  // Revert are outside those closures and need a way to ask.
  nb.ruleStagedCount = () => 0;
  nb.ruleCommitStaged = async () => {};
  nb.ruleClearStaged = () => {};
  nb.verStagedCount = () => 0;
  nb.verCommitStaged = async () => {};
  nb.verClearStaged = () => {};

  // Throw the unsaved changes away. What Close used to do on the way out, now
  // that there is no way out to do it on: the tab stays, so this is the only
  // thing left for a button beside Save to mean.
  async function revertNotebook(){
    const what = nbUnsaved();
    if (!what) return;
    if (!confirm(`Revert ${what}?\n\nIt goes back to what is on disk.`)) return;
    revertPending();
    nb.verClearStaged();
    nb.ruleClearStaged();
    nb.designClearStaged();
    nb.roadmapOrdering = false;
    redrawRoadmap();
    nb.memEditing.clear();
    await loadMemory(nb.memGen);       // drops whatever the editors were holding
  }

  // A notebook tab going away takes whatever is unsaved in it with it, so it is
  // the one tab close that asks. Answered here rather than in hideTab, which is
  // shared by every kind and should not learn about any of them.
  function notebookLeaving(){
    const what = nbUnsaved();
    // The seat would time out on its own in under a minute; saying so is what
    // stops the other window claiming somebody is here who has just left.
    if (!what){ beat(true); return true; }
    if (!confirm(`Close without saving? ${what} would be dropped.`)) return false;
    revertPending();
    nb.roadmapOrdering = false;
    beat(true);
    nb.memGen++; nb.memProj = null;
    return true;
  }
  // Save writes whatever the memory editor is holding, replays whatever the
  // list has staged, and settles the panel. It says nothing to a running
  // session and does not need to: the hook every session runs under carries the
  // news back on the next prompt it is given (roadmap #27).
  async function saveAll(){
    const b = $("roadmapSaveQuiet"), was = b.textContent;
    busy(b, "Saving");
    // Everything staged, replayed in the order it was made, which is what makes
    // the server arrive at what is on screen.
    nb.clashResume = () => saveAll();
    await flushPending();
    // A refusal stops the replay with the op still at the head of the queue and
    // the band asking which version wins. Settling it calls this again from the
    // top, so nothing further here should run in the meantime: writing the
    // memories and settling the panel while a roadmap change is still unwritten
    // would report "saved" over work that is not.
    if (nb.roadmapPending.length){ unbusy(b, was); syncSave(); return; }
    nb.clashResume = null;
    // Before the memory write and the settle: a bump is a git commit, and if it
    // is going to refuse (a staged VERSION, a hand edit in the worktree) the
    // operator should hear that instead of "saved".
    const verMsg = await nb.verCommitStaged();
    await nb.ruleCommitStaged();
    const dsMsg = await nb.designCommitStaged();
    if (memDirty()) await saveMemory(true);
    const j = await postRoadmap({action: "save"});
    await loadMemory(nb.memGen);
    // Out of the busy state, and no further: the button stays disabled, which
    // is what a finished save leaves. Asking syncSave here instead re-enabled
    // it for as long as it took the answer's `unsaved` to land, and a second
    // Save pressed into that window is a save of nothing.
    b.removeAttribute("aria-busy");
    b.textContent = was;
    // Committed, so there is nothing left for a Cancel to go back to.
    nb.roadmapWas = null;
    if (j) notify([verMsg, dsMsg, "saved: the session reads it on its next prompt"]
                  .filter(Boolean).join(" · "));
  }
  $("roadmapSaveQuiet").onclick = () => saveAll();
  $("roadmapRevert").onclick = revertNotebook;

  // ---- the four views ------------------------------------------------------
  function setNbView(v){
    // Which view somebody is on is half of what the presence line says, so it
    // is reported on the switch rather than waiting for the next poll: the
    // other window would otherwise name the tab this one just left.
    if (nb.nbWhere !== v){ nb.nbWhere = v; beat(); }
    nbViewMemo.keep(project, v);
    root.querySelectorAll(".nbtabs button").forEach(b => {
      const on = b.dataset.v === v;
      b.classList.toggle("on", on);
      // The strip scrolls on a narrow screen, so the tab that just became
      // current has to be brought into it: arriving on a view whose own tab
      // is off the end of the strip reads as nothing having happened.
      if (on) b.scrollIntoView({block: "nearest", inline: "nearest"});
    });
    // The incoming view arrives on the same fade content does: one vocabulary
    // for "this is here now", rather than a tab switch being the one place on
    // the page where something simply appears.
    root.querySelectorAll(".nbview").forEach(x => {
      const show = x.dataset.view === v, wasHidden = x.hidden;
      x.hidden = !show;
      if (show && wasHidden && !noMotion()){
        x.classList.remove("justpainted");
        void x.offsetWidth;
        x.classList.add("justpainted");
      }
    });
    // Save and Revert belong to the views that stage: roadmap, briefing and
    // the version on Artifacts. Bugs, tests and findings write through, and
    // a Save under a list nothing stages read as a button that did nothing.
    $("nbFoot").hidden = ["bugs", "analysis", "tests", "git", "docker", "wiki"].includes(v);
    if (v === "git") loadGit();
    if (v === "docker") loadNbDocker();
    if (v === "bugs" && !nb.bugs) loadBugs();
    if (v === "analysis") loadAnalysis();
    if (v === "design") loadDesign();
    if (v === "wiki") loadWiki();
    if (v === "artifacts"){ loadArtifacts(); loadVersion(); }
    if (v === "tests" && !nb.tests) loadTests();
    // The rules once; the code base every time the view is shown, since a
    // commit moves it and the server answers from its cache when not.
    if (v === "briefing"){
      if (!nb.ruleData) loadRules(); else loadCodebase().then(() => drawRules());
      // Once, on the first show. It is re-read when one of the three stores
      // behind it moves, and only while this view is the one on screen.
      if (!nb.preData) loadPreamble();
      // Every show: the brief leaves the tree when the first session starts,
      // which can be while this notebook sits open.
      loadBrief();
    }
  }
  // Unsaved work does not follow you to another tab.
  //
  // It used to: the roadmap's staged changes and a half-edited memory both
  // sat in variables that no tab switch touched, so you could leave an edit
  // on Memory, do something on Bugs, and meet it again later with no memory
  // of having made it, and Save, from over there, would write it. So leaving
  // asks, and answering yes throws it away. Same question the tab close asks,
  // for the same reason, in the one other place work can be walked away from.
  //
  // Only the operator's own click is guarded, never setNbView itself: the
  // panel opens itself on a view sometimes (a findings row asks for Analysis),
  // and nothing is unsaved a moment after opening.
  async function leaveNbView(v){
    const cur = root.querySelector(".nbview:not([hidden])")?.dataset.view;
    if (v === cur) return true;
    const what = nbUnsaved();
    if (!what) return true;
    if (!confirm(`Leave this tab? ${what} would be thrown away.\n\n`
                 + "Unsaved work does not carry across the tabs: Save it "
                 + "first if you want to keep it.")) return false;
    revertPending();
    nb.verClearStaged();
    nb.ruleClearStaged();
    nb.designClearStaged();
    nb.wikiClear();
    nb.roadmapOrdering = false;
    redrawRoadmap();
    nb.memEditing.clear();
    await loadMemory(nb.memGen);     // drops whatever the editors were holding
    return true;
  }
  root.querySelectorAll(".nbtabs button").forEach(b =>
    b.onclick = async () => { if (await leaveNbView(b.dataset.v)) setNbView(b.dataset.v); });
  $("bugSort").onchange = drawBugs;
  // What this notebook watches. Registered once per instance, and only ever
  // acted on while the view in question is actually on screen: a token
  // moving for a tab nobody is looking at is not worth a fetch.
  const showing = v => !root.querySelector(`[data-view="${v}"]`).hidden;
  // A write of this panel's own, still out on the wire.
  //
  // The token moves when the SERVER takes the write; the number this panel
  // compares against moves when the ANSWER gets back. A poll landing between
  // the two reads this panel's own write as somebody else's and re-reads the
  // list, which detaches whatever inline box is open under the finger that
  // opened it. The window is a few tens of milliseconds against a poll every
  // second and a half, so it is about one edit in thirty: rare enough to look
  // like a glitch and common enough to meet.
  //
  // Counted, because several can be out at once, and answered rather than
  // dropped: when the last one lands the same questions are asked again, so
  // a change somebody else made during the write is late by a moment instead
  // of lost until the next one.
  let nbWriting = 0;
  const writing = async fn => {
    nbWriting++;
    try { return await fn(); }
    finally { if (!--nbWriting) for (const [key, news, read] of HALVES){
                const k = key(); if (news(k)) read(); } }
  };
  // Every watch this notebook takes, so destroy() can put them all down
  // again. A closed notebook that goes on watching goes on fetching: its
  // root is detached, not gone, and `showing` reads .hidden off it happily.
  const unwatch = [];
  const watch = (k, fn) => unwatch.push(onRev(k, fn));
  nb.watch = watch;
  watch(() => `dist:${project}`, () => {
    if (showing("artifacts")){ loadArtifacts(); loadVersion(); }
  });
  // A session bumping while this tab is open, and the policy changing from
  // anywhere else. Both are file mtimes on the server: neither costs a git
  // call to notice.
  watch(() => `ver:${project}`, () => { if (showing("artifacts")) loadVersion(); });
  watch("vpolicy", () => { if (showing("artifacts")) loadVersion(); });
  watch("devapp", () => { if (showing("artifacts")) loadArtifacts(); });
  // A commit changes what the dev row says about the build being current,
  // and what the version block computes since the target last moved.
  watch(() => `git:${project}`, () => {
    if (showing("artifacts")){ loadArtifacts(); loadVersion(); }
    if (showing("git")) loadGit();
  });
  watch("phone.dev", () => { if (showing("artifacts")) loadArtifacts(); });
  watch("reports", () => { if (showing("analysis")) loadAnalysis(); });
  watch(() => `wiki:${project}`, k => { if (showing("wiki") && wikiNews(k)) loadWiki(); });
  watch("findings", () => { if (showing("analysis")) loadAnalysis(); });

  // ---- the notebook's own six halves ---------------------------------------
  // All six on this poll, which is the whole of what a view is allowed to
  // wait on. Five of them used to ride a per-project counter on /api/status
  // instead, so the Bugs tab noticed a session's write in a second and a half
  // and the Roadmap beside it took fifteen: one tab, two clocks, and nothing
  // choosing between them.
  //
  // Each compares against the number the PANEL last read rather than
  // reloading on any move, because the token moves for this panel's own write
  // too, and a redraw it did not need detaches whatever inline box is open:
  // a send box, a drop confirmation, a half-typed description, under the
  // finger that opened it. That is also why these are counters on the server
  // and not file mtimes: an mtime cannot tell the echo from the news.
  //
  // The guards are each half's own, and they are not decoration: the roadmap
  // and the memory editor may be holding work the server has never seen, so
  // they re-read only with nothing to lose. Bugs, tests and the queue write
  // through and have nothing to lose by definition.
  //
  // Written once as a list: the token, whether a move of it is news for this
  // panel, and what to re-read, because two things ask these questions: the
  // poll, and the moment a write of this panel's own settles. They have to
  // ask the same ones.
  const HALVES = [
    [() => `roadmap:${project}`,
     k => nb.roadmapRev !== null && revs[k] > nb.roadmapRev
          && !nb.roadmapPending.length && !nb.clash && !nbHeld(),
     () => loadRoadmap(nb.memGen)],
    [() => `mem:${project}`,
     k => nb.memRev !== null && revs[k] && revs[k] !== nb.memRev
          && !memDirty() && !nb.memClash && !nbHeld(),
     () => loadMemory(nb.memGen)],
    [() => `bug:${project}`,
     k => nb.bugs && nb.bugRev !== null && revs[k] !== nb.bugRev,
     () => loadBugs()],
    [() => `tests:${project}`,
     k => nb.tests && nb.testsRev !== null && revs[k] !== nb.testsRev,
     () => loadTests()],
    [() => `rules:${project}`,
     k => nb.ruleData && nb.rulesRev !== null && revs[k] !== nb.rulesRev && !ruleDirty(),
     () => loadRules()],
    [() => `pending:${project}`,
     k => nb.pendRev !== null && revs[k] !== nb.pendRev,
     () => loadPending()],
  ];
  for (const [key, news, read] of HALVES)
    watch(key, k => { if (!nbWriting && news(k)) read(); });
  // ...and the other half of each guard: the token moved and the panel did NOT
  // re-read, because it is holding work. That is the moment to say so (B199).
  const MOVED = [
    [() => `roadmap:${project}`, k => nb.roadmapRev !== null && revs[k] > nb.roadmapRev && nb.roadmapPending.length > 0],
    [() => `mem:${project}`, k => nb.memRev !== null && revs[k] && revs[k] !== nb.memRev && memDirty()],
    [() => `rules:${project}`, k => nb.ruleData && nb.rulesRev !== null && revs[k] !== nb.rulesRev && ruleDirty()],
  ];
  for (const [key, moved] of MOVED)
    watch(key, k => { if (!nbWriting && moved(k)){ nb.movedUnder = true; syncSave(); } });
  // The block a session is handed is the first, third and fifth of those
  // joined, so it is stale the moment any of them moves. Only re-read while
  // somebody is looking at it: it is a fold that is shut by default, and
  // fetching a few kilobytes for a closed fold on every roadmap edit is the
  // kind of cost nobody chooses.
  for (const half of ["rules", "roadmap", "bug"])
    watch(() => `${half}:${project}`,
          () => { if (showing("briefing")) loadPreamble(); });

  // ---- the handle the rest of the page holds ------------------------------
  let dkSeen = "";
  async function loadNbDocker(){
    const p = (state?.projects || []).find(x => x.name === project);
    const node = p?.prefs?.node || dockerNode || "";
    let got;
    try{
      got = await (await fetch("/api/docker" + (node ? "?node=" + encodeURIComponent(node) : ""))).json();
    }catch(e){ $("dkHint").textContent = "could not read the manager: " + e; return; }
    dockerSeen[got.node || node || ""] = got;
    // What belongs to the project, which is the Docker tab's group for it.
    const mine = (got.instances || []).filter(d => d.owner === project);
    const others = (got.containers || []).filter(c => c.owner === project);
    const job = got.job && (got.job.running || got.job.error) ? got.job : null;
    const blind = !!(got.blind || got.error || got.on === false);
    const where = (nodesList || []).find(n => n.id === (got.node || node))?.name || "its node";
    const n = mine.length + others.length;
    $("dkHint").textContent = n
      ? `${n} container${n === 1 ? "" : "s"} of ${project}'s on ${where}${
          blind ? ": the daemon did not answer, so the rows cannot say what is running" : ""}`
      : `nothing belongs to ${project} on ${where} yet: send it from the Artifacts tab, or pick ${project} on a container's row on the Docker tab`;
    const key = JSON.stringify([mine, others, job && job.step, job && job.running, job && (job.log || "").length]);
    if (key === dkSeen) return;
    dkSeen = key;
    $("dkList").innerHTML = dmRowsHtml(mine, job, blind) + dmOtherRowsHtml(others);
    tipify($("dkList"));
    dmWireRows($("dkList"), got);
  }
  $("dkOpen").onclick = () => openDocker();

  nb.writing = writing;

  return {
    root, project,
    // First show loads; later shows are just the pane coming back.
    shown(){ if (!nb.loaded){ nb.loaded = true; openMemory(project); loadPending(); } },
    reloadPending: loadPending,
    reload(){ return loadRoadmap(nb.memGen); },
    reloadMemory(){ return loadMemory(nb.memGen); },
    reloadBugs(){ return loadBugs(); },
    reloadTests(){ return loadTests(); },
    leaving: notebookLeaving,
    held: nbHeld,
    unsaved: nbUnsaved,
    view: setNbView,
    poll(p){
      noteBatch(p.todo_batch); drawBatchNote(); syncSave();
      beat();                       // and who else is in here (roadmap #26)
      // A session started (or ended) under an open notebook.
      //
      // Whether a step can be sent is a fact about the session running beside
      // it, and that fact arrived only with the list, which is fetched when
      // the notebook opens and then not again. So starting Claude while
      // looking at the Roadmap left every arrow gray, correctly describing
      // the world as it had been when the tab opened, until the tab was
      // closed and reopened. It is read off the poll now, like everything
      // else on this row.
      //
      // Redrawn from what is already in hand rather than re-fetched: the list
      // on screen may be carrying staged changes that are not on the server,
      // and a refetch here would quietly throw them away.
      const want = myClaude(project);
      const now = (state?.sessions || []).some(x => x.name === want) ? want : null;
      if (now !== nb.roadmapSession){ nb.roadmapSession = now; redrawRoadmap(); }
      // The Docker view follows a running job the way the tab does.
      if (!root.querySelector('[data-view="docker"]').hidden) loadNbDocker();
      // What this notebook re-reads and when is declared once, up where the
      // watches are taken; nothing here decides it. All six halves are on
      // the revisions poll; this poll carries only what /api/status alone
      // knows, which for a notebook is the batch note and who else is in here.
      // A scan re-ran while the Analysis view is up: re-read. The cache was
      // dropped by refresh() when the mtime moved, so this is one fetch.
      if (!root.querySelector('[data-view="analysis"]').hidden
          && nb.anaStamp !== (state?.reports_mtime ?? null))
        loadAnalysis();

    },
    escape(){ if (nb.roadmapSel){ cancelSend(); redrawRoadmap(); return true; } return false; },
    // Says this tab has left the notebook without taking the notebook down:
    // the page is going (see the pagehide listener by getNotebook).
    leave(){ return beat(true, true); },
    destroy(){
      beat(true);
      unwatch.forEach(off => off());
      nbViewMemo.keep(project, null);
      notebooks.delete(project);
      root.remove();
    },
  };
}
