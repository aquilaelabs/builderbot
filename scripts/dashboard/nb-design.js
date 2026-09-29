// The notebook's Design view: what the project looks like, kept. One design
// language (colours as tokens, type, shape, space, motion and the operator's
// own rules) and pages laid out as labelled blocks on a phone or desktop
// frame, each named for what it is for and the platform it is built for.
// Three folds: the pages, the language and the themes; the pages and the
// themes show one at a time, chosen on a pulldown, and each entry, the
// language included, carries its rules as a section inside it, every rules
// list the Briefing's.
// Every edit is staged and the notebook's Save writes the whole record at
// once, the way the roadmap saves. Nothing here is a prompt: a session reads
// the design piece by piece with bb design show (design.py), which is what
// docs/design-language.md is written from too. One classic script beside
// index.html (docs/design-language.md, Files): a factory makeNotebook calls
// per notebook.

"use strict";

function nbDesignView({$, nb, project, root}){
  // The server's last answer, the working copies, and whether they differ.
  nb.dsData = null;
  nb.dsLang = null;
  nb.dsPages = null;
  nb.dsDirty = false;
  // Which block is selected on each page's board, by the page's key: a saved
  // page is keyed by its id, an unsaved one by a number of this panel's own,
  // so two pages added before a Save do not share a board.
  nb.dsSel = {};
  // Which theme, rule and page each section shows: one at a time, chosen
  // on the section's pulldown (the operator, 28 Sep: listing every page
  // and every theme at once was the whole view scrolled past). A theme and
  // a rule by index, a page by its key; what is added is shown.
  nb.dsShow = {theme: 0, page: null};
  // The rules lists' reading state, per list (the language's, a theme's,
  // a page's): which rows are open, which are being edited, and what an
  // edited row said before Edit, for Cancel. The Briefing's shape.
  nb.dsRuleUI = {};
  const ruleUI = key => nb.dsRuleUI[key] || (nb.dsRuleUI[key] = {editing: new Set(), open: new Set(), was: new Map()});
  let tmpN = 0;
  const keyOf = p => p.id > 0 ? `p${p.id}` : `t${p.tmp}`;
  const presets = () => nb.dsData?.presets || {};
  const byKey = (rows, k) => (rows || []).find(r => r.key === k);
  const platformOf = p => byKey(presets().platforms, p.platform) || (presets().platforms || [])[0];
  const clone = o => JSON.parse(JSON.stringify(o));
  // The slug a holder's rule is named under, as design.py's _slug makes it.
  const holderSlug = name => (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "colour";

  async function loadDesign(){
    try{
      const j = await (await fetch(`/api/design?project=${encodeURIComponent(project)}`)).json();
      if (j.error){ $("dsHint").textContent = "design: " + j.error; return; }
      nb.dsData = j;
    }catch(e){ $("dsHint").textContent = "design: " + e; return; }
    // A re-read never takes what is being edited: the working copies stay
    // until Save or Revert, and only the file's state and the vocabulary
    // come in fresh.
    if (!nb.dsDirty || !nb.dsLang){
      nb.dsLang = clone(nb.dsData.language);
      nb.dsPages = clone(nb.dsData.pages);
      nb.dsDirty = false;
    }
    drawAdd();
    drawDesign();
  }

  // ---- the head row and the add bar -------------------------------------------
  function drawHint(){
    const f = nb.dsData?.file || {};
    const n = (nb.dsPages || []).length;
    const pages = n ? `${n} page${n === 1 ? "" : "s"}` : "no pages yet";
    const file = nb.dsDirty ? "unsaved changes: Save at the foot"
      : !f.exists ? `${f.path || "docs/design-language.md"} not written yet`
      : f.current ? `${f.path} is written and current`
      : `${f.path} is behind what is saved: Write the file`;
    $("dsHint").textContent = `${pages} · ${file}`;
    const w = $("dsWrite");
    w.disabled = !!nb.dsDirty;
    w.title = nb.dsDirty ? "Save first: the file is written from what is saved"
      : "write docs/design-language.md into the project from what is saved here; a session commits it with the work";
  }

  function drawAdd(){
    const P = presets();
    const plat = $("dsPlatform"), tpl = $("dsTemplate");
    const was = plat.value;
    plat.innerHTML = (P.platforms || []).map(p => `<option value="${esc(p.key)}">${esc(p.label)}</option>`).join("");
    if (was && byKey(P.platforms, was)) plat.value = was;
    fillTemplates();
  }
  // The templates a platform's frames allow: a phone app is not offered a
  // desktop layout.
  function fillTemplates(){
    const P = presets();
    const frames = byKey(P.platforms, $("dsPlatform").value)?.frames || [];
    const tpl = $("dsTemplate"), was = tpl.value;
    const rows = (P.templates || []).filter(t => frames.includes(t.frame));
    tpl.innerHTML = rows.map(t => `<option value="${esc(t.key)}">${esc(t.label)}</option>`).join("");
    if (was && rows.some(t => t.key === was)) tpl.value = was;
  }
  $("dsPlatform").onchange = fillTemplates;
  $("dsAdd").onclick = () => {
    const t = byKey(presets().templates, $("dsTemplate").value);
    if (!t) return;
    const p = {id: 0, tmp: ++tmpN, name: "", platform: $("dsPlatform").value, template: t.key,
               frame: t.frame, blocks: clone(t.blocks), notes: ""};
    nb.dsPages.push(p);
    nb.dsShow.page = keyOf(p);
    touched();
    drawDesign();
    root.querySelector(`[data-dspage="${keyOf(p)}"] [data-dsf="name"]`)?.focus();
  };
  $("dsWrite").onclick = async () => {
    const b = $("dsWrite");
    busy(b, "Writing");
    try{
      const j = await (await postJSON("/api/design", {project, action: "write"})).json();
      if (j.error) notify(j.error, true);
      else{
        if (nb.dsData) nb.dsData.file = j.file;
        notify(`${j.path} written into ${project}: the Git view shows it until a session commits it`);
      }
    }catch(e){ notify("design: " + e, true); }
    unbusy(b, "Write the file");
    drawHint();
  };

  // Something changed: the foot's Save wakes, and the prompts follow.
  function touched(){
    nb.dsDirty = true;
    nb.syncSave();
    drawHint();
  }

  // ---- drawing --------------------------------------------------------------------
  const opt = (rows, cur, keyed = "key", labeled = "label") => (rows || [])
    .map(r => `<option value="${esc(r[keyed])}"${r[keyed] === cur ? " selected" : ""}>${esc(r[labeled])}</option>`).join("");
  const ctl = (id, text, help, control, grow) =>
    `<div class="dsctl${grow ? " grow" : ""}">${lbl(id, text, help)}${control}</div>`;

  // What each section shows, kept in range: a removed page or theme
  // leaves the pulldown on the first one.
  function shown(){
    const L = nb.dsLang, S = nb.dsShow;
    S.theme = Math.min(Math.max(0, S.theme), Math.max(0, (L.themes || []).length - 1));
    if (!nb.dsPages.some(p => keyOf(p) === S.page)) S.page = nb.dsPages.length ? keyOf(nb.dsPages[0]) : null;
    return {theme: (L.themes || [])[S.theme], page: nb.dsPages.find(p => keyOf(p) === S.page)};
  }

  function drawDesign(){
    const body = $("dsBody");
    if (!nb.dsData){ body.innerHTML = `<div class="loading">loading…</div>`; return; }
    const sh = shown();
    nb.dsRuleLists = {};
    body.innerHTML = pagesSection(sh.page) + languageSection() + themesSection(sh.theme);
    wireSections(body);
    wireLanguage(body);
    wireThemes(body, sh.theme);
    if (sh.page) wirePage(body.querySelector(`[data-dspage="${keyOf(sh.page)}"]`), sh.page);
    body.querySelectorAll("[data-dsrules]").forEach(wireRulesList);
    // A locked project reads its notebook: every control here is dead but
    // Copy, which takes nothing anywhere, and the pulldowns, which show.
    if (root.classList.contains("ro"))
      body.querySelectorAll("input,select:not([data-dspick]),textarea,button").forEach(e => e.disabled = true);
    drawHint();
  }

  // A section's pulldown: which of its things is shown below it.
  const pick = (id, text, rows, cur, help = "") =>
    ctl(id, text, help, `<select id="${id}" data-dspick>${opt(rows, cur)}</select>`);

  function languageSection(){
    const L = nb.dsLang, P = presets(), C = P.choices || {};
    const status = [byKey(C.font, L.font)?.label, byKey(C.corners, L.corners)?.label].filter(Boolean).join(" · ");
    const body = `
      <div class="field"><div class="dsrow">
        ${ctl("dsFont", "Type", "", `<select id="dsFont">${opt(C.font, L.font)}</select>`)}
        ${ctl("dsCorners", "Corners", "", `<select id="dsCorners">${opt(C.corners, L.corners)}</select>`)}
        ${ctl("dsDensity", "Space", "", `<select id="dsDensity">${opt(C.density, L.density)}</select>`)}
        ${ctl("dsMotion", "Motion", "", `<select id="dsMotion">${opt(C.motion, L.motion)}</select>`)}
      </div></div>
      <div class="field">${ctl("dsFonts", "Families",
            "the exact font stacks when the choice above is not enough: Inter for text, JetBrains Mono for code",
            `<textarea id="dsFonts" class="proseline" rows="1" maxlength="200">${esc(L.fonts || "")}</textarea>`, true)}</div>
      <div class="field">${ctl("dsScope", "Governs",
            "what the language covers when the project is more than one product: the web app in site/",
            `<textarea id="dsScope" class="proseline" rows="1" maxlength="120">${esc(L.scope)}</textarea>`, true)}</div>
      ${rulesFold()}`;
    return docSection("design", "language", "Design language", status, body);
  }

  // The themes: a pulldown of them, the add bar, and the chosen one's
  // colours. The first theme is the one the app starts on.
  function themesSection(t){
    const L = nb.dsLang, P = presets();
    const themes = L.themes || [];
    const rows = themes.map((x, i) => ({key: String(i), label: `${x.name || "unnamed theme"} (${x.mode})${i === 0 ? ", the default" : ""}`}));
    const body = `
      <div class="field"><div class="dsrow">
        ${pick("dsThemePick", "Theme", rows, String(nb.dsShow.theme), "each a named set of colours, dark or light; the first is the one the app starts on, and a theme picker, where the app has one, offers them by name")}
        ${ctl("dsThemeFrom", "Add one from", "", `<select id="dsThemeFrom">${opt(P.schemes, "default")}</select>`)}
        <button type="button" id="dsThemeAdd" ${themes.length >= (P.themes_max || 8) ? "disabled" : ""}>Add theme</button>
      </div></div>
      ${t ? themeBand(t, nb.dsShow.theme, themes.length) : `<div class="field"><div class="hint">No theme yet. Add one from a preset, or leave it: a session that builds the project chooses the colours and puts them here.</div></div>`}`;
    return docSection("design", "themes", "Themes", `${themes.length} theme${themes.length === 1 ? "" : "s"}`, body);
  }

  // The design's rules, the Briefing's shape (nb-rules.js, drawRules): Add a
  // rule first, then a row a rule, folded, its name and whether it stands
  // in every briefing or arrives on its triggers, opening to be read, and
  // Edit turning the row into its form. The same list serves the language's
  // rules, a theme's own and a page's own (the operator, 29 Sep): a rules
  // section inside the page and the theme, following the pulldown.
  // The language's own rules, a section inside the Design language fold;
  // a theme's and a page's are the same section inside each entry (the
  // operator, 29 Sep: a rules fold below everything read as the rules).
  function rulesFold(){
    const L = nb.dsLang, rules = L.rules || (L.rules = []);
    return docSection("design", "rules", "Rules", rules.length ? `${rules.length}` : "none",
      `<div class="hint">What holds for the whole design and the settings cannot say: a session gets one on the turn it edits a file or is asked about a word the rule names; one with no trigger stands in every briefing whole.</div>`
      + rulesList("lang", rules), {open: true});
  }
  const cond = r => (r.paths || []).length || (r.words || []).length;
  const ruleWhen = r => cond(r) ? "named in the briefing; its text arrives when it applies" : "standing: in every briefing whole";
  function rulesList(key, rules){
    nb.dsRuleLists[key] = rules;
    const ui = ruleUI(key);
    return `<div class="addbar" data-add="rule"><button type="button" data-dsruleadd ${rules.length >= (presets().rules_max || 60) ? "disabled" : ""}>Add a rule</button></div>
      <div class="field" data-dsrules="${key}">${rules.map((r, i) => `
        <details class="bug rulerow${ui.editing.has(i) ? " editing" : ""}" data-i="${i}"${ui.editing.has(i) || ui.open.has(i) ? " open" : ""}>
          <summary>
            <span class="btitle rlNameRO">${esc(r.name || "(unnamed)")}</span>
            <span class="rlkind ${cond(r) ? "cond" : ""}">${cond(r) ? "on its triggers" : "every session"}</span>
          </summary>
          <div class="body">${ui.editing.has(i) ? `
            ${lbl("", "Name", "a short name the rule is known by: dialogs, tap-targets")}
            <input class="rlName" maxlength="40" autocomplete="off" spellcheck="false" placeholder="dialogs" value="${esc(r.name || "")}" aria-label="rule name">
            ${lbl("", "The rule")}
            <textarea class="rlText" spellcheck="false" maxlength="20000">${esc(r.text || "")}</textarea>
            <div class="two">
              <div>${lbl("", "Files it covers", "paths or globs, comma-separated; the rule arrives when a session edits one")}
              <input class="rlPaths" autocomplete="off" spellcheck="false" placeholder="src/ui, *.css" value="${esc((r.paths || []).join(", "))}" aria-label="paths"></div>
              <div>${lbl("", "Words that raise it", "comma-separated; the rule arrives when a session is asked about one")}
              <input class="rlWords" autocomplete="off" spellcheck="false" placeholder="dialog, modal" value="${esc((r.words || []).join(", "))}" aria-label="words"></div>
            </div>
            <div class="actbar macts">
              <span class="state">${ruleWhen(r)} · Save at the foot writes it</span>
              <button type="button" class="stop rlCancel" title="discard what was typed">Cancel</button>
              <button type="button" class="danger rlRm">Remove</button>
            </div>` : `
            <div class="bfield"><label>rule</label><div class="bval rlBody">${esc(r.text || "")}</div></div>
            ${(r.paths || []).length ? `<div class="bfield rltrig"><label>files</label><div class="bval">${esc((r.paths || []).join(", "))}</div></div>` : ""}
            ${(r.words || []).length ? `<div class="bfield rltrig"><label>words</label><div class="bval">${esc((r.words || []).join(", "))}</div></div>` : ""}
            <div class="actbar macts">
              <span class="state">${ruleWhen(r)}</span>
              <button type="button" class="rlEdit">Edit</button>
              <button type="button" class="danger rlRm">Remove</button>
            </div>`}
          </div>
        </details>`).join("")}${rules.length ? "" : `<div class="fnote">No rules here yet.</div>`}</div>`;
  }
  // Typed into rather than redrawn, as the Briefing's are: the model changes
  // under the caret and only the row's word follows; Add, Edit, Cancel and
  // Remove redraw.
  function wireRulesList(host){
    const key = host.dataset.dsrules, rules = nb.dsRuleLists[key], ui = ruleUI(key);
    if (!rules) return;
    const split = v => v.split(/[,\s]+/).map(x => x.trim()).filter(Boolean);
    const add = host.previousElementSibling?.querySelector("[data-dsruleadd]");
    if (add) add.onclick = () => {
      ui.editing.add(rules.length);
      rules.push({name: "", text: "", words: [], paths: []});
      touched(); drawDesign();
      root.querySelector(`[data-dsrules="${key}"] .rulerow[data-i="${rules.length - 1}"] .rlName`)?.focus();
    };
    host.querySelectorAll(".rulerow").forEach(row => {
      const i = +row.dataset.i, r = rules[i];
      if (!r) return;
      const typed = () => {
        const kind = row.querySelector(".rlkind");
        kind.textContent = cond(r) ? "on its triggers" : "every session";
        kind.classList.toggle("cond", !!cond(r));
        row.querySelector(".actbar .state").textContent = `${ruleWhen(r)} · Save at the foot writes it`;
        touched();
      };
      const put = (sel, fn) => { const el = row.querySelector(sel); if (el) el.oninput = () => { fn(el.value); typed(); }; };
      put(".rlName", v => { r.name = v; row.querySelector(".rlNameRO").textContent = v.trim() || "(unnamed)"; });
      put(".rlText", v => { r.text = v; });
      put(".rlPaths", v => { r.paths = split(v); });
      put(".rlWords", v => { r.words = split(v); });
      const shift = set => new Set([...set].filter(j => j !== i).map(j => (j > i ? j - 1 : j)));
      row.querySelector(".rlRm").onclick = () => {
        rules.splice(i, 1);
        ui.editing = shift(ui.editing); ui.open = shift(ui.open);
        ui.was = new Map([...ui.was].filter(([j]) => j !== i).map(([j, v]) => [j > i ? j - 1 : j, v]));
        touched(); drawDesign();
      };
      const ed = row.querySelector(".rlEdit");
      if (ed) ed.onclick = () => {
        ui.was.set(i, {...r, paths: [...(r.paths || [])], words: [...(r.words || [])]});
        ui.editing.add(i); ui.open.add(i); drawDesign();
      };
      // Back to reading it as it read before Edit; a row that never had
      // words leaves.
      const cn = row.querySelector(".rlCancel");
      if (cn) cn.onclick = () => {
        const was = ui.was.get(i); ui.was.delete(i);
        if (was) Object.assign(r, was);
        else { rules.splice(i, 1); ui.editing = shift(ui.editing); ui.open = shift(ui.open); }
        ui.editing.delete(i);
        touched(); drawDesign();
      };
      const sum = row.querySelector("summary");
      if (sum) sum.onclick = e => {
        e.preventDefault();
        if (row.open) ui.open.delete(i); else ui.open.add(i);
        slideDetails(row, !row.open);
      };
    });
  }

  // One theme: its name and mode, its colours as rows (a name, a hex and
  // what it is for), and what can be done to it. Make default moves
  // another theme up to first.
  function themeBand(t, i, n){
    const P = presets();
    const modes = (P.modes || ["dark", "light"]).map(m => ({key: m, label: m[0].toUpperCase() + m.slice(1)}));
    return `<div class="dstheme" data-dstheme="${i}">
      <div class="field"><div class="dsrow">
        ${ctl(`dst-name-${i}`, "Name", "", `<textarea id="dst-name-${i}" class="proseline" rows="1" maxlength="40" data-dst="name">${esc(t.name)}</textarea>`, true)}
        ${ctl(`dst-mode-${i}`, "Mode", "", `<select id="dst-mode-${i}" data-dst="mode">${opt(modes, t.mode)}</select>`)}
        ${ctl(`dst-from-${i}`, "Fill from", "replace this theme's colours with a preset's ten",
              `<select id="dst-from-${i}" data-dst="from"><option value="">keep as they are</option>${opt(P.schemes, "")}</select>`)}
      </div></div>
      ${docSection("design", `rules:t${i}`, "Rules", (t.rules || []).length ? `${t.rules.length}` : "none",
        `<div class="hint">What holds for ${esc(t.name.trim() || "this theme")} alone. A session meets one as ${esc(holderSlug(t.name))}/NAME.</div>` + rulesList(`t${i}`, t.rules || (t.rules = [])), {open: true})}
      <div class="field">${lbl("", "Colours", "each a name, a hex and what it is for; a session names them the same in the code")}
      <div class="dscolours">${(t.colors || []).map((c, j) => `
        <div class="dsrow" data-dstc="${j}">
          ${ctl(`dst-${i}-name-${j}`, "Name", "", `<input id="dst-${i}-name-${j}" data-dsm="name" maxlength="40" autocomplete="off" value="${esc(c.name)}">`)}
          ${ctl(`dst-${i}-hex-${j}`, "Hex", "", `<div class="dsc"><span class="dschip" style="background:${esc(c.hex)}"></span><input id="dst-${i}-hex-${j}" data-dsm="hex" maxlength="7" spellcheck="false" autocomplete="off" value="${esc(c.hex)}"></div>`)}
          ${ctl(`dst-${i}-for-${j}`, "For", "", `<textarea id="dst-${i}-for-${j}" class="proseline" rows="1" maxlength="120" data-dsm="means">${esc(c.means)}</textarea>`, true)}
          <button type="button" class="danger" data-dstcrm="${j}" title="take this colour out">Remove</button>
        </div>`).join("")}</div></div>
      <div class="field"><div class="actbar"><span class="state">${i === 0 ? "the default: the app starts on it" : ""}</span>
        <button type="button" data-dstcadd ${(t.colors || []).length >= (P.colors_max || 40) ? "disabled" : ""}>Add colour</button>
        ${i === 0 ? "" : `<button type="button" data-dstdefault title="the app starts on this theme">Make default</button>`}
        <button type="button" class="danger" data-dstrm title="take this theme out">Remove theme</button></div></div>
    </div>`;
  }

  // The pages: a pulldown of them and the chosen one's board and fields.
  // Adding one is the head row's (a platform, a template, Add page).
  function pagesSection(p){
    const n = nb.dsPages.length;
    const rows = nb.dsPages.map(x => ({key: keyOf(x), label: `${x.name.trim() || "unnamed page"} (${platformOf(x)?.label || x.platform}, ${x.blocks.length} block${x.blocks.length === 1 ? "" : "s"})`}));
    const body = n ? `
      <div class="field"><div class="dsrow">
        ${pick("dsPagePick", "Page", rows, nb.dsShow.page || "", "each laid out as blocks on a frame and named for what it is for")}
      </div></div>
      ${p ? pageBody(p) : ""}`
      : `<div class="field"><div class="hint">No pages yet: pick a platform and a template above and press Add page.</div></div>`;
    return docSection("design", "pages", "Pages", n ? `${n} page${n === 1 ? "" : "s"}` : "none yet", body);
  }

  function pageBody(p){
    const P = presets(), key = keyOf(p);
    const plat = platformOf(p);
    const frames = (plat?.frames || Object.keys(P.frames || {})).map(f => ({key: f, label: P.frames?.[f]?.label || f}));
    const n = p.blocks.length;
    const sel = nb.dsSel[key];
    const b = sel != null ? p.blocks[sel] : null;
    return `<div data-dspage="${key}">
      <div class="field"><div class="dsrow">
        ${ctl(`${key}-name`, "For", "what this page is for: the settings page. Applying it means applying the design there",
              `<textarea id="${key}-name" class="proseline" rows="1" maxlength="120" data-dsf="name">${esc(p.name)}</textarea>`, true)}
        ${ctl(`${key}-plat`, "Platform", "", `<select id="${key}-plat" data-dsf="platform">${opt(P.platforms, p.platform)}</select>`)}
        ${ctl(`${key}-frame`, "Frame", "", `<select id="${key}-frame" data-dsf="frame">${opt(frames, p.frame)}</select>`)}
      </div></div>
      <div class="field">${boardHtml(p)}</div>
      <div class="field"><div class="dsrow">
        ${ctl(`${key}-kind`, "Block", "", `<select id="${key}-kind" data-dsf="newkind">${opt(P.kinds, "content")}</select>`)}
        <button type="button" data-dsblockadd title="put a block of this kind on the board">Add block</button>
      </div></div>
      ${b ? `<div class="field" data-dsselected><div class="dsrow">
        ${ctl(`${key}-bkind`, "Kind", "", `<select id="${key}-bkind" data-dsb="kind">${opt(P.kinds, b.kind)}</select>`)}
        ${ctl(`${key}-blabel`, "What it's for", "one line a session reads: the account menu, the list of orders",
              `<textarea id="${key}-blabel" class="proseline" rows="1" maxlength="120" data-dsb="label">${esc(b.label)}</textarea>`, true)}
        <button type="button" class="danger" data-dsblockrm>Remove block</button>
      </div>
      <div class="hint">Drag a block to move it and its corner to size it; the arrow keys move a focused one, with Shift to size.</div></div>`
      : `<div class="field"><div class="hint">${n ? "Tap a block to name what it is for." : "Add a block, or start again from a template with Add page."}</div></div>`}
      ${docSection("design", `rules:${key}`, "Rules", (p.rules || []).length ? `${p.rules.length}` : "none",
        `<div class="hint">What holds for ${esc(p.name.trim() || "this page")} alone. A session meets one as ${esc(holderSlug(p.name || `page-${p.id}`))}/NAME.</div>` + rulesList(key, p.rules || (p.rules = [])), {open: true})}
      <div class="field">${ctl(`${key}-notes`, "Notes", "what the blocks cannot say: what a tap does, where the data comes from",
            `<textarea id="${key}-notes" rows="3" maxlength="65536" data-dsf="notes">${esc(p.notes)}</textarea>`, true)}</div>
      <div class="field"><div class="actbar"><span class="state"></span>
          <button type="button" class="danger" data-dspagerm title="take this page out; Save makes it final, Revert brings it back">Remove page</button></div></div>
    </div>`;
  }

  // ---- the board --------------------------------------------------------------------
  // What a block wears comes from the language: a bar is a surface, an action
  // is the accent, the reading area is the page itself.
  const WEAR = {header: "panel", nav: "panel", tabs: "panel", sidebar: "panel", footer: "panel",
                button: "accent", hero: "accent"};
  // The default theme's colours by role, whatever the design calls them
  // (presets.roles), falling back to the dashboard's own scheme: the board
  // is painted in the language, and a theme with a "page" and a "surface"
  // is still a page and a surface.
  const FALLBACK = {bg: "#1a1f26", panel: "#212730", ink: "#e6edf3", line: "#4d5c6f", accent: "#3fb950"};
  function paint(role){
    const t = (nb.dsLang.themes || [])[0];
    const names = presets().roles?.[role] || [role];
    const hit = (t?.colors || []).find(c => names.includes(c.name.toLowerCase()));
    return hit ? hit.hex : FALLBACK[role];
  }
  function blockStyle(b){
    const wear = WEAR[b.kind] || (["content", "text"].includes(b.kind) ? "bg" : "panel");
    const bg = paint(wear);
    const ink = wear === "accent" ? paint("bg") : paint("ink");
    return `grid-column:${b.x + 1} / span ${b.w};grid-row:${b.y + 1} / span ${b.h};`
      + `background:${bg};color:${ink};border-color:${wear === "accent" ? bg : paint("line")}`;
  }
  function boardHtml(p){
    const g = presets().frames?.[p.frame] || {cols: 12, rows: 8};
    const key = keyOf(p);
    const inner = p.blocks.length
      ? p.blocks.map((b, i) => `<div class="dsblock${nb.dsSel[key] === i ? " on" : ""}" tabindex="0" role="button"
            data-i="${i}" style="${blockStyle(b)}" aria-label="${esc(kindLabel(b.kind))}${b.label ? ": " + esc(b.label) : ""}">
            <b>${esc(kindLabel(b.kind))}</b>${b.label ? `<span>${esc(b.label)}</span>` : ""}<i class="dsgrip" aria-hidden="true"></i></div>`).join("")
      : `<div class="dsempty">nothing on this ${esc(p.frame)} yet</div>`;
    return `<div class="dsboard" data-frame="${esc(p.frame)}" role="group" aria-label="the layout of ${esc(p.name || "this page")}"
      style="grid-template-columns:repeat(${g.cols},1fr);grid-template-rows:repeat(${g.rows},1fr);background:${esc(paint("bg"))};border-color:${esc(paint("line"))}">${inner}</div>`;
  }
  const kindLabel = k => byKey(presets().kinds, k)?.label || k;
  function repaintBoard(p){
    const host = root.querySelector(`[data-dspage="${keyOf(p)}"] .dsboard`);
    if (host) host.outerHTML = boardHtml(p);
    pageOption(p);
  }
  // The page's line on the Pages pulldown: its name, platform and count.
  function pageOption(p){
    const o = root.querySelector(`#dsPagePick option[value="${keyOf(p)}"]`);
    if (o) o.textContent = `${p.name.trim() || "unnamed page"} (${platformOf(p)?.label || p.platform}, ${p.blocks.length} block${p.blocks.length === 1 ? "" : "s"})`;
  }
  // Inside the frame, two ways: a block being SIZED keeps its corner and is
  // capped at the edge, a block being MOVED keeps its size and stops at the
  // edge. One rule for both grew a block being sized past the bottom by
  // sliding it up instead. A frame change does both, size first.
  const clampBlock = (b, g, sizing) => {
    b.x = Math.max(0, Math.min(b.x, g.cols - 1)); b.y = Math.max(0, Math.min(b.y, g.rows - 1));
    if (sizing !== false){ b.w = Math.max(1, Math.min(b.w, g.cols - b.x)); b.h = Math.max(1, Math.min(b.h, g.rows - b.y)); }
    if (!sizing){
      b.w = Math.max(1, Math.min(b.w, g.cols)); b.h = Math.max(1, Math.min(b.h, g.rows));
      b.x = Math.min(b.x, g.cols - b.w); b.y = Math.min(b.y, g.rows - b.h);
    }
  };

  function wirePage(el, p){
    if (!el) return;
    const key = keyOf(p);
    const P = presets();
    const grid = () => P.frames?.[p.frame] || {cols: 12, rows: 8};
    el.querySelector('[data-dsf="name"]').oninput = e => {
      p.name = e.target.value;
      pageOption(p);
      touched();
    };
    el.querySelector('[data-dsf="notes"]').oninput = e => { p.notes = e.target.value; touched(); };
    el.querySelector('[data-dsf="platform"]').onchange = e => {
      p.platform = e.target.value;
      const frames = platformOf(p)?.frames || [];
      if (!frames.includes(p.frame)){ p.frame = frames[0] || p.frame; p.blocks.forEach(b => clampBlock(b, grid(), undefined)); }
      touched(); drawDesign();
    };
    el.querySelector('[data-dsf="frame"]').onchange = e => {
      p.frame = e.target.value;
      p.blocks.forEach(b => clampBlock(b, grid(), undefined));
      touched(); drawDesign();
    };
    el.querySelector("[data-dsblockadd]").onclick = () => {
      const g = grid();
      const b = {kind: el.querySelector('[data-dsf="newkind"]').value, label: "",
                 x: 0, y: 0, w: Math.min(4, g.cols), h: Math.min(2, g.rows)};
      // Under the last block rather than on top of the first, while there
      // is room; the finger moves it from there.
      const last = p.blocks[p.blocks.length - 1];
      if (last){ b.y = Math.min(last.y + last.h, g.rows - b.h); b.x = last.x; }
      clampBlock(b, g, false);
      p.blocks.push(b);
      nb.dsSel[key] = p.blocks.length - 1;
      touched(); drawDesign();
      root.querySelector(`[data-dspage="${key}"] [data-dsb="label"]`)?.focus();
    };
    el.querySelector("[data-dsblockrm]")?.addEventListener("click", () => removeBlock(p));
    el.querySelector('[data-dsb="kind"]')?.addEventListener("change", e => {
      const b = p.blocks[nb.dsSel[key]]; if (!b) return;
      b.kind = e.target.value; touched(); repaintBoard(p);
    });
    el.querySelector('[data-dsb="label"]')?.addEventListener("input", e => {
      const b = p.blocks[nb.dsSel[key]]; if (!b) return;
      b.label = e.target.value; touched();
      const on = el.querySelector(".dsblock.on");
      if (on){
        let s = on.querySelector("span");
        if (!s){ s = document.createElement("span"); on.insertBefore(s, on.querySelector(".dsgrip")); }
        s.textContent = b.label;
      }
    });
    el.querySelector("[data-dspagerm]").onclick = () => {
      nb.dsPages = nb.dsPages.filter(x => x !== p);
      delete nb.dsSel[key];
      nb.dsShow.page = null;
      touched(); drawDesign();
    };
    wireBoard(el.querySelector(".dsboard"), p);
  }

  function removeBlock(p){
    const key = keyOf(p);
    if (nb.dsSel[key] == null) return;
    p.blocks.splice(nb.dsSel[key], 1);
    delete nb.dsSel[key];
    touched(); drawDesign();
  }

  // Pointer events on the board, delegated: a block moves under the finger,
  // its corner sizes it, and either commits on release. Pointer rather
  // than mouse events so a touch does the same thing, with touch-action
  // off on the board so the page does not scroll instead.
  function wireBoard(board, p){
    if (!board) return;
    const key = keyOf(p);
    const P = presets();
    board.addEventListener("pointerdown", e => {
      const el = e.target.closest(".dsblock");
      if (!el || root.classList.contains("ro")) return;
      const i = +el.dataset.i, b = p.blocks[i];
      if (!b) return;
      if (nb.dsSel[key] !== i){ nb.dsSel[key] = i; drawDesign(); return; }
      const g = P.frames?.[p.frame] || {cols: 12, rows: 8};
      const r = board.getBoundingClientRect();
      const cw = (r.width - 12) / g.cols, ch = (r.height - 12) / g.rows;
      const resize = e.target.classList.contains("dsgrip");
      const start = {x: e.clientX, y: e.clientY, bx: b.x, by: b.y, bw: b.w, bh: b.h};
      let moved = false;
      el.setPointerCapture(e.pointerId);
      el.classList.add("dragging");
      const move = ev => {
        const dx = Math.round((ev.clientX - start.x) / cw), dy = Math.round((ev.clientY - start.y) / ch);
        if (resize){ b.w = start.bw + dx; b.h = start.bh + dy; }
        else { b.x = start.bx + dx; b.y = start.by + dy; }
        clampBlock(b, g, resize);
        el.style.cssText = blockStyle(b);
        moved = moved || dx !== 0 || dy !== 0;
      };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
        el.classList.remove("dragging");
        if (moved){ touched(); }
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
      e.preventDefault();
    });
    board.addEventListener("focusin", e => {
      const el = e.target.closest(".dsblock");
      if (el && nb.dsSel[key] !== +el.dataset.i){ nb.dsSel[key] = +el.dataset.i; drawDesign();
        root.querySelector(`[data-dspage="${key}"] .dsblock.on`)?.focus(); }
    });
    board.addEventListener("keydown", e => {
      const el = e.target.closest(".dsblock");
      if (!el || root.classList.contains("ro")) return;
      const b = p.blocks[+el.dataset.i];
      if (!b) return;
      const d = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[e.key];
      if (e.key === "Delete" || e.key === "Backspace"){ e.preventDefault(); removeBlock(p); return; }
      if (!d) return;
      e.preventDefault();
      if (e.shiftKey){ b.w += d[0]; b.h += d[1]; } else { b.x += d[0]; b.y += d[1]; }
      clampBlock(b, P.frames?.[p.frame] || {cols: 12, rows: 8}, e.shiftKey);
      el.style.cssText = blockStyle(b);
      touched();
    });
  }

  // ---- the language's controls ------------------------------------------------------
  function wireLanguage(body){
    const L = nb.dsLang;
    for (const [id, k] of [["dsFont", "font"], ["dsCorners", "corners"], ["dsDensity", "density"], ["dsMotion", "motion"]])
      body.querySelector("#" + id).onchange = e => { L[k] = e.target.value; touched(); };
    body.querySelector("#dsScope").oninput = e => { L.scope = e.target.value; touched(); };
    body.querySelector("#dsFonts").oninput = e => { L.fonts = e.target.value; touched(); };
    const pp = body.querySelector("#dsPagePick");
    if (pp) pp.onchange = e => { nb.dsShow.page = e.target.value; drawDesign(); };
  }

  // The themes: the chosen one's colours typed in place; a theme from a
  // preset is the ten colours in its hexes, named for it.
  function wireThemes(body, t){
    const L = nb.dsLang, P = presets();
    const fromScheme = (key, name) => {
      const sc = byKey(P.schemes, key) || P.schemes[0];
      const light = (c => { const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5; })(sc.colors.bg);
      return {name: name || sc.label.replace(" (light)", ""), mode: light ? "light" : "dark",
              colors: (P.tokens || []).map(x => ({name: x.key, hex: sc.colors[x.key], means: x.means}))};
    };
    body.querySelector("#dsThemePick").onchange = e => { nb.dsShow.theme = +e.target.value; drawDesign(); };
    body.querySelector("#dsThemeAdd").onclick = () => {
      const key = body.querySelector("#dsThemeFrom").value;
      const nt = fromScheme(key, "");
      const names = new Set(L.themes.map(x => x.name.toLowerCase()));
      for (let k = 2; names.has(nt.name.toLowerCase()); k++) nt.name = `${byKey(P.schemes, key)?.label || "Theme"} ${k}`;
      L.themes.push(nt);
      nb.dsShow.theme = L.themes.length - 1;
      touched(); drawDesign();
      root.querySelector(`#dst-name-${L.themes.length - 1}`)?.focus();
    };
    const band = body.querySelector("[data-dstheme]");
    if (!band || !t) return;
    const i = +band.dataset.dstheme;
    band.querySelector('[data-dst="name"]').oninput = e => {
      t.name = e.target.value; touched();
      const o = body.querySelector(`#dsThemePick option[value="${i}"]`);
      if (o) o.textContent = `${t.name || "unnamed theme"} (${t.mode})${i === 0 ? ", the default" : ""}`;
    };
    band.querySelector('[data-dst="mode"]').onchange = e => { t.mode = e.target.value; touched(); drawDesign(); };
    band.querySelector('[data-dst="from"]').onchange = e => {
      if (!e.target.value) return;
      const f = fromScheme(e.target.value, t.name);
      t.mode = f.mode; t.colors = f.colors; touched(); drawDesign();
    };
    band.querySelectorAll("[data-dstc]").forEach(row => {
      const c = t.colors[+row.dataset.dstc]; if (!c) return;
      row.querySelector('[data-dsm="name"]').oninput = e => { c.name = e.target.value; touched(); if (i === 0) nb.dsPages.forEach(repaintBoard); };
      row.querySelector('[data-dsm="means"]').oninput = e => { c.means = e.target.value; touched(); };
      row.querySelector('[data-dsm="hex"]').oninput = e => {
        const v = e.target.value.trim().toLowerCase();
        if (!/^#[0-9a-f]{6}$/.test(v)) return;
        c.hex = v; e.target.previousElementSibling.style.background = v;
        if (i === 0) nb.dsPages.forEach(repaintBoard);
        touched();
      };
      row.querySelector("[data-dstcrm]").onclick = () => { t.colors.splice(+row.dataset.dstc, 1); touched(); drawDesign(); };
    });
    band.querySelector("[data-dstcadd]").onclick = () => {
      t.colors.push({name: "", hex: paint("accent"), means: ""}); touched(); drawDesign();
      root.querySelector(`#dst-${i}-name-${t.colors.length - 1}`)?.focus();
    };
    band.querySelector("[data-dstdefault]")?.addEventListener("click", () => {
      L.themes.splice(i, 1); L.themes.unshift(t); nb.dsShow.theme = 0; touched(); drawDesign();
    });
    band.querySelector("[data-dstrm]").onclick = () => {
      L.themes.splice(i, 1); nb.dsShow.theme = 0; touched(); drawDesign();
    };
  }

  // The view is passive by design (the operator, 28 Sep): nothing here
  // reaches into a session. A session meets the design on its own, through
  // the rules the briefing names and bb design show, and a person who wants
  // it applied now copies the prompt into one.

  // ---- what the notebook's Save and Revert do here ----------------------------------
  nb.designStagedCount = () => nb.dsDirty ? 1 : 0;
  nb.designClearStaged = () => {
    if (!nb.dsData) return;
    nb.dsLang = clone(nb.dsData.language);
    nb.dsPages = clone(nb.dsData.pages);
    nb.dsDirty = false;
    nb.dsSel = {};
    if (!root.querySelector('[data-view="design"]').hidden) drawDesign();
  };
  nb.designCommitStaged = async () => {
    if (!nb.dsDirty) return "";
    let j;
    try{
      j = await (await postJSON("/api/design", {project, action: "save", language: nb.dsLang,
                                                  pages: nb.dsPages.map(p => ({...p, id: p.id > 0 ? p.id : undefined}))})).json();
    }catch(e){ notify("design: " + e, true); return ""; }
    if (j.error){ notify("design: " + j.error, true); return ""; }
    // The saved pages come back with their ids, and a board keyed by a
    // temporary number is keyed by its id from here.
    const sel = {};
    nb.dsPages.forEach((p, i) => {
      if (nb.dsSel[keyOf(p)] != null && j.pages[i]) sel[`p${j.pages[i].id}`] = nb.dsSel[keyOf(p)];
      if (nb.dsShow.page === keyOf(p) && j.pages[i]) nb.dsShow.page = `p${j.pages[i].id}`;
    });
    nb.dsSel = sel;
    nb.dsData = {...nb.dsData, language: j.language, pages: j.pages};
    nb.dsLang = clone(j.language);
    nb.dsPages = clone(j.pages);
    nb.dsDirty = false;
    // The file's state is a question for the server, now that what it would
    // write has changed.
    await loadDesign();
    return "design saved";
  };

  return {loadDesign, drawDesign};
}
