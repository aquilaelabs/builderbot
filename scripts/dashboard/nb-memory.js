// The notebook's memories, the second half of the Briefing view: read,
// edited, written by hand and forgotten, and the refusal when a memory moved
// on disk. One classic script beside index.html (docs/nodes.md §13): one file
// per notebook view (R60). A factory makeNotebook calls per notebook.

"use strict";

function nbMemoryView({$, nb}){
  async function loadMemory(gen){
    let j;
    try{
      const r = await fetch("/api/memory?project=" + encodeURIComponent(nb.memProj));
      j = await r.json();
    }catch(e){ j = {error: String(e)}; }
    if (gen !== nb.memGen) return;              // closed, or reopened elsewhere
    if (j.error){ $("memWhere").textContent = "memory: " + j.error; return; }
    drawMemory(j);
  }

  // The digest of the index as it was loaded, for the write that regenerates
  // it: save_index rebuilds MEMORY.md from the lines the client sent, so a
  // stale one drops the line another writer just added: the third of roadmap
  // #26's three exposures, and the quietest.
  nb.memIndexRev = "";

  // The briefing's head row: one line for both halves of the tab, in the
  // order they sit: the rules, then what Claude remembers. Drawn by whichever
  // half arrives, so it is right after the first and complete after the second.
  function briefingHead(){
    const el = $("memWhere");
    if (!el) return;
    const r = nb.ruleData?.rules?.length;
    const bits = [];
    if (r !== undefined) bits.push(r ? `${r} rule${r === 1 ? "" : "s"}` : "no rules");
    if (nb.memN !== null) bits.push(nb.memN ? `${nb.memN} ${nb.memN === 1 ? "memory" : "memories"}` : "nothing remembered yet");
    el.textContent = "what every session here starts with" + (bits.length ? ": " + bits.join(", ") : "");
  }

  function drawMemory(j){
    nb.memLast = j;
    const n = j.memories.length;
    nb.memIndexRev = j.index_rev || "";
    if (j.rev !== undefined) nb.memRev = j.rev;
    nb.memN = j.exists ? n : 0;
    briefingHead();
    $("memWhere").title = j.dir;
    nb.memTypes = j.types || nb.memTypes;
    // The index and the files disagreeing is the one thing on this tab that is
    // not a memory, so it is a section rather than two loose orange paragraphs
    // above the list. The section's own default is what it wants: open on a
    // desktop, where there is room and this is a warning about what Claude
    // reads; shut on a phone, where the warnings were what you scrolled past
    // to reach a memory. The count is on the heading either way, in the warn
    // colour, so a shut one still says something is wrong.
    $("memDrift").innerHTML = j.issues.length
      ? docSection("memory", "drift", "Index",
                   `${j.issues.length} problem${j.issues.length === 1 ? "" : "s"}`,
                   j.issues.map(i => `<div>${esc(i.text)}</div>`).join(""),
                   {cls: "warn"})
      : "";
    wireSections($("memDrift"));
    // The note is offered only when there is a session to put it in, and says
    // what it will do: the text is typed, not sent. See memory.py's notify().
    $("memCount").textContent = n ? "Memories: newest first" : "Memories";
    // Which were open before this redraw. Saving reloads the book, and folding
    // away the memory that was just edited is the wrong answer to "did that
    // work?": the whole point is to look at it again.
    const open = new Set([...$("memList").querySelectorAll(".mem[open]")]
                         .map(d => d.dataset.file));
    // What is being typed into the rows that have fields out, carried across
    // the redraw the way the Tests view carries its drafts: a redraw arrives
    // after every save, and it must not take a half-written memory with it.
    const typed = new Map();
    $("memList").querySelectorAll(".mem").forEach(d => {
      const ta = d.querySelector("textarea[data-file]");
      const t = d.querySelector(".ixt"), h = d.querySelector(".ixh");
      if (ta || t) typed.set(d.dataset.file, {text: ta?.value, title: t?.value, hook: h?.value});
    });
    $("memList").innerHTML = j.memories.map(m => `
    <details class="mem" data-file="${esc(m.file)}"${open.has(m.file) ? " open" : ""}>
      <summary>
        ${m.type ? `<span class="mtype ${esc(m.type)}">${esc(m.type)}</span>` : ""}
        <span class="mname">${esc(m.name)}</span>
        <span class="mwhen">${ago(m.when)}</span>
      </summary>
      <div class="body">${!nb.memEditing.has(m.file) || m.big ? `
        <div class="bfield"><label>in the index</label><div class="bval${m.listed ? "" : " dim"}">${m.listed
            ? `${esc(m.title)}: ${esc(m.hook)}`
            : "not in the index: a session reads this only when it searches memories"}</div></div>
        ${m.description ? `<div class="mdesc">${esc(m.description)}</div>` : ""}
        ${m.big
            ? `<div class="hint bad">${(m.bytes/1024).toFixed(0)}kB: too large to
               edit here; open it in a terminal</div>`
            : `<div class="bfield"><label>the memory</label><div class="bval mtext">${esc(m.text)}</div></div>`}
        <div class="actbar macts">
          ${m.big ? "" : `<button type="button" class="mEdit">Edit</button>`}
          <button type="button" class="danger" data-del="${esc(m.file)}"
            title="delete this memory and take its line out of the index"
            >Remove</button>
        </div>` : `
        <div class="ix" data-file="${esc(m.file)}">
          ${lbl("", "Title")}
          <input class="ixt" maxlength="80" autocomplete="off" spellcheck="false"
            value="${esc(m.title)}">
          ${lbl("", "Hook", "one line, what it says. Recall matches on it")}
          <textarea class="ixh proseline" rows="1" maxlength="240"
            >${esc(m.hook)}</textarea>
        </div>
        <div class="ixnote${m.listed ? "" : " bad"}">${m.listed
            ? "Its line in the index: the one part loaded into every session started here."
            : "Not in the index: a session reads it only when it searches memories. Save adds the line."}</div>
        ${m.description ? `<div class="mdesc">${esc(m.description)}</div>` : ""}
        ${m.big
            ? `<div class="hint bad">${(m.bytes/1024).toFixed(0)}kB: too large to
               edit here; open it in a terminal</div>`
            : `<textarea spellcheck="false" autocomplete="off"
               data-file="${esc(m.file)}"
               data-rev="${esc(m.rev || "")}">${esc(m.text)}</textarea>
             <!-- No status on this one: what there is to say about a memory
                  is said by the note above the editor, and repeating it here
                  would be the same sentence twice on one screen. -->
             <div class="actbar macts">
               <span class="state">Save at the foot writes it</span>
               <button type="button" class="stop mCancel"
                 title="discard what was typed">Cancel</button>
               <button type="button" class="danger" data-del="${esc(m.file)}"
                 title="delete this memory and take its line out of the index"
                 >Remove</button>
             </div>`}`}
      </div>
    </details>`).join("")
      // Said in the list, where every other view says it, rather than by
      // hiding the list and leaving a heading over nothing.
      || `<div class="empty">none yet: sessions write these as they learn the project; Write a memory adds one by hand</div>`;
    paginate($("memList"), ":scope > .mem", {noun: "memories"});
    // The fold, driven rather than left to the browser's instant one: the same
    // height tween the sidebar cards use, so a memory opens the way a card does.
    $("memList").querySelectorAll(".mem > summary").forEach(sum => {
      sum.onclick = e => {
        e.preventDefault();                       // the browser's snap, replaced
        slideDetails(sum.parentElement, !sum.parentElement.open);
      };
    });
    $("memList").querySelectorAll("textarea[data-file], .ix input").forEach(t => {
      t.dataset.was = t.value;
      t.oninput = nb.syncSave;
    });
    // ...and what was being typed goes back in, over the stored text `was`
    // now remembers, so the redraw changed nothing about what is unsaved.
    typed.forEach((v, file) => {
      const d = $("memList").querySelector(`.mem[data-file="${CSS.escape(file)}"]`);
      if (!d) return;
      const ta = d.querySelector("textarea[data-file]");
      const t = d.querySelector(".ixt"), h = d.querySelector(".ixh");
      if (ta && v.text !== undefined) ta.value = v.text;
      if (t && v.title !== undefined) t.value = v.title;
      if (h && v.hook !== undefined) h.value = v.hook;
    });
    $("memList").querySelectorAll(".mEdit").forEach(b => b.onclick = () => {
      nb.memEditing.add(b.closest(".mem").dataset.file);
      drawMemory(nb.memLast);
    });
    $("memList").querySelectorAll(".mCancel").forEach(b => b.onclick = () => {
      const d = b.closest(".mem");
      nb.memEditing.delete(d.dataset.file);
      // Its fields go before the redraw reads them, so nothing typed is carried.
      d.querySelectorAll("textarea[data-file], .ix input").forEach(t => t.remove());
      drawMemory(nb.memLast);
    });
    // Not while one is being typed into: a redraw arrives after every save, and
    // it should not take a half-written memory with it.
    if (!$("naName")) drawMemAdd();
    nb.syncSave();
    $("memList").querySelectorAll("[data-del]").forEach(b =>
      b.onclick = () => forgetMemory(b.dataset.del));
  }

  // ---- a memory that moved on disk ----------------------------------------
  // Different from an item's conflict in the one way that matters: a memory is
  // a whole document, and the version in the editor may be an hour of typing.
  // So there is no "keep theirs" that quietly drops it. What is stored is put
  // on screen to read and copy from, and the only two answers are to write over
  // it or to reload deliberately, with the loss said out loud.
  nb.memClash = null;

  // Which memories have their fields out. A memory is READ by default, like a
  // bug report and a rule: Edit puts the fields in its place, Save writes and
  // puts them away, Cancel puts them away and drops what was typed.
  nb.memEditing = new Set();
  nb.memLast = null;  // the last payload drawn, for a redraw with nothing fetched

  function drawMemClash(){
    const box = $("memClash");
    if (!box) return;
    box.hidden = !nb.memClash;
    if (!nb.memClash){ box.innerHTML = ""; return; }
    const c = nb.memClash;
    box.innerHTML = `
    <div class="hint bad">${esc(c.what)} changed on disk while you had it
      open${c.at ? " " + esc(ago(c.at)) : ""}. Nothing has been written; your version is still in the editor.</div>
    <div class="clashwho">What is on disk now</div>
    <div class="clashtext big">${esc(c.current) || "<em>empty</em>"}</div>
    <div class="actbar">
      <button type="button" id="memClashDrop" title="reload what is on disk now; what you typed here is dropped">Keep theirs</button>
      <button type="button" id="memClashMine" class="primary" title="write your version over what is on disk now">Use mine</button>
    </div>`;
    $("memClashDrop").onclick = () => { nb.memClash = null; drawMemClash();
                                        nb.memEditing.clear(); loadMemory(nb.memGen); };
    $("memClashMine").onclick = async () => {
      const c2 = nb.memClash; nb.memClash = null; drawMemClash();
      // Rewritten against what is there now, which is what makes it a decision
      // rather than a race won twice.
      if (await postMemory({...c2.body, rev: c2.rev}))
        nb.memEditing.delete(c2.body.file);
      await loadMemory(nb.memGen); refresh(); nb.syncSave();
    };
  }

  // Wrapped so the poll can tell this panel's own write from somebody
  // else's while it is still out. See nbWriting.
  async function postMemory(body){ return nb.writing(() => postMemoryDo(body)); }
  async function postMemoryDo(body){
    if (nb.nbHeld() && body.action !== "history"){
      notify("a session is part-way through changing this notebook: "
             + "check the banner at the top", true);
      return null;
    }
    try{
      const r = await postJSON("/api/memory", {project: nb.memProj, ...body});
      const j = await r.json();
      if (j.conflict){
        nb.memClash = {body, what: body.action === "index" ? "The index" : body.file,
                    ...j.conflict};
        drawMemClash();
        return null;
      }
      if (j.error){ notify(j.error, true); return null; }
      return j;
    }catch(e){ notify("could not reach the server: " + e, true); return null; }
  }

  // One button for the lot: any memory whose text or index line was touched.
  // Saving each field as it blurs would be fewer clicks and worse: an edit to
  // a memory is a deliberate act, and it should take one.
  // Is there anything in the memory half that has not been written?
  function memDirty(){
    const l = $("memList");
    return !!l && [...l.querySelectorAll("textarea[data-file], .ix input")]
      .some(t => t.value !== t.dataset.was);
  }

  // Every memory's index line as it now reads. The index is written whole, from
  // the fields, rather than patched line by line, which is what keeps it from
  // ever describing a memory that is not there.
  function memLines(){
    return [...$("memList").querySelectorAll(".ix")].map(d => ({
      file: d.dataset.file,
      title: d.querySelector(".ixt").value,
      hook: d.querySelector(".ixh").value}));
  }

  async function saveMemory(quiet){
    const edits = [];
    $("memList").querySelectorAll("textarea[data-file]").forEach(t => {
      // With the digest of what was loaded: a memory is a whole-file write and
      // the genuine last-writer-wins of this panel, so it is the one that most
      // needed a revision (roadmap #26).
      if (t.value !== t.dataset.was)
        edits.push({file: t.dataset.file, text: t.value, rev: t.dataset.rev || ""});
    });
    const ix = [...$("memList").querySelectorAll(".ix input")]
      .some(t => t.value !== t.dataset.was);
    if (!edits.length && !ix){ if (!quiet) notify("nothing changed"); return; }
    let done = 0, want = edits.length + (ix ? 1 : 0);
    // Written, so the fields go away, except a row whose write was refused,
    // whose typing the clash band promises is still in the editor.
    const kept = new Set();
    for (const e of edits){
      if (await postMemory({action:"save", ...e})) done++; else kept.add(e.file);
    }
    if (ix){
      if (await postMemory({action:"index", lines: memLines(), rev: nb.memIndexRev})) done++;
      else nb.memEditing.forEach(f => kept.add(f));   // the index lines live in every open row
    }
    nb.memEditing = kept;
    if (done && !quiet)
      notify(`saved ${done} of ${want}: Claude reads these when a session starts`);
    if (!quiet){ await loadMemory(nb.memGen); refresh(); }
  }

  // ---- writing one by hand ------------------------------------------------
  // Claude writes these itself, mid-conversation, and mostly that is the right
  // way round. This is for the other case: a standing instruction the operator
  // would otherwise have to say once per session and hope it stuck.
  nb.memTypes = ["user", "feedback", "project", "reference"];
  const TYPE_WHAT = {
    user: "who you are: role, expertise, how you like to work",
    feedback: "how sessions here should work, and why",
    project: "something about this work that the code does not say",
    reference: "a pointer somewhere else: a URL, a dashboard, a ticket"};

  function drawMemAdd(){
    const box = $("memAdd");
    box.innerHTML = `<div class="addbar" data-add="memory">
    <button type="button">Write a memory</button></div>`;
    box.querySelector("button").onclick = openMemAdd;
  }

  // A slug of the title, which is both the file name and the memory's `name`.
  // Refused rather than repaired on the server, so the field shows what will be
  // written and stays editable.
  const memSlug = t => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .slice(0, 60).replace(/^-+|-+$/g, "");

  // Closing it is a fold too, so Cancel and a written memory both roll the form
  // back up to its link instead of the list under it jumping.
  function shutMemAdd(){ swapBox($("memAdd"), drawMemAdd); }

  function openMemAdd(){
    const box = $("memAdd");
    swapBox(box, () => paintMemAdd(box));
  }

  function paintMemAdd(box){
    box.innerHTML = `<div class="memadd">
    <label for="naTitle">Title<span class="help" data-tip="how it reads in the index" tabindex="0">?</span></label>
    <input id="naTitle" maxlength="80" autocomplete="off" placeholder="No parsed progress">
    <div class="two">
      <div><label for="naName">File</label>
        <input id="naName" maxlength="60" autocomplete="off" spellcheck="false"
          placeholder="no-parsed-progress"></div>
      <div><label for="naType">Kind</label>
        <select id="naType">${nb.memTypes.map(t =>
            `<option value="${esc(t)}">${esc(t)}</option>`).join("")}</select></div>
    </div>
    <div class="hint" id="naWhat"></div>
    <label for="naHook">Hook (required)<span class="help" data-tip="one line saying what this memory is about; the index lists it, and a memory needs one" tabindex="0">?</span></label>
    <textarea id="naHook" class="proseline" rows="1" maxlength="240"
      placeholder="a word and an animated ellipsis, never a bar or a percentage"></textarea>
    <label for="naBody">The memory itself</label>
    <textarea id="naBody" spellcheck="false"
      placeholder="The fact, in a line or two. For a kind that is guidance, follow it with why it is the rule and how to apply it."></textarea>
    <div class="actbar">
      <button type="button" class="stop" id="naCancel">Cancel</button>
      <button type="button" class="primary" id="naGo">Write it</button></div>
  </div>`;
    // The file name follows the title until it is typed in, and then stops:
    // renaming a memory is a thing people do deliberately, once.
    const t = $("naTitle"), n = $("naName");
    t.oninput = () => { if (!n.dataset.mine) n.value = memSlug(t.value); };
    n.oninput = () => { n.dataset.mine = "1"; };
    const what = () => $("naWhat").textContent = TYPE_WHAT[$("naType").value] || "";
    $("naType").onchange = what; what();
    $("naCancel").onclick = shutMemAdd;
    $("naGo").onclick = createMemory;
    // Deliberately unfocused, like every other field in this window: five of
    // them appearing under a keyboard is the thing being avoided.
  }

  async function createMemory(){
    const b = $("naGo"), was = b.textContent;
    // The one field the server refuses without, said on the form rather
    // than as a toast that names no field (16 Sep).
    if (!$("naHook").value.trim()){
      $("naWhat").textContent = "a hook is required: one line saying what this memory is about";
      $("naHook").focus();
      return;
    }
    busy(b, "Writing");
    const j = await postMemory({action: "create",
      name: $("naName").value.trim(), title: $("naTitle").value.trim(),
      hook: $("naHook").value.trim(), type: $("naType").value,
      body: $("naBody").value});
    unbusy(b, was);
    // Left as it was typed on a refusal: postMemory has already said why, and
    // the fix is a word in one of these fields, not typing all five again.
    if (!j) return;
    notify(j.file + " written: a session started here reads it from now on");
    shutMemAdd();
    await loadMemory(nb.memGen);
    refresh();
  }

  async function forgetMemory(file){
    if (!confirm(`Forget ${file}?

The file goes, and its line comes out of the`
      + ` index. A running session keeps what it already read.`)) return;
    if (await postMemory({action:"delete", file})){
      nb.memEditing.delete(file);
      notify(`${file} forgotten`);
      await loadMemory(nb.memGen);
      refresh();
    }
  }

  return {briefingHead, loadMemory, memDirty, postMemory, saveMemory};
}
