// The notebook's Bugs view: the tracker, its form, its sorts and Send to
// Claude. One classic script beside index.html (docs/nodes.md §13): one file
// per notebook view (R60). A factory makeNotebook calls per notebook.

"use strict";

// Whether a report answers a search (R254 step 1): its number (B12 or 12)
// or any of its words, case aside. An empty search is all.
function bugMatch(b, q){
  if (!q) return true;
  if (q === "b" + b.id || q === String(b.id)) return true;
  return ["title", "area", "repro", "expected", "actual", "notes", "status_note"]
    .some(k => String(b[k] || "").toLowerCase().includes(q));
}

// What a report knows (R254 step 3), as facts in place of a dotted line:
// who reported it and when, the build it was seen in and on, when and how
// it was closed, the build that closed it and the release that shipped
// the fix (shippedIn, from the CHANGELOG's dated headings).
function bugFacts(b, rel, words, refs){
  const who = x => x === "claude" ? "Claude" : x === "you" ? "you" : x || "";
  const closed = b.status !== "open";
  const shipped = closed && b.status === "fixed" ? shippedIn(b.closed_at, rel) : "";
  return factGrid([
    ["Reported", `${b.at ? rmDay(b.at) : ""}${b.by ? `, by ${who(b.by)}` : ""}`],
    ["Seen in", b.seen_in || ""], ["Seen on", b.seen_on || ""],
    ["Closed", closed ? `${words[b.status] || b.status}${b.closed_at ? ", " + rmDay(b.closed_at) : ""}${
      b.status_by ? `, by ${who(b.status_by)}` : ""}${b.status_note ? `: ${b.status_note}` : ""}` : ""],
    ["Fixed in", closed ? b.fixed_in || "" : ""],
    ["Shipped in", shipped === null ? "not yet: planned for the next release" : shipped || ""],
    ["Changelog", clRefs(refs), {html: true}]]);
}

