// The notebook's Analysis view, the code base read out, and the preamble a
// session is handed. One classic script beside index.html, the shape tab-*.js
// has (docs/nodes.md §13): one file per notebook view (R60). A factory
// makeNotebook calls per notebook.
function nbAnalysisView({$, nb, project}){
  const anaFx = {level: "", find: ""};

  async function loadAnalysis(){
    const hint = $("anaHint"), list = $("anaList");
    if (!findings || findings.error) await loadFindings(!!findings?.error);
    nb.anaStamp = state?.reports_mtime ?? null;
    if (!findings || findings.loading){ hint.textContent = "loading…"; return; }
    if (findings.error){ hint.textContent = "analysis: " + findings.error; return; }
    if (!findings.available){
      hint.textContent = "no /reports mount: the scanner runs on the host, "
        + "and its output directory is not mapped in";
      list.innerHTML = "";
      return;
    }
    const rows = [];
    for (const rep of findings.reports)
      for (const f of rep.findings)
        if (f.project === project) rows.push(f);
    const lv = {};
    rows.forEach(f => lv[f.level] = (lv[f.level] || 0) + 1);
    const stat = Object.keys(lv).sort((a, b) => (LEVEL_ORDER[a] ?? 9) - (LEVEL_ORDER[b] ?? 9))
      .map(l => `${lv[l]} ${l}${lv[l] === 1 ? "" : "s"}`).join(", ");
    hint.textContent = rows.length
      ? `${stat}: the scan runs on the host; bb findings reads the same digest`
      : "nothing attributed to this project in the current reports, which is "
        + "not the same as passing; SARIF records findings, not coverage";
    // The same two filters the Analysis tab has, project-fixed: one slice of
    // narrowing shared by both surfaces, so learning one is learning the
    // other. The bar only appears when there is something to narrow.
    const shown = fxFilter(rows, anaFx);
    list.innerHTML = (rows.length ? fxBarBand(rows, anaFx) : "")
      + (rows.length && !shown.length
          ? `<div class="empty">nothing matches the filters</div>` : "")
      + findingsRulesHtml(shown);
    fxWireBar(list, anaFx, loadAnalysis);
    // By rule group, which is how the report is read: a rule split across a
    // page boundary would separate its own occurrences.
    // .rule, which is what findingsRulesHtml emits: .grp belongs to the other,
    // per-file renderer, so this matched nothing and paginate returned early:
    // a project with hundreds of findings drew every one of them at once while
    // every list beside it paged.
    paginate(list, ":scope > .rule", {key: "anaList", noun: "rules"});
  }

  // The half of the briefing a session cannot write. Staged behind the
  // panel's Save like the memories beside them, because this is an editor:
  // somebody rewords two rules and drops a third before they are done, and
  // writing each keystroke through would be three records of one decision.
  //
  // A rule is CONDITIONAL exactly when it has a trigger. There is no kind
  // field and no picker for one: the presence of a trigger is the answer,
  // which is one fact to keep true instead of two.
  // The code base, counted (git-tracked files by language): the tab's first
  // section, above the rules. Fetched beside them; a repository's count is
  // cached by commit on the server, so this is cheap after the first time.
  let codeData = null;
  async function loadCodebase(){
    try{
      const r = await fetch("/api/codebase?project=" + encodeURIComponent(project));
      codeData = await r.json();
    }catch(e){ codeData = {error: String(e)}; }
  }
  // GitHub's colours for the languages people recognise; a hue from the
  // name for the rest, so two rare ones do not come out the same.
  const LANG_COLOR = {Python: "#3572A5", JavaScript: "#f1e05a", TypeScript: "#3178c6", HTML: "#e34c26",
    CSS: "#663399", Shell: "#89e051", Kotlin: "#A97BFF", Java: "#b07219", Dart: "#00B4AB", Swift: "#F05138",
    Go: "#00ADD8", Rust: "#dea584", C: "#555555", "C++": "#f34b7d", "C#": "#178600", Ruby: "#701516",
    PHP: "#4F5D95", SQL: "#e38c00", Dockerfile: "#384d54", Makefile: "#427819", Lua: "#000080", Zig: "#ec915c",
    Gradle: "#02303a", SCSS: "#c6538c", Nix: "#7e7eff"};
  function langColor(name){
    if (LANG_COLOR[name]) return LANG_COLOR[name];
    let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `hsl(${h} 55% 55%)`;
  }
  const nfmt = n => Number(n || 0).toLocaleString();
  function codebaseSection(){
    const d = codeData;
    let status = "counting", body = `<div class="hint">counting what git tracks…</div>`;
    if (d && d.error){ status = "no count"; body = `<div class="hint">${esc(d.error)}</div>`; }
    else if (d){
      const code = (d.languages || []).filter(l => l.kind === "code");
      const rest = (d.languages || []).filter(l => l.kind !== "code");
      status = `${nfmt(d.files)} file${d.files === 1 ? "" : "s"} · ${nfmt(d.lines)} line${d.lines === 1 ? "" : "s"}`;
      const bar = code.length
        ? `<div class="cbbar" role="img" aria-label="${esc(code.map(l => `${l.name} ${l.pct}%`).join(", "))}">${
            code.map(l => `<span style="width:${l.pct}%;background:${langColor(l.name)}" title="${esc(l.name)} ${l.pct}%"></span>`).join("")}</div>
           <div class="cblegend">${code.map(l => `<span><span class="dot" style="background:${langColor(l.name)}"></span>${esc(l.name)} <b>${l.pct}%</b><span class="n">${nfmt(l.lines)} lines in ${nfmt(l.files)}</span></span>`).join("")}</div>`
        : `<div class="hint">no code among the tracked files yet</div>`;
      const sk = d.skipped || {};
      const skipped = [sk.binary ? `${sk.binary} binar${sk.binary === 1 ? "y" : "ies"}` : "",
                       sk.vendored ? `${sk.vendored} vendored or minified` : "",
                       sk.large ? `${sk.large} over 4MB` : ""].filter(Boolean);
      body = `<div class="hint">${nfmt(d.code_lines)} lines of code in ${nfmt(d.code_files)} file${d.code_files === 1 ? "" : "s"}, tracked by git${
          d.commit ? ` at <code>${esc(d.commit.slice(0, 7))}</code>` : ""}. Nothing untracked or ignored is counted: build output, dist/, a stray archive.</div>
        ${bar}
        ${rest.length ? `<div class="hint cbfoot">Counted, not in the bar: ${rest.map(l => `${esc(l.name)} ${nfmt(l.lines)} line${l.lines === 1 ? "" : "s"}`).join(", ")}.${
          skipped.length ? ` Skipped: ${skipped.join(", ")}.` : ""}</div>`
        : skipped.length ? `<div class="hint cbfoot">Skipped: ${skipped.join(", ")}.</div>` : ""}`;
    }
    // Open on both sizes: the numbers are the answer, not a place to go and
    // look for one, and the rules under it are the fold that closes.
    return docSection("briefing", "codebase", "Code base", status, body, {open: true});
  }
  // ---- what a session is handed --------------------------------------------
  // The three stores this notebook already shows, joined into the one string
  // bb-tty puts in front of a session. Fetched rather than built here: the
  // order, the joins and the cap are preamble.py's, and a second assembly on
  // this side would be a tab that quietly stops describing what sessions get.
  nb.preData = null;
  async function loadPreamble(){
    try{
      const r = await fetch(`/api/preamble?project=${encodeURIComponent(project)}`);
      const j = await r.json();
      nb.preData = j.error ? {error: j.error} : j;
    }catch(e){ nb.preData = {error: String(e)}; }
    nb.drawRules();
  }
  const preSize = n => n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} bytes`;
  function preambleSection(){
    const d = nb.preData;
    let body, status = "", cls = "";
    if (!d){
      body = `<div class="field"><div class="sub dim">reading…</div></div>`;
    } else if (d.error){
      body = `<div class="field"><div class="hint bad">${esc(d.error)}</div></div>`;
      status = "unavailable"; cls = "bad";
    } else if (!d.text){
      status = "none";
      body = `<div class="field"><div class="sub dim">No rules, no open roadmap `
           + `items and no open bugs, so a session here starts on CLAUDE.md alone.`
           + `</div></div>`;
    } else {
      status = preSize(d.bytes); cls = d.capped ? "warn" : "";
      // Read-only, and a textarea rather than a <pre> because the thing
      // somebody wants to do with this is select all of it and take it
      // somewhere. uniform.mjs exempts a read-only textarea from the control
      // width: this is a page of text, not a field.
      body = `<div class="field">
        <div class="hint">Every session started here is handed this, on top of `
        + `the project's CLAUDE.md.</div>
        <textarea id="preText" readonly rows="16" spellcheck="false"
          aria-label="what a session started here is sent">${esc(d.text)}</textarea>
        <div class="sub dim">${
          (d.parts || []).map(x => `${esc(x.name)} ${preSize(x.bytes)}`).join(" · ")
        }${d.capped ? ` · cut at ${preSize(d.max)}, the rest is not sent` : ""}</div>
      </div>`;
    }
    return docSection("briefing", "preamble", "What a session is sent",
                      status, body, {open: false, cls});
  }

  return {loadAnalysis, loadCodebase, codebaseSection, loadPreamble, preambleSection};
}
