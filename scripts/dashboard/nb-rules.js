// The notebook's house rules (roadmap #7): the operator's and a session's,
// read, edited, staged and saved with the rest of the notebook. One classic
// script beside index.html (docs/nodes.md §13): one file per notebook view
// (R60). A factory makeNotebook calls per notebook.

"use strict";

function nbRulesView({$, nb, project}){
  // One answer for the several askers of a first show (B218): the view
  // switch, the view shown again before the first answer landed, and the
  // poll's watch all asked while nothing was loaded yet, and a notebook's
  // first open fetched the rules and the code base three times over.
  function loadRules(again = false){
    if (nb.rulesInFlight && !again) return nb.rulesInFlight;
    nb.rulesInFlight = loadRulesNow(again).finally(() => { nb.rulesInFlight = null; });
    return nb.rulesInFlight;
  }
  async function loadRulesNow(again){
    nb.loadCodebase().then(() => drawRules());
    try{
      const r = await bootFetch("/api/rules?project=" + encodeURIComponent(project));
      nb.ruleData = await r.json();
    }catch(e){ nb.ruleData = {error: String(e), rules: []}; }
    // The answer's own revision, not the page's token as of now (B201); an
    // answer that failed carries none, and the token stands in.
    nb.rulesRev = nb.ruleData.rev ?? revs[`rules:${project}`] ?? nb.rulesRev;
    // A reload that lands on staged work keeps the work: the poll never
    // asks while the panel is dirty (HALVES), but a load already on its
    // way when Add or Edit was pressed used to land afterwards and drop the
    // row under the finger that made it (B255). What is on disk is read
    // fresh either way; Save's own conflict check is what judges the base.
    if (!ruleDirty()) nb.ruleClash = null;
    drawRules();
    // Already behind (see nb-tests.js): read once more now, unless somebody
    // is typing, which is the case the poll's own guard keeps.
    if (!again && nb.ruleData.rev !== undefined && revs[`rules:${project}`] !== undefined
        && revs[`rules:${project}`] !== nb.ruleData.rev && !ruleDirty()) return loadRulesNow(true);
  }

  // The global rules, under the project's own: every project's sessions
  // are handed them, and each can be switched off for THIS project by
  // anybody who works on it (the operator, 2 Oct), staged with the rest of
  // the Briefing behind the notebook's Save. An administrator also changes
  // the rules themselves here, for every project at once, written as each
  // row's own Save; there is no dialog for them anywhere else. A class of
  // their own, NOT .rulerow: every handler here means "one of this
  // project's rules" by that class.
  const offHere = () => nb.globalOffPending || new Set((nb.ruleData?.global || []).filter(g => g.off_here).map(g => g.name));
  function globalRules(gs){
    const may = !!nb.ruleData?.may_global;
    if (!gs.length && !may) return "";
    const off = offHere();
    const cond = r => (r.paths || []).length || (r.words || []).length;
    const ed = nb.globalEditing;
    const row = (g, i) => {
      const editing = ed && ed.i === i;
      const here = !off.has(g.name);
      return `
        <details class="bug grule${editing ? " editing" : ""}" data-gi="${i}"${editing ? " open" : sectAttr(`rules:global:${project}|${g.name || i}`)}>
          <summary><span class="btitle">${esc(g.name || "(new)")}</span>
            <span class="rlkind ${cond(g) ? "cond" : ""}">${cond(g) ? "on its triggers" : "every session"}</span>
            <span class="pill">global</span>${
            g.disabled ? `<span class="pill warn">off everywhere</span>` : !here ? `<span class="pill warn">off here</span>` : ""}</summary>
          <div class="body">${editing ? `
            ${lbl("", "Name", "a short name the rule is known by")}
            <input class="grName" maxlength="40" autocomplete="off" spellcheck="false" value="${esc(ed.r.name || "")}" aria-label="global rule name">
            ${lbl("", "The rule")}
            <textarea class="grText" spellcheck="false" maxlength="8000">${esc(ed.r.text || "")}</textarea>
            <div class="two">
              <div>${lbl("", "Files it covers")}<input class="grPaths" autocomplete="off" spellcheck="false" value="${esc((ed.r.paths || []).join(", "))}" aria-label="paths"></div>
              <div>${lbl("", "Words that raise it")}<input class="grWords" autocomplete="off" spellcheck="false" value="${esc((ed.r.words || []).join(", "))}" aria-label="words"></div>
            </div>
            <div class="actbar macts"><span class="state">Save writes it for every project</span>
              <button type="button" class="stop grCancel">Cancel</button>
              <button type="button" class="primary grSave">Save</button></div>` : `
            <div class="bfield"><label>rule</label><div class="bval">${esc(g.text || "")}</div></div>${
            (g.paths || []).length ? `<div class="bfield rltrig"><label>files</label><div class="bval">${esc(g.paths.join(", "))}</div></div>` : ""}${
            (g.words || []).length ? `<div class="bfield rltrig"><label>words</label><div class="bval">${esc(g.words.join(", "))}</div></div>` : ""}
            <div class="bfield"><label class="ndcap"><input type="checkbox" class="grHere"${here ? " checked" : ""}${g.disabled ? " disabled" : ""}> On for this project</label>${
              g.disabled ? `<div class="sub">An administrator has turned it off for every project.</div>` : ""}</div>
            <div class="actbar macts"><span class="state">${g.builtin ? "shipped with BuilderBot" : "an administrator's"}${here ? "" : " · Save applies the switch"}</span>${
              may ? (g.builtin
                ? `<button type="button" class="grEvery">${g.disabled ? "On everywhere" : "Off everywhere"}</button>`
                : `<button type="button" class="danger grRm">Remove</button><button type="button" class="grEdit">Edit</button>`) : ""}</div>`}
          </div>
        </details>`;
    };
    const adding = ed && ed.i === -1 ? row(ed.r, -1) : "";
    return `<div class="sub dim ggroup">Global rules: every project's sessions are handed these. Switch one off for this project here${
        may ? "; as an administrator you also change them for every project" : ""}.</div>${
      may && !(ed && ed.i === -1) ? `<div class="addbar" data-add="global"><button type="button" id="grAddHere">Add a global rule</button></div>` : ""}
      <div class="field" id="rlGlobal">${adding}${gs.map(row).join("")}</div>`;
  }

  // An administrator's change to the global rules, written at once for
  // every project: the operator's own list whole, and which shipped ones
  // are off everywhere, as /api/global-rules takes them.
  async function saveGlobal(mutate){
    const gs = (nb.ruleData?.global || []).map(g => ({...g}));
    const own = gs.filter(g => !g.builtin);
    const shippedOff = new Set(gs.filter(g => g.builtin && g.disabled).map(g => g.name));
    mutate(own, shippedOff);
    const r = await postJSON("/api/global-rules", {action: "save",
      rules: own.map(g => ({name: g.name, text: g.text, paths: g.paths || [], words: g.words || [],
                            doc: g.doc || "", check: g.check || "", refuse: g.refuse || [], why: g.why || ""})),
      disabled: [...shippedOff]});
    let j = {};
    try{ j = await r.json(); }catch{ j = {error: `the controller answered ${r.status}`}; }
    if (!r.ok || j.error){ notify(j.error || `the controller answered ${r.status}`, true); return false; }
    nb.globalEditing = null;
    await loadRules(true);
    return true;
  }

  // What a project rule shares with a global one, in a sentence for its row.
  const overlapLine = r => (r.overlaps || []).map(o =>
    `the global rule ${o.name} also fires on ${[...(o.words || []), ...(o.paths || [])].join(", ")}`).join("; ");

  // What is on screen: the staged copy if anything has been typed, otherwise
  // what the server last said.
  const ruleRows = () => nb.rulePending || (nb.ruleData?.rules || []);
  const ruleDirty = () => nb.rulePending !== null || nb.globalOffPending !== null;

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
      ? `Sent to a session only when its work touches these files or words.`
      : `Sent to every session. Add files or words to send it only when it applies.`;
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
      <div class="hint">How you want this project worked on. A session reads these at the start and cannot change yours.</div>
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
            ${lbl("", "Name", "a short name the rule is known by")}
            <input class="rlName" maxlength="40" autocomplete="off" spellcheck="false"
              placeholder="tests" value="${esc(r.name || "")}"
              aria-label="rule name">
            ${lbl("", "The rule")}
            <textarea class="rlText" spellcheck="false" maxlength="8000">${esc(r.text || "")}</textarea>
            ${lbl("", "Why", "the reason behind it, kept here and in bb rules show; a session is sent the rule alone")}
            <textarea class="rlWhy" spellcheck="false" maxlength="8000" rows="2">${esc(r.why || "")}</textarea>
            <div class="two">
              <div>${lbl("", "Files it covers", "paths or globs, comma-separated; the rule arrives when a session edits one")}
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
            <div class="two">
              <div>${lbl("", "Commands it refuses", "comma-separated, each the start of a command as typed; a session's Bash call that runs one is refused with this rule as the reason")}
              <input class="rlRefuse" autocomplete="off" spellcheck="false"
                placeholder="./gradlew assemble, npm publish"
                value="${esc((r.refuse || []).join(", "))}" aria-label="commands it refuses"></div>
              <div>${lbl("", "In place of", "a global rule this one replaces here; a session in this project reads only this one")}
              <select class="rlRepl" aria-label="the global rule it replaces">
                <option value="">no global rule</option>${(d.global || []).map(g =>
                  `<option value="${esc(g.name)}"${g.name === r.replaces ? " selected" : ""}>${esc(g.name)}</option>`).join("")}
              </select></div>
            </div>
            <div class="actbar macts">
              <span class="state">${ruleWhen(r)} · the section's Save writes it</span>
              <button type="button" class="stop rlCancel" title="discard what was typed">Cancel</button>
              <button type="button" class="danger rlRm">Remove</button>
            </div>` : `
            <div class="bfield"><label>rule</label><div class="bval rlBody">${esc(r.text || "")}</div></div>
            ${r.why ? `<div class="bfield"><label>why</label><div class="bval">${esc(r.why)}</div></div>` : ""}
            ${(r.paths || []).length ? `<div class="bfield rltrig"><label>files</label><div class="bval">${esc((r.paths || []).join(", "))}</div></div>` : ""}
            ${(r.words || []).length ? `<div class="bfield rltrig"><label>words</label><div class="bval">${esc((r.words || []).join(", "))}</div></div>` : ""}
            ${(r.overlaps || []).length ? `<div class="bfield rlover"><label>shares ground</label><div class="bval">${esc(overlapLine(r))}. Both reach a session; where they disagree it follows this one and says so.</div></div>` : ""}
            ${r.doc ? `<div class="bfield rlframe"><label>defined in</label><div class="bval">${esc(r.doc)}</div></div>` : ""}
            ${r.check ? `<div class="bfield rlframe"><label>checked by</label><div class="bval">${esc(r.check)} <span class="dim">· bb rules check ${esc(r.name || "")}</span></div></div>` : ""}
            ${(r.refuse || []).length ? `<div class="bfield rlframe"><label>refuses</label><div class="bval">${esc(r.refuse.join(", "))} <span class="dim">· a session's command that starts with one is refused</span></div></div>` : ""}
            ${r.replaces ? `<div class="bfield rlframe"><label>in place of</label><div class="bval">the global rule ${esc(r.replaces)}, which sessions here no longer read</div></div>` : ""}
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
             ? "unsaved: the size updates after Save"
             : `${standing} for every session, ${rows.length - standing} on triggers · `
               + `${chars} characters sent to every session here${
                 d.loud ? "; that is a lot" : ""}`)
          : "No rules yet. A session can add its own, marked as its; "
            + "it cannot change yours."}</div>`;
    // The clash, where the rules are: their list as it stands now beside the
    // choice, in the two words the roadmap's band uses, so the same decision
    // reads the same way on both views.
    const theirs = nb.ruleClash?.rules || [];
    const clash = !nb.ruleClash ? "" : `<div class="field"><div class="hint bad">These rules changed while you had them open. Theirs now holds ${
        theirs.length} rule${theirs.length === 1 ? "" : "s"}${theirs.length ? ": " + theirs.map(r => esc(r.name)).join(", ") : ""}.</div>
        <div class="actbar"><span class="state">nothing has been written</span>
          <button type="button" id="rlKeepTheirs">Keep theirs</button>
          <button type="button" class="primary" id="rlUseMine">Use mine</button></div></div>`;
    // The rules' own Save and Revert, at the section's foot (the operator,
    // 5 Oct): registered before the bar is drawn, which asks it.
    nb.stage("briefing:rules", {
      count: () => (ruleDirty() ? 1 : 0),
      what: () => "the edited rules",
      save: async () => { await saveRules(); return ""; },
      revert: () => nb.ruleClearStaged()});
    box.innerHTML = nb.codebaseSection()
      + nb.briefSection()
      + docSection("briefing", "rules", "Your rules",
      rows.length ? `${rows.length}` : "none", clash + body + nb.sectBar("briefing:rules"),
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
    nb.ruleClearStaged = () => { nb.rulePending = null; nb.globalOffPending = null; nb.globalEditing = null;
                                 nb.ruleEditing.clear(); nb.ruleOpen.clear(); nb.ruleWas.clear(); drawRules(); };
    nb.ruleCommitStaged = saveRules;
    box.querySelectorAll(".rulerow").forEach(row => {
      const i = Number(row.dataset.i);
      const put = (k, sel) => {
        const el = row.querySelector(sel);
        if (el) el.oninput = () => ruleField(i, k, el.value);
      };
      put("name", ".rlName"); put("text", ".rlText"); put("why", ".rlWhy");
      put("paths", ".rlPaths"); put("words", ".rlWords");
      put("doc", ".rlDoc"); put("check", ".rlCheck");
      put("refuse", ".rlRefuse");
      const repl = row.querySelector(".rlRepl");
      if (repl) repl.onchange = () => ruleField(i, "replaces", repl.value);
      // Removing a row shifts every index above it; the set is rebuilt from
      // the rows that stay so an open editor does not jump to its neighbor.
      row.querySelector(".rlRm").onclick = () => {
        const shift = s => new Set([...s].filter(j => j !== i).map(j => (j > i ? j - 1 : j)));
        nb.ruleEditing = shift(nb.ruleEditing); nb.ruleOpen = shift(nb.ruleOpen);
        nb.ruleWas = new Map([...nb.ruleWas].filter(([j]) => j !== i).map(([j, v]) => [j > i ? j - 1 : j, v]));
        ruleStage(rs => rs.splice(i, 1));
      };
      const ed = row.querySelector(".rlEdit");
      if (ed) ed.onclick = () => {
        const r = (nb.rulePending || nb.ruleData?.rules || [])[i];
        nb.ruleWas.set(i, {...r, paths: [...(r.paths || [])], words: [...(r.words || [])], refuse: [...(r.refuse || [])]});
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
          (r.paths || []).join(","), (r.words || []).join(","), r.doc || "", r.check || "",
          (r.refuse || []).join(","), r.replaces || "", r.why || ""]));
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
    wireGlobal(box);
  }

  function wireGlobal(box){
    const gs = nb.ruleData?.global || [];
    box.querySelectorAll(".grule").forEach(el => {
      const i = Number(el.dataset.gi);
      const g = i >= 0 ? gs[i] : nb.globalEditing?.r;
      if (!g) return;
      const on = (sel, fn) => { const b = el.querySelector(sel); if (b) b.onclick = fn; };
      const here = el.querySelector(".grHere");
      // Staged like the project's rules: the foot's Save sends it with them.
      if (here) here.onchange = () => {
        const off = new Set(offHere());
        if (here.checked) off.delete(g.name); else off.add(g.name);
        const was = new Set(gs.filter(x => x.off_here).map(x => x.name));
        const same = off.size === was.size && [...off].every(n => was.has(n));
        nb.globalOffPending = same ? null : off;
        drawRules(); nb.syncSave();
      };
      on(".grEvery", async ev => {
        busy(ev.target, "Saving");
        await saveGlobal((own, shippedOff) => { if (g.disabled) shippedOff.delete(g.name); else shippedOff.add(g.name); });
      });
      on(".grEdit", () => { nb.globalEditing = {i, r: {...g, paths: [...(g.paths || [])], words: [...(g.words || [])]}}; drawRules(); });
      on(".grCancel", () => { nb.globalEditing = null; drawRules(); });
      on(".grRm", async ev => {
        if (!confirm(`Remove the global rule ${g.name}? Every project's sessions stop being handed it.`)) return;
        busy(ev.target, "Removing");
        await saveGlobal(own => { const k = own.findIndex(x => x.name === g.name); if (k >= 0) own.splice(k, 1); });
      });
      const put = (cls, key, list) => {
        const f = el.querySelector(cls);
        if (f) f.oninput = () => { nb.globalEditing.r[key] = list ? f.value.split(/[,\s]+/).filter(Boolean) : f.value; };
      };
      put(".grName", "name"); put(".grText", "text"); put(".grPaths", "paths", true); put(".grWords", "words", true);
      on(".grSave", async ev => {
        const r = nb.globalEditing.r;
        if (!(r.text || "").trim()){ notify("a rule needs its words", true); return; }
        busy(ev.target, "Saving");
        await saveGlobal(own => {
          if (i === -1) own.push(r);
          else { const k = own.findIndex(x => x.name === g.name); if (k >= 0) own[k] = r; }
        });
      });
    });
    const addG = $("grAddHere");
    if (addG) addG.onclick = () => { nb.globalEditing = {i: -1, r: {name: "", text: "", paths: [], words: []}}; drawRules(); };
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
    else if (key === "refuse")
      r[key] = value.split(",").map(x => x.trim()).filter(Boolean);
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
    const body = nb.rulePending || (nb.ruleData?.rules || []);
    try{
      const r = await postJSON("/api/rules", {project, action: "save", rules: body,
                                              ...(nb.globalOffPending ? {globals_off: [...nb.globalOffPending]} : {}),
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
      nb.globalOffPending = null;
      nb.ruleEditing.clear();                   // written: back to reading them
      nb.ruleOpen.clear(); nb.ruleWas.clear();
      drawRules();
    }catch(e){ notify("could not reach the server: " + e, true); }
  }

  return {loadRules, drawRules, saveRules, ruleDirty};
}
