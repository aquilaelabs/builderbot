// The notebook itself: one per project, each a clone of #nbTpl with its
// state in one closure (makeNotebook), so two open in a split share
// nothing. The views are the nb-*.js files beside this one; this is the
// frame they draw into, with its own strip, its presence line and its
// save.
//
// One classic script beside index.html (docs/design-language.md, Files):
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
  openTab({kind: "notebook", arg: name, label: "Notebook: " + projLabel(name)});
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
  nb.groupLast = {};                 // a view group's last view, so its button returns there (R259)
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
  // How many memories the tab found (null until read), for the glance that
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
  const {loadPerms, leavePerms, drawPush} = nbPermsView({$, nb, project, root});
  const {loadSessions} = nbSessionsView({$, nb, project, root});
  // Each section's Save and Revert (see sectBar): published before the views
  // are made, since they register their sections as they are.
  nb.stagers = {}; nb.sectBar = sectBar; nb.stage = stage;
  const {loadArtifacts, loadVersion, drawVersion, postArtifacts, postVersion} = Object.assign(nb, nbArtifactsView({$, nb, project, root, sheet}));
  const {loadSigning} = Object.assign(nb, nbSigningView({$, nb, project}));
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
  // Escape is modalKeys' (page-motion.js), which reaches the backdrop's
  // closeSheet above. A filter field holding a search clears the field on
  // Escape and stops the event, so the sheet stays open for that one.

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
    $("memTitle").textContent = "Notebook: " + projLabel(name);
    nb.memN = null; briefingHead();
    $("memDrift").innerHTML = $("memList").innerHTML = $("memAdd").innerHTML = "";
    nb.roadmapSel = null;                 // the send box lives on the row, and the
    nb.roadmapOrdering = false;           // rows are about to be replaced wholesale
    nb.roadmapPending = []; nb.roadmapWas = null;
    nb.roadmapBatch = null; nb.roadmapStale = false;
    nb.roadmapRev = nb.memRev = null;
    nb.clash = nb.memClash = null; nb.clashResume = null;
    nb.nbRead = 0; nb.nbWhere = "briefing"; drawHere();
    nb.tests = null; nb.testsRev = null;
    nb.tstSuite = ""; nb.tstFlagged = nb.tstUndoc = false;
    nb.roadmapLogOn = false;
    nb.roadmapLog = null;
    nb.roadmapDone = null; nb.roadmapChip = ""; nb.roadmapVer = ""; nb.roadmapFind = ""; nb.roadmapFinishedN = 0;
    nb.roadmapDoneAsking = false;
    nb.bugChip = ""; nb.bugVer = ""; nb.bugFind = "";
    $("roadmapFind").value = ""; $("bugFind").value = "";
    $("histFind").value = "";
    cancelSend();
    $("roadmapText").value = "";
    $("roadmapForm").hidden = true; $("roadmapAddBar").hidden = true; $("roadmapShow").setAttribute("aria-expanded", "false");
    $("roadmapList").innerHTML = `${skel("rows")}`;
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
    setHidden(el, !nb.roadmapBatch && !nb.roadmapStale);
    if (el.hidden){ if (el.firstChild) el.innerHTML = ""; return; }
    const n = nb.roadmapBatch?.changes || 0;
    const mins = nb.roadmapBatch?.at ? Math.max(1, Math.round((Date.now() / 1000 - nb.roadmapBatch.at) / 60)) : 0;
    paint(el, nb.roadmapBatch?.stale
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
         <button type="button" id="roadmapReread">Reload the list</button></div>`, true);
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
      busy(rc, "Checking");
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
        && !await askYes(`Reload? ${nb.roadmapPending.length} unsaved change`
                    + `${nb.roadmapPending.length === 1 ? "" : "s"} of yours would go: `
                    + "the notebook is being replaced with what is on disk."))
      return;
    revertPending();
    nb.roadmapOrdering = false;
    nb.roadmapStale = false;
    await reloadViews();
  }

  // ---- a section's own Save and Revert (the operator, 5 Oct) ------------------
  // Every section that stages anything carries its own Save and Revert at its
  // foot, and they write or throw away that section's changes and nothing
  // else. There was one pair at the bottom of the tab, and on a phone a
  // change made near the top was a long scroll from the button that saved it,
  // past sections that had nothing to do with it. A stager is what a section
  // registers: how many changes it holds, what they are in words, how to
  // write them (a message, or null when a clash stopped it part-way) and how
  // to throw them away.
  function stage(key, st){ nb.stagers[key] = st; }
  // The bar, drawn by whichever view draws the section; dead rather than
  // absent while there is nothing to save, so it does not move under a thumb.
  function sectBar(key){
    // Drawn as syncSave would leave it, its words and its dead buttons with
    // it (B2): a view whose draw did not call syncSave after (the rules')
    // left the bar untitled until whatever synced next, and that wrote two
    // titles into a status read that brought nothing.
    const b = barSays(key);
    // In a field band, as every line of a section's body is (a-dialog/layout):
    // bare, it sat beside the last row it followed rather than under it.
    return `<div class="field"${key === "roadmap" && b.hide ? " hidden" : ""}>${saveBar({
      save: `data-ssave="${esc(key)}" title="${esc(b.saveTitle)}"${b.saveDead ? " disabled" : ""}`,
      revert: `data-srevert="${esc(key)}" title="${esc(b.rvTitle)}"${b.rvDead ? " disabled" : ""}`,
      state: esc(b.state), cls: "sectbar", attrs: `data-bar="${esc(key)}"`})}</div>`;
  }
  // What a section's bar says and which of its buttons are dead, the one
  // answer sectBar draws and syncSave keeps.
  function barSays(key){
    const st = nb.stagers[key], n = st?.count() || 0, held = nbHeld();
    return {
      hide: !(n > 0 || sectDirty(key) || nb.roadmapOrdering),
      saveDead: !sectDirty(key) || (key === "roadmap" && held),
      rvDead: !n,
      rvTitle: n ? `throw away ${st.what()}: it goes back to what is on disk` : "nothing unsaved here to throw away",
      saveTitle: key === "roadmap" && held
        ? (nb.roadmapBatch ? "a session is part-way through changing this list"
                           : "a session changed this list: reload it before saving over it")
        : "save this section; a session running here hears about it on its next prompt",
      // A panel holding unsaved work stops re-reading, since a redraw would
      // eat the typing (B199); said where the Save is, once something here
      // has moved under it. A Save lit with nothing staged is the change no
      // session has been told about yet, which says so rather than sitting
      // there unexplained.
      state: n && nb.movedUnder ? "this has changed since you loaded it: Save will ask which version wins"
        : n ? `${n} unsaved` : sectDirty(key) ? "changed, not told to the session yet" : ""};
  }
  // A section holding unsaved work, or a change no session has been told
  // about yet, which the roadmap's and the memories' Saves settle.
  function sectDirty(key){
    const st = nb.stagers[key];
    if (!st) return false;
    return st.count() > 0 || (key === "roadmap" && !!nb.roadmapUnsaved.roadmap)
      || (key === "briefing:memories" && !!nb.roadmapUnsaved.memory);
  }
  function syncSave(){
    // Held while a session is mid-batch, and again until the list is re-read
    // after one finishes; that is the list's own business, so it holds only
    // the roadmap's Save. Reverting is allowed either way: throwing away your
    // own unsaved work never depends on what anybody else is doing.
    if (![...Object.keys(nb.stagers)].some(k => nb.stagers[k].count() > 0)) nb.movedUnder = false;
    root.querySelectorAll(".sectbar[data-bar]").forEach(bar => {
      const key = bar.dataset.bar, st = nb.stagers[key];
      const save = bar.querySelector("[data-ssave]"), rv = bar.querySelector("[data-srevert]");
      if (!st || !save || !rv || save.getAttribute("aria-busy")) return;
      const b = barSays(key);
      // The Roadmap's bar is its status line (R109), and its Save and Revert
      // are the ones that sat dead most of the time (R224): they appear with
      // a reorder or an edit staged, and go with the Save. The rest stay,
      // dead, so they do not move under a thumb.
      if (key === "roadmap"){ setHidden(save, b.hide); setHidden(rv, b.hide); }
      setDisabled(save, b.saveDead);
      setDisabled(rv, b.rvDead);
      setTitle(rv, b.rvTitle);
      setTitle(save, b.saveTitle);
      // ...its words what is staged, before the session's (.stg).
      setText(bar.querySelector(".state .stg") || bar.querySelector(".state"), b.state);
    });
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
  nb.nbWhere = "briefing"; nb.nbRead = 0;

  // This notebook is the page on show, not one left behind another page.
  const nbOnShow = () => { const t = tabOf(panes[0]); return t?.kind === "notebook" && t.arg === project; };

  async function beat(leave, keepalive){
    if (!nb.memProj) return;
    // Not for a project this account no longer has (deleted, or taken off
    // it): the server answers that with a 400 on every poll (B65), and
    // there is no one there to say anything to.
    if (state && !(state.projects || []).some(p => p.name === nb.memProj)) return;
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
      nb.nbRead = j.read || 0;
      drawHere();
    }catch(e){ /* the least important thing on the page */ }
  }

  // Who else has the notebook open is no longer said (the operator, 17 Oct:
  // not necessary): two windows writing one item are caught at the save,
  // which refuses the second and shows both. The heartbeat stays for what a
  // session has read, said on the Roadmap's status line.
  function drawHere(){
    // A session that has gone and read the list, which is a different claim
    // from having been told: being told rides in on its next prompt (#27), and
    // what the operator wants to know after changing something is whether it
    // has actually looked. The Roadmap's fact, on its status line (R222): it
    // stood over every view.
    const rd = $("roadmapRead");
    if (rd) rd.textContent = nb.nbRead ? ` · read by a session ${ago(nb.nbRead)}` : "";
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
            nb.signStagedCount() ? "a staged signing key change" : "",
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

  // A notebook tab going away takes whatever is unsaved in it with it, so it is
  // the one tab close that asks. Answered here rather than in hideTab, which is
  // shared by every kind and should not learn about any of them.
  async function notebookLeaving(){
    const what = nbUnsaved();
    // The seat would time out on its own in under a minute; saying so is what
    // stops the other window claiming somebody is here who has just left.
    if (!what){ beat(true); return true; }
    if (!await askYes(`Close without saving?\n\n${what} would be dropped.`, {verb: "Close without saving", danger: true})) return false;
    revertPending();
    nb.roadmapOrdering = false;
    beat(true);
    nb.memGen++; nb.memProj = null;
    return true;
  }
  // One section's Save: its own changes written, then the marker settled, so
  // a session running here hears about it on its next prompt (roadmap #27).
  async function saveSection(key, b){
    const st = nb.stagers[key];
    if (!st) return;
    const was = b.textContent;
    busy(b, "Saving");
    const msg = await st.save();
    // A refused roadmap change stops the replay with the op still queued and
    // the band asking which version wins; settling it calls this again.
    if (msg === null){ unbusy(b, was); syncSave(); return; }
    const j = await postRoadmap({action: "save"});
    b.removeAttribute("aria-busy");
    b.textContent = was;
    syncSave();
    if (j) notify([msg, "saved: the session reads it on its next prompt"].filter(Boolean).join(" · "));
  }
  async function revertSection(key){
    const st = nb.stagers[key];
    if (!st || !st.count()) return;
    if (!await askYes(`Revert ${st.what()}?\n\nIt goes back to what is on disk.`)) return;
    await st.revert();
    syncSave();
  }
  root.addEventListener("click", e => {
    const sv = e.target.closest("[data-ssave]"), rv = e.target.closest("[data-srevert]");
    if (sv && !sv.disabled){ e.preventDefault(); saveSection(sv.dataset.ssave, sv); }
    if (rv && !rv.disabled){ e.preventDefault(); revertSection(rv.dataset.srevert); }
  });
  // The two halves this file holds: the roadmap's list and the memories.
  stage("roadmap", {
    count: () => nb.roadmapPending.length,
    what: () => `${nb.roadmapPending.length} change${nb.roadmapPending.length === 1 ? "" : "s"} to the list`,
    save: async () => {
      nb.clashResume = () => saveSection("roadmap", root.querySelector('[data-ssave="roadmap"]'));
      await flushPending();
      if (nb.roadmapPending.length) return null;
      nb.clashResume = null;
      nb.roadmapWas = null;     // committed: nothing left for a Cancel to go back to
      return "";
    },
    revert: () => { revertPending(); nb.roadmapOrdering = false; redrawRoadmap(); }});
  // The Memories section is markup rather than a draw: wired here, once.
  wireSections(root.querySelector('.nbview[data-view="briefing"]'));
  stage("briefing:memories", {
    count: () => memDirty() ? 1 : 0,
    what: () => "the edited memories",
    save: async () => { if (memDirty()) await saveMemory(true); await loadMemory(nb.memGen); return ""; },
    revert: async () => { nb.memEditing.clear(); await loadMemory(nb.memGen); }});

  // ---- the four views ------------------------------------------------------
  function setNbView(v){
    // Which view somebody is on is half of what the presence line says, so it
    // is reported on the switch rather than waiting for the next poll: the
    // other window would otherwise name the tab this one just left.
    if (nb.nbWhere !== v){ nb.nbWhere = v; beat(); }
    nbViewMemo.keep(project, v);
    shellSync();                    // the address names the view (R218 step 3)
    // Its group lit in the top row and the group's views in the row under it
    // with this one lit (R259), so the row is always there and every view's
    // head at one height; Settings sits beside Overview in its group. The
    // view is the group's to come back to.
    const me = root.querySelector(`.nbtabs button[data-v="${CSS.escape(v)}"]`);
    const g = me?.dataset.in || me?.dataset.g || "";
    if (g) nb.groupLast[g] = v;
    root.querySelectorAll(".nbtabs .nbgroups button").forEach(b => {
      const on = b.dataset.g === g;
      if (b.classList.contains("on") !== on) b.classList.toggle("on", on);
      b.setAttribute("aria-selected", String(on));
    });
    const sub = root.querySelector(".nbtabs .nbsub");
    sub?.querySelectorAll("button").forEach(b => {
      const mine = b.dataset.in === g, on = b.dataset.v === v;
      if (b.hidden === mine) b.hidden = !mine;
      if (b.classList.contains("on") !== on) b.classList.toggle("on", on);
      b.setAttribute("aria-selected", String(on));
    });
    // Each strip's line slides to the one pressed (slideMark): the groups'
    // per notebook, the views' per group, so a group's row never slides
    // from another group's.
    slideMark(root.querySelector(".nbtabs .nbgroups"), "nbg:" + project);
    slideMark(sub, "nbv:" + project + ":" + g);
    // A view switched fades through as a rail page does (the operator,
    // 18 Oct): the one going out as a still copy fading on docOut's time,
    // the incoming on docIn's (fadeThrough's halves), rather than a tab
    // switch being the one place on the page where something simply appears.
    let away = null;
    // A view opened anew opens on its first section on a phone.
    if (root.querySelector(`.nbview[data-view="${v}"]`)?.hidden) sectNewVisit();
    root.querySelectorAll(".nbview:not(.fghost)").forEach(x => {
      const show = x.dataset.view === v, wasHidden = x.hidden;
      if (!show && !wasHidden && !noMotion()) away = ghostOf(x);
      x.hidden = !show;
      if (show && wasHidden){ x.classList.remove("justpainted"); fadeIn(x); }
    });
    ghostOut(away);
    // The settings form comes into this view while it is on screen, and goes
    // back to the dialog when another view is picked (page-projsettings.js).
    // ...and its Agents may section into Permissions, which hands it back
    // first whenever another view is shown.
    if (v !== "permissions") leavePerms();
    if (v === "settings") settingsInto(project, root.querySelector('.nbview[data-view="settings"] .nbsettings'));
    else if (rnHost && root.contains(rnHost)) settingsOut();
    if (v === "permissions") loadPerms();
    if (v === "sessions") loadSessions();
    // A view still waiting on its data waits as its markup declares (R109).
    glanceWaiting(root.querySelector(`.nbview[data-view="${v}"] .nbglance`));
    if (v === "git") loadGit();
    if (v === "docker") loadNbDocker();
    if (v === "vms") loadNbVms();
    if (v === "signing") loadSigning();
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
    if (!await askYes(`Leave this tab? ${what} would be thrown away.\n\n`
                 + "Unsaved work does not carry across the tabs: Save it "
                 + "first if you want to keep it.")) return false;
    revertPending();
    nb.verClearStaged();
    nb.ruleClearStaged();
    nb.designClearStaged();
    nb.wikiClear();
    nb.signClearStaged();
    nb.roadmapOrdering = false;
    redrawRoadmap();
    nb.memEditing.clear();
    await loadMemory(nb.memGen);     // drops whatever the editors were holding
    return true;
  }
  // A view's own button opens it; a group's opens the view it was last on,
  // else its first (R259).
  root.querySelectorAll(".nbtabs button").forEach(b =>
    b.onclick = async () => {
      const v = b.dataset.v || nb.groupLast[b.dataset.g]
        || root.querySelector(`.nbtabs .nbsub button[data-in="${CSS.escape(b.dataset.g || "")}"]`)?.dataset.v;
      if (v && await leaveNbView(v)) navPush(() => setNbView(v));
    });
  $("bugSort").onchange = drawBugs;
  $("bugFind").addEventListener("input", () => { nb.bugFind = $("bugFind").value; drawBugs(true); });
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
  // The Docker view re-reads on the manager's token, as the Docker tab
  // does: a job queued, taken or finished, an instance written. Not on the
  // status poll (B727): a read of an agent node's docker is a round trip
  // through its agent, whose heartbeat moves the nodes token, whose watch
  // runs the status poll, which re-read docker again, 134 requests in 30 s.
  watch("devapp", () => { if (showing("docker")) loadNbDocker(); });
  watch("vms", () => { if (showing("vms")) loadNbVms(); });
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
  // This project's VMs as the VMs page draws them, scoped to it (R96): the
  // page's own rows and their presses, the project's card alone.
  async function loadNbVms(){
    try{
      vmsData = await (await fetch("/api/vms")).json();
    }catch(e){ viewGlance($("nvHint"), [], esc("VMs: " + e)); return; }
    const rows = (vmsData.vms || []).filter(v => v.project === project);
    const up = rows.filter(v => v.state === "running").length;
    // The glance (R109): what runs of how many, as the VMs page counts.
    viewGlance($("nvHint"), rows.length ? [{label: "running", value: up, sub: `of ${rows.length} VM${rows.length === 1 ? "" : "s"}`}] : []);
    const may = (vmsData.can || {})[project] === "write";
    const nb = $("nvNew");
    nb.hidden = !may;
    nb.disabled = !(vmsData.hosts || []).length;
    nb.onclick = () => openNewVm(project);
    $("nvOpen").onclick = () => openVmsTab();
    const dial = (state?.projects || []).find(x => x.name === project)?.prefs?.makevms || "deny";
    // What the view is for, as its empty state (R119 step 4).
    $("nvList").innerHTML = rows.length ? vmGroupsHtml(rows)
      : `<div class="field"><div class="hint nbempty">${!(vmsData.hosts || []).length
          ? `No node has VM host yet: a node's Features section on the ${pageLink("nodes", "Nodes page")} installs it.`
          : dial === "deny" ? "A session here may not make VMs (Make VMs is deny in this project's settings); a person makes one with New VM."
          : "A session makes one with bb vm new NAME --os debian, or a person with New VM."}</div></div>`;
    wireVms($("nvList"));
  }

  // This project's containers as the Containers page draws them, scoped to
  // it (the operator, 19 Oct): its tiles, when the images were checked, and
  // its card in the page's cards or list, whichever this browser keeps.
  let dkSeen = "", dkGot = null;
  async function loadNbDocker(){
    const p = (state?.projects || []).find(x => x.name === project);
    const node = p?.prefs?.node || dockerNode || "";
    try{
      dkGot = await (await fetch("/api/docker" + (node ? "?node=" + encodeURIComponent(node) : ""))).json();
    }catch(e){ viewGlance($("dkHint"), [], esc("docker: " + e)); return; }
    dockerSeen[dkGot.node || node || ""] = dkGot;
    drawNbDocker();
  }
  function drawNbDocker(){
    const got = dkGot, node = got.node || "";
    // What belongs to the project, which is the Containers page's group for it.
    const mine = (got.instances || []).filter(d => d.owner === project);
    const others = (got.containers || []).filter(c => c.owner === project);
    const job = got.job && (got.job.running || got.job.error) ? got.job : null;
    const blind = !!(got.blind || got.error || got.on === false);
    const where = (nodesList || []).find(n => n.id === node)?.name || "its node";
    const n = mine.length + others.length;
    // The glance (R109): the Containers page's tiles for the project's own,
    // then its node and when the images were checked, or why the rows
    // cannot say what runs.
    const imgs = !mine.length || !mayDocker() || featureOff("image-updates") ? ""
      : got.images_at ? ` · images checked ${esc(ago(got.images_at))}` : " · images not checked yet";
    viewGlance($("dkHint"), blind || !n ? "" : dmTiles({running: mine.filter(d => d.running).length, all: mine.length,
      behind: mine.filter(d => (d.images_behind || []).length || d.nginx_to).length, checked: !!got.images_at}),
      blind && n ? `on ${esc(where)}: the daemon did not answer, so the rows cannot say what is running`
        : n ? `on ${esc(where)}${imgs}` : "");
    const key = JSON.stringify([mine, others, job && job.step, job && job.running, job && (job.log || "").length,
                                dmView, got.images_at, blind]);
    if (key === dkSeen) return;
    dkSeen = key;
    $("dkSeg").innerHTML = n ? dmViewSeg() : "";
    dmViewWire($("dkSeg"), () => { dkSeen = ""; drawNbDocker(); });
    const ck = $("dkCheck");
    ck.hidden = blind || !mayDocker() || !mine.length;
    ck.onclick = () => dmCheck(ck, node, () => { unbusy(ck, "Check"); ck.insertAdjacentHTML("beforeend", `<span class="lng"> for updates</span>`); loadNbDocker(); });
    // What the view is for, as its empty state (R119 step 4).
    $("dkList").innerHTML = dmGroupsHtml(mine, others, job, blind, project)
      || `<div class="field"><div class="hint nbempty">Send ${esc(projLabel(project))} from ${pageLink("", "Artifacts", `#/projects/${encodeURIComponent(project)}/artifacts`)}, or pick it on a container's row on the ${pageLink("docker", "Containers page")}.</div></div>`;
    dmWireRows($("dkList"), got);
  }
  $("dkOpen").onclick = () => openDocker();

  nb.writing = writing;

  return {
    root, project,
    // First show loads; later shows are just the pane coming back.
    shown(){
      if (!nb.loaded){ nb.loaded = true; openMemory(project); loadPending(); }
      if (nb.away){ nb.away = false; beat(); }
    },
    reloadPending: loadPending,
    reload(){ return loadRoadmap(nb.memGen); },
    reloadMemory(){ return loadMemory(nb.memGen); },
    reloadBugs(){ return loadBugs(); },
    // A roadmap item or a bug by its id (R12, B34), from a link elsewhere
    // (the changelog, R254 step 4): its view, its list narrowed to it.
    find(id){
      const bug = /^b/i.test(id);
      setNbView(bug ? "bugs" : "roadmap");
      if (bug){ nb.bugChip = ""; nb.bugVer = ""; nb.bugFind = id; $("bugFind").value = id; drawBugs(true); }
      else { nb.roadmapChip = ""; nb.roadmapVer = ""; nb.roadmapFind = id; $("roadmapFind").value = id; redrawRoadmap(); }
    },
    reloadTests(){ return loadTests(); },
    leaving: notebookLeaving,
    held: nbHeld,
    unsaved: nbUnsaved,
    view: setNbView,
    where: () => nb.nbWhere,
    // The wiki page on show, for the address, and set from one (R256 step 3).
    wikiPage: () => nb.wkCur,
    wikiAt: name => nb.wikiAt(name),
    // The branch whose comparison is on show, and set from an address (R269 step 2).
    gitPage: () => nb.gitPage?.() || "",
    gitAt: name => nb.gitAt?.(name),
    poll(p){
      noteBatch(p.todo_batch); drawBatchNote(); syncSave();
      // ...and who else is in here (roadmap #26), while this is the page on
      // show: a project page left for another stays in the page model, and
      // it went on saying this person was in its notebook (B765). Off show,
      // it says once that it has left; shown again, it says it is back.
      if (nbOnShow()){ nb.away = false; beat(); }
      else if (!nb.away){ nb.away = true; beat(true); }
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
      // The Docker view follows a job on the devapp token above, never here.
      // What this notebook re-reads and when is declared once, up where the
      // watches are taken; nothing here decides it. All six halves are on
      // the revisions poll; this poll carries only what /api/status alone
      // knows, which for a notebook is the batch note and who else is in here.
      // A scan re-ran while the Analysis view is up: re-read. The cache was
      // dropped by refresh() when the mtime moved, so this is one fetch.
      // What a person changed of the push policy elsewhere, on Permissions.
      if (!root.querySelector('[data-view="permissions"]').hidden) drawPush();
      if (!root.querySelector('[data-view="analysis"]').hidden
          && nb.anaStamp !== (state?.reports_mtime ?? null))
        loadAnalysis();

    },
    escape(){ if (nb.roadmapSel){ cancelSend(); redrawRoadmap(); return true; } return false; },
    // Says this tab has left the notebook without taking the notebook down:
    // the page is going (see the pagehide listener by getNotebook).
    leave(){ return beat(true, true); },
    destroy(){
      // The settings form is one element lent to whichever Settings view
      // shows it: handed back before this notebook's elements go, or it
      // goes with them and every later Settings view is empty.
      leavePerms();
      if (typeof rnHost !== "undefined" && rnHost && root.contains(rnHost)) settingsOut();
      beat(true);
      unwatch.forEach(off => off());
      nbViewMemo.keep(project, null);
      notebooks.delete(project);
      root.remove();
    },
  };
}

