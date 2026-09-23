// The notebook's Roadmap view: the list and its steps, the send box, the
// refusal when two writers meet, and the staged changes Save replays. One
// classic script beside index.html (docs/nodes.md §13): one file per notebook
// view (R60). A factory makeNotebook calls per notebook.
function nbRoadmapView({$, nb}){
  // ---- the shared to-do list ---------------------------------------------
  // Both sides write it: the operator here, a session through `bb roadmap`. Its
  // open items are appended to every Claude session bb-tty starts, which is why
  // something noticed mid-task and left undone survives the conversation.

  async function loadRoadmap(gen){
    // What the staging counter was when we asked. See the guard below.
    const staged = nb.roadmapStaged;
    let j;
    try{
      const r = await fetch("/api/roadmap?project=" + encodeURIComponent(nb.memProj));
      j = await r.json();
    }catch(e){ j = {error: String(e)}; }
    if (gen !== nb.memGen) return;
    // ...and never over something staged WHILE this was in flight. The guard
    // above catches a reply meant for a different project; this catches one for
    // this project that left before the operator typed and came back after.
    //
    // Every path that reloads does ask first: rereadRoadmap confirms, noteBatch
    // checks that nothing is staged, but they ask BEFORE the fetch, and the
    // answer stops being true while it is in flight. The list then came back
    // from the server and quietly took what had been typed since.
    //
    // The test is "did anything stage since we asked", not "is anything staged
    // now": an explicit re-read with work already staged is a request to
    // replace it, and rereadRoadmap has confirmed that. Only the typing that
    // happened DURING the round trip is unanswerable, because nobody was asked
    // about it.
    //
    // Measured rather than reasoned: three concurrent runs of roadmap.mjs, two of
    // them with #roadmapList empty and the hint back to "Nothing yet" a moment
    // after a row was staged. Filed as a test race for weeks (bug #13) because
    // it only showed under load, which is exactly when a fetch is slow enough
    // to land on the wrong side of the typing.
    //
    // The batch marker still gets through: a session opening or closing one is
    // news whether or not this list can be replaced.
    if (nb.roadmapStaged !== staged){
      if (j.batch !== undefined) nb.noteBatch(j.batch);
      return;
    }
    drawRoadmap(j);
  }

  // The send arrow. Crossing something out here does not mean "done"; it means
  // "handed to the session", which is the thing the operator actually needs to
  // see, because a step can be sent and then not carried out.
  const SEND = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M2.6 8h9"/><path d="M8.2 4.6 11.6 8l-3.4 3.4"/>
  <path d="M13.6 3.2v9.6"/></svg>`;

  const UP = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M8 12.6V3.7"/><path d="M4.4 7.3 8 3.7l3.6 3.6"/></svg>`;
  const DOWN = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M8 3.4v8.9"/><path d="M11.6 8.7 8 12.3 4.4 8.7"/></svg>`;

  // A tray with something going into it: put aside, not thrown away. The state
  // between "do this" and "we are not doing this", and the only one of the
  // three that can be undone, which is why it is a toggle and the bin is not.
  const SHELF = `<svg viewBox="0 0 16 16" aria-hidden="true">
  <path d="M2.2 9.4h3l.9 1.6h3.8l.9-1.6h3"/>
  <path d="M2.2 9.4v3.2h11.6V9.4"/>
  <path d="M8 2.2v5"/><path d="M5.9 5.1 8 7.2l2.1-2.1"/></svg>`;

  // Which step a group would hand over next: the first that has not gone. The
  // order is the whole point of a group: send the third before the second and
  // it lands on a tree the second was supposed to have made, so only that one,
  // and any already sent, can be sent at all.
  // Whether a row can be handed to a session: asked by the arrow that offers
  // it and by the redraw that decides whether an armed one is still valid.
  //
  // One function because it used to be two, and they disagreed: the arrow on a
  // sent row was live (that is the whole "it did not take, do it again" case)
  // while the redraw dropped the selection the moment it was made, so picking
  // one armed nothing and the send controls never came up.
  function canSend(r, idx, live){
    // Nothing goes out while the panel is holding unsaved work. The line about
    // to be typed into a session is one of the things that might be unsaved, so
    // sending against a list the server has not been told about would hand over
    // a step that does not exist there, and the session would then go and read
    // a roadmap that says something else. Save first, or throw it away first;
    // either way the list a step comes from is the list on disk.
    if (nb.nbUnsaved()) return false;
    if (!live || r.shelved) return false;
    const steps = r.steps || [];
    if (idx < 0) return steps.length ? nextStep(r) !== null : true;
    const st = steps[idx];
    // The frontier, or one that has already gone. Never a later one: send the
    // third before the second and it lands on a tree the second was to make.
    return !!st && (idx === nextStep(r) || stepGone(st));
  }

  function stepRow(r, idx, live){
    const steps = r.steps || [];
    const nxt = nextStep(r);
    const st = idx < 0 ? r : steps[idx];
    // Shelving is an item's business, never a step's: parking one step of a
    // plan and leaving the rest live is not a state a plan can be in: the
    // thing you have decided not to do now is the whole plan. So the shelf
    // button sits on the item row, and a group is shelved entire.
    //
    // The bin is on every row. It used to be on the head of the queue only:
    // things come off a plan from the front, which meant a stale step three
    // cost you steps one and two to reach, and left the list describing work
    // nobody was going to do. That guardrail was aimed at the wrong risk: the
    // order that matters is the order things are *sent* in, and the frontier
    // rule below is what protects it. A deletion cannot send anything out of
    // order; it can only make a plan shorter, and it now says why it did and
    // keeps the words in the log.
    const shelf = idx < 0;
    // Sent ones stay live so they can go again; "it did not take, do it again"
    // is the reason they are still on screen at all.
    // A crossed line cannot be sent. Un-cross it first; that is one tap, and
    // it makes the struck-through state mean one thing instead of two.
    //
    // A group's own arrow is its next step's arrow: the plan is the item, and
    // reaching for the title to send "the next bit of this" is what a hand
    // does. Picking either highlights both, because they are one choice.
    const can = canSend(r, idx, live);
    const why = nb.nbUnsaved() ? `save or revert first: ${nb.nbUnsaved()} not on disk yet`
              : r.shelved ? "shelved: take it off the shelf to send it"
              : !live ? "no Claude session is running here"
              : st.done ? "a session finished this: sending it again says it did not"
              : st.sent ? "this one has gone already: pick it to send it again"
              : idx < 0 && steps.length
                ? (nxt === null ? "every step of this has gone"
                                : `pick step ${nxt + 1}, the next one in line`)
              : idx < 0 ? "pick this to send"
              : idx === nxt ? "pick this to send"
              : `step ${nxt + 1} comes first`;
    // Both halves of a group light up together.
    const on = nb.roadmapSel && String(nb.roadmapSel.id) === String(r.id)
               && (idx < 0 ? (steps.length ? true : nb.roadmapSel.step === null)
                           : nb.roadmapSel.step === idx);
    // The tags sit above the line rather than beside it: they are labels on the
    // whole item, and on a phone a pill sharing the first line pushed the words
    // into a column two thirds as wide as the ones under it.
    const tags = idx >= 0 || r.by !== "claude" ? ""
      : `<span class="who" title="Claude put this here">claude</span>`;
    // In reorder mode the row's three controls are replaced rather than joined:
    // five buttons and a number do not fit a phone, and moving things about is
    // not something anybody does at the same time as sending them.
    // A step that has gone does not move, and by mark rather than by prefix:
    // a session can finish step three with one and two still to send.
    const fixed = idx >= 0 && (stepGone(st)
      || (steps[idx - 1] && stepGone(steps[idx - 1]))
      || (steps[idx + 1] && stepGone(steps[idx + 1])));
    const moves = `<button class="eye mv" type="button" data-dir="-1"${
        fixed ? " disabled" : ""} aria-label="up"
      title="${fixed ? "a step that has gone stays where it is" : "move it up"}"
      >${UP}</button>
    <button class="eye mv" type="button" data-dir="1"${fixed ? " disabled" : ""}
      aria-label="down"
      title="${fixed ? "a step that has gone stays where it is" : "move it down"}"
      >${DOWN}</button>`;
    return `<div class="roadmap${st.sent ? " sent" : ""}${st.done ? " done" : ""}${
         idx >= 0 ? " step" : ""}${r.shelved ? " shelved" : ""}"
       data-id="${r.id}" data-step="${idx}">
    ${nb.roadmapOrdering ? "" : `<button class="eye go${on ? " sel" : ""}" type="button"${can ? "" : ` aria-disabled="true"`}
      title="${esc(why)}" aria-label="send"
      aria-pressed="${on ? "true" : "false"}">${SEND}</button>`}
    ${idx >= 0 ? (st.done
          ? `<span class="n tick" title="step ${idx + 1}: a session finished this ${nb.stamp(st.done)}">✓</span>`
          : `<span class="n">${idx + 1}</span>`)
                 : r.id < 0
                   ? `<span class="n id new" title="not saved yet; it gets its number when you press Save">new</span>`
                   : `<span class="n id" title="this item is R${r.id} wherever it sits, and what bb roadmap done R${r.id} takes">R${r.id}</span>`}
    <span class="body">
      ${tags ? `<span class="tags">${tags}</span>` : ""}
      <span class="txt" role="textbox" tabindex="0">${esc(st.text)}</span>
      ${st.info ? `<button type="button" class="dtog" aria-expanded="false"
        title="the technical half: files, functions, approach">▸ details</button>
      <div class="dinfo" hidden>${esc(st.info)}</div>` : ""}
    </span>
    ${nb.roadmapOrdering ? moves : `${shelf ? `<button class="eye x${r.shelved ? " on" : ""}" type="button"
      aria-label="${r.shelved ? "take it off the shelf" : "shelve it"}"
      title="${r.shelved
          ? "take it off the shelf: back among the live ones"
          : "shelve it: worth keeping, not for now. It goes dark at the bottom"
            + (steps.length ? " with its steps" : "") + " and a session is told it is parked"}"
      >${SHELF}</button>` : `<span class="eye ph"></span>`}
    <button class="eye ed" type="button" aria-label="reword"
      title="reword this line">${PENCIL}</button>
    <button class="eye rm" type="button" aria-label="drop it"
      title="${idx < 0 ? "take it off the list, with a note saying why"
                         : "drop this step; the one behind it takes its place"}"
      >${BIN}</button>`}
  </div>`;
  }

  // `force` is "the person just did this", and only a redraw somebody asked
  // for may take the list apart while a box is open in it.
  //
  // The reword box, the drop box, the send note and the + step field are
  // imperative DOM under a row, so the innerHTML below takes them and every
  // word typed into them. The poll's own guard upstream watches for STAGED
  // changes, and typing is not staged until the box's Save, so a session
  // running `bb roadmap add` in the background deleted a half-written
  // rewording under the finger holding it. Bugs has skipped its redraw while
  // a form is open since it was built; this is the same rule on the one view
  // that did not have it. `nb.roadmapItems` is still updated underneath, so
  // the next deliberate action draws with whatever arrived meanwhile.
  // Is there a box in the list that a redraw would take something from?
  //
  // The reword box, the drop confirmation and the send note are deliberate
  // states a person leaves by Save or Cancel, so they are protected whenever
  // they are open, the way the Bugs form is. The `+ step` field is not: it
  // STAYS open after each step so several can be typed in a row, and
  // protecting an open one unconditionally would mean an empty box nobody
  // closed freezes this panel for the rest of the day. So that one is
  // protected while it holds words or holds the cursor, and is fair game
  // otherwise, which is the state it spends most of its life in.
  function boxHoldingSomething(){
    const list = $("roadmapList");
    if (list.querySelector(".editbox, .dropbox, .sendbox")) return true;
    return [...list.querySelectorAll(".addstep textarea")].some(
      t => t.value.trim() !== "" || document.activeElement === t);
  }

  function drawRoadmap(j, force){
    if (j.error){ $("roadmapList").innerHTML = `<div class="hint bad">${esc(j.error)}</div>`; return; }
    if (!force && boxHoldingSomething()) return;
    // Every read and every write hands back where the list has got to, so the
    // poll below can tell this panel's own change from somebody else's. Without
    // it every write is followed by a redraw a second later, which detaches
    // whatever inline box was open (a send box, a drop confirmation) under
    // the finger that opened it.
    if (j.rev !== undefined) nb.roadmapRev = j.rev;
    // Whether there is a session to send into, from the answer OR from the
    // page's own session list, which is what lights the Claude button on
    // the project row. The two are the same fact read from the same place
    // on the server, and reading it here from one source only is what let
    // the row say running while every arrow here said no session (B214):
    // an answer drawn before the list caught up stood until something else
    // redrew, and nothing said which of the two to believe.
    const sess = j.session || (typeof liveSessions === "function" && nb.memProj
                               && liveSessions().has(myClaude(nb.memProj))
                               ? myClaude(nb.memProj) : null);
    j = Object.assign({}, j, {session: sess});
    const rows = j.items || [], live = !!sess;
    // Whatever was armed may have been crossed off, dropped, or overtaken by a
    // step in front of it since the last draw.
    if (nb.roadmapSel){
      const r = rows.find(x => String(x.id) === String(nb.roadmapSel.id));
      const ok = r && (nb.roadmapSel.step === null
        ? !(r.steps || []).length && canSend(r, -1, live)
        : canSend(r, nb.roadmapSel.step, live));
      if (!ok) nb.roadmapSel = null;
    }
    nb.roadmapSession = j.session || null;
    // Shelved ones are not counted, here or on the project row: "still to send"
    // is a question about live work, and a parked item is not asking.
    const left = rows.reduce((n, r) =>
      n + (r.shelved || nextStep(r) === null ? 0 : 1), 0);
    const parked = rows.filter(r => r.shelved).length;
    const held = nb.nbUnsaved();
    $("roadmapHint").textContent = !rows.length
      ? "Nothing yet. What goes here is read at the start of every Claude session in this project."
      : held
        ? `${left} still to send${parked ? `, ${parked} shelved` : ""}: ${held} `
          + `not saved, so nothing can be sent until you Save or Revert`
        : live
        ? `${left} still to send${parked ? `, ${parked} shelved` : ""}: ${
            esc(j.session)} is running, so the arrows are live`
        : `${left} still to send${parked ? `, ${parked} shelved` : ""}: no session `
          + `is running here, so nothing can be sent yet`;
    $("roadmapField").hidden = !rows.length && !j.finished_n;
    $("roadmapDone").textContent = j.finished_n ? `Finished (${j.finished_n})` : "Finished";
    $("roadmapDone").hidden = !j.finished_n && !nb.roadmapDoneOn;
    if (nb.roadmapLogOn) nb.drawHistory();
    {
    $("roadmapList").innerHTML = rows.map(r =>
      // The group's own row gets the same `live` as its steps now: its arrow
      // stands for the next one, so it is as clickable as that one is.
      `<div class="grp${r.shelved ? " shelved" : ""}">${stepRow(r, -1, live)}${
        (r.steps || []).map((_, i) => stepRow(r, i, live)).join("")}${
        // How a plain item becomes a plan: give it a step. Hidden while
        // reordering, where the question is only where things sit.
        nb.roadmapOrdering ? "" : `<div class="addstep" data-id="${r.id}"><button
        type="button" class="link">+ step</button></div>`}</div>`).join("");
    $("roadmapList").querySelectorAll(".addstep").forEach(box => {
      box.querySelector("button").onclick = () => openStepInput(box);
    });
    $("roadmapList").querySelectorAll(".roadmap").forEach(row => {
      const id = Number(row.dataset.id), step = Number(row.dataset.step);
      row.querySelectorAll(".mv").forEach(b => b.onclick = () =>
        moveLocally(id, step < 0 ? null : step, Number(b.dataset.dir)));
      const go = row.querySelector(".go");
      // A group's title arrow stands for its next step, so both resolve to the
      // same choice and light up together.
      if (go) go.onclick = () => {
        // A dead arrow says why when pressed (B213). It is aria-disabled
        // rather than disabled because a disabled button swallows the press
        // and the reason was only in its hover title, which a finger never
        // sees, and in the line under the whole list.
        if (go.getAttribute("aria-disabled") === "true") return notify(go.title, true);
        const r = (nb.roadmapItems || []).find(x2 => String(x2.id) === String(id));
        const steps = r?.steps || [];
        pickRoadmap(id, step >= 0 ? step : (steps.length ? nextStep(r) : null));
      };
      // Shelving never asks: nothing is lost and the same tap undoes it. That
      // is the whole difference between it and the bin beside it.
      const x = row.querySelector(".x");
      if (x) x.onclick = () =>
        stageShelve(id, !row.classList.contains("shelved"));
      // Deleting always asks. Nothing here is recoverable, and the strike beside
      // it is the reversible answer for anyone who only meant "not this one".
      const rm = row.querySelector(".rm");
      if (rm) rm.onclick = () => openDrop(row, id, step);
      // A pencil, and the words themselves. The pencil because a tap target you
      // can see is the only one a thumb finds; the words because that is where
      // the hand goes anyway. Steps too: a plan is written before it is right,
      // and the line that needed changing was always the one inside a group.
      const reword = () => openReword(row, id, step);
      // The details fold: closed by default because the row's words are the
      // decision and this is the workings, wanted when the work starts.
      const dt = row.querySelector(".dtog");
      if (dt) dt.onclick = () => {
        const info = row.querySelector(".dinfo");
        const show = info.hidden;
        // The caret turns with the slide rather than after it, so the row reads
        // as one movement instead of a glyph flicking ahead of the content.
        dt.textContent = show ? "▾ details" : "▸ details";
        dt.setAttribute("aria-expanded", String(show));
        slideHidden(info, show);
      };
      // Guarded like every other control on this row: reordering replaces all
      // three of them, so in that mode there is no pencil to bind and an
      // unguarded one took the whole redraw down with it.
      const ed = row.querySelector(".ed");
      if (ed) ed.onclick = reword;
      row.querySelector(".txt").onclick = reword;
    });
    }
    nb.roadmapItems = rows;
    nb.roadmapUnsaved = j.unsaved || {};
    if (j.batch !== undefined) nb.noteBatch(j.batch);
    nb.drawBatchNote();
    nb.syncSave();
    $("roadmapOrder").hidden = !rows.length;
    $("roadmapOrder").classList.toggle("on", nb.roadmapOrdering);
    $("roadmapLog").classList.toggle("on", nb.roadmapLogOn);
    drawSendBox(live);
    // Groups, not steps: a plan cut in half by a page boundary is a plan
    // nobody can read. The roadmap caps at 30 open items anyway, so this only
    // ever bites a list that has grown its steps.
    paginate($("roadmapList"), ":scope > .grp", {noun: "items"});
  }

  // What a session can be switched to on the way in. Tables, not free text:
  // these become part of a command typed into a terminal, and the server keeps
  // its own copy of both lists rather than trusting the one that arrives.
  // Remembered outside the box, because the box is rebuilt from scratch every
  // time its list is redrawn: a half-typed note that vanished whenever
  // something else on the panel moved would be worse than useless.
  nb.sendNoteText = "";

  // The box itself, built once and used by both lists.
  //
  // The roadmap hands a step to a session and the tracker hands it a bug; the
  // question either asks is the same one (anything to add, go or don't), so it
  // is one box rather than two that drift apart. Model and effort are not asked
  // here and are no longer applied here either: they are the project's own
  // setting, in its settings dialog, and bb-tty passes them as launch flags, so
  // a session that is up is already on them and a send is just the send. What
  // used to sit here typed /model ahead of the step, which stopped working the
  // day claude put a confirmation behind that command.
  function sendBoxEl({label, sub, placeholder, onSend, onCancel}){
    const box = document.createElement("div");
    box.className = "sendbox";
    box.innerHTML = `<div class="q">${esc(label)}${
        sub ? ` <span>· ${esc(sub)}</span>` : ""}</div>
    <textarea id="sendMore" rows="2" maxlength="500"
      placeholder="${esc(placeholder)}"></textarea>
    <div class="actbar">
      <button type="button" class="stop">Cancel</button>
      <button type="button" class="primary" id="roadmapGo">Send</button></div>`;
    const more = box.querySelector("#sendMore");
    more.value = nb.sendNoteText;
    // Kept on every keystroke rather than read at the end: a redraw between the
    // typing and the Send would otherwise take the words with it.
    more.oninput = () => { nb.sendNoteText = more.value; };
    more.onkeydown = e => {
      if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); onCancel(); }
    };
    box.querySelector(".stop").onclick = onCancel;
    box.querySelector("#roadmapGo").onclick = onSend;
    return box;
  }

  // Only ever one open, anywhere in THIS notebook: two half-written notes
  // with one Send between them is a message going to the wrong place, and
  // the Bugs view shares this one with the Roadmap, which is why it is not
  // scoped to the list.
  //
  // This notebook and not the page: two projects can be open side by side,
  // and their notes go to two different sessions, so neither is the other's
  // ambiguity. Swept page-wide, opening a note in one project deleted a
  // half-written one in the other.
  function shutSendBoxes(){
    // The clone this view lives in: makeNotebook puts the project on its
    // root, and every id inside it is the template's, so there is no id to
    // reach it by. The state object holds no element.
    const here = $("roadmapList")?.closest("[data-project]");
    (here || document).querySelectorAll(".sendbox").forEach(b => b.remove());
  }

  // The roadmap's, under the step it would send.
  //
  // Rebuilt on every draw rather than parked somewhere and moved: the rows are
  // replaced wholesale by the redraw above, so a box held over would be sitting
  // under whatever row happened to take that place. Cheap, and it cannot end up
  // pointing at the wrong line.
  function drawSendBox(live){
    const list = $("roadmapList");
    list.querySelectorAll(".sendbox").forEach(b => b.remove());
    if (!nb.roadmapSel || !live || nb.roadmapOrdering || nb.roadmapLogOn){ nb.sendShownFor = ""; return; }
    const step = nb.roadmapSel.step === null ? -1 : nb.roadmapSel.step;
    const row = list.querySelector(
      `.roadmap[data-id="${CSS.escape(String(nb.roadmapSel.id))}"][data-step="${step}"]`);
    if (!row){ nb.sendShownFor = ""; return; }
    const box = sendBoxEl({
      label: "Send this one?",
      sub: step >= 0 ? `step ${step + 1}` : "",
      placeholder: "anything to send with it (optional)",
      onSend: reallySend,
      onCancel: () => pickRoadmap(nb.roadmapSel.id, nb.roadmapSel.step),
    });
    row.after(box);
    // Only the first time this arrow arms, never again while it stays armed:
    // the box is rebuilt on every draw, and a poll landing while it is open
    // would otherwise replay the arrival two or three times a minute.
    const key = `${nb.roadmapSel.id}:${step}`;
    if (key !== nb.sendShownFor) arriveBox(box);
    nb.sendShownFor = key;
  }

  nb.roadmapItems = [];
  nb.roadmapSession = null;
  nb.roadmapUnsaved = {};  // {roadmap, memory}: what a session has not been told
  nb.roadmapSel = null;  // {id, step}: the arrow that is armed, if any
  // Which arrow's box has already unrolled. The box is rebuilt on every draw
  // (see drawSendBox), so without this a poll landing while it is open would
  // replay the arrival two or three times a minute: the animation belongs to
  // the arrow being pressed, not to the box being drawn.
  nb.sendShownFor = "";
  nb.roadmapOrdering = false;  // the rows are showing move controls instead
  // Reordering is the one edit held back. Everything else here is a decision:
  // ticked, crossed, dropped, and is written the moment it is made; arranging
  // is a draft you are in the middle of, and closing the panel on a half-done
  // shuffle should leave the order alone. So the moves live here until Save,
  // and the snapshot is what Cancel puts back.
  nb.roadmapPending = [];  // staged changes, in the order they were made
  nb.roadmapWas = null;  // the list as it was before the first staged change
  // A session's open batch, and whether one has closed since this copy of the
  // list was read. Both block Save: while it is open the list is moving, and
  // once it has closed what is on screen is out of date.
  nb.roadmapBatch = null;
  nb.roadmapStale = false;

  // Picking one arms the Send button; picking it again puts it down. The
  // highlight is the whole confirmation: the line it would send is the line the
  // arrow is sitting next to, and a sentence repeating it back was noise.
  function pickRoadmap(id, step){
    nb.roadmapSel = (nb.roadmapSel && String(nb.roadmapSel.id) === String(id) && nb.roadmapSel.step === step)
      ? null : {id, step};
    // A new target starts with an empty note. The text survives a *redraw* of
    // the box it was typed into, which is what the variable is for, but it
    // must not follow you to another step, or to a bug on the other tab, where
    // it would arrive pre-filled with words written about something else.
    nb.sendNoteText = "";
    drawRoadmap({items: nb.roadmapItems, session: nb.roadmapSession, unsaved: nb.roadmapUnsaved}, true);
  }

  // Putting the selection down, and the box with it. It redraws rather than
  // only clearing the variable: the box and the lit arrow are both drawn from
  // nb.roadmapSel, and a sent row stays selectable now (that is the point of being
  // able to send it again), so nothing else is going to take them off screen.
  function cancelSend(){
    nb.roadmapSel = null;
    drawRoadmap({items: nb.roadmapItems, session: nb.roadmapSession, unsaved: nb.roadmapUnsaved}, true);
  }

  async function reallySend(){
    if (!nb.roadmapSel) return;
    let {id, step} = nb.roadmapSel;
    // Always told, where this used to be a checkbox. The question the checkbox
    // asked ("shall I mention the list moved?") cannot have a useful "no" any
    // more: nothing can be sent until the panel is saved, so by the time a step
    // goes there IS no unsaved work to keep quiet about, and a session about to
    // act on a step is exactly who wants to know the plan around it changed.
    // It costs nothing when nothing moved: the note is empty and rides as "".
    const proj = nb.memProj;
    // Held in locals: the box is rebuilt by every redraw between here and the
    // end of this function, so the button read back at the end is not
    // necessarily the one that was pressed, but a switch that was asked for
    // still has to be the one that gets sent.
    const note = nb.sendNoteText;
    const go = $("roadmapGo");
    busy(go, "Sending");
    // Staged changes go first, always, not only when "also save" is ticked.
    // The line about to be typed into a session is one of them, and sending it
    // against a list the server has not been told about would hand over a step
    // that does not exist there. An item added in this panel has a negative id
    // until that flush; the real one comes back from it.
    if (nb.roadmapPending.length){
      nb.clashResume = null;                 // settled by hand, then Send again
      const map = await flushPending();
      if (map.has(String(id))) id = map.get(String(id));
      // Refused: the step about to be typed into a session is described by a
      // list the server has not accepted, so it must not go.
      if (nb.roadmapPending.length){
        unbusy(go, "Send");
        return;
      }
    }
    // The note rides on the same line as the step rather than chasing it: two
    // messages into one input box is how the second ends up glued to the first.
    const j = await postRoadmap({action: "send", id, step, tell: true, note});
    unbusy(go, "Send");
    if (!j) { drawSendBox(!!nb.roadmapSession); return; }
    if (!j.sent){
      // Which line stalled matters: a step left in the box is one to press
      // Enter on, but a `/model` left there has the step still to come, and
      // sending it now would glue the two together. So the switch says so.
      notify(j.switching
        ? `the /${j.switching} line was typed but not sent; something else has `
          + "the keyboard there. The step has NOT been sent; clear that tab and "
          + "send it again"
        : "typed into the session but not sent; something else has the "
          + "keyboard there; press Enter in that tab when it is clear", true);
      drawSendBox(!!nb.roadmapSession);
      return;
    }
    // Cleared only once it has gone. The pickers are a standing preference and
    // stay; a note belongs to the one thing it was written for, and finding it
    // still sitting there on the next step is how it ends up sent twice.
    nb.sendNoteText = "";
    cancelSend();
    // The notebook stays open behind it now. Sending used to close the panel
    // because a modal was in the way of the tab you were being sent to; a tab
    // is not in the way of anything, and coming back to the plan to send its
    // next step is the ordinary next thing.
    startClaude(proj, null);      // opens the tab, or goes to the one that is there
  }

  // Wrapped so the poll can tell this panel's own write from somebody
  // else's while it is still out. See nbWriting.
  async function postRoadmap(body, quiet){ return nb.writing(() => postRoadmapDo(body, quiet)); }
  async function postRoadmapDo(body, quiet){
    try{
      const r = await postJSON("/api/roadmap", {project: nb.memProj, ...body});
      const j = await r.json();
      // Somebody else wrote this item first (roadmap #26). Not a toast: the op
      // stays at the head of the queue and the band asks which version wins,
      // because the alternative (applying it) is how one of the two writers
      // silently loses their words.
      if (j.conflict){ showClash(body, j); return null; }
      if (j.error){ notify(j.error, true); return null; }
      // quiet: one of a run of moves being flushed, where redrawing between
      // each would flicker the list through every intermediate arrangement.
      if (!quiet){ drawRoadmap(j, true); refresh(); }
      return j;
    }catch(e){ notify("could not reach the server: " + e, true); return null; }
  }

  // ---- two writers, one item ------------------------------------------------
  // The optimistic half of roadmap #26. The writes here are tiny and per-field,
  // so they are not serialized behind a lock somebody has to remember to
  // release: each one carries the revision it was read at, and the server
  // refuses it if that is no longer what is stored.
  //
  // This is the refusal made useful. A message saying "somebody got there
  // first" leaves the words that were typed with nowhere to go, which is worse
  // than the overwrite it prevented: the op stays at the head of the queue, the
  // stored version is shown beside the typed one, and one of two buttons
  // decides it. Nothing is applied until it does.
  nb.clash = null;  // {op, item, rev, by, at}
  nb.clashResume = null;  // what to carry on with once it is settled

  function showClash(op, j){ nb.clash = {op, ...j.conflict}; drawClash(); }

  function settleClash(mine){
    const c = nb.clash, go = nb.clashResume;
    nb.clash = null; nb.clashResume = null;
    if (!c) return;
    // Either way the head of the queue is what moves: mine goes again saying it
    // replaces what is there NOW, theirs wins by the op simply being dropped.
    if (mine && nb.roadmapPending[0]) nb.roadmapPending[0].was = c.current;
    else nb.roadmapPending.shift();
    drawClash();
    // Read before the redraw above, which is what raised this the first time
    // round: drawClash used to clear the resume itself, so settling a conflict
    // dropped the save it was part of and left the rest of the queue staged
    // with nothing to push it.
    if (go) go();
    else nb.syncSave();      // no save to carry on with: the rest stays staged
  }

  function drawClash(){
    const box = $("roadmapClash");
    if (!box) return;
    box.hidden = !nb.clash;
    if (!nb.clash){ box.innerHTML = ""; return; }
    const op = nb.clash.op;
    // "you" in the log means a person, and the person reading this is one, but
    // not the one who made that write, or the words would have matched. So it
    // is named as the other window rather than as them.
    const who = nb.clash.by === "claude" ? "a session" : "another window";
    const when = nb.clash.at ? " " + ago(nb.clash.at) : "";
    const theirs = String(nb.clash.current ?? "");
    const mine = op.action === "remove" ? "" : String(op.text || "");
    box.innerHTML = `
    <div class="hint bad">${who} changed this while you had it open${esc(when)}.
      Nothing has been written: pick one.</div>
    <div class="clashpair">
      <div><div class="clashwho">On the list now</div>
        <div class="clashtext">${esc(theirs) || "<em>nothing</em>"}</div></div>
      <div><div class="clashwho">Yours, not written</div>
        <div class="clashtext">${op.action === "remove"
            ? "<em>you dropped it</em>" : esc(mine) || "<em>nothing</em>"}</div></div>
    </div>
    <div class="actbar">
      <button type="button" id="clashTheirs">Keep theirs</button>
      <button type="button" id="clashMine" class="primary">Use mine</button>
    </div>`;
    $("clashTheirs").onclick = () => settleClash(false);
    $("clashMine").onclick = () => settleClash(true);
  }

  // Dropping something, with the reason it went. Inline rather than a confirm()
  // box, because a confirm cannot hold a field, and the field is the point:
  // nothing here can be undone, so the only thing standing between a deleted
  // line and somebody adding it straight back is a note saying why it went.
  // Optional, deliberately. A reason demanded is a reason typed as "x".
  function openDrop(row, id, step){
    if (row.nextElementSibling?.classList.contains("dropbox")) return;
    row.parentElement.querySelectorAll(".editbox,.dropbox").forEach(b => b.remove());
    const what = row.querySelector(".txt").textContent;
    const r = (nb.roadmapItems || []).find(x => String(x.id) === String(id));
    const also = step >= 0
      ? "the one behind it takes its place"
      : (r?.steps || []).length ? `its ${r.steps.length} steps go too` : "";
    const box = document.createElement("div");
    box.className = "dropbox";
    box.innerHTML = `<div class="q">Drop this?${also ? ` <span>· ${esc(also)}</span>` : ""}</div>
    <textarea class="proseline" rows="1" maxlength="500"
      placeholder="why it is going (optional, kept in the history)"></textarea>
    <div class="actbar">
      <button type="button" class="stop">Cancel</button>
      <button type="button" class="danger">Drop it</button></div>`;
    row.after(box);
    arriveBox(box);
    const shut = () => box.remove();
    box.querySelector(".stop").onclick = shut;
    box.querySelector(".danger").onclick = () => {
      const why = box.querySelector("textarea").value;
      shut();
      stageRemove(id, step, why);
    };
    box.querySelector("textarea").onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); box.querySelector(".danger").click(); }
      if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); shut(); }
    };
    // Not focused, like everything else that opens in this window.
  }

  // Rewording, in a box under the row rather than a prompt(). A prompt is one
  // line by construction, and these are not any more: opening a three-line step
  // in one would have flattened it on the way back, which is the kind of quiet
  // data loss an edit box should never do.
  function openReword(row, id, step){
    if (row.nextElementSibling?.classList.contains("editbox")) return;
    row.parentElement.querySelectorAll(".editbox,.dropbox").forEach(b => b.remove());
    const was = row.querySelector(".txt").textContent;
    const r0 = findRow(id);
    const wasInfo = (step < 0 ? r0?.info : r0?.steps?.[step]?.info) || "";
    const box = document.createElement("div");
    box.className = "dropbox editbox";
    box.innerHTML = `<div class="q">${step < 0 ? "Reword it"
        : `Reword step ${step + 1}`}<span>: Enter saves, shift+Enter is a new line</span></div>
    <textarea maxlength="500" spellcheck="false"></textarea>
    <div class="q qd"><span>Details: the technical half: files, functions, approach</span></div>
    <textarea class="dta" maxlength="2000" spellcheck="false"
      placeholder="mostly Claude's to write; empty is fine"></textarea>
    <div class="actbar">
      <button type="button" class="stop">Cancel</button>
      <button type="button" class="primary">Save</button></div>`;
    row.after(box);
    arriveBox(box);
    const ta = box.querySelector("textarea");
    ta.value = was;
    const dta = box.querySelector(".dta");
    dta.value = wasInfo;
    const shut = () => box.remove();
    box.querySelector(".stop").onclick = shut;
    box.querySelector(".primary").onclick = () => {
      const now = ta.value, nowInfo = dta.value;
      shut();
      if (now.trim() && now !== was)
        stageEdit(id, step < 0 ? null : step, now);
      if (nowInfo !== wasInfo)
        stageInfo(id, step < 0 ? null : step, nowInfo);
    };
    ta.onkeydown = e => {
      if (e.key === "Enter" && !e.shiftKey){
        e.preventDefault(); box.querySelector(".primary").click();
      }
      if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); shut(); }
    };
    // Focused, unlike a window opening: the finger that wants this field just
    // tapped the pencil, and the text it wants to change is already in it.
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }

  // Adding steps one after another: the field stays open, so a plan is typed
  // rather than assembled a dialog at a time.
  function openStepInput(box){
    const id = box.dataset.id;
    box.innerHTML = `<textarea class="proseline" rows="1" maxlength="500"
      placeholder="then…"></textarea><button type="button" class="primary">Add</button>
      <button type="button" class="stop">Cancel</button>`;
    const inp = box.querySelector("textarea"), btn = box.querySelector(".primary");
    // Escape closes it too, but a phone keyboard has no Escape, and a field
    // that only closes by being emptied first is a field you are stuck in.
    box.querySelector(".stop").onclick = () => closeStepInput(box);
    const go = async () => {
      if (!inp.value.trim()) return closeStepInput(box);
      if (stageAddStep(id, _clean(inp.value))){
        // The redraw replaced this box; find the new one and carry on typing.
        const again = $("roadmapList").querySelector(`.addstep[data-id="${id}"]`);
        if (again) openStepInput(again);
      }
    };
    btn.onclick = go;
    inp.onkeydown = e => {
      if (e.key === "Enter"){ e.preventDefault(); go(); }
      // stopPropagation, or the document handler behind it reads the same
      // Escape as "close the panel" and the plan being typed goes with it.
      if (e.key === "Escape"){ e.preventDefault(); e.stopPropagation(); closeStepInput(box); }
    };
    // Focused, unlike anything a window opens with: this field exists because
    // the finger that wants it just tapped "+ step", and making them tap twice
    // to type in the thing they asked for is not the same problem.
    inp.focus();
  }

  function closeStepInput(box){
    box.innerHTML = `<button type="button" class="link">+ step</button>`;
    box.querySelector("button").onclick = () => openStepInput(box);
  }

  async function addRoadmap(){
    const t = $("roadmapText");
    if (!t.value.trim()) return;
    if (stageAdd(_clean(t.value))){
      t.value = "";
      // It lands at the end now, which on a phone is below the fold. Scrolled
      // to, because "did that work?" should not need a swipe to answer.
      $("roadmapList").lastElementChild?.scrollIntoView({block: "nearest"});
    }
    // Kept, not taken: the keyboard is already up because they just typed, and
    // a list is usually added to more than one line at a time.
    t.focus();
  }


  $("roadmapAdd").onclick = addRoadmap;
  $("roadmapOrder").onclick = () => {
    // Entering the mode throws nothing away either: whatever is already staged
    // stays staged, and the moves join it.
    nb.roadmapOrdering = !nb.roadmapOrdering;
    if (nb.roadmapOrdering) cancelSend();
    redrawRoadmap();
  };

  // Put the list back the way it was found. The server never saw any of it, so
  // this is only the page's own copy going back to the snapshot taken when the
  // first change was staged.
  function revertPending(){
    if (nb.roadmapPending.length && nb.roadmapWas) nb.roadmapItems = nb.roadmapWas;
    nb.roadmapPending = []; nb.roadmapWas = null;
  }

  const redrawRoadmap = () =>
    drawRoadmap({items: nb.roadmapItems, session: nb.roadmapSession, unsaved: nb.roadmapUnsaved}, true);

  // ---- staging -------------------------------------------------------------
  // Nothing the panel does touches the list until Save. Reordering worked this
  // way already; everything else used to write on the spot, which made Save mean
  // two different things depending on which control you had pressed, and left
  // no way to type three steps, look at them together, and change your mind.
  //
  // Each change is applied to the page's own copy and appended here. Save
  // replays them in the order they were made, which is what makes the server
  // arrive at what is on screen. Anything else (closing, Escape, the backdrop)
  // asks, and puts the copy back.
  //
  // Sending is not staged and cannot be: it types into a live session, which no
  // Save button can take back. It flushes whatever is pending first, so the line
  // that goes carries the list as the operator has just arranged it.
  nb.tmpId = 0;  // ids for items the server has never heard of
  // Moves on every staged change, and never goes back. loadRoadmap reads it before
  // asking and again before drawing, which is how a reply that left before the
  // operator typed is told from one that left after; see the guard there.
  nb.roadmapStaged = 0;

  function stage(op, apply){
    if (!nb.roadmapPending.length) nb.roadmapWas = structuredClone(nb.roadmapItems);
    const out = apply();
    if (out === false) return false;      // nothing actually changed
    nb.roadmapPending.push(op);
    nb.roadmapStaged++;
    redrawRoadmap();
    return true;
  }

  const findRow = id => nb.roadmapItems.find(r => String(r.id) === String(id));

  // The same tidy roadmap.py's _clean does, so the row on screen before Save is
  // the row that lands after it rather than one that quietly loses a space.
  const _clean = t => String(t ?? "").replace(/\r\n?/g, "\n").split("\n")
    .map(l => l.split(/\s+/).filter(Boolean).join(" "))
    .filter((l, i, a) => l || (i && a[i - 1])).slice(0, 12)
    .join("\n").replace(/\n+$/, "");

  function stageAdd(text){
    const id = --nb.tmpId;                   // negative: not on the server yet
    return stage({action: "add", text, tmp: id}, () => {
      nb.roadmapItems.splice(nb.roadmapItems.filter(r => !r.shelved).length, 0,
                       {id, text, by: "you", sent: 0, steps: [], shelved: 0});
      return true;
    });
  }

  function stageAddStep(id, text){
    return stage({action: "add-step", id, text}, () => {
      const r = findRow(id);
      if (!r) return false;
      (r.steps = r.steps || []).push({text, sent: 0});
    });
  }

  // What a replacing op believes it is replacing, carried with it so the write
  // can be refused rather than applied if that is no longer what is stored
  // (roadmap #26). One FIELD's words, not a version for the row: a session
  // attaching details to an item while the operator rewords its line is two
  // people doing two things.
  //
  // The state flips beside them (shelve, cross, reorder) carry nothing:
  // they lose nobody's words if they land after somebody else's change, and a
  // dialog asking which of them wins would be a question with no wrong answer.
  const wasOf = (id, step, act) => {
    const r = findRow(id);
    if (!r) return undefined;
    const t = step !== undefined && step !== null && step >= 0
      ? (r.steps || [])[step] : r;
    if (!t) return undefined;
    return act === "info" ? (t.info || "") : (t.text || "");
  };

  function stageEdit(id, step, text){
    return stage({action: "edit", id, step, text, was: wasOf(id, step, "edit")}, () => {
      const r = findRow(id);
      if (!r) return false;
      if (step === null || step < 0) r.text = text;
      else if ((r.steps || [])[step]) r.steps[step].text = text;
      else return false;
    });
  }

  function stageInfo(id, step, text){
    return stage({action: "info", id, ...(step !== null ? {step} : {}), text,
                  was: wasOf(id, step, "info")}, () => {
      const r = findRow(id);
      if (!r) return false;
      const t = step === null ? r : (r.steps || [])[step];
      if (!t) return false;
      if (text.trim()) t.info = text; else delete t.info;
    });
  }

  function stageRemove(id, step, why){
    return stage({action: "remove", id, ...(step >= 0 ? {step} : {}), why,
                  was: wasOf(id, step, "remove")}, () => {
      const i = nb.roadmapItems.findIndex(r => String(r.id) === String(id));
      if (i < 0) return false;
      if (step >= 0) nb.roadmapItems[i].steps.splice(step, 1);
      else nb.roadmapItems.splice(i, 1);
    });
  }

  function stageShelve(id, on){
    return stage({action: "shelve", id, on}, () => {
      const i = nb.roadmapItems.findIndex(r => String(r.id) === String(id));
      if (i < 0) return false;
      const [r] = nb.roadmapItems.splice(i, 1);
      r.shelved = on ? Math.floor(Date.now() / 1000) : 0;
      // The same place the server would put it: the shelf is the bottom of the
      // list, and coming back off it means the end of the live ones.
      if (on) nb.roadmapItems.push(r);
      else nb.roadmapItems.splice(nb.roadmapItems.filter(x => !x.shelved).length, 0, r);
    });
  }

  // One swap, on the page's copy. The same swap the server would do, so that
  // replaying the list of them at Save arrives at what is on screen.
  function moveLocally(id, step, dir){
    stage({action: "move", id, step, dir}, () => {
      const i = nb.roadmapItems.findIndex(r => String(r.id) === String(id));
      if (i < 0) return false;
      const seq = step === null ? nb.roadmapItems : (nb.roadmapItems[i].steps || []);
      const at = step === null ? i : step;
      const to = at + dir;
      if (to < 0 || to >= seq.length) return false;
      [seq[at], seq[to]] = [seq[to], seq[at]];
    });
  }

  // Replay, in order. An item added here has a negative id the server has never
  // seen, so the id it comes back with is substituted into everything that was
  // staged against it: a step typed onto an item that did not exist yet is the
  // ordinary case, not the exotic one.
  async function flushPending(){
    const map = new Map();
    const real = v => map.has(String(v)) ? map.get(String(v)) : v;
    // What each FIELD now holds, after the write before this one. Editing the
    // same line twice before pressing Save stages two ops both claiming to
    // replace the words that were on screen, and the second would then be
    // refused as a conflict with the first; this panel arguing with itself.
    // After a write, what is stored is what was just written.
    const now = new Map();
    const fkey = b => `${b.id}:${b.step ?? -1}:${b.action === "info" ? "i" : "t"}`;
    // Taken one at a time rather than emptied up front: a refusal half way down
    // used to discard everything behind it as well, which turned one rejected
    // edit into the loss of a whole panel's work. What is left stays staged, so
    // Save can be pressed again once whatever it was is dealt with.
    while (nb.roadmapPending.length){
      const op = nb.roadmapPending[0];
      const body = {...op};
      delete body.tmp;
      if (body.id !== undefined) body.id = real(body.id);
      if (body.was !== undefined && now.has(fkey(body)))
        body.was = now.get(fkey(body));
      const j = await postRoadmap(body, true);
      if (!j) return map;                 // postRoadmap has already said why
      nb.roadmapPending.shift();
      if (op.action === "add" && j.item) map.set(String(op.tmp), j.item.id);
      if (body.was !== undefined && op.action !== "remove")
        now.set(fkey(body), body.text);
    }
    nb.roadmapWas = null;
    return map;
  }
  $("roadmapText").onkeydown = e => {
    if (e.key === "Enter"){ e.preventDefault(); addRoadmap(); }
    // Escape in a field with something in it clears the field, not the panel.
    if (e.key === "Escape" && e.target.value){
      e.preventDefault(); e.stopPropagation(); e.target.value = "";
    }
  };

  // ---- the finished ones (R78) --------------------------------------------
  // Ticked-off items leave the list (a list is read to find out what is
  // left) and live in the history with their plans. The toggle at the top
  // fetches them and draws them below the shelved ones, struck through,
  // with no arrows: there is nothing left to send. Off by default, and off
  // again when the notebook reopens.
  async function loadFinished(){
    let j;
    try{
      const r = await postJSON("/api/roadmap", {project: nb.memProj, action: "finished"});
      j = await r.json();
    }catch(e){ j = {error: String(e)}; }
    nb.roadmapDone = j.finished || [];
    drawFinished();
  }
  function drawFinished(){
    const host = $("roadmapDoneList");
    if (!host) return;
    if (!nb.roadmapDoneOn){ host.innerHTML = ""; host.hidden = true; return; }
    host.hidden = false;
    const rows = nb.roadmapDone;
    if (rows === null){ host.innerHTML = `<div class="loading">loading…</div>`; return; }
    if (!rows.length){ host.innerHTML = `<div class="empty">nothing finished yet</div>`; return; }
    const when = t => t ? fmtTime(t * 1000, {day: "2-digit", month: "short"}) : "";
    host.innerHTML = rows.map(r => `<div class="grp done" data-done="${r.id}">
      <div class="roadmap"><span class="rid">R${r.id}</span> <span class="txt">${esc(r.text || "")}</span>
        <span class="dim"> · done${r.done_by ? " by " + esc(r.done_by) : ""}${r.done_at ? " " + esc(when(r.done_at)) : ""}</span></div>${
      (r.steps || []).map((st, i) => `<div class="roadmap step"><span class="rid">${i + 1}.</span> <span class="txt">${esc(st.text || "")}</span></div>`).join("")}
    </div>`).join("");
  }
  $("roadmapDone").onclick = () => {
    nb.roadmapDoneOn = !nb.roadmapDoneOn;
    $("roadmapDone").classList.toggle("on", nb.roadmapDoneOn);
    if (nb.roadmapDoneOn && nb.roadmapDone === null) loadFinished();
    else drawFinished();
  };
  nb.drawFinished = drawFinished;

  return {cancelSend, drawSendBox, flushPending, loadRoadmap, postRoadmap, redrawRoadmap, revertPending, sendBoxEl, shutSendBoxes};
}

// ---- a step that needs no sending -----------------------------------------
// Handed over, or finished by a session. Two marks, one question: sent is
// the dashboard's and says a line went; done is a session's and says the
// work is finished, sent or not. Moved here from index.html: only this view
// asks.

// A step that needs no sending: handed over, or finished by a session.
// Two marks, one question: sent is the dashboard's and says a line went;
// done is a session's and says the work is finished, sent or not.
const stepGone = s => !!(s.sent || s.done);

function nextStep(r){
  const steps = r.steps || [];
  if (!steps.length) return stepGone(r) ? null : -1;
  const i = steps.findIndex(s => !stepGone(s));
  return i < 0 ? null : i;
}
