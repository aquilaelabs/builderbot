// The notebook's Tests view: the test registry, what each test protects and
// what a run cost. One classic script beside index.html (docs/nodes.md §13):
// one file per notebook view (R60). A factory makeNotebook calls per notebook.

"use strict";

function nbTestsView({$, nb, project}){
  // ---- the test registry ---------------------------------------------------
  // Write-through like the tracker beside it, and for the same reason: what
  // is written here is a sentence about a test that already exists, so there
  // is nothing to stage and nothing a Save could mean.
  //
  // The timings are not written from this page at all. They are parsed out of
  // a run somebody ingested (`bb tests ingest`) because a duration this
  // page produced would be a duration measured on a box that was busy drawing
  // this page.
  nb.tests = null;
  nb.testsRev = null;    // the registry's revision as of the last read
  let tstEditing = new Set();   // the rows whose two fields are out
  nb.tstSuite = ""; nb.tstFlagged = false, nb.tstUndoc = false;

  // The run's output, in the project's shell: opened if none is, focused if
  // one is, and `bb tests log -f` typed into it, which follows a run still
  // going. Output belongs in a terminal, where it scrolls and pages and can
  // be left running; a box on the Docker row used to carry a tail of it and
  // redraw for every line.
  async function openRunOutput(){
    const btn = $("tstOut");
    const mine = tabs.find(t => t.kind === "term" && !isClaude(t)
                                && typeof t.arg === "string" && t.arg.startsWith("sh:") && t.arg.endsWith(":" + project));
    if (mine) focusTab(mine.id); else newShell(project);
    busy(btn, "Opening");
    const t = tabOf(panes[active]);
    if (!t || t.kind !== "term"){
      unbusy(btn, "Open the run's output");
      return notify("no shell tab opened; open one and run bb tests log -f", true);
    }
    // Sent, and sent again while the shell is still coming up. The server
    // asks tmux itself whether the session is there, so this does not wait
    // on the page's own list of sessions, which arrives with the status
    // poll every fifteen seconds and, for a shell on a node, only after the
    // node's next heartbeat: waiting on that said "the shell did not come
    // up" over a shell that was up.
    const session = sessionOf(t.arg);
    let said = "";
    for (let i = 0; i < 24; i++){
      try{
        const r = await postJSON("/api/send", {session, macro: "tests-log"});
        const j = await r.json();
        said = j.error || "";
        if (!said || !/no such session/.test(said)) break;
      }catch(e){ said = "could not send: " + e; break; }
      await new Promise(r => setTimeout(r, 2000));
    }
    if (said) notify(said, true);
    unbusy(btn, "Open the run's output");
  }

  async function loadTests(again = false){
    try{
      const r = await fetch("/api/tests?project=" + encodeURIComponent(project));
      const j = await r.json();
      nb.tests = j.error ? {tests: [], suites: [], error: j.error} : j;
    }catch(e){ nb.tests = {tests: [], suites: [], error: String(e)}; }
    // The revision the ANSWER carried, never the page's token as of now: a
    // write landing between the read and this line moved the token, and
    // recording that marked the write as seen, so the row it made never
    // showed (B201). The same rule the roadmap and memory halves keep.
    // An answer that failed carries none, and the token stands in so the
    // watch keeps asking rather than waiting on a number that never comes.
    nb.testsRev = nb.tests.rev ?? revs[`tests:${project}`] ?? nb.testsRev;
    drawTests();
    // Already behind: a write landed while this answer was on its way, and
    // the poll fired for it BEFORE this landed, so it will not fire again.
    // Read once more now rather than wait for the next write. Once: an
    // answer and a token that disagree for good must not become a loop.
    if (!again && nb.tests.rev !== undefined && revs[`tests:${project}`] !== undefined
        && revs[`tests:${project}`] !== nb.tests.rev) return loadTests(true);
  }

  // Wrapped so the poll can tell this panel's own write from somebody
  // else's while it is still out. See nbWriting.
  async function postTests(body){ return nb.writing(() => postTestsDo(body)); }
  async function postTestsDo(body){
    if (nb.nbHeld()){
      notify("a session is part-way through changing this notebook: "
             + "check the banner at the top", true);
      return null;
    }
    try{
      const r = await postJSON("/api/tests", {project, ...body});
      const j = await r.json();
      if (j.error){ notify(j.error, true); return null; }
      nb.tests = j;
      // This panel's own write moved nothing the poll watches: describing a
      // test does not ingest a run, but the row it changed is redrawn from
      // the answer rather than refetched.
      drawTests();
      return j;
    }catch(e){ notify("could not reach the server: " + e, true); return null; }
  }

  // Durations read as seconds with one decimal up to a minute and as m:ss
  // past it, because "412.9s" is a number somebody has to divide.
  const dur = ms => ms == null ? "-"
    : ms < 60000 ? (ms / 1000).toFixed(1) + "s"
    : Math.floor(ms / 60000) + "m " + Math.round((ms % 60000) / 1000) + "s";

  function drawTests(){
    const j = nb.tests || {};
    const ob = $("tstOut");
    if (ob){ ob.onclick = openRunOutput; ob.hidden = !mayShell(); }
    if (j.error){
      $("tstHint").textContent = "tests: " + j.error;
      $("tstList").innerHTML = ""; $("tstStats").hidden = true;
      $("tstBar").hidden = true; $("tstFolds").innerHTML = "";
      return;
    }
    const all = j.tests || [];
    // A redraw comes from the poll as well as from this panel, and it
    // replaces the list wholesale, so text somebody is part-way through
    // typing has to come back with the row. Carried only where it DIFFERS
    // from what is about to be drawn, which settles the precedence without a
    // dirty flag to clear: their unsaved words beat the stored ones, a save
    // of their own leaves nothing to carry, and a row they never touched
    // takes whatever another window wrote.
    const drafts = new Map(), stored = new Map(all.map(t => [t.key, t]));
    // A draft is a row whose fields are out and hold something unsaved; the
    // rows whose fields are out and untouched are tstEditing's.
    $("tstList").querySelectorAll(".tst[open] > .body").forEach(body => {
      const t = stored.get(body.parentElement.dataset.key);
      const p = body.querySelector(".tstP"), n = body.querySelector(".tstN");
      // The mark and its reason are typing too: a tick the redraw took back
      // between ticking it and Save posted the description and no mark, and
      // said nothing about the difference (B79).
      const a = body.querySelector(".tstAccept"), w = body.querySelector(".tstWhy");
      const accept = a ? a.checked : !!t?.accepted, why = w ? w.value : (t?.accepted || "");
      if (t && p && n && (p.value !== t.protects || n.value !== t.notes
                          || accept !== !!t.accepted || why !== (t.accepted || "")))
        drafts.set(t.key, {protects: p.value, notes: n.value, accept, why});
    });
    if (!all.length){
      $("tstHint").textContent = "";
      $("tstStats").hidden = false;
      $("tstStats").innerHTML = `<div class="hint">No test run recorded yet. A session records one with
        <pre class="ndcmd">bb tests run</pre></div>`;
      $("tstList").innerHTML = ""; $("tstBar").hidden = true;
      $("tstFolds").innerHTML = "";
      return;
    }
    // The header's three numbers. Projected is the sum of every test's last
    // measured duration: what the suite spends *in* its tests; the last run's
    // own wall time is shown beside it, and the difference is the harness.
    const proj = j.total_ms || 0, wall = j.last_wall_ms || 0;
    $("tstHint").innerHTML = `${j.n} tests · <b>${esc(dur(proj))}</b> in tests`
      + (wall ? ` (last run ${esc(dur(wall))})` : "")
      + (j.suspect ? ` · <span class="bad">${j.suspect} flagged, ${esc(dur(j.recover_ms))}
           waiting</span>` : "")
      + (j.undocumented ? ` · ${j.undocumented} undescribed` : "");
    $("tstStats").hidden = true;
    // ---- the folds above the list ------------------------------------------
    // Suites first: one file dominating is a fact about the suite, where one
    // slow test is a fact about one test.
    // One line each, not a row with a subtitle: twenty-four suites as
    // two-line rows is a fold taller than the screen, and what pushed off the
    // bottom of it was the list this tab is for.
    const rollup = (j.suites || []).map(s => `<div class="tstsuite">
        <span class="tstms">${esc(dur(s.ms))}</span>
        <span class="tstsname">${esc(s.suite)}</span>
        <span class="sub">${s.n}${
          s.suspect ? ` · <span class="bad">${s.suspect} flagged</span>` : ""}${
          s.fail ? ` · <span class="bad">${s.fail} failing</span>` : ""}${
          s.skip ? ` · ${s.skip} skipped` : ""}${
          s.undocumented === s.n ? " · none described"
            : s.undocumented ? ` · ${s.undocumented} undescribed` : ""}</span>
      </div>`).join("");
    const d = j.drift || {};
    const driftRows = ["added", "gone", "renamed"].flatMap(k =>
      (d[k] || []).map(x => `<div class="sub">${
        k === "renamed" ? `renamed: ${esc(x.was)} → ${esc(x.now)}`
                        : `${k === "added" ? "new" : "gone"}: ${esc(x.name)}`}</div>`));
    // The true count, not the length of the list under it: the rows are
    // capped at 200 and a first ingest is every test in the project, so a
    // fold headed "200" would be reporting where the list stops.
    const nDrift = (d.n_added ?? (d.added || []).length)
                 + (d.n_gone ?? (d.gone || []).length)
                 + (d.n_renamed ?? (d.renamed || []).length);
    $("tstFolds").innerHTML =
      // Closed by default: the list sorted by duration is what this tab is
      // for, and a fold that opens over it is one somebody has to shut before
      // they can read the thing they came for. The status carries the number
      // either way, which is most of what the rollup says.
      docSection("tests", "suites", "Suites",
                 `${(j.suites || []).length} · ${dur(proj)}`, rollup, {open: false})
      + (d.at ? docSection("tests", "drift", "Since the run before",
           nDrift ? `${nDrift}` : "in step",
           nDrift ? driftRows.join("")
                    + (nDrift > driftRows.length
                       ? `<div class="sub dim">…and ${nDrift - driftRows.length} more</div>` : "")
                  : `<div class="sub">the list and the last run agree.</div>`,
           {cls: nDrift ? "warn" : "", open: false}) : "");
    wireSections($("tstFolds"));
    // ---- the filter --------------------------------------------------------
    const suites = [...new Set(all.map(t => t.suite))].sort();
    $("tstBar").hidden = false;
    $("tstSuite").innerHTML = `<option value="">all suites</option>`
      + suites.map(x => `<option value="${esc(x)}"${
          x === nb.tstSuite ? " selected" : ""}>${esc(x)}</option>`).join("");
    $("tstFlagged").checked = nb.tstFlagged;
    $("tstUndoc").checked = nb.tstUndoc;
    const shown = all.filter(t => (!nb.tstSuite || t.suite === nb.tstSuite)
                                  && (!nb.tstFlagged || t.suspect)
                                  && (!nb.tstUndoc || !t.protects));
    // ---- the list ----------------------------------------------------------
    // What a row's editor is built FROM, when it is opened. Not at draw:
    // two textareas each is nothing until there are two thousand rows, and
    // then it is 3900 of them and 28k nodes and half a second of a phone's
    // time to open a tab whose first screen is twenty-five lines. Measured
    // before and after; see the comment on fill() below.
    const byKey = new Map(shown.map(t => [t.key, t]));
    // Which rows were open before this draw. Saving a description redraws the
    // list, and folding away the row somebody was just writing in is the
    // wrong answer to "did that work?": the same rule the memory book keeps
    // its folds by.
    const openRows = new Set([...$("tstList").querySelectorAll(".tst[open]")]
                             .map(e => e.dataset.key));
    $("tstList").innerHTML = shown.length ? shown.map(t => `
      <details class="tst${t.suspect ? " flagged" : ""}" data-key="${esc(t.key)}"${
        openRows.has(t.key) ? " open" : ""}>
        <summary>
          <span class="tstms${t.suspect ? " bad" : ""}">${esc(dur(t.ms))}</span>
          <span class="tstname">${esc(t.name)}</span>
          <span class="pill">${esc(t.suite)}</span>
          ${t.status && t.status !== "pass"
            ? `<span class="pill ${t.status === "fail" ? "bad" : "warn"}">${esc(t.status)}</span>` : ""}
          ${t.suspect ? `<span class="pill warn" data-tip="takes exactly ${t.suspect}s:
             probably a fixed wait, not ${t.suspect}s of work">${t.suspect}s wait?</span>`
            : t.accepted ? `<span class="pill" data-tip="sits on ${t.sits_on}s, and that is the
             work: ${esc(t.accepted)}">${t.sits_on}s, accepted</span>` : ""}
          ${t.after ? `<span class="tstafter">follows: ${esc(
             t.after.length > 120 ? t.after.slice(0, 118) + "…" : t.after)}</span>` : ""}
        </summary>
        <div class="body"></div>
      </details>`).join("")
      : `<div class="empty">nothing matches the filters</div>`;
    paginate($("tstList"), ":scope > .tst", {key: "tstList", noun: "tests"});
    // The editor, built on the way open. Every row has one; there is a place
    // to describe every test in the project, but a row nobody has opened is
    // a summary line and an empty div until they do.
    const fill = box => {
      const t = byKey.get(box.dataset.key), body = box.querySelector(".body");
      if (!t || !body || body.dataset.done) return;
      body.dataset.done = "1";
      const draft = drafts.get(box.dataset.key);
      const sub = `<div class="sub">${esc(t.key)}${
          t.was ? ` · was ${esc(dur(t.was))}` : ""}${
          (t.history || []).length > 1
            ? ` · ${t.history.map(h => (h / 1000).toFixed(1)).join(", ")}s` : ""}</div>`;
      // Read first, the way a bug report is: the two sentences under their
      // labels and an Edit. The fields come only when Edit is pressed.
      if (!draft && !tstEditing.has(t.key)){
        body.innerHTML = `${sub}
          ${t.protects || t.notes ? `
            <div class="bfield"><label>What it protects</label><div class="bval${t.protects ? "" : " dim"}">${
              esc(t.protects) || "not written yet"}</div></div>
            <div class="bfield"><label>What it exercises</label><div class="bval${t.notes ? "" : " dim"}">${
              esc(t.notes) || "not written yet"}</div></div>`
          : `<div class="bfield"><div class="bval dim">Not described yet: what breaks if this goes red, and what it exercises.</div></div>`}
          ${t.accepted ? `<div class="bfield"><label>The wait is the work</label><div class="bval">${esc(t.accepted)}</div></div>` : ""}
          <div class="actbar"><span class="sp"></span>
            <button type="button" class="tstEdit">Edit</button></div>`;
        body.querySelector(".tstEdit").onclick = () => {
          tstEditing.add(t.key); body.dataset.done = ""; fill(box);
        };
        return;
      }
      body.innerHTML = `${sub}
        <label>What it protects</label>
        <textarea class="tstP" spellcheck="false"
          placeholder="the behaviour that breaks if this goes red">${
            esc(draft ? draft.protects : t.protects)}</textarea>
        <label>What it exercises<span class="help" data-tip="fixtures, stubs, what is real and what is faked" tabindex="0">?</span></label>
        <textarea class="tstN" spellcheck="false"
          placeholder="e.g. runs the real server; the database is faked">${
            esc(draft ? draft.notes : t.notes)}</textarea>
        ${t.sits_on ? `
        <label class="ndcap"><input type="checkbox" class="tstAccept"${(draft ? draft.accept : t.accepted) ? " checked" : ""}>
          this test needs ${t.sits_on}s; stop flagging it</label>
        <textarea class="tstWhy proseline" rows="1" maxlength="300" placeholder="why: a real boot, a timeout being proved"
          ${(draft ? draft.accept : t.accepted) ? "" : "hidden"
            }>${esc(draft ? draft.why : t.accepted)}</textarea>` : ""}
        <div class="actbar"><span class="sp"></span>
          <button type="button" class="stop tstCancel"
            title="discard what was typed">Cancel</button>
          <button type="button" class="primary tstSave">Save</button></div>`;
      const acc = body.querySelector(".tstAccept");
      if (acc) acc.onchange = () => { body.querySelector(".tstWhy").hidden = !acc.checked; };
      body.querySelector(".tstCancel").onclick = () => {
        tstEditing.delete(t.key);
        // The fields go before the redraw reads them for a draft.
        body.querySelectorAll("textarea").forEach(x => x.remove());
        body.dataset.done = ""; fill(box);
      };
      body.querySelector(".tstSave").onclick = e => pressing(e.target, async () => {
        busy(e.target, "Saving");
        const protects = body.querySelector(".tstP").value,
              notes = body.querySelector(".tstN").value;
        const acc = body.querySelector(".tstAccept");
        const why = acc && acc.checked ? (body.querySelector(".tstWhy").value.trim() || "the wait is the work") : "";
        tstEditing.delete(t.key);          // written: back to reading it
        // The mark goes first: describe redraws from its answer, and a
        // second post after that would draw the row twice.
        if (acc && (why !== (t.accepted || "")) && !await postTests({action: "accept", key: t.key, why}))
          tstEditing.add(t.key);
        else if (!await postTests({action: "describe", key: t.key, protects, notes}))
          tstEditing.add(t.key);           // refused: the fields stay, with the typing
      });
    };
    $("tstList").querySelectorAll(".tst > summary").forEach(sum => {
      sum.onclick = e => {
        e.preventDefault();
        const box = sum.parentElement;
        // Filled BEFORE the tween, which measures the height it is animating
        // to: an empty body would animate to nothing and then jump.
        if (!box.open) fill(box);
        slideDetails(box, !box.open);
      };
    });
    // ...and the ones that came back open need their editor back with them.
    $("tstList").querySelectorAll(".tst[open]").forEach(fill);
    tipify($("tstList"));
  }

  $("tstSuite").onchange = () => { nb.tstSuite = $("tstSuite").value; drawTests(); };
  $("tstFlagged").onchange = () => { nb.tstFlagged = $("tstFlagged").checked; drawTests(); };
  $("tstUndoc").onchange = () => { nb.tstUndoc = $("tstUndoc").checked; drawTests(); };

  return {loadTests};
}