// ---- the project page's header (R218 step 3) -----------------------------

// A project is a page: its pane's bar is the header the design names (the
// a-notebook/project-page rule): the name large, the branch and the node in
// the data face, the session's state as the dot and a word, and at the
// right its actions: Start agent, or Open
// Claude in green while yours runs (the chooser under it), Shell, and the rest behind one menu (link, phone, report,
// lock, pin, settings). Drawn by paintBar on every pass like every bar; the
// chooser sits on the pane, not in the bar, so a repaint leaves it up.
// The session's state as the dot and a word: this account's session
// first, then whose else is here, then none. The dot is the one every
// session surface wears.
function projectState(p){
  const name = p.name, mine = liveSessions().has(myClaude(name));
  const busy = new Set((state?.claude_busy || {})[name] || []);
  const one = (st, word, cls = "") => `<span class="pstate${cls}">${st ? `<span class="st ${st}"></span>` : ""}${esc(word)}</span>`;
  // Yours first, then everybody else's with a session here, each with its
  // own dot (the operator, 16 Oct: a card that does not say who else is
  // working in the project hides the one thing worth knowing first).
  // On Claude Code's permission prompt it is asking, in amber, as the dock
  // and Sessions say it (B98), not waiting.
  const asking = mine && claudeOf(myClaude(name))?.state === "asking";
  const me = mine ? (asking ? one("asking", "asking you") : busy.has(state?.me) ? one("working", "working")
    : one("waiting", "waiting for you")) : "";
  // Another account's session on the prompt reads asking too (B104), but
  // not "asking you": only that person's terminal answers it.
  const asks = new Set((state?.claude_asking || {})[tmuxName(name)] || (state?.claude_asking || {})[name] || []);
  const them = othersOn(name).map(n => asks.has(n) ? one("asking", `${n} asking`, " other")
    : one(busy.has(n) ? "working" : "waiting", `${n}${busy.has(n) ? " working" : "'s session"}`, " other")).join("");
  return me || them ? `<span class="pstates">${me}${them}</span>` : one("", "no session");
}
// The one notice a project carries (why nobody can start here, the agent
// out of window), in the notice voice, or nothing.
function projectNote(p){
  const here = withMe(p.name).length > 0;
  // What holds it back is said ahead of a wait that would end by itself
  // (B826: a copy going up was said and the missing Claude Code that really
  // held it never was).
  const held = p.held && !state?.mapping?.[p.name]?.running ? p.held : "";
  // Not this account's to change: nothing is said and Start agent is not
  // drawn (the operator, 21 Oct: a role somebody lacks is not advertised to
  // them, and a reason a button is off is not an error, so no line is red).
  if (!p.locked_me && writeWhy(p)) return "";
  // No Claude Code on its node, for an account that may install it: the
  // button says it (Install Claude), so no line does.
  if (claudeInstall(p)) return "";
  const said = held || p.session_why;
  if (said && !p.locked_me && !here) return `<div class="pnote dim">${esc(said)}</div>`;
  // ...and otherwise why Start agent is dead, whatever made it so (B88):
  // a Profile with no commit author, somebody else's node. A locked one
  // says so by its mark, and is left out.
  const dead = p.locked_me ? "" : claudeDeadWhy(p);
  return dead ? `<div class="pnote dim">${esc(dead)}</div>` : "";
}
// The node to install Claude Code on in place of starting a session, or "":
// the project's node has none and this account may install toolchains there
// (the operator, 21 Oct: the button opens that node's Toolchains).
const claudeInstall = p => !p.locked_me && !liveSessions().has(myClaude(p.name)) && p.claude_missing
  && mayToolchains(p.claude_missing) ? p.claude_missing : "";
