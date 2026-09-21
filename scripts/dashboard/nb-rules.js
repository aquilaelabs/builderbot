// The notebook's house rules (roadmap #7): the operator's and a session's,
// read, edited, staged and saved with the rest of the notebook. One classic
// script beside index.html (docs/nodes.md §13): one file per notebook view
// (R60). A factory makeNotebook calls per notebook.
function nbRulesView({$, nb, project}){
  async function loadRules(){
    nb.loadCodebase().then(() => drawRules());
    try{
      const r = await fetch("/api/rules?project=" + encodeURIComponent(project));
      nb.ruleData = await r.json();
    }catch(e){ nb.ruleData = {error: String(e), rules: []}; }
    nb.rulesRev = revs[`rules:${project}`] ?? nb.rulesRev;
    nb.rulePending = null;
    nb.ruleClash = null;
    drawRules();
  }

  // The global rules, read-only, under the project's own. The server has always
  // sent them and the page never drew them, so somebody writing a project rule
  // could not see what was already in force: the conflict worth preventing
  // starts with not knowing. Under the project's list rather than above it, so
  // Add stays the first band and what is this project's own comes first. A
  // class of their own, NOT .rulerow: every handler and every selector in
  // here means "one of this project's rules" by that class, and a read-only
  // row wearing it was wired for an Edit button it does not have.
  function globalRules(gs){
    gs = gs.filter(g => !g.disabled);
    if (!gs.length) return "";
    const cond = r => (r.paths || []).length || (r.words || []).length;
    return `<div class="sub dim ggroup">also in force here, set for every project in Controller settings</div>
      <div class="field" id="rlGlobal">${gs.map(g => `
        <details class="bug grule">
          <summary><span class="btitle">${esc(g.name || "")}</span>
            <span class="rlkind ${cond(g) ? "cond" : ""}">${cond(g) ? "on its triggers" : "every session"}</span>
            <span class="pill">global</span></summary>
          <div class="body"><div class="bfield"><label>rule</label><div class="bval">${esc(g.text || "")}</div></div>${
            (g.paths || []).length ? `<div class="bfield rltrig"><label>files</label><div class="bval">${esc(g.paths.join(", "))}</div></div>` : ""}${
            (g.words || []).length ? `<div class="bfield rltrig"><label>words</label><div class="bval">${esc(g.words.join(", "))}</div></div>` : ""}</div>
        </details>`).join("")}</div>`;
  }
  // What a project rule shares with a global one, in a sentence for its row.
  const overlapLine = r => (r.overlaps || []).map(o =>
    `the global rule ${o.name} also fires on ${[...(o.words || []), ...(o.paths || [])].join(", ")}`).join("; ");

  // What is on screen: the staged copy if anything has been typed, otherwise
  // what the server last said.
  const ruleRows = () => nb.rulePending || (nb.ruleData?.rules || []);
  const ruleDirty = () => nb.rulePending !== null;

  function ruleStage(fn){
    nb.rulePending = (nb.rulePending || (nb.ruleData?.rules || [])).map(r => ({...r}));
    fn(nb.rulePending);
    drawRules();
    nb.syncSave();
  }

  // What this rule costs and when it arrives, in a sentence. Both the draw and
  // the keystroke that turns one kind into the other read it from here.
  function ruleWhen(r){
    const on = (r.paths || []).length || (r.words || []).length;
    return on
      ? `Named in every session; its text arrives on the turn the work matches. `
        + `A session reads it with <code>bb rules show ${esc(r.name || "…")}</code>.`
      : `In front of every session started here, and paid for on every one. `
        + `Give it a trigger and it arrives only when it applies.`;
  }

  function drawRules(){
    nb.briefingHead();
    const box = $("rulesBox");
    if (!box) return;
    const d = nb.ruleData || {};
    if (d.error){
      box.innerHTML = `<div class="field"><div class="hint bad">rules: ${esc(d.error)}</div></div>`;
      return;
    }
    const rows = ruleRows();
    const cond = r => (r.paths || []).length || (r.words || []).length;
    const standing = rows.filter(r => !cond(r)).length;
    // The cost, said out loud. "Is this rule worth keeping" is not a question
    // anybody can answer without knowing what it is charged for, and the
    // charge is on every session started in this project, forever.
    const chars = ruleDirty() ? null : d.chars;
    const body = `
      <div class="hint">How you want this project worked on. A session reads these
        at the start; it may add rules of its own, marked as its, and cannot
        change yours.</div>
      <div class="addbar" data-add="rule"><button type="button" id="rlAdd">Add a rule</button></div>
      <div class="field" id="rlList">${rows.map((r, i) => `
        <details class="bug rulerow${nb.ruleEditing.has(i) ? " editing" : ""}" data-i="${i}"${
            nb.ruleEditing.has(i) || nb.ruleOpen.has(i) ? " open" : ""}>
          <summary>
            <span class="btitle rlNameRO">${esc(r.name || "(unnamed)")}</span>
            <span class="rlkind ${cond(r) ? "cond" : ""}">${
              cond(r) ? "on its triggers" : "every session"}</span>${
              r.by === "claude" ? `<span class="pill">a session's</span>` : ""}${
              (r.overlaps || []).length ? `<span class="pill warn">shares ground with a global rule</span>` : ""}
          </summary>
          <div class="body">${nb.ruleEditing.has(i) ? `
            ${lbl("", "Name", "a short name; the listing and bb rules show NAME use it")}
            <input class="rlName" maxlength="40" autocomplete="off" spellcheck="false"
              placeholder="tests" value="${esc(r.name || "")}"
              aria-label="rule name">
            ${lbl("", "The rule")}
            <textarea class="rlText" spellcheck="false" maxlength="2000">${esc(r.text || "")}</textarea>
            <div class="two">
              <div>${lbl("", "Files it covers", "paths or globs, comma-separated. The rule arrives when a session is about to edit one")}
              <input class="rlPaths" autocomplete="off" spellcheck="false"
                placeholder="scripts/agent, *.kt"
                value="${esc((r.paths || []).join(", "))}" aria-label="paths"></div>
              <div>${lbl("", "Words that raise it", "comma-separated. The rule arrives when a session is asked about one")}
              <input class="rlWords" autocomplete="off" spellcheck="false"
                placeholder="agent, protocol"
                value="${esc((r.words || []).join(", "))}" aria-label="words"></div>
            </div>
            <div class="two">
              <div>${lbl("", "Document", "the file in the repo that defines it in full")}
              <input class="rlDoc" autocomplete="off" spellcheck="false"
                placeholder="docs/design-language.md"
                value="${esc(r.doc || "")}" aria-label="document"></div>
              <div>${lbl("", "Check", "the command that verifies it; bb rules check runs it")}
              <input class="rlCheck" autocomplete="off" spellcheck="false"
                placeholder="bash scripts/test.sh"
                value="${esc(r.check || "")}" aria-label="check"></div>
            </div>
            <div class="actbar macts">
              <span class="state">${ruleWhen(r)} · Save at the foot writes it</span>
              <button type="button" class="stop rlCancel" title="put the fields away: what was typed here is dropped">Cancel</button>
              <button type="button" class="danger rlRm">Remove</button>
            </div>` : `
            <div class="bfield"><label>rule</label><div class="bval rlBody">${esc(r.text || "")}</div></div>
            ${(r.paths || []).length ? `<div class="bfield rltrig"><label>files</label><div class="bval">${esc((r.paths || []).join(", "))}</div></div>` : ""}
            ${(r.words || []).length ? `<div class="bfield rltrig"><label>words</label><div class="bval">${esc((r.words || []).join(", "))}</div></div>` : ""}
            ${(r.overlaps || []).length ? `<div class="bfield rlover"><label>shares ground</label><div class="bval">${esc(overlapLine(r))}. Both reach a session; where they disagree it follows this one and says so.</div></div>` : ""}
            ${r.doc ? `<div class="bfield rlframe"><label>defined in</label><div class="bval">${esc(r.doc)}</div></div>` : ""}
            ${r.check ? `<div class="bfield rlframe"><label>checked by</label><div class="bval">${esc(r.check)} <span class="dim">· bb rules check ${esc(r.name || "")}</span></div></div>` : ""}
            <div class="actbar macts">
              <span class="state">${ruleWhen(r)}</span>
              <button type="button" class="rlEdit">Edit</button>
              <button type="button" class="danger rlRm">Remove</button>
            </div>`}
          </div>
        </details>`).join("")}</div>
      ${globalRules(d.global || [])}
      <div class="fnote">${rows.length
          ? (chars === null
             ? "unsaved: the size is measured on what is written"
             : `${standing} standing, ${rows.length - standing} conditional · `
               + `${chars} characters in front of every session here${
                 d.loud ? "; that is a lot to pay on every conversation" : ""}`)
          : "Nothing set. A session can leave rules of its own with bb rules "
            + "add, marked as its; the ones you write here it cannot touch."}</div>`;
    // The clash, where the rules are: their list as it stands now beside the
    // choice, in the two words the roadmap's band uses, so the same decision
    // reads the same way on both views.
    const theirs = nb.ruleClash?.rules || [];
    const clash = !nb.ruleClash ? "" : `<div class="field"><div class="hint bad">These rules changed while you had them open: a session or another person wrote to them. Theirs now holds ${
        theirs.length} rule${theirs.length === 1 ? "" : "s"}${theirs.length ? ": " + theirs.map(r => esc(r.name)).join(", ") : ""}.</div>
        <div class="actbar"><span class="state">nothing has been written</span>
          <button type="button" id="rlKeepTheirs">Keep theirs</button>
          <button type="button" class="primary" id="rlUseMine">Use mine</button></div></div>`;
    box.innerHTML = nb.codebaseSection()
      + docSection("briefing", "rules", "Your rules",
      rows.length ? `${rows.length}` : "none", clash + body,
      // Shut on both sizes: the rules are read once and edited rarely, and
      // open they push the code base off the first screen. The count on the
      // heading says there is something behind it.
      {open: !!nb.ruleClash, cls: d.loud && !ruleDirty() ? "warn" : ""})
      // Last, because it CONTAINS the two above: the rules in full, then the
      // open roadmap and bugs. Reading it before them is reading the summary
      // before the thing.
      + nb.preambleSection();
    const keep = box.querySelector("#rlKeepTheirs"), mine = box.querySelector("#rlUseMine");
    if (keep) keep.onclick = () => loadRules();          // their list, my edits dropped
    if (mine) mine.onclick = () => saveRules(true);
    wireSections(box);
    nb.ruleStagedCount = () => (ruleDirty() ? 1 : 0);
    nb.ruleClearStaged = () => { nb.rulePending = null; nb.ruleEditing.clear(); nb.ruleOpen.clear(); nb.ruleWas.clear(); drawRules(); };
    nb.ruleCommitStaged = saveRules;
    box.querySelectorAll(".rulerow").forEach(row => {
      const i = Number(row.dataset.i);
      const put = (k, sel) => {
        const el = row.querySelector(sel);
        if (el) el.oninput = () => ruleField(i, k, el.value);
      };
      put("name", ".rlName"); put("text", ".rlText");
      put("paths", ".rlPaths"); put("words", ".rlWords");
      put("doc", ".rlDoc"); put("check", ".rlCheck");
      // Removing a row shifts every index above it; the set is rebuilt from
      // the rows that stay so an open editor does not jump to its neighbour.
      row.querySelector(".rlRm").onclick = () => {
        const shift = s => new Set([...s].filter(j => j !== i).map(j => (j > i ? j - 1 : j)));
        nb.ruleEditing = shift(nb.ruleEditing); nb.ruleOpen = shift(nb.ruleOpen);
        nb.ruleWas = new Map([...nb.ruleWas].filter(([j]) => j !== i).map(([j, v]) => [j > i ? j - 1 : j, v]));
        ruleStage(rs => rs.splice(i, 1));
      };
      const ed = row.querySelector(".rlEdit");
      if (ed) ed.onclick = () => {
        const r = (nb.rulePending || nb.ruleData?.rules || [])[i];
        nb.ruleWas.set(i, {...r, paths: [...(r.paths || [])], words: [...(r.words || [])]});
        nb.ruleEditing.add(i); nb.ruleOpen.add(i); drawRules();
      };
      // Back to reading it, as it read before Edit. If that leaves the list
      // exactly as it is on disk there is nothing staged any more, and the
      // foot's Save goes quiet with it.
      const cn = row.querySelector(".rlCancel");
      if (cn) cn.onclick = () => {
        const was = nb.ruleWas.get(i); nb.ruleWas.delete(i);
        const rs = (nb.rulePending || (nb.ruleData?.rules || [])).map(r => ({...r}));
        if (was) rs[i] = was;
        else {
          rs.splice(i, 1);
          const shift = s => new Set([...s].filter(j => j !== i).map(j => (j > i ? j - 1 : j)));
          nb.ruleEditing = shift(nb.ruleEditing); nb.ruleOpen = shift(nb.ruleOpen);
        }
        nb.ruleEditing.delete(i);
        const seen = list => JSON.stringify(list.map(r => [r.name || "", r.text || "",
          (r.paths || []).join(","), (r.words || []).join(","), r.doc || "", r.check || ""]));
        nb.rulePending = seen(rs) === seen(nb.ruleData?.rules || []) ? null : rs;
        drawRules(); nb.syncSave();
      };
      // The same tween the bug reports open with, bound on the summary
      // rather than toggle, which fires after the browser has snapped it.
      const sum = row.querySelector("summary");
      if (sum) sum.onclick = e => {
        e.preventDefault();
        if (row.open) nb.ruleOpen.delete(i); else nb.ruleOpen.add(i);
        slideDetails(row, !row.open);
      };
    });
    const add = $("rlAdd");
    if (add) add.onclick = () => {
      nb.ruleEditing.add(rows.length);          // the new row, which is a form until it has words
      ruleStage(rs => rs.push({name: "", text: "", paths: [], words: []}));
    };
  }

  // Typed into rather than redrawn: a repaint on every keystroke would take
  // the caret with it. The staged copy is updated in place and the row's
  // "every session / on its triggers" word is the one thing that has to
  // follow, so it is the only thing touched.
  function ruleField(i, key, value){
    nb.rulePending = (nb.rulePending || (nb.ruleData?.rules || [])).map(r => ({...r}));
    const r = nb.rulePending[i];
    if (!r) return;
    if (key === "paths" || key === "words")
      r[key] = value.split(/[,\s]+/).filter(Boolean);
    else r[key] = value;
    const box = $("rulesBox")?.querySelector(`.rulerow[data-i="${i}"]`);
    if (box){
      const on = (r.paths || []).length || (r.words || []).length;
      const kind = box.querySelector(".rlkind");
      kind.textContent = on ? "on its triggers" : "every session";
      kind.classList.toggle("cond", !!on);
      box.querySelector(".actbar .state").innerHTML = ruleWhen(r);
    }
    nb.syncSave();
  }

  // `force` is the person's answer to the clash band, never a default.
  async function saveRules(force){
    if (!ruleDirty()) return;
    const body = nb.rulePending;
    try{
      const r = await postJSON("/api/rules", {project, action: "save", rules: body,
                                              rev: nb.ruleData?.rev, ...(force === true ? {force: true} : {})});
      const j = await r.json();
      // Somebody else wrote these rules while they were open here (B195).
      // Nothing is written and nothing typed is dropped: the staged copy
      // stays, and the band puts the choice where the rules are.
      if (j.conflict){ nb.ruleClash = j.current; drawRules(); return; }
      if (j.error){ notify(j.error, true); return; }
      nb.ruleClash = null;
      nb.ruleData = j;
      nb.rulePending = null;
      nb.ruleEditing.clear();                   // written: back to reading them
      nb.ruleOpen.clear(); nb.ruleWas.clear();
      drawRules();
    }catch(e){ notify("could not reach the server: " + e, true); }
  }

  return {loadRules, drawRules, saveRules, ruleDirty};
}
