// The notebook's Sessions view: your own conversations on this project,
// newest first, each to go on with, read here, or keep as a text file (the
// operator, 22 Oct: out of Profile and into the project they were had on,
// and any one of them resumed, where the Claude button resumes the last). Beside
// Overview in the Overview group. Only the signed-in account's: the
// controller lists them (transcripts.mine), never another account's.
// One classic script beside index.html, the shape tab-*.js has (docs/nodes.md
// §13): same page, same global scope, one file per notebook view (R60).
//
// A factory rather than a script that runs: makeNotebook calls it per
// notebook with the notebook's element lookup, its state object and its
// project, and takes back the one function the rest of the notebook calls.

"use strict";

// One conversation's row, the Artifacts view's shape so the two lists read
// the same: when, its size, the first thing you said, Resume, Read and
// Download, and behind its ⋯ Make visible (to every session on the project)
// and Delete. An anchor for the download, since a download is a link the
// browser saves. Another account's, made visible, is read and downloaded
// only, with whose it is.
function convRows(project, rows, theirs = false){
  const size = b => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
  // The stamps in the text are written in this browser's zone, the one the
  // times on this page are in, so the log and the page agree.
  const tz = userTZ() || Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  return `<div class="cvlogs">${rows.map(r => `
    <div class="artrow">
      <div class="grow">
        <div class="top"><b>${esc(fmtTime(r.at * 1000))}</b> <span class="pill cvagent" title="the coding agent this conversation is with">${esc(agentById(r.agent)?.name || "Claude")}</span> <span class="dim">${esc(ago(r.at))} · ${esc(size(r.bytes))}${
          theirs ? ` · ${esc(r.by || "")}'s` : ""}</span>${r.shared ? ` <span class="pill">visible to every session</span>` : ""}</div>
        ${r.first ? `<div class="dim first">${esc(r.first)}</div>` : ""}</div>
      <div class="acts actbar">${theirs ? "" : `<button type="button" data-cvresume="${esc(r.id)}" data-cvat="${esc(String(r.at))}" data-cvagent="${esc(r.agent || "claude")}">Resume</button>`}<button type="button" data-cvread="${esc(r.id)}">Read</button><a class="btn" href="/api/transcript?project=${encodeURIComponent(project)}&id=${encodeURIComponent(r.id)}&tz=${encodeURIComponent(tz)}" download>Download</a>${
        theirs ? "" : actMore([
          `<button type="button" data-cvshare="${esc(r.id)}" data-on="${r.shared ? "" : "1"}">${r.shared ? "Make private" : "Make visible"}</button>`,
          `<button type="button" class="danger" data-cvdel="${esc(r.id)}">Delete</button>`], true)}</div>
    </div>`).join("")}</div>`;
}

function nbSessionsView({$, nb, project, root}){
  const view = () => root.querySelector('.nbview[data-view="sessions"]');
  let rows = null;
  async function loadSessions(){
    try{
      const j = await (await fetch("/api/transcripts?project=" + encodeURIComponent(project))).json();
      rows = j.error ? {error: j.error} : {rows: j.rows || [], visible: j.visible || []};
    }catch(e){ rows = {error: "could not reach the controller: " + e}; }
    drawSessions();
  }
  function drawSessions(){
    const v = view(), list = v?.querySelector(".sesslist"), hint = v?.querySelector(".nbglance");
    if (!list) return;
    if (rows === null){ glanceWaiting(hint); list.innerHTML = skel("rows"); return; }
    if (rows.error){ viewGlance(hint, []); list.innerHTML = `<div class="field"><div class="notice bad">${esc(rows.error)}</div></div>`; return; }
    const mine = rows.rows, theirs = rows.visible;
    const week = mine.filter(r => r.at * 1000 > Date.now() - 7 * 86400000).length;
    const open = mine.filter(r => r.shared).length;
    viewGlance(hint, mine.length ? [
      {label: mine.length === 1 ? "conversation" : "conversations", value: mine.length},
      {label: "this week", value: week, omit: !week},
      {label: "visible to every session", value: open, omit: !open}] : [],
      mine.length ? "yours alone unless made visible: the whole exchange, your words and the session's, each command it ran and what came back" : "");
    // What the view is for is its empty state (the a-notebook/views rule).
    list.innerHTML = (mine.length ? `<div class="field mineconv">${convRows(project, mine)}</div>`
      : `<div class="field"><div class="hint nbempty">Your sessions on this project, once you have had one: each is listed here for you alone, to resume, read, download or make visible to every session here.</div></div>`)
      // ...and others' they made visible, which any session here reads too.
      + (theirs.length ? docSection("sessions", "visible", "Made visible by others", String(theirs.length),
          `<div class="field theirconv">${convRows(project, theirs, true)}</div>`) : "");
    wireSections(list);
    list.querySelectorAll(".cvlogs").forEach((l, i) => paginate(l, ":scope > .artrow", {key: `nbSess${i}:` + project, noun: "conversations"}));
    // The ⋯ of a row, as an action bar's (wireMore), its menu over the page.
    list.querySelectorAll(".acts .more > button").forEach(b => b.onclick = () => {
      const m = b.nextElementSibling, shut = m.hidden;
      closeMore();
      if (shut){ m.hidden = false; b.setAttribute("aria-expanded", "true"); floatAt(m, b); }
    });
    list.querySelectorAll("[data-cvshare]").forEach(b => b.onclick = () => act(b, b.dataset.cvshare, b.dataset.on ? "share" : "unshare"));
    list.querySelectorAll("[data-cvdel]").forEach(b => b.onclick = () => {
      const r = mine.find(x => x.id === b.dataset.cvdel);
      if (!confirm(`Delete your conversation of ${r ? fmtTime(r.at * 1000) : "this session"}?\n\n`
          + "It is gone for good: nothing can resume, read or download it again.")) return;
      act(b, b.dataset.cvdel, "delete");
    });
    list.querySelectorAll("[data-cvread]").forEach(b => b.onclick = () => openConversation(project, b.dataset.cvread));
    // Go on with this one: the project's chooser opens on it (resumeConversation).
    list.querySelectorAll("[data-cvresume]").forEach(b => b.onclick = ev => resumeConversation(project, b.dataset.cvresume, +b.dataset.cvat, ev, b.dataset.cvagent));
  }
  // Delete, Make visible and Make private: a person's, on the press.
  async function act(b, id, action){
    closeMore();
    busy(b, {delete: "Deleting", share: "Making visible", unshare: "Making private"}[action]);
    try{
      const j = await (await postJSON("/api/transcripts", {project, id, action})).json();
      if (j.error) notify(j.error, true);
      else notify({delete: "deleted", share: "visible to every session on this project", unshare: "yours alone again"}[action]);
    }catch(e){ notify("could not reach the controller: " + e, true); }
    await loadSessions();
  }
  return {loadSessions};
}