// Why Start agent is dead on this project, or "" when it is live: the one
// answer the button, its description and the line under it all read.
function claudeDeadWhy(p){
  const mine = liveSessions().has(myClaude(p.name));
  if (p.locked_me) return lockedWhy(p);
  if (notMine(p)) return NOT_MINE_WHY;
  // A Claude session is work on the project (B86): Projects Write.
  if (p.write_why) return p.write_why;
  if (heldWhy(p)) return heldWhy(p);
  if (!p.session_at && p.session_why && !mine) return p.session_why;
  if (p.node_removed && !mine) return p.session_why || "its node was removed: pick another in its settings";
  return "";
}
// Why a lock holds this account out, as the server says it (R119).
const lockedWhy = p => p.locked_admin
  ? "locked by an administrator: nobody starts a session or changes it until one unlocks it"
  : `locked by ${p.owner_name || "its owner"}, its owner: only they work in it until they unlock it`;
// The lock's press in a menu: an administrator's says it is one (the
// operator, 23 Oct), since it holds the project's owner out too.
const lockLabel = p => {
  const asAdmin = p.locked ? p.locked_admin : !p.owner_mine;
  return (asAdmin ? "Admin: " : "") + (p.locked ? "Unlock" : "Lock");
};
// The two actions a project page and its card show, and the rest behind
// one menu (R238: nine look-alike icons on a row were one too many). Its
// data-* names are wireProjectRows', which serves them.
function projectActions(p, extra = ""){
  // The agent the project's Start opens (R95 step 4): Claude's unless its
  // settings name another. Its own session running here makes it Open.
  const ag = agentById(p.prefs?.agent_default) || AGENTS[0];
  const name = p.name, mine = liveSessions().has(myAgentSession(ag.id, name));
  const dead = claudeDeadWhy(p);
  // What this account's roles do not give is left out, not drawn dead.
  const forbid = !p.locked_me && !!writeWhy(p);
  const menu = [
    p.git_ok && !isBroken(p) && state?.can?.["git-auth"] !== false
      ? `<button type="button" data-l="${esc(name)}">${
          p.linked ? `${esc(p.forge_name || "Remote")} settings` : "Link to a git host"}</button>` : "",
    p.phone?.mine ? `<button type="button" data-ph="${esc(name)}"${phoneWhy(p) ? " disabled" : ""}>${
        p.phone?.lease?.project === name ? "Take your phone back" : "Lend your phone"}</button>` : "",
    p.mine === false ? "" : `<button type="button" data-bug="${esc(name)}">Report a BuilderBot bug</button>`,
    // Archive is out of sight only (R119, the operator, 23 Oct): its card
    // folds away at the foot of the Projects page and leaves Home, and the
    // project works on. Its owner's or an administrator's.
    p.may_archive ? `<button type="button" data-k="${esc(name)}" data-on="${p.archived ? "0" : "1"}">${p.archived ? "Unarchive" : "Archive"}</button>` : "",
    // ...and Lock, which is: its owner's holds everybody else out, an
    // administrator's its owner too, and says so on the press.
    p.may_lock ? `<button type="button" data-lock="${esc(name)}" data-on="${p.locked ? "0" : "1"}">${lockLabel(p)}</button>` : "",
    p.archived ? "" : `<button type="button" data-p="${esc(name)}" data-on="${p.pinned ? "0" : "1"}">${p.pinned ? "Unpin" : "Pin"}</button>`,
    // A label of this account's to keep projects together on the Projects
    // page (the operator, 18 Oct): nothing else follows from it.
    p.archived ? "" : `<button type="button" data-pgroup="${esc(name)}">${p.group ? "Group: " + esc(p.group) : "Group"}</button>`,
    // This account's color for it (the operator, 18 Oct: picked here, where a
    // dot beside the name read as a checkbox), its swatches unrolling under
    // the name as Group's box does.
    `<button type="button" data-pcolor="${esc(name)}">${p.color ? "Color: " + esc(p.color) : "Color"}</button>`,
    `<button type="button" data-rn="${esc(name)}">Settings</button>`,
    extra,
  ].filter(Boolean).join("");
  // What a press does, or why it is dead, in the button's own words: a
  // screen reader hears it, and a press on a dead one is told.
  const live = liveSessions();
  // Named for the agent it opens, whatever it says: the button's own word is
  // Start agent for every one of them.
  const said = dead ? dead
    : p.session_why ? p.session_why
    : othersOn(name).length ? `${othersOn(name).join(", ")} also working here, in a checkout of their own: start yours`
    : p.session_node && !agentOn(ag.id, p.session_node) && !live.has(myAgentSession(ag.id, name))
      ? `${ag.name}: you are not signed in on ${p.session_at}, this project's node. Press for its sign-in`
    : p.session_at ? `${ag.name}: a session on ${p.session_at}, this project's node`
    : mine ? `${ag.name}: your session is running; open its tab or end it`
    : p.last_claude ? `${ag.name}: no session running; resume or start one`
    : `${ag.name}: start a session here`;
  const say = said.startsWith(`${ag.name}:`) ? said : `${ag.name}: ${said}`;
  // Green only while your session runs, and then it opens it, naming the
  // agent; otherwise a plain Start agent, the chooser under it picking which
  // (the operator, 16 Oct: green on every card read as running everywhere;
  // 22 Oct: one word for every agent).
  const inst = ag.id === "claude" ? claudeInstall(p) : "";
  return `${isBroken(p) || forbid ? "" : inst ? `<button type="button" data-tcinst="${esc(inst)}" title="${
        esc(`Claude Code is not installed on ${p.node_name || "its node"}: open its Agents page to install it`)}">Install Claude</button>`
      : `<button type="button"${mine ? ' class="primary"' : ""} data-c="${esc(name)}"${dead ? " disabled" : ""} title="${esc(say)}">${
        mine ? `Open ${esc(ag.name)}` : "Start agent"}</button>`}
    ${mayShell() && !notMine(p) ? `<button type="button" data-s="${esc(name)}"${!gitReadyFor(p) ? " disabled" : ""}>Shell</button>` : ""}
    <span class="more"><button type="button" data-pmore aria-label="more" aria-expanded="false">${DOTS}</button><div class="actmenu" hidden>${menu}</div></span>`;
}
function projectHeader(t){
  const name = t.arg, p = (state?.projects || []).find(x => x.name === name);
  if (!p) return `<div class="phead"><span class="pname">${esc(projLabel(name))}</span></div>`;
  return `<div class="phead">
    <span class="pname">${esc(p.label || name)}${lockMark(p)}</span>
    <span class="pfacts">${projFacts(p)}</span>
    ${projectState(p)}
    <span class="sp"></span>
    ${projectActions(p)}
  </div>${projectNote(p)}${p.testing ? `<div class="pnote dim ptesting">tests running, started ${esc(ago(p.testing.since))}</div>` : ""}`;
}
// The row's handlers serve the header too (the same data-* names); the
// menu's own button is the one thing the row did differently.
function wireProjectHeader(bar){
  wireProjectRows(bar);
  // On the project's own page its menu's Settings is the notebook's Settings
  // view (R259: the view strip carries no tab for it), not the dialog. Only
  // there: a card on the Projects page keeps wireProjectRows' Settings, which
  // goes to the page (B82: this one turned the notebook in the background).
  bar.querySelectorAll("[data-rn]").forEach(b => b.onclick = () => {
    const n = getNotebook(b.dataset.rn);
    if (n) n.view("settings"); else openProjectSettings(b.dataset.rn);
  });
  wireProjectMenu(bar);
}
// A project's ⋯, on its header and on its card alike.
function wireProjectMenu(bar){
  bar.querySelectorAll("[data-pmore]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const m = b.nextElementSibling, open = m.hidden;
    closeMore();
    m.hidden = !open;
    b.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) floatAt(m, b);
  });
}
