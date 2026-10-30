// The notebook's History panes: the roadmap's own log with its Put back, and
// the one pane the memory, bug and analysis views share. One classic script
// beside index.html (docs/nodes.md §13): one file per notebook view (R60). A
// factory makeNotebook calls per notebook.

"use strict";

function nbHistoryView({$, nb, project}){
  // ---- what happened to this list ----------------------------------------
  // The list shows the present tense and two people write it, so until this
  // there was no answer to "was that step always worded like that?" or "who
  // dropped the third one?". Removing is now the only way a line leaves: the
  // cross-off-by-hand is gone, which makes the log the thing that stops a
  // deletion being final: the words are still here to retype.
  nb.roadmapLogOn = false;  // the panel is showing the log instead of the list
  nb.roadmapLog = null;  // what it is showing, or null while it loads

  const ACT = {
    add:           ["added", "new"],
    "add-step":    ["added a step", "new"],
    edit:          ["reworded", ""],
    "edit-step":   ["reworded", ""],
    remove:        ["dropped", "gone"],
    "remove-step": ["dropped a step", "gone"],
    restored:      ["put back", "new"],
    done:          ["ticked off", ""],
    undone:        ["reopened", ""],
    reopen:        ["reopened", ""],
    moved:         ["moved", ""],
    info:          ["detailed", ""],
    "info-step":   ["detailed", ""],
    sent:          ["sent", ""],
    unsent:        ["put back", ""],
    "done-step":   ["finished a step", ""],
    "undone-step": ["took back a step", ""],
    shelved:       ["shelved", ""],
    unshelved:     ["off the shelf", ""],
    target:        ["targeted", ""],
  };

  // In this browser's time zone (Profile), like every time on the page.
  const stamp = t => fmtTime(t * 1000,
    {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false});
  // A log read by day and by release (R254 step 5): a heading at the head of
  // each day's first line, saying which release that day's work went out in
  // where the project has releases, and each id a link to its row.
  const dayOf = t => fmtTime(t * 1000, {weekday: "short", day: "2-digit", month: "short"});
  const dayHead = (e, prev, rel) => {
    const day = dayOf(e.at || 0);
    if (prev && dayOf(prev.at || 0) === day) return "";
    const v = shippedIn(e.at || 0, rel);
    return `<div class="hday">${esc(day)}${v === null ? " · unreleased" : v ? ` · in ${esc(v)}` : ""}</div>`;
  };
  // Who did it, in one word or name: a person is "you" when it is this
  // account and their name when it is another's, and a session is
  // "claude", with its account's name when that is not this one's. "you ·
  // stencil" said a person twice.
  const whoSays = e => e.by === "claude"
    ? `${agentAsker(e).toLowerCase()}${e.who && e.who !== state?.me ? ` · ${e.who}` : ""}`
    : e.who && e.who !== state?.me ? e.who : (e.by || "");
  const idLink = id => `<a href="#" class="hid" data-hid="${esc(id)}" title="open ${esc(id)}">${esc(id)}</a>`;
  const wireIds = pane => pane.querySelectorAll("[data-hid]").forEach(a => a.onclick = e => {
    e.preventDefault(); nb.closeSheet(); getNotebook(project).find(a.dataset.hid); });

  function drawHistory(){
    if (!nb.roadmapLog){
      $("roadmapHist").innerHTML = `${skel("rows")}`;
      return;
    }
    if (!nb.roadmapLog.length){
      const narrowed = $("histFind").value.trim() || $("histWhen").value !== "0";
      $("roadmapHist").innerHTML = `<div class="hint">${narrowed
        ? "Nothing in the log matches that. Widen the window, or clear the search."
        : `Nothing has happened to this list yet. Every add, reword, send, shelve
         and drop lands here from now on.`}</div>`;
      return;
    }
    $("roadmapHist").innerHTML = nb.roadmapLog.map((e, k, all) => {
      const [word, tone] = ACT[e.act] || [e.act || "changed", ""];
      // R on the number, as everywhere an item is named (ids.py): a log line
      // is exactly where a bare number could be read against the bug tracker.
      const where = e.step != null ? `step ${e.step + 1} of ${idLink("R" + e.id)}` : idLink("R" + e.id);
      return `<div class="hist">${dayHead(e, all[k - 1], nb.roadmapReleases)}
      <span class="when">${esc(stamp(e.at || 0))}</span>
      <span class="tag act ${tone}">${esc(word)}</span>
      <span class="what">${where} · ${esc(e.text || "")}${
          e.was ? ` <span class="was">${esc(e.was)}</span>` : ""}${
          e.act === "moved" ? ` <span class="was" data-style="text-decoration:none">(place ${esc(String(e.from))} to ${esc(String(e.to))})</span>` : ""}${
          e.steps ? ` <span class="was" data-style="text-decoration:none">(${e.steps} steps)</span>` : ""}${
          e.act === "target" || (e.act === "add" && e.target)
            ? ` <span class="was" data-style="text-decoration:none">(${e.target ? `for ${esc(e.target)}` : "no target"})</span>` : ""}
        <span class="who${e.by === "you" ? " you" : ""}">${esc(whoSays(e))}${
          e.approved ? ", approved by you" : ""}</span>${
          e.why ? `<span class="note">why: ${esc(e.why)}</span>` : ""}${
          // A dropped item comes back from here, as it was: the log carries
          // the row (roadmap.remove). Only a drop: done is a session's word.
          e.act === "remove" && e.step == null && e.row && !onList(e.id)
            ? `<button type="button" class="hput" data-id="${esc(String(e.id))}" data-at="${esc(String(e.at || 0))}"${
                nb.nbUnsaved() ? ` disabled title="${esc(`save or revert first: ${nb.nbUnsaved()} not on disk yet`)}"` : ""
              }>Put back</button>` : ""}</span>
    </div>`;
    }).join("");
    $("roadmapHist").querySelectorAll(".hput").forEach(b => b.onclick = async () => {
      busy(b, "Putting back");
      const j = await nb.postRoadmap({action: "restore", id: Number(b.dataset.id), at: Number(b.dataset.at)});
      if (j) loadHistory(); else unbusy(b, "Put back");
    });
    wireIds($("roadmapHist"));
    // Paged like the other three, now that it has a pane to page.
    paginate($("roadmapHist"), ":scope > .hist", {key: "roadmapHist", noun: "entries"});
  }
  const onList = id => nb.roadmapItems.some(r => String(r.id) === String(id));

  // The window the panel is asking for. Narrowed on the server, not here: the
  // log is capped at 300 events a project and most of a search is bytes that
  // never needed to travel.
  function histQuery(){
    const days = Number($("histWhen").value) || 0;
    return {action: "history",
            since: days ? Math.floor(Date.now() / 1000) - days * 86400 : 0,
            find: $("histFind").value.trim()};
  }

  nb.histTimer = null;
  async function loadHistory(){
    nb.roadmapLog = null;
    nb.redrawRoadmap();
    // quiet, because the answer is not a list payload and drawRoadmap must not be
    // handed one that has no items in it.
    const j = await nb.postRoadmap(histQuery(), true);
    nb.roadmapLog = j?.history || [];
    nb.redrawRoadmap();
  }

  // Typing searches, but not on every keystroke: each one is a round trip, and
  // a thumb types faster than a fetch comes back.
  $("histFind").oninput = () => {
    clearTimeout(nb.histTimer);
    nb.histTimer = setTimeout(loadHistory, 250);
  };
  $("histFind").onkeydown = e => {
    if (e.key === "Enter"){ e.preventDefault(); clearTimeout(nb.histTimer); loadHistory(); }
    if (e.key === "Escape" && e.target.value){
      e.preventDefault(); e.stopPropagation(); e.target.value = ""; loadHistory();
    }
  };
  $("histWhen").onchange = loadHistory;

  $("roadmapLog").onclick = () => {
    if (nb.roadmapLogOn){ nb.closeSheet(); return; }
    nb.roadmapOrdering = false;
    nb.roadmapLogOn = true;
    nb.cancelSend();
    nb.openSheet("Roadmap: history", [$("histBar"), $("roadmapHist")],
                 () => { nb.roadmapLogOn = false; nb.roadmapLog = null; $("roadmapLog").classList.remove("on"); });
    loadHistory();
  };

  // ---- one History, four tabs ----------------------------------------------
  // The memory and bug views get the same log the roadmap has, through the
  // same bar: search, a window, a cap. One helper because "functionally the
  // same" should be structurally the same: a divergence here is a bug
  // somebody has to notice by feel.
  // ...each as a word (R254 step 5): the tracker's states as the page says
  // them elsewhere, not their stored names.
  const LOG_WORDS = {wontfix: "won't fix", na: "not applicable", reopened: "reopened", filed: "filed",
                     fixed: "fixed", edited: "edited", noted: "noted", sent: "sent", deleted: "deleted"};
  const LOG_ACTS = {
    filed: "new", fixed: "", wontfix: "gone", reopened: "",
    wrote: "new", forgot: "gone", edited: "", noted: "", deleted: "gone",
    // The findings log's three. Nobody performs these; they are the
    // difference between one scan and the last.
    found: "new", gone: "gone", changed: "",
  };

  // `letter` is the tab's own on a numbered entry, B for the tracker,
  // and nothing for logs whose entries are named rather than numbered.
  function logPane({btnId, barId, paneId, title, fetchLog, emptyText, letter = "", releases = () => null}){
    const btn = $(btnId), bar = $(barId), pane = $(paneId);
    let on = false, timer = null;
    const draw = rows => {
      pane.innerHTML = rows === null
        ? `${skel("rows")}`
        : !rows.length
        ? `<div class="hint">${bar.querySelector("input").value.trim()
             || bar.querySelector(".hwhen").value !== "0"
             ? "Nothing in the log matches that. Widen the window, or clear the search."
             : emptyText || "Nothing has happened here through the notebook yet."}</div>`
        : rows.map((e, k) => `<div class="hist">${dayHead(e, rows[k - 1], releases())}
            <span class="when">${esc(stamp(e.at || 0))}</span>
            <span class="tag act ${LOG_ACTS[e.act] || ""}">${esc(LOG_WORDS[e.act] || e.act || "changed")}</span>
            <span class="what">${e.id != null ? `${letter ? idLink(letter + e.id) : esc(String(e.id))} · ` : ""}${esc(e.text || "")}
              <span class="who${e.by === "you" ? " you" : ""}">${esc(whoSays(e))}${
              e.approved ? ", approved by you" : ""}</span>${
              e.note ? `<span class="note">${esc(e.note)}</span>` : ""}</span>
          </div>`).join("");
      if (rows) wireIds(pane);
      // Every history through one pane means one place to page them.
      paginate(pane, ":scope > .hist", {key: paneId, noun: "entries"});
    };
    const load = async () => {
      draw(null);
      const days = Number(bar.querySelector(".hwhen").value) || 0;
      const j = await fetchLog({
        since: days ? Math.floor(Date.now() / 1000) - days * 86400 : 0,
        find: bar.querySelector("input").value.trim()});
      draw(j?.history || []);
    };
    const toggle = () => {
      if (on){ nb.closeSheet(); return; }
      on = true;
      btn.classList.toggle("on", true);
      // The bar and the pane go into the sheet together and come back
      // together; the button un-presses itself whichever way it is closed.
      nb.openSheet(title, [bar, pane], () => { on = false; btn.classList.remove("on"); });
      load();
    };
    btn.onclick = toggle;
    const find = bar.querySelector("input");
    find.oninput = () => { clearTimeout(timer); timer = setTimeout(load, 250); };
    find.onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); clearTimeout(timer); load(); }
      if (e.key === "Escape" && e.target.value){
        e.preventDefault(); e.stopPropagation(); e.target.value = ""; load();
      }
    };
    bar.querySelector(".hwhen").onchange = load;
  }

  logPane({btnId: "memLog", barId: "memHistBar", paneId: "memHist",
           title: "Memory: history",
           fetchLog: q => nb.postMemory({action: "history", ...q})});
  logPane({btnId: "bugLog", barId: "bugHistBar", paneId: "bugHist", letter: "B", releases: () => nb.bugReleases,
           title: "Bugs: history",
           fetchLog: q => nb.postBug({action: "history", ...q})});

  // The fourth, so all four answer "what happened here" the same way.
  logPane({btnId: "anaLog", barId: "anaHistBar", paneId: "anaHist",
           title: "Analysis: history",
           emptyText: "Nothing has changed between scans yet. Changes show "
             + "from the second scan on.",
           fetchLog: async q => {
             const r = await postJSON("/api/findings", {project, action: "history", ...q});
             const j = await r.json();
             return j.error ? (notify(j.error, true), {history: []}) : j;
           }});

  return {drawHistory, stamp};
}
