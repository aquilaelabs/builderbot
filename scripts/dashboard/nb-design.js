// The notebook's Design view: what the project looks like, kept. One design
// language (colours as tokens, type, shape, space, motion and the operator's
// own rules) and pages laid out as labelled blocks on a phone or desktop
// frame, each named for what it is for and the platform it is built for.
// Every edit is staged and the notebook's Save writes the whole record at
// once, the way the roadmap saves; the prompt under each page and the
// language is the server's (design.py), so the tab, `bb design show` and
// docs/design-language.md say one thing. One classic script beside
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
  let tmpN = 0;
  const keyOf = p => p.id > 0 ? `p${p.id}` : `t${p.tmp}`;
  const presets = () => nb.dsData?.presets || {};
  const byKey = (rows, k) => (rows || []).find(r => r.key === k);
  const platformOf = p => byKey(presets().platforms, p.platform) || (presets().platforms || [])[0];
  const clone = o => JSON.parse(JSON.stringify(o));

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
    refreshStates();
  }

  // ---- drawing --------------------------------------------------------------------
  const opt = (rows, cur, keyed = "key", labeled = "label") => (rows || [])
    .map(r => `<option value="${esc(r[keyed])}"${r[keyed] === cur ? " selected" : ""}>${esc(r[labeled])}</option>`).join("");
  const ctl = (id, text, help, control, grow) =>
    `<div class="dsctl${grow ? " grow" : ""}">${lbl(id, text, help)}${control}</div>`;

  function drawDesign(){
    const body = $("dsBody");
    if (!nb.dsData){ body.innerHTML = `<div class="loading">loading…</div>`; return; }
    body.innerHTML = languageSection() + nb.dsPages.map(pageSection).join("");
    wireSections(body);
    wireLanguage(body);
    nb.dsPages.forEach(p => wirePage(body.querySelector(`[data-dspage="${keyOf(p)}"]`), p));
    // A locked project reads its notebook: every control here is dead but
    // Copy, which takes nothing anywhere.
    if (root.classList.contains("ro"))
      body.querySelectorAll("input,select,textarea,button:not([data-dscopy])").forEach(e => e.disabled = true);
    drawHint();
    refreshStates();
    refreshPrompt("lang");
    nb.dsPages.forEach(p => refreshPrompt(keyOf(p)));
  }

  function languageSection(){
    const L = nb.dsLang, P = presets(), C = P.choices || {};
    const themes = L.themes || [];
    const status = `${themes.length} theme${themes.length === 1 ? "" : "s"}`;
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
      <div class="field">${lbl("", "Themes", "each a named set of colours, dark or light; the first is the one the app starts on, and a theme picker, where the app has one, offers them by name")}
        <div class="addbar" data-add="theme"><select id="dsThemeFrom" aria-label="the preset the new theme starts from">${
          opt(P.schemes, "default")}</select><button type="button" id="dsThemeAdd" ${themes.length >= (P.themes_max || 8) ? "disabled" : ""}>Add theme</button></div></div>
      ${themes.map((t, i) => themeBand(t, i, themes.length)).join("")}
      <div class="field">${ctl("dsScope", "Governs",
            "what the language covers when the project is more than one product: the web app in site/",
            `<textarea id="dsScope" class="proseline" rows="1" maxlength="120">${esc(L.scope)}</textarea>`, true)}</div>
      <div class="field">${lbl("", "Design rules", "everything the settings cannot say, cut into named rules: a session gets one on the turn it edits a file or is asked about a word the rule names; one with no trigger stands in every briefing")}
        <div class="addbar" data-add="rule"><button type="button" id="dsRuleAdd" ${(L.rules || []).length >= (P.rules_max || 60) ? "disabled" : ""}>Add rule</button></div></div>
      ${(L.rules || []).map((r, i) => `<div class="field dsrule" data-dsrule="${i}">
        <div class="dsrow">
          ${ctl(`dsr-name-${i}`, "Rule", "a short name: dialogs, tap-targets", `<input id="dsr-name-${i}" data-dsr="name" maxlength="40" autocomplete="off" value="${esc(r.name)}">`)}
          ${ctl(`dsr-words-${i}`, "Words", "words in a prompt that bring it up, comma-separated", `<textarea id="dsr-words-${i}" class="proseline" rows="1" maxlength="300" data-dsr="words">${esc((r.words || []).join(", "))}</textarea>`, true)}
          ${ctl(`dsr-files-${i}`, "Files", "files or directories whose edit brings it up: src/ui, *.css", `<textarea id="dsr-files-${i}" class="proseline" rows="1" maxlength="300" data-dsr="paths">${esc((r.paths || []).join(", "))}</textarea>`, true)}
        </div>
        ${ctl(`dsr-text-${i}`, "Text", "", `<textarea id="dsr-text-${i}" rows="${(r.text || "").length > 600 ? 10 : 4}" maxlength="20000" data-dsr="text">${esc(r.text)}</textarea>`, true)}
        <div class="actbar"><span class="state">${(r.words || []).length || (r.paths || []).length ? "named in the briefing; its text arrives when it applies" : "standing: in every briefing whole"}</span>
          <button type="button" class="danger" data-dsrrm title="take this rule out">Remove rule</button></div>
      </div>`).join("")}
      <div class="field">${lbl("dsPromptL", "Prompt", "what a session is asked to do; Send to Claude points the session at it")}
        <textarea id="dsPromptL" class="dsprompt" readonly rows="10" spellcheck="false"></textarea>
        <div class="actbar"><span class="state" data-dsstate="lang"></span>
          <button type="button" data-dscopy="lang" title="copy the prompt">Copy</button>
          <button type="button" class="primary" data-dssend="lang">Send to Claude</button></div></div>`;
    return docSection("design", "language", "Design language", status, body);
  }

  // One theme: its name and mode, its colours as rows (a name, a hex and
  // what it is for), and what can be done to it. The first theme is the
  // one the app starts on; Make default moves another up to first.
  function themeBand(t, i, n){
    const P = presets();
    const modes = (P.modes || ["dark", "light"]).map(m => ({key: m, label: m[0].toUpperCase() + m.slice(1)}));
    return `<div class="field dstheme" data-dstheme="${i}">
      <div class="dsrow">
        ${ctl(`dst-name-${i}`, "Theme", "", `<textarea id="dst-name-${i}" class="proseline" rows="1" maxlength="40" data-dst="name">${esc(t.name)}</textarea>`, true)}
        ${ctl(`dst-mode-${i}`, "Mode", "", `<select id="dst-mode-${i}" data-dst="mode">${opt(modes, t.mode)}</select>`)}
        ${ctl(`dst-from-${i}`, "Fill from", "replace this theme's colours with a preset's ten",
              `<select id="dst-from-${i}" data-dst="from"><option value="">keep as they are</option>${opt(P.schemes, "")}</select>`)}
      </div>
      <div class="dscolours">${(t.colors || []).map((c, j) => `
        <div class="dsrow" data-dstc="${j}">
          ${ctl(`dst-${i}-name-${j}`, "Name", "", `<input id="dst-${i}-name-${j}" data-dsm="name" maxlength="40" autocomplete="off" value="${esc(c.name)}">`)}
          ${ctl(`dst-${i}-hex-${j}`, "Hex", "", `<div class="dsc"><span class="dschip" style="background:${esc(c.hex)}"></span><input id="dst-${i}-hex-${j}" data-dsm="hex" maxlength="7" spellcheck="false" autocomplete="off" value="${esc(c.hex)}"></div>`)}
          ${ctl(`dst-${i}-for-${j}`, "For", "", `<textarea id="dst-${i}-for-${j}" class="proseline" rows="1" maxlength="120" data-dsm="means">${esc(c.means)}</textarea>`, true)}
          <button type="button" class="danger" data-dstcrm="${j}" title="take this colour out">Remove</button>
        </div>`).join("")}</div>
      <div class="actbar"><span class="state">${i === 0 ? "the default: the app starts on it" : ""}</span>
        <button type="button" data-dstcadd ${(t.colors || []).length >= (P.colors_max || 40) ? "disabled" : ""}>Add colour</button>
        ${i === 0 ? "" : `<button type="button" data-dstdefault title="the app starts on this theme">Make default</button>`}
        <button type="button" class="danger" data-dstrm ${n === 1 ? "disabled" : ""} title="${n === 1 ? "a language keeps at least one theme" : "take this theme out"}">Remove theme</button></div>
    </div>`;
  }

  function pageSection(p){
    const P = presets(), key = keyOf(p);
    const plat = platformOf(p);
    const frames = (plat?.frames || Object.keys(P.frames || {})).map(f => ({key: f, label: P.frames?.[f]?.label || f}));
    const n = p.blocks.length;
    const sel = nb.dsSel[key];
    const b = sel != null ? p.blocks[sel] : null;
    const body = `
      <div class="field"><div class="dsrow">
        ${ctl(`${key}-name`, "For", "what this page is for: the settings page. Sending it means applying the design there",
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
      <div class="field">${ctl(`${key}-notes`, "Notes", "what the blocks cannot say: what a tap does, where the data comes from",
            `<textarea id="${key}-notes" rows="3" maxlength="65536" data-dsf="notes">${esc(p.notes)}</textarea>`, true)}</div>
      <div class="field">${lbl(`${key}-prompt`, "Prompt", "what a session is asked to do for this page; Send to Claude points the session at it")}
        <textarea id="${key}-prompt" class="dsprompt" readonly rows="10" spellcheck="false" data-dsprompt></textarea>
        <div class="actbar"><span class="state" data-dsstate="${key}"></span>
          <button type="button" data-dscopy="${key}" title="copy the prompt">Copy</button>
          <button type="button" class="primary" data-dssend="${key}">Send to Claude</button>
          <button type="button" class="danger" data-dspagerm title="take this page out; Save makes it final, Revert brings it back">Remove page</button></div></div>`;
    return `<div data-dspage="${key}">${docSection("design", `page:${key}`,
      p.name || "unnamed page", `${plat?.label || p.platform} · ${n} block${n === 1 ? "" : "s"}`, body,
      {open: p.id > 0 ? undefined : true})}</div>`;
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
    const sect = root.querySelector(`[data-dspage="${keyOf(p)}"] .sect > summary .sst`);
    if (sect) sect.textContent = `${platformOf(p)?.label || p.platform} · ${p.blocks.length} block${p.blocks.length === 1 ? "" : "s"}`;
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
      const t = el.querySelector(".sect > summary .t");
      if (t) t.textContent = p.name.trim() || "unnamed page";
      touched(); refreshPrompt(key);
    };
    el.querySelector('[data-dsf="notes"]').oninput = e => { p.notes = e.target.value; touched(); refreshPrompt(key); };
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
      b.kind = e.target.value; touched(); repaintBoard(p); refreshPrompt(key);
    });
    el.querySelector('[data-dsb="label"]')?.addEventListener("input", e => {
      const b = p.blocks[nb.dsSel[key]]; if (!b) return;
      b.label = e.target.value; touched(); refreshPrompt(key);
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
      touched(); drawDesign();
    };
    el.querySelector("[data-dscopy]").onclick = e => copyPrompt(el.querySelector("[data-dsprompt]").value, e.target);
    el.querySelector("[data-dssend]").onclick = e => sendTo(p, e.target);
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
        if (moved){ touched(); refreshPrompt(key); }
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
      touched(); refreshPrompt(key);
    });
  }

  // ---- the language's controls ------------------------------------------------------
  function wireLanguage(body){
    const L = nb.dsLang, P = presets();
    const sst = () => { const e = body.querySelector('[data-sect="design:language"] > summary .sst');
      if (e) e.textContent = `${L.themes.length} theme${L.themes.length === 1 ? "" : "s"}`; };
    for (const [id, k] of [["dsFont", "font"], ["dsCorners", "corners"], ["dsDensity", "density"], ["dsMotion", "motion"]])
      body.querySelector("#" + id).onchange = e => { L[k] = e.target.value; touched(); refreshAllPrompts(); };
    body.querySelector("#dsScope").oninput = e => { L.scope = e.target.value; touched(); refreshAllPrompts(); };
    body.querySelector("#dsFonts").oninput = e => { L.fonts = e.target.value; touched(); refreshAllPrompts(); };
    // The design's rules: typed in place, added and removed with a redraw.
    const split = v => v.split(/[,\s]+/).map(x => x.trim()).filter(Boolean);
    body.querySelectorAll("[data-dsrule]").forEach(band => {
      const r = L.rules[+band.dataset.dsrule]; if (!r) return;
      band.querySelector('[data-dsr="name"]').oninput = e => { r.name = e.target.value; touched(); refreshAllPrompts(); };
      band.querySelector('[data-dsr="text"]').oninput = e => { r.text = e.target.value; touched(); refreshAllPrompts(); };
      band.querySelector('[data-dsr="words"]').oninput = e => { r.words = split(e.target.value); touched(); refreshAllPrompts(); };
      band.querySelector('[data-dsr="paths"]').oninput = e => { r.paths = split(e.target.value); touched(); refreshAllPrompts(); };
      band.querySelector("[data-dsrrm]").onclick = () => { L.rules.splice(+band.dataset.dsrule, 1); touched(); drawDesign(); };
    });
    body.querySelector("#dsRuleAdd").onclick = () => {
      L.rules = L.rules || [];
      L.rules.push({name: "", text: "", words: [], paths: []});
      touched(); drawDesign();
      root.querySelector(`#dsr-name-${L.rules.length - 1}`)?.focus();
    };
    // A theme from a preset: the ten colours in its hexes, named for it.
    const fromScheme = (key, name) => {
      const sc = byKey(P.schemes, key) || P.schemes[0];
      const light = (c => { const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5; })(sc.colors.bg);
      return {name: name || sc.label.replace(" (light)", ""), mode: light ? "light" : "dark",
              colors: (P.tokens || []).map(t => ({name: t.key, hex: sc.colors[t.key], means: t.means}))};
    };
    body.querySelector("#dsThemeAdd").onclick = () => {
      const key = body.querySelector("#dsThemeFrom").value;
      const t = fromScheme(key, "");
      const names = new Set(L.themes.map(x => x.name.toLowerCase()));
      for (let k = 2; names.has(t.name.toLowerCase()); k++) t.name = `${byKey(P.schemes, key)?.label || "Theme"} ${k}`;
      L.themes.push(t); touched(); drawDesign();
      root.querySelector(`#dst-name-${L.themes.length - 1}`)?.focus();
    };
    body.querySelectorAll("[data-dstheme]").forEach(band => {
      const i = +band.dataset.dstheme, t = L.themes[i]; if (!t) return;
      band.querySelector('[data-dst="name"]').oninput = e => { t.name = e.target.value; touched(); refreshAllPrompts(); };
      band.querySelector('[data-dst="mode"]').onchange = e => { t.mode = e.target.value; touched(); refreshAllPrompts(); };
      band.querySelector('[data-dst="from"]').onchange = e => {
        if (!e.target.value) return;
        const f = fromScheme(e.target.value, t.name);
        t.mode = f.mode; t.colors = f.colors; touched(); drawDesign();
      };
      band.querySelectorAll("[data-dstc]").forEach(row => {
        const c = t.colors[+row.dataset.dstc]; if (!c) return;
        row.querySelector('[data-dsm="name"]').oninput = e => { c.name = e.target.value; touched(); if (i === 0) nb.dsPages.forEach(repaintBoard); refreshAllPrompts(); };
        row.querySelector('[data-dsm="means"]').oninput = e => { c.means = e.target.value; touched(); refreshAllPrompts(); };
        row.querySelector('[data-dsm="hex"]').oninput = e => {
          const v = e.target.value.trim().toLowerCase();
          if (!/^#[0-9a-f]{6}$/.test(v)) return;
          c.hex = v; e.target.previousElementSibling.style.background = v;
          if (i === 0) nb.dsPages.forEach(repaintBoard);
          touched(); refreshAllPrompts();
        };
        row.querySelector("[data-dstcrm]").onclick = () => { t.colors.splice(+row.dataset.dstc, 1); touched(); drawDesign(); };
      });
      band.querySelector("[data-dstcadd]").onclick = () => {
        t.colors.push({name: "", hex: paint("accent"), means: ""}); touched(); drawDesign();
        root.querySelector(`#dst-${i}-name-${t.colors.length - 1}`)?.focus();
      };
      band.querySelector("[data-dstdefault]")?.addEventListener("click", () => {
        L.themes.splice(i, 1); L.themes.unshift(t); touched(); drawDesign();
      });
      band.querySelector("[data-dstrm]").onclick = () => {
        if (L.themes.length === 1) return;
        L.themes.splice(i, 1); touched(); drawDesign();
      };
    });
    sst();
    body.querySelector('[data-dscopy="lang"]').onclick = e => copyPrompt(body.querySelector("#dsPromptL").value, e.target);
    body.querySelector('[data-dssend="lang"]').onclick = e => sendTo(null, e.target);
  }

  // ---- the prompts, from the server ---------------------------------------------------
  // Asked a moment after the last keystroke, one request per prompt, and the
  // answer lands in its box without a redraw so the typing is not disturbed.
  const timers = {};
  function refreshPrompt(key){
    clearTimeout(timers[key]);
    timers[key] = setTimeout(async () => {
      const p = key === "lang" ? null : nb.dsPages.find(x => keyOf(x) === key);
      if (key !== "lang" && !p) return;
      const box = key === "lang" ? root.querySelector("#dsPromptL")
                                 : root.querySelector(`[data-dspage="${key}"] [data-dsprompt]`);
      if (!box) return;
      try{
        const j = await (await postJSON("/api/design", {project, action: "preview", language: nb.dsLang,
                                                       ...(p ? {page: p} : {})})).json();
        if (j.error){ box.value = "could not build the prompt: " + j.error; return; }
        box.value = j.text;
      }catch(e){ box.value = "could not reach the server: " + e; }
    }, 250);
  }
  function refreshAllPrompts(){ refreshPrompt("lang"); nb.dsPages.forEach(p => refreshPrompt(keyOf(p))); }

  async function copyPrompt(text, btn){
    try{ await navigator.clipboard.writeText(text || ""); notify("copied"); }
    catch(e){ notify("could not copy: select the text and copy it yourself", true); }
    btn?.blur();
  }

  // Why Send to Claude is dead, on its row: what is sent is a pointer at the
  // SAVED design, into a running session of this account's.
  const running = () => (state?.sessions || []).some(x => x.name === myClaude(project));
  function sendWhy(p){
    if (nb.dsDirty) return "Save first: the session reads what is saved";
    if (p && !p.name.trim()) return "name the page first: what it is for";
    if (!running()) return "no Claude session of yours is running on this project: press Claude on its card";
    return "";
  }
  function refreshStates(){
    const body = $("dsBody");
    if (!body) return;
    for (const b of body.querySelectorAll("[data-dssend]")){
      const key = b.dataset.dssend;
      const p = key === "lang" ? null : nb.dsPages.find(x => keyOf(x) === key);
      const why = sendWhy(p);
      b.disabled = !!why || root.classList.contains("ro");
      b.title = why || (p ? `type a line into the session: build or restyle ${p.name.trim()} to this design`
                          : "type a line into the session: apply the language to the project");
      const st = body.querySelector(`[data-dsstate="${key}"]`);
      if (st){ st.textContent = why; st.classList.toggle("bad", !!why); }
    }
  }
  // The poll: a session starting or ending changes what the rows say.
  nb.dsPoll = () => { if (nb.dsData) refreshStates(); };

  async function sendTo(p, btn){
    const why = sendWhy(p);
    if (why){ notify(why, true); return; }
    busy(btn, "Sending");
    try{
      const j = await (await postJSON("/api/design", {project, action: "send", page: p ? p.id : 0})).json();
      if (j.error) notify(j.error, true);
      else notify(j.sent ? "sent: the session reads the saved design with bb design show"
                         : "typed into the session's input box, but not sent: press Enter there");
    }catch(e){ notify("design: " + e, true); }
    unbusy(btn, "Send to Claude");
    refreshStates();
  }

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
    nb.dsPages.forEach((p, i) => { if (nb.dsSel[keyOf(p)] != null && j.pages[i]) sel[`p${j.pages[i].id}`] = nb.dsSel[keyOf(p)]; });
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
