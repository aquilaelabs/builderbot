// The notebook's Design view: what the project looks like, kept. One design
// language (colors as tokens, type, shape, space, motion and the operator's
// own rules) and pages laid out as labeled blocks on a phone or desktop
// frame, each named for what it is for and the platform it is built for.
// Two sections, the pages and the themes, open like every page's (the
// operator, 19 Oct: they folded for no reason); each shows one at a time, chosen on a pulldown, and each entry, the
// language included, carries its rules as a section inside it, every rules
// list the Briefing's.
// Every edit is staged and its section's Save (Themes or Pages) writes it at
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
  const holderSlug = name => (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "color";

  // Nothing here changes: a locked project's notebook, or a role that reads
  // the project and does not write it (B101).
  const dsRo = () => root.classList.contains("ro") || !!projWriteWhy(project);

  async function loadDesign(){
    try{
      const j = await (await fetch(`/api/design?project=${encodeURIComponent(project)}`)).json();
      if (j.error){ viewGlance($("dsHint"), [], esc("design: " + j.error), "", "bad"); return; }
      nb.dsData = j;
    }catch(e){ viewGlance($("dsHint"), [], esc("design: " + e), "", "bad"); return; }
    // A re-read never takes what is being edited: the working copies stay
    // until Save or Revert, and only the file's state and the vocabulary
    // come in fresh.
    if (!nb.dsDirty || !nb.dsLang){
      nb.dsLang = clone(nb.dsData.language);
      nb.dsPages = clone(nb.dsData.pages);
      nb.dsDirty = false;
    }
    drawDesign();
  }

  // ---- the glance and the add bar ---------------------------------------------
  // Its pages and themes as tiles (R109), and the file's state on the line
  // under them, with no pages said there while there are none.
  function drawHint(){
    const f = nb.dsData?.file || {};
    const n = (nb.dsPages || []).length, t = (nb.dsLang?.themes || []).length;
    const file = nb.dsDirty ? "unsaved changes: Save in their section"
      : !f.exists ? `${f.path || "docs/design-language.md"} not written yet`
      : f.current ? `${f.path} is written and current`
      : `${f.path} is behind what is saved${dsRo() ? "" : ": Write the file"}`;
    viewGlance($("dsHint"), [{label: n === 1 ? "page" : "pages", value: n, omit: !n},
                             {label: t === 1 ? "theme" : "themes", value: t, omit: !t}],
               esc(`${n ? "" : "no pages yet · "}${file}`));
    const w = $("dsWrite");
    w.disabled = !!nb.dsDirty;
    w.hidden = dsRo();
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
  // The add bar is drawn at the top of the Pages section on every draw
  // (the operator, 29 Sep), so it is wired then rather than once.
  function wireAdd(){
    if (!$("dsAdd")) return;
    drawAdd();
    $("dsPlatform").onchange = fillTemplates;
    $("dsAdd").onclick = () => {
      const src = nb.dsPages.find(x => keyOf(x) === ($("dsPageFrom")?.value || ""));
      const t = byKey(presets().templates, $("dsTemplate").value);
      if (!t && !src) return;
      const p = src
        ? {...clone(src), id: 0, tmp: ++tmpN, name: "", key: ""}
        : {id: 0, tmp: ++tmpN, name: "", platform: $("dsPlatform").value, template: t.key,
           frame: t.frame, blocks: clone(t.blocks), notes: ""};
      nb.dsPages.push(p);
      nb.dsShow.page = keyOf(p);
      // The section opens on what was just added, whatever its fold said.
      sectOpen["design:pages"] = true;
      touched();
      drawDesign();
      root.querySelector(`[data-dspage="${keyOf(p)}"] [data-dsf="name"]`)?.focus();
    };
  }
  $("dsWrite").onclick = async () => {
    const b = $("dsWrite");
    busy(b, "Writing");
    try{
      const j = await (await postJSON("/api/design", {project, action: "write"})).json();
      if (j.error) notify(j.error, true);
      else{
        if (nb.dsData) nb.dsData.file = j.file;
        notify(`${j.path} written into ${projLabel(project)}: the Git view shows it until a session commits it`);
      }
    }catch(e){ notify("design: " + failWords(e), true); }
    unbusy(b, "Write the file");
    drawHint();
  };

  // Something changed: its section's Save wakes, and the prompts follow.
  function touched(){
    nb.dsDirty = true;
    nb.syncSave();
    drawHint();
  }

  // ---- drawing --------------------------------------------------------------------
  const opt = (rows, cur, keyed = "key", labeled = "label") => optionList((rows || []).map(r => [r[keyed], r[labeled]]), cur);
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
    if (!nb.dsData){ body.innerHTML = skel("design"); return; }
    const sh = shown();
    nb.dsRuleLists = {};
    body.innerHTML = pagesSection(sh.page) + themesSection(sh.theme);
    wireSections(body);
    wireAdd();
    wireLanguage(body);
    wireThemes(body, sh.theme);
    if (sh.page) wirePage(body.querySelector(`[data-dspage="${keyOf(sh.page)}"]`), sh.page);
    body.querySelectorAll("[data-dsrules]").forEach(wireRulesList);
    // A project read-only to you reads its design: what a role does not give
    // is not drawn (the operator, 21 Oct), so every press that would change
    // it is gone, a fold's own toggle kept, and the fields stay to read,
    // dead, the pulldowns that pick what is shown live (B293).
    if (dsRo()){
      body.querySelectorAll("input,select:not([data-dspick]),textarea").forEach(e => e.disabled = true);
      body.querySelectorAll("button").forEach(b => { if (!b.closest("summary") && !b.hasAttribute("aria-expanded")){ b.hidden = true; b.disabled = true; } });
    }
    drawHint();
  }

  // A section's pulldown: which of its things is shown below it.
  const pick = (id, text, rows, cur, help = "") =>
    ctl(id, text, help, `<select id="${id}" data-dspick>${opt(rows, cur)}</select>`);

  // One of the language's four choices. Its first line is no choice at
  // all, which is where a design starts (the operator, 29 Sep): each
  // choice carries a sentence a session holds the work to, so one that
  // nobody made must say nothing.
  const choice = (rows, cur) => `<option value=""${cur ? "" : " selected"}>not chosen</option>` + opt(rows, cur);

  // A choice that is custom is said by one of the theme's own rules, and
  // names which: its text is what a session reads in the choice's place.
  const CUSTOM = [["font", "Type"], ["corners", "Corners"], ["density", "Space"], ["motion", "Motion"]];
  function customRow(t, i){
    const mine = CUSTOM.filter(([k]) => t[k] === "custom");
    if (!mine.length) return "";
    const rules = (t.rules || []).filter(r => r.name);
    const pickRule = k => optionList([["", "no rule named"], ...rules.map(r => r.name)], (t.custom || {})[k] || "");
    return `<div class="field"><div class="dsrow">${mine.map(([k, word]) =>
      ctl(`dst-${i}-custom-${k}`, `${word}, by the rule`, "which of this theme's rules says it: a session reads that rule where the choice would be",
          `<select id="dst-${i}-custom-${k}" data-dstcustom="${k}">${pickRule(k)}</select>`)).join("")}</div></div>`;
  }

  // The themes: the add bar (blank, a preset, or a copy of a theme here),
  // a pulldown of them, what the language governs, and the chosen theme
  // whole: its colors, its choices (type, corners, space, motion), its
  // families and its rules. The first theme is the default: the app starts
  // on it, and its choices and rules are the design's (the operator, 29
  // Sep, folding the Design language section into the themes).
  function themesSection(t){
    const L = nb.dsLang, P = presets(), C = P.choices || {};
    const themes = L.themes || [];
    const rows = themes.map((x, i) => ({key: String(i), label: `${x.name || "unnamed theme"} (${x.mode})${i === 0 ? ", the default" : ""}`}));
    const first = themes[0];
    const status = first ? [byKey(C.font, first.font)?.label, byKey(C.corners, first.corners)?.label].filter(Boolean).join(" · ") : "";
    const from = `<option value="" selected>blank</option><optgroup label="a preset">${opt(P.schemes, "")}</optgroup>`
      + (themes.length ? `<optgroup label="a copy of">${themes.map((x, i) => `<option value="copy:${i}">${esc(x.name || "unnamed theme")}</option>`).join("")}</optgroup>` : "");
    const body = `
      <div class="field"><div class="dsrow">
        ${ctl("dsThemeFrom", "Add one from", "blank, a preset's ten colors, or a copy of a theme here, choices and rules included", `<select id="dsThemeFrom">${from}</select>`)}
        <button type="button" id="dsThemeAdd" ${themes.length >= (P.themes_max || 8) ? "disabled" : ""}>Add theme</button>
      </div></div>
      <div class="field">${ctl("dsScope", "Governs",
            "what the language covers when the project is more than one product: the web app in site/",
            `<textarea id="dsScope" class="proseline" rows="1" maxlength="120">${esc(L.scope || "")}</textarea>`, true)}</div>
      ${themes.length ? `<div class="field"><div class="dsrow">
        ${pick("dsThemePick", "Theme", rows, String(nb.dsShow.theme), "each a named set of colors, dark or light, with its own type, corners, space, motion and rules; the first is the default, whose choices and rules are the design's")}
      </div></div>` : ""}
      ${t ? themeBand(t, nb.dsShow.theme, themes.length) : `<div class="field"><div class="hint">No theme yet. Add one, or leave it: a session that builds the project chooses the colors, the type, corners, space and motion, and puts them here.</div></div>`}`;
    return docSection("design", "themes", "Themes", `${themes.length} theme${themes.length === 1 ? "" : "s"}${status ? " · " + status : ""}`,
                      body + nb.sectBar("design:themes"));
  }

  // The design's rules, the Briefing's shape (nb-rules.js, drawRules): Add a
  // rule first, then a row a rule, folded, its name and whether it stands
  // in every briefing or arrives on its triggers, opening to be read, and
  // Edit turning the row into its form. The same list serves the language's
  // rules, a theme's own and a page's own (the operator, 29 Sep): a rules
  // section inside the page and the theme, following the pulldown.
  const cond = ruleCond;
  function rulesList(key, rules){
    nb.dsRuleLists[key] = rules;
    const ui = ruleUI(key);
    return `<div class="addbar ctlrow" data-add="rule"><button type="button" data-dsruleadd ${rules.length >= (presets().rules_max || 60) ? "disabled" : ""}>Add a rule</button></div>
      <div class="field" data-dsrules="${key}">${rules.map((r, i) => `
        <details class="bug chev rulerow${ui.editing.has(i) ? " editing" : ""}" data-i="${i}"${ui.editing.has(i) || ui.open.has(i) ? " open" : ""}>
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
              <span class="state">${ruleWhen(r)} · the section's Save writes it</span>
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
        row.querySelector(".actbar .state").textContent = `${ruleWhen(r)} · the section's Save writes it`;
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

  // One theme: its name and mode, its colors as rows (a name, a hex and
  // what it is for), and what can be done to it. Make default moves
  // another theme up to first.
  function themeBand(t, i, n){
    const P = presets(), C = P.choices || {};
    const modes = (P.modes || ["dark", "light"]).map(m => ({key: m, label: m[0].toUpperCase() + m.slice(1)}));
    return `<div class="dstheme" data-dstheme="${i}">
      <div class="field"><div class="dsrow">
        ${ctl(`dst-name-${i}`, "Name", "", `<textarea id="dst-name-${i}" class="proseline" rows="1" maxlength="40" data-dst="name">${esc(t.name)}</textarea>`, true)}
        ${ctl(`dst-mode-${i}`, "Mode", "", `<select id="dst-mode-${i}" data-dst="mode">${opt(modes, t.mode)}</select>`)}
        ${ctl(`dst-from-${i}`, "Fill from", "replace this theme's colors with a preset's ten",
              `<select id="dst-from-${i}" data-dst="from"><option value="">keep as they are</option>${opt(P.schemes, "")}</select>`)}
      </div></div>
      <div class="field"><div class="dsrow">
        ${ctl(`dst-${i}-font`, "Type", "", `<select id="dst-${i}-font" data-dstchoice="font">${choice(C.font, t.font)}</select>`)}
        ${ctl(`dst-${i}-corners`, "Corners", "", `<select id="dst-${i}-corners" data-dstchoice="corners">${choice(C.corners, t.corners)}</select>`)}
        ${ctl(`dst-${i}-density`, "Space", "", `<select id="dst-${i}-density" data-dstchoice="density">${choice(C.density, t.density)}</select>`)}
        ${ctl(`dst-${i}-motion`, "Motion", "", `<select id="dst-${i}-motion" data-dstchoice="motion">${choice(C.motion, t.motion)}</select>`)}
      </div></div>
      ${customRow(t, i)}
      <div class="field">${ctl(`dst-${i}-fonts`, "Families",
            "the exact font stacks when the choice above is not enough: Inter for text, JetBrains Mono for code",
            `<textarea id="dst-${i}-fonts" class="proseline" rows="1" maxlength="200" data-dst="fonts">${esc(t.fonts || "")}</textarea>`, true)}</div>
      ${docSection("design", `rules:t${i}`, "Rules", (t.rules || []).length ? `${t.rules.length}` : "none",
        `<div class="hint">${i === 0
          ? "The design's rules: what holds for the whole design and the settings cannot say. A session gets one on the turn it edits a file or is asked about a word the rule names; bb design show NAME reads one."
          : `What holds for ${esc(t.name.trim() || "this theme")} alone. A session meets one as ${esc(holderSlug(t.name))}/NAME.`}</div>` + rulesList(`t${i}`, t.rules || (t.rules = [])), {open: true})}
      <div class="field">${lbl("", "Colors", "each a name, a hex and what it is for; a session names them the same in the code")}
      <div class="dscolors">${(t.colors || []).map((c, j) => `
        <div class="dsrow" data-dstc="${j}">
          ${ctl(`dst-${i}-name-${j}`, "Name", "", `<input id="dst-${i}-name-${j}" data-dsm="name" maxlength="40" autocomplete="off" value="${esc(c.name)}">`)}
          ${ctl(`dst-${i}-hex-${j}`, "Hex", "", `<div class="dsc"><span class="dschip" style="background:${esc(c.hex)}"></span><input id="dst-${i}-hex-${j}" data-dsm="hex" maxlength="7" spellcheck="false" autocomplete="off" value="${esc(c.hex)}"></div>`)}
          ${ctl(`dst-${i}-for-${j}`, "For", "", `<textarea id="dst-${i}-for-${j}" class="proseline" rows="1" maxlength="120" data-dsm="means">${esc(c.means)}</textarea>`, true)}
          <button type="button" class="danger" data-dstcrm="${j}" title="take this color out">Remove</button>
        </div>`).join("")}</div></div>
      <div class="field"><div class="actbar"><span class="state">${i === 0 ? "the default: the app starts on it" : ""}</span>
        <button type="button" data-dstcadd ${(t.colors || []).length >= (P.colors_max || 40) ? "disabled" : ""}>Add color</button>
        ${i === 0 ? "" : `<button type="button" data-dstdefault title="the app starts on this theme">Make default</button>`}
        <button type="button" class="danger" data-dstrm title="take this theme out">Remove theme</button></div></div>
      ${lightHalf(t, i)}
    </div>`;
  }

  // The theme's other half (R216): the same tokens for the opposite mode,
  // so one name is one scheme with a dark half and a light one, and the
  // app's mode switch picks the half. Started from the colors above, names
  // and meanings kept, hexes to be set; removed whole.
  function lightHalf(t, i){
    const other = t.mode === "light" ? "dark" : "light";
    if (!(t.light || []).length)
      return `<div class="field"><div class="actbar"><span class="state">one palette: the app has no ${other} half of ${esc(t.name.trim() || "this theme")} to switch to</span>
        <button type="button" data-dstladd ${(t.colors || []).length ? "" : "disabled"}>Add a ${other} half</button></div></div>`;
    return `<div class="field">${lbl("", `The ${other} half`, `the same tokens for ${other} mode; the app's Dark / Light switch picks the half`)}
      <div class="dscolors">${t.light.map((c, j) => `
        <div class="dsrow" data-dstl="${j}">
          ${ctl(`dstl-${i}-name-${j}`, "Name", "", `<input id="dstl-${i}-name-${j}" data-dslm="name" maxlength="40" autocomplete="off" value="${esc(c.name)}">`)}
          ${ctl(`dstl-${i}-hex-${j}`, "Hex", "", `<div class="dsc"><span class="dschip" style="background:${esc(c.hex)}"></span><input id="dstl-${i}-hex-${j}" data-dslm="hex" maxlength="7" spellcheck="false" autocomplete="off" value="${esc(c.hex)}"></div>`)}
        </div>`).join("")}</div></div>
      <div class="field"><div class="actbar"><span class="state">${t.light.length} of ${(t.colors || []).length} tokens</span>
        <button type="button" class="danger" data-dstlrm title="take the ${other} half out">Remove the ${other} half</button></div></div>`;
  }

  // The pages: the add bar (a platform, a template, Add page), a pulldown
  // of them, and the chosen one's board and fields. Shut on a new tab,
  // like the language and the themes (the operator, 29 Sep): the board is
  // the big thing on this view, and it opens on what is added.
  function pagesSection(p){
    const n = nb.dsPages.length;
    const rows = nb.dsPages.map(x => ({key: keyOf(x), label: `${x.name.trim() || "unnamed page"} (${platformOf(x)?.label || x.platform}, ${x.blocks.length} block${x.blocks.length === 1 ? "" : "s"})`}));
    // A new page starts from a template, or as a copy of a page here (its
    // blocks, layouts, rules and notes), blank by default (the operator,
    // 29 Sep).
    const add = `<div class="field"><div class="addbar ctlrow" data-add="design">
        <select id="dsPlatform" aria-label="the platform the new page is for"></select>
        <select id="dsTemplate" aria-label="the layout the new page starts from"></select>
        <select id="dsPageFrom" aria-label="a page here to copy, or none"><option value="" selected>not a copy</option>${
          nb.dsPages.map(x => `<option value="${keyOf(x)}">a copy of ${esc(x.name.trim() || "unnamed page")}</option>`).join("")}</select>
        <button id="dsAdd" class="primary" type="button">Add page</button></div></div>`;
    const body = add + (n ? `
      <div class="field"><div class="dsrow">
        ${pick("dsPagePick", "Page", rows, nb.dsShow.page || "", "each laid out as blocks on a frame and named for what it is for")}
      </div></div>
      ${p ? pageBody(p) : ""}`
      : `<div class="field"><div class="hint">No pages yet: pick a platform and a template and press Add page.</div></div>`);
    return docSection("design", "pages", "Pages", n ? `${n} page${n === 1 ? "" : "s"}` : "none yet",
                      body + nb.sectBar("design:pages"));
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
        ${ctl(`${key}-key`, "Key", "optional: a short name of the page's own, which its rules are addressed under (settings/save). Without one they go by the whole name",
              `<textarea id="${key}-key" class="proseline" rows="1" maxlength="24" data-dsf="key">${esc(p.key || "")}</textarea>`)}
        ${ctl(`${key}-plat`, "Platform", "", `<select id="${key}-plat" data-dsf="platform">${opt(P.platforms, p.platform)}</select>`)}
        ${ctl(`${key}-frame`, "Frame", "", `<select id="${key}-frame" data-dsf="frame">${opt(frames, p.frame)}</select>`)}
        ${ctl(`${key}-rows`, "Rows", "how long the page is: the frame is one screen, and a page with more rows scrolls",
              `<input id="${key}-rows" type="number" inputmode="numeric" min="${frameOf(p.frame).rows}" max="${rowsMax()}" value="${gridOf(p).rows}" data-dsf="rows">`)}
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
        ${ctl(`${key}-bin`, "Inside", "the block this one is part of and stays within, drawn over it: a card in a list, a cover in a card, a pill in a bar; a block inside another can hold blocks of its own",
              `<select id="${key}-bin" data-dsb="in"><option value="">none</option>${p.blocks.map((o, j) => j === sel || descends(p, j, sel) ? ""
                : `<option value="${j + 1}"${b.in === j + 1 ? " selected" : ""}>${j + 1}: ${esc(kindLabel(o.kind))}${o.label ? ": " + esc(o.label.slice(0, 30)) : ""}</option>`).join("")}</select>`)}
        <button type="button" class="danger" data-dsblockrm>Remove block</button>
      </div>
      <div class="hint">Drag a block to move it and its corner to size it; the arrow keys move a focused one, with Shift to size. A later layer draws over an earlier one.</div></div>`
      : `<div class="field"><div class="hint">${n ? "Tap a block to name what it is for." : "Add a block, or start again from a template with Add page."}</div></div>`}
      ${docSection("design", `rules:${key}`, "Rules", (p.rules || []).length ? `${p.rules.length}` : "none",
        `<div class="hint">What holds for ${esc(p.name.trim() || "this page")} alone. A session meets one as ${esc(p.key || holderSlug(p.name || `page-${p.id}`))}/NAME.</div>` + rulesList(key, p.rules || (p.rules = [])), {open: true})}
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
  // The default theme's colors by role, whatever the design calls them
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
  // A frame is one screen and a page may be longer than one: its grid is
  // the frame's columns by its own rows, and the board grows with them.
  const rowsMax = () => presets().rows_max || 60;
  const frameOf = f => presets().frames?.[f] || {cols: 12, rows: 8};
  const reach = places => Math.max(0, ...(places || []).map(b => b.y + b.h));
  const gridOf = p => ({cols: frameOf(p.frame).cols,
                        rows: Math.min(rowsMax(), Math.max(frameOf(p.frame).rows, p.rows || 0))});
  const SHAPE = {desktop: [16, 10], phone: [9, 16], landscape: [16, 9]};
  function boardHtml(p){
    const g = gridOf(p);
    const [bw, bh] = SHAPE[p.frame] || SHAPE.desktop;
    const tall = g.rows > frameOf(p.frame).rows ? `aspect-ratio:${bw} / ${(bh * g.rows / frameOf(p.frame).rows).toFixed(2)};` : "";
    const key = keyOf(p);
    // In the blocks' order, which is the drawing order: a later one draws
    // over an earlier one where they overlap, and the layers beside the
    // board are the way to one another covers (the operator, 29 Sep).
    const inner = p.blocks.length
      ? p.blocks.map((b, i) => `<div class="dsblock${nb.dsSel[key] === i ? " on" : ""}" tabindex="0" role="button"
            data-i="${i}" style="${blockStyle(b)}" aria-label="${esc(kindLabel(b.kind))}${b.label ? ": " + esc(b.label) : ""}">
            <b>${esc(kindLabel(b.kind))}</b>${b.label ? `<span>${esc(b.label)}</span>` : ""}<i class="dsgrip" aria-hidden="true"></i></div>`).join("")
      : `<div class="dsempty">nothing on this ${esc(p.frame)} yet</div>`;
    // A page of many screens is looked at through a window of its own,
    // so the fields under the board stay in reach.
    return `<div class="dsboardrow"><div class="dsboardwrap"><div class="dsboard" data-frame="${esc(p.frame)}" role="group" aria-label="the layout of ${esc(p.name || "this page")}"
      style="${tall}grid-template-columns:repeat(${g.cols},1fr);grid-template-rows:repeat(${g.rows},1fr);background:${esc(paint("bg"))};border-color:${esc(paint("line"))}">${inner}</div></div>${layersHtml(p)}</div>`;
  }
  // Whether block j lies inside block i, however many parents up.
  function descends(p, j, i){
    const seen = new Set();
    for (let k = p.blocks[j]?.in; k && !seen.has(k); k = p.blocks[k - 1]?.in){
      if (k - 1 === i) return true;
      seen.add(k);
    }
    return false;
  }
  const depthOf = (p, i) => { let d = 0; const seen = new Set(); for (let k = p.blocks[i]?.in; k && !seen.has(k); k = p.blocks[k - 1]?.in){ seen.add(k); d++; } return d; };
  // The layers: one row per block, the top layer first, a child indented
  // under its parent's depth, the selected one marked as its block is.
  function layersHtml(p){
    const key = keyOf(p), sel = nb.dsSel[key], n = p.blocks.length;
    const rows = p.blocks.map((b, i) => [b, i]).reverse().map(([b, i]) => `<div class="dslayer${sel === i ? " on" : ""}" data-dsl="${i}" role="button" tabindex="0"
        style="padding-left:${10 + depthOf(p, i) * 12}px" title="select this block${b.in ? `; inside block ${b.in}` : ""}">
        <span class="t"><b>${esc(kindLabel(b.kind))}</b>${b.label ? ` <span>${esc(b.label)}</span>` : ""}</span>
        <button type="button" class="ic" data-dslup="${i}" aria-label="a layer up"${i === n - 1 ? " disabled" : ""} title="a layer up: over the one above it">▲</button>
        <button type="button" class="ic" data-dsldown="${i}" aria-label="a layer down"${i === 0 ? " disabled" : ""} title="a layer down: under the one below it">▼</button></div>`).join("");
    return `<div class="lbox dslayers" role="group" aria-label="the layers of ${esc(p.name || "this page")}, top first">${rows || `<div class="hint">no layers yet</div>`}</div>`;
  }
  // A layer moved up or down the stack: the block and its place on every
  // frame swap with the neighbor's, and every parent number follows.
  function moveLayer(p, i, dir){
    const j = i + dir;
    if (j < 0 || j >= p.blocks.length) return;
    // A child stays over its parent and a parent under its children.
    if (dir < 0 && p.blocks[i].in === j + 1) return;
    if (dir > 0 && p.blocks[j].in === i + 1) return;
    moveTo(p, i, j);
    touched(); drawDesign();
  }
  // Block i taken out of the list and put at j: its place on every frame
  // goes with it, and every parent number follows the move.
  function moveTo(p, i, j){
    if (i === j) return;
    const shift = arr => { const [x] = arr.splice(i, 1); arr.splice(j, 0, x); };
    shift(p.blocks);
    for (const rows of Object.values(p.layouts || {})) shift(rows);
    const at = k => k === i + 1 ? j + 1 : (i < j && k > i + 1 && k <= j + 1) ? k - 1 : (i > j && k >= j + 1 && k < i + 1) ? k + 1 : k;
    p.blocks.forEach(b => { if (b.in) b.in = at(b.in); });
    nb.dsSel[keyOf(p)] = j;
  }
  function wireLayers(el, p){
    el.querySelectorAll("[data-dsl]").forEach(row => {
      const pick = () => { nb.dsSel[keyOf(p)] = +row.dataset.dsl; drawDesign(); };
      row.onclick = pick;
      row.onkeydown = e => { if (e.key === "Enter" || e.key === " "){ e.preventDefault(); pick(); } };
    });
    el.querySelectorAll("[data-dslup]").forEach(b => b.onclick = e => { e.stopPropagation(); if (!dsRo()) moveLayer(p, +b.dataset.dslup, 1); });
    el.querySelectorAll("[data-dsldown]").forEach(b => b.onclick = e => { e.stopPropagation(); if (!dsRo()) moveLayer(p, +b.dataset.dsldown, -1); });
  }
  const kindLabel = k => byKey(presets().kinds, k)?.label || k;
  function repaintBoard(p){
    const row = root.querySelector(`[data-dspage="${keyOf(p)}"] .dsboardrow`);
    if (row){
      row.outerHTML = boardHtml(p);
      const el = root.querySelector(`[data-dspage="${keyOf(p)}"]`);
      wireBoard(el.querySelector(".dsboard"), p);
      wireLayers(el, p);
    }
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

  // A block inside another stays within it: sized down to it where it is
  // bigger, moved in where it reaches out.
  const fitIn = (b, par) => {
    b.w = Math.max(1, Math.min(b.w, par.w)); b.h = Math.max(1, Math.min(b.h, par.h));
    b.x = Math.max(par.x, Math.min(b.x, par.x + par.w - b.w));
    b.y = Math.max(par.y, Math.min(b.y, par.y + par.h - b.h));
  };
  const kidsOf = (p, i) => p.blocks.map((b, j) => j).filter(j => j !== i && descends(p, j, i))
    .sort((a, b) => depthOf(p, a) - depthOf(p, b));
  // Block i was just moved or sized from `before`: held within its parent,
  // its children carried by the move (not by a sizing) and held within
  // it in turn, parents before children. Returns the indexes that moved.
  function settle(p, i, before, sizing){
    const b = p.blocks[i];
    if (b.in) fitIn(b, p.blocks[b.in - 1]);
    const dx = b.x - before.x, dy = b.y - before.y;
    const moved = [];
    for (const j of kidsOf(p, i)){
      const c = p.blocks[j];
      if (!sizing){ c.x += dx; c.y += dy; }
      fitIn(c, p.blocks[c.in - 1]);
      moved.push(j);
    }
    return moved;
  }
  // A page remembers where its blocks sat on each frame it has been on
  // (B348): to Phone and back to Desktop left them squeezed into the
  // phone's six columns, because the clamp that fits them to the smaller
  // frame was never undone. Leaving a frame keeps its layout; arriving on
  // one that has a layout for these blocks takes it, and only a frame
  // never visited is clamped into.
  const geometry = b => ({x: b.x, y: b.y, w: b.w, h: b.h});
  function toFrame(p, frame){
    if (frame === p.frame) return;
    p.layouts = p.layouts || {};
    p.layouts[p.frame] = p.blocks.map(geometry);
    p.frame = frame;
    const kept = p.layouts[frame];
    const had = Array.isArray(kept) && kept.length === p.blocks.length;
    if (had) p.blocks.forEach((b, i) => Object.assign(b, kept[i]));
    // As long as its layout there was; a frame never visited is one screen.
    p.rows = had ? Math.max(frameOf(frame).rows, reach(kept)) : frameOf(frame).rows;
    p.blocks.forEach(b => clampBlock(b, gridOf(p), undefined));
    delete p.layouts[frame];
  }
  // A block added or taken away is added to or taken from every layout the
  // page keeps, so the layouts stay about the same blocks.
  function layoutsAdd(p, b){
    for (const [f, rows] of Object.entries(p.layouts || {})){
      const nb_ = geometry(b);
      clampBlock(nb_, {cols: frameOf(f).cols, rows: Math.max(frameOf(f).rows, reach(rows))}, false);
      rows.push(nb_);
    }
  }
  function layoutsRemove(p, i){
    for (const rows of Object.values(p.layouts || {})) rows.splice(i, 1);
  }

  function wirePage(el, p){
    if (!el) return;
    const key = keyOf(p);
    const P = presets();
    const grid = () => gridOf(p);
    // Rows are a draft like the rest: shortening a page brings its blocks
    // up into what is left, and never under the frame's one screen.
    el.querySelector('[data-dsf="rows"]').onchange = e => {
      const n = Math.round(Number(e.target.value)) || 0;
      p.rows = Math.min(rowsMax(), Math.max(frameOf(p.frame).rows, n));
      p.blocks.forEach(b => clampBlock(b, gridOf(p), undefined));
      touched(); drawDesign();
    };
    el.querySelector('[data-dsf="name"]').oninput = e => {
      p.name = e.target.value;
      pageOption(p);
      touched();
    };
    el.querySelector('[data-dsf="notes"]').oninput = e => { p.notes = e.target.value; touched(); };
    el.querySelector('[data-dsf="key"]').oninput = e => {
      p.key = e.target.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+/, "").slice(0, 24);
      touched();
    };
    el.querySelector('[data-dsf="key"]').onchange = () => drawDesign();
    el.querySelector('[data-dsf="platform"]').onchange = e => {
      p.platform = e.target.value;
      const frames = platformOf(p)?.frames || [];
      if (!frames.includes(p.frame)) toFrame(p, frames[0] || p.frame);
      touched(); drawDesign();
    };
    el.querySelector('[data-dsf="frame"]').onchange = e => {
      toFrame(p, e.target.value);
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
      layoutsAdd(p, b);
      nb.dsSel[key] = p.blocks.length - 1;
      touched(); drawDesign();
      root.querySelector(`[data-dspage="${key}"] [data-dsb="label"]`)?.focus();
    };
    el.querySelector("[data-dsblockrm]")?.addEventListener("click", () => removeBlock(p));
    el.querySelector('[data-dsb="kind"]')?.addEventListener("change", e => {
      const b = p.blocks[nb.dsSel[key]]; if (!b) return;
      b.kind = e.target.value; touched(); repaintBoard(p);
    });
    el.querySelector('[data-dsb="in"]')?.addEventListener("change", e => {
      const i = nb.dsSel[key], b = p.blocks[i]; if (!b) return;
      if (e.target.value) b.in = +e.target.value; else delete b.in;
      // Brought within its parent now, here and on every other frame's
      // layout, and drawn over it: a block that came before its parent in
      // the list moves to just after it (the operator, 29 Sep).
      if (b.in){
        fitIn(b, p.blocks[b.in - 1]);
        for (const rows of Object.values(p.layouts || {})) fitIn(rows[i], rows[b.in - 1]);
        if (b.in - 1 > i) moveTo(p, i, b.in - 1);
      }
      touched(); drawDesign();
    });
    wireLayers(el, p);
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
    const i = nb.dsSel[key];
    p.blocks.splice(i, 1);
    layoutsRemove(p, i);
    // Its children are freed, keeping their place; the parent numbers
    // above it move down one.
    p.blocks.forEach(b => { if (b.in === i + 1) delete b.in; else if (b.in > i + 1) b.in -= 1; });
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
      if (!el || dsRo()) return;
      const i = +el.dataset.i, b = p.blocks[i];
      if (!b) return;
      if (nb.dsSel[key] !== i){ nb.dsSel[key] = i; drawDesign(); return; }
      const g = gridOf(p);
      const r = board.getBoundingClientRect();
      const cw = (r.width - 12) / g.cols, ch = (r.height - 12) / g.rows;
      const resize = e.target.classList.contains("dsgrip");
      const start = {x: e.clientX, y: e.clientY, bx: b.x, by: b.y, bw: b.w, bh: b.h};
      let moved = false;
      el.setPointerCapture(e.pointerId);
      el.classList.add("dragging");
      const move = ev => {
        const dx = Math.round((ev.clientX - start.x) / cw), dy = Math.round((ev.clientY - start.y) / ch);
        const before = geometry(b);
        if (resize){ b.w = start.bw + dx; b.h = start.bh + dy; }
        else { b.x = start.bx + dx; b.y = start.by + dy; }
        clampBlock(b, g, resize);
        // Settled (held within its parent, its children carried) before it
        // is drawn, or the screen shows a place the block does not have.
        const carried = settle(p, i, before, resize);
        el.style.cssText = blockStyle(b);
        for (const j of carried){
          const kid = board.querySelector(`.dsblock[data-i="${j}"]`);
          if (kid) kid.style.cssText = blockStyle(p.blocks[j]);
        }
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
      if (!el || dsRo()) return;
      const b = p.blocks[+el.dataset.i];
      if (!b) return;
      const d = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[e.key];
      if (e.key === "Delete" || e.key === "Backspace"){ e.preventDefault(); removeBlock(p); return; }
      if (!d) return;
      e.preventDefault();
      const before = geometry(b);
      if (e.shiftKey){ b.w += d[0]; b.h += d[1]; } else { b.x += d[0]; b.y += d[1]; }
      clampBlock(b, gridOf(p), e.shiftKey);
      const carried = settle(p, +el.dataset.i, before, e.shiftKey);
      el.style.cssText = blockStyle(b);
      for (const j of carried){
        const kid = board.querySelector(`.dsblock[data-i="${j}"]`);
        if (kid) kid.style.cssText = blockStyle(p.blocks[j]);
      }
      touched();
    });
  }

  // ---- the language's controls ------------------------------------------------------
  function wireLanguage(body){
    const L = nb.dsLang;
    const sc = body.querySelector("#dsScope");
    if (sc) sc.oninput = e => { L.scope = e.target.value; touched(); };
    const pp = body.querySelector("#dsPagePick");
    if (pp) pp.onchange = e => { nb.dsShow.page = e.target.value; drawDesign(); };
  }

  // The themes: the chosen one's colors typed in place; a theme from a
  // preset is the ten colors in its hexes, named for it.
  function wireThemes(body, t){
    const L = nb.dsLang, P = presets();
    const fromScheme = (key, name) => {
      const sc = byKey(P.schemes, key) || P.schemes[0];
      const light = (c => { const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5; })(sc.colors.bg);
      return {name: name || sc.label.replace(" (light)", ""), mode: light ? "light" : "dark",
              colors: (P.tokens || []).map(x => ({name: x.key, hex: sc.colors[x.key], means: x.means}))};
    };
    const tp = body.querySelector("#dsThemePick");
    if (tp) tp.onchange = e => { nb.dsShow.theme = +e.target.value; drawDesign(); };
    body.querySelector("#dsThemeAdd").onclick = () => {
      const key = body.querySelector("#dsThemeFrom").value;
      // Blank, a preset, or a copy of a theme here, choices and rules
      // included (the operator, 29 Sep).
      let nt, base;
      if (key.startsWith("copy:")){
        const src = L.themes[+key.slice(5)];
        nt = clone(src); base = `${src.name} copy`; nt.name = base;
      } else if (key){ nt = fromScheme(key, ""); base = byKey(P.schemes, key)?.label || "Theme"; }
      else { nt = {name: "Theme", mode: "dark", colors: [], rules: []}; base = "Theme"; }
      const names = new Set(L.themes.map(x => x.name.toLowerCase()));
      for (let k = 2; names.has(nt.name.toLowerCase()); k++) nt.name = `${base} ${k}`;
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
    band.querySelectorAll("[data-dstchoice]").forEach(sel => sel.onchange = e => {
      const k = sel.dataset.dstchoice, was = t[k];
      t[k] = e.target.value;
      // The rule a custom choice named goes with the choice.
      if (t[k] !== "custom" && t.custom) delete t.custom[k];
      touched();
      if ((was === "custom") !== (t[k] === "custom") || i === 0) drawDesign();
    });
    band.querySelectorAll("[data-dstcustom]").forEach(sel => sel.onchange = e => {
      t.custom = t.custom || {};
      if (e.target.value) t.custom[sel.dataset.dstcustom] = e.target.value; else delete t.custom[sel.dataset.dstcustom];
      touched();
    });
    band.querySelector('[data-dst="fonts"]').oninput = e => { t.fonts = e.target.value; touched(); };
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
    band.querySelector("[data-dstladd]")?.addEventListener("click", () => {
      t.light = t.colors.map(c => ({name: c.name, hex: c.hex, means: c.means})); touched(); drawDesign();
    });
    band.querySelector("[data-dstlrm]")?.addEventListener("click", () => { t.light = []; touched(); drawDesign(); });
    band.querySelectorAll("[data-dstl]").forEach(row => {
      const c = (t.light || [])[+row.dataset.dstl]; if (!c) return;
      row.querySelector('[data-dslm="name"]').oninput = e => { c.name = e.target.value; touched(); };
      row.querySelector('[data-dslm="hex"]').oninput = e => {
        const v = e.target.value.trim().toLowerCase();
        if (!/^#[0-9a-f]{6}$/.test(v)) return;
        c.hex = v; e.target.previousElementSibling.style.background = v; touched();
      };
    });
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

  // ---- each section's Save and Revert (the operator, 5 Oct) -------------------------
  // The design is one record, but its two sections stage apart: Themes holds
  // the language (its themes, choices, notes and rules), Pages the pages. A
  // section's Save writes its half over what is saved of the other, and its
  // Revert puts back only its own.
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const langDirty = () => !!nb.dsData && !!nb.dsLang && !same(nb.dsLang, nb.dsData.language);
  const pagesDirty = () => !!nb.dsData && !!nb.dsPages && !same(nb.dsPages, nb.dsData.pages);
  nb.designStagedCount = () => (langDirty() ? 1 : 0) + (pagesDirty() ? 1 : 0);
  nb.designClearStaged = part => {
    if (!nb.dsData) return;
    if (part !== "pages") nb.dsLang = clone(nb.dsData.language);
    if (part !== "themes"){ nb.dsPages = clone(nb.dsData.pages); nb.dsSel = {}; }
    nb.dsDirty = langDirty() || pagesDirty();
    if (!root.querySelector('[data-view="design"]').hidden) drawDesign();
  };
  nb.designCommitStaged = async part => {
    const lang = part === "pages" ? nb.dsData.language : nb.dsLang;
    const pages = part === "themes" ? nb.dsData.pages : nb.dsPages;
    if (part === "themes" ? !langDirty() : part === "pages" ? !pagesDirty() : !nb.dsDirty) return "";
    // The half not being saved keeps its edits only if it has any: the
    // server answers with the record normalized, and an untouched half
    // compared against that read as edited (5 Oct).
    const keepLang = part === "pages" && langDirty(), keepPages = part === "themes" && pagesDirty();
    let j;
    try{
      j = await (await postJSON("/api/design", {project, action: "save", language: lang,
                                                  pages: pages.map(p => ({...p, id: p.id > 0 ? p.id : undefined}))})).json();
    }catch(e){ notify("design: " + failWords(e), true); return null; }
    if (j.error){ notify("design: " + j.error, true); return null; }
    // The saved pages come back with their ids, and a board keyed by a
    // temporary number is keyed by its id from here.
    if (part !== "themes"){
      const sel = {};
      nb.dsPages.forEach((p, i) => {
        if (nb.dsSel[keyOf(p)] != null && j.pages[i]) sel[`p${j.pages[i].id}`] = nb.dsSel[keyOf(p)];
        if (nb.dsShow.page === keyOf(p) && j.pages[i]) nb.dsShow.page = `p${j.pages[i].id}`;
      });
      nb.dsSel = sel;
    }
    nb.dsData = {...nb.dsData, language: j.language, pages: j.pages};
    if (!keepLang) nb.dsLang = clone(j.language);
    if (!keepPages) nb.dsPages = clone(j.pages);
    nb.dsDirty = langDirty() || pagesDirty();
    // The file's state is a question for the server, now that what it would
    // write has changed.
    await loadDesign();
    return part === "themes" ? "the design's themes saved" : part === "pages" ? "the design's pages saved" : "design saved";
  };
  nb.stage("design:themes", {count: () => (langDirty() ? 1 : 0), what: () => "the edited themes",
                             save: () => nb.designCommitStaged("themes"), revert: () => nb.designClearStaged("themes")});
  nb.stage("design:pages", {count: () => (pagesDirty() ? 1 : 0), what: () => "the edited pages",
                            save: () => nb.designCommitStaged("pages"), revert: () => nb.designClearStaged("pages")});

  return {loadDesign, drawDesign};
}