function nbBugsView({$, nb, project}){
  // ---- bugs ----------------------------------------------------------------
  // Write-through, unlike the roadmap: a bug report is a form submitted once,
  // not a list curated in place, and a session finding one mid-task must not
  // depend on somebody pressing Save later.
  nb.bugs = null;
  nb.bugRev = null;      // the tracker's revision as of the last read

  async function loadBugs(again = false){
    try{
      const r = await fetch("/api/bugs?project=" + encodeURIComponent(project));
      const j = await r.json();
      nb.bugs = j.error ? {bugs: [], error: j.error} : j;
    }catch(e){ nb.bugs = {bugs: [], error: String(e)}; }
    // The answer's own revision, not the page's token as of now (B201); an
    // answer that failed carries none, and the token stands in.
    nb.bugRev = nb.bugs.rev ?? revs[`bug:${project}`] ?? nb.bugRev;
    drawBugs();
    // Already behind (see nb-tests.js): read once more now.
    if (!again && nb.bugs.rev !== undefined && revs[`bug:${project}`] !== undefined
        && revs[`bug:${project}`] !== nb.bugs.rev) return loadBugs(true);
  }

  // Wrapped so the poll can tell this panel's own write from somebody
  // else's while it is still out. See nbWriting.
  async function postBug(body){ return nb.writing(() => postBugDo(body)); }
  async function postBugDo(body){
    // The batch guard reaches here too: a report would survive a session's
    // commit untouched (different file), but "held" has to mean the notebook,
    // or the banner is a lie about its other tabs. Reading is never held.
    if (nb.nbHeld() && body.action !== "history"){
      notify("a session is part-way through changing this notebook: "
             + "check the banner at the top", true);
      return null;
    }
    try{
      const r = await postJSON("/api/bugs", {project, ...body});
      const j = await r.json();
      // Somebody else edited this report first (roadmap #26). The tracker
      // that came back with the refusal is drawn; it is what the report now
      // says, but the FORM is left alone, holding what was typed, and the
      // caller keeps the new revision so pressing Save again writes over
      // theirs deliberately rather than by accident.
      if (j.conflict){
        notify(j.error + ": what was typed is still in the form; "
               + "Save again to write it over theirs", true);
        if (j.bugs){ nb.bugs = j; if (nb.bugRev !== null) nb.bugRev += 1; }
        return j;
      }
      if (j.error){ notify(j.error, true); return null; }
      nb.bugs = j;
      // This panel's own write moved the revision. Left unmarked, the next
      // poll reads it as somebody else's and reloads on top of the answer
      // just received.
      if (nb.bugRev !== null) nb.bugRev += 1;
      drawBugs(true);
      return j;
    }catch(e){ notify("could not reach the server: " + e, true); return null; }
  }

  const SEVS = ["low", "medium", "high", "critical"];

  // Ordered worst-first for sorting; the picker's own list runs the other way
  // because that is how somebody reads a severity scale when choosing one.
  const SEV_RANK = {critical: 0, high: 1, medium: 2, low: 3};
  const STATUS_WORDS = {open: "open", fixed: "fixed", wontfix: "won't fix",
                        na: "not applicable"};

  // Open before closed, always: a tracker is read to find what is left, and
  // a fixed critical topping the list is not that. The choice orders within.
  //
  // ...and severity is the one choice that means nothing once a bug is closed.
  // "How bad is it" is a question about work outstanding; a critical fixed in
  // June above a medium fixed yesterday answers nothing anybody asked. So the
  // closed half falls back to most recently closed, which is the only thing
  // that half is read for. The other four sorts already mean the same in both
  // halves (a date is a date and a title is a title), so they are left alone.
  const BUG_SORTS = {
    // The tie-break matters here and nowhere else: `updated` has one-second
    // resolution, and closing two bugs in the same second is ordinary. Falling
    // back to the id keeps the rows from swapping places between draws.
    severity: (a, b) => a.status !== "open"
                        ? (b.updated || b.at || 0) - (a.updated || a.at || 0)
                          || (b.id || 0) - (a.id || 0)
                        : (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9)
                          || (b.at || 0) - (a.at || 0),
    newest:   (a, b) => (b.at || 0) - (a.at || 0),
    oldest:   (a, b) => (a.at || 0) - (b.at || 0),
    updated:  (a, b) => (b.updated || b.at || 0) - (a.updated || a.at || 0),
    title:    (a, b) => String(a.title).localeCompare(String(b.title)),
  };

  function sortedBugs(){
    const how = BUG_SORTS[$("bugSort").value] || BUG_SORTS.severity;
    return (nb.bugs?.bugs || []).slice().sort((a, b) =>
      (a.status !== "open") - (b.status !== "open") || how(a, b));
  }

  // The report form, used for a new bug and for editing one. The fields are
  // the ones a session needs to act on a report without a conversation: where
  // it lives, how to make it happen, and the gap between should and does.
  function bugForm(b){
    const v = k => esc(b?.[k] || "");
    return `<div class="memadd bugform ctlrow">
      <label>Title</label>
      <textarea class="bfTitle proseline" rows="1" maxlength="1000"
        placeholder="the picker loses its selection on rotate">${v("title")}</textarea>
      <div class="two">
        <div><label>Severity</label>
          <select class="bfSev">${optionList(SEVS, b?.severity || "medium")}</select></div>
        <div><label>Where<span class="help" data-help="files, component, screen" tabindex="0">?</span></label>
          <textarea class="bfArea proseline" rows="1" maxlength="1000"
            placeholder="scripts/dashboard/index.html, the picker">${v("area")}</textarea></div>
      </div>
      <label>How to reproduce</label>
      <textarea class="bfRepro" spellcheck="false"
        placeholder="1. open the picker on a phone&#10;2. rotate">${v("repro")}</textarea>
      <div class="two">
        <div><label>Expected</label>
          <textarea class="bfExpected proseline" rows="1" maxlength="1000"
            >${v("expected")}</textarea></div>
        <div><label>Actual</label>
          <textarea class="bfActual proseline" rows="1" maxlength="1000"
            >${v("actual")}</textarea></div>
      </div>
      <label>Notes<span class="help" data-help="cause, analysis, fix plan" tabindex="0">?</span></label>
      <textarea class="bfNotes" spellcheck="false"
        placeholder="what is known about why; mostly Claude's half">${v("notes")}</textarea>
      <div class="actbar">
        <button type="button" class="stop bfCancel">Cancel</button>
        <button type="button" class="primary bfGo">${b ? "Save the bug" : "Report it"}</button></div>
    </div>`;
  }

  function readBugForm(box){
    return {title: box.querySelector(".bfTitle").value,
            severity: box.querySelector(".bfSev").value,
            area: box.querySelector(".bfArea").value,
            repro: box.querySelector(".bfRepro").value,
            expected: box.querySelector(".bfExpected").value,
            actual: box.querySelector(".bfActual").value,
            notes: box.querySelector(".bfNotes").value};
  }

  function drawBugAdd(){
    const box = $("bugAdd"), ro = projWriteWhy(project);
    box.innerHTML = `<div class="addbar ctlrow" data-add="bug">
      <button type="button"${ro ? " disabled" : ""}>Report a bug</button></div>${deadWhy(ro)}`;
    // The same fold the memory writer opens with: the two are the same control
    // on two views of one notebook, and one of them appearing whole while the
    // other unrolled was the kind of difference you cannot unsee.
    const shut = () => swapBox(box, drawBugAdd);
    box.querySelector("button").onclick = () => swapBox(box, () => {
      box.innerHTML = bugForm(null);
      box.querySelector(".bfCancel").onclick = shut;
      box.querySelector(".bfGo").onclick = async () => {
        const j = await postBug({action: "add", ...readBugForm(box)});
        if (j) shut();
      };
    });
  }

  // `force` is what a deliberate action passes. Without it, a redraw is
  // skipped while a row has something typed into it.
  //
  // The list is rebuilt with innerHTML, which carries each row's open state
  // across but nothing else, and the delete box and the edit form are
  // imperative DOM put into a row AFTER the render, so a repaint took them
  // and whatever the operator had written in them. Any bug_rev change did
  // it: another session filing something, or this one closing a bug in a
  // terminal. The same family as the changelog pane (bug #13), and the same
  // answer the rest of the notebook already gives: Memory stages behind
  // Save, the node editor keeps its draft across a repaint. An editor beats
  // freshness; the next deliberate action redraws with whatever arrived
  // meanwhile, because `bugs` is still updated underneath.
  function drawBugs(force){
    const list = $("bugList"), hint = $("bugHint");
    if (!nb.bugs){
      // Waiting as it lands: Report a bug above the list, which needs no list.
      hint.innerHTML = skel("word"); list.innerHTML = skel("rows");
      if (!$("bugAdd").innerHTML.trim()) drawBugAdd();
      return;
    }
    if (nb.bugs.error){ hint.textContent = "bugs: " + nb.bugs.error; return; }
    if (!force && list.querySelector(".dropbox, .bugform")) return;
    if (nb.bugs.releases !== undefined) nb.bugReleases = nb.bugs.releases;
    const rows = sortedBugs();
    const open = rows.filter(b => b.status === "open").length;
    // Count first; what the tracker is for is its empty state (R119 step 4).
    hint.textContent = rows.length ? `${open} open of ${rows.length}` : "nothing reported";
    // A sort over nothing is a control that does nothing: it arrives with
    // the second bug, when there is an order to choose.
    const sortBar = $("bugSortBar");
    if (sortBar) sortBar.hidden = rows.length < 2;
    // Narrowed by a chip (All, Open, Closed) and the search (R254 step 1).
    nb.bugChip = ["", "open", "closed"].includes(nb.bugChip) ? nb.bugChip : "";
    if (paint($("bugChips"), chipButtons([{key: "open", label: "Open", count: open},
                                          {key: "closed", label: "Closed", count: rows.length - open}], nb.bugChip, "data-bgchip"), true))
      $("bugChips").querySelectorAll("[data-bgchip]").forEach(b => b.onclick = () => fadeThrough(() => [$("bugList")], () => { nb.bugChip = b.dataset.bgchip; drawBugs(true); }));
    const q = (nb.bugFind || "").trim().toLowerCase();
    const shown = b => (!nb.bugChip || (nb.bugChip === "open") === (b.status === "open")) && bugMatch(b, q);
    // Which were open before this redraw, so acting on one does not fold it.
    const held = new Set([...list.querySelectorAll(".bug[open]")].map(d => d.dataset.id));
    // Only the rows on show are built, a page at a time (pageLimit): every
    // one of 795 built and all but 25 hidden was three seconds on a phone
    // for each press of a chip (the operator, 17 Oct).
    const vis = rows.filter(shown);
    const lim = pageLimit(list, "bugList", vis.length);
    // A role that reads the project and does not write it (B86): a report
    // carries no verbs, and Report a bug says why above the list.
    const ro = projWriteWhy(project);
    list.innerHTML = vis.slice(0, lim).map(b => `
      <details class="bug chev" data-id="${b.id}"${held.has(String(b.id)) ? " open" : ""}>
        <summary>
          <span class="tag sev ${esc(b.severity)}">${esc(b.severity)}</span>
          <span class="n id" title="bug B${b.id}: a session knows it by that number">B${b.id}</span>
          <span class="btitle${b.status !== "open" ? " done" : ""}">${esc(b.title)}</span>
          <span class="tag bstat ${esc(b.status)}">${esc(
            b.status === "na" ? "n/a" : b.status === "wontfix" ? "won't fix" : b.status)}</span>
        </summary>
        <div class="body">
          ${["area", "repro", "expected", "actual", "notes"].map(k => b[k]
            ? `<div class="bfield"><label>${k}</label><div class="bval">${esc(b[k])}</div></div>` : "").join("")}
          ${bugFacts(b, nb.bugReleases, STATUS_WORDS, (nb.bugs.changelog || {})["B" + b.id])}
          ${ro ? "" : `<div class="actbar macts">
            <span class="sp"></span>
            <button type="button" class="bSend"${b.status === "open" ? "" : " disabled"}
              title="${b.status === "open"
                ? `send this bug to the running session`
                : `closed: reopen it first to send it`}"
              >Send to Claude</button>
            <button type="button" class="bEdit">Edit</button>
            ${b.status === "open"
              // Five at most on a bar, the rest behind More (R210): six
              // were cut short at 344px (R254 step 7). Mark fixed stays on
              // the bar, the other closes and Remove go under it, Remove
              // last as the one that cannot be undone.
              ? `<button type="button" class="bFix">Mark fixed</button>
                 ${actMore([`<button type="button" class="bWont">Won't fix</button>`,
                   `<button type="button" class="bNa" title="it was real and stopped applying: the feature went away">Not applicable</button>`,
                   `<button type="button" class="danger bRm" title="for a report that should not exist: mis-filed, a duplicate, the wrong project">Remove</button>`])}`
              : `<button type="button" class="bReopen">Reopen</button>
                 <!-- Last, because it is the one that cannot be undone. -->
                 <button type="button" class="danger bRm"
                   title="for a report that should not exist: mis-filed, a duplicate, the wrong project">Remove</button>`}
          </div>`}
        </div>
      </details>`).join("")
      // What the tracker is for, as its empty state (R119 step 4).
      || (rows.length ? "" : `<div class="hint nbempty">What goes here reaches every Claude session in this project.</div>`);
    paginate(list, ":scope > .bug", {key: "bugList", noun: "reports", total: vis.length, more: () => drawBugs()});
    wireMore(list);
    list.querySelectorAll(".bug").forEach(d => {
      const id = Number(d.dataset.id);
      // Opened with the same tween the cards and the memories use. Bound on
      // the summary rather than the details' toggle event, because toggle
      // fires after the browser has already snapped it open.
      const sum = d.querySelector("summary");
      if (sum) sum.onclick = e => { e.preventDefault(); slideDetails(d, !d.open); };
      // The closing note typed in the row (R254 step 6), the box the Delete
      // below and the roadmap's drop open, not the browser's prompt: one
      // shape for every question this view asks, and one a phone lays out.
      const ask = (status, q, verb) => {
        closeMore();
        const body = d.querySelector(".body");
        if (body.querySelector(".dropbox")) return;
        dropBox(body, {q, sub: ": kept on the bug", placeholder: "a commit, a word", verb,
                       go: note => postBug({action: "status", id, status, note}), cancel: () => drawBugs(true)});
      };
      d.querySelector(".bFix")?.addEventListener("click",
        () => ask("fixed", "What fixed it?", "Close as fixed"));
      d.querySelector(".bWont")?.addEventListener("click",
        () => ask("wontfix", "Why not?", "Close: won't fix"));
      d.querySelector(".bNa")?.addEventListener("click",
        () => ask("na", "What stopped it applying?", "Close: not applicable"));
      d.querySelector(".bReopen")?.addEventListener("click",
        () => postBug({action: "status", id, status: "open", note: ""}));
      // Handing a bug over. Same box the roadmap opens under a step, opened
      // under the report instead; it asks the same question and the pickers
      // behind it are the same two.
      d.querySelector(".bSend")?.addEventListener("click", () => {
        const body = d.querySelector(".body");
        if (body.querySelector(".sendbox")) { nb.shutSendBoxes(); return; }
        nb.shutSendBoxes();
        nb.sendNoteText = "";            // see nb.pickRoadmap: a note is not carried over
        nb.roadmapSel = null;               // and only one thing is armed at a time
        nb.drawSendBox(!!nb.roadmapSession);
        // Same session the roadmap sends into, and the same reason it has to
        // exist first: there is no door into a Claude that is not running.
        if (!nb.roadmapSession){
          notify("no Claude session is running here: start one from the "
                 + "project's card first", true);
          return;
        }
        const box = nb.sendBoxEl({
          label: `Send B${id} to ${nb.roadmapSession}?`,
          sub: "the session looks it up by number",
          placeholder: "anything to send with it (optional)",
          onCancel: nb.shutSendBoxes,
          onSend: async () => {
            const go = box.querySelector("#roadmapGo");
            busy(go, "Sending");
            const j = await postBug({action: "send", id, note: nb.sendNoteText});
            unbusy(go, "Send");
            if (!j) return;
            if (!j.sent){
              notify(j.switching
                ? `Not sent: the session is busy with the /${j.switching} line. `
                  + "Clear its tab and send the bug again."
                : "Not sent: the session is busy. Press Enter in its tab when it is free.",
                true);
              return;
            }
            nb.sendNoteText = "";
            nb.shutSendBoxes();
            startClaude(project, null);   // land in the tab it went to
          },
        });
        body.appendChild(box);
        arriveBox(box);   // appended by the click; nothing redraws it under us
      });
      // Same box the roadmap's bin opens, for the same reason: nothing here
      // can be undone, so the only thing between a deleted report and its
      // being filed again is a note saying why it went.
      d.querySelector(".bRm")?.addEventListener("click", () => {
        closeMore();
        const body = d.querySelector(".body");
        if (body.querySelector(".dropbox")) return;
        // Removed first, then redrawn: the box is what defers the redraw,
        // so anything that arrived while it was open lands now.
        dropBox(body, {q: "Delete this report?", sub: ": it is gone for good; to keep a record, close it instead",
                       placeholder: "why it should not have been filed (optional, kept in the log)",
                       verb: "Remove it", tone: "danger", cancel: () => drawBugs(true),
                       go: why => postBug({action: "remove", id, why})});
      });
      d.querySelector(".bEdit")?.addEventListener("click", () => {
        const body = d.querySelector(".body");
        const b = (nb.bugs.bugs || []).find(x => x.id === id);
        body.innerHTML = bugForm(b);
        // The revision this form was opened over, so a write that would go
        // over somebody else's is refused rather than applied. On the form
        // rather than in a closure, the same way the memory editor carries
        // its digest: a refusal moves it on, and the second press is then a
        // decision made knowing what it replaces.
        const form = body.querySelector(".bugform");
        form.dataset.rev = b?.rev ?? "";
        // Forced: this IS the deliberate close, and the form it is putting
        // away is the thing that would otherwise hold the redraw off.
        body.querySelector(".bfCancel").onclick = () => drawBugs(true);
        body.querySelector(".bfGo").onclick = async () => {
          const j = await postBug({action: "edit", id, rev: form.dataset.rev || undefined,
                                   ...readBugForm(body)});
          if (j?.conflict) form.dataset.rev = j.conflict.rev;
        };
      });
    });
    drawBugAdd();
  }

  return {loadBugs, drawBugs, postBug};
}
